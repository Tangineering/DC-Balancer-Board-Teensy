# Phase C notes: sim_permit (R2-LOG-0, R2-SIM-1, R2-SIM-2)

Scope: `hardware/charger_evm_r8/sim/permit/` only. No board, BOM, design-document or record file was edited. No option
was chosen; the C106/C107/C108 question stays open for the operator (design document J.2 item 77, D-81).

## 1. Files changed or added

| File | Change |
|---|---|
| `sim/permit/t2brief.py` | new entry script: families t2int (2-40 us and permanent open, 2520 decks), t2intx (50-300 us, 792), t2intl (1 and 3 ms, 144), t2lat (H1 inhibit latency, 360), t2thr (static H1 fall threshold, 12), t2rise (C107-alone false-trip check, 288); aggregates and figures |
| `sim/permit/t2brief_check.py` | new check-pass script: eight worst decks at 0.25 us time step |
| `sim/permit/decks/t2int, t2intx, t2intl, t2lat, t2thr, t2rise, t2check/` | 4124 generated decks |
| `sim/permit/results/t2int.csv, t2intx.csv, t2intl.csv, t2lat.csv, t2thr.csv, t2rise.csv, agg_t2int.csv, agg_t2lat.csv, agg_t2rise.csv, t2brief_check.csv` | new results |
| `sim/permit/figures/t2int_peak_vs_duration.png` and four `t2int__/t2rise__/t2lat__*_zoom.png` | new figures |
| `sim/permit/RESULTS.md` | header (second entry script, run order); Table 4.1 (three rows); Section 5.6 (two passages restated, old text kept in the superseded form); new Section 5.6a (Tables 5.4a-5.4d, Figures 5.5a-5.5c); conclusion 4 (restated, old text superseded); Section 8 bench item 2 (extended); Section 9 (two files); Section 10 split into 10.1 and new 10.2 (review items and check pass) |

`run.py`, `deck.py`, `analyse.py`, `summarise.py` and the models are unchanged. Note: `run.py` deletes every deck,
CSV and PNG under `decks/`, `results/` and `figures/` at its start, so a full regeneration is `run.py`, then
`t2brief.py`, then `t2brief_check.py` (RESULTS.md header).

## 2. Findings

- **R2-LOG-0 (S2): FIXED in sim/permit; RECORDED for the document owners.** The brief-interruption figures now have a
  committed, reviewed source: RESULTS.md Section 5.6a, Table 5.4a. The B.1 H1-row citation, B.2, J.2 item 77 and D-81
  still cite the scratch path and must be re-pointed (Section 4 below); those files are outside this brief.
- **R2-SIM-1 (S3): FIXED in sim/permit; RECORDED for the documents.** Formal 2/5/10/15/20/30/40 us + permanent sweep
  (plus 50 us-3 ms in the check pass), VBUS 14.5/15.9/16.4 V, corners early/nom/late, seven delay sets. Copies of the
  scratch recon CSVs were not added; instead the 123 matching t2int rows reproduce them to 3e-15 V. The hazard band
  of the as-built board is 5-30 us, not 10-20 us (30 us: 1.160 V worst, 1.031 V at the typical delay).
- **R2-SIM-2 (S3): FIXED in sim/permit (reconciled); RECORDED for J.2 item 77.** Neither proposed figure is the H.13
  quantity. "134 / 232 us" has no source and is about half of the simulated values. Sim 4 Table 5.5 (231-304 /
  490-643 us) is the H1 release latency after a 1 us step. The H.13 inhibit latency on the 3.125 / 4.5 V/ms ramps is
  197-269 us (4.7 nF) and 340-598 us (10 nF). Both follow tau(IN+) = 50.1 kOhm x C = 236 / 501 us.

## 3. Numbers for the later agents (all from RESULTS.md Section 5.6a)

Table 5.4d (trade-off; worst case over all decks; "above 1.0 V" = ILIM_HIZ > VIH 1.0 V with /CE LOW):

| Option | Hazardous interruptions | Worst peak, time above 1.0 V | Permanent open | T-B-06 budget 1.25 / 1.80 A (sim 3 basis, all delays) | False H1 trip, VBUS rise 12 V/ms |
|---|---|---|---|---|---|
| As built 470 p / 470 p / 1.0 n | 5-30 us (40 us+ only with UVB skew) | 1.810 V, 50.7 us (20 us) | 1.160 V, 6.5 us (skew); 0.858 V typical | 219.1 / 139.1 us (fixed delays 243.1 / 158.7) | none |
| C108 = 470 pF | 5-20 us | 1.545 V, 27.9 us (10 us) | 0.883 V, 0 us | 219.1 / 139.1 us | none |
| C107 alone = 4.7 nF | >= 30 us | 2.254 V (full release), 481 us | 0.684 V, 0 us | 219.1 / 139.1 us | yes, rise >= ~2.9 V, release up to 385 us |
| C106 = C107 = 4.7 nF | >= 30 us | 2.254 V, 481 us | 0.683 V, 0 us | 16.1 / -54.0 us (fails) | none |
| C106 = C107 = 10 nF | >= 50 us | 2.254 V, 1230 us | 0 V | -199.2 / -280.2 us (fails) | none |

Other numbers:
- Inhibit latency L (threshold crossing to ILIM_HIZ < 0.75 V): 470 pF options 27.0-34.3 us fixed delays, up to 58.4 us
  with the overdrive model; 4.7 nF 197.2-269.2 us; 10 nF 340.3-597.7 us.
- **New, not a review item:** the as-built H.13 budget at 1.80 A on the sim 3 TCR fall minimum is 158.7 us with fixed
  delays but 139.1 us (sim 3 basis) / 149.6 us (r3 basis) under the overdrive model, below the T-B-06 150 us. The H.13
  46 us deduction covers the fixed-delay L (34.3 us) but not the overdrive-model L (58.4 us). The overdrive figure rests
  on a ramp extrapolation of SBOS300C (RESULTS Section 7 item 2), TODO(verify: SBOS300C tPD at about 0.5 mV/us). The
  H.13 / T-B-06 owner should record it; nothing was changed.
- C107 alone: rises from 0 V and 13.0 V to 15.9/16.4 V at 12 V/ms release H1U (all decks), up to 385 us with ILIM_HIZ
  at 2.25 V; from 14.5 V only at 24 V/ms (2 of 12 decks, 99 us); from 15.2 V never.
- C108 = 470 pF is worse than as built in 49 of 576 matched decks, by at most 5.0 mV and 0.34 us (5-10 us cases). D-81's
  "never worse than 1.0 nF" should read "never worse by more than 5 mV / 0.34 us".
- Static H1 fall threshold of the deck model: 15.9 V nominal 17.017 V (sim 3: 17.012 V).

## 4. Proposed wording for the document owners (not applied; outside this brief)

- Design doc B.1 H1 row (line 1683): replace "(r9-25: sim 4 section 5.6; B.2, J.2 item 77)" by "(r9-25: sim 4
  sections 5.6 and 5.6a, Table 5.4a: as built 1.810 V and 50.7 us above 1.0 V for a 5-30 us interruption)".
- B.2 lost-T2 bullet (lines 1919-1923) and J.2 item 77 (lines 4155-4170): replace "An unreviewed re-run ... 10-20 us"
  by the sim 4 Section 5.6a figures (5-30 us; 1.810 V; 50.7 us); replace "C108 = 470 pF ... 0.51-1.05 V and leaves the
  10 us peak at 1.25-1.48 V" by "narrows the band to 5-20 us (1.545 V, 27.9 us)"; replace "about 134 us or 232 us of
  H1 latency (first-order estimate)" by "197-269 us or 340-598 us of H1 inhibit latency (sim 4 Table 5.4b), leaving
  16.1 / -54.0 us and -199.2 / -280.2 us of the T-B-06 budget at 1.25 / 1.80 A"; add that 4.7 nF and 10 nF give a full
  release of up to 0.48 / 1.23 ms for interruptions of 30 / 50 us or more; replace "C107 = 4.7 nF alone ... waits for a
  simulation" by "C107 alone trips H1 falsely on a VBUS rise of about 2.9 V or more at 12 V/ms (sim 4 Table 5.4c) and
  has the same >= 30 us release". Remove the %TEMP% path and the TODO(verify: sim/permit re-run); keep TODO(verify:
  SLUSDV2C ILIM_HIZ deglitch and restart time) and the T-D-04 bench capture.
- D-81 (LAYOUT_DECISIONS.md lines 2118-2133): "a scratch re-run" -> "sim 4 Section 5.6a"; "10-30 us" stands
  (5-30 us); the rejected-options and C107-alone bullets take the numbers above.
- T-E-07 fail branch (line 3608) and H.13 (line 3424): "C107 alone needs a false-H1-trip check" -> "C107 alone trips H1
  falsely on a 2.9 V rise at 12 V/ms (sim 4 Table 5.4c)"; H.13 may add the overdrive-model note above.

## 5. Verification done

- Every deck converged (0 simulator failures over 4116 decks plus 8 check decks).
- Reproduction of the scratch data: 123 matching rows to 3e-15 V.
- Time-step halving on the eight worst decks: peak within 0.5 mV, time above 1.0 V within 0.5 us, t_hold within 0.05 us.
- Metric cross-check: total time above 1.0 V agrees with the checker's single-episode width within 0.5 us.
- First-order checks: tau values from `gen/netlist.py` lines 164-178 plus R170/R171 10 kOhm; long-interruption
  release 481 / 1230 us against 477 / 1203 us estimated; static threshold against sim 3.

## 6. Left open

- The operator choice among the five options (J.2 item 77). The table does not rank the bands, because the duration
  spectrum of a real T2 fault is unknown (T-D-04 bench capture) and SLUSDV2C gives no ILIM_HIZ deglitch.
- Resistor tolerance is not a corner of sim 4; the H.13 budget combines simulated L with calculated fall minima.
- The as-built overdrive-model H.13 shortfall (139.1 us against 150 us) is recorded, not resolved.
