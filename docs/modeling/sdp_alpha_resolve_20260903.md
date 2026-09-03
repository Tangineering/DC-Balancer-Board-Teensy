# The measured-lever alpha re-solve, and the charger disagreement it exposes

Design record for `tools/sdp_policies/sdp_policy_v5.json`, solved 2026-09-03 under operator
ruling item 3 of `WORK_QUEUE.md` §0c: "alpha re-solve: APPROVED on the measured levers (five
readings, alpha ~ 0.134); supersedes 'alpha stays v4'". Decision D14 of
`tools/sdp_ems_solver.py` carries the same argument at the source; this document carries the
numbers.

## 1. Scope

This document covers the derivation of the stochastic-DP EMS objective's SoC-deviation weight
`alpha` from the levers measured on the board, the artifact solved against that weight, the
difference between that artifact and the shipped `sdp_policy_v4.json`, and the consequences
for the scenarios that play an SDP policy. The alpha sweep, the demand map and the transition
probability matrix are outside the scope of this document; they are unchanged.

## 2. The five lever readings and the estimator

A **lever** is an exchange rate in SoC per gram of hydrogen: the SoC that one gram of hydrogen
buys through a given control. The share lever `L_share` is measured as the difference between
the alpha-sweep `cal` and `greedy` legs, which differ only in the commanded share. The charge
lever `L_chg` is measured as the difference between the `cal` and `charge` legs, which command
an identical constant share and differ only in their charge windows. Table 1 lists the five
readings taken since the charger became an energy-conserving converter.

Table 1 — eta-era lever readings, one per campaign, all on the 61 s `ems-sdp` stimulus.

| Campaign | `L_share` (SoC/g) | `L_chg` (SoC/g) | Ratio |
|---|---|---|---|
| `hil_report_20260902_011926` | 0.416880 | 0.332140 | 0.7967 |
| `hil_report_20260902_041414` | 0.416896 | 0.331758 | 0.7958 |
| `hil_report_20260902_220604` | 0.416279 | 0.332947 | 0.7998 |
| `hil_report_20260903_031220` | 0.416317 | 0.333298 | 0.8006 |
| `hil_report_20260903_063659` | 0.416271 | 0.338414 | 0.8129 |
| **Unweighted mean** | **0.4165286** | **0.3337114** | **0.801173** |

The estimator is the **unweighted mean** of the five readings. The choice is stated rather than
fitted. Each reading is one campaign's marginal rate on the same stimulus, and no reading
carries a per-campaign uncertainty estimate that would justify a weighting. A median would
discard the fifth reading, which is the only one that carries the charge lever's drift. The
share lever is repeatable to 1500 ppm of its own mean across the five campaigns; the charge
lever is not, and spans 2.0 % of its mean across the same five (finding F10 of campaign F
quotes 2.1 % across the last four).

The readings are recorded in `EMS_LEVER_ETA_READINGS` in `tools/sdp_ems_solver.py`, and both
means are derived from that table. A sixth reading is one row.

## 3. The arithmetic

Value iteration prices SoC at the discounted shadow price `alpha / (1 - gamma)` grams per SoC,
so a control whose lever is `L` is taken exactly when `L > (1 - gamma) / alpha`. Decision D12
places `alpha` at the geometric mean of the two controls' admission thresholds, which is the
unique weight whose admission bound sits equidistant in log-lever from the two controls:

    alpha = (1 - gamma) / sqrt(L_share * L_chg)

At `gamma_eff` 0.95 and the measured pair,

    alpha = 0.05 / sqrt(0.4165286 * 0.3337114)
          = 0.05 / 0.372827497
          = 0.134110280093

The admission bound this weight implies is 0.372827 SoC/g, and the shadow price is 2.682206
g/SoC. The measured admission window — the open interval of `alpha` that admits the share lever
and rejects the charge lever — is

    ( 0.05/0.4165286 , 0.05/0.3337114 ) = ( 0.120040 , 0.149830 )

The shipped `sdp_policy_v4.json` weight, 0.118326398, lies **1.43 % below the lower edge** of
that window. Below the lower edge means the measured share lever does not clear the bound, so
the SoC axis is under-priced. That is the defect the re-solve corrects, and `sdp_policy_v5.json`
is the first SDP artifact whose `alpha.admission.in_window_measured` is `true` rather than null.

## 4. The model window rejects the same weight

The solver bills a charge stage from its own model constants: an amp delivered to the pack
costs `V_pack / eta_chg` watts on the bus, so the modelled charge lever is exactly
`eta_chg * L_share_model` = 0.88 * 0.450450 = 0.396396 SoC/g. The modelled admission window is
therefore

    ( 0.05/0.450450 , 0.05/0.396396 ) = ( 0.111000 , 0.126136 )

and 0.134110 sits **6.3 % above its upper edge**. The two windows overlap only on
(0.120040, 0.126136).

The disagreement is not numerical noise. The board measures the end-to-end charge round trip at
`L_chg / L_share` = **0.801173**, where the model asserts `ETA_CHG` 0.88 — a 9.0 % optimism.
The mechanism was identified when the first eta-era reading was taken: the bus falls from
15.76 V to 14.15 V during a charge window, and that sag is billed to the charge leg because it
raises the fuel-cell cost of every amp the vehicle also draws. The plant models the converter,
not the sag's effect on the accounting.

## 5. What the disagreement does to the solved policy

The stage cost is built from the **model** constants while `alpha` is priced on the **measured**
pair. An alpha of 0.134110 prices SoC above the model's charge lever, so the optimizer admits
charging. Measured, not argued: `sdp_policy_v5.json` asserts `charge_goal` in **558 of 2525**
cells, `actions.forbid_charge_all` is false, and the admission is therefore endogenous. The
shipped v4 artifact asserts it in none.

This is the same class of incoherence that decision D12 was written to correct, arrived at from
the other side. In D12 the weight came from a derivation the charge action had never been
checked against; here it comes from a lever pair the solve itself does not use.

Two resolutions are coherent, and the choice belongs to the operator.

- Solve at the measured round trip, `--eta-chg 0.801173`. The same alpha then lies inside both
  windows — the model window becomes (0.111000, 0.138547) — and the charge map is empty again.
  Verified by solve: 0 charge cells, no tripwire override required. The cost is that the
  artifact's `charger.eta_chg` no longer equals `hil_electrical.ETA_CHG`, so `SdpStrategy` prints
  its charger-era mismatch banner on every run that plays the artifact.
- Accept the charge admission as the measured economics' verdict. The cost is that five
  campaigns measure the charge leg 3.4 % to 4.1 % worse in equivalent hydrogen than the
  charge-free calibration, so this knowingly demotes the benchmark.

Neither resolution is taken in this round.

## 6. v4 against v5

Both artifacts carry 101 SoC nodes and 25 demand bins on an identical SoC grid, and both were
solved against the same transition matrix, the same 0 to 25 W demand map and the same
`eta_chg` 0.88 charger. Table 2 states the difference.

Table 2 — `sdp_policy_v4.json` against `sdp_policy_v5.json`.

| Quantity | v4 | v5 |
|---|---|---|
| `alpha.mode` | `lever` | `lever-measured` |
| `alpha.value` | 0.11832639757736393 | 0.13411028009327516 |
| `in_window_model` | true | **false** |
| `in_window_measured` | null (undecidable) | **true** |
| Charge cells | 0 | **558** |
| Policy-block sha256 | `8ca7dcee…` | `1644f6e4…` |

The **share** map differs on exactly three SoC rows — 3, 4 and 5, at SoC 0.553 to 0.555 — for
56 differing cells of 2525. Those rows sit 45 to 47 grid nodes below the target node 0.600. The
widest trajectory in the suite spans the target plus 0.013 down to the target minus 0.019, so
no scenario reaches them. The share half of every walk-derived expectation would therefore
transfer verbatim, exactly as it did across the v3-to-v4 rebinding.

The **charge** map does not. It differs on 47 rows and 558 cells, and **40 of those rows lie
inside** the plus-or-minus 0.040 reachable band around the target node. v5 asserts `charge_goal`
in every admissible bin (0 to 11) at every SoC row strictly below the relative target, that is
rows 3 to 49. Every `ems-sdp` family trajectory descends below its captured `soc0` on the first
decision, so a run on v5 would command `FC_CHARGE` for effectively the whole run.

Both claims are pinned by `test_sdp_v4_v5_share_maps_agree_on_traversed_rows()` in
`tools/test_hil_plant_sim.py`. A failure of the share half means the two artifacts now differ
where runs go. A failure of the charge half means the charger disagreement has been resolved
one way or the other, and this document must be re-read before anything is rebound.

## 7. What moved, and what did not

`sdp_policy_v5.json` is registered as `sdp-v5` in `tools/hil_plant_sim.py` with
`frontier_eligible: False` and a role note. `sdp_policy_v4.json` keeps `frontier_eligible: True`
and remains the frontier leg. `sdp_policy_v4.json` was not modified; every campaign's provenance
still resolves.

**No scenario was rebound.** The default in the implementer brief was that every `ems-sdp*`,
`ems-ftp75-sdp`, `ems-ftp75c-sdp` and `alpha-cal` leg move to v5, on the condition that the map
diff shows no traversed-row difference. Section 6 shows a traversed-row difference on the charge
axis, so the condition fails and the transfer is not made. Consequently:

- **No expectation was re-walked**, and none needed a `provisional_note`. Every walk-derived
  expectation on the SDP legs still describes the artifact those legs play.
- `ems-sdp-cross` and `ems-sdp-braking` were never candidates. They are bound to `sdp-v2`, the
  byte-frozen dynamics demonstration, precisely because they exist to actuate a charge threshold.
- `ems-sdp-alpha-cal` plays a sweep pick resolved from `sweep_20260902_eta088/live_picks.json`,
  not a registered artifact path. Moving its anchor is a sweep re-run, not a registration edit,
  and it is deferred with the rebinding.

**No matched-DP record went stale.** The record key (`KEY_FIELDS` in `tools/dp_results_db.py`,
and `DP_FINGERPRINT_META_KEYS` in `tools/hil_plant_sim.py`) is built from the scenario's
stimulus, its charger and its loss model. No SDP policy file, alpha or strategy name
participates in it, because the DP bound is a property of the problem and not of the strategy
being compared against it. The 37 stored records are reachable unchanged.

`tools/sdp_alpha_sweep.py` needed no change: `--anchor-artifact` already rebinds both
`ANCHOR_ARTIFACT` and `ANCHOR_ALPHA`, reading the alpha off the named artifact. Verified against
v5, which enters the grid at index 8 with `in_model` false and `in_meas` true.

## 8. The solver change

`--alpha-mode lever-measured` applies the geometric-mean placement of decision D12 to the
measured lever pair instead of the modelled one. It takes `--lever-share`, `--lever-chg` and
`--lever-source`, all optional; the defaults are the two means of Table 1 and a provenance string
naming the five campaigns. The three flags are refused under any other mode, so a reader can
never be left believing that the measured pair priced an artifact that the model constants
priced.

The mode records the measured pair as a **measurement**, not as the old-era projection that every
previous mode carries: `charge_measured_is_projection` is false, `window_measured` and
`in_window_measured` are real, the readings that were averaged are published under
`measured_readings`, and `measured_round_trip` carries the 0.801173 ratio. Under an explicit
`--lever-*` pair the readings list is omitted and `measured_source` carries the caller's own
string, because the built-in table is then not what was averaged.

The pre-solve admission tripwire is unchanged and **fires** on the briefed solve: the model
window rejects the weight, so `sdp_policy_v5.json` required `--allow-out-of-window`. The refusal
message names both resolutions of section 5 with their numbers. The exact command is recorded in
the artifact's own `argv` and is

    C:/Users/ricky/miniforge3/python.exe tools/sdp_ems_solver.py \
        --eta-chg 0.88 --alpha-mode lever-measured --allow-out-of-window \
        --out tools/sdp_policies/sdp_policy_v5.json --force

Every pre-existing mode is unchanged. Regenerating `sdp_policy_v4.json` with its recorded argv
reproduces policy-block sha256
`8ca7dceeeaeb16257aa18eb889d3d76df38dbe10ea94e8574249984c078fd770`, which is the shipped file's.
The regeneration differs from the shipped file only in `generated_utc`, `argv`, the
`actions.share_ladder` float representation and the `alpha.rationale` prose — all four of which
predate this round and are recorded at the `ALPHA_DERIVATION` note. A before-and-after
regeneration across this round's edits differs in `generated_utc` and `argv` alone.

## 9. Deferred

- The operator ruling on section 5: solve at the measured round trip, or accept the charge
  admission. Nothing else in this document can be closed before it.
- Rebinding the SDP legs, and re-walking their expectations with `tools/ems_walk.py`, once that
  ruling lands. Both are campaign-time work.
- Moving the alpha sweep's anchor and its `live_picks.json` onto the ruled artifact, which is a
  sweep re-run.
- The charge lever's 2.1 % spread over campaigns C to F is itself unexplained and was carried as
  finding F10 of campaign F. A sixth reading is one row of Table 1, and it moves this alpha.
