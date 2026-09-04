# Low-current power-share stability: what filtering can and cannot buy, and the other levers

Exploration note, 2026-09-03. No firmware change. Sources: `teensy_controller.ino` (fw v26 governor
block, lines 2240–2360 and 10400–10640), `docs/share_sweep_whitepaper/main.tex` (sections on
TP0016/TP0017, the W-profile boundary, "The floor law, revisited", conclusions items 11 and 17),
`controller_design/system_model.md` sections 3, 5, 6e, `docs/HIL_PLANT.md` section 4.2, campaign F
(`HIL Results/hil_report_20260903_063659`) run CSVs, and bench logs PS0003, TP0017, TP0018, TP0105,
TP0110, TP0115, TP0130, WP0071, WP0121 decoded with `tools/decode_benchlog.py`. Scripts:
`hil_lowcurrent_census.py`, `gate_sensitivity.py`, `blg_noise.py`, `blg_noise_spectrum.py`,
`blg_offset.py` in this directory.

## 1. How much of a drive cycle the governor owns today

The share loop has three regimes: open-loop HOLD below 0.55 A of filtered total, a 0.05 A hysteresis
band, and closed loop above 0.60 A, inside which the minority clip binds whenever
`min(sp, 1 - sp) < 0.30 / I_tot`. Table 1 counts State-2 ticks in campaign F.

Table 1. Governor regime census, campaign F, State 2 ticks.

| Run | I_tot median (A) | HOLD (< 0.55 A) | Hysteresis band | Clip binding in closed loop | Loop tracking the commanded share |
|---|---|---|---|---|---|
| ems-sdp (61 s) | 0.999 | 44.7 % | 1.1 % | 54.1 % | 0.0 % |
| ems-ftp75-sdp | 0.430 | 65.8 % | 0.9 % | 33.4 % | 0.0 % |
| ems-ftp75-dp | 0.430 | 65.8 % | 0.9 % | 33.3 % | 0.0 % |
| ems-ftp75-mpc | 0.430 | 65.8 % | 0.9 % | 8.6 % | 24.8 % |
| ems-ftp75-socband | 0.444 | 54.2 % | 1.0 % | 34.3 % | 10.6 % |
| ems-ftp75-5050 | 0.430 | 65.8 % | 0.9 % | 0.0 % | 33.3 % |
| ems-ftp75c-sdp | 0.169 | 100 % | 0 % | 0 % | 0 % |

On the SDP and DP legs the commanded share is a band edge (0.15 or 0.85) for every tick, so the
clip binds for the whole closed-loop portion: the delivered minority current is pinned at 0.30 A
and the EMS share command is never tracked. The effective actuator of those policies is therefore
`SHARE_MINORITY_I_MIN_A`, not the share.

Table 2 shows what a lower closed-loop gate would recover, using the recorded I_tot distributions
(the gate is structurally `2 * I_min`).

Table 2. Closed-loop time fraction versus gate, and clip-free fraction at sp = 0.15 (requires
`I_tot >= I_min / 0.15`).

| Run | gate 0.60 (I_min 0.30) | gate 0.50 (0.25) | gate 0.40 (0.20) | gate 0.30 (0.15) |
|---|---|---|---|---|
| ems-sdp | 54.1 % / 0 % | 56.7 % / 0 % | 62.9 % / 46.5 % | 89.1 % / 50.0 % |
| ems-ftp75-sdp | 33.4 % / 0 % | 39.5 % / 0 % | 58.6 % / 0 % | 72.4 % / 0 % |
| ems-ftp75-socband | 44.8 % / 0 % | 47.2 % / 0 % | 58.8 % / 0 % | 72.3 % / 8.7 % |
| ems-ftp75c-sdp | 0 % | 0 % | 0 % | 2.7 % |

A floor of 0.25 A buys 2–6 percentage points of closed-loop time on FTP-75 and nothing on the
compressed cycle, whose total sits at 0.15–0.27 A. A floor of 0.20 A buys about 25 points on
FTP-75. Below 0.30 A of total no floor value yields a two-source split, so the compressed regen
cycle is out of reach of any governor retune.

## 2. What sets the floor (evidence)

1. **The floor is bracketed, not noise-limited, for the FC-minority direction.** TP0016 (sp 0.15,
   commanded minority 0.245 A at 1.63 A total) collapsed the bus to 8.2 V; TP0017 (sp 0.18, 0.29 A)
   was clean. The bracket is (0.245, 0.29] A at one total current. `SHARE_MINORITY_I_MIN_A` = 0.30 A
   sits 10 mA above the clean edge.
2. **The BT-minority direction fails higher and is one-sided.** WP0073 (b = 0.22, BT minority
   0.381 A) cycled at 18.7 Hz; WP0071 (0.399 A) was clean; WP0100 dropped out 28 times at 0.69 A
   of BT current while FC held 0.63–0.72 A as minority with zero dropouts. The whitepaper's
   conclusion 11 states that no constant-current floor separates the two regions and that the
   boundary is a bus-versus-reference margin of under 100 mV. The bench BT source (1.01–1.35 Ohm)
   confounds this direction; the vehicle pack is far stiffer.
3. **The static offset is channel-asymmetric and grows with load in the BT-minority direction.**
   From hold windows in the decoded logs, `dV0/k_d = (alpha - r) I_tot / (r (1 - r))`:
   FC-minority windows (r ~ 0.2) give -0.01 to -0.06 A; BT-minority windows (r ~ 0.8) give +0.20 A
   at 1.0 A total rising to +0.42 A at 2.0 A total (TP0115). A voltage offset would give a constant;
   a value proportional to I_tot is the droop-scale mismatch signature (rho = 0.9434 in
   `docs/modeling/converter_asymmetry_20260901.md`). At r = 0.5 and 0.25 A total the FC channel
   takes 0.57–0.67 of the current (TP0130, WP0121), the light-load nonlinearity CAL-1 also saw.
4. **The realized droop is about four times weaker than the design value** (`HIL_PLANT.md`
   section 4.2: 0.074 V/A shared and 0.16 V/A single-source measured against 0.316 / 0.633 Ohm
   designed; unexplained). The design authority `k_d I_tot` at 0.7 A is 0.21 V; the realized bus
   droop at that load is about 50 mV. The sub-100 mV race in item 2 follows directly.
5. **The HIL plant cannot test any of this.** The hi-fi engine has no PFM or light-load converter
   model (`system_model.md` section 6e item 3 declares PFM unmodeled; `hil_electrical.py` has no
   light-load branch). A floor or gate change is bench-only validation.

## 3. Measurement noise: what the loop actually sees

Table 3 gives the 1 kHz current-sense noise measured on the decoded logs (first-difference robust
sigma over steady 500-sample windows; fw v3 and later use 16x hardware averaging; main-loop period
1.163 ms median).

Table 3. Per-channel current noise and its structure.

| I_tot (A) | sigma I_fc (mA) | sigma I_bt (mA) | sigma share_act | corr(I_fc, I_bt) | lag-1 autocorrelation |
|---|---|---|---|---|---|
| 0.10 (TP0130) | 11 | 5–9 | — | +0.15 to +0.24 | +0.2 to +0.4 |
| 0.15 (WP0071) | 26 | 31 | 0.039 | -0.52 | +0.6 |
| 0.45 (WP0071) | 25 | 25 | 0.024 | +0.6 to +0.7 | -0.2 |
| 1.0 (PS0003) | 41 | 35 | 0.015 | +0.74 to +0.80 | -0.5 |
| 1.5–1.7 (TP0017/TP0105/TP0110) | 32–52 | 51–71 | 0.015–0.02 | +0.63 to +0.83 | -0.4 to -0.55 |

Three conclusions follow.

- Above about 0.4 A the noise is common-mode load ripple (positive inter-channel correlation,
  alternating-sign autocorrelation), not sensor noise: it is the VESC current loop and converter
  ripple aliased at 1 kHz. It largely cancels in the share ratio, which is why sigma of share_act is
  0.015 while the channel sigmas are 40–70 mA. Filtering the currents harder does not remove the
  part that reaches the share loop.
- At 0.15 A total the correlation flips negative with a slow autocorrelation: the two channels
  are trading current at low frequency. This is plant behaviour (light-load conduction exchange), not
  measurement noise. A filter would hide it from the controller without changing it.
- The hardware averaging (16x) operates over a few microseconds and averages ADC noise only. It
  cannot resolve below the 8.06 mA LSB and does not touch aliased ripple. Raising it to 32x adds
  roughly 0.2 ms of conversion time to a loop already at 1.16 ms.

Noise-to-jitter budget: the loop's closed-loop bandwidth is ~110 rad/s, so the noise-equivalent
bandwidth is ~27 Hz out of a 500 Hz Nyquist band, an amplitude factor of ~0.23. With the measured
sigmas the r jitter is 0.007–0.015 and the resulting minority-current jitter is 4–10 mA rms at
0.25–1.5 A total. Against a 0.30 A floor and a 45 mA bracket width, eliminating all measurement
noise would move the defensible floor by at most ~10 mA (three sigma). The governor's own mode
filter (alpha 0.05, ~20 ms) already reduces the total-current sigma by a factor 0.16, so the 0.05 A
hysteresis is 3–5 sigma; halving it is possible but recovers under 1 % of cycle time (Table 1's
hysteresis column).

**Answer to the filtering question:** stronger filtering of the current measurements cannot lower
`SHARE_MINORITY_I_MIN_A` materially. The floor is a conduction-margin limit of the light-load
converter and ideal-diode chain, bracketed by bench collapse, and noise contributes under 10 mA to it.
A heavier measurement prefilter would also cost phase in the synthesized loop (tau_f 0.8 ms is part
of the design plant; 10 ms would cost 48 degrees at crossover) and would require re-synthesis.

## 4. Other levers, ranked by expected effect

### 4.1 Load-scheduled droop scale (largest physical lever, firmware-only)

The MDAC mapping is `g = K_DROOP / (RE_MAX r)` with `g <= 1`, so `K_DROOP <= RE_MAX * r_min`. At
r = 0.5 the MDACs use only 30 % of their range. The minority clip already confines r to
`[I_min / I_tot, 1 - I_min / I_tot]` at light load, so the admissible droop scale is
`k_d(I_tot) = RE_MAX * max(DROOP_R_MIN, I_min / I_tot)`. Table 4 gives the resulting authority.

Table 4. Droop authority `k_d I_tot` (design scale) with the fixed and the load-scheduled k_d.

| I_tot (A) | r_lo | k_d max (Ohm) | authority now (V) | authority scheduled (V) | gain | d at r = 0.5, dV0 = 0.05 V, now / scheduled |
|---|---|---|---|---|---|---|
| 0.6 | 0.500 | 1.007 | 0.180 | 0.604 | 3.4x | 0.069 / 0.021 |
| 0.7 | 0.429 | 0.863 | 0.210 | 0.604 | 2.9x | 0.060 / 0.021 |
| 1.0 | 0.300 | 0.604 | 0.300 | 0.604 | 2.0x | 0.042 / 0.021 |
| 1.5 | 0.200 | 0.403 | 0.450 | 0.604 | 1.3x | 0.028 / 0.021 |
| 2.0 | 0.150 | 0.302 | 0.600 | 0.604 | 1.0x | 0.021 / 0.021 |

The authority becomes a constant `RE_MAX * I_min` = 0.60 V (design scale; ~0.13 V realized at the
measured 4x-weaker droop) instead of collapsing with load, which attacks the bus-versus-reference race
directly. The static plant gain stays exactly 1 (`alpha = r` for any k_d), so the Youla-H design is
untouched in its nominal loop; only the disturbance term shrinks. Costs and open questions: the
schedule must follow the filtered total with hysteresis so that k_d and r never combine to g > 1
during a slew, a deferral clip to the band edge, or HOLD; the bus voltage sags 0.6 V (design) at
light load instead of 0.2 V, harmless against `LIMIT_V_BUS_MIN` but visible to the HIL bus law
(V0_EFF, K_G), the loss-map DP bound, `governor_model.py`, and every h2 anchor; and the fixed
0.033 Ohm series term makes the gain-1 property approximate, which the larger k_d improves. This
option lowers the floor by increasing margin rather than by lowering `SHARE_MINORITY_I_MIN_A`, and
it needs the two-axis bench sweep of section 5 to show how far the floor moves.

### 4.2 Reference-referred (margin) governor instead of a current floor

The whitepaper's recommendation. Estimate the standing offset online from the closed-loop state,
`d_hat = sp - r` (the integral action makes alpha track sp, so the controller's r holds the offset),
compute the minority channel's conduction margin `M = R_maj I_tot +/- dV0_hat` with the realized
droop scale, and clip the reference to keep `M >= M_min` rather than `I_min >= 0.30 A`. This adapts
to which channel is minority (section 2 item 3 shows the offset differs by direction and by load) and
gives an I_tot-dependent floor, which the W data require. A first step with no control change is to
log `d_hat` per tick (it is already reconstructible from BLG `share_sp`, `gFC`, `gBT`) and check
that the dropout runs sit at a distinct margin.

### 4.3 Per-channel asymmetric floors

Cheap and evidence-backed in one direction: the FC-minority bracket permits at most 0.29 A (a 10 mA
change, no cycle-time benefit); the BT-minority direction has failures at 0.38 A and above, so its
floor would go up, not down, unless the bench-source confound is removed. Not a path to less
governing time.

### 4.4 Apply the clip to the feedforward path and reconsider the handover point

Both dropouts of the fw v6 ladder occurred at the open-to-closed handover, where a 0.42 swing in
commanded share is applied at 0.6 A total (whitepaper items 16–17). Applying the governor clip to
the feedforward submode makes the handover continuous and removes that failure mode, which is a
prerequisite for lowering the gate at all. Whitepaper item 17 argues for raising the engagement
point; a lower gate moves the opposite way and needs 4.1 or 4.2 first.

### 4.5 Firmware noise levers (small)

A two-tap or median filter on the governor inputs only (not on the loop's measurement) would let
`SHARE_GOV_OL_HYST_A` drop from 0.05 to ~0.03 A; the recovered cycle time is the hysteresis column
of Table 1 (about 1 %). Hardware averaging at 32x is not recommended (loop-time cost, no LSB gain).

## 5. Measurements that gate every option

1. **Two-axis dropout-boundary sweep, per channel direction** (setpoint at fixed I_max, I_max at
   fixed setpoint), the whitepaper's standing recommendation. It is not in `WORK_QUEUE.md`. It fixes
   the floor's I_tot dependence and the channel asymmetry, and it is the only way to size 4.1 or 4.2.
2. **The 4x droop discrepancy** (`HIL_PLANT.md` open item). If the realized droop is a quarter of
   the design value, the authority in Table 4 is also a quarter, and the FB-injection chain
   (RD1/RINJ, OPA197 gain, MDAC full scale) is where the margin is being lost. Resolving it may move
   the floor more than any governor change.
3. **Bench BT source stiffness** for the BT-minority failures; repeat WP0100/WP0073 with the pack.

## 6. Summary

Filtering the current measurements harder buys under 10 mA on the minority floor; the noise that
reaches the share loop is common-mode load ripple that already cancels in the ratio, and the floor
itself is a conduction margin bracketed by bench collapse. The governor owns 100 % of the SDP and DP
legs today because those policies command band edges, so the practical route to less governing time
is more droop authority at light load (load-scheduled k_d, section 4.1) or a margin-referred clip
(section 4.2), validated by the two-axis bench sweep and informed by the unexplained 4x droop gap.
