#!/usr/bin/env bash
# CR signal routing from a board that already has its power copper and pours (make_cr_all.sh up to route.py):
# PathFinder, GND plane vias and leftovers, stitching vias. Run from hardware/charger_evm_r8.
set -e
export MSYS_NO_PATHCONV=1
PY="/c/Life Ops/School/Thesis/DC-Balancer-round4/tools/pcb/.venv/Scripts/python.exe"
K="/c/Program Files/KiCad/9.0/bin/kicad-cli.exe"
cp cr/cr_pours.kicad_pcb cr/cr.kicad_pcb
"$K" pcb drc --format report --severity-all --schematic-parity -o cr/drc_finish.rpt cr/cr.kicad_pcb >/dev/null || true
"$PY" gen/finish_dump.py cr/cr.kicad_pcb cr/drc_finish.rpt cr/pf_dump.json F.Cu,In2.Cu,B.Cu 2>&1 | grep -v -E "leak|image"
"$PY" -u gen/pathfinder.py cr/pf_dump.json cr/pf_routes.json --track 0.127 --clear 0.127 --plane-net /GND --keep /GND --iters "${PF_ITERS:-40}"
"$PY" gen/finish_apply.py cr/cr.kicad_pcb cr/pf_routes.json 2>&1 | grep -v -E "leak|image"
PROTECT=/3V3 bash gen/finish.sh cr F.Cu,In2.Cu,B.Cu 0.6 0.3 /GND 6 0.1 0.127
(cd gen && ROUTE_STITCH_ONLY=1 "$PY" route.py cr ../cr 2>&1 | grep -v -E "leak|image handler")
echo "route_cr_pf done"
