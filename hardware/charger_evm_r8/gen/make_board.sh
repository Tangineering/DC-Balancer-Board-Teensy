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
# fab rules (tools/pcb/TOOLCHAIN.md section 3.9). CR: the OSH Park-only file (D-29 amended 2026-11-12, D-55);
# superseded: fab_4layer_5mil_oshpark_pcbway.kicad_dru (shared OSH Park/PCBWay 5/5 mil file, 2026-11-11)
if [ "$B" = cr ]; then cp ../../tools/pcb/fab_rules/fab_4layer_oshpark_only.kicad_dru "$B/$B.kicad_dru"; else
  cp ../../tools/pcb/fab_rules/fab_2layer_oshpark_pcbway.kicad_dru "$B/$B.kicad_dru"; fi
"$PY" ../../tools/pcb/fab_rules/apply_board_setup.py "$B/$B.kicad_pcb" 2>&1 | grep -v "memory leak"
if [ "$B" = cr ]; then   # OSH Park-only board minimums (D-29 amended, D-54) and the 6/6 mil Default net class (D-55)
  "$PY" -c "
import pcbnew, sys
b = pcbnew.LoadBoard(sys.argv[1]); ds = b.GetDesignSettings()
ds.m_TrackMinWidth = pcbnew.FromMM(0.127); ds.m_MinClearance = pcbnew.FromMM(0.127)
ds.m_ViasMinAnnularWidth = pcbnew.FromMM(0.1016); ds.m_ViasMinSize = pcbnew.FromMM(0.4572)
ds.m_HoleToHoleMin = pcbnew.FromMM(0.127)
nc = ds.m_NetSettings.GetDefaultNetclass()
nc.SetTrackWidth(pcbnew.FromMM(0.1524)); nc.SetClearance(pcbnew.FromMM(0.1524))
nc.SetViaDiameter(pcbnew.FromMM(0.6)); nc.SetViaDrill(pcbnew.FromMM(0.3))
pcbnew.SaveBoard(sys.argv[1], b)" "$B/$B.kicad_pcb" 2>&1 | grep -v "memory leak" || true
  # silkscreen cleanup (D-12; D-55, review m-7)
  "$PY" gen/silk_fix.py "$B/$B.kicad_pcb" 2>&1 | grep -v "memory leak" || true
fi
