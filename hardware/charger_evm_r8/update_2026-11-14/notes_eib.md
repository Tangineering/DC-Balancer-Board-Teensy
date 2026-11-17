# EIB update of 2026-11-14: changes from the 2026-11-14 review

This note lists each change made to `eib/eib.kicad_pcb` in response to `REVIEW_2026-11-14.md`, with the script that
made it and the evidence. It is the input for the records step (decisions, README, fab README, BOM). No fab package
was exported and no file was committed.

## 1. Scope and method

### 1.1 Baseline

The baseline is `eib/eib.kicad_pcb` at git HEAD (last board commit `ccfa01a`, D-68). On the baseline, kicad-cli DRC
(`--severity-all --schematic-parity`) gives 0 violations, 0 unconnected items and 0 parity issues. The constraint
check (`gen/check_constraints.py eib ../eib`) gives 5 pass rows, 1 deviation row (D-13 outline citation) and 2 info
rows.

### 1.2 Method

The board was edited in place by one idempotent pcbnew script per change, saved under `gen/`. No generator was run
(no `make_board.sh`, `pcbbuild.py`, `route.py`, trim or finish script). Nets, references, values, footprint library
IDs and the DNP attributes are unchanged. After every change, DRC, `gen/pcbdiff.py` against the previous state and
the constraint check were run. The scripts must be run in this order to reproduce the board from HEAD:

1. `gen/eib_j201_pour_clearance.py`
2. `gen/eib_dnp_paste.py`
3. `gen/eib_pin1_marks.py`
4. `gen/eib_board_marking.py`
5. `gen/eib_wire_labels.py`
6. `gen/eib_silk_refs_r2.py [report.md]`
7. `gen/eib_stackup.py`

A second run of all seven scripts on the finished board changed nothing (`gen/pcbdiff.py`: 0 segments, 0 vias, 0
footprints, 0 zones and 0 other objects differ; the reference report is identical).

## 2. Changes

### 2.1 EIL-0: 0.5 mm pour clearance extended to the J201 wire pads

- **Change:** the D-68 zone-only rule `eib_E_pad_pour_clearance` now has the condition
  `A.Type == 'Zone' && (B.memberOfFootprint('E*') || B.memberOfFootprint('J201'))`, in `gen/eib_pour_rules.kicad_dru`
  and `eib/eib.kicad_dru`. All zones were refilled with the board loaded beside its own `.kicad_pro` and `.kicad_dru`.
- **Script:** `gen/eib_j201_pour_clearance.py`.
- **Evidence (pcbnew distance script over the filled polygons):** before the change, J201 pad 1 was 0.1529 mm and
  pads 2 to 10 were 0.1572 mm from the AGND pours on F.Cu and B.Cu. After the change, the smallest J201 gap is
  0.5005 mm (pad 1) on both layers; the E pads stay at 0.5007 mm. `gen/pcbdiff.py`: 0 tracks and 0 vias changed;
  the two AGND zones changed in fill only.
- **Pour islands (D-63):** on F.Cu, the large AGND island (434.74 mm², 38 vias) is now split into two islands of
  264.90 mm² (22 AGND vias) and 147.96 mm² (15 AGND vias). A new island of 0.95 mm² lies at x 15.25-16.36 mm,
  y 33.34-35.45 mm (left of the J201 column 1) and holds one AGND via. On B.Cu the island count is unchanged (5); the
  areas fell by at most 10.8 mm². Every island that is new or changed holds at least one AGND stitching via. Two
  0.85 mm² F.Cu slivers beside the E pads hold no via; they are on the baseline with the same area and are not caused
  by this change. DRC reports no unconnected item and no dangling via.
- **Zone clearance discrepancy:** both AGND zones declare a 0.2 mm local clearance, but the fill follows the
  0.1524 mm `fab_clearance` rule (review EIL-0 verifier note; the pre-change J201 gaps of 0.1529-0.1572 mm agree with
  0.1524 mm). D-28 and D-68 state "0.20 mm zone clearance". This update does not change the zone clearance; the
  statements in D-28 and D-68 need correction in the records step.
- **Not checked:** CR J101 against the CR pours (outside this board).

### 2.2 EIB-7 / EIL-6 / BOM-2: no paste on the DNP pads

- **Change:** each of the 14 DNP footprints (C203, C204, E4, E6, R258-R265, U203, U204; the board DNP attribute
  equals the `dnp` property set of `eib/eib.net`) has a footprint-level solder-paste margin of -2.0 mm. The margin
  exceeds half of every pad of these footprints, so KiCad plots no paste aperture for them.
- **Reason for the method:** removing F.Paste from the pad layer sets gave 12 `lib_footprint_mismatch` warnings in
  DRC, because the instances then differ from the library footprints. The footprint-level margin is not part of that
  comparison, so DRC stays at 0. The library footprints and `gen/fplib.py` do not change, because DNP is a
  per-instance build choice (D-49). A regeneration through `gen/pcbbuild.py` would not reproduce this change; the
  script must be re-run.
- **Script:** `gen/eib_dnp_paste.py`.
- **Evidence:** an F.Paste Gerber exported to scratch has 62 flashes (94 on the committed package); a coordinate
  check finds 0 apertures on DNP pads and 0 fitted SMD pads without an aperture. B.Paste has 0 flashes. Copper,
  mask, nets and fields are unchanged (pad comparison: 0 differences).
- **For the records step:** the fab README sentence "a paste stencil prints on the empty DNP pads" and the
  mislabelled stencil row in `eib_bom.csv` (BOM-1) are outside this update.

### 2.3 EIL-2: pin-1 marks for U201, U202, Q201-Q203 (and U203, U204)

- **Change:** a filled F.Silkscreen dot (radius 0.10 mm, stroke 0.15 mm, outer diameter 0.35 mm) sits diagonally
  off the outer corner of pad 1. Footprint coordinates: SSOP-8 (DCT) (-2.75, -1.45), SC70-5 (DCK) (-1.75, -1.15),
  SOT-23 (-1.9, -1.5), SOT-23-6 (-2.0, -1.5) mm.
- **Library:** `gen/fplib.py` gained `_pin1_dot()` and `PIN1_DOT`; `ssop_ti()` and `tight()` (keys SOT-23,
  SOT-23-6, SC70-5) add the dot. The four affected files in `eib/charger_r8_eib.pretty/` were written from
  `gen/fplib.py`; each differs from git HEAD by the one dot line (the `tedit` stamp and the CRLF line ends are kept).
  The rest of the library was not regenerated. The instances on the board were then given the same dot, so DRC
  reports no library mismatch.
- **Script:** `gen/eib_pin1_marks.py`.
- **Evidence:** board positions and gaps to the nearest mask opening: U201 (10.245, 29.555) 0.181 mm; U202
  (12.345, 24.755) 0.176 mm; Q201 (5.120, 17.055), Q202 (9.395, 20.430) and Q203 (5.120, 25.055) 0.173 mm; U203
  (5.995, 24.605) and U204 (5.495, 38.905) 0.156 mm. No dot overlaps another courtyard. DRC 0/0/0.
- **CR impact:** the CR uses the same package keys SOT-23, SOT-23-6 and SSOP-8 with a 0.25 mm courtyard. The CR
  library and board were not changed. A future CR library regeneration adds the same dots; their clearance on the
  CR was not checked (CRL-3 is a CR item).

### 2.4 EIL-7: board marking

- **Change:** the two F.Silkscreen texts "EIB r8" and "2026-11-11" are now one text, "EIB r8 2026-11-14", at
  (12.0, 49.05) mm (0.8 x 0.8 mm, stroke 0.15 mm). The line freed above it holds the J201 map (section 2.5). F.Fab
  carries no board marking. The date is that of this update; if the exported package carries a suffix (for
  example 2026-11-14a), the marking and the package name differ by that suffix only.
- **Script:** `gen/eib_board_marking.py`.
- **Evidence:** DRC 0/0/0. Two tented AGND vias, at (11.96, 49.21) and (16.46, 49.21), lie under the text, as they
  did under the former date line.

### 2.5 EIL-1 / INT-2: J201 pin and net labels; EVM points at the E labels

- **J201 map (F.Silkscreen):** the J201 pads cannot carry labels beside them: the pad gaps are 0.74 mm and the parts
  around the grid leave no room on either side of the board. A map therefore sits in the free strip above the board
  marking (ink box x 8.16-22.70 mm, y 43.14-48.18 mm). It has the header "J201 top view" and a 3 x 3 table of
  "pin net" cells in the arrangement of the J201 pads seen from the top, with two vertical separator lines
  (0.15 mm). The cells are built from the pads and nets of the board, so they agree with `eib/eib.net` and Table
  D-66:

  | Row (top view) | Column 1 | Column 2 | Column 3 |
  |---|---|---|---|
  | 1 | 1 3V3 | 4 STAT | 8 RLB |
  | 2 | 5 CE | 2 3V3 | 3 GND |
  | 3 | 7 RLA | 10 RFC | 9 GND |

  Short names: 3V3 = /3V3, GND = /GND_J, STAT = /STAT, CE = /CE_DRV_J, RLA = /ILIM_REL_A, RLB = /ILIM_REL_B,
  RFC = /RFC_OFF_J. Text 0.8 x 0.8 mm, stroke 0.15 mm. The cells and lines avoid every mask opening, drill and
  tented via (cell "4 STAT" is shifted within its column to clear the via at (13.46, 45.46); separator 2 is
  placed in the gap clear of the via at (17.96, 45.46)).
- **EVM points (B.Silkscreen):** the E labels now read E8 TP49, E3 TP33, E4 DNP, E2 JP14, E7 TP38, E1 JP12, E5 TP36
  and E6 DNP, from the A.5 wiring table of `docs/charger_bq25798_wiring_design_2026-11-05.md` (E2 lands on JP14
  pin 2 and E1 on the JP12 REGN pin; E4 and E6 carry no lead, r9-2). Each label starts at x 3.25 mm (E3: 3.75 mm)
  beside its pad row. The labels E2, E7 and E8 cross a tented via, because no via-free position exists at their row;
  the former E2 label already crossed the via at (3.86, 23.96).
- **Script:** `gen/eib_wire_labels.py`.
- **Evidence:** DRC 0/0/0 (silk-to-pad, silk-to-edge and silk overlap checks included).

### 2.6 EIL-2: reference designators next to their own parts

- **Change:** every reference field of the C, R, Q and U parts and of J201 was re-placed under an unambiguity rule.
  The text ink keeps clear of every mask opening (+0.05 mm), drill (+0.15 mm), silkscreen graphic (+0.10 mm), board
  text (+0.40 mm), other reference (+0.25 mm), every courtyard (its own included) and the 0.25 mm edge band. The gap
  to every other courtyard must be at least max(2 x d_own, d_own + 0.15 mm), with d_own <= 2.0 mm the gap to its own
  courtyard; DNP footprints count as other parts, so that an empty footprint cannot take the label of a fitted part.
  Text is 0.8 x 0.8 mm; where no such position exists, 0.8 mm high and 0.6 mm wide (height and stroke stay at the
  `fab_silk_text` rule, 0.8 / 0.15 mm). Tented vias are avoided where possible. Fitted parts are placed first.
- **Script:** `gen/eib_silk_refs_r2.py` (randomized greedy search, fixed seed; the per-reference report is printed or
  written to the optional report path).
- **Result:** 30 of 38 references are on F.Silkscreen, 22 of the 26 fitted parts among them, all within 0.12 mm of
  their own courtyard. U201 now has a silkscreen reference (it was on F.Fab). Q201 sits 0.02 mm from Q201 (it was
  7.0 mm away), R250 0.05 mm from R250 (it was 6.4 mm away), and R267-R270, R273 and R276 sit 0.01-0.05 mm from their
  parts (they were 3.8-6.3 mm away).
- **No unambiguous top-side position:** fitted C201, C202, R251 and R271, and DNP R259, R264, R265 and U203. Their
  references are on F.Fab (fab drawing and iBOM). For the four fitted parts, a mirrored B.Silkscreen text of the
  reference also lies over the part, so that the part can be identified from the bottom. C201 and R251 sit between
  U201, R264 and the DNP C203/C204 with 0.73-0.98 mm gaps, which cannot hold a 0.95 mm text with an unambiguous
  margin. R271 has no candidate position under the rule. C202 has candidate positions, but each of them conflicts
  with a label of the best assignment found, which places 22 fitted references.
- **0.6 mm wide text:** R253, R254, R255, R257, R263, U201 and U204.
- **References over a tented via:** C204, U201 and U202.
- **Per-reference table** (gaps in mm):

  | Reference | DNP | Text w x h (mm) | Angle (deg) | Gap to own courtyard | Gap to nearest other courtyard | Note |
  |---|---|---|---|---|---|---|
  | C201 |  | 0.8 x 0.8 | 0 | - | - | F.Fab; B.Silkscreen text over the part |
  | C202 |  | 0.8 x 0.8 | 0 | - | - | F.Fab; B.Silkscreen text over the part |
  | C203 | DNP | 0.8 x 0.8 | 0 | 0.06 | 0.22 |  |
  | C204 | DNP | 0.8 x 0.8 | 0 | 0.06 | 0.24 | crosses a tented via |
  | C205 |  | 0.8 x 0.8 | 0 | 0.01 | 0.19 |  |
  | J201 |  | 0.8 x 0.8 | 0 | 0.03 | 0.79 |  |
  | Q201 |  | 0.8 x 0.8 | 90 | 0.02 | 0.96 |  |
  | Q202 |  | 0.8 x 0.8 | 0 | 0.02 | 0.17 |  |
  | Q203 |  | 0.8 x 0.8 | 0 | 0.05 | 0.20 |  |
  | R250 |  | 0.8 x 0.8 | 0 | 0.05 | 0.37 |  |
  | R251 |  | 0.8 x 0.8 | 0 | - | - | F.Fab; B.Silkscreen text over the part |
  | R252 |  | 0.8 x 0.8 | 90 | 0.12 | 0.64 |  |
  | R253 |  | 0.6 x 0.8 | 90 | 0.01 | 0.17 |  |
  | R254 |  | 0.6 x 0.8 | 0 | 0.04 | 0.23 |  |
  | R255 |  | 0.6 x 0.8 | 0 | 0.04 | 0.24 |  |
  | R257 |  | 0.6 x 0.8 | 90 | 0.04 | 0.27 |  |
  | R258 | DNP | 0.8 x 0.8 | 0 | 0.09 | 0.31 |  |
  | R259 | DNP | - | - | - | - | F.Fab |
  | R260 | DNP | 0.8 x 0.8 | 0 | 0.05 | 1.84 |  |
  | R261 | DNP | 0.8 x 0.8 | 0 | 0.00 | 0.22 |  |
  | R262 | DNP | 0.8 x 0.8 | 0 | 0.01 | 0.84 |  |
  | R263 | DNP | 0.6 x 0.8 | 90 | 0.07 | 0.26 |  |
  | R264 | DNP | - | - | - | - | F.Fab |
  | R265 | DNP | - | - | - | - | F.Fab |
  | R266 |  | 0.8 x 0.8 | 0 | 0.09 | 2.40 |  |
  | R267 |  | 0.8 x 0.8 | 0 | 0.02 | 0.25 |  |
  | R268 |  | 0.8 x 0.8 | 90 | 0.01 | 0.22 |  |
  | R269 |  | 0.8 x 0.8 | 0 | 0.02 | 0.23 |  |
  | R270 |  | 0.8 x 0.8 | 0 | 0.05 | 1.84 |  |
  | R271 |  | 0.8 x 0.8 | 90 | - | - | F.Fab; B.Silkscreen text over the part |
  | R273 |  | 0.8 x 0.8 | 0 | 0.02 | 0.30 |  |
  | R274 |  | 0.8 x 0.8 | 0 | 0.08 | 0.60 |  |
  | R275 |  | 0.8 x 0.8 | 90 | 0.04 | 0.54 |  |
  | R276 |  | 0.8 x 0.8 | 0 | 0.02 | 0.26 |  |
  | U201 |  | 0.6 x 0.8 | 90 | 0.00 | 0.19 | crosses a tented via |
  | U202 |  | 0.8 x 0.8 | 0 | 0.02 | 0.49 | crosses a tented via |
  | U203 | DNP | - | - | - | - | F.Fab |
  | U204 | DNP | 0.6 x 0.8 | 0 | 0.00 | 0.25 |  |

  A gap of 0.00 mm is a gap below 0.005 mm; no ink box overlaps a courtyard.
- **Evidence:** DRC 0/0/0. `eib/silk_refs.md` (the D-64 table) is now stale; this table supersedes it.

### 2.7 CRL-6 analogue: stack-up definition

- **Change:** `(setup)` holds a `(stackup)` block for the OSH Park standard 2-layer board
  (https://docs.oshpark.com/services/two-layer/, read 2026-11-14): F.Cu and B.Cu 0.035 mm (1 oz), FR4 core 1.51 mm
  (epsilon_r 4.5 at 10 MHz, 175 Tg Kingboard KB6167F per OSH Park; loss tangent 0.02 is the KiCad default), solder
  mask purple 0.01 mm on both sides, silkscreen white on both sides, finish ENIG, board 1.6 mm. The core thickness
  is derived so that the stack sums to 1.6 mm; OSH Park states only the 1.6 mm nominal board thickness. The mask
  thickness is the KiCad default.
- **Script:** `gen/eib_stackup.py` (the pcbnew API in this build does not expose BOARD_STACKUP, so the block is
  written as text and normalized by a pcbnew load and save).
- **Evidence:** a Gerber job file exported to scratch reads BoardThickness 1.6, Finish "ENIG", both mask layers
  colour R80G0B80 (purple), legend White, copper 0.035 mm and dielectric FR4 1.51 mm. DRC 0/0/0.

### 2.8 CRL-8 analogue: NPTH holes in the OSH Park package

- **Finding:** OSH Park decides plating from the copper: "Copper under a drill means via/plated hole, no copper
  means unplated hole" (https://docs.oshpark.com/design-tools/diptrace/producing-plated-vias/, read 2026-11-14).
  OSH Park's troubleshooting page reports that a zip with several drill files is sometimes not detected correctly
  (https://docs.oshpark.com/troubleshooting/drill-issues/). OSH Park's two-layer, slot and KiCad pages do not
  address NPTH files otherwise. The single MixedPlating drill file of the KiKit OSH Park preset is therefore
  acceptable, provided that no copper lies on or around an NPTH hole.
- **Change:** the new check `gen/npth_check.py` measures, for every NPTH pad on every copper layer, the gap from the
  hole edge to the nearest copper (pads, tracks, vias, zone fills). Copper on the hole fails the check; a gap below
  0.254 mm is reported as a warning. `gen/export.sh` runs it after DRC and writes `reports/npth_check.txt`; with
  `set -e`, a failure stops the export. Comments in `gen/export.sh` record that the `kikit_oshpark` package is the
  OSH Park upload and that `drill/` keeps the separate PTH and NPTH files for other fabs. The export was not run.
- **Evidence:** EIB H1 and H2 (3.2 mm, NPTH, no annular copper): nearest copper 1.893 mm (H2) and 1.896 mm (H1) on
  both layers, pass. CR at git HEAD (read-only check): 6 NPTH holes, pass.

## 3. Final evidence

- **DRC** (`--severity-all --schematic-parity`): 0 violations, 0 unconnected items, 0 schematic parity issues.
- **Constraint check:** identical to the baseline (5 pass, 1 deviation, 2 info rows); no pass row was lost.
- **`gen/pcbdiff.py` HEAD against the working tree:** segments 332 / 332, 0 removed, 0 added; track length 500.7 mm
  unchanged; vias 93 / 93, 0 removed, 0 added; zones changed in fill only (AGND_L1_pour, AGND_L2_pour_1); 39
  footprints changed in body only.
- **Pad comparison** (scratch script over all footprints): 0 differences in pad position, size, shape, copper and
  mask layers, net, drill, fields, footprint ID or DNP attribute. The 39 footprint changes are reference-field
  position, layer or size, the pin-1 dots and the DNP paste margin only.
- **Files changed:** `eib/eib.kicad_pcb`, `eib/eib.kicad_dru`, `gen/eib_pour_rules.kicad_dru`, four footprints in
  `eib/charger_r8_eib.pretty/`, `gen/fplib.py`, `gen/export.sh`; new scripts `gen/eib_j201_pour_clearance.py`,
  `gen/eib_dnp_paste.py`, `gen/eib_pin1_marks.py`, `gen/eib_board_marking.py`, `gen/eib_wire_labels.py`,
  `gen/eib_silk_refs_r2.py`, `gen/eib_stackup.py`, `gen/npth_check.py`.

## 4. Items for the records step

1. Correct the "0.20 mm zone clearance" statements of D-28 and D-68 (the fill uses 0.1524 mm).
2. Record the J201 map, the EVM points at the E labels and the bottom-side references C201, C202, R251 and R271 in
   the assembly instructions; replace `eib/silk_refs.md` with the table of section 2.6.
3. Remove the fab README sentence on paste over DNP pads, and correct the stencil row of `eib_bom.csv` (BOM-1).
4. Record that the DNP paste margin is an instance setting that a regeneration does not reproduce.
5. Check the pin-1 dot positions on the CR before a CR library regeneration (section 2.3).
