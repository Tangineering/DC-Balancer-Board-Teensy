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
> small (~0.5 Mbit/s: 40 B + 18 B at 1 kHz plus 22 B + 58 B at 50 Hz, framing
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

> ### ⚠ fw v25 changes the observation frame — update the tooling BEFORE you flash
>
> The observation frame grows **17 → 18 bytes** at fw v25 (`error_code` appended at
> offset 16; the XOR span becomes bytes 1..16). The simulator validates frames by
> length, so a **fw v25 board talking to a pre-fw-v25 checkout is observation-blind**:
> every frame is length-rejected, the run presents as *"the board never answered"*, and
> `run_hil_suite` fails it on `observation_frames`. This is not a subtle degradation —
> nothing works.
>
> **The fix is already in this checkout.** `tools/hil_plant_sim.py` accepts 16-, 17- and
> 18-byte frames with a length-derived checksum span, so it speaks to fw v21–v23,
> fw v24 and fw v25 boards alike. Confirm it before a campaign: the simulator prints one
> provenance line naming the length the board is speaking —
> `[hil] observation frame: 18 bytes — fw v25+ (mppt_thresh_count + error_code present)`.
> A line saying *17 bytes* against a board you believe is fw v25 means the flash did not
> take.
>
> **What the new byte buys.** `FAULT_PI_TIMEOUT` and `FAULT_HIL_LINK` share fault bit
> `0x0010` and `fault_flags` is protocol-frozen, so a `0x8010` union was wire-ambiguous
> between *"the Pi watchdog fired"* and *"the injection link died"*. `error_code` is the
> **latched first cause** — `triggerFault()` records it exactly once, where it only ORs
> bits into `fault_flags` — so `ERR_PI_TIMEOUT` (0x05) and `ERR_HIL_STALE` (0x10) are now
> distinct. The suite reads it directly (see §7's `pi-silence` note and the `--pi-live`
> excusal) and falls back to the older stream-health *inference* only on a pre-v25 board.
> The dashboard renders it on the faults line as `err=…`; an em-dash there means the
> board's frame has no such byte, never *"no error"*.

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
* `config.sdp_policy` — **SDP-strategy runs only** (`--ems sdp-v3` / `sdp-v2`), absent otherwise: which
  baked policy drove the run (`path`, `file_sha256`, `policy_sha256` plus the
  recipe that produced it, `generated_utc`, the grid shape, `decision_dt_s` and
  the source TPM's sha256). It is here because nothing else in this document
  can identify the artifact — `constants_hash` covers module constants, not a
  JSON file on disk, so a regenerated policy would change every command in the
  run while leaving the rest of the sidecar identical (§3.2.3a). ⚠️ It is also
  the **only** place a trace says which *demand map* — and, since 2026-09-01,
  which *charge economics* — it ran: all three `sdp_policy_v*.json` files declare
  the same `schema`, so `policy_sha256` and the artifact's own `normalization`
  block are what separate them (`0443febf…` = the calibrated benchmark `v3`,
  `740c802e…` = the frozen demonstration `v2`, `dbe42d1b…` = the retired `v1`). It carries
  `soc_ref_offset` too (2026-08-31): that scenario key decides which branch of a
  bang-bang policy the run STARTS on, and it leaves no other trace anywhere in
  the CSV — see §3.2.3b;
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
  **Changelog — 2026-08-31 (Round C): the hash moved again.** The wave-2
  scenario round added **19** more names: `AG105_MPPT_V_THRESH`, `AG105_MPPT_V_HYST`, `COMBINED_PROFILE_S`, `COMBINED_PROFILE_MS`, `EMS_MPPT_CRUISE_LEAD_IN_S`, `EMS_MPPT_CRUISE_LEAD_OUT_S`, `EMS_Y_START_S`, `EMS_Y_END_S`, `EMS_Y_DURATION_S`, `EMS_Y_RUN_EXIT_S`, `Y_AUX_LOAD_A`, `FTP75_DURATION_S`, `FTP75_T_END`, `FTP75_PRELOAD_A`, `FTP75_RUN_EXIT_S`, `FTP75_SCALE_MPH_TO_MPS`, `STAIRCASE_LOAD_A`, `STAIRCASE_LOAD_B`, `STAIRCASE_DROP_S`.
  Purely additive again — no pre-existing constant changed value, none removed.
  `FTP75_SCALE_MPH_TO_MPS` is there incidentally: the generator-binding check
  added this round re-exports it into `hil_plant_sim`'s namespace, so the
  collector now sees a constant that already governed the FTP-75 stimulus. The
  boundaries compound — a **pre-Round-C** hash is not comparable with a later
  one, and neither is a pre-2026-08-31 one; compare the `constants` dict across
  either;
  **Changelog — 2026-09-01 (the C1 round): the hash moves again, and this
  time a MODEL DEFAULT moves with it.** The converter-asymmetry round added
  the `ASYM_*` names and, unlike every previous move, it is **not purely
  additive in behaviour**: `--asymmetry` defaults to `measured`, so the plant
  now runs the fitted FC/BT mismatch instead of two identical boost chains:
  the **M2 CONSISTENT PAIR**, ΔV₀ **+0.013522 V** at s_B = 1 with ρ →
  `droop_scale_fc` **0.9434**. The two are one fit and move together; an
  earlier cut of this round mixed M1's ΔV₀ 0.0444 with a separately fitted
  ρ, which double-counts the same physical asymmetry (RMS against CAL-1
  0.0402, versus **0.0063** for the adopted pair). The injected voltage is
  scaled by the `--droop` mode's own scale so the **share** deviation is the
  invariant, and the sense-arm correction is applied from the INA offsets a
  run actually injects rather than from `--noise` being present. See
  `docs/HIL_PLANT.md` §4.4a.
  **What actually moves.** Shares and per-channel currents; α at r = 0.5 goes
  0.5000 → **0.5248** (`--droop design`) / **0.5207** (`measured`) at ≈ 1 A.
  **`V_bus` does NOT move** — the offsets are antisymmetric about `V0_NOLOAD`,
  and a reviewer confirmed the solved bus node bit-identical at a pinned
  actuator point, so every `V_bus`-referenced pin is mean-preserved. Light
  load: a voltage mismatch starves the low channel below ~ΔV₀/R_B of total
  current, which is **~21 mA** at the adopted value (against ~140 mA at the
  retired M1 one) — below `I_AUX_A` 0.15 A, so no live scenario dwells there.
  **⚠️ COMPARABILITY — TWO BOUNDARIES, ONE CAMPAIGN.** Campaign
  `hil_report_20260901_151156` is the last campaign on the far side of BOTH
  the drive-cycle preload removal AND the asymmetry default. A share, a
  per-channel current or an EMS hydrogen total from it (or anything earlier)
  is **not comparable** with a current run for two independent reasons.
  Measured governor-walk hydrogen deltas, symmetric → asymmetric at the M2
  pair: `ems-ftp75-5050` **+6.40 %**, `-socband` **+3.22 %**, `-sdp`
  **+2.95 %**, `-dp` **+4.32 %**; every SoC fall shrinks correspondingly.
  (~two thirds of the M1-era figures first recorded here.) Pass
  **`--asymmetry off`** to reproduce the symmetric plant — it is byte-identical
  to the pre-C1 engine — and read `config.asymmetry` in a run's meta sidecar
  to place any trace on one side of the boundary. `run_hil_suite.py` carries
  the same flag for the scenario half and renders the resolved mode in the
  REPORT.md header table; the replay half realizes no asymmetry in either
  mode, because a replay run drives its rails from a log and constructs no
  hi-fi engine at all;
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
* CSV columns `p_mot_w`, `p_fc_w`, `p_batt_w`, `p_chop_w`, `p_aux_w`, `p_bal_w`
  (appended 2026-09-01f) and `p_chg_loss_w` (appended after them, 2026-09-01)
  carry the per-tick power balance in watts, and
  `tools/hil_report_analysis.py` renders them as the `hil_power_balance` figure
  in every run folder. The identity is

      p_mot + p_chg_loss = p_fc + p_batt + p_chop + p_bal

  with the Ag105 dissipation on the **load** side, beside the motor draw, because
  it is a dissipation. Read `p_bal_w` as the residual of that identity, **not**
  as an error: its named components are the auxiliary load (plotted separately as
  `p_aux_w`), bulk-capacitor storage, the hi-fi motor stamp's transient term and
  the RT1987 drops. The charger is no longer among them — it is the
  `p_chg_loss_w` column. A CSV written before that column existed carries the
  charger term inside `p_bal_w`, and the figure annotates itself when it reads
  one. Full definitions
  and the measured residual magnitudes are in `docs/HIL_PLANT.md` §7.1. On a
  replay CSV, and on any campaign up to `hil_report_20260901_151156`, the columns
  are absent and the figure falls back to a **legacy backfill** that carries an
  on-figure annotation of what it could not derive.

### 3.2.1 The strategies that exist

`--ems` choices come from `EMS_STRATEGIES` in `tools/hil_plant_sim.py`.

| Strategy | Decides | Portable to a real Pi? | Paired scenario |
|---|---|---|---|
| `hold-5050` | share pinned at 0.50; `v_setpoint` from the scenario profile; no charging | **Yes** — reads only `t` and `v_profile` | `ems-drive-cycle` |
| `regen-harvest` | same, plus `charge_goal` **inside braking windows only**, so the Ag105 is fed through REGEN and `FC_CHARGE` never opens | **Yes** — same two keys | `charge-regen` |
| `soc-band` | deadband-P **share bias** on the SoC error, plus **opportunistic FC-path charging** in cruise | **No, as written** — it closes on `fb["soc"]`, which is plant truth (see the portability list under §3.3) | `ems-soc-band` |
| `dp-replay` | nothing — it **plays back a table** of `power_share_setpoint` / `charge_goal` computed **offline** by backward dynamic programming with full foreknowledge of the whole cycle | **No, and never** — a Pi has no future. This is a *benchmark*, not a controller | `ems-dp-replay` |
| `sdp-v3` **(the calibrated BENCHMARK, `frontier_eligible`)** | as `sdp-v2` below, but playing `sdp_policy_v3.json` (policy-block sha256 `0443febf…`), whose alpha is re-derived by **two-sided lever calibration**. The Ag105 charge action is then declined **ENDOGENOUSLY** — zero charge cells in all 101 x 25, `forbid_charge_all` FALSE — so this policy shifts share and never opens the charger. The consumer **refuses at load** any artifact that does not carry the calibrated-benchmark certificate (`alpha.mode == "lever"`, both `alpha.admission.in_window_*` true, `forbid_charge_all` false) | **No, as written** — same reason as `soc-band` | `ems-sdp`, `ems-ftp75-sdp` |
| `sdp-v2` **(DYNAMICS DEMONSTRATION, not `frontier_eligible`)** | looks `power_share_setpoint` / `charge_goal` up in a **state-indexed** policy — (SoC, demand bin) — baked offline by stochastic dynamic programming (`tools/sdp_ems_solver.py`, artifact `sdp_policy_v2.json`), recomputed every `decision_dt_s` (1 s) and held between decisions. ⚠️ Named `sdp-v2` since 2026-08-31: the CODE is unchanged, but it now loads the re-mapped `v2` artifact, and a strategy name claiming `v1` while playing `v2` would be a contract lie (§3.2.3a) | **No, as written** — same reason as `soc-band`: it closes on `fb["soc"]`, which is plant truth. *Causal*, though, unlike `dp-replay`: the lookup is on the present state, so it is defined on any profile | `ems-sdp-cross`, `ems-sdp-braking` (its charge cells are what those two exist to actuate) |
| `y-b30-v1`, `y-b30-v3`, `y-b00-v1`, `y-b00-v3` | **both** axes of the firmware's own `'Y'` combined profile (16 regions, 40 s — the table at `.ino:3162-3179`), at Vmax 1 or 3 m/s and share bound b = 0.30 or 0.00; no charging | **Yes** — read only `t` (and the scenario's `ems_run_exit_s`) | `ems-y-b30-v1` … `ems-y-b00-v3` |
| `mppt-harvest` | `regen-harvest` plus `charge_goal` on the **low-cruise plateaus** as well, so the charger is also fed through the **FC path** — where the Ag105's MPPT input-voltage threshold can bind | **Yes** — same two keys as `regen-harvest` | `mppt-tracking` |

The four `y-*` strategies are built by ONE factory, `make_ems_y(vmax, b)`, over ONE
copy of the firmware's table — the same discipline the firmware itself keeps for
`'Y'` and `'W'` (`.ino:7845-7850`). Two bands, two different experiments:
**b = 0.30** (with a +0.60 A preload) keeps the share inside
`[DROOP_R_MIN, DROOP_R_MAX]` and the loop closed, so the objective is share
*tracking*; **b = 0.00** (no preload) rails the share to 1.00 and 0.00 and
exercises the *cut-and-restore* topology instead. Do not read share-tracking
numbers off a `b00` run — at Vmax 1 that loop is open-loop feedforward.

### 3.2.1a The FTP-75 scenarios, and the `--with-ftp75` gate

Two scenarios drive the **EPA FTP-75** cycle at raw **t = 0..340 s inclusive**
(341 samples at 1 Hz) — the segment of
`references/Systemic_Scaling_of_Powertrain_Models_with_Youla_Driver_Control.pdf`
— scaled so its 56.7 mph peak lands on 3.0 m/s:

```
.venv_hil\Scripts\python.exe tools\hil_plant_sim.py --teensy-ip 192.168.1.50 --scenario ems-ftp75-5050 --dash
.venv_hil\Scripts\python.exe tools\hil_plant_sim.py --teensy-ip 192.168.1.50 --scenario ems-ftp75-socband --dash
```

Each runs **350 s**. `run_hil_suite.py` therefore renders both **SKIPPED** unless
you pass `--with-ftp75`:

```
.venv_hil\Scripts\python.exe tools\run_hil_suite.py --teensy-ip 192.168.1.50 --with-ftp75
```

That is a run-time gate (~11.7 min for the pair, on a campaign that is otherwise
~34 min), not a coverage judgement — nothing about the board or the link blocks
them.

The speed profile is **generated, never hand-edited**. `tools/gen_ftp75_profile.py`
reads the committed EPA file `references/drive_cycles/ftpcol.txt`, verifies its
sha256, slices and scales it, and writes `tools/ftp75_profile.py`. That file's
CRLF bytes are held in place by `references/drive_cycles/.gitattributes`
(`* -text`), so the sha256 gate survives a checkout on any platform; and
`hil_plant_sim.py` imports the generator to compare the two, so a stale or
hand-edited `ftp75_profile.py` is an **import error**, not a silent wrong
stimulus:

```
.venv_hil\Scripts\python.exe tools\gen_ftp75_profile.py --force
```

Two things to know before reading an `ems-ftp75-socband` trace:

* ⚠️ **The +0.65 A bus preload was REMOVED on 2026-09-01** (operator ruling;
  `aux_preload_a` → 0.0 on every drive-cycle scenario). It used to hold the
  source total above the firmware's 0.60 A closed-loop governor gate for the
  whole cycle. It no longer does: the idle source total is `I_AUX_A` = 0.15 A,
  so the share loop runs **open-loop hold** through every idle segment
  (governor walk: 9.71 % hold / 57.12 % feedforward / 33.17 % closed). That
  mode content is the point of the removal — read a share *amplitude* off the
  cycle peak, where the loop is closed, and not off an idle segment.
* Consequently `soc-band`'s **charging branch is now reachable** here (0.15 A
  against its 0.60 A admission threshold) and is asserted by
  `socband_ftp_charge_opened`. This scenario exercises both of the policy's
  branches for the first time; `ems-soc-band` remains the calibrated home of
  the charge-window assertion.
* ⚠️ **CAMPAIGN COMPARABILITY.** Campaigns up to and including
  `hil_report_20260901_151156` ran the FTP-75 legs at 0.65 A (0.45 A on the SDP
  leg). Their hydrogen and SoC totals are a DIFFERENT experiment and must never
  be quoted against a later run: 5050 0.0647 g / ΔSoC −0.02648; socband
  0.09159 / −0.01533; sdp 0.0622 / −0.01845; dp 0.09291 / −0.01478.
  `constants_hash` moved with the change, and so did the `ems-ftp75-dp` table's
  `profile_fingerprint` — `aux_preload_a` is a fingerprinted key, so a table
  solved against the old demand is refused at load rather than played.
  Every FTP-75 threshold is PROVISIONAL again, sized from the governor walk
  (`tools/ems_walk.py`) pending the first zero-preload campaign.
* `ems-ftp75-socband` **allows `OC_FC`**. At the policy's 0.75 share ceiling the
  cycle peak puts 1.21 A on the FC channel — 14 % under `LIMIT_I_FC_MAX` — so a
  drive-controller transient near the peak can spend the rest. A single-channel
  overload there is the designed outcome, not a defect.

### 3.2.1b The four wave-2 scenarios (2026-08-31)

Four scenarios were added after the FTP-75 pair. None needs a flag; together they
add about **4.5 minutes** to a campaign (45 + 130 + 14 + 47 s, plus four settle
pauses). A full default campaign now estimates at **~34 min** (45 min with
`--with-ftp75`); `run_hil_suite.py --list` prints the current figure.

```
.venv_hil\Scripts\python.exe tools\hil_plant_sim.py --teensy-ip 192.168.1.50 --scenario mppt-tracking --dash
.venv_hil\Scripts\python.exe tools\hil_plant_sim.py --teensy-ip 192.168.1.50 --scenario charge-to-full --soc0 0.990 --dash
.venv_hil\Scripts\python.exe tools\hil_plant_sim.py --teensy-ip 192.168.1.50 --scenario pi-silence --dash
.venv_hil\Scripts\python.exe tools\hil_plant_sim.py --teensy-ip 192.168.1.50 --scenario share-staircase --dash
```

**`mppt-tracking` — what a good run looks like on fw v24.**
⚠️ **The Ag105's MPPT is an input-voltage THRESHOLD, not a perturb-and-observe
tracker** (`AG105_Silvertel.pdf` p.10; the P&O wording elsewhere in this repo is
lore). Charging commences only above a threshold, settable 11–33 V by an **MPPTS
resistor** or I2C register `0x02`, and **defaulting to 18 V with MPPTS open**.

This scenario turns that threshold on in the plant model, which makes
`MPPT_DISABLE` causally load-bearing. **The threshold the model applies is the
one the BOARD reports** — observation-frame byte 15 carries the reg-`0x02` count
fw v24 believes it wrote, and the CSV column `mppt_thresh_cnt` logs it.

**⚠️ THE OBJECTIVE INVERTED AT fw v24.** Under fw v23 the module sat at 18 V, a
~15.95 V bus could never clear it, and the firmware and the module **hunted** —
138 `MPPT_DISABLE` toggles at a ~40.05 ms median period, campaign
`20260831_191509`. fw v24 writes reg `0x02` to (windowed-min `V_chg` − 3.0 V),
clamped in counts to **[15, 27] = 12.320–13.376 V**, i.e. under the bus. So:

* **Expected (good):** `mppt_thresh_cnt` non-blank and inside 15–27; `MPPT_DISABLE`
  rising **once per cruise-charge window** (3 rises, band 3–8); no GENSTAT 001
  Low Power; `MPPT_EN` **and** `PWR_TRACK` both set while charging; `I_charge`
  near the 1.0 A ceiling rather than half of it.
* **A hunt is now a FAILURE** — it means the manager did not run, could not write,
  or gave up (in which case `chargingControl()` holds MPPT inhibited for the
  session, so expect a HELD-LOW pin rather than a toggling one).
* **A blank `mppt_thresh_cnt` column means you are running against fw v21–v23**
  (16-byte frame, no byte 15). The suite fails that loudly instead of passing
  vacuously — check the flash, not the scenario.

**R1 (does the board fit an MPPTS resistor?) is no longer a contingency.** Table 7
encodes reg `0x02` 0–250 as *register* mode and ≥251 as the resistor, so a firmware
write overrides any fitted resistor. Checking the MPPTSEL header is still worth
doing for the record, but it no longer decides this scenario's meaning.

**`charge-to-full` — the suite passes `--soc0 0.990`; a hand run must too.**
The Ag105's Fully-Charged branch needs `soc >= 0.995`, and no campaign has ever
raised SoC by more than ~0.0009. Starting at 0.990 leaves ~90 s of charging at this
scenario's 1.0 A ceiling, so **Fully Charged is expected around t = 100** of the
130 s run. `run_hil_suite.py` supplies the override automatically; **a standalone
run at the default `--soc0 0.7` will never reach FULL** and every one of its signal
checks will fail for that reason alone. The run is at standstill throughout, so it
exercises no drive-channel behaviour at all.

**`pi-silence` — expect a `PI_TIMEOUT` fault; that is the pass condition.**
The emulated Pi stops commanding at t = 8.0 while the injection stream keeps
running, which is the only stimulus that reaches the firmware's Pi watchdog without
also tripping the HIL link's own staleness path. The board **should** latch
`FAULT_PI_TIMEOUT` about 500 ms later and stay latched to the end of the run; the
motor command should fall from its ~3.5 A cruise hold to zero. Two things to know:

* The 0x0010 bit is **shared** with `FAULT_HIL_LINK`. The suite settles which one
  fired with the `child_tx_healthy` check. **From fw v25 that is a direct read**:
  observation-frame byte 16 carries the latched first cause, so `ERR_PI_TIMEOUT`
  (0x05) and `ERR_HIL_STALE` (0x10) are distinct on the wire. On a fw v21–v24
  board the check falls back to the older inference by elimination — this
  process's own injection stream was continuous, so a HIL-link explanation is
  implausible — and the check's detail line names which of the two decided.
* A **mid-run warm reset** here invalidates the run: it clears `pi_ever_connected`
  and disarms the very watchdog under test. The suite marks such a run
  INCONCLUSIVE.

**`share-staircase` — the latency numbers are the point.**
A motor-free two-phase sweep. Phase A (t = 6–28, bus load ~1.2 A) walks the share
setpoint 0.80 → 0.20 in 0.10 steps, deliberately straddling the governor's clip
rails at **[0.25, 0.75]**. The load then drops to ~0.55 A and Phase B (t = 33–44)
commands 0.95 / 0.50 / 0.05 / 0.50, cutting and then **restoring** `BT_BUS` and
`FC_BUS`. The load has to drop between the phases: at 1.2 A the cut's own
0.5 A/channel handoff guard would refuse the latch.

The report prints **four measured cut/restore latencies**. Those values are the
deliverable; the 40 ms bound beside them is a regression tripwire. ⚠️ If a run
exceeds it, that is the finding — **do not raise the bound to make the run green.**
The latency is dominated by **command-arrival phase** (the emulated Pi's 50 Hz
cadence), not by a firmware tick: `POWER_BAL_PERIOD_US` and `SHARE_CTRL_TS_US` are
both 1000 µs.

### 3.2.1c The compressed FTP-75 legs, `--with-ftp75c` and `--drag` (2026-09-02)

Five scenarios drive a **time-compressed FTP-75 cycle on a road-load-compensated
plant**: `ems-ftp75c-5050`, `-socband`, `-sdp`, `-dp` and `-mpc`. They are the
first drive-cycle legs on this rig that regenerate at all. Each runs **180 s**:

```
.venv_hil\Scripts\python.exe tools\hil_plant_sim.py --teensy-ip 192.168.1.50 --scenario ems-ftp75c-5050 --dash
```

`run_hil_suite.py` renders all five **SKIPPED** unless you pass `--with-ftp75c`:

```
.venv_hil\Scripts\python.exe tools\run_hil_suite.py --teensy-ip 192.168.1.50 --with-ftp75c
```

The set costs **925 s, 15.4 min** on bench (five legs at 180 s plus five 5 s
settle pauses). `run_hil_suite.py --list` prints that figure alongside the other
opt-in sets, with an extra line recording that this is the only set which changes
the **plant**. That is the second half of the gate: `--with-ftp75` is a run-time
gate alone, while `--with-ftp75c` also selects a plant configuration that cannot
be replicated on this bench.

The speed profile is **generated, never hand-edited**, exactly as `ftp75` is.
`tools/gen_ftp75_profile.py` gained a `--time-factor` flag with a registry of the
two registered factors, and `hil_plant_sim.py` imports the generator to compare
the two tables, so a stale or hand-edited `ftp75c_profile.py` is an import error
rather than a silent wrong stimulus:

```
.venv_hil\Scripts\python.exe tools\gen_ftp75_profile.py --time-factor 0.5 --force
```

Time compression halves the time axis and leaves the velocity axis untouched, so
the table keeps the same 234 points and the same 3.0 m/s peak (now at t = 125 s)
while **every acceleration doubles**, to ±0.3492 m/s².

**`--drag` selects the road load, and `rig` is the default.**

```
--drag rig                 the MEASURED bench road load, F_c + b_eff*v.  DEFAULT.
--drag scaled-air          the study vehicle's scaled air drag, k_air 0.0598, F_c 0.
--drag scaled-air-matched  k_air / 4.4866, which reproduces the FULL-SCALE share.
```

The five `ems-ftp75c-*` scenarios declare `"drag": "scaled-air"`, so the operator
does not have to remember the flag; an explicit `--drag` overrides the scenario
key, and `config.drag_from` in the sidecar records which of the two decided. The
sidecar also carries `config.drag`, the resolved `config.drag_k_air`,
`config.regen_manager`, `config.regen_windows`, `config.regen_duty_s` and
`config.regen_early_releases`, plus
the two era keys `scenario.drag` and `scenario.eta_regen`. Read them before
comparing any two runs: an **absent** era key means the pre-compensation, pre-regen
model, and a compensated run is a different vehicle from a rig-drag one, because the
tractive demand differs by roughly 4.5×.

Passing `--drag rig` to one of these scenarios is a legitimate **zero-regen
control run**: the regen manager re-derives its windows from the resolved mode
and gets an empty list, and both era keys record `None`. It is not, however, the
same experiment, and `run_hil_suite.py` has no `--drag` flag of its own, so a
control run is driven from `hil_plant_sim.py` directly.

Three things to know before reading a `ftp75c` trace:

* ⚠️ **Do not read SoC direction on these legs.** The regen credit is 1.1729 C,
  about 1.4 % of the cycle drain, a SoC gain near +5.5e-5 against a −0.0054
  excursion. Read the harvest off `I_charge`, the `chopper_clamp` event's
  `energy_j` and the plant's `regen_energy_j` counter.
* ⚠️ **The bands on this family were first-campaign predictions.** Campaign
  `hil_report_20260902_220604` ran all five legs and the plant behaved: 6 regen
  windows carrying 19.21–19.25 s against a modelled 6 / 19.6 s, chopper energy
  5.4558–5.4911 J against a 2.5 J floor. `ETA_REGEN` = 0.80 and
  `VESC_REGEN_I_MAX_A` = 1.5 A remain `TODO(verify)`, and the **realizable regen
  fraction measured 0.63**, not the design's modelled 0.707 — the cause is the
  window-length distribution against the Ag105's ~0.9 s dead time, not either
  constant. Those figures are **pre-D-4**: that campaign held `charge_goal` to
  each window's wall-clock end, so the next campaign runs a different commanded
  stimulus (about 0.35 s less commanded regen) and its duty and pack charge must
  be re-pinned, not differenced against these.
* ⚠️ **A regen window now ENDS on a condition, not on the clock** (2026-09-03).
  `RegenManager` releases `charge_goal` when the commanded motor current reaches
  −0.1 A, the firmware's own `regenActive` exit, or at the window's end,
  whichever comes first. The window OPENS at −0.2 A, so the two levels form a
  hysteresis band: releasing at the opening level is a zero-hysteresis comparator
  and closed two windows mid-braking on the measured trace (review finding H1;
  `docs/HIL_PLANT.md` §3.4). On campaign `hil_report_20260902_220604`'s trace the
  released count is **2 of 6**, both at genuine standstills.
  `config.regen_early_releases` counts the windows that
  ended on the current, and `config.regen_duty_s` remains the WALL-CLOCK duty,
  i.e. an UPPER BOUND on the commanded one whenever that count is non-zero. The
  release reads the observation frame's commanded motor current, which an offline
  `ems_walk` does not have, so a WALK still models the longer window; a
  walk-versus-run comparison of regen duty on these legs is expected to differ in
  that direction.
* ⚠️ `ems-ftp75c-socband` runs **per-scenario charge thresholds**, 0.18074 A enter
  and 0.33107 A exit, because the shipped 0.60 A entry threshold sits above this
  cycle's entire source total. If that leg reads as permanently charging, the
  override did not arrive and the frontier's ratios mean nothing.

`ems-ftp75c-dp` is **hifi only**. Every leg of this family runs 180 s, which is
above `MATCHED_DP_LONG_DURATION_S` = 100.0 s, so a matched-DP baseline for any of
them needs `--matched-dp-allow-long` or a prefilled `dp_db` record; prefilling
moves the solve off the campaign critical path. **All five are prefilled**, each
at its own governor-walk terminal SoC, so a campaign that lands near those
targets hits the store and costs no compute. The five solves took 1367 s
(22.8 min) together; `docs/HIL_SCENARIOS.md` §6.2 carries the table. Re-run them
with, per leg,

```
C:/Users/ricky/miniforge3/python.exe tools/dp_results_db.py prefill \
    --scenario ems-ftp75c-5050 --soc0 0.7 --accounting physical \
    --eta-chg 0.88 --loss-map plant "--dsoc-span=-0.001914:-0.001914:1"
```

`--drag` and `--eta-regen` default to the scenario's own road load and the era
derived from it, so neither has to be passed for these five.
⚠️ `ems-ftp75c-sdp`'s record is stored with `converged: false` (residual
2.49e-06 against a 2.0e-06 tolerance), and its matched-DP figure is **not a
bound** on that leg at all: `sdp-v6` (`sdp-v4` before 2026-09-03; the two
command the same thing on every row this leg reaches) commands a constant
0.8500, outside the
DP's own control grid `[0.25, 0.75]`. Read `docs/HIL_SCENARIOS.md` §6.2 before
quoting it.

#### ⚠️ Bench replication of the compensated plant

Road-load compensation **cannot be replicated on this bench with the single motor
now fitted**, and the reason is structural rather than one of tuning. The
compensation would have to be a friction feedforward cancelling
`F_COULOMB + B_EFF*v`, up to 3.60 N at 3.0 m/s, and the only actuator able to
apply it is the traction motor itself. A feedforward of that form keeps the net
motor force **positive** through a stop, because the motor is supplying the
friction the compensation cancels. No instant exists at which the current
reverses, so there is no physical regeneration to measure, and a bench run would
exercise the firmware regen branch only if the command were falsified. That is
not a measurement.

Replication needs a **second motor acting as a road-load brake on the flywheel**,
sized at approximately 3.1 N rim force, 0.24 N·m, 400 rpm, under 10 W and
four-quadrant, under torque control rather than speed control, with coast-down
calibration of `F_COULOMB` and `B_EFF`, a speed-floor interlock below about
0.2 m/s and a setpoint-zero interlock at standstill. None of that is in scope for
the HIL work; the sizing and the interlocks are recorded in
`docs/modeling/ftp75c_regen_cycle_design_20260902.md` §7 and summarised in
`docs/HIL_PLANT.md` §3.5.

**On the bench, `--drag rig` remains the only physically honest configuration,
and it regenerates nothing on any registered cycle.** A `ftp75c` harvest figure
is a HIL result about the model and the firmware's regen path, and it must never
be quoted as a bench measurement.

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

### 3.2.3a `sdp-v3` / `sdp-v2` — the causal stochastic-DP policy

```
.venv_hil\Scripts\python.exe tools\hil_plant_sim.py --teensy-ip 192.168.1.50 --scenario ems-sdp --dash
```

Same cycle and same drain load as `ems-soc-band` and `ems-dp-replay` — all three
share **one** `ems_v_profile` object — so the three are directly comparable.
`--ems` may be omitted; the scenario declares `sdp-v3`.

> **TWO ARTIFACTS, TWO ROLES since 2026-09-01 (the charge-economics ruling).**
> The strategy CODE is one class with two registered instances; what differs is
> the baked artifact and the role recorded in
> `hil_plant_sim.EMS_STRATEGY_META`.
>
> * **`sdp-v3` — the CALIBRATED BENCHMARK** (`sdp_policy_v3.json`, policy-block
>   sha256 `0443febf…`, `frontier_eligible: True`). Bound to `ems-sdp` and
>   `ems-ftp75-sdp`. Campaign `20260901_000816` measured the `v2` leg **off the
>   EMS frontier** — +12.78 % over the DP bound and 1.54 % *worse* than the
>   `soc-band` heuristic — and the cause was its charge action: `v2`'s alpha
>   prices SoC at a shadow price of 5.139 g/SoC, i.e. an admission threshold of
>   **0.1946 SoC/g**, while the Ag105's measured charge lever is **0.2364** and
>   the share lever is **0.409–0.415**. Every lever priced inside that gap is
>   taken by the solver and scored as a loss. `v3` re-derives alpha by two-sided
>   lever calibration (`alpha = (1−gamma)/sqrt(L_share·L_chg) = 0.1629624`), and
>   the charge action is then rejected **ENDOGENOUSLY**: zero charge cells in
>   all 101 × 25, with `actions.forbid_charge_all` **FALSE** — nothing was
>   masked, the optimizer declined. It self-revises: charging returns if the
>   charger's measured lever ever exceeds `(1−gamma)/alpha = 0.30682 SoC/g`.
>   The consumer **refuses at load** any artifact bound here that does not carry
>   that certificate quadruple.
> * **`sdp-v2` — the DYNAMICS DEMONSTRATION** (`sdp_policy_v2.json`, policy-block
>   sha256 `740c802e…`, `frontier_eligible: False`), **byte-frozen**. Bound to
>   `ems-sdp-cross` and `ems-sdp-braking`, which exist to put the policy's CHARGE
>   threshold on the wire and therefore need a policy that HAS charge cells. A
>   run of this strategy measures a mechanism; its `h2_cum_g` / `delta_soc` pair
>   is **not** an energy-management result, the EMS frontier check excludes it by
>   construction, and REPORT.md / `ANALYSIS.md` carry a demonstration banner.
>
> **The two share maps are identical outside SoC rows 1–2** (30 cells of 2525),
> which is why the v2-derived offline walks for `ems-sdp` and `ems-ftp75-sdp`
> transfer to the v3 legs verbatim — neither trajectory comes near those rows.

> **Renamed 2026-08-31, `sdp-v1` → `sdp-v2`.** The strategy CODE did not change;
> the ARTIFACT it loads did (see the demand-map box below). The name moved with
> it because a strategy that says `v1` while playing `v2` is a contract lie, and
> `ems_strategy` in `results.json` / `REPORT.md` is the most visible thing
> separating a pre-re-map campaign from a post-re-map one. `--ems sdp-v1` is no
> longer a valid strategy name — there is deliberately no alias.

Where `dp-replay` plays a table indexed by **time**, this one plays a policy
indexed by **state**: `(SoC, demand bin)`. The offline solve is not causal, but
the resulting policy is — at run time it reads only the present state, so it is
defined on any profile. The lookup runs once per `decision_dt_s` (1 s, from the
artifact) and the two energy fields are held between decisions; `v_setpoint` and
`mode_cmd` still update every 20 ms.

The artifact is `tools/sdp_policies/sdp_policy_v3.json` for `sdp-v3` and
`sdp_policy_v2.json` for `sdp-v2`, both produced by `tools/sdp_ems_solver.py`. The strategy **refuses at startup** if it is missing
or malformed — including a non-finite or out-of-range action, which would
otherwise reach the wire silently — rather than falling back to a 0.5 split.

**Which policy produced a run's numbers** is recorded per run, because nothing
else in the CSV can say: a regenerated artifact changes every command while
leaving the scenario, the schema and `constants_hash` identical. Two digests
are printed at bind time and written to the CSV's meta sidecar under
`config.sdp_policy`:

* **policy-block sha256** — `sha256(json.dumps(doc["policy"], sort_keys=True))`:
  `0443febf…` for `sdp-v3` (the calibrated benchmark), `740c802e…` for `sdp-v2`
  (the frozen demonstration), `dbe42d1b…` for the retired `v1`. All three files
  declare the same `schema`, so this digest and the artifact's `normalization`
  block are the only things that tell one trace from another. This is the
  **decision law**, and it is stable across a
  `--force` regeneration that did not change it. Quote this one.
* **file sha256** — byte identity of the file. It moves on *every* regeneration,
  since the artifact carries `generated_utc`, so it belongs in a run record and
  never in a comment.

Five things to know before reading a trace, all of them consequences of the
artifact and of one design decision, not of the board:

* **It regulates around the SoC this run STARTED at, not the artifact's 0.60.**
  The policy's target is the study's 0.60 while these scenarios start at
  `--soc0 0.7`, so the strategy captures `soc0` on its first call and looks up at
  `target + (soc − soc0)`. Without that shift the run would spend its whole
  length deliberately walking the pack down 0.10 SoC, and no hydrogen comparison
  against `soc-band` would mean anything. The mapping is a pure translation, so
  the policy's shape survives — but absolute-SoC meaning does not.
* **The demand map was re-mapped on 2026-08-31, and that is what `v2` is.**
  `sdp_policy_v1.json` was solved against the TPM sidecar's *ideal-scaling*
  demand span, −1.125 … +1.640 W. This bench measures `P_dem = V_bus·(I_fc +
  I_batt)` at **0 … 22.887 W** — an order of magnitude above it — so campaign
  `hil_report_20260831_191509` clamped **~98 % of decisions into the top bin**:
  the demand axis carried no information and the strategy emitted one constant
  share for a whole run. The plumbing was validated; the policy was not
  exercised. The TPM is unitless by contract (its bins partition a quantile
  axis), so the fix was a **re-map plus a re-solve of the same matrix**:
  `sdp_policy_v2.json` uses a **[0.0, 25.0] W** consumer demand map — the
  measured maximum plus ~9 % headroom, derived in `tools/sdp_ems_solver.py`'s
  decision **D11**. Offline against the same recorded trace: **61 decisions,
  zero clamps, 13 distinct demand bins.**
  The clamp is not removed, only moved out to the edge of the measured
  envelope, and the exit summary still reports it:
  `[hil] sdp-v2: N decisions, demand bin clamped HIGH on … (…%)`. **What the
  counter MEANS has changed:** under `v1` a ~100 % high-clamp rate was the
  expected reading; under `v2` any appreciable clamp rate means this rig has
  moved outside the map the shipped policy was solved for, and the answer is a
  re-solve at a wider map (`--demand-map MIN MAX`), not a wider tolerance.
  `--demand-map-sidecar` reproduces the `v1` mapping if you need to.
* **The table asks 0.95 or 1.00, and BOTH are emitted as 0.8500 — so read
  `cmd_share_sp_raw`, not `cmd_share_sp`.** The share law is bang-bang by
  construction: the stage cost is piecewise-linear in the share, so its minimum
  over [0, 1] sits at a vertex, and the whole table takes only
  {0.00, 0.90, 0.95, 1.00}. Above the (relative) target the action is 0.00; at
  or below it 1.00, except in the top three demand bins where the kink moves
  inside the ladder (0.95 in bins 22–23, 0.90 in bin 24). The offline walk of
  this cycle gets **0.95 over the drain plateau (t = 13…38, bin 22) and 1.00
  elsewhere** — the demand axis genuinely moving the action — but every one of
  those values is above `SOC_BAND_SHARE_MAX`, so the *emitted* command is a
  constant 0.8500 either way. ⚠️ **`cmd_share_sp` therefore cannot tell a `v1`
  run from a `v2` one, or a live demand axis from a saturated one.** The
  pre-clamp `cmd_share_sp_raw` CSV column (added in the same round, for exactly
  this) is the one that shows the table's actual request.
  The grid-floor node 0.550 reads 0.00 — a solver-side clamp-tie degeneracy
  (its D3/D8), not a second switching point, and unreachable here since it needs
  SoC to fall 0.05 below the captured `soc0` against this run's ~0.0017.
  ⚠️ Note the SoC axis cannot be explored by changing `--soc0`: the mapping is
  soc0-**relative**, so `soc_rel` starts at the target whatever `soc0` is. Only
  a longer or heavier-drain run reaches the floor, and only net charging walks
  it the other way.
* **⚠️ NEW UNDER `v2`: this cycle now opens a charge window.** Under the 25 W
  map the solver's own FC-current budget forbids charging above bin 5 and its
  dwell rule above bin 11, so `charge_goal` = 1 exactly in bins 0–5
  (`P_dem` < 6.0 W) at any SoC node below the relative target. The walk lands it
  on **t = 41…58** — the same post-drain 1.0 m/s cruise `soc-band` charges in,
  reached by a completely different rule. Current budget is `soc-band`'s own,
  validated at this operating point: with `FC_CHARGE_ENABLE` open,
  `assertFcChargeEnable()` drops BT off the bus and FC alone carries
  5.593 W / 15.95 V = 0.351 A plus the 0.800 A ceiling = **1.151 A, 18 % under
  `LIMIT_I_FC_MAX`**.
  **Expect ~1 Hz chatter of `FC_CHARGE_ENABLE`** (derived, not yet measured):
  opening the path adds ~0.8 A to `I_fc`, so the measured `P_dem` jumps
  ~5.6 → ~18.3 W = bin 18, which is charge-forbidden, and the next 1 s decision
  withdraws the intent. The policy is memoryless in the demand bin and has no
  hysteresis — `soc-band` avoids exactly this with its dual `i_tot` gate — so
  ~8 open/close cycles are expected over the window, each costing a BT_BUS cut
  and restore. Neither state exceeds a current limit, and `ems-y-b00` exercises
  the same cut and restore fault-free at a heavier load. **Do not expect
  `I_charge` to reach `soc-band`'s 0.5 A**: the Ag105 may never reach
  `chargerReady` inside a 1 s open window, which is why the suite check on this
  scenario asserts the *switch*, not the current. The first `v2` campaign is
  what turns this prediction into a measurement.
* The emitted share is clipped to
  `[SOC_BAND_SHARE_MIN, SOC_BAND_SHARE_MAX] = [0.15, 0.85]`, the **same
  hardware-envelope clamp `soc-band` applies**: a rail sits outside
  `[DROOP_R_MIN, DROOP_R_MAX]`, where the setpoint cut opens the minority
  channel's bus switch and leaves the survivor carrying the whole bus — here
  ~1.45 A of drain against `LIMIT_I_FC_MAX` 1.4 A, i.e. an `OC_FC` latch that
  would truncate the run. **The clamp is actuation-side only**: the baked table
  is untouched, and the raw value the policy asked for is counted and printed
  (`SHARE clamped to the hardware envelope … on N decision(s)` in the exit
  summary), so "the policy wants the rail" stays a visible finding.

  What you should see instead is a **sustained FC-heavy but legal split**:
  0.85 commanded, clipped further by the firmware's own governor to
  `1 − I_min/I_tot` = 0.795 at the drain peak, so `I_fc` ≈ 1.16 A (17 % under
  the limit) with the battery minority held at exactly
  `SHARE_MINORITY_I_MIN_A` 0.30 A. The run is expected **fault-free over its
  full 61 s**.

### 3.2.3b `sdp_soc_ref_offset` — choosing which branch the policy starts on

```
.venv_hil\Scripts\python.exe tools\hil_plant_sim.py --teensy-ip 192.168.1.50 --scenario ems-sdp-cross --dash
.venv_hil\Scripts\python.exe tools\hil_plant_sim.py --teensy-ip 192.168.1.50 --scenario ems-sdp-braking --dash
.venv_hil\Scripts\python.exe tools\hil_plant_sim.py --teensy-ip 192.168.1.50 --scenario ems-ftp75-sdp --dash
```

**The problem this solves.** The SDP table is **bang-bang in the share** about
its target SoC node — the stage cost is piecewise-linear in the share, so its
minimum is always at a vertex. `sdp-v2`'s SoC0-relative mapping puts a run's
first decision *exactly on that node*, and every `ems-sdp` run to date could
only discharge from there, so the policy sat on its fuel-cell branch and the
wire carried **one constant clamped 0.8500 for the whole run**. The plumbing was
validated; the switching law never was.

**The key.** A scenario may declare `sdp_soc_ref_offset` (a float, **SDP-strategy
scenarios only — `sdp-v2` or `sdp-v3`**; it is refused at import on any other).
Both artifacts share the same bang-bang share law on every SoC row the shipped
scenarios reach, so the offset means the same thing under either. The strategy
captures `soc_ref = soc0 − delta` on its first decision, so the run *starts*
`delta` above the target node:

| offset | first lookup lands | table action | emitted `cmd_share_sp` | charging |
|---|---|---|---|---|
| `0.0` (default, `ems-sdp`) | ON the target node | 1.00 | 0.85 | no |
| **positive** (`ems-sdp-cross` +0.0025, `ems-ftp75-sdp` +0.013) | ABOVE it | 0.00 | **0.15** | no |
| **negative** (`ems-sdp-braking` −0.005) | BELOW it | 1.00 | 0.85 | yes, in bins 0–5 |

Nothing else changes: the mapping stays a pure translation of the SoC axis, and
the artifact is untouched. The offset is printed at startup, repeated in the
exit summary (`soc_ref … (offset +0.0130)`) and recorded in the CSV's meta
sidecar under `config.sdp_policy.soc_ref_offset` — which is the only trace of it
anywhere, so **a run bound with the wrong offset looks exactly like a correct
run of a different scenario**. Out-of-range values are **refused at startup**,
not clamped: past `min(target − grid_min, grid_max − target)` (0.05 for the
shipped artifact) the first decision would be clamped onto a grid edge and the
run would not start at the requested offset at all.

**What the three scenarios do with it.**

* `ems-ftp75-sdp` — starts above the node on the 340 s FTP-75 cycle, so the
  wire carries 0.15 for ~200 s and then steps **once** to 0.85 as the drain
  crosses the boundary. ⚠️ Its preload was **0.45 A** (against the other FTP-75
  scenarios' 0.65 A) because the fuel-cell branch's governed peak
  (`I_tot − 0.300 A`) would otherwise have sat 3.2 % under `LIMIT_I_FC_MAX` at
  the cycle peak, and an `OC_FC` latch would have truncated the run at exactly
  its post-flip half. **Both preloads are 0.0 A since 2026-09-01**, which makes
  that peak 0.7046 A (50 % under the limit) and makes the three legs one
  experiment — so the drive-cycle EMS frontier can evaluate. The flip moves
  LATE with the load: expect it near **t = 272–276 s**, not ~200 s. Opt-in with
  `--with-ftp75`, like its two siblings.
* `ems-sdp-cross` — the same downward crossing at a low-demand operating point,
  followed by the **charge threshold's** own minimum-dwell limit cycle (three
  ~8 s windows, ~50–57 s apart). Expect one ~1 s admit-then-drop inside the
  deceleration: the demand enters the admissible bin before the ramp ends and
  `charge_hold_status()`'s cruise guard withdraws the intent on the next
  decision. That is the guard working, and the only live exercise it has had.
* `ems-sdp-braking` — starts *below* the node, so the share command is a
  constant 0.85 all run **by design** and every `FC_CHARGE` transition is
  attributable to the demand axis: charging on each low-speed plateau, closed on
  each 2.2 m/s cruise. ⚠️ **The SoC rise is fuel-cell-fed through `FC_CHARGE`,
  not regen harvest** — this policy never opens the REGEN path. (The "the plant
  floors regen power at zero" reason this line used to give was SUPERSEDED
  2026-09-01 by WP-C; see `docs/HIL_PLANT.md` §3.4.)

> **An UPWARD share crossing is not reachable on this rig, and no scenario
> pretends otherwise.** Raising SoC through the 1e-3-wide dead band around the
> target node inside one `SDP_CHG_MIN_DWELL_S` latch needs a charge ceiling
> above 2.25 A; on the single-source FC charge path that is
> `I_aux 0.15 + 2.25 = 2.4 A` against `LIMIT_I_FC_MAX` 1.4 A — an immediate
> `OC_FC`. The share axis crosses **once, downward**.

> ✔ **All three are CALIBRATED as of campaign `20260901_024231`**, the first
> campaign to run them. Every threshold was re-derived against that campaign's
> measured trace and the `provisional_note` was deleted from all three (the
> `ems-sdp` and `scp-inrush` precedent); each moved bound carries its measured
> value and the campaign id in place. How the walks did:
>
> * `ems-ftp75-sdp` — flip 195.9 walked vs **198.537 measured**, +1.35 %.
> * `ems-sdp-braking` — DEMAND-driven windows land on the profile's own
>   instants: 50.1 s walked vs **52.479 s measured**, +4.7 %, four windows of
>   four, zero cruise ticks, and the walk's five early drops to the instant.
> * `ems-sdp-cross` — the one failure. The flip was fine (-3.5 %) but the CHARGE
>   limit cycle's period was walked at ~52 s against a measured **16.13 s**,
>   wrong by **5.7×**, because the walk assumed the share loop was closed at an
>   operating point where the firmware holds open-loop (§3.3, "Share authority
>   disappears below 0.55 A").
>
> **The structural lesson:** the check that failed asserted the ABSENCE of a
> window at a *modelled instant*. Phase-locked absence assertions fail correct
> boards whenever the walk's period is wrong. Prefer the phase-free kinds —
> `max_continuous_ticks` and `edge_count_between` — which bound the same
> property without claiming to know when the transitions happen.

### 3.2.3c The MPC strategies — `mpc-det` and `mpc-sto`

Two strategies added 2026-09-02 run a governor-aware receding-horizon plan over
the pack state of charge: 20 stages at 1 Hz, a prediction model that carries the
firmware's own share governor, and a control that is exactly the two energy
fields of the 22-byte command packet. The full design, its adjudication and its
evaluation plan are `docs/modeling/mpc_design_20260901.md` and
`docs/modeling/mpc_design_20260901/adjudication.md`; the four scenarios that
drive them are `ems-mpc`, `ems-mpc-sto`, `ems-mpc-cross` and `ems-ftp75-mpc`
(§6.1 of `docs/HIL_SCENARIOS.md`). Three points matter at the console.

1. **`mpc-det` reads the scenario's speed profile as PREVIEW.** No Raspberry Pi
   has that, so a result from it must never be reported as causal. `mpc-sto`
   replaces the preview with the demand transition matrix's conditional mean and
   is causal, but no stimulus in this suite is a draw from that matrix, so it is
   registered `frontier_eligible: False`.
2. **An MPC run is not bit-reproducible.** The planner's search is wall-clock
   bounded, so a loaded host explores fewer candidates. Never put an MPC run in
   a repeatability ledger. Each registered leg declares
   `mpc_max_candidates` = 343 — the full enumeration at the shipped ladder, so
   the cap removes the clock from the candidate count without removing a
   candidate — and `--mpc-max-candidates N` overrides it. The roll-table
   slicing and the board itself remain non-deterministic.
3. **`--mpc-horizon`, `--mpc-share-band`, `--mpc-share-levels`,
   `--mpc-budget-ms`, `--mpc-roll-budget-ms`, `--mpc-terminal-price`,
   `--mpc-h2-map` and `--mpc-single-source`** override the controller. Every one
   defaults to the shipped design, so a scenario's `ems` key alone reproduces
   it, and every resolved value lands in the sidecar's `config.mpc` block
   whether it came from a flag or from the default.
4. **SINGLE-SOURCE (0/1) COMMANDS (2026-09-03).** `--mpc-single-source`, and the
   `mpc_single_source` scenario key that `ems-mpc-single` carries, let the
   planner command a share of exactly **0.0** or **1.0** — one boost off the
   bus through `updateShareSetpointCutoff()`, the other carrying the whole load.
   Admissibility is decided per decision by rolling the real `GovernorModel`
   forward from the committed state and evaluating the firmware's 0.5 A
   share-cut load guard on that path (operator ruling; design record section
   2026-09-03). **Read the `single-source 0/1 candidates ARMED` fragment of the
   run's summary line first** — offered / admitted / committed plus a
   refusal-reason census. A run that admitted nothing is a two-source run
   wearing the leg's name, and every other number on it is a two-source number.
   ⚠️ The gain is on the SoC lever, not on a loss: the offline walks move
   equivalent hydrogen by 0.01–0.43 % while the hydrogen headline moves up to
   49 %. Quote the pair, never the hydrogen alone. The feature is OFF on the
   four other MPC legs, so their records stay comparable.

⚠️ Gate 1 of the design's offline evaluation FAILS as shipped: the prediction
surrogate's delivered-share error on the `ems-soc-band` stimulus is mean
0.0097 / max 0.25000 against a 5e-03 acceptance, worst on `open_feedforward`
stages. The strategy ships with that recorded; the first campaign is the
calibration reading for `mpc_share_pred_err`, whose suite band is 0.30.

Watch three CSV columns, blank on every non-MPC run: `mpc_solve_ms`,
`mpc_share_pred_err` and `mpc_budget_hit`. The last is the one to read first — a
run whose budget expires often is commanded by a shifted incumbent rather than
by a fresh plan. That command is still feasible and was validated one second
earlier, so an expiry is a warning about search depth and not about the command.

### 3.2.4 Comparing EMS strategies

Run `ems-soc-band` (causal heuristic), `ems-sdp` (causal, optimal by
construction) and `ems-dp-replay` (non-causal offline optimum) — the suite runs
all three, on the **same profile, the same drain load and the same object** for
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

**`ems-sdp` is the third leg, and it does NOT come pre-matched.** The generator
bisects only the DP's terminal SoC against `soc-band`'s; the SDP policy's charge
sustenance is whatever the lookup delivers, which is part of what the run
measures. All three now run the **full 61 s** on the identical stimulus, so the
three `h2_cum_g` totals are directly comparable *as totals* — but the pair rule
above binds hardest on this leg: the SDP policy holds a **0.85 FC-heavy split**
for the whole run (§3.2.3a) and so is expected to spend visibly less pack charge
than the other two, which is precisely the trade a hydrogen number alone would
hide. Read its `delta_soc` first.

⚠️ **Under the `v2` artifact this leg also charges** (§3.2.3a), which moves both
axes at once: the charger's draw is billed to the fuel cell, so `h2_cum_g` goes
**up**, while the coulombs returned to the pack make `delta_soc` **less
negative**. Neither move is a ranking on its own. ⚠️ **Do not compare a `v2`
`ems-sdp` total against the `v1` numbers from campaign
`hil_report_20260831_191509`** (0.0125424 g / −0.00166 SoC): those were produced
by a different decision law. The `ems-soc-band` and `ems-dp-replay` legs are
unaffected by the re-map and remain comparable across the boundary.

**Two more caveats before quoting a comparison.** The DP's advantage is computed
in a *reduced* model (no share loop, no Ag105 settle/ramp, a 0.1 s stage, the
`Gfc` **DC gain** rather than its 0.22 s dynamics), so it is an estimate of the
gap, not a measurement of it. And the DP is open loop by construction: it cannot
react to the board or the plant doing anything the generator did not predict.

### 3.2.5 The offline EMS toolchain (no board required)

Five tools reason about EMS strategies without the board (added 2026-09-01e/f):

- `tools/governor_model.py` (stdlib) — a line-for-line port of the firmware's share-delivery
  governor (setpoint latch, 0.60/0.55 A closed-loop hysteresis, open-loop HOLD/feedforward, the
  minority clip, slew modes, both r-based cuts with the fw v25 load guard and survivor blanking).
  `replay_governor()` scores it against a campaign CSV's MDAC codes (runs with no ratio motion are
  reported UNSCORED). ems-sdp-braking is outside its fidelity claim.
- `tools/ems_walk.py` (miniforge) — `walk(strategy, scenario, governor=True)` drives any registered
  strategy through the DP demand/pack/H2 model with the governor at 1 kHz; with `governor=False` it
  reproduces `gen_dp_ems_table.heuristic_walk()` exactly. It is the tool the standing rule "offline
  walks must model the sub-0.55 A open-loop HOLD **and** the FEEDFORWARD SLEW" requires
  (restated 2026-09-02: open loop is two submodes, and the feedforward one writes the MDACs
  through the slew limiter — see `docs/HIL_PLANT.md` §4.4); every FTP-75 expectation band is derived
  with it. Its `trace=True` output can be synthesized into a HIL-schema CSV for the report figures.
- `tools/dp_results_db.py` + `tools/dp_db/` — the ΔSoC-matched DP results database consumed by
  `hil_report_analysis.py --matched-dp` (see the subsection under §5).
- `tools/sdp_alpha_sweep.py` — the SDP α-sweep (`grid` / `solve` / `refine` / `evaluate` / `plots`);
  artifacts under `tools/sdp_policies/sweep_20260901/`, results and walk-synthesized plots under
  `docs/modeling/sdp_alpha_sweep_20260901/` (every plot's title says OFFLINE GOVERNOR WALK — not a
  board run; the files carry a `walk_` prefix so no campaign glob ingests them).
- `tools/benchlog_analysis/asymmetry_fit.py` (`.venv_benchlog`) — the converter-asymmetry fit from the
  SD-card logs behind the plant's default-on `--asymmetry measured` (docs/modeling/
  converter_asymmetry_20260901.md).

Python interpreters: the simulator and suite are stdlib-only (`.venv_hil`); everything numpy-side
runs under miniforge (`C:/Users/ricky/miniforge3/python.exe`). Test invocations: `.venv_hil\Scripts\
python.exe -m pytest tools/ --ignore=tools/test_figures.py` and the miniforge run over the numpy
suites (see CLAUDE.md's latest addendum for the current counts).

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

**⚠️ Share authority disappears below 0.55 A — read this before commanding a
split.** The firmware's share loop is gated on **source current**. It enters
closed loop above `2 · SHARE_MINORITY_I_MIN_A` = 0.60 A of total source current
and drops out below `0.60 − SHARE_GOV_OL_HYST_A` = **0.55 A**
(`.ino:2181`/`:2205`, gate at `:9933`). In open-loop mode the firmware does not
write the MDACs at all — it **holds** the last split the closed loop converged
to. So below 0.55 A:

> `power_share_setpoint` is **accepted, logged, and not acted on.** The command
> still appears on the wire and in the CSV's `cmd_share_sp` column; the delivered
> split is whatever was standing when the load fell away.

This is designed behaviour — re-commanding a split during a coast-down slams the
droop gains — and it is not a defect to work around. What it means for you:

* **Writing a policy.** At low cruise your share decision does not change the
  pack's drain rate. A policy that regulates on SoC (a deadband, an SDP table)
  will be running open loop in exactly the regime it believes it is acting in.
  If it needs authority, give the scenario an `aux_preload_a` that holds the
  total above the gate; otherwise accept the hold and say so in the docstring.
* **Walking a policy offline.** Model the hold. Compute `I_tot` at each step,
  compare it against 0.55 A, and freeze the split below it. Two walks in this
  codebase have been wrong for this one reason — the second badly: campaign
  `20260901_024231` measured a **delivered share of 0.1656 against a commanded
  0.85** on `ems-sdp-cross`'s 0.355 A cruise, which made the walked charge-window
  period wrong by **5.7×** and failed a suite check on a correct board.

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
18-byte observation frame does not carry them (it does carry `error_code`, at
offset 16 — see §2 above). A portable strategy must not depend on the
telemetry-only fields either.

---

## 4. Mode B walkthrough — a real Pi in the loop

> **Pi-side prerequisite (audit 2026-09-01):** `docs/PI_BRIDGE_V4_AUDIT_20260901.md` verified the
> `teensy_bridge_node_2026-08-17A.py` bridge byte-for-byte against telemetry v4; the Pi's
> `sdp_ems_node_2026-03-16A.py` still reads the superseded 15-element layout and the default launch
> file starts it — see `docs/pi_bridge_change_request_20260901.md` for the required Pi-side changes.

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

**The EMS frontier check (cross-run, 2026-09-01).** Every check above is
per-run, and an energy-management result is a COMPARISON — campaign
`20260901_000816` shipped 53/53 PASS with a 9.9 pp policy regression in it.
`run_hil_suite.py` therefore scores one CROSS-RUN assertion over the three
`frontier_eligible` legs of the shared 61 s stimulus: `ems-soc-band` (causal
heuristic, the reference), `ems-sdp` (the calibrated causal policy, the
candidate) and `ems-dp-replay` (the non-causal bound). Legs are compared on
SoC-corrected hydrogen,

```
eq_H2(run) = h2(run) - (dSoC(run) - dSoC(ems-soc-band)) / lambda
```

at `lambda = 0.41 SoC/g` — the MEASURED share lever (campaign
`20260831_191509`: 0.409-0.415 on two independent stimuli). A leg that ends
with more charge left is CREDITED the hydrogen it did not have to burn. The
candidate must be `<= 0.98 x` the reference and `<= 1.06 x` the bound. The
verdict appears in `REPORT.md`'s header row, in a dedicated **EMS frontier**
section with a per-leg table and a lambda-sensitivity table, in
`results.json` under `ems_frontier`, and on stdout.

Anything but PASS makes the suite exit 1, and each non-PASS says why rather
than disappearing:

* **KNIFE-EDGE** — the verdict flips somewhere inside the measured lambda band
  \[0.409, 0.415]. Lambda is known to ~1.5 %, so a verdict that depends on
  where inside it you read is not a verdict. Neither PASS nor FAIL.
* **UNVERIFIED** — a leg is missing from the plan, was SKIPPED, failed its own
  checks, or has no `h2_cum_g` / `delta_soc`; or the legs' `delta_soc` differ by
  more than 0.010 SoC, over which the linear SoC correction is not credible.
  The offending leg is NAMED — a silently dropped leg is exactly how the
  regression above went unnoticed.

A run whose EMS strategy is `frontier_eligible: False` (`sdp-v2`, `hold-5050`,
the `y-*` profiles, ...) is excluded by construction and carries a
**DYNAMICS DEMONSTRATION** banner in its REPORT.md block and its per-run
`ANALYSIS.md`: its energy numbers measure a mechanism, not a competitive score.
⚠️ `h2_cum_g` is the Gfc model's estimate and its coefficients are not
identified against this rig's stack (`TODO(calibrate)`), so the frontier is a
RANKING on one rig, never an absolute mass.

**⚠️ How to read the `vs bound` arm — it is a lever-class detector, not an
optimality gate.** When both the candidate and the DP bound are **charge-free**,
their ratio is **structurally ~1.00** and proves nothing about optimality: two
charge-free runs differ only along the SHARE lever, `lambda` *is* that lever's
rate, so the eq-H2 correction subtracts exactly the difference they have and the
corrected totals coincide. The frontier section renders an **implied lever**
line — `d(delta_soc)/d(h2_cum_g)` between candidate and bound — so you can see
this: campaign `20260901_024231` returned `1.0000 x` with an implied lever of
**0.41021 SoC/g** against `lambda = 0.410`, agreement to 0.05 %. On such a
reading the discriminating arm is **vs reference** (0.9003 there). The vs-bound
arm fires when the candidate reached its result through a lever priced
differently from lambda — which is exactly what campaign `20260901_000816`'s
failing leg did, buying SoC through the Ag105 at ~0.24 SoC/g.

Consequently the earlier intent to tighten `1.06 x` to `1.03` is **amended, not
carried**: never tighten it on a campaign whose candidate never opened the
charger, because such a reading measures the degeneracy above rather than the
candidate's spread. Tighten only against campaigns whose candidate used a second
lever, and re-derive the number from the implied-lever spread they show.

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

### Delta-SoC-matched DP baselines

A hydrogen total ranks nothing on its own. Any energy-management strategy burns less
hydrogen by discharging the pack harder, so two strategies compare only at matched
terminal state of charge. `tools/hil_report_analysis.py` therefore solves, for every
run that executed a drive cycle, a dynamic-programming baseline whose terminal SoC is
THAT run's own, and reports the run's percent deviation from it. The per-campaign
table is `ANALYSIS_SUMMARY.md`'s "Delta-SoC-matched DP comparison"; each run's own
`ANALYSIS.md` carries the full block, and `analysis.json` carries it as `matched_dp`.

The solve is expensive, so solved baselines live in a results database at
`tools/dp_db/` (one JSON per solve under `solves/`, plus a rebuildable `index.json`).
A record is keyed on the problem it answers: the scenario, its profile fingerprint,
the pack and grid parameters, the charger accounting, the auxiliary preload, and the
model quantities the generated DP table header records. A lookup accepts a stored
target within 1e-5 SoC of the requested one.

Select the mode with `--matched-dp`:

| Mode | Behaviour |
|---|---|
| `lookup` (default) | Read `tools/dp_db/` only. A miss is recorded as `no_cached_solve` together with the key, and costs no compute. |
| `solve` | Compute and store a missing baseline. Refused for a scenario longer than 100 s unless `--matched-dp-allow-long` is passed, because FTP-75 costs tens of minutes. |
| `off` | Skip the comparison. |

`--matched-dp-tol` overrides the lookup tolerance. The default 1e-5 is 0.5 % of the
61 s cycle's whole SoC swing (~2e-3), and it is deliberately tight: an earlier 5e-4
default admitted a baseline whose own SoC excursion differed from the run's by a
quarter of the swing, and campaign-080905's `soc-band` leg read +22.29 % against a
true +10.79 %. Widen it only for a cycle whose SoC swing is far larger, and read a
widened figure with the stored-target note the block prints.

To populate the database ahead of an analysis pass:

```
python tools/dp_results_db.py prefill --scenario ems-soc-band     --soc0 0.7 --accounting physical --dsoc-span=-0.0030:-0.0010:5
```

Note the `=` in `--dsoc-span=`: argparse reads a leading-minus value as an option
otherwise. `prefill` skips a target already cached within `--tol` (default 1e-5 SoC),
so a span whose step is not larger than that solves its first target and reports the
rest as cached — choose a step above the tolerance. Each record is written
atomically, so an interrupted prefill leaves a consistent store. `list`, `show` and `rebuild-index` complete the
command set; only `prefill` needs numpy.

**Cost.** One matched baseline is a bisection over roughly 15 to 25 DP solves. On the
61 s `ems-soc-band` / `ems-dp-replay` / `ems-sdp` cycle that is 5 to 15 s. On the
340 s FTP-75 cycle it is 20 to 30 min, so prefill an FTP-75 scenario deliberately and
never inside an interactive analysis pass.

**Reproducing a miss.** A `no_cached_solve` block carries the complete `key_fields`
object in `analysis.json`. Paste it into a file and solve exactly that problem:

```
python tools/dp_results_db.py prefill --key-fields @missing_key.json
```

Prefer this over rebuilding the problem from individual flags, which can miss an
input — the charge ceiling, the run-era preload, the run-exit time — and solve a
problem the lookup will then never match. The object's `era_overrides` sub-object
is load-bearing: it holds the run-era value of every scenario-metadata key the
profile fingerprint covers, and the solve rebuilds the run-era metadata from it.
Without it a scenario-metadata change made since the run — a moved preload, a
newly declared charge ceiling — refuses the solve for fingerprint drift. The
refusal names the keys it reconciled and the keys it could not, and one of the
latter is the unreproducible part of the stimulus.

**Provenance drift.** Every record stores `hil_plant_sim`'s `constants_hash` at
solve time. A lookup compares it and, on a mismatch, USES the record and annotates
it `provenance_drift`, because the hash also moves when a constant the solve never
reads moves. `--matched-dp-strict` turns drift into a miss instead, which is the
setting for a figure that must not come from a differently-parameterised plant.

**Three boundaries on every figure this produces.** First, whether the DP's demand
model carries a regen term is an ERA (`gen_dp_ems_table.build_demand`'s `eta_regen`).
In the **pre-regen** era, which is every campaign on record, it does not: the
deceleration **demand** is identical and what is omitted is the returned energy, so a
regen-bearing scenario is ranked against a regen-free bound and its deviation is
optimistic. That optimism is bounded rather than unquantified — every rig-drag
frontier/EMS leg in this suite carries **0.000 J** of regen energy (no rig-drag drive
cycle commands a negative motor current), so on those legs the omission is exact;
regen-bearing scenarios are `frontier_eligible: False` by role and their residual
optimism measures **≤ 0.9 % of `h2`**. In the **regen** era, which the
`ems-ftp75c-*` family is the first to use, the bound earns the same braking credit the
run does and this boundary is replaced by the Ag105 settle and ramp
(`docs/HIL_PLANT.md` §9.4.2). Second, the
run's hydrogen total is the dynamic Gfc integrator (`H2Consumption`, a ZOH
discretization) while the DP's stage cost is the Gfc DC gain; the two agree at steady
state and differ through every transient. ⚠️ **Corrected 2026-09-02 — that bias is
about 10× smaller than this paragraph used to imply.** Measured on the same inputs it
is **0.0116 % (`ems-ftp75-dp`) to 0.0316 % (`ems-dp-replay`)** of the integrated
total, so a deviation of a few tenths of a percent is *outside* it and must not be
written off as Gfc discretization. The percent-scale table-versus-run gaps this suite
measures are attributed instead to the firmware's sub-0.55 A open-loop behaviour,
which the generator does not model (`docs/HIL_PLANT.md` §9.4). Third, the baseline is solved on the run-era
stimulus: every fingerprint key the sidecar can source is put back (the auxiliary
preload from its `constants` block, the charge ceiling from `config`, the rest from
its `scenario` block), and the applied set is recorded in
`matched_dp.stimulus_era.overrides`. A key the sidecar cannot source keeps this
checkout's value; a sidecar with no `constants` block records
`stimulus_era: unknown` and the baseline is solved on the current metadata
entirely. All three are printed as notes
under every block.

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
  not an error. **The Pi bridge source is now available** at
  `references/EMS/Pi_2026-09-01/` (`teensy_bridge_node_2026-08-17A.py` + ROS2
  nodes + SDP material, uncommitted) — this audit is the remaining Mode B
  blocker; see `WORK_QUEUE.md` §2.
* **Telemetry delivery is address-dependent.** The board sends to a hard-coded
  `192.168.1.100:5000`. A Pi elsewhere on the subnet commands fine and receives
  nothing; that asymmetry is a property of the firmware, not of your setup.
* **The plant is signal-level only.** No power stage, no real currents, no thermal
  behaviour. The Ag105's input-voltage-threshold MPPT mechanism itself **is**
  modelled, opt-in via `mppt_emulation` (default off; on in `mppt-tracking`) — the
  charger's I2C config writes and the CV taper remain unsimulated (`docs/HIL_MODE.md`
  Limitations; `docs/HIL_PLANT.md` fidelity boundaries). The simulator-only
  constants there are `TODO(verify)` and stay that way.
* **The encoder estimator is bypassed.** `v_actual` is injected, so nothing in a
  HIL run exercises the edge-period estimator, the fractional-pitch ledger, or the
  encoder front end. Those remain bench-only questions.
* **A Mode B pass is not a vehicle-readiness statement.** It says the firmware and
  the Pi agree on the wire, against a simulated plant.
