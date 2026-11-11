#!/usr/bin/env bash
# Full EIB regeneration: libraries, schematic, ERC, placement, routing (Freerouting + finishing router),
# silkscreen cleanup. Run from hardware/charger_evm_r8.
set -e
PY="/c/Life Ops/School/Thesis/DC-Balancer-round4/tools/pcb/.venv/Scripts/python.exe"
bash gen/make_board.sh eib
cp eib/eib.kicad_pcb eib/eib_placed.kicad_pcb
(cd gen && "$PY" route.py eib ../eib 2>&1 | grep -v -E "leak|image handler")
bash gen/finish.sh eib F.Cu,B.Cu 0.6 0.3 "" 6 0.05 0.16
