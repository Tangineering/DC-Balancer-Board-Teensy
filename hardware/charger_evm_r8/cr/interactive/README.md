# CR interactive routing instance (2026-11-12)

This folder is a self-contained KiCad 9 project for the interactive routing pass on the CR. The generator never
writes into this folder: `gen/make_board.sh cr` rebuilds `cr/cr.kicad_pcb` only.

## 1. Contents

| File | Content |
|---|---|
| `cr.kicad_pro` / `cr.kicad_pcb` | Start board (section 2). Open `cr.kicad_pro` in KiCad 9. |
| `cr.kicad_sch` | Schematic, for cross-probing and the schematic-parity check. Do not edit it here. |
| `cr.kicad_dru` | OSH Park / PCBWay 4-layer 5/5 mil custom rules (`tools/pcb/fab_rules/fab_4layer_5mil_oshpark_pcbway.kicad_dru`). |
| `charger_r8_cr.pretty`, `charger_r8_cr.kicad_sym` | Project-local libraries, referenced through `${KIPRJMOD}`. |
| `drc.rpt` | DRC of the start board with schematic parity. |

## 2. Start board

The start board is the adopted placement (commit `13a14fc`, strap keep-out D-34) with the round 2 scripted routes of
plan `r2_A`, seed 1, and the GND plane vias of `tools/pcb/corridor_route/plane_vias.py`. The checks give the
following results:

- Signal connections: 173 of 199 made; 26 open.
- GND connections: 31 open. Most are GND fill pieces on F.Cu and B.Cu with no via to the L2 plane.
- DRC with schematic parity: 0 parity issues, 57 unconnected items (26 + 31), 5 starved thermals, 2 silkscreen items.
  The silkscreen items and 4 of the starved thermals exist on the unrouted board; the fifth is U101 pad 25 on the
  B.Cu GND pour.

Open signal connections by net: /H1 4, /BT_OK 2, /FCCEIL 2, /N_IMON 2, /T2C 2, and 1 each on /ARM_OK, /CE_DRV_J,
/FCC_ON, /H1_RB, /H2C, /HB, /ILIM_REL_A, /J3V3_2, /N_DVDT, /N_FNP, /N_OV, /RFC_OFF_J, /SCL and /TS_EXT.

The scripted routes are a starting point only. Any of them can be ripped up and re-routed.

## 3. Rules for this pass (operator rulings 2026-11-12)

1. **Vias.** The default via is 0.6 mm pad / 0.3 mm drill, tented. The rule file permits down to 0.554 mm pad and
   0.254 mm drill. Plain unfilled vias inside SMD pads are acceptable; filled and capped vias are not available at
   OSH Park.
2. **GND.** Each GND fill piece on F.Cu or B.Cu needs at least one via to the L2 plane (In1.Cu). With via in pad
   allowed, a via in a GND pad ties the piece around that pad.
3. **Divider-top zones.** The four outlines on `Cmts.User` mark 2.0 mm around the pads of R102, R109, R111 and
   R114. The rule binds on all layers, but it is an optimization target, not a hard rule: keep the length of logic
   tracks that run parallel to analog tracks inside a zone as short as possible. Exemptions are acceptable where no
   other route exists. The pins exempted by D-35 are J1.7, J1.8, J101.7, J101.11, J101.13, U102.1, U103.1, U105.5,
   U109.1 and U109.3.
4. **Do not move** the parts fixed by A.8 (J1, J101, U101, U102, U103, the tap pads W1-W7, the feet), and do not
   edit the power pours, straps and rule areas. A part move elsewhere is acceptable; record each one so that it can be
   carried back to `gen/layout_cr.py`.
5. Comparator analog nets should stay out of the U101 loop region (preference, decision 2 of the morning review).
   /N_FLT and /CHG_EFUSE_FLT should use one via each.

## 4. Check before you hand the board back

1. In KiCad, refill all zones (B) and run DRC with "Test for parity between PCB and schematic" set. The target is
   0 unconnected items, 0 parity issues, and no violations other than the 2 silkscreen items.
2. From `hardware/charger_evm_r8/gen`, run the design checks on this folder:
   `<venv python> check_constraints.py cr ../cr/interactive`. The venv is
   `tools/pcb/.venv/Scripts/python.exe`.
3. Save the board and tell the design-owner session; it scores the result and carries any part moves back to the
   generator.
