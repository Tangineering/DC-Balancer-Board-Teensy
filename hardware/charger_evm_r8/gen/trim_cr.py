"""Trim the routed CR to its final outline and add the corner mounting holes (D-60; route-race R9-02).

Runs tools/pcb/corridor_route/trim_outline.py --apply on cr/cr.kicad_pcb with the D-60 arguments into a work
folder, checks that the trimmed outline and the hole centres equal cr_geometry.FINAL_OUTLINE and
cr_geometry.MOUNTING_HOLES (0.01 mm), and copies the trimmed board back over cr/cr.kicad_pcb. The project file
cr/cr.kicad_pro is not touched. Run gen/silk_refs.py afterwards (references near the new edge), then DRC and
gen/check_constraints.py.
Usage (from hardware/charger_evm_r8, pcbnew venv): python gen/trim_cr.py <work dir> [--check-only]"""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cr_geometry as G  # noqa: E402
import mb_brd as M  # noqa: E402

work = os.path.abspath(sys.argv[1])
check_only = "--check-only" in sys.argv
os.makedirs(work, exist_ok=True)
here = os.path.dirname(os.path.abspath(__file__))
tool = os.path.normpath(os.path.join(here, "..", "..", "..", "tools", "pcb", "corridor_route", "trim_outline.py"))
board = os.path.normpath(os.path.join(here, "..", "cr", "cr.kicad_pcb"))
args = [sys.executable, tool, board, work, "--y-flip-offset", "%g" % G.YOFF, "--margin", "%g" % G.TRIM_MARGIN,
        "--ear", "%g,%g,%g,%g" % G.KEY_EAR, "--hole-drill", "%g" % G.HOLE_DRILL,
        "--hole-keepout", "%g" % G.HOLE_KEEPOUT, "--hole-board", "%g" % G.HOLE_HEAD,
        "--flip-centre", "%g,%g" % G.CHG_CENTRE]
for t in G.TERMINALS:   # TB005-762 bodies on .brd layer 51 (D-41 key)
    e = M.extent(M.part(t), [M.L_DOCU], False, ("wire",))
    args += ["--flip-block", "%s:%g,%g,%g,%g" % ((t,) + tuple(e))]
if not check_only:
    args.append("--apply")
r = subprocess.run(args, capture_output=True, text=True)
sys.stdout.write(r.stdout[-3000:])
if r.returncode:
    sys.stderr.write(r.stderr[-3000:])
    raise SystemExit("trim_outline.py failed")
res = json.load(open(os.path.join(work, "trim.json")))
outline = [tuple(v) for v in res["outline_plan"]]
holes = [tuple(v) for v in res["holes_plan"]]
want = [tuple(v) for v in G.FINAL_OUTLINE]
bad = []
if len(outline) != len(want) or any(abs(a - b) > 0.01 for p, q in zip(outline, want) for a, b in zip(p, q)):
    bad.append("outline %s differs from cr_geometry.FINAL_OUTLINE" % outline)
if any(abs(a - b) > 0.01 for p, q in zip(holes, G.MOUNTING_HOLES.values()) for a, b in zip(p, q)):
    bad.append("holes %s differ from cr_geometry.MOUNTING_HOLES" % holes)
if res.get("warnings"):
    bad.append("warnings: %s" % res["warnings"])
if bad:
    raise SystemExit("refused: " + "; ".join(bad))
if not check_only:
    shutil.copy2(os.path.join(work, "cr.kicad_pcb"), board)
    print("trimmed board copied to", board)
print("outline and holes match cr_geometry (D-60)")
