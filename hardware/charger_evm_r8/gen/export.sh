#!/usr/bin/env bash
# Export one board's fabrication package into fab/<board>_<date>/ (tools/pcb/TOOLCHAIN.md sections 3.6-3.8a).
# Usage (from hardware/charger_evm_r8): bash gen/export.sh <cr|eib> <date>
set -e
B="$1"; D="${2:-2026-11-11}"
K="/c/Program Files/KiCad/9.0/bin/kicad-cli.exe"
VENV="/c/Life Ops/School/Thesis/DC-Balancer-round4/tools/pcb/.venv/Scripts"
O="fab/${B}_${D}"
rm -rf "$O"; mkdir -p "$O"/gerbers "$O"/drill "$O"/assembly "$O"/docs "$O"/reports
SCH="$B/$B.kicad_sch"; PCB="$B/$B.kicad_pcb"
if [ "$B" = cr ]; then
  CU="F.Cu,In1.Cu,In2.Cu,B.Cu"
else
  CU="F.Cu,B.Cu"
fi
LAYERS="$CU,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts"

# checks (the package is written only from a board that passes both)
"$K" sch erc --format report --severity-all --exit-code-violations -o "$O/reports/erc.rpt" "$SCH" >/dev/null \
  || "$K" sch erc --format report --severity-all --exit-code-violations -o "$O/reports/erc.rpt" "$SCH" >/dev/null
"$K" pcb drc --format report --severity-all --schematic-parity --exit-code-violations -o "$O/reports/drc.rpt" "$PCB" >/dev/null

# fabrication
"$K" pcb export gerbers --layers "$LAYERS" --subtract-soldermask -o "$O/gerbers/" "$PCB" >/dev/null
"$K" pcb export drill --format excellon --excellon-separate-th --generate-map --map-format pdf -o "$O/drill/" "$PCB" >/dev/null
"$K" pcb export drill --format excellon --excellon-separate-th --generate-map --map-format gerberx2 -o "$O/drill/" "$PCB" >/dev/null
(cd "$O" && powershell -NoProfile -Command "Compress-Archive -Force -Path gerbers\*, drill\*.drl -DestinationPath ${B}_gerbers_drill.zip" >/dev/null)

# assembly
"$K" pcb export pos --format csv --units mm --side both --exclude-dnp -o "$O/assembly/${B}-pos.csv" "$PCB" >/dev/null
"$K" sch export bom --fields "Reference,Value,Footprint,MPN,Manufacturer,\${DNP},\${QUANTITY}" \
  --labels "Refs,Value,Footprint,MPN,Manufacturer,DNP,Qty" --group-by "Value,Footprint,MPN,\${DNP}" \
  --ref-range-delimiter "" -o "$O/assembly/${B}-bom.csv" "$SCH" >/dev/null
INTERACTIVE_HTML_BOM_CLI_MODE=1 INTERACTIVE_HTML_BOM_NO_DISPLAY=1 "$VENV/generate_interactive_bom.exe" --no-browser \
  --dest-dir "$(cd "$O/assembly" && pwd -W)" --name-format "%f_ibom" --extra-fields "MPN,Manufacturer" \
  --dnp-field "" "$PCB" >/dev/null 2>&1 || echo "ibom FAILED"

# documentation
"$K" sch export pdf -o "$O/docs/${B}-schematic.pdf" "$SCH" >/dev/null
"$K" pcb export pdf --layers "$CU,F.SilkS,B.SilkS,F.Fab,B.Fab,F.Mask,B.Mask" --common-layers Edge.Cuts \
  --mode-multipage --include-border-title --sketch-pads-on-fab-layers --crossout-DNP-footprints-on-fab-layers \
  -o "$O/docs/" "$PCB" >/dev/null && mv "$O/docs/${B}.pdf" "$O/docs/${B}-pcb.pdf"
"$K" pcb export step --subst-models --force -o "$O/docs/${B}.step" "$PCB" >/dev/null 2>&1 || echo "step FAILED"
"$K" sch export netlist --format kicadsexpr -o "$O/docs/${B}.net" "$SCH" >/dev/null

# KiKit fab presets (TOOLCHAIN 3.8)
"$VENV/kikit.exe" fab jlcpcb --drc --assembly --missingWarn --field MPN --schematic "$SCH" "$PCB" "$O/kikit_jlcpcb" >/dev/null 2>"$O/reports/kikit_jlcpcb.log" || echo "kikit jlcpcb FAILED"
"$VENV/kikit.exe" fab pcbway --drc --assembly --schematic "$SCH" --manufacturer Manufacturer --partNumber MPN "$PCB" "$O/kikit_pcbway" >/dev/null 2>"$O/reports/kikit_pcbway.log" || echo "kikit pcbway FAILED"
"$VENV/kikit.exe" fab oshpark --drc "$PCB" "$O/kikit_oshpark" >/dev/null 2>"$O/reports/kikit_oshpark.log" || echo "kikit oshpark FAILED"
echo "exported $O"; ls "$O"
