# CR Outline and Assembly Change Request, 2026-11-12 (operator-approved, issued to the design owner)

## 1. Scope

This request changes three bases of the charger EVM r8 carrier (CR) design: the mounting concept, the outline and the
assembly method. It applies to `docs/charger_bq25798_wiring_design_2026-11-05.md` (r8) sections A.7 and A.8, and to the
CR capture under `hardware/charger_evm_r8/cr/` on branch `charger-evm-round4`. The EIB outline (24.0 x 38.0 mm, A.9,
D-25) does not change; section 5 applies the assembly rules to it.

All coordinates are in the motherboard (MB) frame of A.8: Eagle top view, origin at the MB origin, +x toward the Teensy,
+y toward L-FC.

## 2. Mounting concept

The operator changes the mounting concept as follows:

- The operator removes the Ag105 and fits raised male pin headers in the 22 CHG holes. The CR plugs onto these headers.
  The CR is therefore removable, and the A.7 header stack (Samtec TSW strips soldered through the CR and the MB, CR
  underside 2.665 mm above the MB top) is superseded.
- The operator fits four standoffs, shown at the four corners of the CHG footprint in the photo
  (`cr_outline_request_photo_2026-11-12.webp`, green marks). The standoffs carry the CR mass and the cable loads. The
  pins carry only the electrical connection.
- The two -x CHG corners (CHG silkscreen x 17.134) lie 1.45 mm outside the new -x edge (section 3.1.1), so the
  standoffs cannot sit at all four corners. The design owner is studying sites inside the old CHG footprint.
- The MB has no hole near the CHG footprint (its only plain holes are at (3.3, 3.3) and (3.3, 94.74)). The standoff
  attachment to the MB is an operator item (section 6, item 2).

## 3. Requested outline

### 3.1 Area

The acceptable area is the grey rectangle in the MB layout screenshot `cr_outline_request_mb_layout_2026-11-12.png`.
The photo `cr_outline_request_photo_2026-11-12.webp` shows the same area on the built board and the standoff positions.
Table 1 gives the requested outline.

Table 1. Requested CR outline (MB frame).

| Edge | Value | Basis |
|---|---|---|
| -x | **x = 18.584** (exact) | +x body face of J-BT, 17.584, plus a 1.000 mm clearance |
| +x | x = 67 | grey edge 67.41, rounded to 1 mm |
| -y | y = 7 | grey edge 6.56, rounded to 1 mm |
| +y | y = 94 | grey edge 94.02, rounded to 1 mm |

The outline is the rectangle x 18.584-67, y 7-94: 48.416 x 87 mm, 4212 mm² gross. This is 3.0 times the r7 outline
(1394.06 mm²). The r7 tab form is not required. Corner fillets are acceptable inside the rectangle.

#### 3.1.1 The -x edge

The -x edge follows the terminal-block body faces with a clearance. The CR spans y 7-94, so all four blocks lie beside
it. Table 2 gives the +x body face of each block from the MB layout (`references/Scale Car Board PCB 20260625.brd`,
tDocu layer 51, line centre). The script `mb_part_extents.py` in this folder computes these figures.

Table 2. Terminal-block +x body faces.

| Block | y span | +x body face | Face + 1.000 mm |
|---|---|---|---|
| J-BT | 8.128-23.368 | 17.584 | 18.584 |
| J-BL | 26.670-49.530 | 17.330 | 18.330 |
| J-NTC | 53.014-67.254 | 16.152 (silkscreen 16.252) | 17.252 |
| J-FC | 72.390-87.630 | 17.330 | 18.330 |

The operator set the 1.000 mm clearance on 2026-11-12. One straight edge at the
largest value (J-BT) is requested. A stepped edge would gain at most 1.33 mm along the J-NTC span and is not requested.
The block faces come from the footprint graphics, TODO(verify: CUI TB005-762 and Wurth 691411410002 drawings, or a
caliper reading on the board).

Note that the r7 outline started at x 17.70, which was 0.37 mm from the J-BL face. The new -x edge is 0.884 mm further
+x, so the design session must re-check every CR part and copper feature in the strip x 17.70-18.584. The CHG header
pads (1.650 mm square on the x 20.998 column) end at x 20.173 and are not affected.

#### 3.1.2 How the other edges were measured

The screenshot was measured by pixel count (`measure_outline_screenshot.py` in this folder). The MB outline lines
(Dimension layer, 131.064 x 98.044 mm) are at pixel columns 38 and 1225 and pixel rows 15 and 904. This gives
9.057 px/mm in x and 9.067 px/mm in y; the mounting hole at (3.3, 3.3) falls on its drawn circle as a check. The grey
edges lie between pixels, so each value in Table 1 is within +-0.11 mm before the rounding. Every rounded value lies
inside the grey edge, by 0.02 to 0.44 mm.

#### 3.1.3 Neighbours of the +x edge

The +x edge at x 67 touches two MB parts on the -y side: the C-DC3 body outline (x 66.954, overlap 0.046 mm) and the
C-D4 silkscreen (x 66.962, overlap 0.038 mm). On the +y side, D-FC-EN (silkscreen from x 67.082) lies 0.082 mm outside
the edge. C-D1, C-D2, C-DC1 and C-DC2 (x >= 67.416) stay uncovered. Coverage of C-DC3 is
acceptable under section 3.3, because the CR stands above it (section 3.4).

### 3.2 MB parts under the outline

The requested area covers both boost channels, the 5 V regulator and the cell balancer. Examples:

- the FC boost: L-FC, REG-FC, C1-FC to C6-FC, CC-FC, RC-FC, C4A-FC to C4C-FC, R1-FC and R2-FC;
- the FC droop network: OP-FC, MDAC-FC, ROP1-FC, ROP2-FC, RD1-FC, RD2-FC and RINJ-FC;
- SNS-FC and CSNS-FC;
- the BT boost and its droop network: L-BT, REG-BT, C1-BT, C2-BT, C3-BT, C5-BT, C6-BT, CC-BT, R1-BT, R2-BT, RC-BT,
  RD1-BT, RD2-BT, RINJ-BT, ROP1-BT, ROP2-BT, OP-BT and MDAC-BT;
- SNS-BT, CSNS-BT, D-BT-EN, D-BT-SQ, C-D3 and C-DC4;
- C-D11, C-D12, C-DC11 and C-DC12, which lie inside the old CHG footprint;
- REG-5V, CO-5V and CIN-5V;
- BAL, RB1A, RB1B, RB2, RB3, CBL1 to CBL3, CBLD and C4A-BT to C4C-BT.

The design session must list the full set from the `.brd`.

### 3.3 Coverage policy

The operator prefers MB parts to stay uncovered, but coverage is acceptable. Coverage is especially acceptable where
the measurement or rework at that part can be done with the CR unplugged. Because the CR is removable (section 2), this
applies to the FC droop block (the AD5443/OPA197 DMM measurement), the BAL rework points and the FC boost channel.

Note that the A.7 rejections of the -y zone, the wide +y zone and the zones over a boost switching node rested on access
to these parts. With a removable CR, these reasons apply only to work that must be done with the charger powered and the
CR fitted. The -x rejection (terminal-block wire entries, screws and the J-NTC push buttons) still applies.

### 3.4 Height

The CR underside must clear the tallest covered MB part plus the CR bottom-side parts plus a margin. The tallest covered
parts are L-FC and L-BT (5.0 mm each, TODO(verify: Eaton HCM1A1305V3 datasheet)) and REG-5V (4.83 mm). The terminal
blocks (13.9 to 21.7 mm) stay outside the outline. The MB also carries bodge wires and through-hole bodge resistors inside the requested
area; the caliper survey must record their heights. The design session selects the male header and the CR receptacle
from these figures. The 2026-11-10 operator statement (no maximum height for the MB and its PCBs) still applies.

## 4. Items the design session must re-assess

The following design items depend on the old mounting concept or the old outline:

1. **Mating connector.** Replace the soldered 22-pin TSW footprint with a receptacle footprint that mates with the MB
   raised headers. Keep the pin identity of A.2 and the pin-identity gate `calc/pin_identity_check.py`.
2. **Standoff holes.** Add four mounting holes at the standoff positions with their keep-outs. The positions cannot be
   the four CHG corners (section 2); propose sites inside the outline for operator approval.
3. **Removability of the leads.** The 20 taps (A.4) and the W leads (A.3) are soldered at their MB or EVM ends. A
   soldered lead prevents the CR from being unplugged. Terminate the taps and the W leads in connectors on the CR, or
   state which leads stay soldered and why.
4. **Retired low-mount rules.** Re-assess the bottom clearance rule (bottom parts <= 1.0 mm, 569.1 mm² bottom area), the
   polyimide sheet, the feet FT1 and FT2 and their fill hole, and the A.7 tab trims. Each rule existed because the CR
   underside was 2.665 mm above the MB copper.
5. **Switching nodes under the CR.** The CR now lies over VSW-FC (L-FC, REG-FC) and VSW-BT (L-BT, REG-BT). Specify the CR
   layer that faces the MB (for example a solid GND layer) and re-check the comparator analog nets against this
   coupling.
6. **Heat under the CR.** REG-5V and both boost converters and inductors dissipate under the CR. Re-assess the A.7 thermal band and the
   placement of temperature-sensitive parts (0.1 % dividers, references, comparator inputs) against the new heat
   sources.
7. **Routing capacity.** Re-run the routability study (`route-race`) on the new outline. The 2026-11-12 study ended with
   22 signal and 27 GND connections open on the r7 outline; the HANDOFF item 5 outline extension is now granted.
8. **Mating key.** A removable CR needs a physical key. Without one, a CR rotated by 180 degrees mates fully and swaps
   VIN+ and VBAT+.
9. **Constraint (c) and the D-xx decisions.** Re-check each `LAYOUT_DECISIONS.md` decision that names an r7 coordinate,
   a tab or a foot.

## 5. Assembly constraints

The operator assembles the CR (and the EIB) with a stencil, solder paste and a reflow oven. The design must meet the
following rules:

1. **Prefer one side.** Put every SMT part on one side if the new outline allows it. One side needs one reflow.
2. **Two-sided boards.** If both sides carry SMT parts, the side that is reflowed first (normally the bottom) is face
   down in the second reflow, and the board rests on those parts. For that side:
   - give every part a similar seated height, so that the board rests flat and no part shifts in the second reflow;
   - use only parts rated for at least two reflow cycles, TODO(verify: each datasheet, J-STD-020 rating);
   - use only small passives; put no IC, connector, inductor, diode or heavy part on it.
3. **Through-hole parts.** Hand-solder the receptacle, the lead pads and any other through-hole part after the last
   reflow, so that they do not prevent the board from resting flat.
4. **Passive size.** The minimum chip size is 0402. The preferred size is 0603. Use a larger size where the new area
   allows it.
5. **IC pitch.**
   - 0.5 mm is the hard minimum, and only with explicit operator approval for that part.
   - 0.65 mm is the preferred minimum.
   - 0.8 mm or more is best.
6. **Stencil.** Prefer coarse-pitch, leaded packages. Use the larger area to choose larger packages where an equivalent
   part exists.
7. **Via in pad (operator ruling 2026-11-12, after D-36).** Route the new outline first with no via on an SMD pad or in
   its mask opening. Plain unfilled vias in SMD pads (D-36) are a last resort only: use them only after a no-via-in-pad
   routing attempt on the new outline has failed, and list each such via for operator review. An unfilled via in a
   stencil-pasted pad can draw solder down the barrel and starve the joint. Filled and capped vias stay excluded
   (OSH Park does not offer them).

### 5.1 Current CR and EIB parts against section 5

Table 3 lists the parts of the current captures that conflict with section 5 (counts from `cr/cr.kicad_pcb` and
`eib/eib.kicad_pcb`).

Table 3. Current parts against the assembly constraints.

| Board | Parts | Package | Rule | Action |
|---|---|---|---|---|
| CR | U101 (TPS26630RGER) | VQFN-24, 0.5 mm, exposed pad | 5.5 | operator approval, or a coarser-pitch package of the same function, TODO(verify: tps2663.pdf package options) |
| CR | 5 resistors, 1 capacitor | 0402 | 5.4 | move to 0603 |
| CR | 8 x DCT SSOP-8, 3 x SC-70-6, 2 x SC-70-5 | 0.65 mm | 5.5 | allowed; move to SOT-23 or SOIC variants (0.95 / 1.27 mm) where they exist |
| CR | 78 bottom-side parts (74 x 0603, 2 x 0805, 2 x 0402) | mixed heights | 5.1, 5.2 | move to the top side if the area allows; otherwise check the height band |
| EIB | 1 x DCT SSOP-8, 1 x SC-70-5 | 0.65 mm | 5.5 | allowed; no change required |

The EIB is single-sided and uses 0603 passives, so it meets rules 5.1 to 5.4 as captured.

## 6. Operator items before the outline is frozen

1. A survey of the requested area on the built board: the bodge wires and bodge resistors inside the rectangle of
   Table 1 and their heights, the L-FC and L-BT body heights, and a caliper check of the J-BT and J-BL +x body faces
   against Table 2.
2. The standoff part and its attachment to the MB (adhesive base or a new hole), and the measured standoff positions.
3. The male header and receptacle selection, or a delegation of that selection to the design session with the height
   figures of section 3.4.