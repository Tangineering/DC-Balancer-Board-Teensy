# Work queue — updated post round 2026-09-02 (Ag105 η = 0.88, η-era DP/SDP, MPC registered, campaign B)

## 0. NEXT — operator review, then the MPC fallback decision, then campaign C

1. **Review this round** (CLAUDE.md addendum 2026-09-02; OVERNIGHT_LOG.md §2026-09-01/02; the
   campaign-B ledger in `HIL Results/`). Four items carry the operator's own review focus:
   - **Physics.** `docs/HIL_PLANT.md` §4.6, §4.6.1 and §4.6.2: the charger is now an energy converter
     at `ETA_CHG` = 0.88 in both engines, stamped as a chord conductance with an 8.0 V floor, with an
     output-referred regen cap that is deliberately NOT netted against the chopper. The six-item
     reversal path is in §4.6.2; `ETA_CHG` = 1.0 alone does not revert the round.
   - **MPC design and the Gate-1 result.** `docs/modeling/mpc_design_20260901.md` §6.5, §8 and §9.
     Gate 1 FAILS with the roll table consulted (mean 0.00971, max 0.25000, band 5e-03) and the round
     shipped `mpc-det` / `mpc-sto` live with that recorded.
   - **The `regen-harvest-true` floor lowering** (max_of 1.0 → 0.65 J, total_of 3.0 → 1.9 J): the only
     previously-measured bound this round moved downward.
   - **The measured-lever inversion.** The projected measured charge lever 0.448393 SoC/g overtakes
     the measured share lever 0.412, against the model's `1/η` ordering; the η-era measured window is
     recorded UNDECIDABLE (null) under the certificate allowance until a campaign re-measures it.
2. **MPC fallback decision (morning).** Either adopt the design's own fallback — full governor rolls
   on open-loop stages with a reduced candidate set, `mpc_design_20260901.md` §3.5 and §7.1 — or
   build a feedforward-aware stage model, or accept the surrogate and keep `mpc_share_pred_err` as a
   measured band. Campaign B's board-side prediction error is the reading that informs the choice.
   Reversal if the legs are to be withdrawn: drop the four `ems-mpc*` scenarios, one commit.
3. **Campaign C — after the physics review and its fixes.** It is the first campaign of the
   post-review era and should re-pin: the OC ceilings whose predicted peaks fell (sdp-cross ~0.84 A,
   sdp-braking ~0.95 A, mppt ~0.72 A), the mppt peak tripwire held at ≤ 21 against a predicted
   [15, 21–22], the socband FTP-75 h2 band 0.031/0.052, the `regen-harvest-true` floors, and the MPC
   bands de-provisionalised from campaign B. Run under hil-agent-analysis.

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
   from campaign B.
6. **Converter asymmetry — DONE (2026-09-01e A4 + C1).** ΔV0 and ρ adopted as the M2 consistent pair,
   default-on, `--asymmetry off` byte-identical. The +8.1 % shared/single residual and the ~4×
   `K_DROOP` finding stay open. Bench `TODO(calibrate)`: an 'O' open-loop share sweep above 0.60 A.
7. **Plant physics review against SD logs — SCHEDULED after the campaign-B analysis.** Inputs on
   record: this round's charger-efficiency change and its documented 6.5 % bus-sourced regen leak,
   the deferred chopper side of the residual identity, the mppt mirror's missing REGEN exclusion, the
   comm-loss RT1987 ON-stamp shift, the `ems-ftp75-dp` table-fidelity gap, the b00-v3 gate-fraction
   discrepancy, and the asymmetry corpus. Vehicle: adversarial-doc-review over `docs/HIL_PLANT.md`.

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
- **The 6.5 % bus-sourced regen leak — NEW.** +0.0915 J of a 1.4016 J charger input arrives from VBUS
  through a closed `MOT_PWR` in the hi-fi engine, where simple mode leaks exactly zero. Closing it
  needs the charger and the chopper clamp solved together at one node voltage; a test caps the leak
  at 0.15 J / 12 % meanwhile.
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
- **The chopper side of the residual identity is DEFERRED (physics review L3).** `p_chop` sits on the
  source side although it is a dissipation, so a braking-window residual is dominated by `−2·p_chop`.
  Moving it beside `p_mot` and `p_chg_loss` changes the meaning of `p_bal_w` in every CSV written
  since 2026-09-01f, and that era boundary is better moved once, with any other identity change.
- **`ems-ftp75-dp`: the table's walk-side fingerprint is stale.** `ftp75-mpc` reads vs_reference
  0.9738 and has no vs_bound prediction, because `dp_ems_table_ems-ftp75-dp.csv` carries a stale
  stimulus fingerprint and refuses to walk until it is regenerated. The older residual stands too:
  run h2 −2.15 % and ΔSoC +4.8 % against the table's own prediction, with a per-stage residual check
  queued.
- Does the charger lever clear the 0.31 SoC/g `sdp` charge-revisit condition in the η era? The model
  now puts `L_chg` at 0.396396 SoC/g, above that trigger, while `sdp_policy_v4` still rejects charging
  endogenously at α 0.118326. The question is settled by measurement, not arithmetic.
- `ems-y` b00-v3 gate fraction (campaign 20.6 % against walk 12.7 %) — the governor walk can settle it.

## 6. Housekeeping

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
- Commits `dec059b`, `390f554`, `e653e90`, `6702920`, `d70a620`, `a932f83`, `887933f`; campaign B
  launched from `887933f`.

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
