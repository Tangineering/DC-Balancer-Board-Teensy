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

## Commit ledger

(rounds land below as they complete)
