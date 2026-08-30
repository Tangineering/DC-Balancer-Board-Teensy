# HIL user manual — running the balancer board against a simulated plant

Operator-facing. This is the "how do I actually run it" document; the reference
material lives elsewhere and is cited rather than repeated:

| For | Read |
|---|---|
| Wire formats, link-loss staging, H1–H5 test plan | `docs/HIL_MODE.md` |
| The plant model itself (equations, constants, fidelity boundaries) | `docs/HIL_PLANT.md` |
| The curated replay-log ledger | `docs/HIL_REPLAY_LOGS.md` |

Everything below was checked against `teensy_controller/teensy_controller.ino`
(fw v21) at the line anchors given; the fw v22 amendments (State-0 injection wait
gate, automatic staged bring-up under `HIL_SIM` at both `BENCH_TEST` values, and
auto-recovery from the dead-link latch) are called out inline and shift some anchors
by a few dozen lines. Where a value is a simulator tuning number
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
* A **PC** running `tools/hil_plant_sim.py` (Python 3, stdlib only — see §2.2 for
  the interpreter path).
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

### 2.2 Python environment — use `.venv_hil`

On the bench PC (Windows), the bare `python` command is the Microsoft Store stub
and fails with "Python was not found". Use the project-local HIL virtual
environment instead. It is separate from `.venv_benchlog` (the log-analysis
environment) on purpose: the HIL tools are stdlib-only, so this venv carries no
packages and never breaks when the analysis environment changes.

Interpreter path, relative to the repository root:

```
.venv_hil\Scripts\python.exe
```

Every command in this manual uses that path and fits on **one line**, so it can
be pasted into PowerShell directly. To recreate the environment (it was created
with `uv`, Python 3.14):

```bash
uv venv .venv_hil
```

No `pip install` step follows — there is nothing to install.

### 2.3 Addresses — these are compiled in

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

### 2.4 Firmware build flags

```
-DHIL_SIM=1 -DUSE_ETHERNET=1
```

`HIL_SIM=1` without `USE_ETHERNET=1` is a compile error by design (`.ino:2575-2578`):
the injection and observation frames live on the UDP socket.

**The source defaults to `#define HIL_SIM 0` — an ordinary flash is a normal bench
build.** The Arduino IDE does not pass `-D` flags, so an HIL flash means **editing that
line in `teensy_controller.ino` to `1`** (or building from the command line with
`-DHIL_SIM=1 -DUSE_ETHERNET=1`), and **editing it back to `0` before the next bench
flash**. `USE_ETHERNET` already defaults to `1`; `BENCH_TEST` defaults to `0`.

> ⚠ **A `HIL_SIM=1` build is unusable on a bench without a simulator.** From fw v22
> State 0 waits indefinitely for the injection stream, so the board never brings the bus
> up, never reaches Idle and never reaches the State-98 console. The symptom is the
> once-per-second `State 0: waiting for HIL injection stream...` line and nothing else —
> no fault, no error code. If a bench session looks dead in exactly that way, check the
> flag first.

**From fw v22, `BENCH_TEST` no longer changes State 0 under `HIL_SIM`.** A HIL build
runs the staged bring-up automatically at *both* values, and State 0 first **waits**
for the injection stream before arming it. So:

* **Boot order is free.** Board first or simulator first, either works. State 0 prints
  `State 0: waiting for HIL injection stream...` once per second until the link is up
  and fresh, and starts no bring-up phase clock before then. `detectFaults()` keeps
  running throughout, and the dark wait cannot latch a spurious undervoltage.
* **No manual `T`/`G`/`Q` bring-up is needed on either build** (see §3.0, kept as
  background for non-HIL bench work).

What `BENCH_TEST` still changes is how strict the board is with itself:

* **`-DBENCH_TEST=1`** — the bench build. Overcurrent faults are compiled out and the
  bring-up gates are more forgiving. **Start here.**
* **`-DBENCH_TEST=0`** — the production build. Full fault coverage. Its staged bring-up
  still latches `FAULT_INIT_FAIL` / `ERR_INIT_FAIL` (`.ino:8218-8220`) if the bus has
  not reached `V_BUS_CHARGED_THRESH` within **`BUS_CHARGE_TIMEOUT_MS` = 800 ms**
  (`.ino:1415`) — but under fw v22 that clock only starts *after* the injection link is
  live, so it now times the simulated plant's bus, not a bare Teensy's zero ADCs.

*Historical (fw v21):* a `BENCH_TEST=0` HIL flash read real ADCs until the first frame
landed and latched `INIT_FAIL` at ~800 ms unless the simulator was already streaming at
power-on, and a `BENCH_TEST=1` HIL flash booted dark and could not reach Run without a
manual bring-up. Both are fixed; the boot banner was re-worded to match.

The board prints a loud HIL banner at boot. If you do not see it, you are not
running the HIL build.

### 2.5 Where the output goes — `HIL Results\`

Every HIL artifact defaults into the folder **`HIL Results\`** at the repo root,
so nothing scatters into the working directory:

* `hil_plant_sim.py --csv <name>` — a **relative** path (bare filename or with
  subdirectories) is resolved under `HIL Results\`; the directory is created if
  needed. An **absolute** path is honored verbatim. The electrical events
  sidecar (`<csv>.events.jsonl`) follows the resolved path automatically.
  The simulator prints `[hil] CSV log: <resolved path>` at startup.
* `run_hil_suite.py` — the default report directory is
  `HIL Results\hil_report_<YYYYmmdd_HHMMSS>\`. An explicit `--out` keeps its
  old meaning (a relative path is relative to your current directory). The
  suite hands each child an absolute per-run CSV path, so those land inside the
  report directory rather than being redirected.

Replay **input** paths are **unchanged** — this convention governs outputs only.
A `--replay <path>` argument is interpreted exactly as typed, relative to your
current working directory (so the usual `logs\ML0146.BLG` form still works), and
is never redirected into `HIL Results\`. The curated replay suite is separate
again: `hil_replay_suite.py` resolves its own 26 input logs against the **repo
root**, so it finds them from any working directory.

---

## 3. Mode A walkthrough — emulated Pi EMS

### 3.0 Background — the manual bus bring-up (NOT required on a HIL build)

> **Skip this section for HIL runs.** From fw v22 a `HIL_SIM=1` build brings the bus up
> by itself in State 0 at *both* `BENCH_TEST` values, after waiting for the injection
> stream. The manual sequence below is kept because it is still how you bring the bus
> up on a **non-HIL** `BENCH_TEST=1` bench flash, and because the failure mode it
> describes is what you would see if the automatic bring-up were ever bypassed.

**Non-HIL bench build.** On a non-HIL `BENCH_TEST=1` flash, `doState0()` boots straight to
Idle with the power stage **dark** — boosts, bus switches and `BT_SEQUENCE` all
stay LOW from `setup()`, and there is no bus gate (`.ino:5094-5112`). Nothing
brings the bus up on its own. If an EMS strategy or a scenario then commands
`MODE_HYBRID`, `doState2()` calls `assertMotPwrEnable(true)` on a dark bus, the
guard refuses, and the board latches `FAULT_MOT_HOTPLUG` / `ERR_MOT_HOTPLUG`
(`.ino:5228-5232`) — `fault_flags = 0xC000` (`FAULT_MOT_HOTPLUG` 0x4000
`.ino:1183`, ORed with `FAULT_ERROR` 0x8000), `error_code = 0xF`
(`.ino:1502`), reported *from state 2*.

Run the staged bring-up manually over USB serial before any run:

1. Type **`T`** — Idle → State 98 (test state).
2. Type **`G`** — arms the staged bring-up (`.ino:5643-5652`): P0 pre-charge →
   P1 boosts → P2 dwell → P3 motor-node connect. Wait for
   **`[bringup] DONE: bus + motor node up`** (`.ino:8273`).
3. Type **`Q`** — back to Idle (`.ino:6021-6053`). The **bus stays up**:
   `busBringupAbort()` returns immediately once the bring-up has completed
   (`.ino:8286-8287`), so it does not darken the stage. `MOT_PWR_ENABLE` *is*
   forced LOW on exit (`.ino:6044`), but `doState2()` treats that reconnect at a
   regulated bus as the sanctioned CSS soft-start case, not a hot-plug
   (`.ino:5222-5227`).

A **`BENCH_TEST=0`** flash needs none of this — its `doState0()` runs the same staged
machine automatically. **So does any `HIL_SIM=1` flash from fw v22**, which is why this
section does not apply to the Mode A / Mode B walkthroughs below.

### 3.1 Run it

```powershell
.venv_hil\Scripts\python.exe tools\hil_plant_sim.py --teensy-ip 192.168.1.50 --scenario ems-drive-cycle --ems hold-5050 --duration 60 --csv ems_run.csv --dash
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

```powershell
.venv_hil\Scripts\python.exe tools\hil_plant_sim.py --teensy-ip 192.168.1.50 --scenario steady --pi-live --duration 120 --csv pilive.csv --dash
```

Under `--pi-live` this process sends injection frames and receives observation
frames, and **nothing else**. No `PiCommander` is created. Scenarios that carry
their own `pi_timeline` are refused at argparse (pick `steady`, `drive`, `sag`,
or `comm-loss`); `--ems` is refused as well.

The dashboard shows `PI-LIVE` in its header, and `v sp` / `share sp` render as
**`—`**: those setpoints are external and genuinely unknown to this process.
An em-dash here is correct, not a bug.

> ⚠ **Before the first Mode B run, decide what your Pi does when the board warm-resets.**
> From fw v22 a stopped-and-restarted simulator makes the board recover on its own
> (State 99 → State 0 → bring-up → Idle) without an operator. A Pi that keeps running
> across that boundary will command its *mid-profile* setpoint into a freshly reset
> drive loop the moment it re-sends a run mode. Make the Pi watch `mainState` in the
> observation stream and restart its timeline on a 99 → 0 transition. Full statement of
> the hazard in §4.4.

### 4.1 Three-node bring-up sequencing — the centrepiece

Order matters, and every step below has a reason grounded in the firmware.

**Step 0 — network first.** Bring the switch up, set the three static addresses,
and prove them: `ping 192.168.1.50` will *not* answer (the Teensy runs no ICMP
stack worth relying on), so verify PC↔Pi instead, and confirm both are on
`192.168.1.0/24`. *Why first:* the board learns the simulator's address from the
first frame it accepts, so a wrong subnet is not "slow", it is silent.

> **Windows check — the no-observation-frames trap (hit on first bring-up,
> 2026-08-30).** If the simulator runs but receives zero observation frames,
> check the PC's Ethernet adapter address first:
>
> ```powershell
> Get-NetIPAddress -InterfaceAlias "Ethernet" -AddressFamily IPv4
> ```
>
> A `169.254.*` address (APIPA) means no static IP is set — there is no DHCP
> server on the bench subnet, so Windows autoconfigures. Injection frames then
> never reach the board, it never learns the host, and it never replies. Fix
> (elevated PowerShell; do **not** use `.100`, that address is the Pi's):
>
> ```powershell
> New-NetIPAddress -InterfaceAlias "Ethernet" -IPAddress 192.168.1.10 -PrefixLength 24
> ```
>
> No gateway is needed on a flat bench subnet. `AddressState: Tentative` in the
> output is duplicate-address detection in progress; re-query until it reads
> `Preferred`. Windows Firewall normally passes the observation frames without a
> rule (they are replies to the simulator's own outbound flow); a VPN client is
> the next discriminator only if frames still do not arrive with the IP correct.

**Step 1 — start the plant simulator.** (Recommended before powering the board, but
from fw v22 no longer required — see the note under this step.)

```powershell
.venv_hil\Scripts\python.exe tools\hil_plant_sim.py --teensy-ip 192.168.1.50 --scenario steady --pi-live --dash
```

*Why still first:* it is the simplest order and it gives the board a plant from its
very first tick. **fw v22 removed the hard requirement:** State 0 in a HIL build waits
for the injection stream before arming the staged bring-up, so a late simulator now
just means the board sits printing `State 0: waiting for HIL injection stream...` until
you start it. *(Under fw v21 a `BENCH_TEST=0` flash read real ADCs meanwhile and latched
`FAULT_INIT_FAIL` at `BUS_CHARGE_TIMEOUT_MS` = 800 ms — `.ino:1415`, `.ino:8613-8617` —
so a late simulator was a guaranteed `INIT_FAIL`.)* *What you see:* once per second,
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

**Step 2a — DELETED at fw v22.** The manual `T` → `G` → `Q` bus bring-up is no longer
required on a HIL flash at either `BENCH_TEST` value: State 0 runs the staged machine
itself once the injection link is live, and you should see the bring-up phases end at
`[bringup] DONE: bus + motor node up` (`.ino:8273`) followed by
`State 0 -> State 1 (IDLE) [HIL: staged bring-up on the simulated plant]` on the USB
console. If you are on a **fw v21** flash, do step 2a as §3.0 describes, or the first Pi
`MODE_HYBRID` command latches `FAULT_MOT_HOTPLUG` (`fault_flags = 0xC000`,
`error_code = 0xF`, from state 2; `.ino:5228-5232`).

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
| `faults=0xA000`, error `Init failure`, state 99 immediately after power-on | `INIT_FAIL` (0x2000) `\|` `FAULT_ERROR` (0x8000): board powered before the simulator, the staged bring-up timed out at 800 ms. **On fw v22 this can no longer be caused by a late simulator** (State 0 waits for injection before any bring-up clock starts), so read it as a genuine bring-up failure on the *simulated* plant — the injected `V_bus` never reached `V_BUS_CHARGED_THRESH`. On fw v21 it usually meant the board was powered before the simulator. | Check that the scenario / electrical model actually raises `V_bus`. On fw v21: power the board down, start the simulator, power up again. |
| Board answers, then latches `0x8010` with error `HIL link dead` | `ERR_HIL_STALE`: >250 ms with no *injection* frame (`HIL_ZERO_MS`, `.ino:2615`) — simulator stopped, Ctrl-C'd, or the cable moved | **fw v22: just restart the simulator.** After ~500 ms of fresh frames the board warm-resets itself to State 0, re-runs the bring-up and returns to Idle — no power cycle. It stays latched only if some *other* fault bit latched too (`fault_flags != 0x8010`), which is intended. *(fw v21: power-cycle for a clean State 1.)* |
| `faults=0x8010` with error `Pi timeout` while running | Pi stopped commanding for >500 ms in State 2/3 | Restart the Pi bridge, then power-cycle the board. Note the flag is the same bit as above — read `error_code` to tell them apart (`ERR_PI_TIMEOUT` 0x05 vs `ERR_HIL_STALE` 0x10, `.ino:1492`, `.ino:1505`). **The fw v22 auto-recovery does NOT apply here:** it requires `error_code == ERR_HIL_STALE`, so a genuine Pi timeout stays latched. |
| Simulator's `tx` climbs, `rx` stays 0 forever | Board not flashed HIL, wrong IP/port, or not on the same L2 segment | Check the boot banner, `--teensy-ip`, `--port 5001`. |
| Pi commands work but the Pi sees no telemetry | The Pi is not at `192.168.1.100` — telemetry goes to that literal address (`.ino:2541`, `.ino:5065`) | Move the Pi to `.100`. |

### 4.3 Shutdown order — the reverse

1. **Pi first.** Stop it commanding while the board still has a live plant and can
   act on the last command it was given. Command it to a safe/idle mode before
   stopping, if the bridge supports that.
2. **Simulator second.** Stopping it kills the injection stream, so the board will
   fault `ERR_HIL_STALE` about 250 ms later. That is expected and harmless — the
   board is a bare Teensy — and it is exactly why the suite's 5 s inter-run settle
   exists. On fw v22 the board would warm-reset itself back to State 0 if you started
   the simulator again; leaving it stopped keeps the board latched, which is the
   correct end-of-session state. Stopping the simulator *first* would instead leave the Pi commanding a
   board whose sensors have been force-zeroed, which is a needlessly confusing
   final trace.
3. **Board last.** Power it down once nothing else is talking to it.

### 4.4 Recovering from a mid-run node loss

* **Simulator died / restarted** — the board is latched in State 99 by then. Restart
  the simulator; the host lock re-learns the new source only after the link went
  dead, which it already has. **On fw v22 that is the whole recovery:** after ~500 ms
  of continuously fresh frames the board warm-resets to State 0, runs the staged
  bring-up and returns to Idle. Watch for `[HIL] link recovered — warm reset,
  re-entering State 0` on the USB console and `faults` clearing to `0x0000` on the
  status line. Note the warm reset puts `mode_cmd` back to SAFE, so the EMS/Pi must
  re-send its mode command to get back into Run. *(fw v21: power-cycle the board.)*

  > ⚠ **A PERSISTENT COMMANDER MUST RESTART ITS TIMELINE ON A WARM RESET.** SAFE is the
  > only thing standing between the recovered board and the commander's *current*
  > setpoint: the board re-enters Run as soon as any streaming commander sends a run
  > mode, and it does so with a freshly reset drive controller and `v_setpoint = 0`. A
  > Pi or custom runner that keeps running through the reset will re-send whatever its
  > profile says at *its* wall-clock time — e.g. a mid-profile 2.5 m/s — into that fresh
  > loop as a step from standstill. On a mixed rig with a live VESC the drive controller
  > rails within tens of milliseconds. **Watch `mainState` in the observation frame: a
  > 99 → 0 transition is the run boundary, and your commander must restart its timeline
  > at t = 0 there** (or stop commanding and let the operator restart it). Mode A's
  > per-process simulators are immune by construction — each run is a new process that
  > starts at t = 0 — so this is a Mode B and custom-runner hazard.
* **Simulator died *during* the bring-up** — a special case, and it is benign. The
  bring-up's phase gates are timed against `millis()` while the sensor values are held,
  so a phase timeout there would latch `FAULT_INIT_FAIL` / `FAULT_MOT_HOTPLUG`, which are
  **not** in the recoverable set. The firmware instead aborts the bring-up safely the
  moment the link goes stale and prints `[bringup] HIL injection link lost mid-bring-up —
  aborting (not a fault); State 0 re-arms when frames return.` The stage goes dark, no
  fault latches, and the bring-up simply restarts when the simulator comes back. Under
  the State-98 `'G'` command the board stays in State 98 with the same notice.
* **Pi died / restarted** — if the board was in State 2/3 it latched `PI_TIMEOUT`.
  **Not** auto-recoverable (the fw v22 path requires `error_code == ERR_HIL_STALE`):
  restart the Pi, power-cycle the board, then re-run steps 2–3.
* **Cable/switch glitch** — both of the above at once. Whether the board self-recovers
  depends on which fault latched *first*: `error_code` names it, and only
  `ERR_HIL_STALE` with `fault_flags` exactly `0x8010` recovers. Re-run the whole
  sequence from step 0; do not try to reattach mid-flight.

There is still deliberately **no remote fault reset**, and no operator command clears
a latch. The fw v22 auto-recovery is narrower than one: admitted only for the dead-link
fault union `0x8010` with `error_code == ERR_HIL_STALE`, only after the State-99
teardown has completed, only with the bench log closed, and only under `HIL_SIM`.
**Every other latched fault still clears only on a board reset**, and a dead-link latch
that arrived alongside any other fault bit stays latched too.

---

## 5. Suite runs

```powershell
# scripted, everything (13 scenarios + 26 replays)
.venv_hil\Scripts\python.exe tools\run_hil_suite.py --teensy-ip 192.168.1.50

# with the live dashboard on each child (needs a real terminal)
.venv_hil\Scripts\python.exe tools\run_hil_suite.py --teensy-ip 192.168.1.50 --dashboard

# Mode B: a real Pi drives every scenario
.venv_hil\Scripts\python.exe tools\run_hil_suite.py --teensy-ip 192.168.1.50 --pi-live --scenarios-only
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

**Between runs (fw v22).** The 5 s inter-run settle is far longer than the 250 ms zero
stage, so the board latches `ERR_HIL_STALE` after each run — and then warm-resets to
State 0 when the next run starts streaming, bringing the simulated stage up again. Each
run therefore begins from a fresh-boot equivalent rather than from a latched board, and
the whole plan runs unattended. A run that latches a *real* fault still leaves the board
latched, and the next run's health checks report it.

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
| `faults=0x0010`, error `HIL link dead` | Simulator stopped or the host stalled >250 ms | Restart the simulator — on fw v22 the board warm-resets to State 0 by itself ~500 ms later. Power-cycle only if `fault_flags` is not exactly `0x8010` (another fault latched too). |
| Frequent brief `hilStale` without a fault | Host scheduling jitter in the 50–250 ms band — held values, motor stood down | Close other load on the PC; check the achieved-rate line (target ≥ 900 Hz) |
| `--dash` refuses to start | stdout is not a tty (piped, redirected, CI) | Run in a terminal, or drop `--dash` |
| `--dashboard` rejected by the suite | Same, at the wrapper level | Run interactively or drop the flag |
| Achieved rate well under 1000 Hz | Host stall, or the hi-fi engine on a slow PC | Try `--electrical simple`; the suite gates at 900 Hz |
| Pi commands ignored | Board not in a state that accepts them, or already latched in 99 | Check `state` on the status line. `mode_cmd` is acted on only in State 1 (Idle), and a fw v22 warm reset resets it to SAFE — so after a recovery the EMS/Pi must re-send its mode command. Power-cycle to clear any non-dead-link latch. |

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
