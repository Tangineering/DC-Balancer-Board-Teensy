"""Run one plan at several seeds in parallel and report the statistics; compare two such runs.

Usage (venv with numpy + shapely):
  python -u seeds.py run <model.json> <plan.json> <outdir> [--seeds 1,2,3,4] [--jobs 8] [-- <route_plan.py options>]
  python seeds.py compare <outdir A> <outdir B> [<report.md>]

run: one route_plan.py run for each seed, --jobs at a time. Writes <outdir>/s<seed>/routes.json,
route_report.md and route.log, and <outdir>/SEEDS.md and SEEDS.json: connections made for each seed, mean,
minimum, maximum, and the nets that are open at every seed (a net that is open at every seed is evidence of a
limit at that net; a net that is open at one seed only is noise).

compare: A is the reference, B the candidate. Both must have the same seeds and the same total. The script
prints the paired differences (same seed), their mean, and the verdict:
  B better     every paired difference is positive, with 4 or more seeds;
  B worse      every paired difference is negative, with 4 or more seeds;
  not separated  anything else.
A difference of means alone is never a result: on the test boards two seeds of one plan differed by up to 9
connections.
A whatif.py holdout folder can be given for A or B: compare reads its held side (<folder>/held), counted on the
nets that remain. `seeds.py compare <folder>/base <folder>/held` gives the hold-out verdict again; a hold-out
against another plan's run counts the open connections of the held-out nets on the other side only (a bias towards
the hold-out, the same as any compare of runs with different totals)."""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def run():
    model, plan, outdir = sys.argv[2], sys.argv[3], os.path.abspath(sys.argv[4])
    seeds = [int(s) for s in arg("--seeds", "1,2,3,4").split(",")]
    jobs = int(arg("--jobs", "8"))
    extra = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    os.makedirs(outdir, exist_ok=True)
    pending, running, done = list(seeds), [], {}
    while pending or running:
        while pending and len(running) < jobs:
            s = pending.pop(0)
            d = os.path.join(outdir, "s%d" % s)
            os.makedirs(d, exist_ok=True)
            p = subprocess.Popen([sys.executable, "-u", os.path.join(HERE, "route_plan.py"), model, plan,
                                  os.path.join(d, "routes.json"), "--report", os.path.join(d, "route_report.md"),
                                  "--seed", str(s)] + extra, stdout=open(os.path.join(d, "route.log"), "w"),
                                 stderr=subprocess.STDOUT)
            running.append((s, p))
        s, p = running.pop(0)
        if p.wait():
            raise SystemExit("seed %d failed, see %s" % (s, os.path.join(outdir, "s%d" % s, "route.log")))
        J = json.load(open(os.path.join(outdir, "s%d" % s, "routes.json")))
        done[s] = dict(made=J["summary"]["connections_made"], total=J["summary"]["connections"],
                       vias=J["summary"]["vias"], seconds=J["summary"]["seconds"],
                       iterations=J["summary"]["iterations"], stopped=J["summary"]["stopped"], open=J["open"],
                       plane_no_site=len(J["summary"].get("plane_pads_no_via_site", [])))
        print("seed %d: %d of %d (%s)" % (s, done[s]["made"], done[s]["total"], done[s]["stopped"]), flush=True)
    made = [done[s]["made"] for s in seeds]
    always = sorted(set.intersection(*[set(done[s]["open"]) for s in seeds]))
    once = sorted(set.union(*[set(done[s]["open"]) for s in seeds]) - set(always))
    S = dict(plan=os.path.abspath(plan), seeds=seeds, options=extra, runs={str(s): done[s] for s in seeds},
             mean=sum(made) / len(made), min=min(made), max=max(made), total=done[seeds[0]]["total"],
             open_every_seed=always, open_some_seeds=once)
    json.dump(S, open(os.path.join(outdir, "SEEDS.json"), "w"), indent=1)
    L = ["# Seeds", "", "Plan `%s`, options `%s`." % (os.path.basename(plan), " ".join(extra) or "none"), "",
         "| Seed | Connections made / total | Vias | Plane pads without a via site | Iterations | Stopped | Seconds |",
         "|---|---|---|---|---|---|---|"]
    L += ["| %d | %d / %d | %d | %d | %d | %s | %d |" % (s, done[s]["made"], done[s]["total"], done[s]["vias"],
                                                         done[s]["plane_no_site"], done[s]["iterations"],
                                                         done[s]["stopped"], done[s]["seconds"])
          for s in seeds]
    L += ["", "Mean %.1f, minimum %d, maximum %d of %d (n = %d)." % (S["mean"], S["min"], S["max"], S["total"], len(seeds)),
          "", "Open at every seed (%d nets): %s" % (len(always), ", ".join(always) or "none"),
          "", "Open at some seeds only (%d nets): %s" % (len(once), ", ".join(once) or "none"),
          "", "These numbers are from `route_plan.py`. Apply and score the seed that is reported; only a scored "
          "result is valid."]
    open(os.path.join(outdir, "SEEDS.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))


def load_seeds(d):
    """SEEDS.json of a seeds.py run, or of a whatif.py holdout folder (its held side, counted on the remaining nets)."""
    f = os.path.join(d, "SEEDS.json")
    if not os.path.exists(f) and os.path.exists(os.path.join(d, "held", "SEEDS.json")):
        f = os.path.join(d, "held", "SEEDS.json")
        print("%s is a whatif.py holdout folder: using its held side (%s)" % (d, f))
    if not os.path.exists(f):
        raise SystemExit("no SEEDS.json in %s (a holdout folder made before 2026-11-12 has none: compare it by hand "
                         "from its WHATIF.md, or run the holdout again)" % d)
    return json.load(open(f))


def compare():
    A = load_seeds(sys.argv[2])
    B = load_seeds(sys.argv[3])
    if A["seeds"] != B["seeds"]:
        raise SystemExit("the two runs have different seeds: %s, %s" % (A["seeds"], B["seeds"]))
    # a what-if that removes nets changes the total: compare open connections, not connections made
    oa = [A["runs"][str(s)]["total"] - A["runs"][str(s)]["made"] for s in A["seeds"]]
    ob = [B["runs"][str(s)]["total"] - B["runs"][str(s)]["made"] for s in B["seeds"]]
    diff = [a - b for a, b in zip(oa, ob)]             # positive: B has fewer open connections
    n = len(diff)
    if n >= 4 and all(d > 0 for d in diff):
        verdict = "B better"
    elif n >= 4 and all(d < 0 for d in diff):
        verdict = "B worse"
    else:
        verdict = "not separated"
    L = ["# Comparison", "", "A (reference): `%s`, total %d. B (candidate): `%s`, total %d." % (
        os.path.basename(A["plan"]), A["total"], os.path.basename(B["plan"]), B["total"]), "",
        "| Seed | Open, A | Open, B | A - B |", "|---|---|---|---|"]
    L += ["| %d | %d | %d | %+d |" % (s, a, b, d) for s, a, b, d in zip(A["seeds"], oa, ob, diff)]
    L += ["", "Mean difference %+.1f open connections (n = %d). Verdict: **%s**." % (sum(diff) / n, n, verdict), "",
          "B better or worse needs 4 or more seeds with the same sign at every seed. If the totals differ (nets "
          "were held out), the open connections of B do not include the nets that left the task."]
    txt = "\n".join(L) + "\n"
    if len(sys.argv) > 4:
        open(sys.argv[4], "w", encoding="utf-8").write(txt)
    print(txt)


if len(sys.argv) >= 5 and sys.argv[1] == "run":
    run()
elif len(sys.argv) >= 4 and sys.argv[1] == "compare":
    compare()
else:
    raise SystemExit(__doc__)
