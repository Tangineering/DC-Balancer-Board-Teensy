# CR update of 2026-11-14, phase B: silkscreen fixes

This note lists the phase B silkscreen changes to `cr/cr.kicad_pcb`, with the script that made each change and the
evidence. Copper, nets, pads and footprint positions are unchanged. No file was committed.

## 1. Baseline and method

### 1.1 Baseline

The baseline is the phase A board (`update_2026-11-14/notes_cr.md`), saved before this work as
`C:/Users/ricky/AppData/Local/Temp/claude/update_2026-11-14/phaseB/silk_cr/cr_before.kicad_pcb`. On the baseline,
kicad-cli DRC (`--severity-all --schematic-parity`) gives 0 violations, 0 unconnected items and 0 parity issues. The
constraint check (`gen/check_constraints.py cr ../cr`) gives 0 FAIL rows; its output is saved as `cc_before.md` in the
same scratch folder.

### 1.2 Method

The board was edited in place by pcbnew scripts under `gen/`. No layout, route or finish generator was run. The
scripts must run in this order to reproduce the board from git HEAD:

1. `gen/cr_pin1_marks.py`
2. `gen/cr_silk_refs_r2.py`
3. `gen/cr_wire_labels.py`
4. `gen/cr_lead_labels.py`
5. `gen/cr_j1_pin18_solid.py`
6. `gen/cr_stackup.py`
7. `gen/cr_silk_fix_r3.py` (new, phase B)
8. `gen/cr_silk_refs_report.py` (new, phase B; writes `cr/silk_refs.md`, read-only on the board)

The J101 header and separator are in `gen/cr_silk_fix_r3.py`, not in `gen/cr_wire_labels.py`. The header position
depends on the W7 "SCL" label, which `gen/cr_lead_labels.py` places after `gen/cr_wire_labels.py`. A header written by
step 3 changed the SCL placement of step 4 in a trial run, so the header moved to step 7.

**Reproduction check:** steps 1 to 7 were run on a scratch copy of the HEAD `cr/` folder. The result equals the
working-tree board line for line, except for object UUIDs. A second run of steps 3 and 7 on that result changed
nothing except UUIDs.

### 1.3 Placement rules

Every text that phase B moves or adds meets these rules (ink box from pcbnew `GetEffectiveTextShape`):

- Text height >= 0.8 mm and stroke 0.15 mm (rule `fab_silk_text`).
- Ink >= 0.10 mm from every mask opening on the same side (pad shape plus the board mask expansion).
- Ink >= 0.15 mm from every hole and >= 0.05 mm from every via drill, so that no text crosses a via drill.
- Ink >= 0.30 mm from every F.Silkscreen graphic (pin-1 dots, cathode bars, outlines, the new separator) and >= 0.10 mm
  from every other silkscreen text.
- Ink >= 0.25 mm inside the board edge.
- For a top-side reference: no overlap with the courtyard polygon of another part, no overlap with the own F.Fab body,
  and a gap to the own courtyard at least 0.10 mm smaller than the gap to any other courtyard.

A reference with no legal top-side position goes onto B.Silkscreen, mirrored, over its part. This is the phase A
convention for R107 (`gen/cr_silk_refs_r2.py`). The F.Fab `${REFERENCE}` text of the footprint stays on the assembly
drawing. On the bottom side, the ink centre must lie inside the own courtyard and nearer the own part centre than any
other part centre. Among the legal bottom positions, the script prefers zero overlap with other courtyards, then the
larger text, then the smaller offset from the part centre.

## 2. Changes

### 2.1 D2: C102c reference and the D107 cathode bar

- **Before:** the C102c reference stood at (38.52, 39.59) mm, 0.8 x 0.8 mm. Its ink ended 0.14 mm above the D107
  cathode bar (ink x 36.92-38.88 mm, y 40.17-40.33 mm), so the bar read as its underline.
- **Finding:** no top-side position meets section 1.3. C102c lies between U101, C102a, R102 and the J1 pin column.
  The probe runs relaxed the mark gap to 0.10 mm, the mask gap to 0.05 mm and the nearness margin to 0 mm, and still
  found no top-side position.
- **After:** the reference is on B.Silkscreen, mirrored, at (42.23, 39.71) mm, 0 degrees, 1.0 x 1.0 mm. The ink box
  is x 39.99-44.47 mm, y 39.09-40.24 mm, with 0.0 mm² overlap with other courtyards.
- **Result:** the nearest F.Silkscreen text to the D107 cathode bar is now the D107 reference, at 1.88 mm.

### 2.2 D3: J101 map header and separator

- **Header:** the header now reads "J101 top view", like the EIB J201 map. It is the J101 reference field followed by
  a board text "top view" on the same baseline, with the 0.48 mm word space of the string "J101 top view". Text is
  0.8 mm high, 0.6 mm character width and 0.15 mm stroke. The ink box is x 51.60-57.98 mm, y 47.24-48.45 mm, in the
  via-free band between the via rows at y 46.56 and 49.08 mm. Characters 0.8 mm wide do not fit between the W7
  "SCL" label and the map strip end (x 58.3 mm).
- **Separator:** a vertical F.Silkscreen line, 0.15 mm wide, at x 47.349 mm from y 50.16 to 56.19 mm. It runs over
  the three map rows, midway between the J1 pin-column mask openings and the map texts. The gap to the J1 mask
  openings is 0.275 mm, and the gap to the map texts is 0.276 mm. The line crosses no via drill.
- **Unchanged:** the nine map cells and their 0.75 mm distance to J1 pins 3, 4 and 5 stay as phase A placed them. The
  separator now divides the J1 column from the map.
- **Script support:** `gen/cr_wire_labels.py` now also removes the "top view" text and the separator in its
  idempotency step (function `mine()`), so that a re-run of step 3 followed by step 7 restores both.

### 2.3 Six references over another courtyard

The phase A check found six references over the courtyard of another part.

| Reference | Before (ink over) | After | Ink box (mm) |
|---|---|---|---|
| R176 | D107 | F.Silkscreen (34.11, 48.08), 0 deg, 1.0 x 1.0 mm; 0.00 mm to the own courtyard, 0.35 mm to the nearest other | x 32.35-35.93, y 47.46-48.61 |
| C102a | D107 | B.Silkscreen, mirrored, (41.01, 42.86), 90 deg, 1.0 x 1.0 mm | x 40.38-41.53, y 40.60-45.08 |
| C119 | U110 | B.Silkscreen, mirrored, (39.96, 63.88), 90 deg, 0.8 x 0.8 mm | x 39.45-40.40, y 62.41-65.35 |
| U119 | U106 | B.Silkscreen, mirrored, (38.56, 67.53), 0 deg, 1.0 x 1.0 mm | x 36.73-40.35, y 66.91-68.06 |
| C131 | U105, U106 | B.Silkscreen, mirrored, (37.66, 69.53), 0 deg, 1.0 x 1.0 mm | x 35.85-39.48, y 68.91-70.06 |
| U107 | U118 | B.Silkscreen, mirrored, (42.66, 74.23), 0 deg, 1.0 x 1.0 mm | x 40.78-44.45, y 73.61-74.76 |

- **Bottom-side references:** every bottom-side reference has 0.0 mm² overlap with other courtyards. The CR now has
  seven references on B.Silkscreen: R107 (phase A), C102c and the five of this table. The bottom side faces the MB
  after assembly, so these labels are read before the CR is plugged on.
- **R176:** the R176 ink is 0.13 mm from the C108 reference, which is vertical, and 0.38 mm from the R112 reference.

### 2.4 Board marking

The CR carried no board marking on any layer. A marking "CR r8 2026-11-14" was added on F.Silkscreen at (44.83, 85.61)
mm, 0 degrees, 0.8 x 0.8 mm, 0.15 mm stroke. The ink box is x 38.84-50.87 mm, y 85.06-86.05 mm, below J102 and clear of
every courtyard. The clearance to the nearest obstacle is 0.23 mm. The script selected the position by the largest
clearance on a 0.25 mm grid under the rules of section 1.3.

### 2.5 cr/silk_refs.md

`cr/silk_refs.md` is regenerated from the board by `gen/cr_silk_refs_report.py`. It now has a layer column and
measures gaps against the courtyard polygons; the D-58 table used the courtyard bounding boxes. It lists 54
references on F.Silkscreen, 7 on B.Silkscreen and 17 on F.Fab. The rows for W3 (now F.Silkscreen), R107, C102c, J101,
W7 and the six references of section 2.3 now show their current placement.

## 3. Evidence

- **DRC** (`--severity-all --schematic-parity`): 0 violations, 0 unconnected items, 0 schematic parity issues
  (scratch `drc_after.rpt`).
- **Constraint check:** the output is byte-identical to the baseline (scratch `cc_before.md` and `cc_after.md`). It
  has 0 FAIL rows, and no pass row was lost.
- **`gen/pcbdiff.py`, git HEAD against the working tree:** segments 692 / 692 and vias 420 / 420, none removed or
  added. The track length is 818.7 mm on both. The zone changes are the phase A fill changes only (VCHG_L1,
  GND_L1_fill).
- **`gen/pcbdiff.py`, baseline against the working tree:** 0 segments, 0 vias and 0 zones changed. 8 footprints
  changed (the 7 references and J101). The board drawings add 1 `gr_line` (the separator) and 2 `gr_text` (the header
  text and the board marking).
- **Footprint comparison** (scratch `fpcmp.py`, baseline against the working tree): 82 footprints and 277 pads. Pads,
  values, positions, the DNP attribute, the non-reference fields and the footprint graphics show 0 differences.
- **Render:** kicad-cli 3D renders of the top and bottom sides (scratch `render_top.png`, `render_bot.png`) were
  inspected. The top render shows the D107 bar with no text above it, the "J101 top view" header, the separator and
  the board marking. The bottom render shows the seven mirrored references, which read correctly from the bottom.

## 4. Files changed

- `cr/cr.kicad_pcb` (silkscreen only).
- `cr/silk_refs.md` (regenerated).
- `gen/cr_wire_labels.py`: the `mine()` idempotency step only.
- New: `gen/cr_silk_fix_r3.py`, `gen/cr_silk_refs_report.py`.

## 5. Open items

1. **W3 reference over the J1 courtyard:** the W3 reference (phase A, `gen/cr_lead_labels.py`) overlaps the J1 pin
   courtyard ring at its +x side by about 0.2 mm. The overlap is with a TSW post courtyard; whether the post hides
   the text is TODO(verify: assembled board). This reference is outside the six of the phase A list and was not moved.
2. **Bottom-side references:** seven references are now readable only before the CR is plugged on (R107, C102c,
   C102a, C119, U119, C131 and U107). The assembly instructions should state this, together with the F.Fab assembly
   drawing.
3. **Records:** the D-59 decision text, the D-12a exception list and the `gen/fab_readme.py` reference to
   `cr/silk_refs.md` must name the B.Silkscreen fallback and the board marking. `update_2026-11-14/notes_cr.md` section
   1.2 lists six scripts; the full order is now section 1.2 of this note.
4. **Phase A lead label below the 0.10 mm mask rule:** a pcbnew measurement of every F.Silkscreen board text against
   the F.Mask openings gives at least 0.607 mm for all of them except the W6 "GND" label (`gen/cr_lead_labels.py`), at
   0.086 mm. That label was placed with the phase A 0.05 mm margin and passes DRC. It was not moved; a fix needs a
   ruling on whether the 0.10 mm rule applies to phase A labels. The J101 map cells measure >= 0.701 mm.

## Fix round 1 (2026-11-15, check1 issue 12)

No board edit. D-78 now states that the "J101 top view" map belongs to J101, records the W6 "GND" label (0.086 mm
from a F.Mask opening, section 4 item 4 of this note) as a phase A exception, and lists the W3 courtyard overlap and
the tented vias under "U106" as residuals for an operator ruling on a further silkscreen pass.
