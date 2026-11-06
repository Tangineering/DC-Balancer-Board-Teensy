# Replacement-charger INTERFACE SPEC for the CURRENT board (rev 20260622) - Path A

Scope: what an off-the-shelf charger (or charger evaluation board, EVM) must meet to replace the
Silvertel Ag105 at the existing `CHG` pads, with no change to the motherboard power stage. Path B
(re-spin) is a separate track. This spec does not choose a part.

## Sources and conventions

| Tag | Source (read this session) |
|---|---|
| [SCH] | `references/Scale_Car_Board_20260624.sch` (Eagle XML, parsed with python) |
| [BRD] | `references/Scale Car Board PCB 20260625.brd` (Eagle XML, parsed) |
| [BOM] | `references/Scale Car Design PCB BOM 20260622.csv` |
| [CSV] | `references/Scale Car Teensy IO - IO.csv` (authoritative pin map) |
| [AG] | Silvertel Ag105 datasheet V1.1 Nov 2021 (`references/Datasheets/AG105_Silvertel.pdf`), PDF page given as p.N |
| [RT] | Richtek RT1987 datasheet DS-00 Sep 2024, p.N |
| [TPS] | TI TPS61288 datasheet SLVSFP3C, p.N |
| [BQ29] | TI bq29200 datasheet SLUSA52C, p.N |
| [FW] | `teensy_controller/teensy_controller.ino` at tree tip (fw v37 rev 2), line numbers |
| [P37] | `docs/fw37_planning_2026-11-04.md` section 3 |
| [INC] | `docs/boost-bringup-debug.md`, 2026-11-04 `J` entry (ML0227 analysis) |

Copies of the datasheets: `.../charger_eval/datasheets/` (Ag105, RT1987, TPS61288, BQ29200).
**UNVERIFIED** = not read in a primary source this session. Net and part names follow [SCH].
Aliases: D-BC-FC = BOM "D-BFC" = docs "D-FC-CH"; D-BC-RG = BOM "D-BRG" = docs "D-RG-EN";
D-BT-SQ = BOM "B-BSQ". All six are RT1987N-A.

## 0. Key facts that shape the spec

1. **The only charger power entry is VCHG-IN, behind two RT1987 switches** [SCH]:
   D-BC-FC (VIN = VBUS, EN = pin 31 `FC_CHARGE_ENABLE`) and D-BC-RG (VIN = V-MOT, EN = pin 30
   `REGEN_ENABLE`). Both VOUTs join at VCHG-IN. With both EN low the charger has no power at all.
2. **The charger's output never sees the pack directly.** VCHG (charger VBAT+) -> D-BT-SQ
   (VIN = VCHG, VOUT = VBT, EN = pin 32) -> VBT = pack + [SCH]. The RT1987 is an ideal diode, so
   current flows only charger -> pack, and the pack cannot drive VCHG. The ML0227 log confirms
   this orientation: the Ag105 read its own output climbing from ~2 V and the ramp started on the
   first line where its output passed the 7.67 V pack [INC].
3. **VIN-, VBAT- and pack negative are all PCB GND** [SCH: CHG VIN- -> GND, CHG VBAT- -> GND,
   J-BT pin 2 -> GND]. The board has GND pours on both copper layers [BRD]. **Requirement R-GND:**
   the replacement charger's input return and battery return must be the same node, with no sense
   element or switch between them. High-side (BAT+) or input-side current sensing is acceptable.
   Low-side sensing (a BAT- shunt) is bypassed by the board GND, which is the Ag105 defect
   ([AG] p.3 Fig. 1 shows the current sense in the Bat- leg. p.4 pins 14/15 say VBat- "Must NOT be
   connected directly to the GND pin").
4. **The pack has no hardware overcharge action on this board.** BQ29200 `OUT` goes to net
   `BAL-NOK` with no other connection [SCH]. It detects 4.35 V/cell +/-25 mV ([BQ29] p.5-6) and
   drives nothing. Firmware `LIMIT_V_BATT_MAX` 8.5 V ([FW] 2140) latches State 99, which opens the
   charger input switches. So **the charger's CV regulation is the primary overcharge control.**
   The Ag105 datasheet also supports only protected packs ([AG] p.18). Whether the RC pack has its
   own protection board is UNVERIFIED.

## 1. Pad-by-pad table (CHG footprint, 22 holes)

Absolute coordinates: element CHG at (47.498, 34.544) mm, rot R180 [BRD]. Pads are on a 2.54 mm
pitch, in two rows 25.00 mm apart, 1.1 mm drill, square pads. The Ag105 pins are 0.64 mm
([AG] p.21).

| Ag105 pin | Pad (BRD name) | Abs X, Y (mm) | Board net [SCH/BRD] | Driven by | Voltage range | Current | Required function on the new charger |
|---|---|---|---|---|---|---|---|
| 10 | VIN+ | 46.00, 61.94 | **VCHG-IN** (+ C-D8, C-D10 10 uF/25 V each; R1-CHG 78.7k / R2-CHG 10k to pin 38 `CHG_VOLTAGE`) | D-BC-FC VOUT (from VBUS) OR D-BC-RG VOUT (from V-MOT) | 0 V (off) / ~15.8 V (FC charge) / 15.8-21.4 V and above (regen), see section 2 | <= ~1.5 A in (2.5 A x 8.4 V / 0.9 / 15.8 V = 1.48 A). FC mode budget <= ~1.0 A | Charger power input. Must meet sections 2, 4, 5, 6 |
| 4 | VIN- | 46.00, 46.70 | GND | - | 0 | input return | Charger input ground. Same node as the battery negative (R-GND) |
| 14, 15 | VBAT-1, VBAT-2 | 21.00, 56.86 / 54.32 | GND | - | 0 | battery return <= 2.5 A | Battery negative = GND. **No shunt or FET between this and the input ground** |
| 18, 19 | VBAT+1, VBAT+2 | 21.00, 46.70 / 44.16 | **VCHG** (polygon under the footprint; C-D11 10 uF/25 V; D-BT-SQ VIN) | the charger (only source on this node) | 0 V when the charger is idle (only 10 uF; the pack is blocked by D-BT-SQ). Charging: VBT + 35-50 mV, i.e. 7.4-8.45 V | <= 2.5 A out (split over 2 pins) | CC/CV output. Must start into an open or capacitive output and ramp itself above the pack (section 3.4) |
| 8 | SDA | 46.00, 56.86 | SDA -> Teensy 18; RSDA 10 kOhm to Teensy 3V3 | Teensy (Wire) | 0-3.3 V | <= 0.33 mA (10 k pull-up) | I2C data, open-drain, 3.3 V compatible, no extra pull-ups to another rail |
| 7 | SCL | 46.00, 54.32 | SCL -> Teensy 19; RSCL 10 kOhm to 3V3 | Teensy | 0-3.3 V | same | I2C clock |
| 3 | STAT | 46.00, 44.16 | CHRG-STAT -> Teensy 6 `CHARGER_STAT` (IN), no pull resistor | the charger | 0-3.3 V max | uA | Status / ready / fault output into a 3.3 V input. Open-drain needs a pull-up to 3V3 (section 3) |
| 11 | MPPTD | 21.00, 64.48 | MPPT-DISABLE -> Teensy 5 `MPPT_DISABLE` (OUT), no pull resistor | Teensy, LOW from `setup()` ([FW] 6720) | 0 / 3.3 V | uA | **Recommended reuse: charge ENABLE, active HIGH, pulled down on the charger side** (LOW / high-Z = no charge). This keeps the firmware's boot level (LOW = inhibited) fail-safe |
| 13 | THERM | 21.00, 59.40 | N$34 -> J-NTC pin 1 (J-NTC pin 2 = GND); 0.61 mm trace, 15 mm | external NTC to GND | analog | uA | Battery NTC input: NTC (10 k, B = 3435 per [AG] p.9) between pad and GND. The bias divider goes on the charger side. Must also work with the NTC absent (fixed resistor) |
| 1, 2, 12, 20 | VSEL, CSEL, MPPTSEL, LDIS | see [BRD] | unconnected | - | - | - | Floating. Usable as mechanical anchors |
| 16, 17, 21, 22 | VLOAD-1/2, VLOAD+1/2 | right row | unconnected on the board | - | - | - | Floating. The charger's SYS/load output (if any) is left unconnected |
| 5, 6, 9 | NC1, NC2, NC3 | left row | unconnected | - | - | - | Floating anchors |

Pad order (left row, top to bottom in local coordinates): VSEL(1) CSEL STAT VIN- NC1 NC2 SCL SDA
NC3 VIN+(10). Right row: MPPTD(11) MPPTSEL THERM VBAT-1 VBAT-2 VLOAD-1 VLOAD-2 VBAT+1 VBAT+2 LDIS
VLOAD+1 VLOAD+2(22) [BRD].

Other relevant nets (for bodge wires):
- **Under the footprint:** VBT, the pack side of D-BT-SQ, at C-D12 (bbox x 33.2-35.3, y 48.6-51.5).
  This is a Kelvin pack-voltage point. 5 V (LM1084 off VBT, battery-derived) is at CO-5V (x 49.3-52.3,
  y 37.3-42.0), 0.1 mm outside the right edge.
- **Teensy breakout receptacles J1/J2 (2.54 mm)** [SCH]: 3V3 J1.29/30 and J2.05/06. 5V J2.01/02.
  GND J1.01/02. `FC_CHARGE_ENABLE` net J1.45/46. `REGEN_ENABLE` net J1.43/44. `MOT_PWR_ENABLE`
  J1.41/42. MPPT-DISABLE J1.13/14. CHRG-STAT J1.15/16. SDA J2.17/18. SCL J2.15/16.
  Spare Teensy pins (not in [CSV]): 10 (J1.23/24), 16, 17, 20-23, 33 (J2.47/48), 34 (J2.45/46).
  Pins 2 and 8 still carry RENC pull-ups. Any new use goes into [CSV] first.

## 2. Electrical envelope

### 2.1 Input (VCHG-IN) cases

Path impedance: one RT1987 regulates VIN - VOUT = 35 mV until I x 20 mOhm exceeds that, then acts
as R_ON = 20 mOhm ([RT] p.7, p.16). The VCHG-IN copper is ~110 mm of 1.524 mm trace on both layers
with 2 vias [BRD]. At 0.035 mm copper (Eagle DRC `mtCopper`; as-built weight UNVERIFIED) that is
about 35 mOhm. Path drop at 1.5 A is therefore ~35 mV + 53 mV = ~0.09 V.

| Case | Switches | VCHG-IN | Notes / limits |
|---|---|---|---|
| **A. FC charge** | FC_CHARGE 1, REGEN 0, BT_BUS 0 (enforced by `assertFcChargeEnable()` [FW] 12743; CSV row 31) | ~15.8 V nominal (VBUS 15.9-16.0 V, `V_BUS_NOMINAL` 16.0 [FW] 2102, minus ~0.1 V) | The FC alone feeds the bus. VBUS sags with the FC boost droop. Fault floor `LIMIT_V_BUS_MIN` 12.0 V ([FW] 2163). Firmware OV `LIMIT_V_BUS_MAX` 17.5 V. Physical ceiling = TPS61288 OVP 18.3/19/19.5 V min/typ/max ([TPS] p.6). FC current `LIMIT_I_FC_MAX` 1.4 A bus-side, one-sample latch ([FW] 2090). Aux load ~0.1-0.15 A. **The charger input current must be limited to <= ~1.0 A in this mode.** FC charging is currently compiled out (`FC_CHARGE_ALLOWED 0`, [FW] 2616) but is a project goal |
| **B. Regen** | REGEN 1 with MOT_PWR 1 (MOT_PWR stays closed through Idle/Run since Death 5) | Idle: V-MOT ~= VBUS - D-MT-EN drop ~= 15.85 V. Braking: up to the TL431/BSP170P chopper clamp, **~21.4 V true** measured ([P37] 3.2). Design value 2.495 V x (1 + 78.7k/10k) = 22.1 V ([BOM] TL431B, R1-SNT/R2-SNT) | Burst profile: V-MOT rises 0.08-0.12 s after the setpoint falls, peaks 0.10-0.20 s in, back at bus level by 0.3-0.6 s. ~0.7 J electrical per decel, ~0.2 A into the pack for 0.4 s if captured ([P37] 3.2). **V-MOT above the clamp is possible:** the chopper is a 47 Ohm shunt ([BOM] R-SHUNT), so it sinks only ~0.46 A at 21.4 V. Any regen current above that plus the charger's draw drives V-MOT higher. Peak UNMEASURED. Firmware faults: `LIMIT_V_CHG_MAX` 24.0 V on pin 38 ([FW] 2285) and `LIMIT_V_RGN_MAX` 28.0 V on pin 39, which reads 0.85x true (~33 V true). Both are detect-and-latch, not clamps |
| **C. Bus-feed hazard** | REGEN 1 while V-MOT ~= VBUS (layer-1 failure, or a `J`-type test) | ~15.8 V, stiff, backed by both boosts and by the pack through the BT boost | This is the incident case: ~11 A bus-side, ~170 W, a circulating bus -> charger -> pack -> BT boost -> bus loop ([INC]). With a correctly sensing charger the loop is bounded by the charger's input/charge limits, which is still forbidden by R3 (section 4) |
| **D. State-99 teardown drain** | FC_CHARGE ~10 ms, then REGEN ~10 ms, onto nodes whose sources are already open ([FW] 5068-5070) | decaying from <= bus level | Capacitor energy only. The charger must tolerate ~10 ms input pulses and abrupt removal without latching a fault that needs a power cycle |
| **E. Off** | all EN low | 0 V; bleeds through R1/R2-CHG (88.7 kOhm) | RT1987 disabled = full isolation both ways ([RT] p.14). Output leakage <= 60 uA ([RT] p.7) |

### 2.2 Required ratings

| Parameter | Requirement | Basis |
|---|---|---|
| Input operating range (no OVP trip) | **<= 12 V to >= 23 V** | 12 V = UV_BUS floor (case A droop). 23 V = 21.4 V clamp + 1.6 V. An input OVP set below ~22 V would drop out at the regen peak, which is the energy being harvested |
| Input absolute maximum | **>= 30 V required, >= 36 V preferred** | V-MOT can exceed the clamp (case B). Firmware latches at 24 V V_chg, but only after the excursion. RT1987 rec. max 32 V, AMR 40 V, its OVP (POVP = GND) is >= 33 V, so it does not protect the charger below 33 V ([RT] p.6-7, p.16). Ag105 AMR was 36 V ([AG] p.19). **Board limitation:** C-D8/C-D10 on VCHG-IN are 25 V parts ([BOM] GRM21BZ71E106KE15L). Path A should replace them with >= 35 V parts (e.g. the 1206 35 V type already used for C-D6/7/9) |
| Input UVLO / start | Start threshold >= ~10 V, or a soft-start delay > the 1.5 ms RT1987 ramp | Prevents the charger from loading VCHG-IN mid-ramp (section 6) |
| Charge current | Programmable, 2.5 A capable, down to <= 0.25 A. Input current limit settable to <= 1.0 A | 2.5 A = Ag105 max ([AG] p.8) and the firmware target ([FW] 2468). FC mode is limited by section 2.1 A: at 1.0 A in, ~1.7 A out. Regen mode is ~0.2 A average ([P37] 3.2), so light-load efficiency matters (target >= 80 % at ~2 W, UNVERIFIED feasibility). Pack charge rating UNVERIFIED |
| CV setpoint | 2S, 8.400 V, accuracy **+/-0.5 % or better** over temperature | No hardware OVP action exists (section 0.4). The firmware OV latch is at 8.5 V |
| CV error from D-BT-SQ | Pack sees the charger CV **minus 35 mV** (light load, VFWD regulation) **to minus 50 mV** (2.5 A x 20 mOhm) ([RT] p.7, p.16) | At termination (light load) the pack ends ~35 mV low, -0.42 % (8.365 V). Raising the charger CV to ~8.43 V to compensate is acceptable only if its accuracy is <= +/-0.3 %. Otherwise keep 8.400 V and accept the undercharge |
| Output ripple at VCHG | < ~50 mVp-p recommended | The RT1987 fast reverse comparator turns D-BT-SQ off within 0.5 us if VIN - VOUT < -50 mV ([RT] p.7, p.16). Near termination the ideal diode regulates at +35 mV, so a ripple trough ~85 mV below the regulation point can chatter the switch. Analysis, UNVERIFIED. Ag105 spec was 100 mVp-p ([AG] p.20) |
| Output overcurrent | Cycle-by-cycle limit independent of the battery-side sense | D-BT-SQ re-closes without soft-start after a TRCB event ([RT] p.15 Table 1), so the charger meets a step load from open to the pack |

## 3. Control requirements

### 3.1 Fail-safe off during Teensy reset or boot

- **Layer 1 (existing, hardware): no input power.** Each RT1987 EN has an internal 475-985 kOhm
  pull-down ([RT] p.7) plus the 10 kOhm EN-to-GND bodge resistors (CLAUDE.md §2). VEN_F >= 0.6 V
  min, VEN_R <= 1.4 V max ([RT] p.7). With Teensy pins high-Z, D-BC-FC and D-BC-RG stay open, so
  the charger is unpowered. `setup()` also drives 30/31/32 LOW early ([FW] 6713-6715).
- **Layer 2 (new charger): its own enable must default to OFF.** Use the MPPTD pad (pin 5) as an
  active-HIGH charge enable with a pull-down on the charger/carrier side (<= 47 kOhm, to beat any
  pad keeper; Teensy 4.1 reset pad state UNVERIFIED). Requirements: VIH <= 2.0 V, abs max >= 3.6 V,
  no back-powering of the charger from a HIGH pin. If the candidate's disable input is active HIGH
  (e.g. an ILIM/HIZ pin where HIGH = off), add an inverter or pull-up so that a low or floating
  pin 5 gives OFF.
- **Power-on default:** after its own power-on reset, the charger must not charge until the host
  enables it. Acceptable: a hardware enable pin held off, or a reset default of 0 A charge current.
  Not acceptable: a charger that starts on reset from NV settings, like the Ag105 did (its reg 0x02
  EPROM held 12.85 V, below the bus [INC]). Reason: section 4 (R3) and the config window in section 5.
- **Watchdog:** if I2C-controlled, a host watchdog that stops charging when the Teensy goes silent
  (<= ~5 s; shorter preferred).

### 3.2 I2C (Teensy pins 18/19)

- Open-drain, with VIL/VIH valid on a 3.3 V bus. RSDA/RSCL 10 kOhm to Teensy 3V3 are fitted [SCH].
  **Remove any EVM pull-ups to 5 V, REGN or VDDA.** Teensy 4.1 IO is 3.3 V and not 5 V tolerant
  (PJRC; not read in a primary source this session, UNVERIFIED).
- Clock: firmware calls `Wire.begin()` with no `setClock` ([FW] 16290-16292), so 100 kHz. 10 kOhm
  pull-ups give t_r ~= 0.85 x R x C = 0.85 us at 100 pF: OK for 100 kHz, too slow for 400 kHz.
- The charger is the only device on this bus [SCH]. Any 7-bit address works. Firmware is
  hard-coded to 0x30 today ([FW] 2464).
- **Unpowered behaviour (most cycles):** the charger has no power whenever both input switches are
  open. Its SDA/SCL must stay high impedance with VDD = 0, without clamping the bus or back-powering
  the charger through the pull-ups (<= 0.33 mA per line).
- **Config persistence:** D-BT-SQ blocks the pack from VCHG, so a charger that powers its logic
  from BAT+ is still dead when the input is off. Volatile registers are therefore lost on every
  input-power cycle. Either (a) the firmware re-writes the config after every power-up (latency in
  section 5), (b) the critical settings (CV, current, threshold) are resistor/pin-strapped, or
  (c) the charger logic is powered from the battery-derived 5 V rail (LM1084 off VBT, at CO-5V /
  J2.01-02). Option (c) is R3-compliant: battery, not bus.

### 3.3 Status input (pin 6 `CHARGER_STAT`)

- Teensy input, `pinMode(CHARGER_STAT, INPUT)` with no pull ([FW] 6706). There is no pull
  resistor on the net [SCH]. The Ag105 drove it push-pull, 3.3 V through 20 kOhm ([AG] p.10, p.20).
- An open-drain status output (CHRG_OK, PG, STAT) needs a pull-up to **3.3 V**, either on the
  carrier (3V3 is not at the footprint: wire from J1.29/30 or J2.05/06) or via a firmware change to
  `INPUT_PULLUP`. The pin must never see more than 3.3 V.
- An unpowered charger must read as "not ready", which is low or open. Use the I2C status as the
  primary readiness source, as with the Ag105 Table 6.

### 3.4 Battery detection and CV sensing through D-BT-SQ

- **EN low:** the RT1987 isolates fully ([RT] p.14). The charger's battery pin sees only C-D11
  (10 uF) and its own output capacitors, i.e. "no battery".
- **EN high (the normal state: raised in bring-up and never lowered, State 99 included,
  [FW] 12782, 12938):** ideal diode. While VCHG < VBT the TRCB condition keeps the FET off with no
  fault flag ([RT] p.15). The charger still sees an open output until it drives VCHG above
  VBT + ~35 mV. Then the FET turns on, auto-restarting without soft-start ([RT] p.15 Table 1).
- The RT1987 draws its supply from its own VIN, which is VCHG, the charger output. D-BT-SQ
  therefore only becomes active once VCHG passes UVLO (3.0-3.35 V rising, [RT] p.7). Whether a
  second tD_ON (8 ms) applies when UVLO clears with EN already high: the datasheet does not say
  (UNVERIFIED, measure).
- **Requirements that follow:**
  1. The charger must enable its output with no battery detected, or let battery detection be
     disabled, and ramp a voltage-regulated output from ~0 V to above the pack. A charger that
     refuses to start without seeing a battery voltage will never start here.
  2. Its "battery voltage" ADC/feedback reads VCHG, not the pack. Idle readings are meaningless, so
     firmware uses the board V_batt ADC (pin 25). Option: give a charger with a separate
     battery-sense pin a Kelvin connection to VBT at C-D12 under the footprint.
  3. Auto-recharge: after termination VCHG decays (only 10 uF plus the charger's own feedback
     divider), so a standalone charger will see "battery low/absent" and restart. The Ag105 repeated
     its Bring-Up this way [INC]. Firmware must disable charging after termination (enable low and/or
     input switch open).
  4. Option to remove these issues: bridge D-BT-SQ, so the pack sits on the charger output. The
     charger is then battery-biased and keeps its config, but **it must then block battery ->
     input back-feed** (EVM input-FET bypass jumpers must not be fitted), and firmware loses its
     hard battery-side disconnect. Operator decision (section 8).

## 4. R3 hazard: no bus-fed charging in Run

Rule R3 ([P37] 3.3): the regen switch may be closed only while the bus cannot supply the charger.
The planned firmware layers: (1) a 1 kHz interlock that closes REGEN only while calibrated
V_rgn > V_bus + margin; (2) an in-charger input threshold above the bus; (3) a backstop detector.
The charger must provide layer 2 by itself, independent of firmware.

**Feature required:** an input-voltage threshold below which the charger takes no charge power.

| Feature type | Strength | Note |
|---|---|---|
| Programmable hysteretic input UVLO / EN-UV divider (converter OFF below it) | **Preferred: a hard off** | Switching the divider between two values gives the two modes |
| Input-voltage regulation (VINDPM / MPPT-style) | Acceptable as layer 2 | A regulation loop, not an off: from a stiff 15.8 V bus with the threshold above it, charge current goes to ~0. Bench-verify ~0 A. Must also be stable from a high-impedance source (VESC regen + CAL 470 uF on V-MOT) |
| Input current limit (IINDPM, input-side sense) | Bound only | Limits case C to a known level. Not an interlock |

**Thresholds (two modes, selected per closed switch):**

| Mode | Source | Threshold window | Recommended | Reasoning |
|---|---|---|---|---|
| FC charge (FC_CHARGE 1) | VBUS via D-BC-FC, ~15.8 V, droops under load | above `LIMIT_V_BUS_MIN` 12.0 V + margin, below the droop-loaded bus | **13.5 V** (13.0-14.0 V) | Lets the charger back off before an FC-only bus collapses. Matches the fw v24 Ag105 window 12.32-13.38 V ([FW] 2516-2517) |
| Regen (REGEN 1) | V-MOT via D-BC-RG | min >= 18.0 V (`LIMIT_V_BUS_MAX` 17.5 V + 0.5 V); physically strict min 18.3 V (TPS61288 OVP min, [TPS] p.6); max <= 20.0 V (>= 1.4 V below the 21.4 V clamp) | **19.0 V nominal, tolerance keeping it within 18.3-20.0 V** (i.e. <= +/-3.5 %) | Strictly above any voltage the boosts can put on the bus, so bus feed is impossible through layer 2. When the charger loads V-MOT, V-MOT settles at the threshold while regen current is available |
| Default (reset, unconfigured, either source) | - | the regen (high) value, or charging disabled | - | Fail-safe toward "bus cannot feed the charger" |

Range requirement for a programmable threshold: >= 12.5-19.5 V. The 19 V setting must be on-scale.

**Mode switching:**
- **By I2C:** volatile settings must be written after every charger power-up and before charging
  is enabled. The FC-mode value is written only while FC_CHARGE is high. On FC_CHARGE fall the value
  returns to the regen value, or the charger loses power anyway.
- **By hardware (preferred where possible):** a threshold-select resistor switched by a small FET
  whose gate follows the `FC_CHARGE_ENABLE` net (bodge wire from J1.45/46). FC_CHARGE high selects
  13.5 V, anything else gives 19.0 V. The RT1987 tD_ON of 8 ms ([RT] p.7) means the select line
  settles before VCHG-IN appears. The default (pin low or floating) is the high, safe threshold.
- Neither replaces firmware layers 1 and 3 or the fw v37 rev 2 `J` guards (G1 bus-side
  I_fc + I_batt > 1.0 A / 5 ms; G2 unaccounted bus power > 3 W / 20 ms; G3 GENSTAT fault class;
  reboot-only trip latch; CLAUDE.md 2026-11-04 addendum). Those must be ported to the new charger.

## 5. Timing: regen start-up latency

Under R3 layer 1 the charger is UNPOWERED until V-MOT is above the bus, so every regen burst is a
cold start. The burst is above bus level for roughly 0.2-0.5 s of a 0.3-0.6 s event ([P37] 3.2).

| Step | Duration | Source |
|---|---|---|
| Firmware detects V_rgn > V_bus + margin (1 kHz loop plus a short dwell) | ~2-3 ms | design target, [P37] 3.3 |
| D-BC-RG turn-on delay tD_ON | 8 ms typ | [RT] p.7 |
| D-BC-RG ramp, 10-90 % | 1.4 ms at 21 V (tON = (VIN/35) x (CSS/0.0023 - 100) us, CSS = 5.6 nF, C-DC8) | [RT] p.15, [BOM]/[SCH] |
| Charger POR, input-valid deglitch, internal regulator up | **charger-dependent** | candidate datasheet |
| Config writes, if volatile (~6 writes x ~0.36 ms at 100 kHz, spread over loop ticks) | ~2-3 ms | computed |
| Charger soft-start to set current | **charger-dependent** | candidate datasheet |
| D-BT-SQ: VCHG must pass UVLO (3.35 V), possibly + 8 ms tD_ON, then exceed VBT | 0-8 ms, overlaps the charger ramp | [RT] p.7, UNVERIFIED for the UVLO case |
| **Board overhead total** | **~12-20 ms** | |

**Requirement:** from input power applied to charge current >= 90 % of the setpoint:
**<= 30 ms target, <= 100 ms hard maximum.** The target gives ~50 ms total onset, which captures
>= ~75 % of the shortest burst. Above ~100 ms only the tail is captured ([P37] 3.2, M1 table).
The Ag105 took ~11.7 s to bring its output up to the pack ([INC]: 0.64 V/s from ~2 V). Charger
data sheets often list an adapter-detect deglitch of tens to hundreds of ms. That number must be
read for every candidate, and measured (M1).

Stop: firmware opens REGEN as V-MOT falls back toward the bus. The charger must accept abrupt
input loss mid-charge (no reverse current is possible: D-BT-SQ blocks) and restart cleanly on the
next burst, with no latched fault that needs a power cycle.

FC-charge mode has no such constraint: the window is seconds long.

## 6. Hot-plug: inrush into the charger input capacitance

- **RT1987 slew is independent of VIN:** dV/dt = 0.8 x VIN / tON = 28 V / (CSS/0.0023 - 100) us =
  **12.0 V/ms** for CSS = 5.6 nF ([RT] p.15). This matches the typical 1.9 ms at 28 V ([RT] p.7:
  0.8 x 28 / 1.9 = 11.8 V/ms). The ramp from 0 to 15.8 V takes ~1.3 ms; to 21 V, ~1.75 ms.
- **Inrush = C_total x 12 mA/uF.** The board contributes C-D8 + C-D10 = 20 uF nominal (less after
  DC bias, UNVERIFIED), i.e. 0.24 A.
- **Limits:**
  1. RT1987 start-up SCP: the current limit starts at 2.5 A and trips after 250 us continuously
     clamped, then restarts after 64 ms ([RT] p.15). A hard ceiling.
  2. **FC-charge mode, binding:** the inrush comes from an FC-only bus through the FC boost's sense.
     `OC_FC` latches on one raw sample > 1.4 A bus-side ([FW] 2090), and the inrush lasts ~1.3 ms,
     so a 1 kHz sample will catch it. Budget: (20 uF + C_chg) x 12 mA/uF + I_aux (~0.15 A) +
     charger draw during the ramp <= ~1.0 A, giving **C_chg <= ~50 uF effective.** Hard upper bound
     ~80 uF (1.4 A with no margin).
  3. **Death-5 class:** the Ag105's advice of 470 uF across the input for long leads ([AG] p.6)
     would draw 470 uF x 12 mA/uF = 5.6 A. That is the same slew and capacitance class as the
     MOT_PWR hot-plug that killed a boost (CLAUDE.md §2, `docs/boost-bringup-debug.md` Death 5).
     **No bulk electrolytic on VCHG-IN.** If an EVM carries one, remove it or count it.
- The charger must not start switching during the 1.3-1.75 ms ramp (UVLO >= ~10 V or a start
  delay), or its draw adds to the inrush at low input voltage.
- Regen-mode inrush comes from V-MOT (CAL 470 uF + VESC), which is stiff. The same capacitance cap
  applies because the same parts are present.
- Output side: when D-BT-SQ first conducts it re-closes without soft-start (TRCB auto-restart). The
  charger's own current limit bounds the step.

## 7. Mechanical and footprint facts

- **Footprint:** 2 x SIL rows, 25.00 mm apart (x = 1.5 and 26.5 local), 2.54 mm pitch, 10 pins
  (left) + 12 pins (right), 1.1 mm drilled square pads [BRD]. The Ag105 datasheet recommends
  1.1 +/- 0.05 mm holes for 0.64 mm pins ([AG] p.21). That pitch and pin size are standard
  0.1" headers.
- **Silkscreen outline:** 32.0 x 34.8 mm, absolute x 17.20-49.20, y 32.84-67.64 [BRD]. Ag105 body
  28.6 +/- 1.5 x 33.1 +/- 1.5 mm, ~9 mm component height above the module PCB (1.6 mm), with the
  keep-out drawn under and around the module ([AG] p.21, figure reading).
- **Parts already inside the keep-out, under the module** [BRD]: D-BT-SQ (RT1987, VDFN 3 x 3),
  C-D11, C-D12 (0805, <= 1.10 mm by IPC name), C-DC11, C-DC12 (0402, <= 0.60 mm). A replacement
  carrier must clear them: >= 2.54 mm standoff, like the Ag105.
- **Neighbours (bounding-box gap to the outline)** [BRD]:

  | Side | Part | Gap | Height |
  |---|---|---|---|
  | Right | CO-5V tant 3528 | 0.1 mm | 2.1 mm |
  | Right | REG-5V LM1084 TO-263 (heat source) | 1.8 mm | 4.83 mm (IPC name) |
  | Top | OP-FC SOIC-8 | overlaps 0.3 mm | ~1.75 mm, UNVERIFIED |
  | Top | MDAC-FC, FC droop network, L-FC | beyond | - |
  | Bottom | C4A/B/C-BT 1210 | 0.3 mm | 1.35 mm |
  | Bottom | BAL BQ29200 + CBL*/RB* | ~0.5 mm | - |
  | Bottom | REG-BT (TPS61288) | further down | - |
  | Left | J-NTC, J-BL terminal blocks (7.62 mm pitch) | 0.8-0.9 mm | UNVERIFIED |

  Board 131.1 x 98.0 mm, 2 layers, 1 oz per DRC. Only two mounting holes (3.8 mm, at (3.3, 3.3) and
  (3.3, 94.7)), none near CHG.
- **Area available:** the footprint itself, ~32 x 35 mm (~1100 mm²), boxed in on all four sides.
  - **A carrier PCB <= ~32 x 35 mm plugged into the 22 holes is the cleanest fit.** Use 0.1" header
    pins, >= 2.54 mm standoff, total height ~13 mm like the Ag105 (2.54 + 1.6 + 9, figure reading).
    The 11 floating holes give mechanical anchoring (VSEL, CSEL, NC1-3, MPPTSEL, LDIS, VLOAD+/-).
  - **An EVM larger than ~32 x 35 mm** must either hover on that carrier above its neighbours (clear
    the terminal blocks and the 4.83 mm LM1084; the LM1084 heats the space above it) or go
    **off-board on leads**.
  - Off-board leads: ~2.5 A battery side, ~1.5 A input side, twisted pairs as short as possible.
    Any input bulk capacitor the long leads seem to need falls under section 6.
- **Board copper to the pads:** VCHG-IN 1.524 mm trace, ~110 mm long (~35 mOhm), from
  D-BC-FC/D-BC-RG at the bottom edge (x 77-95, y 2-10). VCHG is a polygon under the footprint
  (x 20.1-28.7, y 43.3-50.0). GND pours on both layers [BRD].

## 8. Open questions (for the operator / bench)

1. **V-MOT peak above the 21.4 V clamp** during hard regen (scope V-MOT and VCHG-IN, true scale). It sets the input abs-max class and whether C-D8/C-D10 (25 V) must go.
2. **Keep or bridge D-BT-SQ** (section 3.4 item 4). Keeping it requires a charger that starts with no battery seen, plus a cold-start config on every input cycle. Bridging it needs input back-feed blocking and loses the hard battery disconnect.
3. **Does the second RT1987 tD_ON (8 ms) apply** when D-BT-SQ's VIN passes UVLO with EN already high? The datasheet is silent. Measure; it enters the regen latency budget.
4. **Pack data:** maximum charge current, and whether the RC pack has a protection PCM. The BQ29200 OUT is orphaned, so the board has no hardware OV action.
5. **Is an NTC fitted at J-NTC on the vehicle?** TS / THERM handling on the carrier depends on it.
6. **Teensy 4.1 pad state during reset** (keeper / pull): sizes the charger-side pull-down on pin 5 (PJRC/NXP, UNVERIFIED).
7. **FC-mode input current budget:** the actual aux load and FC boost droop at ~1 A, so the charge-current ceiling in FC mode can be set from measurement.
8. **As-built copper weight and effective C-D8/C-D10 capacitance** at 16-21 V bias (path drop, inrush).
9. **Damage status after the 2026-11-04 incident:** D-BC-RG, D-BT-SQ, the Ag105, and the FC channel (zero current after the event, [INC]). Check them before any Path A engagement.
10. **Pin-function changes** (pin 5 becomes an enable, pin 6 an open-drain status, any spare pin) must be entered in the IO CSV first; the CSV is authoritative. Firmware scope: replace `pollAg105()` / `initAg105Charger()` / `ag105IsReady()`, the reg-0x02 MPPT manager and the `J` session. `chargerHasPower()` stays. The `AG105_VBATN_ISOLATED` gate becomes a "charger return verified" gate.
11. **Thermal:** the LM1084 sits 1.8 mm away. Charger losses at 2.5 A (~2-3 W) under any enclosure are unassessed.
12. **Hardware threshold select keyed to `FC_CHARGE_ENABLE`** (section 4) versus I2C-only switching: the operator chooses between a bodge wire and firmware complexity.
