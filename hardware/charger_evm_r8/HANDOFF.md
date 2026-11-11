# Charger EVM r8 capture: handoff (2026-11-11)

This note gives the starting point for the next session. `LAYOUT_DECISIONS.md` is the full record.

## 1. State

| Item | State |
|---|---|
| EIB (2 layers, 24 x 38 mm) | complete: ERC 0, DRC 0 with schematic parity; fab package `fab/eib_2026-11-11/` |
| CR (4 layers, r7 outline 47.30 x 41.86 mm) | schematic complete (ERC 0); placement complete; power pours and straps complete; **95 signal nets not routed** |
| CR board file | `cr/cr.kicad_pcb` = placed + pours (DRC: 212 unconnected, 2 starved thermals, 2 silkscreen items) |
| Best partial CR routing | `cr/attempts/cr_pathfinder_0p1mm_partial.kicad_pcb` (reference only; 516 clearance violations) |
| Ordering BOM | `bom_2026-11-11/ordering_bom.csv`: 116 rows in the reference format; no price, stock or SKU read on a live page (bot checks) |
| Netlist audit | three independent reviewers, 216 parts against B.8/E: no discrepancy |

## 2. Rulings in force

- CR at 5/5 mil (0.127 mm) with 1 oz outer copper; rule file `tools/pcb/fab_rules/fab_4layer_5mil_oshpark_pcbway.kicad_dru` (D-29).
- EIB at 6/6 mil.
- DNP tiers 1 and 2 removed (D-31). Tier 3 (U117, R160-R163, C127, C124; R137 stays; F23 pad stays) is the next lever and is approved by the operator as part of the next session's methods.
- F22 and F24 pads stay without a CR net.

## 3. How to run

From `hardware/charger_evm_r8` in Git Bash (set `MSYS_NO_PATHCONV=1`, or net names such as `/GND` become paths):

1. `bash gen/make_board.sh cr`: libraries, schematic, ERC, netlist, placement, fab rules (about 3 min).
2. `cd gen && ROUTE_SKIP_FR=1 <venv python> route.py cr ../cr`: power copper and pours; copy the result to `cr/cr_pours.kicad_pcb`.
3. `PF_ITERS=60 bash gen/route_cr_pf.sh`: PathFinder, finishing router (GND plane vias), stitching. Add `--res 0.05` to the `pathfinder.py` call for the better 0.05 mm grid (about 110 s per iteration).
4. `bash gen/export.sh cr 2026-11-11` and `python gen/fab_readme.py cr 2026-11-11` once DRC is clean.

The venv is `C:\Life Ops\School\Thesis\DC-Balancer-round4\tools\pcb\.venv\Scripts\python.exe` (pcbnew, kiutils, shapely).
Every pcbnew script calls `wx.DisableAsserts()`: a KiCad debug assert otherwise opens a modal dialog that blocks an
unattended run. `pathfinder.py` writes a `conflict_report` (net, cells, sample positions in the KiCad frame).

## 4. Routing results so far

See `LAYOUT_DECISIONS.md` section 8. The best trajectory is PathFinder on the 0.05 mm grid with tiers 1-2: 73 nets in
conflict at iteration 0, 29 at iteration 11, 30-35 at iterations 12-15 (stopped). The 0.1 mm grid plateaus at
about 47-53. Conflicts are spread over the interior; the CR lacks capacity rather than having one choke point.

## 5. Candidate methods for the orchestrator

1. DNP tier 3, then PathFinder at 0.05 mm with 60+ iterations.
2. PathFinder tuning: slower present-cost growth, larger history increment, 6 mm search window, rip-up of only the conflicting branch.
3. Placement relief: a larger packer routing margin where area allows; tab X series resistors re-sited so fewer nets cross the CHG pin-1..10 wall; U105/U118 back to tab Y with a better tab Y packing (A.8 set).
4. Interactive push-and-shove routing in the KiCad GUI by a person, keeping the scripted placement, pours, rule areas, DRC and exports.
5. Only after these: an operator ruling on a tab X extension or a 6-layer stack (A.7 rejected the obvious outline extensions for non-height reasons).

## 6. Pitfalls found

- Git Bash path conversion turns `/GND` into `C:/Program Files/Git/GND`; set `MSYS_NO_PATHCONV=1`.
- pcbnew `FootprintLoad` returns unwrapped objects after a `PCB_IO_KICAD_SEXPR` instance exists; use kiutils for derived footprints.
- `PCB_VIA::GetWidth()` needs a layer argument in KiCad 9.
- Freerouting ignores the fab copper-to-edge rule; the router keep-out band (`EDGE_BAND`) handles it.
- Fixed power vias must be placement keep-outs (D-33), and the U101 top-edge pins need the +y channel (D-09).
