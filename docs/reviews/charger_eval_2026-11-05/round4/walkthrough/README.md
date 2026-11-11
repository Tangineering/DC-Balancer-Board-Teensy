# BQ25798EVM in place of the Ag105: round-4 design walkthrough (r8, 2026-11-10)

This walkthrough is a guided tour of revision r8 of
[`docs/charger_bq25798_wiring_design_2026-11-05.md`](../../../../charger_bq25798_wiring_design_2026-11-05.md) (the
**design**, about 3,900 lines). It covers the round-4 change, in which the carrier (CR) extends past the Ag105 footprint (r7),
and the fixes of the final independent audit, run 001 (r8). Section references such as "H.23(l)" point into the design, which
holds the full values, citations and calculations. The numbers in this walkthrough come from four sources:

- the design;
- the round-4 calculation outputs [`../calc/r7_calc_out.txt`](../calc/r7_calc_out.txt) and
  [`../calc/r7_calc_out.json`](../calc/r7_calc_out.json) (calc revision 7: revision 5 adds H.23(n)-(w), revision 6 adds
  H.23(x) and revision 7 adds H.23(y); every line of revision 4 is unchanged);
- the review records [`../review_loop.md`](../review_loop.md),
  [`../../../charger-design/run-001-2026-11-10.md`](../../../charger-design/run-001-2026-11-10.md) and
  [`../../../charger-design/ledger.md`](../../../charger-design/ledger.md) (review scores, finding counts, audit values);
- recomputations in [`make_figs_r7.py`](make_figs_r7.py) with the unchanged functions of `r7_calc.py`. Each recomputed curve
  is checked against the calc JSON before it is drawn. Values that the calc does not print are marked "recomputed here".

The figures in this folder are simplified redrawings; the full drawings are listed in section 9. The generator scripts and the
figure files keep their r7 file names; their content is r8.

Coordinates are Eagle board coordinates in mm, top view, +y up (design A.2). Heights are in mm above the MB top unless stated
otherwise.

## 1. Status

The design is at revision r8 and exists on paper only. Nothing has been ordered, desoldered or flashed (design status line).
The bench board keeps fw v37 rev 2 with `AG105_VBATN_ISOLATED 0`, so it does no regen charging.

The review history is as follows:

- Review round 7 produced 60 verified findings (10 major, 50 minor, no blocker) and 7 unverified nits; all are applied in r7
  (design 0.3, 0.4).
- A closing pass re-ran `r7_calc.py` as revision 4 and applied the operator statement D-H that the MB and its PCBs have no
  maximum height.
- The final independent audit (run 001) accepted 13 findings: 3 major and 10 minor, no blocker, no refutation. The walkthrough
  of r7 raised one more finding, CHG-R1-W01 (the vertical order of W5 and the trunk).
- Revision r8 applies all 14 findings and the seven adjacent items A-01 to A-07, followed by a verification round (design 0.3,
  rows r8-1 to r8-16; L.8). Section 7.2 lists the decision taken for each finding.

Three groups of work remain before anything is built:

1. **The operator survey T-A-08 (MS1-MS8).** The r7 outline is not frozen before the survey passes (design 0.2). MS2-MS5, MS7,
   MS8 and the MS6 board-edge reading gate PM0 (section 5.2).
2. **The open items of design J.2.** The operator rulings are the C102b exception (item 62) and the tab X tap assignment
   (item 63). The design items are the EVM plate and clamps (item 54), the off-CR lead support (A.3, item 66) and the
   braking-duty statistic for T-B-16 (item 64). The verifications are the foot bond on polyimide (item 55), the L-FC body height
   (item 56), the assumed inputs of the r8 calc rows (item 67) and the r8 residuals (item 68).
3. **The KiCad capture PM0**, the next build step. It captures the CR and the EIB on the r7 outline with the r8 additions, R106s
   and the B1R footprint, and is gated by T-A-06 (section 5.1).

Revision r7 moves no net, threshold or timing. Revision r8 adds one CR part (R106s) and restates five firmware requirements
(FR-07/FR-46, FR-12(b), FR-22/FR-48, FR-23 and FR-43). It changes no pin, direction or threshold of the IO CSV, so neither
`teensy_controller.ino` nor the IO CSV is edited by the design; the firmware round that implements G.2 implements the r8
statements (design D.5).

## 2. What round 4 changed and why

### 2.1 The extension rule

The round-3 design (r1-r6) confined the CR to the 31 x 33 mm Ag105 footprint. On 2026-11-10 the operator relaxed that
constraint: the CR still plugs into the 22 Ag105 holes, but it may extend sideways past the footprint (design 0.3, round 4 r7
table). The operator added one condition: a cantilever on 22 x 0.64 mm pins needs support at its far end
([`../work/r7_design_basis.md`](../work/r7_design_basis.md) D3).

The EVM stays the power stage, and the EIB stays a separate board. Every fail-safe argument of r1-r6 holds unchanged (design
0.2). The only EIB circuit change is the damping resistor R276 in series with E1 (section 4.6).

### 2.2 The six round-4 questions

Round 4 began with a design phase before any review. Four fact-finding notes and three candidate layouts were written. Two
independent assessors scored the candidates against six questions. Both chose the minimal proposal, which scored 41/50 and 36/50.
The long +x arm (tapside) scored 32 and 30, and the EVM on the CR (evm_on_cr) scored 22 and 22 ([`../review_loop.md`](../review_loop.md) 1.2). The decisions D1-D11 in
`r7_design_basis.md` answer the six questions, and design 0.2 states the result.

| Question | Answer in r7 | Where |
|---|---|---|
| Q1: side, extent and far-end support of the CR | Two tabs: **tab X** (x 48.70-65.00, y 56.30-68.30) toward the Teensy and **tab Y** (x 17.70-37.56, y 67.14-76.00) toward L-FC; 1394.06 mm² r7 outline; a bonded foot under each tab (FT1, FT2) | A.7, H.23(a), H.23(i) |
| Q2: EVM on or beside the CR | No. The 88.90 x 88.90 mm EVM fits neither on the CR nor beside it on the MB. It stands on the **EVM plate** past the MB +y edge | A.7, H.23(l) |
| Q3: EIB merged onto the CR | No. The EVM plate stands on the chassis and the CR sits on the MB, so they are not one rigid co-mount. A merge would export the unbuffered ILIM_HIZ node, REGN, /CE and STAT over 55.8-129.4 mm | B.6, H.23(u), J.2 item 60 |
| Q4: layer count | The CR stays 4-layer, 1.6 mm, double-sided: 73.55 % top and 69.04 % bottom use, against 101.8-109.9 % single-sided | H.23(e) |
| Q5: round-3 constraints | The footprint confinement, the r6 area budget, the named bottom keep-out and the MB power-copper shadow retire. The **bottom clearance rule** replaces the last two. The polyimide sheet stays | A.7, H.23(d) |
| Q6: EVM and MB modifications | Every EM and PM item stays necessary. EM5 and EM23 change text, and PM0, PM1, PM3, PM4, PM6 and PM7 gain r7 steps | C, D.1 |

The calculation H.23 changed four decisions of the design basis ([`../review_loop.md`](../review_loop.md) 1.3):

- No 4 x 4 mm foot in tab X meets the copper rule, so FT1 is 4.0 x 1.6 mm.
- FT2 sits at the tab Y far edge with a 1.0 mm fill hole, because L-FC blocks a syringe lane from +y.
- The T18 pad moves to the footprint low row at (41.68, 35.80).
- R175 and the six 0.1 % divider resistors move to the top side.

The calculation also found three errors in r6 itself. The MB vias are not tented (368 of 368 have a mask opening), the r6
polyimide sheet overlapped the CO-5V body by 1.48 mm², and the E1 load was misattributed (design 0.3, r7-12 to r7-14).

## 3. Power path and electronics

### 3.1 Recap

Figure 1 shows the power path of r8. It follows round-3 Fig 1. Items new or changed in r7 have a purple outline and an "r7"
badge; items new or changed in r8 have a magenta outline and an "r8" badge.

![Fig 1. Power path, r8](fig1_power_path_r7.svg)

The electrical path is the round-3 path. The charger input is the VCHG-IN node, fed from VBUS through D-BC-FC and from V-MOT
through D-BC-RG. On the CR, the TPS26630 eFuse U101 (current limit 2.05-2.41 A, OVP 22.6-23.6 V) protects the charger input,
and the W1/W2 pair carries it to EVM J1. The charger output returns on W3/W4 through D-BT-SQ to the pack. The permit logic,
the QUAL one-shot and the heartbeat monostable sit on the CR. The EIB drives the two EVM stop pins through the E leads E1-E8.

The r7 items are mechanical: the two tabs and their feet, the fixed W1/W2 length, the W3/W4 route maximum after MS2, the EVM
plate, R276 and the 20-pad tap field on tab X. The r8 items are R106s in the U101 FLT readback path (section 4.5), the W1/W2
wire specification (section 4.4) and the B1R riser wedge with the B3 post (section 4.3).

The round-3 walkthrough explains the electronics, and r7 and r8 leave them unchanged apart from R106s:

- the permit logic H1q / H2c and the comparator thresholds: [round-3 Fig 2](../../round3/walkthrough/fig2_permit_logic.svg) and its section 3;
- the /CE and ILIM_HIZ drivers on the EIB: [round-3 Fig 3](../../round3/walkthrough/fig3_evm_drivers.svg);
- the operating modes, concurrency and purge windows: [round-3 Fig 4](../../round3/walkthrough/fig4_modes.svg) and its section 4;
- the failure ranking A1-D4: [round-3 walkthrough](../../round3/walkthrough/README.md) section 5.

### 3.2 Firmware requirements restated in r8

Revision r8 changes firmware requirements only; the code is not edited (design D.5). The changes are as follows.

- **T3 raise, write first (CHG-R1-02; G.1 T3, FR-46, H.16).** The raise writes REG06:07 and then REG03-05 before any read-back.
  With a capped transaction already in flight, the writes complete 1.359 ms after the edge at 100 kHz (margin 0.141 ms) and
  0.565 ms at 400 kHz, against the 1.5 ms FR-07 deadline. The r6 order, with two reads between the writes, took 2.329 ms at
  100 kHz. The read-back follows as four field reads (REG01:02, REG03:04, REG05, REG06:07), each inside the FR-07 cap, and
  completes 3.208 ms (100 kHz) or 1.028 ms (400 kHz) after the edge. A mismatch takes the immediate P5-LOW path (H.23(o)).
  The 1.359 ms bound holds only with the FR-07 r8 queue-priority rule for a posted raise (H.23(y) row (2)). The pin-34 ISR
  latency is outside the budget, TODO(calibrate: T-C-06). No V-MOT peak is published for the read-back delay.
- **T1 Run entry, steps 8b and 8c (CHG-R1-04; F.5 T1, FR-04).** After the heartbeat exercise of step 8b, step 8c raises P5
  with QUAL already LOW, so CLR = P5N clears the QQ one-shot. Pin 33 must read LOW within 5 ms of the P5 rise, which proves
  the U111 CLR path at every Run entry. The end-of-T1 check requires P5 HIGH, /CE sense LOW, EN_CHG = 1 read back, QUAL LOW
  and pin 33 LOW. Steps 8b-8c add 128.5 ms to T1; the T1 budget of about 0.58-0.73 s is unchanged (H.23(y) row (7)). T-F-03
  adds a logic-analyser record of pins 5, 7, 10 and 33, a brake and a forced T9.
- **FR-43 flash and SD gates (CHG-R1-D01; G.3).** `flashWriteAllowed` admits a flash commit with FC_BUS LOW or in
  battery-supported Idle (BT_BUS HIGH and read back, BT_REG HIGH, V_bus >= `V_BUS_CHARGED_THRESH`, no hot-plug, selector
  disarmed, no cut). It never admits State 99, and it does not use `fcPurgeExposure()`, which is TRUE in Idle. `sdOpAllowed`
  admits the SD close and sync in Idle, in State 98 with the heartbeat stopped, and in State 99 phase 3.
- **FR-23 exceptions and FR-12(b) (CHG-R1-03, CHG-R1-01 A-01, CHG-R1-D02; G.2).** EX1 is the FR-12(b3) Idle probe: one address
  poll with every charger path LOW, then at most four transactions, ending with ADC_EN cleared and REG2E read back. EX2 is a
  bounded FLT-LOW diagnostic read: one REG1B read when FLT reads LOW and V_chg > 10.2 V for > 250 ms, which exceeds the 202 ms
  tCL_PLIM maximum (H.23(n)). FR-12(b1) is a proposed stuck-path criterion, V_chg < 12.0 V once both EN read-backs have been
  LOW for >= 0.5 s, TODO(verify: T-C-04); FR-12(b2) is a discharge wait with a 5 s timeout against a 3.695 s worst case
  (H.23(q), H.23(x)).
- **T-B-16 waveform (CHG-R1-08; I, J.2 item 64).** The thermal run uses 0.6 s at max(ICHG, 3.21 A) and 1.4 s at the 1.6 A
  FC-window ICHG, a 30 % duty. A 60 % run B is recorded separately. The waveform and the TDIE < 100 C criterion are
  qualification choices, not derived from a braking statistic.

## 4. Carrier mechanics

### 4.1 Outline and area booking

Figure 2 shows the MB region around the CR in plan. It shows the r7 outline over the dashed Ag105 footprint, the feet, the tap
field, the comparator band, the W-lead dressing path with its anchors, the r8 B1R wedge and the F17 pad beside which R106s sits.

![Fig 2. Plan view, r8](fig2_plan_view_r7.svg)

The r7 outline is the r6 rectangle (x 17.70-48.70, y 34.14-67.14) plus tab X and tab Y: 1394.06 mm² gross, bounding box
47.30 x 41.86 mm (H.23(a)). Tab Y was trimmed from the proposal's x 39.72 / y 76.51 to x 37.56 / y 76.00. The trim keeps
ROP1-FC 0.501 mm clear and puts the tab Y top edge 0.862 mm from the 12.9 mm Eaton L-FC body (H.23(b)). No MB part lies under
either tab. The 1.0 mm pin-11 chamfer moves to the tab Y corner (17.70, 76.00) and stays the only chamfered corner.

The figure also shows where the r7 content sits. The comparators U102-U104, U115 and U119-U121 move to the footprint low-y band
(x 23.15-42.43, y 35.05-41.63), the area freed by the r6 tap field. The band is 10.40 mm from the U101 commutation loop and
8.54-27.82 mm from the LM1084 box (H.23(f)). The six 0.1 % dividers sit in the divider strip directly above the band. Tab Y
top carries the LVC gates. Tab X carries the tap field and R175, and its part within 6.4 mm of the MB 5V copper rim is the
**thermal band** (boundary y 60.5-62.34, 84.9 mm²; H.23(h)). The thermal band holds only pads, wires, the RTV bead and
temperature-insensitive passives.

Plot P4 shows the top-side courtyard booking per region against the 75 % target of H.23(e2).

![P4. Area booking per region](plot_area_booking.png)

Every region passes. Tab Y top is the tightest region at 73.45 %, 1.5 points under the target; it passes only because U108 and
U109 moved to the footprint interior (with U108 kept on tab Y it books 78.00 %, H.23(e2)). The band books 69.5 %, tab X 52.5 %
and the tab Y bottom 29.4 %. In r8 the B1R wedge (11.40 mm²) replaces the 9.00 mm² B1 spot, so the interior books 184.9 of
288.8 mm² = 64.0 % (r7: 63.2 %; H.23(s)). Over each whole side the use is 73.55 % top (795.1 mm²) and 69.04 % bottom (392.9 of
569.1 mm²; H.23(e)). The R106s 0402 courtyard is not yet in the H.23(d)/(e) bottom booking of tab X, TODO(calc); the T-A-06 DRC
is the gate (J.2 item 68(b)). The farthest outline point lies 25.66 mm from the U101 loop, against the 36.5 mm that a 2-layer
build would need for the same coupling, so the 4-layer build stays (H.23(f)).

Two layers keep the CR underside off the MB copper. The 0.125 mm polyimide sheet stays, cut to the r7 outline + 1 mm and
trimmed to >= 0.5 mm from the CO-5V, J-NTC, L-FC, OP-FC and ROP1-FC bodies and pads (29 vertices, 1554.6 mm²; H.23(m)). The
bottom clearance rule keeps every CR bottom courtyard >= 1.0 mm in plan from every non-GND MB layer-1 feature and every MB part
box, measured on copper rims (H.23(d)).

### 4.2 Stack and feet

Figure 3 shows two side sections. Panel (a) runs along +y at x 36.00, through the controlling trunk point, the B3 post and the
W5 run; FT2, its fill hole and the 1x12 header body are projected onto the section plane. Panel (b) runs along +y at x 25.80,
through the B1R wedge (section 4.3). In each panel plan and height share one scale; only the sheet, bed and tape are drawn
thicker than scale.

![Fig 3. Side sections through tab Y and the B1R riser, r8](fig3_side_stack_r7.svg)

The header bodies (2.54 mm, PBT) seat on the 0.125 mm sheet, so the CR underside is at 2.665 mm and the CR top at 4.265 mm. The
post tips stand 0.940 mm proud of the CR top (H.23(j)). Each foot fills the same 2.54 mm gap: a 2.19 mm block (+0/-0.05 mm),
a 0.05 mm acrylic transfer tape to the CR, and a 0.30 mm alkoxy-cure RTV bed to the sheet. PM4 (2d) gates the dry bed gap at
0.15-0.45 mm with feelers before any MB joint is soldered (H.23(i)). FT1 is 4.0 x 1.6 mm at (61.72, 66.705); FT2 is 4.0 x 4.0
mm at (28.00, 73.250) with a 1.0 mm fill hole.

Panel (a) also shows the r8 stacking (H.23(t)). The B3 post holds the trunk bottom 14.965 mm above the MB (10.7 mm above the CR
top). The trunk is one RTV-bound round bundle of 4.885 mm, twice the r8 half-width of 2.443 mm (an ASSUMPTION as in H.23(l)).
W5 rests on the trunk top at 19.850-20.750 mm. The stack top is 20.750 mm above the MB at (32.80, 73.10), which is information
under D-H. The requirement at the controlling point (36.00, 71.10) is 14.433 mm, so the trunk has 0.532 mm of margin there.

Plot P5 shows the bed stiffness, the T-A-09 pull load of the feet and the r8 foot-bond fallback.

![P5. Foot bed stiffness and bed stress](plot_feet.png)

Panel (a) gives the bed stiffness k = EA/t for E_RTV 1-3 MPa, an assumed modulus (J.2 item 55). At the 0.30 mm nominal bed, FT1
gives 21-64 N/mm and FT2 53-160 N/mm. Across the gated 0.15-0.45 mm band and the calc range the figures are 14-128 N/mm (FT1)
and 36-320 N/mm (FT2; H.23(i)). Panel (b) compares the bed stress under the 0.4 N T-A-09 pull with the 30 g service stress at
the tab tip. The ratio is 0.87 for tab X and 0.97 for tab Y, so tab Y governs with a 0.413 N tip-load limit. On the
distributed-load basis the ratios are 1.93 and 1.92, so the 0.4 N pull lies inside the service range only on the tip-load basis
(design I, T-A-09).

The hatched band in panel (a) is the foot-bond fallback of r8 (CHG-R1-05, H.23(r)). If the RTV does not bond to polyimide, the
sheet is cut under the foot. An unchanged foot then stands t_rm lower, and its bed grows to 0.275-0.575 mm at t_rm 0.125 mm.
The minimum stiffness falls to 11.13 N/mm (FT1) and 27.83 N/mm (FT2), 0.783 of the gated minimum. The fallback therefore uses
a re-made foot of h_f' = 2.19 mm + t_rm (2.315 mm at t_rm 0.125 mm), which returns the bed to 0.30 mm, and the PM4 (2d) gate is
repeated. The decision falls before soldering: the T-A-09 step 0 bond coupon qualifies the bed on the sheet and on the mask
before PM4 (1). After the CR is soldered, the sheet under FT2 cannot be removed (1.612 mm to L-FC, 2.540 mm slot), so the only
repair is an RTV re-bed through the fill hole (H.23(r)). The PSA thickness of the sheet is TODO(verify) (J.2 item 67).

The feet reduce the pin loads by a modest amount. At 30 g the worst-pin load falls by 7-21 %. Under a 10 N push at the tab X tip
the worst pin carries 2.69 N without the foot and 0.52-1.99 N with it. All pin-load and first-mode figures are ORDER OF
MAGNITUDE estimates (H.23(i)); MS5 and T-F-18 decide.

### 4.3 W-lead dressing, the B1R riser and the 3-D switched-conductor rule

Every W lead leaves its CR joint and joins the **trunk**, which runs +y along x 25.80 (design A.3). The trunk crosses tab Y at
y 69.60-71.10 and leaves the CR at the tab Y +x edge (x 37.56). Off the CR it reaches y 71.75 at x 48.00 and then the MB tie
base A1 at (60.50, 73.50) (H.23(l) path). From A1 the west group (W1, W2, W6, W7) runs up x 58.00 to the MB +y edge. The east
group (W3, W4, W5) runs via the tie base A2 at (71.50, 88.00). No W lead crosses tab X. The dressing rule keeps every lead
>= 2 mm in plan from the pin-10 joint, the IN strip, the U101 courtyard, the +x pocket, every post tip and every tap pad; at the
r8 W1/W2 OD of 1.75 mm the worst lead is W1 at 2.017 mm (H.23(p)). W5 is the exception. Over the J101 region its ribbon edge
lies 0.775 mm in plan from C102b, and its route passes 1.79 mm from the tap-field courtyard (design A.3; H.23(l)).

No exit from the CR meets the 10 mm switched-conductor clearance in plan: the best raster path gives 5.12 mm for the bundle and
9.34 mm for one lead (J.2 item 62). The rule is therefore applied as a 3-D distance (decision of 2026-11-10, with D-H). Where
the plan distance d to a switched conductor of top height H is < 10 mm, the jacket bottom must be >= H + sqrt(10² - d²). The
L-FC body controls every lead, with H = 5.0 mm as an ASSUMPTION from the size code (TODO(verify: Eaton HCM1A1305V3 drawing),
MS3).

In r7 a level post at B1 and the r5 jacket bead could not both hold (CHG-R1-D03): W2 reaches B1 4.26 mm from its joint, so its
5.0 mm bead ends 0.74 mm past B1, where the jacket must stand 4.538 mm above the CR top (H.23(s)). In r8 the trunk climbs a
ramp from the CR copper instead. The **B1R** riser is a machined insulating wedge (G10/FR-4 or PEEK, an ASSUMPTION), taped to
the CR top, with the footprint x 23.55-26.05, y 62.54-67.10. Its ramp face rises at 65 degrees from the toe at y 62.54 to an
apex 9.78 mm above the CR top at y 67.10. The 65 degree slope is the shallowest computed slope at which W1 and W2 still join the
trunk on the copper: the ramp is 0.13 mm high at T1, below the 0.800 mm jacket radius. From the apex the trunk spans free for
10.4 mm through T2 to the B3 post, which holds it 10.7 mm above the CR top, and then runs level to the tab Y +x edge. The RTV
bead covers >= 5.0 mm of each jacket from its joint; for W1 (4.71 mm of copper run) and W2 (2.36 mm) it continues on the ramp
face (H.23(s)). The 2.50 mm face carries 51 % of the trunk width, so the trunk is bound into one round bundle and bonded to the
face from the toe to the apex (H.23(y) row (4)). The T-A-06 dry fit confirms that the leads can be dressed on the face (J.2
item 66).

W5 lies above the trunk over the whole plan overlap, from the trunk start (y 57.00) to A1 (CHG-R1-W01, H.23(t)). Below the
riser the trunk top lies under the 8 mm W5 fold; from (28.70, 64.01), where the trunk top passes the fold height, W5 rests on
the trunk and is bonded to it with RTV. Between the trunk start and that point W5 stands 0.198-3.115 mm above the trunk
(H.23(y) row (5)). W5 meets its own 3-D requirement everywhere with >= 1.866 mm of margin, the minimum at (28.70, 64.01); over
tab Y the margin to its 15.00 mm requirement is 4.850 mm.

Plot P2 shows the built trunk profile and the W5 ribbon against the requirement along the trunk, from T1 (25.80, 62.60) to A1.

![P2. Trunk and W5 heights along the trunk](plot_lead_height_profile.png)

The requirement, recomputed at the r8 half-width, starts at (25.80, 64.45), 0.050 mm before B1, and reaches its CR maximum of
14.433 mm (10.168 mm above the CR top) at (36.00, 71.10). The built trunk meets the requirement plus the 0.50 mm design margin
(an ASSUMPTION) at every 0.05 mm on the CR; the minimum margin is 0.504 mm at T2 (25.80, 69.60), where 9.497 mm is required and
10.001 mm is built above the CR top (H.23(s)). The W5 band is projected onto the nearest trunk point; its bottom is the
largest of the fold height, its own requirement and the trunk top (H.23(t)). The plot reproduces the calc check points, the
minimum margin and the 20.750 mm stack top.

Off the CR the support is TODO(design: T-A-06 dry fit). As information, the trunk held at 14.965 mm from the tab Y +x edge meets
the requirement plus 0.50 mm on a straight descent to A1 when the support reaches (40.75, 71.10), 3.1 mm past the CR edge
(H.23(s)). At the off-CR controlling points the requirement, the trunk bottom and the W5 bottom are 13.495, 14.399 and
19.285 mm at x 41.5, and 12.018, 12.527 and 17.412 mm at x 44.0 (H.23(t)). T-F-12 measures the jacket heights at the B1R check
points, T2, B3 and the off-CR controlling points. H.23(t) prints no r8 requirement at (37.75, 71.10) or at x 46.7; T-F-12 keeps
14.433 mm and the r7 value 8.61 mm there as TODO(verify) bounds (J.2 item 68(c)).

The anchor rule limits each unsupported span to 30 mm along the lead. The anchors are the B1R wedge, the B3 post (with S3 one
merged spot), the W5 spacer beads S1 (35.00, 47.69) and S2 (28.70, 53.42), and the MB tie bases A1 and A2. The longest span is
26.0 mm (S2-S3); the trunk span from the B1R apex to B3 is 10.4 mm. The chassis tie past the MB +y edge closes the last span:
<= 2.4 mm for the west group, <= 16.4 mm for W3/W4 and <= 17.4 mm for W5 (H.23(l), H.23(s)). A polyimide strip on the MB
(x 36.06-65.28, y 65.30-92.80) covers the crossed MB parts and 11 untented non-GND vias.

### 4.4 W1/W2 wire and fixed length

The r7 hard-short figures rested on a lead inductance of 0.5 µH/m that had no source (CHG-R1-D04). Revision r8 specifies the
W1/W2 wire and derives the inductance from its geometry (A.3, H.23(p)):

- conductor: 20 AWG stranded copper, 19/32 or 7/28;
- insulation: OD 1.60-1.75 mm as measured (PVC 300 V hook-up class, UL1007/UL1569; any insulation in that range);
- lay: twisted pair, pitch 20-25 mm, jackets touching;
- length: fixed at 0.30 m +- 10 mm at every placement (D-F3), with the slack as a service loop anchored on the EVM plate.

The inductance per unit length is L' = (µ0/π) acosh(s/2a), with s the jacket OD and a the conductor radius. The lower bound
uses OD 1.60 mm, the strand-bundle radius and the helix factor at a 20 mm pitch; the upper bound uses OD 1.75 mm, the solid
radius and 0.10 µH/m of internal inductance. The range is 0.399-0.661 µH/m.

Plot P1 shows the worst-case U101 IN peak at a hard short at EVM J1 against the W1/W2 lead length, for the r8 wire band, the
excluded thin-wall PTFE wire and the superseded r7 basis. The model is the unchanged H.19(b) `in_spike()` over the corner
grid V0 16/22 V, C_S 5/20 µF, L_IN 50/150 nH (`spike_worst()`).

![P1. Hard-short IN peak against W1/W2 length](plot_hard_short.png)

The lead inductance limits the short-circuit current rise, so a lower L' and a shorter lead raise the IN peak. At the lowest
L' the IN peak is 33.79 V at 290 mm, 33.64 V at 300 mm and 33.51 V at 310 mm, with a margin of >= 2.21 V to the 36 V D107
VBR(min) and a lead peak of up to 130 A; at the highest L' it is 31.80-31.99 V (H.23(p)). D103 must take a >= 130 A pulse for
<= 1 µs, TODO(verify: D103 datasheet) (B.4). The statement that no W1/W2 pair reaches 36 V holds only inside this modelled
envelope. Two wire classes are excluded. Thin-wall PTFE reaches 38.23 V at 290 mm. An OD above 1.787 mm, which includes the
600 V class, breaks the 2.0 mm plan dressing rule (H.23(p)).

The plot also shows why the fixed length stays. Recomputed here with the unchanged model, the lowest-L' curve reaches 36 V at
about 183 mm. A W1 cut to its 181.6 mm r7 rev-2 route would therefore reach 36.0 V, and a cut to the 199.5 mm revision-4 route
35.5 V. On the r7 basis of 0.5 µH/m the same routes gave 34.9 V and 34.4 V (H.23(l)).

The other leads take their route-rule maxima after MS2 (1.25 x the routed length, rounded up to 10 mm): W3 200, W4 200, W6 140,
W7 SCL 160 and W7 SDA 160 mm at the reference placement (H.23(l)). Until MS2, they keep the 0.30 m cap. W5 is the fixed 304.8
mm factory cable with a 222.7 mm minimum fit.

### 4.5 Taps and the FLT series resistor R106s

Tab X carries 20 SMT tap pads of 1.5 x 1.5 mm (F01-F07, F11-F21, F23, F24) on a 6 x 4 grid at 2.54 mm pitch, with R175 and two
spare positions. Four residual pads stay on the footprint low row y 35.80: F08 (T22), F09 (T8), F10 (T9) and F22 (T18) (design
A.4, H.23(g)). Plot P3 compares the r6 tap lengths (straight basis) with the r7 dressed lengths for the 20-tap set of the calc.

![P3. Tap lengths, r6 straight against r7 dressed](plot_tap_lengths.png)

The sum falls from 1308.0 mm (r6) to 859.3 mm straight and 898.7 mm dressed (-31.3 %). Against the r6 straight basis, only T1
and T8 grow in dressed length: T1 from 68.6 to 70.1 mm and T8 from 82.8 to 89.2 mm. On the straight basis T1 falls to 63.4 mm
and T8 is unchanged at 82.8 mm (H.23(g)). T8 takes an upper lane at y 37.55 over the residual row and then y 34.64 to x 63.50,
which makes it the longest r7 tap at 89.2 mm; a low-edge lane is infeasible by 0.59 mm. Each tab X wire runs from its pad into
the adjacent inter-row gap and toward +x to x 64.77; no wire crosses the REG-5V box (design PM6).

The assignment minimises the straight-length sum under six adjacency exclusions, and none is violated (H.23(g)). Three pairs
remain without an in-service detector (J.2 item 63):

- F05-F12 holds the REGEN EN net at 1.647 V, above the VEN_R maximum of 1.4 V, with 41.2 mA of contention;
- F07-F12 drives 82.5 mA into the pin-17 driver;
- F08-F09 can mask the BQ29200 pack-OV term (OVN).

A candidate with no violation of the extended exclusion set costs +1.2 mm on the sum; the F12/F24 swap also satisfies it
(-0.142 mm, H.23(w)). Until the operator rules, the T-F-12 tap-to-tap check before power-up is the only detector of the three.

The audit found a fourth hazard (CHG-R1-01). A bridge from F05 or F06 (the push-pull REGEN or FC_CHARGE EN outputs) to F17 drove
the U101 FLT output directly: 18.4-45.6 mA with a 40 ohm driver and up to 96.2 mA with a 0 ohm driver, against the 10 mA FLT
absolute maximum (tps2663.pdf SLVSE94G §6.1; H.23(n)). Revision r8 inserts **R106s**, 1.00 kOhm 1 % 0402, between U101 FLT and
the F17 pad. It sits on the tab X bottom beside F17 (fallback: the footprint interior near pin 14), both FLT nets are
solder-masked with tented vias, and F17 is the only exposed copper of the net (A.8, B.4, L.8). The effects are as follows
(H.23(n)):

- the bridge current is 2.657-3.377 mA, a factor of 2.96 below the absolute maximum, bounded with the resistor and 3V3
  tolerances and a 0 ohm driver; R106s dissipates <= 11.5 mW;
- the EN net stays >= 3.017 V, so the switch follows its command; the eFuse fault is masked while the bridged EN output is HIGH,
  because pin 35 then reads the EN level (J.2 item 68(a));
- without a bridge, the FLT LOW readback is 0.153 V typical and 0.325 V maximum against VIL 0.940 V (margin 0.615 V);
- an F17-F15 bridge with FLT asserted leaves pins 35 and 16 at 1.60-1.93 V, inside the undefined input band (H.23(y) row (1),
  J.2 item 68(f)).

T-F-12 before power-up stays the primary detector of every pad bridge. The new test T-C-05c injects the F05-F17, F06-F17 and
F17-F15 bridges on a powered CR and asserts FLT through UVLO (design I).

### 4.6 EVM plate, EIB and E1 damping

The EVM rests on its stock bumpons on an insulating EVM plate past the MB +y edge, held by edge clamps with silicone pads
(design A.7, C EM23). The EVM has no mounting holes; its corner circles are fiducials. The EIB stands on its two M3 nylon
standoffs on the same plate. At the reference placement the EVM spans x -0.40-88.50, 4.97 mm from the Teensy USB corridor, and
the EIB spans x 93.50-117.50 (H.23(l)). Corridor fallback (i) shifts both by -27.03 mm and needs 45.3 mm of chassis room past
the MB -x edge. MS2 decides between them; the plate, clamp and stop geometry is TODO(design: from MS2, MS5 and MS7) (J.2 item
54).

The E-lead maxima re-run on the vector EVM positions: E8 20, E3 25, E4 30, E2 35, E7 40, E1 90, E5 65 and E6 60 mm. E1 takes a
bent route below U1 and L2 of 70.8 mm against its 90 mm maximum (H.23(k)). With its E8 return and the 100 nF C205, the E1 lead
forms a series LC near the 1.5 MHz BQ25798 switching frequency.

Plot P6 shows the series-loop impedance for E1 at 85 mm and 90 mm, with and without R276.

![P6. E1/E8/C205 loop impedance](plot_e1_resonance.png)

Without R276 the loop resonates at 1.471 MHz (85 mm) and 1.430 MHz (90 mm), with Q 19.3 and 19.1. These Q values use the DC
resistance of 28 AWG and are upper bounds; with skin effect Q is about 13.0-13.1 (H.23(k)). With R276 (10.0 Ω, 1 %, 0603) Q is
0.108-0.111, so the loop is overdamped. The cost is a static drop of 1.02 mV held and 3.96 mV worst. The release level falls by
1.786 mV, which lowers IINDPM by 2.23 mA, the safe direction for the converter and the eFuse. T-C-16 measures the ring with
and without R276. In r8 its abort ratio uses the built E1 length: 17.80 at 85 mm and 9.20 at 90 mm (H.23(v)); at any other
built length it uses 25.6, the undamped Q, which bounds the sweep maximum of 25.47 at 81.7 mm (H.23(y) row (6)).

## 5. Build order and measurement gates

### 5.1 Build order

Figure 4 shows the build order from D.1 (PM0-PM6) and the gates of section I. Purple chips mark the operator measurements
MS1-MS8. A solid arrow points to the step that a measurement gates; a dashed arrow points to a later step that uses its result.

![Fig 4. Assembly order and gates, r8](fig4_assembly_order_r7.svg)

The order rests on one constraint: the W1-W4 tails on the CR underside can be trimmed only before the CR is seated (PM4 (2b)).
The steps are:

1. PM0: capture the CR on the r7 outline in KiCad, with R106s beside F17 and the B1R footprint; gate T-A-06 (pin identity, DRC
   with the bottom clearance rule, tab dry fit, B1R dressing).
2. PM1: remove the Ag105 after MS1a; then PM2 (C-D8/C-D10 swap) and PM3 (R170/R171).
3. T-A-09 step 0 (r8): qualify the bed RTV on a bond coupon, on the sheet and on the mask, before PM4 (1).
4. PM4 (1)-(2c): bond the sheet, solder the headers into the CR, fit and trim W1-W4, tape B1R to the CR top and lay W1/W2 on
   the ramp, tape the feet. If the coupon failed, cut the sheet under the feet and use re-made blocks h_f' = 2.19 mm + t_rm.
5. PM4 (2d): dry-seat the CR and gate the bed gap at 0.15-0.45 mm with feelers.
6. PM4 (3)-(5): solder the 22 MB joints with both tabs supported, cut the tails, bed and cure the feet; gate T-A-09.
7. PM4 (6): dress the leads: the B3 post at 10.7 mm, the trunk bound into one bundle on the B1R ramp, W5 on S1/S2 at the 8 mm
   fold and on the trunk from (28.70, 64.01) to A1, the off-CR support, and the chassis ties within their limits.
8. PM6: fit the taps; solder F20/F21 last because they lie over FT1, then repeat T-A-09 on FT1.
   PM7-PM11 follow on their own gates: PM10 and PM11 (which land T20 and T22) come after T-A-01b/c, and PM7 (T18) is done only
   if T-B-09 fails.
9. T-F-12 (tap isolation, lead heights over the full profile, W5 on the trunk), then first power-up and T-F-18.

A tab trim at any gate re-runs `r7_calc.py` (design I, T-A-08).

### 5.2 Operator measurements MS1-MS8

The r7 outline is not frozen before the survey T-A-08 passes (design 0.2). The table lists what each measurement decides and
what it gates (design I, T-A-08, and J.2 items 46-53).

| ID | Measurement | Decides | Gate |
|---|---|---|---|
| MS1a | Ag105 standoff at four corners; module top height | Seating reference (information since D-H) | None; taken before PM1 |
| MS1b | Module mass after removal | Information | None |
| MS2 | Chassis room past the MB +y and -x edges; under-MB clearance; USB plug and bend; W3/W4 channel width; chassis-tie positions | EVM plate position (reference or fallback (i)); W-lead route maxima; tail-cut target. Pass: under-MB clearance >= 1.5 mm, ties within 2.4 / 16.4 / 17.4 mm | PM0 |
| MS3 | Unrecorded MB items inside each tab + 0.5 mm, under each foot spot and along the W-lead path; L-FC body by caliper | Tab outlines; the B1R, B3 and W5 heights. Pass: L-FC >= 0.5 mm from the tab Y top edge and <= 5.0 mm tall | PM0 |
| MS4 | LM1084 thermal survey at 1, 5 and 10 mm from the 5V rim, with MS4a (CO-5V / T18 joint) and MS4b (band +x end) | Thermal-band split; R175 and F101/R172 derating; comparators at x > 39.53 (MS4b rise <= 14.9 C) | PM0 |
| MS5 | MB acceleration near the CHG footprint, 0.1-8 kHz | Whether the feet suffice. Pass: peak <= 30 g, the H.23(i) basis | PM0 |
| MS6 | MB thickness at the board edge and at the CHG holes; CR finished thickness; laminate modulus | Post arithmetic and first-mode estimates | Board edge: PM0; CHG holes: PM4 |
| MS7 | EVM as received: thickness, outline, mass, tail protrusion, connector and test-point heights | Clamp design and plate clearances | PM0 |
| MS8 | Fab stack-up, L4 tenting, inside-corner router radius, 2 oz minimum space | PM0 DFM check and DRC rules; the three concave tab-root corners | PM0 |

## 6. Cost

The bill of materials total stays at about USD 520-630 (design E). Revision r7 adds the CR on the larger outline, R276, the EVM
plate with its clamps, the two feet with transfer tape and bed RTV, and the W-lead anchors, spacers and strip; the four EVM M3
standoffs are deleted. Revision r8 adds R106s, the B1R wedge, the B3 post, the specified W1/W2 wire and the bond coupon, which
fall within the existing allowances (TODO(verify: workshop cost of the machined wedge)). Every EVM and MB modification of r6
stays.

## 7. Review history

### 7.1 Convergence

Plot P7 shows the verified findings per review round, stacked by severity where the record gives it.

![P7. Verified findings per review round](plot_review_convergence.png)

Rounds 1-6 (round 3, revisions r1-r6) produced 53, 44, 34, 32, 24 and 16 verified findings. Review round 7 rose to 60 (10
major, 50 minor), because round 4 added a large body of new mechanical and layout content: the carrier extension, the feet, the
tap field and the W-lead dressing. The final audit fell to 13 (3 major, 10 minor). Neither round 7 nor the audit found a blocker
([`../review_loop.md`](../review_loop.md) 4.1).

The design has not converged in the strict sense of a round with no major finding. The r8 changes were checked in a
verification round (design 0.3, row r8-16); no further independent review round of the r8 text is recorded. Two of the three audit majors (CHG-R1-01, CHG-R1-D01) sat in round-3 content that rounds 1-6 did not catch, and
CHG-R1-D03 sat in content that the round-7 closing pass added.

### 7.2 Audit findings, applied in r8

The final audit (run 001) used Codex as the reviewer, finding-verifier agents without the reviewer's severity, an independent
reviewer and a Codex counter-review. No severity remained in dispute after the counter-review. The agreed fix and its rejected
parts in the [run record](../../../charger-design/run-001-2026-11-10.md) were binding. Every finding below is applied in r8;
the decision column states the choice the design made where the agreed fix left one (design 0.3 r8 rows, L.8).

| ID | Severity | Finding | Decision applied in r8 |
|---|---|---|---|
| CHG-R1-01 | major | An F05-F17 or F06-F17 pad bridge drives U101 FLT against a Teensy output; EN is guaranteed off only at >= 67.5 mA through FLT (10 mA abs max) | R106s 1.00 kOhm 1 % 0402 between FLT and F17 on the tab X bottom; 2.657-3.377 mA with a 0 ohm driver; the A.8 rows state that the switch follows its command and the fault is masked while that EN is HIGH; T-C-05c (H.23(n)) |
| CHG-R1-01 (A-01) | (folded) | The FLT-LOW case had no reachable diagnostic | FR-23 exception EX2: one REG1B read after > 250 ms of FLT LOW with V_chg > 10.2 V; an ACK with VBUS_PRESENT_STAT 1 latches the carrier fault, an ACK with 0 runs the D-BT-SQ check |
| CHG-R1-02 | major | T3 with the FR-46 readbacks needs about 2.30 ms on the 100 kHz fallback, against the 1.5 ms FR-07 deadline | Writes first (1.359 ms at 100 kHz, 0.565 ms at 400 kHz), then four field reads, not one seven-byte read (0.930 ms exceeds the cap); no V-MOT peak published; FR-07 queue-priority rule (H.23(o), H.23(y)) |
| CHG-R1-D01 | major | The FR-43 flash/SD predicate needs FC_BUS LOW, which normal Idle never has, and contradicts itself on State 99 | Two gates: `flashWriteAllowed` (battery-supported Idle or FC_BUS LOW; never State 99; `fcPurgeExposure()` excluded) and `sdOpAllowed` (Idle, State 98, State 99 phase 3) |
| CHG-R1-D04 | minor | The W1/W2 0.5 µH/m is unsourced; thin-wall PTFE at 290 mm gives 34.68 V / 140.95 A | 20 AWG stranded, OD 1.60-1.75 mm, pitch 20-25 mm; L' 0.399-0.661 µH/m; 33.79 V at 290 mm; thin-wall PTFE and OD > 1.787 mm excluded; "no pair reaches 36 V" limited to the envelope (H.23(p)) |
| CHG-R1-03 (A-07) | minor | The FR-48 Idle probe conflicts with the FR-23 I2C gate (V_chg < 3 V against > 10.2 V) | FR-23 exception EX1 for the FR-12(b3) probe; ADC_EN always cleared by a write and REG2E read back; a fixed T_ADC_ONESHOT wait, TODO(calc), measured in T-D-15 |
| CHG-R1-04 (A-03) | minor | T1 step 8b leaves P5 LOW and states 70 ms against a >= 200 ms one-shot | Step 8c re-arms through CLR (P5 rises with QUAL LOW, pin 33 LOW within 5 ms); end-of-T1 check; T1 +128.5 ms; T-F-03 extended |
| CHG-R1-D03 | minor | The B1 post at >= 10.14 mm conflicts with the >= 5 mm jacket bead; the profile rises 1.215 -> 7.555 mm within 2.67 mm | B1R wedge at 65 degrees, B3 post 10.7 mm, 10.4 mm free span; minimum margin 0.504 mm; the trunk bound into one bundle on the 2.50 mm face (H.23(s), H.23(y)) |
| CHG-R1-W01 | (walkthrough) | The design stated no vertical order of W5 and the trunk where they overlap in plan | W5 above the trunk over the whole overlap, resting on it with RTV from (28.70, 64.01) to A1; no plan separation; stack top 20.750 mm (H.23(t)) |
| CHG-R1-05 (A-04) | minor | The foot-bond fallback grows the bed by the removed sheet stack; stiffness falls to 0.78 x the gated minimum | Re-made foot h_f' = 2.19 mm + t_rm; PM4 (2d) repeated; decided before soldering by the T-A-09 step 0 bond coupon; after soldering only an RTV re-bed through the FT2 fill hole (H.23(r)) |
| CHG-R1-D02 | minor | FR-12(b) "V_chg < 3 V within 2 s" against a 1.65-2.52 s decay below UVLO | (b1) 12 V once both EN read-backs have been LOW for >= 0.5 s, proposed, TODO(verify: T-C-04); (b2) a 5 s timeout with no pass/fail against 3.695 s worst case (H.23(q), H.23(x)) |
| CHG-R1-08 (A-05) | minor | T-B-16: 0.6 s bursts at 1 Hz is 60 % duty, not 30 % | 0.6 s at max(ICHG, 3.21 A) and 1.4 s at the 1.6 A FC-window ICHG; run B at 60 % information only; T-F-16 synchronised |
| CHG-R1-06 (A-06) | minor | Superseded markers leave old instructions live (A.3 line 501, line 1536, PM4) | Each marker holds only the old text and the live text is the current instruction; the r7 rev-2 W-lead tables stay in place, labelled history |
| CHG-R1-07 | minor | Hand calculations lie outside the calc outputs (all reproduce) | Calc revisions 5-7 (H.23(u)-(y)); the T-C-16 abort ratio re-based on the built E1 length |
| CHG-R1-A02 | minor | No TPS26630 (SLVSE94G) datasheet in `references/Datasheets` | The datasheet is local (`references/Datasheets/tps2663.pdf`) and cited in K |

None of the three majors was a hardware-destruction path on the r7 text. CHG-R1-01 and CHG-R1-02 failed toward a missed or late
inhibit that the ISR path covers, and CHG-R1-D01 refused flash and SD operations ([`../review_loop.md`](../review_loop.md) 4).
After CHG-R1-06, a "superseded" marker in the design holds only the old text, so the text outside the markers is the live
instruction everywhere.

## 8. How to review this design

The following decisions and checks are open. They are ordered so that the decisions which change the layout come first.

1. **Rule on the tab X tap assignment (J.2 item 63).** Choose between the adopted assignment, the extended-exclusion candidate
   (+1.2 mm) and the F12/F24 swap, and decide the measure for the F08-F09 pair (TODO(design)). Look at section 4.5, design A.8
   (short table) and H.23(g). A change re-runs H.23(g) and replaces the A.8 map, the PM6 dressing and the T-F-12 pair list.
2. **Rule on the C102b exception (J.2 item 62).** W5 lies 0.775 mm in plan from C102b over the J101 region, at >= 8 mm above
   the CR top, that is >= 5.5 mm above the about 2.5 mm C102b body (H.23(w)). The W5 route also passes 1.79 mm from the tap-field
   courtyard (H.23(l)). The 10 mm switched-conductor figure itself still has no stated pickup basis.
3. **Design the off-CR lead support** (TODO(design: T-A-06 dry fit)). It holds the trunk, with W5 on it, from the tab Y +x edge;
   it must reach at least (40.75, 71.10) for a straight descent to A1 (H.23(s)), clear of the OP-FC box (x 40.22-45.12,
   y 67.30-75.28). Plot P2 gives the heights.
4. **Check the r8 choices in design L.8.** The B1R slope and lateral support (J.2 items 66 and 68(g)), the W5-on-trunk stack, the
   R106s value and placement, the four-field-read schedule and the CLR re-arm are design choices that only the r8 verification
   round has checked.
5. **Measure the L-FC body height (MS3).** The 5.0 mm value is an ASSUMPTION that sets the B1R, B3 and W5 heights. A taller body
   re-runs H.23(l), H.23(s) and H.23(t) (design I, T-A-08; J.2 item 56).
6. **Close the r8 verifications (J.2 items 64-68).** These are the sheet PSA thickness, the eFuse IN-side current in the
   latched state (FR-12(b1), T-C-04), the Teensy 3V3 tolerance and pin-35 pull-up range, the T_ADC_ONESHOT duration, the
   R106s bottom booking and the pin-34 ISR latency.
7. **Confirm the remaining operator options.** These are the FT1 relaxed 4 x 4 mm option (J.2 item 58, not recommended by the
   calc), the EVM placement after MS2 (J.2 item 57), and the T-F-18 transmissibility criterion (<= 3, proposed).

## 9. Where to find the detail

### 9.1 Full drawings

| Drawing | Content |
|---|---|
| [`../carrier_layout_r7.svg`](../carrier_layout_r7.svg) | Top view of the CR on the r7 outline over the MB (r8: the B1R wedge in place of the B1 bead), with the EVM reference placement as a second panel |
| [`../wiring_bq25798.svg`](../wiring_bq25798.svg) | Wiring diagram: MB, CR, EIB, EVM, every lead and tap (r8: R106s, the W1/W2 wire specification) |
| [`../carrier_schematic.svg`](../carrier_schematic.svg) | CR and EIB schematic with R276 (r8: R106s in the U101 FLT path) |
| [`../work/svg_png/`](../work/svg_png/) | PNG renders of the three drawings |

### 9.2 Design sections

| Topic | Design section |
|---|---|
| Rulings, verdict, change tables r1-r8 and the review loop | [0.1-0.4](../../../../charger_bq25798_wiring_design_2026-11-05.md) |
| Leads, W1/W2 wire, dressing path, B1R, W5 stacking, anchors, 3-D rule | A.3 |
| Taps and tap field, R106s placement | A.4, A.8 |
| E leads and EIB wiring | A.5, A.9, B.6 |
| Outline, feet, foot-bond fallback, sheet, bottom clearance rule, EVM plate | A.7 |
| Carrier layout regions and booking | A.8 |
| Permit logic, comparators, eFuse, R106s | B.1-B.4 |
| EVM and MB modifications, build procedure PM0-PM11 | C, D.1 |
| Proposals for the protected files | D.5 |
| Bill of materials | E |
| Modes, purge scheduler, transitions (T1 steps 8b-8c, T3) | F |
| Registers and firmware requirements (FR-07, FR-12, FR-23, FR-43, FR-46) | G |
| Round-4 calculation | H.23 (r8: H.23(n)-(y)), [`../calc/r7_calc.py`](../calc/r7_calc.py), [`../calc/r7_calc_out.txt`](../calc/r7_calc_out.txt) |
| Test registry, including T-A-08, T-A-09, T-C-05c, T-C-16, T-F-03, T-F-12, T-F-18 | I |
| Open items 46-68 | J.2 |
| Review dispositions of round 7 and the audit | L.7, L.8, [`../review_loop.md`](../review_loop.md), [`../work/r7_review7_dispositions.md`](../work/r7_review7_dispositions.md) |
| r8 patch sets and the pre-r8 text | [`../work/r8_patches/`](../work/r8_patches/) |
| Round-4 decisions D1-D11 | [`../work/r7_design_basis.md`](../work/r7_design_basis.md) |

### 9.3 Figure sources

The plots P1-P7 are generated by [`make_figs_r7.py`](make_figs_r7.py), which reads `r7_calc_out.json` (calc revision 7) and
calls the functions of `r7_calc.py` without rewriting any calc output. Each recomputed value is checked against the JSON before
the plot is written; the script stops on a mismatch. The diagrams Fig 1-Fig 4 are generated by
[`make_diagrams_r7.py`](make_diagrams_r7.py) from `r7_calc_out.json` and `mb_neighbours_out.json`. The P7 counts come from the
review records, because no calculation holds them. Each plot is also available as an SVG beside its PNG.
