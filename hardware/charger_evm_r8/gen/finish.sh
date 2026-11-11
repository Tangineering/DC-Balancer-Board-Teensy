#!/usr/bin/env bash
# Finishing router loop: DRC -> dump -> A* -> apply, until no unconnected items remain or no progress.
# Usage (from hardware/charger_evm_r8): bash gen/finish.sh <board> <layers> <via_d> <drill> [plane_net] [rounds]
B="$1"; LAYERS="$2"; VIA="$3"; DRILL="$4"; PLANE="$5"; ROUNDS="${6:-4}"; RES="${7:-0.1}"; CLEAR="${8:-0.16}"
PY="/c/Life Ops/School/Thesis/DC-Balancer-round4/tools/pcb/.venv/Scripts/python.exe"
NP="$PY"
K="/c/Program Files/KiCad/9.0/bin/kicad-cli.exe"
prev=999999
stall=0
for r in $(seq 1 "$ROUNDS"); do
  "$K" pcb drc --format report --severity-all --schematic-parity -o "$B/drc_finish.rpt" "$B/$B.kicad_pcb" >/dev/null
  n=$(grep -c "^\[unconnected_items\]" "$B/drc_finish.rpt")
  echo "round $r: unconnected $n"
  "$PY" gen/finish_cleanup.py "$B/$B.kicad_pcb" "$B/drc_finish.rpt" 2>&1 | grep -v -E "leak|image handler"
  if [ "$n" -eq 0 ]; then break; fi
  if [ "$n" -ge "$prev" ]; then stall=$((stall+1)); else stall=0; fi
  if [ "$stall" -ge 2 ]; then break; fi
  [ "$n" -lt "$prev" ] && prev=$n
  "$PY" gen/finish_dump.py "$B/$B.kicad_pcb" "$B/drc_finish.rpt" "$B/finish_dump.json" "$LAYERS" 2>&1 | grep -v -E "leak|image handler"
  extra="--protect ${PROTECT:-/3V3}"; [ -n "$PLANE" ] && extra="$extra --plane-net $PLANE"
  "$NP" gen/finish_route.py "$B/finish_dump.json" "$B/finish_routes.json" --via "$VIA" --drill "$DRILL" --res "$RES" --clear "$CLEAR" --track "${TRACK:-$CLEAR}" $extra
  "$PY" gen/finish_apply.py "$B/$B.kicad_pcb" "$B/finish_routes.json" 2>&1 | grep -v -E "leak|image handler"
done
