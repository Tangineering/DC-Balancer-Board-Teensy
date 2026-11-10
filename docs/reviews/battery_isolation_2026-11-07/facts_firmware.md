# Battery-isolation feasibility study: firmware and system fact sheet

**Scope.** This fact sheet records what the firmware at the tree tip (`teensy_controller/teensy_controller.ino`, fw v37 rev 2, `FW_VERSION 37` at line 4281) does with the battery channel, the charger power paths and the spare I/O. It supports the evaluation of switching circuitry between the pack terminals (J-BT, J-BL) and the board. Citations are `file:line`. The abbreviation `ino` means `teensy_controller/teensy_controller.ino`. Inferences are labelled UNCONFIRMED. Hardware electrical limits of new parts are outside the scope of this document.

**Build flags at the tip.** `BENCH_TEST 1` (ino:4284), `HIL_SIM 0` (ino:4315), `USE_ETHERNET 0` (ino:4325). This is the bench flash of 2026-11-04 (docs/fw37_planning_2026-11-04.md §10.1). Under `BENCH_TEST 1`, OC_FC, OC_BT, UV_BATT, SWITCH_CONFLICT and the GENSTAT latch are compiled out (ino:7114-7116, 7272-7322, 7413-7418, 7430, 7440-7450; planning §10.1).

---

## 1. Netlist facts that the firmware depends on

The schematic `references/Scale_Car_Board_20260624.sch` (net extraction, this study) gives the following connectivity.

| Net | Members | Consequence |
|---|---|---|
| `VBT` | J-BT pin 1, C1-BT, C2-BT, L-BT, R1-BT (V_batt divider), REG-BT VIN, **REG-5V INPUT** (LM1084), CIN-5V, D-BT-SQ VOUT, C-D12 | The pack positive, the BT boost input, the V_batt sense divider and the Teensy logic regulator share one node. |
| `GND` | J-BT pin 2, J-BL pin 3, BAL GND, **CHG VBAT-**, **CHG VIN-**, SNS-BT GND/REF1/REF2, U$1 GND | Pack negative = PCB ground = Ag105 VBat- (the forbidden tie, docs/boost-bringup-debug.md:1645). |
| `VCHG` | CHG VBAT+, D-BT-SQ VIN, C-D11 | D-BT-SQ sits between the Ag105 output and VBT. |
| `5V` | REG-5V OUTPUT, CO-5V, U$1 VIN, J2 pins 1-2 | The Teensy is powered from VBT through the LM1084. |
| `VCHG-IN` | CHG VIN+, D-BC-FC VOUT, D-BC-RG VOUT, R1-CHG | Two charger feeds: FC_CHARGE (from VBUS) and REGEN (from V-MOT). |
| `V-MOT` | D-MT-EN VOUT, D-BC-RG VIN, CAL (470 µF), J-M, Q-SNT/Z-SNT (chopper), R1-SNT | The motor node and the regen node are one node. |

**Note that** `BT_SEQUENCE_ENABLE` (pin 32) drives `D-BT-SQ`, the charger-output-to-VBT switch. It does not gate the pack to the BT boost. The PLAN.md wording "battery-pack sequencing" (PLAN.md:70, 117) and the HIL hi-fi model (§9) do not match this netlist.

## 2. State machine and switch ownership

### 2.1 States

The main loop dispatches on `mainState` (ino:6783-6790).

- **State 0 (Init).** Production runs the staged bring-up `busBringupTick(true)` (ino:7816-7821). `BENCH_TEST 1` goes to Idle with the power stage dark; the operator brings it up with State-98 `G` (ino:7800-7803). `HIL_SIM 1` waits for the injection stream (ino:7762-7779).
- **State 1 (Idle).** The motor current is commanded to 0 at 500 Hz and `REGEN_ENABLE` is driven LOW every tick (ino:7841-7842). `MOT_PWR_ENABLE` stays HIGH (Death-5 doctrine, ino:7827-7835). Idle→Run calls `armShareBatteryOnlyStart()` (ino:7913).
- **State 2 (Run).** `FC_BUS_ENABLE` HIGH unless the share latch owns it (ino:7929); `assertMotPwrEnable(true)` or `FAULT_MOT_HOTPLUG` (ino:7938-7942); then `chargingControlGated()`, `motorControlGated()`, `powerBalanceGated()` in that order (ino:7950-7952).
- **State 3 (Finish).** Motor 0, `assertFcChargeEnable(false)`, `REGEN_ENABLE` LOW, `MPPT_DISABLE` LOW; bus, boosts, `MOT_PWR` stay ON; selector flags cleared (ino:7982-8018).
- **State 98 (Test).** Entered from Idle by `T` (ino:7851-7856). `Q` exits to Idle and forces `MOT_PWR_ENABLE`, `REGEN_ENABLE` LOW and FC_CHARGE off (ino:9224-9268).
- **State 99 (Error).** Phased teardown, latched until power cycle except the HIL auto-recovery (ino:8248-8455). Phase 0: both bus switches LOW, then `assertFcChargeEnable(true)` for a ~10 ms VBUS drain into the charger (ino:8299-8318). Phase 1: FC_CHARGE off, `REGEN_ENABLE` HIGH, `MOT_PWR_ENABLE` LOW for a ~10 ms V-MOT drain (ino:8320-8327). Phase 2: REGEN LOW, MPPT LOW, both boosts LOW; `BT_SEQUENCE_ENABLE` stays HIGH; `CBAL_DISABLE` stays LOW (ino:8329-8340). The two drains are deliberately not gated by `AG105_VBATN_ISOLATED` (ino:5070-5073).

### 2.2 Write sites of the battery-relevant switches

| Pin | Write sites (ino line) | Rule |
|---|---|---|
| `BT_SEQUENCE_ENABLE` (32) | 6715 (setup LOW); 12938 (bring-up P1 HIGH); 8726-8729 (State-98 `6` toggle) | Never driven LOW again by any automatic path. |
| `BT_BUS_ENABLE` (28) | 6711; 8309 (State 99); 8670 (`2`); 12762 (`assertFcChargeEnable`); 12792 (`safeAllSwitches`); 12905 (P0 HIGH); 13025 (abort); 13463, 13570 (share latch); 14893, 14904 (`applyShareRatio`); 15321, 15361, 15392, 15526 (`chargingControl`) | Owned in Run by `chargingControl()` and the share latch (ino:7920-7928). |
| `FC_CHARGE_ENABLE` (31) | 6714; 12774, 12776 (only inside `assertFcChargeEnable`) | Single chokepoint. |
| `REGEN_ENABLE` (30) | 6713; 7842 (Idle LOW); 7985; 8324, 8331 (State 99); 8699 (`4`); 9286 (`Q`); 11457, 11476, 11502 (`J`); 12772; 12791; 12900; 15308, 15357, 15375, 15395, 15524 (`chargingControl`) | Mutually exclusive with FC_CHARGE through the guard. |
| `MOT_PWR_ENABLE` (29) | 6712; 8325 (State 99); 9279 (`Q`); 12794; 12903 (P0 LOW); 13021; 13070-13073 (`assertMotPwrEnable`) | ON only from a bus ≥ `V_BUS_CHARGED_THRESH` (ino:13060-13075). |

All path switches are driven LOW in `setup()` before the SD probe and Ethernet (ino:6709-6715). The comment records 10 kΩ EN-to-GND bodge resistors as a backstop (ino:6708).

### 2.3 Staged bring-up (production `doState0()` and State-98 `G`)

`busBringupTick()` (ino:12837-13013) sequences P0 to P3:

1. P0 (ino:12893-12916): FC_CHARGE off, REGEN LOW, both boosts LOW, MOT_PWR LOW, then both bus switches HIGH (body-diode pre-charge).
2. P0 gate (ino:12919-12943): V_bus ≥ max(V_fc, V_batt) − `PRECHARGE_DROP_MAX` (1.5 V, ino:2326) and ≥ `V_PRECHARGE_MIN` (5.0 V, ino:2328), after `PRECHARGE_MIN_MS` 40 ms, timeout 300 ms (ino:2330-2331). It then enables both boosts and drives **`BT_SEQUENCE_ENABLE` HIGH** (ino:12936-12938).
3. P1/P2 (ino:12946-12972): V_bus ≥ `V_BUS_CHARGED_THRESH` = 13.5 V (ino:2317) within 800 ms, then a 50 ms dwell (ino:2318, 2334).
4. P3 (ino:12974-13006): `assertMotPwrEnable(true)`; V_rgn must track V_bus within 3.0 V in 500 ms (ino:2338, 2347).

**The bring-up reads V_batt in its P0 gate.** A pack held off VBT at boot leaves the gate dependent on V_fc alone.

## 3. Charger control path

### 3.1 `assertFcChargeEnable()` (ino:12743-12778)

- **Enable.** If the share loop holds FC off the bus, FC_BUS is restored first (S2, ino:12755-12759). Then `BT_BUS_ENABLE` LOW (ino:12761), share BT claims cleared, `REGEN_ENABLE` LOW (ino:12772), `delayMicroseconds(100)` (ino:12773), `FC_CHARGE_ENABLE` HIGH (ino:12774).
- **Disable.** `FC_CHARGE_ENABLE` LOW only (ino:12776).
- **Consequence.** An FC charge window is already a battery-off-the-bus state: BT_BUS is open for the window. The pack stays connected to VBT and to the Ag105 output through D-BT-SQ.
- **Backstop.** `FAULT_SWITCH_CONFLICT` latches FC_CHARGE HIGH with BT_BUS or REGEN HIGH (ino:7413-7418, production only).

### 3.2 `chargingControl()` (ino:15289-15562, 50 Hz, `CHARGING_CTRL_PERIOD_US` 20000 at ino:3747)

1. UV backoff state update: V_bus < 12.8 V for 15 ms sets the backoff; > 13.6 V clears it (ino:15296-15302; constants ino:2597-2599).
2. `charge_goal <= 0.05`: MPPT LOW, FC_CHARGE off, REGEN LOW, guarded BT_BUS re-close; return (ino:15305-15323).
3. Regen (`current < -0.1f`, a commanded value, ino:15336): FC_CHARGE off; REGEN HIGH only if `ag105VbatnIsolatedFlag && !ag105CommTripLatched` (ino:15355-15357); MPPT LOW; **BT_BUS kept HIGH** ("BT continues contributing to VBUS during regen", ino:15361).
4. Backoff: REGEN LOW, FC_CHARGE off, MPPT LOW, guarded BT re-close (ino:15362-15392).
5. Cruise: F1 disarm-before-open (ino:15458-15485); window limits `FC_CHG_MAX_MS` 30 s and `FC_CHG_COOLDOWN_MS` 2 s (ino:2632-2634, 15488-15500); entry needs V_bus ≥ 13.5 V, no lockout and `!fcUvLockoutActive()` (ino:15499-15500). The open call needs `FC_CHARGE_ALLOWED` (0 at ino:2616), the G5 flag, no trip latch, and FC_BUS conducting and unblanked (ino:15503-15506). Otherwise the window is explicitly shut (ino:15507-15527). The MPPT release follows `ag105IsReady()` with a 1000 ms holdoff (ino:15539-15560).

**Today's effective behaviour.** With `FC_CHARGE_ALLOWED 0` and `AG105_VBATN_ISOLATED 0`, neither charger feed can open from Run. Regen energy goes to the TL431/BSP170P chopper (ino:5066-5069).

### 3.3 `chargerHasPower()`, `pollAg105()`, `AG105_SETTLE_MS`

- `chargerHasPower()` = FC_CHARGE HIGH, or REGEN HIGH and MOT_PWR HIGH (ino:16244-16247). It reads pin levels; it does not consider the pack.
- `pollAg105()` runs every >20 ms from `loop()` in all states (ino:6812-6813). The power edge starts the settle timer; loss of power clears `ag105Configured`, `ag105DataValid` and `I_charge` and resets the MPPT session (ino:16138-16152).
- `AG105_SETTLE_MS` = 500 ms, `TODO(calibrate)` (ino:2484). The config writes (reg 0x01 = 0x08, reg 0x00 = 0x01) happen once per powered session after settle (ino:16196-16198). They are inhibited while a `J` session stands (ino:16194).
- A powered, settled charger that NAKs in State 2 or 3 latches `FAULT_I2C_CHARGER` (ino:16158, 16216-16217). A failed config write in State 2 or 3 latches `ERR_INIT_FAIL` (ino:16197-16198). State 98 never faults on the charger I2C.
- `ag105IsReady()` = live status byte with GENSTAT 0x02 (Charging) or 0x03 (Full) (ino:16232-16237). GENSTAT 0x00 is "Battery Disconnect" and is a valid, non-fault status (ino:7440-7445). The 0xFF measurement sentinel zeroes `I_charge` (ino:16180-16183).
- The GENSTAT 5/6/7 latch (`FAULT_CHARGER_STAT`) runs only under `!BENCH_TEST` (ino:7438-7450).

**Relevance.** A pack-isolation switch is invisible to `chargerHasPower()`. A disconnected pack would plausibly surface as GENSTAT 0x00 or 0x04 and as reg 0x05 below the pack voltage, as on 2026-11-04 (docs/boost-bringup-debug.md:1544-1547, 1608-1612). That mapping is UNCONFIRMED for a deliberately opened pack switch.

### 3.4 The G5 hardware gate `AG105_VBATN_ISOLATED`

- Defined at ino:5078-5085: default 0 on real boards, 1 under `HIL_SIM`, overridable with `-D`; runtime mirror `ag105VbatnIsolatedFlag`.
- While 0 (or while the G4 latch is set) it refuses `J` `1` / `1 2`, `4` REGEN ON, `5` FC_CHARGE ON (ino:11542-11565, 8694, 8721); holds REGEN LOW in the Run and `D` regen branch (ino:15355-15357); and blocks the FC charge window (ino:15503).
- It does not gate the State-99 drains (ino:5070-5073).
- Its declared meaning is "the Ag105 battery return has been reworked so it is NOT tied to PCB GND" (ino:5058-5062). A battery-isolation scheme that makes charging legal would set this flag; the flag name then describes a different hardware fact (UNCONFIRMED naming fit).

### 3.5 The `J` commissioning session and guards G1-G4

- Start (ino:11259-11466): State 98 only, the G4/G5 refusal first, no bring-up/profile, MOT_PWR HIGH, V_bus ≥ 13.5 V, FC_CHARGE LOW, `CBAL_DISABLE` LOW, no manual motor or live share loop, REGEN LOW, and bus-side I_fc + I_batt ≤ 0.2 A (ino:5103, 11328). The inhibit goes up first; MPPT LOW; `assertFcChargeEnable(false)`; then REGEN HIGH as the charger power edge (ino:11441-11460).
- Tick (ino:11761 onward, called at ino:9440): stops on REGEN or MOT_PWR LOW, FC_CHARGE HIGH (ino:11767-11775). G3 trips on GENSTAT 5/6/7 from 40 ms after the edge (ino:5129, 11779-11785). G1 trips on I_fc + I_batt > 1.0 A for ≥ 5 ms (ino:5098-5099, 11786-11800). G2 trips on V_bus·(I_fc + I_batt) − baseline − min(P_chg, 21 W)/0.75 > 3.0 W for ≥ 20 ms (ino:5122-5125, 11801-11823). Other stops: 120 s cap (ino:4981), V_bus < 13.5 V for ≥ 20 ms (ino:5038).
- Trip action `ag105CommissionTrip()` (ino:11500-11526): REGEN LOW first, then MPPT LOW, no serial I/O before the pins, G4 latch set until reboot.
- **G1 and G2 read the boost-output currents.** They detect a bus→charger→pack→BT boost loop only as excess bus-side source current. They do not read the pack current directly; no pack-side current sensor exists.

## 4. Faults that read the battery channel

`detectFaults()` runs once per loop iteration, after `updateSensors()` and `computeDerivedSignals()` (ino:6769-6771). It clears `fault_flags` each tick and re-evaluates (ino:7108). `triggerFault()` latches State 99 on the first cause (ino:7064-7076).

| Fault | Signal and rule | Build gate | Line |
|---|---|---|---|
| `UV_BATT` | Armed when BT_BUS and BT_REG are both HIGH and V_batt ≥ 7.8 V; latches after 1000 ms net dwell under 7.4 V (leak 0.05, dt cap 5 ms). Every disarm dumps the dwell. | `!BENCH_TEST` | 2096, 2266-2267, 7272-7322 (latch 7308) |
| `OV_BATT` | V_batt > 8.5 V, single sample, every state | all builds | 2140, 7422 |
| `OC_BT` | I_batt (bus-side) > 3.0 A, single sample | `!BENCH_TEST` | 2155, 7430 |
| `OC_FC` | I_fc (bus-side) > 1.4 A, single sample | `!BENCH_TEST` | 2090, 7115 |
| `UV_BUS` | Armed by a matched pair (bus switch and its boost both HIGH) with V_bus ≥ 13.5 V; latches at 20 ms net dwell under 12.0 V | all builds | 2163, 2189-2193, 7324-7410 (latch 7381) |
| `UV_FC` | Armed by the FC pair and V_fc ≥ 7.0 V; 1000 ms dwell under 4.5 V; a share-loop cut holds the dwell; a closed excursion arms a 30 s FC-only lockout | all builds | 2148, 2243, 2256, 2278, 7176-7270 (latch 7249) |
| `OV_BUS` | V_bus > 17.5 V for ≥ 10 ms and ≥ 3 ticks | all builds | 2112, 2122-2128, 7124-7175 (latch 7149) |
| `OV_CHG` / `OV_RGN` | V_chg > 24 V / V_rgn > 28 V, single sample | all builds | 2284-2285, 7435-7436 |
| `SWITCH_CONFLICT` | FC_CHARGE HIGH with BT_BUS or REGEN HIGH | `!BENCH_TEST` | 7413-7418 |

Sensor sources (ino:6947-6955): V_batt = ADC pin 25 × (16.2k + 10k)/10k scale, full scale 8.646 V (ino:2025-2026); I_batt = INA253 on the BT boost output, 0.1 V/A, unipolar, about 8.06 mA/count (ino:2035, 2074-2088 note). The INA253 sense point is between the TPS61288 output and the RT1987 input (ino:2074-2078). Both V_batt and I_batt are referenced to PCB GND.

### 4.1 Misbehaviour if the pack is disconnected (positive leg open)

The following are consequences derived from the code above; none has been bench-tested.

1. **V_batt reads the VBT node, not the pack.** With D-BT-SQ ON and the Ag105 driving VCHG, the divider reads the charger output; with neither, VBT decays with the BT boost and LM1084 load.
2. **UV_BATT (production).** If BT_BUS and BT_REG stay HIGH while the pack opens, the armed dwell latches `ERR_UV_BATT` 1000 ms after VBT falls under 7.4 V (ino:7300-7309). Opening BT_BUS or BT_REG first disarms it and dumps the dwell (ino:7283-7292). A scheme must sequence that order.
3. **OV_BATT (all builds).** If the Ag105 output alone drives an open VBT node above 8.5 V, `ERR_OV_BATT` latches on one sample (ino:7422). The Ag105 open-circuit output voltage with no battery is `TODO(verify: AG105_Silvertel.pdf)`. The ADC saturates at 8.646 V, so the divider cannot read a higher value (ino:2134-2139).
4. **UV_BUS.** If the battery is the only live source (battery-only arm, FC cut), opening the pack collapses the bus. The bus collapses at I_load/C_VBUS, 2.57 V/ms at the HIL aux load (ino:2246-2248 comment), and latches `ERR_UV_BUS` after 20 ms of net dwell.
5. **Logic brownout.** The Teensy VIN comes from REG-5V on VBT (§1). Opening the pack with no other VBT source removes logic power unless USB supplies it. The LM1084 dropout figure is `TODO(verify: LM1084ISX-5p0.pdf)`. During a brownout all GPIO go high-Z; the 10 kΩ EN-to-GND bodges hold the RT1987s off (ino:6708). Pull-downs on `EN-REG-FC`/`EN-REG-BT` are `TODO(verify: .sch)`. `CB-DISABLE` has no external pull (ino:6727-6729), so the BQ29200 `!CB_EN` input floats.
6. **Bring-up.** The P0 gate uses max(V_fc, V_batt) (ino:12931). A missing pack lets bring-up proceed on V_fc alone; `BT_REG_ENABLE` is then driven HIGH into a boost with no input source (UNCONFIRMED effect).

### 4.2 Misbehaviour if the pack negative is floated from PCB GND

This is a hardware topology change; the firmware facts are these. V_batt (ino:6952) and I_batt (ino:6948) are single-ended to PCB GND. The BT boost PGND/AGND, SNS-BT REF1/REF2 and the BQ29200 GND are on PCB GND (§1). A floated pack negative would make V_batt read the pack plus the return-switch drop, would leave I_batt unchanged in reference, and would move the BQ29200 reference unless J-BL pin 3 moves with it. The firmware has no channel to measure the return-switch voltage.

## 5. Share loop and source-selector dependence on the battery

- **Battery-only start.** `armShareBatteryOnlyStart()` at every Idle→Run selects the battery alone (ino:15102-15120, 7913). The selector re-arms when the filtered total is ≤ 2 × `SHARE_MINORITY_I_MIN_A` = 0.25 A (ino:3202, 14106-14125). The battery is therefore the default sole source at standstill and light load.
- **FC-only selection.** A command ≥ `DROOP_R_MAX` 0.85 selects FC alone (ino:3105, 14126-14130). It is refused while `fcUvLockoutActive()` holds, that is 30 s after a purge-class dip (ino:2256, 2425-2427, 14137). A raw I_fc above `SHARE_GOV_I_FC_CEIL_A` 1.25 A or a dipping FC rail drops an FC-selected arm (ino:3530, 14218-14222).
- **Purges need the battery.** The H-20 purges to ~1 V roughly every 10.3 s (ino:15488-15498 comment). An FC-only bus collapses during a purge faster than the 8 ms RT1987 turn-on (`RT1987_T_D_ON_MS`, ino:4875) can restore BT. The fw v33b gate therefore refuses FC charge windows outright on a purging stack (ino:15493-15500). The bench recorded UV_FC + UV_BUS within seconds of the first window on 2026-10-28 (firmware-versions.md row 35).
- **Bus-switch blanking.** A rising bus switch is blanked for 30 ms (`SHARE_CUT_SURVIVOR_BLANK_MS`, ino:4869, 4935-4946); FC charge windows open only on an unblanked FC_BUS (ino:15504).
- **Selector dwell.** A selection change is rate-limited to one per 250 ms (ino:3466).

**Consequence for isolation.** Every charging window that removes the pack from the bus is an FC-only bus. The firmware has no path that tolerates an FC-only bus across a purge. The purge characterisation (duration, interval, floor) is still a bench gate (firmware-versions.md row 30).

## 6. Regen path facts

- Trigger: `current < -0.1f`, the commanded motor current, evaluated at 50 Hz (ino:15336, 3747).
- V-MOT is kept connected to VBUS through Idle and Run, so a closed REGEN feeds the charger from the bus (fw37_planning §3.3, lines 117-122). Operator ruling R3 forbids bus-fed charging in Run (planning:17).
- The planned v38 interlock closes REGEN only when V_rgn > V_bus + margin, evaluated at 1 kHz (planning:131-136). V_rgn reads 0.85 × true and must be calibrated first (planning:160-163).
- In the regen branch BT_BUS stays HIGH (ino:15361). A scheme that isolates the pack during regen events contradicts this branch.

## 7. Spare Teensy pins

The authoritative pin map (`references/Scale Car Teensy IO - IO.csv`) assigns 0, 1, 3-7, 9, 11-15, 18, 19, 24-32, 36-41. The schematic routes every other header pin to the J1/J2 Teensy receptacles (BOM "Board headers J1,J2", 87606-324LF) and to nothing else:

| Pin | Net | Alternate functions (schematic pin name) | Status |
|---|---|---|---|
| 10 | PIN10 | CS / MQSR | Free |
| 16 | PIN16 | A2 / RX4 / SCL1 | Free, analog-capable |
| 17 | PIN17 | A3 / TX4 / SDA1 | Free, analog-capable |
| 20 | PIN20 | A6 / TX5 / LRCLK1 | Free, analog-capable |
| 21 | PIN21 | A7 / RX5 / BCLK1 | Free, analog-capable |
| 22 | PIN22 | A8 / CTX1 | Free, analog-capable |
| 23 | PIN23 | A9 / CRX1 / MCLK1 | Free, analog-capable |
| 33 | PIN33 | MCLK2 | Free |
| 34 | PIN34 | RX8 | Free |
| 35 | PIN35 | TX8 | Free |
| 2 | ENC_A | OUT2 | Still wired to RENC1 and J1 pins 7-8 in the schematic; the 2026-08-16 bodge moved the encoder to pin 14. Whether the old trace was cut is not recorded (UNCONFIRMED). |
| 8 | ENC_B | TX2 / IN1 | As pin 2, to RENC2 (UNCONFIRMED). |
| 7 | N$21 | RX2 / OUT1A | Wired to ROS (100 Ω); CSV "No longer in use"; firmware leaves it undriven (ino:6704-6705). |

Firmware use of peripherals: `Serial1` (VESC), `Wire` on 18/19 at the default clock (ino:16289-16293), SPI for the MDACs, SDIO for the built-in SD, emulated EEPROM at 4276 (ino:1949). `Wire1` (16/17), `Serial5` (20/21) and `Serial8` (34/35) are unused. Two `CHANGE` interrupts on pins 14 and 15 are the only ISRs (ino:6736-6737). No `IntervalTimer` and no `analogWrite` is used. Telemetry `switch_state` uses bits 0x01-0x20 of a u8 (ino:2662-2667, 4586-4595), so two bits are spare; the HIL aux byte and BLG flag bytes are full (CLAUDE.md fw v28 addendum).

## 8. Reaction speed

- **Loop rate.** No fixed tick; the measured median iteration is 1131 µs (884 Hz), p99 tail 1337-1341 µs, worst gap 9.76 ms in ML0226 (docs/reviews/noise_fw37_2026-11-05/agents/vbus_blg1k.md:5; planning:192). During `J` I2C reads the worst interval was 2.4 ms (boost-bringup-debug.md:1580-1581).
- **Cadences.** `detectFaults()` every iteration (ino:6771); `powerBalance()` 1 kHz, `motorControl()` 500 Hz, `chargingControl()` 50 Hz (ino:3746-3748); `pollAg105()` and telemetry every >20 ms (ino:6812). The constants are `TODO(calibrate)`, not measured (ino:3741-3745).
- **Fastest firmware reaction.** A single-sample fault reacts within one iteration (about 1.1 ms typical). Filtered faults take 10 ms (OV_BUS), 20 ms (UV_BUS, G2, the `J` V_bus stop), 5 ms (G1) and 1000 ms (UV_FC, UV_BATT). A 50 Hz `chargingControl()` decision can lag a brake by up to 20 ms plus one motor period (ino:7944-7950).
- **Switch actuation.** GPIO writes are immediate `digitalWrite()` calls; ordering delays use `delayMicroseconds(100)` (ino:12773). RT1987 turn-on delay is taken as 8 ms (ino:4875).
- **Blocking hazards.** `Ethernet.begin()` blocks with no link (ino:6757; planning §10.1); SD init at boot up to ~2 s (ino:6740-6743); the EEPROM commit duration is `TODO(verify: PJRC)` (CLAUDE.md fw v28 rev 3).
- **No MCU hardware watchdog is configured.** A grep finds no `WDOG`/watchdog peripheral use; the only watchdog is the Pi packet timeout, 500 ms, States 2 and 3 only (ino:4731, 7463-7471). A hung loop therefore holds every output at its last level. The charger study's HR5 lists the hardware watchdog as required future work.

## 9. HIL plant models that a battery-isolation scheme would change

- **Simple plant** (`tools/hil_plant_sim.py`, class `Plant` at 1613): the pack (`BatterySource`, 1742) is always connected; the charger current enters the pack as `i_bt_src - i_charge` (2250-2251). `SW_BT_SEQ` (178) is defined but not used in the step. The charger is a status-level model gated exactly like `chargerHasPower()` (2310-2318); no circulating bus→charger→pack loop, no VBat- tie and no pack disconnection is modelled.
- **Hi-fi engine** (`tools/hil_electrical.py`): `BT_SEQ` gates the pack into the BT boost INPUT (2069-2072, 2220-2240: `v_bt_in = v_bt_term if bt_seq_on else 0.0`, `bt_en = AUX_BT_REG and bt_seq_on`). **This does not match the schematic**, where D-BT-SQ links VCHG to VBT (§1). The model behaves like a pack-isolation switch on the BT boost input, which is one candidate topology of this study; the current hardware is not modelled.
- **Firmware HIL mirror.** `AG105_VBATN_ISOLATED` defaults 1 under `HIL_SIM` (ino:5078-5080). `pollAg105()` never touches I2C under an active link and configures by fiat (ino:16089-16134).
- **Items a scheme would need in the plant:** a VBT node separate from the pack, the new switch states and their observation bits, the Teensy logic supply on VBT, a pack-disconnected charger status (GENSTAT 0x00/0x04), and the purge-dip FC source on an FC-only bus.

## 10. Open items recorded by this sheet

1. D-BT-SQ orientation on the board (fw37_planning §3.4 item 2; boost-bringup-debug.md:1573-1576). The reg-0x05 climb on 2026-11-04 is consistent with the schematic orientation.
2. Whether pins 2 and 8 are free of the RENC pull-ups after the 2026-08-16 bodge.
3. The H-20 purge duration, interval and floor (firmware-versions.md row 30, bench gate 0i-1).
4. The Ag105 output behaviour with no battery connected, and whether MPPTD LOW bypasses the input threshold (`TODO(verify: Silvertel)`, ino:11446-11448).
5. The HIL hi-fi `BT_SEQ` semantics versus the netlist (§9).
