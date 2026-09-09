# Handoff: H-20 convex hydrogen map (branch `h20-convex-h2-map`, merged to main 2026-09-09)

For the overnight orchestration session. This document is the trigger and the checklist for
the phase-B tooling round that must precede the next HIL campaign. Read it before launching any
campaign: **every hydrogen anchor, band, lever price and matched-DP record in the repository is
on a retired axis until phase B completes.**

## 1. What changed (phase A, done)

The bench tooling's scored hydrogen model moved from the linear full-size Gfc DC gain
(`H2_GFC_DC_GAIN_GPS_PER_W`, 1.7638e-5 g/s/W) to a convex map derived from the Horizon H-20
brochure (`tools/h2_map.py`, design note `docs/modeling/h20_hydrogen_map_20260908.md`):

    rate(P_stack) = A0 + K_FARADAY * I(P_stack)
    A0 = 6.633e-5 g/s (purge + blower + controller, constant while the stack is in service)
    K_FARADAY = 1.358e-4 g/s per A (13 cells), I(P) from the brochure U-I curve
    P_MAX = 23.416 W stack-side (1.247 A bus-side): controls above it are INFEASIBLE

Operator decisions (2026-09-08): constant-offset loss model; no stack shutdown state (the hook
`h2_map.SHUTDOWN_ENABLED` exists, default off); Gfc kept as a documented, unscored column
(`h2_gfc_cum_g`, `gfc_*` fields); the electrical `FuelCellSource` refit is a separate round.

Wired into: the plant's scored `h2_cum_g` (gated on the board's `FC_REG_ENABLE` mirror), the DP
generator stage cost and table header (`# h2_map:` fingerprint line, saturation infeasibility and
census), the SDP solver stage cost (stack-side now, `--h2-map {h20, eta-proxy}`), the walk (inherits),
the MPC stage cost (`h2_map="h20"` default; terminal price re-based, provisional), the DP results
key (`h2_map` field), and `hil_report_analysis` matched-DP regen pricing. Era switches:
`gen_dp_ems_table.py --h2-map {h20, gfc-linear}`, `sdp_ems_solver.py --h2-map {h20, eta-proxy}`;
archived tables and policies regenerate byte-for-byte under the legacy flags.

The three committed DP tables under `tools/dp_tables/` were regenerated under the H-20 law with
their own recorded command lines (lambda_term 2.855 / 2.108 / 1.695 g/SoC). Test suites at merge:
see the commit message for the counts.

## 2. Why campaigns must wait for phase B

- `run_hil_suite.py` hydrogen expectation bands (every `*_h2_accounted`, walk-derived band, and
  the EMS frontier arithmetic) are stated against the retired map. A run on the new map will
  FAIL them for the wrong reason.
- `EMS_EQ_H2_LAMBDA_SOC_PER_G` (0.41) and the levers `L_share`, `L_chg` were measured in Gfc grams.
  In H-20 grams the share lever is roughly 0.57 SoC/g at the rig median (provisional estimate).
- `tools/dp_db/` matched-DP records are unreachable by design (the key gained `h2_map`).
- The SDP policies `sdp_policy_v4..v6` were solved on the eta-proxy law; under the H-20 law their
  configurations admit charge cells (v6: 46 of 2525) because alpha is calibrated at
  k = 1/(0.5*Q_LHV) while the H-20 marginal at the operating point is ~1.28e-5 (SoC term ~31 %
  over-weighted). `--alpha-mode` prints a warning until re-derived.
- The plant bills A0 from State 0; the DP/walk bill the Run window only. Whole-run `h2_cum_g` and
  Run-window figures differ by A0 * t_run_entry (~1.7 mg on a 16.5 mg ems-sdp run). Suite bands
  must be stated on the Run-window figure (`h2_run_g`).
- A0 is 63 % of the rate at the rig median and ~56 % of an FTP-75 total: inter-strategy differences
  are small relative to the constant; the frontier's same-config noise floor must be re-measured.

## 3. Phase-B checklist (orchestrated tooling round, in this order)

1. **Lever prices.** Re-measure `L_share` and `L_chg` on the H-20 axis from the regenerated DP
   tables and walks (the 2026-09-01e procedure), then set `EMS_EQ_H2_LAMBDA_SOC_PER_G` and its band.
2. **SDP v7.** Re-derive alpha on the H-20 marginal (stack-side basis, `--h2-map h20`), solve
   `sdp_policy_v7`, run the certificate; decide the frontier SDP. Then `H2_BASIS_REF_P_STACK_W`
   and `ALPHA_MISMATCH_REF_P_STACK_W` (3.2 / 3.0 W design estimates) get calibrated or retired.
3. **Charge admission.** The H-20 ceiling makes FC-only charging plus traction infeasible on
   1010 of 2525 default SDP cells (charger ~20 W into the pack). Re-examine `charge_mask()`,
   `chg_a`, and the charge-window scenarios (`charge-cruise`, `charge-to-full`, `mppt-tracking`)
   against the 23.4 W stack ceiling.
4. **Matched-DP records.** Re-solve `tools/dp_db/` (all 75) under `h2_map`; the drain-membership
   witness and fingerprint discipline are unchanged.
5. **Suite bands.** Re-walk every EMS leg with `ems_walk` (governor on, M2 split law, plant loss
   map, now on the H-20 map) and re-state the bands on Run-window hydrogen; re-pin the frontier
   references; re-measure the same-config floor.
6. **MPC.** Re-run Gate 1 and the offline rolls with `h2_map="h20"`; confirm the terminal price
   after item 1.
7. **`hil_report_analysis`.** The matched-DP regen bound now prices at the map's marginal
   (`price_gps_per_w`); the report text branches on the record's `h2_map` field. Verify on one
   fresh campaign folder.
8. **FuelCellSource refit** (separate plant-physics round, after the campaign): fit
   `hil_electrical.FuelCellSource` to the brochure U-I curve (13 cells; today 12 cells and a
   flat 12.5 V curve). This changes bus voltages, bring-up and every electrical anchor; the map's
   own I(P) inversion is deliberate until then (two curves for one stack, documented in the
   design note §6).

## 4. Where to look

- Design note: `docs/modeling/h20_hydrogen_map_20260908.md` (§7 phase-B list, §9 fix-round
  measurements).
- Plant doc: `docs/HIL_PLANT.md` §9.3a (H-20, scored) / §9.3b (Gfc, retained).
- Map module: `tools/h2_map.py`; tests `tools/test_h2_map.py`.
- Full-scale governor study that motivated this: `docs/modeling/fullscale_governor_penalty_20260908.md`.
