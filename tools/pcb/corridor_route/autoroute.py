"""Autorouter method, stage 1: Freerouting on a copy of the board, then a plan for the nets it left open.

Usage (pcbnew venv):
  python autoroute.py <board.kicad_pcb> <outdir> [--passes 40] [--plane-nets /GND] [--track T --clear C]
                      [--via V --drill D] [--y-flip-offset Y0] [--java PATH] [--jar PATH]

Steps:
 1. copy the board and its project files to <outdir> (the input is never modified);
 2. export Specctra DSN, run Freerouting headless, import the session, refill the zones in a second pass, save;
 3. run kicad-cli DRC and list the nets that still have open connections;
 4. write <outdir>/plan_leftover.json: every open net in mode `free`, every other net kept as it is. Route it with
    board_model.py + route_plan.py + apply_routes.py (autorouter method, stage 2).
Freerouting does not know the fab copper-to-edge rule; the board needs a keep-out band along the edge, or the
edge violations show in the score."""
import argparse
import json
import os
import re
import subprocess
import tempfile

import pcbnew
try:
    import wx
    wx.DisableAsserts()
except Exception:
    pass

from projfiles import copy_project

ap = argparse.ArgumentParser()
ap.add_argument("board")
ap.add_argument("outdir")
ap.add_argument("--passes", type=int, default=40)
ap.add_argument("--plane-nets", default="")
ap.add_argument("--track", type=float, default=None)
ap.add_argument("--clear", type=float, default=None)
ap.add_argument("--via", type=float, default=0.6)
ap.add_argument("--drill", type=float, default=0.3)
ap.add_argument("--y-flip-offset", type=float, default=None)
ap.add_argument("--timeout", type=int, default=3000)
ap.add_argument("--java", default=r"C:\Tools\jdk-25.0.5+8\bin\java.exe")
ap.add_argument("--jar", default=r"C:\Tools\freerouting\freerouting-2.5.0.jar")
ap.add_argument("--kicad-cli", default=r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe")
A = ap.parse_args()
out = copy_project(A.board, A.outdir, with_board=True)
stem = os.path.splitext(out)[0]
b = pcbnew.LoadBoard(out)
if b is None:
    raise SystemExit("cannot load %s (write paths as C:/..., not /c/...)" % out)
dsn, ses = stem + ".dsn", stem + ".ses"
pcbnew.ExportSpecctraDSN(b, dsn)
if os.path.exists(ses):
    os.remove(ses)
cmd = [A.java, "-Djava.awt.headless=true", "-jar", A.jar, "--gui.enabled=false",
       "--usage_and_diagnostic_data.disable_analytics=true", "-de", dsn, "-do", ses,
       "--router.autorouter.max_passes=%d" % A.passes]
r = subprocess.run(cmd, capture_output=True, text=True, timeout=A.timeout)
with open(os.path.join(A.outdir, "freerouting.log"), "w", encoding="utf-8") as f:
    f.write(r.stdout[-20000:] + "\n" + r.stderr[-20000:])
if not os.path.exists(ses):
    raise SystemExit("Freerouting produced no session file (see freerouting.log)")
pcbnew.ImportSpecctraSES(b, ses)
b.Save(out)
b2 = pcbnew.LoadBoard(out)
b2.BuildConnectivity()
pcbnew.ZONE_FILLER(b2).Fill(b2.Zones())
b2.Save(out)

fd, tmp = tempfile.mkstemp(suffix=".json")
os.close(fd)
subprocess.run([A.kicad_cli, "pcb", "drc", "--format", "json", "--severity-all", "-o", tmp, out],
               capture_output=True, text=True)
D = json.load(open(tmp, encoding="utf-8"))
os.remove(tmp)
plane = {n for n in A.plane_nets.split(",") if n}
open_nets = set()
for u in D.get("unconnected_items", []):
    for it in u.get("items", []):
        open_nets |= set(re.findall(r"\[([^\]]+)\]", it.get("description", "")))
open_nets -= plane
all_nets = {p.GetNetname() for fp in b2.GetFootprints() for p in fp.Pads() if p.GetNetname()}
keep = sorted((all_nets - open_nets) | plane)
ds = b2.GetDesignSettings()
rules = dict(track=A.track or max(pcbnew.ToMM(ds.m_TrackMinWidth), 0.127),
             clear=A.clear or max(pcbnew.ToMM(ds.m_MinClearance), 0.127), via=A.via, drill=A.drill)
plan = dict(rules=rules, keep_nets=keep, default=dict(mode="free", priority=5),
            note="autorouter stage 2: nets left open by Freerouting, routed free against the kept copper")
if A.y_flip_offset is not None:
    plan["frame"] = dict(y_flip_offset=A.y_flip_offset)
if plane:
    plan["plane_net"] = sorted(plane)[0]
json.dump(plan, open(os.path.join(A.outdir, "plan_leftover.json"), "w"), indent=1)
print("Freerouting done -> %s; nets with open connections: %d (%s); plan_leftover.json written" % (
    out, len(open_nets), ", ".join(sorted(open_nets)[:12]) + (" ..." if len(open_nets) > 12 else "")))
