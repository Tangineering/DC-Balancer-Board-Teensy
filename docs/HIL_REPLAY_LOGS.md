# HIL replay suite — log selection

**Maintained document.** This is the curated list of bench logs (`logs/*.BLG`)
that are replayed at the firmware through `tools/hil_plant_sim.py --replay` as a
HIL scenario class, and the reason each one is in (or out of) the suite. It is
kept in lockstep with `REPLAY_SUITE` in `tools/hil_replay_suite.py` — **if you add
a log to one, add it to the other** (checklist at the bottom).

> **One entry is SYNTHETIC — `SY0001` (§3f).** Every other log in the suite is a
> real recording written by the firmware's own SD logger. `SY0001.BLG` is
> authored by `tools/gen_fu4_replay_log.py`. The `SY` prefix marks that, and no
> value in it is a measurement.

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

**Vacuous checks are now tagged, and counted.** Measured over the 26-entry campaign
`20260830_203006`: **32 of 79 checks were vacuous** — `bounded_current` (24),
`no_rail_limit_cycle` (4), `returns_off_rail` (3), `near_zero_current` (1) — because
`current` is identically 0 A on every run. Four entries (ML0137, ML0140, ML0144,
YP0166) carry *no* evidence about their own classification for this reason. A check
whose command series is all-zero now carries a `**(vacuous — no commander …)**`
marker in its detail, and each entry reports a substantive-vs-total count, so a green
entry cannot read stronger than it is. The condition is measured per run, so the tag
disappears by itself the day a commander is added.

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
relative to `TARGET_FW_VERSION` (25) — the bench board is currently **flashed with
fw v24**; fw v25 is shipped but pending its first flash (see `WORK_QUEUE.md` §0).
`TARGET_FW_VERSION` = fw v23 (the fw v18 control law + the v19 share handoff slew +
v20/v21 observability/HIL + the v22/v23 HIL sequencing and any-fault run-boundary
recovery) **plus the v24 and v25 deltas**: v24 adds the dynamic Ag105 MPPT reg-0x02
threshold, and v25 adds the r-based bus-cutoff guard fix (both `applyShareRatio()`
branches) and grows the HIL observation frame 17 → 18 bytes (`error_code`
appended). **Neither v24 nor v25 changes control semantics for replay purposes** —
v19–v25 change no control semantics except the v19 share handoff slew.

`TARGET_FW_VERSION` was bumped **21 → 23** on 2026-08-30c: it had never been raised
for v22 or v23, so every report header claimed "fw v21" while the whole replay half
in fact depends on the v22 staged bring-up completing and on the v23 between-run
recovery. It was bumped **23 → 24** and then **24 → 25** on 2026-09-01, in step with
the corresponding flash/ship events (see §2a below). `COMPARABLE_FW_MIN` (18) is a
**separate** constant and is unchanged, so no entry's conformance/deviation
classification moves; the only consumer of `TARGET_FW_VERSION` is the report
header's firmware expectation.

### 2a. Version bump records

- **23 → 24 (2026-09-01):** fw v24 (dynamic Ag105 MPPT reg-0x02 threshold) flashed
  to the bench board; observability/threshold-tracking change only, no control-law
  change, so no replay entry moved mode.
- **24 → 25 (2026-09-01):** fw v25 shipped (commits b262e98 + 89fbad6): the r-based
  bus-cutoff guard fix and the 17 → 18 byte observation frame (`error_code` at
  offset 16). Pending its first flash. Neither change touches replayed control
  semantics — the guard fix closes a fault-window edge case the replay corpus does
  not stimulate, and the frame growth is HIL-tooling-only.

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
- **`v_setpoint` reaches the board only on an entry that opts in** (`Cmds` column,
  §3e below). Without it the board sits at whatever setpoint it was left at (0 in
  Idle) and every current-shape check is tagged **NOT EXERCISED**. With it the
  recorded `v_sp`/`share_sp` are replayed as Pi command packets, the board reaches
  Run, and those checks become real — but the **plant** stays open loop either
  way, so it is still a reaction test, never a tracking test.
- **Pre-v18 logs are a different wheel and a different law** (§2).
- **OC faults latch on the INJECTED current regardless of switch topology.** The
  injected rail currents do not depend on the board's own switch state, so an OC
  fault can latch on a current that could not physically have flowed through the
  path the board actually had open. Clean as of campaign `20260831_000518` —
  ML0203's `OC_FC` latch had `FC_BUS` closed — but check `switch_state` at the
  latch time before reading a replay OC result as a hardware statement.
- **The replay half cannot exercise `share_cut_load_hazard`.** That tripwire scores
  `sw_ring` events emitted by the hi-fi electrical engine, and a replay run drives the
  rails from the log and constructs no engine at all — so the check is structurally
  unreachable here and its absence from a replay verdict is not coverage. The share-cut
  guards of fw v25 are exercised only by the scenario half.
- **`no_sustained_rail` is deliberately not used in this half.** It asserts that
  no rail episode outlasts 1.0 s, which is a windup symptom *on a closed loop*.
  Open loop, a correct controller facing a standing error is supposed to stay on
  the rail as long as the recorded trajectory holds that error in front of it
  (YP0166 measured 1.217 s, correctly). Applying it here would fail correct
  behaviour, and inflating the threshold until it passed would leave it asserting
  nothing. `returns_off_rail` covers the real question — does the command
  *release* once the error goes away.

### 3a. Synthetic bring-up preamble (2026-08-30)

> **`skip_preamble` entries must declare `persistent_fault: True`** — asserted at
> import (`_assert_skip_preamble_entries()`), because the global assertion below
> buys such an entry nothing. With no preamble the recorded stimulus starts at
> t = 0, so its first `WARM_RESET_GRACE_S` seconds sit inside the excluded
> fault-scoring window by construction, and **only a fault that PERSISTS past the
> bound is scorable at all**. ML0217 is safe for exactly that reason and no other:
> `INIT_FAIL` latches at ~0.3 s and holds for the remaining 37.6 s. A future entry
> whose expected fault were transient and early would be judged on an empty window
> and pass on nothing. The guard also requires at least one `fault_latched` check,
> since a latch is what makes persistence true (State 99 does not clear).
>
> **Per-entry opt-out: `skip_preamble`.** An entry whose point is that bring-up
> *fails* must replay raw — see ML0217 in §4b. For such an entry the preamble bound
> is **0.0 s**, timestamps are unshifted (sim time = log time) and `replay_rec`
> starts at 0. Everything that needs the bound resolves it through
> `entry_preamble_s(entry)`; nothing hard-codes `REPLAY_PREAMBLE_S`.
>
> **Load-bearing ordering, asserted at import (global case):**
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

### 3b-ter. Injected `I_batt` clamp — `i_bt_clamp_a` (2026-09-01)

**TP0010 alone** additionally carries a clamp on the injected BT current
(`--replay-i-bt-clamp`), for exactly the reason the FC clamp above exists and under the
same operator ruling (a). Measured on the decoded logs:

| Log | recorded \|`I_batt`\| peak | vs `LIMIT_I_BT_MAX` 3.0 A | clamp |
|---|---|---|---|
| TP0010 | **3.586 A** | 120 % of limit | **2.8 A** (6.7 % under, the same fractional margin the FC clamp takes) |
| TP0053 | 2.345 A | 78 % — under the limit | **none** |

Replayed raw at a production build TP0010 latches `OC_BT` before its recorded UV
collapse can be scored, and State 99 then freezes `fault_flags` — destroying the entry
in precisely the way the un-clamped FC channel did. **TP0053 deliberately gets no BT
clamp:** its peak is well under the limit, and clamping a trajectory that needs no
clamping would modify a recording for nothing. The two UV-pair entries therefore differ
in their stimulus modifiers, and they differ *by measurement*.

**No conclusion about BT current may be drawn from the TP0010 run either.**

### 3b-quater. Recorded-stimulus band pins (2026-09-01)

Two check kinds assert that a recorded stimulus still *is* what an entry's
classification assumes, so a decode, rescale or substitution change fails by name
instead of silently turning an entry into a tautology or into a different class:

- **`v_bus_min_in_band(min_v, max_v]`** — the recorded `V_bus` MINIMUM. Carried by
  TP0178/TP0201, whose `fault_not_latched(UV_BUS)` is vacuous on its own (their floors
  never cross the limit).
- **`i_fc_max_in_band[min_a, max_a]`** — the recorded \|`I_fc`\| MAXIMUM, new this round.
  Carried by **ML0151**, band **[1.20, 1.40] A**: its recorded peak is **1.354 A**,
  96.7 % of `LIMIT_I_FC_MAX`, so the entry sits **46 mA** from flipping out of the
  conformance class. That knife-edge was documented in prose in the entry's `why` and
  asserted by nothing; now the ceiling *is* the firmware limit (crossing it makes this a
  deviation-class OC stimulus) and the floor sits 11 % below the measurement (drifting
  down means the near-limit condition the entry documents is gone).

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

### 3c-bis. Transient indication vs LATCH (2026-08-30c)

The firmware **publishes** a fault bit as soon as the condition is indicated, and
separately **latches** it — entering State 99 and ORing in `FAULT_ERROR` (`0x8000`) —
once the condition survives its filter. So `fault_flags & BIT` answers *"was the
condition ever indicated?"*, while `fault_flags & (BIT | FAULT_ERROR)` answers *"did
the board actually latch on it?"*. Measured on this suite: **TP0010 indicates
`UV_BUS` 321 ms before it latches, TP0053 536 ms before** — a real, reportable gap,
not rounding.

Both `fault_latched` and `fault_not_latched` use **latch** semantics (bit *and*
`FAULT_ERROR`), on the reported time and on the end-of-run test. `fault_latched` also
prints how far ahead of the latch the transient indication ran.

**The `no_fault` + `fault_not_latched` pair is not redundant, and the seam is
deliberate.** On a stimulus deep enough to produce a transient indication without a
latch, `fault_not_latched` **passes** (its contract is only "this dip does not
latch") while `no_fault` **fails** (its contract is "nothing was even indicated").
`no_fault` is the strictly stronger claim. An entry that wants to permit a transient
must drop `no_fault` — it must not weaken the pair. TP0178/TP0201 pass today because
their recorded minima (12.1489 / 12.1853 V) never cross `LIMIT_V_BUS_MIN` at all, so
neither check goes near the seam.

⚠️ **What the TP0178/TP0201 de-vacuation actually bought (campaign
`hil_report_20260831_222036`, replay audit).** Adding `v_bus_min_in_band` made the
pair non-vacuous, but it is worth being exact about *what* it asserts: the band pins
the **STIMULUS**, not the board's undervoltage behaviour. It says the recorded sag
still lands in the near-miss window it was chosen for — so if a clamp, a time-base
change or a re-recording moved the floor across 12.0 V (or away from the limit
entirely), the entry fails loudly instead of passing as "did not latch, as expected".
It does **not** exercise the UV latch: on a stimulus that never crosses the limit,
the leaky-dwell integrator never accumulates and there is nothing for the firmware to
decide. The pair therefore carries **no substantive UV-latch assertion**, and none is
wanted here — positive UV coverage lives in the UV pair (TP0010 / TP0053), which must
latch. Read a green TP0178/TP0201 as "the near-miss stimulus is intact", never as
"the UV filter was tested and behaved".

### 3d. Bring-up gate (2026-08-30)

Before any of an entry's own checks run, the board must have reported **mainState 1
(Idle) within `BRINGUP_DEADLINE_S` = 3.5 s**. If it has not, the entry reports one
honest failure — *"the board never reported Idle — BRING-UP FAILED"*, with the last
observed state and the post-grace fault union — and the entry's checks are **not
run**. Without the gate, a board that never came up fails every check for one single
reason and the report reads as N independent findings. An entry whose *point* is a
failing bring-up sets `skip_bringup_gate` (only ML0217 does).

### 3e. Command replay — `replay_commands` (2026-08-30)

An entry may set `replay_commands: True`. `build_sim_argv()` then passes
`--replay-commands` to the simulator, and the log's own recorded `v_sp` and
`share_sp` (columns present in every BLG format v1–v7) are replayed as 22-byte Pi
command packets at 50 Hz alongside the injection frames. The board goes
**Idle → Run** and both control loops step against the recorded stimulus, so the
current-shape checks judge the **live controller's reaction** instead of a flat
zero. Such an entry also carries a `drive_loop_stepped` check, ordered before its
motor-response checks: if commands were replayed and the loop still never moved,
that is a real FAIL and the reader sees the cause first.

**It does not close the loop.** The injected `v_actual` still does not respond to
what the firmware commands, so the drive loop is *expected* to fight the recorded
trajectory wherever the recorded and flashed laws differ.

Entries that do **not** opt in have their motor-response checks tagged
`NOT EXERCISED (no command replay)` — `passed` stays `True` (the assertion "the
firmware did not drive on an uncommanded stimulus" is real and worth keeping), but
the tag and the `n_checks_not_exercised` count say plainly that the check carried
no evidence about the entry's own classification.

Three rules decide the flag, and each entry states which one applied:

1. **Fault-path purity.** An entry whose verdict is a fault *decision* stays
   command-free: the UV pair **TP0010 / TP0053** (whose trajectories are already
   modified by `i_fc_clamp_a` — a second stimulus there could change the outcome
   outright), **ML0217**'s `INIT_FAIL`, and the must-**not**-latch pair
   **TP0178 / TP0201**.
2. **The recorded `v_sp` must be real.** The `'T'` and `'W'` State-98 profiles
   command *current* directly, never velocity, so their records carry `v_sp`
   **identically 0** (measured 2026-08-30): TP0010, TP0053, TP0170, TP0171,
   TP0176, TP0178, TP0201, TP0210, WP0097, WP0197. Replaying that commands
   nothing — `V_SP_ZERO_THRESH` yields 0 A — so `drive_loop_stepped` would fail on
   a stimulus that never existed. Their `share_sp` axis *is* live, but the share
   setpoint alone does not move the motor.
3. **The entry's own expectation must survive it.** **ML0144** asserts
   `near_zero_current`, which is predicated on `v_setpoint = 0`; its recording
   carries 3845 rows of nonzero `v_sp`, so replaying the commands would drive the
   motor and contradict the entry outright.

Everything else with a live recorded `v_sp` opts in: **15 of 27** entries
(`Cmds` column below).

A **fourth bucket** was added with the synthetic entry (FU4, 2026-08-31): the
three rules above all decide whether a *recorded* trajectory should **also** carry
commands. For **SY0001** (§3f) the commands **are** the stimulus — its rails are
constant nominals that assert nothing — so `replay_commands: True` is *mandatory*
there, not a judgement call. Any future synthetic entry inherits this: a generated
log whose rails are nominal placeholders must replay commands or it is a
five-second run of nothing.

The three `OC_FC` entries opt in and are safe to: `OC_FC` latches off the
*injected* `I_fc`, which command replay cannot touch, and each has a long
pre-latch window (measured, log time: ML0203 33.5 s of 43.8 s, ML0165 18.0 s of
38.6 s, ML0169 2.3 s of 18.7 s — ML0169 is the tightest and the one to check first
if `drive_loop_stepped` ever starts failing there).

### 3f. Synthetic entries — the `SY` prefix (FU4, 2026-08-31)

`logs/` holds real recordings written by the firmware's SD logger, one prefix per
profile class (`ML` manual, `TP`/`WP` current profiles, `YP` combined, `PS`).
**`SY` = SYNTHETIC**: the file was authored by a generator, not recorded. There is
one such entry, `SY0001`, and the prefix exists so a reader scanning the directory
can tell it apart without opening it. Nothing in a `SY` log is a measurement; do
not fit a constant to one or cite a number from one.

| | |
|---|---|
| Log | `logs/SY0001.BLG` (170 100 B, BLG v3, `fw_version` 23, 2500 records) |
| Generator | `tools/gen_fu4_replay_log.py` |
| Regenerate | `.venv_hil/Scripts/python.exe tools/gen_fu4_replay_log.py --force`, then re-run `--verify-logs` |

**Why one was authored.** FU4 wanted the **Idle → Run setpoint-arrival transient**
covered. `doState1()` zeroes `v_setpoint` on the Run transition unconditionally,
ignoring the triggering packet's payload
(`teensy_controller/teensy_controller.ino:5382-5410`), so a large setpoint reaches
a freshly reset drive controller only on the **second** post-reset command packet,
≤ 20 ms later. No recorded log delivers that: every bench run begins at standstill
with the setpoint at or near zero. Holding `v_sp` at 2.0 m/s from record 0 delivers
it **structurally** — the firmware's own zeroing supplies the step edge, so nothing
has to be timed against an instant the host cannot observe.

**Honesty rules the file follows, and any future `SY` log must.**

- **Format v3, not v5/v6/v7.** v3 is the earliest format carrying the four
  source/node voltages the replay path needs. v5's drive-controller fields
  (`u_unsat`, `drive_x0`) and v6/v7's encoder diagnostics have no synthetic
  referent, and inventing them would read as fabricated hardware telemetry.
  Choosing v3 makes their absence structural rather than a claim to be trusted.
- **`v_actual` is pinned at 0.0.** Replay is open loop, so any nonzero trajectory
  would be an invented plant response. Zero is also the honest at-rest
  precondition for a Run entry. The velocity-valid flag (record `flags` bit1) is
  set so the decoder emits 0.0 as a real value instead of blanking the column.
- **`I_cmd` is 0.0 on every record: the log carries NO recorded response.** A board
  holding `v_act` at exactly 0 while commanding 12 A is physically impossible, so
  there is no self-consistent response to write down. The response under test is
  entirely the live board's, and any recorded-vs-observed overlay of this entry
  (`tools/hil_report_analysis.py`'s response-deviation figure) is meaningless by
  construction.
- **Deterministic output.** Record timestamps come from the 1 kHz sample index and
  the header clock fields are fixed at 0, so regenerating produces a byte-identical
  file. The log is committed; a generator that diffed on every run would make every
  regeneration look like a data change.
- **`replay_commands` is mandatory, not a judgement.** The rails are constant
  nominals that assert nothing — the recorded `v_sp` is the entire stimulus. This
  is a fourth bucket alongside the three rules in §3e, stated in the module.

---

## 4. The suite

27 entries: **12 conformance, 15 deviation**. `*` = provisional. Check names are the
declarative kinds in `hil_replay_suite.py` (`CHECK_KINDS`). Every entry additionally
carries the implicit `bringup_reached_idle` gate (3d).

> **Reclassified 2026-08-30 (5 entries).** ML0203, ML0165, ML0169 and WP0097 moved
> **conformance -> deviation expecting `OC_FC`**, and ML0217 moved **conformance ->
> deviation expecting `INIT_FAIL`**. Rationale in 4a/4b.

### Conformance — current wheel and control law

| Log | fw | BLG | Classification | Why | Checks | Cmds |
|---|---|---|---|---|---|---|
| **SY0001** * | 23 | 3 | **SYNTHETIC (§3f)** — Idle → Run setpoint-arrival transient: `v_sp` held at 2.0 m/s from record 0, released to 0.0 at log t = 1.5 s, `v_actual` pinned at 0 | The one operating condition no recording covers. `doState1()` zeroes `v_setpoint` on the Run transition regardless of payload (`.ino:5382-5410`), so a large setpoint reaches a freshly reset drive controller only on the **second** packet. Authored, not recorded — no value in it is a measurement | `no_fault`, `drive_loop_stepped`, `steps_onto_rail_within`, `bounded_current`, `returns_off_rail` | **yes** (mandatory) |
| YP0196 | 18 | 6 | `'Y'` combined drive-cycle + power-share profile | Both loops' stimulus together on the current law | `no_fault`, `bounded_current`, `share_loop_actuated`, `drive_loop_stepped`| **yes** |
| WP0197 | 18 | 6 | `'W'` combined current + power-share profile | The current-axis twin of `'Y'` — encoder-less share stimulus | `no_fault`, `bounded_current` | no |
| TP0210 * | 19 | 6 | `'T'` share sweep, handoff-slew build | Most recent share stimulus; nearest to the flashed target | `no_fault`, `bounded_current` | no |
| YP0214 * | 19 | 6 | `'Y'` combined profile on fw v19 | Combined-profile stimulus with the handoff slew in the recording | `no_fault`, `bounded_current`, `share_loop_actuated`, `drive_loop_stepped`| **yes** |

### Conformance — older wheel/law (stability conformance only, §2)

| Log | fw | BLG | Classification | Why | Checks | Cmds |
|---|---|---|---|---|---|---|
| ML0146 | 14 | 5 | clean `'V'` step, 120-slot wheel | First-flash fw v14 clean baseline. **Not a trace-match case** | `no_fault`, `bounded_current`, `no_rail_limit_cycle`, `drive_loop_stepped`| **yes** |
| ML0149 | 14 | 5 | clean `'V'` step, higher setpoint | Second clean fw v14 point, same meaning | `no_fault`, `bounded_current`, `no_rail_limit_cycle`, `drive_loop_stepped`| **yes** |
| TP0170 | 16 | 6 | share sweep, `share_sp = 0.5` | Balanced-share operating point of the first genuine closed-loop share dataset | `no_fault`, `bounded_current` | no |
| TP0176 | 16 | 6 | share sweep at the FC rail (FC-only 43–45 % of the run) | The share-rail extreme: one source carries the bus for a long stretch | `no_fault`, `bounded_current` | no |
| YP0152 | 14 | 5 | first `'Y'` profile on the Youla drive controller | Combined-profile representative from the fw v14 era | `no_fault`, `bounded_current`, `share_loop_actuated`, `drive_loop_stepped`| **yes** |
| **ML0151** | 14 | 5 | **H6 flagship** — 56 s stepladder with the ~428 ms VESC dead window, the drag step-change and ~90 saturation episodes | Richest recorded incident in the archive; many saturation entries/exits back to back is exactly the class the fw v18 general-Hanus fix targets | `no_fault`, `bounded_current`, `returns_off_rail`, `no_rail_limit_cycle`, `drive_loop_stepped`| **yes** |
| TP0178 | 16 | 6 | handoff bus sag to **12.1489 V** — 0.1489 V (1.24 %) **above** `LIMIT_V_BUS_MIN`, hence **0.0 ms** of accumulated dwell (⚠️ record corrected 2026-08-31: the old "10 ms dwell (half the 20 ms latch)" did **not** survive replay — the floor never crosses the limit and the sub-12.15 V excursion is 1–3 ms wide) | The **negative** UV case: the recorded dip must *not* latch UV_BUS. Pairs with the UV pair (TP0010/TP0053), which must. ⚠️ `fault_not_latched` is **vacuous** on this stimulus by construction; `v_bus_min_in_band` is what bites | `no_fault`, `fault_not_latched(UV_BUS)`, `v_bus_min_in_band(12.0, 12.30]` | no |

### Deviation — the modern firmware must not reproduce the defect

| Log | fw | BLG | Recorded defect | Check + caveat | Cmds |
|---|---|---|---|---|---|
| ML0137 | 11 | 5 | boxcar-estimator ±12 A rail-to-rail limit cycle, 2.3–2.6 Hz | `no_rail_limit_cycle`, `bounded_current`, `no_fault`. **Caveat:** replay injects the *recorded* `v_act`, so this tests the controller's reaction to that stimulus, **not** the estimator fix that actually removed the cycle, `drive_loop_stepped`| **yes** |
| ML0140 | 12 | 5 | estimator blind holds, 120–560 ms, under direction dither | `no_fault`, `bounded_current`, `returns_off_rail` — a long frozen-velocity stimulus, `drive_loop_stepped`| **yes** |
| ML0144 | 12 | 5 | `v_sp = 0` relay: 90 % rail bang-bang closing the loop below the estimator floor | `no_fault`, `near_zero_current`. **Honest limit:** replay cannot set `v_setpoint`, so the `v_sp ≠ 0` relay is unreachable. What *is* checkable, and what is checked: with `v_sp = 0` and this log's `v_actual` injected, the firmware commands ~0 A (the `V_SP_ZERO_THRESH` behaviour) instead of bang-banging | no |
| ML0153 | 14 | 5 | T/2 basin — `v_act` corrupted to ~2× true | `no_fault`, `bounded_current`. **Caveat:** the basin fix is in the estimator, which replay bypasses — not testable open-loop, `drive_loop_stepped`| **yes** |
| ML0164 | 16 | 6 | x2 **rounding** basin, locked breakaway-to-stop | `no_fault`, `bounded_current`. Same caveat, `drive_loop_stepped`| **yes** |
| TP0171 | 16 | 6 | reset re-seeded *into* the x2 basin (~15 ms recovery) | `no_fault`, `bounded_current`. Same caveat | no |
| YP0166 | 16 | 6 | mid-run `v = 0` injection at a true 1.49 m/s → ±12 A rail pair within 12 ms (the fw v17 TOCTOU race) | `no_fault`, `bounded_current`, `returns_off_rail` — a full-scale velocity step straight into the ~454 A/(m/s) LF gain must give a **bounded** transient that releases, `share_loop_actuated` (⚠️ **span is BIMODAL** — see below), `drive_loop_stepped`| **yes** |
| TP0201 | 18 | 6 | share-rail handoff gap, bus 15.86 → **12.1853 V** | `no_fault`, `fault_not_latched(UV_BUS)`, `v_bus_min_in_band(12.0, 12.30]` — the floor sits 0.1853 V (1.54 %) **above** the limit, so the dwell integrator never accumulates and no latch is possible (⚠️ record corrected 2026-08-31: not "~10 ms inside the 20 ms dwell"). `fault_not_latched` is therefore **vacuous** here; the band pin is what bites. **Caveat:** the fw v19 handoff *slew* that mitigates the gap acts on the plant, which replay bypasses; only the fault decision is exercisable | no |
| TP0010 | — (pre-versioning) | 1 | bus collapse the old firmware died on **without faulting** | `fault_latched(UV_BUS)` — the fw v5 leaky-dwell filter must latch. That is the whole point of the rework | no |
| TP0053 | 4 | 2 | repetitive source-commutation dropout (~9 ms under / ~51 ms over per ~60 ms cycle) that **evaded** the fw v4 window filter | `fault_latched(UV_BUS)` — the exact case the dwell integrator was designed for: net +6.45 ms per cycle, so it must latch within a few cycles. ⚠️ **Repeat class ±~100 ms, burst-quantized** — see below | no |

**YP0166's `share_loop_actuated` span is BIMODAL — do not band it (2026-08-31, F3,
second datapoint).** Measured spans of the MDAC ratio `r = BT/(FC+BT)`: **0.546 /
0.550** (campaigns `_000518` / `_222036`) and **0.697** (`_191509`). The two modes
have different mechanisms, which is why no single band is honest:

- **~0.55** — the replayed `share_sp`'s own profile rail. The recording spans
  0.300–0.700, i.e. 0.40 of setpoint, which the open-loop share PI's windup carries
  a little past.
- **~0.70** — a run in which the wandering setpoint *also reached* the firmware's
  cutoff clamp, so the MDAC ratio is driven to a rail rather than tracking, and the
  span measured is the clamp's, not the profile's.

Which mode a campaign lands in is decided by the same command-arrival-phase
sensitivity that makes this entry's cutoff *transition count* unstable (which swung
46 → 0 between campaigns with nothing changed, and is deliberately unscored here) —
the same phenomenon read on a different observable. The scored floor is **0.20**,
below both modes by ~2.7×, and that is exactly the right assertion for this entry: it
says the loop actuated and declines to say how far. Clamp-reaching coverage is
deliberate elsewhere — `share-staircase` and `ems-y-b00-*` — so the bimodality costs
the suite no coverage. (Whether to band it or leave it documented is the operator's
call; the conservative doc option is in force.)

### 4a. Deviation — the OC_FC reclassification (operator ruling (a), 2026-08-30)

| Log | fw | BLG | Recorded I_fc peak | Check | Cmds |
|---|---|---|---|---|---|
| ML0203 | 18 | 6 | 2.11 A | `fault_latched(OC_FC)` + `require_stimulus`, `bounded_current`, `share_loop_actuated`, `drive_loop_stepped`| **yes** |
| ML0165 | 16 | 6 | 1.52 A | same, `drive_loop_stepped`| **yes** |
| ML0169 | 16 | 6 | 1.88 A | same, `drive_loop_stepped`| **yes** |
| WP0097 | 5 | 3 | **3.60 A** (archive maximum) | same, **plus `latch_precedes_uv(OC_FC, min_lead_ms 10)`** — the reclassification's own premise, asserted (see below) — but also see the timing caveat below | no |

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

**WP0097's reclassification premise is now ASSERTED (2026-08-31, campaign
`hil_report_20260831_222036` F4).** This entry left the UV pair because its recorded
dip supplies only **18.65 ms** of dwell against the 20 ms `UV_BUS_DWELL_LATCH_MS` —
so it is an OC stimulus with a *near-miss bus collapse behind it*. That is only a
safe classification while the `OC_FC` latch genuinely comes **first**: if a future
clamp, time-base change or filter retune let the bus collapse arrive first, the entry
would still report "OC_FC latched", off the wrong mechanism, with the same green
verdict. Nothing asserted the ordering. The new `latch_precedes_uv` check does:
measured, the OC latches at t = 19.4654 s and the injected `V_bus` first goes under
12.0 V at t = 19.4878 s — a **22.37 ms lead** (19 sub-12 V samples, min 6.12 V) —
against a floor of 10 ms, 45 % of the measurement. The floor is loose on purpose: the
lead is a property of the *recording* (two fixed events in one log), so only a
time-base or clamp change can move it, and by far more than a millisecond. What must
never pass is a lead that has collapsed or inverted.

**TP0053's latch INSTANT is burst-quantized — do not read a shift as a regression
(2026-08-31, F2).** Only 8.3 % of its samples sit under `LIMIT_V_BUS_MIN`, and they
arrive in short bursts, so the leaky dwell integrator accumulates in steps and
crosses the latch threshold *inside a burst*: one burst of slack is a ~60 ms move for
a stimulus that has not changed. Campaign `_222036` measured **+59 ms** against
`_191509`, exactly one burst period. Its repeat class is therefore **±~100 ms**.
TP0010 is **not** in that class — its collapse is continuous, its dwell crossing is a
smooth ramp, and it moved ~0 ms across the same campaign pair (±3 ms). No check pins
the instant on either entry; this is a records note so the next campaign's analysis
does not open a finding on a number that is behaving.

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

| Log | fw | BLG | Recorded defect | Check | Cmds |
|---|---|---|---|---|---|
| ML0217 * | 19 | 6 | **recorded with a dark bus** — measured `V_bus` max **0.35 V** over all 38 s | `fault_latched(INIT_FAIL, latch_elapsed_band_s [0.20, 0.45] s from the State-0 entry — pins P0, excludes P1)`, `bounded_current`; `skip_bringup_gate`, `skip_preamble` | no |

It was never the "duration/soak case" it was catalogued as. Replayed, the staged
bring-up cannot pass **P0** and times out at `PRECHARGE_TIMEOUT_MS` into
`FAULT_INIT_FAIL` (`.ino:8762-8765`) — correct firmware behaviour, and now the
asserted expectation. It is the one entry exempt from the bring-up gate (3d),
necessarily: a failing bring-up is the point.

**Which gate — settled 2026-08-31, and the check now pins it.** `FAULT_INIT_FAIL`
is raised by *both* of `busBringupTick()`'s phase timeouts, so "INIT_FAIL latched"
alone cannot say whether the dark bus failed P0's precharge gate
(`PRECHARGE_TIMEOUT_MS` 300 ms) or P1's charge gate (`BUS_CHARGE_TIMEOUT_MS`
800 ms) — two different findings about the firmware, one bit. A fix round in
campaign `hil_report_20260831_191509` briefly overturned the P0 reading in favour
of P1, on an **absolute** latch timestamp of 0.8015 s; campaign `_222036`'s replay
audit showed that reasoning was wrong twice over. The firmware measures phase
timeouts from `bringupPhaseStart`, re-stamped on the **State-0 entry**, and on a
suite run the board only reaches State 0 when the fw v23 run-boundary warm reset
fires — at ~0.5 s, a property of the host's inter-run gap. In that frame the latch
is **301.3 ms** after the State-0 entry (`_222036`) and **301.1 ms** (`_191509`):
P0's 300 ms gate, to 0.4 %, in both. P1 is unreachable here regardless — it is
entered only once phase 0 passes, and phase 0's gate is the bus reaching
`V_PRECHARGE_MIN`, which a dark bus never does. The check's bound is therefore
`latch_elapsed_band_s` **[0.20, 0.45] s measured from the State-0 entry**, which
brackets 300 ms and excludes 800 ms. The absolute bound it replaced discriminated
nothing: both candidate gates land past 0.5 s absolute.

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
`NEAR_ZERO_I_A` 0.5 A, `RAIL_LEVEL_A` 11.9 A, `BRINGUP_DEADLINE_S` 3.5 s,
`RESET_STEP_LEVEL_A` 11.0 A / `RESET_STEP_WITHIN_S` 0.15 s — are named
constants in the module with their rationale at the definition.
`RESET_STEP_WITHIN_S` is a **derived latency budget, not a measurement** (≤ 20 ms
Run-transition packet + ≤ 20 ms setpoint packet + 20–40 ms rail time + ~3 ms
gating ≈ 83 ms worst case, ×1.8); tighten it from campaign data. `REPLAY_GRACE_S` and
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
   `no_rail_limit_cycle`, `returns_off_rail`, `near_zero_current`,
   `drive_loop_stepped`, `share_loop_actuated`, `steps_onto_rail_within`,
   `v_bus_min_in_band`, `latch_precedes_uv`.
   (`no_sustained_rail` exists but is
   **not** for this half — see §3.) A new kind is a
   small pure `(ReplayCsv, spec) -> (bool, str)` function plus a `CHECK_KINDS` entry
   — and a named constant with its rationale for any threshold it introduces.

   *Worked example — `steps_onto_rail_within` (FU4, 2026-08-31), added for SY0001.*
   It asserts that `|I_cmd|` **first** crosses `level_a` within `within_s` seconds
   after `after_s`. Four things the step-4 pattern required of it:
   - **Two named constants with derivations,** not literals in the entry:
     `RESET_STEP_LEVEL_A` = 11.0 A (deliberately below `RAIL_LEVEL_A` 11.9 — the
     question is "did the loop respond at full authority", not "did it touch the
     clamp to four decimals") and `RESET_STEP_WITHIN_S` = 0.15 s (§6).
   - **`after_s` defaults to `data.preamble_s`,** never a literal 2.5, so a
     `skip_preamble` entry resolves it to 0.0 like everything else that needs the
     bound.
   - **Membership in `MOTOR_RESPONSE_KINDS`,** because the check reads `data.current`
     and is meaningless without command replay. The asymmetry is intended: the
     `NOT EXERCISED` tag never changes `passed`, and this kind *fails* on a flat-zero
     series where the others pass — so a misuse surfaces as a **tagged FAIL**, not a
     silent green tick.
   - **It does not contradict the open-loop rail note (§3):** it bounds when the rail
     is *reached*, never how long the episode lasts.
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
   - `replay_commands: True/False` — **decide this explicitly for every new
     entry** (§3e). Work the three rules in order: (1) is this entry's verdict a
     fault *decision*? Then keep the stimulus pure and set `False`. (2) Is the
     recorded `v_sp` actually nonzero? A `'T'`/`'W'` State-98 recording commands
     current, not velocity, and carries `v_sp` identically 0 — measure it, do not
     assume. (3) Would a live command contradict the entry's own expectation (the
     ML0144 case)? If none of the three refuses it, set `True` **and add a
     `drive_loop_stepped` check ordered before the motor-response checks**.
     Emits `--replay-commands`. An opt-in entry should also carry
     `drive_min_frac` on its `drive_loop_stepped` check — the fraction of the
     recorded window that must show drive activity, set at roughly **half** the
     entry's own measured fraction. The absolute 50-sample floor sits 31–1017×
     below measured activity and only catches a *dead* command path, not a dying
     one; the per-entry fraction is what catches degradation.
   - `share_loop_actuated` — add it to an entry whose recorded `share_sp`
     actually varies (measure it; most logs hold 0.500 constant). It asserts the
     MDAC droop split **moved**, which is the share axis's only observable here.
     It deliberately does **not** assert setpoint tracking: open-loop replay winds
     the share PI regardless, and entries with a *constant* 0.500 setpoint still
     show a ratio span of ~0.35 from windup alone, so a tracking assertion would
     be satisfied by windup and prove nothing.
   - `require_stimulus` on a `fault_latched` check is supported for `FAULT_UV_BUS`
     and `FAULT_OC_FC` (§4c); any other bit is reported as an authoring error rather
     than silently unguarded.

   All three stimulus modifiers (`skip_preamble`, `i_fc_clamp_a`,
   `replay_commands`) are mirrored by `build_sim_argv()`, so a hand-run replay
   injects exactly what a suite-run one does.
4d. **If you have to AUTHOR the log, say so in the filename.** Only do this when the
   property is genuinely unreachable from any recording (FU4's Idle → Run setpoint
   arrival was — every bench run starts at standstill). Then: use the **`SY`
   prefix**, commit a **deterministic generator** beside the file, pick the
   **lowest BLG format** that carries the channels you actually need (so absent
   diagnostic fields are structural, not a promise), write **no invented plant
   response**, and state all of it in §3f and in the entry's `why`. A synthetic log
   whose rails are nominal placeholders **must** set `replay_commands: True` — the
   commands are its only stimulus.
5. **Write the open-loop caveat.** If the defect being guarded lives in the estimator
   or the plant, replay cannot test it — `replay_commands` does not change that, it
   only replays a second recorded channel. Say so in `why` (§3 lists the classes).
   An entry that overclaims is worse than no entry.
6. **Add the `REPLAY_SUITE` entry** in `tools/hil_replay_suite.py`, and **update
   §4 of this document** in the same change.
7. If the recording firmware version is new to `FW_DELTA_NOTES`, add its one-line
   "what differs vs v21 that matters".
