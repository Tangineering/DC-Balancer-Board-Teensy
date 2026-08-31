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
auto-recovery from the dead-link latch — widened at fw v23 to any latched fault across
a run boundary) are called out inline and shift some anchors
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
bench log's rails at the board instead of integrating a plant. It is open-loop, and
by default creates no commander at all, so the board sits in Idle
(`docs/HIL_MODE.md` "Replay mode"). Adding `--replay-commands` also replays the
log's recorded `v_sp`/`share_sp` as Pi command packets at 50 Hz, so the board
reaches Run and both control loops step — **the plant side stays open loop either
way**, so that tests the controller's *reaction* to a recorded stimulus, never
closed-loop tracking.

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

* `hil_plant_sim.py` — **CSV logging is on by default.** Every run writes a
  per-tick CSV and a `.meta.json` sidecar beside it; you do not have to remember
  a flag to keep a record.
  * **No `--csv`** — the run names itself
    `hil_<scenario>_<mode>_<YYYYmmdd_HHMMSS>.csv` under `HIL Results\`. The
    `<mode>` token says what drove the run: `open` (nothing — you drive over
    USB), `timeline` (the scenario's scripted Pi timeline), `ems-<strategy>`
    (Mode A), `pilive` (Mode B), or `replay-<log stem>`; a hi-fi run appends
    `-hifi`. Two runs started inside the same second get a `_1`, `_2`, … suffix
    rather than overwriting each other.
  * **`--csv <name>`** — a **relative** path (bare filename or with
    subdirectories) is resolved under `HIL Results\`; the directory is created
    if needed. An **absolute** path is honored verbatim. A name **you** chose
    is never silently overwritten: if the CSV *or either of its sidecars*
    (`.meta.json`, `.events.jsonl`) already exists the simulator refuses and
    exits **2**, and `--force` is the way to say you meant it. All three
    together are one run's record, which is why any one of them is enough to
    block.
  * **`--no-csv`** — write nothing at all: no CSV, no `.meta.json`, **and no
    hi-fi `.events.jsonl`** (all three derive from the CSV path). On an
    `--electrical hifi` run the simulator prints a notice, because that also
    discards the `scp_cut` / `sw_ring` / chopper event record. For throughput
    probes and repeated replays you do not want on disk.
  * The electrical events sidecar (`<csv>.events.jsonl`) follows the resolved
    path automatically. The simulator prints `[hil] CSV log: <resolved path>`
    at startup.
* `run_hil_suite.py` — the default report directory is
  `HIL Results\hil_report_<YYYYmmdd_HHMMSS>\`. An explicit `--out` keeps its
  old meaning (a relative path is relative to your current directory). The
  suite hands each child an absolute per-run CSV path, so those land inside the
  report directory rather than being redirected.

#### The `.meta.json` sidecar — what a run WAS

Every CSV gets a `<csv>.meta.json` next to it, so a `HIL Results\` folder read
six months later needs no shell history to interpret. It is written **twice**:
once before the 1 kHz loop starts, with `"status": "running"`, so a run you kill
(or that the suite times out) still leaves a record of what was attempted; and
again at exit with `"status"` `completed`, `interrupted` (Ctrl-C) or `error`,
plus the results. Nothing about it touches the real-time loop.

It carries:

* the **scenario** (name, description, default duration, engine) and the **mode**
  token from the filename, plus `ems_strategy`, `pi_live` and `replay_source`;
* `argv` verbatim and a `config` block with the *resolved* run parameters
  (duration, rate, electrical engine, trace config, VESC capacitance, noise,
  `soc0`, capacity, board IP/port);
* `constants` — every module-level numeric constant of `hil_plant_sim.py` and
  `hil_electrical.py` — and `constants_hash`, a sha256 over them. **This is the
  model-provenance record**: a `K_DROOP_BUS` retune or a `K_F` correction moves
  the hash, so two runs can be compared without anybody having to remember which
  constants were in the tree. The dict itself is included, so the hash is
  auditable rather than opaque.
  **Changelog — 2026-08-31: the hash moved.** The DP-EMS round added **20
  constant names** (16 `SOC_BAND_*`, plus `H2_GFC_TS_S`,
  `H2_GFC_DC_GAIN_GPS_PER_W`, `H2_GFC_TAU_DOMINANT_S` and
  `H2_STATIC_PROXY_GPS_PER_W`). The additions are **purely additive — no
  pre-existing constant changed value** — but because the hash covers the whole
  set, a pre-2026-08-31 `constants_hash` is **not comparable** with a later one
  even on an otherwise identical model. Compare the `constants` dict, not the
  hash, across that boundary (this is exactly the limitation
  `collect_model_constants()` documents);
* `git`: the HEAD revision and a `dirty` flag (nulls if git is unavailable —
  provenance never fails a bench run);
* `results`: achieved rate, ticks, `csv_rows`, max overrun, frame counters
  (tx/rx/malformed/send errors/Pi commands), the last observed `state`,
  `switch`, `aux` and `fault_flags`, hi-fi substep rate and event counts, the
  events-file path, final SOC — and the **warm-reset tripwire**
  (`warm_resets_observed`, `warm_resets_mid_run`, `warm_reset_times_s`,
  `warm_reset_grace_s`), described next.

#### The mid-run warm-reset tripwire

From fw v23 the board leaves its latched State 99 on its own after a **run
boundary**: the injection link continuously dead for 1000 ms, then fresh again
for 500 ms. Between runs that is exactly what you want. **Mid-run it is a
hazard** — a host stall of a second or more (a garbage collection, a laptop
parking a core, a blocked disk write) looks identical to a run boundary, so the
board warm-resets under you.

The damage is worth stating precisely, because the obvious version is wrong. A
latched fault does **not** silently disappear: the checks that read the fault
*union* over a run, or the replay suite's `fault_latched` entries, see it fire
and fail loudly. What actually breaks is subtler:

* after the reset the board runs State 0 → bring-up → Idle, so **the rest of the
  run is not the scenario** its checks assume — the stimulus timeline keeps
  playing against a board that restarted underneath it;
* a fault that fires *again* after the reset reads as having fired once, so any
  dwell or timing conclusion drawn from it is wrong;
* a check keyed to the **final** state or flags reads the clean post-recovery
  board and passes.

None of that is recoverable after the fact, which is why such a run is reported
as inconclusive rather than interpreted.

The simulator therefore counts every `mainState` transition out of State 99 and
prints it at exit:

```
[hil] warm resets: 1 observed, 1 mid-run (after 2.0s) at t=7.612s
```

A transition **before** t = 2.0 s is the start-of-run recovery from the previous
run's settle pause and is not counted as mid-run; one at or after 2.0 s is
(`t >= WARM_RESET_GRACE_S`, so exactly 2.0 s counts as mid-run). If a mid-run one
occurs the simulator says so in plain terms, and `run_hil_suite.py` marks that
run **INCONCLUSIVE** rather than PASS or FAIL: nothing about the board was
disproved, the evidence was destroyed. Re-run it on an unloaded host. A run that
was inconclusive **and** failed checks of its own is labelled
`INCONCLUSIVE (also FAILED n check(s))` — those failures are real and are not
cleared by a re-run.

The suite also emits a non-failing **NOTE** whenever grace-window transitions
occurred. Usually that is just the expected inter-run recovery. On the *first*
run of a plan against a freshly powered board there is no previous run to recover
from, so a transition there means the board was already latched at power-on —
worth a look before believing the rest of the plan.

`comm-loss` is the one scenario where the recovery *is* the test — its 2 s gap
exists to cross the boundary — so it **requires** exactly one mid-run warm reset
(declared as `warm_resets_expected` in the scenario registry). Even there the
whitelist covers only the one reset the scenario provokes: **more** than expected
is inconclusive exactly as anywhere else (the extra one destroyed evidence),
while **fewer** is a plain failure — the recovery the scenario exists to test did
not happen. If no count is available at all, the requirement is reported
UNVERIFIED rather than passed.

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

Drop `--csv ems_run.csv` and the run still logs — to
`HIL Results\hil_ems-drive-cycle_ems-hold-5050_<timestamp>.csv`, which is the
better habit for repeated runs: the fixed name above is refused on the second
run unless you pass `--force` (§2.5).

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
* CSV columns `h2_rate_gps` / `h2_cum_g` carry the hydrogen-consumption metric,
  and the exit summary prints the cumulative total. ⚠️ These are the **Gfc
  model's estimate** of hydrogen mass: the map is scale-portable, but the stack
  is not identified against this rig (`TODO(calibrate)`). See the warning under
  §3.2.2.

### 3.2.1 The strategies that exist

`--ems` choices come from `EMS_STRATEGIES` in `tools/hil_plant_sim.py`.

| Strategy | Decides | Portable to a real Pi? | Paired scenario |
|---|---|---|---|
| `hold-5050` | share pinned at 0.50; `v_setpoint` from the scenario profile; no charging | **Yes** — reads only `t` and `v_profile` | `ems-drive-cycle` |
| `regen-harvest` | same, plus `charge_goal` **inside braking windows only**, so the Ag105 is fed through REGEN and `FC_CHARGE` never opens | **Yes** — same two keys | `charge-regen` |
| `soc-band` | deadband-P **share bias** on the SoC error, plus **opportunistic FC-path charging** in cruise | **No, as written** — it closes on `fb["soc"]`, which is plant truth (see the portability list under §3.3) | `ems-soc-band` |
| `dp-replay` | nothing — it **plays back a table** of `power_share_setpoint` / `charge_goal` computed **offline** by backward dynamic programming with full foreknowledge of the whole cycle | **No, and never** — a Pi has no future. This is a *benchmark*, not a controller | `ems-dp-replay` |

### 3.2.2 `soc-band` and the H2 metric — a walkthrough

```powershell
.venv_hil\Scripts\python.exe tools\hil_plant_sim.py --teensy-ip 192.168.1.50 --scenario ems-soc-band --dash
```

`--ems` may be omitted: the scenario declares `soc-band` as its default.

**What the policy does.** It captures the SoC it started at (`SoC0`) on its first
call and sustains *that* — it does not choose an absolute target. Inside a
±`SOC_BAND_HALF` deadband the split stays at 0.50. Below the band it shifts load
toward the **fuel cell** (higher `power_share_setpoint`, so the pack discharges
more slowly), above it toward the **battery**, proportionally, saturating at
±0.25 — i.e. the command never leaves `[0.25, 0.75]` and so can never trip the
firmware's share-cut band `[0.15, 0.85]`. It asserts `charge_goal` only when all
three of: SoC genuinely below the band, **cruise** (measured from a trailing
1 s window of setpoints it has already issued — never by looking ahead), and a
measured source total under the admission threshold. It never charges during
acceleration (operator ruling (b), 2026-08-30: FC-path charging and hard
acceleration are incompatible on this hardware by design).

**What you should see**, on the 61 s scenario:

| t (s) | Expect |
|---|---|
| 3 | `MODE_HYBRID`; the board leaves Idle |
| 8–38 | cruise 1.5 m/s with a 1.0 A drain load; `share sp` holds 0.500 while SoC is inside the band |
| 24.30 | `share sp` starts climbing — SoC has left the band |
| 34.90 | `share sp` saturates at **0.750**; `I_fc` visibly above `I_bt` |
| 38–41 | decelerate to 1.0 m/s, drain ramps out; **no** charging (not cruise) |
| 41.70 | `charge_goal` asserts; `SW_FC_CHARGE` sets and `SW_BT_BUS` clears |
| ≈ 42.6 | `I_charge` > 0.5 A (0.8 A de-rated ceiling for this scenario) |
| 54–58 | decelerate to standstill, charging released |
| 58 | `MODE_SAFE`; Run → Finish → Idle |

Fault-free throughout is the expected outcome.

> ### ⚠️ The H2 numbers are model estimates, not stack-calibrated
> `Gfc` is the fuel-cell consumption model from the PhD student's FCHEV study
> (`references/EMS/DPtrial.m:51-52`), fit at full scale (106 kW). It is
> **scale-portable without adjustment** (operator ruling 2026-08-31): its input
> (`P_fc`, W) and output (g/s) both ride the system's energy scaling factor, per
> `references/Systemic_Scaling_of_Powertrain_Models_with_Youla_Driver_Control.pdf`
> — the `720` in `den[0] = 1044 = 720 × 1.45` is the full-size **fuel cell's
> OCV**, not a battery term. What it is **not** is identified against this rig's
> particular stack (`TODO(calibrate)`), and its DC gain implies η = 47.25 % where
> the same study's static proxy assumes 55 % (+16.4 %). Quote `h2_cum_g` as the
> model's estimate with that calibration caveat; strategy *rankings* on the same
> rig are robust regardless. Full statement: `docs/HIL_PLANT.md` §9.3.

### 3.2.3 `dp-replay` — the offline-optimal benchmark

```powershell
.venv_hil\Scripts\python.exe tools\hil_plant_sim.py --teensy-ip 192.168.1.50 --scenario ems-dp-replay --dash
```

> ### ⚠️ This is NOT a controller
> `dp-replay` plays back a **time-indexed setpoint table** computed offline with
> **full foreknowledge of the entire drive cycle and the entire auxiliary
> load**. It reads no feedback and reacts to nothing. Its only purpose is to be
> the **lower-bound reference** the causal strategies are ranked against — "how
> much did `soc-band` leave on the table?". It is not implementable on the Pi
> and it is **meaningless against any other profile**, which is why it refuses
> to start unless the active scenario's profile fingerprint matches the table's.

**Generating the table.** The table is checked in at
`tools/dp_tables/dp_ems_table_ems-dp-replay.csv`, so a normal run needs no
extra step. Regenerate it after any change to the `ems-soc-band` /
`ems-dp-replay` profile or drain constants — the strategy will refuse until you
do, naming the mismatch:

```powershell
C:\Users\ricky\miniforge3\python.exe tools\gen_dp_ems_table.py --scenario ems-dp-replay --force
```

The generator needs **numpy**, so it runs under **miniforge**, not `.venv_hil`
(which is stdlib-only and is the *simulator's* interpreter). It is offline
tooling — nothing in the 1 kHz loop imports it. It refuses to overwrite an
existing table without `--force`, and is byte-deterministic: the same inputs
produce the same file, and it prints a sha256 so that is checkable.

**One flag you must get right.** `--charger-accounting` selects which hydrogen
accounting the DP minimises, and it must match the electrical engine the table
will be replayed under:

| Setting | For | Why |
|---|---|---|
| `physical` (default) | `--electrical hifi`, i.e. a **default suite campaign** (`--electrical-pref` is `hifi`) | hi-fi stamps the Ag105's draw on the bus, so the fuel cell genuinely pays for charging |
| `simple` | `--electrical simple` | simple mode does **not** stamp it, so the logged metric gives pack charge away free — a `physical` table replayed there is beaten by `soc-band` and is not a bound at all |

**What you should see**, on the 61 s scenario (from the shipped `physical`
table):

| t (s) | Expect |
|---|---|
| 3 | `MODE_HYBRID`; the board leaves Idle |
| 0–4 | `share sp` **0.250** — the DP runs on the battery while the bus is quiet |
| 4–10.6 | `share sp` ramps up as the drain load comes on |
| 10.6–40.1 | `share sp` pinned at **0.750**, the fuel-cell rail; `I_fc` ≈ 1.10 A of a ~1.46 A bus total |
| 41–54 | `share sp` ≈ **0.525** through the low cruise |
| 54–58 | `share sp` back down to 0.250 |
| 58 | `MODE_SAFE`; Run → Finish → Idle |

`charge_goal` is **0 for the entire run**, and that is a *result*, not a gap:
shifting the split toward the fuel cell buys 0.405 SoC per gram of hydrogen
where running the Ag105 buys 0.169, so opportunistic charging is simply the
worse lever at this rig's numbers. Fault-free throughout is the expected
outcome.

The single sharpest tell that the table really was played: `cmd_share_sp` is at
**0.750 by t ≈ 12 s**, which the causal `soc-band` policy cannot reach before
t ≈ 35 (its SoC deficit has to saturate first).

### 3.2.4 Comparing EMS strategies

Run `ems-soc-band` (causal) and `ems-dp-replay` (offline-optimal) — the suite
runs both, on the **same profile, the same drain load and the same object** for
the speed profile, so nothing but the decision rule differs. Compare on **three
axes, and never on one alone**:

1. **`h2_cum_g`** — cumulative hydrogen. ⚠️ The model's estimate, stack not
   identified against this rig (§3.2.2's warning); the *ranking* is robust.
2. **`delta_soc`** — how much pack charge the run actually spent.
3. **Share tracking** — did `I_fc` follow `cmd_share_sp`? That is the *firmware's*
   contribution and is separate from the policy's.

Both of the first two appear in `REPORT.md`'s summary row and in the per-scenario
block (`EMS energy: h2_cum_g …, delta_soc …`), for **any** scenario whose CSV
carries the columns.

**Axes 1 and 2 are a PAIR.** Any strategy burns less hydrogen by discharging the
pack harder, so a hydrogen ranking is only valid at matched `delta_soc`. The
generator handles this on the prediction side by bisecting its terminal-SoC
weight until the DP's predicted terminal SoC equals the causal strategy's
(`--match-terminal-soc`, default `heuristic`); on that matched basis its own
reduced model predicts the DP **14.3 % below** `soc-band`. The *measured* run
will not match either prediction exactly, and there is no mechanism forcing the
two realised runs to land on the same `delta_soc` — so read the measured pair as
a pair, and treat a hydrogen difference at visibly different `delta_soc` as
uninterpretable rather than as a ranking.

**Two more caveats before quoting a comparison.** The DP's advantage is computed
in a *reduced* model (no share loop, no Ag105 settle/ramp, a 0.1 s stage, the
`Gfc` **DC gain** rather than its 0.22 s dynamics), so it is an estimate of the
gap, not a measurement of it. And the DP is open loop by construction: it cannot
react to the board or the plant doing anything the generator did not predict.

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

Mode B runs are usually repeated while the Pi side is being brought up, so the
fixed `--csv pilive.csv` above is refused from the second attempt onward (exit 2).
Add `--force` to overwrite, or — better while iterating — drop `--csv` and let each
attempt auto-name itself into `HIL Results\` so the failed ones stay comparable.

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
> observation stream and restart its timeline on a 99 → 0 transition. **From fw v23 this
> applies to every latched fault, not only the dead link:** a UV, an OV, a bring-up
> failure or a Pi timeout all warm-reset the same way once a run boundary passes, so
> 99 → 0 is the one signal to key on and the Pi must never assume the transition means
> the link merely blinked. Full statement of the hazard in §4.4.

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
| Board answers, then latches `0x8010` with error `HIL link dead` | `ERR_HIL_STALE`: >250 ms with no *injection* frame (`HIL_ZERO_MS`, `.ino:2615`) — simulator stopped, Ctrl-C'd, or the cable moved | **fw v22: just restart the simulator.** After ~500 ms of fresh frames the board warm-resets itself to State 0, re-runs the bring-up and returns to Idle — no power cycle. On fw v22 it stayed latched if some *other* fault bit latched too; **from fw v23 any fault recovers**, provided the link went silent for more than 1 s first (the run boundary, measured from the last frame the board accepted). Leave the simulator down for a couple of seconds before restarting — a stop-and-restart inside 1 s does not qualify. *(fw v21: power-cycle for a clean State 1.)* |
| `faults=0x8010` with error `Pi timeout` while running | Pi stopped commanding for >500 ms in State 2/3 | Restart the Pi bridge, then power-cycle the board. Note the flag is the same bit as above — read `error_code` to tell them apart (`ERR_PI_TIMEOUT` 0x05 vs `ERR_HIL_STALE` 0x10, `.ino:1492`, `.ino:1505`). **On fw v22 the auto-recovery did NOT apply here** (it required `error_code == ERR_HIL_STALE`). **From fw v23 it does**, but only across a run boundary: stop the simulator for a couple of seconds (more than the 1 s of link silence the boundary needs) and restart it, and the board warm-resets instead of needing the power cycle. |
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
  bring-up and returns to Idle. Watch for `[HIL] run boundary + link recovered — warm
  reset, re-entering State 0` on the USB console and `faults` clearing to `0x0000` on the
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
  > at t = 0 there** (or stop commanding and let the operator restart it). **From fw v23
  > the reset can follow ANY latched fault** — UV, OV, `INIT_FAIL`, `MOT_HOTPLUG`, a Pi
  > timeout — not just the dead link, so a commander cannot infer the cause from the
  > transition and must treat every 99 → 0 as a fresh run. Mode A's
  > per-process simulators are immune by construction — each run is a new process that
  > starts at t = 0 — so this is a Mode B and custom-runner hazard.
* **Simulator died *during* the bring-up** — a special case, and it is benign. The
  bring-up's phase gates are timed against `millis()` while the sensor values are held,
  so a phase timeout there would latch `FAULT_INIT_FAIL` / `FAULT_MOT_HOTPLUG` — blaming
  the *plant* for the host having stopped answering. (Under fw v22 that latch was also
  permanent, since neither fault was in the recoverable set; from fw v23 both would clear
  across a run boundary, but only at the cost of one — the host must go silent and come
  back — and the false fault would still be reported in that run's results.) The firmware
  instead aborts the bring-up safely the moment the link goes stale and prints
  `[bringup] HIL injection link lost mid-bring-up — aborting (not a fault); State 0
  re-arms when frames return.` The stage goes dark, no fault latches, and the bring-up
  simply restarts when the simulator comes back — within the same run. Under the
  State-98 `'G'` command the board stays in State 98 with the same notice.
* **Pi died / restarted** — if the board was in State 2/3 it latched `PI_TIMEOUT`.
  On fw v22 this was **not** auto-recoverable. **From fw v23 it is**, but only across a
  run boundary: stop the simulator for a couple of seconds (the boundary needs more than
  1 s of link silence, measured from the last frame the board accepted), then restart it,
  and the board
  warm-resets ~500 ms later. Restart the Pi first, then re-run steps 2–3.
* **Cable/switch glitch** — both of the above at once. From fw v23 the fault *code* no
  longer decides whether the board self-recovers; the run boundary does. Stop the
  simulator, fix the link, restart, and re-run the whole sequence from step 0. Do not
  try to reattach mid-flight.

There is still deliberately **no remote fault reset**, and no operator command clears a
latch. The auto-recovery is narrower than one: only under `HIL_SIM`, only after the
State-99 teardown has completed, only with the bench log closed, only once the injection
link has been continuously fresh for 500 ms, and — from fw v23 — only after a **run
boundary**, meaning `HIL_RUN_BOUNDARY_MS` = 1000 ms passed with no injection frame — timed
from the last frame the board accepted — while it sat in State 99. **A fault raised during
a run normally stays latched for the rest of that run**, whatever it is; taking the
simulator down for a couple of seconds is what marks the run over. "Normally" is doing
real work in that sentence: the board cannot tell a *deliberate* gap from a **host stall
of ≥ 1 s**, so a stalled laptop forges a boundary mid-run and the board recovers under
you — and `comm-loss` forges one on purpose (its 2 s transmit gap). That is what the
mid-run warm-reset tripwire in §2.5 exists to detect; do not treat "it stayed latched" as
a guarantee you can lean on. Exactly 1.0 s of silence is knife-edge, so do not design a
gap at the boundary. On a non-HIL build nothing clears a latch except a board reset.

---

## 5. Suite runs

```powershell
# scripted, everything (15 scenarios + 27 replays; `drive` is SKIPPED, see below)
.venv_hil\Scripts\python.exe tools\run_hil_suite.py --teensy-ip 192.168.1.50

# with the live dashboard on each child (needs a real terminal)
.venv_hil\Scripts\python.exe tools\run_hil_suite.py --teensy-ip 192.168.1.50 --dashboard

# also run the operator-required scenarios -- BE AT THE CONSOLE
.venv_hil\Scripts\python.exe tools\run_hil_suite.py --teensy-ip 192.168.1.50 --with-operator

# Mode B: a real Pi drives every scenario
.venv_hil\Scripts\python.exe tools\run_hil_suite.py --teensy-ip 192.168.1.50 --pi-live --scenarios-only
```

**`--with-operator`.** The `drive` scenario is marked `operator_required`: its whole
stimulus is a human driving the firmware over USB serial (`'V'`, `'D'`, `'Y'`). Run
unattended it commands nothing at all -- the board sits in Idle, the commanded current
is 0.000 A for the whole run, and the drive loop is never exercised -- so by default the
suite renders it **SKIPPED** with a reason rather than scoring a vacuous clean result.
Pass `--with-operator` only when you are at the console and intend to drive it by hand.
Unattended drive-loop coverage is `ems-drive-cycle`'s job.

**How faults are scored (2026-08-30).** Two things changed and both affect how a report
reads:

* **Grace-aware scoring.** Every fault judgement -- scenarios and replays alike -- uses
  observations at `t >= 2.0 s` only. The board warm-resets out of the previous run's
  `ERR_HIL_STALE` settle latch at about `t = 0.5 s`, so every run after the first opens
  showing `0x8010` (or `0x8011` / `0xA010` if its predecessor latched something of its
  own) through no fault of its own. `REPORT.md` still prints the full whole-run union
  and names the carried-in bits separately. A board that *stays* latched still fails --
  the exclusion is on the observation window, never on a bit value.
* **`FAULT_EXPECTATIONS`.** The old permissive "fault allowed" table always passed, so
  it rubber-stamped runs that died before reaching their own stimulus. Each scenario now
  declares what must appear, what may appear, when the stimulus is, and whether the
  board had to still be alive and in Run to reach it. Notably **`charge-cruise` now
  REQUIRES an `OC_FC` latch**: FC-path charging and hard acceleration are incompatible
  on this hardware by design (a single source carries the bus during FC-charge), and the
  latch is the validation of that boundary, not a failure. `scp-inrush` is scored on an
  `scp_cut` event appearing in the hi-fi events sidecar rather than on fault flags.
* **Positive signal checks.** Fault expectations only say what must *not* happen, and a
  run can satisfy every one of them while exercising nothing. Four scenarios now also
  assert a trace fact: `charge-regen` (REGEN really asserted during a braking window,
  and `I_charge` really delivered through it), `charge-fault` (charging established
  before the input collapses), `soc-depletion` (SoC genuinely fell), `handoff-sag` (the
  bus switch really opened and stayed open). A `signal_*` failure means the scenario
  stopped testing its own objective — treat it as seriously as a fault failure.
* **Longer `soc-depletion`.** Its endurance load dropped 3.0 → 2.2 A (at 3.0 A the
  surviving battery channel sat above `LIMIT_I_BT_MAX` for the whole run), and its
  duration rose 650 → 880 s so the depletion depth is unchanged. **The full suite is
  now ~34.5 min rather than ~30.6.**

Mode tagging: `results.json` / `REPORT.md` carry `mode: "pi-live"` or
`"scripted"` in the report header and on every per-run record (`cmd_mode`).

Under `--pi-live`:

* Every scenario that carries its own `pi_timeline` — and `ems-drive-cycle`, whose
  whole stimulus is the EMS layer — is **SKIPPED with a reason**, not failed. They
  appear in the plan and the report marked `SKIP`, and the result line says how
  many of the "passed" runs were skipped rather than executed.
* `FAULT_PI_TIMEOUT` (0x0010) is **excused** on scenarios that otherwise expect no
  fault: the Pi's command cadence is the operator's, not the harness's. The excusal is
  judged on the post-grace union, so the inherited settle latch (which is *also*
  `0x8010`) can no longer be mistaken for it.
* The **comm-loss expectation is unchanged**. Verified from source: the HIL stale
  clock keys on accepted *injection* frames only — `hilLastFrameMs` is stamped in
  `receiveCommands()`'s commit block (`.ino:4970-4976`) and aged in
  `updateSensors()` (`.ino:4379-4431`), while a 22-byte Pi command takes the other
  branch (`processPiCommandPacket()`, `.ino:4835`) and touches only `last_rx_ms` /
  `pi_ever_connected` (`.ino:4884-4885`), which belong to the separate Pi watchdog.
  **A real Pi's traffic does not keep the HIL link alive**, so `comm-loss` still
  latches `ERR_HIL_STALE` with the Pi attached.

**Between runs (fw v22/v23).** The 5 s inter-run settle is far longer than the 250 ms
zero stage, so the board latches `ERR_HIL_STALE` after each run — and then warm-resets to
State 0 when the next run starts streaming, bringing the simulated stage up again. Each
run therefore begins from a fresh-boot equivalent rather than from a latched board, and
the whole plan runs unattended. On fw v22 a run that latched a *real* fault still left
the board latched, so one bad scenario stalled the rest of the suite. **From fw v23 that
case recovers too**, because the 5 s settle also satisfies the 1000 ms run boundary — but
the fault normally stays latched for the whole run that raised it, so the run's own health
checks report it exactly as before — unless a host stall forges a boundary mid-run, which
is what the tripwire below catches. Keep `--settle-s` well above 1 s — the runner warns
below 1.5 s. At or under the 1000 ms boundary the window **may not** accrue and the fw v22
behaviour returns; "may not" is exact, because the boundary is anchored at the board's last
accepted frame, so the previous child's teardown and the next child's startup also count
toward the dead window and the true gap is longer than `--settle-s` by an unmeasured
margin. The wrapper now says so
itself: any `--settle-s` under **1.5 s** prints a boxed warning at plan time (before
`--list`, `--dry-run` and real runs alike). It is a warning and not a floor —
`--settle-s 0` plus a power-cycle between runs stays the deliberate way to give every
run a clean-boot board.

Each child gets an explicit absolute `--csv` inside the fresh report directory, so the
simulator's auto-naming and its overwrite refusal never apply to a suite run. Each of
those CSVs still gets its own `.meta.json` sidecar (§2.5), which is the per-run record
of the constants hash and git revision the run actually used — and, for the report's
warm-reset tripwire, the authoritative mid-run count (the sidecar survives
`--dashboard`, where the child's stdout is never captured).

**INCONCLUSIVE runs.** A run whose child observed a *mid-run* warm reset (§2.5) is
reported as `INCONCLUSIVE`, counted separately in the header and the closing line, and
excluded from the passing total — so the suite exits 1 and you know to re-run it. It is
not a board failure. `comm-loss` is exempt: it requires exactly one.

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
| `faults=0x0010`, error `HIL link dead` | Simulator stopped or the host stalled >250 ms | Restart the simulator — on fw v22 the board warm-resets to State 0 by itself ~500 ms later. On fw v22 a power cycle was still needed if `fault_flags` was not exactly `0x8010`; **fw v23 recovers any fault** once the link has been silent for more than 1 s (the run boundary). |
| Frequent brief `hilStale` without a fault | Host scheduling jitter in the 50–250 ms band — held values, motor stood down | Close other load on the PC; check the achieved-rate line (target ≥ 900 Hz) |
| `--dash` refuses to start | stdout is not a tty (piped, redirected, CI) | Run in a terminal, or drop `--dash` |
| `--dashboard` rejected by the suite | Same, at the wrapper level | Run interactively or drop the flag |
| Achieved rate well under 1000 Hz | Host stall, or the hi-fi engine on a slow PC | Try `--electrical simple`; the suite gates at 900 Hz |
| Pi commands ignored | Board not in a state that accepts them, or already latched in 99 | Check `state` on the status line. `mode_cmd` is acted on only in State 1 (Idle), and a fw v22 warm reset resets it to SAFE — so after a recovery the EMS/Pi must re-send its mode command. To clear a latch, stop the simulator for a couple of seconds and restart it (fw v23 run boundary); on fw v22 a non-dead-link latch needed a power cycle. |

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
