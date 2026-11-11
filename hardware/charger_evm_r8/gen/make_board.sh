#!/usr/bin/env bash
# Regenerate one board from netlist.py: footprint library, symbol library + schematic, ERC, netlist export,
# placed board. Usage: bash gen/make_board.sh <cr|eib>   (run from hardware/charger_evm_r8)
set -e
B="$1"
PY="/c/Life Ops/School/Thesis/DC-Balancer-round4/tools/pcb/.venv/Scripts/python.exe"
K="/c/Program Files/KiCad/9.0/bin/kicad-cli.exe"
"$PY" gen/fplib.py "$B" "$B" 2>&1 | grep -v "memory leak" || true
"$PY" gen/sch.py "$B" "$B" >/dev/null
"$K" sch erc --format report --severity-all --exit-code-violations -o "$B/erc.rpt" "$B/$B.kicad_sch" >/dev/null \
  || "$K" sch erc --format report --severity-all --exit-code-violations -o "$B/erc.rpt" "$B/$B.kicad_sch" >/dev/null \
  || { echo "ERC violations in $B (see $B/erc.rpt)"; }
"$K" sch export netlist --format kicadsexpr -o "$B/$B.net" "$B/$B.kicad_sch" >/dev/null
(cd gen && "$PY" -X faulthandler pcbbuild.py "$B" "../$B" 2>&1 | grep -v "memory leak")
# fab rules (tools/pcb/TOOLCHAIN.md section 3.9)
if [ "$B" = cr ]; then cp ../../tools/pcb/fab_rules/fab_4layer_oshpark_pcbway.kicad_dru "$B/$B.kicad_dru"; else
  cp ../../tools/pcb/fab_rules/fab_2layer_oshpark_pcbway.kicad_dru "$B/$B.kicad_dru"; fi
"$PY" ../../tools/pcb/fab_rules/apply_board_setup.py "$B/$B.kicad_pcb" 2>&1 | grep -v "memory leak"
