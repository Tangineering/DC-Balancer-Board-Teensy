# MPC design brief (decision pair; identical prompt to two models)

Repo: `C:\Life Ops\School\Thesis\DC-Balancer-Board-Teensy` (Windows; Git Bash paths `/c/Life Ops/...`).
READ-ONLY task: do not edit any repo file and run no git operation. Write your deliverable to
the scratchpad file named at the end.

## Context you must read first
- CLAUDE.md addenda 2026-09-01b/e/f (EMS program, governor model, matched DP, α-sweep, the
  charger-efficiency finding).
- WORK_QUEUE.md §1 item 5 (governor-aware MPC / stochastic MPC — the brief the operator wrote).
- tools/governor_model.py (firmware share-delivery governor port: latch, min-load freeze,
  0.60/0.55 A hysteresis, open-loop HOLD below 0.55 A, minority clip, slews, r-based cuts +
  fw v25 guards, MDAC quantization), tools/ems_walk.py (offline walk: any registered strategy
  through the DP demand/pack/H2 model with the governor at 1 kHz), tools/sdp_ems_solver.py
  (the SDP port: state SoC, controls power_share_setpoint on a 21-step ladder + binary
  charge_goal, stage cost W_H2 + α·|SoC−target|, γ, the lever/α derivation), tools/gen_dp_ems_table.py
  (the offline DP bound; demand model; physical charger accounting), tools/tpm_generator.py +
  references/EMS/*.m (the student's TPM and MATLAB SDP), tools/hil_plant_sim.py's strategy registry
  (how `soc-band`, `sdp-v3`, `dp-replay` are instantiated and called each tick; the sidecar meta),
  docs/HIL_SCENARIOS.md ems-* rows, docs/modeling/sdp_alpha_sweep_20260901.md.
- Tonight's parallel change (assume it lands before you are implemented): the plant charger becomes
  an energy-conserving buck/boost at η_chg = 0.88 (bus power for charging = V_pack·i_chg/η, not
  V_bus·i_chg). The charge lever therefore rises to ≈ η·L_share; whether the η-era DP admits charging
  is being solved tonight.

## Operator rulings that bind the design
- Deterministic MPC first (receding horizon with drive-cycle preview); stochastic variant (TPM-driven
  demand scenarios) second. It runs as ANOTHER EMS STRATEGY in the HIL suite (registered like sdp-v3),
  compared live against SDP and against the DP bound (ΔSoC-matched post-pass), and offline through
  ems_walk.
- Stage cost: the student's online proxy P_fc/(η_fc·Q_LHV) with η_fc = 0.4 (Gfc stays plant-side); the
  convex FC map is a flagged option.
- Decisions at 1 Hz; must run in the pure-Python (stdlib) simulator in real time alongside a 1 kHz
  plant (budget: well under 1 s per decision on this machine, no numpy in the runtime path).
- The governor model is the prediction model: the MPC must be GOVERNOR-AWARE (predict what the
  firmware will DELIVER for a commanded share, incl. the sub-0.55 A open-loop hold, minority clip,
  slews, cuts), because the "walks must model the open-loop hold" rule broke two earlier walks.

## Deliver a design document (the operator will review this alongside the physics changes) covering
1. Problem statement: state, controls, horizon, preview source (the scenario's demand profile is known
   to the strategy in the sim — say how the strategy obtains it and how that would map to a vehicle:
   route preview vs TPM), decision rate, constraints (OC_FC/OC_BT limits with margins, SoC window,
   charge_forbidden bins under hard acceleration — operator ruling (b) 2026-08-30, FC_CHARGE/REGEN
   mutual exclusion, the charge-window min-dwell 8 s hysteresis).
2. Prediction model: exactly which governor_model/ems_walk functions are reused, integration step,
   how the 1 kHz governor is rolled forward inside a 1 Hz decision (sub-sampled surrogate? full
   1 kHz roll at short horizons? give the cost per decision estimate), pack/SoC model, H2 proxy.
3. Optimizer: horizon length N and control parametrization (move-blocking over the 21-step ladder +
   binary charge), solver (horizon-DP / exhaustive over blocked moves / greedy with lookahead),
   terminal cost (tie to the SDP value function? α·|SoC−target| as terminal penalty?), warm start,
   compute budget arithmetic showing it fits 1 Hz in pure Python.
4. Stochastic variant: how the TPM (tools/tpm_generator.py, TPM_dt1_hil.mat) supplies demand
   scenarios (scenario tree / expected-value / min-max), what changes vs deterministic, cost.
5. Evaluation plan: offline walk vs soc-band, sdp-v3/v4, dp-replay on ems-sdp and ems-ftp75-*;
   live scenario definitions (which existing ems-* stimuli; expectation checks that are PHASE-FREE
   per the overnight skill's rules; provisional bands); ΔSoC-matched DP comparison; what the metric
   structurally cannot distinguish.
6. Registration/plumbing: strategy name(s), sidecar meta fields, CLI flags, files to add
   (tools/mpc_ems.py + test), how ems_walk and run_hil_suite pick it up, and a step list an implementer
   can execute without further questions.
7. Risks and the reversal path (one-commit removal).
Formal document register (repo CLAUDE.md global style: ≤ 25-word sentences, no chat voice, no
market metaphors, every equation introduced in a sentence). Recompute any number you cite.

Write to: <OUT>
