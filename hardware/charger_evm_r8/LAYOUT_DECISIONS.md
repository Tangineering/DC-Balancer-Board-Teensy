# BQ25798EVM charger path, design r8: KiCad capture and layout decision log

## 1. Scope and status

This log records the placement and routing decisions of the KiCad 9 capture of the r8 charger design
(`docs/charger_bq25798_wiring_design_2026-11-05.md`, commit `dc80dc5`). Each decision cites the design row that it
satisfies (an A.7, A.8, A.9, B.8 or H.23 row) or names the deviation and the reason for it. Section 10 lists the
proposed design changes, and section 11 lists every open `TODO(verify)` item. This work does not edit the r8 design
document.

The capture covers two boards: the carrier **CR** (4 layers) and the EVM interface board **EIB** (2 layers). The
design names no other printed circuit board. The bond coupon of the E BOM is a solder-masked FR-4 offcut from the
workshop. The FT1/FT2 feet and the B1R wedge are machined parts, and the EVM plate is a mechanical plate. None of
these is a KiCad project.

Status on 2026-11-15 (phase C of the 2026-11-14 round):

| Board | Schematic | Placement | Routing | ERC | DRC | Fab package |
|---|---|---|---|---|---|---|
| EIB | complete; part fields synchronized with the ordered BOM (D-82); Note field added on J201 (D-88) | complete | complete; tracks, vias, pads and zone outlines unchanged since D-68, pour fill changed at J201 by D-70; D-70 to D-78 as below; F.Silkscreen E-pad numbers, resized or shifted B.Silkscreen E labels and the "E1 JP12.1" label (D-86) | 0 | 0 violations, 0 unconnected items, 0 parity issues (`eib/drc.rpt`, 2026-11-15T05:36:57) | `fab/eib_2026-11-14/`, written again in place on 2026-11-15 (D-90); not ordered |
| CR | complete; part fields synchronized with the ordered BOM (D-82); J1 and J102 Notes corrected and six Note fields added (D-88) | complete | complete; tracks, vias, pads and zone outlines unchanged since D-69, F.Cu pour fill changed at J1 pin 18 by D-75; D-72 to D-78 as below; "VIN1" and "GND" labels at W1/W2 and the W1 reference moved (D-85) | 0 | 0 violations, 0 unconnected items, 0 parity issues (`cr/drc.rpt`, 2026-11-15T05:29:19) | `fab/cr_2026-11-14/`, written again in place on 2026-11-15 (D-90); not ordered |

Phase C answers the second holistic review of the r9-25 records (findings R2-*; per-finding status in
`update_2026-11-14/notes_phaseC_*.md`). D-85 to D-92 record it. The board edits are silkscreen texts only (D-85,
D-86). `gen/pcbdiff.py` against git HEAD `014c745` gives CR 692 / 692 segments and 420 / 420 vias and EIB 332 / 332
segments and 93 / 93 vias, with 0 added or removed on either board; zones differ in fill only (D-70, D-75). The CR
constraint check (`cr/constraint_check.md`) has 129 rows: 107 pass, 1 pass with the exceptions listed in the rows
above it, 3 exemption rows, 18 information rows and 0 FAIL; the D-20 stitching row still reads 3.49 mm at (31.0,
34.8) against 3.54 mm. The EIB constraint check has 6 pass rows and 2 information rows (D-87). Design revision r9-26
and companion revision r4 carry the matching document changes.

The round leaves these items for the operator. Items 1 to 5 and 11 to 13 change no copper; items 9 and 10 name a
copper change as one option:

1. Closed 2026-11-15 (D-93): J.2 item 74, the U101 OVP band against the VESC regen limit. The operator accepted the
   charger dropout on hard brakes; the divider, R101 and the Mouser file are unchanged (section 11 item 35).
   (**Superseded 2026-11-15:** "Accept a charger dropout on hard brakes, set the VESC regen limit below the OVP rising
   minimum, or retune the OVP divider. Lever (a) is R103 68.1 kOhm and R104 47.5 kOhm 0.1 % with R102 845 kOhm: OVP
   rising 23.256-26.863 V, OVP falling 21.439-24.614 V and UVLO rising 9.092-10.571 V at the sim 5 leakage corners
   (`sim/chopper/RESULTS.md` section 5.8; D-91). A retune changes R103, R104 and possibly R101 in
   `bom_2026-11-14/mouser_import.csv`, so the ruling precedes the Mouser order (section 11 item 35).")
2. FR-50 and FR-51 (firmware round): the `OV_CHG` threshold, response and filter, on the as-fitted OVP bands (D-93) (**Superseded
   2026-11-15, D-93:** "ruled with item 1"); and the recovery
   of a latched U101 in Run (section 11 item 36).
3. J.2 item 77: the T2 interruption option, from the sim 4 section 5.6a option table (section 11 items 32 and 37;
   D-81, D-91).
4. J.2 item 78: the H1 fall worst case 17.843 V against the VINDPM_STAGE1 minimum 17.84 V (section 11 item 38).
5. FW-0: the `CLAUDE.md` section 1-3 conflicts, a precondition of the firmware round (section 11 item 39).
6. D103: keep the ordered STPS2H100A or fit the MBRA2H100T3G alternate (D-79; section 11 item 30).
7. C108 = 470 pF at assembly (D-81; part of item 3).
8. Closed 2026-11-16 (D-95): the phase B EIB reference rule set stays (18 of 26 fitted references on top), and the
   CR W6 "GND" label stays as placed; neither board is exported again. The W3/J1 inspection half of section 11 item 29
   stays open. (**Superseded 2026-11-16, D-95:** "The EIB reference rule set (D-78) and the W6 "GND" label at 0.086 mm
   from a mask opening (D-73).")
9. Closed 2026-11-16 (D-80 ruling): the copper of both boards stays, and the staged T-A-06 metering (design r9-26)
   is the W5 single-bridge mitigation; the grid reorder is declined (section 11 item 31). (**Superseded 2026-11-16,
   D-80 ruling:** "The W5 grids: the staged T-A-06 metering (design r9-26) or a grid reorder, a copper change (D-80;
   section 11 item 31). **Amended 2026-11-16 (D-80 addendum):** not ruled; the addendum records the deep-dive
   findings and the candidate mitigations.")
10. J.2 item 82 (the strap at 2.77 A) (section 11 item 40). The J.2 item 83 half is closed 2026-11-16 (D-94):
    /CHG_ARM keeps its route under a conditional D-36 exemption (section 11 item 41). (**Superseded 2026-11-16,
    D-94:** "J.2 item 82 (the strap at 2.77 A) and J.2 item 83 (/CHG_ARM in the D-36 zone; a re-route is a copper
    change) (section 11 items 40 and 41).")
11. J.2 item 84: the T-C-04 repetitions on the only U101 and a spare U101 in the Mouser order (section 11 item 42).
12. J.2 item 85: C103 stays 1.0 uF or becomes a 4.7 uF part (section 11 item 43).
13. The five opt-in SPARE lines of `bom_2026-11-14/digikey_optional.csv` (D-89; section 11 item 44).

Status on 2026-11-14 (history; superseded by the 2026-11-15 table above):

| Board | Schematic | Placement | Routing | ERC | DRC | Fab package |
|---|---|---|---|---|---|---|
| EIB | complete; part fields synchronized with the ordered BOM (D-82) | complete | complete; tracks, vias, pads and zone outlines unchanged since D-68, pour fill changed at J201 by D-70 (**Superseded 2026-11-14, fix round 2026-11-15:** "copper unchanged since D-68"); pour clearance at J201 (D-70), no paste on DNP pads (D-71), pin-1 dots (D-72), J201 map and E labels (D-73), references and board marking (D-74, D-78), stack-up block (D-76) | 0 | 0 violations, 0 unconnected items, 0 parity issues (`--severity-all --schematic-parity`) | `fab/eib_2026-11-14/`, written on 2026-11-15 by `gen/export.sh eib 2026-11-14` (**Superseded 2026-11-14, package exported:** "to be written by `gen/export.sh eib 2026-11-14`; the last exported package is `fab/eib_2026-11-13c/`"); not ordered |
| CR | complete; part fields synchronized with the ordered BOM (D-82) | complete | complete; tracks, vias, pads and zone outlines unchanged since D-69, F.Cu pour fill changed at J1 pin 18 by D-75 (**Superseded 2026-11-14, fix round 2026-11-15:** "copper unchanged since D-69"); pin-1 and cathode marks (D-72), J101 map and W-lead labels (D-73), references and board marking (D-74, D-78), J1 pin-18 solid zone connection (D-75), stack-up block (D-76) | 0 | 0 violations, 0 unconnected items, 0 parity issues (`--severity-all --schematic-parity`) | `fab/cr_2026-11-14/`, written on 2026-11-15 by `gen/export.sh cr 2026-11-14` (**Superseded 2026-11-14, package exported:** "to be written by `gen/export.sh cr 2026-11-14`; the last exported package is `fab/cr_2026-11-13f/`"); not ordered |

The 2026-11-14 round answers the read-only review `REVIEW_2026-11-14.md` and the five simulations in `sim/`
(`sim/README.md`). D-70 to D-84 record it. Phase A edited silkscreen, paste, pours and stack-up in place (D-70 to
D-77). Phase B fixed three silkscreen defects of the phase A check (D-78), recorded three part decisions (D-79 to
D-81), synchronized the netlist with the ordered parts (D-82) and regenerated the BOM set (D-83). D-84 records the EIB
REGN deviation. Copper is unchanged on both boards: `gen/pcbdiff.py` against git HEAD `014c745` gives CR 692 / 692
segments and 420 / 420 vias, EIB 332 / 332 segments and 93 / 93 vias, and zone changes in fill only.

The CR constraint check (`cr/constraint_check.md`, regenerated 2026-11-14) has 128 rows: 108 pass, 1 pass with the
exceptions listed in the rows above it (IC pitch, D-39), 3 exemption rows (R102 under D-20; R103 and R129 as listed
U101-network exemptions), 16 information rows and 0 FAIL. The D-20 stitching row reads 303 stitch points and 3.49 mm
at (31.0, 34.8) against 3.54 mm. The EIB constraint check (`eib/constraint_check.md`) has 5 pass rows, 1 deviation row
(the D-25 outline) and 2 information rows. `cr/geometry_check.md` was regenerated by `gen/cr_geometry.py` on
2026-11-14 (REVIEW CRL-0): 28 pass rows and 3 information rows on the D-62 outline.

The round leaves these items for the operator. None of them changes copper:

- D103: keep the ordered STPS2H100A or fit the onsemi MBRA2H100T3G alternate (D-79).
- The W5 wire-pad grids: a post-solder isolation check of the orthogonal J101 and J201 pad pairs, or a grid reorder
  (D-80).
- C108: fit the 470 pF assembly option or keep 1.0 nF; the brief T2 interruption hazard remains either way (D-81).
- The EIB reference rule set: the stricter phase B rules (18 of 26 fitted references on the top side) or the phase A
  rules (22 of 26) (D-78).
- The W6 "GND" label at 0.086 mm from a mask opening against the 0.10 mm phase B rule (D-73).

Status on 2026-11-13 (history; superseded by the 2026-11-14 table above):

| Board | Schematic | Placement | Routing | ERC | DRC | Fab package |
|---|---|---|---|---|---|---|
| EIB | complete | complete | complete (D-28; straightened tracks, top AGND pour and stitching D-63; references D-64; J201 wire pads and local re-route D-66; E-pad pour clearance D-68) | 0 | 0 (schematic parity checked) | `fab/eib_2026-11-13c/` (D-49 DNP set; exported after D-68; order 3); not ordered |
| CR | complete | complete (D-54 to D-56) | complete (D-58; power copper D-57; outline D-62, holes D-60 and D-62; GND stitching and straightened tracks D-61, re-run in D-62; references D-59 and D-62; operator cleanup `547dc11`; via merges D-65; J101 wire pads D-66; U101 TCKE1401NM D-67; U101 paste windows D-69) | 0 | 0 violations, 0 unconnected items, 0 parity issues (`--severity-all --schematic-parity`) | `fab/cr_2026-11-13f/` (exported after D-69; copper equals `fab/cr_2026-11-13d/`); not ordered |

On the routed CR with the D-62 outline and the re-run stitching (D-60 to D-62), the constraint check
(`cr/constraint_check.md`) gives 108 pass rows, 1 pass row with listed exceptions, 0 FAIL (including the D-20
stitching row, 3.49 mm against 3.54 mm since D-66, and the D-62 outline rows) (**Superseded 2026-11-14, REVIEW
DOC-10:** "109 pass rows, 0 FAIL (including the D-20 stitching row of D-61, 3.51 mm against 3.54 mm"; the count
included the IC-pitch row "pass (rows above list any exception)", and D-66 moved the stitching figure to 3.49 mm), 3 exemption rows (R102 under D-20; R103 and R129 as listed U101-network exemptions,
D-55/D-56) and 16 information rows (D-56). The fabricator of the CR is OSH Park (bare board), with the rule file
`tools/pcb/fab_rules/fab_4layer_oshpark_only.kicad_dru`. The EIB is a 2-layer board; at OSH Park it is a separate order
and is not on the CR panel. Neither package has been ordered. The operator's pre-order review of the routed CR and the
two packages (D-50 check-in 4) took place in two parts on 2026-11-13. Operator ruling 2026-11-13 (Review 2/2: BAV199,
strap, OSH Park (fab checks), local_6e36c3a4-f328-44cd-8c31-05ea2fa7bfa3, chat 2026-11-13) closes section 11 items 9 and
10 and the VCHGIN half of item 2, closes the stack-up and mask-expansion parts of item 5, closes item 7 as out of scope
and amends item 3. Operator ruling 2026-11-13 (design session, chat 2026-11-13: "Accept short necks") closes the VCHGOUT
half of item 2 (next paragraph). No operator-review item now blocks the CR bare-board order. (**Superseded 2026-11-13:**
"Apart from the VCHGOUT half of section 11 item 2 (next paragraph), no operator-review item now blocks the CR bare-board
order."; the design-session ruling closes the VCHGOUT half.) (**Superseded 2026-11-13:** "Item 3, the OSH Park policy on
non-functional inner pads, stays open as an assumption that the operator checks when the board is submitted. The
drilled-versus-finished reading of the 1.1 mm TSW holes stays open in item 5. It does not block the order, because a
finished hole down to the 1.02 mm drawing value still gives about 0.06 mm of corner clearance on the 0.64 mm post
(D-41). The open rest of item 16 is a parts check and does not block the order."; restated as the list below.) Operator
ruling 2026-11-13 (design session, chat 2026-11-13: "Use 6") closes the quantity question (second paragraph below).
Three items stay open, and none of them blocks the order:

- item 3, the OSH Park policy on non-functional inner pads, as an assumption that the operator checks when the board
  is submitted;
- the drilled-versus-finished reading of the 1.1 mm TSW holes under item 5, because a finished hole down to the
  1.02 mm drawing value still gives about 0.06 mm of corner clearance on the 0.64 mm post (D-41);
- the open rest of item 16, a parts check on the cable. (**Superseded 2026-11-13:** "Four items stay open, and none of
  them blocks the order:"; the list also named "the quantity '5 (E BOM)' in the package README against the OSH Park
  multiples of 3 (second paragraph below)", which the ruling closes.)

The VCHGOUT half of section 11 item 2 is closed by acceptance. The copper sections of the VCHGOUT path from U101 OUT
to W1 were measured on the D-62 board layout and checked against the 3.21 A basis (`round4/calc/r9_calc.py` R9.H26).
Two short necks carry the current on F.Cu only, because the In2.Cu `VCHGOUT_L3_strap` ends at x 36.90: 1.469 mm over
about 1.75 mm (U101 OUT pins to C103) and 2.082 mm over about 1.25 mm (C103 ground pad and the D-56 /GND via notch).
On the IPC-2152 long-conductor basis, these necks carry 2.30 A and 2.75 A at a 10 C rise, and the rise at 3.21 A is
21.9 C and 14.3 C. The operator, asked whether to accept the two short necks, widen the copper or measure the rise on
the bench, ruled "Accept short necks" (operator ruling 2026-11-13, design session, chat 2026-11-13). The two necks
stay as they are, and the board does not change. The long-conductor chart is expected to be conservative for necks
this short, because heat spreads into the wider pour. However, no short-neck calculation is on record, so the
acceptance rests on the ruling and not on a passed check (section 11 item 2). (**Superseded 2026-11-13:** "The one open
engineering item is the VCHGOUT half of section 11 item 2, which is outside the Review 2/2 ruling. The copper sections
of the VCHGOUT path from U101 OUT to W1 were measured on the D-62 board layout and checked against the 3.21 A basis
(`round4/calc/r9_calc.py` R9.H26). Two short necks carry the current on F.Cu only, because the In2.Cu `VCHGOUT_L3_strap`
ends at x 36.90: 1.469 mm over about 1.75 mm (U101 OUT pins to C103) and 2.082 mm over about 1.25 mm (C103 ground pad
and the D-56 /GND via notch). On the IPC-2152 long-conductor basis, these necks carry 2.30 A and 2.75 A at a 10 C rise
and fail the 3.21 A basis. Whether this blocks the order needs an operator ruling: accept the two short necks, widen the
copper, or measure the rise on the bench (section 11 item 2)."; operator ruling 2026-11-13 (design session) accepts the
two necks.) (**Superseded 2026-11-13:** "The VCHGOUT half of item 2 (the In2.Cu `VCHGOUT_L3_strap` at 3.21 A) is outside
the ruling and stays open. No current check of the VCHGOUT path at 3.21 A is on record, so it is not established whether
this half blocks the order."; R9.H26 measures the path.)

The quantity follow-up that the Review 2/2 session raised is closed. The operator was asked whether the package README
quantity is 6 or stays 5. Operator ruling 2026-11-13 (design session, chat 2026-11-13: "Use 6") sets it to 6. The CR
order quantity is 6, that is two OSH Park lots of 3; the E BOM asks for 5, so one board is a spare. Section 1 of the
package README reads "6 (operator ruling 2026-11-13: 'Use 6'; OSH Park sells boards in multiples of 3; the E BOM asks
for 5)". Closed 2026-11-13. The EIB order quantity is 3, one OSH Park lot (operator ruling 2026-11-13, chat: "Order 3"); the EIB package README section 1 reads "3". (**Superseded 2026-11-13:** "One follow-up that the Review 2/2 session raised has no
operator answer and stays open: the fab package README gives a quantity of '5 (E BOM)', but OSH Park sells boards in
multiples of 3. The D-62 re-export states the multiples of 3 in the OSH Park row of the README and keeps the quantity
until the operator rules on it."; the ruling sets the quantity to 6.) The OSH Park row of the package README states the
confirmed OSH Park stack-up (section 11 item 5). The outline is the D-62 outline (operator ruling 2026-11-13, route-race
request R9-04: edges at 0, 30, 45 or 60 degrees to the axes and 1.0 mm fillets), and the status table, the
constraint-check counts and `fab/cr_2026-11-13/` are for the D-62 board. The status line of the package README names
the D-62 outline (corrected in `b3437ef`). (**Superseded 2026-11-13:** "The status line of the package README still
names the D-60 outline and 19 F.Fab references; it is corrected at the next re-export."; `b3437ef` corrects the
status line.) (**Superseded 2026-11-13:** "Two
follow-ups that the Review 2/2 session raised have no operator answer and stay open without a change. First, the fab
package README gives a quantity of 5, but OSH Park sells boards in multiples of 3. Second, its OSH Park row refers to
'the 1 oz fallback', but the OSH Park 4-layer stack-up already is 1 oz outer and 0.5 oz inner copper. In addition, a
further outline trim (D-62; operator ruling 2026-11-13 relayed by the routing session: rectilinear or 30/45/60 degree
edges, 1.0 mm fillets) is in progress and not yet committed. The status table above, the constraint-check counts and
`fab/cr_2026-11-13/` are for the D-61 board until D-62 is recorded."; D-62 is recorded, and the re-export corrects the
OSH Park row.) (**Superseded 2026-11-13:** "The next step is the operator's pre-order review of the routed CR and the
two packages (D-50 check-in 4). Section 11 lists the open items that the review must close before the CR bare-board
order: items 2, 3, 5, 7 and 9."; operator ruling 2026-11-13 (Review 2/2) closes or amends these items, section 11.)
(**Superseded 2026-11-13:** "items 2, 3, 5, 7, 9, 14, 16 and 25, and the W6/W7 lead pads of D-45, and the D-20 stitching
gap of D-61"; the gap fill of D-61 closes the stitching gap, and operator ruling 2026-11-13 (Review 1/2: J102, J1-TSW,
W6-W7 (connector and lead-pad geometry), local_923ffa1c-f985-43ad-8510-7faea2e5f5d7, chat 2026-11-13) closes items 14
and 25, the header half of item 16 and the W6/W7 lead pads (D-41, D-45, D-46). The open rest of item 16, the cable wire
gauge and insulation, is a parts check and does not block the bare-board order.)

Status on 2026-11-11 (history; superseded by the table above):

| Board | Schematic | Placement | Routing | ERC | DRC | Fab package |
|---|---|---|---|---|---|---|
| EIB | complete | complete | complete | 0 | 0 (schematic parity checked) | `fab/eib_2026-11-11/` |
| CR | complete | complete | power pours and straps only; signal nets not routed | 0 | 200 unconnected items, 4 starved thermals (3 U101 thermal-pad vias; J1 pad 10 to two VCHGIN_L1 slivers of 0.65 and 0.50 mm2), 2 silkscreen items | not produced |

On 2026-11-11, the CR signal routing did not close with the methods of section 7. Section 8 records every attempt
and its result; `HANDOFF.md` gave the starting point for the work that followed (D-39 to D-58).

Status on 2026-11-12: the operator took two rounds of decisions (`DESIGN_STATE_2026-11-12.md` Table 1 and section 4;
`decisions_2026-11-12/round2/orchestrator_digest.md`). The CR changes to a removable plug-on board on the outline
x 18.584-67, y 7-94 (D-39), with all SMT parts on the top side (D-44) and a reduced permit gate (D-47). Every entry
below is classified against these decisions:

- entries marked **Retired 2026-11-12** describe the r7 board only and bind no future build;
- entries marked **Re-derive on the new outline** keep their rule, but their coordinates and regions are re-computed
  by the new-outline generator;
- entries marked **Amended 2026-11-12** or **Reversed 2026-11-12** state the rule in force;
- entries marked **Kept** and entries without a mark stay in force unchanged;
- D-39 to D-53 are new entries for the 2026-11-12 decisions (section 8, after D-38). D-54 to D-59 record the
  2026-11-13 work: D-54 the step-5 placement, D-55 and D-56 the two placement fix rounds, D-57 the C102c /GND
  pre-via and the VIN_L3 strap extension, D-58 the CR signal routing and D-59 the reference designators.

The 2026-11-11 status table above (r7 outline), the placement of section 5 and the routing record of section 8 are history. The
r7 layout work, including the interactive-routing project, is in `archive_r7_outline/`. The EIB
fab package `fab/eib_2026-11-13/` carries the D-49 DNP set from the schematic and board attributes, with copper and
drill files identical to `fab/eib_2026-11-11/`; it has not been ordered and awaits operator review (D-49).

## 2. Sources and reproduction

All board data is generated by the scripts in `gen/`. The scripts are the record of every coordinate.

| Step | Script | Input | Output |
|---|---|---|---|
| Netlist | `gen/netlist.py` | B.8 pin tables, E values and packages | part and net data for both boards |
| Footprint library | `gen/fplib.py`, `gen/fpmap.py` | KiCad 9.0.9 stock footprints, A.8/A.9 pad geometry | `<board>/charger_r8_<board>.pretty` |
| Symbols, schematic | `gen/sch.py` | `netlist.py` | `<board>/<board>.kicad_sch`, `charger_r8_<board>.kicad_sym` |
| Placement | `gen/pcbbuild.py`, `gen/layout_cr.py`, `gen/layout_eib.py`, `gen/packer.py` | exported netlist, A.7/A.8/A.9 | placed `<board>.kicad_pcb` |
| Power copper, pours | `gen/route.py`, `gen/route_cr.py`, `gen/route_eib.py` | placed board | pours, straps, router keep-out band |
| Signal routing (CR, D-58) | corridor router `tools/pcb/corridor_route/` with a plan file (board-routing method; plan softum chosen by the route-race r9 study, D-58) | poured board | routed board |
| Signal routing (EIB; r7-outline CR, history) | Freerouting 2.5.0 (`route.py`), `gen/pathfinder.py`, `gen/finish_*.py`, `gen/finish.sh` | board dump | routed board |
| Reference designators (CR, D-59) | `gen/silk_refs.py` | routed board | reference fields on F.Silkscreen or F.Fab, `cr/silk_refs.md` |
| In-place edits of 2026-11-14 (D-70 to D-78) | CR: `gen/cr_pin1_marks.py`, `gen/cr_silk_refs_r2.py`, `gen/cr_wire_labels.py`, `gen/cr_lead_labels.py`, `gen/cr_j1_pin18_solid.py`, `gen/cr_stackup.py`, `gen/cr_silk_fix_r3.py`, `gen/cr_silk_refs_report.py`; EIB: `gen/eib_j201_pour_clearance.py`, `gen/eib_dnp_paste.py`, `gen/eib_pin1_marks.py`, `gen/eib_board_marking.py`, `gen/eib_wire_labels.py`, `gen/eib_silk_refs_r2.py`, `gen/eib_stackup.py` | current board | marks, maps, labels, references, pour and paste settings, stack-up block; `cr/silk_refs.md`, `eib/silk_refs.md` (run order below the table) |
| Part fields (D-67, D-82, D-88) | `gen/sync_fields.py` (`--add-missing` since D-88) | board, exported netlist | Value, MPN, Manufacturer and Note fields of the footprints; with `--add-missing`, a missing field is added as a hidden F.Fab field |
| In-place silkscreen edits of 2026-11-15 (D-85, D-86) | CR: `gen/cr_silk_fix_r4.py`; EIB: `gen/eib_silk_fix_r3.py` | current board | CR "VIN1"/"GND" labels and W1 reference; EIB E-pad numbers and E labels |
| NPTH gate (D-77) | `gen/npth_check.py` (run by `gen/export.sh`) | checked board | `reports/npth_check.txt` |
| Checks | `gen/check_constraints.py` | built board | `<board>/constraint_check.md` |
| Fab package | `gen/export.sh`, `gen/fab_readme.py` | checked board | `fab/<board>_<date>/` (current: `fab/cr_2026-11-14/` and `fab/eib_2026-11-14/`, written on 2026-11-15 by `gen/export.sh cr 2026-11-14` and `gen/export.sh eib 2026-11-14`; **superseded 2026-11-14, packages exported:** "next: `fab/cr_2026-11-14/` and `fab/eib_2026-11-14/`, to be written by `gen/export.sh cr 2026-11-14` and `gen/export.sh eib 2026-11-14`; last exported: `fab/cr_2026-11-13f/`, `fab/eib_2026-11-13c/`"; **superseded 2026-11-14:** "current: `fab/cr_2026-11-13/`, `fab/eib_2026-11-13/`") |

To regenerate the EIB, run `bash gen/make_eib_all.sh` from `hardware/charger_evm_r8`. To regenerate the CR up to
the pour stage, run `bash gen/make_board.sh cr` and then `ROUTE_SKIP_FR=1` `gen/route.py cr ../cr` from `gen/`. Restore
`cr/cr.kicad_pro` from git and refill the zones (D-57 build note, section 9.1). The signal nets are then routed by the
corridor router `tools/pcb/corridor_route/` with plan softum, seed 1 (D-58), and `gen/silk_refs.py` places the
reference fields (D-59). On the r7 outline, `gen/make_cr_all.sh` ran the first two steps and then the PathFinder
stage; it does not route the plug-on CR.

**Amended 2026-11-14 (D-70 to D-78, D-82).** No generator reproduces the boards of 2026-11-13: the operator cleanup
`547dc11` and the D-65 to D-69 in-place edits break the sequence (`RESPIN_HANDOFF_2026-11-13.md` section 3.3.3). The
2026-11-14 changes are therefore idempotent pcbnew scripts that edit the current boards in place. Run them from
`hardware/charger_evm_r8` with the pcbnew venv, in this order. On the CR:

1. `gen/cr_pin1_marks.py` (D-72);
2. `gen/cr_silk_refs_r2.py` (D-74);
3. `gen/cr_wire_labels.py` (D-73);
4. `gen/cr_lead_labels.py` (D-73);
5. `gen/cr_j1_pin18_solid.py` (D-75);
6. `gen/cr_stackup.py` (D-76);
7. `gen/cr_silk_fix_r3.py` (D-78);
8. `gen/sync_fields.py --add-missing cr/cr.kicad_pcb cr/cr.net`, after `gen/sch.py cr cr` and the `kicad-cli` ERC and
   netlist export (D-82, D-88);
9. `gen/cr_silk_fix_r4.py` (D-85, added 2026-11-15);
10. `gen/cr_silk_refs_report.py`, which writes `cr/silk_refs.md` and does not change the board (D-78).
(**Superseded 2026-11-15, D-85 and D-88:** the nine-step CR order without `gen/cr_silk_fix_r4.py` and without
`--add-missing`.)

On the EIB:

1. `gen/eib_j201_pour_clearance.py` (D-70);
2. `gen/eib_dnp_paste.py` (D-71);
3. `gen/eib_pin1_marks.py` (D-72);
4. `gen/eib_board_marking.py` (D-74, D-78);
5. `gen/eib_wire_labels.py` (D-73);
6. `gen/eib_silk_refs_r2.py eib/silk_refs.md` (D-74, D-78);
7. `gen/eib_stackup.py` (D-76);
8. `gen/eib_board_marking.py` and `gen/eib_silk_refs_r2.py eib/silk_refs.md` again (the D-78 rules are checked against
   the J201 map of step 5);
9. `gen/sync_fields.py --add-missing eib/eib.kicad_pcb eib/eib.net`, after `gen/sch.py eib eib` and the `kicad-cli`
   ERC and netlist export (D-82, D-88);
10. `gen/eib_silk_fix_r3.py` (D-86, added 2026-11-15), always last.
(**Superseded 2026-11-15, D-86 and D-88:** the nine-step EIB order without `gen/eib_silk_fix_r3.py` and without
`--add-missing`.)

Both sequences were run on a scratch copy of the git HEAD `014c745` boards with the 2026-11-14 `gen/` scripts and
netlists. The CR result equals the working-tree board: 0 segments, vias, zones or footprints differ, every reference
field is identical, and `cr/silk_refs.md`, `cr/cr.kicad_dru` and the CR library match. The EIB result has identical
copper, zones, rule file, library and board texts. Only the F.Fab field positions of C202, C203, R252, R254, U201 and
U202 differ, because `gen/eib_silk_refs_r2.py` leaves an F.Fab field where the previous state put it. A full
regeneration with `gen/make_board.sh` loses the D-65 to D-69 edits; after such a regeneration, run the two sequences
above in the stated order. `gen/fab_readme.py` and `gen/export.sh` (with the `gen/npth_check.py` gate, D-77) then
write the package.

**Amended 2026-11-15 (D-85 to D-88).** Both new scripts remove their own texts and place them again; a second run
gives the same positions to the nanometre. A replay of the two sequences on a scratch copy of the `014c745` boards,
with the current netlists and the two new scripts at the end, again equals the working-tree CR in every text and
field and the working-tree EIB except the six F.Fab field positions above (`update_2026-11-14/notes_phaseC_board.md`
section 8). Three tool residuals are known and not changed:

- `gen/cr_silk_refs_r2.py` stops on the current CR ("R107 bottom position blocked"), so the CR sequence replays from
  `014c745` only and cannot run again on the current board;
- a re-run of `gen/cr_lead_labels.py` on the current CR removes the W2 "GND" text and places "TS" differently;
  `gen/cr_silk_fix_r4.py` then places "GND" above W2, which differs from the recorded board;
- `gen/eib_silk_refs_r2.py eib/silk_refs.md` writes only its table and removes the hand-kept sections 1, 2 and 4 of
  `eib/silk_refs.md`; restore those sections from git after such a run.

## 3. Coordinate frame and pin identity

**D-01. Frame.** Every design coordinate is an Eagle board coordinate, top view, origin at the MB origin, +y
up (A.2 r6). The CR capture uses KiCad X = x and KiCad Y = 100 - y, so the CR lies at KiCad Y 24.00-65.86 mm.
The EIB uses its own frame (origin at its lower-left corner, +y up) with KiCad Y = 50 - y. The y inversion is
done once, in `pcbbuild.Frame`; no coordinate is typed in the KiCad frame.

**Amended 2026-11-12** (D-39; `outline_change_2026-11-12/retired.md`): the mechanism is unchanged. On the plug-on
outline the CR lies at KiCad Y 6.00-93.00 mm.

**D-02. Pin identity (A.2, A.8, T-A-06 step 0).** The 22 CHG holes form one footprint
(`Ag105_CHG_Carrier_22pin_P2.54mm`) whose pad numbers are the Ag105 pin numbers. Pin 1 is at (45.998, 39.084);
pins 1-10 run up the x 45.998 column and pins 11-22 run down the x 20.998 column. `check_constraints.py`
compares all 22 pad centres with the A.8 table: the maximum error is 0.0000 mm. Pads 1 and 11 are square, and
the silkscreen carries "1" and "11" on both sides. The only chamfer of the outline is at the tab Y corner
(17.70, 76.00) (A.7 r7), so a y-mirrored capture would move the chamfer to a low-y corner.

**Re-derive on the new outline (2026-11-12).** The pad check and `calc/pin_identity_check.py` stay, applied to the
TSW pin footprint of D-41. The chamfer retires: (17.70, 76.00) lies outside the new outline (x < 18.584). The
operator ruled that the CR carries no mechanical key (D-41). The pin-1 silkscreen arrow stays as the orientation mark.

## 4. Libraries, symbols and netlist

**D-03. Project-local libraries and courtyards.** Each project has its own symbol library and footprint library,
listed in the project `sym-lib-table` and `fp-lib-table` with `${KIPRJMOD}` paths. The symbols are generated from
the B.8 pin tables, so every pin number is the B.8 number. An independent three-reviewer audit compared every pin
of 216 parts (CR and EIB) with B.8 and every value and package with E; it found no discrepancy.

The A.8 regions were sized from courtyards of "IPC-7351 nominal land patterns + 0.25 mm". The KiCad stock
courtyards are larger than that basis: the VQFN-24 courtyard is 5.35 mm against a U101 slot of 5.00 x 5.09 mm,
and the seven LVC gates do not fit tab Y. Every footprint therefore uses the IPC-7351 least-density courtyard
excess, 0.10 mm beyond the union of the pads and the body outline (suffix `_CrtYd0.10`). The CR is
hand-assembled with hot air or reflow (A.8 hand assembly row), so the smaller excess is a placement clearance,
not an assembly risk.

| Footprint | Change from stock | Source |
|---|---|---|
| U101 TPS26630 | stock `Texas_RGE0024H_..._EP2.7x2.7mm_ThermalVias`; 3 x 3 thermal vias drilled 0.30 mm on a 0.61 mm land, numbered 25; EP solder-mask margin 0 mm (0.149 mm mask web to the pins) | `lib_verification_2026-11-11.md` row 1; A.8 U101 thermal pad (>= 9 vias, 0.3 mm) |
| SN74LVC DCT gates | pads moved to the TI DCT0008A land: 1.1 x 0.4 mm on a 3.8 mm span | `lib_verification` row 3 |
| SC70-5 gates | stock `Texas_R-PDSO-G5_DCK-5` | `lib_verification` row 5 |
| J101, J201 | Samtec FTSH-107-01-x-DV pattern from the Samtec drawing: pads 2.79 x 0.74 mm, row centres 4.07 mm, body 3.43 x 9.02 mm; J101 has no pad 6 (B.8: 6 omitted, key) | `lib_verification` section 4 |
| CHG header (22 pins) | 1.1 mm drill, 1.9 mm pads on L1 and L4; no pad on L2/L3 where the pin has no inner-layer connection (D-30); top courtyard one circle per pad | A.8 hole table (pad >= 1.9 mm) |
| W1-W4, W6/W7, F01-F24, E1-E8 | written from A.8 / A.9 geometry | A.8 hole and pad tables; A.9 E-pad row |
| small passives and ICs | no silkscreen; outline and pin-1 mark on F.Fab (D-12a) | dense board |

**Amended 2026-11-12** (`decisions_2026-11-12/round2/dec2_parts_assembly_2026-11-12.md` item 4; D-39, D-41, D-44).
The table above records the r7 footprints. The following rules replace it on the new outline:

- **Courtyard basis.** Every footprint uses the IPC-7351 nominal courtyard excess, 0.25 mm beyond the union of the
  pads and the body outline. The 0.10 mm least-density basis (suffix `_CrtYd0.10`) is withdrawn. Its reason, a dense
  hand-assembled board, no longer holds: the CR is stencil- and reflow-assembled on an outline of about 3 times the
  r7 area. The footprints are regenerated.
- **CHG header row.** The 22-pin CHG footprint becomes the CR side of the D-41 stack: TSW-110-07-L-S (pins 1-10) and
  TSW-112-07-L-S (pins 11-22), kept on F.Cu (no flip). The bottom courtyard is the TSW body, 2.54 x 25.40 mm and
  2.54 x 30.48 mm. Pad and drill come from the Samtec TSW drawing, TODO(verify: Samtec TSW drawing, CR pad and drill).
  (**Superseded 2026-11-13:** "TODO(verify: Samtec TSW drawing, CR pad and drill)"; closed by operator ruling
  2026-11-13 (Review 1/2: J102, J1-TSW, W6-W7 (connector and lead-pad geometry),
  local_923ffa1c-f985-43ad-8510-7faea2e5f5d7, chat 2026-11-13), D-41.)
- **U101.** The footprint stays (D-40). The nine exposed-pad thermal vias stay, exempt from D-37, with window-pane
  stencil apertures and L4 tenting.
- **0603 passives.** R101, R103, R104, R105, R106s and C101 change from 0402 to 0603 (D-44).
- **SC70-5 row.** The row retires. U107 becomes SN74LVC1G11DBVR (SOT-23-6, DBV), and no SC70 part remains on the CR
  (D-44, D-47). SCES487I Table 4-1, closed (section 11 item 18). (**Superseded 2026-11-14, REVIEW LOG-4:**
  "(SOT-23-5, DBV)"; "TODO(verify: TI Pin Functions tables) the DBV pinout against the DCK pinout, pin by pin
  against B.8.")
- **SN74LVC DCT row.** It applies to U105, U106, U110 and U118, which keep the DCT package (D-44).
- **J-TAP.** A Molex Micro-Fit 3.0 2 x 5 through-hole header is added (D-46). Its footprint comes from the Molex
  drawing, TODO(verify: Molex 43045 header drawing). (**Superseded 2026-11-13:** "TODO(verify: Molex 43045 header
  drawing)"; closed by operator ruling 2026-11-13 (Review 1/2: J102, J1-TSW, W6-W7 (connector and lead-pad geometry),
  local_923ffa1c-f985-43ad-8510-7faea2e5f5d7, chat 2026-11-13), D-46.)
- **W1-W4, W6/W7.** The through-hole lead pads stay on the CR (D-45). The F01-F24 tap pads are removed (D-46). The
  E1-E8 pads on the EIB are unchanged.
- **Silkscreen.** Reference designators are on the silkscreen for every part (D-12a reversed).
**D-04. Pin typing for ERC.** U101 OUT (17, 18) and PGOOD (16) are typed passive, because two power outputs on
one net and an open collector on the flagged GND net are ERC conflicts, not circuit faults. PWR_FLAG symbols
mark GND, 3V3 and VCHGIN on the CR, and 3V3 and AGND on the EIB.

**D-05. Net names.** Where B.8 names a net, the net carries that name verbatim. Where B.8 names only a pad, the
net takes a descriptive name: F01 `T1_VMOT`, F03 `T2C`, F04 `BTB`, F05 `RGN_TAP`, F06 `FCC_TAP`, F07 `T6_3V3`,
F08 `T22_BAL`, F09 `BT_CURR`, F10 `KELVIN`, F11 `QUAL_TAP`, F12 `FCCEIL`, F13 `ILIM_SENSE_RB`, F14 `H1_RB`, F15
`H2C_RB`, F16 `BTOK_RB`, F17 `CHG_EFUSE_FLT`, F18 `CHG_IIN`, F20 `CE_SENSE_RB`, F21 `HB_TAP`; F02 and
F19 are GND; F22, F23 and F24 have no net (D-31; F23 carried `T19_FCI` until DNP tier 3). The ribbon pins take `J3V3_1`, `J3V3_2`, `CE_DRV_J`, `ILIM_REL_A`,
`ILIM_REL_B`, `RFC_OFF_J`. U111/U113 timing nodes are `N_CX11x` (pin 6) and `N_RC11x` (pin 7).

**Amended 2026-11-12** (`decisions_2026-11-12/cr_tap_review_2026-11-12.md` section 3;
`decisions_2026-11-12/round2/tap_connector/dec_tap_connector_2026-11-12.md`; D-46, D-47). The ten kept taps end on
the J-TAP cavities, and each cavity net keeps the D-05 name of its former F pad: T1 `T1_VMOT`, T7b GND, T2 `T2C`, T5
`FCC_TAP`, T6 `T6_3V3`, T10 `QUAL_TAP`, T13 `H1_RB`, T16 `CHG_EFUSE_FLT`, T17 `CHG_IIN` and T17r GND.
TODO(verify: regenerated `cr/cr.net`) that the regenerated netlist uses these names. The pad names F01-F24 retire. The names `BTB`, `RGN_TAP`, `BT_CURR`, `KELVIN`, `FCCEIL`, `ILIM_SENSE_RB`, `H2C_RB`, `BTOK_RB`,
`CE_SENSE_RB` and `HB_TAP` are removed with their taps; `T22_BAL` was removed by D-38. The U111/U113 timing nodes are
removed with the one-shots. The ribbon pin names are unchanged; J101 pins 11 and 13 are NC (D-49).

**D-06. R106 footprint omitted (CR).** B.8 keeps a DNP R106 footprint between `CHG_EFUSE_FLT` and 3V3. The r8
rule of A.8 (R106s placement) requires that the F17 pad is the only exposed copper of `CHG_EFUSE_FLT` apart
from the R106s terminal, so the capture omits R106 (P-06).

**Amended 2026-11-12** (D-46). The omission stays. The F17 pad is replaced by the J-TAP T16 contact, so the
exposed-copper rule is re-derived against that contact and its solder joint. R106s becomes 0603 (D-44), and its
r7 location on the tab X bottom retires with D-18.

**D-31. DNP option footprints removed (operator ruling 2026-11-11, tiers 1 and 2).** To free routing area on the
CR, the operator ruled that the DNP option footprints are removed tier by tier until the CR routes:

- Tier 1 (removed): C105 (SLVSE94G 8.3.9 forbids an IMON bypass capacitor), R145 and R146 (the I2C pull-ups stay on
  the MB 3V3 side, A.2).
- Tier 2 (removed): the keep-alive option U112, C152, D101 and R_KA (B.5: "do not populate in the baseline"), and
  R134 (FCC pull-down, DNP since r6). The F22 (T18) pad stays, with no CR net.
- Tier 3 (removed 2026-11-11, approved by the operator with the tier 1-2 ruling as the next lever): the FC-current
  permit option U117, R160-R163, C127, C124. R137 stays fitted (`FCI_OK` to 3V3). The F23 (T19) pad stays, with no
  CR net. The rebuild moved only bottom passives (`cr/placement_log.txt`); every fixed coordinate and top IC is unchanged.

The DNP parts are not on the ordering BOM, so the BOM does not change. P-09 records the matching B.8 change.

**Amended 2026-11-12** (`decisions_2026-11-12/round2/dec2_parts_assembly_2026-11-12.md` items 3a-3d;
`decisions_2026-11-12/cr_tap_review_2026-11-12.md` section 3). The reason for the tiers, routing capacity, is weaker
on the new outline. The operator nevertheless re-admitted no part:

- C105, R145 and R146 (tier 1) stay removed, with no footprint.
- The B.5 keep-alive option is retired with its CR parts U112, C152, D101 and R_KA, because its enable (T4) and its
  supply (T18) are removed. T-B-09 stays as the test of regen capture in regen-armed cruise; its fail branch is the
  fused VBT-VCHG link on the MB (B.5 second fallback) or a later keep-alive design.
- R134 stays removed. A pull-down on T5 would make an open T5 read "FC charge proven off".
- U117, R160-R163, C127 and C124 (tier 3) are retired, with no gate input reserved. FR-14(e) becomes "if T-F-04b
  fails, restrict FC windows to standstill/coast". R137 (`FCI_OK`) is removed with the FCCEIL terms (D-47).
- The F22 (T18) and F23 (T19) pads, which tiers 2 and 3 kept without a net, are removed with taps T18 and T19. The
  F24 pad (pin 2 `PURGE_SENSE` option) is removed as well.

## 5. CR placement

Sections 5.1-5.4 record the placement on the r7 outline. The classification of each entry follows
`OUTLINE_CHANGE_REASSESSMENT_2026-11-12.md` Table 4 and `outline_change_2026-11-12/retired.md` section 2. The
placement on the new outline waits for the frozen netlist, after the r9 audit (D-50). The netlist is frozen (D-53).

### 5.1 Fixed coordinates (A.8)

**D-08. Fixed pads.** The 22 CHG holes, W1-W4, W6/W7, the 20 tab X tap pads (r7 assignment) and the four low-row
pads F08, F09, F10 and F22 sit at the A.8 coordinates. R175 sits vertically at (50.80, 62.75), centred between
R175b (61.48) and R175a (64.02); its 1206 pads are 2.925 mm apart. `cr/constraint_check.md` shows every fixed
position to 0.001 mm.

**Re-derive on the new outline (2026-11-12)** (D-41, D-45, D-46). The 22 CHG coordinates stay; they now locate the
TSW pins of D-41. W1-W4 and W6/W7 stay as through-hole pads on the CR, at positions re-derived for the new outline.
The tab X grid and the low-row pads F08, F09, F10 and F22 retire with the tap pads; J-TAP replaces them under the
D-46 placement constraints. R175 stays on the CR at the T6 end and is re-placed; the T-F-12 R175 bypass check (68 ohm)
stays wherever R175 sits.

**D-09. eFuse cluster (A.8 IN strip, OUT strip, +x pocket).** Two causes move the cluster from the A.8 targets.
First, the KiCad courtyards of the TI RGE0024H land (5.18 mm) and of the SMA diodes (7.09 x 3.59 mm) are larger
than the A.8 basis. Second, with U101 at y 64.1 the top-edge pins 13 (IMON) and 14 (FLT) lie 0.7 mm from the +y
outline, between the GND pins 15/16 and the pocket: FLT then has no legal escape at any clearance. U101 and the
IN strip therefore move 0.40 mm toward -y, which opens one track channel along the +y edge.

**Re-derive on the new outline (2026-11-12).** The second cause is gone: the new +y edge is at y 94, so the A.8
targets are reachable again. The first cause changes with the 0.25 mm courtyard basis (D-03). R101, R103, R104, R105
and C101 are 0603 (D-44), and R104 moves to the top (D-32 retired). The pocket rules that remain are the A.8 distances
in the table below.

| Part | A.8 target centre | Placed centre | Constraint kept (`cr/constraint_check.md`) |
|---|---|---|---|
| U101 | (41.8, 64.1) | (41.70, 63.65) | IN/IN_SYS edge facing -y |
| C102c | (41.8, 60.825) | (41.80, 60.27) | 0.53 mm to pins 1/2/5 (<= 3 mm) |
| C102a | (40.95, 57.675) | (40.95, 57.14) | 2.09 mm to pins 1/2/5; VCHGIN pad at the top |
| R102 | (43.55, 58.35) | (43.55, 57.76) | N_UV pad 2.09 mm from pin 6 (design 2.1 mm) |
| C102b | (42.125, 53.65) | (42.125, 53.14) | >= 0.5 mm from the pin-3..10 pads |
| D107 | (38.15, 56.70) | (37.90, 56.30) | cathode 2.43 mm from pins 1/2/5 |
| C103 | (38.35, 64.90) | (38.08, 64.88) | 1.52 mm to pins 17/18 (<= 3 mm) |
| D103 | (34.10, 65.05) | (33.50, 64.84) | cathode at the +x end |
| R101 | +x pocket | (45.275, 63.90) | in line with pin 10, straight escape |
| C101 | +x pocket | (47.225, 63.90) | reached from pin 9 along y 63.40 |
| R105 | +x pocket | (45.275, 65.06) | below the +y-edge escape channel |
| R103 | +x pocket | (47.225, 65.06) | the slot freed by C105 (D-31) |
| R104 | +x pocket | bottom, (39.505, 62.845) | 4.2 mm from pin 7 (A.8: <= 5 mm from pins 7-13); D-32 |

**D-32. R104 on the bottom.** A.8 names a bottom fallback for R103/R104 at y >= 63.71, x 44.3-48.2. The bottom
clearance rule (D-17) covers that whole area, so R104 is placed on the bottom inside a 6 mm circle around pin 7
and lands 4.2 mm from it, which meets the A.8 5 mm rule (P-10).

**Retired 2026-11-12** (all SMT on the top side, no bottom fallback; `decisions_2026-11-12/round2/dec2_parts_assembly_2026-11-12.md`
item 1). R104 (TNPW060349K9BEEA, 0603) is a top part. The A.8 rule that places R103 and R104 within 5 mm of U101
pins 7-13 stays.

**D-10. J101.** J101 sits at (40.60, 46.83) with its rows along y. Its courtyard (7.15 x 9.31 mm, Samtec pads)
lies inside the A.8 J101 region x 37.0-44.5, y 42.13-51.53. Pin 1 is at the +y end.

**Amended 2026-11-12** (`decisions_2026-11-12/round2/dec2_eib_2026-11-12.md`; D-49). The position rule stays; the
region is bounded by internal regions, not by the outline. J101 stays 2 x 7. Pins 11 and 13 are NC on the CR, and the
CR nets `ILIM_SENSE` and `CE_SENSE` and the readback resistors R125 and R148 are removed.

### 5.2 Comparator band (A.8 footprint low-y band, A.7 thermal band)

**D-11. Comparator positions.** Four comparators (U115, U119, U103, U102) form the band's upper row at y 40.10,
with courtyards inside x 23.15-39.27. U104 sits in the lower row at (34.56, 36.60), next to F09/F10. The band holds
only five comparators at x <= 39.53 with KiCad courtyards, so **U120 and U121 take the band positions that A.8
makes conditional on the MS4b reading**: U120 at (38.61, 36.60) (courtyard to x 40.51) and U121 at (41.315, 40.10)
(courtyard to x 43.21). TODO(verify: T-A-08 MS4b reading). P-03 records the fallback.

**Re-derive on the new outline (2026-11-12)** (`decisions_2026-11-12/cr_tap_review_2026-11-12.md`; D-47). U104,
U115 and U121 are removed with their networks. Four comparators remain: U102 (H1), U103 (UVB), U119 (FCC_OFF) and
U120 (FCC_ON). The limit x <= 39.53 was the 10 mm rim rule to the MB 5V copper on the r7 outline; REG-5V and both
boosts now lie under the CR. The comparators and their input networks therefore follow the sensitive-part window of
D-20 (y 30.8-66.86, preferred, not hard) and the keep-outs of `outline_change_2026-11-12/mbparts.md` section 2.3. The
MS4b condition for U120 and U121 is moot: U121 is removed, and U120 is placed under the window rule. Its successor is
the MS4 thermal map of the new heat sources, TODO(measure: operator, MS4).

**D-12. Band corners (P-04).** D108 (BAV199 clamp, analog) uses the band corner left of F08 (x 22.20-25.40, y
34.64-38.62); driven logic may use the strip below the pin-1 post (x 42.80-48.20, y 34.64-37.85).

**Re-derive on the new outline (2026-11-12).** The corners existed because of the D-11 crowding of the r7 band. The
new outline lifts that crowding. The BAV199 clamps D104-D106 stay analog parts under the D-11 window rule.

**D-12a. Silkscreen.** Small passives and ICs carry no silkscreen; their outline and pin-1 mark are on F.Fab and
in the InteractiveHtmlBom. Reference designators are on the fab layers. J1 keeps its "1"/"11" marks, J101/J201
their pin-1 marks, and the EIB carries the E1-E8 labels on its bottom silkscreen.

**Reversed 2026-11-12** (`decisions_2026-11-12/round2/dec2_parts_assembly_2026-11-12.md` item 4). Every CR part
carries its reference designator on the top silkscreen, which helps stencil assembly and rework. The F.Fab outline and
pin-1 mark stay. The text size against the OSH Park silkscreen minimums is TODO(verify: OSH Park); keeping the
0.8 / 0.15 mm values as a house rule is the design owner's choice.

**Amended 2026-11-14 (D-72, D-74, D-78).** The silkscreen now also carries pin-1 dots and SMA cathode bars on the ICs
and diodes listed in D-72, the J101 and J201 wire-pad maps and the W-lead labels (D-73), and a board marking on each
board (D-74, D-78). A reference with no legal top-side position goes onto B.Silkscreen, mirrored, over its part, and
its F.Fab `${REFERENCE}` text stays: 7 CR references and 8 fitted EIB references (D-78). These bottom-side references
can be read only before the CR is plugged onto the MB and before the EIB is mounted on its standoffs.

**Amended 2026-11-17 (operator rulings; the D number is assigned by the design owner).** The bottom-side fallback
above is withdrawn. The operator cannot see the bottom of a board while the top-side parts are assembled, so a
top-side SMD part never has a B.Silkscreen label. In addition, the top silkscreen keeps only the reference labels
that sit at their own parts. A top-side SMD part goes into the **assembly guide** instead of the silkscreen when one
of these conditions is true:

- the part has no visible top-side reference (NONE);
- the label ink is more than 1.0 mm from the part's own pads, or nearer the pads of another part than its own
  (MARGINAL).

The assembly guide is a set of rendered top views, `assembly_guide/<board>/<board>_guide_<n>.png`, written by
`gen/assembly_guide.py` (`dump` in the pcbnew venv, then `plot` in a Python with matplotlib). Each page outlines its
parts on the board and tags each part with its reference and value. `assembly_guide/<board>/README.md` lists every
top-side SMD part with its status and page. Labels of wired connections, holes and through-hole parts (references
J, W, E, H, MH and TP, and parts with plated through-hole pads only) stay on the silkscreen on either side and are
not in the guide, because they are also used after assembly. The board edit is
`gen/assembly_guide.py apply <board>`, which moves the reference of every guide part to F.Fab (hidden) and removes
the bottom-side texts of top-side SMD parts; `gen/silk_no_bottom_smd.py` does the bottom-side part only. The silk
scripts `gen/cr_silk_refs_r2.py`, `gen/cr_silk_fix_r3.py` and `gen/eib_silk_refs_r2.py` no longer place a
bottom-side reference (`BOTTOM_REFS = False`).

State on 2026-11-17: the rulings and tools are in place, and the boards are not edited (the operator froze the
design files, which carry hand-edits). On the current boards the guide holds 62 of the 69 CR top-side SMD parts
(24 NONE, 38 MARGINAL) and 14 of the 37 EIB parts (13 NONE, 1 MARGINAL). The CR count is high because the D-74 and
D-78 placement put most CR labels 2 to 3.5 mm from their parts.

### 5.3 Footprint interior, divider strip and tab Y (A.8)

**D-13. Divider strip.** R109-R112, R114 and R115 (0.1 % dividers) lie inside the A.8 divider strip x 23.15-36.50,
y 42.14-45.69, outside the W3 pad exclusion, >= 13 mm from the MB 5V rim.

**Re-derive on the new outline (2026-11-12).** The distance to the MB 5V rim is re-checked against the new heat
sources under the CR (REG-5V, both boosts, both inductors). The divider pairs stay adjacent and aligned, inside the
D-11 window.

**D-14. Interior.** The interior region is the footprint inset by 0.5 mm, less the band, the J101 region, the IN
and OUT strips, the U101 courtyard and the +x pocket (each + 0.5 mm), the W pads (+ 0.5 mm), the header pads, the
divider strip, the B1R wedge (x 23.55-26.05, y 62.54-67.10, H.23(s)), the bead spots S1 (35.00, 47.69) and S2
(28.70, 53.42) (H.23(l)), the VCHGOUT belt x 29.00-37.30, y 59.00-64.20 (D-22) and 0.55 mm discs around the 11
fixed power vias. The B1R wedge and the bead spots B3, S3, S1 and S2 are top-side "footprints not allowed" rule
areas, so DRC checks them. Analog interior parts (D104-D106, U123) stay at courtyard x <= 39.53 and >= 3.0 mm from
the U101 loop region (H.23(f)).

**Re-derive on the new outline (2026-11-12).** `FP_RECT` is the inset r6 rectangle, and the B1R wedge, the bead spots
B3, S3, S1 and S2 and the r7 VCHGOUT belt belong to the r7 trunk dressing and the r7 power geometry. The new interior
region is built from the new outline, the D-41 TSW bodies, the D-46 J-TAP region, the W pads, the D-11 window and the
new power geometry (D-22). U123 is removed (D-38).

**D-15. Raster packer.** Parts without an A.8 coordinate are placed by `gen/packer.py`: a 0.05 mm occupancy
raster, summed-area tables for exact rectangle feasibility, up to 150 random-restart orderings, and a 0.08 mm
routing margin around every courtyard. The packer maximises the number of placed parts, then minimises the
distance from each part to the centroid of the pads it connects to. The KiCad DRC remains the gate.

**Amended 2026-11-12.** The method stays. `GRID_BOUNDS` (17.0, 33.5, 66.0, 77.0) and the `PARK` position (70, 50)
encode the r7 outline and are replaced; `PARK` lies outside the new outline. Every part is a top part (D-44). If a
regenerated placement does not fit on the top side, the design owner escalates to the operator; there is no bottom
fallback.

**D-16. Tab Y top.** The tab Y set is the A.8 set (U105, U106, U107, U110, U114, U116, U118); the packer fits five of
them (U106, U107, U110, U114, U116) around the FT2 disc, and U105 and U118 fall back to the interior as driven
logic. U108 and U109 sit in the interior (A.8). The 2.0 mm FT2 fill-hole disc carries no part and no copper.

**Retired 2026-11-12** (D-39; `outline_change_2026-11-12/retired.md`). Tab Y and the FT2 disc do not exist on the new
outline. U108, U109, U114 and U116 are removed (D-47). The five LVC packages that remain (U105, U106, U107, U110 and
U118) are placed as driven logic with the rest of the top parts.

### 5.4 Bottom side (A.7 bottom clearance rule, A.8)

**D-17. Bottom clearance rule as DRC rule areas.** The rule "every CR bottom-side courtyard stays >= 1.0 mm in plan
from every MB layer-1 feature that is not GND" (A.7 r7) is implemented as B.Cu "footprints not allowed" rule
areas, built from the r7 calculation's own MB data (`round4/calc/r7_calc.py`: 852 non-GND layer-1 traces, 22
polygons with their rim width, 80 vias and 19 non-GND CHG pads, plus the MB part boxes), each grown by 1.0 mm.

**Retired 2026-11-12** (`decisions_2026-11-12/round2/dec2_parts_assembly_2026-11-12.md` item 1). The CR has no bottom
SMT part, so the rule has nothing to bind. `mb_bottom_clearance()` must be removed from `gen/layout_cr.py`, not re-run:
on the new rectangle it would forbid bottom parts over both boost channels. The vertical clearance is now the D-20 air
gap (>= 1.5 mm from the lowest CR feature, THT tails included, to the tallest MB part below it).

**D-18. Bottom content.** Every passive that A.8 does not move to the top is a bottom part. Each decoupler sits
under the VCC pin of its IC. Comparator-input, hysteresis, reference and timing passives stay off the tab X bottom
(A.7 thermal band) and below y 66.862, 10 mm from the L-FC body edge (A.8 tab Y row). The tab X bottom carries only
1 % logic series resistors and R106s, which sits beside F17 (A.8 r8 R106s placement).

**Retired 2026-11-12** (`decisions_2026-11-12/round2/dec2_parts_assembly_2026-11-12.md` item 1). All SMT parts are on
the top side, with one stencil and one reflow. The bottom side carries only through-hole bodies and tails (the D-41
TSW bodies, the J-TAP tails and the W-lead joints) and the L4 GND plane. The decouplers sit beside the VCC pin of their IC on the top side.

**D-19. Feet.** The FT1 and FT2 keep-outs (A.8) are bottom "footprints not allowed" rule areas; the foot outlines,
the FT1 long-axis tick and the FT2 fill-hole ring are on the bottom silkscreen. The FT2 fill hole is a 1.0 mm NPTH
with a 2.0 mm copper keep-out disc on all four layers (B.8 Mechanical).

**Retired 2026-11-12** (D-39, D-42). The plug-on CR has no feet and no fill hole. The CR rests on the 22-pin
connector stack of D-41, and no standoff is fitted in this round.

## 6. CR stack-up and power copper

**D-29. 5/5 mil rules and 1 oz outer copper (operator ruling 2026-11-11).** The operator stated the fab limits:
OSH Park 2-layer 6/6 mil, OSH Park 4-layer 5/5 mil, PCBWay 6/6 mil on 1 oz or 2 oz and 5/5 mil only on 1 oz. The CR
therefore uses `tools/pcb/fab_rules/fab_4layer_5mil_oshpark_pcbway.kicad_dru` (track and clearance 0.127 mm, all
other rules unchanged) and **1 oz outer copper**, which A.8 admits as the Copper fallback with power pours >= 2.0
mm wide. OSH Park 4-layer is 1 oz outer / 0.5 oz inner. The L3/L4 straps on 0.5 oz inner copper need a width
check for 2.41 A and 3.21 A: TODO(verify: IPC-2152 internal-layer chart). (**Amended 2026-11-13:** closed for the VCHGIN
strap at 2.41 A by operator ruling 2026-11-13 (Review 2/2), section 11 item 2; the VCHGOUT L3 strap check at 3.21 A
stays open there.) (**Amended 2026-11-13:** the VCHGOUT half of section 11 item 2 is closed by acceptance of the two
short F.Cu necks, operator ruling 2026-11-13 (design session, chat 2026-11-13: "Accept short necks").) The EIB stays at
6/6 mil.

**Amended 2026-11-12** (`decisions_2026-11-12/stackup_fabrules_decisions_2026-11-12.md` section 3). The CR is built at
OSH Park only, and a new OSH Park-only CR rule file replaces the shared OSH Park/PCBWay file:

- annular ring 0.1016 mm; via diameter >= 0.4572 mm; hole >= 0.254 mm; hole to hole 0.127 mm (OSH Park
  recommendation, no OSH Park minimum); copper to edge 0.381 mm; plated hole to inner copper 0.254 mm; mask web
  0.1016 mm;
- 0.6 / 0.3 mm is the only via size on the CR; the 0.50/0.25 and 0.46/0.25 mm vias are not allowed;
- the rule-file minimum track and clearance is 0.127 mm (the OSH Park 4-layer limit), but the router net-class default
  is 0.1524 / 0.1524 mm (6/6 mil); 0.127 mm is used only at local necks, such as the gaps between TSW pins;
- copper is 1 oz outer and 0.5 oz inner, unchanged.

The PCBWay minima drop out; a PCBWay order needs a fresh check. The IPC-2152 inner-layer check above applies only if
VCHGOUT or the VCHGIN strap uses L3 (D-21, D-22).

**D-30. CHG pads on the inner layers.** The 22 CHG pads keep 1.9 mm on L1 and L4 (A.8: pad >= 1.9 mm, the soldered
layers). On L2 and L3 a pin has no pad unless it connects there (`remove_unused_layers`, `keep_end_layers`), so
the L3 gap between two CHG holes grows from 0.64 mm to about 0.93 mm (2.54 mm pitch less the 1.1 mm drill and
2 x 0.254 mm plated-hole-to-inner-copper clearance). TODO(verify: that A.8's 1.9 mm pad rule targets the outer
layers only).

**Amended 2026-11-12** (`decisions_2026-11-12/stackup_fabrules_decisions_2026-11-12.md` section 3, P2). The rule
extends to every through-hole pad on the CR: the TSW pins, the W-lead pads and the J-TAP pins. Each pad keeps copper
only on the layers where it connects, zone ties included (for example GND to L2). The TSW pad and drill come from the
Samtec drawing (D-03), so the 1.9 mm pad and 1.1 mm drill of the r7 header are re-derived. TODO(verify: OSH Park)
whether non-functional pads are required on connector holes for barrel anchoring under repeated mating.

**D-20. Stack-up.** L1 signals and power pours, L2 (In1.Cu) a solid GND plane over the whole outline, L3 (In2.Cu)
signals and the VCHGIN strap, L4 (B.Cu) signals, the VCHGOUT strap and a GND pour (A.8 stack-up r7). Vias are
0.6 / 0.3 mm (TOOLCHAIN: 0.3 mm via drill). Every via is tented on both sides (A.8 L4 vias; r8 R106s rule). Inner-
layer pours keep 0.27 mm from plated holes (fab: 0.254 mm). A 0.40 mm router keep-out band runs inside the
outline (fab copper to edge 0.381 mm).

**Amended 2026-11-12** (`decisions_2026-11-12/stackup_fabrules_decisions_2026-11-12.md` sections 1 and 2; D-43). The
CR stack-up on the new outline is as follows:

- L1 (F.Cu): signals and power pours; all SMT parts.
- L2 (In1.Cu): a solid GND plane over the whole outline, unchanged.
- L3 (In2.Cu): signals; any inner power strap (D-21, D-22).
- L4 (B.Cu): a solid GND plane over the whole CR outline, facing the MB, with no signals and no power straps. It is
  stitched to L2 at a pitch of at most 5 mm and keeps its solder mask. The GND plane meets the MB only through the CHG
  GND pins, which keeps the A.6 single-point bond.
- Air gap: at least 1.5 mm from the lowest CR feature, THT tails included, to the tallest MB part below it. The basis
  counts CR bow only, not MB bow. **D-51 (operator ruling 2026-11-12):** the D-41 stack is taken to meet the air gap
  over every MB part except the power terminals, which the CR clears in plan. (**Superseded:** "TODO(measure:
  operator) the L-FC/L-BT height (5.0 mm family value against 6.5 mm for the sibling part) and the bodge part
  heights.")
- Sensitive-part window: the 0.1 % dividers, the comparator inputs and the references are placed preferably in
  y 30.8-66.86 (MB frame). The window is preferred, not hard; a part outside it is listed as an exemption.

A fallback with L4 signals in the middle band only, never in a shadow zone, was offered but not ruled; it needs a new
operator ruling. The 0.6 / 0.3 mm via and the tenting on both sides stay; the U101 exposed-pad vias are tented on L4
(D-40). The polyimide sheet over the 368 untented MB vias is retired (D-43), so the protection against the exposed MB
via rings rests on the air gap and the masked L4 only.

**D-21. VCHGIN (P-01).** A.8 asks for VCHGIN pours >= 2.5 mm wide and for VCHG-IN copper from pad 10 to U101
IN/IN_SYS <= 5 mm and solder-masked. The L1 corridor from pad 10 to the IN pins passes between the U101 pin-6 row
and the R102 N_UV pad (about 1.7 mm), and N_UV must cross it. The capture uses an L1 pour (`route_cr.VIN_L1`) in
parallel with an L3 strap from the pad-10 hole to the C102c via cluster and on to C102b (`route_cr.VIN_L3`, 2.8 mm
wide). The L3 strap also implements the A.8 C102b row (L3 join, via cluster at each end; five vias at C102b, two at
C102c). This strap is not to be cut back: it keeps C102b within its 2 nH loop budget.

**Kept, conditional (2026-11-12).** The rule stays. It is re-checked once the eFuse cluster is re-placed on the new
outline (D-09). An L3 strap keeps the IPC-2152 inner-layer check of D-29 open. (**Amended 2026-11-13:** the check is
closed for the VCHGIN strap by operator ruling 2026-11-13 (Review 2/2), section 11 item 2; the VCHGOUT L3 strap check
stays open there.) (**Amended 2026-11-13:** the VCHGOUT half of section 11 item 2 is closed by acceptance of the two
short F.Cu necks, operator ruling 2026-11-13 (design session, chat 2026-11-13: "Accept short necks").)

**Amended 2026-11-13 (D-56).** The L1 pour no longer reaches pad 10; the L3 strap is the only pad-10 path. It is
widened to a 3.645 mm narrowest section, joins pad 10 solid and has three vias at the C102c end; design-document row
H.25 checks it (2.57 A at 10 C against the 2.41 A basis on a curve fit of the IPC-2152 chart).

**Amended 2026-11-14 (REVIEW CRL-1).** The A.8 length rule "VCHG-IN copper from pad 10 to U101 IN/IN_SYS <= 5 mm"
is not met; D-56 records the measured path of about 7.3 mm and its exemption.

**D-22. VCHGOUT (P-02).** VCHGOUT runs as one L1 pour from OUT 17/18 over C103 and the D103 cathode, and from
there below the D103 anode to W1 through a 2.8 mm corridor (`route_cr.VOUT_L1`, box x 29.10-36.80, y 60.00-63.80),
with no part on the top of that belt. Four vias under the cathode join a parallel L4 strap to W1. The earlier L3
VCHGOUT strap is retired, which frees L3 for signals.

**Re-derive on the new outline (2026-11-12)** (`decisions_2026-11-12/stackup_fabrules_decisions_2026-11-12.md`
section 1, "Designer's call"). The 2.8 mm corridor and the L4 strap existed because of the r6 +y edge and the r7 W1
position. The L4 strap conflicts with the solid L4 GND plane (D-20) and is withdrawn. The design owner re-derives the
VCHGOUT path on L1 and, if needed, on L3. An L1-only path on 1 oz copper avoids the open IPC-2152 inner-layer check;
an L3 parallel keeps it open (D-29).

**D-23. VCHG and the GND star.** VCHG joins pins 18/19 and W3 with an L1 pour. GND joins W4 and pins 14/15 with an
L1 pour, and W2 with a local L1 pour; L2 (solid) and the L4 pour join every GND item.

**Kept (2026-11-12).** W3 and W4 stay at the pin columns. On the new outline L4 is a solid plane (D-20), not a pour.

**D-33. Power vias as placement keep-outs.** The 11 fixed power vias of `route_cr.PRE_VIAS` are keep-outs for parts
on both sides (`layout_cr.PRE_VIA_KO`), so no bottom resistor can land on a through via.

**Amended 2026-11-12.** The mechanism stays. The via list `route_cr.PRE_VIAS` encodes the r7 power geometry and is
rebuilt with D-21 and D-22. With no bottom part, the keep-out applies to the top side only.

## 7. EIB placement and routing (A.9)

**D-25. Outline (P-05).** A.9 gives 36.0 x 24.0 mm with two M3 holes at diagonally opposite corners 3.5 mm in, each
with a 7 mm copper-free keep-out, and the E1-E8 row along the long edge that faces the EVM (A.5: 7 mm off the EVM
right edge). The E row spans 27.94 mm between its outer centres; on the E-row side one hole keep-out reaches 7.0 mm,
so the row needs 37.33 mm of long edge. The EIB is therefore **24.0 x 38.0 mm**. The E column is at x 2.0 mm (E8 at
y 36.04 to E6 at y 8.10); the holes are at (3.5, 3.5) and (20.5, 34.5).

**D-26. E-pad order and isolation.** The E pads follow the A.9 r6 order top to bottom: E8, (empty), E3, E4, E2,
(empty), E7, (empty), E1, (empty), E5, E6, at 2.54 mm pitch; the empty positions carry no copper.

**D-27. E-side parts.** R276 (E1) and R275 (E7) sit at their pads, 3.2 mm centre to centre (A.9 REGN parts row;
H.23(k)). U203 sits near E4 and U204 near E6 (A.9 Analog row); Q201-Q203 sit near E2/E3; U201/U202 sit mid-board on
the signal path from J201, which is on the opposite long edge (A.9 J201 row). The packer keeps a 0.7 mm routing
channel between courtyards.

**Amended 2026-11-12** (D-49). The copper is unchanged. U203, U204, C203, C204 and R258-R265 are DNP, and the E4 and
E6 leads are not fitted.

**D-28. EIB routing and ground.** Signals run on both layers (0.2 mm tracks and clearance, 0.6/0.3 mm vias),
routed by Freerouting in three rounds. The AGND pour on the bottom layer is added after routing and joins E8 (A.9
Ground row); R273 links the J201 GND pins (`GND_J`) to AGND. (**Amended 2026-11-13** (D-63): a matching AGND pour is
added on the top layer, and AGND stitching vias tie the two pours.) (**Corrected 2026-11-14** (D-70, REVIEW
EIL-0): both AGND zones declare a 0.2 mm local clearance, but the fill follows the 0.1524 mm `fab_clearance`
rule of the 2-layer rule file; the J201 gaps of 0.1529-0.1572 mm measured before D-70 agree with 0.1524 mm
(`update_2026-11-14/notes_eib.md` section 2.1). The 0.2 mm figure of this entry applies to tracks; the
pour-to-pad clearance is 0.1524 mm except where D-68 and D-70 set 0.5 mm.)

**D-63. Straightened EIB tracks, a top-layer AGND pour and AGND stitching vias (operator request 2026-11-13).** The
operator asked for the trace-bend cleanup and ground stitching on the EIB, the EIB counterpart of D-61, followed by
a new fabrication package. The finish ran on the routed D-28 board in this order:

1. `tools/pcb/corridor_route/straighten.py --clear 0.2` (the D-28 clearance), twice. The two runs reduced the
   unlocked signal track segments from 479 to 418 (421 after the first run) and the track length from 608.4 mm to
   604.0 mm; the second run changed 2 nets and converged (`eib/straighten.md`).
2. A top-layer AGND pour, `AGND_L1_pour`, with the outline, priority, clearance and thermal settings of the bottom
   pour (`gen/route_eib.py` `gnd_pours()`). Without it, an AGND via has no top-layer copper to tie, so stitching
   requires the second pour. The pour is the same net, so no via touches `GND_J`, R273 stays the only `GND_J`-to-AGND
   path and AGND still joins the EVM only at E8 (A.9 Ground row).
3. `tools/pcb/corridor_route/stitch_gaps.py --net /AGND --clear 0.2 --hole-gap 0.28` on F.Cu and then on B.Cu, with
   the island removal of the top pour off during the run so that every top island receives a via where a legal site
   exists. The runs added 42 and 2 vias (AGND vias 5 to 49; `eib/stitch_gaps.md`). The limit is the CR D-20 value,
   3.54 mm (a 5 mm square pitch); no EIB design row sets a stitching limit. The largest remaining distance is 4.99 mm
   on F.Cu and 4.72 mm on B.Cu, both in the J201 pad field (x 18-23 mm, y 28-32 mm, KiCad frame), where no legal via
   site exists.
4. Island removal of the top pour restored to the bottom pour's mode (isolated islands removed), zones refilled.

The top pour fills 458.0 mm² and the bottom pour 577.7 mm², each in 6 pieces. The bottom pour previously lost the
regions enclosed by bottom-layer tracks as unconnected islands; the stitching vias now tie those regions. No via lies
on an SMD pad or its mask opening (smallest gap 0.044 mm, R270.2). The new vias are tented, so the masks, silkscreens,
paste layers, outline and NPTH drill of the package are identical to `fab/eib_2026-11-11`; both copper layers and the
PTH drill differ (`fab/eib_2026-11-13/README.md` section 6).

Tool fix found in this step: `stitch_gaps.py` read keep-out rule areas from `BOARD.Zones()` only, which omits
footprint-owned zones, and placed 4 vias inside the H1 and H2 mounting-hole keep-outs (DRC `items_not_allowed`).
The tool now also reads footprint zones, and `straighten.py` received the same change for track keep-outs (no EIB
track was affected). The board in the repository was produced with the corrected tool. Reversal: restore
`eib/eib.kicad_pcb` and `gen/route_eib.py` from the commit before D-63 and run `gen/export.sh eib 2026-11-13` again.

**D-64. EIB reference designators on the top silkscreen (operator request 2026-11-13).** The D-12a reversal of
2026-11-12 put the reference designators on the CR silkscreen only; all 48 EIB reference fields stayed hidden, so the
EIB top silkscreen carried no part labels. The 38 reference fields of the passives, transistors, ICs and J201 were made
visible on F.Silkscreen at 1.0 / 0.15 mm, and `gen/silk_refs.py` (the D-59 tool) placed them. H1 and H2 stay hidden,
as on the CR mounting holes. E1-E8 stay hidden on the top, because their labels are on B.Silkscreen (D-12a). Result:
31 references on F.Silkscreen (9 of them over another part's courtyard) and 7 on F.Fab, which had no clear position:
C202, C203, R253, R266, R274, R275 and U201 (`eib/silk_refs.md`). Copper, nets and footprint positions do not change;
of the package Gerbers, only `eib-F_Silkscreen.gto` differs from the D-63 export. The board text "EIB r8 2026-11-11"
is unchanged. Reversal: restore `eib/eib.kicad_pcb` from the commit before D-64 and run `gen/export.sh eib
2026-11-13` and `gen/fab_readme.py eib 2026-11-13 fab/eib_2026-11-11` again.

**Amended 2026-11-14 (D-74, D-78).** `gen/eib_silk_refs_r2.py` replaces the D-64 placement, and `eib/silk_refs.md`
holds its table. The board text "EIB r8 2026-11-11" is now "EIB r8 2026-11-14".

## 8. CR routing attempts

This section records the routing on the r7 outline. It is kept as history; the routing on the new outline is the
route-race of D-50.

**D-24. Methods and results.** The table lists every CR signal-routing attempt. The CR has 95 routable signal
nets after tiers 1 and 2 (GND, VCHGIN, VCHGOUT and VCHG are pours).

| # | Method | Rules | Placement | Result |
|---|---|---|---|---|
| 1 | Freerouting 2.5.0, 40 passes | 0.20 / 0.20 mm | first packer placement | 192 of 335 connections unrouted |
| 2 | Freerouting 2.5.0, 30 passes | 0.16 / 0.16 mm | same | 181 unrouted, 32 router violations |
| 3 | Finishing router (grid A*, net-level rip-up) on result 2 | 0.16 / 0.16 mm | same | 165 -> 102 -> about 100 unconnected; oscillates |
| 4 | PathFinder (negotiated congestion), 0.1 mm grid | 0.16 / 0.16 mm | U101 escape not yet opened | 72-79 of 99 nets in conflict, 16 nets sealed |
| 5 | PathFinder, 0.1 mm grid | 0.127 / 0.127 mm (D-29), inner pads removed (D-30) | U101 shifted, tier 1, fixes D-22/D-33 | 2 nets sealed (tab Y gate inputs) |
| 6 | PathFinder, 0.1 mm grid, 60 iterations | 0.127 / 0.127 mm | tiers 1 and 2, A.8 tab Y set | 0 sealed; conflicts 79 -> 47 at iteration 35 -> 53 at iteration 60 |
| 7 | PathFinder, 0.05 mm grid, stopped at iteration 15 | 0.127 / 0.127 mm | same as 6 | conflicts 73 -> 29 at iteration 11, 30-35 at iterations 12-15 |

Attempt 6 is saved as `archive_r7_outline/cr/attempts/cr_pathfinder_0p1mm_partial.kicad_pcb` with its DRC report; it is a reference,
not a deliverable (516 clearance violations from the remaining conflicts).

**D-34. Routing-study placement variants, round 1.** The routing study (route-race skill, request CR1-03) found pad
R147.2 (/QUAL) enclosed on three sides by the VCHGOUT L4 strap (`route_cr.VOUT_IN`, D-22) and unreachable on an
empty board. The packer did not know the strap outline. The environment variable `CR_PLACE_VARIANT` selects two
variants; with the variable unset, the generator builds the base placement unchanged.

- Variant A (`archive_r7_outline/cr/variants/r1_A/`): the strap outline grown by 0.15 mm is a bottom keep-out for the packer. The strap
  shape is unchanged (D-22 holds). Seven bottom parts move, R147 to (30.05, 66.25) and R107 to tab X; no B.Cu SMD
  pad lies within 0.381 mm of the strap outline.
- Variant B (`archive_r7_outline/cr/variants/r1_B/`): A plus courtyards of C129, R107, R122, R126, R128, R129, R147, R190 and R191 grown
  by 0.225 mm (a row pitch of about 1.75 mm, `layout_cr.CRT_GROW`). The packer disperses the grid rather than keeping
  it in place, and 30 bottom parts move.

Both variants give ERC 0, DRC equal to the base (200 unconnected, 4 starved thermals, 2 silkscreen items) and 0 FAIL
in the constraint check. Each folder holds a `placement_diff.json` against commit `5ddc21a`.

Round 2 measured both variants under the binding divider-top plan. A made 169.0 connections on average and B made
169.2, against 166.2 for the base; neither gain is separated at four seeds. The strap keep-out of variant A is now the
default placement because it removes a real defect (R147.2 unreachable). `CR_PLACE_VARIANT=BASE0` rebuilds the
`5ddc21a` placement. The grid growth of variant B is not adopted.

**Retired 2026-11-12** (D-20, D-22, D-44). The CR has no bottom part, and the VCHGOUT L4 strap is withdrawn, so the
strap keep-out has nothing to protect. The variants are archived in `archive_r7_outline/cr/variants/`.

**D-35. Scope of the divider-top rule.** A.8 Analog requires the divider tops R102, R109, R111 and R114 to be at least
2 mm from any logic trace, without a layer scope. The rule binds logic-net copper on F.Cu and logic-net vias of any
span within 2.0 mm of each part. Logic tracks on In2.Cu and B.Cu may pass under the parts, because L2 is a solid GND
plane between them and F.Cu and the via ban keeps L2 free of antipads in the zone. /GND, /3V3 and the analog band
nets are not logic nets. The routing study measures this form and the all-layer form.

The placement itself puts logic pads inside the zone. Two groups are treated differently:

- Pins of the A.8-fixed parts are exempt, each with its pad and one F.Cu escape that leaves the zone with no via
  inside it. These pins are J1.7 /SCL, J1.8 /SDA, J101.7 /ILIM_REL_A, J101.11 /ILIM_SENSE, J101.13 /CE_SENSE,
  U102.1 /H1 and U103.1 /UVB.
- Three pads of packer-placed parts are also inside the zone: U109.1 /H1 (0.41 mm), U109.3 /RGN_ON (0.40 mm) and
  U105.5 /P5N (0.58 mm).

A placement variant tried to keep packer-placed top logic courtyards out of the zone (R109/R111/R114 pinned, zone
buffer 1.82 mm). It left U111 unplaced at the first attempt. With the tab Y gate fallback moved after the top ICs, it
left U105 and U118 unplaced, so the variant was withdrawn. The three pads therefore carry the same interim exemption
(pad plus one escape) until the operator rules. The constraint check reports them in the row "D-35 packer-placed logic
ICs", and its row "Every part inside the outline" catches a part that the packer parks off the board. The conflict report of attempt 4 showed
the conflicts spread over the whole interior (x 25-45, y 40-65), not at one point: the CR lacks routing capacity
for the 6/6-mil rules, and the 0.05 mm grid (whose clearance model is about 10 % conservative, against 20 % at
0.1 mm) gives the best trajectory so far.

**Re-derive on the new outline (2026-11-12)** (D-36, D-47, D-49). The rule stays as the all-layer optimization metric
of D-36. Several exempt pins no longer exist: U109 is removed (U109.1 /H1 and U109.3 /RGN_ON), the net /RGN_ON is
removed with U121, and J101.11 and J101.13 are NC (/ILIM_SENSE and /CE_SENSE are removed). The remaining exemptions
(J1.7, J1.8, J101.7, U102.1, U103.1 and U105.5, whose U105 pin assignment may change with D-47) are re-evaluated
after the placement on the new outline. On the new outline L4 carries no logic copper (D-20).

**D-36. Operator rulings of 2026-11-12.** The operator approved decisions 1 to 6 of `MORNING_REVIEW_2026-11-12.md`
(tier 3 DNP, the comparator preference, the VR-1 name, the D-35 scope and exemptions, and the strap keep-out as the
default placement). The operator also ruled as follows:

- **Via in pad.** Plain unfilled vias inside SMD pads are acceptable. Only filled and capped vias are excluded,
  because OSH Park does not offer them. This replaces the strict reading of D-20 and VR-1 recorded in `HANDOFF.md`
  section 8 (section 7 before the 2026-11-12 update).
- **Divider-top rule.** The rule binds on all layers; this replaces the F.Cu-plus-vias scope of D-35. The rule is
  an optimization metric, not a gate: the metric is the length of logic-net copper that runs parallel to analog-net
  copper inside the 2.0 mm zone, and a lower value is better. Exemptions are acceptable where no other route exists.
  The D-35 exemptions, including U105.5, U109.1 and U109.3, are approved.
- **Finish method.** The operator routes the CR interactively in `cr/interactive/`. The start board is the adopted
  placement with the round 2 routes of plan `r2_A`, seed 1, and the scripted GND plane vias (173 of 199 signal
  connections, 31 GND connections open).

**Amended 2026-11-12.** The finish method and its start board are **retired**: the placement changes with the new
outline, and the routing on the new outline is the full route-race of D-50. The interactive project is superseded and is
archived at `archive_r7_outline/cr/interactive/`. The via-in-pad ruling is not revoked; D-37 makes it
the fallback. The divider-top ruling stays in force (D-35).

**Amended 2026-11-16 (D-94).** The /CHG_ARM exemption at R114 is an operator ruling on comparative grounds. A
zone-free route exists, so the "no other route exists" test of this entry is not met for that net.

**D-37. Via-in-pad order of use (operator ruling 2026-11-12, with the CR outline change request).** The operator
assembles the CR by stencil, solder paste and reflow. An unfilled via in a pasted pad can draw solder down the barrel
and starve the joint. The routing on the new outline therefore proceeds in this order:

1. Route with no via on an SMD pad or in its mask opening.
2. Only if that attempt fails on the new outline, use plain unfilled vias in SMD pads (D-36), and list each such via
   for operator review.

Filled and capped vias stay excluded. D-36 is not revoked; it becomes the fallback. The change request is
`docs/reviews/cr_routing_2026-11-12/CR_OUTLINE_CHANGE_REQUEST_2026-11-12.md` in the main checkout, section 5,
item 7.

**Amended 2026-11-12** (D-40; `decisions_2026-11-12/stackup_fabrules_decisions_2026-11-12.md` section 5). The nine
U101 exposed-pad thermal vias are exempt from D-37; they use window-pane stencil apertures and L4 tenting. The only
via is 0.6 / 0.3 mm (D-29), so a fallback in-pad via cannot use a smaller size. A fallback in-pad via wicks solder
toward L4; if one is used, 0.3 mm of bump is counted in the D-20 air-gap budget, and the D-20 tenting cannot hold on
the pad side of that via.

**D-38. Tap T22 and the pack-OV permit removed (operator ruling 2026-11-12; design-doc revision r8-17).** A 30 AWG
wire cannot practically be soldered to the outer toe of BQ29200 pin 8 (DRB pad 0.35 mm wide, 0.65 mm pitch to VDD).
The operator accepted the safety downgrade: "Let's go with option 2 and use firmware for pack-voltage protection. The
safety downgrade is acceptable in this case. The firmware can read the battery voltage directly anyways as an OVP
signal to disable charging." The following changes apply:

- Pad F08, R178, D108, R179, U123, U122 and the decouplers C134/C135 are removed from the netlist. ARM_OK drives
  both U114 inputs directly, as before r6. The nets T22_BAL, N_BAL, OVN and ARM_OKP are gone.
- Pack-voltage protection rests on firmware: FR-46 read-back, the slot-5 verify, FR-47(a) (BT_VOLTAGE above
  LIMIT_V_BATT_MAX 8.5 V drops P5; a firmware requirement, not yet implemented) and the OV_BATT fault.
- Charging no longer needs the balance lead J-BL.
- The entries above that name F08, T22_BAL, D108 or U123 (the tap map, the fixed pads, D-12, the analog interior
  list and row P-04) describe the r7 layout. D-12's band corner loses its D108 user; it remains a candidate corner
  for the BAV199 clamps D104-D106 until the new outline is placed.

The netlist after D-38 has 145 CR parts; ERC is 0 and the schematic matches `cr/cr.net`. `cr/cr.kicad_pcb` and the
boards under `archive_r7_outline/cr/interactive/`, `archive_r7_outline/cr/variants/` and `archive_r7_outline/cr/attempts/` are stale against this netlist until the next
layout build.

The 2026-11-12 decisions of D-39 to D-50 follow. Each one is recorded in `decisions_2026-11-12/` (first round) or
`decisions_2026-11-12/round2/` (second round); `decisions_2026-11-12/round2/orchestrator_digest.md` is the one-page
digest, and its reconciliation notes bind where a record disagrees.

**D-39. Plug-on outline and assembly (operator ruling 2026-11-12, change request).**

- Decision: the CR is a removable board that plugs onto the MB CHG holes. Its outline is the rectangle x 18.584-67,
  y 7-94 in the MB frame (48.416 x 87 mm, 4212 mm²). The CR is assembled by stencil, solder paste and reflow oven;
  through-hole parts are hand-soldered last. Chip size is at least 0402 (0603 preferred) (r9-3 / D-44: no 0402 part remains; every chip passive is 0603 or larger), and IC pitch is at least
  0.65 mm, with 0.5 mm only by operator approval (D-40).
- Reason: the r7 board did not route (section 8). The new outline gives about 3 times the area. The re-assessment
  books the current parts at 24 % of one side and estimates 12.9 % routing utilisation with L4 as a solid GND layer.
  These are geometric estimates; a routed run on a regenerated placement is the gate.
- Consequence: the r7 outline V1-V11, its chamfer, the tabs, the feet and the polyimide sheet retire (D-02, D-16,
  D-19, D-43). Every construct that encodes r7 geometry in `gen/layout_cr.py`, `gen/route_cr.py`,
  `gen/check_constraints.py`, `gen/fplib.py`, `gen/fpmap.py`, `gen/netlist.py`, `gen/fab_readme.py` and
  `gen/pcbbuild.py` is replaced (`outline_change_2026-11-12/retired.md` section 4). Both boost switching nodes, both
  inductors and REG-5V now lie under the CR (D-11, D-20). Record: `OUTLINE_CHANGE_REASSESSMENT_2026-11-12.md`;
  `docs/reviews/cr_routing_2026-11-12/CR_OUTLINE_CHANGE_REQUEST_2026-11-12.md` (main checkout). **Closed by D-51
  (operator ruling 2026-11-12):** the section 6 survey of the change request is closed; the only height requirement
  kept is the -x terminal clearance, which holds with a gap of at least 2.200 mm. (**Superseded:** "The section 6
  survey of the change request stays open: the L-FC and L-BT heights, the bodge parts and their heights, the J-BT and
  J-BL face positions, and whether the C1-BT, C1-FC, CBL2, RB2 and RB3 bodies clear x 18.584.")
  **Amended 2026-11-13 (D-60):** the rectangle stays the placement frame; after routing, the board is trimmed to the
  D-60 convex outline (2241.6 mm²) inside it, with the -x edge kept. **Amended 2026-11-13 (D-62):** the trimmed outline
  is the D-62 outline of 10 filleted corners (2327.7 mm²), with the -x vertices exactly on x 18.584.

**D-40. U101 package (operator ruling 2026-11-12).**

- Decision: U101 stays TPS26630RGER (VQFN-24, 0.5 mm pitch). It is the one approved 0.5 mm exception. Its nine
  exposed-pad thermal vias are exempt from D-37, with window-pane stencil apertures and L4 tenting.
- Reason: no leaded TPS26630 exists. The HTSSOP-20 TPS26631 has a different fast-trip (3 x I_OL), which would require
  B.4, H.5 and the B.8 pin map to be re-derived.
- Consequence: the D-03 U101 footprint row stays. The stencil apertures for the exposed pad are
  TODO(verify: SLVSE94G section 11 layout example). Record: `DESIGN_STATE_2026-11-12.md` Table 1 (U101 session
  report); `OUTLINE_CHANGE_REASSESSMENT_2026-11-12.md` section 7.1.

**D-41. Mating connector and stack (operator ruling 2026-11-12).**

- Decision: a Samtec 2-piece stack. The MB carries SSQ-110-01-L-S (column x 45.998, pins 1-10) and SSQ-112-01-L-S
  (column x 20.998, pins 11-22) sockets. (**Amended 2026-11-15, REVIEW R2-INT-4:** the ordered and PM4 sockets are
  SSQ-110-01-G-S and SSQ-112-01-G-S, -G plating (`bom_2026-11-14/digikey_import.csv`); the -L-S part numbers of this
  entry are the 2026-11-12 record.) The CR carries TSW-110-07-L-S and TSW-112-07-L-S pins, with the bodies on the
  CR underside and the tails soldered from the CR top. All 22 positions are populated. The stack has a hard stop: the
  TSW body seats on the SSQ face, so the CR underside stands 11.05 mm above the MB top and the CR top at 12.65 mm.
  The CR carries no mechanical key.
- Reason: the 3-piece alternative had no defined seat and a 3 A contact rating, against at least 3 A required at CHG
  pin 10.
  TSW mated with SSQ is rated 6.3 A per pin with two positions powered (Samtec F-226). A CR rotated by 180 degrees
  lands on the J-BL, J-FC and J-BT terminal blocks (21.70 mm) before the pins engage at 16.89 mm, so the blocks key the
  board. **Amended 2026-11-13 (D-60):** on the trimmed outline, the rotated CR lands on J-BL (7.73 mm of x overlap) and
  J-FC (7.63 mm) at the two ends, not on J-BT; the +x key ear keeps this overlap. **Amended 2026-11-13 (D-62):** on the
  D-62 outline, the rotated CR lands on J-BL (7.73 mm) and J-FC (7.73 mm). (**Superseded:** "J-FC (7.63 mm)".)
- Consequence: the engagement-start height (seated underside plus post insertion) must stay below 21.70 mm; a taller
  stack needs a real key. The sockets on the MB keep the live MB pins touch-safe with the CR removed. The assembly
  order is: solder the SSQ sockets to the MB; plug the TSW strips in; set the reflowed CR on their bodies; solder the
  TSW tails from the CR top; unplug and inspect. The MB underside at both CHG columns is clear (operator check).
  The ordering BOM changes the TSW rows from -G to -L plating and adds the two SSQ rows. The 12.0 mm stack and the
  keying-blank options of the re-assessment are retired. The derating for four powered pins at pins 14/15/18/19
  (1.93 A each) is TODO(verify: Samtec derating). Record: `decisions_2026-11-12/cr_decision_mating_connector_2026-11-12.md`.
- **Amended 2026-11-13** (operator ruling 2026-11-13 (Review 1/2: J102, J1-TSW, W6-W7 (connector and lead-pad
  geometry), local_923ffa1c-f985-43ad-8510-7faea2e5f5d7, chat 2026-11-13)): the CR J1 TSW-110/112-07-L-S footprint is
  approved as placed. The operator supplied the Samtec drawing ("Here is the Samtec datasheet"): the "Recommended P.C.
  Board Layout for (X)TSW Single, Double & Triple (Thru-Hole & Right Angle)", Rev A, file
  TSW-XXX-XX-X-X-XX-XXX-FOOTPRINT. It gives a hole of .040 in [1.02 mm] DIA TYP at a pitch of .100 in [2.54 mm]; it
  states no tolerance, no drilled or finished reading and no pad size. The operator ruled "Keep 1.1 mm" for the drill.
  The 1.1 mm drill is 0.08 mm over the drawing value, kept for plug-in alignment: the 0.64 mm square post has about
  0.10 mm of corner clearance per side, against about 0.06 mm at 1.02 mm. To the request to confirm the 11.05 mm stack
  of this entry and the 1.9 mm CHG pad (D-03, D-30), the operator answered "Confirm both". The heights were not
  checked against a Samtec print in the review session; the 11.05 mm and 12.65 mm figures rest on the operator's
  confirmation of this record. The drilled-versus-finished reading of the OSH Park drill stays with section 11 item 5, and the four-pin
  derating stays open as section 11 item 15. The footprint description still reads "pad/drill PLACEHOLDER
  TODO(verify: Samtec TSW drawing)"; it changes at the next footprint-library regeneration. Section 11 items 12 and 14
  are closed.

**D-42. Standoffs (operator ruling 2026-11-12).**

- Decision: no standoffs in this round. The CR is held by the friction fit of the 22 pins and rests on the TSW bodies
  at the D-41 hard stop.
- Reason: the operator judged the CR mass to be no issue for the friction fit. A later support, such as a 3D-printed
  part, is the operator's remedy if one is needed.
- Consequence: the CR has no mounting hole. The re-run site search (NW, SE, NE and an SW rest foot) is kept for a
  later round; it found the candidate SO2 free radius at 2.49 mm with the REG-5V body modelled in full. Record:
  `decisions_2026-11-12/dec_standoffs_2026-11-12.md`. **Amended 2026-11-13 (D-60):** the CR now has four 6-32 holes
  that hold a 3D-printed support; there are still no standoffs on the MB. (**Superseded:** "the CR has no mounting
  hole".)

**D-43. Polyimide sheet and thermocouple retired (operator ruling 2026-11-12).**

- Decision: no polyimide sheet and no local Kapton over the 368 untented MB vias. The thermocouple on the MB VBT trace
  is removed.
- Reason: the operator chose "Retire entirely" for the sheet, against local tape and a full film. The operator judged
  the thermocouple an unnecessary complication for the amount of risk mitigation.
- Consequence: the protection against the exposed MB via rings rests on the air gap and the masked L4 only (D-20).
  T-F-16 is retired (operator ruling 2026-11-12, "retire T-F-16"; design document r9-5, J.1 item 25): the MB VBT
  trace rise under the CR, the IPC-2221 10 C rise at 3.21 A on 1 oz, is accepted unmeasured (superseded: "T-F-16 needs a
  new method or retirement (design owner)"). Kapton uses unrelated to the sheet (the pin 7-10 tip patch)
  are not retired by this ruling. Record: `decisions_2026-11-12/stackup_fabrules_decisions_2026-11-12.md` sections 2
  and 3a.

**D-44. All SMT on the top side; package rules (operator ruling 2026-11-12).**

- Decision: every SMT part is on the top side, with one stencil and one reflow, and there is no bottom fallback. Six
  0402 parts become 0603: R101 CRCW06038K06FKEA, R103 TNPW060366K5BEEA, R104 TNPW060349K9BEEA, R105 CRCW060327K4FKEA,
  R106s CRCW06031K00FKEA and C101 GRM188R71H223KA01D. Every single-gate logic part is in SOT-23 (DBV); a part with two
  or more sections in use stays in DCT (0.65 mm).
- Reason: one SMT side gives one stencil and one reflow pass, and the new outline has the area. DBV eases paste
  printing, although DCK and DCT already meet the 0.65 mm minimum.
- Consequence: D-17, D-18, D-19 and D-32 retire. Under the D-47 mapping, U107 becomes SN74LVC1G11DBVR; U105
  (SN74LVC3G04, two sections), U106 (SN74LVC2G32, both sections), U110 (SN74LVC2G32) and U118 (SN74LVC2G08) stay
  DCT. The record's "U106 to SN74LVC1G32DBVR" row is void, because U106 now uses both sections (D-47). If a
  regenerated placement does not fit on the top side, the design owner escalates to the operator. The area booking is
  recomputed with the reduced list, the 0603 and DBV parts and the 0.25 mm courtyards. TODO(verify: Murata) for
  GRM188R71H223KA01D; the DBV pinout of U107 is closed by SCES487I Table 4-1 (section 11 item 18; superseded
  2026-11-14, REVIEW LOG-4: "TODO(verify: TI Pin Functions tables) for the DBV pinout of U107"). Record:
  `decisions_2026-11-12/round2/dec2_parts_assembly_2026-11-12.md`.

**D-45. Lead termination (operator ruling 2026-11-12).**

- Decision: the taps go to one CR connector, J-TAP (D-46). The W leads (W1-W4, W6/W7) stay soldered on the CR as
  through-hole leads and unplug at the existing EVM terminals. W5 is an IDC ribbon and is already removable.
- Reason: the CR must come off the MB without desoldering. The EVM terminals already give a W-lead disconnect.
- Consequence: no W-lead connector is added to the CR. The fixed W1/W2 build length of 0.30 m ± 10 mm (D-F3) stays a
  spike-safety limit. The W pad positions are re-derived on the new outline (D-08). Record: `DESIGN_STATE_2026-11-12.md`
  Table 1 (lead session); `outline_change_2026-11-12/leads.md`.
- Generator (2026-11-12): W6 and W7 use the plated through-hole placeholder footprints
  `LeadPads_PTH_1x02_D1.0mm_Pad1.8mm_P2.54mm_Placeholder` and `LeadPads_PTH_1x03_D1.0mm_Pad1.8mm_P2.54mm_Placeholder`
  (`gen/fpmap.py` WPTH_2 / WPTH_3, `gen/fplib.py` `lead_pth_n`). The geometry is the A.9 E-pad (1.0 mm hole, 1.8 mm
  pad) at 2.54 mm pitch with a 0.25 mm courtyard; hole, pad and pitch are closed by the 2026-11-13 amendment below
  (the names keep the `_Placeholder` suffix). (**Superseded 2026-11-13:** "hole, pad and pitch are TODO(verify: 26 AWG
  (W6) / 28 AWG (W7) conductor and insulation OD), as in B.8".) (**Superseded:** the r8 SMT pads
  `LeadPads_SMD_1x0n_1.2x1.5mm_P2.0mm`.)
- **Amended 2026-11-13** (operator ruling 2026-11-13 (Review 1/2: J102, J1-TSW, W6-W7 (connector and lead-pad
  geometry), local_923ffa1c-f985-43ad-8510-7faea2e5f5d7, chat 2026-11-13)): the placeholder status of the W6 and W7
  lead pads is closed. The proposal kept the 1.0 mm hole, the 1.8 mm pad and the 2.54 mm pitch for both footprints and
  kept the footprint names with the `_Placeholder` suffix; the operator answered "Approve, close it". The wires are
  those of the ordering BOM: W6 is Alpha Wire 3049, 26 AWG stranded PVC, WH005 white (/TS_EXT) and BL005 blue (/GND)
  as a twisted pair; W7 is a Jonard 28 AWG Kynar triple (R28R, R28BLK, R28Y). The insulation OD was not read, so the
  ordering BOM keeps its TODO items (ordering item 13).

**D-46. Tap connector J-TAP (operator ruling 2026-11-12).**

- Decision: J-TAP is a Molex Micro-Fit 3.0 dual-row 2 x 5 through-hole header (3.00 mm) on the CR, hand-soldered last.
  All 10 positions are used. The cable is the Molex assembly 2147561101; its far ends take the operator's own .100"
  crimp terminals. (**Superseded 2026-11-13:** "the Molex assembly 2147581101"; see the 2026-11-13 amendment below.)
  The cavity map (r9-13) is:

  | Row | Col 1 | Col 2 | Col 3 | Col 4 | Col 5 |
  |---|---|---|---|---|---|
  | A | T2 | T17 | T17r | T5 | T13 |
  | B | T6 | T1 | T7b | T16 | T10 |

  Superseded in r9-13: row A T1 T7b T17r T5 T13, row B T6 T2 T17 T16 T10 (the map of the 2026-11-12 tap-connector
  decision, kept unchanged by r9-12).

- Reason: ten conductors remain after the tap review (D-47). Cable assemblies are in stock for 2 x 5. The map keeps
  T5, T6 and T10 pairwise non-adjacent, including the opposite-row pin, and keeps T1 and T2 away from T5 and T10. A
  search of all 1664 feasible 2 x 5 maps found none with fewer than two severity-2 pairs (T5-T13 and T13-T10).
- Consequence: the F01-F24 pads, the tab X grid and the low-row pads retire (D-05, D-08). The Micro-Fit polarization
  is required, because a 180-degree rotation of the plug puts T6 on T13; only a column reversal puts T6 on T10
  (design change row r9-14). (**Superseded 2026-11-13, D-55:** "a 180-degree flip puts T6 on T10".) The design owner
  places J-TAP under these constraints:
  - on the +x side of the CR, because every far end lies at +x;
  - with the T2 run short to C-D2 (x 67.4-69.7, y 69.9);
  - with every run inside its A.4 maximum: T1 0.15 m to C-D6 at (97.8, 17.9), T2 0.10 m, J1 taps 0.12 m, J2 taps
    0.15 m;
  - with finger access to the latch;
  - with the THT tails inside the 11.05 mm CR-to-MB gap and the D-20 air gap.

  A PM step unplugs the tap plug before the CR is lifted. T-F-12 becomes a cavity-to-cavity check on the mated
  harness, and the R175 bypass check stays. T1/T7b and T17/T17r are twisted by hand. Open items:
  TODO(verify: Molex 2147561101) the wire gauge and insulation; the wire gauge against the R170/R171 joints at C-D6 and
  C-D2 (A.4 assumed 26 AWG). (**Superseded 2026-11-13:** "TODO(verify: Molex 2147581101) the circuits, wire gauge,
  length and housing; TODO(verify: Molex 43045 header and 43025 housing drawings) the header P/N, orientation, pegs and
  the physical pin numbers of the cavity map"; see the 2026-11-13 amendment below.) **Accepted by the operator
  (2026-11-12):** T5 (A4) is diagonal to T10 (B5). The gate rule (T5, T6 and T10 pairwise non-adjacent, the opposite row included) is
  met; the recommended diagonal separation is not. The r9-13 re-map keeps this diagonal. Record:
  `decisions_2026-11-12/round2/tap_connector/dec_tap_connector_2026-11-12.md`;
  `decisions_2026-11-12/round2/permit_gate_decisions_2026-11-12.md` decision 5.
- r9-12 (audit run 002 SR-SR-01; check-in 2 ruling R1, 2026-11-12, a default the operator may override), superseded in
  r9-13: the cavity map is unchanged. On the diagonals, T6-T7b (the Teensy 3V3 to GND, no limiting resistor), T7b-T17
  and T5-T17 are severity 3 under the `order.py` weights. An exhaustive search of all 10! assignments found no 2 x 5 map
  without a severity-3 pair; the best four-cavity alternative still keeps T7b-T17. The three pairs are accepted as a
  J.2 item 63 entry, and T-F-12 checks all 21 cavity pairs (design A.8 Table A.8-T2b). No placement rule changes.
- r9-13 (orchestrator default 2026-11-12 that replaces the r9-12 R1 fallback; the operator may revert it): the cavity
  map changes at four cavities (A1, A2, B2 and B3) to the table above. The exhaustive search scored all 10! maps with
  the `order.py` weights over the 13 orthogonal and 8 diagonal pairs. No map has zero severity-3 pairs. Among the maps
  with one severity-3 pair, this map moves the fewest cavities. The re-map removes T6-T7b and T5-T17. One severity-3
  pair remains, T7b-T17 (B3-A2 diagonal): its fault reads as a false pass of proof (d), and the lead-alive rule (FR-11)
  guards it. Both twisted pairs stay orthogonally adjacent (T1-T7b at B2-B3, T17-T17r at A2-A3), and the operator-
  accepted T5-T10 diagonal stays. The weighted sum falls from 25.0 to 21.5, and the severity-3 count falls from 3 to 1
  (design A.8 Tables A.8-T2 and A.8-T2b). The placement constraints above do not change, because they are stated per
  tap; the J-TAP region of D-52 does not depend on the cavity assignment. The netlist change is recorded in D-53.
- **Amended 2026-11-13** (operator ruling 2026-11-13 (Review 1/2: J102, J1-TSW, W6-W7 (connector and lead-pad
  geometry), local_923ffa1c-f985-43ad-8510-7faea2e5f5d7, chat 2026-11-13)): J102 is approved with one change, the
  cable P/N. The operator's words were: "Here is the PCB layout from the drawing for 43056-1012, which looks like the
  correct part. Also attached is the drawing showing the physical pin locations relative to the mechanical
  assembly."; then "That was a typo, I meant 43045-1012"; on the latch room, "That is enough room"; on the cable, "For
  the cable, 2147581101 is actually the male version of the cable, and we need female. Or, a female header instead of
  43056-1012"; and the choice "(A). 2147561101 is the correct cable and is in stock at Digikey". Option A keeps the
  43045-1012 male header on the CR and orders cable 2147561101; option B, a female receptacle on the CR, is rejected.
  - Header: the Molex 43045 PCB layout (component side; drawing number and revision not visible) gives a pin hole of
    1.02 +/- 0.05 mm TYP (pegs also 1.02 mm), a pitch and row spacing of 3.00 +/- 0.10 mm, pegs 3.00 +/- 0.08 mm
    outboard of the end columns and 0.94 +/- 0.05 mm beyond the last-circuit row, and a recommended PCB thickness of
    1.57 mm. The footprint matches each value: pegs at (-3, 3.94) and (15, 3.94), a 3.00 mm grid and 1.02 mm holes.
    The Molex part page 430451012 lists a vertical header, 3.00 mm pitch, dual row, 10 circuits, PCB polarizing peg,
    tin plating, 8.5 A per contact, mating with 43025, 214755 and 214756.
  - Pin numbering: circuits 1-5 are in the row away from the pegs and circuits 6-10 in the peg-side row, with circuit
    6 opposite circuit 1. The footprint is the drawing rotated 180 degrees, not mirrored, so the cavity map above is
    physically correct (row A pads 1-5: T2 T17 T17r T5 T13; row B pads 6-10: T6 T1 T7b T16 T10).
  - Latch: the latch is on the last-circuit (peg) edge and faces +x. On the final board the latch nub is at about MB x
    53.5-54.9, y 25.3-26.7; the trimmed edge is about 3.6 mm beyond it, R175 about 3 mm toward -y and MH3 about 14 mm
    toward -y. The operator ruled "That is enough room", so the finger-access constraint above is met.
  - Cable: the Molex page for 2147561101 lists a Micro-Fit 3.0 Female-to-Pigtail off-the-shelf assembly, dual row,
    150 mm, tin, 10 circuits, active. The page does not give the wire gauge or the insulation, so the gauge stays
    TODO(verify: Molex 2147561101) as a parts check, and the open item on the wire gauge against the R170/R171 joints
    stays open.
  - Already applied in commit `6804a16`: the schematic and board MPN field reads 43045-1012, the Note field names
    cable 2147561101, and the fab package BOM shows 43045-1012.
  - Consequence: section 11 item 25 is closed; section 11 item 16 is closed for the header P/N, orientation, pegs and
    physical pin numbering and amended for the cable; D-54 open item 1 is closed for the latch-finger access. The
    superseded open items are quoted at the Decision bullet above.

**D-47. Reduced tap set and permit gate (operator rulings 2026-11-12).**

- Decision: ten tap conductors stay (T1, T7b, T2, T5, T6, T10, T13, T16, T17 and T17r); thirteen are removed. The gate
  is release = (H1·UVB) + FCCP + (QUAL·FCC_OFF·¬P5), with the agreement term FCCP = FCC_ON·¬FCC_OFF; /CE = ¬P5; and
  RFC_OFF = FCC_OFF + (H1·UVB). The gate uses the gate.md 5-LVC mapping (U105, U106, U107, U110 and U118). CE_DRV is
  buffered by U106A (CHG_ARM OR GND), push-pull into R130; R108 stays 47 kOhm.
- Reason: the operator chose to trust firmware except for one hardware check, the regen check H1·UVB. The agreement
  term covers a stuck U119 or U120. The buffer keeps CE_DRV push-pull, so a ribbon 4-5 short with pin 5 high-Z cannot
  lift CE_DRV into the LVC undefined band.
- Consequence: the CR loses U104, U108, U109, U111, U113, U114, U115, U116 and U121, R137 and their passives, and the
  tap pads (D-31, D-46). The comparators U102, U103, U119 and U120 stay with their networks. The only spare section is
  U105 section 3. The CR part list for `gen/layout_cr.py`, `gen/check_constraints.py` and `gen/sch.py` follows the
  regenerated netlist. The latent single faults (gate outputs stuck HIGH, QUAL stuck HIGH, /CE stuck LOW) are accepted
  as J.1 entries, with the T-C-01/T-C-05 truth-table sweep at every build. The gate keeps R3' only with firmware
  invariant I-9 and the R5 MCU watchdog; no charging of any kind is allowed before the R5 firmware and T-W-01a pass,
  and FC windows also need the full T-W-01. Record: `decisions_2026-11-12/cr_tap_review_2026-11-12.md`;
  `decisions_2026-11-12/round2/permit_gate_decisions_2026-11-12.md`; `decisions_2026-11-12/ramifications/gate.md`;
  `decisions_2026-11-12/round2/dec2_hang_defence_2026-11-12.md`.

**D-48. CHG_QUAL on Teensy pin 33 (operator ruling 2026-11-12).**

- Decision: the qualification release CHG_QUAL (tap T10) moves from Teensy pin 10 to pin 33. Pin 10 becomes a freed
  pin.
- Reason: pin 10 is the default SPI CS0 of the Teensy, and a QUAL stuck HIGH releases the converter with /CE HIGH as
  the only barrier. Pin 33 removes that question. The operator ruled that the reset levels of pins 5 and 33 need no
  further check, because the RT1987 EN 10 kOhm pull-downs keep the charger unpowered through any reset or boot.
- Consequence: the T10 far end lands on the Teensy pin-33 header position, and its run is re-checked against its A.4
  maximum. The host test becomes: no SPI or other peripheral claims pin 33. Pin 10 takes the freed-pin rule
  (INPUT_PULLDOWN early in `setup()`, a boot read, and a non-blocking UNEXPECTED_LEAD flag on a HIGH read). FR-49 and
  T-D-01 are not extended for the pin 5 and pin 33 reset levels. Every record text on "pin 10" for QUAL applies as
  pin 33. The operator edits the IO CSV. Record: `decisions_2026-11-12/round2/dec2_firmware_rules_2026-11-12.md`
  item 5; `decisions_2026-11-12/round2/orchestrator_digest.md` (reconciliation notes).

**D-49. EIB kept as fabricated, with the sense branch DNP (operator ruling 2026-11-12).**

- Decision: the EIB copper is unchanged. U203, U204, C203, C204 and R258-R265 are DNP, and the E4 and E6 leads are
  not fitted. J101 stays 2 x 7, with pins 11 and 13 NC. The EIB has not been ordered.
- Reason: the reduced gate needs neither the far-end ILIM sense (U203) nor the /CE sense (U204). Fitting U204 as a
  build-time check would need R262/R263, and R263 would pull /CE LOW in the R272/R272b double-open fault.
- Consequence: `eib-bom.csv` and `eib-pos.csv` are regenerated with DNP flags, and `fab/eib_2026-11-11/` is reviewed
  by the operator before an order. (Regeneration closed 2026-11-13: `fab/eib_2026-11-13/` is generated from the
  schematic and board DNP attributes; every Gerber and Excellon file is identical to `fab/eib_2026-11-11/` apart from
  the creation dates. The operator review now applies to `fab/eib_2026-11-13/`.) The R272 + R272b double-open leaves /CE floating; this is latent, and T-C-05
  metering is the only check. A J101 pin 9 (GND) to pin 10 (RFC_OFF) short drives about 33 mA through R132 (100 ohm),
  above the LVC output current; the B.6 text that calls it safe is corrected, TODO(calc: B.6 9-10 short against the
  LVC IOL). Record: `decisions_2026-11-12/round2/dec2_eib_2026-11-12.md`.
- r9-12 (check-in 2 ruling R2, J.2 item 70(a) option (a)): R132 and R131B on the CR become 4.99 kOhm 1 % 0603, a value
  change on the same top-side footprint (D-44). A 9-10 or 8-9 ribbon short then draws <= 0.687 mA, and the CR rail
  stays >= 3.024 V (design H.24(d)). The 33 mA statement and the TODO(calc) above are superseded in r9. R131A stays
  100 ohm.

**D-50. Round order and finish method (operator ruling 2026-11-12).**

- Decision: the round runs in this order: (1) the decisions into the design document and the netlist; (2) the H
  calculation strip and re-run; (3) the r9 audit; (4) the new-outline generator, in parallel with (3); (5) placement on
  the frozen netlist; (6) the full route-race; (7) DRC and the constraint check; (8) the fab package. The operator
  checks in after (1), after the audit adjudication, after placement and before the fab package or order.
- Reason: the H numbers must be current before the audit checks them, and the placement must wait for the netlist
  that the audit freezes. The operator chose the full route-race over a plain board-routing gate.
- Consequence: the D-36 interactive finish retires. The r7 layout work moves to `archive_r7_outline/`. The H.23 rows
  that encode r7 geometry retire, and a new-outline geometry calculation is added with the generator. The route-race
  needs the new region table, the side flags and the power geometry first. Record:
  `decisions_2026-11-12/round2/dec_process_2026-11-12.md`.
- Step 4 status (2026-11-12, D-51, D-52): the height-survey item that blocked the outline freeze is closed by D-51.
  The new region table, the side flags (every SMT part on the top) and the 0.25 mm footprint re-basis are in the
  generator (D-52). The power geometry keeps the A.8 / D-09 block, with the VCHGOUT strap moved from L4 to L3. Step 5
  is blocked only by the frozen netlist; the placeholder footprints of D-52 do not block it.

**D-51. Height survey closed except the -x terminal clearance (operator ruling 2026-11-12).**

- Decision: the D-41 stack-up, with the CR underside 11.05 mm above the MB top, is taken to clear every MB component
  under the CR except the power terminals J-BL, J-FC and J-BT (21.70 mm). The only height requirement kept is a plan
  requirement: no part of the CR outline overlaps a terminal body, so the CR -x edge x 18.584 clears the bodies in the
  -x direction.
- Reason: the operator ruled that the planned TSW/SSQ header stack-up clears all other MB components. If the operator
  finds an interference later, the operator raises it.
- Consequence: the change-request section 6 height survey is closed on this basis (D-39). The D-20 air-gap
  TODO(measure: operator) for the L-FC/L-BT and bodge part heights closes, and so does section 11 item 21. The D-20
  air gap of 1.5 mm and the README section 8.2 THT-tail shadow rule rest on that survey; both are taken as met and are
  not checked by the generator. `gen/cr_geometry.py` checks the terminal clearance; Table D-51 gives the result. Every
  terminal clears the edge, so no blocker exists. Record: operator ruling 2026-11-12 (later in the day), relayed with
  the D-50 step-4 task.

Table D-51. Plan clearance from the terminal bodies to the CR -x edge x 18.584 (MB frame).

| Terminal | Package (`.brd`) | Body +x (mm) | Gap to the body (mm) | Gap to the silkscreen outer edge (mm) | Gap to the keep-out (mm) | y range of the body (mm) |
|---|---|---|---|---|---|---|
| J-BL | CUI_TB005_-762-03BE | 16.130 | 2.454 | 2.390 | 2.204 | 26.67-49.53 |
| J-FC | CUI_TB005-762-02BE | 16.130 | 2.454 | 2.390 | 2.204 | 72.39-87.63 |
| J-BT | CUI_TB005-762-02BE | 16.384 | 2.200 | 2.136 | 1.950 | 8.13-23.37 |

The body in Table D-51 is the package outline on `.brd` layer 51 (tDocu) of `references/Scale Car Board PCB
20260625.brd`. It spans -7.90 to +4.70 mm across the pin row, placed with R270 at the element origin. The
TB005-762 datasheet (`TB005-762_CUI.pdf` section A-A) puts the pins 4.70 mm from the rear face
(`round4/work/mb_mechanical.md` section 3.1), which agrees with the +4.70 mm edge. The silkscreen edge is layer 21
with half the line width added, and the keep-out is layer 39. The y range of every body lies inside the outline y
7-94 (J-BT from y 8.13), so the x gap decides the plan clearance.

**D-52. New-outline generator (D-50 step 4, 2026-11-12).**

- Decision: the generator builds the CR on the D-39 rectangle. The outline, the MB data and the region geometry come
  from the new modules `gen/cr_geometry.py` and `gen/mb_brd.py`; `gen/layout_cr.py` holds the region table and the
  phases. Table D-52 lists the regions.
- Reason: D-39 and D-50 retire every construct that encodes the r7 geometry (`outline_change_2026-11-12/retired.md`
  section 4). Reading the `.brd` directly replaces the hand-typed MB boxes and the `r7_calc` import.
- Consequence: the following changes apply.
  - Footprints: the CR library uses the 0.25 mm courtyard basis (`fpmap.FP_CR`, suffix `_CrtYd0.25`). The EIB keeps
    the 0.10 mm basis, and its generated library is identical to the previous one apart from the KiCad edit
    timestamps, so the EIB exports are unchanged.
  - CHG footprint: the name `Ag105_CHG_Carrier_22pin_P2.54mm` stays (D-02). The bottom courtyards are the TSW bodies
    plus 0.25 mm, and a pin-1 arrow is on the top silkscreen. The 1.1 mm drill and 1.9 mm pad stay as placeholders,
    TODO(verify: Samtec TSW drawing, CR pad and drill). (**Superseded 2026-11-13:** "The 1.1 mm drill and 1.9 mm pad
    stay as placeholders, TODO(verify: Samtec TSW drawing, CR pad and drill)"; closed by operator ruling 2026-11-13
    (Review 1/2: J102, J1-TSW, W6-W7 (connector and lead-pad geometry), local_923ffa1c-f985-43ad-8510-7faea2e5f5d7,
    chat 2026-11-13), D-41. The drilled-versus-finished reading of the drill stays with section 11 item 5.)
  - J102: the stock Micro-Fit 43045-1012 vertical pattern with the courtyard redrawn at 0.25 mm. P/N, orientation,
    pegs, latch side and cavity numbering are TODO(verify: Molex 43045 header drawing). (**Superseded 2026-11-13:**
    "P/N, orientation, pegs, latch side and cavity numbering are TODO(verify: Molex 43045 header drawing)"; closed by
    operator ruling 2026-11-13 (Review 1/2: J102, J1-TSW, W6-W7 (connector and lead-pad geometry),
    local_923ffa1c-f985-43ad-8510-7faea2e5f5d7, chat 2026-11-13), D-46. Only the cable wire gauge and insulation stay
    open.)
  - W1-W4 keep the A.8 hole and pad sizes and positions; W6/W7 keep the D-45 placeholder. Every CR through-hole pad
    has its unused inner pads removed (D-30, P-11). W6/W7 are packer-placed, because their r8 SMT coordinates overlap
    at the 2.54 mm pitch. Their hole and pitch are TODO(verify: 26 AWG / 28 AWG conductor and insulation OD).
    (**Superseded 2026-11-13:** "Their hole and pitch are TODO(verify: 26 AWG / 28 AWG conductor and insulation OD)";
    closed by operator ruling 2026-11-13 (Review 1/2: J102, J1-TSW, W6-W7 (connector and lead-pad geometry),
    local_923ffa1c-f985-43ad-8510-7faea2e5f5d7, chat 2026-11-13), D-45.)
  - Placement: every SMT part is on the top; the build stops if a netlist part is flipped (D-44). The power block
    (J1, W1-W4, the eFuse cluster and J101) keeps its A.8 / D-09 coordinates. The comparators, R175, the +x pocket
    parts, W6/W7 and J102 are packer-placed.
  - Rule areas: the r7 bottom-clearance, feet, B1R and bead-spot areas are removed. One B.Cu rule area forbids tracks
    over the whole outline (D-20). The route-race layer set must therefore exclude B.Cu; the r7 PathFinder call in
    `gen/make_cr_all.sh` still lists B.Cu.
  - Routing data: the VCHGOUT strap moves from L4 to L3, where it does not meet the VCHGIN strap. The FT stitching
    keep-outs are removed, and every reference designator stays on the silkscreen (D-12a reversed). The router track
    width in `gen/route_cr.py` stays 0.127 mm; the 0.1524 mm default of D-29 is applied in the route-race.
  - Constraint check: `gen/check_constraints.py` replaces the r7 rows (outline V1-V11, the x 39.53 rim rule, the tab X
    and tab Y contents, the R106s tab X row, the tab bookings). The new rows cover the D-39 outline, one SMT side, chip
    size, IC pitch, the 0.25 mm basis, the D-37 via-in-pad listing, L4 without tracks, the J-TAP placement and runs,
    and the D-20 window. The board-independent rows of `cr_geometry.py` run headless and are written to
    `cr/geometry_check.md`.
  - The next `gen/make_board.sh cr` writes the new footprint names into `cr/cr.net`; the connectivity does not change.
    The current `cr/` library and board stay on the r7 build until step 5. **Amended by D-53:** the `cr/` library and
    `cr/cr.net` are regenerated; the board stays on the r7 build until step 5.

Table D-52. Placement regions on the plug-on outline (MB frame; areas from `gen/layout_cr.py`).

| Region | Definition | Area (mm²) | Parts |
|---|---|---|---|
| Inset | outline less 0.5 mm (A.8) | 4077.8 | every courtyard |
| Interior | inset less the power block, J101, the CHG pads, W1-W4, the divider strip, the VCHGOUT belt and the power-via keep-outs | 3584.9 | logic, decouplers, other parts |
| Analog, strict | interior inside y 30.8-66.86 (D-20), at least 10 mm from the MB 5V copper rim (D-11 interim), at least 3 mm from the U101 loop region | 467.4 | comparators, BAV199 clamps, analog passives |
| Analog, wide (fallback) | as the strict region without the 10 mm rim | 1165.1 | the same parts; each one is listed as a D-20 exemption |
| Divider strip | x 23.15-36.50, y 42.14-45.69 less the W3 pad (A.8, D-13) | 42.3 | R109-R112, R114, R115 |
| J-TAP | interior at x >= 42.792 (the +x half, D-46), where every straight-line A.4 maximum is met | 1911.5 | J102 |

The 10 mm rim in Table D-52 is measured from the 5V layer-1 pour rim and the REG-5V keep-out box of the `.brd`. It
replaces the r7 constant x 39.53, TODO(measure: operator, MS4). J102 is packed toward C-D2 pad 1 to keep the T2 run
short (D-46). The headless booking of the 78 CR parts at the 0.25 mm basis is 917.0 of 4077.8 mm² (22.5 %), which
closes section 11 item 23.

**D-53. Netlist frozen (D-50, after check-in 2; design document r9-12; amended in r9-13).**

- Decision: the CR netlist `cr/cr.net` is frozen as regenerated on 2026-11-12. Placement (D-50 step 5) and every later
  step build on it. Table D-53 gives the identity of the frozen netlist.
- Reason: D-50 freezes the netlist after the audit adjudication. The operator approved all 29 agreed fixes of audit
  run 002, and the check-in 2 rulings R1 to R6 are the orchestrator defaults (design document 0.3, row r9-12).
- Changes carried from r9-12:
  - Ruling R2 (J.2 item 70(a), option (a)): R131B and R132 change from 100 ohm to 4.99 kOhm 1 % 0603,
    CRCW06034K99FKEA (design document H.24(d); `round4/calc/r9_calc.py` R9.H24(d)). The footprint and the top-side
    placement (D-44) do not change. R130 and R131A stay 100 ohm.
  - Ruling R1: the J-TAP cavity map and the J102 pin assignment of D-46 do not change, because the re-map search
    found no 2 x 5 map without a severity-3 pair. **Superseded in r9-13** (amendment below).
  - No other run-002 fix changes a part or a net.
- Method: `gen/netlist.py` was edited, then `gen/fplib.py cr cr`, `gen/sch.py cr cr`, `kicad-cli sch erc` and
  `kicad-cli sch export netlist` (KiCad 9.0.9) were run. These are the first four steps of `gen/make_board.sh cr`.
  `gen/pcbbuild.py` (placement) was not run.
- Consequence: the footprint library `cr/charger_r8_cr.pretty` now holds the 0.25 mm courtyard basis of D-52, and
  `cr/cr.net` names it. `cr/cr.kicad_pcb` is still the r7 build and references the retired `_CrtYd0.10` names;
  step 5 replaces it. The ordering BOM (`bom_2026-11-11/ordering_bom.csv`, README section 8.5) and design section E
  carry the new values. `round4/calc/r9_calc.py` now expects 4.99 kOhm in its `cr.net` value check and holds H.24(a)
  on a constant for the r9-9 100 ohm basis; every computed figure is unchanged. Step 5 is no longer blocked.
- Rule: a later change to a part, a value or a net reopens the freeze. Such a change needs a new decision entry, a
  new hash and a design-document change row.
- Amendment r9-13 (2026-11-12, design document change row r9-13; an orchestrator default that the operator may revert):
  the J-TAP re-map of D-46 reopens the freeze. `gen/netlist.py` assigns J102 pin 1 T2C, 2 CHG_IIN, 3 GND, 4 FCC_TAP,
  5 H1_RB, 6 T6_3V3, 7 T1_VMOT, 8 GND, 9 CHG_EFUSE_FLT and 10 QUAL_TAP. The cavity-to-pin convention does not change
  (row A column c = pin c, row B column c = pin 5 + c). `gen/sch.py` carries the new J102 pin names, and
  `gen/cr_geometry.py` carries the new pad-to-tap table (`JTAP`); the J-TAP region does not depend on that table.
  `cr/geometry_check.md` and `cr/geometry_check.json` were regenerated: only the J102 pad numbers of the T1, T2, T7b
  and T17 run rows change, and every row still passes.
  `gen/sch.py cr cr`, `kicad-cli sch erc` and `kicad-cli sch export netlist` (KiCad 9.0.9) were re-run.
  `gen/fplib.py cr cr` was also run; it changed only the `(tedit ...)` stamps of 13 footprints, so the library was kept
  at its r9-12 content. `gen/pcbbuild.py` was not run. Against the r9-12 `cr/cr.net`, connectivity changes only at
  J102: `/T2C` moves from pin 7 to pin 1, `/CHG_IIN` from pin 8 to pin 2, `/T1_VMOT` from pin 1 to pin 7, and the GND
  pin moves from 2 to 8 (pin 3 stays GND). Parts, values, footprints and every other node are unchanged. The ERC reports
  0 errors and 0 warnings. Table D-53 gives the identity of the re-frozen netlist; Table D-53a keeps the r9-12 record.

Table D-53. Identity of the frozen CR netlist (r9-13).

| Item | Value |
|---|---|
| File | `cr/cr.net` (KiCad s-expression netlist, version E, exported 2026-11-12T22:05:57-0800) |
| sha256 | `608bbf977803bc40118baf7a9f7635c60a9d3da6e1ca88ca0b95b1db1f64909b` |
| sha256 without the two `(date ...)` lines (export time, title block; `grep -v '(date ' cr/cr.net \| sha256sum`) | `da64c37a33b1343de252eda6739449a5e932c99f497bec6b3169616d2a60f484` |
| Generator | `gen/netlist.py`, sha256 `f78b38f1d10a1625342599aea84c192f41835b871c40a19fd36735b49582abb4`; `gen/sch.py`, sha256 `15cdcb28ff9c942227226f409af284f96b372ff503a752dd8479e1cc711302c1` |
| Parts | 78 |
| Nets | 79: 54 connected nets and 25 single-pin `unconnected-` nets; 262 pin nodes |
| Connectivity against the r9-12 `cr/cr.net` | J102 pins 1, 2, 7 and 8 only (the four re-mapped cavities A1, A2, B2 and B3) |
| Value changes against the r9-12 `cr/cr.net` | none |
| Footprint names | as Table D-53a |
| ERC (`cr/erc.rpt`) | 0 errors, 0 warnings |
| Netlist export message | as Table D-53a |

A re-export from the unchanged schematic changes only the export-time `(date ...)` line; the second hash reproduces.

**Amendment 2026-11-14 (REVIEW DOC-11; D-66, D-67, D-82).** D-66 changed connectivity and D-67 changed values without
a recorded re-freeze, so Table D-53 no longer identified `cr/cr.net`. Table D-53b records two states: the netlist
after D-67 (committed at `014c745`) and the netlist after the D-82 field synchronization. Table D-53 stays as the
r9-13 record.

Table D-53b. Identity of the CR netlist after D-67 and after D-82.

| Item | After D-67 (`014c745`) | After D-82 (2026-11-14, current) |
|---|---|---|
| Export time (`(date ...)` line) | 2026-11-13T19:08:55-0800 | 2026-11-15T02:06:43-0800 |
| sha256 of the working-tree file | `514be37703e098767bfbe8f684d8cf8ef926c315cff6ae9e926dbcf10aa24fef` (`snapshots/2026-11-14_pre_review/cr/cr.net`) | `39a6c6599778b46d6d14168c685502dc6af4ff881dfcb1e02e0fd55c56a2ea3d` |
| sha256 without the two `(date ...)` lines | `65c7d9800729803c2d382ec8d49bfef8654f953ee54f520f229a7413ec855a2a` | `3cd26f60d09e7b8450399e29c79dd2338d9cae8339810171c10e767dd9ab1d11` |
| Generator | as committed at `014c745` | `gen/netlist.py` sha256 `7ecd2c6c744fa228c52d1af1fcca976dde42616c849040d2477e4a638650a039`; `gen/sch.py` sha256 `6827b59097696284c4c8ecd826c5e8b32c6270e48408c0fad65ecd7c8272bbb8` |
| Parts | 78 | 78 |
| Nets | 77: 54 connected nets and 23 single-pin `unconnected-` nets; 258 pin nodes | 77: 54 connected nets and 23 single-pin `unconnected-` nets; 258 pin nodes |
| Connectivity against Table D-53 (r9-13) | J101 pins 11-14 removed (D-66: the ribbon conductors 11 and 13 were single-pin nets, 12 and 14 GND); J101 becomes the WIRE9 footprint; the eight single-pin U101 nets renamed with the Toshiba pin names (D-67) | as after D-67 (net membership identical, scratch `netcmp.py`, `update_2026-11-14/notes_phaseB_bom.md`) |
| Value changes against Table D-53 | U101 TCKE1401NM; R101 8.45 kOhm; R103 64.9 kOhm; R104 51.1 kOhm (D-67) | as after D-67, plus the D-82 value fields: C102b "4.7uF 100V X7R", the eleven CR 100 nF parts "100nF 100V X7R", C125 "10uF 16V X7R", D103 "Schottky 100V 2A SMA" |
| ERC (`cr/erc.rpt`) | 0 errors, 0 warnings | 0 errors, 0 warnings |

The EIB netlist after D-82 (`eib/eib.net`) has 46 parts and 35 nets (3 single-pin `unconnected-` nets, 111 pin nodes);
sha256 `14ff571313de4b3dc09508ea5542ef6a8c77f964cc339da723c5622102ff2d0b`, without the `(date ...)` lines
`774519aa10f3da6431dfd9a727fc34c2ffe9e429bb46ac046a778e5a067b025f`. Its net membership equals the `014c745` netlist.
The full-file sha256 depends on the export time and the line endings, so the date-stripped hash identifies the
content. The hashes of the current state are recomputed after any later `gen/netlist.py` change.

Table D-53a. Identity of the r9-12 freeze (**superseded in r9-13**; history only).

| Item | Value |
|---|---|
| File | `cr/cr.net` (KiCad s-expression netlist, version E, exported 2026-11-12T21:49:49-0800) |
| sha256 | `e98f4e49e22f60cab729c1db3f93439ce24fda5507423080c31d613b8f340833` |
| sha256 without the two `(date ...)` lines (export time, title block) | `65dbfeb7e1f4073b0f52458d65a7e6bb90d0e47f1a2766b4ec87974206b5dd0b` |
| Generator | `gen/netlist.py`, sha256 `a1c71e9350d878b6cf06ddd0e9c12fad8db7359cf02e82f1c3b827d28dd07555` |
| Parts | 78 |
| Nets | 79: 54 connected nets and 25 single-pin `unconnected-` nets; 262 pin nodes |
| Connectivity against the previous `cr/cr.net` (r9-11) | identical, net by net |
| Value changes against the previous `cr/cr.net` | R131B and R132, 100 ohm to 4.99 kOhm |
| Footprint names | 75 parts carry the `_CrtYd0.25` names (D-52); J1 (`Ag105_CHG_Carrier_22pin_P2.54mm`, D-02) and W6/W7 (D-45 placeholders) keep their names |
| ERC (`cr/erc.rpt`) | 0 errors, 0 warnings |
| Netlist export message | "schematic has annotation errors": the accepted letter-suffix references C102a, C102b, C102c, R106s, R131A and R131B (HANDOFF) |

A re-export from the unchanged schematic was checked: it changes only the export-time `(date ...)` line. The second
hash therefore identifies the frozen content.

**D-54. CR placement on the plug-on outline: variant B (D-50 step 5, 2026-11-13).**

- Decision: the live CR placement is variant B of `gen/layout_cr.py`. `LAYOUT_VARIANT` defaults to `B`; variant A
  stays reproducible with `LAYOUT_VARIANT=A`. The live board `cr/cr.kicad_pcb` is at the power-pour stage: placement,
  then `ROUTE_SKIP_FR=1` `gen/route.py cr ../cr` (power zones, pre-vias, 21 pre-tracks, GND pours), with no signal
  routing. The records of both variants are in `cr/variants_r9/A/` and `cr/variants_r9/B/`.
- Reason: a routability probe routed both variants with the same plain plan at two seeds (board-routing method;
  Table D-54). Both variants reach 106 of 107 connections at both seeds, with the same open connection. Variant B
  needs about 35 % less track, about 12 % fewer router vias and about 60 % less length on the divider and
  comparator-input nets, and B has the lower divider-top metric. Each difference holds at both seeds and is larger than
  the seed-to-seed spread. Both variants have the same constraint result (74 pass, 1 FAIL, 1 exemption), so no
  constraint row decides between them.
- Scope of the evidence: two seeds is below the four-seed minimum of the route-race, so the probe ranks the
  variants and does not certify routability. The full route-race (D-50 step 6) runs on variant B.
- Consequence: the B entries change only the packer inputs of the gate-logic and comparator cluster, J102, C125 and the
  CHG_IIN filter. Every fixed coordinate, region rule and constraint of A stays in force. The netlist is unchanged:
  the date-stripped `cr/cr.net` sha256 is `da64c37a...f484` and `gen/netlist.py` is `f78b38f1...abb4` (Table D-53).

Table D-54. Routability probe of the two placement variants (plain plan, 6/6 mil, via 0.6 / 0.3 mm, no via in an SMD
pad, routing layers F.Cu and In2.Cu, plane net /GND; seeds 1 and 2; lengths in mm).

| Measure | A, seed 1 | A, seed 2 | B, seed 1 | B, seed 2 |
|---|---|---|---|---|
| Connections open (non-plane, of 107) | 1 (/N_OV) | 1 (/N_OV) | 1 (/N_OV) | 1 (/N_OV) |
| New DRC violations | 0 | 0 | 0 | 0 |
| Vias added by the router | 185 | 181 | 161 | 162 |
| Track length, F.Cu and In2.Cu | 1342 | 1391 | 860 | 897 |
| Divider and comparator-input nets: length / vias | 451.4 / 55 | 430.6 / 44 | 176.1 / 28 | 174.2 / 31 |
| /GND connections open before / after the plane-via step | 7 / 6 | 8 / 7 | 5 / 5 | 3 / 3 |
| Divider-top metric: logic track parallel to analog track, same layer | 12.63 | 8.25 | 2.90 | 6.27 |
| Straight-line ratsnest, all signal nets (pad positions) | 817.9 | 817.9 | 556.1 | 556.1 |
| Ratsnest edge crossings, all nets / J101 nets | 146 / 29 | 146 / 29 | 103 / 17 | 103 / 17 |

The live variant-B board gives the placement results of Table D-54a. `gen/check_constraints.py` writes
`cr/constraint_check.md`, and `kicad-cli pcb drc --severity-all --schematic-parity` writes `cr/drc_place.rpt`.

Table D-54a. Placement checks of the live board (variant B, pour stage).

| Check | Result |
|---|---|
| Parts placed, outside the outline, flipped | 78, 0, 0 |
| Constraint rows | 74 pass, 1 FAIL (D-44: U101.25 on B.Cu), 1 D-20 exemption (R102, a fixed part), 14 information |
| D-20 window, comparators, clamps and dividers | 13 of 13 inside the strict window |
| Divider-top metric (logic pads within 2 mm of the divider tops) | 0 pads |
| Distance from the U101 loop region, comparators and clamps (information; rule 3 mm or more) | 10.09-19.38 mm |
| Top-side courtyard booking | 911.5 of 4077.8 mm² (22.4 %) |
| J102 | (48.579, 20.000) rot 90; courtyard x 45.86-55.12, y 16.18-35.82 |
| J-TAP straight-line runs (A.4 maxima) | T2 53.4 mm (A: 59.0 mm); T17 84.5, T17r 68.2, T5 39.1, T13 61.5, T6 50.3, T1 46.7, T7b 46.7, T16 59.1, T10 58.4 mm; all pass |
| DRC | 131 violations: 3 courtyard overlaps, 0 clearance, 4 starved thermals, 75 silk over copper, 47 silk overlap, 2 silk to edge; 108 unconnected items; 0 schematic-parity issues |

The variant-B entries in `gen/layout_cr.py` are these:

1. J102 targets (50.5, 26.0) at rot 90 and lands at (48.579, 20.000). Row A (T2C, CHG_IIN, FCC_TAP, H1_RB) is on the
   -x pad column, so the westbound tap nets enter the logic box and the comparator pocket directly.
2. The comparators have explicit targets in the lower row of the pocket (U102, U103, U120, U119 from -x to +x) at
   rot 180. IN+ and IN- face the dividers, OUT faces the logic box and VCC faces the decoupler.
3. The gate ICs are packed in the logic box (interior within x 35-45, y 16-41.6, less the strict window at x < 40).
   Each gate IC is followed at once by its decoupler, so the decoupler keeps the 3V3 pad.
4. R130, R131A, R131B and R132 stand in one row under J101 at rot 90. The outer pair and the inner pair use separate
   channels to the J101 pad columns. The four resistors are excluded from the "other parts" phase, which removes a
   double placement.
5. The FCC networks are packed before the H1/UVB networks, and the clamps after the comparators.
6. C125 (the 3V3 bulk capacitor) targets the centre of its loads and lands at (33.034, 28.025).
7. R129 may use the wide window and lands at (48.084, 44.300), east of the J1 +x column. C129 lands at J102,
   (44.984, 21.100), outside the D-20 window. A keeps both parts in the strict window.

Item 7 is a deviation from the `ANALOG_PASSIVES` rule (A.7 thermal-band content carried to the D-20 window). The D-20
window is preferred, not hard, and `gen/check_constraints.py` does not test R129 or C129, so no row fails. However,
the CHG_IIN filter now spans J102 to U101 pin 13, and the operator approves or reverts the deviation at check-in 3.

The step-5 build needed three generator fixes. These fixes are common to both variants:

1. The divider strip uses a 0.03 mm packer margin (`PHASE_MARGIN`) and dense fill packing. With the D-15 channel of
   0.08 mm, two rows of an 0805 and an 0603 courtyard need 3.65 mm of the 3.55 mm strip, and R109 and R112 stayed
   unplaced.
2. With `THT_BOTH_SIDES = True` (CR only), a phase that holds a through-hole part packs against the courtyards of both
   sides. W6 and W7 overlapped the B.CrtYd courtyards of the J1 TSW rows before this fix. The EIB build is unchanged.
3. `gen/plot_place.py` follows the outline and the park spot, and draws the `L4_no_tracks` area on the bottom plot
   only.

The build used the OSH Park-only rule file of D-29 (amended 2026-11-12;
`decisions_2026-11-12/stackup_fabrules_decisions_2026-11-12.md` section 3), not the shared file that
`gen/make_board.sh` copies. The OSH Park-only file exists only as `cr/cr.kicad_dru` (also in both variant folders). The
board minima were set to match it: annular ring 0.1016 mm, via 0.4572 mm, hole-to-hole 0.127 mm, track and clearance
0.127 mm. A run of `gen/make_board.sh cr` copies `fab_4layer_5mil_oshpark_pcbway.kicad_dru` back in. The file must
move to `tools/pcb/fab_rules/`, and `gen/make_board.sh` must name it, before the route-race.

Open items after step 5:

1. TODO(verify: Molex 43045 header drawing) the J102 latch-finger access and the D-46 THT-tail and MB clearance at the
   new J102 position. C116, C129 and R147 sit about 0.1-0.2 mm from the -x side of the J102 courtyard.
   **Closed 2026-11-13** for the latch-finger access (operator ruling 2026-11-13 (Review 1/2: J102, J1-TSW, W6-W7
   (connector and lead-pad geometry), local_923ffa1c-f985-43ad-8510-7faea2e5f5d7, chat 2026-11-13); D-46): the latch
   faces +x with the trimmed edge about 3.6 mm beyond the nub, and the operator ruled "That is enough room". The
   ruling does not address the THT-tail and MB clearance half of this item.
2. The D-44 row fails on U101.25, the B.Cu heatsink copper pad of the TPS26630 ThermalVias footprint (no paste, no mask
   opening). Either the pad leaves the footprint, or `gen/check_constraints.py` exempts a copper-only heatsink pad.
3. Three courtyard overlaps come from fixed coordinates. W1/W2 overlap by 0.193 mm at the A.8 2.6 mm pitch with the
   0.25 mm courtyard basis (DRC counts the F and B courtyards). C102b overlaps J101 by 0.040 mm in y at the D-09 start
   values; a +0.05 mm move in y stays inside the D-09 allowance of 0.80 mm.
4. /N_OV (U101.7) is open at every probe seed. It loses its lane in the fixed U101 +x pocket to /N_UV. The route-race
   tries a priority or via-cost change first; a placement request for R103/R104 follows if that fails.
5. `plane_vias.py` adds a /GND via inside U101.25 at every seed. D-40 exempts only the nine thermal vias, so the
   route-race must exclude that pad from the plane-via step.
6. The variant-A J102 target `G.far_end("7")` is stale after the r9-13 re-map (pad 7 is T1 to C-D6). It is kept so that
   A reproduces; a re-run of A must target pad 1.
7. A full `gen/make_board.sh cr` rewrites the `cr/cr.net` date line and 13 footprint files of `cr/charger_r8_cr.pretty`
   (whole-file text differences, content not compared). The step-5 builds restored both from backups, so the library
   and the netlist are those of r9-13.

**D-55. Placement fix round on the variant-B review (2026-11-13).**

- Decision: every finding of `cr/placement_review_r9.md` (B-1, M-1 to M-4, m-1 to m-9) is applied in the generator,
  the footprint library and the tool scripts, and the live board `cr/cr.kicad_pcb` is rebuilt from them (variant B,
  pour stage). The rebuild uses the documented placement half of `gen/make_board.sh` (`gen/pcbbuild.py`, the rule
  copy, `apply_board_setup.py`, the OSH Park minima, `gen/silk_fix.py`) and then `ROUTE_SKIP_FR=1 gen/route.py cr
  ../cr`.
- Reason: the review found one blocker (no region owned the A.8 +x pocket, so the U101 programming and monitor parts
  were packed across the CHG pin column, up to 23 mm from their pins), four majors and nine minors. Each has a local
  fix that changes no net.
- Consequence: the constraint check gives 88 pass rows, 0 FAIL, 3 listed D-20 exemptions (R102, R104, R129) and 16
  information rows (D-54: 74 pass, 1 FAIL). DRC gives 124 violations (75 silk over copper, 49 silk overlap; no
  courtyard overlap, clearance, starved-thermal or silk-to-edge item), 109 unconnected items and 0 parity issues.
  The netlist is unchanged: the date-stripped `cr/cr.net` sha256 is `da64c37a...f484` and `gen/netlist.py` is
  `f78b38f1...abb4`. Variant A shares every change except the B-only packer inputs; its record in
  `cr/variants_r9/A/` predates D-55 and is not rebuilt.

Table D-55. Findings of the variant-B placement review and the applied fixes.

| Finding | Fix | Result on the rebuilt board |
|---|---|---|
| B-1 pocket unowned | `gen/layout_cr.py`: regions `pocket` (x 44.40-51.40, y 63.40-70.00), `pocket_win` (pocket inside the D-20 window) and `north` (x 39.20-44.40, y 66.90-70.60), subtracted from the interior; the phase "U101 network" straight after J-TAP in both variants, with a slot target and a fixed rotation per part (`U101_NET_TARGET`, `U101_NET_ROT`). Near column x 44.40-47.90, rot 0, pad 1 at -x: R104, R103, R129, R106s from -y to +y. North strip, rot 90, pad 1 at -y: R105, C101, R101. C129 joins the phase, east of R129 inside the window. New check rows: A.8 node distances, R106s to pin 14, CHG-column crossings | R101 3.73 mm to pin 10, C101 4.59 mm to pin 9, R103 4.60 mm and R104 2.31 mm to pin 7, R105 3.26 mm and R129 2.80 mm to pin 13 (all <= 5 mm); R106s 4.31 mm to pin 14; CHG-column crossings 0 (review: 6) |
| M-1 paste on the via drills | `gen/fplib.py` `vqfn24()`: four 0.50 x 0.50 mm window-pane apertures at +/-0.55 mm | smallest aperture-to-drill gap 0.274 mm (diagonal); paste coverage 13.7 %; TODO(verify: SLVSE94G section 11, stencil vendor) the coverage target |
| M-2 pre-vias on the C102b pad | `gen/route_cr.py` `PRE_VIAS` and `PRE_TRACKS`, `gen/layout_cr.py` `PRE_VIA_SITES`: (40.35 / 40.95, 51.62) replaced by (39.45, 51.80) and (40.65, 51.40), and a sixth via at (39.45, 55.00); the D-37 row tests the via annulus against the pad plus its mask expansion | 0 vias on a pad or mask opening, smallest gap 0.089 mm; 6 C102b-end vias (A.8 6 each end met; D-21 five; the C102c end keeps 2) |
| M-3 pad 10 on an L1 island | `gen/route_cr.py` `VIN_L1`: the area east of C102c and above the R102 N_UV pad (x 42.35-44.85, y 57.95-62.10) and a ring around pad 10 (x 43.90-48.20, y 60.55-63.60) | no starved thermal at J1.10 (DRC minimum 2 spokes met); the corridor between R102 and the J1 +x column is 0.40 mm wide |
| M-4 rule file and net class | new `tools/pcb/fab_rules/fab_4layer_oshpark_only.kicad_dru` (the content of the former hand-copied `cr/cr.kicad_dru`); `gen/make_board.sh` copies it, sets the D-54 minima and the Default net class 0.1524 / 0.1524 mm (via 0.6 / 0.3 mm); `gen/route_cr.py` TRACK and CLEAR 0.1524 mm | board minimum track and clearance 0.127 mm, annular ring 0.1016 mm, via 0.4572 mm, hole to hole 0.127 mm; Default net class 0.1524 / 0.1524 mm |
| m-1 W1/W2 | W2 x 27.7 to 27.2; `GND_L1_STAR` W2 piece -0.5 mm in x | pad gap 0.807 mm, no courtyard overlap |
| m-2 R103/R104 not in the D-20 rows | listed exemptions with the R102 reason (U101 network under A.8) | R104 and R129 outside the window and listed; R103 and C129 inside |
| m-3 W3 at R110 | the divider-strip W3 keep-out stretched 0.7 mm in +x, and the strip left of x 26.13 closed | all six dividers +0.70 mm in x; W3 to R110 pad gap 1.47 mm (0.78 mm before) |
| m-4 R177, R107 east of the column | region `j101_east` (x 40.90-44.90, below the J101 region), targets J101 pins 2 and 4, phase after "J101 series" | R177 (43.584, 40.100), R107 (42.634, 37.750) |
| m-5 C102b/J101 courtyards | C102b y 53.14 to 53.19 | no courtyard overlap |
| m-6 B.Cu pad 25 | `vqfn24()` drops the B.Cu copy of pad 25; the nine thermal-via pads get a solid zone connection | D-44 rows pass; the three U101 starved-thermal items are gone |
| m-7 silkscreen | `gen/silk_fix.py` runs in the CR placement half of `gen/make_board.sh`; the J1 "11" mark moves to the +x side of pin 11 (x 22.90) | silk to edge 0 (2 before); silk over copper 75 and silk overlap 49 remain, all reference fields (D-12a keeps them on the silkscreen; to be resolved before the fab package) |
| m-8 divider-top nets | `gen/route_cr.py` `GUIDE_CORRIDORS` for T1_VMOT and T2C (south band y 7.90-15.80, -x band x 19.60-23.00 to y 34.90); data for the route-race, read by no generator script | divider-top metric 0 pads |
| m-9 plane via in U101.25 | `tools/pcb/corridor_route/plane_vias.py` keeps a new via off every SMD pad grown by its mask expansion and the via radius; `--allow-via-in-pad` restores the earlier rule | to be confirmed at the route-race |

The B-1 slot layout follows from the 5 mm A.8 radius. Pins 7-12 lie at x 43.66, so the radius reaches only about
x 47.9 at the pocket height, and the near column holds four 0603 rows. The two lowest rows are the only ones inside
the D-20 window; R104 and R103 (the OVP node, pin 7) need them, so R129 sits in row 3, above the window top. This is
a listed exemption (A.8 IMON <= 5 mm binds), and it replaces the D-54 item-7 deviation. C129 now sits inside the
window beside R129, so the CHG_IIN filter has no window deviation.

Superseded D-54 open items: item 2 (the D-44 FAIL on U101.25) and item 3 (the courtyard overlaps) are closed;
item 5 (`plane_vias.py` via in U101.25) is closed in the tool and is confirmed at the route-race; the rule-file
paragraph of D-54 is closed by M-4. Item 4 (/N_OV open) is re-tested at the route-race: R103 and R104 now sit 2.3-4.6
mm from pin 7 on the +x side, but the N_UV and N_OV escapes still cross the VCHGIN L1 pour, which since M-3 also
rings pad 10. Items 1, 6 and 7 stay open. (**Amended 2026-11-13:** the latch-finger access half of item 1 is closed
by operator ruling 2026-11-13 (Review 1/2: J102, J1-TSW, W6-W7 (connector and lead-pad geometry),
local_923ffa1c-f985-43ad-8510-7faea2e5f5d7, chat 2026-11-13), D-46; the THT-tail and MB clearance half stays open.)

**D-56. Fix round on the r9b re-review of the D-55 board (2026-11-13).**

- Decision: findings N-1, N-2, N-3, N-4 (both free slot exchanges), N-6 and N-7 of `cr/placement_review_r9b.md` are
  applied in the generator, the U101 footprint and the constraint check, and the live board is rebuilt with the
  documented placement half of `gen/make_board.sh` and `ROUTE_SKIP_FR=1 gen/route.py cr ../cr` (variant B, pour
  stage). The M-3 pad-10 ring and the L1 extension of D-55 are superseded: J1 pad 10 feeds U101 through the L3
  (In2.Cu) VCHGIN strap alone, as D-21 and the r9 review intended. N-5 (router defect in `tools/pcb/corridor_route`)
  and N-8 (process items) are not in this round; the routing session owns the router.
- Reason: the D-55 `VCHGIN_L1` extension sealed U101 pins 6, 7 and 9 and R102 pad 2 on F.Cu, with the strap under
  them on In2.Cu, so no via could reach them either (four connections open at every probe seed). It also isolated the
  C102c ground pad, and the C103 ground pad had no plane-via site (present since D-54).
- Consequence: with J1.10 on L3 alone, the strap carries the whole 2.41 A input. Row H.25 of the design document
  (`round4/calc/r9_calc.py` R9.H25, change row r9-15) checks it on 0.5 oz (17.5 um) inner copper against a curve fit
  of the IPC-2152 baseline chart at the 10 C rise of the A.8 Copper basis. The review width 2.596 mm fails (2.16 A
  at 10 C); the strap is widened to a 3.645 mm narrowest section (2.57 A, 8.7 C at 2.41 A, required 3.221 mm). The
  J1.10 joint on In2 becomes solid, because four 0.6 mm thermal spokes give 2.40 mm. A third C102c-end via gives
  4.00 A of via capacity (two vias: 2.67 A). The IPC-2152 chart reading stays TODO(verify: IPC-2152 Figure 5-1).
  (**Amended 2026-11-13:** closed for the VCHGIN strap by operator ruling 2026-11-13 (Review 2/2), section 11 item 2;
  the VCHGOUT L3 strap check stays open there.) (**Amended 2026-11-13:** the VCHGOUT half of section 11 item 2 is closed
  by acceptance, operator ruling 2026-11-13 (design session, chat 2026-11-13: "Accept short necks").) The IPC-2221
  internal formula still fails (1.85 A). The solid joint adds heat demand when the TSW tail at pad 10 is soldered; the
  strap is 0.5 oz and about 51 mm2. The netlist is unchanged: the date-stripped `cr/cr.net` sha256 is `da64c37a...f484`
  and `gen/netlist.py` is `f78b38f1...abb4`; no pad number or net changed.

Table D-56. Findings of the r9b re-review and the applied fixes.

| Finding | Fix | Result on the rebuilt board |
|---|---|---|
| N-1 L1 extension seals the U101 +x pads | `gen/route_cr.py` `VIN_L1` = the D-54 main body plus `box(42.35, 60.60, 43.10, 61.55)` (pin 5 tie), no copper at pad 10; `VIN_L3` pad-10 band `box(39.15, 58.50, 47.10, 62.75)` (review y 59.55); the strap zone joins THT pads solid (optional sixth field of `power_zones()`, read by `gen/route.py`); third VCHGIN via (39.75, 59.65) with its track in `PRE_VIAS`, `PRE_TRACKS` and `layout_cr.PRE_VIA_SITES` | `VCHGIN_L1` one piece, 26.77 mm2, holds U101 pins 1, 2 and 5; `VCHGIN_L3_strap` one piece, 50.68 mm2, narrowest section 3.645 mm at x 42.75 (D-55: 1.160 mm at the pad-10 thermal relief), J1.10 joint solid; escape rows U101.6, .7, .9 and R102.2 pass |
| N-2 C102c ground pad isolated | removed with the N-1 enclosure | C102c.2 in the main `GND_L1_fill` piece (3622.87 mm2); D-55 island 0.80 mm2 gone |
| N-3 C103 ground pad without a plane connection | `VOUT_L1` notch `box(37.40, 62.60, 38.80, 63.40)`; /GND pre-via (38.08, 62.90) in `PRE_VIAS` and `PRE_VIA_SITES` | C103.2 island 4.93 mm2 tied to the plane by the via; via annulus 0.179 mm from the C103.2 pad plus its mask expansion |
| N-4 slot order against the U101 pin order | `gen/layout_cr.py` `U101_NET_TARGET`: C101 (43.60, 68.45), R101 (42.00, 68.45), R103 (45.95, 64.20), R104 (45.95, 65.80); R129 and R106s unchanged | R101.1 4.09 mm to pin 10, C101.1 4.28 mm to pin 9, R103.2 3.58 mm and R104.1 3.69 mm to pin 7 (centre to centre). Row 1 lies outside the D-20 window (rim distance), so R104 now passes and R103 is the listed exemption (the review expected both inside). The N_IMON/N_FLT pair stays a route-race test item |
| N-6 paste coverage 13.7 % | `gen/fplib.py` `vqfn24()` apertures 0.675 x 0.675 mm at the same four centres, the largest square with >= 0.15 mm to every drill (limit 0.6757 mm); the U101 footprint in `cr/charger_r8_cr.pretty/` edited by hand from the scratch library build (the other twelve files differ in stamps only) | smallest aperture-to-drill gap 0.151 mm; coverage 25.0 %; aperture web 0.425 mm; the check row now asks gap >= 0.15 mm; TODO(verify: SLVSE94G section 11, stencil vendor) the coverage target |
| N-7 no row detects a sealed pad | `gen/check_constraints.py` escape rows (method of the review section 1) for U101.6, .7, .9, .10, .13, .14, R102.2, C102c.2 and C103.2: a pad passes when its free F.Cu component reaches a same-net pad or via, or holds a 0.6 mm via site that is clear of the hard non-/GND pours on the other layers, the SMD pads plus mask (D-37) and the drills | all nine pass on the D-56 board; on the D-55 board the row reproduces the review (U101.6 0.03 mm2, U101.7 0.14 mm2, U101.9 0.20 mm2, R102.2 0.97 mm2, C102c.2 and C103.2 FAIL) |

The constraint check gives 97 pass rows, 0 FAIL, 3 listed D-20 exemptions (R102, R103, R129) and 16 information
rows. DRC reports 124 violations (75 silk over copper, 49 silk overlap, all reference fields), 107 unconnected items
and 0 parity issues; the two removed unconnected items are the D-55 /GND fill islands, as review trial 4 predicted.
Open: the 4-seed probe re-run on this board (step 6 entry), N-5 and N-8.

**Amended 2026-11-14 (REVIEW CRL-1): exemption from the A.8 VCHG-IN length rule.** A.8 (design document, Header-pin
current bullet) asks for VCHG-IN copper of at most 5 mm from J1 pad 10 to U101 IN/IN_SYS. With the L3 strap as the
only pad-10 path, the measured path is about 7.3 mm. It runs 6.31 mm from pad 10 at (45.998, 38.056) to the nearest
F.Cu-In2.Cu via at (39.75, 38.95), then about 0.95 mm on F.Cu to U101 pin 1 (review CRL-1 verifier note, pcbnew
measurement; KiCad frame). The other two strap vias are at (39.75, 39.65) and (39.75, 40.35). The rule guards against
exposed unfused VCHG-IN copper. The strap is buried on In2.Cu between the In1.Cu and B.Cu GND planes, so no exposed
copper results, and the masking intent holds. The length rule is therefore exempted for this path, and the board does
not change. No constraint row measures the path; the design-document A.8 row needs the same exemption (design-document
change, outside this log).

**D-57. C102c ground pad: /GND pre-via and strap extension (2026-11-13; route-race r9 change request R9-01).**

- Decision: a /GND pre-via at (42.30, 59.30), joined to C102c pad 2 by a 0.4 mm F.Cu track, is added to
  `gen/route_cr.py` `PRE_VIAS`/`PRE_TRACKS` and to `gen/layout_cr.py` `PRE_VIA_SITES`. The VCHGIN L3 strap `VIN_L3`
  gains `box(41.95, 57.00, 44.00, 58.50)`, so the current passes below the via cut-out. The board is rebuilt with the
  D-56 procedure (placement half of `gen/make_board.sh`, then `ROUTE_SKIP_FR=1 gen/route.py cr ../cr`).
- Reason: in round 1 of the r9 route-race, C102c.2 was open after the plane-via step at every seed of every plan
  (probe_d56 section 4.1). The /N_UV track from U101.6 to R102.2 encloses the pad's GND_L1_fill piece; VCHGIN copper,
  R102 and the J1 +x column close the other sides, and the In2 strap left no plane-via site. Of the three probe
  candidates, the via in a strap cut-out changes no placement and no signal route.
- Consequence: the via annulus clears C102c.2 by 0.195 mm, C102a.1 by 0.239 mm and R102.2 by 0.330 mm (pcbnew pad
  shapes; outside every mask opening, D-37). A first site at (42.55, 59.20) was 0.061 mm from R102.2 and is not used.
  The cut-out alone leaves a 2.3-2.6 mm strap section at the trial sites, below the 3.221 mm R9.H25 requirement.
  With the extension, the board-measured minimum section (total vertical chord of the filled strap, x 41.96-45.00) is
  4.174 mm at x 42.535 (D-56: 3.630 mm at x 42.76 on the same measurement). R9.H25 gives 2.75 A at a 10 C rise
  (7.4 C at 2.41 A). The IPC-2221 internal formula gives 2.04 A, below the 2.41 A basis, and needs a 5.258 mm
  section (`round4/calc/r9_calc_out.txt`, R9.H25; the file's "-> pass" label on this row is superseded); it is
  superseded by IPC-2152 per operator ruling 2026-11-13 (Review 2/2), section 11 item 2. (**Superseded 2026-11-13:**
  "the IPC-2221 internal formula now also passes (2.04 A)".) The section sums two parallel paths around the via; a
  single conductor of the same width is the conservative case. The extension takes about 3.1 mm2 of In2.Cu routing
  area under R102. Placement, the netlist and the signal ratsnest are unchanged; the only new copper is the via and
  its track.

**D-58. CR signal routing: route-race r9 plan softum, seed 1 (2026-11-13).**

- Decision: the signal nets of the D-57 board are routed by the corridor router (`tools/pcb/corridor_route/`, board-routing
  method) with plan softum and seed 1. Plan softum is plan softu with `rules.mask_margin` 0.075 mm. Plan softu sets soft
  keep-out zones at the four divider tops (R102, R109, R111, R114) on F.Cu and In2.Cu with reserve 30, and via cost 200
  on /N_UV, /N_OV, /N_DVDT and /N_ILIM. The router output passes through the plane-via step; the zones are not refilled
  afterwards.
- Reason: in round 2 of the r9 route-race, plan softu routed 107 of 107 connections at all four seeds on the D-57
  board, with no via on an SMD pad. Seed 1 is the best of the four: 148 router vias, 830.8 mm of track, divider-top
  same-layer metric 0.00 mm, logic track in the divider zone 0.7 mm, and one logic via in the zone (the /CE_DRV_J
  escape). The /GND net after the plane-via step was open at seed 3 only (one In2.Cu-blocked GND_L1_fill piece).
- Consequence: the U101 high-impedance nets carry these via counts: /N_UV 2, /N_OV 0, /N_DVDT 2, /N_ILIM 2, /N_IMON 3,
  /N_FLT 2. With the default round mask margin of 0.05 mm, seed 2 of plan softu placed two own-net vias (/CHG_ARM at
  U106.1, /3V3 at U118.8) 0.0045 mm inside the square-cornered mask opening of a rectangular pad; the opening corner
  sits 0.072 mm out for a 0.0508 mm expansion. The mask margin 0.075 mm clears this case. Tools commit `114ad04`
  (after the routing) makes the router and its score script ban vias from the square-cornered mask opening (pad grown
  by the larger of its mask expansion and `mask_margin`, plus the via radius). With it, plan softu at the default
  0.05 mm margin routed 107/107 at four of four seeds, all valid, and the score script marks the old softu seed 2 board
  not valid; the applied softum seed 1 board stays valid. Board models built before `114ad04` carry no mask expansion
  and fall back to the round margin, so they need a rebuild. Superseded: "until they use the mitred opening, every
  plan for this board needs `mask_margin` >= 0.075 mm". The smallest via-annulus gap to a pad plus its mask opening is 0.027 mm (constraint check,
  D-37 row). The VIN_L3 extension of D-57 gave no measurable routing cost: plan softu gave 147/150/153/145 vias on the
  D-57 board against 145/143/144/148 on the D-56 board. The route-race record is in the routing session's notes
  (`routing_r9_cr/REVIEW_r2.md`, `TABLE_r2.md`, `plan_softum.json`).

**D-59. Reference designators on the routed CR (2026-11-13).**

- Decision: `gen/silk_refs.py` moves each reference field to the nearest position within 3.0 mm of its courtyard that
  is clear of every top mask opening (plus 0.05 mm), every other silkscreen item (plus 0.10 mm) and a 0.25 mm band
  inside the board edge. The text height is 1.0 mm, or 0.8 mm where 1.0 mm does not fit; the stroke is 0.15 mm (rule
  `fab_silk_text`, 0.8 / 0.15 mm). A position over the courtyard of another part is used only where no free position
  exists. A reference with no clear position moves to F.Fab. Copper, nets and footprint positions are not changed.
- Reason: after routing, DRC reported 124 silkscreen items (75 silk clipped by the solder mask, 49 silk overlaps), all
  reference fields at the 1.27 mm default height. `gen/export.sh` writes a package only from a board with no DRC
  violation.
- Consequence: 60 of 78 references are on the top silkscreen; 26 of them sit over another part's courtyard and are
  hidden after assembly. 18 references are on F.Fab only: C107, C115, C130, C132, D105, D106, R122, R130, R131B, R147,
  R184-R189, U110 and W3. This is a partial reversal of D-12a reversed (every reference on the silkscreen); the
  interactive BOM and the F.Fab layer identify those 18 parts. In the dense rows, a reference can sit up to 3.0 mm from
  its part, so the interactive BOM is the assembly reference. `cr/silk_refs.md` lists each reference with its text
  height, angle and gap to its own courtyard. Reversal: restore the reference fields from 621fb28 (DRC then reports the
  124 items again), or move every small-part reference to F.Fab (D-12a as first written).

**Amended 2026-11-14 (D-74, D-78).** The references are no longer as D-59 and D-62 left them. On the current board 54
references are on F.Silkscreen, 7 on B.Silkscreen (mirrored, over the part: C102a, C102c, C119, C131, R107, U107,
U119) and 17 on F.Fab only (C107, C115, C130, C132, D105, D106, R122, R130, R131B, R147, R184-R189, U110). W3 is on
F.Silkscreen. `cr/silk_refs.md` is now written by `gen/cr_silk_refs_report.py` from the board, with a layer column and
gaps to the courtyard polygons.

**D-60. Trimmed CR outline and four 6-32 holes (operator rulings 2026-11-13; route-race r9 change request R9-02).**

- Decision: after routing, the CR is trimmed to a convex 18-vertex outline inside the D-39 rectangle, and four
  non-plated 3.70 mm holes (6-32 free fit) are added: MH1 (26.23, 69.04), MH2 (54.85, 63.79), MH3 (54.85, 11.43) and
  MH4 (24.48, 25.18), MB frame. Each hole has an all-layer copper keep-out of radius 4.0 mm and keeps a 3.6 mm
  screw-head disc on the board. The outline is the convex hull of the used area (courtyards, pads, signal copper and
  local pours, plus 1.0 mm), the +x key ear box x 50-58.6, y 52-71 and the four head discs. `gen/cr_geometry.py`
  holds the outline (`FINAL_OUTLINE`), the ear and the holes. `gen/trim_cr.py` applies them to the routed board through
  `tools/pcb/corridor_route/trim_outline.py` and refuses when the tool's result differs from that data by more than
  0.01 mm. The board-wide GND zones keep their 0.45 mm inset from the new edge, and the router edge band keeps
  0.40 mm. The D-39 rectangle stays the placement frame.
- Reason: the operator ruled on 2026-11-13, in a conversation with the routing session: "trim away the unused area
  of the board"; "The final board outline does not need to be rectangular"; "add holes in the corners for 6-32
  screws". By explicit choice, the holes hold a 3D-printed support (the MB clearance under each hole is not a
  criterion), a +x key ear is kept for the D-41 key, and the design owner implements the trim in the generator.
- Consequence: the outline area falls from 4212.2 to 2241.6 mm² (53 %); the bounding box is 40.02 x 64.81 mm. The
  nearest item to each hole centre is 4.50 mm (MH1, D103 courtyard), 4.53 mm (MH2, C129 courtyard), 4.75 mm (MH3, J102
  courtyard) and 4.65 mm (MH4, /T2C track). No part, track or via moved, and no plane copper was removed. The trim tool
  rounds the outline to 0.01 mm and simplifies it with a 0.05 mm tolerance: the -x vertices sit at x 18.58 (0.004 mm
  outside the D-39 edge; the D-51 terminal gap stays 2.45 mm or more) and a head disc can overhang the edge by up to
  0.052 mm. A CR rotated 180 degrees lands on J-BL and J-FC only (D-41 amended). After the trim, `gen/silk_refs.py`
  re-placed the references: C110 had no clear position and moved to F.Fab, so 19 references are on F.Fab only (D-59).
  The fab package `fab/cr_2026-11-13/` was re-exported. The D-46 J-TAP latch finger access stays open; MH3 and R175
  lie on the +x/-y side of J102. (**Superseded 2026-11-13:** "The D-46 J-TAP latch finger access stays open"; operator
  ruling 2026-11-13 (Review 1/2: J102, J1-TSW, W6-W7 (connector and lead-pad geometry),
  local_923ffa1c-f985-43ad-8510-7faea2e5f5d7, chat 2026-11-13) closes it, "That is enough room" (D-46).) Reversal: restore `cr/cr.kicad_pcb` from the D-59 commit and run `gen/silk_refs.py`
  and `gen/export.sh` again, or change `FINAL_OUTLINE`, `KEY_EAR` or `MOUNTING_HOLES` and run `gen/trim_cr.py` on the
  routed board. The proposal record is the routing session's `routing_r9_cr/outline_trim/TRIM.md`.
  **Amended 2026-11-13 (D-62):** the 18-vertex outline is replaced by the D-62 outline (10 corners with 1.0 mm
  fillets, edges at multiples of 30 or 45 degrees, 2327.7 mm²; bounding box unchanged at 40.02 x 64.81 mm). MH2 moves
  to (54.85, 68.79); MH1, MH3 and MH4 do not move. The -x vertices sit exactly on x 18.584, so the 0.004 mm overhang
  stated above no longer applies; the largest head-disc overhang is 0.001 mm (MH1, MH4). C110 is back on the
  silkscreen, so 18 references are on F.Fab only. The area, MH2 position, overhang and F.Fab count above, and the
  4.53 mm nearest-item distance of MH2, are for the D-60 board; the D-62 nearest-item distance of MH2 is not recorded.

**D-61. GND stitching vias and straightened tracks on the trimmed CR (operator requests 2026-11-13).**

- Decision: the finish order of the routed CR is: route, plane vias, `gen/trim_cr.py` (D-60), /GND stitching vias on
  a 2.5 mm grid inside the trimmed GND fill (`tools/pcb/corridor_route/plane_vias.py --stitch 2.5`), the straightening
  pass (`straighten.py`, staircase runs of unlocked signal tracks replaced by straight or 45-degree runs), the
  stitching gap fill (`tools/pcb/corridor_route/stitch_gaps.py <board> <out dir> --y-flip-offset 100`: while a point of
  the filled L4 /GND pour lies more than 3.54 mm from a /GND via or plated hole, a via is added at the nearest legal
  site to the worst point), then `gen/silk_refs.py`. The board is the routing session's `07a6181` (merge `75f4504` of the D-60 board `779c419`),
  merged here. The D-60 outline and holes do not change. For the routed CR, the router's stitching replaces the
  generator's `route.py stitch()`; the two must not both run on one board. `gen/trim_cr.py` refuses a board that is
  already trimmed.
- Reason: the operator asked the routing session for both changes on 2026-11-13. The D-58 to D-60 board had only
  6 /GND vias, because the `ROUTE_SKIP_FR=1` build skips `route.py stitch()`, so the D-20 rule (L4 stitched to L2 at a
  pitch of at most 5 mm) was not met and no check measured it. Stitching and straightening after the trim read the
  new edge and the hole keep-outs from the board, so the trim data in `gen/cr_geometry.py` stay independent of them.
  The router's stitching applies the plane-via site rules (routed copper, holes, SMD pads and mask openings,
  unflashed pads, keep-outs).
- Consequence: the routing session reports 269 stitching vias inside the trimmed fill; the board has 275 /GND vias.
  Straightening reduces the track segments from 1791 to 768 and the track length from 830.8 to 823.9 mm; vias, pads
  and locked pre-tracks do not move. The references are unchanged (59 on F.Silkscreen, 19 on F.Fab). A new
  constraint-check row measures D-20 over the filled L4 pour: with 293 stitch points (/GND vias and /GND plated holes),
  the largest distance to the nearest point is 4.08 mm at (36.0, 26.7), against 3.54 mm for a 5 mm square pitch, so the
  row read FAIL. The 2.5 mm grid places a via only within 1.25 mm of each node, and the comparator cluster blocks most
  sites near (32.5, 33.7) (routing session, request R9-03). The gap fill added three /GND vias at (36.04, 26.87),
  (34.34, 33.62) and (34.04, 59.52) (`cr/stitch_gaps.md`); with 296 stitch points the largest distance is 3.47 mm at
  (31.0, 34.7), and the row passes. (**Superseded 2026-11-13:** "The gap is open and is returned to the routing session
  (request R9-03).") An intermediate board
  (`8521bf8`: stitching and straightening before the trim; 19-vertex outline of 2248.3 mm², MH2 (55.10, 67.54), MH4
  (24.23, 25.18); largest stitching gap 3.80 mm) is superseded by this order. Reversal: restore `cr/cr.kicad_pcb` from
  `779c419`; the D-20 stitching then fails with 6 /GND vias. **Amended 2026-11-13 (D-62):** the finish was re-run in
  this order on the D-62 outline; the stitching, straightening and reference counts of this entry are for the D-61
  board (`437d2d7`).

**D-62. CR outline with limited edge angles and filleted corners (operator ruling 2026-11-13; route-race r9 change
request R9-04).**

- Decision: the D-60 trim is redone under three rules. Every outline edge runs at 0, 30, 45, 60, 90, 120, 135 or
  150 degrees (`TRIM_ANGLES` in `gen/cr_geometry.py`). A slanted edge is at least 2.0 mm long (`TRIM_MIN_EDGE`). Every
  corner carries a 1.0 mm fillet, drawn as a true Edge.Cuts arc (`FILLET`). Before the fillets, `FINAL_OUTLINE` has
  10 corners: (58.600, 71.043), (55.835, 72.640), (25.266, 72.640), (22.564, 71.079), (18.584, 67.100),
  (18.584, 28.193), (21.845, 22.545), (47.332, 7.830), (56.928, 7.830) and (58.600, 10.726), MB frame. The holes are
  MH1 (26.23, 69.04), MH2 (54.85, 68.79), MH3 (54.85, 11.43) and MH4 (24.48, 25.18); MH2 moves from (54.85, 63.79)
  (D-60), and the other three holes do not move. `gen/trim_cr.py` passes `--angles`, `--min-edge` and `--fillet` to
  `tools/pcb/corridor_route/trim_outline.py` and reproduces the outline from the routed board `621fb28`.
  `gen/silk_refs.py` and `gen/check_constraints.py` read the outline with `GetBoardPolygonOutlines`, so the arcs are
  part of the outline that they check. The D-60 hole keep-outs, head discs, zone inset and router edge band are
  unchanged.
- Reason: the operator ruled on 2026-11-13, in a conversation with the routing session: "Keep the trim rectilinear,
  or with 30, 45, or 60deg angles. Fillets on corners is good though. Note that PCB fabs will charge based on the
  enclosing rectangle, so trimming away material within the rectangle is generally unnecessary, though it may look
  better. In our case, keeping more of the MB exposed underneath is a small benefit. Redo the trim with my new
  ruleset."
- Consequence: the filleted outline area is 2327.7 mm² (D-60: 2241.6 mm²), that is 55.3 % of the D-39 rectangle. The
  bounding box stays 40.02 x 64.81 mm, so the enclosing rectangle that the fabricator charges for does not change. The
  -x vertices now sit exactly on x 18.584, because `trim_outline.py` snaps them to the D-39 edge; the 0.004 mm overhang
  of D-60 is gone. A CR rotated 180 degrees lands on J-BL (7.73 mm of x overlap) and J-FC (7.73 mm), so the D-41 key
  holds. The fillet at the corner (58.600, 71.043) clips 0.027 mm² off the D-60 ear box. Therefore the ear row of the
  constraint check is measured against the corners before the fillets, and the D-41 key row is the functional check. The
  routing session re-ran the D-61 finish on the trimmed board: `plane_vias.py --stitch 2.5` placed 279 vias,
  `straighten.py` reduced the track segments from 1791 to 769 and the track length from 830.8 to 824.5 mm, and
  `stitch_gaps.py` added three /GND vias at (36.04, 26.88), (34.29, 33.53) and (33.54, 59.53). Then `gen/silk_refs.py`
  placed 60 references on F.Silkscreen and 18 on F.Fab only: C107, C115, C130, C132, D105, D106, R122, R130, R131B,
  R147, R184-R189, U110 and W3. C110 is back on the silkscreen (D-59, D-60). `gen/sync_fields.py` wrote the J102 part
  number 43045-1012 and the cable 2147561101 (D-41 Review 1/2 ruling). The largest D-20 stitching gap is 3.51 mm at
  (43.0, 44.8) in the constraint check, against 3.54 mm (`stitch_gaps.py`, sampling at 0.50 mm, reports 3.52 mm). The
  status line of the package README names the D-62 outline (corrected in `b3437ef`). (**Superseded 2026-11-13:** "The
  status line of the package README still names the D-60 outline and 19 F.Fab references; it is corrected at the next
  re-export."; `b3437ef` corrects the status line.) The fab package `fab/cr_2026-11-13/` and the figures were
  re-exported. The size row of the package README describes the D-62 outline. Its OSH Park row states the confirmed
  stack-up (section 11 item 5) and that OSH Park sells boards in multiples of 3. The quantity is 6 (operator ruling
  2026-11-13, design session, chat 2026-11-13: "Use 6"; two OSH Park lots of 3, one spare against the 5 of the E BOM).
  (**Superseded 2026-11-13:** "the quantity stays '5 (E BOM)' until the operator rules on it."; the ruling sets the
  quantity to 6.) No part, track or via moved in the trim itself. Reversal: restore `cr/cr.kicad_pcb` and the
  `gen/cr_geometry.py` outline and hole data of the D-61 board (`437d2d7`, lineage `b8e3762`) and run `gen/export.sh`
  again. **Amended 2026-11-13:** on the D-62 board, two F.Cu-only necks of the VCHGOUT path fail the IPC-2152
  long-conductor basis at 3.21 A (R9.H26: 21.9 C and 14.3 C). Operator ruling 2026-11-13 (design session, chat
  2026-11-13: "Accept short necks") accepts them, so no part, track, via or pour changes, and the D-62 package stays the
  order package (section 11 item 2).

**D-65. Short In2 via pairs merged onto F.Cu and the J101/C129 stitching vias deleted (operator request
2026-11-13).** The routed board of the operator's cleanup (`547dc11`) has same-net via pairs whose only purpose is a
0.4 to 1.4 mm jog on In2.Cu. The operator asked that SDA, SCL and TS_EXT run on F.Cu without the In2 jog, and that
every other such pair be removed or consolidated without a re-route. In addition, the pre-order review
(`bom_2026-11-13/PREORDER_REVIEW.md` items 3.1.1 and 3.1.2) found a /GND via on J101 pad 9 (D-37) and three /GND vias
0.076 mm from the mask openings of other nets, which equals the OSH Park 4-layer mask alignment of 0.0762 mm.
`gen/via_merge_cr.py` makes the change on the routed board as follows:

- **Both vias deleted** (the F.Cu link is a single segment from pad track to pad track): SDA, SCL, TS_EXT and
  J3V3_1.
- **One via deleted** (the kept via carries the In2 route onward; the deleted one only hopped to it): N_H1M, N_FNP,
  N_UVP and four /3V3 vias at U105, C125 and the two In2 trunk ends at (35.91, 71.86) and (45.74, 69.04).
- **Trackless /GND stitching vias deleted:** (37.50, 53.97) on J101.9, which was also 0.076 mm from the J101.7 mask;
  (48.47, 35.10) at C129.1; (36.78, 56.26) at J101.11.

In total, 18 vias and 32 In2.Cu segments were deleted, and 11 F.Cu segments of the existing 0.1524 mm width were
added (446 to 428 vias). The GATE pair at (42.46, 64.93) and (43.91, 64.78) was tested and kept, because its F.Cu link
crosses /QF. The VCHGIN and VCHGOUT via arrays are current-carrying arrays and were not considered. Via pairs of two
different nets cannot be merged; the closest remaining pairs are 0.15 to 0.17 mm apart edge to edge (CHG_ARM / N_FOP,
FCCNN / FCC_ON, GATE / QF) and stay. No track was rerouted, and no footprint moved.

Result: DRC (`--severity-all --schematic-parity`) gives 0 violations, 0 unconnected items and 0 parity issues. The
constraint check gives 108 pass rows and 0 FAIL, and the D-37 row reads "none". The smallest via-annulus gap to an
other-net mask opening is now 0.110 mm (/GND via at U120.4). The D-20 stitching row reads 300 stitch points with the
largest distance to the nearest one 3.51 mm, unchanged against the 3.54 mm limit. The script reproduces the board
from `e1f05d4` exactly (0 tracks or vias differ). Package: `fab/cr_2026-11-13c/`. Reversal: restore
`cr/cr.kicad_pcb` from `e1f05d4` and export again.

**D-66. W5 by soldered wires: J101 and J201 become 3 x 3 grids of plated wire pads (operator rulings
2026-11-13).** The operator ruled (forked design session, chat 2026-11-13): "Let's remove the J101 and J201", and then
"Change the footprints to through-hole wire pads". The W5 ribbon (FFSD-07-D-12.00-01-N), the two Samtec FTSH-107
headers (CR J101 FTSH-107-01-L-DV, EIB J201 FTSH-107-01-L-DV-K) and the pin-6 key are retired. This closes the J101
part choice and the pin-6 key (section 11 item 13; `bom_2026-11-13/PREORDER_REVIEW.md` items 3.1.3, 3.2.2 and 4.1).
The same rulings keep J1 ("it gives the required board height") and J102 (premade cable), and the EVM J8 lead is
soldered to the J8 pins (no KK housing).

The footprint `WirePads_PTH_3x3_D1.0mm_Pad1.8mm_P2.54mm` (`gen/fplib.py` `wire9`, package key `WIRE9`) uses the
E-pad / W6 / W7 lead-pad geometry: 1.0 mm plated hole, 1.8 mm pad, 2.54 mm pitch, pad 1 square (hole and pad
PLACEHOLDER for 26/28 AWG, TODO(verify: conductor and insulation OD)). The FTSH pin numbers are kept, so every wire
joins J101.n to J201.n. Nine wires remain: pins 1 to 5 and 7 to 10. Pins 11 and 13 were not connected on the CR, and
pins 12 and 14 were redundant ground returns of the ribbon. On the EIB, R265.2 (was ILIM_SENSE to J201.11) and R264.2
(was CE_SENSE to J201.13) are now not connected; both resistors are DNP, and the senses were already dead because CR
J101.11 and J101.13 were not connected (dec2-eib section 4). Table D-66 gives the wire list.

| Wire (J101.n to J201.n) | CR net | EIB net | CR grid position (row, column) | EIB grid position (row, column) |
|---|---|---|---|---|
| 1 | J3V3_1 (R176) | 3V3 | 1, 1 (square pad) | 1, 1 (square pad) |
| 2 | J3V3_2 (R177) | 3V3 | 1, 3 | 2, 2 |
| 3 | GND | GND_J | 1, 2 | 2, 3 |
| 4 | STAT | STAT | 2, 3 | 1, 2 |
| 5 | CE_DRV_J | CE_DRV_J | 2, 1 | 2, 1 |
| 7 | ILIM_REL_A | ILIM_REL_A | 2, 2 | 3, 1 |
| 8 | ILIM_REL_B | ILIM_REL_B | 3, 2 | 1, 3 |
| 9 | GND | GND_J | 3, 1 | 3, 3 |
| 10 | RFC_OFF_J | RFC_OFF_J | 3, 3 | 3, 2 |

Row 1 is the top row of the board view and column 1 the left column. The two grids differ by design: the EIB order
puts each net on the side where its route leaves the grid (up: STAT and ILIM_REL_B; left: CE_DRV_J and ILIM_REL_A;
down: RFC_OFF_J and the GND_J pair to R273), because the CR order forced crossings that the EIB router could not close
(two attempts, with rip-up of up to thirteen nets). The F.Fab layer of each footprint shows the pin numbers.

The change was made in place on the routed boards, without a full re-route:

1. `gen/fplib.py`, `gen/fpmap.py`, `gen/sch.py` and `gen/netlist.py` carry the new footprint, symbol (`JW9`) and
   nets; the schematics and netlists were regenerated (ERC 0 on both boards).
2. `gen/swap_wire9.py <board>` replaces the header at the old centre (CR (40.60, 53.17), EIB (20.00, 31.00)), deletes
   the other-net copper that the plated pads violate and the open-ended tracks of the affected nets.
   `gen/eib_sense_nc.py` takes R264.2 and R265.2 off their nets.
3. `gen/prune_dangling.py <board> <nets>` deletes the dead-end tracks and vias of the affected nets, and
   `gen/finish.sh` (the finishing A* router) closes the unconnected items: CR on F.Cu and In2.Cu (B.Cu stays track-free,
   D-20), 0.1524 mm track; EIB on F.Cu and B.Cu, 0.2 mm track and clearance (D-28).
4. `tools/pcb/corridor_route/straighten.py` straightens the result (CR: the affected nets; EIB: all signal nets,
   three passes, 596 to 332 segments).
5. CR only: `gen/wire9_padvias.py` removes the vias that the router put on the wire pads and ends their tracks in the
   pad, and `gen/wire9_stitch.py` adds three /GND stitching vias between the wire pads at (41.87, 54.44),
   (41.87, 51.90) and (39.33, 51.90), because the D-20 row read 3.70 mm after the swap. One /GND via was moved from
   (36.725, 51.025) to (36.605, 51.025), 0.084 mm to 0.204 mm from the pad 1 mask opening.

On the CR the change is local: J3V3_1, J3V3_2, STAT, CE_DRV_J, ILIM_REL_A, ILIM_REL_B, RFC_OFF_J and CHG_ARM (whose
In2 run crossed the grid and now runs on F.Cu) were re-routed; 428 to 417 vias (corrected 2026-11-13: 420 by count in the board file, including the three `wire9_stitch.py` vias), 838.1 to 818.7 mm of track. On the EIB
the router also ripped up and re-routed 3V3, N_RAIN, nCE_DRV, N_RFIN, N_ISP, N_ISM, Q201_G, Q202_G, REF203, REGN and
N_U203O, and the straightening pass changed 18 nets; 96 to 94 vias (49 AGND unchanged), 604.0 to 500.7 mm of track. The AGND pours,
the AGND stitching (D-63) and the single R273 link between GND_J and AGND are unchanged. Result: DRC
(`--severity-all --schematic-parity`) 0 / 0 / 0 on both boards; CR constraint check 108 pass and 0 FAIL (D-20 3.49 mm,
D-37 "none"); EIB constraint check unchanged (5 pass, 0 FAIL); no via within 0.12 mm of an other-net mask opening on the
EIB, and on the CR none closer than 0.110 mm. Packages: `fab/cr_2026-11-13d/`, `fab/eib_2026-11-13b/`. Reversal: restore
the `cr/`, `eib/` and `gen/` files of the commit before D-66 and export again.

**D-67. U101 changes to the Toshiba TCKE1401NM on the unchanged footprint (operator ruling 2026-11-13).** The
TPS26630RGER has no authorized stock (Digi-Key restock 8-Jul-2027; Mouser and TME 0; every TPS2663x and TPS1663x variant
also 0; `RESPIN_HANDOFF_2026-11-13.md` section 2). The operator ruled (chat 2026-11-13): "Use TCKE1401NM for U101." The
TCKE1401NM,R1F (datasheet Rev. 3.0, 2026-10-09, `references/Datasheets/tcke1401nm.pdf`) has the TPS26630 RGE pin map
(Fig 5.1: VIN, BGATE, DRV, VSYS, UVLO, OVP, GND, dV/dT, ILIM, MODE, EN, IMON, FLAG, PGTH, PGOOD, VOUT, DNC, EP on the same
pin numbers) and a land that the fitted footprint covers (Fig 13.2: 0.24 x 0.58 mm pads on a 3.825 mm span, EP 2.7 mm), so
the footprint, the nets and the copper do not change. The KiCad footprint keeps its name
`TPS26630_RGE0024_VQFN-24_4x4mm_P0.5mm_ThermalVias_CrtYd0.25`. The values change for the TCKE1401NM references:

- **R101** 8.06 kOhm -> **8.45 kOhm 1 %** (CRCW06038K45FKEA): I_LIM = 18.9/R(kOhm) + 0.13 A = 2.37 A typical (Formula 9).
  The datasheet tabulates only the 9 kOhm row (1.84-2.59 A over temperature); scaled, 8.45 kOhm gives about 1.97-2.77 A
  (an extrapolation, TODO(verify: T-C-04)), about 0.21 A above the 1.76 A regen-clamp maximum (TPS26630: 0.30 A).
- **R103** 66.5 kOhm -> **64.9 kOhm 0.1 %** (Panasonic ERA-3AEB6492V; 64.2 kOhm 0.1 % is not stocked) and **R104**
  49.9 kOhm -> **51.1 kOhm 0.1 %** (TNPW060351K1BEEA); R102 stays 845 kOhm. With V_OVPR 1.233 V (1.18-1.298 V) and
  V_UVLOR 1.19 V (1.142-1.224 V): OVP rising 23.19 V typical; with the OVP and UVLO pin leakage, OVP
  rising 21.588-25.019 V, OVP falling 19.899-22.927 V and UVLO rising 9.055-10.548 V (`sim/efuse_decay/RESULTS.md`
  Table 1; `sim/chopper/RESULTS.md` section 5.8) (**Superseded 2026-11-14, sim 5 Table 1, REVIEW PWR-2; marked
  2026-11-15, REVIEW R2-PWR-1 and R2-DOC-3:** "OVP rising 23.19 V typical, 22.19-24.41 V; UVLO rising 9.86 V typical,
  9.46-10.14 V", the bands without pin leakage).
  The OVP band no longer fits 22.6-23.6 V: its low end is 0.09 V below the 22.28 V design clamp (a nuisance OVP trip is
  possible at the tolerance limit) and its high end is 0.41 V above the BQ25798 recommended VBUS maximum (24 V), below the
  BQ25798 VBUS_OVP (25.2-26.2 V). The operator accepted both with the part choice. **Amended 2026-11-15 (REVIEW R2-PWR-1,
  R2-DOC-3):** the acceptance rests on the bands without leakage. With leakage, the OVP rising minimum 21.588 V lies
  0.692 V below the 22.28 V clamp figure, which design J.2 item 81 marks invalid (V_rgn premise); the maximum
  25.019 V lies 1.019 V above 24 V and 0.181 V below the 25.2 V VBUS_OVP minimum. The UVLO rising maximum 10.548 V
  lies 0.348 V above the FR-30 10.2 V threshold (sim 5 section 4.1; design J.2 item 74). The OVP band question is
  design J.2 item 74 (section 11 item 35). (**Superseded 2026-11-14, sim 5 Table 1:** "The UVLO maximum keeps 0.06 V
  below the FR-30 10.2 V threshold.")
- R105 (27.4 kOhm, IMON 0.764 V/A typical), R106s, R129/C129, C101 (22 nF: 7.28 ms at 15.9 V, Formula 2), C102a-c, C103,
  D103 and D107 are unchanged. The IMON gain spreads wider (22.3-33.5 uA/A at 1-2 A, against 25.66-30.14), which T-B-14
  calibration absorbs. Table 10.1 Note 13 ("1 kOhm <= RIMON <= 10 kOhm" when VSYS < 9 V) is accepted as a risk and R105 stays 27.4 kOhm (operator ruling 2026-11-13, chat: "Keep 27.4k"): the note binds only below 9 V, during the UVLO falling band, where CHG_IIN is not used; a 10.0 kOhm 0603 in the parts order allows a swap at assembly. (**Superseded 2026-11-13:** "TODO(verify: Toshiba) Table 10.1 Note 13.")
- Overload: regulated at I_LIM for tCL_PLIM 130-190 ms, then latch-off (MODE open), against 129-202 ms; FLAG asserts
  1.0-3.5 ms into current limiting. The absolute maximum of VIN is 80 V (TPS26630: 67 V), so the D107 clamp (<= 60 V) has
  20 V of margin.

`gen/netlist.py` (U101, R101, R103, R104) and `gen/sch.py` (symbol `TCKE1401NM` with the Toshiba pin names) were changed
and the schematic, ERC and netlist regenerated without `pcbbuild.py`. `gen/sync_fields.py` now also copies Value and
Manufacturer onto the board footprints. Renaming the pins renamed the eight single-pad no-connect nets of U101 (B_GATE ->
BGATE, ~{SHDN} -> EN, NC -> DNC); they were renamed on the board to match. Copper is unchanged (`gen/pcbdiff.py`: 692
segments, 420 vias, 0 differences). The parts come from Mouser (`bom_2026-11-13/mouser_import.csv`). Package
`fab/cr_2026-11-13e/`; its copper equals `fab/cr_2026-11-13d/`, and only the X2 net attributes of the eight U101 no-connect
pads differ in the F.Cu Gerber. Reversal: restore `gen/netlist.py`, `gen/sch.py` and the `cr/` files of the commit before
D-67 and export again.

**D-68. AGND pours keep 0.5 mm from the EIB E lead pads (operator ruling 2026-11-13, chat: "Widen clearance").** The pre-order review
(`bom_2026-11-13/PREORDER_REVIEW.md` item 3.2.1, finding EIB-4) found that the E pads carrying hand-soldered leads (E1, E2,
E3, E5, E7) kept only the zone clearance to the AGND pours on both layers (0.1524 mm as filled; **superseded
2026-11-14, D-70:** "the 0.20 mm zone clearance"; the zones declare 0.2 mm, but the fill follows the 0.1524 mm
`fab_clearance` rule) (the F.Cu pour is D-63), with a 0.05 mm
mask expansion, so a solder blob or flux residue could bridge a lead to AGND. A custom rule now holds the pours 0.5 mm
from any pad of an E footprint on another net (`eib_E_pad_pour_clearance`; E8 is AGND and keeps its connection). The rule
applies to zones only, so tracks and every other spacing keep the fab rule file. It is in `eib/eib.kicad_dru`, and
`gen/make_board.sh` appends it from `gen/eib_pour_rules.kicad_dru` after copying the fab rules, so a regeneration keeps
it. After the refill, the AGND stitching via at (0.81, 43.81), in the corner beside E6, lost its B.Cu pour connection,
because the strip between the E pads and the board edge closed; the via was deleted. Result: the smallest copper gap from
a live E pad to the pours is 0.501 mm on both layers (E7; 0.157 mm measured before, polygon to polygon), the F.Cu pour
area falls from 532.3 to 511.9 mm2 and the B.Cu pour from 585.7 to 562.7 mm2, and the board has 48 AGND vias (49
before). ERC gives 0 messages, DRC (`--severity-all --schematic-parity`) 0 / 0 / 0, and the EIB constraint check 5 pass
and 0 FAIL. Package `fab/eib_2026-11-13c/`; against `fab/eib_2026-11-13b/` only the two copper layers and the PTH drill
file differ. Reversal: restore `eib/eib.kicad_pcb`, `eib/eib.kicad_dru` and `gen/make_board.sh` from the commit before
D-68 and export again.

**D-69. Stencils: 4 mil stainless from OSH Stencils, and U101 exposed-pad paste windows at about 55 % coverage (operator rulings 2026-11-13, chat: "I would order from OSH Stencil" and "Yes, do both").** Both boards are top-side only (no B.Paste). The stencil is 4 mil (0.1 mm) stainless steel, one frameless stencil per board in one order: OSH Stencils prices by area per material and combines the stencils of an order for the discount, so one shared sheet would save only the border between the designs. The smallest paste apertures set the thickness. U101 pins (0.25 x 0.825 mm) give an area ratio of 0.96 at 4 mil and 0.76 at 5 mil; the EIB U202 SC-70 pads give 1.24 and 0.98; IPC-7525 asks at least 0.66. OSH Stencils states 0.001" minimum aperture and 0.0007" laser spot for stainless steel, and limits polyimide to a few uses and parts 0402 or larger. The D-56 window-pane apertures (four 0.675 mm squares, 25.0 %) gave too little paste under the U101 exposed pad at 4 mil. `gen/fplib.py` (vqfn24) now makes each quadrant aperture a polygon: the square from the 0.125 mm half-web to 0.05 mm inside the 2.7 mm pad edge, minus a 0.31 mm keep-out circle around each of the nine via centres. Measured on the board (`cr/constraint_check.md`): 4 apertures, 54.6 % coverage, smallest gap to a via drill 0.160 mm (D-56 asks 0.15 mm), web 0.25 mm. `gen/u101_paste_swap.py` replaced the four paste-only pads of U101 on the board; pins, nets and copper are unchanged (`gen/pcbdiff.py`: 0 differences). DRC (`--severity-all --schematic-parity`) gives 0 / 0 / 0 and the constraint check 108 pass and 0 FAIL; the check now measures the aperture polygons instead of their bounding boxes. Package `fab/cr_2026-11-13f/`; against `fab/cr_2026-11-13e/` only `cr-F_Paste.gtp` differs, so the OSH Park order may use either package, and the stencil uses 13f. The solder paste is not identified (a Type 4 paste is the usual choice for 0.5 mm pitch). Reversal: restore `gen/fplib.py`, the U101 library footprint and `cr/cr.kicad_pcb` from the commit before D-69 and export again.

**D-70. AGND pour clearance of 0.5 mm extended to the EIB J201 wire pads (2026-11-14, REVIEW EIL-0).**

- Decision: the D-68 zone-only rule `eib_E_pad_pour_clearance` also covers J201. Its condition is now `A.Type ==
  'Zone' && (B.memberOfFootprint('E*') || B.memberOfFootprint('J201'))`, in `gen/eib_pour_rules.kicad_dru` and
  `eib/eib.kicad_dru`. All zones were refilled with the board beside its own `.kicad_pro` and `.kicad_dru`.
- Reason: the nine W5 wires are hand-soldered into J201 (D-66), the same joint type as the E leads of D-68. Before the
  change, J201 pad 1 was 0.1529 mm and pads 2 to 10 were 0.1572 mm from the AGND pours on F.Cu and B.Cu.
- Result: the smallest J201 gap is 0.5005 mm on both layers, and the E pads stay at 0.5007 mm. On F.Cu, the AGND
  island of 434.74 mm² (38 vias) splits into 264.90 mm² (22 AGND vias) and 147.96 mm² (15 AGND vias). A new 0.95 mm²
  island left of J201 column 1 holds one AGND via. On B.Cu the island count stays 5, and the areas fall by at most
  10.8 mm². Every new or changed island holds at least one AGND stitching via. DRC reports no unconnected item and no
  dangling via.
- Correction: both AGND zones declare a 0.2 mm local clearance, but the fill follows the 0.1524 mm `fab_clearance`
  rule of the 2-layer rule file. The pre-change J201 gaps agree with 0.1524 mm. D-28 and D-68 are corrected in place.
- Regeneration: `gen/make_board.sh` appends `gen/eib_pour_rules.kicad_dru`, which now holds the extended condition, so
  a regeneration keeps the rule; the zones must then be refilled. On a board kept in place, run
  `gen/eib_j201_pour_clearance.py` (idempotent; step 1 of the EIB order in section 2).
- Evidence: `update_2026-11-14/notes_eib.md` section 2.1 (pcbnew distance script over the filled polygons;
  `gen/pcbdiff.py`: 0 tracks and 0 vias changed, two zones changed in fill only).
- Reversal: restore the two rule files from `014c745` and refill the zones.

**D-71. No solder paste on the EIB DNP pads (2026-11-14, REVIEW EIB-7, EIL-6, BOM-2).**

- Decision: each of the 14 DNP footprints (C203, C204, E4, E6, R258-R265, U203, U204) carries a footprint-level
  solder-paste margin of -2.0 mm. The margin exceeds half of every pad of these footprints, so KiCad plots no paste
  aperture for them.
- Reason: the F.Paste layer of `fab/eib_2026-11-13c/` has 94 flashes, 32 of them on DNP pads (REVIEW EIL-6). Removing
  F.Paste from the pad layer sets gave 12 `lib_footprint_mismatch` warnings in DRC. The footprint-level margin is not
  part of that comparison, so DRC stays at 0.
- Result: an F.Paste Gerber exported to scratch has 62 flashes, 0 apertures on DNP pads and 0 fitted SMD pads without
  an aperture. B.Paste has 0 flashes. Copper, mask, nets and fields are unchanged.
- Regeneration: DNP is a per-instance build choice (D-49), so the library and `gen/fplib.py` do not change.
  `gen/pcbbuild.py` does not reproduce the margin; re-run `gen/eib_dnp_paste.py` after any EIB regeneration.
- Evidence: `update_2026-11-14/notes_eib.md` section 2.2. The EIB package README (`gen/fab_readme.py`) and the EIB
  stencil row of `bom_2026-11-14/eib_bom.csv` (BOM-1, BOM-2; D-83) state the result.
- Reversal: run `gen/eib_dnp_paste.py` with a zero margin, or restore `eib/eib.kicad_pcb` from `014c745`.

**D-72. Pin-1 dots and SMA cathode bars on the silkscreen (2026-11-14, REVIEW CRL-3, INT-5, EIL-2): an exception to
D-12a.**

- Decision: a filled F.Silkscreen dot (radius 0.10 mm, stroke 0.15 mm, outer diameter 0.35 mm) sits off the outer
  corner of pad 1. On the EIB it marks U201 (DCT SSOP-8), U202 (DCK SC70-5), Q201-Q203 (SOT-23), U203 and U204
  (SOT-23-6). On the CR it marks U101 (VQFN-24), D104-D106 (SOT-23), U102, U103, U107, U119, U120 (SOT-23-6) and U105,
  U106, U110, U118 (DCT SSOP-8). D103 and D107 (SMA) carry a 0.15 mm cathode bar, 1.8 mm long, beyond pad 1, which is
  the cathode of both diodes (D103 pad 1 /VCHGOUT, D107 pad 1 /VCHGIN).
- Positions (footprint coordinates, mm): EIB `PIN1_DOT` SSOP-8 (-2.75, -1.45), SC70-5 (-1.75, -1.15), SOT-23 (-1.9,
  -1.5), SOT-23-6 (-2.0, -1.5). CR `PIN1_DOT_CR` SOT-23 (-1.9, -1.5), SOT-23-6 (-1.55, -1.55), SSOP-8 (-2.75, -1.35),
  VQFN-24 (-2.4, -2.4); `CATHODE_BAR_CR` at x -3.45, y -0.9 to 0.9. The shared SOT-23-6 position put the dot over a
  tented via drill at U102, U107 and U119, and the shared SSOP-8 position came within 0.018 mm of a via drill at U110;
  a search over every CR instance chose the CR positions.
- Library: `gen/fplib.py` gained `_pin1_dot()`, `PIN1_DOT`, `_pin1()`, `PIN1_DOT_CR`, `CATHODE_BAR_CR` and
  `_cathode_bar()`. Four EIB and five CR library footprints were written from `gen/fplib.py`; each differs from git
  HEAD by the one mark line. The board instances carry the same mark, so DRC reports no library mismatch. The EIB
  footprints regenerated with `BOARD = "eib"` are line-identical before and after the CR change.
- Result: no mark overlaps a via drill; several overlap a tented via ring under the mask. Gaps to the nearest mask
  opening are 0.156-0.181 mm on the EIB and 0.07-0.80 mm on the CR (`update_2026-11-14/notes_cr.md` section 2.2
  table). The EIB U203 (DNP) and Q203 dots are 0.98 mm apart and stay: the SOT-23 land of Q203 admits one orientation
  only (`update_2026-11-14/notes_phaseB_silk_eib.md` section 3.2).
- Regeneration: a library regeneration with `gen/fplib.py` reproduces the marks, and `gen/pcbbuild.py` places them
  with the footprints. On a board kept in place, run `gen/cr_pin1_marks.py` and `gen/eib_pin1_marks.py` first in their
  sequences (section 2). A change of a mark position is made in `gen/fplib.py` and needs a clearance check on both
  boards.
- Reversal: restore `gen/fplib.py`, the nine library footprints and the two boards from `014c745`.

**D-73. Wire-pad maps and lead labels (2026-11-14, REVIEW INT-2, EIL-1, INT-5).**

- Decision: the J101 and J201 pads have 0.74 mm gaps and no room for labels beside them, so each board carries a
  F.Silkscreen map of its 3 x 3 wire-pad grid, top view. Each cell reads "pin net". The cells are built from the pads
  and nets of the board, so they agree with `cr/cr.net`, `eib/eib.net` and Table D-66. Short names: 3V3 = /J3V3_1 and
  /J3V3_2 (CR) or /3V3 (EIB), GND = /GND (CR) or /GND_J (EIB), STAT = /STAT, CE = /CE_DRV_J, RLA = /ILIM_REL_A, RLB =
  /ILIM_REL_B, RFC = /RFC_OFF_J. Text is 0.8 mm high with a 0.15 mm stroke.
- CR J101 map: in the strip right of the J1 pin column, x 47.70-58.30 mm, each row level with its pad row (y 50.63,
  53.17 and 55.71 mm), between the rows of /GND stitching vias. Its header "J101 top view" and a separator line are
  D-78. Rows (top view): 1 3V3, 3 GND, 2 3V3 / 5 CE, 7 RLA, 4 STAT / 9 GND, 8 RLB, 10 RFC.
- EIB J201 map: above the board marking, ink box x 8.16-22.70 mm, y 43.14-48.18 mm, header "J201 top view", two 0.15
  mm separator lines. Rows (top view): 1 3V3, 4 STAT, 8 RLB / 5 CE, 2 3V3, 3 GND / 7 RLA, 10 RFC, 9 GND. The two maps
  differ by design (Table D-66).
- CR lead labels: the W3 reference moves from F.Fab to F.Silkscreen at (22.50, 54.50) mm. W6 carries "TS" (pad 1,
  TS_EXT) and "GND" (pad 2); W7 carries "SDA" (pad 3), "GND" (pad 2) and "SCL" (pad 1), each on the +x side of its
  hole. The W7 reference moves to (53.51, 44.13) mm. W1, W2 and W4 are unchanged.
- EIB E labels (B.Silkscreen): E8 TP49, E3 TP33, E4 DNP, E2 JP14, E7 TP38, E1 JP12, E5 TP36 and E6 DNP, from the A.5
  wiring table of the design document (E4 and E6 carry no lead, r9-2).
- Scripts: `gen/cr_wire_labels.py`, `gen/cr_lead_labels.py`, `gen/eib_wire_labels.py` (idempotent; section 2 gives the
  order). `gen/cr_wire_labels.py` also removes the D-78 header text and separator in its idempotency step, so a re-run
  must be followed by `gen/cr_silk_fix_r3.py`.
- Open: the W6 "GND" label is 0.086 mm from a mask opening; it was placed under the phase A 0.05 mm rule and passes
  DRC, but it misses the 0.10 mm phase B rule (operator question). The W3 reference overlaps the courtyard ring of a
  J1 post by about 0.2 mm; TODO(verify: assembled board) whether the post hides it. **Amended 2026-11-16 (D-95):**
  the W6 label half is closed; the operator accepted the label as placed. The W3 half stays open as an inspection
  step on the assembled CR.
- Evidence: `update_2026-11-14/notes_cr.md` sections 2.1 and 2.4, `update_2026-11-14/notes_eib.md` section 2.5,
  `update_2026-11-14/notes_phaseB_silk_cr.md` section 5. DRC 0 / 0 / 0.
- Reversal: delete the map and label texts, or restore the boards from `014c745`.

**D-74. Reference designators re-placed and the EIB board marking (2026-11-14, phase A; REVIEW CRL-7, EIL-2, EIL-7).**

- CR: the R107 reference lay inside the J102 body outline and was hidden once J102 is fitted. No unambiguous top-side
  position exists within 4 mm of R107, so the reference is on B.Silkscreen, mirrored, 1.0 x 1.0 mm, over R107 at
  (42.63, 62.25) mm. The C102c reference left the U101 pin-1 corner; D-78 then moved it to the bottom side.
  `gen/cr_silk_refs_r2.py` makes both changes.
- EIB: `gen/eib_silk_refs_r2.py` re-placed every C, R, Q and U reference and J201 under an unambiguity rule: the gap
  to every other courtyard is at least max(2 x d_own, d_own + 0.15 mm), with DNP footprints counted as other parts.
  D-78 tightened the rules.
- EIB board marking: the two texts "EIB r8" and "2026-11-11" became one text "EIB r8 2026-11-14", 0.8 mm high with a
  0.15 mm stroke (`gen/eib_board_marking.py`). D-78 moved it clear of the H1 keep-out.
- Evidence: `update_2026-11-14/notes_cr.md` section 2.3, `update_2026-11-14/notes_eib.md` sections 2.4 and 2.6.
- Reversal: restore the boards from `014c745`.

**D-75. J1 pin 18 joins the F.Cu VCHG pour solidly (2026-11-14, REVIEW CRL-4).**

- Decision: the board rule `cr_J1_pin18_solid` in `cr/cr.kicad_dru` (condition `A.Type == 'Pad' &&
  A.memberOfFootprint('J1') && A.Pad_Number == '18'`, constraint `zone_connection solid`). A rule keeps the J1
  instance equal to its library footprint, so `gen/fplib.py` does not change. Pin 19 and W3 keep their thermal
  reliefs.
- Reason: VCHG has no inner-layer copper, so the whole pin-18 current crosses the F.Cu connection to the VCHG_L1 pour.
  The basis is 3.21 A battery-side current shared 60/40 by pins 18 and 19, that is 1.93 A per pin, and A.8 asks for
  VCHG copper at least 2.0 mm wide on 1 oz (design document A.8 and H.22). With thermal reliefs, two diagonal 0.6 mm
  spokes reached pin 18: 1.22 mm of copper on a ring of radius 1.10 mm (pin 19: 2.43 mm).
- IPC-2152 figures (baseline fit `ipc2152_area_mil2` of `r9_calc.py`, 35 um clad only, long-conductor basis;
  `update_2026-11-14/notes_cr.md` section 2.5): before, 1.22 mm = 66.2 mil² carries 2.09 A at a 10 C rise, with a rise
  of 8.3 C at 1.93 A and 27.7 C at 3.21 A (pin 19 open or a poor joint). After, 4.07 mm = 220.8 mil² gives 2.1 C at
  1.93 A and 6.6 C at 3.21 A.
- Result: the VCHG_L1 fill grows from 12.489 to 15.220 mm², and GND_L1_fill shrinks from 1499.920 to 1499.684 mm². A
  control refill without the rule changed no zone. The constraint rows are unchanged, except that six D-56 escape rows
  report 0.13 mm² less free area (all pass).
- Assembly consequence: pin 18 is a TSW post soldered from the top side. The solid joint heats the whole F.Cu VCHG
  pour, so it needs a higher iron setting or a larger tip and a longer dwell than pin 19 or W3.
- Regeneration: `gen/make_board.sh` copies `tools/pcb/fab_rules/fab_4layer_oshpark_only.kicad_dru` over
  `cr/cr.kicad_dru`, so `cr/cr.kicad_dru` no longer equals the fab rule file. After any regeneration, run
  `gen/cr_j1_pin18_solid.py`; it adds the rule and refills the 16 zones.
- Reversal: delete the rule from `cr/cr.kicad_dru` and refill the zones.

**D-76. Stack-up blocks in both boards (2026-11-14, REVIEW CRL-6).**

- CR: the `(setup)` section holds the OSH Park standard 4-layer stack (docs.oshpark.com/services/four-layer/, read
  2026-11-15): outer copper 0.0432 mm finished (1 oz clad and plated), inner copper 0.0175 mm (0.5 oz clad), L1-L2 and
  L3-L4 prepreg FR408HR 2113 0.1999 mm with Dk 3.61 at 1 GHz, L2-L3 core FR408HR 0.9906 mm, purple PSR-4000BN mask
  0.0152 mm on both sides, white silkscreen, ENIG. The layers sum to 1.542 mm against the 1.6 mm nominal; the board
  thickness stays 1.6 mm. OSH Park states no loss tangent, so the KiCad default 0.02 stays.
- EIB: the OSH Park 2-layer stack (docs.oshpark.com/services/two-layer/, read 2026-11-14): copper 0.035 mm, FR4 core
  1.51 mm (derived so that the stack sums to 1.6 mm; Dk 4.5 at 10 MHz), purple mask 0.01 mm (KiCad default), white
  silkscreen, ENIG.
- Copper note: the IPC-2152 figures of D-75 and of R9.H26 count only the 35 um clad. The finished outer copper is
  0.0432 mm, so those figures are conservative.
- Scripts: `gen/cr_stackup.py`, `gen/eib_stackup.py`. The pcbnew API of this build has no BOARD_STACKUP access, so
  each script writes the block as text and normalizes it by a pcbnew load and save. The generator does not write the
  block; re-run the scripts after any regeneration.
- Evidence: Gerber job files exported to scratch read the thickness, finish, mask colour, legend and the layer
  thicknesses above (`update_2026-11-14/notes_cr.md` section 2.6, `update_2026-11-14/notes_eib.md` section 2.7).

**D-77. NPTH check gate in the export (2026-11-14, REVIEW CRL-8).**

- Decision: `gen/npth_check.py` measures, for every NPTH pad on every copper layer, the gap from the hole edge to the
  nearest copper (pads, tracks, vias, zone fills). Copper on the hole fails; a gap below 0.254 mm is a warning.
  `gen/export.sh` runs it after DRC and writes `reports/npth_check.txt`; with `set -e`, a failure stops the export.
- Reason: OSH Park decides plating from the copper under a drill (docs.oshpark.com, DipTrace plated-vias page, read
  2026-11-14). The KiKit OSH Park preset writes one MixedPlating drill file, which is acceptable only when no copper
  lies on an NPTH hole. The `drill/` folder keeps separate PTH and NPTH files for other fabs.
- Result: EIB H1 and H2 (3.2 mm): nearest copper 1.896 mm and 1.893 mm, pass. CR: 6 NPTH holes, pass; the J102 pegs
  (1.02 mm) have 0.254 mm to the GND zones on F.Cu, In1.Cu and B.Cu (equal to the warning threshold) and 0.319-0.344
  mm on In2.Cu; MH1-MH4 (3.70 mm) have 2.131-2.201 mm.
- Evidence: `update_2026-11-14/notes_eib.md` section 2.8, `update_2026-11-14/notes_cr.md` section 2.7.

**D-78. Silkscreen fixes after the independent check of phase A (2026-11-14, phase B; defects D1 to D4).**

- EIB board marking (D1): at (12.0, 49.05) mm the marking reached 3.11 mm from the H1 centre, inside the 3.55 mm
  keep-out, and its strokes lay over two via drills. It is now at (14.18, 49.15) mm: ink x 8.07-20.37 mm, y
  48.60-49.59 mm, 5.03 mm from the H1 centre. The bottom row has via drills at x 6.21, 11.96, 16.46 and 23.21 mm, so
  no via-free span of 12.3 mm exists; the position has the largest stroke-to-drill gap of a 0.01 mm search, 0.045 mm.
  `gen/eib_board_marking.py` asserts the hole, edge, map and drill rules on every run.
- CR C102c reference (D2): its ink ended 0.14 mm above the D107 cathode bar, so the bar read as its underline. No
  top-side position exists, even with relaxed rules. The reference is on B.Silkscreen, mirrored, at (42.23, 39.71) mm,
  1.0 x 1.0 mm.
- CR J101 header and separator (D3): the header reads "J101 top view" (the J101 reference field plus a "top view"
  text, 0.8 mm high, 0.6 mm character width). A 0.15 mm vertical separator at x 47.349 mm, y 50.16-56.19 mm divides
  the J1 pin column from the map, 0.275 mm from the J1 mask openings and 0.276 mm from the map texts.
- CR references over another courtyard (phase A check): R176 stays on F.Silkscreen at (34.11, 48.08) mm, 0.35 mm from
  the nearest other courtyard. C102a, C119, U119, C131 and U107 move to B.Silkscreen, mirrored, over their parts, with
  0.0 mm² overlap with other courtyards.
- CR board marking: the CR carried none. "CR r8 2026-11-14" is on F.Silkscreen at (44.83, 85.61) mm below J102, 0.8 mm
  text, 0.15 mm stroke, 0.23 mm from the nearest obstacle.
- CR rules for every moved or new text: height at least 0.8 mm, stroke 0.15 mm; ink at least 0.10 mm from mask
  openings, 0.15 mm from holes, 0.05 mm from via drills, 0.30 mm from silkscreen graphics, 0.10 mm from other texts
  and 0.25 mm inside the edge; no overlap with another courtyard or the own F.Fab body.
- EIB references (D4): `gen/eib_silk_refs_r2.py` gained a 0.10 mm mask gap (was 0.05 mm), no stroke over a via drill,
  a spread pass and an orphan rule. A reference whose text centre lies nearer an unlabelled fitted part than its own
  part leaves the top side. Result: 18 of the 26 fitted references are on the top side (phase A: 22). C201, C202,
  R251, R252, R254, R271, U201 and U202 have mirrored B.Silkscreen texts and F.Fab references. R253 and R273 now have
  0.89 mm between their inks (was 0.29 mm). **Amended 2026-11-16 (D-95):** R252 breaks no phase B rule at its phase
  A position. It leaves the top side because the search orders by candidate count and never offers the space again
  after the orphan rule removes U202.
- Operator question: the stricter EIB rule set is applied. The phase A rule set (22 fitted on top, 15 references
  within 0.10 mm of a mask opening, 5 over a via drill) is restored through `MASK_GAP`, `DRILL_HARD` and the
  `orphan_check()` call of `gen/eib_silk_refs_r2.py`. **Amended 2026-11-16 (D-95):** the operator kept the phase B
  rule set ("I accept keeping it the way it is"); the question is closed.
- Bottom-side references: 7 on the CR (C102a, C102c, C119, C131, R107, U107, U119) and 8 on the EIB. They can be read
  only before the CR is plugged onto the MB and before the EIB is mounted. The assembly instructions must state this.
- Map ownership (fix round 2026-11-15, check1 issue 12): the CR map headed "J101 top view" belongs to J101, the
  W5 wire-pad grid. It stands in the strip right of the J1 pin column (D-73) because no space exists beside J101.
  Its cells name J101 pads and nets only, never J1 pins.
- Exception: the CR W6 "GND" label (`gen/cr_lead_labels.py`) is 0.086 mm from a F.Mask opening. It was placed with
  the phase A 0.05 mm margin, not with the 0.10 mm rule above, and it passes DRC
  (`update_2026-11-14/notes_phaseB_silk_cr.md` section 4 item 4). It stays as placed by operator ruling (D-95). Its
  strokes also lie over the drill of the tented /GND via at (25.392, 39.097) (`update_2026-11-14/notes_cr.md` line
  143), and its ink box is 0.0045 mm from the W2 courtyard line. The CR text rules above formally cover only texts
  moved or added in phase B; the W6 label is a D-73 text. (**Superseded 2026-11-16, D-95:** "It stays until the
  operator rules on a further silkscreen pass.")
- Residual observations (check1 issue 12, no DRC item): the W3 reference overlaps the J1 courtyard by about 0.2 mm;
  tented vias lie under "U106", under "r8" of the EIB marking and under the EIB bottom E labels. A further
  silkscreen pass is an operator question. **Amended 2026-11-16 (D-95):** the W6 "GND" label over a tented /GND via is
  an observation of the same kind. The operator ruled no further pass for the W6 label and the EIB references; the
  W3/J1 check stays open as an inspection step on the assembled CR (section 11 item 29).
- Open: stroke-to-drill gaps of 0.003 mm (R258), 0.006 mm (R253), 0.023 mm (C204), 0.045 mm (EIB marking) and 0.054 mm
  (U202, bottom). TODO(verify: OSH Park silkscreen registration tolerance). The vias are tented, so an overlap clips a
  stroke edge only.
- Scripts: new `gen/cr_silk_fix_r3.py` and `gen/cr_silk_refs_report.py` (writes `cr/silk_refs.md`); changed
  `gen/eib_board_marking.py`, `gen/eib_silk_refs_r2.py` and the idempotency step `mine()` of `gen/cr_wire_labels.py`.
  Section 2 gives the run order.
- Evidence: `update_2026-11-14/notes_phaseB_silk_cr.md` and `update_2026-11-14/notes_phaseB_silk_eib.md`: DRC 0 / 0 /
  0, constraint checks identical, `gen/pcbdiff.py` against the phase A boards 0 segments, vias and zones changed,
  kicad-cli 3-D renders of both sides inspected.
- Reversal: restore the reference fields and texts from the phase A boards or from `014c745`.

**D-79. D103 stays the ordered STPS2H100A; the onsemi MBRA2H100T3G is an order alternate (2026-11-14, REVIEW PWR-0,
sim 1).**

- Decision: D103 stays STMicroelectronics STPS2H100A (`bom_2026-11-13/cr_bom.csv` line 11). The swap to the onsemi
  MBRA2H100T3G is an operator question. The opt-in file `bom_2026-11-14/digikey_optional.csv` carries it as a
  labelled alternate line (MBRA2H100T3GOSCT-ND, D-83): BOM quantity 2 for a test fit on two CRs, order quantity 3
  (the D103 decision recommends 2 to 3 parts). (**Superseded 2026-11-14, fix round 2026-11-15:**
  "`bom_2026-11-14/digikey_import.csv` carries it as a labelled alternate line"; that line ordered 8 parts for a
  BOM quantity of 6.)
- Fit: the MBRA2H100T3G fits the existing `D_SMA_CrtYd0.25` land. onsemi CASE 403D Issue J (98AON04079D) gives HE
  4.83-5.59 mm, lead width 1.27-1.63 mm and L 0.76-1.52 mm, so the leads span |x| 0.895-2.795 mm. The board pads are
  2.5 x 1.8 mm at x = +-2.0 mm and cover |x| 0.75-3.25 mm. Style 1 has pin 1 = cathode, which matches pad 1 = /VCHGOUT
  = K (`cr/cr.net`).
- Criteria (design document B.4 D103 row and T-A-05): the alternate meets the voltage, SMA, IR and IFSM criteria (IFSM
  130 A against 75 A; onsemi MBRS2H100/D Rev. 16 p.2). It fails the T-A-05 limit "VF at 3 A <= 0.5 V" (about 0.82 V
  from Fig. 2), as the STPS2H100A also does. Neither datasheet gives a pulse rating for criterion (4), 130 A for at
  most 1 us.
- Simulation (`sim/hardshort/RESULTS.md` rev 2, sections 5.1 and 6): with any D103, U101 OUT reaches -3.8 to -7.8 V
  and stays below -0.3 V for 2.9-11.2 us. The alternate gives a 1.2-1.3 V shallower minimum and a plateau of -1.44 V
  against -2.69 V. However, it keeps OUT below -0.3 V longer (8.9 us against 7.8 us nominal), and its IR maximum at
  125 C is 1.5 mA against 1 mA. No SMA Schottky holds OUT above -0.3 V.
- Consequence for the test order: run T-C-04 step (2) last, or replace it by the 2 ohm fast-trip short of sim 1
  section 6 item 2. Design revisions r9-25 and r9-26 restated J.1 item 5 from sim 1 and superseded its TPS26630
  statements; the T-C-04 repetitions on the only U101 are design J.2 item 84 (section 11 item 42). (**Superseded
  2026-11-15, REVIEW R2-DOC-14:** "The acceptance basis of J.1 item 5 still cites TI guidance for the TPS26630; a
  Toshiba statement or the T-C-04 survival result must replace it (design-document change, outside this log).")
- Open: TODO(verify: onsemi / ST pulse rating) for criterion (4); the T-A-05 "VF at 3 A" limit needs an operator
  restatement; the STPS2H100A IR at 24.4 V / 60 C is not tabulated.

**D-80. R130 and R131A stay 100 ohm (2026-11-14, REVIEW INT-0, EIB-0, EIB-1, sim 4).**

- Decision: R130 and R131A stay 100 ohm; the BOM, the netlist and the copper do not change. The `gen/netlist.py`
  comment records that the H.24(d) reason "conductor 7 has no GND neighbour" is void under D-66.
- Reason: D-66 puts CE_DRV_J (pad 5) and ILIM_REL_A (pad 7) next to GND pads on the CR grid. A single bridge on CR 5-9
  or 7-3 pulls the CR rail to 1.97-2.36 V (`sim/permit/RESULTS.md` section 5.8). A value inside the H.24(d) window
  (3.16-10.5 kOhm) restores the rail (at least 3.03 V at 4.99 kOhm in a scratch re-run of the sim 4 decks). It does
  not stop a 3V3-CE_DRV_J bridge from forcing /CE LOW with P5 LOW. It makes the STAT-CE_DRV_J wire short, the CR 7-4
  bridge and the EIB 7-10 bridge undefined at the LVC inputs, and it slows the edges to 166 ns/V at 60.7 pF. No E96
  value passes every case.
- Mitigation: the staged T-A-06 metering of design r9-26 (bare-board references and a post-wire table), or a grid
  reorder (a copper change on both boards). Both are operator questions; sim 4 names CR 5-9, 7-3, 1-5, 1-3 and EIB
  1-5, 2-5, 2-10, 2-3, and the decision study adds CR/EIB 5-7 in qualification and EIB 7-10 in an FC window.
  (**Superseded 2026-11-16, design r9-26:** "a post-solder isolation check of every orthogonal J101 and J201 pad pair,
  or a grid reorder (a copper change on both boards)".)
- Open: the sim 4 bridge list misses the qualification state and the pairs CR 7-4, 3-2, 8-10, 2-4, 4-10 and EIB 7-10,
  1-4, 4-8, 4-2, 8-3. The design-document B.3 claim of at most 10 ns/V at every LVC input does not hold for the
  existing 4.99 kOhm R131B and R132 paths; TODO(verify: SN74LVC3G06 / SN74LVC1G06 recommended operating conditions,
  delta-t/delta-v).
- **Addendum 2026-11-16 (W5 grid deep-dive with independent checks; ruled the same day, see the ruling bullet after
  this addendum).** When the addendum was written, section 11 item 31 and design J.2 item 76 stayed open.
  (**Superseded 2026-11-16, D-80 ruling:** "not ruled" in this heading, and "Section 11 item 31 and design J.2 item 76
  stay open.") The findings below are information for that ruling; the T-A-06 procedure text does not change.
  - Pad form: the J101 and J201 pads are plated through-holes (D-66 footprint), 1.0 mm drill and 1.8 mm pad on every
    copper layer, pad 1 square, mask open on both sides. The 0.74 mm orthogonal gap (1.42-1.79 mm diagonal) lies
    between the pad rings on both outer layers. A bridge or a stray strand can therefore form on the insertion side
    and on the side where solder wicks through.
  - Worst pair: CE_DRV_J to ILIM_REL_A (CR 5-7, EIB 5-7) during qualification. /CE is LOW in 6 of 8 corners while the
    release is HIGH, so EN_CHG = 0 is the only remaining barrier.
  - 3V3 to CE_DRV_J (CR 1-5, EIB 1-5, EIB 2-5) forces /CE LOW. The comparator-driven ILIM hold (Q201/Q203) and
    EN_CHG = 0 remain. No pair damages a part: the worst driver current is 18.7 mA against the 50 mA absolute maximum.
  - Copper near the grids that no earlier entry records: the CR /GND pour is 0.127 mm from every J101 signal pad (1,
    2, 4, 5, 7, 8, 10) on F.Cu and B.Cu; REVIEW EIL-0 asked for the CR check, and D-70 widened the clearance on the
    EIB only. The EIB nCE_DRV B.Cu track runs between the J201 pads, 0.245-0.29 mm from pads 1, 2, 3, 4, 9 and 10
    (pad 10 nearest); GND_J onto it forces /CE LOW. A tented EIB /AGND via at (16.11, 34.16) is 0.286 mm from J201
    pad 7 (ILIM_REL_A). The CR /J3V3_2 F.Cu track is 0.174 mm from J101 pads 4 and 10. A tented CR /GND via at
    (36.605, 51.025) is 0.308 mm from J101 pad 1. All of this copper is under solder mask, so a bridge needs a mask
    breach.
  - Reorder: a search of all 362 880 orders finds none that makes every orthogonal pair benign. The 96 best orders
    keep 4-6 rail-sag pairs and put GND next to CE_DRV_J or ILIM_REL_A. A reorder leaves the masked-copper paths and
    the diagonals in place, and the post-solder test is still necessary.
  - Meter readings: a correct T-A-06 reading on the 3V3, GND and 100 ohm driver pairs can be a few hundred ohms in one
    meter polarity, because the path contains one junction. A hard bridge still reads near 0 ohm.
  - Detection at first power: T-C-13 detects the 3V3-CE_DRV_J class. R108 holds CHG_ARM LOW, so the bridge draws
    9.8-12.3 mA against at most 1.82 mA expected. A 3V3-GND bridge draws about 18-21 mA, at the 20 mA limit.
  - Candidate mitigations, none taken: (A+) extra power-off readings (CR 2-10, 4-9 and 10-9; EIB E5 nCE_DRV to J201
    pads 1, 2, 3, 4, 9 and 10; J201 pad 7 to AGND; the unsafe diagonals); pre-tin each wire end and trim it flush;
    one T-C-01 truth-table pass with W5 fitted, read on the EIB side too (U201/U202 inputs, E5, the Q201/Q202/Q203
    gates, STAT); a D-70-style 0.5 mm J101 pour clearance on the CR. That last option is a fill change and a CR
    re-export; the three J101 stitching vias then need a check for islands.
- **Ruling 2026-11-16 (operator, chat: "Keep copper, meter"; design r9-29).** Option (a) is adopted: the copper of
  both boards stays as packaged, and the staged T-A-06 metering of design r9-26 is the W5 single-bridge mitigation.
  The grid reorder is declined. Section 11 item 31 and design J.2 item 76 are closed.
  - Scope: the T-A-06 procedure text does not change. The candidate mitigations of the addendum (the A+ readings, the
    pre-tin and flush-trim rule, the T-C-01 pass with W5 fitted) are not part of the ruling. The CR J101 pour
    clearance is a fill change and a CR re-export, so the ruling declines it with the reorder.
  - Basis: no grid order makes every orthogonal pair benign, a reorder leaves the masked-copper paths and the
    diagonals in place, and the post-solder test is necessary under either option. Every bridge outcome is
    current-limited and damages no part.
  - Residual risk: a bridge or a strand that forms in service, after T-A-06, is not covered by a one-time test. A
    bridge to masked copper needs a mask breach first. T-C-13 detects the 3V3-CE_DRV_J class at first power. The 10 %
    band of the T-A-06 pass criteria stays TODO(calibrate: T-A-06 first build).
  - Reversal: a reorder is a copper change on both boards and a re-export of both fab packages. If the reorder is
    taken in a later re-spin, re-route /CHG_ARM out of the D-36 zone in the same edit (D-94).

**D-81. C106, C107 and C108 stay; C108 = 470 pF is an assembly option (2026-11-14, sim 4 T2 race, sim 3).**

- Decision: C106 = C107 = 470 pF (GRM1885C1H471JA01D) and C108 = 1.0 nF (GRM1885C1H102JA01D) stay (`gen/netlist.py`).
  C108 = 470 pF, the C106/C107 part, is an option at assembly; the opt-in file `bom_2026-11-14/digikey_optional.csv`
  carries it as an alternate line (D-83). The 4.7 nF and 10 nF lines there are bench parts only. (**Superseded
  2026-11-14, fix round 2026-11-15:** "`bom_2026-11-14/digikey_import.csv` carries it as an alternate line".)
- Hazard: a scratch re-run of the sim 4 decks shows that a T2 tap interruption of 10-30 us lifts ILIM_HIZ above VIH
  1.0 V while /CE is LOW. The peak is 1.26-1.48 V at 10 us and 1.63-1.77 V at 20 us, for up to 47.6 us. This occurs at
  every corner with typical 2 us comparator delays. It is larger than the permanent-open case of sim 4 Table 5.4 (1.39
  V, 28 us).
- Options rejected: C106 = C107 = 4.7 nF or 10 nF removes the brief-open pulses but uses up the H.13 allowance that
  T-B-06 (at most 150 us) must fit inside at 1.25 A and 1.80 A. C106 = C107 = 2.2 nF is worse than the present values
  at 20 us. C107 = 4.7 nF alone is held until a simulation rules out a false H1 trip on the H.6 fast VBUS rise.
- Option kept: C108 = 470 pF leaves the 10 us case unchanged (1.25-1.48 V), lowers the 20 us case to 0.51-1.05 V and
  is never worse than 1.0 nF, reconnects included. If it is fitted, design-document B.2 (tau about 44 us), the shared
  C108/C129 BOM line and companion-document C308 change.
- Sim 3: the comparator results do not change the choice. The H1 fall worst case of 17.843 V against the VINDPM_STAGE1
  minimum 17.84 V is a DC result and needs its own ruling (`sim/comparators/RESULTS.md` section 6 item 3). The VR-4
  0.08 ratio is not needed for the TLV3012B (item 5).
- Open: a T-D-04 bench step that applies T2 interruptions of 5, 10, 20 and 30 us (design T-D-04, r9-26);
  TODO(verify: SLUSDV2C ILIM_HIZ deglitch and restart time). (**Superseded 2026-11-15, D-91:** "a formal sim 4
  re-run with T2 interruptions of 2-40 us for every option (TODO(verify: sim/permit re-run)); a T-D-04 bench step
  that applies a 10-20 us T2 interruption"; the re-run is sim 4 section 5.6a.)
- **Amended 2026-11-15 (D-91; `sim/permit/RESULTS.md` section 5.6a, Tables 5.4a-5.4d):** the formal re-run replaces
  the scratch figures of the Hazard bullet. As built, interruptions of 5-30 us are hazardous, worst 1.810 V and
  50.7 us above VIH 1.0 V at 20 us (scratch: 10-30 us, up to 47.6 us). C108 = 470 pF narrows the band to 5-20 us
  (1.545 V, 27.9 us). It is worse than as built in 49 of 576 matched decks, by at most 5.0 mV and 0.34 us, so the
  "never worse" statement of the Option kept bullet holds only within those bounds. C107 = 4.7 nF alone trips H1
  falsely on a VBUS rise of about 2.9 V or more at 12 V/ms from 0 V or 13.0 V. C106 = C107 = 4.7 nF or 10 nF move the
  hazard to interruptions of 30 us or 50 us and longer, with a full release at 2.25 V for up to 0.48 ms or 1.23 ms,
  and add 197-269 us or 340-598 us of H1 inhibit latency. The decision of this entry does not change; the option
  choice is design J.2 item 77 (section 11 item 37).

**D-82. Netlist fields synchronized with the ordered parts (2026-11-14, REVIEW PWR-5, LOG-5, EIB-3, EIL-5, BOM-11).**

- Decision: `bom_2026-11-13/cr_bom.csv` and `eib_bom.csv` are the order set (the operator uploaded that list twice;
  `bom_2026-11-13/README.md` section 4.2). `gen/netlist.py` now carries their values, MPNs and manufacturers. The pin
  maps and footprints do not change. Table 2 of `update_2026-11-14/notes_phaseB_bom.md` lists every field.
- Main changes: C101 C0603C223K5RACTU; C102a CL31B105KCHSFNE; C102b "4.7uF 100V X7R" CNC6P1X7R2A475K250AE; C103
  CL21B105KBFNNNF; the CR and EIB 100 nF parts "100nF 100V X7R" GRM188R72A104KA35D; C125 "10uF 16V X7R"
  CL21B106KOQNNNE; D103 "Schottky 100V 2A SMA" STPS2H100A; D104-D106 BAV199-7-F; D107 SMAJ33A; R102 ERA-6AEB8453V;
  R109 ERA-6AEB4873V; R110 and R112 ERA-3AEB5622V; R115 RT0603BRD07104KL; U118 SN74LVC2G08IDCTRQ1; U202
  SN74LVC1G06DCKT; Q201 and Q202 "2N7002BK" 2N7002BK,215. U102, U103, U119, U120 (and DNP U203, U204) carry the note
  "B suffix required, no non-B substitute" (SBOS300C 9.4.4; `sim/comparators/RESULTS.md` section 5.6).
- Method: `gen/sch.py`, ERC and the netlist export regenerated both schematics and netlists (ERC 0 errors and 0
  warnings). Net membership is identical before and after (76 CR nets and 34 EIB nets with members; scratch
  `netcmp.py`). `gen/sync_fields.py` (now with `wx.DisableAsserts()`, and clearing fields that the netlist no longer
  carries) wrote 54 CR and 17 EIB fields. A line diff shows only Value, MPN, Manufacturer and Note property lines.
- Result: DRC parity items before the sync, CR 13 and EIB 7, all value mismatches; after it 0 / 0 / 0 on both boards.
  The constraint report is unchanged. Table D-53b gives the new netlist identity.
- Regeneration: run `gen/sch.py`, ERC, the netlist export and `gen/sync_fields.py <board>.kicad_pcb <board>.net` for
  each board after any `gen/netlist.py` change (section 2).
- Open: TODO(verify: Nexperia 2N7002BK datasheet) Vgs(th) maximum; TODO(verify: Panasonic ERA-3A datasheet) the
  resistance range for R103 (64.9 kOhm). The board footprints of U102, U103, U119, U120 and D103 have no Note field, so their notes
  appear in the schematic, the netlist and the fab BOM only.
- Note fields (fix round 2026-11-15, check1 issue 7): the board Note fields are not authoritative. `gen/netlist.py`,
  the schematic and the netlist carry the Note text; `gen/sync_fields.py` updates only the fields that a footprint
  already has, and the DRC parity check does not compare Note. The CR footprints D103, U102, U103, U119, U120 and
  J101 and the EIB footprint J201 have no Note field on the board. Value, MPN, Manufacturer and DNP agree on all 78
  CR and 46 EIB references (check1 section (b)).

**D-83. BOM set regenerated as `bom_2026-11-14/` (2026-11-14, REVIEW BOM-0 to BOM-10, DOC-9).**

- Decision: `gen/bom_split.py bom_2026-11-14` writes `cr_bom.csv`, `eib_bom.csv`, `system_bom.csv`,
  `digikey_import.csv`, `digikey_optional.csv`, `mouser_import.csv` and `digikey_skipped.csv`;
  `bom_2026-11-14/README.md` is written by hand.
  `bom_2026-11-13/` stays unchanged as the record.
- Generator changes: the MPN check accepts a netlist MPN equal to its `SUBST` target; each stencil row names its own
  board, upload path and pitch, and the EIB stencil row states that the 14 DNP footprints have no aperture (BOM-1,
  BOM-2); a `VMAX` table writes the rated voltage of the substitutes (BOM-3); `clean_notes()` removes stale
  boilerplate (BOM-4); the PLT1M-C row counts ties (BOM-6); the U118, Q201/Q202 and TLV3012B notes are corrected
  (BOM-8, BOM-9).
- Order effect: the 62 main Digi-Key lines equal the 62 lines of `bom_2026-11-13/digikey_import.csv` in quantity, part
  number, MPN and Customer Reference. Four labelled lines are in the opt-in file `digikey_optional.csv`: the D103
  alternate (D-79), the C108 470 pF option (D-81) and the 4.7 nF and 10 nF bench parts (D-81). (**Superseded
  2026-11-14, fix round 2026-11-15:** "Four labelled lines follow them". An opt-out line can reach the order
  unnoticed, and the ALT C108 line has the part number 490-1443-1-ND of the C106/C107 main line, so a list upload
  can merge the two lines into one line of quantity 20.) `bom_2026-11-14/README.md` section 4.1 instructs a fresh
  Digi-Key list from `bom_2026-11-14/digikey_import.csv` (BOM-0); the uploaded 2026-11-13b list still holds the three
  pre-D-67 resistors and the 2147561101 cable.
- Packages: the stencil and PCB rows name `fab/cr_2026-11-14/` and `fab/eib_2026-11-14/`, written on 2026-11-15 by
  `gen/export.sh` (**Superseded 2026-11-14, packages exported:** "which `gen/export.sh` writes next"). The PCB rows
  state the copper state of each package and no longer carry "TODO(verify: package exported)". The README section 7 of that folder lists the superseded statements of `bom_2026-11-13/README.md` and
  `bom_2026-11-13/PREORDER_REVIEW.md` (BOM-5, DOC-9).
- Evidence: `update_2026-11-14/notes_phaseB_bom.md`; `bom_2026-11-14/README.md` sections 2 to 4.

**D-84. EIB REGN track longer than the A.9 limit: deviation accepted (2026-11-14, REVIEW EIL-4).**

- Finding: A.9 (design document, REGN parts row) asks for REGN traces of at most 10 mm. Along the /REGN track graph,
  R252.2 is 13.55 mm from C205.1, and the net carries 19.19 mm of track in all. The other distances from C205.1 are
  R276.2 2.61 mm, R271.2 2.81 mm, Q203.2 5.59 mm and R254.2 5.70 mm (REVIEW EIL-4 and its verifier note).
- Decision: the deviation is accepted, and the copper does not change. The node is static: REGN feeds only the R252
  47.0 kOhm pull-up to the Q201 gate and the other gate pull-ups, behind the R276/C205 low-pass. No dynamic current
  flows on the long branch.
- Open: `gen/check_constraints.py` has no REGN-length row; adding one is optional. Design revision r9-26 added the deviation note to the
  A.9 REGN row (REVIEW R2-DOC-9) (**superseded 2026-11-15:** "The design-document A.9 row needs the deviation note
  (design-document change, outside this log).").

**D-85. CR input-pair labels (2026-11-15, phase C, REVIEW R2-INT-0).**

- Finding: the W1 reference stood under the W2 (/GND) pad, 0.10 mm from it and 3.30 mm (centre to centre) from W1,
  so the 20 AWG input pair could be swapped. A swap wires U101 VCHGOUT to EVM J1 pin 1 (PGND), which is the T-C-04
  hard short at the first power-up: OUT -3.76 to -7.83 V for 2.93-11.16 us (`sim/hardshort/RESULTS.md` section 6).
- Decision: `gen/cr_silk_fix_r4.py` adds "VIN1" level with W1 on its +x side (W1 goes to EVM J1 pin 2, VIN1), moves
  the W1 reference beside W1 (32.35, 39.95), and adds "GND" under W2 (W2 goes to EVM J1 pin 1). "VIN1" names the EVM
  pin, so it cannot be read as /VCHGIN. The ink of "VIN1" lies 0.12 mm from the W1 pad and 1.93 mm from any other
  pad; "GND" lies 0.14 mm from W2 and 1.14 mm from any other pad. The texts follow the D-78 CR rules.
- Evidence: `update_2026-11-14/notes_phaseC_board.md` section 3.1 and Table 3.1; a render check; DRC 0 / 0 / 0.
- Regeneration: run `gen/cr_silk_fix_r4.py` after `gen/sync_fields.py` and before `gen/cr_silk_refs_report.py`
  (section 2). The script is idempotent. Copper and footprint positions are unchanged.
- Consequence: the W1/W2 meter identity check before soldering is in design PM4 (2b) and T-A-06 (r9-26).
- Reversal: remove the two texts and restore the W1 reference position from the pre-phase-C board, then export again.

**D-86. EIB E-pad identification (2026-11-15, phase C, REVIEW R2-INT-7, R2-EIL-0 to R2-EIL-2).**

- Decision: `gen/eib_silk_fix_r3.py` adds an F.Silkscreen number beside every E pad: E8, E3, 4, E2, E7, E1, E5 and E6
  ("E4" has no legal position). Each label lies nearer its own pad than any other pad by at least 0.15 mm, its ink
  centre lies nearer its own pad row than any other E row by at least 0.5 mm, and it keeps 3.6 mm from the H1 and H2
  centres. The full landing labels stay on B.Silkscreen. The E1 label reads "E1 JP12.1" (JP12 pin 1, the square REGN
  post). The E2, E7 and E1 labels take 0.6 mm characters, and the E8 and E2 labels move toward +x, so every bottom E
  label keeps 0.80 mm from the bottom references (was 0.41-0.53 mm). The E7 label still crosses the tented via at
  (7.05, 28.95); no via-clear position exists. `gen/eib_wire_labels.py` names the E1 landing "JP12.1".
- Evidence: `update_2026-11-14/notes_phaseC_board.md` sections 3.2 and 3.3; `eib/silk_refs.md` section 4 (hand-kept).
- Regeneration: run `gen/eib_silk_fix_r3.py` last in the EIB order (section 2); it anchors the bottom labels on a
  1 um grid and is idempotent. Copper and footprint positions are unchanged.
- Reversal: remove the eight top texts and restore the bottom E labels from the pre-phase-C board, then export again.

**D-87. Check and record corrections (2026-11-15, phase C, REVIEW R2-CRL-2 to R2-CRL-6, R2-EIL-3, R2-EIL-5).**

- `cr/drc.rpt` (2026-11-15T05:29:19) and `eib/drc.rpt` (2026-11-15T05:36:57) are refreshed from the final boards: 0
  violations, 0 unconnected pads and 0 footprint errors with schematic parity (R2-CRL-5, R2-EIL-5).
- `gen/check_constraints.py`: the EIB A.9 outline row measures Edge.Cuts, 24.000 x 38.000 mm against 24.0 x 38.0 mm,
  and passes (R2-EIL-3; the former "deviation D-25" row). A new CR row reports the D-36 metric on all layers: /CHG_ARM
  has 5.25 mm of F.Cu track in the 2.0 mm zone, 0.224 mm from R114 pad 2 (/N_UVP); /SCL and /SDA have only their
  D-35-exempt J1.7/J1.8 pads in the zone; no logic via lies in it (R2-CRL-3). The row reports and never fails; the
  /CHG_ARM exemption is design J.2 item 83 (section 11 item 41), because a re-route is a copper change.
  **Amended 2026-11-16 (D-94):** the operator declined the re-route; D-94 is the exemption that applies to the
  /CHG_ARM figures of this row, and the row itself does not change.
- `gen/cr_geometry.py`: the D-39 frame row is labelled as a constant of the generator (result info), not as the board
  outline, which is the D-62 row (R2-CRL-6).
- `gen/fab_readme.py`: the CR design-value row states that the power and GND pours fill at the 0.127 mm rule minimum
  (measured /GND to /VCHG, /VCHGIN and /VCHGOUT 0.1271 mm; /VCHGIN to /VCHGOUT 0.150 mm), although the F.Cu zones
  declare 0.2 mm; no track is 0.127 mm (R2-CRL-2). The board was not refilled.
- The A.8 D103 loop budget of 2 nH is estimated, not extracted: board copper about 0.7-0.8 nH (strip over L2,
  h = 0.1999 mm), package inductance TODO(verify: STPS2H100A / MBRA2H100T3G). The sim 1 nominal L_d of 3 nH covers
  the estimate (R2-CRL-4; `update_2026-11-14/notes_phaseC_board.md` section 4.5).
- Counts: CR 107 pass, 1 pass with listed exceptions, 3 exemption, 18 information, 0 FAIL (was 108, 1, 3, 16, 0); EIB
  6 pass and 2 information (was 5 pass, 1 deviation, 2 information).
- Reversal: restore the three scripts from the pre-phase-C state and run them again; no board changes.

**D-88. Netlist Note fields (2026-11-15, phase C, REVIEW R2-BOM-1, R2-BOM-2, R2-INT-4, R2-INT-5, R2-CRT-0, R2-LOG-1).**

- Decision: `gen/netlist.py` changes two Note fields and three comments; no pin, net, value or MPN changes. The J1 Note
  names the mating SSQ-110-01-G-S and SSQ-112-01-G-S; the J102 Note says that the mate is built from workshop stock,
  with TODO(verify: workshop wire, T-A-05) for the gauge against the R170/R171 joints. The comments cite TCKE1401NM DS
  Rev. 3.0 section 7.10 (p.9) for the IMON capacitor statement, with TODO(verify: Toshiba IMON capacitive load through
  series R) (C129 unchanged), and TI SCES487I Figure 4-1 / Table 4-1 for the U107 pinout.
- `gen/sync_fields.py` has a new `--add-missing` option, which adds a missing MPN, Manufacturer or Note field as a
  hidden F.Fab field, and it saves only on a change. It wrote 8 CR fields (J1 and J102 Notes updated; Notes added on
  U102, U103, U119, U120, D103 and J101) and 1 EIB field (J201 Note).
- `cr/cr.kicad_sch`, `cr/cr.net` and `cr/erc.rpt` are regenerated (ERC 0 / 0). The EIB schematic and both symbol
  libraries regenerate identically; `eib/eib.net` and `eib/erc.rpt` differed only in their date line and were
  restored. Net membership is identical (CR 78 parts and 77 nets, EIB 46 parts and 35 nets).
- Identity: the date-stripped `cr/cr.net` sha256 is `37ef45c1f4e43f35a7f57e51ff9c4c20eede1fd6acf164b62c121e09eed94e36`
  (full file `148f1952ee89dab5ede5555a94941b4e401a97560cfb6c0bb77f40cbaa0d8d00`, exported 2026-11-15T03:46:24-0800);
  `gen/netlist.py` sha256 `2efe2225ae1197367d18012ef159488c5305fd8b470180407aca55ac5c7c1c08`, `gen/sch.py` unchanged
  (`6827b590...`). The EIB identity of Table D-53b is unchanged. This supersedes the "After D-82" column of Table
  D-53b as the current identity.
- Evidence: `update_2026-11-14/notes_phaseC_bom.md`. Board diff: Note property blocks only; segment, via, zone, pad
  and graphic counts unchanged.
- Reversal: restore `gen/netlist.py` and `gen/sync_fields.py` from the pre-phase-C state, regenerate the schematic and
  netlist, run `gen/sync_fields.py`, and delete the seven added Note fields on the boards.

**D-89. BOM set regenerated in place with opt-in SPARE lines (2026-11-15, phase C, REVIEW R2-BOM-0 to R2-BOM-6,
R2-CRT-1, R2-DOC-11).**

- Decision: `gen/bom_split.py bom_2026-11-14` rewrites the CSVs of `bom_2026-11-14/`. The generator gains note
  rewrites (C101, D103, D104-D106, J102, R131B/R132, U107), the EIB stencil history, a word-boundary description cut
  (`desc120()`), five SPARE lines and a printed optional-file total. `bom_2026-11-14/README.md` is edited by hand.
- Order effect: the 62 main Digi-Key lines are unchanged (61 MPNs, about USD 91.49); `system_bom.csv`,
  `mouser_import.csv` and `digikey_skipped.csv` are byte-identical to the previous run. The opt-in file
  `digikey_optional.csv` holds nine lines, about USD 25.80: the four alternate and bench lines of D-83 (about USD
  4.74) and five SPARE lines (USD 21.07): TLV3012BIDBVR x 2, GMC21X5R106K50NT x 5, TSW-112-07-L-S x 1 (a second
  matched J1 set), SSQ-110-01-G-S x 1 and SSQ-112-01-G-S x 1. A SPARE line never enters `digikey_import.csv`.
- Conflict recorded (R2-CRT-1): design section E reads "2 (+2)" and "5 (+3)" for the 10 uF parts, while the main line
  orders exactly 7. Either the operator adds the GMC21X5R106K50NT SPARE line, or section E changes to "2" and "5"
  (section 11 item 44).
- Evidence: `update_2026-11-14/notes_phaseC_bom.md`; `bom_2026-11-14/README.md` section 5.4. Line counts with header:
  cr_bom 47, eib_bom 14, system_bom 27, digikey_import 63, digikey_optional 10, mouser 5, skipped 36.
- Reversal: remove the SPARE entries from the `ALTERNATES` table of `gen/bom_split.py` and run it again.

**D-90. Packages written again in place; older packages are not edited (2026-11-15, phase C, REVIEW R2-DOC-7,
R2-CRT-3).**

- Decision: `bash gen/export.sh cr 2026-11-14` and `bash gen/export.sh eib 2026-11-14` wrote both packages again
  after D-85, D-86 and D-88, and `gen/fab_readme.py` wrote both READMEs against `fab/cr_2026-11-13f` and
  `fab/eib_2026-11-13c`. ERC 0 and DRC 0 / 0 / 0 on both boards; NPTH check CR 6 holes and EIB 2 holes pass.
- Difference from the first 2026-11-14 export: on the CR only `cr-F_Silkscreen.gto` and `docs/cr.net` (the D-88 Note
  fields); on the EIB only the two silkscreen Gerbers. Drill, copper, mask, paste, position and BOM files are
  identical. The CR F.Paste equals `fab/cr_2026-11-13f` (D-69 windows); the EIB F.Paste has 62 flashes (D-71). Every
  file that differs from 13f / 13c has a recorded reason in the package README.
- `gen/fab_readme.py` changes: the CR quantity note cites design section E (6, r9-25) in place of "the E BOM asks for
  5"; the EIB size row reads 24.0 x 38.0 mm (A.9 since r9-25); the PCBWay and JLCPCB rows point to
  `assembly/<board>-bom.csv`, because KiKit wrote no `bom.csv`; the silkscreen reasons name D-85 and D-86. Each old
  text is quoted as superseded in the generated README.
- Older packages: `fab/cr_2026-11-13f/`, `fab/eib_2026-11-13c/` and every earlier package are superseded and must not
  be uploaded. They are not edited: a dated package is a record. `README.md` sections 9.3, 9.4 and 12 name the
  current and the superseded packages instead of a banner (REVIEW R2-DOC-7).
- Record (REVIEW R2-CRT-3): phase B had added superseded banners to `fab/eib_2026-11-11/README.md` and
  `bom_2026-11-11/README.md`. The orchestrator reverted both banners in phase C, because older packages and BOM
  folders are not edited; `git diff` shows no change to either file. The banners on `DESIGN_STATE_2026-11-12.md` and
  `MORNING_REVIEW_2026-11-13.md` stay, because those files are state records with a declared successor, not packages.
- Reversal: run `gen/export.sh` and `gen/fab_readme.py` again from the pre-phase-C boards and generator.

**D-91. Simulation re-runs that change recorded numbers (2026-11-15, phase C, REVIEW R2-SIM-0 to R2-SIM-9,
R2-LOG-0, R2-PWR-0).**

- Sim 2 (`sim/chopper/RESULTS.md` section 5.8, Tables 5.5-5.8; `sim/chopper/run_r2.py`): the sim 5 corner model (both
  pin leaks at +-320 nA, 0.1 % resistors) gives the fitted divider OVP rising 21.588-25.019 V and falling
  19.899-22.927 V; 21.588 V replaces "21.90 V with pin leakage". Lever (a) is R102 845 kOhm, R103 68.1 kOhm and R104
  47.5 kOhm (0.1 %, E96 and E192): OVP rising 23.256-26.863 V (23.818-26.300 V without leakage, 24.935 V typical),
  OVP falling 21.439-24.614 V, UVLO rising 9.092-10.571 V; every healthy first trip lies at the charger-plus-chopper
  capacity, 1.4-1.6 A. The maximum lies 0.66 V above the BQ25798 VBUS_OVP maximum 26.2 V (SLUSDV2C section 6.5,
  p.9); the V_OVPR spread 1.298/1.18 = 1.100 makes the conflict structural. A 0.5x string (432 kOhm, 33.2 kOhm,
  24.6 kOhm) gives 23.163-26.180 V, TODO(recalc: sim 5 part b). The 21.35-23.10 V band is the chopper conduction
  onset, not a V-MOT ceiling. The U101 body diode, added in 1304 runs, changes no trip, cut or latch count. Amends
  D-67 (bands) and feeds section 11 item 35.
- Sim 1 revision 3 (`sim/hardshort/RESULTS.md` sections 5.6 and 5.7, Tables 7a and 7b; `run.py --tft-check`): over
  tFASTTRIP 3-8 us (TCKE1401NM Table 10.3, 4 us typical and 8 us maximum at R101 8.45 kOhm), the fast-trip-short OUT
  minimum is +0.72 to +1.39 V at 2 ohm and +0.25 to +0.53 V at 1.5 ohm (old 6 us basis: +0.82 to +1.23 V and +0.30 to
  +0.45 V); the hard-short headline is unchanged. After the fast trip the part regulates at I_LIM 1.97-2.77 A for up
  to 190 ms: 23.8-65.4 W and up to 12.4 J per event (TODO(verify: Toshiba) for the dwell after an SCP or UVLO trip).
  Amends the D-79 substitute-short figures and feeds section 11 item 42.
- Sim 4 (`sim/permit/RESULTS.md` section 5.6a, Tables 5.4a-5.4d; `t2brief.py`, `t2brief_check.py`): the formal T2
  interruption re-run (4116 decks) gives the as-built hazard band 5-30 us, worst 1.810 V and 50.7 us above 1.0 V,
  and the option table of design J.2 item 77. The H1 inhibit latency is 27.0-34.3 us (fixed delays) for 470 pF,
  197-269 us for 4.7 nF and 340-598 us for 10 nF; the "134/232 us" estimate is superseded. The as-built H.13 budget at
  1.80 A is 158.7 us with fixed delays and 139.1 us under the overdrive model, below the T-B-06 150 us (TODO(verify:
  SBOS300C tPD at about 0.5 mV/us); recorded only). Run order: `run.py`, then `t2brief.py`, then `t2brief_check.py`,
  because `run.py` deletes all outputs at its start. Amends D-81.
- Sim 3 (`sim/comparators/`): `run_log.txt` is now the console of the final run; the earlier console is kept as
  `run_log_pre_dedup_2026-11-15.txt`. No number changes (R2-SIM-8).
- Sim 5: the maximum OVP-start interval is 4.021 s ("4.02 s" in design H.21 and H.23(q); R2-SIM-5). The design
  document F.5 T10 proof (b) decay to 8.0 V is 0.083-4.39 s on the sim 5 basis (design r9-26, doc_fw appendix A).
- Evidence: `update_2026-11-14/notes_phaseC_sim_chopper.md`, `notes_phaseC_sim_permit.md`, `notes_phaseC_sim_misc.md`;
  each RESULTS.md keeps the old text in superseded form, and the old CSVs keep their timestamps.
- Reversal: none needed for a simulation record; a later re-run supersedes these figures in the same form.

**D-92. README figures regenerated (2026-11-15, phase C, REVIEW R2-DOC-6).**

- Decision: `gen/readme_figures.py` now draws U101 as "TCKE1401NM + D103", W5 as nine wires on 3 x 3 pads with two GND
  wires, the J-TAP lead as a Micro-Fit mate from workshop stock, and R131B and R132 at 4.99 kOhm (`gen/netlist.py`
  lines 243-244; `cr/cr.net`). The script was run with the miniforge Python, and its text-overlap check reports 0
  problems on both figures. `figures/fig2_1_block_diagram.{png,svg}` and `figures/fig5_1_permit_gate.{png,svg}` are
  regenerated; the fig5_1 note cites SCES487I Table 4-1.
- Reversal: restore the five strings and run the script again.

**D-93. U101 OVP dropout on hard brakes accepted; divider unchanged (2026-11-15, operator ruling, design J.2 item 74).**

- Decision: the charger dropout that an early U101 OVP trip causes on a hard brake is accepted. R102 845 kOhm, R103
  64.9 kOhm and R104 51.1 kOhm stay (OVP rising 21.588-25.019 V at the sim 5 leakage corners). R101 stays 8.45 kOhm;
  the 7.87 kOhm T-B-23 retune of design J.2 item 74 is not taken. The VESC regen limit is unchanged, and
  `bom_2026-11-14/mouser_import.csv` is unchanged. Lever (a) (R103 68.1 kOhm, R104 47.5 kOhm) is not taken.
- Basis:
  - The OVP rising low edge spreads 1.6 V from the 23.188 V typical. The U101 V_OVPR tolerance (1.18-1.298 V,
    TCKE1401NM Table 10.1) gives 0.997 V of it, the 0.1 % resistors 0.042 V, and the +-320 nA worst-case pin leakage
    0.561 V. A low-threshold U101 trips at 22.15-22.19 V without any leakage, so a buffered divider would not remove the
    risk.
  - Sim 6 (`sim/regen_nocut/RESULTS.md`): the 8 measured hard brakes (12 A from 3.00 m/s or below) deliver 10.9-19.0 W
    peak and 2.0-5.5 J to V-MOT. With the nominal 21.739 W charger they do not trip at any drivetrain efficiency up to
    1.0. At the lo 18.8 W corner the excess is 0.42 mJ against the 18.09 mJ that lifts a 0.4 mF V-MOT to the 21.588 V
    OVP minimum, at the assumed gear efficiency 0.9 (a trip at 1.0; TODO(verify) gear efficiency).
  - An early trip with a converting charger needs a low-threshold U101 and the H-hi chopper corner (or H-typ with
    leakage), together with a brake that exceeds the charger capacity long enough: a 12 A brake from 3.11 m/s (lo) or
    3.49 m/s (nominal), or a 25 A State-98 'T' brake from 2.51-2.70 m/s. The RegenTest_decel_sweep cycle brakes from
    3.50 m/s. In the 100 kHz degraded mode of design FR-41 item 2 at 0.4 mF the 3.00 m/s brakes keep 0.96-0.99 V of
    margin, or 0.22-0.24 V if the staged phase lasts 2.0 ms. The VESC regen limit of 1.5 A blocks the hi charger corner.
  - With a VESC cut at 23.4-25.2 V the consequence is the lost harvest of that brake (at most its 2.0-5.5 J at V-MOT,
    9.2 J from 3.5 m/s) and a 0.5 s loss of regen braking per cut (sim 2 assumption). Sim 2 section 5.4 gives
    millisecond R-G / Z-SNT pulse overstress for cuts at 25.2-30 V.
- Residual risk:
  - Without a VESC cut, V-MOT settles at 28.7-31.6 V for 18.9-23 W on H-hi with sustained overstress of R-G, Z-SNT,
    R-SHUNT and the BSP170P; 35 V and the D-BC-RG OVP latch follow only from about 30 W (sim 2 Part D). The VESC
    `l_max_vin` and fault-stop bench item (design J.2 item 74) therefore stays required before hard-regen tests.
  - A charger that does not convert (CV taper, EN_CHG 0, P5 LOW) trips U101 on ordinary brakes at any OVP corner; that
    mode does not depend on the divider (sim 2 Part D).
  - A brake current above 12 A lowers the start-speed thresholds; the 'T' ramp already allows 25 A.
- Open with it: design FR-50 (`OV_CHG` value, response and filter) and the FR-30 threshold stay for the firmware round
  (section 11 item 36).
- Reversal: order 0.1 % 68.1 kOhm and 47.5 kOhm for R103 and R104 (TODO(verify: distributor stock)), or the 0.5x string
  of design J.2 item 74; both are part changes only, with no copper change.

**D-94. /CHG_ARM keeps its route in the D-36 zone at R114 under a conditional exemption (2026-11-16, operator ruling,
design J.2 item 83).**

- Decision: the re-route of /CHG_ARM out of the D-36 zone is declined (operator ruling 2026-11-16, chat: "I accept
  declining"). D-94 is a D-36 exemption for /CHG_ARM at R114, under the conditions below. The copper does not change.
  The generated row of `cr/constraint_check.md` still reports 5.25 mm; D-94 is the exemption that applies to it.
- Geometry (re-measured on `cr/cr.kicad_pcb` and confirmed by an independent check, 2026-11-16):
  - 5.253 mm of /CHG_ARM F.Cu lies in the 2.0 mm zone, all in one segment (36.359, 54.135)-(36.359, 61.135) of
    0.1524 mm width, with no via in the zone.
  - The minimum gap to R114 pad 2 (/N_UVP, IN+ of the U103 UVB comparator) is 0.224 mm (0.2238 mm). Only 1.40 mm of
    the run faces that pad, so 5.25 mm is an upper bound of the parallel length.
  - In1.Cu and B.Cu GND cover 100 % of the in-zone run. The /GND F.Cu pour lies 0.127-0.128 mm from the track on
    the other side.
  - /CHG_ARM is not a static line. It switches at each charge-window boundary, on arm and on disarm.
- Basis:
  - The estimated coupling is 0.02-0.04 pF (2D model, about +-50 %). With C108 = 1.0 nF, the step on /N_UVP is about
    0.1 mV (0.07-0.13 mV); with the 470 pF option (D-81) it is 0.14-0.28 mV.
  - The node hysteresis is about 37 mV and the node margin about 0.24 V at VBUS 15.9 V. The disarm edge pushes the
    node toward the safe side.
  - A hard /CHG_ARM-to-/N_UVP short is a latent double fault. Alone, it is invisible at the nominal bus, because UVB
    is already HIGH. With a lost T2 tap during an armed window, it equals the "UVB stuck HIGH" fault that the design
    document analyses. VINDPM and the FR-08(d) H1 plausibility trip (at most 5 ms) bound that fault.
  - The literal D-36 test, "where no other route exists", is not met. A zone-free path exists, but only through the
    J101 wire-pad row and column gaps beside /J3V3_1, /CE_DRV_J, /GND, /ILIM_REL_A and /ILIM_REL_B, with 2 more vias.
    That path is unrouted and unchecked.
  - The exemption is therefore an operator ruling on comparative grounds. A short in the J101 grid would be a worse
    fault next to a hand-soldering step, and the re-route would reopen the verified CR package.
- Conditions:
  - On every assembled CR, a cold resistance check from J1.11 (/CHG_ARM) to R114 pad 2 (/N_UVP) is mandatory, on a
    low-voltage resistance range. The expected reading is roughly 100-150 kOhm: R108 47 kOhm in series with R115
    104 kOhm in parallel with the R114/R111/R112 path. TODO(verify: first assembled CR). A reading below about
    1 kOhm indicates a short.
  - T-C-01 is not a substitute for that check. Its rig drives H1 and UVB from supplies (forcing method TODO(design:
    T-C-01 rig)), so it can mask the short.
  - C108 stays fitted, either 1.0 nF or the 470 pF option (D-81).
  - After reflow, the flux around R114, C108 and D106 is cleaned, and R114 pad 2 is inspected under magnification.
  - If the CR copper is re-spun for any other reason, /CHG_ARM is routed out of the zone and the exemption is
    dropped.
- Residual risk:
  - A short that forms after the build check, for example from contamination in service, stays latent until a T2 tap
    is lost during an armed window. VINDPM and the FR-08(d) H1 plausibility trip then remain the only bounds.
  - The mask web between the R114 pad 2 opening and the track is about 0.17 mm, so a bridge needs a mask breach or a
    misregistration of that size. TODO(verify: OSH Park) the mask registration tolerance.
  - The cold-check figure assumes that the U105/U106 input protection does not conduct at the meter test voltage.
- Open with it: design J.2 item 82 (section 11 item 40) stays open. Design revision r9-28 corrected the "static arm
  line" wording in the A.8 Analog bullet and in J.2 item 83. `update_2026-11-14/notes_phaseC_board.md` still describes
  /CHG_ARM as a static arm line; this log does not edit it.
- Reversal: route /CHG_ARM out of the zone in a CR copper change, then refill, run DRC and the constraint check,
  export again and review the package again. If the D-80 grid reorder is taken, design the re-route in the same edit,
  because the only known zone-free path passes the J101 grid.

**D-95. EIB phase B reference rule set kept; CR W6 "GND" label accepted as placed (2026-11-16, operator rulings,
section 11 items 28 and 29).**

- Decision: the operator kept the phase B EIB reference rule set (operator ruling 2026-11-16, chat: "I accept keeping
  it the way it is") and accepted the W6 "GND" label as placed (chat: "Accept as-is"). 18 of the 26 fitted EIB
  references stay on the top side. Neither board is exported again.
- EIB reference findings:
  - R252 breaks no phase B rule at its phase A position. The search orders the parts by candidate count, so U202 (2
    candidates) is placed before R252 (118) and takes the space. The orphan rule then removes U202, and the search
    never offers the space again.
  - 19 fitted references on top are reachable: R252 at (11.32, 22.83) mm, 90 deg, with 0 phase B violations in a
    scratch run. This position is not taken. Take it only if the EIB is exported again for another reason; it also
    moves the bottom texts of R254 and R271.
  - The phase A board was never exported. `fab/eib_2026-11-13c/` and `snapshots/2026-11-14_pre_review/` hold the D-64
    placement (20 on top).
  - A re-run of the phase A rules on the current board gives 22 on top. However, 13 positions differ from the phase A
    board, and the U201/C202 ambiguity (D-78 defect D4) returns.
  - The R254 bottom text is 0.6 mm wide, not 0.8 mm.
  - The control for the eight bottom-referenced parts is the iBOM check during assembly, before the EIB goes onto
    its standoffs (D-78).
- W6 label findings:
  - The label is on the CR, not on the EIB. Several records list it beside the EIB item without naming the board.
  - The ink box is 0.0857 mm from the W6 pad 2 mask opening and 0.1365 mm from the copper.
  - The strokes lie over the drill of the tented /GND via at (25.392, 39.097) (`update_2026-11-14/notes_cr.md` line
    143).
  - The label already touches the W2 courtyard line: 0.0045 mm from the ink box to the circle centreline at x 25.800.
  - No vertical "GND" level with pad 2 meets both the 0.10 mm mask rule and the W2 courtyard rule: 1.040 mm is
    available and 1.050 mm is needed. The text is at the DRC minimum height and stroke, so it cannot shrink.
  - The D-78 CR text rules formally cover only texts moved or added in phase B; the W6 label is a D-73 text.
  - Consequence of the gap: at worst a thinned edge of one letter, which is cosmetic. W6 is fitted only with a pack
    NTC, and its square pad 1 carries "TS".
- Scope: both items are silkscreen only and have no copper option. `MORNING_REVIEW_2026-11-14.md` section 3.4 lists
  them under "Layout items with a copper option"; its 2026-11-16 entry records that both are silkscreen only and have
  no copper option.
- Open: TODO(verify: OSH Park, at submission) whether OSH Park clips silkscreen at mask openings. TODO(verify:
  assembled board) whether the J1 post hides the W3 reference (about 0.2 mm overlap of the J1 courtyard ring); this
  is an inspection step on the assembled CR, not a Gerber decision (section 11 item 29).
- Reversal: for the EIB, restore the phase A rules through `MASK_GAP`, `DRILL_HARD` and the `orphan_check()` call of
  `gen/eib_silk_refs_r2.py` (D-78), or place R252 at the 19-on-top position, then export again. For the W6 label, move
  it in `gen/cr_lead_labels.py` and export the CR again. A re-run of that script deletes the W2 "GND" text, and
  `gen/cr_silk_fix_r4.py` places it again (section 2); a +0.02 mm nudge meets the mask rule but overlaps the W2
  courtyard by 0.0155 mm.

**D-96. Charger I2C at 100 kHz on the fitted 10 kOhm MB pull-ups (PM9 withdrawn), FR-07 budget 3.5 ms, FC-window
thresholds 0.40 / 0.50 A; regen VINDPM 19.0 V retained (2026-11-16, operator rulings, design r9-30).**

- Decision (operator rulings 2026-11-16, chat):
  - I2C: "I would rather stick with 100kHz and the existing pullups rather than switching to 400kHz and have to do
    additional board rework in a difficult location", and later "I'm leaning towards keeping the 10k resistors and
    running at 100kHz". PM9 (MB RSDA/RSCL 10 kOhm -> 2.7 kOhm) is withdrawn. 100 kHz with 10 kOhm is the design
    case, no longer a fallback or a counted degraded mode. EM6 (EVM R39/R40 removed) stays, for its back-powering
    reason; the CR I2C pull-ups R145/R146 stay not fitted (no footprint since design r9-3).
  - FR-07: "Let's use 3.5ms as the edit-to-write-complete budget", that is pin-34 rising edge to REG03-05 write
    complete <= 3.5 ms (was 1.5 ms, which had no physical derivation).
  - FC window: "let's use G<400mA, hysteresis at G>500mA as the fuel cell charging window limits". A window closes at
    G < 0.40 A and is admitted at G >= 0.50 A (was close < 0.30 A, admit >= 0.30 A plus H_adm about 0.40 A). The
    window floor, and so the IINDPM at the H1 edge, becomes 0.40 A. The floor is a close threshold, not a clamp above G.
  - Criterion: "Replace with no overvoltage trip". The 20.5 V test acceptance is replaced by no U101 OVP trip at the
    s5-lo corner, 21.588 V.
  - C_VMOT: "Our previous data logs and measurements suggest 1.0mF on the motor node as a lower bound, likely
    higher." The design uses C_VMOT,min = 1.0 mF until T-E-04 measures it.
  - VINDPM: a regen-image VINDPM of 18.4 V (band 18.03-18.77 V) was evaluated and deferred by the operator: "Let's
    keep at 19V for now then, with a note to revisit later if necessary." The regen-image VINDPM (REG05) stays
    19.0 V (0xBE), band 18.62-19.38 V; design J.2 item 91 records the deferred option.
- Board consequence: no CR or EIB copper, netlist, Note field or package changes. The MB rework loses PM9. The MB
  RSDA/RSCL line (2.70 kOhm, CRCW06032K70FKEA) still stands in `bom_2026-11-14/system_bom.csv` and
  `bom_2026-11-14/digikey_import.csv`; TODO(update: bom_2026-11-14) remove it from the order. The frozen
  `bom_2026-11-11/` and `bom_2026-11-13/` sets are not edited.
- Basis (`sim/raise_latency/RESULTS.md` and `run.py`; IINDPM-first order; minimum over the measured brakes and four
  charger corners; C_VMOT 1.0 mF; IINDPM 0.40 A at the edge; threshold 21.588 V):
  - The largest latency with no s5-lo trip is 6.15 ms nominal (+2.65 ms over 3.5 ms) and 3.71 ms in the stacked
    worst case (efficiency 1.0, 1 ms charger lag, IINDPM accuracy 0.83 and resistor TCR, d310 corner), a margin of
    +0.21 ms. This is the worst latency-limited case; the same stack at the lo corner is capacity-limited. A 17.5 V
    VBUS (OV_BUS limit) at the edge gives 4.29 ms (+0.79 ms). Every case without the efficiency-1.0 stack leaves at
    least 0.28 ms (12 A from 3.5 m/s), and at least 0.79 ms without that brake.
  - Some cases are capacity-limited and trip at a latency of 0: a 12 A brake from 3.25 m/s or more at the lo corner,
    efficiency 1.0 at the lo corner, a 23 W constant-power brake at the lo, nominal and d310 corners, and a hard brake
    inside a CV-phase window. No latency budget covers them.
  - The firmware fits the budget at 100 kHz with 10 kOhm and the x1.133 clock-stretch factor: 1.505-2.539 ms for the
    pin-34 ISR architectures (a, a', b2) and the timer-polled c1; the `loop()`-driven ones (d, c2) do not fit. The predicted SCL/SDA rise time is 593-839 ns for Cb 70-99 pF against the 1000 ns
    standard-mode limit; the Cb ceiling is 118 pF. The FR-07 engine sets the LPI2C SETHOLD to at least 4.75 us,
    because the `Wire` default of 3.42 us is below the UM10204 tHD;STA of 4.0 us and tSU;STA of 4.7 us.
  - The evaluated VINDPM 18.4 V option moves none of the latency results (identical to 0.01 ms), because every
    crossing occurs above about 20 V, where the charger is at its current or power limit.
- Effect on earlier records: the D-93 basis cites "the 100 kHz degraded mode of design FR-41 item 2 at 0.4 mF". That
  mode is now the design case, and the design C_VMOT is 1.0 mF. The D-93 record is not changed; the U101 dropout
  ruling stands.
- Open with it (for the operator; not ruled here):
  - A hard brake inside a CV-phase window trips U101 at any latency, which conflicts with the no-trip criterion while
    "CV does not close a window" (design F.4, FR-39).
  - In-window brake speed and power: a 12 A brake from 3.25 m/s or more is capacity-limited at the lo corner, and no
    firmware limit exists. The T-B-12 23 W pass criterion fails at a latency of 0 at the lo, nominal and d310 corners.
  - T-D-12 (false restore; start 19.72 V, IINDPM 0.40 A, 1.0 mF, 21.588 V) trips 3.52 ms after the restore nominal
    and 2.59 ms stacked (IINDPM accuracy 0.83 and 1 ms lag); after the <= 1 ms detect tick the re-raise must land
    within 2.52 ms nominal and 1.59 ms stacked. T-D-12 needs its own re-raise deadline: <= 2.5 ms nominal, <= 1.5 ms
    if the stacked case must pass (architecture (a) 1.539 ms stretched has no margin there; a'' 0.973 ms fits).
  - The VESC cut level (`l_max_vin`) is still unknown. A cut near 21.35 V would bind before U101.
  - The 0.21 ms stacked margin must hold the BQ25798 register-to-loop dead time, which TI does not specify;
    TODO(verify: TI), measured by T-B-12 and T-B-24.
  - VINDPM 18.4 V is deferred (design J.2 item 91). If it is revisited, it lowers the V-MOT static maximum to
    19.10 V and relaxes T-D-12 to 3.53 / 2.57 ms re-raise; its open side effects are the H1 rise maximum 18.05 V
    above the 18.03 V VINDPM minimum, the bus-feed margin 1.12 -> 0.53 V, the T4(b) 18.2 V condition inside the
    band, and an H.7 capability of about 21.07 W.
- Reversal: restore PM9 (fit 2.7 kOhm at MB RSDA/RSCL) and the 400 kHz FR-07 caps; restore the 1.5 ms budget and the
  0.30 A thresholds in the design document.

## 9. Verification

### 9.1 ERC and DRC

Both schematics pass ERC with `--severity-all --exit-code-violations` (0 errors, 0 warnings). The EIB passes DRC
with `--severity-all --schematic-parity --exit-code-violations` against `fab_2layer_oshpark_pcbway.kicad_dru`
after `apply_board_setup.py` (0 violations, 0 unconnected items). No waiver is used. On the r7 outline (history), the CR at the
pour stage reports only the unrouted connections, 2 starved thermals (the L1 GND fill against two U101 thermal-via pads) and
2 silkscreen items.

**D-54 (2026-11-13):** the CR on the plug-on outline (variant B, pour stage) is checked against the OSH Park-only rule
file with `--severity-all --schematic-parity`: 131 violations (3 courtyard overlaps from fixed coordinates, 0
clearance, 4 starved thermals, 124 silkscreen items), 108 unconnected items and 0 parity issues (Table D-54a).

**D-55 (2026-11-13):** after the placement fix round, DRC with the same options reports 124 violations (75 silk over
copper and 49 silk overlap, all reference fields; no courtyard overlap, clearance or starved-thermal item), 109
unconnected items and 0 parity issues (`cr/drc_place.rpt`). The constraint check gives 88 pass, 0 FAIL, 3 listed
D-20 exemptions and 16 information rows (`cr/constraint_check.md`).

**D-56 (2026-11-13):** after the r9b fix round, DRC with the same options reports 124 violations (75 silk over copper
and 49 silk overlap, all reference fields), 107 unconnected items and 0 parity issues. The constraint check gives 97
pass, 0 FAIL, 3 listed D-20 exemptions (R102, R103, R129) and 16 information rows, with the nine new escape rows
passing.

**D-57 (2026-11-13):** after the C102c pre-via and the strap extension, DRC reports the same 124 silk violations, 107
unconnected items and 0 parity issues. The constraint check gives 97 pass and 0 FAIL; the C102c.2 escape row now
reaches the pad's own via. Build note: `gen/route.py` saves `cr/cr.kicad_pcb` from `cr_placed.kicad_pcb` and resets the
board minimums in `cr/cr.kicad_pro` (hole clearance 0.25 mm instead of 0.254 mm), so its zone fill leaves the J102
NPTH pegs 0.2505 mm from the GND pours (six DRC items). Restore `cr/cr.kicad_pro` from git and refill the zones with
the board loaded as `cr/cr.kicad_pcb`; the six items then clear.

**D-58 / D-59 (2026-11-13):** on the routed board after the reference placement, DRC (`--severity-all
--schematic-parity`) reports 0 violations, 0 unconnected items and 0 parity issues. The constraint check gives 98 pass
rows and 0 FAIL. Before the reference placement, the routed board gave the 124 silkscreen items of D-57 and 0
unconnected items.

**D-60 (2026-11-13):** after the trim, the holes and the reference re-placement, DRC (`--severity-all
--schematic-parity`) reports 0 violations, 0 unconnected items and 0 parity issues. Before the reference re-placement,
the trimmed board gave 4 silkscreen items (2 silk to edge, 2 silk over a hole mask opening). The constraint check gives
108 pass rows and 0 FAIL, including the new D-60 outline, ear and hole rows and the D-41 key row on the trimmed outline.

**D-61 (2026-11-13):** on the trimmed, stitched and straightened board after the reference placement, DRC
(`--severity-all --schematic-parity`) reports 0 violations, 0 unconnected items and 0 parity issues. The constraint
check gave 108 pass rows and 1 FAIL, the new D-20 stitching row (4.08 mm against 3.54 mm). After the stitching gap
fill (three /GND vias), it gives 109 pass rows and 0 FAIL (D-20 row 3.47 mm); DRC is unchanged at 0 items.

**D-62 (2026-11-13):** on the board trimmed to the D-62 outline, after the re-run finish, the reference placement and
the field synchronization, ERC reports 0 items. DRC (`--severity-all --schematic-parity`) reports 0 violations,
0 unconnected items and 0 parity issues. The constraint check gives 109 pass rows and 0 FAIL. The two D-62 outline
rows compare the board Edge.Cuts (20 items, 10 of them arcs) with the filleted `FINAL_OUTLINE` (area difference
0.0103 mm²) and check the edge angles and the 2.0 mm minimum slanted edge. The D-20 stitching row reads 3.51 mm at
(43.0, 44.8) with 306 stitch points, against 3.54 mm.

**D-63 (2026-11-13):** on the straightened and stitched EIB with the top AGND pour, ERC reports 0 messages and DRC
(`--severity-all --schematic-parity`) reports 0 violations, 0 unconnected items and 0 parity issues. The EIB
constraint check is unchanged (`eib/constraint_check.md`). The three KiKit presets ran without messages.

**D-64 (2026-11-13):** after the EIB reference placement, DRC (`--severity-all --schematic-parity`) reports 0
violations, 0 unconnected items and 0 parity issues, and the EIB constraint check is unchanged.

**D-65 (2026-11-13):** after the via merges, DRC (`--severity-all --schematic-parity`) reports 0 violations, 0
unconnected items and 0 parity issues. The constraint check gives 108 pass rows and 0 FAIL (`cr/constraint_check.md`).
The KiKit OSH Park preset ran without messages; the JLCPCB and PCBWay presets fail on the assembly BOM as before.

**D-66 (2026-11-13):** after the wire-pad change, ERC reports 0 messages on both boards and DRC (`--severity-all --schematic-parity`) 0
violations, 0 unconnected items and 0 parity issues on both boards. The CR constraint check gives 108 pass rows and 0 FAIL;
the EIB constraint check is unchanged. The KiKit OSH Park preset ran without messages on both boards.

**D-67 (2026-11-13):** after the U101 change, CR ERC reports 0 messages and DRC (`--severity-all --schematic-parity`) 0 violations, 0 unconnected items and 0 parity issues. The CR constraint check gives 108 pass rows and 0 FAIL. The KiKit JLCPCB and PCBWay presets fail on the assembly BOM as before.

**D-68 (2026-11-13):** after the E-pad pour clearance change, EIB ERC reports 0 messages and DRC (`--severity-all --schematic-parity`) 0 violations, 0 unconnected items and 0 parity issues; the EIB constraint check gives 5 pass rows and 0 FAIL. The KiKit OSH Park preset ran without messages.

**D-69 (2026-11-13):** after the U101 paste-window change, CR DRC (`--severity-all --schematic-parity`) reports 0 violations, 0 unconnected items and 0 parity issues; the CR constraint check gives 108 pass rows and 0 FAIL, with the U101 aperture row at 54.6 % and 0.160 mm.

**D-70 to D-84 (2026-11-14):** on the final boards of the round, ERC reports 0 messages on both schematics, and DRC
(`--severity-all --schematic-parity`) reports 0 violations, 0 unconnected items and 0 parity issues on both boards
(re-run 2026-11-15 for this record). The CR constraint check has 108 pass rows, 1 pass row with listed exceptions, 3
exemption rows, 16 information rows and 0 FAIL; the EIB check has 5 pass rows, 1 deviation row and 2 information rows.
`gen/pcbdiff.py` against git HEAD `014c745` reports 0 added or removed segments and vias on both boards and zone
changes in fill only (CR VCHG_L1 and GND_L1_fill, D-75; EIB AGND_L1_pour and AGND_L2_pour_1, D-70).

**D-85 to D-92 (2026-11-15):** after the phase C silkscreen and field edits, ERC reports 0 messages on both
schematics, and DRC (`--severity-all --schematic-parity`) reports 0 violations, 0 unconnected items and 0 parity
issues on both boards (`cr/drc.rpt` 2026-11-15T05:29:19, `eib/drc.rpt` 2026-11-15T05:36:57). The CR constraint check
has 107 pass rows, 1 pass row with listed exceptions, 3 exemption rows, 18 information rows and 0 FAIL; the EIB check
has 6 pass rows and 2 information rows. `gen/pcbdiff.py` against `014c745` again reports 0 added or removed segments
and vias, and a pcbnew comparison finds footprint positions, pads, zone outlines and tracks identical to the
pre-phase-C boards.

### 9.2 Constraint measurements

`cr/constraint_check.md` and `eib/constraint_check.md` hold the measurements (A.2 pin identity, A.7 outline, A.8
pad positions, the eFuse distance rules, the 10 mm rim rule, the divider strip, the tab contents, R106s, the via
tenting and the U101 thermal vias; for the EIB, the E-pad order, pitch and holes).

The figures in the first paragraph of section 9.1 and in section 9.2 before D-52 are for the r7-outline CR; the
D-54 to D-59 paragraphs of section 9.1 are for the plug-on CR. On the new outline, `gen/check_constraints.py` needs
new rows (`outline_change_2026-11-12/retired.md` section 4): the TSW pads against the A.8 hole table, one SMT side,
chip size at least 0402 (0603 preferred) (r9-3 / D-44: no 0402 part remains; every chip passive is 0603 or larger), IC pitch at least 0.65 mm with the U101 exception, the D-37 via-in-pad
listing, the D-20 air gap and the D-46 J-TAP placement constraints. The rows for the r7 outline, the 10 mm rim rule,
the tab contents and the tab X R106s location retire. **D-52 (2026-11-12):** the rows are implemented in
`gen/check_constraints.py` and `gen/cr_geometry.py`; the D-20 air-gap row is not implemented, because D-51 closes the
height survey. `cr/geometry_check.md` holds the board-independent rows.

## 10. Proposed design changes

The capture does not edit the r8 document. These changes would align the document with the layout; each needs an
operator ruling unless marked as already ruled. The 2026-11-12 decisions (D-39 to D-50) are operator rulings, not
proposals; they enter the design document through the step (1) update of D-50.

| ID | Design row | Proposed change | Reason |
|---|---|---|---|
| P-01 | A.8 Copper, IN strip | Accept a parallel L1 + L3 VCHGIN path, or move R102 so that its N_UV pad does not face the pad-10 corridor | the L1 corridor is about 1.7 mm (D-21) |
| P-02 | A.8 OUT strip, Routing notes | Accept the L1 corridor under the D103 anode plus the L4 strap for the D103-W1 leg of VCHGOUT. **Withdrawn 2026-11-12:** L4 carries no strap; VCHGOUT is re-derived on L1 and, if needed, L3 (D-20, D-22) | D-22 |
| P-03 | A.8 footprint low-y band | Record U120/U121 at the MS4b-conditional band positions, and state where they go if MS4b fails. **Withdrawn 2026-11-12:** U121 is removed (D-47) and the r7 band retires with the outline; the comparators follow the D-11 window rule | the band holds five comparators at x <= 39.53 (D-11) |
| P-04 | A.8 footprint low-y band | Admit a BAV199 clamp in the band corner left of F08, and driven logic below the pin-1 post. **Withdrawn 2026-11-12:** F08 is removed (D-38) and the band corners are re-derived on the new outline (D-12) | D-12 |
| P-05 | A.9 Outline | 24.0 x 38.0 mm EIB | D-25 |
| P-06 | B.8 R106 row, E R107 row | Delete the DNP R106 footprint | the r8 F17 exposed-copper rule (D-06) |
| P-07 | A.8 per-region tables | State courtyards on the IPC least-density basis (0.10 mm) or enlarge the regions. **Withdrawn 2026-11-12:** the courtyard basis reverts to the IPC nominal 0.25 mm (D-03), and the per-region table is re-derived on the new outline | D-03 |
| P-08 | B.4 / B.8 U101 MODE, EN (TCKE1401NM; was SHDN) | Record that MODE open selects latch-off and that EN open is permitted (TCKE1401NM DS Rev. 3.0 Table 6.1, section 7.14) with a 0 V guaranteed margin (VENUP 2.0-4.6 V against VEN_ON 2.0 V minimum, Table 10.2, p.15), so pin 12 needs a clean open node (T-C-04 step (f)); a restart needs EN cycled, VSYS at 0 V or the UVLO pin below V_UVLOF (section 7.15, Table 7.3) (**Superseded 2026-11-14, D-67; marked 2026-11-15, REVIEW R2-PWR-1 and R2-DOC-3:** "SHDN open enables with 0.48 V margin; only UVLO or a power cycle resets a latch", the TPS26630 figures) | `lib_verification` section 2; design B.4 EN row |
| P-09 | B.8, B.5 (ruled 2026-11-11) | Delete the DNP tier 1, 2 and 3 footprints (D-31); B.8 loses U117, R160-R163, C127, C124 and the F23 `T19_FCI` net. **Extended 2026-11-12:** no part is re-admitted; B.5 is deleted; FR-14(e) is rewritten; the F22, F23 and F24 pads are removed (D-31) | CR routing capacity |
| P-10 | A.8 +x pocket row, U101 centre | U101 and the IN strip 0.40 mm toward -y; R103 in the pocket, R104 on the bottom within 5 mm of pin 7. **Withdrawn 2026-11-12:** R104 is a top part (D-32 retired), and the eFuse cluster is re-derived on the new outline (D-09) | U101 pin 13/14 escape and the bottom clearance rule (D-09, D-32) |
| P-11 | A.8 stack-up and Copper (ruled 2026-11-11) | CR at 5/5 mil with 1 oz outer copper; CHG pads 1.9 mm on the outer layers only. **Amended 2026-11-12:** OSH Park-only rule file, 6/6 mil net-class default and 5/5 mil at necks, 0.6 / 0.3 mm vias only, unused inner pads removed on every THT pad, L4 solid GND (D-20, D-29, D-30) | D-29, D-30 |

## 11. Open TODO(verify) items

Layout and fabrication:

1. TODO(verify: T-A-08 MS4b reading) for U120/U121 at x > 39.53 (D-11). **Retired 2026-11-12:** U121 is removed and
   the r7 band retires; the successor is TODO(measure: operator, MS4) for the heat sources under the new outline (D-11).
2. **Amended 2026-11-13** (operator ruling 2026-11-13 (Review 2/2: BAV199, strap, OSH Park (fab checks),
   local_6e36c3a4-f328-44cd-8c31-05ea2fa7bfa3, chat 2026-11-13); D-29, D-56, D-57): the VCHGIN half is closed.
   **Closed 2026-11-13** for the VCHGOUT half by acceptance (operator ruling 2026-11-13 (design session, chat
   2026-11-13): "Accept short necks"; see the end of this item). Both halves are closed. (**Superseded 2026-11-13:**
   "the VCHGIN half is closed and the VCHGOUT half stays open."; the design-session ruling closes the VCHGOUT half.)
   For the VCHGIN half, the operator accepted the IPC-2152
   reading for the In2.Cu VCHGIN strap ("Accept, use IPC-2152") and the 0.5 oz inner copper basis ("Yes"). At
   17.5 um the IPC-2152 baseline fit requires 87.4 mil2, that is a 3.221 mm section. The D-57 strap section of
   4.174 mm (113.2 mil2) gives 2.75 A at a 10 C rise, and the rise at 2.41 A is 7.4 C. The OSH Park 4-layer page
   (docs.oshpark.com/services/four-layer/, read 2026-11-13) gives the inner layers as "0.68 mil (0.0175mm) 0.5 oz
   copper clad". The inner copper is clad and not plated, so the finished thickness is 17.5 um; at 17.3 um the strap
   gives 2.73 A. The IPC-2221 internal formula gives 2.04 A, below the 2.41 A basis, and is superseded by IPC-2152
   (D-57). The TODO(verify: IPC-2152 Figure 5-1) of D-56 closes for the VCHGIN strap. The ruling covers the VCHGIN
   strap only. The In2.Cu VCHGOUT strap (`VCHGOUT_L3_strap`, `gen/route_cr.py`, D-22) is a parallel path to the 1 oz
   L1 VCHGOUT pour. **Amended 2026-11-13 (D-62; `round4/calc/r9_calc.py` R9.H26):** the copper sections of the VCHGOUT
   path from U101 OUT to W1 are measured on the D-62 board layout. The basis is 3.21 A at a 10 C rise, with the 1 oz
   outer copper counted as the 35 um clad only (the plating is not credited) and the inner copper at 17.5 um. The
   IPC-2152 baseline fit then requires 153.4 mil2, that is 2.828 mm on F.Cu alone. Each neck section is a vertical
   chord of the filled /VCHGOUT copper, with pads not counted. The In2.Cu `VCHGOUT_L3_strap` ends at x 36.90, so the
   two necks at the U101 end are F.Cu only. Table 11-2a gives the four necks.

   | Neck | x (mm) | F.Cu + In2.Cu width (mm) | Length (mm) | Section (mil2) | IPC-2152 at 10 C | Rise at 3.21 A | Result |
   |---|---|---|---|---|---|---|---|
   | U101 OUT pins to C103 | 39.25-41.00 | 1.469 + 0 | about 1.75 | 79.7 | 2.30 A | 21.9 C | FAIL (long-conductor basis) |
   | C103 ground pad and D-56 /GND via notch | 37.50-38.75 | 2.082 + 0 | about 1.25 | 112.9 | 2.75 A | 14.3 C | FAIL (long-conductor basis) |
   | D103 belt | 31.75-33.25 | 3.800 + 1.800 | about 1.50 | 255.0 | 4.16 A | 5.6 C | pass |
   | W1 approach | 31.50 | 2.249 + 2.450 | about 0.25 | 188.5 | 3.56 A | 7.9 C | pass |

   The IPC-2152 chart is a long-conductor basis. A neck of 1-2 mm spreads heat into the wide pour on both sides, so
   the chart is expected to be conservative for the two failing necks. However, no short-neck method is on record,
   so the size of that margin is not established. The operator was asked how to handle the two short VCHGOUT necks,
   with the options to accept them, to widen the /VCHGOUT copper or to measure the rise on the bench, and ruled
   "Accept short necks" (operator ruling 2026-11-13, design session, chat 2026-11-13). The VCHGOUT half closes by
   acceptance. The two F.Cu-only necks (x 39.25-41.00, 1.469 mm, rise 21.9 C at 3.21 A; x 37.50-38.75, 2.082 mm, rise
   14.3 C) stay as they are, and the board does not change. The acceptance rests on the ruling and not on a passed
   check, because no short-neck calculation is on record. The TODO(ruling: operator) and TODO(measure: operator)
   markers of this half close. (**Superseded 2026-11-13:** "The VCHGOUT half stays open and needs an operator ruling:
   accept the two short necks, widen the /VCHGOUT copper at the two necks (a routing change; the x 37.50-38.75 neck is
   bounded by the D-56 /GND via notch), or measure the temperature rise on the bench at 3.21 A (D-22, D-29).
   TODO(ruling: operator) accept the two F.Cu necks or widen them, or TODO(measure: operator) the rise at 3.21 A.";
   operator ruling 2026-11-13 (design session) accepts the two necks.)
   (**Superseded 2026-11-13:** "and no check of it is on record. The VCHGOUT half stays
   open: TODO(verify: IPC-2152) the In2.Cu VCHGOUT_L3_strap at 3.21 A, or a check that the 1 oz L1 VCHGOUT pour alone
   carries 3.21 A (D-22, D-29)."; R9.H26 measures the path.)
   (**Superseded:** "TODO(verify: IPC-2152 internal-layer chart) for the L3/L4 straps on 0.5 oz inner copper at
   2.41 A and 3.21 A (D-29). **Amended 2026-11-12:** open only if VCHGOUT or the VCHGIN strap uses L3; L4 carries no
   strap (D-20, D-22). **Amended 2026-11-13 (D-56):** the VCHGIN strap is checked in design-document row H.25 on a
   curve fit of the IPC-2152 baseline chart; the chart reading itself stays open.")
3. **Amended 2026-11-13** (operator ruling 2026-11-13 (Review 2/2: BAV199, strap, OSH Park (fab checks),
   local_6e36c3a4-f328-44cd-8c31-05ea2fa7bfa3, chat 2026-11-13); D-30): the item stays open as an assumption to verify
   at submission; it is not an order blocker. The operator ruled "Let's assume they will accept it. I will find out
   later when I submit the board if not." and, on the action if OSH Park does not accept it, "We will decide once that
   time comes". The OSH Park 4-layer page (read 2026-11-13) has no statement on non-functional pads. Its plated drill
   to internal copper rule of 10 mil (0.254 mm) is met: the inner pours keep 0.27 mm against the 0.254 mm rule, and
   DRC reports 0 items. All vias keep their inner pads; only J1 (22 pads), J102 (10 pads), W1-W4, W6 and W7 remove
   the unused inner pads. TODO(verify: OSH Park, at submission) the non-functional-pad policy on these holes.
   (**Superseded:** "TODO(verify) that A.8's 1.9 mm CHG pad rule targets the outer layers only, and the fabs' inner
   annular-ring rule for the removed inner pads (D-30). **Amended 2026-11-12:** the CHG pads become TSW pads (D-03);
   the open item is TODO(verify: OSH Park) the non-functional-pad policy on connector holes.")
4. TODO(verify: MS8) the minimum inside-corner radius at the three concave outline corners (A.7). **Retired 2026-11-12:** the new outline is a rectangle with no concave corner.
5. **Amended 2026-11-13** (operator ruling 2026-11-13 (Review 2/2: BAV199, strap, OSH Park (fab checks),
   local_6e36c3a4-f328-44cd-8c31-05ea2fa7bfa3, chat 2026-11-13); D-29): the stack-up and mask-expansion parts are
   closed and the drilled-versus-finished reading of the TSW holes stays open. The operator approved the stack-up ("Yes") and
   the solder-mask expansion ("Yes"). The OSH Park 4-layer page (docs.oshpark.com/services/four-layer/, read
   2026-11-13) gives 63 mil (1.6 mm) FR408-HR (190 Tg), 1 oz outer copper (clad and plated), 0.5 oz inner copper, ENIG
   finish, purple SMOBC on both sides, and via tenting "Yes (filled hole and flat surface not guaranteed)". The
   alternate-stack-up notices are commented out in the page source, so no alternate stack-up is active. The mask
   expansion is 0.0508 mm, from the OSH Park KiCad design-rules page ("Solder Mask Expansion should usually be set to
   2mil (0.0508mm)"). The 4-layer page gives a maximum mask alignment error of 3 mil (0.0762 mm) and a minimum mask
   web of 4 mil (0.1016 mm), which is the board setting. The smallest different-net via-to-mask gap on the CR is
   0.115 mm (about 0.094 mm with square pad corners), which is more than the 0.0762 mm alignment error. The 0.027 mm
   via-to-mask-opening gap of the constraint check (D-37 row) is between a pad and its own same-net escape via, so the
   0.115 mm different-net minimum is the figure that the alignment error is compared with
   (`MORNING_REVIEW_2026-11-13.md`, item 3). This closes
   the mask-expansion TODO(verify) of the OSH Park rule set; the code comment in
   `tools/pcb/fab_rules/apply_board_setup.py` still carries the marker. The ruling does not address the
   drilled-versus-finished reading that item 14 passed to this item, and that part stays open: TODO(verify: OSH Park)
   the drilled or finished reading for the 1.1 mm TSW holes (items 14, D-41). It does not block the order (section 1).
   (**Superseded:** "TODO(verify: OSH Park) whether the
   10 mil minimum drill is drilled or finished (the vias use 0.3 mm drill), and OSH Park's temporary alternate 4-layer
   stack-up (`tools/pcb/fab_rules`). **Amended 2026-11-12:** the drill question is moot for vias, because 0.3 mm
   clears both readings (D-29); the stack-up item stays.")
6. TODO(verify: PCBWay) the base-price track/space option, the hole-to-hole edge-to-edge reading and the preferred mask expansion (`tools/pcb/fab_rules`). **Retired 2026-11-12:** the CR rule file is OSH Park-only (D-29).
7. Closed 2026-11-13 as out of scope (operator ruling 2026-11-13 (Review 2/2: BAV199, strap, OSH Park (fab checks),
   local_6e36c3a4-f328-44cd-8c31-05ea2fa7bfa3, chat 2026-11-13)): the operator ruled "Quote is outside the scope of the
   project". (**Superseded:** "TODO(verify: fab quote) for the CR and the EIB.")
8. TODO(verify: KiCad 9 IPC API docs) whether push-and-shove routing can be driven by script. **Retired 2026-11-12:** the interactive finish retires (D-36, D-50).

Parts and land patterns (`lib_verification_2026-11-11.md`):

9. Closed 2026-11-13 (operator ruling 2026-11-13 (Review 2/2: BAV199, strap, OSH Park (fab checks),
   local_6e36c3a4-f328-44cd-8c31-05ea2fa7bfa3, chat 2026-11-13)): the operator approved the pinout ("Yes"). The
   source is the Nexperia BAV199 product data sheet v.4 (1 April 2023), which supersedes v.3 (20200901); its only
   change is "Product changed to non automotive" (Table 8). Section 5, Table 2 "Pinning information", gives pin 1 =
   A1 (anode of diode 1), pin 2 = K2 (cathode of diode 2) and pin 3 = K1, A2. The board matches: D104, D105 and D106
   have pad 1 on /GND, pad 2 on /3V3 and pad 3 on /N_H1P, /N_H1M and /N_UVP. (**Superseded:** "TODO(verify: Nexperia
   BAV199 datasheet rev. 01092020, Table "Pinning information", original PDF).")
10. Closed 2026-11-13 (operator ruling 2026-11-13 (Review 2/2: BAV199, strap, OSH Park (fab checks),
    local_6e36c3a4-f328-44cd-8c31-05ea2fa7bfa3, chat 2026-11-13)): the operator ruled "Close, no need to refine if
    the current footprint is verified compatible". The footprint `SOT-23_CrtYd0.25` has 1.475 x 0.6 mm pads at 1.9 mm
    pitch, with the pad rows 1.875 mm apart, so the pads span 0.20 to 1.675 mm from the centre line. Data sheet v.4
    Fig. 8 gives a lead width of 0.38 to 0.48 mm, which is less than the 0.6 mm pad, and the lead tips at 1.05 to
    1.25 mm from the centre line, which leaves a toe pad of at least 0.43 mm. Fig. 9 gives reflow lands of about
    0.6 x 0.7 mm with the rows about 2.0 mm apart. The KiCad pads are longer toward the body; this is a fillet
    difference and does not change the connectivity. The land-pattern refinement is dropped. (**Superseded:**
    "TODO(verify: Nexperia SOT23 reflow footprint).")
11. TODO(verify: Littelfuse SMAJ datasheet, polarity and pad layout).
12. Closed 2026-11-13 (operator ruling 2026-11-13 (Review 1/2: J102, J1-TSW, W6-W7 (connector and lead-pad
    geometry), local_923ffa1c-f985-43ad-8510-7faea2e5f5d7, chat 2026-11-13); D-41): the operator confirmed the D-41
    TSW to SSQ stack ("Confirm both"), with the CR underside 11.05 mm above the MB top. The heights were not checked
    against a Samtec print in the review session; the closure rests on the operator's confirmation.
    (**Superseded:** "TODO(verify: Samtec TSW-1XX-XX-XXX-S MKT print, pin size .025 SQ). **Amended 2026-11-12:** this
    becomes the TSW to SSQ mating check of D-41.")
13. Closed 2026-11-14 as moot (REVIEW DOC-6): D-66 retires the FTSH headers, the ribbon and the pin-6 key, so no J101
    order string remains. (**Superseded 2026-11-14:** "TODO(verify: Samtec FTSH MKT sheet 2, Fig. 2) the -K plan-view
    envelope, and the exact order string for J101 with position 6 removed.")

Ordering BOM (`bom_2026-11-11/README.md` section 7, items 1-22): every Digi-Key SKU, price, stock and MOQ is
unverified, because Digi-Key, Mouser and the other distributors served bot checks; the D103, D107, J101, J201 and W5
candidates need their T-A-05 datasheet checks; the W1/W2 wire stranding needs a ruling (Alpha 3053 is 10/30, the
r8 spec names 19/32 or 7/28). The 2026-11-12 decisions change the ordering BOM: the TSW rows move to -L plating and
the SSQ rows are added (D-41); the six 0603 parts and SN74LVC1G11DBVR replace their predecessors (D-44); the J-TAP
header and the Molex 2147561101 assembly are added, and the TSW-101 tap-pin row shrinks (D-46); the removed gate and
comparator parts leave the BOM (D-47). The BOM is updated from the regenerated netlist. (**Superseded 2026-11-13:**
"the Molex 2147581101 assembly"; 2147581101 is the male cable, and the operator selected the female 2147561101,
D-46.)

**Amended 2026-11-14 (D-82, D-83).** The ordering source is `bom_2026-11-14/` (`bom_2026-11-14/README.md`); the
`bom_2026-11-11/` paragraph above is history. The J101, J201 and W5 candidates are retired by D-66, and the J-TAP
cable comes from workshop stock (item 16). D103 is the ordered STPS2H100A with an alternate line (D-79), and D107 is
the ordered Littelfuse SMAJ33A (item 11 stays open for its datasheet check). The netlist carries the ordered parts
(D-82).

Layout and fabrication, added 2026-11-12:

14. Closed 2026-11-13 (operator ruling 2026-11-13 (Review 1/2: J102, J1-TSW, W6-W7 (connector and lead-pad
    geometry), local_923ffa1c-f985-43ad-8510-7faea2e5f5d7, chat 2026-11-13); D-41): the Samtec "Recommended P.C. Board
    Layout for (X)TSW Single, Double & Triple (Thru-Hole & Right Angle)", Rev A, gives a hole of .040 in [1.02 mm] DIA
    TYP at .100 in [2.54 mm], with no tolerance, no drilled or finished reading and no pad size. The operator ruled
    "Keep 1.1 mm" (0.08 mm over the drawing value, for plug-in alignment) and confirmed the 1.9 mm pad ("Confirm
    both"). The drilled-versus-finished reading stays with item 5. The footprint description text "pad/drill
    PLACEHOLDER TODO(verify: Samtec TSW drawing)" changes at the next footprint-library regeneration.
    (**Superseded:** "TODO(verify: Samtec TSW drawing) the CR pad and drill for TSW-110/112-07-L-S (D-03, D-41).")
15. TODO(verify: Samtec derating) the four-powered-pin case at CHG pins 14/15/18/19, 1.93 A each (D-41).
16. **Closed 2026-11-13** (operator ruling, chat: "I'll deal with the J-TAP cable with whatever materials I have in my workshop"): the J102 mate is built from workshop stock and the 2147561101 cable is off the BOM; the J102 header (43045-1012) stays. **Amended 2026-11-13** (operator ruling 2026-11-13 (Review 1/2: J102, J1-TSW, W6-W7 (connector and lead-pad
    geometry), local_923ffa1c-f985-43ad-8510-7faea2e5f5d7, chat 2026-11-13); D-46): the header half is closed. The
    header is 43045-1012 ("That was a typo, I meant 43045-1012"); the Molex 43045 PCB layout confirms the orientation,
    the pegs and the physical pin numbering of the cavity map. The cable P/N is amended to 2147561101 ("(A).
    2147561101 is the correct cable and is in stock at Digikey"); its circuits are confirmed as 10, dual row, 150 mm,
    female-to-pigtail. TODO(verify: Molex 2147561101) the wire gauge and insulation stay open as a parts check.
    (**Superseded:** "TODO(verify: Molex 43045 header and 43025 housing drawings) the J-TAP header P/N, orientation,
    pegs and the physical pin numbers of the cavity map; TODO(verify: Molex 2147581101) the cable circuits, wire gauge,
    length and housing (D-46).")
17. Closed 2026-11-12: the operator accepted the J-TAP T5 (A4) to T10 (B5) diagonal (D-46).
18. Closed 2026-11-13: TI SCES487I (rev. November 2024) Figure 4-1 ("DBV or DCK Package") and Table 4-1 give one
    pinout for both packages: A 1, GND 2, B 3, Y 4, VCC 5, C 6. The U107 copper matches it (pad 1 /QUAL, 2 /GND,
    3 /FCCN, 4 /QF, 5 /3V3, 6 /P5N). (**Superseded:** "TODO(verify: TI Pin Functions tables) the DBV pinout of
    SN74LVC1G11DBVR against the DCK pinout, pin by pin against B.8 (D-03, D-44).")
19. Closed 2026-11-14 as moot (D-82): C101 is the ordered KEMET C0603C223K5RACTU (`bom_2026-11-13/cr_bom.csv`, 22 nF
    0603), and `gen/netlist.py` carries it. (**Superseded 2026-11-14:** "TODO(verify: Murata) GRM188R71H223KA01D
    (22 nF 50 V X7R 0603) for C101 (D-44).")
20. TODO(verify: OSH Park) the silkscreen text minimums for the reference designators (D-12a). **Amended 2026-11-13
    (D-59):** `gen/silk_refs.py` places 60 of 78 references on F.Silkscreen at 1.0 mm (0.8 mm where 1.0 mm does not
    fit) with a 0.15 mm stroke, against rule `fab_silk_text` (0.8 / 0.15 mm); 18 references are on F.Fab only
    (`cr/silk_refs.md`). The OSH Park minimum itself stays open.
    **Amended 2026-11-14 (D-74, D-78):** 54 CR references are on F.Silkscreen, 7 on B.Silkscreen and 17 on F.Fab only;
    on the EIB, 18 of 26 fitted references are on the top side. The OSH Park text minimum and the silkscreen
    registration tolerance stay open (items 26 and 27).
21. Closed 2026-11-12 (D-51, operator ruling): the stack-up clears every MB component except the power terminals,
    and the -x terminal clearance holds (gap at least 2.200 mm). (**Superseded:** "TODO(measure: operator) the
    L-FC/L-BT height and the bodge part heights for the D-20 air gap, and the rest of the change-request section 6
    survey (D-39).")
22. **Closed 2026-11-13 by D-69 (operator rulings 2026-11-13, chat: "I would order from OSH Stencil" and "Yes, do both"):** 4 mil stainless stencil from OSH Stencils; the U101 exposed-pad apertures follow the via keep-outs at 54.6 % coverage, 0.160 mm from the drills. (**Superseded:**) TODO(verify: SLVSE94G section 11 layout example) the window-pane stencil apertures for the U101 exposed pad
    (D-40).
23. Closed 2026-11-12 (D-52): the 78 CR parts at the 0.25 mm basis book 917.0 of 4077.8 mm² (22.5 %) of the top
    inset, against the 75 % target (`cr/geometry_check.md`). (**Superseded:** "TODO(calc) the area booking with the
    reduced part list, the 0603 and DBV parts and the 0.25 mm courtyards (D-44).")
24. Closed 2026-11-12 (D-49 r9-12 bullet, D-53 ruling R2): R132 and R131B are 4.99 kOhm 1 % 0603, so a J101
    pin 9-10 or 8-9 short draws at most 0.687 mA and the CR rail stays at or above 3.024 V (design H.24(d)).
    (**Superseded:** "TODO(calc: B.6 9-10 short against the LVC IOL) for J101 pins 9 and 10 (D-49).")
25. Closed 2026-11-13 (operator ruling 2026-11-13 (Review 1/2: J102, J1-TSW, W6-W7 (connector and lead-pad
    geometry), local_923ffa1c-f985-43ad-8510-7faea2e5f5d7, chat 2026-11-13); D-46): the latch is on the last-circuit
    (peg) edge and faces +x. The latch nub is at about MB x 53.5-54.9, y 25.3-26.7; the trimmed edge is about 3.6 mm
    beyond it, R175 about 3 mm toward -y and MH3 about 14 mm toward -y. The operator ruled "That is enough room".
    (**Superseded:** "TODO(verify: Molex 43045 header drawing) the J-TAP latch side and the finger-access keep-out
    (D-46, D-52).")

Added 2026-11-14 (D-70 to D-84):

26. TODO(verify: OSH Park) the silkscreen text minimum (carried from item 20).
27. TODO(verify: OSH Park silkscreen registration tolerance) for the stroke-to-drill gaps of 0.003-0.054 mm on the EIB
    (R258, R253, C204, U202 bottom, the board marking; D-78).
28. Closed 2026-11-16 (D-95): the operator kept the phase B rules ("I accept keeping it the way it is"); 18 of 26
    fitted references stay on top, and the EIB is not exported again. (**Superseded 2026-11-16, D-95:**
    "TODO(ruling: operator) the EIB reference rule set: the stricter phase B rules (18 of 26 fitted references on top)
    or the phase A rules (22 of 26) (D-78).")
29. The W6 half is closed 2026-11-16 (D-95): the operator accepted the CR W6 "GND" label as placed ("Accept as-is").
    TODO(verify: assembled board) whether the J1 post hides the W3 reference, which overlaps its courtyard ring by
    about 0.2 mm (D-73); this half stays open as an inspection step on the assembled CR. (**Superseded 2026-11-16,
    D-95:** "TODO(ruling: operator) the W6 "GND" label at 0.086 mm from a mask opening against the 0.10 mm phase B
    rule; and".)
30. TODO(ruling: operator) D103: keep the STPS2H100A or fit the MBRA2H100T3G alternate; TODO(verify: onsemi / ST pulse
    rating) for criterion (4); the T-A-05 "VF at 3 A <= 0.5 V" limit needs a restatement (D-79).
31. Closed 2026-11-16 (D-80 ruling): the operator kept the copper and adopted the staged T-A-06 metering ("Keep
    copper, meter"); the grid reorder and the CR J101 pour clearance are declined. (**Superseded 2026-11-16, D-80
    ruling:** "TODO(ruling: operator)".) The W5 single-bridge mitigation: a post-solder isolation check of the
    orthogonal J101 and J201 pad pairs, or a grid reorder (a copper change) (D-80). **Amended 2026-11-15:** design T-A-06 now meters the
    grids in stages, against bare-board references and a post-wire table (r9-26, REVIEW R2-INT-1); design J.2 item
    76. **Amended 2026-11-16 (D-80 addendum):** not ruled. The pads are plated through-holes with exposed rings on
    both outer layers; none of the 362 880 grid orders makes every orthogonal pair benign; the addendum lists unrecorded
    masked copper near both grids and the candidate mitigations, none taken.
32. TODO(ruling: operator) C108 = 470 pF at assembly (part of item 37); TODO(verify: SLUSDV2C ILIM_HIZ deglitch and
    restart time) (D-81). (**Superseded 2026-11-15, D-91:** "TODO(verify: sim/permit re-run) with T2 interruptions of
    2-40 us"; closed by sim 4 section 5.6a.)
33. TODO(verify: Nexperia 2N7002BK datasheet) the Vgs(th) maximum for Q201 and Q202; TODO(verify: Panasonic ERA-3A
    datasheet) the resistance range of R103 (D-82).
34. Closed 2026-11-15: the A.8 VCHG-IN length rule is exempted for the buried L3 strap (D-56 amendment), and the A.9
    REGN length deviation is accepted (D-84); design revision r9-26 added both notes (REVIEW R2-DOC-9, R2-CRL-1).
    (**Superseded 2026-11-15:** "both design-document rows need a note".)

Added 2026-11-15 (phase C, D-85 to D-92):

35. Closed 2026-11-15 (D-93): the operator accepted the charger dropout on hard brakes; R102, R103, R104 and R101 and
    `bom_2026-11-14/mouser_import.csv` are unchanged, and the basis is sim 6 (`sim/regen_nocut/RESULTS.md`).
    (**Superseded 2026-11-15:** "TODO(ruling: operator, before the Mouser order) design J.2 item 74, the U101 OVP band
    against the VESC regen limit: accept a charger dropout on hard brakes, set the VESC regen limit below the OVP rising
    minimum, or retune. As fitted,
    OVP rising is 21.588-25.019 V against the 21.35-23.10 V chopper conduction onset. Lever (a), R103 68.1 kOhm and
    R104 47.5 kOhm 0.1 % with R102 845 kOhm, gives 23.256-26.863 V rising and UVLO rising 9.092-10.571 V; its maximum
    lies 0.66 V above the 26.2 V VBUS_OVP maximum, and no divider avoids that (D-91). A retune changes R103, R104 and
    possibly R101 (7.87 kOhm) in `bom_2026-11-14/mouser_import.csv`. TODO(verify: distributor stock) for 0.1 % 68.1 kOhm
    and 47.5 kOhm; TODO(recalc: sim 5 part b) for a 0.5x string.")
36. TODO(ruling: operator, firmware round) design FR-50, the `OV_CHG` threshold, response and filter (with REGEN held
    HIGH, the single-sample 24.0 V latch trips State 99 mid-brake above V-MOT 24.15 V), on the as-fitted OVP bands of
    item 35 (**Superseded 2026-11-15, D-93:** "ruled with item 35"); and design
    FR-51, the recovery of a latched U101 in Run (option (A) wait for Idle, or (B) in-Run recovery with a retry cap).
37. TODO(ruling: operator) design J.2 item 77, the T2 interruption option (Table J.2-1; sim 4 Table 5.4d): accept the
    present design with or without C108 = 470 pF, or open a design change (T2 tap redundancy or retention). No option
    removes the hazard (D-81 amendment, D-91). TODO(verify: SBOS300C tPD at about 0.5 mV/us) for the as-built H.13
    budget at 1.80 A (139.1 us under the overdrive model against T-B-06 150 us).
38. TODO(ruling: operator) design J.2 item 78, the H1 fall worst case 17.843 V against the VINDPM_STAGE1 minimum
    17.84 V (Monte Carlo maximum 17.747 V): accept it statistically, or move the staged VINDPM raise one 100 mV code
    higher; T-C-02 at 0 C and 60 C measures the TCR term.
39. TODO(ruling: operator, firmware-round precondition) FW-0: `CLAUDE.md` sections 1-3 conflict with the r9 rules
    (section 2 requires REGEN_ENABLE LOW before FC_CHARGE_ENABLE, whereas FR-06 and FR-49 require the opposite;
    section 3 describes the Ag105); design D.5 items (7) and (8) list the lines. This log does not edit `CLAUDE.md`.
40. TODO(ruling: operator) design J.2 item 82: the VCHGIN strap and the J1.10 joint at the 2.77 A I_LIM maximum (D-57
    section 10.2 C, D-56 section 11.9 C against 10 C; J1.10 perimeter 3.456 mm against 4.234 mm). The over-basis
    current flows only in an I_LIM dwell of at most 190 ms. This reopens the closure of item 2 for the TCKE1401NM;
    the choice is transient-only acceptance or a strap change (copper).
41. Closed 2026-11-16 (D-94): the operator declined the re-route ("I accept declining"). /CHG_ARM keeps its route
    under a conditional D-36 exemption; the mandatory cold J1.11-to-R114 pad 2 resistance check carries TODO(verify:
    first assembled CR). (**Superseded 2026-11-16, D-94:** "TODO(ruling: operator) design J.2 item 83: a D-36
    exemption for /CHG_ARM at R114, or a re-route (copper) (D-87).")
42. TODO(ruling: operator) design J.2 item 84: the T-C-04 repetitions on the only U101 (5 of step (1), 5 of step (3),
    3 fast-trip shorts, at most 1 of step (2)), a spare U101 in the Mouser order, and whether step (2) runs.
    TODO(verify: Toshiba) safe operating area and repetitive current-limit or TSD rating; the dwell after an SCP or a
    UVLO trip; whether MODE open also latches an OVP event (sim 2 section 5.8.7).
43. TODO(ruling: operator) design J.2 item 85: C103 stays 1.0 uF or becomes a 4.7 uF 50 V 0805 part (MPN and DC-bias
    data TODO(verify); a sim 1 grid re-run before T-C-04).
44. TODO(ruling: operator) the five opt-in SPARE lines of `bom_2026-11-14/digikey_optional.csv` (D-89); without the
    GMC21X5R106K50NT line, design section E "2 (+2)" and "5 (+3)" changes to "2" and "5".
45. TODO(verify) items opened in phase C without an operator decision: STPS2H100A / MBRA2H100T3G package inductance
    for the A.8 2 nH budget (D-87); Toshiba IMON capacitive load through a series resistor (C129; D-88); the workshop
    wire gauge of the J-TAP mate against the R170/R171 joints (T-A-05; D-88).
46. TODO(ruling: operator) the open items of D-96 (design r9-30): CV-phase windows against the no-U101-trip
    criterion, the in-window brake speed and power limit, the T-B-12 23 W pass criterion, the T-D-12 re-raise
    deadline (<= 2.5 ms nominal, <= 1.5 ms if the stacked case must pass) and the VESC `l_max_vin` cut level.
    TODO(verify: TI) the BQ25798 register-to-loop dead time against the 0.21 ms stacked margin (T-B-12, T-B-24).
    TODO(update: bom_2026-11-14) remove the MB RSDA/RSCL 2.70 kOhm line.
