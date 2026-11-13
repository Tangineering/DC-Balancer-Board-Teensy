# Dossier: TI BQ25773 (with the BQ25770G sibling) on the custom charger board, Ag105 replacement for board rev 20260622

Date: 2026-11-10. This dossier assesses the TI BQ25773 as the charger IC of the **custom charger board (CCB)** defined in
`screening_criteria.md` section 1.1. It builds on the round-2 dossier
`docs/reviews/charger_eval_2026-11-05/round2/dossier_BQ25773.md` (cited as **[R2-773]**). Facts that [R2-773] read from the
primary and that this dossier re-checked are cited to the primary directly. Facts that rested on the BQ25773EVM are
re-derived for the CCB. Corrections to [R2-773] are listed in section 15.3.

Status codes: P = PROVEN_DATASHEET, C = PROVEN_CALC, B = BENCH_GATE, F = FAIL, U = UNKNOWN or missing primary,
sys = blocked at system level. "c" in a must-have column means a conditional pass (screening_criteria.md section 2).

---

## 1. Identity and sources

### 1.1 Parts

| Part | Orderable part number | Interface | Gate drive | Package |
|---|---|---|---|---|
| BQ25773 | BQ25773REER (also BQ25773REER.A, the same die and package) | I2C, 7-bit address 0x6B | 5 V N-channel Si MOSFET drive, six switches plus an N-channel BATFET | WQFN-36 (REE), 4.0 x 5.0 mm |
| BQ25770G | BQ25770GREER (also BQ25770GREER.A) | SMBus, 7-bit address 0x09 | Buck dual-phase gate drive for E-mode GaN HEMTs | WQFN-36 (REE), 4.0 x 5.0 mm |

Both orderable part numbers are "Active, Production", 3000-unit large tape and reel, MSL 1 at 260 °C, -40 to 125 °C
(SLUSEK7 orderable addendum p.138; SLUSFK8 orderable addendum p.129).

### 1.2 Primary documents read

| Tag | Document | Revision read | URL | Fetched | Pages read |
|---|---|---|---|---|---|
| **[DS]** | TI SLUSEK7, *BQ25773 40V, I2C, 2- to 5-Cell, Narrow VDC Quasi Dual Phase Buck-Boost Battery Charge Controller*, 144 pp. | SLUSEK7, September 2024 (no later revision exists at the URL; MD5 of the 2026-11-10 download equals the sweep copy) | https://www.ti.com/lit/ds/symlink/bq25773.pdf | 2026-11-10 | pp.1, 4-24 (features, pins, ratings, EC, timing, curves), 25-56 (detailed description), the register map pp.57-122 for every field cited, 123-133 (application, layout), 137-141 (orderable and package) |
| **[DS-G]** | TI SLUSFK8, *BQ25770G 40V, SMBus, 2- to 5-Cell, Narrow VDC Quasi Dual Phase Buck-Boost Battery Charge Controller for GaN HEMT*, 135 pp. | SLUSFK8, April 2024 | https://www.ti.com/lit/ds/symlink/bq25770g.pdf | 2026-11-10 (sweep copy) | pp.1, 4, 8, 12, 27, 51, 55, 57, 113, 117-119, 129 only (identity, comparison table, ratings, address, register base, application diagram, orderable) |
| **[UG]** | TI SLUUCY2, *BQ2577x Evaluation Module User's Guide*, November 2023 | SLUUCY2 | https://www.ti.com/lit/ug/sluucy2/sluucy2.pdf | 2026-11-10 (downloaded; not re-read beyond [R2-773]) | Layout information only; [R2-773] read the schematic and BOM |
| **[TIstore]** | ti.com store inventory endpoint and part-details page | - | `https://www.ti.com/storeservices/cart/opninventory?opn=<OPN>`; https://www.ti.com/product/BQ25773/part-details/BQ25773REER | 2026-11-10 18:27 UTC | Inventory count; the JSON-LD "price" field |

The downloaded datasheets are not retained in the repository; the literature-number and page citations are the record. Text was extracted with pdftotext; garbled tables
(DS p.12, p.20, p.28, p.39, p.123, p.125) were read from the rendered page.

### 1.3 Secondary sources

| Fact | Source | Status |
|---|---|---|
| USD 3.140 for BQ25773REER | ti.com part-details page, JSON-LD `offers.price`; the quantity basis is not stated | UNVERIFIED as a unit price |
| Prices of the external FETs, inductors, sense resistors and capacitors in section 12 | Engineering estimates; no distributor page was read | UNVERIFIED |
| MLCC DC-bias derating of 1206 50 V X7R parts in section 7.4 | Not read from a manufacturer curve | UNVERIFIED |

### 1.4 Board-side sources

`screening_criteria.md` (**CRIT**), `screening.md` (**SCR**), `docs/charger_replacement_evaluation_2026-11-05.md`
(**EVAL**, sections 1.1, 1.2, 2.5, 3.2, 3.4), `docs/reviews/charger_eval_2026-11-05/spec.md` (**SPEC**, the pad table and
section 6 inrush model), `docs/charger_bq25798_wiring_design_2026-11-05.md` (**WD**) and
`docs/reviews/charger_eval_2026-11-05/round3/review_loop.md` (**R6**).

---

## 2. Architecture on the custom board

### 2.1 Topology

The BQ25773 is a controller for a **quasi dual-phase NVDC buck-boost** stage (DS §7.3.16 p.40). The power stage is
external: six N-channel switches (Q1_A/Q2_A buck phase A, Q1_B/Q2_B buck phase B, Q3/Q4 boost leg), two inductors (one per
buck phase, joined at SW2), an N-channel BATFET Q5, two input sense resistors RAC_A and RAC_B (10 mΩ each) and one charge
sense resistor RSR (5 mΩ) (DS Fig 8-1 p.123; DS §8.2.2.6 p.128, p.130). Every MODE-pin code selects the quasi dual-phase
topology; no MODE code selects a plain single-phase buck-boost (DS Table 7-1 p.28).

In buck mode Q4 stays on and the buck phases switch. Below the SINGLE_DUAL_TRANS_TH load threshold only phase A switches
(phase shedding, DS §7.3.16 p.40). The POR threshold is 6 A (REG0x14 bits 7-5 = 100b, DS p.74), with a 1 A lower drop
threshold, so at the CCB load (at most about 3.4 A of output current) phase B is idle in buck mode. FORCE_SINGLE (REG0x14 b4)
holds single-phase operation in buck mode. In buck-boost mode both buck phases switch in sequence; in boost mode Q1_A and
Q1_B stay on and only the boost half bridge switches, at 2 × Fsw, so both phase inductors carry current (DS §7.3.16 p.40,
Table 7-7 p.40-41). Phase B therefore must be populated: the datasheet gives no single-phase build, and the phase-B
switches conduct whenever VBUS approaches VSYS (start-up, decay of VCHG-IN). **A single-phase build is not documented and is
not proposed.** Phase B may be sized for light load only if a TI statement permits it: TODO(verify: TI E2E, asymmetric
phase sizing).

The BATFET is required by the NVDC architecture: pre-charge and trickle use it as a linear regulator (DS §7.3.26.8 p.49) and
the battery is sensed at SRN behind it (DS Table 10-1 rule 5 p.132). **A BATFET-less build is not documented and is not
proposed.**

### 2.2 Buck versus buck-boost

CRIT section 4.8 concludes that a buck charger covers the 2S envelope. The BQ25773 is a buck-boost and operates in buck mode
across the regen and FC operating range (VCHG-IN 13.1-22.3 V against VSYS at most about 8.6 V). Its boost capability earns
nothing (CRIT S16 = 0): with VINDPM at its 3.2 V POR value the converter can regulate VSYS from VBUS down to
VVBUS_CONVEN (3.1-3.7 V, DS p.16). Charging below the FC threshold is blocked by CHARGE_CURRENT = 0 at POR and, after
configuration, by the VINDPM register, not by a hardware floor.

### 2.3 Position between VCHG-IN and VCHG

| Node (CCB) | Element | Note |
|---|---|---|
| VCHG-IN pad (pad 10) | eFuse (system core, not counted) | WD B.4 function |
| eFuse output | VBUS pin through 1 Ω / 0.47 µF (DS pin table p.5) | Optionally tap VBUS upstream of the eFuse: the SC_VBUSACP comparator then holds the converter off while VBUS - ACP_A > 0.70-1.00 V (DS p.15, §7.3.26.9 p.49-50); not relied on, deglitch unpublished |
| Input bank | MLCC before RAC_A and RAC_B; at most 10 µF + 10 nF + 1 nF after each RAC (DS §8.2.2.4 p.126) | Section 7.4 sizes it |
| RAC_A, RAC_B | 10 mΩ, high side | ACP/ACN RC filters 4.99 Ω / 33 nF with 100 nF differential (DS Fig 8-3 p.125) |
| Phases A and B | Q1_x/Q2_x, inductors L_A, L_B | 3.3 µH as characterised (DS §6.7 p.22) |
| SW2 leg | Q3, Q4 | Q4 constant on in buck mode |
| VSYS | ≥ 50 µF effective (DS §8.2.2.5 p.127, Table 8-5) | Unloaded on this board |
| BATFET Q5, RSR | N-channel, 5 mΩ high-side sense | SRN senses VCHG |
| VCHG pad (pads 18, 19) | To D-BT-SQ on the motherboard | Unchanged |

### 2.4 What the 22-hole plug-in board carries

| Pad (SPEC) | CCB net | BQ25773 pin |
|---|---|---|
| VCHG-IN | eFuse input | VBUS, ACP_A/B via RAC |
| GND (VIN-, VBAT-) | PGND plane, AGND joined under the exposed pad (DS Table 10-1 rule 10 p.133) | Exposed pad |
| VCHG (VBAT+) | Downstream of RSR | SRN |
| SDA, SCL | I2C, motherboard pull-ups | SDA (19), SCL (20) |
| STAT (pin 6) | CHRG_OK open drain, Teensy-side pull-up | CHRG_OK (11) |
| MPPTD (pin 5) | P5 term of PERMIT | Via the inhibit stage to ILIM_HIZ (13); to CMPIN_TR (22) only in the optional fast path (section 9.3) |
| THERM (pad 13) | J-NTC pin 1, external NTC to GND (SPEC pad table); the bias divider goes on the charger side | None. The BQ25773 has no battery TS or JEITA input; CMPIN_TR is an independent-comparator input or, with CMPIN_TR_SELECT = 1, a power-stage temperature-regulation input (DS pin table p.7, §7.3.6 p.33). Battery-temperature qualification is therefore absent unless a CCB comparator from THERM into the inhibit chain is added (an adder, section 9.2) |

Board-local straps: CELL_BATPRES 40 % of REGN (2S, window 18.4-48.5 %, DS p.20); MODE 3.57 kΩ (normal compensation,
600 kHz) or 6.04 kΩ (slow, if the effective input capacitance is below 10 µF) (DS Table 7-1 p.28); EN_OTG to GND.

---

## 3. Must-have check

| ID | Result | Value | Citation |
|---|---|---|---|
| M1 common ground | **P** | One PGND for input and battery; RAC_A/B in the input high side; RSR between BATFET and battery in BAT+; nothing in a return | DS Fig 8-1 p.123; pin table SRP/SRN p.7 |
| M2 input rating | **P** | 45 V abs max on VBUS, ACP_x, ACN_x, VSYS, SW1_x, SW2; 50 V on BTSTx/HIDRVx; ROC 0-40 V; ACOV default 32.25 V minimum rising (ACOV_ADJ = 10b) | DS §6.1 p.8, §6.3 p.9, EC p.17, REG0x16 p.76 |
| M3 2S profile | **P** | CV 8.400 V at -0.5/+0.6 % (0-85 °C), no external divider; trickle, pre-charge, CC, CV, termination | DS EC p.10; §7.3.5 pp.30-32 |
| M4 ≥ 3.1 A | **P / C** | CHARGE_CURRENT 0-16.32 A, 8 mA step; loss about 1.4 W at 3.2 A, 8.4 V (section 11) | DS REG0x02 p.63; Fig 6-3 p.22 |
| M5 hard inhibit pin | **P** | ILIM_HIZ < 0.4 V enters HIZ (converter off) from POR; exit needs the pin > 0.8 V **and** EN_HIZ = 0, so no HIZ-related register can override a LOW pin. Whether HIZ takes precedence over PTM (EN_PTM = 1, Q1 and Q4 on) is not stated (§7.3.14 does not mention PTM): bench B16 | DS pin table p.6; EC p.20; §7.3.14 p.40; §7.4.3 p.52 |
| M6 fail-safe default | **P** | CHARGE_CURRENT 0 mA, EN_AUTO_CHG 0, CHRG_INHIBIT 0 at POR; no non-volatile memory; ILIM_HIZ held LOW by a REGN-biased hold-down (section 5.3) | DS Table 7-2 p.31; REG0x02 p.63; REG0x17 p.77 |
| M7 hardware ceiling | **c** | ILIM_HIZ divider sets IINDPM = (V − 1 V)/(40 × RAC), read continuously; defeatable by EN_EXTILIM = 0 at **two** addresses (REG0x32 b7, REG0x80 b4), by a pin voltage above VILIM_ENZ (4.1 V typ / 4.2 V max rising), and probably by EN_IIN_DPM = 0 (REG0x00 b1, POR 1), which disables "the input current limit function" as a whole; IIN_DPM_AUTO_DISABLE = 1 (REG0x01 b4, POR 0) clears EN_IIN_DPM automatically when CELL_BATPRES goes LOW. Whether EN_IIN_DPM = 0 also removes the pin limit is not stated: UNVERIFIED, bench B15 | DS pin table p.6; EC p.12, p.20; §7.3.12-7.3.13 p.39; REG0x00 p.59; REG0x01 p.61; REG0x32 p.100; REG0x80 p.121 |
| M8 runtime threshold | **P** range / **B** draw | VINDPM 3.2-27.0 V, 20 mV step, ±1 % at 18.000 V; "charge current drops accordingly towards zero" below VINDPM. Draw: IQ_VAC 2.50 mA **typical only** (no maximum), switching at zero load, VIN 28 V, VBAT 12.6 V (3S), EN_OOA = 0; the gate-drive part depends on the external FETs (§7.3.3 p.29), so the CCB value is bench B1 | DS REG0x08 p.66; EC p.12; §7.3.21 p.42; EC IQ_VAC p.14 |
| M9 no cold restart | **c** | Threshold crossing: VINDPM loop, no restart (the 50 ms deglitch, 100 ms qualification and 226 ms start belong to power-up only, DS §7.3.1 p.27). Inhibit exit: HIZ and FRC_CONV_OFF state "converter resumes switching"; soft-start re-run and exit latency unpublished | DS §7.3.1 p.27, §7.3.4 p.30, §7.3.14 p.40 |
| M10 host interface | **c** | I2C 100 kHz-1 MHz; VIH 0.8 V min, VIL 0.42 V max, "1.2 V-5 V VDD pull-up"; SDA/SCL abs max 5.5 V; behaviour when unpowered unpublished | DS §7.5 p.52; EC p.19-20; §6.1 p.8 |
| M11 charge-current telemetry | **P** | ADC_IBAT, 6/12/24 ms per channel | DS §7.3.22 p.42-43; REG0x3B p.110 |
| M12 runtime current control | **P** | IIN_HOST 400-8200 mA, 25 mA step; CHARGE_CURRENT 8 mA step; both runtime-writable | DS REG0x06 p.65; REG0x02 p.63 |
| M13 lifecycle | **P** | Active, Production | DS addendum p.138 |

No must-have fails. The conditional passes concern M7 (register- and pin-voltage-defeatable ceiling), M9 (exit latency) and
M10 (unpowered SDA/SCL behaviour). The BQ25798 M7 is also a conditional pass for the same class of register defeat
(EN_EXTILIM, dossier_BQ25798.md M7), so the two parts carry the same M7 grade.

---

## 4. Requirement status (EVAL section 1.1 requirements, EVAL section 1.2 layout)

| Req | BQ25773 on the CCB | Basis |
|---|---|---|
| HR1 regen | **U** (B: exit latency, warm response, burst entry through pre-charge) / input power **C** | Input at the threshold ≥ 23.7 W at the worst corners (section 11.3), charge-limited as for the BQ25798; warm response unpublished, and a burst that starts from a drained VCHG passes through pre-charge and the 5 ms tTRANS_CHG (section 8.3) |
| HR2 FC | **P** charger / **sys** | VINDPM 13.5-15 V, IIN_HOST 0.900 A, FC hardware ceiling 0.76-1.24 A (section 7); purge handling is system-level |
| HR3 loop | **C** | Interlock core (H1, H2, C7) unchanged; VINDPM ≥ 13.5 V blocks draw from a passthrough bus (≈ 7-8 V); REG0x30 (EN_PTM, SYSOVP_MAX) is never written in the recommended build |
| HR4 runaway | **C** regen / **C, weaker than the BQ25798** FC | ILIM_HIZ ceiling from a 2.5 V reference divider, continuous: regen 1.30-1.79 A, FC 0.76-1.24 A; never-write list EN_EXTILIM at two addresses, EN_IIN_DPM = 0 and IIN_DPM_AUTO_DISABLE = 1 (section 7.2); the reference keeps the pin below VILIM_EN under any single divider open; the eFuse bounds single faults. The FC upper corner plus aux (1.39 A) exceeds the 1.20 A firmware arm drop and the 1.247 A H-20 P_MAX; the BQ25798 bound is 1.15 A after a POR, 1.70-1.76 A after an IINDPM loss if ILIM_HIZ is sampled once (S1-B6; section 11.4) |
| HR5 fail-safe | **P** POR / **C** hold-down / **B** watchdog | No charge out of POR and no NVM (P); ILIM_HIZ hold-down from REGN for the hung-Teensy and dead-I2C cases after configuration (C by design); charger watchdog 4-7 s (B7) (section 5) |
| H1 ground/sense | **P** | Section 3, M1 |
| H2 inhibit | **P** mechanism / **B** latency | ILIM_HIZ HIZ (entry latency unpublished); FRC_CONV_OFF with a 1 µs falling-edge deglitch only in the optional fast path, which the recommended build omits (section 9.3); converter-off propagation unpublished |
| H3 fail-safe | **P / C / B** | As HR5 |
| H4 threshold | **P** range / **B** warm | ±1 % at 18 V; ±3 % at 4.48 V is the only other tabulated point; FC setting accuracy B |
| H5 FC | **C** typical / **F** worst case at the present ceiling | 1.60 A at 8.4 V at the typical IIN; 1.35 A at the worst low corner (section 11.4); no ceiling position meets both H5 at the low corner and the 1.20 A arm drop at the high corner |
| H6 ratings | **P** | 45 V abs max; ACOV 33 V default |
| H7 D-BT-SQ | **B** | Not battery-powered unless VCHG > VBAT_UVLOZ (3.5-4.25 V, DS p.16); CHARGE_CURRENT reset on adapter removal (REG0x02 p.63). Between bursts VCHG drains behind D-BT-SQ; below VSYS_MIN the next burst starts in pre-charge (LDO mode) and needs tTRANS_CHG 5 ms to reach fast charge (section 8.3). A keep-alive, BATFETOFF_HIZ = 1 or EN_LDO = 0 is a candidate remedy; none is proven |
| H8 inrush | **C** | 0.89 A with 0.15 A aux on the CCB input bank (section 7.4) |
| H9 I2C/logic | **B** | Unpowered SDA/SCL back-power unpublished |
| H10 thermal | **C** loss / **B** layout | 1.4 W at 3.2 A, 8.4 V; four layers minimum is a CCB choice (the DS asks for a multi-layer PCB with at least one ground layer, Table 10-1 rule 1 p.132) |
| H11 stock | **P** | TI store 15 695 units of BQ25773REER, 2026-11-10 |
| H12 telemetry | **P** / **B** IBAT accuracy | ADC_IBAT LSB and range in the register map; no ADC_IBAT accuracy row in DS EC p.15 |

---

## 5. Hard inhibit and fail-safe

### 5.1 Inhibit mechanisms

| Mechanism | Type | POR state | Default with the Teensy absent | Exit condition and what it re-runs | Latency (published) | Source |
|---|---|---|---|---|---|---|
| ILIM_HIZ < 0.4 V (VHIZ_HIGH 0.4 min / 0.5 typ, falling) | Pin | Follows the CCB bias | HIZ (hold-down ON from REGN, section 5.3) | Pin > 0.8 V max (VHIZ_LOW 0.7 typ / 0.8 max) and EN_HIZ = 0; "converter resumes switching". Soft-start re-run, VBUS re-qualification and exit latency: not stated | None | DS p.6, p.20, §7.3.14 p.40 |
| EN_HIZ (REG0x35 b7) | Register | 0 | 0 | Same as above | None | DS p.104 |
| FRC_CONV_OFF with the independent comparator (optional fast path only, section 9.3) | Pin (CMPIN_TR) gated by a register | FRC_CONV_OFF = 0 (disabled); CMP_EN = 1 | Inactive until configured | CMPOUT returns HIGH: fault bit cleared, "converter resumes switching automatically". The CMP_DEG deglitch applies to the falling (trip) edge only; no exit deglitch is stated. Soft-start: not stated. FRC_CONV_OFF also pulls CHRG_OK LOW for at least 256 µs | Trip deglitch 1 µs (CMP_DEG = 00b); turn-off propagation after the deglitch not stated | DS §7.3.4 p.30; REG0x30 p.96; §7.3.10 p.38 |
| CHRG_INHIBIT (REG0x00 b0) | Register | 0 (charge allowed) | - | Toggle restarts the safety timer | None | DS p.60, §7.3.5.4 p.33 |
| CHARGE_CURRENT = 0 | Register | 0 mA | 0 mA | Host write | - | DS p.63 |
| CELL_BATPRES < 14.7 % of REGN for 1 ms | Pin | Strapped 40 % | - | Resets CHARGE_CURRENT and EN_AUTO_CHG once; charging needs a new CHARGE_CURRENT write. If LOW at start-up, the "battery removal" row loads SYSOVP 27 V. With IIN_DPM_AUTO_DISABLE = 1 the same event also clears EN_IIN_DPM (input current limit off); the POR value 0 must be kept | 1 ms deglitch | DS §7.3.13 p.39, Table 7-6 p.39; REG0x01 p.61 |
| Charger watchdog | Timer | 175 s | Expires: CHARGE_CURRENT → 0 | Host write | 5 s setting (5.5 s typ, 4-7 s; the register text says "5 sec") | DS §7.3.26.1 p.47; §6.6 p.21; REG0x01 p.61 |

**Latched converter-off states.** These states are not inhibits, but each needs host action before switching resumes, so
each bears on HR1 regen availability after a fast transient:

| State | Trigger | Clear condition | Source |
|---|---|---|---|
| OCP_SW1X | RAC voltage above 300 mV or 450 mV (OCP_SW1X_HIGH_RANGE, POR 1 = 450 mV) for one switching cycle | Toggle EN_HIZ 0 → 1 → 0 | DS REG0x32 p.100 |
| OCP_SW2 | Q4 V_DS above 150 mV or 260 mV (OCP_SW2_HIGH_RANGE, POR 1 = 260 mV) for one switching cycle | Toggle EN_HIZ 0 → 1 → 0 | DS REG0x32 p.100 |
| SYSOVP | VSYS above the CELL-strap threshold (2S 12 V) | Write FAULT_SYSOVP = 0, or remove and re-apply the adapter | DS §7.3.26.4 p.48 |
| VSYS_UVP | VSYS below 2.4 V: 7 failed hiccup restarts in 90 s, or at once with VSYS_UVP_NO_HICCUP = 1 | Write FAULT_VSYS_UVP = 0 | DS §7.3.26.12 p.50 |

Firmware recovery: after any CHRG_OK fall that is not a commanded inhibit, read the FAULT_* bits, clear the latched one and
toggle EN_HIZ. Bench B17 checks that a regen step at 21.5 V and 1.79 A input does not trip OCP_SW1X with the chosen RAC and
FETs (450 mV across 10 mΩ corresponds to 45 A, so a trip is expected only on a fault, but the FET V_DS term of OCP_SW2 depends
on the selected Q4).

Paths an inhibit does not cover, all host-enabled and OFF at POR: EN_PTM (REG0x30 b2, passes VBUS straight to VSYS,
DS §7.4.3 p.52); OTG, VAP and FRS (all need the EN_OTG pin HIGH, DS Table 7-5 p.37-38; EN_OTG is grounded on the CCB);
EN_LEARN (REG0x00 b5). The never-write list is: EN_PTM = 1, EN_EXTILIM = 0 (REG0x32 b7 and REG0x80 b4), EN_IIN_DPM = 0
(REG0x00 b1), IIN_DPM_AUTO_DISABLE = 1 (REG0x01 b4), DETECT_VINDPM = 1, SYSOVP_MAX = 1 and ACOV_ADJ = 00b. Firmware reads
back each after every configuration burst. In the recommended build REG0x30 (EN_PTM, SYSOVP_MAX, CMP_POL, FRC_CONV_OFF) is
never written and stays at its POR value 01h; section 9.3 gives the hazard of writing it.

### 5.2 What an inhibit stops

In HIZ "converter shuts off and BATFET is turned on to supplement system from battery" (DS §7.3.14 p.40). The BATFET
conducts BAT → SYS only; BAT is VCHG behind D-BT-SQ, so an inhibit cannot move charge into the pack. BATFETOFF_HIZ = 1
(REG0x34 b1, DS p.103) also turns Q5 off in HIZ. Pre-charge and trickle are converter-sourced and stop with the converter.

### 5.3 Fail-safe construction on the CCB

1. **Teensy unpowered or in reset.** The RT1987 EN pull-downs open D-BC-FC and D-BC-RG, so VCHG-IN is unpowered; with
   VCHG below VBAT_UVLO the IC is off (DS §7.3.1 p.27). Independently, the ILIM_HIZ hold-down NMOS Q_H has its gate pulled
   up to REGN by R_H; Q_H holds ILIM_HIZ LOW whenever REGN exists and PERMIT is not actively HIGH. PERMIT HIGH turns the
   release transistor Q_R on, which pulls Q_H's gate LOW. A dead Teensy, an open MPPTD pad or an unpowered logic stage leaves
   HIZ.
2. **Teensy hung with PERMIT latched HIGH.** The charger watchdog, set to WDTMR_ADJ = 01b after every POR, zeroes
   CHARGE_CURRENT within 4-7 s. The MCU-independent interlock (H1, H2, C7, OVN) keeps working. Exposure: at most 7 s of
   regulated charge at the last setting, never a loop.
3. **I2C dead.** No CHARGE_* writes: the watchdog expires as in item 2. The IC releases a stuck bus after 1.5-2.5 s
   (DS §6.6 p.21).
4. **Charger POR.** CHARGE_CURRENT 0, EN_AUTO_CHG 0, IIN_HOST 5 A, VINDPM 3.2 V, FRC_CONV_OFF 0, EN_EXTILIM 1 (DS
   pp.63-66, p.77, p.96, p.100). The IC does not charge. The only active current limit is the ILIM_HIZ ceiling (section 7).
5. **Input loss with the IC kept alive from VCHG.** If VCHG stays above VBAT_UVLO the IC remains powered and keeps its
   registers, but STAT_AC falling resets CHARGE_CURRENT to 0 and IIN_HOST to 5 A (DS REG0x02 p.63; §7.3.12 p.39). The next
   input return does not charge until the host writes CHARGE_CURRENT.

**HR5 status: P for POR and NVM (item 4), C by design for the hold-down (items 1-3), B for the charger watchdog (B7).** The
POR property covers the case where the charger has not yet been configured. After configuration, with CHARGE_CURRENT
non-zero, a hung Teensy or a dead I2C bus is covered by the hold-down network and the watchdog, as for the BQ25798 on the
same CCB (HR5 C by design, dossier_BQ25798.md section 5.2). The construction needs no part beyond the S6 adders of
section 9.

---

## 6. Input-voltage regulation and POR behaviour

| Item | Value | Source |
|---|---|---|
| Register | VINDPM, REG0x08/0x09 bits 12:2, two-byte write, LSB first | DS p.66; §7.5.1.9 p.56 ([R2-773]) |
| Range, step | 3200-27000 mV, 20 mV; values outside the range clamp | DS p.66 |
| Accuracy | ±1 % at 18.000 V; ±3 % at 4.480 V; no other point tabulated | DS EC p.12 |
| POR value | 3.200 V (0x00A0) | DS p.66, §7.3.12 p.39 |
| Reset sources | POR and REG_RESET only ("Reset by: REG_RESET"); not the watchdog (watchdog list, DS §7.3.26.1 p.47); overwritten by DETECT_VINDPM (VBUS − 1.28 V) only on a host write of that bit | DS p.66, p.104, §7.3.12 p.39 |
| Autonomous charging at POR | None: CHARGE_CURRENT = 0, EN_AUTO_CHG = 0 | DS Table 7-2 p.31 |
| Draw just below the threshold | Charge current regulated toward zero; VSYS unloaded; IQ_VAC 2.50 mA typical, no maximum (VIN 28 V, VBAT 12.6 V 3S, EN_OOA = 0, switching at zero load; the gate-drive part depends on the FETs); IQ_HIZ 1.00 mA typ / 1.15 mA max (system powered by battery). Status P (typical) / B (CCB value, bench B1) | DS §7.3.21 p.42; §7.3.3 p.29; EC p.13-14 |

**Settings for this board.**

| Mode | VINDPM | Word | Band | Margin |
|---|---|---|---|---|
| Regen | 19.000 V | 950 counts = 0x3B6 → 0x0ED8 | 18.81-19.19 V (±1 %) | 0.51 V over the TPS61288 HW OVP minimum 18.3 V; 2.21 V under the 21.4 V clamp ([R2-773] H4a) |
| Regen, above boost OVP | 19.800 V | 990 = 0x3DE → 0x0F78 | 19.60-20.00 V | 0.10 V over the TPS61288 OVP maximum 19.5 V |
| FC | 13.500 V | 675 = 0x2A3 → 0x0A8C | 13.10-13.91 V at an assumed ±3 % | 1.69 V under the 15.6 V loaded bus; ±3 % extrapolated from the 4.48 V row, bench B1 |

A charger POR lands at VINDPM 3.2 V, which is below the pack voltage (CRIT S16 = 0). Because CHARGE_CURRENT is 0 at the same
instant, the low threshold cannot move charge until the host writes it; the host writes VINDPM first and reads it back
before any CHARGE_CURRENT write.

---

## 7. Hardware input-current ceiling after POR (HR4)

### 7.1 Pin law and accuracy

V(ILIM_HIZ) = 1 V + 40 × IINDPM × RAC, RAC = 10 mΩ, so IINDPM = (V − 1 V) / 0.4 Ω (DS pin table p.6). The pin range is
1.15-4.0 V (DS EC p.12). The effective limit is the lower of the pin and IIN_HOST while EN_EXTILIM = 1 (DS §7.3.12 p.39).
The pin voltage is read continuously (DS pin table p.6). DS EC p.12 tabulates the pin accuracy as:

| V(ILIM_HIZ) | Min | Typ | Max |
|---|---|---|---|
| 1.2 V | 300 mA | 500 mA | 700 mA |
| 1.4 V | 800 mA | 1000 mA | 1200 mA |
| 2.2 V | 2800 mA | 3000 mA | 3200 mA |
| 3.0 V | 4800 mA | 5000 mA | 5200 mA |

The error is ±200 mA absolute at every tabulated point. This dossier applies ±200 mA between the points.

### 7.2 Hazards specific to this pin

1. **Register defeat.** EN_EXTILIM = 0 at REG0x32 b7 (DS p.100) or at the mirror REG0x80 b4 (DS p.121) removes the pin
   ceiling. In addition, EN_IIN_DPM = 0 (REG0x00 b1, POR 1) disables "the input current limit function" (DS §7.3.12
   p.39, REG0x00 p.59). Section 7.3.12 describes that function as one limit set by the lower of IIN_DPM and the pin, so the
   pin limit is most probably lost too; the datasheet does not say so explicitly (UNVERIFIED, bench B15;
   TODO(verify: SLUSEK7 / TI E2E)). IIN_DPM_AUTO_DISABLE = 1 (REG0x01 b4, POR 0) makes the charger clear EN_IIN_DPM by itself
   when CELL_BATPRES goes LOW (DS §7.3.13 p.39, REG0x01 p.61). All four bits go on the never-write list with read-back.
2. **Pin-voltage defeat.** Above VILIM_ENZ (4.1 V typ, 4.2 V max, rising) "the external current limit function is disabled
   neglecting EN_EXTILIM bit status"; it re-enables below VILIM_EN (3.9 V min, 4.0 V typ) (DS pin table p.6; EC p.20). With a
   divider from REGN (4.80-5.10 V, DS p.12), an open bottom resistor pulls the pin to REGN and removes the IC ceiling; the
   limit then falls back to IIN_HOST, which is 5 A after every POR, and only the eFuse (2.0-2.5 A, WD B.4) bounds the input.
   The CCB biases the divider from a 2.5 V shunt reference fed from REGN. The pin then cannot exceed 2.5 V with any divider
   resistor open, so the IC ceiling stays active at no more than (2.5 − 1) / 0.4 = 3.75 A. A failed-open reference raises
   the node toward REGN through its bias resistor; the regen divider then gives at most 5.10 × 0.648 = 3.30 V < 3.9 V, a
   5.75 A ceiling that is still active. In both single faults the eFuse bounds the current, as it does for every candidate;
   the reference prevents the IC ceiling from switching off. Splitting R_bot into two parallel 36.5 kΩ parts keeps a single
   open at 2.5 × 36.5 / 46.5 = 1.96 V, a 2.41 A ceiling (optional). Reference part and tolerance: TODO(verify: TLV431 or
   equivalent datasheet); ±0.5 % assumed below.
3. **Pass-through mode.** EN_PTM = 1 (REG0x30 b2) turns Q1 and Q4 on and passes VBUS directly to VSYS (DS §7.4.3 p.52).
   That path bypasses converter regulation; whether the IINDPM loop or a LOW ILIM_HIZ still acts in PTM is not stated. Until
   bench B16 shows that ILIM_HIZ LOW ends PTM, the HR4 bound for a REG0x30 corruption is the eFuse (2.0-2.5 A), which is above
   the regen ceiling and the 1.4 A OC_FC latch. The recommended build never writes REG0x30 (section 9.3).

### 7.3 Mode-switched divider (regen and FC)

Reference 2.5 V, R_top 10.0 kΩ, R_bot 18.4 kΩ (regen). FC mode adds R_FC = 41.2 kΩ in parallel with R_bot through an NMOS
keyed to FCC_net (EVAL 3.4 mode switching). All resistors 0.1 %.

| Mode | R_bot,eff | V(ILIM_HIZ) nominal | IINDPM nominal | Divider and reference error | Pin leakage (±1 µA × R_th) | Pin error (DS) | Hardware ceiling band |
|---|---|---|---|---|---|---|---|
| Regen | 18.4 kΩ | 2.5 × 18.4 / 28.4 = 1.6197 V | (1.6197 − 1) / 0.4 = **1.549 A** | ±0.7 % × 1.62 V = ±11 mV → ±28 mA | 6.48 kΩ → ±6.5 mV → ±16 mA | ±200 mA | **1.30-1.79 A** |
| FC | 18.4 ∥ 41.2 = 12.72 kΩ | 2.5 × 12.72 / 22.72 = 1.3996 V | **0.999 A** | ±0.7 % × 1.40 V = ±10 mV → ±25 mA | 5.60 kΩ → ±5.6 mV → ±14 mA | ±200 mA | **0.76-1.24 A** |

The ±0.7 % term covers the reference (±0.5 % assumed) and the ratio error of the 0.1 % resistors; it leaves no room for the
pin leakage (ILEAK_ILIM ±1 µA, DS EC p.12), which is therefore carried as a separate term. No filter capacitor is placed on ILIM_HIZ: the 1 µF in DS Fig 8-1
p.123 decouples REGN, not the pin. A capacitor on the pin would slow the inhibit exit by R_th × C.

**Comparison with a REGN-ratiometric divider (no reference).** A divider ratio of 0.32394 gives 1.6197 V at REGN 5.00 V. With
REGN at 4.80-5.10 V (DS EC p.12) the pin is 1.5549-1.6521 V, that is 1.387-1.630 A before the pin, divider and leakage errors.
With those errors the regen band becomes about 1.14-1.87 A (1.16-1.86 A without the leakage term). The low corner,
1.14 A × 18.81 V = 21.5 W, misses the HR1 23 W pass condition, and the high corner exceeds the reference-biased 1.79 A. The
reference is therefore required, not optional.

### 7.4 Input capacitance and inrush on the RT1987-ramped node (H8)

Design input bank (nominal values; the budget uses nominal capacitance, which is the inrush worst case):

| Location | Parts | Nominal |
|---|---|---|
| Before RAC_A and RAC_B | 2 × 10 µF, 50 V, 1206, X7R (one per phase) | 20.0 µF |
| After each RAC, at the half bridge | 1 × 10 µF + 10 nF + 1 nF per phase (DS §8.2.2.4 p.126 maximum) | 20.0 µF |
| Damping RC (DS §8.2.2.1 p.124) | 1 µF behind 2.2 Ω | 1.0 µF |
| VBUS pin filter | 0.47 µF behind 1 Ω | 0.47 µF |
| ACP/ACN filters | 4 × 33 nF + 2 × 100 nF | 0.33 µF |
| **CCB total** | | **41.8 µF** |
| Motherboard C-D8 + C-D10 | SPEC section 6 | 20.0 µF |

Inrush = 61.8 µF × 12 mA/µF = **0.74 A**; with 0.15 A aux = **0.89 A ≤ 1.0 A** (SPEC section 6 model). Capacitance margin:
the budget allows (1.0 − 0.15) / 0.012 = 70.8 µF, so the design uses 87 % of it (13 % margin; CRIT S15 = 2). TI's minimum
effective input capacitance is 4 µF without OTG at 20 V / 100 W (DS Table 8-2 p.126). Forty microfarads of nominal MLCC
gives 4 µF even at TI's quoted 10 % DC-bias retention for 0603 35 V parts; 1206 50 V parts retain more (UNVERIFIED). Bench
B6a measures it; below 10 µF effective, MODE goes to the slow-compensation code (DS §7.3.2 p.28).

The converter does not switch during the 1.3-1.75 ms RT1987 ramp: it starts about 226 ms after VBUS > VVBUS_CONVEN (DS
§7.3.1 p.27). The 20 mA, 100 ms qualification sink adds 0.02 A. VSYS capacitance (≥ 50 µF effective) is charged by the
converter after start-up, limited by the ILIM ceiling and, while VSYS < 2.4 V, by the internal 0.3 A clamp at VBUS > 14.4 V
(DS §7.3.26.12 p.50).

---

## 8. Warm response and inhibit-exit timing (EVAL section 3.2)

### 8.1 What the datasheet gives

| Quantity needed | What DS SLUSEK7 states | Status |
|---|---|---|
| VINDPM loop bandwidth or step response | Not given. MODE selects normal or slow compensation only (Table 7-1 p.28) | B |
| Soft-start | SSSTEP_DAC = 8 mA "During Charge Enable"; step period not given (EC p.19). TSHUT recovery is stated to use soft-start (§7.3.26.15 p.51); HIZ and FRC_CONV_OFF exits are not | B |
| HIZ exit latency | "converter resumes switching"; no time | B |
| FRC_CONV_OFF exit latency | "converter resumes switching automatically"; no exit deglitch is defined (CMP_DEG applies to the falling edge only) | B |
| Re-qualification on exit | Not stated. The 50 ms deglitch, 100 ms VBUS qualification and 226 ms start are listed under the power-up sequence only (§7.3.1 p.27); HIZ keeps REGN on (REG0x35 p.104) | B |
| Deglitch on threshold crossing | The 1 ms VINDPM-active deglitch gates status, termination and the timer half-rate only (§7.3.5.3-7.3.5.4 p.33) | P (no converter gating) |
| Hard-stop latency | FRC_CONV_OFF trip deglitch 1 µs; turn-off propagation not given; ILIM_HIZ entry latency not given | B |

### 8.2 Derived bench limits

The requirement is τ_warm ≤ 4 ms (10-90 % ≤ 9 ms; ≤ 2 ms with board-only capacitance) for a step from Vth − 0.5 V to
Vth + 1 V, and converter-off within about 115 µs of an H1 trip (EVAL 2.5, 3.2).

1. **Soft-start step period.** If an inhibit exit re-runs an 8 mA-step soft-start toward a 3.2 A setting, reaching 63 %
   (2.02 A) needs 252 steps. τ ≤ 4 ms then requires a step period ≤ 15.9 µs; the 2 ms board-only case requires ≤ 7.9 µs.
   A longer period fails HR1 in the per-burst inhibit scheme.
2. **Hard-stop.** The allowance shrinks with input current: 117 µs at 1.72 A (EVAL 2.5 table). At the 1.79 A upper regen
   corner of section 7.3 the constant 0.757 V margin of [D798] section 7.2 gives 0.757 V / 4.475 V/ms - 59 µs = 110 µs
   (302.8 µC / 1.79 A - 59 µs = 110.2 µs). The bench pass value is therefore ≤ 110 µs, with a margin under 1 µs, from the H1 edge to input current < 10 % for the ILIM_HIZ pull-down (and for the FRC_CONV_OFF path if
   the optional fast path is built).
3. **Alternative without per-burst inhibit cycling.** VINDPM at 19.0 V already holds input current near zero while V-MOT
   sits at the 16 V bus level (§7.3.21 p.42). If B4 shows the inhibit exit is slow but the VINDPM loop is fast, the H1 trip
   can be moved from "inhibit" to "fault backstop only". That change touches the HR3 loop argument and needs an operator
   ruling; it is a design question, not a part failure.

### 8.3 Burst entry from a drained VCHG (D-BT-SQ)

The charger's battery node is VCHG, which reaches the pack through D-BT-SQ; D-BT-SQ blocks VBT → VCHG (WD B.5). Between
bursts VCHG therefore drains:

- In cruise HIZ the BATFET is on "to supplement system from battery" while BATFETOFF_HIZ = 0 (POR) (DS §7.3.14 p.40).
- REGN takes the lower of VBUS and VSYS when both exceed 6 V (DS §7.3.3 p.28), so the REGN loads, including the CCB's own
  ILIM divider (2.5 V across 28.4 kΩ, 88 µA from the reference), come from VSYS = VCHG.
- IQ_HIZ is 1.00 mA typ / 1.15 mA max with the system powered by the battery (DS EC p.13).

With the 9 × 10 µF VSYS/VCHG bank of section 12.3, the divider alone discharges the node at about 1 V/s and the divider plus
IQ_HIZ at about 12 V/s. From a 7.4 V pack the node reaches the VBAT_PRECHG falling threshold (VSYS_MIN 6.6 V for 2S minus
−50 to 300 mV, that is 6.30-6.65 V, DS Table 7-6 p.39, EC p.17) in about 0.06-1.1 s (calculation, nominal capacitance;
0.75 V at 12 V/s to 1.10 V at 1 V/s). The next burst then starts
in pre-charge: LDO mode with EN_LDO = 1 at POR, current limited to min(IPRECHG 384 mA POR, CHARGE_CURRENT) (DS Table 7-2
p.31, §7.3.5.2 p.31-32, §7.3.26.8 p.49). The transition from the pre-charge level to the fast-charge level takes
tTRANS_CHG = 5 ms (DS §6.6 p.21, NOM column only, no MIN or MAX, shape unpublished). As a linear ramp from IPRECHG
0.384 A to the 3.200 A setting, 63 % is reached at about 2.9 ms and 90 % at about 4.4 ms, inside the τ_warm ≤ 4 ms and
10-90 % ≤ 9 ms budgets; as a delay it fails by 1.0 ms; every reading except an exponential one fails the ≤ 2 ms
board-only case. The status is B on gate B4. It adds to the IC-independent RT1987 D-BT-SQ UVLO drop-out (tD_ON 8 ms + tON about 1.9 ms) that
dossier_BQ25798.md section 8 records for every candidate.

The WD B.5 keep-alive holds VCHG at only 3.63-4.46 V, which is below VSYS_MIN, so it does not remove the pre-charge entry for
this IC. Three remedies are candidates; none is proven, and each is counted in S6 where it adds parts:

1. BATFETOFF_HIZ = 1 (REG0x34 b1, DS p.103): Q5 stays off in HIZ, so VCHG is loaded only by leakage. Cost: VSYS then decays
   toward the REGN switch-over point and is re-charged at every exit; the transient needs benching. No adder.
2. EN_LDO = 0 (REG0x00): the BATFET is fully on or off and IPRECHG is not effective (DS §7.3.5.2 p.32, §7.3.26.8 p.49).
   Whether tTRANS_CHG still applies is not stated: TODO(verify: SLUSEK7). No adder.
3. A VBT-derived keep-alive that holds VCHG above about 6.8 V. It bridges D-BT-SQ through a resistor and touches R6
   finding 2 (D-BT-SQ short). About 3 adders.

Bench B4 gains the sub-case "burst after more than 1 s of cruise HIZ, CHRG_STAT logged", with the charge-current
waveform logged to extract t63 and t10-90.

**S1 evidence: U for the exit path (score 1); the nominal 5 ms tTRANS_CHG (shape unpublished, B) on burst entry from a drained VCHG prevents a
score of 2 until one remedy is benched. S5 evidence for the recommended build (no fast path): U, because the ILIM_HIZ entry
latency is unpublished (score 1). With the optional fast path the 1 µs trip deglitch is P (score 2), at the S6 cost given in
section 9.2.**

---

## 9. Interlock hardware around the IC, against the BQ25798 design

### 9.1 System core (not counted, identical for every candidate)

H1 V-MOT/VBUS comparator, H2 FC permit with BT_ACT, C7 qualifier, OVN pack-OV term (R6 finding 1), eFuse on VCHG-IN,
heartbeat monostables, FCC/RGN level sensing, MCU watchdog (CRIT section 3.3).

### 9.2 BQ25773-specific adders on the CCB

| # | Part | Function | Removes or adds versus the BQ25798 design (WD) |
|---|---|---|---|
| 1 | Q_H, NMOS on ILIM_HIZ | Hold-down: HIZ unless released | Same function as the BQ25798 ILIM_HIZ hold-down |
| 2 | R_H, Q_H gate pull-up to REGN | Fail-safe bias from the IC's own rail | Same |
| 3 | Q_R, release transistor driven by PERMIT | Release on PERMIT HIGH | Same |
| 4 | R_FC 41.2 kΩ | FC ceiling resistor | Same function as the third ILIM resistor |
| 5 | Q_FC, NMOS keyed to FCC_net | Mode switch | Same |
| 6 | U_REF, 2.5 V shunt reference | Ceiling accuracy and the VILIM_ENZ guard (section 7.2) | **Added** (BQ25798 has no ceiling-disable pin threshold in the WD design; UNVERIFIED for its silicon) |
| 7 | R_REF, reference bias from REGN | - | **Added** |
| 8, 9 | R_C1 10 kΩ series, R_C2 100 kΩ pull-down on CMPIN_TR | PERMIT into the on-chip comparator for the FRC_CONV_OFF fast path | **Added** (optional fast path) |
| - | /CE open-drain drive and REGN pull-ups | - | **Removed**: the BQ25773 has no /CE pin; ILIM_HIZ carries both the inhibit and the ceiling |
| - | `CHG_QUAL AND NOT P5` gates (1G04, 1G08) and the CHG_QUAL one-shot | BQ25798 input qualification with ILIM_HIZ released | **Removed if** the BQ25773 completes VBUS qualification while ILIM_HIZ is LOW. DS §7.3.1 p.27 does not condition qualification on HIZ, but does not state it either: B (bench B13) |
| (10-12) | Keep-alive from VBT holding VCHG above about 6.8 V | Avoids pre-charge entry on every burst (section 8.3) | **Contingent.** The WD B.5 keep-alive (3.63-4.46 V) is too low for this IC. Needed only if neither BATFETOFF_HIZ = 1 nor EN_LDO = 0 passes bench B4; about 3 parts |
| (13+) | Comparator from THERM into the inhibit chain | Battery-temperature qualification (section 2.4) | **Contingent.** The BQ25798 has a TS pin; the BQ25773 has none. Needed only if the operator requires battery-temperature qualification on the CCB |

**Count.** Recommended build: 7 adders (items 1-7), no fast path, REG0x30 never written. With the fast path: 9. With the
keep-alive: 10. The BQ25798 count on the CCB is 9 (minimal) to about 16 (single-fault parity) (dossier_BQ25798.md section 9,
S6 = 0). The BQ25773 saves parts if bench B13 passes, and adds the reference pair. **S6 = 1 (6-8 adders, recommended build
without the fast path or the keep-alive); S6 = 0 with either.** Evidence: P for the pin semantics, B for the
qualification-in-HIZ question and for the keep-alive need.

### 9.3 The on-chip comparator and H1

The independent comparator compares CMPIN_TR against an internal reference. The datasheet tabulates that threshold as
1.18/1.2/1.23 V for negative polarity (CMP_POL = 0b) only (DS EC p.19); for CMP_POL = 1, §7.3.4 p.30 and Fig 7-3 show a
1.2 V reference without a tolerance (TODO(verify: SLUSEK7)). H1 is a ratio comparator (V-MOT against 1.067 × VBUS, EVAL 2.2)
whose threshold must track VBUS for the HR3 loop proof. The on-chip comparator therefore cannot replace H1. It can take the
H1/PERMIT output directly and turn the converter off within a 1 µs deglitch once FRC_CONV_OFF = 1 and CMP_POL = 1 are written
after every POR (DS REG0x30 p.96). R_C1/R_C2 must then place logic HIGH well above 1.23 V and logic LOW well below 1.18 V.
With CMP_POL = 1 there is no internal hysteresis (DS §7.3.4 p.30), which suits a logic-level input. EN_CMP_LATCH (REG0x00 b7)
can latch the trip until the host toggles the bit, a hardware form of the firmware trip latch. FRC_CONV_OFF also pulls
CHRG_OK LOW, so pin 6 reads "not OK" during every cruise inhibit; firmware must read CHRG_OK together with
FAULT_FRC_CONV_OFF (REG0x20 b2, DS p.83-84).

**Shared-byte hazard; the fast path is not in the recommended build.** FRC_CONV_OFF (b3) and CMP_POL (b6) share REG0x30
with EN_PTM (b2) and SYSOVP_MAX (b7) (DS REG0x30 p.96, reset 01h). The fast path turns REG0x30 from a register that keeps its
POR value into one that is written after every POR. A corrupted write can then enable PTM, in which VBUS passes to VSYS with
Q1 and Q4 on (DS §7.4.3 p.52), and can raise SYSOVP from the 2S 12 V threshold to 27 V (DS §7.3.26.4 p.48), which removes
the SYSOVP stop that would otherwise end a 16 V pass-through. Read-back detects either change only after the event, and
section 7.2 item 3 leaves the eFuse as the bound. If the operator wants the fast path, the conditions are: write REG0x30 as
one full constant (EVAL 1.3), read it back, and pass bench B16 (EN_PTM set with ILIM_HIZ held LOW and with FRC_CONV_OFF
active). The fast path also costs two adders (S6 1 → 0, −3.3 points) for the S5 gain (1 → 2, +2.3 points), so it lowers the
weighted score by about 1 point.

---

## 10. Telemetry and I2C

| Item | Value | Source |
|---|---|---|
| Address | 0x6B (0xD6 write / 0xD7 read); ManufacturerID 0x40 | DS §7.5 p.52 |
| Logic levels | VIH 0.8 V min, VIL 0.42 V max, pull-up 1.2-5 V; abs max 5.5 V; leakage ±1 µA | DS EC p.19-20; §6.1 p.8 |
| Speed | 100 kHz, 400 kHz, 1 MHz | DS §7.5.1 p.52 |
| Bus timeout | 1.5-2.5 s | DS §6.6 p.21 |
| Unpowered SDA/SCL | Not specified | U → bench B9 |
| ADC channels | VBUS (2 mV LSB, ±2 % at 28 V), IIN (0.5 mA LSB, −4/+2.5 % at 50 mV = 5 A), IBAT (register map; no EC accuracy row), VBAT/SRN (1 mV, −2/+1 % at 9 V), VSYS (2 mV, ±2 % at 9 V), PSYS, CMPIN_TR | DS EC p.15; §7.3.22 p.42-43 |
| Conversion time | 24 / 12 / 6 ms per channel at 15 / 14 / 13 bits; continuous mode cycles the enabled channels | DS REG0x3B p.110 |
| Rate for the EMS | IBAT + IIN + VBUS at 13 bits: 18 ms cycle (55 Hz per channel); IBAT alone: 167 Hz | Calculation |
| ADC validity | "only valid for DC states and not for transients" | DS §7.3.22 p.43 |
| ADC_EN | Cleared by the watchdog and by POR | DS §7.3.26.1 p.47 |
| Watchdog | 5 s setting (5.5 s typ, 4-7 s), 88 s, 175 s (POR), disabled; the register labels and the EC typical values differ | DS §6.6 p.21; REG0x01 p.61 |
| Status | CHRG_STAT (REG0x19), IN_VINDPM, IN_IIN_DPM, STAT_AC, FAULT_* | DS pp.78-86 |

The analog monitors IADPT (input) and IBAT (charge) are also available as pin voltages with published gain accuracy
(DS EC p.14): IADPT −6/+3 % at 20.48 mV (2.05 A at 10 mΩ) and −15/+6 % at 10.24 mV; IBAT −3/+7 % at 20.48 mV (4.1 A) and
−6/+13 % at 10.24 mV ([R2-773] H12 reading of the same table). A Teensy
ADC could read IADPT for a faster input-current term than the 6 ms ADC; that needs a spare Teensy analog pin, which the CCB pad
set does not provide.

---

## 11. Charge capability

### 11.1 Charge-current setting

| Setting | Counts × 8 mA | Bound used | Delivered band | Note |
|---|---|---|---|---|
| 3.104 A | 388 → word 0x0C20 | ±5 % (the 2048 mA row bounds the 3.1 A point; ±3 % at 4096 mA) | 2.95-3.26 A | Fails "≥ 3.1 A" at the low corner |
| **3.200 A** | 400 → 0x0C80 | ±5 % | **3.04-3.36 A** | Recommended; HR1 margin in section 11.3 |
| 3.264 A | 408 → 0x0CC0 | ±5 % | 3.10-3.43 A | Meets 3.1 A at every ICHG corner; exceeds the R6 finding 3 copper basis of 3.21 A. At an 8.4 V pack and the threshold floor the regen input ceiling binds instead (2.77 A, section 11.3), so this setting does not raise the delivered charge there |

Source: DS REG0x02 p.63; EC ICHRG_REG_ACC p.11 (0-85 °C, VBAT 7.4 V among the test points). The CCB battery-path copper and the
motherboard path (R6 finding 3) must be re-sized to 3.36 A for the recommended setting.

### 11.2 Efficiency

DS Fig 6-2 and 6-3 p.22 (RAC 10 mΩ, RSR 5 mΩ, 3.3 µH, 600 kHz CCM; VOUT is the system voltage, so the BATFET and RSR losses
are excluded) read, at 3 A output and VOUT 7.4 V: about 96.3 % at VIN 15 V and about 95.5 % at VIN 20 V (plot reading, ±0.5
percentage point). The BATFET (5 mΩ class) and RSR add 3.2² × 0.010 Ω = 0.10 W. This dossier uses η = 0.95 at 16-19 V input.

| Case | Output power | Loss at η 0.95 |
|---|---|---|
| 3.2 A at 8.4 V | 26.9 W | 1.42 W |
| 3.2 A at 7.4 V | 23.7 W | 1.25 W |

Both are below the 2 W limit (M4, H10). Gate-drive dissipation in the IC at 21 V, 600 kHz, single phase with about 20 nC of
switching gate charge: (21 − 5) V × 20 nC × 600 kHz = 0.19 W (DS §7.3.3 p.29 formula); with θJA 35.6 °C/W (DS p.9) the
junction rise is about 7 °C.

### 11.3 Regen input power at the threshold (HR1 ≥ 23 W)

Input power is the lower of the input-ceiling limit and the charge-current limit.

| Corner | Ceiling limit (VINDPM low edge 18.81 V) | Charge limit (ICHG low edge 3.04 A, η 0.95) | Input at the threshold |
|---|---|---|---|
| Pack 7.4 V, low corners | 1.32 A × 18.81 V = 24.8 W | 3.04 × 7.4 / 0.95 = 23.7 W | **23.7 W** |
| Pack 8.4 V, low corners | 24.8 W | 3.04 × 8.4 / 0.95 = 26.9 W | **24.8 W** |
| Nominal, pack 7.4 V | 1.549 × 19.0 = 29.4 W | 3.2 × 7.4 / 0.95 = 24.9 W | 24.9 W |

With the leakage term of section 7.3 the ceiling low corner is 1.30 A × 18.81 V = 24.5 W, so the charge limit still governs
at a 7.4 V pack; at 8.4 V the ceiling governs (24.5 W, 2.77 A delivered).

Delivered charge at an 8.4 V pack and the threshold floor: min(3.04 A ICHG, 1.30-1.32 A × 18.81 V × 0.95 / 8.4 V) =
2.77-2.81 A, 0.29-0.33 A below the 3.10 A BQ25798 image setting. A higher CHARGE_CURRENT setting does not close the gap,
because the ceiling binds. A guaranteed 3.1 A needs a regen ceiling minimum of 3.1 × 8.4 / (0.95 × 18.81) = 1.457 A; the
nominal setting is then 1.457 + 0.245 = 1.702 A (pin ±0.200, divider ±0.029, leakage ±0.016 A, section 7.3), and the
maximum 1.702 + 0.245 = 1.947 A, 13 % above the 1.72 A hard-stop row. The [EVAL] section 2.5 rows carry a constant charge,
Q = (t + 59 µs) × I = 302.7-303.8 µC; at 1.947 A the allowance is 302.8 µC / 1.947 A − 59 µs = 96.5 µs, below the
110 µs bench pass. The shortfall at an 8.4 V pack is therefore structural (C).

HR1 input condition: **C, ≥ 23.7 W at every corner** (23 W required; 18.9 W peak of the defining brake). The BQ25798 on the
CCB also reaches ≥ 23 W in every case (dossier_BQ25798.md section 7.3): the 2.50 A ICHG value of the 2026-11-05 image was a
register setting, not a silicon cap (ICHG spans 0.05-5 A). For both parts a setting above 3.1 A waits on the pack datasheet
(WD T-E-11, EVAL 8.1 item 6). Input power at the threshold is therefore not a differentiator.

### 11.4 FC mode within the 1.0 A bus budget (HR2, H5)

VBUS 15.6 V loaded, IIN_HOST 0.900 A (36 counts × 25 mA; accuracy 800-1000 mA at this setting, DS EC p.12), FC hardware
ceiling 0.76-1.24 A (section 7.3, with the leakage term). Effective input = min(IIN_HOST, ceiling).

| Corner | Input | Charge at 8.4 V (η 0.955) | Charge at 7.4 V |
|---|---|---|---|
| Low | min(0.80, 0.76) = 0.76 A | 0.76 × 15.6 × 0.955 / 8.4 = **1.35 A** | 1.53 A |
| Typical | 0.90 A | **1.60 A** | 1.81 A |
| High | min(1.00, 1.24) = 1.00 A | 1.77 A | 2.01 A |
| IIN_HOST lost (POR value 5 A) | ceiling ≤ 1.24 A; + 0.15 A aux = 1.39 A | - | - |

**Bound check after an IIN_HOST loss (HR4, FC).** The bus draw stays ≤ 1.00 A in operation. After an IIN_HOST loss with
CHARGE_CURRENT still set, it can reach 1.24 + 0.15 = 1.39 A. That value is 0.14 A above the 1.25 A governor, above the
1.247 A H-20 P_MAX bus equivalent (EVAL 1.1 HR2) and above the 1.20 A firmware raw-I_fc arm drop (EVAL 3.4). It is 0.01 A
below the 1.4 A OC_FC single-sample latch, a margin inside the INA253 zero-current floor uncertainty (about 0.1 A, EVAL 2.3).
The expected outcome is a firmware arm drop or an OC_FC latch while the stack runs above P_MAX; the eFuse (2.0-2.5 A) still bounds the charger input. The residual loop L-F bound of EVAL 2.3 (0.74-0.96 A with the BQ25798
designs) widens to 1.24 A with this part. The BQ25798 CCB bound after a POR is 1.15 A, 0.05 A below the arm drop
(dossier_BQ25798.md section 7.2 item 1); after an IINDPM loss it is 1.15 A only if ILIM_HIZ is re-sampled after
qualification, and 1.70-1.76 A if the pin is sampled once (P6, S1-B6). The FC hardware bound of the BQ25773 is therefore
worse than the baseline only if S1-B6 shows re-sampling.

**Trade-off between the ceiling position and H5.** H5 (≥ 1.5 A at 8.4 V) needs an input of 1.5 × 8.4 / (15.6 × 0.955) =
0.85 A at the low corner. The 1.20 A arm drop with 0.15 A aux allows at most 1.05 A at the high corner. The available window
is 0.20 A wide; the ceiling band is 0.48 A wide (±0.24 A). No divider setting meets both. Lowering the FC nominal so the high
corner plus aux stays at the arm drop gives a nominal of about 0.81 A and a low corner of about 0.57 A, which drops the
worst-case FC charge to about 1.01 A at 8.4 V. Keeping the present nominal holds H5 at the typical point (1.60 A) and misses
it by 0.15 A at the low corner (1.35 A), at the cost of the bound above. **H5: C typical, F worst case at the present
ceiling; HR4 (FC): C, weaker than the BQ25798.** The choice of ceiling position is an operator ruling. The governor rewrites
IIN_HOST at 50 Hz (two-byte write, about 0.4 ms at 100 kHz).

---

## 12. Layout, package, thermal and bill of materials

### 12.1 Layout difficulty

| Item | Value | Source |
|---|---|---|
| Hot loops | Two input loops (CBUS, RAC_x, Q1_x, Q2_x per phase) and one output loop (CSYS, Q3, Q4) | DS Table 10-1 rules 2, 4 p.132 |
| Switching frequency | 600 kHz setting (600 kHz typ, 540-660 kHz) or 800 kHz setting (770 kHz typ, 690-850 kHz); the register and Table 7-1 labels and the EC typical value differ for PWM_FREQ = 0 | DS EC p.19; REG0x01 p.62 |
| Minimum duty in the envelope | VSYS ≥ VSYS_MIN 6.6 V, so D ≥ 6.6 / 22.28 = 0.30 → on-time ≥ 493 ns at 600 kHz. Controller minimum on-time: not published, TODO(verify: SLUSEK7). Charging at 8.4 V from 22.28 V: D = 0.38, 628 ns | Calculation |
| Inductor | 3.3 µH as characterised (Table 8-1 recommends 2.2 µH at 600 kHz, 20 V); DCR 5-25 mΩ per phase; ripple at 22.28 V in, 8.4 V out, 3.3 µH, 600 kHz: 22.28 × 0.377 × 0.623 / (600 kHz × 3.3 µH) = 2.64 A p-p, so I_sat ≥ 3.36 + 1.32 = 4.7 A; choose ≥ 6 A | DS §8.2.2.3 p.125, Table 8-1 |
| FET ratings | Buck half bridges ≥ 30 V at a 20 V system, ≥ 40 V at 28 V; boost leg and BATFET ≥ 30 V; BATFET Ciss < 6 nF. For a 22.28 V clamp and 45 V IC rating, 40 V buck FETs are used here | DS Table 8-7 p.128; p.130 |
| PCB | The DS asks for a multi-layer PCB with at least one ground layer. Its EVM description is internally inconsistent: it names the "BQ2577xG EVM", calls it 6-layer and lists four layers. Four layers minimum is a CCB design choice | DS Table 10-1 rule 1 p.132 |
| Sense routing | Kelvin RAC_A, RAC_B, RSR; ACP/ACN RC filters at the IC | DS Table 10-1 rule 7; Fig 8-3 p.125 |
| Grounds | AGND plane tied to PGND at the exposed pad only | DS Table 10-1 rule 10 p.133 |

**CRIT S10 = 0** (buck-boost with external FETs, three hot loops).

### 12.2 Package

WQFN-36 REE0036A, 4.0 × 5.0 × 0.8 mm, **0.4 mm pitch** (32 × 0.4), one exposed pad 2.7 × 3.7 mm nominal (2.6-2.8 ×
3.6-3.8 mm) (DS package outline p.141). **CRIT S11 = 1** (QFN at ≤ 0.4 mm pitch). The screening provisional score of 2 assumed 0.5 mm and is corrected.

### 12.3 Area and bill of materials (power stage and support, excluding the system core)

| Group | Parts | Count | Rough unit cost (UNVERIFIED) |
|---|---|---|---|
| IC | BQ25773REER | 1 | USD 3.14 (TI page, basis unstated) |
| Switches | 6 × 40 V N-FET 3.3 × 3.3 mm (buck A/B, boost leg) + 1 × 30 V N-FET BATFET | 7 | USD 0.4-0.8 |
| Inductors | 3.3 µH, I_sat ≥ 6 A, shielded, about 6 × 6 mm | 2 | USD 0.8-1.5 |
| Sense resistors | 10 mΩ × 2, 5 mΩ × 1, 1206/2010 | 3 | USD 0.3-0.6 |
| Input bank | 4 × 10 µF 50 V 1206, 2 × (10 nF + 1 nF), 1 µF + 2.2 Ω, 0.47 µF + 1 Ω | 10 | USD 0.05-0.3 |
| ACP/ACN filters | 4 × 4.99 Ω, 4 × 33 nF, 2 × 100 nF | 10 | USD 0.02 |
| VSYS bank | 7 × 10 µF 25 V at Q3/Q4 + 2 × 10 µF after RSR (≥ 50 µF effective) | 9 | USD 0.05-0.2 |
| Bias | REGN_A/B 2 × 2.2 µF + 1 µF, 3 × 0.1 µF bootstrap, SRP/SRN 2 × 10 Ω + 0.1 µF, VBUS 1 Ω/0.47 µF counted above, MODE resistor, CELL divider 2, IADPT/IBAT 2 × 100 pF | 15 | USD 0.02-0.05 |
| **Total** | | **57** + 7-9 adders | **≈ USD 13-20 per board** |

Area estimate: seven 3.3 × 3.3 mm FETs with 2-4 × pad copper (DS Table 10-1 rule 6) about 175 mm², two inductors about
75 mm², the IC with its bypass ring about 60 mm², sense resistors and capacitors about 200 mm², interlock adders about
80 mm²: about 590 mm² of placement before routing. The Ag105 outline is 1114 mm² per side. The stage fits with two-sided
placement and sideways extension for the hot-loop copper; it is the densest layout of the finalists.

---

## 13. Stock and price

| Item | Value | Source and date |
|---|---|---|
| BQ25773REER, TI store | **15 695** units | [TIstore] opninventory, 2026-11-10 18:27 UTC |
| BQ25770GREER, TI store | 54 582 units | [TIstore] opninventory, 2026-11-10 18:27 UTC |
| BQ25773REER price | USD 3.140, quantity basis not stated | ti.com part-details JSON-LD, 2026-11-10; UNVERIFIED |
| Standard package quantity | 3000, large tape and reel | DS addendum p.138; whether the TI store sells cut tape: UNVERIFIED |
| DigiKey | HTTP 403 | Blocked |
| Mouser | Page returned without stock data (script-rendered) | Blocked |
| Power-stage parts (FETs, inductors, sense resistors) | Not checked | UNKNOWN |

**CRIT S12 = 2** (≥ 100 units at one source). **CRIT S13 = 1** (estimate USD 13-20 falls in the USD 15-30 band at its upper
end, but every price except the IC is UNVERIFIED, so the evidence cap of 1 applies).

---

## 14. Round-6 findings (R6) closed, kept or reopened

Only the IC-dependent findings count (CRIT section 3.4).

| R6 # | Key | BQ25773 effect | Basis |
|---|---|---|---|
| 1 | vreg-corruption-no-fixed-pack-ovp (major) | **Kept.** CV is a register (CHARGE_VOLTAGE 5-23 V, DS p.64); BATOVP follows it at 107.8-109.6 % (DS p.18). SYSOVP 11.85 V min for 2S is fixed by the CELL strap but sits above any pack-OV threshold, and SYSOVP_MAX can raise it to 27 V. The OVN term stays. CELL_BATPRES offers a second MCU-independent stop for OVN (1 ms, latches CHARGE_CURRENT = 0, DS §7.3.13 p.39), provided the pin is never LOW at start-up, and the stop keeps the input ceiling only while IIN_DPM_AUTO_DISABLE = 0 (REG0x01 b4, DS p.61) | Same mechanism as the BQ25798 |
| 8 | loop-budget-5ms (major) | **Kept.** Per-burst inhibit and the mode ceiling are pins (no I2C); a mode change still writes VINDPM and IIN_HOST, both two-byte, plus read-back. The write count per mode change is comparable with the BQ25798 image | No reduction proven |
| 10 | chg-src-misattributes-subh1-regen (major) | **Kept.** ADC_IIN accuracy is published at 50 mV (5 A) only, three to four times the operating current; there is no per-source input measurement | DS EC p.15 |
| 12 | ff-reversal-hold-unattainable-at-100khz (minor) | **Kept.** The reversal still needs a VINDPM write. The IC supports 1 MHz, but the Teensy bus rate is a system choice | DS §7.5.1 p.52 |
| 3 | battery-path copper (system class) | Reopens as a sizing task at 3.36 A (section 11.1), as for every candidate | - |

Net: 0 closed, 0 reopened. **CRIT S14 = 2.** The never-write list now holds seven fields at eight register positions (section 5.1). CRIT section 3.4
counts "more never-write registers" as a reopening of R6 finding 8; whether that applies depends on the length of the
BQ25798 image's list, which the main document must compare. If it applies, S14 falls to 1 and condition 3 of CRIT
section 3.5 fails (finding 8 is major).

---

## 15. Open questions, bench gates and blocked fetches

### 15.1 Bench gates

| ID | Test | Pass |
|---|---|---|
| B1 | VINDPM 19.0, 19.8, 13.5 V: regulation point and input current from a stiff source 0.5 V under threshold, CHARGE_CURRENT 3.2 A, the CCB FETs fitted | Within ±1 % at 19 V (±3 % at 13.5 V); I_in < 5 mA (the DS gives IQ_VAC as typical only) |
| B2 | Inhibit latency: H1 edge to input current < 10 % via ILIM_HIZ hold-down (and via FRC_CONV_OFF if the fast path is built), at 1.79 A input | ≤ 110 µs (section 8.2 item 2) |
| B3 | VINDPM, IIN_HOST, WDTMR_ADJ retained across HIZ cycles (and FRC_CONV_OFF cycles if built) (read back) | Unchanged |
| B4 | Warm step: inhibit exit plus Vth − 0.5 V → Vth + 1 V; τ to 63 % of I_chg; also the VINDPM loop alone (no inhibit). Sub-case: burst after more than 1 s of cruise HIZ, CHRG_STAT logged, with BATFETOFF_HIZ = 0, BATFETOFF_HIZ = 1 and EN_LDO = 0 in turn (section 8.3) | τ ≤ 4 ms (≤ 2 ms board-only); records whether a soft-start re-runs and its step period (≤ 15.9 µs), and whether CHRG_STAT passes through 010 (pre-charge) |
| B5 | First charge from VCHG ≈ 0 through D-BT-SQ; D-BT-SQ opened mid-charge; firmware termination | No latch; CHRG_STAT 001 → 011 |
| B6 | (a) LCR of the input MLCC at 16-21 V bias; (b) bus-side current on FC_CHARGE close and at converter start | (a) ≥ 4 µF effective; (b) < 1.0 A peak with aux |
| B7 | Charger watchdog at 5 s setting with CHARGE_CURRENT 1 A and no kicks | I_chg → 0 in 4-7 s |
| B8 | ILIM ceiling: regen and FC divider at three temperatures; open each divider resistor in turn | Inside 1.30-1.79 A and 0.76-1.24 A; ceiling still active with any single resistor open |
| B9 | Charger unpowered, Teensy pull-ups live: SDA/SCL level and current | ≥ 3.0 V, < 50 µA |
| B10 | VCHG-IN ringing at the CCB on a REGEN close at 21 V | < 30 V peak |
| B12 | ADC_IBAT and ADC_IIN against a shunt at 0.5, 1.0, 1.5, 3.2 A | Error recorded for the EMS |
| B13 | ILIM_HIZ held LOW through the whole power-up: does STAT_AC set, VBUS qualify and the converter start on release without a new 226 ms sequence? | Decides whether the CHG_QUAL one-shot and gates can be dropped (section 9.2) |
| B14 | Phase B activity in buck mode at 3.4 A output with SINGLE_DUAL_TRANS_TH POR; FORCE_SINGLE = 1 | Phase B idle in buck mode; no current imbalance faults |
| B15 | EN_IIN_DPM = 0 with IIN_HOST at its 5 A POR value and the regen divider fitted: does the ILIM_HIZ pin still limit the input current? | Records the answer; if the pin limit is lost, EN_IIN_DPM read-back becomes a firmware safety item of the same class as EN_EXTILIM |
| B16 | EN_PTM = 1 with ILIM_HIZ held LOW (and with FRC_CONV_OFF active, if the fast path is built), current-limited source | PTM does not conduct while ILIM_HIZ is LOW; otherwise the eFuse is the HR4 bound for a REG0x30 corruption |
| B17 | Regen step at 21.5 V with 1.79 A input, the selected RAC and FETs | No OCP_SW1X or OCP_SW2 latch; if one latches, the EN_HIZ toggle recovery is timed |

### 15.2 Open questions

1. Asymmetric phase-B sizing (light-load FETs and inductor): not documented. TODO(verify: TI E2E).
2. Controller minimum on-time: not published (section 12.1). TODO(verify: SLUSEK7 or TI E2E).
3. Exit latency and soft-start on HIZ and FRC_CONV_OFF exit (B2, B4): not published.
4. BQ25770G gate drive with Si MOSFETs: SLUSFK8 shows E-GaN in the buck half bridges (DS-G Fig 8-1 p.113) and lists "Buck
   dual phase GaN gate drive" in the comparison table (DS-G p.4). Si compatibility is not stated. TODO(verify: SLUSFK8 §7.3).
5. 2.5 V shunt reference part, tolerance and minimum cathode current. TODO(verify: TLV431 datasheet).
6. Distributor stock and power-stage part prices (section 13).
7. VINDPM accuracy at 13.5-15 V (only 18 V and 4.48 V tabulated).
8. Whether EN_IIN_DPM = 0 also removes the ILIM_HIZ pin limit (B15). TODO(verify: SLUSEK7 / TI E2E).
9. Whether HIZ (ILIM_HIZ LOW) takes precedence over PTM (B16). TODO(verify: SLUSEK7 / TI E2E).
10. Whether tTRANS_CHG applies with EN_LDO = 0, and the VSYS re-charge transient with BATFETOFF_HIZ = 1 (section 8.3, B4).
11. Independent-comparator threshold tolerance for CMP_POL = 1 (only CMP_POL = 0b is tabulated). TODO(verify: SLUSEK7).
12. Whether the operator requires battery-temperature qualification on the CCB; the BQ25773 has no TS input (section 2.4).
13. FC ceiling position: H5 worst case against the 1.20 A arm drop (section 11.4); an operator ruling.

### 15.3 Corrections to [R2-773] found while re-checking

| # | [R2-773] statement | Primary reading |
|---|---|---|
| 1 | BATCOC "1 µs deglitch" (H2 table) | 1 s deglitch (§7.3.26.6 p.49); the register-default inconsistency (REG0x15 reset 3h p.75 against "disabled by default" p.48) stands |
| 2 | Safety timer 8 h default (H5) | REG0x17 CHG_TMR POR 01b = 8 h (p.77), but Table 7-2 p.31 states 12 h: a new DS inconsistency; read back CHG_TMR |
| 3 | ILIM accuracy "about ±0.2 A by interpolation" | Confirmed as ±200 mA absolute at all four tabulated points (EC p.12) |
| 4 | Not recorded | VILIM_ENZ 4.1/4.2 V disables the pin ceiling regardless of EN_EXTILIM (p.6, p.20) |
| 5 | Not recorded | EN_EXTILIM, WDTMR_ADJ and WD_RST are mirrored at REG0x80; EN_AUTO_CHG and EN_OTG at REG0x81 (p.121-122) |
| 6 | Not recorded | CHARGE_CURRENT resets on STAT_AC loss and on CELL_BATPRES LOW (p.63) |
| 7 | Not recorded | Capacitance after each RAC limited to 10 µF + 10 nF + 1 nF (p.126) |
| 8 | Efficiency "≈ 94 % at 20 V" | ≈ 95.5 % at 20 V, 7.4 V, 3 A from Fig 6-3 p.22 (system output; BATFET and RSR excluded) |

### 15.4 Blocked fetches

| URL | Reason |
|---|---|
| https://www.digikey.com/en/products/result?keywords=BQ25773REER | HTTP 403 |
| https://www.mouser.com/c/?q=BQ25773REER | Returned a script-rendered page without stock data |
| TI price per quantity break for BQ25773REER | The part-details page carries one JSON-LD price without a quantity; the price endpoint returned HTTP 404 |

---

## 16. Verdict and comparison with the BQ25798 baseline

### 16.1 Verdict

**FEASIBLE_W_COND.** No must-have fails on the primary. The conditions are:

- the 2.5 V reference-biased, mode-switched ILIM_HIZ divider (section 7);
- the never-write list with read-back: EN_EXTILIM at two addresses, EN_IIN_DPM, IIN_DPM_AUTO_DISABLE, EN_PTM,
  DETECT_VINDPM, SYSOVP_MAX and ACOV_ADJ (sections 5.1, 7.2);
- REG0x30 never written, so the optional FRC_CONV_OFF fast path is not built (section 9.3);
- a remedy for burst entry from a drained VCHG (BATFETOFF_HIZ = 1, EN_LDO = 0 or a VBT keep-alive above about 6.8 V),
  proven on bench B4 (section 8.3);
- an operator ruling on the FC ceiling position, because no setting meets both H5 at the low corner and the 1.20 A arm drop
  at the high corner (section 11.4);
- the always-powered architecture (226 ms cold start), bench gates B2 and B4 for HR1, B8 for the ceiling, B15 and B16 for the
  register defeats, and a four-layer CCB with a populated phase B.

### 16.2 Score (CRIT section 3.1, with the section 3.2 evidence cap)

The score is for the recommended build: 7 adders, no fast path, no keep-alive.

| Criterion (weight) | Score | Evidence | Basis |
|---|---|---|---|
| S1 warm response (15) | 1 | U | Exit soft-start and latency unpublished; burst entry from a drained VCHG passes through the nominal 5 ms tTRANS_CHG of unpublished shape (B, section 8.3) |
| S2 fail-safe POR (10) | 2 | P | No charge at POR; POR VINDPM 3.2 V prevents 3 |
| S3 ceiling quality (8) | 3 | P | Pin ceiling, one resistor and one switch, read continuously, ±200 mA published. Register-defeatable (EN_EXTILIM, probably EN_IIN_DPM); the CRIT bands carry no defeatability term, as for the BQ25798 |
| S4 threshold quality (8) | 2 | P / B | 20 mV, ±1 % at 18 V; retention across HIZ is B3 |
| S5 inhibit latency (7) | 1 | U | ILIM_HIZ entry latency unpublished; the 1 µs FRC_CONV_OFF deglitch belongs to the fast path, which is not built |
| S6 interlock adders (10) | 1 | P / B | 7 adders; 0 if the fast path or the keep-alive is added |
| S7 telemetry (5) | 2 | P | IBAT, IIN, VBUS; no ADC_IBAT accuracy row |
| S8 FC-mode fitness (6) | 1 | P | IIN step 25 mA, but CV +0.6 % exceeds the ±0.5 % anchor |
| S9 rating margin (4) | 2 | P | 45 V |
| S10 layout (7) | 0 | P | External-FET buck-boost |
| S11 package (3) | 1 | P | 0.4 mm pitch QFN |
| S12 stock (5) | 2 | P | 15 695 at TI only |
| S13 cost (2) | 1 | U | Estimate, cap 1 |
| S14 round-6 (5) | 2 | P | Net 0; the longer never-write list may count against R6 finding 8 (section 14) |
| S15 input capacitance (3) | 2 | C | 13 % margin |
| S16 topology barrier (2) | 0 | P | Buck-boost, POR threshold below the pack |
| **Weighted total** | **≈ 49 / 100** | | 5.0 + 6.7 + 8.0 + 5.3 + 2.3 + 3.3 + 3.3 + 2.0 + 2.7 + 0 + 1.0 + 3.3 + 0.7 + 3.3 + 2.0 + 0 = 48.9 |

Sensitivity: with the fast path (S5 2, S6 0) the total is about 48; with the keep-alive (S6 0) about 46; with R6 finding 8
counted as reopened (S14 1) a further 1.7 points lower. The screening provisional score was about 55. The changes are S6
(2 → 1, the reference pair), S8 (2 → 1, the CV anchor), S11 (2 → 1, 0.4 mm pitch), S3 (2 → 3, continuous read with published
accuracy) and S5 (2 → 1, the fast path removed from the recommended build).

### 16.3 Decision rule (CRIT section 3.5)

The baseline is dossier_BQ25798.md: about 40 points, valid only under one M2 rule applied to every part (that dossier,
section 3).

| Condition | BQ25773 | Result |
|---|---|---|
| 1. Every must-have passes; no conditional pass on M5, M6 or M7 where the BQ25798 has P evidence | All must-haves pass. M7 is conditional for both parts for the same EN_EXTILIM register-defeat class; the BQ25798 M7 is itself a "Conditional pass (P mechanism, C nominal bounds, B re-sampling)". M5 and M6 are P for the BQ25773 | Met under a symmetric grading. If the main document reads the BQ25798's "P mechanism" as P evidence for M7, condition 1 bars the BQ25773; that reading would equally penalise any part with a register-defeatable ceiling |
| 2. Score margin ≥ 10 points | 49 − 40 = 9 (recommended build); 6-8 with the contingent adders | **Not met** |
| 3. No major IC-dependent R6 finding reopened | None reopened; R6 finding 8 open to the never-write comparison (section 14) | Met, provisionally |
| 4. S1 ≥ the BQ25798 S1 | 1 against 1 | Met |

**Outcome: the BQ25773 is the alternate, not a switch.** It meets conditions 1 and 4, and condition 3 provisionally (R6 finding 8 open to the never-write comparison, section 14; the strict S14 reading fails it), with a margin below 10 points.

### 16.4 Comparison with the BQ25798

The BQ25773 has three advantages over the BQ25798 on the CCB. First, it passes M2 outright (45 V abs max, ACOV 33 V default),
whereas the BQ25798 fails M2 as written (30 V) and depends on the eFuse OVP being admitted as a protected standoff. If the
operator applies M2 strictly, the BQ25798 fails a must-have and the BQ25773 becomes the leading TI candidate on that ground
alone. Second, its POR state is intrinsically non-charging (CHARGE_CURRENT 0, no NVM; S2 2 against 1), whereas the BQ25798
charges at 1 A out of POR and relies on the REGN-biased /CE and ILIM_HIZ network. After configuration both parts rest on the
same class of hold-down network and watchdog, so HR5 is P/C/B for the BQ25773 against C by design for the BQ25798. Third, its
ceiling pin is read continuously with a published accuracy, whereas the BQ25798 re-sampling of ILIM_HIZ is a bench gate.

HR1 input power is not a differentiator: both parts reach ≥ 23 W at the threshold, and for both a charge setting above
3.1 A waits on the pack datasheet (T-E-11).

However, the BQ25773 carries five weaknesses against the baseline:

1. **FC hardware bound.** The ±200 mA absolute pin accuracy gives an FC ceiling of 0.76-1.24 A. After an IIN_HOST loss the
   bus draw can reach 1.39 A, above the 1.20 A arm drop and the 1.247 A H-20 P_MAX, against 1.15 A for the BQ25798 after a POR (1.70-1.76 A after an IINDPM loss if ILIM_HIZ is sampled once; S1-B6). H5 then
   misses by 0.15 A at the low corner, and no ceiling position meets both limits (section 11.4).
2. **Burst entry from a drained VCHG.** Behind D-BT-SQ the next burst starts in pre-charge and passes through the nominal
   5 ms tTRANS_CHG (shape unpublished): a linear ramp passes the 4 ms warm budget (63 % at about 2.9 ms) and a delay fails
   it, so the item is B. The WD keep-alive does not reach VSYS_MIN; a remedy must be benched (section 8.3).
3. **Register-defeat surface.** The never-write list holds seven fields, including EN_IIN_DPM and the automatic
   IIN_DPM_AUTO_DISABLE path, and REG0x30 shares EN_PTM and SYSOVP_MAX with the fast-path bits (sections 5.1, 7.2, 9.3).
4. **No battery TS input.** Battery-temperature qualification needs a CCB comparator if the operator requires it
   (section 2.4).
5. **Layout.** Seven external FETs, two inductors, three hot loops, a 0.4 mm-pitch QFN and four layers on the CCB, against an
   integrated part.

The BQ25773 also shares the BQ25798's central unknown: neither datasheet publishes the inhibit-exit latency or the warm
response that decide HR1.

---

## 17. Verification log

Findings from two independent reviewers of this dossier (2026-11-10), each re-checked against SLUSEK7 and the round's
board-side documents before disposition.

| # | Finding | Severity | Disposition | Basis |
|---|---|---|---|---|
| 1 | EN_IIN_DPM = 0 and the automatic IIN_DPM_AUTO_DISABLE path missing from the never-write list; CELL_BATPRES OVN stop interacts | Major | Applied | DS §7.3.12-7.3.13 p.39; REG0x00 p.59 (reset 0Eh, b1 = 1); REG0x01 p.61 (b4 POR 0). Added to M7, sections 5.1, 7.2, 14, 16.1; bench B15; pin-limit effect marked UNVERIFIED |
| 2 | REGN-ratiometric band stated as 1.14-1.78 A | Minor | Applied | Recomputed: 1.387-1.630 A before errors; 1.16-1.86 A with pin and divider errors, 1.14-1.87 A with leakage; low corner 21.5 W (section 7.3) |
| 3 | Pin leakage claimed to fit inside the ±0.7 % budget | Minor | Applied | DS EC p.12 ILEAK_ILIM ±1 µA. Carried as a separate column: regen 1.30-1.79 A, FC 0.76-1.24 A (FC R_th 5.60 kΩ gives ±14 mA, not ±16 mA); sections 4, 7.3, 8.2, 11.3, 11.4, 15.1 updated |
| 4 | FC low corner rounded up to 0.78 A | Minor | Applied | 0.999 − 0.225 = 0.774 A; with leakage 0.76 A, giving 1.35 A at 8.4 V (section 11.4) |
| 5 | FAULT_FRC_CONV_OFF cited at REG0x21 b2 | Minor | Applied | DS §7.6.23 p.83: REG0x20 ChargerStatus1, field at b2 (p.84) |
| 6 | Boost-mode switching described as both buck phases switching | Minor | Applied | DS §7.3.16 p.40: in boost mode Q1_A and Q1_B stay on, the boost leg switches at 2 × Fsw |
| 7 | Latched converter-off states (OCP_SW1X, OCP_SW2, SYSOVP, VSYS_UVP) omitted | Minor | Applied | DS REG0x32 p.100; §7.3.26.4 p.48; §7.3.26.12 p.50. Table, recovery step and bench B17 added (section 5.1) |
| 8 | IQ_VAC draw rated P | Minor | Applied | DS EC p.14: 2.50 mA typical only, VBAT 12.6 V 3S, EN_OOA = 0. M8 and section 6 now P (typical) / B; B1 carries it |
| 9 | Switching frequency and watchdog nominals | Minor | Applied | DS EC p.19 (770 kHz typ for PWM_FREQ = 0); §6.6 p.21 (5.5 s typ for 01b) |
| 10 | Four-layer minimum attributed to the DS; pad given as 2.8 × 3.8 mm | Minor | Applied | DS Table 10-1 rule 1 p.132 (multi-layer, one ground layer; EVM text inconsistent); outline p.141 (2.6-2.8 × 3.6-3.8 mm) |
| 11 | Comparator threshold tolerance applied to CMP_POL = 1 | Minor | Applied | DS EC p.19 test condition "Negative polarity CMP_POL=0b"; TODO(verify) added (section 9.3, open question 11) |
| 12 | Keep-alive dismissed; burst entry from a drained VCHG through pre-charge and tTRANS_CHG not assessed | Major | Applied | DS §7.3.14 p.40, §7.3.3 p.28, EC p.13, EC p.17, Table 7-6 p.39, Table 7-2 p.31, §7.3.26.8 p.49, §6.6 p.21 (tTRANS_CHG 5 ms); WD B.5 (3.63-4.46 V); dossier_BQ25798.md section 8. New section 8.3; H7, HR1, S1 basis and B4 updated; drain time recomputed as 0.06-1.1 s (the reviewer's 0.77 s upper end understated the 1 V/s case) |
| 13 | Stale BQ25798 baseline (43 points, 2.50 A ICHG cap, HR5 "stock F", S6 9-10) | Major | Applied | dossier_BQ25798.md: about 40, HR1 ≥ 23 W, HR5 C by design, S6 0 (9-16 adders). Section 11.3 and 16 rebased; "no ICHG cap" removed as a differentiator |
| 14 | S5 and S6 credit different builds; CRIT §3.5 condition 1 not tested | Major | Partly applied | S5/S6 now scored for one build (no fast path: S5 1, S6 1; total about 49, margin 9). Condition 1 tested in section 16.3. Rejected in part: the BQ25798 M7 is itself graded "Conditional pass" in dossier_BQ25798.md, not "Pass", so a symmetric reading does not trigger condition 1; the alternative reading is recorded |
| 15 | FC bound after IIN_HOST loss misstated ("within 0.02 A of the governor"); arm drop and P_MAX not checked | Major | Applied | 1.24 + 0.15 = 1.39 A: 0.14 A above the governor, above P_MAX 1.247 A and the 1.20 A arm drop (EVAL 1.1, 3.4); BQ25798 bound 1.15 A. Section 11.4 rewritten with the ceiling/H5 trade-off computed (window 0.20 A against a 0.48 A band); HR4 FC rated weaker than the baseline; H5 worst case F at the present ceiling |
| 16 | REG0x30 shared-byte hazard (EN_PTM, SYSOVP_MAX) created by the fast path | Major | Applied | DS REG0x30 p.96 (reset 01h); §7.4.3 p.52; §7.3.26.4 p.48; EVAL 1.3. Fast path removed from the recommended build; hazard, full-constant write and bench B16 recorded (sections 7.2, 9.3) |
| 17 | HR5 rated P on the POR property alone | Minor | Applied | Dossier section 5.3 items 1-3; dossier_BQ25798.md section 5.2. HR5 and H3 now P / C / B; comparison now against the BQ25798's C |
| 18 | THERM routed to a Teensy ADC; no battery TS input noted | Minor | Applied | SPEC pad 13 (J-NTC, external NTC to GND); DS pin table p.7, §7.3.6. Section 2.4 corrected; contingent adder and open question 12 added |

Totals: 18 findings; 17 applied, 1 partly applied, 0 rejected.

**Blocked fetches.** None new in this revision. The distributor fetches of section 15.4 remain blocked.
