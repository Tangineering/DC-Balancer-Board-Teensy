"""Check pass of Section 5.6a (2026-11-15): re-runs the worst decks of t2brief.py with half the maximum time step
(0.25 us instead of 0.5 us) and compares the peak, the time above 1.0 V and the latency; also compares the
time-above metric with the checker's single-episode width. Writes results/t2brief_check.csv.

python t2brief_check.py
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_argv = sys.argv[:]
sys.argv = [sys.argv[0], "agg"]
import t2brief as T  # noqa: E402
sys.argv = _argv

CASES = ("int_base_20us_15.9V_early_od4", "int_base_10us_14.5V_early_od4", "int_C108_470p_10us_15.9V_early_od4",
         "int_C107_4n7_only_40us_16.4V_early_od4", "int_C106C107_4n7_30us_16.4V_early_od4",
         "rise_C107_4n7_only_12Vms_13_16.4V_nom_f2", "lat_base_1.8A_15.9V_early_od4",
         "lat_C106C107_4n7_1.8A_15.9V_early_od4")


def main():
    T.JOBS.clear()
    T.fam_int()
    T.fam_rise()
    T.fam_lat()
    base = {j["case"].name: j for j in T.JOBS}
    ref = {}
    for fam in ("t2int", "t2rise", "t2lat"):
        for r in T.load(fam):
            ref[r["case"]] = r
    out = []
    for name in CASES:
        j = dict(base[name])
        c = j["case"]
        c.t_max = 0.25e-6
        c.name = name + "_dt025"
        j["family"] = "t2check"
        row = T.execute(j)
        r0 = ref[name]
        rec = dict(case=name)
        for k in ("ilim_peak_V", "t_above_1v0_ceLOW_us", "t_rel_us", "t_hold_us"):
            if k in row:
                rec[k + "_0.5us"] = round(float(r0[k]), 4)
                rec[k + "_0.25us"] = round(float(row[k]), 4)
        if "ILIM_pin_cert_maxw" in r0:
            rec["single_episode_width_us"] = round(float(r0["ILIM_pin_cert_maxw"]) * 1e6, 2)
            rec["n_1v0_episodes"] = r0.get("n_1v0_episodes", "")
        out.append(rec)
        print(rec, flush=True)
    keys = []
    for r in out:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(os.path.join(T.RES, "t2brief_check.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(out)


if __name__ == "__main__":
    main()
