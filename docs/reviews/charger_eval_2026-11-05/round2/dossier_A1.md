# Round-2 dossier A1: TI BQ25756 on the BQ25756EVM (sibling BQ25756EEVM), Path A replacement for the Ag105 (board rev 20260622)

Date: 2026-11-05. Written against the 2026-11-05 operator rulings:
- regen harvesting and FC charging are both hard requirements;
- Path A must be shown fully feasible;
- R3 is replaced by "no circular loop, no runaway";
- the always-powered charger architecture is accepted;
- an MCU hardware watchdog is required future work.

Round 1 has no dossier for this part. Round 1 only screened it out in one table row (see section 9).

## 0. Sources and evidence rules

Primary documents, read on 2026-11-05. The PDFs and pdftotext copies are in `scratchpad/charger_eval/datasheets/`. Page renders and crops are in `r2/bq756/`.

- **[DS]** TI SLUSEN5A, *BQ25756 Standalone/I2C Controlled, 1- to 14-Cell Bidirectional Buck-Boost Battery Charge Controller*, Aug 2023, rev. Aug 2026 (pdftotext, 75+ pp.). Cited as "DS §x / p.N", where N is the printed page.
  - Read in full: §4 pins, §5 specifications, §6.1-6.4, §6.5 register map, §7.2.1 application.
  - Typical-curve figures 7-3, 7-7 and 7-8 were read from 400 dpi renders (`r2/bq756/f73.png`, `f77.png`, `f78.png`).
- **[DSE]** TI SLUSFF4A, *BQ25756E ... 1- to 7-Cell ...*, Nov 2023, rev. Oct 2026. Fetched with curl from `www.ti.com/lit/ds/symlink/bq25756e.pdf` this round (`datasheets/BQ25756E_ds.*`).
  - Used only to check how the BQ25756EEVM's IC differs. Diffed against [DS] on abs max, operating range, internal OVP, deglitch, watchdog, VAC_DPM and ILIM_HIZ.
- **[UG]** TI SLUUCT7D, *BQ25756EVM* user's guide, May 2023, rev. May 2025 (33 pp.):
  - Table 2-1 defaults, Table 2-3 connectors, Table 2-4 jumpers, Table 2-5 ROC;
  - Figure 3-1 schematic (pp.15-17, read from 300/500 dpi renders `r2/bq756/sch-15.png`, `sch-16.png`, `sch-17.png`, `in.png`, `ic.png`, `out.png`, `right.png`);
  - Table 3-1 BOM (pp.22-25).
- **[UGE]** TI SLUUCY5A, *BQ25756EEVM* user's guide, Nov 2023, rev. May 2025: Table 2-1, Table 2-2, BOM.
- **[TIstore]** ti.com, fetched with plain curl on 2026-11-05 at 18:14 UTC:
  - `storeservices/cart/opninventory?opn=...`;
  - `www.ti.com/tool/BQ25756EVM` and `/tool/BQ25756EEVM` (`data-price`).
- Board facts come from the task brief, `docs/reviews/charger_eval_2026-11-05/spec.md` ([SPEC]), `r2/loop_analysis.md` ([LOOP]) and `r2/regen_dynamics.md` ([REGEN]). [LOOP] and [REGEN] are round-2 analyses, not primaries. The RT1987 numbers are from [SPEC], which cites DS-00.
- Anything a primary does not state is marked **UNKNOWN** or **BENCH**. Snippets and recollection are never used.

## 1. Verdict

**FEASIBLE_WITH_CONDITIONS.** The FC-charging requirement is fully proven on paper. Regen harvesting is not yet proven: it depends on bench gates that decide whether this IC can be both loop-proof and warm.

### 1.1 What the primaries prove
- **Common ground with high-side sensing on both sides.**
  - EVM J1-1 and J3-2 are both PGND.
  - R2 (5 mΩ) senses in VIN+; R24 (5 mΩ) senses in BAT+.
  - There is no BATFET, no NVDC system node, and no input FET. Q5/Q6 and Q7/Q8 are DNP.
- **Hardware ceilings that hold through POR.**
  - Charge voltage is set by the FB divider.
  - Charge current is set by the ICHG resistor.
  - Input current is set by the ILIM_HIZ resistor.
- **Four independent hard-stop pins:**
  - /CE high;
  - ILIM_HIZ above 3.7 V (HIZ);
  - ACUV pulled below 1.1 V (VAC_UVP, 100 µs nominal enter deglitch);
  - ACOV pulled above 1.2 V (VAC_OVP, 100 µs).
- **An input-voltage-regulation register that is NOT re-measured or auto-reset.** This is the key difference from BQ25713/720/798.
  - VAC_DPM is 4.2-65 V in 20 mV steps, ±2 % at 19 V.
  - Only REG_RESET or POR resets it. The watchdog does not.
  - It can sit at 19.9 V, which is 19.50-20.30 V worst case. That is entirely above the TPS61288 OVP maximum of 19.5 V, which the BQ25713/720 cannot reach (19.52 V register cap).
  - It can sit at 15 V for FC mode.
- **Ratings and readback.**
  - 85 V absolute maximum, 70 V operating, 2-13 cell on the EVM.
  - I2C ADC readback of IBAT (2 mA LSB), IAC (0.8 mA), VAC and VBAT (2 mV), plus status and fault registers.
- **Availability.** The TI store has 114 units at USD 208.95.

### 1.2 What keeps it from "proven"

1. **Regen warm response and its compatibility with the loop backstop (H4, BENCH).**
   - The always-powered regen mode needs the converter switching, or at least REGN up, while V-MOT sits at bus level. That requires /CE low, EN_CHG = 1, not in HIZ, and ACUV above its UVP.
   - Every hard-stop pin above turns REGN or the converter off, and the exit is a **cold start**:
     - the ACUV/ACOV exit deglitch is 12 ms (DS §5.6);
     - the converter "toggles the SW node for about 40 ms" at startup (DS §6.3.3.3);
     - the typical /CE-enable to current delay is about 145 ms (Fig 7-7, 40 ms/div);
     - the typical VAC plug-in to current delay is about 175 ms (Fig 7-3).
   - [REGEN] requires τ_warm ≤ 4 ms on the unmodified board. So the [LOOP] comparator H1 **cannot gate any of these pins per burst** without forfeiting regen capture.
   - Three gating options exist. Each is bench-gated (section 5.4):
     - **W1:** gate ACUV. Loop-proof, but cold, so regen fails.
     - **W2:** an analog warm inhibit, holding ILIM_HIZ at about 3.0 V (inside the 2.0-3.7 V input-current-regulation band). Off-label and unmeasured.
     - **W3:** the comparator becomes a latched fault detector, AND-ed with the ILIM_HIZ input-current monitor voltage, and trips ACUV. Warm, with the loop bounded to one pulse. This departs from the [LOOP] "permit" formulation and needs its author's sign-off.
   - The VDPM loop bandwidth, and whether the converter keeps switching in VDPM at zero charge current, are not in [DS].
2. **The stock EVM is not fail-safe (H3).**
   - JP13 ties /CE to PGND, so charging is enabled.
   - The FB divider is 29.4 V (7S).
   - ICHG is 10 A hardware and ILIM is 8 A hardware.
   - At POR the IC is in default mode with EN_CHG = 1, so it **charges autonomously with no host**.
   - Fixed by the mods in section 6.
3. **Input capacitance is a datasheet requirement, not an option (H8).**
   - [DS] §5.3 requires C_IN ≥ 80 µF after derating.
   - The stock EVM carries about 217 µF nominal (168 µF of it polymer). At the RT1987 12 mA/µF ramp that draws about 2.6 A, which exceeds both the OC_FC 1.4 A latch and the RT1987 start-up SCP of 2.5 A.
   - Even the 80 µF floor plus the board's 20 µF draws about 1.2 A. With aux current that is about 1.35 A on an FC-only bus, a 3.6 % margin.
   - **A cold energization through D-BC-FC must therefore be forbidden by sequencing** (section 7, rule S1). The charger is energized only by co-ramping with MOT_PWR during the low-voltage bring-up, and stays powered through Run.
4. **The charger's own watchdog is a slow layer only.**
   - The minimum setting is 40 s, with no tolerance given; at the 160 s setting, 130 s is the minimum (DS §5.6).
   - With EN_CHG_BIT_RESET_BEHAVIOR = 0, expiry stops charging.
   - It does not meet the about 5 s host-silence row in [SPEC]. **The MCU hardware watchdog is therefore required** (section 8).
5. **There is no zero-current register.**
   - ICHG_REG is "Clamped Low" at 400 mA (DS Table 6-10).
   - Inhibit relies on pins or bits (CE, EN_CHG, HIZ, ACUV/ACOV), not on ChargeCurrent = 0.
6. **The sibling BQ25756EEVM uses a different IC (BQ25756E, [DSE]).**
   - 60 V absolute maximum, 36 V operating, internal VAC OVP 36 V typical.
   - R2 is 2 mΩ input sense; the FETs are 60 V AONS66614.
   - It also works electrically, but every register/threshold citation in this dossier is to [DS] (the BQ25756). **Order the BQ25756EVM.**

## 2. Requirement matrix

| Req | Status | Evidence (primary citation) | Bench test that closes it |
|---|---|---|---|
| **H1** common ground, sense placement | PROVEN_DATASHEET | §3.1 | B0 continuity |
| **H2** hard inhibit while powered | BENCH_GATE (mechanisms proven; latency only nominal) | §3.2 | **B2** inhibit latency ≤ 290 µs |
| **H3** fail-safe (a)-(d) | PROVEN_CALC with EVM mods (FAIL as shipped) | §3.3 | B1 dead-MCU check |
| **H4** input-voltage threshold, always-powered regen | BENCH_GATE | §3.4, §5 | **B3** retention, **B4** warm response, **B5** bus-level draw, **B10/B11** W2/W3 |
| **H5** FC-charging mode | PROVEN_DATASHEET | §3.5 | B9 CV at the pack |
| **H6** voltage ratings, ACOV | PROVEN_DATASHEET | §3.6 | M-R2 (true V-MOT peak) |
| **H7** battery pin behind D-BT-SQ | PROVEN_DATASHEET (trickle current value UNKNOWN) | §3.7 | B7 |
| **H8** inrush / hot-plug | PROVEN_CALC with EVM rework plus sequencing rule S1 (FAIL as shipped) | §3.8 | **B6** |
| **H9** I2C / logic / status pin | PROVEN_DATASHEET with EVM mods (unpowered leakage UNKNOWN) | §3.9 | B8 |
| **H10** thermal / efficiency / wiring / mechanical | BENCH_GATE (ratings ample; no 2S efficiency data) | §3.10 | B12 |
| **H11** availability | PROVEN_DATASHEET (TI store) | §3.11 | - |
| **H12** telemetry | PROVEN_DATASHEET | §3.12 | - |

## 3. Requirement detail

### 3.1 H1: common ground, sense placement, no unregulated path

**Ground.** [UG] Fig 3-1 p.15:
- J1 (TB005-762-02BE) pin 1 = PGND (input) and pin 2 = VIN.
- J3 pin 1 = VOUT/BAT and pin 2 = PGND.
- One PGND net throughout (pp.15-17).
- U1 thermal pad pin 37 = PGND.
- The board side has VIN- = VBAT- = GND, which matches.

**Input sense.** R2 is 5 mΩ (WSL25125L000FEA, BOM item 33), in VIN+ between the VIN/C44/C7 node and VSYS (ACP/ACN via R5/R6 10 Ω, C34 470 nF).
- [UG] Table 2-1 note 1: "current EVMs are built with a 5mΩ".

**Charge sense.** R24 is 5 mΩ 5 W (FCSL110R005FER, item 38), in BAT+ between P_OUT (C57) and J3-1 (SRP/SRN via R22/R25, C35).
- [DS] §7.2.1.2.7: "The battery current sense resistor between SRP and SRN is fixed at 5mΩ".

**Nothing sits in the return path.**

**Unregulated paths.** The power stage is four N-FETs (SIR680LDP, item 32): Q1/Q2 on SW1 and Q3/Q4 on SW2.
- Q1's drain is on VSYS and its source on SW1, so its body diode conducts SW1→VSYS only.
- Q3's drain is on P_OUT and its source on SW2, so its body diode conducts SW2→P_OUT only.
- With switching stopped there is therefore no DC path VIN→BAT and none BAT→VIN, unlike the TPS61288 passthrough.
- All bypass parts are DNP ([UG] p.15, `right.png`):
  - Q5/Q6 (input back-to-back FETs) are DNP and bridged by R1000/R1001 0 Ω;
  - the Q7/Q8 VSYS↔P_OUT power-path FETs are DNP;
  - R1004/R1005, R1002/R1003 and D8 are DNP.
- **They must stay unpopulated.**

### 3.2 H2: hard inhibit while powered

| # | Mechanism | Stops | Latency (primary) | POR default |
|---|---|---|---|---|
| 1 | **/CE pin HIGH** (VIH 1.3 V, VIL 0.4 V; DS p.13) | Charging; REGN is not enabled unless charge is enabled (DS §6.3.3, §6.3.3.2) | Typical only: Fig 7-8 shows I_CHG to 0 within one scope sample (0.4 ms at 2.5 kS/s, 40 ms/div). **Below plot resolution, so not a spec** | Pin-defined. EVM: JP13 to GND = enabled |
| 2 | **EN_CHG = 0**, REG0x17[0] | Same | Not specified. Fig 7-6 (I2C disable) has the same resolution | 1 (enabled) |
| 3 | **ILIM_HIZ > V_IH 3.7 V min** (DS p.10) → HIZ | Switching **and REGN** (DS §6.3.3.6) | Not specified | Pin-defined. EVM: R66 2.49 kΩ to GND = not HIZ |
| 4 | **EN_HIZ = 1**, REG0x17[2] | Same | Not specified | 0. **Reset by WATCHDOG and by "Adapter Plug In"** (Table 6-20), so it is not a reliable latch |
| 5 | **ACUV pulled below V_REF_ACUV 1.095-1.106 V** → VAC_UVP, "stops the converter" (DS §6.3.3.1, §6.3.9.1.2) | Converter; PG goes high | **t_ACUV_DGL = 100 µs nominal** (DS §5.6; no min/max). Exit 12 ms | Divider-defined |
| 6 | **ACOV pulled above V_REF_ACOV 1.184-1.206 V** → VAC_OVP | Converter | **t_ACOV_DGL = 100 µs nominal**. Exit 12 ms | Divider-defined |
| - | ChargeCurrent = 0 | **Not available**: ICHG_REG range 400-20 000 mA, "Clamped Low" (Table 6-10) | - | 20 000 mA (pin-limited) |

**Does an inhibit stop all current into the battery pin?**
- Yes. The IC has no BATFET, no NVDC/supplement mode and no system path (block diagram, DS §6.2).
- Trickle and pre-charge are phases of the charge cycle, so they follow /CE, EN_CHG and HIZ (DS §6.3.4.1: a cycle starts only if not HIZ, REGN OK and EN_CHG = 1 and /CE LOW).
- The only battery-pin currents with charging off flow *out of* the battery: the 16 mA I_BAT_LOAD discharge sink (on during BAT_OVP or EN_IBAT_LOAD) and IQ_BAT.
- Behind D-BT-SQ even these drain only VCHG.

**MPPT.** EN_MPPT must stay 0 (POR 0, REG0x1A). A full panel sweep "momentarily enters HIZ" (DS §6.3.5.1.2.1).

**Reverse mode.** EN_REV must stay 0.
- POR 0, and it is also reset by WATCHDOG and Adapter Plug In (Table 6-22).
- D-BT-SQ in any case keeps the pack off the charger's BAT pin, so reverse mode has no pack to draw from.

**Status: BENCH_GATE.**
- The mechanisms are proven.
- Only the ACUV/ACOV deglitch has a datasheet figure, and it is nominal: 100 µs, against the [LOOP] budget of 290 µs × (1.5 A / I_in).
- Gate **B2**.
- The pin mechanisms (1, 3, 5, 6) meet [LOOP] C1. The register mechanisms (2, 4) do not.

### 3.3 H3: fail-safe

**(d) POR defaults** (DS §6.4.1, Tables 6-9 to 6-22):
- the IC starts in **default mode**, with the watchdog already expired;
- EN_CHG = 1, EN_HIZ = 0, EN_REV = 0, EN_MPPT = 0;
- ICHG_REG = 20 A, so the ICHG pin is the limit;
- VFB_REG = 1.536 V, so the FB divider sets CV;
- VAC_DPM = 4.2 V, so the ACUV pin floor governs;
- IPRECHG = 4 A, limited to 20 % of the ICHG pin;
- ITERM = 2 A, or 10 % of the pin if lower;
- 12 h safety timer, 2 h pre-charge timer.

"In default mode, the device keeps charging the battery" (§6.4.1).

**So yes: with /CE low and not HIZ, it charges by itself out of reset at the hardware pin limits.** On the stock EVM those limits are 10 A (R67 4.99 kΩ), 8 A input (R66 2.49 kΩ) and 29.4 V CV (R28 249 kΩ / R64 13.7 kΩ). Hence:
- the FB divider and both resistor ceilings must be changed (mods M1-M3). They then bound even autonomous operation to 2S CV, 2.6 A and the chosen input limit.
- /CE and the hard-inhibit stage must default to "off" in hardware (mods M5, M6).

**(a) Teensy in reset or pins high-Z.**
- Layer 1: every RT1987 EN has a 10 kΩ pull-down, so the charger is unpowered (unless REGEN is closed in the always-powered design: a reset opens it).
- Layer 2 with the mods:
  - **/CE:** JP13 removed. The existing R56 (10.0 kΩ) pulls /CE up to 3V3_PULLUP. That rail is the EVM's LT3010 LDO (U2), fed from VAC through D10/R46, or from BAT through D9 ([UG] p.17). It exists whenever the charger has input, independent of the Teensy. The Teensy (or PERMIT) pulls /CE low through an added N-FET whose gate has a 100 kΩ pull-down.
  - **Hard stop:** the ACUV pull-down stage (M6) is biased from VAC, so it is ON by default.
  - Result: dead MCU = /CE high plus VAC_UVP = no charging.

**(b) Teensy hung with pins latched.**
- The [LOOP] H1/H2 comparators still gate (if the warm-gating option keeps them in the path, section 5.4).
- The charger I2C watchdog (REG0x15[5:4]) is 40/80/160 s. On expiry it resets EN_CHG to the value of EN_CHG_BIT_RESET_BEHAVIOR (REG0x17[3]). Firmware writes that bit to 0 at configuration, so expiry **stops charging**. The bit itself survives the watchdog: it is reset only by REG_RESET.
- Expiry also resets ICHG_REG to 20 A (pin-limited), EN_HIZ to 0 and ADC_EN to 0. **VAC_DPM is NOT reset by the watchdog** (Table 6-12).
- 40 s ≫ the [SPEC] 5 s row. **The MCU RTWDOG (section 8) is what turns a hang into case (a).**
- Residual: a hung Teensy holding /CE low, followed by a charger POR (V-MOT brown-out), restores default mode with EN_CHG = 1. Only the comparators, the hardware ceilings and the MCU watchdog cover this.

**(c) I2C dead or stuck.**
- The IC frees its I2C after START is held for more than 2 s (DS §6.3.10.2).
- Charging state is unchanged until the watchdog expires (≥ 40 s, then EN_CHG = 0 if configured).
- /CE, ACUV and the comparators are I2C-independent.
- Firmware rule: on any I2C failure, drop PERMIT/P5, which drives /CE high and the ACUV stop.

**Pull resistors for "dead MCU = no charging":**
- /CE: keep R56 (10 kΩ to 3V3_PULLUP), remove JP13, add the N-FET with a 100 kΩ gate pull-down.
- Hard-stop stage: ACUV N-FET with its gate pulled up from a VAC-derived 5.1 V zener node through 100 kΩ.
- Not used as the default inhibit: ILIM_HIZ HIZ. It needs ≥ 3.7 V, above the Teensy's 3.3 V, and REGN collapses in HIZ, so a REGN-referenced pull-up would release itself.

**Status: PROVEN_CALC with mods (FAIL as shipped).** B1 closes it.

### 3.4 H4: input-voltage threshold, always-powered regen

**Register.** REG0x08 VAC_DPM, bits 13:2:
- 4200-65000 mV in 20 mV steps, POR 4.2 V;
- "Reset by: REG_RESET" only (Table 6-12, DS p.40). Not reset by the watchdog, by HIZ or by Adapter Plug In (contrast EN_HIZ/EN_REV);
- accuracy ±2 % at 19 V (code 0x3B6), 25 V and 38 V (DS p.10). **No accuracy is given at 15 V.**

**Hardware floor.** The ACUV pin sets V_ACUV_DPM = 1.198-1.222 V (±1 %) × divider. "Regulates VAC to the higher of VAC_DPM register or ACUV" (DS §6.3.3.1, §6.3.5.1.2).
- **Constraint:** the same pin sets the UVP, and the ratio between them is fixed. UVP falling = 1.1/1.21 × floor = 0.909 × floor; UVP rising = 0.950 × floor.
- A floor that is POR-safe above the 16.0 V bus (for example 16.9 V) would put the UVP rising at 16.06 V, right at the bus. The converter would then be off, or hovering, in cruise and cold for every burst.
- **So the hardware floor cannot both survive a POR above the bus and keep the converter warm.**
- Proposed divider (M4): floor 13.19 V (13.06-13.32 V), UVP falling 11.99 V (11.94-12.06 V), UVP rising 12.54 V, ACOV 25.86 V.
- The POR case is then covered by the comparator, not by the threshold (section 5).

**Placement:**

| Setting | Code / register value | Worst case | vs bus 16.0 / fw latch 17.5 | vs TPS61288 OVP 18.3/19/19.5 | vs clamp 21.4 (VESC cut 21.35) |
|---|---|---|---|---|---|
| Regen 19.0 V | 950 / 0x0ED8 | 18.62-19.38 V | +1.12 V over 17.5 | +0.32 V over 18.3 min; below 19.5 max | ≥ 1.97 V headroom |
| Regen 19.9 V | 995 / 0x0F88 | 19.50-20.30 V | +2.0 V | **≥ OVP max**: a failed-FB boost cannot reach it | 1.05 V headroom (shrinks the warm-response window; [REGEN] fig4) |
| FC mode 15.0 V | 750 / 0x0BB8 | ±2 % assumed, **not specified at 15 V** | 0.9 V below 15.9 V | - | - |

- It is programmable at runtime over I2C (16-bit little-endian, multi-write; DS §6.3.10).

**Draw at or just under the threshold.**
- IQ_VAC is 0.75 mA typical / 1 mA maximum, *not switching* (DS p.8).
- With the converter running and VDPM holding charge current at about 0: **not specified**.
- The EVM housekeeping draws extra from VAC: the LT3010 LDO, the LEDs D4-D6 through 2.21 kΩ, and the 1.1 MΩ ACUV/ACOV divider. This is a load on the bus, not energy into the pack.
- Gate **B5**.

**Warm response.**
- **Not specified.** No VDPM-loop bandwidth or transient data appears in [DS]; the compensation is internal and auto-selected at startup (§6.3.3.3).
- VDPM is a regulation loop with no deglitch. As long as V-MOT stays inside the ACUV/ACOV window (UVP ≤ 12.06 V, far below any Run V-MOT), a dip below VAC_DPM **does not re-run qualification**.
- Leaving the window does re-run it: the 12 ms exit deglitch, then restart.
- Unknown whether, at zero charge current in VDPM, the converter keeps switching (PFM; or "fixed-frequency DCM" when EN_PFM = 0, REG0x19[5]) or idles in a state that restarts slowly.
- Gate **B4** (= [REGEN] M-R4): step VAC from VAC_DPM − 0.5 V to VAC_DPM + 1 V from a stiff source with the charger warm. Pass: τ63 ≤ 4 ms (10-90 % ≤ 9 ms), relaxing per [REGEN] if C_VMOT ≈ 4 mF or the VESC cutoff is raised.

**Status: BENCH_GATE.**

### 3.5 H5: FC-charging mode

- **Source.** VBUS about 15.9 V via D-BC-FC, with VAC_DPM = 15.0 V written over I2C. That is above the 13.19 V hardware floor, so the register governs.
- **Charge current.** ICHG_REG 400-20 000 mA in 50 mA steps. 2.5 A = code 50 = 0x00C8.
  - Accuracy ±5 % at 2 A (code 0x28), ±3 % at 5 A and 15 A (DS p.8).
  - Hardware ceiling: R_ICHG = 20.0 kΩ gives 2.40-2.60 A (K_ICHG 48-52 A·kΩ, DS p.8, eq. 4; R_ICHG ≤ 100 kΩ, ROC).
- **Input limit.** IAC_DPM 400-20 000 mA in 50 mA steps (5 mΩ), for the FC budget of about 1.10 A at standstill ([SPEC] §2).
  - Accuracy is specified only at 5/10/20 A with 2 mΩ (DS p.9).
  - The ILIM_HIZ hardware ceiling is K_ILIM × (2/5) / R. With 5 mΩ that is 20 A·kΩ / R: 15.4 kΩ gives 1.30 A and 20.0 kΩ gives 1.00 A (DS §6.3.5.1.1.1, §7.2.1.2.7).
- **CV.**
  - V_FB accuracy is ±0.5 % at 0-85 °C and ±0.7 % at −40 to 125 °C (DS p.8). Use 0.1 % divider parts (DS §7.2.1.2.2).
  - For 8.4 V: R_BOT = 249 kΩ × 1.536/(8.4 − 1.536) − 33 Ω = 55.69 kΩ.
  - Fitting 55.6 kΩ 0.1 % gives 8.411 V at VFB_REG 1.536 V; trimming to 1.534 V (REG0x00 code 0x0F, 2 mV step) gives 8.400 V.
  - Worst case is about ±0.7 % plus the resistors, so 8.33-8.47 V. Recommend targeting 8.35-8.38 V.
  - The pack sits 35-50 mV lower through D-BT-SQ (section 3.7).
- **Termination.** ITERM 250-10 000 mA, ±50 % at 0.25 A (DS p.9), or 10 % of the ICHG pin value (0.25 A with 20 kΩ).
  - Termination is disabled while in DPM (§6.3.4.4).
  - Disable PFM when ITERM < 2 A (§6.3.3.4).
- The actual FC charge current is limited by the FC budget (EMS), not by the charger.

**Status: PROVEN_DATASHEET.**

### 3.6 H6: voltage ratings, OVP

- **Ratings.**
  - Absolute maximum: VAC/ACP/ACN/SRP/SRN/FB 85 V; SW1/SW2 85 V (−4 V for 40 ns) (DS §5.1).
  - Operating VAC 4.2-70 V.
  - Internal VAC_OVP 72-76 V.
  - ACOV is programmable.
- **EVM parts.** Input ceramics 100 V (GCJ32DC72A475KE01L, C3225X7R2A106K250AC); polymer 80 V (80SXV56M); FETs 80 V. C34/C35 are 16 V, but they sit across the sense resistors (differential, ≤ 0.3 V absolute maximum per DS).
- **[DSE] BQ25756E.** 60 V absolute maximum, 36 V operating, internal OVP 36 V typical / 33 V falling. Still ample.
- **At OVP.** Above V_REF_ACOV the converter stops after 100 µs and resumes when VACOV falls, after a 12 ms deglitch (DS §5.6, §6.3.9.1.1). That would be a **mid-burst drop-out** if ACOV were set inside the burst range.
  - The proposed ACOV is 25.9 V, above the 21.4 V clamp plus overshoot.
  - Board limit: C-D8/C-D10 are 25 V parts ([SPEC] §2), so replace them with ≥ 35 V parts regardless.

**Status: PROVEN_DATASHEET.** M-R2 confirms the true V-MOT peak.

### 3.7 H7: battery pin through D-BT-SQ

- **No BATFET, no NVDC, no battery-presence latch.** Overvoltage and load removal are handled by BAT_OVP (104 % of VFB_REG), with a one-cycle stop and a 16 mA SRN sink (DS §6.3.9.1.3).
- **Start from about 0 V.** With VCHG at about 0 V (D-BT-SQ blocks the pack):
  - trickle charge while V_SRN < V_BAT_SHORT (2.8-3.2 V rising). **The trickle current value is not given in [DS]**: I_BAT_SHORT appears in Fig 6-3 without a number;
  - then pre-charge at the lower of IPRECHG and 20 % of the ICHG pin (0.5 A with 20 kΩ) until V_FB > V_BAT_LOWV (71.4 % default, 6.0 V for 8.4 V);
  - then CC. VCHG rises into C_OUT until D-BT-SQ conducts at VBT + 35 mV, after which VCHG ≈ pack.
- **D-BT-SQ open (pin 32 LOW).** CV is reached into the caps only. Termination follows (converter off, §6.3.4.4), then auto-recharge below VRECHG after the 200 ms deglitch. This is a benign hiccup.
- **No bias drain.** Without VAC, bias needs SRN > 3 V (DS §6.3.1/§6.3.2). VCHG is about 0 V, so the IC is fully off: no pack drain.
- **CV sensing.** The FB divider R28/R64 senses the EVM BAT node, upstream of the leads and D-BT-SQ.
  - The pack is low by the D-BT-SQ forward regulation (35 mV, or 20 mΩ × I = 50 mV at 2.5 A, per [SPEC]/RT DS-00) plus lead drop (about 10 mV).
  - That undercharge (≤ 0.7 %, tapering toward 35 mV) is conservative and acceptable. A small VFB_REG trim can recover it.
- **D-BT-SQ must NOT be bridged.** Bridging puts the pack on SRN, which gives:
  - battery-only bias and ADC drain (IQ_BAT up to 700 µA with the ADC on);
  - reverse mode becomes physically possible (bus back-feed from the pack, gated by one register bit);
  - I_BAT_LOAD can drain the pack.

  D-BT-SQ is a structural loop barrier for this IC.

**Status: PROVEN_DATASHEET** (the trickle value is UNKNOWN and immaterial). B7 closes it.

### 3.8 H8: inrush / hot-plug

**EVM input capacitance on the ramped node.** There is no ACFET/RBFET: Q5/Q6 are DNP, bridged by R1000/R1001. So **all of it** sits on the RT1987-ramped node, and nothing is hidden behind an input FET. From [UG] pp.15-16:

| Group | Parts | Nominal |
|---|---|---|
| Ceramic | C2, C5, C8 (4.7 µF 100 V X7S); C4, C42, C150 (10 µF 100 V X7R); C16, C81 (1 µF); C10, C11, C19, C80 (0.1 µF); C13 2.2 µF in series with R10 10 Ω (damper) | 48.7 µF |
| Polymer | **C44, C7, C70: 56 µF 80SXV56M** | 168 µF |
| **Total** | | **about 217 µF** |

**Stock-EVM inrush.** At 12 mA/µF ([SPEC] §6), 217 µF draws about 2.6 A for about 1.3-1.75 ms. That is above OC_FC (1.4 A, single sample) and above the RT1987 start-up SCP (2.5 A for 250 µs, then a 64 ms restart, per [SPEC]). **FAIL as shipped**, and Death-5 class through D-BC-FC.

**The datasheet floor.** C_IN ≥ 80 µF after derating (DS §5.3; [DSE] the same).
- (80 + 20) µF × 12 mA/µF = 1.20 A, plus I_aux 0.15 A = **1.35 A against 1.4 A**.
- A cold FC-path energization is therefore unacceptable at *any* compliant capacitance.

**Resolution:**
- **(i) Rule S1.** The charger input is energized only via D-BC-RG while V-MOT co-ramps during the existing low-voltage MOT_PWR pre-charge bring-up (the Death-5 practice). /CE stays high and ACUV is held stopped, so it does not switch during the ramp. The input then stays energized through Idle and Run.
- **(ii) Regen→FC transitions** open D-BC-FC onto an input already at about V-MOT ≈ VBUS. Discharge in a ≤ 10 ms gap is about 3 mA / 100 µF ≈ 30 V/s, so ≤ 0.3 V, and the inrush is negligible.
- **(iii) Rework (M10).** Remove the polymer C44/C7/C70 and fit ceramics on the existing 1210 sites (C5, C8, C60, C3, C4, C42, C150, C6, C2) to reach 80-100 µF *effective* at 16-21 V. This keeps the V-MOT sag on D-BC-RG closure and the RT1987 SCP margin reasonable.
  - Effective capacitance needs DC-bias curves (missing primary) or a measurement.
- **(iv) Firmware.** Forbid FC_CHARGE when V_chg (pin 38) < V_bus − 1 V.

The output caps (C57, C38, C39 at 56 µF; ceramics on P_OUT) sit behind D-BT-SQ, which blocks pack→VCHG, so there is no output inrush.

**Status: PROVEN_CALC with rework plus S1.** Gate **B6**.

### 3.9 H9: I2C, logic, status pin

**Address and levels.**
- Address 0x6B, fixed (DS §6.3.10). It is the only device on the Teensy bus once the Ag105 (0x30) is gone.
- 100 k / 400 k / 1 MHz.
- V_IH 1.3 V, V_IL 0.4 V, leakage ≤ 1 µA at a 3.3 V pull-up (DS p.13). 3.3 V compatible.
- Logic pins are 6 V absolute maximum.

**Back-powering.** The EVM pulls SCL/SDA up to its own 3V3_PULLUP through R53/R54 (10.0 kΩ, via R69 0 Ω; [UG] p.17).
- When the charger is unpowered, the Teensy's RSDA/RSCL would source into a dead rail and the LED loads.
- **Remove R53 and R54** and keep the board pull-ups.
- Unpowered BQ25756 SDA/SCL/INT/STAT leakage is **not specified**. Gate B8.

**Pin 6 (CHARGER_STAT).**
- Repurpose it to **/INT**: open-drain, active-low 256 µs pulse on PG change, DPM entry, CHARGE_STAT change, faults, watchdog (DS §6.3.8.3).
- Use a falling-edge interrupt with a Teensy-side 10 kΩ pull-up, and remove JP14 (the EVM pull-up).
- Alternatives: STAT1 (charging = ON, Table 6-6) or /PG (pin 40 V absolute maximum, LOW = input in window).

**Pin 5.** Becomes P5 (the PERMIT input of the [LOOP] logic, which drives the /CE N-FET).

**Status: PROVEN_DATASHEET with mods.**

### 3.10 H10: thermal, efficiency, wiring, mechanical

**Ratings.** The EVM is rated 10 A / 400 W ([UG] Table 2-5), with 2 oz × 6 layers, IHLP6767GZ 10 µH (16.5 A, 12 mΩ) and SIR680LDP FETs.
- 2.5 A × 8.4 V = 21 W charging, and about 23 W input in regen, is about 5 % of rating.
- Inductor time constant 10 µH / 12 mΩ = 0.83 µH/mΩ, inside 0.05-1.26 (DS §7.2.1.2.4).

**Efficiency.** [DS] Figs 5-1 to 5-3 cover only 5S, 7S and 10S batteries. **There is no 2S data.** Gate B12.

**REGN LDO dissipation** = (V_AC − 5 V) × Q_G(TOT) × f_SW (DS §6.3.3.2). The SIR680LDP Q_G is not in hand.

**Mechanical.**
- The board is 112 × 84 mm, 5 mm maximum component height ([UG] Table 2-2). It cannot sit on the 25.00 mm-row Ag105 footprint ([SPEC] §7).
- Mount it off-board on standoffs beside the CHG footprint and wire:
  - VIN+ pad (pin 10) → J1-2; VIN− → J1-1;
  - VBAT+ pads (18, 19) → J3-1; GND → J3-2.
- Keep the input pair short and twisted (≤ about 10 cm). The 12 mA/µF ramp, and the integrated compensation that auto-selects at startup, both favour low lead inductance.

**Status: BENCH_GATE (low risk).**

### 3.11 H11: availability (2026-11-05, 18:14 UTC)

**TI store [TIstore]:**

| EVM | Price | Inventory |
|---|---|---|
| BQ25756EVM | USD 208.95 | **114** |
| BQ25756EEVM | USD 208.95 | **91** |

- The 114 and 91 figures from the task brief were re-checked with curl and match.
- Lead time is not published for in-stock units.
- Mouser and Farnell could not be reached (curl HTTP/2 INTERNAL_ERROR), so their price, stock and lead time are **UNKNOWN**.
- No EV2400 or USB2ANY is needed, because the Teensy is the host.

**Status: PROVEN_DATASHEET.**

### 3.12 H12: telemetry

All channels are 16-bit, and readings are "only valid for DC states and not for transients" (DS §6.3.7):

| Register | Quantity | LSB / range |
|---|---|---|
| 0x2F IBAT_ADC | Battery current | 2 mA LSB, ±20 A, two's complement (5 mΩ) |
| 0x2D IAC_ADC | Input current | 0.8 mA LSB with 5 mΩ |
| 0x31 VAC_ADC | Input voltage | 2 mV |
| 0x33 VBAT_ADC | Battery voltage | 2 mV |
| 0x37 TS, 0x39 VFB | Thermistor, feedback | - |

- **Conversion time** per channel: 24 / 12 / 6 ms at 15 / 14 / 13 bits (DS p.12). With continuous conversion on IAC + IBAT + VAC at 13 bits, that is about 18 ms per cycle, about 55 Hz. That is enough for EMS at 50 Hz, but **too slow for the J-guards G1/G2 (5-20 ms)**, which stay on the board's INA253s and ADCs.
- **G3** maps to REG0x24 Fault_Status: VAC_UV, VAC_OV, IBAT_OCP, VBAT_OV, TSHUT, CHG_TMR, DRV_OKZ.
- **Charge state:** REG0x21 CHARGE_STAT, VAC_DPM_STAT, IAC_DPM_STAT, WD_STAT; REG0x22 PG_STAT, TS_STAT.
- **Analog option:** the ICHG and ILIM_HIZ pin voltages are proportional to charge and input current in real time (DS eqs. 5 and §6.3.5.1.1.1). They could feed spare Teensy ADC pins, entered in the IO CSV first.

**Status: PROVEN_DATASHEET.**

## 4. Register map excerpts (DS §6.5)

| Addr | Field | Bits | POR | Reset by | Use |
|---|---|---|---|---|---|
| 0x00 | VFB_REG | 4:0 | 0x10 = 1536 mV (1504-1566 mV, 2 mV) | REG_RESET | CV trim |
| 0x02/03 | ICHG_REG | 10:2 | 0x190 = 20 A (0.4-20 A, 50 mA, clamped low) | REG_RESET, **WATCHDOG** | Charge current (pin-limited) |
| 0x06/07 | IAC_DPM | 10:2 | 0x190 = 20 A (5 mΩ) | REG_RESET | FC budget |
| 0x08/09 | **VAC_DPM** | 13:2 | 0xD2 = 4.2 V (4.2-65 V, 20 mV) | **REG_RESET only** | Regen 19.0/19.9 V, FC 15.0 V |
| 0x10 / 0x12 | IPRECHG / ITERM | 9:2 | 4 A / 2 A | REG_RESET | Lower of register and pin |
| 0x14 | EN_TERM, VBAT_LOWV, EN_PRECHG | | 0x0F | REG_RESET | |
| 0x15 | TOPOFF, **WATCHDOG** (00 off / 40 / 80 / 160 s), EN_CHG_TMR, CHG_TMR, EN_TMR2X | | 0x1D (WD = 40 s) | REG_RESET | |
| 0x17 | VRECHG, WD_RST, DIS_CE_PIN, **EN_CHG_BIT_RESET_BEHAVIOR**, **EN_HIZ**, EN_IBAT_LOAD, **EN_CHG** | | 0xC9 | EN_HIZ: WD + plug-in; EN_CHG: WD (to bit 3) | Inhibit / config |
| 0x18 | EN_ICHG_PIN, EN_ILIM_HIZ_PIN, DIS_PG/STAT, FORCE_STATx | | 0xC0 | Pin enables also by WD | Keep both pins enabled |
| 0x19 | REG_RST, EN_IAC_LOAD, EN_PFM, **EN_REV** | | 0x20 | EN_REV: WD + plug-in | EN_REV = 0 |
| 0x1A | FORCE_SWEEP, P_AND_O_TMR, FULL_SWEEP_TMR, **EN_MPPT** | | 0x20 | REG_RESET | EN_MPPT = 0 |
| 0x21 | ADC_DONE, IAC_DPM_STAT, VAC_DPM_STAT, WD_STAT, CHARGE_STAT[2:0] | | | | |
| 0x24 | VAC_UV, VAC_OV, IBAT_OCP, VBAT_OV, TSHUT, CHG_TMR, DRV_OKZ | | | | G3 |
| 0x2B / 0x2C | ADC control / channel disable | | 0x60 / 0x0A | ADC_EN by WD | |
| 0x3D | PART_NUM = 010, DEV_REV | | 0x12 | | Identity check |

**Configuration sequence** (any write enters host mode and starts the watchdog, §6.4.1). Verify every step by read-back before raising P5.
1. 0x17 ← 0xC0: EN_CHG = 0, EN_CHG_BIT_RESET_BEHAVIOR = 0, EN_HIZ = 0, /CE pin enabled.
2. 0x19: EN_REV = 0, EN_PFM = 0.
3. 0x1A: EN_MPPT = 0.
4. 0x00 trim.
5. 0x02 ← 0x00C8 (2.5 A).
6. 0x06 per mode.
7. 0x08 ← 0x0ED8 (19.0 V) or 0x0F88 (19.9 V) for regen, 0x0BB8 for FC.
8. 0x10 / 0x12.
9. 0x15: WATCHDOG = 40 s, safety timer per test.
10. 0x2B ← 0xA0 (ADC on, continuous, 13-bit); 0x2C ← 0x0E (TS and VFB off).
11. Read back 0x3D.
12. EN_CHG = 1 last.

The Teensy pets WD_RST at ≥ 1 Hz.

## 5. Always-powered regen on this IC: timing in words, and the gating problem

### 5.1 Bring-up (Init, rule S1)
1. P5 LOW, so /CE is high and the ACUV stop is on.
2. During the low-voltage bus ramp, REGEN closes together with MOT_PWR, so VCHG-IN co-ramps with V-MOT.
3. The charger passes VAC_OK at 4.2 V but stays in VAC_UVP until 12.54 V (rising). No switching.
4. Once the bus is settled, firmware writes the configuration and verifies it, then (in Run) raises P5.
5. /CE goes low and the ACUV stop is released. The converter starts: about 40 ms of SW toggling for compensation, then the about 145-175 ms typical start delay from Figs 7-3/7-7.
6. The charger then sits in VDPM, because V-MOT ≈ 16 V is below VAC_DPM = 19 V. The charge current is held at about 0.

### 5.2 Cruise
- V-MOT is about VBUS (D-MT-EN conducting).
- [LOOP] H1 = 0 (V-MOT < 1.067 × VBUS).
- The charger is warm in VDPM. Its draw is the B5 figure.

### 5.3 Regen burst
- V-MOT rises at about 0.11-0.28 V/ms ([REGEN]: 15.9 → 21.2 V in 19-47 ms).
- **t0:** H1 permits at about 17.07 V, which is 1.067 × 16.0 V.
- **t0 + 4-17 ms:** V-MOT crosses VAC_DPM (19 V) and charge current rises with τ_warm (B4). V-MOT then holds near VAC_DPM while the charger absorbs (≤ 2.5 A out, ≤ ILIM in).
- The interval between H1 permitting and VDPM engaging absorbs any warm-inhibit exit latency.
- **End of burst:** V-MOT falls below VAC_DPM, VDPM drives current to 0, then H1 falls at the hysteresis point.
- Abrupt input loss is harmless: D-BT-SQ blocks reverse current, and the four-switch stage has no passthrough.

### 5.4 Where H1 can act on this IC

| Option | H1 drives | Loop proof | Regen warm? | Status |
|---|---|---|---|---|
| **W1** | ACUV pull-down (hard stop, 100 µs nominal) | Physical, as in [LOOP] | **No.** Exit = 12 ms deglitch + restart (≥ 40 ms compensation toggle per §6.3.3.3; typical start delay 145-175 ms) > the VESC trip of 19-47 ms. Regen capture fails unless the VESC cutoff is raised *and* the restart is < 63-75 ms ([REGEN]) | Proven mechanism, fails regen |
| **W2** | ILIM_HIZ held at about 3.0 V (inside 2.0-3.7 V): input-current regulation saturated, so the charge current is driven toward 0 while REGN stays up | Physical if the IAC loop really reaches about 0 A (DCM, no minimum-on-time leak) | Possibly. The loop recovers when the pin is released | **B10**, off-label use |
| **W3** | Latched trip = ¬H1 ∧ (ILIM_HIZ monitor voltage, i.e. I_AC > about 50 mA) → ACUV stop, with a reboot-only latch | Bounded: one pulse ≤ detection + 100 µs deglitch at ≤ I_LIM | Yes. The charger stays warm and VDPM does the cruise blocking | **B2 + B11**, plus a [LOOP] author sign-off |

- In all three options the fail-safe hard stop for a dead MCU or logic (P5/PERMIT LOW) is the ACUV stage plus /CE.
- The FC-window permit [LOOP] H2 also drives the ACUV stop. Its exit latency is irrelevant there.

### 5.5 Regen to FC transition
- [LOOP] §6 order: REGEN LOW, then BT_BUS LOW, then H2 permits, then write VAC_DPM 15.0 V and IAC_DPM to the FC budget and verify, then FC_CHARGE HIGH via `assertFcChargeEnable()`.
- VCHG-IN is still at about VBUS, so there is no inrush (rule S1 (ii)).

### 5.6 FC to regen transition
- FC_CHARGE LOW, then write VAC_DPM 19.0 V and verify, then BT_BUS HIGH, then REGEN HIGH.
- The charger input stays energized through the gap.

### 5.7 Teardown / State 99
- P5 LOW (ACUV stop within 100 µs nominal, then /CE high).
- Then the RT1987s per the existing drain phases.

## 6. EVM modifications (designators from [UG])

| ID | Mod | Purpose |
|---|---|---|
| M1 | R64 13.7 kΩ → **55.6 kΩ 0.1 %**, keeping R28 249 kΩ 0.1 % and JP1. VFB_REG 1.534 V gives 8.40 V (or target 8.35-8.38 V) | 2S CV in hardware (POR-safe) |
| M2 | Open JP4 (R67 4.99 kΩ = 10 A). Fit **R_ICHG 20.0 kΩ** via JP3, or replace R67 | 2.40-2.60 A hardware ceiling (pre-charge 0.5 A, termination 0.25 A) |
| M3 | R66 2.49 kΩ (8 A) → **15.4 kΩ** (1.30 A) for full regen, or **20.0 kΩ** (1.00 A, which also caps regen charge to about 2.1 A at 19 V) | Hardware input ceiling |
| M4 | ACUV/ACOV divider: R21 1.00 MΩ, **R27 133 kΩ → 49.9 kΩ, R30 25.5 kΩ → 51.1 kΩ**. Gives UVP 11.99 V falling, floor 13.19 V, ACOV 25.86 V | Warm at bus level; no mid-burst OVP |
| M5 | **Remove JP13.** Keep R56 10 kΩ to 3V3_PULLUP. Add an N-FET (2N7002 class) drain to /CE (TP21 / JP13-1), source PGND, gate via 1 kΩ from P5/PERMIT, 100 kΩ gate to PGND | /CE fail-safe off |
| M6 | ACUV stop: N-FET drain to ACUV, source PGND, gate pulled up via 100 kΩ from a VAC-derived 5.1 V zener node (VAC via 47 kΩ). A second N-FET pulls that gate low when PERMIT (and the W-option logic) is HIGH | Fail-safe fast hard stop, biased from the charger's own input |
| M7 | Remove **R53, R54** (EVM I2C pull-ups). Wire SCL/SDA/GND from J5 to the Teensy I2C (pins 18/19) | No pull-up back-feed |
| M8 | Remove JP14 (/INT pull-up). Route /INT (J8) to Teensy pin 6 with a Teensy-side 10 kΩ pull-up | Status/interrupt |
| M9 | Remove JP15. Remove R51, R52 (or D5, D6) | Lower housekeeping draw on V-MOT |
| M10 | **Remove C44, C7, C70** (56 µF polymer). Fill the 1210 sites (C5, C8, C60, C3, C4, C42, C150, C6, C2) with X7R ceramics to give 80-100 µF *effective* at 16-21 V (measure) | Meet DS C_IN ≥ 80 µF without the 2.6 A inrush |
| M11 | Keep Q5-Q8, R1002-R1005 and D8 **unpopulated**. Keep JP5/JP6 (TS normal), or wire the pack NTC (J-NTC) per DS eqs. 6-7 | No bypass paths |
| Board | Replace C-D8/C-D10 (25 V) with ≥ 35 V parts ([SPEC]). Add the [LOOP] §9 comparator board (H1, H2, PERMIT) | |

## 7. Firmware deltas specific to this IC

- **S1** (energization only by co-ramp, as above).
- Forbid FC_CHARGE unless V_chg > V_bus − 1 V.
- Configure, then verify by read-back (section 4) before raising P5.
- Pet the WD at ≥ 1 Hz.
- On /INT, read 0x21/0x24/0x25-0x27.
- On WD_STAT = 1, POR evidence (0x08 reads 0x0348) or any read-back mismatch: drop P5 and re-configure.
- Port G1-G3: G3 = 0x24.
- Pin 6 → /INT; pin 5 → P5.
- The fw v37 rev 2 `J` session must become an FC-path session ([LOOP] §13).

## 8. MCU hardware watchdog: REQUIRED FUTURE WORK (operator ruling 5)

- The BQ25756 I2C watchdog (≥ 40 s, EN_CHG reset to 0 when configured) is only a slow third layer. It does not meet the about 5 s host-silence row.
- If Path A proceeds with this charger, the Teensy 4.1 firmware **must add an MCU hardware watchdog**, per [LOOP] §10:
  - RTWDOG primary at about 100 ms (32 kHz clock, TOVAL 3200);
  - WDOG1 at 1.0 s as an independent second timer;
  - WDOG1's output must not be routed to pin 19 (SCL);
  - after a WDT reset, latch `ERR_MCU_WDT` and require acknowledgement before Run;
  - bench proof (M6 in [LOOP]): a forced hang resets within the timeout, with all EN < 0.6 V, PERMIT LOW, /CE high and ACUV stopped.
- Carry this into the future-work list.

## 9. Corrections to round 1

1. **Round 1 screened "BQ25756(E)EVM ... 10 A / 5 mΩ class, oversized; parked as Path B references"** (`docs/charger_replacement_evaluation_2026-11-05.md` §3.1). **Corrected:**
   - charge current is 0.4-20 A in 50 mA steps (DS Table 6-10);
   - 2.5 A is settable by register and by a 20 kΩ R_ICHG hardware ceiling;
   - the 5 mΩ battery sense is fixed by design (DS §7.2.1.2.7);
   - the input sense on current-build EVMs is 5 mΩ ([UG] Table 2-1 note 1).

   "Oversized" is a board-area, cost and C_IN issue, not a functional disqualifier. It is a valid **Path A** candidate (off-board mount).
2. **Round 1 never checked input-voltage regulation for it.** It has VAC_DPM 4.2-65 V / 20 mV / ±2 % at 19 V, not auto-reset, plus an ACUV-pin hardware floor (section 3.4).
3. **"BQ25756(E)EVM" were grouped as one item; the brief calls the EEVM a sibling on the same PCB.** The PCB is the same size (112 × 84 mm, [UG]/[UGE] Table 2-2), but **the IC differs**:
   - BQ25756E ([DSE] SLUSFF4A): 60 V absolute maximum, 36 V operating, internal VAC OVP 36 V typical, 1-7 cell;
   - EEVM R2 is 2 mΩ ([UGE] BOM item 33), the FETs are AONS66614 60 V (item 32), and R27 is not fitted (quantity 0), so the default ACUV is 4.2 V.
4. **[UG] internal inconsistency.** Table 2-1 states ACUV = 10 V. The fitted divider (R21 1.00 MΩ, R27 133 kΩ, R30 25.5 kΩ) gives a UVP of 8.04 V falling and a VDPM floor of 8.84 V by DS eqs. 1-2. ACOV = 54.5 V matches the 55 V entry. Bench-verify.
5. **[DS] internal inconsistency.** The Features list says "400 mA to 20 A with 50 mA/step using 2 mΩ". Table 6-11 and §7.2.1.2.7 say that is the 5 mΩ scaling; with 2 mΩ the range is up to 50 A at 125 mA per code. This dossier uses the 5 mΩ scaling because R2 is 5 mΩ.
6. **[DS] §6.3.5** says inputs "from 4.4 V"; the ROC says 4.2 V. Minor.

## 10. Bench gates

| ID | Test | Pass |
|---|---|---|
| B0 | Continuity J1-1 ↔ J3-2 ↔ U1 pad | < 0.1 Ω |
| B1 | Teensy unpowered, in reset, or P5 LOW, with VAC = 16 V and 21 V from a limited supply | /CE ≥ 1.3 V, ACUV < 1.0 V, no switching, I_IN ≤ housekeeping |
| B2 | Inhibit latency: P5 falls, ACUV stop (and /CE) asserted, while charging at 2.5 A | I_IN < 10 mA within ≤ 290 µs × (1.5 A / I_LIM) |
| B3 | VAC_DPM retention across watchdog expiry, HIZ, /CE toggle, V-MOT dips inside the window, and ACUV stop/restart | Read-back unchanged (POR excepted) |
| B4 | Warm step (M-R4) at VAC_DPM 19.0 V and 19.9 V | τ63 ≤ 4 ms (or per [REGEN] after M-R0/M-R1); no re-qualification |
| B5 | Bus-level draw: VAC = 16.0 / 17.2 / 17.5 V with VAC_DPM = 19 V, /CE low; record converter state (switching / PFM / idle) | I_IN to the charger stage < 10 mA plus housekeeping; no battery current |
| B6 | D-BC-RG co-ramp and D-BC-FC closure into the reworked EVM; scope I_fc and V-MOT | I_fc < 1.0 A; no OC_FC; no RT1987 SCP |
| B7 | Start into D-BT-SQ: VCHG 0 V, pack at 7.4 and 8.4 V; and with D-BT-SQ open | Clean trickle → pre → CC; hiccup only when open |
| B8 | Unpowered EVM: SDA/SCL/INT leakage with the Teensy pull-ups live | < 10 µA; no bus-low hold |
| B9 | CV at the pack through D-BT-SQ at the end of taper | 8.33-8.40 V |
| B10 | W2: ILIM_HIZ forced to 3.0 V while warm at VAC 21 V | I_IN < 10 mA; recovery to I_LIM ≤ 4 ms on release; REGN stays up |
| B11 | No reverse current into VAC in VDPM, PFM or DCM at zero charge (IAC_ADC sign, scope) | I_AC ≥ 0 |
| B12 | Efficiency and thermals at 16 → 8.4 V and 21 → 8.4 V, 2.5 A | > 90 %, components < 80 °C |
| - | Shared gates | [REGEN] M-R0..M-R3, [LOOP] M1-M8 |

## 11. missing_primaries

- **BQ25756 [DS] gaps:**
  - VDPM/charge-loop bandwidth and warm transient;
  - charge-to-zero latency for /CE, EN_CHG, HIZ and ACUV/ACOV (only the 100 µs nominal deglitch is given, with no min/max);
  - HIZ-exit and /CE-enable restart timing, and when the about 40 ms compensation toggle recurs;
  - the I_BAT_SHORT trickle current value;
  - input current when switching at zero charge current;
  - the tolerance of the 40 s watchdog setting;
  - unpowered-pin leakage;
  - 2S efficiency curves;
  - VAC_DPM accuracy at 15 V.
- **EVM parts:**
  - DC-bias curves for Murata GCJ32DC72A475KE01L and TDK C3225X7R2A106K250AC (effective C_IN);
  - SIR680LDP Q_G (REGN dissipation);
  - LT3010 behaviour with its output back-driven;
  - the EVM Altium design files (copper; optional).
- **Mouser and Farnell** pages for BQ25756EVM: unreachable (HTTP/2 INTERNAL_ERROR).
- **Shared with [LOOP] and [REGEN]:**
  - NXP i.MX RT1060 RM (watchdog, reset pad state);
  - PJRC pad state during reset;
  - RT1987 turn-off delay;
  - 74LVC1G thresholds;
  - TL431 datasheet;
  - INA253A1 zero offset;
  - VESC l_max_vin / fault-stop time / input capacitance;
  - TDK C3216X7R1V106K DC bias;
  - BSP170P SOA.
