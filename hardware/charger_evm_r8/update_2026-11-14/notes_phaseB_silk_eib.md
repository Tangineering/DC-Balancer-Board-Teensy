# EIB silkscreen update of 2026-11-14, phase B: board marking (D1) and reference placement (D4)

This note lists the phase B silkscreen changes to `eib/eib.kicad_pcb`. The changes answer defects D1 and D4 of the
phase A independent check and apply the phase B text rules: text at least 0.8 mm high with a 0.15 mm stroke, at
least 0.10 mm from every mask opening, no stroke over a via drill, and at least 0.25 mm inside the board edge. No
copper, net, footprint position or library footprint was changed. No file was committed.

## 1. Files changed

- `gen/eib_board_marking.py`: fixed marking position `POS` and placement assertions (section 2).
- `gen/eib_silk_refs_r2.py`: four new placement rules and a wider bottom-side fallback (section 3).
- `eib/eib.kicad_pcb`: the board marking and the reference fields, written by the two scripts.
- `eib/silk_refs.md`: replaced; it now holds the current placement table (it held the stale D-64 table).
- `update_2026-11-14/notes_phaseB_silk_eib.md`: this note.

Scratch files (search scripts, rule checks, renders, reports) are in
`C:/Users/ricky/AppData/Local/Temp/claude/update_2026-11-14/phaseB/silk_eib/`. The board as found at the start of
phase B is saved there as `eib_before_phaseB.kicad_pcb`.

## 2. D1: board marking clear of the H1 mounting hole

- **Defect:** at (12.0, 49.05) mm the ink box of "EIB r8 2026-11-14" was x 5.89-18.19 mm, y 48.50-49.49 mm. Its
  nearest point was 3.11 mm from the H1 centre (3.5, 46.5) mm, inside the 3.55 mm keep-out. The strokes also lay
  over the drills of the stitching vias at (11.96, 49.21) and (16.46, 49.21) mm (stroke-to-drill gap 0.000 mm,
  scratch `check_silk.py` on the phase A board).
- **Constraint:** the bottom row holds 0.3 mm via drills at x 6.21, 11.96, 16.46 and 23.21 mm, y 49.21 mm
  (pcbnew dump). The 12.30 mm wide text cannot fit between two of these vias, and the J201 map above it (ink bottom
  48.18 mm) and the 0.25 mm edge band (y <= 49.75 mm) leave no other row. The strokes must therefore pass the
  drills between glyphs.
- **Change:** the text moved to POS = (14.18, 49.15) mm. A 0.01 mm search over x 12.65-17.60 mm and y 49.05-49.25 mm
  (scratch `mark_search.py`) gave this position as the one with the largest stroke-to-drill gap.
- **Result:** ink box x 8.07-20.37 mm, y 48.60-49.59 mm. Gap to the H1 centre 5.03 mm (rule >= 3.6 mm); H2 is
  farther. Stroke-to-drill gap 0.045 mm. Edge gap and the 0.40 mm gap to the J201 map hold. The script asserts all
  four conditions on every run and saves only on a change.
- **Open:** the 0.045 mm stroke-to-drill gap is smaller than a typical silkscreen registration tolerance
  (TODO(verify: OSH Park silkscreen registration tolerance)). The vias are tented, so a small overlap would clip a
  stroke edge only.

## 3. D4: references nearer a neighbour than their own part

### 3.1 Changes to `gen/eib_silk_refs_r2.py`

1. **Mask gap 0.10 mm** (was 0.05 mm), from the phase B rule. On the phase A board, 15 references were 0.051-0.092
   mm from a mask opening (scratch `check_silk.py`).
2. **No stroke over a via drill** (`DRILL_HARD`), tested on the stroke outline. On the phase A board, the strokes of
   C203, C204, R258, U201 and U202 lay over a via drill (gap 0.000 mm).
3. **Spread pass:** among the candidates of equal cost (within 0.005), each reference takes the one with the
   largest gap to the other references. Own-part gaps and the score do not change.
4. **Orphan rule:** a reference whose text centre lies nearer a fitted part without a top-side label than its own
   part leaves the top side. The random search scores each assignment after this rule.
5. The report now carries the via flag from the candidate; the phase A test `cost >= 2.0 + d_own` failed by
   rounding, so the phase A report omitted the via crossings of C203 and R258. A second flag, "text centre nearer
   another part", is reported for information.
6. The bottom-side fallback tries both text widths on a +/-1.0 mm grid (R252 found no 0.8 mm wide position on the
   +/-0.6 mm grid) and keeps 0.80 mm between two bottom-side texts (at 0.40 mm, "C202" and "R254" read as one word
   in the bottom render).

### 3.2 Items of D4

- **U201 beside the unlabelled C202:** no better top-side position exists. U201 had 10 candidates under the phase A
  rules, all beside C202, and none under the drill rule; the text centre of every one lay nearer C202 than U201.
  U201 now has a bottom-side text and an F.Fab reference. C202 has the same; its only top-side candidates stood
  level with the unlabelled R254, which the orphan rule rejects. Note that U201 is the only SSOP-8 (DCT) part on the
  EIB and carries a pin-1 dot, so the land pattern identifies it.
- **"R253" ending next to "R273":** fixed. The ink gap is 0.89 mm (was 0.29 mm). R273 sits under its own part, 0.12
  mm from its courtyard; R253 stands vertical below the right end of R253, 0.06 mm from its courtyard.
- **U203 (DNP) and Q203 pin-1 dots 0.98 mm apart:** left unchanged. The dots are library graphics of the SOT-23-6 and
  SOT-23 footprints (`gen/fplib.py` `PIN1_DOT`, `gen/eib_pin1_marks.py`); a per-instance change gives a
  `lib_footprint_mismatch` in DRC, and a library change also moves the U204 dot and the future CR dots. Both
  scripts named in the brief do not touch footprint graphics. U203 is not fitted, and the SOT-23 land pattern of
  Q203 (two pads on one side, one on the other) admits one orientation only, so the near dot cannot cause an
  assembly error.

### 3.3 Trade-off of the stricter rules

The phase A run placed 22 of the 26 fitted references on the top side; this run places 18. The parts with a
bottom-side text are C201, C202, R251, R252, R254, R271, U201 and U202 (phase A: C201, C202, R251, R271). The
losses have three causes, measured on scratch copies:

- the mask gap of 0.10 mm leaves R254 with no candidate;
- the drill rule leaves U201 with no candidate and R252 without a free position (20 fitted);
- the orphan rule then removes C202 (beside the unlabelled R254) and U202 (beside the unlabelled R252) (18 fitted).

A 4000-trial search gives the same 18. Without the orphan rule, 20 fitted references stay on top, but "C202"
stands level with R254 and reads as its label (the D4 defect). The orchestrator may prefer the phase A rule set
(22 fitted, 15 references within 0.10 mm of a mask opening, 5 over a via drill); the constants `MASK_GAP`,
`DRILL_HARD` and the `orphan_check()` call select it.

### 3.4 Marginal stroke-to-drill gaps

The strokes of R258 and R253 pass 0.003 mm and 0.006 mm from a via drill; C204 0.023 mm; U202 (bottom) 0.054 mm;
the board marking 0.045 mm. A margin of 0.05 mm at the stroke level was tried: it removes U202 and R253 from the
top side (19 fitted, before the orphan rule). The margin is left at 0 mm (strokes clear of the drill).

## 4. Verification

- **DRC** (`kicad-cli pcb drc --severity-all --schematic-parity`): 0 violations, 0 unconnected items, 0 schematic
  parity issues.
- **Constraint check** (`gen/check_constraints.py eib ../eib`): identical to the report before phase B (5 pass,
  1 deviation D-13, 2 info rows).
- **`gen/pcbdiff.py` HEAD against the working tree:** segments 332 / 332, 0 removed, 0 added; track length 500.7 mm;
  vias 93 / 93; zones AGND_L1_pour and AGND_L2_pour_1 changed in fill only (phase A refill); 40 footprints changed
  in body only (39 in phase A; C202 is new because its reference field moved).
- **Line census against the board at the start of phase B:** only `(at ...)`, `(size ...)`, `(thickness ...)`,
  text layer, text, effects and UUID lines changed; no zone, pad, track or via line changed.
- **Rule check** (scratch `check_silk.py`, stroke outlines): 36 F.Silkscreen texts and 8 bottom-side reference
  texts, 0 failures of height, stroke, mask gap 0.10 mm, via drill, edge gap 0.25 mm and hole gap 3.6 mm.
- **Idempotency:** a second run of both scripts gives the same report and a board identical except for the UUIDs
  of the bottom-side texts, which the script recreates on each run (phase A behaviour).
- **Renders** (`kicad-cli pcb render`, top and bottom) were inspected: the marking stands clear of the H1 keep-out;
  no top-side reference stands level with an unlabelled part; the bottom-side texts read as separate words.

## 5. Open items

1. Decide between the stricter rule set (18 fitted on top) and the phase A rule set (22 fitted on top); see
   section 3.3. Record the decision in LAYOUT_DECISIONS.md.
2. Record the bottom-side references C201, C202, R251, R252, R254, R271, U201 and U202 in the assembly
   instructions (the phase A item listed four).
3. TODO(verify: OSH Park silkscreen registration tolerance) for the 0.003-0.054 mm stroke-to-drill gaps.
4. If a pin-1 dot change is wanted for U203/Q203, make it in `gen/fplib.py` with a CR clearance check (outside this
   brief).
