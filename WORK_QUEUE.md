# Work queue — updated post round 2026-09-02 (Ag105 η = 0.88, η-era DP/SDP, MPC live, campaigns B and C analysed, physics review closed, session closed out)

## 0h. Campaign II (2026-09-09, the first H-20 campaign) - operator rulings and the fix queue

Source: `HIL Results/hil_report_20260909_095715/HIL_FINDINGS.md` (FINAL SUMMARY) and OVERNIGHT_LOG.md session 2026-09-09
(the headlines at 28 / 31 / 36 / 42 of 75). Zero board defects; every FAIL classified. Items 1-8 need a ruling; 9-18 are
tooling / suite items for the fix round (the 0f queue stays held behind the H2-model rulings where it overlaps).

### Rulings
1. **The plans inverted polarity under the convex map** - the MPC on all three cycles AND the regenerated DP tables (ems-ftp75-dp
   floor 0.5375 / modal 0.85 / zero charge stages; ems-mpc-cross walks 0.15 -> 0.85 with no arm standing). The DP moving with the
   MPC makes this the map's economics. Decide the offline A/B (terminal price 2.140 g/SoC re-based at 14.644 W vs the convex
   stage cost with A0) and whether the ladder endpoints stay on the selector rails (0f-10).
2. **The FC minority chatter, second campaign** (ems-ftp75-sdp: 78 FC_BUS falls identical to campaign I). Firmware: clamp the share
   PI reference at DROOP_R_MIN with anti-windup for in-band commands (0f-9). The DP control case has no stimulus under H-20.
3. **Lambda re-pin** `EMS_EQ_H2_LAMBDA_SOC_PER_G` 0.4673 (walked) -> 0.4799 (board cal-charge lever, in band).
4. **A per-leg H2 basis reference**: the 14.644 W point holds only on the cruise charge legs; the 61 s MPC legs run 8-10 W, FTP-75
   2-5 W, the compressed cycle 1-2 W. The MPC terminal price and ALPHA_MISMATCH_REF are re-based at the cruise point.
5. **The socband reference charges** 449.6 mC (campaign I 447.0) on ftp75c - "charge-free by design" (0c-4) is stale; re-adjudicate.
6. **The v7 alpha basis** (0g-1) with the levers now board-measured (ratio 0.680, not eta).
7. **The ftp75c frontier's bound arm** reads 0.9693: the in-band DP never leaves the battery-only arm while the SDP rides FC-only;
   the DP solve has no selector. Rule whether the matched DP is re-solved under the selector (the 0f matched-DP item) or the
   bound arm is declared structurally uninformative on cycles whose total never clears the gate.
8. **Bench**: the share-staircase FC cut latency reads 2.5 / 8.4 / 11.2 ms across H / I / II (host jitter) - a bench log pins the
   board's own figure; the AD5443/OPA197 DMM measurement still open.

### Fix queue
9. [TOOLS] `Planner.delivery_table()` HOLD state SOURCE-aware (FC-only holds are the whole residual on ems-ftp75-mpc / ftp75c-mpc /
   ems-mpc; the queued BT-only preview does not cover them); the 171.4 s post-window residual (347 ms, 17 ms outside
   `exclude_hold_ms`) on ftp75c-mpc.
10. [SUITE] ems-dp-replay: `signal_dp_fc_current_railed` floor 0.95 A -> ~0.85 A from the H-20 table's 0.625 rail x the window
    total; `signal_dp_early_fc_rail` window [12, 20] -> [5, 11] s floor 0.80; the citation's retired trajectory and "charge_goal
    is 0 for the ENTIRE run" (a 2.5 s window opens at 51.53 s); the one-sided h2 floor.
11. [SUITE] ems-ftp75-dp / ftp75c family citations converted from the retired trajectories (fc_carried 0.7677 / table max 0.8375;
    the ftp75c walk figures are Gfc-era: 5050 cites 0.0020697 g); state the A0 share in every provisional note (66-88 % on the
    low-demand legs); register `charge_edges_safe` on ems-ftp75c-socband; REPORT.md's "ftp75-dp bound PENDING a table
    regeneration" note is stale.
12. [TOOLS] the matched DP re-solved under the selector before any ftp75c vs_bound reading (see ruling 7); the fresh matched-DP
    records for campaign II from the tool pass.
13. [SUITE] plumbing-only hydrogen floors (ems-soc-band 1e-3 g etc.) score nothing - re-derive as bands or drop; `h2_saturated_peak_w`
    prints bus watts under a stack label; a stack-referred saturation margin metric (ems-sdp 93.0 % of P_MAX; clamp-sweep crossed
    the knee at 24.08 W, 63 ticks, on an unscored leg).
14. [SUITE, text] the ems-sdp policy citation names v3 (played v6); `signal_alpha_share_degenerate` quotes alpha 0.073936 (played idx 2,
    0.065498); `mpc_share_prediction`'s label misdescribes the prefix mask.
15. [SUITE] `bt_bus_restored`: record the trigger class (live gate release vs region-edge fallback) and score the two b00 shapes
    separately (b00-v3's restore took 7.99 ms through the turn-on path vs 1.0 ms).
16. [SUITE] window-pinned checks on the sdp-v6 legs: SoC-threshold events carry 1-3 s of cross-campaign phase (the sdp-cross flip
    42.3 / 37.3 / 35.3 / 36.3 s; its windows 2-3 s earlier; braking's 20.6 s re-arm absent) while dwells and periods repeat.
17. [LEDGER] retire campaign I's ems-mpc-cross "frontier entry VOID" line (the leg is in no tuple) and the b30-v3 fc_ceil "trend";
    campaign I's exact-0.0 commit census baseline is retired (the single leg now commits 1.0).
18. [DOC] the F1 window-open delay is TWO commander periods from the standstill trigger (charge-to-full, 39.6 ms) and ZERO from an
    FC-selected arm (REGEN drop and FC_CHARGE open on the same tick) - the design record says one.

## 0e. fw v28 round (operator rulings 2026-09-08) — the source selector, the sliver hold, I_min 0.125 A, the charge-window k_d hold, and the F1 sequencing fix

Rulings (2026-09-08, after the campaign G/G2/H digest): (1) F1 fixed the preferred way; (2) the never-closed
region selects battery-only OR fuel-cell-only from the commanded share with INCLUSIVE 0.85 / 0.15 thresholds;
(3) the forced-0.5 sliver becomes a HOLD, and `SHARE_MINORITY_I_MIN_A` 0.15 -> **0.125 A** (D = 0.25 V);
(4) F4 fixed as proposed; F5 handoff constants **0.10 A dark / 0.12 A live**. F6 is a tools item; F7 is
RECORDED, not built. Every item below is a behaviour change at profile start, so the package ships as
**fw v28** (`FW_VERSION` 28; BLG stays v8; the 18 B / 40 B HIL frames and the v4 / 58 B telemetry are
untouched). Process: `orchestrated-feature` (direct); the encoder harness (§7d) runs in PARALLEL on disjoint
files (it must not edit `test/test_main.cpp` — its `run_tests` hook is added by the orchestrator after the
firmware round lands).

**Firmware brief (one Opus implementer, `teensy_controller.ino` + `test/test_main.cpp` via the test-writer):**
- [x] 1. (DONE `9318e16`, either-cut disarm per review S5; the '5' key refusal S6) **F1 — clear the arm before the charge path opens, and open only onto a conducting fuel cell.**
      Site: `chargingControl()` cruise branch, the `assertFcChargeEnable(true)` call (~line 12005). If the
      never-closed selector currently holds FC off the bus (`shareSpCutFC` owned by the selector), disarm
      the selector this commander period and do NOT call `assertFcChargeEnable(true)`; the latch's own
      release branch (`updateShareSetpointCutoff()`, `V_BUS_CHARGED_THRESH`-gated) re-closes FC_BUS on the
      battery-fed bus at the next 1 kHz tick. Open FC_CHARGE only when `FC_BUS_ENABLE` reads HIGH and
      `busSwitchBlanked(FC_BUS_ENABLE)` is false (conduction-gated, not period-counted, so the cadence is
      irrelevant and the charge-window HANDOFF trigger seen on campaign H is covered by the same test). The
      S2 restore inside `assertFcChargeEnable()` stays (unreachable from the selector afterwards). Test: window
      entry from a battery-only state asserts FC_BUS HIGH for >= the RT1987 turn-on before BT_BUS goes LOW,
      and that no tick has both bus switches LOW with MOT_PWR HIGH.
- [x] 2. (DONE `9318e16`; + review S2 raw-current escape while FC is selected) **F2 — the never-closed SOURCE SELECTOR (replaces "battery-only arm" + "disarm permanently on an
      out-of-band command").** State: the arm plus a selected source in {BT, FC}, default BT at every
      `armShareBatteryOnlyStart()` site (rename to `armShareStartSelector()` or keep the name and document).
      Per-tick rule while armed: commanded `power_share_setpoint >= DROOP_R_MAX` (0.85, INCLUSIVE — the Pi
      clamps to 0.85 and the latch's own test is strict) selects FC; `<= DROOP_R_MIN` (0.15, inclusive)
      selects BT; in between, HOLD the selection. The effective setpoint fed to `updateShareSetpointCutoff()`
      is 0.0 (BT) or 1.0 (FC) — always out of band, so the latch always owns it (one owner per setpoint is
      preserved by construction). A selection CHANGE is make-before-break through the existing machinery and
      nothing else: the latch releases the cut channel (guarded re-close on a live bus — the F7 inherited-code
      overshoot, benign), `releasedThisTick` returns the loop for one tick, the entry then cuts the other
      channel under the last-source guard, the survivor-turn-on blanking (`busSwitchBlanked`) and the fw v25
      load guard (`SHARE_CUT_MAX_HANDOFF_A` 0.5 A — always admits under the 2·I_min gate). Two switches never
      move in the same tick. The gate release (the frozen-path filter advance at ~line 11015 and the
      closed-loop disarm at ~11270) must work from EITHER selection; the FC-charge-window SUPPRESSION of the
      arm is replaced by item 1's disarm-before-open. The hold vs return-to-battery question on RE-ENTERING the
      open-loop region after the loop has closed is unchanged (closed-before hold stays; recorded to-do).
      Tests: BT->FC and FC->BT transitions tick by tick (never both LOW); inclusive thresholds (0.85 exactly
      selects FC, 0.8499 holds); hold between; gate release from FC-only re-closes BT then closes the loop;
      the load guard admits at every total under the gate; a selection change during a deferred cut.
- [x] 3. (DONE `9318e16`; the hold is BOUNDED to [loD, 1-loD], loD = min(0.5, SHARE_HANDOFF_MIN_A/I_tot) per review S3) **F3 — the hysteresis sliver HOLDS instead of pinning 0.5.** Site: the closed-loop clip at ~line
      11325 (`if (lo > 0.5f) lo = 0.5f;`). When `lo > hi` (total inside [2·I_min − SHARE_GOV_OL_HYST_A,
      2·I_min)), hold the reference at the current effective (slewed) setpoint — no motion, the same doctrine
      as `shareFeedforwardClipTarget()`'s empty-band hold. The k_d schedule's own 0.5 cap in
      `shareDroopScaleTarget()` is UNCHANGED (it bounds g, not the reference). Test: a total parked in the
      sliver for 1000 ticks after converging at share 0.80 keeps r within one slew step of 0.80 (was walked to
      0.5000); a genuine coast-down through the sliver still exits to open loop at the exit threshold.
- [x] 4. (DONE `9318e16`; + review S7: HANDOFF slew ceiling whenever the filtered total is under the gate) **`SHARE_MINORITY_I_MIN_A` 0.15 -> 0.125 A** (`constexpr`, ~line 2392; operator: D = 0.25 V).
      Derived and MOVING: gate 0.30 -> 0.25 A, exit 0.25 -> 0.20 A, crossover 0.906 -> 0.755 A (the `'S'`
      line and every prose site derive from the symbols — grep for 0.906, 0.30 A gate, 0.25 A exit, 1.4706,
      0.272 V and re-derive each), authority `RE_MAX·0.125·0.9` = 0.227 V (0.252 V at unity), fw v26
      reachability: floor term 1.375 A, `DROOP_R_MAX` term 1.471 A still governs (the `static_assert`s at
      ~2680–2700 re-derive; NO ceiling is loosened). **F5 with it:** `SHARE_HANDOFF_MIN_A` 0.15 -> **0.10 A**,
      `SHARE_HANDOFF_LIVE_A` 0.20 -> **0.12 A**, so a minority AT the floor reads live (the 0.15 == floor
      equality that produced 58 cuts / 90 s is gone); re-state the fw v19 rationale at the constants and the
      `static_assert` that the floor sits above the dark threshold. Sub-gate fixtures were HALVED for rev 2;
      re-point them proportionally (0.15/0.125) with the justification at the site, as rev 2 did.
- [x] 5. (DONE `9318e16`; K_DROOP target only with FC_CHARGE HIGH, k_d FROZEN under any cut per review S4) **F4 — hold k_d at `K_DROOP` in single-source windows.** `shareDroopScaleTarget()` /
      `updateShareDroopScale()` (~10840–10875): the target is `K_DROOP` whenever `FC_CHARGE_ENABLE` reads HIGH
      or any of `shareIsoFC/BT`, `shareSpCutFC/BT` is set; slewed under the existing
      `SHARE_KD_SLEW_FRAC_PER_TICK` so the codes never step; on window close the schedule resumes from
      `K_DROOP` at the normal rate. Test: open a charge window at 0.16 A single-source and assert the FC code
      never reaches 4095 and `shareGGuardCount` stays 0 (was 9057 ticks on mppt-tracking); the schedule
      resumes after the window.
- [x] 6. (recorded in the design record) **F7 RECORDED, not built:** the re-entry closes a channel on inherited MDAC codes (0.2355 A / 12 ms on
      ems-ftp75-sdp). With the selector, re-entries happen at every selection change; re-seeding the codes at
      the clipped band edge on release is a separate ruling (a second writer outside the rate limiter was
      REJECTED in rev 2).
- [x] 7. (DONE `9318e16`: 4207 / 175 / 4694, 0 warnings; CLAUDE.md addendum 2026-09-08; PENDING FLASH - operator flashes) Changelog block at the top of the `.ino`, `FW_VERSION` 28, `docs/firmware-versions.md` row 28
      (PENDING FLASH), design record `docs/fw28_source_selector.md` (mechanism, the make-before-break
      argument, the derived-constant table at 0.125 A, validation), CLAUDE.md addendum 2026-09-08, then the
      Opus safety review + Sonnet correctness review, fix round, `self-review`, three builds (baseline
      4114 / 175 / 4596), commit with the flag flip, push. Operator flashes.

**Tools mirror round (after the firmware lands; one boundary = fw v28):**
- [x] 8. (DONE `1549067` part 1 + `e7ab118` part 2) `governor_model.py` (selector, sliver hold, k_d charge-window hold, the three constants),
      `test/gov_fw27_harness.cpp` -> fw v28 harness + `test_governor_fw27_equivalence.py` (new cases: both
      transitions, the sliver, the window hold; max code delta 0), `ems_walk.py` + the MPC delivery table /
      shadow governor / `batt_only_cut_mask()` (selector-aware: the policies' commanded share now picks the
      source under the gate), `hil_plant_sim.py` FW28-ERA block, `run_hil_suite.py` `_BATT_ONLY_GATE_A`
      and every early-window switch-word pin (FC-only starts are now reachable), `TARGET_FW_VERSION` 28.
- [x] 9. (DONE `e7ab118`: re-walk table in run_hil_suite.py :1049-1177; mppt-tracking sag/plateau needs the campaign) Re-derive every stimulus expressed as a designed total at I_min 0.125 (the retrospective rule):
      `fw26-clamp-joint` step (1.57 A: bound min(0.85·1.57, 1.57−0.125) = 1.3345 A, `DROOP_R_MAX` term
      governs — confirm and re-walk), the sweep/cruise legs, the sdpx/sdpb/sdpftp pins, the ftp75c legs (now
      FC-selectable under the gate — check what v6 / the DP tables command below 0.25 A), the ems-sdp bin-21
      plateau (ruling still open). Re-walk every anchor; provisional pins for the first fw v28 campaign.
- [x] 10. (DONE `e7ab118`: reported, not applied; joint 1.3561 A with F6 vs board 1.3243 A) **F6:** the walk models the share-loop feedback-EMA overshoot on the fw v26 clamp (+3 % of r for
      ~12 ms; the joint leg's bound needs a third reading on the board).
- [x] 11. (DONE: campaign I `hil_report_20260908_200836`, 66/75, zero board defects, F1 closed on all three triggers, ftp75c frontier verified; tooling `60abb34`; the operator stopped after one campaign for the H2-model update) launch from a detached worktree with `--with-ftp75 --with-ftp75c --with-alpha`) Suites, commit, push; first fw v28 campaign after the operator's flash (full plan incl. the opt-in
      legs; the F1 legs `charge-to-full`, the five `ems-ftp75c-*`, `ems-sdp-cross` are the witnesses).

- [x] 12. (DONE `ded47f3`: growth requirement 0.10 m/s over the window and manual-current exclusion added by review; same-tick sign correction; 4318 / 175 / 4699, harness 51; a wrong flip is silent and permanent for the boot - recorded) **fw v28 rev 2 (operator ruling 2026-09-08 afternoon, from the harness finding): encoder direction-sense
      AUTO-FLIP on positive-feedback runaway, NO fault.** Signature: sign(current) == -sign(v_actual), |v_actual| >=
      0.30 m/s, |current| >= 0.5*MOTOR_I_CMD_MAX, |v_actual| not decreasing, sustained 500 ticks; on detection flip a
      runtime sign factor at the velocity publish seam (not the ISRs / updateWheelSpeed math), print an ASCII line,
      5 s lockout, <= 4 flips per boot (anti-chatter: a significant threshold, per the operator). Not applied to the
      HIL-injected v_actual. Rationale: the encoder connector can be plugged in reversed; the harness measured the
      inverted case railing the drive with no fault. Test-writer: host-native + the harness 180 deg case now asserts
      the flip and recovery. IN PROGRESS (Opus implementer, brief scratchpad/brief_fw28r2_encdir.md).

- [ ] 13. **fw v28 rev 3 (operator ruling 2026-09-08 evening): the encoder direction sign PERSISTS across power
      cycles** (Teensy 4.1 EEPROM emulation; magic + sign + generation + checksum; EEPROM.update() only at a flip,
      <= 4 writes per boot; read at setup(); a State-98 key clears it; a stale stored sign is corrected and
      re-stored by the growth-gated detector). DONE `7482395` (4367 / 175 / 4704, harness 51; State-98 Z key; residual: the flash write duration at the flip tick is TODO(verify: PJRC)).

- [ ] 14. **RT1987 constant-slew ramp A/B (operator ruling 2026-09-08 evening: run it now, before the campaign).**
      Selectable `--rt1987-ramp {legacy,constant-slew}` (datasheet 10-90 % tON -> 645.5 V/s at 100 nF, VIN- and
      start-independent; the model's start-scaled ramp is +25 % cold / -9.8 % warm); A/B every switch-turn-on
      anchor (bring-up P0/P3, scp-inrush, handoff-sag, comm-loss warm re-close = the target, F7 re-entry
      overshoot, the F1 window entry, ftp75c handoffs, replay first turn-ons, fw26-clamp legs); default decided
      by whether the cold pins move toward the board; legacy stays as the one-campaign reversal path.
      DONE `66dea4b`: LEGACY STAYS THE DEFAULT - constant-slew moves the cold pins away from the board (P0 -8 %, P3
      -18 %); neither shape brackets comm-loss (3.75 / 0.139 A vs board 1.66-1.79 A latching) - the residual is
      elsewhere (boost output impedance, RT_R_ON, C_VBUS: each a measurement round); the F7 re-entry row (ON in
      9 vs 22 ms) is the one to re-open on. No pin moved; both shapes selectable and era-fingerprinted.

- [ ] 14b. (DONE `5d281d8` fw v28 rev 4: EEPROM commit deferred off the flip tick; k_d single-source hold keyed on bus topology; 4408 / 175 / 4715 / 51. Tools follow-up: governor_model.py must carry the topology re-key.)
- [x] 15. (DONE `a09d1ca` rev 5 + `f0d82e4` rev 6 after the safety review: inhibit freshness S1, 250 ms selection-change dwell S2, re-arm reachable when the rail command precedes the fall S3, Idle clears S5, BLG bit4 = inhibit S6; 4503 / 175 / 4810 / 51) **fw v28 rev 5 - re-entry rule (operator ruling 2026-09-08 evening):** after the loop has closed and the
      total falls back under the gate the HOLD stays; a commanded share <= 0.15 or >= 0.85 RE-ARMS the selector with
      that source (holds through in-band commands, releases at the gate, same machinery as the never-closed
      selector); in-band commands never trigger single-source on re-entry. After rev 4.
- [x] 16. (DONE: firmware `a09d1ca`/`f0d82e4`, decoder `c11a464`) **BLG v9 (operator ruling: implement):** record appends selector armed/FC bits, encoder dirSign (i8),
      flip count (u8), EEPROM-commit-pending flag; firmware side with rev 5, decoder + benchlog_analysis +
      make_test_blg in the tools round; v1-v8 byte-identical.
- [x] 17. (DONE `c11a464`; better conditioned at the floor than at full load; idle split 0.25 -> 0.3650) **`ASYM_SIMPLE_I_MIN_A` 0.10 -> 0.08 A (operator: my pick)** so the simple engine's split law applies at the
      0.09 A idle; conditioning check at that total. Tools round after the A/B.
- [x] 18. (DONE `c11a464`: k_d + dV0 + R_f wins, CAL-1 RMS 0.0090 vs 0.0457 for k_d-only; the 39 slope fits prefer a NEGATIVE intercept - the +0.033 ohm floor is not bench-supported at 0.2117, recorded for the DMM measurement) **`--droop measured` scaling (operator: use the scalings that best match the bench record):** fit k_d-only /
      k_d+dV0 / k_d+dV0+R_f / realised-k_d against the 39 single-source fits and CAL-1; ship the lowest residual.
- [x] 19. (RULED 2026-09-08: ACCEPT the leg as a CLAMP WITNESS - stimulus unchanged, the sdp_table checks stay tagged as clamp-side; premise failed: plateau is bin 22 and no demand bin discriminates; v6 flips on the SoC target row and every above-target ask clamps to 0.85; needs a start below the SoC target or a drain crossing it - RULING) **ems-sdp stimulus re-tuned (operator ruling):** drain plateau one demand bin below the clamp where the
      v6 and DP tables differ; re-walk, re-pin provisional.
- [x] 20. (DONE `70e4543` + rebind `0063f8e`: charge boundary 0.1385, alpha 0.13411 3.2 % below it; legs rebound greedy 3 / cal 8 = v6 / charge 15 under the SUITE walk configuration - the sweep walks without the asymmetry triple) **Alpha sweep re-run at the measured billing (operator: yes)** after the ramp decision; the 75 matched-DP
      re-solves HELD until the overnight campaign (operator).

- [x] 21. (DONE `07add95`: the selector HOLD makes in-band det/sto commands the same instruction; 23 ticks differ in phase; claim restated as rail-set identity + billing identity + a trace-derived 1.74e-3 envelope; mpc-det pin 0.007982535732) **`test_the_cross_stimulus_wide_share_walk_is_not_available_from_either_law`** failed - mpc-det vs
      mpc-sto h2 differ by 3e-5 (deterministic, not the wall-clock class; most plausibly the rev 4-6 governor mirror)
      and its mpc-det pin 0.009018666 is stale (0.0079825 now). Re-adjudicate the claim (bit-identical hydrogen across
      the two laws) rather than bump the numbers. Left failing in the miniforge suite.
- [ ] 22. Review nits carried: en_low margin as a rule not a literal; the raw-escape fidelity note in governor_model's
      boundaries list; `_selector_commands_a_rail()` raise on an unknown tag; FW28-ERA block lacks
      SHARE_SELECTOR_DWELL_MS; the port's refused_blank one-tick lead after ~460 blank refusals; `--droop measured`
      bench intercept (negative) awaits the AD5443/OPA197 DMM measurement.

## 0f. Campaign I fix queue (2026-09-09) - HELD by the operator's ruling until after the H2-consumption-model update

Every item below is adjudicated in `HIL Results/hil_report_20260908_200836/HIL_FINDINGS.md` (FINAL SUMMARY). None
was applied overnight. Bands are never widened; they are re-derived from the mechanism named.

- [ ] 1. (MECHANISM CORRECTED 2026-09-09, agent C 65978bf: the 0.15 reference is INFEASIBLE under the asymmetric law - minimum deliverable 0.1715 at 1.41 A, the board delivers it to 0.08 % - and the walk's one-tick closed-loop surrogate cuts on 100 % of ticks where the real Youla share controller cuts on 0.40 %; FIX = port the real share_controller.h recursion into governor_model's closed loop, agent E in progress, D-5) **TOOLS, HIGH** - `tools/ems_walk.py` delivers share EXACTLY 0 on a 0.15 floor reference whenever the
      asymmetry triple (loss_map / dv0_v / droop_scale_fc) is on (401 of 610 cruise stages on the greedy alpha policy;
      the board delivers 0.1714 = the split law to 0.1 %). Root-cause the delivery/split solve (a failed inverse falling
      back to 0?); add `--r-series 0.033` to the suite anchor invocation; RE-DERIVE every walk-derived band with a
      0.15-class command (the three alpha legs, ems-sdp's early branch, dp-replay's tail, MPC 0.15 rungs) and the
      23-leg re-walk table; reopen `_FW28_FLOOR_VERDICT["ems-sdp-alpha-greedy"]` (wrong mechanism). Board reading
      0.0030376 g / dSoC -0.00503 is the first measurement.
- [ ] 2. **TOOLS, HIGH** - `Planner.delivery_table()` needs a persistent armed-HOLD selector state (source + armed
      flag seeded by `re_arm_ok`, held across in-band stages, released on the modelled gate crossing): 100 % of the
      MPC prediction residual on ems-ftp75-mpc / ems-ftp75c-mpc / ems-mpc and 60.75 s of unbilled battery-only on
      ems-ftp75-mpc. Then `exclude_hold_ms` (~330 ms) on the post-disarm re-close transient. Never widen pred_err_max.
      - (MECHANISM REFUTED 2026-09-09, agent C' `f6c52a6`.) `re_arm_ok` is true at ZERO decisions on five of the six
        registered MPC legs, so a per-column re-arm fix cannot move them; extending the arm to in-band columns was
        implemented and measured (streams bit-identical on five legs; ems-ftp75c-mpc's in-band Gate-1 mean got WORSE,
        2.972e-01 -> 3.107e-01) and NOT shipped. The arm is instead released at STAGE 0 of every mask ever built,
        because the RELEASE PREVIEW's own stage-0 total already exceeds `GOV_ENTRY_A` - ems-ftp75-mpc 188 of 188
        masks, preview 0.2426-0.3157 A (median 0.2840) against a 0.2500 A gate, while the shadow's measured filtered
        total is 0.0908 A (3.1x).
      - (RE-DIAGNOSED 2026-09-09, D-8 lens-2.) This is NOT a plant-fidelity gap and NOT item 15's class. The
        filtered seed carries almost no weight at stage 0: the EMA runs 50 ticks per sub-sample, so the seed decays
        to `(1 - 0.05)^50` = 0.0769 of itself before the crossing is tested, and the shadow's 0.0908 A measured
        total contributes ~7 mA of the crossing. The release is therefore driven by the PREVIEW's own forecast
        total, so the defect is in the single-source demand preview (`pre_bt_release` / `pre_fc_release`), which
        forecasts a two-source-class total for a cut channel - a TOOLING gap that CAN be closed inside
        `delivery_table()` with no plant number substituted for a forecast. Pinned by
        `test_the_armed_hold_is_unreachable_because_the_release_preview_leads_it`.
        `exclude_hold_ms` 330 ms IS shipped (derivation in run_hil_suite.py); `pred_err_max` 0.30 unchanged.
        STAYS OPEN, re-pointed at the single-source demand preview; NOT implemented in the D-8 pass.
- [ ] 3. **TOOLS** - re-walk the 23-leg fw v28 table at the rev 4-6 governor mirror (the shipped rows predate the
      re-entry rule: no re-arm tail, 69 % of dp-replay's residual) AND model the ftp75c family's F1-disarm-driven
      release (the gate never releases the arm there: filtered peak 0.157-0.179 A; rows ~39 % low) and the rev 6
      inhibit (ftp75c-sdp -9.5 %). Fix the entry prose asserting the gate release.
      - (RE-WALK DONE 2026-09-09, agent C' `f6c52a6`; the rest STAYS OPEN.) All 23 legs re-walked on the corrected
        loop (849ff13) at the suite configuration plus `r_series_ohm=0.033`, recorded as a THIRD column in
        run_hil_suite.py beside fw v27 rev 2 and fw v28 e7ab118, with the FC/BT bus-fall census per leg. R_f
        separated and measured on seven legs: hydrogen IDENTICAL to seven decimals at 0 and 0.033 ohm; the cut
        census moves 11-16 % (ems-ftp75-sdp 5945 -> 6873 FC_BUS falls). NO BAND CONSTANT MOVED: `WalkResult.h2_g`
        is now the H-20 map while the suite's bands are keyed to `h2_cum_g` (the Gfc dynamic map), and restating
        one against the other is a silent scale error - the AXIS RECONCILIATION is the prerequisite and is the
        first thing the next round owes. `sdpftp_en_low_census` stays (0, 6) on load-guard cuts: the r-based cut is
        modelled now but at 6873 against the board's 71. Still to do: the ftp75c F1-disarm-driven release and the
        rev 6 inhibit in the walk, and the entry prose asserting the gate release.
- [ ] 4. **SUITE** - ems-y-b00-v1 `signal_bt_bus_restored`: an event-shaped check on the mechanism (BT_BUS HIGH
      within 50 ms of the filtered total first exceeding the gate after the region-7 command edge), not a 2000-tick
      floor; correct the line-1178 risk note (third mechanism: the in-band hold after region 6 drops v_sp).
- [ ] 5. **SUITE** - a per-run `max_tick_overrun_ms` tripwire at HIL_ZERO_MS (250 ms) beside `achieved_rate` (a 314 ms
      blackout passed the 998 Hz mean gate); print max overrun in key_metrics; `mpc_cadence` counts Run-state rows.
      Re-run ems-mpc-cross on an unloaded host (void this campaign).
- [ ] 6. **SUITE** - `_JOINT_ACCEPT_PEAK_A` 1.3241 A is not calibrated (three readings 1.3243 / 1.2699 / 1.2835 A, a
      4.2 % population with no outlier): re-key to the fw v28 structural bound 1.3345 A with the population recorded;
      keep `joint_peak_held_down`.
- [ ] 7. **SUITE** - ems-sdp-cross low/high-rail windows (the flip walked 42.29 -> 37.27 -> 35.30 s, 296 ms inside the
      35.0 s edge); retire or re-point `signal_sdp_table_interior_at_high_demand` at the delivered 0.85 (the clamp
      witness); an edge-scoped charge-window check on ems-soc-band (F1 acts outside [44, 54]); a per-leg bus-switch
      cut census on the report axis (fw v28 raised it 6x on ems-sdp-cross, all at 0 A); a share-cut census metric on
      replays; `mpc_share_prediction`'s label vs its prefix mask.
- [ ] 8. **DOC** - the charge window opens TWO commander periods (39.9 ms) after the F1 re-close (charge-to-full), not
      one (docs/fw28_source_selector.md + the walk); convert the ems-ftp75-dp / mppt-tracking / charge-cruise
      provisional notes to measured citations of hil_report_20260908_200836 (mppt: the F4 plateau-rise null result);
      ems-mpc-single is registered mpc-det; the replay half gives the selector zero coverage (state it, or re-spec
      an entry with a b = 0 W/Y log).
- [ ] 9. **FIRMWARE ruling** - the FC minority chatter at a sustained command AT the inclusive rail (ems-ftp75-sdp:
      71 r-based `applyShareRatio()` cuts / 90 s at I_fc 0.134-0.168 A; the PI winds below DROOP_R_MIN chasing the
      split law's 0.17; fw v6's accepted residual, benign). Candidate: clamp the share PI reference at DROOP_R_MIN
      with anti-windup for in-band commands so only a strictly out-of-band command reaches the r-based cut path.
- [ ] 10. **EMS design ruling** - the MPC ladder's 0.15 / 0.85 endpoints are the selector rails (60.75 s battery-only,
      -9.9 % FC coulombs unbilled on ems-ftp75-mpc): move the endpoints strictly inside the band, or teach the stage
      model the hold and let the planner choose it.
- [ ] 11. **Rulings** - ems-ftp75c-socband is no longer charge-free (17 windows, 447 mC): re-adjudicate the 2026-09-03
      "charge-free by design" before the verified ftp75c frontier is quoted; the FC-only re-arm persisting to Run exit
      (intended?); scp-inrush h2 dropped as an anchor (i_cut stays).
- [x] 12. (D-4, 2026-09-09: the old records stay unreachable by design; campaign II's tool pass solves fresh records under the h2_map key) The 75 matched-DP re-solves.
- [ ] 13. **RULING (phase B, agent A 354da3d)** - under the convex H-20 map the D12 admission window is NECESSARY BUT NOT SUFFICIENT: sdp_policy_v7 (alpha 0.134041, `--alpha-mode lever-h20`) admits 46 charge cells (demand bin 0, 0.5 W, 0.035 % dwell, below the SoC target; no walk opens a window) while the closed-form tripwire says charge rejected; alpha sits 1.59 % above the BISECTED charge boundary 0.131942 (bisected vs predicted: degeneracy 0.087452 vs 0.119978, charge -12 %). Options: accept the 46 cells (dwell-negligible); bisect alpha to zero them (charge-edge in reverse); or restate the admission rule on the map's marginal at the cell's own operating point. v7 ships as the frontier meanwhile (reversal: v6 under --h2-map eta-proxy).
- [ ] 15. **WALK FIDELITY on low-rail legs (agent E 849ff13):** with the real controller ported, the walk still cuts ~75x more often than the board (greedy ~61 Hz vs ~0.8 Hz; ftp75-sdp 6871 vs 71 falls) and the ems-sdp in-band gap moved +30 % -> -14.6 %. Hypothesis to test first: the firmware RESEEDS the share controller on the re-close (CLOSED->OPEN mode) edge, so each re-close restarts the integrator near the delivered ratio (~1 s to wind down again = 0.8 Hz), while the walk's delivered share responds within one tick and its external re-assertion path bypasses the reseed. Second: the survivor blanking / SHARE_CUTOFF_HYST re-entry conditions in the walk's re-close path. Validate on campaign I's greedy CSV (codes pinned 8148/4814 for 26 s, FC off 0.41 %). The ems-sdp gap is a separate plant-fidelity item (in-band 0.85 rail). Until closed, every hydrogen band is PROVISIONAL and campaign II is the calibration source (D-6).
- [ ] 14. **Handoff correction recorded**: the '1010 of 2525 SDP cells refuse the charge action' statement in docs/HANDOFF_H2_MAP_20260909.md and the design note section 9.1 describes the SPLIT arm (bins 20-24, 0.14 % dwell); on the charge arm P_MAX adds zero refusals beyond charge_forbidden_bins (12-24). The rig median stack power is 13.3654 W, not 3.2 W (A0 26 % of the rate, not 63 %); lambda 0.423, not ~0.57. Fold into the design note at the next doc pass.

**Open-item review (2026-09-08, everything else in this file, triaged):**
- Runs THIS session in parallel with the firmware: **§7d encoder-defect harness** (operator brief, disjoint files).
- Tools round after fw v28 (items 8–11 above) absorbs: §7b Gate-1 single-source-aware; `ems-y-b00-*`
  two-source-law gap; `CANDIDATE_COST_MS_NOMINAL` rule (read the next campaign first); ftp75c realizable
  regen fraction doc (0.63); §7b hygiene batch; §0a mpc-cross / mpc-sto cap-lifted re-walk; the per-stage DP
  residual check; F2 (deferral in the single-source surrogate).
- Rulings still OPEN for the operator: the `--droop measured` split-law scaling (§0c 9a); `ASYM_SIMPLE_I_MIN_A`
  at the 0.09 A idle (§0d 6); the ems-sdp stimulus knob (bin-21 plateau); the RT1987 constant-slew ramp A/B;
  the MPC delivery-table residual past the release; hold vs return-to-battery on re-entry (§0d item 2).
- Off-campaign long jobs, unscheduled: the 75 matched-DP re-solves (`provenance_drift`, now a fw v28 era
  too — re-solve ONCE after the mirror); the alpha-sweep re-run at the measured billing.
- Housekeeping: CLAUDE.md is 70.7 KB — rotate the 2026-09-02b (fw v26) addendum into the archive with the
  2026-09-08 addendum (its facts live in `docs/fw26_current_ceiling_governor.md` and firmware-versions row 26);
  the 56 un-audited line citations (§0a); the benchlog exe rebuild; the sub-5 ms replay chatter (§0a).
- Bench (blocked, no access): everything in §3 plus the fw v28 gates — the fw v6 ladder at 0.125/0.875 and
  the two-axis dropout sweep at the scheduled scale (CAL-6), the AD5443/OPA197 DMM measurement, the VESC
  below 5 V, the standstill capture with the VESC powered, the joint bound's third reading (campaign).


## 0g. D-7 blocker and open rulings (2026-09-09, phase-B fix round A-prime)

- [ ] 1. (D-9, 2026-09-09 ~09:35: UNBLOCKED for campaign II by reverting the frontier SDP to `sdp_policy_v6` - A's reversal path; v7 stays in the tree as the record; the ruling below stands for the alpha basis) **OPERATOR RULING - `sdp_policy_v7` does not certify at the corrected alpha.**
      The shipped artifact is solved `--alpha-mode lever-h20 --eta-chg measured` at the corrected 14.6440 W
      operating point (alpha 0.142475472567). Lens-1 F2 independently raised the walked share lever
      0.4223 -> 0.5672, which lowers the walked admission window to [0.0882, 0.1335], so the alpha sits 6.7 %
      above its top, `alpha.admission.in_window_measured` is false and `hil_plant_sim` REFUSES the
      EMS-frontier binding. The refusal is correct and was not worked around. Both options are defective:
      `lever-h20` prices alpha in the right unit and fails the certificate; `lever-measured` certifies
      (alpha 0.134110280093, both windows IN, 46 charge cells) but prices alpha on the five eta-era BOARD
      readings, which are GFC-GRAM levers - the unit error solver D16 exists to remove. Campaign II's three
      `ems-sdp-alpha-*` legs measure H-20-era levers on the board and settle it. Certifying artifact, one
      command: `python tools/sdp_ems_solver.py --alpha-mode lever-measured --eta-chg measured --out
      tools/sdp_policies/sdp_policy_v7.json --force`. Carried as a strict xfail on three
      `test_hil_plant_sim.py` tests.
- [ ] 2. **RULING - the v7 charge census spread.** 46 cells / demand bin 0 -> 140 cells / bins {0, 1, 2} over
      47 SoC rows, all still below the SoC target. The mechanism is the alpha rise (a dearer terminal SoC
      admits charging at more demands). Pinned exactly in `test_sdp_ems_solver.py`. Whether an artifact that
      commands charging on 140 cells is the one to ship is the same question as item 1.
- [ ] 3. **RULING - the MPC 61 s Gate-1 band is missed by 5.6 %** (share_pred_err_mean 0.005281 against 5e-3):
      lambda 0.423 -> 0.4673 lowers `terminal_price("metric")` 9.5 %, the planner spends the pack harder and
      the committed cruise command drops onto the ladder's bottom rung 0.15, where the delivered/predicted
      disagreement is largest. THE GATE WAS NOT WIDENED - strict xfail in `test_mpc_ems.py`. Closing it needs
      either the lambda ruling (item 1's family) or a planner fix, not a band edit.
- [ ] 4. **TOOLS** - the `ems-ftp75c-*` hydrogen bands were NOT restated on the H-20 axis. The corrected-loop
      walk models neither fw v28's F1 disarm-driven gate release nor the rev-6 inhibit, and on the compressed
      cycle that mechanism decides whether the leg runs two-source at all (campaign I: the filtered total
      never reaches the 0.25 A gate, so the release IS the disarm). Model it, then restate those bands and
      the ftp75c frontier; until then both stay provisional with the gap named.
- [ ] 5. **TOOLS** - the second strict xfail stands: the MPC cross-stimulus wide-share envelope
      (`test_the_cross_stimulus_wide_share_walk_is_not_available_from_either_law`). It needs a floor/band
      ruling on the two MPC laws under the H-20 map, not a band re-pin, so it was not touched this round.

## 0. NEXT — operator review (2026-09-03 morning), in this order

The overnight session 2026-09-02/03 ran two full campaigns on fw v26 (D `hil_report_20260902_220604`,
E `hil_report_20260903_031220`) plus campaign F (`hil_report_20260903_063659`, launched 06:37 from `885b436`; analysis pending — see OVERNIGHT_LOG.md §MORNING DIGEST).
Read the MORNING DIGEST first, then the CLAUDE.md addendum 2026-09-03, then the two ledgers. Items
that need a decision or a read:

1. **fw v26 on the board — one number matters.** The clamp is exact at a settled total (cruise leg:
   I_fc 1.2500 ± 0.0002 A, duty 1.0000, 35 ms settling) and is defeated by a commanded share step
   CONCURRENT with a rising total: the sweep latched OC_FC at 38.029 s on a 0.40 → 0.84 step while the
   drive railed 1.84 → 2.99 A (EMA under-read 25.6 % against a 12 % headroom). Necessary condition
   for that hazard: I_tot > LIMIT_I_FC_MAX / DROOP_R_MAX = **1.647 A**; the largest registered EMS
   two-source total is 1.4714 A (10.7 % margin). Design record `docs/fw26_current_ceiling_governor.md`
   §8.6. **Decision:** whether an EMS-side rule ("no upward share step in the same decision as an
   upward demand step above 1.65 A") goes into the MPC stage model now (queued in §7) — the
   firmware closure (α ≥ 0.25 or slew ≤ 0.0027/tick) was NOT proposed, per the design-intent ruling.
2. **The sweep scenario is now bridged and MEASURED (campaign F):** all 12 regions scored, no OC_FC,
   five clamping regions at 1.2500 ± 0.0004 A; the 68 s bridge clears by margin only (§7b F3). The joint-
   transient leg design (1.65 A step, walked peak 1.3303 A) is recorded in §8.6.5 and needs a stepped
   aux-load branch — approve or drop.
3. **MPC single-source (0/1) enumeration shipped** (`4887bd3`): the board executes exact 0/1 through
   the existing packet; admissibility by a rollout of the real governor; the gain is **0.01–0.43 %
   of equivalent hydrogen** (a control-set completeness change, not a performance one).
   `ems-mpc-single` ran in campaign F: 22 battery-only cuts executed cleanly through the guard
   (deferral 24–45 ms), but eq-H2 +0.18 % WORSE than the same MPC without 0/1 (walk −0.04 %): the
   walk does not model the deferral (§7b F2). A wash, not a win, until re-derived.
   Finding to read: the share-cut load guard never refuses permanently above 0.6 A total (the
   deferral walks the doomed channel down — a delay, not a verdict), contrary to the design record's
   resolution 1.
4. **The loss-map DP bound is validated on the board** (dp-replay −0.17 % / +0.06 %; sdp-v4 −0.09 /
   +0.44 %; the four frontier strategies tied within 0.15 % on FTP-75; soc-band 3.3–3.8 % worse).
   The compressed-cycle frontier is certified (sdp-v4 1.0091 / 1.0076 = "no more than 2 % worse";
   mpc-sto 0.9931 / 0.9916). The ftp75c MPC candidate is a constant-0.15 hold for the whole cycle.
5. **The α decision now rests on four readings** (v4's α 1.34–1.49 % below the measured admission
   window; L_chg ≈ 0.333, L_share ≈ 0.416 SoC/g). Unchanged ruling: α stays v4 until you re-solve.
6. **Bleed era is the new baseline.** Every anchor re-pinned from D and reproduced by E (scp-inrush
   bit-exact to 7 digits; floor ~65 ppm within / ~250 ppm across campaigns). The bench calibration of
   `R_NODE_BLEED_*` (30 kΩ / 60 kΩ, `TODO(calibrate)`) moves the comm-loss re-close (0.109 / 0.082 A)
   and the soc-depletion latch (273.59 s) again.
7. **Two tooling data-integrity items you should know about:** `regen_early_releases` was frozen at 0
   in every sidecar ever written (fixed this round); the three α-leg matched-DP records were solved
   against the wrong drain (a hand-typed mirror — the 2026-09-01 B2 defect again; now derived from
   the simulator, records re-solved, a read-time drain-membership witness added).
8. **Operator-only items:** regenerate or delete the orphaned `dp_ems_table_ems-ftp75-5050.csv`
   (41-point [0.25, 0.75] grid, nothing loads it); the ftp75c socband reference's two genuine charge
   windows (0.20 / 0.48 s) are shorter than the Ag105 settle and harvest nothing — widen the exit
   threshold or add a minimum dwell if the reference is meant to harvest; TP0053's UV latch moved
   −58.6 ms on an identical injected stimulus (re-measure before quoting it as an anchor).

## 0d. TONIGHT (2026-09-03 evening) — what is actually being worked, to check tomorrow morning

Operator rulings this afternoon (all recorded in §0c items 9–14 and the memory file): SDP v6 at the measured
0.801 round trip (DONE, `0848c91`); fw v27 built now, operator flashes before campaign G; I_AUX_A dropout floor
at 5 V (DONE); the 4x droop loss investigated (DONE, localized); I_AUX_A -> 0.09 A at the next era boundary;
the fw v27 feedforward redesign REVISED: the proposed "wait until the raw command is inside the band" closing
rule was RETRACTED (band-edge policies would never close the loop below 2.0 A); the loop-closing point stays as
today. Bench is NOT available; the HIL rig IS.

**fw v27 (rev 2) — the governor package, being built now (host-only; supersedes `2d200b1` before flash):**
- [x] 1. (DONE `153562f`) Never-closed profile runs battery-only: FC cut through the existing cut path (load guard, deferral,
      survivor blanking) from profile start until the loop first closes at 0.60 A; re-entry via the existing
      hysteresis/blanking, the closed-loop clip at the band edge, slew from there. Replaces the seed-at-0.5.
- [x] 2. (DONE) Closed-before hold (as committed in `2d200b1`, incl. the cut-outstanding bypass; `share_actedSp` on
      motion only). TO-DO (operator): hold vs return-to-battery on re-entering the open-loop region.
- [x] 3. (DONE) Load-scheduled droop scale, closed loop only: k_d = RE_MAX * max(DROOP_R_MIN, I_min/I_tot_filt) * s,
      **s = 0.9** (operator); k_d and r slewed under one limiter/hysteresis from the same filtered total;
      **COURSE CORRECTION (operator, evening): constant low-current authority D = 0.30 V, not 0.60 V ->
      SHARE_MINORITY_I_MIN_A 0.30 -> 0.15 A; closed-loop gate 0.30 A (exit 0.25 A); schedule meets the
      0.30 ohm floor at ~0.91 A (fw v26 recovered above it); fw v26 clamp reachability moves to 1.40 A
      (static_asserts re-derived); conduction at a 0.15 A minority under the constant margin is a bench
      HYPOTHESIS the HIL plant cannot test.**
      g <= 1 guard at the code-write site; reseed under the new k_d at the handover; bit-identical to fw v26
      above 2.0 A (schedule floors at 0.30 ohm). Bus sag becomes ~0.6 V design-scale below 2 A.
- [x] 4. (DONE) **BLG v8** record format: the live k_d per record (operator ruled the bump); decoder
      (`tools/decode_benchlog.py`) + tests + the benchlog analysis package updated in lockstep; the 18 B HIL
      frame stays frozen; State-98 'S' line prints k_d.
- [x] 5. (DONE: review SHIP WITH FIXES, H1 survivor-regulator guard + 8 items applied; 4114 / 175 / 4596; committed `153562f` with the flag flip; operator to flash) Review (Opus, safety-first), fix round, three builds (baseline 4024 / 175 / 4506), design record
      `docs/fw27_feedforward_clip.md` -> rename/extend to the governor package, ledger row 27 rev 2, commit
      with the flag flip, push. Then operator flashes.

**Tools era round (one boundary: fw v27 + I_AUX_A 0.09 A), queued behind the firmware:**
- [x] 6. I_AUX_A 0.15 -> 0.09 A in both engines (DONE, under review): fingerprint refusal names the era; all
      three DP tables re-solved (ems-ftp75-dp ~15 min); all 75 dp_db matched records flagged provenance_drift
      (NOT re-solved - queue); walked h2 deltas -6.0 % (ems-sdp) to -30.4 % (ems-ftp75c-sdp), the fixed
      0.060 A as a fraction of each run's draw; AUX-ERA anchors block; four fw26 stimulus preloads raised
      0.06 A to keep the designed totals (joint step stays 1.65 A). RULING NEEDED: standstill total 0.090 A
      is below ASYM_SIMPLE_I_MIN_A 0.10 A, so the simple engine's split law no longer applies at idle
      (code ratio 0.25 vs 0.2599) - lower the floor or accept and record (hi-fi engine unaffected).
      Queue: re-solve the 75 matched-DP records (`dp_results_db.py prefill`, long spans need
      `--matched-dp-allow-long`); alpha-sweep re-run at the measured billing; bench standstill capture
      with the VESC powered to replace the 0.075 A term.
- [x] 7. (DONE `1e0abd4`; the post-G fix round `c708d71` on top) governor_model / ems_walk / MPC surrogate mirror of fw v27 rev 2 (battery-only start, hold, k_d
      schedule), equivalence harness against the firmware (the fw v26 discipline), HIL_PLANT.md FEEDFORWARD
      paragraph; simple-engine bus law and the loss-map DP bound re-derived for the scheduled k_d
      (V0_EFF/R_FIX/K_G at the new g_par law); every anchor re-walked and pinned provisional for campaign G.
- [x] 8. (DONE: addenda 2026-09-03c and 2026-09-04; memory) Suites, commit, push; CLAUDE.md addendum 2026-09-03c; memory.
- [x] 9. (G DONE 2026-09-04 00:31: `hil_report_20260903_233736`, 63/75 suite, zero board defects, 12 FAILs all classified - 1 fw v27 sequencing defect, 2 fw v27 consequences, 1 sim artefact, 6 era scoring items, 1 MPC surrogate defect, 1 calibration reading; G2 = the ten long-cycle legs running in `hil_report_20260904_003108`) Campaign G (HIL, after the operator's v27 flash): the new era baseline — joint leg (1.36 A bound,
      watch first), v6 legs, share-step guard witness = 0, `mpc_share_pred_err` baseline, k_d schedule
      observables, battery-only start on every leg.


**fw v27 rev 3 / fw v28 spec seed (from campaigns G + G2, 2026-09-04; operator to rule and flash - NOT built overnight):**
- [ ] F1 **Break-before-make at the FC-charge window entry from a battery-only state.** The arm is suppressed,
      not disarmed, when FC_CHARGE opens, so assertFcChargeEnable() re-closes FC_BUS from cold and drops
      BT_BUS/REGEN in the same tick; RT1987 t_D_ON 8 ms leaves the bus source-less; V_bus collapses at
      I_AUX/C_VBUS; UV dwell 19.07 ms (charge-to-full) / 17.9 ms (ftp75c x2) vs the 20 ms latch. Preferred:
      chargingControl() clears the arm one commander period BEFORE raising FC_CHARGE so the setpoint latch's
      guarded release re-closes FC_BUS onto a live bus, charge path next tick. Alternative: make-before-break
      with an >= t_D_ON dwell inside assertFcChargeEnable(). Hardware question: the VESC below the sim's 5 V floor.
- [ ] F2 **The arm never releases below the 0.30 A gate** - every cycle whose total stays under it (ftp75c: max
      0.278 A; standstill) runs battery-only for the whole run (h2 -99 %, pack drained). Ruling: release rule at
      low totals (time-based, SoC-based, or a lower gate), or accept.
- [ ] F3 **Forced-0.5000 regime** for totals in 0.25-0.30 A (closed loop below its own entry, empty minority band):
      0.14 A per channel for whole cruise spans (ems-sdp-cross). Ruling: raise the exit to the entry, or clip to
      the rail instead of 0.5, or accept.
- [ ] F4 **Scheduled k_d saturates in single-source FC-charge windows** (k_d 0.906 ohm, mdac_fc 4095, single-source
      droop x3, charge-window sag x3). Hold k_d at K_DROOP while FC_CHARGE is open / a channel is cut.
- [ ] F5 **Share-cut chatter**: SHARE_MINORITY_I_MIN_A 0.15 == SHARE_HANDOFF_MIN_A, so a channel at the floor reads
      dark and the load guard cycles it (58 cuts / 90 s on ems-ftp75-sdp, max 0.21 A, safe). Re-derive
      SHARE_HANDOFF_MIN_A / SHARE_HANDOFF_LIVE_A relative to the floor.
- [ ] F6 The share-loop feedback EMA lets the reference overshoot the clamped rail by ~3 % of r for ~12 ms after
      the fw v26 clamp engages (+0.039 A at 1.57 A; half the ceiling margin) - hazard-budget item, and the walk
      must model it.
- [ ] F7 The battery-only re-entry closes FC_BUS on inherited MDAC codes (r ~0.5): a ~12 ms turn-on overshoot
      (0.2355 A on ems-ftp75-sdp) - benign; consider re-seeding the codes at the clipped band edge on release.

**Campaign H (2026-09-04 02:26-04:05, `hil_report_20260904_022637`, tooling `c708d71`): DONE - 63/75, the twelve FAILs
= the pre-classified set, every tools fix validated on the board; the F1 defect LATCHED on two ftp75c legs (a
third trigger: a charge-window handoff); the joint bound needs a third reading (1.3243 -> 1.2699 A). Budget 2 of 5;
stopped. See OVERNIGHT_LOG.md 'Campaign H result'.**

**Deferred / not tonight:** the alpha sweep re-run at the measured billing (anchor index 7 -> 8; then move the
three `ems-sdp-alpha-*` legs); the long matched-DP re-solves after the I_AUX_A change; the `--droop measured`
split-law scaling (ruling open); the fw v26 joint-leg 8 % MDAC band tightening (after its first campaign);
the two-axis dropout sweep, the pack repeat, the AD5443/OPA197 DMM measurement, the dark-node decay capture and
the tau_r step test (ALL bench, no access).

**Done today (for the morning check):** `fe92a50` split law; `7b1f602` run-002 docs; `26ae346` N9 test;
`88f8e2d` rulings A; `cd296a3`/`96800c7` v5; `9cc2618` addendum; `0848c91` v6 + aux floor + N8 + Step 0 +
droop gap; `2d200b1` fw v27 rev 1 (to be superseded by rev 2 tonight).

## 0b. Carried from the 2026-09-02 review list (still open where not struck)

The session is closed. Two campaigns ran of a budget of five; campaign C is analysed and its fix
round is committed (`5f1cfed`). Read `OVERNIGHT_LOG.md` §MORNING DIGEST (FINAL) first, then the
CLAUDE.md addendum 2026-09-02, then the two ledgers
(`HIL Results/hil_report_20260902_011926/` and `.../hil_report_20260902_041414/`). Six items need a
decision or a read, in this order:

1. **The physics change record and the review's three majors.** `docs/HIL_PLANT.md` §4.6.1–§4.6.2 and
   `docs/reviews/hil-plant/run-001-2026-09-02.md` §Adjudication. Details below.
2. **The MPC design, its live calibration reading, and the fallback decision.** Item 2 below.
3. **The lever measurement and the α re-solve decision.** Two campaigns now agree; α ≈ 0.1343 on the
   measured levers. Item 3 below.
4. **The FTP-75 socband result and the frontier tie.** The socband leg's FAIL was the settling-hold
   defect, fixed in `5f1cfed`; on a ≥ 5 ms guard it passes at 0.6930 A. sdp-v4 and the MPC read within
   0.015 % on FTP-75, inside the ~50 ppm repeatability floor — TIED, do not rank.
5. **The `regen-harvest-true` floor restoration.** The WP-1C lowering (max_of 1.0 → 0.65 J, total_of
   3.0 → 1.9 J) is measured out: campaign B read 1.5810 / 6.3525 J and campaign C 1.5938 / 6.3578 J.
   Restore the floors from the board figures (calibration batch below).
6. **The candidate-cap and budget-expiry finding.** Lifting `MPC_CAMPAIGN_MAX_CANDIDATES` to 1029 made
   the charge axis reachable (`cut_by_cap` 0 on all four legs) but pushed `ems-mpc-cross` to expire the
   10 ms budget on **57.4 %** of decisions. `5f1cfed` raises that leg to `mpc_budget_ms` 15 ms and
   reports `candidates_max`; confirm the budget rather than the cap is the right lever.

Detail on items 1–3, then two actions that follow from them:
- **Physics.** `docs/HIL_PLANT.md` §4.6, §4.6.1 and §4.6.2: the charger is now an energy converter
  at `ETA_CHG` = 0.88 in both engines, stamped as a chord conductance with an 8.0 V floor, with an
  output-referred regen cap that is deliberately NOT netted against the chopper. The six-item
  reversal path is in §4.6.2; `ETA_CHG` = 1.0 alone does not revert the round. Read it together
  with the adversarial review's three majors (`docs/reviews/hil-plant/run-001-2026-09-02.md`
  §Adjudication): **F2** — the "6.5 % bus-sourced regen leak" was misattributed and is
  0.088059 J / 0.118 W of post-clamp-release bus-fed CHARGING through a forward-conducting
  `MOT_PWR`, so the co-solve `TODO(verify)` is retired; **F4** — open loop has two submodes and the
  slew-limited FEEDFORWARD does write the MDACs (356 write ticks on `ems-y-b00-v3`), which is the
  MPC Gate-1 mechanism; **F1** — observation-frame byte 15 is a fiat mirror under `HIL_SIM`
  (11.8 % of ticks differ, max 12 counts) and two suite labels asserted the manager ran.
- **MPC design, the live calibration reading, and the cap caveat.**
  `docs/modeling/mpc_design_20260901.md` §6.5, §8 and §9. Gate 1 FAILS offline with the roll table
  consulted (mean 0.00971, max 0.25000, band 5e-03) and the round shipped `mpc-det` / `mpc-sto`
  live with that recorded. **Campaign B measured the board-side error and it is the designed
  structure:** closed-loop prediction exact (median 1e-5 on both stimuli), all error open-loop
  (`ems-mpc` mean 0.06054 / max 0.21893 open against 0.00418 / 0.124 closed; `ems-ftp75-mpc` over
  345 decisions), live max under the offline Gate-1 0.25 — keep the 0.30 band. ⚠️ **Cap caveat:**
  at `MPC_CAMPAIGN_MAX_CANDIDATES` 343 = 7³ = one charge option's enumeration, with no-charge
  enumerated first, the cap truncated BEFORE the charge axis on every capped decision (13 of 61 on
  `mpc-sto`), so **no "the MPC chose not to charge" reading is supported by campaign B**. The cap
  is 1029 from `6c28dd2`; campaign C ran at that cap with `cut_by_cap` 0 on all four legs, so the
  caveat is LIFTED and FC_CHARGE rises 0/0/0/0 now reads as a decision. ⚠️ **The cap lift moved the
  binding constraint to the budget:** `ems-mpc-cross`'s median solve is 10.002 ms and 57.4 % of its
  decisions expire the 10 ms budget (`ems-mpc` 6.6 %, `ems-ftp75-mpc` 10.3 %, `mpc-sto` 0 %). Expiry
  returns the shifted incumbent, so no unsafe command is issued; `5f1cfed` sets that leg's
  `mpc_budget_ms` to 15 ms and reports `candidates_max`.
- **The measured lever pair and the α decision.** Two campaigns now agree: campaign B read
  **L_chg 0.33214 / L_share 0.41688 SoC/g** and campaign C **0.331758 / 0.416896** (−0.114 % /
  +0.004 %, ratio 0.7958). The projected inversion is REFUTED and the model's ordering holds; the
  end-to-end charge round-trip on the board is **0.797, not η = 0.88** (bus sag 15.76 → 14.15 V
  billed to the charge leg — plant physics, not the solver). ⚠️ `sdp_policy_v4`'s α 0.118326 sits
  **1.34 % below** the measured admission window (0.11993, 0.15071) in BOTH readings. **The hold is
  released: a measured-lever re-solve to α ≈ 0.1343 is now an operator decision**, and the eq-H2
  ordering (greedy +1.125 %, charge +3.829 % against the calibrated leg) reproduced exactly.
- *(Closed review item: the power-on INIT_FAIL. Campaign B's first run opened at 0xa010 /
  `error_code` 0x0e after the evening re-flash; it did NOT recur in campaign C, whose first run
  opened at 0x8011 = campaign B's last latch word, so the chain holds across the campaign boundary
  and the observation is attributed to the re-flash's power-on path.)*
- *(Superseded review item: the `regen-harvest-true` floor lowering, max_of 1.0 → 0.65 J and
  total_of 3.0 → 1.9 J, is measured out — campaign B read 1.5810 / 6.3525 J and campaign C
  1.5938 / 6.3578 J. The calibration re-pin from the board is queued below.)*
- **MPC fallback decision (still open).** Either adopt the design's own fallback — full governor rolls
  on open-loop stages with a reduced candidate set, `mpc_design_20260901.md` §3.5 and §7.1 — or
  build a feedforward-aware stage model, or accept the surrogate and keep `mpc_share_pred_err` as a
  measured band. The board-side reading is the input: the surrogate is exact where it is closed-loop
  and carries all of its error in the open-loop stages the F4 finding named, and campaign C reproduced
  that structure to the digit (closed median 1e-5, open max 0.21894 against B's 0.21893).
  Reversal if the legs are to be withdrawn: drop the four `ems-mpc*` scenarios, one commit.
- **De-provisionalise from campaign C.** The OC ceilings that had no η-era run in campaign B are now
  measured (`ems-sdp-cross`, `ems-sdp-braking`, `mppt-tracking`), as are the MPC bands. Pin them from
  `hil_report_20260902_041414` before the next campaign.

## 0a. Campaign B and C fix queues — shipped and carried

Sources: `HIL Results/hil_report_20260902_011926/HIL_FINDINGS.md` §FINAL SUMMARY (ranked queue) and
the per-batch fix lists A1-*, A2-*, A3 F1–F8, A4-*, A5-*; the fix-round review of `6c28dd2`; and
`HIL Results/hil_report_20260902_041414/HIL_FINDINGS.md` §FINAL SUMMARY. All items were tooling; none
were firmware.

**SHIPPED in `5f1cfed` (post-campaign fix round; review 2 HIGH + 3 MED + 9 LOW, all accepted):**
- HIGH — socband charge-window mask **settling hold** (`exclude_hold_ms`, 10 ms on both arms; import
  guard refuses a hold without the mask). This closes the one FAIL campaign C produced.
- HIGH — a test for the **finalize-in-`finally`** path, which the campaign-B round shipped uncovered.
- MED — `substep_resolution` becomes a **WARNING** and fails only on a sustained collapse fraction
  above 0.1 % of the run; `n_sub_last` logged (campaign C: 0 sub-gate ticks, min n 11 against gate 8).
- MED — the `finally` teardown is **guarded item by item**, so a bad glyph in a deferred note cannot
  skip the finalize.
- MED — `mpc_h2` **informational** on `ems-mpc-cross`, `candidates_max` on the summary line, and a
  per-scenario `mpc_budget_ms` (cross 15 ms).
- LOW batch — mppt pin trimmed to (37.75, 38.44) in `min_value` + `min_ticks` form; `not_exercised`
  derived from `replay_commands`; census scalars only in `results.json`; the asymmetry-era anchors
  block; the teardown-lead band documented as **0.04–0.55 ms**; the `HIL_PLANT.md` substep sentence.

**SHIPPED in `6c28dd2` (tooling fix round; docs half in `7026e3b`):**
- HIGH — cp1252: ASCII summary and warning text, a lossless console, sidecar/event finalization moved
  into a `finally` ahead of any summary print, and the sdp-v2 binder's `except` narrowed so a
  `UnicodeEncodeError` cannot masquerade as a bind failure.
- HIGH — `scan_signals()` threshold tick counter on the numeric path, plus an import guard refusing
  unimplemented spec pairings. `regen_clamp_dwell` keeps its 800 floor (measured 1173 continuous).
- MED — `MPC_CAMPAIGN_MAX_CANDIDATES` 343 → **1029**, so the charge axis is reachable.
- MED — mppt mirror pin in peak-reaching form over a window clear of the regen-lifted braking
  windows; `mppt_threshold_written` / `_moved` relabelled as a carried mirror.
- MED — socband FC tripwire split (charge-free ≤ 0.85 A via the new `exclude_when_switch_bit` mask;
  charge-window ≤ 1.25 A), `socband_fc_carried` re-pointed at the charge-free peak, h2 band
  re-derived to [0.034, 0.051].
- MED — matched-DP prefill of the seven η-era EMS keys (era_overrides `eta_chg` 0.88) and the
  regen-bearing label: dp-replay −0.20 %, sdp −0.35 %, soc-band +3.87 %, ftp75-5050 +5.73 %,
  -dp +4.35 %, -sdp +8.53 %, -socband +7.45 %.
- MED — replay half: a `share_cut_census` entry that is a NOTE rather than a scored check and
  `not_exercised` markers so an unexercised check reads as a count. ⚠️ The baseline under the tool's
  own definition is campaign C's **118 cuts / 6 over the own row / 2 over the previous row / peak
  0.5722 A**; campaign B's hand-derived 163 / 8 / 4 / 0.6608 A used a different definition and the two
  are not comparable.
- MED — `substep_resolution` gate (n_min ≥ 8) with `elec_substep_n` logged (review F6 code item).
- MED — conventions: `asymmetry` added to the run-era fields; the bus-draw ratio marked
  probe-point-specific (0.5565 → 0.64 at a 14.1 V bus); the replay share-guard coverage statement
  corrected in `docs/HIL_REPLAY_LOGS.md`; the standing walk rule is now "model the open-loop hold
  AND the feedforward slew".
- LOW/record — the η-era measured levers recorded in `measured_levers()` (α unchanged).

**CARRIED (open):**
- *(Closed: the asymmetry-era re-pins. Campaign C reproduced `scp-inrush` `i_cut`
  **6.362274641096594 A bit-exact to 16 digits**, `handoff-sag` bit-exact, `comm-loss` re-close on both
  channels 0.3801 / 0.3379 A, and the `soc-depletion` UV_BATT latch at 270.976079 s (3.7 ppm). The
  anchors block shipped in `5f1cfed`.)*
- **`ems-mpc-cross` and `ems-mpc-sto` walk re-derivation, cap-lifted — STILL OPEN and now urgent.**
  Both walks must be re-derived at cap 1029 and 15 ms and the legs re-banded. The cross band must NOT
  be widened to pass: the leg read −0.13 % of the floor in campaign B and +0.10 % in campaign C, so the
  band edge sits inside the MPC's own non-reproducibility and the check is a coin flip as written — it
  is informational (`5f1cfed`) only until the re-walk lands. The `mpc-sto` walk is the suspect on its
  own −13.2 % (det matched its walk to +0.05 % on the other two stimuli).
- **Per-stage DP residual check.** `ems-ftp75-dp` reads −4.14 % h2 and +19.6 % ΔSoC against its own
  correctly-paired table (widened from −2.15 % / +4.8 %). Build the per-stage `cmd_share_sp`-versus-
  table residual check; attribution (PLANT-R1-F5) is the open-loop hold, not `Gfc` dynamics.
- **`ems-y-b00-v3` gate fraction by governor-model replay.** A raw instantaneous `I_total` < 0.55 A
  proxy reads 68.3 % and is not comparable with the 20.6 % / 12.7 % figures; the governor gates on a
  filtered total with hysteresis. Quote the range until the walk settles it.
- **`PLANT-R1-N4` (open-unverified).** `FC_BUS.i` as an INA proxy may under-report a bus load step by
  half at one operating point. A reproducible operating-point test is required before any doc entry.
- **Line-citation provenance.** The docs fix round replaced the stale `.ino:`/`.py:` line references
  in `HIL_PLANT.md` with symbol and pinning-test provenance, but the fix-round report leaves **56
  line citations across three documents** un-audited (`HIL_USER_MANUAL.md`,
  `docs/HIL_REPLAY_LOGS.md` and `docs/modeling/mpc_design_20260901.md` still carry `file:line`
  forms). Audit them before any is used as provenance. ⚠️ The 56 figure is the fix round's own count
  and has not been reproduced from the documents.
- **FTP-75 frontier λ-sensitivity caveat.** Both `ftp75` tuples are still UNVERIFIED, in campaign C
  only through the socband reference's predicted FAIL; on the readings they would have given, sdp-v4
  reads 0.96632 / 0.99863 and the MPC 0.96617 / 0.99849 — **within 0.015 %, inside the ~50 ppm
  repeatability floor: TIED, do not rank**. And **49.6 % of the candidate's eq-H2 is the λ correction**
  (a ΔSoC gap 21× cycle61's), so never quote an FTP-75 ranking without the λ-sensitivity statement.
  The settling-hold fix (`5f1cfed`) should let the reference pass on the next campaign.
- **Replay sub-5 ms cut chatter (INVESTIGATE-LOW).** 58 of ML0203's 119 in-Run cuts follow a dwell
  under 5 ms (min 0.5 ms, BT_BUS chatter at the band edge), and ML0151 cuts a channel 2.0 ms after
  its own rise — inside an unfinished CSS soft-start that the survivor-keyed blanking does not
  cover. Not a defect claim; it is unscored behaviour nobody has characterised.
- **LOW calibration batch.** Re-pin the `regen-harvest-true` chopper bands from the board
  (2.109–2.133 J/window, 6.35 J/run — the probe under-predicted 1.6×); record the `charge-regen`
  chopper era baseline (~0.48 J/window where the 1:1 era clamped 0.0000 J); record the
  `charge-fault` collapse-to-re-inhibit spread 14.9–30.2 ms (record, do not score); ledger the
  `ems-sdp-alpha-charge` FC_CHARGE window-close `i_cut` **0.5093 A** at 55.348 s (the campaign's
  tightest reading against 0.5 A, on the charger switch, outside `share_cut_load_hazard`'s scope by
  design); MPC design §2.5's `mdac_corrections` claim is stale (2968 measured); `rx` 350002 against
  `tx` 350000 is cosmetic; and the A5 suite-LOW batch (uv_bus_latched wording, two non-existent
  check-name references, a YP0166 `oc_margin` pin at 82.3 %, SY0001 `no_fault` at 3.6 %).

## 1. EMS test-program goals (operator directive 2026-09-01) — status

1. **Aux preload removed from drive cycles — DONE (2026-09-01e B1).** `FTP75_PRELOAD_A` /
   `FTP75_SDP_PRELOAD_A` → 0.0; `Y_AUX_LOAD_A` stays. Campaign 151156 is the last preloaded era.
2. **ΔSoC-matched post-hoc DP — DONE (2026-09-01e B2), extended this round.**
   `hil_report_analysis.py --matched-dp {off,lookup,solve}` + `tools/dp_results_db.py`. This round
   fixed the backward pass, which still billed the charger at `V_bus` while reporting the η era
   (latent for the three committed tables, live at λ_term 3.5–6 and for 3 of 16 records), restored the
   database CLI (ten duplicate `--eta-chg` registrations), and made 16 of 16 records reachable again
   by omitting `eta_chg` from the fingerprint when it is None. Open: the `ems-ftp75-mpc` prefill (§5).
3. **α-sweep — DONE, re-solved in the η era.** `tools/sdp_policies/sweep_20260902_eta088/` (41
   artifacts) and `docs/modeling/sdp_alpha_sweep_eta088_20260902.md`. Boundaries 0.110999993716 and
   0.126136356495; live picks idx 3 / 7 / 14 bound to `ems-sdp-alpha-greedy` / `-cal` / `-charge`
   behind `--with-alpha`. The drive cycle now discriminates all three legs.
4. **EMS comparison deliverable — per-campaign form DONE.** The cross-campaign, cross-cycle roll-up
   is queued behind campaign B's η-era numbers, which are the first that may be differenced against
   the η-era DP tables.
5. **Governor-aware MPC — REGISTERED, Gate 1 OPEN.** `tools/mpc_ems.py` ships `mpc-det` and the
   stochastic variant `mpc-sto` (TPM-driven, certainty-equivalent demand plus a 90 % quantile
   overcurrent tightening), both registered as strategies with four scenarios (`ems-mpc`,
   `ems-mpc-sto`, `ems-mpc-cross`, `ems-ftp75-mpc`), three CSV columns, `config.mpc`, eight
   command-line flags and the `cycle61-mpc` / `ftp75-mpc` frontier tuples. Gates 2 and 3 ran; Gate 1
   FAILS on `ems-soc-band` (§0 item 2). Every band carries a `provisional_note` and is calibrated
   from campaign B. **Ran live in campaign B:** `mpc-det` ties sdp-v4 on the 61 s cycle, the
   board-side prediction error is exact closed-loop and entirely open-loop otherwise, and the
   information ablation is measured (`mpc-sto` −22.5 % h2 at +38.7 % drain). **Campaign C ran at cap
   1029 with `cut_by_cap` 0 on all four legs**, so the charge-behaviour reading is now supported (0
   FC_CHARGE rises) and the frontier tuple is certified at 0.9606× / 1.0007×. Open: the budget expiry on
   `ems-mpc-cross` (§0 item 6) and the cap-lifted walk re-band (§0a).
6. **Converter asymmetry — DONE (2026-09-01e A4 + C1).** ΔV0 and ρ adopted as the M2 consistent pair,
   default-on, `--asymmetry off` byte-identical. The +8.1 % shared/single residual and the ~4×
   `K_DROOP` finding stay open. Bench `TODO(calibrate)`: an 'O' open-loop share sweep above 0.60 A.
7. **Plant physics review against SD logs — DONE (2026-09-02).** Run record
   `docs/reviews/hil-plant/run-001-2026-09-02.md`, ledger `docs/reviews/hil-plant/ledger.md`.
   Three major findings (byte-15 fiat mirror; the chopper/`MOT_PWR` topology; open-loop
   HOLD-versus-FEEDFORWARD), five minor, one nit, one open-unverified (`PLANT-R1-N4`, the
   `FC_BUS.i` INA proxy — needs a reproducible operating-point test before any doc entry). The
   "6.5 % bus-sourced regen leak" input to this item was **misattributed** and is corrected to
   **6.3 % / 0.0880 J of post-clamp-release bus-fed charging** (see §5 and §3); the co-solve
   `TODO(verify)` is retired.

## 2. Pi bridge v4 parser audit — DONE (2026-09-01e)

`docs/PI_BRIDGE_V4_AUDIT_20260901.md` + `docs/pi_bridge_change_request_20260901.md` (send to the PhD
student) + `tools/test_pi_bridge_v4.py`. The 08-17A bridge is v4-conformant byte for byte. Mode B is
gated on the Pi running that bridge with a FIXED `sdp_ems_node` (the 03-16A node reads the 15-element
layout — unsafe on its SoC branch — and the default launch file starts it) and on the standalone SDP
scripts being retired or updated from the 54 B protocol. The bridge's stale-link handler overwrites
the fault word (a bitwise OR is needed). Pi-side SoC is a `V_batt` LUT, so it is not comparable with
sim-only strategies.

## 3. Bench items feeding TODO(verify)s

- **Ag105 charge efficiency at OUR operating point — NEW.** The datasheet's 88 % typ is stated at
  25 °C, 12 Vin and 3S; the rig runs 15–16 Vin into a 2S pack, roughly a 1.9:1 conversion where the
  datasheet measured roughly 1.0:1. Bench-measure input and output power at 15–16 Vin, 2S.
- **~~The 6.5 % bus-sourced regen leak~~ — CLOSED 2026-09-02, no bench work needed (PLANT-R1-F2).**
  The number is **0.088059 J of a 1.4016 J charger input, 6.28 %**, and it is not a leak: `MOT_PWR`
  is strict-forward, so the contribution is exactly zero while the chopper clamps and appears only
  after clamp release, as 0.118 W of bus-fed CHARGING through a forward-conducting `MOT_PWR`
  (V-MOT parked at V_BUS − 35.3 mV, 14.93 mA; deleting the link gives 0.000000 J). The queued
  charger/clamp co-solve targeted a mechanism that does not exist and is **retired**; the 0.15 J /
  12 % test ceiling is replaced by two mechanism-specific assertions.
- **Re-measure the charge lever — NEW.** The 0.2364 SoC/g figure was measured on the 1:1
  current-transfer plant and only projected into this era. The projection is what makes the measured
  window UNDECIDABLE, and it is what the first η-era campaign tests.
- VESC regen commanded-versus-delivered mapping (`VESC_REGEN_I_MAX_A` + `ETA_REGEN`).
- 30 ms survivor blanking against a REAL RT1987 turn-on (HIL validated the logic against the modelled
  `t_D_ON` only) — asymmetric failure direction; never shorten it on the model alone.
- Boost-OR `strict_forward` A/B comparison.
- MPPTD-disabled-charge semantics.
- Silvertel EPROM endurance — `TODO(verify: Silvertel)`.
- Open-loop share sweep ('O' command) above 0.60 A for the asymmetry fit (§1 item 6).
- **Two-axis per-channel dropout-boundary sweep — NEW 2026-09-03 (§7c prerequisite).** Setpoint at
  fixed I_max and I_max at fixed setpoint, run separately for the FC-minority and BT-minority
  directions; repeat WP0073/WP0100 on the pack rather than the 1.0–1.35 Ω bench battery supply.
  Sizes `M_floor` for the margin-referred governor and how far the floor moves under a scheduled
  `k_d`. The share-sweep whitepaper's standing recommendation (conclusions 11 and 15), absent from
  this queue until now. Existing brackets: FC-minority (0.245, 0.29] A at 1.6 A total; BT-minority
  (0.381, 0.399) A at 1.6–1.7 A and dropouts at 0.55–1.04 A in the W cluster. **Procedure:
  `controller_design/bench_calibration_manual.md` CAL-6** (2026-09-04) — lowered-floor bench
  build (`SHARE_MINORITY_I_MIN_A` 0.10 A) is its one firmware prerequisite.

## 4. Protocol flags

- `sw_ring` state field — not on the observation frame.
- `shareCutRefusedLoad` / `shareCutRefusedBlank` tick counters — not on the frame (campaign 151156
  proved the refusals only indirectly, from the guard arithmetic).
- `error_code` — ON the frame (fw v25) and consumed by the analysis (attribution + CSV).

## 5. Open analysis questions

- **`dp_db prefill --scenario` era drift.** The registration agent found that a `--scenario` prefill
  keyed an explicit era while fingerprinting the LIVE scenario metadata, which produced records no
  post-era lookup could hit. The era is now resolved into the fingerprint metadata as well, and the
  two era flags are mutually exclusive rather than silently ranked. The residual is structural: a
  `--scenario` prefill still reconstructs from live metadata and therefore drifts whenever a scenario
  changes, so the exact-reproduction path remains `prefill --key-fields @file`.
- **`ems-ftp75-mpc` `dp_db` prefill is PENDING.** Its matched solve costs tens of minutes and the
  FTP-75 bound leg's own table is stale, so the entry was deferred rather than stored against a
  stimulus that is about to be regenerated. Prefill it before campaign C, never during a campaign.
- **The chopper side of the residual identity is DEFERRED (physics review L3, re-affirmed
  PLANT-R1-F3).** `p_chop` sits on the source side although it is a dissipation, so a braking-window
  residual is dominated by −2·p_chop. Measured on `regen-harvest-true`: chopper-active mean
  `p_bal + p_aux` − 2.3876 W, of which − 2.0208 W is that term. `p_bal_w` is a pure observer — no
  published number derives from it in a braking window — so the defect is wording, not a result.
  Moving it beside `p_mot` and `p_chg_loss` changes the meaning of `p_bal_w` in every CSV written
  since 2026-09-01f, so the migration is tied to **the next change of the identity** rather than
  scheduled on its own.
- **`ems-ftp75-dp`: the table's walk-side fingerprint is stale.** `ftp75-mpc` reads vs_reference
  0.9738 and has no vs_bound prediction, because `dp_ems_table_ems-ftp75-dp.csv` carries a stale
  stimulus fingerprint and refuses to walk until it is regenerated. The older residual stands too:
  run h2 −2.15 % and ΔSoC +4.8 % against the table's own prediction, with a per-stage residual check
  queued. ⚠️ **The gap WIDENED in the zero-preload / η / asymmetry era** (campaign
  `20260902_011926`): `ems-ftp75-dp` now reads **−4.14 % / +19.6 %**, while `ems-dp-replay` reads
  +0.33 % / −1.2 %. Attribution (PLANT-R1-F5): the generator has no share loop or governor, and at
  zero preload the firmware's sub-0.55 A open-loop behaviour covers 64.5 % of the FTP-75 Run window.
  The dynamic-versus-DC `Gfc` difference is only 0.01–0.03 % and does NOT explain it.
- Does the charger lever clear the 0.31 SoC/g `sdp` charge-revisit condition in the η era? **Measured
  twice and yes:** `L_chg` 0.33214 (campaign B) and 0.331758 SoC/g (campaign C), against a model value
  of 0.396396 and a trigger of 0.31. `sdp_policy_v4` nonetheless rejects charging endogenously at
  α 0.118326, and the measured admission window puts that α 1.34 % too low — which is the α re-solve
  decision in §0 item 3, not a separate question.
- `ems-y` b00-v3 gate fraction (campaign 20.6 % against walk 12.7 %) — the governor walk can settle it.
  ⚠️ **20.6 % does not reproduce** (2026-09-02): three recomputations give 16.98 / 19.33 / 19.13 %.
  A raw instantaneous `I_total` < 0.55 A proxy reads 68.3 % and is not comparable with either — the
  governor gates on a FILTERED total with hysteresis. Quote the range until the walk settles it.

## 6. Housekeeping

- **CLAUDE.md is 78 KB after the 2026-09-02 addendum**, despite two rotations this session
  (`c4abc39`, `faecc58`). The addendum is current and must not rotate yet; rotate the 2026-08-16c and
  2026-08-25 addenda at the next opportunity, keeping the three bodge records in place.
- Campaign ledgers live in the gitignored `HIL Results/`; promote one to a committed skill exemplar?
- Rebuild the benchlog analyzer exe (pending since fw v18; `asymmetry_fit` is not part of the exe).
- The `.venv_hil` stdlib / miniforge numpy split stands (run `tools/` under `.venv_hil` with
  `--ignore=tools/test_figures.py`).
- `Rs(SOC)` calibration against a real 2S pack; hi-fi M1 re-arm live coverage; early-exit guard.
- `references/Systemic_Scaling_…pdf` was rewritten in the working tree on 2026-09-01 by something
  outside these rounds (18 KB smaller); not committed, operator to check.

## 7. Model and tooling improvements (open)

- Gfc stack identification (absolute H2); SDP smoother stage cost (FC efficiency curve).
- `signal_series_verdict()` native two-sided spec support.
- TPM generator contract wording (sidecar normalization is documentation for the SDP path).
- Ag105 policy on real hardware (lazy re-config, FC_CHARGE open-through-loss).
- Replay half cannot exercise `share_cut_load_hazard` (no events.jsonl; share replays are not
  opt-in) — add an opt-in share-stimulus replay entry if guard coverage from the replay half is wanted.
- Governor model: `conv_tau_s` fit reported (shallow optimum 5–10 ms), not adopted; `ems-sdp-braking`
  is outside the model's fidelity claim.
- MPC: a mean-side assertion on `mpc_share_pred_err` would be the better check (the mean is 26× under
  the max), but `run_hil_suite.py` has no column-mean check kind.

- **EMS share-range rule (operator ruling 2026-09-02).** Every EMS strategy must have access to
  the full firmware command band [0.15, 0.85]. The DP grid and the MPC ladder were narrowed to
  [0.25, 0.75] on 2026-08-31 and are being widened (stage-2 follow-up). Still narrower by
  design: `soc-band` (0.50 +/- 0.25) -- widening its span changes the frontier REFERENCE leg and
  is an operator call. RULING (later 2026-09-02): the 0 / 1 single-source command
  (through the firmware's setpoint latch / cut-and-restore topology, subject to the 0.5 A
  share-cut load guard) is added to the MPC ONLY (its governor rolls make the guard and the
  restore slew exact) and OMITTED from the DP and SDP (a 3-value mode state, ~3x solve cost,
  and little hydrogen value while ETA_BOOST is flat and Gfc is linear). Bench prerequisite for
  any of it to matter: TPS61288 efficiency vs load (TODO(calibrate)).

- **FIRMWARE (fw v26 candidate): FC-current-ceiling share governor (operator directive
  2026-09-02).** Keep the `OC_FC` fault unchanged. Add a governor extension in the share loop:
  when the fuel-cell current approaches its limit, clamp the delivered FC share so that
  `I_fc` holds at a ceiling below `LIMIT_I_FC_MAX` and the share falls as the total current
  rises, i.e. `share_max(I_tot) = I_FC_CEILING / I_tot`, so the battery supplies every ampere
  above the ceiling. Purpose: fewer `OC_FC` latches while permitting higher-power actions.
  Design points to settle in the round: the ceiling and its margin/hysteresis under
  `LIMIT_I_FC_MAX` 1.4 A (fast enough against the OC detection window, no chatter at the
  ceiling); interaction with the minority-current clip (`SHARE_MINORITY_I_MIN_A`), the
  setpoint band and cut latch, the slew limiter and the fw v25 share-cut guard (the clamp
  must never command a cut); behaviour in the open-loop HOLD/FEEDFORWARD submodes (the clamp
  needs a current measurement, so it is a closed-loop-mode feature - decide what open loop
  does); a symmetric battery-side ceiling (RULED IN, later 2026-09-02: much higher ceiling, not expected to bind often); IN PROGRESS as fw v26 (implementer launched 2026-09-02 evening for a same-night flash); a telemetry
  indicator that the clamp is active (a status bit - protocol bump if added); host-native
  tests; bench validation on the `charge-cruise` / `ems-ftp75-socband` class of stimulus
  that latched `OC_FC` before. Documentation: CLAUDE.md governor section, PLAN.md,
  docs/firmware-versions.md, HIL_PLANT.md section 4.4 (the governor modes), HIL_SCENARIOS
  (the `OC_FC` allowances that become reachable-but-clamped). Modelling: `governor_model.py`
  port + firmware-equivalence test; `ems_walk.py`; the DP/SDP demand-side FC-budget test
  (`charge_mask()` currently treats over-limit stages as infeasible; with the clamp the
  delivered share is `min(commanded, ceiling/I_tot)` instead); the MPC closed-stage surrogate
  gains the clamp as a delivered-share bound and the transition rolls pick it up from the
  governor port; Gate 1 re-measured. Sequencing: after the current DP round; the HIL plant
  and MPC model the clamp only once the firmware defines it, so the firmware design comes
  first.

- **Test hygiene: pin the wall-clock-adaptive hi-fi substep in every energy-tolerance test.**
  `test_regen_harvest_is_not_sourced_from_the_bus` (and earlier today
  `test_eta_chg_is_inert_on_a_charge_free_trace`, `test_asymmetry_off_is_byte_identical...`)
  fails under concurrent load and passes in isolation because `ElectricalSim.step()` re-derives
  `_n_sub` from a wall-clock EWMA. `substep_pin=` exists since stage 1; sweep the suite for
  tests that assert energies/voltages to tight tolerances and pin them.

- **fw v26 framing (operator, 2026-09-02 evening):** `OC_FC` latching in an FC-charge window is
  DESIGN INTENT - it is feedback to the EMS that charging should not have been enabled while the
  motor demand exceeded the fuel cell's headroom. The FC-share clamp is intended functionality
  regardless of prior campaign results, not a fix for the recorded latches. FC charging should
  only be admitted when the system has headroom for it (an EMS-side admission rule).
- **LOW priority (tomorrow or later): charge-window guard / Ag105 charge-current reduction.**
  Lowering the Ag105 charge current from the EMS during FC charging while motor load rises is
  "nice to have"; design it as an EMS-side headroom rule first (admission = predicted I_fc with
  charging below the ceiling), firmware-side only if the EMS latency proves too slow. Not before
  the fw v26 clamp is validated on the bench.
- ~~**MPC 0/1 single-source enumeration: RULED rollout-time cut-guard test** (2026-09-02).~~
  **SHIPPED 2026-09-03** — two candidate columns at block 0, admissibility by a bounded roll of
  the real `GovernorModel` from the committed shadow state, `ems-mpc-single` registered in the
  default plan, band checks exempting exactly 0.0/1.0. Design record + Gate-2 table:
  `docs/modeling/mpc_design_20260901.md` §2026-09-03. ⚠️ **The gain is 0.01–0.43 % of equivalent
  hydrogen** while the hydrogen headline moves up to 49 % — a control-set completeness change,
  not a performance one. Two follow-ups left open:
  - **Gate 1 was not re-measured single-source-aware.** A latched stage delivers an exact rail,
    so `mpc_share_pred_err` is trivially satisfied there and the whole-run figure is diluted
    rather than tested. The honest form is an in-band-stages-only split.
  - **`ems_walk`'s single-source demand is opt-in** (`single_source_demand=True`).
    `ems-y-b00-v1` and `-v3` have always commanded 1.00 and 0.00 through that walk on the
    TWO-source bus law; closing that older fidelity gap moves those anchors and is a separate
    decision.

## Shipped 2026-09-03 (overnight, fw v26 campaigns D and E)

- **fw v26 tools mirror** (`c8b50ff`): `governor_model.py` clamp port proven equivalent to the
  firmware by `test/gov_ceiling_harness.cpp` vs `tools/test_governor_ceiling_equivalence.py`;
  delivered-share semantics in DP/SDP/MPC/walk with feasibility on the COMMANDED FC current and
  the delivered BT current (ruling D-3); `fw26-clamp-cruise` / `fw26-clamp-sweep` scenarios; aux-bit
  masks; BLG `share_gov_ceiling`; reachability corrected (`ems-y-b30-v3` is the only registered
  stimulus over the ceiling; 12–13 ticks measured).
- **Post-campaign-D fix round** (`d941170`): ftp75c chopper aggregator relocated + three import
  guards; MPC share band from `SHARE_BAND_DP`; `sw_ring` `over_absmax` verdict gated at the 0.5 A
  load-dump class (ruling D-2); mppt cruise window after the mirror goes live; ftp75c FC budget
  split; regen-manager two-level release (arm −0.2 A / release −0.1 A, ruling D-4 refined); BLEED-ERA
  anchors re-pinned; drain-scenario mirror derived from the simulator + read-time witness; 20
  matched-DP records.
- **MPC single-source enumeration** (`7de3f11` / merge `4887bd3`): see §7 entry (struck).
- **Campaign-E fix round** (this session's last commit): sweep bridging at the both-axes boundaries;
  cruise step pins (`reach_within_ms` spec kind); design record §8.6; `regen_early_releases`
  refreshed in `finalize_meta()`; `CANDIDATE_COST_MS_NOMINAL` 0.0360; `load_dump_rings` census row;
  conventions (State-99 non-evidence trap, aux carried-in rule, `steady` first-run rule).
- **Campaigns:** D (70/70 correct, first bleed era, loss-map bound validated, first ftp75c legs) and
  E (72/72 correct, eight D FAILs closed by their fixes, clamp calibrated, first certified ftp75c
  frontier). Ledgers under `HIL Results/`.

## 7b. Opened 2026-09-03 (from campaigns D and E)

- **MPC stage-model guard against a share step during a rising demand** (from the sweep latch):
  the ladder moves 0.0875 per decision; at 2.0 A that is 0.175 A of FC demand against the clamp's
  0.15 A headroom, and the stage model does not exclude an upward rung concurrent with an upward
  demand step. Rule: no upward share step in the same decision as an upward demand step above
  1.647 A two-source. Design: `docs/modeling/mpc_design_20260902_nonlinearities.md` hazard item.
- **Joint-transient clamp leg** (`fw26_current_ceiling_governor.md` §8.6.5): aux load step
  1.20 → 1.65 A concurrent with share 0.40 → 0.84 (walked peak 1.3303 A, 5971 clamp ticks); needs a
  stepped aux-load branch in `apply_scenario()`. The 1.55 A version cannot exercise the clamp
  (minority clip binding).
- **MPC Gate 1 single-source-aware** (in-band stages only) and the `ems_walk` two-source-law gap on
  `ems-y-b00-*` (from the MPC 0/1 round).
- **`CANDIDATE_COST_MS_NOMINAL` rule**: shipped as the two-campaign mean 0.0360 (max+15 % would be
  0.0427 and coarsen harder); read `mpc_budget_hit` / `candidate_cost_over_nominal` on the next
  campaign before settling the rule.
- **ftp75c realizable regen fraction** 0.63 vs the design note's 0.707 (window-length distribution
  against the ~0.9 s Ag105 dead time) — update `ftp75c_regen_cycle_design_20260902.md`.
- **Physics review of `docs/HIL_PLANT.md` (run 002)** over the bleed change, the loss map, the regen
  model, the estimator's physical option (i·√(L/C) in place of the fixed 1.95 V Death-5 term), and
  the ~70 %-optimistic latch-shift model — per the standing "after one campaign" rule; not run
  overnight (host load during campaigns).
- **Hygiene:** `hil_plant_sim.py` ~8744 banner names a non-existent `_SIM_SOC_BAND_DRAIN_SCENARIOS`
  ("two mirrors" → three, alpha legs included); `HIL_PLANT.md` ~2882 "both mirrors"; `gen`'s drain
  tuple is an import-time snapshot while mpc/walk resolve at use; `gen_dp_ems_table.py` prints a
  full summary at exit 2 when refusing to overwrite; the known wall-clock flakes
  (`test_the_search_width_reads_no_clock`, `test_transition_roll_slices_and_completes`).
- **`share_cut_census` is a spread (118–157) not a pin**; TP0053's ERROR latch is bimodal (quote the
  UV_BUS first-detection instant, stable to 0.4 ms).
- **Campaign F findings (2026-09-03 08:19):** F1 MED `governor_model`'s MDAC code mapping is exact only
  at commanded share 0.84 (`mdac_fc` +1.3 % at 0.84 loaded, +3.1 % at 0.50, +5.0 % at 0.40, +10.4 % at
  0.20; `mdac_bt` −2.2 to −3.4 %) while delivered currents match to 0.07 % — re-derive across the band,
  then re-pin sweep region 12 (`mdac_fc` 5377–5378 / `mdac_bt` 5259–5260) and add pins to region 10.
  F2 MED the single-source surrogate credits the 0/1 stage at its command instant; the board defers the
  cut 24–45 ms on loaded commits (fires at 0.44–0.50 A) — model the deferral before the leg ranks
  anything; keep its h2 band informational. F3 MED the 1.5 s bridge at region 10 → 11 covers the drive
  rail but not the settling tail (total 1.61 → 1.81 A still climbing at the share step; peak 1.2586 A,
  9.4 % margin) — extend to ~2.5 s there or record the margin. F4 LOW `ceiling_step_settling` measures
  Pi-cadence phase (aux rise 3.3–15.8 ms after the command); re-reference to the command instant
  (40.9 / 38.3 ms). F5 LOW `CANDIDATE_COST_MS_NOMINAL` 0.0360 under-reads on two legs (seen
  0.0268–0.0380): per-leg cost or stop re-tuning. F6 LOW `ems-mpc-single` ends Run with FC_BUS open
  (document). F8 LOW `ems-sdp-braking` h2 +1.0 % on an unchanged stimulus (eq-H2 +0.15 %). F10 LOW
  L_chg spread 2.1 % over four campaigns (0.3313 / 0.3318 / 0.3333 / 0.3384).

## 7c. Opened 2026-09-03 (low-current share stability exploration)

Source: `docs/modeling/low_current_share_stability_20260903.md` (census, noise measurements, offset
estimates, ranked options). Framing: on campaign F the share loop is in open-loop HOLD for 45 % of
`ems-sdp` and 66 % of `ems-ftp75-*`, and on every SDP/DP leg the minority clip binds for the whole
closed-loop remainder (the policies command band edges), so the delivered minority is pinned at
`SHARE_MINORITY_I_MIN_A` and the commanded share is never tracked. Stronger current filtering cannot
lower the floor (measured loop-attenuated minority jitter 4–10 mA rms against a bench-bracketed
conduction floor of (0.245, 0.29] A; the noise above 0.4 A is common-mode load ripple that cancels in
the ratio). The three firmware items below raise the light-load conduction margin instead. **All
three are bench-only validation: the HIL plant has no PFM / light-load converter model.**

- **FIRMWARE: load-scheduled droop scale `k_d(I_tot)`.** Today `K_DROOP` = 0.30 Ω is fixed by
  `g = K_DROOP/(RE_MAX·r) ≤ 1` at the band edge, so the droop authority `k_d·I_tot` collapses with
  load (0.18 V at 0.6 A, design scale). In closed loop the minority clip already confines r to
  `[r_lo, 1−r_lo]`, `r_lo = I_min/I_tot_filt`, so `k_d = RE_MAX·r_lo·(safety factor)` keeps `g ≤ 1`
  by construction and makes the FC/BT conduction margin `RE_MAX·I_min/(1−r) ± dV0` independent of
  load (0.60 V design scale, ~0.13 V at the measured 4× weaker droop) — 3.4× more margin at 0.6 A,
  1.0× at 2 A. Static plant gain stays exactly 1 for any k_d, so the Youla-H controller is untouched;
  only the disturbance term shrinks. Design points: closed-loop only (HOLD writes nothing;
  FEEDFORWARD can carry a raw 0.15 setpoint at 0.3 A where a scheduled k_d would push g past 1);
  k_d and r slewed under the same limiter/hysteresis so they never combine to g > 1 during a slew,
  the deferred-cut band-edge clip, or the open→closed reseed (recompute codes from `droopSlew_prev`
  under the new k_d); bus sag becomes a constant 0.6 V (design) below 2 A — harmless against
  `LIMIT_V_BUS_MIN` but it moves the simple engine's bus law, `governor_model.py`, the loss-map bound,
  the fw v26 clamp arithmetic in the tools, and every h2 anchor (hi-fi engine follows the mirrored
  MDAC codes automatically). BLG/HIL observability: log the active k_d (BLG header carries only the
  fixed `K_DROOP_x1000`). Prerequisite: the two-axis per-channel dropout-boundary sweep (§3) to size
  how far the floor moves; informed by the unexplained 4× droop gap (`HIL_PLANT.md` §4.2).
- **FIRMWARE: margin-referred governor (replace the current floor with a conduction-margin floor).**
  Whitepaper conclusion 11: no constant-current floor separates stable from cycling (BT minority
  drops at 0.55–1.04 A while FC holds 0.63 A; 27 mV of bus separates WP0100 from WP0095). In closed
  loop `d_hat = sp − r` is the standing offset, `dV0_hat = d_hat·k_d·I_tot/(r(1−r))`, and the
  minority margin `M = k_d·I_tot/(1−r) + dV0_hat` (mirror for BT). Clip the reference to keep
  `M ≥ M_floor` (a voltage from the bench sweep) instead of `I_min ≥ 0.30 A`; in current terms that
  is `M_floor·r(1−r)/k_d`, larger at the band edges, smaller when the offset favours the minority.
  Bench offset estimates already show the asymmetry: near zero FC-minority, +0.20 A at 1 A rising to
  +0.42 A at 2 A BT-minority (droop-scale-mismatch signature, ρ = 0.9434). Closed-loop only (needs
  `d_hat`); does not add authority, so pair with the scheduled k_d. **Step 0, no firmware:** compute
  `d_hat` and `M` from existing BLG records (`share_sp`, `gFC`, `gBT`, currents) on the dropout runs
  (TP0016, WP0073, WP0100) and their clean neighbours (TP0017, WP0071, WP0095) and check that one
  `M_floor` separates them — if not, the hypothesis is wrong and only the two-axis sweep remains.
- **FIRMWARE: apply the governor clip on the open-loop FEEDFORWARD path.** Whitepaper items 16–17:
  both fw v6 ladder dropouts (TP0105 at r_min, TP0115 at r_max; 5.9 ms both-dark, bus 12.19 V)
  occurred at the open→closed handover, where the reference jumps from the raw fed-forward setpoint
  to the floor-clipped one — a 0.42 swing in commanded share at 0.6 A total, which opens both
  channels however slowly it is slewed (fw v6 slewed the rate; the exposure is the magnitude).
  Clipping the feedforward against the same filtered total makes the handover continuous. Note the
  fw v5 review argument against clipping feedforward (no loop to limit-cycle; honour the operator's
  setpoint) — the clip must be the relaxing form `[I_min/I_tot_filt, 1 − I_min/I_tot_filt]` with the
  0.5 ceiling, never the collapse-to-0.5 that ignited TP0053. Prerequisite for any lowering of the
  closed-loop gate; small on its own. Cheapest of the three; can ship first.

Added to §3 (bench): the two-axis per-channel dropout-boundary sweep (setpoint at fixed I_max, I_max
at fixed setpoint, both minority directions, and a repeat of WP0073/WP0100 on the pack instead of
the 1.0–1.35 Ω bench battery supply) — the whitepaper's standing recommendation, previously absent
from this queue.

## 7d. Opened 2026-09-08 (host-native encoder-defect harness — implementation brief) — DONE `a683e25` (41 pytest + 43 harness checks, first 2676-run sweep, docs/encoder_defect_harness.md); the run_tests hook DONE; the 180 deg case now asserts the fw v28 rev 2 auto-flip (`ded47f3`); FINDING for the operator: a 180 deg phase error = sign-inverted reading, drive railed, NO fault (no encoder-sign plausibility check in detectFaults())

Source: operator question 2026-09-08 ("is it feasible to add a simulation of the encoder wheel to
the hi-fi HIL engine, with phase offset, +1/−1/+1 teeth, and missing teeth"). **Feasibility
verdict:** yes, but NOT as a plant extension. Under `HIL_SIM` the 40 B injection frame carries
`v_actual` in m/s at offset 30 and `updateSensors()` SKIPS `updateWheelSpeed()`, so `doEncoderA()`,
`doEncoderB()`, the A-rising period estimator, the reject gates (`ENC_PERIOD_MIN_US` 200 µs,
`ENC_PERIOD_LO_FRAC` 0.625) and the halving / doubling basins never execute on a HIL board. A
plant-side wheel model would produce a number the firmware copies. Edges must reach the ISRs, and
the cheapest substrate that already does this is the host-native mock (`g_pin_value[ENC_A/ENC_B]`,
`g_mock_micros`; ~20 existing tests drive the real ISRs through it). **Ruling recorded 2026-09-08:**
the harness is a SEPARATE `test/` target, never a `run_hil_suite.py` scenario (every HIL leg is a
board reading; this one touches no board). It runs faster than real time (event-driven; estimate
~500×; the 3961-check production suite takes 0.3 s), so run speed is not a constraint.

**Deliverables (in order):**

1. **`tools/encoder_edge_script.py` — edge-list generator.** Input: a TRUE surface-velocity
   trajectory `v(t)` produced by stepping the plant's mechanical law
   `m_eff·dv/dt = K_F·I_cmd − sign(v)·F_c − b_eff·v` at 1 kHz from an `I_cmd` stream (constants
   IMPORTED from `tools/hil_plant_sim.py`: `M_EFF` 3.5, `K_F` 0.7538, `F_COULOMB` 2.00, `B_EFF`
   0.534 — never re-typed; the `SOC_BAND_DRAIN_SCENARIOS` hand-mirror defect of 2026-09-01 is the
   precedent). Geometry from the firmware: `ENCODER_SLOTS_PER_REV` 90, `FLYWHEEL_RADIUS_M` 0.0762,
   pitch 2π·0.0762/90 = 5.3198 mm; the generator asserts these against the `.ino` `#define`s at
   run time (grep-and-compare, same pattern as the pinmap audit). Output: a sorted list of
   `(t_us, channel, level)` CHANGE events for A and B, plus a JSON defect manifest. Nominal wheel:
   B lags A by exactly 90° electrical (one quarter pitch), 50 % duty on both.
   **Defect scripts** (each parameterised, composable, applied to the IDEAL edge list before
   emission so the manifest names every altered edge by slot index and time):
   - `phase_offset_deg` — B channel shifted from 90° (sweep 0–180; the A-rising estimator is
     blind to it, the quadrature direction decode is not: near 0°/180° direction flips clear
     `encPhaseEwma` — safety review MED-1 — and force holds / zeros on `v_actual`).
   - `bounce_slots` — a `+1/−1/+1` tooth: at slot k the A channel produces an extra
     rising/falling/rising triple inside one pitch, with a settable sub-pitch spacing (sweep
     50 µs – 0.6 T so the 200 µs floor and the 0.625×ref gate are both crossed). Documented escape:
     the T/2 doubling basin.
   - `missing_slots` — slot k (or a run k..k+n) deleted from BOTH channels; produces a 2T A-rising
     period. Documented failure: the absorbing halving basin (`v_actual` reads exactly half).
   - `edge_jitter_us` — zero-mean uniform jitter on every edge (the 2.2 kΩ front end's threshold
     noise; ML0140–145 measured missed AND spurious A-edges with this pull-up fitted).
   - `dropout_window` — a span with no edges at all (the reading-age bound, `ENC_PERIOD_REF_MAX_US`
     200 ms path).
   Defects are positioned by slot index, not time, so a sweep over "where in the cycle" is a sweep
   over k; the generator also accepts a seed for the jitter and records it in the manifest.

2. **`test/encoder_defect_harness.cpp` — fourth `test/` target `run_tests_encoder`.** Built with
   the production flags (`-DBENCH_TEST=0 -DHIL_SIM=0` — the ONLY build whose ISR / estimator path
   runs on the bench board) and `-I../controller_design_MIMO` (Youla drive-controller vectors), same
   MSYS2 UCRT64 g++ invocation and Makefile pattern as the three existing targets. Loop per run:
   walk the edge list; for each 1 ms control tick, apply every edge whose `t_us` falls inside the
   tick (set `g_mock_micros` to the edge's own time, set `g_pin_value[...]`, call `doEncoderA()` /
   `doEncoderB()`, in order), then set `g_mock_micros` to the tick boundary and run
   `updateWheelSpeed()`, `motorControl()` and the plant step UNMODIFIED — the harness only supplies
   edges and reads `I_cmd` back into the mechanical law, so the drive loop is CLOSED on the
   firmware's own speed estimate (this is what the HIL rig cannot do). `powerBalance()` /
   `chargingControl()` are out of scope (motor axis only; no share stimulus).
   Two modes: (a) **regression** — the nominal wheel plus one canonical instance of each defect at a
   fixed (k, speed), pass/fail with `check()` counts, ADDED TO `run_tests` so an estimator change
   cannot pass unnoticed; (b) **sweep** — defect × slot-index × cruise-speed grid (e.g. 4 defects ×
   30 k × 6 speeds, 60 s each: ~70 s of host time at the 500× estimate), report-only, writes one
   row per run to a CSV (`v_true`, `v_actual` error RMS / max / final basin ratio, hold count,
   reset count, `encPhaseEwma` clears, direction flips, drive-PI saturation ticks, max `I_cmd`) and
   dumps the full per-tick trace ONLY for runs whose basin ratio ends outside [0.95, 1.05] (printing
   per tick for every run is the only thing that would make it slow).

3. **Signatures to pin (from the firmware's own documentation, so a test names what it expects):**
   - nominal wheel: `v_actual` tracks `v_true` within the fw v18 estimator delay model
     (`ENC_PERIOD_AVG_N` 2) — the harness re-measures the delay and pins it;
   - single missing slot at cruise: the low-side gate rejects the 2T period and the reading HOLDS
     (fw v17 hold-until-corroborated); a RUN of n missing slots crosses the re-seed count
     (`ENC_PERIOD_REF_SEED_N` 2) and the harness reports the n at which the halving basin becomes
     absorbing — that n is the deliverable, unknown today;
   - bounce spacing < 200 µs: rejected by the floor, no effect; spacing between 200 µs and 0.625 T:
     the gate's reference tracks it and the harness reports whether the T/2 basin is entered and
     whether the direction-change clear ever un-sticks it;
   - phase offset: the offset at which direction flips begin, and the resulting hold duty.
   Where the firmware's documented behaviour and the measured harness behaviour DISAGREE, the
   harness result is a FINDING against the firmware, logged under `docs/` (encoder analysis lineage:
   fw v12 ML0140–145, fw v15 period estimator, fw v17 holds, fw v18 90-slot) — not a widened band.

4. **Not-to-change / standalone-ness:** ISRs, `updateWheelSpeed()`, `encoderVelReset()` and the
   drive controller are NOT edited (the "What NOT to change" list; a tap of the fw v15/v17 class
   needs a separate ruling). If the harness needs a reset seam, use the existing `enc_reset()`
   pattern in `test/test_main.cpp`. No wire-protocol change (the 40 B injection frame, the 18 B
   observation frame and the v4 / 58 B telemetry are untouched). Results folder:
   `logs/encoder_harness/` (own folder; NOT `HIL Results/`), gitignored like the campaign ledgers,
   with the CSV + manifests committed only when a finding is written up.

5. **Follow-on (separate item, not this round):** the physical pulse generator on pins 14/15 (a
   spare Teensy/Arduino replaying an edge script, or streaming edges from the plant's `v` at 1 kHz;
   ≤ ~564 Hz A-channel at 3 m/s) plus a `#if HIL_SIM` switch that stops overriding `v_actual` from
   the frame. THAT run is a board reading and belongs in `run_hil_suite.py`; the harness names
   which edge scripts are worth replaying there. Interrupt latency and GPIO jitter are covered only
   by the physical route — the harness models neither.

**Process:** `orchestrated-feature` (direct) — the Python tool and the C++ target are separable
implementer tasks; the test-writer covers the generator (edge-list invariants: monotone `t_us`,
exact quarter-pitch lag on the nominal wheel, manifest names every altered edge) and the regression
mode; the review pair is correctness / test-fidelity (does the harness call the ISRs in the same
order and at the same micros a real CHANGE interrupt would) and data-integrity (constants imported,
geometry asserted against the `.ino`). Then `self-review`, then all FOUR targets green
(3961 / 175 / 4443 + the new one). Estimated one session.

## Shipped 2026-09-02 (overnight)

- **Ag105 charge efficiency `ETA_CHG` = 0.88 in both HIL engines** (chord-conductance stamp, 8.0 V
  floor, output-referred regen cap, seventh power column `p_chg_loss_w`, `constants_hash`
  `6a88d04ba8a36e61`), with the physics change record and six-item reversal path in
  `docs/HIL_PLANT.md` §4.6.1–4.6.2.
- **η-era charger accounting through DP, SDP, walk and database** — `tools/charger_power.py` (absent
  `eta_chg` means the old era), tables regenerated, backward pass corrected, fingerprint reachability
  restored.
- **`sdp_policy_v4.json`** (α 0.11832639757736393, `lever` mode, 0 charge cells, policy sha
  `8ca7dcee…`), sdp-v3 demoted, `ems-sdp` and `ems-ftp75-sdp` rebound; the η-era 41-point α sweep with
  both boundaries bisected and three live picks.
- **`tools/mpc_ems.py`** (governor-aware receding-horizon EMS, deterministic and stochastic) with its
  design document, adjudication, fix round and full registration; Gate 1 recorded as FAILING.
- **Expectation re-derivation** across the η era (WP-1C) and **`campaign_meta.json`** campaign
  wall-clock metadata in every report folder.
- **Campaign B (`hil_report_20260902_011926`)** — 66 planned, 65 executed + `drive` SKIP, wall
  1:16:45; suite tally 58/66, **corrected to 65 of 65 executed runs correct, zero board defects**;
  replay half 27/27 real, 0 untagged-vacuous. It validated the η = 0.88 model on every independently
  measurable axis, produced the **first live η-era lever measurement** (L_chg 0.33214 /
  L_share 0.41688 SoC/g, ratio 0.797 — the projected inversion refuted, `sdp_policy_v4` the eq-H2
  winner on the board) and the **first live governor-aware MPC** (ties sdp-v4 at 0.96212× on the
  61 s cycle; closed-loop prediction exact, all error open-loop), and it exposed the **double era
  boundary** against campaign 151156 (charger AND converter asymmetry), which breaks the `ems-sdp`
  8 ppm, `scp-inrush` `i_cut` and `comm-loss` symmetric-re-close records.
- **`docs/HIL_PLANT.md` adversarial review, run 001** (`docs/reviews/hil-plant/run-001-2026-09-02.md`
  + `docs/reviews/hil-plant/ledger.md`): three major (F1 byte-15 fiat mirror, F2 the misattributed
  regen "leak", F4 the open-loop feedforward submode), five minor, one nit, `PLANT-R1-N4` open.
- **Campaign-B fix rounds** — docs `7026e3b`, tooling `6c28dd2` (§0a lists the scoring-semantics
  changes); suites at that point 1795 stdlib / 1997 numpy green.
- **Campaign C (`hil_report_20260902_041414`)** — 66 planned, 65 executed + `drive` SKIP, wall 1:22:26;
  suite tally 65/66, **corrected to 65 of 65 executed runs correct, zero board defects**; the single
  FAIL is the settling-hold defect the fix-round review predicted. It validated every campaign-B fix on
  the board, took the **second η-era lever reading** (stable to 0.114 %), certified the **MPC frontier**
  (0.9606× / 1.0007×, tying sdp-v4), re-pinned the **asymmetry-era anchors** (`scp` `i_cut` bit-exact to
  16 digits), and corrected three standing records: the h2 repeatability floor to **~50 ppm** (the 8 ppm
  and 0.79 ppm records retired), the replay census baseline to **118/6/2/0.5722 A**, and the
  teardown-lead band to **0.04–0.55 ms**. New finding: the MPC budget expires on 57.4 % of
  `ems-mpc-cross`'s decisions once the candidate cap is lifted.
- **Post-campaign fix round `5f1cfed`** (§0a) — the settling hold, the finalize test, the substep
  warning, the guarded teardown, the informational `mpc_h2` with a per-scenario budget.
- Commits `dec059b`, `390f554`, `e653e90`, `6702920`, `d70a620`, `a932f83`, `887933f` (campaign B
  launched from it), `71fecb6`, `c4abc39`, `7026e3b`, `6c28dd2` (campaign C launched from it),
  `76253ee`, `faecc58`, `b28f501`, `5f1cfed`, plus this close-out — 16 on main.
- **Suites at close:** `.venv_hil` 1810 passed / 61 skipped; miniforge 2209 passed / 1 skipped (16
  suites). Firmware untouched — fw v25's 3842 / 175 / 4324 stand.

## Shipped 2026-09-01f (follow-on round)

- `hil_power_balance` figure in every HIL report + six append-only power columns (both engines);
  backfilled across all 14 report folders (legacy CSVs: source powers only).
- Refined α-sweep: both transition points bisected (0.111000 / 0.239250 = the admission-window ends),
  20 refined artifacts (idx 21–40), walk-synthesized plots per point, h2-vs-α step figures, doc §10–11.
- Found: the hi-fi Ag105 was a 1:1 current-transfer element — the charger-efficiency finding this
  round's WP-1A resolves.

## Shipped 2026-09-01e

- Campaign hil_report_20260901_151156 (fw v25 first campaign): T1/T2/T3 validated; 3 false FAILs fixed.
- tools/governor_model.py + tools/ems_walk.py (+ tests); tools/dp_results_db.py + tools/dp_db/ +
  matched-DP post-pass; tools/sdp_alpha_sweep.py + 21 artifacts; tools/benchlog_analysis/
  asymmetry_fit.py + docs/modeling/converter_asymmetry_20260901.md; the Pi bridge audit pair;
  preload removal (B1); asymmetry-in-plant + simple-mode sign fix + campaign fix queue (C1).

## 0c. Operator rulings 2026-09-03 (morning review of the overnight round)

1. **MPC share-step rule: RULED IN.** Add to the MPC stage model: no upward share step in the same
   decision as an upward demand step above 1.647 A two-source (design record §8.6).
2. **Joint-transient clamp leg: BUILD** the 1.65 A version (§8.6.5) with a stepped aux-load branch.
3. **α re-solve: APPROVED** on the measured levers (five readings, α ≈ 0.134); supersedes "α stays v4".
4. **ftp75c socband reference: charge-free ACCEPTED**; no constraints on leaving charge mode.
5. **`dp_ems_table_ems-ftp75-5050.csv`: DELETE** (stale, unused).
6. **MDAC-code finding re-explained:** not quantization (< 0.25 %). `governor_model`'s static law
   carries the dV0 term of the asymmetry fit but not its droop-slope term (`ASYM_DROOP_SCALE_FC`
   0.9434, "two parameters of one fit"), so the model's converged ratio (0.491 at share 0.50) differs
   from the board's (0.476 from its codes); the loop delivers the share exactly and the codes carry
   the correction. Fix: add the slope term to `_delivered_share()` / `_ratio_for_delivered()`.
7. **Sequencing: the HIL_PLANT.md physics review (run 002) runs BEFORE items 1–6.**
8. **HIL_PLANT.md physics review run 002 DONE** (`docs/reviews/hil-plant/run-002-2026-09-03.md`,
   ledger updated): 1 major (PLANT-R2-F3, the governor map's split law - the same mechanism as
   item 6 plus the 0.033 Ohm series floor), 7 minor, 6 adjacent; no safety or campaign verdict
   changes. Fix order per the adjudication: F3/N1/N2 (model + tests + re-walk + re-pin) -> docs
   (F2, F5, F4, F7, F6, F1, F8, N3, N5, N6) -> the N9 bench test -> the dark-node decay capture.
9. **Run-002 fix round SHIPPED (2026-09-03):** F3/N1/N2 (full split law, re-walk, re-pins, Gate 1
   mpc-det now PASSES at 0.000740), all document corrections, the N9 firmware test. Opened: (a) the
   split law under `--droop measured` needs a ruling (scale the pair `r_series_ohm = R_f/s`,
   `dv0_v = dV0/s` inside a governor-specific resolver, or give `GovernorModel` a realized k_d; a
   runtime warning ships meanwhile; design note section 6); (b) the MPPT regen exclusion is a level
   test at the 50 Hz tick (a sub-tick regen pulse could fold a sample) and the abandoned window's
   minimum stays visible in the State-98 diagnostics — both recorded, no firmware change proposed;
   (c) `test_the_committed_plan_is_insensitive_to_the_projection` joins the wall-clock-sensitive
   list; (d) the first campaign after this change is a new baseline for `mpc_share_pred_err`.
10. **Rulings round SHIPPED (2026-09-03, `88f8e2d`, `96800c7`):** items 1, 2, 4, 5 as ruled; item 3
    shipped as `sdp_policy_v5` NON-frontier. **Two rulings now open:** (a) **the α re-solve admits
    charging** (558 cells) because the stage cost bills η_chg 0.88 against a measured 0.801 round trip —
    solve at `--eta-chg 0.801173` (0 charge cells, era banner) or accept charge admission; until ruled,
    v4 stays the frontier; (b) the split law under `--droop measured` (design note §6). Watch on the
    first campaign: `fw26-clamp-joint`'s 1.36 A bound is 0.4 % above a never-measured walk (a miss
    latches OC_FC); the guard's `share_step_guard_decisions` must read 0; `mpc_share_pred_err` is a new
    baseline. Follow-ups: tighten the joint leg's 8 % MDAC band to the sweep's 2 % after its first
    campaign; Gate 1 single-source-aware; the F2/F3/F4 campaign-F items still open in §7b.
11. **N8 settled (2026-09-03):** the post-latch `V_bus` 0.0000 is engine behaviour — the unconditional
    0.15 A `I_AUX_A` sink on the hi-fi bus node's 35 uF (4.29 V per tick), not report-side gating.
    Doc-only fix shipped. Opened: (a) ruling — give `I_AUX_A` a dropout floor below ~1 V (ends the
    `neg_clamp` churn; cannot move a loaded anchor); (b) plumb `neg_clamp_count` into the sidecar.
12. **RULING NEEDED — `I_AUX_A` 0.15 A is unsupported by the bench record (2026-09-03):** 98 standstill
    windows across 213 bench logs (fw v3–v19, 167 905 samples, I_cmd 0, V_bus 15.90–15.94 V = the
    documented no-load point) give I_fc + I_batt = 0.0150 ± 0.0065 A raw, which is inside the INA zero
    offset (0.0199 A median) and under two LSB (8.06 mA); the INA shunts sit on the boost OUTPUT side, so
    the sum IS the bus housekeeping draw (no ETA_BOOST conversion). Best estimate <= 0.03 A, likely near
    zero; caveats: no window had the Ag105 path open or a hold longer than 3.65 s, and the BLG carries no
    MOT_PWR bit (VESC state inferred). Consequences of a change: the idle source total on the drive cycles
    (0.15 A puts FTP-75's idle third under the 0.60 A gate), the DP fingerprint (`I_AUX_A` is a key), every
    h2 anchor (~0.15 A x 16 V over the idle segments), the N8 dark-bus collapse rate, and the walks' HOLD
    fractions. A new plant era; do not change it inside a campaign. Options: (a) keep 0.15 A as a
    conservative placeholder and state it; (b) set it from the bench evidence (0.02–0.03 A) and re-pin;
    (c) bench-measure a multi-second standstill with the charger path open when the bench is back.
    **RULED (2026-09-03, operator): `I_AUX_A` -> 0.09 A at the next era boundary.** Basis: the Teensy runs
    from the battery's 5 V regulator (not on the bus); the VESC draws ~1.2 W from the bus (0.075 A at
    15.9 V); the INA253s, RT1987s and MDAC op-amps ride the bus chain; the logged 0.015 A windows had the
    VESC unpowered. Scheduling: the boundary is the fw v27 flash / campaign G — apply the constant in the
    same tools round as the v27 mirror, re-walk every anchor BEFORE the campaign (walk-predicted deltas
    attribute the move, as in the bleed era), mark the matched-DP records stale (`I_AUX_A` is a fingerprint
    key; re-solve the long ones off-campaign), and never change it inside a campaign.
13. **Section 7c Step 0 DONE — the margin-referred governor (4.2) is REFUTED on the bench record**
    (`docs/modeling/low_current_share_stability_step0_20260903.md`, `tools/probes/probe_share_margin_step0.py`).
    No single M_floor separates the six recorded first passages from their clean neighbours under design,
    measured (x0.2117) or split-law droop (overlap factors 2.3 FC / 5.2 BT / 5.2–5.4 pooled vs 1.75 / 5.40 /
    7.59 for the raw minority current). Reason: M_minority = (R_FC + R_BT)·I_minority exactly (residual
    < 1e-15 V over 88 781 records), a <= 1.96x rescaling; realization (ii) is a pure scalar of (i), so the 4x
    droop gap cannot change the verdict. The online estimator d_hat = sp − r is identically zero at every
    quasi-static rail failure (r pinned on the rail the setpoint sits on) — it returns nothing in the regime
    it was proposed for. Restated figures: TP0016 lost the FC at 1.354 A total (commanded minority 0.203 A,
    delivered 0.169 A), not 0.245 A at 1.63 A; WP0100's boundary BT current is 0.733 A, not 0.69 A. Only two
    quasi-static passages exist (both FC); the BT-direction asymmetry rests entirely on slew-driven events
    (11–16 /s of ratio slew, 66–94 % of the limiter ceiling) on the soft bench source. Bench: the two-axis
    sweep must hold |dr/dt| < 1 /s for the static boundary and repeat at the ceiling for the dynamic one; a
    quasi-static BT-minority passage on the pack does not exist yet; the discriminating variable is outside
    the (I_minority, M) pair (RT1987 per-channel conduction state, TPS61288 light-load mode — not in the BLG).
    Items 4.1 (scheduled k_d) and 4.4 (feedforward clip) stand; 4.2 is closed unless a new variable is logged.
14. **The 4x droop loss is LOCALIZED (2026-09-03, desk analysis, `docs/modeling/droop_authority_gap_20260903.md`):**
    the 39 per-channel single-source slope fits in `asymmetry_fit_20260901/fit_summary.json` (g 0.184–0.441)
    give R/g = 0.455 ± 0.006 (median 0.448) against the designed 2.0136 g, a 4.0–4.7x deficit that is
    near-proportional in g and identical on both channels; their no-load intercepts 15.912–15.934 V match
    the designed V_0 15.907 V to 0.12 %, which confirms R_D1 215k, R_D2, R_inj and the 4.011 injection
    ratio. The deficit therefore sits in the **AD5443 -> OPA197 block: realized K_sns·A_v 0.113–0.133 V/A
    against 0.502 designed** (the op-amp stage delivers 1.1–1.3 V/V where 5.02 was designed). The
    INA253 A1/A3 hypothesis is REFUTED twice (every 0.633 derivation already uses 0.1 V/A; the bus droop
    referred to the reported current is invariant to the sense gain). The AD5443 is wired in
    voltage-switching mode, for which the datasheet prints no transfer equation and characterizes nothing
    below V_REF 2 V (this ladder runs at 3–62 mV): `g = D/4096` is an assumption. Two mechanisms remain:
    M-A the op-amp gain is not 5.02 (unity buffer -> 0.401 ohm; a 4.02k-for-40.2k slip on ROP2 -> 0.562 ohm;
    the fits sit between) or M-B the ladder tap is short by ~3.8. **Bench (when available):** one source
    live, 1.000 A, g 0.500; DMM `FC-CURR` (INA out), net N$7 (MDAC.VREF / OP.+IN) and `VDROOP` (OP.OUT):
    design 0.1000 / 0.0500 / 0.2510 V; A_v = 1 -> 0.0500 at VDROOP; ROP2 slip -> 0.0701; tap short ->
    0.0132 / 0.0663; also ohm ROP1/ROP2 unpowered on both channels. Implication: `K_sns` 0.1 is right;
    `RE_MAX` 2.014 and `K_DROOP` 0.30 are design intent that the board realizes at 0.45–0.54 / 0.068–0.080;
    the loop's integral action absorbs it (cost: authority, not share accuracy) — the §7c scheduled-k_d
    lever is therefore ~4x smaller than the note's Table 4 until the block is fixed, and fixing the block
    (a resistor) is the cheaper route to the same authority.
