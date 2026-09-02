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

### v-bus-sense-offset (12 s, hifi only)

- **Tests:** the `UV_BUS_DWELL_LATCH_MS` threshold (20 ms of net accumulated
  under-limit dwell, `.ino:1460`) **from both sides**, in one run. Two sensed-`V_bus`
  excursions of −5.0 V take the measured rail to ≈ 10.9 V: the first lasts **12 ms**
  (t = 5.000–5.012) and must **not** latch; the second lasts **60 ms**
  (t = 8.000–8.060) and must. The 3 s gap lets `UV_BUS_DWELL_LEAK` (0.05) drain the
  first excursion's residue completely — it needs 12 / 0.05 = 240 ms of healthy bus,
  and gets 3 s — so the second excursion latches on its own 60 ms rather than on the
  pair's sum.
- **Pass/fail:** `FAULT_UV_BUS` is required with `not_before_s` = **7.0** — placed
  between the two excursions, so a board that latched on 12 ms of dwell fails here
  rather than passing as "it latched". Three positive signals: the excursion was
  genuinely below the limit for its whole duration; the bus recovered clear of the
  limit for the whole 3 s gap; and the latch (bit **plus** `FAULT_ERROR`) landed at or
  after the second excursion opened. Latch-instant band is **provisional** — derived
  from the geometry, not yet measured on this board.
- **Engine: hifi is required, and the mode is the experiment design.** Under the hi-fi
  engine `v_bus_offset` is **sense-path-only** (`ElectricalSim.v_bus_sense_offset`,
  added in `_rails()` and never seen by the node/diode/chopper network), so it perturbs
  the one quantity under test and nothing else. In simple mode the same offset is a
  real algebraic disturbance that the sources respond to, which would move the source
  currents, the droop split and the charger gate at the same time and confound the
  dwell measurement with all three.
- **Why useful:** this is the **home of the UV-dwell objective**, moved here in 2026-09
  from `handoff-sag`, which could never deliver it — that scenario's bus floor is
  reached on the BT rail behind an `OC_BT` latch, and the two must-NOT-latch replay
  entries (TP0178/TP0201) never cross the limit at all, so they accumulate 0.0 ms and
  are a *voltage* margin rather than a dwell one. `sag` holds the bus under the limit
  for a full second and latches, which a 5 ms threshold — or no filter at all — would
  also do. Only a paired sub- and supra-threshold excursion falsifies both failure
  directions.

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
- **Why useful:** the regen PATH coverage — the firmware's branch selection
  (REGEN high with FC_CHARGE low, `MPPT_DISABLE` low) under a stimulus that
  genuinely holds a negative command. The original scripted design coasted
  instead of braking and latched OC before its first braking window; the positive
  signal checks prevent that regression class.
- ⚠️ **Caption corrected by WP-C (2026-09-01):** this entry used to say the
  charge seen here was bus-sourced because the plant floored regen power. The
  floor is gone (`docs/HIL_PLANT.md` §3.4) and the current IS harvested. What is
  still true is that this scenario's 1.000 m/s² command is only 5 % over the
  coast rate, so the captured force is ~0.16 N and the harvest is in the
  millijoules — it is a **path** test. `regen-harvest-true` is the **energy**
  test. ⚠️ Pre-WP-C traces of this scenario are not comparable with post-WP-C
  ones (the braking force is now clipped).

### regen-harvest-true (46 s, **hi-fi required**, EMS `regen-harvest-hard`)

- **Tests:** genuine kinetic-energy capture, end to end. Three hard braking
  windows (3.0 → 0.4 m/s commanded at 1.733 m/s², which the rig **cannot**
  achieve — the regen clip caps the braking force at `K_F · VESC_REGEN_I_MAX_A`
  = 1.13 N, so the realized decel is ~1.352 m/s² and the drive controller sits on
  its negative rail for the whole window). `charge_goal` is asserted inside each
  window, so the Ag105 is fed through REGEN + MOT_PWR.
- **Why hi-fi is REQUIRED, not preferred:** the chopper objective is an
  `events.jsonl` `chopper_clamp` episode, and only the hi-fi engine emits events.
  Simple mode models the same clamp (`Plant.step()`'s lumped V-MOT node) but has
  nowhere to report an episode.
- **Pass/fail:** fault-free; in Run at t = 14.0; `REGEN_ENABLE` set for ≥ 0.5 s
  inside braking window 1; `I_charge` ≥ 0.04 A through that path (harvested, not
  bus-sourced); `V_rgn` ≥ 17.0 V inside the window (the bench signature — V-MOT
  lifting toward the 18.1 V clamp with V_bus unmoved); and at least one
  `chopper_clamp` event carrying ≥ 0.3 J.
- ⚠️ **Bands are `provisional`** — derived from the WP-C offline walk
  (2026-09-01), not from a campaign. Re-derive them after the first live run.
  The walk measured one coalesced clamp episode of 1.298 J per window, peak V-MOT
  18.15 V, and `I_charge` ~0.08 A once the Ag105 settles; the bands sit at
  roughly half those values so a degraded path fails while walk-vs-board
  modelling error does not.
- ⚠️ **Do not read SoC direction here.** The harvest is single-digit joules
  against a pack simultaneously carrying the bus, so pack SoC still falls across
  the run. Read `I_charge`, the clamp event's `energy_j`, and the plant's
  `regen_energy_j` counter.
- **Why useful:** the first scenario in the suite with energy behind the regen
  path, and the only coverage of the chopper clamp — the queued "chopper
  coverage" item. It also asserts the physical asymmetry the board is designed
  around: the TL431 chopper is the fast primary clamp and the Ag105 the slow
  secondary, so the first ~0.5 s of each window is burnt rather than banked.

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

⚠️ **THE OBJECTIVE INVERTED AT fw v24 (2026-09-01).** Everything below describes
the fw v24 expectation; the fw v23 record it replaces is kept at the end.

- **Tests:** the Ag105 MPPT input-voltage threshold made causal, AND — from fw v24
  — the firmware's **threshold manager**. The regen path holds `MPPT_DISABLE` low.
  On the low-cruise FC-path windows the module's threshold is whatever count the
  board reports on observation-frame byte 15: fw v24 writes reg `0x02` to
  (windowed-min `V_chg` − 3.0 V), clamped in COUNTS to **[15, 27] =
  12.320–13.376 V**, i.e. under the ~15.95 V bus — so the module stops refusing and
  cruise harvest HOLDS.
- **Pass/fail:** fault-free; in Run at t = 39.1; `MPPT_DISABLE` held low for the
  entire first braking window; the pin released (≥ 300 ticks high) across the cruise
  windows; **`MPPT_DISABLE` rose 3–8 times** in that span (phase-free edge census —
  one rise per charge window; the fw v23 hunt is ~69); `I_charge` ≥ 0.25 A;
  **GENSTAT 001 (Low Power) NOT sustained** (≤ 50 ticks, transient only);
  **`MPPT_EN` and `PWR_TRACK` both set** ≥ 1500 ticks; and, from the new
  `mppt_thresh_cnt` CSV column, a **written** reg-`0x02` count (bit 7 clear, i.e.
  not the `0xFF` resistor sentinel) for ≥ 9000 ticks after t = 28.1, with the count
  inside **[15, 27]**.
- **Why useful:** it is the only scenario that can tell "the hunt is absent because
  fw v24 fixed it" from "the hunt is absent because the charge windows never
  opened" — the threshold count on the wire is the positive evidence, and a run
  against a fw v21–v23 flash (16-byte frame, blank column) FAILS the count checks
  loudly instead of passing vacuously. **R1 (is an MPPTS resistor fitted?) is no
  longer a contingency:** Table 7 encodes reg `0x02` 0–250 as register mode and
  ≥251 as the resistor, so a firmware write overrides any fitted resistor.
- **✅ CALIBRATED (2026-09-01, campaign `hil_report_20260901_080905` — 15/15 PASS).**
  Every band above is now measurement-backed: rise census **(3, 5)** (measured 3, the
  exact structural prediction); `tracking_engaged` **2400** (measured 2902);
  `charging_occurred` **0.70 A** (measured peak 0.8815, and above the fw v23 hunt's own
  0.4848 peak, so a hunt regression fails it too); `threshold_written` **12600**
  (measured 12900/12900); `refusal_absent` **20** (measured 0, against fw v23's 1481);
  observed count band **[15, 19]**. Two additions came out of the same campaign:
  a **`column_range_at_least` ≥ 2** witness (`mppt_threshold_moved`), because the count
  PERSISTS across runs — it carried in at 15 from the predecessor, so the level check
  alone would pass on a run in which the manager never executed — and an **`I_fc` ≤
  1.30 A** tripwire (`mppt_fc_headroom`, measured peak 1.1638), because the OC budget
  below is this scenario's tightest margin and was unasserted until a latch. The
  `mppt_threshold_floor` check also changed KIND: `min_value` judges the *peak* and was
  vacuously true, so it now uses `floor_min_value`, which judges the in-window minimum.
  Only the range bound stays provisional (one hi-fi campaign; the ratchet span depends
  on how far `V_chg` sags under charge, and the simple engine's sag is unmeasured).
- **⚠️ HIL-MIRROR BOUNDARY.** Under `HIL_SIM` the reg-0x02 count is computed by the
  mirror from the clamp arithmetic and published on frame byte 15 — the real write path
  is bypassed. An HIL run validates the arithmetic, the clamp band and the frame
  plumbing; it says NOTHING about the write policy, the deadband, the ≤2-per-session
  ratchet or the ≤8-per-boot EPROM budget. The campaign's 5-step-per-second ratchet is a
  mirror artifact and must never be cited as write-budget evidence.
- **⚠️ The realized FC-path margin narrows.** The budget is unchanged (0.15 aux +
  ~0.06 motor + 1.0 ceiling = 1.21 A against `LIMIT_I_FC_MAX` 1.4 A, 14 %), but the
  hunt used to hold the mean charge current near HALF the ceiling, so that budget
  was never actually drawn. Continuous harvest draws the full ceiling. A first
  fw v24 campaign latching `FAULT_OC_FC` here is a budget finding (lower
  `chg_i_ceiling_a`), not a firmware defect. **Measured 2026-09-01: it did not — peak
  `I_fc` 1.1638 A, a 16.9 % margin, 3.8 % *under* the budget** — and that margin is now
  asserted directly by the `mppt_fc_headroom` tripwire rather than left to the fault
  path.
- **fw v23 BASELINE, RETIRED (kept because a regression reproduces it):** the hunt
  was measured twice — `MPPT_DISABLE` toggles **138** (`hil_report_20260831_191509`)
  and **134** (`_222036`), a 2.9 % move, while the median hunt PERIOD repeated to
  0.02 % (**40.0575 ms** against the 40.05 ms record). The period was the stable
  observable and the count was not: the count is the period divided into a window
  whose ENDS are decided by where the cruise windows fall relative to a toggle, so a
  sub-period shift at either end changed it by ±1 with nothing physical moving. The
  scored ceiling was 2200 ticks high; the ~3000-tick "stuck released" outcome it
  excluded is now the EXPECTED one, which is why it was replaced rather than
  re-tuned.

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

Alongside the frontier check, every scenario in this section is also ranked
INDIVIDUALLY against a dynamic-programming baseline solved to that run's own
terminal state of charge. The post-analysis pass
(`tools/hil_report_analysis.py --matched-dp`) reads solved baselines out of the
results database at `tools/dp_db/` and renders a per-campaign
"Delta-SoC-matched DP comparison" table. A cached baseline is accepted only
within 1e-5 SoC of the run's own terminal state of charge, which is 0.5 % of
these cycles' whole swing; a wider match reports a deviation that is not the
run's. It never solves by default, because a matched baseline costs seconds on
the 61 s cycles here and tens of minutes on FTP-75; baselines are populated
ahead of time with `tools/dp_results_db.py prefill`. The procedure, the two boundaries on the
comparison (no regen term in the DP demand model; the dynamic-versus-DC-gain
Gfc bias; the run-era auxiliary preload) and the prefill cost per cycle are in
`docs/HIL_USER_MANUAL.md` section 5.


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

**A second frontier, at drive-cycle scale (2026-09-01).** The check is now a
registry (`run_hil_suite.EMS_FRONTIERS`) rather than one tuple, and the second
entry runs the same three roles over the 340 s FTP-75 segment:

| id | reference | candidate | bound | vs reference | vs bound |
|---|---|---|---|---|---|
| `cycle61` | `ems-soc-band` | `ems-sdp` | `ems-dp-replay` | ≤ 0.98 x | ≤ 1.06 x |
| `ftp75` | `ems-ftp75-socband` | `ems-ftp75-sdp` | `ems-ftp75-dp` | ≤ 1.02 x | ≤ 1.06 x |

⚠️ **The drive-cycle bands do NOT assume the DP wins, and that is the
substantive difference.** The offline solve measured the DP at **−0.01 % vs
`soc-band` at matched terminal SoC** on this cycle — a tie, not the −14.33 %
the 61 s cycle shows. The DP's advantage lives on the low-demand synthetic
cycle, where share-shifting has room to move. Demanding a 2 % improvement at
drive-cycle scale would therefore fail a CORRECT candidate against a reference
the optimum itself only ties, so `vs_reference_max` is **1.02** — "not
materially worse", which is the whole available claim at this scale. The number
is **PROVISIONAL** (derived from the offline tie plus the ~0.05 % run-to-run h2
spread, not measured) and is rendered with that qualifier; re-derive it from the
first campaign that evaluates the tuple.

**Stimulus coherence: both FTP-75 splits are RESOLVED (2026-09-01).** eq-H2
corrects for SoC, not for demand, so legs that ran different stimuli are ranked
on the stimulus difference. A precondition checks the legs' `ems_v_profile` /
`duration_s` / `ems_run_exit_s` / `aux_preload_a` / `chg_i_ceiling_a` against
the registry BEFORE any comparison — knowable before a run starts, which
matters when the alternative is 17 minutes of incomparable numbers. It used to
find two splits in the FTP-75 tuple, and finds none today:

1. **The load-bearing one, resolved by removal.** `ems-ftp75-sdp` ran
   `FTP75_SDP_PRELOAD_A` = 0.45 A while the reference and bound ran
   `FTP75_PRELOAD_A` = 0.65 A, so the candidate carried 0.20 A less
   housekeeping load for 340 s — roughly 1.1 kJ of bus energy it never
   supplied — and would have "won" on avoided load. The operator ruling took
   `aux_preload_a` to **0.0 on every drive-cycle scenario**, so both constants
   now hold the same value. Neither of the two resolutions recorded here
   before was taken; the current budget that forced the split apart is no
   longer binding (the governed FC peak on the 0.85 branch is 0.7046 A against
   `LIMIT_I_FC_MAX` 1.4 A).
2. **The second one, resolved by declaration — and it had to be.** The two
   policy legs capped the Ag105 at 0.8 A while the reference leg declared no
   cap and would have run at 2.5 A. It was inert only because the preload
   foreclosed `soc-band`'s charge branch, and the preload removal REOPENS that
   branch, so the split would have become live. `ems-ftp75-socband` now
   declares the siblings' **0.8 A**. `ems-ftp75-5050` still declares nothing,
   correctly: `hold-5050` never commands `charge_goal` and is not a leg of
   this tuple.

So the `ftp75` frontier is expected to render a real verdict from here on.
`stimulus_mismatch_exit_affecting` stays **False for one more campaign** — no
campaign has yet evaluated this tuple, so the first one to do so should confirm
the precondition passes before a mismatch is made exit-affecting. The `cycle61`
tuple's own coherence IS exit-affecting already: its three legs are documented
to share one stimulus object, so a split there would be a regression.

⚠️ **Baseline-era boundary.** Campaigns up to and including
`hil_report_20260901_151156` ran the FTP-75 legs at 0.65 A (0.45 A on the SDP
leg). Their hydrogen and SoC totals are NOT comparable with anything after
2026-09-01: 5050 0.0647 g / ΔSoC −0.02648; socband 0.09159 / −0.01533; sdp
0.0622 / −0.01845; dp 0.09291 / −0.01478. `constants_hash` moved, and so did
the `ems-ftp75-dp` table's `profile_fingerprint` (`aux_preload_a` is a
fingerprinted key, so a stale table is refused at load).

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
  The preload is **0.0 A** since 2026-09-01, as on every sibling. It was 0.45 A
  (not the siblings' then-0.65 A) because at 0.65 the fuel-cell branch's
  governed peak was 1.355 A, 3.2 % under `LIMIT_I_FC_MAX`, and an OC_FC latch
  would have truncated the run at exactly its post-flip half. At preload 0 that
  peak is **0.7046 A**, 50 % under the limit, so the de-rating is moot — and
  the constants' equality is what resolves the drive-cycle frontier's stimulus
  split. ⚠️ The flip moves LATE with the load: governor walk **t = 272.0 s** at
  preload 0 (against 195.9 s walk / 198.537 s measured at 0.45 A), so the
  transition band is re-opened to **(240, 295) s** and every threshold on this
  entry is PROVISIONAL again.
- **Pass/fail:** fault-free (`allow_only: 0`, stricter than the socband sibling
  deliberately); in Run at t = 260; the 3.0 m/s peak commanded; `cmd_share_sp`
  never above 0.16 over (20, 185) s and reaching 0.84 over (212, 340) s — together
  a measured crossing inside **t = 185..212 s**; the same span on
  `cmd_share_sp_raw` (<= 0.01 then **>= 0.89** — the floor must admit demand bin
  24's 0.90 request, not just the 0.95/1.00 pair), which is what identifies the TABLE's
  branch rather than the emitted level; `I_fc` <= 0.35 A early (the commanded 0.15
  is below the minority governor's floor, so delivered FC is pinned at 0.300 A)
  and >= 1.08 A at the cycle peak; `I_batt` <= 0.90 A run-wide (a tripwire on the
  branch handover, where its peak lands); `h2_cum_g` in [0.056, 0.070] g.
- **Why useful:** the only run in the suite that puts the SDP policy's switching
  law itself on the wire.
- **✔ CALIBRATED (campaign `20260901_024231`), the `provisional_note` deleted.**
  Measured: flip at **t = 198.537 s** (walk 195.9, +1.35 %), one transition, both
  rails on the wire; raw 0.00 flat pre-flip and 1.00 with 0.95 dips post-flip
  (**bin 24 was not entered**, so the 0.89 raw floor stays at its boundary-case
  value rather than being tightened to the measured 0.95); `I_fc` peaks 0.3039 A
  pre-flip and 1.1516 A at the cycle peak; `I_batt` peaks 0.7117 A at the flip;
  `h2_cum_g` 0.0621749 g. This is the walk's best result — an integral quantity
  landing inside 1.4 % — and it is the one SDP-interior scenario whose drain is
  carried by a **closed** share loop throughout, which is exactly what
  `ems-sdp-cross`'s walk did not have.
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
  gives the downward SHARE crossing at t = 42.3 s, and the low cruise — P_dem
  5.37 W, the top charge-admissible bin — then produces the CHARGE threshold's own
  minimum-dwell limit cycle: **nine ~8 s windows at a 16.13 s period** (measured,
  campaign `20260901_024231`; the offline walk predicted three at ~52 s, see
  below).
  ⚠️ An UPWARD share crossing is **not reachable on this rig**: raising SoC through
  the 1e-3-wide dead band around the target node inside one `SDP_CHG_MIN_DWELL_S`
  latch needs a charge ceiling above 2.25 A, which on the single-source FC path is
  an immediate OC_FC. Nothing here asserts one.
- **Pass/fail:** fault-free; in Run at t = 180; `cmd_share_sp` at the 0.15 clamp
  over (5, 35) s and reaching 0.84 over (50, 190) s (a crossing inside 35..50 s);
  `cmd_share_sp_raw` <= 0.01 early. The charge limit cycle is asserted by **four
  phase-free properties** over (70, 190) s: `FC_CHARGE_ENABLE` open >= 45 s
  (`sdpx_charge_cycled`), no single window longer than **9.0 s**
  (`sdpx_charge_max_hold` — the 8.0 s dwell plus one decision stage), the switch
  set on at most 84000 of the window's 120000 ticks (`sdpx_charge_released_fraction`
  — a released fraction of at least 0.30), and **6–12 rising edges**
  (`sdpx_charge_window_count`). Plus `I_charge` >= 0.75 A and `I_fc` <= 1.28 A.
- **Why useful:** the first live exercise of the charge dwell latch as a
  hysteresis, and of `charge_hold_status()`'s cruise-guard early drop (one ~1 s
  admit-then-drop lands inside the deceleration by construction — expected, and
  deliberately not asserted). No board-side **share-branch** check is possible at
  this operating point and the entry says so: the governor clips both branches to
  within 0.07 A of each other at 0.67 A of total.
- **✔ CALIBRATED (campaign `20260901_024231`), the `provisional_note` deleted —
  and this scenario is where the round's one FAILURE came from.** Measured: flip
  **42.292 s**; **9 charge windows**, period **16.13 s**, gaps 8.04–8.08 s
  (σ 17 ms), 64103 of 120000 ticks set (released fraction 0.466), longest hold
  **8.085 s** = dwell + 1.1 %; `I_charge` reached its full 0.8000 A ceiling;
  `I_fc` peaked 1.1920 A (14.9 % under `LIMIT_I_FC_MAX`). Both switching surfaces
  were located for the first time — share at SoC 0.69800, charge at 0.69700, both
  on the predicted grid nodes.
- **⚠️ THE RETIRED CHECK, AND THE LESSON.** `sdpx_charge_released_between`
  asserted the ABSENCE of a charge window over t = 90..108 s, an instant taken
  from the walk's ~52 s period. The board's period is 16.13 s — **the walk was
  wrong by 5.7×** — so the window sat on top of a charge window and failed a
  correct board. Root cause: the walk applied the firmware's **closed-loop**
  minority governor at a 1.0 m/s cruise drawing I_tot ≈ 0.355 A, below the
  firmware's 0.55 A open-loop drop-out. The board holds its last converged split
  there and **delivered 0.1656 against the commanded 0.85**, so the pack drained
  at −3.90e-5 SoC/s rather than the walked ~6.9e-6. Phase-locked absence
  assertions are now discouraged in favour of `max_continuous_ticks` /
  `edge_count_between`; see the strategy-authoring note in `hil_plant_sim.py`.

### ems-sdp-braking (134 s, any engine, EMS `sdp-v2` — DEMONSTRATION)

- **Tests:** the policy's charge decision on the **demand axis alone**. Four
  braking cycles (10 s at 2.2 m/s, 3 s decel to 1.0 m/s, 12 s plateau, 6 s accel
  back) with `sdp_soc_ref_offset = -0.005`, which pins the share command at a
  constant 0.85 for the whole run by design — so with the SoC axis held still,
  every FC_CHARGE transition is attributable to demand: the plateaus are bin 5
  (charge-admissible) and the cruises bin 10 (forbidden).
  ⚠️ **The SoC rise is fuel-cell-fed through FC_CHARGE, not regen harvest** —
  not because regen is floored (WP-C 2026-09-01 removed that floor) but because
  this policy never opens the REGEN path, so no harvested joule can reach the
  pack here whatever the plant models. This validates the policy's decel-window
  charge behaviour and NOT regen capture; `regen-harvest-true` is the capture
  scenario.
- **Pass/fail:** fault-free; in Run at t = 100; `cmd_share_sp` bounded in
  [0.84, 0.86] for the whole run (asserted from both sides — that bound is what
  licenses the attribution); `FC_CHARGE_ENABLE` open >= 45 s across the plateaus
  and closed for all but 0.1 s inside two of the 2.2 m/s cruise holds;
  `I_charge` >= 0.65 A; `I_fc` <= 1.32 A; and **8–10 rising edges** of
  FC_CHARGE over (2.5, 130) s — a CENSUS composed as four plateau windows plus
  4–6 cruise-guard early drops (`sdpb_charge_edge_census`).
- **Why useful:** the correlation — charging ON in the low windows and OFF in the
  cruises — is the cleanest available attribution of a policy action to the demand
  axis. The charge ceiling (0.7 A) and the acceleration rate (0.20 m/s²) are both
  **current-budget constants**: the cruise guard withdraws the charge latch only
  at the NEXT decision, so the charger can still be open one second into an
  acceleration, and at 0.40 m/s² with the usual 0.8 A ceiling that peak is 1.379 A
  — 1.5 % under `LIMIT_I_FC_MAX`.
- **✔ CALIBRATED (campaign `20260901_024231`), the `provisional_note` deleted —
  and this walk was RIGHT, for a stated reason.** These windows are DEMAND-driven,
  so they land on the profile's own fixed instants rather than on an integrated
  drain (contrast `ems-sdp-cross` above). Measured: four sustained windows of
  four, **52.479 s** of charging (walk 50.1, +4.7 %), longest 13.108 s, **zero**
  ticks inside both asserted cruise windows, and the walk's **five** cruise-guard
  early drops to the instant (t = 3.008 / 19.175 / 50.390 / 81.624 / 112.842) —
  the first live exercise of that branch, now censused. `I_charge` reached its
  full 0.7000 A ceiling.
- **⚠️ THE TIGHTEST OC MARGIN IN THE SUITE, now asserted.** Measured peak `I_fc`
  **1.2617 A** at t = 65.51, in the one-decision charge overhang into an
  acceleration — **9.9 % under `LIMIT_I_FC_MAX`**, and 8.1 % above what the walk
  modelled. `sdpb_fc_peak_bounded` (1.32 A) is the tripwire against a retune
  eating that margin without tripping an OC_FC latch. Never raise it to make a
  run green: the two knobs that move the peak are the charge ceiling and the
  acceleration rate.

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
  commanding) rather than a transient one. ⚠️ **The 0.65 A preload was removed
  2026-09-01** (operator ruling). It used to keep the share loop closed through
  the cycle's idle segments and to foreclose the `soc-band` charge window by
  construction; both were costs, not features. At preload 0 the idle source
  total is `I_AUX_A` = 0.15 A, so the firmware runs **OPEN-LOOP HOLD** through
  every idle segment (governor walk: open_hold 9.71 % / open_feedforward
  57.12 % / closed 33.17 % of ticks) — that mode content is now test content —
  and `soc-band`'s **charge branch is reachable again**, newly asserted by
  `socband_ftp_charge_opened`.
- **Pass/fail:** *5050:* fault-free; in Run at t = 300; the 3.0 m/s peak commanded
  at t ≈ 245; `I_fc` ≥ **0.40 A** at the peak; `h2_cum_g` in the PROVISIONAL
  band **[0.021, 0.035] g** (governor walk 2.809 × 10⁻² at preload 0; the
  6.47 × 10⁻² that stood here is the retired 0.65 A era's measurement).
  *socband:* **fault-free** — the
  `FAULT_OC_FC` allowance was RETIRED 2026-09-01 by operator ruling. It had covered the
  0.75 share ceiling leaving only **11.3 %** of peak margin against the measured
  1.2414 A, and an OC there would indeed be the correct hardware response under ruling
  (b) — but six campaigns have run this scenario and the allowance went **unused in
  every one**, while it silently excused the one fault the scenario is most likely to
  produce. Ruling (b) itself is unchanged (`charge-cruise` still *requires* OC_FC under
  it); what changed is only that this scenario is not the place to hedge. If a campaign
  latches OC_FC here now, the finding is a budget one — `FTP75_PRELOAD_A`, or the peak
  margin eroding — and deserves to be seen. Share bias ≥ 0.60 commanded and `I_fc` ≥ **0.95 A** delivered over (30, 340) s
  (re-derived AGAIN 2026-08-31: `min_value` is a PEAK-over-window test, and the
  constant-0.50 `ems-ftp75-5050` sibling peaks at 0.8275 A over the same window, so
  any floor at or below that discriminates nothing; 0.95 A sits 15 % above it and
  23 % below the measured socband peak 1.2414 A. The earlier 0.70 A and 0.55 A
  figures were derived against instants rather than window peaks);
  `h2_cum_g` in a **two-sided [0.070, 0.115] g band** around the measured
  9.159 × 10⁻² (−24 % / +26 %). The old vacuous 5 × 10⁻³ floor existed only because a
  truncated run was an allowed outcome; retiring the OC_FC allowance removes that
  outcome, so the run now always reaches t = 345 and the floor can finally bracket the
  measurement. The 9.159 × 10⁻² figure is **bit-identical across all six campaigns**
  that have run this scenario.
  ⚠️ `soc-band` **saturates its bias at 0.75 by t = 46.8 s and holds it for the
  remaining 298 s** — past that point the run tests the firmware's share loop under
  one fixed setpoint, not the policy's law.
- **Why useful:** the longest accounting runs in the suite, on a cycle a reader
  outside the project recognises; skipped by default purely on run time (~23 min
  for the four, `ems-ftp75-sdp` and `ems-ftp75-dp` included).

### ems-ftp75-dp (350 s, **hifi only**, EMS `dp-replay`, gated behind `--with-ftp75`)

- **Tests:** the drive-cycle twin of `ems-dp-replay` — the same FTP-75 stimulus
  the other three `ems-ftp75-*` scenarios run, driven by a setpoint table solved
  offline by backward dynamic programming with full foreknowledge of the cycle
  and of the auxiliary load. It is the **non-causal lower bound** leg of the
  `ftp75` EMS frontier, not a controller.
- **Stimulus:** the same `FTP75_PROFILE` list object, the same
  `FTP75_RUN_EXIT_S`, and the same `FTP75_PRELOAD_A` — **0.0 A** since
  2026-09-01, which is now also `ems-ftp75-sdp`'s value. A bound is only a
  bound over the demand it solved, so the table was **re-solved** for the
  zero-preload demand; its `profile_fingerprint` moved with the constant and a
  stale table is refused at load rather than played. `chg_i_ceiling_a` is
  declared at 0.8 A here for the solver's sake — a DP table decides charging
  for itself, so an undeclared ceiling would hand the offline-optimal leg a
  2.5 A lever the legs it bounds never had; `ems-ftp75-socband` now declares it
  too, and `ems-ftp75-5050` still does not (`hold-5050` never commands
  `charge_goal`).
- **hifi only,** for `ems-dp-replay`'s reason exactly: the shipped table is
  solved `--charger-accounting physical`, which only a hi-fi run's `h2_cum_g`
  matches, and `bind_scenario()` refuses the mismatch at startup.
- **The table:** `tools/dp_tables/dp_ems_table_ems-ftp75-dp.csv`, ~30 min to
  solve. Regenerate with
  `C:/Users/ricky/miniforge3/python.exe tools/gen_dp_ems_table.py --scenario ems-ftp75-dp --force`.
  The strategy refuses to start unless the table's `profile_fingerprint` matches
  the live scenario AND ten header-recorded model values match the live ones.
- **Pass/fail:** fault-free; in Run at t = 300; the 3.0 m/s peak commanded at
  t ≈ 245; `I_fc` carried at the peak; `h2_cum_g` inside a PROVISIONAL band
  around the DP's own predicted total (see the entry in `FAULT_EXPECTATIONS`).
- **Why useful:** without it the drive-cycle frontier has no lower bound, and a
  causal policy's drive-cycle result can only be compared with a heuristic —
  which cannot say how much was left on the table.

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
- **Why useful:** live reproduction of a recorded bench hazard class, and the
  single-source sag depth on the hi-fi droop model.
- **⚠️ THE UV-DWELL OBJECTIVE MOVED OUT (2026-09-01, operator ruling).** This scenario
  never delivered it and could not: its bus floor is reached on the BT rail behind an
  `OC_BT` latch (measured min `V_bus` 14.43 V, 2.43 V above the limit), so the dwell
  decision was never the thing being measured. **`v-bus-sense-offset` is its home now**
  — it walks the *sensed* rail below the limit for a controlled 12 ms and then 60 ms and
  so asserts `UV_BUS_DWELL_LATCH_MS` from both sides. Read no UV-threshold number off
  this scenario. The `FAULT_UV_BUS` allowance stays here as class-modelling
  permissiveness, not as coverage.

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
