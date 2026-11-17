"""Review figures for sim 3 (comparators), morning review 2026-11-14 section 4.3.

Reads the existing result CSVs of sim/comparators/csv/ only; no simulation is run and no file in
sim/comparators/ is written. Outputs are written next to this script.

Sources of every plotted number:
- csv/mc_baseline.csv        : per-board SPICE trips (column h1f2 = H1 fall at VBUS 16.39 V), N = 4000.
- csv/mc_statistics.csv      : MC min/max, worst case (WC) with TCR (wc_lo/wc_hi) and without TCR
                               (wc_lo_noTCR/wc_hi_noTCR), per design (baseline, opt08 = VR-4 option).
- csv/analytic_200k_gauss_vs_uniform.csv : 200 000-sample uniform and normal maxima.
- csv/psrr_reference_sweep.csv : WC H1 fall max at 16.39 V under the four PSRR treatments (Table 5a).
- Design-document bands and criteria are the values quoted in sim/comparators/RESULTS.md
  Tables 4, 5, 6 and 7 (B.2, H.1, H.2, H.22): see DOC_BANDS below.
"""
import csv
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, '..', '..', 'comparators', 'csv')
plt.rcParams.update({'font.size': 9})


def read(name):
    with open(os.path.join(CSV, name), newline='') as f:
        return list(csv.DictReader(f))


stats = {(r['design'], r['key']): r for r in read('mc_statistics.csv')}
mc = read('mc_baseline.csv')
a200 = {(r['design'], r['quantity']): r for r in read('analytic_200k_gauss_vs_uniform.csv')}
psrr = [r for r in read('psrr_reference_sweep.csv')]


def s(design, key, col):
    return float(stats[(design, key)][col])


# Criteria quoted in RESULTS.md section 1 / Table 5 (design document H.1 regen threshold stack).
VINDPM_STAGE1_MIN = 17.84
VBUS_STEADY_MAX = 16.39

# ---------------------------------------------------------------- Figure A: H1 fall at VBUS 16.39 V
h1f2 = np.array([float(r['h1f2']) for r in mc])
mc_min, mc_max = s('baseline', 'h1f2', 'min'), s('baseline', 'h1f2', 'max')
wc_lo, wc_hi = s('baseline', 'h1f2', 'wc_lo'), s('baseline', 'h1f2', 'wc_hi')
wn_lo, wn_hi = s('baseline', 'h1f2', 'wc_lo_noTCR'), s('baseline', 'h1f2', 'wc_hi_noTCR')
v4_lo, v4_hi = s('opt08', 'h1f2', 'wc_lo'), s('opt08', 'h1f2', 'wc_hi')
q = 'H1 fall @ VBUS 16.39'
uni_max = float(a200[('baseline', q)]['uniform200k_max'])
gau_max = float(a200[('baseline', q)]['gauss_max'])
DOC_LO, DOC_HI = 17.340, 17.764   # RESULTS.md Table 4, design document column
psrr_hi = {r['variant']: float(r['h1f2_hi']) for r in psrr if r['design'] == 'baseline'}

print('h1f2 n=%d min=%.4f max=%.4f; WC TCR %.4f-%.4f; noTCR %.4f-%.4f; VR-4 WC %.4f-%.4f'
      % (len(h1f2), h1f2.min(), h1f2.max(), wc_lo, wc_hi, wn_lo, wn_hi, v4_lo, v4_hi))
print('200k uniform max %.4f, normal max %.4f; PSRR maxima %s'
      % (uni_max, gau_max, ', '.join('%s %.4f' % kv for kv in psrr_hi.items())))

fig, (ax0, ax1) = plt.subplots(1, 2, figsize=(10.5, 5.6), gridspec_kw={'width_ratios': [1.25, 1]})

ax0.hist(h1f2, bins=60, color='#4C78A8', alpha=0.85, label='SPICE Monte Carlo, N = %d' % len(h1f2))
ymax = ax0.get_ylim()[1]
bars = [  # (label, lo, hi, colour, y-position as fraction of ymax)
    ('Design document band (B.2, H.1)', DOC_LO, DOC_HI, '0.45', 1.30),
    ('WC without resistor TCR', wn_lo, wn_hi, '#54A24B', 1.20),
    ('WC with resistor TCR', wc_lo, wc_hi, '#E45756', 1.10),
]
for lab, lo, hi, col, yf in bars:
    y = ymax * yf
    ax0.plot([lo, hi], [y, y], color=col, lw=4, solid_capstyle='butt', label='%s %.3f-%.3f V' % (lab, lo, hi))
ax0.axvline(VINDPM_STAGE1_MIN, color='#B279A2', ls='--', lw=1.3)
ax0.text(VINDPM_STAGE1_MIN - 0.005, ymax * 0.90, 'VINDPM_STAGE1 min\n17.84 V', color='#B279A2', fontsize=9,
         ha='right')
ax0.set_ylim(0, ymax * 1.45)
ax0.set_xlim(17.20, 17.92)
ax0.set_xlabel('H1 fall trip on V-MOT (V) at VBUS 16.39 V')
ax0.set_ylabel('boards per bin')
ax0.set_title('H1 fall distribution and bands (present design)')
ax0.legend(loc='upper center', bbox_to_anchor=(0.5, -0.14), fontsize=8, framealpha=0.95)
ax0.grid(alpha=0.3)

# Right panel: upper edge only, one row per estimate.
rows = [
    ('MC uniform, N = 4000 (max)', mc_max, '#4C78A8'),
    ('Analytic normal, 200 000 (max)', gau_max, '#4C78A8'),
    ('Analytic uniform, 200 000 (max)', uni_max, '#4C78A8'),
    ('Design document max', DOC_HI, '0.45'),
    ('WC without TCR', wn_hi, '#54A24B'),
    ('WC with TCR, KPS = 0', psrr_hi['KPS = 0'], '#E45756'),
    ('WC with TCR, PSRR ref 3.3 V (used)', psrr_hi['ref 3.3 V (used)'], '#E45756'),
    ('WC with TCR, PSRR ref 1.8 V', psrr_hi['ref 1.8 V'], '#E45756'),
    ('WC with TCR, PSRR ref 5.5 V', psrr_hi['ref 5.5 V'], '#E45756'),
    ('VR-4 option, WC with TCR', v4_hi, '#F58518'),
]
for i, (lab, v, col) in enumerate(rows):
    ax1.plot([v], [i], 'o', color=col, ms=7)
    d = (v - VINDPM_STAGE1_MIN) * 1000.0
    # Four decimals: CSV 17.7445 / 17.8405 V would print as 17.744 / 17.840 V at three decimals, whereas
    # RESULTS.md section 5.2 / Table 5a round them to 17.745 / 17.841 V. Labels sit centred above
    # each point so that none collides with the row labels.
    ax1.annotate('%.4f V (%+.1f mV)' % (v, d), (v, i), xytext=(0, 5), textcoords='offset points',
                 fontsize=8, ha='center', va='bottom')
ax1.axvline(VINDPM_STAGE1_MIN, color='#B279A2', ls='--', lw=1.3)
ax1.axvspan(VINDPM_STAGE1_MIN, 18.08, color='#B279A2', alpha=0.08)
ax1.text(18.075, -0.4, 'above 17.84 V:\nH.1 criterion fails', color='#B279A2', fontsize=8,
         ha='right', va='bottom')
ax1.set_yticks(range(len(rows)))
ax1.set_yticklabels([r[0] for r in rows], fontsize=8)
ax1.set_xlim(17.60, 18.08)
ax1.set_ylim(-0.6, len(rows) - 0.1)
ax1.set_xlabel('H1 fall maximum on V-MOT (V); mV relative to 17.84 V')
ax1.set_title('Upper edge against VINDPM_STAGE1 min')
ax1.grid(alpha=0.3, axis='x')
fig.tight_layout()
outA = os.path.join(HERE, 'fig_h1_fall_vs_vindpm_stage1.png')
fig.savefig(outA, dpi=150)
plt.close(fig)
print('wrote', os.path.basename(outA))

# ---------------------------------------------------------------- Figure B: band edges vs the design document
# Design-document bands as quoted in RESULTS.md Table 4 (H1), Table 6 (UVB) and Table 7 (FCC, H.22).
# Each row: (label, key for the lower edge, key for the upper edge, doc lower, doc upper).
# The H.22 FCC_OFF band (r9_calc_out.txt R9.H22: 'Vos 9 mV, VHYS/2') is a rise/fall threshold envelope, so its
# lower edge is compared with the FCC-falling worst case (focf / focfm) and its upper edge with the FCC-rising
# worst case (focr / focrm); RESULTS.md Table 7 and section 10 (falling WC without TCR 0.3764 V).
DOC_BANDS = [
    ('H1 fall, VBUS 15.20 V', 'h1f0', 'h1f0', 16.053, 16.463),
    ('H1 rise, VBUS 15.90 V', 'h1r1', 'h1r1', 17.097, 17.516),
    ('H1 fall, VBUS 15.90 V', 'h1f1', 'h1f1', 16.810, 17.229),
    ('H1 rise, VBUS 16.39 V', 'h1r2', 'h1r2', 17.627, 18.052),
    ('H1 fall, VBUS 16.39 V', 'h1f2', 'h1f2', 17.340, 17.764),
    ('UVB fall (inhibit)', 'uvbf', 'uvbf', 12.89, 13.78),
    ('UVB rise (re-permit)', 'uvbr', 'uvbr', 13.26, 14.16),
    ('FCC_OFF, EN net, fall/rise envelope', 'focf', 'focr', 0.377, 0.432),
    ('FCC_OFF, IN-, fall/rise envelope', 'focfm', 'focrm', 0.387, 0.441),
    ('FCC_ON, EN net, rising', 'fonr', 'fonr', 1.745, 1.875),
]
fig, ax = plt.subplots(figsize=(10.0, 6.0))
ax.axvspan(-13, 13, color='#54A24B', alpha=0.10)
ax.axvline(0, color='0.3', lw=0.8)
n = len(DOC_BANDS)
for i, (lab, klo, khi, dlo, dhi) in enumerate(DOC_BANDS):
    y = n - 1 - i
    nlo = (s('baseline', klo, 'wc_lo_noTCR') - dlo) * 1000.0
    nhi = (s('baseline', khi, 'wc_hi_noTCR') - dhi) * 1000.0
    tlo = (s('baseline', klo, 'wc_lo') - dlo) * 1000.0
    thi = (s('baseline', khi, 'wc_hi') - dhi) * 1000.0
    ax.plot([nlo], [y + 0.12], 'v', color='#54A24B', ms=7, label='WC without TCR, lower edge' if i == 0 else None)
    ax.plot([nhi], [y + 0.12], '^', color='#54A24B', ms=7, label='WC without TCR, upper edge' if i == 0 else None)
    ax.plot([tlo], [y - 0.12], 'v', color='#E45756', mfc='none', ms=7,
            label='WC with TCR, lower edge' if i == 0 else None)
    ax.plot([thi], [y - 0.12], '^', color='#E45756', mfc='none', ms=7,
            label='WC with TCR, upper edge' if i == 0 else None)
    ax.annotate('%+.1f / %+.1f' % (nlo, nhi), (max(nlo, nhi), y + 0.12), xytext=(6, -3),
                textcoords='offset points', fontsize=8, color='#2F6B2A')
    print('%-30s noTCR %+6.1f %+6.1f mV | TCR %+6.1f %+6.1f mV' % (lab, nlo, nhi, tlo, thi))
ax.text(1.5, n - 0.35, '+-13 mV', ha='left', fontsize=9, color='#2F6B2A', bbox=dict(facecolor='white', edgecolor='none', pad=1))
ax.set_yticks(range(n))
ax.set_yticklabels([b[0] for b in DOC_BANDS][::-1])
ax.set_ylim(-0.7, n - 0.1)
ax.set_xlabel('Simulated band edge minus design-document band edge (mV); negative = lower')
ax.set_title('Sim 3 worst-case band edges against design document B.2, H.1, H.2 and H.22 (present design)')
ax.grid(alpha=0.3, axis='x')
ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.11), fontsize=8, ncol=2, framealpha=0.95)
ax.text(1.0, -0.30, 'Document edges as quoted in sim 3 RESULTS.md Tables 4, 6 and 7 (UVB edges to 10 mV); '
        'FCC_OFF lower edge vs FCC falling, upper edge vs FCC rising.',
        transform=ax.transAxes, ha='right', fontsize=8, color='0.35')
fig.tight_layout()
outB = os.path.join(HERE, 'fig_band_edges_vs_doc.png')
fig.savefig(outB, dpi=150)
plt.close(fig)
print('wrote', os.path.basename(outB))
