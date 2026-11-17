# CR reference designators

This list gives the placement of every visible reference field on `cr/cr.kicad_pcb` (D-59). It is written by
`gen/cr_silk_refs_report.py` from the board. The placement comes from `gen/silk_refs.py` (D-58), then
`gen/cr_silk_refs_r2.py`, `gen/cr_wire_labels.py`, `gen/cr_lead_labels.py`, `gen/cr_silk_fix_r3.py`
(update 2026-11-14) and `gen/cr_silk_fix_r4.py` (the W1 reference, phase C 2026-11-15, D-85). 54 references are on F.Silkscreen, 7 on B.Silkscreen and 17 on F.Fab.

The gap is measured from the text ink box to the own courtyard polygon. The note "over the courtyard of" names
another part whose courtyard polygon the ink overlaps. The text stroke is 0.15 mm throughout.

| Reference | Layer | Text height (mm) | Angle (deg) | Gap to own courtyard (mm) | Note |
|---|---|---|---|---|---|
| C101 | F.Silkscreen | 1.0 | 0 | 0.40 |  |
| C103 | F.Silkscreen | 1.0 | 0 | 2.07 |  |
| C106 | F.Silkscreen | 1.0 | 0 | 0.40 |  |
| C107 | F.Fab | - | - | - | no clear silkscreen position |
| C108 | F.Silkscreen | 1.0 | 90 | 1.97 |  |
| C110 | F.Silkscreen | 1.0 | 90 | 1.19 |  |
| C111 | F.Silkscreen | 0.8 | 90 | 2.31 |  |
| C114 | F.Silkscreen | 1.0 | 0 | 2.40 |  |
| C115 | F.Fab | - | - | - | no clear silkscreen position |
| C116 | F.Silkscreen | 1.0 | 90 | 1.97 |  |
| C119 | B.Silkscreen | 0.8 | 90 | 0.00 | mirrored, over the part (no clear top-side position); F.Fab ${REFERENCE} on the assembly drawing |
| C125 | F.Silkscreen | 1.0 | 0 | 2.31 |  |
| C126 | F.Silkscreen | 1.0 | 0 | 2.28 |  |
| C129 | F.Silkscreen | 1.0 | 0 | 1.40 |  |
| C130 | F.Fab | - | - | - | no clear silkscreen position |
| C131 | B.Silkscreen | 1.0 | 0 | 0.00 | mirrored, over the part (no clear top-side position); F.Fab ${REFERENCE} on the assembly drawing |
| C132 | F.Fab | - | - | - | no clear silkscreen position |
| C102a | B.Silkscreen | 1.0 | 90 | 0.00 | mirrored, over the part (no clear top-side position); F.Fab ${REFERENCE} on the assembly drawing |
| C102b | F.Silkscreen | 1.0 | 0 | 3.09 |  |
| C102c | B.Silkscreen | 1.0 | 0 | 0.00 | mirrored, over the part (no clear top-side position); F.Fab ${REFERENCE} on the assembly drawing |
| D103 | F.Silkscreen | 1.0 | 90 | 0.51 |  |
| D104 | F.Silkscreen | 0.8 | 0 | 3.35 |  |
| D105 | F.Fab | - | - | - | no clear silkscreen position |
| D106 | F.Fab | - | - | - | no clear silkscreen position |
| D107 | F.Silkscreen | 1.0 | 0 | 0.29 |  |
| J1 | F.Silkscreen | 1.0 | 0 | 0.19 |  |
| J101 | F.Silkscreen | 0.8 | 0 | 7.43 | header of the J101 map ('J101 top view') |
| J102 | F.Silkscreen | 1.0 | 0 | 0.28 |  |
| R101 | F.Silkscreen | 1.0 | 0 | 0.63 |  |
| R102 | F.Silkscreen | 1.0 | 0 | 3.01 |  |
| R103 | F.Silkscreen | 1.0 | 0 | 0.21 |  |
| R104 | F.Silkscreen | 1.0 | 0 | 0.75 |  |
| R105 | F.Silkscreen | 1.0 | 0 | 0.32 |  |
| R107 | B.Silkscreen | 1.0 | 0 | 0.00 | mirrored, over the part (no clear top-side position); F.Fab ${REFERENCE} on the assembly drawing |
| R108 | F.Silkscreen | 1.0 | 90 | 2.01 |  |
| R109 | F.Silkscreen | 1.0 | 0 | 3.03 |  |
| R110 | F.Silkscreen | 1.0 | 0 | 3.41 |  |
| R111 | F.Silkscreen | 1.0 | 90 | 2.18 |  |
| R112 | F.Silkscreen | 1.0 | 90 | 1.96 |  |
| R113 | F.Silkscreen | 0.8 | 90 | 0.19 |  |
| R114 | F.Silkscreen | 1.0 | 0 | 3.33 |  |
| R115 | F.Silkscreen | 0.8 | 90 | 0.12 |  |
| R116 | F.Silkscreen | 1.0 | 0 | 2.35 |  |
| R122 | F.Fab | - | - | - | no clear silkscreen position |
| R123 | F.Silkscreen | 1.0 | 0 | 1.99 |  |
| R126 | F.Silkscreen | 1.0 | 90 | 2.42 |  |
| R129 | F.Silkscreen | 0.8 | 0 | 3.26 |  |
| R130 | F.Fab | - | - | - | no clear silkscreen position |
| R132 | F.Silkscreen | 1.0 | 0 | 3.34 |  |
| R147 | F.Fab | - | - | - | no clear silkscreen position |
| R175 | F.Silkscreen | 1.0 | 90 | 0.31 |  |
| R176 | F.Silkscreen | 1.0 | 0 | 0.00 |  |
| R177 | F.Silkscreen | 1.0 | 0 | 3.24 |  |
| R184 | F.Fab | - | - | - | no clear silkscreen position |
| R185 | F.Fab | - | - | - | no clear silkscreen position |
| R186 | F.Fab | - | - | - | no clear silkscreen position |
| R187 | F.Fab | - | - | - | no clear silkscreen position |
| R188 | F.Fab | - | - | - | no clear silkscreen position |
| R189 | F.Fab | - | - | - | no clear silkscreen position |
| R131A | F.Silkscreen | 1.0 | 0 | 2.04 |  |
| R131B | F.Fab | - | - | - | no clear silkscreen position |
| R106s | F.Silkscreen | 1.0 | 0 | 0.41 |  |
| U101 | F.Silkscreen | 1.0 | 0 | 3.24 |  |
| U102 | F.Silkscreen | 1.0 | 0 | 0.92 |  |
| U103 | F.Silkscreen | 1.0 | 0 | 2.58 |  |
| U105 | F.Silkscreen | 1.0 | 0 | 1.18 |  |
| U106 | F.Silkscreen | 0.8 | 90 | 0.00 |  |
| U107 | B.Silkscreen | 1.0 | 0 | 0.00 | mirrored, over the part (no clear top-side position); F.Fab ${REFERENCE} on the assembly drawing |
| U110 | F.Fab | - | - | - | no clear silkscreen position |
| U118 | F.Silkscreen | 1.0 | 0 | 0.51 |  |
| U119 | B.Silkscreen | 1.0 | 0 | 0.00 | mirrored, over the part (no clear top-side position); F.Fab ${REFERENCE} on the assembly drawing |
| U120 | F.Silkscreen | 1.0 | 0 | 2.49 |  |
| W1 | F.Silkscreen | 0.8 | 0 | 0.01 |  |
| W2 | F.Silkscreen | 1.0 | 0 | 0.38 |  |
| W3 | F.Silkscreen | 0.8 | 90 | 0.00 | over the courtyard of J1 |
| W4 | F.Silkscreen | 1.0 | 0 | 0.09 |  |
| W6 | F.Silkscreen | 1.0 | 0 | 0.36 |  |
| W7 | F.Silkscreen | 0.8 | 90 | 3.04 |  |
