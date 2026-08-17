import csv, numpy as np

path = r"C:\Life Ops\School\Thesis\DC-Balancer-Board-Teensy\logs\ML0148\ML0148.csv"
with open(path, newline='') as f:
    r = csv.reader(f)
    header = next(r)
    rows = [row for row in r]

cols = {h:i for i,h in enumerate(header)}
print(header)
data = {}
for h in header:
    try:
        data[h] = np.array([float(row[cols[h]]) for row in rows])
    except Exception as e:
        pass

t = data['t_us'] / 1e6
v_sp = data['v_sp']
v_act = data['v_act']
I_cmd = data['I_cmd']
u_unsat = data.get('u_unsat')
drive_x0 = data.get('drive_x0')

print("N", len(t), "dt approx", np.median(np.diff(t)))
print("t range", t[0], t[-1])

# setpoint profile: find distinct step levels
diffs = np.diff(v_sp)
step_idx = np.where(np.abs(diffs) > 1e-6)[0]
print("num setpoint changes", len(step_idx))
for i in step_idx[:20]:
    print(f"t={t[i+1]:.4f} v_sp {v_sp[i]:.4f}->{v_sp[i+1]:.4f}")

# Find the main step 0->1
mask = v_sp > 0.5
if mask.any():
    i0 = np.argmax(mask)
    t0 = t[i0]
    print("step start t=", t0, "v_sp target", v_sp[i0])
    # find end of high setpoint
    hi_idx = np.where(mask)[0]
    i_end = hi_idx[-1]
    t_end = t[i_end]
    print("step end (v_sp still high) t=", t_end)

    # rise time: 10%-90% of v_act from t0
    sub_t = t[i0:i_end+1]
    sub_v = v_act[i0:i_end+1]
    target = 1.0
    try:
        t10 = sub_t[np.argmax(sub_v>=0.1*target)]
        t90 = sub_t[np.argmax(sub_v>=0.9*target)]
        print("rise time 10-90%:", t90-t10)
    except Exception as e:
        print(e)

    # overshoot
    peak = sub_v.max()
    print("peak v_act", peak, "overshoot %", (peak-target)/target*100)

    # settling time (within 2% of target, staying)
    band = 0.02*target
    within = np.abs(sub_v - target) <= band
    # find first index after which it stays within band till end
    last_out = np.where(~within)[0]
    if len(last_out):
        settle_i = last_out[-1] + 1
        if settle_i < len(sub_t):
            print("settling time (2%) from step start:", sub_t[settle_i]-t0)
        else:
            print("never settles within 2%")
    else:
        print("settles immediately?")

    # steady-state stats over last 5s of the hold (exclude transient first 1.5s)
    ss_mask = (sub_t - t0) > 1.5
    ss_err = sub_v[ss_mask] - target
    print("SS error mean", ss_err.mean(), "std", ss_err.std())

    # gain check: use I_cmd during steady state
    I_ss = I_cmd[i0:i_end+1][ss_mask]
    print("I_cmd steady mean", I_ss.mean(), "std", I_ss.std())

# u_unsat / clamp analysis
if u_unsat is not None:
    sat = np.abs(u_unsat) >= 12.0 - 1e-6
    print("fraction saturated (|u_unsat|>=12A):", sat.mean())
    print("max u_unsat", u_unsat.max(), "min", u_unsat.min())
    # dwell time near clamp during hold
    sat_hold = sat[i0:i_end+1]
    print("saturated fraction during step 0-1 hold:", sat_hold.mean())
    # count crossings of clamp boundary at 12
    cross = np.sum(np.abs(np.diff((u_unsat>=12).astype(int)))>0)
    print("num crossings of +12A boundary:", cross)

if drive_x0 is not None:
    print("drive_x0 range during hold:", drive_x0[i0:i_end+1].min(), drive_x0[i0:i_end+1].max())
    # slope of x0 during steady state (post 1.5s)
    x0_ss = drive_x0[i0:i_end+1][ss_mask]
    t_ss = sub_t[ss_mask]
    if len(t_ss)>2:
        slope = np.polyfit(t_ss, x0_ss, 1)[0]
        print("drive_x0 steady-state slope (per s):", slope)

# limit cycle frequency in v_act during hold (post 1.5s)
if mask.any():
    v_ss = sub_v[ss_mask]
    t_ss2 = sub_t[ss_mask]
    dt = np.median(np.diff(t_ss2))
    v_detrend = v_ss - v_ss.mean()
    # FFT
    n = len(v_detrend)
    freqs = np.fft.rfftfreq(n, dt)
    fft = np.abs(np.fft.rfft(v_detrend))
    top = np.argsort(fft)[-5:][::-1]
    print("dominant freqs (Hz):", [(freqs[k], fft[k]) for k in top if freqs[k]>0.1])
    print("amp (peak-to-peak) of v_act oscillation:", v_ss.max()-v_ss.min())
