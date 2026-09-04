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
  * RT1987 SOFT-state current is the PHYSICAL pass current (ramp displacement
    c_load*d(target)/dt plus downstream load), not a resistive gap against a
    one-substep-stale node voltage.  Fixed 2026-08-30 — the stale form read tens
    of amps of fictitious demand, permanently SCP-cut the 5.6 nF switches (REGEN,
    FC_CHARGE) and injected enough fictitious I_fc to latch FAULT_OC_FC on a
    production HIL boot.  See Rt1987._soft_operating_point() and HIL_PLANT.md
    §8.4's fourth modelling note.
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
    stamp site), not an oversight, and not charge-balanced within one substep.
    Post-fix (2026-08-30) the explicit debit is the PHYSICAL current, so the
    healthy-ramp imbalance fell by orders of magnitude (it was up to i_fold =
    8.5 A of fictitious source-node drain); in the FOLD branch the residual
    imbalance now points the other way (the implicit output draw can exceed the
    i_fold input debit). It matters only during the ~1-20 ms soft-start ramp:
    treat inrush current shape during that window as approximate, not exact
    (docs/HIL_PLANT.md §8.4).

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
# 2026-08-30c: output voltage at SOFT entry above which the episode counts as
# starting on a PRE-CHARGED node, and the tON anti-feedback in
# Rt1987._soft_operating_point() engages.  1.0 V is the rt1987_t_on_s() VIN floor:
# below it the tON formula is already clamped and there is no feedback to break,
# and every hardware-corroborated cold-start ramp begins at ~0 V.
RT_SS_PRECHARGED_V = 1.0
RT_I_FOLD_LOW = 2.5     # A     limit while VOUT < 2 V rising
RT_I_FOLD_HIGH = 8.5    # A     limit at dV <= 5 V
RT_DV_FOLD_KNEE = 5.0   # V     dV at which the limit reaches RT_I_FOLD_HIGH

# ─────────────────────────────────────────────────────────────────────────────
# DROOP REALIZATION MODE — `design` (default) vs `measured`   (2026-09-01, WP-E)
# ─────────────────────────────────────────────────────────────────────────────
# THE STANDING OPEN FINDING IS UNCHANGED AND IS NOT RESOLVED BY THIS SWITCH.
# The realized bus droop measured on hardware is ~4x BELOW what the MDAC droop
# chain above predicts:
#
#     DESIGN (this engine, fitted from a live HIL trace 2026-08-30c)
#         0.316 ohm both sources / 0.633 ohm single, ratio exactly 2.000
#     MEASURED (bench fit of TP0170-0180 excl. TP0178, ML0165, ML0169, fw v16)
#         0.074 V/A both sources / 0.1615 V/A single, V0 = 15.95 V
#
# `measured` mode makes the hi-fi engine REPRODUCE the bench numbers.  It does
# NOT explain the gap: it is a single empirical scale factor on the realized
# droop resistance, applied at the one point the chain becomes a resistance,
# and everything else in the network (RT1987 machines, soft-start/TRCB, the
# chopper, the sources, the OPA197 ceiling) is untouched.  Anyone reconciling
# the FB-node superposition against the bench fit is still doing the work this
# banner has always described; `measured` mode only lets a scenario be run on
# the bench's sag depths in the meantime.
#
# THE ANCHOR, and why it is the SINGLE-SOURCE regime.  One scalar cannot land
# both regimes: the network is a parallel Thevenin pair, so its shared/single
# ratio is STRUCTURALLY exactly 2.000, while the bench fit's is
# 0.1615/0.0740 = 2.182.  The scale is therefore anchored on the regime the
# bench measured most tightly — single-source, 0.1615 +/- 0.001 V/A (0.6 %) —
# and the residual is pushed onto the shared regime, 0.0740 +/- 0.004 V/A
# (5.4 %), where it lands at +8.1 %, i.e. ~1.5 sigma of that fit's own stated
# uncertainty.  Anchoring the other way would have put single-source 8.4 % off
# a value known to 0.6 %, i.e. ~13 sigma.  Both residuals are the SAME
# structural fact — the ratio disagreement — and neither anchor removes it.
#
# THE SCALE IS NOT A RATIO OF THE TWO END-TO-END NUMBERS, and the difference
# matters by 15 %.  Only the MDAC droop term `RE_MAX*g` is rescalable; the
# series path in front of it — the boost's Thevenin R_OUT, the ideal-diode
# R_ON, and the INA253 shunt — is fixed physical copper that the droop code
# does not set and that no rescale may touch.  So the scale is taken over the
# DROOP TERM ALONE, with that floor subtracted from both sides:
#
#     s = (K_meas_single - R_FIXED) / (K_design_single - R_FIXED)
#
# Applying the naive end-to-end ratio 0.16/0.633 instead lands the single-
# source regime at 0.1847 V/A (+15 %) — the floor would be scaled down along
# with the droop and then re-added at full size.  Verified by test at three
# currents in each regime.
#: unscalable series resistance between a channel's regulated node and the bus,
#: at DC: the boost Thevenin term, the RT1987 pass FET, and the sense shunt.
#: The 0.010 term is Boost.R_OUT, repeated as a literal because the class is
#: defined far below this constants block; a test pins the two equal.
DROOP_FIXED_SERIES_OHM = 0.010 + RT_R_ON + R_SHUNT    # 0.033 ohm
#: hi-fi single-source droop realized at DESIGN scale, ohm, at the nominal
#: g_code = 0.298 (the MDAC fraction the firmware commands at share r = 0.5).
#: FITTED from a live HIL trace (2026-08-30c) at 0.633 and reproduced by this
#: engine's own DC solve at 0.63287 — pinned by test.
DROOP_DESIGN_SINGLE_OHM = 0.63287
#: bench-measured single-source bus droop, V/A.  Pinned equal to
#: hil_plant_sim.K_DROOP_BUS_SINGLE by test (hil_electrical must not import
#: hil_plant_sim — the dependency runs the other way).
DROOP_MEASURED_SINGLE_OHM = 0.16
#: the scale `--droop measured` applies to every channel's realized droop
#: resistance.  `--droop design` applies 1.0 and is byte-identical to every
#: run recorded before this switch existed.
DROOP_SCALE = {
    "design": 1.0,
    "measured": ((DROOP_MEASURED_SINGLE_OHM - DROOP_FIXED_SERIES_OHM)
                 / (DROOP_DESIGN_SINGLE_OHM - DROOP_FIXED_SERIES_OHM)),
}
DROOP_MODES = tuple(DROOP_SCALE)
#: the `--droop` CLI default, single-sourced here (E-M3, 2026-09-01).  Both
#: hil_plant_sim.py and run_hil_suite.py declare their flag with it, and
#: hil_plant_sim's scenario-vs-CLI resolution decides "the operator passed
#: --droop explicitly" by comparing the parsed value against it — so the
#: default and that comparison cannot drift apart.
DROOP_MODE_DEFAULT = "design"
assert DROOP_MODE_DEFAULT in DROOP_SCALE

# ═════════════════════════════════════════════════════════════════════════════
# PART A (C1 round, 2026-09-01) — CONVERTER ASYMMETRY
# Source: docs/modeling/converter_asymmetry_20260901.md §9 (reviewed fit round).
# Everything between this banner and its closing banner is the asymmetry model.
# ═════════════════════════════════════════════════════════════════════════════
#: THE M2 CONSISTENT PAIR (fix round F1, 2026-09-01).  ASYM_DV0_V and
#: ASYM_DROOP_SCALE_FC below are the TWO PARAMETERS OF ONE FIT and must move
#: together; do not mix either with a value from another model.
#:
#: WHY M2 AND NOT M1.  The first implementation of this block took M1's
#: DeltaV0 = +0.0444 V (a one-parameter fit that sets rho = 1 BY CONSTRUCTION)
#: and combined it with a rho estimated SEPARATELY from the single-source
#: regime.  That double-counts: M1's DeltaV0 has already absorbed whatever
#: droop-ratio mismatch the corpus contains, because with rho pinned at 1 the
#: voltage term is the only place for it to go.  Adding rho back on top applies
#: the same physical asymmetry twice.
#:
#: THE THREE-WAY COMPARISON against CAL-1 (alpha 0.5354 / 0.5262 / 0.5327 at
#: I_tot 0.452 / 0.935 / 1.346 A, commanded r = 0.5), RMS share error:
#:
#:     parameterization                          dV0        rho      RMS
#:     ------------------------------------      -------    ------   ------
#:     M1 dV0 + separately-fitted rho (SHIPPED)   0.0444     0.930    0.0402
#:     M1 alone (rho = 1)                         0.0444     1.000    0.0253
#:     M2 CONSISTENT PAIR (adopted)               0.013522   0.9434   0.0063
#:
#: The decisive evidence is the SHAPE, not only the RMS: CAL-1's deviation from
#: r is FLAT IN I_tot, which is the rho signature.  A voltage mismatch produces
#: a deviation going as 1/I_tot, so a fit that puts the whole effect in DeltaV0
#: must over-predict at light load and under-predict at heavy load, and the
#: shipped pair did both at once while also carrying rho.
#:
#: static no-load voltage mismatch between the two boost chains, V, as
#: DeltaV0 = V0_FC - V0_BT, at s_B = 1.  A POSITIVE value means the FC chain
#: regulates high and over-delivers current at every load (sign convention,
#: doc 9.1).  M2 fit: CI95 [+0.00097, +0.02429] — the interval is wide and
#: includes values near zero, which is the honest reading of a term the M2
#: partition finds to be the SMALLER of the two mechanisms.
#: Source: docs/modeling/asymmetry_fit_20260901/fit_summary.json,
#: M2.params.dV0_V_if_sB_1.
ASYM_DV0_V = 0.013522
#: per-channel multiplier on the realized droop resistance, applied ON TOP of
#: whatever DROOP_SCALE[droop_mode] already realizes.  BT is the reference
#: channel at 1.000, which keeps the `--droop measured` anchor where it is.
#: M2 fit rho = s_F/s_B: CI95 [0.9205, 0.9636] — and unlike the retired
#: single-source estimate 0.930 [0.834, 1.079], this interval EXCLUDES 1.000.
#: The mismatch is significant under the consistent pair.
#: Source: fit_summary.json, M2.params.rho_sF_over_sB.
#: ⚠️ It still must not be cited as evidence about the +8.1 % shared/single
#: residual, which doc 8 shows the asymmetry does NOT explain.
ASYM_DROOP_SCALE_FC = 0.9434
ASYM_DROOP_SCALE_BT = 1.000
#: the firmware's droop design constant k_d, ohm (`K_DROOP`, .ino:2166-2167),
#: repeated here because the sense-arm equivalence below is written in it.
#: A test pins it equal to hil_plant_sim.K_DROOP_FW_OHM.
ASYM_K_DROOP_OHM = 0.30
#: `--asymmetry` modes.  "off" restores the two identical Boost objects and is
#: BYTE-IDENTICAL to every trace recorded before this mode existed (regression
#: anchors: the scp i_cut 6.3797373196569644 A record and the hi-fi bring-up
#: current pins).  "measured" is the DEFAULT per the operator ruling of
#: 2026-09-01 — the next campaign opens a new baseline era.
ASYMMETRY_MODES = ("measured", "off")
ASYMMETRY_MODE_DEFAULT = "measured"
assert ASYMMETRY_MODE_DEFAULT in ASYMMETRY_MODES


def asymmetry_dv0_sense_v(ina_offset_fc, ina_offset_bt):
    """The SENSE-ARM equivalent voltage of a pair of INA zero offsets, V.

    Doc 7.1: a pair of zero offsets shifts the MEASURED share by
        d_alpha = (delta_F - alpha*(delta_F + delta_B)) / I_tot
    and at r = 0.5 the equivalent voltage mismatch is
        dV0_sense = k_d * (delta_F - 0.5*(delta_F + delta_B)) / 0.25
    which at the plant's own injected defaults {+0.020, 0.0} is +0.0120 V.

    Evaluated at r = 0.5 because that is where the fit's own equivalence is
    stated; the two terms' r dependence differs (doc 7.1) and no attempt is
    made here to separate them away from that point.
    """
    d_f = float(ina_offset_fc)
    d_b = float(ina_offset_bt)
    return ASYM_K_DROOP_OHM * (d_f - 0.5 * (d_f + d_b)) / 0.25


def asymmetry_dv0_v(ina_offset_fc=0.0, ina_offset_bt=0.0):
    """Return the DeltaV0 to inject, given the INA offsets ACTUALLY injected.

    F3 (fix round, 2026-09-01) — DISCRIMINATED ON THE EFFECTIVE OFFSETS, NOT ON
    NoiseConfig PRESENCE.  The quantity that double-counts is the sense-arm
    contribution the run actually injects, and that is a property of the
    resolved `ina_zero_offset` values, not of whether a NoiseConfig object
    exists.  `NoiseConfig(ina_zero_offset=0.0)` is a real and reachable
    configuration, and under the previous "is a NoiseConfig present" test it
    would have had 0.0120 V subtracted for offsets it never injects.  Simple
    mode and replay mode construct no NoiseConfig at all
    (hil_plant_sim.py:8087-8094 vs :8163) and must therefore pass zeros.

    ⚠️ THE CONFRONTATION, RECORDED HONESTLY.  Under the M2 consistent pair the
    sense arm (+0.0120 V at the injected defaults) is COMPARABLE TO THE WHOLE
    voltage term (+0.013522 V), so a `--noise` run injects a residual near
    zero.  That is not a defect in the arithmetic: the M2 partition says most
    of the corpus deviation is DROOP RATIO, which `ASYM_DROOP_SCALE_FC` carries
    and which the sense arm does not touch.  A `--noise` run therefore keeps
    essentially all of the asymmetry and loses only the small voltage term the
    INA offsets were already supplying.  The result is CLAMPED AT >= 0: a
    negative injected DeltaV0 would invert the fitted sign on the strength of
    two near-equal numbers with overlapping intervals, which the data does not
    support in either direction.
    """
    return max(0.0, ASYM_DV0_V - asymmetry_dv0_sense_v(ina_offset_fc,
                                                       ina_offset_bt))


def asymmetry_params(mode, ina_offset_fc=0.0, ina_offset_bt=0.0,
                     droop_scale=1.0):
    """Resolve (v0_offset_fc, v0_offset_bt, droop_scale_fc, droop_scale_bt).

    The voltage mismatch is applied ANTISYMMETRICALLY about V0_NOLOAD
    (+DeltaV0/2 on FC, -DeltaV0/2 on BT) so the MEAN no-load voltage of the two
    chains is unchanged and the bus-level baselines move as little as the
    mismatch allows.  Mode "off" returns the symmetric identity.

    F2 (fix round, 2026-09-01) — THE INJECTED VOLTAGE SCALES WITH `droop_scale`.
    What the corpus measures is a SHARE deviation.  The fit converts it to a
    voltage through the term A = DeltaV0/(k_d*s_B), i.e. the reported DeltaV0 is
    a LUMPED A*k_d AT THE DESIGN DROOP, and the physical voltage it names is
    only as certain as the droop realization assumed to derive it.  Injecting
    the literal number under `--droop measured` (DROOP_SCALE 0.21171) drives the
    share deviation up by 1/0.21171: the delivered alpha at r = 0.5 and 0.5 A
    reached 0.80 with the M1 value.  Scaling the injected voltage by the mode's
    own droop scale makes the SHARE deviation — the measured quantity — the
    invariant across droop modes, which is the property the fit actually
    supports.  A test pins alpha at r = 0.5 under both modes.
    """
    if mode not in ASYMMETRY_MODES:
        raise ValueError("asymmetry mode must be one of %s" % (ASYMMETRY_MODES,))
    if mode == "off":
        return 0.0, 0.0, 1.0, 1.0
    dv0 = asymmetry_dv0_v(ina_offset_fc, ina_offset_bt) * float(droop_scale)
    return (+0.5 * dv0, -0.5 * dv0,
            ASYM_DROOP_SCALE_FC, ASYM_DROOP_SCALE_BT)
# ═════════════════════ end PART A constants ══════════════════════════════════

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

# ── Node bleed (dark-node decay), PER NODE since 2026-09-02 ─────────────────
# The bleed is a lumped stand-in for every static load referred to a node: the
# resistive dividers the Teensy reads the rail through, the RT1987 quiescent
# current of each switch tied to that node, and the leakage of the bulk
# capacitance itself.  It was ONE 2 kOhm value on every node from the engine's
# first commit, and that value was NEVER calibrated: it was chosen to give a
# visibly decaying dark node and never checked against the board.
#
# OPERATOR RULING 2026-09-02 (the DP-bound round).  The physical bus decays
# from full to near zero in 30-60 s.  With C_VBUS + C_MOT_LOCAL + C_VESC on the
# energized path, a 2 kOhm bleed empties the node in well under a second, which
# is off by roughly an order of magnitude in the loss it bills the sources.
# The split values below carry that recollection:
#   * N_BUS gets 30 kOhm, the FASTER bleed, because the bus is where the two
#     source dividers, the VBUS divider and the majority of the quiescent
#     loads are referred.
#   * every other node gets 60 kOhm, because most of them bleed FORWARD into
#     the bus through their own switch rather than to ground on their own.
# TODO(calibrate): both numbers are the operator's 30-60 s recollection
# expressed as a two-value split, NOT a measurement.  The bench procedure that
# settles them is a DARK-NODE DECAY CAPTURE:
#   1. Bring the board up in State 98 and close FC_BUS so VBUS reaches nominal.
#   2. Command the boosts off and open every path switch, leaving the bus
#      floating on its own capacitance.
#   3. Log V_bus at 1 kHz to the SD card until it falls below 1 V.
#   4. Fit tau on ln(V_bus) over the linear region; R = tau / C_node, with
#      C_node the sum of the capacitances still tied to the node at step 2.
#   5. Repeat with MOT_PWR closed to get the N_MOT-inclusive time constant, and
#      difference the two conductances for the N_MOT value.
# Until that capture exists, treat both values as a physically-plausible band
# rather than as board constants, and read `docs/HIL_PLANT.md` section 4.8 for
# the reversal path.
R_NODE_BLEED_BUS = 30e3     # ohm  effective bleed on N_BUS
R_NODE_BLEED_OTHER = 60e3   # ohm  effective bleed on every other node
V_MOT_LOAD_FLOOR = 1.0      # V    floor for the H1 motor-draw/regen Norton
                            #      conductance (i_motor / max(v_node, this)) so the
                            #      element cannot divide by (or explode near) zero
                            #      when V-MOT is dark
V_CHG_LOAD_FLOOR = 8.0      # V    floor for the Ag105 input-current stamp
                            #      (i_charge*V_pack/(ETA_CHG*max(v_node, this))).
                            #      THIS FLOOR IS PHYSICAL, WHERE V_MOT_LOAD_FLOOR
                            #      IS NUMERICAL, and the difference is why the
                            #      two values differ.  The motor floor guards a
                            #      load that legitimately operates all the way
                            #      down to a dark node, so its 1.0 V is an
                            #      arbitrary small number chosen to bound a
                            #      division.  The charger does not: the plant
                            #      zeroes `i_charge` below AG105_V_IN_MIN (8.0 V,
                            #      hil_plant_sim.py, `chg_powered`), so NO
                            #      legitimate state evaluates this stamp between
                            #      1 and 8 V and the floor can be set at the
                            #      lowest input the module can charge from.
                            #      Consequence: with V_pack <= 8.4 V and
                            #      i_charge <= 2.5 A the input current is bounded
                            #      at ~2.98 A instead of ~23.86 A.  The value is
                            #      pinned equal to AG105_V_IN_MIN by test (it
                            #      cannot be imported: the dependency runs
                            #      hil_electrical -> hil_plant_sim, never back).
V_NODE_RUNAWAY_MULT = 2.0   # x V_ABSMAX  hard backstop: a node past this after a
                            #      substep solve is a solver artefact, not a
                            #      plausible physical state on this rig (H1)

# ── Ag105 charge efficiency (2026-09-01, operator ruling) ───────────────────
# The charger is an ENERGY converter, not a current repeater.  It draws
# i_charge*V_pack/(ETA_CHG*V_chg) at its input and delivers i_charge into the
# pack; the difference is dissipated in the module.
#
# SOURCE: references/Datasheets/AG105_Silvertel.pdf, "DC Electrical
# Characteristics" item 1, "Charge Efficiency EFF 88 % typ".  Note 2 of that
# table qualifies it: "Typical figures are at 25 degC, 12 Vin, 3 series cell
# configuration".
#
# THE DATASHEET POINT IS NOT OUR POINT.  This rig runs 15-16 V in and a 2S
# (8.4 V) pack, so the conversion ratio is roughly 1.9:1 where the datasheet
# measured roughly 1.0:1.  No efficiency data exist for our operating point,
# and none can be derived from the datasheet.  The operator ruled a STATIC
# 0.88 for both electrical engines rather than an unmeasured curve, so this
# constant is a modelling decision with a datasheet anchor, not a measurement.
#
# TODO(verify): bench-measure input/output power at 15 V in, 2S.
ETA_CHG = 0.88              # -    Ag105 input -> pack energy efficiency

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
# WP-C (2026-09-01) — THE CHOPPER IS A LINEAR CLAMP, NOT A BARE SWITCHED RESISTOR.
# The TL431 drives the BSP170P's gate in its linear region, so the dump current
# rises FROM ZERO as the node passes V_CHOPPER_TRIP instead of stepping to
# V/47 the instant it does.  Modelled as a stiff Norton clamp of effective
# resistance R_CHOPPER_REG, saturating at the dump resistor's own V/R_CHOPPER
# (the FET fully enhanced).  Two reasons this replaces the old bare 1/R stamp:
#   * PHYSICS: the bench observation is "V_rgn HELD at 18.1 V" (CLAUDE.md
#     2026-08-17b).  A bare 1/47 shunt cannot hold 18.1 V against anything less
#     than 0.385 A — it pulls the node straight back under the trip, so a small
#     regen source chatters across the threshold at the substep rate instead of
#     being clamped.  The regulator holds the level for ANY dump current up to
#     18.1/47 = 0.385 A, which is exactly what was seen.
#   * SCOPE: this stamp only differs from the old one ABOVE 18.1 V on N_MOT, a
#     state no pre-WP-C stimulus could reach (regen power was floored at zero and
#     the bus runs at ~16 V), so no existing trace moves.
# TODO(verify): R_CHOPPER_REG is a modelling choice, not a measurement — it is the
# clamp's small-signal output resistance.  0.5 Ω makes the clamp stiff (0.19 V of
# droop at the 0.385 A saturation point) without making the node solve stiff.
R_CHOPPER_REG = 0.5         # ohm   TL431/BSP170P linear-regulation output resistance
# Coalescing window for the per-episode `chopper_clamp` event (below) and for the
# `reverse_block` events a regen episode provokes on MOT_PWR.  Both are substep-rate
# phenomena: without coalescing a 2 s braking window emits tens of thousands of
# identical dicts into events.jsonl.
EVENT_COALESCE_S = 0.005    # s


class _EventLog(list):
    """A list that remembers what has passed through it (PART B2, 2026-09-01).

    The consumer trims this list after every drain, so counts taken over the
    live list under-report.  `total` and `kinds` are the durable figures.
    Clearing the list (`del log[:]`) deliberately does NOT reset them.
    """

    def __init__(self, *a):
        super().__init__(*a)
        self.total = 0
        self.kinds = {}

    def append(self, ev):
        self.total += 1
        k = ev.get("kind")
        self.kinds[k] = self.kinds.get(k, 0) + 1
        super().append(ev)


def chopper_dump_current(v_node):
    """Dump current [A] drawn by the regen chopper at node voltage `v_node`.

    Zero below the clamp; linear-regulating above it; saturating at the 47 Ω dump
    resistor once the pass FET is fully enhanced.  One function so the stamp, the
    dissipation check and the simple-mode lumped model in hil_plant_sim.py cannot
    disagree about what the chopper does.
    """
    if v_node <= V_CHOPPER_TRIP:
        return 0.0
    return min((v_node - V_CHOPPER_TRIP) / R_CHOPPER_REG, v_node / R_CHOPPER)


# ── Regen source (WP-C, 2026-09-01) ─────────────────────────────────────────
# Braking energy arrives on N_MOT as a power source (see hil_plant_sim.py's
# VESC_REGEN_I_MAX_A / ETA_REGEN block for where the number comes from).  The
# stamp is BOUNDED in the H1 sense (2026-08-30d: an ideal source into an open node
# ran the solver to ~10 kV and manufactured a false Death-5 verdict): it is a
# Norton pair referenced to the PREVIOUS substep's node voltage, sized so that it
# delivers exactly the requested current at v == v_prev and exactly ZERO at
# V_REGEN_OC_MAX.  The node therefore cannot be driven past V_REGEN_OC_MAX by this
# element under any solve, with no clamping, no event and no discontinuity.
# TODO(verify): V_REGEN_OC_MAX stands in for the VESC's own DC-link overvoltage
# cutback, which has never been characterized on this rig.  20.0 V is the abs-max
# the ring estimator already uses; it is comfortably above the 18.1 V chopper clamp,
# so the CHOPPER stays the operative limiter (which is the physical design).
V_REGEN_OC_MAX = V_ABSMAX   # V    open-circuit bound of the regen Norton source
REGEN_I_SRC_MAX_A = 20.0    # A    absolute cap on the stamped source current, so
                            #      p/v cannot explode as V-MOT approaches zero

# Sources — see the SOURCE MODELS block further down (FuelCellSource /
# BatterySource).  These remain as the fallback/legacy scalars: V_FC_OPEN is the
# rig's known open-circuit class and R_FC_INT the effective IR sag the source model
# is FITTED to reproduce.
V_FC_OPEN = 13.0            # V     H-20 fuel cell, open-circuit class
R_FC_INT = 0.45             # ohm   effective bench IR sag  TODO(calibrate)
V_BT_OPEN = 8.0             # V     2S LiPo mid-charge (SOC ~0.7 on the OCV curve)
R_BT_INT = 0.05             # ohm   TODO(verify)
I_AUX_A = 0.09              # A     housekeeping load on VBUS
# 0.15 -> 0.09 A, operator ruling 2026-09-03.  PROVENANCE, because the number
# is a fingerprint key and a wrong one silently mis-bills every walk:
#   * The bench evidence that had been read as 0.15 A is 98 standstill windows
#     across 213 bench logs, whose raw source total is 0.0150 A — INSIDE the
#     0.020 A INA253 offset, so it bounds the load rather than measuring it,
#     and it was taken with the VESC UNPOWERED.
#   * The Teensy is fed from the battery's own 5 V regulator and never appears
#     on VBUS at all.
#   * The VESC draws about 1.2 W from the bus, that is 0.075 A at 15.9 V.
#   * The INA253s, the RT1987 controllers and the OPA197 MDAC buffers ride the
#     bus chain and make up the remainder.
# Pinned equal to `hil_plant_sim.I_AUX_A` by test, and carried in
# DP_FINGERPRINT_META_KEYS, so a DP table or matched-DP record solved at 0.15 A
# is REFUSED rather than silently mis-loaded.  TODO(calibrate): a standstill
# capture with the VESC powered would replace the 0.075 A term with a
# measurement.
# Operator ruling 2026-09-03 (physics review run 002, item N8): below 5 V
# everything downstream of VBUS shuts down anyway, so the housekeeping sink
# must drop out rather than keep pulling a dark node down to exactly 0.000 V
# tick after tick.  Matches the firmware's own `bus_up` 5 V torque gate in
# spirit (a different signal, same operating boundary).  See the stamp site
# at `J[N_BUS] -= self.i_aux` in ElectricalSim._substep() and
# docs/HIL_PLANT.md section 4.3.
V_AUX_DROPOUT_V = 5.0       # V     I_AUX_A (and anything riding on self.i_aux,
                            #       e.g. a scenario preload the plant adds
                            #       before calling step()) stops sinking below
                            #       this bus voltage
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
# ── THE LOAD-DUMP CLASS, AND WHY THE VERDICT IS GATED ON IT ────────────────
# `DI_DT_LOAD_DUMP` below is a FIXED worst-case slew with no `i_cut` scaling, so
# `_open()` adds the SAME 1.95 V ring allowance (1.5 nH x 1.3e9 A/s) to the node
# whether the switch was carrying 6 A or 65 mA.  That is a defensible bound for a
# Death-5-class cut and a nonsense one for a milliamp release, and campaign
# 20260902_220604 measured the consequence: `regen-harvest-true` FAILED
# `sw_ring_over_absmax` on its three COMMANDED REGEN opens (i_cut 0.065 A,
# v_node 18.0639 V, estimated peak 20.0139 V) — over the 20 V abs-max by 13.9 mV.
#
# THE CONFLICT IS STRUCTURAL, NOT A CALIBRATION.  The estimator's implied node
# ceiling is `V_ABSMAX - 1.95` = 18.050 V, which sits 50 mV BELOW the
# chopper-clamp forward-conduction state `V_CHOPPER_TRIP - RT_V_FWD` = 18.065 V.
# The scenario REQUIRES that clamp (`signal_regen_clamp_dwell` >= 800 ticks), so
# ANY commanded REGEN open while the chopper conducts fails the check in ANY
# era at ANY cut above the 50 mA emission gate.  The hot-loop, current-scaled
# bound at 65 mA is ΔV = 0.130 V/A * i_cut = 8.5 mV (provenance below); the
# 20.01 V is an estimator margin figure, not a node voltage.
#
# THE GATE USES THE FIRMWARE'S OWN DEFINITION OF A HAZARDOUS CUT rather than a
# number fitted to the census, so the estimator's load-dump class and the
# firmware's refused-cut class coincide: `SHARE_CUT_MAX_HANDOFF_A = 0.5f`
# (teensy_controller.ino:2290), the fw v6 share-cut LOAD GUARD — a cut of a
# channel carrying more than this is exactly what the firmware refuses to
# perform.  Every Death-5 datapoint is multi-amp and the largest legitimate
# non-teardown cut in the campaign census is 0.66 A, so the class still contains
# every cut the verdict was written for.
#
# ⚠️ V_ABSMAX IS NOT TOUCHED, and neither is the emission gate: a `sw_ring`
# event with its `peak_v` is still emitted for every cut above 0.05 A, so the
# census and the peak history are unchanged.  Only the VERDICT is gated, and
# each event now carries `load_dump_class` saying which side of the gate it fell.
SW_RING_LOAD_DUMP_I_A = 0.5   # A  == SHARE_CUT_MAX_HANDOFF_A (.ino:2290)
DI_DT_LOAD_DUMP = 1.3e9     # A/s  ~1.3 A/ns class slew on an SCP cut
                            #      (docs/boost-bringup-debug.md, Death-5 analysis).
                            #      L1: this is a FIXED WORST-CASE bound applied
                            #      regardless of the actual cut current i_cut.  A
                            #      scaling law vs i_cut IS documented in this repo
                            #      (docs/boost-bringup-debug.md:195): the hot-loop
                            #      current-scaled form is peak = v_node +
                            #      0.130 V/A * i_cut (1.95 V / 15 A from the FC
                            #      output-cap hot-loop commutation record,
                            #      docs/boost-bringup-debug.md:1572-1573).  This
                            #      fixed allowance is a non-certifying bound, not
                            #      that scaling law; the two are verdict-invariant
                            #      against each other and against the node's own
                            #      i*sqrt(L/C) ring over the corpus's 1028
                            #      sw_ring events.  Treat the resulting peak_v as
                            #      "at least this bad", not a current-dependent
                            #      prediction.

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


def node_bleed_conductances():
    """Per-node bleed conductance [S], in node-index order.

    ONE resolution of the two bleed constants, so the engine, the DP loss map
    and every probe read the same split.  N_BUS takes R_NODE_BLEED_BUS; every
    other node takes R_NODE_BLEED_OTHER.  Read through the MODULE GLOBALS at
    call time rather than captured at import, so a monkeypatch of either
    constant places a subsequently-constructed simulator in that bleed era."""
    g_other = 1.0 / R_NODE_BLEED_OTHER
    g = [g_other] * N_NODES
    g[N_BUS] = 1.0 / R_NODE_BLEED_BUS
    return g


class Rt1987:
    """One RT1987 ideal-diode switch as a time-domain state machine.

    States: OFF (full isolation — back-to-back FETs, NO body-diode path),
    TD_ON (8 ms EN-rise delay), SOFT (soft-start ramp with foldback SCP active),
    ON (forward regulation servo + fast reverse comparator).
    """

    def __init__(self, name, n_in, n_out, css_nf, c_load_f, r_series=0.0,
                 strict_forward=False):
        self.name = name
        #: WP-C: block conduction below the forward-regulation point instead of
        #: letting the linear branch deliver reverse current.  See stamp().
        self.strict_forward = bool(strict_forward)
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
        #: highest VIN seen during the CURRENT soft-start episode.  The ramp duration
        #: is derived from THIS, not from the instantaneous VIN, so tON is
        #: monotonically non-decreasing within one episode — see
        #: _soft_operating_point()'s 2026-08-30c block.
        self._ss_v_in_max = 0.0
        #: diagnostics for the 2026-08-30c pre-charged-node fix: how many substeps
        #: the output sat at/above its own ramp target (the pass device sources
        #: nothing there), and the worst excursion above it.
        self._ss_above_target_substeps = 0
        self._ss_above_target_max_v = 0.0
        self._fold_active = False
        self._restart_no_ss = False
        #: substep length of the most recent update(), cached so the SOFT-state
        #: operating point can evaluate the ramp target at the SAME instant as the
        #: node voltages it is compared against (see _soft_operating_point()).
        #: update() always precedes stamp() within a substep, so this is fresh.
        self._h = 0.0
        #: WP-C: last emitted reverse_block dict + its time, for coalescing.  A
        #: regen episode on V-MOT reverse-blocks MOT_PWR and re-arms it every few
        #: substeps by construction (that IS the ideal diode doing its job), so the
        #: raw event stream is tens of thousands of identical dicts.  Coalesced
        #: events carry a `repeats` count and a `t_end`; the FIRST of a burst keeps
        #: its own timestamp, so nothing that reads event times moves.
        self._rev_last_ev = None
        self._rev_last_t = None

    def _reverse_event(self, events, t_now, dv, during=None):
        """Emit (or coalesce into) a reverse_block event.  See _rev_last_ev."""
        if (self._rev_last_ev is not None and self._rev_last_t is not None
                and (t_now - self._rev_last_t) <= EVENT_COALESCE_S):
            self._rev_last_ev["repeats"] = self._rev_last_ev.get("repeats", 1) + 1
            self._rev_last_ev["t_end"] = t_now
            self._rev_last_ev["dv"] = dv
            self._rev_last_t = t_now
            return
        ev = {"t": t_now, "kind": "reverse_block", "switch": self.name, "dv": dv}
        if during is not None:
            ev["during"] = during
        events.append(ev)
        self._rev_last_ev = ev
        self._rev_last_t = t_now

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
            # count=True: stamp() is the ONE call per substep per switch, so the
            # above-target diagnostic counts substeps rather than calls (MED-2).
            i_fold, i_phys, target = self._soft_operating_point(v_in, v_out,
                                                               count=True)
            # NOTE (2026-08-30c, tried and REJECTED): "if v_out >= target: return"
            # — skipping the stamp when the node sits above its own ramp, on the
            # argument that a gate-limited device sources nothing there.  It is true
            # of the device and WRONG for this model: the conductance-to-target IS
            # the soft-start servo, and removing it on one side of the target turns a
            # stiff servo into a bang-bang.  Measured on the pre-charged case it made
            # things worse, not better (I_tot peak 6.95 A vs 2.82 A with the servo
            # left intact).  The overshoot it was meant to prevent is a symptom of a
            # MOVING target, and is fixed at the source in _soft_operating_point().
            r = RT_R_ON + self.r_series
            if i_phys > i_fold:
                # Foldback binding: an EQUIVALENT RESISTANCE that delivers the limit
                # at the present demand, not an ideal current source (an ideal source
                # into a 30 uF node is unbounded within one substep).  Scaling the
                # pass resistance by the OVERDRIVE RATIO i_phys/i_fold is the form
                # that uses only physical quantities: it is exactly the resistance
                # at which the same physical demand delivers i_fold.  The previous
                # form divided the (target - stale v_out) gap by i_fold, which
                # inherited the one-substep ramp skew described below.
                r = max(r, r * i_phys / max(i_fold, 1e-6))
            g = 1.0 / r
            G[self.n_out][self.n_out] += g
            J[self.n_out] += g * target
            J[self.n_in] -= min(i_fold, max(0.0, i_phys))
            return
        # ON: forward branch with the 35 mV regulation offset, i = (dv - V_FWD)/R.
        #
        # WP-C (2026-09-01) — NO REVERSE CONDUCTION IS STAMPED.  The RT1987 in ON
        # is a REGULATED ideal diode: its gate is servoed to hold +35 mV forward,
        # not saturated, so a reverse current collapses the differential and the
        # reverse comparator opens the FET within t_FRC ~ 0.5 us — two orders of
        # magnitude shorter than one substep (~30 us).  Stamping the link as a
        # symmetric R_ON resistor let up to |RT_V_REV|/R_ON = 2.38 A of reverse
        # current flow for a whole substep before the state machine noticed, which
        # is what made a regen episode back-feed VBUS through a closed MOT_PWR
        # instead of lifting V-MOT.  The bench falsifies that directly: sustained
        # regen drove V_rgn 13.3 -> 18.1 V with V_BUS UNMOVED (CLAUDE.md
        # 2026-08-17b) — 2.38 A into the measured single-source droop would have
        # moved the bus ~0.4 V.  Between 0 and RT_V_REV the part is still ON and
        # still un-tripped; it simply carries no current, so V-MOT can rise the
        # comparator's own 50 mV before the state machine opens the switch on the
        # next substep.  The forward branch is untouched, so the TP0178/TP0201
        # reactive-pickup handoff behaviour is unchanged.
        # The threshold is the FORWARD REGULATION POINT, not zero volts: the linear
        # branch below is i = (dv - RT_V_FWD)/R, which is already NEGATIVE for any
        # dv under 35 mV.  Guarding at v_out > v_in would leave a 35 mV window of
        # unphysical reverse conduction — and that window is exactly where a regen
        # source parks the motor node, so it was enough on its own to hide the whole
        # effect (measured: V-MOT pinned 31 mV UNDER the bus for a 3 s braking run,
        # with the bus quietly absorbing the harvest through a diode that should
        # have been blocking, and V_rgn never reaching the chopper).
        #
        # ⚠️ SCOPED DEVIATION, and deliberately not applied engine-wide.  The same
        # correction on the two boost-OR links (FC_BUS/BT_BUS) is a DIFFERENT
        # experiment: those two switches feed one node from two sources whose
        # outputs sit within millivolts of each other, so removing the sub-35 mV
        # reverse path changes which channel blocks during a hand-off.  Measured
        # cost of applying it there: the hardware-corroborated cold-start pin moves
        # 0.2224 -> 0.2245 A (+0.9 %) and BT_BUS ends a bring-up OFF rather than ON.
        # ⚠️ L5 (reviewer, 2026-09-01) INDEPENDENT RE-VERIFICATION of the two
        # implementer-claimed numbers, via a standalone A/B script exercising this
        # code path directly (scratch, not committed): the +0.9 % cold-start pin
        # move (0.2224 -> 0.2245 A) REPRODUCED EXACTLY. The "BT_BUS ends a
        # bring-up OFF" claim did NOT reproduce under either of two tested
        # stimuli — a plain P0-only cold bring-up (both channels ended ON in
        # BOTH the baseline and strict_forward configurations) and an
        # asymmetric-droop-code bring-up (code_fc=0.9/code_bt=0.1, both channels
        # still ended ON in both configurations). This does not falsify the
        # claim — the implementer's own stimulus (a genuine parallel-source
        # hand-off scenario) was not reproduced here and may differ from both
        # attempts above — but it is UNVERIFIED as stated; re-verify against the
        # implementer's actual stimulus before relying on it.
        # That is a parallel-source hand-off question and needs its own A/B round
        # against the bench; it is FLAGGED here, not shipped.  `strict_forward` is
        # therefore set only on the links whose DOWNSTREAM node carries an active
        # source (MOT_PWR: the VESC; REGEN/FC_CHARGE: the shared VCHG-IN node they
        # both drive), which is the only place the distinction is load-bearing.
        if self.strict_forward and (v_in - v_out) < RT_V_FWD:
            return
        r = RT_R_ON + self.r_series
        g = 1.0 / r
        G[self.n_in][self.n_in] += g
        G[self.n_out][self.n_out] += g
        G[self.n_in][self.n_out] -= g
        G[self.n_out][self.n_in] -= g
        off = RT_V_FWD / r
        J[self.n_in] += off        # the offset opposes forward conduction
        J[self.n_out] -= off

    def _soft_operating_point(self, v_in, v_out, count=False):
        """Return (foldback limit, PHYSICAL pass current, ramp target) [A, A, V].

        The ramp target is the RT1987's soft-start VOUT profile: a linear ramp from
        the output's starting voltage to VIN over
        tON = (VIN/35)*(CSS_nF/0.0023 - 100) us (datasheet).  With CSS = 100 nF that
        is ~19.8 ms at 16 V; with 5.6 nF, ~1.07 ms.

        ── 2026-08-30 fix: the middle return value is now PHYSICAL ──────────────
        It used to be `(target - v_out) / R` with `target` evaluated at the CURRENT
        substep and `v_out` carried over from the PREVIOUS one.  Those two are one
        substep apart, so the gap contained the ramp's per-substep step
        `rate*h` on top of the genuine tracking lag.  Since `R` is 21 mOhm, that
        skew reads as TENS OF AMPS of demand while the physical pass current is
        milliamps: rate*h/R at 15 kV/s and h = 50 us is ~36 A, against a true
        C*rate of ~0.5 A.  Three consequences, all now fixed:
          * the 5.6 nF switches (REGEN, FC_CHARGE, tON ~1 ms) were fold-active for
            their entire ramp, so t_clamped ran past the 250 us SCP blanking and
            they CUT every time — they could never reach ON, and no hifi charge
            scenario could power the Ag105;
          * `self.i` is the INA253 sense point (_substep() reads
            switches["FC_BUS"].i / ["BT_BUS"].i), so bring-up injected amps of
            fictitious I_fc/I_batt — enough to latch FAULT_OC_FC (LIMIT_I_FC_MAX
            1.4 A, single-sample) on a production HIL boot, from a real current of
            C*dV/dt ~ 35 uF * 16 V / 28 ms ~ 20 mA;
          * SCP was decided by the artefact rather than by the load.

        The physical pass current during soft-start is the charge current the
        output node needs to FOLLOW the ramp, plus whatever the downstream load
        draws:  i_phys ~= c_load * d(target)/dt + i_load.  Both terms are recovered
        without extra state by evaluating the ramp target at the SAME instant as
        `v_out` (i.e. one substep back, `t_state - h`): in tracking equilibrium the
        discrete solve settles at target_prev - v_out = R*(c_load*rate + i_load),
        so the lag term alone IS the physical current.  `c_load*rate` is kept as a
        FLOOR so a momentary overshoot of the node past the target (a load release)
        cannot under-report the displacement current to zero.

        A genuine overload still folds and cuts: a node held down by load or a
        short does not track, `target_prev - v_out` grows without bound, and the
        demand crosses i_fold on physics rather than on discretization.

        ── RAMP SHAPE: WHAT THE DATASHEET SAYS vs WHAT THIS MODEL DOES (MED-3) ──
        Read this before quoting a soft-start current from this engine as physical.
        DS 17.1/17.3 define tON as the **10 % to 90 % rise time**, programmed by CSS:
            tON = (VIN/35) * (CSS_nF/0.0023 - 100) us
        so the part's TRUE slew rate is
            dVOUT/dt = 0.8 * VIN / tON = 0.8 * 35 / (CSS_nF/0.0023 - 100)
        which is **INDEPENDENT OF VIN** — 645.5 V/s at CSS = 100 nF, whatever the
        rail.  (Verified against the constants: tON = VIN * 1.23938e-3 s, so VIN
        cancels.)

        THIS MODEL RAMPS `v_ss_start -> v_ref` OVER tON, i.e. it conflates the SLOPE
        with the ENDPOINT and inherits a VIN- and start-dependent error:
            cold (v_ss_start ~ 0):   rate = VIN/tON        = 806.9 V/s  -> +25.0 %
            warm (v_ss_start 4.4 V,
                  v_ref 15.78 V):    rate = 11.38/tON      = 581.9 V/s  ->  -9.8 %
        The two biases have OPPOSITE SIGN, which is why no single scale factor fixes
        it, and why the displacement current this function reports is systematically
        high on a cold start and low on a warm one.  NOTE the consequence for any
        test that bounds the reported current by `c_load * rate` computed from
        rt1987_t_on_s(): that bound is SELF-REFERENTIAL — it re-derives the same
        wrong slope, so it validates internal consistency, not physicality.

        FUTURE WORK, deliberately NOT done here: a constant-slew ramp
        (dVOUT/dt = 0.8*35/(CSS_nF/0.0023 - 100), endpoint v_ref, duration whatever
        the distance requires).  It is the physically right shape, and it MOVES THE
        COLD PINS — the +25 % bias is baked into the hardware-corroborated 0.2226 A /
        0.4740 A bring-up numbers, which have been reproduced in three campaigns.
        Changing it needs its own A/B round against hardware, not a drive-by.

        ── 2026-08-30c fix: tON IS MONOTONICALLY NON-DECREASING PER EPISODE ────
        tON used to be recomputed from the INSTANTANEOUS v_in on every substep while
        `v_ss_start` stayed latched, and on a PRE-CHARGED node that pairing is a
        POSITIVE FEEDBACK LOOP:
            v_in sags -> tON = (VIN/35)*(...) shrinks -> `rate` and `frac` both grow
            -> more displacement demand -> more bus draw -> v_in sags further.
        The cold-start case escapes it (a dark node draws its inrush while the bus is
        stiff), which is why the 2026-08-30b fix did not surface this.  The comm-loss
        recovery does not: the fw v23 warm reset closes MOT_PWR onto V-MOT bled to
        ~4.4 V while the bus is live, and the loop ran the REPORTED current to ~6.8x
        the physical displacement current (measured standalone; ~3.9x on the board,
        where the load differs) and drove the node ABOVE its own ramp target — enough
        to latch a spurious OC_FC 3 ms after Idle.

        WHY NOT SIMPLY LATCH tON AT SOFT ENTRY (the obvious fix, and it is wrong):
        at SOFT entry the input is frequently still DARK.  The staged bring-up closes
        FC_BUS/BT_BUS before the boosts are enabled, so v_in at entry is ~0 and
        rt1987_t_on_s()'s max(v_in, 1.0) floor latches tON = 1.24 ms instead of the
        ~19.8 ms the ramp actually takes — a 16x-too-fast ramp.  MEASURED: the
        cold-start P0 peak goes 0.2226 -> 3.81 A.

        L1 CLARIFICATION (the shipped mechanism IS a per-episode high water mark, so
        this next sentence has to be read carefully): applying the HWM
        UNCONDITIONALLY — to cold episodes as well — regresses the COLD path exactly
        as the entry-latch does, and for the same reason.  During P0 the input node
        is fed through a boost body diode and SAGS under the switch's own draw, so on
        a cold start holding tON at its pre-draw value keeps the ramp ahead of a node
        that cannot follow it (cold P0 0.2226 -> 3.81 A again).  What ships is the
        HWM SCOPED TO A PRE-CHARGED ENTRY; the cold path keeps the instantaneous VIN
        and is bit-for-bit unchanged.

        WHAT IS ACTUALLY DONE — the anti-feedback is SCOPED TO A PRE-CHARGED ENTRY.
        The runaway needs v_ss_start well above zero: that is what lets a shrinking
        tON move `target` DISCONTINUOUSLY (frac = t_state/tON jumps), and with
        r = 21 mOhm a 0.1 V step in the target is ~4.8 A of demand.  A cold start
        begins at v_ss_start ~ 0 with the target rising smoothly from zero, and its
        behaviour is triple-corroborated on hardware — so it keeps the original
        instantaneous-VIN path, BIT-FOR-BIT.  Only an episode that starts on a
        pre-charged node (v_ss_start > RT_SS_PRECHARGED_V) derives tON from the
        per-episode VIN high water mark instead.  That is physical in its own right:
        a CSS capacitor charging at a fixed current cannot make an in-progress ramp
        finish SOONER because the input momentarily sagged.  With tON held, a sagging
        v_in SHRINKS `rate` (numerator falls, denominator held) instead of growing
        it — negative feedback, which is the point.
        """
        r = RT_R_ON + self.r_series
        if v_in > self._ss_v_in_max:
            self._ss_v_in_max = v_in
        precharged = self.v_ss_start > RT_SS_PRECHARGED_V
        # RAMP REFERENCE.  Cold start (the hardware-corroborated path) keeps the
        # original instantaneous VIN, bit-for-bit.  A pre-charged episode uses the
        # per-episode high water mark for BOTH the duration and the endpoint: with
        # r = 21 mOhm, a target that follows the bus's own sag/ripple turns millivolts
        # of node ripple into AMPS of apparent demand, and the measured trace showed
        # exactly that — the target oscillating with v_in (15.78 -> 14.76 -> 15.35)
        # and i_phys chattering 0.0 <-> 3.0 A around a true 0.562 A displacement.
        v_ref = self._ss_v_in_max if precharged else v_in
        t_on = rt1987_t_on_s(max(v_ref, 1.0), self.css_nf)
        frac = 1.0 if t_on <= 0 else min(1.0, self.t_state / t_on)
        target = self.v_ss_start + (v_ref - self.v_ss_start) * frac
        # Ramp target at the instant `v_out` was solved (one substep back).
        t_prev = max(0.0, self.t_state - self._h)
        frac_prev = 1.0 if t_on <= 0 else min(1.0, t_prev / t_on)
        target_prev = self.v_ss_start + (v_ref - self.v_ss_start) * frac_prev
        # NOTE (2026-08-30d, ADDED then REMOVED — do not reinstate): a
        # `target = min(target, v_in)` cap, on the argument that a pass device
        # cannot ramp its output above its own input.  The premise is right and the
        # cap is the wrong mechanism: when the held reference leads a sagging rail
        # it drives the target BELOW v_out, and the SOFT stamp then sinks the full
        # 47.6 S servo conductance out of n_out with J[n_in] = 0 — charge
        # annihilated, measured at -94 A on a 0.3 Vpp bus ripple and -345 A on a bus
        # collapse, while self.i still reported <= 8.5 A.  The v_out > v_in regime
        # belongs to the reverse comparator (TRCB), which now runs in SOFT — see
        # update()'s state machine.  That is also what the part does: DS 17.6 says
        # the fast reverse comparator trips within t_FRC (~0.5 us) whenever
        # VIN - VOUT falls below V_FRC, with no restriction to post-soft-start.
        # Displacement current needed to follow the ramp, zero once it has run out.
        rate = 0.0 if t_on <= 0 or self.t_state >= t_on else \
            max(0.0, v_ref - self.v_ss_start) / t_on
        # F2 (review, 2026-08-30): the i_track floor is unconditional — it reports
        # c_load*rate even when the node sits at/above the ramp (load release),
        # where the true displacement current is ~0.  Assumption recorded here:
        # c_load*rate < RT_I_FOLD_LOW (2.5 A) for every shipped c_load (worst is
        # MOT_PWR at ~1.37 mF -> ~1.1 A), so the floor alone can never assert
        # _fold_active.  A caller passing c_vesc_f >~ 10 mF breaks that — gate the
        # floor on (target_prev > v_out) if such capacitances ever ship.
        # Residual h-sensitivity (F1): the fix removes the rate*h/R skew, but the
        # reported current converges only for substeps <= ~125 us; tests pin _n_sub.
        i_track = self.c_load * rate
        i_lag = max(0.0, target_prev - v_out) / r
        i_phys = max(i_track, i_lag)
        if v_out >= target:
            # At/above its own ramp the gate-limited device sources nothing, so the
            # displacement floor does not apply either — reporting c_load*rate here
            # would put a fictitious current on the INA253 sense point (self.i) for a
            # switch that is not conducting.
            #
            # MED-2 (2026-08-30d): this counter used to increment on EVERY call, and
            # this function is called TWICE per substep — once from update() for the
            # sense current, once from stamp() for the network contribution — plus
            # any number of times from a diagnostic probe.  It therefore counted
            # CALLS, not substeps, and read ~2x high.  `count=True` is passed only
            # from stamp(), which runs exactly once per substep per switch.
            #
            # The entry tick is also excluded.  _goto("SOFT") latches
            # v_ss_start = v_out, so at t_state == 0 the ramp target IS v_out and the
            # `>=` is satisfied by equality — a definitional artefact, not the
            # condition this diagnostic exists to expose.  The previous comment here
            # claimed "on a cold start it never happens"; that was FALSE, and
            # test_hil_electrical.py documented the opposite (exactly one count per
            # cold SOFT entry).  With the entry tick skipped the claim becomes true
            # as written, and a nonzero count now means what it says: the node was
            # genuinely above its own ramp mid-episode.
            if count and self.t_state > 0.0:
                self._ss_above_target_substeps += 1
                self._ss_above_target_max_v = max(self._ss_above_target_max_v,
                                                  v_out - target)
            i_phys = 0.0
        dv = max(0.0, v_in - v_out)
        i_fold = rt1987_fold_limit(dv)
        self._fold_active = i_phys > i_fold
        return i_fold, i_phys, target

    # -- advance ------------------------------------------------------------
    def update(self, dt, v, en, events, t_now, trace_l_nh):
        v_in, v_out = v[self.n_in], v[self.n_out]
        self.t_state += dt
        self._h = dt        # must be set BEFORE _soft_operating_point() is used
        # Measured current for the ON branch (used by the reverse comparator and
        # by the ring estimate); in SOFT it is the PHYSICAL soft-start pass current
        # (ramp displacement + downstream load), clamped by the foldback limit.
        # This value is the INA253 sense point for FC_BUS/BT_BUS, so it must never
        # carry the discretization artefact _soft_operating_point() documents.
        #
        # L2 — ORDERING IS LOAD-BEARING, do not move this block below the state
        # machine.  _soft_operating_point() maintains `_ss_v_in_max` (the
        # per-episode VIN high water mark) as a side effect of being called.  The
        # state machine's SOFT branch further down re-derives the completion tON
        # from that same high water mark, so it must run AFTER at least one call has
        # refreshed it on this substep.  In the same order, the documented
        # `v_in=None` fallback in _goto("SOFT") (which seeds the mark at 0.0) is
        # self-healing: the first call here lifts it to the live VIN before anything
        # reads it.  Reversed, the completion test would consult a stale — possibly
        # zero — mark and could declare a ramp finished on the first substep.
        if self.state == "ON":
            self.i = max(0.0, (v_in - v_out - RT_V_FWD) / (RT_R_ON + self.r_series))
        elif self.state == "SOFT":
            i_fold, i_phys, _t = self._soft_operating_point(v_in, v_out)
            self.i = min(i_fold, i_phys)
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
            # DS 17.4 condition 1: "When the device is first enabled, if any of the
            # following conditions exist, the internal power MOSFET will not turn
            # on: 1. VIN - VOUT < V_FRC (typically -50mV)".  So t_D(ON) elapsing is
            # necessary but NOT sufficient — the part also refuses to start into a
            # reverse differential, and "continuously monitors these conditions to
            # determine when to allow the power path to be enabled".  Holding in
            # TD_ON is that monitoring: the switch waits, and enters soft-start on
            # the first tick the differential is admissible.  Without this gate a
            # soft-start could begin on a node already above its input, which is
            # precisely the state the ramp cannot represent.
            if self.t_state >= RT_TD_ON_S and (v_in - v_out) >= RT_V_REV:
                self._goto("SOFT", v_out, v_in)
        elif self.state == "SOFT":
            # TRCB DURING SOFT-START (2026-08-30d).  The reverse comparator is NOT
            # a post-soft-start feature: DS 17.6 puts it under "when the power path
            # is enabled", trips within t_FRC (~0.5 us, i.e. inside one substep),
            # and DS Table 1 gives its fault response as "Auto-restart WITHOUT
            # soft-start at fault removal" with FLTB high-impedance.  The model used
            # to run this branch only in ON, which left SOFT with no representation
            # of the v_out > v_in regime at all — so a sagging rail (bus ripple, a
            # load step mid-ramp, a collapse) drove the ramp target under the node
            # and the servo stamp SANK the difference: measured -94 A on 0.3 Vpp of
            # ripple, -345 A on a collapse, with J[n_in] = 0 so the charge simply
            # vanished from the network.  Checked BEFORE the SCP/completion logic
            # below because a reverse event is faster (0.5 us) than either.
            if (v_in - v_out) < RT_V_REV:
                self._reverse_event(events, t_now, v_in - v_out, "soft_start")
                self.state = "OFF"
                self.t_state = 0.0
                self.t_clamped = 0.0
                self.t_retry = 0.0
                self._fold_active = False
                self.i = 0.0
                self._restart_no_ss = True
                return
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
            # collapsed into the forward-regulation band.  Uses the LATCHED duration,
            # for the same reason _soft_operating_point() does: a completion test on
            # a tON that shrinks with a sagging VIN would declare the ramp finished
            # early, which is the same artifact wearing a different hat.  Note this
            # is the per-episode VIN high water mark, not the instantaneous VIN.
            t_on = rt1987_t_on_s(
                max(self._ss_v_in_max if self.v_ss_start > RT_SS_PRECHARGED_V
                    else v_in, 1.0), self.css_nf)
            if self.t_state >= t_on and (v_in - v_out) <= RT_V_FWD * 2.0:
                self._goto("ON")
        elif self.state == "ON":
            # Fast reverse comparator: off within 0.5 us, auto-restart WITHOUT
            # soft-start once forward again.
            if (v_in - v_out) < RT_V_REV:
                self._reverse_event(events, t_now, v_in - v_out)
                self.state = "OFF"
                self.t_state = 0.0
                self.t_retry = 0.0
                self._restart_no_ss = True

    def _goto(self, state, v_out=0.0, v_in=None):
        if state == "SOFT":
            self.v_ss_start = v_out
            # 2026-08-30c: a NEW soft-start episode, so the per-episode VIN high
            # water mark that sets the ramp duration restarts here beside
            # v_ss_start — the two describe one ramp.  `v_in` is optional only so an
            # existing direct _goto("SOFT", v) call cannot break; every in-tree
            # caller passes it.
            self._ss_v_in_max = v_in if v_in is not None else 0.0
            self._ss_above_target_substeps = 0
            self._ss_above_target_max_v = 0.0
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
            # THE LOAD-DUMP CLASS (2026-09-03) — see SW_RING_LOAD_DUMP_I_A.
            # `DI_DT_LOAD_DUMP` is a fixed worst case with no i_cut scaling, so
            # the 1.95 V allowance only describes a cut in that class. The event
            # and its `peak_v` are emitted for every cut above the 0.05 A gate
            # regardless; only the VERDICT is confined to the class.
            load_dump = i_before >= SW_RING_LOAD_DUMP_I_A
            ev = {"t": t_now, "kind": "sw_ring", "switch": self.name,
                  "reason": reason, "i_cut": i_before, "peak_v": peak,
                  "load_dump_class": bool(load_dump),
                  "over_absmax": bool(load_dump and plausible
                                      and peak > V_ABSMAX)}
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

    def __init__(self, name, node, c_out, droop_scale=1.0, v0_offset_v=0.0):
        self.name = name
        self.node = node
        self.c_out = c_out
        # PART A (2026-09-01): this channel's static no-load voltage offset about
        # V0_NOLOAD, in volts.  0.0 is the SYMMETRIC chain and reproduces every
        # trace recorded before the asymmetry mode existed.  See the PART A
        # constants banner for the fit and its sign convention.
        self.v0_offset_v = float(v0_offset_v)
        #: THE ONE SCALING POINT of the droop realization (see DROOP_SCALE).
        #: 1.0 is the DESIGN chain and is the default everywhere; anything else
        #: is an empirical rescale of the realized droop resistance and does
        #: NOT change the chain's structure, its clip, or the network.
        self.droop_scale = float(droop_scale)
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
        #
        # `self.droop_scale` (2026-09-01) is 1.0 for the DESIGN chain — the
        # expression is then arithmetically identical to every run recorded
        # before the mode existed — and DROOP_SCALE["measured"] when the run
        # asked for the bench-measured realization.  It is the ONLY point the
        # mode touches; see the DROOP_SCALE banner for the anchor and for what
        # the mode does and does not claim.
        self.r_droop = max(0.0, RE_MAX * g_code * self.droop_scale)
        # OPA197 output ceiling on the bodged 5 V rail caps the achievable droop
        # excursion at (R_D1/R_inj)*V_OP_CEIL; beyond it the droop stops growing.
        # DELIBERATELY NOT SCALED with `droop_scale`: the ceiling is a hard
        # op-amp output voltage mapped through the FB divider, and the mode
        # makes no claim about where the gap lives, so the less invented of the
        # two readings is kept.  The choice is INERT in practice — the ceiling
        # is (215k/53.6k)*4.9 = 19.66 V of droop excursion, which at the design
        # 0.60 ohm/channel needs ~32.8 A and in measured mode ~130 A.  Neither
        # is reachable behind I_OUT_MAX = 6.0 A, so no shipped trace can
        # distinguish the two readings.
        drop_max = (R_D1 / R_INJ) * V_OP_CEIL
        if self.r_droop * max(i_ch, 0.0) > drop_max:
            self.v_clip = drop_max
        else:
            self.v_clip = None
        # No-load regulation target, reached through the validated first-order
        # voltage-loop lag tau_r.
        # PART A: `v0_offset_v` shifts THIS channel's regulation target only.  It
        # is inside the max() with the body-diode passthrough because a chain
        # whose input already exceeds its own regulation point is passing, not
        # regulating, and the offset is a property of the regulation point.
        target = max(V0_NOLOAD + self.v0_offset_v, v_in - V_BODY_DIODE)
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
                 fuel_cell=None, battery=None, droop_mode="design",
                 asymmetry_mode=ASYMMETRY_MODE_DEFAULT, substep_pin=None):
        if trace_config not in TRACE_L_NH:
            raise ValueError(f"trace_config must be one of {sorted(TRACE_L_NH)}")
        if droop_mode not in DROOP_SCALE:
            raise ValueError("droop_mode must be one of %s" % (DROOP_MODES,))
        if asymmetry_mode not in ASYMMETRY_MODES:
            raise ValueError("asymmetry_mode must be one of %s"
                             % (ASYMMETRY_MODES,))
        # DEFAULT "design": every baseline recorded before this switch existed
        # is reproduced bit-for-bit, which is the load-bearing property (a
        # regression test pins it).  See the DROOP_SCALE banner.
        self.droop_mode = droop_mode
        self.droop_scale = DROOP_SCALE[droop_mode]
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
        # Per-node bleed conductance, resolved from the module globals AT
        # CONSTRUCTION so a probe or a test can place the process in another
        # bleed era with a monkeypatch of the two constants and then build a
        # simulator, exactly as the ETA_CHG era switch works.
        self.g_bleed = node_bleed_conductances()

        # ── PART A: converter asymmetry ──────────────────────────────────────
        # Resolved HERE, after `self.noise` is assigned, because the DeltaV0 to
        # inject is a function of the INA zero offsets this run actually
        # injects (F3) — which live on the NoiseConfig when there is one and
        # are zero when there is not.  The two per-channel droop scales COMPOSE
        # MULTIPLICATIVELY with the `--droop` mode scale: the mode sets the
        # realization level, the asymmetry sets the FC/BT ratio about it, and
        # BT = 1.000 keeps the measured anchor.  The VOLTAGE is scaled by the
        # same mode scale (F2), so the SHARE deviation — the quantity the fit
        # actually measured — is invariant across droop modes.
        self.asymmetry_mode = asymmetry_mode
        _off = getattr(self.noise, "ina_zero_offset", None) or {}
        self.asym_ina_offset_fc = float(_off.get("I_fc", 0.0))
        self.asym_ina_offset_bt = float(_off.get("I_batt", 0.0))
        (self.asym_v0_offset_fc, self.asym_v0_offset_bt,
         self.asym_droop_scale_fc, self.asym_droop_scale_bt) = asymmetry_params(
            asymmetry_mode, self.asym_ina_offset_fc, self.asym_ina_offset_bt,
            droop_scale=self.droop_scale)
        self.asym_dv0_v = self.asym_v0_offset_fc - self.asym_v0_offset_bt

        self.boost_fc = Boost("FC", N_OFC, C_BOOST_OUT_FC,
                              droop_scale=self.droop_scale * self.asym_droop_scale_fc,
                              v0_offset_v=self.asym_v0_offset_fc)
        self.boost_bt = Boost("BT", N_OBT, C_BOOST_OUT_BT,
                              droop_scale=self.droop_scale * self.asym_droop_scale_bt,
                              v0_offset_v=self.asym_v0_offset_bt)

        self.switches = {
            "FC_BUS": Rt1987("FC_BUS", N_OFC, N_BUS, CSS_NF["FC_BUS"], C_VBUS,
                             r_series=R_SHUNT),
            "BT_BUS": Rt1987("BT_BUS", N_OBT, N_BUS, CSS_NF["BT_BUS"], C_VBUS,
                             r_series=R_SHUNT),
            "MOT_PWR": Rt1987("MOT_PWR", N_BUS, N_MOT, CSS_NF["MOT_PWR"],
                              C_MOT_LOCAL + c_vesc_f, strict_forward=True),
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
            "REGEN": Rt1987("REGEN", N_MOT, N_CHG, CSS_NF["REGEN"], C_CHG_NODE,
                            strict_forward=True),
            "FC_CHARGE": Rt1987("FC_CHARGE", N_BUS, N_CHG, CSS_NF["FC_CHARGE"],
                                C_CHG_NODE, strict_forward=True),
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

        # PART B2 (C1 round, 2026-09-01): a COUNTING list.  hil_plant_sim
        # drains and TRIMS this list every tick (`del electrical.events[:]`),
        # so `len(self.events)` and a kind census taken over it report only
        # whatever accumulated since the last drain -- near-zero on a normal
        # exit.  `_EventLog` keeps the durable totals at the one place every
        # event passes through, so summary()'s `events` / `event_kinds` are the
        # whole run's figures and not a trimmed-list artifact.
        self.events = _EventLog()
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
        self.chopper_peak_w = 0.0       # W, worst instantaneous V_rgn*i_dump while clamping
        self._chopper_over = False      # once-per-excursion latch for chopper_over_power
        # ── WP-C regen accounting ───────────────────────────────────────────
        self.p_regen_w = 0.0            # W, electrical power injected on N_MOT this tick
        self.regen_energy_j = 0.0       # J, cumulative electrical energy injected
        self.chopper_energy_j = 0.0     # J, cumulative energy burnt in the clamp
        self.chopper_episodes = 0       # count of coalesced clamp episodes
        self._chop_ev = None            # in-flight chopper_clamp event dict
        self._chop_end_t = None         # time the last episode stopped conducting
        self.numeric_fault = False      # M2: sticky -- set once, never cleared
        self.neg_clamp_count = 0        # M2: diagnostic counter of negative-node clamps
        self.aux_dropout_ticks = 0      # count of substeps the V_AUX_DROPOUT_V floor
                                         # withheld the i_aux stamp (dark/collapsed bus)

        self.t = 0.0
        self.achieved_substep_hz = 0.0
        # `substep_pin` (2026-09-02): DISABLE the adaptive re-derivation and run
        # exactly this many substeps every tick.  The campaign path never sets
        # it and stays adaptive.  It exists because `step()` re-derives
        # `_n_sub` from a wall-clock EWMA at the END of every tick, so a test
        # that assigned `sim._n_sub` after each step was still running the
        # FIRST substep of the next tick at whatever count the host load had
        # produced.  Two byte-identity tests flaked on exactly that
        # (`test_asymmetry_off_is_byte_identical_to_a_symmetric_baseline` and
        # `test_eta_chg_is_inert_on_a_charge_free_trace`): the resolution, and
        # therefore the trace, depended on machine load.  With the pin set the
        # engine is deterministic in the substep count and those comparisons
        # are exact.
        self.substep_pin = None if substep_pin is None else max(1, int(substep_pin))
        self._n_sub = 8 if self.substep_pin is None else self.substep_pin
        # `n_sub_last` (2026-09-02, review L2): the substep count the LAST
        # completed step() actually ran with.  `_n_sub` is re-derived at the END
        # of step() from the measured cost, so it is the count the NEXT tick
        # will use — reading it after step() (as the CSV column and the status
        # line did) logs a resolution that was never applied to the row beside
        # it.  Initialized to the same starting value, so a reader before the
        # first step() sees the count that step would use.
        self.n_sub_last = self._n_sub
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
        # WP-C: electrical regen power arriving on V-MOT this tick [W], >= 0.
        # Absent key == 0.0, so every pre-WP-C caller (and every test that builds
        # its own actuator dict) keeps its exact behaviour.
        self.p_regen_w = max(0.0, float(actuators.get("p_regen_w", 0.0)))

        n = self._n_sub
        self.n_sub_last = n         # L2: what THIS tick ran (see __init__)
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
        # ... unless `substep_pin` is set, in which case the resolution is the
        # operator's and the wall clock does not get a vote (see __init__).
        if self.substep_pin is not None:
            self._n_sub = self.substep_pin
        else:
            self._n_sub = max(1, min(self.N_SUB_MAX,
                                     n_pref if n_budget >= n_pref else n_budget))
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
        #
        # Output-side CONFIRMED 2026-08-31 against the schematic (sheets 1-2:
        # TPS61288 VOUT -> VOUT-FC/BT -> INA253 IS+ -> IS- -> VBUS-FC/BT ->
        # RT1987 VIN); do not re-open.
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
            G[i][i] += self.g_bleed[i] + self.c_node[i] / h
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
        # V_AUX_DROPOUT_V floor (2026-09-03, physics review N8): below 5 V
        # everything on the bus shuts down anyway, so the housekeeping sink
        # (and any scenario preload riding on self.i_aux — see I_AUX_A) must
        # NOT keep draining a dark node.  Gated on `v[N_BUS]`, which at this
        # point in _substep() is still the PREVIOUS substep's solved value
        # (self.v has not been overwritten yet — new_v is assigned later, at
        # the `_solve(G, J)` call below) — the same "stamp from the previous
        # substep's node voltage" convention every other load/source element
        # in this method already follows (g_mot, the regen Norton pair, the
        # charger chord, the chopper clamp), so this adds no new algebraic
        # loop.  At v[N_BUS] >= V_AUX_DROPOUT_V the stamp is bit-identical to
        # the pre-floor form.
        if v[N_BUS] >= V_AUX_DROPOUT_V:
            J[N_BUS] -= self.i_aux
        else:
            self.aux_dropout_ticks += 1
        # Motor draw/regen sits on the V-MOT node, behind MOT_PWR, through the 470 uF
        # ESR.  H1 FIX: this was previously stamped as an IDEAL current source
        # (J[N_MOT] -= i_motor) -- fine for a positive (motoring) draw, but for a
        # NEGATIVE (regen) current with MOT_PWR open, the node has only its own
        # bleed for company (2 kOhm when this fix was written; 60 kOhm since the
        # 2026-09-02 per-node ruling, which makes the runaway 30x FASTER, not
        # slower) and an ideal source into that is unbounded: reproduced,
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
        # ── Regen source on V-MOT (WP-C, 2026-09-01) ────────────────────────
        # Braking energy off the flywheel, delivered by the VESC into the motor
        # node.  Bounded Norton (see the V_REGEN_OC_MAX banner): the pair
        # (g_reg, i_reg + g_reg*v_prev) delivers exactly i_reg at v == v_prev and
        # exactly zero at V_REGEN_OC_MAX, so the element is strictly passive above
        # that bound and cannot run the node away the way the pre-H1 ideal motor
        # source did.  Note this element is deliberately NOT gated on MOT_PWR: the
        # VESC hangs on V-MOT and the plant only reports regen power while the
        # switch is closed (that is where f_drive is gated), so gating twice would
        # hide a plant/engine disagreement instead of exposing it.
        i_regen_stamped = 0.0
        if self.p_regen_w > 0.0:
            v_prev = max(v[N_MOT], V_MOT_LOAD_FLOOR)
            headroom = V_REGEN_OC_MAX - v_prev
            if headroom > 0.0:
                i_regen_stamped = min(self.p_regen_w / v_prev, REGEN_I_SRC_MAX_A)
                g_reg = i_regen_stamped / headroom
                G[N_MOT][N_MOT] += g_reg
                J[N_MOT] += i_regen_stamped + g_reg * v_prev
        if i_charge:
            # The charger input is the single shared VCHG-IN node — both the
            # FC-charge and regen paths land there (schematic sheet 4).
            #
            # ── ENERGY-CONSERVING CHARGER (2026-09-01, operator ruling) ─────
            # Until this round the stamp was `J[N_CHG] -= i_charge`, i.e. the
            # module was a 1:1 CURRENT repeater: the node gave up exactly the
            # current the pack received, so the model destroyed
            # i_charge*(V_chg - V_pack) — about 11 W on a 1.4 A charge window —
            # and over-drew the bus by roughly V_chg/V_pack.  The Ag105 is a
            # switching converter, so the conserved quantity is POWER:
            #     i_in = i_charge * V_pack / (ETA_CHG * V_chg)
            # The pack still receives exactly `i_charge` (see the
            # `i_charge_into_pack` line at the top of this method); only the
            # INPUT current changes.  ETA_CHG carries the datasheet citation.
            #
            # STAMP FORM: a CHORD CONDUCTANCE, exactly like the motor draw
            # above.  A true constant-power load has i(v) = P/v and therefore
            # NEGATIVE incremental conductance -P/v^2.  Stamping that
            # linearization would put a negative term on the diagonal of G — the
            # one form that can make the solve indefinite, which is the opposite
            # of what the H1 round was protecting against.  So the element is
            # stamped as the CHORD through the operating point instead:
            #     g_chg = i_in / v_prev,   i_in = i_charge*V_pack/(ETA_CHG*v_prev)
            # At v == v_prev this delivers exactly `i_in` (self-consistent,
            # g*v_prev == i_in), the diagonal term is POSITIVE (so the solve
            # stays positive-definite and the H1 runaway class is closed), and
            # the delivered current SHRINKS as the node sags instead of holding
            # a fixed draw into a collapsing rail — self-limiting, which a
            # current source is not.  It re-linearizes every substep, and at
            # h <= 50 us against the 10 uF charger node the lag is negligible.
            # (The retired current-source form was described here as "the same
            # pattern as the regen Norton source": it was not.  The regen source
            # is a two-element Norton pair with its own zero-crossing bound; the
            # charger is a load and belongs with `g_mot`.)
            #
            # The V_CHG_LOAD_FLOOR floor bounds the division on a dark node.  It
            # is the module's own minimum input voltage (see the constant), not
            # an arbitrary numerical epsilon: below it the plant carries no
            # charge current at all, so the stamp is bounded at ~2.98 A and the
            # 1-to-8 V band is never an operating point.
            v_chg_prev = max(v[N_CHG], V_CHG_LOAD_FLOOR)
            i_in = i_charge * v_bt_term / (ETA_CHG * v_chg_prev)
            G[N_CHG][N_CHG] += i_in / v_chg_prev

        # Regen chopper: autonomous TL431/BSP170P clamp into 47 ohm.  It sits
        # directly on V-MOT (the regen node IS the motor node; schematic sheet 4),
        # so it does NOT couple to V_bus through the REGEN switch.
        # ⚠️ CORRECTED 2026-09-02 (review PLANT-R1-F2).  This comment used to say
        # it DOES couple through a closed MOT_PWR, and predicted ~0.03-0.06 V of
        # bus sag from the shunt's ~0.385 A.  THAT IS UNREACHABLE IN THIS MODEL
        # AND WAS NEVER MEASURED: MOT_PWR is instantiated `strict_forward=True`,
        # so the link is stamped only while V_bus - V_MOT >= RT_V_FWD, and at the
        # clamp V_MOT is 18.135 V — above V_bus, and above the 17.5 V
        # LIMIT_V_BUS_MAX latch a bus that high would trip anyway.  The measured
        # bus sag while clamping is < 1e-5 V, and deleting the BUS<->MOT link
        # entirely changes it by 0 J.  The bench observation "V_rgn 13.3 ->
        # 18.1 V held, V_bus unmoved" (CLAUDE.md 2026-08-17b) is reproduced
        # because the two nodes are DECOUPLED at the clamp, not because a small
        # coupling happens to be small.
        # The forward direction is a different matter and is real: AFTER the
        # clamp releases, V_bus rises back above V_MOT and MOT_PWR conducts
        # bus -> motor node, which is the documented 0.088059 J / 6.28 % of a
        # braking window's charger input (see hil_plant_sim.py's charger cap).
        # WP-C: linear-regulating clamp (see the R_CHOPPER_REG banner).  Stamped
        # from the previous substep's node voltage like every other mode decision
        # in this engine.  Below saturation it is a Norton clamp referenced to
        # V_CHOPPER_TRIP (i = (v - trip)/R_reg); at and above saturation it
        # degrades to the bare dump resistor, which is the pre-WP-C stamp.
        self.chopper_active = v[N_MOT] > V_CHOPPER_TRIP
        if self.chopper_active:
            g_reg = 1.0 / R_CHOPPER_REG
            if (v[N_MOT] - V_CHOPPER_TRIP) * g_reg >= v[N_MOT] / R_CHOPPER:
                G[N_MOT][N_MOT] += 1.0 / R_CHOPPER          # FET saturated
            else:
                G[N_MOT][N_MOT] += g_reg
                J[N_MOT] += g_reg * V_CHOPPER_TRIP

        new_v = _solve(G, J)
        # WP-C regen energy actually DELIVERED into the node this substep, from the
        # Norton pair's own constitutive law i(v) = i_reg + g_reg*(v_prev - v).
        if i_regen_stamped > 0.0 and math.isfinite(new_v[N_MOT]):
            v_prev = max(v[N_MOT], V_MOT_LOAD_FLOOR)
            g_reg = i_regen_stamped / (V_REGEN_OC_MAX - v_prev)
            i_del = max(0.0, i_regen_stamped + g_reg * (v_prev - new_v[N_MOT]))
            self.regen_energy_j += i_del * max(0.0, new_v[N_MOT]) * h
        # Chopper dissipation check — THE reason the chopper is simulated at all:
        # whether V_rgn^2 / 47 Ω ever exceeds the dump resistor's 20 W rating.
        # Computed from the SOLVED node voltage (the clamp conductance above was
        # stamped from the pre-solve voltage, so this is the consistent pairing).
        if self.chopper_active and math.isfinite(new_v[N_MOT]):
            # WP-C: dissipation is v * i_dump through the SHARED clamp law, so the
            # regulating region is accounted honestly instead of being charged the
            # saturated v^2/R.  At saturation the two forms coincide exactly.
            p_chop = max(0.0, new_v[N_MOT]) * chopper_dump_current(new_v[N_MOT])
            self.chopper_energy_j += p_chop * h
            self._chopper_episode(p_chop, new_v[N_MOT], h)
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

    # ── chopper episode bookkeeping (WP-C) ───────────────────────────────────
    def _chopper_episode(self, p_chop, v_node, h):
        """Fold this conducting substep into a coalesced `chopper_clamp` event.

        ONE event per braking episode, not one per substep: a clamp that is holding
        a node conducts on every substep for the whole episode, and the raw stream
        would be tens of thousands of dicts.  Consecutive conducting substeps
        separated by less than EVENT_COALESCE_S are the same episode (the clamp
        legitimately drops out for a substep or two whenever the source current
        dips under the regulator's demand).  `chopper_clamp` is a NEW kind and is
        deliberately distinct from `chopper_over_power`, which the suite scores as
        a FAILURE — a clamp doing its job is an objective, not a defect.
        """
        if (self._chop_ev is not None and self._chop_end_t is not None
                and (self.t - self._chop_end_t) <= EVENT_COALESCE_S):
            ev = self._chop_ev
        else:
            # PART B2: a NEW episode. Close the previous one first, then start
            # this one WITHOUT appending it yet — see close_chopper_episode().
            self.close_chopper_episode()
            ev = {"t": self.t, "kind": "chopper_clamp", "node": "MOT",
                  "dur_s": 0.0, "energy_j": 0.0, "peak_w": 0.0, "peak_v": 0.0}
            self._chop_ev = ev
            self.chopper_episodes += 1
        ev["dur_s"] += h
        ev["energy_j"] += p_chop * h
        ev["peak_w"] = max(ev["peak_w"], p_chop)
        ev["peak_v"] = max(ev["peak_v"], v_node)
        ev["t_end"] = self.t
        self._chop_end_t = self.t

    def close_chopper_episode(self):
        """Append the in-flight `chopper_clamp` episode, now that it is whole.

        PART B2 (C1 round, 2026-09-01) — THE DEFECT THIS FIXES. The episode dict
        used to be appended to `self.events` on its FIRST conducting substep and
        then mutated in place for the rest of the episode. The consumer
        (hil_plant_sim's `_drain_electrical_events`) serializes and TRIMS the
        list every 1 ms tick, so the dict was written out carrying only its
        first partial tick — `dur_s` 0.25-0.9 ms and a correspondingly tiny
        `energy_j` — and every later mutation landed on an object nothing would
        ever read again. A 1148 ms clamp window therefore reported sub-millijoule
        energy in a sidecar whose whole purpose is the energy accounting.

        FIX CHOSEN: emit ONCE, at episode END. The alternative the spec allowed —
        re-emitting an updated copy on every drain behind an `update: true` flag —
        was rejected on two grounds. It multiplies a single 1148 ms episode into
        ~1148 sidecar rows, and it makes every consumer responsible for
        de-duplicating by taking the last row, which is a contract that fails
        silently when a consumer forgets. Emitting once means an event in the
        sidecar is, unconditionally, a whole episode.

        COST, stated: an episode still open when the process is SIGKILLed is
        never emitted, whereas the old code emitted a (wrong) partial record for
        it. That is accepted — the run's durable energy accounting lives in
        `chopper_energy_j` / `chopper_episodes` on the summary, neither of which
        depends on the event stream, and a truncated record that under-reports
        by three orders of magnitude is worse evidence than no record.
        """
        if self._chop_ev is not None:
            self.events.append(self._chop_ev)
            self._chop_ev = None

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
        # PART B2: durable totals from the counting log, NOT a census over the
        # live list (which the consumer trims every tick).
        kinds = dict(getattr(self.events, "kinds", {}))
        n_events = getattr(self.events, "total", len(self.events))
        return {
            "achieved_substep_hz": self.achieved_substep_hz,
            "substeps_per_tick": self._n_sub,
            "events": n_events,
            "event_kinds": kinds,
            "trace_config": self.trace_config,
            # PART A provenance: which asymmetry the two chains actually carried.
            "asymmetry_mode": self.asymmetry_mode,
            "asymmetry_dv0_v": self.asym_dv0_v,
            "asymmetry_droop_scale_fc": self.asym_droop_scale_fc,
            "asymmetry_droop_scale_bt": self.asym_droop_scale_bt,
            "numeric_fault": self.numeric_fault,          # M2: sticky
            "neg_clamp_count": self.neg_clamp_count,      # M2: diagnostic
            "aux_dropout_ticks": self.aux_dropout_ticks,  # V_AUX_DROPOUT_V floor engagements
            "chopper_peak_w": self.chopper_peak_w,        # worst V_rgn*i_dump while clamping
            # WP-C energy accounting (see docs/HIL_PLANT.md "Regen model").
            "regen_energy_j": self.regen_energy_j,
            "chopper_energy_j": self.chopper_energy_j,
            "chopper_episodes": self.chopper_episodes,
        }
