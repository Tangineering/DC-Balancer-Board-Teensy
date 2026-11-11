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

## 2. Review round 7

### 2.1 Method

Five independent lenses reviewed the r7 revision: mechanical (mech), electrical (elec), safety (safety), process and test (proc),
and documentation (doc). A finding-verifier agent then checked each serious finding on its own and recomputed the numbers. The
verifier was not given the reviewer's severity. The verdicts are in `work/r7_review7_findings.json` (67 entries).

### 2.2 Result

| Measure | Count |
|---|---|
| Verified findings | 60 |
| Confirmed | 33 |
| Partially confirmed | 27 |
| Refuted | 0 |
| Blocker (verifier severity) | 0 |
| Major (verifier severity) | 10 |
| Minor (verifier severity) | 50 |
| Nits (not verified, applied) | 7 |

### 2.3 Dispositions

`work/r7_review7_dispositions.md` groups the findings into seven decisions. The verifier's fix is the default where it differs
from the reviewer's.

| Decision | Subject | Patch folder |
|---|---|---|
| D-F1 | Feet: controlled 0.05 mm tape bond line, h_f = 2.19 mm, PM4 (2d) feeler gate, alkoxy RTV bed, FT2 fill-hole witness, T-A-09 pull reduced | `r7rev7_F1` |
| D-F2 | W leads: designed dressing path, pin-tip covers, anchors at <= 30 mm spans, polyimide strip, W5 as a fixed 0.30 m cable, USB corridor width | `r7rev7_F2` |
| D-F3 | W1/W2 kept at a fixed 0.30 m +- 10 mm: the 181.6 mm route gives 34.9 V / 73 A at turn-off, 1.1 V below D107 VBR(min) | `r7rev7_F2` |
| D-F4 | Tab X tap assignment re-run with adjacency exclusions; adjacent-pad short table | `r7rev7_F4` |
| D-F5 | Per-region area booking (H.23(e2)); comparator band, R175 derating, MS4 points, T-A-06 L4 mask criterion | `r7rev7_F5` |
| D-F6 | Electrical leftovers: T-C-16 abort limit, E3/E4 pickup through E8, E1 route, EVM plate retention, G1 rationale | `r7rev7_F6` |
| D-F7 | Procedure and documentation: PM4 fixture and props, T-A-08 gates, MS1/MS5/T-F-18 criteria, supporting files, sheet trims | `r7rev7_F7` |

A consistency sweep followed as `r7rev7_Z`. Two integration conflicts were resolved by hand: one F6 edit was re-anchored, and one
F7 edit was withdrawn because it duplicated an F2 edit.

## 3. Closing pass

### 3.1 Operator statement D-H

On 2026-11-10 the operator stated that the MB and its PCBs have no maximum height limit. The closing pass applied this as decision
D-H:

- The 13.14 mm Ag105 envelope and the lid clearance are reference information only (A.7, H.23(j)).
- MS1a and MS2 lose their height items.
- J.2 item 59 is closed.
- Every rejection that rested on height was re-assessed, and each stays rejected on its other reasons (A.7). The mezzanine option
  (J.2 item 61) loses its height objection, but it stays rejected because it covers the Teensy USB/SD access and the J1/J2 tap
  pins.

D-H also allowed the 10 mm switched-conductor rule (J.2 item 62) to be applied as a 3-D distance. Spacers hold the round W leads
>= 14.41 mm above the MB on the CR and the W5 ribbon >= 15.00 mm. The L-FC height of 5.0 mm is an assumption that MS3 measures.

### 3.2 Calculation revision 4 and patches

`calc/r7_calc.py` revision 4 closed the residuals of the fix round:

- T-A-09 pull of 0.4 N, on both the tip-load and the distributed-load basis.
- Region bookings with U109 and U108 moved to the interior.
- Spacer positions S1 (35.00, 47.69) and S2 (28.70, 53.42); the longest span is 26.0 mm.
- Chassis-tie limits past the MB +y edge (2.4 / 16.4 / 17.4 mm with margin).
- The 3-D height profile.
- The E1 route at 70.8 mm.
- The adjacent-pad consequences (F05-F12, F07-F12, F08-F09, F09-F10).
- The 3.4 mm relief-hole option (rejected: the holes merge into slots).
- The polyimide strip extent.
- The T8 upper lane (89.2 mm; 20-tap dressed sum 898.7 mm).

Patch `r7close_A` (88 edits) synchronised the design with revision 4, applied D-H, updated the BOM total to about USD 520-630, and
added the review-round-7 rows to 0.3, 0.4 and the new L.7. Patch `r7close_Z` (23 edits) was the final consistency sweep. The SVGs
were regenerated from `r7_calc_out.json`.

### 3.3 Items left open by the closing pass

- The support for the round W leads off the CR is `TODO(design: T-A-06 dry fit)`.
- J.2 item 63: the tap-assignment choice and the F08-F09 pair (`TODO(design)`).
- J.2 item 62: the C102b exception needs a ruling.
- About 60 superseded markers hold the new text while the old text stays live. The latest marker in each chain is correct.
