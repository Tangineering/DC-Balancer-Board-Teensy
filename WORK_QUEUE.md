# Work queue — updated post round 2026-09-02 (Ag105 η = 0.88, η-era DP/SDP, MPC live, campaigns B and C analysed, physics review closed, session closed out)

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
  (0.381, 0.399) A at 1.6–1.7 A and dropouts at 0.55–1.04 A in the W cluster.

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
