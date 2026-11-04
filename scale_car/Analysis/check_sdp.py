#!/usr/bin/env python3
"""
check_sdp.py — SDP run analysis.

Answers the four questions that matter for the first SDP run:

  1. Did braking actually charge the pack?      (regen arming + I_batt sign)
  2. Did SOC stay inside 0.25-0.90?            (band + guard excursions)
  3. Did the FC ever charge the pack?           (must be zero, by construction)
  4. How well did the governor track share?     (same metric as the sweep runs)

Read-only. Does not touch fchev_plot.py.

Usage:
    python3 check_sdp.py /path/to/rosbag_sdp_YYYY-MM-DD_HH-MM-SS
"""

import glob
import os
import sys

try:
    from mcap_ros2.reader import read_ros2_messages
except ImportError:
    sys.exit("pip install mcap mcap-ros2-support")

SOC_MIN, SOC_MAX = 0.25, 0.90
GUARD_LOW_ENTER, GUARD_LOW_EXIT = 0.30, 0.33
GUARD_HIGH_ENTER, GUARD_HIGH_EXIT = 0.88, 0.85
REGEN_PDEM_W = -2.0
MODE_NAMES = {0: "HYBRID", 1: "FC_ONLY", 2: "BATT", 3: "IDLE", 4: "SAFE"}

VS = ["v_actual", "V_batt", "I_batt", "I_charge", "V_fc", "I_fc", "V_bus",
      "V_rgn", "V_chg", "power_share_actual", "droop_FC", "droop_BT",
      "charger_status", "switch_state", "fault_flags", "error_code",
      "error_source_state", "SOC"]
EC = ["v_setpoint", "power_share_cmd", "charge_goal", "mode", "droop_enable"]
DC = ["v_ref", "P_demand", "elapsed_s", "progress"]
ED = ["P_fc", "P_batt", "power_share_diag", "feasible", "soc_clamped",
      "solve_ms", "mode_diag"]
FIELDS = {"/vehicle_state": VS, "/ems_command": EC,
          "/drive_cycle": DC, "/ems_diagnostics": ED}


def find_mcap(path):
    if os.path.isfile(path) and path.endswith(".mcap"):
        return path
    if os.path.isdir(path):
        hits = glob.glob(os.path.join(path, "*.mcap"))
        if len(hits) == 1:
            return hits[0]
        sys.exit(f"Expected one .mcap in {path}, found {len(hits)}")
    sys.exit(f"Not found: {path}")


def read(mcap_path):
    out = {t: {"t": [], **{f: [] for f in fs}} for t, fs in FIELDS.items()}
    t0 = None
    for m in read_ros2_messages(mcap_path):
        topic = m.channel.topic
        if topic not in FIELDS:
            continue
        ts = m.log_time_ns / 1e9
        if t0 is None:
            t0 = ts
        d = list(m.ros_msg.data)
        fs = FIELDS[topic]
        if len(d) < len(fs):
            continue
        out[topic]["t"].append(ts - t0)
        for i, f in enumerate(fs):
            out[topic][f].append(float(d[i]))
    return out


def mean(x):
    return sum(x) / len(x) if x else float("nan")


def rms(x):
    return (sum(v * v for v in x) / len(x)) ** 0.5 if x else float("nan")


def resample(t_src, v_src, t_tgt):
    """Zero-order hold onto t_tgt."""
    out, j, n = [], 0, len(t_src)
    for tt in t_tgt:
        while j + 1 < n and t_src[j + 1] <= tt:
            j += 1
        out.append(v_src[j] if n else float("nan"))
    return out


def runs_of(flags):
    """Contiguous True runs as (start_idx, end_idx_inclusive)."""
    out, s = [], None
    for i, f in enumerate(flags):
        if f and s is None:
            s = i
        elif not f and s is not None:
            out.append((s, i - 1))
            s = None
    if s is not None:
        out.append((s, len(flags) - 1))
    return out


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    bag = sys.argv[1]
    d = read(find_mcap(bag))

    vs, ec, dc = d["/vehicle_state"], d["/ems_command"], d["/drive_cycle"]
    if not vs["t"]:
        sys.exit("No /vehicle_state messages — bag is empty.")
    if not ec["t"]:
        sys.exit("No /ems_command messages — the EMS node never published. "
                 "Check the EMS pane for a startup traceback.")

    dur = vs["t"][-1]
    print(f"bag       {os.path.basename(bag.rstrip('/'))}")
    print(f"duration  {dur:.1f} s")
    print(f"messages  vehicle_state {len(vs['t'])} ({len(vs['t'])/dur:.1f} Hz)"
          f" | ems_command {len(ec['t'])} ({len(ec['t'])/dur:.1f} Hz)"
          f" | drive_cycle {len(dc['t'])}")

    # ── 1. SOC band ──────────────────────────────────────────────────────────
    soc = vs["SOC"]
    print("\n--- 1. SOC band ---")
    print(f"start {soc[0]:.4f}   end {soc[-1]:.4f}   "
          f"delta {soc[-1]-soc[0]:+.4f}")
    print(f"min   {min(soc):.4f}   max {max(soc):.4f}")
    below = sum(1 for s in soc if s < SOC_MIN)
    above = sum(1 for s in soc if s > SOC_MAX)
    print(f"outside [{SOC_MIN},{SOC_MAX}]: {below} below, {above} above "
          f"-> {'OK' if below == 0 and above == 0 else 'BAND VIOLATED'}")
    lo_g = sum(1 for s in soc if s < GUARD_LOW_ENTER) / len(soc) * 100
    hi_g = sum(1 for s in soc if s > GUARD_HIGH_ENTER) / len(soc) * 100
    print(f"time under low guard {GUARD_LOW_ENTER}: {lo_g:.1f}%   "
          f"over high guard {GUARD_HIGH_ENTER}: {hi_g:.1f}%")

    # ── 2. Mode distribution ─────────────────────────────────────────────────
    modes = [int(round(m)) for m in ec["mode"]]
    print("\n--- 2. Modes ---")
    for m in sorted(set(modes)):
        n = modes.count(m)
        print(f"{MODE_NAMES.get(m, m):8s} {n:6d}  {n/len(modes)*100:5.1f}%")
    sdp_frac = modes.count(0) / len(modes) * 100
    print(f"SDP actually ran (HYBRID) {sdp_frac:.1f}% of the run"
          + ("" if sdp_frac > 20 else "   <-- LOW, guards dominated"))

    # ── 3. Regen on braking ──────────────────────────────────────────────────
    print("\n--- 3. Regen on braking ---")
    if not dc["t"]:
        print("no /drive_cycle — cannot evaluate braking")
    else:
        pdem = resample(dc["t"], dc["P_demand"], ec["t"])
        chg = ec["charge_goal"]
        braking = [p < REGEN_PDEM_W for p in pdem]
        nb = sum(braking)
        print(f"braking samples (P_demand < {REGEN_PDEM_W} W): "
              f"{nb} / {len(braking)}  ({nb/len(braking)*100:.1f}%)")
        if nb == 0:
            print("NO BRAKING in this cycle — regen could not arm. "
                  "Check the drive cycle has decelerations.")
        else:
            armed = sum(1 for b, c in zip(braking, chg) if b and c > 0.05)
            leaked = sum(1 for b, c in zip(braking, chg) if not b and c > 0.05)
            print(f"armed while braking     {armed}/{nb} "
                  f"({armed/nb*100:.1f}%)  -> "
                  f"{'OK' if armed/nb > 0.95 else 'MISSES BRAKING EVENTS'}")
            print(f"armed while NOT braking {leaked} -> "
                  f"{'OK' if leaked == 0 else 'LEAKING, regen gate wrong'}")
            ev = runs_of(braking)
            print(f"distinct braking events {len(ev)}, "
                  f"median {sorted((ec['t'][b]-ec['t'][a]) for a, b in ev)[len(ev)//2]:.2f} s")

        # Did current actually flow INTO the pack?
        ib = resample(vs["t"], vs["I_batt"], ec["t"])
        ich = resample(vs["t"], vs["I_charge"], ec["t"])
        if nb:
            ib_b = [v for v, b in zip(ib, braking) if b]
            ib_d = [v for v, b in zip(ib, braking) if not b]
            print(f"I_batt mean while braking {mean(ib_b):+.4f} A   "
                  f"while driving {mean(ib_d):+.4f} A")
            neg = sum(1 for v in ib_b if v < -0.02)
            print(f"I_batt negative (into pack) during braking: "
                  f"{neg}/{len(ib_b)} ({neg/len(ib_b)*100:.1f}%)")
            print(f"I_charge mean while braking {mean([v for v, b in zip(ich, braking) if b]):+.4f} A")
            if neg / len(ib_b) < 0.2:
                print("  NOTE: regen armed but little current went in. Either the")
                print("  decels are too gentle at this mass, or REGEN_ENABLE is not")
                print("  reaching the hardware. Check charger_status in the plot.")

    # ── 4. FC must never charge the pack ─────────────────────────────────────
    print("\n--- 4. FC charging the pack (must be zero) ---")
    ifc = resample(vs["t"], vs["I_fc"], ec["t"])
    ich2 = resample(vs["t"], vs["I_charge"], ec["t"])
    if dc["t"]:
        viol = sum(1 for p, i, c in zip(pdem, ifc, ich2)
                   if p > 1.0 and c > 0.05 and i > 0.05)
        print(f"samples with I_charge>0.05 A while P_demand>1 W: {viol} -> "
              f"{'OK, FC never charged' if viol == 0 else 'VIOLATION'}")
    print(f"charger_status nonzero: "
          f"{sum(1 for v in vs['charger_status'] if v > 0.5)}/{len(vs['t'])}")

    # ── 5. Share tracking ────────────────────────────────────────────────────
    print("\n--- 5. Power-share tracking ---")
    act = resample(vs["t"], vs["power_share_actual"], ec["t"])
    cmd = ec["power_share_cmd"]
    hyb = [i for i, m in enumerate(modes) if m == 0]
    if len(hyb) < 50:
        print("too few HYBRID samples to assess tracking")
    else:
        err = [act[i] - cmd[i] for i in hyb]
        print(f"HYBRID samples {len(hyb)}   RMS error {rms(err):.4f}   "
              f"bias {mean(err):+.4f}")
        itot = [abs(resample(vs['t'], vs['I_fc'], ec['t'])[i])
                + abs(resample(vs['t'], vs['I_batt'], ec['t'])[i]) for i in hyb]
        gate = sum(1 for v in itot if v > 0.25)
        print(f"I_total mean {mean(itot):.3f} A   above 0.25 A gate "
              f"{gate/len(itot)*100:.1f}%")
        bands = [(0.0, 0.3), (0.3, 0.45), (0.45, 0.6), (0.6, 99)]
        print("  RMS error by I_total band:")
        for lo, hi in bands:
            e = [err[k] for k, v in enumerate(itot) if lo <= v < hi]
            if len(e) > 20:
                print(f"    {lo:.2f}-{hi if hi < 99 else float('inf'):.2f} A  "
                      f"n={len(e):5d}  RMS {rms(e):.4f}")

    # ── 6. Faults and solve time ─────────────────────────────────────────────
    print("\n--- 6. Faults / solver ---")
    ff = [int(round(v)) for v in vs["fault_flags"]]
    nz = [f for f in ff if f]
    latched = [f for f in ff if f & 0x8000]
    print(f"nonzero fault_flags {len(nz)}/{len(ff)}   LATCHED (0x8000) {len(latched)}")
    if nz:
        seen = {}
        for f in nz:
            seen[f] = seen.get(f, 0) + 1
        for f, n in sorted(seen.items(), key=lambda kv: -kv[1])[:6]:
            print(f"    0x{f:04X}  {n}")
    if d["/ems_diagnostics"]["solve_ms"]:
        sm = d["/ems_diagnostics"]["solve_ms"]
        print(f"solve_ms mean {mean(sm):.2f}  max {max(sm):.2f} "
              f"(budget 50 ms at 20 Hz)")


if __name__ == "__main__":
    main()
