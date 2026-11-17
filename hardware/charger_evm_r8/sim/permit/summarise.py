"""Aggregate tables for RESULTS.md, built from the per-family CSVs in results/ (called at the end of run.py; can also
run alone: python summarise.py). Writes results/agg_t2.csv, results/agg_bridge.csv and results/agg_t6.csv and prints
the same rows."""
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")


def load(fam):
    path = os.path.join(RES, fam + ".csv")
    return list(csv.DictReader(open(path, encoding="utf-8"))) if os.path.exists(path) else []


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def rng(vals, fmt="%.3f"):
    vals = [v for v in vals if v == v]
    if not vals:
        return "-"
    lo, hi = min(vals), max(vals)
    return (fmt % lo) if abs(hi - lo) < 1e-12 else (fmt + "-" + fmt) % (lo, hi)


def write(name, rows):
    if not rows:
        return
    keys = list(rows[0])
    with open(os.path.join(RES, name), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print("  " + " | ".join(str(r[k]) for k in keys))


def t2_rows():
    out = []

    def grp(fam, label, sel):
        if not sel:
            return
        pk = [f(r["ILIM_pin_max"]) for r in sel]
        out.append(dict(family=fam, group=label, decks=len(sel),
                        release_us=rng([f(r["REL_logic_poss_maxw"]) * 1e6 for r in sel], "%.1f"),
                        ilim_peak_V=rng(pk), n_above_0v75=sum(p > 0.75 for p in pk), n_above_1v0=sum(p > 1.0 for p in pk),
                        above_1v0_us=rng([f(r["ILIM_pin_cert_maxw"]) * 1e6 for r in sel], "%.1f")))
    t2 = [r for r in load("t2race") if r["opened"] == "T2"]
    for vb in ("14.5", "15.9", "16.4"):
        grp("t2race", "T2, %s V, fixed tPD 2 us, 4 corners, cruise+Idle" % vb, [r for r in t2 if r["vbus"] == vb])
    sk = load("t2skew")
    for h1, uvb in (("2.0", "2.0"), ("4.0", "4.0"), ("2.0", "4.0"), ("2.0", "6.0"), ("2.0", "8.0"), ("2.0", "10.0"),
                    ("2.0", "12.0"), ("4.0", "14.0")):
        sel = [r for r in sk if f(r["tpd_H1_us"]) == f(h1) and f(r["tpd_UVB_us"]) == f(uvb)]
        grp("t2skew", "H1 %s / UVB %s us (skew %g us), 3 VBUS x 3 corners" % (h1, uvb, f(uvb) - f(h1)), sel)
        grp("t2skew", "H1 %s / UVB %s us, 16.4 V only" % (h1, uvb), [r for r in sel if r["vbus"] == "16.4"])
    od = load("t2od")
    for on in ("od1.3", "od2", "od4", "od_H1fast_UVBmax"):
        for vb in ("14.5", "15.9", "16.4"):
            grp("t2od", "base, %s, %s V, 3 corners" % (on, vb),
                [r for r in od if r["option"] == "base" and r["od_set"] == on and r["vbus"] == vb and r["test"] == "T2 open"
                 and r["case"].startswith("od_")])
    for fo in ("base", "C108_470p", "C107_4n7_only", "C106C107_4n7", "C106C107_10n"):
        for on in ("od4", "od_H1fast_UVBmax"):
            grp("t2od", "fix %s, %s, 16.4 V, 3 corners" % (fo, on),
                [r for r in od if r["case"].startswith("odfix_") and r["option"] == fo and r["od_set"] == on
                 and r["test"] == "T2 open"])
    fx = load("t2fixskew")
    for fo in ("base", "C108_470p", "C107_4n7_only", "C106C107_4n7", "C106C107_10n"):
        for r in sorted([r for r in fx if r["option"] == fo], key=lambda r: f(r["skew_us"])):
            grp("t2fixskew", "fix %s, H1 4 us, UVB %s us (skew %g us)" % (fo, r["tpd_UVB_us"], f(r["skew_us"])), [r])
    return out


def latency_rows():
    """H1 release latency (V-MOT step) under the overdrive model: first ILIM_REL_cr assertion after the step."""
    out = []
    for r in load("t2od"):
        if "regenstep" in r["case"]:
            out.append(dict(case=r["case"], option=r["option"], corner=r["corner"],
                            release_first_us=round((f(r["ILIM_REL_cr_poss_first"]) - 1e-3) * 1e6, 1)))
    for r in load("t2fix"):
        if "regenstep" in r["case"]:
            out.append(dict(case=r["case"], option=r["option"], corner=r["corner"],
                            release_first_us=round((f(r["ILIM_REL_cr_poss_first"]) - 1e-3) * 1e6, 1)))
    return out


def bridge_rows():
    out = []
    br = [r for r in load("bridge") if f(r.get("va")) == 0.8]
    labels = []
    for r in br:
        if r["bridge"] not in labels:
            labels.append(r["bridge"])
    for lab in labels:
        for bl in ("parts", "max"):
            sel = [r for r in br if r["bridge"] == lab and r.get("base_load") == bl]
            if not sel:
                continue
            out.append(dict(bridge=lab, base_load=bl, decks=len(sel), cr_rail_V=rng([f(r["c3v3_end"]) for r in sel]),
                            eib_rail_V=rng([f(r["e3v3_end"]) for r in sel]),
                            I_R130_mA=rng([f(r["I_R130_mA"]) for r in sel], "%.1f"),
                            I_R131A_mA=rng([f(r["I_R131A_mA"]) for r in sel], "%.1f"),
                            nCE_end_V=rng([f(r["end_nCE_V"]) for r in sel]),
                            ILIM_end_V=rng([f(r["end_ILIM_V"]) for r in sel])))
    return out


def t6_rows():
    out = []
    for r in load("jtap"):
        if r["opened"] != "T6":
            continue
        out.append(dict(case=r["case"], state=r["state"], va=r.get("va", ""), base_load=r.get("base_load", "") or "parts",
                        verdict=r["verdict"],
                        cr_below_1v65_ms=round(f(r["tl_cr_below_1v65_ms"]), 1),
                        rel_safe_ms=round(f(r["tl_rel_logic_safe_ms"]), 1),
                        ilim_rel_cr_safe_ms=round(f(r["tl_ilim_rel_cr_safe_ms"]), 1),
                        ce_logic_safe_ms=round(f(r["tl_ce_logic_safe_ms"]), 1),
                        ce_pin_high_ms=round(f(r["tl_ce_pin_high_ms"]), 1),
                        below_1v65_driving_ms=round(f(r["tl_below_1v65_driving_ms"]), 1),
                        cr_below_0v45_ms=round(f(r["tl_cr_below_0v45_ms"]), 1),
                        cr_rail_end_V=round(f(r["tl_c3v3_end"]), 3), eib_rail_end_V=round(f(r["tl_e3v3_end"]), 3)))
    return out


def main():
    print("T2 race aggregates:")
    write("agg_t2.csv", t2_rows())
    print("H1 release latency after a 1 us V-MOT step:")
    write("agg_latency.csv", latency_rows())
    print("Bridge aggregates:")
    write("agg_bridge.csv", bridge_rows())
    print("T6-open timelines:")
    write("agg_t6.csv", t6_rows())


if __name__ == "__main__":
    main()
