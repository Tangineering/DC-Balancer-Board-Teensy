# Dossier: Analog Devices (Linear Technology) LTC4015 on the custom charger board (2026-11-10)

This dossier evaluates the LTC4015 synchronous buck charge controller as the charger IC of the custom charger board (CCB)
that replaces the Silvertel Ag105 (BOM `CHG`) on board rev 20260622. It builds on the 2026-11-05 round-2 dossier
(`docs/reviews/charger_eval_2026-11-05/round2/dossier_LTC4015.md`, cited as **[R2]**). Facts that [R2] read from the primary
datasheet are re-verified here against the same primary; facts that rested on the DC2039A demo board are re-derived for a
custom layout.

Status codes follow EVAL section 1.2: P = PROVEN_DATASHEET, C = PROVEN_CALC, B = BENCH_GATE, F = FAIL, U = UNKNOWN or missing
primary, sys = blocked at system level.

---

## 1. Identity and sources

### 1.1 Part

| Item | Value | Source |
|---|---|---|
| Part | LTC4015, multichemistry buck battery charger controller with digital telemetry system | [DS] p.1 |
| Orderable part numbers | LTC4015EUHF#PBF, LTC4015EUHF#TRPBF (E grade: specified 0-85 °C junction, -40 to 125 °C by design); LTC4015IUHF#PBF, LTC4015IUHF#TRPBF (I grade: specified -40 to 125 °C) | [DS] p.3 Order Information; p.9 Note 2 |
| Package | UHF, 38-lead 5 mm x 7 mm plastic QFN, 0.50 mm pitch, exposed pad (pin 39) = GND | [DS] p.3, p.74 |
| Thermal | theta_JA = 34 °C/W, T_JMAX = 125 °C | [DS] p.3 |
| Recommended choice | LTC4015IUHF#PBF (the CCB sits beside power stages; the I grade carries the tolerance over the full junction range) | [DS] p.9 Note 2 |

### 1.2 Documents

| Tag | Document | Revision read | Location | Fetch |
|---|---|---|---|---|
| [DS] | LTC4015 data sheet, 76 pp | Rev B (footer "4015fb") | Mirror https://www.rlocman.ru/i/File/2017/09/30/4015fb.pdf; local copy not retained in the repository; the page citations are the record | fetched and read 2026-11-10 (ADI vendor sweep) |
| [R2] | Round-2 dossier (DC2039A EVM evaluation) | 2026-11-05 | `docs/reviews/charger_eval_2026-11-05/round2/dossier_LTC4015.md` | repository |
| [EVAL] | `docs/charger_replacement_evaluation_2026-11-05.md` | 2026-11-05 | repository | - |
| [CRIT] | `docs/reviews/charger_ic_search_2026-11-10/screening_criteria.md` | 2026-11-10 | repository | - |
| [SCR] | `docs/reviews/charger_ic_search_2026-11-10/screening.md` | 2026-11-10 | repository | - |
| [R6] | `docs/reviews/charger_eval_2026-11-05/round3/review_loop.md`, round 6 | 2026-11-05/06 | repository | - |

Page numbers are the printed data-sheet page numbers, which equal the PDF page numbers. The demo manual DC2039A (read by
[R2]) is used here only for the observation that the stock 0.22 uF VC network is MPPT compensation ([R2] section 3 H4); no
layout information was needed from it.

### 1.3 Secondary sources (UNVERIFIED)

| Fact | Source | Status |
|---|---|---|
| Distributor stock and price snapshots | findchips.com aggregate page, fetched 2026-11-10; web-search snippets of Mouser.ca and DigiKey.com.br listings | UNVERIFIED |
| Lifecycle status | Not obtained (analog.com product page timed out) | U |
| Whether a revision later than Rev B exists | Not obtained (analog.com blocked) | U |

---

## 2. Architecture on the custom board

### 2.1 Topology

The LTC4015 is a synchronous step-down (buck) controller. All power switches are external ([DS] p.14, p.40, p.43):

- top and bottom N-channel MOSFETs of the buck, driven from TG/BG with a bootstrap diode and capacitor ([DS] p.44 Fig. 12);
- an N-channel input ideal-diode MOSFET (INFET) from VIN to SYS ([DS] p.18);
- a P-channel output ideal-diode MOSFET (OUTFET) from BAT to SYS ([DS] p.18);
- an input sense resistor RSNSI between CLP and CLN, in the VIN-to-SYS leg (high-side; [DS] p.14, p.18);
- a charge sense resistor RSNSB between CSP and CSN, in series with the inductor on the battery side (high-side; [DS] p.13,
  p.42).

SYS is the maximum of VIN and VBAT and is the supply of the internal INTVCC regulator ([DS] p.14 pin 31). The buck converts
from SYS to BAT. No path exists from SYS to BAT except through the buck, and the INFET blocks SYS to VIN ([DS] p.18).

### 2.2 Position between VCHG-IN and VCHG

| CCB node | LTC4015 node | Remark |
|---|---|---|
| VCHG-IN (Ag105 pad 10, from D-BC-RG and D-BC-FC) | VIN, through the INFET to SYS via RSNSI | Input sense on the high side; INFET reverse turn-off -30 mV, fast-off at VSYS - 25 mV ([DS] p.6, p.18) |
| VCHG (Ag105 VBAT+ pads 18 and 19, input of D-BT-SQ) | BAT side of RSNSB (CSN); BATSENS Kelvin | Charge sense on the high side |
| GND (Ag105 GND pads) | GND, SGND, exposed pad | One node: M1 holds by construction |
| SDA, SCL (pads) | SDA, SCL; DVCC to the Teensy 3V3 pull-up rail | [DS] p.13 pin 3 |
| STAT (pad, Teensy pin 6) | SMBALERT (open drain) | [DS] p.8, p.19 |
| MPPTD (pad, Teensy pin 5) | P5, the only Teensy output on the 22 pads. The CCB derives both inhibit stages from it: DRVCC enable = P5 AND NOT trip (trip = the latched fault of the system core); UVCLFB clamp release (PERMIT) = GATE AND P5, where GATE is the H1/H2 hardware permit (section 5.4). This is the split of [EVAL] section 4.1 (/CE from P5 AND NOT trip, ILIM_HIZ from GATE); no second Teensy pin is needed | The IO CSV must be amended before any pin reuse (CSV-wins rule) |

### 2.3 What the plug-in board carries

The CCB carries the LTC4015, the two buck FETs, the INFET and the OUTFET, the inductor, RSNSI and RSNSB, the SYS and BAT
capacitors, the UVCLFB divider, the VC network, the CCREF 301k 0.1 % resistor, the NTC bias network, the CELLS/CHEM straps,
the IC-specific interlock adders of section 9, and the system-level interlock core (H1, H2, C7, OVN, eFuse) shared by every
candidate ([CRIT] section 1.2).

### 2.4 System dependency: the D-BT-SQ bridge

The LTC4015 starts every new charge cycle with a 2-4 s battery detection test at a 1 mA load; if the voltage is unstable it
runs an open/short test at minimum current for 1-2 s ([DS] p.30). A new cycle starts when input power is cycled, when
suspend_charger is toggled, or after a system fault ([DS] p.28 Fig. 5A note, p.32). With D-BT-SQ in series, the charger output
VCHG is a capacitive node that the pack cannot back-feed, so detection runs against about 30 uF ([R2] H7). This dossier
therefore assumes the [R2] disposition: a motherboard bridge across D-BT-SQ, so that BAT sits on the pack and the IC stays
powered from the pack through the OUTFET ([DS] p.14, p.18). The bridge is a motherboard rework outside the CCB (sys). Section
14 records that the bridge element should be a fuse, not a 0 Ohm link.

The bridge has two further costs:

1. **Lost pack isolator.** D-BT-SQ is the only Teensy-controlled switch between the charger output and the pack. The board
   interface spec makes "the charger's output never sees the pack directly" a design property, and its decision 2 states that
   bridging "loses the hard battery disconnect" (spec.md section 0 item 2, section 6 decision 2). With D-BT-SQ kept, firmware
   that detects a charger power-stage fault can open D-BT-SQ as a second cut beside the eFuse and the input RT1987s. With the
   bridge, a top-FET short is bounded only by the eFuse on VCHG-IN ([EVAL] section 2.7, "Charger HS FET short"), and a
   bottom-FET short is a pack short through the inductor and RSNSB that only the bridge fuse clears (section 5.5).
2. **Off-CCB rework.** VBT is reachable only at C-D12, under the footprint, not at one of the 22 pads (spec.md section 1). The
   bridge is therefore a motherboard element, which conflicts with the brief that the charger, the power stage and the interlock
   all sit on the CCB. One option keeps the fuse on the CCB and adds one flying lead from the CCB to VBT at C-D12.

The bridge fuse needs a continuous rating of at least 3.3 A (ICHG maximum 3.297 A, section 7.1) and a clearing I2t below the
withstand of the pack wiring and the VCHG copper for a pack short. The part is not selected: TODO(verify: fuse datasheet, pack
short-circuit current).

---

## 3. Must-have check

| ID | Requirement ([CRIT] section 2) | Result | Value and basis | Citation |
|---|---|---|---|---|
| M1 | Common ground, no return-path element | **Pass (P)** | RSNSB in CSP-CSN (battery side of the inductor), RSNSI in CLP-CLN (input side); GND, SGND and the paddle are one node | [DS] p.13-15, p.42 |
| M2 | Abs max >= 35 V on every VCHG-IN pin; operation to 22.28 V; no OVP at or below 22.28 V | **Pass (P for VIN, CSN; C for SYS, CLP, CLN, INFET)** | VIN, CSN abs max -0.3 to 40 V. SYS, CLP, CLN, INFET, CSP and BATSENS have no absolute rating, only relative limits (CLP, CLN to SYS; CSP, BATSENS to CSN); their 35 V figure is the operating range (VSYS 3.05-35 V, CLP/CLN common mode 4-35 V), so the >= 35 V claim for those pins is an inference. 22.28 V is inside every range. OVLO rising 37.7 V min / 38.6 V typ / 39.5 V max, 1.4 V hysteresis | [DS] p.3, p.4, p.41 |
| M3 | CV 8.400 V settable, +-1.0 % total over temperature | **F (as written)** | VCHARGE(TOL) +-1.25 % over junction temperature for all chemistries. Code 31 (4.200 V/cell): 8.295-8.505 V, upper bound 21 mV above 8.484 V. Code 30 (4.1875 V/cell): 8.270-8.480 V, upper bound holds, lower bound 46 mV below 8.316 V. No code meets +-1.0 % on both sides. **The code-30 setting is POR-volatile:** at POR en_jeita = 1, so CV comes from vcharge_jeita_3 (default 4.20 V/cell), and VCHARGE_SETTING defaults to 0x3F. After every charger POR the CV is therefore 4.20 V/cell (8.295-8.505 V) until firmware writes en_jeita = 0 and VCHARGE_SETTING again. Open ruling R-M3 | [DS] p.4, p.5, p.22, p.34, p.60 |
| M4 | >= 3.1 A at 8.4 V, <= 2 W loss | **Pass (C)** | ICHG full scale 32 mV/RSNSB; RSNSB 10 mOhm gives 3.105-3.297 A at code 31; loss estimate 1.2 W (section 11), figure reading <= 2.0 W | [DS] p.5, p.42, p.10 G05 |
| M5 | Hard inhibit pin, acts from POR without I2C | **Conditional (c, B)** | No dedicated inhibit pin. Two pin-level mechanisms: UVCLFB below the regulation point gives zero charge current ("at 1.15V the charge current is zero", p.13); DRVCC below 3.9 V turns the controller off (p.41). The UVCLFB mechanism is register-defeatable: VIN_UVCL_SETTING = 0x00 prevents input undervoltage regulation (p.46). The DRVCC mechanism exits through a new charge cycle (cold). Section 5 | [DS] p.13, p.28, p.41, p.46 |
| M6 | Fail-safe default; no NVM enabling autonomous charge | **Pass (C)** | No EEPROM or OTP; registers reset to defaults at POR and on ship-mode exit (p.23). The fail-safe level is built with INTVCC-biased pull-ups (section 5). Out of POR the IC charges autonomously only from VIN above about 18.1 V (zero-current point, typical), with full current above 18.92 V, at CV 4.20 V/cell (M3). Under the D-BT-SQ bridge a charger POR occurs only on pack removal or ship-mode exit; a Teensy reset leaves the last register image in place (section 5.4) | [DS] p.13, p.22, p.23, p.50, p.60 |
| M7 | Hardware ceiling from POR that no register can raise | **Pass (P)**, on condition that SYS carries no load other than the IC | Input ceiling 32 mV/RSNSI and charge ceiling 32 mV/RSNSB; IIN_LIMIT_SETTING and ICHARGE_TARGET default to their maximum codes and can only lower them; cycle-by-cycle peak 47-57 mV/RSNSB. The input loop "can only reduce charge current to zero, it cannot limit the overall input current which is a function of the load on VSYS": on the CCB SYS has no external load, so 32 mV/RSNSI bounds the input. A SYS-node fault (CSYS short, OUTFET fault) is bounded by the eFuse, not by RSNSI. One value only (no mode switch); section 7 | [DS] p.4, p.6, p.18, p.27, p.40, p.42, p.50 |
| M8 | Runtime input-voltage regulation 13.5-15 V and 18.5-19.5 V; zero current below threshold without shutdown; <= 10 mA draw | **Pass (P range); U/B draw (at risk)** | UVCL: (code + 1) x 4.6875 mV at UVCLFB, 8 bits, default 0xFF = 1.2 V; with k = 15.766: 18.92 V at 0xFF, **14.04 V at code 189**, LSB 74 mV. UVCL "can only reduce charge current to zero". Draw in the hold state (cc_cv_charge, UVCL at zero current, switcher not suspended) is not tabulated; the datasheet gives the minimum current to operate the charger as "generally approximately in the range 5mA to 20mA" (p.46), and section 11.2 estimates IQ about 4 mA plus gate drive 10 mA. The <= 10 mA criterion is therefore at risk, not only a bench item. (The p.4 figures 3.00 mA, "Charging, Switcher Suspended", and ISYS 3.65 mA, "Charging, VBAT > VCHARGE", belong to other states and are not hold-state evidence.) VIN pin < 140 uA (no maximum published) | [DS] p.4, p.18, p.22, p.41, p.46, p.60 |
| M9 | No cold restart in the regen path | **Conditional (c, B)** | Threshold crossing: no state change; the charger returns to suspended only for VIN within 100 mV of BATSENS, suspend_charger = 1, or a system fault (Fig. 5A note); soft-start runs only "when charging is enabled" (p.40). Per-burst inhibit exit (UVCLFB release): no state change. Any VCHG-IN collapse to within 100 mV of BATSENS starts a new cycle with 2-4 s detection | [DS] p.28, p.30, p.40, p.41 |
| M10 | I2C 100 kHz, 3.3 V logic, no back-powering | **Pass (P)** | Address 1101_000[R/W] = 0x68; 400 kHz max; VIH 70 % DVCC, VIL 30 % DVCC with DVCC 1.6-5.5 V tied to the pull-up rail; SDA/SCL abs max -0.3 V to DVCC; IDVCCQ 0 uA; leakage +-1 uA | [DS] p.3, p.8, p.13, p.19 |
| M11 | Charge-current telemetry >= 50 Hz | **Pass (P)** | IBAT register 0x3D; seven ADC channels at about 1.6 ms each, so each channel refreshes about every 11 ms | [DS] p.20 |
| M12 | Runtime input-current and charge-current control | **Pass (P)**, programmable chemistry only | IIN_LIMIT_SETTING 0x15, 25 mA steps at 20 mOhm; ICHARGE_TARGET 0x1A, 100 mA steps at 10 mOhm (en_jeita must be 0). In a fixed chemistry the charger setting registers 0x1A-0x2E are read-only, which fails M12 for the charge current | [DS] p.50, p.54 note 2, p.60 |
| M13 | Lifecycle Active | **Conditional (U)** | analog.com product page not reachable; distributor snapshots show stock (UNVERIFIED) | section 13 |

The LTC4015 fails one must-have (M3) as written and carries conditional passes on M5, M9 and M13. It stays in the finalist
set only under the declared exception of [SCR] section 4.3.

---

## 4. Requirement status (HR1-HR5, H1-H12)

The table follows the layout of [EVAL] section 1.2. The design assumed is the recommended design A of section 9 (I2C-set
threshold and input limit, D-BT-SQ bridged, 10 nF VC network).

| Req | LTC4015 on the CCB | Basis |
|---|---|---|
| HR1 regen | **B** (C capacity; B warm response; sys M-R3) | Input >= 24.0 W at the threshold at a 7.4 V pack (section 11); warm path is the VC slew only, estimated 0.07-0.2 ms with a 10 nF VC (section 8), conditional on L-3 confirming that a VC capacitor of about 47 nF or less is stable on the regen node; error-amplifier current limits unpublished; VESC behaviour at a 19 V hold is the system gate M-R3 |
| HR2 FC | **P** charger / **sys** | IIN 1.00 A at code 39, 25 mA steps, UVCL FC threshold 14.04 V (code 189), a bus-collapse guard only; the purge and budget issues are system-level ([EVAL] section 3.4) |
| HR3 loop | **C** | Buck: VIN must exceed BATSENS by 140-250 mV before charging and charging stops within 100 mV ([DS] p.4, p.41), so a boost-passthrough bus cannot charge the pack; INFET blocks pack to VCHG-IN; the H1/H2/C7 interlock covers the rest; the eFuse covers a top-FET short. The D-BT-SQ bridge removes the Teensy-controlled pack isolator, so a power-stage fault has one cut fewer than in the BQ25798 design (section 2.4, 5.5) |
| HR4 runaway | **C** regen; FC mode **C** for design B only, **operator ruling** for design A | Regen ceiling 1.553-1.649 A by RSNSI 20 mOhm (P), with SYS unloaded (M7). Design A has no hardware FC ceiling: the FC bound is the IIN register (1.00 A) backed by the 1.65 A hardware value, which exceeds H-20 P_MAX (1.247 A) and the OC_FC 1.4 A latch. OC_FC is firmware and needs a running Teensy. The [EVAL] section 2.3 residual loop L-F (D-BT-EN shorted, I_BT below the BT_ACT trip) is bounded in the BQ25798 design by the hardware FC ILIM ceiling 0.74-0.96 A; in design A it is bounded by a register value and 1.65 A of hardware. Design B restores a hardware FC ceiling of about 1.0 A (section 7.3) |
| HR5 fail-safe | **C (B for the DRVCC stage and the latencies; sys MCU watchdog)** | Converter-off by DRVCC gating (B: the DRVCC UVLO is not a documented control input) and zero current by UVCLFB clamp (pin, default inhibit), both biased from INTVCC; no NVM; no host watchdog, so the MCU watchdog is mandatory. Under the bridge the IC keeps its register image across a Teensy reset, so HR5 "no autonomous charge from stored settings" needs the boot rule of section 5.4 |
| H1 ground/sense | **P** | Section 3 M1 |
| H2 inhibit | **P** mechanism / **B** latency | UVCLFB clamp: zero current documented, latency set by the unpublished UVCL amplifier current (7-180 us estimate); DRVCC cut: converter off, about 0.1-0.2 ms (estimate) |
| H3 fail-safe | **C** | Section 5.4 |
| H4 threshold | **P** range / **B** warm, taper, hold draw | 18.92 V +-1.2 % at code 0xFF; LSB 74 mV; full-scale accuracy only; taper 1.2 -> 1.15 V typical only |
| H5 FC | **P** current and termination / **F** CV against +-0.5 % | CV +-1.25 % ([DS] p.4); same issue as M3; H5 asks for +-0.5 % |
| H6 ratings | **P** (VIN, CSN) / **C** (other VCHG-IN pins) | 40 V abs max on VIN and CSN; 35 V operating range on SYS, CLP, CLN (section 3 M2); OVLO 37.7 V min; CCB FETs and capacitors chosen at >= 40 V |
| H7 D-BT-SQ | **P** bridged (**sys**) / **U** kept | Bridged: BATSENS on the pack, registers persist; kept: detection against 30 uF and an undocumented constant-peak-current mode below BATSENS 2.4 V (section 14) |
| H8 inrush | **C** | 0.89 A nominal including 0.15 A aux; 0.67 A at an assumed 70 % DC-bias retention (section 12.3) |
| H9 I2C/logic | **P** | Section 3 M10 |
| H10 thermal | **C** | Power stage 1.2 W estimate; IC 0.27 W, about 9 °C rise (section 12) |
| H11 stock | **U** | Section 13 |
| H12 telemetry | **P** | IBAT, IIN, VIN, VSYS, VBAT, die temperature, NTC ratio, coulomb counter (section 10) |

---

## 5. Hard inhibit and fail-safe

### 5.1 Inhibit mechanisms

| Mechanism | Action | Default with the Teensy absent | Exit re-runs | Latency |
|---|---|---|---|---|
| **UVCLFB clamp** (CCB N-FET from UVCLFB to GND) | UVCL loop regulates charge current to zero: "Maximum charge current is tapered off when this pin is below 1.2V, at 1.15V the charge current is zero" ([DS] p.13). The charger stays in cc_cv_charge ([DS] p.28) | Inhibit, if the clamp gate is pulled up from INTVCC (section 5.4) | No state change: UVCL is a loop, not a state of Fig. 5A ([DS] p.28) (P). No soft-start on release: **C (inferred)**. The datasheet does not state it; p.40 runs soft-start "when charging is enabled", and p.71 ramps ICHARGE_DAC for "digital soft-start/stop" as a function of charger state, NTC and settings. Bench gate L-3 is the proof (CHARGER_STATE stays cc_cv_charge, ICHARGE_DAC does not ramp from 0) | Not published. Estimate: gate rise about 1 us with a 10k pull-up; VC slew 0.9 V at the UVCL amplifier current. Linear gm 1.06 mS x 1.2 V = 1.27 mA into 10 nF gives about 7 us; an amplifier current saturating at 50 uA gives about 180 us. **B** |
| **DRVCC gate** (CCB load switch from INTVCC to DRVCC) | Controller off when DRVCC < 3.9 V ([DS] p.41); DRVCC undervoltage lockout is a system fault ([DS] p.28) | Off, if the load-switch enable is pulled down | New charge cycle: 2-4 s battery detection, then soft-start up to 12.4 ms ([DS] p.30) | Not published. Estimate: DRVCC 2.2 uF from 5.0 to 3.9 V at a gate-drive draw of about 10 mA gives about 0.24 ms; an active bleed shortens it. During this decay the converter can still switch with reduced gate drive. The datasheet characterizes DRVCC = INTVCC (EC conditions, p.4) or an external LDO/DC-DC from VSYS (p.41); the UVLO used as a commanded inhibit is not a documented control input. **B** |
| **VC clamp** (optional CCB N-FET from VC to GND) | VC "normally ranges from 900mV to 2.4V"; the current comparator threshold rises with VC ([DS] p.13). Below 0.9 V no top-FET turn-on is expected | As the UVCLFB clamp, if biased the same way | Nothing documented | Gate plus VC discharge, about 1 us. External forcing of VC is **not documented** in [DS]: **B/U** |
| suspend_charger (0x14 bit 8) | Charger suspended | 0 = charging enabled at POR ([DS] p.50) | New cycle with 2-4 s detection ([DS] p.32) | Not published. Register-only: fails M5 on its own |
| VIN_UVCL_SETTING above VIN (0x16) | Zero current | 0xFF = divider maximum | Nothing | VC slew. Register-only |
| ICHARGE_TARGET / IIN_LIMIT_SETTING minimum | Not an inhibit: minimum 1 mV/RSNSB and 0.5 mV/RSNSI ([DS] p.5, p.60) | - | - | - |
| NTC forced out of the JEITA window | Charger off in regions 1 and 7; NTC_PAUSE returns to the previous state ([DS] p.28, p.34) | - | Nothing | ADC cycle about 11 ms ([DS] p.20): too slow for H1 |
| Ship mode (ARM_SHIP_MODE 0x19 = 0x534D) | Acts only when VIN < about 1 V; cannot be disarmed; all registers reset on exit ([DS] p.22-23, p.60) | - | - | Not an inhibit; on the never-write list |

### 5.2 Register defeat of the UVCLFB clamp

The datasheet states that "input undervoltage regulation can be prevented by setting VIN_UVCL_SETTING to its lowest value
(0x00)" ([DS] p.46). At code 0x00 the UVCLFB reference is 4.6875 mV, and a grounded UVCLFB is only about 5 mV below it,
inside the 50 mV taper band of p.13. The UVCLFB clamp then does not guarantee zero current. M5 therefore passes only under
the [CRIT] M5 proviso: the POR value (0xFF) enables the mechanism, and firmware must hold VIN_UVCL_SETTING at or above a floor
with readback. A floor of code 150 (11.2 V, 0.7 V at UVCLFB) keeps the grounded pin at least 0.66 V below the zero-current point
of every permitted code. The floor value is a design choice (C); the taper width below code 0xFF is typical only and unpublished
(TODO(verify: 4015fb, taper versus code)).

### 5.3 Single-bit address error on mode writes

The two mode registers are 0x15 (0b0001_0101) and 0x16 (0b0001_0110). The data written in a mode change are 0x003F or 0x0027
(39) to 0x15, and 0x00FF or 0x00BD (189) to 0x16. The register map ends at 0x4A, and "registers 0x17, 0x18, 0x49 are reserved
and should not be written" ([DS] p.49, p.54). The eight single-bit errors of each address land as follows ([DS] p.49-54,
p.30, p.32, p.62):

| Bit | 0x15 becomes | 0x16 becomes | Effect of the mode-write data |
|---|---|---|---|
| 0 | 0x14 CONFIG_BITS | 0x17 reserved | 0x14: see the CONFIG_BITS table below. 0x17: effect undocumented, **U** (TODO(verify: 4015fb, reserved register behaviour)) |
| 1 | 0x17 reserved | 0x14 CONFIG_BITS | As bit 0 |
| 2 | 0x11 QCOUNT_HI_ALERT_LIMIT | 0x12 QCOUNT_PRESCALE_FACTOR | Coulomb-counter alert limit or scale corrupted; telemetry only |
| 3 | 0x1D MAX_CV_TIME | 0x1E MAX_CHARGE_TIME | 0x1D = 39 or 63 s: timer termination after about 1 min of CV, then no charge until VBAT < 97.5 % of VCHARGE ([DS] p.32, p.62). 0x1E = 189 or 255 s: max_charge_time fault after 189-255 s of charging, exited only through VBAT < 35 % of VCHARGE, VIN within 100 mV of BATSENS, a suspend toggle or a system fault ([DS] p.30, p.62). Both are fail-off (lost harvest), not runaways |
| 4 | 0x05 VSYS_LO_ALERT_LIMIT | 0x06 VSYS_HI_ALERT_LIMIT | Alert limits only; at most a spurious SMBALERT |
| 5 | 0x35 CHARGE_STATUS (read-only) | 0x36 LIMIT_ALERTS (read; writing 0 to a bit clears it) | 0x35: write to a read-only register, effect undocumented but no setting exists to change. 0x36: may clear latched limit alerts |
| 6 | 0x55 | 0x56 | Outside the published map; effect undocumented, **U** |
| 7 | 0x95 | 0x96 | Outside the published map; effect undocumented, **U** |

For the two CONFIG_BITS rows, the written data set the following bits ([DS] p.50):

| Intended write | Data | CONFIG_BITS bits set | Effect |
|---|---|---|---|
| 0x16 = 0xFF (regen threshold) | 0x00FF | 0-7, including bit 3 mppt_en_i2c | **MPPT enabled**: the algorithm sweeps VIN_UVCL_SETTING across its range ([DS] p.18) and can settle below the bus voltage |
| 0x16 = 189 (FC threshold) | 0x00BD | 0, 2, 3, 4, 5, 7 | **MPPT enabled**, coulomb counter on, forced measurement, BSR run |
| 0x15 = 0x3F (regen limit) | 0x003F | 0-5 | **MPPT enabled** |
| 0x15 = 39 (FC limit) | 0x0027 | 0, 1, 2, 5 | Coulomb counter on, BSR run; benign |

Suspend_charger is bit 8, so no mode-write datum (all below 0x0100) sets it. MPPT moves the threshold, not the current
ceilings. In regen mode the H1 permit and the UVCLFB clamp still forbid bus-fed conversion; in an FC window H2 permits it, and
the IIN register bounds it. The timer cases stop charging. The address-error analysis therefore shows **no documented runaway
path; the reserved register 0x17 and the unmapped addresses 0x55/0x56/0x95/0x96 are undocumented targets (U)**. Firmware must
read back, after every mode write, CONFIG_BITS, MAX_CV_TIME and MAX_CHARGE_TIME (and SYSTEM_STATUS bit 11 mppt_en_pin,
[DS] p.53), and treat mppt_en_i2c = 1 or a timer value different from the configured one as a fault (write suspend_charger = 1
and latch). This is the LTC4015 counterpart of [R6] finding 1's address-error analysis (section 14).

### 5.4 Fail-safe construction (HR5)

The fail-safe design uses two independent stages, both biased from the LTC4015's own INTVCC (5 V, [DS] p.5, p.14), so that the
inhibit level exists whenever the IC can switch:

1. **Converter-off master (DRVCC gate).** A load switch feeds DRVCC from INTVCC. Its enable has a pull-down and is driven by
   P5 AND NOT trip (section 2.2). Teensy unpowered, in reset, high-Z or hung low: DRVCC is unpowered, the controller is off
   ([DS] p.41), and SYSTEM_STATUS drvcc_good reads 0 ([DS] p.53) for readback. The datasheet sequencing rule (DRVCC only after
   INTVCC > 3 V, [DS] p.14, p.41) holds because the switch is supplied from INTVCC. However, the datasheet characterizes only
   DRVCC = INTVCC or an external supply from VSYS; switching DRVCC to use its UVLO as a commanded inhibit is not a documented
   control input, and the converter can switch with reduced gate drive during the decay from 5.0 to 3.9 V. This stage is
   therefore **B** (bench gate L-11). The exit is cold (2-4 s detection), so this stage is used only at Run entry, at Run exit
   and on latched faults.
2. **Per-burst zero-current clamp (UVCLFB).** An N-FET clamps UVCLFB to GND. Its gate has a 10k pull-up to INTVCC, and a second
   N-FET, driven by PERMIT = GATE AND P5 with a pull-down, pulls the gate low to release the clamp. PERMIT absent, unpowered or
   LOW gives clamp ON. This stage carries the H1 hard-stop and is warm on exit.

**Boot rule (Teensy reset with the charger image retained).** Under the D-BT-SQ bridge the LTC4015 is powered from the pack at
all times (section 2.4), so a Teensy reset, a watchdog reset or a reflash does not reset the charger. The retained image can
hold the FC threshold (code 189 = 14.04 V, below the 16 V bus), the FC IIN value, a latched suspend, or a corrupted value.
Before the first P5 HIGH after any Teensy boot, firmware writes VIN_UVCL_SETTING = 0xFF and the regen IIN value, reads both
back, reads CONFIG_BITS, MAX_CV_TIME and MAX_CHARGE_TIME, writes en_jeita = 0 and VCHARGE_SETTING (M3), and detects a charger
POR with a canary register (a non-default value in an otherwise unused writable register, for example an alert limit with its
alert disabled). Firmware treats SYSTEM_STATUS mppt_en_pin = 1 at boot as a fault that blocks P5.

Case analysis:

| Case | DRVCC gate | UVCLFB clamp | Result |
|---|---|---|---|
| Teensy unpowered or in reset | Off (P5 pull-down) | On (INTVCC pull-up) | No conversion; RT1987 EN pull-downs also open the input switches |
| Teensy hung with outputs latched HIGH | On | Follows PERMIT, which still needs H1 (regen) or H2 (FC) in hardware | Bounded by the interlock; **no host watchdog in the LTC4015** ([R2] C8; register map [DS] pp.49-54), so the MCU watchdog of [EVAL] section 5.1 is mandatory. In an FC window with a stale or corrupted IIN, design A is bounded only by the 1.65 A hardware value (section 7.3) |
| Teensy reset, watchdog reset or reflash with the charger image retained (bridge) | Off during reset; on after boot only through P5 | On during reset | The image may carry the FC threshold below the bus; no conversion while P5 is LOW. Safe by hardware during the reset; the boot rule above restores the regen image before P5 HIGH. HR5 "no autonomous charge from stored settings" depends on that rule (C) |
| I2C dead or stuck | Unaffected | Unaffected | Last register image persists; hardware stages still inhibit |
| Charger POR (pack removal or ship-mode exit only, under the bridge) | Unaffected (hardware) | Unaffected | Registers at defaults: UVCL 0xFF = 18.92 V, zero-current point 17.92 V worst low, so zero charge current from a bus at or below 17.5 V (quiescent draw only); IIN and ICHG at the resistor ceilings; CV 4.20 V/cell (M3) |
| Charger POR with a failed-FB boost (bus 18.3-19.5 V, [EVAL] section 2.7) | Unaffected | Follows PERMIT | The POR threshold no longer blocks bus draw. In regen mode H1 still blocks (fall trip >= 20.52 V at a 19.5 V bus). In an FC window H2 releases the clamp: a double fault bounded by the 1.65 A hardware ceiling |
| CCB stage failure (clamp FET A1 open, or release FET A2 shorted) | DRVCC stage still available | Lost | H1 and H2 do not act on the RT1987 EN pins ([EVAL] section 4.1: D-BC-RG EN "Not gated" by H1); they reach the charger only through the clamp release. The remaining layers are the UVCL threshold (soft) and the firmware F1 cross-check within 6 ms, as in the [EVAL] section 2.7 "Comparator stuck HIGH" row. A double fault with a stale threshold is bounded by the regen ceiling of 1.65 A. The optional A5 VC clamp shares the A1 gate net, so it adds no independence from an A2 short unless it has its own release path |

HR5 status: **C** for the UVCLFB construction and the boot rule, **B** for the DRVCC stage and the latencies, **sys** for the MCU
watchdog.

### 5.5 Single faults of the bridged power stage

| Fault | Path | Bound |
|---|---|---|
| Top-FET short | VCHG-IN -> inductor -> RSNSB -> bridge -> pack | eFuse on VCHG-IN ([EVAL] section 2.7, "Charger HS FET short"); the RT1987 input switches have no current limit after tON. With D-BT-SQ kept, firmware could also open D-BT-SQ; under the bridge that layer is lost |
| Bottom-FET short | Pack -> bridge -> RSNSB -> inductor -> bottom FET -> GND | A pack short. Only the bridge fuse clears it (section 2.4); the eFuse is on the input side and does not see it |
| OUTFET short | VCHG-IN -> INFET -> SYS -> shorted OUTFET -> BAT -> bridge -> pack | With VIN above VBAT the input reaches the pack without the buck. The input loop cannot limit it, because it acts only on charge current ([DS] p.18). Bound: the eFuse on VCHG-IN (C). With D-BT-SQ kept, firmware could also open D-BT-SQ |

---

## 6. Input-voltage regulation and POR behaviour

| Item | Value | Source |
|---|---|---|
| Loop | UVCL: regulates UVCLFB to (VIN_UVCL_SETTING + 1) x 4.6875 mV by reducing charge current; "can only reduce charge current to zero" | [DS] p.18, p.60 |
| Range at the pin | 4.6875 mV to 1.200 V, 8-bit DAC | [DS] p.4, p.22 |
| Accuracy | 1188/1200/1212 mV at code 0xFF over junction temperature (+-1 %); lower codes: LSB only | [DS] p.4 |
| Zero-current point | 1.15 V at code 0xFF, typical only | [DS] p.13 |
| Divider | R_top 158k, R_bot 10.7k, 0.1 %: k = 15.766 ([R2] E4). The datasheet gives two clamp figures: "about 2.5V with 200uA" (p.9 Note 4, p.13) and "the clamp begins to engage at 2V nominally" (p.45). The bound used here is the 2 V engage point. At 22.28 V the pin sits at 1.41 V, a margin of 0.59 V | [DS] p.9 note 4, p.13, p.45 |
| Regen threshold (code 0xFF) | 18.92 V nominal; with +-1 % reference and +-0.2 % ratio: **18.69-19.15 V** full-current point; zero-current point 18.13 V nominal, 17.92 V worst low (C) | calculation |
| FC threshold (code 189) | k x 190 x 4.6875 mV = **14.04 V** (code 188 gives 13.97 V); accuracy unspecified at this code | calculation, [DS] p.60 |
| Resolution | 74 mV per code at k = 15.766 | calculation |
| POR value | 0xFF, the divider maximum; the register can only lower the threshold | [DS] p.22, p.60 |
| What resets it | POR of the digital section and ship-mode exit ([DS] p.23); MPPT, if enabled, rewrites it ([DS] p.60). No watchdog exists | [DS] p.23, p.49-54, p.60 |
| Write rule | "Do not write to the VIN_UVCL_SETTING register when MPPT is enabled" | [DS] p.45 |
| Autonomous charging at POR | Yes, from any VIN above 18.13-18.92 V: suspend_charger = 0, ICHARGE at 32 mV/RSNSB and CV 4.20 V/cell (JEITA region 3 with a 10k fixed NTC resistor; en_jeita = 1 at POR), IIN at 32 mV/RSNSI. From a bus at or below 17.5 V (latched OV) the charge current is zero; the quiescent draw remains | [DS] p.22, p.34, p.50, p.60 |

The regen zero-current point (17.92 V worst) sits 0.42 V above the 17.5 V `LIMIT_V_BUS_MAX` latch and 1.9 V above the 16.0 V
bus nominal. For a bus at or below 17.5 V, a charger POR inside an FC window therefore returns the charger to a state in which
it cannot draw charge current from the bus; FC charging resumes only after the firmware writes code 189 with readback. A
failed-FB boost (bus 18.3-19.5 V, [EVAL] section 2.7) defeats this property (section 5.4). Under the D-BT-SQ bridge a charger POR
occurs only on pack removal or ship-mode exit; the common reset events (Teensy reset, watchdog, reflash) leave the charger image
in place, and the boot rule of section 5.4 covers them.

Write order with readback ([R2] section 5, kept): entering FC, write IIN first and the threshold last; leaving FC, raise the
threshold first and IIN afterwards. A failed write in either direction leaves the high-threshold state.

---

## 7. Hardware input-current ceiling after POR (HR4)

### 7.1 Ceilings

The input ceiling is the full-scale servo voltage 32 mV across RSNSI; the register can only lower it ([DS] p.18, p.42, p.50).
The loop acts on charge current only: it "cannot limit the overall input current which is a function of the load on VSYS"
([DS] p.18, p.27, p.40). The ceiling below is therefore an input ceiling only while SYS carries no load other than the IC, which
holds on the CCB. A SYS-node fault (CSYS short, OUTFET fault) is bounded by the eFuse, not by RSNSI.
The regulated tolerance is +-2.0 % of full scale over junction temperature ([DS] p.4). With RSNSI = 20 mOhm, 1 %:

- I_IN,max = 32 mV x 1.02 / (20 mOhm x 0.99) = **1.649 A**;
- I_IN,min = 32 mV x 0.98 / (20 mOhm x 1.01) = **1.553 A**.

The charge-side ceiling is 32 mV/RSNSB +-2.0 %; with RSNSB = 10 mOhm, 1 %: **3.105-3.297 A** ([DS] p.4). The cycle-by-cycle
peak limit is 47-57 mV/RSNSB = 4.7-5.7 A ([DS] p.6).

### 7.2 Regen mode

Required input at the 23 W pass condition and the lowest full-current threshold: 23 W / 18.69 V = 1.231 A. The ceiling minimum
1.553 A gives 29.0 W at 18.69 V, so the input ceiling does not limit HR1; the charge-side ceiling does (section 11). The ceiling
maximum, 1.649 A, sits between the 1.40 A and 1.72 A rows of the [EVAL] section 2.5 hard-stop table (allowance 125 us by the
constant-margin model at VBUS 15.9 V: 302.8 uC / 1.649 A - 59 us = 124.6 us).

### 7.3 FC mode

The FC budget is about 1.0 A of bus current. The LTC4015 has one RSNSI, so the hardware ceiling cannot switch with FCC_net
without CCB adders. Design A therefore bounds FC mode by three layers:

1. IIN_LIMIT_SETTING code 39: (39 + 1) x 0.5 mV / 20 mOhm = **1.000 A**, step 25 mA ([DS] p.60). Accuracy below full scale is
   not published (TODO(verify: 4015fb, ICL accuracy at 20 mV)).
2. After a charger POR the threshold returns to 18.92 V, so charge current from a bus at or below 17.5 V is zero; the FC
   configuration needs a deliberate write. Under the bridge a charger POR occurs only on pack removal or ship-mode exit, so this
   layer rarely acts. A register corruption or a firmware fault that leaves IIN high involves no POR, and this layer does not
   help.
3. The only hardware value behind the register is 1.649 A, above the H-20 P_MAX (1.247 A bus) and the 1.4 A OC_FC single-sample
   latch. With a running Teensy, OC_FC faults the vehicle to State 99 with all paths off. OC_FC is firmware: with a hung Teensy
   (pins frozen, H2 HIGH) and a stale IIN value, only the 1.65 A hardware value remains.

Design A therefore has **no hardware FC-mode ceiling**. This reopens the [EVAL] section 2.3 residual loop L-F (D-BT-EN shorted,
I_BT below the BT_ACT trip of 0.11-0.29 A, lasting for the window). The BQ25798 design bounds it by the hardware FC ILIM ceiling
0.74-0.96 A ([EVAL] sections 2.3, 3.4, 4.1); design A bounds it by a register value of 1.00 A backed by 1.65 A of hardware. This
bound needs an operator ruling (R-FCA, section 15.1) beside the [EVAL] section 2.3 residual. [CRIT] section 2 (M7 note) records
that a single fixed ceiling passes M7 and loses points in S3.

Design B (section 9.3) splits RSNSI into a series pair with a bypass switch keyed to FCC_net, which gives a hardware FC ceiling
of about 1.0 A that holds after POR and closes the reopened residual. It costs six further adders and forfeits the
POR-to-regen-only property only if the threshold is also moved into hardware.

HR4: **C** in regen mode; in FC mode **C** for design B and an **operator ruling** for design A. M7: **P** (single value, SYS
unloaded). S3 score: 1 for design A; 3 for design B (continuous analog loop, published +-2 % full-scale accuracy; evidence C).

---

## 8. Warm response and hard-stop timing ([EVAL] section 3.2)

### 8.1 What the datasheet gives

- The UVCL loop reduces charge current without a state change; the charger leaves cc_cv_charge only for VIN within 100 mV of
  BATSENS, suspend_charger = 1, or a system fault ([DS] p.28 Fig. 5A note).
- Soft-start (ICHARGE_DAC ramp at 400 us per LSB, maximum 12.4 ms) runs "when charging is enabled" after detection
  ([DS] p.30, p.40); ICHARGE_DAC is ramped for "digital soft-start/stop" as a function of charger state, NTC and settings
  ([DS] p.71). The datasheet does not state whether a UVCL release triggers a ramp; the absence of one is inferred from Fig. 5A,
  where UVCL is not a state (C), and bench gate L-3 is the proof.
- The VC node is shared by the input-current, charge-current, VBAT and UVCL loops, and "all require a 6.8nF to 14.7nF
  capacitor from the VC node to ground"; hundreds of nF apply only to MPPT with resistive sources above 0.5 Ohm ([DS] p.42).
  The DC2039A's 0.22 uF network is therefore not a constraint on the CCB ([R2] H4).
- Transconductances: CC 4.10 mS, UVCL 1.06 mS, ICL 4.10 mS, CV (2 cell) 0.15 mS ([DS] p.7). Amplifier output-current limits,
  loop bandwidth and VC clamp levels are **not published**.

### 8.2 Estimates (C on the model, B on the numbers)

| Event | Model | Result at C_VC = 10 nF | Result at C_VC = 0.22 uF ([R2] stock) |
|---|---|---|---|
| Warm response: V-MOT crosses the threshold from below | VC rises from the hold level to the full-current level (delta <= 1.5 V, VC range 0.9-2.4 V, [DS] p.13) at the CC amplifier current; linear limit 4.1 mS x 32 mV = 131 uA | <= 0.12 ms linear; 0.75 ms if the amplifier delivers only 20 uA; inductor slew (19 - 8.4) V / 15 uH = 0.7 A/us adds about 5 us | 2.5 ms linear |
| Hard stop by the UVCLFB clamp | Gate rise about 1 us (10k pull-up into about 100 pF); VC fall 0.9 V at the UVCL amplifier sink current | 7 us (linear, 1.27 mA) to 180 us (50 uA saturation) | 0.16 ms linear |
| Hard stop by the VC clamp (option) | FET discharge of 10 nF through about 1 Ohm | About 1 us plus gate rise | - |
| Hard stop by the DRVCC gate | DRVCC 2.2 uF from 5.0 to 3.9 V at about 10 mA | About 0.24 ms | - |

Requirement: tau_warm <= 4 ms (10-90 % <= 9 ms; <= 2 ms at board-only capacitance), hard stop <= about 115 us after H1 trips
([EVAL] section 2.5, 3.2). The warm budget holds with a factor of about 5 or more even if the CC amplifier current saturates at
20 uA. The hard-stop budget holds for the UVCLFB clamp only if the UVCL amplifier sinks at least about 80 uA (0.9 V x 10 nF /
112 us); this is unpublished, so the VC clamp is recommended as a parallel stage on the same gate signal, subject to bench proof
that forcing VC causes no adverse behaviour.

### 8.3 Loop stability on the regen source

The datasheet compensation guidance covers stiff and resistive sources ([DS] p.42). The regen source is a VESC current source
into about 470 uF plus the TL431/BSP170P clamp. UVCL stability on that node is **not documented**: bench gate L-3 / [EVAL]
M-R4 with the CCB VC network.

The 10 nF value of C_VC is load-bearing. The S1 score, the M9 and H2 statuses and the hard-stop path of 7-180 us all assume it,
so they are conditional on L-3 confirming a stable VC capacitor of about 47 nF or less. If stability needs the DC2039A-class
0.22 uF, the section 8.2 table gives a 2.5 ms warm response, which meets the 4 ms limit but fails the 2 ms limit at board-only
capacitance, and a linear UVCLFB hard stop of 0.16 ms, which exceeds 115 us. At 0.22 uF the VC clamp (A5) becomes a required
stage, HR1 warm response becomes F at board-only capacitance, and S1 stays 2 on its documentation anchor but loses its
quantitative support.

### 8.4 Condition for staying warm

The warm path requires VCHG-IN to stay above BATSENS + 100 mV between bursts ([DS] p.41). In the always-powered design D-BC-RG
is closed through Run except inside an FC window, where IO CSV row 31 holds REGEN LOW. D-BC-RG re-closes in the FC -> regen
handover of [EVAL] section 4.4. An open input path longer than the hold-up time starts a new cycle with 2-4 s detection.
With 40 uF falling 16 -> 8.5 V (300 uC) and the operating draw of 5-20 mA ([DS] p.46, section 3 M8), the hold-up is
15-60 ms (C). The handover budget of [EVAL] section 4.4 is about 10-12 ms. Over 12 ms the droop is
5-20 mA x 12 ms / 40 uF = 1.5-6.0 V, which leaves VCHG-IN at 10.0-14.5 V, above BATSENS + 100 mV (about 8.5 V). At the
40 ms upper bound of [EVAL] section 0.1 ruling 3, a 20 mA draw gives a 20 V droop and a cold re-entry. The S1 score 2 (B)
below therefore depends on the 12 ms handover budget.

S1 score 2 (evidence B; conditional on L-3, section 8.3). S5 score 1 (no published latency).

---

## 9. Interlock hardware around the LTC4015 versus the BQ25798 design

### 9.1 System-level core (not counted)

H1 comparator, H2 FC permit with BT_ACT, C7 qualifier, OVN from the BQ29200 OUT, eFuse on VCHG-IN, the heartbeat and FCC/RGN
level sensing, and the MCU watchdog are identical for every candidate ([CRIT] section 3.3).

### 9.2 Design A adders (recommended)

| # | Adder | Function | Parts |
|---|---|---|---|
| A1 | UVCLFB clamp N-FET + 10k gate pull-up to INTVCC | Per-burst zero-current inhibit, default ON | 2 |
| A2 | PERMIT-driven release N-FET + gate pull-down | Releases A1 only when PERMIT is HIGH | 2 |
| A3 | Load switch INTVCC -> DRVCC + enable pull-down | Converter-off master, default OFF | 2 |
| A4 | D-BT-SQ bridge as a fuse (motherboard, or on the CCB with one flying lead to VBT at C-D12) | Keeps BAT on the pack (section 2.4) and fuses the new pack path (section 14) | 1 |
| | **Total** | | **7** |

Optional A5: VC clamp N-FET on the A1 gate net (1 part, total 8), pending the bench result of section 8.2. On the A1 gate net it
adds no independence from an A2 short; an independent release path costs one or two more parts.

Design A reaches 7 adders partly by omitting a hardware FC ceiling (section 7.3). The BQ25798 count includes that function
(R_FC and Q3). A like-for-like comparison is therefore design B (13 adders).

### 9.3 Design B adders (hardware mode switching)

Design B adds, to design A:

- an UVCLFB divider switch (one resistor and one N-FET keyed to FCC_net) that lowers the threshold to about 14 V in hardware;
- an RSNSI series pair with a high-side P-FET bypass driven through an N-FET level shifter and two resistors, keyed to FCC_net,
  which sets a hardware FC ceiling of about 1.0 A and a regen ceiling of about 1.6 A.

Design B totals 13 adders (S6 = 0). Mode changes then need no I2C write, which closes [R6] findings 8 and 12, but a charger POR
inside an FC window keeps the 14 V threshold and relies on the hardware FC ceiling instead of the POR-to-regen-only property.

### 9.4 Comparison with the BQ25798 design (WD)

| BQ25798 interlock element | LTC4015 design A |
|---|---|
| /CE open-drain drive and REGN-biased pull-ups | Replaced by A1/A2 (UVCLFB clamp, INTVCC-biased) |
| ILIM_HIZ hold-down and release transistors | Replaced by A3 (DRVCC gate) as the converter-off stage |
| Third ILIM resistor and switch keyed to FCC_net | **Replaced by a register bound** (IIN code 39) backed by the 1.65 A hardware value; the hardware FC ceiling is lost and the [EVAL] section 2.3 L-F residual reopens (section 7.3). Returns as hardware in design B |
| `CHG_QUAL AND NOT P5` gates (1G04, 1G08) | **Removed**: the LTC4015 has no input-qualification window with a hardware ceiling to release |
| D-BT-SQ disposition | Bridge (fused) instead of keeping D-BT-SQ and managing the BAT 2.5 V hold and BATOVP cycling. The bridge removes the Teensy-controlled pack isolator (section 2.4) |
| Never-write list (OTG, EN_EXTILIM, PTM bits) | Never-write list: mppt_en_i2c = 1, ARM_SHIP_MODE, VIN_UVCL_SETTING below the floor, the reserved registers 0x17, 0x18, 0x49. Pin straps instead of registers: CELLS, CHEM, and the MPPT and EQ pins tied to GND by direct copper ("GND this pin if unused, do not float", [DS] p.13 pin 13, p.14 pin 21) |

S6 scores, with the [CRIT] section 3.3 count:

| Build | Adders | S6 under the band rule | S6 if A3 counts as "an adder needed to defeat a register-defeatable pin" |
|---|---|---|---|
| Design A | 7 | 1 (6-8 band) | 0 (A3 exists because VIN_UVCL_SETTING = 0x00 defeats the UVCLFB clamp, [DS] p.46) |
| Design B (parity with the BQ25798 FC ceiling) | 13 | 0 | 0 |

The BQ25798 dossier scores the baseline S6 = 0 (9 adders minimal, about 16 at single-fault parity). The [SCR] provisional
baseline S6 = 1 is superseded.

---

## 10. Telemetry and I2C

| Item | Value | Source |
|---|---|---|
| Address | 0x68 (1101_000[R/W]); no conflict on the Teensy bus, which carries only the charger today | [DS] p.8 |
| Protocol | SMBus read word / write word only; I2C-compatible; 400 kHz maximum; 50 ns spike suppression | [DS] p.8-9, p.19 |
| Logic | DVCC = Teensy 3V3 (pull-up rail); VIH 70 % = 2.31 V, VIL 30 % = 0.99 V | [DS] p.8, p.13 |
| Back-powering | SDA/SCL abs max -0.3 V to DVCC; IDVCCQ 0 uA. With the bridge the IC is powered whenever the pack is present; with the Teensy off, the pull-ups and DVCC are at 0 V | [DS] p.3, p.8 |
| ADC | 14-bit, signed 16-bit result, LSB 54.93 uV at the ADC; seven channels at about 1.6 ms each (about 11 ms per scan) | [DS] p.20 |
| IBAT (0x3D) | 1.46487 uV/RSNSB = **0.146 mA** at 10 mOhm; error +-200 uV at 0 mV (+-20 mA), +-2.5 % at 32 mV | [DS] p.7, p.20 |
| IIN (0x3E) | 1.46487 uV/RSNSI = **0.073 mA** at 20 mOhm; error +-200 uV at 0 mV (+-10 mA), +-2.5 % at 32 mV | [DS] p.7, p.20 |
| VIN (0x3B), VSYS (0x3C) | 1.648 mV; error +-100 mV at 1 V, +-1.5 % at 35 V | [DS] p.7, p.20 |
| VBAT (0x3A) | 192.264 uV per cell (Li) | [DS] p.20 |
| Accuracy caveat | The ADC error table is specified under "Battery Only Mode" conditions; accuracy while charging is not tabulated separately | [DS] p.7 |
| Coulomb counter | qLSB = prescale / (8333.33 x RSNSB); TCE +-1.5 % (10-50 mV) at 25 °C, +-2.5 % over temperature; en_qcount defaults to 0 | [DS] p.8, p.40, p.50 |
| Status | CHARGER_STATE 0x34, CHARGE_STATUS 0x35 (vin_uvcl_active, iin_limit_active, CC, CV), SYSTEM_STATUS 0x39 (charger_enabled, mppt_en_pin, drvcc_good, cell_count_error, ok_to_charge, no_rt, thermal_shutdown, vin_ovlo) | [DS] p.52-53 |
| Alert | SMBALERT open drain, abs max -0.3 V to DVCC: pull up only to the Teensy 3V3 rail (the p.8 leakage condition at 5 V is a test condition, not a rating). The motherboard STAT net must carry no pull-up to a higher rail. Cleared by an ARA read returning 0xD1 | [DS] p.3, p.8, p.19 |
| Watchdog | **None** | [DS] pp.49-54 |
| Measurement gating | The ADC does not run with the battery as the only source unless force_meas_sys_on = 1 | [DS] p.20 |

At 100 kHz a word transaction (address, command, two data bytes) takes about 0.4 ms. A mode change with readback is two writes
and two reads, about 1.6 ms, plus a CONFIG_BITS read (section 5.3).

S7: score 3 (charge current, input current and input voltage, published accuracy, about 11 ms per scan; evidence P with the
battery-only caveat).

---

## 11. Charge capability

### 11.1 Design values

| Item | Value | Basis |
|---|---|---|
| Chemistry strap | Li-Ion programmable (CHEM1, CHEM0 = L, L); en_jeita = 0 written at configuration | [DS] p.5, p.33, p.60 |
| Cell strap | 2 cells: CELLS2 = L, CELLS1 = H (INTVCC), CELLS0 = L, the EC test condition | [DS] p.4 header, p.71 |
| CV | Code 31 = 4.200 V/cell (8.295-8.505 V) or code 30 = 4.1875 V/cell (8.270-8.480 V), per ruling R-M3. Both are volatile: at POR en_jeita = 1 and CV = vcharge_jeita_3 = 4.20 V/cell until reconfigured. Mitigation option: write vcharge_jeita_n (0x25, 0x26) as well as VCHARGE_SETTING, so that a later en_jeita = 1 also selects the chosen code; this does not survive a POR either | [DS] p.4, p.22, p.34, p.51, p.60 |
| RSNSB / ICHG | 10 mOhm 1 %; code 31 = 3.20 A nominal, 3.105-3.297 A | [DS] p.4, p.60 |
| RSNSI / IIN | 20 mOhm 1 %; 1.553-1.649 A ceiling; FC code 39 = 1.00 A | section 7 |
| f_SW | 500 kHz (RT 95.3k, the EC test point; 475-525 kHz) | [DS] p.7, p.42 |
| Inductor | L = VBAT (1 - VBAT/VIN,max) / (0.25 f ICHG,max) = 8.4 x (1 - 8.4/22.28) / (0.25 x 500 kHz x 3.2 A) = 13.1 uH; choose 15 uH, I_sat >= 6 A (above the 5.7 A cycle-by-cycle maximum) | [DS] p.6, p.43 |
| Minimum on-time | 140 ns typ (EC), about 85 ns (applications text). Lowest duty 3 V / 22.28 V = 0.135 gives 270 ns at 500 kHz: no cycle skipping | [DS] p.7, p.45; [CRIT] section 4.8 item 4 |
| Maximum duty / dropout | 98.4 %; series resistance top FET 10 + DCR 25 + RSNSB 10 + RSNSI 20 + INFET 5 = 70 mOhm (assumed parts); VIN,min = (8.484 + 3.21 x 0.070) / 0.984 = 8.85 V, far below the 13.14 V FC floor | [DS] p.7; [CRIT] section 4.3 |

### 11.2 Efficiency and loss at 3.2 A, 19 V in, 8.4 V out (D = 0.442)

The loss model uses the [DS] p.44 equations with assumed parts (dual 40 V N-FET at 10 mOhm/13 mOhm hot, Q_g 10 nC each,
inductor DCR 25 mOhm). The part values are placeholders: TODO(verify: selected FET and inductor datasheets).

| Loss | Calculation | W |
|---|---|---|
| Top FET conduction | 0.442 x 3.2^2 x 0.010 x 1.3 | 0.059 |
| Bottom FET conduction | 0.558 x 3.2^2 x 0.013 | 0.074 |
| Top FET transition | 0.5 x 19 V x 3.2 A x 5.4 ns x 500 kHz (edge times from 2.0/0.5 Ohm drivers, [DS] p.7) | 0.082 |
| Dead-time body diode | 2 x 60 ns x 0.7 V x 3.2 A x 500 kHz ([DS] p.7 t_NO) | 0.134 |
| Gate charge (from SYS) | 20 nC x 500 kHz x 19 V | 0.190 |
| IC quiescent | 19 V x 4 mA ([DS] p.41) | 0.076 |
| Inductor | DCR 0.256 + core about 0.05 | 0.306 |
| RSNSB, RSNSI | 3.2^2 x 0.010 + 1.5^2 x 0.020 | 0.147 |
| INFET, recovery, other | | 0.073 |
| **Total** | | **1.14** |

Calculated efficiency: 26.9 W / (26.9 + 1.14) W = **95.9 %** (C). The datasheet curve for a 2-cell pack at 7.4 V, 4 A, on the
8 A application circuit reads about 93 % at 16-20 V input ([DS] p.10 G05, figure reading, typical); that figure bounds the loss
at about 2.0 W. M4 passes with the calculated loss and is marginal at the curve's efficiency.

### 11.3 Regen input power at the threshold (HR1)

| Pack | Charge current (minimum) | Output power | Input at eta 0.93 (curve) | Input at eta 0.959 (calc) |
|---|---|---|---|---|
| 7.4 V | 3.105 A | 22.98 W | 24.7 W | 24.0 W |
| 8.4 V (CC end) | 3.105 A | 26.08 W | 28.0 W | 27.2 W |

Every row exceeds the 23 W pass condition and the 18.9 W peak of the defining 3 -> 1 m/s brake. The input ceiling (29.0 W at the
lowest full-current threshold, section 7.2) does not bind. HR1 capacity: **C**.

### 11.4 FC mode within the 1.0 A bus budget

At IIN = 1.00 A from a 15.6 V loaded bus and an assumed 91 % efficiency at 1.7-1.9 A (between the 0.75 A and 4 A curves of
[DS] p.10 G05): P_out = 14.2 W, which gives **1.69 A at 8.4 V** and 1.92 A at 7.4 V. This exceeds the H5 1.5 A target (C).

The FC threshold 14.04 V (code 189) is a bus-collapse guard, not an FC-sag guard ([EVAL] section 3.4): the FC-mode bus is the
regulated 16 V boost output, not the stack voltage. During a purge the stack falls to about 1 V; the bus holds until the TPS61288
loses its minimum input and then falls at about 28-31 V/ms while the charger still draws 0.90-1.00 A ((0.09 + 0.90-1.00) A
/ 35 uF; I_AUX 0.09 A, C_VBUS 35 uF), so UVCL acts about 0.06-0.07 ms ((16.0 - 14.04) V / 28.3-31.1 V/ms) after the collapse
starts (0.76 ms at the aux-only 2.57 V/ms), and the aux load still takes the bus to the UV_BUS latch. The 2026-11-08 purge ruling (no FC charging during
or just before a purge, a preemptive share shift to the battery, EMS-requested charging between purges) therefore relies
entirely on the Teensy (EMS window scheduling, the H2 drop through BT_BUS), as for every candidate.

### 11.5 Termination behaviour relevant to the EMS

- Li-Ion timer termination after MAX_CV_TIME of CV time cannot be disabled; the default is 14 400 s and the register is writable
  up to 65 535 s ([DS] p.5, p.32, p.50).
- After termination the charger stays off until VBAT < 97.5 % of VCHARGE ([DS] p.5, p.32), so regen is not absorbed in that
  window; a suspend toggle restarts with 2-4 s detection.
- MAX_CHARGE_TIME (default 65 535 s, 18.2 h) can be set to 0 to disable the fault ([DS] p.50).

---

## 12. Layout, package, thermal and BOM

### 12.1 Layout

- One hot loop: CSYS, top and bottom FET, optional Schottky diodes ([DS] p.46 item 1). The CCB uses a dual N-FET in one
  package to keep the loop short.
- Kelvin routing of CSP/CSN and CLP/CLN with a 1 nF capacitor across CSP-CSN at the IC ([DS] p.46 items 4-5).
- Exposed pad stitched to a continuous ground plane on layer 2 ([DS] p.13 pin 14).
- The UVCLFB node is high-impedance and noise-sensitive; a filter capacitor to SGND may be needed ([DS] p.45). The A1/A5 clamp
  FETs sit next to the pin with short gate traces.
- The INFET and OUTFET add two further power-path parts that a monolithic part does not need (S10 = 1).
- No published reference layout for a 2S, 3 A design was read (the demo manual's layout was not used).

### 12.2 Package and thermal

QFN-38, 5 x 7 mm, 0.50 mm pitch, one exposed pad: reflow-friendly, S11 = 2 ([DS] p.3, p.74). IC dissipation
VSYS x (IQ + IG) = 19 V x (4 + 10) mA = 0.27 W, a rise of about 9 °C at 34 °C/W ([DS] p.41). The DRVCC gate of section 5.4
leaves DRVCC supplied from INTVCC, so the IC dissipation is unchanged.

### 12.3 Input capacitance and inrush (H8)

| Item | Nominal |
|---|---|
| VIN bypass on the CCB | 2 x 1 uF / 50 V |
| CSYS (ripple and RMS): 4 x 10 uF / 50 V X7R 1210; RMS <= ICHG/2 = 1.6 A ([DS] p.43) | 40 uF |
| Motherboard C-D8/C-D10 | 20 uF |
| Total on the RT1987-ramped node | 62 uF |

CSYS charges through the INFET body diode during the ramp, so it counts. Inrush at 12 mA/uF: 62 x 0.012 = 0.74 A, plus the 0.15 A
aux load = **0.89 A** nominal (11 % margin to 1.0 A). At an assumed 70 % DC-bias retention at 16 V: 0.67 A (33 % margin)
(TODO(verify: selected 1210 capacitor DC-bias curve)). No switching occurs during the ramp: a new cycle runs 2-4 s detection
first ([DS] p.30). SYS ripple at 20 uF effective: 0.525 x 0.475 x 3.2 A / (20 uF x 500 kHz) = 80 mV at 16 V ([DS] p.43). S15 = 2
on nominal values (C); 3 once the derating is confirmed.

### 12.4 BOM estimate (per board, design A)

| Group | Parts | Rough cost (USD, UNVERIFIED) |
|---|---|---|
| LTC4015IUHF | 1 | 8-17 |
| Dual N-FET buck, N INFET, P OUTFET | 3 | 2-3 |
| Inductor 15 uH / 6 A | 1 | 1-2 |
| RSNSB, RSNSI | 2 | 1 |
| Capacitors (VIN, CSYS, CBAT, INTVCC 4.7 uF, DRVCC 2.2 uF + 0.1 uF, 2P5VCC 2.2 uF, CSPM5, SYSM5, CB, VC network, filters) | about 20 | 3-4 |
| Resistors (RT, CCREF 301k 0.1 %, NTCBIAS + NTC substitute, UVCLFB divider 0.1 %, VC) | about 8 | 1 |
| Bootstrap diode | 1 | 0.2 |
| Interlock adders (section 9.2) | 7 | 2 |
| **Total** | **about 43** | **about 19-30** |

S13 band 2 (USD 15-30); capped at 1 by the UNVERIFIED prices.

---

## 13. Stock and price

| Source | Date | Data | Status |
|---|---|---|---|
| findchips.com aggregate, LTC4015EUHF#PBF | 2026-11-10 | Newark 75 (USD 7.65-11.72); ADI listing 247 (USD 7.59-16.88); Rochester 56; Bristol 25; brokers with 3 900-7 000 | UNVERIFIED |
| Web-search snippet, Mouser.ca 584-LTC4015EUHF#PBF | undated | 47 191 in stock; USD 22.28 at 1 | UNVERIFIED |
| Web-search snippet, DigiKey.com.br 505-LTC4015EUHF#PBF-ND | undated | 639 in stock; USD 15.02 at 1; 10-week standard lead time | UNVERIFIED |
| analog.com product page | 2026-11-10 | Timeout | blocked |
| digikey.com, digikey.com.br product pages | 2026-11-10 | HTTP 403 | blocked |

The I grade (LTC4015IUHF#PBF) stock was not obtained. Power-stage parts are generic (dual 40 V N-FET, P-FET, 15 uH inductor,
1 % sense resistors) with many second sources. S12 is capped at 1 (UNVERIFIED).

---

## 14. Round-6 findings of the BQ25798 carrier design

| R6 # | Finding | Class ([CRIT] section 3.4) | LTC4015 effect |
|---|---|---|---|
| 1 | VREG corruption, no fixed pack OVP (major) | IC-dependent | **Closes.** The Li-Ion CV DAC tops out at 4.2 V/cell ("To maintain inherent over charge protection, the maximum Li-Ion charge voltage level is 4.2V/cell", [DS] p.60; p.32) and the cell count is a pin strap ([DS] p.14, p.71). No register write can raise CV above 8.505 V worst case. New residual: a lifted CELLS strap (open = Z) can select a higher cell count ([DS] p.71 table); mitigation is direct copper straps, post-reflow inspection, and a boot check of VBAT x 2 against the Teensy BT_VOLTAGE; the OVN term stays as the backstop |
| 8 | 5 ms loop budget versus 1 ms deadlines (I2C burden) (major) | IC-dependent | **Keeps** (design A): a mode change is two word writes, two readbacks and a CONFIG_BITS read (about 2 ms at 100 kHz), comparable with the BQ25798 image. **Closes** in design B (no I2C per mode change) |
| 10 | `chg_src` misattributes sub-H1 regen (major) | IC-dependent | **Closes conditionally**: IIN ADC with published accuracy (+-200 uV offset, +-2.5 % at 32 mV, [DS] p.7), specified under battery-only conditions; no per-source split. Bench confirmation of the accuracy while charging (B) |
| 12 | Reversal hold unattainable at 100 kHz (minor) | IC-dependent | **Keeps** (design A); closes in design B |
| 2 | D-BT-SQ short, unfused pack on VCHG (minor) | System | **Reopens in a new form**: the bridge puts the pack permanently on the charger output, so a shorted bottom FET shorts the pack through the inductor and RSNSB, and the Teensy-controlled pack isolator is lost (section 2.4, 5.5). The bridge element must be a fuse (adder A4) |
| 3, 4, 5, 6, 7, 9, 11 | System-level or copper sizing | Not counted | Unchanged |
| 13-16 | EVM-carrier geometry | Closed by any CCB | Closed |

Net IC-dependent ledger (design A): closes 1, conditionally closes 10, keeps 8 and 12, reopens none of the IC-dependent set.
S14 = 3 (evidence C; 10 is B).

---

## 15. Open questions, bench gates and blocked fetches

### 15.1 Operator rulings

| ID | Question |
|---|---|
| R-M3 | Accept CV +-1.25 % (code 31: 8.295-8.505 V, 5 mV above `LIMIT_V_BATT_MAX` 8.5 V at the upper bound) or code 30 (8.270-8.480 V, full-charge voltage up to 1.5 % low), or widen M3. Without a ruling the LTC4015 fails M3. Code 30 is POR-volatile: after every charger POR the CV is 4.20 V/cell (8.295-8.505 V) until firmware reconfigures it, so the 8.505 V upper bound applies after each POR whatever R-M3 decides |
| R-BR | Accept the D-BT-SQ bridge (as a fuse, on the motherboard or on the CCB with a flying lead to VBT at C-D12), which removes BT_SEQUENCE_ENABLE as a charger isolator (the "hard battery disconnect" of spec.md decision 2), leaves the bottom-FET short to the bridge fuse alone, and adds a continuous 112-325 uA pack drain with telemetry off ([DS] p.4) |
| R-INH | Accept a two-stage inhibit (UVCLFB clamp warm, DRVCC gate cold) in place of a dedicated inhibit pin (M5 conditional) |
| R-FCA | Design A only: accept an FC-mode bound of the IIN register (1.00 A) backed by 1.65 A of hardware for the reopened [EVAL] section 2.3 L-F residual (the BQ25798 design holds 0.74-0.96 A in hardware), or require design B |

### 15.2 Bench gates (on a CCB prototype)

| ID | Test | Pass |
|---|---|---|
| L-1 | Stiff VIN 16.0 / 17.5 / 18.0 V, code 0xFF, bridged pack | Input <= 10 mA; abs(IBAT) <= 10 mA; vin_uvcl_active = 1 |
| L-2 | 3.2 A charging from 20 V; step the UVCLFB clamp, the VC clamp and the DRVCC gate separately | Input current < 50 mA within 115 us (UVCLFB or VC clamp); record the DRVCC figure |
| L-3 | = [EVAL] M-R4: VIN step Vth - 0.5 V -> Vth + 1 V; then a 470 uF + VESC-emulating current source | tau_warm <= 4 ms, CHARGER_STATE stays cc_cv_charge, UVCL loop stable |
| L-4 | IBAT versus VIN at codes 0xFF, 189 and the firmware floor 150; UVCLFB grounded at each code; input draw in the hold state | Zero-current point >= 17.9 V at 0xFF; zero current with the clamp at every permitted code; hold-state draw recorded against the <= 10 mA criterion |
| L-5 | RT1987 12 V/ms ramp 0 -> 16 V into VCHG-IN | Peak <= 1.0 A including aux |
| L-6 | Run-entry detection time with the bridge | cc_cv_charge within 4.5 s, no fault |
| L-7 | Single-bit address error emulation: write 0x00FF to 0x14, 0x003F to 0x1D, 0x00FF to 0x1E | Firmware detects mppt_en_i2c and the changed timer values and latches within one tick |
| L-8 | 3.2 A at 16 V and 21 V for 10 min | Component temperatures within rating; loss <= 2 W |
| L-9 | Charger POR inside an FC configuration; then a Teensy reset inside an FC configuration with the charger image retained | After POR: threshold back at 0xFF, zero current from 16 V, and VCHARGE_DAC (0x45) read to confirm the CV reverts to code 31. After the Teensy reset: no conversion before P5 HIGH; the boot rule restores the regen image and detects the canary |
| L-10 | IIN accuracy at codes 39 and 63 while charging | Error within the band used by the FC-window power-balance check |
| L-11 | DRVCC gate at 3.2 A charging: open the load switch; record FET Vgs and switching during the DRVCC decay; then re-apply DRVCC | No linear-region operation of the buck FETs beyond their SOA; re-application causes no fault state beyond the documented new cycle |
| L-12 | Post-reflow strap inspection (CELLS, CHEM, MPPT, EQ) and boot readback | SYSTEM_STATUS mppt_en_pin = 0 and cell_count_error = 0; a lifted strap blocks P5 |

### 15.3 Open technical items

1. UVCL and CC amplifier output-current limits and VC clamp levels (decide the hard-stop latency): not in [DS].
2. Behaviour with VC forced below 0.9 V (VC clamp option): not in [DS].
3. Taper width of the UVCL loop at codes below 0xFF and DAC accuracy at code 189: not in [DS].
4. Constant-peak-current mode below BATSENS 2.4 V ([DS] p.30) with D-BT-SQ kept: whether the UVCLFB clamp stops it is not
   documented. This is the main reason the bridge is required.
5. ICL accuracy below full scale (FC code 39).
6. Lifecycle status and the latest data-sheet revision.
7. Effect of a write to the reserved register 0x17 and to the unmapped addresses 0x55, 0x56, 0x95, 0x96 (section 5.3): not in [DS].
8. Hold-state input draw at zero charge current (5-20 mA operating range, [DS] p.46) against the <= 10 mA criterion.
9. Bridge fuse selection (continuous >= 3.3 A, clearing I2t against a pack short) and its location (section 2.4).

### 15.4 Blocked fetches

| URL | Reason | Needed for |
|---|---|---|
| https://www.analog.com/en/products/ltc4015.html | WebFetch timeout (60 s) | Lifecycle (M13), latest revision, price |
| https://www.analog.com/media/en/technical-documentation/data-sheets/LTC4015.pdf | analog.com blocked in this round; Rev B read from the rlocman.ru mirror | Confirm Rev B is current |
| https://www.digikey.com/en/products/detail/analog-devices-inc/LTC4015EUHF-PBF/5361644 | HTTP 403 | Stock and price |
| https://www.digikey.com.br/en/products/detail/analog-devices-inc/LTC4015EUHF-PBF/5361644 | HTTP 403 | Stock and price |
| https://www.mouser.com/ProductDetail/584-LTC4015IUHF%23PBF | Not attempted (Mouser timed out in round 2) | I-grade stock |

---

## 16. Verdict

(Superseded 2026-11-10 by scoring.md sections 2.2, 2.6 and 7: under the strict S1 reading the LTC4015 scores S1 = 1, design B
totals 46.0 (margin +5.7 over the BQ25798 at 40.3), design A totals 40.7 with S6 = 0, and condition 4 holds as 1 against 1.
The 51.0 total and the "2 against 1" reading below are kept as the dossier record only.)

**FEASIBLE_W_COND, not recommended over the BQ25798.**

The LTC4015 is technically feasible on the CCB under five conditions: an operator ruling R-M3 on the CV tolerance; a fused
bridge across D-BT-SQ (ruling R-BR), which removes the Teensy-controlled pack isolator; either design B or an operator ruling
R-FCA on the design A FC-mode bound; bench proof (L-2) that the UVCLFB or VC clamp stops conversion within about 115 us; and
bench proof (L-3) that a VC capacitor of about 47 nF or less is stable on the regen node.

Comparison with the BQ25798 baseline. The LTC4015 is stronger on four IC-level properties. Its CV DAC cannot exceed 4.2 V/cell,
which closes R6 finding 1 by IC design. It is rated 40 V on VIN and CSN with OVLO at 37.7 V minimum, which the BQ25798 (30 V)
cannot meet without a protected input. Its buck topology carries a documented 140-250 mV VIN-BATSENS differential UVLO, which
makes the boost-passthrough circulation physically impossible. Its POR threshold of 18.92 V forbids charge current from a bus at
or below 17.5 V after a charger POR. However, under the required bridge the LTC4015 is pack-powered at all times, so a charger
POR occurs only on pack removal or ship-mode exit; the common reset events (Teensy reset, watchdog, reflash) leave the charger
image in place, which can hold the FC threshold below the bus, and only a boot rule covers them (section 5.4). The POR property
also fails for a failed-FB boost at 18.3-19.5 V.

The weaknesses are as follows:

- It fails M3 as written (+-1.25 % CV), and the code-30 alternative reverts to 4.20 V/cell after every charger POR.
- It has no dedicated inhibit pin: the UVCLFB clamp is register-defeatable ([DS] p.46) and the DRVCC stage is not a documented
  control input (M5 conditional, where the BQ25798 /CE is P).
- It has no host watchdog, and any input collapse costs a 2-4 s battery detection.
- Design A has no hardware FC-mode ceiling (1.65 A hardware behind a 1.00 A register value), which reopens the [EVAL] section 2.3
  L-F residual; design B restores it at 13 adders.
- The bridge removes the hard battery disconnect and sits off the CCB.
- The hold-state draw (5-20 mA operating range) puts the <= 10 mA criterion at risk.
- The external-FET layout adds an INFET and an OUTFET.

Decision rule ([CRIT] section 3.5). The baseline is the BQ25798 dossier score of about 40 (S6 = 0); the [SCR] provisional 45
with S6 = 1 is superseded.

| Condition | Result |
|---|---|
| 1. Every must-have passes; no conditional pass on M5, M6 or M7 where the BQ25798 has P | **Fails**: M3 F (the M5 clause is surplus: the BQ25798 M5 is P on the ILIM_HIZ stop level and B on its EN_EXTILIM interaction, S1-B3) |
| 2. Margin >= 10 points | Design A: 45.7-49.0, margin about 6-9 points depending on the S6 reading (section 9.4); not decisive. Design B: 51.0, margin about 11. Against the BQ25798 uncapped sensitivity (about 46) every build falls below 10 |
| 3. Reopens no major IC-dependent R6 finding | Holds (finding 1 closed, 8 kept, 10 conditionally closed) |
| 4. S1 >= the BQ25798 S1 | Holds (2 against 1), conditional on L-3 |

The verdict rests on condition 1. The LTC4015 is therefore recorded as an alternate at most, and only after rulings R-M3, R-BR
and R-FCA (or design B) and the bench gates L-2 and L-3. It does not beat the BQ25798 by enough to switch.

### 16.1 Score detail ([CRIT] section 3.1)

| Criterion (weight) | Score | Evidence | Points |
|---|---|---|---|
| S1 warm response (15) | 2 | B (conditional on L-3, section 8.3) | 10.00 |
| S2 fail-safe POR (10) | 1 | P | 3.33 |
| S3 ceiling quality (8) | 1 (design A); 3 (design B) | P / C | 2.67 / 8.00 |
| S4 threshold quality (8) | 2 | B (zero-current point 1.15 V typical only, [DS] p.13; 18.13 V nominal, below the 18.5 V M8 floor; section 4) | 5.33 |
| S5 inhibit latency (7) | 1 | U | 2.33 |
| S6 interlock adders (10) | 1 or 0 (design A, 7 adders, section 9.4); 0 (design B, 13 adders) | C | 3.33 or 0 / 0 |
| S7 telemetry (5) | 3 | P | 5.00 |
| S8 FC-mode fitness (6) | 0 (CV +-1.25 %) | P | 0.00 |
| S9 rating margin (4) | 1 (40 V) | P | 1.33 |
| S10 layout (7) | 1 | P | 2.33 |
| S11 package (3) | 2 | P | 2.00 |
| S12 stock (5) | 1 | UNVERIFIED cap | 1.67 |
| S13 cost (2) | 1 | UNVERIFIED cap | 0.67 |
| S14 round-6 findings (5) | 3 | C | 5.00 |
| S15 input capacitance (3) | 2 | C | 2.00 |
| S16 topology barrier (2) | 3 | P | 2.00 |
| **Total** | | | **Design A 49.0 (S6 = 1) or 45.7 (S6 = 0); design B 51.0** |

Changes from the [SCR] provisional scores: S7 2 -> 3 (published accuracy and an 11 ms scan), S14 2 -> 3 (finding 1 closed by the
4.2 V/cell DAC ceiling), S15 3 -> 2 (nominal capacitance on the CCB gives 11 % margin, below the 30 % anchor until the DC-bias
derating is confirmed). S6 is given as a range and design B is scored separately (section 9.4).

Sensitivity of S1. The S1 = 2 anchor requires documentation that the inhibit exit has no soft-start. For the UVCLFB release this
is inferred (C, section 5.1), not stated. If S1 is read as 1 ("no documentation either way"), every total falls by 5.0 points and
condition 4 still holds (1 against 1).

---

## 17. Verification log

Two independent reviews of the first version of this dossier were re-checked against [DS] (4015fb, the local copy and its
per-page text) and against the repository documents cited in each row.

| # | Finding | Severity | Disposition | Basis |
|---|---|---|---|---|
| 1 | Address-error enumeration in 5.3 incomplete (0x1D, 0x1E, 0x17 and others) | Major | Applied | [DS] p.49 (0x17, 0x18, 0x49 reserved), p.50 (0x1D, 0x1E), p.30 and p.62 (timer effects), p.54 (map ends at 0x4A). 5.3 now lists all 16 single-bit targets; readback set extended; conclusion restated as "no documented runaway path; undocumented targets U" |
| 2 | CV code 30 is POR-volatile; CV reverts to 4.20 V/cell after POR | Major | Applied | [DS] p.60 (en_jeita = 1 default; VCHARGE_SETTING controlled by vcharge_jeita_n), p.34 (region 3 4.20 V), p.22 (VCHARGE_SETTING default 0x3F). M3, M6, section 6, 11.1, R-M3 and L-9 updated |
| 3 | FC threshold at code 188 is 13.97 V, not 14.05 V | Minor | Applied | 189 x 4.6875 mV x 15.766 = 13.97 V; design code changed to 189 (14.04 V) in M8, HR2, section 6, 5.3, 5.4, 11.4 and L-4 |
| 4 | Hold-state draw mis-cited; 5-20 mA operating range | Minor | Applied | [DS] p.4 (3.00 mA = "Charging, Switcher Suspended"; ISYS 3.65 mA = "Charging, VBAT > VCHARGE"), p.46 (5-20 mA). M8 now U/B at risk; 8.4 hold-up recomputed at 5-20 mA (15-60 ms; handover droop 1.0-4.0 V); "no draw" changed to "zero charge current; quiescent draw only" |
| 5 | Abs max 40 V applies to VIN and CSN only | Minor | Applied | [DS] p.3 (VIN, CSN -0.3 to 40 V; other pins relative limits only), p.4 (VSYS 3.05-35 V, CLP/CLN common mode 4-35 V). M2 and H6 split P/C |
| 6 | SMBALERT is not 5 V tolerant | Minor | Applied | [DS] p.3 (SMBALERT -0.3 V to DVCC); p.8 5 V is a leakage test condition. Section 10 Alert row corrected |
| 7 | ICL does not limit total input with a SYS load | Minor | Applied | [DS] p.18 ("cannot limit the overall input current"), p.27, p.40. Condition "SYS unloaded" added to M7, 7.1 and HR4; SYS-node faults assigned to the eFuse |
| 8 | "No soft-start on UVCL release" is an inference | Minor | Applied | [DS] p.40 ("When charging is enabled"), p.71 (ICHARGE_DAC soft-start/stop by state). Re-tagged C in 5.1 and 8.1; L-3 remains the proof; S1 sensitivity added in 16.1 |
| 9 | H8 inrush 0.91/0.68 A disagrees with 12.3 | Minor | Applied | 62 uF x 12 mA/uF + 0.15 A = 0.894 A; 0.7 x 0.744 + 0.15 = 0.671 A. H8 set to 0.89/0.67 A. (Raised by both reviewers; counted once) |
| 10 | UVCLFB clamp: two figures (2.5 V at 200 uA; engages at 2 V) | Minor | Applied | [DS] p.9 Note 4, p.13, p.45. Section 6 uses the 2 V engage point; margin 0.59 V at 22.28 V |
| 11 | M6 "only above 18.92 V" contradicts section 6 | Minor | Applied | [DS] p.13 (zero current at 1.15 V); 1.15 V x 15.766 = 18.13 V. M6 restated |
| 12 | Decision rule compared against a stale baseline (45, S6 = 1); S6 not like-for-like | Major | Applied | dossier_BQ25798.md section 16 (about 40, S6 = 0); [CRIT] S6 row and section 3.3. Section 9.4 S6 table, 16 condition table and 16.1 totals restated (design A 48.4-51.7, design B 53.7); the verdict now rests on condition 1 |
| 13 | Design A has no hardware FC-mode ceiling; L-F residual reopens | Major | Applied | [EVAL] section 2.3 (L-F bounded by FC ILIM 0.74-0.96 A), 3.4 "Hard bounds", 4.1; [CRIT] M7 note. HR4 FC graded C for design B only; ruling R-FCA added; 9.4 row changed to "replaced by a register bound" |
| 14 | POR advantage mostly moot under the bridge; Teensy reset with retained image missing | Major | Applied | [DS] p.14 pin 31 (SYS = max of VBAT, VIN); [R2] line 132 (retained image after a Teensy reset). Case row and boot rule added to 5.4; HR5, M6, section 6 and the verdict reworded |
| 15 | Bridge removes the pack isolator and sits off the CCB | Major | Applied | spec.md section 0 item 2, section 1 (VBT at C-D12), section 6 decision 2; [EVAL] section 2.7. Section 2.4 extended; new section 5.5 single-fault table; fuse requirement stated with a TODO for selection; HR3, R-BR and R6 finding 2 row updated |
| 16 | POR claim fails for a failed-FB bus (18.3-19.5 V) | Minor | Applied | [EVAL] section 2.7 failed-FB row; section 6 zero-current point 17.92 V worst. Qualifier added in section 6; row added to 5.4 |
| 17 | CCB stage-failure row misstates H1/H2 action on RT1987 EN | Minor | Applied | [EVAL] section 4.1 ("Not gated: D-BC-RG EN with H1"), section 2.7 "Comparator stuck HIGH". Row restated; A5 dependence on the A1 gate net stated in 5.4 and 9.2 |
| 18 | FC threshold is a bus-collapse guard, not a purge backstop | Minor | Applied | [EVAL] section 3.4 Threshold row and blocker item 1 (2.57 V/ms). 11.4 rewritten; (16.0 - 14.04) / 2.57 = 0.76 ms |
| 19 | DRVCC gating is not a documented control input | Minor | Applied | [DS] p.4 EC conditions (DRVCC = INTVCC), p.41 (external LDO/DC-DC from VSYS; UVLO 3.9 V), p.14 pin 27. DRVCC stage graded B in 5.1, 5.4 and HR5; bench gate L-11 added |
| 20 | MPPT and EQ pins are straps of the same hazard class | Minor | Applied | [DS] p.14 pin 21, p.13 pin 13 ("GND this pin if unused, do not float"), p.45 (no VIN_UVCL_SETTING write with MPPT enabled). Straps added to 9.4 and bench gate L-12; mppt_en_pin = 1 at boot blocks P5 (5.4 boot rule) |
| 21 | S1 and the H2 latency depend on C_VC = 10 nF | Minor | Applied | Section 8.2 table (0.22 uF: 2.5 ms warm, 0.16 ms hard stop); [EVAL] sections 2.5, 3.2. Condition and fallback stated in 8.3, HR1, 8.4 and 16.1 |
| 22 | MPPTD pad carries one Teensy output; DRVCC and clamp-release derivation unstated | Minor | Applied | spec.md section 1 pad table; [EVAL] section 4.1. Section 2.2 and 5.4 now state DRVCC enable = P5 AND NOT trip and PERMIT = GATE AND P5; the case table holds with that assignment |

Totals: 22 distinct findings (23 raised; the H8 inconsistency was raised by both reviewers), 22 applied, 0 rejected, 0 partly
applied. One further item was added during the re-check: the OUTFET-short path of section 5.5 (C), which bypasses the buck and is
bounded only by the eFuse.
