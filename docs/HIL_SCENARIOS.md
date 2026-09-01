# HIL Suite Scenario Reference

This document catalogs every scenario that `tools/run_hil_suite.py` runs, grouped by
category. For each scenario it states what the scenario tests, the pass and failure
criteria, and why the test is useful. The authoritative definitions are the `SCENARIOS`
registry in `tools/hil_plant_sim.py` (stimulus, duration, electrical engine) and the
`FAULT_EXPECTATIONS` table in `tools/run_hil_suite.py` (scoring). This document
summarizes those tables; on any disagreement, the code wins.

## 1. How scoring works

Every scenario is judged on the same machinery, so the per-scenario entries below use
these terms:

- **Post-grace fault union.** Fault bits observed before `WARM_RESET_GRACE_S` (2.0 s)
  are attributed to the previous run's inherited latch, which the fw v23 between-run
  recovery clears. Judgement applies to bits observed after the grace bound.
- **`require` / `allow_only`.** A required bit must appear in the post-grace union.
  Any bit outside the allow mask fails the run. A scenario with no
  `FAULT_EXPECTATIONS` entry is expected fault-free.
- **`not_before_s`.** A required fault that latches before its own stimulus did not
  come from the stimulus and fails.
- **`survive_to`.** The board must be un-latched and in the stated `mainState` set at
  time *t* — positive proof that the run reached its own stimulus.
- **`signals_require`.** Positive trace evidence (CSV columns, switch bits, aux pin
  bits, edge latencies) that the objective was actually exercised. This field exists
  because "no fault" alone is satisfied by a run that does nothing.
- **`events_require`.** Evidence from the hi-fi engine's `.events.jsonl` sidecar
  (SCP cuts, rings), not grace-filtered.
- **Warm-reset tripwire.** A mid-run mainState 99 → non-99 transition marks the run
  INCONCLUSIVE unless the scenario whitelists it (`warm_resets_expected`).

Electrical engine: `"any"` scenarios run under the campaign's `--electrical-pref`
(default hifi); `"hifi"` scenarios always run the `hil_electrical.py` engine.

## 2. Baseline and disturbance scenarios

### steady (10 s, any engine)

- **Tests:** the quiescent baseline — bring-up completes, then a fixed aux load with
  no stimulus event at all.
- **Pass/fail:** no `FAULT_EXPECTATIONS` entry; any post-grace fault is a failure.
  The ~8 s of post-grace steady state supplies the campaign's baseline statistics.
- **Why useful:** it is the reference every other run's medians and variances are
  compared against, and the cheapest detector of a regression in bring-up or the
  idle operating point.

### step-load (10 s, any engine)

- **Tests:** a +1.2 A aux load step at t = 5 s — a bus disturbance the share loop
  must reject.
- **Pass/fail:** expected fault-free (no table entry). The post-step settled window,
  not just the transient, is the observable.
- **Why useful:** the simplest closed-loop share-rejection stimulus; a droop or
  share-loop regression shows here before it shows anywhere subtler.

### sag (9 s, any engine)

- **Tests:** a −5 V bus sensor-path disturbance for 1 s at t = 5 s, crossing
  `LIMIT_V_BUS_MIN` (12.0 V) — the real UV path (HIL_MODE.md test H2).
- **Pass/fail:** `FAULT_UV_BUS` is required, must not latch before t = 5.0, and no
  other bit may appear. Measured dwell on hardware: 19.887 ms against the 20 ms
  design.
- **Why useful:** it validates the leaky UV-dwell integrator and the latch path
  end to end, with the injected stimulus making the dwell timing exactly repeatable.

## 3. Link-loss and watchdog scenarios

### comm-loss (12 s, any engine, `warm_resets_expected: 1`)

- **Tests:** the simulator stops transmitting for 2 s at t = 5 s — the firmware's
  hold-then-zero staleness ladder, the `ERR_HIL_STALE` latch, and the fw v23
  run-boundary warm recovery.
- **Pass/fail:** `FAULT_PI_TIMEOUT` (0x0010, aliased by `FAULT_HIL_LINK`) is
  required, not before t = 5.0, nothing else allowed. Exactly one mid-run warm reset
  is required; more is INCONCLUSIVE, fewer fails. Unchanged under `--pi-live`
  because the HIL stale clock keys on accepted injection frames only.
- **Why useful:** the only stimulus that exercises the full link-death → latch →
  boundary → warm-reset → auto bring-up sequence; it is also the acceptance test for
  the RT1987 warm re-close fix (the pre-charged-node soft-start).

### pi-silence (14 s, any engine)

- **Tests:** the firmware's Pi watchdog (`checkPiWatchdog()`, `PI_TIMEOUT_MS` 500)
  in isolation: the emulated Pi stops commanding at t = 8.0 while the injection
  stream keeps running at full rate.
- **Pass/fail:** `FAULT_PI_TIMEOUT` required, not before t = 8.0; the board must be
  in Run at t = 7.5; the `child_tx_healthy` check must confirm the injection stream
  was continuous (the 0x0010 bit is shared with `FAULT_HIL_LINK`, so attribution is
  by elimination); and the commanded motor current must fall by ≥ 2.0 A across the
  latch — the fault's consequence, not just its flag.
- **Why useful:** it closes a verified coverage gap. Every earlier stimulus that
  stopped commands also stopped injection, which trips the HIL staleness path
  instead; `pi_mute_after_s` mutes the commander alone.

## 4. Charging-path scenarios (Ag105)

### charge-cruise (15 s, any engine)

- **Tests:** the FC-path charge bring-up in Run state — `charge_goal` at t = 8.0
  opens `FC_CHARGE_ENABLE` on intent, the Ag105 settles to Charging, and the MPPT
  release is gated on readiness.
- **Pass/fail:** `FAULT_OC_FC` is **required**, not before t = 8.0, with the board
  alive in Run at t = 8.0. Operator ruling (b): FC-path charging plus cruise is
  infeasible by design (single-source operation against `LIMIT_I_FC_MAX` 1.4 A), so
  the OC latch validates the design boundary rather than failing the run.
- **Why useful:** it asserts a known hardware incompatibility positively, so a
  future change that silently relaxes the limit or the single-source behaviour
  becomes a visible diff.

### charge-regen (45 s, any engine, EMS `regen-harvest`)

- **Tests:** regen-path charging: continuous deceleration ramps steeper than the
  coast rate drive the commanded current negative, `charge_goal` is asserted only
  inside braking windows, and the Ag105 is fed through REGEN + MOT_PWR with
  `MPPT_DISABLE` held low.
- **Pass/fail:** completely fault-free; must survive to the first braking window
  (t = 14.0) in Run; `REGEN_ENABLE` must be set for ≥ 0.5 s inside braking window 1;
  and `I_charge` must exceed 0.5 A through that path. Charge ceiling is de-rated to
  1.6 A so the shared draw keeps a 37 % per-channel margin.
- **Why useful:** the only end-to-end regen-charging coverage in the suite. The
  original scripted design coasted instead of braking and latched OC before its
  first braking window; the positive signal checks prevent that regression class.

### charge-fault (25 s, any engine)

- **Tests:** the charger input rail collapses at t = 20 s after charging is
  established — the GENSTAT decode and the charger-loss path.
- **Pass/fail:** fault-free (GENSTAT 000 is a non-error status and
  `FAULT_I2C_CHARGER` is unreachable under HIL_SIM, so the correct response is to
  drop readiness and carry on without latching); the board must survive to t = 20 in
  Run; and `I_charge` must exceed 0.5 A in (8, 20) s, or the collapse tests nothing.
  Charge ceiling de-rated to 0.8 A so the run survives to its own stimulus.
- **Why useful:** an earlier version latched OC_FC 14 s before its own stimulus and
  still passed under the old permissive table; the `survive_to` + positive-signal
  pair is the fix, and the scenario is the only input-loss coverage the charger has.

### charge-to-full (130 s, any engine, suite forces `--soc0 0.990`)

- **Tests:** the Ag105 Fully-Charged / CV path at standstill: CC charging from
  SoC 0.990 reaches the 0.995 threshold (predicted ~t = 100, measured offline at
  98.90 s), GENSTAT 011 with the CV flag, and the current taper — plus the
  firmware's deliberate no-action response to FULL.
- **Pass/fail:** fault-free; in Run at t = 60; `I_charge` ≥ 0.8 A during CC;
  GENSTAT 011 and the CV flag each held ≥ 0.5 s after t = 60; `I_charge` ≤ 0.05 A
  after t = 125; and `FC_CHARGE_ENABLE` still open after t = 110 — the no-action
  baseline asserted positively.
- **Why useful:** the first run in the suite ever to reach AG105_ST_FULL, and it
  pins the "firmware does nothing on FULL" policy so a future change to it must
  fail a check rather than land silently.

### mppt-tracking (45 s, any engine, EMS `mppt-harvest`, `mppt_emulation` on)

- **Tests:** the Ag105 MPPT input-voltage threshold (18 V default with MPPTS open),
  made causal for the first time: the regen path holds `MPPT_DISABLE` low, while on
  the low-cruise FC-path windows the ~15.95 V bus cannot clear the threshold, so the
  firmware and the module are predicted to hunt.
- **Pass/fail:** fault-free; in Run at t = 39.1; `MPPT_DISABLE` held low for the
  entire first braking window; the pin both released (≥ 300 ticks high) **and** not
  stuck released (≤ 10000 ticks) across the cruise windows — the hunt signature;
  `I_charge` ≥ 0.25 A despite the gate; GENSTAT 001 (Low Power) observed; and
  MPPT_EN set with PWR_TRACK clear.
- **Why useful:** this entry asserts a model prediction contingent on open hardware
  question R1 (is an MPPTS resistor fitted?). A campaign that does not hunt is
  evidence about R1, recorded as a hardware finding — the scenario converts an open
  question into a measurable observable.
- **Baseline, and its repeat class (informational — no check reads the count):**
  the hunt has now been measured twice. `MPPT_DISABLE` toggles **138**
  (`hil_report_20260831_191509`) and **134** (`_222036`) — a 2.9 % move — while the
  median hunt PERIOD repeats to 0.02 % (**40.0575 ms** against the 40.05 ms record).
  The period is the stable observable and the count is not: the count is the period
  divided into a window whose ENDS are decided by where the cruise windows fall
  relative to a toggle, so a sub-period shift at either end changes it by ±1 with
  nothing physical moving. Read a count move of a few percent as phase; read a
  PERIOD move as real. The scored bounds (≥ 300 / ≤ 10000 ticks high) are far from
  both numbers by design.

## 5. Source-model endurance

### soc-depletion (400 s in the suite, any engine, suite forces `--soc0 0.20`)

- **Tests:** a sustained battery-only load (share railed to 0.0, so FC_BUS is cut
  and BT carries everything): V_batt walks down the OCV curve toward
  `LIMIT_V_BATT_MIN` — the honest UV_BATT path.
- **Pass/fail:** only `FAULT_UV_BATT` is allowed (not required — arrival depends on
  `--soc0`/`--capacity-ah`); the board must survive the load ramp to t = 13 in Run;
  and a disjunctive depletion proof must hold: SoC fell by ≥ 0.05 **or** UV_BATT
  latched after the ramp. The two arms foreclose each other, so either satisfies
  the objective. Measured latch: 270.7 s against the ~273 s estimate.
- **Why useful:** the only long-horizon pack-model coverage, and the only path to a
  genuine (not sensor-injected) UV_BATT. The disjunctive gate replaced a threshold
  that was physically unreachable and had rubber-stamped a dead board.

## 6. EMS (Mode A) scenarios

### 6.0 Strategy roles, and the cross-run EMS frontier check

Every EMS strategy carries a **role** in `hil_plant_sim.EMS_STRATEGY_META`
(`policy_file` + `frontier_eligible`), and the role decides how a run's energy
numbers may be read.

| role | strategies | what a run's `h2_cum_g` / `delta_soc` mean |
|---|---|---|
| **frontier** (`frontier_eligible: True`) | `soc-band` (causal heuristic, the eq-H2 **reference**), `sdp-v3` (causal calibrated policy, the **candidate**), `dp-replay` (non-causal offline **bound**) | an energy-management result, ranked by the frontier check below |
| **demonstration** (`frontier_eligible: False`) | `sdp-v2`, `hold-5050`, `regen-harvest`, `mppt-harvest`, the four `y-*` profiles | a measurement of the MECHANISM the run puts on the wire — **not** a competitive score. These runs are excluded from the frontier check by construction and carry a demonstration banner in REPORT.md and in their per-run `ANALYSIS.md`. |

**The EMS frontier check** (`run_hil_suite.py`, `evaluate_ems_frontier()`) is the
suite's only CROSS-RUN assertion. It exists because an energy-management result is a
comparison and no per-run threshold can express one: campaign `20260901_000816`
shipped 53/53 PASS with a 9.9 pp policy regression in it. Legs are compared on
SoC-corrected hydrogen,

```
eq_H2(run) = h2(run) - (dSoC(run) - dSoC(ems-soc-band)) / lambda
```

so a leg that ends with more charge left is **credited** the hydrogen it did not
have to burn. `lambda = 0.41 SoC/g` is the MEASURED share lever (campaign
`20260831_191509` priced share-shifting at 0.409–0.415 SoC/g on two independent
stimuli; the offline DP solve says 0.405). The two assertions are

- `eq_H2(ems-sdp) <= 0.98 x eq_H2(ems-soc-band)` — the optimal-by-construction leg
  must beat the heuristic by at least 2 %, and
- `eq_H2(ems-sdp) <= 1.06 x eq_H2(ems-dp-replay)` — it must stay near the
  non-causal bound it cannot reach. ⚠️ 1.06 is a first-campaign bound on the
  calibrated artifact; the intent is to **tighten it to 1.03** after two `sdp-v3`
  campaigns have measured the leg's spread.

Verdicts other than PASS: **KNIFE-EDGE** when the verdict flips anywhere inside the
measured lambda band \[0.409, 0.415] (lambda is known to ~1.5 %, so such a result is
not a result — neither PASS nor FAIL); **UNVERIFIED** when a leg is missing, skipped,
or failed its own checks, or when the legs' `delta_soc` differ by more than 0.010 SoC
(the correction is a linear extrapolation and is not credible over a large gap).
Anything but PASS counts as a failing suite run and is NAMED in REPORT.md — a
silently dropped leg is exactly how the regression above went unnoticed.

⚠️ `h2_cum_g` is the Gfc **model's estimate**. The map is scale-portable, but the
coefficients are not identified against this rig's stack (`TODO(calibrate)`), so
every frontier number is a RANKING on one rig and not an absolute mass.

### ems-drive-cycle (58 s, any engine, EMS `hold-5050`)

- **Tests:** a full accelerate / two-level cruise / decelerate / stop drive cycle
  commanded by the emulated Pi EMS layer at 50 Hz, ending Run → Finish → Idle at
  `EMS_RUN_EXIT_S`.
- **Pass/fail:** expected fault-free (no table entry). It is the suite's unattended
  drive-loop coverage; deceleration is gentler than coast so no regen branch is
  entered.
- **Why useful:** end-to-end validation of the Youla drive controller, the
  zero-cutoff, and the Mode-A command path on a realistic profile; it is the
  scenario whose sub-1 % repeatability anchors cross-campaign comparisons.

### ems-soc-band (61 s, any engine, EMS `soc-band`)

- **Tests:** the causal charge-sustaining EMS: a drain phase walks SoC out of the
  policy band so the split biases toward the fuel cell, then a quiet 1.0 m/s cruise
  admits an opportunistic FC-path charge window. The H2 metric runs end to end.
- **Pass/fail:** fault-free; in Run at t = 41; `cmd_share_sp` ≥ 0.60 (the policy
  biased); `I_fc` ≥ 0.85 A (the board acted on it); `I_charge` ≥ 0.5 A in the
  charge window; and `h2_cum_g` ≥ 1 × 10⁻³ g (the accounting ran). Thresholds are
  modelled; a miss moves the drain magnitude, never the threshold.
- **Why useful:** all three branches of the `soc-band` policy execute separably in
  one trace, and the run is one half of the DP benchmark comparison.

### ems-dp-replay (61 s, hifi only, EMS `dp-replay`)

- **Tests:** the identical cycle and drain (same profile list object as
  `ems-soc-band`), driven by the non-causal offline-optimal DP setpoint table.
  It is the benchmark the causal strategies are ranked against on `h2_cum_g` and
  terminal SoC.
- **Pass/fail:** fault-free; in Run at t = 50; `cmd_share_sp` ≥ 0.74 in (12, 20) s —
  the DP's early FC rail, unreachable by any causal policy that early, i.e. the
  "is this actually the DP table?" check; `I_fc` ≥ 0.95 A; and `h2_cum_g` ≥ 2 ×
  10⁻³ g. No charge check by design: the DP opens the charger on zero stages, which
  is a finding (share-shifting buys 0.405 SoC/g against the Ag105's 0.169).
- **Why useful:** matched-terminal-SoC hydrogen comparison against `ems-soc-band`
  (−14.33 % offline, −9.4 % live) is the thesis-level EMS result; the startup
  fingerprint refusals guarantee the table and the stimulus cannot drift apart.

### ems-sdp (61 s, any engine, EMS `sdp-v3` — THE BENCHMARK LEG)

- **Tests:** the identical cycle and drain again (the same profile list object as
  `ems-soc-band` and `ems-dp-replay`), driven by the causal stochastic-DP policy —
  a table indexed by STATE (SoC x demand bin) baked offline by
  `tools/sdp_ems_solver.py`. It is the causal optimal-by-construction leg between
  the `soc-band` heuristic and the non-causal `dp-replay` bound.
- **Pass/fail:** fault-free; in Run at t = 50; the profile's 1.5 m/s cruise
  commanded; `cmd_share_sp` >= 0.84 (the policy's fuel-cell rail, emitted at the
  0.85 hardware-envelope clamp — a level neither sibling can reach); the PRE-CLAMP
  `cmd_share_sp_raw` measured two-sided at the interior 0.95 on the drain plateau
  and back at the 1.00 rail on the low cruise (the checks that identify the v2
  demand map, since every table value clamps to the same emitted 0.8500);
  **`FC_CHARGE_ENABLE` never opens** (`max_ticks: 0`, whole post-grace run);
  `I_fc` >= 1.00 A; and the two hydrogen accumulators.
- **Why useful:** the third leg of the three-way EMS comparison on one stimulus,
  and the one leg `run_hil_suite.py`'s **EMS frontier check** scores as the
  candidate (eq-H2 at lambda 0.41, against `ems-soc-band` and `ems-dp-replay`).
- **⚠️ REBOUND TO `sdp-v3` (2026-09-01, the charge-economics ruling).** Campaign
  `20260901_000816` measured this leg OFF the frontier: +12.78 % over the DP
  bound and 1.54 % worse than the heuristic, because v2's alpha admits the
  Ag105 charge lever (0.2364 SoC/g) below its own 0.1946 SoC/g admission
  threshold while the campaign prices share-shifting at 0.409-0.415. The
  artifact `tools/sdp_policies/sdp_policy_v3.json` (policy-block sha256
  `0443febf…`) re-derives alpha by two-sided lever calibration and the charge
  action is then declined **ENDOGENOUSLY** — zero charge cells in all 101 x 25,
  `forbid_charge_all` FALSE. So the old `sdp_charge_window_opened` check is now
  its inverse, `charge_path_never_opens`. **The share axis is unchanged:** v2
  and v3 differ in `policy.share` on SoC rows 1-2 only, which this trajectory
  (row 50, falling ~0.0017) never reaches — but every share band above was
  CALIBRATED on v2 campaigns and the first v3 campaign is expected to repeat
  them.

### ems-ftp75-sdp (350 s, any engine, EMS `sdp-v3`, gated behind `--with-ftp75`)

- **Tests:** the SDP policy's **bang-bang share law**, on the same FTP-75 profile
  object as the other two FTP-75 scenarios. The scenario key
  `sdp_soc_ref_offset = +0.013` starts the run 0.013 SoC **above** the policy's
  target node, i.e. on the table's battery-heavy branch (raw action 0.00, emitted
  at the clamp as 0.15); the cycle's own drain then walks the state across the
  switching boundary and the command steps ONCE to 0.85. Every `ems-sdp`-family
  run before this round started exactly on the node and could only discharge, so
  the wire carried one constant 0.8500 for the whole run.
  The preload is **0.45 A**, not the siblings' 0.65 A: at 0.65 the fuel-cell
  branch's governed peak is 1.355 A, 3.2 % under `LIMIT_I_FC_MAX`, and an OC_FC
  latch would truncate the run at exactly its post-flip half.
- **Pass/fail:** fault-free (`allow_only: 0`, stricter than the socband sibling
  deliberately); in Run at t = 260; the 3.0 m/s peak commanded; `cmd_share_sp`
  never above 0.16 over (20, 150) s and reaching 0.84 over (250, 340) s — together
  a measured crossing inside **t = 150..250 s**; the same span on
  `cmd_share_sp_raw` (<= 0.01 then **>= 0.89** — the floor must admit demand bin
  24's 0.90 request, not just the 0.95/1.00 pair), which is what identifies the TABLE's
  branch rather than the emitted level; `I_fc` <= 0.45 A early (the commanded 0.15
  is below the minority governor's floor, so delivered FC is pinned at 0.300 A)
  and >= 1.00 A at the cycle peak; `h2_cum_g` in [0.020, 0.12] g.
- **Why useful:** the only run in the suite that puts the SDP policy's switching
  law itself on the wire. ⚠️ Every band is FIRST-CAMPAIGN PROVISIONAL, from an
  offline walk; the flip-time band is +/-20 % of the walk's 195.9 s because the
  flip time is an integral of the drain.
- **⚠️ REBOUND TO `sdp-v3` (2026-09-01), AND THE WALK TRANSFERS VERBATIM.** The
  offline walk was measured against v2 and was NOT re-run, because a row-by-row
  diff of the two baked tables shows it does not need to be: `policy.share` is
  identical at every SoC row from 3 upward (the artifacts differ in 30 cells,
  all on rows 1-2), and this scenario spans rows ~63 down to ~44. Every number
  above — the 0.15/0.85 emitted pair, the {0.00} / {1.00, 0.95} raw requests,
  the 195.9 s flip and its (150, 250) s band — is arithmetically the same under
  v3. On the CHARGE axis, v2's cells sit in demand bins 0-5 only and this
  walk's demand never falls below bin 9 in Run, so v3's zero map removes cells
  the trajectory could not visit either way: "no charge stage is reachable" was
  already the claim, and under v3 it is additionally true by construction.

### ems-sdp-cross (200 s, any engine, EMS `sdp-v2` — DEMONSTRATION)

- **Tests:** both of the artifact's SoC switching surfaces in one run. A two-level
  cruise (2.2 m/s to t = 70, then 1.0 m/s) with `sdp_soc_ref_offset = +0.0025`
  gives the downward SHARE crossing at t ≈ 44 s, and the low cruise — P_dem
  5.37 W, the top charge-admissible bin — then produces the CHARGE threshold's own
  minimum-dwell limit cycle: three ~8 s windows about 50–57 s apart.
  ⚠️ An UPWARD share crossing is **not reachable on this rig**: raising SoC through
  the 1e-3-wide dead band around the target node inside one `SDP_CHG_MIN_DWELL_S`
  latch needs a charge ceiling above 2.25 A, which on the single-source FC path is
  an immediate OC_FC. Nothing here asserts one.
- **Pass/fail:** fault-free; in Run at t = 180; `cmd_share_sp` at the 0.15 clamp
  over (5, 25) s and reaching 0.84 over (65, 190) s (a crossing inside 25..65 s);
  `cmd_share_sp_raw` <= 0.01 early; `FC_CHARGE_ENABLE` open >= 12 s across the low
  cruise **and** released for all but 2 s of (90, 108) s — the pair is what makes
  it a cycle rather than one latched window; `I_charge` >= 0.5 A.
- **Why useful:** the first live exercise of the charge dwell latch as a
  hysteresis, and of `charge_hold_status()`'s cruise-guard early drop (one ~1 s
  admit-then-drop lands inside the deceleration by construction — expected, and
  deliberately not asserted). No board-side share check is possible at this
  operating point and the entry says so: the governor clips both branches to
  within 0.07 A of each other at 0.67 A of total. ⚠️ FIRST-CAMPAIGN PROVISIONAL.

### ems-sdp-braking (134 s, any engine, EMS `sdp-v2` — DEMONSTRATION)

- **Tests:** the policy's charge decision on the **demand axis alone**. Four
  braking cycles (10 s at 2.2 m/s, 3 s decel to 1.0 m/s, 12 s plateau, 6 s accel
  back) with `sdp_soc_ref_offset = -0.005`, which pins the share command at a
  constant 0.85 for the whole run by design — so with the SoC axis held still,
  every FC_CHARGE transition is attributable to demand: the plateaus are bin 5
  (charge-admissible) and the cruises bin 10 (forbidden).
  ⚠️ **The SoC rise is fuel-cell-fed through FC_CHARGE, not regen harvest.** The
  plant floors regen power at zero, so this validates the policy's decel-window
  charge behaviour and NOT regen capture.
- **Pass/fail:** fault-free; in Run at t = 100; `cmd_share_sp` bounded in
  [0.84, 0.86] for the whole run (asserted from both sides — that bound is what
  licenses the attribution); `FC_CHARGE_ENABLE` open >= 25 s of the walk's 50.1 s
  across the plateaus and closed for all but 0.5 s inside two of the 2.2 m/s
  cruise holds; `I_charge` >= 0.4 A.
- **Why useful:** the correlation — charging ON in the low windows and OFF in the
  cruises — is the cleanest available attribution of a policy action to the demand
  axis. The charge ceiling (0.7 A) and the acceleration rate (0.20 m/s²) are both
  **current-budget constants**: the cruise guard withdraws the charge latch only
  at the NEXT decision, so the charger can still be open one second into an
  acceleration, and at 0.40 m/s² with the usual 0.8 A ceiling that peak is 1.379 A
  — 1.5 % under `LIMIT_I_FC_MAX`. ⚠️ FIRST-CAMPAIGN PROVISIONAL.

### ems-y-b30-v1 / ems-y-b30-v3 (49 s, any engine, preloaded)

- **Tests:** the firmware's own 16-region 'Y' combined drive-cycle + power-share
  table, commanded from the EMS layer at Vmax 1 or 3 m/s with share bound b = 0.30.
  The **0.85 A** preload (`Y_AUX_LOAD_A`, raised from 0.60 A on 2026-08-31) holds the
  source total in 1.00–2.27 A, above the 0.60 A governor gate, so this is
  **closed-loop share tracking**. ⚠️ At the old 0.60 A the firmware's
  minority-current governor clipped the share to 0.624 / 0.672 at region 6 — *below*
  the table's own 0.70 clip — so the hi bound was **undeliverable** and b30 runs
  characterised the governor instead. b30 results do **not** compare across that
  change; b00 (no preload) is unaffected.
- **Pass/fail:** fault-free; survive to the end of the last moving region (t = 43)
  in Run; the share axis reaches its 0.70 clip in region 6 and sweeps back down by
  ≥ 0.30 across region 10; the motor axis reaches 0.95·Vmax at the region-7 ramp
  top; and `I_fc` exceeds a per-Vmax floor (**0.50 / 0.66 A**) over region 3 alone
  (13.0–16.0 s, where v is held constant so only the share command moves `I_fc`),
  proving the board acted on the bias. ⚠️ Both the window and the floors were
  RE-DERIVED FROM MEASUREMENT on 2026-08-31 (campaign `hil_report_20260831_191509`):
  the previous (13–20 s) window swallowed region 4's ramp, where a plain 0.50 split
  alone reaches 0.49 / 0.92 A, and the modelled 0.58 / 0.80 floors sat ABOVE the true
  run's own region-3 peaks (0.5659 / 0.7606 A). All windows are derived from the
  imported region table, not typed.
- **Why useful:** exercises the two loops' cross-coupling on the firmware's own
  profile geometry, with the clip band as a designed observable.

### ems-y-b00-v1 / ems-y-b00-v3 (49 s, any engine, no preload)

- **Tests:** the same table with b = 0.00: regions 6 and 11 command share 1.00 and
  0.00, outside [`DROOP_R_MIN`, `DROOP_R_MAX`], so `updateShareSetpointCutoff()`
  cuts and then restores each bus switch — **cut-and-restore topology**. No preload
  (a preload would exceed the cut's 0.5 A/channel guard), so the share loop runs
  open-loop feedforward — entirely at Vmax 1, and for ~4/5 of the run at Vmax 3
  (only **20.6 %** above the gate, campaign `hil_report_20260831_191509`; the model
  walk over the TABLE alone gives **12.7 %** — a different denominator, and the two
  have NOT been reconciled: take 20.6 % as the measurement and 12.7 % as an
  independent order-of-magnitude agreement, not as a discrepancy anyone has
  explained). Cut/restore
  verdicts are sound; share *amplitude* read off these runs is not.
- **Pass/fail:** fault-free; the same two axis sweeps and the motor-peak check as
  b30; plus four switch assertions — BT_BUS cut in region 6 and restored in
  region 7, FC_BUS cut in regions 10/11 and restored in regions 12/13.
- **Why useful:** the restore assertions are novel coverage — before these entries,
  nothing in the suite had ever checked that the setpoint latch releases, only that
  it takes.
- **Undocumented asymmetry, recorded not explained (campaign
  `hil_report_20260831_222036`):** b00-v3 emits an `sw_ring` sidecar event on the
  FC_BUS cut and b00-v1 does not, on otherwise identical switch sequencing. The
  plausible reading is that at Vmax 1 the channel current at the cut is below the
  hi-fi engine's ring-detection threshold, so the same physical cut produces no
  event — but nobody has verified that, and no check reads the event either way.
  Do not treat a missing FC_BUS ring on the low-speed variant as a finding until
  it is.

### ems-ftp75-5050 / ems-ftp75-socband (350 s each, any engine, gated behind `--with-ftp75`)

*(`ems-ftp75-sdp` is the third member of this gated set and has its own entry
above, with the EMS scenarios it belongs to.)*

- **Tests:** the first 340 s of the EPA FTP-75 cycle, scaled to a 3.0 m/s peak,
  driven by `hold-5050` and `soc-band` respectively — an endurance test of the EMS
  layer (~30 accelerate/cruise/decelerate/idle cycles, 345 s of continuous 50 Hz
  commanding) rather than a transient one. A 0.65 A preload keeps the share loop
  closed through the cycle's idle segments; it also forecloses the `soc-band`
  charge window by construction.
- **Pass/fail:** *5050:* fault-free; in Run at t = 300; the 3.0 m/s peak commanded
  at t ≈ 245; `I_fc` ≥ 0.70 A at the peak; `h2_cum_g` in the measured band
  **[0.045, 0.085] g** (measured 6.47 × 10⁻²). *socband:* `FAULT_OC_FC` additionally
  allowed (the 0.75 share ceiling leaves only **11.3 %** of peak margin against the
  measured 1.2414 A — the model budget under-predicts currents by a systematic
  +2.6 % — and an OC there is the correct hardware response, operator ruling (b));
  share bias ≥ 0.60 commanded and `I_fc` ≥ **0.95 A** delivered over (30, 340) s
  (re-derived AGAIN 2026-08-31: `min_value` is a PEAK-over-window test, and the
  constant-0.50 `ems-ftp75-5050` sibling peaks at 0.8275 A over the same window, so
  any floor at or below that discriminates nothing; 0.95 A sits 15 % above it and
  23 % below the measured socband peak 1.2414 A. The earlier 0.70 A and 0.55 A
  figures were derived against instants rather than window peaks);
  `h2_cum_g` keeps the conservative 5 × 10⁻³ g floor (an allowed OC_FC latch
  truncates the total) plus a **0.115 g ceiling** (measured 9.16 × 10⁻²).
  ⚠️ `soc-band` **saturates its bias at 0.75 by t = 46.8 s and holds it for the
  remaining 298 s** — past that point the run tests the firmware's share loop under
  one fixed setpoint, not the policy's law.
- **Why useful:** the longest accounting runs in the suite, on a cycle a reader
  outside the project recognises; skipped by default purely on run time (~17.5 min
  for the three, `ems-ftp75-sdp` included).

## 7. Share-loop and topology scenarios

### handoff-sag (24 s, hifi only)

- **Tests:** the TP0178/TP0201 class: at a 0.74 A pre-load the share setpoint is
  railed to 0.0, so the setpoint latch cuts FC off the bus; a +1.5 A step at t = 20
  then probes the single-source sag depth and the UV dwell decision. A reactive
  standby pickup is *not* reachable from a setpoint-latched cut (the switch is
  EN-low) — the scenario's scope is the cut's load guard and the sag, stated
  honestly in the registry.
- **Pass/fail:** only `FAULT_UV_BUS` allowed (kept as class-modelling permissiveness;
  measured min V_bus 14.43 V means it is never exercised here — OC_BT would win
  first); survive to t = 20 in Run; and `FC_BUS_ENABLE` must be open for essentially
  the whole (8, 20) s window (≤ 200 set ticks), proving the cut actually happened
  and held. The 2 s gap between the cruise step and the rail command is
  load-bearing: the drive transient must settle below the 0.5 A cut guard first.
- **Why useful:** live reproduction of a recorded bench hazard class, and the only
  scenario that measures the single-source sag against the UV dwell on the hi-fi
  droop model.

### share-staircase (47 s, any engine)

- **Tests:** two motor-free phases at two loads. Phase A (I_tot ≈ 1.2 A): a
  0.80 → 0.20 share staircase straddles the governor's [0.25, 0.75] rails — the
  clip band becomes a designed observable. Phase B (I_tot ≈ 0.55 A, below the cut
  guard): excursions to 0.95 and 0.05 cut and restore BT_BUS and FC_BUS, with all
  four edge latencies measured.
- **Pass/fail:** fault-free; survive to t = 32 in Run; the top step commanded and
  the full sweep observed on `cmd_share_sp`; `I_fc` railed to ≥ 0.80 A at the top
  and falling ≥ 0.50 A across the sweep (the board tracked, not held); both cuts,
  both restores, and four edge latencies each ≤ 40 ms — a regression tripwire (the
  measured value is the deliverable; the spread is 50 Hz command-arrival phase, not
  a firmware tick).
- **Why useful:** it converts the incidentally-measured TP0170–0180 clip band into
  a designed, bidirectional sweep, and it is the only scenario that quantifies the
  cut/restore latency rather than just their occurrence.

## 8. Hi-fi bring-up and RT1987 scenarios

### bringup (8 s, hifi only)

- **Tests:** the firmware's staged bring-up (P0–P3) from dark against the real
  RT1987 t_D(ON) and soft-start delays.
- **Pass/fail:** fault-free, plus `survive_to`: un-latched and in Idle or Run at
  t = 4.0 (~6× the measured 0.62 s completion, clear of the grace bound). The
  positive assertion exists because "no fault" is also satisfied by a board that
  never left State 0.
- **Why useful:** the canonical sequencing check — every other run depends on this
  path, and its per-phase peak currents are exact-to-four-decimals repeatable
  cross-campaign, making it a sensitive drift detector.

### scp-inrush (6 s, hifi only, `vesc_cap_f` 0.9 mF)

- **Tests:** RT1987 soft-start foldback and SCP: MOT_PWR ramps up unloaded during
  P3, a 6.5 A pulse lands mid-soft-start once V-MOT crosses 1.2 V, the foldback
  binds and cuts inside that same 1 kHz tick (deterministically ahead of any
  firmware reaction), the 64 ms retry completes to ON, and a 5.0 A run load then
  latches OC_FC.
- **Pass/fail:** judged on the events sidecar, not fault flags: exactly one
  `scp_cut` on MOT_PWR with `i_cut` in [6.15, 6.55] A (live board: 6.3797373 A,
  bit-identical across three runs) and no ring above the 20 V abs-max (the Death-5
  signature must not appear). `FAULT_OC_FC` and `FAULT_MOT_HOTPLUG` are allowed —
  both are correct outcomes of the designed sequence — and no `not_before_s` /
  `survive_to` is legal because the whole stimulus completes inside the grace
  window.
- **Why useful:** the only coverage of the RT1987 foldback/SCP state machine and
  its retry cadence. The 2026-08-31 three-phase redesign made the outcome
  deterministic, retiring the two-outcome race check that had been scoring a coin
  flip.

## 9. Operator-gated scenario

### drive (30 s, any engine, `operator_required`)

- **Tests:** plant only — the operator drives the firmware by hand over USB
  (`V`, `D`, `Y`) against injected sensors.
- **Pass/fail:** rendered SKIPPED unless `--with-operator` is given. Unattended it
  commands nothing (the board idles and the drive loop is never stepped), and
  scoring that as a PASS would advertise coverage the run does not have.
- **Why useful:** it gives an operator a scored, logged harness for ad-hoc
  hand-driven experiments inside a campaign; unattended drive-loop coverage belongs
  to `ems-drive-cycle`.

## 10. Scenarios outside this document's scope

The suite's replay half (27 curated BLG replays, including the synthetic SY0001
entry) is documented in `docs/HIL_REPLAY_LOGS.md` and is deliberately not duplicated
here.
