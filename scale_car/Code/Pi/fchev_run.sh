#!/usr/bin/env bash
# =============================================================================
# fchev_run.sh — one-command launcher for the FCHEV scaled car
# UC Davis Future Mobility Lab
# Rev 2026-10-19A
#
# Brings up every node in its own tmux pane, in the correct order, with the
# right delays between them. One SSH login, one command, everything running.
#
# Lives on the Pi at:  ~/fchev/fchev_run.sh
#
#   ./fchev_run.sh           interactive menu
#   ./fchev_run.sh --attach  reattach to a session already running
#   ./fchev_run.sh --stop    graceful shutdown, correct reverse order
#   ./fchev_run.sh --status  what is running right now
#   ./fchev_run.sh --teensy  raw UDP check, no ROS 2 (Ops Guide 2.4 / 9.4)
#   ./fchev_run.sh --check   post-launch verification (Ops Guide 4.1-4.6)
#
# NOTE on the Ops Guide: sections 2.4 and 9.4 tell you to run
# simple_ems_test_2026-03-16A.py. That script is the old 54-byte parser and
# discards every v4 packet, so it always reports "no Teensy packet" even when
# tcpdump shows traffic arriving. Use --teensy instead; it decodes v4.
#
# Why tmux: the session lives on the Pi, not in your SSH client. If the link
# drops (or Ethernet comes up and knocks the route out) the nodes keep running
# and you just reattach. Closing your laptop does not stop the experiment.
#
# Inside tmux:
#   Ctrl+b then d     detach, leave everything running
#   Ctrl+b then o     cycle focus between panes
#   Ctrl+b then z     zoom the focused pane full screen (again to unzoom)
#   Ctrl+b then [     scroll mode, q to exit
# =============================================================================

set -uo pipefail

SESSION="fchev"
PKG="fchev_ems"
LOGDIR="$HOME/fchev/logs"
CYCDIR="$HOME/fchev/drive_cycles"
SRC="source /opt/ros/jazzy/setup.bash && source $HOME/ros2_ws/install/setup.bash && export ROS_DOMAIN_ID=42 && export RMW_IMPLEMENTATION=rmw_fastrtps_cpp"

# Startup gaps. The bridge must be publishing /vehicle_state before the EMS
# starts, or the EMS sees stale state and immediately commands SAFE.
GAP_BRIDGE=3
GAP_EMS=2
GAP_BAG=1

C_HDR=$'\033[1;36m'; C_OK=$'\033[0;32m'; C_WARN=$'\033[1;33m'
C_ERR=$'\033[0;31m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'

say()  { echo -e "${C_HDR}$*${C_OFF}"; }
ok()   { echo -e "${C_OK}  $*${C_OFF}"; }
warn() { echo -e "${C_WARN}  $*${C_OFF}"; }
err()  { echo -e "${C_ERR}  $*${C_OFF}"; }
dim()  { echo -e "${C_DIM}  $*${C_OFF}"; }

# read_num <varname> <prompt> <default> [min] [max]
# Re-prompts until the answer is a real number. A non-numeric answer here used
# to be passed straight through as a ROS parameter override, which kills the
# node at declare_parameter() with InvalidParameterTypeException — the node
# then never publishes /ems_command and the Teensy sits in State 1.
read_num() {
  local __var="$1" __prompt="$2" __def="$3" __min="${4:-}" __max="${5:-}"
  local __ans
  while true; do
    read -rp "  ${__prompt} [${__def}]: " __ans
    __ans="${__ans:-$__def}"
    if [[ ! "$__ans" =~ ^-?([0-9]+\.?[0-9]*|\.[0-9]+)$ ]]; then
      err "\"$__ans\" is not a number. Enter a value like ${__def}, or press Enter for the default."
      continue
    fi
    if [[ -n "$__min" ]] && awk "BEGIN{exit !($__ans < $__min)}"; then
      err "must be at least ${__min}"
      continue
    fi
    if [[ -n "$__max" ]] && awk "BEGIN{exit !($__ans > $__max)}"; then
      err "must be at most ${__max}"
      continue
    fi
    printf -v "$__var" '%s' "$__ans"
    return 0
  done
}

# ── Preflight ────────────────────────────────────────────────────────────────
need_tmux() {
  if ! command -v tmux >/dev/null 2>&1; then
    err "tmux is not installed. Install it with:"
    echo "      sudo apt install tmux -y"
    exit 1
  fi
}

session_exists() { tmux has-session -t "$SESSION" 2>/dev/null; }

# tmux send-keys does NOT wait for the pane's shell to be ready. A freshly
# created pane is still sourcing .bashrc — which on this Pi sources ROS, about
# a second — and anything sent during that window can be dropped. The node then
# never starts, the EMS never publishes, and the Teensy sits in Idle wondering
# why. Prove the shell is reading input by round-tripping a token first.
wait_pane_ready() {
  local pane="$1"
  local token="FCHEVREADY${$}"
  local tries=0
  tmux send-keys -t "$SESSION:run.$pane" "echo $token" C-m 2>/dev/null
  while (( tries < 75 )); do          # 75 x 0.2s = 15s ceiling
    if tmux capture-pane -p -t "$SESSION:run.$pane" 2>/dev/null \
         | grep -qx "$token"; then
      return 0
    fi
    sleep 0.2
    tries=$((tries + 1))
  done
  warn "pane $pane shell did not respond in 15s — sending anyway"
  return 1
}

# Send a command to a pane, but only once that pane can actually receive it.
pane_run() {
  local pane="$1"; shift
  wait_pane_ready "$pane"
  tmux send-keys -t "$SESSION:run.$pane" "$SRC" C-m
  wait_pane_ready "$pane"
  tmux send-keys -t "$SESSION:run.$pane" "clear && $*" C-m
}

# ── --status ─────────────────────────────────────────────────────────────────
do_status() {
  need_tmux
  if session_exists; then
    say "Session '$SESSION' is running:"
    tmux list-panes -t "$SESSION" -F "  pane #{pane_index}  #{pane_title}  #{pane_current_command}"
    echo
    dim "Reattach with:  ./fchev_run.sh --attach"
  else
    say "No '$SESSION' session running."
  fi
  echo
  say "ROS 2 nodes visible right now:"
  bash -c "$SRC && ros2 node list" 2>/dev/null | sed 's/^/  /' || dim "  (none)"
  exit 0
}

# ── --teensy ─────────────────────────────────────────────────────────────────
# Raw UDP read, no ROS 2. This is what Ops Guide 2.4 and 9.4 are asking for.
# Replaces simple_ems_test_2026-03-16A.py, which still parses the old 54-byte
# packet and therefore silently discards everything the v4 firmware sends.
do_teensy() {
  local nsec="${1:-5}"
  say "Raw UDP check — listening on port 5000 for ${nsec}s"
  dim "(no ROS 2 involved; this is the pre-launch sanity check)"
  echo

  if command -v ss >/dev/null 2>&1 && ss -ulpn 2>/dev/null | grep -q ':5000 '; then
    err "Port 5000 is already bound — the bridge is probably running."
    dim "Stop it first, or use './fchev_run.sh --check' to read /vehicle_state instead."
    exit 1
  fi

  TEENSY_SECS="$nsec" python3 -I - <<'PY'
import os, socket, struct, sys, time

FMT  = "<BIH" + "f"*10 + "HHBBHBBB"
SIZE = struct.calcsize(FMT)          # 58
assert SIZE == 58

FAULTS = [(0x0001,"OC_FC"),(0x0002,"UV_BATT"),(0x0004,"OV_BUS"),
          (0x0008,"SWITCH_CONFLICT"),(0x0010,"PI_TIMEOUT"),(0x0020,"OV_BATT"),
          (0x0040,"UV_FC"),(0x0080,"OC_BT"),(0x0100,"UV_BUS"),
          (0x0200,"OV_RGN"),(0x0400,"OV_CHG"),(0x0800,"I2C_CHARGER"),
          (0x1000,"CHARGER_STAT"),(0x2000,"INIT_FAIL"),(0x4000,"MOT_HOTPLUG"),
          (0x8000,"ERROR")]
MODES = {0:"HYBRID",1:"FC_ONLY",2:"BATT",3:"CHARGE",4:"SAFE"}

def faults_str(f):
    return "none" if f == 0 else " ".join(n for b,n in FAULTS if f & b)

def xor(d):
    r = 0
    for b in d: r ^= b
    return r

secs = float(os.environ.get("TEENSY_SECS", "5"))
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.bind(("0.0.0.0", 5000))
except OSError as e:
    print(f"  cannot bind port 5000: {e}")
    print()
    print("  Something already holds it — almost always teensy_bridge.")
    print("  Stop it, or use './fchev_run.sh --check' to read /vehicle_state instead.")
    sys.exit(1)
s.settimeout(1.0)

n = bad = dropped = 0
prev = None
last = None
t0 = time.monotonic()
while time.monotonic() - t0 < secs:
    try:
        pkt, _ = s.recvfrom(256)
    except socket.timeout:
        continue
    if len(pkt) != SIZE or pkt[0] != 0xAA or xor(pkt[1:-1]) != pkt[-1]:
        bad += 1
        continue
    f = struct.unpack(FMT, pkt)
    ctr = f[2]
    if prev is not None:
        gap = (ctr - prev) & 0xFFFF
        if gap > 1:
            dropped += gap - 1
    prev = ctr
    n += 1
    last = f
s.close()

el = time.monotonic() - t0
if n == 0:
    print("  NO PACKETS RECEIVED")
    print()
    print("  If tcpdump shows traffic but this does not, something else holds")
    print("  port 5000. Check:  sudo ss -ulpn | grep 5000")
    print("  If tcpdump is also silent, the Teensy is not transmitting — check")
    print("  that the firmware was flashed with USE_ETHERNET=1 (the boot banner")
    print("  must say 'Listening on port 5001', not 'BENCH MODE').")
    sys.exit(1)

(_, ts, ctr, v, Vb, Ib, Ic, Vfc, Ifc, Vbus, Vrgn, Vchg, sha,
 dFC, dBT, chg, sw, flt, ec, es, _cs) = last

rate = n / el
print(f"  packets       {n} in {el:.1f}s  ({rate:.1f} Hz, expect ~50)")
print(f"  dropped       {dropped}")
print(f"  malformed     {bad}")
print()
print(f"  v_actual      {v:.3f} m/s")
print(f"  V_batt        {Vb:.2f} V      {'OK' if Vb > 6.2 else 'LOW — below 6.2 V cutoff'}")
print(f"  I_batt        {Ib:.3f} A")
print(f"  V_fc          {Vfc:.2f} V")
print(f"  I_fc          {Ifc:.3f} A      {'OK' if Ifc < 1.4 else 'OVER 1.4 A bus-side limit'}")
print(f"  V_bus         {Vbus:.2f} V      {'OK' if 12.0 <= Vbus <= 17.5 else 'OUT OF RANGE (12.0-17.5)'}")
print(f"  V_rgn         {Vrgn:.2f} V")
print(f"  share_actual  {sha:.3f}" + ("   (meaningless at standstill)" if abs(Ifc)+abs(Ib) < 0.05 else ""))
print(f"  switch_state  0x{sw:02X}")
print(f"  faults        0x{flt:04X}   {faults_str(flt)}")
if ec:
    print(f"  error_code    0x{ec:02X}  latched from state {es}")
print()
if flt == 0 and dropped == 0 and rate > 45:
    print("  Clean. Safe to launch.")
    sys.exit(0)
if flt:
    print("  FAULTS LATCHED — the Teensy will refuse to run. Diagnose before reset.")
if dropped:
    print(f"  {dropped} packets dropped — check the Ethernet route (see --check).")
if rate <= 45:
    print(f"  Rate {rate:.1f} Hz is low — expect ~50 Hz.")
sys.exit(2)
PY
  exit $?
}

# ── --check ──────────────────────────────────────────────────────────────────
# Post-launch verification, Ops Guide 4.1 through 4.6, in one pass.
do_check() {
  say "Post-launch verification"
  echo

  say "Nodes (4.1)"
  bash -c "$SRC && ros2 node list" 2>/dev/null | sed 's/^/    /' || true
  echo

  say "Topics (4.2)"
  bash -c "$SRC && ros2 topic list" 2>/dev/null | sed 's/^/    /' || true
  echo

  say "Rates (4.3)"
  for t in /vehicle_state /ems_command; do
    r=$(bash -c "$SRC && timeout 4 ros2 topic hz $t 2>/dev/null | grep -m1 'average rate'" || true)
    if [[ -n "$r" ]]; then
      ok "$t  ${r#*: }"
    else
      err "$t  no messages"
    fi
  done
  echo

  say "Vehicle state (4.4)"
  bash -c "$SRC && timeout 5 ros2 topic echo /vehicle_state --once" 2>/dev/null \
    | grep -E '^- ' | sed 's/^- //' | python3 -I -c '
import sys
NAMES = ["v_actual","V_batt","I_batt","I_charge","V_fc","I_fc","V_bus",
         "V_rgn","V_chg","share_actual","droop_FC","droop_BT",
         "charger_status","switch_state","fault_flags","error_code",
         "error_source_state","SOC"]
FAULTS = [(0x0001,"OC_FC"),(0x0002,"UV_BATT"),(0x0004,"OV_BUS"),
          (0x0008,"SWITCH_CONFLICT"),(0x0010,"PI_TIMEOUT"),(0x0020,"OV_BATT"),
          (0x0040,"UV_FC"),(0x0080,"OC_BT"),(0x0100,"UV_BUS"),
          (0x0200,"OV_RGN"),(0x0400,"OV_CHG"),(0x0800,"I2C_CHARGER"),
          (0x1000,"CHARGER_STAT"),(0x2000,"INIT_FAIL"),(0x4000,"MOT_HOTPLUG"),
          (0x8000,"ERROR")]
vals = []
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    try: vals.append(float(line))
    except ValueError: pass
if len(vals) < 18:
    print(f"    only {len(vals)} elements — expected 18. Is the bridge on the v4 packet?")
    sys.exit(0)
for i, n in enumerate(NAMES):
    v = vals[i]
    if n == "fault_flags":
        f = int(v)
        s = "none" if f == 0 else " ".join(x for b,x in FAULTS if f & b)
        print(f"    [{i:2}] {n:<18} 0x{f:04X}  {s}")
    elif n == "switch_state":
        print(f"    [{i:2}] {n:<18} 0x{int(v):02X}")
    else:
        print(f"    [{i:2}] {n:<18} {v:.3f}")
if all(x == 0.0 for x in vals):
    print()
    print("    All zeros — the bridge has never received a packet from the Teensy.")
    print("    Run  ./fchev_run.sh --teensy  with the bridge stopped.")
' || err "    could not read /vehicle_state"
  echo

  say "Comms (4.6)"
  bash -c "$SRC && timeout 5 ros2 topic echo /comms_status --once" 2>/dev/null \
    | grep -E '^- ' | sed 's/^- //' | python3 -I -c '
import sys
n = ["pkts_rx","pkts_dropped","stale_ms","link_ok"]
v = [float(x) for x in sys.stdin if x.strip()]
for i, name in enumerate(n[:len(v)]):
    print(f"    {name:<14} {v[i]:.0f}")
if len(v) >= 4 and v[3] < 1.0:
    print("    link_ok is 0 — the Teensy has gone quiet.")
' || dim "    (no /comms_status — bridge not running?)"

  echo
  say "Routing"
  if ip route show | grep -q "^default.*dev eth0"; then
    err "eth0 holds a default route — this is the setup that drops SSH and"
    err "causes packet loss when eth0 and wlan0 share 192.168.1.x. Fix with:"
    echo "      sudo ip route del default via 192.168.1.1 dev eth0"
  else
    ok "eth0 is not the default route"
  fi
  exit 0
}

# ── --attach ─────────────────────────────────────────────────────────────────
do_attach() {
  need_tmux
  if session_exists; then
    exec tmux attach -t "$SESSION"
  else
    err "No session called '$SESSION'. Start one with: ./fchev_run.sh"
    exit 1
  fi
}

# ── --stop ───────────────────────────────────────────────────────────────────
# Reverse of startup order, matching Ops Guide Section 9: drive cycle, then
# EMS, then bridge. The EMS and bridge both publish SAFE to the Teensy on
# shutdown, so this ordering leaves the hardware in a safe state.
do_stop() {
  need_tmux
  if ! session_exists; then
    warn "Nothing running."
    exit 0
  fi
  say "Stopping in safe order (drive cycle -> EMS -> bridge)..."
  for pane in 3 2 1 0; do
    if tmux list-panes -t "$SESSION" -F "#{pane_index}" 2>/dev/null | grep -qx "$pane"; then
      tmux send-keys -t "$SESSION.$pane" C-c 2>/dev/null
      sleep 1
    fi
  done
  ok "SAFE commands sent. Waiting for clean shutdown..."
  sleep 2
  tmux kill-session -t "$SESSION" 2>/dev/null
  ok "Session closed."
  echo
  warn "The Teensy latches State 99 on fault — a reset there needs the physical"
  warn "button. Check its serial output before the next run."
  exit 0
}

# ── Arg handling ─────────────────────────────────────────────────────────────
case "${1:-}" in
  --attach|-a) do_attach ;;
  --stop|-s)   do_stop ;;
  --status)    do_status ;;
  --teensy|-t) do_teensy "${2:-5}" ;;
  --check|-c)  do_check ;;
  --help|-h)
    # Print the header comment block only, stopping at the first code line.
    awk 'NR>1 { if (/^#/) { sub(/^# ?/,""); print } else { exit } }' "$0"
    exit 0 ;;
esac

need_tmux

# ── Existing session? ────────────────────────────────────────────────────────
if session_exists; then
  warn "A session called '$SESSION' is already running."
  read -rp "  [a]ttach to it, [k]ill and start fresh, [q]uit? " a
  case "$a" in
    a|A) exec tmux attach -t "$SESSION" ;;
    k|K) tmux kill-session -t "$SESSION"; ok "Killed. Starting fresh."; sleep 1 ;;
    *)   exit 0 ;;
  esac
fi

# ── Preflight: can we see the Teensy? ────────────────────────────────────────
echo
say "=============================================="
say "  FCHEV Scaled Car — Launcher"
say "=============================================="
echo
say "Preflight"

if ping -c 2 -W 1 192.168.1.50 >/dev/null 2>&1; then
  ok "Teensy reachable at 192.168.1.50"
else
  err "Teensy NOT reachable at 192.168.1.50"
  echo
  warn "Check: Ethernet cable seated, Teensy powered, firmware flashed with"
  warn "USE_ETHERNET=1. If the link worked before and the LEDs are now dark,"
  warn "re-flashing the firmware has fixed this previously."
  echo
  read -rp "  Continue anyway? [y/N] " c
  [[ "$c" =~ ^[yY] ]] || exit 1
fi

if bash -c "$SRC && ros2 pkg list 2>/dev/null | grep -qx $PKG"; then
  ok "Package $PKG found"
else
  err "ROS 2 package '$PKG' not found. Did you build the workspace?"
  echo "      cd ~/ros2_ws && colcon build --packages-select $PKG"
  exit 1
fi

# Raw UDP check before building panes. Ping only proves the Ethernet PHY is
# answering; it does not prove the firmware is actually sending telemetry.
# A build with USE_ETHERNET=0 pings fine and transmits nothing.
echo
read -rp "  Run the 3s raw UDP check first? [Y/n] " rawchk
if [[ ! "$rawchk" =~ ^[nN] ]]; then
  echo
  if ( do_teensy 3 ); then
    :
  else
    rc=$?
    echo
    if [[ $rc -eq 1 ]]; then
      err "No telemetry. Launching now would give you a bridge publishing zeros."
    else
      warn "Check flagged something above."
    fi
    read -rp "  Launch anyway? [y/N] " c
    [[ "$c" =~ ^[yY] ]] || exit 1
  fi
  echo
fi

# ── Menu: which EMS ──────────────────────────────────────────────────────────
echo
say "Which EMS?"
echo "  1) simple   rule-based on SOC — the baseline"
echo "  2) sweep    sweeps power share on a timer, ignores SOC (diagnostic)"
echo "  3) sdp      stochastic dynamic programming"
echo "  4) none     bridge only, no EMS"
echo
read -rp "  Choice [1]: " ems_choice
ems_choice="${ems_choice:-1}"

SWEEP_ARGS=""
case "$ems_choice" in
  1) EMS_EXE="simple_ems_node"; EMS_NAME="simple" ;;
  2) EMS_EXE="sweep_ems_node";  EMS_NAME="sweep"
     echo
     echo "  Waveform:  1) staircase (per-step response — better for tuning)"
     echo "             2) triangle  (continuous ramp)"
     read -rp "  Choice [1]: " wf
     if [[ "${wf:-1}" == "2" ]]; then WAVE="triangle"; else WAVE="staircase"; fi
     read_num per "Sweep period in seconds" 20 2 300
     read_num vh  "Hold speed in m/s (0 = follow drive cycle)" 1.0 0 5
     # period_s and v_hold are declared as DOUBLE in sweep_ems_node. ROS 2 infers
     # the override's type from its spelling: "20" becomes int64 and raises
     # InvalidParameterTypeException at declare_parameter(), killing the node
     # before it publishes anything. Force a decimal point so it parses as double.
     per=$(awk "BEGIN{printf \"%.3f\", $per}")
     vh=$(awk  "BEGIN{printf \"%.3f\", $vh}")
     if awk "BEGIN{exit !($vh == 0)}"; then
       SWEEP_ARGS="--ros-args -p waveform:=$WAVE -p period_s:=$per -p use_drive_cycle:=true"
     else
       SWEEP_ARGS="--ros-args -p waveform:=$WAVE -p period_s:=$per -p v_hold:=$vh"
     fi
     # Feasible-band clip: hold the command inside [I_min/I_tot, 1-I_min/I_tot],
     # the split the Teensy governor can actually deliver at the present total
     # current. Answer n for the A/B baseline. The bag name records the choice.
     echo
     echo "  Clip the command to the governor's feasible band?"
     echo "    y) ON   — command only what the hardware can deliver  (B)"
     echo "    n) OFF  — command the raw sweep, current behaviour    (A)"
     read -rp "  Choice [Y/n]: " cf
     if [[ "${cf:-y}" =~ ^[Nn] ]]; then
       SWEEP_ARGS="$SWEEP_ARGS -p clip_feasible:=false"
       EMS_NAME="sweep-noclip"
     else
       read_num imin "  SHARE_MINORITY_I_MIN_A from the firmware ('S' dump prints I_min=)" 0.125 0.05 0.50
       imin=$(awk "BEGIN{printf \"%.4f\", $imin}")
       SWEEP_ARGS="$SWEEP_ARGS -p clip_feasible:=true -p i_min:=$imin"
       EMS_NAME="sweep-clip"
     fi
     echo
     warn "sweep_ems_node ignores SOC completely. It will happily drain or"
     warn "overcharge the battery — watch SOC in the pane and stop when it"
     warn "leaves your band."
     ;;
  3) EMS_EXE="sdp_ems_node";    EMS_NAME="sdp"
     echo
     warn "Check sdp_ems_node reads the v4 indices (SOC at [17], faults at"
     warn "[14]). On the old indices it runs without erroring and optimises"
     warn "against V_batt and V_rgn instead — silently wrong results."
     read -rp "  Continue? [y/N] " c
     [[ "$c" =~ ^[yY] ]] || exit 1
     ;;
  4) EMS_EXE=""; EMS_NAME="none" ;;
  *) err "Not a choice."; exit 1 ;;
esac

# ── Menu: drive cycle ────────────────────────────────────────────────────────
echo
say "Drive cycle?"
CYCLES=()
if [[ -d "$CYCDIR" ]]; then
  while IFS= read -r f; do CYCLES+=("$f"); done < <(find "$CYCDIR" -maxdepth 1 -name '*.csv' | sort)
fi

CSV=""
if [[ ${#CYCLES[@]} -eq 0 ]]; then
  warn "No CSVs in $CYCDIR"
  echo "  1) built-in sine wave fallback (1-5 m/s, 120s)"
  echo "  2) none"
  read -rp "  Choice [2]: " dc
  [[ "${dc:-2}" == "1" ]] && CSV="BUILTIN"
else
  i=1
  for f in "${CYCLES[@]}"; do
    echo "  $i) $(basename "$f")"
    i=$((i+1))
  done
  echo "  $i) built-in sine wave fallback"
  echo "  $((i+1))) none — no drive cycle, car stays still"
  echo
  read -rp "  Choice [1]: " dc
  dc="${dc:-1}"
  if [[ "$dc" -ge 1 && "$dc" -le ${#CYCLES[@]} ]]; then
    CSV="${CYCLES[$((dc-1))]}"
  elif [[ "$dc" -eq $i ]]; then
    CSV="BUILTIN"
  fi
fi

# ── Menu: recording ──────────────────────────────────────────────────────────
echo
read -rp "Record a rosbag? [Y/n] " rec
RECORD=1
[[ "$rec" =~ ^[nN] ]] && RECORD=0

STAMP="$(date +%Y-%m-%d_%H-%M-%S)"
BAG="$LOGDIR/rosbag_${EMS_NAME}_${STAMP}"

# ── Summary ──────────────────────────────────────────────────────────────────
echo
say "=============================================="
say "  Launching"
say "=============================================="
ok "EMS          $EMS_NAME"
[[ -n "$SWEEP_ARGS" ]] && dim "             $SWEEP_ARGS"
if [[ "$CSV" == "BUILTIN" ]]; then
  ok "Drive cycle  built-in sine wave"
elif [[ -n "$CSV" ]]; then
  ok "Drive cycle  $(basename "$CSV")"
else
  ok "Drive cycle  none"
fi
if [[ $RECORD -eq 1 ]]; then
  ok "Recording    $(basename "$BAG")"
else
  warn "Recording    OFF — this run will not be saved"
fi
echo
read -rp "  Go? [Y/n] " go
[[ "$go" =~ ^[nN] ]] && { echo "  Cancelled."; exit 0; }

mkdir -p "$LOGDIR"

# ── Build the tmux session ───────────────────────────────────────────────────
# Pane 0 bridge | Pane 1 EMS | Pane 2 drive cycle | Pane 3 monitor/rosbag
tmux new-session -d -s "$SESSION" -n run -x 200 -y 50
tmux split-window -t "$SESSION:run" -h
tmux split-window -t "$SESSION:run.0" -v
tmux split-window -t "$SESSION:run.2" -v
tmux select-layout -t "$SESSION:run" tiled

tmux set-option -t "$SESSION" pane-border-status top 2>/dev/null
tmux set-option -t "$SESSION" mouse on 2>/dev/null

label() { tmux select-pane -t "$SESSION:run.$1" -T "$2" 2>/dev/null; }

# Pane 0 — bridge. Must be first; nothing else has data without it.
echo
say "Starting..."

label 0 " BRIDGE "
pane_run 0 "echo '--- teensy_bridge ---' && ros2 run $PKG teensy_bridge"

dim "bridge up, waiting ${GAP_BRIDGE}s for telemetry to flow"
sleep "$GAP_BRIDGE"

# Pane 1 — EMS
if [[ -n "$EMS_EXE" ]]; then
  label 1 " EMS: $EMS_NAME "
  pane_run 1 "echo '--- $EMS_EXE ---' && ros2 run $PKG $EMS_EXE $SWEEP_ARGS"
  dim "EMS up, waiting ${GAP_EMS}s"
  sleep "$GAP_EMS"
else
  label 1 " no EMS "
  pane_run 1 "echo 'No EMS running — bridge sends SAFE on its watchdog, so the' && echo 'Teensy will stay in State 1 (Idle). mode_cmd=4 never triggers Run.'"
fi

# Pane 3 — rosbag. Started before the drive cycle so the whole run is captured.
if [[ $RECORD -eq 1 ]]; then
  label 3 " REC "
  pane_run 3 "cd $LOGDIR && echo '--- recording ---' && ros2 bag record -a -o $BAG"
  dim "recording started, waiting ${GAP_BAG}s"
  sleep "$GAP_BAG"
else
  label 3 " MONITOR "
  pane_run 3 "echo 'Spare pane. Try:' && echo '  ros2 topic hz /vehicle_state' && echo '  ros2 topic echo /ems_command'"
fi

# Pane 2 — drive cycle. Last, because this is what starts the car moving.
if [[ -n "$CSV" ]]; then
  label 2 " DRIVE CYCLE "
  if [[ "$CSV" == "BUILTIN" ]]; then
    pane_run 2 "echo '--- drive_cycle (built-in sine) ---' && ros2 run $PKG drive_cycle_node"
  else
    pane_run 2 "echo '--- drive_cycle ---' && ros2 run $PKG drive_cycle_node --ros-args -p csv_path:=$CSV"
  fi
else
  label 2 " no drive cycle "
  pane_run 2 "echo 'No drive cycle. Car holds whatever the EMS commands.'"
fi

ok "All panes up."

# ── Did the EMS actually come up and command Run? ────────────────────────────
# The failure this catches: a node silently never started, so /ems_command
# either is not published at all or carries mode=4 (SAFE). mode_cmd=4 never
# triggers the Teensy's Idle->Run transition, so the car just sits there.
if [[ -n "$EMS_EXE" ]]; then
  echo
  dim "checking the EMS is commanding Run..."
  sleep 2
  # /ems_command = [v_setpoint, power_share, charge_goal, mode, droop_enable]
  # mode is the 4th element.
  mode=$(bash -c "$SRC && timeout 5 ros2 topic echo /ems_command --once" 2>/dev/null \
         | grep -E '^- ' | sed -n '4p' | sed 's/[^0-9.]//g')
  if [[ -z "$mode" ]]; then
    err "/ems_command is not publishing."
    warn "The EMS pane probably did not start. Check pane 1 (top-right)."
    warn "The Teensy will stay in State 1 (Idle)."
  elif [[ "${mode%%.*}" == "4" ]]; then
    warn "EMS is commanding mode=4 (SAFE) — the Teensy will NOT enter Run."
    warn "Usual cause: the EMS is not receiving /vehicle_state, so it has gone"
    warn "stale and fallen back to SAFE. Check pane 1 for 'stale' warnings,"
    warn "and confirm faults are clear with:  ./fchev_run.sh --check"
  else
    ok "EMS commanding mode=${mode%%.*} — Teensy should report State 1 -> State 2"
  fi
fi
echo
dim "Ctrl+b d to detach and leave it running   |   ./fchev_run.sh --stop to shut down"
sleep 2

tmux select-pane -t "$SESSION:run.1" 2>/dev/null
exec tmux attach -t "$SESSION"
