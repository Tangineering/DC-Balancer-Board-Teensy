# HIL suite run 2026-08-30 20:30 — per-scenario findings

Second full `run_hil_suite.py` pass on fw v23 — the FIRST run under the suite/scenario fix
round (commit 7802466: grace-aware scoring, FAULT_EXPECTATIONS, scenario redesigns, replay
preamble/clamp rework). This file is the orchestrator's analysis ledger, one section per
run, appended as each investigation agent reports. Purposes of this campaign: (1) validate
the redesigned scenarios reach their objectives (regen path, GENSTAT collapse, SOC walk,
share-cut rail, SOFT-state fold); (2) confirm the scoring fixes (no false FAILs from
carried-in latches, no rubber-stamp PASSes); (3) catch any defect the fix round itself
introduced.

**SUITE COMPLETE (partial: false): 38 runs — 36 PASS / 1 FAIL (comm-loss, legitimate) /
1 SKIP (drive, operator_required). All 26 replays PASS.** soc-depletion (880 s) was
excluded from the plan by the operator — not an anomaly. Note: results meta reports
`target_fw: 21` — the TARGET_FW_VERSION constant was never bumped for fw v22/v23 (queued).

## Suite verdict snapshot (live, appended as runs land)

| Run | Suite verdict | Failed checks | Notes |
|---|---|---|---|
| steady | PASS | — | analyzed: baseline reproduced to 4 sig figs |
| step-load | PASS | — | analyzed: grace fix confirmed on hardware, right-reason PASS |
| sag | PASS | — | analyzed: dwell 19.992 ms vs 20.0 design; scoring bit-exact |
| ems-drive-cycle | PASS | — | analyzed: sub-1% repeat of the best drive validation; right-reason PASS |
| handoff-sag | PASS | — | analyzed: share-cut PROVEN (12 ms latency, guard at 24% margin); hifi droop = design droop (4× bench) — reconciliation queued |
| bringup | PASS | — | analyzed: staged bring-up repeatable to ~1 ms/~1 mA vs baseline |
| scp-inrush | PASS | — | analyzed: SCP cut fired (6.29 A); fold structurally unreachable without OC — 1 ms margin is the whole story |
| ML0203 (replay) | PASS | — | first replay scored under the OC_FC reclassification |
| comm-loss | FAIL | fault_allow_only | analyzed: REAL in-run OC_FC correctly scored — hifi SOFT-start pre-charged-node artifact; sim fix queued; recovery path itself validated (Δ 1.1 ms) |
| drive | SKIPPED | — | operator_required, correct new behavior |
| charge-cruise | PASS | — | analyzed: OC_FC at 8.727 s / 1.4024 A — ruling-(b) validation delivered |
| charge-regen | PASS | — | analyzed: regen path validated end-to-end ×3 windows; energy-recovery NOT validated (plant floors regen power) |
| charge-fault | PASS | — | analyzed: first GENSTAT collapse observed; readiness gate works in the loss direction |

---

## Per-run findings

(appended as analysis completes)

### steady — PASS confirmed correct; reference baseline reproduced (HIGH confidence)

First run, freshly powered board: no warm reset, Idle at t=0.1382 s (baseline 0.138). Steady
levels match the previous campaign to four significant figures: V_bus 15.8144 V, V_fc
12.9156 V, V_batt 7.8404 V (same −2.4 mV/28 s coulomb drift), I_fc = I_batt = 0.0829 A
(50/50 open-loop droop). Charger unpowered (correct). Link 30,000/30,000 tx, one
pre-first-frame blank row, 0 seq irregularities (mod-256-aware), max Δt 11.4 ms (one host
stall, no plant effect). hifi substeps median 60.7 kHz, only 0.013% of rows below 13 kHz —
cleaner than last campaign's 1.6%. Zero faults, zero events. Post-grace union 0x0 verified
by direct measurement. **No action.**

### step-load — PASS confirmed correct; the grace-scoring fix behaved exactly as designed (HIGH confidence)

The false-FAIL poster child of last campaign, now passing FOR THE RIGHT REASON, verified
bit-for-bit from the raw CSV: 0x8010 present only t∈[0.0013, 0.5001) — the settle latch
carried in from `steady` (which ended clean, matching the systematic signature) — cleared by
the warm reset at t=0.5001, and fault_flags 0x0 for all 28,000 post-grace rows. The check's
carried-in attribution text matches the measured timeline exactly; the sidecar's 1
grace-window reset / 0 mid-run matches the state trace. Step response: +1.2 A at t=5.000 →
V_bus 15.8144→15.4349 V (−0.3795 V vs baseline −0.38), I_fc = I_batt 0.0829→0.6827 A clean
50/50, settled 3 ms (baseline ~5 ms). 0 events; substeps median 60.8 kHz. **The 23-false-FAIL
fix is confirmed working on hardware. No action.**

### sag — PASS; UV chain and scoring both verified; baseline reproduced sub-millisecond (HIGH confidence)

Carried-in 0x8010 (from step-load's settle latch) observed only t<0.5, cleared by the
t=0.500445 warm reset — correctly excused. Post-grace union recomputed independently =
0x8100 exactly, bit-identical to the suite's `fault_bits_post_grace`. UV_BUS first
indication t=5.002067 (+2.067 ms after the stimulus, satisfying not_before_s=5.0);
**dwell-to-latch 19.992 ms vs 20.0 ms design** (last campaign 19.887 — Δ +0.105 ms,
reproducible within sampling jitter). Teardown 0x27→0x34→0x28→0x20, gaps 9.377/9.737 ms —
matches the ~9–10 ms baseline. 3 benign sw_ring events (FC_BUS+BT_BUS at the phase-1
opening, peak 17.76 V; FC_CHARGE at phase 2, 15.44 V; all under the 19 V OVP / 20 V absmax).
V_bus collapses 10.81→0 V in ~11 ms after isolation; V_rgn decays separately (fw v22
topology, correct). Link clean (29,999/30,000 obs frames, 0 genuine seq gaps). **No action.**

### ems-drive-cycle — PASS confirmed correct; the drive validation reproduces sub-1% (HIGH confidence)

Last campaign's false-FAIL poster child, now a right-reason PASS verified from the raw CSV:
carried-in 0x8010 only for t<0.500277 (predecessor charge-fault ended CLEAN in State 2 —
the carry-in is the settle-pause latch itself), warm reset at 0.500277, fault_flags 0x0000
on all 58,000 post-grace rows — bit-identical to the suite's `fault_bits_post_grace: 0`.
Drive regression vs baseline is essentially a bit-for-bit repeat: tracking |err| median
0.53 mm/s (was 0.5), p95 6.08 mm/s (6.1), share 0.5000 (0.4998–0.5002), I_fc peak 0.3804 A,
board peak 6.1192 A, V_bus 15.6262–15.8144, 60,000 ticks at 999.98 Hz, Run→Finish→Idle at
t=55.015 (EMS_RUN_EXIT_S 55). Zero-cutoff coast clean: 3,005 standstill rows in State 2
with current and v_actual exactly 0. Zero events; EMS cadence 2,920 pi_frames (baseline
2,917). Note for the record: `constants_hash` shifted vs baseline — expected, the fix
commit added scenario stimulus constants (SOC/HANDOFF/SCP/REPLAY families) that the
fingerprint correctly covers; every measured drive metric reproduced <1%. **No action.**

### charge-cruise — PASS correctly scored; ruling-(b) OC_FC validation delivered (HIGH confidence)

Carried-in 0x8011 (the predecessor ended latched WITH an OC_FC bit — corroborating the
comm-loss OC finding — cleared by the 0.5005 s warm reset; entire pre-8.0 window genuinely
clean, so the not_before_s gate had real work and did it). assertFcChargeEnable at
t=8.0271: switch 39→53 in one tick, no tick ever shows FC_CHARGE up with BT_BUS up
(sub-ms internal ordering unresolvable at 1 kHz — absence-of-violation verified). GENSTAT
0x00→0x04 (8.040)→0x42 (8.5404)→0x5A (8.5601) with MPPT release exactly coincident with
readiness. OC_FC trip: I_fc max 1.4024 A at t=8.726054, latch 0x8001 at 8.727071 (last
campaign 1.4065 A at 8.7221 — same mechanism, integrator-history variance). I_charge only
0.973 A at trip — the FC-side limit crosses before the charger nears its 2.5 A ceiling:
the intended infeasibility signature per operator ruling (b). Clean teardown 53→40→32,
latch held to run end. **No action.**

### charge-fault — PASS correctly scored; FIRST t=20 GENSTAT-collapse observation (HIGH confidence)

The 0.8 A chg_i_ceiling_a held exactly (I_charge flat 0.8000 A from t≈11.96 to 19.95;
zero overshoot). I_fc plateau 1.1919 A — 15% margin under LIMIT_I_FC_MAX (last campaign
OC'd at 5.758 s). Collapse at t=20.0000: I_charge 0.8→0 and GENSTAT 0x5A→0x00 same tick;
+13.5 ms: V_chg re-settles to 15.06 V, I_fc falls to 0.3723 A, MPPT_DISABLE re-asserted
LOW (readiness gate working in the loss direction — first observation). FC_CHARGE stays
open the whole remaining 20 s (open-on-intent policy; charge_goal never dropped), zero
faults, board in Run to the end — allow_only=0 genuinely satisfied. Follow-ups flagged
for the operator (not defects): (1) nothing surfaces a sustained charger-loss to the Pi —
GENSTAT 0x00 is the only observable and no informational fault class exists; (2) the
open-through-loss FC_CHARGE policy and post-recovery behavior on a real input-rail bounce
are still unverified (this plant fault is one-way). **Suite/scenario: no action.**

### charge-regen — PASS CONFIRMED REAL; regen power path validated end-to-end, three windows (HIGH confidence)

Last campaign: OC_FC at 5.585 s, 0% of regen objectives. This run: 100%, and the old
failure mechanism is confirmed absent — **FC_CHARGE_ENABLE high on 0 of 44,999 ticks;
REGEN+FC_CHARGE both-high on 0 ticks**. Switch took exactly three post-bring-up values:
0x27 cruise, 0x2F (+REGEN) braking. BT_BUS stayed HIGH through every window (the
structural reason the old OC cannot recur — charger draw shared across both channels).
- **REGEN windows**: open latencies +14/+19/+22 ms vs the charge_goal+0.20 s grid; high
  durations 1.821/1.800/1.801 s. regenActive (current < −0.1 A) led charge_goal by
  ~100 ms each window — the lead-in ordering working exactly as designed.
- **I_charge via REGEN+MOT_PWR**: peaks 1.5403/1.5371/1.5373 A (96% of the 1.6 A
  ceiling), τ 0.371 s vs AG105_TAU_S 0.4, >0.5 A for ~1.15 s per window. Per-channel peak
  0.857 A = 61% of LIMIT_I_FC_MAX (39% margin; design said 37%). Channel imbalance ≤1.1 mA.
- **MPPT_DISABLE LOW the entire run** (regen branch + charge_goal≤0.05 branch both drive
  LOW; the release path remains charge-cruise's job). CBAL active. GENSTAT never carried
  MPPT_EN/PWR_TRACK — coherent.
- **Ag105 power-cycles cleanly between windows**: 0x00→0x04 within 8-9 ms of REGEN close,
  settle 0.4985-0.4991 s vs AG105_SETTLE_S 0.5 (sub-tick agreement), 0x42 Charging|CC,
  revert to 0x00 within one tick of REGEN opening. Note: 24% of each 2.1 s window is
  charger settle, and the window is at ~the physical max (~2.2 s, a_coast-limited) — no
  headroom left in this design. Lazy re-config is NOT verified by this trace (HIL mirrors
  pollAg105 by fiat) — real-hardware item.
- **Chopper silent, correctly**: V_rgn max 15.779 V vs the 18.1 V clamp. 3 sw_ring events
  (REGEN hard-opened under full 1.54 A load each window; peak 17.14 V, over_absmax 0) —
  re-check the ring before raising chg_i_ceiling_a toward 2.5 A.
- **FIDELITY CAVEAT (do not over-read)**: the plant floors regen power at zero (the VESC
  regen-clip finding), so the ~11.5 J/window into the pack came from the boosts, not from
  braking — SOC NET FELL 0.700000→0.698580. This run validates the PATH, SEQUENCING, and
  charger state machine, not energy recovery; the chopper's silence follows from the same
  boundary.
- **Scoring**: signal margins 3.64× (REGEN ticks) / 3.08× (I_charge); post-grace union
  0x0000 over 43,000 ticks; carried-in 0x8011 (charge-cruise's own OC latch) correctly
  excused; windows 2/3 (ungated) identical to window 1 within 3.2 mA.
- **Follow-ups**: (a) docstring note that regen power is floored (SOC decrease is the
  tell); (b) chopper coverage needs a stimulus that injects energy into the motor node;
  (c) Ag105 re-config verification on real hardware; (d) ring + 5% OC margin re-check at
  the shipped 2.5 A ceiling; (e) 0.49 V bus droop under 1.54 A charger draw vs
  K_DROOP_BUS 0.074 V/A — one datapoint AGAINST the standing ~4×-below-design droop
  finding, opposite direction; worth chasing.

### comm-loss — REAL in-run OC_FC, correctly scored; ROOT CAUSE: hifi SOFT-start pre-charged-node artifact (HIGH confidence; stamp mechanism MED)

The campaign's one FAIL, and the scoring is RIGHT — the new grace machinery caught
something the old union would have blurred. Timeline: link-loss latch at 5.252406
(Δ +3.4 ms from prediction), teardown 19.1 ms byte-identical to sag's, dead window
2.2296 s, **recovery at 7.5011 (Δ +1.1 ms off the 500 ms debounce)**, staged bring-up
115.4 ms to Idle with clean flags — the fw v23 recovery path itself fully validated
AGAIN. Then OC_FC latched at 7.619454, **3.0 ms after Idle**, and the board sat dark for
the remaining 22.36 s (74.5% of the run dead).

**Mechanism (sim artifact, proven by three internal inconsistencies):** comm-loss is the
ONLY run whose bring-up closes MOT_PWR into a PRE-CHARGED node (V-MOT bled 13.86→4.39 V
over the dead window through the 2 kΩ bleed; measured vs predicted 0.1%). The RT1987
SOFT model latches v_ss_start at entry but recomputes t_on from the INSTANTANEOUS sagging
v_in every substep — a positive feedback the cold-start case (2026-08-30b fix) escapes.
Evidence: node 0.84 V ABOVE its own ramp target; V_rgn slewing at 2.05× its own ramp
rate; reported 2.77 A total vs 0.71 A physical (3.9×). Substep rate was healthy (52-54
kHz) — not a convergence issue.

**Adjudicated actions:** (a) fix tools/hil_electrical.py — latch t_on at SOFT entry
alongside v_ss_start + clamp/assert the SOFT node can never exceed its target; regression
test at v_ss_start=4.4 V/v_in=15.6/c_load=970 µF pinned-substep (QUEUED for the
post-suite fix round — sim files are frozen while the suite runs). (b) Do NOT widen
comm-loss's allow_only — that would launder the artifact and mask the only observable of
this defect class. The run stays FAIL until (a) lands. (c) Ledger note, no firmware
action: the recovery bring-up closes MOT_PWR into a pre-charged node on real hardware
too, but physically pre-charge REDUCES inrush (0.56 vs 0.78 A) — the single-sample OC
check asymmetry is recorded, risk low. (d) Reporting nit: the grace-window warm-reset
note prints both timestamps against a count of 1 — render only in-grace timestamps.

### bringup — PASS genuine; the exemplary staged bring-up is REPEATABLE to ~1 ms / ~1 mA (HIGH confidence)

Carried-in 0x8010 present only t<0.5014 (predecessor handoff-sag ended CLEAN in State 2 —
the latch is the inter-process settle gap itself), cleared by the grace-window reset;
post-grace union 0x0000 independently confirmed. Bring-up regression vs baseline: P0+P1/P2
89.6 ms peak I_fc 0.2226 A (baseline 90 ms / 0.223), P3 24.0 ms peak 0.4740 A (24 ms /
0.473), Idle at +115.0 ms total (114) — the SOFT-state physics fix's three-decimal
corroboration is now shown REPEATABLE run-to-run, not a one-off. Whole-run I_fc max 34% of
limit; 0 events; substeps mean 58.1 kHz; tail steady at the standard Idle operating point
(V_rgn tracking V_bus within 0.035 V through closed MOT_PWR). **No action.**

### handoff-sag — genuine PASS; share-cut mechanism PROVEN; UV objective structurally unreachable here (HIGH confidence)

**Proven, first time on hardware:** (1) updateShareSetpointCutoff() fires on the
out-of-band setpoint and opens FC_BUS 12.0 ms after the rail command (one share tick),
independent of the 0.60 A governor gate; (2) the SHARE_CUT_MAX_HANDOFF_A 0.5 A guard
admits the cut at 0.3779 A (24.4% under; pre-rail total 0.7558 A vs the designed 0.74,
+2.1% — the (0.60, 1.00) A bracket held exactly); one-tick whole-current transfer, bus
excursion 0.2408 V monotone settled in 3.0 ms; (3) single-source stability 14 s dead flat,
then the t=20 +1.5 A step → I_batt 2.2709 A (24.3% margin vs the designed 25%), V_bus min
14.4300 V, settle 4.7 ms, zero faults; (4) shareSpCut holds permanently — FC_BUS set on 0
ticks after the cut over 34 s. signal_fc_bus_open passed with the full 200-tick budget
unused. Carried-in 0x8010 excused correctly; post-grace union 0x0000.

**Not proven / open by construction:** the TP0178 reactive standby pickup (EN-low RT1987
does not conduct — needs a droop-driven handoff stimulus, not a setpoint latch); the UV
dwell decision (min V_bus 2.43 V above the floor; at the fitted single-source droop,
12.0 V needs ~6.1 A — OC_BT always wins first; allow_only UV_BUS is permissive but never
exercisable here); closed-loop-share observability (symmetric model → zero share error →
MDACs never move; 5316/5316 all run).

**DROOP RECONCILIATION (cross-run, closes charge-regen follow-up (e)):** fitted from this
trace, hifi droop = 0.316 Ω shared / 0.633 Ω single (ratio exactly 2.000, V₀ 15.867) —
the DESIGN droop chain (0.30 V/A at g=0.298, +5%), NOT the bench-measured
K_DROOP_BUS 0.074/0.16. charge-regen's 0.49 V sag under 1.54 A is exactly 1.54 × 0.316 —
not an anomaly. Consequence: hifi sag depths overstate the real bus by ~4× (conservative
for sag tests, not comparable to bench logs). Either reconcile hil_electrical's FB-node
superposition against the measured fit or banner hifi sag figures as design-droop.

**Follow-ups queued:** (1) the stale "+0.8 A / FC-only" comment in
FAULT_EXPECTATIONS["handoff-sag"] — same defect the round-2 reviewer found independently
(already in the post-suite fix queue); (2) the 2 s separation between the t=4 v_setpoint
(drive rail pushes I_fc to 0.623 A > the 0.5 A guard for 233 ticks, until t=4.573) and
the t=6 rail command is LOAD-BEARING and undocumented — document or widen; (3) decide the
UV objective's home (retire from this scenario or give it a v_bus_sense_offset scenario);
(4) the droop reconciliation above; (5) analyze_events discards peak_v for
non-over_absmax rings — this run's 17.578 V FC-open ring (0.078 V above LIMIT_V_BUS_MAX,
analytic-only) appears nowhere in REPORT.md; record the worst ring unconditionally.

### scp-inrush — PASS correct; SOFT-state fold/SCP FIRED (first time), dynamics differ from prediction benignly (HIGH confidence)

**One SCP cut at t=0.600000, i_cut 6.290 A** (arithmetic checks: 5.0 A load + 1.11 A CSS
ramp + blank-window lag growth; fold limit 5.36 A at dv≈15.15 V → ~0.9 A overdrive at
cut). Zero retry cycles — structurally unreachable with firmware attached: State-99
teardown pulled MOT_PWR LOW at ~10 ms post-fault, 54 ms before the 64 ms re-arm. Zero
over_absmax (no Death-5 signature; the two 17.72 V rings are the teardown's own EN-low
openings at ~0.1 A). OC_FC won the race decisively, not marginally: the SOFT conduction
interval carried I_fc 1.966 A (>1.4 limit) for ~0.95 ms ≥ one sample period — the
expectation's "~1.75 samples per retry" derivation was WRONG in premise (it assumed
over-limit current exists only in the 250 µs blank window); OC on the first fold cycle
was near-deterministic. P0 peak I_fc 0.2226 A — the SOFT-state physics fix corroborated a
THIRD time at three decimals. Carried-in bare 0x8010 (predecessor bringup ended clean —
the documented signature holds); post-grace union 0x8001 ⊆ allow_only; events_require
did real load-bearing work (baseline campaign had zero scp_cut).

**Structural finding (record):** fold binds at ≈5.36 A of boost output vs
LIMIT_I_FC_MAX+LIMIT_I_BT_MAX = 4.4 A — **no load magnitude reaches the fold without an
OC fault at any share split**; the previous campaign's "~2.5 A folds under the OC limit"
guidance was arithmetically unachievable and 5.0 A was the right call. The scenario's
honest reading: the sim mechanism fires ~1 ms before the firmware protects itself, and
that 1 ms is the whole margin.

**Follow-ups queued:** (1) tighten events_require — pin scp_cut count == 1, over_absmax
== 0, and i_cut in a plausibility band (a 0.3 A cut would pass today); (2) correct the
sampling-probability comment at the expectation entry; (3) retry-cadence coverage needs a
firmware-free hil_electrical bench, not a suite scenario; (4) optional .ino comment note
at MOT_CONNECT_TIMEOUT_MS ("covers ≥2 SCP retry cycles" is unexercisable — OC preempts).

### Replay half (26/26 PASS) — rework GENUINELY WORKING; zero wrongly-scored entries; 32/79 checks vacuous by construction (HIGH confidence)

Adversarial verification, all 26 CSVs streamed. Every high-stakes PASS is backed by a
reproduced number a permissive filter could not fake:
- **TP0010/TP0053 (UV pair, clamp+preamble):** injected I_fc max exactly 1.3000 A, zero
  over-limit samples, no OC bit; bring-up completed during the preamble (State 1 at
  0.5925 s); UV_BUS latched at 7.2992/6.9654 s — Δ 2.2/3.4 ms from the documented
  log-time qualifications — held to run end; V_fc/V_batt carried exactly the substituted
  12.9000/7.9000 nominals. **The UV-latch replay coverage is ALIVE.**
- **ML0217 (skip_preamble, INIT_FAIL):** unshifted (replay_rec 0 at t≈0), State 1 never
  reached, 0xA000 at +301.4 ms after bring-up start (= PRECHARGE_TIMEOUT_MS 300),
  persisted 37.6 s; dark bus confirmed (V_bus ≤ 0.350 V).
- **OC quartet:** latch 0.8-1.7 ms after the first injected 1.4 A crossing in all four;
  peaks 2.1114/1.5231/1.8777/3.6022 A match the documented 2.11/1.52/1.88/3.60. WP0097's
  41 ms window latched and held 39 ms to log end — genuine but the thinnest evidence in
  the half.
- **TP0178/TP0201 negative UV:** minima 12.1489/12.1853 V, never below 12.0, UV never set.
- **Carried-in signature systematic 26/26:** carried_in == predecessor_final | 0x0010
  without exception (incl. 0xA010 after ML0217 and 0x8110 after TP0010); all cleared at
  t≈0.500. ML0151 knife-edge confirmed at 1.3538 A = 96.7% and legitimately clean;
  preamble exclusion confirmed on the rate-check spans; bring-up gate passed at
  0.591-0.593 s on all 25 gated entries (6× margin — the gate is not carrying the half).

**Findings (none change a verdict):** F1 MED — `_whole_run_first_note()` prints "latched
BEFORE the grace bound and PERSISTED" falsely on ML0203/ML0169/TP0053 (the pre-grace bit
is the carried-in latch, cleared at 0.5; true only for ML0217 — indistinguishable to a
reader); fix: emit only when the bit is set on the LAST pre-grace sample. F2 LOW-MED —
check_fault_latched reports the first TRANSIENT indication as the latch time (TP0010 off
by 321 ms / TP0053 by 536 ms vs the real latch); report the first sample with
bit+FAULT_ERROR. F3 LOW — the latch test itself should AND in FAULT_ERROR. F4 LOW — the
preamble≥grace assert is void for skip_preamble entries (ML0217's first 2.0 s of recorded
stimulus sit in the excluded window; passes only because INIT_FAIL persists) — same gap
the round-2 reviewer found; per-entry guard. F5 LOW — transient-UV publishing makes
no_fault and fault_not_latched contradictory on a deepened negative-UV stimulus. F6
coverage caveat — current ≡ 0 on all 26 runs: bounded_current(24) +
no_rail_limit_cycle(4) + returns_off_rail(3) + near_zero_current(1) = 32/79 checks
vacuous; ML0137/ML0140/ML0144/YP0166 carry no evidence about their own classification —
tag vacuous checks in rendering and report a substantive-check count.

---

## FINAL SUMMARY — campaign 20260830_203006 (fix-round validation)

**Suite: 38 runs — 36 PASS / 1 FAIL / 1 SKIP. Every verdict is CORRECT.** The fix round
(commit 7802466) did what it was built for: zero false FAILs (was 23), zero rubber-stamp
PASSes (was 3), the one FAIL is a real latch correctly scored, and the drive SKIP is the
designed operator gate. The firmware was correct in all 37 executed runs; zero power
cycles across the whole campaign.

**Scenario objectives reached for the first time (hardware firsts):**
1. **Regen power path end-to-end ×3 windows** (charge-regen): REGEN/FC_CHARGE mutual
   exclusion absolute, Ag105 power-cycling between windows with 0.499 s settles,
   I_charge 1.54 A via REGEN+MOT_PWR, 39% OC margin. (Path/sequencing validation only —
   the plant floors regen power; SOC net fell.)
2. **Ag105 GENSTAT input-collapse response** (charge-fault): loss direction of the
   readiness gate observed; MPPT_DISABLE re-asserted +13.5 ms; ceiling knob held 0.8000 A
   exactly.
3. **Share-cut setpoint latch** (handoff-sag): cut 12 ms after the rail command, load
   guard admitted at 24% margin, one-tick current transfer, single-source stability, and
   a 1.5 A step at 24% BT margin — zero faults.
4. **RT1987 SOFT-state SCP cut** (scp-inrush): 6.29 A cut, correct fold arithmetic, OC_FC
   won the race near-deterministically (the probabilistic prediction was wrong in
   premise); structural finding: the fold is unreachable without an OC fault at any share
   split — the ~1 ms sim-before-firmware window is the whole test.
5. **charge-cruise ruling-(b) validation:** OC_FC at 1.4024 A on the FC-charge ramp with
   cruise established — the designed infeasibility signature.
6. **Replay half alive:** UV-latch regression coverage restored (clamp+preamble),
   INIT_FAIL cold-boot entry working, OC quartet latching at the recorded instants.

**Repeatability (vs campaign 181426):** staged bring-up to ~1 ms/~1 mA (three
corroborations of the SOFT-state physics fix at 0.222-0.223 A); UV dwell 19.992 vs
19.887 ms; ems-drive-cycle a sub-1% repeat (tracking median 0.53 mm/s); sag teardown
byte-identical.

**The one FAIL (comm-loss) is the campaign's most valuable finding:** a REAL OC_FC
latched 3.0 ms after an otherwise perfect mid-run recovery (recovery Δ 1.1 ms) — root
cause a hifi SOFT-start defect on PRE-CHARGED nodes (t_on recomputed from sagging v_in
while v_ss_start is latched; 3.9× non-physical current; successor to the 2026-08-30b
cold-start fix). Scored FAIL and kept FAIL deliberately — widening allow_only would
launder the artifact.

**Cross-cutting discovery:** the hifi engine implements the DESIGN droop (0.316/0.633 Ω
fitted, ratio exactly 2.000) — 4× the bench-measured K_DROOP_BUS. This closes
charge-regen's droop "anomaly" (0.49 V = 1.54 A × 0.316) and means hifi sag depths are
conservative and NOT comparable to bench logs until reconciled or bannered.

**Fix queue for the post-suite round (adjudicated):** (1) hil_electrical SOFT-start
pre-charged-node fix + pinned regression [MED-HIGH]; (2) replay F1-F6 reporting/robustness
fixes; (3) reviewer #1/#2 deferred items (stale handoff-sag comment — independently
corroborated; skip_preamble guard = F4); (4) scp-inrush events_require tightening +
probability-comment correction; (5) handoff-sag rail-timing documentation; (6) worst-ring
unconditional recording; (7) comm-loss grace-note rendering nit; (8) TARGET_FW_VERSION
21→23; (9) hifi-droop bannering + charge-regen regen-floored docstring note. Operator
items (not prescribed): UV-objective home (v_bus_sense_offset scenario?), Ag105
lazy-re-config verification on real hardware, chopper-coverage stimulus, soc-depletion
run when a session has 15 spare minutes.
