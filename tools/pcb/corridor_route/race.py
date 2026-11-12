"""Routing race helper: prepare one work folder per entry, and rank the scored attempts of all entries.

Usage (any Python 3):
  python race.py init <board.kicad_pcb> <racedir> --entries corridor,direction,auto [--note TEXT]
  python race.py rank <racedir>

init: creates <racedir>/<entry>/ for each entry with a copy of the board and its project files (same base name),
and writes <racedir>/race.json. The original board is only read.
rank: reads every score.json below <racedir> (written by score.py), sorts by the rank vector (open non-plane
connections, new DRC violations, extra pour islands, vias, track length; lower is better, left to right) and
writes <racedir>/RANKING.md. An attempt with new DRC violations ranks below every attempt without them that has
the same open connections."""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from projfiles import copy_project  # noqa: E402


def init(board, racedir, entries, note):
    os.makedirs(racedir, exist_ok=True)
    made = []
    for e in entries:
        d = os.path.join(racedir, e)
        if os.path.exists(d) and os.listdir(d):
            raise SystemExit("%s exists and is not empty; a race folder is never reused" % d)
        made.append(copy_project(board, d, with_board=True))
    json.dump(dict(board=os.path.abspath(board), entries=entries, note=note),
              open(os.path.join(racedir, "race.json"), "w"), indent=1)
    print("race folders:\n  " + "\n  ".join(made))


def rank(racedir):
    rows = []
    for f in glob.glob(os.path.join(racedir, "**", "*.json"), recursive=True):
        try:
            S = json.load(open(f))
        except Exception:
            continue
        if not isinstance(S, dict) or "rank" not in S or "open_other" not in S:
            continue
        rel = os.path.relpath(f, racedir).replace("\\", "/")
        rows.append((S["rank"], rel.split("/")[0], rel, S))
    rows.sort(key=lambda r: r[0])
    L = ["# Race ranking", "",
         "Sorted by: open connections on non-plane nets, new DRC violations, extra pour islands, vias, track length.",
         "", "| # | Entry | Attempt (score file) | Open connections | New DRC | Extra islands | Vias | Length (mm) | Label |",
         "|---|---|---|---|---|---|---|---|---|"]
    for i, (rk, entry, rel, S) in enumerate(rows):
        L.append("| %d | %s | %s | %d | %d | %d | %d | %.0f | %s |" % (i + 1, entry, rel, rk[0], rk[1], rk[2], rk[3], rk[4],
                                                                    S.get("label", "")))
    if rows:
        best = {}
        for rk, entry, rel, S in rows:
            best.setdefault(entry, (rk, rel))
        L += ["", "## Best attempt of each entry", "", "| Entry | Attempt | Rank vector |", "|---|---|---|"]
        L += ["| %s | %s | %s |" % (e, rel, rk) for e, (rk, rel) in best.items()]
        w = rows[0]
        L += ["", "Winner: %s (%s). Open connections by net: %s." % (
            w[1], w[2], ", ".join("%s %d" % kv for kv in sorted(w[3].get("open_by_net", {}).items(),
                                                                key=lambda kv: -kv[1])) or "none")]
    else:
        L.append("| - | no score.json found | | | | | | | |")
    txt = "\n".join(L) + "\n"
    open(os.path.join(racedir, "RANKING.md"), "w", encoding="utf-8").write(txt)
    print(txt)


if len(sys.argv) >= 3 and sys.argv[1] == "rank":
    rank(sys.argv[2])
elif len(sys.argv) >= 4 and sys.argv[1] == "init":
    args = sys.argv[4:]
    ent = args[args.index("--entries") + 1].split(",") if "--entries" in args else ["corridor", "direction", "auto"]
    note = args[args.index("--note") + 1] if "--note" in args else ""
    init(sys.argv[2], sys.argv[3], ent, note)
else:
    raise SystemExit(__doc__)
