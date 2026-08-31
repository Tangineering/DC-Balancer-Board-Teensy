# HIL replay suite — log selection

**Maintained document.** This is the curated list of real bench logs (`logs/*.BLG`)
that are replayed at the firmware through `tools/hil_plant_sim.py --replay` as a
HIL scenario class, and the reason each one is in (or out of) the suite. It is
kept in lockstep with `REPLAY_SUITE` in `tools/hil_replay_suite.py` — **if you add
a log to one, add it to the other** (checklist at the bottom).

Companion documents: [`HIL_MODE.md`](HIL_MODE.md) (the wire protocol, the replay
flags, the fidelity caveat) and [`HIL_PLANT.md`](HIL_PLANT.md) (the simulated
plant, which replay bypasses).

---

## 1. Purpose

The synthetic scenarios (`steady`, `step-load`, `sag`, `comm-loss`, `drive`) probe
the firmware with *invented* stimuli. This suite probes it with **history**: every
rail voltage, source current and velocity sample that the board actually saw during
a recorded bench run is streamed back at it, at true wall-clock pacing.

**What this half actually is** (relabelled 2026-08-30, `HIL Results/hil_report_20260830_181426/HIL_FINDINGS.md`
"Replay half"): a **bring-up + fault-decision regression harness**. Replay mode
constructs no commander, so *no replayed run ever reaches State 2* — the board
brings up, sits in Idle, and the commanded current is `0.000 A` for the whole run.
Every current-shape check is therefore vacuously true on a healthy board. They are
retained as **"no spurious command"** assertions — the firmware must not drive on a
stimulus it was never commanded to follow — and are annotated as such rather than
advertised as controller coverage. What the half genuinely tests is: *does the
fw v22+ staged bring-up complete on this stimulus, and does the fault machinery
make the right latch decision on it?*

That buys two things the synthetic scenarios cannot:

1. **Regression against real incidents.** A recorded VESC dead window, a handoff bus
   sag, an estimator basin, a 90-episode saturation run — each becomes a repeatable
   stimulus that any future firmware build must survive, on a bare Teensy, without
   the rig.
2. **A defect archive that keeps working.** Old logs recorded on defective firmware
   are the only samples of those failure stimuli that will ever exist. Replaying them
   at the modern build is how we prove the failure mode is gone.

---

## 2. Policy: conformance vs deviation

The mode of an entry is decided **by the firmware version the log was recorded on**,
relative to the currently flashed target — **fw v21 = the fw v18 control law + the
v19 share handoff slew + v20/v21 observability/HIL**. v19–v21 change no control
semantics except the v19 share handoff slew.

| Mode | When | What the firmware must do |
|---|---|---|
| **conformance** | The recording firmware's control semantics match the target, or the delta does not matter for the property under test | The live response is expected to be *well-behaved* on the recorded stimulus: no faults, bounded command, no windup, no limit cycle |
| **deviation** | The log was recorded on older firmware with a **known defect** | The modern firmware must **not reproduce** the recorded failure mode |

**The pre-v18 conformance caveat.** fw v18 changed both the wheel (120-slot →
90-slot, so every pre-v18 `v_act` was computed on physically different geometry)
and the control law (general-Hanus anti-windup + re-synthesis). For any entry with
`fw_version < 18`, *conformance means* **stable, fault-free and free of limit
cycling** — **it does not mean the live command matches the recorded `I_cmd`.**
Divergence there is expected and is not a defect. The per-version deltas are
encoded as `FW_DELTA_NOTES` in `hil_replay_suite.py` and are emitted into every
evaluation's `notes`.

---

## 3. Open-loop caveats — read before interpreting any result

Replay is **open loop** (see `HIL_MODE.md` §"Fidelity caveat"). Concretely:

- **The plant integrator is bypassed.** The firmware's commands do not influence
  the replayed trajectory. Command +12 A and `v_actual` keeps doing exactly what
  the bench did. Replay validates **responses** (state transitions, sequencing,
  fault latching, command shape at an operating point), never trajectories.
- **The encoder and its estimator are bypassed.** `v_actual` is *injected* in
  engineering units. Every estimator fix — the fw v12 edge-period estimator, the
  v13 adaptive filter, the v15 fractional-pitch ledger, the v17 TOCTOU fix — is
  therefore **not testable by replay**. A log recorded inside an estimator basin
  replays as *the corrupted velocity the firmware was fed*, which is a perfectly
  good stimulus for the controller and no test at all of the estimator.
- **The charger is not replayed.** No BLG record format v1–v7 carries a charge
  current or an Ag105 status byte, so `I_charge` injects as `0.0 A` and
  `ag105_status` as `0x00` (GENSTAT *Battery Disconnect*) for every entry.
- **`v_setpoint` is not replayable.** The injection frame carries sensors only; the
  22-byte Pi command packet is a separate path. The board sits at whatever setpoint
  it was left at (0 in Idle). Anything that depends on a commanded setpoint — the
  ML0144 `v_sp ≠ 0` relay, for instance — is out of reach; see that entry for the
  honest reduced claim.
- **Pre-v18 logs are a different wheel and a different law** (§2).

### 3a. Synthetic bring-up preamble (2026-08-30)

> **Per-entry opt-out: `skip_preamble`.** An entry whose point is that bring-up
> *fails* must replay raw — see ML0217 in §4b. For such an entry the preamble bound
> is **0.0 s**, timestamps are unshifted (sim time = log time) and `replay_rec`
> starts at 0. Everything that needs the bound resolves it through
> `entry_preamble_s(entry)`; nothing hard-codes `REPLAY_PREAMBLE_S`.
>
> **Load-bearing ordering, asserted at import:**
> `REPLAY_PREAMBLE_S >= WARM_RESET_GRACE_S`. If the preamble were shorter, the first
> `(grace − preamble)` seconds of every recorded trajectory would fall inside the
> excluded fault window (§3c) and a real early fault would vanish with no symptom.
> Shortening the preamble without re-deriving the grace bound trips the assertion.

Every replay is preceded by **`REPLAY_PREAMBLE_S` = 2.5 s of healthy nominal rails**
(`tools/hil_plant_sim.py`) before the recorded trajectory starts. fw v22+ runs a
closed-loop staged bring-up (P0-P3) at the start of every HIL run and it needs live
rails to complete; a recorded log begins wherever the operator pressed record, which
for ML0217 is a dark bus and for the whole legacy UV group is a run already in
progress. Consequences, all load-bearing when reading a result:

- **Every time in a replay CSV or check detail is SIM-relative.** Log time =
  `sim time − 2.5 s`. Preamble rows carry `replay_rec = -1`.
- **The preamble does not test bring-up dynamics.** The bus is presented already in
  regulation, so P0/P1/P2 pass on their minimum dwells. It exists only so the
  recorded trajectory is delivered to a board in Idle. Bring-up dynamics are the
  `bringup` *scenario's* job.
- **2.5 s is derived, not round:** it must exceed `WARM_RESET_GRACE_S` (2.0 s, below)
  so no part of the recorded trajectory falls inside the excluded window, and it must
  exceed the measured warm-reset recovery plus bring-up (~0.62 s).

### 3b. Absent-rail substitution (2026-08-30)

BLG v1/v2 records carry **no `V_fc`, `V_batt` or `V_rgn` field at all**. Injecting
`0.0 V` — the old behaviour — handed the firmware a dark board: the staged bring-up's
P3 gate reads `V_rgn` as its motor-node proxy, so it never tracked `V_bus` and both
v1/v2 entries latched `FAULT_MOT_HOTPLUG` at ~1.09 s, long before the recorded
collapse arrived. The zeros were an artefact of the record format, not a property of
the run. Absent fields are now supplied as:

| Field | Substituted with |
|---|---|
| `V_fc` | 12.9 V — healthy nominal (the `steady` scenario settles at 12.9156 V) |
| `V_batt` | 7.9 V — 2S pack mid-charge |
| `V_chg` | 0.0 V — **not** substituted; an unpowered charger input is the honest value |
| `V_rgn` | **derived**: the injected `V_bus` while the board's own `MOT_PWR` bit is set, else 0 V (fw v22 topology — the RGN-V divider sits on V-MOT) |

The `V_rgn` derivation ignores the ~35 mV RT1987 forward drop and the motor node's
own RC; no check here resolves either.

### 3b-bis. Injected `I_fc` clamp — `i_fc_clamp_a` (2026-08-30)

Two entries (**TP0010, TP0053**) carry a per-entry clamp on the injected FC current,
plumbed to the simulator as `--replay-i-fc-clamp`. It is a **deliberate modification
of a recorded trajectory** and is declared at every scoring site: the simulator's
start-up banner, the entry `why`, the evaluation notes, and here.

Why it exists — measured 2026-08-30 by replaying the firmware's own filters over the
decoded logs:

| Log | recorded `I_fc` peak | first sample > 1.4 A | UV dwell qualifies at | gap |
|---|---|---|---|---|
| TP0010 | 3.223 A (230 % of limit) | log t = 4.770 s | 4.796 s | OC is **26 ms** early |
| TP0053 | 2.958 A (211 %) | log t = 3.929 s | 4.462 s | OC is **533 ms** early |

Replayed raw at a production build the board latches `OC_FC` *first*, and **State 99
freezes `fault_flags`** — so `UV_BUS` can never be set afterwards and the UV-latch
regression these two logs exist for is destroyed by a fault that is itself correct.

The clamp is honest under **operator ruling (a)**: those currents came from a DC
bench supply standing in for the H-20, which could never source them. Clamping to
**1.3 A** (7 % under the limit) removes a stimulus the real hardware cannot produce
and delivers the bus collapse the entries were kept for. Verified post-clamp: no
sample can reach 1.4 A (so `OC_FC` is unreachable by construction) and the UV dwell
still qualifies — peak dwell 20.7 ms (TP0010) and 20.6 ms (TP0053) against the 20.0 ms
latch, because the clamp touches `I_fc` only and the UV filter reads `V_bus` alone.

**No conclusion about FC current may be drawn from these two runs.**

### 3c. Grace window — inherited settle latch (2026-08-30)

Every fault check judges observations at **`t ≥ WARM_RESET_GRACE_S` (2.0 s)** only.
A replay CSV carries the same inherited latch a scenario CSV does: from fw v23 the
board warm-resets out of the previous run's `ERR_HIL_STALE` latch at `t ≈ 0.5 s`, so a
run that had nothing to do with it opens showing `0x8010` (or `0x8011` / `0xA010` when
its predecessor latched something of its own). **19 of the 26 replays in the first
fw v23 suite pass failed on nothing but that.** The bound is imported from
`hil_plant_sim` so this module and `run_hil_suite.py` cannot diverge. It excludes an
observation *window*, never a bit value: a board that stays latched keeps reporting
its flags after the bound and still fails. The excluded bits are named in the check
detail as "carried-in".

A fault that latches *before* the bound and **persists** is still scored: the filter
ORs over samples, not over edges, and State 99 is latched while the simulator keeps
streaming (no run boundary, so the fw v23 warm recovery never arms). ML0217's
`INIT_FAIL` at ~0.3 s is the standing example. Because the time a check prints is
necessarily the first *post-grace* observation, the whole-run first observation is
reported beside it whenever the two differ.

**The grace bound and the preamble bound are different questions and are never
interchangeable.** Grace is about the **board** (whose latch is this?); the preamble
bound is about the **stimulus** (were these rails recorded, or synthesized here?).
Two consequences:

- **Stimulus guards** (§4c) filter from the *preamble* bound. The preamble holds a
  healthy 15.95 V, which would otherwise ARM the UV filter on rails this harness
  invented rather than on anything the log recorded.
- **Rate-based checks** (`no_rail_limit_cycle`) compute over the recorded window
  only. It is the one check whose verdict is a rate, so preamble seconds would go
  straight into its denominator — 2.5 s of preamble on ML0137's ~4 s log would
  understate the alternation rate by ~1.6× and could pass a genuine limit cycle. The
  other command checks are extremal (`bounded_current`, `no_sustained_rail`) or
  per-episode (`returns_off_rail`); a quiet preamble adds no episodes and cannot
  lower a maximum, so they are unaffected.

### 3d. Bring-up gate (2026-08-30)

Before any of an entry's own checks run, the board must have reported **mainState 1
(Idle) within `BRINGUP_DEADLINE_S` = 3.5 s**. If it has not, the entry reports one
honest failure — *"the board never reported Idle — BRING-UP FAILED"*, with the last
observed state and the post-grace fault union — and the entry's checks are **not
run**. Without the gate, a board that never came up fails every check for one single
reason and the report reads as N independent findings. An entry whose *point* is a
failing bring-up sets `skip_bringup_gate` (only ML0217 does).

---

## 4. The suite

26 entries: **11 conformance, 15 deviation**. `*` = provisional. Check names are the
declarative kinds in `hil_replay_suite.py` (`CHECK_KINDS`). Every entry additionally
carries the implicit `bringup_reached_idle` gate (3d).

> **Reclassified 2026-08-30 (5 entries).** ML0203, ML0165, ML0169 and WP0097 moved
> **conformance -> deviation expecting `OC_FC`**, and ML0217 moved **conformance ->
> deviation expecting `INIT_FAIL`**. Rationale in 4a/4b.

### Conformance — current wheel and control law

| Log | fw | BLG | Classification | Why | Checks |
|---|---|---|---|---|---|
| YP0196 | 18 | 6 | `'Y'` combined drive-cycle + power-share profile | Both loops' stimulus together on the current law | `no_fault`, `bounded_current` |
| WP0197 | 18 | 6 | `'W'` combined current + power-share profile | The current-axis twin of `'Y'` — encoder-less share stimulus | `no_fault`, `bounded_current` |
| TP0210 * | 19 | 6 | `'T'` share sweep, handoff-slew build | Most recent share stimulus; nearest to the flashed target | `no_fault`, `bounded_current` |
| YP0214 * | 19 | 6 | `'Y'` combined profile on fw v19 | Combined-profile stimulus with the handoff slew in the recording | `no_fault`, `bounded_current` |

### Conformance — older wheel/law (stability conformance only, §2)

| Log | fw | BLG | Classification | Why | Checks |
|---|---|---|---|---|---|
| ML0146 | 14 | 5 | clean `'V'` step, 120-slot wheel | First-flash fw v14 clean baseline. **Not a trace-match case** | `no_fault`, `bounded_current`, `no_rail_limit_cycle` |
| ML0149 | 14 | 5 | clean `'V'` step, higher setpoint | Second clean fw v14 point, same meaning | `no_fault`, `bounded_current`, `no_rail_limit_cycle` |
| TP0170 | 16 | 6 | share sweep, `share_sp = 0.5` | Balanced-share operating point of the first genuine closed-loop share dataset | `no_fault`, `bounded_current` |
| TP0176 | 16 | 6 | share sweep at the FC rail (FC-only 43–45 % of the run) | The share-rail extreme: one source carries the bus for a long stretch | `no_fault`, `bounded_current` |
| YP0152 | 14 | 5 | first `'Y'` profile on the Youla drive controller | Combined-profile representative from the fw v14 era | `no_fault`, `bounded_current` |
| **ML0151** | 14 | 5 | **H6 flagship** — 56 s stepladder with the ~428 ms VESC dead window, the drag step-change and ~90 saturation episodes | Richest recorded incident in the archive; many saturation entries/exits back to back is exactly the class the fw v18 general-Hanus fix targets | `no_fault`, `bounded_current`, `returns_off_rail`, `no_rail_limit_cycle` |
| TP0178 | 16 | 6 | handoff bus sag to 12.15 V — 0.15 V above `LIMIT_V_BUS_MIN`, 10 ms dwell (half the 20 ms latch) | The **negative** UV case: the recorded dip must *not* latch UV_BUS. Pairs with the UV pair (TP0010/TP0053), which must | `no_fault`, `fault_not_latched(UV_BUS)` |

### Deviation — the modern firmware must not reproduce the defect

| Log | fw | BLG | Recorded defect | Check + caveat |
|---|---|---|---|---|
| ML0137 | 11 | 5 | boxcar-estimator ±12 A rail-to-rail limit cycle, 2.3–2.6 Hz | `no_rail_limit_cycle`, `bounded_current`, `no_fault`. **Caveat:** replay injects the *recorded* `v_act`, so this tests the controller's reaction to that stimulus, **not** the estimator fix that actually removed the cycle |
| ML0140 | 12 | 5 | estimator blind holds, 120–560 ms, under direction dither | `no_fault`, `bounded_current`, `returns_off_rail` — a long frozen-velocity stimulus |
| ML0144 | 12 | 5 | `v_sp = 0` relay: 90 % rail bang-bang closing the loop below the estimator floor | `no_fault`, `near_zero_current`. **Honest limit:** replay cannot set `v_setpoint`, so the `v_sp ≠ 0` relay is unreachable. What *is* checkable, and what is checked: with `v_sp = 0` and this log's `v_actual` injected, the firmware commands ~0 A (the `V_SP_ZERO_THRESH` behaviour) instead of bang-banging |
| ML0153 | 14 | 5 | T/2 basin — `v_act` corrupted to ~2× true | `no_fault`, `bounded_current`. **Caveat:** the basin fix is in the estimator, which replay bypasses — not testable open-loop |
| ML0164 | 16 | 6 | x2 **rounding** basin, locked breakaway-to-stop | `no_fault`, `bounded_current`. Same caveat |
| TP0171 | 16 | 6 | reset re-seeded *into* the x2 basin (~15 ms recovery) | `no_fault`, `bounded_current`. Same caveat |
| YP0166 | 16 | 6 | mid-run `v = 0` injection at a true 1.49 m/s → ±12 A rail pair within 12 ms (the fw v17 TOCTOU race) | `no_fault`, `bounded_current`, `returns_off_rail` — a full-scale velocity step straight into the ~454 A/(m/s) LF gain must give a **bounded** transient that releases |
| TP0201 | 18 | 6 | share-rail handoff gap, bus 15.86 → 12.185 V | `no_fault`, `fault_not_latched(UV_BUS)` — 0.185 V above the limit for ~10 ms, inside the 20 ms dwell, so no latch. **Caveat:** the fw v19 handoff *slew* that mitigates the gap acts on the plant, which replay bypasses; only the fault decision is exercisable |
| TP0010 | — (pre-versioning) | 1 | bus collapse the old firmware died on **without faulting** | `fault_latched(UV_BUS)` — the fw v5 leaky-dwell filter must latch. That is the whole point of the rework |
| TP0053 | 4 | 2 | repetitive source-commutation dropout (~9 ms under / ~51 ms over per ~60 ms cycle) that **evaded** the fw v4 window filter | `fault_latched(UV_BUS)` — the exact case the dwell integrator was designed for: net +6.45 ms per cycle, so it must latch within a few cycles |

### 4a. Deviation — the OC_FC reclassification (operator ruling (a), 2026-08-30)

| Log | fw | BLG | Recorded I_fc peak | Check |
|---|---|---|---|---|
| ML0203 | 18 | 6 | 2.11 A | `fault_latched(OC_FC)` + `require_stimulus`, `bounded_current` |
| ML0165 | 16 | 6 | 1.52 A | same |
| ML0169 | 16 | 6 | 1.88 A | same |
| WP0097 | 5 | 3 | **3.60 A** (archive maximum) | same — but see the timing caveat below |

These four were classified "clean" from their **bench** behaviour. They were recorded
with **DC bench supplies standing in for the H-20 fuel cell**, and `BENCH_TEST`
compiles `FAULT_OC_FC` out — so their recorded `I_fc` routinely exceeded
`LIMIT_I_FC_MAX` (1.4 A) with nothing on the board to notice. Replayed at a
production, OC-live build, **an `OC_FC` latch is correct hardware replication**:
operator ruling (a) of 2026-08-30 is explicit that the 1.4 A limit stays, being
already slightly above the H-20's theoretical maximum, and that HIL replicates the
actual hardware. Scoring these entries "must not fault" asserted the opposite of the
hardware.

**WP0097 is tight in TIME (L6-class caveat, measured).** Its `I_fc` crosses 1.4 A
only at log t = 16.964 s and the log **ends at 17.006 s** — the whole OC stimulus is
the last **40 ms** of the recording. There is no margin in current (the peak is 2.6×
the limit) but almost none in time: anything that shortens the replay, shifts its time
base or trims the tail pushes the crossing off the end and the entry becomes an
`INCONCLUSIVE` stimulus report. That report is the *designed* failure mode
(`require_stimulus`), so it degrades loudly — but treat any timing change here as
fragile.

**ML0151 is a knife-edge conformance pass — do not move it.** Its recorded `I_fc`
peaks at **1.354 A, 96.7 % of the 1.4 A limit** (measured 2026-08-30). It stays a
conformance entry because it does not *cross*, and that is deliberate. But it sits
46 mA from flipping class: any downward re-derivation of `LIMIT_I_FC_MAX`, or any
change to how the injected `I_fc` is scaled, turns its `no_fault` check into a FAIL
for a reason unrelated to the saturation behaviour it exists to test. **Check this
number first if ML0151 ever starts failing.**

**What the reclassification costs, stated plainly:** ML0169 was the suite's
saturation-endurance case. Once `OC_FC` latches the board is in State 99, so
`returns_off_rail` is meaningless there and the check is dropped. **Saturation
endurance now has no replay representative.** Restoring it needs a recorded run whose
`I_fc` stays under 1.4 A throughout — a candidate for the next log census.

### 4b. Deviation — ML0217, dark-bus (2026-08-30)

| Log | fw | BLG | Recorded defect | Check |
|---|---|---|---|---|
| ML0217 * | 19 | 6 | **recorded with a dark bus** — measured `V_bus` max **0.35 V** over all 38 s | `fault_latched(INIT_FAIL)`, `bounded_current`; `skip_bringup_gate`, `skip_preamble` |

It was never the "duration/soak case" it was catalogued as. Replayed, the staged
bring-up cannot pass P1 and times out at `BUS_CHARGE_TIMEOUT_MS` into
`FAULT_INIT_FAIL` (`.ino:8784-8786`) — correct firmware behaviour, and now the
asserted expectation. It is the one entry exempt from the bring-up gate (3d),
necessarily: a failing bring-up is the point.

**This entry replays RAW (`skip_preamble`).** The first version of it kept the
synthetic preamble, and that made its own expectation *unreachable*: the board
completed bring-up on the healthy preamble rails and then met the dark trajectory as
a **running** board, which latches `UV_BUS` at ~t = 2.52 s. `FAULT_INIT_FAIL` is
raised only by `busBringupTick()`'s phase timeouts (`.ino:8762-8765`, `:8784-8786`),
i.e. only from State 0's bring-up machine — a running board can never produce it.
Replaying raw restores the genuine cold-boot-into-darkness test: P0's gate never sees
the bus reach `V_PRECHARGE_MIN`, and `PRECHARGE_TIMEOUT_MS` (300 ms, `.ino:1466`)
latches `INIT_FAIL`. ML0217 is a modern BLG v6 with every rail field present, so it
needs no absent-rail substitution and loses nothing by skipping the preamble.

**Observability of the latch (verified).** It fires ~300 ms after bring-up starts,
*before* the 2.0 s grace bound — and is still scored, because State 99 is latched and
the simulator keeps streaming, so `fault_flags` reads `0xA000` on every post-grace
sample (§3c). The check additionally prints the whole-run first-observation time, so
the ~0.3 s event is not misreported as a 2.0 s one.

### 4c. `require_stimulus` — the stimulus guards

The UV pair (TP0010, TP0053) and all four OC entries above use `require_stimulus`:
before scoring the firmware, the **injected** stimulus is checked against the
firmware's own latch criterion for that bit.

- **`FAULT_UV_BUS`** — the `V_bus` series is run through the firmware's *own*
  leaky-dwell integrator (`LIMIT_V_BUS_MIN` 12.0 V, `UV_BUS_DWELL_LATCH_MS` 20 ms,
  `UV_BUS_DWELL_LEAK` 0.05, `UV_BUS_DWELL_DT_CAP_MS` 5 ms, armed once
  `V_BUS_CHARGED_THRESH` 13.5 V is reached).
- **`FAULT_OC_FC`** — the `I_fc` series must actually exceed `LIMIT_I_FC_MAX` 1.4 A.
  The firmware's OC check is a single-sample comparison with no dwell filter, so this
  mirrors it exactly.

Both guards filter from the **preamble** bound, not the grace bound (§3c): a guard
asks whether the *recorded log* contains the stimulus, and preamble rails were
synthesized by this harness. On a `skip_preamble` entry the bound is 0.0.

The clamp on TP0010/TP0053 (§3b-bis) does **not** weaken their guard: it touches
`I_fc` only, while `_uv_stimulus_qualifies()` reads `V_bus`.

If the stimulus would not qualify, the check fails **loudly as inconclusive** rather
than excusing the firmware — a suite entry whose stimulus stopped qualifying is a
suite bug that must be seen. Any other bit with `require_stimulus` set is reported as
a suite authoring error rather than silently skipping the guard.

---

## 5. Exclusions

| Excluded | Why |
|---|---|
| ML0182, ML0183 | Encoder-diagnostic runs on a **defective** 120-slot thin-tooth wheel (~92 % blind). The stimulus characterises a sensor mount that no longer exists |
| ML0135 | Obsolete PI control law plus a reverse-direction diagnostic — neither the law nor the manoeuvre maps onto anything the current build does |
| The fw v3–v8 bulk campaigns (TP0014–TP0134, WP0039–WP0124, PS000x, TEST0001) | Superseded control law *and* superseded fault logic; replaying dozens adds runtime, not coverage. Three representatives are kept: TP0010 and TP0053 as the **UV pair** (two different collapse shapes), plus WP0097 — retired from that group on 2026-08-30 (its dip gives only ~18 ms of dwell against the 20 ms latch and the log ends mid-dip) and now the archive's largest `OC_FC` stimulus, 3.60 A |
| Hand-spin / manual-wheel diagnostics generally | The stimulus is an operator's hand, not a control scenario: no repeatable property to assert |

The same list is mirrored as `REPLAY_EXCLUSIONS` in `hil_replay_suite.py` so the
reasoning travels with the code.

---

## 6. Firmware constants the checks are pinned to

Every number below was read from source, not from memory. Re-verify if the firmware
moves.

| Constant | Value | Source |
|---|---|---|
| `MOTOR_I_CMD_MAX` | 12.0 A | `teensy_controller/teensy_controller.ino:2048` (line 2052 `static_assert`s it against `DRIVE_CTRL_I_MAX`) |
| `FAULT_UV_BUS` | `0x0100` | `teensy_controller.ino:1155` |
| `LIMIT_V_BUS_MIN` | 12.0 V | `teensy_controller.ino:1258` |
| `UV_BUS_DWELL_LATCH_MS` | 20.0 ms | `teensy_controller.ino:1284` |
| `UV_BUS_DWELL_LEAK` | 0.05 | `teensy_controller.ino:1285` |
| `UV_BUS_DWELL_DT_CAP_MS` | 5.0 ms | `teensy_controller.ino:1288` |
| `V_BUS_CHARGED_THRESH` | 13.5 V (`V_BUS_NOMINAL − 2.5`) | `teensy_controller.ino:1363` |
| `LIMIT_I_FC_MAX` | 1.4 A (bus-side) | `teensy_controller.ino:1300`. **Stays 1.4 A** — operator ruling (a), 2026-08-30 |
| `FAULT_OC_FC` / `FAULT_INIT_FAIL` | `0x0001` / `0x2000` | `teensy_controller.ino:1149`, `:1255` |
| `MOT_CONNECT_TIMEOUT_MS` | 500 ms | `teensy_controller.ino:1473` |
| Full fault bitmask | `0x0001`–`0x8000` | `teensy_controller.ino:1149–1166`; `FAULT_HIL_LINK` aliases `FAULT_PI_TIMEOUT` (`:1168`) |

Suite-policy thresholds (not firmware) — `SUSTAINED_RAIL_S` 1.0 s,
`LIMIT_CYCLE_ALT_PER_S` 2.0/s, `OFF_RAIL_LEVEL_A` 10.0 A / `OFF_RAIL_WITHIN_S` 1.0 s,
`NEAR_ZERO_I_A` 0.5 A, `RAIL_LEVEL_A` 11.9 A, `BRINGUP_DEADLINE_S` 3.5 s — are named
constants in the module with their rationale at the definition. `REPLAY_GRACE_S` and
`REPLAY_PREAMBLE_S` are **imported** from `hil_plant_sim` rather than redefined, so the
two modules cannot drift apart.

---

## 7. Running it

Running the board belongs to the wrapper; this module lists the suite and scores an
existing CSV.

```
# what is in the suite
python3 tools/hil_replay_suite.py --list

# every .BLG present, headers agree with the table
python3 tools/hil_replay_suite.py --verify-logs

# the argv to hand hil_plant_sim for one entry
python3 tools/hil_replay_suite.py --argv-for ML0151 --csv-dir runs/
python3 tools/hil_plant_sim.py --teensy-ip 192.168.1.50 \
        $(python3 tools/hil_replay_suite.py --argv-for ML0151 --csv-dir runs/)

# score the CSV that produced
python3 tools/hil_replay_suite.py --evaluate ML0151 runs/hil_replay_ML0151.csv
```

The emitted argv carries **`--force`**, because the CSV name is derived from the log
and is therefore identical on every replay of the same entry: `hil_plant_sim.py`
refuses an explicit `--csv` whose CSV or either sidecar (`.meta.json`,
`.events.jsonl`) already exists, so without it the second replay of an entry into the
same `--csv-dir` would exit 2 instead of running. **Re-running an entry into the same
directory therefore overwrites that entry's previous artifacts** — point `--csv-dir`
somewhere else to keep them.

`evaluate_replay_csv(entry, csv_path)` returns
`{"log", "mode", "passed", "checks": [{"name", "passed", "detail"}], "notes": [...]}`;
`--json` prints it verbatim. A missing or unparseable CSV, an unknown check kind, or a
check that raises are all reported as **failures**, never propagated.

Observation columns are blank on every tick before the board's first observation
frame; each check drops blanks per-series, and a CSV with *no* observation frames at
all fails every check with an explicit "the board never answered" note rather than
passing vacuously.

---

## 8. How to add a log

1. **Classify it.** What is the run (profile type, setpoints), and what is the one
   property worth asserting? If you cannot name the property, it is a diagnostic
   log, not a suite entry — leave it out and say why in §5.
2. **Pick the mode** by the recording firmware version (§2). Was there a known
   defect on that build that this log exhibits? → *deviation*. Otherwise →
   *conformance*, and if `fw_version < 18` say explicitly in `why` that conformance
   means stability, not a trace match.
3. **Read the header, don't guess.** `python3 tools/hil_replay_suite.py --verify-logs`
   after adding the entry — it reads the BLG magic, the format version (byte 4) and
   `fw_version` (u16 at offset 18, absent in BLG v1) and refuses to agree with a
   table that disagrees with the file.
4. **Define the checks** from the existing kinds where possible: `no_fault`,
   `fault_latched`, `fault_not_latched`, `bounded_current`, `no_sustained_rail`,
   `no_rail_limit_cycle`, `returns_off_rail`, `near_zero_current`. A new kind is a
   small pure `(ReplayCsv, spec) -> (bool, str)` function plus a `CHECK_KINDS` entry
   — and a named constant with its rationale for any threshold it introduces.
4b. **Check the recorded `I_fc` against `LIMIT_I_FC_MAX` (1.4 A) before calling a log
   "clean".** Four entries were miscatalogued for exactly this reason (§4a): a bench
   run recorded with a DC supply in place of the fuel cell, under a `BENCH_TEST`
   build with the OC check compiled out, shows no fault while genuinely exceeding
   the limit. If the recorded peak crosses 1.4 A the entry is a **deviation**
   expecting `fault_latched(OC_FC)` with `require_stimulus`, not a conformance entry.
4c. **Optional entry fields.**
   - `skip_bringup_gate: True` — exempt from the Idle-within-3.5 s gate (§3d). Only
     for an entry whose point is that bring-up fails.
   - `skip_preamble: True` — replay the log raw, unshifted. Pairs with
     `skip_bringup_gate`: a State-0-only fault (`INIT_FAIL`) is unreachable if the
     board has already come up on synthetic rails. Emits `--replay-no-preamble`.
   - `i_fc_clamp_a: X` — clamp the injected FC current (§3b-bis). A **deliberate
     modification of a recorded trajectory**: use it only where an unphysical
     recorded current (a DC bench supply standing in for the fuel cell) would
     pre-empt the stimulus the entry exists for, and declare it in `why`. Emits
     `--replay-i-fc-clamp`.
   - `require_stimulus` on a `fault_latched` check is supported for `FAULT_UV_BUS`
     and `FAULT_OC_FC` (§4c); any other bit is reported as an authoring error rather
     than silently unguarded.

   Both stimulus modifiers are mirrored by `build_sim_argv()`, so a hand-run replay
   injects exactly what a suite-run one does.
5. **Write the open-loop caveat.** If the defect being guarded lives in the estimator,
   the plant or a commanded setpoint, replay cannot test it. Say so in `why` (§3
   lists the classes). An entry that overclaims is worse than no entry.
6. **Add the `REPLAY_SUITE` entry** in `tools/hil_replay_suite.py`, and **update
   §4 of this document** in the same change.
7. If the recording firmware version is new to `FW_DELTA_NOTES`, add its one-line
   "what differs vs v21 that matters".
