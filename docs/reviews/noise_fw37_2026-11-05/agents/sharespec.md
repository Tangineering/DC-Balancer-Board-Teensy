# Share-ratio noise spectrum, fw v35 (10-30_01-49-38) vs fw v37 rev 2 (11-05_20-09-52)

**Bound:** the 10-30 bag ran fw v35 and the 11-05 bag ran fw v37 rev 2 (dates; `git diff ab4a705 da0746c`). In that diff, `share_controller.h` and `share_controller_coeffs.h` are byte-identical. A grep of the non-comment `.ino` changes finds only J-session guards on the share path. Neither bag has a gap > 22 ms (no gaps > 25 ms). Both bags hold 10 moving purges and use the same SDP command pattern.

**Definitions.** s = I_fc/(I_fc+I_batt), computed only in 0x27 with I_tot > 0.3 A. "Clean window" means moving (v > 0.3), purges ±0.5 s excluded and command steps (|Δcmd| > 0.02) ±0.2 s excluded. n = s − clip(cmd, 0.15, 0.85) is the part of the share the EMS did not command. Spectra use Welch averaged per run, at 50 Hz, so everything above 25 Hz is folded into the plots.

**Brief correction:** `vs[:,10]/[11]` are not 0–4095 MDAC codes. They are Q16 droop gains, `droop_gain_*_actual × 65535` (`.ino` l.7687). The droop ratio can be recovered as r = g_BT/(g_FC+g_BT), and k_d ≈ 0.30–0.36 Ω.

## 1. The share loop is not amplifying anything; the share drop was hidden by purges and EMS steps

A peel of the raw share spectrum (moving, 0x27, 3 runs per bag, nperseg 128) shows why the quick scan saw no improvement. Values are band rms, v35 → v37:

| term | 0.1–1 | 1–2 | 2–6 | 6–12 | 12–25 Hz |
|---|---|---|---|---|---|
| raw s | .056→.058 | .031→.039 | **.034→.041** | .020→.020 | .021→.022 |
| purges (peel) | .025→.021 | .016→.023 | .023→.033 | .015→.016 | .017→.017 |
| EMS cmd steps | .049→.053 | .024→.030 | .010→.016 | – | – |
| purges removed | .050→.054 | .027→.031 | **.025→.023** | .013→.012 | .013→.013 |

- **The EMS command dominates below 2 Hz.** The SDP changes the command about 0.6 times/s while moving, with 18 (v35) and 25 (v37) large steps inside the clean runs.
- **Purges are the largest 2–6 Hz term.** The purge depth is the same in both bags (mean s_before² 0.216 vs 0.217, 10/10 purges). The 0.023 → 0.033 change is therefore most likely estimator spread, but this is not verified.

**Clean-window budget** (`sharespec_budget_psd.png`; 13 runs/1950 ticks vs 17 runs/2524 ticks, nperseg 64). Band rms of n, v35 → v37:

| band | n total | 1x-locked (cos/sin of ∫v) | +I_tot +V_fc coherent | quantization | uncorrelated residual |
|---|---|---|---|---|---|
| 2–6 | **.0237→.0111** | .0173→.0068 | .0211→.0083 | .0011→.0012 | .0107→.0072 |
| 6–12 | .0130→.0089 | .0058→.0019 | .0086→.0048 | .0014→.0015 | .0097→.0073 |
| 12–25 | .0125→.0114 | .0031→.0019 | .0074→.0066 | .0020→.0021 | .0099→.0091 |

The 1x-band share noise fell by 53 %. The v35 peak at 4–5 Hz (PSD 3e-4, coherence with the 1x angle 0.72) is gone in v37 (peak ~4e-5). A matched operating point confirms this: cmd 0.16 with I_tot ≈ 0.76–0.80 A gives share 2–4/4–6 Hz rms of .0163/.0176 → .0057/.0076.

## 2. What the remaining share noise is made of (fw v37, ranked by contribution)

1. **EMS command steps (0.1–2 Hz, ~0.05 rms).** These are intended. Steps are tracked: 9/9 steps > 0.3 reach 90 % in 1–3 samples (20–60 ms), consistent with the 22 ms design settle plus the 0.02/tick slew. The loop **passes** them, as designed.
2. **H-20 purges (~0.02–0.03 rms in each band).** The s → 0 dip is physical. On top of it, the loop **adds** a kick. During each 80–120 ms purge, r ramps by +0.20…+0.40 at about 0.002/tick, which is the `DROOP_RATIO_SLEW_HANDOFF_PER_TICK` rate while FC reads dark. When the stack returns, I_fc spikes to 0.23–0.71 A for 1–2 samples; at the cmd 0.16 rail that is up to 2.75× the pre-purge value, and s spikes to 0.4–0.9. Recovery to the pre-purge share takes 1–2 samples (≤ 40 ms), so the tail runs at controller speed and is not slow (`sharespec_purge_overlay.png`). This holds in 10/10 moving purges in both bags.
3. **Governor-floor reference in the cmd-0.16 rail.** This is the main 2–6 Hz term in steady state. The rail is 73–76 % of commanded time. While `share_govTotAFilt` < 0.78 A, `spTarget` is clipped to `SHARE_MINORITY_I_MIN_A`/I_tot_filt, so the loop holds the FC current, not the ratio. Block means (v37, I_tot < 0.78) give I_fc = 0.007·I_tot + 0.121 A (n = 302 blocks of 0.1 s). Above 0.78 A, I_fc = 0.18·I_tot. The share therefore moves as 0.125/I_tot: in the binding chunks the 2–6 Hz rms is 0.0146 against a governor-reference rms of 0.0151. The loop **passes** this reference by design, and in doing so it shields the PEM from the flywheel ripple.
   - In v35 the 1x ripple was large enough that I_tot crossed 0.78 A inside each rotation. The clip toggled 7.97 times/s (v37: 4.23), so the reference was half-wave rectified.
4. **The ripple divides at the droop ratio r, not at the DC share.** This happens because ΔV0 ≠ 0. In v37 at cmd 0.16 with I_tot > 0.78, the measured split is H(I_fc/I_tot) = 0.23–0.26 at 2–25 Hz, while the DC share is 0.164 and r = 0.204. At cmd 0.49, H = 0.55–0.70 with r = 0.535 and s = 0.491. From the r − s offset, ΔV0 ≈ −45…−65 mV (FC no-load voltage low). Confidence is moderate: the static split-law fit has R² ≤ 0.23. The resulting term, (H − s)·dI_tot/I_tot, is about 0.006–0.008 rms. It is coherent with I_tot at phase ~0°. The loop rejects it only partly at 2–6 Hz (nominal |S| 0.11–0.33) and passes it above ~15 Hz.
5. **The 6–25 Hz floor is flat.** In v37 the share PSD is 0.9–1.4e-5 /Hz across 8–25 Hz, which looks like folded content. About 60 % of it is uncorrelated with I_tot, V_fc or the 1x angle. HF share rms × I_tot stays at 6.4–10.8 mA in every I_tot bin from 0.3 to 1.4 A. That is a roughly fixed **differential current noise of ~1 ADC count**, so the share term scales as 1/I_tot. It is 4–5× above quantization (share quantization is 0.0029 rms over 0–25 Hz).
   - The loop **neither** amplifies nor rejects this content. The nominal |S| peaks at 1.19 at 61 Hz, which would fold to 11 Hz, and there is no 11 Hz bump in the share PSD.
6. **Quantization is negligible:** 0.001–0.002 rms per band.

## 3. Targeted checks

- **(a) 4.10 / 6.93 Hz lines.** At standstill, neither line is in the currents (≤ 0.9 mA). V_fc carries a 6.84 Hz line at standstill in both bags (4.4–4.7× the local median, 10–12 mV rms), so it is on the H-20 side. It does not show in the moving share. While moving, "4.10 Hz" is the 1x line at the ~2 m/s plateau.
- **(c) Folded content.** See item 5 in section 2: the floor is flat and white-like, and the |S| peak region shows no structure.
- **(d) V_fc ripple.** V_fc adds little beyond I_tot: the multiple coherence rises from 0.0081 to 0.0083 rms at 2–6 Hz. The V_fc ripple is mostly a consequence of the I_fc ripple.
- **(e) 10 Hz anti-phase exchange.** Not present in either bag. There is a narrow 9.96 Hz line in moving I_batt (v37: 4.4× the neighbouring bins, ~15 mA), but it is **in-phase** with I_fc (+11°, coherence 0.66). It is common-mode, so it has little effect on the share. Its origin is unknown: `v_setpoint` updates at 20 Hz, and 2x rotation would be smeared.
- **Loop speed in situ.** The transfer from the governor reference to n at 4.7 Hz measures 0.66∠−57° (v37) and 0.91∠−40° (v35). The nominal T with the 19.5 ms EMA predicts ≈ 0.85∠−43°. My EMA is approximated at 50 Hz, which under-lags by ~14°. Together with the 2–6 Hz ripple split sitting near its HF value, this **hints** that the loop rejects less than the nominal model at this operating point. This is unverified and needs the 1 kHz BLG.

## 4. Verdict on share-loop bandwidth

A bandwidth change is not the lever:
- The two largest non-commanded terms are a commanded reference (the governor floor) and a physical outage (the purge). Purge behaviour is a windup problem, not a bandwidth problem.
- A faster loop would follow the floor reference more faithfully.
- For the ΔV0 split term, doubling the bandwidth would at best halve a term of about 0.006 rms, at the cost of the 11.7 ms delay margin.
- The loop shows no amplification in 0–25 Hz.

The interaction that does exist is through the governor: total-current ripple enters the share through 0.125/I_tot_filt. This is common-mode ripple turned into share variation by the clip's nonlinearity. It is designed behaviour, and it keeps I_fc quiet.

## Adversarial verification (data and physics lenses)

- [C1] In clean windows (moving v>0.3, 0x27, I_tot>0.3 A, purges +/-0.5 s and command steps +/-0.2 s excluded), the non-commanded share n = s - clip(cmd) 2-6 Hz rms fell from 0.0237 (fw v35) to 0.0111 (fw v37), and its 1x-angle-locked part from 0.0173 to 0.0068.
   data: PARTLY -- In clean 0x27 moving windows (purges and command steps excluded), the 2-6 Hz rms of n = s - clip(cmd) fell from 0.024 (fw v35) to 0.011 (fw v37), a factor of about 2.2 that holds across window length, estimator and purge gating. The 1x-angle-locked part fell by a factor of about 2.6 (ratio 0.38-0.40). Its absolute value depends on the estimator: about 0.017-0.023 before and 0.007-0.008 after, with coherence giving the low end and a per-run cos/sin least-squares fit the high end. The locked line 
   physics: PARTLY -- In clean windows (moving, 0x27, I_tot > 0.3 A, purges and command steps excluded), s - clip(cmd) at 2-6 Hz falls from about 0.023 (fw v35) to about 0.010-0.011 (fw v37), and its 1x-angle-locked part falls from about 0.017 to about 0.0065. This quantity is mostly not "non-commanded". With cmd at about 0.16 against the minority floor 0.125/I_tot (about 0.17-0.18 at about 0.72 A, teensy_controller.ino:622), the governor reference itself moves by 0.024 to 0.011 rms with the I_tot ripple. The reducti
- [C2] The raw moving-0x27 share 2-6 Hz rms rose from 0.034 to 0.041 because purges (peel term 0.023 to 0.033) and EMS command steps (0.010 to 0.016) dominate it; with purges interpolated out it is 0.025 to 0.023, and below 2 Hz the command (about 0.05 rms) dominates.
   data: PARTLY -- In the moving-0x27 share, the raw 2-6 Hz rms rose from about 0.037 (v35) to 0.041 (v37). Purges dominate it: the peeled purge term grew from about 0.026 to 0.034, and v37 spends more of its ticks in purge windows (11.6 vs 9.6 %). With purges interpolated out, the rms falls from about 0.027 to 0.022 (0.029 to 0.024 if purge ticks are excluded instead). With the command subtracted at a one-sample lag, the command term in this band is about 0.017 -> 0.019, nearly flat. The 0.010 -> 0.016 rise appea
   physics: CONFIRMED -- On moving 0x27 runs, the share's 2-6 Hz rms rose from about 0.033 (v35) to 0.038 (v37). The rise is entirely H-20 purge excursions (peel term 0.022 to 0.031) and EMS command steps (0.009 to 0.015), not more purges: about 10 purges per 100 s in both bags. With purges interpolated out, the band is 0.024 vs 0.022, and the residual after also subtracting the command fell from 0.023 to 0.016. Purges dominate the band in v37 (about 67 % of variance) but not in v35 (about 44 %). Below 2 Hz the clipped 
- [C3] At the cmd-0.16 rail with I_tot below 0.78 A, the governor floor holds I_fc at about 0.12-0.126 A (0.1 s block means in v37: I_fc = 0.007*I_tot + 0.121, n=302), so s follows 0.125/I_tot_filt; above 0.78 A, I_fc = 0.18*I_tot.
   data: CONFIRMED -- At the cmd-0.16 rail with I_tot below about 0.78 A (0x27, purges excluded), the minority floor holds I_fc flat at 0.12-0.13 A in both v35 and v37. In 5-sample block means for v37, I_fc = 0.008*I_tot + 0.120 (n=300); for v35, the slope is 0.016 and the intercept 0.118. So s follows about 0.125/I_tot_filt. Above 0.78 A, I_fc tracks the command: the through-origin fit gives I_fc ≈ 0.16*I_tot (k = 0.162-0.167). A free-intercept fit gives a slope of 0.14-0.18 depending on block length and bag.
   physics: PARTLY -- Below about 0.78 A of filtered total at the cmd-0.16 rail, the governor floor clip (teensy_controller.ino:14581-14583, I_min 0.125 A) holds I_fc at 0.125 A. Block means give a slope of 0.01-0.02 and a mean of 0.1248 A in both v35 and v37, so the share follows 0.125/I_tot_filt. Above 0.78 A the share tracks the command: I_fc is about 0.16-0.17 x I_tot through the origin (v37 0.162, v35 0.167). The free-fit slope (0.14-0.19) is poorly conditioned over that short range, so it should not be quoted a
- [C4] In 10/10 moving purges per bag, the droop ratio r winds up by +0.20 to +0.40 at about 0.002/tick (DROOP_RATIO_SLEW_HANDOFF_PER_TICK) during the 80-120 ms outage; on FC return I_fc spikes to 0.23-0.71 A (up to 2.75x pre-purge at the 0.16 rail) for 1-2 samples, and the share recovers within 20-40 ms.
   data: PARTLY -- The bags show 10 moving purges in each of the v37 (11-05) and v35 (10-30) runs. During each 80-120 ms I_fc outage, the droop ratio r = gBT/(gFC+gBT) winds toward BT. From the low-share state (r0 ~0.2-0.37, s ~0.16-0.28) it winds by +0.17 to +0.40. From the FC-majority state (r0 ~0.7-0.8) it winds by only +0.01 to +0.15. The per-sample rate varies from about 0.002 to 0.08 per 20 ms sample, so it is not one constant slew. When FC returns, the first I_fc sample is 0.15-0.89 A, which is 1.05-3.6x th
   physics: PARTLY -- In the fw v37 bag (11-05), every one of the 10 moving purges (80-120 ms, I_fc=0) lets the droop ratio r=gBT/(gFC+gBT) climb toward FC. The size of the climb depends on the operating point.

At the low (~0.16-0.3) share rail, 7/10 purges wind +0.21 to +0.41. After a first-sample step of up to +0.25 at the full 0.02/tick rate, they climb at ~0.035/sample, which is the 0.002/tick handoff slew at ~880 Hz.

At the 0.85 rail, 3/10 purges wind only +0.01 to +0.11 because r saturates near DROOP_R_MAX.


- [C5] Load-current ripple divides at roughly the droop ratio r rather than at the DC share: at cmd 0.16 with I_tot>0.78 (v37), H(I_fc/I_tot) = 0.23-0.26 over 2-25 Hz vs s = 0.164 and r = 0.204; the 12-24 Hz share rms times I_tot stays at 6.4-10.8 mA across I_tot bins 0.3-1.4 A (a fixed differential current of about 1 ADC count).
   data: PARTLY -- At cmd 0.16 with the filtered I_tot at or above 0.78 A (v37, 0x27, purges excluded), load-current ripple splits to the FC at |H(I_fc/I_tot)| = 0.23-0.26 over 2-25 Hz. The phase is about 0 deg, and the first-difference regression slope is 0.255. That is well above the DC share s = 0.165 and about 20-25 % above the droop ratio r = 0.204, so ripple divides much nearer the droop ratio than the DC share. The 12-24 Hz share rms times I_tot is 7.7-11.9 mA (about 1-1.5 ADC counts) over I_tot bins 0.3-1.
   physics: PARTLY -- At cmd 0.16 and filtered I_tot >= 0.78 A on v37 (0x27, purges excluded), load-current ripple divides near the incremental droop-slope ratio, not the DC share. Over 6-25 Hz (folded spectrum) H(I_fc/I_tot) is 0.255, with phase about -5 deg and coherence 0.91. At 2-6 Hz it is 0.231, where the share loop rejects only partly. For comparison, s = 0.165 and the code ratio r = 0.204. The 12-24 Hz share rms x I_tot is about 1-1.5 ADC counts, but it is not fixed: it rises from 7.5 to 12.3 mA as I_tot goes