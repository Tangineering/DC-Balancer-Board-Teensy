## V_bus switching-noise budget vs measurement (label: switching)

**Answer.** Converter switching ripple explains neither the V_bus standstill floor nor most of the moving excess.
- **Standstill floor.** This is the Teensy ADC floor. TPS61288 ripple adds less than 0.1 mV per sample here.
- **Moving excess in the 1 kHz BLG.** This splits into two parts:
  - **61-66 %: a real bus-voltage line.** It is speed-locked at F = 453 Hz per m/s, real at its unfolded frequency and coherent with I_tot.
  - **21-26 %: a broadband excess that is incoherent between channels.** The only switching source whose budget reaches it is the VESC's 15 kHz PWM ripple aliasing through the 16-sample ADC average.
- **TPS61288 ripple is suppressed by the ideal diodes.** It reaches VBUS at 0.04-1.3 mV per sample, because the forward-regulated RT1987s act as a 110-500 mOhm series resistance into the VBUS ceramics. The ripple is large in V_fc and I_fc, not in V_bus.
- **The bag's 6-23.8 Hz excess is white.** It is the 1 kHz content folded by the 47.62 Hz snapshot. The 12-23.8 Hz band is higher only because it is wider.

### 1. Sources (datasheet / BOM / schematic)
- **TPS61288** (SLVSFP3C):
  - f_sw is 440/500/600 kHz (EC, p.6).
  - Below a 2.6 A inductor peak the off-time extends, and the peak clamps at 1.3 A (s8.4.2, p.12). Light-load operation is single-pulse PFM, so there is no low-frequency burst envelope (s9.1, p.13).
  - There is no MODE/FPWM pin (Table 6-1, p.4).
  - **PFM entry, re-derived.** A DCM pulse at Ipk 2.6 A and 500 kHz delivers I = f L Ipk^2 / (2(Vout-Vin)). This gives **0.45 A for BT (7.7 V), 0.57 A for FC at 9.5 V (H-20) and 0.75 A for FC at 11.1 V (bench)**; inputs are L = 2.2 uH (BOM line 9) and Eq.2-4 (p.14-15).
  - Consequently FC is always in PFM. BT is in PFM on the bench (0.07-0.31 A) and in DCM at 500 kHz at vehicle cruise (0.65 A).
  - **Ripple at VOUT:**
    - PFM: 4-47 mV p-p, bracketed by Ipk 1.3 and 2.6 A. The model uses Q = L Ipk^2 / (2(Vout-Vin)) and the BOM line 6 output caps (3x22 uF 25 V X7R 1210, derated to 30-40 uF effective, bodge caps included).
    - BT CCM at 1 A: 26 mV p-p (Eq.5) plus 4 mV from ESR (Eq.6, p.16).
- **RT1987.** Below I = 35 mV / 20 mOhm = 1.75 A, the gate servo holds VIN-VOUT = VFWD (35 mV typ; EC p.7; s17.6 p.16). At switching frequencies the channel is therefore R_eff = VFWD / I, giving **110-500 mOhm at 0.07-0.32 A**.
  - VBUS has only ceramics: C-D2, C-D4, C-D5 and C-D9 (schematic p.4; 4 x 10 uF, 12-35 uF derated; TODO(verify: DC-bias curves)).
  - **Ideal-diode effect.** R_eff and the VBUS ceramics form a 9-120 kHz low-pass that attenuates 100-500 kHz boost ripple by 0.03-0.36. Ripple at VBUS is 0.1-17 mV p-p.
- **VESC.** foc_f_zv is 30 kHz, which gives 15 kHz on the FETs (docs/VESC_MOTOR_INTEGRATION.md:300).
  - The DC-link ripple is 0.5-1.3 A rms at the ML0226 holds. The inputs are the SVPWM capacitor-current formula, I_q = I_cmd, lambda = 1.422 mWb (:79) and the 15.8:1 chain (:152).
  - The VESC input capacitance is TODO(verify: VESC EDU). The 470 uF CAL has an ESR of about 80 mOhm (BOM line 30).
- **H-20 (input disturbance).** Not separable here, because ML0226 ran on a **bench supply on FC**: V_fc was 11.1 V with no purge dips (minimum 10.67 V).
- **ADC.**
  - SCALE_V_BUS uses 46.4k/10k, so 1 LSB = 4.545 mV (.ino:2028).
  - There is no capacitor at BUS-V (schematic p.4 A3; no ADC capacitor in the BOM). The 8.25 kOhm Thevenin source therefore passes switching ripple to the sample-and-hold.
  - **Measured read period.** Inter-channel phase of the speed line fits pure delays of 151 us over 2 reads and 297 us over 4 reads, i.e. **74-75.5 us per analogRead()**. This confirms the 78 us ADACK estimate to 4 %.
  - The 16 averaged conversions are a comb, not a boxcar: |H| is 0.02-0.18 at 15/30 kHz (very sensitive to Tc) and averages to an rms gain of 0.23 over 100-600 kHz.

### 2. Budget vs measurement (ML0226, fw v37, 1 kHz)
Per-sample V_bus rms in mV. "Snapshot" is the 1-in-21 decimation, which is what the bag sees. "Broadband" is line-robust: the median PSD over 100-500 Hz x 500 Hz.

| hold | v (m/s) | snapshot | broadband | lines | TPS61288 pred | VESC pred |
|---|---|---|---|---|---|---|
| stand | 0 | 2.24 | 2.10 | 0.80 | <0.01 | 0 |
| V0.5 | 0.50 | 2.44 | 2.41 | 0.34 | 0.04-1.3 | 0.09-3.4 |
| V1.0 | 1.00 | 3.26 | 2.52 | 2.06 | 0.04-1.2 | 0.16-5.7 |
| A4.2 | 1.34 | 4.50 | 3.35 | 3.01 | 0.06-1.2 | 0.20-7.1 |
| V1.5 | 1.50 | 5.67 | 3.33 | 4.59 | 0.07-1.1 | 0.21-7.6 |
| V2.0 | 2.00 | 5.75 | 3.61 | 4.48 | 0.14-1.0 | 0.26-9.5 |

**(i) Standstill floor.**
- V_bus reads 0.46 LSB (2.10-2.18 mV). This equals V_rgn (0.48-0.50 LSB) and I_fc/I_batt (0.42-0.60 LSB).
- Cross-channel difference correlation is |r| <= 0.06, so a slow common reference is excluded.
- The floor is the ADC conversion noise plus 0.29 LSB of quantization. No switching term is needed.
- The bag standstill floor is higher: 3.03 mV (v37) and 3.46 mV (v35) in 0x26, and 4.98 mV battery-only. This 2.1-2.6 mV rss above the bench is **unexplained** (vehicle state: VESC idle, pack). TODO: a vehicle standstill K log.

**(ii) Moving: the speed-locked line.** At 1.5-2.0 m/s the snapshot variance is 13-14 % floor, 21-26 % broadband excess and **61-66 % lines**.
- **Frequency.** The dominant line is F = 453 Hz per m/s x v_act: median error 4.3 Hz over 856 spectrogram frames, folded at 500 Hz, with 2x and 3x harmonics also visible.
- **Coherence.** At the line, coherence with I_tot is 0.94-0.99 and coherence between I_fc and I_batt is 0.95-0.98.
- **Real at its unfolded frequency.** The V_rgn-V_bus phase is a 151 us delay with a 4 deg constant. The V_bus vs I_fc phase is a 297 us delay with a 164 deg constant (inverted, nearly resistive). An alias of a kHz carrier would add a 50-190 deg offset.
- **Impedance.** |Z| at the line is 81-133 mOhm.
- **Identity.** 453 Hz per m/s is 217 flywheel orders. That is the 12th mechanical order (6 x f_e) if motor:flywheel is 18.1:1; the documented chain is 15.8:1. TODO(verify: ratio).
- **Not resolved.** V-MOT (via V_rgn) carries 0.64-0.82 x the VBUS line amplitude. This is low for a VESC-side source; a possible cause is D-MT servo decoupling, with low confidence.

**(iii) Moving: the broadband excess.**
- It is 2.6-2.9 mV per sample (0.57-0.64 LSB). It is incoherent between V_bus and V_rgn (0.02-0.04) and with I_tot.
- It is larger on V-MOT: about 4.2 mV, i.e. 1.45 x VBUS (true volts, using V_rgn's 0.85 read scale).
- It grows with speed and current.
- TPS61288 cannot supply it (at most 1.3 mV). The VESC 15 kHz alias (0.1-9.5 mV) brackets it and predicts the V-MOT > VBUS ordering. Confidence: medium-low, because of the unknown VESC capacitors and the comb's Tc sensitivity.
- Switching ripple is visible elsewhere: I_fc broadband rises from 0.42 to 5.0 LSB (40 mA per sample) and V_fc from 5-7 to 25-29 LSB. These are the TPS61288 PFM pulses at the shunt and the boost input.

**(iv) The bag.**
- **White excess.** At fw v37 cruise (0x27, 2.53 m/s) the per-sample V_bus is 12.6 mV. Measured band rms is 5.71/6.21/8.70 mV against a white prediction of 5.18/6.35/8.90 mV; v35 matches above 6 Hz. **No source is specific to 12-23.8 Hz.**
- **Low coherence.** Decimating the BLG by 21 drops the V_bus-I_tot coherent fraction in 6-23.8 Hz to 0.08-0.39, against 0.94-0.99 at the line at 1 kHz. Folding many components with different transfer functions scrambles the coherence. **The bag's low coherence above 6 Hz therefore does not show an independent voltage source.**
- **Bench vs vehicle.** The bench snapshot at 2.0 m/s is 5.75 mV and the vehicle is 12.6 mV at 2.5 m/s with 25 % more current. The split of the vehicle excess into line and broadband needs a vehicle 1 kHz K log.

Figures: vbus_switching_budget.png (left: the table; right: bag bands vs white), vbus_switching_speedline.png (spectrogram with the 453 v overlay).

Unverified: VESC input capacitance; VBUS ceramic derating; the ADACK value (inferred from phase only); RT1987 servo bandwidth; motor ratio; the cause of the bag standstill floor.

## Adversarial verification (data and physics lenses)

- [S1] The 1 kHz BLG standstill V_bus floor is the ADC floor at 0.46 LSB (2.10-2.18 mV per sample), equal to the quiet floors of V_rgn (0.48-0.50 LSB) and I_fc/I_batt (0.42-0.60 LSB), with cross-channel difference correlation |r| <= 0.06.
   data: PARTLY -- The ML0226 standstill V_bus floor is ADC/quantization-limited at about 0.47-0.48 LSB per sample (2.13-2.18 mV; LSB = 4.545 mV). Readings are integer codes toggling over 3-6 values, and the robust MAD of the tick difference is 0.

The floor is comparable to the quiet floors of V_rgn (0.52-0.54 LSB) and I_fc/I_batt (0.43-0.49 LSB at true rest; I_fc rises to 0.59-0.61 LSB in the motor-active first 8 s). The largest |r| between channel tick differences is 0.06 (V_bus vs I_fc).

Caveats:
- The only true-standstill tail is t = 421.0-422.04 s (log end, about 1 s). The 0-8 s window has I_cmd at about 
   physics: PARTLY -- In ML0226 (fw v37 bench, BLG sampled every 1.131 ms, about 884 Hz, Nyquist 442 Hz), the standstill V_bus tick-to-tick floor is 0.47-0.48 LSB (2.13-2.18 mV at 4.545 mV/LSB). This equals the white ADC floor of the other channels in counts: V_rgn 0.53-0.54 LSB, and I_fc/I_batt 0.43-0.49 LSB in the clean tail window. The cross-channel diff correlation is |r| <= 0.061. The floor is therefore an ADC/quantization floor and not bus ripple. Caveats: the clean window 421-422 s holds only about 915 samples, and the 0-8 s window carries brief motor commands (I_cmd up to 3 A) plus slow current content. PSD
- [S2] The dominant moving V_bus component is a real line at F = 453 Hz per m/s x v_act (median error 4.3 Hz over 856 frames), carrying 61-66 % of the snapshot per-sample variance at 1.5-2.0 m/s.
   data: PARTLY -- ML0226 (fw v37) has a V_bus line whose frequency is proportional to v_act, coherent with I_tot (pooled 0.92, I_fc 0.91, I_batt 0.93), seen in 322 STFT frames at 1.15-2.0 m/s. In sample-index units it tracks fold(453.5 v), median error 0.3 Hz. The BLG samples at ~876-885 Hz, not 1 kHz, so in real Hz this is ~397 Hz per m/s for the k=1 alias (alias order unresolved). The line is above the nominal fold in every frame, so the BLG alone cannot show it is a real component rather than an alias. Its phase constants are not robust (V_rgn-V_bus tau ~180 us real, -51 deg; V_bus-I_fc ~345 us, +56 deg). It
   physics: PARTLY -- The dominant moving V_bus line in ML0226 is real at F = 453 Hz per m/s x v_act, which is above 500 Hz for every qualifying frame (v 1.15-2.02 m/s), so it appears aliased in the 1 kHz log. Its median tracking error is 0.9 Hz over 327 of 720 STFT frames. Coherence with I_tot is 0.97-0.98, with |Z| at the line about 130-136 mOhm. Phase fits on the true (unfolded) frequency give tau = 157 us, c = -5 deg for V_rgn vs V_bus (2 ADC reads) and tau = 303 us, c = -165 deg for V_bus vs I_fc (4 reads), which excludes a kHz-carrier alias and the mirror frequency. The line carries about 19-29 % of the V_bus
- [S3] TPS61288 switching ripple contributes only 0.04-1.3 mV per sample to V_bus at rig loads, so it cannot explain the 2.6-2.9 mV broadband moving excess.
   data: PARTLY -- A first-principles budget (RT1987 forward-regulation R_eff 35 mV/I, 12-35 uF VBUS ceramics, 16-sample comb rms gain 0.23) predicts 0.01-1.2 mV per sample of TPS61288 switching ripple on V_bus. However, the same budget underpredicts the measured I_fc broadband excess by 2-3.5x: about 40 mA measured at 0.23-0.32 A on ML0226, against 11-20 mA predicted. A comb-independent estimate is the measured shunt ripple times the VBUS capacitor impedance. It gives 0.2-6 mV, which brackets the observed 1.4-2.9 mV V_bus moving excess. Aliased switching ripple therefore cannot be ruled out as the source of the
   physics: PARTLY -- By a datasheet-level estimate (TPS61288 s8.4.2 p.11-12 and Eq.5 p.16, RT1987 R_eff = 35 mV/I, 12-35 uF bus ceramics, 16x ADC comb rms gain 0.23), TPS61288 output ripple adds at most about 1.3 mV per sample to V_bus at rig loads. That bound is conservative because it ignores the V-MOT 470 uF/VESC shunt. On that estimate alone the TPS61288 does not explain the 2.6-2.9 mV moving excess. However, the I_fc noise rise (0.43 to 5.5 LSB, about 44 mA) is 2-3x larger than the same model predicts for the I channel. That rise is therefore either another source or evidence that the model underestimates the
- [S4] The fw v37 bag cruise V_bus excess is white: band rms 5.71/6.21/8.70 mV against 5.18/6.35/8.90 mV predicted from the 12.6 mV per-sample sigma, so the 12-23.8 Hz band is higher only because it is wider.
   data: PARTLY -- The fw v37 bag cruise V_bus excess is approximately white over 6-23.8 Hz. Band rms is 5.71/6.21/8.70 mV against 5.18/6.35/8.90 mV from sigma 12.6 mV, with density 6.7-8.5 mV^2/Hz and a small 1x bump in 2-6 Hz. The 12-23.8 Hz band is larger only because it is wider. That result rests on about 21 s of data.

In ML0226 (bench, BLG tick 1131 us, not 1 ms), V_bus content at 6-23.8 Hz is only 0.5-1.1 mV, and most of the V_bus energy (2-7 mV) lies above 23.8 Hz. Peak coherence with I_tot at the 1x line is 0.93-0.96. The pooled 6-23.8 Hz coherent fraction is 0.11-0.61 at the BLG rate and 0.05-0.54 aft
   physics: PARTLY -- In fw v37 cruise (bag 2026-11-05), V_bus is close to white at the 47.6 Hz telemetry rate. Band rms is 5.71/6.21/8.70 mV against 5.18/6.35/8.90 mV predicted from sigma 12.6 mV, so 12-23.8 Hz is higher mainly because the band is wider. A small 1x excess remains in 2-6 Hz (+10 % rms). fw v35 is not white (2-6 Hz is 2.1x the prediction). On the ML0226 bench closed-loop holds, the V_bus-I_tot coherent fraction is 0.96 in 2-6 Hz but only 0.55/0.24 in 6-12/12-23.8 Hz at 1 kHz. Decimating 1-in-21 lowers it to 0.45/0.30/0.20 and raises the in-band V_bus to 3-3.8 mV by aliasing content above 23.8 Hz. Lo
- [S5] One blocking analogRead() with 16 hardware averages takes 74-75.5 us, confirming the 78 us ADACK-based estimate to within 4 %.
   data: PARTLY -- ML0226 is sampled at 875.5 Hz (mean dt 1142 us), not 1 kHz. On that time base, the 397 Hz/(m/s) line gives about 83 us per analogRead() from the V_bus to V_rgn phase delay: 166 us over 2 reads, bootstrap CI about +/-12 %. V_bus to I_fc gives about 82 us per read but is biased by the bus-impedance phase. That is consistent with the roughly 78 us ADACK estimate to within about 6 %, not 4 %. However, the adjacent I_fc to I_batt reads are only about 41 us apart, so per-read timing is not demonstrably uniform. The 74-75.5 us figure comes from assuming fs = 1000 Hz and should be withdrawn.
   physics: UNRESOLVED -- Each blocking analogRead() at 12-bit with 16x hardware averaging plausibly takes about 75-80 us. The estimate assumes ADACK, ADIV /2, long sample, and about 50 ADCK cycles per conversion (analog.c:153,243,259), and the cycle count and ADACK frequency are TODO(verify: i.MX RT1060 RM/DS). The phase-delay fits (151 us over 2 reads, 297 us over 4 reads) do not confirm it. ML0226 is sampled at about 875.5 Hz, not 1 kHz, so a "453 Hz" line is aliased or mis-scaled with an ambiguous true frequency. The coherence at that line is 0.14-0.16, and the fit ignores per-channel analog filter phase. Even take