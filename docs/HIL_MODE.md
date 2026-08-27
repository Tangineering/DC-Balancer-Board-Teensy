# HIL mode — real Teensy against a simulated plant (fw v21)

> For the plant-side deep dive — the mechanical/electrical model, constant provenance,
> the simplifications and their consequences, the CSV schema and the extension roadmap —
> see [`docs/HIL_PLANT.md`](HIL_PLANT.md). This document covers the link: frames, staging,
> build flags and the H1–H5 test plan.

## Purpose

HIL mode makes the **real Teensy the device under test** and replaces the *plant*
— the boosts, the pack, the bus capacitance, the motor and the car's mechanics —
with a simulation running on a host PC. The firmware does not know the difference:
`detectFaults()`, the §2 sequencing rules and their guards, the Youla drive
controller, the power-share loop, the charger logic and the state machine all run
**completely unmodified** on the injected values.

That is what makes it useful. Several classes of behaviour are hard or destructive
to provoke on the bench:

- a bus undervoltage deep enough to latch `ERR_UV_BUS`;
- a source dropping out mid-slew (the TP0201 handoff class);
- a communications failure while the board is sequencing;
- a full drive cycle without spinning a real flywheel.

In HIL those become a command-line argument. There is deliberately **no
HIL-specific fault suppression anywhere in the firmware** — a fault-injection rig
whose faults are suppressed tests nothing.

## Architecture

```
   HOST (tools/hil_plant_sim.py)                      TEENSY 4.1 (-DHIL_SIM=1)
  ┌──────────────────────────────┐                  ┌───────────────────────────────┐
  │  Plant model @ 1 kHz         │                  │  updateSensors()              │
  │   mechanical: m_eff, K_F,    │   40 B inject    │    HIL branch: assign the 7   │
  │     F_c, b_eff               │ ───────────────► │    rails + v_actual from the  │
  │   electrical: droop bus,     │   UDP :5001      │    frame (engineering units,  │
  │     source split, charger/   │   sync 0xB5      │    no SCALE_*; updateWheel-   │
  │     regen rails, Ag105       │                  │    Speed() SKIPPED)           │
  │     status + I_charge        │                  │  pollAg105(): HIL branch —    │
  │                              │                  │    no I2C, values injected    │
  │                              │                  │            │                  │
  │                              │                  │            ▼                  │
  │                              │                  │  computeDerivedSignals()      │
  │                              │                  │  detectFaults()   ← UNMODIFIED│
  │                              │                  │  state machine / controllers  │
  │                              │                  │  sequencing guards, MDAC, VESC│
  │  Reconstruct actuator state  │   16 B observe   │            │                  │
  │  ◄─────────────────────────── │ ◄──────────────  │            ▼                  │
  │   state, switches, aux pins, │   sync 0xB6      │  hilSendTick() @ 1 kHz        │
  │   I_cmd, MDAC codes, faults  │   1 kHz          │                               │
  └──────────────────────────────┘                  └───────────────────────────────┘
            │                                                     │
            └── CSV log (per tick)                                └── USB serial: banner,
                                                                      State-98 'S' dump,
                                                                      normal SD .BLG logging
```

Both frames ride the **existing** UDP socket (`local_port` 5001) — the one the Pi
bridge uses. `receiveCommands()` dispatches on packet **length**: 22 bytes is the
Pi command packet (byte-identical to fw ≤ v20), 40 bytes is a HIL injection frame,
everything else is dropped. The sync bytes are distinct as well (`0xAA`/`0xBB` for
the Pi link, `0xB5`/`0xB6` for HIL), so the two protocols cannot be confused even
before the length check.

## Frame formats

### Injection frame — host → Teensy, 40 bytes, little-endian

| Offset | Size | Field | Units / notes |
|--------|------|-------|---------------|
| 0 | 1 | sync `0xB5` | |
| 1 | 1 | `seq` | uint8, wraps; echoed in the observation frame |
| 2 | 4 | `V_fc` | V — **post-scaling engineering units**, no ADC counts |
| 6 | 4 | `V_batt` | V |
| 10 | 4 | `V_bus` | V |
| 14 | 4 | `V_chg` | V |
| 18 | 4 | `V_rgn` | V |
| 22 | 4 | `I_fc` | A |
| 26 | 4 | `I_batt` | A |
| 30 | 4 | `v_actual` | m/s (flywheel surface speed, same terms as `v_setpoint`) |
| 34 | 4 | `I_charge` | A — simulated Ag105 measured charge current (reg `0x06` equivalent, **already scaled** by 0.011 A/count) |
| 38 | 1 | `ag105_status` | raw Table 6 status byte, exactly as an I2C read returns it (`references/Datasheets/Ag105_Table6_I2C_Status_Byte.json`) |
| 39 | 1 | XOR checksum | over bytes 1–38 |

The frame grew from 35 to 40 bytes when the charger fields were added. The 35-byte
layout was **never flashed** (fw v21 is still pending its first flash), so there is
deliberately no back-compat path: a 35-byte datagram no longer matches the length
dispatch and is dropped unread, which shows up as the `'S'` dump's accept count
stuck at zero — a loud failure rather than a half-decoded frame.

Rejected if the length, the sync byte or the checksum is wrong, or if any float
decodes as NaN/Inf (`I_charge` included; an XOR checksum passes plenty of bit patterns that do, and a
NaN reaching `v_actual` poisons the drive controller's recursion permanently).
Rejections are counted and shown in the `'S'` dump.

### Observation frame — Teensy → host, 16 bytes, little-endian

| Offset | Size | Field | Notes |
|--------|------|-------|-------|
| 0 | 1 | sync `0xB6` | |
| 1 | 1 | `seq` echo | last **accepted** injection seq — round-trip latency measure |
| 2 | 1 | `mainState` | 0/1/2/3/98/99 |
| 3 | 1 | `switch_state` | `SW_FC_BUS` 0x01, `SW_BT_BUS` 0x02, `SW_MOT_PWR` 0x04, `SW_REGEN` 0x08, `SW_FC_CHARGE` 0x10, `SW_BT_SEQ` 0x20 — same packing as telemetry offset 52 |
| 4 | 1 | aux pins | bit0 `FC_REG_ENABLE`, bit1 `BT_REG_ENABLE`, bit2 `MPPT_DISABLE`, bit3 `CBAL_DISABLE` |
| 5 | 4 | `current` | float32 A, **post-clamp** motor-current command |
| 9 | 2 | MDAC code FC | raw 16-bit AD5443 word (`0x1000` control nibble + 12-bit code) |
| 11 | 2 | MDAC code BT | ditto |
| 13 | 2 | `fault_flags` | uint16 |
| 15 | 1 | XOR checksum | over bytes 1–14 |

Sent at 1 kHz from `loop()`, but only **after the first accepted injection frame**
(before that there is no host address to send to) and only when `networkUp`.

## Link-loss behaviour: hold, then zero

Two thresholds, and the staging is deliberate:

| Age of last accepted frame | Behaviour |
|---|---|
| ≤ `HIL_STALE_MS` (50 ms) | apply the injected values normally |
| ≤ `HIL_ZERO_MS` (250 ms) | **HOLD** the last values, set `hilStale` |
| > `HIL_ZERO_MS` | force **safe zeros** on all seven rails and `v_actual`, **latch `ERR_HIL_STALE`** |

A dropped or late packet is a *host scheduling* artefact, not a plant event.
Zeroing immediately would inject a full-scale rail collapse into `detectFaults()`
and latch a bogus undervoltage fault on nothing but a missed 1 ms tick. But a
genuinely dead link must not read as a healthy plant frozen at its last good
values either — that would let the firmware keep sequencing switches against
fiction indefinitely — so after 250 ms the injected sensors read as a
disconnected board would, and the ordinary fault logic takes it from there.

Two things happen on the *edges* of that staging (added in the fw v21 review round):

- **Entering the stale hold calls `haltMotorOutput()`.** A frozen `v_actual` is
  still live feedback to a drive controller with an LF gain of ~454 A/(m/s): a
  constant error integrates straight to the ±12 A rail, and in a mixed rig that
  current is commanded into a *real* VESC. The sensor values are still held (that
  is what keeps a missed tick from latching a bogus UV fault), but the actuator is
  stood down: setpoint zeroed, Youla state reset, 0 A sent. A State-98 manual motor
  run is therefore stopped by a link hiccup — the intended conservative outcome.
- **Reaching the zero stage latches a fault**: `ERR_HIL_STALE` (`0x10`, appended to
  the `ErrorCode_t` enum) through the normal `triggerFault()` funnel, so State 99
  entry, error latching and the BLG close behave exactly as for any other fault.
  A 50–250 ms gap is recoverable and must not fault; a dead link is not recoverable
  and must be deterministic — previously the zeros only faulted if the UV_BUS check
  happened to be armed, so a dead link during Init/Idle idled forever on fiction.
  The fault *bit* is a deliberate alias of `FAULT_PI_TIMEOUT`: all 16 bits of the
  fixed-width `fault_flags` word are allocated, and `error_code` is what names the
  cause. See the comment at the `#define FAULT_HIL_LINK` site.

**Host binding (fw v21).** The host address/port is learned from the **first**
accepted frame and re-learned only after the link has gone dead. While the link is
up, a well-formed frame from any other source address is ignored entirely — not
applied, and not allowed to restamp the freshness timestamp — and counted in
`hilFramesForeign` (shown in the `'S'` dump). Consequence, accepted: a simulator
restarted on a **new port** cannot take over until the link has been silent for
`HIL_ZERO_MS` (250 ms), which is the window the operator sees on a restart anyway.

**Receive drain (fw v21).** `receiveCommands()` drains up to
`UDP_DRAIN_MAX_PER_TICK` (8) datagrams per loop tick instead of one. Every 22-byte
Pi command in the drain is dispatched in arrival order; injection frames are all
parsed (so the counters stay truthful) but only the **last accepted** one is
committed, since a frame is a plant snapshot rather than an event. The `'S'` dump
prints `udp drain (last/max/cap-hits)` — a max sitting at the cap with cap-hits
rising means the loop is not keeping up with the injection rate.

Before the *first* frame ever arrives the real ADCs are read as usual, so a HIL
flash is still readable on a desk with the simulator not yet started.

> ⚠️ **Production (`BENCH_TEST=0`) HIL boot is order-sensitive: start
> `tools/hil_plant_sim.py` BEFORE powering the board.** Until the first frame
> lands the firmware reads real (disconnected) ADCs, and the staged bring-up
> latches `FAULT_INIT_FAIL` at ~800 ms on those readings. Injection that starts
> mid-bring-up also satisfies the bring-up gates on a step rather than a ramp.
> The boot banner repeats this.

## Building and flashing

```
# Arduino IDE / arduino-cli: add the flags to the build
-DHIL_SIM=1 -DUSE_ETHERNET=1
```

`HIL_SIM=1` with `USE_ETHERNET=0` is a **compile error** — HIL rides the UDP
socket, so a build without the Ethernet stack would silently never receive a
frame.

> ⚠️ **Never attach a live power stage to a HIL_SIM=1 flash.** Every sensor value
> the firmware sees is fiction supplied by a host, so every switch decision it
> makes is made against a simulated plant. The board prints a loud boot banner to
> this effect. Reflash a normal build before any bench run.

## Running the simulator

```
python3 tools/hil_plant_sim.py \
        --teensy-ip 192.168.1.50 \
        --port 5001 \
        --scenario steady \
        --duration 30 \
        --csv hil_run.csv
```

Stdlib only — no numpy. (To drive the board from a recorded bench log instead of
the modelled plant, see **Replay mode** below.) Scenarios:

| Scenario | What it does |
|---|---|
| `steady` | fixed aux load; the quiescent baseline |
| `step-load` | +1.2 A aux load step at t = 5 s — a bus disturbance the share loop must reject |
| `sag` | −5 V bus disturbance for 1 s at t = 5 s, crossing `LIMIT_V_BUS_MIN` (12.0 V) |
| `comm-loss` | stops transmitting for 1 s at t = 5 s, then resumes |
| `drive` | plant only; the operator drives the firmware by hand (`'V'`, `'D'`, `'Y'`) over USB |
| `charge-cruise` | Run + cruise + `charge_goal` > 0 via the Pi command timeline — `FC_CHARGE` opens on intent, the Ag105 settles to Charging, MPPT released |
| `charge-regen` | cruise/brake cycling with `charge_goal` > 0 — `MPPT_DISABLE` asserted during regen, `REGEN` ⇄ `FC_CHARGE` mutual exclusion visible |
| `charge-fault` | charging established, then the charger input rail collapses at t = 20 s — the GENSTAT decode / charger-loss path |
| `soc-depletion` | sustained battery-heavy load; `V_batt` walks down the OCV curve toward `LIMIT_V_BATT_MIN` (use `--soc0` / `--capacity-ah` to fit a bench session) |
| `handoff-sag` **(hi-fi only)** | share driven to a rail so one source goes dark, then perturbed — the TP0178/TP0201 reactive-pickup gap |
| `bringup` **(hi-fi only)** | from dark: the firmware's staged bring-up P0–P3 against the real RT1987 t_D(ON) + soft-start delays |
| `scp-inrush` **(hi-fi only)** | RT1987 soft-start foldback margin on `MOT_PWR` into the top of the VESC input envelope (0.9 mF) under load |

`python3 tools/hil_plant_sim.py --list-scenarios` prints this table with the engine each
scenario needs and its default duration. Scenarios marked **hi-fi only** require
`--electrical hifi` and are refused under the default `simple` engine rather than
producing a meaningless trace.

| Flag | Meaning |
|---|---|
| `--electrical {simple,hifi}` | electrical engine (default `simple` — one droop node). `hifi` selects `tools/hil_electrical.py`: TPS61288 average model, RT1987 ideal-diode state machines, a six-node ODE at an adaptive substep rate. See `docs/HIL_PLANT.md` §8. |
| `--trace-config {long,short}` | hi-fi parasitic-inductance set: `long` = as-manufactured FastHenry extraction, `short` = post-bodge (default) |
| `--vesc-cap-uf X` | hi-fi VESC input capacitance (envelope 200–900 µF, default 500) |
| `--soc0 X` | initial battery state of charge, 0–1 (default 0.7) |
| `--capacity-ah X` | battery capacity (default 5.0 Ah) |
| `--noise` | hi-fi: apply ADC quantization (and any configured sigmas) to the injected values |
| `--list-scenarios` | print the scenario registry and exit |

Several scenarios also drive the board through the firmware's **22-byte Pi command
packet** (mode, `v_setpoint`, `power_share_setpoint`, `charge_goal`) on the same socket —
that is the only way `charge_goal` reaches the firmware, and it is what makes the charging
path testable at all. See `docs/HIL_PLANT.md` §10.

The simulator prints a 1 Hz status line and, at exit, the achieved tick rate and
worst overrun. The CSV carries every tick: injected sensor values plus the decoded
observation frame.

Plant constants are the repo's calibrated ones (fw v14 force-axis correction —
`controller_design_MIMO/calibration/motor_id_20260815.md`): `m_eff` 3.5 kg,
`K_F` 0.7538 N/A, `F_c` 2.00 N, `b_eff` 0.534 N·s/m, `V_BUS_NOMINAL` 16.0 V,
2S pack 7.4–8.4 V, ~13 V-class fuel cell.

## Replay mode — a recorded bench log as the stimulus

`--replay PATH.BLG` swaps the simulated plant for a **recorded bench run**: the
`.BLG`'s per-sample rail voltages, source currents and velocity are streamed back
at the board as ordinary injection frames, at true wall-clock pacing. A recorded
incident (a UV sag, a boost-death precursor, an encoder-corruption burst) becomes a
repeatable stimulus you can re-run against any firmware build.

```
python3 tools/hil_plant_sim.py --teensy-ip 192.168.1.50 \
        --replay logs/TP0178.BLG --csv hil_replay_TP0178.csv
```

| Flag | Meaning |
|---|---|
| `--replay PATH.BLG` | replay this log; **mutually exclusive with `--scenario`** |
| `--replay-speed X` | pacing multiplier (default `1.0` = true wall clock) |
| `--loop` | repeat the log until `--duration` elapses (replay only) |
| `--duration` | defaults to the log's own length ÷ `--replay-speed` |

The log is decoded through `tools/decode_benchlog.py`'s `decode_blg()` (lazy
import; a clear message and a non-zero exit if it can't be imported, read or
parsed), so every BLG format version that decoder supports (v1–v7) replays.

### ⚠️ Fidelity caveat — replay is an OPEN-LOOP stimulus

**The plant integrator is bypassed. The firmware's commands do NOT influence the
replayed trajectory.** In live simulation the loop is closed — a bigger `I_cmd`
accelerates the modelled flywheel and comes back as a larger `v_actual`. In replay
the trajectory is fixed history: command +12 A and `v_actual` keeps doing exactly
what the bench did. Replay therefore validates **responses** — state transitions,
switch sequencing, fault latching, command shape at a given operating point — and
must never be read as a closed-loop trajectory match. Two further consequences:

- The board's own `'V'`/`'D'`/`'Y'` commands cannot "drive" a replay.
- Divergence between the replayed `I_cmd` (in the log) and the live `current` (in
  the observation frame) is **expected**, not a defect — see the version warning
  below.

Because the record schema carries neither field, `I_charge` is replayed as **0.0 A**
and `ag105_status` as **0x00** (GENSTAT *Battery Disconnect* — what the firmware's
own failed-read path leaves behind). Charger-path behaviour is therefore *not*
exercised by replay; use a live scenario for that.

### Field mapping

Left column = the decoder's own CSV column names; right = injection-frame fields.

| BLG record field | Injection frame field | Notes |
|---|---|---|
| `V_fc` | `V_fc` | BLG format v3+ only; 0.0 for v1/v2 logs (warned at start) |
| `V_batt` | `V_batt` | v3+ |
| `V_bus` | `V_bus` | all versions |
| `V_chg` | `V_chg` | v3+ |
| `V_rgn` | `V_rgn` | v3+ |
| `I_fc` | `I_fc` | all versions |
| `I_batt` | `I_batt` | all versions |
| `v_act` | `v_actual` | blank cell (record's velocity-valid flag clear) → 0.0 m/s |
| — | `I_charge` | not in any BLG record version → **0.0** |
| — | `ag105_status` | not in any BLG record version → **0x00** |

Timing uses the record `t_us` axis (wrap-safe modular differencing, matching the
decoder), replayed through the **same drift-corrected scheduler** as live
simulation, with a zero-order hold between samples. `--rate` still sets the
transmit tick rate (1 kHz default, which matches the 1 kHz BLG sample rate).

The observation-frame receive path, the CSV log and the 1 Hz status line all run
exactly as in live simulation. The replay CSV keeps the live schema unchanged and
**appends one column, `replay_rec`** — the source record index each row was drawn
from, so a replay CSV lines up against the decoded `.BLG` row-for-row while
remaining readable by anything that parses the simulated schema.

### Firmware-version warning

At start-up replay prints the log's header `fw_version` and warns that control-law
responses will differ across versions. This is not boilerplate: a v14 `'V'` trace is
a *different control law* from a v13 one (regenerated coefficients, new `K_I`, ×1.34
DC plant gain), fw v18 changed both the coefficients and the saturated-mode
behaviour, and pre-v18 `v_act` was computed on a physically different encoder wheel.
Replaying an old log against a new flash is a legitimate and useful test — just do
not expect the commands to match the log's.

### Worked example — re-running the TP0178 bus sag

`TP0178` (2026-08-17b) recorded `V_bus` sagging to **12.15 V** — 0.15 V above
`LIMIT_V_BUS_MIN` and only ~10 ms long, under the 20 ms dwell — so the firmware
correctly did *not* fault. Replaying it verifies that judgement stays correct in the
current build:

```
python3 tools/hil_plant_sim.py --teensy-ip 192.168.1.50 \
        --replay logs/TP0178.BLG --csv hil_TP0178.csv
```

Expected: the injected `V_bus` column in `hil_TP0178.csv` reproduces the 12.15 V
trough (it is the recorded one), the observation frame's `mainState` never reaches
99, and `fault_flags` stays 0 throughout — the sag is under the dwell. Then push it
over the line: the same run under `--scenario sag` (a −5 V, 1 s disturbance) *must*
latch State 99 with the UV bit, which is test **H2**. Replay checks the near-miss;
the scenario checks the trip. Both should hold on any build.

## Live dashboard (`--dash`)

`tools/hil_dashboard.py` gives the simulator a one-screen live view instead of the
1 Hz status lines:

```bash
python3 tools/hil_plant_sim.py --teensy-ip 192.168.1.50 --scenario steady --dash
```

It shows, all on one non-scrolling screen: elapsed time, source (scenario or
replay), electrical mode, achieved tick rate and the tx/rx/bad/pi frame counters;
**v setpoint vs actual** and **power-share setpoint vs actual** (share = I_fc/I_tot,
shown as `—` below ~50 mA total where the ratio is meaningless); **V_bus, I_tot,
I_fc, I_bt** with unicode sparklines and each channel's observed range; the six
RT1987 switch states (`FC_BUS BT_BUS MOT_PWR REGEN FC_CHG BT_SEQ`) and the four aux
pins (`FC_REG BT_REG MPPT_DIS CBAL_DIS`) as ●/○ from the observation frame's
bitmasks; the firmware `mainState` (number + name), commanded current, charge
current, the raw Ag105 status byte, `fault_flags` **decoded to names**; and, in
hi-fi mode, the achieved substep rate, electrical event count and chopper peak
power.

**Lightness contract.** The 1 kHz loop's entire obligation is one attribute
assignment (`dash.snapshot = {...}`) — atomic under the GIL, no locks, no queues,
no I/O on the hot path. A **daemon thread** wakes at 5 Hz, takes whatever snapshot
happens to be current, appends to its own history rings and redraws with plain
ANSI escapes (not curses, so Windows Terminal / MSYS2 work; VT processing is
enabled via the stdlib `os.system("")` trick). The view is therefore *sampled*:
it is several — often many — ticks behind and drops everything in between, by
design. The CSV and the BLG remain the record of truth. Measured cost on a 5 s
`steady` run through a pty: **1000.0 Hz without `--dash` vs 999.9 Hz with it.**
A renderer exception can never propagate into the simulation — the thread catches
everything, restores the cursor, prints one warning and dies; the run continues.

If stdout is **not a tty** (piped, redirected, captured), the dashboard refuses to
start, says so in one line, and the normal 1 Hz status lines are kept.

### Suite integration (`--dashboard`, default OFF)

`tools/run_hil_suite.py --dashboard` appends `--dash` to every child. It is **off
by default** so suite behaviour without it stays byte-identical, and because of one
trade-off: the wrapper normally captures each child's stdout into a per-run `.log`
and parses the run summary out of it, but a dashboard writing ANSI into a captured
pipe is useless (and the child's own tty check would just disable it). So with
`--dashboard` the children are given the **real terminal** for stdout (stderr is
still captured), the run record is marked `stdout_passthrough`, and the
stdout-derived summary columns in `REPORT.md` are empty for that run. Use it to
watch a run; leave it off when you want a complete report.

## Running the full suite

The individual commands above are for a single scenario or a single recorded log.
`tools/run_hil_suite.py` is the one-shot wrapper: it runs **every** scenario in
`SCENARIOS` and **every** entry in the replay suite against a flashed board, then
packages the whole thing into a timestamped report directory.

```bash
python3 tools/run_hil_suite.py --teensy-ip 192.168.1.50
```

**Prerequisites**

- The board is flashed `-DHIL_SIM=1 -DUSE_ETHERNET=1` (fw v21 or later — the runner
  states that expectation in the report header; it does not enforce it).
- Board and simulator host share an L2 segment, and the board answers on
  `--teensy-ip` / `--port` (default `5001`, the `.ino` `local_port`).
- Nothing on the power stage. This is signal-level HIL; the scenarios drive the
  firmware's fault and sequencing paths deliberately.
- Under a production (`BENCH_TEST=0`) build the simulator must already be streaming
  before the board powers on, or the board hits `INIT_FAIL` in ~800 ms.

**Options**

| Flag | Meaning |
|------|---------|
| `--out DIR` | report directory (default `hil_report_<YYYYmmdd_HHMMSS>/`) |
| `--list` | print the run plan and estimated wall time; needs no board |
| `--dry-run` | build every child argv, write `plan.json`, run nothing |
| `--only PAT` / `--skip PAT` | shell globs on the run name; repeatable |
| `--replay-only` / `--scenarios-only` | run one half of the plan |
| `--electrical-pref {hifi,simple}` | engine for scenarios whose requirement is `any` (default `hifi`); scenarios that *require* one engine always run in it |
| `--settle-s X` | pause between runs (default 5 s) |
| `--keep-going` | do not abort when the first run sees no observation frames |

**Board state between runs.** Each run opens its own socket, and the firmware learns
its host from the first accepted injection frame. The default 5 s settle pause is far
longer than the 250 ms zero stage, so between runs the board force-zeros the injected
rails, unbinds the host and latches `ERR_HIL_STALE` — i.e. each run starts from a
known *latched* board, not from whatever the previous scenario left behind. That
latch is expected; the runner judges each run's fault outcome against that run's own
stimulus. For a clean State-1 board on a particular run, power-cycle and pass
`--settle-s 0`.

**Execution model.** Every run is a separate `hil_plant_sim.py` child process (not an
in-process call) with a hard timeout of the run's duration + 30 s, so a wedged run is
killed and recorded as `TIMEOUT` instead of hanging the session. Each child's
stdout/stderr lands in a per-run `.log`.

**What the report contains** (`REPORT.md` + machine-readable `results.json`):

- a header — date, board IP, firmware expectation, host, achieved tick rates;
- a summary table of every run (kind, electrical mode, duration, pass/fail, key metrics);
- a **scenarios** section. Scenario entries carry no declarative checks, so the runner
  applies its own health criteria: at least one observation frame arrived (zero frames
  = FAIL, the board is absent), the fault outcome matches an expectation table (`sag`
  must latch UV_BUS per H2; `comm-loss` must latch `ERR_HIL_STALE`, since its 1 s gap
  is past the 250 ms zero stage; `soc-depletion` and `charge-fault` are *allowed* to
  fault; everything else must stay clean), the achieved rate held above 900 Hz, and no
  `sw_ring` event exceeded the 20 V abs-max;
- a **replay** section, grouped conformance vs deviation, with each declarative check's
  detail and the entry's fw-delta / open-loop notes;
- a **known open findings** section that always carries the `K_DROOP_BUS`
  design-vs-measured ×4 discrepancy, plus any over-abs-max `sw_ring` events seen;
- an appendix listing every artifact file.

Exit code: `0` all passed, `1` at least one failure, `2` the board never answered on
the first run (the runner aborts early rather than grinding through 30+ dead runs).

## HIL test plan

| ID | Precondition | Stimulus | Acceptance criterion |
|----|--------------|----------|----------------------|
| **H1 — boot to idle** | Board flashed `-DHIL_SIM=1 -DUSE_ETHERNET=1`, nothing on the power stage. Simulator not yet started. | Power the board, read the USB banner; start `--scenario steady`. | Banner names HIL_SIM and the simulated-sensor warning. Within 1 s of simulator start the `'S'` dump shows `link: UP`, rising accept count, zero rejects. Board reaches State 1 (Idle) with no fault; `fault_flags == 0`. Simulator's rx count rises at ~1 kHz. |
| **H2 — fault injection (UV)** | H1 passing, board in Idle or Run with the bus brought up. | `--scenario sag` (bus −5 V for 1 s at t = 5 s). | `V_bus` in the CSV crosses below `LIMIT_V_BUS_MIN` 12.0 V for longer than the 20 ms dwell; the observation frame shows `mainState` 99 and `fault_flags` with the UV bit set, latched. Switch bitmask goes to the State-99 safe combination. No fault is raised by the sag *before* the dwell elapses. |
| **H3 — comm-loss hold-then-zero** | H1 passing, board in Idle, simulator logging. | `--scenario comm-loss` (1 s transmit gap at t = 5 s). | During the first 50 ms of the gap the board's behaviour is unchanged. `'S'` dump reads `STALE` between 50 ms and 250 ms with no fault attributable to the gap. After 250 ms it reads `DEAD (zeroed)` and the injected rails read 0 — the ordinary UV/sequencing logic responds to that as it would to a dead board. On resume, `link: UP` returns and the accept count resumes rising. |
| **H4 — closed-loop drive cycle** | H1 passing, board in State 98, `MOT_PWR_ENABLE` closed, `--scenario drive` running. | Command `'V' 1.0` (or a `'D'` drive cycle) over USB serial. | Injected `v_actual` in the CSV converges on the setpoint with no sustained ±12 A rail chatter; observed `current` shows the Hanus-conditioned ramp and release. Steady-state error small (the model has no encoder noise, so this validates the loop's *structure*, not its tuning). Compare against `controller_design_MIMO/figures/drive_siso_step.csv`. |
| **H5 — switch-sequencing observation** | H1 passing, board in State 98. | Exercise the bring-up (`'G'`), then toggle switches individually; attempt `FC_CHARGE_ENABLE` with `BT_BUS_ENABLE`/`REGEN_ENABLE` closed. | The observation frame's switch byte shows the §2 ordering at 1 ms resolution: `BT_SEQUENCE_ENABLE` off at boot then on; `assertFcChargeEnable()` drives `BT_BUS`/`REGEN` low **before** `FC_CHARGE` goes high — never a tick with the illegal combination. The aux byte shows `MPPT_DISABLE`/`CBAL_DISABLE` at their fail-safe levels from the first frame. |

## Limitations

- **The charger is simulated at the STATUS level only — its I2C transport is not.**
  What *is* exercised: `I_charge` and `ag105_status_raw` come from the injection
  frame, and everything downstream of them runs unmodified — the GENSTAT decode and
  `ag105IsReady()`, the `detectFaults()` GENSTAT error check (inject GENSTAT
  `0b101`/`0b110`/`0b111` to trip it), `I_charge` in telemetry and the BLG, and
  `chargingControl()`'s MPPT release gating. The firmware's own `chargerHasPower()`
  power gating is still read from the **real switch pins**, so the sequencing under
  test is the firmware's, not the host's.
  What is **not**: while the link is up, `pollAg105()` never touches the Wire bus
  (a HIL rig has no Ag105, so every real poll would be a NACK/timeout burning loop
  time and feeding the UDP drain backlog). Consequently `initAg105Charger()`'s
  read-verify-write config handshake is not simulated — `ag105Configured` is set by
  fiat once the charger is powered and settled — and neither `ERR_I2C_CHARGER` nor
  the charger `ERR_INIT_FAIL` path is reachable in a HIL build. Those stay
  bench-only. Before the *first* injection frame the real I2C path still runs, the
  same way the real ADCs do.
  The plant-side model is deliberately thin: input power → `AG105_SETTLE_S` bring-up
  → "Charging" with a first-order ramp toward the configured 2.5 A ceiling. No
  battery state of charge, no CV taper, no MPPT perturb-and-observe — `MPPT_DISABLE`
  only clears the tracking flags in the status byte.
- **Signal-level injection, not power-HIL.** Nothing electrical is exercised: the
  ADC front ends, the dividers, the INA253s, the RT1987 turn-on behaviour and the
  boosts themselves are all bypassed. A HIL pass says the *firmware logic* is
  right, not that the board is.
- **1 kHz soft real time on a non-realtime host.** Ticks can be late; the
  simulator reports achieved rate and worst overrun, and resynchronizes rather
  than replaying a burst of catch-up ticks. Read those numbers before trusting a
  timing-sensitive result.
- **The encoder estimator is bypassed.** `updateWheelSpeed()` is not called under
  HIL, so nothing here exercises the edge-period estimator, the fractional-pitch
  ledger, the adaptive gate or the corroboration hold. Those remain bench-only
  concerns, and the 74HC14 Schmitt fix is not testable here.
- **The plant model is first-order and deliberately simple.** Two simplifications
  are named at their sites in `hil_plant_sim.py`: a single droop bus node with no
  converter dynamics, and an FC/BT current split proportional to the droop MDAC
  code ratio (sign- and monotonicity-preserving, not the true analog gain). Do
  not fit control gains against it.
- **BLG logs from a HIL run set record flags bit6.** Bench logs written under
  `HIL_SIM=1` stamp `flags` bit `0x40` on every record, so a decoded run declares
  that its sensor columns are simulated rather than measured. Record size and
  header are unchanged (BLG stays v7). **Follow-up:** `tools/decode_benchlog.py`
  does not yet surface this bit — it passes the flags byte through raw.
- **Regen is floored at zero bus current.** The rig's VESC Battery Regen Max is a
  torque clip rather than a dump path (see the 2026-08-17b addendum), so
  decelerating energy stays kinetic in this model instead of returning to the bus.
