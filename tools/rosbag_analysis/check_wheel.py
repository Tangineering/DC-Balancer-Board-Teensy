"""
check_wheel.py — is the ~4 Hz current oscillation locked to wheel rotation?

    python3 check_wheel.py ../Logs/rosbag_sweep_2026-10-20_09-08-49 [wheel_radius_m]

Test 1: does the peak frequency track vehicle speed?
        f_wheel = v / (2*pi*r).  Constant f/v  =>  once-per-revolution.
Test 2: are I_fc and I_batt in phase or antiphase at that frequency?
        in phase  -> TOTAL current oscillates -> load / mechanical / speed loop
        antiphase -> SHARE oscillates         -> the droop/share loop is limit-cycling
Test 3: does v_actual itself show the same peak?  (points at the encoder)
"""
import csv, sys, math

BAG = sys.argv[1] if len(sys.argv) > 1 else '../Logs/rosbag_sweep_2026-10-20_09-08-49'
R   = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0762

try:
    import numpy as np
except ImportError:
    sys.exit("needs numpy:  python3 -m pip install --break-system-packages numpy")

r = list(csv.DictReader(open(BAG + '/csv/vehicle_state.csv')))
t   = np.array([float(x['t_s'])     for x in r])
ifc = np.array([float(x['I_fc'])    for x in r])
ibt = np.array([float(x['I_batt'])  for x in r])
v   = np.array([float(x['v_actual']) for x in r])

m = t > 60.0
t, ifc, ibt, v = t[m], ifc[m], ibt[m], v[m]
dt = float(np.median(np.diff(t)))
circ = 2 * math.pi * R
print(f"\n{BAG.split('/')[-1]}   {len(t)} loaded samples, fs = {1/dt:.1f} Hz")
print(f"  wheel radius {R:.4f} m -> circumference {circ:.4f} m -> {1/circ:.3f} rev per metre")

def resid(x, win=15):
    sm = np.convolve(x, np.ones(win)/win, mode='same')
    e = win//2
    return (x - sm)[e:-e], e

def peak_freq(x):
    x = x - x.mean()
    if len(x) < 64: return float('nan'), 0.0
    w = np.hanning(len(x))
    P = np.abs(np.fft.rfft(x*w)); f = np.fft.rfftfreq(len(x), dt)
    sel = (f > 1.0) & (f < 20.0)          # ignore DC drift and HF
    if not sel.any(): return float('nan'), 0.0
    i = np.argmax(P[sel])
    return float(f[sel][i]), float(P[sel][i])

# ---- Test 1: frequency vs speed, in windows ------------------------------
print("\nTEST 1 — does peak frequency track speed?")
print(f"  {'window':>8}{'mean v':>9}{'f_peak':>9}{'f/v':>9}{'predicted':>11}")
W = int(8.0/dt)                                  # 8 s windows
ratios = []
for k in range(0, len(t)-W, W):
    sl = slice(k, k+W)
    vv = float(v[sl].mean())
    if vv < 0.5: continue
    rr, _ = resid(ifc[sl])
    fp, _ = peak_freq(rr)
    if fp != fp: continue
    ratios.append(fp/vv)
    print(f"  {t[k]:7.0f}s{vv:9.2f}{fp:9.2f}{fp/vv:9.2f}{vv/circ:11.2f}")
if ratios:
    arr = np.array(ratios)
    print(f"\n  f/v  mean {arr.mean():.2f}  sd {arr.std():.2f}   "
          f"predicted {1/circ:.2f} for once-per-rev")
    verdict = ("LOCKED to wheel rotation" if abs(arr.mean() - 1/circ) < 0.25*(1/circ)
               and arr.std() < 0.3*arr.mean() else "NOT a clean wheel lock")
    print(f"  -> {verdict}")

# ---- Test 2: phase between the two channels ------------------------------
ra, e = resid(ifc); rb, _ = resid(ibt)
n = min(len(ra), len(rb))
c = float(np.corrcoef(ra[:n], rb[:n])[0,1])
print(f"\nTEST 2 — I_fc vs I_batt residual correlation = {c:+.3f}")
if c > 0.3:
    print("  -> IN PHASE: total current oscillates. Load / mechanical / speed-loop origin.")
elif c < -0.3:
    print("  -> ANTIPHASE: the SHARE oscillates at constant total. Droop/share loop limit cycle.")
else:
    print("  -> uncorrelated: independent noise on each channel (measurement-side).")

# ---- Test 3: does the speed signal itself carry it? ----------------------
rv, _ = resid(v)
fv, av = peak_freq(rv)
fi, ai = peak_freq(ra)
print(f"\nTEST 3 — v_actual residual: peak {fv:.2f} Hz, amplitude {av/len(rv)*2:.5f} m/s")
print(f"         I_fc     residual: peak {fi:.2f} Hz")
if fv == fv and fi == fi and abs(fv - fi) < 0.5:
    print("  -> SAME frequency in the speed signal. Encoder or drivetrain is the prime suspect.")
else:
    print("  -> speed signal does NOT share the peak; the oscillation is downstream of it.")
