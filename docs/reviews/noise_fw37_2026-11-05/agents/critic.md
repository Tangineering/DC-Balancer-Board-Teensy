# Completeness critic report (fw v35 vs v37 rev 2 noise round)

## 1. Contradictions between reports, and how I resolved them

My check uses the same masks for both bags: duplicate rows dropped, a 47.62 Hz grid, `switch_state` 0x27, v > 0.3 m/s, I_tot > 0.3 A, purges ±0.5 s excluded, `power_share_cmd` changes −0.2/+1.0 s excluded, and contiguous segments ≥ 96 samples (9 segments before, 10 after). The script is `C:/Users/ricky/AppData/Local/Temp/claude/3fe373bc8dcb48b3/e5f4c966-cfe4-4b0f-849e-8303e1628832/scratchpad/critic/c1.py`.

| band rms, v35 → v37 | 2–6 Hz | 6–12 Hz | 12–23.5 Hz |
|---|---|---|---|
| own share s | 0.0276 → 0.0110 (0.40x) | 0.0134 → 0.0091 (0.68x) | **0.0129 → 0.0119 (0.92x)** |
| I_tot (A) | 0.155 → 0.049 | 0.045 → 0.041 | **0.060 → 0.056 (0.93x)** |
| I_fc (A) | 0.046 → 0.016 | 0.017 → 0.012 | 0.019 → 0.018 |

- **(a) The 12–25 Hz band did not fall.** beforeafter reports a 0.52–0.54x fall in that band for I_tot and share. The other reports disagree: sensing gives 0.0134 → 0.0137, sharespec 0.0125 → 0.0114, sharemodel (6–23 Hz) 0.018 → 0.014. My check agrees with them (0.92–0.93x). beforeafter's figure comes from 27 s of speed-matched chunks with purges interpolated, and it is the outlier. The statement "the folded HF band fell in every channel, consistent with lower |C|" is therefore **not supported**. The drive-law change moved content only below about 12 Hz.
- **(b) What drives the remaining 1x share ripple: the k_d schedule or the minority-floor clamp?** beforeafter proposes 1x modulation of k_d. sharespec, sharemodel and freeform point to the floor clamp `lo = SHARE_MINORITY_I_MIN_A/share_govTotAFilt`. sharemodel's numbers settle it:
  - k_d share term ≈ 0.0005, against a predicted floor spEff of 0.0141 and a measured 0.0128.
  - r → s is in phase at about unity gain, which is the reference-tracking signature.

  The floor clamp is right. The knee at 0.78 A also sits next to the k_d crossover at 0.755 A, which is why beforeafter found the region split but attributed it to the wrong term. The action "schedule k_d from a slow load estimate" is therefore low-value for share noise. "Give the floor clamp a slow filter" is the correct version of the same idea.
- **(c) The claim that the floor holds I_fc constant (sharemodel §5, sharespec item 3) is overstated.** I measured H(I_fc/I_tot) at 2–6 Hz in the floor regime (cmd < 0.2, I_tot < 0.78 A, v37): **0.20 at +27° (n = 421)**. sharespec gives 0.23–0.26 for the same cmd above the knee. So the floor cuts FC 1x ripple by only about 15–20 %, not to about zero. The reason is that the 19.5 ms EMA passes about half of a 4.6 Hz reference, and the loop tracks it with lag. "Share is the wrong metric; a flatter share puts ripple into the PEM" therefore holds only weakly. A slow floor filter would raise I_fc 1x by at most about 20 %, while the share ripple in that regime would mostly disappear.
- **(d) Is the HF differential current fixed or load-proportional?** sensing says it rises with I_tot (1.73 → 2.58 LSB); sharespec says it is a fixed ~1 count. My tick-difference σ(Δs)·I_tot/√2 is flat across load:
  - v37: 10.8 / 12.7 / 12.2 / 12.6 mA in the bins 0.3–0.6 / 0.6–0.8 / 0.8–1.0 / 1.0–1.5 A.
  - v35: 13.6–16.9 mA.

  It is **roughly fixed in mA**, so sharespec is closer. It is about 1.5 LSB, not 1, and it fell about 20 % with v37. The 20 % fall hints at a partly physical, drive-coupled origin rather than pure ADC skew or alias. That is a hypothesis only.
- **(e) The fast load-split fraction differs: 0.23–0.26 (sharespec), β 0.34–0.37 (sensing), ~0.27 (freeform).** These are different estimators over different regime mixes. sensing regresses tick increments over all commands, where the median share is 0.24. They are not contradictory, but none of the three is a clean split-law parameter.
- **(f) Units.** `vs[:,10]` and `vs[:,11]` are Q16 gains (`.ino:7687`, `droop_gain_FC_actual*65535`), not MDAC codes. The brief is wrong on this point. beforeafter and sharespec are right.
- **(g) Duplicate rows.** freeform and sharemodel found one duplicate per 21 rows, because `millis()-lastSend > 20` at `.ino:6812` gives a 21 ms period. beforeafter and sensing did not de-duplicate. Their 1x ratios survive this, since it is a common-mode effect on both bags. Their PSD sidebands at ±2.38 Hz do not survive, and neither do any "fixed line" claims.

## 2. Questions left unanswered

1. **Operator Q3, interaction:** no report measured the in-situ share-loop S/T.
   - sharespec's governor-reference → n transfer (0.66∠−57° measured against ~0.85∠−43° nominal) is the only in-situ hint that the loop rejects less than the model predicts.
   - sharemodel's |S| table is nominal and gain-scaled; it is not a re-synthesis.
   - The verdict "no bandwidth change" is sound on the structural argument: the dominant term is a reference, so |T| ≈ 1 at any bandwidth. But nothing has confirmed that the loop matches the model at I_tot 0.7 A.
2. **Origin of the 12–24 Hz floor (≈ 0.012 share, now the largest non-commanded steady term).** The candidates are inter-channel skew, VESC-PWM or PFM alias, and real 25–500 Hz dynamics. All are open. sensing's PFM-boundary estimate (both boosts at or inside the PFM boundary) is unverified, and it would make the ripple frequency load-dependent.
3. **Purge windup (sharespec C4, I_fc spikes to 0.71 A).** Only one report covers it, and the verdict is "partly". The fw v35 purge-class lockout already detects purge-class dips (`.ino:148`). Nobody checked whether that detector fires inside the 80–120 ms purge, which a purge-aware freeze would need.
4. **Did the disturbance change? (beforeafter C2: d ≈ 0.6–0.8x of before)** This rests on one after-bag, 1–4 chunks per bin, and nominal |S|. No report tested the mechanical alternative: the disc or flywheel changed between 10-30 and 11-05.
5. **The 9.96–10.0 Hz speed-locked lines (50–124 mA; up after, 37 → 59 mA)** were seen by beforeafter and sharespec but explained by neither. They are larger than the residual share floor contribution in the currents.
6. **Freeform's V_fc step (−0.69 V at +5.5 s after each purge) and the V_batt floor excess (9 mV, 3x V_bus)** come from one analyst each and have no physical identification.

## 3. Claims resting on a single unverified number

- sensing's ~550 µs of ADC reads per tick (ADACK clock TODO). The skew mechanism and the A-B-B-A recommendation depend on it.
- sharespec's ΔV0 ≈ −45…−65 mV comes from a static fit with R² ≤ 0.23.
- freeform's pack R0 of 0.025 Ω depends on η = 0.90, and it goes straight to the bridge `pack_r_int_ohm` action.
- beforeafter's "share HP 0.86x unmasked vs 0.48x masked" depends on its own purge and step mask. The direction is confirmed by four reports; the 0.48 figure is not.
- freeform's /h2_usage under-report of ~2.1x assumes the brochure A0 applies to this stack.

## 4. Consensus that holds

- The drive law cut 1x by 0.20–0.40x on every channel.
- The operator's "share not reduced" is a windowing effect: SDP steps and purges dominate the unmasked share variance.
- Do not retune the share-controller bandwidth.
- Fix the telemetry cadence: use `lastSend += 20`.
- Add a v5 telemetry option with 20 ms boxcar means (protocol-bump skill).
- For the re-spin, every report converges on an anti-alias RC on the INA253 ADC branch only, keeping the droop/MDAC branch unfiltered.

## 5. The one measurement that settles the biggest open question

The biggest open question is whether the remaining ~0.012 share HF floor and the 10 Hz lines are **real differential current** or a **sampling artefact** (skew or alias), and whether the share loop's in-situ S matches the model. The bags cannot answer this, because everything above 23.8 Hz folds into them.

**The measurement:** one 1 kHz BLG run at steady cruise (~2.2 m/s, `power_share_cmd` held at 0.16, then at 0.49, for ≥ 30 s each, purges included and flagged), done twice.

1. **Run A:** the current firmware.
2. **Run B:** identical, except a one-line read-order change in `updateSensors()`: I_fc and I_batt read back to back, or synchronously via `analogSyncRead`.

**What each outcome means:**
- If the I_fc − r·I_tot differential PSD changes between A and B, the floor is an artefact and firmware sampling fixes it.
- If it is unchanged, the floor is physical, and the re-spin RC or boost FPWM work is justified.

The same log gives the pre-fold spectrum of the 10 Hz lines, a direct S/T estimate from the existing 1x excitation, and the real `youlaController_Power()` step period.