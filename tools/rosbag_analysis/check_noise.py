import csv, sys, statistics as st

BAG = sys.argv[1] if len(sys.argv) > 1 else '../../logs/rosbags/rosbag_sweep_2026-10-20_09-08-49'
LSB = 0.00806          # 8.06 mA/count, SCALE_I at 12-bit / Vref 3.3 / K_sns 0.1
TAUS = [20.0, 60.0, 100.0]

r = list(csv.DictReader(open(BAG + '/csv/vehicle_state.csv')))
t    = [float(x['t_s'])     for x in r]
ifc  = [float(x['I_fc'])    for x in r]
ibt  = [float(x['I_batt'])  for x in r]
vfc  = [float(x['V_fc'])    for x in r]
vbt  = [float(x['V_batt'])  for x in r]
vbus = [float(x['V_bus'])   for x in r]
shr  = [float(x['power_share_actual']) for x in r]

def sigma(v):
    """White-noise sigma: successive differences high-pass the smooth signal."""
    if len(v) < 3: return float('nan')
    d = [v[i+1]-v[i] for i in range(len(v)-1)]
    return st.pstdev(d) / (2**0.5)

def ema(times, v, tau_ms):
    out = [v[0]]
    for i in range(1, len(v)):
        dt = max(1e-6, (times[i]-times[i-1])*1000.0)
        a = dt/(tau_ms+dt)
        out.append(out[-1] + a*(v[i]-out[-1]))
    return out

idle = [i for i,x in enumerate(t) if x < 50]
load = [i for i,x in enumerate(t) if x > 60]

print(f"\n{BAG.split('/')[-1]}   {len(r)} samples, {t[-1]:.1f} s\n")
print("RAW NOISE FLOOR")
print(f"  {'segment':<9}{'I_fc':>22}{'I_batt':>22}")
for nm, ix in (('idle', idle), ('loaded', load)):
    if len(ix) < 20:
        print(f"  {nm:<9}  (only {len(ix)} samples — re-export without --tmin)")
        continue
    a = sigma([ifc[i] for i in ix]); b = sigma([ibt[i] for i in ix])
    print(f"  {nm:<9}{a:>10.4f} A ({a/LSB:4.1f} LSB){b:>10.4f} A ({b/LSB:4.1f} LSB)")

if len(load) > 80:
    print("\nSIGMA vs LOAD   (I_total quartiles, loaded segment — rising = switching ripple)")
    pairs = sorted(((ifc[i]+ibt[i], i) for i in load))
    n = len(pairs)//4
    for k in range(4):
        ix = sorted(i for _, i in pairs[k*n:(k+1)*n])
        tots = [ifc[i]+ibt[i] for i in ix]
        a = sigma([ifc[i] for i in ix])
        print(f"  Q{k+1}  I_total {min(tots):.3f}-{max(tots):.3f} A   sigma I_fc {a:.4f} A ({a/LSB:4.1f} LSB)")

print(f"\nVOLTAGES   sigma V_fc {sigma(vfc):.4f} V   V_batt {sigma(vbt):.4f} V   V_bus {sigma(vbus):.4f} V")

print("\nFILTER PREVIEW   (EMA at 50 Hz telemetry rate — the Teensy loop sees ~20x more samples)")
print(f"  {'tau':>7}{'sigma I_fc':>16}{'sigma share':>16}{'share gain':>13}")
print(f"  {'raw':>7}{sigma(ifc):>13.4f} A{sigma(shr):>16.4f}{'—':>13}")
for tau in TAUS:
    f_ifc = ema(t, ifc, tau); f_ibt = ema(t, ibt, tau)
    f_shr, last = [], 0.5
    for a, b in zip(f_ifc, f_ibt):
        tot = abs(a)+abs(b)
        if tot > 0.05: last = abs(a)/tot
        f_shr.append(last)
    s_i, s_s = sigma(f_ifc), sigma(f_shr)
    print(f"  {tau:>5.0f}ms{s_i:>13.4f} A{s_s:>16.4f}{sigma(shr)/s_s:>12.1f}x")

# ---- plot raw vs filtered share -------------------------------------------
try:
    import matplotlib.pyplot as plt
except ImportError:
    print("\n(matplotlib not installed — numbers only)"); sys.exit(0)

TAU = 60.0
f_ifc = ema(t, ifc, TAU); f_ibt = ema(t, ibt, TAU)
f_shr, last = [], 0.5
for a, b in zip(f_ifc, f_ibt):
    tot = abs(a)+abs(b)
    if tot > 0.05: last = abs(a)/tot
    f_shr.append(last)

cmd = None
try:
    c = list(csv.DictReader(open(BAG + '/csv/ems_command.csv')))
    cmd = ([float(x['t_s']) for x in c], [float(x['power_share_cmd']) for x in c])
except Exception:
    pass

fig, ax = plt.subplots(3, 1, figsize=(13, 10), sharex=True)
fig.suptitle(f"Signal filtering preview — EMA {TAU:g} ms", fontsize=13, fontweight='bold')
if cmd: ax[0].plot(cmd[0], cmd[1], lw=1.6, color='tab:blue', label='commanded')
ax[0].plot(t, shr,   lw=0.7, alpha=.55, color='tab:orange', label='achieved, raw')
ax[0].plot(t, f_shr, lw=1.4, color='tab:red', label=f'achieved, EMA {TAU:g} ms')
ax[0].set_ylabel('power share'); ax[0].set_ylim(-.05, 1.05)
ax[0].legend(fontsize=8); ax[0].grid(alpha=.3)
ax[1].plot(t, ifc,   lw=0.7, alpha=.5, color='tab:blue',  label='I_fc raw')
ax[1].plot(t, f_ifc, lw=1.4, color='tab:blue', label='I_fc filtered')
ax[1].plot(t, ibt,   lw=0.7, alpha=.5, color='tab:orange', label='I_batt raw')
ax[1].plot(t, f_ibt, lw=1.4, color='tab:orange', label='I_batt filtered')
ax[1].axhline(1.4, ls=':', color='tab:red', lw=1)
ax[1].set_ylabel('current (A)'); ax[1].legend(fontsize=8, ncol=2); ax[1].grid(alpha=.3)
ax[2].plot(t, vfc, lw=0.8, color='tab:green', label='V_fc raw')
ax[2].plot(t, ema(t, vfc, TAU), lw=1.4, color='darkgreen', label='V_fc filtered')
ax[2].axhline(4.5, ls=':', color='tab:red', lw=1)
ax[2].set_ylabel('V_fc (V)'); ax[2].set_xlabel('time (s)')
ax[2].legend(fontsize=8); ax[2].grid(alpha=.3)
plt.tight_layout(); plt.show()