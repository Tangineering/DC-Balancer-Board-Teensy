## 1. Findings

1. **D-07 does not exist** in `LAYOUT_DECISIONS.md`. However, `gen/layout_cr.py:175-176` tags BAND_W/BAND_E "D-07", and the log calls these D-12 (`LAYOUT_DECISIONS.md:157`). Other tags in the same file are stale too: "D-05" at `layout_cr.py:57,60` should be D-11, and "D-06" at `:105` should be D-18. Fix the tags together with the rebuild.
2. **A single-sided CR is now likely feasible (ESTIMATE).** A.8 gives a single-sided demand of 101.8-109.9 % of the r7 usable top area of 1081.1 mmÂ² (design doc `:1375`, `:1389`), which is about 1100-1188 mmÂ². The new gross area is 4212 mmÂ² (CR request `:43`), so the demand is about 26-28 % of the gross area before the new exclusions: the receptacle, the standoff keep-outs and the lead connectors. If the CR is single-sided, every rule that exists only because of bottom parts retires, and L4 can become a solid GND layer that faces the MB (CR request item 4.5).
3. **U101 needs the 0.5 mm approval.** CR request Table 3 (`:172`) leaves "a coarser-pitch package of the same function" as TODO. A.8 already answers it: there is no leaded TPS26630, and the PWP parts (TPS26631/33/36/37) behave differently (design doc `:1453-1456`, SLVSE94G Â§4). Unless the operator approves 0.5 mm for U101, the B.4 eFuse must be re-derived.
4. **The VR-1 conflict matters at U101 first.** The U101 footprint puts 9 thermal vias inside the EP pad (D-03 table, `LAYOUT_DECISIONS.md:75`). Under a strict reading of CR request Â§5.6 (no via on an SMD pad) this is a violation. Under D-36 (`:326-328`) it is allowed. With a stencil and reflow, unfilled EP vias wick solder, TODO(verify: SLVSE94G Â§11 layout example, stencil aperture guidance). The second place it matters is GND stitching: MORNING_REVIEW `:95` reports 34 of 56 fill pieces with no via site under VR-1. The larger area reduces that pressure.
5. **The pin-11 chamfer at (17.70, 76.00) lies outside the new outline**, because x < 18.584. A removable CR also brings a new failure mode: it can be plugged one pitch off along y. A one-pitch shift still mates 11 of 12 and 9 of 10 pins. The soldered stack could not have this fault. The standoff holes can key the CR if they are asymmetric. This is an operator item.
6. **`mb_bottom_clearance()` is not bounded to r7 by its data.** `r7_calc.NONGND`/`PARTS` cover the whole MB (`r7_calc.py:579-586`). Only the `distance(P) < 1.5` filter (`layout_cr.py:141`) binds the result to the outline. On the new rectangle, the rule would forbid bottom parts over both boost channels (part boxes grown by 1.0 mm). It must be removed, not just re-run.

## 2. Classification: LAYOUT_DECISIONS.md

| Row | Class | Reason / new input needed |
|---|---|---|
| D-01 frame | KEEP | Mechanism unchanged. The text "KiCad Y 24.00-65.86" becomes 6.00-93.00. |
| D-02 pin identity | RE-DERIVE | The pad check and `pin_identity_check.py` stay. The chamfer mark retires (finding 5). Needs a new orientation mark and the keying ruling. |
| D-03 libraries/courtyards | RE-DERIVE | The CHG22 row becomes the receptacle footprint (item 4.1). The 0.10 mm courtyards were justified by "hand-assembledâ€¦ dense board"; the change to stencil reflow and the extra area reopen IPC nominal courtyards. U101 and 0402 against Â§5.4/Â§5.5. |
| D-04, D-05, D-06 | KEEP | Circuit and ERC only. |
| D-31 DNP tiers | KEEP | Operator ruling. The reason (routing capacity) is weaker now. Re-admitting the parts is an operator option. |
| D-08 fixed pads | RE-DERIVE | The CHG coordinates stay. The tab X grid, the low row, R175 and W1-W7 depend on the lead-termination decision (item 4.3). |
| D-09 eFuse cluster | RE-DERIVE | Cause 2, the +y edge 0.7 mm from pins 13/14 (`:123`), is gone. The A.8 targets are reachable again. |
| D-32 R104 bottom | RETIRE | Rested on the bottom clearance rule and the pocket bounded by the r6 +y edge. |
| D-10 J101 | KEEP | The region is bounded by internal regions, not by the outline. |
| D-11 comparators | RE-DERIVE | x <= 39.53 is the 10 mm rim rule to the MB 5V copper. REG-5V and both boosts are now under the CR. Needs the MS4 thermal map. |
| D-12 band corners | RE-DERIVE | A consequence of the D-11 crowding. |
| D-12a silkscreen | RE-DERIVE | The reason ("dense board") is gone. Reference designators help stencil and rework. Operator preference. |
| D-13 divider strip | RE-DERIVE | ">= 13 mm from the MB 5V rim" against the new heat sources (item 4.6). |
| D-14 interior | RE-DERIVE | FP_RECT is the inset r6 rectangle. B1R, B3/S3 and the bead spots belong to the tab Y trunk dressing. |
| D-15 packer | KEEP | Method only. GRID_BOUNDS changes. |
| D-16 tab Y top | RETIRE | The tab and the FT2 disc no longer exist. |
| D-17 bottom clearance rule | RETIRE | Low mount. If bottom parts remain, replace it with a height rule: CR underside height minus the MB part height minus the CR bottom part height >= margin. |
| D-18 bottom content | RE-DERIVE | Default all-top (Â§5.1). The "y < 66.862, 10 mm from L-FC" limit fails because L-FC is under the CR. |
| D-19 feet | RETIRE | Standoffs replace the feet (item 4.2). |
| D-29 5/5 mil, 1 oz | KEEP | Fab ruling. The operator may revert to 6/6 mil now that capacity is less tight. |
| D-30 CHG inner pads | RE-DERIVE | The pad and drill come from the receptacle drawing, TODO(verify: receptacle datasheet). |
| D-20 stack-up | RE-DERIVE | L4 changes from a "GND pour around bottom parts" to a solid GND layer that faces VSW-FC/VSW-BT. Tenting stays. VR-1 versus D-36 (finding 4). |
| D-21 VCHGIN | KEEP (conditional) | Re-check after D-09. |
| D-22 VCHGOUT | RE-DERIVE | The 1.5 mm corridor and the L4 strap existed because of the r6 +y edge and the W1 position. The L4 strap conflicts with a solid L4 GND. |
| D-23 VCHG/GND star | KEEP | W3/W4 stay at the pin columns. |
| D-33 power-via keep-outs | KEEP | Mechanism. |
| D-24 routing record | KEEP | History only. Item 4.7 re-runs the study. |
| D-34 strap keep-out | RE-DERIVE | Follows D-22. Moot if there are no bottom parts. |
| D-35 divider-top scope | KEEP / RE-DERIVE | The rule stays (all-layer metric per D-36). The packer-pad exemptions must be re-evaluated after re-placement. |
| D-36 rulings | KEEP / RETIRE | Via-in-pad conflicts with CR request Â§5.6 (open). The finish-method start board (r2_A routes) RETIRES: the placement changes. |
| D-25 to D-28 EIB | KEEP | EIB unchanged; it meets Â§5.1-5.4 (CR request `:178`). |

`LAYOUT_DECISIONS.md` Â§11 item 4 (MS8 inside-corner radius) RETIRES, because the rectangle has no concave corners. Item 12 (TSW post size) becomes the male header and receptacle mating check.

## 3. Classification: design doc A.7 / A.8 rows

| Row (line) | Class | Reason / input |
|---|---|---|
| A.7 r7 outline V1-V11 (`:771-789`) | RETIRE | The rectangle x 18.584-67, y 7-94 replaces it. |
| Concave corners (`:791`) | RETIRE | Rectangle. |
| Tab content (`:794-803`) | RETIRE | The tap field location is re-derived (item 4.3). |
| Tab trims and neighbours (`:804-813`) | RETIRE | ROP1-FC and L-FC are now covered (Â§3.3). |
| Clearances on copper rims (`:814-819`) | RETIRE | Rested on the bottom rule, L4 mask and the sheet. |
| Rejected zones (`:820-843`) | RE-DERIVE | The -x rejection stays (CR request `:105-106`). The others are superseded by Â§3.3, except work with the CR powered and fitted. |
| Outline freeze, T-A-08 MS3 (`:844`) | RE-DERIVE | Becomes the CR request Â§6 item 1 survey. |
| Pin-11 chamfer (`:846`) | RE-DERIVE | Finding 5. |
| Header stack TSW, 2.665/4.265 mm, PM4 (`:852-871`) | RETIRE | Receptacle selection from the Â§3.4 heights. The stack-top information is re-computed. |
| r6 rectangle, header body over D-BT-SQ (`:872-881`) | RETIRE | |
| Controlled interface, rules (`:882-897`) | RE-DERIVE | Tail flush-cut: the limit now comes from the underside height above the tallest MB part. "No bottom tap tails": KEEP. "<= 1.0 mm passives": RETIRE (Â§5.2). |
| Polyimide sheet, outline, relief holes, cut-outs, r6 defect (`:898-938`) | RETIRE | Operator question: an insulating film on the CR underside instead. |
| Bottom keep-out (`:939`), bottom clearance rule and 569.1 mmÂ² (`:942-951`) | RETIRE | |
| MB vias not tented (`:952`) | RE-DERIVE | The fact stays. The sheet cover is gone, so the CR L4 must present no exposed copper, or the gap must be quantified. |
| MB content under tabs (`:955`) | RETIRE | Becomes the full Â§3.2 list from the `.brd`. |
| Area 73.55/69.04 % (`:960`) | RE-DERIVE | Finding 2. |
| Neighbours CO-5V/LM1084 (`:967`) | RETIRE | Both are now under the CR. |
| Thermal band (`:969-982`) | RE-DERIVE | New sources: REG-5V, both boosts, both inductors. Needs MS4. |
| Feet table, construction, bedding, removal, repair (`:983-1073`) | RETIRE | |
| Tab stiffness and pin loads (`:1074-1087`) | RE-DERIVE | Plate on 4 standoffs. Needs the standoff height tolerance against the mating depth, so that the pins carry no load (CR request `:21-22`). |
| Feet effect (`:1088`) | RETIRE | |
| CR pad placement: taps, W1-W4, W6/W7 (`:1097-1134`) | RE-DERIVE | Item 4.3 connectors. The W1/W2 rule ">= 2.0 mm from MPPT-DISABLE that a tail would approach" is height-based now. U101 and J101: KEEP. Overhang: RETIRE. |
| EVM/EIB mounts (`:1140-1167`) | KEEP | |
| EVM reference placement, W-lead routes (`:1168-1194`) | RE-DERIVE | Routes measured from the tab X edges (H.23(l)). W1/W2 stay at a fixed 0.30 m. |
| A.8 hole table (`:1203-1215`) | KEEP | |
| Added pads W1-W7 (`:1221-1226`) | RE-DERIVE | Item 4.3. |
| F01-F24 rows, R175 (`:1227-1230`) | RE-DERIVE | |
| FT1/FT2 rows (`:1231-1232`) | RETIRE | |
| U101 centre, J101 region (`:1233-1234`) | KEEP | |
| Tab X assignment: six exclusions and the short table (`:1236-1318`) | KEEP rules / RE-DERIVE table | The hazards are circuit facts. The 1.04 mm pad-gap geometry changes if the taps become connector pins. |
| R106s placement (`:1320-1337`) | RE-DERIVE | The masking rules stay. The location target (tab X bottom, under the sheet) retires. |
| Per-region table (`:1339-1359`) | RE-DERIVE | Courtyard limit 18.2-48.2/34.64-66.64. Pocket "top only". Tab regions RETIRE. |
| r7 area booking H.23(e), (e2) (`:1373-1410`) | RE-DERIVE | |
| Header strips TSW (`:1412`) | RETIRE | Receptacle (item 4.1). |
| Copper (`:1415`) | KEEP | |
| Stack-up (`:1422-1428`) | RE-DERIVE | The 2-layer argument used "farthest point 25.66 mm"; now about 60 mm (ESTIMATE). Keep 4 layers for the shield to the MB. |
| MB battery path, T-A-06c "before the sheet is bonded" (`:1429-1437`) | RE-DERIVE | The overlay is reachable whenever the CR is unplugged. |
| U101 thermal pad, D103/C103, U101 input, Analog (`:1438-1451`) | KEEP | Finding 4 for the EP vias. |
| Header-pin current (`:1444-1448`) | RE-DERIVE | Receptacle contact ratings: pad 10 >= 3 A, VBAT+ >= 2.0 A per pin, TODO(verify: receptacle datasheet). |
| Hand assembly (`:1452-1456`) | RE-DERIVE | Stencil and reflow. Finding 3. |

## 4. Generator constructs that encode r7 geometry

**`gen/layout_cr.py`**
- `:21-25` `OUTLINE`/`P`/`INSET`: the r7 11-vertex polygon. Replace it with the rectangle and optional convex fillets.
- `:33-42` `FIXED` F01-F24 (tab X grid and low row) and R175. `:30-31` W1-W7. `:44-55` the D-09 shifts.
- `:75-79` `BOARD_ONLY` FT2H/FT1M/FT2M. Replace them with 4 standoff holes at TODO(measure: operator).
- `:83` `FP_RECT` (the r6 inset). `:97` `B1R`. `:98-99` `SPOTS` B3/S3 at y 70.8/73.1. `:100` `FT2_DISC`. `:101-102` `TAB_X`/`TAB_Y`. `:103-104` `FT1_KO`/`FT2_KO`. `:105` `L_FC_BOX`. `:112` `VOUT_BELT`. `:118` `TABY_TOP`.
- `:121-168` `mb_bottom_clearance()`, `mbk()`, and the `rule_areas()` entries MB_bottom_clearance/FT1/FT2. The function imports `r7_calc` (its own r7 `OUTLINE` at `r7_calc.py:603`).
- `:172` `GRID_BOUNDS` (17.0, 33.5, 66.0, 77.0) does not cover y 7-33.5 or 77-94. `:173` `RIM_X` 39.53. `:174` `LFC_Y` 66.862. `:175-176` BAND_W/BAND_E.
- `:181-202` class sets: `TABY_ICS`, `TABX_OK`, `TABY_BOT`, `POCKET_BOT`, and the "tab X bottom" semantics of `ANALOG_BOT`.
- `:219-222` `VOUT_L4_KO`/variant B.
- `:225-262` `setup()`: the `bot` region from `mbk()` and the FT keep-outs; `bot_core`/`bot_analog`/`taby_bot`/`pocket_bot` box(44.3, 63.71, 48.2, 66.64); the phases "tab Y gates" and "tab Y bottom logic".
- `:326-331` `target()`: C125 (50.8, 61.0), R106s (58.42, 61.48) on the tab X bottom, tab Y ICs at (27.0, 71.0).

**`gen/route_cr.py`**
- `:19` `VIN_L3`, `:22` `VOUT_IN` (the L4 strap), `:24-38` `PRE_VIAS`/`PRE_TRACKS`: tied to D-09 and D-22.
- `:45` the VCHGOUT_L4_strap zone.
- `:50-55` `VIN_L1`, `VOUT_L1` (top edge 66.64 = the r6 courtyard limit), `VCHG_L1`, `GND_L1_STAR`.
- `:70-73` `stitching()`: the keep-outs FT2_DISC, FT1_KO and the hardcoded (28.0, 73.25).

The L2 plane and the GND fills follow `P` and need no change (`:43`, `:59-66`).

**`gen/check_constraints.py`**
- `:60-63` the outline row (V1-V11, chamfer, area 1394.06).
- `:112-119` the rim rule x <= 39.53.
- `:129-135` the R106s "tab X bottom" row.
- `:136-147` the tab X/tab Y content rows.
- `:149-152` the "tab Y top" booking.
- New rows are needed for: the standoff holes; the receptacle pads against the A.8 table; one SMT side; chip size >= 0402 (0603 preferred); IC pitch >= 0.65 mm with a U101 exception row; VR-1/D-36 via-in-pad; part heights.

**Other files**
- `fplib.py:84-108` CHG22 (TSW, 1.9 mm pads, 1.1 mm drill), `:148-170` `ft2_hole`/`foot_mark`, `:320-325` the `EXTRA["cr"]` FT entries.
- `fpmap.py:24,32-34`.
- `netlist.py:77` the TSW MPN.
- `fab_readme.py:15-16` the size string (47.30 x 41.86, 1394.06 mmÂ², one NPTH).
- `pcbbuild.py:166,283,331` read `OUTLINE`/`GRID_BOUNDS`/`PARK`. `PARK` (70, 50) stays outside the new outline.

## 5. Proposal

1. Default to a **single-sided CR** and confirm it with a fresh H.23(e)-style booking on the new outline. Then:
   - retire D-17, D-18, D-32 and D-34;
   - make L4 a solid GND layer facing the MB;
   - replace the bottom clearance rule with a height-only check.
2. Replace `mb_bottom_clearance()` with a 3-D check that `check_constraints.py` reports:
   - inputs: the MB part heights from the Â§6 survey, the standoff height and the CR bottom heights;
   - output: the minimum vertical gap.
3. Rebuild the thermal-class regions (`RIM_X`, `LFC_Y`, `INT_ANALOG`) from a heat-source map that covers REG-5V, REG-FC, REG-BT, L-FC and L-BT. Until MS4 reports, keep the analog parts at >= 10 mm from each source rim, TODO(measure: operator, MS4).
4. Treat the standoff holes as the keying feature (finding 5).

## 6. Operator questions

1. U101: do you approve 0.5 mm pitch? No leaded TPS26630 exists (design doc `:1453`).
2. VR-1 (CR request Â§5.6) or D-36: which one governs? In particular, are the U101 EP thermal vias allowed?
3. Single-sided CR: do you accept it as the default if the booking fits?
4. Keying of the removable CR: asymmetric standoffs, a blocked receptacle position, or a silkscreen mark only?
5. Do you want an insulating film on the CR underside (replacing the polyimide sheet) over the untented MB vias?
6. Do you want to re-admit any of the DNP tiers of D-31 now that there is 3x area?
7. Should the 0.10 mm courtyard basis (D-03) and the no-silkscreen rule (D-12a) revert for stencil assembly?
