# Charger EVM r8 capture: handoff (2026-11-11, updated 2026-11-12)

**Status (2026-11-12, end of D-50 steps 2-4).** Steps 1 to 4 of the D-50 round order are done, and check-in 1 has
passed. Step 2 is the section H re-run (`docs/reviews/charger_eval_2026-11-05/round4/calc/r9_calc.py`, design change
row r9-9). Step 3 is audit run 002, adjudicated in `docs/reviews/charger-design/run-002-2026-11-12.md` (r9-10): 29
findings, 0 blocker, 8 major and 21 minor after verification, with no fix applied. Step 4 is the new-outline
generator (D-51, D-52; `cr/geometry_check.md`). The D.3 rows are applied to `references/Scale Car Teensy IO - IO - 2026-11-12.csv`
(r9-11). The next action is operator check-in 2: README section 11 items 15 to 21.

This note gives the starting point for the next session. `LAYOUT_DECISIONS.md` is the full record. The 2026-11-12
decisions are D-39 to D-50 there, and every older entry carries its 2026-11-12 classification (retired, re-derive,
amended or kept).

## 1. State

| Item | State |
|---|---|
| EIB (2 layers, 24 x 38 mm) | complete: ERC 0, DRC 0 with schematic parity; fab package `fab/eib_2026-11-11/`, **not ordered**. Copper unchanged; U203, U204, C203, C204 and R258-R265 DNP, E4/E6 leads not fitted (D-49). The DNP set is applied by hand in `assembly/eib-bom.csv` and `assembly/eib-pos.csv`; `assembly/eib_ibom.html` is not regenerated and still shows the DNP parts as fitted. `gen/netlist.py` now carries `dnp=True` on the same 14 items (U203, U204, C203, C204, R258-R265, E4, E6); the EIB schematic, board and fab exports are not yet regenerated from it (open item). The operator reviews the package before an order |
| CR outline | **plug-on outline x 18.584-67, y 7-94 (MB frame), 48.416 x 87 mm, stencil and reflow assembly (D-39); applied to the documents** (`LAYOUT_DECISIONS.md`, `OUTLINE_CHANGE_REASSESSMENT_2026-11-12.md`). The generator is built on it (D-52: `gen/mb_brd.py`, `gen/cr_geometry.py`, `gen/layout_cr.py`, `gen/check_constraints.py`); `cr/geometry_check.md` passes every check. The height survey is closed by D-51. No board file is built on the outline yet |
| 2026-11-12 decisions | first round (`DESIGN_STATE_2026-11-12.md` Table 1) and second round (`decisions_2026-11-12/round2/`, digest `orchestrator_digest.md`) **recorded**; LAYOUT_DECISIONS D-39 to D-50 and the classification of D-01 to D-38 applied this round |
| CR netlist | regenerated from `gen/netlist.py` on the reduced design (D-47, D-31, D-44): 78 parts (r8: 145). W6 and W7 carry the through-hole placeholder footprints of D-45. `cr/charger_r8_cr.pretty` was rebuilt with `gen/fplib.py` and now holds the J102 Micro-Fit footprint, so ERC reports 0 errors and 0 warnings. The netlist export reports "schematic has annotation errors"; the cause is the six letter-suffix references C102a, C102b, C102c, R106s, R131A and R131B (the message disappears when all six are renamed to numeric references in a scratch copy). These references are the B.8 designators and are accepted. The generator now applies the 0.25 mm courtyard basis (`_CrtYd0.25`, D-52); the `cr/` library and `cr/cr.net` keep the 0.10 mm names until the next `gen/make_board.sh cr` in step 5 (connectivity unchanged). The netlist is frozen only after check-in 2 approves the run-002 fixes |
| CR board file | `cr/cr.kicad_pcb` is the **r7-outline** build (placed + pours, DRC 200 unconnected, 4 starved thermals, 2 silkscreen items). It is stale against the new outline and the reduced netlist; it is not an input to the next build |
| CR interactive pass (2026-11-12) | **superseded** by the new outline and the route-race (D-36, D-50). The project is archived at `archive_r7_outline/cr/interactive/` (move staged this round; KiCad must not hold the old path open) |
| r7 layout work | archived in `archive_r7_outline/` (variants, attempts, images, routability study); reference only |
| Best partial CR routing (r7) | `archive_r7_outline/cr/attempts/cr_pathfinder_0p1mm_partial.kicad_pcb` (reference only; 516 clearance violations) |
| Ordering BOM | `bom_2026-11-11/ordering_bom.csv`: r9 rows applied on the reduced part list (TSW/SSQ, J-TAP and cable assembly, 0603 and DBV rows; README section 8); the r9-5 mechanical rows are applied as well (feet, bed RTV and bond coupon rows deleted, 467MP re-scoped to the B1R wedge, CR PCB row on the plug-on outline with 1 oz / 0.5 oz copper, stencil and paste row added). No price, stock or SKU read on a live page (bot checks). The B1R wedge, posts and off-CR support rows wait for the A.3 lead route on the new outline |
| Section H re-run (step 2) | done: `round4/calc/r9_calc.py` with `r9_calc_out.txt` and `.json`; design change row r9-9; H.24(a)-(c) new |
| Audit run 002 (step 3) | adjudicated: `docs/reviews/charger-design/run-002-2026-11-12.md`; L.9 and Table L.9-1 final; 0 blocker, 8 major, 21 minor; no fix applied until check-in 2 |
| IO CSV | done: D.3 rows applied to `references/Scale Car Teensy IO - IO - 2026-11-12.csv` under the operator's delegation; the undated CSV is deleted; freed pins named FREE_10, FREE_16, FREE_17, FREE_21, FREE_23 (r9-11) |
| Netlist audit (r8) | three independent reviewers, 216 parts against B.8/E: no discrepancy. About 18 section-L dispositions rest on removed parts, so L.8 no longer certifies the design; the r9 audit (L.9) replaces it |

## 2. Rulings in force

CR board and assembly:

- Plug-on outline x 18.584-67, y 7-94; KiCad Y 6.00-93.00 (D-01, D-39).
- All SMT on the top side, one stencil and one reflow, no bottom fallback; escalate to the operator if a placement
  does not fit (D-44).
- Courtyards on the IPC-7351 nominal basis, 0.25 mm; reference designators on the silkscreen (D-03, D-12a).
- R101, R103, R104, R105, R106s and C101 in 0603; single-gate logic in SOT-23 (DBV), so U107 is SN74LVC1G11DBVR;
  U105, U106, U110 and U118 stay DCT (D-44).
- U101 stays TPS26630RGER, the one 0.5 mm exception; its exposed-pad vias are exempt from D-37, with window-pane
  stencil apertures and L4 tenting (D-40).
- Vias: no via on an SMD pad first; plain unfilled via-in-pad only as a listed last resort (D-37, D-36). 0.6 / 0.3 mm
  is the only via size (D-29).

Mechanics and leads:

- Mating stack: SSQ-110/112-01-L-S sockets on the MB, TSW-110/112-07-L-S pins on the CR (bodies on the underside);
  hard stop with the CR underside 11.05 mm above the MB; all 22 positions; no key; engagement-start height below
  21.70 mm; CR pins soldered while plugged (D-41).
- No standoffs; the CR is held by the 22-pin friction fit (D-42).
- Taps go to one CR connector, J-TAP; the W leads stay soldered on the CR as through-hole leads and unplug at the
  existing EVM terminals (D-45).
- J-TAP: Molex Micro-Fit 3.0 2 x 5 THT, hand-soldered last, cable 2147581101; cavity map row A T1 T7b T17r T5 T13,
  row B T6 T2 T17 T16 T10; placement constraints in D-46.

Stack-up and fab rules:

- L4 solid GND over the whole CR, no signals and no straps, stitched to L2 at <= 5 mm, masked; air gap >= 1.5 mm to
  the tallest MB part, THT tails included; sensitive-part window y 30.8-66.86 preferred, not hard (D-20).
- VCHGOUT routing is the design owner's call on L1 and, if needed, L3 (D-22).
- OSH Park-only CR rule file; router default 6/6 mil (0.1524 mm), 5/5 mil (0.127 mm) only at necks; 1 oz outer /
  0.5 oz inner; unused inner pads removed on every THT pad (D-29, D-30). The EIB stays at 6/6 mil.
- No polyimide sheet and no thermocouple (D-43). T-F-16 is retired (operator ruling 2026-11-12); the MB VBT trace rise
  under the CR is accepted unmeasured (design document J.1 item 25), so no T-F-16 open item remains.

Circuit:

- Ten taps (T1, T7b, T2, T5, T6, T10, T13, T16, T17, T17r); gate release = (H1·UVB) + FCC_ON·¬FCC_OFF +
  (QUAL·FCC_OFF·¬P5); /CE = ¬P5; RFC_OFF = FCC_OFF + (H1·UVB); 5-LVC mapping U105, U106, U107, U110, U118; CE_DRV
  buffered by U106A; R108 47 kOhm (D-47).
- No DNP option re-admitted; B.5 retired; the F22, F23 and F24 pads removed (D-31).
- Tap T22 and the BQ29200 pack-OV permit removed; pack OV is firmware-only (D-38).
- CHG_QUAL on Teensy pin 33; pin 10 is a freed pin (D-48). The IO CSV is amended in `references/Scale Car Teensy IO - IO - 2026-11-12.csv` (2026-11-12).
- EIB sense branch DNP; J101 pins 11 and 13 NC (D-49).

Firmware preconditions (design-document requirements; no firmware is edited in this round):

- The R5 MCU watchdog firmware is built with the rest of the new-charger firmware, in the handoff after the PCB
  design. No charging of any kind before R5 and T-W-01a pass; FC windows also need the full T-W-01
  (`decisions_2026-11-12/round2/dec2_hang_defence_2026-11-12.md`).
- The remaining second-round firmware rules (T_QUAL_MAX, QUAL before P5, the pin-34 edges, the CHG_IIN cross-check,
  the freed-pin rule, the new FR-08(b) and the new State 98 `J`) are in
  `decisions_2026-11-12/round2/dec2_firmware_rules_2026-11-12.md`.

## 3. Next steps (D-50)

Steps 1 to 4 below are done (2026-11-12). Check-in 1 passed (operator ruling (b)); step 2 became the new script
`round4/calc/r9_calc.py`, and the earlier scripts stay unmodified as the r8 record.

1. **Operator check-in 1:** a diff summary of the design-document and netlist update (done).
2. Re-derive H.4, H.19, H.20, H.22 and every row that rests on a removed part, and mark the r7-outline H.23 rows
   retired. This step runs before the audit. (Done, r9-9: the new script `round4/calc/r9_calc.py` does the re-run;
   `round3/calc/r3_calc.py` and `round4/calc/r7_calc.py` stay unmodified as the r8 record. Superseded: "Strip the
   removed parts from `round3/calc/r3_calc.py` and `round4/calc/r7_calc.py`, re-run both".)
3. The r9 audit (hybrid: adversarial-doc-review on B.1, F.3, F.5, G.3, J.1 and the reopened section-L items;
   self-review on B.3, B.6, B.7, F.2, F.4, G.2 and the A.8 adjacent-pair short table for the J-TAP order). The result
   is L.9, which replaces L.8 (done, r9-10).
4. In parallel with step 3: the new-outline generator. Replace every r7 construct listed in
   `outline_change_2026-11-12/retired.md` section 4 (outline, `GRID_BOUNDS`, `PARK`, `RIM_X`, `LFC_Y`,
   `mb_bottom_clearance()`, tab regions, feet, the r7 power geometry), add the TSW, J-TAP and W-pad footprints, the
   region table, the side flags and the new `check_constraints.py` rows, and add the H.23 successor geometry calc.
   Re-base every courtyard on the D-03 0.25 mm rule in `gen/fplib.py` and rename the `*_CrtYd0.10` footprints
   (open until done; the W6/W7 placeholders already use 0.25 mm), and replace the W6/W7 placeholder geometry
   once the 26/28 AWG OD is verified. Regenerate the EIB schematic, board and fab exports so that the
   `dnp=True` set in `gen/netlist.py` drives `eib-bom.csv`, `eib-pos.csv`, the kikit files and `eib_ibom.html`.
   (Done for the CR generator, D-51, D-52. Still open from this step: the EIB export regeneration from the
   `dnp=True` set (section 1, EIB row), because D-52 leaves the EIB exports unchanged. Open placeholders: the Molex 43045 drawing, the TSW pad and drill, the W6/W7 holes and the
   MS4 rim distance. For steps 5 and 6: `gen/make_cr_all.sh` must drop B.Cu from the PathFinder layer set, and
   `gen/route_cr.py` TRACK is 0.127 mm against the D-29 0.1524 mm default.)
5. **Operator check-in 2 (next):** the audit adjudication and fix approval; the netlist is frozen afterwards. The
   rulings are README section 11 items 15 to 21.
6. Placement on the frozen netlist, all SMT on the top side.
7. **Operator check-in 3:** placement images, before routing.
8. The full route-race (`route-race` skill: reference at four or more seeds, diagnosis, tested change requests, one
   design-owner batch).
9. DRC and the constraint check.
10. **Operator check-in 4:** before the fab package and any order. Then the fab package
    (`gen/export.sh`, `gen/fab_readme.py`).

Open items for the operator at check-in 2: README section 11 items 15 to 21, and the EIB package review before an
order (D-49). The check-in 1 items are closed: the T5-T10 diagonal was accepted (D-46), and the section 6 survey was
closed by D-51.

## 4. How to run (r7 outline; the scripts change with step 4)

Step 4 has changed the generator (D-52); the steps below are the r7 sequence and need the step-5 and step-6 changes
listed in section 3 before the next build.

From `hardware/charger_evm_r8` in Git Bash (set `MSYS_NO_PATHCONV=1`, or net names such as `/GND` become paths):

1. `bash gen/make_board.sh cr`: libraries, schematic, ERC, netlist, placement, fab rules (about 3 min).
2. `cd gen && ROUTE_SKIP_FR=1 <venv python> route.py cr ../cr`: power copper and pours; copy the result to `cr/cr_pours.kicad_pcb`.
3. `PF_ITERS=60 bash gen/route_cr_pf.sh`: PathFinder, finishing router (GND plane vias), stitching. Add `--res 0.05` to the `pathfinder.py` call for the better 0.05 mm grid (about 110 s per iteration).
4. `bash gen/export.sh cr 2026-11-11` and `python gen/fab_readme.py cr 2026-11-11` once DRC is clean.

The venv is `C:\Life Ops\School\Thesis\DC-Balancer-round4\tools\pcb\.venv\Scripts\python.exe` (pcbnew, kiutils, shapely).
Every pcbnew script calls `wx.DisableAsserts()`: a KiCad debug assert otherwise opens a modal dialog that blocks an
unattended run. `pathfinder.py` writes a `conflict_report` (net, cells, sample positions in the KiCad frame).

## 5. Routing results on the r7 outline (history)

See `LAYOUT_DECISIONS.md` section 8. The best trajectory is PathFinder on the 0.05 mm grid with tiers 1-2: 73 nets in
conflict at iteration 0, 29 at iteration 11, 30-35 at iterations 12-15 (stopped). The 0.1 mm grid plateaus at
about 47-53. Conflicts are spread over the interior; the CR lacks capacity rather than having one choke point.

## 6. Candidate methods for the r7 outline (superseded 2026-11-12)

The new outline and the route-race of D-50 supersede this list. It is kept as a record.

1. DNP tier 3 (applied 2026-11-11), then PathFinder at 0.05 mm with 60+ iterations.
2. PathFinder tuning: slower present-cost growth, larger history increment, 6 mm search window, rip-up of only the conflicting branch.
3. Placement relief: a larger packer routing margin where area allows; tab X series resistors re-sited so fewer nets cross the CHG pin-1..10 wall; U105/U118 back to tab Y with a better tab Y packing (A.8 set).
4. Interactive push-and-shove routing in the KiCad GUI by a person, keeping the scripted placement, pours, rule areas, DRC and exports.
5. Only after these: an operator ruling on a tab X extension or a 6-layer stack (A.7 rejected the obvious outline extensions for non-height reasons).

## 7. Pitfalls found

- Git Bash path conversion turns `/GND` into `C:/Program Files/Git/GND`; set `MSYS_NO_PATHCONV=1`.
- pcbnew `FootprintLoad` returns unwrapped objects after a `PCB_IO_KICAD_SEXPR` instance exists; use kiutils for derived footprints.
- `PCB_VIA::GetWidth()` needs a layer argument in KiCad 9.
- Freerouting ignores the fab copper-to-edge rule; the router keep-out band (`EDGE_BAND`) handles it.
- Fixed power vias must be placement keep-outs (D-33), and the U101 top-edge pins need the +y channel (D-09, r7 outline).
- `mb_bottom_clearance()` covers the whole MB; on the new rectangle it would forbid parts over both boosts. Remove it; do not re-run it (D-17).

## 8. Operator rulings (2026-11-11, after this handoff)

- **Fab.** The CR is built at OSH Park (4-layer: 1 oz outer, 0.5 oz inner). OSH Park does not offer filled and
  capped vias, so via in pad is not available. The D-20 via rule ("no via on an SMD pad or in its mask opening")
  stays in force without exception, J101 included. Rule file: `tools/pcb/fab_rules/fab_4layer_5mil_oshpark_pcbway.kicad_dru`.
- **Superseded 2026-11-12 (D-36):** plain unfilled vias inside SMD pads are acceptable; only filled and capped
  vias are excluded. **Superseded 2026-11-12 (D-37):** no via in an SMD pad first; plain via-in-pad only as a listed
  last resort. **Superseded 2026-11-12 (D-29):** the rule file becomes an OSH Park-only CR file.
- **/3V3.** The choice of tracks, a fill or a rail for /3V3 belongs to the PCB design session that orchestrates the
  routing attempts. On the new outline L4 is solid GND (D-20), so /3V3 runs on L1 or L3.
- **Routing skills.** `route-race` and `board-routing` (`.claude/skills/`) and the tools in `tools/pcb/corridor_route/`
  are merged to main. `tools/pcb/corridor_route/reference/design-intake.md` describes the change-request intake.
  The routing study measured 42, 39, 40, 39 open connections of 210 at seeds 1 to 4 on a copy of commit 71ecdef
  under D-20; with tier 3 DNP and /3V3 held out, 20 to 23 (r7 outline). The U101 +x pocket has one F.Cu lane for
  /N_UV, /N_OV and /N_DVDT; relief needs R105 about 0.3 mm and R101 about 0.6 mm further in +y, with the /N_UV via out
  of the lane (r7 outline; the pocket is re-derived on the new outline, D-09).
- **Finishing scripts.** In a scratch test, `gen/finish.sh` ripped up routed nets and added DRC violations on the
  corridor router's output. Use `tools/pcb/corridor_route/plane_vias.py` for plane vias with that router.
