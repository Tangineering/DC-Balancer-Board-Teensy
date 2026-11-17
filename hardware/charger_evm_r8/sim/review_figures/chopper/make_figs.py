"""Review figures for MORNING_REVIEW_2026-11-14.md section 4.2 (sim 2, chopper).

Reads the existing sim 2 result CSVs only; it runs no simulation and writes only into this folder.

Sources (all relative to ../../chopper/):
  results_static_iv.csv  - Part A key points (RESULTS.md Table 5.1)
  r2_ovp_corners.csv     - Parts G, GS, GC first-trip brackets (RESULTS.md Tables 5.6, 5.7, section 5.8.3)
  r2_body_compare.csv    - body-diode re-run against the 2026-11-14 runs (RESULTS.md section 5.8.6)
Quoted constants (not in a CSV) are cited where they are used.
"""
import csv
import math
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, '..', '..', 'chopper'))
DPI = 150
plt.rcParams.update({'font.size': 9.5, 'axes.titlesize': 10.5, 'legend.fontsize': 8.5})

# RESULTS.md Table 5.5 / MORNING_REVIEW section 3.1: OVP rising band of the fitted divider at the
# sim 5 leakage and resistor corners (also r2_ovp_corners.csv rise column of s5-lo / s5-hi).
OVP_RISE_MIN, OVP_RISE_MAX = 21.588, 25.019
# RESULTS.md section 5.1 / MORNING_REVIEW 4.2: logged pin-39 reading ceiling 18.1-18.3 V.
LOG_CEIL = (18.1, 18.3)

COLORS = {'H-lo': '#1f77b4', 'H-typ': '#2ca02c', 'H-hi': '#17becf',
          'F-k9': '#d62728', 'F-k15': '#ff7f0e', 'F-soft': '#9467bd', 'F-open': '#7f7f7f'}


def read_csv(name):
    with open(os.path.join(SRC, name), newline='') as fh:
        return list(csv.DictReader(fh))


def fnum(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return float('nan')


# ---------------------------------------------------------------------------------------------
# Figure 1: static chopper onset (R-SHUNT current) and the pin-39 reading, from Part A key points.
# ---------------------------------------------------------------------------------------------
def fig_static():
    rows = {r['chopper']: r for r in read_csv('results_static_iv.csv')}
    onset = {k: fnum(rows[k]['v_onset_1mA']) for k in rows}
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.5, 4.6))

    # (a) R-SHUNT current against V-MOT. Points are the CSV columns v_onset_1mA ... v_at_850mA
    # at 0.001 / 0.01 / 0.1 / 0.3 / 0.47 / 0.74 / 0.85 A; below the onset the current is < 1 mA (drawn as 0).
    cols = [('v_onset_1mA', 0.001), ('v_clamp_10mA', 0.01), ('v_at_100mA', 0.1), ('v_at_300mA', 0.3),
            ('v_at_470mA', 0.47), ('v_at_740mA', 0.74), ('v_at_850mA', 0.85)]
    ax1.axvspan(21.35, 23.10, color='#2ca02c', alpha=0.15, lw=0)
    ax1.text(22.22, 0.93, 'healthy onset band\n21.35-23.10 V', ha='center', va='top', fontsize=8.5)
    for k in ('H-lo', 'H-typ', 'H-hi', 'F-k15', 'F-k9'):
        v = [fnum(rows[k][c]) for c, _ in cols]
        i = [a for _, a in cols]
        ax1.plot([15.0, v[0]] + v, [0.0, 0.0] + i, '-', color=COLORS[k], lw=1.4,
                 label='%s (onset %.2f V)' % (k, onset[k] + 1e-9))  # 23.095 rounds half-up to 23.10 (Table 5.1)
        ax1.plot(v, i, 'o', color=COLORS[k], ms=3.5)
    ax1.plot([], [], ' ', label='F-soft, F-open: no onset')
    # U101 OVP rising band at the sim 5 corners, drawn as a bracket (the band diagram is a separate figure).
    ax1.annotate('', xy=(OVP_RISE_MIN, 1.02), xytext=(OVP_RISE_MAX, 1.02),
                 arrowprops=dict(arrowstyle='|-|', color='k', lw=1.0, shrinkA=0, shrinkB=0))
    ax1.text(OVP_RISE_MAX + 0.4, 1.02, 'U101 OVP rising %.3f-%.3f V\n(sim 5 corners, at VCHG-IN)'
             % (OVP_RISE_MIN, OVP_RISE_MAX), ha='left', va='center', fontsize=8)
    # 35 V caps and the RT1987 40 V absolute maximum: sim/chopper/RESULTS.md lines 12 and 40.
    for vl, lab in ((35.0, '35 V caps'), (40.0, 'RT1987 40 V abs max')):
        ax1.axvline(vl, color='k', ls=':', lw=0.8)
        ax1.text(vl - 0.3, 0.93, lab, rotation=90, ha='right', va='top', fontsize=8)
    # H-typ slope above 0.47 A: (34.95 - 22.21) / (0.74 - 0.47) = 47.2 V/A (R-SHUNT 47 Ohm, RESULTS.md 5.1).
    ax1.annotate('above 0.47 A,\nV-MOT rises at\nthe R-SHUNT\nslope, about\n47 V/A: an\nonset, not a\nceiling',
                 xy=(27.0, 0.57), xytext=(15.4, 0.78), fontsize=8, va='top',
                 arrowprops=dict(arrowstyle='->', lw=0.8))
    ax1.set_xlim(15, 45)
    ax1.set_ylim(0, 1.12)
    ax1.set_xlabel('V-MOT, forced (V)')
    ax1.set_ylabel('Current through R-SHUNT (A)')
    ax1.set_title('(a) Chopper onset, static sweep key points')
    ax1.grid(alpha=0.3)
    ax1.legend(loc='lower right', fontsize=7.5, framealpha=0.95)

    # (b) pin-39 reading at V-MOT 15.93 / 22 / 25 / 30 / 35 V (CSV read_* columns).
    vx = [15.93, 22.0, 25.0, 30.0, 35.0]
    rc = ['read_15p93', 'read_22', 'read_25', 'read_30', 'read_35']
    ax2.axhspan(LOG_CEIL[0], LOG_CEIL[1], color='orange', alpha=0.3, lw=0)
    ax2.text(15.3, 18.45, 'logged reading ceiling 18.1-18.3 V', fontsize=8, va='bottom')
    ax2.plot([15, 35], [15, 35], 'k:', lw=0.8, label='reading = V-MOT')
    for k, lab in (('H-typ', 'H-typ (H-lo, H-hi within 0.4 V)'), ('F-k15', 'F-k15'),
                   ('F-k9', 'F-k9 (F-open identical)'), ('F-soft', 'F-soft (hypothesis)')):
        y = [fnum(rows[k][c]) for c in rc]
        ax2.plot(vx, y, 'o-', color=COLORS[k], ms=4, lw=1.2, label=lab)
    # vmot_for_read_18p2: V-MOT at an 18.2 V reading (23.42 V F-k15, 25.21 V F-k9).
    for k in ('F-k15', 'F-k9'):
        vm = fnum(rows[k]['vmot_for_read_18p2'])
        ax2.plot([vm, vm], [12, 18.2], '--', color=COLORS[k], lw=1.0)
        ax2.plot(vm, 18.2, 's', color=COLORS[k], ms=6, mfc='white')
        ax2.text(vm + 0.2, 12.4, '%.2f V' % vm, color=COLORS[k], fontsize=8.5, rotation=90, va='bottom')
    ax2.annotate('18.2 V reading -> true V-MOT\n23.4-25.2 V (knee sinks)', xy=(24.3, 18.2), xytext=(26.5, 14.0),
                 fontsize=8, arrowprops=dict(arrowstyle='->', lw=0.8))
    ax2.text(35.2, 28.9, 'healthy: ADC full scale 29.27 V', fontsize=7.5, ha='right', va='top')
    ax2.set_xlim(15, 35.5)
    ax2.set_ylim(12, 31)
    ax2.set_xlabel('V-MOT, true (V)')
    ax2.set_ylabel('V_rgn reading, pin 39 (V)')
    ax2.set_title('(b) Pin-39 reading against true V-MOT (VR-1)')
    ax2.grid(alpha=0.3)
    ax2.legend(loc='upper left', fontsize=7.5)
    fig.tight_layout()
    out = os.path.join(HERE, 'fig_chopper_onset_vrgn.png')
    fig.savefig(out, dpi=DPI)
    plt.close(fig)
    print('wrote', os.path.basename(out))


# ---------------------------------------------------------------------------------------------
# Figure 2: first U101 OVP trip brackets at the sim 5 corners and for the lever (a) dividers.
# ---------------------------------------------------------------------------------------------
def fig_first_trip():
    rows = read_csv('r2_ovp_corners.csv')
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.5, 4.8), gridspec_kw={'width_ratios': [1.35, 1]})

    groups = [  # (label, part, ovp key, charger)
        ('Fitted 64.9k/51.1k, s5-lo\n(rising 21.588 V), charger none', 'G', 's5-lo', 'none'),
        ('Fitted 64.9k/51.1k, s5-lo\n(rising 21.588 V)', 'G', 's5-lo', 'nom'),
        ('Fitted 64.9k/51.1k, s5-hi\n(rising 25.019 V)', 'G', 's5-hi', 'nom'),
        ('Lever (a) 68.1k/47.5k, lo\n(rising 23.256 V)', 'GC', 'c68.1k-47.5k-lo', 'nom'),
        ('Lever (a) 68.1k/47.5k, hi\n(rising 26.863 V)', 'GC', 'c68.1k-47.5k-hi', 'nom'),
        ('69.8k/46.4k, lo\n(rising 23.835 V)', 'GC', 'c69.8k-46.4k-lo', 'nom'),
        ('69.8k/46.4k, hi\n(rising 27.504 V)', 'GC', 'c69.8k-46.4k-hi', 'nom'),
    ]
    states = ['H-lo', 'H-typ', 'H-hi']
    ax1.axvspan(1.1, 1.2, color='#d62728', alpha=0.12, lw=0)
    ax1.axvspan(1.4, 1.6, color='#2ca02c', alpha=0.12, lw=0)
    n = len(groups)
    for gi, (lab, part, ovp, chg) in enumerate(groups):
        y0 = n - 1 - gi
        for si, st in enumerate(states):
            m = [r for r in rows if r['part'] == part and r['ovp'] == ovp and r['chopper'] == st
                 and r['charger'] == chg]
            if not m:
                continue
            gt, le = fnum(m[0]['I_first_trip_gt']), fnum(m[0]['I_first_trip_le'])
            y = y0 + (si - 1) * 0.22
            lo = 0.0 if math.isnan(gt) else gt  # nan = tripped at the lowest grid current (<= 0.25 A)
            ax1.plot([lo, le], [y, y], '-', color=COLORS[st], lw=5, solid_capstyle='butt',
                     label=st if gi == 1 else None)
            txt = ('<= %.2f A' % le) if math.isnan(gt) else ('%.1f-%.1f A' % (gt, le))
            ax1.text(le + 0.03, y, txt, va='center', fontsize=7.5)
    ax1.set_yticks(range(n))
    ax1.set_yticklabels([g[0] for g in groups][::-1], fontsize=7.8)
    ax1.set_xlim(0, 2.0)
    ax1.set_ylim(-0.6, n - 0.4)
    ax1.set_xlabel('Regen current, first U101 OVP trip bracket (A)')
    ax1.text(1.15, n - 0.45, 'charger\ncapacity', ha='center', va='top', fontsize=7.5, color='#a00')
    ax1.text(1.5, n - 0.45, 'charger +\nchopper', ha='center', va='top', fontsize=7.5, color='#060')
    ax1.set_title('(a) First trip, 0.6 s bursts, no VESC cut, 0.97 mF')
    ax1.grid(axis='x', alpha=0.3)
    ax1.legend(loc='upper right', fontsize=8)

    # (b) H-hi, nominal charger: first-trip bracket against the rising threshold at VCHG-IN.
    pts = [r for r in rows if r['chopper'] == 'H-hi' and r['charger'] == 'nom'
           and (r['part'] == 'GS' or r['ovp'] in ('s5-lo', 'c68.1k-47.5k-lo', 'c69.8k-46.4k-lo'))]
    pts.sort(key=lambda r: fnum(r['rise']))
    for r in pts:
        x, gt, le = fnum(r['rise']), fnum(r['I_first_trip_gt']), fnum(r['I_first_trip_le'])
        col = '#d62728' if le <= 1.2 else '#2ca02c'
        mk = 's' if r['part'] != 'GS' else 'o'
        ax2.plot([x, x], [gt, le], '-', color=col, lw=4, solid_capstyle='butt')
        ax2.plot(x, (gt + le) / 2, mk, color='k', ms=4, mfc='white')
    ax2.axvline(23.10, color='k', ls='--', lw=1.0)
    ax2.text(23.15, 0.93, 'H-hi onset 23.10 V\n(required minimum)', fontsize=8, va='bottom', ha='left')
    ax2.annotate('fitted, s5-lo\n21.588 V', xy=(21.588, 1.09), xytext=(21.35, 1.0), ha='left', va='top',
                 fontsize=7.5, arrowprops=dict(arrowstyle='->', lw=0.7))
    ax2.annotate('68.1k/47.5k lo\n23.256 V', xy=(23.256, 1.51), xytext=(23.2, 1.6), ha='right', va='bottom',
                 fontsize=7.5, arrowprops=dict(arrowstyle='->', lw=0.7))
    ax2.annotate('69.8k/46.4k lo\n23.835 V', xy=(23.835, 1.51), xytext=(23.9, 1.56), ha='left', va='bottom',
                 fontsize=7.5, arrowprops=dict(arrowstyle='->', lw=0.7))
    # GS sweep span 22.7-23.4 V (both colours), r2_ovp_corners.csv part GS.
    ax2.annotate('', xy=(22.7, 1.30), xytext=(23.4, 1.30),
                 arrowprops=dict(arrowstyle='|-|', color='k', lw=0.9, shrinkA=0, shrinkB=0))
    ax2.text(22.65, 1.30, 'GS sweep 22.7-23.4 V', ha='right', va='center', fontsize=7.5)
    ax2.text(21.4, 1.45, 'squares: G / GC runs\ncircles: GS sweep', fontsize=7.5)
    ax2.set_xlim(21.3, 24.7)
    ax2.set_ylim(0.9, 1.72)
    ax2.set_xlabel('OVP rising threshold at VCHG-IN (V)')
    ax2.set_ylabel('First-trip bracket (A)')
    ax2.set_title('(b) H-hi, nominal charger')
    ax2.grid(alpha=0.3)
    fig.tight_layout()
    out = os.path.join(HERE, 'fig_first_trip_brackets.png')
    fig.savefig(out, dpi=DPI)
    plt.close(fig)
    print('wrote', os.path.basename(out))


# ---------------------------------------------------------------------------------------------
# Figure 3: U101 body-diode re-run, per-run change against the 2026-11-14 runs.
# ---------------------------------------------------------------------------------------------
def fig_body():
    rows = read_csv('r2_body_compare.csv')
    parts = [('B-body', 'Part B (360)'), ('E-body', 'Part E (840)'), ('E-latch-body', 'latching U101 (48)'),
             ('D-body', 'Part D (56)')]
    cols = ['#1f77b4', '#ff7f0e', '#9467bd', '#2ca02c']
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.5, 4.2))
    for (p, lab), c in zip(parts, cols):
        sel = [r for r in rows if r['part'] == p]
        ax1.plot([fnum(r['vmot_peak_old']) for r in sel], [1e3 * fnum(r['vmot_peak_delta']) for r in sel],
                 '.', color=c, ms=3.5, label=lab)
        ax2.plot([1e3 * fnum(r['ovp_off_s_old']) for r in sel], [1e3 * fnum(r['ovp_off_s_delta']) for r in sel],
                 '.', color=c, ms=3.5, label=lab)
    dv = max(rows, key=lambda r: abs(fnum(r['vmot_peak_delta'])))
    dt = max(rows, key=lambda r: abs(fnum(r['ovp_off_s_delta'])))
    ax1.annotate('max |dV| %.1f mV' % (1e3 * abs(fnum(dv['vmot_peak_delta']))),
                 xy=(fnum(dv['vmot_peak_old']), 1e3 * fnum(dv['vmot_peak_delta'])),
                 xytext=(60, -10), fontsize=8.5, arrowprops=dict(arrowstyle='->', lw=0.8))
    ax2.annotate('max |dt| %.2f ms' % (1e3 * abs(fnum(dt['ovp_off_s_delta']))),
                 xy=(1e3 * fnum(dt['ovp_off_s_old']), 1e3 * fnum(dt['ovp_off_s_delta'])),
                 xytext=(150, 0.6), fontsize=8.5, arrowprops=dict(arrowstyle='->', lw=0.8))
    n_trip = sum(r['ovp_trips_delta'] != '0' for r in rows)
    n_cut = sum(r['vesc_cuts_delta'] != '0' for r in rows)
    n_lat = sum(r['rt1987_latched_old'] != r['rt1987_latched_new'] for r in rows)
    e_max = max(abs(fnum(r['e_charger_J_delta'])) for r in rows)
    i_max = max(fnum(r['body_peak_A']) for r in rows)
    q_max = max(fnum(r['body_charge_C']) for r in rows)
    box = ('%d runs: changed U101 trip counts %d, VESC cut counts %d, RT1987 latches %d\n'
           'max |charger energy change| %.0f uJ; body diode <= %.0f uA, %.1f nC'
           % (len(rows), n_trip, n_cut, n_lat, 1e6 * e_max, 1e6 * i_max, 1e9 * q_max))
    ax1.set_xscale('log')
    ax1.set_xlabel('V-MOT peak without body diode (V)')
    ax1.set_ylabel('V-MOT peak change (mV)')
    ax1.set_title('(a) V-MOT peak')
    ax1.set_ylim(-14, 14)
    ax1.grid(alpha=0.3)
    ax1.legend(fontsize=7.5, loc='upper right')
    ax2.set_xlabel('U101 off time without body diode (ms)')
    ax2.set_ylabel('U101 off-time change (ms)')
    ax2.set_title('(b) U101 OVP off time')
    ax2.set_ylim(-1.0, 1.0)
    ax2.grid(alpha=0.3)
    fig.text(0.5, 0.01, box, ha='center', va='bottom', fontsize=8.5,
             bbox=dict(boxstyle='round', fc='#f4f4f4', ec='#999'))
    fig.tight_layout(rect=(0, 0.1, 1, 1))
    out = os.path.join(HERE, 'fig_body_diode_delta.png')
    fig.savefig(out, dpi=DPI)
    plt.close(fig)
    print('wrote', os.path.basename(out))
    print('check: trips %d cuts %d latches %d dV %.4f mV dE %.1f uJ dt %.3f ms'
          % (n_trip, n_cut, n_lat, 1e3 * abs(fnum(dv['vmot_peak_delta'])), 1e6 * e_max,
             1e3 * abs(fnum(dt['ovp_off_s_delta']))))


if __name__ == '__main__':
    fig_static()
    fig_first_trip()
    fig_body()
