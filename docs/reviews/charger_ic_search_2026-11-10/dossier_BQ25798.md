# Dossier: TI BQ25798 on the custom charger board (baseline re-assessment, 2026-11-10)

This dossier re-assesses the TI BQ25798, the part chosen on 2026-11-05, for the **custom charger board (CCB)** defined in
`screening_criteria.md` section 1.1: one board that plugs into the 22 Ag105 holes of board rev 20260622 and carries the
charger IC, its power stage and the hardware interlock. The 2026-11-05 design mounted a BQ25798EVM off-board and connected it
through a carrier (CR) and an EVM interface board (EIB). This dossier states what that design becomes when the IC sits on the
CCB. It builds on the round-2 primary-read dossier and does not repeat its verified facts; it cites them.

Source tags used below:

| Tag | Document |
|---|---|
| [DS] | TI SLUSDV2C, *BQ25798 I2C Controlled, 1 to 4-Cell, 5A Buck-Boost Battery Charger with Dual-Input Selector, MPPT for Solar Panels and Fast Backup Mode*, May 2020, revised June 2026 (151 pp.). Cited as DS p.N plus section, table or figure. PDF page = printed page |
| [UG] | TI SLUUCB5E, *BQ25792EVM, BQ25798EVM and BQ25798BKUPEVM (BMS034) Evaluation Module*, June 2020, revised July 2022. Read for layout information only (section 3, p.14; BOM Table 4-1, pp.22-24) |
| [R2] | `docs/reviews/charger_eval_2026-11-05/round2/dossier_BQ25798.md` (primary-read dossier, 2026-11-05) |
| [EVAL] | `docs/charger_replacement_evaluation_2026-11-05.md` |
| [WD] | `docs/charger_bq25798_wiring_design_2026-11-05.md` (round-6 carrier and EIB design) |
| [R6] | `docs/reviews/charger_eval_2026-11-05/round3/review_loop.md`, review round 6 |
| [CRIT] | `docs/reviews/charger_ic_search_2026-11-10/screening_criteria.md` |
| [SCR] | `docs/reviews/charger_ic_search_2026-11-10/screening.md` |
| [RT] | Richtek RT1987 DS-00 (`references/Datasheets/RT1987_DS-00.pdf`), as cited by [EVAL] and [WD] |
| [TIstore] | ti.com, fetched with curl on 2026-11-10 at 18:27 UTC: `ti.com/storeservices/cart/opninventory?opn=BQ25798RQMR` and `?opn=BQ25798EVM`; product page `ti.com/product/BQ25798` (embedded tiered-price JSON) |

Status codes: P = PROVEN_DATASHEET, C = PROVEN_CALC, B = BENCH_GATE, F = FAIL, U = UNKNOWN or missing primary, sys = blocked
at system level. Values read off a datasheet figure are labelled "figure reading, typical" and are never treated as a
specification. The calculations of this dossier are in `calc/bq798_ccb.py` in this folder;
every result used is restated in the text with its inputs.

---

## 1. Identity and sources

| Item | Value | Source |
|---|---|---|
| Manufacturer, part | Texas Instruments BQ25798 | DS p.1 |
| Orderable part number | BQ25798RQMR (VQFN-HR, RQM, 29 pins, 3000 per large T&R; also listed as BQ25798RQMR.A / .B); status **Active**, production; MSL Level-2-260C-1 year; -40 to 85 °C | DS p.145, package option addendum |
| Package | RQM0029A, VQFN-HR, 4.0 x 4.0 mm (3.9-4.1 mm), 1.0 mm maximum height, 0.4 mm lead pitch (23X 0.4), no exposed thermal pad; power pins are elongated pads | DS p.148 (package outline), p.149 (land pattern) |
| Datasheet read | SLUSDV2C, revised June 2026 (the same revision that [R2] read in full on 2026-11-05) | DS p.1 |
| URL, fetch date | https://www.ti.com/lit/ds/symlink/bq25798.pdf, fetched 2026-11-10 | - |
| EVM guide read (layout only) | SLUUCB5E, revised July 2022; https://www.ti.com/lit/ug/sluucb5/sluucb5.pdf, fetched 2026-11-10 | UG p.1 |
| Pages re-read for this dossier | Pin table (pp.4-6), absolute maximum and recommended operating conditions (p.7-8), thermal information (p.8), electrical characteristics (pp.8-17), typical characteristics (p.18), §7.3.1-7.3.4.5 (pp.25-28), §7.3.6 and §7.3.6.5 (pp.33, 35), typical application and design procedure (pp.130-134), application curves (p.136), layout (pp.139-140), package (pp.145-150) | DS |

Secondary sources: none are relied on. Distributor stock other than the TI store was not reachable (section 13).

---

## 2. Architecture on the custom board

### 2.1 Topology

The BQ25798 is an integrated four-switch buck-boost NVDC charger: Q1/Q2 form the input-side half bridge (PMID-SW1-GND),
Q3/Q4 the output-side half bridge (SW2-GND-SYS), and an integrated BATFET connects SYS to BAT. Input current is sensed
between VBUS and PMID (RSNS 8 mOhm) and charge current between SYS and BAT; both sense elements are internal and high-side
(DS Table 5-1 pp.4-6; EC p.14, RSNS and RQ1_ON-RQ4_ON). Typical on-resistances are RQ1 24 mOhm, RQ2 35 mOhm, RQ3 28 mOhm,
RQ4 17 mOhm and RBATFET 11 mOhm (DS EC pp.12, 14-15; typical only, no maximum given).

Across the operating envelope the converter runs in buck mode: VCHG-IN is at least 13.14 V wherever charging is required and
the charger output is at most 8.455 V ([CRIT] section 4.4; VREG accuracy DS EC p.11). The buck-path series resistance is
RSNS + RQ1 + RQ4 + RBATFET = 60 mOhm typical plus the inductor DCR; with an assumed 10 mOhm DCR the drop at 3.21 A is
0.22 V (C, typical values). This replaces the 100 mOhm assumption of [CRIT] section 4.3 for this part. The boost capability
earns no credit here ([CRIT] section 4.8).

Minimum on-time is not specified in [DS], but the low-duty case of [CRIT] section 4.8 item 4 (0.13 at a 3 V VCHG) does not
apply to this part. The BQ25798 is an NVDC charger: the converter output is SYS, and "the charger regulates SYS pin to at
least SYSMIN voltage" (DS §7.3.6 p.33). Below VSYSMIN the BATFET charges BAT in linear (LDO) mode (DS §7.3.9.2 p.39;
IPRECHG_ACC note, EC p.11). With VSYSMIN regulated at 7.12-7.52 V for 2s (EC p.10), the smallest buck duty is about
7.12 / 22.28 = 0.32, which is 427 ns at 750 kHz (C). This holds only while SYS is a separate node that carries capacitors
only and reaches BAT only through the internal BATFET (section 2.2).

### 2.2 Placement between VCHG-IN and VCHG

```
MB pad 10 VCHG-IN --> CCB: TPS26630 eFuse (OVP 22.61-23.63 V, I_OL 2.05-2.41 A, [WD] B.4)
                         --> VBUS/VAC1/VAC2 (tied) -- RSNS -- PMID -- Q1/Q2 -- L -- Q3/Q4 -- SYS -- BATFET -- BAT/BATP
                                                                                                          |
MB pads 18/19 VCHG  <-------------------------------------------------------------------------------------+
                                       (VCHG -> D-BT-SQ RT1987 on the MB -> VBT, the pack)
MB pads 4/14/15 GND <--- single CCB ground (PGND and AGND joined at the IC GND pin)
```

- VAC1 and VAC2 tie to VBUS, and ACDRV1/ACDRV2 tie to GND, because no ACFET/RBFET pair is fitted (DS Table 5-1 pp.4-5).
  The IC then runs in "VBUS input only" mode ([R2] M5; DS §7.3.5.2). The EVM jumper network JP1-JP4 disappears.
- **SYS is a separate node.** It carries only its datasheet ceramics (5 x 10 uF + 0.1 uF, CSYS >= 6 uF effective, DS Table
  5-1 p.6 and §6.3 p.8) and no load, and it reaches BAT only through the internal BATFET. Only BAT (with BATP through
  100 Ohm) connects to MB pads 18/19. SYS must never be strapped to BAT. The charge-current sense element is in the BATFET
  path ("The internal charging current sensing circuit is connected between SYS and BAT", DS Table 5-1 p.5), and with
  charging disabled the converter keeps regulating SYS (DS §7.3.6 p.33 item 1; §7.3.9.2 p.39). A SYS-BAT strap would
  therefore bypass ICHG regulation and the IBAT ADC, and /CE would no longer stop power into VCHG: with ILIM_HIZ released,
  charge would be bounded only by the ILIM ceiling (1.81 A x 18.62 V x 0.925 / 7.4 V = 4.2 A, C). The `CHG_QUAL AND NOT P5`
  window, whose safety rests on /CE HIGH ([EVAL] 2.7), would then reopen loop L-R. The 2026-11-05 EVM design kept SYS
  separate and unloaded ([WD] EM7, J3). A CCB layout check and bench check CCB-1 (section 15.2) confirm the separation.
- SDRV takes a 1 nF 50 V 0402 capacitor to GND because no ship FET is fitted (DS Table 5-1 p.5).
- BATP connects to the BAT pin through 100 Ohm (DS Table 5-1 p.5). The pack side of D-BT-SQ (VBT) is not on any of the 22
  pads ([CRIT] section 1.1), so BATP cannot sense the pack. [R2] §2.7 recommends BAT-pin sensing even where pack sensing
  is possible.
- PROG: 8.2 kOhm (2S, 750 kHz) with a 2.2 uH inductor, or 6.04 kOhm (2S, 1.5 MHz) with a 1 uH inductor (DS Table 7-1 p.25;
  §8.2.2.2 p.133: each frequency "only works" with its inductor). The CCB removes the EVM constraint that held [R2] at
  1.5 MHz (EVM L2 1 uH only). Section 11 recommends 750 kHz.

### 2.3 What the 22-hole plug-in board carries

| Block | Parts | Origin in the 2026-11-05 design |
|---|---|---|
| Charger IC and power stage | BQ25798RQMR, inductor, VBUS/PMID/SYS/BAT ceramics (SYS a separate capacitor-only node), BTST1/BTST2 47 nF, REGN 4.7 uF, PROG, TS divider, SDRV 1 nF | The EVM |
| IC-specific interlock adders | /CE pull-up to REGN and open-drain drive; ILIM_HIZ hold-down from REGN; release feed; FC-leg ceiling switch; `CHG_QUAL AND NOT P5` gates | EIB ([WD] B.6) and CR |
| System core (same for every candidate, [CRIT] section 3.3) | TPS26630 eFuse with input bulk and TVS; TLV3012B comparators H1, BT_ACT, FCC/RGN level sensing; C7 network; OVN pack-OV term; heartbeat monostables | CR ([WD] B.1-B.4) |
| Connections | 1x10 + 1x12 header columns at the CHG pads; CR tap field to the MB (V-MOT, VBUS, BT_CURRENT, EN nets, Teensy pins) | CR ([WD] A.2, A.4) |

The CR (31 x 33 mm, 4-layer, [WD] E) was already fully populated. The charger power stage therefore extends the CCB
sideways past the footprint (section 12).

---

## 3. Must-have check

| ID | Result | Value | Citation |
|---|---|---|---|
| M1 common ground | **Pass (P)** | One GND pin (27); input sense VBUS-PMID and charge sense SYS-BAT are internal and high-side; no element in any return | DS Table 5-1 pp.4-6; [R2] §2.1 |
| M2 input rating >= 35 V | **Fail as written; conditional pass (c) as a protected standoff** | VAC1/VAC2/VBUS/PMID/SW1 abs max 30 V (VBUS and PMID "converter not switching"); VBUS operating 3.6-24 V. On the CCB the TPS26630 eFuse (60 V part) is the 35 V element; its OVP cut-off 22.61-23.63 V ([WD] B.4) keeps the IC pins at or below the 24 V operating maximum. VBUS_OVP 25.2 V min, so no drop-out at the 22.28 V clamp. The screen rejected the 30-33 V parts on M2 F; this reading is valid only if the main document applies it to every part (note below the table) | DS §6.1 p.7, §6.3 p.7, EC p.9; [SCR] section 5.2 |
| M3 2S profile, CV +-1.0 % | **Pass (P)** | VREG 8.4 V at -0.25/+0.65 % (TJ -40 to 85 °C) -> 8.379-8.455 V; pre-charge, CC, CV, termination 40-1000 mA | DS EC p.11 |
| M4 >= 3.1 A at 8.4 V, <= 2 W | **Conditional pass (B)** | ICHG 0.05-5 A, ROC fast charge 5 A. Loss at 3.1 A into 8.4 V: 2.11 W at 20 V / 750 kHz, 1.66 W at 15 V / 750 kHz (figure reading, typical; section 11). The 2 W limit is exceeded by 0.11 W only in regen bursts of <= 0.6 s | DS EC p.11, §6.3 p.7, Fig 6-3 p.18 |
| M5 hard inhibit pin from POR | **Pass (P; EN_EXTILIM interaction B)** | ILIM_HIZ < 0.75 V stops switching with REGN on; /CE HIGH disables charging; both act without I2C. /CE stops power into VCHG only with SYS separate (section 2.2). That EN_EXTILIM = 0 removes only the current-clamp role of the pin and leaves the < 0.75 V stop is an inference: §7.3.4.3 gives the two in separate paragraphs and does not state how they interact (B: S1-B3). The design keeps EN_EXTILIM = 1 and reads it back | DS Table 5-1 p.5, §7.3.4.3 p.27, EC p.16; [EVAL] 0.2 reason 2 |
| M6 fail-safe default | **Pass (C, by design; requires SYS separate)** | /CE has no internal pull ("do not leave floating"); the CCB pulls it to REGN. ILIM_HIZ is held below 0.75 V by an NMOS whose gate is pulled to REGN. No NVM: all registers are volatile and POR returns to defaults | DS Table 5-1 p.5; [R2] §2.3(d); section 5 |
| M7 hardware current ceiling | **Conditional pass (P mechanism, C nominal bounds, B re-sampling)** | ILIM_HIZ divider read by the ADC at qualification; the host "cannot program the IINDPM register to any values higher than this ILIM clamp after POR, unless ... EN_EXTILIM is set to 0". The ceiling holds after POR (EN_EXTILIM POR 1), but one R/W bit (REG14[1]) defeats it, so the M7 wording "no register write can raise" is met only with read-back of REG14 | DS §7.3.4.3 p.27, Table 7-30 p.78; section 7 |
| M8 runtime input-voltage regulation | **Pass (P range; B draw)** | VINDPM 3.6-22 V, 100 mV, R/W at any time; +-2 % at 18.6 V, +-3 % at 10.6 V. Draw near threshold: IQ_VBUS 3-5 mA at 15 V with the converter switching (charge disabled); REGN-on HIZ draw unspecified | DS EC p.8, p.12; [R2] §2.4 |
| M9 no cold restart in the regen path | **Conditional pass (U -> B)** | ILIM_HIZ "resumes switching" above 1 V with no qualification step stated; VINDPM is a regulation loop; neither re-runs POR, deglitch or a stated soft-start. No primary gives the exit timing | DS §7.3.4.3 p.27; [R2] §2.4 warm response |
| M10 host interface | **Pass (P; unpowered-pin behaviour U)** | I2C 0x6B, VIH 1.3 V / VIL 0.4 V, 6 V abs max; SDA/SCL clamping with the IC unpowered is not specified | DS EC pp.15-16, §6.1 p.7; [R2] §2.9 |
| M11 charge-current telemetry | **Pass (P; requires SYS separate)** | IBAT ADC 1 mA LSB, 6 ms per channel at 13 bits typical (12 minimum); IBAT measures the BATFET path only (section 2.2) | DS EC pp.16-17; [R2] §2.12 |
| M12 runtime current control | **Pass (P)** | IINDPM 0.1-3.3 A and ICHG 0.05-5 A, 10 mA steps, R/W | DS EC pp.11-12 |
| M13 lifecycle | **Pass (P)** | Active | DS p.145 |

M2 is the only must-have that this part fails as written. [SCR] section 5.2 leaves the reading to the scoring (scoring.md). This
dossier applies the protected-standoff reading and records the consequence: the IC is protected only while the eFuse OVP is
healthy. The TPS26630 OVP cut-off is 22.61-23.63 V (V(OVPR) 1.176-1.224 V, SLVSE94G section 6.5 p.6, through the
845k / 66.5k / 49.9k divider of [WD] B.4: tap ratio 0.05190). The OVP switch turn-off delay OVP_tOFF(dly) is 8.5/11/14 us
(SLVSE94G section 6.6 p.8; URL https://www.ti.com/lit/ds/symlink/tps2663.pdf confirmed, revision June 2024). At the
4.30 V/ms regen slope ([EVAL] section 2.5) the eFuse output therefore holds at most 4.30 V/ms x 14 us = 0.06 V above the
cut-off: 23.63 + 0.06 = 23.69 V at the IC pins. This level is under the 24 V recommended VBUS maximum and the 25.2 V
VBUS_OVP minimum (SLUSDV2C section 6.3 p.7, section 6.5 p.9). A conservative reading that adds the 20 mV OVP-pin overdrive of
the delay specification (0.020 / 0.05190 = 0.39 V at the input) gives 24.07 V. A pin voltage of 25.2 V needs at least
(25.2 - 23.63) / 14 us = 112 V/ms, that is 54 A into the 0.48 mF board-only V-MOT capacitance. The output overshoot during
the turn-off delay remains a bench item (main document section 7, condition 1).

The protected-standoff reading has two further consequences. First, the eFuse OVP minimum, 22.61 V, is 0.33 V (1.5 %)
above the 22.28 V clamp maximum ([WD] B.4, H.5). A V-MOT excursion above 22.61 V for more than 8.5-14 us opens the eFuse,
VCHG-IN collapses, and the eFuse re-closes only when its input falls below V(OVPF) 1.09-1.15 V / 0.05190 = 21.0-22.2 V
(SLVSE94G p.6). The restart then takes OVP_ton(dly) 150 + 49.5 x 22 = 1239 us (about 1.2 ms), a dVdT ramp of about
8.35 ms x 21.6 / 24 = 7.5 ms (SLVSE94G p.8-9, C(dVdT) 22 nF) and the cold start of section 8 (REGN about 150 ms plus about
30 ms poor-source check): about 190 ms in total. M9 is therefore met only while V-MOT stays below 22.61 V; the peak above
the VESC cut is unmeasured ([WD] T-E-03). Second, the [EVAL] section 3.2 lever "raise the VESC cut-off to about 23-24 V" is
not available. The cut-off must stay below 22.61 V with the fitted divider. With any re-selected divider whose OVP maximum
stays at or below the 24 V operating limit, the nominal cut-off is at most 24.0 / 1.0219 = 23.49 V and the OVP minimum at
most 23.49 x 0.9781 = 22.97 V, so the VESC cut-off can rise at most to about 22.9 V.

The protected-standoff reading is not specific to this part. If it admits the BQ25798, it equally admits every part rated at
24 V or more operating with a 30-33 V absolute maximum (the BQ25713, BQ25720/BQ25731, BQ24650 and RT9492 class that [SCR]
rejects on M2 F), because the eFuse belongs to the system core of every candidate ([CRIT] section 3.3). The main document
must apply one M2 rule to every part: either the baseline fails M2 as written, or the 30-33 V class is re-admitted to
scoring with S9 = 0. Until that rule is stated, the score of section 16 is not a valid reference for the [CRIT] section 3.5
decision rule.

---

## 4. HR1-HR5 and H1-H12 status

Layout follows [EVAL] section 1.2. The left status column is the 2026-11-05 EVM design; the right column is the CCB.

| Req | 2026-11-05 (EVM) | CCB | Basis on the CCB |
|---|---|---|---|
| HR1 regen | U (B: latency, warm) | **U (B)** | Warm response and inhibit-exit latency are not in [DS]; bench gates S1-B3/S1-B4 and system gate S0-R3/T-E-03 unchanged. ICHG 3.1 A is available at 750 kHz with a loss of 2.11 W at a 20 V input, 0.11 W above the 2 W limit (M4 conditional on loss, section 11.2); the regen ceiling limits charge at an 8.4 V pack to 2.87-2.91 A at the 18.62 V threshold floor (C, section 7) |
| HR2 FC | P charger / sys | **P / sys** | ICHG, IINDPM and VINDPM cover the FC mode; the purge and budget blockers of [EVAL] 3.4 are system-level |
| HR3 loop | C | **C (conditional)** | Interlock H1/H2/C7/NOT-P5 unchanged; the CCB removes the ribbon-conductor fault rows of [WD] B.6. Conditions: SYS separate from BAT (section 2.2), so /CE HIGH holds in the `CHG_QUAL AND NOT P5` window; the single-fault-parity build of section 9.2; a hard-stop allowance that matches the chosen regen ceiling (129 us reference-biased, 108 us REGN divider, section 7.2) |
| HR4 runaway | C nominal | **C nominal** | Mode-switched ILIM divider; pin-to-current accuracy unspecified; re-sampling after qualification is P6 / S1-B6; register-defeatable through EN_EXTILIM (REG14[1]), covered by read-back only |
| HR5 fail-safe | B (stock F) | **C (design, conditional) / B** | Inhibit bias from REGN on the CCB from the first build; the "stock F" penalty no longer exists. Conditions: SYS separate (section 2.2); the hardware heartbeat (ARM_OK, [WD] r1-4) for the hung-Teensy case; the single-fault-parity build (section 9.2). Without the heartbeat, HR5 is B. B items: charger watchdog contradictions (P7, S1-B5), REGN-ordering scope check |
| H1 ground/sense | P | **P** | Section 3, M1 |
| H2 inhibit | P mech / B latency | **P / B** | Two pins; latency unspecified (section 8) |
| H3 fail-safe | B (stock F) | **C** | Section 5 |
| H4 threshold | P range / B warm | **P / B** | VINDPM 3.6-22 V; draw and warm response bench |
| H5 FC | P | **P (CV note)** | ICHG and termination P. CV upper error +0.65 % exceeds the H5 "+-0.5 % or better" wording by 0.15 % (12.6 mV); the pack terminates at 8.34-8.42 V through D-BT-SQ ([EVAL] 3.4) |
| H6 ratings | P (30 V abs, OVP 25.2 V) | **P with the eFuse; M2 c** | Section 3, M2 |
| H7 D-BT-SQ | B (2.5 V hold, BATOVP) | **B** | Architectural: DS §7.3.6 p.33 items 1-2 (panel P1, P2); unchanged by the CCB |
| H8 inrush | C 0.84 A (B scope) | **C 0.46-0.57 A** | eFuse dVdT on the CCB (section 12.3) |
| H9 I2C/logic | P | **P (U unpowered pins)** | No EVM pull-ups to remove; the MB 3V3 pull-ups are the only ones |
| H10 thermal/mech | B | **B** | Heat path in CCB copper; B8 thermal on the CCB |
| H11 stock | P (TI 162 EVMs) | **P (TI 415 146 ICs)** | Section 13 |
| H12 telemetry | P (no accuracy) | **P / U accuracy** | Section 10 |

---

## 5. Hard inhibit and fail-safe

### 5.1 Inhibit mechanisms

| Mechanism | Stops | Default with the Teensy absent (CCB bias) | What its exit re-runs | Latency in [DS] |
|---|---|---|---|---|
| **ILIM_HIZ < 0.75 V** (VIL 0.75 V, VIH 1 V) | Switching in forward and OTG modes; REGN stays on | Held LOW by an NMOS whose gate is pulled to REGN; released only by the logic (`ILIM_REL`) | "The charger resumes switching if the ILIM_HIZ pin voltage becomes higher than 1V." No qualification, D+/D- or VINDPM re-measure is stated | Not given (B: S1-B3, S1-B4) |
| **/CE HIGH** (VIH 1.3 V, VIL 0.4 V, no internal pull) | Charging in every phase; the converter keeps regulating SYS | Pulled to REGN; the open-drain driver pulls LOW only when armed (P5 AND NOT trip) | Re-enables the charge cycle; no stated soft-start. With no battery at BAT the IC holds BAT near 2.5 V while /CE is HIGH (panel P1) | Pin-to-current latency not given (U). Figs 8-6/8-7 trigger on IBAT and show VBUS, SW2, SW1 and IBAT only, with no /CE trace. After the trigger, IBAT rises in about 0.3 ms (enable) and falls over about 1 ms (disable) (figure reading, typical, 1.5 MHz / 1 uH boost mode, VBUS 5 V, VBAT 8 V, ICHG 1 A) |
| EN_CHG = 0 (REG0F[5]) | As /CE | POR 1; reset to 1 by WATCHDOG unless STOP_WD_CHG = 1 | As /CE | Not given |
| EN_HIZ = 1 (REG0F[2]) | Converter and REGN off | POR 0; auto-cleared at plug-in | **Poor-source qualification**, and an ICO restart if EN_ICO = 1 (POR 0); never used per burst | Not given |
| TS out of window | Charge suspend | Set by the REGN-TS-NTC divider; TS_IGNORE (reset by WD) defeats it | Charge resumes in the JEITA state | Not given |
| QON low for tRST | System power reset, sets HIZ while VBUS is high | Internal pull-up | HIZ exit | Not used |
| VBUS_OVP (25.2-26.2 V) | Switching | Fixed | Auto-restart below 24.0-24.8 V | Not given |

Sources: DS Table 5-1 pp.4-5, §7.3.4.3 p.27, §7.3.6 p.33, §7.3.6.5 p.35, EC pp.9 and 16, Fig 8-6/8-7 p.136; [R2] §2.2.

The per-burst gate is ILIM_HIZ, driven by `ILIM_REL = GATE OR (CHG_QUAL AND NOT P5)`. /CE is the static arm, driven by
P5 AND NOT trip ([EVAL] 4.1). This allocation follows panel P1: /CE-per-burst holds BAT near 2.5 V behind D-BT-SQ, below the
RT1987 UVLO, so every burst could pay tD_ON 8 ms ([EVAL] 0.3 P1).

### 5.2 How HR5 is made fail-safe on the CCB

| Fault state | /CE | ILIM_HIZ | Result |
|---|---|---|---|
| Teensy unpowered or in reset (pins high-Z; external P5/QUAL 47 kOhm pull-downs and RT1987 EN 10 kOhm pull-downs, [EVAL] 2.7) | Driver output off -> pull-up to REGN -> HIGH | Release driver off -> hold-down NMOS gate at REGN -> pin LOW | No switching, no charge. The RT1987 EN pull-downs also leave VCHG-IN unpowered ([R2] §2.3(a)) |
| Teensy hung with pins latched HIGH | Static arm may stay LOW; the hardware heartbeat monostable (U113, ARM_OK) is ANDed into the /CE drive and forces /CE HIGH within 30-40 ms ([WD] r1-4) | H1/C7 hold ILIM_HIZ LOW outside GATE, but H2 uses FCC_net, which a Teensy pin drives, so inside an FC window GATE and P5 can stay HIGH. ARM_OK, ANDed into the release, holds ILIM_HIZ LOW within 30-40 ms | Charge stops within 30-40 ms through the heartbeat path, not through H1/H2/C7. The charger watchdog is a second tier only (P7); the MCU hardware watchdog is required ([EVAL] 5.1) |
| I2C dead | As hung; if I2C never worked since POR the configuration is unverified and P5 stays LOW | Held | No charge |
| Charger POR (VCHG-IN collapse and return) | Pull-up to REGN; REGN returns about 150 ms after VBUS_PRESENT | Hold-down gate pulled to REGN | The IC charges by itself at 1 A out of POR (EN_CHG 1, ICHG 1 A, DS §7.3.9.1 p.41, Table 7-2 p.25) only if both pins are released. P5 stays LOW until the full image is re-verified ([WD] FR-30) |
| CCB 3V3 lost | Open-drain outputs float; /CE pulled to REGN | Hold-down gate pulled to REGN | Inhibit ([WD] B.6, 3V3-lost row) |

REGN ordering: before REGN exists both pins read 0 V, so /CE is nominally "enabled". The converter cannot switch without
REGN (DS §7.3.4.1 p.26), and switching starts only after poor-source qualification, D+/D- detection and a further 30 ms
(DS §7.3.4 steps 5-8 p.26). When REGN rises, /CE and the hold-down gate rise with it. The window is therefore closed by
sequence, not by a specified timing margin: C, with a scope check of /CE, ILIM_HIZ and SW1 at the first VCHG-IN application
(test T-C-05 class, [WD] I).

No non-volatile state exists: every register returns to its default at POR (DS §7.4.1 p.55-56; [R2] §2.3(d)). The
fail-safe therefore rests on the two REGN-biased pins, the external pull-downs and the hardware heartbeat, and the CCB fits
them from the first build. HR5 is **C** by design under three conditions: SYS is separate from BAT (section 2.2); the
heartbeat (ARM_OK) path of the system core is fitted; and the build is the single-fault-parity build of section 9.2 (the
minimal 9-part build has no single-fault-redundant release). Without the heartbeat, the hung-Teensy row is not covered and
HR5 is **B**. HR5 also stays **B** for the charger watchdog, which [EVAL] 0.3 P7 does not credit until S1-B5 reads back
EN_CHG, VREG and ICHG after an expiry.

---

## 6. Input-voltage regulation and POR behaviour

| Item | Value | Source |
|---|---|---|
| Range, step | 3.6-22 V, 100 mV | DS EC p.12; Table 7-17 p.62 |
| Accuracy | +-2 % at 18.6 V; +-3 % at 10.6 V; +-5 % at 4.3 V (only these three points) | DS EC p.12 |
| Regen setting 19.0 V | 18.62-19.38 V | [R2] §2.4 |
| FC setting 13.5 V | about 13.14-13.86 V (+-2.6 % interpolated) | [EVAL] 3.4 |
| POR value | Register POR 3.6 V; at each plug-in the IC writes VBUS0 - 1.4 V (VBUS0 >= 7 V) or VBUS0 - 0.7 V (VBUS0 < 7 V), VBUS0 measured at no load right after D+/D- detection | DS §7.3.4.4 p.27 |
| What overwrites a host value | Documented: adapter plug-in, FORCE_VINDPM_DET = 1, EN_MPPT = 1; not REG_RST, not the watchdog. The plug-in definition (VBUS above VBUS_UVLOZ after a fall below VBUS_PRESENTZ 3.1-3.3 V) is an inference; Table 7-17 defines no unplug threshold. Not excluded: any re-qualification (the automatic retry after VBUS_OVP clears, the 7-minute poor-source retry, a host EN_HIZ = 0 retry). The power-up sequence updates VINDPM and the ILIM clamp at each good-source qualification, and [DS] does not state whether these retries re-measure VBUS0 (B: S1-B2) | DS §7.3.4 step 6 p.26, §7.3.4.2 p.27, §7.3.4.4 p.27, §7.4.2 p.56, Table 7-17 p.62, EC p.9; [R2] §2.4 |
| Autonomous charging at POR | Yes: EN_CHG 1, ICHG 1 A, IINDPM 3 A (or the ILIM clamp), VINDPM VBUS0 - 1.4 V; blocked only by the /CE and ILIM_HIZ hardware | DS §7.3.9.1 p.41, Table 7-2 p.25; [R2] §2.3(d) |

At a normal bus (VBUS0 15.9 V) the auto value is 14.5 V, above the pack. In the low-input states of [CRIT] section 4.5
(body-diode passthrough, bring-up P0) VBUS0 lies near 7-8 V and the auto value falls to about 5.6-6.6 V (6.3 V just below
the 7 V step), below the 7.4-8.4 V pack. As a buck-boost the IC can then charge in boost mode from a bus below the pack. This is why S16 scores 0 in section 16:
the hardware holds and the interlock, not physics, stop the passthrough circulation.

The CCB changes nothing in this section. The Run-entry write of VINDPM after PG_STAT and the readback before P5 rises
([EVAL] 4.4, invariant I-3) remain.

---

## 7. Hardware input-current ceiling after POR (HR4)

### 7.1 Mechanism

VILIM_HIZ = 1 V + 0.8 Ohm x ILIM (DS Eq.1 p.27). The ADC reads the pin after PG_STAT at each qualification (DS §7.3.4 step 6
p.26) and clamps IINDPM; a reading below 1.08 V gives a 100 mA clamp. The pin table states that the input current limit is
"the lower setting of ILIM_HIZ pin and the IINDPM register" (DS Table 5-1 p.5). Whether the pin is also followed
continuously is the P6 contradiction ([EVAL] 0.3), bench S1-B6. ILIM_HIZ leakage is +-1.5 uA (DS EC p.12). No accuracy is
given for the pin-to-current conversion; the nearest specification is IINDPM_ACC at VBUS 9 V: 880-1000 mA at 1 A,
1800-1960 mA at 2 A (DS EC p.12).

### 7.2 CCB divider and bands (C)

On the CCB the divider is a direct REGN-referenced network, not the EVM rework of [WD] B.6 (which gave regen 1.33-1.76 A and
FC 0.65-0.95 A). Inputs: REGN 4.8-5.2 V (DS EC p.15), 1 % resistors, leakage +-1.5 uA through the divider Thevenin
resistance, Eq.1.

| Mode | Network | Pin voltage nominal | Ceiling band |
|---|---|---|---|
| Regen | R_T 54.9 kOhm (REGN -> pin, via the release feed) / R_B 46.4 kOhm | 2.290 V | **1.42-1.81 A** (nominal 1.61 A) |
| FC (R_FC switched in by FCC_net) | R_T 54.9 k / (R_B 46.4 k parallel R_FC 69.8 k) | 1.684 V | **0.71-1.00 A** (nominal 0.86 A) |

Consequences:

1. **FC bound after a charger POR:** <= 1.003 A + 0.15 A aux = 1.15 A at standstill, below the 1.20 A firmware arm drop,
   the 1.247 A H-20 P_MAX and the 1.4 A OC_FC latch (**C nominal**: ideal Eq.1, no pin-to-current accuracy). The 0.047 A
   margin to the arm drop is smaller than any plausible conversion error and stays unverified until S1-B6. [EVAL] 3.4 used
   the 0.74-0.96 A band; the 1 % REGN-referenced CCB divider widens it to 0.709-1.003 A. Keep the [EVAL] FC band, or bias
   both legs from the reference option of item 3. The ceiling holds after POR (EN_EXTILIM POR 1) but is register-defeatable
   through REG14[1]; only read-back covers a register corruption ([EVAL] 2.7, REG14 bit-slip row). After an IINDPM
   register loss (REG_RST, a stray REG06 write or EN_EXTILIM = 0; the watchdog does not reset REG06, DS Table 7-18 p.63)
   the FC bound is 1.15 A only if the pin is re-sampled after qualification (P6, S1-B6). If the pin is sampled once, the
   regen clamp latched at the Run-entry qualification persists through FC windows ([EVAL] 4.1): 1.55-1.61 A (item 3) +
   0.15 A aux = 1.70-1.76 A, above the arm drop by 0.56 A and the 1.4 A OC_FC latch by 0.36 A (C nominal; up to 1.96 A
   with the REGN divider). DS §7.3.4.3 p.27 describes only the held-clamp behaviour.
2. **Regen ceiling against the hard-stop allowance:** the band maximum 1.81 A exceeds the 1.72 A row of [EVAL] 2.5 (117 us
   allowance). The [EVAL] 2.5 rows correspond to a fixed V-MOT margin of (117 + 59) us x 4.30 V/ms = 0.757 V at VBUS 15.9 V
   (0.791 V at 16.39 V), with deductions of 24 + 15 + 20 = 59 us. At 1.807 A on 0.4 mF the slew is 4.52 V/ms, so the
   allowance is 0.757 / 4.52 - 59 = **108 us** at VBUS 15.9 V and 116 us at 16.39 V (C). This is below the S1-B3 pass value
   of 115 us, so the REGN divider requires S1-B3 at <= 108 us. The REGN tolerance (+-4 %) dominates the band width, so a REGN-referenced divider cannot hold both a minimum
   >= 1.54 A (section 11) and a maximum <= 1.72 A: the span from REGN alone is about 0.23 A.
3. **Reference-biased option:** a 2.5 V shunt reference fed from REGN, 0.1 % resistors and a 5 kOhm Thevenin narrow the
   regen band to about 1.55-1.61 A (+-0.5 % reference, +-0.3 % ratio, +-7.5 mV leakage term; C, nominal Eq.1 only). Cost: one
   reference and one feed resistor. A single open fault of the reference raises the pin toward REGN and the ceiling to the
   IINDPM maximum 3.3 A, which is the same failure class as an open R_B in the REGN divider. The pin-to-current conversion
   accuracy stays unspecified (B: S1-B6 calibration). At the 1.61 A maximum the slew is 4.03 V/ms and the hard-stop
   allowance is 0.757 / 4.03 - 59 = **129 us** (C), so S1-B3 at 115 us covers this option with margin. **This dossier takes
   the reference-biased ceiling as the baseline**; the REGN divider remains an option only with S1-B3 at <= 108 us.

### 7.3 Input power at the threshold (HR1 pass condition >= 23 W)

At the 18.62 V threshold floor, with ideal Eq.1: 1.42 A x 18.62 V = **26.5 W** (REGN divider minimum); 1.33 A x 18.62 V =
24.8 W ([WD] B.6 minimum). If the pin conversion carried an IINDPM-class -10 % error (applicability UNVERIFIED), the REGN
divider minimum would give 23.8 W. Every case meets 23 W (C, nominal conversion).

---

## 8. Warm response and HIZ-exit timing

| Requirement ([EVAL] 3.2, 2.5) | [DS] evidence | Status |
|---|---|---|
| tau_warm <= 4 ms (10-90 % <= 9 ms; <= 2 ms at board-only capacitance), step Vth - 0.5 V to Vth + 1 V | No VINDPM loop bandwidth or step response. Fig 8-16 (IINDPM transient, p.138) settles in about 0.1-0.2 ms ([R2] figure reading, typical). The converter stays enabled in VINDPM regulation (regulation loop, DS §7.3.4.4) | B (S1-B4) |
| No deglitch, POR or soft-start at the Vth crossing | VINDPM is a loop; no stated re-qualification on a dip above VBUS_PRESENTZ 3.1-3.3 V | B (S1-B2, S1-B4) |
| ILIM_HIZ exit + warm within the head start | "Resumes switching" above 1 V; no stated deglitch; no pin-to-current latency in [DS] (U). Fig 8-6 triggers on IBAT and shows no /CE trace; after the trigger IBAT rises in about 0.3 ms (figure reading, typical, 1.5 MHz / 1 uH boost mode, VBUS 5 V) | B (S1-B4 release case) |
| Hard stop <= about 115 us after H1 trips (<= 108 us with the REGN-divider regen ceiling, section 7.2) | ILIM_HIZ stop latency not given. The /CE pin-to-current latency is not given either (U): Fig 8-7 triggers on IBAT, shows no /CE trace, and IBAT falls over about 1 ms after the trigger (figure reading, typical, 1.5 MHz boost mode, ICHG 1 A). The per-burst gate is allocated to ILIM_HIZ on this U/B status and on panel P1, not on a measured /CE latency | B (S1-B3) |
| Cold start never used | REGN 150 ms after VBUS_PRESENT + poor source about 30 ms (DS §7.3.4 p.26) + D+/D- 0.5-2 s if enabled (DS §7.3.4.5 p.28) + 30 ms (DS §7.3.4 p.26) | P: always-powered design mandatory |

The CCB does not change the IC evidence. It changes two board terms of the warm-response budget:

1. **Gate RC:** [EVAL] 2.5 deducts 20 us for the gate RC of the EIB stages (1 kOhm / 10 nF filters against ribbon
   coupling, [WD] B.6). On the CCB the hold-down gate is a short trace; the RC can be cut to the value the layout needs.
   With the 20 us deduction kept, the allowance at the chosen regen ceiling is 129 us (reference-biased, 1.61 A maximum)
   or 108 us (REGN divider, 1.81 A maximum) at VBUS 15.9 V (section 7.2, C). Each microsecond removed from the gate RC adds
   one microsecond to the allowance; recompute once the layout fixes the RC.
2. **Capacitance on V-MOT:** the CCB input ceramics sit on VCHG-IN, behind D-BC-RG; they do not add to C(V-MOT), and the
   tau table of [EVAL] 3.2 is unchanged.

The D-BT-SQ UVLO drop-out between bursts ([R2] §1.2 item 3; [WD] B.5) is architectural and unchanged: VCHG decays below the
RT1987 UVLO in 0.17-0.78 s in cruise and the next burst pays tD_ON 8 ms + tON about 1.9 ms ([RT] p.7, §17.1). The keep-alive
of [WD] B.5 (TPS22810, BAT54, 680 Ohm, DNP) moves onto the CCB as a DNP option; T-B-09 decides it.

---

## 9. Interlock hardware around the IC

### 9.1 Functions required and how the BQ25798 meets them

| Function ([CRIT] 3.3, [EVAL] 2.6) | BQ25798 pin or feature | IC-specific adder on the CCB |
|---|---|---|
| Per-burst hardware converter-off from GATE | ILIM_HIZ < 0.75 V | Hold-down NMOS (gate pulled to REGN), one open-drain channel to release its gate, the release feed (PMOS from REGN, or the R_T path) |
| Static arm, fail-safe | /CE | Pull-up to REGN, one open-drain channel |
| `CHG_QUAL AND NOT P5` (qualification read sees the divider, not 100 mA) | Needed because the ADC samples ILIM_HIZ at qualification (§7.3.4.3) | One inverter and one AND gate |
| Mode-switched hardware ceiling keyed to FCC_net | ILIM_HIZ divider | One NMOS, one resistor (R_FC), one gate pull-up to REGN |
| eFuse on VCHG-IN | - | System core (not counted) |
| REGN-biased pull-ups | REGN 4.8-5.2 V, IREGN 30 mA minimum. [DS] names only ILIM_HIZ, TS and STAT as REGN pull-up rails and adds: "Except the charger related pull up rails, the REGN is not recommended to source any other external circuit". The /CE pull-up and the two NMOS gate pull-ups are treated as charger-related rails; this is an interpretation, not a datasheet permission. Added load: IIN_BIAS_CE <= 1 uA plus gate leakage and pull-up current (uA level with 100 kOhm-class pull-ups) against 30 mA. CCB-1 confirms the behaviour | Counted with the stages above |

Sources: DS §7.3.4.1 p.26 (REGN usage), §7.3.4.3 p.27, EC p.15 (REGN), EC p.16 (IIN_BIAS_CE); [WD] B.6; [EVAL] 4.1.

### 9.2 Part count

| Build | Adder parts (packages and resistors, [CRIT] 3.3 rule) | Notes |
|---|---|---|
| 2026-11-05 EVM design | About 40: [WD] B.6 U201, U202, U203, U204, Q201-Q203, R250-R275 (about 25 resistors), plus the EVM reworks (R23, R256, R21 link) and the CR NOT-P5 gates | Includes the EIB ribbon protection (input pull-downs, series limiters, far-end sense comparators) |
| **CCB, minimal** | **9**: one triple open-drain inverter package (/CE, release, FC leg), hold-down NMOS, FC-leg NMOS, R_FC, three REGN pull-ups (/CE, two gates), inverter + AND for NOT-P5 | No single-fault-redundant release feed, no pin-level readback |
| **CCB, single-fault parity with [WD]** | **About 16**: minimal set + release PMOS and its feed and gate resistors (3) + far-end readback of /CE and ILIM_HIZ (two TLV3012B sections or two divider taps to spare Teensy pins, about 4 parts) | Keeps the [WD] B.6 single-fault table; the ribbon rows disappear |
| Optional | +2 for the reference-biased ceiling (section 7.2); +3 DNP for the keep-alive (section 8) | |

The CCB removes about 24 parts that existed only because of the ribbon and the EVM: the EIB input pull-downs R267-R270, the
series limiters R264, R265, R275, the ribbon 3V3 feed and bleed (R176, R177, R274), the EIB ground link R273, and the EVM
reworks. It adds nothing that the EVM design did not have. The count still exceeds 8 in every build, so S6 scores 0
(section 16). [SCR] section 4.1 scored the baseline S6 = 1 provisionally; that value assumed a smaller count than either
CCB build.

---

## 10. Telemetry and I2C

| Item | Value | Source |
|---|---|---|
| Address | 7-bit 0x6B; reads beyond REG48 return 0xFF; 1.5 s incomplete-transaction timeout | DS §7.3.14 p.53; [R2] §2.9 |
| Levels | VIH 1.3 V, VIL 0.4 V, VOL 0.4 V at 5 mA, IBIAS <= 1 uA; pins 6 V abs max | DS EC pp.15-16, §6.1 p.7 |
| Bus speed | Standard and fast mode. On the CCB the SDA/SCL path is a short trace to the header pins and the MB 2.7 kOhm pull-ups ([WD] G.1, PM9): 400 kHz becomes practical without the 0.30 m lead of [EVAL] 4.2 | [WD] G.1 |
| ADC channels | IBUS 0-5 A, IBAT 0-8 A, 1 mA LSB; VBUS 0-30 V, VBAT 0-20 V, VSYS 0-24 V, 1 mV LSB; TS; TDIE 0.5 °C. IBAT measures the BATFET path, so it reads the charge current only with SYS separate (section 2.2) | DS EC pp.16-17; [R2] §2.12 |
| Conversion time | 24 / 12 / 6 / 3 ms per channel at 15 / 14 / 13 / 11-bit typical (minimum 14 / 13 / 12 / 10; 3 ms "not recommended"); IBAT + IBUS + VBUS at 6 ms = 18 ms (about 55 Hz) only with all other channels disabled in ADC_Function_Disable_0/1 (all channels are enabled by default) | DS EC p.16, §7.3.10 p.47 |
| Accuracy | **Not specified** (resolution only); "valid for DC states and not for transients" | DS EC p.16, §7.3.10 p.47 |
| Watchdog | 0.5/1/2/20/40/80/160 s, POR 40 s; accuracy only at 160 s (tWDT 136 min / 160 typ s); STOP_WD_CHG behaviour B (P7) | DS §6.6 p.17 (accuracy), Table 7-26 p.72 (settings); [R2] §2.3(b) |
| STAT | Open drain, LOW = charging, 1 Hz blink = fault; 6 mA abs max sink | DS Table 5-1 p.4, §6.1 p.7 |
| INT | Open drain, 256 us active-low pulse | DS Table 5-1 p.5 |

The 22 pads carry no INT line ([CRIT] section 1.1). INT can reach a spare Teensy pin only through a CR-type tap and an IO
CSV amendment; the driver polls status instead ([EVAL] 4.5).

---

## 11. Charge capability

### 11.1 Ratings

ICHG 0.05-5 A in 10 mA steps (DS EC p.11); ROC fast-charge current 5 A, ISW 5 A, IVBUS 3.3 A (DS §6.3 p.7). Buck-mode
ICHG accuracy is given only at 0.5-2 A (2 A: -6.5/+3.5 %, VBAT 8 V, DS EC p.11).

### 11.2 Charge at 3.1 A: efficiency and loss

Efficiency at VBAT 8 V, figure reading, typical (DS Fig 6-3 750 kHz / 2.2 uH, Fig 6-4 1.5 MHz / 1 uH, p.18): at 3.1 A about
92.5 % (20 V) and 94 % (15 V) at 750 kHz; about 91 % (20 V) and 93 % (15 V) at 1.5 MHz.

| Point | Output | Loss, 750 kHz | Loss, 1.5 MHz |
|---|---|---|---|
| 3.1 A into 7.4 V, 20 V input | 22.94 W | 1.86 W | 2.27 W |
| 3.1 A into 8.4 V, 20 V input | 26.04 W | 2.11 W | 2.58 W |
| 3.1 A into 8.4 V, 15 V input | 26.04 W | 1.66 W | 1.96 W |

The 3.1 A point occurs only in regen bursts of <= 0.6 s ([EVAL] 3.2); sustained FC charging is <= 1.9 A (section 11.4) at
about 1 W. 750 kHz keeps the regen burst loss within 0.11 W of the 2 W class; 1.5 MHz exceeds it by 0.58 W. The figure
includes the 2.2 uH WE-LHMI 74437346022 used by TI for Fig 6-3 (DS p.18 header).

### 11.3 Regen: charge at the threshold

At the 18.62 V threshold floor, 750 kHz, nominal Eq.1 (calculation in section 7):

| Pack | ICHG 3.1 A demand (input) | Delivered with the CCB REGN divider (ceiling minimum 1.42 A = 26.5 W) | With an IINDPM-class -10 % pin error (UNVERIFIED applicability) |
|---|---|---|---|
| 7.4 V | 24.8 W | **3.10 A** (ICHG-limited) | 2.98 A |
| 8.4 V | 28.2 W | **2.91 A** (ceiling-limited) | 2.62 A |

A guaranteed 3.1 A at an 8.4 V pack and the threshold floor needs a ceiling minimum of 1.51 A (92.5 %) or 1.54 A (91 %).
The reference-biased ceiling of section 7.2 (1.55-1.61 A) meets it and keeps the hard-stop allowance at 129 us (section 7.2). Input at the
threshold is >= 23 W in every case (section 7.3). The ICHG register cap of the 2026-11-05 image (2.50 A, [EVAL] 3.3) is no
longer the binding limit at 7.4 V. The pack's maximum charge current still waits on the pack datasheet ([EVAL] 8.1 item 6).

The table above takes ICHG at its nominal value. Buck ICHG accuracy is published only up to 2 A (section 11.1), so the low
corner at 3.10 A is an extrapolation of the 2 A row (U): 3.10 x 0.935 = 2.90 A at an 8.4 V pack, 0.20 A below the setting
(2.97 A if the -130 mA error of the 2 A row is held absolute). With the reference-biased ceiling the input-ceiling limit is
1.55 x 18.62 x 0.925 / 8.4 = 3.18 A, so ICHG binds. A setting S >= 3.10 / 0.935 = 3.316 A, that is 3.32 A in 10 mA steps,
gives 3.32 x 0.935 = 3.10 A at the low corner; min(3.10, 3.18) = 3.10 A at nominal pin conversion only (S1-B6). The high
corner is then 3.32 x 1.035 = 3.44 A, which becomes the headroom and copper basis in place of 3.21 A. With an IINDPM-class
-10 % pin error on the 1.55 A floor the input-ceiling limit is 1.395 x 18.62 x 0.925 / 8.4 = 2.86 A (B).

HR1 input on the charge-limited basis (the lower of the input-ceiling limit and the charge-current limit), 7.4 V pack:
3.1 x 7.4 / 0.925 = 24.8 W (+7.8 % over 23 W) at the nominal ICHG; 3.1 x 0.935 x 7.4 / 0.925 = 23.2 W (+0.8 %) at the
extrapolated low corner (U). The input-ceiling capability is 1.55 x 18.62 = 28.9 W.

### 11.4 FC mode within the 1.0 A bus budget

| FC ceiling (CCB divider) | Charge at 8.4 V | Charge at 7.4 V |
|---|---|---|
| 0.71 A (minimum) | 1.24 A | 1.40 A |
| 0.86 A (nominal) | 1.50 A | 1.70 A |
| 1.00 A (maximum) | 1.75 A | 1.98 A |

Inputs: 15.6 V loaded bus ([CRIT] 4.4), 94 % efficiency (Fig 6-3 at about 1.5 A, 15 V, figure reading, typical). In cruise
the governor writes IINDPM = min(0.90, 1.20 - I_aux - I_traction,filt - 0.10) A ([EVAL] 3.4), so the ceiling is a POR bound,
not the operating point. The purge ruling of 2026-11-08 (no FC charging during or just before a purge, preemptive share
shift, EMS-requested windows between purges) is a firmware and EMS rule; the BQ25798 supports it through P5 (/CE static arm)
and the H2 permit, and the window-close path is the same as on 2026-11-05.

---

## 12. Layout, package, thermal, BOM

### 12.1 Layout

The datasheet gives a priority-ordered list (DS §8.4.1 p.139) and an example (Fig 8-21 p.140):

1. 0.1 uF 0402/0201 capacitors on the IC layer, on top of the PMID-GND and SYS-GND pins, with at least one 10 uF bulk in
   parallel; the remaining bulk with low-impedance connections.
2. SW1 and SW2 leave through multiple vias under the IC to an inner or bottom layer; minimum copper area; BTST capacitors
   on vias.
3. REGN capacitor close, at least 2 ground vias to the internal ground plane.
4. VBUS 0.1 uF close; ground through at least 2 vias.
5. BAT capacitors close; via count sized for the current; BATP and TS routed away from SW1/SW2.

The EVM is 4-layer with separate AGND and PGND joined at the IC; TI states that two grounds are not required (UG §3 p.14,
item 7). Consequences for the CCB:

- **4 layers are required** in practice: the SW1/SW2 escape under the IC and the ground-plane via rule need an inner layer.
  The CR was already 4-layer, 2 oz outer ([WD] E), so this adds no new process.
- **Two hot loops** (PMID-Q1-Q2-GND in buck mode and SYS-Q3-Q4-GND in boost mode) are inside the IC; the external loops are
  the PMID and SYS 0.1 uF placements. This is the integrated-buck-boost case of [CRIT] S10 (score 1).
- **0.4 mm pitch, 29 pads, no exposed pad** (DS p.148-149): fine-pitch stencil and reflow; inspection by X-ray or
  cross-section is advisable for the first build. The CCB assembly can include reflow ([CRIT] 1.1).
- The switching node must stay away from the comparator inputs (H1 dividers with 0.1 % resistors and up to 10 MOhm,
  [WD] E). Place the power stage on the CCB extension, away from the CR comparator field, with the ground plane unbroken
  between them; R6 test-registry checks for ground shift and coupling still apply ([CRIT] 1.2, EVAL 6.4 trigger 5).

### 12.2 Thermal

RthetaJA 44.2 °C/W, RthetaJB 9.7 °C/W, PsiJB 9.7 °C/W (JEDEC, DS §6.4 p.8). TREG default 120 °C; TSHUT 150 °C (DS EC
p.13). Sustained FC charging at about 1.0 W gives a JEDEC-board rise of about 44 °C; a 0.6 s regen burst at 2.1 W is limited
by thermal capacitance, not RthetaJA. The CCB sits raised on headers above the MB, near the LM1084 heat source ([R2] §2.10);
the heat path is CCB copper only. Bench gate B8 (sustained FC charge, TDIE REG41 and TREG_STAT) moves to the CCB.

### 12.3 Input capacitance and inrush

[DS] minimum effective capacitance: CVBUS 2 uF, CPMID 4 uF (no backup), CSYS 6 uF, CBAT 3 uF (DS §6.3 p.8). [DS] suggests
2 x 10 uF + 0.1 uF at VBUS and 3 x 10 uF + 0.1 uF at PMID for a 3.3 A input limit, rated 25 V or more for a 20 V input
(DS Table 5-1 p.6, PMID row; §8.2.2.3 p.134). On the CCB these are 50 V X7R 1206 parts from the first build (closes [R2] M7).

| Configuration | Capacitance on the RT1987-ramped node (12 mA/uF) | Peak, with 0.15 A aux |
|---|---|---|
| IC directly on VCHG-IN, [DS]-suggested 50.2 uF + MB C-D8/C-D10 20 uF | 70.2 uF | 0.84 + 0.15 = **0.99 A** (1 % margin) |
| IC directly, reduced: VBUS 1 x 4.7 uF, PMID 2 x 10 uF, 2 x 0.1 uF + MB 20 uF | 44.9 uF | 0.54 + 0.15 = **0.69 A** |
| **eFuse on the CCB** (baseline): MB 20 uF + eFuse IN 5.8 uF ([WD] B.4) on the ramp; IC ceramics charged by the eFuse dVdT (0.11 A, [WD] B.4) | 25.8 uF | 0.31 + 0.11 + 0.15 = **0.57 A** worst overlap (43 % margin) |

Nominal capacitance is used throughout; DC-bias derating lowers the real values, so the figures are upper bounds (C).

### 12.4 BOM estimate (charger IC and power stage only; system core excluded)

| Item | Qty | Note | Cost basis |
|---|---|---|---|
| BQ25798RQMR | 1 | | USD 5.038 (1-99, [TIstore]) |
| Inductor 2.2 uH, Isat >= 6 A | 1 | Peak at 3.21 A: 4.38 A (15.6 V), 4.63 A (19 V), 4.80 A (22.28 V) at 750 kHz (calc from DS §8.2.2.2 Eq.5); TI used WE-LHMI 74437346022 (DS p.18; ratings UNVERIFIED) | allowance USD 1.5 |
| 10 uF 50 V X7R 1206 (VBUS 2, PMID 3) | 5 | | allowance USD 0.3 each |
| 10 uF 25 V X7R (SYS 5, BAT 2) | 7 | SYS abs max 23 V, BAT 20 V (DS §6.1) | allowance USD 0.15 each |
| 0.1 uF (VBUS, PMID, SYS), 47 nF x 2 (BTST), 4.7 uF 10 V (REGN), 1 nF 50 V (SDRV) | 7 | | allowance USD 0.5 total |
| PROG 8.2 k, TS 2 R, BATP 100 Ohm, ILIM divider 2-3 R | 6-7 | | allowance USD 0.3 total |
| **Total** | **27-28 parts** | | **about USD 10-12 per board** (IC price P; the rest allowances, UNVERIFIED) |

The IC-specific interlock adders (section 9.2) add 9-16 small parts at about USD 2-4.

---

## 13. Stock and price

| Item | Value | Source, date |
|---|---|---|
| BQ25798RQMR stock | **415 146** | [TIstore] opninventory, 2026-11-10 18:27 UTC |
| BQ25798RQMR price | USD 5.038 (1-99), 4.107 (100-249), 3.229 (250-999), 2.738 (1k) | [TIstore] product page tiered-price JSON, 2026-11-10 |
| BQ25798EVM stock (reference only) | 161; USD 156.45 | [TIstore], 2026-11-10 |
| Second source (Mouser, DigiKey) | UNKNOWN | Mouser returned a 13.9 kB page with no stock field (bot wall); DigiKey HTTP 403 (section 15.3) |
| Lifecycle | Active | DS p.145 |

---

## 14. Round-6 findings

| # | Key ([R6]) | Effect of the CCB on the BQ25798 design | Class ([CRIT] 3.4) |
|---|---|---|---|
| 1 | vreg-corruption-no-fixed-pack-ovp | **Kept, and more serious than the 2026-11-05 wording implies.** VREG is bounded to 5-9.99 V only while the host-writable CELL field (REG0x0A[7:6]) reads 2s. One errant CELL write resets VREG to the 3s or 4s default (12.6 V or 16.8 V) and allows up to 18.8 V. A later REG_RST or watchdog expiry keeps the new cell count "regardless of the state of the PROG pin", so the state survives until POR; PROG applies the 2s bound only at POR (DS §7.3.2 and Table 7-2 pp.25-26). VBAT_OVP is 103-105 % of VREG and follows it (EC p.12). Add CELL to the read-back image (I-3 / FR-30 / FR-46 class). The OVN term from the BQ29200 OUT stays the only fixed pack-OV backstop | IC-dependent, kept |
| 2 | dbtsq-short-unfused-pack-on-vchg | Unchanged (D-BT-SQ on the MB); detection FR-48 unchanged | System |
| 3 | cr-and-mb-battery-path-copper-sized-below-ichg | Reopens as a CCB copper-sizing task at 3.21 A (every candidate) | Not counted |
| 4 | tc04-in-spike-criterion-omits-mb-vchgin-ratings | Unchanged: the eFuse IN spike and the MB-end limits move with the eFuse onto the CCB | System |
| 5 | imon-bypass-cap-against-datasheet | Unchanged (eFuse IMON, no bypass capacitor) | System |
| 6 | fcc-rgn-lvc-threshold-vs-rt1987-en-band | Unchanged | System |
| 7 | pin38-39-adc-overvoltage-on-vmot-excursion | Unchanged | System |
| 8 | loop-budget-5ms-breaks-1ms-tick-deadlines | **Kept, eased.** The I2C write and read-back burden is IC-intrinsic (same register image). The CCB makes 400 kHz practical (short traces), which shortens each transaction by up to 4x; the 5 ms budget mechanism is unchanged | IC-dependent, kept |
| 9 | purge-fc-only-ridethrough-bag-evidence-reopen | Unchanged | System |
| 10 | chg-src-misattributes-subh1-regen-reopen | **Kept.** No ADC accuracy in [DS]; the learned offset and slope of FR-20/FR-22 remain | IC-dependent, kept |
| 11 | ff-headroom-admission-contradicts-single-g-test | Unchanged | System |
| 12 | ff-reversal-hold-unattainable-at-100khz | **Kept, eased** by 400 kHz on short traces, as finding 8 | IC-dependent, kept |
| 13 | cr-coordinate-convention-mirror-ambiguity | Closed by any single CCB (re-check in the new layout) | Not counted |
| 14 | eib-e-lead-max-lengths-geometrically-infeasible | Closed (no EIB, no leads) | Not counted |
| 15 | t-a-05-stale-j101-region-dims | Closed (no J101 ribbon header) | Not counted |
| 16 | a6-w2-not-beside-star-pads | Closed (no W2 lead) | Not counted |

Net for the IC-dependent findings: 0 closed, 0 reopened (S14 = 2). The CCB closes the four geometry findings 13-16 for the
BQ25798 as for any candidate.

---

## 15. Open questions, bench gates and blocked fetches

### 15.1 Open questions

1. **M2 reading** ([SCR] 5.2): the IC is 30 V-rated; this dossier relies on the eFuse OVP as the 35 V element.
   The OVP response time is closed: OVP_tOFF(dly) 8.5/11/14 us, SLVSE94G section 6.6 p.8; URL confirmed (section 3).
   The output overshoot during the turn-off delay remains a bench item.
2. **Regen ceiling design** (section 7.2): the dossier baseline is the reference-biased divider (two more parts, band about
   1.55-1.61 A, hard-stop allowance 129 us). The REGN divider (band 1.42-1.81 A) is an option only with S1-B3 tightened to
   <= 108 us. Operator ruling required.
3. **ICHG for regen**: 3.1 A needs the pack's maximum charge current ([EVAL] 8.1 item 6).
4. **Minimum on-time:** closed. NVDC SYS regulation bounds the buck duty at >= 0.32 (section 2.1), provided SYS is
   separate from BAT.
5. **Unused D+/D- termination** on the CCB: [DS] does not state it; TODO(verify: TI E2E or SLUUCB5E schematic for the
   recommended unused-pin treatment). AUTO_INDET_EN = 0 is written after the first qualification ([EVAL] 4.5, no-M8
   sequence).
6. **Inductor**: part selection, Isat >= 6 A and DCR, against a datasheet (WE-LHMI 74437346022 or equivalent).
7. **M2 rule** (section 3, note): the main document must apply one rule to every part.
8. **CELL field corruption** (section 14, finding 1): add CELL to the read-back image.

### 15.2 Bench gates (carried; CCB-specific changes in bold)

| Gate | Purpose | Change on the CCB |
|---|---|---|
| S1-0b | First qualification with VAC_OVP at POR | VAC1/VAC2 tied to VBUS by design, ACDRV grounded; unchanged |
| S1-B1 | Draw at bus voltage <= 5 mA | Unchanged; standby draw 3.5-5.0 mA from the bus ([WD] B.5, H.15) |
| S1-B2 | VINDPM retention | **Extended to the re-qualification paths: VBUS_OVP recovery, poor-source retry and EN_HIZ exit (section 6)** |
| S1-B3 | Hard-stop latency <= 115 us | **<= 115 us with the reference-biased ceiling, <= 108 us with the REGN divider (section 7.2); gate RC recomputed for the CCB. Also: set EN_EXTILIM = 0 and confirm that ILIM_HIZ < 0.75 V still stops switching (section 3, M5)** |
| S1-B4/B4r | Warm response and release | Unchanged |
| S1-B5 | Charger watchdog read-back | Unchanged |
| S1-B6 | ILIM_HIZ re-sampling; pin-conversion calibration | **Also calibrates the chosen CCB divider** |
| S1-B7 | D-BT-SQ burst entry | Unchanged; keep-alive DNP on the CCB |
| B8 | Thermal | **On the CCB, raised above the MB** |
| B9 | ADC accuracy | Unchanged |
| **New: CCB-1** | First power: scope /CE, ILIM_HIZ, REGN and SW1 at the first VCHG-IN application. Confirm that SYS and BAT are not joined: with /CE HIGH and ILIM_HIZ released, the current into VCHG is zero | Proves the REGN-ordering closure of section 5.2 and the SYS separation of section 2.2 |
| **New: CCB-2** | 3.1 A regen burst at 750 kHz: loss, TDIE, SW1 ringing | Proves M4 in the 2 W class |

### 15.3 Blocked fetches

| URL | Reason |
|---|---|
| https://www.mouser.com/c/?q=BQ25798RQMR | Returned a 13.9 kB page with no product or stock data (bot wall), 2026-11-10 |
| https://www.digikey.com/en/products/result?keywords=BQ25798RQMR | HTTP 403, 2026-11-10 |
| TPS26630 datasheet SLVSE94G (OVP response time) | Closed: OVP_tOFF(dly) 8.5/11/14 us, SLVSE94G section 6.6 p.8; URL https://www.ti.com/lit/ds/symlink/tps2663.pdf confirmed (section 3) |
| Inductor datasheets (Würth WE-LHMI 74437346022, TDK SPM6530T-1R0M120) | Not fetched; ratings UNVERIFIED |

---

## 16. Verdict and comparison with the 2026-11-05 baseline

**Verdict: FEASIBLE_W_COND.** No requirement fails on the primary datasheet. The conditions are those of [EVAL] 0.2
(conditions 1-8, 10-14), less every EVM item (mods M1-M7, M9-M11, the EIB, the off-board leads), plus five CCB items:
SYS kept as a separate capacitor-only node that reaches BAT only through the BATFET (section 2.2); the eFuse OVP as the M2
standoff under one M2 rule for every part (section 3); the reference-biased regen ceiling, or S1-B3 at <= 108 us
(section 7.2); the single-fault-parity build with the heartbeat path for HR5 (section 5.2); and the bench gates CCB-1 and
CCB-2 (section 15.2). With SYS strapped to BAT the verdict would be NOT FEASIBLE: /CE would not inhibit, and HR3 and HR5
would fail.

Score under [CRIT] section 3 with the evidence cap of section 3.2:

| Criterion (weight) | Score | Evidence | Basis |
|---|---|---|---|
| S1 warm response (15) | 1 | U/B | No documentation of exit timing or loop bandwidth |
| S2 fail-safe POR (10) | 1 | P/C | POR charges at 1 A; both inhibit pins default to inhibit when biased from REGN on the CCB ([SCR] provisional 0 assumed the stock bias) |
| S3 ceiling quality (8) | 2 | B | Switchable by one resistor and one NMOS; continuous re-sampling unknown (P6); register-defeatable through EN_EXTILIM (REG14[1]). The [CRIT] S3 bands carry no defeatability penalty; the main document must score challengers with register-defeatable ceilings by the same rule |
| S4 threshold quality (8) | 2 | B | 100 mV, +-2 % at 18.6 V; survival across the re-qualification paths not proven (section 6), carried as S1-B2 |
| S5 inhibit latency (7) | 1 | U | Not documented for either pin; Figs 8-6/8-7 give no pin-to-current latency |
| S6 interlock adders (10) | 0 | C | 9 (minimal) to about 16 (single-fault parity) |
| S7 telemetry (5) | 2 | P | IBAT, IBUS, VBUS ADC; no accuracy |
| S8 FC-mode fitness (6) | 1 | P | 10 mA IINDPM steps; CV +0.65 % misses the +-0.5 % anchor ([SCR] provisional 2) |
| S9 rating margin (4) | 0 | P | 30 V |
| S10 layout (7) | 1 | P | Integrated buck-boost |
| S11 package (3) | 1 | P | 0.4 mm-pitch QFN, multi-pad |
| S12 stock (5) | 2 | P/U | TI 415 146; second source UNKNOWN ([SCR] provisional 3) |
| S13 cost (2) | 1 | cap | About USD 10-12, but passive costs are allowances (UNVERIFIED cap); 3 uncapped |
| S14 round-6 (5) | 2 | C | Net 0 |
| S15 inrush (3) | 3 | C | 0.57 A worst overlap with the CCB eFuse |
| S16 topology barrier (2) | 0 | P | Buck-boost; auto-VINDPM falls below the pack at a 7-8 V bus (section 6) ([SCR] provisional 1) |
| **Weighted total** | **about 40** | | Uncapped sensitivity (S8 2, S12 3, S13 3, S16 1): about 46. Valid only with SYS separate and under one M2 rule (section 3) |

**Comparison with the 2026-11-05 baseline.** On the CCB the BQ25798 keeps every IC-intrinsic strength that made it the
2026-11-05 choice: a host-written VINDPM that survives REG_RST and the watchdog (survival across re-qualification is
still B, S1-B2), a 22 V VINDPM range,
two hardware inhibit pins with REGN available for fail-safe bias, 1 mA / 1 mV telemetry, and very large single-source stock.
It also keeps every IC-intrinsic weakness: a 30 V absolute maximum that needs the eFuse OVP as its 35 V standoff, autonomous
1 A charging out of POR that only the REGN-biased pins prevent, the ILIM_HIZ sampling ambiguity (P6), the BAT 2.5 V hold and
BATOVP cycling behind D-BT-SQ (P1, P2), the contradictory charger watchdog (P7), the 7-minute poor-source lockout, and no
published warm-response, inhibit-latency or ADC-accuracy figure. A host-writable CELL field also lifts the VREG bound to
18.8 V until POR (section 14, finding 1). The custom board removes the EVM-specific penalties (11
mods, the EIB and ribbon fault classes, 25 V capacitors, about 24 support parts and the 0.30 m leads), enables 750 kHz with a
2.2 uH inductor for a 0.47 W lower burst loss at 3.1 A, and cuts the D-BC-RG/D-BC-FC close current from 0.99 A to 0.57 A
with the eFuse dVdT on the same board. These are design gains, not a change of the IC's requirement status: HR1 stays U,
HR2 P/sys, HR3 C (conditional on SYS separation, the build and the hard-stop allowance), HR4 C nominal, and HR5 rises from
B (stock F) to C by design, conditional on SYS separation and the heartbeat path, with the watchdog items still B. The score
of about 40 is the reference for the [CRIT] section 3.5 decision rule (a challenger must exceed it by at least 10 points)
only after the main document applies one M2 rule to every part (section 3). If the baseline fails M2 as written, the
shortlist must be judged on its own merit. If the protected-standoff reading is adopted, the 30-33 V class (at least the
BQ25713/BQ25731 runner-up class) must be re-admitted to scoring with S9 = 0.

---

## 17. Verification log

Two independent reviews of this dossier were re-checked against SLUSDV2C (local copy fetched 2026-11-10, 151 pages,
p.136 rendered as an image for the figure findings), [EVAL] 2.5 and 2.7, [WD] r1-4, [CRIT] and [SCR].

| # | Finding | Severity | Disposition | Basis |
|---|---|---|---|---|
| 1 | "SYS and BAT join at the IC" bypasses the BATFET charge sense; /CE stops being an inhibit; HR3/HR5/M5/M6/M11 overstated | Blocker | Applied | Confirmed: DS Table 5-1 p.5 (sense between SYS and BAT), §7.3.6 p.33 item 1 and §7.3.9.2 p.39 (SYS regulated with charge disabled). The diagram and section 2.1 already routed through the BATFET, but the bullet wording permitted a strap. Section 2.2 rewritten (SYS separate, capacitor-only); M5/M6/M11, HR3, HR5 and the verdict conditioned on it; CCB-1 extended |
| 2 | Regen REGN-divider ceiling 1.81 A gives a 108 us allowance, below the 115 us S1-B3 value | Major | Applied | Recomputed: [EVAL] 2.5 rows give a constant 0.757 V margin; 1.807 A / 0.4 mF = 4.52 V/ms gives 108 us (116 us at 16.39 V); 1.61 A gives 129 us. Reference-biased ceiling adopted as baseline; S1-B3 split; TODO(calc) removed |
| 3 | Protected-standoff M2 reading denied to the 30-33 V competitors | Major | Partly applied | Confirmed against [SCR] lines 27-29 and the M2 F rejections. The dossier cannot set the main document's rule; it states the uniformity requirement and makes the "about 40, beat by 10 points" reference conditional on one M2 rule. Score unchanged |
| 4 | Figs 8-6/8-7 do not give a /CE latency; durations misread by about 2x; test conditions misstated | Major | Applied | Confirmed on the rendered p.136: channels VBUS, SW2, SW1, IBAT; trigger Ch4 520 mA; 1.0 ms/div; header 1.5 MHz, L1 1 uH. Sections 5.1 and 8 rewritten; latency U; S5 basis restated |
| 5 | VREG 2S bound depends on the host-writable CELL field, which survives WD and REG_RST | Major | Applied | Confirmed: DS §7.3.2 pp.25-26 ("regardless of the state of the PROG pin"). Section 14 row 1 restated; CELL added to the read-back image (open question 8) |
| 6 | Hung-Teensy row credits H1/H2/C7; the heartbeat is the real inhibit; reset row cites pad pull-downs | Minor | Applied | Confirmed: [EVAL] 2.3 H2 uses FCC_net; [WD] r1-4 (U113, 30-40 ms); [EVAL] 2.7 (47 kOhm and 10 kOhm external pull-downs). Section 5.2 and HR5 conditioned on the heartbeat and the single-fault-parity build |
| 7 | FC POR bound 1.15 A is nominal, margin 0.047 A; ceiling register-defeatable | Minor | Applied | Confirmed: DS §7.3.4.3 p.27, Table 7-30 p.78; band 0.709-1.003 A. Labelled C nominal; M7, HR4 and S3 state the REG14[1] defeat. S3 score kept at 2 because the [CRIT] bands carry no defeatability term; uniform treatment flagged |
| 8 | VINDPM overwrite list not proven complete; EN_HIZ row conflict; ICO restart needs EN_ICO = 1 | Minor | Applied | Confirmed: DS §7.3.4 step 6 p.26, §7.3.4.2 p.27, Table 7-17 p.62. Section 6 row, section 5.1 EN_HIZ row, S4 basis, S1-B2 and the section 16 strength wording revised |
| 9 | Low-input auto-VINDPM is 5.6-6.6 V, not 6.3-6.6 V | Minor | Applied | DS §7.3.4.4 p.27: 7.0 - 1.4 = 5.6 V |
| 10 | Minimum-on-time concern does not apply to an NVDC part | Minor | Applied | DS §7.3.6 p.33, EC p.10 (VSYSMIN 7.12-7.52 V), §7.3.9.2 p.39; duty >= 0.32 (427 ns at 750 kHz). Open question 4 closed |
| 11 | ADC bits at 3 ms are 11 typical; IBAT_ADC on p.17; 18 ms needs other channels disabled | Minor | Applied | DS EC pp.16-17, §7.3.10 p.47 |
| 12 | EN_EXTILIM interaction with the < 0.75 V stop is an inference | Minor | Applied | DS §7.3.4.3 p.27 gives the two in separate paragraphs. M5 kept P on the stop level; the EN_EXTILIM interaction marked B; check added to S1-B3 |
| 13 | REGN pull-ups for /CE and gates are an interpretation | Minor | Applied | DS §7.3.4.1 p.26 quoted; load stated; CCB-1 as confirmation |
| 14 | Citation slips (D+/D- timing, PMID capacitors, watchdog accuracy, page count) | Minor | Applied | DS p.28 §7.3.4.5; p.6 PMID row; p.17 §6.6; 151 pages |
