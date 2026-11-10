# Round 4 review-design loop: BQ25798EVM wiring design, carrier extension (r7, 2026-11-10)

This log records round 4 of the BQ25798EVM path (Path A). Round 4 changes one layout constraint: the carrier (CR) still
plugs into the 22 Ag105 holes, but it may now extend sideways past the 31 x 33 mm footprint. The design document
`docs/charger_bq25798_wiring_design_2026-11-05.md` was revised in place from r6 to r7. The round-3 record
(`../round3/review_loop.md`) is unchanged. The log has three parts: the design phase, review round 7, and the final independent
audit.

Coordinates: Eagle `.brd` board coordinates, mm, top view, +y up (design A.2). EVM points: EVM frame of `work/evm_geometry.md`.

## 1. Design phase

### 1.1 Fact-finding

Four parallel fact-finding notes established the inputs before any layout proposal was made:

| Note | Content |
|---|---|
| `work/evm_geometry.md` (+ `work/evm/`, `work/evm_calc/`) | EVM outline and points from the SLUUCB5E rev E vector figures; the corner circles are fiducials (no mounting holes); JP21 pin 1 is the lower square post; the round-3 rendered-figure scale was 2.2-2.5 % high |
| `work/mb_mechanical.md` (+ `mb_mech_calc.py`, `mb_pinload.py`, `mb_support_spots.py`) | MB parts, copper and rework points around the CHG footprint; pin-load and first-mode models; thermal estimate near the LM1084 |
| `work/eib_merge_failsafe.md` (+ `eib_merge_calc.py`) | EIB merge geometries G1/G2 and the fail-safe arguments; the E1/E8/C205 series resonance; the E-lead pickup criterion |
| `work/stackup_area.md` (+ `calc/stackup_area.py`) | 2-layer, single-sided and 4-layer options; loop inductance, coupling ratio, strict-basis area booking |

### 1.2 Proposals and assessment

Three carrier proposals were written independently: `work/proposal_minimal.md` (two short tabs), `work/proposal_tapside.md` (a
long +x arm toward the Teensy) and `work/proposal_evm_on_cr.md` (the EVM carried on the CR). Two independent assessors scored
them against the six round-4 questions. Both chose the minimal proposal (41/50 and 36/50; tapside 32 and 30; evm_on_cr 22 and
22). The assessors recorded factual errors in the proposals that r7 must not inherit; `work/r7_design_basis.md` section 9 lists
them.

### 1.3 Decisions and calculation

`work/r7_design_basis.md` fixes the r7 decisions D1-D11 (answers to the six questions), the BOM and test changes, the
measurements MS1-MS8 and the section edit plan. `calc/r7_calc.py` (H.23) was written against it and checked by a second,
independent calculation (`work/r7_check/`, `work/r7_check2/`, `work/r7_check3/`). The checks found these calculation errors,
all corrected before the design was revised:

| # | Error | Effect |
|---|---|---|
| C1 | MB CHG header pads measured as discs, not 1.65 mm squares | clearances to the tab edges 0.06-0.33 mm too large; no decision changed |
| C2 | per-net copper area summed per shape (overlaps counted twice) | 30.56 -> 29.16 mm² under tab X (+-0.3 mm² raster bias) |
| C3 | the SCL L1 trace outside the r7 outline missing from the "< 0.5 mm outside tab X" list | added (0.039 mm) |
| C4 | r6 tap lengths of T22/T8/T9 measured from the field centre | r6 sum 1308.7 -> 1308.0 mm |
| C5 | W5 terminal label | relabelled; geometry unchanged |
| C6 | fallback (i) chassis room stated as the EVM overhang only | 27.4 -> 45.3 mm (W1 approach point plus bend allowance) |
| C7 | tab Y 10 N push point printed at the first-run FT2 x | label only (< 0.5 % effect); corrected in the closing pass |

The calculation results changed four decisions (`work/r7_design_basis.md` sections 10 and 11):

- FT1: no 4 x 4 mm body in tab X meets the copper rule; the adopted foot is 4.0 x 1.6 mm with a +-0.29 mm placement tolerance.
- FT2: the far-edge spot (28.00, 73.25) with a 1.0 mm fill hole, because the L-FC body blocks a syringe lane from +y.
- T18: its pad moves to the footprint low row (41.68, 35.80), because a tab X pad cannot route to CO-5V without running along
  the LM1084.
- Area: R175 and the six 0.1 % divider resistors move to the top (73.55 % top / 69.04 % bottom).

The calculation also found three errors in r6 itself: the MB vias are not tented, the r6 polyimide sheet overlapped the CO-5V
body, and the E1 load was misattributed in A.5/H.15.

### 1.4 In-place revision

Seven section writers produced patch files against disjoint section groups (`work/r7_patches/`); `calc/apply_patches.py`
applied them atomically (185 edits). A consistency pass (stale references, cross-references, numbers against H.23, terminology)
followed as `work/r7_patches/95_consistency/`.
