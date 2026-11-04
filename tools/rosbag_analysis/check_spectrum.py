"""
check_spectrum.py — what does the current noise look like in frequency?

Usage (from the Analysis folder):
    python3 check_spectrum.py ../../logs/rosbags/rosbag_sweep_2026-10-20_09-08-49

IMPORTANT: telemetry is 50 Hz, so this can only show 0-25 Hz. The real ripple is
at tens of kHz and has ALREADY been aliased down. What you see here is the fold,
not the source. This tells you whether the aliased noise is broadband or a beat;
it cannot tell you the switching frequency.
"""
import csv, sys

BAG = sys.argv[1] if len(sys.argv) > 1 else '../../logs/rosbags/rosbag_sweep_2026-10-20_09-08-49'

try:
    import numpy as np
except ImportError:
    sys.exit("needs numpy:  python3 -m pip install --break-system-packages numpy")

r = list(csv.DictReader(open(BAG + '/csv/vehicle_state.csv')))
t   = np.array([float(x['t_s'])    for x in r])
ifc = np.array([float(x['I_fc'])   for x in r])
ibt = np.array([float(x['I_batt']) for x in r])

m = t > 60.0                      # loaded segment only
t, ifc, ibt = t[m], ifc[m], ibt[m]
if len(t) < 256:
    sys.exit("not enough loaded samples — re-export the CSV without --tmin")

dt = float(np.median(np.diff(t)))
fs = 1.0 / dt
print(f"\n{BAG.split('/')[-1]}")
print(f"  {len(t)} loaded samples, fs = {fs:.1f} Hz, Nyquist = {fs/2:.1f} Hz")

def residual(v, win=15):
    """Subtract a centred moving average: removes the sweep, keeps the noise."""
    k = np.ones(win) / win
    sm = np.convolve(v, k, mode='same')
    e = win // 2
    return (v - sm)[e:-e]

def spectrum(v):
    v = v - v.mean()
    w = np.hanning(len(v))
    V = np.fft.rfft(v * w)
    f = np.fft.rfftfreq(len(v), dt)
    p = np.abs(V) / (np.sum(w) / 2)
    return f[1:], p[1:]

for name, sig in (('I_fc', ifc), ('I_batt', ibt)):
    res = residual(sig)
    f, p = spectrum(res)
    band = f < fs / 2
    f, p = f[band], p[band]
    # flatness: peak vs median. White noise sits near 3-5x; a tone is 20x+.
    ratio = p.max() / np.median(p)
    print(f"\n  {name}:  residual rms {res.std():.4f} A  ({res.std()/0.00806:.1f} LSB)")
    print(f"    peak/median = {ratio:5.1f}   -> {'BEAT / tone' if ratio > 15 else 'broadband (flat)'}")
    top = np.argsort(p)[-5:][::-1]
    print("    strongest components:")
    for i in top:
        print(f"      {f[i]:6.2f} Hz   amplitude {p[i]:.5f} A")

try:
    import matplotlib.pyplot as plt
except ImportError:
    print("\n(matplotlib not installed - numbers only)"); sys.exit(0)

fig, ax = plt.subplots(2, 1, figsize=(12, 8))
fig.suptitle("Current noise spectrum (aliased - NOT the true ripple frequency)",
             fontsize=12, fontweight='bold')
for k, (name, sig, col) in enumerate((('I_fc', ifc, 'tab:blue'),
                                      ('I_batt', ibt, 'tab:orange'))):
    f, p = spectrum(residual(sig))
    ax[k].semilogy(f, p, lw=0.8, color=col)
    ax[k].axhline(float(np.median(p)), ls=':', color='gray', lw=1, label='median (noise floor)')
    ax[k].set_ylabel(f"{name} amplitude (A)")
    ax[k].set_xlim(0, fs / 2)
    ax[k].legend(fontsize=8); ax[k].grid(alpha=.3)
ax[1].set_xlabel("frequency (Hz)  -  aliased into 0-25 Hz by 50 Hz telemetry")
plt.tight_layout(); plt.show()
