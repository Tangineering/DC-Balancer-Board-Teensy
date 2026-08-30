#!/usr/bin/env python3
"""
hil_electrical.py — high-fidelity electrical engine for the Teensy HIL plant.

`tools/hil_plant_sim.py` ships a deliberately simple electrical model: one droop
node, an algebraic FC/BT split, no converter and no switch dynamics.  That is the
right model for sequencing and fault-logic work, and it is what `--electrical
simple` (the default) still uses.

This module is the OPTIONAL `--electrical hifi` engine.  Its purpose is narrow and
specific: recreate the electrical failure modes the bench has actually recorded, so
they can be replayed against firmware as stimuli —

  * the TP0178 / TP0201 **handoff sag**: a source goes dark at a share rail and the
    standby ideal-diode switch only picks up REACTIVELY, after the bus has already
    sagged below its own source minus the RT1987's 35 mV forward-regulation target;
  * the Death-5 class **SCP burst-retry ring**: a hot-plug into a discharged node
    trips the RT1987's soft-start foldback, the cut dumps the load current into the
    trace parasitics, and the resulting overshoot passes the TPS61288's 20 V abs-max;
  * the **regen chopper clamp** on the regen node (TL431 + BSP170P into 47 Ω);
  * the staged **bus bring-up** (P0-P3) against the real RT1987 turn-on delays.

Everything here is an AVERAGE model, not a switching model — no 1 MHz ripple, no
inductor current state.  See "Fidelity boundaries" at the bottom of this docstring
and §"Hi-fi electrical engine" in docs/HIL_PLANT.md.

────────────────────────────────────────────────────────────────────────────────
Sources for every constant below (cited again at each definition):
  * TPS61288 datasheet §7.5 / §9.2.2.5, as already transcribed and gate-checked in
    controller_design/tps61288_full_model.py (G_EA, K_COMP, VREF, L, ω_RHPZ form).
  * Schematic 20260622 + the RC-BT bodge (CLAUDE.md "Hardware bodge record
    2026-07-10"): R_C = 61.2 kΩ on BOTH channels.
  * RD1 = 215 k FB retune, 2026-07-11 (CLAUDE.md fw v14 / §6 addenda): V0 = 15.907 V.
  * INA253A1IPWR (CLAUDE.md §5): K_sns = 0.1 V/A, 2 mΩ integrated shunt, ~350 kHz.
  * OPA197 on the 5 V rail bodge (CLAUDE.md §7): A_v = 5.02, output ceiling ~4.9 V.
  * RT1987 datasheet (references/Datasheets/RT1987_DS-00.pdf): UVLO 3.175 V, t_D(ON)
    8 ms typ, soft-start t_ON formula, foldback SCP profile, 250 µs SCP blanking,
    64 ms auto-retry, V_FWD 35 mV, R_ON 20-22 mΩ, -50 mV reverse comparator, full
    isolation when off (back-to-back FETs, no body-diode path).
  * FastHenry extraction, papers/Droop_Control/sections/05_bringup_debugging.tex
    Table~\\ref{tab:Lsweep} lines 182-183: FC 1.538 nH, BT 3.480 nH (long trace).
  * docs/boost-bringup-debug.md for the Death-5 mechanism and the ~1.3 A/ns class
    load-dump slew used in the ring estimate.

Fidelity boundaries (read before believing a number out of this engine):
  * AVERAGE model.  No switching ripple, no inductor current state, no CCM/DCM
    boundary.  The boost is the datasheet small-signal structure evaluated in the
    time domain with the nonlinearities (duty/compensator clamps, enable, OVP,
    body-diode passthrough) added back.
  * Parasitic inductance is NOT integrated.  nH against µF is a ~100 MHz natural
    frequency — unintegrable in real-time Python.  Switching-event overshoot is
    estimated ANALYTICALLY (V_peak ≈ V_node + L·di/dt) and emitted as an EVENT
    annotation, compared against the 20 V abs-max.  So the engine DETECTS the
    boost-death mechanism; it does not simulate the ringing waveform.
  * RT1987 numbers are TYPICALS.  The datasheet min/max spread is not modelled, so
    a margin that is thin here is thin in the typical part, not in the worst part.
  * The INA253 sense pole (~350 kHz) is lumped/neglected: at the achievable substep
    rate (single-digit kHz to tens of kHz) it is far outside the resolvable band.
  * Backward Euler.  The engine is L-stable, so a stiff node pair (a 22 mΩ switch
    between two ~35 µF nodes is a 0.77 µs RC) settles to the correct quasi-static
    solution instead of blowing up — but the transient itself is not resolved.
  * M6: the RT1987 SOFT-START stamp is charge-NON-CONSERVING.  Rt1987.stamp()'s
    SOFT branch drives the output node through an IMPLICIT conductance (so it
    participates correctly in the node solve) but debits the input node
    EXPLICITLY, from the previous substep's current estimate rather than the node
    solve's own current -- a deliberate stability trade (see the comment at the
    stamp site), not an oversight, and not charge-balanced within one substep. It
    matters only during the ~1-20 ms soft-start ramp itself: treat inrush current
    shape during that window as approximate, not exact (docs/HIL_PLANT.md §8.4).

Stdlib only (the parent script is stdlib-only by charter): no numpy.
"""

import math
import time

# ─────────────────────────────────────────────────────────────────────────────
# Switch bitmask — mirrors hil_plant_sim / the firmware's switch_state.
# Duplicated (rather than imported) so this module has no import-time coupling
# back to the parent script.
# ─────────────────────────────────────────────────────────────────────────────
SW_FC_BUS, SW_BT_BUS, SW_MOT_PWR = 0x01, 0x02, 0x04
SW_REGEN, SW_FC_CHARGE, SW_BT_SEQ = 0x08, 0x10, 0x20
AUX_FC_REG, AUX_BT_REG = 0x01, 0x02

# ─────────────────────────────────────────────────────────────────────────────
# TPS61288 boost — DS §7.5 / §9.2.2.5, transcribed in
# controller_design/tps61288_full_model.py lines 61-77 (gate-checked there).
# ─────────────────────────────────────────────────────────────────────────────
VREF = 0.6              # V     FB reference
G_EA = 180e-6           # S     error-amplifier transconductance
K_COMP = 13.5           # A/V   power-stage transconductance
L_BOOST = 2.2e-6        # H     inductor
R_EA = 10e6             # ohm   EA output resistance (finite-gain term)
R_C = 61.2e3            # ohm   compensator zero resistor — BOTH channels post the
                        #       2026-07-10 RC-BT bodge (schematic still shows 27.4 k)
C_C = 2e-9              # F     compensator zero cap
C_P = 27e-12            # F     COMP-pin pole cap
V_COMP_MAX = 2.4        # V     COMP clamp (average-model saturation ceiling)
V_OVP_TRIP = 19.0       # V     TPS61288 hardware OVP (CLAUDE.md §6: "confirmed 19 V")
V_ABSMAX = 20.0         # V     abs-max the ring estimate is compared against
V_BODY_DIODE = 0.55     # V     disabled-boost passthrough drop (Vin -> Vout)
R_BODY_DIODE = 0.15     # ohm   its series resistance   TODO(verify): not extracted

# ─────────────────────────────────────────────────────────────────────────────
# Droop chain — CLAUDE.md §5/§7 + the RD1 = 215 k retune.
# ─────────────────────────────────────────────────────────────────────────────
K_SNS = 0.1             # V/A   INA253A1IPWR (the A3 was intended; A1 was fitted)
A_V = 5.02              # OPA197 non-inverting gain 1 + 40.2k/10k
V_OP_CEIL = 4.9         # V     OPA197 output ceiling on the bodged 5 V rail
R_D1 = 215e3            # ohm   FB top (bodge; schematic shows 237 k)
R_D2 = 10e3             # ohm   FB bottom
R_INJ = 53.6e3          # ohm   droop injection resistor
R_SHUNT = 2e-3          # ohm   INA253 integrated shunt (a fixed physical droop)
RE_MAX = K_SNS * A_V * R_D1 / R_INJ          # 2.014 ohm at g = 1
_P_PAR = R_D2 * R_INJ / (R_D2 + R_INJ)
H1 = _P_PAR / (R_D1 + _P_PAR)                # FB gain from the boost output node
H2 = H1 * R_D1 / R_INJ                       # FB gain from the op-amp injection
V0_NOLOAD = VREF * (1.0 + R_D1 / R_D2 + R_D1 / R_INJ)   # 15.907 V

# ─────────────────────────────────────────────────────────────────────────────
# RT1987 ideal-diode controller — datasheet typicals.
# ─────────────────────────────────────────────────────────────────────────────
RT_UVLO_V = 3.175       # V     VIN below this = OFF (full isolation)
RT_TD_ON_S = 8e-3       # s     EN-rise to soft-start delay, typ
RT_R_ON = 0.021         # ohm   20-22 mOhm fully enhanced
RT_V_FWD = 0.035        # V     forward-regulation target (the handoff-gap element)
RT_V_REV = -0.050       # V     reverse comparator threshold
RT_SCP_BLANK_S = 250e-6  # s    continuous clamp time before a CUT
RT_SCP_RETRY_S = 64e-3  # s     auto-retry after a CUT
RT_I_FOLD_LOW = 2.5     # A     limit while VOUT < 2 V rising
RT_I_FOLD_HIGH = 8.5    # A     limit at dV <= 5 V
RT_DV_FOLD_KNEE = 5.0   # V     dV at which the limit reaches RT_I_FOLD_HIGH

# Soft-start capacitors per switch (schematic 20260622).
CSS_NF = {
    "FC_BUS": 100.0, "BT_BUS": 100.0, "MOT_PWR": 100.0,
    "REGEN": 5.6, "FC_CHARGE": 5.6, "BT_SEQ": 5.6,
}


def rt1987_t_on_s(v_in, css_nf):
    """RT1987 soft-start time: tON = (VIN/35)*(CSS_nF/0.0023 - 100) us (datasheet)."""
    if v_in <= 0.0:
        return 0.0
    return (v_in / 35.0) * (css_nf / 0.0023 - 100.0) * 1e-6


def rt1987_fold_limit(dv):
    """Foldback current limit vs the switch's VIN-VOUT differential [A].

    L2 fix: this docstring previously said "2.5 A while VOUT < 2 V rising", which
    contradicts the code below (and docs/HIL_PLANT.md, which already agreed with
    the code, not the old docstring).  The actual profile: 8.5 A while dV <= 5 V,
    interpolated linearly DOWN as dV rises past the 5 V knee (reaching ~5.3 A at
    dV = 16 V), continuing to fall until it hits the RT_I_FOLD_LOW = 2.5 A floor
    (at dV ~= 25.6 V on this slope) and staying there for any larger dV.
    """
    if dv <= RT_DV_FOLD_KNEE:
        return RT_I_FOLD_HIGH
    # Linear from (5 V, 8.5 A) toward (16 V, ~5.3 A) and clamped at RT_I_FOLD_LOW.
    slope = (5.3 - RT_I_FOLD_HIGH) / (16.0 - RT_DV_FOLD_KNEE)
    return max(RT_I_FOLD_LOW, RT_I_FOLD_HIGH + slope * (dv - RT_DV_FOLD_KNEE))


# ─────────────────────────────────────────────────────────────────────────────
# Node capacitances (states of the ODE).  Schematic 20260622 + bodge caps.
# ─────────────────────────────────────────────────────────────────────────────
C_BOOST_OUT_FC = 30e-6      # F  derated per-channel boost output bulk
C_BOOST_OUT_BT = 40.1e-6    # F  +10.1 uF from the BT bodge caps
C_VBUS = 35e-6              # F  VBUS proper (30-40 uF band, midpoint)
C_MOT_LOCAL = 470e-6        # F  the 470 uF behind MOT_PWR
ESR_MOT = 0.080             # ohm  its ESR
C_VESC_DEFAULT = 0.5e-3     # F  VESC input, 0.2-0.9 mF envelope
C_CHG_NODE = 10e-6          # F  TODO(verify): no separate charger-input cap identified
C_RGN_NODE = 10e-6          # F  TODO(verify): likewise

R_NODE_BLEED = 2000.0       # ohm  effective bleed on every node (dark-node decay)
V_MOT_LOAD_FLOOR = 1.0      # V    floor for the H1 motor-draw/regen Norton
                            #      conductance (i_motor / max(v_node, this)) so the
                            #      element cannot divide by (or explode near) zero
                            #      when V-MOT is dark
V_NODE_RUNAWAY_MULT = 2.0   # x V_ABSMAX  hard backstop: a node past this after a
                            #      substep solve is a solver artefact, not a
                            #      plausible physical state on this rig (H1)

# Regen chopper — TL431 + BSP170P into 47 Ω / 20 W, autonomous (no firmware control).
# Clamp level CALIBRATED from bench observation (operator, 2026-08-27): sustained regen
# drove V_rgn 13.3 -> 18.1 V with the chopper holding 18.1 V (CLAUDE.md 2026-08-17b);
# the 16.5 V TODO(calibrate) placeholder is retired.  The point of simulating the
# chopper is the POWER question: does dissipation in the 47 Ω dump resistor ever
# exceed its 20 W rating?  At the 18.1 V clamp V²/R = 6.97 W steady — the rating is
# only reachable through excursions past sqrt(20*47) ≈ 30.7 V — so the engine tracks
# per-substep dissipation, keeps the worst value, and emits a chopper_over_power
# event (once per excursion) if it crosses P_CHOPPER_MAX_W.
V_CHOPPER_TRIP = 18.1       # V     bench-calibrated clamp level (see above)
R_CHOPPER = 47.0            # ohm   47 Ω dump resistor
P_CHOPPER_MAX_W = 20.0      # W     resistor power rating (BOM R-SHUNT, 20 W)

# Sources — see the SOURCE MODELS block further down (FuelCellSource /
# BatterySource).  These remain as the fallback/legacy scalars: V_FC_OPEN is the
# rig's known open-circuit class and R_FC_INT the effective IR sag the source model
# is FITTED to reproduce.
V_FC_OPEN = 13.0            # V     H-20 fuel cell, open-circuit class
R_FC_INT = 0.45             # ohm   effective bench IR sag  TODO(calibrate)
V_BT_OPEN = 8.0             # V     2S LiPo mid-charge (SOC ~0.7 on the OCV curve)
R_BT_INT = 0.05             # ohm   TODO(verify)
I_AUX_A = 0.15              # A     housekeeping load on VBUS
ETA_BOOST = 0.85            # boost efficiency, used to refer output current to the
                            # source side (SOC bookkeeping and IR sag are INPUT-side)

# ─────────────────────────────────────────────────────────────────────────────
# Trace parasitics — FastHenry, 05_bringup_debugging.tex Table Lsweep (lines 182-183).
# NOT integrated (see the module docstring); used only for the analytic ring estimate.
# ─────────────────────────────────────────────────────────────────────────────
TRACE_L_NH = {
    # as-manufactured long output loops
    "long": {"FC": 1.538, "BT": 3.480, "OTHER": 2.5},
    # post-bodge short routing.  NO extraction exists for the reworked loops; both are
    # assumed FC-like.  TODO(verify): needs its own FastHenry run.
    "short": {"FC": 1.5, "BT": 1.5, "OTHER": 1.5},
}
DI_DT_LOAD_DUMP = 1.3e9     # A/s  ~1.3 A/ns class slew on an SCP cut
                            #      (docs/boost-bringup-debug.md, Death-5 analysis).
                            #      L1: this is a FIXED WORST-CASE bound applied
                            #      regardless of the actual cut current i_cut -- no
                            #      scaling law vs i_cut is documented anywhere in
                            #      this repo, so none is invented here.  Treat the
                            #      resulting peak_v as "at least this bad", not a
                            #      current-dependent prediction.

# ─────────────────────────────────────────────────────────────────────────────
# ADC quantization — computed from the firmware's own scale constants
# (teensy_controller.ino lines 1128-1144): ADC_VREF 3.3 V, ADC_MAX 4095,
# K_sns 0.1 V/A, dividers as listed.
# ─────────────────────────────────────────────────────────────────────────────
_ADC_VREF, _ADC_MAX = 3.3, 4095.0
LSB_V_FC = _ADC_VREF * (27.4 + 10.0) / 10.0 / _ADC_MAX     # ~3.01 mV/count
LSB_V_BATT = _ADC_VREF * (16.2 + 10.0) / 10.0 / _ADC_MAX   # ~2.11 mV/count
LSB_V_BUS = _ADC_VREF * (46.4 + 10.0) / 10.0 / _ADC_MAX    # ~4.55 mV/count
LSB_V_CHG = _ADC_VREF * (78.7 + 10.0) / 10.0 / _ADC_MAX    # ~7.15 mV/count
LSB_V_RGN = LSB_V_CHG                                      # same divider
LSB_I = _ADC_VREF / _ADC_MAX / K_SNS                       # 8.06 mA/count

INA_ZERO_OFFSET_A = 0.02    # A  MEASURED (2026-08-27, per-log minimum mean with the bus
                            # live, 201 logs): I_fc +0.0199 A median (~2.5 counts) —
                            # this default is the FC-CHANNEL figure.  I_batt shows NO
                            # measurable positive offset (+0.0002 A median; clipped at
                            # 0, so a small negative offset cannot be excluded).  The
                            # two fitted parts are ASYMMETRIC — NoiseConfig defaults to
                            # a per-channel dict {"I_fc": 0.020, "I_batt": 0.0}.


class NoiseConfig:
    """Additive noise applied to the INJECTED values (never to internal states).

    Quantization is real and computed from the firmware's scale constants.  The
    gaussian sigmas default to ZERO (a noise-free run stays deterministic); the
    `suggested()` classmethod carries the per-rail sigmas MEASURED from the
    bench-log corpus (2026-08-27).  `ina_zero_offset` is a per-channel dict —
    the two fitted INA253A1s measured ASYMMETRIC (see INA_ZERO_OFFSET_A); a
    plain float is accepted for back-compat and applied to both channels.
    """

    def __init__(self, quantize=True, sigma=None, ina_zero_offset=None,
                 seed=None):
        self.quantize = quantize
        self.sigma = dict(sigma or {})
        if ina_zero_offset is None:
            # Measured defaults (2026-08-27): FC channel +20 mA, BT channel none.
            self.ina_zero_offset = {"I_fc": INA_ZERO_OFFSET_A, "I_batt": 0.0}
        elif isinstance(ina_zero_offset, dict):
            self.ina_zero_offset = dict(ina_zero_offset)
        else:
            self.ina_zero_offset = {"I_fc": float(ina_zero_offset),
                                    "I_batt": float(ina_zero_offset)}
        import random
        self._rng = random.Random(seed)

    @classmethod
    def suggested(cls, **kw):
        """Per-rail gaussian sigmas MEASURED from the bench-log corpus (2026-08-27).

        Method: all 206 logs/*.BLG, 1 s windows detrended with a 75 ms moving
        mean, residual std over quiescent plateaus only (moving-mean p-p gate),
        bus-live (V_bus > 10 V) so unpowered 0-count windows are excluded.
        Values are the ADDITIVE (pre-quantization) component
        sqrt(sd^2 - LSB^2/12), since apply() quantizes AFTER adding noise.
        Residuals are white (|lag-1 acf| < 0.06) in every channel.

          V_fc   0.019  -- 6.3 LSB, gaussian (kurt 3.0), the noisiest rail by ~8x
                           in LSB terms: genuine analog noise on the FC sense
                           path, worth a scope look (it feeds the share loop).
                           Batch-dependent: 0.0186 (<153) / 0.0209 (153-180
                           supply swap) / 0.0158 (>180).  Load-independent.
          V_batt 0.0024 -- 1.2 LSB, quantization-dominated (kurt ~7).  LOAD-
                           DEPENDENT: reaches ~0.020 under pack sag; this is the
                           quiescent sensor floor only.
          V_bus  0.0018 -- 0.49 LSB, near the LSB/sqrt(12) floor; the most
                           consistent channel (201 logs, both supply batches).
          V_chg  0.004  -- NOT MEASURABLE: the charger path is unpowered in every
                           logged run, so the channel is pinned at 0 counts and
                           negative noise is censored (kurt 272).  Adopted from
                           V_rgn, which shares the identical 78.7k/10k divider.
                           TODO(verify) once a charge run is logged.
          V_rgn  0.0040 -- 0.63 LSB, measured at a real 13.3-13.5 V level (not
                           clipped).  Heavy-tailed (kurt ~6), so a pure gaussian
                           slightly understates its excursions.
          I_fc / I_batt 0.0044 -- 0.6 LSB, both channels agree (4.9 / 5.2 mA raw)
                           in the 5-30 mA band.  Above ~80 mA the observed std
                           grows to 12-57 mA, but that is boost ripple and
                           share-loop dither, NOT sensor noise -- deliberately
                           excluded (ripple physics belongs to the electrical
                           engine, not this sensor-noise model).
        """
        return cls(sigma={
            "V_fc": 0.019, "V_batt": 0.0024, "V_bus": 0.0018,
            "V_chg": 0.004, "V_rgn": 0.0040,
            "I_fc": 0.0044, "I_batt": 0.0044,
        }, **kw)

    def apply(self, rails):
        out = dict(rails)
        lsb = {"V_fc": LSB_V_FC, "V_batt": LSB_V_BATT, "V_bus": LSB_V_BUS,
               "V_chg": LSB_V_CHG, "V_rgn": LSB_V_RGN,
               "I_fc": LSB_I, "I_batt": LSB_I}
        for key, step in lsb.items():
            val = out[key]
            if key in ("I_fc", "I_batt"):
                val += self.ina_zero_offset.get(key, 0.0)
            s = self.sigma.get(key, 0.0)
            if s:
                val += self._rng.gauss(0.0, s)
            if self.quantize and step > 0:
                val = math.floor(val / step + 0.5) * step
            # The firmware's ADC path cannot produce a negative reading: the INA253s
            # run 0-referenced (CLAUDE.md §5) and the dividers are unipolar.
            out[key] = max(0.0, val)
        return out


# ═════════════════════════════════════════════════════════════════════════════
# SOURCE MODELS — PEM fuel-cell stack and 2S LiPo pack
#
# Structure and parameter names follow:
#   S. Yadav and F. Assadian, "Robust Energy Management of Fuel Cell Hybrid
#   Electric Vehicles Using Fuzzy Logic Integrated with H-Infinity Control",
#   Energies 2025, 18, 2107 (references/ in this repo).
#     * Fuel cell  — §2.1: Nernst potential Eq. (3), activation Eq. (4),
#       concentration Eq. (5), ohmic Eq. (6), terminal cell voltage Eq. (7),
#       double-layer RC Eq. (11), stack voltage Eq. (12).  This is the
#       Dicks-Larminie dynamic form the paper cites.
#     * Battery    — §2.2: equivalent-circuit model, terminal voltage Eq. (13),
#       RC-pair dynamics Eq. (14), SOC coulomb count Eq. (15), output Eq. (16),
#       with SOC-dependent lookups Em(SOC), Rs(SOC), Rn(SOC), Cn(SOC).
#
# The paper's NUMERIC parameters are for a vehicle-scale stack and pack.  This rig
# is an H-20 class ~13 V stack and a 2S RC LiPo, so the model FORM is the paper's
# and the parameters are fitted to the rig's only known points: ~13 V open circuit,
# the ~0.45 ohm effective bench IR sag, and LIMIT_V_FC_MIN 6.0 V / the 7.4-8.4 V
# battery operating band (CLAUDE.md).  Every rig-specific value below is marked
# TODO(calibrate) — none of them is measured.
#
# One instance of each is SHARED between the two electrical modes: Plant owns them
# and passes them to ElectricalSim, so `--electrical simple` and `--electrical hifi`
# integrate the SAME source state (and the same SOC) and a scenario behaves the same
# way in both.  See docs/HIL_PLANT.md "Source models".
#
# L6 FIDELITY BOUNDARY: the current fed to these models (self.i_fc / self.i_bt,
# set from self.switches["FC_BUS"].i / ["BT_BUS"].i in _substep()) is the IDEAL-
# DIODE SWITCH LINK current, not the boost's own input draw.  With a boost enabled
# but its bus switch OPEN -- the bring-up scenario's operating condition, and any
# scenario stage where a channel is regulating but not yet feeding the bus -- the
# switch carries zero current, so these source models see zero draw even though
# the boost itself may be drawing from the source.  Deliberate (the switch link is
# the only current this network solves for on that side), but it means FC/SOC
# dynamics during an enabled-but-unbussed boost stage are NOT modelled here.
# ═════════════════════════════════════════════════════════════════════════════

# ── Fuel cell (paper §2.1) ───────────────────────────────────────────────────
FC_E_NERNST = 1.15          # V/cell  Eq. (3) at nominal partial pressures.  The
                            # reactant-flow states Eqs. (8)-(10) are NOT modelled:
                            # this rig has no flow instrumentation, so E is held at
                            # the paper's Gibbs-free-energy value.  TODO(calibrate)
FC_N_CELLS = 12             # fitted so N*Vcell(0) = 12.97 V ~ the 13 V OC class
FC_AREA_CM2 = 3.0           # cm^2   TODO(calibrate): not measured on the H-20
FC_TAU_S = 0.020            # s      double-layer time constant Ra*C of Eq. (11).
                            # TODO(calibrate) — this is what makes a fast load step
                            # sag and then recover, the TP0178 transient territory.
FC_R_SERIES_RIG = 0.41      # ohm    rig wiring/contact resistance ADDED to the
                            # paper's stack model.  The paper's Eq. (4)/(6) terms
                            # give only ~0.04 ohm at this cell area, while the bench
                            # sees ~0.45 ohm total; the balance is rig harness, not
                            # electrochemistry.  TODO(calibrate)


def fc_v_act(i_a, area_cm2=FC_AREA_CM2):
    """Activation loss, paper Eq. (4): Vact = 0.0268*log((I/A + 1)/0.0027)."""
    return 0.0268 * math.log10((max(i_a, 0.0) / area_cm2 + 1.0) / 0.0027)


def fc_v_conc(i_a, area_cm2=FC_AREA_CM2):
    """Concentration loss, paper Eq. (5): Vconc = -0.05*log(1 - (I/A + 1)/1500)."""
    x = (max(i_a, 0.0) / area_cm2 + 1.0) / 1500.0
    return -0.05 * math.log10(max(1e-6, 1.0 - min(x, 0.999999)))


def fc_v_ohmic(i_a, area_cm2=FC_AREA_CM2):
    """Ohmic loss, paper Eq. (6): Vohmic = (I/A + 1)*30e-5."""
    return (max(i_a, 0.0) / area_cm2 + 1.0) * 30e-5


class FuelCellSource:
    """PEM stack, paper §2.1 form, fitted to the rig's H-20 class operating points.

    Terminal voltage (paper Eq. (12), plus the rig harness term):

        V_stack = N*(E - Va - Vohmic(I)) - R_SERIES_RIG*I

    where Va is the double-layer state of Eq. (11).  The paper writes that state as
    dVa/dt = I/(A*C) - Va/(Ra*C), whose equilibrium is the linear I*Ra/A; here the
    equilibrium is instead the NONLINEAR activation + concentration pair of
    Eqs. (4)-(5), so the polarization curve keeps its Tafel and concentration
    regions while the RC branch supplies the same first-order dynamics:

        dVa/dt = (Vact(I) + Vconc(I) - Va) / FC_TAU_S

    Consequence, and the reason this model is here at all: a fast load step is met
    at first with only the ohmic loss and then sags over FC_TAU_S as the activation
    overpotential builds — the shape the TP0178 "loose FC supply" hypothesis is
    about (docs/boost-bringup-debug.md).
    """

    def __init__(self, n_cells=FC_N_CELLS, area_cm2=FC_AREA_CM2, tau_s=FC_TAU_S,
                 r_series=FC_R_SERIES_RIG, health=1.0):
        if tau_s <= 0.0:
            # L3: tau_s divides update()'s dt/tau_s term -- 0 (or negative) is a
            # ZeroDivisionError (or a sign-flipped, unstable double-layer state)
            # rather than a caught, explained failure.
            raise ValueError(f"FuelCellSource tau_s must be > 0, got {tau_s!r}")
        self.n_cells = n_cells
        self.area_cm2 = area_cm2
        self.tau_s = tau_s
        self.r_series = r_series
        self.health = health          # 1.0 = nominal; scenarios derate the stack
        self.v_a = fc_v_act(0.0, area_cm2) + fc_v_conc(0.0, area_cm2)
        self.v_terminal = self.open_circuit()
        self.i = 0.0

    def open_circuit(self):
        v_cell = FC_E_NERNST - fc_v_act(0.0, self.area_cm2) \
            - fc_v_conc(0.0, self.area_cm2) - fc_v_ohmic(0.0, self.area_cm2)
        return self.health * self.n_cells * v_cell

    def update(self, dt, i_a):
        """Advance the double-layer state and return the terminal voltage [V]."""
        i_a = max(0.0, i_a)
        self.i = i_a
        v_eq = fc_v_act(i_a, self.area_cm2) + fc_v_conc(i_a, self.area_cm2)
        self.v_a += (v_eq - self.v_a) * min(1.0, dt / self.tau_s)
        v = self.n_cells * (FC_E_NERNST - self.v_a - fc_v_ohmic(i_a, self.area_cm2))
        self.v_terminal = max(0.0, self.health * v - self.r_series * i_a)
        return self.v_terminal


# ── Battery (paper §2.2) ─────────────────────────────────────────────────────
# Generic 2S LiPo OCV curve, PER CELL.  No pack characterization exists in this
# repo, so this is a standard LiPo discharge shape, NOT a measurement of the fitted
# pack: TODO(calibrate).  It does respect the 7.4-8.4 V operating band the
# 2026-07-10 system decision set (CLAUDE.md "Hardware bodge record 2026-07-10").
LIPO_OCV_SOC = (0.00, 0.05, 0.10, 0.20, 0.40, 0.60, 0.80, 0.90, 1.00)
LIPO_OCV_V = (3.30, 3.50, 3.60, 3.70, 3.78, 3.87, 3.99, 4.06, 4.20)
BATT_CELLS = 2              # 2S (CLAUDE.md §6)
BATT_CAPACITY_AH = 5.0      # Ah   plausible 2S RC pack   TODO(verify)
BATT_RS_NOM = 0.040         # ohm  Rs(SOC) mid-band       TODO(calibrate)
BATT_R1 = 0.020             # ohm  single RC pair, Eq. (14)  TODO(calibrate)
BATT_C1 = 200.0             # F    tau ~ 4 s                 TODO(calibrate)


def _interp(xs, ys, x):
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for k in range(1, len(xs)):
        if x <= xs[k]:
            f = (x - xs[k - 1]) / (xs[k] - xs[k - 1])
            return ys[k - 1] + f * (ys[k] - ys[k - 1])
    return ys[-1]


class BatterySource:
    """2S LiPo pack, paper §2.2 equivalent-circuit form.

        V_T = Em(SOC) - I*Rs(SOC) - V1          (Eq. 13, one RC pair)
        dV1/dt = I/C1 - V1/(R1*C1)              (Eq. 14)
        SOC   -= (1/Cbatt) * integral(I dt)     (Eq. 15; I > 0 = DISCHARGE)

    The sign convention is the paper's: positive current discharges, negative
    current charges.  The Ag105's charge current therefore enters as a NEGATIVE
    battery current, which is what makes a long `charge-cruise` run visibly raise
    V_batt along the OCV curve.
    """

    def __init__(self, soc0=0.7, capacity_ah=BATT_CAPACITY_AH, cells=BATT_CELLS):
        if capacity_ah <= 0.0:
            # L3: capacity_as divides update()'s coulomb-count term -- 0 (or
            # negative) is a ZeroDivisionError rather than a caught, explained
            # failure.
            raise ValueError(f"BatterySource capacity_ah must be > 0, got {capacity_ah!r}")
        self.soc = min(1.0, max(0.0, soc0))
        self.capacity_as = capacity_ah * 3600.0
        self.cells = cells
        self.v1 = 0.0
        self.i = 0.0
        self.v_terminal = self.ocv()

    def ocv(self):
        return self.cells * _interp(LIPO_OCV_SOC, LIPO_OCV_V, self.soc)

    def rs(self):
        # Rs(SOC): flat mid-band, rising steeply as the pack empties.  TODO(calibrate)
        k = 1.0 if self.soc > 0.15 else (1.0 + 3.0 * (0.15 - self.soc) / 0.15)
        return self.cells * BATT_RS_NOM * k

    def update(self, dt, i_a):
        """Advance SOC and the RC pair; return the terminal voltage [V].

        `i_a` is the NET pack current: positive discharges, negative charges.
        """
        self.i = i_a
        self.soc = min(1.0, max(0.0, self.soc - (i_a * dt) / self.capacity_as))
        tau = BATT_R1 * BATT_C1
        self.v1 += (i_a * BATT_R1 - self.v1) * min(1.0, dt / tau)
        self.v_terminal = max(0.0, self.ocv() - i_a * self.rs() - self.v1)
        return self.v_terminal


# ─────────────────────────────────────────────────────────────────────────────
# Small dense linear solve (Gaussian elimination, partial pivoting).  n = 6 here,
# so ~72 multiply-adds — cheap enough to run inside the substep loop.
# ─────────────────────────────────────────────────────────────────────────────
def _solve(A, b):
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-18:
            M[col][col] += 1e-12          # singular guard: an isolated dark node
            piv = col
        if piv != col:
            M[col], M[piv] = M[piv], M[col]
        inv = 1.0 / M[col][col]
        for r in range(col + 1, n):
            f = M[r][col] * inv
            if f:
                for c in range(col, n + 1):
                    M[r][c] -= f * M[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        acc = M[r][n]
        for c in range(r + 1, n):
            acc -= M[r][c] * x[c]
        x[r] = acc / M[r][r]
    return x


# Node indices of the electrical network.
# N_RGN is RETIRED as a physical node (2026-08-30 topology fix): the regen node
# IS V-MOT (RGN-V divider + chopper sit upstream of the REGEN switch, whose
# output joins FC_CHARGE's at the shared N_CHG / VCHG-IN node).  The index is
# kept so the matrix dimensions and node-name lists stay stable; the node has no
# links and bleeds to 0.
N_OFC, N_OBT, N_BUS, N_MOT, N_CHG, N_RGN = range(6)
N_NODES = 6
_NODE_NAMES = ["OFC", "OBT", "BUS", "MOT", "CHG", "RGN"]


class Rt1987:
    """One RT1987 ideal-diode switch as a time-domain state machine.

    States: OFF (full isolation — back-to-back FETs, NO body-diode path),
    TD_ON (8 ms EN-rise delay), SOFT (soft-start ramp with foldback SCP active),
    ON (forward regulation servo + fast reverse comparator).
    """

    def __init__(self, name, n_in, n_out, css_nf, c_load_f, r_series=0.0):
        self.name = name
        self.n_in = n_in
        self.n_out = n_out
        self.css_nf = css_nf
        self.c_load = c_load_f      # downstream capacitance, for the ramp-rate limit
        self.r_series = r_series    # extra fixed series R (the INA shunt on boost links)
        self.state = "OFF"
        self.t_state = 0.0          # s in the current state
        self.t_clamped = 0.0        # s continuously at the foldback limit
        self.t_retry = 0.0          # s since a CUT
        self.i = 0.0                # A last-substep current (in -> out)
        self.cut_count = 0
        self.v_ss_start = 0.0       # V  output voltage at soft-start entry
        self._fold_active = False
        self._restart_no_ss = False

    # -- stamping -----------------------------------------------------------
    def stamp(self, G, J, v, en):
        """Add this switch's contribution to (G, J) for the coming substep.

        Semi-implicit: the conduction MODE is chosen from the previous substep's
        node voltages/current, then stamped as a linear element (conductance +
        Norton source) so the node solve stays linear.
        """
        v_in, v_out = v[self.n_in], v[self.n_out]
        if self.state in ("OFF", "TD_ON"):
            return                                   # full isolation, nothing to stamp
        if self.state == "SOFT":
            # Soft-start: the pass FET's gate is ramped so VOUT FOLLOWS a linear
            # ramp toward VIN.  It is a CONTROLLED SOURCE on the output node, not a
            # resistor to the input node — stamping it as a resistor-plus-offset
            # referenced to the PREVIOUS v_in is what made the first version diverge
            # (the implicit conductance term moved v_in inside the solve while the
            # explicit offset did not, injecting a fictitious ~1400 A into the bus).
            # So: drive n_out toward `target` through the pass resistance, and take
            # the same current out of n_in explicitly.  The input node here is a
            # stiff regulated boost output, so the explicit half is well behaved.
            i_fold, i_res, target = self._soft_operating_point(v_in, v_out)
            r = RT_R_ON + self.r_series
            if i_res > i_fold:
                # Foldback binding: an EQUIVALENT RESISTANCE that delivers the limit
                # at the present differential, not an ideal current source (an ideal
                # source into a 30 uF node is unbounded within one substep).
                r = max(r, (target - v_out) / max(i_fold, 1e-6))
            g = 1.0 / r
            G[self.n_out][self.n_out] += g
            J[self.n_out] += g * target
            J[self.n_in] -= min(i_fold, max(0.0, i_res))
            return
        # ON: forward branch with the 35 mV regulation offset, i = (dv - V_FWD)/R.
        r = RT_R_ON + self.r_series
        g = 1.0 / r
        G[self.n_in][self.n_in] += g
        G[self.n_out][self.n_out] += g
        G[self.n_in][self.n_out] -= g
        G[self.n_out][self.n_in] -= g
        off = RT_V_FWD / r
        J[self.n_in] += off        # the offset opposes forward conduction
        J[self.n_out] -= off

    def _soft_operating_point(self, v_in, v_out):
        """Return (foldback limit, resistive-branch current, ramp target) [A, A, V].

        The ramp target is the RT1987's soft-start VOUT profile: a linear ramp from
        the output's starting voltage to VIN over
        tON = (VIN/35)*(CSS_nF/0.0023 - 100) us (datasheet).  With CSS = 100 nF that
        is ~19.8 ms at 16 V; with 5.6 nF, ~1.07 ms.
        """
        t_on = rt1987_t_on_s(max(v_in, 1.0), self.css_nf)
        frac = 1.0 if t_on <= 0 else min(1.0, self.t_state / t_on)
        target = self.v_ss_start + (v_in - self.v_ss_start) * frac
        dv = max(0.0, v_in - v_out)
        i_fold = rt1987_fold_limit(dv)
        i_res = max(0.0, (target - v_out)) / (RT_R_ON + self.r_series)
        self._fold_active = i_res > i_fold
        return i_fold, i_res, target

    # -- advance ------------------------------------------------------------
    def update(self, dt, v, en, events, t_now, trace_l_nh):
        v_in, v_out = v[self.n_in], v[self.n_out]
        self.t_state += dt
        # Measured current for the ON branch (used by the reverse comparator and
        # by the ring estimate); in SOFT it is the limit that was stamped.
        if self.state == "ON":
            self.i = max(0.0, (v_in - v_out - RT_V_FWD) / (RT_R_ON + self.r_series))
        elif self.state == "SOFT":
            i_fold, i_res, _t = self._soft_operating_point(v_in, v_out)
            self.i = min(i_fold, i_res)
        else:
            self.i = 0.0

        powered = v_in >= RT_UVLO_V
        if not en or not powered:
            if self.state != "OFF":
                self._open(events, t_now, trace_l_nh, v_out, "en_low" if not en else "uvlo")
            else:
                # H2 fix: _open() is the ONLY other site that clears _restart_no_ss,
                # and it only runs when leaving a non-OFF state.  If the switch was
                # already OFF-with-reverse-block-pending (set by the ON-state reverse
                # comparator branch below) when EN goes low or VIN drops under UVLO,
                # this branch used to be a no-op and the flag survived the EN cycle --
                # so a FRESH enable into a discharged node would skip BOTH TD_ON and
                # soft-start, defeating the very foldback this engine exists to
                # exercise.  Clear it here too, unconditionally, on any EN-low/
                # unpowered transition.  Documented semantics are unchanged: a
                # reverse-blocked, STILL-ENABLED switch re-arms without soft-start;
                # a power/EN cycle in between forces a full TD_ON + soft-start restart.
                self._restart_no_ss = False
                self.t_state = 0.0
            # M1 fix: the 64 ms SCP auto-retry timer decrement lives below this
            # early return, so an EN-low (or UVLO) window used to FREEZE t_retry
            # instead of letting it run -- the real RT1987 resets on an EN cycle (a
            # power-down/up is a stronger event than a mere timeout elapsing), so a
            # latched retry must not survive being power-cycled.  Chosen semantics,
            # documented here: EN-cycle RESETS the retry timer outright, rather than
            # "decrement unconditionally" (which would let time silently pass while
            # unpowered and could make a retry appear to elapse faster than the part
            # would ever observe with EN genuinely low the whole time).
            self.t_retry = 0.0
            return

        if self.state == "OFF":
            if self.t_retry > 0.0:
                self.t_retry = max(0.0, self.t_retry - dt)
                if self.t_retry > 0.0:
                    return
            if self._restart_no_ss:
                # Reverse-blocked, not powered down: the RT1987 re-arms WITHOUT a
                # new t_D(ON) + soft-start cycle as soon as it is forward again.
                # This is exactly the reactive standby-diode pickup that produces
                # the TP0178/TP0201 handoff gap, so it must not be turned into an
                # 8 ms restart.
                if (v_in - v_out) > RT_V_FWD:
                    self._restart_no_ss = False
                    self._goto("ON")
                return
            self._goto("TD_ON")
        elif self.state == "TD_ON":
            if self.t_state >= RT_TD_ON_S:
                self._goto("SOFT", v_out)
        elif self.state == "SOFT":
            # SCP: the foldback clamp (not the ramp limiter) held continuously for
            # 250 us trips a CUT with a 64 ms auto-retry.
            if getattr(self, "_fold_active", False) and (v_in - v_out) > 1.0:
                self.t_clamped += dt
            else:
                self.t_clamped = 0.0
            if self.t_clamped >= RT_SCP_BLANK_S:
                self.cut_count += 1
                self._open(events, t_now, trace_l_nh, v_out, "scp_cut")
                self.t_retry = RT_SCP_RETRY_S
                return
            # Soft-start complete when the ramp has run out AND the differential has
            # collapsed into the forward-regulation band.
            t_on = rt1987_t_on_s(max(v_in, 1.0), self.css_nf)
            if self.t_state >= t_on and (v_in - v_out) <= RT_V_FWD * 2.0:
                self._goto("ON")
        elif self.state == "ON":
            # Fast reverse comparator: off within 0.5 us, auto-restart WITHOUT
            # soft-start once forward again.
            if (v_in - v_out) < RT_V_REV:
                events.append({"t": t_now, "kind": "reverse_block", "switch": self.name,
                               "dv": v_in - v_out})
                self.state = "OFF"
                self.t_state = 0.0
                self.t_retry = 0.0
                self._restart_no_ss = True

    def _goto(self, state, v_out=0.0):
        if state == "SOFT":
            self.v_ss_start = v_out
        self.state = state
        self.t_state = 0.0
        self.t_clamped = 0.0
        self._fold_active = False

    def _open(self, events, t_now, trace_l_nh, v_node, reason):
        """Open the switch and emit the ANALYTIC parasitic-ring estimate.

        The nH-µF loop is not integrated (see the module docstring).  The energy
        that would ring is estimated as V_peak = V_node + L*di/dt with di/dt taken
        from the load-dump slew class, and compared against the 20 V abs-max.  A
        peak over abs-max is the Death-5 boost-kill signature.
        """
        i_before = self.i
        if i_before > 0.05:
            l_h = trace_l_nh * 1e-9
            peak = v_node + l_h * DI_DT_LOAD_DUMP
            # H1 fix: gate the Death-5 verdict on v_node itself being a PLAUSIBLE
            # node state at cut time (<= the 20 V abs-max already).  Without this an
            # implausible/runaway node value (e.g. from a solver artefact the M2/H1
            # backstops above did not fully suppress) could manufacture an
            # over_absmax verdict on its own, independent of any real di/dt event.
            plausible = v_node <= V_ABSMAX
            ev = {"t": t_now, "kind": "sw_ring", "switch": self.name,
                  "reason": reason, "i_cut": i_before, "peak_v": peak,
                  "over_absmax": bool(plausible and peak > V_ABSMAX)}
            events.append(ev)
        if reason == "scp_cut":
            events.append({"t": t_now, "kind": "scp_cut", "switch": self.name,
                           "i_cut": i_before, "cut_count": self.cut_count})
        self.state = "OFF"
        self.t_state = 0.0
        self.t_clamped = 0.0
        self.i = 0.0
        self._restart_no_ss = False


class Boost:
    """One TPS61288 channel, as a droop-regulated source behind the validated
    first-order voltage-loop lag.

    ── DELIBERATE DEVIATION, and why ────────────────────────────────────────────
    The first implementation of this class was the literal datasheet structure the
    spec asked for: gm error amp (G_EA), the exact two-state compensation impedance
    Z_comp(R_EA, R_C, C_C, C_P), and the Norton power stage
    i_N = K_COMP(1-D)(1 - s/w_RHPZ) v_comp — i.e. a time-domain rebuild of
    controller_design/tps61288_full_model.py.  It is numerically UNUSABLE here.
    That voltage loop crosses at 4-19 kHz (system_model.md §6e, gate C of the
    full-order model), and the substep rate a stdlib-Python host actually achieves
    on this network is ~20-40 kHz.  Integrating a 19 kHz loop at 20-40 kHz puts the
    crossover essentially at Nyquist: the explicit compensator-to-node coupling went
    unstable within three substeps and tripped the 19 V OVP on every bring-up.  The
    limiter was the DISCRETIZATION, not the physics, and no budgeting scheme fixes
    it — resolving that loop needs ~1 MHz substeps.

    So the channel is modelled at the level the repo has ALREADY validated for this
    bandwidth: the simplified share plant of tps61288_full_model.py:188-191 /
    system_model.md §6d — a droop-regulated voltage source behind a first-order lag
    tau_r, current-limited.  Everything the hi-fi engine actually needs survives:

      * the FB-node superposition droop (V_target = V0 - (R_D1/R_inj)*v_op, which is
        the exact solution of h1*v_out + h2*v_op = VREF — NOT a series-resistor hack),
      * the OPA197 ceiling, the 19 V OVP trip, enable/disable,
      * and the disabled-boost body-diode passthrough, which lives in
        ElectricalSim._substep() because it is a network element, not a loop element.

    What is LOST relative to the datasheet structure: the RHPZ lead, the compensator
    saturation/recovery shape, and any claim about voltage-loop margin.  Do not use
    this engine to judge boost stability — use tps61288_full_model.py, which is what
    it is for.  The constants for the full structure are retained above so the
    datasheet form can be restored if this ever runs somewhere it can be integrated.
    """

    #: closed voltage-loop lag.  TAUR_NOM in tps61288_full_model.py:87; the corner
    #: family there spans 20-300 us.
    TAU_R = 100e-6
    #: Thevenin output resistance of the regulated source.  Small but non-zero so the
    #: node stamp stays well-conditioned; the REAL output impedance the firmware sees
    #: is the droop law above, not this.
    R_OUT = 0.010
    #: output-current ceiling.  TPS61288 switch-current-limit class referred to the
    #: output.  TODO(verify): not extracted from the datasheet in this repo.
    I_OUT_MAX = 6.0

    def __init__(self, name, node, c_out):
        self.name = name
        self.node = node
        self.c_out = c_out
        self.v_src = 0.0
        self.v_target = 0.0
        self.r_droop = 0.0
        self.v_clip = None
        self.enabled = False
        self.ovp_latched = False
        self.i_out = 0.0
        self.limiting = False

    def reset(self, v_start=0.0):
        self.v_src = v_start
        self.v_target = v_start
        self.v_clip = None
        self.i_out = 0.0
        self.limiting = False

    def update(self, dt, v_out, v_in, i_ch, g_code, enabled, events, t_now):
        """Advance the regulated source.  Returns True when it should be stamped."""
        if enabled and not self.enabled:
            # A fresh enable starts from wherever the body diode already left the
            # output node — the real converter does not start from 0 V either.
            self.reset(max(0.0, min(v_out, v_in - V_BODY_DIODE)))
            self.ovp_latched = False
        self.enabled = enabled
        if not enabled or self.ovp_latched or v_in < 1.0:
            self.i_out = 0.0
            return False
        if v_out > V_OVP_TRIP:
            self.ovp_latched = True
            events.append({"t": t_now, "kind": "boost_ovp", "channel": self.name,
                           "v_out": v_out})
            self.i_out = 0.0
            return False

        # ── Droop as an IMPLICIT output resistance ───────────────────────────
        # FB-node superposition: solve h1*v_out + h2*v_op = VREF with
        # v_op = A_v*K_sns*g*i_channel.  Because h2/h1 = R_D1/R_inj exactly, the
        # solution is
        #     v_out = V0 - (R_D1/R_inj)*A_v*K_sns*g*i  =  V0 - RE_MAX*g*i
        # i.e. the droop network makes the channel a Thevenin source of internal
        # resistance R_e = RE_MAX*g (2.014 ohm at g = 1).  Stamping it AS that
        # resistance puts the droop inside the node solve.
        #
        # This matters numerically as much as physically: the first version fed the
        # measured current back explicitly into the next substep's target, and with
        # a 23 mOhm ideal-diode link between two ~0.6 ohm droop sources the explicit
        # loop gain is R_e/R_link ~ 26 per substep — it oscillated rail-to-rail and
        # produced tens of thousands of spurious reverse-blocking events.  Implicit
        # is both the correct physics and the only stable form at these substep rates.
        self.r_droop = max(0.0, RE_MAX * g_code)
        # OPA197 output ceiling on the bodged 5 V rail caps the achievable droop
        # excursion at (R_D1/R_inj)*V_OP_CEIL; beyond it the droop stops growing.
        drop_max = (R_D1 / R_INJ) * V_OP_CEIL
        if self.r_droop * max(i_ch, 0.0) > drop_max:
            self.v_clip = drop_max
        else:
            self.v_clip = None
        # No-load regulation target, reached through the validated first-order
        # voltage-loop lag tau_r.
        target = max(V0_NOLOAD, v_in - V_BODY_DIODE)
        self.v_src += (target - self.v_src) * min(1.0, dt / self.TAU_R)
        return True

    def r_total(self, v_node):
        r = self.R_OUT + (0.0 if self.v_clip is not None else self.r_droop)
        src = self.v_src - (self.v_clip or 0.0)
        # Output-current ceiling, again as an equivalent resistance rather than an
        # ideal current source (see Rt1987.stamp()).
        if (src - v_node) / r > self.I_OUT_MAX:
            r = max(r, (src - v_node) / self.I_OUT_MAX)
        return r, src

    def stamp(self, G, J, v):
        """Thevenin (droop-resistance) source onto the channel's output node."""
        n = self.node
        r, src = self.r_total(v[n])
        g = 1.0 / r
        G[n][n] += g
        J[n] += g * src

    def post_solve(self, v):
        r, src = self.r_total(v[self.node])
        self.i_out = max(0.0, (src - v[self.node]) / r)
        self.limiting = self.i_out >= self.I_OUT_MAX * 0.999


class ElectricalSim:
    """High-fidelity electrical engine — see the module docstring.

    Public API (frozen; hil_plant_sim and the test-writer code against it):

        e = ElectricalSim(trace_config="short", noise=None)
        rails = e.step(dt, actuators)   # actuators: sw, aux, i_motor_a,
                                        # code_fc, code_bt, i_charge_a
        e.achieved_substep_hz           # float, honestly measured
        e.events                        # list of dicts appended as things happen

    `rails` carries exactly the electrical subset of Plant.step()'s return value:
    V_fc, V_batt, V_bus, V_chg, V_rgn, I_fc, I_batt.  Mechanical (v_actual) and the
    Ag105 status/current stay in Plant.
    """

    #: substep dt is never allowed above this (accuracy ceiling; backward Euler
    #: makes the engine unconditionally STABLE, so this is not a stability bound —
    #: see the deviation note in docs/HIL_PLANT.md).
    DT_SUB_MAX = 50e-6
    #: never more than this many substeps per mechanical tick, whatever the budget
    #: measurement says (a mis-measured cost must not be able to stall the frame).
    N_SUB_MAX = 400
    #: fraction of the mechanical tick the electrical engine may consume.
    BUDGET_FRAC = 0.65

    def __init__(self, trace_config="short", noise=None, c_vesc_f=C_VESC_DEFAULT,
                 fuel_cell=None, battery=None):
        if trace_config not in TRACE_L_NH:
            raise ValueError(f"trace_config must be one of {sorted(TRACE_L_NH)}")
        self.trace_config = trace_config
        self.trace_l = TRACE_L_NH[trace_config]
        self.noise = noise
        self.c_vesc = c_vesc_f

        # Node voltages — the ODE state.
        self.v = [0.0] * N_NODES
        self.c_node = [
            C_BOOST_OUT_FC, C_BOOST_OUT_BT, C_VBUS,
            # The trailing C_RGN_NODE entry PADS the retired N_RGN index (see the
            # node-index note above) so the list length matches N_NODES.  The node
            # has no links; the capacitance value is inert.
            C_MOT_LOCAL + c_vesc_f, C_CHG_NODE, C_RGN_NODE,
        ]

        self.boost_fc = Boost("FC", N_OFC, C_BOOST_OUT_FC)
        self.boost_bt = Boost("BT", N_OBT, C_BOOST_OUT_BT)

        self.switches = {
            "FC_BUS": Rt1987("FC_BUS", N_OFC, N_BUS, CSS_NF["FC_BUS"], C_VBUS,
                             r_series=R_SHUNT),
            "BT_BUS": Rt1987("BT_BUS", N_OBT, N_BUS, CSS_NF["BT_BUS"], C_VBUS,
                             r_series=R_SHUNT),
            "MOT_PWR": Rt1987("MOT_PWR", N_BUS, N_MOT, CSS_NF["MOT_PWR"],
                              C_MOT_LOCAL + c_vesc_f),
            # TOPOLOGY FIX (2026-08-30, schematic sheet 4 + operator): D-BC-RG's
            # OUTPUT joins D-BC-FC's output at the shared VCHG-IN node into the
            # Ag105 (CHG-V divider senses that node), so REGEN links MOT -> CHG.
            # The RGN-V divider and the chopper sit on V-MOT itself, UPSTREAM of
            # the switch — the old MOT -> N_RGN link put the sense point on the
            # wrong side and every simulated bring-up failed P3 (V_rgn dark).
            # L5: REGEN and FC_CHARGE both terminate on the SHARED N_CHG node, and
            # each is handed c_load_f = C_CHG_NODE -- so each CSS soft-start ramp is
            # computed as if it alone charges the 10 uF.  With both closed the true
            # shared load is not double-counted in the network solve (one node, one
            # capacitor); only the per-switch ramp timing is optimistic.  Bounded
            # inaccuracy: the 5.6 nF CSS gives a ~1 ms ramp either way.  Accepted.
            "REGEN": Rt1987("REGEN", N_MOT, N_CHG, CSS_NF["REGEN"], C_CHG_NODE),
            "FC_CHARGE": Rt1987("FC_CHARGE", N_BUS, N_CHG, CSS_NF["FC_CHARGE"],
                                C_CHG_NODE),
            # BT_SEQ gates the pack into the BT boost INPUT; it is not a node link in
            # this six-node network, so it is tracked only for its enable state.
            "BT_SEQ": Rt1987("BT_SEQ", N_OBT, N_OBT, CSS_NF["BT_SEQ"], 1e-6),
        }
        self._sw_map = [
            (SW_FC_BUS, "FC_BUS"), (SW_BT_BUS, "BT_BUS"), (SW_MOT_PWR, "MOT_PWR"),
            (SW_REGEN, "REGEN"), (SW_FC_CHARGE, "FC_CHARGE"), (SW_BT_SEQ, "BT_SEQ"),
        ]

        # Source models are SHARED with Plant (one instance each, so SOC and the
        # FC double-layer state are integrated exactly once per tick regardless of
        # which electrical mode is active).  Defaults are created only when this
        # engine is used standalone (tests, notebooks).
        self.fuel_cell = fuel_cell if fuel_cell is not None else FuelCellSource()
        self.battery = battery if battery is not None else BatterySource()

        self.events = []
        self.i_aux = I_AUX_A
        # M5 DEVIATION: renamed from v_bus_offset to v_bus_sense_offset.  Stamping
        # this as a real network disturbance (a Norton source on N_BUS) was tried
        # and risks destabilizing the node solve against the boost droop sources at
        # the small source resistance needed to make it dominate; rather than ship
        # an under-tested network change, this stays a SENSED-RAIL-ONLY offset (the
        # `sag` scenario's -5 V dip is added only in _rails(), never seen by the
        # node, diodes or chopper) and the asymmetry vs simple mode (where the same
        # scenario offset IS a real algebraic disturbance) is documented explicitly
        # here and in docs/HIL_PLANT.md's scenario table.
        self.v_bus_sense_offset = 0.0
        self.i_charge_into_pack = 0.0   # A, set by Plant: Ag105 -> pack (charging)
        self.chopper_active = False
        self.chopper_peak_w = 0.0       # W, worst instantaneous V_rgn^2/R while clamping
        self._chopper_over = False      # once-per-excursion latch for chopper_over_power
        self.numeric_fault = False      # M2: sticky -- set once, never cleared
        self.neg_clamp_count = 0        # M2: diagnostic counter of negative-node clamps

        self.t = 0.0
        self.achieved_substep_hz = 0.0
        self._n_sub = 8
        self._cost_ewma = 0.0
        self._cost_init = False     # L4: separate init flag -- see step()
        self.i_fc = 0.0
        self.i_bt = 0.0

    # ── main entry ───────────────────────────────────────────────────────────
    def step(self, dt, actuators):
        sw = int(actuators.get("sw", 0))
        aux = int(actuators.get("aux", 0))
        i_motor = float(actuators.get("i_motor_a", 0.0))
        code_fc = float(actuators.get("code_fc", 0.0))
        code_bt = float(actuators.get("code_bt", 0.0))
        i_charge = float(actuators.get("i_charge_a", 0.0))

        n = self._n_sub
        h = dt / n
        t0 = time.perf_counter()
        for _ in range(n):
            self._substep(h, sw, aux, i_motor, code_fc, code_bt, i_charge)
        elapsed = time.perf_counter() - t0

        # ── Adaptive substep budgeting ──────────────────────────────────────
        # Measure the real per-substep cost, then pick the substep count that fills
        # BUDGET_FRAC of the mechanical tick.  The engine therefore runs at the
        # host's MAXIMUM ACHIEVABLE rate rather than a fixed one, and never eats
        # the whole tick — the 1 kHz frame transmission always gets its slack.
        per = elapsed / n if n else 0.0
        # L4: use an explicit init flag rather than "_cost_ewma == 0.0" as the
        # uninitialized sentinel.  On a coarse perf_counter (some hosts/containers)
        # a genuinely zero-elapsed tick is possible and would otherwise RESET the
        # EWMA to 0.0 every time it recurred, corrupting the reported
        # achieved_substep_hz down to 0.0 rather than holding the last real rate.
        if not self._cost_init:
            self._cost_ewma = per
            self._cost_init = True
        else:
            self._cost_ewma = 0.75 * self._cost_ewma + 0.25 * per
        if self._cost_ewma > 0.0:
            n_budget = int((dt * self.BUDGET_FRAC) / self._cost_ewma)
        else:
            n_budget = self.N_SUB_MAX
        n_pref = max(1, int(math.ceil(dt / self.DT_SUB_MAX)))
        # Budget WINS over the accuracy preference: a host that cannot afford the
        # 50 us ceiling runs coarser and says so, rather than overrunning the tick.
        self._n_sub = max(1, min(self.N_SUB_MAX, n_pref if n_budget >= n_pref else n_budget))
        # L4 (cont.): hold the last non-zero achieved rate on a zero-elapsed tick
        # (coarse perf_counter) instead of reporting a misleading 0.0 Hz.
        if elapsed > 0:
            self.achieved_substep_hz = n / elapsed

        self.t += dt
        return self._rails(sw)

    # ── one electrical substep ───────────────────────────────────────────────
    def _substep(self, h, sw, aux, i_motor, code_fc, code_bt, i_charge):
        v = self.v
        # ── Source terminals ────────────────────────────────────────────────
        # The INA253s sense each boost's OUTPUT current; the sources see the INPUT
        # current, so refer it back through the bus/source voltage ratio and the
        # boost efficiency before driving the polarization / SOC models.
        bt_seq_on = bool(sw & SW_BT_SEQ)
        i_fc_src = self._source_current(self.i_fc, self.fuel_cell.v_terminal, v[N_BUS])
        i_bt_src = self._source_current(self.i_bt, self.battery.v_terminal, v[N_BUS])
        v_fc_in = self.fuel_cell.update(h, i_fc_src)
        # Net pack current: boost draw minus whatever the Ag105 is pushing back in.
        v_bt_term = self.battery.update(h, i_bt_src - self.i_charge_into_pack)
        v_bt_in = v_bt_term if bt_seq_on else 0.0

        # Switch state machines advance first (they read the previous node solve).
        for bit, name in self._sw_map:
            s = self.switches[name]
            l_nh = self.trace_l["FC" if name == "FC_BUS" else
                                ("BT" if name == "BT_BUS" else "OTHER")]
            s.update(h, v, bool(sw & bit), self.events, self.t, l_nh)

        # Channel currents (INA253 sense point = the switch link current).
        self.i_fc = self.switches["FC_BUS"].i
        self.i_bt = self.switches["BT_BUS"].i

        fc_en = bool(aux & AUX_FC_REG)
        bt_en = bool(aux & AUX_BT_REG) and bt_seq_on
        fc_active = self.boost_fc.update(h, v[N_OFC], v_fc_in, self.i_fc,
                                         code_fc, fc_en, self.events, self.t)
        bt_active = self.boost_bt.update(h, v[N_OBT], v_bt_in, self.i_bt,
                                         code_bt, bt_en, self.events, self.t)

        # ── Assemble the backward-Euler node system: (G + C/h) v' = J + (C/h) v ──
        G = [[0.0] * N_NODES for _ in range(N_NODES)]
        J = [0.0] * N_NODES
        for i in range(N_NODES):
            G[i][i] += 1.0 / R_NODE_BLEED + self.c_node[i] / h
            J[i] += self.c_node[i] / h * v[i]

        # Regulated boost sources onto their own output nodes.
        if fc_active:
            self.boost_fc.stamp(G, J, v)
        if bt_active:
            self.boost_bt.stamp(G, J, v)

        # Disabled-boost body-diode passthrough (THE back-feed hazard path): a
        # disabled TPS61288 still conducts Vin -> inductor -> body diode -> Vout.
        # Stamped as a Norton source behind R_BODY_DIODE so the bus can be pulled up
        # through a dark converter, and so a regen event can push current INTO it.
        for boost, v_in, node in ((self.boost_fc, v_fc_in, N_OFC),
                                  (self.boost_bt, v_bt_in, N_OBT)):
            if (not boost.enabled or boost.ovp_latched) and v_in > 1.0:
                v_src = v_in - V_BODY_DIODE
                if v_src > v[node]:
                    g_bd = 1.0 / R_BODY_DIODE
                    G[node][node] += g_bd
                    J[node] += g_bd * v_src

        # Ideal-diode switch links.
        for _bit, name in self._sw_map:
            if name == "BT_SEQ":
                continue                     # input-side gate, not a node link
            self.switches[name].stamp(G, J, v, None)

        # Loads.
        J[N_BUS] -= self.i_aux
        # Motor draw/regen sits on the V-MOT node, behind MOT_PWR, through the 470 uF
        # ESR.  H1 FIX: this was previously stamped as an IDEAL current source
        # (J[N_MOT] -= i_motor) -- fine for a positive (motoring) draw, but for a
        # NEGATIVE (regen) current with MOT_PWR open, the node has only the 2 kOhm
        # bleed for company and an ideal source into that is unbounded: reproduced,
        # it ran the node to ~10 kV within seconds, and the resulting kV-scale
        # sw_ring events fired the over_absmax Death-5 signature -- a numerical
        # solver runaway rendered as a hardware conclusion.  Stamped instead as a
        # bounded Norton conductance referenced to the PREVIOUS substep's node
        # voltage: g = i_motor / max(v_node, V_MOT_LOAD_FLOOR).  At v_node == v_prev
        # this delivers exactly i_motor (self-consistent: g*v_prev == i_motor), but
        # as the node evolves the delivered current scales WITH voltage instead of
        # staying an unbounded constant, so the runaway direction (rising |V|)
        # shrinks the effective source term instead of feeding it.
        if i_motor:
            g_mot = i_motor / max(v[N_MOT], V_MOT_LOAD_FLOOR)
            G[N_MOT][N_MOT] += g_mot
        if i_charge:
            # The charger input is the single shared VCHG-IN node — both the
            # FC-charge and regen paths land there (schematic sheet 4).
            J[N_CHG] -= i_charge

        # Regen chopper: autonomous TL431/BSP170P clamp into 47 ohm.  It sits
        # directly on V-MOT (the regen node IS the motor node; schematic sheet 4),
        # so it does NOT couple to V_bus through the REGEN switch — but it DOES
        # couple through a CLOSED MOT_PWR, since that RT1987 conducts BUS <-> MOT.
        # Expected bus effect while clamping: the 47 ohm shunt draws ~18.1/47 =
        # ~0.385 A, which the droop law turns into ~0.385 * 0.074-0.16 =
        # ~0.03-0.06 V of bus sag.  That is small enough to be consistent with the
        # bench observation "V_rgn 13.3 -> 18.1 V held, V_bus unmoved"
        # (CLAUDE.md 2026-08-17b) rather than contradicting it.
        self.chopper_active = v[N_MOT] > V_CHOPPER_TRIP
        if self.chopper_active:
            G[N_MOT][N_MOT] += 1.0 / R_CHOPPER

        new_v = _solve(G, J)
        # Chopper dissipation check — THE reason the chopper is simulated at all:
        # whether V_rgn^2 / 47 Ω ever exceeds the dump resistor's 20 W rating.
        # Computed from the SOLVED node voltage (the clamp conductance above was
        # stamped from the pre-solve voltage, so this is the consistent pairing).
        if self.chopper_active and math.isfinite(new_v[N_MOT]):
            p_chop = (new_v[N_MOT] ** 2) / R_CHOPPER
            if p_chop > self.chopper_peak_w:
                self.chopper_peak_w = p_chop
            if p_chop > P_CHOPPER_MAX_W:
                if not self._chopper_over:      # once per excursion
                    self._chopper_over = True
                    self.events.append({"t": self.t, "kind": "chopper_over_power",
                                        "p_w": p_chop, "v_rgn": new_v[N_MOT],
                                        "rating_w": P_CHOPPER_MAX_W})
            else:
                self._chopper_over = False
        else:
            # Excursion over (chopper no longer conducting): re-arm the latch here
            # too, or an excursion that ENDS by dropping below the clamp would leave
            # it stuck and silently swallow the next over-power event.
            self._chopper_over = False
        prev_v = self.v
        for i in range(N_NODES):
            if not math.isfinite(new_v[i]):
                # M2: NaN/inf used to pass the "< 0.0" clamp below untouched and
                # reach the wire -- the firmware rejects a NaN-carrying frame outright
                # (a misleading ERR_HIL_STALE rather than the real cause).  Restore
                # the node's previous value, log it, and set a STICKY fault so a
                # summary/report consumer can tell the whole run is suspect even if
                # a later substep happens to solve clean again.
                self.events.append({"t": self.t, "kind": "numeric_fault",
                                    "node": _NODE_NAMES[i], "value": repr(new_v[i])})
                self.numeric_fault = True
                new_v[i] = prev_v[i]
                continue
            if new_v[i] < 0.0:
                self.neg_clamp_count += 1
                new_v[i] = 0.0
            elif new_v[i] > V_NODE_RUNAWAY_MULT * V_ABSMAX:
                # H1 backstop: any node this far past the 20 V abs-max is not a
                # plausible state at any bench-recorded operating point -- emit ONE
                # event and clamp so a single bad substep cannot propagate an
                # unbounded value (and cannot itself manufacture an over_absmax
                # sw_ring verdict via the gate in _open() below).
                self.events.append({"t": self.t, "kind": "node_runaway",
                                    "node": _NODE_NAMES[i], "v": new_v[i],
                                    "clamped_to": V_NODE_RUNAWAY_MULT * V_ABSMAX})
                new_v[i] = V_NODE_RUNAWAY_MULT * V_ABSMAX
        self.v = new_v
        if fc_active:
            self.boost_fc.post_solve(self.v)
        if bt_active:
            self.boost_bt.post_solve(self.v)

    # ── outputs ──────────────────────────────────────────────────────────────
    def _rails(self, sw):
        v = self.v
        rails = {
            # Sensed source terminals (the firmware's FC_VOLTAGE / BT_VOLTAGE taps
            # are on the source side of each boost).
            "V_fc": self.fuel_cell.v_terminal,
            "V_batt": self.battery.v_terminal,
            "V_bus": max(0.0, v[N_BUS] + self.v_bus_sense_offset),
            "V_chg": v[N_CHG],
            # RGN-V's divider hangs on V-MOT itself, upstream of the REGEN switch
            # (schematic sheet 4) — it is the firmware's motor-node proxy and the
            # staged bring-up's P3 gate reads it.
            "V_rgn": v[N_MOT],
            "I_fc": self.i_fc,
            "I_batt": self.i_bt,
        }
        if self.noise is not None:
            rails = self.noise.apply(rails)
        return rails

    @staticmethod
    def _source_current(i_out, v_src, v_out):
        """Refer a boost OUTPUT current back to its source-side input current."""
        if i_out <= 0.0 or v_src <= 0.5:
            return 0.0
        return i_out * max(v_out, v_src) / (v_src * ETA_BOOST)

    # ── convenience for scenarios / diagnostics ──────────────────────────────
    def node_voltage(self, name):
        return self.v[_NODE_NAMES.index(name)]

    def switch_state(self, name):
        return self.switches[name].state

    def summary(self):
        kinds = {}
        for e in self.events:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        return {
            "achieved_substep_hz": self.achieved_substep_hz,
            "substeps_per_tick": self._n_sub,
            "events": len(self.events),
            "event_kinds": kinds,
            "trace_config": self.trace_config,
            "numeric_fault": self.numeric_fault,          # M2: sticky
            "neg_clamp_count": self.neg_clamp_count,      # M2: diagnostic
            "chopper_peak_w": self.chopper_peak_w,        # worst V_rgn^2/R while clamping
        }
