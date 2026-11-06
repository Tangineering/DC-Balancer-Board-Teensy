# fw v35 -> v37 rev 2: noise before/after, like-for-like (label: beforeafter)

## 0. Bottom line
- **Same cycle, same plan.** v_setpoint matches in bag time: RMS difference 0.35 mm/s and max 14 mm/s over 167 s. The cycle runs from about 55.8 s to 160.3 s in both bags. The SDP share sequence is nearly identical: 87 share-command changes in each run while moving, at the same instants. Every moving tick is `switch_state` 0x27; 0x26 occurs only at standstill.
- **The 1x line fell on every channel, including share.** Measurement: 7 paired steady chunks, 24.7 s per run, 1.95-2.72 m/s, 0x27, `power_share_cmd` 0.16, purges and share steps excluded.
  - I_tot 1x: 0.26 / 0.26 / 0.20 x
  - V_bus 1x: 0.38 / 0.27 / 0.27 x
  - own share 1x: 0.23 / 0.31 / 0.21 x
- **"Share did not drop" comes from the window, not the loop.** Over all moving 0x27 ticks, share HP>0.7 Hz goes 0.073 -> 0.063 (0.86x). With purges and commanded share steps excluded, it goes 0.042 -> 0.020 (0.48x). H-20 purges and SDP share steps are about 90 % of the after-run share HP variance (67 % before), and v37 does not touch either.
- **The drop is larger than the design predicts (0.20-0.26x measured vs |C*S| 0.28-0.30x).** The controller part matches: |C| ratio 0.34, measured |I_tot 1x / v 1x| ratio 0.33-0.37. The extra reduction comes from a smaller v_actual 1x disturbance than the |S| change predicts (section 2).
- **Tracking cost.** Lag of v_actual behind v_setpoint went 0.34 -> 0.60 s. Speed error below 0.7 Hz doubled (5.0 -> 9.8 mm/s).

## 1. Matched 1x / broadband table

**Method.**
- Lock-in on a tracked phase: phi = 2*pi*integral(2.089 * v_ref) dt, with v_ref = 1 s mean of v_actual. Hann window and linear detrend.
- Background = median lock-in at the off-orders 0.6, 0.8, 1.3, 1.6, 1.75, 2.6 and 2.8.
- Broadband = HP > 0.7 Hz RMS after a least-squares removal of orders 1, 2, 2.31 and 3.
- Data mask: purges ±0.5 s (V_fc dips > 1 V below a 5 s median: 20 before, 18 after); share steps > 0.02 excluded ±0.3 s; |dv_sp/dt| < 0.15 m/s²; I_tot > 0.3 A.
- Telemetry: max(diff(t)) 21.4 / 22.0 ms, so there are no gaps. The background correction changes no ratio by more than 0.03.

| channel | 1.95 m/s (4.1 Hz) 1x B -> A | 2.15 m/s (4.5 Hz) | 2.70 m/s (5.6 Hz) | broadband B -> A (2.15 m/s) |
|---|---|---|---|---|
| I_tot A | 0.233 -> 0.061 (0.26) | 0.225 -> 0.058 (0.26) | 0.222 -> 0.045 (0.20) | 0.072 -> 0.053 (0.74) |
| I_fc A | 0.038 -> 0.010 (0.27) | 0.033 -> 0.012 (0.36) | 0.036 -> 0.007 (0.20) | 0.021 -> 0.017 (0.81) |
| I_batt A | 0.213 -> 0.055 (0.26) | 0.202 -> 0.051 (0.25) | 0.187 -> 0.038 (0.20) | 0.057 -> 0.039 (0.68) |
| V_bus mV | 10.3 -> 3.9 (0.38) | 14.6 -> 4.0 (0.27) | 16.6 -> 4.5 (0.27) | 11.6 -> 8.6 (0.74) |
| share | 0.063 -> 0.015 (0.23) | 0.043 -> 0.014 (0.31) | 0.010 -> 0.002 (0.21) | 0.020 -> 0.014 (0.69) |
| droop_BT gain (x1e-3) | 95 -> 15 (0.16) | 61 -> 14 (0.22) | 6.8 -> 0.8 (0.12) | 15 -> 7 (0.48) |
| v_actual mm/s | 24.3 -> 12.6 (0.52) | 20.1 -> 14.2 (0.71) | 16.8 -> 10.1 (0.60) | 11.6 -> 7.5 (0.65) |

- **Chunk counts.** The bins hold 1 / 4 / 2 chunks (2.9 / 12.1 / 9.7 s). No matched steady chunk exists below 1.5 m/s.
- **Other lines.** 2x and 2.31x fell 0.3-0.8x and are at most 0.03 A after.
- **Quantization floors are not limiting.** In rms: I channel 2.3 mA, I_tot 3.3 mA, V_bus 1.3 mV, share about 0.0028 at 0.7 A.
- **Units.** `droop_FC` / `droop_BT` in the bag are Q16 gains (`droop_gain_*_actual` = k_d/(RE_MAX*r) x 65535), not 0-4095 MDAC codes. Figures: `beforeafter_matched_order_spectra.png`.
- **Broadband by band.** Over the matched moving mask, purges interpolated and 0.5 s erosion (27 s), the falls are:
  - I_tot: 2-6 Hz 0.33x, 6-12 Hz 0.73x, 12-24.5 Hz 0.54x
  - share: 0.38x, 0.60x, 0.52x
  - v_actual 12-24.5 Hz 0.57x

  The folded HF band fell in every channel. This is consistent with the lower |C| at high frequency (inferred, not separated).

## 2. Is it the controller, or did the disturbance change?
**Design comparison**, interpolated from `controller_design_MIMO/drive_siso_metrics.txt` (rotation-band table and the |S| ladder):

| v (f) | design |C| ratio | design |S| ratio | design |C*S| ratio | measured I_tot 1x | measured v_actual 1x | implied disturbance ratio |
|---|---|---|---|---|---|---|
| 1.95 (4.07 Hz) | 0.345 | 0.883 | 0.304 | 0.26 | 0.52 | 0.59 |
| 2.15 (4.49 Hz) | 0.345 | 0.858 | 0.296 | 0.26 | 0.71 | 0.83 |
| 2.70 (5.64 Hz) | 0.339 | 0.835 | 0.283 | 0.20 | 0.60 | 0.72 |

- **Bus-side gain |I_tot 1x / v_actual 1x|, per-chunk median.** Before: 9.6 / 11.1 / 13.6 A per (m/s). After: 4.9 / 3.6 / 4.5. The ratios are 0.51 (one chunk) / 0.33 / 0.33, which matches |C_new/C_old| = 0.34. The phase is 136-144 deg in both runs (|C| phase was 133-146 deg).
- **The board runs the new law,** consistent with ML0226 (planning section 10.3: 0.40 / 0.31 / 0.30 at equal disturbance; bus 1x 29-61 mA). The in-bag after values are 45-61 mA.
- **The pre-loop disturbance looks smaller after.** v_actual 1x = |S|*d for both measurement-artefact and force disturbances. The measured v ratio (0.52-0.71) is below the |S| ratio (0.84-0.88), so d is about 0.6-0.8x of before.
- **The before disturbance was stable across four bags.**
  - 10-26: 16-20 mm/s at 1.5-3.0 m/s
  - 10-28 pre-fault: 15-20
  - 10-29 pre-fault: 15-21
  - 10-30: 17-24
  - 11-05: 10.6-14.5

  Confidence that the disturbance changed: moderate. There is only one after-bag, 1-4 chunks per bin, and |S| comes from the nominal plant, whose 72-corner family spans up to 0.50x at 2.1 Hz. Whether something mechanical changed between 10-30 and 11-05 is unknown; ML0226 found the August bad tooth gone on 11-04.
- **Extra before-evidence (`beforeafter_1x_vs_speed.png`).** I_tot 1x was 0.20-0.24 A at 1.5-3.0 m/s in all four pre-v37 bags, including the battery-only 10-26 bag. The 1x level does not depend on the share loop.
  - Firmware bounds: 10-26 is fw <= v31a. 10-28 and 10-29 are fw <= v35, using spans up to 3 s before the OC_FC latch at 229 s.
  - 10-26 (single source) shows V_bus 1x of 33-38 mV for the same 0.22 A, against 12-18 mV with both sources on the bus.

## 3. Operator claims: confirmed or refuted
- **V_bus 1x went down: confirmed,** 0.27-0.38x.
- **Share 1x did not drop: refuted under matched conditions** (0.21-0.31x). The claim is reproduced only on unmasked windows (0.86x), because purges and SDP share steps (0.16 <-> 0.84) dominate share HP variance.
- **The quick-scan "share 2-6 Hz up 0.029 -> 0.044" is a window artefact.** Its ≥512-sample runs were 1 run / 60.5 s before against 3 runs / 93.3 s after, with purges and steps inside. Excluding purges alone gives 0.0247 -> 0.0239.
- **What went up:**
  - LF tracking error (section 4).
  - v_actual 0.1-0.7 Hz: 1.07-1.13x.
  - V_bus 0.1-0.7 Hz on the steady mask: 2.5 -> 3.4 mV (1.35x), plausibly from the slower speed loop moving the load at LF.
- **The quick-scan LF increases are window artefacts:**
  - V_bus 0.1-2 Hz: with purges excluded it is 4.35 -> 3.72 mV.
  - `droop_BT` LF: matched band ratio 0.89-0.93.
- **Remaining share 1x depends on the operating region.** The FC response to the I_tot ripple, δI_fc/δI_tot, depends on the k_d schedule region. At I_tot 0.65-0.73 A (below the 0.755 A k_d crossover) the FC part lags by 31-75 deg, and share 1x = 0.007-0.018 after (0.030-0.063 before). At 0.88-0.92 A (k_d = K_DROOP) the lag is -1 to 17 deg and share 1x = 0.0014-0.0027. The linear phasor model (δI_fc - s δI_tot)/I_tot reproduces share 1x to within 10 % per chunk.
- **The droop_BT gain modulation (the share controller's output) follows the same split.** It is 47-95e-3 before (11-17e-3 after) in the scheduled region, against 6-7e-3 (0.7-0.9e-3) above it.
- **Hypothesis, unverified: the load-scheduled k_d is modulated at 1x.** Its input `share_govTotAFilt` (`SHARE_GOV_FILT_ALPHA` 0.05, about 20 ms) passes a 4.5 Hz ripple at about 0.87 gain. That is more than the `SHARE_KD_HYST_A` 0.05 A hysteresis at both the v35 and the v37 ripple amplitude, so k_d is re-targeted every half cycle, and k_d changes the split through the ΔV0 offsets. Region and ripple size are confounded in the bags, so they cannot separate this from droop/plant dynamics.

## 4. Tracking cost in the bag (drive window 56-161 s, 105 s)
| | before | after |
|---|---|---|
| lag of v_actual behind v_sp (xcorr) | 0.34 s | 0.60 s |
| RMS error, all | 19.1 mm/s | 18.2 |
| LF (<0.7 Hz) RMS error | 5.0 | 9.8 (1.96x; HIL ems-drive-cycle gave 1.9x) |
| accel phase (dv_sp/dt > 0.15, 11.3 s) | 22.5 RMS, mean -8.0 | 36.2, mean -15.9 |
| steady (79.7 s) | 17.8 | 13.9 (1x removed) |
| max error after ramp ends (4 ends) | 31-39 | 27-34 |
| final stop (160.3 s) min error | 0 | -48 |

- Overshoot did not grow on this ramp cycle.
- The −48 mm/s undershoot at the final stop is one event; it echoes the HIL brake-target undershoot item.

## 5. Freeform
- **Speed-matched non-order lines are present in all three dual-source bags (10-28, 10-30, 11-05).** At about 2.7 m/s, lines at 9.9-13.6 Hz reach 50-124 mA in 2.56 s windows, for example 10.0 Hz at t ≈ 137 s in every bag (37 -> 59 mA in the matched chunk). They are not 1x/2x/2.31x/3x and v37 did not reduce them. Probably folded HF content locked to speed (VESC electrical or tire; origin unknown, low confidence). Candidate for the share-spectrum agent; sub-20 ms analysis needs a 1 kHz BLG.
- **Single-source operation has about 2.2x the V_bus 1x per ampere of dual-source operation** (10-26).

## 6. Unverified / limits
- There is one after-bag. Bins below 1.5 m/s are empty under the matched steady criteria.
- |S| and |C*S| are nominal-plant figures.
- The firmware identity of the bags is bounded by date and diff only, as the brief describes; I did not re-run `git diff`.
- The k_d-modulation mechanism is a hypothesis.

## 7. Files
- `docs/reviews/noise_fw37_2026-11-05/figs/beforeafter_matched_order_spectra.png`
- `docs/reviews/noise_fw37_2026-11-05/figs/beforeafter_1x_vs_speed.png`
- Scripts: `C:/Users/ricky/AppData/Local/Temp/claude/3fe373bc8dcb48b3/e5f4c966-cfe4-4b0f-849e-8303e1628832/scratchpad/beforeafter/`
  - `lock2.py`: run as `lock2.py 0.15 125 1`
  - `budget.py`, `allruns.py`, `frac.py`, `track.py`, `figs.py`

## Adversarial verification (data and physics lenses)

- [C1] Under matched conditions the I_tot 1x line fell to 0.26/0.26/0.20x of fw v35 at 1.95/2.15/2.70 m/s, below the design |C*S| ratio 0.30/0.30/0.28.
   data: PARTLY -- Under matched conditions (0x27, cruise), the I_tot 1x flywheel line fell to about 0.24x of fw v35. Window scatter is about ±0.04 and there is no resolvable speed dependence. Measured values are 0.223 to 0.053-0.055 A at 2.2 m/s, about 0.216 to 0.051 A at about 1.85 m/s, and about 0.221 to 0.052 A at 2.7 m/s. This is below the design rotation-band |C*S| ratio of 0.28-0.30 at 4.1-5.6 Hz. The per-bin values 0.26/0.26/0.20 are within noise of 0.24 and should not be read as a trend.
   physics: PARTLY -- Under matched conditions (0x27, cmd 0.16, 7 paired chunks, 24.7 s per run), the I_tot 1x line fell to 0.26/0.26/0.20 of fw v35 at 1.95/2.15/2.70 m/s. This is consistent with the drive-law |C*S| design ratio (0.30/0.30/0.28 nominal) combined with a 17-28 % smaller once-per-rev source amplitude in the 11-05 run, which the v_actual 1x tone shows. Corrected for that source change, the controller-attributable reduction matches the design to within about 0.01 at 2.15 and 2.70 m/s. The 1.95 m/s bin res
- [C2] The controller part of the reduction matches the design: the bus-side gain |I_tot 1x / v_actual 1x| fell from 11.1/13.6 to 3.6/4.5 A per (m/s) at 2.15/2.70 m/s (ratio 0.33), equal to |C_new/C_old| 0.34. The extra reduction comes from v_actual 1x falling 0.60-0.71x against a predicted |S| ratio of 0.84-0.86, i.e. a disturbance about 0.7-0.8x smaller.
   data: PARTLY -- The controller part of the reduction matches the design. The bus-side |I_tot 1x / v_actual 1x| fell from about 11-12 and 13-15 A/(m/s) to about 3.6-6 and 4.5-5 A/(m/s) at 2.0-2.5 and 2.5-3.0 m/s. That is a ratio of 0.30-0.39 depending on the estimator, consistent with the model |C_new/C_old| of 0.34. In addition, v_actual 1x fell to 0.60-0.76x of its v35 level. In each speed bin it is below the spread of every pre-v37 run (19.6-21.9 and 15.2-18.8 mm/s). The model |S| ratio is 0.84-0.86, so the 1
   physics: PARTLY -- The controller part is confirmed. The bus-side 1x gain |I_tot/v_actual| fell from 11.1/13.6 to 3.6/4.5 A/(m/s) in the 2.0-2.5 and 2.5-3.0 m/s bins, a ratio of 0.325-0.328. This matches the design |C_new/C_old| of 0.34-0.35 at 4.6/5.6 Hz to within about 4 %. v_actual 1x fell 0.63-0.72x against 10-30 (0.69-0.73x against the pooled pre-v37 bags). The nominal |S| ratio predicts 0.84-0.85x. That leaves an unexplained 0.76-0.86x residual, which is within the 72-plant |S| spread (about 15 %) and rests 
- [C3] Share 1x did fall (0.23/0.31/0.21x); the operator's 'no reduction' is reproduced only on unmasked windows. There share HP>0.7 Hz is 0.073->0.063 (0.86x), against 0.042->0.020 (0.48x) once H-20 purges and SDP share steps are excluded.
   data: PARTLY -- The share's 1x flywheel component did fall from fw v35 to v37: 0.54x unmasked and 0.44x with purges and steps masked (share-lock-in RMS 0.032->0.017 and 0.030->0.013). That is a smaller fall than the claimed 0.21-0.31x. Broadband share HP>0.7 Hz is unchanged or slightly up without masking (0.064->0.071, 1.11x per-bag; 0.86x only under the matched mask) and unchanged with purges alone excluded (0.98x). It falls about 0.5-0.7x (0.48x matched mask, 0.67x per-bag contiguous Welch on only 13 s of bef
   physics: CONFIRMED -- The share 1x flywheel line did fall with fw v37, to about 0.2-0.3x of fw v35 (0.23/0.31/0.21x by speed bin; 0.12-0.28x under other gating). That is the same fall as the I_tot 1x (0.20-0.26x), which fits the split law carrying the total-current ripple into the share. On unmasked matched 0x27 windows, the share HP > 0.7 Hz RMS falls only 0.073->0.063 (0.86x). The reason is that H-20 purge transients and SDP share-step responses, which do not depend on the drive law, dominate that variance. With pu
- [C4] Remaining share 1x depends on the k_d-schedule region. Below the 0.755 A crossover (I_tot 0.65-0.73 A) δI_fc lags δI_tot by 31-75 deg and share 1x is 0.007-0.018 (after). At 0.88-0.92 A (k_d=K_DROOP) the lag is -1 to 17 deg and share 1x is 0.0014-0.0027; droop_BT gain 1x is 11-17e-3 vs 0.7-0.9e-3.
   data: PARTLY -- In the after bag, the remaining share 1x is about 3x larger in steady cruise chunks with I_tot under about 0.76 A (median 0.012, at v 1.9-2.2 m/s) than in chunks at 0.85-0.98 A (median 0.004, at v about 2.7 m/s). In the low-I_tot chunks, δI_fc tends to lag δI_tot, with a median of about 40 deg but a range of -7 to 75 deg and ±15-45 deg error per window. Above 0.85 A it is near in-phase, at -18 to 21 deg. droop_BT 1x drops by about 10x over the same split.

The same pattern is present in fw v35. 
   physics: PARTLY -- Remaining share 1x tracks the k_d-schedule region in this sample. Below the 0.755 A filtered-total crossover (I_tot 0.66-0.73 A), k_d ∝ 1/I_tot_filt. There δI_fc LEADS δI_tot by 31-75 deg (after), share 1x is 0.007-0.018 and droop_BT 1x is 11-17e-3 of full scale. At 0.90-0.92 A, where k_d is flat at K_DROOP and the after-bag ripple never crosses back under 0.755 A, the phase is -1 to 17 deg, share 1x is 0.0014-0.0027 and droop_BT 1x is 0.7-0.9e-3. The linear model reproduces share 1x within 6 %.
- [C5] The v37 tracking cost is visible in the bag: lag of v_actual behind v_setpoint 0.34 -> 0.60 s, LF (<0.7 Hz) speed-error RMS 5.0 -> 9.8 mm/s, and accel-phase RMS error 22.5 -> 36.2 mm/s. The ramp-end overshoot did not grow (27-34 vs 31-39 mm/s).
   data: PARTLY -- The v37 tracking cost shows in the bag as a larger low-frequency and ramp-phase error, but not as a large lag. Over the drive window, the RMS of the 0.7 Hz LP speed error rose from 5.0 to 9.8 mm/s (5.3 -> 10.0 with an independent window). The accel-phase RMS error rose from 22.5 to 36.2 mm/s (23.9 -> 36.8 with an independent mask), and the mean accel-phase error doubled from -8 to -16 mm/s. Ramp-end overshoot did not grow (31-39 mm/s before, 27-34 mm/s after). Steady-cruise speed-error RMS fell 
   physics: PARTLY -- The fw v37 tracking cost is visible in the bag. The tracking lag behind v_setpoint roughly doubles: about 38 -> 76 ms on accelerations and 25 -> 44 ms on decelerations, from ramp error over acceleration at 0.21 m/s^2; the least-squares delay is 20 -> 40 ms. That ratio is consistent with 1/w_c going from 63 ms (15.98 rad/s) to 153 ms (6.55 rad/s). The 0.34 -> 0.60 s cross-correlation lag is an artefact of a nearly flat correlation peak (within 0.1-0.3 %) and should not be quoted. The RMS of the e