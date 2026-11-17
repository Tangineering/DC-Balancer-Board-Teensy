# CR update of 2026-11-14: changes from the 2026-11-14 review

This note lists each change made to `cr/cr.kicad_pcb` in response to `REVIEW_2026-11-14.md`, with the script that
made it and the evidence. It is the input for the records step (decisions, README, fab README, BOM). No fab package
was exported and no file was committed.

## 1. Scope and method

### 1.1 Baseline

The baseline is `cr/cr.kicad_pcb` at git HEAD (last board commit `014c745`, D-69). The working-tree board was equal to
HEAD at the start of this update, so every hand adjustment recorded in HEAD (the D-65 via merges, the D-66 wire pads,
the D-69 U101 paste windows and the earlier manual edits) is the starting point and is kept. On the baseline,
kicad-cli DRC (`--severity-all --schematic-parity`) gives 0 violations, 0 unconnected items and 0 parity issues. The
constraint check (`gen/check_constraints.py cr ../cr`) gives 129 rows, of which 109 are pass rows and 0 are FAIL rows.

### 1.2 Method

The board was edited in place by one idempotent pcbnew script per change, saved under `gen/`. No generator was run
(no `make_board.sh`, `pcbbuild.py`, `route.py`, `trim_cr.py`, finish or stitching script). Nets, references, values,
footprint library IDs, footprint positions and the DNP attributes are unchanged. After every change, DRC,
`gen/pcbdiff.py` against the previous state and, where copper or pours changed, the constraint check were run. The
scripts must be run in this order to reproduce the board from HEAD:

1. `gen/cr_pin1_marks.py`
2. `gen/cr_silk_refs_r2.py`
3. `gen/cr_wire_labels.py`
4. `gen/cr_lead_labels.py`
5. `gen/cr_j1_pin18_solid.py`
6. `gen/cr_stackup.py`

A second run of all six scripts on the finished board changed nothing (`gen/pcbdiff.py`: 0 segments, 0 vias, 0
footprints, 0 zones and 0 other objects differ; `cr/cr.kicad_dru` byte-identical; no library file changed).

The EIB update ran before this one. This update builds on its `gen/fplib.py` (`_pin1_dot`, `PIN1_DOT`) and on its
`gen/export.sh` NPTH gate. The EIB library footprints regenerated from the edited `gen/fplib.py` with `BOARD = "eib"`
(SSOP-8, SC70-5, SOT-23, SOT-23-6) are line-identical to the files the EIB update wrote, so the CR changes to
`gen/fplib.py` do not alter the EIB.

## 2. Changes

### 2.1 INT-2 / EIL-1: J101 pin and net map

- **Side:** the CR plugs onto the MB with the J1 header pins on the underside, and the W5 leads are soldered with the
  CR in place (DOC-4), so only the top side is visible at that step. The map is on F.Silkscreen.
- **Change:** the J101 pads cannot carry labels beside them (0.74 mm pad gaps; parts and references on every side of
  the grid). A 3 x 3 map of "pin net" cells sits in the free strip to the right of the J1 pin column, x 47.70-58.30 mm.
  Each map row is level with its pad row (y 50.63, 53.17 and 55.71 mm), and the columns follow the pad columns from
  left to right as seen from the top. These rows lie in the via-free bands between the rows of /GND stitching vias, so
  no cell crosses a via. The J101 reference field moved from row 1 of the strip to the map header, centred over the map
  at (53.02, 47.79) mm. The cells are built from the pads and nets of the board, so they agree with `cr/cr.net` and
  Table D-66:

  | Row (top view) | Column 1 | Column 2 | Column 3 |
  |---|---|---|---|
  | 1 (y 50.63) | 1 3V3 | 3 GND | 2 3V3 |
  | 2 (y 53.17) | 5 CE | 7 RLA | 4 STAT |
  | 3 (y 55.71) | 9 GND | 8 RLB | 10 RFC |

  Short names: 3V3 = /J3V3_1 and /J3V3_2, GND = /GND, STAT = /STAT, CE = /CE_DRV_J, RLA = /ILIM_REL_A,
  RLB = /ILIM_REL_B, RFC = /RFC_OFF_J (the same short names as the EIB J201 map).
- **Text size:** 0.8 mm high, 0.15 mm stroke, 0.6 mm character width. The 0.8 mm-wide characters do not fit the strip
  with the 0.6 mm minimum gap between columns; the column gap is 0.89 mm. The C102b reference stays where it was, to
  the left under the header.
- **Script:** `gen/cr_wire_labels.py`.
- **Evidence:** DRC 0/0/0. `gen/pcbdiff.py`: 0 tracks, 0 vias, 0 zones changed; 9 board texts added; J101 changed in
  its reference field only.

### 2.2 CRL-3 / INT-5: pin-1 and polarity marks

- **Change:** a filled F.SilkS pin-1 dot (radius 0.10 mm, stroke 0.15 mm, outer diameter 0.35 mm) beside pad 1 of
  U101 (VQFN-24), D104-D106 (SOT-23, BAV199), U102, U103, U107, U119, U120 (SOT-23-6) and U105, U106, U110, U118 (DCT
  SSOP-8); a 0.15 mm F.SilkS cathode bar, 1.8 mm long, beyond the toe of pad 1 (K) of D103 and D107 (SMA). Pad 1 is
  the cathode of both SMA diodes (D103 pad 1 /VCHGOUT, D107 pad 1 /VCHGIN, `gen/netlist.py`).
- **Positions (footprint coordinates):** SOT-23 (-1.9, -1.5), the shared EIB position; SOT-23-6 (-1.55, -1.55),
  SSOP-8 (-2.75, -1.35) and VQFN-24 (-2.4, -2.4), CR overrides; SMA bar x -3.45, y -0.9 to 0.9. The shared SOT-23-6
  position (-2.0, -1.5) put the dot over the drill of a tented /GND stitching via at U102, U107 and U119, and the
  shared SSOP-8 position (-2.75, -1.45) came within 0.018 mm of a via drill at U110. The CR positions were selected by
  a search over every instance of each package.
- **Board positions and gaps** (gap to the nearest mask opening, which is the own pad 1 except at U101, where it is pin 24 of the same pin-1 corner; gap to the nearest via
  drill):

  | Part | Mark at (mm) | Mask gap (mm) | Via-drill gap (mm) |
  |---|---|---|---|
  | U101 | (39.300, 38.750) | 0.80 | 0.17 |
  | D104 | (23.959, 61.750) | 0.17 | 0.27 |
  | D105 | (27.184, 57.975) | 0.17 | 0.38 |
  | D106 | (31.484, 57.975) | 0.17 | 0.15 |
  | U102 | (27.409, 68.575) | 0.07 | 0.33 |
  | U103 | (31.659, 68.575) | 0.07 | 0.61 |
  | U107 | (41.059, 72.725) | 0.07 | 0.33 |
  | U119 | (40.159, 68.575) | 0.07 | 0.25 |
  | U120 | (35.909, 68.575) | 0.07 | 0.24 |
  | U105 | (36.359, 75.725) | 0.12 | 0.15 |
  | U106 | (39.459, 69.575) | 0.12 | 0.43 |
  | U110 | (41.109, 68.575) | 0.12 | 0.11 |
  | U118 | (35.259, 76.225) | 0.12 | 0.10 |
  | D103 | bar from (36.950, 36.060) | 0.07 | 0.58 |
  | D107 | bar from (38.800, 40.250) | 0.07 | 0.73 |

  Several dots overlap the annular ring of a tented via under the mask; none overlaps a via drill. For each dot except
  the U101 dot, the nearest pad on the board is pad 1 of its own part; the U101 dot sits at the corner of pins 1 and 24.
- **Library:** `gen/fplib.py` gained `PIN1_DOT_CR`, `CATHODE_BAR_CR`, `_pin1()` and `_cathode_bar()`; `ssop_ti()`,
  `vqfn24()` and the `SMA`, `SOT-23`, `SOT-23-6` and `SC70-5` entries of `CUSTOM` now take their mark from these. The
  five affected files of `cr/charger_r8_cr.pretty/` were written from `gen/fplib.py`; each differs from git HEAD by the
  one mark line (the `tedit` stamp and the line ends are kept). The rest of the library was not regenerated. The
  instances on the board were then given the same mark, so DRC reports no library mismatch.
- **W-lead labels:** see section 2.4.
- **Script:** `gen/cr_pin1_marks.py`.
- **Evidence:** DRC after this step: 1 violation (`silk_overlap`, the U101 dot under the C102c reference), removed by
  section 2.3; DRC 0/0/0 after section 2.3. `gen/pcbdiff.py`: 15 footprints changed in body only, 0 tracks, 0 vias,
  0 zones.
- **Design-record impact:** D-12 / D-12a kept these parts free of silkscreen, with the marks on F.Fab. This change is
  an exception to D-12a for the 13 ICs and diodes listed.

### 2.3 CRL-7 (and the U101 dot clearance): references re-placed

- **R107:** its reference lay fully inside the J102 body outline (F.Fab x 46.06-54.93 mm, y 64.38-83.63 mm), 6 mm from
  R107, and is hidden once J102 is fitted. No unambiguous top-side position exists within 4 mm of R107 (every legal
  position lies nearer another courtyard than its own). The reference is now on B.Silkscreen, mirrored, 1.0 x 1.0 mm,
  centred over R107 at (42.63, 62.25) mm (the EIB fallback for C201, C202, R251 and R271). It crosses a tented via. The
  bottom side faces the MB after assembly, so the label is read before the CR is plugged on.
- **U106 and C116:** a pcbnew text-box check shows that their references end before the J102 body (U106 ink x
  44.85-45.80 mm, C116 x 43.86-45.01 mm, body from x 46.06 mm). They are not hidden and were not moved (the review
  verifier note reached the same result).
- **C102c:** its reference at (37.60, 38.68) mm covered the pin-1 corner of U101 (DRC `silk_overlap` with the new U101
  dot). It now sits at (38.52, 39.59) mm, 0.8 x 0.8 mm, 0.00 mm from the C102c courtyard and 0.05 mm from the nearest
  other courtyard. It crosses a tented via drill.
- **Rules:** a 0.05 mm grid search within 4.0 mm of the own courtyard; ink >= 0.05 mm from every F.Mask opening,
  >= 0.15 mm from every hole, >= 0.10 mm from every other F.Silkscreen item and >= 0.25 mm from the board edge
  (`gen/silk_refs.py` margins); preferred in order: no overlap with another courtyard, nearer the own courtyard than
  any other, clear of via drills, larger text, nearer the own courtyard. No other reference was moved by this script.
- **Script:** `gen/cr_silk_refs_r2.py`.
- **Evidence:** DRC 0/0/0.

### 2.4 INT-5 / CRL-3: W-lead labels

- **W1, W2, W4, W6:** their references were already on F.Silkscreen and are unchanged. W5 is the J101 grid (section
  2.1).
- **W3:** the reference moved from F.Fab to F.Silkscreen at (22.50, 54.50) mm, 0.8 x 0.8 mm, vertical, between the J1
  pin column and the W3 pad, 0.06 mm from the W3 pad mask opening (the nearest pad).
- **W6 per-hole labels:** "TS" beside pad 1 (TS_EXT) at (26.06, 41.27) mm and "GND" beside pad 2 at (25.36, 38.63) mm,
  both vertical, 0.8 x 0.8 mm, on the +x side of the hole and level with it. "GND" crosses a tented via.
- **W7 per-hole labels:** "SDA" (pad 3) at (51.06, 41.59) mm, "GND" (pad 2) at (51.51, 44.68) mm and "SCL" (pad 1) at
  (51.06, 46.67) mm, 0.8 x 0.8 mm, on the +x side of each hole and level with it ("SDA" and "SCL" vertical, so that
  they keep clear of the via drills). The W7 reference stood level with pad 3; it moved to the +x side of the label
  column, vertical, at (53.51, 44.13) mm, level with pad 2.
- **Rules:** as in section 2.3; in addition, each label must be nearer its own pad than any other pad, and each W6/W7
  label stands on the +x side of its hole with its centre within 0.3 mm of the hole centre in y. The full net names fit
  everywhere; the single-letter fallback of INT-5 was not needed.
- **Script:** `gen/cr_lead_labels.py`.
- **Evidence:** DRC 0/0/0. `gen/pcbdiff.py`: W3 and W7 changed in their reference fields only; 5 board texts added.

### 2.5 CRL-4: J1 pin 18 solid zone connection

- **Basis:** VCHG has no inner-layer copper, so the whole pin-18 current crosses the F.Cu connection to the VCHG_L1
  pour. Design document A.8 / H.22: 3.21 A battery-side current shared 60/40 by pins 18 and 19, that is 1.93 A per
  pin; A.8 asks for VCHG copper >= 2.0 mm wide on 1 oz.
- **Before:** the zone thermal relief (0.6 mm spokes at 45 degrees, 0.3 mm gap) reached pin 18 on two diagonals only:
  1.22 mm of copper on a ring of radius 1.10 mm around the pad (pin 19: 2.43 mm). IPC-2152 baseline fit
  (`r9_calc.py ipc2152_area_mil2`, 35 um counted as clad only, long-conductor basis): 1.22 mm = 66.2 mil² carries
  2.09 A at a 10 degC rise; the rise is 8.3 degC at 1.93 A and 27.7 degC at 3.21 A (pin 19 open or a poor joint). The
  neck meets the 10 degC basis with an 8 % current margin only and does not meet the A.8 2.0 mm rule.
- **Change:** a board rule `cr_J1_pin18_solid` in `cr/cr.kicad_dru` (condition `A.Type == 'Pad' &&
  A.memberOfFootprint('J1') && A.Pad_Number == '18'`, constraint `zone_connection solid`). A DRC rule was used instead
  of a pad override, so the J1 instance stays equal to its library footprint and `gen/fplib.py` needs no change. All
  16 zones were refilled with the board loaded beside its own `cr.kicad_pro` and `cr.kicad_dru`. Pin 19 and W3 keep
  their thermal reliefs.
- **After:** 4.07 mm of copper on the same ring (220.8 mil²): a rise of 2.1 degC at 1.93 A and 6.6 degC at 3.21 A on
  the same basis. The VCHG_L1 fill grew from 12.489 to 15.220 mm²; the GND_L1_fill shrank from 1499.920 to
  1499.684 mm² at its boundary with the VCHG pour.
- **Control:** a refill of the pre-change board without the rule changed no zone (`gen/pcbdiff.py`: 0 zones), so the
  two fill changes are caused by the rule alone.
- **Hand-soldering consequence:** pin 18 is a TSW post soldered from the top side. With the solid connection, the joint
  heats the whole F.Cu VCHG pour, so it needs more heat than pin 19 or W3 (a higher iron setting or a larger tip, and
  a longer dwell). The assembly instructions should state this.
- **Regeneration:** `gen/make_board.sh` copies `tools/pcb/fab_rules/fab_4layer_oshpark_only.kicad_dru` over
  `cr/cr.kicad_dru`; `gen/cr_j1_pin18_solid.py` must then be re-run. `cr/cr.kicad_dru` is no longer identical to the
  fab rule file (it was, per the CRL-5 verifier note).
- **Script:** `gen/cr_j1_pin18_solid.py`.
- **Evidence:** DRC 0/0/0. `gen/pcbdiff.py`: 0 tracks, 0 vias; zones VCHG_L1 and GND_L1_fill changed in fill only.
  Constraint check: 129 rows, 109 pass, 0 FAIL; the rule, item and result columns are identical to the baseline; six
  D-56 F.Cu-escape rows report a "free" area 0.13 mm² smaller (for example U101.6 1055.09 -> 1054.96 mm²), all pass.

### 2.6 CRL-6: OSH Park 4-layer stack-up

- **Change:** `(setup)` holds a `(stackup)` block for the OSH Park standard 4-layer board
  (https://docs.oshpark.com/services/four-layer/, read 2026-11-15): outer copper 1 oz clad and plated, 0.0432 mm
  (1.7 mil) finished; inner copper 0.5 oz clad, 0.0175 mm; L1-L2 and L3-L4 prepreg FR408HR 2113, 0.1999 mm, Dk 3.61
  at 1 GHz; L2-L3 core FR408HR, 0.9906 mm; solder resist purple (PSR-4000BN), 0.0152 mm, both sides; silkscreen white;
  finish ENIG. OSH Park states no loss tangent; the KiCad default 0.02 is kept. The listed layers sum to 1.542 mm
  against the 1.6 mm nominal; the figures are entered as the page states them, and the board thickness stays 1.6 mm.
  KiCad keeps no silkscreen thickness.
- **Note on copper:** the review text and D-29 state "1 oz outer"; the OSH Park page gives the finished outer
  thickness as 1.7 mil (0.0432 mm, clad and plated). The IPC-2152 figures of this note and of R9.H26 count only the
  35 um clad, which is conservative.
- **Script:** `gen/cr_stackup.py` (the block is written as text and normalized by a pcbnew load and save).
- **Evidence:** a Gerber job file exported to scratch reads BoardThickness 1.6, Finish "ENIG", mask colour R80G0B80
  (purple), legend White, copper 0.0432 / 0.0175 / 0.0175 / 0.0432 mm, dielectrics 0.1999 / 0.9906 / 0.1999 mm.
  DRC 0/0/0. `gen/pcbdiff.py`: setup only.

### 2.7 CRL-8: NPTH holes in the OSH Park package

- **Decision applied:** the EIB update added `gen/npth_check.py` and a gate in `gen/export.sh` that runs it on `$PCB`
  for every board (EIB notes section 2.8: OSH Park decides plating from the copper under the drill, so the merged
  MixedPlating drill file of the KiKit OSH Park preset is acceptable when no copper lies on an NPTH hole). The gate is
  not board-specific and already covers the CR export; no CR change was needed.
- **Evidence (final board):** 6 NPTH holes, result pass. J102 pegs (1.02 mm): nearest copper 0.254 mm on F.Cu, In1.Cu
  and B.Cu (GND zones), 0.319-0.344 mm on In2.Cu; MH1-MH4 (3.70 mm): 2.131-2.201 mm. The J102 peg gap equals the
  0.254 mm warning threshold of the check and passes.

### 2.8 CRL-5 and DOC-8: fab README generator

`gen/fab_readme.py` regenerates the package README at the next export; its text defects were corrected (no README
was regenerated in the committed packages):

- **Design rules row (CRL-5):** it now names the board's own rule file (`cr/cr.kicad_dru` = the OSH Park-only fab
  rule file plus the J1 pin-18 rule; `eib/eib.kicad_dru` = the 2-layer fab rule file plus the D-68 / EIL-0 pour rule)
  and separates the rule minima (CR: 0.127 mm track and clearance, 0.254 mm hole, 0.1016 mm annular ring, 0.381 mm
  copper to edge) from the design values (0.1524 mm net-class default, 0.127 mm at necks only, via 0.6 / 0.3 mm with
  a 0.15 mm ring).
- **Solder mask row (CRL-5):** for the CR it states that the nine 0.3 mm U101 exposed-pad through-holes (footprint
  pad 25, not vias) are open on F.Cu inside the 2.7 mm exposed-pad mask opening and tented on B.Mask only.
- **Section numbering (CRL-5, DOC-8):** the comparison section is numbered 5 when the board has no DNP part (the CR),
  so the sections run 1 to 5 without a gap.
- **EIB DNP stencil text (EIB-7 / DOC-8):** the EIB README now states that each DNP footprint carries a -2.0 mm paste
  margin (`gen/eib_dnp_paste.py`), so the stencil has no aperture on the DNP pads; the former sentence "a paste stencil
  prints on the empty DNP pads" remains only for a board without that margin.
- **EIB size row (DOC-8):** the outline decision is cited as D-25 (it read D-13, the CR divider strip).
- **Evidence:** the generator was run on scratch copies of `fab/cr_2026-11-13f` and `fab/eib_2026-11-13c`; the CR
  README sections read 1 to 4 (no comparison was requested), the EIB README 1 to 5, and the rows read as above.

## 3. Final evidence

- **DRC** (`--severity-all --schematic-parity`): 0 violations, 0 unconnected items, 0 schematic parity issues.
- **Constraint check:** 129 rows, 109 pass, 0 FAIL, identical rule / item / result columns to the baseline; no pass
  row was lost.
- **`gen/pcbdiff.py` HEAD against the working tree:** segments 692 / 692, 0 removed, 0 added; track length 818.7 mm
  unchanged; vias 420 / 420, 0 removed, 0 added; zones VCHG_L1 and GND_L1_fill changed in fill only (section 2.5);
  20 footprints changed in body only (C102c, D103-D107, J101, R107, U101, U102, U103, U105, U106, U107, U110, U118,
  U119, U120, W3, W7).
- **Pad comparison** (scratch script over all footprints, HEAD against the working tree): 276 pads, 0 differences in
  position, size, shape, net, drill, layers, zone connection or mask and paste margins; 82 footprints, 0 differences in
  library ID, position, orientation, value, DNP attribute, layer or field text.
- **Silkscreen:** every new text is 0.8 mm high with a 0.15 mm stroke (the moved R107 reference 1.0 mm); every new line
  and dot has a 0.15 mm stroke. DRC includes the silk-to-mask, silk-to-edge, silk-overlap and text-size checks.
- **Files changed:** `cr/cr.kicad_pcb`, `cr/cr.kicad_dru`, five footprints in `cr/charger_r8_cr.pretty/` (D_SMA,
  SOT-23, SOT-23-6, DCT SSOP-8, VQFN-24), `gen/fplib.py`, `gen/fab_readme.py`; new scripts `gen/cr_pin1_marks.py`,
  `gen/cr_silk_refs_r2.py`, `gen/cr_wire_labels.py`, `gen/cr_lead_labels.py`, `gen/cr_j1_pin18_solid.py`,
  `gen/cr_stackup.py`.

## 4. Items for the records step

1. Record the J101 map (section 2.1) and the W3, W6 and W7 labels in the assembly instructions, together with the EIB
   J201 map; the two maps differ by design (Table D-66).
2. Record the D-12a exception for the CR pin-1 dots and cathode bars (section 2.2) and the CR overrides of
   `PIN1_DOT` in `gen/fplib.py`.
3. `cr/silk_refs.md` (D-59) is stale for W3 (now on F.Silkscreen), R107 (now on B.Silkscreen), C102c, J101 and W7; the
   fab README status text of `gen/fab_readme.py` still cites `cr/silk_refs.md` as the list of references on F.Fab.
4. Record the J1 pin-18 solid connection, its IPC-2152 basis and its hand-soldering consequence (section 2.5), and that
   `cr/cr.kicad_dru` now differs from the fab rule file; a regeneration must re-run `gen/cr_j1_pin18_solid.py`.
5. Record the OSH Park outer copper as 0.0432 mm finished in the stack-up (section 2.6).
6. CRL-5 / DOC-8 text corrections are in `gen/fab_readme.py`; the next export regenerates the README. The DOC-8 items
   outside the generator (the superseded banner on `fab/eib_2026-11-11`, design-doc lines 490, 1663 and 4045) are not
   changed by this update.
7. Not changed by this update: INT-0 / EIB-1 (the GND pads next to the 100 ohm drivers on the J101 grid), which needs a
   copper or BOM ruling.
