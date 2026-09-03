#!/usr/bin/env python3
"""Probe: the offline governor walk the two `fw26-clamp-*` expectations are cut
from.

WHY THIS EXISTS.  Every bound in `FAULT_EXPECTATIONS["fw26-clamp-cruise"]` and
`["fw26-clamp-sweep"]` is a WALK, not a measurement, and the walk was originally
run once by hand.  A number nobody can regenerate is a number nobody can check,
so the walk lives here and `tools/test_run_hil_suite.py` regenerates the
governing figures from it.

WHAT IT MODELS, and what it does not.  The stimulus is reduced to its
electrical essentials: a CONSTANT two-source total per phase or region, and the
commanded share the Pi timeline sets.  `tools/governor_model.py` -- the port
proven equivalent to `applyShareCurrentCeilings()` by
`test/gov_ceiling_harness.cpp` -- is ticked at 1 kHz against it, with the
delivered share fed back through `GovernorModel.delivered_share()` exactly as
`ems_walk.walk()` does.

It does NOT model the drive loop.  For `fw26-clamp-sweep` the per-region totals
are the HOST demand model's (`run_hil_suite._fw26_region_total()`); on the board
the drive loop sets the VESC current and therefore the total.  That is the
prediction the entry's `provisional_note` warns about, and it is why the
tolerances are what they are.

Usage:
    C:/Users/ricky/miniforge3/python.exe tools/probes/probe_fw26_clamp_walk.py
    C:/Users/ricky/miniforge3/python.exe tools/probes/probe_fw26_clamp_walk.py --dv0 0.0
"""
import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import governor_model as gov_mod                                # noqa: E402

# The plant's measured converter asymmetry. The entries are walked at BOTH this
# and 0.0; the two agree on every current to four decimals, because the clamp
# pins the fuel-cell CURRENT and the asymmetry moves only the RATIO that
# delivers it.
DV0_MEASURED_V = 0.013522

DT_S = 1e-3


def walk_phase(total_a, share, seconds, *, dv0_v=0.0, gov=None, t0=0.0,
               settle_s=0.0):
    """Tick the governor at a constant total and commanded share.

    Returns (gov, stats) so a caller can carry one governor across phases, which
    is what makes the release in `fw26-clamp-cruise`'s phase B a SAME-RUN
    negative control rather than a second run."""
    if gov is None:
        gov = gov_mod.GovernorModel(dt_s=DT_S, seed_r=0.5, dv0_v=dv0_v)
    d = 0.5
    n = int(round(seconds / DT_S))
    clamped = 0
    i_fc_max = 0.0
    i_fc_last = 0.0
    i_bt_last = 0.0
    r_last = None
    codes = (None, None)
    switch_low = 0
    # SETTLED-WINDOW statistics, which are what the suite's checks judge: every
    # window in both entries is inset from its own command edge. The
    # whole-phase figures are kept beside them so the transient is visible
    # rather than hidden by the inset.
    n_settle = int(round(settle_s / DT_S))
    s_clamped = 0
    s_n = 0
    s_i_fc_max = 0.0
    s_i_fc_min = float("inf")
    for k in range(n):
        i_fc = d * total_a
        o = gov.step(share, i_fc, total_a - i_fc, True, True,
                     (t0 + k * DT_S) * 1000.0)
        d = gov.delivered_share(o.r_applied, total_a, o.fc_bus_req, o.bt_bus_req)
        i_fc_last, i_bt_last = d * total_a, (1.0 - d) * total_a
        i_fc_max = max(i_fc_max, i_fc_last)
        clamped += int(o.ceil_fc or o.ceil_bt)
        r_last = o.r_applied
        codes = (o.code_fc, o.code_bt)
        if not (o.fc_bus_req and o.bt_bus_req):
            switch_low += 1
        if k >= n_settle:
            s_n += 1
            s_clamped += int(o.ceil_fc or o.ceil_bt)
            s_i_fc_max = max(s_i_fc_max, i_fc_last)
            s_i_fc_min = min(s_i_fc_min, i_fc_last)
    return gov, {"ticks": n, "clamped_ticks": clamped,
                 "settled_ticks": s_n, "settled_clamped_ticks": s_clamped,
                 "settled_clamp_duty": s_clamped / float(s_n) if s_n else 0.0,
                 "settled_i_fc_peak": s_i_fc_max,
                 "settled_i_fc_min": (None if s_i_fc_min == float("inf")
                                      else s_i_fc_min),
                 "clamp_duty": clamped / float(n) if n else 0.0,
                 "i_fc": i_fc_last, "i_fc_peak": i_fc_max, "i_batt": i_bt_last,
                 "balance_residual": abs(total_a - i_fc_last - i_bt_last),
                 "r_applied": r_last, "mdac_fc": codes[0], "mdac_bt": codes[1],
                 "switch_low_ticks": switch_low}


# -- fw26-clamp-cruise --------------------------------------------------------
CRUISE_TOTAL_A = 2.00
# The timeline's own three commanded shares. The pre-phase is the firmware's
# default 0.50 split, held from t = 5.0 to t = 8.0.
CRUISE_PRE_PHASE = (0.50, 3.0)
CRUISE_PHASE_A = (0.75, 16.0)     # commanded share, seconds
CRUISE_PHASE_B = (0.40, 8.0)
# The inset `FAULT_EXPECTATIONS["fw26-clamp-cruise"]` applies to both phase
# windows (8.0 -> 8.5 and 26.0 -> 27.0). The settled figures below are the ones
# its bounds are written against.
CRUISE_SETTLE_S = 0.5


def cruise(dv0_v=DV0_MEASURED_V):
    """The pre-phase, then phase A, then phase B, ONE governor.

    THE PRE-PHASE IS LOAD-BEARING and was missing from the first hand-run of
    this walk. `SCENARIOS["fw26-clamp-cruise"]`'s timeline commands share 0.50
    from t = 5.0 and steps to 0.75 at t = 8.0, so the governor enters phase A
    ALREADY CONVERGED at r = 0.4944 / I_fc 1.0000 A. Starting phase A from the
    constructor's seed instead lets the reference slew from an unconverged
    state and reports a 1.5000 A transient the scenario never produces."""
    g, _pre = walk_phase(CRUISE_TOTAL_A, CRUISE_PRE_PHASE[0],
                         CRUISE_PRE_PHASE[1], dv0_v=dv0_v)
    g, a = walk_phase(CRUISE_TOTAL_A, CRUISE_PHASE_A[0], CRUISE_PHASE_A[1],
                      gov=g, t0=CRUISE_PRE_PHASE[1], settle_s=CRUISE_SETTLE_S)
    _, b = walk_phase(CRUISE_TOTAL_A, CRUISE_PHASE_B[0], CRUISE_PHASE_B[1],
                      gov=g, t0=CRUISE_PRE_PHASE[1] + CRUISE_PHASE_A[1],
                      settle_s=CRUISE_SETTLE_S)
    return {"pre_phase": _pre, "phase_a": a, "phase_b": b}


# -- fw26-clamp-sweep ---------------------------------------------------------
# The region table is imported from the simulator so it cannot drift from the
# stimulus; the per-region totals come from the suite's own helper, so the walk
# and the check labels quote one number.
def sweep(dv0_v=DV0_MEASURED_V, neutralise=False):
    import hil_plant_sim as sim
    import run_hil_suite as rhs
    saved = (gov_mod.CEILING_REACHABLE_I_TOT_A, gov_mod._FC_CEIL_A,
             gov_mod._BT_CEIL_A)
    if neutralise:
        # The fw v25 arithmetic: the ceilings pinned out of reach.
        gov_mod._FC_CEIL_A = 1e9
        gov_mod._BT_CEIL_A = 1e9
        gov_mod.CEILING_REACHABLE_I_TOT_A = 1e9
    try:
        out = []
        g = None
        t = 0.0
        for i, (t0, v, sp, want_clamp) in enumerate(
                sim.FW26_CLAMP_SWEEP_REGIONS, start=1):
            total = rhs._fw26_region_total(v)
            g, st = walk_phase(total, sp, sim.FW26_CLAMP_SWEEP_REGION_S,
                               dv0_v=dv0_v, gov=g, t0=t,
                               settle_s=rhs._FW26_SWEEP_SETTLE_S)
            t += sim.FW26_CLAMP_SWEEP_REGION_S
            st.update({"region": i, "v": v, "share": sp, "i_tot": total,
                       "expected_clamp": want_clamp})
            out.append(st)
    finally:
        (gov_mod.CEILING_REACHABLE_I_TOT_A, gov_mod._FC_CEIL_A,
         gov_mod._BT_CEIL_A) = saved
    return out


# -- fw26-clamp-sweep, BOUNDARY RECONSTRUCTION (campaign E, 2026-09-03) -------
#
# WHY A SECOND WALK.  `sweep()` above ticks each region at a CONSTANT total, so
# it reports the settled operating point and a transient that assumes the total
# steps instantaneously.  Neither is what a boundary does on the board: an
# upward velocity step RAILS the drive controller at its 12 A current clamp, and
# the two-source total then follows the vehicle's own speed.  The campaign E
# latch happened in exactly that window, so the quantity the fix has to be
# judged on is the peak delivered fuel-cell current ACROSS a boundary, with the
# governor's ~20 ms load EMA and its 0.02/tick reference slew both lagging it.
#
# THE RAIL MODEL, and its calibration.  While the drive controller is railed the
# motor's contribution to the bus current is proportional to vehicle speed (the
# rail pins the motor CURRENT, so the bus POWER follows the back-EMF):
#
#     I_tot(t) = I_AUX_A + preload + RAIL_K_A_PER_MPS * v(t),  v ramping at
#     RAIL_A_MPS2 from v_prev to v_new; then the settled term at v_new.
#
# Both constants are fitted to campaign E's own boundaries, and the fit is the
# reason this model is allowed to carry a bound at all:
#
#   boundary     v_prev -> v_new   measured                 model
#   t = 14 s     0.0 -> 3.0        no step, then 1.33 A/s    no step, 1.41 A/s
#   t = 26 s     0.5 -> 2.5        +0.295 A step, 1.32 A/s   +0.296 A, 1.41 A/s
#   t = 38 s     2.5 -> 3.0        +1.148 A step             +1.173 A
#
# The model is CONSERVATIVE at every one of the three - it never under-predicts
# the step or the ramp rate - which is the direction a safety bound needs.
#
# WARNING - IT IS STILL A MODEL.  The board's drive loop, not this arithmetic,
# sets the real total, and t = 38 is the only boundary at which a railed total
# was ever observed: the run latched 29 ms into it, so nothing past that instant
# has ever been measured.  Re-fit both constants on the first campaign that runs
# the bridged table to completion.
RAIL_K_A_PER_MPS = 0.76         # A of bus current per m/s while railed
RAIL_A_MPS2 = 1.85              # m/s^2 while railed
# The demand model's SETTLED motor term at each velocity the table uses.  Kept
# here rather than imported so the probe does not depend on the suite for the
# one number it needs from it; `test_run_hil_suite.py` pins the two against each
# other.
SETTLED_MOTOR_A = {0.0: 0.0, 0.5: 0.0844, 1.5: 0.3143, 2.5: 0.6275,
                   3.0: 0.8163}


def reconstruct_sweep(regions=None, bridge_s=None, dv0_v=DV0_MEASURED_V,
                      t_start=5.0, t_end=80.0, pre_share=0.50):
    """Tick the sweep's commands at 1 kHz through the rail model.

    Returns (rows, peaks): `rows` is a list of
    (t, i_tot, i_fc, share, v_cmd, clamped) and `peaks` maps each region start
    to the largest delivered I_fc from that boundary to the next region's."""
    import hil_plant_sim as sim
    regions = sim.FW26_CLAMP_SWEEP_REGIONS if regions is None else regions
    bridge_s = (sim.FW26_CLAMP_SWEEP_BRIDGE_S if bridge_s is None
                else bridge_s)
    base = sim.I_AUX_A + sim.FW26_CLAMP_SWEEP_PRELOAD_A
    cmds = ([(t_start, {"v_setpoint": 0.0,
                        "power_share_setpoint": pre_share})]
            + sim.fw26_sweep_commands(regions, bridge_s, pre_share=pre_share))
    g = gov_mod.GovernorModel(dt_s=DT_S, seed_r=0.5, dv0_v=dv0_v)
    d = pre_share
    v_act, v_cmd, sp = 0.0, 0.0, pre_share
    idx = 0
    rows = []
    n = int(round((t_end - t_start) / DT_S))
    for k in range(n):
        t = t_start + k * DT_S
        while idx < len(cmds) and cmds[idx][0] <= t + 1e-9:
            v_cmd = cmds[idx][1].get("v_setpoint", v_cmd)
            sp = cmds[idx][1].get("power_share_setpoint", sp)
            idx += 1
        if v_cmd > v_act + 1e-9:
            v_act = min(v_cmd, v_act + RAIL_A_MPS2 * DT_S)
            motor = RAIL_K_A_PER_MPS * v_act
        else:
            v_act = v_cmd
            motor = SETTLED_MOTOR_A[v_cmd]
        tot = base + motor
        i_fc = d * tot
        o = g.step(sp, i_fc, tot - i_fc, True, True, t * 1000.0)
        d = g.delivered_share(o.r_applied, tot, o.fc_bus_req, o.bt_bus_req)
        rows.append((t, tot, d * tot, sp, v_cmd, bool(o.ceil_fc or o.ceil_bt)))
    edges = [r[0] for r in regions] + [t_end]
    peaks = {}
    for i, t0 in enumerate(edges[:-1]):
        w = [r[2] for r in rows if t0 - 1e-9 <= r[0] < edges[i + 1]]
        peaks[t0] = max(w) if w else None
    return rows, peaks


def boundary_report(regions=None, bridge_s=None, dv0_v=DV0_MEASURED_V):
    """(peaks, whole-table peak) for one table - the probe's print and the
    discriminating test in `tools/test_run_hil_suite.py` read the same call."""
    rows, peaks = reconstruct_sweep(regions, bridge_s, dv0_v)
    return peaks, max(r[2] for r in rows)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dv0", type=float, default=DV0_MEASURED_V,
                    help="converter asymmetry [V] (default: the measured one)")
    args = ap.parse_args(argv)

    c = cruise(args.dv0)
    print("fw26-clamp-cruise, dv0 %.6f V, total %.2f A" % (args.dv0,
                                                           CRUISE_TOTAL_A))
    for name, st in (("phase A (share 0.75)", c["phase_a"]),
                     ("phase B (share 0.40)", c["phase_b"])):
        print("  %-22s whole-phase duty %.4f peak %.4f | SETTLED duty %.4f "
              "I_fc [%.4f, %.4f] last %.4f  I_batt %.4f  r %.4f  "
              "residual %.1e  switch-low %d"
              % (name, st["clamp_duty"], st["i_fc_peak"],
                 st["settled_clamp_duty"], st["settled_i_fc_min"],
                 st["settled_i_fc_peak"], st["i_fc"], st["i_batt"],
                 st["r_applied"], st["balance_residual"],
                 st["switch_low_ticks"]))

    print("")
    print("fw26-clamp-sweep, dv0 %.6f V" % args.dv0)
    absent = {r["region"]: r for r in sweep(args.dv0, neutralise=True)}
    print("  reg   v    sp    I_tot    I_fc    I_batt  s_duty  mdac_fc  "
          "mdac_bt   absent_fc absent_bt  clamp?")
    for r in sweep(args.dv0):
        a = absent[r["region"]]
        print("  %3d  %3.1f  %.2f  %7.3f  %6.4f  %6.4f  %5.3f  %7d  %7d   "
              "%7d   %7d  %s"
              % (r["region"], r["v"], r["share"], r["i_tot"], r["i_fc"],
                 r["i_batt"], r["settled_clamp_duty"], r["mdac_fc"],
                 r["mdac_bt"],
                 a["mdac_fc"], a["mdac_bt"],
                 "YES" if r["expected_clamp"] else "no"))

    print("")
    print("fw26-clamp-sweep BOUNDARY RECONSTRUCTION (rail model, EMA lag)")
    import hil_plant_sim as _sim
    pk_fix, run_fix = boundary_report(dv0_v=args.dv0)
    pk_raw, run_raw = boundary_report(bridge_s=0.0, dv0_v=args.dv0)
    print("  region start   bridged peak I_fc   UNBRIDGED peak I_fc")
    for i, (t0, _v, _sp, _c) in enumerate(_sim.FW26_CLAMP_SWEEP_REGIONS,
                                          start=1):
        print("   %2d  t=%5.1f      %7.4f            %7.4f%s"
              % (i, t0, pk_fix[t0], pk_raw[t0],
                 "   <-- over LIMIT_I_FC_MAX unbridged"
                 if pk_raw[t0] > 1.40 else ""))
    print("  whole-table peak: bridged %.4f A, unbridged %.4f A "
          "(LIMIT_I_FC_MAX 1.40 A, bridge %.2f s)"
          % (run_fix, run_raw, _sim.FW26_CLAMP_SWEEP_BRIDGE_S))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
