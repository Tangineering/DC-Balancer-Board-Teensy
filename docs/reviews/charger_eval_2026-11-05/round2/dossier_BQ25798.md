# Round-2 dossier: TI BQ25798 on the BQ25798EVM (BMS034A/B-003), Path A replacement for the Ag105 (board rev 20260622)

Date: 2026-11-05. This supersedes the round-1 dossier
`docs/reviews/charger_eval_2026-11-05/dossier_TI_BQ25798__integrated_4_FET_buck_boost__NVDC__dual_input__VOC_scaling_MPPT_.md`.
That dossier was written from search snippets and recollection. This one is written from the primary documents, against the
2026-11-05 operator rulings:
- regen harvesting and FC charging are both hard requirements;
- Path A must be shown fully feasible;
- R3 is replaced by "no circular loop, no runaway";
- the always-powered charger is accepted (REGEN closed through Run, threshold between the bus maximum and the clamp);
- an MCU hardware watchdog is required future work.

## 0. Sources and evidence rules

| Tag | Document | How read |
|---|---|---|
| [DS] | TI **SLUSDV2C**, *BQ25798 I2C Controlled, 1 to 4-Cell, 5A Buck-Boost Battery Charger with Dual-Input Selector, MPPT and Fast Backup Mode*, May 2020, rev. June 2026, 152 pp. | Read in full: sections 4-8 and the register map. Cited as DS p.N (PDF page = printed page) plus the section, table or figure. Figures 6-3/6-4 (p.18) and 8-4 to 8-19 (pp.136-138) were rendered to PNG and read by eye. **Values read off a figure are labelled "figure reading, typical" and are never treated as a specification.** |
| [UG] | TI **SLUUCB5E**, *BQ25792EVM, BQ25798EVM and BQ25798BKUPEVM (BMS034) Evaluation Module*, June 2020, rev. July 2022, 25 pp. | Read in full. Covers Table 1-2 (I/O), Table 1-3 (jumpers), Table 1-4 (ROC), the §2.4 procedure, Table 4-1 (BOM, pp.22-24), Figure 4-5 (schematic page 1, p.19) and Figure 4-6 (schematic page 2, p.20). The schematics were rendered at 200 dpi (`r2/bq798/sch-19.png`, `sch-20.png`). Figure 4-7 is the BKUP variant and does not apply. |
| [RT] | Richtek RT1987 DS-00 | Read for D-BT-SQ only: IQ, UVLO, tD_ON, TRCB restart (pp.7, 14-16). |
| [TIstore] | ti.com, fetched with plain curl on 2026-11-05 at 17:39 UTC: tool page `ti.com/tool/BQ25798EVM` (`data-price`), store inventory endpoint `ti.com/storeservices/cart/opninventory?opn=...`, product page `ti.com/product/BQ25798` (tiered price JSON) | Primary vendor data |
| [SPEC], [LOOP], [REGEN] | `docs/reviews/charger_eval_2026-11-05/spec.md`; round-2 `r2/loop_analysis.md`; round-2 `r2/regen_dynamics.md` | Board facts and cross-cutting analyses |

Anything not found in a primary document is marked **UNKNOWN** or **BENCH**. Nothing is filled in from recollection.

**Could not be reached:**
- **www.mouser.com:** HTTP/2 INTERNAL_ERROR, then timeout with curl; DNS ENOTFOUND with WebFetch.
- **uk.farnell.com:** same failures.
- **www.mikroe.com:** DNS ENOTFOUND.

These are listed under §10. Per the tool policy I stopped after these failures.

## 1. Verdict: FEASIBLE_WITH_CONDITIONS

No hard requirement fails on the primaries.

### 1.1 Proven from the documents

| Property | Value | Source |
|---|---|---|
| Common ground on the EVM | Every EVM shunt is in a positive rail. Sensing is internal, between VBUS and PMID and between SYS and BAT | UG Fig 4-5 |
| Hardware converter-off pin | ILIM_HIZ < 0.75 V stops switching; > 1 V resumes | DS §7.3.4.3 p.27; Table 5-1 p.5; EC p.16 |
| Hardware charge-disable pin | CE, active LOW | DS Table 5-1 p.5 |
| Input-voltage threshold | VINDPM 3.6-22 V, 100 mV steps, ±2 % at 18.6 V (DS p.12, p.62). A 19.0 V threshold is 18.62-19.38 V worst case. A 20.0 V setting can also sit above the TPS61288 OVP maximum of 19.5 V (the BQ25713/BQ25720 cannot exceed 19.52 V) | DS p.12, p.62 |
| VINDPM is not overwritten while the input stays present | Only adapter plug-in, FORCE_VINDPM_DET or MPPT rewrite it. REG_RST and the watchdog do not | DS §7.3.4.4 p.27, §7.4.2 p.56, Table 7-17 p.62 |
| Host watchdog with a fail-to-off option | Minimum setting 0.5 s. With **STOP_WD_CHG = 1**, expiry sets EN_CHG = 0 | DS Table 7-26 p.72, Table 7-20 p.65 |
| CV regulation | 2S 8.4 V at -0.25 %/+0.65 % | DS p.11 |
| Charge current | 50 mA-5 A in 10 mA steps | DS p.11, p.61 |
| Input OVP | VBUS_OVP 25.2 V minimum; 30 V absolute maximum | DS p.7, p.9 |
| No switching during the RT1987 ramp | REGN turns on about 150 ms after VBUS_PRESENT | DS §7.3.4 step 5, p.26 |
| I2C telemetry | IBAT, IBUS, VBUS and VBAT, 1 mA / 1 mV LSB | DS pp.16-17 |
| Availability | TI store: EVM USD 156.45, 162 in stock; IC 143 526 in stock | [TIstore] |

### 1.2 What keeps it from "proven"

1. **The stock EVM is not fail-safe.**
   - JP17 grounds CE, so charging is enabled.
   - The POR defaults are charge enabled, ICHG 1 A, IINDPM 3 A and watchdog 40 s. They are cleared to "charging, autonomous" (DS §7.1 p.23, §7.4.1 pp.55-56).
   - The EVM pull-up rail (TLV76033, fed from VBUS and BAT) back-powers the Teensy through R39/R40.
   - Fixes: §5 mods M1-M6.
2. **Regen capture is decided by latencies the datasheet does not give.**
   - Neither the ILIM_HIZ exit-to-current latency nor the VINDPM loop bandwidth is specified.
   - The only primary hint is DS Fig 8-6 (p.136): with CE asserted at VBUS 5 V, IBAT rises in about 0.1-0.2 ms (figure reading, typical).
   - [REGEN] requires τ_warm ≤ 4 ms on the unmodified board. Bench gate B4 (= M-R4).
3. **Board-level finding that applies to every candidate:** D-BT-SQ drops out between bursts.
   - D-BT-SQ draws its own IQ (650 µA typ, 780 µA max) from VCHG ([RT] p.7).
   - With the charger idle (converter gated off in cruise), VCHG decays below the RT1987 UVLO (2.925 V typ falling) in well under a second.
   - The next burst then pays tD_ON (8 ms typ) plus tON (1.9 ms typ) ([RT] p.7, §17.1 p.14) before any current reaches the pack. That alone breaks τ_warm ≤ 4 ms.
   - With the BQ25798 a **keep-alive resistor VBT→VCHG (mod M8)** fixes this, and also keeps the IC powered and its configuration intact from the pack (§2.7).
   - It is an operator ruling. The alternative is bridging D-BT-SQ.
4. **Input-current ceiling conflict.**
   - The ILIM_HIZ pin is also the hardware input-current ceiling, and it is read when the input qualifies (DS §7.3.4 step 6, §7.3.4.3).
   - In regen mode the [LOOP] comparator holds ILIM_HIZ LOW at that instant (V-MOT ≈ VBUS in cruise), so the clamp reads 100 mA.
   - Firmware must then set EN_EXTILIM = 0, and the IINDPM register becomes the only ceiling.
   - Runaway stays bounded at board level: the comparator in regen mode, OC_FC in FC mode. But [LOOP] C2 (a hardware ceiling) is met only in FC mode. Bench gate B6 tests whether ILIM_HIZ also regulates continuously (EC p.12 lists VILIM_REG_RNG 1-4 V).
5. **The regen hard requirement is also gated by the board, not the charger.**
   - The VESC cut-off at about 21.35 V within 19-47 ms ([REGEN]) is one gate.
   - M-R0 and M-R3 come first.
   - If the cut-off is raised to about 24 V, it collides with the BQ25798's 24 V recommended VBUS maximum (DS p.7) and with the 25 V EVM capacitors.

## 2. Requirement matrix

| # | Requirement | Status | One-line evidence |
|---|---|---|---|
| H1 | Common ground / sense placement | PROVEN_DATASHEET | UG Fig 4-5: J1-J5 GND on PGND, AGND joined by NT1. Shunts R2/R6/R11/R12/R13 (0.01 Ω) are all high-side. IC sense is internal (DS Table 5-1) |
| H2a | Hard inhibit while powered (mechanism) | PROVEN_DATASHEET | ILIM_HIZ < 0.75 V = converter off, REGN on. CE HIGH = charge off. ICHG = 0 is not available (50 mA minimum, clamped low) |
| H2b | Inhibit latency ≤ ~290 µs ([LOOP] M2) | BENCH_GATE | Not specified. Fig 8-7 shows charge disable over about 0.3 ms (figure reading, typical, 5 V input) |
| H3 | Fail-safe (reset / hang / I2C dead / POR) | BENCH_GATE | Mechanisms proven (CE pin, ILIM_HIZ, WD 0.5 s plus STOP_WD_CHG, 1.5 s I2C timeout). POR default charges at 1 A, so mods M1-M3 are mandatory. STOP_WD_CHG behaviour to be bench-verified |
| H4a | Threshold range / accuracy / runtime programmability | PROVEN_DATASHEET | VINDPM 3.6-22 V, 100 mV, ±2 % at 18.6 V, ±3 % at 10.6 V, R/W at any time |
| H4b | Draw at or just under the threshold | BENCH_GATE | IQ_VBUS 3 mA (charge disabled, converter switching, 15 V), ISD_VBUS 386 µA (EN_HIZ). The ILIM_HIZ-HIZ draw with REGN on is not specified |
| H4c | Warm response / no re-qualification | BENCH_GATE | Not specified. Re-qualification is tied only to plug-in (VBUS < VBUS_PRESENT 3.2 V) and EN_HIZ toggles (DS §7.3.4.2). The VINDPM re-measure is tied only to plug-in (§7.3.4.4, §7.4.2) |
| H5 | FC charging ≥ 2 A at 2S, CV, termination | PROVEN_CALC | 2 A is in range. The board OC_FC budget gives about 1.8-2.0 A. VREG -0.25/+0.65 %. ITERM 40-1000 mA |
| H6 | Voltage ratings / OVP | PROVEN_DATASHEET | VBUS 24 V operating, 30 V abs max. VBUS_OVP 25.2-26.2 V rising, auto-restart. EVM 25 V caps must be upgraded (M7) |
| H7 | Battery pin through D-BT-SQ | BENCH_GATE | Works by topology. Initial-power-up trickle 1.5 s at BATP < 2.25 V. RT1987 UVLO re-entry costs 8 ms. Keep-alive M8 or a D-BT-SQ bridge is needed |
| H8 | Inrush / hot-plug | PROVEN_CALC | EVM VBUS+PMID 50.2 µF nominal + board 20 µF → 0.84 A at 12 mA/µF. No bulk. No switching for about 150 ms after VBUS present |
| H9 | I2C / logic / STAT | PROVEN_DATASHEET | 0x6B, VIH 1.3 V / VIL 0.4 V, 6 V abs max. EVM pull-ups must go (M4). Unpowered-pin clamping is UNKNOWN (moot with M8) |
| H10 | Thermal / efficiency / mechanical | BENCH_GATE | About 93 % at 15 V / 2.5 A and about 91 % at 20 V (Fig 6-4, figure reading). EVM size not in UG, so off-board on leads |
| H11 | Availability | PROVEN_DATASHEET | TI store 2026-11-05 17:39 UTC. Mouser/Farnell not reachable |
| H12 | Telemetry | PROVEN_DATASHEET | IBAT/IBUS 1 mA, VBUS/VBAT 1 mV, 6-24 ms per channel. **No ADC accuracy spec in DS** |

### 2.1 H1: common ground and sense placement
- **IC:** the input current sense sits between VBUS and PMID (RSNS 8 mΩ, DS p.14, Table 5-1 p.4). The charge current sense sits between SYS and BAT (Table 5-1 p.5, BAT pin). Both are internal and high-side. There is one GND pin (27) (Table 5-1 p.6).
- **EVM (UG Fig 4-5, p.19):**
  - J1 pin 2, J2 pin 2, J3 GND, J4 GND and J5 pin 3 are all PGND.
  - AGND joins PGND at net-tie **NT1**.
  - All five measurement shunts (R2 VIN1, R6 VIN2, R11 SYS, R12 PMID, **R13 battery between the BAT/Q5 node and J5-1**; all WSL2010 0.01 Ω, UG BOM p.22) are in positive rails.
  - Nothing sits between any input return and the battery return.
- **Unregulated paths:**
  - None with OTG off (EN_OTG POR 0, reset by the watchdog to 0, DS Table 7-28 p.75).
  - Backup mode is impossible without ACFET1, because EN_BACKUP is forced to 0 (DS §7.3.7.2 p.37).
  - Passive back-feed from SYS to VBUS is blocked: Q4 has its drain on SYS and source on SW2 (DS Table 5-1 p.6), so its body diode only conducts SW2→SYS. Q1 has its drain on PMID (p.6).
- **Status: PROVEN_DATASHEET.**

### 2.2 H2: hard charge inhibit while powered

| Mechanism | What it stops | Response | POR / reset default | Ref |
|---|---|---|---|---|
| **ILIM_HIZ pin < 0.75 V** (V_IL 0.75 V, V_IH 1 V) | Converter stops switching in forward and OTG modes, so no input power and no BAT current. REGN stays on. "Similar to HiZ mode using EN_HIZ bit, but with REGN on" | Not specified | Set by the external network. EVM: R21 127 k from REGN / R23 100 k (JP14) gives about 2.2 V = **enabled** | DS §7.3.4.3 p.27; Table 5-1 p.5; EC p.16 |
| **CE pin HIGH** (active-low enable; V_IH 1.3 V, V_IL 0.4 V; "do not leave floating") | Charging (all phases: a charge cycle needs EN_CHG = 1 **and** CE LOW, §7.3.9.1). The converter keeps regulating SYS (IQ_VBUS 3-5 mA at 15 V, EC p.8) | Fig 8-7: IBAT falls over about 0.3 ms (figure reading, typical, VBUS 5 V) | External. EVM: R42 10 k to PULLUP, **JP17 installed = CE grounded = enabled** (UG Table 1-3 p.5, Fig 4-6) | DS Table 5-1 p.5; §7.3.9.1 pp.41-42; p.136 |
| EN_CHG = 0 (REG0F[5]) | Same as CE | Not specified | **POR 1**; **reset by WATCHDOG to 1** unless STOP_WD_CHG = 1 | DS Table 7-25 p.70; Table 7-20 p.65 |
| EN_HIZ = 1 (REG0F[2]) | Converter off, REGN off, ADC off, BATFET on | Not specified | POR 0. **Auto-cleared at adapter plug-in.** Auto-set by poor source, IBUS_OCP and VSYS_SHORT. Toggling it forces a poor-source retry and an ICO restart | DS §7.3.6.5 p.35; §7.3.4.2 p.27; §7.3.6.2 p.34 |
| ICHG = 0 | **Not available.** The range is 50 mA-5 A and writes below the minimum are ignored ("Clamped Low") | - | POR 1 A | DS Table 7-16 p.61; Table 7-13 p.58 |
| TS out of window | Charge suspended ("If TS voltage exceeds the VT1-VT5 range, the controller suspends charging") | Not specified | TS_IGNORE POR 0, reset by WD | DS §7.3.9.5.1 p.45; Table 7-34 p.83 |
| VINDPM above input | A regulation loop, not an inhibit | - | Plug-in sets VBUS0 - 1.4 V | DS §7.3.4.4 p.27 |

Do the inhibits stop **all** current into the battery pin?
- **ILIM_HIZ, EN_HIZ, VBUS_OVP:** these stop switching entirely, so nothing is delivered.
- **The BATFET only conducts BAT→SYS in supplement mode**, as an ideal diode (DS §7.3.8.2 p.40). That cannot charge.
- **Trickle (IBAT_SHORT 100 mA) and precharge** are charging phases and need CE LOW and EN_CHG = 1 (§7.3.9.1).
- **One caveat (DS §7.3.6 p.33):** with "charge disabled by CE pin or EN_CHG ... no battery attached", the IC "keeps the BAT pin voltage at low-level, steady-state voltage, close to 2.5 V".
  - Behind D-BT-SQ that is harmless (2.5 V < pack).
  - With the keep-alive (M8) it may sink the bleed current and pull VCHG under the RT1987 UVLO. That is a reason to gate with ILIM_HIZ rather than CE (bench gate B7).

**Choice for this board:**
- **ILIM_HIZ** is the [LOOP] H3 target, in variant (b): an NMOS from the charger's REGN holds the pin LOW unless PERMIT.
- **CE**, driven by Teensy pin 5 through an open-drain stage, is the independent second inhibit (M2).

**Status:** H2a PROVEN_DATASHEET. H2b (latency ≤ 290 µs for [LOOP] §4.3) BENCH_GATE B3.

### 2.3 H3: fail-safe
- **(a) Teensy in reset or pins high-Z:**
  - The RT1987 EN pull-downs open D-BC-FC and D-BC-RG ([SPEC] §3.1), so the charger has no VBUS.
  - With M2, pin 5 high-Z means the NFET is off and CE is pulled HIGH, so charging is disabled.
  - With the [LOOP] H3 stage, ILIM_HIZ is held LOW.
  - With M8 the IC stays powered from BAT in battery-only mode, but with no VBUS it cannot charge.
  - **Required pulls:** CE pull-up to the EVM PULLUP rail (R42 10 k, keep it) with JP17 removed; a 100 k gate pull-down on the M2 NFET; the [LOOP] 47 k pull-down on P5; the ILIM_HIZ inhibit NMOS biased from REGN.
- **(b) Teensy hung with its pins latched (P5 = 1, REGEN = 1, BT_BUS = 1):**
  - [LOOP] H1 still gates ILIM_HIZ, so there is no loop.
  - The charger watchdog: settings 0.5/1/2/20/40/80/160 s, POR 40 s (DS Table 7-26 p.72). Accuracy is specified only for 160 s (136-160 s, EC p.17); **the 0.5 s accuracy is not given**.
  - Firmware writes WATCHDOG = 0.5 s (or 1 s) and **STOP_WD_CHG = 1**. A missed kick then sets EN_CHG = 0 (DS Table 7-20 p.65).
  - The WATCHDOG field is reset only by REG_RST (Table 7-26). STOP_WD_CHG lists no reset source in Table 7-20, so both survive until POR. **Bench gate B5:** confirm that charging stops at expiry with STOP_WD_CHG = 1, because the generic text (§7.4.1 p.56) says expiry restores defaults, which puts EN_CHG at 1.
  - **What the watchdog resets** (DS Table 7-16 p.61, 7-20, 7-25, 7-28, 7-30, 7-34, 7-55): EN_CHG→1 (→0 with STOP_WD_CHG), ICHG→1 A, ITERM, EN_TERM, EN_OTG→0, EN_IINDPM→1, TS_IGNORE→0, ADC_EN→0.
  - **What it does not reset:** VREG, VSYSMIN, IINDPM, VINDPM, EN_HIZ, WATCHDOG (Tables 7-14/7-15/7-17/7-18/7-25/7-26).
  - So a watchdog reset cannot raise CV or lower the threshold.
- **(c) I2C dead or stuck:**
  - The IC releases the bus "if a started transaction doesn't complete within 1.5 s" (DS §7.3.14 p.53).
  - With no kicks, WD expiry stops charging as in (b).
  - If I2C never worked since POR, the config is unverified and [LOOP] F2 keeps P5 LOW, so CE stays HIGH.
- **(d) POR defaults:** the IC **charges by itself out of reset**.
  - "After power up, the charging is defaulted enabled with all the registers default settings" (DS §7.1 p.23). "After power-on-reset, the device starts in default mode with watchdog timer expired" (§7.4.1 p.56).
  - The defaults (DS Table 7-9 p.41, Table 7-2 p.25, Table 7-17/18):

    | Parameter | POR default |
    |---|---|
    | VREG | 8.4 V with the 2S PROG strap |
    | ICHG | 1 A |
    | IPRECHG | 120 mA |
    | ITERM | 200 mA |
    | IINDPM | 3 A, or the D+/D- result |
    | VINDPM | VBUS0 - 1.4 V |
    | Timers | 12 h fast-charge |

  - Only the hardware CE pull and the ILIM_HIZ hold make POR safe. This meets [LOOP] C1 and C4 (no NV restart: all registers are volatile) but **not C3** (charge-current POR default is not 0 A), so the hardware pulls are mandatory.
- **Status: BENCH_GATE** (B5, plus scope verification of the M1-M3 pull states during Teensy reset).

### 2.4 H4: input-voltage threshold (always-powered regen)
- **Register:** REG05 VINDPM[7:0]: 3600-22000 mV, 100 mV/LSB, offset 0. Writes below the minimum are ignored. POR 3600 mV (DS Table 7-17 p.62; EC p.12).
- **Accuracy:** VINDPM_ACC is ±2 % at 18.6 V, ±3 % at 10.6 V and ±5 % at 4.3 V (EC p.12). Only these three points are specified. The settings below interpolate the ±2 % (18.6 V) and ±3 % (10.6 V) figures; treat them as estimates.

  | Setting | Window | Placement |
  |---|---|---|
  | **Regen 19.0 V** | 18.62-19.38 V | Min is 1.12 V above the 17.5 V fw OV latch, 1.42 V above the measured 17.2 V overshoot and 0.32 V above the TPS61288 OVP minimum of 18.3 V. Max is 2.0 V below the 21.4 V clamp and 1.97 V below the VESC cut-off at about 21.35 V |
  | **Regen option 20.0 V** | about 19.6-20.4 V | Min is above the TPS61288 OVP **maximum** of 19.5 V, so even a failed-FB boost bus cannot reach the threshold. Max is 0.95 V below the VESC cut-off, which shortens the [REGEN] time budget. The BQ25713/BQ25720 (max 19.52 V) cannot do this. [REGEN] says the threshold costs only 1-2 % of energy, so the trade is safety margin against warm-response budget |
  | **FC mode 15.0 V** | about 14.6-15.45 V (±3 %) | Below the 15.9 V bus |
- **Runtime programmability:** R/W at any time over I2C.
- **Events that overwrite it while powered:**
  - Adapter plug-in: "set to the value based on the VBUS measurement when the adapter plugs in". Unplug resets it to 3.6 V. Not reset by REG_RST or WATCHDOG (Table 7-17 p.62; §7.4.2 p.56: the VBUS0 measurement is "only done when an adapter is plugged in").
  - FORCE_VINDPM_DET (REG13[1]).
  - EN_MPPT (POR 0).
  - Unplug here means VBUS falling below VBUS_PRESENTZ 3.1-3.3 V (EC p.9). V-MOT never gets that low in Run with the VESC alive, so **the regen threshold, once written after the Run-entry plug-in, survives the whole Run.** This is better than the BQ25713, which re-measures before every converter enable.
  - **Bench gate B2:** VINDPM retention across ILIM_HIZ LOW/HIGH cycles.
- **Draw at or just under the threshold:**
  - With the [LOOP] comparator, the converter is gated off (ILIM_HIZ LOW) whenever V-MOT < 1.067 × VBUS. The cruise draw is therefore the REGN-on HIZ draw, which is **not specified**. It lies between ISD_VBUS 386 µA (EN_HIZ, REGN off, 15 V) and IQ_VBUS 3 mA (converter switching, charge disabled, ISYS = 0, OOA off) or 5 mA (OOA on) (EC p.8).
  - That current passes through D-MT-EN as bus → charger quiescent current. It is not a charge path and not a loop (no BAT current).
  - Between the comparator permit (about 17 V) and VINDPM, the converter runs PFM at no load, again at the IQ level.
  - **B1:** measure I(VCHG-IN) at 15.9 V and at 18.5 V with VINDPM 19.0 V.
- **Warm response:**
  - No VINDPM loop bandwidth and no ILIM_HIZ exit timing are given.
  - Primary hints (figure readings, typical, not specifications): Fig 8-6 (p.136, 1 ms/div) shows IBAT rising to 1 A in about 0.1-0.2 ms after charge enable at VBUS 5 V. Fig 8-16 (p.138, 1 ms/div) shows the IINDPM loop settling in about 0.1-0.2 ms.
  - Both suggest sub-millisecond current loops, but neither is the "idle at Vth - 0.5 V, step to Vth + 1 V" case that [REGEN] defines.
  - **B4 = M-R4 decides it.** Requirement: τ_warm ≤ 4 ms (10-90 % ≤ 9 ms), or ≤ 2 ms if C(V-MOT) is board-only.
- **Re-qualification:**
  - Poor-source qualification runs after REGN power-up at plug-in, and on an EN_HIZ = 0 write (DS §7.3.4.2 p.27; §7.3.13.1.3 p.51).
  - The VBUS0 measurement for VINDPM runs only at plug-in.
  - The ILIM_HIZ pin "resumes switching if ... higher than 1 V" with no qualification step stated (DS §7.3.4.3).
  - So a dip of V-MOT back to the bus does not restart qualification as long as it stays above 3.2 V. This is datasheet wording, to be confirmed in B2/B4.
  - **Do not toggle EN_HIZ per burst** (round-1 advice, withdrawn): it turns REGN off and forces poor-source retry and ICO.
  - Leave AUTO_INDET_EN = 0, EN_ICO = 0, EN_MPPT = 0 (REG11, REG0F, REG15; AUTO_INDET_EN and EN_ICO reset only by REG_RST).
- **Status:** H4a PROVEN_DATASHEET; H4b and H4c BENCH_GATE.

### 2.5 H5: FC-charging mode
- **Path:** VBUS 15.9 V via D-BC-FC, BT_BUS off. VBUS > VBAT, so the IC runs in buck mode (DS §7.3.6 p.33).
- **ICHG:** 50-5000 mA, 10 mA steps (DS p.11, Table 7-16 p.61). Buck-mode accuracy at VBAT 8 V: 2 A -6.5/+3.5 %, 1 A ±5 %, 0.5 A ±7.5 % (EC p.11). At 2.5 A only the boost-mode figure is given (-3/+7 %).
- **Board budget (calc):**
  - Input at 2.0 A charge = 2.0 × 8.4 / (0.935 × 15.9) = **1.13 A** (efficiency from Fig 6-4, figure reading, 15 V, about 2 A, 1.5 MHz).
  - Bus side 1.13 + I_aux 0.15 = 1.28 A, against OC_FC 1.4 A (single sample) ([SPEC] §6): 8.5 % margin.
  - Recommended: **IINDPM 1.00 A** (accuracy 880-1000 mA at 9 V, EC p.12, which never exceeds the setting) gives about **1.77 A** charge. 2.0 A is reachable with IINDPM 1.13 A at the thin margin above.
  - The charger meets "≥ 2 A". The board's OC_FC sets the practical limit.
- **CV:** VREG 3.0-18.8 V, 10 mV steps. Writes outside the CELL band (2S: 5-9.99 V) are ignored. Accuracy at 8.4 V: -0.25/+0.65 % → 8.379-8.455 V at VCHG (DS p.10-11, Table 7-2 p.25). D-BT-SQ VFWD is 35 mV typ ([RT] p.7), so the pack settles at 8.34-8.42 V: inside LIMIT_V_BATT_MAX 8.5 V and the BQ29200 4.35 V/cell.
  - **Risk:** firmware can write up to 9.99 V in the 2S band. Read back VREG and require ≤ 8.40 V before P5.
- **Termination:** ITERM 40-1000 mA, 40 mA steps; ±14 % at 480 mA, ±20 % at 120 mA (EC p.11). Termination is disabled during DPM or thermal regulation (§7.3.9.3 p.43).
  - Through D-BT-SQ, the recharge after termination is driven by VCHG, not the pack ([SPEC] §3.4). Firmware clears EN_CHG at termination (CHG_STAT = 111b, REG1C).
- **VSYSMIN:** set it well below VREG (≤ 5.0 V, REG00 2.5-16 V in 250 mV steps). Otherwise "during SYSMIN regulation with BATFET LDO operation the charge current is limited to 2 A" (§7.3.9.2 p.42) while VCHG < VSYSMIN. Or set DIS_LDO = 1.
- **Status: PROVEN_CALC.**

### 2.6 H6: voltage ratings and OVP

| Item | Value | Ref |
|---|---|---|
| VBUS operating | 3.6-24 V | DS p.7, p.9 |
| VBUS / VAC / PMID abs max | 30 V (not switching for VBUS/PMID) | DS p.7 |
| SW1 / SW2 / SYS / BAT abs max | 30 V / 23 V / 23 V / 20 V | DS p.7 |
| VBUS_OVP | rising 25.2 / 25.7 / 26.2 V, falling 24.0 / 24.4 / 24.8 V. "Converter stops switching immediately ... automatically starts switching again when VBUS drops below" | DS p.9, §7.3.13.1.2 p.51 |
| VAC_OVP | 26 / 18 / 12 / 7 V (default 26 V: register reset 85h). Acts only on the ACFET-RBFET pairs (§7.3.13.1.1 p.51), so it is **inactive with the ACFETs bypassed (M5)** | DS p.9, Table 7-26 p.72 |

- **Against V-MOT:** the 21.4 V clamp (true) is 3.8 V below OVP minimum, so there is no drop-out mid-burst. 2.6 V of operating headroom remains to 24 V.
- **If the VESC cut-off is raised to about 24 V ([REGEN] option):** V-MOT reaches the recommended operating maximum and comes within 1.2 V of OVP minimum. OVP would stop the converter during the clamp phase (harvest lost, not unsafe).
- **EVM capacitors:** VBUS C11/C12 and PMID C29/C30/C31 are 10 µF **25 V** X5R 0805. C38/C39 BAT and C19-C23 SYS are 25 V X5R (UG BOM p.22). Replace the VBUS/PMID parts with ≥ 35 V X7R (M7). Board C-D8/C-D10 likewise ([SPEC]).
- **Datasheet inconsistencies, recorded:**
  - Table 4-1 (p.3) still lists the ACOVP options as "7V, 12V, 22V or 26V", while the EC table, the register table and the revision history (p.142, "Corrected ... 18V instead of 22V") say 18 V.
  - The REG10 table text "POR: 11b" contradicts its own "0h = 26V (default)" and the register reset value 85h. The value 85h decodes as VAC_OVP = 00 = 26 V.
- **Status: PROVEN_DATASHEET.**

### 2.7 H7: battery pin through D-BT-SQ
- **Topology:** VCHG (charger BAT) → D-BT-SQ (RT1987 back-to-back FETs, ideal diode, VFWD 35 mV) → VBT. The pack cannot drive VCHG ([RT] §17, p.14).
- **The IC tolerates an open or capacitive battery node:** "With no battery attached to BAT ... charge enabled ... BAT pin follows the charge profile ..." (DS §7.3.6 p.33). It starts into C-D11 and its own BAT caps. Once VCHG > VBT + 35 mV, D-BT-SQ conducts, with no soft-start (TRCB auto-restart, [RT] Table 1 p.15).
- **Cold power-up from VCHG ≈ 0 V (no keep-alive):**
  - "To enter trickle charge at initial power up, the BATP sense voltage must be below VBAT_SHORTZ = 2.5 V max. The charger then regulates the battery voltage to 2.5 V/cell typical for tBAT_SHORTZ = 1.5 s, outputting up to 100 mA" (DS §7.3.9.2 p.42).
  - For 2S that is about 5 V, below the pack, so **at least 1.5 s with no pack current**. Then precharge, then fast charge.
- **Between bursts (always-powered regen):**
  - With ILIM_HIZ LOW the converter is off and the BATFET is on to support SYS.
  - VCHG decays under D-BT-SQ's own IQ: 650 µA typ, 780 µA max ([RT] p.7).
  - EVM BAT+SYS caps are 7 × 10 µF + C-D11 10 µF = 80 µF nominal. That gives about 8-10 V/s, so 8.4 V → 2.925 V (UVLO falling) in **about 0.6-0.7 s**.
  - The next burst pays **tD_ON 8 ms + tON 1.9 ms** ([RT] p.7, §17.1 p.14), assuming UVLO recovery follows the EN-high start sequence. [SPEC] §3.4 flags this as unverified.
  - **This fails τ_warm ≤ 4 ms by itself, for any charger.**
- **Mod M8 keep-alive** (operator ruling): a resistor from VBT (pack side, C-D12 under the footprint) to VCHG.
  - Sizing: R ≤ (7.4 V - 3.35 V UVLO_max - 1 V margin) / 0.78 mA ≈ 3.9 kΩ. **Use 1.0 kΩ:** VCHG ≥ 7.4 - 0.78 = 6.6 V. Its continuous current is the RT1987 IQ (0.65-0.78 mA, about 15-19 mAh/day from the pack, including parked).
  - **Benefits:**
    - The IC is powered from BAT (VBAT_UVLOZ 2.6 V without SFET, EC p.9). I2C is accessible at all times (IQ_BAT_ON 17 µA).
    - The non-volatile-until-POR settings survive every VBUS cycle: VREG, IINDPM, WATCHDOG, STOP_WD_CHG, AUTO_INDET_EN, VSYSMIN, VBAT_LOWV.
    - The 1.5 s trickle and the RT1987 restart are avoided.
    - The unpowered-I2C-pin question (H9) becomes moot.
  - **Required with it:**
    - VBAT_LOWV = 0h (15 % VREG = 1.26 V, REG08[7:6]), so VCHG ≈ 6.6 V is already "fast-charge" (DS Table 7-19 p.64).
    - VSYSMIN ≤ 5.0 V or DIS_LDO = 1.
    - Gate with ILIM_HIZ, not CE (§2.2 caveat).
  - **Leak path check:** pack → R → BAT. The IC can sink at most VBT/R ≈ 8.4 mA into a shorted charger. The pack cannot reach VBUS (§2.1).
  - **Alternative:** bridge D-BT-SQ ([SPEC] §3.4 item 4). The BQ25798 4-switch topology blocks battery → VBUS passively (§2.1), so that is safe even with JP3 fitted.
- **CV sensing:** BATP is the CV sense input ("Positive Input for Battery Voltage Sensing ... Place 100 Ω series resistance", DS Table 5-1 p.5; RBATP 2.5 MΩ, EC p.12).
  - EVM JP9 selects BATP = BAT pin (2-3) or J5 BATTERY / EXT_BATP via R15 100 Ω (UG Table 1-3 p.4).
  - **Recommend BATP = BAT pin (JP9 2-3).** Sensing the pack (VBT) would remove the 35 mV error, but with D-BT-SQ open the charger would push VCHG open-loop until VSYS_OVP. That protection behaviour is not specified for this case, so it is not recommended.
- **Status: BENCH_GATE** (B7: VCHG stays above UVLO with M8; no fault on burst entry; termination and recharge cycle behaviour).

### 2.8 H8: inrush / hot-plug
- **EVM input-node capacitance** (VBUS and PMID are tied through the internal 8 mΩ sense):

  | Group | Parts | Nominal |
  |---|---|---|
  | VBUS | C11, C12 (10 µF) + C13 (0.1 µF) | 20.1 µF |
  | PMID | C29, C30, C31 (10 µF) + C32 (0.1 µF) | 30.1 µF |
  | DNP | C9, C10, C26-C28, C33/C34 (BKUP only), C1, RSNUB/CSNUB | - |
  | **Total** | | **50.2 µF** (UG Fig 4-5, BOM pp.22-24) |

  There is no electrolytic or tantalum on the BQ25798EVM input. C25 33 µF Ta is DNP and sits on SYS anyway.
- **Inrush:** (20 µF board + 50.2 µF) × 12 mA/µF ([SPEC] §6) = **0.84 A**, plus I_aux 0.15 A = **0.99 A** at nominal capacitance. That is inside the [SPEC] ≤ 1.0 A FC budget and below the RT1987 SCP (2.5 A) and OC_FC (1.4 A).
  - DC bias lowers the effective C. The TDK C2012X5R1E106K curve was not read, so the figure above is the worst case.
  - Not Death-5 class: no bulk.
- **No switching during the 1.3-1.75 ms ramp:** "As soon as VVBUS > VVBUS_UVLOZ ... VBUS_PRESENT_STAT is set to 1. 150 ms (typical) later, REGN is turned on". Switching follows poor-source and D+/D- detection (DS §7.3.4 steps 5-8, p.26). Fig 8-5 (p.136) shows charge current about 0.5-0.6 s after input (figure reading).
- **ACFET1/RBFET1 (Q1/Q2 CSD17581Q3A):** bypass them with JP3/JP4 installed and JP1/JP2 on pins 2-3 (ACDRV to GND) (UG Table 1-3). This avoids a second, IC-timed hot-plug of VBUS through the ACFETs. The IC then locks DIS_ACDRV = 1 (DS Table 7-5 p.30).
- **Snubber note:** the UG §1.3 note recommends RSNUB/CSNUB only for hot-plugging adapters above 15 V. The RT1987 ramp (12 V/ms) is not a hot-plug step. Leave them DNP; scope it at bring-up.
- **Status: PROVEN_CALC.**

### 2.9 H9: I2C, logic, status pin
- **Address:** 7-bit **0x6B**. Standard and fast mode. "Register read beyond REG48 returns 0xFF". Timeout of 1.5 s on an incomplete transaction (DS §7.3.14 p.53). No other device is on the bus ([SPEC] §3.2), so there is no conflict. Firmware is hard-coded to 0x30 today.
- **Levels:** VIH 1.3 V, VIL 0.4 V, VOL 0.4 V at 5 mA (EC pp.15-16). Abs max -0.3 to 6 V (DS p.7). The 3.3 V bus is fine.
- **EVM pull-ups:** R39 (SCL), R40 (SDA), R41 (INT) and R42 (CE) are 10 k to **PULLUP**. PULLUP = TLV76033 (U2) fed by R35 10 Ω from the BAT54 diode-OR (D11 from VBUS, D12 from BAT) through JP30 (UG Fig 4-6 p.20, BOM).
  - With the charger powered and the Teensy unpowered, R39/R40 back-power the Teensy through its I/O clamps (≤ 0.33 mA per line).
  - **Remove R39 and R40 (M4)** and keep the board RSDA/RSCL to Teensy 3V3.
  - Keep JP30 and R42: CE's fail-safe pull-up needs the PULLUP rail.
- **Unpowered-charger pin behaviour:** clamping of SDA/SCL with the IC unpowered is not specified. UNKNOWN, but moot with M8, since the IC is then always powered from BAT.
- **STAT:** open drain, 6 mA abs max sink. LOW = charging. HIGH = complete, disabled, HIZ or battery-only. 1 Hz blink = fault (DS Table 7-11 p.48, Table 5-1 p.4).
  - Remove the JP32 LED shunt (D13 via R38 2.21 k to PULLUP).
  - Pin 6 uses `INPUT_PULLUP`, or add 10 k to 3V3.
  - Use REG1C CHG_STAT and REG20/21 as the primary readiness source (as with the Ag105 Table 6). STAT HIGH cannot distinguish "complete" from "HIZ" or "unpowered".
- **Pin 5 repurposed** as CHG_EN (active HIGH) through the M2 NFET. The CSV row rename comes first, per CLAUDE.md.
- **Status: PROVEN_DATASHEET** (with M4; plus the bench check in §8).

### 2.10 H10: thermal, efficiency, wiring, mechanical
- **Efficiency** (DS Fig 6-4 p.18, 2S, 1.5 MHz, L = 1 µH, which is the EVM configuration with JP24 = 2S/1.5 MHz, R29 6.04 k, L2 1 µH). Figure readings, typical:

  | Input | At 2.5 A | Loss at 21 W out |
  |---|---|---|
  | 15 V | about 93 % | about 1.6 W |
  | 20 V | about 91 % | about 2.1 W |

  - At 1.8 A FC: about 1.1 W.
  - 750 kHz is about 1-1.5 points better (Fig 6-3), but "the 750 kHz switching frequency only works with the 2.2 µH inductor" (DS §8.2.2.2 p.133). The EVM has only the 1 µH L2 (L1 footprint 1 µH, DNP), so stay at 1.5 MHz.
- **Thermal:** RθJA 44.2 °C/W (JEDEC, DS p.8). TREG default 120 °C reduces charge current (DS §7.3.13.2 p.52). TSHUT 150 °C default.
  - FC charging is the sustained case. Regen is bursts of tens to hundreds of ms.
  - **B8:** sustained 1.8 A FC charge on the EVM at 15.9 V; log TDIE (REG41) and TREG_STAT.
  - The LM1084 next to the footprint is a heat source ([SPEC] §7). Off-board placement avoids it.
- **Mechanical:** the UG gives no EVM dimensions (layout figures only, pp.15-18). It carries five 5.08 mm terminal blocks, a micro-USB, about 33 jumpers and three headers (BOM), so it is far larger than the 32 × 35 mm footprint.
  - **Off-board on leads**, mounted to the chassis.
  - Leads: VCHG-IN and GND twisted (≤ 1.5 A); VCHG and GND twisted (≤ 2.5 A); SDA/SCL/CE/ILIM_HIZ/STAT/TS on a shielded or twisted bundle. Keep it as short as practical; size each pair ≥ 20 AWG.
  - **No bulk capacitor at the EVM end** (§2.8).
- **Status: BENCH_GATE** (B8 thermal).

### 2.11 H11: availability (2026-11-05, 17:39 UTC)

| Item | Status | Source |
|---|---|---|
| BQ25798EVM | **USD 156.45, inventory 162** | TI store |
| BQ25792EVM | inventory 131 (round 1 said out of stock: corrected) | TI store |
| IC BQ25798RQMR | inventory 143 526. Price USD 4.381 (1-99), 2.381 at 1 ku | TI store / product page JSON |
| Mouser, Farnell, Mikroe (Charger 25 Click, MIKROE-5839) | **not reachable** (§0). Price, stock and lead time UNKNOWN | - |

- Lead time: not published for in-stock TI store items.
- **Status: PROVEN_DATASHEET** (TI store).

### 2.12 H12: telemetry
- **ADC channels** (DS §7.3.10 p.47-48, EC pp.16-17, Tables 7-55 to 7-59 pp.113-118):

  | Channel | Range | LSB | Notes |
  |---|---|---|---|
  | IBUS (REG31) | 0-5 A | 1 mA | 2's complement, positive VBUS→PMID |
  | IBAT (REG33) | 0-8 A | 1 mA | positive for charging |
  | VBUS (REG35) | 0-30 V | 1 mV | |
  | VAC1/2 | 0-30 V | - | |
  | VBAT (REG3B) | 0-20 V | 1 mV | this is VCHG, not the pack |
  | VSYS | 0-24 V | - | |
  | TS | - | - | |
  | TDIE | - | 0.5 °C | |

- **Conversion time:** 24 / 12 / 6 / 3 ms per channel (15 / 14 / 13 / 12-bit nominal; 3 ms "not recommended"). With only IBAT + VBUS + IBUS enabled at 6 ms, a refresh takes about 18 ms (about 55 Hz). That is adequate for 50 Hz `I_charge` and for the G2 power term.
- **Limitations:**
  - **No ADC accuracy specification** exists in DS §6.5 (only resolution).
  - "ADC readings are only valid for DC states and not for transients" (p.47). A 30-50 ms regen pulse is a transient, so per-burst coulombs should come from the board's V_chg (pin 38) plus IBAT averaging, or from integrating IBAT in continuous mode (B9 calibration against a shunt).
  - ADC_EN POR 0 and is reset by the watchdog (Table 7-55), so firmware re-enables it after any WD event.
- **Status: PROVEN_DATASHEET** (availability and resolution). Accuracy UNKNOWN; B9.

## 3. Register map excerpt (driver)

| Reg | Field | Write | Why | Reset by |
|---|---|---|---|---|
| 0x00 | VSYSMIN[5:0] | ≤ 5.0 V | Avoid the 2 A BATFET-LDO clamp with VCHG < VSYSMIN | REG_RST |
| 0x01-02 | VREG[10:0] | 840 (8.400 V) | CV; read back ≤ 8.40 V | REG_RST |
| 0x03-04 | ICHG[8:0] | 177 (1.77 A FC) / 250 (2.5 A regen) | Charge current | **WATCHDOG**, REG_RST |
| 0x05 | VINDPM | 190 (19.0 V) regen / 150 (15.0 V) FC | Threshold. **Rewrite after every plug-in** | plug-in / unplug only |
| 0x06-07 | IINDPM[8:0] | 100 (1.00 A) FC / 130-150 regen | Input ceiling | REG_RST, plug-in detection |
| 0x08 | VBAT_LOWV[7:6] | 0h (15 %) | Fast charge from VCHG ≈ 6.6 V (M8) | REG_RST |
| 0x09 | STOP_WD_CHG[5] | 1 | WD expiry → EN_CHG = 0 | POR only (none listed) |
| 0x09 | ITERM[4:0] | per pack | Termination | WD, REG_RST |
| 0x0A | CELL[7:6] | leave 1h (2S) | Changing it resets ICHG/VSYSMIN/VREG | REG_RST (PROG) |
| 0x0F | EN_CHG[5], EN_HIZ[2], EN_ICO[4] | 1 / 0 / 0 | Normal; clear EN_CHG at termination | see §2.2 |
| 0x10 | WATCHDOG[2:0] | 1h (0.5 s) or 2h (1 s); kick WD_RST[3] each loop | Charger-side watchdog | REG_RST |
| 0x11 | AUTO_INDET_EN[6] | 0 | No D+/D- detection (500 ms-2 s) or IINDPM overwrite | REG_RST |
| 0x12 | EN_OTG[6], DIS_LDO[2], PFM_FWD_DIS[4] | 0 / 1 (optional) / per B4 | | WD/REG_RST |
| 0x13 | FORCE_VINDPM_DET[1], EN_IBUS_OCP[0] | 0 / 1 | | REG_RST |
| 0x14 | EN_EXTILIM[1] | 0 in regen mode if B6 shows a POR-latched clamp | ILIM_HIZ read as 100 mA when held LOW | REG_RST |
| 0x15 | EN_MPPT[0] | 0 | VOC MPPT stops the converter periodically | REG_RST |
| 0x18 | TS_IGNORE[0] | 1 if no NTC (re-write after WD) | | WD, REG_RST |
| 0x1B-0x21 | status / fault | read at 50 Hz | WD_STAT, PG_STAT, VINDPM_STAT, CHG_STAT, VBUS_OVP, IBUS_OCP, TSHUT | - |
| 0x2E | ADC_EN[7], ADC_SAMPLE[5:4] | 1, 2h (6 ms) | Telemetry | WD (ADC_EN) |
| 0x31/0x33/0x35/0x3B | IBUS / IBAT / VBUS / VBAT | read | `I_charge`, G2 | - |

The full map (REG00-REG48) is on DS pp.57-140. A 49-byte multi-read from 0x00 dumps it (§7.3.14.7 p.55).

## 4. Timing in words

1. **Pack connect (with M8):**
   - VCHG rises through R; the IC POR from BAT.
   - 5 ms later: PROG read (2S, 1.5 MHz).
   - 20 ms later: I2C live (DS §7.3.3 p.26).
   - The Teensy writes the static configuration (VREG, VSYSMIN, VBAT_LOWV, IINDPM, AUTO_INDET_EN = 0, EN_MPPT = 0, STOP_WD_CHG = 1, WATCHDOG 0.5 s, ADC) and reads it back.
2. **Run entry (regen mode):**
   - MOT_PWR is already closed. REGEN closes; D-BC-RG ramps VCHG-IN 0 → 15.9 V in about 1.3 ms.
   - VBUS_PRESENT is set. 150 ms later REGN comes on. Poor source then takes about 30 ms; PG_STAT = 1.
   - The ADC reads ILIM_HIZ (held LOW by the comparator, so a 100 mA clamp) and VBUS0 (15.9 V, so VINDPM = 14.5 V).
   - D+/D- detection is skipped (AUTO_INDET_EN = 0). About 30 ms later the converter would start, but ILIM_HIZ is LOW, so it does not.
   - The Teensy sees PG_STAT, writes VINDPM 19.0 V, EN_EXTILIM = 0 and IINDPM, reads them back, then raises P5 (CE LOW). PERMIT now follows the comparator.
3. **Braking burst:**
   - V-MOT rises from 15.9 V at 0.1-0.4 V/ms ([REGEN]: about 5.5 V in 19-47 ms).
   - At about 17.0 V (1.067 × VBUS) the comparator raises PERMIT and ILIM_HIZ is released. The converter resumes (latency B3/B4).
   - Below 19.0 V VINDPM throttles the input to zero. Above 19.0 V the converter draws up to IINDPM and charges at up to ICHG. With τ_warm short, V-MOT holds near 19 V ([REGEN]).
   - When regen ends, V-MOT falls. VINDPM unloads first; below 1.067 × VBUS - 0.30 V hysteresis the comparator pulls ILIM_HIZ LOW (stop latency ≤ 290 µs, B3).
4. **Cruise:** the converter is off. VCHG is held by M8. VINDPM stays at 19.0 V, because no plug-in occurred.
5. **Regen → FC transition:** [LOOP] §6 order.
   - P5 LOW, then REGEN off, BT_BUS off (existing `assertFcChargeEnable()` order), then FC_CHARGE on.
   - VCHG-IN stays above 3.2 V only if the switches overlap, which they must not. So VBUS falls below PRESENT and **this is a new plug-in**: VINDPM is re-measured (15.9 - 1.4 = 14.5 V) and must be rewritten to 15.0 V, along with IINDPM 1.00 A and ICHG.
   - In FC mode the ILIM_HIZ read sees the H2 permit (if P5 is HIGH by then), so the clamp can be resistor-set; otherwise the same as regen mode.
   - Then P5 HIGH.
6. **Watchdog / hang:** the Teensy stops kicking. After 0.5 s (nominal; accuracy unspecified) EN_CHG = 0. The [LOOP] H1/H2 gates were already holding independently.

## 5. EVM and board modifications (designators from UG Fig 4-5/4-6, BOM)

| ID | Mod | Reason |
|---|---|---|
| M1 | **Remove the JP17 shunt.** CE is now held HIGH by R42 10 k to PULLUP | Default charge-disabled (H3) |
| M2 | Add an NFET (e.g. 2N7002-class): drain to CE (TP36 /CE), source to AGND, gate = Teensy pin 5 via 1 k, 100 k gate pull-down. Pin 5 HIGH = charge enable. Rename the CSV row (e.g. `CHG_EN`) before any firmware change | Fail-safe CE independent of the Teensy rail; no 3.3 V into a REGN or PULLUP-referenced pin |
| M3 | ILIM_HIZ: keep the R23 100 k / R21 network (JP14), or change R21 for the chosen hardware ceiling (e.g. 150 k → about 2.0 V → about 1.25 A at REGN 5.0 V; 1.15-1.35 A over REGN 4.8-5.2 V). Add the [LOOP] §9 variant-(b) inhibit NMOS from ILIM_HIZ (TP33) to AGND, biased from REGN (TP27), released by PERMIT. JP21 stays open | Hard converter-off, fail-safe (H2/H3) |
| M4 | Remove R39 and R40 (SCL/SDA 10 k to PULLUP). Optionally R41 (INT unused). Remove the JP32 shunt (STAT LED) | No back-powering of the Teensy; STAT reads cleanly on pin 6 |
| M5 | Bypass the input FETs: JP3 + JP4 installed, JP1 + JP2 on 2-3 (ACDRV to GND). Feed VCHG-IN into J1 VIN1 (through R2 and JP3). Leave J2 unconnected and insulated (it is live via JP4) | No second hot-plug; IC in "VBUS input only" mode (DS §7.3.5.2) |
| M6 | Battery: JP5 installed, JP8 on 1-2 (bypass the ship FET Q5), JP9 on 2-3 (BATP at the BAT pin). J5-1 to the Ag105 VBAT+ pads (VCHG), J5-3 to GND | Removes Q5 and its 100 nA charge pump; CV at the IC |
| M7 | Replace C11, C12, C29, C30, C31 (10 µF 25 V X5R 0805) with ≥ 35 V X7R parts of similar or lower capacitance (keep the total ≤ about 50 µF nominal). Board C-D8/C-D10 likewise | V-MOT 21.4 V plus overshoot |
| M8 | **(Operator ruling)** 1.0 kΩ 0.25 W from VBT (C-D12) to VCHG, across D-BT-SQ. Firmware then sets VBAT_LOWV = 15 %, VSYSMIN ≤ 5 V | Keeps D-BT-SQ out of UVLO (avoids tD_ON 8 ms per burst); IC always powered and configured |
| M9 | TS: either wire J7 to the board J-NTC (10 k, B 3435 per [AG] p.9; the EVM REGN divider R18 5.23 k / R24 30.1 k is sized for a 103AT, B 3435, so it fits) and **remove JP18** (UG Table 1-3 p.5), or keep JP18 (simulated "normal"). TS_IGNORE resets on WD, so do not rely on it alone | Charge suspend on a hot pack |
| M10 | PROG: leave JP24 (2S, 1.5 MHz, R29 6.04 k). Never move a PROG jumper with power applied | POR VREG default 8.4 V, never 3S/4S |
| M11 | D+/D-: remove JP6, JP10, JP11; leave J6 unpopulated in use | No USB detection path |
| Board | Comparator, FC permit and logic per [LOOP] §9 (H1-H3), on a small carrier near the footprint; PERMIT and H1 readback to two spare Teensy pins (CSV first) | Loop impossibility |

## 6. Firmware impact specific to this IC
- **Replace the Ag105 driver:** `pollAg105`, `initAg105Charger`, `ag105IsReady`, the reg-0x02 MPPT manager and `J`.
- **New driver:**
  - Static configuration once per POR (with M8, once per pack connect).
  - Per-plug-in rewrite of VINDPM, IINDPM and ICHG, triggered by VBUS_PRESENT_FLAG/PG_FLAG (REG22).
  - WD_RST kick each loop, only after `detectFaults()`.
  - A verified-config gate before P5.
  - Clear EN_CHG at CHG_STAT = 111b.
  - 50 Hz reads of REG1B-21 and of the ADC.
- **Mode sequencer:** per [LOOP] §6. The FC-window entry is always a plug-in on this IC.
- **J-guard port:**
  - G1 (bus-side I_fc + I_batt), unchanged.
  - G2 adds the charger IBUS × VBUS term from REG31/REG35, about 55 Hz.
  - G3 maps to the REG20/21 faults: VBUS_OVP, IBUS_OCP, CONV_OCP, TSHUT, VSYS_SHORT, plus the CHG_TMR/TRICHG/PRECHG timers in REG1E.
- **Rewrite `J`:** per [LOOP] §13, the fw v37 rev 2 `J` session through MOT_PWR + REGEN with the BT boost on the bus closes the loop by construction. It must become an FC-path session.
- **`AG105_VBATN_ISOLATED`** becomes "charger return verified" (true for this EVM, §2.1). REGEN may then be held through Run **only** with [LOOP] H1 fitted.
- **MCU hardware watchdog** (operator ruling 5, [LOOP] §10): RTWDOG at 100 ms plus WDOG1 at 1.0 s; not on pin 19. It is **required future work** before the first unattended charger session.
  - The charger's own 0.5 s watchdog with STOP_WD_CHG is a complement, not a substitute. It stops charging, but it does not open the RT1987 paths and does not stop the motor.

## 7. Hardware inhibit stage (ILIM_HIZ, fail-safe)
[LOOP] §9 variant (b) applies directly:
- **Q2:** NMOS from ILIM_HIZ to AGND, gate pulled up to **REGN** (TP27) through 100 k. When REGN is up, ILIM_HIZ < 0.75 V and the charger is HIZ with REGN on.
- **Q1:** NMOS on Q2's gate, driven by PERMIT (3V3 logic) through 1 k with 100 k to GND.
- PERMIT HIGH turns Q1 on and Q2 off, releasing the pin to the R21/R23 divider (≈ 2.0-2.2 V = enabled, sets ILIM).
- Logic dead or PERMIT LOW means Q2 is on: inhibit.
- REGN down means the converter cannot run anyway (no gate drive, DS §7.3.4.1 p.26).
- **Divider loading:** ILIM_HIZ leakage is ±1.5 µA (EC p.12). With Q2 off (leakage nA) the divider value holds.
- **POR-read issue (H4/§1.2 item 4):** with Q2 on at qualification, the clamp reads 100 mA (DS §7.3.4.3: "lower than 1.08 V ... ILIM clamp to be 100 mA"). Hence EN_EXTILIM = 0 in regen mode, unless B6 shows the pin regulates continuously (EC p.12, VILIM_REG_RNG 1-4 V).

## 8. Bench gates (BQ25798-specific; [LOOP]/[REGEN] M-numbers in brackets)

| Gate | Test | Pass |
|---|---|---|
| B0 | Unpowered-charger I2C check without M8: board pull-ups live, charger unpowered, measure SDA/SCL and current into the EVM | No clamp below VIH; < 50 µA |
| B1 | I(VCHG-IN) from a stiff 15.9 V and 18.5 V source: VINDPM 19.0 V, P5 HIGH, ILIM_HIZ released (and held LOW) | ≤ 5 mA; no IBAT |
| B2 | VINDPM retention: write 19.0 V, cycle ILIM_HIZ 1000×, dip the input to 12 V and back, read REG05 | Unchanged |
| B3 [M2] | Inhibit latency: IBAT/IBUS at 2.5 A, step ILIM_HIZ LOW (and CE HIGH) | IBUS < 10 % in ≤ 290 µs at 1.5 A input |
| B4 [M-R4] | Warm step: idle at Vth - 0.5 V (ILIM released, CE LOW), step the input to Vth + 1 V from a stiff source. Also the ILIM_HIZ-release case at Vth + 1 V | τ_warm ≤ 4 ms (10-90 % ≤ 9 ms); no soft-start or re-qualification visible |
| B5 | WD: WATCHDOG 0.5 s, STOP_WD_CHG = 1, charging; stop kicking | Charging stops; EN_CHG reads 0; time recorded (accuracy at 0.5 s unknown) |
| B6 | ILIM_HIZ dynamic: during charging, change the divider voltage 2.2 → 1.6 V | Does IBUS follow (dynamic) or not (POR-latched)? Decides EN_EXTILIM |
| B7 | D-BT-SQ with and without M8: cruise 5 s then burst; scope VCHG, VBT, IBAT | With M8, VCHG stays > 3.35 V and the first pack current appears ≤ 4 ms after the permit |
| B8 | Thermal: 1.8 A FC charge at 15.9 V for 30 min; regen burst train | TREG_STAT 0; TDIE logged |
| B9 | ADC accuracy: IBAT/IBUS/VBUS against a shunt and a DMM, DC and 50 ms pulses | Error recorded for the EMS |
| B10 [LOOP M1 etc.] | Comparator/permit/watchdog proofs per [LOOP] §12 | Per [LOOP] |

Scope-armed first bring-up remains good practice (operator ruling 4).

## 9. Round-1 claims re-checked: corrections

1. **Sources:** the datasheet is **SLUSDV2C** (rev. June 2026) and the EVM guide is **SLUUCB5E** (rev. July 2022). Both are confirmed and read.
2. **VINDPM maximum: 22 V, confirmed** (DS p.12, p.62). Round-1 showstopper 1 is cleared. 100 mV steps confirmed. Accuracy ±2 % at 18.6 V was not known in round 1.
3. **VINDPM auto-set:** the offset depends on **VBUS0 voltage**, not source power. VBUS0 - 1.4 V when VBUS0 ≥ 7 V; VBUS0 - 0.7 V below 7 V (DS §7.3.4.4 p.27). Round 1 said "low-power vs high-power source": wrong. VINDPM is **not** reset by REG_RST or the watchdog; it resets to 3.6 V at unplug (Table 7-17).
4. **VAC_OVP:** options 26/18/12/7 V and the 26 V default are confirmed. **It only switches the ACFET-RBFET pairs.** With the input FETs bypassed, the only converter-stopping input OVP is the fixed VBUS_OVP 25.2-26.2 V. Round 1's "VAC_OVP = 18 V as an FC-mode runaway block" is void in this configuration. DS Table 4-1 still prints 22 V (erratum).
5. **Cold start was badly underestimated:**
   - Round 1 said about 90-120 ms.
   - Primary: REGN turns on **150 ms** after VBUS_PRESENT; poor source takes about 30 ms; D+/D- detection takes **500 ms-2 s** with AUTO_INDET_EN = 1; then 30 ms (DS §7.3.4 p.26, §7.3.4.5 p.27-28). Fig 8-5 shows about 0.5-0.6 s.
   - In addition, with VCHG ≈ 0 there is the 1.5 s trickle (§7.3.9.2 p.42).
   - This is moot for regen under the always-powered design. It applies at Run entry and FC entry.
6. **Poor-source retry is 7 minutes** (not "7 or 10"). An EN_HIZ = 0 write, or a re-plug, forces a retry (DS §7.3.4.2 p.27).
7. **VREG accuracy at 8.4 V is -0.25/+0.65 %**, not ±0.4 % (EC p.11). ICHG 50 mA-5 A / 10 mA confirmed; IINDPM 100 mA-3.3 A / 10 mA confirmed.
8. **POR ICHG is 1 A for every cell count** (DS rev C §7.3.2 Table 7-2 and §7.3.9.1). The EVM UG jumper text (JP22-JP25 "2 A ICHG") is stale.
9. **CE active-low confirmed** (VIH 1.3 V / VIL 0.4 V), **EN_CHG POR 1 confirmed**. New: the EVM ships with **JP17 installed, so CE is grounded and charging is enabled.**
10. **Watchdog:**
    - Options 0.5/1/2/20/40/80/160 s and the 40 s default are confirmed.
    - New: **STOP_WD_CHG** (REG09[5]) makes expiry set EN_CHG = 0.
    - Expiry resets ICHG to 1 A and EN_CHG, but **not** VREG, IINDPM or VINDPM. Round 1's hazard "WD reset of VINDPM with a hung Teensy" is void.
    - The specified accuracy is only for 160 s (136-160 s).
11. **I2C address 0x6B confirmed.** The 1.5 s transaction timeout is new.
12. **STAT open-drain, LOW = charging, confirmed.** A 1 Hz blink means fault.
13. **ILIM_HIZ:**
    - V = 1 V + 0.8 Ω × ILIM, confirmed.
    - The HIZ threshold, unverified in round 1, is **< 0.75 V stop, > 1 V resume, with REGN on.**
    - New: the pin is read at qualification, and a value < 1.08 V gives a 100 mA clamp.
    - Round 1's "no hard-off threshold" weakness is withdrawn: ILIM_HIZ is a hard converter-off pin.
14. **"Toggle EN_HIZ on each regen burst" is withdrawn.** It would force poor-source retry and ICO and turn REGN off. Gate with ILIM_HIZ instead.
15. **The EVM input capacitance, unverified in round 1, is 50.2 µF nominal (VBUS + PMID), all 25 V X5R ceramics, with no electrolytic** on the BQ25798EVM. The 33 µF polymers C33/C34 are on the BKUPEVM only; C25 33 µF tantalum is DNP.
16. **EVM pull-ups go to a 3.3 V TLV76033 rail fed from VBUS and BAT**, not to 5 V. They still back-power, so remove R39/R40.
17. **"Registers lost on every input-power loss"** holds only without M8. The IC also has a separate BATP sense pin (EVM JP9), which round 1 missed.
18. **BQ25792EVM "out of stock at TI": now 131 in stock.** BQ25798EVM: USD 156.45, 162 in stock. Round 1's "about EUR 154, about 12 wk lead time" is superseded; no lead time is shown for in-stock items.
19. **The VOC MPPT is disabled at POR, confirmed.** New: it cannot be enabled while VBAT < VSYSMIN (§7.3.6.3 p.34).
20. **Abs max VBUS 30 V and 3.6-24 V operating confirmed.** New: SYS 23 V abs max, BAT 20 V.
21. **TS:** the EVM uses an REGN divider (R18 5.23 k / R24 30.1 k) plus a "normal" simulation jumper JP18. TS_IGNORE exists but is reset by the watchdog.
22. **The IC does not switch during the RT1987 ramp, confirmed.** The figure is 150 ms + 30 ms + (D+/D-) + 30 ms, not "≥ 20-50 ms".
23. **The round-1 "Fit 5.5/10, regen weak because of cold start" framing is superseded.** Under the always-powered design the regen question becomes the warm response (B4) plus the board-level D-BT-SQ UVLO issue (§2.7).

## 10. Missing primaries (operator to fetch)
- **Mouser and Farnell** product pages for BQ25798EVM, BQ25792EVM and BQ25798RQMR: price, stock, lead time. Both hosts fail (HTTP/2 error and timeout with curl; DNS with WebFetch).
- **Mikroe Charger 25 Click (MIKROE-5839, BQ25792):** product page, schematic, BOM, CE and pull-up wiring, cell jumper and capacitor ratings. www.mikroe.com does not resolve.
- **TI BQ25792 datasheet SLUSDG1:** not fetched. Needed only if the Click or the BQ25792EVM is chosen. DS Table 4-1 differences: no MPPT or backup; ACOVP default 7 V on the BQ25790. Verify the BQ25792 defaults.
- **TDK C2012X5R1E106K125AB DC-bias curve:** effective input C (H8 margin).
- **BQ25798 dynamic data absent from the DS:** ILIM_HIZ exit/entry latency; VINDPM loop bandwidth; watchdog accuracy at 0.5 s; ADC accuracy; HIZ (REGN-on) VBUS draw; whether ILIM_HIZ regulates continuously. These are bench gates B1-B9, or a TI E2E/app note if one exists.
- **RT1987:** whether UVLO recovery with EN high repeats tD_ON (DS-00 is silent; [SPEC] §3.4). Decides whether M8 is mandatory.
- **Cross-cutting items carried from [LOOP]/[REGEN]:**
  - NXP i.MX RT1060 RM (watchdog, reset-cause register, pad states);
  - PJRC reset and boot timing;
  - 74LVC1G datasheets;
  - VESC Six EDU `l_max_vin`, fault-stop time and input capacitance.
