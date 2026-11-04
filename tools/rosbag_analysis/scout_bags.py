#!/usr/bin/env python3
"""
scout_bags.py - one-command inventory and quick stats for the Pi rosbags.

The rosbag counterpart of tools/benchlog_analysis/scout_batch.py. For each bag
it reads the .mcap once, writes a cached numpy archive next to nothing in the
repo (the cache goes to --cache, default a temp dir), and prints one table row:
duration, message counts and rates per topic, /vehicle_state width, the
charge_goal / mode / v_setpoint ranges, the switch-state bit occupancy, regen
statistics (REGEN_ENABLE ticks, I_charge, V_rgn and V_chg while regen is open),
faults and latched error codes.

Usage:
    python3 scout_bags.py ../../logs/rosbags/rosbag_*          # table
    python3 scout_bags.py BAG --cache /tmp/x --npz             # also write BAG.npz
    python3 scout_bags.py BAG --json                           # machine-readable

Load a cached archive in an analysis script:
    d = np.load("<cache>/<bag>.npz")
    t, vs = d["vs_t"], d["vs"]          # vs[:, VS.index("V_rgn")]
    t_ec, ec = d["ec_t"], d["ec"]       # ec[:, EC.index("charge_goal")]

Times are seconds from the first message of ANY topic in the bag (log_time,
i.e. Pi receive time - not Teensy time; the Teensy timestamp is not
republished). Dependencies: mcap, mcap-ros2-support, numpy.
"""

import argparse
import glob
import json
import os
import sys
import tempfile

import numpy as np

try:
    from mcap_ros2.reader import read_ros2_messages
except ImportError:
    sys.exit("pip install mcap mcap-ros2-support")

# /vehicle_state, 18 elements (bridge 2026-08-17A onward; 2026-10-31A docstring).
VS = ["v_actual", "V_batt", "I_batt", "I_charge", "V_fc", "I_fc", "V_bus",
      "V_rgn", "V_chg", "power_share_actual", "droop_FC", "droop_BT",
      "charger_status", "switch_state", "fault_flags", "error_code",
      "error_source_state", "SOC"]
# /ems_command, first 5 elements (bridge _cb_ems_command).
EC = ["v_setpoint", "power_share_cmd", "charge_goal", "mode", "droop_enable"]

SW = [(0x01, "FC_BUS"), (0x02, "BT_BUS"), (0x04, "MOT_PWR"),
      (0x08, "REGEN"), (0x10, "FC_CHG"), (0x20, "BT_SEQ")]


def find_mcap(p):
    if os.path.isfile(p) and p.endswith(".mcap"):
        return p
    hits = glob.glob(os.path.join(p, "*.mcap"))
    if len(hits) != 1:
        raise SystemExit(f"{p}: expected one .mcap, found {len(hits)}")
    return hits[0]


def load_bag(path):
    """Return dict: vs_t, vs (N x 18), ec_t, ec (M x 5), other topics as lists."""
    vs_t, vs, ec_t, ec = [], [], [], []
    other = {}
    widths = {}
    t0 = None
    for m in read_ros2_messages(find_mcap(path)):
        top = m.channel.topic
        ts = m.log_time_ns / 1e9
        if t0 is None:
            t0 = ts
        try:
            d = [float(x) for x in m.ros_msg.data]
        except (AttributeError, TypeError):
            d = None
        if d is not None:
            widths.setdefault(top, set()).add(len(d))
        if top == "/vehicle_state" and d is not None and len(d) >= len(VS):
            vs_t.append(ts - t0); vs.append(d[:len(VS)])
        elif top == "/ems_command" and d is not None and len(d) >= len(EC):
            ec_t.append(ts - t0); ec.append(d[:len(EC)])
        else:
            other.setdefault(top, []).append((ts - t0, d))
    return dict(vs_t=np.array(vs_t), vs=np.array(vs).reshape(-1, len(VS)),
                ec_t=np.array(ec_t), ec=np.array(ec).reshape(-1, len(EC)),
                other=other, widths={k: sorted(v) for k, v in widths.items()})


def rate(t):
    return (len(t) - 1) / (t[-1] - t[0]) if len(t) > 1 else 0.0


def scout(path):
    b = load_bag(path)
    vt, vs, et, ec = b["vs_t"], b["vs"], b["ec_t"], b["ec"]
    col = lambda n: vs[:, VS.index(n)]
    r = dict(bag=os.path.basename(os.path.normpath(path)),
             widths={k: v for k, v in b["widths"].items()},
             n_vs=len(vt), n_ec=len(et),
             other_counts={k: len(v) for k, v in b["other"].items()})
    if len(vt) == 0:
        return r, b
    sw = col("switch_state").astype(int)
    r["dur_s"] = float(vt[-1] - vt[0])
    r["vs_hz"] = rate(vt)
    r["ec_hz"] = rate(et)
    r["max_gap_ms"] = float(np.max(np.diff(vt)) * 1e3) if len(vt) > 1 else 0.0
    r["sw_occ"] = {n: float(np.mean((sw & bit) != 0)) for bit, n in SW}
    reg = (sw & 0x08) != 0
    r["regen_ticks"] = int(reg.sum())
    # regen episodes = rising edges of the REGEN bit
    r["regen_episodes"] = int(np.sum(np.diff(reg.astype(int)) == 1) + (1 if reg[0] else 0))
    ich = col("I_charge")
    r["I_charge_max"] = float(np.max(ich))
    r["I_charge_gt0.05_ticks"] = int(np.sum(ich > 0.05))
    r["I_charge_max_regen"] = float(np.max(ich[reg])) if reg.any() else None
    r["V_rgn_max"] = float(np.max(col("V_rgn")))
    r["V_rgn_max_regen"] = float(np.max(col("V_rgn")[reg])) if reg.any() else None
    r["V_chg_max_regen"] = float(np.max(col("V_chg")[reg])) if reg.any() else None
    r["chg_status_values"] = sorted({int(x) for x in col("charger_status")})[:16]
    r["v_act_max"] = float(np.max(col("v_actual")))
    r["v_act_min"] = float(np.min(col("v_actual")))
    r["V_bus_min"] = float(np.min(col("V_bus")))
    r["V_batt_range"] = [float(np.min(col("V_batt"))), float(np.max(col("V_batt")))]
    r["I_fc_max"] = float(np.max(col("I_fc")))
    r["I_batt_max"] = float(np.max(col("I_batt")))
    r["fault_flags_or"] = int(np.bitwise_or.reduce(col("fault_flags").astype(int)))
    ecode = col("error_code").astype(int)
    r["error_codes"] = sorted({int(x) for x in ecode if x})
    if ecode.any():
        i = int(np.argmax(ecode != 0))
        r["first_error_t"] = float(vt[i])
        r["first_error_src"] = int(col("error_source_state")[i])
    if len(et):
        g = ec[:, EC.index("charge_goal")]
        r["charge_goal_range"] = [float(g.min()), float(g.max())]
        r["charge_goal_frac_gt0.05"] = float(np.mean(g > 0.05))
        r["modes"] = sorted({int(x) for x in ec[:, EC.index("mode")]})
        r["v_sp_range"] = [float(ec[:, 0].min()), float(ec[:, 0].max())]
        r["share_cmd_range"] = [float(ec[:, 1].min()), float(ec[:, 1].max())]
    return r, b


def row(r):
    if not r.get("n_vs"):
        return f"{r['bag']:<42} NO /vehicle_state  widths={r['widths']}"
    reg = r["regen_ticks"]
    return (f"{r['bag']:<42} {r['dur_s']:6.0f}s vs={r['n_vs']:5d}@{r['vs_hz']:4.1f}Hz "
            f"gap={r['max_gap_ms']:5.0f}ms cg={r.get('charge_goal_range', '-')} "
            f"vmax={r['v_act_max']:.2f} Vbus_min={r['V_bus_min']:.2f} "
            f"REGEN={reg}/{r['regen_episodes']}ep Ichg_max={r['I_charge_max']:.3f} "
            f"Vrgn_max={r['V_rgn_max']:.2f} err={r['error_codes']} flt=0x{r['fault_flags_or']:04x}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bags", nargs="+")
    ap.add_argument("--cache", default=os.path.join(tempfile.gettempdir(), "rosbag_cache"))
    ap.add_argument("--npz", action="store_true", help="write <cache>/<bag>.npz")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    out = []
    for p in a.bags:
        if not os.path.isdir(p) and not p.endswith(".mcap"):
            continue
        if os.path.isdir(p) and not glob.glob(os.path.join(p, "*.mcap")):
            continue
        r, b = scout(p)
        out.append(r)
        if a.npz:
            os.makedirs(a.cache, exist_ok=True)
            np.savez_compressed(os.path.join(a.cache, r["bag"] + ".npz"),
                                vs_t=b["vs_t"], vs=b["vs"], ec_t=b["ec_t"], ec=b["ec"],
                                VS=np.array(VS), EC=np.array(EC))
        if not a.json:
            print(row(r), flush=True)
    if a.json:
        print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
