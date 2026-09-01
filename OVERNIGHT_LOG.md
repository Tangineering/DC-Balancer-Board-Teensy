# Overnight autonomous session log — 2026-08-30/31

Operator stepped away ~22:30 2026-08-30 with instructions: land the command-replay/suite-fix
round once reviews are clean, commit/push to main, then run 1-5 rounds of run_hil_suite.py
(all scenarios) with hil-agent-analysis on each, making orchestrated fixes between rounds
autonomously. Fixes that would normally need operator approval are made anyway for tonight
but LOGGED HERE so the operator can review them tomorrow and choose which commit to resume
from. Commits are in logical chunks; each entry names its commit.

Suite invocation (from campaign 214819 meta): `--teensy-ip 192.168.1.50 --port 5001`,
electrical_pref hifi, settle 5.0 s. Board: fw v23, HIL build (operator's local
BENCH_TEST 0 / HIL_SIM 1 flip — NEVER committed). Dashboard OFF (no tty in my shell).

## Decisions that would normally need operator approval

1. **ML0203 opted into command replay with a FULL-RANGE recorded share_sp (0.000-1.000).**
   Replaying it drives updateShareSetpointCutoff() in both directions (channel cut +
   share-loop freeze). Kept because that is correct firmware behaviour on a genuinely
   recorded setpoint and none of its checks reads switch_state — but it is a fault-latch
   entry gaining a second actuating stimulus. Reverse by setting its
   `replay_commands: False` in tools/hil_replay_suite.py if you want the OC_FC stimulus
   pure. (Documented in the entry comment + decision rules.)
2. **steady/step-load/drive left OUT of FAULT_EXPECTATIONS** (reviewer suggested positive
   assertions): adding any entry costs the --pi-live PI_TIMEOUT excusal and swaps
   no_unexpected_fault for fault_allow_only — judged not worth it for scenarios with no
   state consequence. bringup DID get survive_to {t:4.0, states {1,2}}.
3. **Scenario durations trimmed without operator sign-off on the specific numbers**
   (user asked for the trim in general): steady 10, step-load 10, sag 9, comm-loss 12,
   charge-cruise 15, charge-fault 25, ems-drive-cycle 58, handoff-sag 24, bringup 8,
   scp-inrush 6; drive/charge-regen kept; soc-depletion 400 s + soc0 0.20 (A1).
   Cross-campaign caveat: baseline-statistics windows shrink vs campaigns 203006/214819.

4. **Round-1 fix round run with a LIGHTENED pipeline** (single implementer + test
   reconciliation + orchestrator diff review, no fresh two-lens pass): all nine items
   originate FROM tonight's two-lens review + audit findings and are LOW/MED tooling
   changes. Deviation from the full orchestrated-feature pipeline, judged proportionate.
5. **FU3 tightens drive_loop_stepped thresholds from round-1 measured data** — future
   replay runs FAIL if the command path degrades below ~half of tonight's activity.
   Deliberate ratchet; loosen per entry if a legitimate stimulus change lowers activity.
6. **FU4 deferred** (Idle→Run setpoint-arrival synthetic entry — new stimulus design,
   your call).
7. **[SUPERSEDED by #8 — re-margin measured INFEASIBLE; nothing was retired.]**
   Original plan: scp-inrush re-margin retiring the 6.290 A i_cut pin.
   Round 2 FAILed events_require_scp_cut with 0 cut events: the sim's SCP cut and the
   firmware's OC teardown are 0–1 ticks apart, decided by the observation round-trip
   (L=2 in round 1/campaign 2, L=1 in round 2 — the 0.076% "repeat" was two draws of
   the same coin). Plant trace bit-identical; board correct both rounds; classified
   scenario knife-edge. Fix applied tonight: SCP_INRUSH_MOT_LOAD_A raised so the cut
   fires inside the admission tick's blanking window (phase-independent), i_cut band
   re-derived from a headless hil_electrical bench, tripwire wording fixed. The old
   6.290 A figure is retired FOR MARGIN, NOT DRIFT — the 5.0 A stimulus + 6.0-6.6 band
   can be restored by reverting the scenario constant if you prefer the knife-edge
   documented instead.
8. **scp-inrush made a TWO-OUTCOME expectation instead** (the root-causer's fallback,
   adopted after the implementer's headless bench proved the re-margin infeasible: a
   tick-S cut needs ~12.70 A load = 1.49× RT_I_FOLD_HIGH 8.5 A — a hard short, not the
   SCP-margin case the scenario exists for; the load knob cannot fix the phase race).
   Outcome A (fold won, L=2): exactly 1 scp_cut with i_cut in 6.0–6.6. Outcome B
   (firmware won, L=1): 0 cuts AND a MOT_PWR sw_ring in the fold-approach band AND
   OC_FC latched — explicitly labeled WEAKER evidence (fold approached, not fired).
   Both are the same correct physics in the two legal orderings; the check no longer
   scores a coin flip. THE DETERMINISTIC-FOLD PATH REMAINS OPEN FOR YOU: a stimulus
   TIMING redesign (close MOT_PWR into an already-loaded node so the fold engages well
   before any firmware reaction) — a scenario redesign I did not attempt autonomously.
   Also found: the 5.0 A stimulus never had its claimed 15% fold margin (bench
   threshold ~5.53 A; the real path is a few % more aggressive than the bench —
   single-digit margin either way IS the fragility, now documented in place).

## Operator review (2026-08-31 morning)

**ALL DECISIONS RATIFIED** (operator, after walkthrough). No reverts. Follow-ups queued as
the next orchestrated rounds: (a) the scp deterministic-fold stimulus TIMING redesign
(decision #8's open item) + FU4 (Idle→Run setpoint-arrival synthetic entry, decision #6);
(b) DP-informed EMS strategies + H2 metric; (c) scenario expansion (Y-profile EMS ×4,
FTP75, MPPT tracking, +3). This log is now historical record; resume-point section moot.

## Commit ledger

- `9d17d23` — adopted the parallel session's HIL report analysis pipeline (pre-round).
- `817295d` — the feature round: command replay, soc-depletion gate (A1), replay
  metrics (A5), duration trims. All reviews clean after fix round; 674+25/718 tests.
- **Round 1 (hil_report_20260831_000518): 39/39 PASS, all verified for the right
  reason.** TRCB fix CONFIRMED on hardware; command replay proven at scale 1.00;
  soc-depletion redesign validated; B1 (INA253 side) raised and refuted same night.
  Ledger + summary in the report folder (not committed — HIL Results/ is gitignored).
- `9612369` — round-1 fix round: share_loop_actuated, drive_min_frac ratchet,
  fault_first_t_whole_run, switch_transitions, i_cut band, comment cites.
- **Round 2 (hil_report_20260831_010145): 38/39.** The one FAIL (scp-inrush, 0 cut
  events) root-caused as the L=1/L=2 observation-round-trip knife-edge — board
  bit-identical and correct in both orderings; everything else REPEAT CLEAN with
  multiple exact repeats.
- `82c8f75` — scp two-outcome `events_any_of` (re-margin proven infeasible by headless
  bench — see decisions #7/#8), warm_reset_tripwire wording, RX-before-step note,
  where-filter on event specs.
- **Round 3 (hil_report_20260831_015024): 39/39, audit-confirmed.** Two-outcome check
  validated live on its first B draw; L bimodal-by-mechanism; handoff latency read as
  phase jitter.
- **Round 4 (hil_report_20260831_021553): 39/39, ZERO structural diffs vs round 3.**
  scp drew outcome A (both branches now exercised); handoff latency datapoint #5
  (13.130 ms) corrected the jitter model to uniform [0,20) ms (50 Hz share tick) and
  CLOSED the tracker. 156 runs tonight, no power-cycles, no board defects.
- (final commit below = this log + the CLAUDE.md addendum)

## Where to resume from

Every commit tonight is safe to resume from; nothing was left mid-flight. If you want
to unwind a decision: `817295d` predates all suite-check ratchets; `9612369` predates
the two-outcome scp expectation; `82c8f75` (== HEAD before the close-out commit) is
the state all of rounds 3–4 validated. The four report folders (000518, 010145,
015024, 021553) are local-only (HIL Results/ gitignored) — each carries HIL_FINDINGS
+ HIL_SUMMARY.

---

# Overnight autonomous session log — 2026-08-31/09-01

Operator instructions (2026-08-31 evening): work through WORK_QUEUE.md autonomously;
judgment calls decided by a Fable-high + Opus-xhigh decision pair, adjudicated by the
orchestrator; all changes via streamlined orchestrated rounds; up to FIVE cycles of
run_hil_suite (fw v23 on the board — NOT reflashed) + live hil-agent-analysis + fix
rounds; fw v24 (dynamic Ag105 MPPT threshold) PREPARED and host-native-tested but not
flashed; findings logged here for morning review. Session starts from commit d5d72e3
(fix round + sdp_policy_v2).

## Campaign 1 (first v2 campaign)

Launched immediately after d5d72e3. Purpose: calibrate the three provisional ems-sdp
v2 checks (raw-share interior, low-demand rail, charge window), observe the predicted
~1 Hz FC_CHARGE chatter, validate the fix round's re-derived thresholds
(_Y_FC_FLOOR {0.50, 0.66} measured, socband 0.95, fc_bus_restored 900,
v_bus_min_in_band on TP0178/TP0201), full plan + --with-ftp75, no --with-operator
(drive SKIPs by design).
