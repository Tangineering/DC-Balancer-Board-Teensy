# CR outline and assembly change: design re-assessment (2026-11-12)

## 1. Scope and status

This document re-assesses the CR design against the operator-approved change request
`docs/reviews/cr_routing_2026-11-12/CR_OUTLINE_CHANGE_REQUEST_2026-11-12.md` (main checkout). The change request
sets three new bases:

- **Mounting.** The CR plugs onto male headers in the 22 MB CHG holes and rests on four standoffs. It is removable.
- **Outline.** The rectangle x 18.584-67, y 7-94 in the MB frame (48.416 x 87 mm, 4212 mm²).
- **Assembly.** Stencil, paste and reflow oven. One SMT side if possible; 0402 minimum and 0603 preferred; IC pitch
  0.65 mm preferred minimum, 0.5 mm only with operator approval; through-hole parts hand-soldered last.

The outline is provisional until the operator closes section 6 of the change request (MB survey, standoff part,
connector choice). No generator file or board file has changed. The analyses behind each section are in
`outline_change_2026-11-12/`. An independent check of each analysis is in
`outline_change_2026-11-12/independent_checks.json`; this document uses the corrected figures.

D-37 governs vias on the new outline: route first with no via on an SMD pad or in its mask opening, and use plain
unfilled vias in pads (D-36) only after that attempt fails.

## 2. Summary

The new outline removes the routing shortfall of the r7 board on paper. The current parts, at their current
packages, book 24 % of one side of the new outline (r7: 73.55 % top, 69.04 % bottom). After the package upsizing of
section 7 they book about 27 %, before the lead connectors of section 6. All SMT parts therefore fit on the top side.
The estimated routing utilisation falls from 38 % on r7 to 9.7 % with three signal layers, or 12.9 % with L4 kept as
a solid GND layer. These are geometric estimates; r7 failed on local cuts that a global ratio did not predict, so a
routed run on a regenerated placement remains the gate.

The re-assessment finds four design problems that the change request does not state:

1. **Keying.** A removable CR can be fitted rotated by 180 degrees. Rotation exchanges the two pin columns, which
   swaps VIN+ and VBAT+. A physical key is necessary (section 4.3).
2. **Support polygon.** The two -x corners of the CHG footprint lie 1.45 mm outside the new -x edge, so standoffs
   cannot sit at all four corners. With the candidate sites, the whole x 20.998 pin column lies outside the support
   polygon, and a push on that column loads the pins (section 5).
3. **U101 package.** The TPS26630 exists only in VQFN-24 at 0.5 mm pitch. Either the operator approves 0.5 mm for
   U101, or U101 changes to the TPS26631 in HTSSOP-20 at 0.65 mm (section 7.1).
4. **Switching nodes and heat under the CR.** Both boost switching nodes, both inductors and the LM1084 now lie
   under the CR. The MB-facing layer and the placement of sensitive parts must respond (section 3).

## 3. MB parts under the outline

### 3.1 Parts and heights

The outline covers 67 MB parts, all on the MB top side: 59 fully and 8 partly, plus the CHG footprint. Table 1 gives
the tallest classes.

Table 1. Tallest MB parts under the outline.

| Height (mm) | Parts | Source |
|---|---|---|
| 5.0 | L-FC, L-BT (HCM1A1305V3-2R2-R) | Eaton family data; TODO(verify: Eaton ELX1488, caliper). The sibling HCM1A1307V3 is 6.5 mm. |
| 4.83 | REG-5V (LM1084ISX-5.0, TO-263) | LM1084 datasheet p.30 |
| 2.10 | CO-5V (tantalum 3528) | IPC package name |
| 1.75 | OP-FC, OP-BT (SOIC-8) | `mb_mechanical.md` |

The parts that cross an edge are C1-BT, C1-FC, CBL2, RB2 and RB3 (-x edge, silkscreen extents), MDAC-BT and OP-BT
(-y edge) and C-DC3 (+x edge). C-D4 (x 67.03) and D-FC-EN (x 67.08) lie within 0.1 mm of the +x edge. The change
request section 3.2 lists D-FC-EN, C-DC1 and C-DC2 as covered; C-DC1 and C-DC2 are clear by more than 3 mm. The
section 3.2 list of examples omits C2/C3/C5/C6-BT, CC-BT, RINJ-BT, C-D11, C-D12, C-DC11, C-DC12, MDAC-BT and OP-BT.

The bodge parts under the outline have no recorded height: the two 10 kΩ EN-to-GND resistors at D-BT-SQ and
D-BT-EN, any OPA197 5 V wire, and the planned tap joints T9 and T18. D-38 (2026-11-12) removes tap T22 and its
joint at BQ29200 pin 8.

### 3.2 Switching nodes and heat

REG-5V is an LM1084 linear regulator, so it has no switching node. The two switching nodes under the CR are VSW-FC
(pour x 35.64-43.36, y 81.61-87.55) and VSW-BT (pour x 32.84-44.63, y 16.33-23.04), at 500 kHz. Table 2 gives the
heat sources.

Table 2. Heat sources under the CR.

| Source | Dissipation | Basis |
|---|---|---|
| REG-5V (LM1084) | 0.40 / 0.63 / 1.08 W | `docs/reviews/charger_eval_2026-11-05/round4/work/mb_mechanical.md` lines 225-272 |
| FC boost (REG-FC, L-FC) | 1.17-2.20 W at 14.6 W input, η 0.92-0.85 | P_in(1 − η); η 0.85 is a model value, TODO(verify: TPS61288 Fig 7-3) |
| BT boost (REG-BT, L-BT) | Not derived | TODO(calc: BT channel operating point) |

### 3.3 Consequences

- **Minimum CR underside height.** With no bottom SMT, the CR underside must stand at least 5.0 + 1.5 = 6.5 mm above
  the MB (tallest part plus a 1.5 mm air gap). The connector stack of section 4 gives 12.0 mm.
- **MB-facing layer.** L4 becomes solid GND with no signals inside the shadow zones (the footprints of L-FC, L-BT,
  the two VSW pours, REG-FC, REG-BT and REG-5V with its 5V pour, each grown by 3 mm), stitched to L2 at a pitch of at
  most 5 mm. The routing estimate of section 8 allows L4 to be solid GND over the whole board.
- **Sensitive parts.** The 0.1 % dividers, the comparator inputs and the references belong in the window y 30.8 to
  66.86, which keeps 10 mm from both inductors and contains the J1 span. The free area for sensitive parts, at least
  10 mm from the 5V rim and 5 mm from the boosts, is 1783.6 mm².
- **Strip x 17.70-18.584.** On the r7 board, U114, U116, R108, R131B and R176 have pads at x 18.375 in this strip. All
  five are re-placed on the new outline.

## 4. Mating connector

### 4.1 Selection

The CHG pattern is two single-row columns 25.0 mm apart: x 45.998 (pins 1-10, y 39.084-61.944) and x 20.998
(pins 11-22, y 36.544-64.484), with 1.1 mm drilled holes. The proposal is:

- **MB:** Samtec TSW-1xx-07 male strips (post A 10.92 mm, body 2.54 mm), seated in the CHG holes.
- **CR:** Samtec SSQ-1xx-01 through-hole socket strips (insulator 8.51 mm), or SSQ-1xx-21 (low insertion force).
- **Rating:** TSW mated with SSQ is 6.3 A per pin with two positions powered (Samtec F-226). The requirements are
  3 A at pin 10 and 2.0 A at pins 14/15/18/19. The derating for four powered pins in pins 14-19 is
  TODO(verify: Samtec derating curve).
- **Height:** CR underside 12.0 mm above the MB (usable window 11.05-13.21 mm, insertion 4.89 mm), which leaves 7.0 mm
  over L-FC and L-BT. A TSW-1xx-14 variant gives 14.0 mm (window 12.83-15.50 mm).
- **Plating:** the current TSW sheet lists F, GF, L and T only; the ordering BOM plating -G must change, for
  example to -L.

`calc/pin_identity_check.py` (the capture mirror gate of D-02) still applies to the receptacle footprint.

### 4.2 Assembly sequence

The TSW strips are seated flat on the MB first (tail protrusion 0.94 mm). The CR is then plugged onto them and set on
the standoffs, and the TSW tails are soldered from the MB underside. Plugging the strips into the CR first lifts the
TSW bodies 0.95 mm and leaves no tail protrusion. The MB underside must be clear at both CHG columns,
TODO(measure: operator).

### 4.3 Keying

The D-02 outline chamfer was a check against a mirrored capture, not a physical key. A blank (no-hole) position on
the CR does not key either: the surplus MB posts stop 3.62 mm below the CR, so a CR rotated by 180 degrees mates
fully. One of these keys is necessary:

- the SSQ polarized-position option, with one MB TSW pin omitted at an NC position whose rotated image is a fitted pin
  (for example socket 5 plugged and MB pin 5 omitted; under rotation socket 5 lands on pin 16, VLOAD-1); or
- an asymmetric standoff pattern that admits the CR in one orientation only.

## 5. Standoffs

The standoffs carry the CR mass and the cable loads; the pins carry only current. The proposed CR hole is a 2.7 mm
NPTH for M2.5 nylon hardware, with no plating and a 3.4 mm copper keep-out radius on all layers, which keeps the A.6
single-point GND bond. The stack equation is S = h_header body + h_receptacle ≥ h_MB,max + h_CR,bottom + 1.0 mm, and
the standoff length is S minus the base and seat thicknesses, matched within 0.1 mm.

The site search is not complete. The candidate sites near the CHG corners (MB frame) are SO1 (26.0, 35.6),
SO2 (56.4, 34.4), SO3 (22.0, 69.2) and SO4 (49.3, 66.7). The independent check found three defects in the search:

- The search ignored the new MB header bodies; with them, SO3 has a free radius of about 3.45 mm, not 6.07 mm.
- It took the first point that passed a threshold, not the local maximum. Free discs of 8-12 mm exist near the NE
  corner and between the two pin columns, so an adhesive-base support may fit there.
- The whole x 20.998 column lies 1.0-4.9 mm outside the SO1-SO4 support polygon.

The search must therefore run again with the header bodies included and with sites inside the old CHG footprint,
which also brings the x 20.998 column inside the support polygon. The MB has no hole near the footprint, so the
attachment (bonded base or a new drilled hole) is an operator item.

## 6. Lead removability

### 6.1 Leads

The 20 tap conductors split as follows: 14 end in Dubox pins on the MB headers, 4 are soldered on the MB (T1, T2, T9,
T20), and 2 are shields with no far end (T7b, T17r). D-38 (2026-11-12) removes tap T22 (BQ29200 pin 8) and its pad
F08, and pack-voltage protection moves to firmware. Tap currents are at most 1.82 mA in service and 48.5 mA in
the T6 fault. W1/W2 carry up to 2.41 A for up to 202 ms (normally 1.76 A) and W3/W4 up to 3.21 A. W5 is an IDC cable
and is already removable.

### 6.2 Proposal

Every lead unplugs at a connector on the CR (option A):

- J-TAP: a 2 x 12 Molex Micro-Fit 3.0 header, or two JST PH 1 x 12 headers, for the taps;
- J-W12: Phoenix MC 1,5 at 3.81 mm for W1/W2;
- J-W34: Phoenix MSTB at 5.08 mm for W3/W4;
- J-W67: a 2 x 3 header for W6/W7.

These connectors need about 660-960 mm² (16-23 % of the outline). The fixed W1/W2 build length of 0.30 m ± 10 mm
(D-F3) is a spike-safety limit; it is measured to the plug, and the plug adds to the W1/W2 loop inductance and
resistance in H.5 and H.19. T9 leaves the MB under the CR. The cavity map can close the open short-table hazards
F05-F12 and F07-F12 with the J.2 item 63 exclusion set. The F08-F09 hazard no longer exists, because D-38 removes
pad F08.

The alternative (option B) keeps the leads soldered to the CR and unplugs them at their far ends, with one
connector for the 4 MB-soldered taps.

## 7. Assembly conformance

### 7.1 U101

No leaded TPS26630 exists. The options are:

- **A.** Approve 0.5 mm pitch for U101 (TPS26630RGER, VQFN-24).
- **B.** Change to the TPS26631PWPR (HTSSOP-20, 0.65 mm, MSL 2). With PGTH at GND (B.4) the TPS26631 never enters its
  2x pulse mode and acts as a 1x limiter. Its fast-trip is 3 x I_OL (6.15-7.23 A) instead of 2 x I_OL, so H.5 and the
  B.8 pin map must be re-derived.

The TPS26600 is a circuit-breaker part with a different fault response and is not a drop-in fallback.

The U101 exposed pad carries nine 0.30 mm thermal vias (D-03). Under D-37 they must first be designed out of the pad
(or moved beside it), and they become D-36 vias only after a failed no-via attempt. Whether D-37 is meant to cover an
exposed thermal pad is an operator question.

### 7.2 Other parts

- The six 0402 parts move to 0603; the +x pocket constraint (D-32) that required 0402 no longer binds once the
  pocket is re-placed.
- The TLV3012B comparators are already SOT-23-6 (DBV). The SC70 logic (SN74LVC1G08/1G11/1G14) moves to SOT-23 (DBV)
  where the pinout matches, TODO(verify: DBV pinouts).
- SN74LVC2G08 and SN74LVC1G123 have no package coarser than DCT (0.65 mm); they stay in DCT.
- U105 (SN74LVC3G04DCTR) can become SN74LVC1G04DBVR parts, which is a netlist change.
- All 78 bottom passives move to the top. The top-side booking is then about 1116 mm² of 4104.5 mm² usable (27 %),
  before the connectors of section 6.

## 8. Routing estimate

A scratch top-only repack of the current parts on the new outline placed 153 of 153 parts, with a signal minimum
spanning tree of 1253-1549 mm against 1639 mm today. Table 3 compares the geometric routing utilisation.

Table 3. Routing utilisation (estimate, not routed).

| Board | Signal layers | Utilisation |
|---|---|---|
| r7 (did not close) | 3 | 38 % |
| New outline | 3 | 9.7 % |
| New outline, L4 solid GND | 2 | 12.9 % |

The repack used placeholder standoff discs at the r7 corners, and it did not include the section 6 connectors. A
routed run on a regenerated placement is the gate. That run needs a new region table in `gen/layout_cr.py`, side
flags in the netlist and new power geometry in `gen/route_cr.py`. The generator constructs that encode r7 geometry
include GRID_BOUNDS (17.0, 33.5, 66.0, 77.0), RIM_X 39.53, LFC_Y 66.862, the MB bottom-clearance model, the tab
regions and the PARK position (70, 50), which lies outside the new outline.

## 9. Effect on the decision record

Table 4 classifies the LAYOUT_DECISIONS entries. The reasons for each row are in
`outline_change_2026-11-12/retired.md`.

Table 4. Decisions under the new mounting and outline.

| Class | Decisions |
|---|---|
| Retire | D-16 (tab Y top), D-17 (bottom clearance rule), D-19 (feet), the D-36 start board, the r7 part of D-32 |
| Re-derive | D-02 (key), D-03 (receptacle, courtyards), D-08, D-09, D-11, D-12, D-12a, D-13, D-14, D-18, D-20 (L4 solid GND), D-22, D-30, D-34, D-35 (exemptions after re-placement) |
| Keep | D-01 (new KiCad Y 6.00-93.00), D-04 to D-06, D-10, D-15, D-21, D-23, D-24, D-25 to D-28 (EIB), D-29, D-31, D-33, D-37 |

The following work of 2026-11-12 is superseded by the new outline: the interactive start board in `cr/interactive/`,
the r7 routing study results, and the routability options P3 (0402), P5 (0.5 mm DCU), P6, P8 and P9 of
`ROUTABILITY_OPTIONS_2026-11-12.md`. P1 (an OSH Park-only rule file) and P2 (unused inner pads on through-hole
leads) still apply.

## 10. Operator decisions

The regeneration of the CR on the new outline needs these decisions:

1. U101: approve 0.5 mm (TPS26630RGER) or change to the TPS26631PWPR (section 7.1).
2. Whether D-37 applies to the U101 exposed-pad thermal vias (section 7.1).
3. All SMT on the top side (section 7.2).
4. The connector stack: 12.0 mm (TSW-07) or 14.0 mm (TSW-14), and standard or low-insertion-force SSQ (section 4.1).
5. The key: SSQ polarized position with one omitted MB pin, or asymmetric standoffs (section 4.3).
6. The standoff attachment (bonded or drilled), and whether the CR is screw-clamped or rests on the standoffs
   (section 5).
7. Lead option A or B, the tap connector family, and the crimp tools available (section 6).
8. L4 as solid GND facing the MB, with a 1.5 mm minimum air gap (section 3.3).
9. Whether an insulating film replaces the polyimide sheet over the untented MB vias.
10. Whether to re-admit any DNP tier of D-31, and whether to restore silkscreen designators (D-12a) for stencil
    assembly.

The section 6 survey of the change request remains open: the L-FC and L-BT heights, the bodge parts and their
heights, the J-BT and J-BL face positions, whether the C1-BT, C1-FC, CBL2, RB2 and RB3 bodies clear x 18.584, and the
MB underside at the CHG columns.
