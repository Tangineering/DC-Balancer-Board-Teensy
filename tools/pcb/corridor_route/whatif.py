"""What-if tests for design-change requests, on scratch copies only. The orchestrator of a race runs these before
a request is sent to the design owner, so that the request carries a measured gain and not a worker's estimate.

Usage (pcbnew venv):
  python whatif.py holdout <model.json> <plan.json> <outdir> --nets /A,/B [--seeds 1,2,3,4] [--iters 60]
  python whatif.py move <board.kicad_pcb> <outdir> --part R101 [--dx 0.4] [--dy 0] [--rot 90] [--y-flip-offset Y0]

holdout: tests a request that takes nets out of the routing problem (DNP removal, a new pour or rail for a net).
  It routes the plan as it is and with the named nets added to `keep_nets`, at each seed, in parallel, and
  compares the open connections on the nets that remain. Writes <outdir>/WHATIF.md and <outdir>/tested.json
  (an entry for merge_requests.py --tested; add the "match" field by hand), and <outdir>/base/SEEDS.json and
  <outdir>/held/SEEDS.json counted on the remaining nets, which `seeds.py compare` reads.
move: tests a placement request. It writes a copy of the board to <outdir> with one part moved by (dx, dy) in
  the plan frame (y up when --y-flip-offset is given) and rotated by --rot degrees, refills the zones, and
  reports the DRC items that the move adds (courtyard overlaps, clearance). Then build a model of the copy and
  route it with `route_plan.py --keep-routes <routes.json of the best attempt on the original>`: nets whose old
  copper is still legal on the moved board are kept, the others are routed again. Compare the open connections.
Neither command touches the original board. A part move that the what-if likes is still only a request: the design
owner checks it against the design rows."""
import json
import os
import subprocess
import sys


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


if len(sys.argv) < 5 or sys.argv[1] not in ("holdout", "move"):
    raise SystemExit(__doc__)
HERE = os.path.dirname(os.path.abspath(__file__))
outdir = os.path.abspath(sys.argv[4] if sys.argv[1] == "holdout" else sys.argv[3])
os.makedirs(outdir, exist_ok=True)

if sys.argv[1] == "holdout":
    model, plan = sys.argv[2], sys.argv[3]
    held = [n for n in arg("--nets", "").split(",") if n]
    seeds = [int(s) for s in arg("--seeds", "1,2,3,4").split(",")]
    iters = arg("--iters", "60")
    P = json.load(open(plan))
    P2 = dict(P)
    P2["keep_nets"] = sorted(set(P.get("keep_nets", [])) | set(held))
    P2["groups"] = [dict(g, nets=[n for n in g["nets"] if n not in held]) for g in P.get("groups", [])]
    P2["groups"] = [g for g in P2["groups"] if g["nets"]]
    plan2 = os.path.join(outdir, "plan_holdout.json")
    json.dump(P2, open(plan2, "w"), indent=1)
    jobs = []
    for s in seeds:
        for tag, pl in (("base", plan), ("held", plan2)):
            out = os.path.join(outdir, "%s_s%d.json" % (tag, s))
            jobs.append((tag, s, out, subprocess.Popen(
                [sys.executable, "-u", os.path.join(HERE, "route_plan.py"), model, pl, out, "--seed", str(s),
                 "--iters", iters], cwd=HERE, stdout=open(out + ".log", "w"), stderr=subprocess.STDOUT)))
    for _, _, _, p in jobs:
        p.wait()
    sys.path.insert(0, HERE)
    from core import Ctx
    C = Ctx(model, plan)
    rest = [n for n in C.routable if n not in held and C.connections(n) > 0]
    total = sum(C.connections(n) for n in rest)

    def open_rest(f):
        R = json.load(open(f))
        st = R.get("net_stats", {})
        return sum(st[n]["open"] if n in st else C.connections(n) for n in rest)

    res = {(tag, s): open_rest(out) for tag, s, out, _ in jobs}
    gains = [res[("base", s)] - res[("held", s)] for s in seeds]
    mean = sum(gains) / len(gains)
    L = ["# What-if: hold out %s" % ", ".join(held), "",
         "Open connections on the %d nets that remain (%d connections), plan `%s`, %s iterations." % (
             len(rest), total, os.path.basename(plan), iters), "",
         "| Seed | Plan as it is | Nets held out | Gain |", "|---|---|---|---|"]
    L += ["| %d | %d | %d | %+d |" % (s, res[("base", s)], res[("held", s)], g) for s, g in zip(seeds, gains)]
    n_ = len(gains)
    verdict = ("gain" if n_ >= 4 and all(g > 0 for g in gains) else
               "loss" if n_ >= 4 and all(g < 0 for g in gains) else "not separated")
    L += ["", "Mean gain: %+.1f connections on the remaining nets (n = %d). Verdict: **%s**. The held-out nets "
          "themselves (%d connections) leave the routing problem. A gain is a result only with 4 or more seeds and "
          "a positive difference at every seed." % (mean, n_, verdict,
                                                   sum(C.connections(n) for n in held if n in C.routable))]
    open(os.path.join(outdir, "WHATIF.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    # SEEDS.json for each side, counted on the remaining nets only, so that `seeds.py compare` can read a hold-out
    # (outdir/base, outdir/held; `seeds.py compare <x> <outdir>` takes outdir/held)
    for tag, pl in (("base", plan), ("held", plan2)):
        runs = {}
        for s in seeds:
            st = json.load(open(os.path.join(outdir, "%s_s%d.json" % (tag, s)))).get("net_stats", {})
            runs[str(s)] = dict(made=total - res[(tag, s)], total=total,
                                open=sorted(n for n in rest if (st[n]["open"] if n in st else C.connections(n)) > 0))
        made = [runs[str(s)]["made"] for s in seeds]
        os.makedirs(os.path.join(outdir, tag), exist_ok=True)
        json.dump(dict(plan=os.path.abspath(pl), seeds=seeds, options=["--iters", iters], runs=runs,
                       mean=sum(made) / len(made), min=min(made), max=max(made), total=total,
                       counted_on="the %d nets that remain after the hold-out of %s" % (len(rest), ", ".join(held))),
                  open(os.path.join(outdir, tag, "SEEDS.json"), "w"), indent=1)
    json.dump([dict(match=dict(kind="?", parts=[]), gain=round(mean, 1), verdict=verdict, seeds=seeds,
                    how="held out %s; open connections on the remaining nets %s -> %s" % (
                        ", ".join(held), [res[("base", s)] for s in seeds], [res[("held", s)] for s in seeds]))],
              open(os.path.join(outdir, "tested.json"), "w"), indent=1)
    print("\n".join(L))
else:
    import pcbnew
    try:
        import wx
        wx.DisableAsserts()
    except Exception:
        pass
    sys.path.insert(0, HERE)
    from projfiles import copy_project
    board = sys.argv[2]
    part = arg("--part")
    dx, dy, rot = float(arg("--dx", "0")), float(arg("--dy", "0")), float(arg("--rot", "0"))
    if arg("--y-flip-offset") is not None:
        dy = -dy
    out = copy_project(board, outdir, with_board=True)
    b = pcbnew.LoadBoard(out)
    fp = b.FindFootprintByReference(part)
    if fp is None:
        raise SystemExit("part %s is not on the board" % part)
    p = fp.GetPosition()
    fp.SetPosition(pcbnew.VECTOR2I(p.x + pcbnew.FromMM(dx), p.y + pcbnew.FromMM(dy)))
    if rot:
        fp.SetOrientationDegrees(fp.GetOrientationDegrees() + rot)
    b.Save(out)
    b2 = pcbnew.LoadBoard(out)
    b2.BuildConnectivity()
    pcbnew.ZONE_FILLER(b2).Fill(b2.Zones())
    b2.Save(out)
    cli = r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe"

    def viol(bf):
        tmp = os.path.join(outdir, "_drc.json")
        subprocess.run([cli, "pcb", "drc", "--format", "json", "--severity-all", "-o", tmp, bf], capture_output=True)
        D = json.load(open(tmp, encoding="utf-8"))
        os.remove(tmp)
        c = {}
        for v in D.get("violations", []):
            c[v["type"]] = c.get(v["type"], 0) + 1
        return c

    # the baseline is a refilled copy of the unmoved board: the same zone fill as the moved copy
    import shutil
    base_dir = os.path.join(outdir, "_base")
    base = copy_project(board, base_dir, with_board=True)
    b0 = pcbnew.LoadBoard(base)
    b0.BuildConnectivity()
    pcbnew.ZONE_FILLER(b0).Fill(b0.Zones())
    b0.Save(base)
    v0, v1 = viol(base), viol(out)      # _base stays: it is the control board of relief_trial.py
    new = {t: v1[t] - v0.get(t, 0) for t in v1 if v1[t] > v0.get(t, 0)}
    # silkscreen is fixed up later; a starved thermal does not make a result invalid (common.md section 5)
    blocking = {t: n for t, n in new.items() if not t.startswith("silk") and t != "starved_thermal"}
    print("moved %s by (%.3f, %.3f) mm, rotated %.0f deg -> %s" % (part, dx, dy if arg("--y-flip-offset") is None else -dy,
                                                                  rot, out))
    json.dump(dict(part=part, dx=dx, dy=(dy if arg("--y-flip-offset") is None else -dy), rot=rot,
                   old=dict(x=pcbnew.ToMM(p.x), y=pcbnew.ToMM(p.y)), new_drc=new, legal=not blocking),
              open(os.path.join(outdir, "move.json"), "w"), indent=1)
    print("DRC items added by the move: %s" % (new or "none"))
    if blocking:
        print("The move is not legal as it stands (%s). Do not route it." % ", ".join(sorted(blocking)))
    else:
        print("The move is legal for DRC. Run the project's constraint check on the copy before routing it.")
