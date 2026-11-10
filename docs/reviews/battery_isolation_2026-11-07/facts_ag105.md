# Ag105 fact sheet for the battery-isolation feasibility study

Primary source: Silvertel Ag105 datasheet V1.1, November 2021 (`references/Datasheets/AG105_Silvertel.pdf`, 21 pages,
read in full; cited below as "DS p.N"). Secondary sources: the extracted tables
`references/Datasheets/Ag105_Table3..7_*.json`, the schematic `references/Scale_Car_Board_20260624.sch` (Eagle XML net
names), and BOM line `CHG` in `references/Scale Car Design PCB BOM 20260622.csv` (Silvertel AG105, DigiKey
5061-AG105-ND). The text extraction of DS p.4, p.10, p.17 and p.19-20 is column-scrambled; those pages were read from
rendered images. Items that the datasheet does not state are marked TODO(verify: Silvertel) or BENCH. Inferences are
marked UNCONFIRMED.

## 1 Pin map and board connectivity

### 1.1 Pin rules (DS p.4, Table 2)

Table 1 lists every pin, its datasheet rule, and the net it connects to on board revision 20260622. The pad-to-pin
order was checked against the Eagle footprint in the `Silvertel Ag105` library of the `.sch`: the left row is pins
1-10 from VSEL downwards; the right row is pins 11-22 from MPPTD upwards.

Table 1. Ag105 pins, datasheet rules and board nets.

| Pin | Name | DS rule (Table 2, p.4) | Board net (`.sch`) |
|---|---|---|---|
| 1 | VS | Resistor to Vin- sets charge voltage | Unconnected (no pinref) |
| 2 | CS | Resistor to Vin- sets charge current | Unconnected |
| 3 | STAT | Status output | `CHRG-STAT` to Teensy (U$1 6-OUT1D) and J1:15/16 |
| 4 | Vin- | Negative supply input (11-36 V) | `GND` |
| 5, 6, 9 | IC | Internal connection, do not connect | NC1-NC3 pads |
| 7 | SCL | High-impedance I2C clock input | `SCL` |
| 8 | SDA | I2C data | `SDA` |
| 10 | Vin+ | Positive supply input (11-36 V) | `VCHG-IN` (D-BC-FC VOUT, D-BC-RG VOUT, C-D8, C-D10, R1-CHG) |
| 11 | MPPTD | "Pull this pin to Vin- to disable MPPT" | `MPPT-DISABLE` to Teensy (U$1 5-IN2) and J1:13/14 |
| 12 | MPPTS | Resistor to Vin- sets the MPPT threshold | Unconnected (MPPTSEL pad open) |
| 13 | THERM | Optional 10 k NTC to Vin- for JEITA | `N$34` to J-NTC pin 1 (J-NTC pin 2 on `GND`) |
| 14, 15 | VBat- | Battery negative output. "Must NOT be connected directly to the GND pin." | `GND` (VBAT-1, VBAT-2) |
| 16, 17 | VLoad- | Load negative output. "Internally connected to Vin-." | Unconnected |
| 18, 19 | VBat+ | Battery positive output | `VCHG` (C-D11, D-BT-SQ VIN) |
| 20 | LD | "Pull this pin to Vin- to disable the load output." | Unconnected |
| 21, 22 | VLoad+ | Load positive output | Unconnected |

### 1.2 Internal current-sense placement (DS p.3, Figure 1)

Figure 1 places the **Current Sense** block between Bat- and the internal node that joins Vin-, the converter
return and Load-. The sense output drives the Feedback block of the buck-boost converter. Therefore the converter
regulates only the current that returns through Bat-. Bat+ connects directly to the converter output; Load+
connects to Bat+ through an internal switch.

Figure 1 also draws a second internal switch in parallel with the Current Sense block, between the Vin-/Load- node
and Bat-. The datasheet does not describe this switch. One reading is a low-loss path for battery discharge into
Load-; this reading is UNCONFIRMED.

On this board, pins 14/15 (VBat-) and pin 4 (Vin-) are both on net `GND`, and pack negative (J-BT pin 2) is also on
`GND`. Both ends of the sense element are therefore at the same node. Battery current returns to Vin- through the
board ground pour, not through the sense. The Ag105 feedback consequently reads near zero for any battery current.
This is consistent with reg 0x06 = 0 during the ML0227 ramp recorded in
`docs/reviews/charger_eval_2026-11-05/incident.md` (section (a)).

### 1.3 VLoad- and the load path

- VLoad- is "internally connected to Vin-" (DS p.4). It is the return for a load that the Ag105 powers from the
  battery through VLoad+ (DS p.3 Figure 1; DS p.7 Figure 4 shows the load between VLoad+ and VLoad-).
- Battery-to-load current flows Bat+ -> internal switch -> VLoad+ -> load -> VLoad- -> Vin- node -> (sense or its
  parallel switch) -> Bat-. The discharge current therefore passes the Bat- leg of the module (Figure 1).
- The maximum continuous discharge current is **4 A** (DS p.20, row 6, I_DIS). The datasheet does not name the path
  explicitly; the load output is the only discharge path in Figure 1, so I_DIS applies to it (UNCONFIRMED).
- The maximum voltage across the VLoad pins is **30 V** (DS p.20, row 3). If the input can exceed 30 V, back-feed
  protection on VLoad+ is recommended (DS p.16).
- "The Ag105 provides no overcurrent protection between the battery and the load output" (DS p.19, section 5.6.2).
- "The Ag105 will never present the battery potential on the Vload output when charging is in process" (DS p.9).
  By default the battery is on VLoad whenever the module is not charging, for example when fully charged or when the
  input is below the MPPT threshold (DS p.9). LD pulled to Vin- disables the load output (DS p.4).
- A load that must run during charge is fed from the input side, not from VLoad (DS p.9 refers to section 3.2; DS
  p.16 Figure 10 and DS p.7 Figure 4 feed the load from the input through diode D2).

### 1.4 Whether a load current is counted in charge regulation

The datasheet does not address a load placed directly across the battery. From Figure 1 the following holds
(UNCONFIRMED; derived from the block diagram only):

- A load connected between VBat+ and VBat- (downstream of the sense, in parallel with the battery) returns through
  the sense. The converter counts that load current as charge current. CC current into the cells is reduced by the
  load current, and the CV termination at 10 % of the set current (DS p.5) can be held off or triggered falsely.
- A load connected between VBat+ and Vin-/GND (or VLoad-) returns without passing the sense. The converter does not
  see that current, so it supplies it without regulation in addition to the regulated battery current.
- Whether the over-current trip (section 4.1) uses the same sense element is not stated. TODO(verify: Silvertel).

## 2 Charge process (DS p.5, section 2.1)

- Stage 1, constant current, set by the CS pin or I2C reg 0x00. Stage 2, constant voltage at the VS/I2C setting.
- Termination: when the CV current falls to **10 % of the configured CC current**, charging stops and the battery is
  flagged fully charged (DS p.5). Table 4 (DS p.8) lists the cut-off as exactly 10 % for every setting, for example
  250 mA cut-off at 2500 mA.
- Recharge: the module does not charge again until the battery voltage falls **0.2 V/cell** below the configured
  charge voltage (DS p.5; DS p.11 "Fully charged"). For 2S/8.4 V this is 8.0 V.
- Pre-Charge: when the battery is below **2.7 V/cell** at charge start, the module supplies **10 %** of the set current
  until the cell exceeds **3.0 V/cell** or a fixed **30 min** timer elapses (DS p.5; DS p.20 row 2, T_RT = 30 min typ).
  Timer expiry sets Major Battery Fault (DS p.6).

## 3 Battery detection and Bring-Up (DS p.6, section 2.2)

- The module measures the battery voltage to detect a battery. "If the battery presents 0V it performs a Bring-Up
  Charge, in which the output is gradually ramped while the Ag105 monitors the current draw and voltage" (DS p.6).
- No current draw during Bring-Up -> Battery Disconnect status, and the detection cycle repeats (DS p.6).
- Battery voltage below **2 V** while **10 %** of the charge current flows -> Major Battery Fault (DS p.6; DS p.18).
- Battery below **2.7 V/cell** at 10 % current -> Pre-Charge (DS p.6).
- Battery above **2.7 V/cell** when the current draw reaches 10 % -> normal charge (DS p.6).
- Battery within **0.2 V/cell** of the charge voltage -> Fully Charged status (DS p.6; DS p.11).
- "While in a status that prevents charging, the Ag105 will continue to measure the battery voltage or perform the
  Bring-Up charge in order to detect a battery disconnect" (DS p.6).
- **Not given by the datasheet:** the Bring-Up ramp rate, the ramp end voltage, the Bring-Up duration, and the
  detection-cycle retry period. TODO(verify: Silvertel). The only measured figure on this project is an output ramp of
  about **0.64 V/s** from about 2 V into an open VCHG node (C-D11, 10 uF), recorded in serial data during ML0227
  (`docs/reviews/charger_eval_2026-11-05/incident.md`, table row "r05"). That figure is BENCH and was taken with the
  sense element shorted.
- Interaction with the shorted sense: the 10 % current threshold is detected through the sense (Figure 1). With VBat-
  on GND the module cannot see the battery current, so the Bring-Up exit condition is not met by the sense
  (UNCONFIRMED; consistent with the ML0227 ramp to 11-13 A in the incident record).

### 3.1 Battery connected after input power-up

The datasheet has no dedicated statement. The detection cycle repeats while no battery is detected (DS p.6), so a
battery connected later is detected on a subsequent cycle. The cycle period is not given. TODO(verify: Silvertel);
BENCH.

### 3.2 Battery disconnected during a charge

The datasheet has no dedicated statement. The applicable clauses are:

- "If the Ag105 detects a voltage or current behaviour that is not expected from a battery, charging will be
  terminated, and the Ag105 will return to the battery detect cycle" (DS p.11, Over Current/Regulation error).
- "If the voltage across the battery is below what would be expected from a cell configuration, the Ag105 will cease
  output and trigger a regulation error. After this the Ag105 will continue to test the output with a Bring-Up"
  (DS p.19, section 5.6.1).

The response time, the output overshoot on the VBat+ node when the battery opens during CC, and whether the module
reports Fully Charged (current falls below 10 %) instead of a regulation error are not given. UNCONFIRMED; BENCH.

### 3.3 Open-circuit output

With no battery the module performs Bring-Up, sees no current, reports Battery Disconnect and repeats (DS p.6, DS
p.11). The open-circuit output voltage limit during the ramp is not given. TODO(verify: Silvertel).

## 4 Protection

### 4.1 Over-current and short circuit

- Trip at **200 mA above the set charge current**; the module shuts down the DC-DC converter and STAT reports an
  over-current error (DS p.18, section 5.3). At the 2.5 A setting the trip is 2.7 A.
- Partial short: the output is limited to the configured charge current; if the voltage is below a valid cell
  configuration the module stops and reports a regulation error, then repeats Bring-Up (DS p.19, 5.6.1).
- Dead short: over-current status first, then repeated output tests and Major Battery Fault (DS p.19, 5.6.1).
- Short-circuit duration: infinite (DS p.20, row 10, T_SC max = infinity).
- No over-current protection on the battery-to-load path (DS p.19, 5.6.2).
- No battery-reversal protection; DS p.18 recommends an external diode D1 (DST1550S) and a 10 A slow-blow fuse
  (DS p.7, p.15, p.16 figures).
- The datasheet requires protected packs or cells; bare cells are "not supported" (DS p.18, 5.1).

### 4.2 Deep discharge and Major Battery Fault clearing

- No rise above 2 V during Bring-Up -> over-discharged, STAT 5 pulses, cleared only by a power cycle or a battery
  disconnect (DS p.18, 5.4).
- DS p.11 states a different clearing set for Major Battery Fault: "a battery potential of greater than 2.7V/cell, a
  power cycle or a battery disconnect". The two pages disagree on the 2.7 V/cell clause. TODO(verify: Silvertel).

### 4.3 Input protection and limits

- Absolute maximum DC supply: **-0.3 V to 36 V** (DS p.19, 6.1). Clamp recommended if the supply can exceed 36 V
  (DS p.18, 5.2).
- Recommended input: **11 V min, 36 V max** (DS p.19, 6.2 row 1).
- Input under-voltage lockout V_LOCK: **11 V typical** (DS p.19, 6.2 row 2; the value is in the Typ column).
- Long input leads: a 470 uF capacitor across the input may be required (DS p.6, 2.3).
- Idle input current: **18 mA max** (DS p.20, row 4). Battery standby current with no input: **120-420 uA**
  (DS p.20, row 7).

### 4.4 Thermal

- Built-in over-temperature protection disables the output until the module cools (DS p.19, 5.7). Thresholds and
  hysteresis are not given. TODO(verify: Silvertel).
- Operating ambient **-40 to +70 C** (DS p.17; DS p.19 row 3). Full settings to +45 C. For 2 cells: all settings at
  <= 45 C, **<= 2.0 A** at <= 60 C, **<= 1.75 A** at <= 70 C, measured with about 0.5 m/s airflow; sealed enclosures
  derate further (DS p.17, Table 9).
- JEITA with a 10 k / B 3435 NTC on THERM: 50 % current at 0-10 C, stop below 0 C, stop above 45 C, or charge to
  60 C at reduced voltage with Extended JEITA (reg 0x0A) (DS p.9, Figure 5).

## 5 Efficiency and output quality (DS p.20)

- Charge efficiency **88 % typical** (row 1; note 2: 25 C, 12 V input, 3S configuration). No other operating point
  is given.
- Output ripple at the battery terminal 100 mVp-p typical (row 9); ripple and noise current 300 mAp-p max at 2.5 A
  (row 13).
- Line regulation 0.15 % typical (row 11); load regulation 0.4 % typical at 24 V input, CV mode (row 12).
- Typical figures are "for design aid only. Not Guaranteed" (note 1).

## 6 Start-up timing after input power arrives

The datasheet gives no start-up time, no I2C-ready time and no time from input arrival to first charge current.
TODO(verify: Silvertel). The firmware uses `AG105_SETTLE_MS 500u`, itself marked `TODO(calibrate)`
(`teensy_controller/teensy_controller.ino` line 2484). All I2C measurements read 0xFF while the input is below
**9 V** or while the module is in an error state, for example below the MPPT threshold (DS p.14, Measurements).

## 7 MPPT threshold and MPPTD (DS p.10, section 2.9)

- When MPPT is enabled the module "will monitor the input voltage and adjust the charge profile in order to maximise
  the energy harvested" (DS p.10).
- The MPPT setting is a **threshold of 11-33 V "that must be present across the input of the Ag105 before charging
  will commence"** (DS p.10). Default with MPPTS open: **18 V** (DS p.10).
- Resistor law: R_MPPT = 20e3 x (36 / (47 - V_MPPT) + 1) ohm (DS p.10; read from the rendered page).
- I2C reg 0x02: values 0-250 set 11-33 V at about **0.088 V/count**; values >= 251 select the external resistor;
  default 0xFF (DS p.13 Table 7; Table7 JSON). Count 0 = 11.0 V and count 250 = 33.0 V.
- MPPTD: "Pull this pin to Vin- to disable MPPT" (DS p.4, p.10). MPPT "can be enabled or disabled without restarting
  the module or terminating charge" (DS p.10). On this board MPPTD is driven directly by Teensy pin 5
  (`MPPT_DISABLE`, net `MPPT-DISABLE`), so LOW disables MPPT and HIGH releases it.
- Not stated: whether the input threshold still gates charge start while MPPTD is LOW, and whether an in-progress
  charge stops when the input falls below the threshold. TODO(verify: Silvertel). Status bit 4 "Power Tracking"
  (Table 6) indicates that the charge profile is tracking the input power; bit 3 reports MPPT enable.
- Board consequence: the default 18 V threshold is above the 16.0 V VBUS nominal (CLAUDE.md section 6), so charging
  from the bus with MPPT enabled requires reg 0x02 below the bus voltage. The fw v24 policy writes counts 15-27
  (12.320-13.376 V) (CLAUDE.md section 3).

## 8 Status reporting

### 8.1 STAT pin (DS p.11, Table 5; Table5 JSON)

Table 2 lists the STAT patterns. All pulses are 200 ms high and 200 ms low, with 1.2 s between pulse sets (DS p.11).
STAT is a 3.3 V output through an internal 20 k series resistor (DS p.10, Figure 6a); V_OL 0.5 V max, V_OH 3.3 V min
(DS p.20, row 8).

Table 2. STAT output modes (DS p.11, Table 5).

| Mode | Status | STAT |
|---|---|---|
| 0 | Charging | Steady high |
| 1 | Fully Charged | 50 % high, 2 s period |
| 2 | Disconnected Battery Error | 1 pulse |
| 3 | Battery Temperature Error | 2 pulses |
| 4 | OC/Regulation Error | 3 pulses |
| 5 | Timeout Error | 4 pulses |
| 6 | Major Battery Fault | 5 pulses |
| 7 | Input Voltage Removed | Steady low |

### 8.2 I2C status byte (DS p.13, Table 6; Table6 JSON)

The status byte precedes every read value. GENSTAT (bits 0-2): 000 Battery Disconnect, 001 Low Power, 010 Charging,
011 Fully Charged, 100 Bring-Up Charge, 101 OC/Regulation Error, 110 Thermal Shutdown, 111 Timeout Error. The 110 row
prints with a stylised "v" for the middle bit; the JSON records it as 1 1 0. Bit 3 MPPT enabled, bit 4 Power
Tracking, bit 5 Constant Voltage, bit 6 Constant Current, bit 7 Thermal Limiting.

Table 5 and Table 6 do not map one to one. Table 6 has Low Power and Bring-Up Charge but no Major Battery Fault code;
Table 5 has Major Battery Fault and Battery Temperature Error. The meaning of "Low Power" is not defined. TODO(verify:
Silvertel).

## 9 Register map and I2C protocol (DS p.12-14, Table 7, Table 8; Table7 JSON)

- Address **0x30** (7-bit) by default, changeable through field 0xE5 to 0x01-0x7F (DS p.13-14). Interface referenced
  to Vin-, compatible with 3 V and 5 V buses, unbuffered; 10 k pull-ups advised (DS p.12).
- Write: address, field ID, data byte (DS p.12 Figure 7). Read: address, field ID, stop and start, address + read,
  then **status byte followed by data byte** (DS p.12 Figure 8).

Table 3 lists the fields.

Table 3. Ag105 I2C fields (DS p.13, Table 7).

| Field | Name | Access | Default | Function | Scale | EPROM |
|---|---|---|---|---|---|---|
| 0x00 | Charge Current Setting | R/W | 0x00 | 0 = resistor; 1-12 = 2.5 A down to 0.1 A | - | yes |
| 0x01 | Battery Voltage Setting | R/W | 0x00 | 0 = resistor; 1-12 = 3.9-12.6 V | - | yes |
| 0x02 | MPPT Voltage | R/W | 0xFF | 0-250 = 11-33 V; >= 251 = resistor | 0.088 V | yes |
| 0x03 | Timeout | R/W | 0x00 | 0 = none; 1-254 x 3 min | - | yes |
| 0x04 | Recovery Time | R/W | 0x00 | 0 = no recovery; 1-254 x 3 min | - | yes |
| 0x05 | Measured Battery Voltage | R | - | 8-bit | 0.064 V | - |
| 0x06 | Measured Charge Current | R | - | 8-bit | 0.011 A | - |
| 0x07 | Measured Input Voltage | R | - | 8-bit | 0.141 V | - |
| 0x0A | Extended JEITA | R/W | 0x00 | 0/1 | - | yes |
| 0xFD / 0xFE | Firmware major / minor | R | - | char | - | fixed |
| 0xE5 | I2C address | R/W | 0x30 | 0x01-0x7F | - | yes |
| 0xE6 | Reset Memory | W | - | reset all settings to default | - | - |

Notes on the fields:

- With no RVS/RCS resistor, the module defaults to **4.2 V and 1000 mA** (DS p.8). The 2S/8.4 V code is 0x08 and the
  2.5 A code is 0x01 (Table3/Table4 JSON). Out-of-range writes to 0x00 or 0x01 default to 1000 mA or 4.2 V (DS p.14,
  Table 8).
- Reg 0x06 full scale: 255 x 0.011 A = 2.805 A. The register reads 0xFF when the input is below 9 V or the module is
  in an error state (DS p.14). Reg 0x06 is the module's own sense reading; with VBat- on GND it does not measure the
  battery current (section 1.2).
- Timeout counts from the first charging state, continues after charge stops, and resets only on Fully Charged or a
  power cycle; Recovery counts only while the timeout flag is set (DS p.14). Example: 0xF0 = 12 h (DS p.14).
- EPROM write endurance is not given. TODO(verify: Silvertel).

## 10 Can the module be inhibited while powered?

The datasheet provides no charge-enable pin and no charge-enable register (DS p.4 Table 2; DS p.13 Table 7). This
confirms the prior finding. The available controls and their limits are:

- **LD** disables only the load output (DS p.4, p.9). It does not stop charging.
- **MPPTD** disables only MPPT tracking, without "terminating charge" (DS p.10).
- **Reg 0x02 at a high threshold** (for example count 250 = 33 V, above the 16 V bus) with MPPT enabled would
  prevent charging from commencing, because the threshold "must be present ... before charging will commence"
  (DS p.10). This is an indirect inhibit. It is UNCONFIRMED whether it stops a charge already in progress and whether
  it applies while MPPTD is LOW. Each change is an EPROM write of unknown endurance.
- **Reg 0x00 / 0x01** can lower the current to 0.1 A or the voltage target (Table 7), but cannot set zero.
- **Removing input power** (below the 11 V UVLO, DS p.19) is the only datasheet-certain stop. On this board that means
  opening the charger power paths (`FC_CHARGE_ENABLE`, or `REGEN_ENABLE` with `MOT_PWR_ENABLE`), which feed net
  `VCHG-IN` through D-BC-FC and D-BC-RG.
- **Removing the battery from VBat+/VBat-** makes the module fall back to its detection cycle (DS p.6, p.11). This
  does not remove the input; the module keeps ramping its output into the open node during Bring-Up (section 3).

## 11 Facts that constrain the isolation design

The following points summarise the datasheet constraints. They are derived from the items above; items not directly
stated in the datasheet are marked UNCONFIRMED.

1. The module regulates only current that returns through VBat- into the sense. Correct regulation requires VBat-
   separated from Vin- (GND) by the sense alone, with the pack negative on VBat- (DS p.3, p.4).
2. While charging, the battery cannot supply the system through VLoad (DS p.9). Any system load during charge must
   be fed from the input side or must return to Vin- outside the sense, and in the latter case the converter supplies
   it unregulated (UNCONFIRMED, section 1.4).
3. Pack negative is system ground on this board (J-BT pin 2 on `GND`). Placing the sense in the pack return during
   charge therefore lifts the pack negative from system ground by the sense drop; the sense resistance is not given
   (TODO(verify: Silvertel); the incident record proposes a pins 14/15 to 16/17 resistance measurement as BENCH).
4. Opening the battery leg while the module charges produces a regulation-error or detection response whose timing
   and VBat+ overshoot are not specified (sections 3.2, 3.3). This must be measured before a switch opens under load.
5. The input must stay above 11 V (DS p.19) and above the reg 0x02 threshold for charge to start (DS p.10); the
   module restarts its detection cycle after any input loss, with an unspecified start-up time (section 6).
6. Over-current protection (set + 200 mA, DS p.18) is effective only if the sense sees the current. It provides no
   protection on the battery-to-load path (DS p.19).
