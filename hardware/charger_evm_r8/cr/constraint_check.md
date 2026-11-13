| Rule (design row) | Item | Measured | Limit | Result |
|---|---|---|---|---|
| A.8 CHG holes, 22 pins (pin identity, D-02) | J1 | max position error 0.0000 mm | 0.001 mm | pass |
| D-02 / D-41: CHG footprint on F.Cu (no flip) | J1 | F.Cu | F.Cu | pass |
| D-60 final outline (Edge.Cuts) = cr_geometry.FINAL_OUTLINE, inside the D-39 rectangle | Edge.Cuts | 18 segments, x 18.580-58.600, y 7.830-72.640, area 2241.6 mm2; area differing from FINAL_OUTLINE 0.0000 mm2 | 18 segments; difference < 0.01 mm2 | pass |
| D-60 6-32 mounting hole on the board (NPTH 3.70 mm) with its all-layer keep-out | MH1 | (26.23, 69.04), 1 pad, NPTH, drill 3.70 mm; keep-out zone present | (26.23, 69.04), NPTH 3.70 mm, keep-out r 4.0 mm | pass |
| D-60 6-32 mounting hole on the board (NPTH 3.70 mm) with its all-layer keep-out | MH2 | (54.85, 63.79), 1 pad, NPTH, drill 3.70 mm; keep-out zone present | (54.85, 63.79), NPTH 3.70 mm, keep-out r 4.0 mm | pass |
| D-60 6-32 mounting hole on the board (NPTH 3.70 mm) with its all-layer keep-out | MH3 | (54.85, 11.43), 1 pad, NPTH, drill 3.70 mm; keep-out zone present | (54.85, 11.43), NPTH 3.70 mm, keep-out r 4.0 mm | pass |
| D-60 6-32 mounting hole on the board (NPTH 3.70 mm) with its all-layer keep-out | MH4 | (24.48, 25.18), 1 pad, NPTH, drill 3.70 mm; keep-out zone present | (24.48, 25.18), NPTH 3.70 mm, keep-out r 4.0 mm | pass |
| Every part inside the outline (packer placed all parts) | all | 0 outside | 0 | pass |
| D-44 every SMT part on the top side | none | 0 flipped | 0 | pass |
| D-44 no SMD pad on B.Cu (one stencil, one reflow) | none | 0 pads | 0 | pass |
| D-44 chip passives >= 0603 (r9-3) | none | 0 below 0603 | 0 | pass |
| D-39 IC pitch >= 0.65 mm (U101 0.5 mm approved, D-40) | U101 | 0.50 mm | >= 0.65 mm or U101 | pass |
| D-39 IC pitch >= 0.65 mm | U102, U103, U105, U106, U107, U110, U118, U119, U120 | 9 ICs checked | minimum pad-centre spacing | pass (rows above list any exception) |
| D-03 (amended 2026-11-12) courtyard basis 0.25 mm | none | 0 on the 0.10 mm basis | 0 | pass |
| D-37 via annulus on an SMD pad or its mask opening (fallback only; each listed for operator review) | none | 0 vias; smallest annulus gap to a pad + mask 0.027 mm | 0 unless listed | pass |
| A.8 IN strip: VCHGIN vias at the C102b end (A.8 6 each end; D-21 five) | C102b pad 1 | 6 vias within 3 mm | >= 6 | pass |
| D-20 L4 (B.Cu): no tracks, GND pour only | B.Cu | 0 tracks; pour nets /GND | 0 tracks; /GND only | pass |
| A.8 W1-W4 lead pads (D-45; D-08 re-derived at placement; W2 D-55) | W1 | (30.300, 61.200) | (30.30, 61.20) | pass |
| A.8 W1-W4 lead pads (D-45; D-08 re-derived at placement; W2 D-55) | W2 | (27.200, 61.200) | (27.20, 61.20) | pass |
| A.8 W1-W4 lead pads (D-45; D-08 re-derived at placement; W2 D-55) | W3 | (24.300, 45.400) | (24.30, 45.40) | pass |
| A.8 W1-W4 lead pads (D-45; D-08 re-derived at placement; W2 D-55) | W4 | (24.300, 55.600) | (24.30, 55.60) | pass |
| D-55 (m-1) W1 (VCHGOUT) to W2 (GND) pad gap and courtyard overlap | W1-W2 | pad gap 0.807 mm; courtyard overlap 0.000 mm2 | >= 0.5 mm; 0 mm2 | pass |
| D-45 W6/W7 plated through-hole lead pads (PLACEHOLDER geometry) | W6 | 2 PTH pads | 2 | pass |
| D-45 W6/W7 plated through-hole lead pads (PLACEHOLDER geometry) | W7 | 3 PTH pads | 3 | pass |
| D-46 J-TAP header, Micro-Fit 3.0 2 x 5 | J102 | 10 pads | 10 cavities | pass |
| D-46 J-TAP on the +x side of the CR (courtyard in the +x half, x >= 42.792) | J102 | courtyard x 45.86-55.12, y 16.18-35.82 | x min >= 42.792 | pass |
| H.23(l) successor: J-TAP straight-line run (lower bound of the dressed run; A.4 maximum) | T2 J102.1 -> C-D2.1 | 53.4 mm | <= 100 mm | pass |
| H.23(l) successor: J-TAP straight-line run (lower bound of the dressed run; A.4 maximum) | T17 J102.2 -> J2.09 | 84.5 mm | <= 150 mm | pass |
| H.23(l) successor: J-TAP straight-line run (lower bound of the dressed run; A.4 maximum) | T17r J102.3 -> J2.29 | 68.2 mm | <= 150 mm | pass |
| H.23(l) successor: J-TAP straight-line run (lower bound of the dressed run; A.4 maximum) | T5 J102.4 -> J1.45 | 39.1 mm | <= 120 mm | pass |
| H.23(l) successor: J-TAP straight-line run (lower bound of the dressed run; A.4 maximum) | T13 J102.5 -> J2.45 | 61.5 mm | <= 150 mm | pass |
| H.23(l) successor: J-TAP straight-line run (lower bound of the dressed run; A.4 maximum) | T6 J102.6 -> J1.29 | 50.3 mm | <= 120 mm | pass |
| H.23(l) successor: J-TAP straight-line run (lower bound of the dressed run; A.4 maximum) | T1 J102.7 -> C-D6.1 | 46.7 mm | <= 150 mm | pass |
| H.23(l) successor: J-TAP straight-line run (lower bound of the dressed run; A.4 maximum) | T7b J102.8 -> C-D6.2 | 46.7 mm | <= 150 mm | pass |
| H.23(l) successor: J-TAP straight-line run (lower bound of the dressed run; A.4 maximum) | T16 J102.9 -> J2.43 | 59.1 mm | <= 150 mm | pass |
| H.23(l) successor: J-TAP straight-line run (lower bound of the dressed run; A.4 maximum) | T10 J102.10 -> J2.47 | 58.4 mm | <= 150 mm | pass |
| D-46 J-TAP latch finger access | J102 | latch side not modelled | TODO(verify: Molex 43045 header drawing) | info |
| A.8 IN strip: pad edge to pins 1/2/5 | C102c pad 1 | 0.53 mm | <= 3.0 mm | pass |
| A.8 IN strip: pad edge to pins 1/2/5 | C102a pad 1 | 2.09 mm | <= 3.0 mm | pass |
| A.8 IN strip: pad edge to pins 1/2/5 | D107 pad 1 | 2.43 mm | <= 3.0 mm | pass |
| A.8 OUT strip: C103 pad to pins 17/18 | C103 pad 1 | 1.52 mm | <= 3.0 mm | pass |
| A.8 IN strip: R102 N_UV pad to pin 6 (design 2.1 mm) | R102 | 2.09 mm | information | info |
| A.8 ILIM node within 5 mm of U101 pins 7-13 (pad to pin, centre to centre; D-55) | R101.1 -> U101.10 | 4.09 mm | <= 5 mm | pass |
| A.8 dVdT node within 5 mm of U101 pins 7-13 (pad to pin, centre to centre; D-55) | C101.1 -> U101.9 | 4.28 mm | <= 5 mm | pass |
| A.8 OVP node within 5 mm of U101 pins 7-13 (pad to pin, centre to centre; D-55) | R103.2 -> U101.7 | 3.58 mm | <= 5 mm | pass |
| A.8 OVP node within 5 mm of U101 pins 7-13 (pad to pin, centre to centre; D-55) | R104.1 -> U101.7 | 3.69 mm | <= 5 mm | pass |
| A.8 IMON node within 5 mm of U101 pins 7-13 (pad to pin, centre to centre; D-55) | R105.1 -> U101.13 | 3.26 mm | <= 5 mm | pass |
| A.8 IMON node within 5 mm of U101 pins 7-13 (pad to pin, centre to centre; D-55) | R129.1 -> U101.13 | 2.80 mm | <= 5 mm | pass |
| A.8 N_UV: R103 to U101 pin 6 (information; pin 6 is outside pins 7-13) | R103.1 -> U101.6 | 3.31 mm | information | info |
| A.8 (r9-3) R106s as near to U101 pin 14 as the courtyard check allows (D-55) | R106s.1 -> U101.14 | 4.31 mm | <= 5 mm (target; r6 pocket figure) | pass |
| D-55 (B-1, m-4) ratsnest edges crossing the CHG +x pin column (MST per net, straight line) | none | 0 edges | 0 | pass |
| D-20 window y 30.8-66.86 and >= 10 mm from the MB 5V copper rim (preferred; exemption if outside) | U102 | inside | inside | pass |
| D-20 window y 30.8-66.86 and >= 10 mm from the MB 5V copper rim (preferred; exemption if outside) | U103 | inside | inside | pass |
| D-20 window y 30.8-66.86 and >= 10 mm from the MB 5V copper rim (preferred; exemption if outside) | U119 | inside | inside | pass |
| D-20 window y 30.8-66.86 and >= 10 mm from the MB 5V copper rim (preferred; exemption if outside) | U120 | inside | inside | pass |
| D-20 window y 30.8-66.86 and >= 10 mm from the MB 5V copper rim (preferred; exemption if outside) | D104 | inside | inside | pass |
| D-20 window y 30.8-66.86 and >= 10 mm from the MB 5V copper rim (preferred; exemption if outside) | D105 | inside | inside | pass |
| D-20 window y 30.8-66.86 and >= 10 mm from the MB 5V copper rim (preferred; exemption if outside) | D106 | inside | inside | pass |
| D-20 window y 30.8-66.86 and >= 10 mm from the MB 5V copper rim (preferred; exemption if outside) | R109 | inside | inside | pass |
| D-20 window y 30.8-66.86 and >= 10 mm from the MB 5V copper rim (preferred; exemption if outside) | R111 | inside | inside | pass |
| D-20 window y 30.8-66.86 and >= 10 mm from the MB 5V copper rim (preferred; exemption if outside) | R114 | inside | inside | pass |
| D-20 window y 30.8-66.86 and >= 10 mm from the MB 5V copper rim (preferred; exemption if outside) | R110 | inside | inside | pass |
| D-20 window y 30.8-66.86 and >= 10 mm from the MB 5V copper rim (preferred; exemption if outside) | R112 | inside | inside | pass |
| D-20 window y 30.8-66.86 and >= 10 mm from the MB 5V copper rim (preferred; exemption if outside) | R115 | inside | inside | pass |
| D-20 window y 30.8-66.86 and >= 10 mm from the MB 5V copper rim (preferred; exemption if outside) | R102 | outside: courtyard x 42.60-44.49, y 56.09-59.43 | inside | exemption (D-20) |
| D-20 window y 30.8-66.86 and >= 10 mm from the MB 5V copper rim (U101 network and CHG_IIN filter) | R103 | outside: courtyard x 44.46-47.40, y 63.48-64.92 | inside | listed exemption: U101 network, A.8 <= 5 mm (D-55, D-56) |
| D-20 window y 30.8-66.86 and >= 10 mm from the MB 5V copper rim (U101 network and CHG_IIN filter) | R104 | inside | inside | pass |
| D-20 window y 30.8-66.86 and >= 10 mm from the MB 5V copper rim (U101 network and CHG_IIN filter) | R129 | outside: courtyard x 44.46-47.40, y 66.68-68.12 | inside | listed exemption: U101 network, A.8 IMON <= 5 mm (D-55) |
| D-20 window y 30.8-66.86 and >= 10 mm from the MB 5V copper rim (U101 network and CHG_IIN filter) | C129 | inside | inside | pass |
| D-35 / D-36 logic-IC pads within 2.0 mm of the divider tops (metric, F.Cu pads) | none | 0 pads | metric: lower is better (D-36) | info |
| A.8 divider strip x 23.15-36.50, y 42.14-45.69 | R109 | inside | inside | pass |
| A.8 divider strip x 23.15-36.50, y 42.14-45.69 | R110 | inside | inside | pass |
| A.8 divider strip x 23.15-36.50, y 42.14-45.69 | R111 | inside | inside | pass |
| A.8 divider strip x 23.15-36.50, y 42.14-45.69 | R112 | inside | inside | pass |
| A.8 divider strip x 23.15-36.50, y 42.14-45.69 | R114 | inside | inside | pass |
| A.8 divider strip x 23.15-36.50, y 42.14-45.69 | R115 | inside | inside | pass |
| D-55 (m-3) W3 18 AWG joint to the R110 0.1 % divider pad (pad gap; information) | W3 - R110.1 | 1.47 mm | information (r9 step 5: 0.78 mm) | info |
| H.23(f) distance from the U101 loop region (information) | U102 | 19.38 mm | >= 3.0 mm (region rule) | info |
| H.23(f) distance from the U101 loop region (information) | U103 | 18.00 mm | >= 3.0 mm (region rule) | info |
| H.23(f) distance from the U101 loop region (information) | U119 | 17.56 mm | >= 3.0 mm (region rule) | info |
| H.23(f) distance from the U101 loop region (information) | U120 | 17.56 mm | >= 3.0 mm (region rule) | info |
| H.23(f) distance from the U101 loop region (information) | D104 | 13.52 mm | >= 3.0 mm (region rule) | info |
| H.23(f) distance from the U101 loop region (information) | D105 | 11.23 mm | >= 3.0 mm (region rule) | info |
| H.23(f) distance from the U101 loop region (information) | D106 | 10.04 mm | >= 3.0 mm (region rule) | info |
| H.23(e) successor: top-side courtyard booking (KiCad courtyards, information) | top | 911.5 of 4077.8 mm2 = 22.4 % | <= 75 % target | info |
| D-20 every via tented on both sides | board setup | front True, back True | both tented | pass |
| D-20 L2-L4 GND stitching (/GND vias and plated holes) over the filled L4 pour (D-61) | /GND | 296 stitch points; largest distance to the nearest one 3.47 mm at (31.0, 34.7) | <= 3.54 mm (5 mm square pitch, D-20) | pass |
| A.8 U101 thermal pad >= 9 vias 0.3 mm (D-40 exempt from D-37) | U101 | 9 vias | >= 9 | pass |
| D-40 / A.8 U101 exposed-pad paste apertures clear of every via drill (window pane; D-55) | U101.25 | 4 apertures; smallest gap to a drill 0.151 mm; coverage 25.0 % | gap >= 0.15 mm (D-56, N-6); coverage TODO(verify: SLVSE94G section 11, stencil vendor) | pass |
| D-56 (r9b N-7) F.Cu escape: a 0.1524 mm track leaves the pad to a same-net pad or a 0.6 mm via site (hard pours, other-net copper, keep-outs) | U101.6 /N_UV | free 967.77 mm2; reaches R102.2, via(44.98,57.85); via site (46.59, 63.21), 3.70 mm from the pad | reaches a same-net pad/via or holds a via site | pass |
| D-56 (r9b N-7) F.Cu escape: a 0.1524 mm track leaves the pad to a same-net pad or a 0.6 mm via site (hard pours, other-net copper, keep-outs) | U101.7 /N_OV | free 968.77 mm2; reaches R103.2, R104.1; via site (45.26, 63.20), 1.39 mm from the pad | reaches a same-net pad/via or holds a via site | pass |
| D-56 (r9b N-7) F.Cu escape: a 0.1524 mm track leaves the pad to a same-net pad or a 0.6 mm via site (hard pours, other-net copper, keep-outs) | U101.9 /N_DVDT | free 0.90 mm2; reaches via(44.52,63.34); via site none | reaches a same-net pad/via or holds a via site | pass |
| D-56 (r9b N-7) F.Cu escape: a 0.1524 mm track leaves the pad to a same-net pad or a 0.6 mm via site (hard pours, other-net copper, keep-outs) | U101.10 /N_ILIM | free 967.03 mm2; reaches R101.1, via(42.61,68.29), via(44.21,65.47); via site (44.53, 65.00), 1.09 mm from the pad | reaches a same-net pad/via or holds a via site | pass |
| D-56 (r9b N-7) F.Cu escape: a 0.1524 mm track leaves the pad to a same-net pad or a 0.6 mm via site (hard pours, other-net copper, keep-outs) | U101.13 /N_IMON | free 968.72 mm2; reaches R105.1, R129.1, via(41.01,68.29), via(43.30,66.31) +1; via site (43.43, 65.48), 0.35 mm from the pad | reaches a same-net pad/via or holds a via site | pass |
| D-56 (r9b N-7) F.Cu escape: a 0.1524 mm track leaves the pad to a same-net pad or a 0.6 mm via site (hard pours, other-net copper, keep-outs) | U101.14 /N_FLT | free 966.44 mm2; reaches R106s.1, via(42.46,66.47), via(44.52,69.74); via site (42.03, 66.48), 0.56 mm from the pad | reaches a same-net pad/via or holds a via site | pass |
| D-56 (r9b N-7) F.Cu escape: a 0.1524 mm track leaves the pad to a same-net pad or a 0.6 mm via site (hard pours, other-net copper, keep-outs) | R102.2 /N_UV | free 967.77 mm2; reaches U101.6, via(44.98,57.85); via site (44.45, 56.05), 2.16 mm from the pad | reaches a same-net pad/via or holds a via site | pass |
| D-56 (r9b N-7) F.Cu escape: a 0.1524 mm track leaves the pad to a same-net pad or a 0.6 mm via site (hard pours, other-net copper, keep-outs) | C102c.2 /GND | free 1.37 mm2; reaches via(42.30,59.30); via site none | reaches a same-net pad/via or holds a via site | pass |
| D-56 (r9b N-7) F.Cu escape: a 0.1524 mm track leaves the pad to a same-net pad or a 0.6 mm via site (hard pours, other-net copper, keep-outs) | C103.2 /GND | free 3.85 mm2; reaches via(38.08,62.90); via site (38.38, 62.60), 0.83 mm from the pad | reaches a same-net pad/via or holds a via site | pass |
| H.23(a) successor: plug-on outline (D-39) | Edge.Cuts | 4 vertices, 48.416 x 87.000 mm, area 4212.19 mm2, KiCad Y 6.00-93.00 | 48.416 x 87.000 mm, 4212.19 mm2 | pass |
| H.23(a) successor: courtyard inset 0.5 mm (A.8) | INSET | 4077.78 mm2 | information | info |
| D-60 final outline (trimmed after routing), inside the D-39 rectangle | FINAL_OUTLINE | 18 vertices, area 2241.6 mm2 (53 % of D-39), x 18.580-58.600, y 7.83-72.64, convex | inside the D-39 rectangle within 0.01 mm (trim rounding); -x edge at x 18.584 (D-51) | pass |
| D-60 +x key ear kept (D-41) | KEY_EAR | box x 50.0-58.6, y 52.0-71.0; 0.453 mm2 outside the outline | inside the final outline within the 0.06 mm trim tolerance | pass |
| D-60 6-32 mounting hole (NPTH 3.70 mm; head disc r 3.6 mm on the board; keep-out r 4.0 mm) | MH1 | (26.23, 69.04); hole edge 1.70 mm from the board edge; head disc overhang 0.048 mm | head disc inside the final outline within the 0.06 mm trim tolerance | pass |
| D-60 6-32 mounting hole (NPTH 3.70 mm; head disc r 3.6 mm on the board; keep-out r 4.0 mm) | MH2 | (54.85, 63.79); hole edge 1.88 mm from the board edge; head disc overhang 0.000 mm | head disc inside the final outline within the 0.06 mm trim tolerance | pass |
| D-60 6-32 mounting hole (NPTH 3.70 mm; head disc r 3.6 mm on the board; keep-out r 4.0 mm) | MH3 | (54.85, 11.43); hole edge 1.70 mm from the board edge; head disc overhang 0.049 mm | head disc inside the final outline within the 0.06 mm trim tolerance | pass |
| D-60 6-32 mounting hole (NPTH 3.70 mm; head disc r 3.6 mm on the board; keep-out r 4.0 mm) | MH4 | (24.48, 25.18); hole edge 1.70 mm from the board edge; head disc overhang 0.052 mm | head disc inside the final outline within the 0.06 mm trim tolerance | pass |
| D-51 (operator ruling 2026-11-12 (a)): CR -x edge x 18.584 clears the terminal body in plan | J-BL (CUI_TB005_-762-03BE) | body +x 16.130 -> gap 2.454 mm; silk outer +x 16.194 -> 2.390 mm; keep-out +x 16.380 -> 2.204 mm; y overlap with the outline 22.86 mm | gap > 0 (no plan overlap) | pass |
| D-51 (operator ruling 2026-11-12 (a)): CR -x edge x 18.584 clears the terminal body in plan | J-FC (CUI_TB005-762-02BE) | body +x 16.130 -> gap 2.454 mm; silk outer +x 16.194 -> 2.390 mm; keep-out +x 16.380 -> 2.204 mm; y overlap with the outline 15.24 mm | gap > 0 (no plan overlap) | pass |
| D-51 (operator ruling 2026-11-12 (a)): CR -x edge x 18.584 clears the terminal body in plan | J-BT (CUI_TB005-762-02BE) | body +x 16.384 -> gap 2.200 mm; silk outer +x 16.448 -> 2.136 mm; keep-out +x 16.634 -> 1.950 mm; y overlap with the outline 15.24 mm | gap > 0 (no plan overlap) | pass |
| D-41 key: CR rotated 180 deg about (33.498, 50.514) lands on the terminals | J-BL, J-FC | rotated outline x 8.396-48.416; engagement start 16.89 mm, terminal top 21.70 mm, margin 4.81 mm | J-BL and J-FC hit (D-41 as amended by D-60; J-BT not needed); engagement start < 21.70 mm | pass |
| H.23(j) successor: D-41 stack heights | TSW on SSQ | CR underside 11.05 mm, CR top 12.65 mm, engagement start 16.89 mm | underside 11.05 mm (D-41) | pass |
| A.8 CHG holes in the .brd = the A.8 table (pin identity, D-02) | MB CHG package | max error 0.0000 mm | 0.001 mm | pass |
| H.23 successor: CHG pad (1.9 mm, PLACEHOLDER) to the outline edge | J1 pads | 1.468 mm | >= 0.5 mm (A.8 inset) | pass |
| H.23 successor: TSW body + 0.25 mm courtyard inside the 0.5 mm inset (D-41, D-03) | TSW-110 (pins 1-10) | margin 7.584 mm | >= 0 | pass |
| H.23 successor: TSW body + 0.25 mm courtyard inside the 0.5 mm inset (D-41, D-03) | TSW-112 (pins 11-22) | margin 0.398 mm | >= 0 | pass |
| H.23(h) successor: D-20 window y 30.8-66.86 less 10 mm from the MB 5V copper rim (D-11 interim) | analog window | 839.3 mm2, x 19.08-66.50 | information; TODO(measure: operator, MS4) | info |
| H.23(l) successor: J-TAP region, +x half, every straight-line A.4 maximum met | J102 region | 2038.9 mm2, x 42.79-66.50, y 7.50-93.50 | non-empty | pass |
| H.23(l) successor: J-TAP straight-line run, +x half of the CR (lower bound of the dressed run) | T2 (J102.1) -> C-D2.1 (67.705, 69.850) | 1.2-67.1 mm | <= 100 mm (A.4) | pass |
| H.23(l) successor: J-TAP straight-line run, +x half of the CR (lower bound of the dressed run) | T17 (J102.2) -> J2.09 (109.982, 81.026) | 43.5-99.6 mm | <= 150 mm (A.4) | pass |
| H.23(l) successor: J-TAP straight-line run, +x half of the CR (lower bound of the dressed run) | T17r (J102.3) -> J2.29 (109.982, 55.626) | 43.5-82.6 mm | <= 150 mm (A.4) | pass |
| H.23(l) successor: J-TAP straight-line run, +x half of the CR (lower bound of the dressed run) | T5 (J102.4) -> J1.45 (87.122, 35.306) | 20.6-73.2 mm | <= 120 mm (A.4) | pass |
| H.23(l) successor: J-TAP straight-line run, +x half of the CR (lower bound of the dressed run) | T13 (J102.5) -> J2.45 (109.982, 35.306) | 43.5-88.9 mm | <= 150 mm (A.4) | pass |
| H.23(l) successor: J-TAP straight-line run, +x half of the CR (lower bound of the dressed run) | T6 (J102.6) -> J1.29 (87.122, 55.626) | 20.6-65.4 mm | <= 120 mm (A.4) | pass |
| H.23(l) successor: J-TAP straight-line run, +x half of the CR (lower bound of the dressed run) | T1 (J102.7) -> C-D6.1 (97.790, 16.412) | 31.3-94.7 mm | <= 150 mm (A.4) | pass |
| H.23(l) successor: J-TAP straight-line run, +x half of the CR (lower bound of the dressed run) | T7b (J102.8) -> C-D6.2 (97.790, 19.363) | 31.3-92.3 mm | <= 150 mm (A.4) | pass |
| H.23(l) successor: J-TAP straight-line run, +x half of the CR (lower bound of the dressed run) | T16 (J102.9) -> J2.43 (109.982, 37.846) | 43.5-87.2 mm | <= 150 mm (A.4) | pass |
| H.23(l) successor: J-TAP straight-line run, +x half of the CR (lower bound of the dressed run) | T10 (J102.10) -> J2.47 (109.982, 32.766) | 43.5-90.6 mm | <= 150 mm (A.4) | pass |
| H.23(b) successor: MB parts crossing the outline edge (information; heights closed by D-51) | CBL2, CHG, L-BT, MDAC-FC, OP-FC, RB1A, RB2, RD2-BT, REG-5V, RINJ-BT, SNS-BT | 11 parts | information | info |
