# Work queue — updated post round 2026-09-02 (Ag105 η = 0.88, η-era DP/SDP, MPC live, campaigns B and C analysed, physics review closed, session closed out)

## 0. NEXT — operator review, in this order

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
