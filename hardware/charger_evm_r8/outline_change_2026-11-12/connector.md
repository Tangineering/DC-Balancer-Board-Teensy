# Item [connector]: MB male header and CR receptacle for the 22 CHG holes

## 1. Findings

**F1. The CHG pattern is two single-row columns 25.0 mm apart. It is not a 2-row header.**
- In the `.brd` AG105 package (`references/Scale Car Board PCB 20260625.brd`:1755-1781), pads 1-10 (VSEL..VIN+) sit at package x 1.5 and pads 11-22 (MPPTD..VLOAD+2) at package x 26.5. All 22 holes are drill 1.1 mm and square. The element is CHG at (47.498, 34.544), R180 (`.brd`:3508).
- In the board frame, pins 1-10 lie on x 45.998 (y 39.084-61.944) and pins 11-22 on x 20.998 (y 36.544-64.484). The design doc gives the same table (A.8, `docs/charger_bq25798_wiring_design_2026-11-05.md`:1205-1215) and the same pitch and column spacing (A.2, :456-458).
- The pad restring is the `.brd` rule rvPadTop 0.25 inside 10-20 mil (`.brd`:2491, 2498-2499), which gives a 1.650 mm square MB pad (design doc :816 and :918).
- Consequence: you need two single-row strips, 1x10 and 1x12, offset by one pitch at each end (:1412-1414). A 2x11 or a 2-row part does not fit the pattern.

**F2. Current requirements.**

| Pin(s) | Requirement | Source |
|---|---|---|
| 10 (VIN+) | 2.41 A carried, rated >= 3 A | :1444-1445, T-A-05 :3186 |
| 18/19 (VBAT+), 14/15 (GND) | 1.93 A each at 60/40 sharing, rated >= 2.0 A | :1445-1446 |
| 4 (VIN-) | 2.41 A | :1447 |

Samtec rates TSW mated with SSQ at **6.3 A per pin, with 2 positions powered** (TSW/HTSW catalogue F-226 p.1, current table; SSW/SSQ catalogue F-226 "Current Rating"). That leaves margin on every power pin. Samtec does not state the temperature-rise basis on the page: TODO(verify: Samtec power report tc0838-1975, https://suddendocs.samtec.com/testreports/tc0838-1975_reportrev2_pwr.pdf). The WR-PHD fallback (Option C) is listed at 3 A, which is exactly the pad-10 requirement with no margin.

**F3. Samtec mating data used in the stack arithmetic.**
- SSQ insulator height is 8.51 mm and the single-row body is 2.41 mm wide.
- Body length is 2.54 x N + 0.51 mm: 25.91 mm for 10 pins and 30.99 mm for 12 pins.
- Insertion depth is 3.68-6.35 mm. Through-hole style -01 has a 2.64 mm tail; the low-insertion-force (LIF) equivalent is -21.
- The rating is 100 cycles with 10 Âµin Au.
- Source: https://suddendocs.samtec.com/catalog_english/ssq_th.pdf

For TSW-1xx-07, A = 10.92 mm, B = 2.54 mm, C = 5.84 mm, and the body is 2.54 mm. Samtec recommends a 1.02 Â± 0.03 mm hole for the -LL option (https://suddendocs.samtec.com/catalog_english/tsw_th.pdf p.1-2).

The current TSW sheet lists plating codes -F, -GF, -L and -T only. The `-G` in the ordering BOM parts TSW-110-07-G-S and TSW-112-07-G-S (`hardware/charger_evm_r8/bom_2026-11-11/ordering_bom.csv`, CHG header rows) is not on that sheet. TODO(verify: Samtec/Digi-Key that -G is still orderable; otherwise use -L).

**F4. Insertion and withdrawal forces are from older SSQ sheet revisions and disagree between revisions.**

| Contact | Insertion | Withdrawal | Totals for 22 pins (in / out) |
|---|---|---|---|
| Standard | about 1.67 N avg per contact | about 1.39 N | about 37 N / 31 N |
| LIF | 0.81-0.92 N | 0.81 N | about 18-20 N / 18 N |

TODO(verify: current Samtec SSQ spec). Sources: https://www.farnell.com/datasheets/82032.pdf and https://www.mouser.com/catalog/specsheets/samtec_samis20654-1.pdf.

**F5. The tallest covered MB parts** are L-FC and L-BT at 5.0 mm, TODO(verify: Eaton HCM1A1305V3), and REG-5V at 4.83 mm (CR Â§3.4). The heights of the bodge wires and resistors are unknown: TODO(measure: operator, CR Â§6 item 1).

**F6. The MB header body positions were already used in r7.** r7 sat TSW bodies on the MB at these columns (A.7 :852-854, H.23(j) :3147), so the plan footprint of the MB header body is not new. However, the r7 polyimide sheet (0.125 mm) under the body retires with the low mount, so the body now seats on the MB solder mask directly.

## 2. Proposal

### 2.1 Option A (recommended): Samtec TSW on the MB, SSQ on the CR, standoff-defined height

**MB side.** Fit TSW-110-07-L-S in column x 45.998 (pins 1-10) and TSW-112-07-L-S in column x 20.998 (pins 11-22). Mount them with the short end B (2.54 mm) down through the MB and post C (5.84 mm) up as the mating post.
- MB-bottom protrusion is 2.54 - 1.6 = 0.94 mm. The MB thickness of 1.6 mm is an ASSUMPTION, TODO(measure: MS6 caliper).
- The r7 PM4 step-4 tail cut is no longer needed.
- Populate all 22 positions. The 11 NC pins add retention and alignment.
- Datasheet: https://suddendocs.samtec.com/catalog_english/tsw_th.pdf

**CR side.** Fit SSQ-110-01-L-S and SSQ-112-01-L-S.
- The bodies are on the CR bottom. The tails go up through the CR and are hand-soldered from the top after the last reflow (CR Â§5.3).
- Tail protrusion above a 1.6 mm CR is 1.04 mm.
- Datasheet: https://suddendocs.samtec.com/catalog_english/ssq_th.pdf

**Stack arithmetic** (MB top = 0):
- Header body top: 2.54 mm.
- Fully bottomed stack (socket face on the header body): 2.54 + 8.51 = 11.05 mm. Insertion depth = 5.84 - g, where g is the gap between the body top and the socket face. The rule 3.68 <= 5.84 - g <= 6.35 gives g from 0 to 2.16 mm.
- **Proposed standoff and CR underside height: 12.0 mm** (g = 0.95 mm, insertion 4.89 mm). The usable window is 11.05-13.21 mm.
- The CR then rests on the four standoffs and never on the pins, as CR Â§2 requires. The 0.95 mm gap absorbs header seating and standoff tolerance: TODO(verify: standoff part tolerance), TODO(measure: header seated height after soldering).
- Socket body bottom: 12.0 - 8.51 = 3.49 mm above the MB, over the header bodies only.
- Clearance to L-FC and L-BT: 12.0 - 5.0 = **7.0 mm**, less any CR bottom-side part height. With the single-sided-SMT preference (CR Â§5.1), nothing hangs below the CR except the socket bodies.
- CR top: 13.6 mm above the MB.
- **Taller variant** if the heat review (CR Â§4 item 6) wants more air gap: TSW-1xx-14-L-S (C = 8.13 mm, B = 2.79 mm) on 14.0 mm standoffs gives insertion 5.18 mm and a window of 12.83-15.50 mm. However, this variant has no hard stop inside the window, and C exceeds the 6.35 mm maximum insertion depth. The standoffs must therefore prevent over-insertion.

**Current.** 6.3 A per pin (F2): 2.6x the pad-10 load and 3.3x the 1.93 A VBAT+ load.

**Assembly sequence.**
1. Desolder and clear the 22 MB CHG holes after you remove the Ag105.
2. Plug the TSW strips into the SSQ strips of the finished CR.
3. Set the CR on the standoffs and solder the TSW tails from the MB underside. This aligns the strips to the CR at the true stack height.
4. Unplug the CR and inspect the MB joints.

### 2.2 Option B: as Option A with SSQ-110-21-L-S and SSQ-112-21-L-S (LIF contacts)

The footprint, height and current are unchanged. The withdrawal force falls to about 18 N for 22 pins (F4), so the CR comes off with less rocking of the pins. The trade-off is lower contact normal force, so contact resistance on pins 10, 18 and 19 is TODO(verify: Samtec qualification report 579717). LIF is not available with Tin plating, which is why -L is chosen.

### 2.3 Option C (second source, marginal): WÃ¼rth WR-PHD

The parts are 61301011121 and 61301211121 (male) with 61301011821 and 61301211821 (female, single row). The family is listed at 3 A (https://www.we-online.com/catalog/datasheet/61301011021.pdf). That is exactly the pad-10 >= 3 A requirement, so it fails a margin test. Part numbers, heights (the dual-row reference is 8.40 mm) and post lengths are TODO(verify: WÃ¼rth datasheets). Use this option only if Samtec parts are unavailable.

### 2.4 KiCad footprint (CR)

Keep the existing pad set of `Ag105_CHG_Carrier_22pin_P2.54mm` (D-02):
- 22 PTH pads, 1.1 mm drill, 1.9 mm pads on L1 and L4, no unused inner pads (D-30). Pads 1 and 11 are square.
- The 1.1 mm drill gives about 0.1 mm radial clearance on the 0.635 mm square tail (0.898 mm diagonal). Samtec recommends 1.02 mm: TODO(verify: SSQ footprint print, https://suddendocs.samtec.com/prints/ssq-1xx-xx-xx-x-xx-xxx-xx-xx.pdf).

Change only the graphics:
- Add two bottom courtyard and fab rectangles for the socket bodies: 2.41 x 25.91 mm centred on (45.998, 50.514), and 2.41 x 30.99 mm centred on (20.998, 50.514). Add +0.25 mm courtyard margin.
- **Keep the footprint on F.Cu. Do not flip it to B.Cu to put the body underneath.** A flip mirrors the pad x about the anchor and breaks pin identity.
- Add a top hand-solder access keep-out of >= 1.0 mm from each pad to any SMT courtyard. This is a proposal, not a sourced value.

The KiCad stock footprints `PinSocket_1x10/1x12_P2.54mm_Vertical` are not used, because they cannot hold the 25.0 mm column spacing and the one-pitch offset in a single footprint.

### 2.5 Pin-identity gate (still applies, in a changed form)

1. **Pad-coordinate gate (unchanged).** `docs/reviews/charger_eval_2026-11-05/round3/calc/pin_identity_check.py` (lines 10-16) compares a KiCad pad CSV with the `.brd` positions at 0.05 mm, with `--kicad-y-down`. Run it as T-A-06 step 0 on the receptacle footprint, together with `check_constraints.py` (D-02). It now also catches an accidental B.Cu flip.
2. **New physical identity.** The MB headers are identical pins, so pin identity at the MB end comes from the MB holes alone. The outline chamfer that D-02 used as the mirror key does not exist on the rectangular outline (CR Â§3.1). The four corner standoffs are 180Â°-symmetric, so they do not key either.
   - Keying comes from the 10/12 asymmetry. On a CR rotated 180Â°, the two MB pins at (20.998, 36.544) and (20.998, 64.484) land 1.015 mm beyond the ends of the 10-socket body and strike the CR laminate.
   - **New rule:** keep a no-hole, no-via zone of 1.0 mm radius on the CR at CR-frame (45.998, 36.544) and (45.998, 64.484).
   - Add an asymmetric silkscreen arrow at pin 1.
   - Optionally offset one standoff to make the pattern asymmetric: TODO(measure: operator).

## 3. Rows that change

**Design doc:**
- A.2 (:475): the "Mechanical anchors only (soldered)" text changes to "mated, no net".
- A.7 header stack bullet (:852-860): replace it with the Option A stack (12.0 mm underside), and drop the sheet, B-up/C-down and step-4 cut text.
- A.8 "Header strips" (:1412-1414): becomes MB TSW plus CR SSQ.
- A.8 header-pin current (:1444-1447): add the 6.3 A rating.
- PM4 (:2019): replace with the plug-and-solder alignment sequence.
- E BOM (:2272): SSQ x2 added, TSW plating changed to -L, TSW lead style unchanged.
- H.23(j) (:3147): re-derive with the new arithmetic.
- T-A-05 (:3186): post length now checked against standoff height, not board thickness.
- T-A-06: add the keying-blank check.
- K sources (:3683): add the SSQ F-226.

**LAYOUT_DECISIONS.md:**
- D-02 (:52-58): replace the chamfer-keying sentence with the keying-blank rule.
- Â§4 library row "CHG header (22 pins)" (:79): add the bottom socket courtyard and the no-flip rule.
- D-30: unchanged.
- Item 12 TODO (:402): extend it to the SSQ print.

**Ordering BOM:** the TSW-110 and TSW-112 rows (-G to -L) and two new SSQ rows.

## 4. Operator questions

1. Do you accept a 12.0 mm CR underside on 12.0 mm standoffs (Option A), or do you want the 14 mm variant for thermal margin?
2. Standard contacts (Option A) or LIF (Option B)? This depends on how often you expect to unplug the CR within the 100-cycle rating.
3. Is the MB underside clear of the 0.94 mm TSW tail protrusion at both columns? TODO(measure: operator).
4. Do you want an asymmetric standoff position as a second key, in addition to the keying blank?
5. Should all 22 positions be populated? The recommendation is yes.
