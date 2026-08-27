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

    2.5 A while VOUT is low (large dV at the start of a ramp into a discharged
    node reads as dV >= knee at first, so the profile is expressed the datasheet
    way: the limit RISES from 2.5 A toward 8.5 A as dV FALLS to <= 5 V).  Above the
    knee the limit is interpolated linearly down toward 2.5 A at dV = 16 V, which
    reproduces the ~5.3 A quoted at dV = 16 V.
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

# Regen chopper — TL431 + BSP170P into 47 Ω / 20 W, autonomous (no firmware control).
# Observed clamping 13.3 -> 18.1 V peak (CLAUDE.md 2026-08-17b).  The THRESHOLD itself
# was never measured: TODO(calibrate).
V_CHOPPER_TRIP = 16.5       # V     TODO(calibrate)
R_CHOPPER = 47.0            # ohm   47 Ω / 20 W dump resistor

# Sources.
V_FC_OPEN = 13.0            # V     H-20 fuel cell, open-circuit class
R_FC_INT = 0.45             # ohm   TODO(verify)
V_BT_OPEN = 8.0             # V     2S LiPo mid-charge
R_BT_INT = 0.05             # ohm   TODO(verify)
I_AUX_A = 0.15              # A     housekeeping load on VBUS

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
                            #      (docs/boost-bringup-debug.md, Death-5 analysis)

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

INA_ZERO_OFFSET_A = 0.02    # A  10s-of-mA class zero offset, clipped at 0.
                            # TODO(verify): no measured per-part offset in the repo.


class NoiseConfig:
    """Additive noise applied to the INJECTED values (never to internal states).

    Quantization is real and computed from the firmware's scale constants.  The
    gaussian sigmas default to ZERO: no measured per-rail noise figure exists
    anywhere in this repo, so a non-zero default would be invention.  The
    `suggested()` classmethod offers plausible values for deliberate use.
    """

    def __init__(self, quantize=True, sigma=None, ina_zero_offset=INA_ZERO_OFFSET_A,
                 seed=None):
        self.quantize = quantize
        self.sigma = dict(sigma or {})
        self.ina_zero_offset = ina_zero_offset
        import random
        self._rng = random.Random(seed)

    @classmethod
    def suggested(cls, **kw):
        """A non-zero sigma set, ALL TODO(verify) — order-of-magnitude guesses only."""
        return cls(sigma={
            "V_fc": 0.010, "V_batt": 0.010, "V_bus": 0.015,   # TODO(verify)
            "V_chg": 0.020, "V_rgn": 0.020,                   # TODO(verify)
            "I_fc": 0.020, "I_batt": 0.020,                   # TODO(verify)
        }, **kw)

    def apply(self, rails):
        out = dict(rails)
        lsb = {"V_fc": LSB_V_FC, "V_batt": LSB_V_BATT, "V_bus": LSB_V_BUS,
               "V_chg": LSB_V_CHG, "V_rgn": LSB_V_RGN,
               "I_fc": LSB_I, "I_batt": LSB_I}
        for key, step in lsb.items():
            val = out[key]
            if key in ("I_fc", "I_batt") and self.ina_zero_offset:
                val += self.ina_zero_offset
            s = self.sigma.get(key, 0.0)
            if s:
                val += self._rng.gauss(0.0, s)
            if self.quantize and step > 0:
                val = math.floor(val / step + 0.5) * step
            # The firmware's ADC path cannot produce a negative reading: the INA253s
            # run 0-referenced (CLAUDE.md §5) and the dividers are unipolar.
            out[key] = max(0.0, val)
        return out


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
            # ramp — the switch behaves as a voltage source at the ramp value, not
            # as a fixed current source.  It supplies whatever the load asks up to
            # the foldback ceiling; only when the ceiling binds does it become a
            # current source (and only THEN does the 250 us SCP blanking count).
            i_fold, i_res, target = self._soft_operating_point(v_in, v_out)
            if i_res > i_fold:
                J[self.n_in] -= i_fold
                J[self.n_out] += i_fold
            else:
                r = RT_R_ON + self.r_series
                g = 1.0 / r
                G[self.n_in][self.n_in] += g
                G[self.n_out][self.n_out] += g
                G[self.n_in][self.n_out] -= g
                G[self.n_out][self.n_in] -= g
                # Thevenin toward the ramp value: the drop (v_in - target) is the
                # FET's own not-yet-enhanced channel, modelled as a source offset.
                off = (v_in - target) * g
                J[self.n_in] += off
                J[self.n_out] -= off
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
            return

        if self.state == "OFF":
            if self.t_retry > 0.0:
                self.t_retry = max(0.0, self.t_retry - dt)
                if self.t_retry > 0.0:
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

        # A reverse-blocked switch re-arms straight into ON (no soft-start) — this
        # is what makes the handoff pickup REACTIVE and fast once the bus has sagged.
        if self.state == "OFF" and getattr(self, "_restart_no_ss", False) \
                and self.t_retry <= 0.0 and en and powered and (v_in - v_out) > RT_V_FWD:
            self._restart_no_ss = False
            self._goto("ON")

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
            ev = {"t": t_now, "kind": "sw_ring", "switch": self.name,
                  "reason": reason, "i_cut": i_before, "peak_v": peak,
                  "over_absmax": peak > V_ABSMAX}
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
        self.enabled = False
        self.ovp_latched = False
        self.i_out = 0.0
        self.limiting = False

    def reset(self, v_start=0.0):
        self.v_src = v_start
        self.v_target = v_start
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

        # Droop injection: v_op = A_v*K_sns*g*i_channel, clipped at the OPA197
        # ceiling set by the bodged 5 V rail (CLAUDE.md §7).
        v_op = min(V_OP_CEIL, max(0.0, A_V * K_SNS * g_code * i_ch))
        # FB-node superposition: solve h1*v_out + h2*v_op = VREF for v_out.  With
        # h2/h1 = R_D1/R_inj exactly, this is V0 - (R_D1/R_inj)*v_op, i.e. a droop of
        # RE_MAX*g ohms per channel (RE_MAX = 2.014 ohm at g = 1).
        self.v_target = (VREF - H2 * v_op) / H1
        # A boost cannot regulate below its own input (plus the body-diode path).
        self.v_target = max(self.v_target, v_in - V_BODY_DIODE)
        self.v_src += (self.v_target - self.v_src) * min(1.0, dt / self.TAU_R)
        return True

    def stamp(self, G, J, v):
        """Thevenin source (current-limited) onto the channel's output node."""
        n = self.node
        if self.limiting:
            # Ride the current limit as a fixed source until the node voltage rises
            # far enough that the resistive branch is back inside the ceiling.
            J[n] += self.I_OUT_MAX
        else:
            g = 1.0 / self.R_OUT
            G[n][n] += g
            J[n] += g * self.v_src

    def post_solve(self, v):
        i = (self.v_src - v[self.node]) / self.R_OUT
        if self.limiting:
            self.i_out = self.I_OUT_MAX
            self.limiting = i > self.I_OUT_MAX
        else:
            self.i_out = min(i, self.I_OUT_MAX)
            self.limiting = i > self.I_OUT_MAX



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

    def __init__(self, trace_config="short", noise=None, c_vesc_f=C_VESC_DEFAULT):
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
            "REGEN": Rt1987("REGEN", N_MOT, N_RGN, CSS_NF["REGEN"], C_RGN_NODE),
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

        self.events = []
        self.i_aux = I_AUX_A
        self.v_bus_offset = 0.0     # scenario disturbance, added to the SENSED bus
        self.v_fc_open = V_FC_OPEN  # scenario-settable source health
        self.v_bt_open = V_BT_OPEN
        self.chopper_active = False

        self.t = 0.0
        self.achieved_substep_hz = 0.0
        self._n_sub = 8
        self._cost_ewma = 0.0
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
        self._cost_ewma = per if self._cost_ewma == 0.0 else \
            0.75 * self._cost_ewma + 0.25 * per
        if self._cost_ewma > 0.0:
            n_budget = int((dt * self.BUDGET_FRAC) / self._cost_ewma)
        else:
            n_budget = self.N_SUB_MAX
        n_pref = max(1, int(math.ceil(dt / self.DT_SUB_MAX)))
        # Budget WINS over the accuracy preference: a host that cannot afford the
        # 50 us ceiling runs coarser and says so, rather than overrunning the tick.
        self._n_sub = max(1, min(self.N_SUB_MAX, n_pref if n_budget >= n_pref else n_budget))
        self.achieved_substep_hz = (n / elapsed) if elapsed > 0 else 0.0

        self.t += dt
        return self._rails(sw)

    # ── one electrical substep ───────────────────────────────────────────────
    def _substep(self, h, sw, aux, i_motor, code_fc, code_bt, i_charge):
        v = self.v
        # Source terminals with IR sag against the LAST substep's channel currents.
        v_fc_in = max(0.0, self.v_fc_open - R_FC_INT * self.i_fc)
        bt_seq_on = bool(sw & SW_BT_SEQ)
        v_bt_in = max(0.0, self.v_bt_open - R_BT_INT * self.i_bt) if bt_seq_on else 0.0

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
        # Motor draw sits on the V-MOT node, behind MOT_PWR, through the 470 uF ESR.
        if i_motor:
            J[N_MOT] -= i_motor
        if i_charge:
            # The charger draws from whichever path is powering it.
            node = N_CHG if (sw & SW_FC_CHARGE) else N_RGN
            J[node] -= i_charge

        # Regen chopper: autonomous TL431/BSP170P clamp into 47 ohm.  V_bus is NOT
        # affected — the chopper sits behind MOT_PWR/REGEN on the regen node.
        self.chopper_active = v[N_RGN] > V_CHOPPER_TRIP
        if self.chopper_active:
            G[N_RGN][N_RGN] += 1.0 / R_CHOPPER

        self.v = _solve(G, J)
        for i in range(N_NODES):
            if self.v[i] < 0.0:
                self.v[i] = 0.0
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
            "V_fc": max(0.0, self.v_fc_open - R_FC_INT * self.i_fc),
            "V_batt": max(0.0, self.v_bt_open - R_BT_INT * self.i_bt)
                      if (sw & SW_BT_SEQ) else self.v_bt_open,
            "V_bus": max(0.0, v[N_BUS] + self.v_bus_offset),
            "V_chg": v[N_CHG],
            "V_rgn": v[N_RGN],
            "I_fc": self.i_fc,
            "I_batt": self.i_bt,
        }
        if self.noise is not None:
            rails = self.noise.apply(rails)
        return rails

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
        }
