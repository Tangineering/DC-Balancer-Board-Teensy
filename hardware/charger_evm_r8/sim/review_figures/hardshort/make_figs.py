"""Morning-review figures for sim 1 (hardshort), section 4.1.

Reads only the existing result CSVs of ../../hardshort/results/ (no re-simulation):
  - grid.csv       : revision-2 hard-short grid (RESULTS.md section 5.1, Table 5, 216 cases)
  - tft_check.csv  : revision-3 fast-trip check (RESULTS.md section 5.6, Table 7a, 528 runs)

Writes fig_hs_grid_sma.png and fig_hs_tft_check.png next to this script.
"""
import csv
import os
from collections import defaultdict

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, '..', '..', 'hardshort', 'results')

plt.rcParams.update({'font.size': 10})

# TCKE1401NM VOUT absolute minimum -0.3 V (DS Table 8.1; RESULTS.md section 5.1 / Table 8 step (2)).
V_LIMIT = -0.3


def read(name):
    with open(os.path.join(RES, name), newline='') as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# Figure A: hard-short grid, OUT minimum and time below -0.3 V per D103 candidate
# Source: results/grid.csv (columns d103, feed, V0, out_min_V, t_out_below_m0p3_us).
# The 'none' case (-20 to -51 V) is omitted here; it is shown in plots/fig2_out_min_by_d103.png.
# ---------------------------------------------------------------------------
grid = read('grid.csv')
order = ['STPS2H100A_fit', 'MBRA2H100_mfr', 'MBRA2H100_maxfit', 'VSSA310S_fit', 'SS3H10_mfr']
label = {
    'STPS2H100A_fit': 'STPS2H100A\nordered\n(SMA)',
    'MBRA2H100_mfr': 'MBRA2H100\nT3G alt.\n(SMA)',
    'MBRA2H100_maxfit': 'MBRA2H100\nT3G\nmax-VF fit',
    'VSSA310S_fit': 'VSSA310S',
    'SS3H10_mfr': 'SS3H10\n(SMC)',
}
vcol = {'16': '#1f77b4', '22': '#ff7f0e', '23.6': '#d62728'}
mark = {'bench': 'o', 'veh': '^'}

fig, axs = plt.subplots(1, 2, figsize=(10, 5.2))
by = defaultdict(list)
for row in grid:
    if row['d103'] == 'none':
        continue
    by[row['d103']].append(row)

for i, d in enumerate(order):
    rows = by[d]
    for j, row in enumerate(rows):
        x = i + (j % 12 - 5.5) * 0.04
        kw = dict(color=vcol[row['V0']], marker=mark[row['feed']], s=18,
                  alpha=1.0 if i < 2 else 0.45, linewidths=0)
        axs[0].scatter(x, float(row['out_min_V']), **kw)
        axs[1].scatter(x, float(row['t_out_below_m0p3_us']), **kw)

sma = [r for d in order[:2] for r in by[d]]
om = [float(r['out_min_V']) for r in sma]
tb = [float(r['t_out_below_m0p3_us']) for r in sma]
allfit = [r for d in order for r in by[d]]
tb_all = [float(r['t_out_below_m0p3_us']) for r in allfit]
print('SMA pair: OUT min %.3f..%.3f V, t<-0.3 V %.2f..%.2f us (n=%d)' % (min(om), max(om), min(tb), max(tb), len(sma)))
print('all fitted D103: t<-0.3 V %.2f..%.2f us (n=%d)' % (min(tb_all), max(tb_all), len(allfit)))

ax = axs[0]
ax.axhline(V_LIMIT, color='r', lw=1.0)
ax.text(4.4, V_LIMIT + 0.15, 'TCKE1401NM VOUT min -0.3 V', color='r', ha='right', va='bottom', fontsize=9)
ax.axhspan(min(om), max(om), xmin=0, xmax=0.4, color='0.85', zorder=0)
ax.annotate('SMA pair: %.2f to %.2f V' % (max(om), min(om)), xy=(0.5, min(om)), xytext=(1.8, -7.6),
            fontsize=9, arrowprops=dict(arrowstyle='->', lw=0.8))
ax.set_ylim(-8.5, 0.5)
ax.set_ylabel('U101 OUT minimum (V)')
ax.set_title('OUT minimum', fontsize=10)

ax = axs[1]
ax.axhspan(min(tb), max(tb), xmin=0, xmax=0.4, color='0.85', zorder=0)
ax.annotate('SMA pair: %.2f to %.2f us' % (min(tb), max(tb)), xy=(0.5, max(tb)), xytext=(1.8, 11.6),
            fontsize=9, arrowprops=dict(arrowstyle='->', lw=0.8))
ax.set_ylim(0, 12.5)
ax.set_ylabel('time with OUT < -0.3 V (us)')
ax.set_title('Duration below the -0.3 V limit', fontsize=10)

for ax in axs:
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels([label[d] for d in order], fontsize=9, rotation=0)
    ax.tick_params(axis='x', labelsize=9)
    ax.grid(alpha=0.3)
handles = [plt.Line2D([], [], color=vcol[v], marker='o', ls='', label='VCHG-IN %s V' % v) for v in ['16', '22', '23.6']]
handles += [plt.Line2D([], [], color='k', marker=mark[f], ls='', label={'bench': 'bench feed', 'veh': 'vehicle MB feed'}[f])
            for f in ['bench', 'veh']]
fig.legend(handles=handles, loc='lower center', ncol=5, fontsize=9, frameon=False)
fig.text(0.5, 0.075, 'Opaque markers: the two SMA D103 candidates; faded: the other fitted candidates '
         '(the no-D103 case is omitted).', ha='center', fontsize=9)
fig.suptitle('T-C-04 step (2) hard short: grid of feed {bench, vehicle} x VCHG-IN {16, 22, 23.6} V x\n'
             'R_short {5, 50} mOhm x W1/W2 L x {0.7, 1.0, 1.3}, 36 cases per D103', fontsize=10)
fig.tight_layout(rect=(0, 0.11, 1, 0.93))
fig.savefig(os.path.join(HERE, 'fig_hs_grid_sma.png'), dpi=150)
plt.close(fig)

# ---------------------------------------------------------------------------
# Figure B: revision-3 fast-trip check, OUT minimum against tFASTTRIP per R_short
# Source: results/tft_check.csv (columns case, feed, V0, Rsh, Lsh, d103, tft, out_min_V).
# Per-corner value = worst (lowest) over the two D103 cases and L_short 0/100 nH,
# as in RESULTS.md Table 7a. Corners: bench/vehicle feed x 16/23.6 V.
# ---------------------------------------------------------------------------
tft = read('tft_check.csv')
n_runs = len(tft)
n_fail = sum(1 for r in tft if r['out_min_V'] in ('', 'nan', 'NaN'))
print('tft_check.csv: %d runs, %d without an OUT minimum' % (n_runs, n_fail))

TFTS = [3, 4, 6, 8]
corners = [('bench', '16'), ('bench', '23.6'), ('veh', '16'), ('veh', '23.6')]
ccol = {('bench', '16'): '#1f77b4', ('bench', '23.6'): '#9467bd',
        ('veh', '16'): '#2ca02c', ('veh', '23.6'): '#d62728'}
cname = {('bench', '16'): 'bench 16 V', ('bench', '23.6'): 'bench 23.6 V',
         ('veh', '16'): 'vehicle 16 V', ('veh', '23.6'): 'vehicle 23.6 V'}

worst = defaultdict(lambda: 1e9)   # (Rsh, feed, V0, tft_us) -> lowest OUT min
allv = defaultdict(list)           # Rsh -> every OUT min (all corners, D103, Lsh, delays)
for r in tft:
    if not r['case'].startswith('tft') or '_rsh_' not in r['case']:
        continue
    rsh = float(r['Rsh'])
    t_us = int(round(float(r['tft']) * 1e6))
    key = (rsh, r['feed'], r['V0'], t_us)
    v = float(r['out_min_V'])
    worst[key] = min(worst[key], v)
    allv[rsh].append(v)

panels = [(2.0, '2 ohm'), (1.5, '1.5 ohm'), (1.0, '1 ohm'), (0.5, '0.5 ohm')]
fig, axs = plt.subplots(1, 4, figsize=(10.5, 4.4))
for ax, (rsh, name) in zip(axs, panels):
    pts = []
    for c in corners:
        ys = [worst[(rsh, c[0], c[1], t)] for t in TFTS]
        pts += ys
        ax.plot(TFTS, ys, marker='o', ms=4, color=ccol[c], label=cname[c])
    lo, hi = min(pts), max(pts)
    print('R_short %.1f ohm: per-corner worst %.3f..%.3f V; all runs max %.3f V' % (rsh, lo, hi, max(allv[rsh])))
    ax.axhline(V_LIMIT, color='r', lw=1.0)
    ax.axhline(0.0, color='k', lw=0.6, ls=':')
    ax.axvline(4, color='0.5', lw=0.6, ls='--')
    ax.axvline(8, color='0.5', lw=0.6, ls='--')
    if rsh == 0.5:
        ax.set_ylim(-1.45, 0.1)
        ax.text(3.0, -1.42, 'all runs max %.3f V:\nbelow 0 V at every delay' % max(allv[rsh]),
                fontsize=9, va='bottom')
        ax.text(2.9, V_LIMIT + 0.02, '-0.3 V', color='r', fontsize=9, ha='left', va='bottom')
    else:
        top = hi + 0.15 * (hi - V_LIMIT)
        ax.set_ylim(V_LIMIT - 0.08 * (top - V_LIMIT), top)
        ax.text(8.1, V_LIMIT + 0.01 * (top - V_LIMIT), '-0.3 V', color='r', fontsize=9, ha='right', va='bottom')
    ax.set_title('R_short %s\nOUT min %+.3f to %+.3f V' % (name, lo, hi), fontsize=9.5)
    ax.set_xticks(TFTS)
    ax.set_xlabel('tFASTTRIP (us)')
    ax.grid(alpha=0.3)
axs[0].set_ylabel('U101 OUT minimum (V)')
axs[0].text(4.05, axs[0].get_ylim()[0] + 0.05, 'typ.', fontsize=9, color='0.4')
axs[0].text(7.95, axs[0].get_ylim()[0] + 0.05, 'max.', fontsize=9, color='0.4', ha='right')
h, l = axs[0].get_legend_handles_labels()
fig.legend(h, l, loc='lower center', ncol=4, fontsize=9, frameon=False)
nplot = sum(len(allv[r]) for r, _ in panels)
print('plotted runs (R_short 2/1.5/1/0.5 ohm): %d of %d' % (nplot, n_runs))
fig.suptitle('Revision 3 fast-trip check: OUT minimum against tFASTTRIP (%d R_short runs of the %d-run check),\n'
             'worst over D103 and L_short 0/100 nH per corner' % (nplot, n_runs), fontsize=10)
fig.tight_layout(rect=(0, 0.07, 1, 0.90))
fig.savefig(os.path.join(HERE, 'fig_hs_tft_check.png'), dpi=150)
plt.close(fig)
print('done')
