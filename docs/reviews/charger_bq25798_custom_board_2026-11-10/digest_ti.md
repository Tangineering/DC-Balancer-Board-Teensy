# Digest of the TI primaries for a custom BQ25798 charger board

Sources (both read in full where relevant; figures rendered with pdftoppm and viewed):

- **DS** = BQ25798 datasheet SLUSDV2C, header "MAY 2020 - REVISED JUNE 2026", 151 pages
  (`scratchpad/ti/bq25798.pdf`, text `ds.txt`). Page numbers below are the printed page numbers (equal to the PDF page).
- **UG** = BQ25792EVM / BQ25798EVM / BQ25798BKUPEVM (BMS034) user guide SLUUCB5E, "JUNE 2020 - REVISED JULY 2022",
  31 pages (`scratchpad/ti/sluucb5e.pdf`, text `ug.txt`).
- Renders: `scratchpad/ti/png/` (ds-007/008/012-016 EC tables, ds-130/133/134/139/140 application and layout,
  m-148/149 package; ug-15..18 layers, ug-19..21 schematics, ug-22..24 BOM; c19*/c20* schematic crops at 300 dpi;
  z*/y*/v*/w* layer crops at 400 dpi).

Notation: "calc" marks a number computed here from a cited DS equation; it is not a TI figure.
"Interp." marks a reading of a rendered layout image that the design files would have to confirm.

---

## 1. Pin table, package and thermal data

### 1.1 Pins (DS Table 5-1 pp.4-6; abs max DS §6.1 p.7, rendered ds-007.png)

Package: RQM, VQFN-HR 29 pins, 4.0 mm x 4.0 mm (DS p.1 Package Information; Fig 5-1 p.4).

| Pin | Name | Type | Function (DS Table 5-1, condensed) | Abs max vs GND (DS §6.1) |
|---|---|---|---|---|
| 1 | STAT | DO | Open-drain charge status; pull up via 10 k. LOW = charging, HIGH = complete or disabled, 1 Hz blink = fault. DIS_STAT = 1 disables | -0.3..6 V; sink 6 mA |
| 2, 3 | VBUS | P | Charger input. Input current sense (RSNS 8 mOhm, DS p.14) between VBUS and PMID. Recommended 2 x 10 uF + 1 x 0.1 uF, 0.1 uF closest | -2..30 V (converter not switching) |
| 4 | BTST1 | P | High-side (Q1) driver supply; 47 nF, >= 10 V, BTST1 to SW1 | -0.3..32 V; BTST1-SW1 -0.3..6 V |
| 5 | REGN | P | Internal LDO output, from the higher of VBUS or BAT; 4.7 uF, 10 V to PGND. Gate-drive supply and TS-divider bias | -0.3..6 V |
| 6 | D+ | AIO | USB data line for BC1.2 / HVDCP detection on VIN1 | -0.3..6 V |
| 7 | D- | AIO | As D+ | -0.3..6 V |
| 8 | VAC2 | P | Input-2 detection (3.6-24 V = valid). Tie to VBUS if ACFET2/RBFET2 not fitted | -2..30 V |
| 9 | VAC1 | P | Input-1 detection. Tie to VBUS if ACFET1/RBFET1 not fitted | -2..30 V |
| 10 | ACDRV2 | P | Charge pump gate drive for ACFET2-RBFET2 (5 V above their common source). Tie to GND if not fitted | -0.3..32 V |
| 11 | ACDRV1 | P | As ACDRV2 for port 1 | -0.3..32 V |
| 12 | /QON | DI | Ship-FET enable / system power reset; internal pull-up RQON | -0.3..6 V |
| 13 | /CE | DI | Active-low charge enable (charging = EN_CHG 1 AND /CE LOW). "must be pulled HIGH or LOW, do not leave floating" | -0.3..6 V |
| 14 | SCL | DI | I2C clock, 10 k to logic rail | -0.3..6 V |
| 15 | SDA | DIO | I2C data, 10 k to logic rail | -0.3..6 V |
| 16 | TS | AI | NTC input; divider REGN-TS-GND; 103AT-2 10 k recommended | -0.3..6 V |
| 17 | ILIM_HIZ | AI | V = 1 V + 800 mOhm x IINDPM; < 0.75 V = non-switching (REGN on); > 1 V resumes; tie to REGN for maximum ILIM | -0.3..6 V |
| 18 | BATP | P (DS lists P) | Battery voltage sense; 100 Ohm series to pack + | -0.3..20 V |
| 19 | BTST2 | P | High-side (Q4) driver supply; 47 nF, >= 10 V, BTST2 to SW2 | -0.3..29 V; BTST2-SW2 -0.3..6 V |
| 20 | PROG | AI | POR default (fsw, cell count) by resistor to GND, 1 % or 2 % | -0.3..6 V |
| 21 | /INT | DO | Open-drain, active-low 256 us pulse; 10 k to logic rail | -0.3..6 V; sink 6 mA |
| 22, 23 | BAT | P | Battery power connection; charge-current sense between SYS and BAT; 2 x 10 uF | -0.3..20 V |
| 24 | SDRV | P | External ship-FET gate drive. "Connect a 1nF, 50V rated, 0402 package, ceramic capacitor from SDRV to GND when the ship FET is not used" | -0.3..26 V; SDRV-BAT -0.3..6 V |
| 25 | SYS | P | Converter output to system (Q4 drain); 5 x 10 uF + 1 x 0.1 uF | -0.3..23 V (not switching); SYS-BAT -0.3..16 V |
| 26 | SW2 | P | Boost-side switching node (Q3/Q4) | -2 (50 ns)..23 V |
| 27 | GND | P | Ground return | - |
| 28 | SW1 | P | Buck-side switching node (Q1/Q2) | -2 (50 ns)..30 V |
| 29 | PMID | P | Q1 drain; 3 x 10 uF + 1 x 0.1 uF (+ 2 x 33 uF POSCAP only for backup mode) | -0.3..30 V (not switching); PMID-VBUS -0.3..6 V |

Other abs max: TJ -40..150 C, Tstg -55..150 C (DS §6.1). ESD 2000 V HBM, 250 V CDM (DS §6.2).

### 1.2 Package (DS pp.146-150, RQM0029A drawing 4225253/A 11/2019, rendered m-148/m-149)

- Body 3.9-4.1 mm x 3.9-4.1 mm, height 0.8-1.0 mm (1 mm max), standoff 0.00-0.05 mm.
- **No exposed thermal pad.** VQFN-HR "HotRod" flip-chip style: 33 pads, 0.15-0.25 mm wide signal pads at 0.4 mm
  pitch (23X 0.4 basic), plus elongated power pads (PMID, SW1, GND, SW2, SYS on the top edge; corner L-shaped pads
  at pins 1/9/16/24 region). Heat leaves through the power pins into copper, which is why DS §8.4.1 wants wide
  same-layer copper and via fields on PMID/SYS/GND.
- Land pattern: DS p.149 "Example board layout", non-solder-mask-defined preferred, 0.05 mm max mask
  expansion; pad coordinates in parentheses are reference values only. Stencil page p.150 not transcribed:
  TODO(verify: SLUSDV2C p.150 stencil, before footprint capture).
- Tape and reel: BQ25798RQMR, SPQ 3000, 12 mm tape, pin-1 quadrant Q2 (DS p.146).

### 1.3 Thermal (DS §6.4 p.8)

| Metric | Value |
|---|---|
| RθJA | 44.2 C/W |
| RθJC(top) | 20.9 C/W |
| RθJB | 9.7 C/W |
| ΨJT | 0.5 C/W |
| ΨJB | 9.7 C/W |

These are JEDEC-board metrics (DS §6.4 note 1). **The UG publishes no EVM thermal numbers**: no thermal image, no
temperature-rise table; the only statement is the warning "Some components may reach high temperatures >55 C when
the board is powered on" (UG p.1). TREG 60/80/100/120 C (default 120 C) and TSHUT 150/130/120/85 C (default 150 C,
hysteresis 30 C) are register-selectable (DS REG16 Table, ds.txt line 4994; EC p.13). Efficiency curves for 2S
are DS Fig 6-3 (750 kHz) and Fig 6-4 (1.5 MHz), p.18 (graph only; not transcribed).

---

## 2. Typical application and Section 8 detailed design

### 2.1 Figure 8-1 (DS p.130), single input, no ship FET (values read from the render ds-130.png)

| Node | Component(s) shown |
|---|---|
| VIN (to VBUS) | 0.1 uF; "Optional" 2 Ohm + 2.2 uF RC snubber to GND (Note 1: "Recommended if hot plugging adapters > 15 V") |
| VBUS | 1 x 0.1 uF and 2 x 10 uF |
| VAC1, VAC2 | tied to VBUS; ACDRV1, ACDRV2 tied to GND |
| PMID | 1 x 0.1 uF and 3 x 10 uF |
| BTST1-SW1, BTST2-SW2 | 47 nF each |
| SW1-SW2 | 1.0 uH |
| REGN | 4.7 uF |
| PROG | 6.04 kOhm to GND (2S, 1.5 MHz per Table 7-1) |
| ILIM_HIZ | 127 kOhm from REGN, 100 kOhm to GND (calc: 5 V x 100/227 = 2.20 V -> 1.5 A by Eq 1) |
| SYS | 1 x 0.1 uF and 5 x 10 uF |
| BAT | 2 x 10 uF; "Optional" TVS to GND (Note 2: "Recommended if hot plugging 4S battery packs with long leads or PCB traces") |
| SDRV | 1 nF to GND |
| BATP | 100 Ohm to pack + |
| TS | 5.24 kOhm REGN-TS, 30.31 kOhm TS-GND, 10 k NTC TS-GND |
| STAT | 2.2 kOhm + LED to REGN |
| /CE, SDA, SCL, /INT, /QON | to host |

Fig 8-2 (p.131, two inputs + ship FET) adds back-to-back ACFET-RBFET pairs with a 294 Ohm series gate resistor
from each ACDRV, an optional 100 Ohm + 47 nF on BATP. Fig 8-3 (p.132) adds 2 x 33 uF POSCAP on PMID for backup mode.

### 2.2 Design example (DS Table 8-1 p.133, quoted)

| PARAMETER | VALUE |
|---|---|
| VBUS voltage range | 5V to 20V |
| PV panel voltage | VOC = 10V, VMPP = 8V |
| Secondary adapter voltage range | 5V to 20V |
| Input current limit (IINDPM[8:0]) | 3.0A |
| Fast charge current limit (ICHG[8:0]) | 3.0A |
| Backup mode voltage (VOTG[10:0]) | 12.0V |
| Battery regulation voltage (VREG[10:0]) | 8.4V |
| Enable MPPT (EN_MPPT[0]) | 1 |
| VOC measure interval (VOC_RATE[1:0]) | 2min |
| VOC measure delay (VOC_DLY[1:0]) | 300ms |
| VOC percent for MPP (VOC_PCT[2:0]) | 0.8125 |

Note: this TI example is itself a 2S, 8.4 V, 3 A design.

### 2.3 Inductor (DS §8.2.2.2 pp.133-134)

Quotes: "Please note that the 1.5 MHz switching frequency only works with the 1µH inductor and the 750 kHz
switching frequency only works with the 2.2µH inductor." "The inductor saturation current must be at least 2A to
accommodate PFM pulses."

- Eq 4: ISAT >= MAX[(IIN + IRIPPLE/2), (ICHG + IRIPPLE/2)].
- Eq 5 (buck): IRIPPLE = VSYS (VBUS - VSYS) / (VBUS FSW L). Eq 6 (boost): IRIPPLE = VBUS (VSYS - VBUS) / (VSYS FSW L).
- PFM peak current is limited to 2 A with OOA enabled, 3.3 A with OOA disabled (DS §7.3.6.4 p.34).
- EVM part: TDK SPM6530T-1R0M120, 1 uH, 11.1 A, 7.8 mOhm, 7.1 x 6.5 x 3.0 mm (UG Table 4-1 p.22). The EVM has no
  2.2 uH part; a 750 kHz design needs one sourced: TODO(verify: candidate 2.2 uH datasheet).
- calc for this board (Eq 5, VSYS = 8.4 V, buck only because VBUS >= 15.9 V > VSYS):

| VBUS | 1.5 MHz, 1.0 uH | 750 kHz, 2.2 uH |
|---|---|---|
| 21.5 V (V-MOT max, task context) | 3.41 A p-p | 3.10 A p-p |
| 16.0 V (VBUS nominal, CLAUDE.md §6) | 2.66 A p-p | 2.42 A p-p |

  calc ISAT floor at ICHG 3.10 A: 4.81 A (1.5 MHz) or 4.65 A (750 kHz); at ICHG 2.50 A: 4.21 A / 4.05 A.
  Ripple rises monotonically with VBUS at fixed VSYS < VBUS/2, so 21.5 V (and the 22.28 V clamp) is the worst case.

### 2.4 Capacitors (DS §8.2.2.3-8.2.2.4 pp.134-135; DS §6.3 p.8)

- Input (PMID): "The capacitor with 25V or higher voltage rating is preferred for up to 20V input voltage.
  1*0.1 µF + 3*10 µF ceramic capacitors are suggested for up to 3.3-A input current limit". Eq 7:
  ICIN = ICHG sqrt(D(1-D)), D = VSYS/VBUS. calc at ICHG 3.10 A: 1.51 A rms at 21.5 V, 1.55 A rms at 16 V.
  Eq 8: ΔVIN = D(1-D) ICHG / (CIN FSW).
- Output (SYS): "The capacitor with 16V or higher voltage rating is preferred for the 2s battery configuration.
  1*0.1 µF + 5*10 µF capacitors are suggested for up to 5A charging current." Eq 9-10 apply in boost mode,
  which this board does not enter in charge (VBUS > VSYS).
- Recommended minimum effective capacitance (DS §6.3 p.8): CVBUS 2 uF, CPMID 4 uF (70 uF with backup mode),
  CSYS 6 uF, CBAT 3 uF. These are *effective* (after DC bias). The EVM's 25 V X5R 0805 10 uF parts
  (TDK C2012X5R1E106K125AB) at a 21.5-22.3 V bus lose an unknown fraction: TODO(verify: TDK DC-bias curve). The
  task's >= 35 V input-side rule is stricter than TI's 25 V guidance and needs 35 V or 50 V parts on VBUS/PMID.
- BTST: 47 nF, >= 10 V (pin table); EVM uses 0.047 uF 25 V X7R 0402 (GRM155R71E473KA88D).
- REGN: 4.7 uF, 10 V (pin table); EVM uses 4.7 uF 16 V X5R 0603 (GRM188R61C475KAAJD). REGN 4.6-5.0 V at VBUS 5 V,
  4.8-5.2 V at VBUS 15 V, current limit >= 30 mA (EC p.15). "the REGN is not recommended to source any other
  external circuit" apart from ILIM_HIZ, TS and STAT pull-ups; /INT pull-up should be an external 1.8 V or 3.3 V
  rail (DS §7.3.4.1 p.26).

### 2.5 PROG pin (DS §7.3.2 Tables 7-1 and 7-2 p.25, quoted)

| SWITCHING FREQUENCY | CELL COUNT | TYPICAL RESISTANCE AT PROG PIN |
|---|---|---|
| 1.5MHz | 1s | 3.0k |
| 750kHz | 1s | 4.7k |
| 1.5MHz | 2s | 6.04k |
| 750kHz | 2s | 8.2k |
| 1.5MHz | 3s | 10.5k |
| 750kHz | 3s | 13.7k |
| 1.5MHz | 4s | 17.4k |
| 750kHz | 4s | 27.0k |

| CELL (REG0x0A[7:6]) | 1s | 2s | 3s | 4s |
|---|---|---|---|---|
| ICHG (REG0x03/04) | 1A | 1A | 1A | 1A |
| VSYSMIN (REG0x00[5:0]) | 3.5V | 7V | 9V | 12V |
| VREG (REG0x01/02) | 4.2V | 8.4V | 12.6V | 16.8V |
| VREG Range | 3V - 4.99V | 5V - 9.99V | 10V - 13.99V | 14V - 18.8V |

A CELL write resets ICHG/VSYSMIN/VREG to the cell-count defaults; REG_RST or watchdog expiry returns them to the
defaults (DS p.25-26). PWM_FREQ is REG13 bit 5 (0 = 1.5 MHz, 1 = 750 kHz), POR value from PROG (ds.txt line 4718).

### 2.6 ILIM_HIZ (DS §7.3.4.3 p.27; EC p.12, p.16)

- Eq 1: VILIM_HIZ = 1 V + 800 mOhm x ILIM. Read by the ADC at POR after PG_STAT, before switching; clamps IINDPM
  unless EN_EXTILIM = 0. Below 1.08 V the clamp is 100 mA.
- < 0.75 V (VIL_ILIM_HIZ max) stops switching, REGN stays on; > 1 V (VIH_ILIM_HIZ min) resumes. Usable range
  1-4 V (VILIM_REG_RNG). Leakage +/-1.5 uA at 4 V.
- IINDPM accuracy at VBUS 9 V: 3000 mA set -> 2720-2920 mA; 2000 -> 1800-1960; 1000 -> 880-1000; 500 -> 415-500
  (EC p.12).

### 2.7 TS network (DS §7.3.9.5 pp.44-46; Fig 7-12)

RT1 (REGN-TS) = 5.24 kOhm and RT2 (TS-GND) = 30.31 kOhm for T1 = 0 C, T5 = 60 C with a 103AT NTC (DS p.46).
JEITA comparators as % of REGN (EC pp.13-14): T1 rising 72.4-74.2 % (0 C), T5 falling 33.7-34.7 % (60 C);
T2/T3 programmable. TS_IGNORE = 1 disables the function. Missing thermistor = charge disabled (DS §7.3.6 item 1).
EVM fits 5.23 kOhm (R18) and 30.1 kOhm (R24), not the DS 5.24/30.31 kOhm (UG Table 4-1 p.23).

### 2.8 Input FETs, ship FET and logic pins

- **ACDRV / ACFET-RBFET** (DS §7.3.5 pp.29-32): optional back-to-back N-FETs per input. Without them: VAC1 and VAC2
  shorted to VBUS, ACDRV1/2 to GND; POR then sets DIS_ACDRV = 1, EN_ACDRV1/2 locked 0 (Table 7-5). Turn-on
  conditions (§7.3.5.1): FETs detected at POR, VAC > VVAC_PRESENT, VAC < VAC_OVP, DIS_ACDRV_BOTH not set, EN_HIZ not
  set, VBUS < VVBUS_PRESENT. Backup mode requires ACFET+RBFET (DS §8.1). EVM gate network per pair: 294 Ohm
  series (R4/R9), 1 nF C0G gate-source (C2/C4), 12 V zener (D2/D6, BZT52C12T-7), optional 100 k bleeder and 40 V
  Schottky DNP (UG Fig 4-5, crop c19a.png). EVM FETs are CSD17581Q3A, **30 V** (UG Table 4-1), below the task's
  35 V rule.
- **SDRV / ship FET** (DS §7.3.12 pp.49-50): charge pump, 100 nA, gate ~5 V above BAT. SDRV_CTRL 00 idle (FET on),
  01 shutdown, 10 ship, 11 system reset (~350 ms). Not used: 1 nF 50 V 0402 to GND (pin table). EVM Q5 is
  CSD17575Q3, 30 V.
- **/QON**: internal pull-up, VQON 3.2 V typ, RQON 200 kOhm typ (EC p.16); the pin table says "typical output
  voltage is 3.6 V-3.8 V with VBUS and VBAT > 5V" (conflict, see §7). Exit ship mode by LOW for tSM_EXIT
  (1 s or 15 ms by WKUP_DLY).
- **/CE**: VIH 1.3 V min, VIL 0.4 V max (EC p.16); must not float.
- **STAT, /INT**: VOL 0.4 V at 5 mA; abs max 6 V and 6 mA sink. STAT states, DS Table 7-11 p.48 (quoted):
  charging in progress (incl. recharge, top-off) = LOW; charging complete = HIGH; HIZ mode, charge disable = HIGH;
  battery only and OTG = HIGH; charge suspend (fault) = blinking at 1 Hz.
- **PG**: the BQ25798 has no PG pin (DS Table 4-1 p.3: "/PG, IBAT, BATN pins: No"); power-good is PG_STAT in
  I2C (DS §7.3.4 step 6).
- I2C 7-bit address 0x6B (DS §7.3.14 p.53-54); SCL/SDA VIH 1.3 V min (EC p.15-16).

---

## 3. EVM schematic as a refdes table (UG Figs 4-5, 4-6, 4-7; BOM Table 4-1 pp.22-24)

Function and block are read from the schematic renders (ug-19/20/21, crops c19a-d, c20a-c); values and MPNs from
the BOM. Column "Ours": **E** = essential for a single-input VAC1/VBUS charger on a 2S pack; **E?** = essential in
a modified form or a design decision; **C** = EVM convenience (omit); **O** = optional protection (decide).

| Refdes | Value | MPN (manufacturer) | Function | EVM block | Ours |
|---|---|---|---|---|---|
| U1 | BQ2579x HotRod | BQ25792RQM (TI) in BOM and Fig 4-5 label; BQ25798 on the -003 build | Charger | core | **E** (BQ25798RQM) |
| L2 | 1 uH | SPM6530T-1R0M120 (TDK), 11.1 A, 7.8 mOhm | Power inductor SW1-SW2 | power stage | **E** (1 uH @1.5 MHz or 2.2 uH @750 kHz) |
| L1 | 1 uH, DNP | MPIM252010F1R0M-LF (Microgate), 3.2 A | Alternate small-inductor footprint | power stage | C |
| C6, C8 | 0.047 uF 25 V X7R 0402 | GRM155R71E473KA88D (Murata) | BTST1-SW1, BTST2-SW2 | power stage | **E** |
| C11, C12 | 10 uF 25 V X5R 0805 | C2012X5R1E106K125AB (TDK) | VBUS bulk | input | **E?** (re-rate >= 35 V) |
| C13 | 0.1 uF 50 V X7R 0402 | C1005X7R1H104K050BE (TDK) | VBUS HF decoupling | input | **E** |
| C9, C10 | 10 uF, DNP | C2012X5R1E106K125AB | Extra VBUS bulk | input | O |
| C29, C30, C31 | 10 uF 25 V X5R 0805 | C2012X5R1E106K125AB | PMID bulk | power stage | **E?** (re-rate >= 35 V) |
| C32 | 0.1 uF 50 V X7R 0402 | C1005X7R1H104K050BE | PMID HF (DS 8.4.1 item 1) | power stage | **E** |
| C26, C27, C28 | 1 uF / 10 uF, DNP | GRM219R71E105KA88D / C2012X5R1E106K125AB | Extra PMID/VPMID | OTG output | C |
| C33, C34 | 33 uF 25 V polymer (BKUP EVM only) | ECASD41E336M040KA0 (Murata) | PMID hold-up for backup mode | backup | C (no backup mode) |
| C18 | 0.1 uF 50 V X7R 0402 | C1005X7R1H104K050BE | SYS HF (DS 8.4.1 item 1) | power stage | **E** |
| C19-C23 | 10 uF 25 V X5R 0805 | C2012X5R1E106K125AB | SYS bulk (5 x) | power stage | **E** |
| C24, C25 | 10 uF / 33 uF 35 V Ta, DNP | C2012X5R1E106K125AB / T521D336M035ATE065 (Kemet) | Extra SYS bulk | system | O |
| C38, C39 | 10 uF 25 V X5R 0603 | GRT188R61E106ME13D (Murata) | BAT capacitors (2 x) | battery | **E** |
| C37, C40 | 0.1 uF / 10 uF, DNP | C1005X7R1H104K050BE / GRT188R61E106ME13D | Extra BAT caps | battery | O |
| C35 | 4.7 uF 16 V X5R 0603 | GRM188R61C475KAAJD (Murata) | REGN | core | **E** |
| C14, C15 | 0.1 uF 50 V X7R 0402 | C1005X7R1H104K050BE | VAC1, VAC2 to AGND | input detect | **E?** (VAC1/VAC2 tied to VBUS: one 0.1 uF) |
| C16, C17 | 0.01 uF, DNP | C0402C103J5RACTU (Kemet) | ACDRV1/2 to AGND | input mux | C |
| C36 | 1000 pF 50 V C0G 0402 | GRM1555C1H102JA01D (Murata) | SDRV cap; on the EVM its far side is BAT (JP8 pin 1) | ship FET | **E** as 1 nF 50 V 0402 **SDRV to GND** (rev C, §7) |
| C41, C42 | 1000 pF, DNP | GRM1555C1H102JA01D / GRM1555C1H102FA01D | SDRV/ship-FET gate options | ship FET | C |
| R15 | 100 Ohm 0603 | RC0603FR-07100RL (Yageo) | BATP series | battery sense | **E** |
| JP9 | 3-pin header | PEC03SAAN (Sullins) | BATP to J5 remote sense or BAT pin | battery sense | C (hard-wire BATP sense point) |
| R29 | 6.04 k in Fig 4-6 / 6.20 k in BOM | RC0603FR-076K2L (Yageo) | PROG 2S 1.5 MHz | config | **E** (6.04 k 1 %, or 8.2 k for 750 kHz) |
| R27, R28, R30-R34 | 3.57k/4.75k/8.20k/10.5k/14.0k/18.0k/27.0k (BOM) | Vishay/Yageo/Panasonic | Other PROG options | config | C |
| JP22-JP29 | 2-pin headers | PEC02SAAN | PROG selection | config | C |
| R21 + R23 | 127 k + 100 k | CRCW0603127KFKEA, RC0603FR-07100KL | ILIM_HIZ divider from REGN (1.5 A) | ILIM | **E?** (value set by design; round-3 permit logic drives this pin) |
| R20 | 255 k | CRCW0603255KFKEA | ILIM 500 mA option | ILIM | C |
| JP13, JP14, JP21 | headers | PEC02SAAN | ILIM 500 mA / 1.5 A / HIZ short | ILIM | C |
| R18, R24 | 5.23 k, 30.1 k | CRCW04025K23FKED, CRCW040230K1FKED | TS bias network | TS | **E** (with pack NTC via J-NTC) |
| R22 | 0 Ohm 0805 | BOM lists "5106 Keystone" (BOM error) | TS to EXT_TS | TS | C |
| R19, R25, R26 | 7.68 k, 10.0 k, 4.87 k | Vishay 0402 | NTC simulators (cool/normal/warm) | TS | C |
| JP12, JP15, JP16, JP18-JP20 | headers | PEC02SAAN | TS connect and simulators | TS | C |
| J7 | 2-pin TB 3.5 mm | 0393570002 (Molex) | External thermistor | TS | C (MB J-NTC path) |
| R42 | 10.0 k 0402 | CRCW040210K0FKED | /CE pull-up to PULLUP | logic | **E?** (round-3 permit logic owns /CE) |
| JP17 | header | PEC02SAAN | /CE to GND (charge enable) | logic | C |
| R39, R40, R41 | 10.0 k 0402 | CRCW040210K0FKED | SCL, SDA, /INT pull-ups | logic | **E?** (MB already has RSDA/RSCL; /INT pull-up needed if /INT used) |
| R38, D13, JP32 | 2.21 k, green LED LTST-C190GKT (Lite-On), header | | STAT LED | indicator | C (STAT goes to Teensy pin 6 per round-3) |
| U2 | TLV76033DBZR (TI) | | 3.3 V pull-up LDO from VBUS/BAT | pull-up rail | C (Teensy 3V3 exists) |
| D11, D12 | 30 V 0.2 A Schottky | BAT54HT1G (ON) | Diode-OR VBUS/BAT to U2 | pull-up rail | C |
| C43, C44 | 0.1 uF 25 V X5R 0402 | GRM155R61E104KA87D (Murata) | U2 in/out | pull-up rail | C |
| R35 | 10.0 Ohm 1206 | ERJ-8ENF10R0V (Panasonic) | U2 input series | pull-up rail | C |
| R36 | 0 Ohm 0603 | CRCW06030000Z0EA | U2 output link | pull-up rail | C |
| JP30, JP31, JP33 | headers | | PULLUP source select (LDO / EV2400 / USB2ANY) | interface | C |
| R37, R43 | 10.0 Ohm 1206 | ERJ-8ENF10R0V | EV2400 / USB2ANY pull-up series | interface | C |
| J8 | 4x1 R/A header | 0022053041 (Molex) | EV2400 I2C | interface | C |
| J9 | 5x2 shrouded | N2510-6002-RB (3M) | USB2ANY I2C | interface | C |
| S1 | push switch | KSR221GLFS (C&K) | /QON to GND | logic | C (/QON has internal pull-up; leave open or MCU) |
| Q1, Q2 (Q3, Q4) | 30 V N-FET | CSD17581Q3A (TI) | ACFET1-RBFET1 (ACFET2-RBFET2) | input mux | O (input isolation is done by RT1987 switches on the MB; if fitted, >= 35 V FETs) |
| R4, R9 | 294 Ohm 0603 | CRCW0603294RFKEA | ACDRV series gate | input mux | O (with Q1/Q2 only) |
| C2, C4 | 1000 pF 50 V C0G 1 % 0402 | GRM1555C1H102FA01D | ACFET gate-source | input mux | O |
| D2, D6 | 12 V zener 300 mW | BZT52C12T-7 (Diodes) | ACFET gate clamp | input mux | O |
| R1, R5 / R3, R8 / D1, D5 | 0 Ohm / 100 k / 40 V Schottky ZLLS350TA, all DNP | | ACFET bypass / bleeders / ACDRV clamp | input mux | C |
| JP1, JP2 | 3-pin headers | PEC03SAAN | ACDRV to FETs or GND | input mux | C (ACDRV1/2 hard-tied to GND if no FETs) |
| JP3, JP4 | 2-pin gold | HTSW-102-07-G-S (Samtec) | VAC1/VAC2-VBUS bypass | input mux | C (hard-tie) |
| Q5 | 30 V N-FET | CSD17575Q3 (TI) | Ship FET | ship FET | O (not needed; pack is permanently on PCB GND per task) |
| R17, R14, R16, D9, D10 | 0 Ohm / DNP | | Ship-FET gate and bypass network | ship FET | C |
| JP5, JP8 | headers | | BAT-BATTERY bypass, SDRV connect | ship FET | C |
| R2, R6, R11, R12, R13 | 0.01 Ohm 1 W 2010 | WSL2010R0100FEA18 (Vishay) | Current-measurement shunts (VIN1, VIN2, SYS, VPMID, BAT) | measurement | C (IC senses internally; IBUS/IBAT ADC) |
| J1, J2, J3, J4 | 2x1 5.08 mm TB | ED120/2DS (On-Shore) | VIN1, VIN2, SYSTEM, VPMID terminals | connectors | C |
| J5 | 3x1 5.08 mm TB | ED120/3DS | BATTERY / EXT_BATP / GND | connectors | C |
| J6 | micro-USB B | 47346-0001 (Molex) | USB input / D+/D- | USB | C |
| JP6, JP7, JP10, JP11 | headers | | USB D-/VIN select/D+D- short/D+ | USB | C (tie D+/D- per §7: TODO(verify: DS p.4 unused D+/D- handling)) |
| RSNUB1/2 + CSNUB1/2 | 2.0 Ohm + 2.2 uF | no footprint (Note 1) | Input RC snubber, hot-plug > 15 V | input | **O, recommended**: the input sees 16-21.5 V switched by RT1987s |
| R7, R10 + C5, C7 | 2.0 Ohm + 2200 pF, DNP | CRCW06032R00JNEA, GRM1885C1H222JA01D | SW1/SW2 RC snubbers | power stage | O (footprint advisable, DNP) |
| D3, D4, D7, D8 | 30 V 1 A Schottky, DNP | MBR130T1G (ON) | PMID/SW/SYS clamps | power stage | O |
| CSNUB (BATP) | 0.047 uF | no footprint (Note 2) | BATP snubber, 4S hot plug + ship FET | battery | C (2S) |
| DTVS | CUHZ20V,H3F | no footprint (Note 3) | BAT TVS, 4S hot plug, no ship FET | battery | C (2S, no hot plug) |
| TP1-TP50 | Keystone 5000/5002/5003/5004/5016 | | Test points | test | C (keep a few: VBUS, BAT, SW1, SW2 pads) |
| H1-H4 | SJ-5303 | | Bumpons | mechanical | C |
| NT1 | Net-tie | | PGND-AGND single join | ground | **E** (or single-plane per UG §3 item 7) |

Fig 4-7 (BQ25798BKUPEVM, -002) is the same circuit with C33/C34 fitted (UG p.21).

Essential count for our application (single input, no USB, no backup, no ship FET, 2S): U1, L, 2 BTST caps,
REGN cap, VBUS 0.1 uF + >= 2 x 10 uF, PMID 0.1 uF + 3 x 10 uF, SYS 0.1 uF + 5 x 10 uF, BAT 2 x 10 uF, VAC 0.1 uF,
SDRV 1 nF, BATP 100 Ohm, PROG resistor, ILIM_HIZ network, TS network, /CE bias, I2C/INT/STAT pull-ups where the MB
lacks them. About 25 placements against the EVM's ~150.

---

## 4. EVM PCB stack and power-loop placement

### 4.1 Stack

UG §4.1 shows four copper layers: Top (Fig 4-1 p.15), Signal Layer 1 (Fig 4-2 p.16), Signal Layer 2 (Fig 4-3
p.17), Bottom (Fig 4-4 p.18). **The UG states no copper weights, board thickness or dielectric**:
TODO(verify: TI EVM design files / fab drawing, not in SLUUCB5E). Board outline is BMS034A/B, roughly square with
corner mounting holes (Fig 4-1).

### 4.2 Placement of the power loop (Fig 4-1 top, crop z15.png; Interp. throughout)

Orientation as printed (VIN terminals J1/J2 left, SYSTEM/BATTERY terminals J3/J5 right):

- **U1** sits in the board centre with pin 1 top-left; its top edge carries the PMID-SW1-GND-SW2-SYS power pads
  (DS Fig 5-1), so the power stage is built **above** U1.
- **C32 (PMID 0.1 uF) and C18 (SYS 0.1 uF)**, 0402, sit side by side immediately above U1's top edge on the top
  layer, C32 over the PMID/SW1 side, C18 over the SW2/SYS side (labels "C32 C18" directly over the IC).
- **PMID bulk C29, C30, C31** (0805) are a row immediately above-left of U1, **SYS bulk C19, C20, C21** a row
  above-right, mirror-symmetric about the IC's vertical centre line; the remaining SYS bulk C22, C23 and the BAT
  caps C37-C40 continue to the right of U1 (labels "C37 C38 C39 C40" right of the IC).
- **VBUS caps C10-C13 and REGN C35** are a vertical stack left of U1 ("C10 C11 C12 C35 C13"), on the VBUS
  pins' side (pins 2-3, left edge).
- **L2** (6.5 x 7.1 mm) sits directly above the C32/C18 pair, centred on U1, about one capacitor length above the
  IC; a rectangular "PGND" copper pour between the SW test points lies above L2; SW1 test points TP3/TP4 left,
  SW2 TP10/TP11 right.
- **Input FETs Q1-Q4** are far left in a column with zeners D2/D6; ship FET **Q5** bottom-right near J5.
- PGND pours surround the stage; many stitching vias across the board (Fig 4-1, 4-2).

### 4.3 Which layer carries SW1/SW2 (Figs 4-2, 4-3; crops y16, v17, w17; Interp.)

- **Signal Layer 1 (layer 2)** is an almost continuous ground pour. It has a **rectangular void** directly over the
  SW-routing region between U1 and L2 (y16.png, white rectangle with via rings on both long sides).
- **Signal Layer 2 (layer 3)** carries the switch nodes: two copper strips leave via clusters under U1 (via groups
  at the IC's top edge) and run up to via columns at the L2 pad positions, one on each side (SW1 left, SW2 right),
  with branches to the SW test points TP3/TP4 and TP10/TP11 (v17.png). This matches DS §8.4.2: "The SW1 and SW2
  pins are routed to vias placed under the IC and then back out on an inner PCB layer."
- **Bottom layer** (Fig 4-4, mirrored view, v18/z18.png): the bootstrap caps **C6 and C8** sit under U1, on the same
  via fields as SW1/SW2 (DS §8.4.2: "These vias are also used to route to the C7 BTST1 and BTST2 capacitors on the
  bottom layer"); C14/C15 (VAC 0.1 uF) and C36/C41 (SDRV) are also on the bottom under or beside U1; C9, C27, C28
  footprints (DNP) and the ACDRV parts R4/D1, R9/D5, C2/R3, C4/R8 are bottom-side under Q1-Q4.

### 4.4 DS Figure 8-21 layout example (DS p.140, ds-140.png)

Left half: top-layer pours removed; right half: pours shown. U1 centred; L5 (inductor) above U1, centred, its
two pads labelled SW1 (left) and SW2 (right), each with a column of three vias. One 0402 "C2" (PMID 0.1 uF) and
one 0402 "C1" (SYS 0.1 uF) directly above U1's top edge; two 0805-size "C2" PMID bulk left and two "C1" SYS bulk
right at the same height, all on the top layer. "C3" VBUS caps (one 0402 near the VBUS pins, one bulk further
left) and "C7" REGN below-left; "C6" BAT caps right of U1 with their own PGND. SW1/SW2 run from vias under the
IC on a mid layer (light blue) to the inductor vias; the BTST "C7" caps are on the bottom layer (dark blue) under
the IC. Pours: PMID upper-left, PGND top-centre between the inductor pads and between the cap pairs, SYS
upper-right, VBUS left, BAT right, PGND bottom. Note on the figure: at least 2 vias each for the REGN and small VBUS
cap grounds to the internal ground plane.

---

## 5. Layout guidelines (verbatim)

### 5.1 DS §8.4.1 (p.139)

"The switching nodes rising and falling times should be minimized for minimum switching loss. Proper layout of
the components to minimize the high frequency current path loops (shown in the figure below) is important to
prevent the electrical and magnetic field radiation and the high frequency resonant problems. Below is a PCB
layout priority list for proper layout. Layout of the PCB according to this specific order is essential.

1. Place 0.1µF small size (such as 0402 or 0201) capacitors on the same layer as and on top of the IC with short
   traces to the PMID and GND and SYS and GND pins. Ideally, at least one of the typical 10µF bulk capacitors is
   placed in parallel with these 0.1uF capacitors. The remaining bulk capacitors must connect with low impedance
   (i.e. same layer as IC with wide traces and/or through multiple vias) back to PMID, SYS and GND.
2. Capacitor placement above requires the inductor input terminal to SW1 and the inductor output terminal to SW2
   use multiple vias under the IC to internal or bottom layer traces that connect to the inductor. Minimize the
   copper area of this trace to lower electrical and magnetic field radiation but make the trace wide enough to
   carry the inductor current. Minimize parasitic capacitance from this area to any other trace or plane. The BTST
   capacitors can be connected with vias on both sides.
3. Place the REGN decoupling capacitor close to the IC REGN pin and connect with a short trace. Then use at least
   2 vias to connect the capacitor ground to the internal ground plane/pour that has multiple vias back up to IC
   GND pin.
4. Place a 0.1 µF small size (such as 0402 or 0201) capacitor close to the VBUS pin. The remaining 10 µF bulk
   capacitors can be placed further away. Capacitor ground connections must through at least 2 vias to the
   internal ground plane/pour that has multiple vias back to IC GND pin.
5. Place the BAT capacitors close to BAT and GND.
6. Via size and parallel quantities must be sufficient for a given current path.
7. Route BATP and TS traces away from switching nodes such as SW1 and SW2.

Refer to the EVM design and more information in the BQ25798EVM and BQ25798BKUPEVM (BMS034) Evaluation Module for
the recommended component placement with trace and via locations."

Figure 8-20 (p.139) shows the two high-frequency loops: input loop through the PMID capacitor, Q1 and Q2; output
loop through Q3, Q4 and the SYS capacitor.

### 5.2 DS §8.4.2 (p.140)

"Figure 8-21 shows the recommended placement and routing of external components. The components are labelled with
"R," "C" or "L" to indicate resistor, capacitor or inductor and a number that corresponds to the numbered list in
Section 8.4.1. Since the layout guidelines are listed in priority order, this number also provides a priority for
component placement.

The placement of C1 and C2 0.1 µF PMID and SYS capacitors is critical for noise filtering. They should be placed
on the same layer as the BQ25798, as close to the IC as possible. This will generally require that the traces to
connect SW1 and SW2 to the inductor are routed on a different layer.

The SW1 and SW2 pins are routed to vias placed under the IC and then back out on an inner PCB layer. This supports
the tightest placement of C1 and C2 capctiors as described above. These vias are also used to route to the C7
BTST1 and BTST2 capactiors on the bottom layer as shown."

Figure note: "Not shown above are at least 2 vias for REGN capacitor (C7) and VBUS decoupling capacitor (small C3)
ground to connect through internal/bottom layer ground plane back to IC GND pin."

### 5.3 UG §3 PCB Layout Guidelines (p.14, verbatim)

"Careful placement of components is critical in order for the charger to meet specifications. The items below are
listed in order of placement priority.

1. Place high frequency decoupling capacitors for PMID and SYS (C3 and C18 on the EVM) as close possible to their
   respective pins and ground pin on the same layer as the charger IC (in other words, no vias) in order to have
   the smallest current loop.
2. Place bulk capacitors for PMID and SYS as close possible to their respective pins and the charger's ground pin
   on the same layer as the charger IC on the same layer as the charger IC (in other words, no vias).
3. Place the REGN capacitor (C35) to ground and BTST capacitors (C6 and C8) to SW as close as possible to their
   respective pins only using vias for 1 side of each component if necessary.
4. Place high frequency decoupling capacitors for VBUS and BAT pins as close as possible to their respective pins.
   Use at least 2 vias per capacitor terminal if required.
5. Place bulk capacitors for VBUS and BAT pins as close as possible to their respective pins. Use at least 2 vias
   per capacitor terminal if required.
6. Place the inductor close to SW1 and SW2 pins. It is acceptable to use multiple vias to make these connections
   as the vias are only adding small amounts of inductance and resistance to an inductor.
7. While this EVM has analog ground (AGND) and power ground (PGND) planes that connect close to the charge GND pin,
   two grounds not required. Resistors and capacitors used for setting sensitive nodes (for example, ILIM, TS) can
   use one common ground plane but with their ground terminals connected away from high current ground return
   paths containing switching noise.

Note that this EVM has test points and jumpers requiring traces out to the PCB edges. Routing these traces
required some PCB layout compromises for less critical components than those listed in the first six items above."

UG item 1 names "C3" as the PMID HF capacitor; on the schematic and layout the PMID 0.1 uF is **C32** (C3 is a DNP
1 uF at VIN2). Treat "C3" as a UG typo (Fig 4-5; Fig 4-1 label "C32 C18").

---

## 6. Electrical limits relevant to this board

| Item | Value | Source | Consequence here |
|---|---|---|---|
| VAC1, VAC2 abs max | -2..30 V | DS §6.1 p.7 | Pin rating is 30 V, not 35 V or 40 V. V-MOT clamp 22.28 V (task) is 7.7 V below it |
| VBUS, PMID abs max | 30 V (converter not switching) | DS §6.1 | The 30 V figure holds only when not switching; no separate switching figure is given |
| SW1 abs max | -2 (50 ns)..30 V | DS §6.1 | |
| SW2, SYS abs max | 23 V | DS §6.1 | |
| BAT, BATP abs max | 20 V | DS §6.1 | |
| ACDRV1/2, BTST1 abs max | 32 V | DS §6.1 | |
| VBUS operating | 3.6-24 V | DS §6.3 p.7; EC VVBUS_OP | Clamp 22.28 V is 1.72 V under the 24 V ROC maximum |
| VBUS_OVP | 25.2/25.7/26.2 V rising, 24.0/24.4/24.8 V falling (min/typ/max) | DS EC p.9 | Fixed; not reached by V-MOT |
| VAC_OVP | 26 V (0h, typ 25.2-26.8 rising), 18 V (1h), 12 V (2h), 7 V (3h) | DS EC p.9; REG10[5:4] | 18 V setting would trip at V-MOT 21.5 V; 26 V is the usable setting. POR value disputed (see §7) |
| Input current IVBUS | 3.3 A max | DS §6.3 | |
| IINDPM range | 0.1-3.3 A, 10 mA step | DS EC p.12; REG06 | |
| VINDPM range | 3.6-22 V, 100 mV step; accuracy +/-2 % at 18.6 V, +/-3 % at 10.6 V | DS EC p.12; REG05 | Default VINDPM = VBUS0 - 1.4 V (VBUS0 >= 7 V) at POR (DS §7.3.4.4) |
| ICHG | 50-5000 mA, 10 mA step, POR 1 A | DS REG03 Table 7-16; §6.3 fast charge 5 A | 2.5 A and 3.10 A are inside range |
| ICHG accuracy | 0..+10 % at 1 A, +/-5 % at 0.5 A (VBAT 8 V) | DS EC p.10-11 (text extraction; higher-current rows TODO(verify: DS p.10-11 render)) | |
| ISW | 5 A | DS §6.3 | |
| IBAT discharge | 6 A rms, 10 A peak 1 s; IBAT_OCP 9.3 A min | DS §6.3; EC p.12 | |
| VREG (2S) | 5-9.99 V, POR 8.4 V; VBAT_OVP 103-105 % of VREG rising | DS Table 7-2; EC p.12 | |
| VSYSMIN 2S | POR 7 V; 250 mV step | DS Table 7-2; EC | |
| fsw | 1.5 MHz (1 uH) or 750 kHz (2.2 uH) by PROG / PWM_FREQ | DS EC p.14; §8.2.2.2 | |
| RDS(on) typ | RSNS 8, Q1 24, Q2 35, Q3 28, Q4 17, BATFET 11 mOhm | DS EC pp.12, 14-15 | Conduction-loss estimate input |
| TREG / TSHUT | 60/80/100/120 C (default 120) / 150/130/120/85 C (default 150), hysteresis 30 C | DS EC p.13; REG16 | |
| ILIM_HIZ | HIZ < 0.75 V (VIL max), resume > 1 V (VIH min), range 1-4 V | DS EC pp.12, 16 | |
| /CE | VIH 1.3 V min, VIL 0.4 V max; no float | DS EC p.16; Table 5-1 | |
| Watchdog | WATCHDOG[2:0] 0 = disable, 0.5/1/2/20/40/80/160 s, POR 40 s; expiry returns registers to default (incl. ICHG, VSYSMIN, VREG) | DS REG10 (ds.txt line 4472); §7.4.1; §7.3.2 | |
| ADC | 16-bit; conversion 24/12/6/3 ms per channel at 15/14/13/11 effective bits; IBUS 0-5 A, VBUS/VAC 0-30 V, VBAT 0-20 V, VSYS 0-24 V, 1 mA / 1 mV LSB; operates if VBUS > 3.4 V or VBAT > 2.9 V | DS §7.3.10 p.47; EC p.16-17 | |
| Quiescent | 17 uA battery-only (ADC off), 0.5 uA shutdown; 3-5 mA VBUS switching no load | DS EC p.8 | |
| Default charge profile | VRECHG 200 mV, IPRECHG 120 mA, trickle 100 mA, ITERM 200 mA, JEITA, CHG_TMR 12 h, PRECHG_TMR 2 h | DS Table 7-9 p.41 | |
| SYSMIN/BATFET-LDO clamp | charge current limited to 2 A max during SYSMIN regulation with BATFET LDO | DS §7.3.9.2 p.42 | Only if the pack is below VSYSMIN (7 V); the task floor is 7.4 V |
| I2C | 0x6B | DS §7.3.14 | |

---

## 7. Revision C (June 2026) items versus the round-3 design

The round-3 documents already cite **SLUSDV2C (rev June 2026)** and **SLUUCB5E (rev July 2022)**
(`docs/charger_bq25798_wiring_design_2026-11-05.md` line 1078), so there is no datasheet-revision gap. The rev C
change list (DS §10 p.142) contains items that bear on round-3 choices or on a custom board:

1. **SDRV-to-BAT option deleted.** Rev C: "Deleted SDRV connected to BAT when shipFET disabled as an option"; the
   pin table now says 1 nF 50 V 0402 **SDRV to GND** when no ship FET is used. The EVM's C36 connects SDRV through
   1000 pF to **BAT** with JP8 1-2 (Fig 4-5), and round-3 EVM modification **EM13** keeps JP8 1-2
   (wiring design line 1171, citing UG Table 1-3). On the custom board, use SDRV to GND. Round-3 EM13 follows the
   superseded configuration: flag to the round-3 owner.
2. **Default ICHG.** Rev C "Clarified that default charge current for all configurations is 1A". The UG Table 1-3
   and the EVM silkscreen/schematic still say "2A ICHG" for 1S/2S PROG settings (UG pp.4-5, Fig 4-6). Round-3
   records the conflict (evaluation doc line 653); rev C resolves it to 1 A.
3. **PROG resistor on the EVM.** Fig 4-6 shows R29 = 6.04 k (DS Table 7-1 value); the BOM lists R29 = 6.20 k
   (and 3.57k/4.75k/14.0k/18.0k where Table 7-1 has 3.0k/4.7k/13.7k/17.4k). Round-3 EM19 already flags this
   (wiring design line 1177). Custom board: 6.04 k 1 % (1.5 MHz) or 8.2 k (750 kHz). The DS gives no PROG
   detection window: TODO(verify: TI, PROG tolerance band).
4. **VAC_OVP.** Rev C corrected REG10[5:4] 1h to 18 V (was 22 V). DS REG10 is still self-contradictory (field
   "Reset 0h", "POR: 11b", "0h = 26V (default)"), and the UG §2.4.3 step 6 says "increase the VAC_OVP from 7 V
   default". Round-3 P5 already handles this (writes 0h, bench step S1-0b). Device Comparison Table 4-1 (p.3)
   lists BQ25798 ACOVP default 26 V, options 7/12/18/26 V.
5. **ILIM_HIZ.** Rev C adds "Connect ILIM_HIZ to REGN to set the maximum input current limit" (pin table).
6. **ACDRV.** Rev C corrects "common drain" to "common source" for the ACFET-RBFET pair (pin table): the FET pair
   is source-to-source, gates driven 5 V above the common source.
7. **/QON pull-up.** Rev C pin table: "typical output voltage is 3.6 V-3.8 V with VBUS and VBAT > 5V"; the EC table
   p.16 still gives VQON 3.2 V typ and RQON 200 kOhm. Internal conflict; any external logic on /QON must accept
   either.
8. **Input source detection** runs only on VAC1 and "can take up to 2s" (rev C, §7.3.4.5). With no USB, set
   AUTO_INDET_EN = 0 or accept the delay: TODO(verify: DS §7.3.4.5 for D+/D- handling when unused).
9. **Layout guidelines "clarified"** (rev C, §8.4). The numbered list and the Fig 8-21 labels do not agree: §8.4.2
   says labels match the list, yet C1/C2 are both list item 1 (PMID and SYS 0.1 uF), C3 is item 4 (VBUS), C6 is
   item 5 (BAT) and C7 is both REGN (item 3) and BTST (item 2). Use the text, not the label numbers.
10. **Date inconsistency.** The rev C header says "REVISED JUNE 2026"; the change-list heading says "Changes from
    Revision B (January 2023) to Revision C (May 2026)".
11. **STOP_WD_CHG** added to the REG09 header; watchdog behaviour (EN_CHG reset) remains contradictory, as
    round-3 P7 records.
12. Rev C also states SYSMIN charge clamp (2 A), trickle-to-precharge regulation, VBAT_OVP threshold with
    EN_TERM = 0, SDRV typical output, and "Deleted that BATFET turns off in ship mode". None changes a power-stage
    value.

---

## 8. Does TI publish EVM design files?

- **SLUUCB5E itself** contains the complete schematic (Figs 4-5..4-7), the four copper-layer plots (Figs 4-1..4-4)
  and the BOM (Table 4-1); its abstract says "A complete schematic diagram, printed-circuit board (PCB) layouts,
  and bill of materials (BOM) are also included in this document" (UG p.1). The layer plots are images without
  dimensions, stack-up or drill data.
- The saved BQ25798EVM tool page (`scratchpad/ti/evm_page.html`) links the user guide SLUUCB5E (PDF and HTML) and a
  "Download" entry for the EVM software (`/tool/download/BQ25798EVM`); no Altium, Gerber or design-file package is
  listed in the saved page. One E2E thread ("BQ25798: BQ25789 Schematic review") is linked.
- TIDA-050047 (TIDUEY1C) lists schematics and a BOM; an older revision TIDUEY1B listed an Altium project (task
  context; not verified in this digest, nothing downloaded). Whether TIDA-050047 uses the BQ25798 power stage in a
  layout reusable here: TODO(verify: TIDUEY1C).
- Practical consequence: a custom layout must be drawn from DS §8.4 and the UG images; exact via counts, trace
  widths and copper weights are not available: TODO(verify: TI design files, request through E2E or the TI
  sales channel).
