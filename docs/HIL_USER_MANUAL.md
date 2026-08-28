# HIL user manual — running the balancer board against a simulated plant

Operator-facing. This is the "how do I actually run it" document; the reference
material lives elsewhere and is cited rather than repeated:

| For | Read |
|---|---|
| Wire formats, link-loss staging, H1–H5 test plan | `docs/HIL_MODE.md` |
| The plant model itself (equations, constants, fidelity boundaries) | `docs/HIL_PLANT.md` |
| The curated replay-log ledger | `docs/HIL_REPLAY_LOGS.md` |

Everything below was checked against `teensy_controller/teensy_controller.ino`
(fw v21) at the line anchors given. Where a value is a simulator tuning number
rather than a measured one, it is marked as such — do not launder those into
calibrated facts.

---

## 1. The three operating modes

All three run the SAME firmware build and the SAME wire protocol. What changes is
**who supplies the 22-byte Pi command packet** (`v_setpoint`,
`power_share_setpoint`, `charge_goal`, `mode_cmd`).

| Mode | Command source | How to run | Use it when |
|---|---|---|---|
| **Scripted scenarios** (default) | The scenario's own `pi_timeline` inside `hil_plant_sim.py` | `--scenario NAME` | Regression runs, fault injection, the suite. Reproducible to the tick. |
| **Mode A — emulated EMS** | An EMS *strategy* running on the host, at 50 Hz, closing on feedback | `--scenario NAME --ems STRATEGY` | Developing/regression-testing an energy-management policy **without** the Pi. |
| **Mode B — Pi-live** | A **real Raspberry Pi**, on the network, sending real command packets | `--pi-live` | End-to-end integration: the actual Pi software against the actual firmware, on a simulated plant. |

The plant, the fault paths, the sequencing guards and both controllers are
identical in all three — only the commander differs.

A fourth thing exists and is *not* a mode: `--replay PATH.BLG` streams a recorded
bench log's rails at the board instead of integrating a plant. It is open-loop and
creates no commander at all (`docs/HIL_MODE.md` "Replay mode").

---

## 2. Hardware and network setup

### 2.1 What you need

* A **Teensy 4.1** with the Ethernet kit (the `NativeEthernet` PHY board), flashed
  with the HIL build. **No PCB, no power stage, no motor.** That is the point of
  HIL: every sensor value is injected.
* A **PC** running `tools/hil_plant_sim.py` (Python 3, stdlib only).
* For Mode B, the **Raspberry Pi** running the real bridge software.
* An **unmanaged Ethernet switch**, any 100 Mbit or faster.

> ⚠️ **A switch, not a hub.** A hub is a shared collision domain: every node sees
> every frame and any two simultaneous transmitters collide and back off. This link
> carries a 1 kHz injection stream in one direction and a 1 kHz observation stream
> in the other, plus 50 Hz commands and 50 Hz telemetry — permanently bidirectional,
> which is exactly the traffic pattern a hub handles worst. Total offered load is
> small (~0.5 Mbit/s: 40 B + 16 B at 1 kHz plus 22 B + 58 B at 50 Hz, framing
> included), so bandwidth is never the constraint — **latency jitter is**, and a
> switch removes it. Wi-Fi bridges and powerline adapters are worse than a hub;
> do not use them.

### 2.2 Addresses — these are compiled in

The firmware's addresses are **hard-coded**, not configured at runtime:

| What | Value | Anchor |
|---|---|---|
| Teensy IP | `192.168.1.50` | `.ino:4228` (`IPAddress ip(192,168,1,50)`) |
| Teensy listen port | `5001` (`local_port`) | `.ino:2543`, `Udp.begin(local_port)` `.ino:4230` |
| Telemetry destination | `192.168.1.100:5000` (`pi_ip`, `pi_port`) — **FIXED, not learned** | `.ino:2541-2542`, `sendTelemetry()` `.ino:5065` |
| HIL observation destination | the **learned** simulator host: `hilHostIp:hilHostPort` | `.ino:2651-2654`, sent at `.ino:2779` |

Two consequences the operator must plan around:

1. **The Pi must be at 192.168.1.100** to receive telemetry at all. The firmware
   sends v4 telemetry to that literal address regardless of who commanded it. A Pi
   on any other address can still *command* the board (commands are accepted from
   any source) but will never *see* telemetry. This asymmetry is real and is one of
   the things Mode B is for finding out about.
2. **The simulator's address is learned, and then locked.** The board binds the
   host on the first accepted injection frame and ignores well-formed frames from
   any other source until the link goes dead (250 ms of silence) — `.ino:4947`,
   host-lock comment. So a simulator restarted on a new ephemeral port takes over
   only after that quarter second; that is normal, not a fault.

Suggested static-IP plan (one flat subnet, no router needed):

```
192.168.1.50    Teensy      (compiled in — do not change)
192.168.1.100   Raspberry Pi (compiled in as the telemetry sink)
192.168.1.10    PC / plant simulator (any free address on the subnet)
netmask 255.255.255.0, no gateway required
```

### 2.3 Firmware build flags

```
-DHIL_SIM=1 -DUSE_ETHERNET=1
```

`HIL_SIM=1` without `USE_ETHERNET=1` is a compile error by design (`.ino:2535-2537`):
the injection and observation frames live on the UDP socket.

`BENCH_TEST` chooses how strict the board is with itself:

* **`-DBENCH_TEST=1`** — the bench build. Overcurrent faults are compiled out and
  the bring-up is more forgiving. **Start here.** It tolerates a late simulator.
* **`-DBENCH_TEST=0`** — the production build. The staged bring-up reads *real*
  ADCs until the first injection frame lands, and if the bus has not reached
  `V_BUS_CHARGED_THRESH` within **`BUS_CHARGE_TIMEOUT_MS` = 800 ms**
  (`.ino:1381`) it latches `FAULT_INIT_FAIL` / `ERR_INIT_FAIL` (`.ino:8218-8220`).
  On a bare Teensy the ADCs read ~0 V, so **the simulator must already be
  streaming when the board powers up.** The firmware says so itself in its boot
  banner (`.ino:4139-4147`).

The board prints a loud HIL banner at boot. If you do not see it, you are not
running the HIL build.

---

## 3. Mode A walkthrough — emulated Pi EMS

### 3.1 Run it

```bash
python3 tools/hil_plant_sim.py --teensy-ip 192.168.1.50 \
        --scenario ems-drive-cycle --ems hold-5050 \
        --duration 60 --csv ems_run.csv --dash
```

`--ems` may be omitted for `ems-drive-cycle`: the scenario declares
`hold-5050` as its default strategy. On any other scenario `--ems` is explicit,
and if that scenario carries its own `pi_timeline` the EMS **replaces** it — the
simulator prints a `NOTICE:` line saying so, so a replaced timeline is never
silent.

Refused combinations (argparse-level, with the reason printed):

* `--ems` with `--pi-live` — two command sources would overwrite each other at
  50 Hz and the board would follow whichever wrote last.
* `--ems` with `--replay` — replay bypasses the plant integrator entirely.

### 3.2 What you should see

* Startup: `[hil] EMS strategy: hold-5050 at 50 Hz, v_setpoint profile: 8 points`.
* Dashboard header shows `scenario=ems-drive-cycle EMS:hold-5050`.
* **`v sp`** follows the profile: 0 for the first 3 s, ramp to 1.5 m/s by t = 10 s,
  cruise, a step to 2.0 m/s, ramp down to 0 by t = 52 s.
* **`share sp`** pinned at `0.500` for the whole run.
* **`v act`** tracks `v sp` after the firmware enters Run (the strategy commands
  `MODE_HYBRID` at t = 3 s).
* Exit summary: `pi commands sent: N (EMS hold-5050, N policy evaluations; final
  v_sp=... share_sp=...)`.
* CSV columns `cmd_v_sp` / `cmd_share_sp` carry what was actually commanded.

### 3.3 Adding a strategy

A strategy is one function plus one registry line, in `tools/hil_plant_sim.py`
(see the `MODE A — EMULATED PI EMS` block):

```python
def ems_my_strategy(t, fb):
    """my-strategy — one line saying what it does.

    name       : my-strategy
    intent     : what decision this policy actually makes
    fields     : which of v_setpoint / power_share_setpoint / charge_goal /
                 mode_cmd it drives (UNSET FIELDS HOLD)
    feedback   : which fb keys it reads — and whether they are
                 telemetry-equivalent (see below)
    provenance : where its numbers come from
    """
    return {"power_share_setpoint": 0.5 if fb["V_batt"] > 7.6 else 0.9}

EMS_STRATEGIES = {
    "hold-5050": ems_hold_5050,
    "my-strategy": ems_my_strategy,      # add here; --ems choices come from this dict
}
```

Contract:

* Called at **50 Hz** (`PiCommander.PI_CMD_HZ`), not at the 1 kHz plant tick.
* Returns **any subset** of the four fields. **Unset fields hold** — the same
  contract the firmware itself applies to a field it rejects (comment
  `.ino:4869`, code `.ino:4874-4876`). Returning `{}` is legal.
* Returning an unknown field name raises immediately (typos fail loudly). Only
  the four documented fields (`v_setpoint`, `power_share_setpoint`,
  `charge_goal`, `mode_cmd`) are accepted — `droop_enable` is the reserved
  byte (`.ino:4880-4881`) and is not a legal EMS-policy return, same as any
  other unknown key.

**Portability — read this before using `fb`.** `fb` is deliberately richer than
what a real Pi can see. The Pi receives only the 58-byte v4 telemetry packet
(`.ino:4988-5069`, PLAN.md §6b). Keys that are telemetry-equivalent, i.e. safe in
a strategy you intend to move onto the real Pi:

`v_actual`, `V_batt`, `I_batt`, `I_charge`, `V_fc`, `I_fc`, `V_bus`, `V_rgn`,
`V_chg`, `ag105_status`, `switch`, `fault_flags` (plus `t`, since the Pi has a
clock and the packet carries `timestamp_ms`).

Keys that are **not** — using them makes a strategy simulator-only:

* `soc` — plant truth from the simulator's coulomb count. The real pack has no
  SoC output; the Pi would have to estimate it.
* `state` — live `mainState`, from the HIL observation frame. v4 telemetry carries
  only `error_source_state` (offset 56), which is the state at the time of the
  *first fault*, not the live state.
* `aux` — FC/BT regulator enables, `MPPT_DISABLE`, `CBAL_DISABLE`. Observation
  frame only.
* `current` — post-clamp motor-current command. Observation frame only.
* `v_profile` — the scenario's scripted speed profile; a host-side script, not
  feedback at all.
* `obs_age_s` (F11) — seconds since the last DECODED observation frame, or
  `None` if none has ever arrived. Observation-frame-derived keys (`state`,
  `switch`, `aux`, `current`, `fault_flags`) are **not** bounded by freshness
  themselves — `obs` is not zeroed out on a stall — so a policy that reads any
  of them **must** check `obs_age_s` itself and treat those keys as stale once
  it exceeds roughly `HIL_ZERO_MS / 1000` (0.25 s). `obs_age_s` is HIL-only,
  same as the keys it qualifies.

Note the converse too: v4 telemetry carries `power_share_actual` (offset 43) and
the two droop-gain words (47/49), which `fb` does **not** expose, because the
16-byte observation frame does not carry them. A portable strategy must not
depend on them either.

---

## 4. Mode B walkthrough — a real Pi in the loop

```bash
python3 tools/hil_plant_sim.py --teensy-ip 192.168.1.50 \
        --scenario steady --pi-live --duration 120 --csv pilive.csv --dash
```

Under `--pi-live` this process sends injection frames and receives observation
frames, and **nothing else**. No `PiCommander` is created. Scenarios that carry
their own `pi_timeline` are refused at argparse (pick `steady`, `drive`, `sag`,
or `comm-loss`); `--ems` is refused as well.

The dashboard shows `PI-LIVE` in its header, and `v sp` / `share sp` render as
**`—`**: those setpoints are external and genuinely unknown to this process.
An em-dash here is correct, not a bug.

### 4.1 Three-node bring-up sequencing — the centrepiece

Order matters, and every step below has a reason grounded in the firmware.

**Step 0 — network first.** Bring the switch up, set the three static addresses,
and prove them: `ping 192.168.1.50` will *not* answer (the Teensy runs no ICMP
stack worth relying on), so verify PC↔Pi instead, and confirm both are on
`192.168.1.0/24`. *Why first:* the board learns the simulator's address from the
first frame it accepts, so a wrong subnet is not "slow", it is silent.

**Step 1 — start the plant simulator. BEFORE the board is powered.**

```bash
python3 tools/hil_plant_sim.py --teensy-ip 192.168.1.50 --scenario steady --pi-live --dash
```

*Why:* on a `BENCH_TEST=0` flash the staged bring-up reads real ADCs until the
first injection frame lands and latches `FAULT_INIT_FAIL` if the bus has not
charged within `BUS_CHARGE_TIMEOUT_MS` = 800 ms (`.ino:1381`, `.ino:8218-8220`).
A bare Teensy's ADCs read zero, so a late simulator means a guaranteed
`INIT_FAIL`. *What you see:* once per second,
`[hil] t=... no observation frames yet (tx=N) — is the board flashed with -DHIL_SIM=1?`
That message is EXPECTED at this step; `tx` climbing proves the simulator is
transmitting.

**Step 2 — power the Teensy.** *Why now:* it boots into a stream that is already
running, so its first bring-up tick already has injected rails. *What you see:*
within a second or two the "no observation frames" line is replaced by the live
status line (`state=`, `sw=0x..`, `I_cmd=`, `faults=0x0000`), or the dashboard
starts showing rails and switch dots. `rx` climbing = the board is answering.
On the board's USB serial you should see the HIL banner and the bring-up phases.
**Expected resting state: `state=1` (Idle), `faults=0x0000`.**

**Step 3 — start the Pi last.** *Why last:* the Pi's commands must land on
a board that is already alive and already fault-free. A command arriving during
bring-up is at best ignored; worse, once the Pi has ever been seen
(`pi_ever_connected`, `.ino:4885`) the firmware arms its **Pi watchdog** — in
State 2 or 3, 500 ms (`PI_TIMEOUT_MS`, `.ino:2788`) without a *command packet*
latches `FAULT_PI_TIMEOUT` (`.ino:4817-4826`). Starting the Pi before the plant
means arming a watchdog against a board that cannot yet respond. *What you see:*
the status line's `state` steps 1 → 2 when the Pi commands a Run mode, and
`I_cmd` becomes non-zero as the drive controller tracks the Pi's `v_setpoint`.

### 4.2 Failure signatures if you break the order

F12: `triggerFault()` ORs `FAULT_ERROR` (0x8000) into `fault_flags` alongside
*every* latched fault (`.ino:4501-4503`), so a lone `PI_TIMEOUT`/`HIL_STALE`
latch is observed as `0x8010`, never bare `0x0010` — and `INIT_FAIL` (bit
0x2000) is observed as `0xA000`, never bare `0x2000`. The literals below are
corrected to what you will actually see on the wire.

| Symptom | What happened | Fix |
|---|---|---|
| `faults=0xA000`, error `Init failure`, state 99 immediately after power-on | `INIT_FAIL` (0x2000) `\|` `FAULT_ERROR` (0x8000): board powered before the simulator, bring-up timed out at 800 ms on real (zero) ADCs | Power the board down, start the simulator, power up again. Or use the `BENCH_TEST=1` build while bringing the rig up. |
| Board answers, then latches `0x8010` with error `HIL link dead` | `ERR_HIL_STALE`: >250 ms with no *injection* frame (`HIL_ZERO_MS`, `.ino:2615`) — simulator stopped, Ctrl-C'd, or the cable moved | Restart the simulator. The board stays latched in State 99; power-cycle it for a clean State 1. |
| `faults=0x8010` with error `Pi timeout` while running | Pi stopped commanding for >500 ms in State 2/3 | Restart the Pi bridge. Note the flag is the same bit as above — read `error_code` to tell them apart (`ERR_PI_TIMEOUT` 0x05 vs `ERR_HIL_STALE` 0x10, `.ino:1492`, `.ino:1505`). |
| Simulator's `tx` climbs, `rx` stays 0 forever | Board not flashed HIL, wrong IP/port, or not on the same L2 segment | Check the boot banner, `--teensy-ip`, `--port 5001`. |
| Pi commands work but the Pi sees no telemetry | The Pi is not at `192.168.1.100` — telemetry goes to that literal address (`.ino:2541`, `.ino:5065`) | Move the Pi to `.100`. |

### 4.3 Shutdown order — the reverse

1. **Pi first.** Stop it commanding while the board still has a live plant and can
   act on the last command it was given. Command it to a safe/idle mode before
   stopping, if the bridge supports that.
2. **Simulator second.** Stopping it kills the injection stream, so the board will
   fault `ERR_HIL_STALE` about 250 ms later. That is expected and harmless — the
   board is a bare Teensy — and it is exactly why the suite's 5 s inter-run settle
   exists. Stopping the simulator *first* would instead leave the Pi commanding a
   board whose sensors have been force-zeroed, which is a needlessly confusing
   final trace.
3. **Board last.** Power it down once nothing else is talking to it.

### 4.4 Recovering from a mid-run node loss

* **Simulator died / restarted** — the board is latched in State 99 by then. Restart
  the simulator; the host lock re-learns the new source only after the link went
  dead, which it already has. Then **power-cycle the board**: State 99 is latched
  by design and nothing on the network clears it.
* **Pi died / restarted** — if the board was in State 2/3 it latched `PI_TIMEOUT`.
  Same recovery: restart the Pi, power-cycle the board, then re-run steps 2–3.
* **Cable/switch glitch** — both of the above at once. Re-run the whole sequence from
  step 0; do not try to reattach mid-flight.

There is deliberately **no remote fault reset**. A latched State 99 clears only on
a board reset.

---

## 5. Suite runs

```bash
# scripted, everything (13 scenarios + 26 replays)
python3 tools/run_hil_suite.py --teensy-ip 192.168.1.50

# with the live dashboard on each child (needs a real terminal)
python3 tools/run_hil_suite.py --teensy-ip 192.168.1.50 --dashboard

# Mode B: a real Pi drives every scenario
python3 tools/run_hil_suite.py --teensy-ip 192.168.1.50 --pi-live --scenarios-only
```

Mode tagging: `results.json` / `REPORT.md` carry `mode: "pi-live"` or
`"scripted"` in the report header and on every per-run record (`cmd_mode`).

Under `--pi-live`:

* Every scenario that carries its own `pi_timeline` — and `ems-drive-cycle`, whose
  whole stimulus is the EMS layer — is **SKIPPED with a reason**, not failed. They
  appear in the plan and the report marked `SKIP`, and the result line says how
  many of the "passed" runs were skipped rather than executed.
* `FAULT_PI_TIMEOUT` (0x0010) is **excused** on scenarios that otherwise expect no
  fault: the Pi's command cadence is the operator's, not the harness's.
* The **comm-loss expectation is unchanged**. Verified from source: the HIL stale
  clock keys on accepted *injection* frames only — `hilLastFrameMs` is stamped in
  `receiveCommands()`'s commit block (`.ino:4970-4976`) and aged in
  `updateSensors()` (`.ino:4379-4431`), while a 22-byte Pi command takes the other
  branch (`processPiCommandPacket()`, `.ino:4835`) and touches only `last_rx_ms` /
  `pi_ever_connected` (`.ino:4884-4885`), which belong to the separate Pi watchdog.
  **A real Pi's traffic does not keep the HIL link alive**, so `comm-loss` still
  latches `ERR_HIL_STALE` with the Pi attached.

`--dashboard` hands children the real terminal for stdout, so per-run summary
columns (and the achieved-rate gate) are unavailable and the report says so. It is
refused on a non-tty stdout rather than silently degrading.

---

## 6. Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| `no observation frames yet (tx=N)` forever | Not the HIL build, wrong IP/port, or different L2 segment | Confirm the boot banner; `--teensy-ip 192.168.1.50 --port 5001`; unmanaged switch, no Wi-Fi bridge |
| Board's `'S'` dump shows HIL **accepts stuck at 0** while rejects/foreign climb | A **35-byte legacy injection frame**. The fw v21 frame is **40 bytes** (I_charge at 34, Ag105 status at 38, XOR over 1..38); a 35-byte datagram no longer matches the length dispatch and is dropped unread | Update the simulator (this repo's `pack_inject`); do not patch the firmware |
| Accepts climb but `hilFramesForeign` also climbs | Another process is sending injection frames — an old simulator still running | Kill the stale process; the lock only releases after 250 ms of true silence |
| `faults=0x0010`, error `HIL link dead` | Simulator stopped or the host stalled >250 ms | Restart the simulator, power-cycle the board (State 99 is latched) |
| Frequent brief `hilStale` without a fault | Host scheduling jitter in the 50–250 ms band — held values, motor stood down | Close other load on the PC; check the achieved-rate line (target ≥ 900 Hz) |
| `--dash` refuses to start | stdout is not a tty (piped, redirected, CI) | Run in a terminal, or drop `--dash` |
| `--dashboard` rejected by the suite | Same, at the wrapper level | Run interactively or drop the flag |
| Achieved rate well under 1000 Hz | Host stall, or the hi-fi engine on a slow PC | Try `--electrical simple`; the suite gates at 900 Hz |
| Pi commands ignored | Board not in a state that accepts them, or already latched in 99 | Check `state` on the status line; power-cycle to clear |

---

## 7. What Mode B does NOT validate

Say this out loud in any report that uses Mode B:

* **The Pi's own software is not in this repository.** Nothing here tests the Pi's
  logic, its failure handling, or its restart behaviour. Mode B tests the
  *interface* between whatever the Pi sends and what the firmware does with it.
* **The Pi's telemetry parser has not been audited against v4.** The packet is
  58 bytes with the checksum over bytes 1–56 and `charger_status` at offset 51
  (`.ino:4988-5069`, PLAN.md §6b). Whether the Pi bridge parses that layout —
  rather than a v3 layout with everything after offset 51 shifted by one — is an
  **open item**. A silent one-byte desync produces plausible-looking wrong numbers,
  not an error.
* **Telemetry delivery is address-dependent.** The board sends to a hard-coded
  `192.168.1.100:5000`. A Pi elsewhere on the subnet commands fine and receives
  nothing; that asymmetry is a property of the firmware, not of your setup.
* **The plant is signal-level only.** No power stage, no real currents, no thermal
  behaviour. The charger's I2C config writes, the CV taper and the MPPT loop are
  not simulated (`docs/HIL_MODE.md` Limitations; `docs/HIL_PLANT.md` fidelity
  boundaries). The simulator-only constants there are `TODO(verify)` and stay that
  way.
* **The encoder estimator is bypassed.** `v_actual` is injected, so nothing in a
  HIL run exercises the edge-period estimator, the fractional-pitch ledger, or the
  encoder front end. Those remain bench-only questions.
* **A Mode B pass is not a vehicle-readiness statement.** It says the firmware and
  the Pi agree on the wire, against a simulated plant.
