"""Plots for the round-4 (r7) design walkthrough.

Every plotted result is read from ../calc/r7_calc_out.json (revision 4) or recomputed with a function imported from
../calc/r7_calc.py (in_spike, sw3d, loop_L and the module constants). Importing r7_calc parses the MB .brd at module
level but does not run main(), so no calc output file is rewritten. Values that exist only in the design text or the
review records are cited constants with the source line named beside them.

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
    v0s, css, lins = (16.0, 22.0), (5e-6, 20e-6), (50e-9, 150e-9)    # r7_calc.sec_l() worst-case corners
    CIN = 3.4e-6                                                    # r7_calc.sec_l() C_IN 3.4 uF
    VBR = 36.0                                                      # D107 VBR(min), r7_calc.sec_l() / H.23(l)
    build = R.W12_BUILD                                             # (290, 300, 310) mm, D-F3

    def worst(Lmm, lpm):
        return max(R.in_spike(v0, cs, lin, CIN, lout=lpm * 1e-6 * Lmm / 1000.0)[0]
                   for v0 in v0s for cs in css for lin in lins)

    for row in hs:                                                  # reproduce the calc rows at 0.5 uH/m
        check("IN peak at %.1f mm" % row["lead_mm"], worst(row["lead_mm"], 0.5), row["in_peak_V"], 0.01)

    L = np.arange(150.0, 350.0 + 1e-9, 5.0)
    # 0.5 uH/m is the calc basis (145-155 nH at 0.30 m +- 10 mm, design H.5 row); 0.33 and 0.62 uH/m are the
    # 20 AWG pair range of the CHG-R1-D04 verifier (charger-design/run-001-2026-11-10.md line 124), plotted as
    # sensitivity bounds; they are not design values.
    series = [(0.33, ":", LIGHT), (0.5, "-", INK), (0.62, "--", MID)]
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    fig.subplots_adjust(left=0.11, right=0.97, top=0.9, bottom=0.17)
    ax.axvspan(build[0], build[2], color=FAINT, lw=0, label="fixed W1/W2 build 0.30 m +- 10 mm")
    res = {}
    for lpm, ls, c in series:
        v = [worst(x, lpm) for x in L]
        res[lpm] = v
        ax.plot(L, v, ls, color=c, lw=1.8, label="lead %.2f uH/m" % lpm)
    ax.axhline(VBR, color=INK, lw=1.0, ls="-.")
    ax.text(352, VBR + 0.1, "D107 VBR(min) 36 V", ha="right", va="bottom", fontsize=8, color=INK)
    for row in (hs[0], hs[1]):
        ax.axvline(row["lead_mm"], color=MID, lw=0.8, ls=(0, (2, 2)))
        ax.plot([row["lead_mm"]], [row["in_peak_V"]], "o", ms=5, mfc="white", mec=INK)
    ax.text(hs[1]["lead_mm"] - 1.5, 31.55, "r7 rev-2 W1\nroute\n%.1f mm:\n%.1f V" % (hs[1]["lead_mm"], hs[1]["in_peak_V"]),
            fontsize=7, color=INK, ha="right", va="bottom")
    ax.annotate("rev-4 shortest W1\nroute %.1f mm\n%.1f V" % (hs[0]["lead_mm"], hs[0]["in_peak_V"]),
                (hs[0]["lead_mm"], hs[0]["in_peak_V"]), xytext=(6, 14), textcoords="offset points", fontsize=7,
                color=INK)
    ax.plot([hs[3]["lead_mm"]], [hs[3]["in_peak_V"]], "s", ms=5, mfc="white", mec=INK)
    ax.annotate("300 mm: %.1f V" % hs[3]["in_peak_V"], (hs[3]["lead_mm"], hs[3]["in_peak_V"]),
                xytext=(6, 8), textcoords="offset points", fontsize=7)
    ax.set_xlim(150, 352)
    ax.set_xlabel("W1/W2 lead length (mm)")
    ax.set_ylabel("U101 IN peak (V)")
    ax.set_title("Hard short at EVM J1: U101 IN peak against W1/W2 lead length")
    ax.legend(loc="upper right", bbox_to_anchor=(1.0, 0.86))
    source(fig, "r7_calc.py H.23(l), in_spike() = r3_calc.py H.19(b); worst of V0 16/22 V, C_S 5/20 uF, "
                "L_IN 50/150 nH; C_IN 3.4 uF")
    save(fig, "plot_hard_short")
    return {k: (min(v), max(v)) for k, v in res.items()}, {lpm: [worst(x, lpm) for x in (290.0, 310.0)]
                                                           for lpm, _, _ in series}


# =====================================================================================================================
# P2 3-D switched-conductor rule along the W1 round-lead run (r7_calc.sw3d)
# =====================================================================================================================
def p2():
    path = R.w_paths()["W1"]
    ivs, _ = R.sw3d(path, "W1")
    iv = ivs[0]
    jv = J["l"]["rev4"]["sw3d"]["W1"][0]
    check("W1 run start s (B1)", iv["s0"], jv["s"][0], 0.002)
    check("W1 run end s", iv["s1"], jv["s"][1], 0.002)
    check("W1 peak requirement", iv["need"], jv["need"], 0.002)
    s = np.array([p[0] for p in iv["prof"]]) - iv["s0"]
    need = np.array([p[2] for p in iv["prof"]])
    zb = np.array([p[3] for p in iv["prof"]])
    sl = R.arclen([q for q, _ in path])
    pts = [q for q, _ in path]
    sB3 = sl[pts.index(tuple(R.WP["B3"]))] - iv["s0"]
    fig, ax = plt.subplots(figsize=(6.6, 4.0))
    fig.subplots_adjust(left=0.1, right=0.97, top=0.9, bottom=0.17)
    ax.fill_between(s, 0, zb, step="mid", color=FAINT, lw=0, label="lead base (CR top on the CR, MB top off it)")
    ax.plot(s, need, "-", color=INK, lw=1.8, label="required jacket-bottom height (3-D 10 mm rule)")
    ax.axhline(R.Z_CR_TOP, color=MID, lw=1.0, ls="--")
    ax.text(1.2, R.Z_CR_TOP - 0.15, "CR top %.3f mm" % R.Z_CR_TOP, ha="left", va="top", fontsize=7.5, color=MID,
            bbox=dict(fc="white", ec="none", pad=0.4))
    ax.axhline(R.H_LFC, color=MID, lw=1.0, ls=":")
    ax.text(1.2, R.H_LFC + 0.15, "L-FC body top %.1f mm (ASSUMPTION; MS3)" % R.H_LFC,
            ha="left", va="bottom", fontsize=7.5, color=MID, bbox=dict(fc="white", ec="none", pad=0.4))
    w5 = J["j"]["w5_over_lfc_bottom"]
    ax.axhline(w5, color=LIGHT, lw=1.4, ls="-.")
    ax.text(0.3, w5 + 0.15, "W5 ribbon requirement >= %.2f mm" % w5, fontsize=7.5, color=INK)
    for lab, x in (("B1", 0.0), ("B3", sB3)):
        ax.axvline(x, color=INK, lw=0.8, ls=(0, (1, 2)))
        ax.text(x + 0.3, 6.2, lab + " post", rotation=90, fontsize=7.5, va="bottom")
    ax.plot([s[np.argmax(need)]], [need.max()], "o", ms=5, mfc="white", mec=INK)
    ax.annotate("peak %.2f mm\n(L-FC body, Eaton)" % need.max(), (s[np.argmax(need)], need.max()),
                xytext=(8, -4), textcoords="offset points", fontsize=7.5, va="top")
    ax.set_xlim(-0.5, s[-1] + 0.5)
    ax.set_ylim(0, 19.5)
    ax.set_xlabel("distance along the run from B1 (25.80, 64.50) to (50.45, 72.09) (mm)")
    ax.set_ylabel("height above the MB top (mm)")
    ax.set_title("W1 round-lead run: required height under the 3-D switched-conductor rule")
    ax.legend(loc="upper right", fontsize=7)
    source(fig, "r7_calc.py H.23(l) rev. 4, sw3d() on the W1 path (west group); H_LFC, Z_CR_TOP; "
                "W5 figure H.23(j)")
    save(fig, "plot_lead_height_profile")
    return dict(run=s[-1], peak=need.max(), sB3=sB3, need_B1=need[0], end=need[-1])


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
    lim = 100.0 * R.U_TARGET
    fig, ax = plt.subplots(figsize=(5.8, 3.8))
    fig.subplots_adjust(left=0.12, right=0.97, top=0.9, bottom=0.2)
    bars = ax.bar(range(5), U, 0.7, color=[MID, MID, MID, MID, LIGHT])
    for i, (b, n) in enumerate(zip(bars, names)):
        ax.text(b.get_x() + b.get_width() / 2, U[i] - 2.0, "%.2f %%\n%.1f /\n%.1f\nmm2" % (U[i], reg[n]["sum"],
                J["e2"]["areas"][n]), ha="center", va="top", fontsize=7, color="white" if i < 4 else INK)
    ax.axhline(lim, color=INK, lw=1.0, ls="--")
    ax.text(4.45, lim + 1.5, "%.0f %% limit" % lim, ha="right", fontsize=8)
    ax.set_xticks(range(5))
    ax.set_xticklabels(labels)
    ax.set_ylim(0, 100)
    ax.set_ylabel("courtyard area booked U (%)")
    ax.grid(axis="x", visible=False)
    ax.set_title("Area booking per A.8 region of the r7 carrier")
    source(fig, "r7_calc_out.json H.23(e2) regions (courtyard sum / region area); limit U_TARGET in r7_calc.py")
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
    fig, axs = plt.subplots(1, 2, figsize=(9.6, 4.0))
    fig.subplots_adjust(left=0.07, right=0.98, top=0.86, bottom=0.17, wspace=0.28)
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
    ax.text(R.T_BED[1] + 0.005, 11, "nominal %.2f mm" % R.T_BED[1], fontsize=7)
    ax.set_yscale("log")
    ax.set_ylim(8, 3000)
    ax.set_xlim(0.10, 0.60)
    ax.set_xlabel("RTV bed gap t (mm)")
    ax.set_ylabel("bed stiffness k = E A / t (N/mm)")
    ax.set_title("(a) FT1/FT2 bed stiffness against bed gap")
    ax.legend(loc="upper right", fontsize=6.5)
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
                "recommended pull)")
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
