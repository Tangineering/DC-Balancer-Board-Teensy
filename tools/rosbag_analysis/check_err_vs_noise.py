"""
check_err_vs_noise.py — is the share tracking error real, or is it feedback noise?

    python3 check_err_vs_noise.py ../Logs/rosbag_sweep_2026-10-20_09-08-49

For each I_total band it reports:
    err RMS    achieved - commanded share, RMS
    sigma_sh   sample-to-sample noise on the share, from TIME-ADJACENT differences
    noise/err  ~1 => that band's error is essentially measurement noise
               <<1 => real tracking error dominates there

Differences are taken in time order and only between genuinely adjacent samples,
then binned by current. Binning first and differencing after measures the sweep,
not the noise.
"""
import csv, sys, bisect

BAG = sys.argv[1] if len(sys.argv) > 1 else '../Logs/rosbag_sweep_2026-10-20_09-08-49'
T0  = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0

try:
    import numpy as np
except ImportError:
    sys.exit("needs numpy:  python3 -m pip install --break-system-packages numpy")

r = list(csv.DictReader(open(BAG + '/csv/vehicle_state.csv')))
c = list(csv.DictReader(open(BAG + '/csv/ems_command.csv')))
ct = [float(x['t_s']) for x in c]
cs = [float(x['power_share_cmd']) for x in c]

seq = []
for x in r:
    t = float(x['t_s'])
    if t <= T0:
        continue
    tot = abs(float(x['I_fc'])) + abs(float(x['I_batt']))
    a = float(x['power_share_actual'])
    i = bisect.bisect_right(ct, t) - 1
    if i >= 0 and 0.0 < a < 1.0 and tot > 0:
        seq.append((t, tot, a, a - cs[i]))

if len(seq) < 200:
    sys.exit(f"only {len(seq)} usable samples — re-export the CSV without --tmin")

seq.sort(key=lambda z: z[0])                       # TIME order

dts = [seq[i+1][0] - seq[i][0] for i in range(len(seq)-1)]
gap = float(np.median(dts)) * 1.8                  # "adjacent" = within 1.8x the median step

pairs = [(seq[i][1], seq[i+1][2] - seq[i][2], seq[i][3])
         for i in range(len(seq)-1)
         if seq[i+1][0] - seq[i][0] < gap]

print(f"\n{BAG.rstrip('/').split('/')[-1]}")
print(f"  {len(seq)} samples after t={T0:g}s, {len(pairs)} adjacent pairs "
      f"(median step {float(np.median(dts))*1000:.1f} ms)")

e_all = np.array([z[2] for z in pairs])
d_all = np.array([z[1] for z in pairs])
print(f"  overall:  err RMS {(e_all**2).mean()**0.5:.4f}   "
      f"sigma_sh {d_all.std()/(2**0.5):.4f}")

pairs.sort(key=lambda z: z[0])
n = len(pairs) // 4
print(f"\n  {'I_total band':<22}{'err RMS':>9}{'sigma_sh':>10}{'noise/err':>11}   verdict")
for k in range(4):
    ch = pairs[k*n:(k+1)*n] if k < 3 else pairs[3*n:]
    d = np.array([z[1] for z in ch]); e = np.array([z[2] for z in ch])
    sig = d.std() / (2**0.5)
    err = (e**2).mean()**0.5
    rat = sig/err if err else 0.0
    verdict = ("mostly noise" if rat > 0.8 else
               "mixed" if rat > 0.45 else "mostly real error")
    print(f"  {ch[0][0]:6.3f} - {ch[-1][0]:6.3f} A     {err:9.4f}{sig:10.4f}{rat:11.2f}   {verdict}")
