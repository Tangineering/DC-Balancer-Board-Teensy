"""Review figure for MORNING_REVIEW_2026-11-14.md sections 3.2 and 4.4 (sim 4, permit gate).

Reads the committed sim 4 CSVs only (no re-simulation):
  ../../permit/results/agg_t2lat.csv  -> H1 inhibit latency L and T-B-06 budget (RESULTS.md Table 5.4b)
  ../../permit/results/t2int.csv, t2intx.csv, t2intl.csv, t2lat.csv, t2thr.csv, t2rise.csv
                                      -> deck count and sim_ok check (RESULTS.md section 5.6a: 4116 decks)
Output: fig_permit_h13_budget.png (this folder).
The 150 us T-B-06 limit and the 46 us H.13 deduction are quoted from RESULTS.md section 5.6a
("at most 150 us (line 3545)"; "The H.13 deductions (46 us)").
"""
import csv
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, '..', '..', 'permit', 'results')

OPTIONS = [  # (key in CSV, label as in the morning review table section 3.2)
    ('base', 'As built\n(C106 = C107 = 470 pF,\nC108 = 1.0 nF)'),
    ('C108_470p', 'C108 = 470 pF'),
    ('C107_4n7_only', 'C107 alone\n= 4.7 nF'),
    ('C106C107_4n7', 'C106 = C107\n= 4.7 nF'),
    ('C106C107_10n', 'C106 = C107\n= 10 nF'),
]
T_B_06_US = 150.0      # RESULTS.md 5.6a, design document line 3545
H13_DEDUCT_US = 46.0   # RESULTS.md 5.6a: 24 + 15 + 7 us


def rng(s):
    """Parse 'a-b' where a or b may be negative (e.g. '-252.1--139.7')."""
    s = s.strip()
    for i in range(1, len(s)):
        if s[i] == '-' and s[i - 1] != '-' and s[i - 1] != 'e':
            return float(s[:i]), float(s[i + 1:])
    v = float(s)
    return v, v


def num(s):
    s = s.strip()
    return None if s in ('', '-') else float(s)


def deck_check():
    total, bad = 0, 0
    for fam in ('t2int', 't2intx', 't2intl', 't2lat', 't2thr', 't2rise'):
        with open(os.path.join(RES, fam + '.csv'), newline='') as fh:
            rows = list(csv.DictReader(fh))
        nbad = sum(1 for r in rows if r['sim_ok'].strip().lower() not in ('true', '1', 'yes'))
        print('%-7s decks %4d  sim_ok false %d' % (fam, len(rows), nbad))
        total += len(rows)
        bad += nbad
    print('TOTAL decks %d, not ok %d' % (total, bad))
    return total, bad


def load_lat():
    with open(os.path.join(RES, 'agg_t2lat.csv'), newline='') as fh:
        rows = list(csv.DictReader(fh))
    out = {}
    for key, _ in OPTIONS:
        d = {}
        for amp in ('1.25', '1.8'):
            sel = [r for r in rows if r['option'] == key and r['I_A'] == amp]
            lo = min(rng(r['L_us'])[0] for r in sel)
            hi = max(rng(r['L_us'])[1] for r in sel)
            flo = min(rng(r['L_fixed_us'])[0] for r in sel)
            fhi = max(rng(r['L_fixed_us'])[1] for r in sel)
            # worst VBUS = minimum budget over the VBUS rows that carry a value
            s3 = [num(r['budget_sim3_us']) for r in sel if num(r['budget_sim3_us']) is not None]
            s3f = [num(r['budget_fixed_sim3_us']) for r in sel if num(r['budget_fixed_sim3_us']) is not None]
            r3 = [num(r['budget_r3_us']) for r in sel if num(r['budget_r3_us']) is not None]
            d[amp] = dict(L=(lo, hi), Lf=(flo, fhi), sim3=min(s3), sim3f=min(s3f), r3=min(r3))
        out[key] = d
    return out


def main():
    plt.rcParams.update({'font.size': 9})
    deck_check()
    lat = load_lat()
    for key, _ in OPTIONS:
        for amp in ('1.25', '1.8'):
            v = lat[key][amp]
            print('%-14s %4s A  L %.1f-%.1f us (fixed %.1f-%.1f)  budget sim3 %.1f  sim3 fixed %.1f  r3 %.1f'
                  % (key, amp, v['L'][0], v['L'][1], v['Lf'][0], v['Lf'][1], v['sim3'], v['sim3f'], v['r3']))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.5, 5.2), gridspec_kw=dict(width_ratios=[1, 1.05]))
    cols = {'1.25': '#1f77b4', '1.8': '#d62728'}
    short = ['As built', 'C108 = 470 pF', 'C107 alone = 4.7 nF', 'C106 = C107 = 4.7 nF', 'C106 = C107 = 10 nF']

    # Left: H1 inhibit latency L, ranges over VBUS 14.5-16.4 V, corner and delay set (agg_t2lat.csv L_us,
    # L_fixed_us). Horizontal layout: one row per option, one bar per current.
    off = {'1.25': 0.17, '1.8': -0.17}
    for amp in ('1.25', '1.8'):
        for i, (key, _) in enumerate(OPTIONS):
            v = lat[key][amp]
            yi = i + off[amp]
            ax1.hlines(yi, v['L'][0], v['L'][1], color=cols[amp], lw=7, alpha=0.35,
                       label=('%s A, all delay sets' % amp.replace('1.8', '1.80')) if i == 0 else None)
            ax1.hlines(yi, v['Lf'][0], v['Lf'][1], color=cols[amp], lw=7,
                       label=('%s A, fixed tPD 2 / 4 us' % amp.replace('1.8', '1.80')) if i == 0 else None)
    for i, (key, _) in enumerate(OPTIONS):
        lo = min(lat[key][a]['L'][0] for a in ('1.25', '1.8'))
        hi = max(lat[key][a]['L'][1] for a in ('1.25', '1.8'))
        ax1.annotate('%.1f-%.1f us' % (lo, hi), (hi, i), textcoords='offset points', xytext=(6, -3),
                     ha='left', va='center', fontsize=8.5)
    ax1.axvline(H13_DEDUCT_US, color='k', ls='--', lw=1)
    ax1.text(H13_DEDUCT_US + 6, 4.5, 'H.13 deductions\n46 us (24 + 15 + 7)', ha='left', va='bottom', fontsize=8)
    ax1.set_yticks(range(len(OPTIONS)))
    ax1.set_yticklabels(short, fontsize=8.5)
    ax1.invert_yaxis()
    ax1.set_xlabel('H1 inhibit latency L (us)')
    ax1.set_xlim(0, 800)
    ax1.set_ylim(4.6, -0.6)
    ax1.set_title('H1 inhibit latency, VBUS 14.5-16.4 V')
    ax1.grid(axis='x', alpha=0.3)
    ax1.legend(loc='upper right', fontsize=8)

    # Right: T-B-06 budget, minimum over the VBUS rows that carry a value (sim 3: 15.9 / 16.4 V;
    # r3: 15.5 / 15.9 / 16.4 V; agg_t2lat.csv shows '-' elsewhere). Horizontal bars, labels at bar ends.
    h = 0.3
    for amp in ('1.25', '1.8'):
        vals = [lat[key][amp]['sim3'] for key, _ in OPTIONS]
        ys = [i + off[amp] for i in range(len(OPTIONS))]
        ax2.barh(ys, vals, height=h, color=cols[amp],
                 label='%s A, sim 3 basis' % amp.replace('1.8', '1.80'))
        for y, v in zip(ys, vals):
            if abs(v) >= 100:   # long bar: label inside the bar end, clear of the 150 us line
                ax2.annotate('%.1f' % v, (v, y), textcoords='offset points',
                             xytext=(-4 if v >= 0 else 4, 0), ha='right' if v >= 0 else 'left',
                             va='center', fontsize=8, color='white', fontweight='bold')
            else:               # short bar: label outside the bar end
                ax2.annotate('%.1f' % v, (v, y), textcoords='offset points',
                             xytext=(4 if v >= 0 else -4, 0), ha='left' if v >= 0 else 'right',
                             va='center', fontsize=8, color=cols[amp])
    # r3 basis at 1.80 A: diamonds on a third row slot below the 1.80 A bar, label to the right
    r3 = [lat[key]['1.8']['r3'] for key, _ in OPTIONS]
    yr3 = [i - 0.40 for i in range(len(OPTIONS))]
    ax2.plot(r3, yr3, 'kD', ms=4, label='1.80 A, r3 basis')
    for y, v in zip(yr3, r3):
        ax2.annotate('r3 %.1f' % v, (v, y), textcoords='offset points', xytext=(5, 0),
                     ha='left', va='center', fontsize=7.5)
    ax2.axvline(T_B_06_US, color='k', ls='--', lw=1)
    ax2.text(T_B_06_US + 4, 4.5, 'T-B-06\n150 us', ha='left', va='bottom', fontsize=8)
    ax2.axvline(0, color='k', lw=0.8)
    ax2.set_yticks(range(len(OPTIONS)))
    ax2.set_yticklabels([''] * len(OPTIONS))
    ax2.set_xlabel('budget left for T-B-06 (us), all delay sets, worst VBUS')
    ax2.set_xlim(-420, 330)
    ax2.set_ylim(4.6, -0.75)
    ax2.set_title('T-B-06 budget = window - largest L')
    ax2.grid(axis='x', alpha=0.3)
    ax2.legend(loc='upper left', fontsize=8)

    fig.suptitle('Sim 4 section 5.6a, t2lat family (360 decks), 3 corners, C_VMOT_MIN 0.4 mF; source results/agg_t2lat.csv\n'
                 'Budget = worst of VBUS 15.9 / 16.4 V (sim 3 basis) or 15.5 / 15.9 / 16.4 V (r3 basis); '
                 'no budget value exists at other VBUS', fontsize=8.5)
    fig.tight_layout()
    out = os.path.join(HERE, 'fig_permit_h13_budget.png')
    fig.savefig(out, dpi=150)
    print('wrote ' + os.path.basename(out))


if __name__ == '__main__':
    main()
