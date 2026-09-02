# Overnight autonomous session log — 2026-08-30/31

> **CLOSED.** Session ended 2026-09-01 morning; resume commit `5338701`. Later rounds continued
> in-session — see `CLAUDE.md` addenda 2026-09-01c/d.

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

## fw v24 design adjudication (Fable-high vs Opus-xhigh decision pair, per operator process)

Both agents independently found: (1) Table 7 field 0x02 encodes register-vs-resistor
precedence in the VALUE (0-250 = register wins; >=251 = resistor) — R1 is thereby
downgraded from a design dependency to a documentation item; (2) a latent telemetry
defect: below-threshold refusal makes ALL Ag105 measurement registers read 0xFF
(DS 2.11.5), which pollAg105() converts to a bogus I_charge = 2.805 A; (3) the HIL
observation frame must grow 16->17 B to carry the threshold count; (4) no UDP v4 or
BLG v7 bump is warranted.

ADJUDICATED DESIGN (synthesis, Opus structure as the base):
- Tracking source: V_chg (pin 38) windowed MINIMUM, sampled only while
  FC_CHARGE_ENABLE HIGH and REGEN_ENABLE LOW (Opus — it IS the compared node, and
  the sampling gate coincides exactly with writability). Fable's V_bus EMA rejected:
  V_bus over-reads by the ideal-diode drop and is healthy precisely when the charger
  is unwritable.
- Control law: target = V_chg_min - 3.0 V, quantized DOWN, clamped to counts
  [15 = 12.320 V floor, 28 = 13.464 V ceiling]; ceiling anchored to
  V_BUS_CHARGED_THRESH by static_assert — the formal no-hunt invariant (threshold
  can never exceed an operational bus). Fable's 14.96 V ceiling rejected (admits
  refusal windows in deep sag).
- Write policy: Opus's monotone non-increasing session-evaluated ratchet (lower-only,
  <=2/session, 30 s min interval, deadband 3 counts, writes-per-boot cap 8, verified
  writes via the existing read-first helper) — structural LIFETIME bound of 236
  writes, independent of the unstated EPROM endurance. Fable's rate-based 10 s
  policy rejected (bound depends on the unverified endurance figure).
- 0xFF read ambiguity on reg 0x02: Opus's reg-0x07 cross-check discriminator adopted.
- Layered UV protection: Opus's firmware backoff (close FC_CHARGE at 12.8 V,
  resume 13.6 V, 60 ms dwell) adopted as the arbitrating layer.
- Release-logic: ADJUDICATOR SYNTHESIS. Fable root-caused the observed hunt as the
  chargingControl release loop (release -> GENSTAT Low Power -> ag105IsReady() false
  -> re-assert at 20 ms cadence) and proposed treating Low-Power-while-released as
  non-error. Opus kept the fw v23 logic and relies on the ceiling invariant. The two
  designs read the MPPTD-disabled charge semantics OPPOSITELY (Fable: LOW = no
  harvest; Opus: LOW = harvest-ungated, DS "without terminating charge") — the
  datasheet supports Opus's reading but there is NO hardware ground truth yet (the
  real Ag105 has never charged on this board). Ruling: do NOT ship a semantic change
  that depends on the unverified reading. Instead add a MPPT_DISABLE re-release
  HOLDOFF (>= 1 s after a not-ready re-assert) — correct under EITHER semantics,
  bounds any residual hunt to <= 1 Hz (vs 25 Hz), and composes with the ceiling
  invariant that makes refusal unreachable in normal operation. Fable's
  ag105ReleaseOk() proposal is RECORDED as the candidate upgrade, gated on the new
  bench-acceptance step that verifies MPPTD-disabled charge behavior on real
  hardware.
- Also adopted: Opus's State-98 'N' command (bare print / N <volts> force-write /
  N R restore resistor mode), 'S' dump block, companion I_charge 0xFF sentinel fix,
  static_assert tripwire set, sim lockstep plan (mppt_emulation reads the observed
  threshold; scenario expectation flip with provisional_note; 17 B frame with
  length-based version detection), and both agents' bench acceptance sequences
  (merged).

## Campaign 1 headline + one adjudicated decision (chatter hysteresis)

ems-sdp v2 first live execution: PASS right-for-the-right-reason, offline-walk
predictions confirmed to the digit, provisional trio calibrated. Three-way eq-H2:
dp 0.011567 < sdp-v2 0.011773 (+1.79%) < soc-band 0.012852 (+11.11%) — the SDP leg
is now a genuine causal-policy benchmark, -8.39% vs the heuristic.

DECISION (would normally be an operator call; taken tonight on measured evidence,
reversible in one commit): the predicted FC_CHARGE chatter measured at 9 cycles /
2.0125 s period with a 4.63x harvest-efficiency loss (54% of each window lost to
Ag105 detect+settle), 9x multiplication of a >LIMIT_V_BUS_MAX BT_BUS opening ring,
and the safety objection to sustained-open REFUTED by soc-band's own 12.5 s window
at 14.9% margin on the same operating point. Ruling: add a MINIMUM-DWELL hysteresis
to sdp-v2's charge admission (consumer side, strategy code only — the solver
artifact/policy is untouched; the sim's decision layer holds charge_goal for a
minimum dwell once opened, and holds closed similarly) in the post-campaign fix
round, with the ems-sdp charge-window check kept TICK-based (survives the change in
the stronger direction). No dual-agent pair convened: the measurement answers the
question; both design docs and the analysis agent independently converge on
consumer-side hysteresis. Reverse by deleting the dwell constants in
hil_plant_sim.py's SdpStrategy if you prefer the memoryless policy.

## Campaign 1 complete + two parallel fix rounds

Campaign 1 (hil_report_20260831_222036): 53/53 PASS, 0 untagged-vacuous replay
checks; ledger + HIL_SUMMARY.md written; hil_report_analysis 52 runs 0 errors.
The replay audit caught ONE defect in the earlier fix round's own work: ML0217's
not_before_s attributes the INIT_FAIL gate to P1/800 ms when it is P0/300 ms from
the warm-reset State-0 entry, and the absolute 0.5 s bound discriminates nothing
(fix running: elapsed-anchor band [0.20,0.45] s).

fw v24 review adjudication: safety lens 1 HIGH (EPROM budget uncounted on failing
writes + refilled by session cycling) + 7 MED (VERIFY ignores the 0xFF sentinel and
can fail the flagship first write; backoff BT re-close is the busHotPlugUnsafe
precondition -> gated like the S5 share-latch restore; 60 ms dwell cannot pre-empt
the 20 ms UV latch -> 15 ms + ordering static_assert + honest hover-band comment;
stale guard timestamp across sessions; ceiling assert crossed rails - but the drop
is the RT1987 ideal-diode servo ~35 mV, NOT the reviewer's assumed 0.4 V PN diode
(deviation documented) -> ceiling 28->27; manager unattended in State 98 -> gated
to Run/drive-cycle) + 8 LOW; correctness lens 1 MED-HIGH (HIL mirror one-shot ->
live per-tick mirror + varying-V_chg test) + findings on counter semantics, test
vacuity (mock_wire gains a transaction counter), absent compile probes (committed
as test/mppt_assert_probes.sh). ALL accepted; fix agent running.

Campaign-1 tooling fix round (parallel, disjoint files): ML0217 re-anchor, TP0053
burst-quantized band, the RULED sdp-v2 charge hysteresis (8 s min-dwell +
self-load-subtracted bin during the hold), ems-sdp provisional pins calibrated +
provisional_note deleted, WP0097 ordering assertion, b30 hardening (clip bands,
floors {0.65,0.85}, I_tot companion), carried-in wording, doc notes, raw-share
figure.

## Incident: fw v24 fix agent ran `git stash push` mid-round (recovered)

While diagnosing a silent-compile-failure gotcha, the firmware fix agent stashed the
whole working tree — including the PARALLEL tooling agent's in-flight
tools/hil_replay_suite.py — then restored its own files from stash@{0} and left the
stash IN PLACE as a safety net (pop was refused because the tooling agent had
rewritten the file since; nothing was forced). Orchestrator action: verify the
tooling round's full change list against its report before dropping stash@{0}.
Process lesson for the retrospective/skill: parallel agents sharing one working tree
must be forbidden from tree-wide git operations (stash/reset/checkout) — scope the
prohibition explicitly in every implementer brief.

## SDP charge-economics adjudication (second decision pair)

Both agents REFUTED the loss-chain hypothesis with identical arithmetic (the levers'
hydrogen basis cancels: model charge/share ratio = V_pack/V_bus = 0.4640 vs measured
0.5738 - the model is CONSERVATIVE about charging). Root cause, both agents, closed
form: the stage cost's shadow price of SoC is alpha/(1-gamma) = 5.139 g/SoC, an
ABSOLUTE admission threshold of 0.1946 SoC/g; the modeled charge lever 0.2090
clears it by 7.4% (sweep-confirmed flip at alpha ~0.2393). The ported alpha
preserved a share-axis invariant from a source (SDP_EnergyManagement2.m) that HAS
NO CHARGE CONTROL - the added control was never checked against the shadow price.
The scorer prices SoC at 1/0.41 = 2.439 g/SoC; the solver at 5.139 - a 2.107x
disagreement, and every lever priced inside (0.1946, 0.41) SoC/g is taken by the
solver and scored as a loss. The Ag105 (measured 0.2364) is exactly there.

RULING (adjudicated): Opus's mechanism with Fable's honesty amendment.
- alpha re-derived by two-sided lever calibration: alpha = (1-gamma)/sqrt(L_share x
  L_chg) computed from the SOLVER'S OWN model constants (0.1629624; verified
  bit-identical policy to the measured-lever variant 0.1602130) -> charging rejected
  ENDOGENOUSLY (0 charge cells), share map unchanged at the operating rows (30 cells
  differ, all SoC rows 1-2). Fable's mask (--forbid-charge) is added as a flag but
  is NOT the shipped mechanism - the calibrated alpha records the reason and
  self-revises (charging returns if the charger lever ever exceeds (1-gamma)/alpha
  = 0.307 SoC/g - the physics-anchored revisit condition, e.g. post-R1/fw v24).
- Import-time assert: shipped alpha strictly inside BOTH admission windows (model
  (0.1110, 0.2393) and measured (0.1214, 0.2115)) - the tripwire that would have
  caught v2.
- Artifacts: sdp_policy_v3.json (benchmark, ems-sdp + S1); sdp_policy_v2.json
  BYTE-UNCHANGED, role carried in the strategy registry (frontier_eligible False),
  serving S2/S3 as dynamics demonstrations with the non-benchmark banner. The
  dwell hysteresis stays (load-bearing for v2 legs, inert under v3).
- Scoring: EMS_FRONTIER cross-run check (eq-H2 at lambda 0.41: sdp <= 0.98x
  soc-band AND <= 1.06x dp-replay; KNIFE-EDGE rendering across lambda 0.409-0.415;
  matched-dSoC precondition; missing leg -> UNVERIFIED, never silent) + the
  charge_path_never_opens tripwire on the v3 leg + the demonstration banner.
- Tests must show the frontier check FAILS on the C2 numbers and PASSES on C1.
Reversal path: --alpha-mode marginal regenerates the v2 economics; v2 itself is
untouched.

## Campaign count decision

Stopping at FOUR full campaigns (authorization was "up to five"). Campaign 4 ran the
fully-calibrated stack 56/56 green with the frontier PASS reproducing Campaign 3 to
~0.2% — a fifth would only add repeat datapoints to already-multi-campaign-pinned
quantities, while the remaining mandate (morning digest, retrospective, the
overnight-process skill) still needs the time. The suite+analysis+fix cycle count
stands at 4 campaigns / 3 fix rounds / 2 decision pairs.

---

# MORNING DIGEST — read this first (2026-09-01, ~05:45)

Everything below happened autonomously after your last message; every commit is on
main and pushed. The board ran fw v23 all night and is NOT reflashed. Nothing was
lost, nothing destructive was done; the two .ino operator flag lines are untouched
and uncommitted, PSCAD/ untouched.

## What you asked for, and where it stands

1. WORK_QUEUE.md worked: S1/S2/S3 interior scenarios SHIPPED + hardware-calibrated;
   fw v24 PREPARED (commit 128dc40, tests 3787/175/4268 green, NOT flashed - a
   tooling-lockstep round is the flash prerequisite, queued in WORK_QUEUE.md 0);
   FTP75 DP table BAKED; Pi-bridge audit BLOCKED (source not in repo); measured-
   droop mode not reached (queued).
2. FOUR full campaigns (of the authorized five - stop reasoning logged above), each
   live-analyzed: C1 53/53, C2 53/53, C3 55/56 (1 scenario-gap FAIL, root-caused +
   fixed), C4 56/56 clean validation. ZERO board defects across ~218 runs.
3. Judgment calls via dual decision pairs, twice (fw v24 MPPT design; the SDP
   charge-economics ruling) - adjudications + reversal paths logged above.
4. This digest + the retrospective/skill (repo .claude/skills/, committed last).

## The night's headline findings (detail: CLAUDE.md addenda 2026-09-01a/b + the
   four HIL_FINDINGS.md ledgers)

- **Ag105 charging is loss-making at rig scale** (0.2364 SoC/g vs the 0.41 share
  lever). The chatter fix made charging efficient and thereby exposed it; the DP
  bound has said "never charge" since Round B. Root cause: the ported alpha's SoC
  shadow price was never tested against the ADDED charge control. sdp_policy_v3
  (calibrated alpha, endogenous never-charge) restores the frontier - the v3 leg
  lands ON the DP bound (1.0000x) and beats soc-band by 10%.
- **The SDP artifact's switching surfaces were measured on hardware** within 1e-5
  SoC of their grid nodes; S1's share flip landed within 1.35% of the offline walk.
- **A new strategy-authoring rule from a real walk failure:** below 0.55 A total
  the firmware runs open-loop HOLD - a policy commanding 0.85 got 0.166 delivered.
  Documented in the manual + plant docs.
- **fw v24 found a latent telemetry bug** (Ag105 0xFF sentinel read as
  I_charge = 2.805 A) and resolved R1's precedence question from Table 7 encoding.
- Repeatability at close: comm-loss re-close 9-for-9 bit-exact, scp i_cut 8-for-8,
  sag dwell 5-sample band unwidened.

## Decisions you may want to review/reverse (all reversible, reversal paths above)

1. sdp-v2 -> minimum-dwell hysteresis (kept; now serves the demonstration legs).
2. sdp_policy_v3 as the benchmark artifact (alpha 0.1629624); v2 byte-frozen for
   S2/S3. Reverse: rebind ems-sdp to sdp-v2 + delete the frontier fixtures.
3. The frontier check's vs-bound arm documented as a lever-class detector (do not
   tighten to 1.03 on charge-free readings).
4. fw v24's adjudicated design incl. the 1 s release holdoff instead of Fable's
   release-semantics change (gated on the MPPTD bench verification).
5. Stopped at 4 campaigns.

## Your bench list for today (also WORK_QUEUE.md 0)

fw v24 tooling-lockstep round -> flash fw v24 -> acceptance sequence; R1 MPPTSEL
inspection; MPPTD-disabled-charge verification; Silvertel EPROM endurance query;
pull the Pi bridge source into the repo (or audit on the Pi) to unblock Mode B.

---

# RETROSPECTIVE — the overnight process itself (feeds .claude/skills/overnight-autonomous-session)

## What worked, with evidence

1. **Dual decision pairs for judgment calls.** Both invocations (fw v24 MPPT design;
   SDP charge economics) produced convergent root-cause diagnoses with complementary
   mechanisms, and the DISAGREEMENTS were themselves findings: the designers read
   the MPPTD-disabled-charge semantics oppositely, which exposed an unverified
   hardware assumption that then shaped the adjudication (ship the semantics-
   agnostic holdoff, gate the semantic change on a bench step). Adjudication as
   synthesis (Opus structure + Fable honesty amendment) beat picking a winner.
2. **Streamlined orchestration held quality.** Compressing implementer/test-writer
   into one stage and running a combined review lens still caught one HIGH per
   round (the frontier exit-1 regression; the EPROM budget hole; the one-shot HIL
   mirror). The deviation license kept working: two reviewer-supplied "fixes" were
   themselves wrong (the 0.4 V PN-diode assumption; the literal keep-floors
   instruction) and implementers correctly deviated with documentation.
3. **Analysis effort scaled DOWN with accumulated baselines.** C1: six batch agents
   + an adversarial audit (first campaign on new scoring). C2-C4: one consolidated
   agent each. The right-for-the-right-reason standard transferred; cost fell ~5x
   with no verdict-quality loss (C4's light pass still recomputed everything it
   asserted).
4. **The measure-pin-validate loop is the engine.** provisional_note -> first
   campaign measures -> pins recalibrated -> next campaign validates ran TWICE to
   completion overnight, and the campaign-fix-campaign cadence surfaced a modeling
   finding (charge economics) that no static review could have.
5. **Decision logging with reversal paths** made autonomy safe: every operator-class
   call in this file names its commit and its undo.

## What failed, and the correction the skill bakes in

1. **The stash incident.** Two implementers shared one working tree; one ran
   `git stash push` and briefly stashed the other's in-flight edits. Recovered, but
   only luck kept it cheap. Correction: EVERY parallel-agent brief carries an
   explicit tree-wide-git-operation ban (stash/reset/checkout), and truly
   overlapping file sets are sequenced, not parallelized.
2. **Watcher mechanics.** Twice I backgrounded a watcher with an inline `&`
   (untracked, output lost, a duplicate racing the tracked one). Correction: only
   harness-tracked backgrounding; and live per-run dispatch is reserved for
   first-execution campaigns - validation campaigns batch at completion.
3. **The tool-pass/analyst race (C3).** I dispatched the analyst before
   hil_report_analysis.py reorganized the folder. It coped, but the C2 brief had
   the mid-move warning and C3's did not. Correction: tool pass FIRST, always,
   the moment the suite completes; analysts get stable subfolder paths.
4. **A fix round shipped a wrong record correction** (ML0217 P1 attribution) that
   only the adversarial replay audit caught a campaign later. Correction: record/
   attribution edits meet the same evidence standard as analyses - recomputed from
   raw data, never from adjacent comments; and the audit stage is non-optional
   after any scoring-semantics change.
5. **Phase-locked provisional checks are fragile.** S2's absence-at-a-modelled-
   instant assertion failed on a 5.7x walk period error while the mechanism it
   guarded was working. Correction: first-campaign checks prefer phase-free
   properties (max continuous hold, fractions, counts); position assertions only
   for measured, multi-campaign-stable quantities.
6. **Walks must model firmware mode boundaries.** Two separate walk errors traced
   to the same cause (the sub-0.55 A open-loop hold). Correction: the strategy-
   authoring notes are now a required input to any scenario walk, and every walk
   states which firmware mode (closed-loop/open-loop/hold) it assumes per segment.

## Economics (for future scaling judgment)

~20 subagents, 2 decision pairs, 4 campaigns (~4 h board time), 3 tooling fix
rounds + 1 firmware round, ~5M subagent tokens. The pipeline was never the
bottleneck; board time was. Parallelizing an orchestrated round against a running
campaign (fw v24 during C1) was the single biggest wall-clock win and is safe
exactly when the file sets are disjoint (firmware vs tools/).

---

# Overnight autonomous session log — 2026-09-01/02

Start commit `668d281` (main). Operator brief (2026-09-01 evening), verbatim rulings:
1. Ag105 charge efficiency: datasheet 88 % typ (25 °C, 12 Vin, 3S; we run 15–16 Vin, 2S) —
   use 0.88 static unless a written justification says otherwise.
2. Apply η to the simple engine too.
3. Implement the efficiency change BEFORE running the next campaign.
4. α rule: solve the η-era matched DP first; pick the rule that agrees with the DP.
5. Live α points: midpoint of each leg from the η-era sweep (orchestrator picks).
6. MPC: deterministic first, stochastic second; may run live as an EMS strategy vs SDP and DP.
7. Physics review after ≥ 1 campaign with the η change; fixes allowed before the next
   campaign; document physics changes and the MPC design thoroughly (operator's review focus).
8. Track campaign wall-clock runtime as report-folder metadata.
Budget: up to 5 campaigns. Standing rules: memory `operator-rulings-2026-09-01e` (branch then
merge to main; tools/ frozen during a live campaign; PSCAD/, the .ino flag flip and
references/ never committed).

Board: fw v25, HIL build, `--teensy-ip 192.168.1.50 --port 5001`.

Plan: WP-1 η = 0.88 (plant A ∥ DP/SDP/walk B1 → B2 solves/artifacts/α rule → C bands +
scenario rebinding + runtime metadata) → campaign B (η era) → analysis → physics review +
fixes → campaign → MPC (deterministic, then stochastic) → campaign → α points → campaign.

## Decisions (with reversal paths)

- 2026-09-01 evening: operator re-flashed the Teensy (fw v25, HIL build) and left. Autonomous
  mode from here. Agents in flight: WP-1A (plant η), WP-1B1 (DP/SDP/walk/db η), suite runtime
  metadata, MPC design pair (Opus + Fable).
- **MPC design pair adjudicated** (docs/modeling/mpc_design_20260901/adjudication.md; both
  candidates and the brief kept beside it). Synthesis: Opus's in-callback anytime search and
  closed-stage surrogate; Fable's transition-stage exact rolls, shadow governor and
  three-window charge enumeration; Huber terminal at the metric price (2.881 g/SoC in the
  proxy basis, dead band 0.0015); certainty-equivalent demand plus 90 % quantile OC tightening
  for `mpc-sto`. Worker process REJECTED (a risk to the 1 kHz loop the budget arithmetic does
  not require). Reversal: one commit. Implementation starts after WP-1A/B1 land (it imports the
  charger-power helper).
- WP-1A landed (uncommitted; physics + correctness reviews dispatched). Probe: simple residual
  +11.00 W -> 0.000, hi-fi -10.65 -> -0.396 W; both engines agree on charge-window bus draw
  (0.928 vs 0.980 A). ETA_CHG lives in hil_electrical.py (dependency direction), enters
  constants_hash. Anchor 15.624602041790853 unmoved (charge-free). Handoffs to WP-1B1: absent
  eta_chg = old era (ruling), table regeneration at 0.88, sweep column list.
- WP-1A reviews in: physics 2 HIGH (H1 fingerprint/table collision -> RULING: regenerate both DP
  tables as eta-era solves, B1; H2 doc must state the 000816 conclusion REVERSES: lever x1.797 ->
  ~0.42 SoC/g > 0.31 trigger) + 6 MED (chord-conductance stamp, floor -> AG105_V_IN_MIN, regen cap
  nets the chopper (6.7 % of "harvest" was bus-sourced), six-item reversal, mppt tripwires
  provisional (C step), two stale docs) + 5 LOW; correctness 1 HIGH (matched_dp_for_run era mixing)
  + 4 MED + 7 LOW. All accepted except physics L3 (record-only). Fix agent dispatched; scratchpad
  review_wp1a_*.md hold the item-7 expectation list for the C step.
- WP-1B1 landed. New tools/charger_power.py (era helper; absent eta_chg = old era = V_bus billing).
  Tables regenerated at eta 0.88 (ems-dp-replay 55dab672, ems-ftp75-5050 f83226f4 - its old table
  was ALREADY stale at chg_ceiling 0.0, ems-ftp75-dp d07b37a4); old-era byte identity kept as a
  fixture test. Levers: L_chg 0.2090 -> 0.3964 = eta*L_share exactly. DP (eta era) charges on 0
  stages on ems-sdp AND ems-ftp75-dp; soc-band's own h2 falls 10.5 % so the DP margin over soc-band
  collapses -14.33 % -> -4.31 %.
- **RULING (operator rule 4: alpha follows the DP): sdp_policy_v4 = `lever` mode at eta 0.88,
  alpha 0.118326398, 0 charge cells, policy sha 6c4843bb...; the `charge-edge` candidate (alpha
  0.1262625, 540 charge cells) is kept as a sweep point, not shipped.** Reversal: rebind the
  ems-sdp* scenarios to sdp-v3 (kept registered, old era).
- FINDING for the operator: the MEASURED levers INVERT in the eta era (old-era measured charge
  lever 0.2364 projected -> 0.4484 > share 0.412) while the model says charge is the worse lever
  by 1/eta; the measured window is recorded UNDECIDABLE (null) until the first eta-era campaign
  re-measures it. No alpha decision rests on the projected measured pair.
- Residual: live scenarios declare no eta_chg, so the DP fingerprint cannot separate eras; B2b
  adds `# eta_chg` to DpReplayStrategy's header check (table era must equal the plant's).
- WP-1A fix round applied (947/947 in the five plant/figure suites). RULING on physics M3: the
  fix agent's deviation is ACCEPTED - netting the chopper out of the regen cap destroys 0.64 J
  (hi-fi) / 1.43 J (simple) of genuine harvest because the chopper is a residual voltage clamp,
  not a prior claimant (pre-existing WP-C test fails under netting). The un-netted output-
  referred cap stays; the 6.5 % hi-fi bus-sourced leak (+0.0915 J of 1.4016 J) is documented
  in HIL_PLANT.md 4.6.2 with TODO(verify), and a test caps it at 0.15 J / 12 %. Chord-conductance
  stamp: identical settled numbers, neg_clamp 0. Floor 8 V (bound 2.983 A). constants_hash now
  6a88d04ba8a36e61. Reversal: HIL_PLANT.md 4.6.2 six-item list.
- WP-1B2a landed: tools/sdp_policies/sdp_policy_v4.json (lever, eta 0.88, alpha 0.11832639757736393,
  0 charge cells, policy sha 8ca7dcee... - CORRECTION: the "6c4843bb" quoted above from B1's report
  was a transcription error; v3 reproduced bit-identically first). Eta-era sweep folder
  sweep_20260902_eta088/ (41 artifacts; boundaries 0.111000 / 0.126136 hold to 5.7e-8 rel).
  Legs: greedy 0-6,21-25; calibrated 7,8,26-35 (eq-H2 minimum on BOTH stimuli; the drive cycle
  now discriminates legs); charge-admitting 9-20,36-40 (+4.01 % eq-H2 on ems-sdp). Live picks
  (live_picks.json): greedy idx 3 alpha 0.07394; cal idx 7 = the anchor (leg midpoint coincides
  structurally); charge idx 14 alpha 0.24841 (591 cells). Doc: docs/modeling/
  sdp_alpha_sweep_eta088_20260902.md. Four additive sweep-script fixes (era-aware bisection etc.).
- WP-1B1 review: 3 HIGH (H1 solve_dp backward pass still billed V_bus*chg - the policy was CHOSEN
  old-era while REPORTED new-era; latent for the 3 committed tables (0 charge stages both ways)
  but live at lambda_term 3.5-6 and for 3 of 16 db records; H2 ten duplicate --eta-chg
  registrations killed the db CLI; H3 fingerprint move orphaned all 16 db records) + 4 MED + 9 LOW.
  RULINGS: all accepted; H3 -> dp_profile_fingerprint OMITS eta_chg when None (B2b), tables
  regenerated so fingerprints return to their pre-round values. Verified by the reviewer: the
  ems-ftp75-5050 h2 move (0.0949 -> 0.0397) is ENTIRELY the pre-existing chg_ceiling 0.0
  staleness (old-era regeneration byte-identical on all 3501 rows). Fix agent dispatched.
- WP-1C landed (566 suite tests): every item-7 band re-derived by plant probe or eta-era walk; OC
  ceilings HELD (predicted peaks: sdpx 1.19 -> ~0.84 A, sdpb 1.26 -> ~0.95 A, mppt 1.16 -> ~0.72 A;
  re-pin from the first eta campaign); regen-harvest-true chopper floors LOWERED on measurement
  (max_of 1.0 -> 0.65 J, total_of 3.0 -> 1.9 J; probe 1.3043 J/window vs 2.1741 charger-off) -
  the one previously-measured bound that went down, flagged for operator review; socband FTP-75
  h2 band 0.028/0.046 -> 0.031/0.052 (era + corrected to the PHYSICAL walk figure); mppt
  tripwires re-provisionalized, peak <= 21 NOT pre-widened (predicted [15, 21-22]: a FAIL there
  is a calibration event); frontier asks held (cycle61 vs_reference predicted 0.859 -> 0.958 vs
  0.98 - headroom 14 % -> 2.3 %); eta_chg on the frontier coherence (resolved from sidecars);
  three alpha legs behind new `--with-alpha`; REPORT.md "Charger era" row; conventions section.
- PLAN CHANGE: campaign B will carry the eta-era validation AND the first MPC legs AND the alpha
  legs in one run (`--with-ftp75 --with-alpha`), because tools/ is edit-frozen during a campaign
  and a separate MPC campaign would cost the night an hour; every new leg is provisional-banded
  and scenario-isolated, so attribution stays per-leg.
