# Work queue — updated post round 2026-09-01e (fw v25 first campaign + EMS test-program round)

## 0. NEXT — operator review, then campaign 2

1. **Review this round** (CLAUDE.md addendum 2026-09-01e; `HIL Results/hil_report_20260901_151156/
   HIL_SUMMARY.md`; the change request for the PhD student `docs/pi_bridge_change_request_20260901.md`).
2. **Campaign 2** — the first campaign of the NEW baseline era (preload 0 on the FTP-75 legs, converter
   asymmetry default-on, the three tooling fixes from campaign 151156). It calibrates every provisional
   FTP-75 band (walk-derived; provisional_note on each), validates the chopper-event fix bands on
   regen-harvest-true, confirms the mppt cruise-window tripwire, and settles the comm-loss re-close
   re-baseline (0.3591 A/ch, WP-C-attributed). Run with `--with-ftp75`; analyze under
   hil-agent-analysis; expect the FTP-75 frontier to EVALUATE for the first time.
3. **Pick the three α points** for live SDP runs (docs/modeling/sdp_alpha_sweep_20260901.md §8):
   `ems-sdp` discriminates three legs (greedy idx 0–6, calibrated 7–13 incl. the anchor 10,
   charge-admitting 14–20); on `ems-ftp75-sdp` points 7–20 are identical. A live sweep point binds
   through the non-frontier `sdp-v2` role (sweep artifacts are outside the lever windows / mode
   "explicit"); a scenario key for the policy file is a one-line addition when wanted.

## 1. EMS test-program goals (operator directive 2026-09-01) — status

1. **Aux preload removed from drive cycles — DONE (B1).** FTP75_PRELOAD_A / FTP75_SDP_PRELOAD_A → 0.0;
   Y_AUX_LOAD_A stays (constructs the Y stimulus). Campaign 151156 is the last preloaded era;
   constants_hash and the FTP-75 DP fingerprint moved (table regenerated, 403c5e71…). Expectations
   re-derived with the governor walk (tools/ems_walk.py) — provisional until campaign 2.
2. **ΔSoC-matched post-hoc DP — DONE (B2).** `hil_report_analysis.py --matched-dp {off,lookup,solve}`
   + `tools/dp_results_db.py` (store tools/dp_db/, lookup tol 1e-5 SoC, era overrides, prefill). Open:
   the FTP-75 legs of campaign 151156 are being prefilled (~24 min each); a DP-vs-live per-stage
   share residual check for ems-ftp75-dp (run h2 −2.15 % vs its table's prediction) is queued.
3. **α-sweep — DONE (B3).** 21 artifacts under tools/sdp_policies/sweep_20260901/ + offline evaluation
   on ems-sdp and ems-ftp75-sdp. Charging enters the table at α = 0.23925; share-0 degeneracy below
   0.106; charge-admitting points lose +16 % eq-H2 on ems-sdp (the charge-economics finding again).
4. **EMS comparison deliverable — per-campaign form DONE** (the "ΔSoC-matched DP comparison" table in
   ANALYSIS_SUMMARY.md). The cross-campaign/cross-cycle roll-up document is queued after campaign 2
   (needs the zero-preload FTP-75 legs and the FTP-75 matched solves).
5. **Governor-aware MPC / stochastic MPC — NEXT ROUND.** Prediction model now exists:
   tools/governor_model.py (firmware port, validated on campaign MDAC traces) + tools/ems_walk.py.
   Design decisions recorded in memory: deterministic MPC = receding horizon with drive-cycle preview;
   stage cost = the student's online proxy P_fc/(η·Q_LHV) with η = 0.4 (Gfc stays plant-side), the
   convex map as a flagged option (TODO(calibrate) at rig scale); stochastic variant via the TPM
   (tools/tpm_generator.py, TPM_dt1_hil.mat). Must run in the stdlib simulator at 1 Hz decisions —
   horizon-DP over the share ladder is tractable in pure Python. Source: references/EMS/
   SDP_EnergyManagement_Governor2.m (governor_tick mirrors the firmware; its I_bench_nominal_A 2.0 A
   and P_fc_ramp 50 kW/s are placeholders; tick 1.136 ms vs the firmware's 1 ms).
6. **Converter asymmetry — DONE (A4 + C1).** Measured ΔV0 +0.0444 V (M1) / the M2 consistent pair
   (ΔV0 0.0135 V, ρ 0.943) adopted in the plant (C1 fix round: injecting M1's ΔV0 together with a
   separate ρ double-counted the collinear component — RMS vs CAL-1 0.040 → 0.006); default-on;
   `--asymmetry off` byte-identical. The +8.1 % shared/single residual is NOT explained by asymmetry;
   the ~4× K_DROOP finding reproduces independently and stays open. Bench TODO(calibrate): an 'O'
   open-loop share sweep above 0.60 A (no open-loop feedforward windows exist in the corpus).
7. **Plant physics review against SD logs — SEEDED, not started.** Inputs now on record: the chopper
   event-accounting defect (fixed), the mppt mirror's missing REGEN exclusion, the comm-loss RT1987
   ON-stamp shift, the ftp75-dp table-fidelity gap, the b00-v3 gate-fraction discrepancy, the
   asymmetry corpus (docs/modeling/converter_asymmetry_20260901.md §F table seed in the
   investigation). Vehicle: adversarial-doc-review over docs/HIL_PLANT.md.

## 2. Pi bridge v4 parser audit — DONE

`docs/PI_BRIDGE_V4_AUDIT_20260901.md` + `docs/pi_bridge_change_request_20260901.md` (send to the PhD
student) + `tools/test_pi_bridge_v4.py`. The 08-17A bridge is v4-conformant byte for byte. Mode B is
gated on the Pi running that bridge with a FIXED `sdp_ems_node` (the 03-16A node reads the 15-element
layout — unsafe on its SoC branch — and the default launch file starts it) and on the standalone SDP
scripts being retired or updated from the 54 B protocol. The bridge's stale-link handler overwrites the
fault word (bitwise OR needed). Pi-side SoC is a V_batt LUT — not comparable with sim-only strategies.

## 3. Bench items feeding TODO(verify)s

- VESC regen commanded-vs-delivered mapping (`VESC_REGEN_I_MAX_A` + `ETA_REGEN`).
- 30 ms survivor blanking against a REAL RT1987 turn-on (HIL validated the logic against the modelled
  t_D_ON only) — asymmetric failure direction; never shorten on the model alone.
- Boost-OR `strict_forward` A/B comparison.
- MPPTD-disabled-charge semantics.
- Silvertel EPROM endurance — `TODO(verify: Silvertel)`.
- Open-loop share sweep ('O' command) above 0.60 A for the asymmetry fit (item 1.6).

## 4. Protocol flags

- `sw_ring` state field — not on the observation frame.
- `shareCutRefusedLoad` / `shareCutRefusedBlank` tick counters — not on the frame (campaign 151156
  proved the refusals only indirectly, from the guard arithmetic).
- `error_code` — ON the frame (fw v25) and now consumed by the analysis (attribution + CSV).

## 5. Open analysis questions

- **Charger efficiency model (found by the power-balance column, 2026-09-01f) — OPERATOR DECISION.** The hi-fi Ag105 is a 1:1 CURRENT-transfer element (J[N_CHG] -= i_charge; the pack receives the same current), so it destroys i_charge·(V_chg − V_batt) and over-draws the bus ~1.8× versus a real buck at η ≈ 0.9 (a 15 V bus would supply ≈ 0.79 A to deliver 1.4 A at 7.9 V). This bears on the campaign-000816 "charging is loss-making at rig scale" conclusion and on L_chg 0.2364 SoC/g behind sdp_policy_v3's α: an η-conserving charger stamp would make charging ~1.8× cheaper in bus energy. Decide: keep (document) or re-model, then re-derive the charge lever and re-solve the SDP α. The simple engine separately treats charging as free energy (i_total never includes the charger draw, hil_plant_sim.py:1448) — documented, hifi-only campaigns are unaffected.
- Does the charger lever clear the 0.31 SoC/g `sdp` charge-revisit condition under the regen model?
  Campaign 151156 measured charge-regen at ~39 mC/window (regen-fed, −97 % vs the bus-fed era); a
  marginal SoC/g derivation across two campaigns is needed (no automated metric) — after campaign 2.
- ems-ftp75-dp: run h2 −2.15 % / ΔSoC +4.8 % vs its own table's prediction — per-stage residual check
  queued (item 1.2).
- ems-y b00-v3 gate fraction (campaign 20.6 % vs walk 12.7 %) — the governor walk can now settle it.

## 6. Housekeeping

- Campaign ledgers live in gitignored `HIL Results/`; promote 151156 to a committed skill exemplar?
- Rebuild the benchlog analyzer exe (still pending since fw v18; the asymmetry_fit module is new and
  not part of the exe).
- `.venv_hil` stdlib / miniforge numpy split stands (test_figures.py needs numpy; run tools/ with
  `--ignore=tools/test_figures.py` under .venv_hil).
- Rs(SOC) calibration against a real 2S pack; hifi M1 re-arm live coverage; early-exit guard.
- `references/Systemic_Scaling_…pdf` was rewritten in the working tree on 2026-09-01 15:41 by
  something outside this round (18 KB smaller) — not committed; operator to check.

## 7. Model and tooling improvements (open)

- Gfc stack identification (absolute H2); SDP smoother stage cost (FC efficiency curve).
- `signal_series_verdict()` native two-sided spec support.
- TPM generator contract wording (sidecar normalization is documentation for the SDP path).
- Ag105 policy on real hardware (lazy re-config, FC_CHARGE open-through-loss).
- Replay half cannot exercise `share_cut_load_hazard` (no events.jsonl; share replays non-opt-in) —
  add an opt-in share-stimulus replay entry if guard coverage from the replay half is wanted.
- Governor model: `conv_tau_s` fit reported (shallow optimum 5–10 ms), not adopted; ems-sdp-braking is
  outside the model's fidelity claim (charge-window ratio wind-down dynamics).

## Shipped 2026-09-01f (follow-on round)

- `hil_power_balance` figure in every HIL report + six append-only power columns (both engines);
  backfilled across all 14 report folders (legacy CSVs: source powers only).
- Refined α-sweep: both transition points bisected (0.111000 / 0.239250 = the admission-window ends),
  20 refined artifacts (idx 21–40), walk-synthesized plots per point, h2-vs-α step figures, doc §10–11.
- Found: the hi-fi Ag105 is a 1:1 current-transfer element (charger-efficiency decision, §5).

## Shipped this round (2026-09-01e)

- Campaign hil_report_20260901_151156 (fw v25 first campaign): T1/T2/T3 validated; 3 false FAILs fixed.
- tools/governor_model.py + tools/ems_walk.py (+ tests); tools/dp_results_db.py + tools/dp_db/ +
  matched-DP post-pass; tools/sdp_alpha_sweep.py + 21 artifacts; tools/benchlog_analysis/
  asymmetry_fit.py + docs/modeling/converter_asymmetry_20260901.md; the Pi bridge audit pair;
  preload removal (B1); asymmetry-in-plant + simple-mode sign fix + campaign fix queue (C1).
