# Round-2 dossier: TI BQ25773 on the BQ25773EVM (I2C variant), Path A replacement for the Ag105 (board rev 20260622)

Date: 2026-11-05. This supersedes the round-1 dossier
`docs/reviews/charger_eval_2026-11-05/dossier_TI_BQ25773___BQ25770G__NVDC_buck_boost_charge_controller_.md`
for this part. It is written against the 2026-11-05 operator rulings:
- regen harvesting and FC charging are both hard requirements;
- Path A must be shown fully feasible;
- R3 is replaced by "no circular loop, no runaway or unregulated charge current";
- the always-powered charger architecture is accepted;
- an MCU hardware watchdog is required future work.

## 0. Sources and evidence rules

Every number below comes from one of these primaries, read on 2026-11-05. The PDFs and pdftotext copies are in
`scratchpad/charger_eval/datasheets/`. Per-page text and the schematic renders are in `r2/bq773/`:
`BQ25773_ds.pg.txt`, `BQ25773EVM_ug_SLUUCY2.pg.txt`, the 600 dpi schematic tiles `t00-t22.png`, and the efficiency plots
`eff-022.png`.

| Tag | Document | How it was read |
|---|---|---|
| **[DS]** | TI **SLUSEK7**, *BQ25773 40V, I2C, 2- to 5-Cell, Narrow VDC Quasi Dual Phase Buck-Boost Battery Charge Controller*, September 2024, 144 pp. | Read in full. pp.1-56 (features, pins, abs max, EC, timing, detailed description), the register map pp.57-122 for every field cited, and the application section pp.123-131. Cited as "DS p.N" (PDF page = printed page) plus section, table or figure |
| **[UG]** | TI **SLUUCY2**, *BQ2577x Evaluation Module User's Guide* (BQ25770EVM/BQ25773EVM), November 2023, 25 pp. | Table 1-1 (p.2), Table 2-1 I/O (p.3), Table 2-2 jumpers (p.4), procedure (pp.5-9), Figure 3-1 schematic (p.10, read from 600 dpi renders), Table 3-1 BOM (pp.15-18) |
| **[TIstore]** | ti.com, fetched with plain curl 2026-11-05 17:38 UTC | `https://www.ti.com/tool/BQ25773EVM` (`data-price`) and `https://www.ti.com/storeservices/cart/opninventory?opn=…` |

Board and cross-cutting facts come from:
- the task brief;
- `docs/reviews/charger_eval_2026-11-05/spec.md` **[SPEC]** (inrush: RT1987 slew 12.0 V/ms, i.e. 12 mA/µF, spec §6);
- `r2/loop_analysis.md` **[LOOP]** (comparator H1, FC permit H2, inhibit stage H3, bench gates M1-M8, watchdog §10);
- `r2/regen_dynamics.md` **[REGEN]** (τ_warm requirement, VESC cut-off, M-R0..M-R4).

Nothing is filled in from recollection. Values not in a primary are marked **UNKNOWN** or **BENCH**.

## 1. Verdict

**FEASIBLE_WITH_CONDITIONS.** No hard requirement fails on the primaries.

This is the first I2C candidate whose input-voltage threshold can be placed **above the TPS61288 HW-OVP maximum (19.5 V)** and
still below the 21.4 V clamp. VINDPM goes up to 27.0 V in 20 mV steps, ±1 % at 18 V (DS p.12, p.66). The BQ25713 and BQ25720
stop at 19.52 V.

Proven from the documents:

| Item | Source |
|---|---|
| Common ground: one PGND, signal GND joined by net-tie NT1; RAC_A/RAC_B and RSR are high-side | UG Fig 3-1 p.10 |
| A **hardware** converter-off pin: ILIM_HIZ < 0.4 V = HIZ | DS p.6, p.20, §7.3.14 p.40 |
| A **µs-class hardware** converter-off path: independent comparator + FRC_CONV_OFF, 1 µs deglitch | DS §7.3.4 p.30, REG0x30 p.96 |
| No charging out of POR: CHARGE_CURRENT = 0 mA, EN_AUTO_CHG = 0, no non-volatile memory | DS Table 7-2 p.31, p.63, p.77 |
| Host watchdog settable to 5 s (4-7 s) | DS p.21, REG0x01 p.61 |
| OTG/VAP/FRS physically locked out by holding the EN_OTG pin LOW | DS Table 7-5 p.37-38 |
| 2S CV 8.4 V at -0.5/+0.6 % | DS p.10 |
| Charge current to 16.32 A in 8 mA steps; ±5 % at 2048 mA | DS p.11, p.63 |
| 45 V abs max on VBUS/ACP/ACN; ACOV 33 V by default | DS p.8, p.17, p.76 |
| I2C ADCs for VBUS / IIN / IBAT / VBAT / VSYS | DS p.15, pp.80-93 |
| TI store: $199, 95 EVMs in stock | TIstore |

What keeps it from "proven":

1. **Regen capture is decided by timing facts the datasheet does not give** (BENCH M2/M4 of [LOOP]/[REGEN]):
   - the HIZ / force-converter-off **exit** latency, which in the comparator-gated design is the capture latency for every burst;
   - the VINDPM-loop / soft-start warm response, required τ_warm ≤ 4 ms on the unmodified board ([REGEN]).

   Unlike the BQ25713, the BQ25773 POR VINDPM is a fixed 3.2 V. It re-measures VBUS only on host request (DETECT_VINDPM, DS
   §7.3.12 p.39) or at power-up (DS §7.3.1 p.27). Nothing in DS says an HIZ exit overwrites a host-written VINDPM. Retention
   across an HIZ cycle is still a 1-minute bench read-back (B3).
2. **The stock EVM breaks three board rules and needs mods (§6):**
   - **JP4 ships in the 4S position.** The POR CHARGE_VOLTAGE would then be 16.8 V and SYSOVP 22 V (DS Table 7-6 p.39, UG
     Table 2-2 p.4).
   - **Input capacitance is 167.6 µF nominal**, including two 33 µF tantalum-polymer capacitors that do not derate. The predicted
     inrush is 2.25 A against the 1.4 A OC_FC single-sample latch and the RT1987 2.5 A start-up SCP.
   - **The I2C, CHRG_OK and EN_OTG pull-ups go to an EVM 3.3 V LDO** (U2 TPS7A1633), which is fed from VBAT and VIN through
     D3/D4.
3. **A cold start takes ~226 ms** (converter powers up 226 ms after VBUS > VVBUS_CONVEN, DS §7.3.1 p.27). Regen therefore
   **requires** the operator-accepted always-powered architecture (REGEN closed through Run). A cold-started charger captures
   no regen burst.
4. **The FC-window bus budget.** 2 A at 8.4 V draws about 1.11 A from the 15.9 V bus (§3, H5). With about 0.15 A of aux load
   this approaches the 1.4 A single-sample OC_FC latch. This is a board limit, not a charger limit, but it caps the usable
   FC-mode charge current at about 1.6-2.0 A unless OC_FC is revisited.
5. **Board-side regen gate.** The VESC stops regenerating at about 21.35 V within 19-47 ms ([REGEN]). M-R0/M-R3 must confirm the
   mechanism before any charger can be scored on regen.
6. **MCU hardware watchdog (operator ruling 5): REQUIRED FUTURE WORK** if this path is pursued. RTWDOG primary at 100 ms plus
   WDOG1 at 1.0 s, per [LOOP] §10. The charger's own watchdog (4-7 s) is a second-tier backstop, not a substitute. The firmware
   has no MCU watchdog today.

## 2. Requirement matrix

Status codes: PD = PROVEN_DATASHEET, PC = PROVEN_CALC, BG = BENCH_GATE, F = FAIL, U = UNKNOWN_MISSING_PRIMARY.

### H1: common ground, high-side sensing, no unregulated path. Status: PD

**Ground:**
- J1-PGND (input -), J2-PGND (VSYS -) and J3-PGND (VBAT -) are one **PGND** net.
- Signal **GND** (ACP/ACN filter caps C72-C75, CMPOUT/CELL dividers, J6/J8 GND) joins PGND only at net-tie **NT1**, beside U1
  pin 37 / the thermal pad. Test points TP18/19/21/36/49/50 are on PGND; TP52/TP61 are on GND.
- Source: UG Fig 3-1 p.10, tiles t00, t11, t12.

**Sensing:**
- Input current is sensed by **RAC_A and RAC_B (10 mΩ each)** in series with VIN_SW → VIN_R_A/B, high-side.
- Charge current is sensed by **RSR (5 mΩ, CSNL2010)** between VBAT_R (source of BATFET Q5) and VBAT/J3, high-side in BAT+.
- No sense element or switch is in any return.
- Source: UG Fig 3-1; BOM p.17.

**Every non-converter path on the EVM:**

| Path | Direction | Bound |
|---|---|---|
| (a) Q5 (CSD18501Q5A, N-ch) body diode, source on the VBAT_R side | BAT→SYS only | DS pin table p.7 (BATDRV "5 V above SRP"); UG t11 |
| (b) Q9 (SI7489DP P-ch input FET), bypassed by JP6 (installed, factory) | VIN→VIN_SW | UG Table 2-2 p.4 |
| (c) D3/D4 diode-OR from VBAT and VIN into the U2 3V3 LDO via R47 10 Ω | LDO draw, a few mA | UG t21. On this board VBAT = VCHG behind D-BT-SQ, so it cannot draw from the pack |

**On this board:** EVM VIN+ → VCHG-IN, PGND → GND, J3 VBAT → VCHG, J3 PGND → GND. That is Ag105 VIN- = VBAT- = GND, the
same topology the operator confirmed for the board.

### H2: hard charge inhibit while powered. Status: PD for the mechanisms; latency is BG (row H2b)

| Mechanism | How | Default after POR | Stops |
|---|---|---|---|
| **ILIM_HIZ pin** (hardware) | < 0.4 V min (VHIZ_HIGH 0.4/0.5 V) enters HIZ; exit needs > 0.8 V max **and** EN_HIZ = 0 | Set by the EVM divider R15 200 k (REGNA) / R16 300 k = 3.0 V → **not** HIZ (UG p.8 step 6) | Converter off: "converter shuts off and BATFET is turned on to supplement system from battery" (DS §7.3.14 p.40). BATFET on is BAT↔SYS only; no source exists, so no current into BAT. Optional BATFETOFF_HIZ = 1 also turns Q5 off (REG0x34 b1 p.103) |
| **EN_HIZ** (REG0x35 b7) | I2C | 0 | Same as above |
| **FRC_CONV_OFF + independent comparator** (hardware, needs config) | CMPOUT low → Q1 and Q4 off, CHRG_OK low; auto-resume when CMPOUT returns high. Needs FRC_CONV_OFF = 1 (REG0x30 b3, default 0) and CMP_EN = 1 (REG0x34 b2, default 1). Falling-edge deglitch CMP_DEG = 00b → **1 µs** (REG0x30 b5-4 p.96) | **Disabled** (FRC_CONV_OFF = 0) | Converter off. DS §7.3.4 p.30 |
| **CHRG_INHIBIT** (REG0x00 b0) | I2C | 0 (charge enabled) | "When this bit is 0, battery charging will start with valid values" (p.60). 1 = inhibit |
| **CHARGE_CURRENT = 0** (REG0x02/03) | I2C | **0 mA** (p.63) | Fast charge. Pre-charge and trickle use the **lower** of CHARGE_CURRENT and IPRECHG / IBAT_SHORT when EN_LDO = 1, so 0 stops them too (DS §7.3.5.2 p.31). With EN_LDO = 0, CHARGE_CURRENT is the only limit (same page) |
| **CHARGE_VOLTAGE written 0** | I2C | – | Resets CHARGE_CURRENT to 0 (p.64) |
| **BATCOC** | Hardware, 1 µs deglitch | REG0x15 b2-1 reset = 3h (100 mV = 20 A at 5 mΩ, p.75). DS §7.3.26.6 p.48 says "disabled by default (00b)". **DS internal inconsistency** | Resets CHARGE_CURRENT and turns BATFET off. At 5 mΩ it is useless as a backstop at this power level |

**Does an inhibit stop ALL current into the battery pin?**
- With charge disabled, the BATFET is off. VSYS is regulated at VSYS_MIN (VBAT < VSYS_MIN) or VBAT + 150/160 mV (DS §7.4.1.1 p.51;
  REG0x00 EN_LDO text p.59).
- The N-FET body diode conducts BAT→SYS only.
- Supplement mode (BATFET as ideal diode) is BAT→SYS. On this board BAT = VCHG behind D-BT-SQ, so it can only drain the ~30 µF
  of VCHG, never the pack.
- In HIZ the BATFET is on (default) while the converter is off. The VSYS caps (about 156 µF, §6) can dump at most C × 0.15 V ≈
  23 µC into VCHG. Negligible.

**Paths an inhibit does NOT cover; all are host-only enables, default off:**
- **PTM**: EN_PTM REG0x30 b2, default 0. Q1 and Q4 both on, input passed straight to SYS (DS §7.4.3 p.52), "flash charge" with
  a PPS adapter. With BATFET on, the charge current is then set by the source impedance, not by the charger. **Firmware must never
  write EN_PTM = 1**; read it back as 0 on every config cycle.
- **OTG / VAP / FRS**: these need the EN_OTG **pin** HIGH (Table 7-5 p.37-38). EVM JP2 installed grounds EN_OTG (UG Table 2-2;
  t12/t11). Keep JP2 installed and remove R44 (10 k from EN_OTG to EVM 3V3) so a lost jumper cannot float it high.
- **Learn mode**: EN_LEARN, default 0.

### H2b: inhibit latency vs [LOOP] M2 (≤ 290 µs at 1.5 A input). Status: BG

- FRC_CONV_OFF: 1 µs deglitch, then "turns off Q1 and Q4". The propagation after the deglitch is not given.
- ILIM_HIZ entry latency: not given.
- I2C CHRG_INHIBIT: one write, about 0.3 ms at 100 kHz, plus an unspecified internal response. Too slow to rely on.

**Bench B2:**
- Step the inhibit (ILIM_HIZ pulled low by H3, and separately CMPIN_TR via FRC_CONV_OFF).
- Measure the time for input current to fall below 10 mA at IINDPM = 1.5 A.
- Pass: ≤ 290 µs.
- Recommended wiring: drive **both**. ILIM_HIZ is the cold, POR-valid fail-safe. FRC_CONV_OFF is the fast path once configured.

### H3: fail-safe. Status: PD with the §6 EVM mods (as shipped, (a) relies on charge-current defaults only)

**(a) Teensy in reset / pins high-Z:**
- The RT1987 EN 10 k pull-downs open D-BC-FC and D-BC-RG, so the charger is unpowered. With D-BT-SQ blocking, the device POR's
  ("When VBAT < VBAT_UVLO: if VBUS falls below VBUS_UVLO then device is off without I2C communication", DS §7.3.1 p.27).
- Independently, mod H3/§6 makes ILIM_HIZ LOW unless the permit is actively HIGH:
  - Q2 holds the pin low, biased from the charger's own REGN_A;
  - Q1 releases it only on PERMIT ([LOOP] §9 H3(b)).
- As shipped, ILIM_HIZ = 3.0 V (enabled), but CHARGE_CURRENT = 0 at POR means no charging anyway.

**(b) Teensy hung, pins latched (REGEN / FC_CHARGE / permit HIGH, last CHARGE_CURRENT non-zero):**
- The charger watchdog resets CHARGE_CURRENT to 0 A, re-enables the charge timer, clears EN_OTG and ADC_EN (DS §7.3.26.1 p.47).
- Periods (DS §6.6 p.21; REG0x01 b6-5 p.61):

  | WDTMR_ADJ | Period | Note |
  |---|---|---|
  | 01b | **5 s nominal, 4-7 s** | Minimum available |
  | 10b | 88 s (70-105 s) | |
  | 11b | 175 s (140-210 s) | POR default |

- The timer is reset only by a write to CHARGE_VOLTAGE or CHARGE_CURRENT, WD_RST, or a WDTMR_ADJ write.
- Firmware must write WDTMR_ADJ = 01b after **every** charger POR.
- The comparator interlock (H1/H2 of [LOOP]) keeps working, because it is MCU-independent. Bounded exposure: ≤ 7 s of regulated
  charge at the last setting, never a loop.
- **MCU hardware watchdog = required future work** (operator ruling 5; [LOOP] §10: RTWDOG 100 ms + WDOG1 1.0 s; a reset drops
  every EN through its 10 k pull-down; latch `ERR_MCU_WDT`).

**(c) I2C dead or stuck:**
- No CHARGE_* writes means the watchdog expires as in (b).
- A stuck START is released by the charger after tTIMEOUT_I2C = 1.5-2.5 s (DS p.21, §7.5.1.3 p.54).
- No clock stretching (p.54).

**(d) POR defaults** (all from the register map; reset by POR/REG_RESET):

| Register | POR value | Source |
|---|---|---|
| CHARGE_CURRENT | **0 mA** | p.63 |
| EN_AUTO_CHG | 0 | p.77 |
| CHRG_INHIBIT | 0 | p.60 |
| CHARGE_VOLTAGE | from the CELL_BATPRES pin (2S 8.400 V; **4S 16.800 V on the factory JP4**) | p.64, Table 7-6 p.39 |
| VINDPM | **3.200 V** (0xA0) | p.66, §7.3.12 p.39 |
| IIN_HOST | 5000 mA | p.65 (also reset to 5 A on every adapter removal, p.39) |
| ILIM_HIZ | external limit enabled, EN_EXTILIM = 1 | p.100 |
| WDTMR | 175 s | p.61 |
| ACOV | 33 V | p.76 |
| EN_PTM | 0 | p.96 |
| FRC_CONV_OFF | 0 | p.96 |

- **It does not charge by itself out of reset.** Default pre-charge 384 mA and trickle 128 mA are clamps applied as min() with
  CHARGE_CURRENT = 0 (Table 7-3 p.32; §7.3.5.2 p.31).
- There is no auto-wake/auto-charge bit equivalent to the BQ25713's AUTO_WAKEUP_EN.
- The converter itself does start about 226 ms after VBUS and regulates VSYS to VSYS_MIN (6.6 V for 2S) with no load. This
  draws ≈ 2.5 mA (IQ_VAC, DS p.14) but puts nothing into BAT.

**Pull resistors needed so a dead MCU means no charging:**
- the RT1987 EN pull-downs (on the board already);
- ILIM_HIZ held low by an NMOS biased from REGN_A, released only by PERMIT ([LOOP] H3(b)); replaces the EVM's always-enabled
  bias;
- EN_OTG grounded (JP2) with R44 removed;
- CMPIN_TR biased so that an unpowered permit reads "inhibit" once FRC_CONV_OFF is configured (§6 item 9).

### H4: input-voltage threshold for the always-powered regen mode

#### H4a: range, resolution, programmability. Status: PD

- **VINDPM** REG0x08/09 bits 12:2: 3200-27000 mV in **20 mV** steps, POR 3200 mV, runtime-writable (2-byte LSB-then-MSB write,
  §7.5.1.9 p.56; DS p.66).
- Accuracy ±1 % at 18.000 V (VINDPM = 0x384) and ±3 % at 4.480 V (0x0E0) (DS p.12).
- Only these two points are tabulated. ±1 % is applied at 18-20 V (nearest point); ±3 % is assumed at the 15 V FC setting, a
  conservative extrapolation. Bench B1 confirms.

**Settings:**

| Use | Setting | Field / word | Band | Margins |
|---|---|---|---|---|
| Regen, safety-floor choice | 19.000 V | 950 = 0x3B6 / **0x0ED8** | 18.81-19.19 V (±1 %) | 3.0 V over steady bus 16.0 V; 1.31 V over fw OV 17.5 V; 1.61 V over measured overshoot 17.2 V; **0.51 V over TPS61288 HW OVP min 18.3 V**; 2.21 V under the 21.4 V clamp |
| Regen, above boost HW OVP max | 19.800 V | 990 = 0x3DE / **0x0F78** | 19.60-20.00 V | **0.10 V above TPS61288 OVP max 19.5 V**, so even a failed-FB boost cannot drive the bus to the threshold; 1.40 V under the clamp. [REGEN]: threshold choice costs only 1-2 % of energy, but less headroom shrinks the τ budget by about (21.35 − Vth) / (21.35 − 19.0) |
| FC mode | 15.000 V | 750 = 0x2EE / **0x0BB8** | 14.55-15.45 V (±3 %) | Below the 15.59 V bus minimum ([LOOP]); the converter can draw from the bus |

#### H4b: draw at or just under the threshold. Status: PD (typicals) + bench B1

- Switching at zero load (EN_OOA = 0): IQ_VAC **2.50 mA typ** at VIN 28 V (DS p.14).
- HIZ: IQ_HIZ **1.00 mA typ / 1.15 mA max** at VIN 28 V (DS p.13).
- The first IQ_VAC row prints "1000 / 1150 mA" for EN_LEARN no-switching. This is evidently µA, matching IQ_HIZ; a DS unit typo.
- **Behaviour:** below VINDPM the charger "decreases the charge current … towards zero" (§7.3.21 p.42).
  - VSYS has no load on this board, so input current falls to the quiescent value.
  - Supplement then draws only from VCHG (D-BT-SQ isolates the pack).
- Bench B1: stiff 17.5 V, VINDPM 19.0 V, CHARGE_CURRENT 2.5 A, measure I_in. Expect a few mA.

#### H4c: warm response (charger powered and enabled; V-MOT crosses the threshold). Status: BG

- Not specified: no VINDPM loop bandwidth, no soft-start step time (only the step size SSSTEP_DAC = 8 mA, "during charge enable",
  DS p.19), no HIZ or FRC_CONV_OFF exit latency.
- MODE pin compensation: R18 3.57 k → 000b, normal compensation, 600 kHz (UG BOM p.16; DS Table 7-1 p.28). "Slow" is recommended
  for < 10 µF effective VBUS capacitance.
- **In the [LOOP] design the comparator holds the charger inhibited whenever V-MOT < 1.067 × VBUS** (the whole of cruise). Every
  regen burst therefore starts with an **inhibit exit**, and τ_warm = exit latency + loop rise.
- **[REGEN] requirement:** τ_warm ≤ 4 ms (10-90 % ≤ 9 ms) on the unmodified board; about 20 ms if 4 mF on V-MOT is confirmed;
  about 60 ms if the VESC cut-off is raised.
- **Bench B4** ([REGEN] M-R4, [LOOP] M2), run twice:
  1. FRC_CONV_OFF exit (CMPIN_TR step) at VINDPM 19.0 V, from Vth − 0.5 V to Vth + 1 V on a stiff supply, CHARGE_CURRENT 2.5 A;
     measure 63 % of I_bat;
  2. the same via ILIM_HIZ.

  Pass at ≤ 4 ms in either path. If only the VINDPM loop (no inhibit cycling) meets it, the [LOOP] comparator gating must be
  revisited. That is a design question, not a charger fail.

#### H4d: no re-qualification on V-MOT dips. Status: PD

- The 50 ms deglitch, 100 ms / 20 mA VBUS qualification and 226 ms converter start belong to the **power-up** sequence after
  VBUS > VVBUS_UVLOZ (2.5-2.9 V) (DS §7.3.1 p.27).
- A dip from 21.4 V to the 15.6-16 V bus crosses neither VVBUS_UVLO (2.3-2.8 V), VVBUS_CONVENZ (2.9-3.5 V) nor ACOV (DS p.16-17).
- The only VINDPM-related deglitch is the 1 ms "VINDPM active" status used for termination / timer half-rate (DS p.33). It does
  not gate the converter.

### H5: FC-charging mode. Status: PD (charger); the board bus budget is a condition

**Operating point:**
- VBUS 15.9 V → buck mode (Table 7-7 p.40-41) → 2S 8.4 V. BT_BUS off; assertFcChargeEnable() ordering is unchanged.
- **Charge current:** REG0x02/03 bits 13:3, 0-16320 mA, **8 mA** step, non-zero values < 128 mA treated as 128 mA (p.63).
  - 2048 mA ±5 %; 1024 mA ±8 % (DS p.11, 0-85 °C).
  - 2.5 A → 312 counts = 2496 mA, word 0x09C0.
- **CV:** REG0x04/05 bits 14:2, 5000-23000 mV, **4 mV** step. 8.400 V = 0x834, word 0x20D0. Accuracy **-0.5 % / +0.6 %**
  (8.358-8.450 V, DS p.10).
- **Termination:** ITERM 128-2016 mA in 8 mA steps, default 256 mA (p.70). Autonomous termination and recharge only with
  EN_AUTO_CHG = 1 (default 0, §7.3.5.1 p.30).
  - Recommended: host-controlled. Firmware terminates on the pack ADC (pin 25), because SRN sees VCHG upstream of D-BT-SQ (H7),
    and writes CHARGE_CURRENT = 0.
  - Safety timer 8 h default (p.77).

**Input current limit:**
- IIN_HOST REG0x06/07, 400-8200 mA, 25 mA step (p.65); accuracy 800-1000 mA at the 900 mA setting (DS p.12).
- The effective limit is the **lower** of IIN_HOST and the ILIM_HIZ pin (EN_EXTILIM = 1, p.100).

**Bus budget (board condition):**
- 2.0 A × 8.4 V = 16.8 W. At about 95.5 % efficiency (Fig 6-2, VIN 15 V, VOUT 7.4 V, read from plot p.22) that is 17.6 W in,
  i.e. **1.11 A from 15.9 V**.
- Plus about 0.15 A aux gives 1.26 A against the OC_FC 1.4 A single-sample latch. Usable, but with no margin for transients.
- **Set IIN_HOST ≤ 1.0 A in FC mode.** That caps FC charge at about 1.8 A (1.0 × 15.9 × 0.955 / 8.4).
- ≥ 2 A in FC mode needs either an OC_FC rework (fw) or accepting the margin. This is a board limit, not a charger limit.

### H6: voltage ratings, OVP behaviour. Status: PD

**Charger IC ratings:**

| Rating | Value | Source |
|---|---|---|
| Abs max VBUS, ACP_A/B, ACN_A/B, VSYS | **45 V** | DS p.8 |
| Abs max SW1x, SW2 | 45 V | DS p.8 |
| Abs max SRP/SRN | 30 V | DS p.8 |
| Abs max BTST/HIDRV | 50 V | DS p.8 |
| ROC VBUS/ACx | 0-40 V | DS p.9 |
| ROC VSYS, SRP/SRN | 23 V | DS p.9 |

- **ACOV**, REG0x16 b1-0, default 10b; ACOV fall thresholds are 1 V lower:

  | Setting | Rising threshold (min/typ/max) | Source / note |
  |---|---|---|
  | 00b | 19.25/20.00/20.75 V | Would trip on regen; **never select** |
  | 01b | 26.25/27.00/27.75 V | Register text says "25V". **DS inconsistency** |
  | 10b (default) | **32.25/33.00/33.75 V** | 10.85 V above the 21.4 V clamp |
  | 11b | 40.25/41.00/41.75 V | |

  Source: DS p.17, p.76.
- **At ACOV:** VBUS > VACOV_RISE for > 100 µs → converter shuts down, CHRG_OK low, BATFET on. It resumes when VBUS < VACOV_FALL
  for > 1 ms. Non-latched (DS §7.3.26.2 p.48).
  - At the default setting a regen burst cannot cause a drop-out unless V-MOT exceeds 32.25 V. That would also break the
    clamp / C-D8 / C-D10 ratings first.

**EVM parts on VIN:**

| Part | Rating |
|---|---|
| 10 µF MLCC GRM21BR61H106KE43L | 50 V |
| 33 µF tantalum polymer T521X336M050ATE050 | 50 V |
| C70 0.47 µF (VBUS pin) | 50 V |
| Q1_A/B, Q2_A/B AON6262E | 60 V |
| Q3/Q4/Q5 CSD18501Q5A | 40 V |
| Q9 SI7489DP | -100 V |
| VBAT caps C34/C39 | 35 V |

- All of these exceed 21.4 V plus margin (UG BOM pp.15-17). Unlike the BQ25713EVM, no input-path part is under-rated.
- Board C-D8/C-D10 (25 V) must still go to ≥ 35 V ([SPEC] §2). That is a board mod, independent of the charger.

### H7: battery pin through D-BT-SQ. Status: BG (datasheet-supported)

- **The device is never battery-powered on this board.** It powers from the higher of VBUS and VBAT (DS §7.3.1 p.27). BAT = VCHG
  is 0 V behind D-BT-SQ, so every loss of charger input power is a full POR.
  - **Firmware must re-configure on every charger power-up.** Registers are accessible 5 ms after the 5 ms POR (p.27), long
    before the 226 ms converter start.
  - The always-powered design makes this rare.
- **About 0 V on BAT at power-up:**
  - VBAT < VBAT_SHORT (2.9-3.1 V) → trickle at min(CHARGE_CURRENT, IBAT_SHORT 128 mA) with EN_LDO = 1.
  - VSYS_MIN − VBAT > 4 V → the BATFET clamp is 128 mA; 1-4 V → 512 mA (Table 7-9 p.49).
  - With CHARGE_CURRENT = 0 nothing flows.
  - Once enabled, about 128 mA charges VCHG (C-D11 10 µF + EVM C34/C39 2 × 10 µF ≈ 30 µF) toward the pack in about 2 ms. D-BT-SQ
    then conducts at VCHG ≈ VBT + 35 mV.
  - SRN then reads the pack (7.4-8.4 V > VSYS_MIN 6.6 V), giving fast charge (CC) after tTRANS_CHG 5 ms (DS p.21).
  - **No step load**, because the charger current-limits the first conduction.
- **Battery detection:** CELL_BATPRES ≥ 18 % of REGN = present (DS p.20). Strapped 2S at 40 % (JP4 1-2, measured 2 V, UG Table
  2-2). No detection of the electrochemical pack is needed.
- **CV sensing:** at SRN, which is VCHG **upstream** of D-BT-SQ. The pack ends lower by the RT1987 forward drop (35-50 mV per
  [SPEC] §2, ≈ -0.4 to -0.6 %).
  - Combined with -0.5/+0.6 % CV accuracy, worst case is 8.316-8.450 V at the pack.
  - CHARGE_VOLTAGE can be trimmed in 4 mV steps (e.g. 8.440 V) **only after** the pin-25 ADC cross-check (M8-class calibration).
  - BATOVP is 107.8-109.6 % of CHARGE_VOLTAGE (9.06-9.21 V at 8.4 V, DS p.18). It is non-latched and only active while charging.
- **NVDC / BATFET:** N-ch Q5 is fully on in fast charge and linear in LDO mode (pin table p.7).
  - VSYS (J2) stays unloaded; keep the EVM SYS capacitors, since TI requires ≥ 50 µF effective (DS Table 8-5 p.127).
  - Do **not** tie SYS to BAT: that would defeat the BATFET LDO current clamp.
- **D-BT-SQ must NOT be bridged.** Keeping it:
  - makes supplement, VAP and OTG unable to touch the pack;
  - means the device never runs from the pack (no idle drain).

  Bridging would:
  - connect the 156 µF of VSYS caps to the pack through Q5 (BATFET on at battery-only wake, §7.3.1, "BATFET is turned on");
  - keep the charger alive on the pack (IQ_BAT 12-1100 µA, DS p.13);
  - make OTG possible (blocked only by the EN_OTG pin).
- **Bench B5:**
  1. First enable from VCHG ≈ 0: confirm CHRG_STAT goes 001 → 011, no BATOVP trip, D-BT-SQ conducts.
  2. Drop D-BT-SQ (pin 32 LOW) mid-charge: expect a non-latched BATOVP on the 30 µF node and clean recovery.
  3. Termination by firmware at 8.40 V pack.

### H8: inrush / hot-plug. Status: PC with mod (FAIL as shipped) + bench B6

**EVM input capacitance on the RT1987-ramped node** (UG Fig 3-1, tiles t00/t01/t10/t11; BOM p.15), JP6 installed (factory,
Q9 bypassed):

| Location | Parts | Nominal |
|---|---|---|
| VIN_SW (phase B side) | C3, C4, C47, C55 (4 × 10 µF) + C1 33 µF Ta-poly | 73 µF |
| VIN_SW (phase A side) | C16, C17, C42, C43 (4 × 10 µF) + C32 33 µF Ta-poly | 73 µF |
| After RAC | C7, C20 (10 µF) + C8/C9/C21/C22 (10 n/1 n) | 20.0 µF |
| VIN snubber | C48 1 µF behind R28 ∥ R29 (3.9 Ω each) | 1.0 µF |
| VBUS pin filter | C70 0.47 µF behind R32 1 Ω | 0.47 µF |
| Differential | C2, C29 (0.1 µF) | ≈ 0.1 µF |
| **Total** | | **≈ 167.6 µF** |

- **As shipped:** (167.6 + 20 board C-D8/C-D10) µF × 12 mA/µF = **2.25 A**. That is over the 1.4 A OC_FC single-sample latch and
  near the RT1987 2.5 A start-up SCP ([SPEC] §6). **FAIL.**
- Nominal is the worst case for inrush. DC bias only lowers MLCC value; tantalum polymer does not derate.
- **Mod A** (keep JP6 installed): depopulate **C1, C32, C4, C47, C55, C17, C42, C43**. Keep **C3, C16** (one per phase,
  before RAC), C7, C20, C48, C70.
  - 41.7 µF + 20 µF = 61.7 µF → **0.74 A**; plus 0.15 A aux = **0.89 A ≤ 1.0 A budget**.
  - TI's minimum effective input capacitance is 4 µF (20 V/100 W, OTG not needed, DS Table 8-2 p.126). That needs ≥ 1 µF
    effective per remaining MLCC at 16-21 V. The DC-bias curve of GRM21BR61H106KE43L is not a primary in hand, so measure with an
    LCR meter at bias (bench B6a).
  - If effective capacitance < 10 µF, change R18 3.57 k → 6.04 k (MODE 010b, slow compensation, 600 kHz; DS Table 7-1 p.28).
- **Mod B** (alternative, not proven): remove JP6 so Q9 (CHRG_OK-controlled inrush FET, UG Table 2-2) isolates VIN_SW.
  - The RT1987 then sees only C48 + C70 + C63: (1.6 + 20) µF × 12 = 0.26 A.
  - The Q9 gate slew (R36 20 k / C63 0.1 µF / Q10) is not specified. Q9 also opens whenever CHRG_OK drops (ACOV, faults), and
    each re-close is a new hot-plug from the live bus.
  - **Not recommended** without a scope measurement.
- **The charger does not switch during the 1.3-1.75 ms ramp:** the converter starts about 226 ms after VBUS (DS §7.3.1 p.27).
  The 100 ms / 20 mA qualification sink adds 0.02 A.
- **VSYS-side capacitance** (C10-C14, C56-C59 9 × 10 µF + C23/C24 2 × 33 µF ≈ 156 µF) is charged by the converter at start-up,
  input-current-limited by min(IIN_HOST, ILIM_HIZ).
  - Below VSYS_UVP the input limit is clamped to 0.3 A (VBUS > 14.4 V) (DS §7.3.26.12 p.50).
  - Above it, the ILIM pin setting applies. **Bench B6b:** bus-side current at converter start must stay < 1.0 A.
- **Death-5 relevance:** with JP6 installed and Mod A, every REGEN / FC_CHARGE close is a 0.74 A, 1.3 ms ramp. That is about 7.6×
  below the Death-5 class (470 µF × 12 mA/µF = 5.6 A). Keep the 10 ms dwell rules of assertFcChargeEnable().

### H9: I2C / logic. Status: BG (the unpowered back-power check only)

**Bus facts:**

| Item | Value | Source |
|---|---|---|
| 7-bit address | **0x6B** (D6h write / D7h read) | DS §7.5 p.52, Device Comparison p.4 |
| Bus speed | 100 kHz / 400 kHz / 1 MHz | DS p.52 |
| VIL / VIH | 0.42 V max / 0.8 V min, "1.2 V-5 V VDD pull-up" | DS p.19-20 |
| SDA/SCL abs max | 5.5 V | DS p.8 |
| Leakage | ±1 µA at 5.5 V | DS p.20 |
| ID registers | ManufacturerID 0x2E = 0x40; DeviceID 0x2F = 0x09 | DS p.94-95 |

- 0x6B is the only device on the Teensy bus. Use the ID registers as F2 config self-test.
- 3.3 V compatible.

**EVM pull-ups (must go):**
- R12, R13 10 k to the EVM 3V3 (U2 TPS7A1633, fed from VBAT through D3 and from VIN through D4 + R47 10 Ω) (UG t12/t21).
- **Remove R12 and R13.** Otherwise the Teensy RSDA/RSCL pull-ups and the EVM rail fight, and the Teensy 3V3 back-powers a dead EVM
  rail through 5 k.
- **Remove JP5** (disconnects U2 OUT) as well, or leave it, once every pull-up to it is gone: R11, R14, R33, R43, R44, R19 (LED).

**Back-powering an unpowered charger through SDA/SCL:**
- Clamp behaviour with the device unpowered is not specified.
- **Bench B9:** charger unpowered, Teensy pull-ups live; measure bus-high and current into SDA/SCL. Pass: bus ≥ 3.0 V and
  < 50 µA.

**Status pin for pin 6:**
- CHRG_OK, open-drain, VOL ≤ 0.4 V at 5 mA, leakage ±1 µA, abs max 5.5 V (DS p.6, p.20).
- HIGH = VBUS valid (3.5 V < VBUS < ACOV) after the 50 ms deglitch and no fault. LOW on ACOV, ACOC, TSHUT, BATOVP while charging,
  BATDOC, REGN_PG, force-converter-off (256 µs minimum pulse). Latched low on SYSOVP or VSYS_UVP until the host clears it (DS
  §7.3.10 p.38).
- Optional: a 256 µs pulse on each CHRG_STAT change (CHRG_OK_INT).
- Wire pin 6 to J5-2, remove R43, use Teensy INPUT_PULLUP or a pull-up to Teensy 3V3.
- Semantics replace "STAT steady-LOW = no input" with "CHRG_OK LOW = no valid input or a converter fault". It is not a
  charging-state pin; charging state is CHRG_STAT (REG0x19 b7-5, p.79).

**Pin 5:** becomes the Teensy term of PERMIT (P5) into the H3 inhibit stage → ILIM_HIZ (J5-1). It is no longer an MPPT
disable.

### H10: thermal, efficiency, wiring, mechanical. Status: BG (mechanical fit and leads); efficiency PD

**Efficiency** (read from TI typical-characteristic plots; RAC 10 mΩ, RSR 5 mΩ, 3.3 µH, 600 kHz CCM; the EVM inductors are
CMLE104T-3R3MS 3.3 µH):

| Case | Efficiency | Source |
|---|---|---|
| VIN 15 V, VOUT 7.4 V, 2.5 A | **≈ 95-96 %** | Fig 6-2 p.22 |
| VIN 20 V (regen), 7.4 V, 2.5 A | **≈ 94 %** | Fig 6-3 p.22 |
| Light load, VIN 15/20 V, 0.1-0.2 A | 85-93 % | Fig 6-7 p.23 |

**Loss and thermal:**
- About 1.0 W at 16 V / 8.4 V / 2.5 A (21 W out). About 1.3 W at 19-21 V.
- Spread over 7 DFN5×6 FETs and two inductors rated 13 A (UG BOM p.16). No thermal concern.
- TSHUT 155 °C rise / 135 °C fall (DS p.18).
- Off-board mounting removes the LM1084-proximity question.

**Mechanical:**
- **The EVM board dimensions are not given in SLUUCY2** (assembly figures pp.11-14 carry no dimension). **UNKNOWN; measure.**
- The populated inventory alone is about the area of the 32 × 35 mm Ag105 outline before routing and spacing: two 10 × 10 mm
  inductors, seven 5 × 6 mm DFN8 FETs, four 7343 tantalums, three 5.08 mm terminal blocks, a 20-pin J7 and a 10-pin J6. **It
  cannot sit on the footprint.**
- Mount it off-board with a carrier PCB in the 22 Ag105 holes ([SPEC] §7).

**Leads:**
- VCHG-IN/GND as a short twisted pair (≤ 10 cm suggested), plus VCHG/GND.
- DS §8.2.2.1 p.124 warns of hot-plug ringing with cable inductance and gives an RC damping network. The EVM already has R28 ∥
  R29 + C48 on VIN.
- **Bench B10:** scope VCHG-IN at the EVM terminal on a REGEN close with V-MOT at 21 V. Pass: peak < 30 V, ringing damped within
  50 µs.

### H11: availability. Status: PD (TI store, fetched 2026-11-05 17:38 UTC)

- **BQ25773EVM: $199.00** (`data-price="199.0"`, ti.com/tool/BQ25773EVM). **TI inventory 95.**
- BQ25773REER IC: TI inventory 39 695.
- No GaN "BQ25773GEVM" OPN returned inventory from the TI endpoint.
- Lead time is not shown for in-stock items.
- Mouser and Farnell could not be fetched (HTTP/2 reset; timeout). Missing.
- The EV2400 is not needed: the Teensy is the host.

### H12: telemetry. Status: PD

16-bit ADC (DS §7.3.22 pp.42-43; registers pp.80-93):

| Channel | LSB | Format / range | Accuracy | Register |
|---|---|---|---|---|
| ADC_IBAT | **1 mA** | 2's complement; charge positive only with a valid adapter | **Not tabulated for the ADC.** The IBAT *pin* monitor is -3/+7 % at 20.48 mV (4.1 A), -6/+13 % at 10.24 mV, DS p.14. Treat ADC_IBAT accuracy as UNKNOWN until bench B12 | 0x28/29 |
| ADC_IIN | 0.5 mA | 2's complement | -4/+2.5 % at 50 mV (5 A) | 0x2A/2B |
| ADC_VBUS | 2 mV | | ±2 % at 28 V | 0x26/27 |
| ADC_VBAT (SRN) | 1 mV | | -2/+1 % at 9 V | 0x1A/1B |
| ADC_VSYS | 2 mV | | | 0x2C/2D |
| PSYS, CMPIN_TR | | | | |

- **Rate:** 6/12/24 ms per channel (13/14/15-bit, ADC_SAMPLE); continuous mode cycles the enabled channels (REG0x3B p.110).
  IBAT + IIN + VBUS at 13-bit gives an 18 ms cycle (≈ 55 Hz per channel). That suits the 50 Hz EMS / I_charge telemetry.
- "ADC readings are only valid for DC states and not for transients" (p.43). **The J-guards G1 (5 ms) and G2 (20 ms) must keep
  using the Teensy's own INA253 and divider ADCs.** The charger ADC is a corroborating term only.
- ADC_EN is cleared by the charger watchdog (p.47) and on every POR. Re-enable it in the config cycle.
- Status bits: CHRG_STAT, IN_VINDPM, IN_IIN_DPM, STAT_AC, FAULT_* (REG0x18-0x21 pp.78-86).

### System row (not a charger property): regen hard requirement on this board. Status: BG

- The VESC stops regenerating at about 21.35 V within 19-47 ms ([REGEN]). Until M-R0 (cut-off mechanism) and M-R3 (CV load at
  19 V on V-MOT) are done, no charger can be credited with regen capture.
- The BQ25773 is the only I2C candidate here that can sit at Vth ≥ 19.6 V (above boost OVP max).
- If the VESC cut-off is raised to about 24 V ([REGEN]), ACOV 33 V default and the 45 V abs max still leave margin.

## 3. Register map excerpt (the fields this application uses)

2-byte registers: write LSB then MSB, with nothing in between; MSB first is ignored (DS §7.5.1.9 p.56).

| Reg | Field (bits) | POR | Application value | Cite |
|---|---|---|---|---|
| 0x00 | CHRG_INHIBIT (0) | 0 | 1 = inhibit (soft backstop) | p.59-60 |
| 0x00 | EN_LDO (2) | 1 | keep 1 (BATFET LDO clamps for first-charge from VCHG ≈ 0) | p.59 |
| 0x00 | EN_LEARN (5) | 0 | 0 | p.59 |
| 0x01 | WDTMR_ADJ (6:5) | 11b (175 s) | **01b (5 s)** every POR | p.61 |
| 0x01 | EN_LWPWR (7) | 1 | 0 (performance mode, so ADC/IBAT available) | p.61 |
| 0x02/03 | CHARGE_CURRENT (13:3), 8 mA | 0 | 0 until permitted; ≤ 0x09C0 (2496 mA) | p.63 |
| 0x04/05 | CHARGE_VOLTAGE (14:2), 4 mV | CELL pin | 0x20D0 (8.400 V) | p.64 |
| 0x06/07 | IIN_HOST (10:2), 25 mA | 0x320 (5 A) | FC 0x00A0 (1.000 A); regen ≤ 0x00F0 (1.500 A) | p.65 |
| 0x08/09 | VINDPM (12:2), 20 mV | 0x280 (3.2 V) | regen 0x0ED8 (19.0 V) or 0x0F78 (19.8 V); FC 0x0BB8 (15.0 V) | p.66 |
| 0x0E/0F | VSYS_MIN (12:0), 5 mV | 6.6 V (2S) | leave | p.69 |
| 0x15 | WD_RST (6) | 0 | 1 = kick | p.75 |
| 0x16 | ACOV_ADJ (1:0) | 10b (33 V) | leave 10b (or 11b); **never 00b** | p.76 |
| 0x17 | EN_AUTO_CHG (7) | 0 | 0 (host-controlled) | p.77 |
| 0x19 | CHRG_STAT (7:5) | – | telemetry | p.79 |
| 0x20/0x21 | FAULT_* / STAT_AC, IN_VINDPM, IN_IIN_DPM | – | telemetry | pp.83-86 |
| 0x30 | FRC_CONV_OFF (3) | 0 | **1** (fast hardware inhibit via CMPIN_TR) | p.96 |
| 0x30 | CMP_POL (6), CMP_DEG (5:4) | 0, 00b (1 µs) | CMP_POL = 1 (CMPOUT LOW when CMPIN_TR < 1.2 V = permit LOW), CMP_DEG 00b | p.96 |
| 0x30 | EN_PTM (2) | 0 | **must stay 0**; read back | p.96 |
| 0x32 | EN_EXTILIM (7) | 1 | **keep 1**, so the ILIM_HIZ resistor ceiling always applies | p.100 |
| 0x34 | CMP_EN (2) | 1 | 1 | p.103 |
| 0x34 | BATFETOFF_HIZ (1) | 0 | 1 (optional) | p.103 |
| 0x34 | OTG_VAP_MODE (5) | 1 | leave (EN_OTG pin grounded) | p.103 |
| 0x35 | EN_HIZ (7) | 0 | soft backstop | p.104 |
| 0x35 | EN_OTG (4) | 0 | 0 | p.104 |
| 0x35 | DETECT_VINDPM (5) | 0 | **never write 1** (would overwrite VINDPM with VBUS − 1.28 V) | p.104 |
| 0x35 | REG_RESET (6) | 0 | – | p.104 |
| 0x3A/0x3B | EN_ADC_* , ADC_RATE, ADC_EN, ADC_SAMPLE | off | IBAT, IIN, VBUS; continuous; 13-bit | pp.109-110 |
| 0x2E/0x2F | IDs | 0x40 / 0x09 | self-test | p.94-95 |

## 4. Timing diagrams in words

**T1. Charger cold power-up** (FC_CHARGE or REGEN closes; VCHG-IN ramps at the RT1987 slew):

| t | Event | Source |
|---|---|---|
| 0 | EN high | |
| ≈ 1.3 ms | VCHG-IN ≈ 15.8 V; inrush ≈ 0.74 A after Mod A | [SPEC] §6 |
| ≈ 0.2 ms | VBUS passes UVLOZ 2.7 V; POR 5 ms | DS p.27 |
| ≈ 10 ms | **Registers accessible.** Firmware config burst (≈ 3 ms at 100 kHz): IDs → WDTMR_ADJ 01b → EN_LWPWR 0 → CHARGE_VOLTAGE 8.400 → VINDPM → IIN_HOST → CMP_POL/FRC_CONV_OFF → ADC setup → **read back all**, including EN_PTM = 0. CHARGE_CURRENT stays 0 | DS p.27 |
| ≈ 50 ms | Deglitch over; REGN up, CHRG_OK high, STAT_AC = 1; MODE detect | DS p.27 |
| 50-150 ms | VBUS qualification, 20 mA sink; CELL_BATPRES read (does not override host-written values); one VBUS ADC | DS p.27, §7.3.13 p.39 |
| ≈ 226 ms after VBUS > 3.4 V | Converter starts, regulates VSYS to 6.6 V | DS p.27 |
| after that | Firmware may write CHARGE_CURRENT, gated by PERMIT | |

**T2. Regen burst with the charger already powered (always-powered, REGEN closed in Run, VINDPM 19.0 V, CHARGE_CURRENT set):**

| Phase | What happens |
|---|---|
| Cruise | V-MOT ≈ VBUS. Comparator H1 LOW → PERMIT LOW → ILIM_HIZ LOW (HIZ) and CMPIN_TR LOW (FRC_CONV_OFF). Charger off, draw ≈ 1 mA |
| t0 | Brake; V-MOT rises in 19-47 ms toward 21.35 V ([REGEN]) |
| t1 | V-MOT > 1.067 × VBUS + hysteresis (≈ 17.4 V at a 16 V bus). H1 HIGH → PERMIT HIGH (TLV3012B ≤ 4 µs) → inhibit released. **The converter resumes: latency UNKNOWN (B4)** |
| t1 + τ | The charge loop ramps; input current rises until VINDPM holds V-MOT at 18.81-19.19 V or IIN/ICHG limits. Must happen before V-MOT reaches 21.35 V: τ_warm ≤ 4 ms ([REGEN]) |
| End of burst | Regen current falls; VINDPM drives the charge current to 0. V-MOT falls under the H1 fall trip → PERMIT LOW → inhibit within B2 latency (≤ 290 µs required) before D-MT-EN can conduct |

**T3. Regen → FC mode** (order per [LOOP] §6):
1. P5 LOW (inhibit), wait ≥ B2 latency.
2. CHARGE_CURRENT = 0.
3. REGEN LOW.
4. BT_BUS LOW, via assertFcChargeEnable().
5. Write VINDPM 15.0 V and IIN_HOST 1.0 A; read back.
6. FC_CHARGE HIGH, then the H2 permit.
7. P5 HIGH.
8. Write CHARGE_CURRENT.

**T4. FC → regen:** the reverse order:
1. P5 LOW.
2. CHARGE_CURRENT 0.
3. VINDPM 19.0 V, read back.
4. FC_CHARGE LOW.
5. BT_BUS HIGH.
6. REGEN HIGH.
7. Write CHARGE_CURRENT. P5 follows H1.

The VINDPM write must precede the path change, so the charger never sees the bus with a below-bus threshold in regen topology.

## 5. Datasheet / user-guide inconsistencies found (do not trust the wrong side)

| # | Inconsistency | Correct / safe reading |
|---|---|---|
| 1 | DS §6.6 p.21 names the watchdog field "REG0x12[14:13]" (the SMBus BQ25770 address) | It is ChargeOption0 word bits 14:13 = REG0x01 b6-5 (p.61) |
| 2 | ACOV 01b: EC p.17 gives 27 V rising; REG0x16 p.76 says "25V" | Not used. Default 33 V is consistent |
| 3 | BATCOC: §7.3.26.6 p.48 says disabled by default (00b); REG0x15 shows reset 3h (100 mV) | Read it back |
| 4 | IQ_VAC no-switching row prints "mA" | Evidently µA (p.14) |
| 5 | UG p.8-9 writes AUTOTUNE/GM values to 0x61/0x62 | DS lists 0x60/0x61 as AUTOTUNE_READ (read-only) and 0x62-0x65 as FORCE (pp.113-120). Follow DS. Not needed for charging |
| 6 | PH_DROP_DEG 10b max "1.46 ms" < min 8.94 ms (p.74) | Typo |

## 6. EVM modifications (designators from UG Fig 3-1 / BOM)

1. **JP4 → 1-2 (2S)**; check the CELL pin ≈ 2 V (UG Table 2-2). Factory is 4S: CV 16.8 V, SYSOVP 22 V. JP1 (battery removal)
   stays off.
2. **Input capacitance (Mod A):**
   - Depopulate C1, C32 (33 µF Ta-poly) and C4, C47, C55, C17, C42, C43.
   - Keep C3, C16, C7, C20, C48, C70, C2, C29. JP6 stays installed.
   - LCR-check the effective capacitance at 19 V (≥ 4 µF total). If < 10 µF effective, R18 → 6.04 k (slow compensation).
3. **ILIM_HIZ (J5-1):**
   - Re-bias the divider for a hardware input-current ceiling of about 1.5 A: R15 200 k → 31.6 k, R16 300 k → 14.7 k, from REGN_A.
     V = 5 × 14.7 / 46.3 = 1.588 V → IINDPM = (1.588 − 1) / (40 × 0.01) = **1.47 A** (DS pin table p.6). Accuracy is about ±0.2 A
     by interpolation of DS p.12 (1.4 V: 0.8-1.2 A).
   - Divider Thevenin about 10 k × ILEAK ±1 µA = ±10 mV.
   - Add the [LOOP] H3(b) stage: Q2 NMOS drain on ILIM_HIZ, gate pulled up to REGN_A (100 k); Q1 releases on PERMIT. Pin LOW =
     HIZ unless PERMIT is actively HIGH.
   - JP3 (HIZ) stays off.
4. **CMPIN_TR / CMPOUT:**
   - Remove R39 (2 M), R11, R14 and the R42 / R38 VIN-sense network.
   - Feed PERMIT through 10 k into CMPIN_TR with 100 k to GND.
   - Firmware sets CMP_POL = 1, FRC_CONV_OFF = 1: CMPIN_TR < 1.2 V → converter off.
   - Fast-path inhibit; optional but recommended (B2).
5. **I2C:** remove R12 and R13 (10 k to EVM 3V3). SDA/SCL from J8/J6 to Teensy 18/19 with the board's RSDA/RSCL only.
6. **CHRG_OK → pin 6:** remove R43 (10 k to EVM 3V3). J5-2 to Teensy pin 6 with a Teensy-side pull-up. D1/Q7 (LED driver on
   CHRG_OK) can stay; Q7's gate load is negligible.
7. **EN_OTG:** keep JP2 installed (forward mode, EN_OTG to GND); remove R44.
8. **3V3 LDO:** remove JP5 (U2 output disconnected) once 5-7 are done.
9. **Do not populate D2. Keep VSYS (J2) unloaded and the SYS capacitors fitted. Do not link VSYS to VBAT.**
10. **Board-side (not EVM):** C-D8/C-D10 25 V → ≥ 35 V; [LOOP] H1/H2 comparators and the H3 stage on a carrier; carrier wiring:
    - EVM J1 VIN/PGND ↔ Ag105 VIN+ / VIN-;
    - J3 VBAT/PGND ↔ VBAT+ / VBAT-;
    - J8 SDA/SCL;
    - J5-1 ← H3;
    - J5-2 → pin 6;
    - CMPIN_TR ← PERMIT.
11. **Firmware (fw v38 scope):**
    - Replace the Ag105 driver with a BQ25773 driver (config + read-back on every charger POR, T1).
    - WDTMR 5 s with a 1 Hz CHARGE_CURRENT / WD_RST kick.
    - Port the J guards G1-G3 and the trip latch.
    - Enable `FAULT_SWITCH_CONFLICT` outside `#if !BENCH_TEST` ([LOOP] §13).
    - Convert the fw v37 rev 2 `J` session to an FC-path session ([LOOP] §13).
    - MCU hardware watchdog (RTWDOG + WDOG1, `ERR_MCU_WDT`) as required future work.

## 7. Bench gates (this part)

| ID | Test | Pass |
|---|---|---|
| B1 | VINDPM 19.0 / 19.8 / 15.0 V: regulation point and I_in from a stiff source 0.5 V under threshold, CHARGE_CURRENT 2.5 A | Within ±1 % (±3 % at 15 V); I_in < 5 mA |
| B2 (= [LOOP] M2) | Inhibit-to-I_in < 10 mA latency, via ILIM_HIZ and via FRC_CONV_OFF, at IINDPM 1.5 A | ≤ 290 µs |
| B3 | VINDPM, IIN_HOST, WDTMR, FRC_CONV_OFF retained across an HIZ / FRC_CONV_OFF cycle (read back) | Unchanged |
| B4 (= [REGEN] M-R4) | Warm step: inhibit exit + Vth − 0.5 → Vth + 1 V; τ to 63 % of I_chg | ≤ 4 ms (unmodified board) |
| B5 | First charge from VCHG ≈ 0 through D-BT-SQ; D-BT-SQ open mid-charge; firmware termination | No latch, CHRG_STAT sequence 001 → 011, clean recovery |
| B6 | (a) LCR at 19 V bias on the kept MLCCs; (b) scope bus-side current on FC_CHARGE close and at converter start (226 ms) | (a) ≥ 4 µF; (b) < 1.0 A peak |
| B7 | Charger watchdog: stop I2C kicks with CHARGE_CURRENT 1 A | I_chg → 0 within 4-7 s |
| B8 | POR with the factory-strap check: CHARGE_VOLTAGE reads 0x20D0 before any write | 8.400 V |
| B9 | Charger unpowered: SDA/SCL bus-high and back-feed current | ≥ 3.0 V, < 50 µA |
| B10 | VCHG-IN ringing at the EVM on REGEN close at 21 V | < 30 V peak |
| B12 | ADC_IBAT vs a shunt at 0.5 / 1 / 2.5 A | Error recorded for the EMS |

## 8. Corrections to the round-1 dossier

1. **Source:** primaries were obtained (SLUSEK7 Sep 2024; SLUUCY2 Nov 2023). Round-1 "[DV] / UNVERIFIED" items are now cited.
2. **Absolute maximum (round 1: UNVERIFIED):** 45 V VBUS/ACP/ACN/VSYS/SW; 30 V SRP/SRN; ROC VBUS 40 V (DS p.8-9).
3. **ACOV:** thresholds are 20 / 27 (EC; register text 25) / **33 (default)** / 41 V rising with 1 V hysteresis, > 100 µs to
   trip, > 1 ms to recover (DS p.17, p.48, p.76). Round 1's "41 V label presumably the 36 V EPR setting" is confirmed as 11b.
4. **VINDPM range** is **3.2-27.0 V**, 20 mV LSB, ±1 % at 18 V and ±3 % at 4.48 V (DS p.12, p.66). Round 1 inferred the 20 mV
   LSB correctly but could not confirm the ceiling. 19.0 V and 19.8 V are both legal.
5. **WRONG in round 1: "POR default VINDPM = measured no-load VBUS − 1.28 V".** The BQ25773 POR value is a fixed **3.2 V
   (0xA0)**. VBUS − 1.28 V is written only when the host sets DETECT_VINDPM (DS §7.3.12 p.39; REG0x35 b5 p.104). The hazard
   direction is the same (permissive toward the bus), but there is no automatic re-measurement to overwrite host values.
6. **WRONG: charge-current LSB "128 mA at 5 mΩ (inferred)".** The LSB is **8 mA**. The minimum non-zero is 128 mA; the range is
   0-16320 mA (DS p.63). No RSR swap is needed for resolution. Low-current accuracy is ±8 % at 1 A and ±5 % at 2 A (DS p.11).
7. **ILIM_HIZ exists on the BQ25773** (pin 13): < 0.4 V HIZ, > 0.8 V exit, and ILIM = (V − 1) / (40 × RAC) (DS p.6, p.20).
   **CHRG_INHIBIT exists** (REG0x00 b0). **EN_HIZ exists** (REG0x35 b7). Round 1 had these UNVERIFIED / [SIB].
8. **New, not in round 1:** the independent comparator **FRC_CONV_OFF** hardware converter-off with 1 µs deglitch (DS §7.3.4
   p.30). It needs I2C configuration after every POR.
9. **WRONG: the watchdog is "140, 175 and 210 s options (mapping UNVERIFIED)".** Those are the min/typ/max of the 175 s setting.
   The options are **5 s (4-7 s) / 88 s (70-105 s) / 175 s (140-210 s)** / disabled (DS p.21, p.61). The 5 s setting **meets**
   the spec's ≤ ~5 s host-silence stop within its 7 s maximum. Round 1's "does not meet" is reversed.
10. **Start-up latency** was understated as "≥ 55-60 ms". The converter powers up **about 226 ms** after VBUS > VVBUS_CONVEN,
    after the 50 ms deglitch and a 100 ms / 20 mA qualification (DS §7.3.1 p.27). Cold-start regen capture is impossible, so the
    always-powered architecture is mandatory, not optional.
11. **BATFET is N-channel** (BATDRV = SRP + 5 V; EVM Q5 CSD18501Q5A), not a P-channel / "polarity UNVERIFIED" (DS p.7).
12. **The CELL_BATPRES 2S default (8.400 V CV, 6.6 V VSYS_MIN, 12 V SYSOVP, 200 mV recharge)** is confirmed (DS Table 7-6 p.39).
    **New hazard:** the EVM ships JP4 in **4S** (UG Table 2-2).
13. **EVM input capacitance (round 1: UNVERIFIED)** is about 167.6 µF nominal including **two 33 µF tantalum-polymer**
    capacitors (C1, C32) plus about 156 µF on VSYS. Inrush as shipped is 2.25 A: FAIL until Mod A (§6).
14. **EVM I2C pull-ups (round 1: "likely")** are R12/R13 10 k to the EVM 3V3 (U2 TPS7A1633 fed from VBAT via D3 and VIN via D4).
    Remove them, plus R43 (CHRG_OK) and R44 (EN_OTG).
15. **CV accuracy** at 8.4 V is **-0.5 / +0.6 %** (DS p.10), not the family "±0.5 %".
16. **IIN_HOST** is 400-8200 mA in 25 mA steps; 0.8-1.0 A at the 900 mA setting (DS p.12, p.65). Round 1's "≤ 1.0 A plausible" is
    confirmed.
17. **Thermistor:** CMPIN_TR is either the independent comparator or a TREG regulation loop with an NTC (DS §7.3.6 p.33). No
    JEITA. If CMPIN_TR is used for FRC_CONV_OFF (§6 item 4), TREG is unavailable; monitor J-NTC from a Teensy ADC instead.
18. **Efficiency (round 1: UNVERIFIED):** about 95-96 % at 15 V → 7.4 V, 2.5 A; about 94 % at 20 V (DS Fig 6-2/6-3 p.22).
19. **OTG / VAP:** round 1's concern is now proven controllable in hardware. All three need the EN_OTG pin HIGH (Table 7-5);
    JP2 grounds it.
20. **Price / stock (round 1: price unknown):** $199, TI stock 95 (2026-11-05).
21. **EVM identity:** SLUUCY2 covers the silicon BQ25770EVM/BQ25773EVM; U1 is BQ25773REER on the BQ25773EVM (BOM p.17). The GaN
    SLUUD24 board was not evaluated.
22. **Fit score:** round 1 gave 4/10 on unread primaries. On primaries the part has no FAIL. Its remaining risks are B2/B4 timing
    (shared with every candidate), EVM size, and an EVM over-designed for 16 A.

## 9. missing_primaries

- Murata GRM21BR61H106KE43L DC-bias curve (effective capacitance of the kept input MLCCs at 16-21 V; bench B6a substitutes).
- EVM board outline dimensions (not in SLUUCY2; measure the board).
- Mouser / Farnell stock and price pages (fetch failed); TI lead time for back-order.
- TI data on the VINDPM loop bandwidth, soft-start ramp time and HIZ / FRC_CONV_OFF exit and entry latencies (not in SLUSEK7; B2 /
  B4).
- ADC_IBAT accuracy specification (not tabulated in SLUSEK7; B12).
- Q9 inrush-circuit slew (only needed for Mod B).
- BQ25773 SDA/SCL behaviour when unpowered (B9).
- Cross-cutting, carried from [LOOP] / [REGEN]:
  - NXP i.MX RT1060 reference manual (watchdog);
  - 74LVC1G0x thresholds;
  - TL431;
  - VESC Six EDU `l_max_vin`, fault-stop timing and input capacitance;
  - RT1987 turn-off delay.
