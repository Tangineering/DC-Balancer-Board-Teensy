"""Battle-test round 1, requirements/operability lens, IC1 detailed design revision 3.

Stdlib only. Every input is cited inline; nothing here is a new measurement.
Run: python bt1_requirements_operability.py  (from this directory or with an absolute path)
"""
import csv
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
DC = os.path.join(REPO, "references", "drive_cycles")


def hdr(t):
    print("\n" + "=" * 78 + "\n" + t + "\n" + "=" * 78)


# ---------------------------------------------------------------------------
hdr("A. Regen pulse: hardware chain latency against the V-MOT rise (design sec 7.8, Table 11)")
# V-MOT 15.9 -> 21.35 V in 19-47 ms, onset ~5 ms after I_cmd < 0 (facts_prior sec 6; EVAL 3.1)
V0, VPK = 15.9, 21.35
ASSERT = (16.90, 17.24)          # design Table 9, VBUS 16.0 V worst case
T_DON = 8.0                      # RT1987 t_D_ON typical, no maximum (design Table 11)
T_EF = 1.24 + 3.6                # eFuse UVLO turn-on delay + 0 -> 18 V ramp (design 7.5, calc sec 5)
CHAIN = T_DON + T_EF
print(f"chain VOK assert -> Ag105 input at 18 V: {CHAIN:.2f} ms (typical; t_D_ON has no max)")
for tr in (19.0, 47.0):
    for a in ASSERT:
        t_to_peak = tr * (VPK - a) / (VPK - V0)
        print(f"  rise {tr:4.0f} ms, assert {a:.2f} V: assert->peak {t_to_peak:5.1f} ms; "
              f"budget left for Ag105 start + tau {t_to_peak - CHAIN:+6.1f} ms")
print("  EVAL 3.2 requirement: tau_warm <= 2 ms (board C) / <= 4 ms (0.97 mF); design S0-6 GO uses 'about 15 ms'")

# ---------------------------------------------------------------------------
hdr("B. Regen energy captured per pulse with a cold start (design sec 7.8: every pulse starts cold)")
VTH = 18.0                       # Ag105 regen-profile threshold, DS p.10 default (design Table 5)
DECAY = (14.0, 20.0)             # V/s post-trip decay (facts_prior sec 6)
COLD = (65.0, 170.0)             # ms cold start (facts_prior sec 6, [REGEN] 0 item 6)
ETA = 0.88                       # Ag105 DS p.20 (12 V in, 3S only)
E_AVAIL_31 = 6.32                # J at V-MOT, 3 -> 1 m/s, 12 A (EVAL 3.2)
Q_AVAIL_31 = 0.661               # C into pack (EVAL 3.2)
for C_mF in (0.48, 0.97, 4.0):
    C = C_mF * 1e-3
    e_node = 0.5 * C * (VPK ** 2 - VTH ** 2)
    rows = []
    for ts in COLD:
        for d in DECAY:
            # Ag105 input arrives ~ at the peak at best (sec A: budget ~ 0..23 ms); start ts after that
            v_start = VPK - d * ts / 1000.0
            e = 0.5 * C * max(v_start ** 2 - VTH ** 2, 0.0)
            rows.append(e)
    lo, hi = min(rows), max(rows)
    # pulses per 3 -> 1 m/s decel: braking 0.58 s, re-pulse every 0.535 s -> 2 pulses
    print(f"  C {C_mF:4.2f} mF: node energy above 18 V {e_node*1e3:6.1f} mJ; harvested per pulse {lo*1e3:5.1f}-{hi*1e3:6.1f} mJ; "
          f"2 pulses -> {2*lo*1e3:5.1f}-{2*hi*1e3:6.1f} mJ = {200*lo/E_AVAIL_31:4.2f}-{200*hi/E_AVAIL_31:4.2f} % of 6.32 J; "
          f"into pack {2*lo*ETA/8.0*1e3:4.1f}-{2*hi*ETA/8.0*1e3:5.1f} mC vs 661 mC")

# ---------------------------------------------------------------------------
hdr("C. HR1 23 W against the design's own regen entry gate V_batt < 8.0 V (design sec 9.5)")
for v in (7.4, 7.8, 8.0):
    print(f"  V_pack {v:.1f} V: regen profile (I_o 2.35 A) P_in {2.35*v/ETA:5.2f} W; module ceiling 2.5 A {2.5*v/ETA:5.2f} W")
print(f"  23 W needs V_pack >= {23*ETA/2.5:.2f} V at 2.5 A; the entry gate admits only V_batt < 8.0 V -> 23 W unreachable in any window")

# ---------------------------------------------------------------------------
hdr("D. FC window charge per H-20 purge cycle at standstill (design sec 9.7)")
T_PURGE, D_PURGE = 10.34, 0.14   # facts_prior sec 7
GUARD = 0.30 + 0.30              # assumed pre/post guard (prediction +/-20 ms/edge, BT_BUS re-close t_D_ON no max) - ASSUMPTION
I_SET = 1.25
for label, ts in (("cold start 0.065 s", 0.065), ("cold start 0.17 s", 0.17),
                  ("Bring-Up into open VCHG, 2 -> 7.4 V at 0.64 V/s (no R_KA, ruling 9)", (7.4 - 2.0) / 0.64),
                  ("Bring-Up into open VCHG, 2 -> 8.4 V at 0.64 V/s", (8.4 - 2.0) / 0.64)):
    t_chg = max(T_PURGE - D_PURGE - GUARD - ts, 0.0)
    q = I_SET * t_chg
    iavg = q / T_PURGE
    h = 0.9 * 5.0 / iavg if iavg > 0 else float("inf")
    print(f"  {label}: start {ts:5.2f} s, charging {t_chg:5.2f} s/cycle, {q:5.2f} C/cycle, mean {iavg:5.3f} A, "
          f"~{h:5.1f} h for 90 % of a 5 Ah pack (capacity UNVERIFIED)")
print("  With fw v33b in force (ino:15483-15500), fcUvLockoutActive() re-arms on every purge (UV_FC_PURGE_LOCKOUT_MS 30 s")
print("  > 10.34 s interval): on a running H-20 every window is refused -> 0 C/cycle.")

# ---------------------------------------------------------------------------
hdr("E. Drive-cycle fractions: standstill time and true braking time")


def load(fn):
    t, v = [], []
    with open(os.path.join(DC, fn), newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            t.append(float(row["time_s"]))
            v.append(float(row["v_mps"]))
    return t, v


def a_coast(v):
    # rig coast-down: 2.00 N + 0.534 v over 3.5 kg (docs/reviews/fw36_regen_2026-11-04/README.md line 25)
    return (2.00 + 0.534 * v) / 3.5


for fn in ("UDDS_trimmed_3.5mps.csv", "UDDS_trimmed_to_idle.csv", "RegenTest_decel_sweep.csv",
           "RegenTest_v2_lowspeed.csv"):
    t, v = load(fn)
    T = t[-1] - t[0]
    still = brake = 0.0
    n_ev = 0
    in_ev = False
    for i in range(len(t) - 1):
        dt = t[i + 1] - t[i]
        vm = 0.5 * (v[i] + v[i + 1])
        acc = (v[i + 1] - v[i]) / dt
        if v[i] == 0.0 and v[i + 1] == 0.0:
            still += dt
        b = vm > 0.0 and -acc > a_coast(vm)
        if b:
            brake += dt
            if not in_ev:
                n_ev += 1
        in_ev = b
    print(f"  {fn:28s}: {T:7.1f} s; standstill {100*still/T:5.1f} %; decel steeper than coast-down "
          f"{100*brake/T:5.2f} % in {n_ev} events")

# ---------------------------------------------------------------------------
hdr("F. Self-test step 7 charge-mode exposure (design sec 9.3)")
print("  Step 7 holds FF1 set until the pump clears it: 43-76 ms (calc sec 4), limit 90 ms,")
print("  against the design's statement 'at most about 2 ms per step'. Idle pack discharge (Teensy + aux, BT_BUS closed)")
print("  then runs reverse through the Ag105 sense for up to 90 ms at every Idle entry.")

# ---------------------------------------------------------------------------
hdr("G. UDDS stop durations (FC window candidates if State-2 standstill windows were allowed)")
t, v = load("UDDS_trimmed_3.5mps.csv")
stops, cur = [], 0.0
for i in range(len(t) - 1):
    if v[i] == 0.0 and v[i + 1] == 0.0:
        cur += t[i + 1] - t[i]
    elif cur > 0:
        stops.append(cur)
        cur = 0.0
if cur > 0:
    stops.append(cur)
print(f"  stops: {len(stops)}; durations (s): {sorted(stops)}")
usable = sum(max(s - 0.6 - 0.17, 0.0) for s in stops)
print(f"  charge time if every stop were a window (0.6 s guards, 0.17 s start): {usable:.1f} s of {t[-1]-t[0]:.0f} s "
      f"-> {I_SET*usable:.1f} C per cycle (purge synchronisation ignored)")
