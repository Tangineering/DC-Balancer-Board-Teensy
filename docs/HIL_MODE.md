# HIL mode — real Teensy against a simulated plant (fw v21, extended fw v22)

> For the plant-side deep dive — the mechanical/electrical model, constant provenance,
> the simplifications and their consequences, the CSV schema and the extension roadmap —
> see [`docs/HIL_PLANT.md`](HIL_PLANT.md). This document covers the link: frames, staging,
> build flags and the H1–H5 test plan.
>
> For the OPERATOR-facing walkthrough — network/switch setup, the three-node bring-up
> and shutdown order, Mode A (emulated Pi EMS, `--ems`), Mode B (a real Pi in the loop,
> `--pi-live`) and a troubleshooting table — see
> [`docs/HIL_USER_MANUAL.md`](HIL_USER_MANUAL.md).

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

## Link-loss behaviour: hold, then zero, then latch — and (fw v22/v23) auto-recover

Three thresholds and one recovery path. The staging is deliberate:

| Age of last accepted frame | Behaviour |
|---|---|
| ≤ `HIL_STALE_MS` (50 ms) | apply the injected values normally |
| ≤ `HIL_ZERO_MS` (250 ms) | **HOLD** the last values, set `hilStale` |
| > `HIL_ZERO_MS` | force **safe zeros** on all seven rails and `v_actual`, **latch `ERR_HIL_STALE`** |
| link returns, fresh for `HIL_RECOVER_DEBOUNCE_MS` (500 ms) | **warm reset back to State 0** (fw v22) — see below |

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

### Auto-recovery from a latched State 99 (fw v22; widened fw v23)

Under fw v21 that latch was permanent, and stopping the simulator is the normal end
of an HIL run — so a 38-run suite cost 38 physical power cycles. A HIL build now
warm-resets itself back to State 0 when the link comes back. This is the **only**
path out of State 99 anywhere in the firmware, and it exists only under `HIL_SIM`.

Fw v22 admitted recovery only for the exact dead-link fault signature. That proved too
narrow in practice: a suite scenario latched a real `FAULT_UV_BUS`, and every later run
then found the board latched. **Fw v23 admits ANY latched fault** — under `HIL_SIM` the
plant is a simulation, so every fault is a simulated-plant event belonging to one run —
and replaces the signature test with a **run-boundary** gate.

All four conditions are required:

1. `state99Phase == 3` — the phased teardown has **completed**. Resetting between
   phases would abandon the sequencing mid-way and could leave an energized path
   pointed into a not-yet-disabled boost (CLAUDE.md §2 back-feed rule).
2. **A run boundary has been observed** (fw v23): the injection link continuously
   **silent** for `HIL_RUN_BOUNDARY_MS` = **1000 ms** while in State 99. The window is
   anchored to the **last accepted frame**, and tracked in *any* teardown phase — so the
   figure means literally "1000 ms with no injection frame". Anchoring it to the first
   *observed* dead tick instead would have added the 250 ms `HIL_ZERO_MS` detection
   latency plus the teardown, making the real requirement ~1250 ms+ and leaving a literal
   1 s host gap unable to recover at all. The boundary is only an admission precondition
   — the reset is still gated on phase 3, on the closed log and on the fresh-link
   debounce. A gap of **exactly** 1.0 s is knife-edge (one loop tick of margin), so
   host-side gaps should sit comfortably above 1 s rather than at it. This is
   what keeps a widened admission safe. While a scenario is running *and the host keeps
   streaming*, no boundary can accrue and a mid-scenario fault cannot self-clear — which
   is what the replay suite's `fault_latched` deviation checks rely on. That premise is
   conditional, not structural: a host stall of ≥ 1 s (a GC pause, a laptop parking a
   core, a blocked write) **does** forge a boundary mid-scenario, and `comm-loss` now
   forges one deliberately (its 2 s transmit gap; `warm_resets_expected` 1). Because the
   premise can break, it is not assumed — every run is checked against the **mid-run
   warm-reset tripwire** described below, and a run that shows an unexpected one is
   reported INCONCLUSIVE rather than scored. 1000 ms is
   deliberately far longer than the 250 ms zero stage, so a host-side hiccup (a suite
   process being killed slowly, a GC pause) cannot forge a boundary, while the gap
   between suite scenarios is multiple seconds. The observation is sticky and is cleared
   by `hilWarmReset()`, so one boundary admits at most **one** recovery attempt: a
   persistent fault condition simply re-latches on the next run.

   *Why not simply widen the fw v22 signature test?* `triggerFault()` ORs bits into
   `fault_flags` even when the board is already latched, while `error_code` stays
   first-cause-only. "A real fault, then the simulator stops" therefore produces
   `0x8010`-plus-bits with a non-HIL `error_code`, and no equality signature can
   separate the cases.

   For the pure dead-link case the window is already running when State 99 is entered, so
   the boundary accrues during the teardown before any frames return and recovery timing
   is effectively unchanged from fw v22.

   `hilWarmReset()` prints the outgoing `error_code`, `fault_flags` and
   `error_source_state` **before** clearing them. With any fault now recoverable, that
   print is the last place the cause exists — it is not carried on the observation frame,
   and a host that was not attached when the fault latched never saw it. The State-99
   1 Hz report also appends the live boundary/arm/phase status, so a board that will not
   recover shows which precondition it is waiting on (the `'S'` dump is not reachable
   from State 99; its `run boundary:` / `recover arm:` lines remain useful afterwards).
3. The link has been continuously fresh (`age <= HIL_STALE_MS`) for
   `HIL_RECOVER_DEBOUNCE_MS` = **500 ms**. The window re-arms from zero on any
   staleness. 500 ms is deliberately longer than the 250 ms zero stage, so a link
   flapping around the dead-link boundary settles into the latch — visible and
   diagnosable — instead of cycling the board through bring-up on every flap.
4. The SD bench log is fully closed and drained. `triggerFault()` only *requests* the
   close; `logDrainTick()` does the card I/O in phase 3, the same window this check
   lives in, so a reset taken with a close in flight would strand an unfinished file.

`hilWarmReset()` then restores the software state machine to boot values — fault and
error latches, the UV/OV arming and dwell integrators, the motor and Youla drive
state, the share loop and all four isolation/setpoint-cut latches, the control rate
limiters, the bring-up machine, the Pi command state (including `mode_cmd` back to
**SAFE**, so a stale `MODE_HYBRID` cannot re-enter Run), the Ag105 session flags, the
State-98 bench-tool residue and the velocity estimator — and sets `mainState = 0`.
Boot-monotonic diagnostics (encoder edge counters, HIL frame counters, OV/UV transient
counts) stay cumulative across runs by design.

**No pin is touched by the reset.** Teardown phase 2 has already left the stage in the
`setup()` configuration, with the single exception of `BT_SEQUENCE_ENABLE`, which the
IO CSV says need not be turned off again and which bring-up phase P1 drives HIGH
anyway. Recovery therefore opens and closes no switch: State 0 re-derives the whole
sequence through the staged bring-up machine.

The console prints `[HIL] link recovered — warm reset, re-entering State 0` plus a
run-separator note. The `'S'` dump's `--- HIL ---` section shows `recover arm:`
(armed / elapsed against the debounce) and a cumulative `warm resets:` count.

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

> ✅ **Boot order is free from fw v22.** State 0 in a HIL build waits — non-blocking,
> with a 1 Hz `State 0: waiting for HIL injection stream...` notice and
> `detectFaults()` live — until the link is up and fresh before it **arms** the
> staged bring-up machine, so no bring-up phase clock runs before the plant exists.
> The board and the simulator may be started in either order.
>
> *Historical (fw v21):* a production (`BENCH_TEST=0`) HIL flash read real
> (disconnected) ADCs until the first frame landed and latched `FAULT_INIT_FAIL` at
> ~800 ms if injection had not started. That race is removed, not documented; the
> boot banner was re-worded to match.
>
> Note the gate guards the **start** only (it is skipped once `bringupActive`): a
> link hiccup *during* bring-up is handled by the two-stage hold-then-zero above,
> and a genuine loss faults and then auto-recovers.

> ⚠️ **`BENCH_TEST` no longer changes State 0 under `HIL_SIM` (fw v22).** A HIL build
> runs the staged bring-up at *both* `BENCH_TEST` values. The `BENCH_TEST=1`
> dark-boot bypass exists because enabling a boost at boot on a soft bench supply
> browns out the board-powered Teensy — a statement about a real power stage, of
> which a HIL build has none. Keeping it only made a `BENCH_TEST=1` HIL flash unable
> to reach Run without an operator driving `'T'`/`'G'`/`'Q'` at the USB console.
> Non-HIL builds are unaffected and keep the fw v21 behaviour verbatim.

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

A relative `--csv` path (as above) lands in `HIL Results/` at the repo root; an
absolute path is honored verbatim (`docs/HIL_USER_MANUAL.md` §2.5). The
electrical events sidecar follows the resolved path.

**CSV logging is on by default.** Omit `--csv` and the run names itself
`hil_<scenario>_<mode>_<YYYYmmdd_HHMMSS>.csv` under `HIL Results/`, where
`<mode>` is `open` / `timeline` / `ems-<strategy>` / `pilive` /
`replay-<log stem>` (plus `-hifi` on a hi-fi run); `--no-csv` disables logging
entirely — **including the hi-fi `.events.jsonl` sidecar**, which derives from the
CSV path, so an `--electrical hifi --no-csv` run records no `scp_cut` / `sw_ring` /
chopper events anywhere (the simulator prints a notice saying so). An explicit
`--csv` is refused (exit 2) unless `--force` when *any* of its three artifacts —
the CSV, `.meta.json` or `.events.jsonl` — already exists, since together they are
one run's record. The example above therefore needs `--force` the second time it is
run. Every CSV is accompanied by a `<csv>.meta.json` sidecar recording the
scenario, the command mode, the resolved configuration, a sha256 over the plant
and electrical model constants (with the constants themselves, so the hash is
auditable), the git revision, and the run's results. It is written once before
the loop with `"status": "running"` and rewritten at exit — a killed run still
leaves a record. See `docs/HIL_USER_MANUAL.md` §2.5 for the full schema.

Two additional command sources exist and are documented in
[`docs/HIL_USER_MANUAL.md`](HIL_USER_MANUAL.md): `--ems STRATEGY` (Mode A — an
emulated Pi EMS policy replaces the scenario's `pi_timeline`) and `--pi-live`
(Mode B — a real Pi owns the command link and this process injects only).

Stdlib only — no numpy. (To drive the board from a recorded bench log instead of
the modelled plant, see **Replay mode** below.) Scenarios:

| Scenario | What it does |
|---|---|
| `steady` | fixed aux load; the quiescent baseline |
| `step-load` | +1.2 A aux load step at t = 5 s — a bus disturbance the share loop must reject |
| `sag` | −5 V bus disturbance for 1 s at t = 5 s, crossing `LIMIT_V_BUS_MIN` (12.0 V) |
| `comm-loss` | stops transmitting for **2 s** at t = 5 s, then resumes — long enough to clear fw v23's 1000 ms run boundary with margin, so the warm recovery is part of the test |
| `drive` **(operator-required)** | plant only; the operator drives the firmware by hand (`'V'`, `'D'`, `'Y'`) over USB. Marked `operator_required` in `SCENARIOS`, so `run_hil_suite.py` renders it **SKIPPED** unless `--with-operator` is given — run unattended it commands nothing and the drive loop is never exercised (that is `ems-drive-cycle`'s job). |
| `charge-cruise` | Run + cruise + `charge_goal` > 0 via the Pi command timeline — `FC_CHARGE` opens on intent, the Ag105 settles to Charging, MPPT released |
| `charge-regen` | cruise/brake cycling driven by the **`regen-harvest` EMS strategy** (redesigned 2026-08-30). `charge_goal` is asserted **only inside a braking window**, so the Ag105 is fed through `REGEN` + `MOT_PWR` and the single-source `FC_CHARGE` path never opens. Charge ceiling de-rated to 1.6 A (`chg_i_ceiling_a`). |
| `charge-fault` | charging established (cruise at t = 5, `charge_goal` staggered to t = 8), then the charger input rail collapses at t = 20 s — the GENSTAT decode / charger-loss path. Charge ceiling de-rated to 0.8 A (`chg_i_ceiling_a`) so the FC-path draw stays under `LIMIT_I_FC_MAX` and the run survives to its own stimulus. |
| `soc-depletion` | sustained battery-heavy load; `V_batt` walks down the OCV curve toward `LIMIT_V_BATT_MIN` (use `--soc0` / `--capacity-ah` to fit a bench session). The share rail (t = 5) and the load (a 3 s ramp from t = 10) are **staggered**: landing both on one tick put 1.47 A on FC for a single sample and latched `OC_FC`. The load itself is **2.2 A**, not 3.0: the setpoint latch cuts FC *off the bus* at `share_sp = 0.0`, so BT alone carries 0.15 + 2.2 = **2.35 A** against `LIMIT_I_BT_MAX` 3.0 A (22 % margin) — at 3.0 A it was 3.15 A, over the limit outright, for the whole run. **Suite override re-derived 2026-08-30:** `--soc0` **0.20**, duration **400 s** (was 0.15 / 880 s). The old pair could not satisfy its own check — it treated the 2.2 A *bus-side* load as the coulomb current, when the pack sits behind the boost (6.46 → 14.37 V) and delivers ≈ **6.19 A**; and the `UV_BATT` latch is a *state* condition (`OCV(soc) − I·(Rs(soc)+R1) = 6.2 V` solves at `soc_latch ≈ 0.113`), so the run ends there rather than running the assumed ~870 s. From `soc0` 0.15 the maximum observable fall was 0.037, **below** the 0.05 threshold at any duration. At 0.20 the ceiling is 0.087 = **1.74×** the threshold, the latch is expected at ≈ 266 s, and the signal gate is now **disjunctive** — either the 0.05 fall *or* a post-ramp `UV_BATT` latch proves the depletion, because the two foreclose each other. |
| `handoff-sag` **(hi-fi only)** | the share **setpoint latch** cuts one source off the bus, then a +1.5 A step probes the single-source sag and the UV dwell decision. Operating point re-derived 2026-08-30: a +0.40 A pre-load from t = 4 puts the pre-rail total at ~0.74 A — above the 0.60 A closed-loop governor gate, below the cut's own 0.5 A/channel handoff guard — and the rail direction is **share 0.0** (BT survives), because at the FC rail `LIMIT_I_FC_MAX` 1.4 A leaves too little perturbation budget. ⚠️ A *reactive pickup* is **not** reachable from a setpoint-latched cut: the switch is driven EN-low and an EN-low RT1987 does not conduct at all. |
| `bringup` **(hi-fi only)** | from dark: the firmware's staged bring-up P0–P3 against the real RT1987 t_D(ON) + soft-start delays |
| `scp-inrush` **(hi-fi only)** | RT1987 soft-start **foldback + SCP cut** on `MOT_PWR` into the top of the VESC input envelope (0.9 mF). Three-phase stimulus (2026-08-31 deterministic redesign): the ramp runs **unloaded**, then a 6.5 A fold pulse (`SCP_INRUSH_FOLD_LOAD_A`) steps in when V-MOT crosses `SCP_INRUSH_ARM_V` 1.2 V mid-soft-start — the fold binds in one substep and the cut fires inside that same tick, before the board's switch word can arrive (phase-independent, unlike the pre-redesign t = 0 flat load whose cut raced the firmware's OC teardown). A one-shot latch withdraws the pulse; a 5.0 A run load (`SCP_INRUSH_RUN_LOAD_A`, +110 ms) then latches `OC_FC` deterministically. Scored on exactly one `MOT_PWR` `scp_cut` in the events sidecar; see the `SCP_INRUSH_*` constants block for the derivations. |

`python3 tools/hil_plant_sim.py --list-scenarios` prints this table with the engine each
scenario needs and its default duration. Scenarios marked **hi-fi only** require
`--electrical hifi` and are refused under the default `simple` engine rather than
producing a meaningless trace.

| Flag | Meaning |
|---|---|
| `--electrical {simple,hifi}` | electrical engine (default `simple` — one droop node). `hifi` selects `tools/hil_electrical.py`: TPS61288 average model, RT1987 ideal-diode state machines, a six-node ODE at an adaptive substep rate. See `docs/HIL_PLANT.md` §8. |
| `--replay-no-preamble` | replay: skip the synthetic bring-up preamble and play the log **raw** from t = 0 (timestamps unshifted). For a log whose point is that bring-up *fails* — with the preamble the board comes up on the synthetic rails first, so `FAULT_INIT_FAIL`, raised only from State 0's bring-up machine, can never fire. |
| `--replay-i-fc-clamp X` | replay: clamp the injected `I_fc` to at most X amps. **Modifies a recorded trajectory** — for logs whose recorded FC current came from a DC bench supply the real H-20 could never source, and would otherwise latch `OC_FC` before the stimulus the log was kept for arrives. Declared loudly wherever it is used; no FC-current conclusion may be drawn from such a run. |
| `--trace-config {long,short}` | hi-fi parasitic-inductance set: `long` = as-manufactured FastHenry extraction, `short` = post-bodge (default) |
| `--vesc-cap-uf X` | hi-fi VESC input capacitance (envelope 200–900 µF, default 500) |
| `--soc0 X` | initial battery state of charge, 0–1 (default 0.7) |
| *(scenario field)* `chg_i_ceiling_a` | per-scenario Ag105 charge-current ceiling, in the same class of knob as `vesc_cap_f`: it sizes the **stimulus**, it does not model the firmware (which always configures the 2.5 A profile). Absent → `AG105_I_MAX` 2.5 A. Used by `charge-fault` (0.8 A) and `charge-regen` (1.6 A) so their FC-path draw stays under `LIMIT_I_FC_MAX`; the sim prints a line whenever it is de-rated. |
| `--capacity-ah X` | battery capacity (default 5.0 Ah) |
| `--noise` | hi-fi: apply ADC quantization (and any configured sigmas) to the injected values |
| `--csv PATH` | per-tick CSV log (default: auto-named under `HIL Results/`) |
| `--no-csv` | write no CSV and no `.meta.json` sidecar |
| `--force` | overwrite an explicitly-given `--csv` that already exists |
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

A fixed `--csv` name like this one is refused on the **second** run (exit 2) —
the CSV, its `.meta.json` and its `.events.jsonl` are that run's record and are
not overwritten silently. Add `--force` to replace them, or drop `--csv` and let
the run auto-name itself (`hil_replay-tp0178_<timestamp>.csv`).

| Flag | Meaning |
|---|---|
| `--replay PATH.BLG` | replay this log; **mutually exclusive with `--scenario`** |
| `--replay-speed X` | pacing multiplier (default `1.0` = true wall clock) |
| `--loop` | repeat the log until `--duration` elapses (replay only) |
| `--duration` | defaults to the log's own length ÷ `--replay-speed` |
| `--replay-commands` | ALSO replay the log's recorded `v_sp`/`share_sp` as Pi command packets — see below (replay only) |

The log is decoded through `tools/decode_benchlog.py`'s `decode_blg()` (lazy
import; a clear message and a non-zero exit if it can't be imported, read or
parsed), so every BLG format version that decoder supports (v1–v7) replays.

### Command replay (`--replay-commands`)

By default a replay sends **injection frames only**. No `PiCommander` is built, so
no 22-byte command packet ever reaches the board: it brings up, sits in **State 1
(Idle)** holding `vesc.setCurrent(0)`, and the observation frame's `current` is
`0.0000 A` for the whole run. Every current-shape assertion in the replay suite is
then vacuously true.

`--replay-commands` closes that gap. The log's own recorded `v_sp` and `share_sp`
— columns present in **every** BLG format v1–v7 — are replayed as ordinary Pi
command packets at **50 Hz**, on the same socket as the injection frames:

```
python3 tools/hil_plant_sim.py --teensy-ip 192.168.1.50 \
        --replay logs/ML0151.BLG --replay-commands --csv hil_replay_ML0151.csv
```

- **While the synthetic bring-up preamble runs** the commander holds `MODE_SAFE`,
  `v_setpoint = 0`, `share = 0.5`. `MODE_SAFE` only acts from State 2, so it is
  inert during bring-up — which is what is wanted there. With
  `--replay-no-preamble` there is no preamble and `MODE_HYBRID` is commanded from
  `t = 0`; on a log whose point is that bring-up fails the board never reaches
  Idle, so the command is harmlessly ignored (dispatch requires `mainState == 1`).
- **After the preamble** it commands `MODE_HYBRID` with the record's own
  `v_sp`/`share_sp`. `mode_cmd <= 3` from State 1 is what moves the board
  **Idle → Run**.
- The command state is written from **the same tick's replay record**, so it is
  zero-order held on exactly the same time axis as the injection stream —
  `--replay-speed` alignment is automatic.
- Two CSV columns, `cmd_v_sp` and `cmd_share_sp`, are appended to the replay
  schema **unconditionally** (blank under a plain `--replay`), and the
  `.meta.json` sidecar records `replay_source.replay_commands`. They carry the
  record's own commanded value for **that tick** (1 kHz), not the last value
  transmitted — the 50 Hz packet stream lags them by ≤ 20 ms.
- **Use `--replay-speed 1.0` when command fidelity matters.** The command stream
  runs at 50 Hz of *wall* clock, not of log time, so a speed of X under-samples
  the recorded setpoint by exactly X.

Two firmware behaviours to know before reading such a trace:

- **Idle → Run zeroes `v_setpoint` and resets the drive controller**
  (`doState1()`, `.ino:5382-5410`). The real setpoint therefore arrives on the
  *next* 50 Hz packet, ≤ 20 ms later. That is by design, not a dropout.
- **Once in Run the 50 Hz stream is load-bearing.** The Pi watchdog
  (`PI_TIMEOUT_MS = 500`, `.ino:2915`) arms after the first command packet and
  latches if the stream stops in State 2/3, so the commander keeps transmitting on
  every due tick for the whole run — through log gaps and the preamble alike.

> ⚠️ **Command replay does NOT close the loop.** It adds a second *replayed*
> channel. The injected `v_actual` still does not respond to what the firmware
> commands, so this exercises the controller's **reaction** to a recorded
> stimulus, never closed-loop tracking. Expect the drive loop to **fight** the
> recorded trajectory wherever the recorded and flashed control laws differ —
> that is the stimulus, not a defect.

Which suite entries opt in, and why some deliberately do not, is
`replay_commands` in `tools/hil_replay_suite.py` and the `cmds` column of
`docs/HIL_REPLAY_LOGS.md`.

### ⚠️ Fidelity caveat — replay is an OPEN-LOOP stimulus

**The plant integrator is bypassed. The firmware's commands do NOT influence the
replayed trajectory.** In live simulation the loop is closed — a bigger `I_cmd`
accelerates the modelled flywheel and comes back as a larger `v_actual`. In replay
the trajectory is fixed history: command +12 A and `v_actual` keeps doing exactly
what the bench did. Replay therefore validates **responses** — state transitions,
switch sequencing, fault latching, command shape at a given operating point — and
must never be read as a closed-loop trajectory match. Two further consequences:

- The board's own `'V'`/`'D'`/`'Y'` commands cannot "drive" a replay.
- `--replay-commands` (above) does **not** change any of this: it replays the
  recorded *commands* as a second fixed channel, it does not close the loop.
- **OC faults latch on injected currents regardless of switch topology.** The
  injected rail currents are independent of the board's own switch state, so an
  OC fault can latch on a current that could not physically have flowed through
  the path the board actually had open. Clean as of campaign
  `20260831_000518` — ML0203's `OC_FC` latch had `FC_BUS` closed — but check
  `switch_state` at the latch time before reading any replay OC result as a
  statement about hardware.
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

### Synthetic bring-up preamble (2026-08-30)

Every replay is preceded by **`REPLAY_PREAMBLE_S` = 2.5 s of healthy nominal rails**
before the recorded trajectory starts. fw v22+ runs a closed-loop staged bring-up
(P0–P3) at the start of every HIL run and it needs live rails to complete; a recorded
log begins wherever the operator pressed record, which for some logs is a dark bus and
for the BLG v1/v2 group is a run already in progress.

- **Every timestamp in a replay CSV is SIM-relative:** log time = `t − 2.5 s`.
  Preamble rows carry **`replay_rec = -1`** and no source record.
- The preamble does **not** test bring-up dynamics — the bus is presented already in
  regulation, so P0/P1/P2 pass on their minimum dwells. That is the `bringup`
  scenario's job. The preamble exists only so the recorded trajectory reaches a board
  sitting in Idle.
- 2.5 s is derived: it must exceed `WARM_RESET_GRACE_S` (2.0 s), so no part of the
  recorded trajectory falls inside the fault-scoring grace window, and it must exceed
  the measured warm-reset recovery plus bring-up (~0.62 s).

### Absent rails in BLG v1/v2 (2026-08-30)

BLG v1/v2 records carry **no `V_fc`, `V_batt` or `V_rgn` field**. Injecting `0.0 V`
handed the firmware a dark board — the staged bring-up's P3 gate reads `V_rgn` as its
motor-node proxy, so it never tracked `V_bus` and those replays latched
`FAULT_MOT_HOTPLUG` at ~1.09 s. Absent fields are now supplied as healthy nominals —
`V_fc` 12.9 V, `V_batt` 7.9 V, `V_chg` left at 0 V (an unpowered charger input is the
honest value) — and `V_rgn` is **derived**: the injected `V_bus` while the board's own
`MOT_PWR` bit is set, else 0 V (fw v22 topology: the RGN-V divider sits on V-MOT). The
derivation ignores the ~35 mV RT1987 forward drop and the motor node's own RC.

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

(Repeating this exact command needs `--force`, or a fresh `--csv` name, or no
`--csv` at all — see the note under "Replay mode" above.)

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
start, says so in one line, and the normal 1 Hz status lines are kept. If the
renderer thread dies mid-run, the suppressed 1 Hz status lines resume printing
from the next tick (the dashboard no longer leaves the screen frozen forever).

**Sparklines and narrow terminals.** Each frame reads the real terminal size
(`shutil.get_terminal_size`, falling back to 80×24) and adapts to it: line text
is truncated to the terminal width so the fixed-line `ESC[H` redraw can never
wrap and corrupt the screen; the sparklines shrink to `max(10, cols-40)` points
wide, showing only the most recent samples at that width; the `fault_flags`
line caps at 4 spelled-out names plus a `+k more` suffix; and if the whole
frame still would not fit the terminal's row count, the lowest-priority lines
(section header rules and blank spacers first, then the hi-fi/hint lines) are
dropped before the essential rows. At the *default* 80-column-or-wider terminal
and the default 5 Hz refresh, a sparkline spans roughly its full **60-sample /
~12 s** history window (stretching further if the renderer falls behind); on a
narrower terminal it shows fewer of those samples, i.e. a shorter time window
at the same 5 Hz sample rate — the spark is always "however many of the most
recent samples fit", not a fixed time span.

### Suite integration (`--dashboard`, default OFF)

`tools/run_hil_suite.py --dashboard` appends `--dash` to every child. It is **off
by default** so suite behaviour without it stays byte-identical, and because of one
trade-off: the wrapper normally captures each child's stdout into a per-run `.log`
and parses the run summary out of it, but a dashboard writing ANSI into a captured
pipe is useless (and the child's own tty check would just disable it). So with
`--dashboard` the children are given the **real terminal** for stdout (stderr is
still captured), the run record is marked `stdout_passthrough`, and the
stdout-derived summary columns in `REPORT.md` are empty for that run. `REPORT.md`
says so explicitly — a "Dashboard mode" header row, a per-scenario note above the
affected fields, and an explicit `achieved_rate` check with `passed: true` and a
"rate gate SKIPPED" detail (not a silently absent check) — so the empty columns
read as "unmeasurable in this mode", not as a parse failure. Because passthrough
needs the real terminal, `--dashboard` refuses to run at all (with a clear error)
when stdout is not a tty (piped/CI); drop the flag or run interactively. Use it to
watch a run; leave it off when you want a complete report.

## Running the full suite

The individual commands above are for a single scenario or a single recorded log.
`tools/run_hil_suite.py` is the one-shot wrapper: it runs **every** scenario in
`SCENARIOS` and **every** entry in the replay suite against a flashed board, then
packages the whole thing into a timestamped report directory.

```bash
python3 tools/run_hil_suite.py --teensy-ip 192.168.1.50
```

`--pi-live` runs the same plan with a real Pi commanding: scenarios carrying their
own `pi_timeline` (and the EMS scenario) are SKIPPED with a reason, and the report
is tagged `mode: pi-live`. See [`docs/HIL_USER_MANUAL.md`](HIL_USER_MANUAL.md) §5.

**Prerequisites**

- The board is flashed `-DHIL_SIM=1 -DUSE_ETHERNET=1` (fw v21 or later — the runner
  states that expectation in the report header; it does not enforce it).
- Board and simulator host share an L2 segment, and the board answers on
  `--teensy-ip` / `--port` (default `5001`, the `.ino` `local_port`).
- Nothing on the power stage. This is signal-level HIL; the scenarios drive the
  firmware's fault and sequencing paths deliberately.
- From fw v22 the board may be powered before or after the simulator: State 0 waits
  for the injection stream. (Under fw v21 a production build had to see the simulator
  streaming before power-on or it hit `INIT_FAIL` in ~800 ms.)

**Options**

| Flag | Meaning |
|------|---------|
| `--out DIR` | report directory (default `HIL Results/hil_report_<YYYYmmdd_HHMMSS>/` at the repo root; an explicit DIR keeps its usual CWD-relative meaning) |
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
rails, unbinds the host and latches `ERR_HIL_STALE`.

**From fw v22 that latch releases itself.** Once the next run starts streaming, the
board debounces the link for 500 ms and warm-resets to State 0, then runs the staged
bring-up on the new run's injected plant — so each run now begins from a *fresh boot
equivalent*, not from a latched board, and the whole 38-run plan executes without
anyone touching the hardware.

**From fw v23 that also covers a run that latched a REAL fault.** Fw v22 admitted
recovery only for the exact `0x8010` dead-link union, so one scenario latching (for
example) `FAULT_UV_BUS` left every later run to find a latched board and the suite
needed a power cycle. Fw v23 admits any fault code, gated instead on a **run boundary**:
the link must have been silent for `HIL_RUN_BOUNDARY_MS` = 1000 ms, measured from the
last accepted frame, while the board is in State 99. The default `--settle-s 5` gap
satisfies that comfortably. Within a run a boundary is not *supposed* to accrue, so a
fault normally stays latched for the rest of the run that raised it and the runner
judges each run's fault outcome against that run's own stimulus. Two caveats, both
load-bearing: a **host stall of ≥ 1 s forges a boundary anyway** (the anchor is the last
accepted frame, and the host cannot promise it will never stall), and `comm-loss`
forges one **on purpose**. So "stays latched for the rest of the run" is the expected
case, not a guarantee — which is precisely why the mid-run warm-reset tripwire below
checks it on every run instead of assuming it. If the fault condition is persistent, the
next run simply re-latches (one recovery attempt per boundary).

*Keep `--settle-s` well above 1 s* (the runner warns below 1.5 s). At or under the
1000 ms boundary the window may not accrue and the board can stay latched into the next
run, exactly as under fw v22. The margin is not fully under `--settle-s`'s control
either: the boundary is anchored at the last accepted frame, so the previous child's
teardown and the next child's startup also count toward the dead window, making the
true gap longer than the pause by an amount nothing measures.

*Under fw v21 each run instead started from a known latched board; the way to get a
clean State-1 board for a particular run was to power-cycle and pass `--settle-s 0`.*

**Execution model.** Every run is a separate `hil_plant_sim.py` child process (not an
in-process call) with a hard timeout of the run's duration + 30 s, so a wedged run is
killed and recorded as `TIMEOUT` instead of hanging the session. Each child's
stdout/stderr lands in a per-run `.log`.

**What the report contains** (`REPORT.md` + machine-readable `results.json`):

- a header — date, board IP, firmware expectation, host, achieved tick rates;
- a summary table of every run (kind, electrical mode, duration, pass/fail, key metrics);
- a **scenarios** section. Scenario entries carry no declarative checks, so the runner
  applies its own health criteria: at least one observation frame arrived (zero frames
  = FAIL, the board is absent), the fault outcome matches the declarative
  **`FAULT_EXPECTATIONS`** table, the achieved rate held above 900 Hz, and no
  `sw_ring` event exceeded the 20 V abs-max;
- **`FAULT_EXPECTATIONS`** (2026-08-30) replaced the old permissive `FAULT_ALLOWED`
  free-text table, whose check never compared the observed bits against anything and
  so rubber-stamped three runs whose objectives were never reached. Each entry may
  declare: `require` (a bit mask that must appear), `allow_only` (everything that may
  appear — any other bit fails), `not_before_s` (a required bit appearing before the
  stimulus time fails: it did not come from the stimulus), `survive_to`
  (`{"t": X, "states": {2, 3}}` — the board must still be un-latched and in one of
  those states at `t = X`, i.e. it actually reached its own stimulus), and
  `events_require` (event kinds that must appear in the hi-fi events sidecar), and
  **`signals_require`** — POSITIVE evidence from the CSV that the objective was
  actually reached. Every other field constrains *faults*, i.e. what must not happen,
  and a scenario can satisfy all of them while doing nothing at all; `signals_require`
  asserts a trace fact instead (switch-bit tick counts, a column reaching a value, a
  column falling by an amount, optionally inside a time window). Applied to
  `charge-regen` (REGEN asserted during braking + `I_charge` actually delivered),
  `charge-fault` (charging established before the collapse), `soc-depletion` (SoC
  genuinely fell) and `handoff-sag` (the bus switch really opened and stayed open).
  Every entry carries a source citation. Current expectations: `sag` requires `UV_BUS`;
  `comm-loss` requires `ERR_HIL_STALE`; **`charge-cruise` requires `OC_FC`** (operator
  ruling (b): FC-path charging and hard acceleration are incompatible by design, so
  the latch is the validation); `charge-regen`, `charge-fault` expect no fault but must
  survive to their stimulus; `soc-depletion` allows only `UV_BATT`; `handoff-sag`
  allows only `UV_BUS`; `scp-inrush` requires an `scp_cut` event and allows `OC_FC` or
  `MOT_HOTPLUG`;
- **grace-aware fault scoring** (2026-08-30). Every fault judgement, both halves, uses
  observations at `t ≥ WARM_RESET_GRACE_S` (2.0 s) only. From fw v23 the board
  warm-resets out of the previous run's `ERR_HIL_STALE` settle latch at `t ≈ 0.5 s`, so
  every run after the first opens showing `0x8010` (or `0x8011` / `0xA010` when its
  predecessor latched something of its own) through no fault of its own — 23 of the 33
  FAILs in the first fw v23 pass were that artefact. `REPORT.md` still prints the full
  whole-run union, with the carried-in bits named separately. The rule excludes an
  observation *window*, never a bit value: a board that stays latched shows its bits
  after the bound and still fails — and a fault that latched *before* the bound and
  persists is still seen, since the filter ORs over samples rather than edges. A
  companion check asserts the post-grace window is **non-empty**: a board that
  answered for 0.4 s and then went silent would otherwise have every fault check pass
  on no evidence at all;
- the **mid-run warm-reset tripwire** on every run of both halves. Each child counts the
  `mainState` transitions out of the latched State 99 that it observed, reports them on
  its `[hil] warm resets:` summary line and in its `.meta.json` sidecar, and the runner
  judges the count. Transitions in the first 2 s are the expected start-of-run recovery
  from the previous run's settle pause and are not counted as mid-run. A nonzero
  **mid-run** count marks the run **INCONCLUSIVE** — not PASS, not FAIL: a host stall of
  ≥ 1 s reads to fw v23+ as a run boundary, so the board warm-resets and clears whatever
  fault it had latched, and every fault-based check on that run (the replay suite's
  `fault_latched` entries most sharply) would read clean for the wrong reason. The one
  whitelisted scenario is `comm-loss`, which *requires* exactly one — declared as
  `warm_resets_expected` in the scenario registry;
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
| **H3 — comm-loss hold-then-zero** | H1 passing, board in Idle, simulator logging. | `--scenario comm-loss` (**2 s** transmit gap at t = 5 s). | During the first 50 ms of the gap the board's behaviour is unchanged. `'S'` dump reads `STALE` between 50 ms and 250 ms with no fault attributable to the gap. After 250 ms it reads `DEAD (zeroed)` and the injected rails read 0 — the ordinary UV/sequencing logic responds to that as it would to a dead board — and `ERR_HIL_STALE` latches State 99. On resume, `link: UP` returns and the accept count resumes rising; **fw v22/v23:** ~500 ms later the console prints `[HIL] run boundary + link recovered — warm reset, re-entering State 0`, the observation frame's `mainState` returns 0 → 1 and `fault_flags` clears to 0, and the `'S'` dump's `warm resets:` count increments. *(fw v23: the boundary window is measured from the last accepted frame, so the scenario's transmit gap satisfies it directly and the `run boundary:` status reads `SEEN`. The gap is **2 s** against a 1000 ms requirement — a 1.0 s gap was knife-edge by one tick and made the outcome a coin flip. The simulator's own `[hil] warm resets:` line must report exactly **1 mid-run**, which is what `run_hil_suite.py` requires for this scenario alone.)* |
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
