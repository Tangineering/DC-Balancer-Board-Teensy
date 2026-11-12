# Charger EVM r9: design review guide

## 1. Purpose and how to read this document

This README presents the r9 charger design for operator review, with progressive detail. Section 2 shows the overall
functional block diagram and the architecture. Section 3 lists what changed on 2026-11-12; a reader who needs only the
changes can read section 3 alone. Sections 4 to 7 explain the design concepts, the permit gate, the operating modes and the
firmware consequences. Sections 8 to 12 cover the physical implementation, status, plan, open items and the source
index. Appendix A defines the abbreviations and the identifier families.

The full record is the design document `docs/charger_bq25798_wiring_design_2026-11-05.md` (revision r9). Section 12 maps
each topic to its authoritative file and section. Neither text that the design document marks "superseded", "withdrawn"
or "history" nor the r7-outline work in `archive_r7_outline/` is the current design.

## 2. Architecture

### 2.1 Block diagram

Three different parts carry the refdes J1. In this document, **CR J1** is the 22-pin CHG header (TSW strips). **MB
J1/J2** are the Teensy 4.1 Dubox receptacles, and **EVM J1** is the charger VIN screw terminal.

Figure 2.1 shows the power and signal architecture of the charger path. Power flows from VBUS or V-MOT into the EVM and
returns to the pack through CR J1 pads 18/19.

Figure 2.1. Charger path, block diagram (r9).

```text
 FUEL CELL (H-20)                       BATTERY PACK 2S (VBT), pack V- = PCB GND
      |                                      ^                  |
  FC boost TPS61288                          | D-BT-SQ          BT boost TPS61288
      |  (FC_REG_ENABLE 3)                   | (BT_SEQ 32)      |  (BT_REG_ENABLE 4)
  D-FC-EN (FC_BUS 27)                        |              D-BT-EN (BT_BUS 28)
      |                                      |                  |
      +============ VBUS 16.0 V ============ ) =================+
      |                  |                   |
      |              D-MT-EN (MOT_PWR 29)    |  VCHG (MB net)
      |                  |                   |
      |               V-MOT ---- VESC/motor  |
      |                  |                   |
  D-BC-FC (FC_CHARGE 31) D-BC-RG (REGEN 30)  |
      |                  |                   |
      +------> VCHG-IN <-+  (pin 38 CHG_VOLTAGE divider R1-CHG)
                  |                          |
 ===MB============|==========================|============================================
                  | CR J1 pad 10             ^ CR J1 pads 18/19     pads 4, 14, 15 = GND
 ===CR (plug-on: SSQ sockets on the MB, TSW strips on the CR)=============================
                  v                          |
        eFuse U101 TPS26630 + D103           |
                  |  VCHGOUT                 |  VCHG
                  |  W1/W2 20 AWG            |  W3/W4 18 AWG
                  v                          |
 ===EVM (BQ25798EVM on an insulating plate)==|============================================
   EVM J1 VIN ---> BQ25798 buck-boost ---> EVM J5 BATTERY
                  ^       ^           |
                 /CE   ILIM_HIZ      STAT
                  |       |           v
 ===EIB (2-layer, beside the EVM)==========================================================
   U201/U202 open-drain drivers, Q201-Q203; leads E1, E2, E3, E5, E7, E8 to EVM test points
                  ^                   |
                  | CE_DRV,           | STAT
                  | ILIM_REL_A/B,     v
                  | RFC_OFF, 3V3 x 2      W5 14-way ribbon: CR J101 <-> EIB J201
 ===CR permit gate=========================================================================
   Comparators U102 H1, U103 UVB, U119 FCC_OFF, U120 FCC_ON
   Logic U105, U106, U107, U110, U118  ->  CE_DRV, ILIM_REL_A/B, RFC_OFF
                  ^                                   ^
                  | J-TAP J102 (Micro-Fit 2 x 5)      | CR J1 pad 11 CHG_ARM (Teensy pin 5)
                  |  10 tap conductors                |
 ===Taps==========|===================================|====================================
   T1  V-MOT  (C-D6, R170)      T2 VBUS (C-D2, R171)     T7b, T17r shields
   T5  pin-31 EN net (MB J1.45) T6 3V3  (MB J1.29)       T10 pin 33 CHG_QUAL (MB J2.47)
   T13 pin 34 CHG_H1_RB         T16 pin 35 CHG_EFUSE_FLT T17 pin 22 CHG_IIN
                  ^                                   ^
 ===Teensy 4.1 on MB J1/J2 (Dubox 2 x 24)=================================================

 CR J1 signal pads outside the permit gate:
   pad 3 STAT          EVM STAT -> E7 -> EIB -> W5 -> CR -> CR J1 pad 3 -> Teensy pin 6
   pads 8/7 SDA/SCL    Teensy pins 18/19 -> CR J1 pads 8/7 -> CR -> W7 -> EVM J8 (I2C 0x6B)
   pad 13 TS_EXT       MB J-NTC -> CR J1 pad 13 -> CR -> W6 -> EVM J7 pin 1 (only with a pack NTC)
```

The diagram is schematic and not to scale. The mark ")" on the VBUS bar is a crossing with no connection: VCHG passes
VBUS without joining it. Only CR J1 pad 11 and the J-TAP conductors enter the permit gate. Table 2.2, section 8.6 and
design-document sections A.5 and C give the EIB-to-EVM leads and the EVM modifications.

### 2.2 Blocks

Table 2.1 lists each block, its role and its physical location.

Table 2.1. Blocks of the charger path.

| Block | Role | Physical location |
|---|---|---|
| MB RT1987 switches D-BC-FC, D-BC-RG | Route VBUS (FC charging) or V-MOT (regen) into VCHG-IN | MB, existing parts |
| MB D-BT-SQ (RT1987) | Connects the charger output net VCHG to the pack VBT | MB, existing part |
| CR J1 (22-pin CHG header) | Mates the CR to the 22 former Ag105 holes | CR underside, TSW strips in MB SSQ sockets |
| eFuse U101 TPS26630RGER | Input current limit 2.23 A nominal, UVLO 9.91 V, OVP 23.12 V; fault output and IMON | CR top |
| Permit gate | Four comparators and five LVC packages; holds the converter off unless a release term is true | CR top |
| J-TAP (J102) | Brings the ten tap conductors onto the CR | CR, THT header, +x side |
| EVM (BQ25798) | Buck-boost charger, I2C address 0x6B | Off-board, on an insulating plate fixed to the chassis |
| EIB | Converts CR logic levels into /CE, ILIM_HIZ hold/release and the FC current clamp at the EVM | 2-layer board on two M3 x 10 mm nylon standoffs on the EVM plate |
| Teensy 4.1 | Commands CHG_ARM, CHG_QUAL and the RT1987 enables; reads readbacks and I2C | MB, on J1/J2 receptacles |

Every block in Table 2.1 appears in Figure 2.1. Only the MB switches, the eFuse and the EVM carry charger power; the
other blocks carry logic.

### 2.3 Interfaces

Table 2.2 lists each interface, its connector and what crosses it.

Table 2.2. Interfaces of the charger path.

| Interface | Connector | What crosses it |
|---|---|---|
| MB to CR power and signals | MB SSQ-110/112-01-L-S sockets, CR TSW-110/112-07-L-S strips (CR J1) | Pad 10 VCHGIN; pads 18/19 VCHG; pads 4, 14, 15 GND; pad 11 CHG_ARM; pad 3 STAT; pads 8/7 SDA/SCL; pad 13 TS_EXT; 11 pads without a net |
| MB to CR taps | J-TAP (J102) Micro-Fit 3.0 2 x 5, cable Molex 2147581101 | T1, T7b, T2, T5, T6, T10, T13, T16, T17, T17r |
| CR to EVM input | W1 (VCHGOUT), W2 (GND); CR plated holes to EVM J1 screw terminal | Charger input, <= 2.41 A for <= 202 ms (eFuse limit), normally <= 1.76 A |
| EVM to CR output | W3 (VCHG), W4 (GND); EVM J5 screw terminal to CR plated holes | Charger output, <= 3.21 A |
| CR to EVM I2C | W7 twisted triple; CR plated holes to EVM J8 (Molex KK 254 housing) | SCL, SDA; GND bonded at the CR end only |
| CR to EVM thermistor | W6 twisted pair to EVM J7 pin 1 | TS_EXT; fitted only if a pack NTC is fitted at J-NTC |
| CR to EIB | W5 14-way 0.635 mm flat cable, CR J101 to EIB J201 | 3V3 (two conductors), CE_DRV, ILIM_REL_A, ILIM_REL_B, RFC_OFF to the EIB; STAT to the CR; four GND |
| EIB to EVM | E leads, 28 AWG Kynar | E8 AGND to TP49, E3 to TP33, E2 to JP14 pin 2, E7 STAT to TP38, E1 REGN to JP12, E5 /CE to TP36 |

Every interface in Table 2.2 appears in Figure 2.1. The power interfaces are CR J1 pads 4, 10, 14, 15, 18 and 19 and the
leads W1-W4. All logic crosses CR J1, J-TAP, W5, W6, W7 or the E leads.

## 3. What changed on 2026-11-12

The thermocouple and the polyimide sheet are removed, and no charging of any kind runs before the R5 build flag
(section 7.2). Sections 3.1 to 3.3 give the full change record.

### 3.1 Physical and functional changes

The 2026-11-12 decisions removed parts, moved signals and replaced the carrier outline. Table 3.1 lists every change that
a reviewer could otherwise miss. The decision identifiers refer to `LAYOUT_DECISIONS.md` (D-38 to D-50) and to the
design-document change rows r8-17 and r9-1 to r9-8.

Table 3.1. Changes of 2026-11-12.

| Area | Before (r8 or r7) | Now (r9) | Record |
|---|---|---|---|
| Thermocouple on the MB VBT trace | Fitted under the polyimide sheet, read in T-F-16 | **Removed.** No replacement. The MB VBT trace, at its IPC-2221 10 C rise at 3.21 A on 1 oz, is unmeasured until T-F-16 is retired or re-specified (J.2 items 45, 72(a)) | D-43 |
| Polyimide sheet over 368 untented MB vias | 0.125 mm sheet bonded under the CR | **Retired.** Protection is the >= 1.5 mm air gap and the solder-masked L4 GND | D-43 |
| CR outline | r7 outline with tab X, tab Y, chamfer and feet FT1/FT2 | **Plug-on rectangle** x 18.584-67, y 7-94 (48.416 x 87 mm), removable | D-39 |
| MB parts under the CR | None of the switching parts | Both boost switching nodes, L-FC, L-BT, REG-5V: about 1.6-3.3 W, BT boost TODO(calc) (Table 8.1) | D-39 |
| MB-CR mating | TSW pins soldered into the MB | Samtec SSQ sockets on the MB, TSW strips on the CR, hard stop at 11.05 mm | D-41 |
| Standoffs, feet, key | Feet FT1/FT2 bonded with RTV | **None.** Friction fit of 22 contacts; the terminal blocks stop a flipped CR; T-F-18 re-scoped to CR retention | D-41, D-42 |
| Assembly | SMT on both sides | **All SMT on the top**, one stencil, one reflow; THT hand-soldered last | D-44 |
| Copper weight | 2 oz outer / 1 oz inner | 1 oz outer / 0.5 oz inner (OSH Park); set on 2026-11-11, kept by the 2026-11-12 amendment | D-29 |
| L4 use | Signals, the VCHGOUT strap and a GND pour | Solid GND, no signals, no straps | D-20 |
| Finish method | Interactive finish from the r7 start board | Retired; full route-race on the new outline | D-36, D-50 |
| Tap conductors | 23 taps on SMT pads F01-F24 | **10 taps** on one Molex Micro-Fit 3.0 2 x 5 header J-TAP (J102) | D-46 |
| Permit gate logic | 11 LVC packages, two monostables | **5 LVC packages** (U105, U106, U107, U110, U118), no sequential element | D-47 |
| Comparators | Seven (incl. U104 BT_OK, U115 BTB_OFF, U121 RGN_ON) | **Four**: U102 H1, U103 UVB, U119 FCC_OFF, U120 FCC_ON | D-47 |
| QUAL timing | Hardware one-shot U111 (0.20-0.46 s) | Level input; firmware bound T_QUAL_MAX 0.46 s | D-47 |
| Hang defence | Heartbeat monostable U113 (ARM_OK) on pin 21 | **R5 watchdog only** (firmware); pin 21 freed | D-47, D2-2 |
| Pack OV | BQ29200 OUT tap T22 into a gate pack-OV input (OVN) | **Firmware only**: LIMIT_V_BATT_MAX 8.5 V, CHG_PACK_OV (FR-47(a)), OV_BATT | D-38 |
| Balance lead J-BL | Required to charge | Not required to charge | D-38 |
| CHG_QUAL | Teensy pin 10 (SPI CS0 default) | **Teensy pin 33**; pin 10 freed | D-48 |
| EIB far-end senses | U203 (ILIM_HIZ) and U204 (/CE) fitted | **DNP** with C203, C204, R258-R265; leads E4, E6 not built | D-49 |
| W5 ribbon conductors 11, 13 | ILIM_SENSE, CE_SENSE | **Not connected**; J101 stays 2 x 7; 9-10 and 8-9 shorts reach 33 mA (section 8.6) | D-49 |
| W6/W7 at the CR | SMT pads | Plated through-holes, soldered | D-45 |
| Chip sizes | Six 0402 parts | All chip passives 0603 or larger | D-44 |
| Teensy pin 7 readback (step PM10) | Planned (ROS removal) | Withdrawn; ROS stays fitted, pin 7 undriven | r9-4 |
| Keep-alive option (design-document B.5), U117 FC-current shed | DNP footprints | Withdrawn; no footprints. If T-F-04b fails, FC windows are restricted to standstill and coast (FR-14(e)). If T-B-09 fails, fallback 2 (fused VBT-VCHG link, PM8) or a later keep-alive redesign applies | r9-3 |
| Audit certification | Audit run 001 (L.8) | **Not certified** until audit run 002 (L.9) | r9-8 |
| Charging precondition | R5 needed for FC windows only | **No charging of any kind** before the R5 build flag (R5 firmware and T-W-01a) | D2-1 |

Most rows of Table 3.1 remove hardware and move its function into firmware or into a test. The plug-on outline is the
one change that adds new mechanical and thermal open items (sections 8.1 and 8.2).

### 3.2 Withdrawn and re-scoped tests, requirements and MB steps

Table 3.2 lists the tests, firmware requirements and MB steps that the 2026-11-12 decisions withdrew or re-scoped.

Table 3.2. Withdrawn or re-scoped tests, requirements and MB steps.

| Identifier | Status | Record |
|---|---|---|
| T-F-17, T-A-01c | Withdrawn | r8-17 |
| PM11 (BQ29200 OUT tap T22) | Deleted | r8-17 |
| T-B-03 | Withdrawn; its stray-shunt check and level criteria have no new home | r9-2 |
| T-C-05, T-C-07, T-C-13, T-C-16 | Re-scoped | r9-2 |
| PM7 (taps T18, T19) | Deleted | r9-3 |
| PM10, T-A-01b, T-E-02 | Withdrawn | r9-4 |
| T-A-09 | Withdrawn | r9-5 |
| T-F-16 | Open: retire or re-specify | r9-5 |
| T-F-18 | Re-scoped to CR vibration and contact retention | r9-5 |
| FR-08(a), FR-08(c) | Withdrawn; FR-08(b) replaced by an I2C latch trip | r9-7 |
| FR-09, FR-34, FR-35, FR-47(b), I-7, T-C-10, T-D-09 | Withdrawn | r9-7 |

Table 3.2 matters most for test-plan and firmware review. The design document marks each of these identifiers withdrawn
or re-scoped in its own row.

### 3.3 Unchanged context

The project still replaces the Silvertel Ag105 module (refdes CHG) on motherboard rev 20260622 with a TI BQ25798EVM.
Nothing has been ordered, desoldered or flashed. The bench board still runs fw v37 rev 2 with `AG105_VBATN_ISOLATED` 0,
so the bench performs no regen charging. No firmware file is edited in this round.

## 4. Design concepts, high level

### 4.1 The problem the charger path solves

The charger path must harvest regen energy from V-MOT and charge the pack from the fuel cell through VBUS. Operator
ruling R1 makes both functions hard requirements. Ruling R6 allows FC charging only in windows between H-20 purges, and
ruling R7 allows regen and FC charging to run concurrently. The Ag105 module cannot meet these requirements safely.
Ruling R2 therefore selects the BQ25798EVM as the power stage on the current board.

Ruling R5 requires an MCU hardware watchdog before any charger arming. This document calls that watchdog the R5
watchdog.

### 4.2 Hazards

The governing safety requirement is ruling R3': no circular charging loop VBUS -> charger -> pack -> BT boost -> VBUS,
and no runaway. The charger may stay powered through Run only with a fail-safe Teensy-commanded hard inhibit plus a
hardware comparator backstop. Table 4.1 lists the four hazards that follow from this requirement.

Table 4.1. Hazards.

| Hazard | Mechanism |
|---|---|
| Bus feeds the charger | With MOT_PWR closed, V-MOT sits at bus level, so an open REGEN path feeds the charger from VBUS |
| Back-feed into a disabled boost | A disabled TPS61288 passes current through its body diode; the only pack-to-VBUS element is D-BT-EN |
| Pack overvoltage | A corrupted charger voltage register or a failed charge stop overcharges the 2S pack |
| Hung MCU | A frozen Teensy holds the last commanded switch and gate levels |

The first two hazards concern energy flow between the rails. The last two concern the pack and the controller, and
section 4.3 shows that firmware carries most of their defence.

### 4.3 Defence layers

The design defends each hazard with up to four layers. The register layer is the BQ25798 register image (VINDPM,
IINDPM, ICHG, VREG). The firmware layer is the set of invariants and trips in design-document sections F.5 and G.2. The
hardware layer is the CR permit gate. The watchdog layer is the R5 watchdog, implemented in firmware.

Table 4.2 uses three gate signals that section 5 defines in detail. H1 is HIGH when V-MOT exceeds 1.089 x VBUS, UVB is
HIGH when the bus is healthy, and FCCP is the FC-window release term. The table also uses t_WDT, the R5 watchdog timeout
(50 ms target).

Table 4.2. Defence layers per hazard.

| Hazard | Register layer | Firmware layer | Hardware permit gate | Watchdog |
|---|---|---|---|---|
| Bus feeds the charger (regen-armed cruise) | VINDPM 18.62-19.38 V above the 16.39 V bus maximum | I2C latch trip (FR-08(b)); H1 plausibility check (FR-08(d)) | The regen comparator pair (H1 AND UVB) holds ILIM_HIZ until V-MOT exceeds 1.089 x VBUS | R5 resets within t_WDT |
| Loop in an FC window | VINDPM 14.5 V, IINDPM <= 0.90 A | FC_CHARGE and BT_BUS never HIGH together (invariant I-9), FAULT_SWITCH_CONFLICT, BT-current trip (FR-10) | None in r9; the FC-window release term (FCCP) only releases the converter | R5 |
| Back-feed into a disabled boost | None | Switch ordering rules; reset release order checked in T-W-01 | None | Reset drops every EN through 10 kOhm pull-downs |
| Pack overvoltage | VREG 8.320 V interim; VBAT_OVP follows VREG (not independent) | Register read-back (FR-46), slot-5 verify, CHG_PACK_OV (FR-47(a)), OV_BATT at 8.5 V | None since D-38 | R5 bounds a hang to about 51 ms |
| Hung MCU | BQ25798 watchdog 0.5 s (never cited as a barrier) | Watchdog feed token from the 1 kHz monitor tick (FR-28) | None since D-47 | **R5 is the only hang defence** |

The operator stance behind the r9 gate is "trust firmware except the regen H1 AND UVB check". The no-loop claim
therefore holds only as a register- and firmware-backed claim. In regen-armed cruise the hardware keeps one check, H1
AND UVB. In an FC window the loop barrier is firmware only.

The BQ25798 watchdog stays at 0.5 s with STOP_WD_CHG = 1, read back in every register verify (FR-03, ruling D2-4). Bench
test T-B-08 settles three SLUSDV2C conflicts, among them the VREG value after a watchdog expiry. The fallback setting is
WATCHDOG = 00.

## 5. The permit gate

### 5.1 Concept

The BQ25798 converts only when three conditions hold together. /CE must be LOW, EN_CHG must be 1, and the converter must
be released (ILIM_REL HIGH). The permit gate controls the first and the third condition. EIB Q201 holds ILIM_HIZ below
0.75 V (converter off, REGN on) unless ILIM_REL_B is HIGH, so a release needs two healthy switches. The gate has no
sequential element in r9.

### 5.2 Inputs

The gate has six inputs: four comparator outputs and two Teensy commands. Table 5.1 lists them.

Table 5.1. Permit gate inputs.

| Input | Source | Meaning when HIGH | Thresholds |
|---|---|---|---|
| H1 | U102 TLV3012B; T1 (V-MOT) against T2 (VBUS) | V-MOT > 1.089 x VBUS; the bus cannot feed V-MOT | Rise 17.31 V, fall 17.01 V at VBUS 15.9 V; hysteresis 0.30 V |
| UVB | U103 TLV3012B; T2 against its own reference | Bus healthy | VBUS > 13.33 V fall, 13.72 V rise |
| FCC_OFF (net name FCCN) | U119; T5 (D-BC-FC EN net) | D-BC-FC guaranteed off | EN < 0.39-0.44 V (below RT1987 VEN_F 0.6 V) |
| FCC_ON | U120; T5 | D-BC-FC commanded on | EN > 1.75-1.88 V (above RT1987 VEN_R 1.4 V) |
| P5 | CHG_ARM, Teensy pin 5 via CR J1 pad 11; R108 47.0 kOhm pull-down | Charging allowed | Logic level |
| QUAL | CHG_QUAL, Teensy pin 33 via T10; R123 47 kOhm pull-down | Run-entry qualification read requested | Logic level |

P5 and QUAL are the gate-variable names of the Teensy commands CHG_ARM and CHG_QUAL. FCC uses two comparators because the
RT1987 may turn on anywhere up to 1.4 V and is guaranteed off only below 0.6 V. An intermediate EN level, an open T5 or
a comparator in power-on reset reads FCC_OFF = FCC_ON = 0. That state releases nothing through the FC or qualification
terms. An open T5 sits at about 0.97-1.0 V and announces itself at Run entry.

### 5.3 Logic

The design-document section B.1 defines the gate in three equations:

```text
ILIM_REL = (H1 AND UVB) OR (FCC_ON AND NOT FCC_OFF) OR (QUAL AND FCC_OFF AND NOT P5)
CE_DRV   = P5 (buffered), so /CE = NOT P5
RFC_OFF  = FCC_OFF OR (H1 AND UVB)
```

The first release term (H1U) is the regen release. The second term (FCCP) is the FC-window release; it needs both
comparators to agree, so a stuck-HIGH U120 alone does not release the converter. The third term (QF) releases the
converter for the Run-entry ADC read only while /CE is HIGH and FC charging is proven off.

RFC_OFF is HIGH whenever FC charging is proven off (FCC_OFF) or the regen release is active (H1 AND UVB). A HIGH
RFC_OFF removes the FC current clamp (0.65-0.95 A) at the EVM ILIM pin. The clamp therefore acts only in an FC window with no regen
release.

At Teensy reset or boot, the pull-downs give P5 LOW and QUAL LOW, and the buffer drives CE_DRV LOW, so /CE is HIGH. The
RT1987 EN pull-downs keep the charger unpowered. During comparator power-on reset (<= 1.9 ms) all four comparator outputs
are LOW, so no release term is true. Design-document section B.1 gives the full truth table, and section 8.4 maps the
terms onto packages.

### 5.4 Accepted latent faults

The operator accepted several single faults that no hardware detects in service. Table 5.2 lists them.

Table 5.2. Accepted latent faults of the r9 gate.

| J.1 item | Fault | Consequence | Remaining barrier |
|---|---|---|---|
| 18 | Stuck-HIGH output of U118A, U118B, U110A or U110B, or ILIM_REL shorted to 3V3 | Converter released in regen-armed cruise with /CE LOW | VINDPM 18.62-19.38 V only |
| 19 | QUAL stuck HIGH (pin 33 or T10) | Converter released whenever P5 and FCC are LOW | /CE HIGH and EN_CHG = 0 |
| 13 | /CE stuck LOW (U201 1Y, or R272 and R272b both open) | Charging whenever released; CHG_PACK_OV inhibit (FR-47(a)) lost | I2C latch trip while released (FR-08(b)); OV_BATT |
| 20 | QUAL stuck HIGH plus /CE stuck LOW | Full R3' loop | FR-08(b) with a live MCU; R5 under a hang |
| 21 | T5 node driven HIGH (short to T6, or pin 31 stuck HIGH) | FC_CHARGE may be on with BT_BUS HIGH | VINDPM only; J-TAP pin order |
| 22-24 | RFC_OFF blind to REGEN; no hardware loop barrier in an FC window; no arrival check at the EVM | See design document | Firmware |
| 15 | Open tap T13 (pin 34) | Pin 34 reads "no brake", so F.5-T3 never fires and harvest above the FC image is lost; safe direction | The hardware H1 on the CR |
| 16 | Open tap T16 (pin 35) | Pin 35 reads "no fault"; an eFuse trip is seen only as a V_chg collapse | None dedicated |

Most entries in Table 5.2 leave a register or firmware barrier only. UVB stuck HIGH is also latent, with no readback;
its acceptance against a readback on a freed pin is undecided. Section 8.4 gives the build tests that cover these faults.
In service, the J-TAP pin order is the only hardware mitigation: T5, T6 and T10 occupy pairwise non-adjacent cavities.

## 6. Operating modes and protections

### 6.1 Switch states per mode

Table 6.1 gives the switch state of each main mode. A full vector lists eight switches in the order FC_REG, BT_REG,
FC_BUS, BT_BUS, MOT_PWR, REGEN, FC_CHARGE, BT_SEQ. Rows without a full vector list only the switches and commands that
change. The mode names follow design-document section F.2.

Table 6.1. Modes, switch states and stop conditions.

| Mode | Switch state | What releases the converter | What stops it |
|---|---|---|---|
| Init (State 0) | Staged bring-up through several vectors; REGEN 0, FC_CHARGE 0 | Nothing; the charger has no input power | Not applicable |
| Idle (State 1) | 1 1 1 1 1 0 0 1; P5 0, QUAL 0 | Nothing; the charger has no input power | Not applicable |
| Run entry qualification (F.5-T1) | 1 1 1 1 1 1 0 1; P5 0 | QF (QUAL HIGH, raised only on PG_STAT = 1) | Firmware drops QUAL; T_QUAL_MAX 0.46 s backstop latches CHG_QUAL_OVERRUN |
| Regen-armed cruise | 1 1 1 1 1 1 0 1; P5 1 | Nothing; H1U = 0 holds ILIM_HIZ | Not applicable |
| Regen burst | As regen-armed cruise | H1U = 1 while V-MOT > 1.089 x VBUS | H1 falls; VINDPM 19.0 V; IINDPM 1.70 A; clamp 1.33-1.76 A |
| FC window (R6/R7) | 1 1 1 0 1 1 1 1; P5 1 | FCCP (FCC_ON agreeing with NOT FCC_OFF) | Closes at t_pred - T_LEAD before each purge; FR-42 backstop; IINDPM 0.90 A; raw I_fc > 1.20 A arm drop; OC_FC 1.4 A |
| Charger trip in a window (F.5-T10) | P5, QUAL, FC_CHARGE and REGEN LOW on the same tick | None | BT_BUS closes only after a no-conversion proof, else controlled State 99 |
| State 98 J | Stage 1: as F.5-T1. Stage 2: BT_BUS 0, FC_BUS 1, REGEN 1, FC_CHARGE 1 | Stage 1: QF. Stage 2: FCCP | G1-G3 guards (re-key open); reboot-only trip latch |
| State 99 (F.5-T7) | Phased teardown | None | Phase 0 drives P5 and QUAL LOW before any switch moves |
| Teensy reset | All EN LOW through 10 kOhm pull-downs | None | Not applicable |

In Table 6.1, t_pred is the predicted purge time and T_LEAD is the 100 ms purge lead time. Outside State 98, only three
modes can release the converter: qualification, a regen burst and an FC window.

### 6.2 Qualification and arming order

QUAL rises only with P5 LOW, and only after EN_CHG = 0 and REG11 = 0 are written and read back. On every P5 path, QUAL
is driven LOW and held LOW for at least one 1 kHz tick before P5 rises (invariant I-5). During qualification the bus
feeds the charger quiescent current, about 50-90 mW, for at most 0.46 s per Run entry. J.1 item 14 records this draw as
an explicit R3' exception.

### 6.3 FC windows

An FC window is admitted only with all of these conditions:

- charge_goal > 0.05;
- the chgFull latch (set when the charger reports charge done) clear;
- the purge schedule locked;
- no trip latch;
- the R5 build flag and the full-T-W-01 build flag set (section 7.2).

The FC image sets VINDPM 14.5 V, IINDPM = min(0.90 A, G) and ICHG 1.60 A. G is the traction-current governor limit of
design-document section F.4; it subtracts a 2 s peak-hold of traction current. BT_BUS stays LOW for the whole window,
which by itself removes the only pack-to-VBUS element. During a brake in a window, V-MOT > VBUS reverse-biases D-BC-FC,
so the charger draws only from the motor.

### 6.4 Hang behaviour

Under a hang the gate follows the frozen P5, QUAL and FCC levels. Charging continues as last commanded for at most
t_WDT + 1 ms, about 51 ms at the 50 ms target. The watchdog reset then drops P5, QUAL and every EN through the
pull-downs. This bound assumes that the i.MX RT1062 pad keeper does not hold pins 5 and 33 HIGH against the 47 kOhm
pull-downs. Keeper strength is TODO(verify: IMXRT1060RM). A hang inside an FC window can still meet one purge with a
frozen MCU, in about 1.5 % of window hangs. Only the bench characterises this case (T-D-14).

## 7. Firmware requirements this hardware creates

### 7.1 Scope

The firmware is not changed in this round. Every item below is a requirement for the future BQ25798 firmware round,
which follows the PCB design. The R5 watchdog firmware is built in that same round.

### 7.2 Preconditions for charging

The firmware records two build flags. The R5 build flag states that the R5 watchdog firmware exists and T-W-01a (forced
hangs without a purge) has passed. The full-T-W-01 build flag states that the full T-W-01, with the T-D-14
purge-emulator cases, has passed.

No charging of any kind (regen, qualification or FC windows), attended or not, runs before the R5 build flag is set. FC
windows additionally need the full-T-W-01 build flag. Run with the charger disarmed needs neither flag.

The EVM must not be connected until the IO CSV is amended and firmware with the new pin map is flashed. The reason is
that fw v37 State 98 key '4' toggles pin 5 directly.

### 7.3 Pin map

Table 7.1 lists the Teensy pins that the charger path uses or frees in r9.

Table 7.1. Teensy pins of the charger path.

| Pin | Code name | Direction and mode | Route |
|---|---|---|---|
| 5 | CHG_ARM (was MPPT_DISABLE) | OUTPUT, LOW early in setup(); HIGH = charging allowed | CR J1 pad 11 |
| 6 | CHARGER_STAT | INPUT; polarity inverted vs Ag105 (LOW = charging) | CR J1 pad 3 |
| 18, 19 | SDA, SCL | I2C 400 kHz (100 kHz fallback), MB pull-ups 2.7 kOhm | CR J1 pads 8, 7 |
| 20 | WDOG1_B_RSVD | Unconfigured until R5; no CR consumer | None |
| 22 | CHG_IIN | INPUT_DISABLE, analog, 0.764 V/A | T17 |
| 31 | FC_CHARGE_ENABLE | OUTPUT, never INPUT_PULLUP | T5 taps the EN net |
| 33 | CHG_QUAL | OUTPUT, LOW early in setup(); no peripheral may claim it | T10 |
| 34 | CHG_H1_RB | INPUT_PULLDOWN, GPIO only (never WDOG1_B) | T13 |
| 35 | CHG_EFUSE_FLT | INPUT_PULLUP (the only pull-up) | T16 |
| 38 | CHG_VOLTAGE | Analog, VCHG-IN through R1-CHG | MB |
| 10, 16, 17, 21, 23 | Freed | INPUT_PULLDOWN, boot read, UNEXPECTED_LEAD on HIGH | None |

Pins 5 and 33 are the only charger commands, and both default LOW. Every other charger pin in Table 7.1 is an input or
an analog channel.

### 7.4 Principal requirements

The design document defines the requirements as FR-01 to FR-49 and invariants I-1 to I-9. Table 7.2 lists the items
that carry the r9 safety argument.

Table 7.2. Principal firmware requirements.

| Requirement | Content |
|---|---|
| R5 watchdog | RTWDOG 50 ms while rtwdogShort is TRUE (State 2, or any of P5, QUAL, FC_CHARGE, REGEN HIGH); WDOG1 1.0 s second stage; fed only by the FR-28 token in the 1 kHz monitor tick |
| T_QUAL_MAX backstop | An independent 1 kHz check drops QUAL, P5 and REGEN after 0.46 s of QUAL HIGH (FR-04, FR-45) |
| Invariant I-9 | FC_CHARGE and BT_BUS are never HIGH together; both setters refuse |
| FR-13 | FC_CHARGE + REGEN becomes legal; FC_CHARGE + BT_BUS stays a latched conflict |
| FR-49 | Outside State 98, the FC_CHARGE setter refuses HIGH while REGEN is LOW; RT1987 EN pads are checked at boot and before every Run entry |
| FR-07 | The pin-34 interrupt acts on both edges; the falling edge posts the F.5-T4 image restore at the queue head and re-reads H1 at service time |
| F.5-T3 gate | The raise of the charger image on a brake in an FC window requires REGEN read back HIGH |
| FR-08(b) | With P5 LOW for >= 20 ms, a charging status or IBAT > 50 mA on two fresh reads latches a trip |
| FR-47(a) CHG_PACK_OV | BT_VOLTAGE (pin 25) above 8.5 V on one sample drops P5 first; not yet implemented, so only OV_BATT acts today |
| FR-11 | CHG_IIN must agree with the I2C IBUS ADC; a sustained disagreement latches CHG_IIN_LEAD |
| F.5-T10 proof (d) | The no-conversion proof (d) is used only after CHG_IIN and IBUS agree in the same charger power cycle (lead-alive rule); otherwise F.5-T10 falls back to proof (b) |
| FR-18 | State 98 J becomes two stages: register commissioning, then a supervised FC-window charge |
| FR-20 | Telemetry protocol v5, bumped in lockstep with the Pi bridge |
| FR-02 | The Ag105 driver is removed; `AG105_VBATN_ISOLATED` is renamed `CHG_RETURN_VERIFIED` |

The lead-alive rule in Table 7.2 has a known gap. An open T17, or a T17r-T17 short, can make proof (d) pass falsely;
the lead-alive agreement is the only guard against this case.

### 7.5 IO CSV amendments

The operator edits the IO CSV personally; design-document section D.3 only proposes text. The amendments replace rows 5,
6 and 31 and amend the notes of rows 27-30 and 32. They also add rows 19 (note), 20, 21, 22, 33, 34 and 35. The row-30 note
figure of about 0.95 V rests on the removed R133 and needs a re-run before use. The row-31 note "REGEN_ENABLE MAY stay
on" may conflict with FR-49.

## 8. Physical implementation

### 8.1 CR outline and mating

The CR is a removable plug-on rectangle at x 18.584-67, y 7-94 in the MB frame (Eagle board coordinates, +y up). It has
no tab, chamfer, concave corner or mounting hole. Samtec SSQ-110-01-L-S (pins 1-10, x 45.998 column) and SSQ-112-01-L-S
(pins 11-22, x 20.998 column) sockets are soldered into the 22 MB CHG holes. TSW-110-07-L-S and TSW-112-07-L-S strips
sit with their bodies on the CR underside. All 22 positions are populated.

The stack has a hard stop where each TSW body seats on its SSQ face. The CR underside is then 11.05 mm above the MB top,
and the CR top is at 12.65 mm. TSW in SSQ is rated 6.3 A per pin with two positions powered. The design powers four
positions (pins 14/15/18/19, 1.93 A each); that derating is TODO(verify: Samtec derating curve). The SSQ is rated for 100
mating cycles.

The CR has no key and no standoffs. A CR rotated 180 degrees lands on J-BL, J-FC and J-BT (21.70 mm) before its pins
engage at 16.89 mm. The engagement-start height must therefore stay below 21.70 mm.

Only the friction of the 22 contacts holds the CR. The total withdrawal force is about 31 N, taken from an older SSQ
sheet revision, TODO(verify: current Samtec SSQ spec). Test T-F-18 is re-scoped to CR vibration and contact retention;
its retention criterion is TODO(calc: generator step). A 3-D printed support is the operator's later fallback.

The mating stack is assembled in this order (PM4):

1. Clear the 22 MB CHG holes.
2. Solder the SSQ sockets to the MB, bodies flat and square.
3. Plug the TSW strips into the sockets.
4. Set the reflowed CR on the TSW bodies.
5. Solder the TSW tails from the CR top while the CR is plugged in.
6. Unplug the CR and inspect it.

An air gap of >= 1.5 mm separates the lowest CR feature, THT tails included, from the tallest MB part below it. The
air-gap basis counts the CR bow only, not the MB bow or the connector seating tolerance (J.2 item 72(d)). With the
polyimide sheet retired, the 368 untented MB vias face only the solder-masked L4 GND across this gap.

The outline covers 67 MB parts. Both boost switching nodes, the inductors L-FC and L-BT, the regulators REG-5V, REG-FC
and REG-BT and their heat now lie under the CR. Table 8.1 gives the heat estimates of the outline re-assessment.

Table 8.1. MB heat sources under the CR.

| Source | Dissipation | Basis |
|---|---|---|
| REG-5V (LM1084) | 0.40 / 0.63 / 1.08 W | Re-assessment Table 2 |
| FC boost (REG-FC, L-FC) | 1.17-2.20 W at 14.6 W input, efficiency 0.92-0.85 | Efficiency 0.85 is a model value, TODO(verify: TPS61288 Fig 7-3) |
| BT boost (REG-BT, L-BT) | Not derived | TODO(calc: BT channel operating point) |

The known sources in Table 8.1 total about 1.6-3.3 W, and the BT boost adds an unknown amount. Section 8.2 gives the
placement rules that respond to these sources.

### 8.2 Stack-up, fab and placement rules

The CR is a 4-layer, 1.6 mm OSH Park board. Table 8.2 lists the layer use.

Table 8.2. CR stack-up.

| Layer | Copper | Use |
|---|---|---|
| L1 (F.Cu) | 1 oz | Signals, power pours, all SMT parts |
| L2 | 0.5 oz | Solid GND over the whole outline |
| L3 | 0.5 oz | Signals; VCHGOUT strap only if needed |
| L4 (B.Cu) | 1 oz | Solid GND facing the MB; no signals, no straps; stitched to L2 at <= 5 mm; masked, every via tented |

The two GND layers in Table 8.2 enclose L3, and L4 faces the MB switching nodes below the CR.

The CR uses an OSH Park-only rule file with a 0.127 mm minimum track and space and a 0.1524 mm router default. The only
via size is 0.6/0.3 mm. Unused inner pads are removed on every THT pad (D-29, D-30). Filled and capped vias are not
available. A via in an SMD pad is a last resort after a route without one fails. Each such via is listed for operator
review (D-37). The U101 exposed pad carries >= 9 thermal vias with window-pane stencil apertures; these vias are
exempt from D-37.

The divider-top rule of D-36 binds on all layers as an optimisation metric, not a gate. The metric is the length of
logic-net copper that runs parallel to analog-net copper inside the 2.0 mm zone; a lower value is better. Exemptions are
acceptable where no other route exists, and the D-35 exemptions are approved.

Two placement rules respond to the heat and switching sources of section 8.1. THT tails stay outside the shadows of
L-FC, L-BT and REG-5V plus 1 mm. The 0.1 % dividers, the comparator inputs and the references preferably sit in the
window y 30.8 to 66.86.

### 8.3 Parts and assembly

Every SMT part sits on the CR top and is assembled with one stencil in one reflow pass; THT parts are hand-soldered last.
Every chip passive is 0603 or larger. IC pitch is 0.65 mm minimum, with U101 TPS26630RGER (0.5 mm VQFN-24) as the one
approved exception. Single-gate logic uses SOT-23 (DBV); U107 is SN74LVC1G11DBVR. Reference designators are printed on
the top silkscreen. Courtyards follow the IPC-7351 nominal 0.25 mm rule, which is not yet applied in the footprint
library.

### 8.4 Permit gate implementation

Table 8.3 maps each gate term of section 5.3 onto the five LVC packages.

Table 8.3. Gate term to package mapping.

| Term | Function | Package and section |
|---|---|---|
| FCCNN | NOT FCC_OFF | U105 SN74LVC3G04DCTR, section 1 |
| P5N | NOT P5 | U105, section 2 |
| (spare) | 3A tied to GND | U105, section 3 (the only spare) |
| CE_DRV | P5 OR GND (buffer) -> R130 -> J101.5 | U106 SN74LVC2G32DCTR, section A |
| RFC_OFF | FCC_OFF OR H1U -> R132 -> J101.10 | U106, section B |
| QF | QUAL AND FCC_OFF AND P5N | U107 SN74LVC1G11DBVR |
| GATE | H1U OR FCCP | U110 SN74LVC2G32DCTR, section A |
| ILIM_REL | GATE OR QF -> R131A/R131B -> J101.7/.8 | U110, section B |
| H1U | H1 AND UVB | U118 SN74LVC2G08DCTR, section A |
| FCCP | FCC_ON AND FCCNN | U118, section B |

Table 8.3 leaves one spare section, U105 section 3. The CE_DRV buffer is U106A.

Two tests cover the latent faults of Table 5.2 at every build. T-C-01 drives the six gate inputs through all 64 states.
It compares every output at J101 with the B.1 equations, then repeats with pin 5 high-Z. T-C-05 forces ILIM_REL HIGH at
R131A/R131B and checks the release at the EVM pin. It also meters R272 and R272b against 47.0 kOhm.

### 8.5 J-TAP and leads

J-TAP (J102) is a Molex Micro-Fit 3.0 dual-row 2 x 5 THT header at 3.00 mm pitch on the +x side of the CR. It mates
with the Molex 2147581101 cable assembly. Table 8.4 gives the cavity map.

Table 8.4. J-TAP cavity map (columns 1-5).

| Row | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| A | T1 (V-MOT) | T7b (GND shield) | T17r (GND shield) | T5 (FCC tap) | T13 (CHG_H1_RB) |
| B | T6 (3V3) | T2 (VBUS) | T17 (CHG_IIN) | T16 (CHG_EFUSE_FLT) | T10 (CHG_QUAL) |

In Table 8.4, T5 (A4) sits diagonal to T10 (B5), which meets the non-adjacency rule but not the recommended diagonal
separation. Housing polarization is required, because a 180-degree flip puts T6 on the T10 circuit.

At the far end, T5, T6, T10, T13, T16 and T17 use the operator's 0.100 in crimps. Each crimp sits in the second
position of its MB J1/J2 pair. T1 and T2 are soldered to R170 and R171 (10.0 kOhm 0.1 %) at C-D6 and C-D2; T7b and T17r are cut back and
insulated. T6 is the only source of the CR and EIB logic rail, through R175 68 ohm. J-TAP is unplugged, with all
supplies off, before the CR is lifted (PM6).

Every W lead is a soldered through-hole joint on the CR, and no W-lead connector is fitted on the CR. Table 8.5 lists
the leads and where each unplugs when the CR is removed.

Table 8.5. W leads.

| Lead | Conductor | Far end | Disconnects at |
|---|---|---|---|
| W1, W2 | 20 AWG twisted pair, fixed 0.30 m +- 10 mm | EVM J1 pins 2 (VIN1), 1 (GND) | EVM J1 screw terminal |
| W3, W4 | 18 AWG twisted pair | EVM J5 pins 1 (BATTERY), 3 (GND) | EVM J5 screw terminal |
| W5 | 14-way flat cable, Samtec FFSD-07-D-12.00-01-N | EIB J201 | IDC sockets at both ends |
| W6 | 26 AWG twisted pair (only with a pack NTC) | EVM J7 pin 1 | EVM J7 |
| W7 | 28 AWG twisted triple | EVM J8 pins 2, 3 | Molex KK 254 housing |

Every lead in Table 8.5 disconnects at the EVM or EIB end, so the CR lifts off without desoldering.

### 8.6 EIB and EVM

The EIB is a 2-layer, 24.0 x 38.0 mm board as fabricated, on two M3 x 10 mm nylon standoffs on the EVM plate. U201
channel 1 drives /CE from CE_DRV. Channel 2 drives the Q203 release feed from ILIM_REL_A, and U202 drives the Q201
ILIM_HIZ hold from ILIM_REL_B. Channel 3 drives the Q202 FC current clamp leg from RFC_OFF. The EIB ground reaches the
EVM only through E8 at TP49 and the CR only through R273 10 ohm.

The EIB DNP set is U203, U204, C203, C204 and R258-R265; leads E4 and E6 are not built, and the copper is unchanged.
On the CR, J101 stays 2 x 7 with ribbon conductors 11 and 13 not connected.

A short between J101 pin 9 (GND) and pin 10 (RFC_OFF) drives up to 33 mA through R132 100 ohm (J.2 item 70(a)). This
current exceeds the LVC recommended output current. A short between pins 8 and 9 does likewise for ILIM_REL_B. R175
limits the current and sags the CR rail; design-document section B.6 had called these pairs safe, TODO(calc).

The EVM carries R256 200 kOhm and C252 2.2 nF across JP21, and R272/R272b 47.0 kOhm as redundant /CE pull-ups. The EVM
rests on its stock bumpons on an insulating plate, held by edge clamps with silicone pads and not drilled.
Design-document section C (EM1-EM23) lists the EVM modifications.

### 8.7 Grounding

The design uses single-point bonding. The CR GND plane bonds to MB GND only at CR J1 pads 4, 14 and 15 through the mated
contacts. The EVM power ground reaches the CR through W2 and W4. The only other DC path, E8 -> EIB -> R273 10 ohm -> W5
GND, carries less than about 2 mA (design-document A.6). The W6 and W7 shields are bonded at the CR end only. The pack
negative is PCB ground by design.

### 8.8 MB modifications

The MB keeps every trace (PM8: no trace cuts) and keeps ROS fitted. Steps PM7, PM10 and PM11 are deleted or withdrawn
(Table 3.2). The remaining modifications are:

- PM1: remove the Ag105 (CHG).
- PM2: replace C-D8 and C-D10 with 10 uF >= 35 V 0805.
- PM3: fit R170 and R171 at C-D6 and C-D2 for T1 and T2.
- PM4: fit the SSQ sockets and mate the CR.
- PM6: build the J-TAP harness.
- PM9: change RSDA and RSCL to 2.7 kOhm.

## 9. Current status

### 9.1 Netlist and board files

The CR netlist `cr/cr.net` is regenerated from `gen/netlist.py` with 78 parts (145 in r8) and passes ERC with 0 errors
and 0 warnings. It is frozen only after the audit-run-002 adjudication. The netlist export reports annotation errors for
the six letter-suffix designators C102a, C102b, C102c, R106s, R131A and R131B; these references are accepted. The
footprints still use the 0.10 mm courtyards. The board file `cr/cr.kicad_pcb` is the stale r7-outline build and is not an
input to the next build. No generator or board file exists on the plug-on outline yet.

### 9.2 BOM

The ordering BOM `bom_2026-11-11/ordering_bom.csv` holds 99 part rows. It counts 98 PCB components (72 fitted CR parts
and 26 fitted EIB parts) and 51 unique parts. The BOM includes two BQ25798EVM units, five CR boards and five EIB boards.

The r9 edit added rows for the SSQ sockets, the J-TAP header and cable and the stencil and solder paste. It deleted the
feet, RTV bed, bond coupon, polyimide and thermocouple rows (BOM README section 8.2). The B1R wedge, post and off-CR
support rows stay stale until the A.3 lead route is re-derived on the new outline. BOM README section 7 item 26 lists
them.
Nothing is ordered, and no price, stock or SKU is verified on a live vendor page.

### 9.3 EIB fab package

The EIB package `fab/eib_2026-11-11/` passes ERC and DRC and is not ordered; it awaits operator review. The DNP set is
applied by hand to the BOM and position CSV files. `assembly/eib_ibom.html` and the schematic and PCB PDFs still show the
DNP parts as fitted. A re-run of `gen/export.sh eib` or `gen/fab_readme.py` would overwrite the hand edits.

### 9.4 Archive and certification

The r7-outline layout work (interactive project, variants, attempts, routability study) is archived in
`archive_r7_outline/` as reference only. Audit run 001 (L.8) no longer certifies the design, because the 2026-11-12
decisions removed parts on which its dispositions rest. Certification waits for audit run 002 (L.9).

## 10. Implementation plan in steps

### 10.1 Round order

The round order is D-50, in eight steps with four operator check-ins. Step 1 is done and awaits check-in 1, so seven
steps remain. Table 10.1 lists each step with its inputs, outputs and blocking items.

Table 10.1. Round order (D-50).

| Step | Inputs | Outputs | Blocking open items |
|---|---|---|---|
| 1. Apply decisions to the design document and CR netlist (done) | 2026-11-12 decision records | Design document r9, `cr/cr.net` (78 parts), BOM, LAYOUT_DECISIONS D-38 to D-50 | **Check-in 1**: diff review; section 11 items 1, 2, 4 and 5 |
| 2. Strip removed parts from `round3/calc/r3_calc.py` and `round4/calc/r7_calc.py`, re-run | r9 netlist | Re-derived H.4, H.19, H.20, H.22 and every changed row; r7 H.23 rows retired | Ribbon 9-10 and 8-9 short current against the LVC limit (section 8.6) |
| 3. Audit run 002 (hybrid adversarial review and self-review) | Step-2 numbers; Table L.9-1 | L.9 adjudication | Table L.9-1 finalisation; **check-in 2** (fix approval, then netlist freeze) |
| 4. New-outline generator (parallel with step 3) | `outline_change_2026-11-12/retired.md` section 4 | Region table, side flags, TSW/J-TAP/W-pad footprints, 0.25 mm courtyards, new constraint rows, H.23 successor, regenerated EIB exports | Molex pinout, TSW pad and drill, W6/W7 hole sizes, change-request section 6 survey |
| 5. Placement on the frozen netlist, all SMT on the top | Frozen netlist, generator | Placed board | Area booking; MB heights for the air gap; **check-in 3** (placement images) |
| 6. Full route-race | Placed board, power geometry | Routed board and one batch of change requests | Via-in-pad fallbacks listed for review |
| 7. DRC and constraint check | Routed board | Clean DRC and constraint reports | Not applicable |
| 8. Fab package (`gen/export.sh`, `gen/fab_readme.py`) | Checked board | CR fab package | **Check-in 4** (before the fab package and any order); fab quotes; BOM verification (T-A-05) |

Steps 2 to 4 of Table 10.1 can start without new hardware. Placement waits for the frozen netlist and for the MB height
survey.

### 10.2 After the PCB round

The firmware round follows the PCB design and builds the BQ25798 driver, the R5 watchdog and the section 7 requirements.
T-W-01a then gates any charging, and the full T-W-01 gates FC windows.

## 11. Open items for the operator

The following decisions belong to the operator. Each item names its record.

1. Review the step-1 diff summary at check-in 1 (HANDOFF section 3).
2. Confirm the J-TAP map with T5 (A4) diagonal to T10 (B5). The non-adjacency rule is met; the recommended diagonal
   separation is not (D-46, J.2 item 63).
3. Retire T-F-16 or re-specify its method, now that the thermocouple is removed (D-43, J.2 item 72).
4. Complete the change-request section 6 survey (D-39, survey item MS3). It covers the L-FC/L-BT heights (5.0 mm
   listing vs 6.5 mm sibling), the bodge-part heights and the J-BT and J-BL face positions. It also checks whether
   C1-BT, C1-FC, CBL2, RB2 and RB3 clear x 18.584.
5. Review the EIB fab package before any order (D-49).
6. Decide whether UVB stuck HIGH stays latent or gets a readback on a freed pin (F.3, audit item).
7. Rule on the W1/W2 wire: Alpha 3053 stranding 10/30 against the specified 19/32 or 7/28 (BOM README section 7 item 11).
8. Find a home for the stray-shunt check and level criteria of the withdrawn T-B-03 (design document I, T-B-03; J.2
   item 70(c)).
9. Decide whether the L.4 dispositions hang-fc-window-r5-gates-r1 and fr12-idle-selftests-need-motpwr-btbus-low enter
   Table L.9-1, and whether outline-only dispositions retire or are re-audited.
10. Confirm E8 (115 mm) in the fallback (iii) lead re-check, only if survey item MS2 (EVM placement) forces a corridor
    fallback (J.2 item 70(b)).
11. Edit the IO CSV (D.3, D-48). The edits are CHG_QUAL on pin 33, pin 10 freed, the row-21 code name, rows for pins
    10, 16, 17 and 23, and the row-31 note against FR-49.
12. Decide whether to adopt CHG_IIN plausibility against the expected gate state as a firmware check (partial cover of
    J.1 item 18).
13. Decide whether FR-47(a) also writes EN_CHG = 0 on the P5 drop and verifies that the charge current falls (dec2-gate
    suggestion, round-2 digest).
14. Decide the tolerance and action of a pin-25 plausibility check against the BQ25798 VBAT ADC (J.2 item 39).

## 12. Where the detail lives

Table 12.1 maps each topic to the authoritative file and section. Paths are relative to the repository root unless they
begin with a folder of `hardware/charger_evm_r8/`.

Table 12.1. Topic index.

| Topic | File | Section |
|---|---|---|
| Operator rulings R1-R9, revision log r9-1 to r9-8 | `docs/charger_bq25798_wiring_design_2026-11-05.md` | 0.1, 0.2 |
| Assemblies, CHG pin map, leads, taps | Design document | A.1-A.4 |
| EIB leads, grounding, CR outline and mating, copper and placement rules | Design document | A.5-A.8 |
| Permit gate equations, truth table, comparators, logic, eFuse, EIB, reset states, pin-level netlist | Design document | B.1-B.4, B.6-B.8 |
| EVM modifications EM1-EM23 | Design document | C |
| MB modifications, Teensy pins, IO CSV proposals | Design document | D.1-D.3 |
| Modes, single faults, FC windows, invariants and transitions | Design document | F.1-F.5 |
| Register image, firmware requirements FR-01 to FR-49, MCU watchdog | Design document | G.1-G.3 |
| Calculations | Design document; `round3/calc/r3_calc.py`, `round4/calc/r7_calc.py` | H |
| Tests (T-A to T-W) | Design document | I |
| Accepted residuals and open items | Design document | J.1, J.2 |
| Audit runs | Design document | L.8 (no longer certifying), L.9 (pending) |
| Layout decisions D-01 to D-50 | `LAYOUT_DECISIONS.md` | D-38 to D-50 for 2026-11-12 |
| Current state and next steps | `HANDOFF.md` | 1-3 |
| Pre-round-2 state record | `DESIGN_STATE_2026-11-12.md` | Superseded where round 2 differs |
| First-round decision records | `decisions_2026-11-12/` | One file per decision |
| Second-round decision records | `decisions_2026-11-12/round2/` | `orchestrator_digest.md` |
| Outline change rationale | `OUTLINE_CHANGE_REASSESSMENT_2026-11-12.md` | 2, 3, 8 |
| Ordering BOM | `bom_2026-11-11/ordering_bom.csv`, `README.md` | 8.2-8.3 for r9 changes |
| CR netlist and generator | `cr/cr.net`, `gen/netlist.py` | Not applicable |
| EIB fab package | `fab/eib_2026-11-11/README.md` | 1, 5 |
| Stale r7-outline work | `archive_r7_outline/` | Reference only |

Table 12.1 points to the design document for every technical value in this README. The other files hold decision
records, status and the BOM.

## Appendix A. Abbreviations and identifiers

### A.1 Abbreviations

Table A.1 defines the abbreviations that this document uses.

Table A.1. Abbreviations.

| Abbreviation | Meaning |
|---|---|
| MB | Motherboard rev 20260622 with the Ag105 charger module (refdes CHG) removed |
| CR | CHG adapter carrier, a new 4-layer board plugged onto the MB |
| EVM | TI BQ25798EVM (BMS034A/B-003, user guide SLUUCB5E), used as the charger power stage |
| EIB | EVM interface board, a 2-layer board beside the EVM |
| FC, BT | Fuel cell (Horizon H-20) and battery (2S pack, net VBT) |
| VBUS | 16.0 V boost output bus |
| V-MOT | VESC/motor node; VESC is the motor controller |
| MCU | Microcontroller, here the Teensy 4.1 (i.MX RT1062) |
| SMT, THT | Surface-mount and through-hole technology |
| DNP | Do not populate: the footprint exists, the part is not fitted |
| LVC | TI SN74LVC single- and dual-gate logic family |
| NTC | Negative-temperature-coefficient thermistor |
| ERC, DRC | Electrical and design rule check |
| BOM | Bill of materials |
| IO CSV | `references/Scale Car Teensy IO - IO.csv`, the authoritative Teensy pin map |
| REGN | BQ25798 internal gate-drive regulator output |
| VINDPM, IINDPM | BQ25798 input voltage and input current regulation limits |
| ICHG, VREG | BQ25798 charge current and charge voltage registers |
| PG_STAT, REG11 | BQ25798 power-good status bit; BQ25798 register 0x11 |
| TP, JP | EVM test point and jumper position |
| ROS | MB resistor in the Teensy pin-7 net |

### A.2 Identifiers from the design document

Table A.2 lists the identifier families that this document takes verbatim from the design document.

Table A.2. Identifier families.

| Identifier | Meaning | Defined in |
|---|---|---|
| R1-R9, R3' | Operator rulings of 2026-11-05 | Design document 0.1 |
| r8-17, r9-1 to r9-8 | Revision-log rows of 2026-11-12 | Design document 0.2 |
| D-01 to D-50 | Layout decisions | `LAYOUT_DECISIONS.md` |
| D2-1 to D2-5 | Operator rulings on hang defence | `decisions_2026-11-12/round2/` |
| T1-T17r | Tap conductors from the MB to the CR | Design document A.4 |
| F.5-T1 to F.5-T10 | Mode transitions, named here with the prefix F.5 to keep them apart from the taps | Design document F.5 |
| FR-nn, I-n | Firmware requirements and invariants | Design document G.2, F.5 |
| T-A-nn to T-W-nn | Tests | Design document I |
| PMn | MB modification steps | Design document D.1 |
| MS1-MS8 | Pre-capture survey items of test T-A-08 | Design document I |
| J.1 item n, J.2 item n | Accepted residuals and open items | Design document J.1, J.2 |
| L.8, L.9 | Audit run 001 and audit run 002 | Design document L |

The tap names and the transition names overlap (for example T1 and F.5-T1), so this document always writes the prefix
for a transition.
