"""Offline model of the firmware's share-delivery governor.

PURPOSE
-------
This module reproduces, in stdlib Python, the firmware path that sits between a
commanded ``power_share_setpoint`` and the droop ratio physically written to the
two AD5443 multiplying DACs. An offline energy-management walk that applies the
commanded share directly is measuring a firmware that does not exist: the share
loop is gated on source current, it holds the last converged split below
the closed-loop exit (0.25 A at fw v27 rev 2, 0.55 A through fw v26), it
clips the reference through a minority-current governor on BOTH the closed and
the open-loop paths, it schedules the droop scale k_d on the load, it
rate-limits every ratio move, and it may take a channel off the bus outright.
Two walks in this repository have been wrong for exactly that reason
(``tools/hil_plant_sim.py``, the "SHARE AUTHORITY DISAPPEARS BELOW 0.55 A"
banner).

The firmware is the authority. Every constant below is transcribed from
``teensy_controller/teensy_controller.ino`` with its line number, and every mode
decision follows the order of ``powerBalance()``. The PhD student's
``references/EMS/SDP_EnergyManagement_Governor2.m`` was consulted as a
cross-reference only; none of its numbers are used, because it is a full-scale
re-derivation on a 1.136 ms tick with placeholder constants.

PORTED FIRMWARE SITES
---------------------
``updateShareSetpointCutoff()``   .ino:9781-10078  -> ``_setpoint_cutoff()``
``updateShareSlewMode()``         .ino:10035-10064 -> ``_slew_mode()``
``powerBalance()``                .ino:10079-10378 -> ``GovernorModel.step()``
``applyShareRatio()``             .ino:10379-10537 -> ``_apply_share_ratio()``
``applyShareCurrentCeilings()``   .ino:10273-10313 -> ``_apply_share_current_ceilings()``
``clearShareCeilingState()``      .ino:10215-10218 -> ``_clear_ceiling_state()``
``setDroopMdac()``                .ino:10740-10748 -> ``_mdac_codes()``
``busSwitchBlanked()``            .ino:3406-3416   -> ``_blanked()``
``resetShareControllerCore()``    .ino:10577-10604 -> ``_reset_controller_core()``
``shareFeedforwardClipTarget()``  .ino:10810-10822 -> ``feedforward_clip_target()``
``shareDroopScaleTarget()``       .ino:10847-10855 -> ``droop_scale_target()``
``updateShareDroopScale()``       .ino:10856-10866 -> ``_update_droop_scale()``
``armShareBatteryOnlyStart()``    .ino:11737-11739 -> ``arm_battery_only_start()``

fw v27 rev 2 (2026-09-03) IS MIRRORED IN FULL: the conduction floor at 0.15 A
and every quantity derived from it (the 0.30 A closed-loop gate, the 0.25 A
exit, the 0.906 A droop-scale crossover, the 1.4706 A ceiling reachability), the
battery-only start with its frozen-path filter advance, the relaxing feedforward
clip with its isolated-channel bypass and accumulating proposal, the
load-scheduled droop scale with its hysteresis and fractional slew, and the
g-guard count at the write site. See ``docs/fw27_governor_package.md``.
⚠️ THE MEASURED-AGREEMENT TABLE BELOW IS A fw v21-v26 RECORD. It was scored
against boards that ran the fixed 0.30 ohm scale, a 0.60 A gate and an unclipped
feedforward walk, so it is evidence about the PORT, not about fw v27 rev 2. It
is re-scored on the first fw v27 campaign (campaign G).

FIDELITY BOUNDARIES
-------------------
1. THE YOULA SHARE CONTROLLER IS NOT PORTED. ``share_controller.h`` is on the
   do-not-change list and its difference equations are not reproduced here.
   The closed loop is modelled as: the applied ratio walks toward the governed
   reference at this tick's slew ceiling, and once it has arrived the loop holds
   the delivered share at the governed reference. The bench measurement that
   licenses this is the share-sweep whitepaper's hold-window mean error of less
   than 1e-3 (``docs/share_sweep_whitepaper/main.tex:150-158``). Closed-loop
   TRANSIENTS other than the slew limit are therefore not modelled. The optional
   ``conv_tau_s`` parameter inserts a first-order lag between the governed
   reference and the controller's demanded ratio so a later round can fit one;
   it defaults to 0 (arrival is instantaneous once the slew limiter allows it).
2. THE PLANT IS THE STATIC DROOP LAW. Delivered share follows the two-branch
   divider of the droop network,
   ``alpha = (dV0/I_tot + R_BT) / (R_FC + R_BT)`` with
   ``R_FC = rho*k_d/r + R_f`` and ``R_BT = k_d/(1-r) + R_f``
   (``docs/modeling/governor_split_law_20260903.md``; the M2 fit pair of
   ``docs/modeling/converter_asymmetry_20260901.md`` section 9 plus the common
   series floor ``hil_electrical.py:277``). The three parameters ``dv0_v``,
   ``droop_scale_fc`` and ``r_series_ohm`` default to 0.0 / 1.0 / 0.0, at which
   the law is exactly ``alpha = r``; the plant's values are 0.013522 V /
   0.9434 / 0.033 ohm. THE 2026-09-03 CORRECTION: this module carried only the
   ``dV0`` term (``alpha = r + dV0*r*(1-r)/(k_d*I_tot)``,
   ``controller_design/system_model.md`` lines 105-110 and 189-203), which
   mis-inverts the ratio by up to +10.5 % at low share and is wrong with the
   asymmetry off as well. In closed loop
   the integral action absorbs the offset, so the model inverts the law to find
   the ratio that delivers the reference. In open-loop hold or feedforward there
   is no integral action, so the law is applied forward to the held ratio.
3. BUS AND CONVERTER STATES ARE INPUTS, NOT MODEL PROPERTY. The firmware's bus
   switches are written by ``chargingControl()``, ``doState2()`` and the
   operator as well as by the share loop, so ``step()`` accepts the observed
   switch states each tick and returns the governor's own request. The caller
   composes the two.
4. NO FAULT PATH, NO STATE MACHINE. State 99 teardown, the UV backoff and the
   motor loop are outside this model.

MEASURED AGREEMENT — ALL 28 RUNS OF CAMPAIGN 20260901_080905
------------------------------------------------------------
``replay_governor()`` over every scenario CSV, scored on ``state == 2`` ticks,
model seeded from the first observed MDAC pair, ``conv_tau_s = 0``. ``rms_mv``
is the residual restricted to the +/-50-tick neighbourhood of ticks where the
OBSERVED ratio moved; ``mv`` is the count of such ticks.

    run                 verdict     scored     mv       rms    rms_mv     max
    bringup             UNSCORED         0      0       nan       nan     nan
    charge-cruise       SCORED        5723     10   0.01499   0.10809  0.3500
    charge-fault        SCORED       21993      8   0.00695   0.09923  0.3500
    charge-regen        SCORED       39983      6   0.00001   0.00006  0.0002
    charge-to-full      SCORED      126985     10   0.00318   0.10809  0.3500
    comm-loss           UNSCORED         0      0       nan       nan     nan
    ems-dp-replay       SCORED       55001   6069   0.00576   0.00712  0.1523
    ems-drive-cycle     UNSCORED     52002      0   0.00000       nan  0.0000
    ems-ftp75-5050      UNSCORED    342998      0   0.00000       nan  0.0000
    ems-ftp75-sdp       SCORED      343010  50075   0.00536   0.00539  0.1716
    ems-ftp75-socband   SCORED      343003  42563   0.00615   0.00639  0.0086
    ems-sdp-braking     SCORED       62464   4947   0.08169   0.04021  0.7001
    ems-sdp-cross       SCORED      193005   9694   0.02447   0.00737  0.3500
    ems-sdp             SCORED       54994   6922   0.01027   0.01396  0.7001
    ems-soc-band        SCORED       55007   3683   0.00704   0.01167  0.3500
    ems-y-b00-v1        SCORED       42996    708   0.00059   0.00142  0.0062
    ems-y-b00-v3        SCORED       43007   2761   0.01297   0.01141  0.1703
    ems-y-b30-v1        SCORED       42987   5676   0.00727   0.00983  0.2054
    ems-y-b30-v3        SCORED       43018   5086   0.00725   0.00980  0.1959
    handoff-sag         UNSCORED     20985      0   0.00000       nan  0.0000
    mppt-tracking       SCORED       39997    288   0.02228   0.07539  0.3500
    pi-silence          UNSCORED      5494      0   0.00000       nan  0.0000
    sag                 UNSCORED         0      0       nan       nan     nan
    scp-inrush          UNSCORED         0      0       nan       nan     nan
    share-staircase     SCORED       40998   2481   0.00701   0.01052  0.2217
    soc-depletion       UNSCORED    267701      0   0.00000       nan  0.0000
    steady              UNSCORED         0      0       nan       nan     nan
    step-load           UNSCORED         0      0       nan       nan     nan

HONEST RANGE: 17 of 28 runs carry any ratio motion at all and are therefore the
only ones that say anything. Across those, whole-run RMS spans 0.00001 to
0.08169 and the moving-window RMS spans 0.00006 to 0.10809. THE HEADLINE IS THE
RANGE, NOT ITS BEST MEMBER. Two distinct populations sit inside it:

  * Runs with sustained ratio motion (the ems-* families, share-staircase):
    whole-run RMS 0.005 to 0.025, with ``ems-sdp-braking`` the exception below.
  * Runs with a handful of moving ticks around a charge-window transition
    (charge-cruise, charge-fault, charge-to-full, mppt-tracking): a low
    whole-run RMS but a moving-window RMS of 0.08 to 0.11, because essentially
    all their motion IS the transition the model aligns worst on. Their
    whole-run figures must not be quoted as agreement.

``ems-sdp-braking`` (RMS 0.0817, max 0.7001) IS OUTSIDE THE LICENSED FIDELITY
CLAIM and must not be predicted with this model. It is the campaign run in which
the fw <= 24 ``applyShareRatio()`` hazard fired: FC_BUS was cut with 0.6371 A
standing, the bus collapsed 14.56 -> 12.40 V and OC_BT latched (CLAUDE.md,
2026-09-01c). The residual accumulates across charge-window entries and exits,
where the board's wound-down ratio persists and the model's does not — dynamics
this model does not contain, not a parameter that can be fitted.

CONV_TAU_S FIT — REPORTED, NOT ADOPTED
-------------------------------------
Whole-run RMS against ``conv_tau_s`` (seconds), same nine runs:

    run                 0.0      0.002    0.005    0.01     0.02     0.05
    ems-sdp             0.01027  0.00536  0.00533  0.00538  0.00581  0.00784
    ems-sdp-braking     0.08169  0.08517  0.06948  0.05729  0.03494  0.04533
    ems-sdp-cross       0.02447  0.02443  0.02323  0.02208  0.02000  0.01348
    ems-ftp75-sdp       0.00536  0.00529  0.00520  0.00516  0.00533  0.00623
    ems-soc-band        0.00704  0.00682  0.00628  0.00652  0.00841  0.01233
    ems-dp-replay       0.00576  0.00565  0.00551  0.00542  0.00554  0.00640
    share-staircase     0.00701  0.00658  0.00577  0.00490  0.00474  0.00751
    ems-ftp75-socband   0.00615  0.00615  0.00615  0.00615  0.00616  0.00617
    ems-y-b30-v3        0.00725  0.00647  0.00517  0.00427  0.00588  0.01242

Seven of the nine show a shallow optimum at 0.005 to 0.01 s and degrade beyond
it; the improvements are real but small (share-staircase 0.0070 -> 0.0049,
ems-y-b30-v3 0.0073 -> 0.0043, ems-sdp 0.0103 -> 0.0053). THE DEFAULT REMAINS
0.0. Two reasons. First, a 0.005 s lag is not independently measured — it is
fitted to these nine runs, and adopting it would launder a fit into a constant.
Second, the two runs that do NOT show that optimum are diagnostic:
``ems-ftp75-socband`` is flat to five decimals (its residual is not a lag at
all), and ``ems-sdp-braking`` improves MONOTONICALLY out to 0.02 s — a run
asking for ever more lag is missing dynamics, not carrying one, and fitting to
it would be exactly the single-run tuning this range exists to prevent.

STDLIB ONLY. This module is imported by the stdlib-only simulator; it must not
acquire dependencies.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# Firmware constants. Names are the firmware's, verbatim.
# ─────────────────────────────────────────────────────────────────────────────
_K_SNS = 0.1              # V/A  INA253A1 gain                       .ino:2166 block
_A_V = 5.02               # OPA197 gain                              .ino:2166 block
_RD1_OVER_RINJ = 215.0 / 53.6                                       # .ino:2163

GOV_CONST = {
    # Droop injection chain.
    "RE_MAX": _K_SNS * _A_V * _RD1_OVER_RINJ,   # 2.013619 ohm       .ino:2166
    "K_DROOP": 0.30,                            # ohm                .ino:2167
    "DROOP_R_MIN": 0.15,                        #                    .ino:2170
    "DROOP_R_MAX": 0.85,                        #                    .ino:2171
    # Share-loop gating.
    "SHARE_I_TOT_MIN_A": 0.075,                 # A                  .ino:2182
    # fw v27 rev 2 (2026-09-03): the light-load conduction floor moved 0.30 -> 0.15 A on the
    # operator's ruling. EVERYTHING below is derived from it and moves with it: the closed-loop
    # gate 2*I_min = 0.30 A, the exit 0.25 A, the minority clip band, the k_d crossover 0.906 A
    # and the fw v26 ceiling reachability. See docs/fw27_governor_package.md section 8.
    "SHARE_MINORITY_I_MIN_A": 0.15,             # A                  .ino:2392
    "SHARE_CUT_MAX_HANDOFF_A": 0.5,             # A                  .ino:2237
    "SHARE_GOV_OL_HYST_A": 0.05,                # A                  .ino:2245
    # Slew ceilings.
    "DROOP_RATIO_SLEW_PER_TICK": 0.02,          #                    .ino:2254
    "SHARE_HANDOFF_MIN_A": 0.15,                # A                  .ino:2274
    "DROOP_RATIO_SLEW_HANDOFF_PER_TICK": 0.002,  #                   .ino:2281
    "SHARE_HANDOFF_LIVE_A": 0.20,               # A                  .ino:2288
    "SHARE_HANDOFF_DWELL_MAX_TICKS": 175,       # ticks              .ino:2298
    "SHARE_GOV_FILT_ALPHA": 0.05,               # per tick           .ino:2303
    # Source current-ceiling governor (fw v26).
    "SHARE_GOV_I_FC_CEIL_A": 1.25,              # A (bus-side)       .ino:2406
    "SHARE_GOV_I_BT_CEIL_A": 2.70,              # A (bus-side)       .ino:2424
    "SHARE_GOV_CEIL_HYST_A": 0.05,              # A                  .ino:2430
    # Load-scheduled droop scale k_d (fw v27 rev 2).
    #   k_d(tot) = max(K_DROOP, RE_MAX * clamp(I_min/tot, DROOP_R_MIN, 0.5) * SHARE_KD_SAFETY)
    # slewed at SHARE_KD_SLEW_FRAC_PER_TICK against a hysteretic held sample of the governor's
    # filtered total (SHARE_KD_HYST_A). The last two are DERIVED in the firmware, not literals:
    #   SHARE_KD_HYST_A            = SHARE_GOV_OL_HYST_A                       .ino:2534
    #   SHARE_KD_SLEW_FRAC_PER_TICK = DROOP_RATIO_SLEW_PER_TICK / DROOP_R_MAX  .ino:2546
    "SHARE_KD_SAFETY": 0.9,                     #                    .ino:2528
    "SHARE_KD_HYST_A": 0.05,                    # A                  .ino:2534
    "SHARE_KD_SLEW_FRAC_PER_TICK": 0.02 / 0.85,  #                   .ino:2546
    # Battery-only start (fw v27 rev 2): the effective setpoint the arm feeds the setpoint latch.
    "SHARE_BATTERY_ONLY_SP": 0.0,               #                    .ino:2573
    # Actuation.
    "SHARE_CUTOFF_HYST": 0.01,                  #                    .ino:3258
    "SHARE_CUT_SURVIVOR_BLANK_MS": 30.0,        # ms                 .ino:3353
    "SHARE_SP_CHANGE_EPS": 1e-4,                #                    .ino:9756
    "MDAC_RES": 4095,                           # AD5443 12-bit      .ino:1845
    "MDAC_CMD_LOAD_UPDATE": 0x1000,             # control nibble     .ino:10746
    # Loop cadence. powerBalance() is gated on POWER_BAL_PERIOD_US and the
    # Youla controller is designed for the same 1 kHz.
    "POWER_BAL_PERIOD_US": 1000,                #                    .ino:2455
    # Controller reset seed. resetShareControlState() seeds 0.5.
    "SHARE_CTRL_R0": 0.5,                       #                    .ino:10605
}

_RE_MAX = GOV_CONST["RE_MAX"]
_R_MIN = GOV_CONST["DROOP_R_MIN"]
_R_MAX = GOV_CONST["DROOP_R_MAX"]

# Reachability threshold for the fw v26 fuel-cell ceiling (docs/fw26_current_
# ceiling_governor.md section 4.1.1; RE-DERIVED for fw v27 rev 2, .ino:2686-2696
# and docs/fw27_governor_package.md section 8.5). The minority-current clip runs
# FIRST, so the largest fuel-cell current the loop can command is
#     min(DROOP_R_MAX, 1 - SHARE_MINORITY_I_MIN_A/I_tot) * I_tot
#           = min(DROOP_R_MAX * I_tot, I_tot - SHARE_MINORITY_I_MIN_A)
# and the ceiling can bind only where BOTH terms exceed it:
#     DROOP_R_MAX * I_tot > CEIL      ->  I_tot > CEIL / DROOP_R_MAX = 1.4706 A
#     I_tot - I_min       > CEIL      ->  I_tot > CEIL + I_min       = 1.40 A
# ⚠️ THE GOVERNING TERM SWAPPED AT fw v27 rev 2. At I_min = 0.30 A the
# conduction-floor term was the tighter one and the threshold was 1.55 A; at
# 0.15 A the BAND EDGE governs and the threshold is 1.4706 A. The expression
# below is therefore the MAXIMUM of the two, written as the arithmetic rather
# than as whichever term happened to win, so a future retune of the floor cannot
# silently leave a wrong constant here.
CEILING_REACHABLE_I_TOT_A = max(
    GOV_CONST["SHARE_GOV_I_FC_CEIL_A"] / GOV_CONST["DROOP_R_MAX"],
    GOV_CONST["SHARE_GOV_I_FC_CEIL_A"] + GOV_CONST["SHARE_MINORITY_I_MIN_A"],
)   # 1.470588 A at the shipped constants

# Hoisted out of GOV_CONST for the per-tick path. `_apply_share_current_
# ceilings()` runs on EVERY closed-loop tick of every offline walk, and a dict
# lookup per constant per tick is measurable at the tick counts the MPC's roll
# jobs reach. The values are the dictionary's, read once at import, so there is
# no second declaration to drift.
_FC_CEIL_A = GOV_CONST["SHARE_GOV_I_FC_CEIL_A"]
_BT_CEIL_A = GOV_CONST["SHARE_GOV_I_BT_CEIL_A"]
_CEIL_HYST_A = GOV_CONST["SHARE_GOV_CEIL_HYST_A"]
_I_TOT_MIN_A = GOV_CONST["SHARE_I_TOT_MIN_A"]

MODE_FROZEN = "frozen_min_load"
MODE_LATCHED = "latched"
MODE_OPEN_HOLD = "open_hold"
MODE_OPEN_FF = "open_feedforward"
MODE_CLOSED = "closed"
# The F1 do-nothing return (.ino:10197): open-loop mode reached with an
# OUT-OF-BAND setpoint, which the setpoint latch owns. The loop writes NOTHING.
# Distinct from MODE_OPEN_FF, which is an actual slew-limited MDAC write, so a
# mode census cannot read a run's idle ticks as feedforward actuation.
MODE_OPEN_F1_IDLE = "open_f1_idle"

MODES = (MODE_FROZEN, MODE_LATCHED, MODE_OPEN_HOLD, MODE_OPEN_FF, MODE_CLOSED,
         MODE_OPEN_F1_IDLE)

# The modes on which the firmware performs no MDAC write at all. GovernorOut.wrote
# is derived from this set, so a caller can tell a commanded split from a
# phantom one.
NON_WRITING_MODES = frozenset({MODE_FROZEN, MODE_LATCHED, MODE_OPEN_HOLD,
                               MODE_OPEN_F1_IDLE})


def _constrain(x: float, lo: float, hi: float) -> float:
    """Arduino ``constrain()``. Note the firmware semantics with lo > hi: the
    macro evaluates ``x < lo ? lo : (x > hi ? hi : x)``, so an inverted pair
    returns ``lo``. ``powerBalance()`` relies on that (.ino:10265 comment)."""
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


# ─────────────────────────────────────────────────────────────────────────────
# State and per-tick result
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class GovernorState:
    """Every firmware variable the ported path reads or writes."""

    # powerBalance() / governor
    filt_total: float = 0.0            # share_govTotAFilt          .ino:9746
    closed_loop_mode: bool = False     # shareClosedLoopMode        .ino:9748
    closed_loop_run: bool = False      # shareClosedLoopRun         .ino:9749
    acted_sp: float = 0.5              # share_actedSp              .ino:9750
    sp_eff_prev: float = 0.5           # share_spEffPrev            .ino:9751
    r_prev: float = 0.5                # droopSlew_prev             .ino:9747

    # Topology claims
    iso_fc: bool = False               # shareIsoFC                 .ino:3252
    iso_bt: bool = False               # shareIsoBT                 .ino:3253
    sp_cut_fc: bool = False            # shareSpCutFC               .ino:3268 block
    sp_cut_bt: bool = False            # shareSpCutBT
    deferred_fc: bool = False          # shareCutDeferredFC         .ino:9788
    deferred_bt: bool = False          # shareCutDeferredBT
    latched: bool = False              # the return of updateShareSetpointCutoff()

    # Conduction-aware slew mode (updateShareSlewMode)
    handoff_i_fc_filt: float = 0.0     # shareHandoffIFcFilt        .ino:9968
    handoff_i_bt_filt: float = 0.0     # shareHandoffIBtFilt        .ino:9969
    dark_fc: bool = True               # shareHandoffDarkFC         .ino:9970
    dark_bt: bool = True               # shareHandoffDarkBT         .ino:9971
    handoff_dwell: int = 0             # shareHandoffDwell          .ino:9972
    handoff_prev_ratio: float = 0.5    # shareHandoffPrevRatio      .ino:9973
    slew_step: float = GOV_CONST["DROOP_RATIO_SLEW_HANDOFF_PER_TICK"]

    # Source current-ceiling governor (fw v26). Hysteretic, so the two flags
    # carry memory across ticks; they are dropped on every path that freezes
    # the share loop and on a reset (.ino:10202-10218).
    gov_fc_clamped: bool = False       # shareGovFcClamped          .ino:10202
    gov_bt_clamped: bool = False       # shareGovBtClamped          .ino:10203
    ceil_ticks: int = 0                # ticks with either flag set after the
                                       # clamp ran; the walk's `clamped` census

    # ── fw v27 rev 2 ────────────────────────────────────────────────────────
    # Load-scheduled droop scale. ``droop_kd`` is MDAC TRUTH, exactly like
    # ``r_prev``: it is the scale the gains currently on the AD5443s were
    # computed with, so ``resetShareControlState()`` deliberately does NOT
    # touch it (.ino:11720 comment). ``kd_sched_tot`` is the hysteretic HELD
    # sample of ``filt_total`` that the schedule reads; it is a load estimate
    # and IS zeroed with the filter.
    droop_kd: float = GOV_CONST["K_DROOP"]      # shareDroopKd       .ino:10809
    kd_sched_tot: float = 0.0                   # shareKdSchedTot    .ino:10361
    g_guard_count: int = 0                      # shareGGuardCount   .ino:10365
    # Battery-only start. ``armed`` is set at a profile boundary only
    # (``arm_battery_only_start()``); ``active`` is the per-tick derivation that
    # also requires an in-band commanded setpoint and no FC-charge window.
    batt_only_armed: bool = False               # shareBatteryOnlyArmed
    batt_only_active: bool = False              # shareBatteryOnlyActive
    # The feedforward PROPOSAL while a controller-initiated cut is outstanding.
    # NOT MDAC truth (an isolated tick writes nothing) — it is the accumulating
    # walk the iso bypass needs, because ``r_prev`` is frozen for the duration of
    # the cut. Re-anchored to ``r_prev`` on every non-isolated feedforward tick
    # and at each site that takes a cut (.ino:10809 block, section 12 of the
    # design record).
    iso_prop_ratio: float = 0.5                 # shareIsoPropRatio

    # Controller surrogate (see fidelity boundary 1)
    ctrl_out: float = 0.5

    # Switch beliefs and turn-on blanking (writeBusSwitch/busSwitchBlanked)
    sw_fc: bool = False
    sw_bt: bool = False
    rise_ms_fc: float = 0.0            # busSwitchRiseMsFC          .ino:3345
    rise_ms_bt: float = 0.0            # busSwitchRiseMsBT
    rise_seen_fc: bool = False         # busSwitchRiseSeenFC
    rise_seen_bt: bool = False         # busSwitchRiseSeenBT
    sw_init: bool = False              # first tick has no previous switch word

    # Diagnostics (.ino:3360 block — TICK counts, not episode counts)
    refused_load: int = 0              # shareCutRefusedLoad
    refused_blank: int = 0             # shareCutRefusedBlank
    ticks: int = 0
    mode_counts: dict = field(default_factory=lambda: {m: 0 for m in MODES})


@dataclass
class GovernorOut:
    r_applied: float
    mode: str
    fc_bus_req: bool
    bt_bus_req: bool
    cut_refused_load: bool
    cut_refused_blank: bool
    g_fc: float
    g_bt: float
    code_fc: int
    code_bt: int
    # fw v26 current-ceiling clamp flags, as of the end of this tick. Mirrored
    # on the board into HIL observation-frame aux bits 4/5, bench-log flags bit
    # 7 and the State-98 'S' dump. False on every tick that did not reach the
    # clamp (the clamp is cleared on all of those).
    ceil_fc: bool = False
    ceil_bt: bool = False
    # fw v27 rev 2 observables. ``k_d`` is the LIVE load-scheduled droop scale the
    # reported ``g_``/``code_`` fields were mapped through (bench-log v8 field
    # class LEVEL — read it, never difference it). ``g_clamp_count`` is the
    # saturating boot-monotonic count of MDAC writes whose commanded gain
    # exceeded full scale, i.e. the firmware's ``shareGGuardCount``.
    # ``batt_only`` is the arm's per-tick ACTIVE derivation.
    k_d: float = GOV_CONST["K_DROOP"]
    g_clamp_count: int = 0
    batt_only: bool = False
    # True when this tick actually reached setDroopMdac(). False on every
    # non-writing return (frozen, latched, hold, F1 idle) AND on a write that
    # applyShareRatio() abandoned because a channel is isolated (.ino:10492),
    # where the active channel keeps its previous gain. The reported g_/code_
    # fields then describe the STANDING split, not a fresh command.
    wrote: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# MDAC helpers
# ─────────────────────────────────────────────────────────────────────────────
def _mdac_code(gain: float) -> int:
    """``setDroopMdac()`` word for one channel (.ino:10746-10747).

    The firmware truncates ``gain*MDAC_res`` through a C cast, so this uses
    ``int()`` and not ``round()``."""
    g = _constrain(float(gain), 0.0, 1.0)
    return GOV_CONST["MDAC_CMD_LOAD_UPDATE"] | int(g * GOV_CONST["MDAC_RES"])


def mdac_fraction(word: Optional[int]) -> Optional[float]:
    """Recover the 0..1 droop-gain fraction from a raw AD5443 command word.

    Re-implemented locally rather than imported: ``governor_model`` must not
    depend on ``hil_plant_sim``. Semantics match ``hil_plant_sim.mdac_fraction``
    (.py:931) except that a missing word returns ``None`` instead of 0.0, so a
    caller can tell "no write recorded" from "zero scale"."""
    if word is None:
        return None
    w = int(word)
    if (w & 0xF000) != GOV_CONST["MDAC_CMD_LOAD_UPDATE"]:
        return 0.0
    return (w & 0x0FFF) / float(GOV_CONST["MDAC_RES"])


def ceiling_bounded_share(sp: float, i_tot: float) -> float:
    """Steady-state (hysteresis-free) image of ``applyShareCurrentCeilings()``.

    THE DELIVERED-SHARE SEMANTIC FOR THE OFFLINE DEMAND MODELS. The dynamic
    port is ``GovernorModel._apply_share_current_ceilings()``, which carries the
    ``SHARE_GOV_CEIL_HYST_A`` release memory. A stage-level demand model has no
    tick history, so it uses the converged bound instead: the hysteresis only
    delays a RELEASE, and a converged stage is either clamped or not.

    Order is the firmware's: battery lower bound first, fuel-cell upper bound
    second (so the fuel cell wins the infeasible pair above
    ``I_FC_CEIL + I_BT_CEIL`` = 3.95 A of total), then the droop band. The
    minority-current clip is the CALLER's, applied before this, exactly as
    ``powerBalance()`` does.

    AN OUT-OF-BAND COMMANDED SETPOINT IS NEVER CLAMPED. This is not a
    convenience: in the firmware an out-of-band setpoint is owned by
    ``updateShareSetpointCutoff()``, which either latches (freezing the whole
    share loop, so the clamp never runs) or defers (in which case
    ``powerBalance()`` suppresses the clamp explicitly and drops its flags).
    The open-loop path returns quietly on the same condition. There is
    therefore NO path through the firmware on which a setpoint outside
    ``[DROOP_R_MIN, DROOP_R_MAX]`` reaches the clamp, and a demand model whose
    share grid spans the full ``[0, 1]`` (the stochastic dynamic program's
    does) must not have its full-span single-source commands pulled into the
    droop band by this helper.

    Returns ``sp`` unmodified when neither ceiling is exceeded, so a demand
    model below the ceilings is bit-identical to its pre-fw-v26 self.

    ⚠️ THE REACHABILITY GUARD IS PART OF THE CONTRACT, NOT AN OPTIMISATION
    (2026-09-02).  The docstring above says the minority-current clip is the
    caller's.  That is true of ``GovernorModel.step()``, which applies it; it is
    NOT true of the stage-level demand models, none of which carries a
    conduction floor.  Without the guard those models clamped on totals the
    board cannot clamp at: 250 of ``ems-dp-replay``'s 34 827 cells bound at
    I_tot 1.47137 A, where the board's own clip caps the fuel cell at 1.1714 A
    and no ceiling can bind.  The guard therefore encodes the reachability
    threshold ``CEILING_REACHABLE_I_TOT_A`` directly. fw v27 rev 2 RE-DERIVES
    that threshold: the governing term swapped from the conduction floor to the
    BAND EDGE when I_min moved to 0.15 A, so it is now
    max(I_FC_CEIL/DROOP_R_MAX, I_FC_CEIL + I_MIN) = 1.4706 A, not 1.55 A. It
    remains conservative for the battery ceiling, whose own threshold is
    max(I_BT_CEIL/DROOP_R_MAX, I_BT_CEIL + I_MIN) = 3.176 A.

    RESIDUAL, stated rather than implied: between the clip's own onset and
    1.4706 A the board still delivers slightly less fuel-cell current than this
    helper reports, because the CLIP is active there while the CEILING is not.
    That gap is the minority clip's and is not this helper's to close; the
    dynamic port models it, and the demand models' own share grids
    ([0.15, 0.85]) keep the error under 0.05 A."""
    tot = float(i_tot)
    sp = float(sp)
    if sp < _R_MIN or sp > _R_MAX:
        return sp
    # THE INERT EARLY-OUT, FIRST, ON HOISTED CONSTANTS (2026-09-02).
    # This helper is called per share point per stage by the DP's vectorised
    # image, per sub-sample by the MPC's transition rolls and per stage by the
    # walk, and every one of those calls returns the argument untouched on the
    # entire registered stimulus set. A dict lookup per constant per call was
    # measurable at those counts (0.147 us/call against 0.070 us/call hoisted),
    # so the module-level names read once at import are used instead. They are
    # the dictionary's own values, so there is no second declaration to drift.
    if tot < CEILING_REACHABLE_I_TOT_A or not tot > _I_TOT_MIN_A:
        return sp
    if sp * tot <= _FC_CEIL_A and (1.0 - sp) * tot <= _BT_CEIL_A:
        return sp
    clamped = False
    lo_demand = (1.0 - sp) * tot
    if lo_demand > _BT_CEIL_A:
        sp = max(sp, 1.0 - _BT_CEIL_A / tot)
        clamped = True
    if sp * tot > _FC_CEIL_A:
        sp = min(sp, _FC_CEIL_A / tot)
        clamped = True
    if clamped:
        sp = _constrain(sp, _R_MIN, _R_MAX)
    return sp


def r_from_codes(code_fc: Optional[int], code_bt: Optional[int]) -> Optional[float]:
    """Recover the applied droop ratio from the two MDAC words.

    The gain map is ``g_FC = K_DROOP/(RE_MAX*r)`` and
    ``g_BT = K_DROOP/(RE_MAX*(1-r))`` (.ino:10534-10535), so
    ``g_BT/(g_FC+g_BT) = r`` exactly, independent of ``K_DROOP`` and
    ``RE_MAX``. Note the sign: a HIGHER ``r`` (more fuel-cell share) LOWERS the
    fuel-cell gain and its code.

    Returns ``None`` when either word is missing or both fractions are zero
    (no meaningful ratio)."""
    g_fc = mdac_fraction(code_fc)
    g_bt = mdac_fraction(code_bt)
    if g_fc is None or g_bt is None:
        return None
    tot = g_fc + g_bt
    if tot <= 0.0:
        return None
    return g_bt / tot


# ─────────────────────────────────────────────────────────────────────────────
# The model
# ─────────────────────────────────────────────────────────────────────────────
class GovernorModel:
    """Tick-level model of the firmware share-delivery path.

    Parameters
    ----------
    dt_s        tick period. The firmware ticks ``powerBalance()`` at
                ``POWER_BAL_PERIOD_US`` = 1 ms. The per-tick slew ceilings and
                the EMA weight are defined PER TICK, so changing ``dt_s`` alone
                does NOT rescale them — a caller that ticks slower is modelling
                a slower firmware. ``dt_s`` is used only for the blanking clock
                when no absolute time is supplied.
    dv0_v       source open-circuit-voltage difference V_0F - V_0B, in volts.
    k_droop     droop scale used by the static plant law. Defaults to the
                firmware's ``K_DROOP``.
    droop_scale_fc
                rho, the fuel-cell channel's droop-resistance multiplier
                relative to the battery channel (the SECOND parameter of the
                M2 asymmetry fit, ``hil_electrical.ASYM_DROOP_SCALE_FC``
                = 0.9434). 1.0 is the symmetric chain and the module default.
    r_series_ohm
                R_f, the unscalable series resistance COMMON to both channels
                between a regulated node and the bus
                (``hil_electrical.DROOP_FIXED_SERIES_OHM`` = 0.033, i.e.
                the boost Thevenin term + the RT1987 pass FET + the sense
                shunt). It is present in BOTH asymmetry modes; 0.0 is the
                idealized chain and the module default.
    conv_tau_s  optional first-order lag on the controller's demanded ratio
                (fidelity boundary 1). 0 disables it.
    seed_r      initial ``droopSlew_prev``. The firmware boots at 0.5.
    """

    def __init__(self, dt_s: float = 1e-3, dv0_v: float = 0.0,
                 k_droop: float = GOV_CONST["K_DROOP"],
                 conv_tau_s: float = 0.0, seed_r: float = 0.5,
                 v_bus_ok: bool = True, droop_scale_fc: float = 1.0,
                 r_series_ohm: float = 0.0):
        if dt_s <= 0.0:
            raise ValueError("dt_s must be positive")
        if not 0.0 <= seed_r <= 1.0:
            raise ValueError("seed_r must lie in [0, 1]")
        if k_droop <= 0.0:
            raise ValueError("k_droop must be positive")
        if conv_tau_s < 0.0:
            raise ValueError("conv_tau_s must not be negative")
        if droop_scale_fc <= 0.0:
            raise ValueError("droop_scale_fc must be positive")
        if r_series_ohm < 0.0:
            raise ValueError("r_series_ohm must not be negative")
        self.dt_s = float(dt_s)
        self.dv0_v = float(dv0_v)
        self.k_droop = float(k_droop)
        # THE TWO SPLIT-LAW PARAMETERS ADDED 2026-09-03 (review run-002,
        # PLANT-R2-F3/N1/N2). See `delivered_share()` for the law they enter.
        # The defaults are the IDENTITY MAP, so every caller that predates them
        # is bit-identical.
        self.droop_scale_fc = float(droop_scale_fc)
        self.r_series_ohm = float(r_series_ohm)
        self.conv_tau_s = float(conv_tau_s)
        self.seed_r = float(seed_r)
        # Stands in for the ``V_bus >= V_BUS_CHARGED_THRESH`` and
        # ``digitalRead(FC_REG_ENABLE) == HIGH`` guards on every re-close
        # (.ino:9832, :10453). The walk does not model bus voltage or converter
        # enables, so the default asserts a regulated bus with both boosts on —
        # the Run-state condition. Set False to model a teardown.
        self.v_bus_ok = bool(v_bus_ok)
        self.state = GovernorState()
        self.reset(seed_r)

    # ── lifecycle ────────────────────────────────────────────────────────────
    def reset(self, seed_r: Optional[float] = None) -> None:
        """``resetShareControlState()`` (.ino:10605) plus the switch beliefs.

        The firmware deliberately does NOT touch ``droopSlew_prev`` on a reset
        (the MDACs keep whatever split is physically on them), so ``seed_r``
        here is the boot seed, not a per-reset re-seed: passing ``None`` keeps
        the ratio already applied.

        fw v27 rev 2: this method is the BOOT / ``hilWarmReset()`` re-anchor,
        not the in-run ``resetShareControlState()`` (that is
        ``_reset_share_control_state()``). It therefore re-anchors the live
        droop scale to ``K_DROOP`` and drops the battery-only arm, exactly as
        ``hilWarmReset()`` does — the post-recovery bring-up re-runs
        ``initMdacOutputs()`` and the hardware really does move to the
        ``K_DROOP`` codes (.ino:10800 block, design record section 10.4)."""
        r = self.state.r_prev if seed_r is None else float(seed_r)
        if not 0.0 <= r <= 1.0:
            raise ValueError("seed_r must lie in [0, 1]")
        st = GovernorState()
        st.r_prev = r
        self._reset_controller_core(st, GOV_CONST["SHARE_CTRL_R0"])
        st.handoff_prev_ratio = r
        st.iso_prop_ratio = r
        st.droop_kd = self.k_droop
        self.state = st

    def arm_battery_only_start(self) -> None:
        """``armShareBatteryOnlyStart()`` (.ino:11737).

        Called at a PROFILE BOUNDARY only — the State 1 -> State 2 Run entry and
        the five State-98 profile starts. Deliberately NOT called by
        ``_reset_share_control_state()``: the latch's own release path calls
        that, so arming there would re-arm the cut the release just undid, on
        the very tick it undid it (design record section 9.2)."""
        self.state.batt_only_armed = True

    @staticmethod
    def _reset_controller_core(st: GovernorState, seed_ratio: float) -> None:
        """``resetShareControllerCore()`` (.ino:10577).

        The firmware seeds the controller integrator so the first closed-loop
        output continues from ``seed_ratio``, and seeds the effective-setpoint
        reference from the same value clipped into the droop band. The
        surrogate controller here carries only the output, so the integrator
        seed collapses onto it."""
        seed = _constrain(float(seed_ratio), 0.0, 1.0)
        st.ctrl_out = seed
        st.sp_eff_prev = _constrain(seed, _R_MIN, _R_MAX)

    # ── applyShareCurrentCeilings() (fw v26) ─────────────────────────────────
    def _clear_ceiling_state(self) -> None:
        """``clearShareCeilingState()`` (.ino:10215). Called from every path
        that FREEZES the share loop, so a frozen loop never publishes a stale
        clamp. State 99 is deliberately not one of those paths; the model has
        no fault path, so that asymmetry does not arise here."""
        self.state.gov_fc_clamped = False
        self.state.gov_bt_clamped = False

    def _apply_share_current_ceilings(self, sp: float) -> float:
        """Port of ``applyShareCurrentCeilings()`` (.ino:10273-10313).

        Bounds the effective setpoint (the FUEL-CELL FRACTION) so the commanded
        per-channel current stays at or below that channel's ceiling, evaluated
        on ``state.filt_total`` (the firmware's ``share_govTotAFilt``), never on
        a raw total. Order, verbatim from the firmware:

        1. the caller has already applied the minority-current clip;
        2. battery LOWER bound, hysteretic;
        3. fuel-cell UPPER bound, hysteretic, re-derived from the possibly
           battery-raised setpoint so the fuel cell wins an infeasible pair;
        4. the droop band, and only when a clamp is engaged, so an unclamped
           setpoint is returned untouched (fw v26 inertness).
        """
        st = self.state
        tot = st.filt_total
        if not tot > _I_TOT_MIN_A:
            if st.gov_fc_clamped or st.gov_bt_clamped:
                self._clear_ceiling_state()
            return sp

        bt_ceil = _BT_CEIL_A
        fc_ceil = _FC_CEIL_A
        hyst = _CEIL_HYST_A

        # FAST PATH. With no flag standing and neither demand over its ceiling
        # the firmware's arithmetic reduces to returning the argument, which is
        # the fw v26 inertness property stated as code rather than as a comment.
        if not (st.gov_fc_clamped or st.gov_bt_clamped):
            if sp * tot <= fc_ceil and (1.0 - sp) * tot <= bt_ceil:
                return sp

        demand_bt = (1.0 - sp) * tot
        if st.gov_bt_clamped:
            if demand_bt < bt_ceil - hyst:
                st.gov_bt_clamped = False
        elif demand_bt > bt_ceil:
            st.gov_bt_clamped = True
        if st.gov_bt_clamped:
            lo_bound = 1.0 - bt_ceil / tot
            if sp < lo_bound:
                sp = lo_bound

        demand_fc = sp * tot
        if st.gov_fc_clamped:
            if demand_fc < fc_ceil - hyst:
                st.gov_fc_clamped = False
        elif demand_fc > fc_ceil:
            st.gov_fc_clamped = True
        if st.gov_fc_clamped:
            hi_bound = fc_ceil / tot
            if sp > hi_bound:
                sp = hi_bound

        if st.gov_fc_clamped or st.gov_bt_clamped:
            sp = _constrain(sp, _R_MIN, _R_MAX)
            st.ceil_ticks += 1
        return sp

    # ── fw v27 rev 2: the load-scheduled droop scale ─────────────────────────
    @property
    def k_droop_live(self) -> float:
        """The scale ``applyShareRatio()`` maps through THIS tick.

        Through fw v26 this was the compile-time ``K_DROOP`` and the constructor
        parameter ``k_droop`` was the whole story. From fw v27 rev 2 the
        constructor parameter is the schedule's FLOOR (and the boot value) while
        ``state.droop_kd`` is the live scale. Every site that used to read
        ``self.k_droop`` for a PHYSICAL quantity — the code mapping and the two
        halves of the split law — reads this instead; the schedule's own floor
        comparison still reads ``self.k_droop``.

        ⚠️ A STAGE MODEL THAT NEVER TICKS READS THE FLOOR, and that is the
        honest answer rather than a gap. ``delivered_share()`` is called by
        demand models that hold no tick history (the dynamic program's
        vectorised image, the predictive controller's stage surrogate); on a
        model that has never run a closed-loop tick this returns ``K_DROOP``,
        which is the fw v26 law. The converged schedule at a given load has one
        owner, ``hil_plant_sim.scheduled_g_par()``, and wiring it into those
        demand models is a dynamic-program re-solve round — see the loss-map
        block there for the bias it leaves (at most 1.110 % of bus voltage, and
        only below 0.4694 A of filtered total)."""
        return self.state.droop_kd

    def droop_scale_target(self, tot_filt: float) -> float:
        """``shareDroopScaleTarget()`` (.ino:10847). Pure function of a filtered
        total: the admissible scale at that load, floored at ``K_DROOP``.

            k_d = max(K_DROOP, RE_MAX * clamp(I_min/tot, DROOP_R_MIN, 0.5) * SAFETY)

        The 0.5 cap mirrors the closed-loop clip's own ``if (lo > 0.5) lo = 0.5``
        sliver rule; the ``max`` floor is what recovers fw v26 bit-for-bit at and
        above the crossover ``RE_MAX*SAFETY*I_min/K_DROOP`` = 0.906 A. A
        non-positive or tiny total carries no information, so the LIVE value is
        held (the firmware's own structural divide guard)."""
        tot = float(tot_filt)
        if not tot > _I_TOT_MIN_A:
            return self.state.droop_kd
        r_lo = GOV_CONST["SHARE_MINORITY_I_MIN_A"] / tot
        if r_lo < _R_MIN:
            r_lo = _R_MIN
        if r_lo > 0.5:
            r_lo = 0.5
        kd = _RE_MAX * r_lo * GOV_CONST["SHARE_KD_SAFETY"]
        return self.k_droop if kd < self.k_droop else kd

    def _update_droop_scale(self) -> None:
        """``updateShareDroopScale()`` (.ino:10856). CLOSED-LOOP ONLY, once per
        tick, above every write site. The open-loop hold writes no MDACs, so
        publishing a new scale there would describe hardware that did not move,
        and the feedforward submode is deliberately left on the inherited
        value."""
        st = self.state
        if abs(st.filt_total - st.kd_sched_tot) > GOV_CONST["SHARE_KD_HYST_A"]:
            st.kd_sched_tot = st.filt_total
        target = self.droop_scale_target(st.kd_sched_tot)
        step = st.droop_kd * GOV_CONST["SHARE_KD_SLEW_FRAC_PER_TICK"]
        st.droop_kd = _constrain(target, st.droop_kd - step, st.droop_kd + step)

    def feedforward_clip_target(self, sp: float, prev_ratio: float) -> float:
        """``shareFeedforwardClipTarget()`` (.ino:10810), fw v27 rev 1.

        The relaxing minority-current clip on the OPEN-LOOP FEEDFORWARD path.
        An EMPTY band is a HOLD at the ratio the hardware already carries — NOT
        a collapse to 0.5, which is the fw v4 ``TP0053`` failure this form
        deliberately does not repeat. The band opens monotonically with the
        filtered total, so the clipped reference relaxes toward the raw setpoint
        as load grows and the clip introduces no movement of its own.

        At the shipped fw v27 rev 2 constants the caller only runs below the
        0.30 A gate, where the band is empty, so this is always the hold; the
        relaxing branch is written for a future retune, exactly as the firmware
        writes it."""
        tot = self.state.filt_total
        if not tot > _I_TOT_MIN_A:
            return prev_ratio
        lo = GOV_CONST["SHARE_MINORITY_I_MIN_A"] / tot
        hi = 1.0 - lo
        if not lo < hi:
            return prev_ratio
        return _constrain(float(sp), lo, hi)

    # ── plant law ────────────────────────────────────────────────────────────
    def delivered_share(self, r: float, i_tot: float,
                        fc_on: bool, bt_on: bool) -> float:
        """Fuel-cell fraction of the source total actually delivered.

        Topology first: a channel off the bus delivers nothing, so a cut pins
        the share at 0.0 (FC cut) or 1.0 (BT cut). With both channels dark the
        share is undefined and 0.0 is returned; the caller is expected to know
        there is no source.

        With both live, the delivered share is the TWO-BRANCH DIVIDER of the
        static droop network (review run-002, PLANT-R2-F3, 2026-09-03). Each
        channel is a Thevenin source behind its own realized droop resistance
        plus the series resistance common to both branches:

            R_FC = rho * k_d / r     + R_f
            R_BT =       k_d / (1-r) + R_f
            alpha = (dV0 / I_tot + R_BT) / (R_FC + R_BT)

        with ``rho = droop_scale_fc`` (``hil_electrical.ASYM_DROOP_SCALE_FC``
        = 0.9434 in the measured mode, 1.0 off) and ``R_f = r_series_ohm``
        (``hil_electrical.DROOP_FIXED_SERIES_OHM`` = 0.033, PRESENT IN BOTH
        MODES). ``dV0`` is the voltage half of the same M2 fit; the two fit
        parameters are one fit and must move together
        (``docs/modeling/converter_asymmetry_20260901.md`` section 9,
        ``hil_electrical.py:277``). The law and its validations are recorded in
        ``docs/modeling/governor_split_law_20260903.md``.

        ⚠️ WHAT THIS REPLACED, and why it is not a refinement. Until 2026-09-03
        this method carried ``alpha = r + dV0*r*(1-r)/(k_d*I_tot)``, i.e. the
        dV0 half of the fit alone with rho pinned at 1 and no series floor —
        the M1/M2 mixture the fit document rejects. Against campaign F's
        converged sweep windows it mis-inverted the ratio by +3.1 % at
        alpha 0.50 and +10.5 % at alpha 0.20; it was ALSO wrong with the
        asymmetry off, by up to 0.0096 of share at the band rails, because the
        0.033 ohm floor is era-independent.

        The law degenerates to ``alpha = r`` at ``dV0 = 0``, ``rho = 1``,
        ``R_f = 0`` (the module defaults), and is clamped to [0, 1] because it
        has no validity outside it. With no current there is no delivered
        share to speak of, so ``i_tot <= 0`` returns the applied ratio, exactly
        as before."""
        if not fc_on and not bt_on:
            return 0.0
        if not fc_on:
            return 0.0
        if not bt_on:
            return 1.0
        rr = _constrain(float(r), 0.0, 1.0)
        if self.map_is_identity() or i_tot <= 0.0:
            return rr
        if rr <= 0.0:
            return 0.0
        if rr >= 1.0:
            return 1.0
        # fw v27 rev 2: the LIVE scheduled k_d, not the fixed floor. The droop
        # resistance a channel actually presents is k_d/r, and k_d is now a
        # function of load below the 0.906 A crossover. Two consequences, both
        # stated in docs/HIL_PLANT.md section 4.4a: with rho = 1 and R_f = 0 the
        # scale CANCELS and the law is unchanged (alpha = r); with R_f > 0 the
        # fixed series floor's RELATIVE weight shrinks as k_d grows — at
        # DROOP_R_MAX, where it is largest in band, from 8.55 % of a channel
        # resistance at 0.30 ohm to 3.00 % at the 0.906 ohm cap.
        # ⚠️ THAT WEIGHT IS MONOTONE; THE SHARE'S DIRECTION IS NOT. R_f
        # partially cancels the rho asymmetry in the upper band, so taking
        # weight off it can move the delivered share FURTHER from the commanded
        # ratio there (measured at r = 0.80: 0.00557 -> 0.00794 across the
        # schedule's span). Do not restate this as "closer to the identity".
        kd = self.k_droop_live
        r_fc = self.droop_scale_fc * kd / rr + self.r_series_ohm
        r_bt = kd / (1.0 - rr) + self.r_series_ohm
        alpha = (self.dv0_v / float(i_tot) + r_bt) / (r_fc + r_bt)
        return _constrain(alpha, 0.0, 1.0)

    def map_is_identity(self) -> bool:
        """Whether ``delivered_share()`` is the identity on an interior ratio.

        ALL THREE PARAMETERS HAVE TO BE TRIVIAL (N2, 2026-09-03). The shortcut
        used to key on ``dv0_v == 0.0`` alone, which was correct only while the
        law had no other term: with ``r_series_ohm`` present the map is NOT the
        identity at ``dV0 = 0``, and an ``--asymmetry off`` walk taking the old
        shortcut would silently keep the wrong map.

        PUBLIC (2026-09-03 fix round, L3). It is not an implementation detail:
        ``mpc_ems.Planner.__init__`` keys its ``_map is None`` shortcut on this
        predicate rather than re-deriving it, which is the whole point of
        having one owner for the question."""
        return (self.dv0_v == 0.0 and self.droop_scale_fc == 1.0
                and self.r_series_ohm == 0.0)

    def _ratio_for_delivered(self, alpha: float, i_tot: float) -> float:
        """Invert the static law: the ratio whose delivered share is ``alpha``.

        This is what the closed loop's integral action finds. Multiplying
        ``alpha*(R_FC + R_BT) = dV0/I_tot + R_BT`` through by ``r*(1-r)`` gives
        the quadratic ``A*r^2 + B*r + C = 0`` with

            P = (2*alpha - 1) * R_f - dV0/I_tot
            A = -P
            B =  P + k_d * (alpha*(1 - rho) - 1)
            C =  alpha * rho * k_d

        At the trivial parameters A -> 0, B -> -k_d and C -> alpha*k_d, so the
        physical root is the one that tends to ``-C/B = alpha``. It is taken
        through the numerically stable pairing ``q = -(B + sign(B)*sqrt(D))/2``,
        ``r = C/q``, which does not cancel catastrophically as A -> 0 (the
        textbook ``(-B + sqrt(D))/(2A)`` form does, and A is small on every
        physical parameter set). The degenerate cases are handled exactly as
        the pre-2026-09-03 code handled them: an unusable discriminant or a
        vanishing leading pair returns ``alpha`` rather than raising."""
        a = _constrain(float(alpha), 0.0, 1.0)
        if self.map_is_identity() or i_tot <= 0.0:
            return a
        kd = self.k_droop_live      # fw v27 rev 2 — the live scheduled scale
        p = (2.0 * a - 1.0) * self.r_series_ohm - self.dv0_v / float(i_tot)
        qa = -p
        qb = p + kd * (a * (1.0 - self.droop_scale_fc) - 1.0)
        qc = a * self.droop_scale_fc * kd
        if abs(qa) < 1e-15:
            if abs(qb) < 1e-15:
                return a
            return _constrain(-qc / qb, 0.0, 1.0)
        disc = qb * qb - 4.0 * qa * qc
        if disc < 0.0:
            return a
        sq = math.sqrt(disc)
        q = -0.5 * (qb + (sq if qb >= 0.0 else -sq))
        if q == 0.0:
            return a
        return _constrain(qc / q, 0.0, 1.0)

    # ── switch bookkeeping ───────────────────────────────────────────────────
    def _observe_switches(self, sw_fc: bool, sw_bt: bool, t_ms: float) -> None:
        """``writeBusSwitch()``'s rising-edge stamp (.ino:3391-3403) applied to
        EXTERNALLY observed switch states.

        The model does not own the switches, so every LOW->HIGH transition it
        sees — whether the governor asked for it or ``chargingControl()`` did —
        starts a blanking window, which is exactly the firmware's behaviour: the
        chokepoint stamps all 26 write sites."""
        st = self.state
        if st.sw_init:
            if sw_fc and not st.sw_fc:
                st.rise_ms_fc = t_ms
                st.rise_seen_fc = True
            if sw_bt and not st.sw_bt:
                st.rise_ms_bt = t_ms
                st.rise_seen_bt = True
        st.sw_fc = bool(sw_fc)
        st.sw_bt = bool(sw_bt)
        st.sw_init = True

    def _write_switch(self, which: str, level: bool, t_ms: float) -> None:
        st = self.state
        if which == "FC":
            if level and not st.sw_fc:
                st.rise_ms_fc = t_ms
                st.rise_seen_fc = True
            st.sw_fc = level
        else:
            if level and not st.sw_bt:
                st.rise_ms_bt = t_ms
                st.rise_seen_bt = True
            st.sw_bt = level

    def _blanked(self, which: str, t_ms: float) -> bool:
        """``busSwitchBlanked()`` (.ino:3406). A switch that is HIGH with no
        recorded edge is NOT blanked — an unknown edge is treated as old."""
        st = self.state
        blank = GOV_CONST["SHARE_CUT_SURVIVOR_BLANK_MS"]
        if which == "FC":
            return st.rise_seen_fc and (t_ms - st.rise_ms_fc) < blank
        return st.rise_seen_bt and (t_ms - st.rise_ms_bt) < blank

    # ── updateShareSetpointCutoff() ──────────────────────────────────────────
    def _setpoint_cutoff(self, sp: float, i_fc: float, i_batt: float,
                         t_ms: float) -> bool:
        """Port of .ino:10419-10620. Returns True while a latch is active, i.e.
        the caller must freeze the whole share loop this tick.

        fw v27 rev 2 BATTERY-ONLY START: while the arm owns the setpoint this
        function sees ``SHARE_BATTERY_ONLY_SP`` (0.0) instead of the commanded
        share, which is EXACTLY the share-zero cut this path already implements.
        The cut therefore inherits the last-source guard, the survivor-regulator
        guard, the fw v25 load guard, the survivor-turn-on blanking and the
        deferral, and the re-entry is this function's own release branch. No
        second cut mechanism exists (design record section 9.1)."""
        st = self.state
        if st.batt_only_active:
            sp = GOV_CONST["SHARE_BATTERY_ONLY_SP"]
        st.deferred_fc = False
        st.deferred_bt = False
        released = False

        # S1 self-heal: an ownership claim over a switch somebody else re-closed
        # is orphaned and must degrade to live control (.ino:9801-9817).
        if st.sp_cut_fc and st.sw_fc:
            st.sp_cut_fc = False
            st.iso_fc = False
        if st.sp_cut_bt and st.sw_bt:
            st.sp_cut_bt = False
            st.iso_bt = False
        if st.iso_fc and st.sw_fc:
            st.iso_fc = False
        if st.iso_bt and st.sw_bt:
            st.iso_bt = False

        # Release, evaluated first (.ino:9827-9871). The re-close carries the
        # charged-bus and boost-enabled guards, modelled by ``v_bus_ok``.
        if st.sp_cut_fc and sp >= _R_MIN:
            if self.v_bus_ok:
                self._write_switch("FC", True, t_ms)
                st.iso_fc = False
                st.sp_cut_fc = False
                released = True
                self._reset_share_control_state()
        elif st.sp_cut_bt and sp <= _R_MAX:
            if self.v_bus_ok:
                self._write_switch("BT", True, t_ms)
                st.iso_bt = False
                st.sp_cut_bt = False
                released = True
                self._reset_share_control_state()

        # A release tick returns the loop to normal control for one tick before
        # the opposite latch may engage (.ino:9876).
        if released:
            return False

        # Entry (.ino:9917-9962): last-source guard, then the load guard, then
        # survivor-turn-on blanking. Blocked on load -> DEFERRED; blocked on
        # blanking -> no latch, no flag, retry next tick.
        cut = GOV_CONST["SHARE_CUT_MAX_HANDOFF_A"]
        # SURVIVOR-REGULATOR GUARD (fw v27 rev 2 review H1, .ino:10570/:10604).
        # The last-source guard tests the two BUS switches; the entry must also
        # test that the SURVIVOR'S BOOST IS ENABLED, or a battery-only cut fired
        # at a State-98 profile start could leave the bus fed by a DISABLED
        # TPS61288. The model does not carry the two ``*_REG_ENABLE`` pins, so
        # it reuses ``v_bus_ok`` — the same flag that already stands in for the
        # charged-bus + boost-enabled guards on every re-close (see its
        # declaration). At the default ``v_bus_ok = True`` (both boosts on, the
        # Run-state condition every offline walk models) this guard is inert, so
        # the port stays bit-identical to fw v26 for every existing caller;
        # ``v_bus_ok = False`` now refuses the cut too, which is the
        # conservative direction and matches the firmware's fall-through.
        if not st.sp_cut_fc and not st.sp_cut_bt:
            if sp < _R_MIN:
                if st.sw_fc and st.sw_bt and self.v_bus_ok:
                    if abs(i_fc) <= cut and self._blanked("BT", t_ms):
                        st.refused_blank += 1
                    elif abs(i_fc) <= cut:
                        self._write_switch("FC", False, t_ms)
                        st.iso_fc = True
                        st.sp_cut_fc = True
                        # fw v27 rev 2 section 12: anchor the feedforward
                        # proposal at the ratio physically on the MDACs the
                        # instant the cut is taken — r_prev freezes from here.
                        st.iso_prop_ratio = st.r_prev
                    else:
                        st.deferred_fc = True
                        st.refused_load += 1
            elif sp > _R_MAX:
                if st.sw_bt and st.sw_fc and self.v_bus_ok:
                    if abs(i_batt) <= cut and self._blanked("FC", t_ms):
                        st.refused_blank += 1
                    elif abs(i_batt) <= cut:
                        self._write_switch("BT", False, t_ms)
                        st.iso_bt = True
                        st.sp_cut_bt = True
                        st.iso_prop_ratio = st.r_prev   # mirror (fw v27 rev 2)
                    else:
                        st.deferred_bt = True
                        st.refused_load += 1

        return st.sp_cut_fc or st.sp_cut_bt

    def _charge_path_claim_bt(self, t_ms: float) -> None:
        """``assertFcChargeEnable(true)``'s ownership override (.ino:9260-9286).

        The charge path is a deliberate state action and OUTRANKS the share
        loop's claims. Two clears, in the firmware's order:

        * S2 ORDERING (.ino:9272-9276) — FC is restored to the bus BEFORE BT is
          cut, and only when the share loop's own claim is what holds it off
          (``shareSpCutFC || shareIsoFC``) AND ``FC_BUS_ENABLE`` reads LOW. The
          scoping is load-bearing: ``doState99()`` phase 0 opens both switches
          and then calls this function, and an unscoped restore would re-energize
          the bus during a teardown.
        * BT is driven LOW and both BT claims are cleared unconditionally
          (.ino:9280-9286), because ``applyShareRatio()``'s re-entry would
          otherwise close ``BT_BUS`` while ``FC_CHARGE`` is HIGH — the illegal
          combination — and a stale latch would freeze the whole share loop for
          as long as the charge path holds the switch.
        """
        st = self.state
        if (st.sp_cut_fc or st.iso_fc) and not st.sw_fc:
            st.iso_fc = False
            st.sp_cut_fc = False
            self._write_switch("FC", True, t_ms)
        self._write_switch("BT", False, t_ms)
        st.iso_bt = False
        st.sp_cut_bt = False

    def _reset_share_control_state(self) -> None:
        """``resetShareControlState()`` (.ino:10605). ``droopSlew_prev``, the
        switch beliefs and the blanking stamps are deliberately untouched."""
        st = self.state
        self._reset_controller_core(st, GOV_CONST["SHARE_CTRL_R0"])
        st.filt_total = 0.0
        st.acted_sp = st.acted_sp     # the firmware assigns the live setpoint;
                                      # step() re-assigns it below on the same
                                      # tick, so no phantom change can appear.
        st.closed_loop_mode = False
        st.closed_loop_run = False
        st.deferred_fc = False
        st.deferred_bt = False
        st.handoff_i_fc_filt = 0.0
        st.handoff_i_bt_filt = 0.0
        st.dark_fc = True
        st.dark_bt = True
        st.handoff_dwell = 0
        st.slew_step = GOV_CONST["DROOP_RATIO_SLEW_HANDOFF_PER_TICK"]
        st.handoff_prev_ratio = st.r_prev
        # fw v26 (.ino:11011): resetShareControlState() drops the clamp state.
        st.gov_fc_clamped = False
        st.gov_bt_clamped = False
        # fw v27 rev 2 (.ino:11719): the k_d SCHEDULE INPUT is a load estimate
        # and goes with the filter. ``droop_kd`` itself is MDAC truth and is
        # deliberately NOT reset — the converters physically hold their codes
        # across a profile boundary, and snapping the scale back to K_DROOP
        # there would jump the codes by the full schedule span in one write.
        # The battery-only ARM is likewise not set here (section 9.2).
        st.kd_sched_tot = 0.0

    # ── updateShareSlewMode() ────────────────────────────────────────────────
    def _slew_mode(self, i_fc: float, i_batt: float) -> None:
        """Port of .ino:10035-10064. Sets ``state.slew_step`` for this tick.

        The dwell allowance burns only on ticks where the applied ratio ACTUALLY
        MOVED (the O1 motion gate): a static hold with a dark channel selects
        the slow ceiling but costs nothing."""
        st = self.state
        alpha = GOV_CONST["SHARE_GOV_FILT_ALPHA"]
        moved = abs(st.r_prev - st.handoff_prev_ratio) > 1e-6
        st.handoff_prev_ratio = st.r_prev

        st.handoff_i_fc_filt += alpha * (abs(i_fc) - st.handoff_i_fc_filt)
        st.handoff_i_bt_filt += alpha * (abs(i_batt) - st.handoff_i_bt_filt)

        live = GOV_CONST["SHARE_HANDOFF_LIVE_A"]
        dark = GOV_CONST["SHARE_HANDOFF_MIN_A"]
        if st.dark_fc:
            if st.handoff_i_fc_filt >= live:
                st.dark_fc = False
        elif st.handoff_i_fc_filt < dark:
            st.dark_fc = True
        if st.dark_bt:
            if st.handoff_i_bt_filt >= live:
                st.dark_bt = False
        elif st.handoff_i_bt_filt < dark:
            st.dark_bt = True

        full = GOV_CONST["DROOP_RATIO_SLEW_PER_TICK"]
        if not (st.dark_fc or st.dark_bt):
            st.handoff_dwell = 0
            st.slew_step = full
            return
        if st.handoff_dwell >= GOV_CONST["SHARE_HANDOFF_DWELL_MAX_TICKS"]:
            st.slew_step = full
            return
        if moved:
            st.handoff_dwell += 1
        st.slew_step = GOV_CONST["DROOP_RATIO_SLEW_HANDOFF_PER_TICK"]

    # ── applyShareRatio() ────────────────────────────────────────────────────
    def _apply_share_ratio(self, ratio: float, i_fc: float, i_batt: float,
                           t_ms: float, from_controller: bool):
        """Port of .ino:10379-10537. Returns
        ``(wrote_mdacs, cut_refused_load, cut_refused_blank)``."""
        st = self.state
        r = _constrain(float(ratio), 0.0, 1.0)
        refused_load = False
        refused_blank = False
        cut_limit = GOV_CONST["SHARE_CUT_MAX_HANDOFF_A"]
        hyst = GOV_CONST["SHARE_CUTOFF_HYST"]

        # FC cutoff / re-entry (.ino:10422-10457).
        if (not st.iso_fc) and r < _R_MIN and not st.deferred_fc:
            if st.sw_fc and st.sw_bt:
                if abs(i_fc) > cut_limit:
                    st.refused_load += 1
                    refused_load = True
                elif self._blanked("BT", t_ms):
                    st.refused_blank += 1
                    refused_blank = True
                else:
                    self._write_switch("FC", False, t_ms)
                    st.iso_fc = True
                    # fw v27 rev 2 section 12 (.ino:11518): anchor the
                    # feedforward proposal at the MDAC truth. This write can
                    # come from a ONE-SHOT caller that never reaches the
                    # feedforward branch's own anchor.
                    st.iso_prop_ratio = st.r_prev
        elif (st.iso_fc and not st.sp_cut_fc and r >= _R_MIN + hyst
              and self.v_bus_ok):
            self._write_switch("FC", True, t_ms)
            st.iso_fc = False

        # BT cutoff / re-entry (.ino:10460-10487).
        if (not st.iso_bt) and r > _R_MAX and not st.deferred_bt:
            if st.sw_bt and st.sw_fc:
                if abs(i_batt) > cut_limit:
                    st.refused_load += 1
                    refused_load = True
                elif self._blanked("FC", t_ms):
                    st.refused_blank += 1
                    refused_blank = True
                else:
                    self._write_switch("BT", False, t_ms)
                    st.iso_bt = True
                    st.iso_prop_ratio = st.r_prev   # mirror (fw v27 rev 2)
        elif (st.iso_bt and not st.sp_cut_bt and r <= _R_MAX - hyst
              and self.v_bus_ok):
            self._write_switch("BT", True, t_ms)
            st.iso_bt = False

        # While a channel is isolated the active one keeps its previous droop
        # gain — no MDAC write at all (.ino:10492).
        if st.iso_fc or st.iso_bt:
            return False, refused_load, refused_blank

        rc = _constrain(r, _R_MIN, _R_MAX)

        # fw v25 refused-cut band-edge slew clip, CONTROLLER PATH ONLY
        # (.ino:10512-10520). One-shot operator or state writes land exactly
        # where commanded.
        if (refused_load or refused_blank) and from_controller:
            rc = _constrain(rc, st.r_prev - st.slew_step,
                            st.r_prev + st.slew_step)
            rc = _constrain(rc, _R_MIN, _R_MAX)

        st.r_prev = rc
        return True, refused_load, refused_blank

    # ── one tick of powerBalance() ───────────────────────────────────────────
    def step(self, sp: float, i_fc: float, i_batt: float,
             sw_fc: bool, sw_bt: bool, t_s: float,
             charge_path_owns_bt: bool = False) -> GovernorOut:
        """Advance one ``powerBalance()`` tick.

        ``sp``      the commanded ``power_share_setpoint``.
        ``i_fc``,   the two INA253 channel currents, in amperes, with the
        ``i_batt``  firmware's sign convention (forward source current).
        ``sw_fc``,  the OBSERVED bus-switch states at the top of this tick.
        ``sw_bt``   Other owners write these; the governor's own request comes
                    back on the result.
        ``t_s``     absolute time, seconds. Used for the 30 ms turn-on blanking.
        ``charge_path_owns_bt``
                    True on a tick where ``assertFcChargeEnable(true)`` holds
                    BT_BUS for the fuel-cell charge path. Applied BEFORE the
                    setpoint cutoff, as the firmware's call order does
                    (``chargingControl()`` runs before ``powerBalance()`` in
                    every caller — .ino:9853 note). Default False keeps every
                    existing caller unchanged.
        """
        st = self.state
        st.ticks += 1
        t_ms = float(t_s) * 1000.0
        self._observe_switches(sw_fc, sw_bt, t_ms)
        if charge_path_owns_bt:
            self._charge_path_claim_bt(t_ms)

        sp = float(sp)
        total = abs(i_fc) + abs(i_batt)

        # 0. fw v27 rev 2 BATTERY-ONLY START — derive the arm's ownership for
        #    this tick (.ino:10990-10996), before the setpoint latch runs.
        #    (c) an OUT-OF-BAND commanded setpoint is a CUT owned by the latch,
        #        so the arm DISARMS PERMANENTLY on sight of one rather than
        #        merely deferring: one owner per setpoint, and a battery-only
        #        rule that took the fuel cell back after the operator's own cut
        #        released would be a second owner arriving late. A band-edge
        #        0.15 or 0.85 is IN band and is a share, so it does not disarm.
        #    (f) an FC-charge window SUPPRESSES the arm (not disarms it):
        #        assertFcChargeEnable() holds BT_BUS low there, so the entry's
        #        last-source guard would refuse the cut anyway. The model's
        #        proxy for that window is ``charge_path_owns_bt``, which is the
        #        same signal the caller uses for the ownership override above.
        if st.batt_only_armed and (sp < _R_MIN or sp > _R_MAX):
            st.batt_only_armed = False
        st.batt_only_active = st.batt_only_armed and not charge_path_owns_bt

        # 1. Setpoint latch owns every out-of-band setpoint, evaluated BEFORE
        #    the minimum-load gate so the release path runs at standstill too
        #    (.ino:10087).
        if self._setpoint_cutoff(sp, i_fc, i_batt, t_ms):
            st.latched = True
            if st.gov_fc_clamped or st.gov_bt_clamped:
                self._clear_ceiling_state()      # .ino:10421 (fw v26)
            # THE ONE THING A BATTERY-ONLY FREEZE MUST NOT INHERIT
            # (.ino:11009-11020). A latched cut returns before the governor
            # filter is advanced, by design: a frozen loop has no governed state
            # to advance. That is fatal for an arm whose RELEASE CONDITION is
            # the filtered total crossing the closed-loop gate — the filter
            # could never cross it and the profile would run single-sourced for
            # its whole length. So while, and only while, the arm owns the cut,
            # the frozen path keeps the load estimate alive and drops the arm
            # the instant the gate is met. Note the firmware's ``>=`` against
            # SHARE_I_TOT_MIN_A here, against the ``<`` gate below.
            if st.batt_only_active:
                if total >= _I_TOT_MIN_A:
                    st.filt_total += GOV_CONST["SHARE_GOV_FILT_ALPHA"] * (
                        total - st.filt_total)
                    if st.filt_total > 2.0 * GOV_CONST["SHARE_MINORITY_I_MIN_A"]:
                        st.batt_only_armed = False
            return self._out(MODE_LATCHED, False, False)
        st.latched = False

        # 2. Minimum-load gate: hold everything (.ino:10099).
        if total < GOV_CONST["SHARE_I_TOT_MIN_A"]:
            if st.gov_fc_clamped or st.gov_bt_clamped:
                self._clear_ceiling_state()      # .ino:10432 (fw v26)
            return self._out(MODE_FROZEN, False, False)

        # 3. Governor load filter (.ino:10104).
        st.filt_total += GOV_CONST["SHARE_GOV_FILT_ALPHA"] * (total - st.filt_total)

        # 4. One conduction-aware slew ceiling for the whole tick (.ino:10112).
        self._slew_mode(i_fc, i_batt)

        # 5. Loop-mode decision with hysteresis (.ino:10126-10145).
        entry = 2.0 * GOV_CONST["SHARE_MINORITY_I_MIN_A"]
        if not st.closed_loop_mode:
            if st.filt_total > entry:
                st.closed_loop_mode = True
                # OPEN->CLOSED seed from the ratio physically on the MDACs.
                self._reset_controller_core(st, st.r_prev)
        elif st.filt_total < entry - GOV_CONST["SHARE_GOV_OL_HYST_A"]:
            st.closed_loop_mode = False

        if not st.closed_loop_mode:
            return self._open_loop(sp, i_fc, i_batt, t_ms)
        return self._closed_loop(sp, i_fc, i_batt, total, t_ms)

    # ── open-loop branch (.ino:10147-10213) ──────────────────────────────────
    def _open_loop(self, sp: float, i_fc: float, i_batt: float,
                   t_ms: float) -> GovernorOut:
        st = self.state
        if st.closed_loop_run:
            sp_changed = abs(sp - st.acted_sp) > GOV_CONST["SHARE_SP_CHANGE_EPS"]
            iso_outstanding = st.iso_fc or st.iso_bt
            if not sp_changed and not iso_outstanding:
                # HOLD. No MDAC write; the converged split stands. This is the
                # behaviour two offline walks in this repository missed.
                # fw v26: HOLD writes nothing, so the clamp is deliberately NOT
                # applied and its state is dropped (.ino:10514).
                if st.gov_fc_clamped or st.gov_bt_clamped:
                    self._clear_ceiling_state()
                return self._out(MODE_OPEN_HOLD, False, False)
            if sp_changed:
                st.closed_loop_run = False

        # F1: an out-of-band setpoint is never actuated here (.ino:10197).
        # Its own mode, so a census cannot read these idle ticks as actuation.
        if sp < _R_MIN or sp > _R_MAX:
            return self._out(MODE_OPEN_F1_IDLE, False, False)

        slew = st.slew_step
        # ── fw v27: THE RELAXING MINORITY-CURRENT CLIP RUNS HERE TOO ─────────
        # FIRST, exactly as on the closed-loop path (conduction feasibility owns
        # the floor; the ceilings are applied to its result). At the shipped
        # constants this is always the HOLD branch, so the fed-forward reference
        # stops walking out to an infeasible extreme and the open->closed
        # handover carries no magnitude jump.
        #
        # ⚠️ BYPASSED WHILE A CONTROLLER-INITIATED CUT IS OUTSTANDING (review
        # HIGH-1, .ino:11223-11245). ``applyShareRatio()`` returns before it
        # records ``r_prev`` while a channel is isolated, so ``r_prev`` is FROZEN
        # at the rail the cut came from — one hysteresis width short of re-entry.
        # Feeding the clip there would propose that frozen rail forever and
        # strand the channel off the bus. So while isolated the RAW setpoint is
        # fed forward, bit-identically to fw v26.
        #
        # ⚠️ AND THE BYPASS NEEDS ITS OWN WALK ANCHOR (fw v27 rev 2 section 12).
        # The slew below used to walk from ``r_prev``, which is frozen for the
        # duration of the cut, so every isolated tick proposed the same
        # ``rail + one step`` and the proposal could never accumulate. That is
        # harmless only while one step clears SHARE_CUTOFF_HYST on its own:
        #   DROOP_RATIO_SLEW_PER_TICK          0.020 > 0.01  -> re-enters, 1 tick
        #   DROOP_RATIO_SLEW_HANDOFF_PER_TICK  0.002 < 0.01  -> never re-enters
        # and at the rev 2 gate the handoff rate is the ORDINARY sub-gate
        # ceiling (no sub-0.30 A total can hold both channels above the 0.20 A
        # live threshold). ``iso_prop_ratio`` accumulates the proposal across
        # isolated ticks and is re-anchored to the MDAC truth on every tick that
        # is not isolated. The rate bound survives end to end: the proposal
        # advances by at most one tick's ceiling and the write the re-entry
        # finally makes lands AT the proposal, at most one SHARE_CUTOFF_HYST off
        # the rail.
        prev_ratio = st.r_prev
        iso_outstanding = st.iso_fc or st.iso_bt
        if not iso_outstanding:
            st.iso_prop_ratio = prev_ratio      # follow the hardware
        ff_sp = (sp if iso_outstanding
                 else self.feedforward_clip_target(sp, prev_ratio))
        # fw v26: FEEDFORWARD does write the MDACs, so it takes the clamp
        # (.ino:11250). Inert at every reachable open-loop total (below 0.25 A
        # no channel can carry 1.25 A), applied so a future ceiling retune
        # cannot leave a writing path unguarded.
        # Same inlined inert guard as the closed-loop path; see the note there.
        _tot = st.filt_total
        if (st.gov_fc_clamped or st.gov_bt_clamped
                or ff_sp * _tot > _FC_CEIL_A
                or (1.0 - ff_sp) * _tot > _BT_CEIL_A):
            ff_sp = self._apply_share_current_ceilings(ff_sp)
        walk_from = st.iso_prop_ratio if iso_outstanding else prev_ratio
        target = _constrain(ff_sp, walk_from - slew, walk_from + slew)
        if iso_outstanding:
            st.iso_prop_ratio = target
        wrote, rl, rb = self._apply_share_ratio(target, i_fc, i_batt, t_ms,
                                                from_controller=False)
        # fw v27 review MEDIUM-1 — ``share_actedSp`` RECORDS ACTUATION, NOT
        # ARRIVAL. On a HELD tick nothing reaches the MDACs, so recording the
        # setpoint would answer HOLD's ``spChanged`` question with a yes the
        # hardware cannot back. The exact float compare is deliberate: it is the
        # same test ``applyShareRatio()`` would answer with a write, and the held
        # path produces ``prev_ratio`` by assignment, not by arithmetic.
        if target != prev_ratio:
            st.acted_sp = sp
        return self._out(MODE_OPEN_FF, rl, rb, wrote)

    # ── closed-loop branch (.ino:10215-10377) ────────────────────────────────
    def _closed_loop(self, sp: float, i_fc: float, i_batt: float,
                     total: float, t_ms: float) -> GovernorOut:
        st = self.state
        st.closed_loop_run = True
        st.acted_sp = sp
        # fw v27 rev 2 (.ino:11268): the loop has closed, so the battery-only
        # start is over for this profile — whichever way this tick was reached.
        # Belt and braces with the gate test on the frozen path: that path is the
        # only one that can be taken while the cut is latched, this one the only
        # one that can be taken while it is not.
        st.batt_only_armed = False
        # The load-scheduled droop scale advances HERE and nowhere else — closed
        # loop only, one call per tick, ABOVE every write site, so the reference
        # clip, the fw v26 ceilings and the fw v25 load guard (all of which work
        # in CURRENT space and never read k_d) run against the same scale
        # applyShareRatio() will map through at the bottom of this tick.
        self._update_droop_scale()
        slew = st.slew_step

        sp_target = sp
        # Deferred-cut reference clip (.ino:10250).
        if st.deferred_fc or st.deferred_bt:
            sp_target = _constrain(sp_target, _R_MIN, _R_MAX)

        # Minority-current governor clip, in-band setpoints only (.ino:10254).
        if _R_MIN <= sp_target <= _R_MAX:
            lo = GOV_CONST["SHARE_MINORITY_I_MIN_A"] / st.filt_total
            # Hysteresis-sliver ceiling: with lo > hi the Arduino constrain()
            # would return lo, i.e. the minority split on the WRONG side.
            if lo > 0.5:
                lo = 0.5
            hi = 1.0 - lo
            sp_target = _constrain(sp_target, lo, hi)

        # Source current-ceiling clamp (fw v26, .ino:10635-10640). AFTER the
        # minority-current clip (conduction feasibility owns the floor) and
        # BEFORE the effective-setpoint slew, so the clamp reaches the
        # controller through the same rate limit as every other reference
        # movement. SUPPRESSED while a deferred cut owns the setpoint: the
        # deferral clip above has parked the reference on a band edge to starve
        # a doomed channel, and one owner per tick applies.
        # PERFORMANCE (2026-09-02). The guard below is the clamp's own inert
        # condition, inlined so that a tick on which no ceiling is near does no
        # call at all. `_apply_share_current_ceilings()` returns its argument
        # untouched in exactly that case, so the two are equivalent by
        # construction: the method is entered whenever a flag stands (the
        # hysteresis and its clearing are the method's), or whenever either
        # demand is over its ceiling. This matters because the model is ticked
        # at 1 kHz inside the MPC's transition rolls, which run against a
        # per-callback budget.
        if st.deferred_fc or st.deferred_bt:
            if st.gov_fc_clamped or st.gov_bt_clamped:
                self._clear_ceiling_state()
        else:
            _tot = st.filt_total
            if (st.gov_fc_clamped or st.gov_bt_clamped
                    or sp_target * _tot > _FC_CEIL_A
                    or (1.0 - sp_target) * _tot > _BT_CEIL_A):
                sp_target = self._apply_share_current_ceilings(sp_target)

        # Effective-setpoint slew (.ino:10290).
        st.sp_eff_prev = _constrain(sp_target, st.sp_eff_prev - slew,
                                    st.sp_eff_prev + slew)
        sp_eff = st.sp_eff_prev

        # CONTROLLER SURROGATE — fidelity boundary 1. The firmware forms its
        # error against the MEASURED share |I_fc|/I_tot (.ino:10314), so the
        # surrogate does the same and integrates it:
        #     u_next = u + beta * (sp_eff - alpha_measured)
        # with beta = 1 by default. Three properties follow, and all three are
        # load-bearing:
        #   * with both channels live, alpha_measured is the static law applied
        #     to the standing ratio, so the fixed point is exactly the ratio
        #     that delivers sp_eff — the integral action absorbing dV0;
        #   * beta = 1 makes the demanded step the whole error, so the SLEW
        #     LIMITER below is what governs the approach: "walks toward the
        #     governed reference at the tick's ceiling and holds there once
        #     arrived", which is the whitepaper-licensed model;
        #   * when TOPOLOGY pins the measurement — a channel off the bus, so
        #     alpha_measured is 0.0 or 1.0 regardless of the ratio — the error
        #     never closes and the ratio winds to the band edge. That is the
        #     mechanism behind the DROOP_R_MIN wind-up recorded during every
        #     FC-charge window (CLAUDE.md, 2026-09-01c), and a surrogate that
        #     assumed perfect tracking cannot reproduce it.
        # conv_tau_s < the tick period leaves this unchanged; a larger value
        # slows the integral action so a later round can fit a rise time.
        if st.sw_fc and st.sw_bt:
            demand = self._ratio_for_delivered(sp_eff, total)
        else:
            # TOPOLOGY-PINNED MEASUREMENT. With one channel off the bus the
            # measured share is 0.0 or 1.0 whatever the ratio is, so the error
            # never closes and the integrator runs to its authority limit. The
            # ratio then sits at the band edge the clip in _apply_share_ratio()
            # imposes. Sign from the standing error, exactly as the integrator's
            # would be.
            alpha_meas = 1.0 if st.sw_fc else 0.0
            demand = 0.0 if alpha_meas > sp_eff else 1.0
        if self.conv_tau_s > 0.0:
            beta = 1.0 - math.exp(-self.dt_s / self.conv_tau_s)
            st.ctrl_out += beta * (demand - st.ctrl_out)
        else:
            st.ctrl_out = demand
        # Output clamp = the Youla wrapper's own [0, 1] authority span with
        # anti-windup (.ino:10318 comment).
        droop_ratio = _constrain(st.ctrl_out, 0.0, 1.0)

        # Ratio slew limit — IN-BAND RATIOS ONLY. An out-of-band command passes
        # through unlimited so applyShareRatio() sees the controller's true
        # intent (.ino:10339).
        if _R_MIN <= droop_ratio <= _R_MAX:
            droop_ratio = _constrain(droop_ratio, st.r_prev - slew,
                                     st.r_prev + slew)

        wrote, rl, rb = self._apply_share_ratio(droop_ratio, i_fc, i_batt,
                                                t_ms, from_controller=True)
        return self._out(MODE_CLOSED, rl, rb, wrote)

    # ── setDroopMdac() ───────────────────────────────────────────────────────
    def set_droop_mdac(self, g_fc: float, g_bt: float):
        """``setDroopMdac()`` (.ino:11841). Returns the two AD5443 words and
        charges the fw v27 rev 2 g-guard.

        THE CLAMP IS THE PROTECTION; THE COUNTER IS THE OBSERVABILITY. The
        load-scheduled k_d keeps ``g <= SHARE_KD_SAFETY`` at the band edge BY
        CONSTRUCTION, but that is a statement about the REFERENCE: the ~20 ms
        governor filter under-reads a rising load (the fw v26 clamp-sweep
        finding, 25.6 % against a 12 % design headroom), so a stale light-load
        ``k_d`` can meet a ratio the controller has already slewed toward a
        high-load value and give ``g = k_d/(RE_MAX*r) > 1``. The ``constrain()``
        below has always silently clipped that; the count is what stops "the
        droop network is saturated" from being invisible.

        Charged ONCE per clamped WRITE — a call whose two gains BOTH exceed full
        scale charges one event, not two — and SATURATING at 0xFFFF rather than
        wrapping, because a wrapped-to-zero count would read as "never
        happened"."""
        if g_fc > 1.0 or g_bt > 1.0:
            if self.state.g_guard_count < 0xFFFF:
                self.state.g_guard_count += 1
        return _mdac_code(g_fc), _mdac_code(g_bt)

    # ── result packing ───────────────────────────────────────────────────────
    def _out(self, mode: str, refused_load: bool,
             refused_blank: bool, wrote: bool = False) -> GovernorOut:
        st = self.state
        st.mode_counts[mode] = st.mode_counts.get(mode, 0) + 1
        r = st.r_prev
        # fw v27 rev 2: the LIVE scheduled scale, not the fixed floor. Above the
        # 0.906 A crossover the schedule IS K_DROOP, so every code here is
        # bit-identical to fw v26 there.
        kd = st.droop_kd
        g_fc = kd / (_RE_MAX * r) if r > 0.0 else 1.0
        g_bt = kd / (_RE_MAX * (1.0 - r)) if r < 1.0 else 1.0
        wrote_now = bool(wrote) and mode not in NON_WRITING_MODES
        # Only a tick that actually reached setDroopMdac() may charge the
        # g-guard; a non-writing return reports the STANDING split and touches
        # no counter.
        if wrote_now:
            code_fc, code_bt = self.set_droop_mdac(g_fc, g_bt)
        else:
            code_fc, code_bt = _mdac_code(g_fc), _mdac_code(g_bt)
        g_fc = _constrain(g_fc, 0.0, 1.0)
        g_bt = _constrain(g_bt, 0.0, 1.0)
        return GovernorOut(
            r_applied=r,
            mode=mode,
            fc_bus_req=st.sw_fc,
            bt_bus_req=st.sw_bt,
            cut_refused_load=refused_load,
            cut_refused_blank=refused_blank,
            g_fc=g_fc,
            g_bt=g_bt,
            code_fc=code_fc,
            code_bt=code_bt,
            wrote=wrote_now,
            ceil_fc=st.gov_fc_clamped,
            ceil_bt=st.gov_bt_clamped,
            k_d=kd,
            g_clamp_count=st.g_guard_count,
            batt_only=st.batt_only_active,
        )

    # ── convenience ──────────────────────────────────────────────────────────
    def mode_fractions(self) -> dict:
        st = self.state
        n = sum(st.mode_counts.values())
        if n == 0:
            return {m: 0.0 for m in MODES}
        return {m: st.mode_counts.get(m, 0) / float(n) for m in MODES}

    def ceiling_fraction(self) -> float:
        """Fraction of MODE-counted ticks on which the fw v26 clamp was
        engaged. Zero on any stimulus below CEILING_REACHABLE_I_TOT_A."""
        st = self.state
        n = sum(st.mode_counts.values())
        return 0.0 if n == 0 else st.ceil_ticks / float(n)


# ─────────────────────────────────────────────────────────────────────────────
# Validation harness: replay a campaign CSV through the model
# ─────────────────────────────────────────────────────────────────────────────
SW_FC_BUS = 0x01     # hil_plant_sim.py:166
SW_BT_BUS = 0x02
SW_MOT_PWR = 0x04


def replay_governor(rows, *, dt_s: float = 1e-3, dv0_v: float = 0.0,
                    conv_tau_s: float = 0.0, state_filter: int = 2,
                    seed_from_first_codes: bool = True,
                    move_window_ticks: int = 50,
                    step_states=(2, 98)) -> dict:
    """Replay observed rows through the model and score the applied ratio.

    ``rows`` is any iterable of mappings carrying at least ``t``,
    ``cmd_share_sp``, ``I_fc``, ``I_batt``, ``switch``, ``mdac_fc``,
    ``mdac_bt`` and (optionally) ``state``. Missing or blank fields skip the
    row. Residuals are accumulated only on rows whose ``state`` equals
    ``state_filter`` (2 = Run) and which carry both MDAC words.

    ``step_states`` NAMES THE STATES IN WHICH THE MODEL IS TICKED AT ALL, and
    the default is load-bearing. ``powerBalance()`` is called from exactly two
    sites — ``doState2()`` (.ino:5892) and ``doState98()`` (.ino:7087, :7112,
    :7134, :7143, :7159, :7173) — so the share loop does NOT run in Init, Idle,
    Finish or Error, and no ordinary state transition resets its state
    (``resetShareControlState()`` is called by profile starts and
    ``hilWarmReset()``, not by an Idle -> Run entry). Ticking the model through
    the bring-up transient therefore let a pre-Run current excursion arm
    ``shareClosedLoopRun``, after which every Run tick took the HOLD branch at
    the reset seed while the board fed the setpoint forward — measured on
    ``ems-sdp`` as a whole-run RMS of 0.1277 against 0.0028 once the states are
    honoured. Pass ``None`` to tick unconditionally.

    The model is stepped on every supplied row in an admitted state, so a caller
    that decimates the log is modelling a decimated firmware.

    WHAT THIS CAN AND CANNOT PROVE. The observation stream is a 1 kHz mirror of
    a firmware that ran its own 1 kHz loop, so the tick alignment is
    approximate: a sub-millisecond phase difference shows as a one-tick lag on
    every slewing edge. Read the RMS as a steady-state agreement figure and the
    maximum as a transient-alignment figure, never the other way round.

    ⚠️ A WHOLE-RUN RMS CAN BE VACUOUS. A run whose observed ratio never moves
    is agreement with a constant, and a model that merely holds its seed scores
    a perfect RMS on it. ``n_moving`` counts the scored rows whose observed
    ratio DIFFERS from the previous scored row's, and ``rms_moving`` restricts
    the residual to the +/-``move_window_ticks`` neighbourhood of those rows —
    the ticks where the governor actually decided something. When ``n_moving``
    is zero the run is reported as ``verdict == "UNSCORED"`` and both moving
    figures are NaN; such a run is not evidence of agreement and must never be
    quoted as one.

    Returns a dict with ``n``, ``n_scored``, ``n_moving``, ``rms``,
    ``rms_moving``, ``n_scored_moving_window``, ``max_abs``, ``max_abs_t``,
    ``verdict``, ``mode_fractions`` and ``mode_counts``.
    """
    def _f(row, key):
        v = row.get(key)
        if v is None or v == "":
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _i(row, key):
        v = _f(row, key)
        return None if v is None else int(v)

    if move_window_ticks < 0:
        raise ValueError("move_window_ticks must not be negative")
    step_set = None if step_states is None else frozenset(step_states)
    gov = GovernorModel(dt_s=dt_s, dv0_v=dv0_v, conv_tau_s=conv_tau_s)
    seeded = not seed_from_first_codes
    sq = 0.0
    n_scored = 0
    n = 0
    max_abs = 0.0
    max_abs_t = None
    # Scored samples, kept so the moving-window restriction can be applied after
    # the walk: a window is centred on a moving row and reaches BACKWARD as well
    # as forward, which a single streaming pass cannot honour.
    errs = []
    moving_idx = []
    prev_obs = None

    for row in rows:
        t = _f(row, "t")
        sp = _f(row, "cmd_share_sp")
        i_fc = _f(row, "I_fc")
        i_bt = _f(row, "I_batt")
        sw = _i(row, "switch")
        if t is None or sp is None or i_fc is None or i_bt is None or sw is None:
            continue
        code_fc = _i(row, "mdac_fc")
        code_bt = _i(row, "mdac_bt")
        r_obs = r_from_codes(code_fc, code_bt)
        state = _i(row, "state")

        # Outside the share loop's own states the firmware does not tick it, so
        # neither does the model — and it is not seeded from them either.
        if step_set is not None and state not in step_set:
            continue

        if not seeded:
            # Seed the model from the hardware's own applied ratio, so the
            # residual measures the governor's DECISIONS and not an arbitrary
            # difference in starting split.
            if r_obs is None:
                continue
            gov.reset(r_obs)
            seeded = True

        out = gov.step(sp, i_fc, i_bt,
                       bool(sw & SW_FC_BUS), bool(sw & SW_BT_BUS), t)
        n += 1

        if r_obs is None or (state_filter is not None and state != state_filter):
            continue
        err = out.r_applied - r_obs
        sq += err * err
        if prev_obs is not None and r_obs != prev_obs:
            moving_idx.append(n_scored)
        prev_obs = r_obs
        errs.append(err)
        n_scored += 1
        if abs(err) > max_abs:
            max_abs = abs(err)
            max_abs_t = t

    # Moving-window restriction. Union of [i-w, i+w] over the moving rows,
    # computed by interval merge so an O(n*w) scan cannot blow up on a long run.
    n_moving = len(moving_idx)
    sq_mov = 0.0
    n_mov_win = 0
    if n_moving:
        w = move_window_ticks
        lo_prev = hi_prev = None
        for i in moving_idx:
            lo, hi = max(0, i - w), min(n_scored - 1, i + w)
            if hi_prev is not None and lo <= hi_prev + 1:
                hi_prev = max(hi_prev, hi)
                continue
            if hi_prev is not None:
                for j in range(lo_prev, hi_prev + 1):
                    sq_mov += errs[j] * errs[j]
                    n_mov_win += 1
            lo_prev, hi_prev = lo, hi
        if hi_prev is not None:
            for j in range(lo_prev, hi_prev + 1):
                sq_mov += errs[j] * errs[j]
                n_mov_win += 1

    return {
        "n": n,
        "n_scored": n_scored,
        "n_moving": n_moving,
        "n_scored_moving_window": n_mov_win,
        "rms": math.sqrt(sq / n_scored) if n_scored else float("nan"),
        "rms_moving": (math.sqrt(sq_mov / n_mov_win) if n_mov_win
                       else float("nan")),
        "max_abs": max_abs if n_scored else float("nan"),
        "max_abs_t": max_abs_t,
        # A run with no observed ratio motion is agreement with a constant and
        # is NOT evidence about the governor.
        "verdict": "SCORED" if n_moving else "UNSCORED",
        "mode_fractions": gov.mode_fractions(),
        "mode_counts": dict(gov.state.mode_counts),
        "refused_load_ticks": gov.state.refused_load,
        "refused_blank_ticks": gov.state.refused_blank,
    }


def replay_csv(path: str, **kwargs) -> dict:
    """``replay_governor()`` over a campaign CSV file path."""
    import csv

    with open(path, "r", newline="", encoding="utf-8") as fh:
        return replay_governor(csv.DictReader(fh), **kwargs)


if __name__ == "__main__":       # pragma: no cover - operator convenience
    import argparse
    import json

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("csv", nargs="+", help="campaign CSV(s) to replay")
    ap.add_argument("--dv0", type=float, default=0.0)
    ap.add_argument("--conv-tau", type=float, default=0.0)
    a = ap.parse_args()
    for p in a.csv:
        res = replay_csv(p, dv0_v=a.dv0, conv_tau_s=a.conv_tau)
        print(p)
        print(json.dumps(res, indent=2, sort_keys=True))
