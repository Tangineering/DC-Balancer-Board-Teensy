## mbparts: MB parts under the new CR outline, switching nodes, heat sources, CR underside treatment and the minimum underside height

### 1. Findings

**1.1 MB parts inside the outline.** I parsed the outline x 18.584-67, y 7-94 against `references/Scale Car Board PCB 20260625.brd`, using pads plus layers 21/22/39/40/51/52 for the extents. Scripts and full output: `C:\Users\ricky\AppData\Local\Temp\claude\3fe373bc8dcb48b3\88ddad5f-e7e9-4a73-b399-a08cdcf77486\scratchpad\outline\mbparts\parts.py` and `...\mbparts\parts_in_outline.txt`.

- 67 MB parts lie under the outline, plus the CHG footprint itself. 59 are fully inside and 8 are partly inside. All are top-side.
- The 8 partial parts cross an edge:
  - **-x edge:** C1-BT (x 18.00-20.10), C1-FC (18.51-20.60), CBL2 (17.31-19.78), RB2 (18.27-19.83) and RB3 (18.02-19.57). Each extent includes silkscreen, so the body may be clear. TODO(measure: operator).
  - **-y edge:** MDAC-BT (y 4.21-7.47) and OP-BT (4.41-9.31).
  - **+x edge:** C-DC3 (x 66.80-68.33).

Table 1 lists the parts by height class. The heights are package maxima.

| Height (mm) | Parts (package, value) | Source |
|---|---|---|
| 5.0 | L-FC (x 21.05-36.56, y 77.01-89.61), L-BT (20.29-35.80, 8.18-20.78); HCM1A1305V3-2R2-R, 2.2 ÂµH | `round4/work/mb_mechanical.md:92`; the HCM1305-2R2-R row (5.0 mm, DCR 4.60/5.29 mÎ©) is quoted from search snippets of Eaton TD 4371 ([datasheets.com](https://www.datasheets.com/eaton/hcm1305-2r2-r)). **TODO(verify: Eaton ELX1488):** the V3 family is not confirmed, and the sibling HCM1A1307V3 is 6.5 mm ([Eaton ELX1489](https://www.eaton.com/content/dam/eaton/products/electronic-components/resources/data-sheet/eaton-hcm1a1307v3-automotive-power-inductor-data-sheet-elx1489-en.pdf)). The ELX1488 fetch timed out twice. |
| 4.83 | REG-5V LM1084ISX-5.0 (TO-263, body x 50.97-62.31, y 36.87-54.51) | `LM1084ISX-5p0.pdf` p.30, "TO-263 - 4.83 mm max height" |
| 2.10 | CO-5V (CAPM3528X210, tantalum) | IPC name |
| 1.75 | OP-FC, OP-BT (SOIC-8 OPA197) | `mb_mechanical.md:95` |
| 1.35 | C4A/B/C-FC, C4A/B/C-BT (1210, 22 ÂµF) | IPC name |
| 1.20 | SNS-FC, SNS-BT (INA253A1, TSSOP-20) | `INA253A1IPWR.pdf` p.33 |
| 1.10 | C1-FC, C1-BT, C3-FC, C3-BT, C-D3, C-D11, C-D12, CIN-5V (0805); MDAC-FC, MDAC-BT (MSOP-10) | IPC name; `heights_40mm.txt` |
| 1.00 | REG-FC, REG-BT (TPS61288, VQFN-HR); D-BT-EN, D-BT-SQ (RT1987 DFN 3x3); BAL (BQ29200 VSON-8) | `TPS61288LRQQR.pdf` p.27; `RT1987_DS-00.pdf` p.19 (A 0.80-1.00); `BQ29200_TI.pdf` p.22 |
| 0.85 | C2/C5/C6/CC/CSNS-FC and -BT, CBL1-3, CBLD (0603 C) | IPC name |
| 0.60 | R1/R2/RC/RD1/RD2/RINJ/ROP1/ROP2-FC and -BT (0603 R); C-DC3, C-DC4, C-DC11, C-DC12 (0402 C) | IPC name |
| 0.40 | RB1A, RB1B, RB2, RB3 (0402 R) | IPC name |

**1.2 Errors in the change request Â§3.2.**
- D-FC-EN (68.834, 74.168), C-DC1 (71.12, 69.85) and C-DC2 (71.374, 75.946) are **outside** the outline (x >= 67.4), but Â§3.2 lists them as covered.
- Â§3.2 omits these covered parts: C-D11, C-D12, C-DC11, C-DC12, C2/C3/C5/C6-FC and -BT, CC-FC, CC-BT, RINJ-BT, MDAC-BT and OP-BT (both partial), and C-DC3.

**1.3 Values that differ from the `.brd`.** The `.brd` values are as-designed. The CLAUDE.md bodge records change two of them:
- RC-BT is fitted at 61.2 k, but the `.brd` shows 27.4 k.
- The RD1 = 215 k FB retune is recorded, but RD1-FC and RD1-BT read 237 k in the `.brd`.

Both are 0603 swaps and do not change the heights.

**1.4 Switching nodes.** REG-5V is an **LM1084 linear regulator**, so it has no switching node; the task's "REG-5V SW" does not exist. The two switching nodes are listed below. The polygon definitions come from the `.brd`, layer 1, via `nets.py`.

- **VSW-FC:** pour x 35.64-43.36, y 81.61-87.55 (28.8 mmÂ²), plus the L-FC and REG-FC bodies.
- **VSW-BT:** pour x 32.84-44.63, y 16.33-23.04 (42.3 mmÂ²), plus the L-BT and REG-BT bodies.
- **Switching frequency:** fSW = 500 kHz typ (440-600) at VIN 7.2 V, VOUT 16 V (`TPS61288LRQQR.pdf` p.6).

Other power copper under the CR:
- VFC pour, x 9.22-27.36, y 80.34-87.81;
- VBT pour, x 7.87-28.19, y 12.70-23.62;
- VOUT-FC, VOUT-BT, VBUS-FC and VBUS-BT pours;
- the 16 V VBUS pour, x 65.53-79.55, y 19.56-72.64, which lies under the CR strip x 65.53-67.

The MB has two layers (1 and 16). The coupling path is shown here with representative numbers. The capacitance from the VSW-BT pour to a CR L4 plane at a 6.5 mm gap is Îµ0Â·42.3 mmÂ²/6.5 mm â‰ˆ 0.06 pF. At an assumed edge rate of 16 V/5 ns (TODO(verify: scope)), that gives about 0.2 mA displacement-current spikes. A solid GND layer absorbs this current harmlessly. A routed high-impedance divider node in the same projection does not, and the inductor's stray field adds to the coupling.

**1.5 Heat sources under the CR.** All of these figures are estimates.

| Source | Position | Dissipation | Basis |
|---|---|---|---|
| REG-5V (LM1084) | 5V pour x 49.78-61.98, y 37.85-54.61 (153.1 mmÂ²) | 0.40 / 0.63 / 1.08 W; pour rise 9.7-55 Â°C; MB surface +2.4-11.9 Â°C at 10 mm | `mb_mechanical.md` Â§5.1-5.3 (lines 228-269) |
| REG-FC, REG-BT + inductors | above | â‰ˆ P_out(1/Î· âˆ’ 1). At the 14.6 W rig stack median (CLAUDE.md campaign II) the loss is 1.2-2.2 W per channel for Î· 0.92-0.85. At ~3 A Ã— 8 V per channel (CLAUDE.md RC-BT record) it is 1.9-3.6 W. Inductor copper is ~3Â²Ã—5.29 mÎ© â‰ˆ 48 mW, so most of the loss is in the IC, with core loss unknown. | Î· 0.85 is `HIL_PLANT.md:974` (a modelling choice); the measured curve is `TPS61288LRQQR.pdf` p.8 Fig 7-3, TODO(verify: read curve). RÎ¸JA 33.6 Â°C/W EVM / 71.4 standard (p.5 Â§7.4). |
| SNS-FC, SNS-BT | x 53.85-60.95 / 51.57-58.67 | ~18 mW at 3 A | 2 mÎ© integrated shunt, TODO(verify: INA253 DS) |
| D-BT-SQ, D-BT-EN (RT1987) | (29.72, 50.04), (63.75, 22.86) | small | R_ON TODO(verify: RT1987 DS) |
| CR U101 eFuse (on the CR) | CR | IÂ²R_ON at â‰¤ 3.21 A | TODO(verify: tps2663.pdf R_ON) |

**1.6 The strip x 17.70-18.584 on the r7 CR** (`cr/cr.kicad_pcb`, checked with `strip.py`). The strip contains only tab Y parts, with pads starting at x 18.375:
- U114 and U116 (LVC2G08, top), pads 1-4;
- R108, R131B and R176 (bottom), pad 1.

No track or via lies in the strip. The F.Cu, In1.Cu and B.Cu GND pours start at x 18.15. Every one of these features must move to at least x 18.584 + 0.40 mm (the D-20 router band), plus the courtyard. They are re-placed anyway, because the new outline supersedes tab Y.

**1.7 Items under the outline with no height on record** (operator survey, Â§6.1):
- two of the 10 kÎ© EN-to-GND bodge resistors, at D-BT-SQ and D-BT-EN;
- any OPA197 5 V bodge wire near OP-FC;
- the planned tap joints T9 (SNS-BT REF1), T22 (BAL pad 8) and T18 (CO-5V pad 1, conditional), each with an RTV dot (design doc D.1 PM6, PM7, PM11).

R171 and C-D2 are outside the outline.

### 2. Proposal

**2.1 CR bottom layer (L4).**
- L4 becomes a **solid GND pour with no routed signals** inside the **shadow zones**. A shadow zone is a hot or switching footprint grown by 3 mm in plan. The footprints are L-FC, L-BT, the two VSW pours, REG-FC, REG-BT and the REG-5V body plus its 5V pour.
- Signals elsewhere on L4 are allowed, as D-20 permits now.
- Stitch L2 GND to L4 GND at â‰¤ 5 mm pitch across the shadow zones.
- The CR keeps solder mask on L4.
- This keeps the A.6 single-point bond, because the plane touches the MB only through the CHG GND pins.
- With **no bottom SMT** (Â§5.1), the r7 bottom clearance rule (D-17), the polyimide sheet (r7-3), the feet FT1/FT2 and the fill hole (D-19) all retire.

**2.2 Via-in-pad.** D-37 already resolves the VR-1 / D-36 conflict: VR-1 applies first and plain via-in-pad is a fallback. One point is specific to this item. A fallback in-pad via wicks solder through to L4 and leaves a bump on the face toward the MB. Count 0.3 mm of bump in the gap budget only if the fallback is used. D-20 "tented both sides" cannot hold on the pad side of such a via.

**2.3 Keep-out map for temperature-sensitive CR parts.** The sensitive parts are:
- the TLV3012 comparators with their internal references (U102-U104, U115, U119-U121);
- the 0.1 % 25 ppm/K dividers R102-R104, R109-R112, R114 and R115;
- the BAV199 parts D104-D106 and D108;
- the timing capacitors.

The keep-out rules are:
- â‰¥ 10 mm in plan from the REG-5V body or 5V pour rim. The worst-case MB rise there is 2.4-11.9 Â°C (`mb_mechanical.md` Table 4).
- â‰¥ 5 mm from the L/REG/VSW boxes of both boosts.
- â‰¥ 2 mm from SNS-FC and SNS-BT.
- â‰¥ 5 mm from U101 on the CR.
- Each divider pair stays adjacent and aligned, so that both resistors see one temperature (ratio tracking).

The resulting areas (`keepout.py`) are:
- **free area for sensitive parts: 1783.6 of 4212.2 mmÂ²**, of which the main region is x 18.6-67, y 25.5-94 (1504 mmÂ²) less the FC boost corner;
- the best sub-region is x ~19-48, y ~26-72 (over the old CHG footprint, with only D-BT-SQ nearby);
- with a 3 mm boost margin, the free area grows to 2027.6 mmÂ².

The total plan shadow over hot copper and bodies inside the outline is 741.5 mmÂ². That shadow area carries pads, connectors, logic and power copper only.

**2.4 Air gap and minimum underside height.**
- **Minimum gap: 1.5 mm.** This is IPC-6012 bow/twist 0.75 % Ã— 87 mm â‰ˆ 0.65 mm (TODO(verify: IPC-6012 class figure)) plus â‰¥ 0.85 mm of clear air. The air gap also bounds the gap conductance (k/g â‰ˆ 17 W/mÂ²K at 1.5 mm).
- **Minimum CR underside = 5.0 (L-FC/L-BT, tallest covered part) + 0 (no bottom SMT) + 1.5 = 6.5 mm above the MB top.**
- If bottom 0603 passives are kept: 5.0 + 0.95 + 1.5 = **7.45 mm** (0603 cap height TODO(verify: part datasheet)).
- **THT tails** (receptacle, lead connectors) protrude below L4. Keep tails out of the L-FC/L-BT/REG-5V shadows plus 1 mm. Elsewhere the tallest covered part is 2.10 mm (CO-5V, next to REG-5V) or 1.75 mm (OP-FC/OP-BT), so tails â‰¤ 2.0 mm fit at 6.5 mm.
- **Header and receptacle:** the stack is the 2.54 mm male body plus the receptacle body and must reach â‰¥ 6.5 mm. A receptacle body of â‰¥ 3.96 mm is needed (TODO(verify: the selected receptacle drawing)).
- Any bodge part taller than 5.0 mm in Â§1.7 raises this floor (TODO(measure: operator)).

### 3. Design-doc and LAYOUT_DECISIONS rows that change

- **Design doc:**
  - A.7 thermal band (r7-7, line 969; H.23(h), line 3144): replace with the Â§2.3 keep-out map.
  - r7-4 bottom clearance rule, r3-10 (bottom â‰¤ 1.0 mm), r7-3 polyimide sheet and the A.7 feet: retire.
  - r7-5 allocation (bottom 69.04 % of 569.1 mmÂ²): recompute for one side.
  - A.7 "CR underside 2.665 mm" (line 854): becomes â‰¥ 6.5 mm.
  - A.8 stack-up L4: GND in the shadow zones.
  - The `mb_mechanical.md` Table 3 L-FC/L-BT row: verify against V3.
  - MS4 thermal survey: extend to REG-FC, REG-BT and both inductors.
  - D.1 PM0 and PM4: no sheet, and a removable CR.
- **LAYOUT_DECISIONS:**
  - D-17, D-18 and D-19: retire or replace.
  - D-20: L4 content.
  - D-01: the KiCad Y range becomes 6-93.
  - D-16: the tab Y set moves.
  - D-37: add the bottom-bump note.

### 4. Operator questions

1. What are the caliper heights of L-FC and L-BT, and is the fitted part V3 at 5.0 mm or taller?
2. What are the heights of the bodge resistors and wires at D-BT-SQ, D-BT-EN and OP-FC, and any others inside the rectangle?
3. Do you accept "no bottom SMT", which sets the underside to 6.5 mm, or do you want bottom passives (7.45 mm)?
4. Do you accept the 1.5 mm gap, and the rule that L4 carries no signals in the shadow zones?
5. Are C1-BT, C1-FC, CBL2, RB2 and RB3 bodies (not their silkscreen) clear of x 18.584?
6. Should the TPS61288 efficiency at 16 V out be measured, or read from Fig 7-3, to replace Î· 0.85?

