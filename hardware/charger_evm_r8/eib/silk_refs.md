# EIB reference designator placement (2026-11-14)

This table lists the placement of every C, R, Q and U reference and of the J201 reference on `eib/eib.kicad_pcb`. It
replaces the D-64 table. `gen/eib_silk_refs_r2.py` places the references and prints the table (run from
`hardware/charger_evm_r8` with the pcbnew venv: `python gen/eib_silk_refs_r2.py [report.md]`); the rules are in
the docstring of that script.

## 1. Placement rules

- Text is 0.8 mm high with a 0.15 mm stroke; the width is 0.8 mm, or 0.6 mm where no 0.8 mm wide position exists.
- The text ink box keeps 0.10 mm from every mask opening, 0.15 mm from every pad drill, 0.10 mm from every
  silkscreen graphic, 0.40 mm from every board text, 0.25 mm from every other reference and 0.25 mm from the board
  edge. It does not overlap a courtyard.
- No text stroke lies over a via drill. The test is made on the stroke outline, so an ink box can span a drill.
- The gap to every other courtyard is at least max(2 x d_own, d_own + 0.15 mm), with d_own <= 2.0 mm the gap to the
  own courtyard.
- A reference whose text centre lies nearer a fitted part without a top-side label than its own part leaves the top
  side.
- A fitted part without a top-side reference has its reference on F.Fab only, and the assembly guide
  (`assembly_guide/eib/`) shows it. The same holds for a reference whose ink lies more than 1.0 mm from its own pads
  or nearer the pads of another part (operator rulings 2026-11-17, D-97). (**Superseded 2026-11-17, D-97:** "has its
  reference on F.Fab and a mirrored B.Silkscreen text over the part, read from the bottom. Two bottom-side texts keep
  0.80 mm from each other.")

## 2. Result

On F.Silkscreen: 24 of 38 references, 17 of the 26 fitted parts among them. Fitted parts with the reference on F.Fab
only, shown in the assembly guide: C201, C202, R251, R252, R254, R271, U201 and U202 (their bottom texts were removed,
D-97) and Q202 (its label lay nearer the pads of R260, 0.33 mm, than its own, 0.80 mm; MARGINAL, D-97).
(**Superseded 2026-11-17, D-97:** "25 of 38 references, 18 of the 26 fitted parts among them. Fitted parts with a
bottom-side text: C201, C202, R251, R252, R254, R271, U201 and U202.") DNP parts with the reference on F.Fab only: C203, R259, R264,
R265 and U203. U201 is the only SSOP-8 (DCT) part and U202 the only SC70-5 (DCK) part on the EIB; both carry a
pin-1 dot.

The Note column flags two conditions. "Crosses a tented via" means that the ink box comes within 0.05 mm of a via
drill; the strokes stay clear of the drill. "Text centre nearer another part" means that the centre of the ink box
lies nearer another courtyard than its own. This flag is information only; the courtyard gap rule of section 1
decides the placement.

## 3. Placement table

Gaps in mm. A gap of 0.00 mm is a gap below 0.005 mm; no ink box overlaps a courtyard.

| Reference | DNP | Text w x h (mm) | Angle (deg) | Gap to own courtyard (mm) | Gap to nearest other courtyard (mm) | Note |
|---|---|---|---|---|---|---|
| C201 |  | 0.8 x 0.8 | 0 | - | - | F.Fab only; assembly guide (bottom text removed 2026-11-17, D-97) |
| C202 |  | 0.8 x 0.8 | 0 | - | - | F.Fab only; assembly guide (bottom text removed 2026-11-17, D-97) |
| C203 | DNP | - | - | - | - | F.Fab (no unambiguous silkscreen position) |
| C204 | DNP | 0.6 x 0.8 | 0 | 0.11 | 0.34 | crosses a tented via; text centre nearer another part |
| C205 |  | 0.8 x 0.8 | 0 | 0.11 | 0.48 | text centre nearer another part |
| J201 |  | 0.8 x 0.8 | 0 | 0.13 | 0.69 |  |
| Q201 |  | 0.8 x 0.8 | 90 | 0.12 | 0.96 |  |
| Q202 |  | - | - | - | - | F.Fab only; assembly guide (MARGINAL label moved 2026-11-17, D-97; was 0.8 x 0.8, 0 deg, gaps 0.02 / 0.17) |
| Q203 |  | 0.8 x 0.8 | 0 | 0.05 | 0.59 |  |
| R250 |  | 0.8 x 0.8 | 0 | 0.15 | 0.37 | text centre nearer another part |
| R251 |  | 0.8 x 0.8 | 0 | - | - | F.Fab only; assembly guide (bottom text removed 2026-11-17, D-97) |
| R252 |  | 0.8 x 0.8 | 0 | - | - | F.Fab only; assembly guide (bottom text removed 2026-11-17, D-97) |
| R253 |  | 0.8 x 0.8 | 90 | 0.06 | 0.27 | crosses a tented via; text centre nearer another part |
| R254 |  | 0.6 x 0.8 | 0 | - | - | F.Fab only; assembly guide (bottom text removed 2026-11-17, D-97) |
| R255 |  | 0.6 x 0.8 | 0 | 0.14 | 0.34 |  |
| R257 |  | 0.8 x 0.8 | 90 | 0.10 | 0.49 | crosses a tented via; text centre nearer another part |
| R258 | DNP | 0.8 x 0.8 | 0 | 0.29 | 0.66 | crosses a tented via |
| R259 | DNP | - | - | - | - | F.Fab (no unambiguous silkscreen position) |
| R260 | DNP | 0.8 x 0.8 | 0 | 0.05 | 1.84 |  |
| R261 | DNP | 0.8 x 0.8 | 0 | 0.10 | 0.26 | text centre nearer another part |
| R262 | DNP | 0.8 x 0.8 | 0 | 0.01 | 0.84 | text centre nearer another part |
| R263 | DNP | 0.6 x 0.8 | 90 | 0.07 | 0.26 |  |
| R264 | DNP | - | - | - | - | F.Fab (no unambiguous silkscreen position) |
| R265 | DNP | - | - | - | - | F.Fab (no unambiguous silkscreen position) |
| R266 |  | 0.8 x 0.8 | 0 | 0.09 | 2.40 |  |
| R267 |  | 0.8 x 0.8 | 0 | 0.12 | 0.35 |  |
| R268 |  | 0.8 x 0.8 | 90 | 0.11 | 0.42 | text centre nearer another part |
| R269 |  | 0.8 x 0.8 | 0 | 0.12 | 0.30 |  |
| R270 |  | 0.8 x 0.8 | 0 | 0.05 | 1.84 |  |
| R271 |  | 0.8 x 0.8 | 90 | - | - | F.Fab only; assembly guide (bottom text removed 2026-11-17, D-97) |
| R273 |  | 0.8 x 0.8 | 0 | 0.12 | 1.01 |  |
| R274 |  | 0.8 x 0.8 | 0 | 0.08 | 0.60 |  |
| R275 |  | 0.6 x 0.8 | 90 | 0.14 | 0.44 |  |
| R276 |  | 0.8 x 0.8 | 0 | 0.09 | 0.33 |  |
| U201 |  | 0.8 x 0.8 | 0 | - | - | F.Fab only; assembly guide (bottom text removed 2026-11-17, D-97) |
| U202 |  | 0.8 x 0.8 | 90 | - | - | F.Fab only; assembly guide (bottom text removed 2026-11-17, D-97) |
| U203 | DNP | - | - | - | - | F.Fab (no unambiguous silkscreen position) |
| U204 | DNP | 0.6 x 0.8 | 0 | 0.00 | 0.25 | text centre nearer another part |

## 4. E-pad labels (phase C, 2026-11-15)

`gen/eib_silk_fix_r3.py` writes the E-pad labels after the references (proposed decision D-86; REVIEW2 R2-INT-7,
R2-EIL-0 to R2-EIL-2). The rules are in the docstring of that script. The script does not move a reference. A re-run
of `gen/eib_silk_refs_r2.py` on the labelled board gave 0 reference or text differences (scratch copy, 2026-11-15).

Table 4.1 lists the F.Silkscreen E-pad numbers. Each label lies nearer its own pad than any other pad by at least
0.15 mm, and its ink centre lies nearer its own pad row than any other E-pad row by at least 0.5 mm. E4 has no legal
position for "E4", so it reads "4".

| Pad | Text | Width x height (mm) | Angle (deg) | Ink box x, y (mm) | Gap to own pad (mm) | Gap to nearest other pad (mm) |
|---|---|---|---|---|---|---|
| E8 | E8 | 0.6 x 0.8 | 0 | 2.76-3.77, 14.70-15.65 | 0.11 | 0.34 |
| E3 | E3 | 0.6 x 0.8 | 0 | 2.61-3.62, 17.23-18.18 | 0.11 | 1.68 |
| E4 (DNP) | 4 | 0.8 x 0.8 | 0 | 0.30-0.94, 21.08-22.07 | 0.11 | 1.34 |
| E2 | E2 | 0.6 x 0.8 | 0 | 3.06-4.07, 24.21-25.16 | 0.11 | 0.28 |
| E7 | E7 | 0.6 x 0.8 | 0 | 0.26-1.30, 29.99-30.94 | 0.10 | 2.47 |
| E1 | E1 | 0.8 x 0.8 | 0 | 3.07-4.36, 33.77-34.72 | 0.12 | 0.36 |
| E5 | E5 | 0.8 x 0.8 | 0 | 3.07-4.36, 38.85-39.80 | 0.12 | 0.54 |
| E6 (DNP) | E6 | 0.6 x 0.8 | 90 | 0.29-1.24, 42.63-43.64 | 0.11 | 1.99 |

Table 4.2 lists the B.Silkscreen E landing labels after the phase C fix. Each label kept at least 0.80 mm from every
bottom reference text. Since D-97 (2026-11-17) the board has no bottom reference texts, and the E landing labels
are the only bottom silkscreen; the nearest-reference column is the record of the 2026-11-15 board.

| Label | Width x height (mm) | Ink box x (mm) | Nearest bottom reference, gap (mm) | Stroke to nearest via drill (mm) |
|---|---|---|---|---|
| E8 TP49 | 0.8 x 0.8 | 3.70-8.54 | U202, 8.55 | 0.065 |
| E3 TP33 | 0.8 x 0.8 | 3.75-8.59 | U202, 4.94 | 0.103 |
| E4 DNP | 0.8 x 0.8 | 3.25-7.59 | R252, 2.66 | 0.081 |
| E2 JP14 | 0.6 x 0.8 | 4.10-7.79 | R252, 0.86 | 0.090 |
| E7 TP38 | 0.6 x 0.8 | 3.25-6.91 | R254, 1.28 | 0.000 (over the tented via at (7.05, 28.95); no via-clear position) |
| E1 JP12.1 | 0.6 x 0.8 | 3.25-7.77 | R271, 1.70 | 0.403 |
| E5 TP36 | 0.8 x 0.8 | 3.25-8.09 | R251, 3.44 | 0.977 |
| E6 DNP | 0.8 x 0.8 | 3.25-7.59 | R251, 5.90 | 0.309 |

Note that `gen/eib_silk_refs_r2.py eib/silk_refs.md` writes only the section 3 table; sections 1, 2 and 4 are kept by
hand.
