# Round 4 (r7) design basis: decisions for the in-place revision of the BQ25798EVM wiring design

This note fixes the r7 decisions before the calculation (`round4/calc/r7_calc.py`) and the in-place revision of
`docs/charger_bq25798_wiring_design_2026-11-05.md` (the **design**). It is the brief that every r7 agent follows. Where a number
below says "r7_calc", the value in the design must come from `round4/calc/r7_calc_out.txt`, not from this note.

Inputs: the four fact-finding notes (`work/evm_geometry.md`, `work/mb_mechanical.md`, `work/eib_merge_failsafe.md`,
`work/stackup_area.md`), the three proposals (`work/proposal_minimal.md`, `work/proposal_tapside.md`,
`work/proposal_evm_on_cr.md`) and the two judge reports (both chose the minimal proposal, 41/50 and 36/50; tapside 32 and
30; evm_on_cr 22 and 22). The judge reports are summarised in section 9.

Coordinates: Eagle `.brd` board coordinates, mm, top view, origin at the MB origin, +x right, +y up (design A.2). EVM points:
EVM frame of `work/evm_geometry.md` (origin at the lower-left corner of the EVM outline, top view).

## 1. Coined terms and identifiers (use verbatim; one term = one meaning)

| Term | Meaning |
|---|---|
| **tab X** | the CR extension toward the Teensy: x 48.70-65.00, y 56.30-68.30 |
| **tab Y** | the CR extension toward L-FC: x 17.70-37.56, y 67.14-76.00 (trimmed from the proposal's x 39.72 / y 76.51) |
| **r7 outline** | the r6 rectangle x 17.70-48.70, y 34.14-67.14 plus tab X and tab Y, with the relocated pin-11 chamfer |
| **bottom clearance rule** | every CR bottom-side courtyard stays >= 1.0 mm in plan from every MB layer-1 feature that is not GND (traces, pours and vias of any other net, measured on the copper rim including the polygon outline width) and from every MB part box; it applies on the footprint and on both tabs. It replaces the r3 power-copper shadow (+1 mm) and the named bottom keep-out x 24.5-36.0, y 48.5-53.5, of which it is a superset. (The proposals call it "rule B"; the design uses the long name only.) |
| **thermal band** | the part of tab X within 6.4 mm of the MB 5V copper rim; it carries only pads, wires, the RTV bead and temperature-insensitive passives (R175, 1 % logic series resistors and pull-downs); no comparator, reference, 0.1 % divider, BAV199 or timing capacitor |
| **FT1**, **FT2** | the far-end support feet under tab X (FT1) and tab Y (FT2) |
| **MS1-MS8** | the operator measurements of section 6. Do NOT call them M1-M5: M1-M11 are the EVM modifications of the evaluation study (`docs/charger_replacement_evaluation_2026-11-05.md` section 4.2), and the work notes' "M1-M7" measurement labels collide with them. |
| **EVM plate** | the insulating plate that carries the EVM (on its stock bumpons, held by four corner clamps) and the EIB (on its two M3 nylon standoffs), fixed to the chassis |
| **route rule** | W-lead build maximum = 1.25 x the routed length (CR pad -> corridor -> MB edge -> terminal approach on its wire-entry side -> terminal), rounded up to 10 mm |

## 2. Decisions (answers to Q1-Q6)

### D1. Outline (Q1)

- r7 outline = r6 rectangle + tab X + tab Y (trimmed). Gross area r7_calc (expected 1023.0 + 195.6 + 175.96 = ~1394.6 mm² less the
  chamfer).
- Tab Y is trimmed on two edges against the judges' findings:
  - right edge x 39.72 -> **37.56**: ROP1-FC (x 38.06-39.66, y 73.43-75.86) and the ROP2-FC corner are part of the FC droop
    network (OPA197 gain set), whose AD5443/OPA197 DMM block measurement is an open bench item; trimming keeps them reachable and
    no MB part lies under either tab. OP-FC (x 40.22) then has 2.66 mm.
  - top edge y 76.51 -> **76.00**: the L-FC silkscreen is y 77.01 but the Eaton listing gives a 12.9 mm body (`TODO(verify:
    Eaton HCM1A1305V3 drawing)`); with 12.9 mm the plan gap would be 0.35 mm at y 76.51 before placement tolerance; at 76.00 it is
    >= 0.86 mm.
- Tab X keeps x 65.00. The VBUS L1 polygon has a 1.016 mm outline width, so its copper rim reaches x ~65.02: the tab X right
  edge sits on the VBUS copper rim in plan. This is acceptable because the tab edge region carries no exposed copper underneath
  (bottom clearance rule, L4 mask, polyimide sheet), but every plan clearance and the bottom clearance rule must be computed on
  copper rims, not on polygon vertex paths (5V polygon width 0.508 mm: rim at y 54.86; the 5V L1 trace + via at (59.39, 55.58)
  reach y ~55.83, 0.47 mm below the tab X low edge).
- **Pin-11 chamfer kept and relocated:** the r6 chamfer corner (17.70, 67.14) becomes an edge point of the r7 outline. The
  1.0 mm x 45 degree chamfer moves to the tab Y -x/+y corner (17.70, 76.00), which stays the only chamfered corner and marks the
  pin-11 side. A y-mirrored capture additionally puts tab X over REG-5V (4.83 mm tall), so it cannot seat; the print check
  (T-A-06 step 0) still catches the mirror before ordering. `calc/pin_identity_check.py` is unchanged (pads unchanged).
- No MB part lies under either tab (r7_calc confirms). Neither tab covers a named rework point (R171/T2 joint on C-D2 pad 1,
  RENC2, BAL pad 8, RB1A, CBL2, CO-5V, the T18 point, ROP1-FC, ROP2-FC).
- Rejected zones (record the reasons in A.7): -x and off-board past x = 0 (J-BL/J-FC 21.70 mm, J-NTC 13.90 mm; J-BL wire entry
  and screws); -y (BAL pad 8 = T22/PM11, RB1A, CBL2; 2.96 mm from VSW-BT); +y wide / edge-reaching zones (need a raised stack,
  cover the FC droop analog or a boost switching node); +x beyond x 65.00 (34.2 mm cantilever, f1 estimate 0.51-0.73 kHz, over
  139 mm² of the 16 V VBUS pour, arm tip 0.5 mm from RENC2 in the unrecorded encoder-bodge area; this was the runner-up
  "tapside" proposal); the EVM on the CR ("evm_on_cr": covers the whole FC boost channel, which has an open undiagnosed fault).

### D2. Header stack (Q1)

- Header parts unchanged: Samtec TSW-110-07-G-S (column x 45.998, pins 1-10) and TSW-112-07-G-S (column x 20.998, pins 11-22),
  2.54 mm PBT body, 0.64 mm square post. No spacer, no raised stack. The body seats on the 0.125 mm polyimide sheet (kept, D4):
  CR underside 2.665 mm above the MB, CR top 4.265 mm (CR 1.6 mm, `TODO(verify: CR fab stack-up)`). The stack height over the
  footprint is unchanged from r6; the W5 IDC socket and ribbon fold (>= 8 mm above the CR top, A.3) stay the tallest item at
  ~12.3 mm + cable against the nominal Ag105 envelope of 13.14 mm (AG105_Silvertel.pdf Figure 11 p.21). Gate D-2 (MS1) still
  gates PM1.
- Post arithmetic (r7_calc, with the sheet): the orientation and protrusions of r6 PM4 apply unchanged; the agent restates them
  only if r7_calc shows a difference.

### D3. Far-end support (Q1; operator constraint "a cantilever on 22 x 0.64 mm pins needs support at the far end")

- **Both tabs carry a fitted foot by default** (not "reserved"). FT1 under tab X near its tip; FT2 under tab Y near its far
  edge. Locations by r7_calc: 4 x 4 mm foot body, >= 0.5 mm from the outline, no MB via under the foot, no non-GND MB copper
  within 1.0 mm of the foot body (rims), clear of the tap pads' wire exits. Starting points: FT1 centre (62.7, 61.26) (the off-pour
  spot of `work/mb_support_spots_out.txt`; minimal's keep-out x 60.70-64.70, y 59.26-63.26); FT2 near the middle of the tab Y far
  edge (r7_calc chooses; the tab Y underside holds one N$8 trace and one GND via).
- Foot construction: a PA66 or PBT block 4 x 4 mm, height h_f = 2.54 mm - t_bed with t_bed = 0.30 mm nominal (2.24 mm), bonded to
  the CR underside with neutral-cure RTV silicone before seating. **After** the 22 MB joints are soldered and inspected (no wet
  adhesive during soldering, no preload: the header bodies set the height), a neutral-cure RTV bed fills the 0.30 +- 0.15 mm gap
  between the foot and the polyimide sheet, applied with a syringe from the tab edge; cure >= 24 h before the bond check.
  Acetoxy-cure RTV is excluded (acetic acid near copper). The sheet is the sacrificial layer: removal = cut the bed, peel the
  sheet; the MB mask is never bonded. `TODO(verify: RTV datasheet: neutral cure, temperature rating, adhesion to polyimide
  without primer)`. Fallback if the bond check fails on polyimide: a 5 x 5 mm cut-out in the sheet at the foot spot and the bed
  bonds to the MB solder mask (the spot carries no power copper).
- r7_calc gives the tab tip stiffness, the RTV bed stiffness (E_RTV assumed 1-3 MPa, `TODO(verify)`), the propped first-mode
  estimate and the pin loads with and without the feet. Every resonance figure is an order-of-magnitude upper estimate (assumed
  20 GPa laminate, clamped root); MS5 and T-F-18 decide.

### D4. Polyimide sheet (Q5): KEPT

- Both judges rejected the minimal proposal's retirement: the sheet is the r3 secondary barrier of finding
  cr-bottom-over-mb-power-traces and costs USD 10. The bottom clearance rule is added **on top of** the sheet: two layers.
- r7 sheet outline = r7 outline + 1 mm on every side, **trimmed to >= 0.5 mm from every MB part body** it would otherwise meet
  (r7_calc lists them: expected L-FC and ROP1-FC at tab Y, the J-NTC corner, and CO-5V). The r6 relief holes at the 22 header
  pads and the five footprint cut-outs (D-BT-SQ, C-D11, C-D12, C-DC11, C-DC12) are unchanged.
- **Latent r6 item to check (r7_calc):** the r6 sheet "outline + 1 mm" runs to x 49.70; CO-5V's box starts at x 49.30
  (y 37.27-41.98). If the sheet overlaps the CO-5V body, the r6 drawing put the sheet onto a 2.1 mm tantalum, against r5's
  "cut-outs, not a drape". Record the result as a self-found item in the r7 change table and fix it in the r7 sheet outline.

### D5. Layer count and stack-up (Q4)

- 4-layer, 1.6 mm, double-sided, passives only on the bottom (<= 1.0 mm). Stack-up = `work/stackup_area.md` 7.2 = r6: L1 2 oz
  (1 oz allowed by the PM0 DFM check, then pours >= 2.5 mm battery side, >= 2.0 mm input side), prepreg 0.2 mm, L2 1 oz solid
  GND, core ~1.0-1.1 mm, L3 1 oz signals, prepreg 0.2 mm, L4 2 oz GND pour stitched <= 5 mm, every L4 via tented.
- Reasons: single-sided needs U 100-108 % on the r7 outline (r7_calc restates for the trimmed tab Y); 2-layer raises the
  commutation-loop inductance 4-7x per mm and the coupling into the comparator inputs 46-53x; matching the 4-layer coupling at
  5 mm needs 36.5 mm of separation, and no point of the r7 outline is that far from the U101 loop (r7_calc: farthest point).
- Battery-side copper (3.21 A): W3/W4 stay at the pin columns, so the battery current stays out of the tabs; pours >= 2.5 mm
  (2 oz 7.7 A, 1 oz 4.6 A at 10 C rise, H.22(c)). It does not decide the layer count.
- Comparator-vs-power separation: the comparators U102-U104, U115, U119-U121 with their 0.1 % dividers and filter capacitors move
  from the bottom to the top of the footprint low-y band (the freed r6 tap-field area, x 23.15-42.43, y 35.05-41.63), which is
  >= 10.4 mm from the commutation-loop band (y >= 52.03) and 8.5-27.8 mm from the LM1084 body (r7_calc). The battery copper near W3
  (24.3, 45.4) is low di/dt and is not the aggressor.

### D6. Area and placement allocation (Q4/Q5)

- Area booking on the strict basis of `work/stackup_area.md` (r7_calc): top usable, top U with the r3 bottom set, bottom area
  under the bottom clearance rule minus the two foot keep-outs, bottom U. Target <= 75 % each side. The r6 "~678 of ~881 mm²"
  and the 95-103 % strict-basis overrun retire.
- Allocation (minimal Table 9, adjusted for the trimmed tab Y and the feet): tab X top = tap field (21 SMT pads 1.5 x 1.5 mm in a
  6 x 4 grid at 2.54 mm; r7_calc gives the exact centres and the per-tap straight lengths) + R175; tab X bottom = bottom-clearance-
  rule passives in the thermal-band classes + FT1 keep-out; footprint low-y band = residual pads F08 (T22), F09 (T8), F10 (T9) +
  the comparators with their dividers and filter caps (top); footprint high-y band = U101 cluster unchanged (A.8 r5 table);
  footprint interior = J101 region, U122/U123/D108 near F08, monostables, W3/W4, W6/W7 pads unchanged; tab Y top = LVC gates
  U105-U110, U114, U116, U118 with decouplers (driven logic only; no comparator input or timing node within 10 mm of L-FC);
  tab Y bottom = logic pull-downs, series resistors, decouplers + FT2 keep-out.
- Tap wires from tab X are dressed toward +y until x > 63, never over the LM1084 body. The A.4 maximum tap lengths stay valid
  upper bounds; A.4 gains the r7 straight lengths as information.

### D7. EVM placement and leads (Q2)

- The EVM cannot mount on the CR (88.90 x 88.90 mm = ~5.7x the r7 CR area; no mounting holes; its mass on 22 pins). It cannot sit
  directly beside the CR on the MB (no part-free 89 x 89 mm region; J-BL screws must stay reachable; MB has only two plain holes,
  both at x 3.30). A mezzanine over the MB is recorded as an option for a later round (operator ruling), not adopted.
- **EVM mount (EM23 rewritten):** the EVM has no mounting holes (the corner circles are fiducials; SLUUCB5E Figs 4-1..4-4, BOM
  FID1-FID6). The stock bumpons H1-H4 (3M SJ-5303, 11.18 mm dia, 5.08 mm) stay and rest on the EVM plate; two nylon clamp bars
  (or four corner L-clamps) with 0.5 mm silicone pads press <= 2.0 mm edge lips, notched at J8, clear of TP48/TP49, the terminal
  wire faces and the fiducials; no fastener or adhesive bonds EVM copper to the plate, the CR or the chassis; the EIB sits on the
  same plate on its two M3 nylon standoffs (one rigid body: no E-lead relative motion). Plate and clamp geometry
  `TODO(design: from MS2 and MS7)`. No drilling of the EVM.
- **Reference placement (adopted once MS2 confirms the chassis room):** the EVM plate on the chassis just past the MB +y edge,
  EVM bottom edge toward the MB with a gap for the J8 housing (J8 mates from -y), EVM right edge at x <= 88.5 so the Teensy 4.1
  USB plug corridor (exits +y at x 93.47-101.09 from y 93.73; plug + bend `TODO(measure: MS2)`) stays free; the EIB beside the
  EVM right edge per the r6 rule must also stay out of that corridor (r7_calc checks; if it cannot, the EIB moves to the EVM
  left edge or the EVM rotates, r7_calc picks). r7_calc computes the W-lead route maxima (route rule) for that placement. **Until
  MS2 confirms it, the r6 0.30 m caps stay the T-A-02 bound**; the route maxima become the build maxima after MS2. The chassis tie
  within 30 mm of the CR edge (A.3 r5) is met at the MB +y edge for leads leaving over tab X (r7_calc: distance).
- **E-leads:** the EIB placement relative to the EVM is unchanged, so the r6 rule (straight x 1.25, rounded up to 5 mm) re-runs
  on the vector EVM positions: E8 20, E3 25, E4 30, E2 35, E7 40, **E1 90** (was 85), **E5 65** (was 60), E6 60 mm. E4 lands on
  JP21 pin 1 = the **lower** square post (75.312, 64.769) EVM mm; the A.5 pixel point (902, 408) is the AGND post (pin 2). The pickup
  criterion of `work/eib_merge_failsafe.md` Table 9 (sustained EMF <= 10 % of the smallest margin) documents the margin: every
  length-critical build maximum is <= ~0.5 of its criterion limit (E4 tightest).
- **R276:** 10.0 ohm 1 % 0603 (CRCW060310R0FKEA, same MPN as R273) in series with E1 at the EIB E1 pad, between the E1 lead and the
  EIB REGN node (C205). Reason: E1 with its E8 return and C205 (100 nF) is a series LC near the 1.5 MHz switching frequency
  (~1.47 MHz at 85 mm, ~1.43 MHz at 90 mm), undamped Q ~19-20. r7_calc recomputes the resonance, Q with and without R276 and the
  static drop across R276 at the E1 load (H.15) and at any ILIM clamp current; the agent states which effect on the release level
  it is and its size (the work note's "1.6 mV at 2 mA" must be re-derived, not copied).
- W-lead CR ends are unchanged (W1 (30.3, 61.2), W2 (27.7, 61.2), W3 (24.3, 45.4), W4 (24.3, 55.6), W7 pads y 57.5 at x
  27.0/29.0/31.0, W6 pads (33.0, 57.5)/(35.0, 57.5), J101 x 37.0-44.5, y 42.13-51.53): the CR extension does not shorten the EVM
  leads. Only the EVM placement does.

### D8. EIB merge (Q3): no

- With the EVM off the MB, the CR-edge-to-EVM-pin distance is 0.10-0.30 m (geometry G2), where a direct merge inverts the r1-2
  premise (exports the unbuffered ILIM_HIZ node, REGN, /CE and STAT; a single E-bundle short E1 to the ILIM group removes the
  hardware input clamp undetected); its re-proof needs EVM-end parts and shielded cables, which re-create the EIB. Area: the
  merged courtyard (~253 mm²) would raise the top utilisation by ~19 points.
- Every r6 fail-safe argument holds as is (EIB, W5 list, U203/U204, R272/R272b, E8/R273 unchanged); three documentation changes:
  the JP21 pin-1 coordinate, the E1/E5 maxima and R276.
- Recorded as a documented future option (not adopted): the G1 island merge (EVM within 10-60 mm of a CR edge, rigid co-mount)
  under the ten conditions of `work/eib_merge_failsafe.md` section 7 (island + R273 only tie, A.9 pad order and isolation pairs
  unchanged, lead dressing, parts kept/deleted, E1 damping, one rigid body, thermal, area, the EVM stage >= 20 mm from U104/U102/U103
  and T8/T9).

### D9. Round-3 constraints (Q5)

| Constraint | r7 |
|---|---|
| CR confined to the 31 x 33 mm footprint (A.1, A.7) | retires |
| Area budget "~678 of ~881 mm²" (H.18, H.22(k)); strict-basis 95-103 % | retires; replaced by H.23 |
| A.7 "overhang only if the capture needs it" | retires; replaced by the defined tabs |
| Named bottom keep-out x 24.5-36.0, y 48.5-53.5 | retires as a named rectangle; the bottom clearance rule covers it |
| MB power-copper shadow +1 mm | changes into the bottom clearance rule (stricter: every non-GND feature, rims, footprint + tabs) |
| 4-layer build | stays (D5) |
| Passives-only bottom, <= 1.0 mm | stays (single-sided does not fit; >= 1.5 mm air under the 2.54 mm body) |
| Polyimide sheet | stays, cut to the r7 outline + 1 mm with trims (D4) |
| Flush-cut tails <= 0.5 mm | stays for W1-W4 (the only CR through-hole parts with a tail on the CR underside; the header bodies cover the pin rings); applies to the r7 underside |
| Top-side SMT tap pads, no bottom-side tap tails | stays (tab X lies over MB MPPT-DISABLE, CB-DISABLE, CHRG-STAT, SCL, SDA and 3V3 traces) |
| Pin-11 chamfer | stays, relocated (D1) |
| EVM on four M3 standoffs in the corner holes | retires (no holes); D7 |
| EIB on two M3 standoffs on the chassis | changes: same standoffs, on the EVM plate |
| U101 loop rules, A.6 ground scheme, W1-W4 holes, header strips and ratings, courtyards >= 0.5 mm from outline and pads | stay |
| MB battery path under the CR (T-A-06c Kelvin, PM4 step 1a overlay, T-F-16 thermocouple) | stays |

### D10. EVM and MB modifications (Q6)

- No EVM modification and no MB modification becomes unnecessary: every EM item serves the EVM's electrical function, which the
  carrier change does not touch, and every PM item is still required. Study M1-M11 -> design EM mapping as in
  `work/proposal_minimal.md` Table 11.
- Changed text: EM5 (JP21 pin 1 = lower square post (75.312, 64.769)); EM23 rewritten (D7). PM0 (capture on the r7 outline, the
  bottom clearance rule in the bottom DRC, tap field split, chamfer relocated, foot keep-outs); PM1 (MS1 recorded first, as r6);
  PM4 (sheet cut to the r7 outline; the CR supported under both tabs while the 22 MB joints are soldered; feet bonded after
  soldering, D3); PM6 (18 taps land on the tab X field and three (T22, T8, T9) on F08-F10). The section agent checks every other
  PM for a dependency on the footprint confinement and reports any found.
- D.4 bodge-record text: add the tabs, the two feet and the r7 sheet; the record stays a proposal for CLAUDE.md (never-rotated
  hardware records, once built).

### D11. Files this design does not edit (proposals only)

- CLAUDE.md: no change required by r7 itself; the D.4 bodge record (proposal) gains the r7 items.
- `teensy_controller/teensy_controller.ino`: no change (r7 is mechanical; no pin, threshold or timing changes).
- WORK_QUEUE.md: proposal to add one queue item for the operator measurements MS1-MS8 with their gates.
- `references/Scale Car Teensy IO - IO.csv`: no change.

## 3. BOM and cost (E)

Changes (budget allowances, not verified prices): CR PCB on the r7 outline (bbox ~47.30 x 41.86 mm; allowance USD 70 -> 70-100,
`TODO(verify: fab quote)`); polyimide sheet unchanged in count (check it is cut from the same sheet size at the larger outline);
R276 (new, 1 + 1 spare); EVM plate + clamp bars/L-clamps + silicone pads (new allowance USD 0-15; EVM M3 standoffs x 4 deleted;
EIB keeps its two); FT1/FT2 feet (2 + 2 spare, PA66/PBT block) + neutral-cure RTV (r6 RTV line: check the cure type; add if
acetoxy) USD 0-5. The section agent recomputes the E total range from the r6 total.

## 4. Test registry (section I) changes

Existing IDs end at T-A-07, T-C-15, T-F-17 (T-F-10 is absent: do not reuse it). New IDs: **T-A-08**, **T-A-09**, **T-C-16**,
**T-F-18**. (`work/eib_merge_failsafe.md` proposes T-A-08/T-C-16/T-F-18 with other content for the G1 merge; that merge is not
adopted, so the IDs are free; the review log notes the reuse.)

- **T-A-08 Pre-capture survey (gate for PM0; MS1 part gates PM1):** MS1-MS7 as listed in section 6 with pass/fail: no unrecorded
  item inside a tab outline + 0.5 mm or under a foot spot; L-FC body >= 0.5 mm from the tab Y top edge; MB thickness enters the
  post arithmetic; the MS4 and MS5 results confirm the thermal-band split and the foot design. Fail: trim the tab and re-run
  `round4/calc/r7_calc.py`.
- **T-A-09 Foot fit and bond check:** after cure, no gap at either bed interface (feeler 0.05 mm); 5 N upward pull at each tab tip
  for 10 s: no debond; loupe inspection of the 22 header joints before and after; header-pin joint resistance unchanged (T-F-12
  method). Fail: re-bed; if RTV does not hold on polyimide, the sheet cut-out fallback of D3.
- **T-C-16 E1/C205 ring:** charger converting at the regen image (ICHG 3.10 A); scope REGN at C205 against E8 on the EIB and at
  TP27 against TP49 on the EVM, with R276 bridged by a temporary link and with R276 in circuit. Pass with R276: the ring amplitude at
  C205 does not exceed the REGN ripple at TP27.
- **T-F-18 Tab vibration and joint integrity (MS5 follow-up):** accelerometers on the MB near pin 10 and on the tab X top over FT1
  during a representative run, spectrum 0.1-8 kHz, transmissibility tab/MB; then the loupe inspection and the T-F-12 resistance
  checks. Pass: no cracked joint, no T-F-12 change, no bed debond; transmissibility <= 3 where the MB excitation is above the
  logger noise floor (proposed criterion, operator to confirm).
- Changed: T-A-02 (delete "corner-hole diameter", "M3 rod through a corner hole", the M2.5/adhesive fallback; add EVM plate and
  clamp fit, clamps clear of TP48/TP49 and wire faces, EVM copper (TP49, J1 pin 1) to plate and chassis > 1 MOhm with W1-W7
  disconnected, EIB on the plate, E-lead maxima per D7 incl. E1 90/E5 65 and E4 on the lower JP21 post, R276 fitted and measured
  10.0 ohm +-1 %, W-lead maxima = 0.30 m until MS2, route maxima after MS2); T-A-05 (R276, clamp/plate/foot materials and
  temperature ratings, RTV neutral cure, sheet size); T-A-06 (placement DRC on the r7 outline; bottom-clearance-rule overlay on
  the `.brd` layer-1 copper rims; L4 solder-mask Gerber check: no opening except W1-W4 and the 22 header rings; foot keep-outs
  free; thermal-band content check; sheet print on the r7 sheet outline with its trims; chamfer at (17.70, 76.00); dry fit of
  both tabs; E-lead lengths per D7); T-F-12 (chafe inspection now also under both tabs; feet beds intact); calculation rows
  H.18, H.22(i), H.22(k) point to H.23.
- Every row that cites the 31 x 33 mm outline, the bottom keep-out rectangle, the r6 tap field position, the EVM corner holes or
  the r6 E1/E5 maxima is updated or marked superseded; the section agent greps for them.

## 5. Calculation (H.23, `round4/calc/r7_calc.py`)

Stdlib-only Python (as r3_calc.py), reads the `.brd` through `round4/calc/mb_neighbours.py`, prints labelled sections H.23(a)..,
writes `r7_calc_out.txt` and `r7_calc_out.json`. Required sections: (a) r7 outline, areas, chamfer; (b) plan clearances of each
tab and of the sheet to MB parts and copper rims; (c) MB content under each tab (parts, copper by net, vias); (d) bottom
clearance rule area on footprint, tab X, tab Y minus foot keep-outs; (e) area booking and U per side, single-sided U; (f)
farthest outline point from the U101 loop; (g) tap field centres and per-tap straight lengths vs r6; (h) thermal band distances;
(i) foot spots, copper under them, foot and bed dimensions, stiffness, propped/unpropped f1, pin loads (10 g, 30 g, 10 N tip
push) with/without feet; (j) header post arithmetic with the sheet; stack height vs Ag105 envelope; (k) E-lead maxima on vector
positions; E1/C205 resonance, Q with/without R276, R276 static drop; (l) EVM reference placement, USB corridor check, EIB position,
W-lead route maxima, lead resistances at the route maxima vs 0.30 m (H.11 basis), chassis-tie distance; (m) r6 sheet vs CO-5V
check. Each input carries its source or ASSUMPTION / TODO marker.

## 6. Operator measurements MS1-MS8 (before the outline is frozen; T-A-08)

1. **MS1 (gate D-2, before PM1):** Ag105 standoff (MB top to module underside) at four corners, module top height above the MB,
   module mass after removal. Decides: the CR stack top (~12.3 mm + cable) against the measured module envelope.
2. **MS2 (enclosure and chassis):** lid clearance over the footprint and both tabs, lid profile; chassis room past the MB +y edge
   for the EVM plate (EVM 88.90 x 88.90 mm + clamps + the J8 mating gap), the MB mounting scheme (two holes at x 3.30), chassis
   clearance under the MB for the 22 tails (<= 1.0 mm after PM4), the Teensy USB plug length and bend room. Decides: the EVM plate
   position and the W-lead route maxima.
3. **MS3 (survey of unrecorded items):** inside each tab outline + 0.5 mm and under each foot spot: the OPA197 5 V bodge wire path
   (may run between LM1084/CO-5V and OP-FC through x 48.7-52, y 54-67), the 10 kOhm EN bodge resistors (D-FC-EN), the 74HC14, the
   2026-08-16 encoder reroute wires, R171 on C-D2 pad 1, RENC2; position and height of each. L-FC body by caliper. Decides: the tab
   outlines (gate for PM0).
4. **MS4 (LM1084 thermal survey, on the current board):** MB surface at 1, 5, 10 mm from the 5V copper rim along x = 57 into the
   tab X area, closed enclosure, Run with Ethernet and SD active, V_batt 8.4 V and 7.4 V, 30 min soak; LM1084 input current.
   Decides: the thermal-band split (estimate 3.3-17 C rise at 5 mm, `work/mb_mechanical.md` Table 4).
5. **MS5 (vibration, on the current vehicle):** accelerometer on the MB near the CHG footprint in a representative run, peak shock
   and spectrum 0.1-8 kHz. Decides: whether the feet suffice (T-F-18 confirms after the build).
6. **MS6 (thicknesses):** MB at the CHG holes (caliper); CR finished thickness and laminate modulus from the chosen fab. Decides:
   the post arithmetic, the foot height, the f1 estimates.
7. **MS7 (EVM as received):** thickness, as-built outline, mass with shunts (and after EM7), TH-tail protrusion, heights of J7, J8,
   J9, the jumper headers with shunts, the test points. Decides: the clamp design and the plate clearances.
8. **MS8 (fab rules):** the chosen fab's 1.6 mm 4-layer stack-up table, L4 tenting, minimum inside-corner router radius, 2 oz
   outer minimum space at the U101 0.5 mm pitch. Decides: the PM0 DFM check (copper weight) and the concave tab-root corners.

## 7. Section-by-section edit plan of the design

| Section | r7 edit |
|---|---|
| Title, status (lines 1-3), supporting-files table | round 4 r7; status line adds r7 after review round 7; files table adds the `round4/` files |
| 0.2 Verdict | one r7 paragraph: carrier extended by two tabs, EVM/EIB unchanged in function, no fail-safe argument changes |
| 0.3 | new "Round 4 r7" change table (r7-1...) from these decisions + the review round 7 table appended later |
| 0.4 | add round 4 / review round 7 sentence (filled after the review) |
| A.1 | CR row (outline, tabs, feet), EVM row (plate, clamps), EIB row (on the EVM plate) |
| A.3 | W-lead maxima note (0.30 m until MS2, route maxima after); chassis tie at the MB +y edge |
| A.4 | tap field move (F01-F07, F11-F24 on tab X; F08-F10 residual), r7 straight lengths |
| A.5 | JP21 pin 1 lower post; E1 90 / E5 65; R276 |
| A.6 | L2 plane continuous into both tabs; feet non-conductive; nothing else |
| A.7 | r7 outline, tab content, rejected zones, chamfer relocation, sheet outline (r7) with trims, the bottom clearance rule (replaces shadow + keep-out, marked superseded), feet, EVM mount, EIB mount; r6 bullets marked superseded, not deleted |
| A.8 | per-region table: add tab X / tab Y regions, footprint low-y band re-use; copper rules unchanged |
| A.9 | R276 at the E1 pad; pad order unchanged |
| B.6 | R276 in the EIB part list; fail-safe arguments unchanged (one sentence) |
| C | EM5 text, EM23 rewritten |
| D.1 | PM0, PM1, PM4, PM6 changes |
| D.3 | no CSV change (one sentence) |
| D.4 | bodge record adds tabs, feet, r7 sheet |
| D.5 (new) | r7 proposals for files this design does not edit (D11) |
| E | BOM lines + cost range |
| H | H.18, H.18b, H.22(i), H.22(k) marked superseded by H.23 where they are; new H.23 table from r7_calc |
| I | T-A-02, T-A-05, T-A-06, T-A-06c (if it mentions the sheet timing), T-F-12 changed; T-A-08, T-A-09, T-C-16, T-F-18 new; every stale reference fixed |
| J | J.2 new open items (MS1-MS8; EVM plate design; foot bond on polyimide; L-FC body; G1 merge option; mezzanine option) |
| K | add SLUUCB5E rev E vector figures, On-Shore ED120 drawing, Samtec F-226, 3M SJ-5303 |
| L.7 | review round 7 dispositions (after the review) |

## 8. What must not change

The permit logic (B.1), the comparator thresholds (B.2, H.4), the eFuse design (B.4), the EIB circuit apart from R276, the W5
pin list, the firmware requirements (G), the operating modes (F), the A.6 ground topology and the U101 loop geometry. Round 4
changes the carrier's mechanics, its placement map and the EVM mount, and nothing else.

## 9. Judge findings carried into r7

- Keep the polyimide sheet (both judges); keep the pin-11 chamfer (judge 2); fit the far-end foot by default (judge 2, operator
  constraint); trim tab Y off ROP1-FC/ROP2-FC (both); compute clearances on copper rims (judge 2: VBUS polygon width 1.016 mm,
  5V 0.508 mm); L-FC 12.9 mm body (both); EVM placement x <= 88.5 for the Teensy USB exit (both); thermal-band rule and the MS3
  survey list incl. the OPA197 5 V wire path (judge 1, from tapside); precision analog in the freed r6 tap-field area (judge 1);
  EVM clamp details and insulation check (judge 1, from evm_on_cr); R276, the JP21 correction, E1 90 / E5 65, EM23 rewrite (all);
  the G1 island merge only as a documented option (both); the route rule for W maxima after MS2 (both).
- Judge-recorded factual errors in the proposals that r7 must not inherit: minimal's "0.53 mm before the VBUS pour" (rim 0.02 mm),
  "the same clearance that the r6 outline keeps (1.8 mm)" (the r6 outline keeps 2.27 mm to REG-5V; 1.8 mm is from the
  silkscreen), "neither tab covers a named rework point" (tab Y covered ROP1-FC; fixed by the trim), "5V pour rim y ~54.86 at
  1.44 mm" (the 5V trace/via reach y ~55.83); tapside's EVM tray over the Teensy USB corridor; evm_on_cr's E1 105 mm beyond the
  analysed 90 mm.

## 10. Addendum after H.23 (decisions on the r7_calc results and the independent check)

The first `r7_calc.py` run and its independent check (`work/r7_check/`) agree on every decision-relevant number. The check found
five calculation errors (square MB header pads treated as discs; per-shape instead of per-net copper areas; the SCL L1 trace
missing from the "< 0.5 mm outside tab X" list; the r6 basis of T22/T8/T9; the J201 label). None changes a tab or a foot
decision. The decisions below supersede the corresponding text in sections 2-7 where they differ.

- **A1 FT1/FT2 size and position.** No 4 x 4 mm body in tab X meets the D3 rule (via-free, copper rim >= 1.0 mm, >= 0.5 mm inside
  the outline): the MB signal bundle (SDA, SCL, CHRG-STAT, MPPT-DISABLE, CB-DISABLE, 3V3, CS-MDAC-FC) crosses the whole tab tip.
  The largest compliant body (4.0 x 2.0 mm at (62.00, 66.70)) has only ~ +-0.1 mm of placement slack in y and +0.024 mm in +x.
  Criterion adopted: **each foot is the largest bed area whose placement tolerance is >= +-0.25 mm in x and in y against the full
  D3 rule, centred to maximise the smallest slack.** r7_calc searches widths 3.0-4.0 mm and heights 1.4-4.0 mm at 0.1 mm steps and
  gives the size, centre, tolerances and bed area for FT1 and FT2, then reruns stiffness, f1 and pin loads with them. The relaxed
  4 x 4 mm spot (62.50, 61.40) over masked signal traces stays an operator option only (a bonded foot over signal traces, and the
  MB-mask fallback of D3 is unavailable there).
- **A2 T18 tap pad.** T18 (CO-5V pad 1, option) cannot follow the D6 dressing rule from tab X (its straight path passes 0.17 mm
  left of the REG-5V box). T18's pad F22 moves to the residual row on the footprint, at the r6 grid position nearest CO-5V on the
  low row (expected (41.68, 35.80)); its former tab X position becomes a spare. The residual row is then F08 (T22), F09 (T8),
  F10 (T9), F22 (T18). r7_calc reruns the tab X assignment without T18 and reports any change.
- **A3 Area allocation.** Adopted: **R175 and the six 0.1 % divider resistors R109, R110, R111, R112, R114, R115** move from the
  r3 bottom set to the top; the comparator input filter capacitors C106, C107, C108, C140 stay on the bottom. Reason: the
  dividers are the high-impedance threshold nodes and belong beside the comparators, away from the MB copper; a filter capacitor
  is the low-impedance end of its node. Target <= 75 % each side; r7_calc prints the adopted case beside the core and extended
  readings (which stay as sensitivity rows). Correction to D5: the comparators U102-U104, U115, U119-U121 are already top-side in
  the r3 booking; r7 moves their placement region (to the low-y band), not their side.
- **A4 USB corridor.** The reference placement relies on the 45 mm plug + bend ASSUMPTION (MS2). r7_calc evaluates the fallbacks
  for an open-ended corridor (x 93.47-101.09 from y 93.73): (i) the EVM + EIB group shifted -x until the EIB and the J5 approaches
  clear the corridor band by >= 3 mm (EVM overhang past the MB -x edge); (ii) the EIB moved to the corridor's +x side (EIB left
  edge >= 104.09) with the EVM unchanged: E-lead straight lengths and r6-rule maxima against the D7 values, the pickup criterion
  limits (E3 92, E4 59, E6 196 mm) and the E1/C205 resonance with R276; (iii) the EIB at the EVM left edge (E4 against its
  criterion). The design adopts the reference placement with the first passing fallback, decided by MS2.
- **A5 W5 dressing (A.3).** The r6 text "fold toward -x over the tap field ... along W1/W2" retires. r7: W5 leaves J101 toward +y,
  passes over tab X at the fold height (>= 8 mm above the CR top) with W1/W2 and crosses the MB +y edge in the W-lead band
  (x 56-68.91); it is dressed clear of the tap pads so every tap stays reworkable.
- **A6 Corrections the design must carry (self-found items, r7 change table):**
  - the MB vias are **not tented** (368 of 368 carry alwaysstop; 0.9596 mm openings in both mask Gerbers): A.7 "16 tented GND
    vias" is superseded; the sheet and the bottom clearance rule cover the exposed rings;
  - the r6 sheet outline overlapped the CO-5V body by 0.400 x 3.700 mm (a latent r6 defect against r5 "cut-outs, not a drape");
    the r7 sheet trims fix it, and the J-NTC 0.448 mm clearance;
  - A.5 / H.15: E1 supplies the Q201/Q202 gate pull-ups (R252, R254), R271 and the release feed through Q203/R255; of the H.15
    "REGN pull-ups R254/R272/R272b", only R254 passes through E1 (R272/R272b sit on the EVM);
  - D1 number: the 5V via pad reaches 0.343 mm below the tab X low edge (0.467 mm is the trace rim); D3 text: tab Y has no
    non-GND copper and no via under it;
  - the E1/C205 undamped Q (19-26) is an upper bound (skin effect at 1.43 MHz, Rac/Rdc ~1.7, Q ~13); the R276 conclusion is
    unchanged;
  - the minimal proposal's tap sums used two wrong MB points (T1 3.39 mm off, T9 at the package centre); r7 uses the .brd pads.

## 11. Addendum after the second H.23 run (re-check concerns)

- **B1 FT1** adopted: 4.0 x 1.6 mm, centre at the exact max-min y (about 66.705), t ~0.29 mm; 4.0 x 1.7 misses 0.25 mm. The FT1
  bed is applied through its lane at the tab X top edge **before** the W leads and the tap wires are fitted (PM4 order: 22 MB
  joints, inspection, FT1/FT2 beds, cure, then W1-W7 and the taps). The D3 fallback cut-out for FT1 is no larger than its
  keep-out (5.0 x 2.6 mm), so the MPPT-DISABLE trace stays covered.
- **B2 FT2**: A1 is restated for FT2 as "the largest lever (distance from the pin-11 row) subject to t >= 0.25 mm": far-edge
  spot (28.00, 73.25), 4 x 4 mm. Its +y lane is behind the L-FC body, so FT2 is bedded through a **1.0 mm fill hole** (NPTH)
  through tab Y and the foot at the foot centre, injected from the CR top with a blunt needle; the CR top keeps a 0.5 mm copper
  and part keep-out around the hole. The FT2 keep-out has no edge lane.
- **B3 T18**: F22 on the low row at (41.68, 35.80) (10.54 mm), clear of the mated W5 socket envelope beside J101. Every candidate
  ends at CO-5V pad 1, 0.172 mm from the REG-5V box: F101/R172 at that joint get a temperature-derating check in T-A-05.
- **B4 tab X dressing**: T1, T7b and T5 have straight lines that cross the LM1084 box; they are dressed toward +y in the
  inter-row gaps (D6 rule), never across neighbouring pads.
- **B5 corridor fallback (i)** needs 45.3 mm of chassis room past the MB -x edge (r7_calc: W1 J1 approach point at x -34.83 plus a
  10.5 mm 20 AWG bend allowance, ASSUMPTION) and must not take the volume of the J-BL/J-FC/J-NTC harnesses; MS2 measures both. The "EVM rotated"
  variant is not evaluated (open item). Fallbacks (ii) and (iii) fail.
- **B6 precision statements**: per-net copper areas are stated to +-0.3 mm2 (raster bias); the bottom area uses the r3 bottom set
  435.25 mm2.
