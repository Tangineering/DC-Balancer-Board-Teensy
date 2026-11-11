"""Plots for the round-4 design walkthrough (design revision r8; the script keeps its r7 file name).

Every plotted result is read from ../calc/r7_calc_out.json (calc revision 7) or recomputed with a function imported from
../calc/r7_calc.py (in_spike, spike_worst, lprime, awg_d, z_need, sample_path, loop_L and the module constants).
Importing r7_calc parses the MB .brd at module level but does not run main(), so no calc output file is rewritten.
Every recomputation is cross-checked against the JSON value that the calc prints (check()). Values that exist only in
the design text or the review records are cited constants with the source line named beside them.

Run:  "C:/Users/ricky/miniforge3/python.exe" -I make_figs_r7.py
Output: plot_*.png (150 dpi) and plot_*.svg in this folder.
"""
import json
import math
import os
import sys

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CALC = os.path.normpath(os.path.join(HERE, "..", "calc"))
sys.dont_write_bytecode = True
sys.path.insert(0, CALC)
import r7_calc as R  # noqa: E402  (module-level BRD parse only; main() is guarded)

with open(os.path.join(CALC, "r7_calc_out.json")) as f:
    J = json.load(f)

# ---------------------------------------------------------------------------------------------------------------------
# Style: neutral grays, distinct line styles and hatches so every figure reads in grayscale.
# ---------------------------------------------------------------------------------------------------------------------
INK = "#222222"
MID = "#666666"
LIGHT = "#AAAAAA"
FAINT = "#DDDDDD"
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9, "axes.titlesize": 10, "axes.labelsize": 9,
    "axes.edgecolor": MID, "axes.labelcolor": INK, "xtick.color": MID, "ytick.color": MID,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": "#EEEEEE",
    "grid.linewidth": 0.6, "legend.frameon": False, "legend.fontsize": 8, "svg.fonttype": "none",
})


def source(fig, text):
    fig.text(0.01, 0.005, "Source: " + text, fontsize=6.5, color=MID, ha="left", va="bottom")


def save(fig, name):
    fig.savefig(os.path.join(HERE, name + ".png"), dpi=150)
    fig.savefig(os.path.join(HERE, name + ".svg"))
    plt.close(fig)
    print("wrote", name + ".png/.svg")


def check(label, got, want, tol):
    if abs(got - want) > tol:
        raise SystemExit("cross-check FAILED: %s = %.4f, calc JSON %.4f" % (label, got, want))
    print("  check %-40s %.4f (JSON %.4f)" % (label, got, want))


# =====================================================================================================================
# P1 hard short: U101 IN peak vs W1/W2 lead length (r7_calc.in_spike, the r3 H.19(b) model ported unchanged)
# =====================================================================================================================
def p1():
    hs = J["l"]["hard_short"]
    pj = J["p"]
    VBR = 36.0                                                      # D107 VBR(min), r7_calc.py H.23(l) / H.23(p)
    build = R.W12_BUILD                                             # (290, 300, 310) mm, D-F3

    def worst(Lmm, lpm):                                            # H.23(p) spike_worst(): the H.19(b) source grid
        return R.spike_worst(lpm * 1e-6 * Lmm / 1000.0)[0]

    for row in hs:                                                  # the r7 rows at 0.5 uH/m (H.23(l))
        check("r7 IN peak at %.1f mm, 0.5 uH/m" % row["lead_mm"], worst(row["lead_mm"], 0.5), row["in_peak_V"], 0.01)
    # r8 wire (H.23(p)): lower bound s = OD min 1.60 mm, a = 19/32 bundle radius, helix factor at OD max and 20 mm pitch;
    # upper bound s = OD max 1.75 mm, a = solid 20 AWG radius, k = 1, + 0.10 uH/m internal (r7_calc.sec_p()).
    a_hi = max(pj["conductor_radii"].values())
    a_lo = min(pj["conductor_radii"].values())
    od0, od1 = pj["recommended"]["od"]
    k = math.sqrt(1 + (math.pi * od1 / R.TWIST_P[0]) ** 2)
    lmin = R.lprime(od0, 5 * R.awg_d(32) / 2) / k * 1e6
    lmax = (R.lprime(od1, R.awg_d(20) / 2) + 0.10e-6) * 1e6
    check("r8 L' min (uH/m)", lmin, pj["recommended"]["lprime_uH_m"][0], 0.001)
    check("r8 L' max (uH/m)", lmax, pj["recommended"]["lprime_uH_m"][1], 0.001)
    check("conductor radius a_hi used", 5 * R.awg_d(32) / 2, a_hi, 0.001)
    check("conductor radius a_lo used", R.awg_d(20) / 2, a_lo, 0.001)
    for Lmm in build:
        rr = pj["recommended"]["rows"]["%.1f" % Lmm]
        check("r8 IN peak at %.0f mm, L' min" % Lmm, worst(Lmm, lmin), rr["in_peak_Lmin"], 0.01)
        check("r8 IN peak at %.0f mm, L' max" % Lmm, worst(Lmm, lmax), rr["in_peak_Lmax"], 0.01)
    ptfe = pj["candidates"][0]                                      # thin-wall PTFE/ETFE, excluded in r8
    kp = math.sqrt(1 + (math.pi * ptfe["od"][1] / R.TWIST_P[0]) ** 2)
    lptfe = R.lprime(ptfe["od"][0], 5 * R.awg_d(32) / 2) / kp * 1e6
    check("PTFE L' min (uH/m)", lptfe, ptfe["lprime_uH_m"][0], 0.001)
    check("PTFE IN peak at 290 mm", worst(290.0, lptfe), ptfe["in_peak_290_Lmin"], 0.01)

    L = np.arange(150.0, 350.0 + 1e-9, 2.5)
    fig, ax = plt.subplots(figsize=(6.8, 4.3))
    fig.subplots_adjust(left=0.1, right=0.97, top=0.91, bottom=0.16)
    ax.axvspan(build[0], build[2], color=FAINT, lw=0, label="fixed W1/W2 build 0.30 m +- 10 mm (D-F3)")
    vmin = np.array([worst(x, lmin) for x in L])
    vmax = np.array([worst(x, lmax) for x in L])
    v05 = np.array([worst(x, 0.5) for x in L])
    vpt = np.array([worst(x, lptfe) for x in L])
    ax.fill_between(L, vmax, vmin, color=MID, alpha=0.18, lw=0)
    ax.plot(L, vmin, "-", color=INK, lw=2.0, label="r8 wire, L' min %.3f uH/m (spike-critical)" % lmin)
    ax.plot(L, vmax, "--", color=INK, lw=1.4, label="r8 wire, L' max %.3f uH/m" % lmax)
    ax.plot(L, vpt, ":", color=MID, lw=1.6, label="thin-wall PTFE, L' min %.3f uH/m (excluded)" % lptfe)
    ax.plot(L, v05, "-.", color=LIGHT, lw=1.2, label="r7 basis 0.5 uH/m (unsourced, superseded)")
    ax.axhline(VBR, color=INK, lw=1.0, ls=(0, (6, 2)))
    ax.text(200, VBR + 0.12, "D107 VBR(min) 36 V", ha="left", va="bottom", fontsize=8, color=INK)
    # crossing of the r8 L' min curve with 36 V (walkthrough recomputation, not a calc row)
    lo, hi = 150.0, 290.0
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if worst(mid, lmin) > VBR:
            lo = mid
        else:
            hi = mid
    x36 = 0.5 * (lo + hi)
    rows = {Lmm: pj["recommended"]["rows"]["%.1f" % Lmm] for Lmm in build}
    ax.plot([290.0], [rows[290.0]["in_peak_Lmin"]], "o", ms=5, mfc="white", mec=INK)
    ax.annotate("290 mm: %.2f V\n(margin %.2f V, H.23(p))" % (rows[290.0]["in_peak_Lmin"], rows[290.0]["margin"]),
                (290.0, rows[290.0]["in_peak_Lmin"]), xytext=(-14, 30), textcoords="offset points", fontsize=7,
                ha="right", arrowprops=dict(arrowstyle="-", color=MID, lw=0.7))
    ax.plot([290.0], [ptfe["in_peak_290_Lmin"]], "s", ms=5, mfc="white", mec=MID)
    ax.annotate("PTFE at 290 mm: %.2f V" % ptfe["in_peak_290_Lmin"], (290.0, ptfe["in_peak_290_Lmin"]),
                xytext=(8, 4), textcoords="offset points", fontsize=7, color=MID)
    ax.axvline(x36, color=MID, lw=0.8, ls=(0, (2, 2)))
    ax.text(x36 - 1.5, 30.75, "r8 L' min\nreaches 36 V\nat %.0f mm" % x36, fontsize=7, ha="right", va="bottom")
    ax.set_xlim(150, 352)
    ax.set_ylim(30.5, 41.5)
    ax.set_xlabel("W1/W2 lead length (mm)")
    ax.set_ylabel("U101 IN peak (V)")
    ax.set_title("Hard short at EVM J1: U101 IN peak against W1/W2 lead length (r8 wire)")
    ax.legend(loc="upper right", fontsize=7)
    source(fig, "r7_calc.py H.23(p): L' = (mu0/pi) acosh(s/2a), 20 AWG 19/32 or 7/28, OD 1.60-1.75 mm, pitch 20-25 mm;\n"
                "spike_worst() = H.19(b) in_spike, V0 16/22 V, C_S 5/20 uF, L_IN 50/150 nH; 36 V crossing: this script")
    save(fig, "plot_hard_short")
    cut = {Lmm: (worst(Lmm, lmin), worst(Lmm, 0.5)) for Lmm in (hs[1]["lead_mm"], hs[0]["lead_mm"])}
    return dict(lmin=lmin, lmax=lmax, x36=x36, routes_r8_vs_r7=cut, ptfe=lptfe)


# =====================================================================================================================
# P2 3-D switched-conductor rule along the W1 round-lead run (r7_calc.sw3d)
# =====================================================================================================================
def p2():
    """r8 trunk profile (H.23(s)) and W5 stacking (H.23(t)): the built trunk bottom on the B1R ramp, the free span, the B3
    post and the off-CR descent, against the 3-D requirement at the r8 trunk half-width; the W5 ribbon above the trunk,
    each W5 sample projected onto its nearest trunk point (the overlap test of r7_calc.sec_s_t())."""
    S, T = J["s"], J["t"]
    P = R.WP
    h = R.paths_with_od(J["p"]["recommended"]["od"][1])[1]     # exact trunk half-width at the r8 OD (H.23(p)/(s))
    check("trunk half-width at the r8 W1/W2 OD", h, S["h_trunk"], 0.001)
    tb = 2 * h
    m = math.tan(math.radians(S["slope_deg"]))
    y0, z_top = S["toe_y"], S["b3_height"]
    zc = R.Z_CR_TOP
    trunk = [P["T1"], P["B1"], P["T2"], P["T3"], P["B3"], P["T4"], P["T5"], P["T6"], P["A1"]]
    sl = R.arclen(trunk)
    smp = R.sample_path(trunk)
    za = min(z_top, m * (R.RISER_Y_END - y0))
    sa = R.RISER_Y_END - P["T1"][1]                    # apex, along the x 25.80 run from T1
    s_b3n = sl[4] - R.ANCHOR_FP / 2                    # B3 post edge on the -s side
    check("B1R apex above the CR top", za, S["apex"], 0.002)

    def z_cr(s):                                       # r7_calc.sec_s_t() design(): built height above the CR top
        if s <= sa:
            return min(z_top, max(0.0, m * (s + P["T1"][1] - y0)))
        if s <= s_b3n:
            return za + (z_top - za) * (s - sa) / (s_b3n - sa)
        return z_top
    qe = tuple(S["off_support_end"])
    s_e = min(smp, key=lambda z: math.hypot(z[1][0] - qe[0], z[1][1] - qe[1]))[0]
    s_a1, z_hold = sl[-1], z_top + zc

    def bottom(s, q):                                  # trunk jacket bottom above the MB top
        if R.pip(q[0], q[1], R.OUTLINE):
            return zc + z_cr(s)
        return z_hold if s <= s_e else z_hold * (s_a1 - s) / (s_a1 - s_e)
    s_arr, need, bot, base, oncr = [], [], [], [], []
    for s, q in smp:
        nd, _ = R.z_need(q, h)
        on = R.pip(q[0], q[1], R.OUTLINE)
        s_arr.append(s), need.append(nd), bot.append(bottom(s, q)), base.append(zc if on else 0.0), oncr.append(on)
    s_arr, need, bot, base = map(np.array, (s_arr, need, bot, base))
    mask = np.array(oncr) & (need > 0)
    mg = bot[mask] - need[mask]
    check("trunk minimum margin on the CR", mg.min(), S["min_margin"], 0.002)
    check("trunk requirement maximum on the CR (above the CR top)", need[np.array(oncr)].max() - zc,
          S["max_req_above_cr"], 0.002)
    s_min = s_arr[mask][int(np.argmin(mg))]
    for ds, rq, bt in S["checkpoints"]:                # T-F-12 check points past B1
        sq = (P["B1"][1] - P["T1"][1]) + ds
        q = (25.80, P["T1"][1] + sq)
        check("check point +%.2f mm required" % ds, R.z_need(q, h)[0] - zc, rq, 0.002)
        check("check point +%.2f mm built" % ds, z_cr(sq), bt, 0.002)
    # W5 above the trunk (H.23(t)): W5 path from r7_calc.sec_s_t(), fold Z_CR_TOP + W5_FOLD, ribbon 0.9 mm (RIB_T)
    w5 = [(40.75, 46.83), P["F1"], P["F2"], P["S3"], P["F3"], P["F4"], P["A1R"]]
    w5s = R.sample_path(w5, 0.1)
    full = [P["T0"], P["J67"], P["T1"]] + trunk[1:]
    sfull = R.sample_path(full, 0.1)
    off0 = R.arclen(full)[2]
    w5_end = R.arclen(w5)[-1]
    wrows = []
    for s, q in w5s:
        d, st, qt = min(((math.hypot(q[0] - b[0], q[1] - b[1]), a, b) for a, b in sfull), key=lambda z: z[0])
        if d >= R.RIBBON_W / 2 + h:
            continue
        zt = bottom(st - off0, qt) if st >= off0 else zc
        own = R.z_need(q, R.RIBBON_W / 2)[0]
        fold = zc + R.W5_FOLD if s < w5_end - 1e-9 else 0.0
        zb = max(fold, own, zt + tb)
        wrows.append((st - off0, zb, own))
    wrows.sort()
    top = max(r[1] for r in wrows) + R.RIB_T
    check("W5 stack top", top, T["stack_top"], 0.002)
    ws = np.array([r[0] for r in wrows if r[0] >= 0])
    wb = np.array([r[1] for r in wrows if r[0] >= 0])

    fig, ax = plt.subplots(figsize=(7.6, 4.6))
    fig.subplots_adjust(left=0.08, right=0.98, top=0.91, bottom=0.15)
    ax.fill_between(s_arr, 0, base, step="mid", color=FAINT, lw=0, label="lead base (CR top on the CR, MB top off it)")
    ax.fill_between(s_arr, bot, bot + tb, color="#C9C9C9", lw=0, label="trunk round bundle T_b %.3f mm" % tb)
    ax.plot(s_arr, bot, "-", color=INK, lw=1.9, label="trunk jacket bottom, built (B1R, span, B3 post)")
    need_p = np.where(need > 0, need, np.nan)
    ax.plot(s_arr, need_p, "--", color=INK, lw=1.3, label="required jacket bottom (3-D 10 mm rule, h %.3f mm)" % h)
    ax.fill_between(ws, wb, wb + R.RIB_T, color="#7A7A7A", lw=0, label="W5 ribbon (0.9 mm ASSUMPTION), projected")
    ax.axhline(R.H_LFC, color=MID, lw=0.9, ls=":")
    ax.text(6.0, R.H_LFC + 0.15, "L-FC top %.1f mm (ASSUMPTION)" % R.H_LFC, fontsize=7, color=MID)
    ax.text(6.0, zc - 0.2, "CR top %.3f mm" % zc, fontsize=7, color=MID, va="top")
    s_edge = s_arr[~np.array(oncr)].min()
    marks = [("toe/T1", 0.0), ("B1R apex", sa), ("B3 post", sl[4]), ("CR edge x 37.56", s_edge),
             ("support end (40.75, 71.10)", s_e), ("A1", s_a1)]
    for lab, x in marks:
        ax.axvline(x, color=MID, lw=0.7, ls=(0, (1, 2)))
        ax.text(x + 0.25, 0.5, lab, rotation=90, fontsize=6.8, va="bottom", color=INK)
    ax.axvspan(s_edge, s_a1, ymin=0.0, ymax=1.0, color="#F4F4F4", lw=0, zorder=-2)
    ax.text(33.0, 23.4, "off the CR: support TODO(design: T-A-06 dry fit);\ndescent shown as information "
            "(H.23(s))", fontsize=6.8, ha="center", va="top", color=MID)
    ax.plot([s_min], [need[mask][int(np.argmin(mg))]], "o", ms=5, mfc="white", mec=INK)
    ax.annotate("minimum margin %.3f mm\nat T2 (25.80, 69.60)" % S["min_margin"], (s_min, need[mask][int(np.argmin(mg))]),
                xytext=(17, -36), textcoords="offset points", fontsize=7, ha="left", va="top",
                arrowprops=dict(arrowstyle="-", color=MID, lw=0.7))
    ax.annotate("stack top %.3f mm at (%.2f, %.2f)" % (T["stack_top"], T["stack_top_at"][0], T["stack_top_at"][1]),
                (sl[4], top), xytext=(-190, 12), textcoords="offset points", fontsize=7,
                arrowprops=dict(arrowstyle="-", color=MID, lw=0.7))
    ax.set_xlim(-0.6, s_a1 + 0.6)
    ax.set_ylim(0, 31)
    ax.set_xlabel("distance along the trunk from T1 (25.80, 62.60) to A1 (60.50, 73.50) (mm)")
    ax.set_ylabel("height above the MB top (mm)")
    ax.set_title("Trunk and W5 heights under the 3-D switched-conductor rule (r8)")
    ax.legend(loc="upper left", fontsize=6.6, ncol=2)
    source(fig, "r7_calc.py H.23(s) (B1R 65 deg, toe y 62.54, apex, B3 post 10.7 mm, support end) and H.23(t) "
                "(W5 over the trunk);\n"
                "z_need() at the r8 half-width; H_LFC 5.0 mm ASSUMPTION")
    save(fig, "plot_lead_height_profile")
    return dict(run=s_a1, sa=sa, sB3=sl[4], s_edge=s_edge, s_e=s_e, min_margin=mg.min(), s_min=s_min, top=top,
                w5_min_margin=min(r[1] - r[2] for r in wrows if r[2] > 0))


# =====================================================================================================================
# P3 tap-wire lengths r6 vs r7
# =====================================================================================================================
def p3():
    g = J["g"]
    asg = g["assignment"]
    taps = [t for t in asg if t in R.SUM20]            # the calc's 20-tap set (T18, T19, F24 are options)
    r6 = np.array([asg[t][3] for t in taps])
    r7 = np.array([asg[t][6] for t in taps])
    check("20-tap r6 sum", r6.sum(), g["sum_r6"], 0.01)
    check("20-tap r7 dressed sum", r7.sum(), g["sum_r7_dressed"], 0.01)
    order = np.argsort(-r6)
    fig, ax = plt.subplots(figsize=(7.4, 4.0))
    fig.subplots_adjust(left=0.08, right=0.98, top=0.9, bottom=0.2)
    x = np.arange(len(taps))
    w = 0.4
    ax.bar(x - w / 2, r6[order], w * 0.92, color=LIGHT, label="r6 straight basis (sum %.1f mm)" % g["sum_r6"])
    ax.bar(x + w / 2, r7[order], w * 0.92, color=INK, label="r7 dressed (sum %.1f mm)" % g["sum_r7_dressed"])
    ax.set_xticks(x)
    ax.set_xticklabels(["%s\n%s" % (taps[i], asg[taps[i]][0]) for i in order], fontsize=6.5)
    ax.set_ylabel("tap-wire length (mm)")
    ax.set_xlabel("tap (pad), sorted by r6 length")
    ax.grid(axis="x", visible=False)
    ax.set_title("Tap-wire length per tap: r6 straight basis against r7 dressed (the %d-tap set)" % len(taps))
    ax.legend(loc="upper right")
    source(fig, "r7_calc_out.json H.23(g) assignment (r6 basis and r7 dressed length per tap); sums sum_r6, "
                "sum_r7_dressed")
    save(fig, "plot_tap_lengths")
    d = r6 - r7
    return dict(n=len(taps), sum6=g["sum_r6"], sum7=g["sum_r7_dressed"], longest6=(taps[int(np.argmax(r6))], r6.max()),
                longest7=(taps[int(np.argmax(r7))], r7.max()), grew=[t for t, v in zip(taps, d) if v < 0])


# =====================================================================================================================
# P4 per-region area booking
# =====================================================================================================================
def p4():
    reg = J["e2"]["regions"]
    names = ["band", "interior", "tab X", "tab Y", "tab Y bottom"]
    labels = ["band\n(top)", "interior\n(top)", "tab X\n(top)", "tab Y\n(top)", "tab Y\n(bottom)"]
    U = [reg[n]["U"] for n in names]
    sums = {n: reg[n]["sum"] for n in names}
    # r8: the B1R wedge replaces the 3 x 3 mm B1 spot in the footprint interior (H.23(s) interior_U)
    u7_int = U[1]
    U[1] = J["s"]["interior_U"]
    sums["interior"] = reg["interior"]["sum"] - R.ANCHOR_FP ** 2 + J["s"]["block_area"]
    check("r8 interior booking", 100 * sums["interior"] / J["e2"]["areas"]["interior"], U[1], 0.01)
    labels[1] = "interior\n(top, r8)"
    lim = 100.0 * R.U_TARGET
    fig, ax = plt.subplots(figsize=(5.8, 3.8))
    fig.subplots_adjust(left=0.12, right=0.97, top=0.9, bottom=0.2)
    bars = ax.bar(range(5), U, 0.7, color=[MID, MID, MID, MID, LIGHT])
    for i, (b, n) in enumerate(zip(bars, names)):
        ax.text(b.get_x() + b.get_width() / 2, U[i] - 2.0, "%.2f %%\n%.1f /\n%.1f\nmm2" % (U[i], sums[n],
                J["e2"]["areas"][n]), ha="center", va="top", fontsize=7, color="white" if i < 4 else INK)
    ax.axhline(lim, color=INK, lw=1.0, ls="--")
    ax.text(4.45, lim + 1.5, "%.0f %% limit" % lim, ha="right", fontsize=8)
    ax.set_xticks(range(5))
    ax.set_xticklabels(labels)
    ax.set_ylim(0, 100)
    ax.set_ylabel("courtyard area booked U (%)")
    ax.grid(axis="x", visible=False)
    ax.set_title("Area booking per A.8 region of the carrier (r8)")
    ax.text(1, U[1] + 1.5, "r7 (B1 spot): %.1f %%" % u7_int, ha="center", fontsize=7)
    source(fig, "r7_calc_out.json H.23(e2) regions (courtyard sum / region area); interior with B1R: H.23(s);\n"
                "limit U_TARGET in r7_calc.py")
    save(fig, "plot_area_booking")
    return dict(zip(names, U)), lim


# =====================================================================================================================
# P5 feet: bed stiffness vs bed gap; T-A-09 pull stress vs 30 g service stress
# =====================================================================================================================
def p5():
    i = J["i"]
    A = {"FT1 (tab X)": i["ft1"]["size"][0] * i["ft1"]["size"][1],
         "FT2 (tab Y)": i["ft2"]["size"][0] * i["ft2"]["size"][1]}
    # cross-check k = E A / t against the calc's k_s list (E_RTV x T_BED order)
    for (nm, a), tn in zip(A.items(), ("tab X", "tab Y")):
        ks = [e * a / t for e in R.E_RTV for t in R.T_BED]
        for got, want in zip(ks, i["ks"][tn]["all"]):
            check("k_s %s" % nm, got, want, 0.01)
    t = np.linspace(0.10, 0.60, 201)
    gate = i["foot_height"]["gate"]
    fig, axs = plt.subplots(1, 2, figsize=(9.6, 4.9))
    fig.subplots_adjust(left=0.07, right=0.98, top=0.88, bottom=0.31, wspace=0.28)
    ax = axs[0]
    ax.axvspan(gate[0], gate[1], color=FAINT, lw=0, label="PM4 (2d) gate %.2f-%.2f mm" % tuple(gate))
    sty = {"FT1 (tab X)": ("-", INK), "FT2 (tab Y)": ("--", MID)}
    for nm, a in A.items():
        ls, c = sty[nm]
        lo, hi = (min(R.E_RTV) * a / t, max(R.E_RTV) * a / t)
        ax.fill_between(t, lo, hi, color=c, alpha=0.12, lw=0)
        ax.plot(t, lo, ls, color=c, lw=1.2, label="%s, %.1f mm2, E %.0f MPa" % (nm, a, min(R.E_RTV)))
        ax.plot(t, hi, ls, color=c, lw=2.0, label="%s, %.1f mm2, E %.0f MPa" % (nm, a, max(R.E_RTV)))
    ax.axvline(R.T_BED[1], color=MID, lw=0.8, ls=":")
    ax.text(R.T_BED[1] + 0.005, 2200, "nominal %.2f mm" % R.T_BED[1], fontsize=7, va="top")
    # r8 foot-bond fallback (H.23(r)): an UNCHANGED foot over a sheet cut-out sees the gated band shifted by t_rm
    rr = J["r"]
    t_rm = rr["t_rm"][0]
    fb = (gate[0] + t_rm, gate[1] + t_rm)
    ax.axvspan(fb[0], fb[1], ymin=0.0, ymax=0.12, facecolor="none", edgecolor=INK, hatch="////", lw=0,
               label="foot-bond fallback, unchanged foot: bed %.3f-%.3f mm" % fb)
    kfb, kg = {}, {}
    for nm, a in A.items():
        kfb[nm] = min(R.E_RTV) * a / fb[1]
        kg[nm] = min(R.E_RTV) * a / gate[1]
        ax.plot([fb[1]], [kfb[nm]], "v", ms=5, mfc="white", mec=INK, zorder=5)
    check("fallback FT1 k_s min", kfb["FT1 (tab X)"], 11.13, 0.01)   # H.23(r) text row
    check("fallback FT2 k_s min", kfb["FT2 (tab Y)"], 27.83, 0.01)   # H.23(r) text row
    ax.set_yscale("log")
    ax.set_ylim(8, 3000)
    ax.set_xlim(0.10, 0.60)
    ax.set_xlabel("RTV bed gap t (mm)")
    ax.set_ylabel("bed stiffness k = E A / t (N/mm)")
    ax.set_title("(a) FT1/FT2 bed stiffness against bed gap")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.15), ncol=2, fontsize=6.5)
    fig.text(0.07, 0.035, "Triangles: the unchanged foot at the fallback bed %.3f mm with E 1 MPa: FT1 %.2f N/mm and "
             "FT2 %.2f N/mm, x%.3f of the gated minimum %.2f / %.2f N/mm.\n"
             "The re-made foot h_f' = %.2f mm + t_rm "
             "(%.3f mm at t_rm %.3f mm) returns the bed to the nominal %.2f mm (H.23(r))."
             % (fb[1], kfb["FT1 (tab X)"], kfb["FT2 (tab Y)"], kfb["FT1 (tab X)"] / kg["FT1 (tab X)"],
                kg["FT1 (tab X)"], kg["FT2 (tab Y)"], R.H_F, rr["h_f_new"][0], t_rm, R.T_BED[1]),
             fontsize=6.8, color=INK, va="bottom")
    ax = axs[1]
    pu = i["pulls"]
    kslab = ["k_s min", "k_s nom (E 1)", "k_s nom (E 3)", "k_s max"]
    x = np.arange(4)
    w = 0.2
    for j, (tn, off) in enumerate((("tab X", -1.5), ("tab Y", 0.5))):
        p = pu["tabs"][tn]
        ax.bar(x + off * w, p["s30_kPa"], w * 0.9, color=LIGHT if j else MID,
               label="%s: 30 g service stress" % tn, hatch=None if j == 0 else "//", edgecolor="white")
        ax.bar(x + (off + 1) * w, p["rec_kPa"], w * 0.9, color=INK if j == 0 else "#444444",
               label="%s: %.1f N pull" % (tn, pu["recommended_N"]), hatch=None if j == 0 else "\\\\",
               edgecolor="white")
    ax.set_xticks(x)
    ax.set_xticklabels(["%s\nX %.0f N/mm\nY %.0f N/mm" % (k, a, b) for k, a, b in
                        zip(kslab, [min(i["ks"]["tab X"]["all"])] + i["ks"]["tab X"]["nom"] + [max(i["ks"]["tab X"]["all"])],
                            [min(i["ks"]["tab Y"]["all"])] + i["ks"]["tab Y"]["nom"] + [max(i["ks"]["tab Y"]["all"])])],
                       fontsize=6.5)
    ax.set_ylabel("bed stress (kPa)")
    ax.grid(axis="x", visible=False)
    ax.set_title("(b) T-A-09 pull %.1f N against the 30 g service stress" % pu["recommended_N"])
    ax.legend(loc="upper left", fontsize=6.8)
    fig.suptitle("Far-end support feet FT1/FT2: bed stiffness and the T-A-09 pull", fontsize=10)
    source(fig, "r7_calc.py H.23(i): E_RTV, T_BED, foot sizes, k_s, PM4 (2d) gate; pulls (tip-load basis, "
                "recommended pull); H.23(r): foot-bond fallback (t_rm 0.125 mm)")
    save(fig, "plot_feet")
    return A, pu


# =====================================================================================================================
# P6 E1 + E8 + C205 series loop impedance
# =====================================================================================================================
def p6():
    f = np.logspace(5, 7, 1200)
    w = 2 * np.pi * f
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    fig.subplots_adjust(left=0.11, right=0.97, top=0.9, bottom=0.17)
    out = {}
    for Lmm, ls in ((85.0, "-"), (90.0, "--")):
        Lm = Lmm * 1e-3
        Ll = R.loop_L(Lm, 5e-3)
        rl = R.R28 * 2 * Lm + R.ESR205
        jr = J["k"]["resonance"]["%.1f" % Lmm]
        f0 = 1 / (2 * math.pi * math.sqrt(Ll * R.C205))
        check("E1 loop L (nH) l %.0f mm" % Lmm, Ll * 1e9, jr["L_nH"], 0.01)
        check("E1 loop f0 (MHz) l %.0f mm" % Lmm, f0 / 1e6, jr["f0_MHz"], 0.001)
        X = w * Ll - 1 / (w * R.C205)
        for rext, c, lw, lab in ((0.0, INK, 1.6, "without R276"), (R.R276, MID, 1.6, "with R276 %.0f ohm" % R.R276)):
            ax.loglog(f, np.hypot(rl + rext, X), ls, color=c, lw=lw,
                      label="l %.0f mm, %s (Q %.2f)" % (Lmm, lab, jr["Q_R276"] if rext else jr["Q"]))
        out[Lmm] = (Ll * 1e9, f0 / 1e6, rl, jr)
    f_lo, f_hi = J["k"]["resonance"]["90.0"]["f0_MHz"], J["k"]["resonance"]["85.0"]["f0_MHz"]
    ax.axvspan(f_lo * 1e6, f_hi * 1e6, color=FAINT, lw=0)
    ax.text(f_lo * 1e6 * 0.97, 25, "f0 %.2f-%.2f MHz" % (f_lo, f_hi), ha="right", fontsize=7.5)
    ax.axvline(1.5e6, color=MID, lw=0.8, ls=":")
    ax.text(1.55e6, 25, "BQ25798 fsw 1.5 MHz", fontsize=7, color=MID)
    ax.set_ylim(0.03, 60)
    ax.set_xlim(1e5, 1e7)
    ax.set_xlabel("frequency (Hz)")
    ax.set_ylabel("|Z| of the series loop (ohm)")
    ax.set_title("E1 + E8 + C205 series loop impedance, with and without R276")
    ax.legend(loc="lower left", fontsize=7)
    source(fig, "r7_calc.py H.23(k): loop_L (two-wire, s 5 mm, 28 AWG), C205 100 nF, ESR 20 mOhm ASSUMPTION, "
                "R = 28 AWG DC x 2l")
    save(fig, "plot_e1_resonance")
    return out


# =====================================================================================================================
# P7 review convergence
# =====================================================================================================================
def p7():
    # Counts exist only in the review records:
    #   round 3 rounds 1-6 totals and the round-6 majors: round4/review_loop.md section 4.1 table, row "1-6" (line 179)
    #   round 7 (60 / 0 blocker / 10 major / 50 minor): round4/review_loop.md section 2.2 table (lines 78-84)
    #   final audit (13 / 0 / 3 / 10): round4/review_loop.md lines 157-160; charger-design/run-001-2026-11-10.md
    ROUNDS = ["r3 rd 1", "r3 rd 2", "r3 rd 3", "r3 rd 4", "r3 rd 5", "r3 rd 6", "r4 rd 7", "final\naudit"]
    TOTAL = [53, 44, 34, 32, 24, 16, 60, 13]
    MAJOR = [None, None, None, None, None, 9, 10, 3]
    MINOR = [None, None, None, None, None, None, 50, 10]
    fig, ax = plt.subplots(figsize=(6.6, 4.0))
    fig.subplots_adjust(left=0.1, right=0.97, top=0.9, bottom=0.2)
    x = np.arange(len(ROUNDS))
    for k in range(len(x)):
        tot, mj, mn = TOTAL[k], MAJOR[k], MINOR[k]
        if mj is None:
            ax.bar(x[k], tot, 0.6, color="white", edgecolor=MID, hatch="..", lw=0.8)
        else:
            ax.bar(x[k], mj, 0.6, color=INK)
            rest = tot - mj
            if mn is not None:
                ax.bar(x[k], mn, 0.6, bottom=mj, color=LIGHT)
            else:
                ax.bar(x[k], rest, 0.6, bottom=mj, color="white", edgecolor=MID, hatch="..", lw=0.8)
        ax.text(x[k], tot + 1, str(tot), ha="center", fontsize=8)
    ax.axvline(5.5, color=MID, lw=0.9, ls="--")
    ax.text(5.6, 78, "round-4 content\n(carrier extension, feet,\ntap field, dressing)", fontsize=7, va="top")
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=INK, label="major"), Patch(color=LIGHT, label="minor"),
                       Patch(facecolor="white", edgecolor=MID, hatch="..", label="severity not split in the record"),
                       Patch(color="white", label="blocker: 0 in round 7 and the audit")], loc="upper right",
              fontsize=7, bbox_to_anchor=(0.72, 1.0))
    ax.set_xticks(x)
    ax.set_xticklabels(ROUNDS, fontsize=8)
    ax.set_ylim(0, 80)
    ax.set_ylabel("verified findings")
    ax.grid(axis="x", visible=False)
    ax.set_title("Verified findings per review round")
    source(fig, "round4/review_loop.md sections 2.2, 3 and 4.1; round3/review_loop.md; "
                "charger-design/run-001-2026-11-10.md")
    save(fig, "plot_review_convergence")


if __name__ == "__main__":
    print("P1"); r1 = p1(); print(r1)
    print("P2"); print(p2())
    print("P3"); print(p3())
    print("P4"); print(p4())
    print("P5"); A, pu = p5(); print(A)
    print("P6"); print(p6())
    print("P7"); p7()
