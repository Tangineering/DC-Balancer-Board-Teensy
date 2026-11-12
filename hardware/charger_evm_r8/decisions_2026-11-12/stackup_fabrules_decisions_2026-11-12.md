# CR stack-up and fab-rule decisions (operator, 2026-11-12)

Session: "CR decision: stack-up and fab rules". Scope: OUTLINE_CHANGE_REASSESSMENT_2026-11-12.md section 10
items 8 and 9, section 3.3, and ROUTABILITY_OPTIONS P1/P2 plus D-29. No repo file edited.

The operator answered by option buttons; the quoted option label is the operator's choice verbatim.

## 1. L4 facing the MB (item 8)

| Sub-item | Operator choice | Resulting rule |
|---|---|---|
| L4 extent | "Whole board (Recommended)" | L4 (B.Cu) solid GND over the whole CR outline; no signals and no power straps on L4; stitched to L2 at <= 5 mm pitch; keep L4 solder mask. Fallback (offered, not ruled): if a scripted run fails, L4 signals in the middle band only, never in a shadow zone - needs a new operator ruling. |
| D-22 VCHGOUT L4 strap | "Designer's call" | Design owner re-derives VCHGOUT routing. Constrained by the line above: no L4 strap, so L1 pour and/or L3. L1 (1 oz) avoids the open IPC-2152 0.5 oz inner check; an L3 parallel keeps that TODO open. |
| Air gap | "1.5 mm min (Recommended)" | >= 1.5 mm from the lowest CR feature (including THT tails) to the tallest MB part below it. Not binding at the 12.0 mm TSW-07 stack (7.0 mm over L-FC/L-BT). Independent-check caveat stands: basis counts CR bow only, not MB bow / standoff tolerance. |
| Sensitive-part window | "Preferred, not hard" | 0.1 % dividers, comparator inputs, references preferred in y 30.8-66.86 (MB frame) with the mbparts 2.3 keep-outs (10 mm REG-5V rim, 5 mm boosts, 2 mm SNS, 5 mm U101, divider pairs adjacent). Placement outside is allowed with a listed exemption. 1783.6 mm2 is an upper bound (U101 keep-out not subtracted). Upper edge 66.86, not 67 (L-FC silk 76.948). |

## 2. Insulating film over the untented MB vias (item 9)

Operator choice: "Retire entirely" (offered against "Retire; local tape only" (recommended) and "Keep a full film").
Result: no polyimide sheet and no local Kapton over the 368 untented MB vias. Knock-ons for the design owner:
- design doc r3-10, r5-10, r7-3, r7-12 (sheet as the via-ring cover), MB table line ~432, A.7 lines ~819/847/854/880/898-900,
  D.1 PM0/PM4 sheet steps, BOM line "Polyimide sheet": retire;
- the polyimide strip under the lead path (design doc ~618) also goes; tie-base bonding there re-derives with the new lead exits;
- r6-3 thermocouple "bonded under the polyimide sheet" (T-F-16) needs a new mounting;
- r7-12 coverage argument for exposed MB via rings now rests on spacing + masked L4 only;
- Kapton items unrelated to the sheet (T18 joint, rv7-7 E-pad joints, rv7-2 pin 7-10 tips) were not discussed - not retired by this ruling.

## 3. Fab rules (P1, P2, D-29)

| Sub-item | Operator choice | Resulting rule |
|---|---|---|
| Rule file | "OSH Park-only (Recommended)" | New OSH Park-only CR rule file: ring 0.1016 mm, via-diameter min 0.254 + 2 x 0.1016 = 0.4572 mm, hole min 0.254 mm, hole-to-hole 0.127 mm (OSH recommendation; no OSH minimum), edge 0.381 mm, plated hole to inner copper 0.254 mm, mask web 0.1016 mm. PCBWay minima drop out; a PCBWay order would need a re-check. Silk text: OSH Park states no height - keeping the 0.8 / 0.15 mm values as a house rule is the designer's call (not discussed). |
| Via sizes | "0.6/0.3 only" | Only 0.6/0.3 mm vias on the CR (default and sole size). 0.50/0.25 and 0.46/0.25 not allowed. The OSH Park drilled-vs-finished 10 mil question becomes moot for vias (0.3 mm clears both readings). |
| P2 inner pads | "Remove everywhere unused" | remove_unused_layers on all CR THT (receptacle, W-lead and tap connector pins, J1 per D-30): pad kept on any layer where it connects (incl. zone ties, e.g. GND to L2). TODO(verify: OSH Park) whether non-functional pads are required on 1.3-1.5 mm or connector holes for barrel anchoring under repeated mating. |
| Track/space | "6/6 default, 5/5 necks (Recommended)" | Rule-file minimum track/clearance 0.127 mm (OSH 4-layer limit); router net-class default 0.1524 / 0.1524 mm; 0.127 mm only at local necks (e.g. J1 / receptacle pin gaps, two lanes at 1.9 mm pads). D-29 amended accordingly; 1 oz outer / 0.5 oz inner unchanged. |

## 3a. Addendum: thermocouple removed (operator, same session)

Operator's words: "Also, let's remove the thermocouple. It was a good idea due to the thermal concerns but I think
it's an unnecessary complication for the amount of risk mitigation."

Rows that carry it: design doc r6-3 (line ~319), PM4 step 1b (~1444, ~2028), A.x line ~2112, the tools/hardware BOM
row "Thermocouple (r6)" (~2304, USD 15 allowance), T-F-16 (~3306; its method is the thermocouple), T-B-16 / finding
cr-and-mb-battery-path-copper-sized-below-ichg (~3866). Ordering BOM rows 97 (Omega 5TC-TT-K-36-36) and the
"thermocouple bond" use on row 96 (Kapton tape; the tape stays for the pin 7-10 tip patch). T-F-16 needs a new
pass criterion or retirement - design owner's call; not discussed with the operator.

## 4. Open TODOs carried forward
- IPC-2152 0.5 oz inner check only if VCHGOUT (or VCHGIN L3 strap) uses L3 (D-29 TODO).
- OSH Park non-functional-pad policy on large / connector holes (P2).
- MB survey items that feed the 1.5 mm gap: caliper L-FC/L-BT height (V3 5.0 vs 6.5 mm sibling), bodge part heights.
- Shadow-zone geometry is no longer a routing input (whole-board L4) but still feeds THT-tail placement (tails out of L-FC/L-BT/REG-5V shadows + 1 mm, mbparts 2.4).

## 5. Rows to change (design owner)
- LAYOUT_DECISIONS D-20 (L4 content, via tenting re-assessed), D-22 (re-derive, no L4 strap), D-29 (OSH-only file, 6/6 default), D-30 (extend to all THT per P2), D-37 (no change; 0.6/0.3 only means no small in-pad fallback via).
- cr/cr.kicad_dru and tools/pcb/fab_rules: new OSH Park-only file; route net class 0.1524.
- Design doc A.7 / A.8 stack-up L4, polyimide rows listed in section 2 above.
