# Finalist dossier: TI BQ25690 on the custom charger board (2026-11-10)

This dossier evaluates the Texas Instruments BQ25690 as the charger IC of the custom charger board (CCB) that replaces the
Silvertel Ag105 (BOM `CHG`) on board rev 20260622. It applies the must-haves M1-M13 and the scored criteria S1-S16 of
`screening_criteria.md` (cited as **CRIT**), and it compares the part with the BQ25798 baseline of the 2026-11-05 evaluation.

Citation tags:

- **DS** = TI SLUSFN4A, the BQ25690 data sheet (section 1.2). "DS p.N" is the printed page, which equals the PDF page.
- **EVAL** = `docs/charger_replacement_evaluation_2026-11-05.md`.
- **WD** = `docs/charger_bq25798_wiring_design_2026-11-05.md` (interlock functions only).
- **R6** = `docs/reviews/charger_eval_2026-11-05/round3/review_loop.md`, review round 6.
- **SCR** = `screening.md` (the screening record of this search).

Status codes follow EVAL section 1.2: P = PROVEN_DATASHEET, C = PROVEN_CALC, B = BENCH_GATE, F = FAIL, U = UNKNOWN or missing
primary, sys = blocked at system level. A value read from a typical-characteristics figure or an application scope capture is
labelled "figure reading, typical" and has status B at best.

---

## 1. Identity and sources

### 1.1 Part

| Item | Value | Source |
|---|---|---|
| Part | BQ25690, standalone/I2C-controlled, 1-7 cell, 3 A buck-boost NVDC charger with bypass and USB-PD reverse mode | DS p.1 |
| Orderable part number | BQ25690RBAR (RBA, WQFN-HR 26 pin, 4.0 x 3.5 mm, reel of 3000, MSL2, marking B690) | DS section 10.1 p.75 |
| Lifecycle | Active | DS section 10.1 p.75 |
| Data sheet status | Production Data from revision A (December 2025); revision * (October 2025) was Advance Information | DS section 9 p.73 |

### 1.2 Documents read

| Document | Revision read | URL | Fetch | How read |
|---|---|---|---|---|
| TI SLUSFN4A, *BQ25690 Standalone/I2C Controlled, 34V, 1- to 7-Cell Li-Ion, 3A Buck-Boost Bidirectional NVDC Battery Charger with Bypass Mode and USB-PD OTG Output* | Revision A, October 2025, revised December 2025, 84 pp. (including the package addendum and mechanical pages) | https://www.ti.com/lit/ds/symlink/bq25690.pdf | 2026-11-10 (sweep-ti copy) | Text extraction of sections 4-7 and 10; pages 5-10, 12-14, 16-17, 22, 47, 64, 67 and 78 read as rendered pages; Figures 7-2, 7-5 and 7-7 rendered at 300 dpi and read by eye |

The BQ25690EVM user guide was not read. The layout statements of section 12 rest on DS section 7.4 only.

### 1.3 Secondary sources (UNVERIFIED)

| Fact | Source | Status |
|---|---|---|
| DigiKey stock: 176 (digikey.jp), 460 (digikey.dk), 0 (digikey.ca French); lead time 18 weeks; USD 5.18 at quantity 1 and USD 3.1518 at 250 (digikey.com.mx) | Web-search snippets of DigiKey regional pages, 2026-11-10 | UNVERIFIED |
| A BQ25690EVM exists (DigiKey part 28721478) | Same search | UNVERIFIED; not relevant to the CCB |

### 1.4 Correction of the screening record

Three facts in SCR (finalist row 1, section 1.3 table, provisional score column) do not agree with the primary data sheet:

| SCR statement | Primary fact | Effect |
|---|---|---|
| "RILIM_HIZ ROC 4.6-27.4 kOhm"; pin ceiling limited to 0.63-0.82 A at 10 mOhm; 5 mOhm / RAC_SNS workaround | The ROC gives **RILIM_HIZ 0.0-33 kOhm** (DS section 5.3 p.6). The 4.6-27.4 kOhm rows are RCELL, RVCHG and RICHG. KILIM is one min / typ / max row, specified at IIN_MAX = 0.5, 1.0 and 1.6 A (DS section 5.5 p.9); above 1.6 A the band is an extrapolation | M7 passes on P evidence at 10 mOhm. The TI E2E question and the 5 mOhm arrangement are not needed |
| "C_IN 1.8 uF min" | **CVIN >= 10 uF** after derating, CVIN = CVIN_ACP + CVIN_ACN with **CVIN_ACP >= CVIN_ACN**, CVIN_ACN >= 100 nF (DS section 5.3 p.5). Section 7.2.2.2 p.66 states the split as CVIN_ACN < 4 x CVIN_ACP, and Table 7-2 p.64 as "4x CIN1 > CIN2"; the two forms disagree (section 12.3) | S15 stays 3 (section 12.4); the inrush is about 0.13 A at 12 mA/uF |
| S7 telemetry score 2 | The register map has **no ADC** (DS Table 6-12 p.45, registers 0x00-0x26) | M11 passes only with a CCB current monitor; S7 = 0 |
| "+-0.5 % specified at 4S" | The 2S row is specified: 8.358-8.442 V at 0-85 C (DS section 5.5 p.8) | M3 is P |

---

## 2. Architecture on the custom board

### 2.1 Topology

The BQ25690 is a synchronous 4-switch buck-boost converter with all four power MOSFETs (Q1-Q4) and the loop compensation
integrated (DS section 6.1 p.19). It uses a narrow-VDC (NVDC) power path: the converter output is SYS, and an external
N-channel BATFET driven by BATDRV connects SYS to the battery side (DS section 6.3.8.1.1 p.25). Input current is sensed by an
external resistor RAC_SNS between ACP and ACN on the input side; charge current is sensed by an external resistor RBAT_SNS
between SRP and SRN on the battery side (DS Table 4-1 pp.3-4, Figure 7-1 p.64). Both sense resistors are high-side. The
return of input and battery is one GND node.

Across the 2S operating envelope the converter runs in buck mode: the lowest input at which charging is required is 13.14 V
and the highest charger output is 8.484 V (CRIT section 4.4). The converter changes between buck, buck-boost and boost without
host control (DS section 6.3.7 p.24), so it can also run in boost mode if VCHG-IN falls toward the pack voltage (section 9.5).

### 2.2 Position between VCHG-IN and VCHG

| Node (CCB) | Connection |
|---|---|
| Pad VCHG-IN | System eFuse (core, WD) -> CVIN_ACP (bulk input capacitance) -> RAC_SNS 10 mOhm (ACP -> ACN) -> VIN |
| VIN | CVIN_ACN: 0.1 uF at the pin plus one bulk capacitor (layout rule 2, DS section 7.4.1 p.70). Total CVIN >= 10 uF after derating with CVIN_ACP >= CVIN_ACN (DS section 5.3 p.5; section 12.3) |
| SW1, SW2 | One inductor, 10 uH at 450 kHz (DS Table 7-4 p.65) |
| SYS | >= 15 uF after derating for 2S (DS section 5.3 p.5). No system load on the CCB |
| SYS -> SRP | BATFET, N-channel, drain on SYS, source on SRP; gate on BATDRV (DS Figure 7-1 p.64) |
| SRP -> SRN | RBAT_SNS 10 mOhm (section 7.4 explains the choice of 10 mOhm) |
| SRN | Pad VCHG (input of D-BT-SQ, then the pack). CBAT >= 5 uF after derating (DS section 5.3 p.5) |
| CELL, VCHG, ICHG | Straps: 6.04 kOhm (2S), 13.7 kOhm (4.2 V/cell), ICHG tied to GND (deliberate strap fault, section 5.3) |
| ILIM_HIZ | Mode-switched resistor to GND (section 7); **required** static HIZ drive from a VCHG-IN-derived bias rail, asserted unless the core static permit is HIGH (section 5.2) |
| /CE | Two redundant pull-ups to REGN; open-drain pull-down driven by the core PERMIT logic; far-end readback to the core (section 5) |
| SDA, SCL | Pads SDA, SCL; address 0x6A (DS section 6.3.11.5 p.41) |
| STAT | Pad STAT (open drain; LOW = charging, HIGH = complete, HIZ, charge disabled, battery-only or OTG, 1 Hz blink = charge-suspend fault; DS Table 6-11 p.39) |
| TS | Fixed divider from REGN, or the pack NTC through pad THERM (section 15) |

The CCB carries the charger stage, the CCB current monitor (section 10), the IC-specific adders (section 9) and the system
interlock core of WD (H1, H2 with BT_ACT, C7, OVN, eFuse, monostables, FCC/RGN sensing). The pad set is the Ag105 pad set
(SPEC); no pad changes are needed.

---

## 3. Must-have check

| ID | Result | Value | Citation |
|---|---|---|---|
| M1 common ground, high-side sense | **P pass** | ACP/ACN on the input side, SRP/SRN on the battery side, one GND; no element in the return | DS Table 4-1 pp.3-4, Figure 7-1 p.64 |
| M2 input rating | **P pass** | Abs max 45 V on VIN, ACP, ACN, SYS, SRP, SRN, BATDRV, SW1, SW2, BYPDRV; BTST1/2 6 V with respect to SW. ROC VIN 2.5-34 V. VIN_OVP rising 35.5 V min, falling 33.8 V min | DS section 5.1 p.5, section 5.3 p.5, section 5.5 p.6 |
| M3 2S CV +-1.0 % | **P pass** | 8.358-8.442 V (2S, 4.2 V/cell, TJ 0-85 C); -1.15/+0.9 % over TJ -40 to 125 C, which gives 8.303-8.476 V; upper limit 8 mV inside the 8.484 V M3 limit, lower limit 13 mV below the 8.316 V M3 limit. M3 is P on the TJ 0-85 C basis and F on the full-TJ basis (operator basis ruling). Pre-charge, CC, CV, termination present | DS section 5.5 p.8; section 6.3.8.2.3 p.29 |
| M4 >= 3.1 A at 8.4 V, loss <= 2 W | **B conditional** | ICHG range 40-3300 mA, 20 mA step; accuracy specified only at 0.5 A and 1.5 A (+-5 %) and only at VBAT = 12, 20 and 28 V (VBAT > VSYSMIN) or 9, 15 and 21 V (VBAT < VSYSMIN): no 2S point is published (U, extrapolated); typical +2 % at 3 A at VBAT 16 V, VBUS 20 V (figure reading). Average inductor current must not exceed 4 A. Loss 2.14-2.48 W typical at 3.1 A, 15-20 V input (section 11.2) | DS section 5.5 p.8, Figure 5-12 p.16, section 6.3.7 p.24 |
| M5 hard inhibit pin | **Conditional pass (P mechanism; B HIZ entry level)** | M5 requires a pin that stops conversion. /CE does not: with charging disabled the converter keeps switching and regulates SYS 200 mV above the battery voltage (DS section 6.3.8.1.1 p.25, Figure 7-7 p.67). /CE is the per-burst charge disable (charging needs EN_CHG = 1 **and** /CE LOW; no register defeats it). The pin that stops conversion is ILIM_HIZ above VIH_ILIM_HIZ (HIZ: REGN off, converter stops; DS section 6.3.3 p.21). EN_EXTILIM = 0 disables HIZ control through the pin (DS section 6.3.8.1.2.1 p.26); POR value 1, reset to 1 by the watchdog, so the never-write list plus readback holds it, as M5 allows. VIH_ILIM_HIZ has a MIN of 1.77 V only, so the drive level that guarantees HIZ entry is not published (B, T-5.HIZ). The CCB therefore makes the ILIM_HIZ HIZ drive mandatory (section 5.2) | DS Table 4-1 p.3; section 5.5 p.9; section 6.3.3 p.21; section 6.3.8.1.1 p.25; section 6.3.8.1.2.1 p.26; section 6.3.8.2.2 p.28 |
| M6 fail-safe default | **P pass for /CE (with the CCB bias); C for the HIZ layer** | /CE has no internal bias ("must be pulled HIGH or LOW"), so the CCB pull-up to REGN decides the default. The HIZ layer cannot take its default from REGN (HIZ turns REGN off) and takes it from a VCHG-IN-derived bias rail (section 5.2). No NVM or OTP is described. Additional POR inhibit through the ICHG strap fault at a true POR (section 5.3) | DS Table 4-1 p.3; section 6.3.3 p.21; section 6.3.6 p.24 |
| M7 hardware ceiling | **Conditional pass (P mechanism; EN_EXTILIM defeat, never-write plus readback)** | IIN_MAX = KILIM / RILIM, KILIM 2890 / 3333 / 3780 A x Ohm (min / typ / max), specified at IIN_MAX = 0.5, 1.0 and 1.6 A (one row; above 1.6 A extrapolated); RILIM ROC 0-33 kOhm; the lower of pin and IINDPM applies. EN_EXTILIM (POR 1, reset to 1 by REG_RESET and WATCHDOG) can disable the pin: never-write plus readback | DS section 5.3 p.6, section 5.5 p.9, section 6.3.8.1.2.1 p.26, Table 6-27 p.52 |
| M8 runtime input-voltage regulation | **P pass, conditional on FORCE_VINDPM** | VINDPM 2.5-34 V, 20 mV step, 19.6-20.4 V at 20 V, 11.76-12.24 V at 12 V; DPM reduces charge current and keeps the converter regulating SYS. IQ_VIN switching 700 uA typical. FORCE_VINDPM is reset by the watchdog (section 6) | DS section 5.5 pp.6, 9; section 6.3.5 p.21; section 6.3.8.1.2 p.25 |
| M9 no cold restart per burst | **B conditional** | /CE exit: charge current about 1.2 ms after the /CE edge, full current at about 1.4 ms (Figure 7-5, figure reading, typical, boost mode at 5 V, real 7.4 V battery). A /CE edge starts a new charge cycle only with VBAT (SRN) < VRECHG, and the cycle passes through trickle, pre-charge and the Table 6-8 clamps if SRN has decayed (section 8.3). VINDPM crossing re-runs nothing: the converter stays on and VIN_OKZ is 2.35 V max (specified "no battery"). Exit from HIZ through ILIM_HIZ is cold and re-reads the straps; it is excluded from the per-burst path | DS Figure 7-5 p.67; section 5.5 p.6; section 6.3.3 p.21 |
| M10 host interface | **P pass levels; U back-powering** | VIH 1.3 V min, VIL 0.4 V max, pull-up rail 1.8-5 V, 100 kHz to 1 MHz, open drain. Behaviour of SDA/SCL with the IC unpowered is not stated | DS section 5.3 p.5, section 5.5 p.12, section 5.6 p.12, section 6.3.11 p.40 |
| M11 charge-current telemetry | **C pass with a CCB monitor** | No ADC in the register map; the ILIM_HIZ pin voltage is an analog input-current monitor (+-13 %), not readable over I2C | DS Table 6-12 p.45; section 6.3.8.1.2.1 p.26 |
| M12 runtime current control | **P pass** | IINDPM 40-3300 mA, ICHG 40-3300 mA, both 20 mA step | DS Tables 6-15, 6-17 pp.46-47 |
| M13 lifecycle | **P pass** | Active | DS section 10.1 p.75 |

The BQ25690 passes every must-have. The conditional passes concern M4, M5, M8, M9, M10 and M11. The M5 condition (HIZ entry
level, B) concerns a must-have on which the BQ25798 has P evidence (its "ILIM_HIZ < 0.75 V stops switching" is a published
level), so CRIT section 3.5 condition 1 is not met until bench gate T-5.HIZ passes.

---

## 4. Requirement status (HR1-HR5, H1-H12)

| Req | Status | Basis |
|---|---|---|
| **HR1** regen | **U (B: warm response, buck mode, VRECHG start condition)**; input capability **C** | /CE exit about 1.4 ms to full current, typical, boost mode at 5 V (section 8); head start 2.65 ms worst case at regen VINDPM 19.0 V. A cycle starts only with SRN < VRECHG (8.02 V at POR, 8.15 V at 97 %); above that, capture is not established (section 8.3, T-3.VRECHG). Input at the threshold 23.9 W minimum at the regen ceiling, 24.9-28.3 W at ICHG 3.1 A (section 11) |
| **HR2** FC | **P charger / sys** | FC ceiling 0.71-0.95 A by hardware; IINDPM 20 mA step; charge 1.25-1.58 A at 8.4 V, 1.46 A at the typical ceiling (section 11.4). Purge handling is system-level; each purge re-opens the window from a decayed VCHG-IN (section 11.5) |
| **HR3** loop | **C (with the core interlock)** | Same H1/H2/C7/OVN core as WD; no ILIM release path is needed, so `CHG_QUAL AND NOT P5` disappears (section 9). Two hardware layers as in the baseline: /CE (per burst) and the static ILIM_HIZ HIZ drive (section 5.2). Buck-boost: no physical no-charge floor (S16 = 0) |
| **HR4** runaway | **C** (regen maximum B, T-7) | Continuous analog ILIM ceiling with published KILIM; mode switch defaults to the FC (lower) value (section 7); register-defeatable through EN_EXTILIM REG0x14 bit 5, never-write plus readback, as the baseline REG14[1] |
| **HR5** fail-safe | **C** | /CE pull-ups plus open-drain permit stage; static HIZ drive from a VCHG-IN-derived bias; ICHG strap fault clears EN_CHG at a true POR (not after an input dip with SRN bias retained, not after REG_RST); STOP_WD_CHG makes a watchdog expiry disable charging, but only after a nominal 40 s (baseline 0.5 s); no NVM (section 5). Bench gates T-5.4, T-5.HIZ |
| H1 ground/sense | P | Section 3, M1 |
| H2 inhibit | P mechanism / B latency | /CE stop: IBAT falls within about 20 us of the /CE edge, figure reading, typical, boost mode (section 8.3) |
| H3 fail-safe | C | As HR5 |
| H4 threshold | P range / B warm | VINDPM 2.5-34 V, 20 mV, +-2 % at 20 V and 12 V; retention conditional on FORCE_VINDPM (section 6) |
| H5 FC | **F at the typical ceiling with R_FC 4.02 kOhm** | CV +-0.5 % (0-85 C). The typical FC ceiling 0.829 A binds below IINDPM (typical 0.855 A at 900 mA) and gives 1.46 A at 8.4 V; 1.5 A needs 0.853 A input and is reached only near the top of the KILIM band. R_FC 3.83 kOhm brings the typical charge to about 1.50 A (section 11.4) |
| H6 ratings | P | 45 V abs max, VIN_OVP 35.5 V min |
| H7 D-BT-SQ | B | Battery detection behind D-BT-SQ depends on the SRN voltage at start-up and on the SRN leakage (B, section 6.4); EN_BAT_DETECT = 0, EN_PRECHG and VRECHG behaviour are bench gates |
| H8 inrush | C | CVIN >= 10 uF; about 0.13-0.14 A for the charger stage at 12 mA/uF; no switching during the ramp (cold start about 270 ms, figure reading) (section 12.4) |
| H9 I2C/logic | P levels / U unpowered behaviour | Section 10 |
| H10 thermal | B | 2.14-2.48 W typical at 3.1 A and 15-20 V input (section 11.2); <= 2 W at ICHG <= about 2.6 A (20 V) |
| H11 stock | U | DigiKey snippets only, UNVERIFIED (section 13) |
| H12 telemetry | F for the IC; C with a CCB monitor | Section 10 |
| **Verdict** | **FEASIBLE_W_COND**; alternate to the BQ25798, not a recommended switch | Section 16 |

---

## 5. Hard inhibit and fail-safe behaviour

### 5.1 Inhibit mechanisms

| Mechanism | Effect | Default with the Teensy absent | What the exit re-runs | Latency |
|---|---|---|---|---|
| /CE HIGH | Charging disabled; converter keeps regulating SYS (DS section 6.3.8 p.24, Figure 7-7 p.67). REGN stays on | Set by the CCB pull-up: HIGH = inhibit | Exit starts a new charge cycle and resets the safety timer (DS section 6.3.8.2.5 p.31). No soft-start of the converter, which is already switching. Delay to current about 1.2 ms, figure reading, typical | Stop: about 20 us or less, figure reading, typical (section 8.3) |
| EN_CHG = 0 (register) | As /CE | POR 1. The data sheet contradicts itself: Table 6-26 p.51 lists WATCHDOG as a reset source of EN_CHG (to 1), and Table 6-25 p.51 says STOP_WD_CHG = 0 "keeps existing EN_CHG setting" on expiry. With STOP_WD_CHG = 1 an expiry sets EN_CHG = 0 (P). With STOP_WD_CHG = 0 the result is U, TODO(verify: TI E2E) | As /CE | Not published |
| ILIM_HIZ > VIH_ILIM_HIZ (1.77 V, MIN only) | HIZ: REGN off, converter stops, input draw 11 uA typical at 24 V (DS section 6.3.3 p.21, section 5.5 pp.6, 9). The drive level that guarantees entry is not published (B) | Asserted by the static HIZ drive (section 5.2) | Exit through the pin re-reads the CELL, ICHG and VCHG straps (DS section 6.3.3 p.21, section 6.3.6 p.22); REGN restarts; cold. Whether the re-read ICHG strap fault clears EN_CHG again is U (T-5.HIZ) | Not published |
| EN_HIZ = 1 (register) | As above | POR 0; reset by REG_RESET, WATCHDOG and adapter plug-in | With FORCE_VINDPM = 0, exit re-measures the unloaded VIN and rewrites VINDPM (DS section 6.3.5 p.21) | Not published |
| BATFET_CTRL = 1 | BATFET forced off; converter keeps running (DS Table 6-27 p.52) | POR 0 | Not documented | Not published |
| ICHG strap fault (pin to GND) | No charge cycle at POR; EN_CHG cleared by the device; converter regulates SYS to VSYSMIN (DS section 6.3.6 p.24, Table 6-3 p.22) | Every POR | Host writes ICHG_PIN_OVERRIDE = 1, ICHG, EN_CHG = 1 | POR-time only |

The per-burst gate is /CE. /CE disables charging but does not stop conversion (DS section 6.3.8.1.1 p.25, Figure 7-7 p.67).
The ILIM_HIZ HIZ input is the only pin that stops conversion. Its exit is cold, so the CCB uses it as a static inhibit: HIZ
is asserted unless the core static permit (P5 AND heartbeat AND OVN, without the per-burst H1 term) is HIGH, and it is not
toggled per burst. Pulling ILIM_HIZ HIGH from REGN is not possible, because HIZ turns REGN off and the pin would fall back
below the threshold (DS section 6.3.3 p.21). The CCB 3.3 V feed is also unsuitable, because it is absent when the Teensy is
unpowered. The HIZ drive therefore takes its bias from VCHG-IN (section 5.2).

Note that the BQ25798 per-burst gate, "ILIM_HIZ below 0.75 V stops switching" (EVAL 0.2 reason 3), has no equivalent on the
BQ25690. Here an ILIM_HIZ pin at GND removes the hardware ceiling and leaves the IINDPM register as the only limit (DS section
6.3.8.1.2.1 p.26). The fault direction is therefore reversed: on the BQ25798 a grounded ILIM_HIZ inhibits; on the BQ25690 it
defeats HR4 (section 7.4).

### 5.2 Fail-safe /CE bias

The CCB uses the same structure as WD for /CE: a pull-up resistor to a rail that exists whenever the converter can switch,
and an open-drain stage that pulls /CE LOW only while the core PERMIT is HIGH. With PERMIT LOW, unpowered or undriven, the
open-drain stage is off and /CE is HIGH.

| Pull-up rail | Behaviour | Assessment |
|---|---|---|
| REGN (4.8-5.2 V at VIN 15 V, 26 mA limit; DS section 5.5 p.12) | REGN is on whenever VIN_OK < VIN < VIN_OVP and the IC is not in HIZ (DS section 6.3.4 p.21). The converter cannot switch without REGN, so /CE is HIGH whenever conversion is possible | Preferred (same as the WD REGN-biased pull-ups). /CE abs max 6 V (DS section 5.1 p.5) |
| CCB 3.3 V feed | Present only when the Teensy-side 3.3 V is present | Rejected as the only pull-up: with the 3.3 V feed absent and VCHG-IN present, /CE would float |

The /CE net carries the same two additions as the baseline design: a second, redundant REGN pull-up (WD r3-2, R272/R272b), so
one open resistor cannot let /CE float, and a far-end readback of the /CE pin level to the core (WD r1-3, U204, FR-08(b)).
A STAT-against-command plausibility check in firmware is a further cross-check (STAT LOW = charging, DS Table 6-11 p.39).
/CE (pin 9) is adjacent to GND (pin 10) (DS Figure 4-1 p.3); a solder bridge holds /CE LOW permanently, and only the readback,
the STAT check or the static HIZ layer detects or stops it (section 5.3).

### 5.2a Static HIZ drive (second hardware layer)

The HIZ layer is the equivalent of the baseline ILIM_HIZ hold-down: it stops conversion with /CE stuck LOW, with the open-drain
stage failed, or with any per-burst path fault. Its default must not depend on REGN (HIZ turns REGN off) or on the Teensy-side
3.3 V. Proposed circuit (all part data UNVERIFIED; TODO(verify: part data sheets)):

| Element | Function |
|---|---|
| Micro-power LDO, >= 35 V input, 5.0 V output, fed from VCHG-IN | Bias rail. A micro-power part keeps the draw below threshold inside the H4 5-10 mA budget; a zener and resistor would draw about 5.6 mA at 18.5 V and is rejected |
| Single inverter (74LVC1G04 class) on the 5.0 V rail, input = core static permit (core pull-down) | Output HIGH (HIZ) when the static permit is LOW, unpowered or undriven |
| Schottky diode in series with the output | Blocks the inverter output when LOW, so RILIM is not loaded and the ceiling of section 7 is unchanged (pin voltage <= 1 V in regulation) |
| Series resistor, about 1 kOhm | Limits current into RILIM. Pin level about 4.8 V x RILIM / (RILIM + 1 kOhm): 3.3 V at 2.23 kOhm (regen), 3.8 V at 4.02 kOhm (FC); below the 6 V abs max (DS section 5.1 p.5) |

The pin level is about 1.9-2.2 times the 1.77 V MIN, but no maximum entry threshold is published, so HIZ entry at this level
is B (T-5.HIZ). The static permit is released when regen mode is armed or an FC window opens; each release is a cold exit
(about 270 ms class, section 8.3), which is outside the per-burst path. A TODO remains on the net name of the static permit in
WD (TODO(verify: WD r1-4)).

### 5.3 Intrinsic POR inhibit through the ICHG strap fault

The data sheet defines an ICHG resistance below 3.8 kOhm or above 46.8 kOhm as "FAULT, no charge" (DS Table 6-3 p.22). After
a strap fault "the device does not automatically start a charge cycle (EN_CHG cleared to 0 by the device)", and the converter
"remains on and regulates SYS to VSYSMIN" (DS section 6.3.6 p.24). The CCB therefore ties ICHG to GND directly. An open ICHG
joint also reads as a fault. A bridge between ICHG (pin 15) and VCHG (pin 14) shorts the VCHG strap to GND, which is a VCHG
strap fault and also gives no charge (DS Figure 4-1 p.3, Table 6-2 p.22). Two other adjacent-pin bridges are not covered by
the strap: /CE (pin 9) to GND (pin 10) holds /CE LOW permanently (section 5.2), and STAT (pin 6) to ILIM_HIZ (pin 7) pulls
the ILIM pin LOW while charging, which removes the hardware ceiling (section 7.3). Both enter the CCB single-fault table and
an assembly inspection gate (T-ASM).

Consequences:

- Every true charger POR (VIN and SRN both below their thresholds) lands in a non-charging state, independent of /CE (P).
  With the /CE pull-up this gives two independent POR inhibits. An input dip with the IC still biased from SRN is not a POR
  (section 5.5). A REG_RST does not re-run the CELL, ICHG and VCHG pin detection, which is "only done at the charger first
  time POR" (DS section 6.4.2 p.44); after REG_RST, EN_CHG returns to 1 and ICHG_PIN_OVERRIDE to 0, and whether the strap
  fault still blocks charging is U (T-5.REGRST).
- The host enables charging with the **POR enable sequence**: STOP_WD_CHG = 1, EN_BAT_DETECT = 0, VRECHG, FORCE_VINDPM = 1
  plus VINDPM, ICHG_PIN_OVERRIDE = 1 (REG0x1C bit 3), ICHG (REG0x02), EN_CHG = 1 (REG0x13 bit 5) (DS section 6.3.6 p.24,
  Tables 6-15, 6-23, 6-25 to 6-27, 6-35). The data sheet requires the host to program the charge-profile registers after a
  strap fault before EN_CHG = 1 (DS section 6.3.6 p.24).
- The ICHG register clamp from the strap is lost. The charge current is then bounded by the ICHG register (<= 3.3 A) and by
  the hardware input ceiling (section 7), which carries HR4.
- CELL (6.04 kOhm, 2S) and VCHG (13.7 kOhm, 4.2 V/cell) stay valid, so the VREG clamp of 8.40 V holds (section 6.3).
- Open item: the ICHG register value after a strap fault and the ICHG clamp after a watchdog clears ICHG_PIN_OVERRIDE are not
  stated. TODO(verify: SLUSFN4A, TI E2E).

### 5.4 Watchdog behaviour

After POR the device starts in default mode with the watchdog expired; the first I2C write enters host mode and starts the
watchdog (DS section 6.4.1 p.43). WATCHDOG POR is 40 s (DS Table 6-24 p.50). On expiry the device returns to default mode and
resets the registers marked "WATCHDOG". Relevant resets: EN_CHG -> 1, EN_HIZ -> 0, FORCE_VINDPM -> 0, EN_EXTILIM -> 1,
BATFET_CTRL -> 0, EN_REV -> 0, EN_BACKUP -> 0, EN_BYPASS -> 0, VCHG_PIN_OVERRIDE / CELL_PIN_OVERRIDE / ICHG_PIN_OVERRIDE -> 0
(DS Tables 6-25 to 6-27, 6-34, 6-35). STOP_WD_CHG = 1 makes an expiry set EN_CHG = 0 (DS Table 6-25 p.51). STOP_WD_CHG lists
no "Reset by" source, so it is retained until POR. TODO(verify: SLUSFN4A whether REG_RST resets STOP_WD_CHG). The EN_CHG
entry and the STOP_WD_CHG = 0 description contradict each other (section 5.1); with STOP_WD_CHG = 1 the outcome is P.

The firmware writes STOP_WD_CHG = 1 after every charger POR. A hung Teensy then loses charging after a nominal 40 s through
the charger watchdog. The data sheet publishes no maximum timeout; it gives only 136 s minimum and 160 s nominal for the 160 s
setting (DS section 5.6 pp.12-13). The shortest setting is 40 s (DS Table 6-24 p.50), against 0.5 s in the baseline image
(BQ25798 REG0x10 = 0x81, EVAL section 4.5). The charger watchdog is therefore about 80 times slower than the baseline second
tier and cannot act inside an FC window before the next purge. On the BQ25690 the heartbeat monostables of the core are the
only hung-MCU tier fast enough for FC windows; the charger watchdog is a backstop for long hangs only.

### 5.5 HR5 status

| Fault | Outcome |
|---|---|
| Teensy unpowered or in reset | PERMIT and static permit LOW (core pull-downs) -> open-drain stage off -> /CE HIGH (REGN pull-ups); static HIZ drive asserts HIZ (VCHG-IN-derived bias). No charge, no conversion |
| Teensy hung | Core heartbeat monostables drop PERMIT and the static permit (WD); charger watchdog (STOP_WD_CHG = 1) disables charging after a nominal 40 s (no maximum published) as a slow backstop |
| I2C dead | /CE HIGH by the core (P5 LOW) and HIZ asserted; after a true charger POR the strap fault holds charging off with no write |
| /CE stuck LOW (bridge to pin 10, open-drain stage shorted) | Static HIZ layer stops conversion when the static permit drops; readback flags the fault. During a permitted window only EN_CHG (firmware) and the RT1987 path switches remain |
| True charger POR (VIN and SRN both below their thresholds; thermal shutdown) | Strap fault: no charge until the POR enable sequence (section 5.3). VINDPM returns to the relative algorithm (section 6.1) |
| VCHG-IN dropout with the IC biased from SRN (DS section 6.3.1 p.20) | Not a POR: registers retained (EN_CHG = 1, overrides set), charging resumes on the VIN return gated only by /CE and the HIZ layer. The strap-fault layer is not credited here (T-5.4) |
| REG_RST | Pin detection not re-run (DS section 6.4.2 p.44); EN_CHG -> 1, ICHG_PIN_OVERRIDE -> 0; charge state U (T-5.REGRST). /CE and HIZ unaffected |
| Stored settings | No NVM or OTP is described in DS; no autonomous charge from stored settings |

HR5 is **C**: each mechanism is P except the HIZ entry level (B), and the composition is a CCB design. The remaining bench
gates are T-5.4, T-5.HIZ and T-5.REGRST (section 15).

---

## 6. Input-voltage regulation and POR behaviour

### 6.1 VINDPM

| Item | Value | Source |
|---|---|---|
| Range | 2.5-34 V (register 7Dh-6A4h) | DS section 5.5 p.9; Table 6-18 p.47 |
| Step | 20 mV | Same |
| Accuracy | 19.6-20.4 V at 20 V; 11.76-12.24 V at 12 V (+-2 %) | DS section 5.5 p.9 |
| Typical accuracy | +0.1 to +0.5 % between 12 V and 34 V, figure reading, typical | DS Figure 5-15 p.17 |
| Register POR value | 2.9 V (91h) | DS Table 6-18 p.47 |
| Register reset sources | None listed: the VINDPM register is not reset by REG_RESET or by the watchdog | DS Table 6-18 p.47 |
| Method bit | FORCE_VINDPM, POR 0 (relative); reset by REG_RESET and WATCHDOG | DS Table 6-27 p.52 |
| Relative algorithm | With FORCE_VINDPM = 0, VINDPM is set to 87.5 % of the unloaded VIN (VIN > 6 V) at adapter plug-in and at an exit from HIZ through EN_HIZ | DS section 6.3.5 p.21 |
| Host absolute value | With FORCE_VINDPM = 1 the algorithm is disabled and the host value is used | Same |

Settings for this board:

| Mode | VINDPM setting | Band (+-2 %) | Register |
|---|---|---|---|
| Regen | 19.00 V | 18.62-19.38 V | 0x08 = 19000 mV / 20 mV = 950 = 3B6h, field bits 14:4. 19.00 V is the baseline threshold (EVAL 2.7, 4.5); an 18.50 V setting gives only 0.94 ms of worst-case head start (section 8.3) |
| FC | 13.50 V | 13.23-13.77 V (+-2 % extrapolated between the 12 V and 20 V specification points) | 675 = 2A3h |

### 6.2 What resets the host value

| Event | Result |
|---|---|
| /CE toggle | No effect on VINDPM (P: /CE is not a listed trigger, DS section 6.3.5 p.21) |
| Input dip that stays above VIN_OKZ (2.35 V max, specified "VIN falling, no battery", DS section 5.5 p.6) | No plug-in event; value retained. The good-source qualification uses VVIN_UVLOZ, which has no value in the EC table (DS section 6.3.10.1 p.38). The CCB is close to the "no battery" case because SRN is behind D-BT-SQ, but the plug-in threshold with SRN powered is U, TODO(verify: SLUSFN4A, TI E2E) |
| Watchdog expiry | VINDPM register retained; FORCE_VINDPM returns to 0. The next plug-in or EN_HIZ exit then replaces the value with 87.5 % of the unloaded VIN (P) |
| REG_RST | As the watchdog for FORCE_VINDPM (P) |
| Charger POR | VINDPM 2.9 V, FORCE_VINDPM 0; the plug-in algorithm sets 87.5 % of the unloaded VIN (P) |

Relative values after a POR or after a watchdog followed by a plug-in (C, 87.5 % of the unloaded VIN):

| Unloaded VCHG-IN at the event | Resulting VINDPM | Relation to the bus |
|---|---|---|
| 16.0 V (bus) | 14.0 V | Below the bus: the charger can draw from the bus. HR3 rests on H1/H2, as for the baseline (EVAL 1.3: VBUS0 - 1.4 V) |
| 21.5 V (V-MOT peak) | 18.8 V | Above the bus |
| About 7.0 V (bus fed through a disabled TPS61288 body diode) | 6.1 V | Below the pack: boost-mode charging from the passthrough bus is possible; only the interlock stops it (CRIT section 4.5) |

The firmware writes FORCE_VINDPM = 1 and the mode value after every charger POR, after every watchdog flag (WD_FLAG) and on
every mode transition, with readback. S4 = 2: the value survives inhibit exit and input dips, but not the combination of a
watchdog expiry and a later plug-in.

### 6.3 Charge profile at POR

| Item | POR value | Source |
|---|---|---|
| VREG | From CELL and VCHG straps: 2 x 4.2 V = 8.40 V; the strap value is the upper clamp | DS section 6.3.6 pp.22-23 |
| VREG clamp with VCHG_PIN_OVERRIDE = 1 | 9.6 V for CELL_PIN = 2S | DS Table 6-4 p.23 |
| CELL_PIN change | Allowed only with CELL_PIN_OVERRIDE = 1; VREG and VSYSMIN are rewritten automatically from the new cell count | DS section 6.3.6 p.23 |
| VSYSMIN | 6.2 V (2S) | DS Table 6-1 p.22 |
| ICHG | Strap fault: undefined, TODO(verify: SLUSFN4A) | DS Table 6-3 p.22 |
| IINDPM | 3300 mA | DS Table 6-17 p.47 |
| EN_CHG | 1; cleared by the device on a strap fault | DS Table 6-26 p.51; section 6.3.6 p.24 |
| EN_BAT_DETECT | 1 | DS Table 6-27 p.52 |
| EN_PRECHG | 1 | DS Table 6-23 p.49 |
| VRECHG | 10b = 95.5 % x VREG = 8.02 V (2S); reset by REG_RESET only. The firmware writes 11b = 97 % (8.15 V) in the POR enable sequence (section 8.3) | DS Table 6-23 p.49 |
| VBAT_LOWV / IPRECHG | 11b = 71.4 % x VREG = 6.0 V; IPRECHG 100 mA | DS Table 6-23 p.49; Table 6-21 p.48 |
| EN_MPPT (REG0x17 bit 0) | 0; reset by REG_RESET only | DS Table 6-30 pp.53-54 |
| Safety timers | Fast charge 12 h, pre-charge 2 h | DS Table 6-6 p.28 |
| JEITA | Enabled | DS Table 6-32 p.55 |

Autonomous charging at POR: none with the ICHG strap fault (P). Without the strap fault the device would charge at the ICHG
strap current as soon as /CE is LOW (DS section 6.3.8.2.2 p.28), which is why the CCB uses the fault strap.

### 6.4 Battery detection behind D-BT-SQ

The charger regulates its SRN pin, which is the VCHG pad. D-BT-SQ conducts only from VCHG to the pack, so SRN does not see the
pack voltage when no charge current flows. If VBAT < VBAT_SHORT at start-up, the device charges SRN to VBAT_DET with the trickle
current and then lets SRN fall by 200 mV; if SRN moves through both levels, the battery is declared absent and SYS is
regulated to VBAT_DET + 400 mV or VSYSMIN + 200 mV (DS section 6.3.8.2.1 pp.27-28). If SRN does not charge to VBAT_DET or
discharge to VBAT_DET - 200 mV within 2 s, the device declares a battery plugged in and charges normally to VREG (same
section). VBAT_DETECT POR is 00b = 2.8 V/cell, that is 5.6 V for 2S; the maximum setting is 3.3 V/cell (6.6 V) (DS Table 6-28
p.53). The pack is at 7.4-8.4 V.

The outcome on the CCB is **B**, not C, because two conditions depend on unspecified leakage:

- The routine runs only if VBAT (SRN) < VBAT_SHORT at start-up, that is below 2.15 V/cell = 4.3 V for 2S (DS section 5.5
  p.8). If D-BT-SQ reverse leakage or residual charge on CBAT holds SRN above 4.3 V, detection does not run and charging
  proceeds normally.
- The absent verdict needs SRN to fall by 200 mV within 2 s. The data sheet says only that SRN "is allowed to discharge"; it
  names no sink. Without a discharge path on the VCHG node (CBAT plus the D-BT-SQ input), the routine reports "battery
  plugged in" and charging proceeds.

Battery detection is therefore not credited as a POR-safety property; the ICHG strap fault carries that property at a true
POR (section 5.3). The firmware writes EN_BAT_DETECT = 0 in the POR enable sequence (reset by REG_RESET only, DS Table 6-27
p.52), so the routine does not interfere with regen bursts. Reverse mode requires EN_BAT_DETECT = 0 as a precondition (DS
Table 6-26 p.51), so the write removes that precondition; EN_REV goes on the never-write list (section 14). Bench gate T-6.4
records the SRN voltage at start-up and the VCHG-node leakage.

---

## 7. Hardware input-current ceiling (HR4)

### 7.1 Mechanism

IIN_MAX = KILIM / RILIM with KILIM 2890 / 3333 / 3780 A x Ohm (min / typ / max), specified at IIN_MAX = 0.5, 1.0 and 1.6 A
in one row and referenced to RAC_SNS = 10 mOhm and RAC_SNS bit 0 (DS section 5.5 p.9, section 6.3.8.1.2.1 pp.26-27). Above
1.6 A the band is an extrapolation (B). The pin carries a current proportional to the input current;
the converter enters input-current regulation when the pin voltage reaches 1 V (DS section 6.3.8.1.2.1 p.26). The ceiling is
therefore a continuous analog loop, not a value sampled at plug-in: a change of RILIM acts at once (P). The ROC allows RILIM
0-33 kOhm (DS section 5.3 p.6). The IINDPM register accuracy (2700-3000 mA at 3000 mA, 810-900 mA at 900 mA) is always at or
below the setting (DS section 5.5 p.9).

### 7.2 Mode-switched divider

The CCB fits R_FC = 4.02 kOhm (1 %) permanently and switches R_RG = 4.99 kOhm (1 %) in parallel with one N-MOSFET keyed to the
core regen-mode signal RGN_ON (WD U121). The FET gate has a pull-down, so an absent or undriven mode signal leaves the lower
(FC) ceiling. This is the opposite polarity to the BQ25798 design, where the third resistor was switched by FCC_net (EVAL 0.2
condition 5); it gives the fail-safe direction without extra parts.

| Mode | RILIM | Tolerance band of RILIM | IIN_MAX min | IIN_MAX typ | IIN_MAX max |
|---|---|---|---|---|---|
| FC (FET off) | 4.020 kOhm | 3.980-4.060 kOhm | 2890 / 4060 = **0.712 A** | 3333 / 4020 = 0.829 A | 3780 / 3980 = **0.950 A** |
| Regen (FET on) | 4.02 // 4.99 = 2.226 kOhm | 2.204-2.249 kOhm | 2890 / 2249 = **1.285 A** | 3333 / 2226 = 1.497 A | 3780 / 2204 = **1.715 A** |

The FET on-resistance (a few ohms) adds to R_RG and lowers the regen ceiling by less than 0.1 %. The KILIM band is +-13 %;
it dominates the resistor tolerance. The FC row lies inside the KILIM test range. In the regen row the typical (1.497 A) and
minimum values lie inside it; the maximum (1.715 A) lies above the 1.6 A test point and is extrapolated (B, T-7).

Alternative for H5 (section 11.4): R_FC = 3.83 kOhm with R_RG = 5.36 kOhm gives an FC ceiling of 0.747 / 0.870 / 0.997 A
(min / typ / max; 2890 / 3868, 3333 / 3830, 3780 / 3792) and a regen ceiling of 1.281 / 1.492 / 1.709 A (RILIM 2.234 kOhm,
band 2.212-2.256 kOhm). The FC bound after a charger POR is 0.997 + 0.15 = 1.147 A < 1.247 A, and the HR1 minimum at 18.62 V
is 23.9 W. This dossier keeps R_FC = 4.02 kOhm as the reference design and lists the alternative as the H5 option.

### 7.3 Checks

| Check | Calculation | Result |
|---|---|---|
| HR1 regen input at the threshold, worst case | 1.285 A x 18.62 V (VINDPM 19.00 V at -2 %) | **23.9 W >= 23 W** (4.0 % margin). R_RG = 4.99 kOhm meets HR1 at this threshold; a lower R_RG is not needed and would raise the regen maximum above the 1.72 A row of EVAL 2.5 |
| H2 hard-stop allowance at the regen maximum | 1.715 A (extrapolated above the 1.6 A KILIM test point, B) against the EVAL 2.5 rows | Inside the 1.72 A row (117 us at 15.9 V) by 0.3 %; the <= 115 us pass value applies. T-7 confirms the regen maximum; sizing R_RG for a typical ceiling <= 1.6 A is the fallback |
| FC bound after a charger POR | 0.950 A + 0.15 A aux | **1.10 A** < 1.247 A (H-20 P_MAX) < 1.20 A (firmware arm drop) < 1.4 A (OC_FC), without reliance on ICHG or IINDPM |
| FC bound if the mode FET fails short | 1.715 A + 0.15 A | 1.87 A > 1.4 A: OC_FC latches. The core FC-window permit and the eFuse remain; same class as a shorted mode switch in the baseline |
| ILIM_HIZ shorted to GND | Pin ceiling removed; IINDPM register (POR 3.3 A) is the only limit | **New single-fault exposure compared with the baseline** (section 5.1). The adjacent-pin bridge STAT (pin 6) to ILIM_HIZ (pin 7) has the same effect while charging (STAT LOW), and is in the assembly gate T-ASM. Mitigation: firmware compares the input current from the CCB monitor with the mode ceiling and drops PERMIT; the eFuse is the hardware backstop |
| EN_EXTILIM written 0 | Pin disabled | Never-write plus readback; a watchdog expiry restores 1 (DS Table 6-27 p.52) |
| RAC_SNS written 1 with 10 mOhm fitted | Internal scaling assumes 5 mOhm; the true ceiling halves | Safe direction |

S3 = 3 (P): one resistor and one switch, continuous action, published KILIM accuracy.

---

## 8. Warm response and inhibit timing against EVAL section 3.2

### 8.1 Requirements

EVAL 3.2: tau_warm <= 4 ms (10-90 % <= 9 ms; <= 2 ms if the capacitance is board-only), from Vth - 0.5 V to Vth + 1 V; no
input-detect deglitch, POR or soft-start when V-MOT crosses Vth. EVAL 2.5: hard stop within about 115 us of the H1 trip.

### 8.2 Threshold crossing (VINDPM path)

With /CE LOW and V-MOT below VINDPM, the DPM loop holds the charge current near zero and the converter regulates SYS (DS
section 6.3.8.1.2 p.25). A crossing therefore re-runs no qualification: VIN stays far above VIN_OKZ (2.35 V max) and no
plug-in event occurs (P). The VINDPM loop bandwidth and step response are not published (U). The charge-enabled hold below
the threshold is the "always-powered regen" mode of EVAL 0.1; its draw at the bus voltage is the switching quiescent current
(700 uA typical, DS section 5.5 p.6) plus the CCB loads, inside the 5-10 mA of H4.

### 8.3 /CE path (per-burst gate under H1)

| Event | Figure reading, typical (DS p.67, 800 us/div, VBUS 5 V, VBAT 7.4 V, ICHG 1 A, boost mode) | Status |
|---|---|---|
| /CE falling -> converter changes from PFM to continuous switching | 1.18 ms | B |
| /CE falling -> IBAT at its final value | about 1.37 ms; 10-90 % rise about 0.15-0.2 ms after the delay | B |
| /CE rising -> IBAT at zero | within 2 pixels of the edge, about 20 us or less (resolution limit of the published image) | B |
| Adapter plug-in -> switching (cold start, Figure 7-2, 100 ms/div) | about 270 ms | B |

The /CE delay of about 1.2 ms is not a soft-start of the converter, which is already switching in PFM (Figure 7-5 shows SW1
and SW2 active before the edge). Its origin is not documented.

The head start is the time from the H1 release to the moment V-MOT reaches the VINDPM minimum. With the H1 worst
rise maximum of 17.86 V (VBUS 16.39 V, EVAL section 2.2) and the fastest measured rise of 287 V/s (EVAL 3.2):

| Regen VINDPM | VINDPM minimum (-2 %) | Worst-case head start | Against 1.4 ms /CE-to-current (typical) |
|---|---|---|---|
| 18.50 V (alternative) | 18.13 V | (18.13 - 17.86) / 287 = 0.94 ms | Does not fit (0.46 ms short) |
| **19.00 V (this dossier)** | 18.62 V | (18.62 - 17.86) / 287 = **2.65 ms** | Fits with 1.25 ms margin |

At slower rises the head start is longer. The 1.8-11.6 ms range of EVAL 3.2 belongs to the baseline threshold; it is not
reproduced here. All /CE timing figures are typical, at 5 V input and in boost mode; the buck-mode figures at 16-21 V are
bench gate T-8a.

The 1.4 ms figure holds only when a /CE falling edge starts a full-current charge cycle. The data sheet
lists the conditions for a new cycle: VIN > VVIN_OK, **VBAT < VRECHG**, EN_CHG = 1 and /CE LOW, no TS fault, no safety-timer
fault (DS section 6.3.8.2.2 p.28). VBAT is sensed at SRN, which is the VCHG pad behind D-BT-SQ.

- VRECHG POR is 95.5 % x VREG = 8.02 V; the maximum setting 97 % gives 8.15 V (DS Table 6-23 p.49). With SRN held near the
  pack voltage above this level, a /CE edge may not start a cycle, so regen capture at pack voltages of about 8.0-8.4 V is
  not established. The same section states that toggling /CE after termination starts a new cycle; the two statements are
  reconciled only by bench test T-3.VRECHG. The firmware writes VRECHG = 97 % in the POR enable sequence, and HR1 is claimed
  only for SRN < VRECHG until T-3.VRECHG passes.
- If SRN has decayed between bursts, the cycle passes through the low-voltage phases first: trickle at 100 mA for SRN <
  VBAT_SHORT (2.15 V/cell, 4.3 V), pre-charge at IPRECHG (POR 100 mA) for SRN < VBAT_LOWV (POR 71.4 % x VREG = 6.0 V), and the
  VSYSMIN clamp of Table 6-8 while SRN < VSYSMIN (6.2 V): 3.3 A for a deficit below 0.6 V, 1.26 A between 0.6 V and 1.6 V,
  0.3 A above 1.6 V (DS section 5.5 p.8; section 6.3.8.2.3 p.29, Tables 6-7 and 6-8; Table 6-21 p.48; Table 6-23 p.49). The
  Figure 7-5 capture used a real 7.4 V battery, so it shows none of these phases. Bench gate T-6.4b covers SRN between 0 V and
  VSYSMIN; otherwise a keep-alive must hold VCHG above 6.2 V.

### 8.4 Hard stop

The /CE stop is about 20 us or less in the published capture, inside the 115 us allowance. It is a typical boost-mode
capture, not a specification (B). The HIZ stop through ILIM_HIZ has no published latency (U) and is not on the per-burst path.

### 8.5 Scores

S1 = 1 (B). The data sheet documents that the converter stays enabled under DPM and with charge disabled, but the /CE exit
shows a delay of about 1.2 ms, which is above the 1 ms limit of the S1 score-2 anchor. Read against the EVAL 3.2 budget
(tau_warm <= 4 ms), the 1.4 ms edge-to-current time passes; read against the anchor, it misses by about 0.2 ms. The strict
reading is used. S5 = 2 (B): the capture documents a stop well under 1 ms.

---

## 9. Interlock hardware around the BQ25690 compared with the BQ25798 design

### 9.1 System core (identical for every candidate, not counted)

H1 V-MOT/VBUS comparator, H2 FC-window permit with BT_ACT, C7 qualifier, OVN pack-OV term from the BQ29200 OUT (R6 finding 1),
eFuse on VCHG-IN, heartbeat monostables, FCC_OFF/FCC_ON/RGN_ON level sensing (R6 finding 6), MCU watchdog (EVAL 2.6, WD).

### 9.2 IC-specific adders

| Function | BQ25798 (WD) | BQ25690 (CCB) | Difference |
|---|---|---|---|
| /CE pull-up from REGN | 1 resistor | 1 resistor | Same |
| /CE open-drain stage driven by PERMIT | 1 stage (SN74LVC3G06 section) | 1 stage | Same |
| Second hardware layer that stops conversion | 2 (ILIM_HIZ hold-down and release transistors) | 4 (static HIZ drive: micro-power LDO, inverter, Schottky diode, series resistor; section 5.2a) | The BQ25690 layer needs a pull-UP above an unpublished entry level from a VCHG-IN-derived rail, so it costs 2 more parts |
| Mode-switched ILIM resistor and switch | 2 (third resistor, switch keyed to FCC_net) | 2 (R_RG, FET keyed to RGN_ON) | Same count; default is the lower ceiling |
| `CHG_QUAL AND NOT P5` gates (1G04 + 1G08) | 2 | 0 | **Removed**: no input-qualification release of ILIM_HIZ is needed, because /CE HIGH does not block input qualification on the BQ25690 |
| Keep-alive or bridge for D-BT-SQ | DNP option (B.5) | None planned; EN_PRECHG and the SRN phases of section 8.3 decide (bench T-6.4b, T-8b) | Removed if the bench gates pass |
| **Total adders (SCR basis)** | **8** | **8** | S6: both 1 (6-8) |
| /CE redundant pull-up and far-end readback (WD r3-2, r1-3) | +2 (R272b, U204) | +2 | Not in the SCR baseline count; adding them to both gives 10 and 10, S6 = 0 for both |

The like-for-like comparison is therefore even. A count of 4 adders for the BQ25690 is reached only by removing the second hardware
layer instead of replacing it and by leaving out the /CE readback and the redundant pull-up. With /CE as the only hardware path,
one driver or pin fault on /CE (for example the pin 9 to pin 10 bridge) would remove the hardware loop barrier (H1/H2 ->
PERMIT) and leave only EN_CHG and the RT1987 path switches.

| Further part | Purpose |
|---|---|
| Fixed TS divider | Required in any application unless the pack NTC is wired to THERM; not an adder |

### 9.3 Telemetry part (counted in S7, not S6)

One I2C current/voltage monitor on the CCB (section 10.2). The BQ25798 needs none.

### 9.4 Part-count estimate

Charger stage (IC, inductor, BATFET, two shunts, about 16 capacitors, three straps, BTST and filter resistors): about 30 parts.
IC-specific adders: 8 (10 with the /CE readback and redundant pull-up). Telemetry monitor with its decoupling: 3. The system core is unchanged from WD.

---

## 10. Telemetry and I2C

### 10.1 I2C

| Item | Value | Source |
|---|---|---|
| Address | 0x6A (7-bit), fixed | DS section 6.3.11.5 p.41 |
| Speed | Standard, fast and fast-mode-plus (100 kHz, 400 kHz, 1 MHz) | DS section 6.3.11 p.40 |
| Levels | VIH 1.3 V min, VIL 0.4 V max; pull-up rail 1.8-5 V; SDA VOL 0.4 V max | DS section 5.3 p.5; section 5.5 p.12 |
| Register width | 16-bit registers little-endian; multi-write recommended | DS section 6.3.11 p.40 |
| Interrupt | /INT, 256 us active-low pulse | DS Table 4-1 p.4 |
| Unpowered SDA/SCL | Not stated; abs max 6 V on SDA/SCL | DS section 5.1 p.5; back-powering U |
| Watchdog | 40/80/160 s or disabled; POR 40 s | DS Table 6-24 p.50 |

Address 0x6A does not collide with the Ag105 address 0x30, which the BQ25690 replaces, or with the INA228 address range
0x40-0x4F. TODO(verify: the full Teensy I2C bus map on board rev 20260622).

### 10.2 Telemetry

The BQ25690 has no ADC. The register map contains status bits only: PG_STAT, IINDPM_STAT, VINDPM_STAT, TREG_STAT, WD_STAT,
CHARGE_STAT, ICO_STAT, TS_STAT and the fault bits (DS Tables 6-36 to 6-38 pp.57-58). The ILIM_HIZ pin voltage is proportional
to the input current (IIN = KILIM x VILIM / (RILIM x 1 V), DS section 6.3.8.1.2.1 p.26), with the +-13 % KILIM band. No pad
routes it to the Teensy.

The CCB therefore carries an I2C current/voltage monitor. A 20-bit INA228-class monitor (UNVERIFIED part data; TODO(verify:
INA228 data sheet)) across the 10 mOhm RBAT_SNS shunt measures charge current and VCHG; a second channel on RAC_SNS (a second
monitor or a two-channel part) gives input current and VCHG-IN for the FC-window power-balance cross-check (EVAL 0.2 condition
8). The monitor needs the CCB 3.3 V feed. S7 = 0 by the CRIT anchor ("CCB monitor needed for charge current").

---

## 11. Charge capability

### 11.1 Charge current at 3.1 A

ICHG 3.10 A = register 155 = 9Bh (20 mA step, DS Table 6-15 p.46). The 3.3 A register ceiling leaves 6.5 % headroom. The
specified ICHG accuracy is +-5 % at 1.5 A and 0.5 A only, at VBAT = 12, 20 and 28 V (VBAT > VSYSMIN) or 9, 15 and 21 V (VBAT
< VSYSMIN) (DS section 5.5 p.8). No accuracy is published at an 8.4 V (2S) battery: the 2S ICHG accuracy is U (extrapolated),
and the check is part of T-11. Figure 5-12 (p.16; VBUS 20 V, VBAT 16 V) shows about +2 % at 3 A, figure reading, typical. The average inductor current in buck mode equals the charge current and stays below the 4 A limit
(DS section 6.3.7 p.24).

### 11.2 Efficiency and loss

Figure 5-1 (DS p.14; 2S, VBAT 8 V, 450 kHz, 10 uH SRP5050FA-100M), figure reading, typical:

| VBUS | 1.0 A | 1.5 A | 2.5 A | 3.0 A |
|---|---|---|---|---|
| 20 V | 93.7 % | 93.6 % | 92.4 % | 91.4 % |
| 15 V | 95.1 % | 94.9 % | 93.5 % | 92.5 % |
| 12 V | 96.0 % | 95.8 % | 94.2 % | 93.1 % |

Loss at 3.1 A into 8.4 V (P_out = 26.0 W), extrapolated from the 3.0 A points: 20 V input, 91.3 % -> 2.48 W; 15 V input,
92.4 % -> 2.14 W. H10 (<= 2 W) is met at 3.1 A only below about 13 V input. At ICHG 2.8 A and 20 V (P_out 23.5 W, about 91.8 %)
the loss is 2.10 W; at 2.6 A (21.8 W, about 92.1 %) it is 1.87 W. The fitted inductor DCR changes these values; H10 is B.

Buck-path resistance in the charge path (DS section 5.5 p.10 RDS(on)): Q1 + Q4 = 74 mOhm typical (134 mOhm maximum), plus
BATFET 3.7 mOhm, RBAT_SNS 10 mOhm and RAC_SNS 10 mOhm, gives 97.7 mOhm typical before DCR and 107.7 mOhm with an assumed
10 mOhm DCR. At the maximum values with an assumed worst-case DCR of 74 mOhm (TODO(verify: Bourns SRP5050FA datasheet)) the
sum is 134 + 3.7 + 20 + 74 = 232 mOhm. The required input at 8.484 V and 3.21 A is then (8.484 + 3.21 x 0.232) / 0.95 =
9.71 V, below the 10.88 V buck feasibility floor; the part is a buck-boost, so buck headroom does not constrain it.

Conduction loss estimate inside the IC at 3.1 A, 19 V input, buck mode (D = 8.5 / 19 = 0.45; DS section 5.5 p.10, RDS(on) typical
37 / 77 / 77 / 37 mOhm): Q1 3.1^2 x 0.037 x 0.45 = 0.16 W; Q2 3.1^2 x 0.077 x 0.55 = 0.41 W; Q4 (on in buck mode)
3.1^2 x 0.037 = 0.36 W; total 0.93 W typical, about 1.7 W at the 67 / 140 mOhm maximum. With RthJA 22.9 C/W (EVM, 4-layer,
70 um copper; DS section 5.4 p.6) and about 1.4 W in the IC including switching loss (estimate), the junction rises about 32 C.

### 11.3 Regen input at the threshold

| Case | Input at the threshold | Charge into 7.4 V | Charge into 8.4 V |
|---|---|---|---|
| Regen ceiling minimum (1.285 A), VINDPM floor 18.62 V, eta 0.92 | 23.9 W | 2.97 A (input-limited) | 2.62 A |
| Regen ceiling typical (1.497 A), 19.00 V | 28.4 W | 3.10 A (ICHG-limited; input 24.9 W) | 3.10 A (ICHG-limited; input 28.3 W of 28.4 W) |
| ICHG 3.10 A, eta 0.92 | 3.1 x 7.4 / 0.92 = 24.9 W | 3.10 A | 3.1 x 8.4 / 0.92 = 28.3 W needed; ceiling-limited below the typical point |

The input capability for HR1 (>= 23 W at the threshold) is met at the bottom of the ceiling tolerance (23.9 W). Capture is
established only while SRN < VRECHG (8.02 V at POR, 8.15 V with VRECHG = 97 %), because a /CE edge starts a cycle only below
that level (section 8.3). The 8.4 V column is therefore conditional on T-3.VRECHG; at pack voltages of about 8.0-8.4 V, regen
capture is not established. The BQ25798 design reached 20.3 W at 7.4 V because its ICHG cap was 2.50 A (EVAL 3.3); the
BQ25690 needs ICHG >= 23 W x 0.92 / 7.4 V = 2.86 A for the same target, and 3.1 A is inside its range. The loss at that point is the H10 issue of section 11.2. The 18.9 W peak of the
defining 3 -> 1 m/s brake (EVAL 3.2) is covered in every row.

### 11.4 FC mode

IINDPM 0.90 A (register 45 = 2Dh): input 810 / 855 / 900 mA (min / typ / max; DS section 5.5 p.9). The FC hardware ceiling
is 0.712 / 0.829 / 0.950 A (section 7.2); the lower of the two applies (DS section 6.3.8.1.2.1 p.26), so at typical values
the ceiling (0.829 A) binds, not IINDPM. At the 15.57 V loaded bus and 94.9 % (Figure 5-1, 15 V, 1.5 A):

| Input | P_in | Charge into 8.4 V | Charge into 7.4 V |
|---|---|---|---|
| 0.712 A (ceiling minimum) | 11.1 W | 1.25 A | 1.42 A |
| 0.810 A (IINDPM minimum) | 12.6 W | 1.43 A | 1.62 A |
| **0.829 A (ceiling typical, binding)** | 12.9 W | **1.46 A** | 1.66 A |
| 0.855 A (IINDPM typical) | 13.3 W | 1.51 A | 1.71 A |
| 0.900 A (IINDPM maximum; needs the ceiling near the top of its band) | 14.0 W | 1.58 A | 1.80 A |

H5 (>= 1.5 A at 8.4 V) **fails at the typical FC ceiling** with R_FC = 4.02 kOhm (1.46 A). 1.5 A into 8.4 V needs 12.6 W /
0.949 / 15.57 V = 0.853 A of input, which is above the typical ceiling, so H5 is met only near the top of the KILIM band. The
alternative R_FC = 3.83 kOhm of section 7.2 (typical ceiling 0.870 A) moves the binding limit to IINDPM typical (0.855 A,
1.51 A); with the IINDPM band (810-900 mA) H5 is then met at typical values and missed at the IINDPM minimum, which is the
baseline situation (EVAL 0.2 condition 5). The cruise governor
rewrites IINDPM at 50 Hz with 20 mA resolution (DS Table 6-17 p.47). FC-mode CV is +-0.5 % at 0-85 C (DS section 5.5 p.8).

### 11.5 FC purge ruling (2026-11-08)

(Superseded in part 2026-11-10 by the main document, docs/charger_ic_search_2026-11-10.md section 5.6. IO CSV row 31
holds REGEN and BT_BUS LOW inside an FC window. Before a predicted purge the window closes in the order of the 2026-11-05
wiring design (r1-1, invariant I-9) and EVAL section 4.4: the charger is inhibited and its threshold written back above the
bus, then FC_CHARGE_ENABLE goes LOW, then BT_BUS_ENABLE and REGEN_ENABLE close, then the share shifts to the battery.
VCHG-IN has no feed for about 10-12 ms and droops by about 0.3-0.8 V (IQ_VIN 0.25-0.7 mA from about 11 uF), far above
VIN_OKZ 2.35 V; a true POR needs the feed open for about 214 ms or more. The per-purge cold re-entry described below
therefore applies only when D-BC-RG does not re-close within the hold-up, or on an unpredicted collapse, and then to every
part, not to the BQ25690 alone. This handover is a design item; the fw v37 rev 2 Run path does not implement it.)

The ruling (no FC charging during or just before a purge, a preemptive share shift to the battery, EMS-requested charging
between purges) is implemented by the EMS and the core permit, not by the charger. The BQ25690 contributes:

- a /CE stop of about 20 us (typical), so a pre-purge inhibit lands well before the bus sags;
- no warm restart between purges if D-BC-RG stays open. FC_CHARGE_ENABLE goes LOW before BT_BUS_ENABLE closes (IO CSV
  row 31 guard, FAULT_SWITCH_CONFLICT as the backstop), and the share shift follows the BT_BUS close. The FC feed to VCHG-IN
  is therefore opened at every purge, and without a D-BC-RG re-close VCHG-IN decays: the IC draws IQ_VIN 250 uA (not switching) to 700 uA (switching) (DS section 5.5 p.6) from about
  11 uF on the CCB. If the IC does not stay biased from SRN behind D-BT-SQ (DS section 6.3.1 p.20), each purge ends in a true
  POR: the ICHG strap fault, EN_CHG = 0, a cold start of about 270 ms (Figure 7-2, figure reading) and the POR enable sequence
  of section 5.3. If the IC does stay biased, the reconnect is still an adapter plug-in event (cold start). Re-opening the
  window is also a cold D-BC-FC close, which EVAL 0.2 condition 10 restricts. Each purge cycle therefore re-opens the FC
  window from a decayed or unpowered VCHG-IN; the cold start and the I2C re-enable writes are budgeted per purge, and they add
  to the R6 finding 8 burden. Bench gate T-11.5 measures the VCHG-IN decay through a 100-200 ms purge and the SRN bias state;
- an FC ceiling that holds after a charger POR caused by a purge collapse (section 7.3);
- a buck-boost converter that does not stop by physics when the FC-only bus collapses toward the pack voltage; it stops at
  VINDPM (13.23 V minimum in FC mode) and then at VIN_OKZ. The core H2 permit carries the stop.

---

## 12. Layout, package, thermal and bill of materials

### 12.1 Package

RBA0026A, WQFN-HR, 4.1 x 3.6 mm maximum, 0.8 mm maximum height (DS section 10.3 p.78). Signal leads on a 0.45 mm pitch, power
leads 21-25 elongated at 0.4-0.45 mm spacing, one inner thermal pad (26) of 1.77 x 0.652 mm. This is a multi-pad QFN with an
inner pad: S11 = 1. Reflow is required; hand assembly is not practical.

### 12.2 Layout

The data sheet lists eight layout rules in priority order (DS section 7.4.1 p.70). The decisive ones: SYS and VIN capacitors
on the IC layer without vias, SW1 and SW2 routed under the IC to an inductor via, BTST capacitors close, sense traces away from
the switch nodes, at least three thermal vias, a 4-layer board with one internal GND layer for maximum dissipation (DS section
7.4.2 p.72). Two hot loops exist (VIN side in buck mode, SYS side in boost mode). S10 = 1 (integrated buck-boost). A 2-layer
reference layout is printed (DS Figures 7-23, 7-24 pp.71-72).

### 12.3 Power-stage parts

| Part | Selection | Basis |
|---|---|---|
| Inductor | 10 uH, I_SAT >= 4.4 A, shielded | Ripple at 20 V in, 8.4 V out, 450 kHz: 8.4 x 11.6 / (20 x 450e3 x 10e-6) = 1.08 A p-p (35 % of 3.1 A, inside the 20-40 % p-p rule of DS section 7.2.2.1 p.65); I_L,pk = 3.1 + 0.54 = 3.64 A; x 1.2 = 4.4 A |
| BATFET | N-channel, low RDS(on); DS example TPN3R704PL (3.7 mOhm, 3.1 x 3.1 mm) | DS Table 7-2 p.64 |
| RAC_SNS | 10 mOhm, 1 %, >= 0.25 W | 1.715 A^2 x 0.01 = 29 mW |
| RBAT_SNS | 10 mOhm, 1 %, >= 0.25 W | 3.1^2 x 0.01 = 96 mW. 10 mOhm (not 5 mOhm) keeps RBAT_SNS = 0 at POR consistent with the fitted part, so a corrupt RBAT_SNS = 1 halves the charge current instead of doubling it |
| CVIN | 4 x 4.7 uF, 50 V, X7R, 1210, split across RAC_SNS: 3 on the ACP side (between the eFuse output and RAC_SNS), 1 plus 0.1 uF on the ACN side at VIN | >= 10 uF total after DC-bias derating at 22 V; about 8.5 uF ACP and 2.9 uF ACN at 60 % retention. This meets CVIN_ACP >= CVIN_ACN (DS section 5.3 p.5) and CVIN_ACN < 4 x CVIN_ACP (DS section 7.2.2.2 p.66; Table 7-2 p.64 "4x CIN1 > CIN2", CIN1 on the ACP side in Figure 7-1 p.64). The p.5 and p.66 forms of the ratio disagree; the split satisfies both. TODO(verify: TI E2E, which form is binding). >= 35 V rating per DS section 7.2.2.2 p.66 for 24 V inputs |
| CSYS | 4-6 x 4.7 uF, 25 V or more, plus 0.1 uF | >= 15 uF after derating (2S); 35 V rating if bypass mode is considered reachable (section 14) |
| CBAT | 2 x 4.7 uF, 25 V | >= 5 uF after derating |

### 12.4 Input capacitance and inrush (H8, S15)

CCB charger-stage input capacitance: about 11.3 uF after derating (assumed 60 % retention of 18.8 uF at 20 V, TODO(verify: the
selected capacitor's DC-bias curve)) plus 0.1 uF and the 33 nF filters. The ACP / ACN split of section 12.3 moves capacitance
upstream of RAC_SNS but keeps all of it downstream of the eFuse, so the total seen by the RT1987 ramp and the eFuse is
unchanged; only the eFuse output node now carries about 8.5 uF directly. At 12 mA/uF (RT1987, CSS 5.6 nF, EVAL 1.1 H8):
11.5 uF x 12 mA/uF = 0.14 A. The CRIT section 1.2 budget is (1.0 - 0.15) / 0.012 = 70.8 uF for the CCB plus C-D8/C-D10 plus
the eFuse capacitors; the charger stage uses about 16 % of it. The BQ25690 does not switch during the RT1987 ramp (about 1.3 ms),
because its cold start takes about 270 ms (Figure 7-2, figure reading, typical). S15 = 3 (C), provided the motherboard and
eFuse capacitance stay within the remaining 59 uF. TODO(verify: spec.md, C-D8/C-D10 values).

### 12.5 Area

Charger stage about 15 x 20 mm on the top side (IC 4 x 3.5 mm, inductor 7 x 7 mm class, BATFET 3.3 x 3.3 mm, two 2512 or 1206
shunts, 1210 and 0805 capacitors). It fits beside the system core on a CCB that extends sideways past the 32.0 x 34.8 mm Ag105
footprint.

### 12.6 Cost estimate (5 boards; all prices UNVERIFIED)

| Item | USD per board |
|---|---|
| BQ25690RBAR | 5.2 |
| Inductor | 1.5-2.5 |
| BATFET | 0.8 |
| Shunts | 0.6 |
| Capacitors and straps | 2-3 |
| Telemetry monitor | 4-6 |
| IC-specific adders | 0.5-1 |
| **Total (charger-specific)** | **about 15-19** |

S13 = 1 (anchor 2 by value, capped at 1 because the prices are UNVERIFIED).

---

## 13. Stock and price

| Source | Date | Data | Status |
|---|---|---|---|
| DigiKey regional pages (search snippets) | 2026-11-10 | 176 (JP), 460 (DK), 0 (CA-FR); 18-week lead time; USD 5.18 (1), USD 3.15 (250) | UNVERIFIED |
| ti.com product and store pages | 2026-11-10 | HTTP 403 in the sweep (SCR section 5) | Blocked |
| Mouser, Arrow | Not attempted | - | UNKNOWN |

S12 = 1 (UNVERIFIED cap). The power-stage parts are commodity parts; their stock was not checked.

---

## 14. Round-6 findings of the BQ25798 carrier design

Only the IC-dependent findings (CRIT section 3.4) are scored. The geometric findings 13-16 close for every CCB, and finding 3
reopens as a copper-sizing task for every CCB.

| R6 | Sev. | Mechanism on the BQ25690 | Effect |
|---|---|---|---|
| 1 vreg-corruption-no-fixed-pack-ovp | major | VREG is clamped at the strap value 8.40 V, so a single corrupt write to REG0x04 cannot raise CV (P, DS section 6.3.6 p.23). However, REG0x1B holds CELL_PIN_OVERRIDE (bit 6) and CELL_PIN (bits 2:0) in one byte, and a CELL_PIN change rewrites VREG automatically from the cell count (DS section 6.3.6 p.23, Table 6-34 p.56). A single corrupt write of REG0x1B can therefore move VREG, if the device accepts the override and the new CELL_PIN in one write. TODO(verify: SLUSFN4A, TI E2E). A watchdog expiry clears the override bits (P); whether it lowers an already-raised VREG is not stated | **Kept** (mitigated, not closed). The OVN term stays mandatory. REG0x1B is on the never-write list with readback |
| 8 loop-budget-5ms | major | Mode change writes VINDPM (16-bit, 2 data bytes) and IINDPM (2 bytes); the ceiling changes by pin (RGN_ON), with no write. Telemetry moves to the CCB monitor (24-bit reads). The POR enable sequence of section 5.3 (STOP_WD_CHG, EN_BAT_DETECT, VRECHG, FORCE_VINDPM + VINDPM, ICHG_PIN_OVERRIDE, ICHG, EN_CHG) is 6-7 transactions, and it recurs after every true POR, including the purge-induced PORs of section 11.5; the BQ25798 has no strap-fault re-enable | **Kept**; the steady-state burden is of the same order as the BQ25798 image, the per-POR burden is larger |
| 10 chg-src-misattribution | major | No IC ADC. A CCB monitor on RAC_SNS gives input current with the monitor's published accuracy; whether that satisfies the "input-current ADC with a published accuracy" closure condition is a scoring choice, not an IC property | **Kept** |
| 12 reversal-hold-at-100kHz | minor | VINDPM still needs an I2C write per mode change | **Kept** |

New register-corruption exposures (not R6 findings; recorded for the review registry):

| Register bit | Consequence of a corrupt write | Reset by | Mitigation |
|---|---|---|---|
| EN_BYPASS (REG0x12 bit 4) | Q1 and Q4 on, VSYS = VIN (16-21 V); the BATFET regulates charge current linearly; bypass exits only on input current > 115 % of IINDPM or below the light-load limit (DS section 6.3.8.3 pp.33-34) | REG_RESET, WATCHDOG | Never-write plus readback; CSYS rated >= 35 V; BATFET SOA check |
| EN_REV (REG0x13 bit 1) | Reverse mode drives VIN from SRN; SRN sees only VCHG, and D-BC-FC/D-BC-RG block reverse flow into the bus | REG_RESET, WATCHDOG | Never-write plus readback |
| EN_EXTILIM (REG0x14 bit 5) | Hardware ceiling AND HIZ entry through the pin disabled | REG_RESET, WATCHDOG (to 1) | Never-write plus readback |
| VCHG_PIN_OVERRIDE / CELL_PIN_OVERRIDE (REG0x1B) | VREG clamp raised (9.6 V or by cell count) | REG_RESET, WATCHDOG | Never-write plus readback; OVN |
| EN_EXT_BYPASS (REG0x12 bit 3) | External bypass with EN_BYPASS = 1 (DS section 6.3.8.3) | REG_RESET, WATCHDOG | Never-write plus readback |
| EN_BACKUP (REG0x13 bit 0) | Backup mode | REG_RESET, WATCHDOG | Never-write plus readback |
| FORCE_VIN_DSCH (REG0x13 bit 3) | 20 mA load on VIN (IVIN_LOAD, DS section 5.5 p.10) | REG_RESET, WATCHDOG | Never-write plus readback |
| REG_RST (REG0x10 bit 7) | Registers to default: EN_CHG -> 1, ICHG_PIN_OVERRIDE -> 0, FORCE_VINDPM -> 0, EN_BAT_DETECT -> 1, VRECHG -> 95.5 %; pin detection is not re-run (DS section 6.4.2 p.44), so the charge state is U | Self-clearing | Never-write (always 0); /CE and the HIZ layer unaffected; T-5.REGRST |
| EN_MPPT (REG0x17 bit 0) | Enables a routine that stops the converter to measure VOC (VOC_DLY 50 ms-5 s, VOC_RATE 30 s-30 min) and sets VINDPM to VOC_PCT x VOC (POR 84.375 %). No section 6.3 text describes the routine beyond the register table. Its effect on the host VINDPM (S4) and on the warm response is U, TODO(verify: TI E2E) | REG_RESET only (not the watchdog), so a corrupt write persists until REG_RST or POR | Never-write plus readback |

Several hazard bits share a byte with bits that the firmware writes routinely: REG0x12 holds WD_RST (the watchdog kick) and
STOP_WD_CHG next to EN_BYPASS, EN_EXT_BYPASS and RBAT_SNS; REG0x13 holds EN_CHG next to EN_REV, EN_BACKUP, FORCE_VIN_DSCH,
EN_HIZ and RAC_SNS; REG0x14 holds FORCE_VINDPM and EN_BAT_DETECT next to EN_EXTILIM and BATFET_CTRL (DS Tables 6-25 to 6-27
pp.50-52). Every write to REG0x12, 0x13 and 0x14 is therefore a read-modify-write with a masked readback.

The S14 comparison against the baseline never-write list (EVAL section 4.5: REG0A CELL/TRECHG/VRECHG, REG16 pull-downs, REG09
REG_RST, the OTG registers) is as follows. Both lists hold a register reset, an input load (REG16 VAC1_PD_EN, 60 Ohm; here
FORCE_VIN_DSCH, 20 mA), a VREG-moving write (REG0A CELL; here REG0x1B) and reverse-mode bits (OTG; here EN_REV). The BQ25798
also shares EN_CHG with EN_BACKUP in REG0F. The BQ25690 list is longer (bypass, EN_EXTILIM, EN_MPPT), but each added entry is
a never-write bit with readback, of the same class as the baseline entries, and none raises CV above the OVN term. S14 = 2
(net 0: no IC-dependent finding closes; none reopens with a worse mechanism than the BQ25798 REG0A CELL write).

---

## 15. Open questions, bench gates and blocked fetches

### 15.1 Bench gates

| ID | Gate | Pass condition |
|---|---|---|
| T-8a | /CE-to-current in buck mode, VIN 16 V and 19 V, VBAT 7.4 V and 8.4 V, ICHG 3.1 A | Edge-to-90 % <= 2 ms (inside the 2.65 ms worst-case head start at regen VINDPM 19.0 V, section 8.3); measured, not typical |
| T-8b | Warm response under H1 with the V-MOT ramp of EVAL 3.2 (287 V/s and the slowest measured rise) | tau_warm <= 4 ms from the H1 edge |
| T-8c | /CE stop latency at 1.7 A input, buck mode | <= 115 us (EVAL 2.5) |
| T-8d | VINDPM step response at 19.0 V | No overshoot that trips the VESC cut-off at 21.20 V |
| T-3.VRECHG | /CE falling edge with SRN at 8.1 V and at 8.35 V (VRECHG 95.5 % and 97 %), CE toggled after a previous burst | Records whether a charge cycle starts above VRECHG; decides the HR1 statement for pack voltages of 8.0-8.4 V |
| T-6.4 | Battery detection behind D-BT-SQ, EN_BAT_DETECT 1 and 0 | Record SRN at start-up and the VCHG-node leakage; with 1: record the BAT_FAULT_STAT verdict; with 0: charge starts |
| T-6.4b | Start from a decayed VCHG: SRN below VBAT_SHORT (4.3 V), between VBAT_SHORT and VBAT_LOWV (6.0 V), and between VBAT_LOWV and VSYSMIN (6.2 V), EN_PRECHG 1 and 0 | Time from /CE edge to CC at 3.1 A <= 2 ms, or a keep-alive must hold VCHG above 6.2 V |
| T-5.4 | Strap-fault POR inhibit and register retention | After every true POR path (VIN and SRN cycle, TSHUT) no charge current until the POR enable sequence; after a VCHG-IN dropout with SRN held up, record whether registers are retained (no POR); record the ICHG register and the ICHG clamp after a watchdog; with STOP_WD_CHG = 0, record EN_CHG after a watchdog expiry (data sheet contradiction, section 5.1) |
| T-5.HIZ | ILIM_HIZ HIZ entry and exit | Pin level at which HIZ is entered (VIH_ILIM_HIZ has a MIN only); HIZ entered at the 3.3-3.8 V drive of section 5.2a in both mode states; whether the strap re-read at the pin exit clears EN_CHG again; HIZ stop latency |
| T-5.REGRST | REG_RST with the ICHG strap fault | Whether charging starts after REG_RST (pin detection not re-run, EN_CHG -> 1, ICHG_PIN_OVERRIDE -> 0) with /CE LOW and HIZ released |
| T-11.5 | VCHG-IN decay through a 100-200 ms purge (FC_CHARGE opened) | VCHG-IN and SRN waveforms; whether the IC stays biased from SRN or reaches a true POR; time and I2C transactions to re-open the window |
| T-7 | ILIM ceiling at 19.0 V (regen) and 15.6 V (FC), both mode states | Input inside 1.285-1.715 A and 0.712-0.950 A; the regen maximum above 1.6 A is extrapolated from KILIM and is checked against the 117 us row of EVAL 2.5 |
| T-11 | Loss, IC temperature and ICHG accuracy at 3.1 A, 16 V and 20 V input, 2S pack | Loss <= 2 W, or ICHG cap reduced to the value that meets it; ICHG error at 8.4 V recorded (no 2S accuracy is published) |
| T-ASM | Assembly inspection of the adjacent-pin bridges 6-7 (STAT-ILIM_HIZ), 9-10 (/CE-GND), 14-15 (VCHG-ICHG) | No bridge; plus a POR self-check that reads ICHG_PIN, CELL_PIN and VCHG_PIN (REG0x1B/0x1C) and expects the ICHG fault code |
| T-10 | SDA/SCL with the BQ25690 unpowered and the Teensy bus at 3.3 V | No back-powering current > 10 uA, bus functional |
| T-14 | REG0x1B single-write test (CELL_PIN_OVERRIDE and CELL_PIN in one write) | Characterises the R6 finding 1 path |

### 15.2 Open questions (data sheet does not answer)

1. Origin of the 1.2 ms /CE-to-switching delay and its value in buck mode. TODO(verify: TI E2E).
2. ICHG register value and ICHG clamp after an ICHG strap fault and after a watchdog clears ICHG_PIN_OVERRIDE. TODO(verify:
   SLUSFN4A, TI E2E).
3. BATFET state with /CE HIGH and VBAT above VSYSMIN (DS section 6.3.8.1.1 p.25 states the SYS regulation point, not the
   BATFET state).
4. Whether REG_RST resets STOP_WD_CHG (no "Reset by" entry, DS Table 6-25 p.51).
5. VINDPM loop bandwidth (not published).
6. Whether a VREG value above the clamp is lowered when a watchdog clears VCHG_PIN_OVERRIDE.
7. Whether pad THERM carries the pack NTC on board rev 20260622; otherwise a fixed TS divider (EN_TS POR 1, JEITA POR enabled,
   DS Table 6-32 p.55). TODO(verify: spec.md).
8. STAT states (DS Table 6-11 p.39): LOW = charging (including recharge and top-off); HIGH = charging complete, HIZ, charge
   disabled, battery-only or OTG; blinking at 1 Hz = charge suspend (a fault that disables charging). The steady polarity is
   the inverse of the Ag105 steady-HIGH = charging that the firmware decodes on `CHARGER_STAT` (pin 6), and the 1 Hz fault
   blink differs from the Ag105 pulse trains. A firmware change is needed before use; no firmware is changed by this dossier.
9. Whether a /CE edge starts a cycle with SRN above VRECHG (DS section 6.3.8.2.2 p.28 lists VBAT < VRECHG as a start condition
   and also states that toggling /CE after termination starts a new cycle). T-3.VRECHG.
10. Which form of the CVIN split is binding: CVIN_ACP >= CVIN_ACN (DS section 5.3 p.5) or CVIN_ACN < 4 x CVIN_ACP (DS section
    7.2.2.2 p.66). TODO(verify: TI E2E).
11. EN_CHG after a watchdog expiry with STOP_WD_CHG = 0 (DS Tables 6-25 and 6-26 p.51 contradict each other). TODO(verify: TI
    E2E).
12. The ILIM_HIZ level that guarantees HIZ entry (VIH_ILIM_HIZ MIN 1.77 V only, DS section 5.5 p.9). TODO(verify: TI E2E).
13. The plug-in threshold with SRN powered (VIN_OKZ and VIN_OK are specified "no battery"; VVIN_UVLOZ has no value, DS section
    5.5 p.6, section 6.3.10.1 p.38). TODO(verify: SLUSFN4A, TI E2E).
14. Function of the EN_MPPT routine beyond the REG0x17 register table, and its interaction with FORCE_VINDPM. TODO(verify: TI
    E2E).

### 15.3 Blocked or not attempted fetches

| URL | Reason |
|---|---|
| https://www.ti.com/product/BQ25690 | HTTP 403 to WebFetch and curl in the sweep (SCR section 5); lifecycle taken from DS section 10.1 |
| TI store inventory for BQ25690RBAR | Not attempted after the 403 above |
| BQ25690EVM user guide (TI literature number not identified) | Not attempted; needed only for the EVM layout and BOM |
| https://www.digikey.com/en/products/detail/texas-instruments/BQ25690RBAR/28738808 | Not fetched; only regional snippets were seen (UNVERIFIED) |
| INA228 data sheet (https://www.ti.com/lit/ds/symlink/ina228.pdf) | Not fetched; the monitor selection in section 10.2 is UNVERIFIED |

---

## 16. Verdict and comparison with the BQ25798

(Superseded 2026-11-10 by scoring.md sections 2.3, 2.6 and 7: under the common S6 counting rule the BQ25690 has 9 adders,
S6 = 0 and a total of 48.3 against the BQ25798 baseline of 40.3, a margin of 8.0. The 51.7 against 45.0 comparison below is
kept as the dossier record only. The purge assumption of section 11.5 is also superseded; see the note there.)

**Verdict: FEASIBLE_W_COND.** The BQ25690 passes every must-have, with conditional passes on M4 (loss at 3.1 A), M8 (FORCE_VINDPM
discipline), M9 (buck-mode warm response and the VRECHG start condition), M10 (unpowered I2C behaviour), M11 (CCB monitor) and
M5 (the pin that stops conversion is ILIM_HIZ, whose HIZ entry level is not published). The M5 condition concerns a must-have
on which the BQ25798 has P evidence, so CRIT section 3.5 condition 1 is not met until T-5.HIZ passes.

Scores (CRIT section 3.1 with the section 3.2 evidence cap):

| Criterion (weight) | BQ25798 (SCR 4.1) | BQ25690 (this dossier) | Evidence and change from SCR |
|---|---|---|---|
| S1 (15) | 1 | 1 | B; SCR 2 lowered: 1.2 ms /CE delay exceeds the 1 ms anchor |
| S2 (10) | 0 | 2 | P; SCR 1 raised: ICHG strap fault clears EN_CHG at a true POR (not after an input dip with SRN bias, U after REG_RST) |
| S3 (8) | 2 | 3 | P; SCR 2 raised: continuous analog ceiling, KILIM published, ROC 0-33 kOhm |
| S4 (8) | 2 | 2 | P |
| S5 (7) | 1 | 2 | B; SCR 1 raised: /CE stop about 20 us in the published capture |
| S6 (10) | 1 | 1 | C; 8 adders against 8 like for like (section 9.2); a single-layer count of 4 is not like for like |
| S7 (5) | 2 | 0 | P; SCR 2 lowered: no ADC |
| S8 (6) | 2 | 2 | P |
| S9 (4) | 0 | 2 | P (45 V) |
| S10 (7) | 1 | 1 | P |
| S11 (3) | 1 | 1 | P |
| S12 (5) | 3 | 1 | UNVERIFIED cap; SCR 2 lowered |
| S13 (2) | 3 | 1 | UNVERIFIED cap; SCR 3 lowered |
| S14 (5) | 2 | 2 | C |
| S15 (3) | 2 | 3 | C |
| S16 (2) | 1 | 0 | C; SCR 1 lowered: relative VINDPM follows the input below the pack (section 6.2) |
| **Weighted total (of 100)** | **45.0** | **51.7** | |

Weighted terms for the BQ25690: 5.00 + 6.67 + 8.00 + 5.33 + 4.67 + 3.33 + 0 + 4.00 + 2.67 + 2.33 + 1.00 + 1.67 + 0.67 + 3.33
+ 3.00 + 0 = 51.67.

The baseline column is the SCR section 4.1 score. The BQ25798 finalist dossier (`dossier_BQ25798.md`) scores the baseline at
about 40, with S6 = 0 at 9 or more adders. Under that count the like-for-like BQ25690 count, with the /CE readback and the
redundant pull-up, is 10, so its S6 is also 0 and its total 48.3; the margin is then about 8.3 points. On either basis the
margin is below the 10 points of CRIT section 3.5 condition 2.

**Comparison.** Against the BQ25798 baseline the BQ25690 gains in four places: a 45 V rating with VIN_OVP at 35.5 V minimum,
which removes the 30 V abs-max gap of the baseline (M2 is P here; the BQ25798 30 V rating is below the CRIT M2 limit as
written); a continuous, fail-low, mode-switched hardware input ceiling at 10 mOhm with a published KILIM band; an intrinsic
inhibit through the ICHG strap fault at a true POR, so such a POR cannot charge the pack without host writes; and a 3.3 A ICHG
range that meets the HR1 23 W target at a 7.4 V pack, which the baseline's 2.50 A cap does not. The interlock hardware is not
smaller: a like-for-like count with two hardware layers (/CE per burst, the static ILIM_HIZ HIZ drive) gives 8 adders for both
parts, because the BQ25690 HIZ layer needs a pull-up from a VCHG-IN-derived rail.

Against it stand the following risks:

- M5 is a conditional pass: /CE disables charging but does not stop conversion, and the HIZ entry level of ILIM_HIZ is not
  published, so CRIT section 3.5 condition 1 is open until T-5.HIZ passes.
- No ADC: a CCB monitor is required, and R6 finding 10 stays open.
- A grounded ILIM_HIZ pin (or a STAT-to-ILIM_HIZ bridge while charging) defeats the hardware ceiling instead of inhibiting the
  converter, a fault direction the baseline does not have.
- The warm response rests on one typical boost-mode capture at 5 V with a 1.2 ms /CE delay of undocumented origin. The
  worst-case head start is 2.65 ms only with regen VINDPM at 19.0 V. A /CE edge starts a cycle only with SRN < VRECHG, so regen
  capture at pack voltages of about 8.0-8.4 V is not established, and a decayed VCHG node re-enters trickle, pre-charge and
  the Table 6-8 clamps. HR1 remains UNDETERMINED, as for the baseline.
- H5 fails at the typical FC ceiling with R_FC = 4.02 kOhm (1.46 A at 8.4 V); R_FC = 3.83 kOhm restores the baseline situation.
- The charger watchdog shortest setting is 40 s (nominal; no maximum published) against 0.5 s in the baseline, so the heartbeat monostables are the only fast hung-MCU
  tier.
- Each FC purge opens the FC charge feed (FC_CHARGE / BT_BUS exclusion), so the window re-opens cold, and after a true POR
  with the 6-7-transaction POR enable sequence, which adds to R6 finding 8.

The weighted margin is 6.7 points against the SCR baseline (about 8.3 against the finalist-dossier baseline). It depends on
S12/S13 evidence caps that a vendor-page fetch could raise by up to 4.0 points (S12 1 -> 3, S13 1 -> 2), and on an S1 reading
that could move it by 5 points in either direction once T-8a is measured. Condition 4 (S1 at least the baseline S1) holds at
1 = 1, and condition 3 holds (no major R6 finding reopens). The BQ25690 therefore does **not** beat the BQ25798 by enough to
switch. It is recorded as the **alternate**, subject to T-5.HIZ (condition 1). Its advantages in rating, ceiling and 3.3 A
charge range are real; bench gates T-8a, T-3.VRECHG, T-5.HIZ, T-5.4 and T-11.5 decide whether it can overtake the baseline.

---

## 17. Verification log

Two independent reviews of this dossier were checked against SLUSFN4A (84 pp., MD5 95895e694b73cf1e851af891d5c99e4e, the same
file as the sweep copy). Each finding was re-read in the primary source before disposition.

| # | Finding | Severity | Disposition | Basis |
|---|---|---|---|---|
| 1 | H5 "met at the nominal setting": typical FC ceiling 0.829 A binds below IINDPM; 0.90 A is the IINDPM maximum | major | Applied | DS section 5.5 p.9 (IINDPM 810/855/900 mA; KILIM row); section 6.3.8.1.2.1 p.26 (lower limit applies). 0.829 x 15.57 x 0.949 / 8.4 = 1.46 A. Sections 4, 7.2, 11.4 rewritten; R_FC 3.83 kOhm option added with the FC-bound recheck (1.147 A < 1.247 A) |
| 2 | Input capacitance must be split across RAC_SNS | major | Applied | DS section 5.3 p.5 (CVIN_ACP >= CVIN_ACN, read on the rendered page); section 7.2.2.2 p.66 (CVIN_ACN < 4 x CVIN_ACP); Table 7-2 p.64. Sections 1.4, 2.2, 12.3, 12.4 updated; ratio inconsistency recorded as TODO |
| 3 | HR1 omits the VBAT < VRECHG start condition | major | Applied | DS section 6.3.8.2.2 p.28 (start conditions; /CE toggle after termination); Table 6-23 p.49 (VRECHG POR 10b = 95.5 %). Sections 4, 6.3, 8.3, 11.3; gate T-3.VRECHG added |
| 4 | /CE 1.4 ms figure ignores trickle, pre-charge and Table 6-8 phases | minor | Applied | DS section 5.5 p.8 (IBAT_SHORT, VBAT_SHORT); Tables 6-7, 6-8 p.29; Table 6-21 p.48 (IPRECHG POR 100 mA); Table 6-23 p.49 (VBAT_LOWV POR 11b). Section 8.3; T-6.4b extended |
| 5 | KILIM test conditions and extrapolation above 1.6 A | minor | Applied | DS section 5.5 p.9 (one row, IIN_MAX = 1.6 A, 1 A, 0.5 A). Sections 1.4, 3, 7.1, 7.2, 7.3; T-7 |
| 6 | VBAT_DET POR value omitted | minor | Applied | DS Table 6-28 p.53 (VBAT_DETECT reset 0x0 = 2.8 V/cell). Section 6.4 |
| 7 | EN_CHG / STOP_WD_CHG contradiction | minor | Applied | DS Table 6-26 p.51 (EN_CHG reset by WATCHDOG); Table 6-25 p.51 (STOP_WD_CHG 0b keeps EN_CHG). Sections 5.1, 5.4; T-5.4; question 11 |
| 8 | "At most 40 s" watchdog has no published maximum | minor | Applied | DS section 5.6 pp.12-13 (tLP_WDT 100 / 160 s, tWDT 136 / 160 s, no MAX). Sections 5.4, 5.5 |
| 9 | VIH_ILIM_HIZ has a MIN only; HIZ entry not guaranteed | minor | Applied | DS section 5.5 p.9 (MIN 1.77 V, TYP and MAX blank). Sections 3 (M5), 5.1, 5.2a; T-5.HIZ; question 12 |
| 10 | ICHG accuracy test conditions omitted; no 2S point | minor | Applied | DS section 5.5 p.8 (VBAT 12/20/28 V and 9/15/21 V); Figure 5-12 p.16 (VBAT 16 V). Sections 3 (M4), 11.1; T-11 |
| 11 | 2.83 A arithmetic inconsistent with eta 0.92 | minor | Applied | 23 x 0.92 / 7.4 = 2.86 A. Section 11.3 |
| 12 | EN_MPPT missing from the corruption table | minor | Applied | DS Table 6-30 pp.53-54 (EN_MPPT bit 0, reset by REG_RESET only); no routine description in section 6.3 (text search). Sections 6.3, 14; question 14 |
| 13 | Inconsistent count of POR enable writes | minor | Applied | DS section 6.3.6 p.24 (host programs the profile, then EN_CHG). One named sequence in section 5.3, reused in 5.5, 14, T-5.4 |
| 14 | VIN_OKZ specified "no battery"; VVIN_UVLOZ has no value | minor | Applied | DS section 5.5 p.6; section 6.3.10.1 p.38. Sections 3 (M9), 6.2; question 13 |
| 15 | STAT state set incomplete | minor | Applied | DS Table 6-11 p.39; Table 4-1 p.4. Section 2.2, question 8 |
| 16 | Page count 80 instead of 84 | minor | Applied | PDF page tree: 84 pages (pdfinfo). Section 1.2 |
| 17 | S6 count drops the second hardware layer, the /CE readback and the redundant pull-up | major | Applied | DS section 6.3.8.1.1 p.25 and Figure 7-7 p.67 (converter keeps switching with /CE HIGH); WD r1-3, r1-4, r3-2. Section 5.2a added; section 9.2 recounted to 8 vs 8; S6 2 -> 1; total 55.0 -> 51.7 |
| 18 | M5 passed on /CE, which does not stop conversion | major | Applied | CRIT M5 text; DS section 6.3.8.1.1 p.25; section 6.3.3 p.21 (HIZ stops switching); section 6.3.8.1.2.1 p.26 (EN_EXTILIM = 0 also disables HIZ through the pin). M5 re-stated as a conditional pass through ILIM_HIZ; HIZ drive made mandatory; CRIT 3.5 condition 1 open |
| 19 | Head start copied from the baseline threshold; 0.94 ms at 18.5 V | major | Applied | EVAL section 2.2 (worst rise max 17.86 V); EVAL 3.2 (287 V/s). (18.13 - 17.86) / 287 = 0.94 ms. Regen VINDPM moved to 19.0 V: 2.65 ms, HR1 23.9 W. Sections 4, 6.1, 7.3, 8.3, 11.3; T-7, T-8a, T-8d |
| 20 | Purge "warm restart" conflicts with the FC_CHARGE / BT_BUS exclusion | major | Applied | IO CSV row 31 guard and the purge ruling (as cited in the reviewer's evidence and in the project rules); DS section 5.5 p.6 (IQ_VIN); section 6.3.6 p.24; Figure 7-2 p.67. Section 11.5 rewritten; T-11.5 added; R6 finding 8 row updated |
| 21 | Battery detection claimed as a POR-safe property (C) | major | Applied | DS section 6.3.8.2.1 pp.27-28 ("If VBAT < VBAT_SHORT at startup"; "is allowed to discharge"; 2 s plug-in rule); section 5.5 p.8; Table 6-28 p.53. Section 6.4 downgraded to B; removed from the verdict; H7 and T-6.4 updated |
| 22 | Adjacent-pin bridges create a valid ICHG strap, hold /CE LOW, or defeat the ceiling | minor | Partly applied | DS Figure 4-1 p.3 confirms the pin order. Rejected in part: ICHG is tied directly to GND, so a 14-15 bridge shorts the VCHG strap to GND, which is a VCHG strap fault (DS Table 6-2 p.22) and gives no charge; it does not create a valid ICHG code. Applied: the 9-10 (/CE-GND) and 6-7 (STAT-ILIM_HIZ) bridges, the /CE readback, the strap-readback POR self-check and gate T-ASM (sections 5.2, 5.3, 7.3) |
| 23 | Charger watchdog 40 s minimum against the 0.5 s baseline | minor | Applied | DS Table 6-24 p.50 (00b disable, 01b 40 s, 10b 80 s, 11b 160 s); EVAL section 4.5 (REG0x10 = 0x81). Sections 5.4, 5.5, 16 |
| 24 | Never-write list incomplete; shared bytes not noted | minor | Applied | DS Table 6-25 pp.50-51 (REG0x12: RBAT_SNS, EN_BYPASS, EN_EXT_BYPASS, WD_RST, STOP_WD_CHG); Table 6-26 p.51; Table 6-27 p.52; Table 6-23 p.49 (REG_RST); section 6.4.2 p.44 (REG_RST does not re-run pin detection). Section 14 extended with the S14 comparison; T-5.REGRST |
| 25 | A VIN dip with SRN bias is not a POR | minor | Applied | DS section 6.3.1 p.20 ("Either VIN or the battery connected at SRN power the internal bias circuits"); section 5.5 p.6. Sections 5.3, 5.5; T-5.4 |
| 26 | Regen ceiling maximum above the KILIM test points; 0.3 % H2 margin | minor | Applied | DS section 5.5 p.9. Sections 7.2, 7.3 (H2 row labelled B); T-7 against the 117 us row; R_RG 4.75 kOhm variant not used |

Review 1 findings are rows 1-16; review 2 findings are rows 17-26. Applied: 25. Partly applied: 1. Rejected: 0. The verdict on
the part (FEASIBLE_W_COND) is unchanged; the comparison with the BQ25798 changes from "credible challenger at the 10-point
threshold" to "alternate, margin 6.7 points, condition 1 open on M5".
