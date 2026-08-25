
---

## Status & session addendum (2026-08-25b, fw v19: 'L' encoder fields + conduction-aware handoff slew)

Follow-on to the logs 194-203 analysis round (same day). That round validated fw v18 on
hardware (anti-windup holds the rail across ~160 saturation episodes, zero chatter; Schmitt +
90-slot wheel cut spurious drops >1000x to 0.15-0.40/s cruise; encoder scale 0.998-0.999
everywhere) and root-caused the TP0201 bus sag: the share loop armed OPEN->CLOSED while FC was
the only meaningfully conducting source, the ~20 ms arming gain walk (DROOP_RATIO_SLEW_PER_TICK
0.02/tick) crossed the FC->BT conduction handoff, and the bus went unsourced ~5.7 ms
(15.86 -> 12.185 V, 0.185 V above LIMIT_V_BUS_MIN, no fault; V_fc ROSE 0.66 V at dropout -
the TP0178 supply-transient hypothesis is REFUTED for TP0201). Also found: a localized
once-per-revolution defect on the new 90-slot disc (encoder counts ~42-74 mod 180; ~0.5x
v_act dips 2-3 slots long each rev, driving 6-12 A transients - the entire residual "cruise
chatter" and most of the sat count; physical inspection is the fix), and the -0.9%-of-setpoint
systematic SS error is plausibly the dips biasing the estimator mean. Orchestrated round
(Opus implementer, Sonnet test-writer, Opus safety + Sonnet correctness reviews) shipped
**fw v19 (pending flash; carries v19 alone)**. Ledger row 19 has full detail.

- **'L' stream 8 -> 11 fields** (operator request): appends `enc_pos` (raw encoderPos, int32),
  `edgeA`/`edgeB` (encEdgeCountA/B) so the operator can hand-rotate the wheel and watch the
  decode live. Backpressure guard 110 -> 192 B (safety S4: 165 was an EXACT fit; one
  8-character float would have blocked the print and stalled the loop incl. detectFaults()).
  Serial-only - BLG stays v6, UDP stays v4/58 B.
- **Conduction-aware handoff slew (TP0201 mitigation).** While either channel's FILTERED
  |I| (per-channel EMA at SHARE_GOV_FILT_ALPHA, hysteresis: DARK < SHARE_HANDOFF_MIN_A 0.15 A,
  LIVE >= SHARE_HANDOFF_LIVE_A 0.20 A) is dark, the droop-ratio slew ceiling at all three
  in-band sites (feedforward, reference, actuation) drops 10x to
  DROOP_RATIO_SLEW_HANDOFF_PER_TICK 0.002/tick - the analog handoff gets ~200 ms instead of
  ~20 ms to complete, keeping the commanded operating points close through the crossing.
  One updateShareSlewMode() call per powerBalance() tick stores shareSlewStepThisTick
  (structural reference/actuation agreement, fw v6 doctrine preserved). Converged holds are
  bit-identical to fw v18. An arming PRECONDITION was rejected (the standby channel cannot
  conduct until the ratio crosses - deadlock); a slow PREFIX was rejected (TP0201's crossing
  sat at the END of its walk).
- **Dwell cap, MOTION-GATED (safety S1 HIGH + orchestrator O1 HIGH).** The safety review
  proved the implementer's S4-disjointness claim wrong (the dropped-out half of a
  TP0010/TP0013 dropout cycle IS a dark channel; the fw v6 S4 ~35-tick floor-clip bound was
  load-bearing in exactly this regime), so each dark event gets ONE allowance of
  SHARE_HANDOFF_DWELL_MAX_TICKS = 175 slow ticks, then FULL rate until a LIVE transition
  re-arms it. The orchestrator's final-review trace then caught O1: TP0201's ~1500-tick
  static pre-arm hold would have burned that allowance BEFORE the hazardous arming walk -
  so the dwell counts only slow ticks on which droopSlew_prev actually MOVED (one-tick-lag
  motion detector via shareHandoffPrevRatio; a static hold costs nothing; the S4 exposure
  bound is unchanged because S4's hazard is the walk itself). S4's bound is thus RELAXED
  (175 moving ticks + fast remainder, once per dark event), not preserved - stated honestly
  at the site; the S3 residual (the slow limiter is invisible to the share controller's
  [0,1]-only anti-windup) is bounded by the same cap and documented.
- **Observability:** 'S' dump gains a `share slew mode:` line (FULL/HANDOFF/CAPPED + filtered
  magnitudes + dwell). The mode is NOT reconstructible from logged raw currents (filter +
  hysteresis + motion-gated dwell state) - log-conventions.md says so. Governor/slew constant
  family is now tabulated in PLAN.md 9e. Setpoint-latch release with a dark re-closed channel
  now takes up to ~200 ms extra to reach the commanded split (S5, operator note - not a stuck
  loop).
- **Tests: 3372 production + 175 bench pass** (rebuilt from source, orchestrator-verified).
  New: TP0201 static-hold regression (dwell untouched by a 300-tick dark hold, walk then runs
  at 0.002/tick), motion-burn exactness with interleaved holds, dark-seed warm-up (5 ticks at
  1.0 A), hysteresis band, re-arm on LIVE only, reset seeding (no spurious first-tick motion),
  live-stretch reference freshness, 11-field plot format incl. negative enc_pos, 191/192
  backpressure boundary. reset_test_state() gained the shareHandoff* block (latent
  cross-test-pollution gap closed).
- **Bench gates for fw v19 (argued, not measured - both REQUIRED before trusting the bounds):**
  repeat the TP0201 condition (sp 0.85, 6 A trapezoid, 5-10 runs - occurrence rate + sag
  depth vs the 12.185 V baseline), and re-validate the share sweep at light load (the
  TP0170-180 dataset predates the slew change; minority channels sat under 0.15 A there).
  Then the standing order: inspect the 90-slot disc sector (counts ~42-74 mod 180), VESC
  regen-ceiling characterization, 'Y'/'W' with a real bus load >= 1.5 A. Note TP0199/0202
  used sp 0.12/0.87 - OUTSIDE [DROOP_R_MIN 0.15, DROOP_R_MAX 0.85] - so they exercised the
  setpoint latch, not the governor rails; use in-band setpoints to test the governor.
