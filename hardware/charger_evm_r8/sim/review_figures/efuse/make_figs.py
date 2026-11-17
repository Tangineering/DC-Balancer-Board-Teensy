"""Morning review 2026-11-14/15, section 4.5 (sim 5, efuse_decay): review figures.

Reads ONLY the existing result CSVs of sim/efuse_decay/results/ (no re-simulation) and writes three PNG
figures next to this script:

  fig_efuse_bands.png       U101 UVLO/OVP threshold bands (a_bands_corners.csv, a_bands_montecarlo.csv)
  fig_efuse_t12_vs_ievm.png FR-12(b1) worst time to 12.0 V against the EVM draw (b_decay_cases.csv), with the
                            T10 proof (b) 16.0 -> 8.0 V ranges quoted in MORNING_REVIEW_2026-11-14.md section 4.5
  fig_efuse_ratio.png       FR-12(a2) shorted-switch ratio ranges per node set (c_ratio_summary.csv; open-switch
                            worst from headline.txt / RESULTS.md section 4.3)
"""
import csv
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.normpath(os.path.join(HERE, "..", "..", "efuse_decay", "results"))
plt.rcParams.update({"font.size": 10})
CATS = [0.0, 0.1, 0.2, 0.391, 1.08, 2.31]


def read_csv(name):
    with open(os.path.join(RES, name), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------------------------------------
# Figure A: threshold bands
# ---------------------------------------------------------------------------------------------------------
def fig_bands():
    corners = {r["threshold"]: r for r in read_csv("a_bands_corners.csv")}
    mc = {r["threshold"]: r for r in read_csv("a_bands_montecarlo.csv")}
    # Design-document (D-67) bands: RESULTS.md section 4.1 Table 1, column "Design doc".
    doc = {"UVLO_rise": (9.46, 10.14), "UVLO_fall": (8.61, 9.53), "OVP_rise": (22.19, 24.41)}
    labels = {"UVLO_rise": "UVLO rising", "UVLO_fall": "UVLO falling",
              "OVP_rise": "OVP rising", "OVP_fall": "OVP falling"}
    # Reference levels: RESULTS.md section 4.1 (FR-30 10.2 V, clamp 22.28 V, BQ25798 24.0 / 25.2 V) and the
    # F.5 T10 proof (b) level 8.0 V (MORNING_REVIEW section 4.5; RESULTS.md section 4.1 UVLO falling bullet).
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.6), gridspec_kw={"width_ratios": [1, 1.25]})
    groups = [(axes[0], ["UVLO_fall", "UVLO_rise"], (7.6, 11.0),
               [(8.0, "T10 proof (b)\n8.0 V"), (10.2, "FR-30\n10.2 V")]),
              (axes[1], ["OVP_fall", "OVP_rise"], (19.3, 26.6),
               [(22.28, "clamp\n22.28 V"), (24.0, "BQ25798\nrec.\n24.0 V"), (25.2, "BQ25798\nOVP min\n25.2 V")])]
    for ax, keys, xlim, refs in groups:
        for i, k in enumerate(keys):
            c = corners[k]
            lo_l, hi_l = float(c["corner_min_leak320nA_V"]), float(c["corner_max_leak320nA_V"])
            lo_n, hi_n = float(c["corner_min_noleak_V"]), float(c["corner_max_noleak_V"])
            lo_m, hi_m = float(mc[k]["min_V"]), float(mc[k]["max_V"])
            typ = float(c["typ_noleak_V"])
            y = i * 1.0
            ax.barh(y + 0.22, hi_l - lo_l, left=lo_l, height=0.18, color="#e8a27c",
                    label="corners, +-320 nA leak" if i == 0 else None)
            ax.barh(y, hi_n - lo_n, left=lo_n, height=0.18, color="#7fb27f",
                    label="corners, no leak" if i == 0 else None)
            ax.barh(y - 0.22, hi_m - lo_m, left=lo_m, height=0.18, color="#7f9fd0",
                    label="Monte Carlo min-max (n = 4000)" if i == 0 else None)
            ax.plot([typ], [y], marker="|", color="k", ms=14, mew=2,
                    label="typical, no leak" if i == 0 else None)
            ax.text(lo_l - 0.04, y + 0.22, "%.3f" % lo_l, ha="right", va="center", fontsize=9)
            if k in ("OVP_rise", "UVLO_fall"):
                # Placed above the bar end so the label does not cross the 25.2 V or 10.2 V reference line.
                ax.text(hi_l, y + 0.33, "%.3f" % hi_l, ha="right", va="bottom", fontsize=9)
            else:
                ax.text(hi_l + 0.04, y + 0.22, "%.3f" % hi_l, ha="left", va="center", fontsize=9)
            if k in doc:
                d0, d1 = doc[k]
                ax.plot([d0, d1], [y - 0.42, y - 0.42], color="0.35", lw=2,
                        label="design document band (D-67)" if i == 1 else None)
                ax.text(d1 + 0.04, y - 0.42, "doc %.2f-%.2f" % (d0, d1), fontsize=9, va="center",
                        color="0.35")
        for xv, txt in refs:
            ax.axvline(xv, color="k", lw=1, ls="--")
            # Labels sit right of their line so that no line strikes through a label.
            ax.text(xv + 0.05, len(keys) - 0.42, txt, ha="left", va="bottom", fontsize=9)
        ax.set_yticks(range(len(keys)))
        ax.set_yticklabels([labels[k] for k in keys])
        ax.set_xlim(*xlim)
        ax.set_ylim(-0.65, len(keys) + 0.05)
        ax.set_xlabel("VCHG-IN threshold (V)")
        ax.grid(axis="x", alpha=0.3)
    axes[0].set_title("U101 UVLO (VCHG-IN)")
    axes[1].set_title("U101 OVP (VCHG-IN)")
    h, lab = axes[0].get_legend_handles_labels()
    fig.legend(h, lab, loc="lower center", ncol=3, fontsize=9, frameon=False)
    fig.suptitle("Sim 5 part (a): TCKE1401NM Table 10.1 limits, R102/R103/R104 0.1 %")
    fig.tight_layout(rect=(0, 0.11, 1, 1))
    out = os.path.join(HERE, "fig_efuse_bands.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print("wrote", out)


# ---------------------------------------------------------------------------------------------------------
# Figure B: worst time to 12.0 V against the EVM draw, and the T10 proof (b) ranges
# ---------------------------------------------------------------------------------------------------------
def fig_t12():
    rows = read_csv("b_decay_cases.csv")
    states = [("ON", "#3b6db3", "o"), ("LATCHED_BD", "#c0392b", "s"), ("OVP_START", "#e67e22", "^")]
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 4.6), gridspec_kw={"width_ratios": [1, 1, 0.9]})
    for ax, v0 in zip(axes[:2], ("16.00", "22.28")):
        for st, col, mk in states:
            worst = {}
            for r in rows:
                if r["state"] != st or r["V0_V"] != v0:
                    continue
                ie = float(r["I_evm_mA"])
                t = float(r["t_to_12V_s_ngspice"])
                worst[ie] = max(worst.get(ie, 0.0), t)
            if not worst:
                continue
            # Equal spacing over the swept I_evm values (RESULTS.md section 2.2: 0, 0.1, 0.2, 0.391, 1.08,
            # 2.31 mA).
            xs = sorted(worst)
            ax.plot([CATS.index(x) for x in xs], [worst[x] for x in xs], marker=mk, color=col, label=st)
            if st == "OVP_START" or (st == "ON" and v0 == "16.00"):
                ax.annotate("%.3f s" % worst[0.0], (0, worst[0.0]), textcoords="offset points",
                            xytext=(8, 4), fontsize=9, color=col)
            if st == "LATCHED_BD":
                ax.annotate("%.3f s" % worst[0.391], (3, worst[0.391]), textcoords="offset points",
                            xytext=(8, -16 if v0 == "22.28" else 8), fontsize=9, color=col)
        ax.axhline(1.5, color="k", ls="--", lw=1)
        ax.axhline(0.5, color="k", ls=":", lw=1)
        ax.text(len(CATS) - 0.75, 1.53, "1.5 s dwell", ha="right", va="bottom", fontsize=9)
        ax.text(-0.2, 0.53, "0.5 s dwell", ha="left", va="bottom", fontsize=9)
        ax.axvline(3, color="0.4", lw=1)
        ax.text(3.1, 4.3, "H.15 floor\n0.391 mA", fontsize=9, color="0.3", va="top")
        ax.set_xticks(range(len(CATS)))
        ax.set_xticklabels(["0", "0.1", "0.2", "0.391", "1.08", "2.31"], fontsize=9)
        ax.set_xlim(-0.3, len(CATS) - 0.7)
        ax.set_ylim(0, 4.4)
        ax.set_xlabel("EVM Idle VBUS draw I_evm (mA, swept values)")
        ax.set_title("FR-12(b1), V0 = %s V" % v0.rstrip("0").rstrip("."))
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("worst time from both EN LOW to 12.0 V (s)")
    axes[1].legend(loc="upper right", fontsize=9, bbox_to_anchor=(1.0, 0.80))

    # Right panel: F.5 T10 proof (b), 16.0 -> 8.0 V. The values are the ranges quoted in
    # MORNING_REVIEW_2026-11-14.md section 4.5 (0.083-4.39 s all draws; 0.083-1.38 s with I_evm >= 0.391 mA;
    # superseded hand estimate 55-181 ms). No per-case CSV exists for this decay (the recompute is a scratch
    # script in update_2026-11-14/notes_phaseC_doc_fw.md appendix A), so only the quoted ranges are drawn.
    ax = axes[2]
    bars = [("all I_evm\n(0-2.31 mA)", 0.083, 4.39, "#c0392b"),
            ("I_evm >= 0.391 mA", 0.083, 1.38, "#3b6db3"),
            ("hand estimate\n(superseded)", 0.055, 0.181, "0.6")]
    for i, (lab, lo, hi, col) in enumerate(bars):
        y = len(bars) - 1 - i
        ax.barh(y, hi - lo, left=lo, height=0.45, color=col, alpha=0.8)
        ax.text(hi + 0.08, y, "%s-%s s" % (("%.3f" % lo).rstrip("0"), ("%.3f" % hi).rstrip("0")),
                va="center", fontsize=9)
    ax.set_yticks(range(len(bars)))
    ax.set_yticklabels([b[0] for b in reversed(bars)], fontsize=9)
    ax.set_xlim(0, 6.2)
    ax.set_xlabel("decay time 16.0 -> 8.0 V (s)")
    ax.set_title("T10 proof (b), quoted ranges")
    ax.grid(axis="x", alpha=0.3)
    fig.suptitle("Sim 5 part (b): VCHG-IN decay after both charger-path EN go LOW (worst over C_in, C_evm, "
                 "IQ, Vf)", fontsize=10)
    fig.tight_layout()
    out = os.path.join(HERE, "fig_efuse_t12_vs_ievm.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print("wrote", out)


# ---------------------------------------------------------------------------------------------------------
# Figure C: FR-12(a2) ratio
# ---------------------------------------------------------------------------------------------------------
def fig_ratio():
    rows = read_csv("c_ratio_summary.csv")
    scen = []
    for r in rows:
        if r["scenario"] not in scen:
            scen.append(r["scenario"])
    nodes = []
    for r in rows:
        if r["node_set"] not in nodes:
            nodes.append(r["node_set"])
    colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2"]
    fig, ax = plt.subplots(figsize=(10, 4.8))
    w = 0.11
    for j, nd in enumerate(nodes):
        for i, sc in enumerate(scen):
            r = [x for x in rows if x["scenario"] == sc and x["node_set"] == nd][0]
            lo, hi = float(r["ratio_min_shorted"]), float(r["ratio_max_shorted"])
            x = i + (j - (len(nodes) - 1) / 2) * w
            ax.plot([x, x], [lo, hi], color=colors[j], lw=5, solid_capstyle="butt",
                    label=nd if i == 0 else None)
            if sc.startswith("V_fc 13") and nd.startswith("as-built, gain fit 0.48"):
                ax.annotate("%.3f" % lo, (x, lo), xytext=(-22, -14), textcoords="offset points", fontsize=9)
            if sc.startswith("V_fc 13") and "open-cathode" in nd:
                ax.annotate("%.3f" % lo, (x, lo), xytext=(6, -10), textcoords="offset points", fontsize=9)
    # Open-switch upper bound including the +-2 count noise bound: max(ratio + ratio_noise_bound) of
    # c_ratio_open_switch.csv = 0.0089 = headline.txt "C open-switch worst ratio incl. noise: 0.0089". Only the
    # upper bound is drawn: it is the decision-relevant one for k. The CSV lower end (ratio - noise bound) is
    # -0.0831, which disagrees with the "-0.003" of RESULTS.md section 4.3 Table 5, so no lower end is drawn.
    ax.axhline(0.0089, color="0.35", lw=1.5)
    ax.text(len(scen) - 0.5, 0.02, "open switch, any node: at most +0.009 (with ADC noise)", ha="right",
            fontsize=9, color="0.25")
    for k, ls, txt in ((0.5, ":", "k = 0.5 (fails on measured data)"), (0.3, "--", "k = 0.3"),
                       (0.2, "-", "k = 0.2 (recommended, dV_bus >= 2 V)")):
        ax.axhline(k, color="k", ls=ls, lw=1.2)
        ax.text(-0.45, k + 0.01, txt, fontsize=9, va="bottom")
    ax.set_xticks(range(len(scen)))
    ax.set_xticklabels([s.replace(", V_batt", ",\nV_batt") for s in scen], fontsize=9)
    ax.set_xlim(-0.5, len(scen) - 0.5)
    ax.set_ylim(-0.03, 1.08)
    ax.set_ylabel("dV_rgn / dV_bus, shorted D-MT-EN")
    ax.set_title("Sim 5 part (c): FR-12(a2) ratio over the P0-gate grid, P2 end 15.8-16.0 V")
    ax.legend(loc="center left", bbox_to_anchor=(1.01, 0.5), fontsize=9, frameon=False)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    out = os.path.join(HERE, "fig_efuse_ratio.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print("wrote", out)


if __name__ == "__main__":
    fig_bands()
    fig_t12()
    fig_ratio()
