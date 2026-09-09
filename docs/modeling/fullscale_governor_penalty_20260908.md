# The full-scale governor hydrogen penalty: reproduction and attribution

Date: 2026-09-08. Tools: `tools/fullscale_governor/` (README there).
Sources: `references/EMS/SDP_EnergyManagement_Governor3.m`, `references/EMS/sweep_governor_scale.m`,
`references/EMS/matlab_governor_results.jpg`.

## 1. Question

The PhD student's full-scale study reports that the power-share governor costs the SDP energy
management 3 to 16 % of equivalent hydrogen on the UDDS cycle, depending on the governor current
scale S_I. The bench HIL campaigns (B through H) and the offline governor walk report a change of
under 0.1 % for the same class of strategy. This note reproduces the full-scale study in Python,
validates the port against MATLAB, and identifies the mechanism that separates the two results.

## 2. Reproduction

### 2.1 Input

The student's demand file `references/EMS/simulink_pdem_output_UDDS.mat` was supplied on
2026-09-08 (it was absent when this work started). The loader decodes the opaque Simulink
`out.simout` object and resamples it onto whole seconds 0..1369 exactly as `sweep_governor_scale.m`
does; MATLAB's own loader on the same file reports the identical range, -38.3 to +47.9 kW over 1370
samples. Traction energy is 1.82 kWh and regeneration is 43 % of traction.

Before the file arrived a stand-in was built by fitting a road-load model to the shipped stochastic
Simulink cycles (`udds_demand.py`; R^2 0.981, RMS 2.5 kW) and driving it with the UDDS speed trace.
It is kept under `references/EMS/generated/udds_pdem_synth_20260908.*` with provenance. It correlates
with the real demand at 0.954 and carries the same traction energy, but its baseline hydrogen is 14 %
lower (54.33 g against 63.49 g at alpha 200) because the real cycle's power is more peaked. All
results below use the student's file.

### 2.2 Port validation

The port was first validated against the student's MATLAB code (R2024b, `matlab/run_sweep_synth.m`)
on the stand-in demand: every column of both tables agrees to four decimals (`compare_with_matlab.py`,
24 rows, zero mismatches). On the student's own file the port reproduces every value on his published
slide (`matlab_governor_results.jpg`): both baselines, all twelve M_H2,eq values, all twelve SoC RMS
ratios and all twelve closed-loop fractions. One entry on the slide is a transcription slip: the
alpha 200, S_I = 127.8 penalty is printed as +8.82 %, but 69.67 g against the 63.49 g baseline is
+9.73 %, which is what both the port and his own arithmetic give.

### 2.3 Sweep result

Table 2 is the reproduced sweep on the student's demand. His slide values are identical except
where noted in Section 2.2.

Table 2. Governor penalty in equivalent hydrogen, SDP on UDDS (student's demand).

| S_I | Entry [kW] | alpha 200: M_H2,eq [g] | Penalty | SoC RMS ratio | Closed loop | alpha 500: M_H2,eq [g] | Penalty | SoC RMS ratio | Closed loop |
|---|---|---|---|---|---|---|---|---|---|
| baseline | - | 63.49 | - | 1.00 | - | 64.46 | - | 1.00 | - |
| 1.0 | 0.4 | 73.38 | +15.58 % | 1.12 | 76.1 % | 72.51 | +12.48 % | 1.02 | 62.8 % |
| 10.0 | 4.3 | 67.71 | +6.65 % | 1.44 | 65.6 % | 67.40 | +4.56 % | 1.08 | 48.4 % |
| 25.0 | 10.8 | 69.39 | +9.28 % | 1.42 | 40.7 % | 66.42 | +3.04 % | 1.03 | 51.9 % |
| 50.0 | 21.6 | 70.54 | +11.10 % | 1.59 | 33.8 % | 66.57 | +3.27 % | 1.01 | 48.2 % |
| 100.0 | 43.2 | 70.28 | +10.68 % | 1.92 | 18.5 % | 66.97 | +3.89 % | 1.01 | 50.4 % |
| 127.8 | 55.2 | 69.67 | +9.73 % | 2.16 | 12.3 % | 67.50 | +4.71 % | 1.01 | 47.7 % |

## 3. Attribution

`attribution.py` reruns S_I = 1 and 127.8 under four configurations. Table 3 gives alpha 200; the
alpha 500 rows behave the same way.

Table 3. Ablation at alpha 200 on the student's demand. Penalty is equivalent hydrogen versus
the ungoverned baseline of the same configuration.

| Configuration | S_I | Penalty | FC energy change | g H2 per kWh of FC energy | Mean stack efficiency | Samples with FC cut |
|---|---|---|---|---|---|---|
| Baseline (no governor) | - | - | 1.021 kWh | 61.5 | 0.488 | - |
| Default (convex map, 50 kW/s ramp) | 1.0 | +15.58 % | -2.6 % | 71.4 (+16.2 %) | 0.420 | 45.1 % |
| Default | 127.8 | +9.73 % | -8.8 % | 68.2 (+11.0 %) | 0.440 | 52.0 % |
| Ramp limit removed | 1.0 | +10.63 % | +0.6 % | 68.0 (+10.7 %) | 0.441 | 59.2 % |
| Ramp limit removed | 127.8 | +0.81 % | +0.0 % | 62.0 (+0.8 %) | 0.484 | 69.8 % |
| Linear hydrogen map (eta 0.5) | 1.0 | +0.00 % | -5.2 % | 60.0 (0.0 %) | 0.500 | 30.6 % |
| Linear hydrogen map (eta 0.5) | 127.8 | -0.00 % | -2.6 % | 60.0 (0.0 %) | 0.500 | 48.3 % |
| No start cost | 1.0 | +26.31 % | -5.6 % | 77.9 (+28.3 %) | 0.385 | 31.8 % |
| No start cost | 127.8 | +14.30 % | -9.4 % | 70.5 (+16.1 %) | 0.425 | 46.6 % |

Three facts follow.

1. **The penalty is an operating-point effect, not an energy-shift effect.** With a
   constant-efficiency hydrogen map the penalty is exactly zero at every S_I and both alphas, even
   though the governor still moves up to 9 % of the fuel-cell energy onto the battery and cuts the
   fuel cell off the bus for half the cycle. The charge-sustaining correction prices the energy
   shift back exactly, as the student's own header note states. What remains under the convex map
   is the change in grams per kWh: the governed stack runs at a mean efficiency of 0.42 to 0.46
   instead of 0.49.
2. **The stack is off 94 to 96 % of the time.** The SDP policy commands P_fc = 0 on 93.6 % (alpha
   200) and 95.7 % (alpha 500) of samples and runs the stack in short high-power bursts. The
   convex map's parasitic term a0 with shutdown, plus the 0.5 g start cost, makes short
   high-power bursts optimal. Only 28 to 29 % of the commanded share setpoints lie inside the governor's
   band [0.15, 0.85]; the rest are 0, which the setpoint latch answers by cutting the fuel-cell
   switch.
3. **The governor smears the bursts.** Each burst reaches the governor as a step from share 0 to a
   high share, which the latch must release, the slew limiter must ramp at 50 kW/s (0.30 s per
   burst at 46 kW), and the minority clip and the PI stub must settle. The applied fuel-cell power
   averages 12 to 17 kW while on, which is the low-efficiency region of the convex map. Removing
   the ramp limit at S_I = 127.8 collapses the penalty from 9.7 % to 0.8 %; at S_I = 1 the
   closed-loop clip still smears the bursts and 10.6 % remains.

Pre-clipping the setpoint into the band (the `sp_preclip` knob) makes the penalty far worse
(measured at +47 to +80 % on the stand-in demand), because it forces the stack to run
continuously at 3 to 6 kW. This confirms that
the penalty is about where the stack runs, not about whether the governor honours the command.

## 4. Why the bench shows no penalty

The bench study and the full-scale study differ in three ways that each remove the mechanism.

1. **Hydrogen accounting.** Every figure that scores a bench run is linear in stack power. The
   plant's `h2_cum_g` is the Gfc transfer function (`H2Consumption`): four dynamic modes with a
   0.22 s dominant time constant but one constant steady-state gain, `H2_GFC_DC_GAIN_GPS_PER_W`,
   and no idle term. `gen_dp_ems_table.py`, the matched-DP bound and the walk's `h2_g` solve
   against that gain; the walk's and the MPC's online proxy is eta 0.4 constant; the logged
   `h2_sdp_cum_g` is the student's original eta 0.5 proxy. A convex stack map with the student's
   a0 / P_peak / eta_peak form IS implemented for the MPC surrogate (`mpc_ems.py`,
   `--mpc-h2-map convex`), but it is refused unless measured stack coefficients are supplied and
   no campaign or registered leg has ever enabled it. Under a linear map the equivalent-hydrogen
   figure is an identity under any redistribution of the same energy. Table 3's linear-map rows
   are the full-scale study under the bench accounting, and they read zero.
2. **Strategy shape.** The bench SDP policies (`sdp_policy_v4` to `v6`) command shares inside
   [0.15, 0.85] on every cell and never switch the stack off; the registered EMS legs command
   an out-of-band share only in the `ems-y-b00` and `ems-mpc-single` legs. The full-scale SDP
   commands stack-off on 95 % of samples. The setpoint latch, which dominates the full-scale
   result, is almost never exercised on the bench.
3. **Actuator rate.** The full-scale governor re-derives the slew ceiling from a 50 kW/s stack ramp
   placeholder, so a 46 kW burst takes 0.3 s of a 1 s command period to reach. The bench slew
   limit is 0.02 per tick at 1 kHz, which crosses the whole band in 35 ms against a 20 ms command
   period. The bench governor cannot smear a command the way the scaled one does.

The full-scale result is therefore correct within its own model, and it measures the cost of
pairing a bang-bang supervisor with a rate-limited actuator and a latch under a convex fuel map.
It does not measure a property of the governor that the bench could have observed, because the
bench scores on a linear map (its convex map exists only as a never-enabled MPC option) and its
supervisors never issue the bang-bang commands.

## 5. What would make the two studies comparable

- **Same fuel map.** Enable a convex map with an idle term on the bench SCORING side (the
  existing `mpc_ems.py` map covers only the MPC surrogate, and it needs measured a0 / P_peak /
  eta_peak for this stack), or give the full-scale study the linear one. Under the linear map
  both report zero; under the convex map the bench result would depend on how often the bench
  SDP idles the stack, which today is never.
- **Same supervisor shape.** The full-scale SDP's 95 % stack-off duty is the driver of everything
  in Table 3. A stack-on constraint (minimum on-time, or a minimum share when on) would be the
  ordinary engineering fix and would remove most of the penalty regardless of the governor.
- **Real actuator constants.** `P_fc_ramp_W_per_s` and `I_bench_nominal_A` are placeholders in
  the student's file, and Table 3 shows the ramp constant alone moves the S_I = 127.8 penalty
  from 12 % to under 1 %.

## 6. Caveats

- The student's slide carries one transcription slip (Section 2.2); the port's 9.73 % is the value
  consistent with his own grams.
- The governor in the MATLAB is the student's transcription of the fw v25 spec with a PI share
  controller stub. It is not `tools/governor_model.py`, and the fw v26 ceilings and fw v27
  battery-only start are absent from it. The attribution in Section 3 does not depend on those
  differences.
- Nearest-grid SoC snapping (`use_interp = false`) is kept as the student ran it.
