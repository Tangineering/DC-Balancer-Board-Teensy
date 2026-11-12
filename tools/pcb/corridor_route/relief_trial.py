"""Judge one placement trial against an equal control. The script decides; the agent that proposed the move
does not.

Usage (venv with numpy + shapely):
  python -u relief_trial.py <start model.json> <moved model.json> <plan.json> <start routes.json> <outdir>
                            --site X,Y,R --nets /A,/B [--seeds 1,2,3,4] [--iters 30]

For each seed the script routes twice with the same options: the control on the start model and the trial on the
moved model. Both keep the complete nets of the start result, except the nets that pass within R mm of the site
(X, Y in the plan frame), which are routed again together with the open nets. The only difference between the
two runs is the move.

The move is ACCEPTED when all three hold at every seed:
  1. every net named with --nets is complete in the trial;
  2. no net that was complete in the start result is open in the trial;
  3. the trial has more connections than the control.
Otherwise it is REJECTED, and the report says which rule failed. A move that passes rule 3 at every seed but
fails rule 1 is reported as "gain without closure": it is not a relief of the site, but the gain may be sent
as a request of its own.

Writes <outdir>/TRIAL.md, <outdir>/trial.json (an entry for merge_requests.py --tested; add the "match" field),
and the routes of each run in <outdir>/control_s<seed>/ and <outdir>/trial_s<seed>/. Apply and score the trial
routes of one seed before the move is reported: only a scored result is valid."""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


if len(sys.argv) < 7 or not arg("--site") or not arg("--nets"):
    raise SystemExit(__doc__)
m0, m1, plan, start, outdir = sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], os.path.abspath(sys.argv[6])
site, nets = arg("--site"), [n for n in arg("--nets").split(",") if n]
seeds = [int(s) for s in arg("--seeds", "1,2,3,4").split(",")]
iters = arg("--iters", "30")
os.makedirs(outdir, exist_ok=True)
S0 = json.load(open(start))
complete0 = {r["net"] for r in S0["results"] if not r.get("open_pads")} - set(S0.get("open", []))
jobs = []
for s in seeds:
    for tag, model in (("control", m0), ("trial", m1)):
        d = os.path.join(outdir, "%s_s%d" % (tag, s))
        os.makedirs(d, exist_ok=True)
        jobs.append((tag, s, d, subprocess.Popen(
            [sys.executable, "-u", os.path.join(HERE, "route_plan.py"), model, plan, os.path.join(d, "routes.json"),
             "--report", os.path.join(d, "route_report.md"), "--seed", str(s), "--keep-routes", start,
             "--ripup-site", site, "--iters", iters], stdout=open(os.path.join(d, "route.log"), "w"),
            stderr=subprocess.STDOUT)))
res = {}
for tag, s, d, p in jobs:
    if p.wait():
        raise SystemExit("%s seed %d failed, see %s" % (tag, s, os.path.join(d, "route.log")))
    J = json.load(open(os.path.join(d, "routes.json")))
    res[(tag, s)] = dict(made=J["summary"]["connections_made"], open=set(J["open"]), kept=J["summary"].get("kept"),
                         iterations=J["summary"]["iterations"])
rows, fails = [], set()
for s in seeds:
    c, t = res[("control", s)], res[("trial", s)]
    still = [n for n in nets if n in t["open"]]
    lost = sorted(complete0 & t["open"])
    r1, r2, r3 = not still, not lost, t["made"] > c["made"]
    for ok, name in ((r1, "1 (named nets complete)"), (r2, "2 (no complete net lost)"), (r3, "3 (more than the control)")):
        if not ok:
            fails.add(name)
    rows.append((s, c["made"], t["made"], t["made"] - c["made"], ", ".join(still) or "none", ", ".join(lost) or "none"))
gain_all = all(r[3] > 0 for r in rows)
if not fails:
    verdict = "ACCEPTED"
elif gain_all and fails == {"1 (named nets complete)"}:
    verdict = "REJECTED as relief of the site (rule 1); gain without closure at every seed"
else:
    verdict = "REJECTED (rule %s)" % "; rule ".join(sorted(fails))
total = S0["summary"]["connections"]
L = ["# Placement trial", "", "Site %s (x, y, radius; plan frame). Named nets: %s. Start result: %d of %d." % (
    site, ", ".join(nets), S0["summary"]["connections_made"], total), "",
    "| Seed | Control | Trial | Trial - control | Named nets still open | Complete nets lost |", "|---|---|---|---|---|---|"]
L += ["| %d | %d | %d | %+d | %s | %s |" % r for r in rows]
L += ["", "Verdict: **%s**." % verdict, "",
      "Control and trial use the same kept nets, the same rip-up site, the same seeds and the same iteration limit "
      "(%s); the only difference is the move. Nets kept: control %s, trial %s (a difference means that the move made "
      "kept copper illegal; those nets were routed again in the trial)." % (
          iters, [res[("control", s)]["kept"] for s in seeds], [res[("trial", s)]["kept"] for s in seeds])]
open(os.path.join(outdir, "TRIAL.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
json.dump([dict(match=dict(id="?"), gain=round(sum(r[3] for r in rows) / len(rows), 1), seeds=seeds, verdict=verdict,
                refuted=bool(fails), lost=sorted({n for r in rows for n in r[5].split(", ") if n != "none"}),
                how="relief_trial.py at site %s: control %s, trial %s" % (site, [r[1] for r in rows], [r[2] for r in rows]))],
          open(os.path.join(outdir, "trial.json"), "w"), indent=1)
print("\n".join(L))
