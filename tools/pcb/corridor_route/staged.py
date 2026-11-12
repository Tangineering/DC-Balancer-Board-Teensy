"""Staged routing and finishing pass: drivers around route_plan.py.

Usage (venv with numpy + shapely):
  python -u staged.py staged <model.json> <plan.json> <outdir> [--seed 1] [--iters 20] [--order cross]
  python -u staged.py finish <model.json> <plan.json> <outdir> --start <routes.json> [--radius 2.0] [--seeds 1,2]
                             [--iters 12]

staged: the priority classes of the plan are routed one after the other. Class 1 is routed alone; its complete
nets are locked; class 2 is routed against them; and so on. The constrained nets get the board to themselves, and
a later change to an ordinary net cannot move them. Output: <outdir>/routes.json and route_report.md (the last
stage), and stage_<p>.json for each class.

finish: a finishing pass on an existing result. The complete nets are kept, except the nets (priority above 1)
that pass within --radius of an open pad; those and the open nets are routed again. Each seed is one trial. The
trial with the most connections is written to <outdir>/routes.json only if it has more connections than the
start; otherwise the start result is copied there. Output: FINISH.md with one row for each trial."""
import argparse
import json
import os
import shutil
import subprocess
import sys

ap = argparse.ArgumentParser()
ap.add_argument("cmd", choices=("staged", "finish"))
ap.add_argument("model")
ap.add_argument("plan")
ap.add_argument("outdir")
ap.add_argument("--seed", default="1")
ap.add_argument("--seeds", default="1,2")
ap.add_argument("--iters", default=None)
ap.add_argument("--order", default="cross")
ap.add_argument("--start", default=None)
ap.add_argument("--radius", default="2.0")
A = ap.parse_args()
HERE = os.path.dirname(os.path.abspath(__file__))
os.makedirs(A.outdir, exist_ok=True)


def run(out, rep, extra):
    cmd = [sys.executable, "-u", os.path.join(HERE, "route_plan.py"), A.model, A.plan, out, "--report", rep] + extra
    log = open(out.replace(".json", ".log"), "w")
    r = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT)
    if r.returncode:
        raise SystemExit("route_plan.py failed, see %s" % log.name)
    return json.load(open(out))["summary"]


if A.cmd == "staged":
    P = json.load(open(A.plan))
    dp = P.get("default", {}).get("priority", 5)
    prios = sorted({g.get("priority", dp) for g in P.get("groups", [])} | {dp})
    prev = None
    rows = []
    for k, p in enumerate(prios):
        out = os.path.join(A.outdir, "stage_%s.json" % p)
        extra = ["--seed", A.seed, "--order", A.order, "--max-priority", str(p), "--iters", A.iters or "20"]
        if prev:
            extra += ["--keep-routes", prev]
        s = run(out, out.replace(".json", ".md"), extra)
        rows.append((p, s["nets"], s["kept"], s["connections_made"], s["connections"], s["seconds"]))
        print("stage priority <= %s: %d of %d connections, %d nets kept from the stage before, %d s" % (
            p, s["connections_made"], s["connections"], s["kept"], s["seconds"]), flush=True)
        prev = out
    shutil.copy(prev, os.path.join(A.outdir, "routes.json"))
    shutil.copy(prev.replace(".json", ".md"), os.path.join(A.outdir, "route_report.md"))
    L = ["# Staged routing", "", "| Priority up to | Nets | Kept from the stage before | Connections made / total | Seconds |",
         "|---|---|---|---|---|"] + ["| %s | %d | %d | %d / %d | %d |" % r for r in rows]
    if len(prios) == 1:
        L += ["", "The plan has one priority class; this is an ordinary run."]
    open(os.path.join(A.outdir, "STAGED.md"), "w").write("\n".join(L) + "\n")
else:
    if not A.start:
        raise SystemExit("finish needs --start <routes.json>")
    s0 = json.load(open(A.start))["summary"]
    best, rows = None, []
    for seed in A.seeds.split(","):
        out = os.path.join(A.outdir, "trial_s%s.json" % seed)
        s = run(out, out.replace(".json", ".md"), ["--seed", seed, "--keep-routes", A.start, "--ripup-radius", A.radius,
                                                   "--iters", A.iters or "12"])
        rows.append((seed, s["connections_made"], s["connections"], s["vias"], s["seconds"]))
        print("finish seed %s: %d of %d connections (start %d)" % (seed, s["connections_made"], s["connections"],
                                                                   s0["connections_made"]), flush=True)
        if best is None or s["connections_made"] > best[0]:
            best = (s["connections_made"], out)
    gain = best[0] - s0["connections_made"]
    src = best[1] if gain > 0 else A.start
    shutil.copy(src, os.path.join(A.outdir, "routes.json"))
    rep = src.replace(".json", ".md")
    if gain > 0 and os.path.exists(rep):
        shutil.copy(rep, os.path.join(A.outdir, "route_report.md"))
    L = ["# Finishing pass", "", "Start: %d of %d connections. Rip-up radius %s mm." % (
        s0["connections_made"], s0["connections"], A.radius), "",
        "| Seed | Connections made / total | Vias | Seconds |", "|---|---|---|---|"]
    L += ["| %s | %d / %d | %d | %d |" % r for r in rows]
    L += ["", "Result: %s." % ("gain of %d connection(s); routes.json is the trial %s" % (gain, os.path.basename(src))
                               if gain > 0 else "no gain; routes.json is the start result, unchanged")]
    open(os.path.join(A.outdir, "FINISH.md"), "w").write("\n".join(L) + "\n")
    print(L[-1])
