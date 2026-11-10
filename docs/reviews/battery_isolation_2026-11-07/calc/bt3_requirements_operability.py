"""Battle-test round 3, requirements and operability lens. Stdlib only.
Input: BLG CSVs decoded by tools/decode_benchlog.py (path in argv[1], default $TEMP/bt3).
Section A: I_cmd at the regen events that the design's HR1 evidence uses (calc/bt2_requirements_operability.py B),
           against the OR-V' arm (I_cmd <= -2 A on two consecutive 1 kHz ticks, design 9.5).
V_rgn in the BLG reads 0.85 x true (fw36 review README item 6); the true V-MOT = V_rgn / 0.85."""
import csv, os, sys
d = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.environ.get("TEMP", "."), "bt3")
EVENTS = [("ML0151", 41.36), ("ML0157", 47.30), ("ML0165", 22.64), ("ML0165", 28.55), ("ML0195", 33.20),
          ("YP0166", 21.97), ("YP0196", 21.97)]
K = 0.85
def load(f):
    rows = []
    with open(os.path.join(d, f + ".csv")) as fh:
        for r in csv.DictReader(fh):
            try:
                rows.append((int(r["t_us"]), float(r["I_cmd"]), float(r["V_rgn"]) / K, float(r["v_act"]),
                             float(r["v_sp"]), float(r["V_bus"])))
            except ValueError:
                pass
    t0 = rows[0][0]
    return [((t - t0) / 1e6, i, v, va, vs, vb) for (t, i, v, va, vs, vb) in rows]
cache = {}
print("A. I_cmd at the HR1 evidence events (window -0.30 .. +0.60 s around the listed time)")
for f, tev in EVENTS:
    if f not in cache:
        cache[f] = load(f)
    w = [r for r in cache[f] if tev - 0.30 <= r[0] <= tev + 0.60]
    if not w:
        print(f"  {f} {tev}: no rows"); continue
    vmax = max(w, key=lambda r: r[2])
    vb = sum(r[5] for r in w[:20]) / 20
    onset = next((r for r in w if r[2] > vb + 1.0), None)
    imin = min(r[1] for r in w)
    # first two consecutive samples <= -2 A
    arm = None
    for a, b in zip(w, w[1:]):
        if a[1] <= -2.0 and b[1] <= -2.0:
            arm = b; break
    neg = next((r for r in w if r[1] < -0.1), None)
    def fmt(r): return "none" if r is None else f"{r[0]:.4f} s"
    print(f"  {f} {tev:6.2f}: V-MOT(true) peak {vmax[2]:5.2f} V at {vmax[0]:.4f} s; onset(+1 V) {fmt(onset)}; "
          f"I_cmd min {imin:6.2f} A; first I_cmd<-0.1 {fmt(neg)}; OR-V' arm {fmt(arm)}; "
          f"v_sp {w[0][4]:.2f}->{w[-1][4]:.2f} m/s; dt arm-onset "
          f"{'n/a' if (arm is None or onset is None) else f'{(arm[0]-onset[0])*1e3:+.1f} ms'}")

# ---------------------------------------------------------------------------------------------
# Section B: fw v37 drive law (teensy_controller/drive_controller_coeffs.h, fw v37 commit db59fb7)
# open-loop response to a held velocity-error step (vehicle speed frozen = fastest possible
# command build-up; the real plant reduces |e| and slows it further). Time for i_cmd to reach -2 A.
import re
def load_hdr(path):
    s = open(path).read()
    def arr(name):
        m = re.search(name + r"\s*\[[^\]]*\](?:\s*\[[^\]]*\])?\s*=\s*\{(.*?)\};", s, re.S)
        return [float(v.rstrip('f')) for v in re.findall(r"[-+]?\d\.\d+e[-+]\d+f?", m.group(1))]
    AD = arr("DRIVE_CTRL_AD"); BD = arr("DRIVE_CTRL_BD"); CD = arr("DRIVE_CTRL_CD")
    DD = float(re.search(r"DRIVE_CTRL_DD\s*=\s*([-+0-9.e]+)f", s).group(1))
    n = 5
    return [AD[i*n:(i+1)*n] for i in range(n)], BD, CD, DD
here = os.path.dirname(os.path.abspath(__file__))
hdr = os.path.join(here, "..", "..", "..", "..", "teensy_controller", "drive_controller_coeffs.h")
AD, BD, CD, DD = load_hdr(hdr)
print("\nB. fw v37 drive law, held error step (2 ms ticks, vehicle speed frozen): time to i_cmd <= -2 A")
for e in (-0.1, -0.2, -0.3, -0.5, -1.0):
    x = [0.0]*5; t_hit = None; u = 0.0
    for k in range(200):
        u = sum(CD[j]*x[j] for j in range(5)) + DD*e
        u = max(-12.0, min(12.0, u))
        if u <= -2.0 and t_hit is None:
            t_hit = k*2.0
        x = [sum(AD[i][j]*x[j] for j in range(5)) + BD[i]*e for i in range(5)]
    u10 = None
    print(f"  e = {e:+.2f} m/s: i_cmd at t=0 {DD*e:+.3f} A; reaches -2 A at "
          f"{'never in 400 ms' if t_hit is None else f'{t_hit:.0f} ms'}")

# ---------------------------------------------------------------------------------------------
# Section C: regen-window entry precondition "I_PACK1 discharge below 1.5 A" and "estimated I_L <= 0.75 A"
# (design 9.5) evaluated at the OR-V' arm tick of each HR1 evidence event. I_PACK1 is not in the BLG;
# it is estimated with the design's own formula (9.3 step 5): BT_CURRENT x V_bus / (0.95 x V_batt).
# The BLG column I_batt is BT_CURRENT (ino:7026). LM1084 input current is excluded (lower bound).
def load2(f):
    rows = []
    with open(os.path.join(d, f + ".csv")) as fh:
        t0 = None
        for r in csv.DictReader(fh):
            try:
                t = int(r["t_us"]); t0 = t0 if t0 is not None else t
                rows.append(((t - t0) / 1e6, float(r["I_cmd"]), float(r["I_batt"]), float(r["V_bus"]),
                             float(r["V_batt"]), float(r["I_fc"])))
            except ValueError:
                pass
    return rows
print("\nC. Pack discharge estimate at the OR-V' arm tick (entry needs < 1.5 A; I_L hold <= 0.75 A)")
c2 = {}
for f, tev in EVENTS:
    if f not in c2:
        c2[f] = load2(f)
    w = [r for r in c2[f] if tev - 0.30 <= r[0] <= tev + 0.60]
    arm = None
    for a, b in zip(w, w[1:]):
        if a[1] <= -2.0 and b[1] <= -2.0:
            arm = b; break
    pre = [r for r in w if r[0] < (arm[0] if arm else tev) - 0.005][-50:]
    ib_pre = sum(r[2] for r in pre) / max(len(pre), 1)
    after = [r for r in w if arm and arm[0] <= r[0] <= arm[0] + 0.010]
    def pk(r): return r[2] * r[3] / (0.95 * r[4]) if r[4] > 1 else float('nan')
    ip_arm = pk(arm) if arm else float('nan')
    ip_max10 = max((pk(r) for r in after), default=float('nan'))
    print(f"  {f} {tev:6.2f}: BT_CURRENT pre-brake {ib_pre:5.2f} A, at arm {arm[2] if arm else float('nan'):5.2f} A; "
          f"V_batt {arm[4] if arm else float('nan'):.2f} V; pack discharge est at arm {ip_arm:4.2f} A, max in next 10 ms {ip_max10:4.2f} A; "
          f"I_L est (BT x Vbus/(0.88 Vbatt)) {arm[2]*arm[3]/(0.88*arm[4]) if arm else float('nan'):4.2f} A")
