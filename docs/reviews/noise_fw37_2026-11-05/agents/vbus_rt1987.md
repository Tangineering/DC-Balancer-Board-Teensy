## RT1987 ideal diodes vs V_bus noise and droop share (label rt1987)

**Bottom line.** None of the measured V_bus noise comes from the RT1987s. The switches matter in two quieter ways. Each one adds about 10 mOhm of incremental series resistance outside the droop loop, which shifts the incremental load split by about +0.02 toward 0.5. Each one also adds a common 35 mV offset, and that offset cancels in the split. In ML0226 the real V_bus content in 6-24 Hz is only 0.55-0.64 mV per band. A 47.62 Hz snapshot of the same data reads 2.5-3.8 mV, so the bag "6-24 Hz floor" is mostly content folded down from 24-442 Hz and above. No diode effect is needed to explain it.

### 1. Power topology (Eagle `references/Scale_Car_Board_20260624.sch` netlist, parsed; BOM 20260622)
- **FC path:** REG-FC.VOUT drives `VOUT-FC`, which carries C4A/B/C-FC (3x22 uF) and the FB divider top RD1-FC. From there the path runs through the SNS-FC IS+ to IS- shunt to `VBUS-FC` (C-D1 10 uF), then through D-FC-EN (RT1987, VIN to VOUT) to `VBUS`.
- **BT path:** the BT path has the same structure: `VOUT-BT`, SNS-BT, `VBUS-BT` (C-D3 10 uF), D-BT-EN and `VBUS`. In addition, BT carries the 10 uF + 0.1 uF hot-loop bodge caps (docs/boost-bringup-debug.md:24, :222; the FC channel has them too per :1288).
- **VBUS:** C-D2/4/5/9 (4x10 uF), the input of D-BC-FC (charger feed), the input of D-MT-EN, and R1-BUS (46.4k/10k, pin 26).
- **V-MOT:** D-MT-EN VOUT feeds `V-MOT`, which carries CAL 470 uF electrolytic, C-D6/C-D7 10 uF, J-M (VESC), the TL431/BSP170P chopper, and the RGN-V divider R1-SNT 78.7k/R2-SNT 10k. The divider also drives the TL431 U-SNT REF pin (pin 39).
- **Each RT1987:** CAP 1 nF (C-DC odd), SS 5.6 nF (C-DC even), POVP to GND (OVP at 33 V, DS 17.4 condition 2, p.15), CD tied to EXP. The 10k EN pulldowns are a bodge (CLAUDE.md).
- **Answer to the topology question:** the INA253 sits **upstream** of its RT1987, and the TPS61288 FB divider taps `VOUT-FC/BT`, upstream of both the shunt and the diode. The V_bus ADC senses the **post-diode common VBUS node**. The shunt (2 mOhm) and the RT1987 are therefore series elements outside each boost's regulation and droop loop.

### 2. Forward-regulation physics (RT1987_DS-00)
- **Source of the regulation curve:** the text in section 17.6 (p.16) describes VIN-VOUT servoed to VFWD = 35 mV typ (p.7; no min or max) while I*RON < VFWD. However, the typical curve "Ideal Diode Regulation Voltage vs Output Current" (p.13, VIN 28 V, digitized) is **not flat**. It reads 35 / 46 / 55 mV at 0 / 1 / 2 A, so the incremental resistance is about **10.5 mOhm below 2 A** and about 21 mOhm above it. RON is about 22-24 mOhm at VIN 8-16 V (p.13).
- **(a) Bus impedance and split:** each path adds about 10.5 mOhm (switch) + 2 mOhm (shunt) + PCB in series with its droop. A common series term Rs fitted to the README operating point (r = 0.204, |Z| = 67 mOhm, incremental I_fc/I_tot = 0.255) gives **Rs = 30 mOhm per path** and realized k_d = 47 mOhm. The terms are not resolved individually: the typical-curve switch + shunt (12.5 mOhm) accounts for about 40 % of Rs, and the remainder is boost output resistance and PCB, TODO(verify). Rs = 12.5 mOhm alone moves the incremental split from 0.204 to 0.223. The contribution to bus Z is about 6 of the 67-79 mOhm.
- **dV0:** the 35 mV offset is common to both paths and cancels in the split. VFWD varies by only 33.5 to 38 mV over -40 to 125 C (p.13), about 0.03 mV/C. There is no part-to-part specification, TODO(verify: Richtek), but even a several-mV mismatch is roughly 10x smaller than the README dV0 of -45 to -65 mV. The TPS61288 VREF tolerance, 0.588-0.612 V (DS 6.5, line 289, p.6, about +/-320 mV at 16 V), is the plausible source of that dV0. **The RT1987 is not the dV0 source.** Confidence is medium-high; the VFWD spread is unspecified.
- **(b) Light current:** the switch is a diode with a 35 mV knee. I_fc reaches 0 only when V_bus > V0_fc - 35 mV, and no current-domain dead band exists. The -50 mV fast comparator (tFRC 0.5 us) trips only on a fast reverse transient. Re-enable after a reverse block happens without soft-start (Table 1, p.15), so no 8 ms tD_ON gap occurs on purge return. A diode limit cycle would leave isolated I_fc zeros outside purges and anti-correlated I_fc/I_batt with a flat V_bus. **Neither signature is present** (section 3).
- **Servo bandwidth:** not in the datasheet. Section 17.6 says only that the control circuitry "is designed to accommodate relatively slow changes in load conditions", TODO(verify: Richtek). Above the servo bandwidth the FET at a frozen gate is a resistor of about VFWD/I_dc: about 0.23 Ohm at 0.15 A (FC minority), 0.07 Ohm at 0.5 A, and 0.035 Ohm at 1 A. With about 35 uF on VBUS (HIL C_VBUS) this forms an RC post-filter for boost ripple, with a corner around 20 kHz at 0.15 A. This is a benefit, it is light-current dependent, and it is unverified.
- **(c) MOT_PWR:** the switch blocks reverse current, so V-MOT is decoupled from bus dips and regen lifts V-MOT, not VBUS. In the forward direction it couples: at high frequency it is about VFWD/I_mot (35-90 mOhm), which is comparable to the 470 uF ESR (HIL `ESR_MOT` 0.080 Ohm, TODO(verify: Panasonic EEE-FN1V471UP)). VESC PWM ripple is therefore not isolated from VBUS, but it lies far above the ADC bandwidth and its in-band effect is not measurable here.

### 3. Data tests
**Sources.** ML0226 (fw v37, 422 s, fs 884 Hz, not 1 kHz: median dt 1.131 ms): FC = **bench supply** (V_fc 11.06 V, minimum 10.67 V, no purge dips; ML0227 the same day records an "FC supply" dropout); BT = the pack (7.69 V). The droop was fixed at share 0.5 / k_d 0.300 ('P' not run). YP0214: FC bench supply (8.57 V flat), pack 8.04 V. The bags: fw v35 / v37 with the H-20, and the 10-26 bag is battery-only.

**(i) Minority floor.** There are **no non-purge I_fc dropouts.**
- ML0226: 0 of 245 879 ticks with I_tot > 0.2 A have I_fc = 0, even at the 0.5 m/s hold with I_fc = 0.067 A per path.
- Bags, moving, 0x27, purge-masked: 0 of 4437 (fw v35) and 0 of 4559 (fw v37). I_fc p5 is 0.089 / 0.097 A. Isolated single-sample zeros: 0.
- I_fc and I_batt correlation in ML0226 is positive in every band: +0.96 (2-6 Hz), +0.62 (24-100 Hz), +0.07 to +0.38 (above 100 Hz). No anti-correlated source exchange appears (figure, panel c).
- Per-tick white noise while moving is 17.5 mA (I_fc) and 17.7 mA (I_batt), against 4.0 / 3.5 mA at standstill. This is real or aliased current content, independent per channel, and it is not a diode signature.

**(ii) V-MOT vs V_bus.** At 2-6 Hz, V_rgn tracks V_bus with coherence 0.93-0.97 at 0 deg. However, |H| = 0.79-0.87 after dividing by 0.848, and the DC holds give dV_rgn/dV_bus = 0.64. The V_rgn channel is therefore **affine, with an incremental gain of about 0.67-0.74 x true**, not 0.85 (the TL431 REF on RGN-V is a candidate, TODO(verify)). Bag regressions (0.40-0.48) are biased low by errors-in-variables. As a result, **the 35 mV / 10 mOhm MOT_PWR drop cannot be measured with this channel**, because the switch term is degenerate with the gain error (V_bus is approximately -Z*I_tot).
- **Excess noise above the standstill floor:** V-MOT and V_bus have similar excess (250-442 Hz: 2.35 vs 2.6 mV), and their coherence above 100 Hz is only 0.03-0.08.
- **Result:** within 442 Hz there is no evidence that V-MOT ripple exceeds V_bus ripple.

**(iii) Regulated vs resistive.** This is not separable in the data at about 10 mOhm per path. An open item: the V_bus holds in ML0226 give an incremental slope of 27 mOhm between 0.13 and 0.28 A and 79-80 mOhm from 0.28 to 0.62 A. The 2-6 Hz |Z| is 37 mOhm at 0.5 m/s and 79 mOhm at 2 m/s. The RT1987 curve is linear in this range and cannot cause this. Candidates are the INA253 near-zero output (about 6 mV at 0.06 A) and boost PFM, both unverified.

**V_bus spectrum at 884 Hz (holds; standstill in brackets).**

| Band | Holds | Standstill |
|---|---:|---:|
| 2-6 Hz | 2.19 mV, coherence with I_tot 0.95, \|Z\| 79 mOhm | 0.20 mV |
| 6-24 Hz | 0.85 mV | 0.44 mV |
| 24-100 Hz | 3.26 mV | 0.89 mV |
| 100-250 Hz | 2.29 mV | 1.28 mV |
| 250-442 Hz | 2.99 mV | 1.47 mV |

Speed-locked lines are almost fully coherent with I_tot: 33 / 67 Hz at 0.5 / 1.0 m/s (32x f_rot), and 82 / 282 Hz at 2.0 / 1.5 m/s. At those lines |Z| is 33-135 mOhm, with phase rising to +72-92 deg at 82-282 Hz. This is the boost closed-loop output impedance, and the motor is the source. It is not a diode effect.

**Aliasing check.** ML0226 was resampled as 47.62 Hz snapshots, as the bag does.
- V_bus 6-12 / 12-23.8 Hz goes from 0.55 / 0.64 mV to **2.47 / 3.75 mV**.
- I_tot goes from 6.8 / 7.0 mA to 25.8 / 34.9 mA.

The bag 6-24 Hz floors and their low coherence are therefore folded 24-442+ Hz content. The operating point differs from the bags (bench, about 0.3 A total), so the scaling to the bags is approximate.

### 4. HIL model error
The HIL model is `drop = 35 mV + I*(RT_R_ON 21 mOhm + r_series)` (tools/hil_electrical.py:139-140, :1335-1341, :1601).

| I | HIL | DS p.13 curve | DS 17.6 text |
|---:|---:|---:|---:|
| 0.15 A | 38.1 mV | 36.6 mV | 35 mV |
| 0.5 A | 45.5 mV | 40.5 mV | 35 mV |
| 1.0 A | 56 mV | 46 mV | 35 mV |
| 1.5 A | 66.5 mV | 50.5 mV | 35 mV |

The error against the curve is +1.5 to +16 mV. This does not matter for anything load-bearing:
- **Handoff:** the 35 mV knee is identical in all three models, so the handoff and reactive-pickup logic (:1649, :1714) is unaffected.
- **Split:** `DROOP_FIXED_SERIES_OHM` = 0.033 overstates the switch term by about 10 mOhm, but it happens to land on the empirical Rs of 30 mOhm. The incremental split at the README point is 0.260 (HIL) against 0.255 (fit) and 0.240 (curve + shunt + 10 mOhm R_out).
- **Bus voltage:** the bus sits 5-10 mV too low at 0.5-1 A.

Using the 17.6 text model (zero incremental resistance) would be worse: split 0.223 or below.

### 5. Ranked RT1987 effects, with magnitudes
1. **Series incremental resistance (about 10.5 mOhm per path, plus the 2 mOhm shunt, outside FB).** Shifts the incremental split by about +0.02 toward 0.5 and adds about 6 mOhm of the 67-79 mOhm bus Z. It contributes 8 % or less of the droop-coherent V_bus. Confidence: medium (typical curve; one fit).
2. **Common 35 mV offset.** V_bus sits about 36-41 mV below the regulated VOUT nodes, and the offset cancels in the split. Any VFWD mismatch is a few mV, which is under 10 % of dV0. Confidence: medium-high.
3. **Unidirectional clamp.** Engages only on purges and reverse transients. Observed effect on noise: zero (0 non-purge dropouts, no anti-correlation). Confidence: high for 0.07-0.4 A.
4. **High-frequency resistance VFWD/I.** Post-filters boost ripple into VBUS, more strongly at light current, and gives poor HF isolation of the VESC at V-MOT. Unmeasurable at 884 Hz; servo bandwidth TODO(verify: Richtek). Confidence: low.

**What remains.** The remaining bag V_bus noise comes from the droop at 1x and from aliasing. The speed-locked 32x and higher-order lines pass through the boost output impedance.

## Adversarial verification (data and physics lenses)

- [C1] On the 20260622 netlist the INA253 shunt and the RT1987 both sit downstream of the TPS61288 FB tap (VOUT-x -> SNS IS+/IS- -> VBUS-x 10 uF -> RT1987 -> VBUS), and the V_bus divider R1-BUS/R2-BUS taps the post-diode common VBUS node.
   data: CONFIRMED -- On the 20260624 Eagle netlist (references/Scale_Car_Board_20260624.sch), each TPS61288 FB divider (RD1-x) taps VOUT-x, upstream of both the INA253 shunt (IS+ on VOUT-x, IS- on VBUS-x with one 10 uF) and the RT1987 (D-x-EN, VIN on VBUS-x). The shunt and ideal-diode drops are therefore outside each boost's regulation loop. The V_bus divider (R1-BUS 46.4k / R2-BUS 10k, BUS-V to Teensy pin 26) taps the common post-diode VBUS node. That node also carries D-MT-EN.VIN, D-BC-FC.VIN and C-D2/C-D4/C-D5/C-D9 (4 x 10 uF). V-MOT (CAL 470 uF, C-D6/C-D7) is downstream of D-MT-EN and is not sensed by R1-BUS.
   physics: CONFIRMED -- The claim holds. On the 20260624 netlist, each TPS61288 FB divider (RD1-x.2) taps VOUT-x upstream of the INA253 shunt (IS+ on VOUT-x, IS- on VBUS-x). The RT1987 (D-x-EN, VIN on VBUS-x with a 10 uF C-D1/C-D3, VOUT on VBUS) is also downstream of the FB tap. So both the shunt drop and the ideal-diode drop are outside the boost voltage loop. The V_bus divider R1-BUS (46.4k) / R2-BUS (10k) sits on the post-diode common VBUS node, which also feeds D-MT-EN and D-BC-FC, and its tap is BUS-V on Teensy pin 26. One caveat: this is the pre-bodge Eagle file, although no recorded bodge changes these connect
- [C2] The RT1987 typical regulation curve is not flat: VIN-VOUT = 35/46/55 mV at 0/1/2 A (about 10.5 mOhm incremental below 2 A), so the HIL's 35 mV + I*21 mOhm overstates the drop by +1.5 mV at 0.15 A and +10 mV at 1 A, while the section 17.6 text model max(35 mV, I*RON) understates it.
   data: CONFIRMED -- The RT1987 typical regulation curve is not flat: VIN-VOUT is about 35/46/55 mV at 0/1/2 A, an incremental slope of about 10.3 mOhm below 2 A, rising to about 21 mOhm (R_ON) above 3 A (RT1987_DS-00 p.13, VIN 28 V, typical). The HIL element law of 35 mV + I*21 mOhm therefore overstates the drop by about +1.5 mV at 0.15 A and +10 mV at 1 A. The text model max(35 mV, I*R_ON) understates it by about 11 mV at 1 A. The curve is for VIN 28 V only; the slope at the rig's 8-16 V is unverified.
   physics: CONFIRMED -- RT1987_DS-00 p.13 ("Ideal Diode Regulation Voltage vs. Output Current", VIN = 28 V, typical) gives VIN-VOUT of about 34-35 / 45 / 54.5 mV at 0 / 1 / 2 A. The incremental slope is about 10-11 mOhm below 2 A, rising to about 20 mOhm (= RON) above 3 A. The HIL's 35 mV + I*21 mOhm (tools/hil_electrical.py:139-140, :1601) overstates the drop by about 1.5-2.7 mV at 0.15 A and about 10-11 mV at 1 A. The section 17.6 model max(35 mV, I*RON) understates it by about 10-12 mV at 1-2 A. The rig-voltage (8-16 V) dependence and the part-to-part spread are not specified (TODO(verify: Richtek)).
- [C3] No RT1987 dropout or limit-cycle signature exists at the minority floor: 0 of 245 879 ML0226 ticks with I_tot > 0.2 A have I_fc = 0 (I_fc down to 0.067 A), 0 of 4437 / 4559 moving, purge-masked 0x27 bag samples (fw v35 / v37) have I_fc = 0, and corr(I_fc, I_batt) is positive in every band (+0.96 at 2-6 Hz).
   data: PARTLY -- There is no sustained RT1987 dropout at the minority floor. In ML0226 (bench-supply FC at about 11.06 V, no purges, about 884 Hz logging), 0 of 245 879 ticks with I_tot > 0.2 A have I_fc < 0.004 A; the minimum I_fc is 0.048 A. In the 0x27 moving bags, all 46 (fw v35) and 49 (fw v37) I_fc = 0 samples fall inside V_fc-dip purges. After purge masking, 0 of 3867 / 4034 samples are zero. Pooled corr(I_fc, I_batt) is positive in every band: ML0226 +0.975 at 2-6 Hz and +0.46-0.72 above that; in the bags +0.13-0.79 at 2-6 Hz depending on gating. This rules out dropouts lasting one sample or longer (ab
   physics: PARTLY -- ML0226 is a bench-supply hold log (V_fc 10.9-11.2 V). It shows no sustained (≥ 1 ms) FC dropout at the minority floor: 0 of 245 879 ticks with I_tot > 0.2 A have I_fc < 4 mA, and the minimum I_fc is 0.048 A. The bag count of 0 is an artefact of the purge mask, which itself excludes I_fc < 0.03 A. Without the mask, there are 71 (v35) and 68 (v37) zero-current samples in moving 0x27 operation. Most coincide with H-20 purge collapses (median V_fc 2.4 V), but 24 and 19 occur at V_fc > 6 V and remain unexplained, possibly purge edges (UNRESOLVED). Band-pass corr(I_fc, I_batt) is positive in every b
- [C4] Resampling ML0226 to 47.62 Hz snapshots inflates V_bus from 0.55/0.64 mV to 2.47/3.75 mV in the 6-12/12-23.8 Hz bands (I_tot from 7 to 26-35 mA), so the bag 6-24 Hz V_bus floor is mostly folded 24-442+ Hz content, not a diode or droop effect.
   data: PARTLY -- On ML0226 (fw v37 bench, FC on a bench supply, I_tot 0.13-0.62 A, 4 closed-loop holds, about 96k ticks at 875.5 Hz), sampling every 21 ms raises V_bus band rms from 0.57/0.65 mV to about 2.6-2.75 / 3.75-3.8 mV in the 6-12 / 12-23.8 Hz bands. It raises I_tot from about 7 mA to 26-36 mA. The rise is due to content between 24 and 437 Hz (about 4.8 mV V_bus, about 47 mA I_tot) folding into the bag bands. This folded floor explains the bag standstill floor (2.9-3.4 mV) in magnitude. It explains only about 22-24 % of the fw v37 cruise 6-24 Hz V_bus power (5.5/8.1 mV rms), so most of the cruise floor
   physics: PARTLY -- In ML0226 (884 Hz BLG, closed-loop holds), a 21 ms sample-and-hold raises V_bus from 0.55/0.64 to 2.47/3.75 mV and I_tot from about 7 to 26-35 mA in the 6-12/12-23.8 Hz bands. The cause is folding of the 4.98 mV rms of V_bus content above 23.8 Hz, of which about 1.3 mV is 4.545 mV-LSB quantization. That folded content accounts for only about 21 % of the fw v37 bag's 5.5/8.1 mV floor in variance terms, so aliasing is a material part of the bag 6-24 Hz floor but not shown to be most of it. It does not rule out RT1987 or droop dynamics in the 25-442 Hz range that alias into the band. It only rule
- [C5] The V_rgn channel is affine with an incremental gain of about 0.67-0.74 x true (dV_rgn/dV_bus = 0.64 across the ML0226 holds; 2-6 Hz |H| 0.79-0.87 after /0.848 at coherence 0.93-0.97), so the MOT_PWR switch's 35 mV / about 10 mOhm drop cannot be measured from V_rgn - V_bus.
   data: PARTLY -- The V_rgn channel tracks V_bus with a low, non-constant incremental gain. Across the four ML0226 v_sp holds, dV_rgn/dV_bus = 0.63-0.64 (DC). In the 2-6 Hz band, |H(V_rgn/0.848, V_bus)| = 0.70-0.75 at 1.5 m/s and 0.85-0.92 at 2.0 m/s, with coherence 0.93-0.97 and phase within 4 deg. That is 0.59-0.78 x true raw, not 0.79-0.87, and it is hold-dependent rather than a single affine gain. The 0.5 and 1.0 m/s holds are too incoherent (0.25-0.69) to use. The ripple is at or below one V_rgn LSB (7.15 mV), and the log is sampled at about 875 Hz, not 1 kHz. A switch-resistance effect would push H above 
   physics: PARTLY -- The static V_rgn/V_bus ratio is a constant 0.848 (0.8477-0.8481) across all five ML0226 holds, consistent with the known pure-gain error. The 0.64 regression slope comes from a 31 mV span that cannot resolve gain from offset, so it does not establish an affine channel. The incremental 2-6 Hz H(V_rgn/0.848, V_bus) depends on operating point: 0.70-0.74 at 1.5 m/s and 0.87-0.89 at 2.0 m/s, at coherence 0.95-0.97, and it is unreliable below 1.5 m/s (coherence 0.32-0.69). It is below 1, whereas a series MOT_PWR drop would push it above 1, so an unidentified measurement error of about 8 mV dominates