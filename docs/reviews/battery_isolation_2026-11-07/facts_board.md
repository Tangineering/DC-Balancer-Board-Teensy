# Battery isolation study: board fact sheet (rev 20260622)

This fact sheet records the as-designed connectivity, copper, connectors, spare control pins and supply rails of
the manufactured DC balancer board that bear on a battery-isolation rework. Every value cites a primary. Values
that no primary gives are marked BENCH or TODO(verify: source); inferences are marked UNCONFIRMED.

## 0. Sources and method

The net data were extracted programmatically from the Eagle XML files. The following sources were used:

- **SCH**: `references/Scale_Car_Board_20260624.sch` (parts, `<net>`/`<pinref>`, Ag105 library at lines 4351-4440).
- **BRD**: `references/Scale Car Board PCB 20260625.brd` (`<element>`, `<signal>`/`<contactref>`, wires, polygons,
  vias, design rules).
- **CSV**: `references/Scale Car Teensy IO - IO.csv` (authoritative pin map).
- **BOM**: `references/Scale Car Design PCB BOM 20260622.csv` (line numbers are file line numbers, header = line 1).
- **JOB**: `references/PCB Manufacturing Files/gerber_job.gbrjob` and `PnP_Scale Car Board_front.txt`.
- **Datasheets** in `references/Datasheets/`: Ag105 DS V1.1 (Nov 2021), BQ29200 SLUSA52C, RT1987 DS-00,
  TPS61288 SLVSFP3C, LM1084 SNVS037H, TB005-762 (Same Sky, 09/12/2024).
- **PJRC** Teensy 4.1 product page (pjrc.com/store/teensy41.html), read 2026-11-07.

Coordinates are BRD board coordinates in millimetres (origin at the lower-left of the 131.064 x 98.044 mm outline).
Pad coordinates were computed from the element origin, the rotation and the package pad offsets, and were checked
against trace end points.

## 1. Board construction

1. The board has **two copper layers** (BRD `layerSetup` = `(1*16)`; JOB `LayerNumber` 2).
2. The design-rule copper thickness is 0.035 mm per layer, which is 1 oz (BRD `mtCopper`). The weight that was
   actually ordered is TODO(verify: fabrication order).
3. The board thickness is 1.6608 mm (JOB `BoardThickness`).
4. **GND is a solid pour on both layers over the whole board** (BRD: GND polygons on layers 1 and 16, bounding box
   0.09-130.48 x 0.33-97.71 mm, `pour="solid"`, `thermals="no"`, `rank="3"`), stitched by 288 GND vias.
   Because `thermals="no"`, every GND through-hole pad is solid-connected to both pours.
5. Through-hole pad annulus: `rvPadTop` = 0.25 of the drill, clamped to 10-20 mil (BRD design rules). A 1.1 mm hole
   therefore has a ~1.65 mm pad; a 1.6 mm hole has a ~2.1 mm pad (computed, UNCONFIRMED against the Gerbers).
6. Minimum vias are 0.35 mm drill (BRD `msDrill`).

## 2. The pack connection: J-BT and J-BL

### 2.1 Connectors

| Ref | Part (BOM line) | Pins (BRD net) | Pad position | Hole |
|---|---|---|---|---|
| J-BT | TB005-762-02BE, 2-pole, 7.62 mm (BOM line 50, shared with J-FC, J-M) | 1 = **VBT**, 2 = **GND** | 1: (11.68, 19.56); 2: (11.68, 11.94) | 1.6 mm |
| J-BL | TB005-762-03BE, 3-pole, 7.62 mm (BOM line 52) | 1 = **VBAL+** (pack top), 2 = **VMID** (cell junction), 3 = **GND** (pack negative) | 1: (11.43, 45.72); 2: (11.43, 38.10); 3: (11.43, 30.48) | 1.6 mm |
| J-NTC | Wurth 691411410002, 2-pole 7.62 mm (BOM line 43) | 1 = N$34 (Ag105 THERM), 2 = GND | element (9.65, 59.94) | - |

The TB005-762 series is rated 30 A per contact (UL) and 32 A (IEC), 300 V (UL), with a contact resistance of 20 mOhm
maximum and an operating range of -40 to 105 degC (TB005-762 datasheet, p.1, Specifications).

Note: `docs/reviews/charger_eval_2026-11-05/incident.md` section (c) places J-BL pin 3 at (11.4, 45.7). That position
is J-BL **pin 1** (VBAL+); the trace end points of net VBAL+ start at (11.43, 45.72). Pin 3 (GND) is at (11.43, 30.48),
18.5 mm from J-BT pin 2.

### 2.2 Pack negative is bonded to PCB GND at two connectors

**Pack negative reaches PCB GND through two independent conductors**: J-BT pin 2 (main lead) and J-BL pin 3 (balance
lead negative). Both pads are on net GND (BRD `contactref` J-BT 2, J-BL 3) and are solid-connected to both pours.
Consequence (UNCONFIRMED magnitude): a switch inserted only in the J-BT negative lead leaves the balance-lead negative
wire as a parallel return path that would carry the full return current. Any negative-leg switch must therefore also
break J-BL pin 3, or the balance-lead negative must be moved to the switched side.

There is **no sense element, fuse or switch in the pack negative anywhere** on the board (SCH net GND contains J-BT 2,
J-BL 3, CHG VBAT-, CHG VIN-, REG-BT AGND/PGND, BAL GND/EPAD, every R2 divider leg, both INA253 GND/REF pins, REG-5V
ADJ/GND and the Teensy GND pins).

### 2.3 Balance lead network (J-BL to BQ29200)

The SCH nets are as follows:

- VBAL+ (J-BL 1) -> RB2 160 Ohm -> VC2 (BAL pin 1); VBAL+ -> RB1B 100 Ohm -> N$38 = BAL VDD (pin 7), CBL3 100 nF to GND.
- VMID (J-BL 2) -> RB3 260 Ohm -> VC1 (BAL pin 2), CBL2 100 nF to GND; VMID -> RB1A 100 Ohm -> VC1_CB (BAL pin 3).
- CBL1 100 nF between VC1 and VC2; CBLD 330 nF on BAL CD (pin 4).
- Balance traces are 0.4064 mm on the top layer only, with no vias (BRD signals VBAL+, VMID, VC1, VC2, VC1_CB).

The balance lead powers nothing except the BQ29200 (VDD through RB1B). It is not connected to VBT.

## 3. Net VBT and everything on it

### 3.1 Members

SCH net VBT: J-BT 1, **REG-BT VIN** (TPS61288, pads 7 and 15), L-BT 1 (2.2 uH), C1-BT 10 uF, C2-BT 100 nF,
**R1-BT** 16.2 kOhm (top of the V_batt divider), **REG-5V INPUT** (LM1084, pad 3), CIN-5V 10 uF / 25 V X7R
(BOM line 26), C-D12 10 uF, and **D-BT-SQ VOUT** (RT1987, pad 1_2).

### 3.2 Copper

The VBT copper is as follows (BRD signal VBT):

- A top-layer VBT pour around J-BT (8.0-28.2 x 12.7-23.6 mm) joins J-BT 1 to L-BT and the input capacitors.
- A 2.54 mm top trunk runs (23.2, 14.5) -> (34.8, 31.8). A 1.524 mm branch runs (34.8, 31.8) -> (34.3, 49.2) to a
  small VBT pour at D-BT-SQ (30.8-35.0 x 48.3-49.8).
- **The LM1084 feed is a 1.016 mm trace that crosses to the bottom layer for 10.7 mm through two single 0.35 mm vias**
  at (46.99, 34.54) and (57.66, 34.54), then reaches REG-5V pad 3 at (59.18, 39.57).
- A 0.254 mm branch feeds R1-BT at (28.45, 22.61).

### 3.3 The BT boost input and its current sense

1. REG-BT (TPS61288) draws its input directly from VBT. Its switching peak current limit is 12 / 15 / 17.1 A
   (min / typ / max) at VIN = 7.2 V, VOUT = 16 V, L = 2.2 uH (SLVSFP3C section 7.5, ILIM). The input voltage range is
   2.0-18 V (SLVSFP3C section 7.3).
2. **SNS-BT (INA253A1, BOM line 14) is on the boost OUTPUT, not on the pack.** Its IN+ / IN- shunt sits between
   VOUT-BT and VBUS-BT (SCH nets VOUT-BT: SNS-BT IS+1..3; VBUS-BT: SNS-BT IS-1..3, D-BT-EN VIN). The board therefore
   has **no measurement of pack current**. The INA253 GND, REF1 and REF2 are on PCB GND (SCH net GND).
3. A disabled TPS61288 passes VBT to VOUT-BT through the high-side body diode (CLAUDE.md section 2 hazard statement;
   design history, not re-derived here).

### 3.4 V_batt divider

R1-BT 16.2 kOhm (VBT) / R2-BT 10 kOhm (GND) on net BT-V to Teensy pin 25 (SCH; CSV `BT_VOLTAGE`). The full-scale input
is 3.3 x 26.2 / 10 = 8.646 V. The R2-BT ground pad is at (31.5, 22.6) on the PCB GND pour, so the divider measures VBT
relative to PCB GND, not relative to pack negative. The static load is 8.4 V / 26.2 kOhm = 0.32 mA.

### 3.5 D-BT-SQ (battery sequencing switch)

D-BT-SQ is an RT1987N-A at (29.72, 50.04) (BRD). **VIN (pads 10, 11_12) = VCHG = Ag105 VBAT+; VOUT (pad 1_2) = VBT**
(SCH, BRD). EN = net D-BT-SQ to Teensy pin 32 (`BT_SEQUENCE_ENABLE`). Its FLTB pin (4) is not connected; POVP and GND
are on GND; CAP has 1 nF (C-DC11); SS has 5.6 nF (C-DC12, left at 5.6 nF by bodge B3, `docs/PSCAD_SIM_DESIGN.md` table
row B3).

RT1987 facts (RT1987 DS-00): 3.4-32 V input range, 40 V absolute maximum, 8 A continuous / 20 A peak (10 ms), 20 mOhm
typical R_ON, EN active high ("Pull low to disconnect VIN from VOUT", section 8), ideal-diode reverse-current blocking
with a 35 mV forward regulation voltage (section 13). The device is powered from its VIN pin, so **D-BT-SQ is supplied
from the Ag105 side (VCHG); it cannot conduct when VCHG is below its UVLO** (UNCONFIRMED behaviour of the UVLO state
with EN high; DS-00 section 13 gives the UVLO threshold, the exact value was not legible in the text extraction:
TODO(verify: RT1987 DS-00 p.6-7)).

Consequence: the Ag105 output (VCHG) reaches the pack only forward through D-BT-SQ, and the pack is blocked from
back-feeding VCHG while D-BT-SQ regulates as an ideal diode.

## 4. The Ag105 module (CHG)

### 4.1 Footprint and pad map

The Ag105 is a through-hole DIL module (Silvertel library package `AG105`, 22 pads, 1.1 mm drill, square pads, 25 mm
row spacing). Element origin (47.498, 34.544), rotation R180 (BRD); PnP centroid (33.50, 50.51). The datasheet pin
numbers follow Ag105 DS V1.1 Table 2 (p.4).

| DS pin | Pad | Position | Board net | Copper |
|---|---|---|---|---|
| 1 VS | VSEL | (46.0, 39.08) | none | isolated from pours |
| 2 CS | CSEL | (46.0, 41.62) | none | isolated |
| 3 STAT | STAT | (46.0, 44.16) | CHRG-STAT -> Teensy 6 | top + bottom traces, 1 via |
| 4 Vin- | VIN- | (46.0, 46.70) | **GND** | solid to both pours |
| 5, 6, 9 IC | NC1, NC2, NC3 | (46.0, 49.24 / 51.78 / 59.40) | none | isolated |
| 7 SCL | SCL | (46.0, 54.32) | SCL -> Teensy 19, RSCL 10 k to 3V3 | traces |
| 8 SDA | SDA | (46.0, 56.86) | SDA -> Teensy 18, RSDA 10 k to 3V3 | traces |
| 10 Vin+ | VIN+ | (46.0, 61.94) | VCHG-IN | 1.524 mm traces, top + bottom |
| 11 MPPTD | MPPTD | (21.0, 64.48) | MPPT-DISABLE -> Teensy 5 | traces, no pull resistor |
| 12 MPPTS | MPPTSEL | (21.0, 61.94) | none | isolated |
| 13 THERM | THERM | (21.0, 59.40) | N$34 -> J-NTC 1 | 0.6096 mm top trace |
| 14, 15 VBat- | VBAT-1, VBAT-2 | (21.0, 56.86), (21.0, 54.32) | **GND** | solid to both pours |
| 16, 17 VLoad- | VLOAD-1, VLOAD-2 | (21.0, 51.78), (21.0, 49.24) | **none** | isolated from pours |
| 18, 19 VBat+ | VBAT+1, VBAT+2 | (21.0, 46.70), (21.0, 44.16) | VCHG | top VCHG pour (20.1-28.7 x 43.3-50.0) |
| 20 LD | LDIS | (21.0, 41.62) | none | isolated |
| 21, 22 VLoad+ | VLOAD+1, VLOAD+2 | (21.0, 39.08), (21.0, 36.54) | none | isolated |

VCHG has no traces and no vias; it is a top-layer pour joining VBAT+1/2, C-D11 and D-BT-SQ VIN (BRD signal VCHG).

### 4.2 The Ag105 load output and sense topology (datasheet facts)

1. The block diagram places the current sense between **Bat-** and **Load-/Vin-** (DS V1.1 Fig. 1, p.3).
2. VBat- (pins 14, 15) "Must NOT be connected directly to the GND pin"; VLoad- (16, 17) is "Internally connected to
   Vin-" (DS Table 2, p.4).
3. **The Ag105 has its own load output** (VLoad+ / VLoad-, pins 21/22 and 16/17) and a Load Disable pin LD (pin 20,
   "Pull this pin to Vin- to disable the load output", Table 2 p.4). By default the battery is presented on VLoad
   whenever the battery is not being charged, and "The Ag105 will never present the battery potential on the Vload
   output when charging is in process" (Load Disable, p.9).
4. Load-output limits: maximum continuous discharge current **I_DIS = 4 A**; maximum voltage across the VLoad pins 30 V
   (DC Electrical Characteristics rows 6 and 3, p.20). "The Ag105 provides no overcurrent protection between the
   battery and the load output" (VLoad output Protection, p.19).
5. Battery standby current with no input voltage is 120-420 uA (DC Electrical Characteristics row 7, p.20).
6. The DS typical circuits fit D1 (DST1550S) and a 10 A slow-blow fuse in the battery lead for reversal and
   over-current protection (Figs. 4, 9, 10, pp.7, 15, 16). The module does not provide battery-reversal protection
   (Battery Reversal, p.18).
7. Charge output over-current trips at 200 mA above the set charge current (Over current Protection, p.18).
8. Supply: 11-36 V operating, 36 V absolute maximum, UVLO 11 V (pp.19-20).

On this board the VLoad+, VLoad-, LD, VS, CS and MPPTS pads have **no copper connection**. The load output exists in
the module but is unused.

### 4.3 Can the VBat- or VLoad- pads be isolated in place?

- **VBAT-1 and VBAT-2 cannot be isolated by cutting one trace.** They are plated through-holes solid-connected
  (no thermal relief) to the GND pour on **both** layers. Isolation needs one of the following (UNCONFIRMED
  workmanship assessment):
  - remove the module pin from the hole (cut the pin above the board, or desolder) and connect a flying lead to the
    pin stub, leaving the GND barrel unused; or
  - mill an annular isolation ring around each pad on both the top and bottom pours. The barrel joins the two layers,
    so a cut on one layer is insufficient.
- `charger_eval_2026-11-05/incident.md` (Ag105 pads row) assesses desoldering the module with solid-connected GND pads
  on a 1.66 mm board as a lifted-pad and barrel-damage risk, and recommends cutting the module pins and removing them
  one at a time.
- **VLOAD-1/2, VLOAD+1/2 and LDIS are already isolated pads.** Wires can be soldered to them with no copper cut.
  VLOAD-2 at (21.0, 49.24) sits inside the VCHG pour's bounding box, so its clearance ring borders the VCHG pour on
  the top layer (BRD; clearance from `mtIsolate`, UNCONFIRMED width).
- **VIN-** is solid to both pours; it is the module's system-ground reference for STAT, MPPTD, THERM and I2C.
- Pin pitch is 2.54 mm along each row; VBAT-2 to VLOAD-1 is 2.54 mm centre to centre.

### 4.4 Charger input path

VCHG-IN (Ag105 VIN+) is fed by two RT1987 switches (SCH): **D-BC-FC** (VIN = VBUS, EN = Teensy 31 `FC_CHARGE_ENABLE`)
and **D-BC-RG** (VIN = V-MOT, EN = Teensy 30 `REGEN_ENABLE`). V-MOT is fed from VBUS by **D-MT-EN** (EN = Teensy 29
`MOT_PWR_ENABLE`). VCHG-IN also carries C-D8, C-D10 (10 uF each) and the R1-CHG 78.7 k / R2-CHG 10 k divider to Teensy
pin 38. The VCHG-IN copper is 1.524 mm traces on both layers via (58.67, 5.59) and (39.62, 34.54) (BRD).

## 5. BQ29200 (BAL)

BAL is a BQ29200DRBT at (24.38, 29.46) (BRD; BOM line 83). Pin map from SLUSA52C section 6 (pin configuration figure,
p.4) and BRD pads: 1 VC2, 2 VC1, 3 VC1_CB, 4 CD, 5 GND, 6 CB_EN, 7 VDD, 8 OUT, 9 PowerPAD; three 0.35 mm thermal vias
(pads V, V_2, V_4) on GND.

1. **BQ29200 GND = PCB GND.** The bottom-cell measurement is VC1 to GND (SLUSA52C section 7.5, OUT drive conditions
   "(VC2-VC1) and (VC1-GND)"). If PCB GND is separated from pack negative, the BQ29200 bottom-cell reading shifts by
   the GND-to-pack-negative offset (inference, UNCONFIRMED magnitude).
2. VDD is supplied from the pack top through the balance lead (RB1B 100 Ohm), not from VBT.
3. **OUT (pin 8, net BAL-NOK) has no copper** (BRD signal BAL-NOK: one contactref, zero wires). OUT goes from low to
   high on an overvoltage after the CD delay (SLUSA52C p.1 description and section 8). **The BQ29200 OVP therefore
   actuates nothing on this board.** An isolation switch could use OUT as a hardware OVP trip (design option, not a
   fact of the present board).
4. **CB_EN (pin 6) is on net CB-DISABLE to Teensy pin 9** (SCH, BRD), active low ("Active LOW pin at CB_EN",
   SLUSA52C section 7.5). This contradicts CLAUDE.md section 4, which says CB_EN is hardwired to GND. The schematic,
   board file and firmware (`teensy_controller.ino` lines 6728-6729: `INPUT_PULLUP`, then OUTPUT LOW) agree that
   pin 9 drives CB_EN; the CLAUDE.md wording is UNCONFIRMED against the as-built board.

## 6. Supply rails and who the pack powers

### 6.1 Rail inventory

| Rail | Source | Members (SCH) | Notes |
|---|---|---|---|
| VBT | Pack via J-BT 1; Ag105 VBAT+ via D-BT-SQ (forward only) | REG-BT, REG-5V input, R1-BT, caps | Pack 7.4-8.5 V operating limits (`LIMIT_V_BATT_MIN` / `MAX`, CLAUDE.md section 6) |
| 5V | REG-5V LM1084-5.0 (BOM line 25) | **Teensy VIN**, OP-FC / OP-BT V+ (OPA197), J2 pins 01/02, CO-5V 10 uF tantalum (BOM line 27) | LM1084 is the only 5 V source on the board |
| 3V3 | Teensy on-board regulator (Teensy 3V3 pins are members) | SNS-FC / SNS-BT VS, MDAC-FC / MDAC-BT VDD, RSDA, RSCL, RENC1, RENC2, CSNS caps, J1 29/30, J2 05/06, J3 even pins | PJRC: 250 mA recommended maximum for external 3.3 V use |
| VBUS | FC and BT boosts through D-FC-EN / D-BT-EN | D-MT-EN, D-BC-FC, R1-BUS divider | 16.0 V nominal, 17.5 V firmware OV limit (CLAUDE.md section 6) |
| VCHG-IN | D-BC-FC or D-BC-RG | Ag105 VIN+ | 11-36 V Ag105 input range |
| VFC | Fuel cell via J-FC 1 | REG-FC only | The H-20 purges to ~1 V (CLAUDE.md fw v30 addendum) |

There is **no gate-drive rail above VBUS** (no charge pump, no REGN-type rail). The RT1987 CAP pins are internal
charge-pump capacitors (DS-00 section 8) and are not usable as a rail.

### 6.2 LM1084 and Teensy power

1. LM1084-5.0: output regulation is specified for 6.5 V <= VIN <= 20 V (SNVS037H section 5.5); dropout is 1.5 V
   maximum at 5 A (p.1); the absolute maximum input-to-output differential is 25 V (section 5.1).
2. The Teensy 4.1 is powered from the 5V net at VIN (SCH net 5V: U$1 VIN). PJRC states that 5 V may be applied to
   VIN and that "a pair of pads on the bottom side may be cut apart, to separate VUSB from VIN". **Whether that pad
   pair is cut on the fitted Teensy is TODO(verify: BENCH).** If it is not cut, a connected USB cable back-drives the
   5V net (and the LM1084 output) from the host.
3. VIN input range of the Teensy 4.1: TODO(verify: PJRC schematic); the product page gives only "5V".
4. `docs/boost-bringup-debug.md` line 188 records a Teensy brownout with USB disconnecting when two 9 V batteries
   collapsed under a MOT_PWR inrush; this is consistent with board-powered logic.

### 6.3 Every way the pack powers the board, and what browns out without it

1. **VBT is the only supply of the logic.** The chain is pack -> J-BT 1 -> VBT -> LM1084 -> 5V -> Teensy VIN ->
   Teensy 3V3 regulator -> INA253 VS, AD5443 VDD, I2C and encoder pull-ups. The OPA197 droop amplifiers are also on 5V.
2. **No path from VBUS or VFC reaches VBT.** D-BT-EN is an ideal diode from VBUS-BT to VBUS and blocks reverse
   current (RT1987 DS-00 section 1). The TPS61288 does not run in reverse. REG-FC draws only from VFC.
3. **The only other source of VBT is the Ag105 output** (VCHG -> D-BT-SQ forward -> VBT). If the pack is disconnected
   while the Ag105 is charging, the Ag105 output becomes the only supply of the LM1084 and of REG-BT (inference,
   UNCONFIRMED; the Ag105 "Bring-Up" and battery-detection behaviour, DS p.6, would then see a non-battery load).
4. **Brownout list with the pack removed and no Ag105 output**: Teensy (all control, I2C, SD logging, Ethernet),
   both INA253 current senses (3V3), both MDACs (3V3) and both OPA197s (5V) of the droop chain, the BT boost input,
   and the V_batt reading. With the Teensy unpowered, every RT1987 EN falls to its pull-down level, so all six power
   switches open (section 7.3).
5. **The balance lead does not power the board.** VBAL+ reaches only the BQ29200 through 100-260 Ohm resistors.
6. Supplying the LM1084 from VBUS would be within its specified range (VBUS 16.0 V nominal, 17.5 V firmware limit,
   against the 6.5-20 V regulation range). The dissipation would be (16 - 5) V x I_5V (UNCONFIRMED I_5V: TODO(verify:
   BENCH)). This is a design lever, not a property of the present board.

## 7. Teensy pins and enable practice

### 7.1 Pins used by the CSV and firmware

The CSV assigns pins 0, 1, 3, 4, 5, 6, 7 (marked "No longer in use"), 9, 11, 12, 13, 14, 15, 18, 19, 24-32, 36-41.
The firmware defines exactly these (`teensy_controller.ino` lines 1979-2016) and leaves pin 7 undriven (lines
1986-1989). The firmware also uses the built-in micro-SD over SDIO (Teensy 4.1 pins 42-47, `SdFat`, line 1948),
native Ethernet (dedicated pads, line 1946) and Serial1 on pins 0/1. No firmware reference to Serial2-8, Wire1/2 or
SPI1/2 exists (grep).

### 7.2 Spare pins and their board connection

The spare Teensy pins are broken out to the 2 x 24 receptacles J1 / J2 (87606-324LF, BOM line 54), two contacts per
pin (SCH nets).

| Teensy pin | SCH net | Header contacts | Other parts on the net | Assessment |
|---|---|---|---|---|
| 10 | PIN10 | J1 23/24 | none | Free |
| 16 (A2) | PIN16 | J2 21/22 | none | Free, analog-capable |
| 17 (A3) | PIN17 | J2 19/20 | none | Free, analog-capable |
| 20 (A6) | PIN20 | J2 13/14 | none | Free, analog-capable |
| 21 (A7) | PIN21 | J2 11/12 | none | Free, analog-capable |
| 22 (A8) | PIN22 | J2 09/10 | none | Free, analog-capable |
| 23 (A9) | PIN23 | J2 07/08 | none | Free, analog-capable |
| 33 | PIN33 | J2 47/48 | none | Free |
| 34 | PIN34 | J2 45/46 | none | Free |
| 35 | PIN35 | J2 43/44 | none | Free |
| 2 | ENC_A | J1 07/08 | RENC1 pull-up to 3V3 (4.7 k as designed, 2.2 k per the 2026-08-16 bodge record) | Avoid: a pull-up may still be fitted (UNCONFIRMED after the encoder reroute); it would hold an enable HIGH during reset |
| 8 | ENC_B | J1 19/20 | RENC2 pull-up to 3V3 | Avoid, same reason |
| 7 | N$21 | via ROS 100 Ohm to ENC-EN, J1 17/18 | ENC-EN was rewired by the 2026-08-16 bodge (sensors hardwired to power) | Avoid until the bodge wiring is checked (BENCH) |

Header supply contacts: 3V3 on J1 29/30, J2 05/06 and the ten even pins of J3 (2 x 10 header); 5V on J2 01/02; GND on
J1 01/02, J2 03/04, J2 29/30 and the ten odd pins of J3 (SCH nets 3V3, 5V, GND).

### 7.3 Reset-state behaviour and pull-down practice

1. PJRC: "Teensy 4.1 pins default to INPUT most with a 'keeper' resistor". A keeper holds the last level weakly, so
   an enable line needs an explicit pull resistor to have a defined reset level.
2. The six RT1987 EN pins carry 10 kOhm EN-to-GND bodge resistors so that every switch defaults OFF while the GPIO is
   high-Z (CLAUDE.md section 2; bodge B7 in `docs/PSCAD_SIM_DESIGN.md`, per-switch scope and date OPEN as OQ-7).
   The RT1987 also has an internal EN pull-down (DS-00 section 13, `R_EN_PD`; value TODO(verify: RT1987 DS-00 p.6)).
3. MPPT-DISABLE, CB-DISABLE and CHRG-STAT have no external pull resistor (SCH nets list only the Ag105 / BQ29200 pin,
   the Teensy pin and the header). The firmware pre-sets CB-DISABLE with `INPUT_PULLUP` before driving it LOW (lines
   6728-6729) and drives every RT1987 EN LOW early in `setup()` (lines 6702-6720).
4. The Teensy logic level is 3.3 V. Any new switch whose control must survive a Teensy brownout needs its OFF state
   set by a passive pull, not by the GPIO.

## 8. Load-bearing facts for the isolation design

1. Pack negative is bonded to PCB GND at J-BT 2 **and** J-BL 3; both must be addressed by any negative-leg switch.
2. All logic is powered from VBT through the LM1084; there is no alternative path from VBUS or VFC. Disconnecting
   the pack browns out the Teensy unless a new supply path is added.
3. The board measures VBT against PCB GND and has no pack-current sensor; SNS-BT is on the boost output.
4. The Ag105 VBat- pads are solid-connected to both GND pours; isolating them needs pin removal or two-sided milling.
   The VLoad+, VLoad- and LD pads are unconnected and free to wire.
5. The Ag105 load output is rated 4 A continuous with no over-current protection, while the BT boost input can draw
   up to the 12-17.1 A switch limit. The intended Ag105 topology (all pack current through the module) therefore
   cannot carry the BT boost input current (inference from DS p.20 and SLVSFP3C section 7.5).
6. D-BT-SQ is the only link from the Ag105 output to the pack; it is supplied from VCHG and blocks reverse current.
7. The BQ29200 OUT pin is unconnected, so no hardware OVP actuation exists today; CB_EN is Teensy-driven.
8. Ten spare Teensy pins (10, 16, 17, 20-23, 33-35) are free on the J1 / J2 headers, six of them analog-capable,
   with 3V3, 5V and GND contacts on the same headers.
9. J-BT and J-BL are 30 A (UL) terminal blocks with 20 mOhm maximum contact resistance; an off-board switch in the
   pack harness needs no board copper change.
10. Available rails for gate drive are 3V3 (250 mA external budget), 5V (LM1084), VBT (7.4-8.5 V), VBUS (~16 V) and
    VCHG-IN (up to ~21 V); there is no rail above VBUS.
