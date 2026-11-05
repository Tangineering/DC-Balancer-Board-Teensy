# Dossier R2: TI BQ25720 on the BQ25720EVM (BQ25723EVM sibling), Path A requirement matrix

Round 2, 2026-11-05. Read from primary documents this time:

- **[DS]** TI SLUSDU3 (May 2021), BQ25720 data sheet.
  - Local copy: `.../charger_eval/datasheets/BQ25720_ds.pdf` and its `.txt`.
  - Page numbers ("p.N") are PDF pages, which match the printed page numbers.
- **[UG]** TI SLUUC74 (May 2021, document footer "last updated 10/2025"), BQ25720/BQ25723 EVM user's guide.
  - Includes Table 1-1 (I/O), Table 1-2 (jumpers), Table 1-3, Table 3-1 (BOM, p.10-11) and Figure 3-7 (schematic, p.18).
  - I rendered the schematic at 450 dpi and read it visually; crops are in `r2/evm720/`.
- **Board facts:** from the round-1 interface spec (`docs/reviews/charger_eval_2026-11-05/spec.md`), plus the round-2 cross-cutting notes `r2/loop_analysis.md` [LA] and `r2/regen_dynamics.md` [RD].
- **Pricing:** www.ti.com/tool/BQ25720EVM and /BQ25723EVM, fetched with plain curl on 2026-11-05.

Tag conventions:
- **UNVERIFIED**: not found in any primary document read here.
- **TODO(verify: X)**: names the document that would close the item.

---

## 0. Bottom line

| | |
|---|---|
| Verdict | **FEASIBLE_WITH_CONDITIONS.** No datasheet showstopper was found. Regen capture, a hard requirement under operator ruling 1, depends on four bench gates that the documents cannot close (M2, M-R4, M-PARK, M-D-BT-SQ). Two of them are pre-purchase-relevant: M-R3 on the board and M-R4 on the EVM. |
| Why it can work | (1) **ILIM_HIZ** is a true hardware converter-off input. Below 0.4 V the device is in HIZ; above 0.8 V it exits. It is level-sensitive, unlatched, works straight out of POR and needs no I2C. (2) **ChargeCurrent = 0 A at POR**: the device never charges by itself. (3) The 4-switch buck-boost has **no passive VIN->VSYS path** with the converter off, and the BATFET body diode blocks SYS->BAT. (4) Charge sense is **R2 in BAT+**, input sense is **R1 in VIN+**, and **PGND/GND are one node (NT1)**. (5) **VINDPM can be set from 3.2 to 19.52 V at runtime** in 64 mV steps, -3 %/+2 % at 18.7 V. (6) **ACOV is at least 26.0 V**, so the charger does not drop out at the 21.4 V clamp. |
| What the documents cannot prove | (a) Warm response τ_warm ≤ 4 ms: no loop-bandwidth or VINDPM transient data exists. (b) Latency from ILIM_HIZ low to converter off, and HIZ-exit time: not specified. (c) Whether VINDPM is re-measured (reset to VBUS_noload - 1.28 V) on HIZ exit or converter re-enable, rather than only at POR. (d) Whether the charger stays healthy when "parked" in VINDPM for minutes with VSYS unloaded: the VSYS_UVP hiccup can latch the converter off after 7 failed restarts in 90 s. (e) The precharge-to-fast-charge hand-off into a battery that sits behind the D-BT-SQ ideal diode. |
| Gating conditions | The hardware permit stage (H1 V-MOT/VBUS comparator, H2 FC-window permit, PERMIT into ILIM_HIZ biased from the charger's VDDA) per [LA] §8. A Teensy hardware watchdog (RTWDOG/WDOG1), recorded as **REQUIRED FUTURE WORK** (operator ruling 5, §11 below). Firmware register discipline: never write EN_LDO = 0, AUTO_WAKEUP_EN = 1, OTG/VAP enables or WDTMR_ADJ = 00b; verify by read-back. The EVM modifications in §9. |

---

## 1. Requirement matrix

| Req | Status | Evidence (primary) | Bench test that closes it |
|---|---|---|---|
| **H1 common ground / sense placement / no unregulated path** | PROVEN_DATASHEET | See §2.1. | Continuity check: J1-PGND, J5-PGND, J6-PGND and TP8/TP31 (PGND) vs TP33 (GND) < 0.1 Ω |
| **H2 hard inhibit while powered** | BENCH_GATE | The mechanisms are proven in the DS (§3). The latency is not specified. | M2: ILIM_HIZ falling to input current < 10 mA, and the HIZ-exit time |
| **H3 fail-safe (reset / hang / I2C dead / POR)** | BENCH_GATE | POR: ChargeCurrent 0 A [DS §9.6.2 p.45]. Watchdog 4-7 s minimum setting [DS §8.6 p.20]. HIZ pin [DS p.6, p.19]. A hung MCU is bounded only by the charger watchdog (4-7 s) unless the hardware permit and a Teensy RTWDOG exist (§4). | M6 (forced Teensy hang: EN < 0.6 V, PERMIT low, I_in -> 0), M2 |
| **H4 input-voltage threshold for always-powered regen** | BENCH_GATE | Register, range, LSB and accuracy are proven [DS §8.5 p.11; §9.6.21 p.79]. 19.0 V and 15.0 V are both reachable. Quiescent draw is typical-only. Warm response is absent from the DS. The VSYS_UVP latch risk while parked is in the DS (§5). | M-R4 (warm step), M-PARK (10 min parked at VINDPM 19 V from a stiff 16 V source), M2 (VINDPM persistence across HIZ) |
| **H5 FC charging from VBUS** | PROVEN_CALC | ChargeCurrent 64 mA LSB to 8.128 A; ±4/3 % at 2.048 A; CV ±0.6 % at 8.4 V; termination is host-only [DS p.10, §9.4.1.2 p.37]. The ≥ 2 A output needs ≥ 1.12 A of charger input, which leaves ≈ 0.1 A margin to the OC_FC 1.4 A latch (§6). | FC-mode bench: 1.0 A IIN_HOST and measure I_fc peak |
| **H6 voltage ratings / OVP** | PROVEN_DATASHEET | VBUS abs max 32 V; recommended 26 V; ACOV rise 26.0/26.8/27.7 V with 100 µs deglitch [DS p.8, p.15-16]. EVM input capacitors are 35 V [UG Table 3-1]. Board C-D8/C-D10 (25 V) must still be changed. | – |
| **H7 battery pin through D-BT-SQ** | BENCH_GATE | LDO precharge (384 mA clamp below VSYS_MIN), 98-102 % transition, CSA common-mode ≥ 2.5 V [DS p.10, p.13, p.15, §9.6.2.1 p.46]. Do **not** bridge D-BT-SQ (§7). | M-D-BT-SQ: cold start into a 0 V VCHG with the pack at 7.4 and 8.4 V; confirm a clean transition to fast charge and no oscillation |
| **H8 inrush / hot-plug** | PROVEN_CALC | EVM VIN node: C53 33 µF Ta + 6 × 10 µF/35 V (C3, C4, C23, C24, C44, C45) + C18 1 µF/3.9 Ω + C25 0.47 µF [UG BOM p.10, Fig 3-7]. About 55-60 µF effective with C53 fitted, about 25 µF after removing C53 (MLCC DC-bias TODO). No ACFET in the IC; EVM P-FET selector Q6/Q7 bypassed by JP1 (§8). | Scope D-BC-FC / D-BC-RG closure onto the EVM: I_peak < 0.5 A |
| **H9 I2C / logic** | PROVEN_DATASHEET | SMBus 7-bit address 0x09; VIL 0.8 V / VIH 2.1 V; pins rated 7 V abs; fSCL 10-400 kHz; tTIMEOUT 25-35 ms [DS p.19-20, §9.5 p.38]. EVM pull-ups R35/R32/R33/R45 go to the EVM 3V3, which is dead when the charger is unpowered, so they must be removed (§9). CHRG_OK is open-drain and reads HIGH when the charger is unpowered. | Unpowered-charger bus idle check (SDA/SCL ≥ 3.0 V with VBUS = 0) |
| **H10 thermal / efficiency / wiring / mechanical** | BENCH_GATE | Efficiency at VIN 15 V and 20 V, VOUT 7.4 V, 2.5 A: about 95 % and 94 % (Fig 8-3/8-4 p.21, read from the plots, 5 mΩ sense). About 1.1-1.3 W loss on an 800 kHz EVM: thermally benign. Light load at 50 mA: about 85 % (Fig 8-6, VIN 12 V). EVM board dimensions are **not in SLUUC74**. It cannot sit in the Ag105 footprint. | Fit / lead-length check plus a 30 min 2.5 A soak with a thermocouple on Q1/Q4/L1 |
| **H11 availability** | UNKNOWN_MISSING_PRIMARY | TI.com list price **US$156.45** for both the BQ25720EVM and BQ25723EVM (`data-price` attribute on www.ti.com/tool/BQ25720EVM and /BQ25723EVM, 2026-11-05). TI inventory is behind a login ("Log in to view inventory"). Mouser and Farnell timed out from this host. | Operator: check TI.com stock (logged in), Mouser and Farnell by hand |
| **H12 telemetry** | PROVEN_DATASHEET | ADCIBAT: ICHG 64 mA LSB; ADCIINCMPIN: IIN 50 mA LSB; ADCVBUS: 96 mV LSB; VSYS/VBAT 64 mV LSB [DS §9.6.7-9.6.10 p.55-58]. **Each channel takes 25 ms at most; continuous mode updates only every 1 s** [DS §9.6.16 p.70]. Fast analog IBAT (8/16 × V_SRP-SRN) and IADPT (20/40 × V_ACP-ACN) pins exist [DS p.6, p.13]. The J-guards G1-G3 use the board's own ADCs, not the charger's. | None for capability. An IBAT-pin ADC channel needs a CSV pin first. |

---

## 2. Evidence by requirement

### 2.1 H1: common ground, sense placement, unregulated paths (PROVEN_DATASHEET)

**Grounds.** Read from [UG] Fig 3-7 p.18:
- J1 pin 1 (input return), J5 pin 1 (battery return) and J6 pin 2 (system return) all connect to PGND.
- PGND and signal GND join at net-tie NT1 next to U1's PGND / thermal pad (pins 27/33).
- There is **no sense element and no switch in any return**. This matches the board, where CHG VIN- = VBAT- = GND (spec §0.3).

**Charge-current sense.** R2 = 0.01 Ω (WSLP1206R0100FEA) sits in **BAT+**, between the BATFET Q5 (AONR21307 P-ch) drain node and the J5-VBAT terminal. SRP/SRN are filtered by R15/R16 10 Ω and C27 0.1 µF ([UG] Fig 3-7, BOM p.10-11). The DS pin text agrees [DS p.7].

**Input-current sense.** R1 = 0.01 Ω in **VIN+** (high side), filtered by R11/R12 4.99 Ω and C46/C47 33 nF, as in DS Fig 10-2 [DS p.85].

**Unregulated paths.**
- **Converter off (HIZ), VIN to VSYS:** in the 4-switch stage Q1 (high side, drain at VIN) blocks VIN->SW1 with its body diode, so no passive VIN->VSYS path exists [DS Table 9-3 p.29 for the switch roles; body-diode orientation from standard N-ch high-side placement].
- **VSYS to BAT:** the BATFET is a P-ch with its source at VSYS. BATDRV is "shorted to VSYS to turn off" [DS p.5]. Its body diode therefore conducts BAT->SYS only ("works as an ideal-diode in supplement mode"), so VSYS cannot push current into BAT with the BATFET off.
- **Small EVM loads hang on VBUS and BAT.** The D2/D3 diode-OR (BAT54H) feeds the U2 LM3480 3.3 V LDO through R38 10 Ω and JP8. Removing JP8 (§9) eliminates the load on BAT (= VCHG).

### 2.2 H6: voltage ratings (PROVEN_DATASHEET)

| Item | Value | Source |
|---|---|---|
| Abs max VBUS, ACP, ACN, SRP, SRN, VSYS | -0.3 to 32 V | [DS §8.1 p.8] |
| Recommended VBUS/ACP/ACN; SRN/SRP/VSYS | 0-26 V; 0-19.2 V | [DS §8.3 p.8] |
| VINPUT_OP | 3.5-26 V | [DS p.9] |
| ACOV rise / fall | 26.0/26.8/27.7 V; 25.0/25.8/26.7 V; 1 V hysteresis; 100 µs rise deglitch; 1 ms fall deglitch | [DS p.15-16] |
| On ACOV | CHRG_OK low, converter disabled; resumes when VBUS < VACOV_FALL for 1 ms. ChargeCurrent **is not** reset by ACOV. | [DS §9.3.22.2 p.35; §9.6.2 p.45] |
| SYSOVP (2S) | 11.7/12/12.2 V, latched; clear by writing 0 to the status bit or by an input power cycle | [DS p.16; §9.3.22.4 p.36] |
| BATOVP | 102.5/104/105 % of ChargeVoltage (≥ 2S) | [DS p.16] |
| EVM VIN capacitors | 35 V (C3, C4, C23-C45, C53); TVS Z1 SMAJ26CA (26 V standoff, 42.1 V clamp per the BOM text) | [UG BOM p.10-11] |

Against the V-MOT envelope:
- **Clamp:** 21.4 V true is 4.6 V below ACOV min 26.0 V. No drop-out mid-burst.
- **Raised VESC cut-off:** at about 24 V [RD] there is still 2.0 V to ACOV min.
- **Abs max:** 32 V gives 10.6 V of headroom above the clamp.
- **TVS limit:** Z1 clamps at 42.1 V, above the 32 V abs max, so it does not protect U1 against a hard V-MOT overshoot.
- **Board work:** C-D8/C-D10 on VCHG-IN are 25 V parts and must become ≥ 35 V (spec §2.2), which is mandatory if the VESC cut-off is raised.

### 2.3 H9: I2C and logic (PROVEN_DATASHEET with modifications)

- **Address:** SMBus target 7-bit 0x09 (0x12 write / 0x13 read) [DS §9.5 p.38]. [UG] p.9 confirms "Tgt Address 12(9)". The Teensy bus carries no other device.
- **BQ25723 alternative:** I2C at 0x6B [DS Table 6-1 p.4; UG p.9 "D6(6B)"]. Its register addresses differ (ChargeOption0 0x00, ChargeCurrent 0x02 [UG §2.4.1 p.9]). **The BQ25723 data sheet is not in the library** (missing primary if that variant is chosen).
- **Logic levels:** SDA/SCL VIL ≤ 0.8 V, VIH ≥ 2.1 V; Schmitt inputs [DS p.19, §9.5]. Abs max 7 V [DS p.8]. Compatible with 3.3 V.
- **Timing:** fSCL 10-400 kHz. tTIMEOUT 25-35 ms means the Teensy must never hold SCL low for 25 ms or more [DS §8.6 p.20].
- **SMBus framing:** read-word / write-word, low byte first [DS Tables 9-7/9-8 p.39].
- **CHRG_OK (for pin 6):**
  - Open-drain, active HIGH = VBUS in range, VBUS > VVBUS_CONVEN and no SYSOVP/SYSUVP/ACOC/TSHUT/BATOVP/BATOC/force-off fault, after a 50 ms deglitch [DS p.6, §9.3.5 p.27].
  - **Hazard:** with the charger unpowered the open drain is off and the pull-up reads HIGH. A single `digitalRead` cannot tell "OK" from "dead". Firmware must AND it with an SMBus ChargerStatus read (STAT_AC, bit 15 of 20h [DS p.49-50]).
  - It indicates input and fault state only, not charging. IN_FCHRG / IN_PCHRG (20h bits 10/9) give the charge state.
- **Back-powering:** the behaviour of the SDA/SCL/CHRG_OK pins with the IC unpowered is not specified in [DS] (UNVERIFIED; bench check in §1).

---

## 3. H2: hard charge inhibit while powered (mechanisms proven, latency bench)

| # | Mechanism | Where | POR default | Scope (stops what) | Response | Needs I2C? |
|---|---|---|---|---|---|---|
| 1 | **ILIM_HIZ pin < 0.4 V -> HIZ** (converter shuts off, REGN stays on, ADC off); exit needs > 0.8 V **and** EN_HIZ = 0 | [DS p.6 pin table; p.19 VHIZ; §9.3.9 p.28] | EVM divider R19 383k (VDDA) / R27 220k gives about 2.2 V (TP22 2.2 V, [UG] p.9), i.e. **not HIZ** | Converter off, so no VIN->VSYS power at all. The BATFET stays ON by default in HIZ (BATFETOFF_HIZ = 0, 32h bit 1 [DS p.66]), but VSYS then has no source except VCHG's own few µF. | **Not specified.** Bench M2 against the ≤ 290 µs budget [LA §4.3] | **No**: level-sensitive, continuously read [DS p.6] |
| 2 | **EN_HIZ** (32h bit 15) | [DS §9.6.13 p.64] | 0 | As #1 | Not specified | Yes |
| 3 | **CHRG_INHIBIT** (12h bit 0) | [DS p.44] | 0 = charge enabled | Charge terminated; the converter keeps regulating VSYS (NVDC) | Not specified | Yes |
| 4 | **ChargeCurrent = 0** (14h) | [DS §9.6.2 p.45] | **0 A** | Fast charge **and** precharge: the precharge current "is set by the ChargeCurrent register and clamped below 384 mA" [DS 12h EN_LDO p.44], so 0 means 0. Also reset by: CELL pin low, STAT_AC invalid, RESET_REG, ChargeVoltage written to 0, watchdog. | One SMBus word write (≈ 0.4 ms at 100 kHz) plus an internal delay that is not specified | Yes |
| 5 | **FORCE_CONV_OFF** (30h bit 3) + independent comparator (CMPIN/CMPOUT) | [DS p.60; CMP_DEG p.60; VINDEP_CMP 1.2/2.3 V ±30 mV p.17] | 0 (disabled) | When CMPOUT goes low the device **latches** into HIZ, CHRG_OK goes low and the charge current is set to zero internally. Exit needs CMPOUT released and the bit cleared. | CMPOUT falling-edge deglitch 5 µs (CMP_DEG = 00b); converter-off delay after it not specified | Must be armed by I2C after **every** POR; then works without I2C |
| 6 | Watchdog expiry -> ChargeCurrent = 0 | [DS §9.3.22.1 p.35; 12h bits 14:13 p.42] | **175 s** (11b) | As #4 | 4-7 s at the minimum setting (01b) [DS p.20] | Set by I2C |
| 7 | Remove input power (RT1987 D-BC-FC / D-BC-RG off) | board | EN pull-downs | Everything: VBUS < UVLO gives POR, and registers reset | RT1987 turn-off (UNVERIFIED in DS-00) plus decay of the node capacitance | No |

**Does it stop all current into the battery pin?**

Yes for #1, #2 and #7: the converter is off, and there is no passive path (§2.1).

For #3, #4 and #6 the converter keeps running and regulates VSYS:
- VSYS = VSYS_MIN (6.6 V for 2S) while VCHG < VSYS_MIN.
- Otherwise VSYS = VBAT + 150 mV with the BATFET off [DS §9.4.1.1 p.37].
- No current reaches BAT through the BATFET body diode (orientation BAT->SYS), so with ICHG = 0 the charge current is zero.
- Supplement (BAT->SYS), OTG and VAP (BAT->VBUS) only take energy from VCHG, which D-BT-SQ isolates from the pack in that direction.
- **Two register states defeat #4 and must never be written:**
  - **EN_LDO = 0** (12h bit 2). "BATFET fully ON. Precharge current is set by battery pack internal resistor. The system is regulated by the MaxChargeVoltage register" [DS p.44]. That is an unregulated charge path into VCHG -> D-BT-SQ -> pack, limited only by the input current limit. POR default is 1.
  - **AUTO_WAKEUP_EN = 1** (30h bit 0). The device "automatically enable[s] 128 mA charging current for 30 mins" with VBAT < VSYS_MIN [DS p.61]. POR default is 0.
  - Firmware must read back 12h and 30h after every configuration and treat a mismatch as a fault.

**Recommended inhibit architecture.** #1 is the primary hard inhibit, driven by PERMIT per [LA] §8, option (b):
- Q2 (NMOS) pulls ILIM_HIZ to GND; its gate is biased from the charger's own VDDA.
- Q1 releases Q2 only while PERMIT = P5 ∧ (H1 ∨ H2) is HIGH.
- A dead Teensy, dead logic or a missing permit therefore means HIZ.

#4 (ICHG = 0) is the POR default and the firmware backstop. #5 is an optional second hardware path: the H1 comparator output into CMPIN with CMP_POL = 1, armed by firmware after each POR. Because it latches, it adds no fail-safety at POR and is an extra layer only.

**H2 timing in words.**
- PERMIT falls; the Q1/Q2 stage has gate delay of order 100 ns.
- ILIM_HIZ crosses 0.4 V. The EVM's C35 is 100 pF on that pin; at the Q2 sink current it discharges in well under 1 µs.
- The device recognises HIZ after an internal deglitch that is **unknown**, then stops switching. Input current then decays to the HIZ quiescent current (also unspecified in [DS]).
- Budget per [LA]: ≤ 290 µs at a 1.5 A input limit. **Gate M2.**

---

## 4. H3: fail-safe cases

| Case | What happens with the BQ25720EVM in the proposed wiring | Evidence |
|---|---|---|
| (a) Teensy in reset / pins high-Z | Pins 30/31 float, and the 10 kΩ EN pull-downs open D-BC-RG and D-BC-FC, so VCHG-IN collapses and the charger is unpowered (POR on return, ChargeCurrent 0 A). The P5 net (47 kΩ pull-down per [LA] §8) drops PERMIT, which pulls ILIM_HIZ low while the charger decays. **No charging.** Pin 5 has no pull resistor on the board today (spec §1), so one must be added. | [DS p.6, p.19, §9.6.2 p.45]; board spec |
| (b) Teensy hung, pins latched in their last state | The charger keeps its last ChargeCurrent until the **charger watchdog**: 4-7 s at the shortest setting (01b; POR default 175 s, 140-210 s) [DS §8.6 p.20, 12h p.42]. That is too slow to be the guard. The bounding layers are: H1 removes PERMIT whenever V-MOT < 1.067 × VBUS, so a hung charger cannot be bus-fed in regen mode; H2 drops it if BT current flows in the FC window; the Teensy **RTWDOG at 100 ms + WDOG1 at 1 s** resets the MCU, after which case (a) applies (REQUIRED FUTURE WORK, §11). | [DS]; [LA] §8, §10 |
| (c) I2C dead or stuck | The SMBus target releases after tTIMEOUT 25-35 ms of SCL low [DS p.20]. Registers keep their values. The charger keeps charging at the last ICHG until its watchdog (4-7 s). The ILIM_HIZ hard inhibit is GPIO/hardware and unaffected. If I2C is dead from POR, ICHG stays 0, so nothing charges. Firmware: 3 consecutive NAKs force P5 LOW and latch a fault. | [DS] |
| (d) Charger POR defaults | Out of reset: ChargeCurrent 0 A; ChargeVoltage = 8.400 V (2S from JP3); VSYS_MIN 6.6 V; VINDPM = VBUS_noload - 1.28 V; IIN_HOST 3.25 A; ILIM_HIZ divider about 3.0 A; WDTMR 175 s; CHRG_INHIBIT 0; EN_LDO 1; AUTO_WAKEUP 0; FORCE_CONV_OFF 0; OTG_VAP_MODE 1 / EN_OTG 0. **The converter does start** and regulates VSYS at 6.6 V, which is below the 7.4 V pack minimum, so even a fully-on BATFET could not push VCHG above the pack and D-BT-SQ cannot conduct. **It does not charge by itself.** | [DS §9.3.1 p.26; Table 9-2 p.28; 12h/14h/15h/30h/32h/3Dh/3Eh/3Fh resets] |

**Pull resistors needed so a dead MCU means no charging:**
- Existing 10 kΩ EN pull-downs on pins 30/31/32 (board).
- 47 kΩ pull-down on the P5 net (pin 5) on the carrier.
- The PERMIT -> ILIM_HIZ inverter stage biased from VDDA ([LA] §8 option b), so that "logic dead, charger alive" gives HIZ.
- JP6 (ILIM_HIZ to GND) stays open; Q2 replaces it.

---

## 5. H4: input-voltage threshold (VINDPM) for the always-powered mode

**Register InputVoltage 3Dh** [DS §9.6.21 p.79]:
- Bits 13:6, 64 mV LSB, fixed 3.2 V offset, range **3.200-19.520 V** (code 0-255).
- Host-writable at any time after POR [DS §9.3.7 p.28].
- POR value: VBUS at no load - 1.28 V, measured "right before the converter is enabled" [DS §9.3.7 p.28].
- RESET_VINDPM (32h bit 13) re-triggers the measurement. RESET_REG does **not** reset VINDPM [DS p.65].

**Accuracy** [DS §8.5 p.11]:

| Setting | Accuracy |
|---|---|
| 18.688 V (0x3C80) | -3 % / +2 % (18.127-19.062 V) |
| 10.880 V | -4 % / +2.5 % |
| 4.480 V | -5.2 % / +5.0 % |

**Settings:**

| Use | Code | Value | Tolerance (accuracy as noted) |
|---|---|---|---|
| Regen | 247 (word 0x3DC0) | 19.008 V | 18.44-19.39 V (18.7 V row) |
| Regen, highest available | 255 | 19.520 V | ≈ 18.93-19.91 V (18.7 V row extrapolated) |
| FC mode | 184 (word 0x2E00) | 14.976 V | 14.38-15.35 V (10.9 V row, -4/+2.5 %) |

**Margins at code 247:**
- Steady bus 16.0 V: +2.4 V minimum.
- Firmware OV 17.5 V and measured overshoot 17.2 V: ≥ 0.94 V.
- TPS61288 OVP minimum 18.3 V: +0.14 V.
- TPS61288 OVP maximum 19.5 V: **not exceeded at any code**, because the register ceiling is 19.52 V. A failed-FB boost (18.3-19.5 V) can therefore sit above VINDPM. Only the H1 comparator protects that case [LA].
- Clamp 21.4 V: 2.0 V below it.

**Draw from a stiff source at or under the threshold.** Not specified as a VINDPM-parked figure. The closest DS data:
- PFM no-load input current 2.2 mA typical (VIN 20 V, 3S, buck) [DS p.12].
- 2.4 mA typical in buck-boost at 12 V [DS p.13].
- No maximum is given.
- The HIZ quiescent with an adapter present is not specified.

**Warm response.**
- The DS gives **no** VINDPM/IINDPM loop bandwidth and no transient figure for a VBUS step across VINDPM.
- The only relevant timing is the charge-current soft start at charge enable: 64 mA steps every 8 µs [DS p.18], about 312 µs to 2.5 A. Whether that ramp re-runs each time VBUS climbs out of VINDPM is not stated.
- Cold start from VBUS application (Fig 10-3 p.90, 2-cell, 40 ms/div, read from the scope trace): VDDA/CHRG_OK about 48 ms after VBUS rises, VSYS about 180 ms after. **Cold-start regen is impossible** (the VESC trips within 19-47 ms [RD]). The always-powered mode is mandatory, as the operator accepted.
- Required: τ_warm ≤ 4 ms (10-90 % ≤ 9 ms) at C_VMOT ≈ 0.97 mF [RD]. **Bench gate M-R4**, run on the EVM before committing.

**Qualification and deglitch restarts on a dip.**
- While VBUS stays above VVBUS_CONVENZ (3.2 V) and below ACOV there is no re-qualification. CHRG_OK's 50 ms deglitch applies only to VBUS entering the 3.5-25.8 V window [DS p.6].
- A dip below the threshold is just regulation.
- **But** if the parking strategy uses HIZ (converter off) between bursts, every exit re-enables the converter. Whether that re-runs the inductance detection (IADPT read "before the converter starts up" [DS §9.3.12 p.29]) and the VBUS no-load VINDPM measurement, which would overwrite the host's 19 V with V-MOT - 1.28 V, is **not stated**. That is gate M2. A bounding note: H1 hysteresis means a reset VINDPM of about 15.8 V is only active while V-MOT > 1.067 × VBUS, so it is bounded, not a loop.

**Parking hazard specific to the BQ25720 (gate M-PARK).**
- Parked with the converter enabled, VINDPM 19 V and V-MOT ≈ 16 V, the VINDPM loop holds input power near zero.
- The DS says that when input power is short "the system voltage starts to drop" [DS §9.3.18 p.32]. With SYS open, VSYS sags at the rate of the EVM's own VSYS leakage.
- If VSYS falls below VSYS_UVP (default 2.4 V) for 2 ms, the device hiccups (500 ms off / 10 ms on) and **latches off after 7 failed restarts in 90 s** [DS §9.3.22.8 p.36-37]. A Run of a few minutes could kill regen capture silently.
- Mitigations, all register-only:
  - VSYS_UVP_ENZ = 1 (12h bit 6, disables UVP).
  - A light VSYS load (e.g. 1-5 mA).
  - Firmware polling of Fault VSYS_UVP (20h bit 3) with a write-0 recovery.
- Measure the actual VSYS decay at the 10 min park first.

**Recommended regen operating point (to be confirmed on the bench):**
- Converter enabled; VINDPM 19.008 V; ChargeCurrent 2.496 A (code 39).
- IIN_HOST about 1.30 A, plus the ILIM_HIZ divider set to about 1.5 A as a hardware ceiling (§9).
- HIZ only as the fault/inhibit path (PERMIT low), not as the between-burst parking state.

---

## 6. H5: FC charging (PROVEN_CALC)

**Path.** VBUS about 15.9 V -> D-BC-FC -> VCHG-IN, with BT_BUS and REGEN off (assertFcChargeEnable). VINDPM 14.976 V (code 184) protects the FC bus: as the FC boost droops toward the threshold, the charge current folds back before UV_BUS (12.0 V).

**Charge current** [DS §9.6.2 p.45; EC p.10]: 64 mA LSB at 10 mΩ RSR (EVM R2 = 10 mΩ, RSNS_RSR = 0 default); range 0-8.128 A; 2.496 A = code 39.

| ICHG point | Accuracy (0-85 °C) |
|---|---|
| 4.096 A | -3/+2 % |
| 2.048 A | -4/+3 % |
| 1.024 A | -5/+6 % |
| 0.512 A | ±12 % |

**CV** [DS p.10]: ±0.6 % at 8.400 V (0-85 °C), i.e. 8.350-8.450 V at VCHG.
- The pack sits 35-50 mV lower because of D-BT-SQ (spec §2.2). This misses the spec's "±0.5 % or better" by 0.1 %.
- Mitigation: set 8.352 V (code 1044, word 0x20A0) for a VCHG window of 8.302-8.402 V and a pack ≤ 8.37 V.
- Always below the firmware 8.5 V OV latch and BQ29200 4.35 V/cell.
- BATOVP trips at 104 % of the setting.

**Termination: host-only.** "Host terminates charge by setting CHRG_INHIBIT bit to 1b, or setting ChargeCurrent() to zero" [DS §9.4.1.2 p.37]. There is no autonomous termination. Firmware implements it: CV reached and ADCIBAT ≤ 1 LSB (64 mA) for N reads, or the IBAT analog pin.

**FC budget.**
- Bus-side FC limit: OC_FC 1.4 A single-sample latch. Aux load 0.10-0.15 A.
- At ≈ 95 % efficiency (Fig 8-3, VIN 15 V, VOUT 7.4 V):
  - 1.0 A input gives 1.0 × 15.9 × 0.95 / 8.4 = **1.80 A** out.
  - ≥ 2.0 A out needs 1.12 A input. That is 1.27 A bus-side with aux, and the IIN_DPM tolerance is ±100 mA (1.4 A row, [DS p.11]). Margin to the 1.4 A latch would be ≈ 0.03 A worst case.
- **Capability PROVEN. Operating point: IIN_HOST 1.00 A (word 0x1400), about 1.8 A charge, unless OC_FC is revisited.**
- IIN_HOST resets to 3.25 A on adapter removal [DS §9.6.23 p.81]. The hardware ILIM_HIZ divider ceiling (about 1.5 A) is the safety net.

---

## 7. H7: battery pin behind D-BT-SQ (BENCH_GATE)

**Battery detection** is by the CELL_BATPRESZ divider only (JP3 3-4 = 2S, 40 % of VDDA) [DS Table 9-2 p.28; UG Table 1-2].
- There is no voltage-based detection. JP4 ("Bat removal", not installed) and J2-4 CELL_control (Q12, R29 300k pull-down) only pull the CELL pin low.
- Keep JP4 off and J2-4 open: a low CELL pin resets ChargeVoltage to the 1S default (4.2 V) and ChargeCurrent to 0 [DS p.5, p.45].

**Start-up sequence in words** (pack 7.4-8.4 V behind D-BT-SQ, VCHG starting about 0 V):
1. The charger POR loads the 2S defaults.
2. The host writes ChargeVoltage, then ChargeCurrent. The DS says ChargeVoltage must be written before ChargeCurrent [DS §9.6.3 p.47].
3. With VSRN < VSYS_MIN (6.6 V) the device is in LDO precharge [DS §9.6.2.1 p.46]:
   - VSYS is regulated at 6.6 V.
   - The BATFET is linear.
   - The current is clamped at 384 mA (≥ 2S, ±15 % at 0x0180 [DS p.10]).
   - At about 0.38 A into about 30-60 µF (EVM BAT capacitors + C-D11 + the recommended 47 µF), VCHG reaches 6.6 V in **about 0.5-1 ms**.
4. **During precharge, VSYS_MIN = 6.6 V is below the pack, so VCHG ≤ 6.6 V and D-BT-SQ cannot conduct.** At VSRN ≥ 98-102 % of VSYS_MIN [DS p.15] the device moves to fast charge (BATFET fully on), VCHG rises to the pack + 35 mV and current flows.
5. Between the transition and D-BT-SQ conduction, VCHG has no battery to stiffen it (only capacitance). The device's view is "battery present, above VSYS_MIN, no current accepted until VCHG > pack". Stability of that hand-off is **not covered by [DS]**. Gate M-D-BT-SQ.

**CSA common-mode** for SRP/SRN is 2.5-19.2 V [DS p.13], so current regulation is undefined below VCHG ≈ 2.5 V. This is covered by the precharge clamp, but it is one more reason for the bench check.

**CV sensing** is at SRN = VCHG, upstream of D-BT-SQ. The pack ends 35-50 mV low (§6).

**[UG] instruction:** "Add a 47-µF capacitor on the BAT pin when testing without a real battery" [UG §2.3 p.6]. Behind D-BT-SQ the EVM effectively has no battery until VCHG passes the pack. **Populate C56 (33 µF 35 V tantalum footprint, DNP) or add 47 µF ≥ 25 V low-ESR at J5.** The DS also asks for ≥ 20 µF after the sense resistor [DS p.86]. C55 + C26 (2 × 10 µF 25 V 1206) alone are below 20 µF effective at 8.4 V (DC bias, TODO(verify: Murata GRM31CR71E106KA12L curve)).

**Do NOT bridge D-BT-SQ.** Bridging would:
- power the IC from the pack ("powers up from the higher voltage of VBUS or VBAT" [DS §9.3.1 p.26]);
- enable the supplement (BAT->SYS), VAP and OTG (BAT->VBUS) paths from a real energy source;
- keep the device alive through every input loss.

With D-BT-SQ in place:
- The charger is unpowered whenever its input is off, so it PORs on every input loss and the registers must be re-written. This is fail-safe, because ICHG = 0.
- Pack-to-VBUS reverse flow through the charger is physically impossible.

---

## 8. H8: inrush and hot-plug (PROVEN_CALC; scope confirmation recommended)

**EVM VIN node** ([UG] BOM p.10-11, Fig 3-7):

| Part(s) | Value | Effective at 16-21 V |
|---|---|---|
| C53 | 33 µF 35 V tantalum (T521D, 65 mΩ) | No DC-bias loss: 33 µF |
| C3, C4, C23, C24, C44, C45 | 6 × 10 µF 35 V X5R 0805 (GRM21BR6YA106KE43L) | ≈ 3-5 µF each, TODO(verify: Murata DC-bias curve) |
| C18 | 1 µF 35 V, in series with R3/R4 3.9 Ω (damping) | – |
| C25 | 0.47 µF (VBUS pin RC, R13 1 Ω) | – |
| C12, C17 | 10 nF + 1 nF (after RAC) | – |
| C42, C43, C54 | DNP | – |
| C2 (47 µF polymer) | DNP; on **VSYS**, not VIN | – |

- **Total effective:** ≈ 52-64 µF with C53; **≈ 20-31 µF with C53 removed**.
- **Board side:** C-D8/C-D10 (2 × 10 µF; replace with 35 V parts).
- **DS minimum:** 4 µF effective for 65 W [DS Table 10-1 p.86]. Removing C53 therefore keeps a large margin.
- **Inrush per the spec's RT1987 figure (≈ 12 mA/µF, spec §6):**
  - With C53: about 0.7-0.9 A.
  - Without C53: about 0.35-0.5 A.
  - In FC mode this adds to the aux load on the FC channel: with C53 removed it stays below the 1.4 A OC_FC latch with margin.
  - In the always-powered mode the node is charged once per Run entry, from V-MOT through D-BC-RG.
  - This is small against the Death-5 node (470 µF + VESC), and it is ramped, not hot-plugged.
- **Input FETs.**
  - The BQ25720 has **no ACFET/RBFET drivers** (pin list [DS p.5-7]).
  - The EVM adds a back-to-back **P-channel** selector Q6/Q7 (DMP3035SFG), driven from CHRG_OK through Q10/Q9 with R9 100k / C22 0.1 µF / R10 10 Ω gate network. JP1 installed (factory) bypasses it [UG Table 1-2].
  - **Keep JP1 installed.** If it were removed, Q6/Q7 would connect the 6 × 10 µF bank only after the 50 ms CHRG_OK deglitch, through an RC-softened gate whose slew is not documented: an uncontrolled second hot-plug.
- **VSYS start-up** (7 × 10 µF + C49/C48 2 × 33 µF tantalum ≈ 100 µF): charged by the converter under its own input current limit (IIN_HOST / ILIM_HIZ), not from V-MOT directly. Bounded by the ≈ 1.5 A ILIM divider ceiling (§9).
- **Mode transitions** (REGEN -> FC, after REGEN off and before D-BC-FC conducts, RT1987 t_d,on 8 ms): the VBUS node drops by about I_q × 8 ms / C ≈ 2.2 mA × 8 ms / 25 µF ≈ 0.7 V. That is far above UVLO, so there is no POR, provided the sequencer has PERMIT low (HIZ) during the swap [LA §7].

---

## 9. EVM modifications (designators from [UG] Fig 3-7 / Table 3-1)

| # | Modification | Reason |
|---|---|---|
| 1 | **Keep JP1 installed** (bypass Q6/Q7) | No CHRG_OK-delayed hot-plug; the RT1987s do the switching (§8) |
| 2 | **Remove C53** (33 µF tantalum on VIN) | Inrush on the RT1987-ramped node (§8) |
| 3 | **JP2 installed** (OTG/VAP/FRS pin to GND = forward mode; factory default) | OTG/VAP cannot be pin-enabled; firmware also keeps EN_OTG = 0 / OTG_VAP_MODE = 1 |
| 4 | **JP3 on 3-4 (2S)**; **JP4 open**; J2-4 CELL_control open | 2S defaults; no spurious battery-removal |
| 5 | **JP6 open.** Wire the PERMIT inverter stage (Q2 NMOS drain to J2-1/TP22 ILIM_HIZ, gate biased from VDDA/TP19, Q1 controlled by PERMIT) per [LA] §8 option (b) | Hardware HIZ inhibit, fail-safe |
| 6 | **Change R27 220k -> 140k** (with R19 383k): V_ILIM = 6 V × 140/523 ≈ 1.61 V -> I_DPM = (1.61 - 1)/(40 × 0.01) ≈ **1.5 A** (accuracy at 1.6 V: 1.3-1.7 A [DS p.11]). Keep EN_EXTILIM = 1 (POR default). | Resistor-set hardware input-current ceiling independent of I2C ([LA] §8 C-requirement). REGN/VDDA = 5.7-6.3 V [DS p.12]; the ceiling therefore carries about ±5 % of VDDA error, a TODO(calibrate) to measure TP22. |
| 7 | **Remove JP8** (EVM LDO U2 off). **Remove R35, R32** (SDA/SCL 10k pull-ups to EVM 3V3) and **R33** (CHG_OK pull-up). R45 also goes to EVM 3V3; trace its net on the PCB and remove it if it is a bus pull-up (UNVERIFIED from the schematic crop). | With the charger unpowered the EVM 3V3 is dead, and pull-ups to it would load the board bus (RSDA/RSCL 10k to Teensy 3V3). The board already has the bus pull-ups. |
| 8 | CHG_OK (J2-2/TP28) to Teensy pin 6 through 1 kΩ, with a 10 kΩ pull-up to Teensy 3V3 on the carrier | Pin 6 input. Firmware must AND it with STAT_AC (§2.3). |
| 9 | Populate **C56** (33 µF 35 V tantalum) or add 47 µF at J5 | [UG] p.6 note; [DS] ≥ 20 µF after RSR (§7) |
| 10 | Leave J6 VSYS open, or add a 1-5 mA bleed if M-PARK shows VSYS decay toward UVP | §5 parking hazard |
| 11 | Leave J4 CMPIN with R7 300k to GND, unless the optional FORCE_CONV_OFF second path is wired (H1 output into CMPIN, CMP_POL = 1) | §3 #5 |
| 12 | Board side: C-D8/C-D10 -> ≥ 35 V parts | §2.2 |
| 13 | Wiring: J1 VIN/PGND -> CHG pads VIN+/VIN- (≤ 1.5 A); J5 VBAT/PGND -> VBAT+/VBAT- pads (2.5 A, both pad pairs); twisted pairs as short as possible | The EVM's own ceramic input caps sit at the EVM end, as the DS layout wants [DS p.86] |

---

## 10. Register map excerpts (SMBus 0x09, word access, low byte first)

| Reg | Name | POR | Fields used | Proposed value |
|---|---|---|---|---|
| 12h | ChargeOption0 [p.42-44] | E70Eh | b15 EN_LWPWR (1); b14:13 WDTMR_ADJ (11 = 175 s; 01 = 5 s, 4-7 s); b6 VSYS_UVP_ENZ (0); b3 IBAT_GAIN; b2 **EN_LDO (1, never 0)**; b1 EN_IIN_DPM (1); b0 **CHRG_INHIBIT** (0) | **0xA70E** (WDT 5 s; low-power off is irrelevant with an adapter present; keep EN_LDO = 1) plus VSYS_UVP_ENZ per M-PARK. Read back. |
| 14h | ChargeCurrent [p.45-46] | 0000h (0 A) | b12:6, 64 mA LSB @ 10 mΩ | 2.496 A = code 39 = **0x09C0**; 0 to stop |
| 15h | ChargeVoltage [p.47-48] | 2S: 8400 mV | b14:3, 8 mV LSB, 1.024-19.2 V; writing 0 forces ICHG = 0 | 8.352 V = code 1044 = **0x20A0** (or 8.400 V = 0x20D0) |
| 20h | ChargerStatus [p.49-50] | 0000h | b15 STAT_AC; b12 IN_VINDPM; b11 IN_IIN_DPM; b10 IN_FCHRG; b9 IN_PCHRG; b7 ACOV; b5 ACOC; b4 SYSOVP (W0 clears); b3 VSYS_UVP (W0 clears); b2 Force_Converter_Off | Poll at 50 Hz |
| 23h-26h | ADC results [p.55-58] | – | VBUS 96 mV; ICHG 64 mA / IDCHG 256 mA; IIN 50 mA; VSYS/VBAT 64 mV | Telemetry ≤ 1 Hz (continuous) |
| 30h | ChargeOption1 [p.59-61] | 3300h | b11 RSNS_RAC / b10 RSNS_RSR (0 = 10 mΩ, matches R1/R2); b7:4 CMP settings; b3 **FORCE_CONV_OFF**; b0 **AUTO_WAKEUP_EN (never 1)** | 0x3300, or 0x3348 if the CMPIN path is used (CMP_POL = 1, FORCE_CONV_OFF = 1) |
| 31h | ChargeOption2 [p.62-63] | 00B7h | b7 EN_EXTILIM (1 = ILIM pin active); b3 EN_ACOC | Keep 00B7h (ILIM pin ceiling active) |
| 32h | ChargeOption3 [p.64-66] | 0434h | b15 **EN_HIZ**; b14 RESET_REG; b13 RESET_VINDPM; b12 EN_OTG (0); b5 OTG_VAP_MODE (1); b1 BATFETOFF_HIZ | Keep EN_OTG = 0, OTG_VAP_MODE = 1 |
| 35h | ADCOption [p.70-71] | 2000h | b15 ADC_CONV; b14 ADC_START; b6/b4/b2/b0 VBUS/IIN/ICHG/VBAT | 0xE055 (continuous; VBUS, IIN, ICHG, VBAT) |
| 36h | ChargeOption4 [p.72] | 0048h | b15:13 VSYS_UVP threshold; b10 VSYS_UVP_NO_HICCUP | Per M-PARK |
| 3Dh | InputVoltage [p.79] | VBUS_noload - 1.28 V | b13:6, 64 mV LSB, +3.2 V offset | Regen **0x3DC0** (19.008 V); FC **0x2E00** (14.976 V) |
| 3Eh | VSYS_MIN [p.80] | 2S: 6.6 V | b15:8, 100 mV LSB | Keep 6.6 V (below the pack minimum by design) |
| 3Fh | IIN_HOST [p.81] | 4100h (3.25 A) | b14:8, 50 mA LSB; reset on adapter removal | Regen 1.30 A = **0x1A00**; FC 1.00 A = **0x1400** |
| FEh / FFh | IDs [p.82-83] | 0040h / 00E1h | – | Verify after every POR before any write |

**Firmware configuration order after every charger POR** (detected by STAT_AC 0->1 or a ManufacturerID read-back):
1. Verify the IDs.
2. 12h: WDT 5 s, EN_LDO 1.
3. 30h, 31h, 32h, 36h.
4. 15h ChargeVoltage.
5. 3Dh VINDPM for the mode.
6. 3Fh IIN_HOST.
7. 35h ADC.
8. Read back everything.
9. Only then 14h ChargeCurrent.
10. Only then release P5.

Feed the charger watchdog with a 15h or 14h write every ≤ 2 s.

---

## 11. Required future work recorded (operator ruling 5): MCU hardware watchdog

If Path A is pursued, the Teensy 4.1 must gain a hardware watchdog. The design is from [LA] §10:
- RTWDOG primary at 100 ms; WDOG1 at 1.0 s as an independent second timer; WDOG1 output never routed to pin 19 (SCL).
- After a WDT reset, firmware latches `ERR_MCU_WDT` and requires acknowledgement before Run.

Why the BQ25720 needs it:
- The charger's own watchdog bottoms out at 4-7 s [DS p.20].
- A hung Teensy with pins latched would otherwise leave the charger running at its last ChargeCurrent for up to 7 s, bounded only by the H1/H2 hardware permit.

Bench proof (M6): a forced hang resets within the timeout, every EN falls below 0.6 V, PERMIT goes LOW (so ILIM_HIZ < 0.4 V) and the charger input current falls to quiescent.

Missing primaries for it: the NXP i.MX RT1060 Reference Manual and PJRC pad state at reset [LA].

---

## 12. Round-1 corrections (dossier_TI_BQ25720...md)

1. **Primary access:** round 1 had no PDF. All values below are now read from SLUSDU3/SLUUC74.
2. **Recommended VBUS max:** 26 V is now **verified for the BQ25720** [DS §8.3 p.8]; round 1 had it only from a sibling. SRN/SRP/VSYS recommended max is 19.2 V.
3. **ACOV:** round 1 said "26 V, E2E only". Primary values: rise **26.0/26.8/27.7 V**, fall 25.0/25.8/26.7 V, 100 µs / 1 ms deglitch [DS p.15-16]. CHRG_OK goes low above 26.8 V typ, not at the 25.8 V "upper edge" round 1 used for headroom. Headroom from the clamp to ACOV min is 4.6 V.
4. **VINDPM accuracy:** round 1 had it UNVERIFIED. It is -3/+2 % at 18.688 V and -4/+2.5 % at 10.88 V [DS p.11]. 19.008 V therefore means 18.44-19.39 V.
5. **CHRG_INHIBIT** is confirmed at 12h bit 0, POR 0 [DS p.44]; round 1 had the bit position from the sibling.
6. **ILIM_HIZ** thresholds 0.4/0.8 V are confirmed for the BQ25720 [DS p.19].
   - **Correction:** the BQ25720EVM has **no ILIM_control inverter and no "pre-bias jumper" to remove**. ILIM_HIZ is a plain divider (R19 383k from VDDA, R27 220k, C35 100 pF) with JP6 to GND for HIZ, brought out on J2-1 [UG Fig 3-7, Table 1-1/1-2].
   - Round 1's "drive 3.3 V for enable" would set I_DPM ≈ 5.75 A. A divider-set ceiling is needed (§9 #6).
7. **Watchdog:** 01b = 5 s **(4-7 s)**, 10b = 88 s, 11b = 175 s (140-210 s) is now verified [DS p.20, p.42].
8. **CV accuracy** is **±0.6 % at 8.4 V** (0-85 °C), not the sibling's ±0.5 % [DS p.10]. That misses the spec's ±0.5 % by 0.1 %; mitigated by an 8.352 V setting.
9. **VSYS_MIN:** the POR default for 2S is **6.6 V** [DS p.80, Table 9-2], so round 1's "must be written below 7.4 V" needs no write. 6.6 V below the pack is also what keeps POR-state VCHG from reaching the pack.
10. **Precharge clamp** of 384 mA (≥ 2S, below VSYS_MIN) is verified [DS p.10, §9.6.2.1 p.46].
11. **Start-up latency:** round 1 used the sibling's "150 ms converter power-up". The BQ25720 primary gives register reset at +5 ms and access at +10 ms [DS §9.3.1 p.26], CHRG_OK after a 50 ms deglitch, and on Fig 10-3 (p.90) VSYS up about 180 ms after VBUS (scope read). Charge-current soft start is 64 mA / 8 µs [DS p.18].
12. **Input selector:** round 1 said "N-channel MOSFET selector". The EVM input selector is **P-channel** Q6/Q7 (DMP3035SFG-7), CHRG_OK-driven through Q10/Q9 and bypassed by JP1 (installed) [UG BOM, Table 1-2]. The IC itself has no ACFET/RBFET drivers.
13. **EVM input capacitance:** round 1 guessed "ceramics + bulk electrolytic/polymer footprint". Actual: 6 × 10 µF 35 V 0805 + **C53 33 µF tantalum (fitted)** + C18 1 µF snubber. The C2 47 µF polymer footprint is DNP and on **VSYS** [UG BOM p.10-11, Fig 3-7].
14. **EVM 3V3:** round 1 said "fed from VDDA/VIN side". It is the U2 LM3480 LDO, fed through R38 10 Ω and JP8 from a **D2 (BAT) / D3 (VBUS) BAT54H diode-OR** [UG Fig 3-7]. The pull-up designators are now known (R35, R32, R33, R45, R39).
15. **JP4:** round 1 asked to check that the "battery-removal jumper JP4 is in BAT+, not BAT-". JP4 is not in the power path; it pulls the CELL_BATPRESZ pin low to signal battery removal [UG Table 1-2, Fig 3-7]. The battery path is Q5 -> R2 -> J5.
16. **Common ground:** round 1 had it UNVERIFIED. It is now PROVEN: J1/J5/J6 returns are all PGND; PGND-GND join at NT1; RSR (R2) in BAT+; RAC (R1) in VIN+.
17. **Address/protocol:** 0x09 is confirmed. The BQ25723 is I2C at 0x6B with ChargeCurrent at 0x02/0x03 (the [UG] p.9 procedure writes 0x02) — round 1's "03/02h" is consistent. The BQ25723 data sheet itself is still unread (missing primary).
18. **New hazards round 1 missed:**
    - EN_LDO = 0 (unregulated precharge through a fully-on BATFET).
    - AUTO_WAKEUP_EN = 1 (autonomous 128 mA for 30 min).
    - The VSYS_UVP 7-strike latch when parked in VINDPM.
    - The FORCE_CONV_OFF latching comparator path, which is an available second inhibit.
    - CHRG_OK reads HIGH when the charger is unpowered.
19. **ADC rate (new):** 25 ms maximum per channel; continuous mode refreshes every 1 s [DS p.70]. ICHG has 64 mA steps.
20. **Pricing:** round 1 quoted DigiKey (£138.01 UK etc., undated). The TI.com list price is **US$156.45** (2026-11-05). Stock was not obtainable (§1 H11).
21. **Regen verdict:** round 1 scored regen as a cold-start showstopper and gave "5/10". Under operator ruling 3 (always powered) cold start no longer applies. The open question becomes τ_warm and parked-mode behaviour (M-R4, M-PARK, M2). Round 1's "tail-only capture" framing is void (operator ruling 1).
22. **Round 1 said the EVM pull-ups "can clamp the bus through the dead LDO".** That still holds. The fix is to remove R35/R32 (and JP8), not to feed EVM 3V3 from the Teensy: feeding it would back-drive the U2 output (LM3480 reverse behaviour UNVERIFIED).

---

## 13. Bench gates specific to this part (in order)

| Gate | Test | Pass criterion |
|---|---|---|
| M-R3 (board, before purchase) | CV-mode electronic load at 19 V / 1.3 A on V-MOT | Braking continues with V-MOT held at 19 V; otherwise any charger captures only ≈ 20 mC per decel [RD] |
| M-R4 | Warm step on the EVM: parked at VINDPM 19.008 V, ICHG 2.5 A, VIN stepped from 18.5 V to 20 V from a stiff source, with 8.0 V CV load + 47 µF on J5 | τ_warm ≤ 4 ms (10-90 % ≤ 9 ms) |
| M-PARK | 10 min parked at 16 V with VINDPM 19 V, converter enabled | No Fault VSYS_UVP; input draw ≤ 5 mA; VINDPM register unchanged |
| M2 | ILIM_HIZ step to < 0.4 V while charging at 1.5 A input | Input < 10 mA within ≤ 290 µs. HIZ exit: time to regulate, and whether 3Dh is overwritten (read before/after). Input brown-out to 3 V and back: re-config detected |
| M-D-BT-SQ | Cold start into VCHG ≈ 0 V behind an RT1987 ideal diode, pack 7.4 V and 8.4 V | Clean precharge-to-fast transition, no relaxation oscillation, CV 8.35 V ± 0.6 % at VCHG |
| M6 | Forced Teensy hang (RTWDOG) | EN < 0.6 V, PERMIT LOW, ILIM_HIZ < 0.4 V, I_in -> quiescent |
| Inrush | Scope D-BC-FC closure onto the EVM (C53 removed) | I_peak < 0.5 A; no OC_FC latch |

---

## 14. Missing primaries (operator to fetch)

- **BQ25723 data sheet** (TI SLUSE?? — literature number unknown here). Needed only if the I2C variant / BQ25723EVM is chosen.
- **BQ25720 transient data:** VINDPM loop bandwidth, warm response, ILIM_HIZ -> converter-off latency, HIZ exit time, whether VINDPM is re-measured on HIZ exit. These are absent from SLUSDU3; a TI E2E or application note might hold them. Otherwise M2/M-R4.
- **HIZ-mode input quiescent with an adapter present:** not specified in SLUSDU3.
- **BQ25720EVM board dimensions / mechanical drawing:** not in SLUUC74.
- **Murata GRM21BR6YA106KE43L and GRM31CR71E106KA12L DC-bias curves:** effective EVM VIN/BAT capacitance.
- **Distributor stock and lead time:** Mouser and Farnell timed out from this host; TI.com inventory needs a login.
- **SMAJ26CA (Littelfuse) data sheet:** breakdown voltage vs the V-MOT envelope.
- **I/O behaviour of SDA/SCL/CHRG_OK with the IC unpowered** (back-power): not specified.
- Inherited from [LA]/[RD]: the i.MX RT1060 RM (watchdog), PJRC reset pad states, RT1987 turn-off delay, VESC Six EDU input capacitance and l_max_vin behaviour.
