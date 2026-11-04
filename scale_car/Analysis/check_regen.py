#!/usr/bin/env python3
"""
check_regen.py — did the regen path ever actually open?

Decodes switch_state from /vehicle_state and answers, from data you already have,
the question the plots cannot: was REGEN_ENABLE ever driven HIGH?

The firmware raises it only inside `if (regenActive)`, and
`regenActive = (current < -0.1f)` where `current` is the VESC *commanded* motor
current. So:

  charge_goal = 1 and SW_REGEN never set  ->  the VESC never commanded braking
                                              current. That is a VESC config
                                              question (brake current limit),
                                              not a firmware or Pi question.

  SW_REGEN set but I_charge stays 0        ->  the path opened and the charger
                                              did not accept it. Downstream of
                                              the firmware.

Usage:
    python3 check_regen.py ../Logs/rosbag_sdp_2026-10-27_00-52-58
"""

import glob
import os
import sys

try:
    from mcap_ros2.reader import read_ros2_messages
except ImportError:
    sys.exit("pip install mcap mcap-ros2-support")

SW = [(0x01, "FC_BUS"), (0x02, "BT_BUS"), (0x04, "MOT_PWR"),
      (0x08, "REGEN"), (0x10, "FC_CHARGE"), (0x20, "BT_SEQ")]
SW_REGEN, SW_FC_CHARGE = 0x08, 0x10

VS = ["v_actual", "V_batt", "I_batt", "I_charge", "V_fc", "I_fc", "V_bus",
      "V_rgn", "V_chg", "power_share_actual", "droop_FC", "droop_BT",
      "charger_status", "switch_state", "fault_flags", "error_code",
      "error_source_state", "SOC"]
EC = ["v_setpoint", "power_share_cmd", "charge_goal", "mode", "droop_enable"]


def find_mcap(p):
    if os.path.isfile(p) and p.endswith(".mcap"):
        return p
    if os.path.isdir(p):
        h = glob.glob(os.path.join(p, "*.mcap"))
        if len(h) == 1:
            return h[0]
        sys.exit(f"Expected one .mcap in {p}, found {len(h)}")
    sys.exit(f"Not found: {p}")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    bag = sys.argv[1]
    vs = {k: [] for k in ["t"] + VS}
    ec = {k: [] for k in ["t"] + EC}
    t0 = None
    for m in read_ros2_messages(find_mcap(bag)):
        top = m.channel.topic
        if top not in ("/vehicle_state", "/ems_command"):
            continue
        ts = m.log_time_ns / 1e9
        if t0 is None:
            t0 = ts
        d = list(m.ros_msg.data)
        tgt, fs = (vs, VS) if top == "/vehicle_state" else (ec, EC)
        if len(d) < len(fs):
            continue
        tgt["t"].append(ts - t0)
        for i, f in enumerate(fs):
            tgt[f].append(float(d[i]))

    if not vs["t"]:
        sys.exit("No /vehicle_state in this bag.")
    n = len(vs["t"])
    sw = [int(round(v)) for v in vs["switch_state"]]

    print(f"bag       {os.path.basename(bag.rstrip('/'))}")
    print(f"samples   {n}   duration {vs['t'][-1]:.1f} s")

    print("\n--- switch_state occupancy ---")
    for bit, name in SW:
        c = sum(1 for v in sw if v & bit)
        print(f"  {name:10s} HIGH {c:6d}/{n}  ({c/n*100:5.1f}%)")

    print("\n--- distinct switch_state words ---")
    seen = {}
    for v in sw:
        seen[v] = seen.get(v, 0) + 1
    for v, c in sorted(seen.items(), key=lambda kv: -kv[1])[:8]:
        names = "|".join(nm for b, nm in SW if v & b) or "none"
        print(f"  0x{v:02X}  {c:6d}  {names}")

    regen_n = sum(1 for v in sw if v & SW_REGEN)
    fcchg_n = sum(1 for v in sw if v & SW_FC_CHARGE)

    print("\n--- VERDICT ---")
    print(f"  FC_CHARGE_ENABLE HIGH: {fcchg_n}  -> "
          f"{'OK, FC never routed to the pack' if fcchg_n == 0 else 'FC WAS ROUTED TO THE PACK'}")

    if not ec["t"]:
        print("  no /ems_command — cannot cross-check charge_goal")
    else:
        cg = sum(1 for v in ec["charge_goal"] if v > 0.05)
        print(f"  charge_goal > 0.05:    {cg}/{len(ec['t'])} samples")
        if regen_n == 0 and cg > 0:
            print("  REGEN_ENABLE HIGH:     0")
            print()
            print("  => The Pi asked for regen and the firmware never opened the path.")
            print("     regenActive is (commanded motor current < -0.1 A), so the VESC")
            print("     never commanded braking current. CHECK THE VESC BRAKE CURRENT")
            print("     LIMIT (Motor Settings -> Current -> Motor Current Max Brake and")
            print("     Battery Current Max Regen). Nothing in the firmware or the Pi")
            print("     can produce charging until that is nonzero.")
        elif regen_n > 0:
            print(f"  REGEN_ENABLE HIGH:     {regen_n} ({regen_n/n*100:.1f}%)")
            ich = [v for v, s in zip(vs["I_charge"], sw) if s & SW_REGEN]
            vrg = [v for v, s in zip(vs["V_rgn"], sw) if s & SW_REGEN]
            ib = [v for v, s in zip(vs["I_batt"], sw) if s & SW_REGEN]
            mx = max(ich) if ich else 0.0
            print(f"  while REGEN high: I_charge max {mx:.4f} A, "
                  f"V_rgn max {max(vrg) if vrg else 0:.2f} V, "
                  f"I_batt min {min(ib) if ib else 0:+.4f} A")
            print()
            if mx > 0.05:
                print("  => REGEN WORKED. Current flowed into the pack.")
            else:
                print("  => The path opened but no charge current flowed. The VESC IS")
                print("     braking (that is what raised the pin), so this is downstream:")
                print("     the Ag105 is not accepting the regen input. Check V_rgn above")
                print("     against the charger's minimum input voltage, and charger_status.")
        else:
            print("  REGEN_ENABLE HIGH:     0, and charge_goal was never raised either")
            print("  => No braking was commanded in this run at all. Check the drive")
            print("     cycle actually contains decelerations.")

    print(f"\n  charger_status nonzero: {sum(1 for v in vs['charger_status'] if v > 0.5)}/{n}")
    print(f"  I_charge   max {max(vs['I_charge']):.4f} A")
    print(f"  V_rgn      max {max(vs['V_rgn']):.2f} V")
    print(f"  I_batt     min {min(vs['I_batt']):+.4f} A  (negative = into pack)")


if __name__ == "__main__":
    main()
