## Completeness critique: remaining V_bus ripple, switching noise and the RT1987 ideal diodes (label: critic)

**Verdict.** The four reports agree that the RT1987s add no measurable V_bus noise. Most of the bag ripple is real speed-locked bus ripple folded down by the 21 ms snapshot, plus the folded ADC floor. TPS61288 switching ripple is at most about 1.2 mV per sample. Several numbers disagree between reports, and quick computations settle each one below. The diode question still has one open part: nobody has measured how the RT1987 behaves above its servo bandwidth.

### 1. Contradictions and how they resolve

1. **The line's frequency: 453 (switching) vs 397-401 Hz per m/s (blg1k, rt1987 data verdict).** The 453 figure is in sample-index units, which assumes a 1 kHz loop. The loop is free-running at about 875 Hz (`loop()`, :6768; the telemetry gate at :6812 is `millis()-lastSend > 20`). Rescaled, 453 x 0.8755 = 397 Hz per m/s.
   - That equals 6 x f_e exactly: 2.089 x 15.84 x 2 pole pairs x 6 = 397.1 Hz per m/s.
   - **Correct: 6x electrical, real at 600-1000 Hz.** The switching report's "217 flywheel orders / 18.1:1 ratio" identity is wrong.
2. **Time per analogRead(): 75 us (switching), 83 us (rt1987 data verdict), about 125 us (blg1k).**
   - The 75 us figure inherits the same 1.142 x frequency error: 75 x 1.142 = 86 us.
   - The blg1k figure comes from the phase of Z, which mixes real impedance phase with read skew. From the V_bus to V_rgn delay (two reads apart, :7031-7033) the value is **about 83 us**.
   - On that figure, V_bus is read 3.5-4 reads after I_tot, so the skew is about 290-330 us. TODO(verify): stamp `micros()` around `updateSensors()`.
3. **The rt1987 report treats the 82 / 282 Hz lines as real, with a +72-92 deg phase from the boost output impedance.** Both lines are aliases of 802 / 602 Hz. A 332 us skew gives 2π f τ = 72 deg at 602 Hz and 96 deg at 802 Hz, so **the phase is read skew, not inductive impedance.** Folding flips the sign, which the analysts' sign conventions hide.
4. **RT1987 incremental resistance: about 0 (blg1k, from the §17.6 text) vs about 10.5 mOhm (rt1987, from the typical curve on p.13).** The curve is measured data, so the rt1987 figure is right.
   - The HIL model overstates the switch by about 10 mOhm per path, not 20.
   - Caveat: the curve was digitized at VIN 28 V and is typical only. The rig runs at 8-16 V.
5. **TPS61288 light-load mode.** DS §8.4.2 (p.11-12) says off-time extension starts at a 2.6 A peak, and the peak then *keeps falling* to a 1.3 A clamp.
   - For FC at 0.15 A and 9.5 V, a DCM pulse at 500 kHz needs Ipk = sqrt(2 x 0.15 x 6.5 / (2.2 uH x 500 kHz)) = **1.33 A**. That is right at the clamp knee, still at about 500 kHz.
   - blg1k's "FC deep in PFM at about 100 kHz" wrongly holds the peak at 2.6 A.
   - The boundary formula 3.72 W / (16 - Vin) is common to all three reports: BT 0.45 A; FC 0.57 / 0.64 / 0.74 A at 9.5 / 10.2 / 11 V. The README's 0.40 A for BT is wrong.
   - The conclusion does not change: every PFM frequency is far above 442 Hz.
6. **The bag residual correlates with V_rgn at r 0.38-0.48, but at 1 kHz the broadband V_bus/V_rgn coherence is 0.02-0.04.** Both hold. The bag correlation comes from the folded *coherent line*. V_rgn reads 166 us after V_bus, which is 36-60 deg at 600-1000 Hz (cos 0.5-0.8), and V_rgn carries 0.64-0.82 x the line amplitude.
7. **"V and I_tot co-scale with speed but are uncorrelated tick by tick" (bagtest).** Read skew explains this quantitatively. The same-tick correlation of the folded 6f_e line goes as cos(2π · 397v · 0.33 ms): +0.34 at 1.5 m/s and -0.48 at 2.5 m/s. The sign changes with speed, so pooling over speed bins drives it to about 0. Bagtest's hypothesis (e) holds, and the low bag coherence is not a separate voltage source.
8. **The V_rgn gain: affine at 0.64 incremental vs a constant 0.848.** This is unresolved. The DC holds span only 31 mV, which cannot separate gain from offset. As a result the MOT_PWR switch drop is not measurable with the current data.

### 2. Parts of the question nobody answered

- **The RT1987 beyond its servo bandwidth.** The datasheet gives no bandwidth. If the gate is frozen above it, the switch looks like VFWD/I: about 0.23 Ohm on FC at 0.15 A and 0.07 Ohm on BT at 0.5 A.
  - This is a live candidate for blg1k's |Z| rise from about 85 to 128-133 mOhm at 600-800 Hz.
  - The alternatives are weak. Read skew cannot change |Z|. Wiring would need about 11 uH. The TPS61288 crosses over at 4-19 kHz, so its output impedance should still be flat at 800 Hz.
  - **This is the one in-band diode effect that remains plausible.** Nobody tested it.
- **The H-20 interaction.** No BLG exists with the H-20 on the FC input: ML0226, YP0214 and the August TP logs all used a bench supply. The claim that re-enable after a reverse block has no soft-start (Table 1, p.15) decides purge-return behaviour, and no data has tested it.
- **The vehicle standstill floor.** The bags read 2.9-3.5 mV, and the 10-26 bag reads 4.7-4.9 mV, against 2.2-2.5 mV on the bench (snapshot). Nobody explained the gap.
- **The vehicle loop rate.** It is unknown (blg1k infers 1.0 ms or less without SD logging). At a loop rate fs, 6f_e folds to near DC at v = fs/397. That is about 2.5 m/s at 1 kHz, which is the fw v37 cruise speed of 2.53 m/s. **A 21-tick boxcar cannot remove a line that the loop itself folds near DC.** The boxcar fix that all four reports recommend therefore needs this caveat, and the analog RC on the divider tap is the real fix.
- **The MOT_PWR switch's ripple isolation of V-MOT.** No report measured it (see item 8 above).

### 3. Claims resting on one unverified number

| Claim | Unverified number it rests on |
|---|---|
| RT1987 post-filters TPS61288 ripple | Servo bandwidth (no datasheet value) |
| Broadband excess = VESC PWM alias | VESC input capacitance; comb Tc / ADACK rate (rms gain 0.23); foc_f_zv-to-f_sw mapping |
| Bench → vehicle scaling of 1.2-1.5 x | One bench log on a bench supply at 0.13-0.62 A |
| 10.5 mOhm per switch, split shift +0.02 | One typical curve, digitized at VIN 28 V |
| Hidden I_fc / purge / PFM term ≤ 4 mV | One bag, binned at 47.6 Hz |
| Purge return has no 8 ms gap | Table 1 p.15 only; no H-20 BLG |

### 4. The one measurement

**A vehicle 1 kHz `K` log (BLG) with the H-20 and the pack, switch state 0x27.**
- **Sequence:** 10 s at standstill, then steady holds of at least 15 s each at 1.0, 1.5, 2.0 and 2.5 m/s, and at least one natural purge.
- **What it settles in one run:**
  - The split of the vehicle bag excess into folded drive line, broadband excess and floor.
  - The vehicle standstill floor.
  - The vehicle loop rate, and therefore the boxcar caveat.
  - The 1x / 6f_e amplitudes and |Z(f)| at the vehicle operating point.
  - The first look at purge and RT1987 behaviour at 1 kHz.

For the diode-specific bandwidth question, a differential scope across VIN-VOUT of D-FC and D-BT (AC-coupled, at 2 m/s) would settle whether the 600-800 Hz Z rise is the switch. The board has no test points for this, so it needs probe access or a re-spin.

### 5. Ranked budget of the remaining V_bus noise (fw v37 cruise, bag band 2-23.8 Hz, total about 11-12.6 mV rms)

The variance shares come from the ML0226 bench split (lines 61-66 %, broadband 21-26 %, floor 13-14 %), scaled to the vehicle. That scaling is unverified.

| # | Source | Expected mV rms | Confidence |
|---|---|---|---|
| 1 | Folded speed-locked bus ripple (6f_e plus 1x e and harmonics) through the boost/bus Z, which may include the RT1987 HF rise | 8-10 | Medium |
| 2 | Folded broadband excess, incoherent between channels (VESC PWM alias is the leading candidate) | 5-6 | Low-medium |
| 3 | ADC floor, folded (measured bag floor) | 2.7-3.3 | High |
| 4 | Real in-band droop response to I_tot (1x, 2-6 Hz) | about 2.4 (6-24 Hz real content only 0.4-0.9) | High |
| 5 | TPS61288 switching / PFM ripple aliased through the 16x average | ≤ 1.2 | Medium |
| 6 | RT1987 in-band (about 10 mOhm series, common 35 mV offset, no chatter or dropout) | ≤ 0.6; chatter about 0 | Medium-high |

The quadrature sum of the central values is about 12.3 mV, close to the measured 12.6 mV.

No figures or files were produced; this report is the deliverable.