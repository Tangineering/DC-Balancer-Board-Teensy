#!/usr/bin/env bash
# Full CR regeneration (run from hardware/charger_evm_r8): libraries, schematic, ERC, placement, power copper and
# pours, PathFinder signal routing, GND plane vias and leftovers, stitching vias.
set -e
export MSYS_NO_PATHCONV=1      # keep net names such as /GND and /3V3 intact on the command line
PY="/c/Life Ops/School/Thesis/DC-Balancer-round4/tools/pcb/.venv/Scripts/python.exe"
K="/c/Program Files/KiCad/9.0/bin/kicad-cli.exe"
bash gen/make_board.sh cr
cp cr/cr.kicad_pcb cr/cr_placed.kicad_pcb
(cd gen && ROUTE_SKIP_FR=1 "$PY" route.py cr ../cr 2>&1 | grep -v -E "leak|image handler")
cp cr/cr.kicad_pcb cr/cr_pours.kicad_pcb
"$K" pcb drc --format report --severity-all --schematic-parity -o cr/drc_finish.rpt cr/cr.kicad_pcb >/dev/null || true
"$PY" gen/finish_dump.py cr/cr.kicad_pcb cr/drc_finish.rpt cr/pf_dump.json F.Cu,In2.Cu,B.Cu 2>&1 | grep -v -E "leak|image"
"$PY" -u gen/pathfinder.py cr/pf_dump.json cr/pf_routes.json --track 0.127 --clear 0.127 --plane-net /GND --keep /GND --iters "${PF_ITERS:-40}"
"$PY" gen/finish_apply.py cr/cr.kicad_pcb cr/pf_routes.json 2>&1 | grep -v -E "leak|image"
PROTECT=/3V3 bash gen/finish.sh cr F.Cu,In2.Cu,B.Cu 0.6 0.3 /GND 6 0.1 0.127
(cd gen && ROUTE_STITCH_ONLY=1 "$PY" route.py cr ../cr 2>&1 | grep -v -E "leak|image handler")
