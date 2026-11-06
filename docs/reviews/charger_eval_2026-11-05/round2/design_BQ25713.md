# Path A design: TI BQ25713EVM-017 in place of the Ag105, always-powered charger (board rev 20260622)

Round 2, 2026-11-05. Scratch design; the repository was not modified. Companion block/wiring diagram:
`.../charger_eval/r2/design_BQ25713.svg`. Calculators: `.../charger_eval/r2/comp_calc.py` (comparator H1),
`.../charger_eval/r2/d713/ilim_calc.py` (ILIM ceilings, inrush, FC budget, thermal, CV error).

This document turns the round-2 dossier (`r2/dossier_BQ25713.md`) into a buildable design. It applies the operator
rulings of 2026-11-05 and the three adversarial verdicts on the dossier (loop, regen, integration lenses: all
"not refuted, major findings"). Where the dossier and a verdict disagree, the verdict's correction is applied here
and listed in section 0.3.

---

## 0. Verdict, rulings applied, sources

### 0.1 Verdict

**Path A with the BQ25713EVM-017 is FEASIBLE WITH CONDITIONS. It is not yet "fully feasible".** The loop-freedom and
runaway-freedom arguments are complete in hardware and do not depend on firmware, I2C, the charger's threshold register
or the MCU state (section 3.6). FC charging is proven from the datasheet. **Regen capture, a hard requirement, rests on
four bench gates that no primary document can close:**

| Gate | What it decides | Why no document closes it |
|---|---|---|
| **B3** VINDPM retention across Hi-Z exit | Whether the host-written 19.008 V threshold survives each burst | SLUSD83C §9.3.3.2 p.25 measures "VBUS at no load ... right before the converter is enabled" and does not say whether a Hi-Z exit re-runs it |
| **B4b** Hi-Z-exit warm response | Whether the charger reaches 63 % of its charge current before V-MOT reaches the VESC's ~21.35 V cut-off | No loop-bandwidth, Hi-Z-exit or VINDPM transient figure in SLUSD83C |
| **B2** Hi-Z entry latency | Bus-feed pulse bound when a burst ends abruptly (≤ 275 µs at 1.6 A) | Not specified in SLUSD83C |
| **M-R0 / M-R3** VESC cut-off | Whether braking continues when V-MOT is held at 19 V | A VESC behaviour, not a charger property (`r2/regen_dynamics.md` §7) |

If B3 or B4b fails, section 5.6 gives the two documented fallbacks (VESC `l_max_vin` raised to at most 23 V; a bounded
firmware pre-release on brake intent, which needs an operator ruling). If both fallbacks fail, Path A with this IC fails
regen and the next candidate in the matrix must be tried. **Commit to buying hardware only for the stage-1 bench
(two EVMs, the interlock parts); do not desolder the Ag105 until stage 1 passes (section 9).**

### 0.2 Operator rulings applied (2026-11-05)

1. Regen harvesting and FC charging are both hard requirements. The design is sized for both (ceilings, mode sequencer,
   time-multiplexed paths).
2. Path A is preferred and must be shown fully feasible: section 9 is the proof plan with numeric gates.
3. R3 is replaced by "no circular loop, no runaway". It is relaxed for this charger only because it has a hard
   converter-off pin (ILIM_HIZ < 0.4 V, SLUSD83C p.18, §9.3.3.4 p.25) driven by a fail-safe, Teensy-commanded,
   hardware-gated stage (section 3), plus an input-voltage threshold (VINDPM). The always-powered architecture (REGEN
   closed through Run) is used.
4. The PCB and pack survived the 2026-11-04 incident; stage-0 damage checks are treated as passed. A scope-armed first
   bring-up is kept (stages 3-4).
5. **The MCU hardware watchdog (RTWDOG + WDOG1) is REQUIRED FUTURE WORK before any unattended charger session**,
   specified in section 7.6.

### 0.3 Corrections to the dossier applied in this design (from the three verdicts)

| # | Dossier said | Design uses | Basis |
|---|---|---|---|
| C1 | Comparator "open-drain" outputs wired onto the Q_b gate beside pin 5 | Comparators drive only 74LVC1G gate inputs; one gate output (PERMIT) is the sole driver of the inhibit stage | TLV3012/TLV3012B are push-pull (TI SBOS300C p.1); a wire-OR with a GPIO lets one override the other |
| C2 | Q_a gate pulled up to the EVM 3V3 (LM3480 U2) | Q_a gate pulled up to the charger's own REGN (EVM TP21) | Loss of the EVM 3V3 would leave ILIM_HIZ at its divider (> 0.8 V) = enabled; [LOOP] §8 H3 requires a charger-rail bias |
| C3 | "PTM_PINSEL default is set by hardware" | PTM_PINSEL, EN_PTM and EN_EXTILIM are R/W register bits; they are written to safe values and read back at ≥ 6 Hz, mismatch = trip | SLUSD83C Table 9-7/9-8 p.40-41; §9.4.3 p.32 (PTM passes input to SYS) |
| C4 | R27 127 kΩ, "1.05-1.42 A" ceiling; FC divider optional | Mode-switched divider: REGEN-HIGH 154 kΩ (1.33-2.28 A), FC-LOW 154 kΩ ∥ 324 kΩ (0.30-1.13 A), switched by the FC_CHARGE net. Mandatory | Pin accuracy ±0.2 A (IDPM_REG_ACC_ILIM, SLUSD83C p.12) + VREGN 5.7-6.3 V (p.12) + 1 % resistors (EVM BOM); IIN_HOST resets to 3.25 A on adapter removal (§9.6.6.1 p.61) |
| C5 | IIN_HOST 0.7 A gives ~1.2 A charge | IIN_HOST is a maximum: typical regulation ~100 mA below; 0.7 A gives ~0.6 A in, ~1.0-1.1 A charge; a dynamic FC-window input governor is required | SLUSD83C §9.6.6.1 p.61, EC p.12 rows 0x1E00 / 0x0A00 |
| C6 | Single-fault "D-BT-EN shorted -> H2 withdraws permit" | Holds only above the 0.11-0.29 A BT_ACTIVE threshold; a firmware trip on I_BT above offset + 50 mA while BT_BUS is commanded LOW is added (F4) | Loop verdict F4 |
| C7 | (not in the dossier or [LOOP]) | **The H1 (V-MOT/VBUS) term is qualified by REGEN-net HIGH and FC_CHARGE-net LOW.** Without this, in an FC window with D-BT-EN shorted, any braking event raises H1 and grants the permit, closing loop L-F for the burst duration | New in this design, section 3.6 |
| C8 | B4b from a pre-charged VCHG | B4b/B7 start from VCHG decayed below VSYSMIN (6.144 V), the real post-cruise state behind D-BT-SQ | Integration verdict; SLUSD83C p.11, p.57, p.60 |
| C9 | No FC <-> regen transition sequencer | Sequencer triggered on brake intent (setpoint fall, 80-120 ms lead) | Regen verdict F5; [P37] §3.2 |
| C10 | "VINDPM 13.5 V doubles as an FC-sag guard" | It is a bus-collapse guard (VCHG-IN is the regulated 16 V VBUS) | Integration verdict |
| C11 | LM3480 rating unknown | Closed: 30 V operating, 35 V abs max | TI SNVS011H §6.1/§6.3 (fetched, `datasheets/lm3480.pdf`) |
| C12 | LVC logic thresholds unknown | Closed: VIH 2.0 V, VIL 0.8 V at VCC 3.0-3.6 V; Ioff ±10 µA partial power-down | TI SCES217A (SN74LVC1G08) Recommended Operating Conditions and EC; same family SCES487I/SCES488E/SCES219W/SCES214A fetched this round |

### 0.4 Sources (tags used below)

| Tag | Document |
|---|---|
| [DS] | TI SLUSD83C, BQ25713/BQ25713B datasheet, rev. May 2023 ("p.N" = PDF page) |
| [UG] | TI SLUUBT8B, BQ2571x EVM user guide: Table 1 I/O, Table 2 jumpers, Table 4 BOM pp.10-12, Fig. 11 schematic p.17 |
| [TLV] | TI SBOS300C, TLV3011/3012/301xB (Apr 2023): §6.9 B-version EC (Vos ±9 mV over temp, VHYS 2-8 mV), p.1 push-pull, §9.4.4-9.4.5 fail-safe inputs / POR |
| [LVC] | TI SCES217A SN74LVC1G08; SCES487I 1G11; SCES488E 1G27; SCES219W 1G32; SCES214A 1G04 (fetched 2026-11-05) |
| [RT] | Richtek RT1987 DS-00: tD_ON 8 ms, VEN_R 1.4 V max, VEN_F 0.6 V min (EC p.7), §17.3 soft-start, §17.6 ideal diode |
| [TPS] | TI SLVSFP3C TPS61288: VOVP 18.3/19/19.5 V (p.6) |
| [LM] | TI SNVS011H LM3480 |
| [LOOP] | `r2/loop_analysis.md` |
| [REGEN] | `r2/regen_dynamics.md` |
| [DOS] | `r2/dossier_BQ25713.md` and its three verdicts (loop / regen / integration) |
| [SPEC] | `docs/reviews/charger_eval_2026-11-05/spec.md` (pad table §1, hot-plug §6, mechanical §7) |
| [P37] | `docs/fw37_planning_2026-11-04.md` |
| [FW] | `teensy_controller/teensy_controller.ino` fw v37 rev 2 |

---

## 1. Wiring: Ag105 pads to the EVM

### 1.1 Architecture

- **Ag105 desoldered.** The CHG footprint (22 holes, 2 rows 25.00 mm apart, 2.54 mm pitch, [SPEC] §7) receives an
  **interlock carrier**: a ≤ 32 × 35 mm perfboard/PCB on 0.1" header pins with ≥ 2.54 mm standoff (clears D-BT-SQ,
  C-D11, C-D12 under the footprint, [SPEC] §7). It carries the comparators, the gate network and the harness terminals.
  The 11 floating holes (VSEL, CSEL, NC1-3, MPPTSEL, LDIS, VLOAD±) are mechanical anchors only.
- **The EVM is mounted off-board** on a plate (SLUUBT8B gives no dimensions, so it cannot fit the footprint; [DOS] §2.10).
  The EVM's ILIM inhibit transistors (Q_a, Q_b) and the ceiling switch (Q_c) are fitted **on the EVM**, at TP22, so the
  inhibit node never travels on a harness.
- One harness runs carrier -> EVM: the power pairs, I2C, CHRG_OK, PERMIT, FCC-ceiling, and the REGN return.

### 1.2 Pad -> EVM connector table

| Ag105 pad (pin) | Board net [SPEC] §1 | EVM terminal | Wire | Length | Notes |
|---|---|---|---|---|---|
| VIN+ (10) | VCHG-IN (D-BC-FC / D-BC-RG outputs; C-D8, C-D10; R1-CHG/R2-CHG to pin 38) | **J1-VIN** | 20 AWG, twisted with the return | ≤ 150 mm | Input ≤ 2.28 A worst case (regen pin ceiling, §3.5); 20 AWG ≈ 33 mΩ/m. **No capacitor added** (inrush, §8.1) |
| VIN- (4) | GND | **J1-GND** | 20 AWG, twisted with VIN+ | ≤ 150 mm | Input return. Same node as battery return (EVM net-tie NT1, [UG] Fig. 11) |
| VBAT+ (18, 19) | VCHG (D-BT-SQ VIN, C-D11) | **J5-BAT** | 18 AWG, twisted with the return, both pads joined on the carrier | ≤ 150 mm | ≤ 2.5 A; 18 AWG ≈ 21 mΩ/m -> 6.3 mΩ round trip, 16 mV at 2.5 A (counted in §8.5) |
| VBAT- (14, 15) | GND | **J5-GND** | 18 AWG | ≤ 150 mm | Battery return. **Nothing in series** (R-GND requirement, [LOOP] C2) |
| SDA (8) | Teensy 18, RSDA 10 kΩ to Teensy 3V3 | **J3-SDA** | 26-28 AWG, twisted with J3-GND | ≤ 200 mm | EVM pull-ups R32/R35 **removed**; board RSDA/RSCL are the only pull-ups |
| SCL (7) | Teensy 19, RSCL 10 kΩ | **J3-SCL** | twisted with GND | ≤ 200 mm | I2C at 400 kHz max ([DS] p.19 FS(CL)); use 400 kHz, fall back to 100 kHz if the harness rings |
| - | GND (signal) | **J3-GND** | 26 AWG, in the I2C pair | | Signal reference; joins pad 14 on the carrier |
| STAT (3) | CHRG-STAT -> Teensy 6 (IN, no pull) | **J2-CHRG_OK** | 26 AWG | ≤ 200 mm | Open drain, R33 10 kΩ to EVM 3V3 (0-3.3 V). Pin 6 renamed `CHRG_OK` (CSV first). Unpowered charger = LOW |
| MPPTD (11) | Teensy 5 (OUT) | **carrier only** (P5 input of gate G6, 47 kΩ pull-down on the carrier) | - | - | **Not wired to the EVM.** Pin 5 renamed `CHG_ARM` (HIGH = armed; same polarity as `MPPT_DISABLE` HIGH = release, CSV first) |
| THERM (13) | J-NTC pin 1 | not connected | - | - | The BQ25713 has no TS pin ([DS] pin table p.6-8). Optional: J-NTC -> spare analog pin 16 (A2) with 10 kΩ pull-up to 3V3, firmware temperature qualify (0-45 °C), CSV first. Recorded as residual risk R9 |
| (carrier) | - | **EVM TP22 (ILIM_HIZ)** | - | - | Not a harness wire: the inhibit stage sits on the EVM (§3.4) |
| (carrier) PERMIT | gate G6 output | EVM Q_b gate (via 1 kΩ, 100 kΩ to EVM GND) | 26 AWG, twisted with GND | ≤ 200 mm | Logic-level; loss of this wire = Q_b off = Hi-Z (fail-safe) |
| (carrier) FCC | FC_CHARGE_EN net (pin 31, J1.45/46) | EVM Q_c gate via 1 kΩ (net already has the RT1987 10 kΩ pull-down) | 26 AWG | ≤ 200 mm | Selects the FC-LOW ceiling (§3.5). Loss of wire = REGEN-HIGH ceiling, but the FC window's own permit term also needs FCC on the carrier, so the charger is gated off |

### 1.3 Carrier connections not on the footprint (bodge wires)

All taken at the Teensy breakout receptacles J1/J2 [SPEC] §1 unless noted; every new Teensy pin is entered in
`Scale_Car_Teensy_IO__IO.csv` **before** firmware uses it.

| Signal | Source | Carrier use |
|---|---|---|
| 3V3 | J1.29/30 (Teensy 3V3) | U1, U2, gates, 100 nF each |
| GND | J1.01/02 and pad 4/14 | common |
| VBUS | D-MT-EN VIN / C-D2 node ([LOOP] §9) | H1 divider RB1/RB2 (Kelvin wire, 28 AWG, no current) |
| V-MOT | D-MT-EN VOUT / CAL+ | H1 divider RA1/RA2 (Kelvin wire). **Not** the existing RGN-V divider: it is the TL431 REF node ([LOOP] §9) |
| REGEN_EN net (pin 30) | J1.43/44 | gates G3 (R term) and G1 (NOR) |
| FC_CHARGE_EN net (pin 31) | J1.45/46 | G2 (F term), G4 (inverter), EVM Q_c |
| BT_BUS_EN net (pin 28) | J1 position TODO(verify: SCH) | G1 |
| BT_CURRENT net (pin 41, INA253 SNS-BT out) | J2 position TODO(verify: SCH) | U2 IN+ (10 pA bias, no load on the ADC net) |
| P5 (pin 5, MPPTD pad 11) | footprint | G6 |
| H1 readback -> **pin 33** (J2.47/48) | U1 OUT via 1 kΩ | F1 monitor |
| PERMIT readback -> **pin 34** (J2.45/46) | G6 OUT via 1 kΩ | F1 monitor |
| BT_ACTIVE readback -> **pin 17** | U2 OUT via 1 kΩ | F4 monitor |
| (reserved) pin 20 | - | WDOG1_B output if a hardware watchdog line is wanted later (§7.6). **Never pin 19 (SCL)** |

### 1.4 Local capacitance and mounting

- VCHG-IN: board C-D8 + C-D10 (2 × 10 µF) + EVM residue 31.5 µF after depopulation (§2) = 51.5 µF nominal. Nothing added.
- VCHG: C-D11 10 µF (board) + EVM C26 10 µF and the EVM BAT-side parts. Nothing added.
- The EVM J1 RC snubber (R3 ∥ R4 3.9 Ω, C18 1 µF, [UG] BOM) stays: it damps lead inductance against the ceramic input.
  The RT1987 slew is 12.0 V/ms ([SPEC] §6), so the hot-plug edge is slow and ringing is expected to be small: scoped
  in stage 3.
- Mounting: EVM on four M3 standoffs on an insulating plate fixed to the chassis beside the board, terminal blocks J1/J5/J6
  (5.08 mm, [UG] BOM) facing the board; strain relief on both pairs. Free air; EVM loss ≤ 2 W (§8.4).

---

## 2. EVM and motherboard modifications (by designator)

### 2.1 EVM (BQ25713EVM-017, [UG] Table 2, Table 4, Fig. 11)

| # | Designator | Change | Why |
|---|---|---|---|
| E1 | JP2 / JP3 / JP4 | **JP2 on, JP3 off, JP4 off** (CELL ≈ 2.7 V = 2S) | 2S strap -> MaxChargeVoltage default 8.400 V, VSYSMIN 6.144 V, SYSOVP 12 V ([DS] Table 9-1 p.25, p.58, p.60). JP4 forces battery removal: never fit |
| E2 | JP1, JP7 | Factory: JP1 on, JP7 top | Bypasses the EVM input selector; the board RT1987s do all switching |
| E3 | JP5 / JP6 / R26 | **JP5 on, JP6 off, remove R26 (383 kΩ)**; leave J2-ILIM_control open | ILIM pre-bias from VDDA through R19; the ILIM_control / D5 path is not used ([DOS] §7: schematic polarity LOW = Hi-Z contradicts UG Table 1) |
| E4 | R27 | **220 kΩ -> 154 kΩ** (0.1 % preferred, 1 % acceptable) | REGEN-HIGH ceiling 1.80 A nominal (§3.5) |
| E5 | new Rp + Q_c | **324 kΩ from TP22 to Q_c drain; Q_c (2N7002-class) source GND; gate = FCC wire via 1 kΩ** | FC-LOW ceiling 0.71 A nominal when FC_CHARGE is HIGH (§3.5) |
| E6 | new Q_a, Q_b | **Q_a: drain TP22, source GND, gate 100 kΩ to TP21 (REGN). Q_b: drain Q_a gate, source GND, gate = PERMIT via 1 kΩ, 100 kΩ gate-to-GND** | Fail-safe hard inhibit (§3.4) |
| E7 | C53 | **Remove** (33 µF / 35 V tantalum) | Inrush (§8.1) |
| E8 | C23, C24, C44 (three of C23/C24/C44/C45) | **Remove**; keep C3, C4, C45 (nearest Q1) and C18 | Inrush; TI minimum 4 µF effective ([DS] Table 10-1 p.75) |
| E9 | C25 | **0.47 µF 16 V -> 0.47 µF ≥ 50 V X7R 0805** | VBUS-pin filter sees V-MOT up to 21.4 V ([UG] BOM p.10) |
| E10 | R32, R35 | **Remove** (10 kΩ I2C pull-ups to EVM 3V3) | Would back-feed the dead EVM 3V3 from the Teensy pull-ups |
| E11 | J3-3V3 | Leave unconnected; keep **JP8 fitted** | EVM 3V3 (LM3480, fed through D3 VBUS / D2 BAT) still powers R33 (CHRG_OK pull-up) |
| E12 | J6 SYS | Unloaded; **do not depopulate SYS capacitors** | TI requires ≥ 50 µF effective on VSYS ([DS] Table 10-2 p.76) |
| E13 | J2-ENZ_OTG, J2-CELL_control, J4 | Leave open | OTG needs EN_OTG pin + REG0x35[4] + REG0x34[5] + VBUS < CONVENZ ([DS] §9.3.4 p.25); EN_OTG register stays 0 |
| E14 | RAC R2 / RSR R8 | **Keep** 10 mΩ, 1 W (WSLP1206) | High-side input and charge sense; matches register RSNS bits = 0 ([DS] 0x31[3:2]) |

### 2.2 Motherboard

| # | Item | Change | Why |
|---|---|---|---|
| B1 | CHG (Ag105) | **Desolder**; clean pads; fit the interlock carrier | - |
| B2 | C-D8, C-D10 (10 µF / 25 V on VCHG-IN) | **Replace with 10 µF ≥ 35 V (50 V preferred) X7R**, same footprint (size TODO(verify: BRD)); recount the inrush with the new part's DC-bias curve | V-MOT up to 21.4 V true (design clamp 22.13 V); 25 V is under-rated with a raised VESC cut-off (§5.6) |
| B3 | D-BT-SQ | **Keep. Do not bridge** | Blocks pack -> charger back-feed, OTG/VAP and the EVM LDO drain ([DOS] §2.7) |
| B4 | H1 / H2 dividers | New 0.1 % dividers on the carrier, Kelvin-wired to VBUS and V-MOT | The RGN-V divider is the TL431 REF node ([LOOP] §9) |
| B5 | Pin 5 | Carrier 47 kΩ pull-down on the P5 input (pin 5 has no external pull today, [SPEC] §1) | Reset/high-Z Teensy = P5 LOW |
| B6 | IO CSV | Rows: pin 5 `CHG_ARM` (OUT, HIGH = armed), pin 6 `CHRG_OK` (IN), pin 33 `CHG_H1_RB` (IN), pin 34 `CHG_PERMIT_RB` (IN), pin 17 `BT_ACTIVE_RB` (IN), optional pin 16 `BATT_NTC` (AIN) | CSV is authoritative (CLAUDE.md priority 1) |
| B7 | CLAUDE.md | A never-rotated hardware bodge record (charger swap, carrier, EVM mods, B2) | Same class as the 2026-07-10 / 2026-08-16 records |

---

## 3. Backstop hardware (the interlock carrier and the EVM inhibit stage)

### 3.1 Signals and the permit equation

```
H1   = V-MOT > 1.067 x VBUS (+0.30 V hysteresis)            comparator U1 (TLV3012B)
BTA  = I_BT > ~0.2 A  (INA253 SNS-BT output > 19.8 mV)       comparator U2 (TLV3012B)
RGN, FCC, BTB = REGEN_EN (30), FC_CHARGE_EN (31), BT_BUS_EN (28) nets, read at the Teensy breakout

R    = H1 AND RGN AND NOT FCC                    regen term  (charger fed from V-MOT, bus cannot feed V-MOT)
F    = FCC AND NOT (RGN OR BTB OR BTA)           FC term     (charger fed from an FC-only bus)
PERMIT = P5 AND (R OR F)                         -> EVM inhibit stage; LOW = ILIM_HIZ < 0.4 V = Hi-Z
```

Change versus [LOOP] §8 (`PERMIT = P5 ∧ (H1 ∨ H2)`): the H1 term is qualified by RGN ∧ ¬FCC (correction C7). H1 proves
only that D-MT-EN is reverse-biased; it says nothing about **where the charger input comes from**. With FC_CHARGE HIGH the
input is VBUS, so a braking-raised H1 must not permit.

### 3.2 Comparator U1 (H1), values from `comp_calc.py`

| Part | Value | Notes |
|---|---|---|
| U1 | TLV3012B (SC70-6 `TLV3012BIDCKR`) | Push-pull; Vos ±9 mV over temp, internal hysteresis 2-8 mV ([TLV] §6.9); supply 1.65-5.5 V; POR holds OUT LOW up to 1.9 ms; inputs fail-safe to 5.5 V with V+ = 0 ([TLV] §9.4.4-9.4.5 via [LOOP] §8) |
| RA1 / RA2 (V-MOT leg -> IN+) | 499 kΩ / 56.2 kΩ, 0.1 % | ratio 1/9.879 |
| RB1 / RB2 (VBUS leg -> IN-) | 464 kΩ / 56.2 kΩ, 0.1 % | ratio 0.10804 |
| RH (OUT -> IN+) | 6.49 MΩ, 1 % | 0.30 V of designed hysteresis at V-MOT |
| CA / CB | 470 pF each | matched τ ≈ 24 µs (common-mode steps do not trip) |
| Supply | Teensy 3V3, 100 nF | The 3V3 rail is pack-derived (VBT -> LM1084 -> 5 V -> Teensy) |

Trip points (worst case: 0.1 % resistors, Vos ±9 mV, VHYS 2-8 mV, VOH 3.1-3.3 V):

| VBUS | Permit rise (nom / worst max) | Inhibit fall (nom / worst min) | Guard (fall min − VBUS) |
|---|---|---|---|
| 15.59 V | 16.79 / 16.96 V | 16.49 / 16.33 V | 0.735 V |
| 15.90 V (nominal) | 17.13 / 17.29 V | 16.82 / 16.66 V | 0.757 V |
| 16.40 V (steady max, 1 % RD1) | 17.67 / 17.83 V | 17.36 / 17.19 V | 0.793 V |
| 17.20 V (transient park) | 18.53 / 18.70 V | 18.22 / 18.05 V | 0.850 V |
| 18.30 V (TPS OVP min) | 19.71 / 19.89 V | 19.41 / 19.23 V | 0.929 V |
| 19.50 V (TPS OVP max) | 21.00 / 21.18 V | 20.70 / 20.52 V | 1.016 V |

With 1 % resistors the worst fall at 15.9 V is 16.14 V (guard 0.24 V): 0.1 % parts are mandatory. IN+ is 3.04 V at
V-MOT 30 V (inside the fail-safe range). Propagation ≤ 4 µs ([LOOP] §4.3 citing [TLV] p.10) plus the 24 µs filter.

### 3.3 Comparator U2 (BT_ACTIVE) and the gate network

- **U2** TLV3012B: IN+ = BT_CURRENT net (Teensy pin 41 node); IN- = U2's own 1.242 V reference (1.208-1.276 V, [TLV] EC)
  divided 61.9 kΩ / 1.00 kΩ = 19.75 mV, 100 nF on the tap. At 0.1 V/A (INA253A1, CLAUDE.md §5) that is 0.198 A nominal,
  0.11-0.29 A over Vos ±9 mV. The INA253 zero offset is TODO(verify: `references/Datasheets/INA253A1IPWR.pdf`).
  BTA is a fast, MCU-independent backstop; the calibrated firmware trip F4 (50 mA above offset) is the fine one.
- **Gate network** (all 3V3, SOT-23-5 DBV, 100 nF each, stock on the TI store 2026-11-05 in section 10):

| Gate | Part | Inputs | Output |
|---|---|---|---|
| G1 | SN74LVC1G27 NOR3 | RGN, BTB, BTA | N1 = NOT(RGN OR BTB OR BTA) |
| G2 | SN74LVC1G08 AND2 | FCC, N1 | F |
| G4 | SN74LVC1G04 INV | FCC | FCCn |
| G3 | SN74LVC1G11 AND3 | H1, RGN, FCCn | R |
| G5 | SN74LVC1G32 OR2 | R, F | GATE |
| G6 | SN74LVC1G08 AND2 | GATE, P5 (47 kΩ pull-down) | **PERMIT** |

Logic levels: VIH 2.0 V / VIL 0.8 V at VCC 3.0-3.6 V; Ioff ±10 µA, so inputs tolerate a powered input with the gate
unpowered ([LVC] SCES217A). A TLV3012B output at VOH (≥ VCC − 0.2 V at 5 mA, [TLV]) drives them directly.

Residual: an EN net held between RT1987 VEN_F 0.6 V min and LVC VIL 0.8 V could read LOW while the switch conducts
([RT] p.7, [LVC]). For RGN and FCC that misreading removes the term that uses it: safe direction. For BTB, BTA covers it.

### 3.4 EVM inhibit stage (fitted at TP22)

```
 EVM VDDA --R19 383k--+--------------------------- TP22 = ILIM_HIZ (C35 100 pF, factory)
                      |            |          |
                    R27 154k     Q_a D      324k (Rp)
                      |            |          |
                     GND        Q_a S=GND   Q_c D, Q_c S = GND, Q_c G <- FCC wire via 1k
                                   |
              TP21 REGN --100k---- Q_a G ---- Q_b D,  Q_b S = GND
                                              Q_b G <- PERMIT via 1k, 100k to GND
```

| Condition | Q_b | Q_a | ILIM_HIZ | Charger |
|---|---|---|---|---|
| PERMIT HIGH | on | off (gate pulled to GND) | divider value 1.20-1.83 V (> 0.8 V exit) | converter allowed |
| PERMIT LOW, wire open, carrier 3V3 dead, Teensy reset/unpowered | off | **on, biased from REGN** | ≈ 0 V (R19 current ≤ 16.5 µA) | **Hi-Z** (< 0.4 V, [DS] p.18) |
| Charger unpowered | - | - | 0 V | unpowered |
| First 50 ms after VCHG-IN rises | - | REGN and VDDA both absent | ≈ 0 V via R27 | converter cannot start before 150 ms ([DS] §9.3.3 step 5 p.24); REGN/VDDA rise together at 50 ms, Q_a turns on with REGN |

- Q_a/Q_b/Q_c: 2N7002-class (the EVM already uses 2N7002ET1G, [UG] BOM; its datasheet is a missing primary). Q_a sees
  VGS ≈ 6 V from REGN (5.7-6.3 V, [DS] p.12), so a VGS(th) up to 2.5 V has ample margin; the hold-down must keep TP22
  < 0.3 V (bench B1).
- **Firmware rule (integration verdict):** P5 is forced LOW whenever pin 6 `CHRG_OK` is LOW, and P5 rises only after a
  verified configuration in the current charger power cycle (§6). This removes the case "P5 HIGH, permits released at
  POR, converter starts at 150 ms on POR defaults" ([DS] p.24-25, p.41).

### 3.5 Mode-switched ILIM ceiling (`ilim_calc.py`)

V(ILIM_HIZ) = 1 V + 40 × IDPM × RAC ([DS] eq. 2 p.61), RAC = 10 mΩ, so I = (V − 1)/0.4. Divider fed from VDDA
5.7-6.3 V ([DS] p.12 VREGN_REG), R19 383 kΩ 1 %; pin accuracy ±0.2 A ([DS] p.12 IDPM_REG_ACC_ILIM: 1300/1500/1700 mA at
1.6 V, 300/500/700 mA at 1.2 V); regulation range 1.15-4 V ([DS] p.12 VIREG_DPM_RNG_ILIM).

| Ceiling | Bottom leg | V nominal | I nominal | Worst span (VDDA, 1 % R, ±0.2 A pin) | Selected when |
|---|---|---|---|---|---|
| Stock | R27 220 kΩ | 2.19 V | 2.97 A | 2.43-3.52 A | (removed) |
| **REGEN-HIGH** | R27 154 kΩ | 1.72 V | **1.80 A** | **1.33-2.28 A** | FCC net LOW |
| **FC-LOW** | 154 kΩ ∥ 324 kΩ = 104.4 kΩ | 1.29 V | **0.71 A** | **0.30-1.13 A** | FCC net HIGH (Q_c on) |

- The effective input limit is the lower of the pin and IIN_HOST ([DS] §9.3.3.2 p.25). IIN_HOST is the operating value;
  the pin is the I2C-independent ceiling, needed because IIN_HOST resets to 3.25 A on adapter removal ([DS] p.61).
- In regen mode the source is V-MOT and the permit proves D-MT-EN is not conducting, so a high ceiling costs nothing
  against OC_FC. Regen minimum 1.33 A × 18.44 V (VINDPM min) = 24.5 W ≥ the [REGEN] §5 requirement of 23 W at Vth.
- In the FC window, 1.13 A + 0.15 A aux = 1.28 A leaves 0.12 A of motor current under the 1.4 A OC_FC latch **even with
  IIN_HOST lost**. In normal operation the dynamic governor (§6.4) keeps the charger input far below this.
- FC-LOW min 1.20 V stays above the 1.15 V regulation floor. 0.1 % resistors tighten both spans by ~±0.03 A only;
  the ±0.2 A pin accuracy dominates.
- Firmware must never write EN_EXTILIM = 0 (0x32[7]): that alone removes the pin ceiling ([DS] p.42-43, p.61).

### 3.6 Loop impossibility and runaway bounds (what each element proves)

| Hazard | Necessary conditions ([LOOP] §3) | Broken by (hardware, MCU-independent) | Soft layers |
|---|---|---|---|
| L-R: pack -> BT boost -> VBUS -> D-MT-EN -> V-MOT -> D-BC-RG -> charger -> D-BT-SQ -> pack | D-MT-EN conducting (V-MOT < VBUS) **and** charger converting | **R term**: converting needs H1, i.e. V-MOT ≥ VBUS + 0.73 V worst case, so D-MT-EN is reverse-biased ([RT] §17.6) | VINDPM 19.008 V above the bus; F1 cross-check; G2 |
| L-F: pack -> BT boost -> VBUS -> D-BC-FC -> charger -> pack | FC_CHARGE on, pack current into the bus, charger converting | **F term**: needs BTB LOW and BTA LOW; **R term disabled while FCC HIGH (C7)** | `assertFcChargeEnable()`; F4 (I_BT > offset + 50 mA, 20 ms); FAULT_SWITCH_CONFLICT in all builds |
| Runaway (current above ceiling) | sense bypass, no hardware ceiling, IC fault | High-side RAC/RSR, common return (net-tie NT1, [UG] Fig. 11); ILIM pin ceiling (§3.5); CV 8.400 V ±0.6 %, BATOVP 102.5-105 % ([DS] p.11, p.15) | IIN_HOST, ChargeCurrent, readback set, OV_BATT 8.5 V all builds |
| PTM pass-through (input straight to SYS) | EN_PTM = 1, PTM_PINSEL = 1, EN_EXTILIM = 0, ILIM_HIZ grounded ([DS] §9.4.3 p.32, p.40-41) | none in hardware (register state) | Never write those bits; readback at ≥ 6 Hz; mismatch -> trip (opens REGEN and FC_CHARGE, which removes input power) |

**Single faults** (one fault, everything else healthy). The [LOOP] §8 table holds with these changes:

| Fault | Effect with this design | Loop? |
|---|---|---|
| D-BT-EN shorted, FC window, braking | H1 = 1 but R is disabled (FCC HIGH); F needs BTA LOW: permit withdrawn above ~0.2 A; below it F4 trips in 20 ms | No sustained loop (≤ 20 ms below 0.29 A) |
| D-BC-FC shorted, regen mode | V-MOT tied to VBUS via D-BC-RG + short, H1 never true | No |
| D-BC-FC shorted, REGEN LOW, braking | R needs RGN: off. F needs FCC: off | No |
| PERMIT wire open / carrier 3V3 lost | Q_b off, Q_a on from REGN: Hi-Z | No |
| EVM 3V3 (LM3480) lost | Inhibit stage does not use it; CHRG_OK reads LOW -> firmware P5 LOW | No |
| REGN lost | Converter cannot run without REGN | No |
| Charger register corruption (VINDPM below bus, PTM bits) | R/F gating unaffected for loops; PTM is a runaway path -> readback trip | No loop; PTM bounded by trip latency (≤ 170 ms) |
| Q_a open or shorted | Open: Hi-Z cannot be forced, gating lost -> detected by F1 (PERMIT LOW but IIN ADC > 0 in cruise) -> REGEN/FCC opened. Shorted: no charging (safe) | Needs a second fault |
| Teensy hang | Hardware gating holds; charger watchdog zeroes ChargeCurrent in 4-7 s ([DS] p.19, p.30); **RTWDOG (future work) resets in 100 ms** | No |

---

## 4. Operating modes

Switch vector: FC_REG, BT_REG, FC_BUS, BT_BUS, MOT_PWR, REGEN, FC_CHARGE, BT_SEQ. Register names per §6. "Hi-Z" =
ILIM_HIZ held < 0.4 V by the inhibit stage.

| Mode | Switches | Charger power / state | Registers (verified) | PERMIT | What prevents a loop | What prevents runaway |
|---|---|---|---|---|---|---|
| Teensy reset / boot | 0 0 0 0 0 0 0 0 (10 kΩ pull-downs) | unpowered | - | 0 (P5 pull-down) | No input power | - |
| Init (State 0), Idle (State 1) | per existing staged bring-up; **REGEN 0, FC_CHARGE 0** | unpowered | - | 0 | No input power | - |
| Run entry, arming (≤ 200 ms) | 1 1 1 1 1 **1** 0 1 | powered from V-MOT ≈ VBUS; POR then Hi-Z | being written, P5 LOW | 0 | R needs P5 and H1 | POR ChargeCurrent 0 ([DS] p.56); auto-wakeup 128 mA bounded and disabled in Hi-Z before release |
| Run cruise, regen armed | 1 1 1 1 1 1 0 1 (or the selector's single-source vectors) | powered, Hi-Z | VINDPM 19.008 V, IIN_HOST 1.60 A, ChargeCurrent 2.496 A, VREG 8.400 V, WDT 5 s, CHRG_INHIBIT 0, AUTO_WAKEUP 0, PTM bits 0, EN_EXTILIM 1 | 0 (H1 = 0) | **R term (H1)**; VINDPM above bus as soft layer | Hi-Z; ceilings REGEN-HIGH 1.33-2.28 A |
| Run regen burst | as cruise; V-MOT > 1.067 VBUS + 0.30 V | converting from V-MOT, VINDPM holds V-MOT ≈ 19.0 V (+0.12 V path drop) | as cruise | 1 | D-MT-EN reverse-biased whenever PERMIT is 1 | Source-limited: drawing more than regen supplies pulls V-MOT to VINDPM, then to the H1 fall (≥ 16.66 V) -> Hi-Z. IIN ≤ min(1.6 A reg, pin); ICHG ≤ 2.496 A |
| Burst end / VESC abrupt stop | as cruise | converting -> Hi-Z | as cruise | 1 -> 0 | H1 fall ≥ 0.73 V above VBUS | One bounded pulse if Hi-Z entry exceeds 275 µs at 1.6 A (B2) |
| FC-charge window | 1 1 1 **0** 1 **0** **1** 1 | powered from VBUS (FC-only) via D-BC-FC | VINDPM 13.504 V, IIN_HOST governed 0.30-0.70 A, ChargeCurrent from `charge_goal` ≤ 1.216 A, rest as above | P5 ∧ F | **F term**: BTB LOW and BTA LOW; R disabled | FC-LOW ceiling 0.30-1.13 A; governor; firmware pre-empt at I_fc 1.25 A; OC_FC 1.4 A; VINDPM 13.5 V bus-collapse guard |
| FC window + braking | as FC window | REGEN 0, so regen goes to CAL/chopper/VESC cut-off | - | F unchanged | R disabled | - ; the sequencer leaves the window on brake intent (§5) |
| Finish (State 3) | -> Idle vector | Hi-Z -> unpowered | - | 0 | P5 LOW first, then REGEN LOW | - |
| State 98 tests | operator keys | any | `'4'`/`'5'` keys move switches; **pin 5 only through the verified-config gate**; `J` redefined as an FC-path session (BT_BUS 0) | gated | R/F independent of keys | ceilings; readback set; J guards |
| State 99 | phased teardown, **P5 LOW added as step 0**, then FC_CHARGE LOW, REGEN LOW, then existing phases | Hi-Z -> unpowered | - | 0 | - | the "drain into Ag105" phases now drain nothing: keep as harmless or remove |
| Teensy hang | frozen | frozen | frozen | frozen but hardware-evaluated | R/F terms are MCU-independent | Charger WDT 4-7 s -> ChargeCurrent 0; **RTWDOG 100 ms (future work) -> reset -> all pull-downs** |
| I2C dead | any | Hi-Z (firmware cannot verify -> P5 LOW) | unverifiable | 0 | - | - |
| Charger POR during Run (VCHG-IN glitch) | any | re-boots on POR defaults | **invalid** until rewritten | P5 forced LOW on CHRG_OK fall (1 kHz poll) | R/F still gate | POR ChargeCurrent 0; VINDPM POR = VBUS − 1.28 V (harmless under Hi-Z) |
| 3V3 brown-out | EN nets fall with 3V3 | unpowered / Hi-Z | - | 0 | inhibit stage self-biased from REGN | - |

**Why REGEN stays open in Idle.** [LOOP] §11 recommends it: it removes exposure while the motor is held at 0. Arming takes
~170-200 ms at Run entry (RT1987 tD_ON 8 ms + 1.3 ms ramp + 50 ms CHRG_OK + configuration, [RT] p.7, [DS] p.24), so a
brake in the first 200 ms of Run goes to the chopper. If the operator wants regen from the first tick, REGEN can be closed
in Idle under the same gating with no change to the proofs.

---

## 5. Mode transitions

Invariants ([LOOP] §6, extended): (I-1) P5 LOW across every switch change; (I-2) a sub-bus VINDPM is written only while
REGEN = 0, BT_BUS = 0, FC_CHARGE = 1; the regen VINDPM is written while still FC-powered; (I-3) P5 rises only after a full
readback in the charger's current power cycle; (I-4) no transition while a burst is in progress (H1 readback 1 or
V_rgn > V_bus + 0.3 V, calibrated); (I-5, new) **never** write EN_PTM, PTM_PINSEL, EN_EXTILIM = 0, RESET_REG, RESET_VINDPM,
EN_OTG, WDTMR = 00.

### 5.1 T1: Idle -> Run, regen arm

| # | Action | Rationale |
|---|---|---|
| 1 | P5 LOW; confirm PERMIT readback (pin 34) = 0 | (I-1) |
| 2 | `assertRegenEnable()`: require FC_CHARGE LOW, MOT_PWR HIGH and V-MOT charged (Death-5 guards), then REGEN HIGH | CSV row 31; REGEN close hot-plugs VCHG-IN from V-MOT at 12 V/ms: 51.5 µF × 12 mA/µF = 0.62 A from CAL, replenished by the bus (§8.1) |
| 3 | Wait for pin 6 CHRG_OK HIGH (expect 50 ms after CONVEN + tD_ON 8 ms, [DS] p.24); timeout 250 ms -> stay unarmed, flag `CHG_NO_ACK` (no fault: the arm is optional to motion) | Charger boots in Hi-Z (Q_a on) |
| 4 | Identity (0x2E = 0x40, 0x2F = 0x88) then the §6.1 sequence in the regen profile, then full readback | (I-3) |
| 5 | P5 HIGH -> state REGEN_ARMED. PERMIT stays 0 until H1 | H1 gates every burst |
| 6 | On the first PERMIT episode: re-read VINDPM within 20 ms after it ends (B3 monitor) | Detects the per-exit re-measure |

### 5.2 T2: regen-armed -> FC window (entry conditions: cruise, `charge_goal` > 0, no burst, FC headroom ≥ 0.4 A, SoC below target)

| # | Action | Rationale |
|---|---|---|
| 1 | P5 LOW; wait 1 ms (≥ B2 latency); PERMIT readback 0; charger IIN ADC = 0 at next sample | Charger hard-off before any path change |
| 2 | Share loop to FC-only (fw v28 selector / S2 order: FC must be on the bus and delivering first) | The bus must not lose its only source (campaign-H UV_BUS class) |
| 3 | `assertFcChargeEnable()`: REGEN LOW, BT_BUS LOW, wait ≥ RT1987 turn-off (M3; 1 ms until measured, firmware uses 100 µs today [FW] ~12772) | CSV row 31 |
| 4 | Verify I_BT (pin 41) < offset + 50 mA for 20 ms and BTA readback (pin 17) = 0 | Pack physically off the bus |
| 5 | FC_CHARGE HIGH (FCC net also selects FC-LOW ceiling via Q_c). Wait tD_ON 8 ms + ramp + 2 ms; V_chg (pin 38) ≈ V_bus | VCHG-IN held at ~15 V by its caps through the 8 ms gap (decay ≈ 5 mA × 8 ms / 51.5 µF ≈ 0.8 V, load an estimate: Hi-Z quiescent unspecified, B5), so no re-POR |
| 6 | Write VINDPM 0x2840 (13.504 V), IIN_HOST 0x0600 (0.30 A), ChargeCurrent from `charge_goal`; readback | (I-2), (I-3) |
| 7 | P5 HIGH (F term grants) | Charging starts at ≤ 0.30 A input |
| 8 | Governor ramps IIN_HOST ≤ +100 mA per 20 ms (§6.4) | Bounded FC boost load step |

### 5.3 T3: FC window -> regen-armed (on brake intent, window end, `charge_goal` = 0, or fault)

| # | Action | Rationale |
|---|---|---|
| 1 | P5 LOW; 1 ms; PERMIT 0 | (I-1) |
| 2 | Write VINDPM 0x3DC0 (19.008 V), IIN_HOST 0x2000 (1.60 A), ChargeCurrent 0x09C0 (2.496 A); readback. On I2C failure continue with P5 LOW (stays inhibited) | (I-2): written while still FC-powered |
| 3 | FC_CHARGE LOW (FCC net LOW -> REGEN-HIGH ceiling) | - |
| 4 | BT_BUS HIGH via the share-loop re-entry and hot-plug guards | Two-source operation |
| 5 | REGEN HIGH (`assertRegenEnable()`), tD_ON 8 ms | Charger stays powered: VCHG-IN on its caps, V-MOT ≈ VBUS |
| 6 | Check CHRG_OK stayed HIGH; re-read VINDPM/IIN_HOST/ChargeCurrent. On mismatch or CHRG_OK fall: treat as POR, rerun §6.1 | (I-3) |
| 7 | P5 HIGH -> REGEN_ARMED | - |

**Timing.** Steps 1-7 ≈ 1 + ~1.5 (three readback pairs at 400 kHz) + 0.1-1 + share re-entry (tens of ms, existing guards)
+ 8 + 1 ms ≈ 15-40 ms. Brake intent (the 50 Hz setpoint fall) leads the V-MOT rise by 80-120 ms ([P37] §3.2), so the
sequencer must trigger on **commanded** deceleration, not on V-MOT. A brake that arrives with no lead (Pi-commanded step to
zero) inside an FC window is lost to the chopper: acceptable, logged.

### 5.4 T4: any -> trip (J-guard, F1-F4, readback mismatch, OV_BATT, State 99)

P5 LOW -> FC_CHARGE LOW -> REGEN LOW (no wait between: P5 LOW is effective in gate delays plus B2). Trip latch: reboot-only
for the Path A bring-up, as fw v37 rev 2 `J` ([FW]); relax to a session latch only after stage 5.

### 5.5 T5: Run -> Finish / Idle, and T6: CHRG_OK fall while armed

T5: P5 LOW, then REGEN LOW (or FC_CHARGE LOW). T6: P5 LOW immediately (pin 6 polled at 1 kHz; the charger's own 50 ms rising
deglitch, [DS] p.7, applies to the rise only); state -> ARMING; after CHRG_OK HIGH rerun §6.1.

### 5.6 Fallbacks if B3 or B4b fails (regen verdict F2/F3)

- **B3 fails** (VINDPM re-measured on each Hi-Z exit): capture continues in "comparator relay" mode (re-measured VINDPM ≈
  V-MOT − 1.28 V ≈ 15.8-16.1 V, so V-MOT is held by H1's 0.30 V hysteresis band with a measurement dead time per cycle). This
  is **disqualified for safety**, not for harvest: each cycle is another B2 exposure and the aggregate is not proven bounded.
  Firmware detects it (§5.1 step 6) and disarms regen for the boot (`CHG_VINDPM_LOST`).
- **B4b fails** (τ too slow): (a) raise the VESC `l_max_vin` to **≤ 23 V** (the BQ25713's recommended VBUS max is 24 V,
  [DS] p.9, ACOV min 25 V, p.15; [REGEN] §4's 24 V example leaves zero margin), which needs C25, C-D8, C-D10 ≥ 35 V and
  M-R0 to confirm the mechanism; at 23 V the 3 m/s budget rises to tens of ms ([REGEN] §4). (b) Firmware pre-release on
  brake intent: during the 80-120 ms lead, let the charger leave Hi-Z with only the VINDPM soft layer (19.008 V, above the
  bus) preventing bus draw, so that it is already switching when V-MOT rises. This bypasses the H1 hardware proof for a
  bounded window, so it needs a gate change (a timed, firmware-requested R-term override capped in hardware, e.g. an RC
  one-shot ≤ 150 ms), proof of retention from B3, and an **operator ruling**. It is not part of the baseline design.
- If (a) is unavailable and (b) is refused: Path A on this IC fails the regen requirement; evaluate the next candidate.

---

## 6. Register sequences

All 16-bit registers are written LSB address first, then MSB, as one I2C transaction from the LSB address; MSB-only
writes are ignored ([DS] §9.5.1.8 p.35). Address 0x6B (7-bit) for BQ25713RSNR ([DS] Table 6 p.5; [UG] BOM p.12).

### 6.1 Configuration sequence (charger held in Hi-Z by hardware; P5 LOW)

| Step | Reg (LSB/MSB) | Write (word) | Decoded | Cite |
|---|---|---|---|---|
| 0 | 0x2E, 0x2F | read: 0x40, 0x88 | ManufacturerID, DeviceID (BQ25713) | [DS] p.72 |
| 1 | 0x00/01 ChargeOption0 | **0x270F** | MSB 0x27: EN_LWPWR 0, **WDTMR_ADJ 01 = 5 s**, IDPM_AUTO_DISABLE 0, OTG_ON_CHRGOK 0, EN_OOA 1, PWM_FREQ 1 = 800 kHz (EVM L1 2.2 µH), LOW_PTM_RIPPLE 1. LSB 0x0F: SYS_SHORT_DISABLE 0, EN_LEARN 0, IADPT_GAIN 0, IBAT_GAIN 1, EN_LDO 1, EN_IDPM 1, **CHRG_INHIBIT 1** | Table 9-5/9-6 p.37-39; reset 0xE70E |
| 2 | 0x30/31 ChargeOption1 | **0x0210** | MSB 0x02: EN_IBAT 0, PSYS 0, RSNS_RAC 0 (10 mΩ), RSNS_RSR 0, PSYS_RATIO 1, **PTM_PINSEL 0**. LSB 0x10: CMP default (deglitch 1 µs), **FORCE_LATCHOFF 0, EN_PTM 0**, EN_SHIP_DCHG 0, **AUTO_WAKEUP_EN 0** | Table 9-7/9-8 p.40-41; reset 0x0211 |
| 3 | 0x32/33 ChargeOption2 | **0x02B7** (= reset, written explicitly) | **EN_EXTILIM 1** (pin ceiling active), Q2_OCP 150 mV, ACX_OCP 150 mV, EN_ACOC 0, EN_BATOC 1; peak-power mode off | Table 9-9/9-10 p.42-43 |
| 4 | 0x34/35 ChargeOption3 | **0x0030** (= reset) | EN_HIZ 0 (hardware owns Hi-Z), RESET_REG 0, RESET_VINDPM 0, **EN_OTG 0**, EN_ICO_MODE 0, OTG_VAP_MODE 1, IL_AVG 15 A, BATFETOFF_HIZ 0 | Table 9-11/9-12 p.44-45 |
| 5 | 0x04/05 MaxChargeVoltage | **0x20D0** | 8400 mV (8 mV LSB in bits 14:3). Never write 0 | Table 9-25/9-26 p.58 |
| 6 | 0x0C/0D MinSystemVoltage | read only: expect **0x1800** | 6.144 V (2S POR). Note RESET_REG would set the 1S value 3.584 V: never use RESET_REG | p.60, p.44 |
| 7 | 0x0E/0F IIN_HOST | regen **0x2000** (1.60 A) / FC start **0x0600** (0.30 A) | MSB × 50 mA; reset 0x4100 = 3.25 A; value is a maximum, typ ~100 mA lower | Table 9-29 p.62; p.61; EC p.12 |
| 8 | 0x0A/0B InputVoltage (VINDPM) | regen **0x3DC0** (19.008 V) / FC **0x2840** (13.504 V) | word = V_mV − 3200 (64 mV LSB, bits 13:6). Accuracy −3/+2 % at 18.688 V -> 18.44-19.39 V; −4/+2.5 % at 10.88 V -> FC 12.96-13.84 V | Table 9-33/9-34 p.64; EC p.12 |
| 9 | 0x3A/3B ADCOption | **0x2057** | one-shot (ADC_CONV 0), full-scale 3.06 V, enable VBUS, IIN, ICHG, VSYS, VBAT | Table 9-17/9-18 p.50-51 |
| 10 | 0x02/03 ChargeCurrent | regen **0x09C0** (2.496 A) / FC ≤ **0x04C0** (1.216 A) | word = I_mA (64 mA LSB, bits 12:6). Accuracy −4/+3 % at 2048 mA | Table 9-23/9-24 p.56; EC p.11 |
| 11 | read back 0x00, 0x02, 0x04, 0x0A, 0x0E, 0x30, 0x32, 0x34 | compare under masks; must-be-zero: 0x30[2], 0x31[0], 0x35[7:4]; must-be-one: 0x32[7] | - | - |
| 12 | 0x00/01 | **0x270E** (CHRG_INHIBIT 0); read back | charging enabled in the IC; still Hi-Z | - |
| 13 | - | P5 HIGH | armed; hardware R/F terms decide conversion | - |

TI's own Hi-Z configuration order is the same shape: Hi-Z first, disable auto-wakeup, check VREG, set current, release Hi-Z,
with a low input limit at first release ([DS] §9.6.5.1 p.61).

POR behaviour handled: AUTO_WAKEUP_EN = 1 at POR (128 mA for ≤ 30 min while VBAT < VSYSMIN, [DS] p.41) fires behind
D-BT-SQ at every input power-up, but only while Hi-Z is off; Hi-Z is held from boot and step 2 clears it first. POR
ChargeCurrent is 0 when auto-wakeup is not active ([DS] p.56); "any CHRG_OK low except ACOV resets ChargeCurrent to 0"
([DS] p.56). ACOV does not reset it (charging resumes 1 ms after ACOV clears, [DS] p.15): ACOV is at ≥ 25 V, above every
board condition, and G3 trips on the latched ACOV flag.

### 6.2 Runtime I2C schedule (non-blocking, one transaction per 1 ms loop tick, 400 kHz; a 16-bit read ≈ 0.12 ms)

| Rate | Transaction | Purpose |
|---|---|---|
| 50 Hz | write 0x3A/3B = 0x6057 (ADC_START) | one-shot conversion; continuous mode updates only every 1 s ([DS] p.50) |
| 50 Hz (≥ 12 ms after start; typ 10 ms, no max) | read 0x27 (VBUS: 64 mV + 3.2 V, saturates at 19.52 V), 0x29 (ICHG 64 mA), 0x2B (IIN 50 mA), 0x2C (VBAT 64 mV + 2.88 V) | telemetry, G1/G2, F1 plausibility |
| 50 Hz | read 0x20/21 ChargerStatus | AC_STAT, IN_VINDPM, IN_IINDPM, IN_FCHRG, IN_PCHRG; latched faults ACOV/BATOC/ACOC/SYSOVP/SYS_SHORT/Latchoff -> G3 ([DS] p.52-53) |
| 1 Hz, only if the interlock tick ran this iteration | write 0x04/05 = 0x20D0 | services the 5 s charger watchdog (4-7 s, [DS] p.19; timer resumes on a write of 0x02/03, 0x04/05 or 0x01[6:5], p.37) |
| round-robin, one per 20 ms (full set ≤ 170 ms) | read 0x00, 0x02, 0x04, 0x0A, 0x0E, 0x30, 0x32, 0x34 | readback trip set (PTM bits, EN_EXTILIM, VREG, VINDPM, IIN, ICHG) |
| on every PERMIT falling edge in regen mode | read 0x0A | B3 monitor |

Wire calls must be bounded: an unpowered or hung slave releases after 25-35 ms ([DS] p.19 ttimeout), which is longer than
the 1 ms tick. Use a non-blocking I2C driver (or a Teensy Wire timeout, TODO(verify: PJRC Wire timeout API)); a stalled
transaction marks the charger UNVERIFIED and drops P5.

### 6.3 Watchdog configuration

Charger: WDTMR 5 s (step 1). Never write 00 (disables and *resumes* charging, [DS] p.30). Serviced only from the main loop,
after the interlock, never from an ISR. On expiry the IC sets ChargeCurrent to 0 and keeps every other register; firmware
detects it on the readback round-robin and re-arms through §6.1 step 10. MCU watchdog: §7.6.

### 6.4 FC-window input governor (50 Hz)

```
I_fc_other   = I_fc(pin 40) - IIN_chg(0x2B)                 // FC boost current not taken by the charger (bus-side approx.)
budget       = min(0.70 A, 1.20 A - I_fc_other - 0.05 A)    // 1.20 A < OC_FC 1.4 A and below SHARE_GOV_I_FC_CEIL_A
IIN_target   = clamp(budget, 0.30 A, 0.70 A); step up <= +100 mA per 20 ms, step down immediate
if budget < 0.30 A for 100 ms -> leave the window (T3)
if I_fc > 1.25 A for 5 ms -> P5 LOW (pre-empts OC_FC)       // single-sample OC_FC remains the backstop
ChargeCurrent = min(charge_goal, 1.216 A, ICHG_from_IIN)    // 64 mA LSB
```
Expected FC charge at IIN_HOST 0.70 A (typ ~0.6 A in): 1.06-1.11 A at 8.0-8.4 V (η 0.935, [DS] Fig. 8-6/8-7 reading).
Also budget the H-20 P_MAX equivalence (1.247 A bus, CLAUDE.md 2026-09-09) in the same clamp.

---

## 7. Firmware architecture sketch (not edited into the .ino)

### 7.1 Files and ownership

| Unit | Responsibility |
|---|---|
| `bq25713.h/.cpp` | Register constants (§6.1), non-blocking I2C job queue, masked readback, ADC one-shot, status decode |
| `chg_mode.h/.cpp` | Mode manager / sequencer (states below), invariants I-1..I-5, governor |
| `chg_interlock` (inside `detectFaults()` path, 1 kHz) | F1-F4, OV_BATT, J guards G1-G3, trip latch, P5 writer |
| `wdt_mcu` (FUTURE WORK, §7.6) | RTWDOG + WDOG1 config, feed, reset cause |

### 7.2 Skeleton

```cpp
// ---- pins (CSV first) -------------------------------------------------------
#define CHG_ARM          5   // was MPPT_DISABLE; HIGH = armed (P5)
#define CHRG_OK          6   // was CHARGER_STAT; BQ25713 CHRG_OK, open drain via EVM R33
#define CHG_H1_RB       33   // TODO(verify: CSV row)
#define CHG_PERMIT_RB   34
#define BT_ACTIVE_RB    17

// ---- BQ25713 (SLUSD83C) -----------------------------------------------------
namespace bq {
  constexpr uint8_t ADDR = 0x6B;
  constexpr uint8_t R_CO0 = 0x00, R_ICHG = 0x02, R_VREG = 0x04, R_VINDPM = 0x0A,
                    R_VSYSMIN = 0x0C, R_IIN = 0x0E, R_STAT = 0x20, R_ADCVBUS = 0x26,
                    R_ADCIBAT = 0x28, R_ADCIIN = 0x2A, R_ADCVSB = 0x2C, R_MID = 0x2E,
                    R_DID = 0x2F, R_CO1 = 0x30, R_CO2 = 0x32, R_CO3 = 0x34, R_ADCOPT = 0x3A;
  constexpr uint16_t CO0_INHIBIT = 0x270F, CO0_RUN = 0x270E;   // WDT 5 s, LWPWR 0
  constexpr uint16_t CO1_SAFE = 0x0210;                        // AUTO_WAKEUP 0, PTM 0
  constexpr uint16_t CO2_SAFE = 0x02B7;                        // EN_EXTILIM 1
  constexpr uint16_t CO3_SAFE = 0x0030;                        // EN_HIZ 0, EN_OTG 0
  constexpr uint16_t VREG_2S  = 0x20D0;                        // 8.400 V
  constexpr uint16_t VINDPM_REGEN = 0x3DC0, VINDPM_FC = 0x2840; // 19.008 / 13.504 V
  constexpr uint16_t IIN_REGEN = 0x2000, IIN_FC_START = 0x0600; // 1.60 / 0.30 A
  constexpr uint16_t ICHG_REGEN = 0x09C0, ICHG_FC_MAX = 0x04C0; // 2.496 / 1.216 A
  constexpr uint16_t ADC_START = 0x6057;
  struct Mask { uint8_t reg; uint16_t mask, want; };
  constexpr Mask kSafety[] = {                                 // readback trip set
    {R_CO1, 0x0105, 0x0000},   // PTM_PINSEL (bit8), EN_PTM (bit2), AUTO_WAKEUP (bit0) must be 0
    {R_CO2, 0x0080, 0x0080},   // EN_EXTILIM must be 1
    {R_CO3, 0xF000, 0x0000},   // EN_HIZ, RESET_REG, RESET_VINDPM, EN_OTG must be 0
    {R_CO0, 0x6000, 0x2000},   // WDTMR = 01
    {R_VREG, 0x7FF8, VREG_2S},
  };
}

enum class ChgMode : uint8_t { OFF, ARMING, REGEN_ARMED, TO_FC, FC_WINDOW, TO_REGEN, TRIPPED };

class Bq25713 {            // non-blocking: at most one transaction per poll()
 public:
  void poll(uint32_t nowUs);                  // advances the job queue
  bool queueWrite(uint8_t reg, uint16_t v);
  bool queueRead(uint8_t reg);
  bool configured() const;                    // §6.1 verified in this power cycle
  uint16_t status() const; float iin() const; float ichg() const; float vbus() const;
  bool readbackMismatch() const;              // any kSafety/target mismatch
  void invalidate();                          // on CHRG_OK fall / I2C stall
};

class ChgModeManager {
 public:
  void tick1kHz();                            // called from loop() after updateSensors()
  void requestFcWindow(float chargeGoalA);    // from chargingControl()
  void brakeIntent();                         // setpoint fall: start T3 if in FC window
  void trip(uint16_t cause);                  // T4, latched
 private:
  void setP5(bool on);                        // the ONLY writer of CHG_ARM
  ChgMode mode_ = ChgMode::OFF;
};

// ---- 1 kHz interlock (runs inside detectFaults() every tick, all builds) ---
void chgInterlock1k() {
  const bool p5 = digitalReadFast(CHG_ARM);
  const bool h1 = digitalReadFast(CHG_H1_RB), permit = digitalReadFast(CHG_PERMIT_RB);
  const bool bta = digitalReadFast(BT_ACTIVE_RB);
  if (!digitalReadFast(CHRG_OK) && p5) chg.invalidateAndDropP5();          // T6
  // F1: H1 must agree with calibrated ADCs (V_rgn calibrated first, M8)
  const bool h1_pred = V_rgn_cal > 1.067f * V_bus + 0.30f;
  const bool h1_never = V_rgn_cal < V_bus + 0.20f;
  if (h1 && h1_never) persist(F1_H1_STUCK_HIGH, 5 /*ms*/);
  // F1b: PERMIT LOW but charger draws (Q_a open / Hi-Z ignored): IIN ADC > 100 mA for 40 ms
  if (!permit && chg.iinA() > 0.10f) persist(F1_HIZ_IGNORED, 40);
  // F1c: PERMIT readback must equal the gate equation from known inputs
  // F4: pack feeding the bus while BT_BUS commanded LOW (any mode)
  if (!digitalReadFast(BT_BUS_ENABLE) && (I_batt - I_BT_OFFSET) > 0.05f) persist(F4_BT_LEAK, 20);
  if (digitalReadFast(FC_CHARGE_ENABLE) && bta) chg.trip(F4_BTA_IN_FC);
  // G1 (FC window / J session): bus-side I_fc + I_batt > 1.0 A + motor allowance for 5 ms
  // G2: P_boosts - P_vesc - P_aux - P_chg_in > 3 W for 20 ms  (VESC input power rate TODO(verify))
  // G3: ChargerStatus latched faults (0x20 bits 7..2) -> trip
  if (chg.readbackMismatch()) chg.trip(CHG_REG_MISMATCH);                   // PTM, EXTILIM, VREG ...
  if (V_batt > LIMIT_V_BATT_MAX) chg.trip(OV_BATT);                          // all builds
}
```

`FAULT_SWITCH_CONFLICT` moves out of `#if !BENCH_TEST` ([FW] ~7413). State 98 `'M'` stops toggling pin 5 directly and calls
`ChgModeManager` (verified-config gate). The fw v37 rev 2 `J` session (charger fed through MOT_PWR + REGEN with BT_BUS on)
closes L-R by construction and is **redefined as an FC-path session** (BT_BUS 0, F term). `AG105_VBATN_ISOLATED` and the Ag105
paths (`pollAg105()`, reg 0x00-0x06 writes, MPPT ratchet, `ag105IsReady()`) are removed; `I_charge` is fed from 0x29.

### 7.3 Mode manager states

`OFF` (REGEN 0, FCC 0) -> `ARMING` (T1 steps 1-4) -> `REGEN_ARMED` -> `TO_FC` (T2) -> `FC_WINDOW` -> `TO_REGEN` (T3) ->
`REGEN_ARMED`; any -> `TRIPPED` (T4, latched to reboot). Run exit -> `OFF` (T5). State 99 entry calls `trip()` first.

### 7.4 Telemetry and the forced protocol bump

Proposed **protocol v5** (to be executed with the `protocol-bump` skill; the Pi bridge must change in lockstep):

| Field | Type | Content |
|---|---|---|
| `charger_status` (offset 51, existing byte) | u8 | REG 0x21 (AC_STAT, IN_VINDPM, IN_IINDPM, IN_FCHRG, IN_PCHRG...) - meaning changes from Ag105 Table 6 |
| `I_charge` (existing float) | f32 | ICHG ADC 0x29, 64 mA LSB |
| new `chg_fault` | u8 | REG 0x20 latched faults (OR-accumulated between packets) |
| new `chg_iin` | u8 | IIN ADC 0x2B, 50 mA LSB |
| new `chg_vbus` | u8 | VBUS ADC code 0x27 (64 mV + 3.2 V; 0xFF = saturated) |
| new `chg_mode` | u8 | `ChgMode` |
| new `chg_hw` | u8 | bits: P5, H1, PERMIT, BTA, CHRG_OK, configured, trip latch, VINDPM-lost |
| new `chg_cfg` | u8 | bits: regen/FC profile, IIN_HOST code high bits |

Six bytes added: 58 -> **64 bytes**, checksum over bytes 1-62 (layout and offsets fixed by the protocol-bump procedure
against PLAN.md §6b; these numbers are a proposal). `switch_state`, `fault_flags` (16-bit) and `error_code` gain new
codes: `CHG_NO_ACK`, `CHG_REG_MISMATCH`, `CHG_VINDPM_LOST`, `F1_H1_STUCK_HIGH`, `F1_HIZ_IGNORED`, `F4_BT_LEAK`,
`F4_BTA_IN_FC`, `ERR_MCU_WDT`. BLG gains the same bytes in its next version.

### 7.5 Tests (host-native, before any flash)

Mock BQ25713 on the Wire mock (register file, POR values per §6.1, auto-reset rules: ChargeCurrent -> 0 on CHRG_OK low,
IIN -> 3.25 A on adapter removal, watchdog expiry). Cases: §6.1 order and masks; P5 never HIGH before verification; P5 drop on
CHRG_OK fall within one tick; T2/T3 order including the CSV rule; readback trip on each forbidden bit; governor never
commanding > 0.70 A or stepping > 100 mA/20 ms; F1/F4 persistence; `J` refusal with BT_BUS HIGH; State-99 step 0 drops P5;
`FAULT_SWITCH_CONFLICT` active in BENCH_TEST 1.

### 7.6 MCU hardware watchdog: REQUIRED FUTURE WORK (operator ruling 5)

No MCU watchdog exists today (only the Pi watchdog `checkPiWatchdog`, [LOOP] §10). **Path A must not run an unattended
charger session until this is implemented and passes M6.**

| Item | Specification |
|---|---|
| Primary timer | **RTWDOG (WDOG3)**, 32 kHz LPO clock, **timeout 100 ms (TOVAL 3200)**; range up to 2.048 s without prescaler (source: tonton81/WDT_T4 `Watchdog_t4.tpp` WDT3 branch, [LOOP] §10; NXP i.MX RT1060 RM is a missing primary) |
| Secondary timer | **WDOG1, 1.0 s** (0.5-128 s in 0.5 s steps, WDT_T4 WDT1 path), independent of RTWDOG |
| Pins | WDOG1_B, if routed, on **pin 20** (spare); **never pin 19 (SCL)**. EWM optional on pin 21 (never pin 25 = BT_VOLTAGE) |
| Feed | Exactly once per `loop()` iteration, only after `detectFaults()`, `chgInterlock1k()` and the switch writer ran in that iteration; never from an ISR/timer; no feed inside blocking calls |
| Blocking budget (lower bound for the timeout, measure first) | SdFat synchronous write/close; EEPROM commit (fw v28 rev 3, duration TODO(verify: PJRC)); Wire to an unpowered charger (bounded by §6.2's non-blocking driver); Serial bursts. Pass: worst measured stall ≤ 50 ms (half the timeout) |
| On timeout | System reset; pins go high-Z; 10 kΩ RT1987 EN pull-downs open every path (each RT1987 also has a 475-985 kΩ internal pull-down, [RT] p.7); carrier P5 pull-down -> PERMIT LOW; the charger loses input power; V-MOT isolated on CAL (same as any MOT_PWR open during braking). Pad keeper state after reset: TODO(verify: i.MX RT1060 RM IOMUXC) |
| After reset | Read `SRC_SRSR` (WDOG3_RST_B / WDOG1 bits) -> latch `ERR_MCU_WDT` into telemetry; require Pi/operator acknowledgement before Run; re-bring-up through the existing staged bring-up and `assertMotPwrEnable()`/`motPwrHotPlugUnsafe()` guards; charger reconfigured from POR under P5 LOW |
| Proof | Host-native: a mock RTWDOG counter that must never be fed on an iteration that skipped `detectFaults()`. Bench (M6): a BENCH_TEST-only State-98 hang key spinning with P5, REGEN and BT_BUS HIGH; scope EN nets and PERMIT. **Pass: reset within 100 ms (+ LPO tolerance, TODO(verify: RM)), every EN < 0.6 V and PERMIT LOW within 1 ms of reset, `ERR_MCU_WDT` latched after boot** |

---

## 8. Quantitative checks

### 8.1 Inrush (RT1987 slew 12.0 V/ms, i.e. 12 mA/µF, [SPEC] §6; nominal C is the worst case)

| Case | C on VCHG-IN | Inrush | + aux 0.15 A | Limit | Result |
|---|---|---|---|---|---|
| Stock EVM + board | 94.5 + 20 = 114.5 µF | 1.37 A | 1.52 A | OC_FC 1.4 A single sample | **FAIL** |
| Modified EVM (E7, E8) + board | 31.5 + 20 = 51.5 µF | 0.62 A | **0.77 A** | budget 1.0 A | PASS |
| Regen arm (REGEN close from V-MOT ≈ 16 V) | 51.5 µF | 0.62 A from CAL, replenished by both boosts | - | Death-5 class needs mF-class bulk | PASS (no bulk) |
| Warm transitions (T2/T3) | VCHG-IN already ≈ 15 V | ≈ 0.1 A (≈ 1 V re-charge) | - | - | PASS |
| Hi-Z exit, SYS caps (~136 µF) charged to VSYSMIN 6.144 V | from V-MOT (regen) / from FC bus at IIN ≤ 0.30 A start (FC) | ≤ pin ceiling | FC: ≤ 1.13 + 0.15 = 1.28 A worst | OC_FC 1.4 A | PASS (B6 confirms; input-loop overshoot unspecified) |

Converter cannot switch during the 1.3-1.75 ms ramp (starts 150 ms after CONVEN, [DS] p.24).

### 8.2 Threshold margin stack-up (regen profile)

| Quantity | Value | Basis |
|---|---|---|
| VBUS steady max | 16.23 V (VREF +2 %), 16.39 V if the bodged RD1 is 1 % | [LOOP] §4.2, [TPS] p.6 |
| VBUS transient park | 17.0-17.2 V, ≤ 5 ms above 17.0 V | [LOOP] §4.2 (regen-onset overshoot unmeasured: M4) |
| D-MT-EN forward drop | V-MOT ≈ VBUS − 35 mV typ in cruise | [RT] p.7 (favourable: lowers V-MOT) |
| H1 permit rise, worst max | 17.29 / 17.83 / 18.70 V at VBUS 15.9 / 16.39 / 17.2 V | §3.2 |
| H1 inhibit fall, worst min | 16.66 / 17.19 / 18.05 V | §3.2 |
| VINDPM (code 247) | 18.44-19.39 V | [DS] p.12 |
| D-BC-RG + 110 mm trace + 150 mm lead at 1.6 A | 35 mV + 1.6 × (20 + 35 + 5) mΩ ≈ 0.13 V | [RT]; [SPEC] §7 trace ≈ 35 mΩ. V-MOT sits **above** VCHG-IN by this drop |
| V-MOT ripple | unmeasured (M4) vs H1 hysteresis 0.30 V and 24 µs filter | - |
| VESC regen cut-off | ~21.35 V (mechanism to confirm, M-R0) | [REGEN] §1 |
| Chopper clamp | 21.4 V true measured (design 22.13 V) | [LOOP] §4.2 |
| BQ25713 recommended VBUS max / ACOV min / abs max | 24 V / 25 V / 30 V | [DS] p.9, p.15 |

| Margin | Value | Result |
|---|---|---|
| VINDPM min − H1 rise max at steady bus 16.39 V | 18.44 − 17.83 = 0.61 V | absorption never chatters H1 |
| VINDPM min − H1 rise max in a 17.2 V park | 18.44 − 18.70 = −0.26 V | a burst starting inside a park is withheld ≤ 5 ms (safe direction); a running absorption continues (fall min 18.05 V < 18.44 V) |
| VINDPM min − fw OV latch 17.5 V | 0.94 V | pass |
| VINDPM min − TPS61288 OVP min 18.3 V | **0.14 V** | the soft layer alone does not cover a failed-FB boost; **H1 does** (tracks VBUS, fall min ≥ 19.23 V at 18.3 V bus) |
| VESC cut − (VINDPM max + path drop) | 21.35 − 19.52 = 1.83 V | the charger holds V-MOT ~1.8 V under the cut-off once it is warm |
| Clamp/ACOV: 25 V − 21.4 V | 3.6 V | ACOV never fires on the board |
| Ceramics: C25, C-D8, C-D10 ≥ 35 V vs 21.4 V (23 V if the VESC cut is raised) | ≥ 12 V | pass after E9/B2 |

### 8.3 Regen capture estimate

From [REGEN] §3 (C = 0.97 mF HIL nominal, ceiling 2.5 A, Vth 19.0 V):

| Decel | Ideal into pack | Warm, τ ≤ budget | τ above budget (VESC trips, 0.53 s coast) | τ budget at 0.97 mF (4 mF) |
|---|---|---|---|---|
| 2 -> 1 m/s, 12 A | 1.81 J / 215 mC | 96-99 % | 36-40 % | 17 ms (114 ms) |
| 3 -> 1 m/s, 12 A | 5.55 J / 661 mC | 96-99 % | 6-40 % | 4.5 ms (23 ms) |
| 2 -> 1 m/s, 5 A | 1.83 J | 95-97 % | - | 73 ms (> 300 ms) |

Design-specific adjustments:
- **Head start.** The charger leaves Hi-Z at the H1 rise (~17.1 V at a 15.9 V bus), 1.9 V before V-MOT reaches VINDPM. At the
  model's 0.97 mF and an 11-19 W surplus V-MOT rises at ~0.6-1.1 V/ms, giving ~2-3 ms extra; at the measured 0.11-0.28 V/ms
  (which implies C ≈ 4 mF) it is 7-17 ms ([REGEN] §2). B4b measures τ from the H1 edge, so this is credited only once
  measured.
- **Input capability.** min(pin 1.33 A, IIN_HOST typ ≥ 1.40 A) × 18.44 V ≥ 24.5 W ≥ 23 W. ChargeCurrent 2.496 A at a 7.4 V
  pack is 18.5 W out, ~20 W in at η 0.924 ([DS] Fig. 8-7): above the 18.9 W peak of a 3 m/s brake, below the 23 W design
  margin. If the pack rating allows, raise regen ChargeCurrent to 0x0B80 (2.944 A) - TODO(verify: pack datasheet max charge
  current); otherwise cap the VESC Battery Current Regen Max (0.98-1.23 A at 19 V, [REGEN] §5).
- **Near full charge** the CV taper reduces absorption; V-MOT then climbs to the cut-off and the chopper takes it. The EMS
  should hold SoC below the CV knee when regen is expected.
- **EMS visibility:** 0.2-0.66 C per hard decel; the 64 mA ICHG LSB gives ~1 % error per event ([REGEN] §6).

### 8.4 Thermal

| Case | P_out | η ([DS] Fig. 8-6/8-7 reading) | Loss | Notes |
|---|---|---|---|---|
| FC window, 1.1 A at 8.2 V | 9 W | ~0.935 at 16 V | ~0.6 W | continuous |
| Regen burst, 2.5 A at 8.4 V, 19 V in | 21 W | ~0.925 | ~1.7 W | 0.3-0.6 s bursts |
| Worst, 24 W out at 19 V | 24 W | ~0.925 | ~1.95 W | - |
| Sense resistors (2.5 A) | - | - | RSR 62 mW, RAC ~25 mW | 1 W parts |

RθJA 37.2 °C/W, TSHUT 155 °C ([DS] p.10, p.16); EVM rated 8 A out / 3 A in ([UG] Table 3); L1 8.5 A. Off-board in free air: no
thermal concern. Light-load efficiency at the burst tail (50 mA) ~79 % ([DS] Fig. 8-3).

### 8.5 CV error through D-BT-SQ

CV is regulated at SRN (= the EVM BAT terminal): 8.400 V ±0.6 % = 8.350-8.450 V ([DS] p.11). The pack sees SRN minus the lead
(6.3 mΩ round trip) and D-BT-SQ (max(35 mV typ VFWD, I × 20 mΩ RON), [RT]):

| I | Drop (D-BT-SQ + lead) | Pack voltage band |
|---|---|---|
| 2.5 A | 50 + 16 = 66 mV | 8.284-8.384 V |
| 0.5 A | 35 + 3 = 38 mV | 8.312-8.412 V |
| taper 0.1 A | 35 + 1 = 36 mV | 8.314-8.414 V |

Never above 8.415 V: 85 mV under OV_BATT 8.5 V; BATOVP 8.61-8.82 V ([DS] p.15). Under-charge of ≤ 0.12 V at taper (safe
direction). The 35 mV VFWD is typ only. Termination is host-only ([DS] §9.4.1.2 p.31): firmware ends charge at ICHG ≤ 128 mA
(two LSBs) with V_batt ≥ 8.30 V for 10 s, then CHRG_INHIBIT 1.

---

## 9. Staged bench plan (each stage is a go/no-go gate)

### Stage 0: board-side facts (no new charger; current fw v37 rev 2 board)

| Test | Pass |
|---|---|
| M-R0: State-98 `U` VESC fault watch during a step decel; read Maximum Input Voltage, Fault Stop Time, fault log in VESC Tool | Mechanism of the ~21.35 V cut-off identified (expected `l_max_vin` over-voltage fault) |
| M-R1: V-MOT capacitance (decay or charge-pulse method) | Value with ±20 % |
| M-R2: scope true V-MOT vs pin 39 at ~21 V | V-MOT peak < 22.5 V; V_rgn gain recorded |
| M8: calibrate V_rgn ADC (0.85×) | Error < 1 % |
| **M-R3 (decisive)**: electronic load in CV mode at 19.0 V, current limit 1.3 A, on V-MOT during step decels 2 -> 1 and 3 -> 1 m/s | **GO if braking continues for ≥ 0.25 s with V-MOT held at 19 V** (mechanics-limited energy available). If the pulse still ends after 30-50 ms: no charger can meet regen without changing the VESC: **STOP** and resolve the VESC configuration first |

### Stage 1: standalone EVM on the bench (no Teensy logic; two EVMs ordered)

Rig: modified EVM; **emulated V-MOT node** = 0.97 mF film/electrolytic on a breadboard bus fed by supply A (16.0 V, "VBUS")
through an ideal-diode stand-in (an RT1987 on a spare board, or a Schottky with its drop noted) and by supply B (21 V,
current-limited to 0.6 A, i.e. an ~11 W regen current source) switched by a MOSFET; a second U1 comparator built on the same
values watching node vs supply A; the EVM VIN through a second RT1987/ideal diode; battery side = a 2S pack at 7.6-8.0 V
behind an RT1987 (or a Schottky) with a 10 µF VCHG node; electronic load on J6 off. Scope: node, VCHG-IN, VCHG, TP22, battery
current (current probe or 10 mΩ shunt), input current.

| Gate | Test | Pass / fail |
|---|---|---|
| S1.1 (B0) | Continuity J1-GND/J5-GND/J6-GND; CELL pin | < 0.1 Ω; CELL 2.6-2.8 V |
| S1.2 (B1) | TP22 with PERMIT LOW, PERMIT wire open, REGN only; with PERMIT HIGH (FCC LOW / HIGH) | **< 0.3 V** in every off case; 1.61-1.83 V (REGEN-HIGH) and 1.20-1.37 V (FC-LOW) released |
| S1.3 (B7) | Power-up into the battery stand-in from VCHG = 0 V, AUTO_WAKEUP 0 written in Hi-Z | No current into the pack before release; after release D-BT-SQ stand-in closes; no BATOVP / SYS_SHORT flags |
| S1.4 (B5) | Stiff 16.0 / 17.5 / 18.3 V, VINDPM 19.008 V, ICHG 2.496 A, not Hi-Z; and in Hi-Z | Input current **< 10 mA**, IIN ADC 0, IN_VINDPM 1; Hi-Z quiescent recorded; VCHG decay rate over 60 s recorded |
| S1.5 (B3) | VINDPM readback after 50 Hi-Z pin cycles, an EN_HIZ cycle, a 26 V ACOV step (C25 already replaced), a watchdog expiry, a dip to 15 V | **Unchanged 0x3DC0 in every case**. Any change -> §5.6 |
| S1.6 (B2) | Charger converting at IIN 1.6 A; PERMIT falling edge -> input current < 10 mA | **≤ 275 µs** (= 290 µs × 1.5/1.6) |
| S1.7 (B4a) | VINDPM step 18.5 -> 20 V with a stiff source | record τ |
| S1.8 (B4b, decisive) | Charger idle in Hi-Z at node 16 V with **VCHG decayed below 6.144 V** (after the S1.4 decay interval, ≥ 10 s), then switch supply B on (node rises at 0.6 A/0.97 mF ≈ 0.6 V/ms); permit from the comparator | τ (H1 edge -> battery current 63 % of the steady burst current) **≤ 4 ms + measured head start; 10-90 % ≤ 9 ms; node peak < 21.0 V**. Also run with 4 mF to confirm the [REGEN] scaling |
| S1.9 | 1 h FC-profile charge at 0.7 A IIN from a 16 V supply into the pack stand-in | ICHG 1.0-1.15 A; EVM hottest part < 70 °C; taper ends at SRN 8.35-8.45 V |

**GO to stage 2 only if S1.5 and S1.8 pass** (or a §5.6 fallback is accepted by the operator).

### Stage 2: Teensy control and loop-impossibility tests (bench harness, not the car)

Teensy 4.1 on a bench harness with the interlock carrier, both EVM rigs, EN nets driven by the firmware into RT1987 stand-ins.
Firmware: the §7 driver and mode manager on a bench build.

| Gate | Forced condition | Pass |
|---|---|---|
| S2.1 | Full §6.1 sequence; 1000 arm/disarm cycles | 0 readback mismatches; P5 never HIGH before verification (logic analyser on pin 5 vs I2C) |
| S2.2 | Teensy reset button held during an active permit | TP22 < 0.3 V within 1 ms; input current < 10 mA within B2 |
| S2.3 | Hang (spin loop, P5 HIGH) - without the MCU watchdog | PERMIT follows the hardware equation (stays LOW without H1/F); ChargeCurrent -> 0 within **7 s** (charger WDT) |
| S2.4 | I2C SDA shorted to GND for 1 s; then released | P5 LOW within 20 ms (configured() false); re-arm only after a full readback |
| S2.5 | Carrier 3V3 removed during a permit | Hi-Z (Q_a on from REGN) |
| S2.6 | H1 output lifted (stuck LOW) during an emulated burst | no harvest, no fault other than F1 "no permit during burst" (warning) |
| S2.7 | H1 forced HIGH (jumper) in emulated cruise | **F1_H1_STUCK_HIGH trip ≤ 5 ms**; REGEN and FC_CHARGE opened |
| S2.8 | 30 mV injected on the BT_CURRENT node during an emulated FC window | PERMIT LOW within 50 µs (BTA); trip latched |
| S2.9 | Firmware writes EN_PTM 1 (bench-only build, current-limited 0.3 A supply, pack replaced by a 10 Ω load) | Readback trip **≤ 200 ms**, REGEN/FCC open. Also record whether PTM was entered with ILIM_HIZ grounded and EN_EXTILIM 1 (does EN_EXTILIM 1 block PTM? loop verdict F3) |
| S2.10 | EN_EXTILIM 0 written (bench-only) | Readback trip; also confirm whether Hi-Z still works with EN_EXTILIM 0 ([DS] p.61 ambiguity) |
| S2.11 | REGEN and FCC nets both HIGH (forced) | PERMIT LOW (R and F both 0) |

### Stage 3: integration on the board (wheels off), scope-armed

Desolder the Ag105 only now. Fit carrier, EVM, B2 capacitors. Scope: V-MOT, VCHG-IN, VCHG, VBUS (4 ch); current clamp on the
battery lead and on the EVM input lead; logic channels on P5, H1, PERMIT, BTA, REGEN, FCC, BT_BUS.

| Gate | Test | Pass |
|---|---|---|
| S3.1 (M7) | Boot self-test: FCC = REGEN = 0, V_chg decays to < 1 V; H1 = 0 in Idle; BTA = 0 with BT_BUS 0 | every boot |
| S3.2 (M1) | H1 trip points vs VBUS (bench supply on the V-MOT leg via the carrier test pad, bus live) | within §3.2; hysteresis 0.25-0.35 V |
| S3.3 (B6) | First FC window at IIN 0.30 A, standstill | Bus-side peak < 1.0 A including the FC_CHARGE ramp and Hi-Z-exit step; no OC_FC; V_bus min > 15.0 V |
| S3.4 | Governor ramp to 0.70 A with the motor at constant low speed | I_fc ≤ 1.20 A always; no OC_FC; FC charge 1.0-1.15 A |
| S3.5 (B9) | CV taper to termination | Pack ≤ 8.415 V; termination fires |
| S3.6 | Regen-armed cruise, motor spinning, 10 min | **0 PERMIT events**, IIN ADC 0, charger input < 10 mA by clamp, 0 trips |
| S3.7 (M4) | Bus/V-MOT ripple and onset overshoot | ripple < 0.15 V p-p (half the hysteresis); overshoot < 17.5 V |
| S3.8 (M6-lite) | Teensy reset during regen-armed cruise | all EN < 0.6 V; PERMIT LOW; no boost fault on re-bring-up |

### Stage 4: real regen decels and transitions

| Gate | Test | Pass |
|---|---|---|
| S4.1 | Step decels 2 -> 1 m/s and 3 -> 1 m/s at -12 A, wheels off then on the rig, 20 each | V-MOT peak < 21.0 V (no VESC cut); captured charge (ICHG integral and clamp) ≥ 80 % of the model (≥ 170 mC / ≥ 530 mC); during every permit I_bt and I_fc show no rise above pre-burst + 0.1 A (no L-R signature) |
| S4.2 | VESC abrupt stop during absorption (State-98 `setCurrent(0)` mid-burst) | bus-side current pulse ≤ I_in × (t_inh − 0.29 ms); single pulse; no OC_FC |
| S4.3 | 100 FC <-> regen transitions under a drive cycle with brake-intent triggering | 0 trips, 0 UV_BUS, 0 loop flags; no brake lost when the lead ≥ 50 ms |
| S4.4 | J-guard injection (G1-G3) on the vehicle | each trips and latches |

### Stage 5: endurance and the MCU watchdog (gate for unattended use)

RTWDOG/WDOG1 implemented (§7.6); M6 passes; 1 h drive cycle with FC windows and regen: 0 trips; SoC accounting from ICHG
within 5 % of the pack-voltage estimate. **Only after stage 5 is any unattended charger session allowed.**

---

## 10. Cost, parts, schedule, residual risks

### 10.1 Parts to order (TI store inventory read with plain curl, 2026-11-05)

| Part | Qty | Unit | Stock found today | Notes |
|---|---|---|---|---|
| BQ25713EVM-017 | 2 (one spare / stage-1 destructive tests) | USD 156.45 | **38** | TI store ([DOS] §2.11 price; inventory re-read today) |
| TLV3012BIDCKR (SC70-6) | 4 | - | 144 621 | TLV3012BIDBVR (SOT-23) 27 694 if SC70 is awkward on perfboard |
| SN74LVC1G08DBVR | 4 | - | 1 180 294 | G2, G6 |
| SN74LVC1G27DBVR | 2 | - | 84 489 | G1 |
| SN74LVC1G11DBVR | 2 | - | 36 150 | G3 |
| SN74LVC1G04DBVR | 2 | - | 421 236 | G4 |
| SN74LVC1G32DBVR | 2 | - | **54** | G5; low stock: order now or substitute (NOR + INV) |
| 2N7002-class NMOS | 6 | - | not checked | Q_a, Q_b, Q_c (+ spares) |
| 0.1 % resistors 499k, 464k, 56.2k×2; 1 % 6.49M, 61.9k, 1.00k, 154k, 324k, 100k, 47k, 1k | kit | - | not checked | |
| 0.47 µF ≥ 50 V X7R 0805 (C25); 10 µF ≥ 35 V X7R (C-D8, C-D10) | 4 / 4 | - | not checked | |
| 18/20/26/28 AWG wire, 0.1" headers, perfboard, standoffs | - | - | - | |

Prices for the small parts were not quoted (Mouser and Farnell unreachable from this session). Estimate: EVMs USD 312.90
+ small parts ~USD 40-80 (estimate, unverified) + shipping.

### 10.2 Schedule estimate (calendar, one operator)

| Stage | Effort |
|---|---|
| 0 (M-R0..M-R3, M8) | 1-2 days, can start now |
| Order lead time | days (EVM in stock at TI) |
| EVM mods + carrier build | 2 days |
| 1 (standalone EVM, incl. B3/B4b) | 2-3 days |
| Firmware driver + mode manager + tests + protocol v5 | 4-6 days (orchestrated round) |
| 2 (Teensy control, failure injection) | 2 days |
| 3 (integration) | 2 days |
| 4 (regen decels, transitions) | 2-3 days |
| MCU watchdog (future work) + stage 5 | 2-3 days |
| **Total** | **~3-4 weeks** to stage 4; stage 5 before unattended use |

### 10.3 Residual risks, ranked

| # | Risk | Effect | Mitigation / owner gate |
|---|---|---|---|
| R1 | VINDPM re-measured on Hi-Z exit (B3) | Regen architecture disqualified on this IC | S1.5; §5.6 fallbacks; next candidate |
| R2 | Hi-Z-exit warm response too slow (B4b) | Regen capture falls to 6-40 % on hard brakes | S1.8; raise VESC cut ≤ 23 V; capacitance per M-R1 |
| R3 | VESC stops regenerating at ~21.35 V for a non-voltage reason (M-R3 fails) | No charger can meet regen without VESC changes | Stage 0 first |
| R4 | Hi-Z entry latency > 275 µs (B2) | One bounded bus-feed pulse per abrupt stop (not a loop) | S1.6; lower regen IIN_HOST scales the budget 1/I |
| R5 | No MCU watchdog until future work lands | A hang freezes switch states; hardware gating holds, overcharge rests on CV, FC overload on the TPS61288's own limit | §7.6; no unattended sessions before stage 5 |
| R6 | PTM / EN_EXTILIM register corruption | Unregulated input pass-through for ≤ 170 ms until the readback trip | Never-write rule, readback trip, S2.9/S2.10 |
| R7 | D-BT-EN short below the BTA threshold in an FC window | ≤ 0.29 A circulating for ≤ 20 ms until F4 | F4 calibrated after the INA253 offset is measured |
| R8 | FC window loses brakes with no setpoint lead | Regen lost for that event (chopper) | Logged; EMS avoids FC windows near expected braking |
| R9 | No battery temperature input (no TS pin; NTC unwired) | Charging at out-of-range pack temperature | Optional NTC on pin 16 + firmware qualify |
| R10 | 64 mA ICHG resolution | ~1 % per-event EMS error; blind to tail currents | Accept; or add IBAT analog pin to a spare ADC later |
| R11 | Off-board EVM wiring (vibration, connector) | Lost PERMIT wire = Hi-Z (safe); lost power lead = no charging; lost I2C = disarm | Strain relief; fail-safe by design |
| R12 | SN74LVC1G32 low stock (54) | Build delay | Order now or NOR+INV substitute |

---

## 11. Requirement status summary

| Req | Status |
|---|---|
| Common ground, high-side sense | PROVEN_DATASHEET ([UG] Fig. 11, [DS] p.6-8) |
| Hard inhibit while powered (mechanism) | PROVEN_DATASHEET (ILIM_HIZ, [DS] p.18, p.25); **latency BENCH_GATE (B2)** |
| Fail-safe (reset, hang, I2C, 3V3, POR) | PROVEN_CALC with this design (§3.4, §3.6); hang bound needs the MCU watchdog (future work) |
| Loop impossibility (L-R, L-F) | PROVEN_CALC in hardware (§3.6), single-fault table complete; residual R7 bounded by F4 |
| No runaway | PROVEN_DATASHEET + CALC (ceilings §3.5, CV/BATOVP); PTM readback (R6) |
| FC charging | PROVEN_DATASHEET; **inrush and governor BENCH_GATE (B6/S3.3-S3.4)** |
| Regen threshold placement | PROVEN_CALC (§8.2) |
| **Regen capture** | **BENCH_GATE: B3, B4b, B2 and board-side M-R0/M-R3** |
| Voltage ratings | PROVEN_DATASHEET after E9 and B2 |
| CV through D-BT-SQ | PROVEN_CALC (§8.5) |
| Telemetry | PROVEN_DATASHEET; protocol v5 to be executed |
| MCU hardware watchdog | **REQUIRED FUTURE WORK** (§7.6) |

## 12. missing_primaries

- **BQ25713 Hi-Z entry/exit latency, VINDPM loop bandwidth / transient, and VINDPM retention across Hi-Z/ACOV/watchdog**: not in
  SLUSD83C. TI E2E/FAE or bench B2-B4.
- **BQ25713 VBUS-side quiescent current in Hi-Z and below VINDPM**: not in SLUSD83C (B5).
- **NXP i.MX RT1060 Reference Manual** (RTWDOG/WDOG1/EWM, SRC_SRSR, IOMUXC pad reset/keeper): login-gated; WDT_T4 source used instead (not
  an NXP primary).
- **PJRC Teensy 4.1** pad state during reset, boot time to `setup()`, Wire timeout API, EEPROM commit duration.
- **2N7002 / 2N7002ET1G** datasheet (Q_a/Q_b/Q_c VGS(th), leakage; ti.com symlink returned HTML).
- **BAT54H (EVM D2/D3/D5), SMAJ26CA (Z1), CSD25402Q3A (Q7 BATFET)** datasheets.
- **Murata GRM21BR61E106KA73L** DC-bias curve (effective EVM input C) and the C-D8/C-D10 replacement's curve.
- **BQ25713EVM-017 mechanical drawing / design files** (not in SLUUBT8B).
- **INA253A1** zero-current offset (`references/Datasheets/INA253A1IPWR.pdf`, not re-read this round): sets the BTA and F4 thresholds.
- **TL431** datasheet (clamp tolerance; BOM ±0.5 % only).
- **RT1987 turn-off delay** (absent from DS-00): M3.
- **VESC Six EDU** `l_max_vin` default, over-voltage fault behaviour in current control, fault-stop time, input capacitance: M-R0/M-R1.
- **2S pack datasheet** (maximum charge current; gates the optional 2.944 A regen ChargeCurrent).
- **Mouser / Farnell** stock, price, lead time for the EVM and small parts (hosts still unreachable from this session).
