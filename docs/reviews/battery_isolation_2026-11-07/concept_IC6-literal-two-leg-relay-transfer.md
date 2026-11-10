# IC6 design dossier: literal two-leg relay transfer of the pack to the Ag105 battery port

Date: 2026-11-07. Board revision 20260622, fw v37 rev 2 (`AG105_VBATN_ISOLATED 0`). Inputs: `facts_board.md`,
`facts_ag105.md`, `facts_firmware.md`, `facts_prior.md` and `brainstorm.md` in this folder. Nothing in this dossier
has been ordered, desoldered or flashed.

## 0. Summary

**Post-review status (review round 1, section 10).** IC6 is **withdrawn as a requirement-meeting design**. HR1
(regen) fails by construction, and operator ruling 1 makes regen a hard requirement; no fix inside IC6 restores it
(section 10.2, finding S-F1). IC6 also misses the H5 charge-rate floor of at least 1.5 A at 8.4 V inside the FC
budget (section 10.6). The concept is retained only as a **standstill-only fallback (IC6-R1)**, to be used if the
operator relaxes ruling 1 to "FC charging only". Section 10.5 states the revised fallback design; where the body below
and section 10.5 disagree, section 10.5 governs. The body text keeps its original figures so that the review
findings remain traceable.

This dossier develops concept IC6, the operator's literal request: a relay assembly in the pack harness moves both
pack legs from the board (J-BT) to the Ag105 battery port (VBat+ and VBat-) for a charge window, and moves them back
for driving. The design keeps the Teensy powered from the pack in both relay positions, so the "Teensy browns out"
objection of `docs/respin_power_architecture_2026-11-04.md` option 2 does not apply to it.

The design has the following properties:

1. **The circulating loop is broken by topology.** While the pack is on the Ag105 battery port, the pack and the
   charger output have no connection to VBT, D-BT-SQ is permanently disabled, and a hardware interlock holds the BT
   boost and BT_BUS off. While the pack is on the board, a hardware permit removes power from both charger feeds.
2. **The Ag105 current sense carries the cell current again.** The pack return reaches GND only through VBat- and
   the module sense, so the ML0227 mechanism (sense paralleled by the GND pour) is absent in the CHARGE position.
3. **Charging is standstill-only.** A hardware interlock prevents the relay from leaving RUN while `MOT_PWR_ENABLE`,
   `BT_REG_ENABLE` or `BT_BUS_ENABLE` is HIGH. Regen energy therefore cannot reach the pack: **HR1 FAILS**.
4. **Teensy hang, reset and brownout all return the relay to RUN** through a dynamic (charge-pump) coil drive and
   passive pull-downs, and remove power from both charger feeds.

The residual single-fault risk that this design does not close is a welded pack-negative contact (section 5, row
F3), which re-creates the sense bypass during a charge window. That fault cannot form a loop. The original text
bounded its current by the FC input power; review round 1 refuted that bound for a bench supply on J-FC (the ML0227
condition), and section 10.5 adds a hardware charge-current ceiling in its place.

Section 2.4 lists five departures from the concept brief, and each one is justified there. The most important
departure moves the logic-return diode to the pack side of the relay. The brief's position at VBat- cannot keep
the Teensy powered while the relay is in transit.

## 1. Topology

### 1.1 Nets and definitions

This dossier uses the following new net names. Existing net names are those of `Scale_Car_Board_20260624.sch`.

- **PACK+ / PACK-**: the pack terminals, on the pack side of the relays (harness).
- **VLOGIC**: the new LM1084 input net, fed from PACK+ through fuse F1. It replaces the VBT feed of REG-5V.
- **VBATN**: the lifted Ag105 VBat- pins 14/15 (module side of the cut).
- **G_K**: the gate node of the coil driver Q1.
- **RUN position**: both relays de-energized; PACK+ on VBT (J-BT 1), PACK- on GND (J-BT 2).
- **CHARGE position**: both relays energized; PACK+ on VCHG (Ag105 VBat+), PACK- on VBATN.

### 1.2 Power topology

Figure 1 shows the power topology. K1 and K2 are two single-pole changeover relays driven by one coil driver. The
board-side nets are unchanged except for the four rework items marked (R1) to (R4).

```
  PACK (2S LiPo)                 SWITCH BOARD (in the J-BT harness)                         DC BALANCER BOARD
  ==============                 ==================================                         =================

  PACK+ --+--[F0 main]--+------------------ COM K1 --NC-----------------------------> J-BT 1 = VBT
          |             |                       |    \__NO--[F4]--------------------> VCHG (C-D11 pad / Ag105
          |             |                       |                                     VBat+ 18/19)      (R2)
          |             +--[R_PC 220R]----------|----------------------------------> (to K1 NC side = VBT)
          |             |
          |             +--[F1 1-2 A]---------------------------------------------> VLOGIC = REG-5V pad 3
          |                                                                          (VBT trace cut)   (R3)
          |             +-- coil K1 --[R_S1 17R]--+
          |             +-- coil K2 --[R_S2 17R]--+--D(Q1 NTR4501N)S-- GND
          |                     (freewheel D_FW1/D_FW2 across each coil+R_S)
          |
  PACK- --+--------------------------------- COM K2 --NC-----------------------------> J-BT 2 = GND
                                                |    \__NO--[F2]--------------------> VBATN (lifted Ag105
                                                |                                      pins 14/15)      (R1)
                                                +--|<|--[F3]---- (K2 NC side = GND)
                                                  D_LR MBRS540 (anode GND, cathode PACK-)

  BALANCE LEAD: J-BL 1 VBAL+ and 2 VMID unchanged; J-BL 3 (pack negative) REMOVED from the harness (X1).   (R4)
  D-BT-SQ: EN cut from Teensy pin 32 and tied to GND (permanently OFF).                                    (R5)
```

The following points explain the figure:

- R_PC and D_LR sit across the two NC contacts. In RUN each is shorted by its closed contact. In CHARGE, R_PC holds
  VBT at the pack voltage (soft re-close, section 4.3), and D_LR is reverse-biased by the charge current through the
  sense (section 4.5).
- VLOGIC is taken ahead of both relays, so the LM1084 and the Teensy stay on the pack in RUN, in CHARGE and in
  transit.
- In CHARGE, VBT has no source except R_PC. VCHG reaches the pack only through K1 NO, and D-BT-SQ isolates VCHG from
  VBT in both directions (RT1987 DS-00 section 17, p.14: "Unlike single MOSFET devices, the RT1987 completely isolates
  VIN and VOUT when disabled using the EN input").

### 1.3 Control topology

Figure 2 shows the coil-drive and permit logic. All new control parts sit on the switch board and are referenced
to PCB GND through a J2 header GND contact.

```
 Teensy pin 33 --||-- C_P 1uF --+--|>|--+--> G_K ----+---- R_H 100k ---- GND
 (toggled in loop)              |  D_P2 |  (C_H 1uF) |
                                |  BAT54            +---- gate Q1 (coil driver, Figure 1)
                       GND --|>|-+                   |
                         D_P1 BAT54                  +---- drain Q_A (BSS138) gate <- pin 4  BT_REG_ENABLE net
                                                     +---- drain Q_B (BSS138) gate <- pin 28 BT_BUS_ENABLE net
                                                     +---- drain Q_C (BSS138) gate <- pin 29 MOT_PWR_ENABLE net
                                                     +---- drain Q_OVP (BSS138) gate <- BQ29200 OUT (10k series,
                                                     |                                  100k to GND)
                                                     +---- gate Q5 (BSS138, inverter), drain = N_INV, 100k to 3V3

 N_INV --> gates of Q6 and Q7 (BSS138)
   Q6 drain -> D-BC-FC EN net (pin 31 side of a new 1k series resistor R_31)        (R6)
   Q7 drain -> D-BC-RG EN net (pin 30 side of a new 1k series resistor R_30)        (R6)

 Readbacks:  VLOGIC --16.2k--+--10k-- GND   -> pin 16 PACK_V   (10 nF at the pin)
             VCHG   --16.2k--+--10k-- GND   -> pin 17 VCHG_V   (10 nF at the pin)
             BQ29200 OUT --100k--+--47k-- GND -> pin 22 BAL_OVP (analog)
```

The logic has the following meaning:

- **G_K is HIGH only while the Teensy toggles pin 33.** The pump C_P/D_P1/D_P2 rectifies the toggle into C_H. A static
  pin level, HIGH or LOW, delivers no charge, and R_H discharges G_K. A hung loop, a reset, or an unpowered Teensy
  therefore de-energizes both relays.
- **Q_A, Q_B and Q_C are the transfer interlock.** Any one of BT_REG, BT_BUS or MOT_PWR HIGH clamps G_K low, so the
  relay can be in CHARGE only with the BT boost off, BT_BUS open and the motor node unpowered.
- **Q_OVP is the hardware cell-OVP action.** A BQ29200 OUT high clamps G_K low and returns the pack to RUN, which
  disconnects the pack from the charger output.
- **Q5, Q6 and Q7 are the charger permit.** With G_K low, Q6 and Q7 hold both charger-feed EN nets low, so the
  Ag105 cannot be powered while the pack is on the board. The new 1 kOhm series resistors limit the current from a
  Teensy pin that drives HIGH against Q6 or Q7 to 3.3 mA.

### 1.4 Electrical state table

Table 1 states, for each relay position, which source each node has. It is the basis of the HR3 argument in
section 6.

Table 1. Node sources per relay position.

| Node | RUN (de-energized) | CHARGE (energized) | Transit (both poles open, at most 15 ms) |
|---|---|---|---|
| VBT | Pack via K1 NC | R_PC from PACK+ only (no BT boost load, interlocked) | R_PC and its own capacitance |
| VCHG | Isolated (K1 NO open, D-BT-SQ off); decays through the VCHG_V divider | Pack via K1 NO; Ag105 output | Ag105 output only if powered (firmware forbids) |
| VLOGIC | Pack (ahead of relay) | Pack (ahead of relay) | Pack (ahead of relay) |
| GND to pack negative | K2 NC (plus D_LR in parallel) | Ag105 sense (VBat- to Vin-), D_LR reverse-biased during charge | D_LR only |
| Ag105 input (VCHG-IN) | No feed possible (Q6, Q7 hold both EN low) | D-BC-FC permitted; D-BC-RG permitted but MOT_PWR is interlocked LOW | No feed (firmware sequence) |

## 2. Parts, ratings and fail-safe defaults

### 2.1 Relays K1 and K2

The selected relay is the TE Connectivity (Potter & Brumfield) **T9A series, 1 Form C, 1 W "D" coil, 5 VDC
(coil code 5)**, one per pole. The exact ordering code (mounting and termination code) is TODO(verify: TE T9A
ordering table). Table 2 lists the ratings that this design uses. The source is the TE data sheet "T9A Series, DC
Coil 30A PCB or Panel Mount Relay", Rev. 0815 (09-2015), pages 1-2.

Table 2. T9A ratings used by this design.

| Quantity | Value | Use in this design |
|---|---|---|
| Form C contact rating | 20 A (NO) / 10 A (NC), 28 VDC resistive, 100x10^3 cycles | NC carries the RUN pack current; NO breaks the charge current only in fault actions |
| Limiting continuous current | 30 A (stated for the form A column; form C value not stated) | Form C NC carry rating above 10 A is UNCONFIRMED |
| Initial contact resistance | 75 mOhm at 1 A, 5 VDC (the only figure given) | Worst-case bound; the typical value is BENCH (gate B4) |
| Minimum recommended contact load | 1 A, 5 VDC | Met at each make: every make charges a capacitance from the pack (section 4.3) |
| Operate / release time, maximum, including bounce | 15 / 15 ms | Transfer timing (section 4.4) |
| Coil, code 5, 1 W | 5 VDC rated, 3.75 V operate, 0.5 V release, 25 Ohm +/-10 %, 1 W | Coil drive (section 2.2) |
| Maximum coil power | 110 % of nominal | Series-resistor sizing |
| Mechanical endurance | 10x10^6 operations | Transfers are at near-zero current, so mechanical life governs |
| Ambient (DC coil) | -55 to 85 degC | Harness enclosure |

The NC side is the weaker side of a Form C contact (10 A against 20 A). The RUN current must therefore be checked
against 10 A (section 4.1). A relay whose NC rating exceeds the bench peak (16.46 A, `facts_prior` section 9) was
not found with a coil that runs from a 7.4-8.4 V source; the Omron G7J 2a2b type, for example, is rated 8 A on its
NC contacts (Omron G7J data, distributor reprint; primary TODO(verify: Omron)). This is a recorded limitation, not a
solved problem. Review round 1 (finding E-M2) rejected the T9A for the RUN path; section 10.5 substitutes a 30 A NC
automotive changeover relay with a boosted coil supply.

Two single-pole relays are used instead of one double-pole relay. Two separate armatures can move at different
instants within the 15 ms operate time; section 4.4 shows that every intermediate combination is benign when the
charger is unpowered.

### 2.2 Coil drive

The coils run from VLOGIC (pack, 7.4-8.4 V) through series resistors, not from the 5 V rail, so the LM1084 does not
dissipate the coil power. With R_S = 17 Ohm in series with each 25 Ohm coil:

- At 8.4 V the coil current is 8.4 / 42 = 0.200 A, the coil power is 1.00 W (100 % of nominal, inside the 110 %
  limit) and R_S dissipates 0.68 W. Use a 2 W resistor.
- At 7.0 V (pack floor less sag) the coil voltage is 7.0 x 25 / 42 = 4.17 V, 111 % of the 3.75 V operate value. The
  operate voltage rises with coil temperature (TE note 3, p.2); the hot-coil margin is BENCH (gate B5).
- Two relays draw 0.40 A (3.36 W) at 8.4 V and 0.35 A (2.61 W) at 7.4 V for as long as CHARGE is held. Section 4.6
  charges this to the FC budget. A pull-in/hold economizer would reduce it, but the T9A data sheet gives no hold
  voltage, so an economizer is TODO(verify: TE) and is not part of the baseline.

Q1 is an onsemi **NTR4501N** (NTR4501N/D Rev. 16, Feb 2024, pp.1-2): V_DSS 20 V, I_D 3.2 A continuous at 25 degC,
R_DS(on) 80 mOhm max at V_GS 4.5 V and 105 mOhm max at 2.5 V, V_GS(th) 0.65-1.2 V. At 0.40 A and 105 mOhm, Q1
dissipates 17 mW.

The freewheel diodes D_FW1 and D_FW2 are onsemi **MBRS540T3G** (MBRS540T3/D Rev. 13, Feb 2026, p.2): 40 V, 5 A,
V_F 0.50 V max at 5 A. A plain freewheel diode clamps the Q1 drain at VLOGIC + V_F, about 9 V, against the 20 V
V_DSS. However, a plain freewheel diode lengthens the release time beyond the 15 ms data-sheet figure; the measured
release time is BENCH (gate B5). No zener is fitted; the release time is not on any safety-critical path (section
4.4).

### 2.3 Dynamic coil enable (pump)

The pump uses onsemi **BAT54** Schottky diodes (BAT54LT1/D Rev. 18, Nov 2024, pp.1-2: V_R 30 V, I_F 200 mA,
V_F 0.35 V typical at 10 mA). Firmware toggles pin 33 once per main-loop iteration, which gives a square wave of
about 442 Hz at the measured 884 Hz median loop rate (`facts_firmware` section 8). G_K settles near
3.3 - 2 x 0.35 = 2.6 V (UNCONFIRMED; the BAT54 V_F at the pump's sub-milliampere current is lower than the 10 mA
figure, so 2.6 V is a lower estimate). G_K exceeds the NTR4501N 2.5 V R_DS(on) rating point.

The hold network is C_H = 1 uF and R_H = 100 kOhm (tau = 0.1 s). The G_K load is R_H (26 uA at 2.6 V) plus leakage.
The droop over the worst measured loop gap of 9.76 ms is 26 uA x 9.76 ms / 1 uF = 0.25 V (computed as
I x t / C; this is an upper bound, because R_H current falls as G_K falls). G_K remains at about 2.35 V, above the
1.2 V maximum Q1 threshold.

When the toggle stops, G_K decays from 2.6 V:

- to 1.2 V (Q1 V_GS(th) maximum) in 0.1 x ln(2.6/1.2) = 77 ms;
- to 0.65 V (Q1 V_GS(th) minimum) in 0.1 x ln(2.6/0.65) = 139 ms.

The relay therefore releases 77-139 ms after the last toggle, plus the release time (gate B5). A blocking operation
of the main loop longer than about 70 ms releases the relay. The EEPROM commit (up to about 1.2 s with interrupts
masked, `facts_prior` section 10 item 7), SD close and `Ethernet.begin()` must therefore be forbidden while CHARGE
is held. This is the same rule that the MCU watchdog lesson already imposes.

The hardware PWM peripheral must not drive pin 33. A hardware PWM keeps running in a hung loop and would defeat the
dynamic enable.

### 2.4 Departures from the concept brief

The brief for IC6 was followed except for the five points in Table 3.

Table 3. Departures from the IC6 brief.

| Brief item | This dossier | Reason |
|---|---|---|
| D_RET Schottky from GND to the lifted VBat- | D_LR from PCB GND to **PACK-** (across the K2 NC contact) | In transit, both K2 contacts are open, so a diode at VBat- connects to nothing. The logic return (LM1084, Teensy, coils) then has no path to pack negative; GND rises toward PACK+ and the LM1084 loses its input. The 10 uF CO-5V and the Teensy decoupling cannot hold 0.3-0.6 A for 15 ms (about 4.5 mF would be needed for a 1 V droop). D_LR at PACK- carries the logic return in transit. |
| Schottky from pack+ to the LM1084 input, optionally OR'd with VBUS | Direct fused feed from PACK+ (F1), no diode, no VBUS OR | No second source is OR'd, so no diode is needed. Omitting the diode keeps 0.3-0.45 V of LM1084 headroom (section 4.5). A VBUS OR would take the logic power from the FC during a charge window and consume the FC charge budget. |
| Pin 34 auxiliary-contact readback | Pin 17 VCHG_V analog readback | The T9A has no auxiliary contact. VCHG reads the pack voltage only when K1 NO is closed, so it confirms pole A. Pole B has no readback (section 5, row F3). |
| Pin 35 external watchdog IC | Dynamic coil drive (section 2.3) plus the internal RTWDOG (X9) | The TI TPS3431 (ti.com/lit/ds/symlink/tps3431.pdf, Pin Functions and Timing Requirements) asserts WDO for only t_RST (about 200 ms) per timeout and then releases it. Driving the coil from WDO would cycle the relay with the charger powered. The dynamic drive releases the relay on any static pin level and needs no latch. Pin 35 stays spare. |
| Optional auxiliary-contact element in the pin 30/31 EN nets | Q5/Q6/Q7 permit keyed on G_K, with 1 kOhm series resistors | The T9A has no auxiliary contact. The permit is keyed on the coil command, not on contact position; contact position is confirmed by firmware through VCHG_V. |

In addition, the brief's "hardware AND (coil only with BT_REG and BT_BUS low)" is extended with Q_C (MOT_PWR) and
Q_OVP (BQ29200 OUT). The brief's three-pole option (pole C for the balance negative) is replaced by X1: the balance
negative is removed from J-BL pin 3. Section 4.7 shows that the BQ29200 still measures correctly.

### 2.5 Other parts

Table 4 lists the remaining parts. Parts without a fetched primary carry a requirement and a TODO.

Table 4. Remaining parts.

| Ref | Part | Rating used | Source |
|---|---|---|---|
| D_LR | onsemi MBRS540T3G | 40 V, 5 A average, V_F 0.50 V max at 5 A, I_R 0.3 mA max at 40 V, 25 degC | MBRS540T3/D Rev. 13, p.2 |
| Q_A, Q_B, Q_C, Q_OVP, Q5, Q6, Q7 | onsemi BSS138 | 50 V, 0.22 A, V_GS(th) 0.8-1.5 V, R_DS(on) 6.0 Ohm max at 4.5 V | onsemi BSS138 data sheet, p.2 (document revision not read, TODO(verify: onsemi)) |
| R_PC | 220 Ohm, 1 W | 8.4 V / 220 Ohm = 38 mA, 0.32 W worst case into a discharged VBT | Ohm's law |
| R_S1, R_S2 | 17 Ohm, 2 W | Section 2.2 | Ohm's law |
| F0 | Main pack fuse, at the pack | Must pass the BT-boost class current (up to the 16.46 A bench peak); interrupting rating at least the 120-420 A prospective pack current (`facts_prior` section 9) | Part TODO(verify: fuse vendor). Ag105 DS p.7, p.15, p.16 figures show a 10 A slow-blow fuse in the battery lead. |
| F1 | VLOGIC fuse, 1-2 A fast | Carries I_5V plus 0.40 A of coil current | Part TODO(verify: fuse vendor); I_5V is BENCH (gate B8) |
| F2 | VBATN-lead fuse, 4 A fast | Passes 2.5 A charge plus the logic and coil return; opens a welded-K2-NO fault (section 5, row F4) | Part TODO(verify: fuse vendor) |
| F3 | D_LR-series fuse, 2 A fast | Passes the 0.3-0.6 A transit return | Part TODO(verify: fuse vendor) |
| F4 | VCHG-lead fuse, 4 A fast | Protects the VCHG flying lead | Part TODO(verify: fuse vendor) |
| C_P, C_H | 1 uF, 10 V, X7R | Pump and hold | - |
| R_31, R_30 | 1 kOhm | Series in the pin-31 and pin-30 EN nets | - |
| Dividers | 16.2 kOhm / 10 kOhm (x2), 100 kOhm / 47 kOhm | Full scale 8.646 V (same as R1-BT/R2-BT); BAL_OVP 9.5 V maps to 3.04 V | `facts_board` section 3.4; BQ29200 V_OUT 6-9.5 V at VDD 10 V (SLUSA52C section 7.5, p.6) |

### 2.6 Fail-safe defaults

Every new switch defaults to the safe state through a passive element, not through a GPIO level.

- **K1 and K2 default to RUN.** The coil current requires G_K above 0.65-1.2 V. R_H (100 kOhm) holds G_K at 0 V
  with the Teensy unpowered, in reset, with pin 33 at its keeper level, or with pin 33 static.
- **The charger feeds default OFF in RUN.** Q6 and Q7 are ON whenever G_K is low, because N_INV is pulled up to 3V3
  by 100 kOhm and Q5 is OFF. With the Teensy unpowered, 3V3 is absent; the feeds are then held OFF by the RT1987
  internal EN pull-down (475-985 kOhm, RT1987 DS-00 p.7) and by the 10 kOhm bodge pull-downs where fitted (OQ-7).
- **D-BT-SQ is permanently OFF** (EN tied to GND, rework R5).
- **No new switch can be energized by a USB-powered Teensy alone.** A USB-powered Teensy can toggle pin 33. However,
  the coil supply is VLOGIC (pack), so the relay can move only with the pack present.

## 3. Teensy pins and control sequences

### 3.1 Pin allocation

Table 5 allocates the free pins of `facts_board` section 7.2. Pins 2, 7 and 8 are avoided. The CSV
(`references/Scale Car Teensy IO - IO.csv`) must be amended before firmware uses any of these pins; this study does
not edit it.

Table 5. New pin allocation.

| Pin | Proposed code name | Dir | Function | Reset state |
|---|---|---|---|---|
| 33 | `PACK_CHG_PUMP` | OUT | Toggled each loop iteration to hold the relays in CHARGE; held LOW otherwise | Keeper; static, so relays in RUN |
| 16 | `PACK_V` | AIN | VLOGIC (pack positive) through 16.2k/10k | - |
| 17 | `VCHG_V` | AIN | VCHG through 16.2k/10k; pole-A position readback | - |
| 22 | `BAL_OVP` | AIN | BQ29200 OUT through 100k/47k | - |
| 35 | spare | - | Reserved for an external watchdog if the RTWDOG is rejected | - |
| 32 | (`BT_SEQUENCE_ENABLE`) | - | Retired: the EN trace is cut and EN is tied to GND | - |

### 3.2 Sequences

The following sequences cover every state named in the task. "Confirm" means a firmware check with a timeout that
latches a fault on expiry.

**Boot (setup).** Pin 33 is set OUTPUT LOW before any other I/O, next to the existing early writes. The relays are in
RUN from power-on, so the pack is on VBT exactly as on today's board. The staged bring-up (P0-P3) and its P0 gate on
max(V_fc, V_batt) are unchanged, because V_batt (pin 25, VBT) reads the pack in RUN. At boot, firmware checks
VCHG_V < 2 V. A reading near the pack voltage means K1 NO is welded or Q1 is shorted (section 5, rows F2 and F7), and
firmware latches a new fault instead of enabling BT_REG.

**Idle and Run discharge.** The relays are in RUN and pin 33 is LOW. The board is electrically today's board with
D-BT-SQ disabled. Q6 and Q7 hold both charger feeds OFF in hardware. Regen goes to the TL431/BSP170P chopper, as in
fw v37 rev 2.

**Regen brake (Run).** No change from today: REGEN is held LOW (now also in hardware by Q7), the chopper clamps
V-MOT. **No regen energy reaches the pack.** A per-event transfer is not offered (section 4.4); a planned "regen
hold" with MOT_PWR HIGH in CHARGE is excluded by the Q_C interlock.

**FC-charge window (entry from Idle, vehicle stationary).**

1. Preconditions: State 1, wheel speed zero, Pi command to charge, PACK_V < the recharge threshold, BAL_OVP low,
   FC stack running, V_bus >= 13.5 V.
2. Set the motor current to 0 and drive `MOT_PWR_ENABLE` LOW. V-MOT and the VESC discharge. Reason: with the pack
   off the bus, the VESC would be fed from an FC-only bus that collapses at each purge.
3. Drive `BT_BUS_ENABLE` LOW, then `BT_REG_ENABLE` LOW. Reason: BT_BUS first removes the battery from the bus before
   its boost stops, so no disabled-boost back-feed path exists. The bus is now FC-only with no traction load.
4. Confirm that pins 4, 28 and 29 read LOW and V_bus >= 13.5 V for 50 ms.
5. Start toggling pin 33. Confirm VCHG_V within 0.3 V of PACK_V within 100 ms (15 ms operate time plus margin). On a
   timeout, stop the toggle (K1 failed to transfer; section 5 row F1).
6. Wait 50 ms more (both armatures settled; contact bounce over).
7. (Superseded by section 10.5: the Ag105 is unpowered here and cannot ACK I2C, finding F-M6.) Write the charge
   current (reg 0x00) for the FC budget, code 6 (1.0 A) by default (section 4.6), then call
   `assertFcChargeEnable(true)`. The existing guard drives BT_BUS and REGEN LOW first. The Ag105 is powered by
   D-BC-FC with the battery already on its port.
8. `pollAg105()` configures the module lazily after `AG105_SETTLE_MS`, as today. Firmware then requires GENSTAT
   Charging and reg 0x06 > 0 within a timeout (gate B2), and runs the K2-weld plausibility check of section 5 row F3
   for the whole window.

**H-20 purge during a window.** (Superseded by section 10.5: the ride-through below conflicts with operator ruling
6, finding S-M1.) The bus is FC-only, so it collapses at about 2.57 V/ms (`facts_prior` section 7).
VCHG-IN falls below the 11 V Ag105 UVLO (DS p.19), and the charger stops. The pack keeps supplying VLOGIC, so the
Teensy, the relay coils and the pump are unaffected. When the stack recovers, the bus and VCHG-IN rise together
through the already-closed D-BC-FC, and the Ag105 restarts its detection cycle with a battery present.

The firmware must treat this as a charge pause, not as a fault. Today UV_BUS latches after a 20 ms dwell under
12.0 V when the FC pair is armed (`facts_firmware` section 4), which is shorter than a 100-140 ms purge. The fw v33b
gate also refuses FC windows on a purging stack. Both rules need a CHARGE-mode exception (section 8). As an
alternative, the window can follow ruling 6 and close about 1 s before each predicted purge. That alternative costs
one Ag105 restart per 10.34 s period in both cases.

**Window exit (normal).**

1. Call `assertFcChargeEnable(false)` (FC_CHARGE LOW).
2. Wait until V_chg (pin 38) < 9 V, timeout 1 s. Reason: the relay must not move while the Ag105 is powered (X7).
   The decay rate depends on the module's idle current below 18 mA (DS p.20 row 4) and is BENCH.
3. Stop toggling pin 33 and hold it LOW. The relays release 77-139 ms later plus the release time.
4. Confirm VCHG_V < 2 V within 500 ms (K1 left NO). Confirm V_batt (pin 25) within 0.3 V of PACK_V (K1 NC closed).
   R_PC has held VBT at the pack voltage, so the NC make is nearly current-free.
5. Re-run the staged bring-up from P0 (boosts off, bus discharged). The bring-up restores BT_REG, BT_BUS and MOT_PWR
   in its proven order. Review round 1 (finding F-M4) corrected the rationale: since 2026-08-03 the sanctioned connect
   of a discharged motor node is from a regulated bus through the D-MT-EN soft-start (P3, `motPwrConnectBlocked()`,
   ino:972-981), so the Death-5 low-voltage doctrine is not the reason. Section 10.5 replaces this step with a
   shorter exit.

**Finish (State 3).** State 3 is a Run exit; the relays are already in RUN. No change.

**State 99 (Error).** The order is: FC_CHARGE LOW and REGEN LOW first (charger input removed); then pin 33 LOW
(relays to RUN after 77-139 ms); then the existing teardown of bus switches and boosts. The pack returns to VBT
through R_PC-precharged contacts while the boosts are off. The Teensy remains powered from VLOGIC through the
latched error, so telemetry continues. The Phase-0 and Phase-1 drains into the charger (`facts_firmware` section 2.1)
are blocked in RUN by Q6 and Q7 and must be removed or accepted as ineffective.

**Teensy reset or brownout.** Every GPIO goes high-Z. The RT1987 EN pull-downs open both charger feeds immediately.
Pin 33 stops toggling, so the relays release 77-139 ms later. On reset the charger feed therefore drops before the
relay moves, which respects X7 without firmware. VCHG-IN (C-D8 plus C-D10, 20 uF) falls from 16 V to the 11 V UVLO
in about 20 uF x 5 V / 18 mA = 5.6 ms if the Ag105 draws its 18 mA maximum idle current (computed; the actual idle
current is BENCH).

**Teensy hang (loop frozen, pins static).** The toggle stops. Q5 turns OFF when G_K falls below 0.8-1.5 V (55-118 ms),
so Q6 and Q7 pull both charger EN nets low through the 1 kOhm series resistors even if pin 31 is stuck HIGH. Q1
turns OFF at 77-139 ms. The two threshold windows overlap, so the relay can move before the charger feed drops.
In that case K1 NO breaks at most 1.0 A of cell current plus about 0.7 A of logic and coil current at 8.4 V, which
is inside the 20 A, 28 VDC NO rating. Every other output (FC_BUS, FC_REG) stays at its last level; the RTWDOG (X9)
is still required for those.

## 4. Quantitative checks

### 4.1 Conduction loss in RUN

The pack current in RUN flows through K1 NC, K2 NC and the harness. The production envelope is set by OC_BT, a
single-sample 3.0 A trip on the bus-side BT current (`facts_firmware` section 4). At 16.0 V and an assumed boost
efficiency of 0.90 (UNCONFIRMED; not taken from SLVSFP3C), the pack current at the trip is
3.0 x 16.0 / (0.90 x 7.4) = 7.21 A. This is 72 % of the 10 A NC rating. OC_BT is compiled out of `BENCH_TEST 1`
builds, and the incident record shows 16.46 A on the BT channel (`facts_prior` section 9). The bench envelope
exceeds the NC rating.

Table 6 gives the drop and loss of the two contacts in series for three contact resistances. Only the 75 mOhm value
is a data-sheet figure, and it is specified at 1 A.

Table 6. Two-contact drop and loss in RUN (harness resistance excluded).

| R per contact | Drop at 7.21 A | Loss at 7.21 A | Drop at 15 A | Loss at 15 A |
|---|---|---|---|---|
| 5 mOhm (assumed typical) | 72 mV | 0.52 W | 0.15 V | 2.25 W |
| 20 mOhm | 0.29 V | 2.08 W | 0.60 V | 9.0 W |
| 75 mOhm (TE initial, at 1 A) | 1.08 V | 7.80 W | 2.25 V | 33.8 W |

The design is acceptable only if the measured contact resistance is low. The acceptance criterion for gate B4 is
10 mOhm or less per contact at 10 A, and a temperature rise at 7.2 A continuous that the TE derating curve (p.2)
accepts. The 75 mOhm row would drop VBT by 1.08 V at the production envelope; firmware that judges the pack on VBT
(pin 25) would see 7.4 V at a true pack voltage of 8.5 V. Section 8 therefore moves UV_BATT and OV_BATT to PACK_V.

### 4.2 Switching duty and SOA

- **Normal transfers occur at near-zero contact current.** On entry, BT_REG and BT_BUS are LOW (interlocked) and the
  charger is unpowered. On exit, the charger input has decayed below its UVLO. The only currents at break are the
  R_PC current and capacitor charge, both below 0.1 A.
- **Fault-action breaks** (BQ29200 OVP, Teensy hang, BT interlock trip during CHARGE) open K1 NO and K2 NO under the
  charge current. The worst case is the 2.5 A setting plus about 0.7 A of logic and coil current, 3.2 A at 8.4 V,
  inside the 20 A, 28 VDC NO rating.
- **Q1** dissipates 17 mW in steady state. During the slow G_K decay of a hang it passes through its linear region
  for tens of milliseconds at up to 0.4 A and a few volts, which is about 1 W for under 0.1 s; the NTR4501N steady-
  state rating is 1.25 W on a 1 in^2 pad (p.1). The transient is UNCONFIRMED against its SOA curve.
- **D_LR** carries 0.3-0.6 A in transit (V_F below 0.50 V). In RUN it shares the return current only if the K2 NC
  drop exceeds its forward voltage, which at 5 mOhm requires several tens of amperes (UNCONFIRMED; the MBRS540
  forward curve at low current was not read).

### 4.3 Inrush at each make

**K1 NC make (exit).** Without R_PC, VBT would be discharged after a long window (VBT capacitance discharges through
the 26.2 kOhm divider and the TPS61288 quiescent current). The make would close the pack onto C1-BT, C-D12, the
TPS61288 input capacitance and, through the disabled boost's body diode, its output capacitance. With an assumed
harness inductance of 1 uH and 40 uF of total capacitance (both UNCONFIRMED; the VBT capacitance total is gate X8),
Z0 = sqrt(1 uH / 40 uF) = 0.16 Ohm, so the peak current is about 8.4 / 0.16 = 53 A. With 50 mOhm loop resistance the
damping ratio is 0.16, and VBT overshoots to about 13.4 V. This is below the 20 V TPS61288 VIN absolute maximum
(SLVSFP3C section 7.1, p.5; read from a column-scrambled text extraction, TODO(verify: rendered page)) and below the
RT1987 40 V maximum on the D-BT-SQ VOUT pin. The event is of the same class as plugging the pack into J-BT by hand.

R_PC removes this event. In CHARGE, R_PC holds VBT at the pack voltage less 220 Ohm x (0.32 mA divider + TPS61288
shutdown current), within about 0.1 V. The K1 NC make then closes across about 0.1 V.

**K1 NO make (entry).** The pack closes onto VCHG: C-D11 (10 uF), the D-BT-SQ VIN capacitance and the Ag105 output
capacitance (TODO(verify: Silvertel)). VCHG starts near 0 V (discharged by the VCHG_V divider). The peak current is
of the same order as the hand plug-in case; it charges a smaller capacitance. The make current wets the contact
(T9A minimum load 1 A at 5 VDC). The Ag105 VBat+ absolute rating against a fast step from 0 to 8.4 V is not given by
the data sheet (TODO(verify: Silvertel)); the step is the same as connecting a battery to the module as DS Fig.4
intends. Review round 1 (finding F-M5) rejected the "same class as hand plug-in" argument: rule H8 limits every new
make onto capacitance to 1.0 A peak, and the estimate is about 30 A. Section 10.5 adds a VCHG pre-charge path.

**K2 makes** carry only the logic and coil return and capacitor charge.

### 4.4 Timing against the regen burst and the Ag105 start

Table 7 builds the earliest time from a decision to charge to the first Ag105 charge current.

Table 7. Entry timeline.

| Step | Duration | Source |
|---|---|---|
| BT_BUS LOW, BT_REG LOW, confirm | 50 ms (firmware dwell) | Section 3.2 step 4 |
| Pump charges G_K, relay operates | <= 15 ms operate (G_K rise is a few ms; UNCONFIRMED) | TE T9A p.1 |
| VCHG_V confirm and settle | 50 ms (firmware) | Section 3.2 step 6 |
| D-BC-FC turn-on delay | 8 ms typical | RT1987 DS-00 section 17.1 |
| Ag105 start to I2C-ready and to current | TODO(verify: Silvertel); 65-170 ms cold start measured | `facts_prior` section 6 |
| `AG105_SETTLE_MS` | 500 ms (`TODO(calibrate)`) | `facts_firmware` section 3.3 |

The total is 50 + 15 + 50 + 8 + (65 to 170) + 500 = 688-793 ms, of which the relay contributes at most 15 ms. The
regen pulse reaches the VESC stop at 21.35 V within 19-47 ms, the burst lasts 0.3-0.6 s, and a cold charger never
catches the first pulse (`facts_prior` section 6). A per-event transfer therefore captures at best the tail of a
burst, which is the 6-40 % side of the capture cliff. The relay is not the limiting element; the Ag105 start is (X6).

A per-event transfer also requires an FC-only bus at the moment of braking and the MOT_PWR interlock to be removed,
and it would give two relay operations per braking event. This dossier does not offer it. **HR1 fails for IC6.**

The datasheet path from a powered Ag105 to a present battery is the module's intended case: the battery is on the
port before input power arrives. The module then measures a battery above 2.7 V/cell and enters normal charge
without the 0 V Bring-Up ramp (DS p.6). The 0.64 V/s ML0227 ramp (`facts_ag105` section 3) does not occur in this
sequence (UNCONFIRMED until gate B2).

### 4.5 Teensy supply continuity

The LM1084-5.0 regulates for 6.5 V <= VIN <= 20 V, with a 1.5 V maximum dropout (SNVS037H section 5.5, p.5).
VLOGIC is the pack voltage less the F1 and lead drop. Table 8 gives the LM1084 input-to-GND voltage in each
position at the 7.4 V operating floor.

Table 8. LM1084 input headroom at a 7.4 V pack.

| Condition | Deductions from 7.4 V | LM1084 input | Margin over 6.5 V |
|---|---|---|---|
| RUN, 15 A pack current | Pack sag 24 mOhm x 15 A = 0.36 V (DCIR UNCONFIRMED); GND above pack- by 15 A x 10 mOhm = 0.15 V (K2 NC plus wire, assumed) | 6.89 V | 0.39 V |
| CHARGE, charger idle | GND above pack- by 0.7 A x R_s through the Ag105 sense (R_s BENCH, milliohm class; D_LR does not conduct, finding E-n7) | about 7.4 V | about 0.9 V |
| CHARGE, charging | Pack- above GND by I_cell x R_s; pack at charge voltage | > 7.4 V | > 0.9 V |
| Transit | D_LR V_F at 0.7 A, at most 0.50 V | >= 6.9 V | >= 0.4 V |

Review round 1 (finding E-M3) showed that the RUN row holds only at 10 mOhm per contact. At the T9A data-sheet
figure of 75 mOhm, the LM1084 input at 15 A is 7.4 - 0.36 - 1.13 = 5.91 V, below the 6.5 V regulation minimum
(SNVS037H section 5.5). Section 10.5 replaces the relay; Table 15 there gives the revised headroom.

The supply is continuous in every position. The ripple of the Teensy 5 V rail during a transfer is BENCH (gate B6).
This answers objection 2 of the re-spin note.

### 4.6 FC charge budget and parasitic draw

In CHARGE the Ag105 output supplies the cell current, which the sense regulates, plus the VLOGIC load, which the
sense does not see. The VLOGIC load is the coils (2.61-3.36 W) plus the logic (I_5V x VLOGIC, linear regulator; I_5V
is BENCH, gate B8). This dossier assumes I_5V = 0.3 A (2.5 W at 8.4 V; UNCONFIRMED) for the budget.

The bus budget is the 1.25 A governor ceiling less the 0.15 A aux load (`facts_prior` section 7), 1.10 A at 16 V,
which is 17.6 W. At the code-6 setting (1.0 A, Table 4 of `Ag105_Table4_Charge_Current_Select.json`), the Ag105
output is 8.4 W of cell power plus 3.36 W of coils plus 2.5 W of logic, 14.3 W. At the 0.88 efficiency (DS p.20,
specified only at 12 V in, 3S; UNCONFIRMED for this point), the input is 16.2 W, which is 1.02 A at 16 V. With the
aux load the bus carries 1.17 A, 6 % under the 1.25 A governor. Code 5 (1.25 A) would need 1.32 A and exceeds the
governor. Code 6 is therefore the maximum setting. About 40 % of the charger output is parasitic in this
configuration; a coil economizer is the main lever.

At 1.0 A a 5 Ah pack (capacity UNVERIFIED) needs more than 5 h from empty, before purge pauses. The H-20 P_MAX
(23.4 W stack, about 1.247 A at the bus) is not reached.

### 4.7 Measurement-reference shifts

- **V_batt (pin 25)** measures VBT against PCB GND. In RUN it reads the pack less both contact drops (Table 6). In
  CHARGE it reads the pack through R_PC. It remains useful as a "VBT present" readback.
- **PACK_V (pin 16)** measures VLOGIC against PCB GND. In RUN it reads the pack less the K2 NC drop and the F1 drop
  (about 0.15 V at 15 A with 10 mOhm). In CHARGE it reads the pack plus I_cell x R_s (pack negative above GND). It is
  the better pack measurement and should carry UV_BATT, OV_BATT and the SoC estimator.
- **INA253 SNS-FC and SNS-BT** are on the boost outputs and referenced to PCB GND. They do not move. In CHARGE,
  SNS-BT reads its zero floor (up to 0.1 A, SLOS954A section 7.5, via `facts_prior` section 10 item 11).
- **BQ29200** measures VC1 against its GND pin, which is PCB GND. After X1 removes the balance negative:
  - in RUN, VC1 - GND reads the bottom cell less the K2 NC drop (under-read, but nothing charges the pack in RUN);
  - in CHARGE, VC1 - GND reads the bottom cell plus I_cell x R_s (over-read, so the OVP trips early, which is the
    safe direction);
  - in CHARGE with the charger idle, it reads the bottom cell less 0.7 A x R_s, because the logic return flows
    backwards through the Ag105 sense, not through D_LR (corrected in review round 1, finding E-n7). VC1 - GND stays
    above the -0.3 V absolute minimum (SLUSA52C section 7.1).
  The top-cell measurement (VC2 - VC1) is unaffected. The OVP threshold is 4.35 V/cell, 8.70 V pack, after 2.0-4.0 s
  (SLUSA52C p.5, via `facts_prior` section 5).
- **Ag105 reg 0x05 and 0x06** measure the battery through VBat-. With the pack on the port they read the cell
  voltage and the cell current (DS p.13), which the 0xFF sentinel rule still governs (DS p.14).

## 5. Single-fault table

Table 9 lists each credible single fault, its effect and the layer that bounds it. "Loop" means the HR3 path
bus -> charger -> pack -> BT boost -> bus.

Table 9. Single faults.

| Row | Fault | Effect | Loop? | Bound and detection |
|---|---|---|---|---|
| F1 | K1 NC welded (cannot leave VBT) | On entry the pack stays on VBT; VCHG_V stays low | No | Firmware entry confirm (step 5) aborts. If firmware errs and powers the charger, the Ag105 runs into an open VCHG (D-BT-SQ off). Safe. |
| F2 | K1 NO welded (pack+ stuck on VCHG) | After exit VBT is fed only by R_PC (38 mA); BT channel unusable | No | Boot and exit checks see VCHG_V at the pack voltage; firmware refuses BT_REG. The vehicle is stranded on the FC; the Teensy stays powered. |
| F3 | K2 NC welded (pack- stuck on GND) while K1 transfers | In CHARGE the pack negative is on GND, which parallels the Ag105 sense again: the ML0227 regulation loss | No: VBT is unsourced and BT boost interlocked | Original bound (FC input, 23.4 W x 0.88 / 8.4 V = 2.45 A for a lossless boost) REFUTED as a hardware bound in review round 1: a bench supply on J-FC removes it, and ML0227 ran on a bench supply. Revised bound: the hardware charge-current ceiling and trip latch of section 10.5. CV regulation is kept only if the module senses voltage across Bat+ to Bat- (UNCONFIRMED). Detection: firmware plausibility of reg 0x06 (near 0) against the bus-side input power (G2 port); BQ29200 OVP (8.70 V, 2-4 s) returns the pack to RUN through Q_OVP; PACK_V OV in firmware. No direct hardware readback of pole B. |
| F4 | K2 NO welded (pack- stuck on VBATN) in RUN | The whole RUN return (up to 15 A) flows through F2 and the Ag105 sense, and through D_LR | No | F2 (4 A) opens; the return then flows through F3 and D_LR; F3 (2 A) opens. With both open, the BT boost and the logic lose their return and the Teensy browns out; all EN pull-downs act. Before F2 opens, the sense carries a current above the 4 A I_DIS figure (DS p.20) for the fuse clearing time; the sense rating is TODO(verify: Silvertel). |
| F5 | D_LR short | In CHARGE, GND is bonded to pack negative: same as F3 | No | Same as F3; F3 (2 A) may open if the cell current exceeds 2 A. |
| F6 | D_LR open | Each transfer interrupts the logic return for up to 15 ms; the Teensy resets | No | A reset releases the relay and opens the charger feeds. Commissioning gate B6 detects it. |
| F7 | Q1 drain-source short | Relays held in CHARGE regardless of firmware; BT channel unusable | No | G_K stays low, so Q6 and Q7 keep the charger feeds OFF: no charging occurs. VCHG_V at the pack voltage with pin 33 static gives a firmware fault. |
| F8 | Q1 open, coil open, R_S open | Relays never reach CHARGE | No | Entry confirm aborts. Safe. |
| F9 | Pump or C_H short to 3V3, or G_K held HIGH by a leak | Relays may hold CHARGE with the Teensy hung | No | Q_A/Q_B/Q_C still clamp G_K on any BT or MOT_PWR command; Q_OVP still acts. The hang protection of section 3.2 is lost. Detection: G_K is not read back (residual). |
| F10 | Teensy hang | Section 3.2 | No | Dynamic drive and Q6/Q7. Outputs other than the relay and the charger feeds need the RTWDOG (X9). |
| F11 | Firmware commands CHARGE while moving | Interlock: MOT_PWR HIGH clamps G_K | No | Q_C; the transfer cannot occur with MOT_PWR HIGH. |
| F12 | Firmware raises BT_REG or BT_BUS in CHARGE | Q_A/Q_B drop the relay with the charger live (X7 violated) | No | Break of at most 3.2 A at 8.4 V on NO (inside rating); R_PC-precharged NC make. Ag105 runs into an open VCHG. |
| F13 | D-BT-SQ short (VCHG to VBT) | In CHARGE, the pack is also on VBT; in RUN, VCHG is on the pack | No | In CHARGE the BT boost is interlocked off; in RUN the charger feeds are held OFF by Q6/Q7. A loop needs a second fault (Q6 or Q7 failure plus a firmware error). |
| F14 | R_PC short | VBT joined to PACK+ in CHARGE | No | Same as F13 in CHARGE. |
| F15 | BQ29200 OUT stuck high | Charging impossible | No | BAL_OVP readback shows it. Safe. |
| F16 | BQ29200 OVP dead | Overcharge protection reduced to the Ag105 CV loop and firmware PACK_V OV | No | Two layers remain while the sense is valid. |
| F17 | Vibration drop-out of a coil in CHARGE | As F12 | No | As F12. |
| F18 | Flying-lead short (VLOGIC, VCHG or VBATN lead) | Pack fault current into the short | - | F1, F4 and F2 respectively; F0 at the pack as backup. Fuse parts are TODO(verify). |
| F19 | Firmware moves the relay with VCHG-IN live (sequencing error) | Up to 15 ms with pole A on VCHG and pole B on GND: a bounded sense bypass | No | VBT is unsourced, so no loop; the D-BC-FC turn-on delay (8 ms) plus the Ag105 start (65-170 ms) exceed the operate time if the feed was opened in the same tick. |

## 6. HR1-HR5 status

Table 10 gives the status of each hard requirement for IC6.

Table 10. Hard-requirement status.

| ID | Status | Reason |
|---|---|---|
| Post-review (section 10.6) | HR1 FAILS; HR2 FAILS against H5 (1.5 A floor), BENCH for standstill charging at 1.0 A; HR3 PROVEN_CALC; HR4 PROVEN_CALC conditional on the section 10.5 hardware ceiling, BENCH for its trip curve; HR5 PROVEN_CALC conditional on the latch and ordering fixes, BENCH for gate B7 | The original rows below are superseded. |
| HR1 Regen | **FAILS** | In RUN the pack has no path from the charger (K1 NO open, D-BT-SQ off). CHARGE requires MOT_PWR LOW (Q_C), so no braking can occur in CHARGE. A per-event transfer would be limited by the Ag105 start (0.69-0.79 s total against a 19-47 ms first pulse). |
| HR2 FC charging | **BENCH** | Standstill windows are within the governor at code 6 (1.17 A against 1.25 A, section 4.6). A purge pauses the charge without a Teensy brownout. The firmware purge policy, the Ag105 restart time after each purge, I_5V and the 0.88 efficiency point are unmeasured. Charging while driving is not provided. |
| HR3 No loop | **PROVEN_CALC** | In CHARGE: VBT is unsourced except through R_PC (38 mA maximum), D-BT-SQ isolates VCHG from VBT in both directions (RT1987 DS-00 p.14), and Q_A/Q_B hold the BT boost and BT_BUS off. In RUN: Q6/Q7 hold both charger feeds off. No single fault in Table 9 forms a loop. Conditional on rework R5 and the hardware permits being built as specified. |
| HR4 No runaway | **BENCH** | With pole B correct, the Ag105 sense carries the cell current, so its CC loop and its set-plus-200 mA trip (DS p.18) are effective. The sense resistance and the module's behaviour with an external VLOGIC load on Bat+ are unmeasured (gates B1, B2). The single faults F3 and F5 restore the sense bypass; their bound is the FC input power, not a charger-side ceiling. |
| HR5 Fail-safe inhibit | **PROVEN_CALC** | Unpowered, reset, hung or static pin 33: relays in RUN through R_H; charger feeds OFF through RT1987 EN pull-downs and Q6/Q7. No autonomous charge from POR: the charger has no power path in RUN. Gates B7 and B12 must confirm the timing and the OQ-7 pull-downs. |

The prior re-spin objections are engaged as follows:

1. **The bus needs another source during the window.** True. At standstill the bus carries only the charger and the
   aux load, and a purge pauses the charge. Charging while driving is not attempted.
2. **The Teensy browns out.** Resolved by VLOGIC ahead of the relays and D_LR across K2 NC (section 4.5).
3. **No pack buffering.** True during a window; the window is standstill-only and hardware-interlocked.
4. **Switch transitions per regen event.** Not attempted. This is the reason HR1 fails.
5. **References move.** The BQ29200 shift is in the safe direction during charge; V_batt is supplemented by PACK_V;
   the INA253s do not move (section 4.7).

## 7. Rework, parts list and cost

### 7.1 Rework steps on the manufactured board

The following steps are in the recommended order. Each step that cuts copper must be photographed and recorded as a
never-rotated bodge record.

1. **R1, lift Ag105 VBat- (pins 14, 15).** Cut each module pin above the board, one at a time, as
   `charger_eval_2026-11-05/incident.md` recommends. Do not desolder the module (solid GND pads, lifted-pad risk).
   Insulate the board-side stubs, which remain on GND. Solder an 18 AWG lead to both module-side pin stubs (VBATN).
   The module standoff height is BENCH (gate B13).
2. **R5, disable D-BT-SQ.** Cut the trace from the D-BT-SQ EN pad (pin 5) to the Teensy pin-32 net and tie EN to
   an adjacent GND pad (POVP and GND are on GND). The exact trace segment is TODO(verify: BRD). Do not remove the
   RT1987.
3. **R3, re-feed the LM1084.** Cut the top-layer VBT segment between the via at (57.66, 34.54) and REG-5V pad 3 at
   (59.18, 39.57). CIN-5V is at (61.72, 39.62), so it appears to stay on the regulator side of the cut
   (UNCONFIRMED; verify the trace topology before the cut). Solder the VLOGIC lead to pad 3.
4. **R2, VCHG lead.** Solder an 18 AWG lead to the C-D11 pad on the VCHG pour, or to the Ag105 VBat+ pins 18/19.
5. **R6, charger-feed permits.** Cut the pin-31 net between the J2 header and D-BC-FC EN, and the pin-30 net between
   the header and D-BC-RG EN, and bridge each cut with 1 kOhm. Solder the Q6 and Q7 drain wires to the EN side. The
   trace locations are TODO(verify: BRD).
6. **R4, balance lead.** Remove the pack-negative wire from J-BL pin 3 in the harness and insulate it (X1). This also
   removes the parallel return path that the incident analysis rated as a fire hazard.
7. **Switch board.** Build K1, K2, Q1, the pump, the interlock FETs, R_PC, D_LR, the dividers and the fuses on a
   separate board in the J-BT harness. Bring the signal wires (pins 33, 16, 17, 22; taps on the pin 4, 28 and 29
   nets; 3V3; GND) from the J1/J2 header contacts.
8. **BQ29200 OUT.** Solder a fine wire to the BQ29200 pin-8 pad (no copper on the board; SON package). This is
   fine-pitch work and is BENCH.
9. **Harness.** Fit F0 at the pack. Route PACK+ and PACK- to the switch board and the four outputs (VBT, GND, VCHG,
   VBATN) to J-BT 1, J-BT 2 and the two flying leads.

### 7.2 Parts list

Table 11 lists the parts. Prices were not fetched; every price is TODO(verify: distributor).

Table 11. Parts list.

| Qty | Ref | Part |
|---|---|---|
| 2 | K1, K2 | TE T9A, 1 Form C, 5 VDC 1 W coil (ordering code TODO(verify: TE)) |
| 1 | Q1 | onsemi NTR4501NT1G |
| 7 | Q_A, Q_B, Q_C, Q_OVP, Q5, Q6, Q7 | onsemi BSS138 |
| 3 | D_LR, D_FW1, D_FW2 | onsemi MBRS540T3G |
| 2 | D_P1, D_P2 | onsemi BAT54LT1G |
| 2 | R_S1, R_S2 | 17 Ohm, 2 W |
| 1 | R_PC | 220 Ohm, 1 W |
| 2 | R_30, R_31 | 1 kOhm |
| 3 | Pull-ups and pull-downs | 100 kOhm (R_H, N_INV pull-up, Q_OVP gate) |
| 1 | Q_OVP gate series | 10 kOhm |
| 2 + 1 | Dividers | 16.2 kOhm / 10 kOhm pairs; 100 kOhm / 47 kOhm pair |
| 2 | C_P, C_H | 1 uF, X7R |
| 3 | ADC filters | 10 nF |
| 5 | F0-F4 | Fuses and holders as Table 4 (TODO(verify)) |
| - | Wire and connectors | 14 AWG pack leads, 18 AWG flying leads, terminal blocks, perfboard, enclosure |

The parts are two power relays, small-signal semiconductors, passives and fuses. In category terms this is far
below the USD 505-540 of the BQ25798 path (`facts_prior` section 11); a priced total is TODO(verify: distributor).

## 8. Firmware, telemetry and HIL impact

### 8.1 Firmware

1. Pin definitions for 33, 16, 17 and 22 (after the CSV amendment); pin 33 OUTPUT LOW early in `setup()`.
2. A new charge mode at standstill, implemented first as a State-98 command and then as an Idle sub-mode, so the
   five-state structure stays intact. It owns the sequences of section 3.2.
3. The pump toggle: one `digitalWriteFast()` per loop iteration, after `detectFaults()`, only while the charge mode
   holds. No hardware PWM.
4. No blocking operation while the charge mode holds (EEPROM commit, SD close, `Ethernet.begin()`).
5. `chargerHasPower()` gains the relay state; `AG105_VBATN_ISOLATED` set to 1 means "VBat- reworked and the pack is
   on the Ag105 port", and the Run regen branch must keep REGEN LOW regardless (the hardware Q7 already does).
6. UV_BATT and OV_BATT move to PACK_V with a filtered OV check. V_batt (pin 25) stays as a VBT readback.
7. A purge-pause policy for the charge mode: UV_BUS and the fw v33b gate must not latch on a purge while the bus
   carries only the charger.
8. New faults: relay-position mismatch (VCHG_V against the commanded state), K2-weld plausibility (reg 0x06 against
   the bus input power), BAL_OVP asserted.
9. `BT_SEQUENCE_ENABLE` writes are removed; pin 32 becomes undriven.
10. State 99 ordering of section 3.2; the Phase-0/1 drains are removed or accepted as blocked.
11. RTWDOG (X9) remains required for the outputs that the dynamic drive does not cover.

### 8.2 Telemetry

`switch_state` has two spare bits (`facts_firmware` section 7). Bit 6 can carry "pump active" and bit 7 "pole A
confirmed". PACK_V needs a new field, which is a protocol change (v5; a proposal already exists in the repository).
The protocol-bump procedure applies.

### 8.3 HIL

- The simple plant (`tools/hil_plant_sim.py`) keeps the pack permanently connected and ignores `SW_BT_SEQ`. It needs
  a relay state, a VBT node separate from the pack, an Ag105 battery-port model, the logic supply on the pack, and a
  purge collapse on an FC-only bus with charger restart.
- The hi-fi engine (`tools/hil_electrical.py`) models `BT_SEQ` as a pack-to-BT-boost input switch. This is close to
  pole A of IC6 (RUN connects the pack to the BT boost input), with the opposite command polarity. It can be
  repurposed as the K1 model.
- The 40-byte injection frame needs fields for PACK_V, VCHG_V and BAL_OVP, and the observation frame's aux byte is
  full. Both frame layouts change.

## 9. Open questions and bench gates

Table 12 lists the bench gates in the order in which they should run. Gates B1, B4 and B13 need no rework and decide
whether the rest is worth doing.

Table 12. Bench gates.

| Gate | Question | Pass condition |
|---|---|---|
| B1 | Ag105 sense resistance R_s, pins 14/15 to 16/17, out of circuit or on a spare module (X8) | Value recorded; sets the BQ29200 and PACK_V offsets |
| B2 | Ag105 powered with a battery already on its port: start time, GENSTAT sequence, reg 0x06 with an external load on Bat+ | Charges at the set cell current; the external load does not trip OC or prevent termination |
| B3 | Ag105 response to a battery disconnect mid-charge (F12, F17): VCHG overshoot, status | VCHG stays below the D-BT-SQ and C-D11 ratings; module returns to detection |
| B4 | T9A contact resistance at 10 A, both contacts, and temperature rise at 7.2 A continuous | <= 10 mOhm per contact; temperature inside the TE curve |
| B5 | Coil operate voltage hot (7.0 V supply after 1 h energized); release time with the freewheel diode | Operates at 7.0 V hot; release time recorded |
| B6 | 5 V and 3V3 rails during 100 transfers with D_LR fitted | No Teensy reset; droop recorded |
| B7 | Frozen-loop test: time from the last toggle to relay release and to the Q6 pull-down | Within 77-139 ms plus release; FC_CHARGE EN low |
| B8 | I_5V and LM1084 temperature at 8.4 V | Budget of section 4.6 holds |
| B9 | VBT capacitance and the K1 NC make with and without R_PC | Peak VBT below 20 V; R_PC make current-free |
| B10 | Purge during a window: charger restart time, firmware pause policy | No fault latch; restart time recorded |
| B11 | BQ29200 OUT trip: raise one balance tap above 4.35 V with a bench supply | Relay returns to RUN within the CD delay |
| B12 | OQ-7: which charger-feed EN nets carry the 10 kOhm pull-down | Both D-BC-FC and D-BC-RG pulled down |
| B13 | Ag105 pin cut feasibility (standoff height, pin access) | Pins 14/15 cut without damage |
| B14 | K2-weld simulation: jumper K2 NC closed during a window | Firmware plausibility trips; current stays at or below the FC bound |

Table 13 lists the open questions that no bench gate in this dossier closes.

Table 13. Open questions.

| Item | Status |
|---|---|
| T9A form C NC carry current above 10 A | TODO(verify: TE) |
| Ag105 CV voltage sense point (Bat+ to Bat- or to Vin-), which decides whether CV survives fault F3 | TODO(verify: Silvertel) |
| Ag105 behaviour of the undocumented internal switch in parallel with the sense (DS Fig.1) | TODO(verify: Silvertel) |
| Ag105 sense current rating in the discharge direction (fault F4) | TODO(verify: Silvertel) |
| TPS61288 VIN absolute maximum (20 V read from a scrambled extraction) | TODO(verify: SLVSFP3C rendered p.5) |
| Fuse part numbers and ratings | TODO(verify: fuse vendor) |
| Teensy VUSB-VIN pad state | BENCH (`facts_board` section 6.2) |
| Pack datasheet: maximum charge current, protection board | Missing primary |
| Whether a regen requirement can be met by any IC6 variant | Not by this design; HR1 FAILS |

## 10. Review round 1 adjudication

### 10.1 Method

Three adversarial reviewers (fault, electrical and system lenses) reviewed sections 0-9. This section records a
verdict for each finding: ACCEPTED (the design is changed) or REFUTED (with the evidence). Each verdict was checked
against the primaries in this folder and in the repository. Findings that several reviewers raised are adjudicated
once and cross-referenced. Finding identifiers are F- (fault lens), E- (electrical lens) and S- (system lens);
M is major and n is minor.

The following primaries were re-read for this adjudication:

- operator rulings 1, 5, 6 and 9, and requirement rows H5 and H8 (`facts_prior.md` sections 2.2 and 3);
- the staged bring-up P0-P3 and the build flags (`facts_firmware.md` sections 1 and 2.3);
- the 2026-08-03 change of the motor-node connect doctrine (`teensy_controller.ino`:860-881 and 972-981);
- the lazy-configuration write in `pollAg105()` (`teensy_controller.ino`:16190-16205);
- the Ag105 load-during-charge clause (DS V1.1 p.9 and p.16 Figure 10, via `facts_ag105.md` section 1.4);
- the Ag105 current-select table (`Ag105_Table4_Charge_Current_Select.json`);
- the CB_EN wiring (`facts_board.md` section 5 item 4).

A replacement relay candidate was found by web search: the Panasonic CB1 automotive relay, 1 Form C, rated 40 A NO
and 30 A NC at 14 VDC, with 15 mOhm maximum contact resistance by voltage drop at 6 VDC and 1 A (Panasonic ASCTB220E,
read only from a third-party copy at datasheet.eeworld.com.cn/view/6582045.html). The 12 V coil data (about
103 Ohm, 117 mA, 1.4 W) come from distributor listings (Octopart, Buerklin). Every CB1 value is therefore
TODO(verify: Panasonic ASCTB220E, rendered original).

### 10.2 Requirement-level findings

Table 14 adjudicates the findings that decide whether IC6 can be the overall winner.

Table 14. Requirement-level findings.

| ID | Finding | Verdict | Evidence and action |
|---|---|---|---|
| S-F1 (= F-M8, E-M1) | HR1 regen fails by construction; ruling 1 makes regen a hard requirement | **ACCEPTED** | Ruling 1 (`facts_prior.md` section 3 item 1) makes regen and FC charging "both hard requirements", and a design that "catches only the tail of regen bursts, fails". Section 4.4 and Table 10 already record HR1 FAILS. Regen occurs while driving, and driving needs the pack on VBT; the literal two-leg transfer places the pack on VBT or on the Ag105 port, never on both. The entry timeline (688-793 ms) cannot meet a 19-47 ms first pulse. No fix inside IC6 exists. **IC6 is withdrawn as a requirement-meeting design** and retained as a standstill-only fallback (IC6-R1, section 10.5), conditional on an explicit operator ruling that relaxes ruling 1 to FC charging only. |
| S-M1 | The FC-only purge ride-through conflicts with ruling 6 | **ACCEPTED** | Ruling 6 (`facts_prior.md` section 3 item 6) requires that "a predicted purge interrupts the window so the battery is back on the bus before the dip". Section 3.2 chose the ride-through as primary. IC6-R1 adopts the ruling-6 policy and costs it in full (section 10.5.4). |
| S-M2 | The FC boost restart after a purge, with the charger feed closed, is unbounded against OC_FC 1.4 A | **ACCEPTED** | No bound was given, and gate B10 measured only the restart time. IC6-R1 opens FC_CHARGE before every predicted purge, and within 2 ms of an unpredicted bus sag below 13.5 V. Gate B10 now records the peak I_fc against OC_FC 1.4 A. |
| S-M3 | The FC budget was compared with a governor ceiling that is inert single-source | **ACCEPTED** | CLAUDE.md fw v28 addendum: "the fw v26 ceiling is inert single-source; OC_FC latches on one raw sample". The window is FC-only. The budget is re-based on the H-20 P_MAX bus equivalent (about 1.247 A) and OC_FC 1.4 A (section 10.6). The reviewer's pessimistic case is reproduced: (8.4 + 3.36 + 3.36) W / 0.85 = 17.8 W, which is 1.11 A at 16 V and 1.26 A with the 0.15 A aux load. That exceeds 1.247 A. |
| S-M5 | The firmware, protocol and HIL scope is large and reverses the doctrine that keeps MOT_PWR closed in Idle | **ACCEPTED in part** | The scope list is correct (section 8). IC6-R1 removes the doctrine reversal: MOT_PWR stays closed through a window (section 10.5.2), so `doState1()` keeps its present behaviour and no P0 re-run is needed. The remaining scope stands and is recorded as a cost. |
| (new) | H5 requires at least 1.5 A at 8.4 V within the FC budget | **Raised by this adjudication** | Requirement row H5 (`facts_prior.md` section 2.2). Section 10.6 shows that code 4 (1.5 A) exceeds the P_MAX bus equivalent with the IC6 coil load. HR2 therefore fails H5. |

### 10.3 Safety and fault-lens findings

Table 15 adjudicates the fault-lens findings. The electrical and system findings that duplicate them are named in
the first column.

Table 15. Fault-lens findings.

| ID | Finding | Verdict | Evidence and action |
|---|---|---|---|
| F-M1 (= E-M5, S-M4) | Pole B has no position readback; a welded K2 NC, a shorted D_LR or a re-contacting cut pin-14/15 stub restores the ML0227 sense bypass; the only hardware ceiling is a 4 A fast fuse | **ACCEPTED** | VBATN connects to GND through the Ag105 sense in every K2 position (DS V1.1 Fig.1 p.3), so a DC voltage readback cannot distinguish the positions. The cut-stub case was missing from Table 9. IC6-R1 adds (a) a hardware charge-current ceiling: a shunt and comparator in the VCHG lead that set a trip latch; (b) a second shunt in the VBATN lead, which gives an active pole-B check (section 10.5.3); (c) removal of the board-side pin-14/15 stubs flush with the pads, potting of the cut, and a new fault row F20. |
| F-M2 (= S-n3) | A K2 NO weld in RUN shows up only as a brown-out while driving, after F2 and F3 open; the BQ29200 VC1 path then carries ESD-structure current | **ACCEPTED** | The mechanism follows from Table 9 row F4. With the VBATN-lead shunt of IC6-R1, a K2 NO weld is detected at standstill: in RUN the VBATN lead must carry 0 A, but a weld makes it carry the whole logic return (at least I_5V). Firmware checks this at boot and after every window exit, and refuses BT_REG on a non-zero reading. An in-motion brown-out then needs a weld that forms without a transfer, which is not a credible relay mechanism (UNCONFIRMED). The current through RB3 (260 Ohm) and RB1A (100 Ohm) into the BQ29200 pins after both fuses open is recorded as UNCONFIRMED stress. |
| F-M3 (= E-n4) | A single RUN return; NC contact chatter can force the return through D_LR and open F3 silently; the next transfer then resets the Teensy | **ACCEPTED** | With the T9A at 75 mOhm, the K2 NC drop at 7.2 A is 0.54 V, which exceeds the MBRS540 forward voltage, so D_LR shares the return and a 2 A fuse can open. IC6-R1 replaces the relay (CB1, NC 30 A, 15 mOhm maximum: 0.25 V at 16.46 A, TODO(verify)). F3 is re-sized to 5 A slow-blow, matching the 5 A MBRS540 average rating (MBRS540T3/D p.2). Firmware records the reset cause and the commanded relay state; a reset during a transfer latches "transit return suspect" and blocks further windows. A direct D_LR readback is not possible, because K2 NC shorts D_LR in RUN. |
| F-M4 (= E-n8) | Every window exit re-closes MOT_PWR onto a drained motor node (Death-5 class); a firmware error can close it mid-window | **REFUTED in part, ACCEPTED in part** | The Death-5 low-voltage pre-charge doctrine was superseded on 2026-08-03 (`teensy_controller.ino`:870-878 and 972-981): "a discharged motor node at a regulated bus is the sanctioned connect", through the D-MT-EN soft-start at P3. A connect onto a regulated bus is therefore not a hot-plug in the project's own doctrine. The stack-OCV argument applies only to P0, where MOT_PWR is LOW. However, the per-window repetition of P3 on an FC-only bus is a real cost. IC6-R1 keeps MOT_PWR closed through the window (section 10.5.2), so no window exit connects the motor node. The dossier's step-5 rationale was corrected in the body. |
| F-M5 | The K1 NO make closes the pack onto VCHG at about 30 A peak, against the H8 limit of 1.0 A, and feeds contact weld | **ACCEPTED** | Rule H8 (`facts_prior.md` section 2.2) "applies to every new switch that closes onto capacitance". Z0 = sqrt(1 uH / 15 uF) = 0.26 Ohm, and 8.4 V / 0.26 Ohm = 32 A (harness inductance and capacitance UNCONFIRMED). IC6-R1 adds a switched VCHG pre-charge path of 22 Ohm, with a peak of 0.38 A (section 10.5.2). |
| F-M6 | The charge-current write in step 7 cannot execute on an unpowered Ag105; `pollAg105()` re-writes 2.5 A after every power loss; 2.5 A exceeds the FC budget | **ACCEPTED** | CLAUDE.md section 3 and `teensy_controller.ino`:16190-16192 ("Write the 2.5A / 2S-8.4V profile once per power session"). At 2.5 A the input is about (21 + 5.9) W / 0.88 = 30.6 W, above the 23.4 W stack P_MAX. IC6-R1 rewrites the configuration sequence (section 10.5.4). |
| F-M7 (= E-n6 part) | The hardware OVP action is non-latching; a firmware fault can re-enter CHARGE cyclically | **ACCEPTED** | Q_OVP clamps G_K only while BQ29200 OUT is high. IC6-R1 adds a trip latch that the OVP and the current comparator set, and that only a firmware clear resets (section 10.5.3). |
| F-n1 (= E-M6) | Under a hang, Q1 (V_GS(th) 0.65-1.2 V) can release before the Q5/Q6/Q7 permit (0.8-1.5 V) drops; two armatures can skew | **ACCEPTED** | The threshold windows overlap (NTR4501N/D p.2; BSS138 p.2), as section 3.2 already conceded. IC6-R1 inserts a Schmitt buffer on G_K: the permit drops at the first threshold crossing, and the coil drive follows through a fixed RC delay of about 50 ms and a second Schmitt stage (section 10.5.3). |
| F-n2 (= E-n2) | Q1 runs linear for tens of ms during a hang, and contact force falls under load | **ACCEPTED** | The peak dissipation is V^2/(4R) = 8.4^2 / (4 x 21 Ohm) = 0.84 W (recomputed by the electrical reviewer). The Schmitt stage of F-n1 switches Q1 hard. |
| F-n3 (= S-n1) | An I2C stall or any loop block longer than about 70 ms drops the relay under charge current | **ACCEPTED** | The 77 ms hold time (section 2.3) can be shorter than a Wire stall on an unpowered slave (timeout UNCONFIRMED). With the F-n1 ordering, the permit drops first, so the break occurs with the charger input removed. Firmware sets a Wire timeout of 20 ms or less while CHARGE holds (Teensy Wire timeout API TODO(verify: PJRC)). |
| F-n4 | No reverse-polarity protection or keying on the four harness outputs | **ACCEPTED** | Ag105 DS p.18 states no battery-reversal protection and recommends D1 (DST1550S) and a 10 A slow-blow fuse (`facts_ag105.md` section 4.1). IC6-R1 uses four mutually non-mateable keyed connectors and the DS p.18 D1 arrangement on the battery port (placement TODO(verify: Ag105 DS p.18 figure)). |
| F-n5 | The Q_A, Q_B and Q_C taps fail open silently | **ACCEPTED** | IC6-R1 deletes Q_C (section 10.5.2). For Q_A and Q_B, firmware runs a tap self-test at boot: with the pump running and the 12 V coil supply disabled, it raises BT_REG and then BT_BUS and confirms each time that the G_K readback falls. This uses one more analog pin (pin 23). |
| F-n6 | The boot check "VCHG_V < 2 V" false-trips after a warm reset from CHARGE | **ACCEPTED** | tau = 26.2 kOhm x 10 uF = 0.262 s, and ln(8.4 / 2) x 0.262 s = 0.38 s, longer with the Ag105 output capacitance (TODO(verify: Silvertel)). IC6-R1 latches the K1-NO-weld fault only if VCHG_V stays within 0.3 V of PACK_V for 2 s with the pre-charge FET off. |
| F-n7 | The State-99 Phase-0/1 drains are blocked in RUN, and their purpose is not analysed | **ACCEPTED** | The drains discharge VBUS and V-MOT into the charger in Error (`facts_firmware.md` section 2.1). In RUN, IC6-R1 blocks that path by design. VBUS and V-MOT then discharge only through the VESC idle load and the board dividers. The discharge time is BENCH (new gate B15). |
| F-n8 | VLOGIC has no undervoltage cutoff; an over-discharged pack cannot be recovered on-board | **ACCEPTED** | Below 6.5 V the LM1084 does not regulate (SNVS037H section 5.5). Firmware UV_BATT on PACK_V (7.4 V floor, CLAUDE.md fw v30) stops traction but not the logic load. IC6-R1 records a hardware low-voltage disconnect of VLOGIC as required future work (part TODO(verify)). Recovery of a pack below 2.7 V/cell is outside the scope of this fallback. |
| F-n9 | The pack protection board and datasheet are missing; the 53 A K1 NC inrush estimate rests on a scrambled TPS61288 extraction | **ACCEPTED** | The Ag105 does not support bare cells (DS p.18 section 5.1). The pack datasheet is already an open item (Table 13). R_PC removes the K1 NC make event; the 20 V figure remains TODO(verify: SLVSFP3C rendered p.5). |
| F-n10 | CB_EN is Teensy-driven, not hardwired; the bottom-cell bleed current returns through K2 and the sense | **ACCEPTED** | `facts_board.md` section 5 item 4: CB_EN is on net CB-DISABLE to Teensy pin 9, active low. With CBAL_DISABLE LOW, the bottom-cell bleed (VMID through RB1A to VC1_CB and GND) returns to pack negative through the Ag105 sense in CHARGE, which offsets reg 0x06 by the bleed current (magnitude UNCONFIRMED). IC6-R1 drives CBAL_DISABLE HIGH (OVP only) during a window; the BQ29200 OVP function on OUT does not depend on CB_EN. |

### 10.4 Electrical and system findings not covered above

Table 16 adjudicates the remaining findings.

Table 16. Remaining electrical and system findings.

| ID | Finding | Verdict | Evidence and action |
|---|---|---|---|
| E-M2 | The RUN traction current flows through the 10 A NC side of the T9A; the bench peak is 16.46 A | **ACCEPTED** | TE T9A Rev. 0815 p.1 (Form C 20 A NO / 10 A NC, confirmed by the reviewer's search) against `facts_prior.md` section 9. IC6-R1 uses the Panasonic CB1 (30 A NC, TODO(verify)). Its 12 V coil needs a 12 V supply, which IC6-R1 takes from a small boost converter on VLOGIC. VBUS is not used, because a purge would drop the coil. Gate B4 becomes a go/no-go gate before any rework, and windows run only in a build with OC_BT active or with an equivalent pack-current bound. |
| E-M3 | With the 75 mOhm data-sheet contact resistance, the LM1084 input falls to 5.91 V at 15 A | **ACCEPTED** | 7.4 - 0.36 - 1.13 = 5.91 V, below 6.5 V (SNVS037H section 5.5). Table 17 (section 10.5.5) recomputes the headroom with the CB1 15 mOhm maximum. |
| E-M4 | The logic and coil load sit on the Ag105 output during charge, outside the datasheet configuration; the idle logic return flows backwards through the sense | **ACCEPTED** | Ag105 DS p.9 refers a load that runs during charge to section 3.2, and DS p.16 Figure 10 feeds it from the input side (`facts_ag105.md` section 1.4). Moving the load to the input side costs more FC power: the LM1084 from 16 V dissipates (16 - 5) V x I_5V, which is 3.3 W at 0.3 A. IC6-R1 keeps the load on VBat+ as a recorded datasheet departure. Gate B2 gains the reviewer's cases: the external load outside the sense, about 0.7 A of reverse sense current at each restart, and about 1.7 A of total output at code 6. If gate B2 fails, the fallback is not viable on the Ag105. |
| E-n1 | The T9A coil table and the 75 mOhm figure were not re-verified | **ACCEPTED** | Moot after the relay change; the CB1 values carry the same TODO. |
| E-n3 | The pump capacitor is driven directly by pin 33 | **ACCEPTED** | A 330 Ohm series resistor is added: 330 Ohm x 0.5 uF = 0.17 ms, well below the 1.13 ms half-period. The first-edge pin current is then at most 3.3 V / 330 Ohm = 10 mA (PJRC per-pin guidance UNCONFIRMED). |
| E-n5 | Rework R3 needs a local LM1084 input capacitor | **ACCEPTED** | SNVS037H requires input capacitance at the device, and the side of CIN-5V on the cut is UNCONFIRMED. A 10 uF ceramic is added from REG-5V pad 3 to GND. |
| E-n6 | The BQ29200 OUT high level at VDD = 8.4 V is lower than the 10 V test figure; firmware must latch on BAL_OVP | **ACCEPTED** | SLUSA52C section 7.5 specifies V_OUT at its own test conditions. The Q_OVP gate still exceeds the 1.5 V BSS138 maximum threshold. The hardware latch of F-M7 replaces a firmware-only latch. The BAL_OVP divider scaling is labelled pessimistic. |
| E-n7 | Table 8 and section 4.7 route the idle logic return through D_LR; it flows through the sense | **ACCEPTED** | R_s (milliohm class, BENCH) times 0.7 A is far below the Schottky forward voltage, so the sense carries the return. Table 8 and section 4.7 were corrected in the body. |
| E-n9 (= S-M4) | The F3 bound of "about 2.5 A" disappears on a bench supply | **ACCEPTED** | 23.4 W x 0.88 / 8.4 V = 2.45 A, for a lossless boost. ML0227 ran on a bench supply (`facts_prior.md` section 4.1). Table 9 row F3 was corrected; the hardware ceiling of IC6-R1 replaces the bound. |
| S-n2 | The pump settles G_K near 2.6 V, which droops to 2.35 V, below the 2.5 V point of the NTR4501N R_DS(on) specification | **ACCEPTED** | NTR4501N/D p.2. With the Schmitt buffer of F-n1, Q1 is driven from the 3V3 rail, which is above the 2.5 V rating point. |
| S-n4 | The charge window needs a Pi command in Idle that the 22-byte command packet does not carry | **ACCEPTED** | `chargingControl()` runs only in Run, and `charge_goal` is consumed there (`facts_firmware.md` section 3). A window-request field is a command-protocol extension and must go through the protocol-bump procedure. |
| S-n5 | The coils draw 2.6-3.4 W for the whole window; no economizer can be specified; the hot-coil margin is 11 % | **ACCEPTED** | The CB1 coil (1.4 W each, TODO(verify)) is supplied at a regulated 12 V, so the operate margin no longer depends on the pack voltage. The coil power is about 2.8 W plus the converter loss (efficiency TODO(verify)), and it is charged to the FC budget in section 10.6. |
| S-n6 | VC1 references PCB GND without the balance negative and under-reads the bottom cell in RUN by the K2 NC drop | **ACCEPTED** | At the CB1 15 mOhm maximum, the error is 0.25 V at 16.46 A (1.1 V with the T9A at 75 mOhm). Firmware must not use the BQ29200 for an imbalance check; the OVP function is unaffected. |

No finding was refuted in full. Finding F-M4 was refuted in its Death-5 rationale only.

### 10.5 Revised fallback design IC6-R1

#### 10.5.1 Scope

IC6-R1 is the standstill-only FC-charging fallback. It applies only if the operator relaxes ruling 1 to "FC charging
only". The topology of section 1.2 is kept: two changeover poles move PACK+ from VBT to VCHG and PACK- from GND to
VBATN, and VLOGIC is taken ahead of both relays. The changes below replace the corresponding body text.

#### 10.5.2 Power-path changes

1. **Relays.** K1 and K2 are Panasonic CB1 1 Form C relays with 12 V coils (30 A NC, 40 A NO, 15 mOhm maximum;
   TODO(verify: Panasonic ASCTB220E)). The coils run from a 12 V boost converter on VLOGIC (part TODO(verify:
   vendor)). Q1 stays the low-side coil switch.
2. **MOT_PWR stays closed through a window.** Q_C is deleted. The motor is held by `commandMotorCurrent(0)` with a
   wheel-speed-zero precondition, which is the present Idle doctrine. Benefit: no motor-node connect occurs per
   window. However, the VESC sits on an FC-only bus during the window, and the hardware no longer forbids a transfer
   while MOT_PWR is HIGH. A traction command in CHARGE then loads an FC-only bus, which latches UV_BUS or OC_FC and
   returns the relay to RUN through State 99.
3. **VCHG pre-charge.** A P-channel MOSFET Q_PV in series with 22 Ohm, 1 W connects PACK+ to VCHG. A 100 kOhm resistor
   pulls its gate to PACK+ (OFF by default); a BSS138 driven from Teensy pin 10 turns it on. The peak current is
   8.4 V / 22 Ohm = 0.38 A, which meets H8. Q_PV is not a permanent keep-alive (ruling 9); it is ON for at most 100 ms
   per entry.
4. **Fuses.** F3 becomes 5 A slow-blow. F4 (VCHG lead) stays as the wiring fuse; the current ceiling of section
   10.5.3 is the functional limit.
5. **Pin 14/15 stubs.** The board-side stubs are cut flush with their pads, and the cut is potted. New Table 9 row
   F20 (stub re-contact) is bounded by the ceiling and detected by the pole-B check.
6. **Reverse polarity.** Four keyed, mutually non-mateable connectors, and Ag105 DS p.18 D1 (DST1550S) on the battery
   port.

#### 10.5.3 Control and protection changes

1. **Charge-current ceiling.** A 20 mOhm shunt in the VCHG lead feeds a high-side current-sense amplifier and a
   comparator (parts TODO(verify: TI or ADI data sheet); the common-mode range must cover 0-9 V). The comparator trips
   at 2.5 A, which is 1.5 x the 1.7 A nominal output at code 6 (1.0 A cell current plus about 0.7 A of coil-converter
   and logic load). The amplifier output also goes to pin 20 (I_VCHG). The ML0227 current (11-13 A) is about 4.6 times
   the trip level.
2. **VBATN shunt.** A second 20 mOhm shunt in the VBATN lead, with a bidirectional amplifier, goes to pin 21
   (I_VBATN). In CHARGE it reads the cell current; in RUN it must read 0 A.
3. **Trip latch.** A D flip-flop (part TODO(verify: vendor)) is set by the current comparator or by BQ29200 OUT. An RC
   network on its preset input sets it at power-up, so CHARGE is forbidden until firmware clears it. Its output pulls
   the charger-feed EN nets low at once (through Q6/Q7) and clamps the coil drive. Firmware clears it through pin 34,
   only with pin 31 LOW and the relays in RUN. Pin 35 reads it back.
4. **Release ordering.** A Schmitt buffer powered from 3V3 squares G_K. Its output drives the permit (Q5/Q6/Q7)
   directly, and drives Q1 through an RC delay of about 50 ms and a second Schmitt buffer. The charger feed therefore
   drops about 50 ms before the coil current is removed (parts TODO(verify: vendor); gate B7 confirms the order with a
   scope). Residual: a loss of 3V3 (for example, F1 open) removes the charger feed and the coil drive together; that
   break is bounded by the ceiling, and its VCHG overshoot is gate B3.
5. **Pump.** A 330 Ohm resistor is fitted in series with C_P.
6. **G_K readback.** Pin 23 reads G_K for the Q_A/Q_B tap self-test (F-n5).

#### 10.5.4 Firmware sequence changes

1. **Configuration.** The window code (default code 7, 0.75 A; section 10.6) is a firmware variable. `pollAg105()`
   writes reg 0x01 = 0x08 and reg 0x00 = window code once the Ag105 ACKs, without the 2.5 A default, and only when the
   read-back value differs (EPROM endurance TODO(verify: Silvertel)). Both registers are read back and must match
   before the window counts as valid. No ACK within 2 s aborts the window. Because the value persists in EPROM, the
   first detection cycle of each later power session starts at the window code.
2. **Entry.** The preconditions of section 3.2 apply, plus: trip latch cleared, I_VBATN = 0 A in RUN, CBAL_DISABLE
   HIGH. Then BT_BUS LOW and BT_REG LOW; Q_PV ON until VCHG_V is within 0.3 V of PACK_V; pump ON; confirm VCHG_V;
   Q_PV OFF; confirm that VCHG_V holds; then `assertFcChargeEnable(true)`.
3. **Pole-B check.** Within 3 s of GENSTAT Charging, firmware requires I_VBATN to agree with reg 0x06 within 0.2 A
   (tolerance TODO(calibrate)), and I_VCHG - I_VBATN to stay inside the expected VLOGIC band. Any mismatch is a K2 or
   stub fault: FC_CHARGE LOW, then the normal exit, then a latched fault.
4. **Purge policy (ruling 6).** About 1 s before each predicted purge, firmware runs the exit, so the pack is back on
   the bus before the dip. On an unpredicted sag below 13.5 V for 2 ms, it opens FC_CHARGE at once and then exits.
5. **Exit.** FC_CHARGE LOW; wait for V_chg < 9 V (timeout 1 s); pump OFF; confirm the VCHG_V decay and V_batt at
   PACK_V; confirm I_VBATN = 0 A (K2 NO weld check); then re-close BT_REG and BT_BUS through the existing guarded path
   onto the FC-regulated bus. No P0 re-run is needed, because MOT_PWR stayed closed.
6. **Reset cause.** After any reset, firmware reads the reset cause and the last commanded relay state (F-M3).
7. **Watchdog.** The RTWDOG (ruling 5) is a precondition of any window, because the dynamic drive covers only the
   relays and the charger feeds.

The cost of the ruling-6 policy per 10.34 s purge period is the exit (up to 1 s for the V_chg decay, 77-139 ms of
pump decay, the release time and about 0.5 s of confirms), the purge itself, and the re-entry (about 0.7-0.8 s,
Table 7). This is about 1.5-2.5 s of the 10.34 s period (15-25 %), two relay operations per period (about 700 per
hour) and one Ag105 restart per period. The CB1 mechanical life is TODO(verify: Panasonic ASCTB220E).

#### 10.5.5 Revised LM1084 headroom

Table 17 recomputes Table 8 for the RUN position with the CB1 15 mOhm maximum per contact and an assumed 5 mOhm of
harness per leg (UNCONFIRMED). The pack sag uses the 24 mOhm DCIR estimate (UNCONFIRMED).

Table 17. LM1084 input headroom at a 7.4 V pack, IC6-R1, RUN.

| Pack current | Pack sag | GND lift (20 mOhm) | LM1084 input | Margin over 6.5 V |
|---|---|---|---|---|
| 7.21 A | 0.17 V | 0.14 V | 7.09 V | 0.59 V |
| 15 A | 0.36 V | 0.30 V | 6.74 V | 0.24 V |
| 16.46 A | 0.40 V | 0.33 V | 6.67 V | 0.17 V |

The margin at the bench peak is small but positive. The F1 and lead drop at the logic current is not included
(fuse resistance TODO(verify: fuse vendor)).

### 10.6 Post-review status

The FC budget is re-based on the H-20 P_MAX bus equivalent (about 1.247 A) and OC_FC 1.4 A. The IC6-R1 parasitic
load is about 3.3 W of coil power (2.8 W through a converter of assumed 0.85 efficiency, TODO(verify)) plus
I_5V x 8.4 V of logic power (I_5V BENCH). Table 18 gives the bus current at 16 V, including the 0.15 A aux load.

Table 18. Bus current per charge code (IC6-R1).

| Code (cell current) | Nominal (eta 0.88, I_5V 0.3 A) | Pessimistic (eta 0.85, I_5V 0.4 A) | Against 1.247 A |
|---|---|---|---|
| 7 (0.75 A) | 0.86 + 0.15 = 1.01 A | 0.95 + 0.15 = 1.10 A | Inside in both cases |
| 6 (1.0 A) | 1.01 + 0.15 = 1.16 A | 1.11 + 0.15 = 1.26 A | The pessimistic case exceeds |
| 4 (1.5 A, the H5 floor) | 1.31 + 0.15 = 1.46 A | 1.42 + 0.15 = 1.57 A | Exceeds in both cases |

Code 7 is the safe default. Without any coil load, code 4 would need 1.22 A nominal, 2 % under the P_MAX equivalent.
The IC6-specific coil load is therefore what removes H5. The logic load is common to every concept that powers the
logic from the pack during charge.

Table 19 gives the post-review status of each hard requirement.

Table 19. Post-review hard-requirement status (IC6-R1).

| ID | Status | Reason |
|---|---|---|
| HR1 Regen | **FAILS** | By construction (S-F1). Ruling 1 disqualifies IC6 as the overall winner. |
| HR2 FC charging | **FAILS against H5; BENCH as a fallback** | 0.75 A (code 7) or 1.0 A (code 6, BENCH) at standstill, against the 1.5 A floor. The ruling-6 policy costs 15-25 % of each purge period. |
| HR3 No loop | **PROVEN_CALC** | Unchanged: no reviewer found a loop. |
| HR4 No runaway | **PROVEN_CALC, conditional; BENCH for the trip curve** | The hardware ceiling (2.5 A trip, latched) bounds F3, F5 and F20 without the FC as a bound. Gate B2 (Ag105 behaviour with the load outside the sense) remains a go/no-go gate. |
| HR5 Fail-safe inhibit | **PROVEN_CALC, conditional; BENCH for gate B7** | The trip latch sets at power-up, the permit drops before the relay moves, and the RTWDOG is a window precondition. |

IC6 is withdrawn as a requirement-meeting design, and IC6-R1 is a recorded standstill-only fallback. IC6-R1 needs an
explicit operator ruling that relaxes ruling 1 and accepts a charge rate below H5. Its feasibility then depends on
three go/no-go bench gates that need no rework: B4 (CB1 contact resistance and NC carry at 16.5 A), B2 (the Ag105
with an external load on VBat+ and a reverse sense current at restart) and B13 (the pin 14/15 cut). The added
protection (two shunts, a comparator, a latch, two Schmitt stages, a 12 V converter and a pre-charge FET) roughly
doubles the switch-board complexity of the original dossier. For the full requirement set, the prior rating of
"switch both battery legs off the PCB" as the weakest option (`docs/respin_power_architecture_2026-11-04.md` option 2)
stands. IC6 resolves only objection 2 of that note (Teensy brownout) and part of objection 5 (references).

Three gate changes follow from the review:

- new gate B15: the State-99 discharge time of VBUS and V-MOT in RUN with the charger drains blocked (F-n7);
- gate B10 is revised: the peak I_fc at an unpredicted purge, with FC_CHARGE opened within 2 ms, against OC_FC 1.4 A;
- gate B2 is extended with the E-M4 cases.
