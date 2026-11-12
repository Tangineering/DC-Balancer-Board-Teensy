## Standoffs (change-request items 4.2 and 6.2)

### 1. Findings

**F1. Corner geometry.** I took the CHG footprint corners from the MB `.brd` silkscreen of element CHG (AG105 package, origin (47.498, 34.544), R180): x 17.134-49.262, y 32.780-67.708. They come from `mb_part_extents.py` run on `references/Scale Car Board PCB 20260625.brd`. The 22 header holes lie on x 20.998 (pins 11-22, y 36.544-64.484) and x 45.998 (pins 1-10, y 39.084-61.944), per design doc A.8 (`docs/charger_bq25798_wiring_design_2026-11-05.md:1205-1215`).

- **The two -x corners (x 17.134) lie outside the new CR outline.** The CR -x edge is x 18.584 (change request Table 1). A standoff therefore cannot sit on the -x corners themselves. It must move at least 3.4 mm inside the edge, to x >= 21.98 (see the F4 keep-out radius).
- **The standoffs must also stay clear of the receptacle bodies.** For pin 22 (y 36.544) and pin 11 (y 64.484), I assumed a receptacle body that extends 1.27 mm past the end pin, TODO(verify: receptacle drawing). The standoff centres then fall at y <= 32.0 or y >= 69.15 on the x 20.998 column.

**F2. MB parts and copper at the corners.** I parsed the `.brd` with the scratch script `scan.py`. The MB has 2 layers (`layerSetup (1*16)`), and both layers carry GND pours over all four corners. Table 1 lists the corner neighbourhoods. Distances are to the bounding box of each part body (silk 21 / tDocu 51) or to the copper edge.

Table 1. MB content within 3.5 mm of each CHG corner.

| Corner | Content |
|---|---|
| SW (17.134, 32.780) | VBAL+ traces at 0 mm, GND via 0.61, J-BL body 1.00, RB2 pad 1.34, CBL2 2.08, VMID / VC2 / VC1 traces 2.2-3.2. This is the BAL network and is fully congested. |
| SE (49.262, 32.780) | C4B-BT pad 0.24, GND via 0.64, C4C-BT 1.51, VBT bottom trace 1.26, BT-V / EN-REG-BT traces 1.9-2.4, VBT via 2.75, VOUT-BT pour 3.06. |
| NW (17.134, 67.708) | J-NTC body 0.95 and nothing else. The point itself is off the CR. |
| NE (49.262, 67.708) | GND via 0.29, N$7 traces 1.0, CS-MDAC-FC 1.5, a 3V3 via 1.9, MDAC-FC body 2.29, MISO / MPPT-DISABLE / VDROOP-FC / FC-CURR traces 2.8-3.5. |

**F3. Adhesive-base supports do not fit at three of the four corners.** The catalogue snap-lock adhesive supports have 12.7 x 12.7 mm (Essentra LCBSBM) or 17.8 x 17.8 mm (LCBSB) bases, per RS listings [LCBSBM-5-01A2-RT](https://au.rs-online.com/web/p/pcb-supports/7214714) and [LCBSB-3-01A2-RT](https://nz.rs-online.com/web/p/pcb-supports/7214717). The free MB-top disc at the SW, SE and NE corners has a radius of only 2.6-3.3 mm (Table 2). Only NW has a free disc of 6.07 mm radius, which is still smaller than a 12.7 mm square base needs (half-diagonal 8.98 mm).

**F4. Free positions that do exist (the scratch script `freedisc.py`).**

- **Search method.** The script finds the centre nearest each corner with a free MB-top disc of radius r_base. Obstacles are part bodies and SMD/THT pads; traces under the solder mask are allowed.
- **CR-side limits.** The centre stays >= 3.4 mm inside the CR outline and >= 3.4 mm from the receptacle keep-out boxes.
- **Disc sizes.** r_base = 2.6 mm covers an M2 hex of 4.0 mm across flats (AF) plus a 0.3 mm epoxy fillet. r_base = 3.2 mm covers an M2.5 hex of 5.0 mm AF plus the fillet. Both AF values are TODO(verify: the chosen standoff datasheet).

Table 2. Candidate standoff centres (MB frame, mm). Every position is TODO(measure: operator, after a dry fit).

| Id | M2.5 centre (r_base 3.2) | Corner distance | Nearest via | Nearest non-GND copper | M2 centre (r_base 2.6) |
|---|---|---|---|---|---|
| SO1 (SW) | (26.0, 35.6), free radius 3.24, limited by RB1B | 9.33 | 2.03 | 2.61 | (26.0, 35.0) |
| SO2 (SE) | (56.4, 34.4), free radius 3.23, limited by C4C-BT and REG-5V pad 2 | 7.28 | 1.18 (VBT) | 0.00 (VBT trace under the base) | (54.7, 35.0) |
| SO3 (NW) | (22.0, 69.2), free radius 6.07 | 5.12 | 8.67 | 4.60 | same |
| SO4 (NE) | (49.3, 66.7), free radius 3.29, limited by MDAC-FC | 1.00 | 1.29 | 1.73 | (49.3, 67.3) |

**F5. A new MB hole is feasible only at SO3.** At SO3 the nearest non-GND copper is 4.60 mm away and the nearest via 8.67 mm, so a 2.7 mm hole (radius 1.35) keeps more than 3 mm of margin. A drilled hole would expose GND pour on both layers at the hole wall. At SO1, SO2 and SO4, non-GND copper lies 0-2.6 mm from the centre, so a drill is rejected there.

**F6. The four supports leave long overhangs.** They span y 34.4-69.2, but the CR spans y 7-94, so it overhangs by 27.4 mm at -y and 24.8 mm at +y. The support polygon also leaves pins 21/22 (x 20.998, y <= 39.1) slightly outside it at the -x/-y side. A coarse search found free MB discs of radius >= 3.2 mm near the CR ends at (57.4, 12.6), (63.6, 10.6), (50.8, 77.2) and (50.2, 85.0). That search counts only silk/tDocu wire boxes and does not cover the bodges, so each of these is TODO(measure: operator).

**F7. Ground scheme.** A.6 bonds CR GND to MB GND only at CHG pads 4/14/15 (`...wiring_design...md:731-741`). Two things would create a second GND bond and a loop: a metal standoff on the exposed GND at an SO3 drilled hole, or a plated CR hole with copper. The design therefore needs nylon hardware and an unplated CR hole without copper.

**F8. Thermal concern at SO2.** SO2 lies 3.3 mm from the REG-5V pad, and REG-5V (TO254P1524X483, 4.83 mm tall per its IPC package name) dissipates under the CR (change request 4.6). Nylon 6/6 has a temperature limit, TODO(verify: standoff datasheet, continuous-use temperature). A temperature reading at SO2 is needed, TODO(measure: operator).

**F9. Surface-mount spacers (WÃ¼rth WA-SMSI) are not suitable as the primary part.**

- **Part data.** WA-SMSI is a steel, tin-plated spacer with an M2.5 internal thread and 5.1 mm OD. Heights are 1-10 mm; it is MSL 1 and meant for reflow ([WÃ¼rth catalogue](https://www.we-online.com/catalog/en/SMSI_SMT_STEEL_SPACER_M2_5_THREAD_INTERNAL); [datasheet](https://cdn.sparkfun.com/assets/5/f/d/7/8/WA-SMSI_SMT_Steel_Spacer_with_internal_Thread_M2.5.pdf)).
- **On the MB.** The MB has no pad for it. The operator would have to scrape mask on the GND pour and hand-solder the spacer, which bonds steel to GND (the F7 problem).
- **On the CR underside.** This puts a heavy part on the side that is reflowed first, which change request 5.2 forbids. Alternatively it adds a second reflow, against 5.1.
- **Via rule.** If the part is ever used, VR-1 must hold on its pads whatever D-36 allows: an open via in a mechanical solder joint wicks the solder. For the recommended NPTH standoff holes, there is no pad, so the VR-1 / D-36 conflict does not arise.

### 2. Proposal

**P1. Part.** Use four M2.5 female-female nylon 6/6 hex standoffs (5.0 mm AF) with M2.5 nylon pan-head screws from the CR top. Each standoff is bonded to the MB solder mask with a two-part epoxy; there is no MB hole. All part numbers and AF values are TODO(verify: datasheet). The M2 variant (4.0 mm AF, Table 2 right-hand column) is the fallback where a disc is too tight. At SO3 the operator can choose a drilled 2.7 mm hole with a through nylon screw instead of the bond (F5). The removable path is four screws out, then the CR pulls straight up.

**P2. CR mounting hole.**

- **Hole.** NPTH, 2.7 mm diameter for M2.5 (ISO 273 fine; 2.2 mm for M2), TODO(verify: ISO 273 table; OSH Park NPTH handling; D-19 already uses a 1.0 mm NPTH).
- **Copper keep-out.** Radius 3.4 mm on all four layers (L2 GND plane included). This covers the 5.77 mm hex corner diameter plus 0.5 mm, and a 5.0 mm pan head, TODO(verify: DIN 7985 dk). No plating and no pad, per F7.
- **Solder mask.** Leave the mask closed outside the drill.
- **Part keep-outs.** Top: no part within radius 3.5 mm, to clear the screw head and the driver. Bottom: no part within radius 3.4 mm.
- **DRC.** Implement the keep-outs as "footprints not allowed" rule areas, the same way as D-17 and D-19.

**P3. Positions.** Use SO1-SO4 from Table 2 as fixed CR features, in the same way as the D-08 fixed pads, before the re-placement. Optionally add SO5 and SO6 near the CR ends (F6). The operator confirms each position on the board.

**P4. Stack-height equations.** All heights are measured from the MB top.

- **Symbols.**
  - h_hb: the height of the male-header body above the MB top, including any raised spacer.
  - h_rb: the height of the receptacle body below the CR underside (receptacle on the CR bottom, THT, hand-soldered last per change request 5.3).
  - t_b: the epoxy bond thickness.
  - H_so: the standoff length.
  - t_s: the shim thickness.
- **Datum, seated.** The receptacle face bottoms on the header body, so the seated stack is S = h_hb + h_rb. This requires a post length L_post <= D_socket (the socket depth), so the receptacle bottoms on the body and not on the post tip. It also requires an engagement of L_post âˆ’ (h_rb âˆ’ D_socket) >= e_min. Both are TODO(verify: header and receptacle drawings).
- **Clearance.** S >= h_MB,max + h_CR,bot + c, with c >= 1.0 mm.
  - h_MB,max = max(L-FC 5.0, L-BT 5.0, REG-5V 4.83, bodges). L-FC and L-BT are TODO(verify: Eaton HCM1A1305V3); the bodge heights are TODO(measure: operator, change request 6.1).
  - With a one-sided CR (h_CR,bot = 0), S >= 6.0 mm at minimum.
  - With the A.7 body h_hb = 2.54 mm (`...md:853`), h_rb >= 3.46 mm.
- **Standoff.** H_so = S âˆ’ t_b âˆ’ t_s. Choose H_so as the stock length at or just below S âˆ’ t_b. Then shim with 0 <= t_s < the stock step, TODO(verify: nylon shim washer thicknesses).
- **Mismatch rule.** Î´_i = (t_b + H_so + t_s)_i âˆ’ S must satisfy 0 <= Î´_i <= 0.1 mm at each standoff.
  - If Î´ < 0, the screw pulls the CR down onto bottomed receptacles and bends the CR across the pins.
  - If Î´ > 0, it reduces contact engagement by Î´.
- **Fit procedure.** Seat the CR, measure the gap at each standoff with a feeler gauge, shim to that gap, and tighten the screws finger-tight.

**P5. Load path.**

- **Downward and mass loads.** CR â†’ standoff faces in compression â†’ epoxy in compression â†’ MB laminate. The pins carry no load when Î´ >= 0.
- **Upward loads (cable pull).** Screw â†’ standoff â†’ epoxy in tension/peel. This is the weakest link, TODO(verify: epoxy peel strength); SO3 can be drilled to remove it.
- **Lateral loads.** Clamp friction carries them (4 x preload x Î¼). If the clamp slips, the CR moves within the 0.2 mm radial hole clearance and loads the pins in bending, TODO(verify: nylon M2.5 preload). The pins carry only the electrical connection when the clamp holds.

### 3. Rows that change

**Design document** (`docs/charger_bq25798_wiring_design_2026-11-05.md`):

- **A.7 header stack** (`:852-870`): replace with the P4 equations. Delete the polyimide-sheet and 2.665 mm basis.
- **A.7 / A.8 FT1, FT2 rows** (A.8 FT1/FT2 rows, `:80`, `:86`): delete. Add rows MH1-MH4 (optionally MH5, MH6) with the P2 hole and keep-outs.
- **H.23(j)** (`:3147`): new stack arithmetic. H.23(a) loses its foot terms.
- **D.1 PM4:** the foot steps (2c) and (5) and the rv7-1 / r8-10 foot-bond procedure become "bond standoffs, dry fit, shim, screw".
- **T-A-09:** foot check becomes standoff fit and the Î´_i check.
- **MS1a / T-A-08:** add the position and height of each Ag105 corner standoff (useful as the S reference) and the SO1-SO6 site survey.
- **E (BOM):** delete the FT1/FT2 machined feet. Add 4-6 nylon hex standoffs, nylon screws, a shim set and the epoxy.

**LAYOUT_DECISIONS.md:**

- **D-19 (feet):** retired. Replace it with a new D-xx "Standoff holes" (P2/P3).
- **D-17 (bottom clearance rule):** re-scope, because the 2.665 mm basis is gone.
- **D-08 (fixed pads):** add MH1-MH4.
- **D-36 / VR-1:** note that the standoff holes carry no pads, so no conflict arises.

### 4. Operator questions

1. Is a bonded nylon standoff without an MB hole acceptable at SO1, SO2 and SO4, and should SO3 be drilled (F5)?
2. Do you accept positions 1-9 mm from the CHG corners (Table 2) instead of the corners themselves? The -x corners are off the CR.
3. Should two more supports go near the CR ends (F6), subject to your survey?
4. Is SO2 too hot for nylon? Please give a temperature reading at (56.4, 34.4) with REG-5V and the BT boost loaded.
5. Should the CR be screwed to the standoffs (as proposed) or only rest on them with the pins locating it? Resting only gives no uplift or lateral restraint beyond the pin retention.
6. Did the Ag105 sit on its own corner standoffs (the MS1a reading)? If so, their height is a direct S reference.

Scratch scripts: `C:\Users\ricky\AppData\Local\Temp\claude\3fe373bc8dcb48b3\88ddad5f-e7e9-4a73-b399-a08cdcf77486\scratchpad\outline\standoffs\scan.py`, `C:\Users\ricky\AppData\Local\Temp\claude\3fe373bc8dcb48b3\88ddad5f-e7e9-4a73-b399-a08cdcf77486\scratchpad\outline\standoffs\freedisc.py` and `C:\Users\ricky\AppData\Local\Temp\claude\3fe373bc8dcb48b3\88ddad5f-e7e9-4a73-b399-a08cdcf77486\scratchpad\outline\standoffs\ends.py`. Limitation: the obstacle model uses silk/tDocu wire bounding boxes and pads only, so any part drawn as a polygon or rectangle, any text, and all bodges are missed (each position stays TODO(measure: operator)).
