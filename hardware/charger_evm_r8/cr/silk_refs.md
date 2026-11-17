# CR reference designators

This list gives the placement of every reference field on `cr/cr.kicad_pcb` (D-59). It is written by
`gen/cr_silk_refs_report.py` from the board. The placement comes from `gen/silk_refs.py` (D-58), then
`gen/cr_silk_refs_r2.py`, `gen/cr_wire_labels.py`, `gen/cr_lead_labels.py`, `gen/cr_silk_fix_r3.py`
(update 2026-11-14) and `gen/cr_silk_fix_r4.py` (the W1 reference, phase C 2026-11-15, D-85). 16 references are on F.Silkscreen, 0 on B.Silkscreen and 62 on F.Fab.

The gap is measured from the text ink box to the own courtyard polygon. The note "over the courtyard of" names
another part whose courtyard polygon the ink overlaps. The text stroke is 0.15 mm throughout.

| Reference | Layer | Text height (mm) | Angle (deg) | Gap to own courtyard (mm) | Note |
|---|---|---|---|---|---|
| C101 | F.Silkscreen | 1.0 | 0 | 0.40 |  |
| C103 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| C106 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| C107 | F.Fab | - | - | - | no clear silkscreen position |
| C108 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| C110 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| C111 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| C114 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| C115 | F.Fab | - | - | - | no clear silkscreen position |
| C116 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| C119 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| C125 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| C126 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| C129 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| C130 | F.Fab | - | - | - | no clear silkscreen position |
| C131 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| C132 | F.Fab | - | - | - | no clear silkscreen position |
| C102a | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| C102b | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| C102c | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| D103 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| D104 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| D105 | F.Fab | - | - | - | no clear silkscreen position |
| D106 | F.Fab | - | - | - | no clear silkscreen position |
| D107 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| J1 | F.Silkscreen | 1.0 | 0 | 0.19 |  |
| J101 | F.Silkscreen | 0.8 | 0 | 7.43 | header of the J101 map ('J101 top view') |
| J102 | F.Silkscreen | 1.0 | 0 | 0.28 |  |
| R101 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| R102 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| R103 | F.Silkscreen | 1.0 | 0 | 0.21 |  |
| R104 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| R105 | F.Silkscreen | 1.0 | 0 | 0.32 |  |
| R107 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| R108 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| R109 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| R110 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| R111 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| R112 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| R113 | F.Silkscreen | 0.8 | 90 | 0.19 |  |
| R114 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| R115 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| R116 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| R122 | F.Fab | - | - | - | no clear silkscreen position |
| R123 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| R126 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| R129 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| R130 | F.Fab | - | - | - | no clear silkscreen position |
| R132 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| R147 | F.Fab | - | - | - | no clear silkscreen position |
| R175 | F.Silkscreen | 1.0 | 90 | 0.31 |  |
| R176 | F.Silkscreen | 1.0 | 0 | 0.00 |  |
| R177 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| R184 | F.Fab | - | - | - | no clear silkscreen position |
| R185 | F.Fab | - | - | - | no clear silkscreen position |
| R186 | F.Fab | - | - | - | no clear silkscreen position |
| R187 | F.Fab | - | - | - | no clear silkscreen position |
| R188 | F.Fab | - | - | - | no clear silkscreen position |
| R189 | F.Fab | - | - | - | no clear silkscreen position |
| R131A | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| R131B | F.Fab | - | - | - | no clear silkscreen position |
| R106s | F.Silkscreen | 1.0 | 0 | 0.41 |  |
| U101 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| U102 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| U103 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| U105 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| U106 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| U107 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| U110 | F.Fab | - | - | - | no clear silkscreen position |
| U118 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| U119 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| U120 | F.Fab | - | - | - | hidden; in the assembly guide (assembly_guide/cr/) |
| W1 | F.Silkscreen | 0.8 | 0 | 0.01 |  |
| W2 | F.Silkscreen | 1.0 | 0 | 0.38 |  |
| W3 | F.Silkscreen | 0.8 | 90 | 0.00 | over the courtyard of J1 |
| W4 | F.Silkscreen | 1.0 | 0 | 0.09 |  |
| W6 | F.Silkscreen | 1.0 | 0 | 0.36 |  |
| W7 | F.Silkscreen | 0.8 | 90 | 3.04 |  |
