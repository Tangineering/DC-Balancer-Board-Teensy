"""Morning review 2026-11-14/15, section 3.1 (J.2 item 74): U101 OVP band figures.

Reads existing result CSVs only (no simulation is run, no file outside this folder is written).

Sources:
  ../../chopper/results_static_iv.csv      healthy chopper onset H-lo / H-typ / H-hi (RESULTS Table 5.1)
  ../../chopper/r2_bands.csv               fitted divider OVP bands, no leak / +-320 nA both pins (Table 5.5)
  ../../chopper/r2_candidates.csv          lever (a) 68.1k / 47.5k (Table 5.7)
  ../../chopper/r2_impedance.csv           0.5x and 0.25x scaled strings (Table 5.8)
  ../../chopper/r2_ovp_corners.csv         Parts G, GC, GS first-trip brackets (Table 5.6, 5.8.3, 5.8.4)
  ../../chopper/results_thresholds.csv     Part B first-trip brackets at OVP lo (22.19 V) / typ (23.19 V)
  ../../efuse_decay/results/a_bands_corners.csv   typical 25 C leak column (sim 5 Table 1)
  ../../efuse_decay/results/a_mc_samples.csv      illustrative Monte Carlo (sim 5 part a), printed only
Quoted values (not in a CSV):
  BQ25798 VBUS_OVP rising 25.2 / 25.7 / 26.2 V, 24 V recommended VBUS maximum (SLUSDV2C 6.5, 6.3; chopper RESULTS 5.8.5)
  TCKE1401NM V_OVPR 1.18 / 1.233 / 1.298 V (DS Table 10.1; chopper RESULTS 5.8.5 and 10.2 check pass)
  UVLO/OVP pin leakage +-320 nA (DS Table 10.1; chopper RESULTS 5.8.1)
  Fitted divider R102 845k, R103 64.9k, R104 51.1k, 0.1 % (chopper RESULTS 5.8.1)
"""
import csv
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = os.path.normpath(os.path.join(HERE, '..', '..'))
CHOP = os.path.join(SIM, 'chopper')
EFU = os.path.join(SIM, 'efuse_decay', 'results')

plt.rcParams.update({'font.size': 9.5})


def rows(path):
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def fnum(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return float('nan')


# ---------------------------------------------------------------- data
static = {r['chopper']: r for r in rows(os.path.join(CHOP, 'results_static_iv.csv'))}
ONSET = {k: fnum(static[k]['v_onset_1mA']) for k in ('H-lo', 'H-typ', 'H-hi')}  # 21.35 / 22.12 / 23.095

bands = {(r['leak'], r['threshold']): r for r in rows(os.path.join(CHOP, 'r2_bands.csv'))}
fit_nl = bands[('none', 'OVP_rise')]
fit_lk = bands[('+-320 nA both pins', 'OVP_rise')]
FIT = dict(typ=fnum(fit_nl['typ_noleak']),
           nl=(fnum(fit_nl['min']), fnum(fit_nl['max'])),
           lk=(fnum(fit_lk['min']), fnum(fit_lk['max'])))

cand = rows(os.path.join(CHOP, 'r2_candidates.csv'))
lev = [r for r in cand if r['R103'] == '68100' and r['R104'] == '47500'][0]
imp = {r['scale']: r for r in rows(os.path.join(CHOP, 'r2_impedance.csv'))}


def opt(r):
    return dict(typ=fnum(r['ovp_rise_typ']),
                nl=(fnum(r['ovp_rise_min_noleak']), fnum(r['ovp_rise_max_noleak'])),
                lk=(fnum(r['ovp_rise_min']), fnum(r['ovp_rise_max'])))


OPTIONS = [
    ('Fitted\n845k / 64.9k / 51.1k', FIT),
    ('Lever (a)\n845k / 68.1k / 47.5k', opt(lev)),
    ('0.5x string\n432k / 33.2k / 24.6k', opt(imp['0.5'])),
    ('0.25x string\n205k / 16k / 11.8k', opt(imp['0.25'])),
]

corners = {r['threshold']: r for r in rows(os.path.join(EFU, 'a_bands_corners.csv'))}
typ25 = fnum(corners['OVP_rise']['typ_typleak25C_V'])

# Quoted constants
BQ_OVP = (25.2, 25.7, 26.2)     # SLUSDV2C 6.5
BQ_REC = 24.0                   # SLUSDV2C 6.3
VOVPR = (1.18, 1.233, 1.298)    # TCKE1401NM Table 10.1
I_LEAK = 320e-9                 # TCKE1401NM Table 10.1, both pins
R102, R103, R104, TOL = 845e3, 64.9e3, 51.1e3, 0.001

# ---------------------------------------------------------------- decomposition (fitted divider, rising minimum)
# Nominal OVP gain = (R102+R103+R104)/R104 = 961.0/51.1 = 18.806.
#   typ          = 1.233 * 18.806 = 23.188 V   (r2_bands typ_noleak 23.1881)
#   V_OVPR min   = 1.180 * 18.806 = 22.191 V   -> spread term 23.188 - 22.191 = 0.997 V
#                  (this is the design-doc B.4 / sim 2 "OVP lo" 22.19 V, exact resistors, no leak)
# Resistor term: minimum gain with R104 at +0.1 % and R102, R103 at -0.1 %:
#   g_min = (909.9k*0.999 + 51.1k*1.001) / (51.1k*1.001) = 18.771
#   1.180 * 18.771 = 22.150 V -> resistor term 22.191 - 22.150 = 0.042 V (CSV no-leak min 22.1494)
# Leak term (CSV): 22.1494 - 21.5884 = 0.561 V, split by superposition into
#   OVP pin : 320 nA * (R104 || (R102+R103)) * gain = 320n * 48.38k * 18.806 = 0.291 V
#   UVLO pin: 320 nA * (R102 || (R103+R104)) * R104/(R103+R104) * gain
#           = 320n * 102.0k * 0.4405 * 18.806 = 0.270 V
# (RESULTS 5.8.1 quotes 0.291 V and 0.270 V; the script recomputes them as a check.)
g_nom = (R102 + R103 + R104) / R104
g_min = ((R102 + R103) * (1 - TOL) + R104 * (1 + TOL)) / (R104 * (1 + TOL))
g_max = ((R102 + R103) * (1 + TOL) + R104 * (1 - TOL)) / (R104 * (1 - TOL))
v_typ = VOVPR[1] * g_nom
v_spread = VOVPR[0] * g_nom
v_res = VOVPR[0] * g_min
par = lambda a, b: a * b / (a + b)  # noqa: E731
d_ovp_pin = I_LEAK * par(R104, R102 + R103) * g_nom
d_uvlo_pin = I_LEAK * par(R102, R103 + R104) * R104 / (R103 + R104) * g_nom
v_leak_csv = FIT['lk'][0]

print('Fitted OVP rising decomposition (V):')
print('  gain nom %.4f, min %.4f, max %.4f' % (g_nom, g_min, g_max))
print('  typ %.4f (CSV %.4f)' % (v_typ, FIT['typ']))
print('  V_OVPR min, exact R %.4f  (spread term %.4f)' % (v_spread, v_typ - v_spread))
print('  + 0.1 %% resistors %.4f (CSV %.4f; resistor term %.4f)' % (v_res, FIT['nl'][0], v_spread - v_res))
print('  OVP-pin leak %.4f, UVLO-pin leak %.4f, sum %.4f; CSV leak term %.4f'
      % (d_ovp_pin, d_uvlo_pin, d_ovp_pin + d_uvlo_pin, FIT['nl'][0] - v_leak_csv))
print('  max side: V_OVPR max exact R %.4f, +res %.4f (CSV %.4f), +leak CSV %.4f'
      % (VOVPR[2] * g_nom, VOVPR[2] * g_max, FIT['nl'][1], FIT['lk'][1]))
print('  typ with typical 25 C leak (a_bands_corners) %.4f, shift %.4f' % (typ25, typ25 - FIT['typ']))

# Illustrative Monte Carlo (sim 5 part a; uniform over -40..125 C limits, NOT a yield figure)
mc = [fnum(r['OVP_rise_V']) for r in rows(os.path.join(EFU, 'a_mc_samples.csv'))]
n = len(mc)
for thr in (23.0, 23.1, ONSET['H-typ']):
    print('  MC fraction OVP_rise < %.3f V: %.4f (n=%d)' % (thr, sum(v < thr for v in mc) / n, n))

# ---------------------------------------------------------------- figure 1: band diagram + decomposition
C_LEAK, C_NL, C_TYP = '#c9d7ea', '#4f7cb8', '#12355b'
C_CHOP, C_BQ = '#f2c26b', '#d9776f'

fig, (ax, bx) = plt.subplots(2, 1, figsize=(10, 7.6), gridspec_kw={'height_ratios': [3.0, 1.55]})
ax.axvspan(ONSET['H-lo'], ONSET['H-hi'], color=C_CHOP, alpha=0.35, lw=0)
for k in ('H-lo', 'H-typ', 'H-hi'):
    ax.axvline(ONSET[k], color='#a0701a', lw=0.9, ls=':')
ax.axvspan(BQ_OVP[0], BQ_OVP[2], color=C_BQ, alpha=0.25, lw=0)
ax.axvline(BQ_OVP[1], color=C_BQ, lw=1.0, ls=':')
ax.axvline(BQ_REC, color='0.3', lw=1.2, ls='--')

nrow = len(OPTIONS)
for i, (name, o) in enumerate(OPTIONS):
    y = nrow - 1 - i
    ax.barh(y, o['lk'][1] - o['lk'][0], left=o['lk'][0], height=0.62, color=C_LEAK, edgecolor='0.55', lw=0.6)
    ax.barh(y, o['nl'][1] - o['nl'][0], left=o['nl'][0], height=0.36, color=C_NL)
    ax.plot([o['typ']], [y], marker='D', ms=7, color=C_TYP, mec='white', mew=0.8, zorder=5)
    # End labels sit outside the light leak box, on a white background, so that the onset lines and
    # the box edges do not cross the digits. Upper label = leak end, lower (blue) label = no-leak end.
    WB = dict(facecolor='white', edgecolor='none', pad=0.4, alpha=0.9)
    ax.text(o['lk'][0] - 0.05, y + 0.19, '%.3f' % o['lk'][0], ha='right', va='center', fontsize=8.5, bbox=WB,
            zorder=6)
    ax.text(o['lk'][0] - 0.05, y - 0.19, '%.3f' % o['nl'][0], ha='right', va='center', fontsize=8.5, color=C_NL,
            bbox=WB, zorder=6)
    ax.text(o['lk'][1] + 0.05, y + 0.19, '%.3f' % o['lk'][1], ha='left', va='center', fontsize=8.5, bbox=WB,
            zorder=6)
    ax.text(o['lk'][1] + 0.05, y - 0.19, '%.3f' % o['nl'][1], ha='left', va='center', fontsize=8.5, color=C_NL,
            bbox=WB, zorder=6)
    ax.text(o['typ'], y + 0.40, '%.3f' % o['typ'], ha='center', va='bottom', fontsize=8.5, color=C_TYP,
            fontweight='bold')
ax.set_yticks(range(nrow))
ax.set_yticklabels([n_ for n_, _ in OPTIONS][::-1])
ax.set_ylim(-0.85, nrow - 0.2)
ax.set_xlim(20.0, 28.0)
ax.set_xlabel('VCHG-IN (V)')
ax.set_title('(a) U101 OVP rising band per divider option (R102 / R103 / R104, 0.1 %)', loc='left', fontsize=10,
             pad=20)
ytop = nrow - 0.32
ax.text((ONSET['H-lo'] + ONSET['H-hi']) / 2, ytop, 'MB chopper onset\n21.35-23.10 V', ha='center', va='top',
        fontsize=8.5, color='#7a5410')
for k, lab in (('H-lo', 'H-lo'), ('H-typ', 'H-typ'), ('H-hi', 'H-hi')):
    ax.text(ONSET[k], -0.80, lab, ha='center', va='bottom', fontsize=8, color='#7a5410')
ax.text((BQ_OVP[0] + BQ_OVP[2]) / 2, ytop, 'BQ25798 VBUS_OVP\n25.2 / 25.7 / 26.2 V', ha='center', va='top',
        fontsize=8.5, color='#8a2f27')
ax.text(BQ_REC + 0.05, -0.80, '24 V BQ25798 rec. VBUS max', ha='left', va='bottom', fontsize=8,
        color='0.25')
ax.legend(handles=[
    Line2D([], [], marker='D', ls='', color=C_TYP, label='typical (no leak)'),
    Patch(color=C_NL, label='V_OVPR 1.18-1.298 V + 0.1 % resistors, no pin leak'),
    Patch(facecolor=C_LEAK, edgecolor='0.55', label='+ +-320 nA on OVP and UVLO pins'),
], loc='lower center', bbox_to_anchor=(0.5, 1.0), ncol=3, fontsize=8, frameon=False)

# panel (b): low-edge waterfall for the fitted divider
steps = [
    ('typical\n(1.233 V)', v_typ, None),
    ('V_OVPR min\n1.18 V', v_spread, v_typ - v_spread),
    ('0.1 %\nresistors', FIT['nl'][0], v_spread - FIT['nl'][0]),
    ('OVP-pin leak\n320 nA', FIT['nl'][0] - d_ovp_pin, d_ovp_pin),
    ('UVLO-pin leak\n320 nA', v_leak_csv, FIT['nl'][0] - d_ovp_pin - v_leak_csv),
]
cols = [C_TYP, '#6b8fc2', '#6b8fc2', '#9fb6d6', '#9fb6d6']
prev = None
for j, (lab, v, d) in enumerate(steps):
    if d is None:
        bx.plot([v], [j], marker='D', ms=7, color=C_TYP)
        bx.text(v + 0.06, j, '%.3f V' % v, va='center', fontsize=8.5, color=C_TYP, fontweight='bold')
    else:
        bx.barh(j, d, left=v, height=0.55, color=cols[j], edgecolor='0.4', lw=0.5)
        bx.text(v - 0.05, j, '%.3f V' % v, va='center', ha='right', fontsize=8.5)
        bx.text(v + d + 0.05, j, '-%.3f V' % d, va='center', ha='left', fontsize=8.5, color='0.25',
                bbox=dict(facecolor='white', edgecolor='none', pad=0.5))
    if prev is not None:
        bx.plot([prev, prev], [j - 1, j], color='0.6', lw=0.6, ls=':')
    prev = v
for k in ('H-lo', 'H-typ', 'H-hi'):
    bx.axvline(ONSET[k], color='#a0701a', lw=0.9, ls=':')
    bx.text(ONSET[k] - 0.03, -0.95, '%s onset\n%.3f V' % (k, ONSET[k]), ha='right', va='top', fontsize=8,
            color='#7a5410')
bx.axvspan(23.0, 23.1, color='#b03a2e', alpha=0.25, lw=0)
bx.text(23.25, 2.9, 'Part GS: H-hi first trip\nmoves 1.1-1.2 -> 1.4-1.5 A\nbetween 23.0 and 23.1 V',
        fontsize=8, color='#7d241b', va='center')
bx.set_yticks(range(len(steps)))
bx.set_yticklabels([s[0] for s in steps], fontsize=8.5)
bx.invert_yaxis()
bx.set_ylim(len(steps) - 0.5, -1.0)
bx.set_xlim(21.0, 24.4)
bx.set_xlabel('VCHG-IN, OVP rising minimum of the fitted divider (V)')
bx.set_title('(b) Fitted divider: decomposition of the rising minimum, 23.188 V -> 21.588 V', loc='left',
             fontsize=10)
fig.tight_layout()
out1 = os.path.join(HERE, 'fig_ovp_bands.png')
fig.savefig(out1, dpi=150)
plt.close(fig)
print('wrote fig_ovp_bands.png')

# ---------------------------------------------------------------- figure 2: first-trip brackets
oc = rows(os.path.join(CHOP, 'r2_ovp_corners.csv'))
th = rows(os.path.join(CHOP, 'results_thresholds.csv'))


def g_bracket(part, chopper, ovp):
    r = [x for x in oc if x['part'] == part and x['chopper'] == chopper and x['ovp'] == ovp
         and x['charger'] == 'nom'][0]
    return fnum(r['I_first_trip_gt']), fnum(r['I_first_trip_le'])


def b_bracket(chopper, ovp):
    # results_thresholds: I_first_ovp_trip_gt = last current without a trip, _le = first current with a trip
    r = [x for x in th if x['part'] == 'B' and x['chopper'] == chopper and x['ovp'] == ovp
         and x['charger'] == 'nom' and x['vcut'] == 'none' and x['u101'] == 'release'][0]
    return fnum(r['I_first_ovp_trip_gt']), fnum(r['I_first_ovp_trip_le'])


CORNERS = [
    # label, rising threshold (V), getter
    ('Fitted, leak corner lo\n(Part G s5-lo)', FIT['lk'][0], lambda c: g_bracket('G', c, 's5-lo')),
    ('Fitted, V_OVPR min, exact R,\nno leak (Part B "lo")', 22.19, lambda c: b_bracket(c, 'lo')),
    ('Fitted, typical\n(Part B "typ")', 23.19, lambda c: b_bracket(c, 'typ')),
    ('Fitted, leak corner hi\n(Part G s5-hi)', FIT['lk'][1], lambda c: g_bracket('G', c, 's5-hi')),
    ('Lever (a), leak corner lo\n(Part GC)', fnum(lev['ovp_rise_min']),
     lambda c: g_bracket('GC', c, 'c68.1k-47.5k-lo')),
    ('Lever (a), leak corner hi\n(Part GC)', fnum(lev['ovp_rise_max']),
     lambda c: g_bracket('GC', c, 'c68.1k-47.5k-hi')),
]
STATES = [('H-lo', '#2a9d8f'), ('H-typ', '#e9a23b'), ('H-hi', '#b03a2e')]

gs = sorted([x for x in oc if x['part'] == 'GS'], key=lambda x: fnum(x['rise']))

fig, (ax, bx) = plt.subplots(1, 2, figsize=(10.4, 5.4), gridspec_kw={'width_ratios': [2.25, 1.0]})
for i, (lab, vr, get) in enumerate(CORNERS):
    for s, (st, col) in enumerate(STATES):
        lo, hi = get(st)
        y = i + (s - 1) * 0.24
        ax.plot([lo, hi], [y, y], color=col, lw=6, solid_capstyle='butt')
        ax.text(hi + 0.02, y, '%.2f-%.2f' % (lo, hi), va='center', fontsize=7.5, color=col)
ax.axvspan(1.1, 1.2, color='#b03a2e', alpha=0.08, lw=0)
ax.axvspan(1.4, 1.75, color='#2a9d8f', alpha=0.08, lw=0)
ax.text(1.15, -1.15, 'charger capacity\nexceeded', ha='center', va='top', fontsize=7.5, color='#7d241b')
ax.text(1.575, -1.15, 'charger + chopper\ncapacity', ha='center', va='top', fontsize=7.5, color='#1d6b61')
ax.set_yticks(range(len(CORNERS)))
ax.set_yticklabels(['%s\n%s V' % (lab, ('%.3f' % vr).rstrip('0')) for lab, vr, _ in CORNERS], fontsize=8)
ax.invert_yaxis()
ax.set_ylim(len(CORNERS) - 0.5, -1.2)
ax.set_xlim(1.0, 2.0)
ax.set_xlabel('Regen current at the first U101 OVP trip (A): last without / first with a trip')
ax.set_title('(a) First-trip bracket, nominal charger, no VESC cut', loc='left', fontsize=10)
ax.legend(handles=[Line2D([], [], color=c, lw=6, label=s) for s, c in STATES], loc='lower right', fontsize=8,
          title='chopper', title_fontsize=8)

xs = [fnum(x['rise']) for x in gs]
for x in gs:
    v = fnum(x['rise'])
    lo, hi = fnum(x['I_first_trip_gt']), fnum(x['I_first_trip_le'])
    bx.plot([v, v], [lo, hi], color='#b03a2e', lw=6, solid_capstyle='butt')
bx.axvline(ONSET['H-hi'], color='#a0701a', lw=0.9, ls=':')
bx.text(ONSET['H-hi'] - 0.02, 1.58, 'H-hi onset\n23.095 V', fontsize=7.5, color='#7a5410', va='top', ha='right')
bx.axvline(FIT['typ'], color=C_TYP, lw=0.9, ls='--')
bx.text(FIT['typ'] + 0.01, 1.25, 'fitted typ\n23.188 V', fontsize=7.5, color=C_TYP)
bx.set_xlim(min(xs) - 0.1, max(xs) + 0.1)
bx.set_ylim(1.0, 1.6)
bx.set_xlabel('Swept OVP rising threshold (V)')
bx.set_ylabel('First-trip bracket (A)')
bx.set_title('(b) Part GS, H-hi, nominal charger', loc='left', fontsize=10)
fig.tight_layout()
fig.savefig(os.path.join(HERE, 'fig_ovp_first_trip.png'), dpi=150)
plt.close(fig)
print('wrote fig_ovp_first_trip.png')
