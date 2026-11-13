# Decision item 6 (standoffs): operator ruling 2026-11-12 and the re-run site search

## Ruling
No standoffs in this design round. Operator's words: "We will not use standoffs. The weight should not be an issue
for the friction fit of 22 pins. If it ends up being an issue later, I will fix it when the time comes, likely by 3D
printing a support for the CR. The standoffs are not necessary for this design round."

## Re-run site search (kept for a later round; read-only analysis)
Scripts: C:\Users\ricky\AppData\Local\Temp\claude\3fe373bc8dcb48b3\5f1633cc-39d7-4238-b323-7b7a4184fb5e\scratchpad\so\
(model.py, search.py, col.py, sw.py, east.py, sets.py). Obstacles: MB top part bodies (bounding box of every
21/51/22/52/39/40 primitive), SMD and THT pads, and TSW header bodies (2.54 mm strips, 1.27 mm past each end pin,
TODO(verify: TSW drawing)). Bodges not modelled. Coordinates are in the MB frame.

| Site | MB frame | Free r (mm) | Nearest non-GND Cu | Nearest via |
|---|---|---|---|---|
| NW in-line with x 20.998 column | (21.00, 70.30) | 4.20 (J-FC), header 4.55 | 5.69 | 7.31 |
| SE end | (58.90, 11.70) | 7.64 | 2.53 (MISO L16) | 3.14 |
| NE end | (64.60, 91.60) | 6.10 | 1.05 (FC-CURR L16) | 3.35 |
| SW rest foot, in-line | (20.70, 23.20) | 2.41 (CBLD, L-BT) | 0.00 (VBT under mask) | 2.05 |
| interior | (35.10, 38.90) | 9.63 | 0.00 | 2.39 |
| interior | (31.90, 62.50) | 9.61 | 1.86 | 9.52 |

Findings that change the reassessment section 5:
- SO2 (56.36, 34.38) has a free radius of 2.49 mm when the REG-5V body is modelled in full. That is below both
  the M2.5 base (3.2) and the M2 base (2.6).
- No free disc of 1.7 mm or more exists in line with the south end of the x 20.998 column (x 20.9-23, y 24-35,
  the BAL network). That column can be inside the support polygon only with a rest foot at (20.70, 23.20) or with
  a seated connector stack (11.05 mm).
- The set NW + SE + NE + SW foot puts both columns inside the support polygon. Its corner overhangs are SW 16.1,
  SE 9.4, NE 3.4 and NW 22.4 mm. The old SO1-SO4 set leaves the x 20.998 column 4.89 mm outside.
