# Path A design: TI BQ25798EVM replacing the Ag105, always-powered regen + FC charging (board rev 20260622)

> **Round-2 study note (2026-11-05, added when this scratch record was copied into the repo).** This is the designer's
> working record. Where it disagrees with `docs/charger_replacement_evaluation_2026-11-05.md` section 4, **the study wins**.
> The final panel found, and the study corrects: (1) §3.1/§3.3 build GATE = H1 OR H2 without the C7 qualifier; the study
> requires PERMIT = P5 AND [(H1 AND RGN AND NOT FCC) OR H2] (one extra gate); (2) SLUSDV2C p.33 states that with charge
> disabled by /CE and no battery seen, BAT is held near 2.5 V, so S1-B7 is an expected failure for the /CE-per-burst scheme
> and the study makes the D-BT-SQ disposition (M8 + P5-only /CE, or a bridged D-BT-SQ) an explicit decision; (3) R42 (/CE
> pull-up) must be biased from REGN, not PULLUP; (4) VAC_OVP POR is 7 V per SLUUCB5E §2.4.3 step 6; (5) the HR4 ceiling is
> PROVEN_CALC (nominal), not PROVEN_DATASHEET. Scratch paths below refer to the round-2 working directory, not the repo.
>
> **Critic-round correction banner (2026-11-05, later).** The study (sections 0.4, 2.3, 2.5, 4.1-4.6) further corrects this
> record: (6) **M5: keep JP4 installed** (it ties VAC2 to VBUS, which SLUSDV2C Table 5-1 p.5 and §7.3.5.2 require when ACFET2/RBFET2
> are absent) and insulate or remove the J2 terminal block; the "remove JP4" recommendation below would leave VAC2 floating and is
> withdrawn; (7) ILIM_REL = GATE OR (CHG_QUAL AND NOT P5) in hardware; (8) the single R21 150k / R23 100k divider (1.15-1.35 A) is
> replaced by a mode-switched divider, R21 121k / R23 100k plus R_FC 158k switched in by FCC_net (regen 1.44-1.72 A, FC
> 0.74-0.96 A), and the regen IINDPM register becomes 1.70 A (0x00AA); (9) the INA253 zero-current floor is up to 10 mV = 0.1 A
> (SLOS954A §7.5), so no "I_BT > 50 mA" trip; (10) the S1-B3 latency allowance is 117-194 µs (not 320 µs); (11) poor-source
> recovery is required (7-minute retry otherwise, SLUSDV2C §7.3.4.2, §7.3.13.1.3); (12) the VCHG-IN protection is an eFuse.


Round 2, 2026-11-05. Scratch design record, not committed. It implements the operator's 2026-11-05 rulings:
1. regen harvesting and FC charging are both hard requirements;
2. Path A must be shown fully feasible before committing;
3. R3 is replaced by "no circular loop, no runaway", with an always-powered charger (REGEN closed through Run);
4. the board survived the 11-13 A incident (a scope-armed first bring-up is still required);
5. an MCU hardware watchdog is REQUIRED FUTURE WORK.

It builds on the BQ25798 dossier (`r2/dossier_BQ25798.md`, [DOS]) and resolves its three MAJOR review findings (loop, regen,
integration lenses) by changing the inhibit architecture (§3.4). Diagram: `r2/design_BQ25798.svg`.

**Verdict.** On paper, Path A with the BQ25798EVM is **feasible: no datasheet fact blocks it, and the loop is impossible by
construction with every single fault.** It is **not yet proven**, because six numbers the datasheet does not give decide
whether regen capture works. Those numbers are bench gates S1-B3, S1-B4, S1-B4r, S1-B5, S1-B7 and S0-R0/R3 (§9, §10.3). The
first gate is not about the charger at all: it is the VESC over-voltage cut-off (M-R0/M-R3). If that gate fails, regen
capture is limited on this rig whatever charger is fitted.

## 0. Sources and evidence rules

| Tag | Document | Use |
|---|---|---|
| [DS] | TI **SLUSDV2C** BQ25798 datasheet, rev. June 2026 (`datasheets/BQ25798_ds.pdf`; page-tagged text `r2/BQ25798_ds_pg.txt`) | Every BQ25798 number, cited as p.N + section/table |
| [UG] | TI **SLUUCB5E** BQ2579xEVM user guide, rev. July 2022 | Jumpers (Table 1-3 pp.4-5), BOM (Table 4-1 pp.22-24), schematic Fig 4-5 (p.19) / Fig 4-6 (p.20, viewed as rendered PNG) |
| [RT] | Richtek RT1987 DS-00 | EC table p.7; §17 pp.14-16 |
| [TLV] | TI SBOS300C TLV3011/3012 | B-grade EC p.8-10; §9.4.4-9.4.5 p.22 (as read in [LOOP]) |
| [LVC] | TI **SCES217AA** SN74LVC1G08, rev. Aug 2026 (fetched this round, `datasheets/sn74lvc1g08.pdf`) | §5.3 p.5: VIH 2.0 V / VIL 0.8 V at VCC 3.0-3.6 V; Ioff partial power-down (Features; §7.3.2). The 1G00 sheet was fetched too. The 1G27/1G32 sheets were not read, and the same LVC1G family limits are assumed for them |
| [TPS] | TI SLVSFP3C TPS61288 | VOVP 18.3/19/19.5 V, p.6 |
| [LOOP], [REGEN], [SPEC], [DOS] | `r2/loop_analysis.md`, `r2/regen_dynamics.md`, `docs/reviews/charger_eval_2026-11-05/spec.md`, `r2/dossier_BQ25798.md` plus its three adversarial verdicts | Board facts and cross-cutting analyses |
| [FW] | `teensy_controller/teensy_controller.ino`, fw v37 rev 2 tree tip | Telemetry v4 layout (~7634), `LIMIT_I_FC_MAX` 1.4 A (2090), `AG105_ADDR` (2464) |
| [WDT] | tonton81 WDT_T4 source (`r2/wdt/`) | Teensy watchdog register usage. NOT an NXP primary |
| [TIstore] | `ti.com/storeservices/cart/opninventory?opn=...`, plain curl, **2026-11-05 20:02 UTC** | Stock |

A value read off a datasheet figure is labelled "figure reading, typical". A value no primary gives is marked **BENCH** or
**TODO(verify: source)**. No snippet or recollection is presented as verified.

## 1. Wiring: Ag105 pads to the EVM

### 1.1 Mounting

- **The EVM goes off-board on leads.** It has 5 terminal blocks, about 33 jumpers and three headers ([UG] BOM pp.22-24). It
  cannot fit the 32 × 35 mm boxed-in footprint ([SPEC] §7).
- **Mounting:** on the chassis on nylon standoffs, at least 20 mm from the LM1084 side of the board. Leads should be no
  longer than 0.30 m.
- **Ag105 removal:** desolder the Ag105 (22 pins, 1.1 mm holes). Fit 0.1" turned-pin sockets or solder wires directly into
  the vacated holes.
- **Carrier location:** the small comparator/logic carrier (§3) sits at the board edge next to the taps.
- **No capacitor of any kind is added at the EVM input** (§8.1).

### 1.2 Pad-to-EVM table

Pad coordinates are from [SPEC] §1. EVM connectors are from [UG] Table 1-2 (p.4). Signal routing is via the carrier (§3).

| Ag105 pad (pin) | Board net | → EVM point | Wire | Notes |
|---|---|---|---|---|
| VIN+ (10) | VCHG-IN (D-BC-FC / D-BC-RG VOUT; C-D8, C-D10; R1/R2-CHG → pin 38) | **J1 VIN1** (into VBUS via R2 0.01 Ω + JP3, after M5) | 20 AWG, twisted with its GND, ≤ 0.30 m | ≤ 1.35 A (the ILIM hardware ceiling, §2 M3). 33 mΩ/m → ≤ 27 mV drop at 1.35 A |
| VIN- (4) | GND | **J1 GND** | the pair's return | R-GND satisfied: J1-J5 grounds are one PGND node, and all EVM shunts are high-side ([UG] Fig 4-5; [DOS] §2.1) |
| VBAT+ (18, 19) | VCHG (D-BT-SQ VIN, C-D11) | **J5 BATTERY (pin 1)** | 18 AWG, twisted with its GND, ≤ 0.30 m | ≤ 2.5 A. 21 mΩ/m → ~13 mΩ round trip → 31 mV at 2.5 A, ~0 at termination (§8.5). Use both pads |
| VBAT- (14, 15) | GND | **J5 GND (pin 3)** | the pair's return | - |
| THERM (13) | N$34 → J-NTC pin 1 | **J7 pin 1 (EXT_TS)**, J7 pin 2 = AGND to GND | 26 AWG pair in the signal bundle | Only if an NTC is fitted on the vehicle ([SPEC] open Q5). Then remove JP18 (M9) |
| SDA (8) | SDA → Teensy 18, RSDA 10 k to 3V3 | **EVM SDA net** (J8 header SDA pin, [UG] Fig 4-6; confirm by continuity) | 26 AWG, twisted with GND | 100 kHz only: 10 k pull-up × ~100 pF gives t_r ≈ 0.85 µs ([SPEC] §3.2) |
| SCL (7) | SCL → Teensy 19, RSCL 10 k to 3V3 | **EVM SCL net** (J8 SCL pin) | same | EVM pull-ups R39/R40 removed (M4) |
| STAT (3) | CHRG-STAT → Teensy 6, no pull | **EVM STAT net** (JP32 pin 2 side, [UG] Fig 4-6) | 26 AWG | Open-drain, **LOW = charging** ([DS] Table 7-11 p.48). Teensy `INPUT_PULLUP`. Remove the JP32 shunt (M4) |
| MPPTD (11) | MPPT-DISABLE ← Teensy 5 | **carrier input P5** (not to the EVM) | - | Pin 5 becomes `CHG_ARM` (CSV rename first). It reaches CE only through the PERMIT logic (§3) |
| (new) | carrier PERMIT | **EVM /CE net** via stage A on the EVM (§3.5) | 26 AWG twisted with GND, ≤ 0.30 m | - |
| (new) | carrier ILIM_REL | **EVM ILIM_HIZ net** via stage B on the EVM | 26 AWG twisted with GND | - |
| VSEL, CSEL, MPPTSEL, LDIS, VLOAD±, NC | floating | - | - | Unused; they serve as mechanical anchors |

**Taps for the comparator** (bodge wires to the carrier, 26 AWG, ≤ 0.10 m):
- **V-MOT:** at CAL+ (the D-MT-EN VOUT side).
- **VBUS:** at the D-MT-EN VIN side, C-D2 ([LOOP] §9).
- **BT_CURRENT:** the INA253 output net at the pin-41 node.
- **EN nets:** BT_BUS (pin 28), REGEN (pin 30, J1.43/44), FC_CHARGE (pin 31, J1.45/46).
- **3V3 and GND:** J1.29/30 and J1.01/02 ([SPEC] §1).

### 1.3 Local capacitance

| Node | Capacitance | Note |
|---|---|---|
| VCHG-IN | 20 µF nominal on the board (C-D8, C-D10) + 50.2 µF on the EVM input (VBUS C11, C12 + C13; PMID C29-C31 + C32) = **70.2 µF nominal**. No electrolytic ([UG] BOM p.22; [DOS] §2.8) | After M7 the parts are rated ≥ 35 V. DC derating then shrinks, so use the nominal value as the worst case |
| VCHG | C-D11 10 µF + EVM BAT/SYS ceramics (C38, C39 10 µF 0603; C19-C23 10 µF) ≈ 80 µF nominal | - |

## 2. EVM and motherboard modifications

Designators are from [UG] Fig 4-5/4-6 and BOM. The jumper defaults are from Table 1-3 (pp.4-5).

| ID | Change | Why / evidence |
|---|---|---|
| **M1** | **Remove the JP17 shunt.** /CE is then held HIGH by R42 10 k to PULLUP | The stock EVM grounds /CE ("CHARGE ENABLE", installed by default, [UG] Table 1-3 p.5). POR otherwise charges at 1 A by itself ([DS] §7.1 p.23, Table 7-9 p.41) |
| **M2** | **Stage A on /CE:** an NMOS (BSS138 / 2N7002 class, SOT-23) with drain on /CE, source on AGND, and gate = PERMIT through 1 kΩ, with 100 kΩ + 10 nF to AGND on the gate. PERMIT HIGH → /CE LOW → charging allowed | /CE VIH 1.3 V / VIL 0.4 V ([DS] EC p.16). Fail-safe: no PERMIT means /CE is pulled HIGH by the EVM's own PULLUP rail. That rail is a TLV76033 fed from the VBUS/BAT diode-OR (D11/D12, JP30, [UG] Fig 4-6), so it is alive whenever the IC is. The 10 nF with 1 k is a 10 µs glitch filter for the lead run |
| **M3** | **Stage B on ILIM_HIZ:** change **R21 127 k → 150 k** (keep JP14 fitted; JP13 and JP21 stay open; R23 100 k stays). Add Q2 (NMOS: drain on ILIM_HIZ, source on AGND, gate pulled up to REGN through 100 k) and Q1 (NMOS: drain on Q2's gate, source on AGND, gate = ILIM_REL through 1 k, with 100 k + 10 nF to AGND) | Divider: REGN × 100/(150+100) = 0.4 × REGN. REGN is 4.8-5.2 V at VBUS 15 V ([DS] EC p.15), so the pin sits at 1.92-2.08 V. ILIM = (V - 1)/0.8 Ω ([DS] Eq.1 p.27) = **1.15-1.35 A, a hardware input ceiling** (stock R21 gives 2.2 V = 1.5 A, "JP14 1.5 A"). Below 0.75 V the converter stops with REGN on; above 1 V it resumes ([DS] §7.3.4.3 p.27; EC p.16). ILIM_HIZ leakage is ±1.5 µA ([DS] EC p.12), negligible against the 60 kΩ Thevenin. Q2 on pulls the pin to about 0 V |
| **M4** | **Remove R39 and R40** (SCL/SDA 10 k to PULLUP). Remove the **JP32 shunt** (STAT LED via R38 2.21 k to PULLUP). R41 (INT) may stay; INT is unused | Otherwise PULLUP back-powers the Teensy through its I/O clamps ([DOS] §2.9). STAT must swing only to Teensy 3V3 |
| **M5** | **JP3 + JP4 installed; JP1 + JP2 moved from their default 1-2 ("ACDRV to VAC FETs") to the GND position, 2-3** ("connect to GND when input protection MOSFETs are not used or bypassed", [UG] Table 1-3 p.4). Feed J1 only. J2 is live through JP4: **keep JP4 installed and insulate or remove the J2 terminal block** (critic-round correction: removing JP4 would float VAC2, contrary to [DS] Table 5-1 p.5 / §7.3.5.2) | Removes the ACFET hot-plug. With no ACFET detected at POR, EN_ACDRV1/2 lock at 0 ([DS] Table 7-29 p.76). **Set before first power-up.** ~~Recommend: remove JP4 rather than leaving a live J2~~ (withdrawn) |
| **M6** | **JP5 installed + JP8 on 1-2** (ship FET Q5 bypassed). **JP9 on 2-3** (BATP at the BAT pin, CV sensed at the IC) | [UG] Table 1-3 p.4. A remote BATP at VBT is incompatible with the M8 keep-alive (BAT would sit about 1.5 V below BATP when idle) |
| **M7** | Replace **C11, C12, C29, C30, C31** (10 µF 25 V X5R 0805, C2012X5R1E106K125AB) with 10 µF **≥ 35 V X7R** of no larger nominal value. Motherboard: replace **C-D8 and C-D10** (GRM21BZ71E106KE15L, 25 V) with 10 µF 35 V 1206 X7R, the same type as C-D6/C-D7 | V-MOT reaches 21.2-21.5 V measured; the design clamp is 21.98-22.28 V ([REGEN] §0; [LOOP] §4.2). A 25 V part has no margin |
| **M8** (PROPOSAL, needs operator approval) | **1.0 kΩ, 0.25 W, from VBT (C-D12, under the footprint) to VCHG** (an Ag105 VBAT+ pad), across D-BT-SQ | Keeps VCHG above the RT1987 UVLO (3.0-3.35 V rising, [RT] p.7) between bursts, so D-BT-SQ re-conducts without paying tD_ON 8 ms + tON ([RT] p.7, Table 1 p.15). It also keeps the BQ25798 powered and configured from the pack (§6). **Load budget:** D-BT-SQ IQ 0.65-0.78 mA ([RT] p.7) + IQ_BAT_ON 540 µA with ADC on ([DS] EC p.8) + REGN loads ≈ 0.3-0.4 mA, so VCHG ≈ VBT - 1.5-1.7 V = **5.7-6.9 V**. **Cost:** about 1.7 mA continuous pack drain (≈ 41 mAh/day). Worst-case dissipation into a shorted VCHG is 8.4²/1 k = 70 mW. **Fallback** if S1-B7 fails: bridge D-BT-SQ. That is safe for this IC because SYS→VBUS has no passive path ([DOS] §2.1), but it loses the hardware pack disconnect |
| **M9** | TS: if an NTC is fitted at J-NTC, wire THERM → J7 and **remove JP18** ("remove this jumper whenever using an externally connected thermistor", [UG] Table 1-3 p.5). If not, keep JP18 (simulated NORMAL). Never rely on TS_IGNORE: it is reset by the watchdog ([DS] Table 7-34 p.83) | Charging is suspended outside the TS window ([DS] Table 5-1 p.5) |
| **M10** | Keep **JP24** (PROG = 2S, 1.5 MHz). Never move a PROG jumper with power applied | POR VREG 8.4 V, VSYSMIN 7 V, ICHG 1 A ([DS] Table 7-2 p.25). Note: R29 is **6.04 k** in Fig 4-6 but **6.20 k** in BOM p.23. The UG is self-inconsistent, so check at bring-up by reading back CELL = 1h (2S) and PWM_FREQ = 0 |
| **M11** | Remove **JP6, JP10, JP11** (D+/D- paths). J6 is unused | No USB detection path. AUTO_INDET_EN = 0 (§6) |
| **TP caution** | The UG uses inconsistent test-point numbers (BAT is "TP29" on p.7 and "TP27" on p.12; the dossier also called TP27 REGN) | **Identify REGN, /CE, ILIM_HIZ and PULLUP by net with a meter before soldering.** Do not trust TP numbers |
| **Board B1** | Comparator/logic carrier (§3) with its taps | - |
| **Board B2** | CSV first, then firmware: pin 5 `MPPT_DISABLE` → **`CHG_ARM`** (OUT, HIGH = arm). Pin 6 `CHARGER_STAT` keeps its name, but the meaning inverts: **LOW = charging**, `INPUT_PULLUP`. New rows: **pin 10 `CHG_QUAL`** (OUT), **pin 33 `CHG_PERMIT_RB`** (IN), **pin 34 `CHG_H1_RB`** (IN), **pin 16 `CHG_H2_RB`** (IN). All are spare pins per [SPEC] §1. Pins 19/20/21/25 are excluded (SCL; WDOG/EWM options; BT_VOLTAGE) | CLAUDE.md: the CSV is authoritative |

**Sense resistors:** none to change. R2 (VIN1) and R13 (battery, between BAT/Q5 and J5-1) are 0.01 Ω high-side measurement
shunts ([UG] BOM p.22). The IC senses internally: RSNS between VBUS and PMID, and SYS-BAT ([DS] Table 5-1 pp.4-5). R13
gives a bench current reading at TP19/TP20 (UG p.7).

**Bulk input capacitors:** none to remove. The BQ25798EVM has no electrolytic or tantalum on the input. C25 (33 µF tantalum,
on SYS) is DNP, and C33/C34 polymers are on the BKUP variant only ([DOS] §2.8).

## 3. Backstop hardware (carrier + EVM-side stages)

### 3.1 Logic summary

```
H1      = TLV3012B: V-MOT > 1.067 x VBUS (+0.30 V hysteresis)           [regen-path loop barrier]
BT_ACT  = TLV3012B: INA253 BT output > 19.8 mV (I_BT > ~0.2 A)
H2      = FCC_net AND NOT(BTB_net OR RGN_net OR BT_ACT)                  [FC-path loop barrier]
GATE    = H1 OR H2
PERMIT  = GATE AND P5 (CHG_ARM)              -> stage A -> /CE           (dynamic charge inhibit)
ILIM_REL= GATE OR CHG_QUAL                   -> stage B -> ILIM_HIZ      (dynamic converter-off)
```

This is [LOOP] §9 with two changes that close the three MAJOR review findings:

1. **/CE is driven by PERMIT, not by pin 5 alone.** This is review fix F1(a). The comparator therefore gates a pin whose
   behaviour does not depend on any register bit. CE HIGH disables charging, and the charge cycle needs "EN_CHG = 1 **and**
   CE pin LOW" ([DS] §7.3.9.1 p.41). With charge disabled, SYS is regulated about 200-600 mV above BAT ([DS] §7.3.8.1 p.39).
   SYS is unloaded, so the only input draw is IQ_VBUS (3-5 mA at 15 V, [DS] EC p.8).
2. **ILIM_HIZ is released whenever firmware raises CHG_QUAL.** Firmware raises it only during an input qualification
   window, with P5 LOW. As a result the ADC reads the **divider** (1.15-1.35 A) at the step-6 qualification ([DS] §7.3.4
   p.26, §7.3.4.3 p.27), and **EN_EXTILIM stays at its POR value 1**.
   - The hardware ceiling is kept in both modes ([LOOP] C2).
   - The documented HIZ behaviour (< 0.75 V stops switching) applies with no register caveat.
   - The "does HIZ survive EN_EXTILIM = 0" question (reviews: loop F1, regen MAJOR, integration 1) is **designed out**.
     EN_EXTILIM is never written to 0.

Outside qualification windows (CHG_QUAL LOW), **both** charger pins follow GATE. In armed operation that gives two
independent hardware inhibits, on two pins, through two transistor stages.

### 3.2 H1: V-MOT/VBUS comparator (values from `r2/comp_calc.py`)

| Part | Value | Note |
|---|---|---|
| U1 | TLV3012B (SOT-23-6 DBV or SC70 DCK) | Push-pull; Vos ±9 mV (B grade); prop ≤ 4 µs ([TLV] p.8-10). **Output LOW (sinking) during POR, up to 1.9 ms, and when unpowered.** Fail-safe inputs tolerate up to 5.5 V with V+ = 0 ([TLV] §9.4.4-9.4.5 p.22) |
| V-MOT divider | RA1 499 k / RA2 56.2 k, 0.1 %; CA 470 pF | τ 24 µs |
| VBUS divider | RB1 464 k / RB2 56.2 k, 0.1 %; CB 470 pF | τ 24 µs, matched |
| Hysteresis | RH 6.49 M, OUT → IN+ | ≈ 0.30 V at the V-MOT scale |
| Supply | Teensy 3V3 (J1.29/30), 100 nF | Pack-derived (VBT → LM1084 → Teensy). When 3V3 is gone, every RT1987 EN is LOW too ([LOOP] §9) |

Trip points ([LOOP] §4.2 table, `comp_calc.py`, 0.1 % resistors, Vos ±9 mV):

| VBUS | Rise (permit), worst max | Fall (inhibit), worst min | Guard over VBUS |
|---|---|---|---|
| 15.9 V | 17.29 V | 16.66 V | 0.76 V |
| 16.39 V (steady max) | 17.83 V | 17.19 V | 0.79 V |
| 19.5 V (TPS61288 OVP max) | - | 20.52 V | 1.02 V |

Across 15.59-19.5 V the worst-case guard is ≥ 0.73 V. With 1 % resistors the guard collapses to 0.24 V, so **0.1 % is
mandatory**.

**The existing RGN-V divider is NOT reused.** Its node is the TL431 REF ([LOOP] §9 checks), so loading it would shift both
the clamp and the pin-39 reading.

### 3.3 H2: FC-window permit

- **U2:** TLV3012B. IN+ = BT_CURRENT net (INA253 output, 10 pA bias). IN- = U2.REF 1.242 V → 61.9 k / 1.00 k → 19.8 mV,
  with 100 nF. The trip is 0.11-0.29 A over Vos ±9 mV at 0.1 V/A ([LOOP] §9).
- **INA253A1 zero-current offset:** TODO(verify: INA253A1IPWR.pdf).
- **Logic (3V3, 100 nF per gate):**

  | Gate | Part | Inputs | Output |
  |---|---|---|---|
  | G1 | SN74LVC1G27 (NOR3) | BTB_net, RGN_net, BT_ACT | N1 |
  | G2 | SN74LVC1G08 (AND) | FCC_net, N1 | H2 |
  | G3 | SN74LVC1G32 (OR) | H1, H2 | GATE |
  | G4 | SN74LVC1G08 (AND) | GATE, P5 (47 k pull-down on the carrier) | PERMIT |
  | G5 | SN74LVC1G32 (OR) | GATE, CHG_QUAL (47 k pull-down) | ILIM_REL |

- **Input thresholds:** VIH 2.0 V / VIL 0.8 V at VCC 3.0-3.6 V ([LVC] §5.3 p.5).
  - **Residual:** the band between the RT1987 VEN_F minimum (0.6 V, [RT] p.7) and VIL 0.8 V. An EN net stuck in it reads
    "off" while the switch may conduct. **The BT_ACT current term covers it** for the FC window ([LOOP] §9).
  - Ioff partial power-down ([LVC] §7.3.2) means the EN-net inputs are safe while the carrier is unpowered.
- **Readbacks:** PERMIT → pin 33, H1 → pin 34, H2 → pin 16, through 1 k series resistors.

### 3.4 What is gated, and what deliberately is not

**Gated:** the charger's /CE and ILIM_HIZ pins.

**Not gated: D-BC-RG EN (pin 30) AND H1, which was considered and rejected.**
1. Every burst would pay RT1987 tD_ON 8 ms typ + tON about 1.5 ms ([RT] p.7, §17.3 p.15). That alone exceeds τ_warm ≤ 4 ms
   ([REGEN] §5).
2. Every burst would hot-plug VCHG-IN (70 µF × 12 mA/µF = 0.84 A).
3. It is the opposite of the accepted "always-powered" design.

D-BC-RG stays a firmware-commanded mode switch (closed through Run).

### 3.5 Stage placement and power-up states

Stages A and B sit **on the EVM**, beside /CE and ILIM_HIZ, because they must be biased from the EVM's own PULLUP and REGN
rails. PERMIT and ILIM_REL travel in the 0.30 m signal bundle, each twisted with a ground. The 1 k/10 nF gate filter rejects
coupled spikes shorter than about 5 µs and adds ≤ 20 µs to the inhibit budget (§8.3).

| Condition | PERMIT | ILIM_REL | /CE | ILIM_HIZ | Charger |
|---|---|---|---|---|---|
| Teensy 3V3 absent (carrier unpowered) | 0 | 0 | HIGH (R42 → PULLUP) | LOW (Q2 via REGN), if REGN is up | Charge off + converter off. Also unpowered at VBUS (RT1987 pull-downs) |
| TLV3012 in POR (≤ 1.9 ms) | 0 | CHG_QUAL | HIGH | follows QUAL | Charge off |
| Teensy in reset (pins high-Z) | 0 (P5 47 k ↓) | GATE (QUAL 47 k ↓) | HIGH | follows GATE | No VBUS (EN 10 k ↓); charge off |
| Qualification (P5 0, QUAL 1) | 0 | 1 | HIGH | divider (1.92-2.08 V) | Qualifies with the hardware ceiling; charge off |
| Armed (P5 1, QUAL 0) | GATE | GATE | ¬GATE | GATE ? divider : 0 V | Only while V-MOT > 1.067 VBUS, or in a verified FC window |
| State 99 (P5 0, QUAL 0) | 0 | GATE (= 0 in cruise) | HIGH | LOW | Both inhibits on, then the paths open |
| Teensy hang (pins frozen) | P5 ∧ GATE | GATE ∨ QUAL | follows GATE | follows GATE (or released if frozen in QUAL) | Comparator-gated; charger WD stops charging (§6.4) |

## 4. Operating modes

Switch vector order: FC_REG, BT_REG, FC_BUS, BT_BUS, MOT_PWR, REGEN, FC_CHARGE, BT_SEQ. "Loop closed?" means whether the
switches close the physical loop graph L-R (via D-MT-EN + D-BC-RG) or L-F (via D-BC-FC) ([LOOP] §3).

| Mode | Switches | P5 / QUAL | Charger registers (§6) | Loop closed? | What prevents a loop | What prevents runaway |
|---|---|---|---|---|---|---|
| Teensy reset / boot | 0 0 0 0 0 0 0 0 (pull-downs) | high-Z (↓) | as left (M8 keeps the IC on the pack) | No | No input power | - |
| Init (State 0) | staged; REGEN 0, FCC 0 | 0 / 0 | **static image written and verified** (IC is pack-powered via M8) | No | No input power | - |
| Idle (State 1) | 1 1 1 1 1 **0** 0 1 | 0 / 0 | static image; WD kicked; EN_CHG 0 | No | REGEN = FCC = 0 | - |
| **Run cruise, regen armed** | 1 1 1 1 1 **1** 0 1 | **1 / 0** | VINDPM 19.0 V, IINDPM 1.25 A (pin clamp 1.15-1.35 A), ICHG 2.50 A, EN_CHG 1 | **L-R closed** | **H1 = 0** → /CE HIGH and ILIM_HIZ LOW (two pins). Soft layer: VINDPM 18.62-19.38 V above the bus maximum of 17.2 V | Converter off |
| **Run regen burst** | as cruise | 1 / 0 | as cruise | Closed by the switches, but D-MT-EN is reverse-biased ([RT] §17.6) | Physics: the bus cannot feed V-MOT while V-MOT > VBUS ([LOOP] §4.1). H1 releases only in this condition | Self-limited: drawing more than the regen supplies pulls V-MOT to VINDPM, then to the H1 fall trip. Hardware input ceiling 1.15-1.35 A; ICHG 2.5 A; IBUS_OCP 7-9 A ([DS] EC p.9) |
| Run regen, VESC abrupt stop | as cruise | 1 / 0 | as cruise | briefly | H1 falls within ≤ 4 µs, then charger latency ≤ 340 µs at 1.25 A (S1-B3) | A single pulse ≤ I_in × (t_inh - t_budget), cannot be sustained ([LOOP] §4.3) |
| Run cruise, battery-only selection | 1 1 0 1 1 1 0 1 | 1 / 0 | as cruise | L-R closed | H1 | as cruise |
| Run cruise, FC-only selection | 1 1 1 0 1 1 0 1 | 1 / 0 | as cruise | No (BT out) | - | as cruise |
| **FC-charge window** | 1 1 1 **0** 1 **0** **1** 1 | 1 / 0 | VINDPM 13.5 V, IINDPM ≤ 0.90 A (scheduled §6.3), ICHG 1.60 A | No while D-BT-EN is truly off | **H2** (FCC ∧ ¬BTB ∧ ¬RGN ∧ I_BT < 0.2 A) → /CE and ILIM_HIZ. CSV rule plus `assertFcChargeEnable()` | Pin clamp 1.15-1.35 A; register 0.90 A; firmware raw I_fc > 1.20 A → P5 LOW in the same tick; OC_FC 1.4 A latch ([FW] 2090) |
| FC window + braking | as FC window | → transition §5.3 | → regen image | No | REGEN 0 until the transition completes | - |
| Finish (State 3) | → Idle vector | 0 / 0 | EN_CHG 0 | No | P5 LOW first, then REGEN LOW | - |
| State 98 tests | operator keys | via the gated sequencer only | per test | `'2'` + REGEN can close L-R | H1/H2 act on the pins regardless of keys. Pin 5 is never toggled raw (§7.6) | as above |
| State 99 | phased open | **0 / 0 first** | EN_CHG 0 written (best effort) | No after teardown | Both pins inhibited (GATE = 0 in cruise), then REGEN/FCC open | - |
| Teensy hang | frozen | frozen | frozen; **charger WD 0.5 s → EN_CHG = 0** (STOP_WD_CHG = 1) | possibly | H1/H2/stages are MCU-independent | Pin clamp + charger WD; **MCU WDT (future work) resets → all EN LOW** |
| I2C dead | any | firmware holds P5 0 (config unverifiable) | unknown | possibly | /CE HIGH (P5 0); H1/H2 | - |

**The `J` session as defined in fw v37 rev 2** (charger fed through MOT_PWR + REGEN with BT_BUS closed) **closes L-R by
construction** ([LOOP] §13). It is retired. Its replacement is an FC-path bench session (§7.6).

## 5. Mode transitions (ordered)

Invariants (from [LOOP] §6, strengthened):

- **(I-1)** P5 is LOW across every switch change.
- **(I-2)** A sub-bus VINDPM (13.5 V) is written only while REGEN = 0, BT_BUS = 0 and FCC = 1. The regen VINDPM (19.0 V) is
  written before FCC drops.
- **(I-3)** P5 rises only after a readback of the full masked image (§6.2) and of ICO_ILIM (REG19) ≥ 1.10 A, in the
  charger's current plug-in cycle.
- **(I-4)** No transition starts while H1 = 1 (a burst in progress), except the brake-edge FC→regen transition, which starts
  before the burst.
- **(I-5, new)** CHG_QUAL is HIGH only while P5 is LOW, and only from a REGEN/FCC close until PG_STAT = 1 plus 50 ms.

### 5.1 Run entry (Idle → Run cruise, regen armed)

| # | Action | Rationale |
|---|---|---|
| 0 | Precondition: static image verified (IC is pack-powered via M8); H1 readback = 0; MOT_PWR = 1 (V-MOT pre-charged, Death-5 rule) | - |
| 1 | P5 LOW (already); **CHG_QUAL HIGH** | ILIM_HIZ released so that step 6 reads the divider |
| 2 | REGEN HIGH. D-BC-RG tD_ON 8 ms + ramp to 15.85 V in about 1.3 ms ([RT] p.7; [SPEC] §6) | Inrush 70.2 µF × 12 mA/µF = 0.84 A, drawn from CAL and refilled through D-MT-EN by both boosts (BT_BUS closed). Not on OC_FC alone |
| 3 | Wait for VBUS_PRESENT (REG1B[0]); then REGN at +150 ms; poor-source check about 30 ms (IPOORSRC 7-20 mA, [DS] EC p.10) → **PG_STAT (REG1B[3]) = 1**, ILIM read, VINDPM auto = VBUS0 - 1.4 ≈ 14.5 V ([DS] §7.3.4 steps 5-6 p.26; §7.3.4.4 p.27). D+/D- is skipped (AUTO_INDET_EN = 0, verified in Idle) | No switching during the ramp |
| 4 | Poll REG05 until it is ≠ 0x24 (the auto value has landed) and stable across 2 polls 20 ms apart. Then **CHG_QUAL LOW** | VINDPM written before the step-6 auto-set is silently overwritten (loop review F3) |
| 5 | Write the regen mode image (§6.3); read back the whole masked image and REG19 ICO_ILIM ∈ [1.10, 1.40] A | (I-3) |
| 6 | **P5 HIGH** (armed). Both pins now follow H1, so the charger stays inhibited until V-MOT > 1.067 × VBUS | - |

- **Arm latency:** about 0.25 s after REGEN closes.
- **If REG19 reads 0.10 A** (ILIM was low at qualification): stay disarmed until the next Idle/Run cycle and raise a
  harvest-lost flag. Safe.

### 5.2 Regen armed → FC window

| # | Action | Rationale |
|---|---|---|
| 1 | Check H1 readback = 0 (I-4); P5 LOW; wait ≥ 1 ms (≥ 3 × the S1-B3 latency) | Charger hard-off before any path change |
| 2 | REGEN LOW | CSV row 31. **No unplug follows:** VCHG-IN (70 µF) falls only at IQ/70 µF ≈ 40-70 V/s, so it stays far above VBUS_PRESENTZ ≈ 3.2 V ([DS] EC p.9). This corrects [DOS] §4 step 5 (integration review finding 2) |
| 3 | BT_BUS LOW (existing S2 order inside `assertFcChargeEnable()`; restore FC first if the share loop has it cut) | Takes the pack off the bus |
| 4 | Wait ≥ the RT1987 turn-off time (M3 measurement; firmware 100 µs today) | DS-00 gives no turn-off figure |
| 5 | FC_CHARGE HIGH; tD_ON 8 ms. VCHG-IN has drooped ≤ 0.6 V, so the D-BC-FC close is **warm**: ≤ 0.6 V × 70 µF ⇒ a ≤ 50 µs, ≤ 0.84 A slew pulse | A cold FC close is never used in Run (§8.1) |
| 6 | Write the FC mode image (VINDPM 13.5 V, IINDPM scheduled, ICHG 1.60 A); read back | (I-2), (I-3). No re-qualification, so the ILIM clamp from the Run-entry qualification (1.15-1.35 A) still holds |
| 7 | P5 HIGH; H2 grants PERMIT and ILIM_REL | Charging starts |

### 5.3 FC window → regen armed (brake-edge triggered)

| # | Action | Rationale |
|---|---|---|
| 1 | P5 LOW | (I-1) |
| 2 | Write VINDPM 19.0 V, IINDPM 1.25 A, ICHG 2.50 A; read back (≈ 0.6 ms at 100 kHz). On I2C failure, continue with P5 held LOW | (I-2): written while still FC-powered |
| 3 | FC_CHARGE LOW | - |
| 4 | BT_BUS HIGH through the share-loop re-entry and hot-plug guards; REGEN HIGH (tD_ON 8 ms each, in parallel) | REGEN only after FCC is LOW (CSV) |
| 5 | When D-BC-RG conducts (VCHG-IN tracks V-MOT; pin 38 vs pin 39 within 0.3 V), re-verify the image; P5 HIGH | - |

- **Duration:** about 10-12 ms.
- **Timing problem:** the electrical regen onset is ~5 ms after `I_cmd` goes negative ([REGEN] §1.1). This corrects the
  "80-120 ms" in fw37 planning §3.2. **If the transition starts on the brake command, the first ~10 ms of regen go to the
  node capacitance.**
- **Options for the operator:**
  - **(a)** gate the negative VESC current command for ≤ 15 ms while the transition completes (a command-path change, not
    a PI change);
  - **(b)** accept the loss: node energy only, but the VESC may then trip at 21.35 V for 0.53 s ([REGEN] §0);
  - **(c)** restrict FC windows to standstill/coast, where no brake can follow within 15 ms.
- **Recommended: (c) for Path A bring-up, then (a) after an operator ruling.**

### 5.4 Run exit / Finish / State 99

| Case | Order |
|---|---|
| Run exit / Finish | P5 LOW → EN_CHG = 0 write → REGEN LOW (and FC_CHARGE LOW if in a window) |
| State 99 | **P5 LOW and CHG_QUAL LOW in phase 0**, before any switch moves |

The fw v37 State-99 phases that "drain VBUS then V-MOT into the charger" ([LOOP] §13 item 4) drain nothing into an inhibited
BQ25798. **Delete them.** Phase 1's REGEN HIGH with MOT_PWR LOW pattern must go with them.

## 6. Register sequences

I2C 7-bit address **0x6B**, 100 kHz. Multi-byte read/write auto-increments across registers ([DS] §7.3.14 p.53,
§7.3.14.7 p.55).

**Byte order of the 16-bit fields:** the field layout puts bits 15:8 at the lower offset (REG01 = VREG[10:8], REG02 =
VREG[7:0]; [DS] Figure 7-27 p.60). This is inferred from the figure. **Self-check:** at the first read, REG01:02 must read
0x03 0x48 (= 840 × 10 mV = 8.40 V, the 2S POR value) before anything is written.

### 6.1 Never-write list

| Register | Why it is never written |
|---|---|
| **REG0A** (CELL / TRECHG / VRECHG) | Writing CELL resets ICHG/VSYSMIN/VREG to that cell count's defaults. After a CELL change, REG_RST or watchdog expiry restore e.g. 12.6 V regardless of PROG ([DS] §7.3.2 p.25; Table 7-21 p.66). The board has no hardware OV action: the BQ29200 OUT is orphaned ([SPEC] §0.4). This is loop review F2 |
| **REG16** (TREG / TSHUT / VBUS_PD_EN / VAC1_PD_EN / VAC2_PD_EN) | VAC1 = VCHG-IN after M5. VAC1_PD_EN would put a 60 Ω sink on the bus path ([DS] EC p.10; Table 7-32 p.81; integration finding 5). The POR value 0xC0 is the wanted value |
| REG09 bit 6 **REG_RST** | Always written as 0 |
| REG0B-0D (OTG), REG47 | Not used |

### 6.2 Static image (written in State 0 and after any WD_STAT/POR detection; verified continuously)

| Reg | Value | Decode | Verify mask | Reset by | Source |
|---|---|---|---|---|---|
| 0x00 VSYSMIN | **0x04** | 2.5 V + 4 × 250 mV = 3.5 V (below the M8 keep-alive VCHG of 5.7 V, so no BATFET-LDO 2 A clamp) | 0x3F | REG_RST | Table 7-14 p.59; §7.3.9.2 p.42 |
| 0x01:02 VREG | **0x03 0x48** | 840 × 10 mV = 8.400 V | 0x07FF; **require ≤ 840** | REG_RST (but §7.3.2 says WD restores 8.4 V: benign) | Table 7-15 p.60; Table 7-2 p.25 |
| 0x03:04 ICHG | mode (§6.3) | 10 mA/LSB | 0x01FF | **WATCHDOG**, REG_RST (→ 1 A) | Table 7-16 p.61 |
| 0x05 VINDPM | mode | 100 mV/LSB, 3.6-22 V | 0xFF | plug-in / unplug only | Table 7-17 p.62 |
| 0x06:07 IINDPM | mode | 10 mA/LSB; clamped by the ILIM pin (EN_EXTILIM = 1) | 0x01FF | REG_RST, D+/D- detection | Table 7-18 p.63 |
| 0x08 | **0x03** | VBAT_LOWV = 0h (15 % VREG = 1.26 V: fast charge from VCHG ≈ 6 V); IPRECHG 120 mA | 0xFF | REG_RST / WD (IPRECHG) | Table 7-19 p.64 |
| 0x09 | **0x25** | REG_RST 0, **STOP_WD_CHG 1**, ITERM 5h = 200 mA | 0x7F | WD (ITERM) | Table 7-20 p.65. **Self-contradiction:** Fig 7-32 shows STOP_WD_CHG as "R-0h" while Table 7-20 says RW. **S1-B5 must prove it writable** |
| 0x0A | **read only**: expect CELL = 1h (bits 7:6 = 01) | 2S | 0xC0 | - | Table 7-21 p.66 |
| 0x0E | **0x3D** (POR) | timers: fast charge 12 h, 2× slowed in DPM | 0xFF | WD, REG_RST | Table 7-24 p.69 |
| 0x0F | **0x02** (disarmed) / **0x22** (armed) | EN_AUTO_IBATDIS 0 (no 30 mA BAT discharge pulling the M8 node down, §7.3.6 p.33), EN_CHG 0/1, EN_ICO 0, EN_HIZ 0, EN_TERM 1, EN_BACKUP 0 | 0xFF | EN_CHG WD (→ 0 with STOP_WD_CHG); EN_HIZ auto at plug-in | Table 7-25 pp.70-71 |
| 0x10 | **0x81** | VBUS_BACKUP 2h (n/a), VAC_OVP 0h (26 V, n/a with ACFETs bypassed), WD_RST 0, **WATCHDOG 1h = 0.5 s**. Kick = write **0x89** | 0xF7 | REG_RST | Table 7-26 p.72 (its own "POR: 11b" contradicts the 85h reset: write explicitly) |
| 0x11 | **0x00** | FORCE_INDET 0, **AUTO_INDET_EN 0**, HVDCP off, SDRV 0 | 0xFF | **AUTO_INDET_EN is reset by WATCHDOG** (→ 1) | Table 7-27 p.73. Corrects [DOS] §3 ("REG_RST only") |
| 0x12 | **0x04** | EN_OTG 0, PFM_FWD_DIS 0 (S1-B4 may require 1), **DIS_LDO 1**; DIS_ACDRV not asserted by firmware | 0x7F (bit 7 excluded: reset by VAC < VAC_PRESENT) | WD (EN_OTG, DIS_LDO) | Table 7-28 p.75 |
| 0x13 | **0x01** | ACDRV off, PWM_FREQ 0 (1.5 MHz), STAT enabled, FORCE_VINDPM_DET 0, EN_IBUS_OCP 1 | 0x3F | REG_RST / WD (DIS_STAT) | Table 7-29 pp.76-77 |
| 0x14 | **0x16** (POR) | SFET_PRESENT 0 (locks EN_BATOC, SDRV), **EN_IINDPM 1, EN_EXTILIM 1** | 0xFF | EN_IINDPM WD | Table 7-30 pp.78-79. Read each pass: a single slip in bit 2 would remove input regulation (loop F4) |
| 0x15 | **0xAA** (POR) | EN_MPPT 0 | 0x01 | REG_RST | Table 7-31 p.80 |
| 0x16 | **read only**: expect bits 3:1 = 000 | no VBUS/VAC pull-downs | 0x0E | - | Table 7-32 p.81 |
| 0x18 | **0x54** (POR), TS_IGNORE 0 | TS active | 0x01 | WD | Table 7-34 p.83 |
| 0x2E | **0xA0** | ADC_EN 1, continuous, 13-bit (6 ms/channel) | 0xFC | **ADC_EN reset by WD** | Table 7-55 p.113 |
| 0x2F | **0x08** | VSYS ADC off; IBUS, IBAT, VBUS, VBAT, TS, TDIE on | 0xFE | - | Table 7-56 p.114 |
| 0x30 | **0xF0** | D+, D-, VAC2, VAC1 ADC off | 0xF0 | - | Table 7-57 p.115 |

**Write blocks:**
- **0x00-0x09:** one 10-byte write. VINDPM is included but is overwritten at the next plug-in, which is harmless.
- **0x0E-0x15:** one 8-byte write.
- **0x18:** single byte.
- **0x2E-0x30:** one 3-byte write.

No block touches 0x0A or 0x16.

**ADC refresh:** 6 channels × 6 ms = 36 ms (≈ 28 Hz) ([DS] EC p.16, tADC_CONV). `I_charge` stays in the 50 Hz telemetry as
a held value refreshed at 28 Hz. ADC_SAMPLE 3h would halve that, but TI marks it "not recommended". **The ADC has no accuracy
specification**, and "readings are only valid for DC states and not for transients" ([DS] §7.3.10 p.47) → S1-B9.

### 6.3 Mode images

| Field | Regen armed | FC window (standstill) | FC window (cruise) | Disarmed |
|---|---|---|---|---|
| VINDPM REG05 | **0xBE = 19.0 V** (±2 % → 18.62-19.38 V, EC p.12) | **0x87 = 13.5 V** (≈ ±2.6 % interpolated → 13.14-13.86 V) | 0x87 | left |
| IINDPM REG06:07 | **0x00 0x7D = 1.25 A** (effective min(reg, pin) = 1.15-1.25 A) | **0x00 0x5A = 0.90 A** | min(0.90, 1.20 - I_aux - I_trac,filt - 0.10) A, rewritten at 50 Hz with readback; window closes if < 0.30 A | left |
| ICHG REG03:04 | **0x00 0xFA = 2.50 A** | **0x00 0xA0 = 1.60 A** | 1.60 A | left (WD → 1 A) |
| REG0F | 0x22 | 0x22 | 0x22 | **0x02** |

- **Why 19.0 V and not 20.0 V:**
  - 20.0 V (19.6-20.4 V) would put VINDPM above the TPS61288 OVP maximum (19.5 V, [TPS] p.6), but it halves the
    VINDPM → VESC-cut window (21.35 - 20.4 = 0.95 V vs 1.97 V), and with it the τ budget ([REGEN] §5).
  - H1 already blocks a failed-FB bus: its fall trip at VBUS 19.5 V is ≥ 20.52 V ([LOOP] §7).
  - Revisit if M-R0 raises the VESC cut-off.
- **IINDPM accuracy** is specified only at VBUS 9 V (1.0 A → 0.88-1.00 A, [DS] EC p.12). The 15.8 V figure is
  TODO(verify: bench S1-B9).

### 6.4 Watchdog, kick and POR handling

- **Charger watchdog:** 0.5 s with STOP_WD_CHG = 1, so expiry sets EN_CHG = 0 ([DS] Table 7-20 p.65, Table 7-26 p.72).
  - It is kicked **once per 20 ms poll**, only in an iteration where `detectFaults()` and the 1 kHz interlock have already
    run. Margin: 25 polls.
  - Accuracy is specified only at 160 s ([DOS] §2.3). The 0.5 s tolerance is BENCH (S1-B5).
- **What the watchdog resets** (tables above):
  - EN_CHG → 0;
  - ICHG → 1 A;
  - ITERM, IPRECHG, timers;
  - **AUTO_INDET_EN → 1**;
  - EN_IINDPM → 1;
  - DIS_LDO, ADC_EN → 0;
  - TS_IGNORE → 0;
  - TREG/TSHUT;
  - EN_OTG → 0.
  - **It does not reset:** VINDPM, IINDPM, VSYSMIN, WATCHDOG, EN_EXTILIM, EN_MPPT, STOP_WD_CHG.
  - **VREG: the datasheet contradicts itself** (§7.3.2 p.25 vs Table 7-15). Treat it as possibly reset (benign at 8.4 V).
- **Detection rule:**
  - **Triggers:** WD_STAT (REG1B[5]) = 1, WD_FLAG, any masked-image mismatch, VBAT_PRESENT/VBUS_PRESENT/PG changes, or
    REG01:02 = 0x0348 together with ICHG = 1 A while armed.
  - **Response:** **P5 LOW first**, then rewrite the static and mode images, verify, and re-arm only via §5.1 steps 4-6.
  - **On a POR (pack reconnect):** read REG48 (part information), then write the full static image before anything else.
- **Poll schedule** (20 ms frame, 1 kHz loop, ≤ 1.4 ms blocking per slot at 100 kHz):

  | Slot | Action | Time |
  |---|---|---|
  | 0 | REG1B-REG21 status (7 B) | ~1.0 ms |
  | 5 | critical verify: REG00-REG0A (11 B), loop F2 | ~1.3 ms |
  | 10 | ADC REG31-REG36 (IBUS, IBAT, VBUS) + REG41 TDIE | ~1.2 ms |
  | 15 | WD kick (REG10 = 0x89); every 5th frame, extended verify REG0E-REG19, REG2E-REG30 in parts | ~0.3-1.4 ms |

  Blocking Wire is the existing `pollAg105()` pattern. A non-blocking LPI2C driver is a recommended follow-up.

## 7. Firmware architecture sketch (not edited into the .ino)

```cpp
// ---- pins (CSV first) ----
#define CHG_ARM        5    // was MPPT_DISABLE; HIGH = arm (-> PERMIT AND)
#define CHARGER_STAT   6    // BQ25798 STAT open-drain, LOW = charging; INPUT_PULLUP
#define CHG_QUAL      10    // HIGH = release ILIM_HIZ for input qualification
#define CHG_H2_RB     16
#define CHG_PERMIT_RB 33
#define CHG_H1_RB     34
#define BQ_ADDR       0x6B  // SLUSDV2C §7.3.14 p.53

enum class ChgMode : uint8_t { OFF, QUAL_REGEN, ARMED_REGEN, XFER, QUAL_FC, ARMED_FC, TRIPPED };

struct BqImage { uint8_t blk0[10]; uint8_t blk1[8]; uint8_t r18; uint8_t adc[3]; };   // §6.2
class Bq25798 {
 public:
  bool writeStatic();                       // blocks 0x00-0x09, 0x0E-0x15, 0x18, 0x2E-0x30; never 0x0A/0x16
  bool writeMode(float vindpm, float iindpm, float ichg, bool enChg);  // + readback
  bool verifyCritical();                    // REG00-0A masked; VREG<=840; CELL==1h; EN_EXTILIM/EN_IINDPM==1
  bool verifyExtended(uint8_t part);        // REG0E-19, 2E-30, REG16 bits3:1==0, REG19 ICO_ILIM
  bool kick();                              // REG10=0x89
  bool readStatus(BqStatus&);               // REG1B-21
  bool readAdc(BqAdc&);                     // IBUS REG31, IBAT REG33, VBUS REG35, TDIE REG41
  bool wdOrPorSeen() const;
};

// 1 kHz, every loop, after detectFaults():
void chargerInterlockTick() {
  const bool h1 = digitalReadFast(CHG_H1_RB), pm = digitalReadFast(CHG_PERMIT_RB), h2 = digitalReadFast(CHG_H2_RB);
  // F1: cross-check against calibrated ADCs (V_rgn 0.85x MUST be calibrated first, gate M8/[LOOP])
  const bool h1Pred = V_rgn_cal > 1.067f*V_bus + 0.15f;          // mid-hysteresis prediction
  const bool h1Clear = V_rgn_cal < 1.067f*V_bus - 0.45f;          // definitely-0 band
  if ((h1 && h1Clear) || (!h1 && h1Pred && V_rgn_cal > V_bus + 1.5f)) mismatchMs++; else mismatchMs = 0;
  if (h2 != expectH2()) h2MismatchMs++; else h2MismatchMs = 0;
  if (pm && !digitalReadFast(CHG_ARM)) tripCharger(ERR_CHG_PERMIT_STUCK);   // PERMIT without ARM = logic fault
  if (mismatchMs > 5 || h2MismatchMs > 5) tripCharger(ERR_CHG_H_MISMATCH);
  if (chgMode == ChgMode::ARMED_FC && I_fc > 1.20f) digitalWriteFast(CHG_ARM, LOW);  // raw-sample escape, same tick
  jGuardsTick();                                                   // G1..G3 below
}

void tripCharger(ErrorCode_t e) {   // reboot-only latch (fw v37 rev 2 J-trip semantics)
  digitalWriteFast(CHG_ARM, LOW); digitalWriteFast(CHG_QUAL, LOW);
  chgTripLatched = true; requestState99(e);                        // State 99 opens REGEN/FCC in its phases
}
```

### 7.1 Mode manager

`chargerModeTick()` is a non-blocking step machine implementing §5.1-§5.4.
- One I2C transaction per tick at most.
- Timeouts:
  - PG_STAT within 400 ms of REGEN/FCC close, otherwise disarm + flag;
  - VINDPM landed within 200 ms;
  - readback mismatch → retry once → disarm.
- `chargingControl()` keeps `charge_goal` as intent: 0 → regen-only; > 0 → FC windows allowed under the §6.3 schedule.
  **Regen arming no longer depends on `charge_goal`** (ruling 1).
- `AG105_VBATN_ISOLATED` becomes `CHG_RETURN_VERIFIED` (true for this EVM, [DOS] §2.1). REGEN may be held through Run only
  if the CSV carries the new readback pins, the interlock reports the carrier present, and the power-on self-test passes
  (§9 S5-a).

### 7.2 J-guard port

| Guard | Condition | Rate |
|---|---|---|
| G1 | bus-side I_fc + I_batt > 1.0 A for 5 ms during any **bench charger session** | 1 kHz |
| G1-Run | in Run, an armed regen burst must not raise I_fc + I_batt by > 0.3 A over the pre-burst value | 1 kHz |
| G2 | unaccounted bus power > 3 W for 20 ms: V_bus × (I_fc + I_batt) − P_traction,est − P_aux − P_chg_in, with **P_chg_in = IBUS × VBUS from REG31/REG35** | 28 Hz ADC; P_traction from VESC telemetry, rate TODO(verify) |
| G3 | REG20/REG21 faults (VBUS_OVP, VBAT_OVP, IBUS_OCP, CONV_OCP, VSYS_SHORT, VSYS_OVP, TSHUT) or timer faults (REG1E); also EN_HIZ auto-set in Run → harvest-lost flag | 50 Hz |
| Trip latch | P5 LOW, QUAL LOW, State 99; cleared only by reboot | - |

`FAULT_SWITCH_CONFLICT` is enabled in **all** builds (today it sits inside `#if !BENCH_TEST`, [LOOP] §13 item 1).

### 7.3 Telemetry: forced protocol bump to v5

The v4 layout's `charger_status` (offset 51) and `I_charge` (offset 19) are Ag105 semantics ([FW] ~7634). The proposal
below **must go through the `protocol-bump` procedure, with the Pi bridge updated in lockstep.**

| Offset | Bytes | Field |
|---|---|---|
| 0-50 | as v4 | unchanged except **19 `I_charge` = BQ25798 IBAT (REG33, A, float)** |
| 51 | 1 | `charger_status`: bits 0-2 CHG_STAT (REG1C[7:5]), 3 PG_STAT, 4 VINDPM_STAT, 5 IINDPM_STAT, 6 any REG20/21 fault, 7 image verified |
| 52 | 1 | switch_state (unchanged) |
| 53 | 2 | fault_flags (+ new bits: CHG_H_MISMATCH, CHG_PERMIT_STUCK, MCU_WDT) |
| 55 | 1 | error_code (+ ERR_CHG_H_MISMATCH, ERR_CHG_PERMIT_STUCK, ERR_MCU_WDT) |
| 56 | 1 | error_source_state |
| **57** | 2 | `chg_in_ma`: IBUS REG31, int16 mA |
| **59** | 2 | `chg_vbus_mv`: VBUS REG35, uint16 mV |
| **61** | 1 | `chg_ctrl`: bit 0 ARM cmd, 1 PERMIT rb, 2 H1 rb, 3 H2 rb, 4 QUAL, 5 mode FC, 6 trip latch, 7 charger WD seen |
| **62** | 1 | `chg_fault`: REG20 raw |
| **63** | 1 | `chg_vindpm`: REG05 readback (100 mV/LSB) |
| **64** | 1 | checksum, XOR of bytes 1-63 |

**v5 = 65 bytes.** BLG gains the same fields (BLG v10) via its own procedure.

### 7.4 MCU HARDWARE WATCHDOG: REQUIRED FUTURE WORK (operator ruling 5)

**Status:** this is not implemented in fw v37 rev 2 (only the Pi watchdog exists, [LOOP] §10). **Path A may not run an
unattended charger session until it is implemented and has passed the bench test below.** The charger's own 0.5 s watchdog
complements it but does not replace it: it stops charging, but it does not open the RT1987 paths or stop the motor.

| Item | Specification |
|---|---|
| Primary timer | **RTWDOG (WDOG3)**, 32 kHz LPO clock, **TOVAL 3200 = 100 ms**. Maximum without prescaler: 65535 ticks = 2.048 s ([WDT] `begin()` WDT3 path) |
| Secondary timer | **WDOG1 at 1.0 s** (range 0.5-128 s in 0.5 s steps, [WDT] WDT1 path), independent of RTWDOG. **WDOG1_B must NOT be routed to pin 19 (I2C SCL).** Pin 20 is acceptable if a hardware WDOG_B is wanted (CSV first) |
| Optional | EWM output on pin 21 as a sixth AND input to PERMIT, so a hang removes the permit before the reset. EWM polarity is TODO(verify: i.MX RT1060 RM) |
| Feed policy | Exactly once per `loop()`, after `detectFaults()`, `chargerInterlockTick()` and the switch writer have all run in that iteration. Never from an ISR or timer callback. No feed inside blocking calls: budget them instead (SdFat sync, EEPROM commit, I2C to the charger ≤ 1.4 ms, Serial) |
| Timeout bound | 100 ms > the longest legitimate stall. To be measured with a loop-period histogram before enabling (SdFat close and EEPROM commit durations are TODO(verify: PJRC)) |
| Reset behaviour | System reset; cause read from SRC_SRSR (WDOG3_RST_B) ([WDT] `expired()`). From reset until `setup()`, the 10 kΩ EN pull-downs hold every RT1987 off (VEN_F min 0.6 V, [RT] p.7). The carrier's P5 and QUAL 47 k pull-downs keep PERMIT LOW. Pad keeper state after reset is TODO(verify: i.MX RT1060 RM IOMUXC); boot time is TODO(verify: PJRC) |
| After a WDT reset | Boot to State 0; latch **ERR_MCU_WDT** in telemetry (v5 bits above); **require Pi or operator acknowledgement before Run**. Re-bring-up through the existing staged bring-up and `assertMotPwrEnable()`/`motPwrHotPlugUnsafe()` guards. The charger re-images from §6.2 with P5 LOW |
| Host test | Mock RTWDOG counter: assert no feed on any iteration that skipped `detectFaults()`; assert ERR_MCU_WDT latches and blocks Run until acknowledged |
| Bench test (gate S3-W) | State-98 hang key that spins forever with P5, REGEN and BT_BUS HIGH. **Pass:** reset within 100 ms (+ clock tolerance, TODO(verify: RM)); every EN < 0.6 V within 1 ms of reset; PERMIT and ILIM_REL LOW; ERR_MCU_WDT reported after boot. Repeat with the WDOG1-only configuration (≤ 1.0 s) |

### 7.5 Driver replacement scope

**Removed:**
- `pollAg105()`, `initAg105Charger()`, `ag105IsReady()`;
- the reg-0x02 MPPT ratchet and the `N` key;
- `AG105_ADDR`;
- the Ag105 telemetry semantics;
- about 60 charger/`J` tests (about 1340 lines referencing Ag105 symbols, integration finding 12).

**Added:**
- the driver and the mode manager;
- the interlock;
- the guards;
- the HIL plant charger model (VINDPM-gated behind H1, replacing the threshold/MPPT Ag105 model);
- telemetry v5 and BLG v10;
- tests for every invariant (I-1 to I-5), the never-write list, the masked verify, the WD re-image, and the brake-edge
  transition.

### 7.6 State 98

- `'4'` (the raw pin-5 toggle) is removed.
- `'M'`-style pin-5 access goes only through the mode manager.
- **The new `J` is an FC-path session:** BT_BUS 0, REGEN 0, FCC 1, H2 in force, with G1-G3 and the trip latch.
- **New `'V'`:** prints the image, the readbacks, PERMIT/H1/H2, REG19 and the ADC values.
- `'5'` (FC_CHARGE) refuses a cold close in Run and pre-energizes via REGEN first (§8.1).

## 8. Quantitative checks

### 8.1 Inrush

| Case | Calculation | Result |
|---|---|---|
| Cold close of either path | C = 70.2 µF nominal × 12.0 mA/µF (RT1987 slew, CSS 5.6 nF, [SPEC] §6; [RT] §17.3) | **0.84 A** for ~1.3 ms |
| Run-entry REGEN close | Sourced by CAL, refilled through D-MT-EN by both boosts | Not an OC_FC single-sample risk |
| Cold FC close from an FC-only bus | 0.84 + I_aux 0.15 | 0.99 A against the 1.0 A budget and OC_FC 1.4 A: 1 % margin, and tON is typical-only ([RT] p.7) → **forbidden in Run** |
| Warm FC close (§5.2) | ΔV ≤ 0.6 V | ≤ 50 µs at ≤ 0.84 A |

Gate S5-c measures it. **Death-5 class: no.** There is no bulk capacitance; 0.84 A is far below the RT1987 SCP of 2.5 A
([RT] p.15).

### 8.2 Threshold margin stack-up (regen mode)

| Item | Value | Source |
|---|---|---|
| VBUS steady max | 16.23 V (VREF + 2 %); 16.39 V if RD1 is 1 % | [LOOP] §4.2 |
| VBUS transient (load-dump park) | 17.2 V, ≤ 5 ms above 17.0 V | [LOOP] §4.2 |
| D-MT-EN | V-MOT ≈ VBUS - 35 mV in cruise (favourable) | [RT] p.7 |
| H1 rise / fall worst | 17.83 / 17.19 V at VBUS 16.39 V | §3.2 |
| VINDPM (sensed at VCHG-IN) | 18.62-19.38 V | [DS] EC p.12 |
| D-BC-RG + trace drop at 1.25 A | 35 mV + 1.25 × (20 + 35) mΩ ≈ 0.10 V → V-MOT holds at 18.72-19.48 V | [SPEC] §2.1 |
| V-MOT ripple | **unmeasured** (M4). H1 hysteresis 0.30 V; filter 24 µs | [LOOP] §4.2 |
| VESC OV cut (apparent) | ≈ 21.35 V (UNCONFIRMED mechanism) | [REGEN] §0 |
| Chopper design clamp | 21.98-22.28 V (measured peaks 21.2-21.5 V, unclamped) | [REGEN] §0 |
| BQ25798 VBUS_OVP min | 25.2 V; 24 V recommended max; 30 V abs max | [DS] p.7, p.9 |

| Margin | Value |
|---|---|
| VINDPM_min - VBUS steady max | 18.62 - 16.39 = **2.23 V** |
| VINDPM_min - transient | **1.42 V** |
| VINDPM_min - fw OV latch 17.5 V | **1.12 V** |
| VINDPM_min - TPS61288 OVP min 18.3 V | **0.32 V** (VINDPM alone does not cover a failed-FB boost; H1 does, [LOOP] §7) |
| H1 rise max - VINDPM_min | 18.62 - 17.83 = **0.79 V** (absorption never chatters H1) |
| VESC cut - V-MOT hold max | 21.35 - 19.48 = **1.87 V** (the τ budget headroom) |
| BQ VBUS_OVP min - design clamp max | 25.2 - 22.28 = **2.9 V**; to the 24 V recommended max: **1.7 V** |

### 8.3 Inhibit-latency budget

- **Budget:** C_VMOT ≥ 0.4 mF, I_in ≤ 1.25 A (the regen IINDPM). The time from VINDPM_min to the bus is ≥ 348 µs
  ([LOOP] §4.3 scaled by 1.5/1.25).
- **Allocations:** TLV3012B ≤ 4 µs, LVC ≈ 0.01 µs, gate RC ≤ 20 µs.
- **Charger allowance:** /CE-HIGH or ILIM_HIZ-LOW to IBUS < 10 % must be **≤ 320 µs**. That is S1-B3, and the faster of the
  two pins counts.
- **If slower:** one bounded pulse per event, never sustained.

### 8.4 Regen capture estimate

**Charger ceiling:**
- Input clamp 1.15-1.35 A × V-MOT ≥ 18.62 V ⇒ **≥ 21.4 W of input**.
- About 91 % efficiency at 20 V (Fig 6-4 p.18, figure reading, typical) ⇒ ≥ 2.37 A charge (ICHG cap 2.50 A).
- This covers the 3 → 1 m/s, 12 A brake (peak 18.9 W electrical) ([REGEN] §0 item 4, §3).

**Capture, if S0-R3 shows the VESC keeps braking with V-MOT held at 19 V, and S1-B4 passes:**

| Decel | Capture of the mechanics-limited energy | Into the pack per decel |
|---|---|---|
| 2 → 1 m/s | **96-99 %** ([REGEN] §0 item 5, C = 0.97 mF) | ≈ 1.74-1.79 J (207-213 mC) |
| 3 → 1 m/s | 96-99 % | ≈ 5.3-5.5 J (634-655 mC) |

In SoC terms that is 1.2e-5 to 3.7e-5 per decel on a 5 Ah pack (capacity unverified) ([REGEN] §6).

**Warm-response budget:**
- **t_resume** (H1 rising → converter switching under VINDPM): hidden by the H1→VINDPM head start of 1.33 V at
  115-285 V/s = **4.7-11.6 ms**. Requirement: ≤ 4.5 ms (S1-B4r).
- **τ_warm** after V-MOT crosses VINDPM: **≤ 4 ms** (10-90 % ≤ 9 ms) at C = 0.97 mF; ≤ 2 ms if C is board-only (0.49 mF)
  ([REGEN] §5).

**If either fails:** the cliff applies. The VESC trips, coasts for 0.53 s, and capture falls to 6-40 %.

**If S0-R3 fails** (the pulse still ends after 30-50 ms with the node held at 19 V): at most ~20 mC (0.17 J) per decel, for
any charger ([REGEN] §7 M-R3).

**FC charging:**
- Standstill: IINDPM 0.90 A at 15.8 V, ~93.5 % (Fig 6-4, figure reading) ⇒ **1.58 A charge**. Bus side 0.90 + 0.15 =
  1.05 A, under the governor ceiling 1.25 A, the H-20 P_MAX ≈ 1.247 A bus-equivalent, and OC_FC 1.4 A.
- Cruise: reduced by traction (§6.3). The EMS models must use this budget, not "2 A".

### 8.5 Thermal

| Case | Calculation | Result |
|---|---|---|
| FC charge 1.6 A × 8.4 V = 13.4 W out at ~93 % | loss ≈ 1.0 W; ΔT ≈ 1.0 × 44.2 °C/W (JEDEC RθJA, [DS] p.8; the EVM copper is better) ≈ 45 °C | TJ ≈ 70-75 °C at 25-30 °C ambient, well under TREG 120 °C ([DS] Table 7-32 p.81) |
| Regen bursts | 23 W × 9 % ≈ 2.1 W for ≤ 0.6 s | Negligible |
| L2 | 11.1 A rated ([UG] BOM p.22) | - |
| D-BT-SQ | 2.5 A² × 20 mΩ = 125 mW | - |
| M8 | normal 3 mW; fault 70 mW | - |

Gate S1-B8 logs TDIE (REG41).

### 8.6 CV error through D-BT-SQ

- VREG 8.400 V at the BAT pin (JP9 2-3); accuracy -0.25/+0.65 % ([DS] EC p.11) → **VCHG 8.379-8.455 V**.
- Path to the pack:
  - D-BT-SQ regulation: 35 mV light load ([RT] p.7);
  - 2.5 A × 20 mΩ = 50 mV at full current;
  - lead drop 0.6 m × 21 mΩ/m × I = 31 mV at 2.5 A, ~2.5 mV at ITERM 200 mA.
- **Pack at termination: 8.34-8.42 V.** That is 0.2-0.7 % under 8.40 V and below `LIMIT_V_BATT_MAX` 8.5 V.
- **Do not trim VREG upward:** the +0.65 % tolerance would already reach 8.455 V at VCHG ([SPEC] §2.2).
- VBAT_OVP is 103-105 % of VREG, measured at VCHG ([DS] EC p.12). It is not a pack-side backstop. **The firmware OV_BATT
  latch (8.5 V) is the only pack-side OV action** on this board.

## 9. Staged bench plan (each stage is a go/no-go gate)

Scope-armed first power at every new stage (ruling 4). Equipment: bench PSU (≥ 24 V, 3 A); a second PSU or electronic load
capable of a 16 → 21 V step with < 1 ms rise; the pack (or a Kepco/2-quadrant battery simulator); an RT1987 stand-in (a
spare RT1987 EVB or a Schottky + 5.6 nF-CSS RT1987 on perfboard); a 4-channel scope; a 30 A current probe; a 0.01 Ω shunt
(EVM R13, TP19/TP20); DMMs.

### Stage S0: no-new-hardware measurements on the vehicle (prerequisites, decide the regen requirement)

| Gate | Test | Pass |
|---|---|---|
| S0-R0 (= M-R0) | State-98 `U` fault watch during a 2 → 1 m/s, 12 A step decel; read VESC Tool Maximum Input Voltage, Fault Stop Time and the fault log | Mechanism identified (OV fault + fault-stop yes/no) and l_max_vin recorded |
| S0-R1 (= M-R1) | V-MOT capacitance (bring-up decay with a known load, or LCR with the VESC unpowered) | C_VMOT known to ±20 %. Sets the τ requirement (2/4/20 ms) |
| S0-R2 (= M-R2) | Scope true V-MOT vs pin 39 at ~21 V; calibrate V_rgn | Ratio known to < 1 %. **Required before F1 is trusted** |
| S0-R3 (= M-R3) | Electronic load in CV mode at 19.0 V, 1.3 A limit, on V-MOT; hard decel | **GO if braking continues (V-MOT held at 19 V for ≥ 0.25 s at 2 → 1 m/s). NO-GO for regen if the pulse still ends after 30-50 ms**: stop and escalate (VESC config, Path B) |
| S0-M3 | RT1987 turn-off delay (D-BT-EN, D-BC-RG) | Measured. It replaces the 100 µs constant |

### Stage S1: standalone EVM (bench supply + stand-in + pack + load), after M1-M11

| Gate | Test | Pass |
|---|---|---|
| S1-0 | Power-up from the pack only via M8 (VIN unpowered): read REG48, REG01:02 = 0x03 0x48, REG0A CELL = 1h, REG13 PWM_FREQ = 0; write and verify §6.2 | All match; I2C works with board-equivalent 10 k pull-ups at 100 kHz |
| S1-B0 | /CE and ILIM_HIZ levels with the stages fitted: PERMIT and ILIM_REL driven, floating and unpowered | /CE ≥ 2.9 V when not permitted; ILIM_HIZ ≤ 0.2 V when not released (REGN up); 1.92-2.08 V when released |
| S1-B1 | I(VIN) from a stiff 15.9 V and 18.5 V source, VINDPM 19.0 V: (a) both inhibits on, (b) released + /CE LOW | (a) ≤ 1 mA; (b) ≤ 5 mA ([DS] IQ_VBUS); IBAT = 0 ± 10 mA in both |
| S1-B2 | VINDPM retention: write 19.0 V; 1000 ILIM_HIZ + /CE cycles; input dip to 12 V and back | REG05 unchanged; no PG loss; no EN_HIZ auto-set |
| S1-B3 (M2) | Inhibit latency at 1.25 A input / 2.5 A charge: step /CE HIGH alone; step ILIM_HIZ LOW alone | IBUS < 10 % in **≤ 320 µs** for at least one pin, and both pins stop within 1 ms |
| S1-B4 (= M-R4) | **Warm step:** charger idle at Vth - 0.5 V (18.5 V), released, /CE LOW; step the input to 20.0 V from a stiff source | **τ_warm ≤ 4 ms (10-90 % ≤ 9 ms)**, or the S0-R1-derived limit; no soft-start or re-qualification visible (PG stays 1) |
| S1-B4r | Resume case: input at 17.5 V with ILIM_HIZ held LOW, then release ILIM_HIZ and /CE together and ramp the input 17.5 → 20 V at 285 V/s | Charge current reaches 63 % of ICHG **≤ 4 ms after V crosses 19.0 V**; converter switching ≤ 4.5 ms after release |
| S1-B5 | Charger WD: 0.5 s, STOP_WD_CHG = 1; stop kicking during a 1.6 A charge | STOP_WD_CHG reads back 1 (writability proven); charging stops between 0.4 and 1.0 s; EN_CHG reads 0 |
| S1-B6 | Qualification with CHG_QUAL HIGH: REG19 ICO_ILIM | 1.15-1.35 A; and 0.10 A when deliberately qualified with ILIM held LOW (proves the mechanism) |
| S1-B7 | M8 node: 10 s with /CE HIGH and ILIM_HIZ LOW (cruise state), then a burst | VCHG ≥ 3.5 V throughout; first pack current ≤ 4 ms after release. **If it fails**, switch stage A to P5-only (§10.2 variant) or bridge D-BT-SQ, then retest |
| S1-B8 | Thermal: 1.6 A FC charge at 15.9 V for 30 min + a 1 Hz burst train for 5 min | TDIE < 100 °C; TREG_STAT 0 |
| S1-B9 | ADC: IBAT/IBUS/VBUS vs shunt and DMM, DC, 50 ms pulses and burst integrals | Errors recorded for the EMS (no pass level: characterization) |
| S1-C | CV/termination through the RT1987 stand-in into the pack | Pack 8.34-8.42 V at termination; firmware clears EN_CHG at CHG_STAT 7h |

### Stage S2: Teensy control (bench Teensy + carrier + EVM + stand-in, no vehicle)

| Gate | Test | Pass |
|---|---|---|
| S2-a | Run the §5.1-§5.4 sequences against the bench supply (V-MOT and VBUS emulated by two supplies on the carrier taps) | Every invariant I-1 to I-5 holds in a logic-analyser capture; arm latency ≤ 0.4 s |
| S2-b | H1 trip points: sweep the V-MOT supply with VBUS at 15.9 / 16.4 / 19.5 V | Within §3.2 worst case; hysteresis 0.25-0.35 V |
| S2-c | H2 truth table over all 16 input combinations, plus BT_ACT at 0.1/0.2/0.3 A injected | Matches §3.3 |
| S2-d | Firmware F1 cross-check: inject an H1 stuck-high (jumper) | Trip within ≤ 6 ms |

### Stage S3: loop-impossibility tests (forced failures, bench, current-limited supplies)

The bench emulates the loop: PSU-A = "bus" through an RT1987 stand-in to the charger input; PSU-B = "pack" with an
electronic load as the "BT boost back to bus" path. Limit PSU-A to 2 A.

| Gate | Forced failure | Pass |
|---|---|---|
| S3-a | Teensy reset held (RESET low) with "REGEN" and "BT_BUS" emulated HIGH | IBAT = 0; /CE HIGH; IBUS ≤ 5 mA |
| S3-b | Teensy hang key (P5 HIGH frozen), V-MOT = VBUS | IBAT = 0 (H1 = 0); charger WD stops charging ≤ 1.0 s if H1 is forced high |
| S3-c | SDA held LOW (I2C dead) | P5 never rises; IBAT = 0 |
| S3-d | Comparator unpowered; comparator output shorted LOW; H1 forced HIGH with VINDPM 19 V and V-MOT = VBUS 15.9 V | (1)(2) IBAT = 0; (3) IBUS ≤ 5 mA (the soft layer holds) and F1 trips ≤ 6 ms |
| S3-e | Carrier 3V3 removed while armed | /CE HIGH, ILIM_HIZ LOW within 1 ms |
| S3-f | REG05 deliberately written to 14.0 V (below the bus) while armed, V-MOT = VBUS | IBAT = 0 (H1); verify-mismatch → disarm within 20 ms |
| S3-W | MCU WDT (once implemented, §7.4) | §7.4 bench pass criteria |

### Stage S4: integration on the board, vehicle on stands, motor unloaded

- **Instrumentation:** scope on V-MOT, VCHG-IN, VCHG and VBUS (true scale); current clamp on the pack lead; INA253 FC and BT
  outputs.

| Gate | Test | Pass |
|---|---|---|
| S4-a | Power-on self-test ([LOOP] M7): FCC = REGEN = 0 → V_chg decays toward 0; Idle H1 = 0; BT_BUS = 0 → BT_ACT = 0 | All pass every boot |
| S4-b | Run entry with regen armed, cruise 60 s at 0.5-1.5 m/s | IBAT = 0 ± 20 mA; I_batt and I_fc unchanged vs fw v37 (± 50 mA); no G1/G2/G3 trip |
| S4-c | Warm FC transitions at standstill (§5.2/§5.3), 20 cycles | I_fc peak < 1.2 A on the scope; no OC_FC; no UV_BUS; charge 1.5-1.6 A |
| S4-d | 30 min FC window at standstill | Pack current matches IBAT (S1-B9 error); TDIE logged |

### Stage S5: real regen decels (vehicle on the ground or a roller)

| Gate | Test | Pass |
|---|---|---|
| S5-a | 2 → 1 m/s step at 5 A, then 12 A, 10 each | V-MOT holds at 18.7-19.5 V; no VESC OV cut (no second pulse at +0.53 s); pack-lead clamp shows a charge pulse; **captured ≥ 80 % of the S0-R3-predicted energy**; no bus current rise during bursts (G1-Run) |
| S5-b | 3 → 1 m/s, 12 A | Same; IBAT ≤ 2.5 A; no IINDPM-saturated V-MOT rise to 21.35 V |
| S5-c | VESC abrupt stop mid-burst (`setCurrent(0)`) | Bus current pulse into V-MOT ≤ 1.25 A × (t_inh - 0.35 ms) (scope VBUS→V-MOT via the D-MT-EN drop) |
| S5-d | A drive cycle with steeper-than-coast-down decels (0.65-1.03 m/s² coast-down, [REGEN] §6) + an FC window | EMS sees I_charge per event; no trip |

**Exit criteria for "Path A feasible":** S0-R3, S1-B3, S1-B4/B4r, S1-B5, S1-B7, S3-all and S5-a pass. S3-W is needed before
any unattended session.

## 10. Cost, parts, schedule, residual risks

### 10.1 Parts (stock = TI store, 2026-11-05 20:02 UTC, plain curl; non-TI stock UNKNOWN: Mouser/Farnell unreachable)

| Part | Qty | Unit | Stock | Note |
|---|---|---|---|---|
| **BQ25798EVM** | 2 (one to modify and test, one to characterize/spare) | USD 156.45 ([DOS] §2.11) | **162** | BQ25792EVM 131 in stock (no MPPT/backup; not evaluated) |
| TLV3012BIDBVR / TLV3012BIDCKR | 2 + 2 spare | ~USD 1 (TODO(verify: price)) | 27 694 / 144 621 | - |
| SN74LVC1G27DCKR | 1 + spare | - | 1 050 765 | NOR3 |
| SN74LVC1G08DCKR | 2 + spare | - | 863 376 | AND |
| SN74LVC1G32DRLR | 2 + spare | - | 937 821 (DBVR: only 54) | OR |
| BSS138 / 2N7002, SOT-23 | 3 + spares | - | UNKNOWN (non-TI) | TI alternative CSD15380F3 (741 151), but it is an LGA FemtoFET and impractical to hand-solder; Vgs(th) TODO(verify) |
| 0.1 % resistors: 499 k, 464 k, 56.2 k ×2; 6.49 M 1 %; 61.9 k, 1.00 k | 1 set ×2 | - | UNKNOWN | - |
| 150 k 1 % 0603 (R21) | 1 | - | UNKNOWN | - |
| 10 µF ≥ 35 V X7R 0805 (EVM C11, C12, C29-C31) | 5 + spares | - | UNKNOWN | - |
| 10 µF 35 V X7R 1206 (board C-D8, C-D10) | 2 | - | UNKNOWN | Same type as C-D6/C-D7 (BOM) |
| 1.0 k 0.25 W (M8) | 1 | - | - | Pending operator approval |
| Wire: 18 AWG and 20 AWG twisted pairs, 26 AWG bundle; carrier perfboard | - | - | - | - |

**Estimated cost:** about USD 313 (two EVMs) + ~USD 40 parts + optional carrier PCB ~USD 30 ⇒ **≈ USD 350-400**.

### 10.2 Schedule estimate

| Step | Duration |
|---|---|
| Order lead (TI in stock; distributor parts unknown) | 3-7 days |
| S0 measurements, in parallel with ordering (no new hardware) | 2-3 bench days |
| EVM mods + carrier build | 2-3 days |
| S1 | 4-5 bench days |
| Firmware: driver + mode manager + interlock + guards + v5 + tests (orchestrated round) | 2-3 weeks |
| S2-S3 | 3-4 days |
| S4-S5 | 3-5 days |
| MCU WDT (§7.4) | +1 week, before unattended use |
| **Total** | **≈ 5-7 weeks** to the Path A exit criteria |

**Variant if S1-B7 fails:** drive stage A from P5 alone (a 0 Ω link selects PERMIT or P5). ILIM_HIZ then becomes the only
dynamic hardware gate. That is still a documented hard converter-off with EN_EXTILIM = 1, but the loop proof rests on one
pin plus the VINDPM soft layer, like the [LOOP] single-fault table. Or bridge D-BT-SQ.

### 10.3 Residual risks, ranked

1. **The VESC over-voltage cut-off limits regen on this rig, whatever the charger** (S0-R0/R3, mechanism UNCONFIRMED). If
   braking stops at 30-50 ms even with V-MOT held at 19 V, the regen hard requirement cannot be met by Path A or Path B
   without VESC changes.
2. **Warm response is unspecified** (S1-B4/B4r). Missing τ ≤ 4 ms is a cliff to 6-40 % capture.
3. **Inhibit latency is unspecified** (S1-B3). Missing it gives a bounded single pulse, not a loop.
4. **/CE-HIGH behaviour on the M8 node** (S1-B7; [DS] §7.3.6 p.33 "keeps BAT ~2.5 V" with no battery). Fallbacks are
   defined.
5. **FC→regen transition (~11 ms) vs the regen onset (~5 ms after command)** needs an operator ruling (§5.3 a/b/c).
6. **FC-charge capacity in cruise** is bounded by OC_FC, the governor and the H-20 P_MAX, not by the charger. The EMS charge
   window must use the §6.3 schedule.
7. **Datasheet self-contradictions:** STOP_WD_CHG R vs RW (S1-B5); WD reset of VREG; VAC_OVP POR text; R29 6.04 vs 6.20 k;
   TP numbering. All are handled by readback.
8. **ADC accuracy unspecified** (S1-B9). EMS regen accounting error is unquantified until measured.
9. **Blocking I2C (≤ 1.4 ms per slot)** and the off-board lead run (EMI on PERMIT/ILIM_REL, 100 kHz I2C).
10. **MCU WDT not implemented:** REQUIRED FUTURE WORK (§7.4). Without it, a hang leaves the switches frozen. H1/H2 still
    prevent the loop; overcharge rests on the charger CV and its watchdog.
11. **M8 drains the pack** by ~41 mAh/day, and it is a proposal awaiting operator approval.
12. **H2's BT_ACT trip depends on the INA253A1 zero offset** (TODO(verify)).

## 11. Corrections to the dossier and reviews found while designing

1. **AUTO_INDET_EN and EN_IINDPM are reset by WATCHDOG** ([DS] Table 7-27 p.73; Table 7-30 p.78). [DOS] §2.4/§3 said
   "REG_RST only". Confirms the regen-lens finding.
2. **REG09 STOP_WD_CHG** is "R-0h" in Fig 7-32 but RW in Table 7-20 (p.65). Writability is a bench gate.
3. **EN_EXTILIM never needs to be 0** with CHG_QUAL. All three reviews' EN_EXTILIM concern is designed out (§3.1).
4. **The regen→FC switch is not a plug-in** (§5.2). VINDPM is rewritten explicitly on every transition.
5. **VSYSMIN 3.5 V, not 5.0 V:** the M8 node sits at 5.7-6.9 V once IQ_BAT_ON 540 µA is counted.
6. **EN_AUTO_IBATDIS = 0** so the 30 mA BAT OVP discharge cannot pull the M8 node down ([DS] §7.3.6 p.33; Table 7-25).
7. **R29** is 6.04 k (Fig 4-6) vs 6.20 k (BOM p.23). [DOS] cited 6.04 k only.
8. **M8 is a proposal**, not an operator ruling (integration finding 6).
9. **FC charge current ≈ 1.6 A at standstill**, less in cruise; not "1.8-2.0 A" (regen and integration findings).

## 12. missing_primaries

- **BQ25798 dynamic data absent from SLUSDV2C:**
  - /CE and ILIM_HIZ entry/exit latency in buck mode;
  - VINDPM loop bandwidth out of saturation;
  - ADC accuracy;
  - watchdog accuracy at 0.5 s;
  - the REGN-on HIZ VBUS draw;
  - behaviour of the BAT pin with /CE HIGH and a 1 kΩ-fed "battery".

  Sources: TI E2E/app support, or bench gates S1-B1..B9.
- **i.MX RT1060 Reference Manual:** RTWDOG, WDOG1, EWM, SRC_SRSR, IOMUXC pad reset/keeper. NXP login-gated; only the WDT_T4
  source was used.
- **PJRC Teensy 4.1** reset pad state and boot-to-`setup()` time.
- **SN74LVC1G27 and SN74LVC1G32 datasheets** (1G08 and 1G00 were read this round; family limits assumed).
- **BSS138 / 2N7002 / CSD15380F3 datasheets** (Vgs(th) at 3.3 V drive).
- **Mouser/Farnell pricing and stock** for the non-TI passives and MOSFETs; TI store unit prices for the logic and
  comparator parts.
- **VESC Six EDU:** `l_max_vin`, OV fault behaviour in current control, fault-stop time, input capacitance (S0-R0/R1).
- **RT1987:** turn-off delay; whether UVLO recovery with EN high repeats tD_ON (makes M8 mandatory or optional); min/max of
  tON.
- **INA253A1 zero-current offset** (the PDF is in the repo, not re-read).
- **TDK C2012X5R1E106K / GRM21BZ71E106K DC-bias curves**; TL431 datasheet; EEE-FN1V471UP tolerance.
- **Mikroe Charger 25 Click (BQ25792):** not reachable; not evaluated.
