"""Merge the design-change requests of all race workers into one ranked batch for the design owner.

Usage (any Python 3):
  python merge_requests.py <racedir> [--round N] [--tested tested.json] [--history history.json] [--radius 1.5]

Reads every `requests.json` below <racedir> (one per worker folder; format in reference/common.md section 7).
Writes <racedir>/change_requests.json and <racedir>/CHANGE_REQUESTS.md.

Merge: two requests are one when they have the same kind and either share a part, name the same pour, or lie
within --radius mm of each other. Support is the list of workers and of methods (the first folder level below
<racedir> is the worker; its name up to the first "-" is the method). Support from different methods ranks above
support from several workers of one method.
Tested gain: --tested is a JSON list of {"match": {"kind": ..., "parts": [...]} or {"id": "<merged id>"},
"gain": <mean connections>, "seeds": [..], "verdict": "...", "lost": [nets], "how": "..."} written by
whatif.py holdout (WHATIF tested.json) and relief_trial.py (trial.json); the orchestrator adds "match". A request
without a tested gain is marked "untested"; the workers' estimates are shown as estimates only.
Tier: plan (the orchestrator decides), placement (the design session decides), ruling (the operator decides).
Hold-back: --history is the decisions file of earlier rounds (list of {"key": ..., "decision": "accepted" |
"rejected" | "modified", ...}). A request that was rejected before, or that touches a part moved by an accepted
change, is listed under "Held back" and is not sent."""
import glob
import json
import math
import os
import sys

TIER = {"plan": "plan", "placement": "placement", "pin_swap": "placement", "dnp": "ruling", "pour_or_rail": "ruling",
        "rule": "ruling", "layers": "ruling", "outline": "ruling"}


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
    raise SystemExit(__doc__)
race = sys.argv[1]
radius = float(arg("--radius", "1.5"))
rnd = arg("--round", "1")
tested = json.load(open(arg("--tested"))) if arg("--tested") else []
history = json.load(open(arg("--history"))) if arg("--history") else []

reqs, problems = [], []
for f in sorted(glob.glob(os.path.join(race, "**", "requests.json"), recursive=True)):
    worker = os.path.relpath(f, race).replace("\\", "/").split("/")[0]
    try:
        items = json.load(open(f, encoding="utf-8"))
    except Exception as e:
        problems.append("%s: not valid JSON (%s)" % (f, e))
        continue
    for r in items:
        ev = r.get("evidence") or {}
        if not ev.get("report"):
            problems.append("%s %s: no report evidence; not merged" % (worker, r.get("id", "?")))
            continue
        # a request without open nets is a quality request (a pour island, a long constrained net): it is kept
        if r.get("kind") not in TIER:
            problems.append("%s %s: unknown kind %r; not merged" % (worker, r.get("id", "?"), r.get("kind")))
            continue
        r["_worker"] = worker
        r["_method"] = worker.split("-")[0]
        reqs.append(r)


def same(a, b):
    if a["kind"] != b["kind"]:
        return False
    if set(a.get("parts") or []) & set(b.get("parts") or []):
        return True
    if a.get("pour") and a.get("pour") == b.get("pour"):
        return True
    if a.get("at") and b.get("at"):
        return math.hypot(a["at"][0] - b["at"][0], a["at"][1] - b["at"][1]) <= radius
    return False


groups = []
for r in reqs:
    for g in groups:
        if any(same(r, m) for m in g):
            g.append(r)
            break
    else:
        groups.append([r])

merged = []
for k, g in enumerate(groups):
    parts = sorted({p for r in g for p in (r.get("parts") or [])})
    ats = [r["at"] for r in g if r.get("at")]
    at = [round(sum(a[0] for a in ats) / len(ats), 2), round(sum(a[1] for a in ats) / len(ats), 2)] if ats else None
    key = "%s:%s" % (g[0]["kind"], ",".join(parts) or g[0].get("pour") or ("%.1f,%.1f" % tuple(at) if at else "?"))
    m = dict(id="CR%s-%02d" % (rnd, k + 1), key=key, kind=g[0]["kind"], tier=TIER[g[0]["kind"]], parts=parts,
             pour=g[0].get("pour"), at=at, layer=g[0].get("layer"),
             what=sorted({r.get("what", "") for r in g}, key=len)[-1],
             workers=sorted({r["_worker"] for r in g}), methods=sorted({r["_method"] for r in g}),
             open_nets=sorted({n for r in g for n in (r["evidence"].get("open_nets") or [])}),
             evidence=[dict(worker=r["_worker"], id=r.get("id"), **r["evidence"]) for r in g],
             estimates=sorted({r.get("closes_estimate") for r in g if r.get("closes_estimate") is not None}),
             design_rows=sorted({d for r in g for d in (r.get("design_rows") or [])}),
             tested_gain=None, tested_how="untested")
    for t in tested:
        mt = t.get("match", {})
        if mt.get("id") == m["id"] or (mt.get("kind") == m["kind"] and set(mt.get("parts") or []) & set(parts)) or \
                (mt.get("kind") == m["kind"] and mt.get("pour") and mt.get("pour") == m["pour"]):
            m["tested_gain"], m["tested_how"] = t.get("gain"), "%s (seeds %s)" % (t.get("how", ""), t.get("seeds"))
            m["verdict"] = t.get("verdict") or ("refuted" if t.get("refuted") else "tested")
            m["lost"] = t.get("lost") or []
    merged.append(m)

held, send = [], []
moved = {p for h in history if h.get("decision") in ("accepted", "modified") for p in (h.get("parts") or [])}
rejected = {h.get("key") for h in history if h.get("decision") == "rejected"}
for m in merged:
    if m["key"] in rejected:
        m["held"] = "rejected in an earlier round"
        held.append(m)
    elif m["tier"] == "placement" and set(m["parts"]) & moved:
        m["held"] = "touches a part that an accepted change already moved (%s)" % ", ".join(sorted(set(m["parts"]) & moved))
        held.append(m)
    else:
        send.append(m)
send.sort(key=lambda m: (-(m["tested_gain"] if m["tested_gain"] is not None else -1), -len(m["methods"]),
                         -len(m["workers"]), -(max(m["estimates"]) if m["estimates"] else 0)))
json.dump(dict(round=rnd, send=send, held=held, problems=problems),
          open(os.path.join(race, "change_requests.json"), "w"), indent=1)


def row(m):
    gain = ("%+.1f, %s%s" % (m["tested_gain"], m.get("verdict", "tested"),
                             ("; loses " + ", ".join(m["lost"])) if m.get("lost") else "")
            ) if m["tested_gain"] is not None else "untested"
    est = ("%s (estimate)" % "-".join(str(e) for e in (m["estimates"][:1] + m["estimates"][-1:] if len(m["estimates"]) > 1
                                                      else m["estimates"]))) if m["estimates"] else "-"
    return "| %s | %s | %s | %s | %s | %d workers, %d methods (%s) | %s | %s | %s |" % (
        m["id"], m["tier"], m["kind"], m["what"], ", ".join(m["parts"]) or m["pour"] or "-", len(m["workers"]),
        len(m["methods"]), ", ".join(m["methods"]), gain, est, ", ".join(m["design_rows"]) or "-")


L = ["# Change requests, round %s" % rnd, "",
     "Merged from %d worker requests into %d. Sorted by tested gain, then by the number of methods that support "
     "the request. A gain is tested only when the column says so; the workers' estimates are estimates." % (
         len(reqs), len(merged)), "",
     "| ID | Tier | Kind | What | Parts or pour | Support | Tested gain (connections) | Workers' estimate | Design rows to check |",
     "|---|---|---|---|---|---|---|---|---|"]
L += [row(m) for m in send] or ["| none | | | | | | | | |"]
L += ["", "Tiers: plan = the orchestrator applies it in the next round; placement = the design session decides "
      "(part move, swap, rotation within the design rules); ruling = the operator decides (DNP removal, a new pour "
      "or rail, rule set, layer count, outline), asked through the design session.", "", "## Evidence", ""]
for m in send:
    L.append("- **%s** %s at %s: open nets %s. %s" % (m["id"], m["what"], m["at"], ", ".join(m["open_nets"]) or "-",
                                                    "; ".join("%s: %s%s" % (e["worker"], e.get("report", ""),
                                                                           (", capacity %s demand %s" % (e.get("capacity"), e.get("demand")))
                                                                           if e.get("capacity") is not None else "")
                                                              for e in m["evidence"])))
    L.append("  Tested: %s." % m["tested_how"])
if held:
    L += ["", "## Held back (not sent)", ""]
    L += ["- %s %s: %s" % (m["id"], m["what"], m["held"]) for m in held]
if problems:
    L += ["", "## Requests that were not merged", ""] + ["- " + p for p in problems]
open(os.path.join(race, "CHANGE_REQUESTS.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
print("\n".join(L))
