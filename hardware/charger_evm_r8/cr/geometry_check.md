# CR plug-on outline: geometry checks (gen/cr_geometry.py; D-51, D-52)

Source: `references/Scale Car Board PCB 20260625.brd` (MB frame, mm). Generated; do not edit.

| Rule (design row) | Item | Measured | Limit | Result |
|---|---|---|---|---|
| H.23(a) successor: plug-on outline (D-39) | Edge.Cuts | 4 vertices, 48.416 x 87.000 mm, area 4212.19 mm2, KiCad Y 6.00-93.00 | 48.416 x 87.000 mm, 4212.19 mm2 | pass |
| H.23(a) successor: courtyard inset 0.5 mm (A.8) | INSET | 4077.78 mm2 | information | info |
| D-51 (operator ruling 2026-11-12 (a)): CR -x edge x 18.584 clears the terminal body in plan | J-BL (CUI_TB005_-762-03BE) | body +x 16.130 -> gap 2.454 mm; silk outer +x 16.194 -> 2.390 mm; keep-out +x 16.380 -> 2.204 mm; y overlap with the outline 22.86 mm | gap > 0 (no plan overlap) | pass |
| D-51 (operator ruling 2026-11-12 (a)): CR -x edge x 18.584 clears the terminal body in plan | J-FC (CUI_TB005-762-02BE) | body +x 16.130 -> gap 2.454 mm; silk outer +x 16.194 -> 2.390 mm; keep-out +x 16.380 -> 2.204 mm; y overlap with the outline 15.24 mm | gap > 0 (no plan overlap) | pass |
| D-51 (operator ruling 2026-11-12 (a)): CR -x edge x 18.584 clears the terminal body in plan | J-BT (CUI_TB005-762-02BE) | body +x 16.384 -> gap 2.200 mm; silk outer +x 16.448 -> 2.136 mm; keep-out +x 16.634 -> 1.950 mm; y overlap with the outline 15.24 mm | gap > 0 (no plan overlap) | pass |
| D-41 key: CR rotated 180 deg about (33.498, 50.514) lands on the terminals | J-BL, J-FC, J-BT | rotated outline x -0.004-48.412; engagement start 16.89 mm, terminal top 21.70 mm, margin 4.81 mm | all three hit; engagement start < 21.70 mm | pass |
| H.23(j) successor: D-41 stack heights | TSW on SSQ | CR underside 11.05 mm, CR top 12.65 mm, engagement start 16.89 mm | underside 11.05 mm (D-41) | pass |
| A.8 CHG holes in the .brd = the A.8 table (pin identity, D-02) | MB CHG package | max error 0.0000 mm | 0.001 mm | pass |
| H.23 successor: CHG pad (1.9 mm, PLACEHOLDER) to the outline edge | J1 pads | 1.464 mm | >= 0.5 mm (A.8 inset) | pass |
| H.23 successor: TSW body + 0.25 mm courtyard inside the 0.5 mm inset (D-41, D-03) | TSW-110 (pins 1-10) | margin 18.982 mm | >= 0 | pass |
| H.23 successor: TSW body + 0.25 mm courtyard inside the 0.5 mm inset (D-41, D-03) | TSW-112 (pins 11-22) | margin 0.394 mm | >= 0 | pass |
| H.23(h) successor: D-20 window y 30.8-66.86 less 10 mm from the MB 5V copper rim (D-11 interim) | analog window | 839.3 mm2, x 19.08-66.50 | information; TODO(measure: operator, MS4) | info |
| H.23(l) successor: J-TAP region, +x half, every straight-line A.4 maximum met | J102 region | 2038.9 mm2, x 42.79-66.50, y 7.50-93.50 | non-empty | pass |
| H.23(l) successor: J-TAP straight-line run, +x half of the CR (lower bound of the dressed run) | T1 (J102.1) -> C-D6.1 (97.790, 16.412) | 31.3-94.7 mm | <= 150 mm (A.4) | pass |
| H.23(l) successor: J-TAP straight-line run, +x half of the CR (lower bound of the dressed run) | T7b (J102.2) -> C-D6.2 (97.790, 19.363) | 31.3-92.3 mm | <= 150 mm (A.4) | pass |
| H.23(l) successor: J-TAP straight-line run, +x half of the CR (lower bound of the dressed run) | T17r (J102.3) -> J2.29 (109.982, 55.626) | 43.5-82.6 mm | <= 150 mm (A.4) | pass |
| H.23(l) successor: J-TAP straight-line run, +x half of the CR (lower bound of the dressed run) | T5 (J102.4) -> J1.45 (87.122, 35.306) | 20.6-73.2 mm | <= 120 mm (A.4) | pass |
| H.23(l) successor: J-TAP straight-line run, +x half of the CR (lower bound of the dressed run) | T13 (J102.5) -> J2.45 (109.982, 35.306) | 43.5-88.9 mm | <= 150 mm (A.4) | pass |
| H.23(l) successor: J-TAP straight-line run, +x half of the CR (lower bound of the dressed run) | T6 (J102.6) -> J1.29 (87.122, 55.626) | 20.6-65.4 mm | <= 120 mm (A.4) | pass |
| H.23(l) successor: J-TAP straight-line run, +x half of the CR (lower bound of the dressed run) | T2 (J102.7) -> C-D2.1 (67.705, 69.850) | 1.2-67.1 mm | <= 100 mm (A.4) | pass |
| H.23(l) successor: J-TAP straight-line run, +x half of the CR (lower bound of the dressed run) | T17 (J102.8) -> J2.09 (109.982, 81.026) | 43.5-99.6 mm | <= 150 mm (A.4) | pass |
| H.23(l) successor: J-TAP straight-line run, +x half of the CR (lower bound of the dressed run) | T16 (J102.9) -> J2.43 (109.982, 37.846) | 43.5-87.2 mm | <= 150 mm (A.4) | pass |
| H.23(l) successor: J-TAP straight-line run, +x half of the CR (lower bound of the dressed run) | T10 (J102.10) -> J2.47 (109.982, 32.766) | 43.5-90.6 mm | <= 150 mm (A.4) | pass |
| H.23(b) successor: MB parts crossing the outline edge (information; heights closed by D-51) | C-D4, C-DC3, C1-BT, C1-FC, CBL2, CHG, MDAC-BT, OP-BT, RB2, RB3 | 10 parts | information | info |
| H.23(e) successor: top-side courtyard booking, 78 parts, 0.25 mm basis (D-44, D-52) | largest: J102 182.2, J1 99.5, J101 70.1, U101 27.6, D107 24.5 mm2 | 917.0 of 4077.8 mm2 = 22.5 % | <= 75 % (A.8 booking target) | pass |
