# Dossier A2: TI BQ25731EVM (BQ25731 I2C 1-5S buck-boost charge controller, no battery FET)

Round 2, 2026-11-05. Path A candidate. The sibling is the BQ25730EVM (same PCB with Q5 BATFET fitted).

## Sources (all read this round, local copies in `scratchpad/charger_eval/datasheets/`)

| Tag | Document | Notes |
|---|---|---|
| [DS] | TI SLUSE66A, "BQ25731 I2C 1- to 5-Cell Buck-Boost Battery Charge Controller with USB-C PD 3.0 OTG Output", June 2020, rev. Jan 2021. Page = printed page number (equals PDF page) | Read in full: §7-§12, registers |
| [UG] | TI SLUUCB9A, "BQ2573X Evaluation Module", June 2020, rev. Jan 2021 | Read in full. Schematic Fig 3-8 (p.20) was rendered to PNG at 200 dpi and read visually (`r2/a2/sch-20.png`, crops c1-c4) |
| [TI-WEB] | https://www.ti.com/tool/BQ25731EVM, fetched 2026-11-05 with curl (`r2/a2/tool.html`) | Price attribute `price="156.45"`. Inventory needs a login |
| [LOOP] | `r2/loop_analysis.md` (this round) | H1/H2/H3 backstops, M-gates, inhibit stage (b) |
| [REGEN] | `r2/regen_dynamics.md` (this round) | τ_warm ≤ 4 ms requirement, V-MOT rise rates |
| [SPEC] | `docs/reviews/charger_eval_2026-11-05/spec.md` | Board interface at the Ag105 pads |

Not obtainable: Mouser (DNS blocked in this session: `www.mouser.com` must be allowed), Farnell/Newark (connection timeout), the TI
store stock count (login-gated). See `missing_primaries` at the end.

Number conventions: "[DS] p.10" is a datasheet value. "calc" is my arithmetic from datasheet values. "fig-read" is a value read off a
datasheet plot (about ±0.5 percentage points). Nothing here comes from recollection or search snippets.

---

## 0. Verdict

**FEASIBLE_WITH_CONDITIONS for Path A.** The BQ25731EVM supports every structural requirement:
- a common ground, with high-side sense on both input and battery;
- a real hard-inhibit **pin** (ILIM_HIZ < 0.4 V turns the converter off);
- no battery FET, so there is no supplement/NVDC path into the pack;
- 26 V operating and 32 V absolute maximum ratings;
- VINDPM programmable over I2C up to 19.52 V;
- 2S/8.4 V CV at ±0.6 %, and 2.5 A at about 96 % efficiency.

Six conditions apply:
1. **EVM modifications** (§6). Four are load-bearing:
   - cut the input capacitance from 113 µF to about 41 µF nominal (Death-5 / OC_FC budget);
   - add the charger-side inhibit stage on ILIM_HIZ ([LOOP] §9 stage b);
   - fix the OTG pin low;
   - remove the EVM's I2C and CHRG_OK pull-ups to its own 3V3 rail.
2. **[LOOP] H1/H2/H3 are mandatory, not optional.** The BQ25731 cannot stop charging on its own when the host is lost:
   - its watchdog is at least 4 s, and on expiry it loads **256 mA**, not 0 A ([DS] p.33, p.42);
   - its POR state is CHRG_INHIBIT = 0 (charge enabled) and VINDPM = VBUS − 1.28 V, i.e. below the bus ([DS] p.42-44, p.26).
3. **Bench gate M2 (HIZ latency and register retention).** Needed values:
   - ILIM_HIZ-low to input-current-zero ≤ about 290 µs;
   - ILIM_HIZ-high to regulating within the regen head-start budget (§4);
   - a host-written VINDPM must survive a HIZ cycle. [DS] §9.3.6 says a no-load VBUS measurement runs "right before the converter is enabled" and does not say whether that overwrites the host value.
4. **Bench gate M4 (warm response, τ_warm ≤ 4 ms).** No loop-bandwidth figure exists in [DS].
5. **Firmware write-mask.** Never set EN_PTM (pass-through would tie VCHG-IN directly to the pack), EN_OTG, EN_LEARN, AUTO_WAKEUP_EN, or RESET_REG during operation. Always write the RSNS bits before any current register.
6. **MCU hardware watchdog (RTWDOG + WDOG1), recorded as REQUIRED FUTURE WORK** (operator ruling 5, [LOOP] §10). The BQ25731's own watchdog cannot replace it (condition 2).

No requirement is a FAIL.
- **H11 (availability)** is partly unverified: the TI price is primary, but the stock count and the Mouser/Farnell listings are missing.
- **H2, H4 and H10** close only on bench gates.

---

## 1. Requirement matrix

| Req | Status | Evidence (citations) | Bench test if gated |
|---|---|---|---|
| **H1** common ground, high-side sense, no unregulated path | PROVEN_DATASHEET | Grounds: J1-1 (VIN PGND), J5-1 (VBAT PGND) and J6-2 (VSYS PGND) are all PGND; PGND/GND are joined at net-tie NT1 ([UG] Table 1-1 p.2-3, Fig 3-8 p.20). Input sense **R1** 5 mΩ sits in VIN+ between the input caps and Q1 drain (ACP/ACN through R11/R12 4.99 Ω, C46/C47 33 nF, C11 10 nF). Charge sense **R2** 5 mΩ sits in BAT+: VSYS → R46 (0 Ω, fitted on the BQ25731EVM) → C28 → R2 → J5 VBAT. SRP/SRN go through R15/R16 10 Ω, C27 0.1 µF ([UG] Fig 3-8; BOM note 1 p.12: "BQ25731EVM, install R46 and do not install Q5"). Nothing sits in the return. No unregulated path: there is no battery FET ([DS] p.1, p.4 "BATFET power path: No") and no ACFET driver pin ([DS] Table 7-1 p.5-7). Q6/Q7 (P-FET input pair) are bypassed by **R8** 0 Ω (fitted, [UG] BOM p.11). With the converter off: VBUS → SW1 is blocked by the Q1 body diode (cathode at VBUS); SYS → SW2 is blocked by the Q4 body diode (cathode at VSYS) ([DS] Fig 10-1 p.83, Table 9-3 p.27; standard N-FET orientation) | – |
| **H2** hard inhibit while powered | BENCH_GATE (mechanism proven; latency not in [DS]) | Mechanisms: (1) **ILIM_HIZ pin < 0.4 V → HIZ, converter shuts off; > 0.8 V exits** ([DS] p.6, p.17 VHIZ, §9.3.8 p.26-27). (2) EN_HIZ (0x35 bit7, I2C). (3) FORCE_CONV_OFF (0x30 bit3): latches the converter off on CMPOUT falling, POR default 0, needs I2C to arm and clear ([DS] p.59-60). (4) CHRG_INHIBIT (0x00 bit0) and ChargeCurrent = 0 stop the charge, but **the converter keeps operating**: "if charge is disabled the converter should keep operating" ([DS] §9.3.21.5 p.34); UG §2.4.1 p.9 shows VSYS regulated with no battery. These do not qualify as hard inhibits. (5) EN_LEARN shuts the converter off (I2C). Only (1) is a pin. All current into the battery pin stops in HIZ: the converter is off and there is no BATFET or supplement path (H1). Pre-charge (384 mA clamp below VSYS_MIN, [DS] p.10, §9.6.2.1 p.46) and AUTO_WAKEUP (128 mA, 0x30 bit0, default 0) are converter functions and also stop in HIZ. POR default is **not HIZ** on the EVM: R19 383k / R27 220k from VDDA put ILIM_HIZ at about 2.2 V ([UG] p.9 step 3, Fig 3-8), so the inhibit stage of §6 is mandatory. Response time is not specified | **M2:** step ILIM_HIZ 2.2 V → 0 V at 1.5 A input; capture input current. Pass ≤ 290 µs × (1.5 A / I_in) to < 10 mA ([LOOP] §4.3). Also measure HIZ-exit to regulating |
| **H3** fail-safe | PROVEN_DATASHEET, with conditions (§6 inhibit stage plus RTWDOG future work) | (a) Teensy reset / high-Z: the RT1987 EN pull-downs open D-BC-FC and D-BC-RG ([SPEC] §3.1), and P5 is pulled down. Stage (b) Q2 is biased from the charger's own **VDDA** and pulls ILIM_HIZ < 0.4 V, so the charger is HIZ whenever it has any power. (b) Hung Teensy with pins latched HIGH: the charger watchdog is **4 / 5.5 / 7 s** min/typ/max at the shortest setting ([DS] p.18, WDTMR_ADJ 01b p.42). On expiry ChargeCurrent becomes **256 mA**, not 0 ([DS] §9.3.21.1 p.33; Table 9-8 p.42). [DS] §9.6.2 p.45 lists "watchdog event" among the 0 A resets, which contradicts this; the conservative reading is 256 mA. So the charger alone does **not** stop. [LOOP] H1 limits charging to genuine regen, and in the FC window the CV loop (8.4 V) bounds it. The RTWDOG reset (future work) then drops every pin. (c) I2C dead/stuck: the charger releases the bus after 25-35 ms (tTIMEOUT, [DS] p.18) and keeps its last registers. Inhibit is by pin only (H1/H2/P5), independent of I2C. (d) POR defaults: CHRG_INHIBIT = 0, i.e. **charge enabled** ([DS] p.44). ChargeVoltage = 8.400 V from the 2S strap ([DS] Table 9-2 p.26, p.47). ChargeCurrent: [DS] contradicts itself: text and figure say 0 A, while the header "reset = 0080h" and Table 9-11 bit 7 reset = 1 mean **256 mA** (p.45). VINDPM = no-load VBUS − 1.28 V ([DS] p.26, p.79). IIN_HOST = 3.2 A (5 mΩ) / 3.25 A (10 mΩ) (p.80). WDT = 175 s (p.42). **Without the inhibit stage, an unconfigured EVM on V-MOT can charge at up to 256 mA with VINDPM below the bus.** Pulls needed: P5 47 k to GND on the carrier; Q2 gate 100 k to VDDA; Q1 gate 100 k to GND ([LOOP] §9); OTG pin tied to GND (JP2 fitted or a hard short; R45 pulls it to 3V3 otherwise, [UG] Fig 3-8); JP6 left open; JP3(3-4) 2S strap | Read back 0x03/02 right after POR (resolves 256 mA vs 0). M6 ([LOOP]) with the charger connected |
| **H4** input-voltage threshold (regen and FC) | BENCH_GATE (range/accuracy proven; warm response and retention not in [DS]) | Register 0x0B/0Ah: **3.2-19.52 V, 64 mV LSB**, 8-bit, offset 3.2 V, R/W at runtime ([DS] Table 9-7 p.40, §9.6.21 p.79, §9.3.6 p.26). Accuracy is characterized at three points only: 18.688 V −3.5 %/+2 % (**18.03-19.06 V**), 10.88 V −4.5 %/+3 %, 4.48 V −8 %/+5.5 % ([DS] p.10). Regen: code 247 = 19.008 V; extrapolating the 18.688 V tolerance gives 18.34-19.39 V. That is 0.84 V above the fw OV latch 17.5 V, **0.04 V above the TPS61288 OVP minimum 18.3 V**, and 2.0 V below the 21.4 V clamp (calc). Code 255 = 19.52 V gives 18.84-19.91 V (extrapolated), which fits the [SPEC] §4 window 18.3-20.0 V. **The ceiling 19.52 V cannot exceed the TPS61288 OVP maximum 19.5 V with margin**, so a failed-FB bus is covered only by H1 ([LOOP] §7). FC mode: 13.504 V (code 161) or 15.04 V (code 185) are both settable. Draw at or below the threshold: in the [LOOP] design the charger is in HIZ during cruise. HIZ quiescent with input present is not specified ("low quiescent current mode with REGN LDO enabled", [DS] p.26). Converter enabled with no load: 2.2 mA typ (PFM buck, VIN 20 V, VBAT 12.6 V; IAC_SW_LIGHT_buck, [DS] p.11). Warm response: no bandwidth or transient figure in [DS]. Only the charge soft-start is given: 64 mA steps every 8 µs "during charge enable", about 0.31 ms to 2.5 A (calc from [DS] p.17). Deglitch: none is described for VINDPM re-entry. CHRG_OK's 50 ms deglitch applies to VBUS crossing 3.5 V ([DS] p.5), which V-MOT never does in Run. **Risk R-1:** "Charger initiates a VBUS voltage measurement without any load right before the converter is enabled" ([DS] §9.3.6 p.26). If HIZ exit re-runs this and overwrites the host VINDPM, the regen threshold is lost on every H1 cycle. Harvest would then fail (no loop: H1 still holds) | **M2** (VINDPM read-back after 10 HIZ cycles and after an input brown-out) and **M4** ([REGEN]): with the charger HIZ-gated by a simulated H1 edge, step the input from Vth − 0.5 V to Vth + 1 V; measure from the ILIM_HIZ release and from the Vth crossing to 63 % of ICHG. Pass: τ_warm ≤ 4 ms after the Vth crossing, and HIZ-exit to converter running ≤ head-start (§4, ~6 ms worst case) |
| **H5** FC charging | PROVEN_DATASHEET (capability); the FC budget is a board condition | Input 3.5-26 V ([DS] p.9). Charge current 0-8.128 A at 64 mA LSB (10 mΩ) or 0-16.256 A at 128 mA LSB (5 mΩ) ([DS] p.45, §9.3.5 p.25). CV 1.024-23.0 V, 8 mV LSB; **8.400 V ±0.6 %** (0-85 °C, [DS] p.9). [SPEC] asks ±0.5 %; the ±0.5 % headline applies at ≥ 12.6 V only. Termination is **host-controlled**: there is no autonomous termination and no auto-recharge; the host sets CHRG_INHIBIT or ChargeCurrent = 0 ([DS] §9.4.1 p.35). ICHG accuracy at 5 mΩ is poor at our currents: 2048 mA −12/+13.5 %, 1024 mA −18/+21.5 % ([DS] p.10). Recommend a 10 mΩ RSR (mod A3): 2 A then gives the same 20 mV sense voltage as the 4096 mA / 5 mΩ row (−5/+6 %). That is an inference from equal sense voltage, not a 10 mΩ datasheet row. Budget: 2.0 A × 8.4 V / 0.965 / 15.8 V = **1.10 A input** (η fig-read [DS] Fig 8-3 p.19, VIN 15 V, VOUT 7.4 V). With 0.15 A aux that is 1.25 A FC bus-side, under the 1.4 A OC_FC latch but over the [SPEC] 1.0 A budget. A 1.0 A input limit through IIN_HOST (code 20 at 10 mΩ = 0x1400; max reading +100 mA, [DS] p.80) gives about 1.8 A out | FC-window charge at IIN_HOST 1.0 A: measure I_fc peak (incl. window-open transient) < 1.3 A |
| **H6** voltage ratings / OVP | PROVEN_DATASHEET | VBUS/ACP/ACN recommended 0-26 V; abs max **32 V** (SW 32 V; BTST/HIDRV 38 V) ([DS] p.8). ACOV rise **26.0/26.8/27.7 V**, 100 µs deglitch, converter off. Fall 25.0/25.8/26.7 V, 1 ms deglitch, then auto-resume ([DS] p.14, §9.3.21.2 p.33). At the 21.4 V clamp: 4.6 V below recommended max, 10.6 V below abs max, 4.6 V below ACOV min. **No mid-burst drop-out** unless V-MOT > 26 V. [SPEC] requires abs max ≥ 30 V (met); 36 V preferred (not met). EVM part ratings on the input: Q1-Q4 AON6362 30 V; input MLCC 35 V; Ta 35 V; Z1 SMAJ26CA (26 V standoff; breakdown not read) ([UG] BOM p.10-12). SYSOVP for 2S is 11.7/12/12.2 V, **latching** ([DS] p.14, §9.3.21.4 p.34), far above 8.4 V. Board side, not EVM: C-D8/C-D10 are 25 V parts, so replace them with ≥ 35 V ([SPEC] §2.2) | – |
| **H7** battery pin through D-BT-SQ | PROVEN_DATASHEET (bench confirmation listed) | No battery detection by voltage: cell count and "present" come from the **CELL_BATPRESZ strap** (JP3 3-4 = 2S, [UG] Table 1-2 p.3; [DS] Table 9-2 p.26). The charger therefore starts into the open/capacitive VCHG node. [UG] §2.4.1 p.9 regulates VSYS to 8.4 V ±0.5 V into a 1 A load with no battery. CV sense is SRN = EVM J5 side = VCHG, upstream of D-BT-SQ. The pack therefore sees CV − 35-50 mV ([SPEC] §2.2), i.e. 8.35-8.365 V nominal. With 8 mV LSB the CV could be trimmed to 8.440 V. Worst case +0.6 % gives 8.491 V at the charger and ~8.456 V at the pack, under the 8.5 V fw OV latch (calc). Operator's call. Start from 0 V: VSYS < 1.6 V → IIN_DPM forced to 0.5 A until VSYS > 1.6 V (UVP latch only after 3 min, [DS] §9.3.21.8 p.34). VSRN < VSYS_MIN (6.6 V for 2S) → 384 mA clamp ([DS] p.10, p.46). The ~150 µF output node charges in about 3 ms (calc), then D-BT-SQ conducts. No BATFET exists, so the NVDC/BATFET questions do not apply. **Do not bridge D-BT-SQ.** It is not needed. Bridging would keep the charger battery-powered (it powers from VBAT above 2.55 V, [DS] §9.3.1 p.24), which preserves registers, but it removes the hard pack disconnect. Caveat: with charge disabled, the converter regulates VSYS (to VSYS_MIN by inference, not stated). That stays below the 7.4 V pack floor, so D-BT-SQ stays off. A pack below ~6.6 V would then receive current that ChargeCurrent does not limit; HIZ covers this | Confirm: (i) cold start into the 0 V VCHG node with D-BT-SQ fitted; (ii) with CHRG_INHIBIT = 1 and the pin released, the VSYS regulation level, and the pack current at VBT = 7.4 V (expect 0) |
| **H8** inrush / hot-plug | PROVEN_CALC (after mod A1) | EVM input as built: C3, C4, C42, C43, C23, C24, C44, C45 = 8 × 10 µF 35 V X5R 0805 (GRM21BR6YA106KE43L), plus **C53 33 µF Ta**, plus C18 1 µF behind R3‖R4 (1.95 Ω), plus C25 0.47 µF behind R13 1 Ω, plus C12/C17 11 nF ([UG] BOM p.10-11, Fig 3-8). **113.5 µF nominal.** RT1987 ramp 12 V/ms → 12 mA/µF ([SPEC] §6) → **1.36 A** + board 0.24 A + aux 0.15 A = 1.75 A > OC_FC 1.4 A (calc, no DC-bias derating; derating not read). **Mod A1:** remove C53, C23, C24, C44, C45 → 41.5 µF nominal → 0.50 + 0.24 + 0.15 = **0.89 A ≤ 1.0 A budget** even with zero derating. This meets [SPEC] C_chg ≤ 50 µF effective. There is no ACFET/RBFET, so no input-FET turn-on into SYS caps. With ILIM_HIZ held low at POR the converter does not start during the ramp. When released, the converter starts with IIN_DPM 0.5 A while VSYS < 1.6 V ([DS] p.34) and the 384 mA clamp. Death-5 class: not reproduced (41 µF ≪ 470 µF). Converter input capacitance after the mod: 4 × 10 µF; [DS] Fig 10-1 uses 6 × 10 µF. Input ripple ≈ ICHG·√(D(1−D)) ≈ 1.25 A rms at 16 → 8.4 V, 2.5 A (calc from [DS] Eq 4 p.85). Within four 0805 MLCCs; verify ripple on the bench | FC-window open with the mod: scope I_fc and VCHG-IN, no OC_FC trip |
| **H9** I2C / logic / status pin | BENCH_GATE (only the unpowered leakage is open) | Address **0x6B** (7-bit; D6h/D7h) ([DS] §9.5 p.35, p.4). The bus has no other device. Firmware is hard-coded to 0x30 ([SPEC] §3.2), so change it. ManufacturerID 0x40 at 0x2E, DeviceID 0xD6 at 0x2F (p.82): use them as a probe. SDA/SCL VIL 0.4 V, VIH 1.3 V, abs max 7 V ([DS] p.17, p.8), so 3.3 V is fine. fSCL 10-400 kHz (p.18); fw 100 kHz. Back-powering: the EVM pull-ups **R35, R32** (SDA/SCL, read from Fig 3-8) go to the EVM's own 3V3. That rail comes from LM3480 U2 via JP8, fed from VBUS/BAT through D2/D3. When the EVM is unpowered they would load the Teensy bus through 10 k into a dead rail. **Remove R35/R32** and use the board's RSDA/RSCL. Status: **CHRG_OK** is open-drain active-high (input 3.5-25.8 V and no fault), 50 ms rising deglitch, abs max 7 V ([DS] p.5, §9.3.4 p.25). Remove EVM pull-up **R33** (CHRG_OK to EVM 3V3, Fig 3-8). Pull pin 6 up to Teensy 3V3 (10 k on the carrier, or `INPUT_PULLUP` after a CSV entry). Unpowered SDA/SCL/CHRG_OK leakage (pin-to-supply structures with the IC unpowered) is not specified ([DS] gives 1 µA at 7 V powered only) | With the charger unpowered and its input open, measure the SDA/SCL idle level and current from the Teensy 3V3 pull-ups (pass ≥ 3.1 V, ≤ 50 µA) |
| **H10** thermal / efficiency / wiring / mechanical | BENCH_GATE (thermal proven; lead/ripple and mechanical need measurement) | Efficiency fig-read [DS] Fig 8-3/8-4 p.19 (4.7 µH, 400 kHz, 5 mΩ/5 mΩ, VOUT 7.4 V): VIN 15 V: ~96.7 % at 2.5 A, ~93.5 % at 1 A. VIN 20 V: ~95.7 % at 2.5 A, ~91 % at 1 A, < 82 % below ~0.25 A. Loss at 16 → 8.4 V, 21 W out: **~0.75 W**. At 21 → 8.4 V, 2.5 A: **~0.95 W** (calc). Regen operating points of 11-19 W ([REGEN]) sit at 1.3-2.3 A, i.e. 94-96 %. Inductor L1 is rated 13 A / 9 mΩ max ([UG] BOM p.11), so it has large margin. θJA 37.2 °C/W ([DS] p.9); controller dissipation is small (FETs external). Mechanical: board dimensions are **not given in [UG]**. The board carries four DFN5x6 FETs, a 10 × 10 mm inductor, three 5.08 mm terminal blocks, J2/J4 blocks, J3/J7 headers and jumpers, so it cannot fit the 32 × 35 mm footprint ([SPEC] §7). → **Off-board on leads** (or hovering on a pad carrier). Leads: J1 VIN/PGND ↔ pads 10/4; J5 VBAT/PGND ↔ pads 18-19/14-15; J3 SDA/SCL/GND ↔ pads 8/7; CHRG_OK (TP28/J2) ↔ pad 3. Twisted pairs ≤ ~15 cm. The 12 V/ms RT1987 ramp rules out a cable-LC hot-plug spike ([DS] §10.2.2.1 p.84 concerns adapter plug-in), so keep the R3/R4/C18 damper and add no bulk capacitance | Lead test at 2.5 A: VCHG ripple < 50 mVp-p at the D-BT-SQ pad ([SPEC] §2.2 chatter limit); EVM temperature rise in the enclosure; measure EVM outline for mounting |
| **H11** availability | UNKNOWN_MISSING_PRIMARY (partial) | [TI-WEB]: BQ25731EVM listed with `price="156.45"` (USD, TI store), "Order now"; the stock figure is behind a login. BQ25730EVM same price attribute. The task header reports TI store stock 54 (BQ25731EVM) / 29 (BQ25730EVM) on 2026-11-05; I could not verify this (login). Mouser: DNS blocked in this session. Farnell/Newark: timeout. Lead time: not shown. No EV2400 is needed (the Teensy is the I2C host; [UG] p.1 lists it for BQstudio only) | Operator: confirm stock and lead time on ti.com / Mouser / Farnell |
| **H12** telemetry | PROVEN_DATASHEET (rate-limited; analog pins recommended for the J-guards) | I2C ADC (8-bit; [DS] p.40-41, §9.6.7-9.6.10 p.54-58): VBUS 0-24.48 V at 96 mV LSB; ICHG 64 mA LSB (10 mΩ) / 128 mA (5 mΩ); IDCHG 256/512 mA; IIN 50 mA (10 mΩ) / 100 mA (5 mΩ); VSYS/VBAT 64 mV (2.88 V offset for 1-4S); PSYS; CMPIN. **Conversion time 25 ms max per channel**, one-shot or continuous every 1 s ([DS] ADCOption p.70). Four channels take ~100 ms, so 50 Hz is not achievable over I2C; ICHG alone one-shot gives ≤ 40 Hz. ADC is off by default (0x3A = 00h). Analog outputs: IBAT pin 8×/16× (SRP−SRN), ±2 %/±4 % at 40.96/20.48 mV; IADPT pin 20×/40× (ACP−ACN), ±2 %/±3 % ([DS] p.12, §9.3.16.1 p.28). IBAT buffer is off by default (EN_IBAT 0x31 bit7). For the EMS (30-50 ms regen pulses, [REGEN]) and for G2 (20 ms window), wire **IBAT and IADPT to Teensy ADC pins**. They are clamped < 3.3 V, so they are Teensy-safe. This needs spare analog pins entered in the IO CSV first. G3 maps to ChargerStatus 0x20 faults (ACOV/BATOC/ACOC/SYSOVP/VSYS_UVP/Force_Converter_Off, [DS] p.50) | – |

---

## 2. Round-1 claims re-checked (corrections)

Round 1 had no dedicated BQ25731 dossier. Its claims about this part are in `charger_replacement_evaluation_2026-11-05.md` §3.1 and in
the [SIB] tags of the BQ25720 and BQ25773 dossiers.

| Round-1 claim | Location | Round-2 finding |
|---|---|---|
| "26 V operating" | eval §3.1 | **Confirmed**: VBUS/ACP/ACN recommended 0-26 V; VINPUT_OP 3.5-26 V ([DS] p.8-9) |
| "32 V abs max per TI listing" | eval §3.1 | **Confirmed** from the datasheet: SRN/SRP/ACN/ACP/VBUS/VSYS −0.3 to 32 V ([DS] p.8) |
| "SRP/SRN high-side" | eval §3.1 | **Confirmed**; also the RAC input sense is high-side (EVM R1/R2, [UG] Fig 3-8) |
| "EVM appears out of stock" | eval §3.1 | **Corrected**: [TI-WEB] shows Order now at $156.45; the task header reports 54 in stock. The count is unverified by me (login) |
| "ICHG/VINDPM UNVERIFIED" | eval §3.1 | **Now verified**: ICHG 0-16.256 A / 128 mA (5 mΩ), 0-8.128 A / 64 mA (10 mΩ); VINDPM 3.2-19.52 V / 64 mV ([DS] p.40, 45, 79) |
| "BQ25720EVM fills the same niche" (reason for rejection) | eval §3.1 | **Superseded**: the BQ25731 has a pin hard-inhibit, no BATFET, and a 1-5S range. It stands on its own merits; the reason for rejection is void |
| "Recommended VBUS max 26 V [SIB] BQ25731 layout" | BQ25720 dossier l.35 | **Confirmed for the BQ25731** ([DS] p.8). Note: the source is §8.3, not the layout section |
| "1-5 cell I2C parts are the BQ25730 and BQ25731" | BQ25773 dossier l.28 | **Confirmed** ([DS] title, p.1, p.4) |
| "sibling 3.2-19.52 V / 64 mV encoding belongs to BQ25720/BQ25731" | BQ25773 dossier l.64 | **Confirmed for the BQ25731** ([DS] §9.6.21 p.79) |
| Family: watchdog expiry "zeroes ChargeCurrent" | BQ25720 dossier l.92 | **Wrong for the BQ25731**: expiry loads **256 mA** ([DS] §9.3.21.1 p.33; Table 9-8 p.42); §9.6.2 p.45 contradicts itself |
| Family: ChargeCurrent POR 0 A (BQ25713 C3 example) | [LOOP] C3 | **Ambiguous for the BQ25731**: text and figure say 0 A; header 0x0080 and the Table 9-11 bit reset say 256 mA ([DS] p.45). C3 is not proven by the register default. The pin stage carries C3 |
| Family: ILIM_HIZ < 0.4 V Hi-Z / > 0.8 V exits | BQ25720 dossier l.59 | **Confirmed for the BQ25731** ([DS] p.6, p.17) |
| Family EVM: "ILIM_HIZ HIGH = disable" (713 EVM) | BQ25720 dossier l.94 | **Not the case on the BQ2573x EVM**: J2-ILIM_HIZ is "Logic LOW to enable HIZ mode", JP6 shorts it to GND ([UG] Table 1-1/1-2 p.3). The default with JP6 open is enabled (2.2 V) |
| Family: VSYS_MIN register 3Eh, 2S default 6.6 V | BQ25720 dossier l.86 | **Different on the BQ25731**: 6.6 V for 2S is a CELL-strap value ([DS] Table 9-2 p.26). Register 0x3E is VSYS_TH2 (VAP/PROCHOT), not VSYS_MIN ([DS] §9.6.18 p.74) |
| Family: converter power-up 150 ms after VBUS | BQ25720 dossier l.122 | **Not stated for the BQ25731**: only "5 ms ... reset registers ... another 5 ms ... accessible" ([DS] §9.3.1 p.24). The converter-enable delay is unspecified, so it goes in M2 |
| Family: CHRG_OK 50 ms deglitch | BQ25720 dossier l.113 | **Confirmed** ([DS] p.5) |
| Family: host-controlled termination | BQ25720 dossier l.70 | **Confirmed** ([DS] §9.4.1 p.35) |
| Family: pre-charge ≤ 384 mA below VSYS_MIN | BQ25720 dossier l.86 | **Confirmed** ([DS] p.10, §9.6.2.1 p.46) |
| Family: no TS/NTC input | BQ25720 dossier l.117 | **Confirmed for the BQ25731**: no TS pin in Table 7-1 ([DS] p.5-7). THERM pad 13 stays unused, or use CMPIN as an NTC comparator (optional) |
| Implicit: charger threshold above 19.5 V possible | – | **No**: maximum 19.52 V ([DS] p.79), same as the BQ25720 ([LOOP] §0 item 4) |

Document inconsistency noted: [UG] calls the EVM "NVDC-1" and the TI page says "N-channel MOSFET selector", but [DS] p.1/p.4 says no
battery MOSFET, and the BQ25731EVM BOM fits R46 instead of Q5. The datasheet and BOM govern. [UG] BOM vs schematic: the BOM lists C49
fitted / C56 DNP, while Fig 3-8 shows C49 DNP / C56 fitted. Both sit on the charger output side, so this does not affect H8.

---

## 3. Register map excerpts (10 mΩ RAC/RSR assumed after mod A3; 16-bit little-endian word, LSB register first)

| Reg | Name | Field / encoding | POR | Use |
|---|---|---|---|---|
| 0x01/00 | ChargeOption0 | bit15 EN_LWPWR (1); bits14:13 WDTMR_ADJ (00 off, 01 5 s, 10 88 s, 11 175 s); bit4(lo) EN_LEARN; bit1 EN_IIN_DPM; **bit0 CHRG_INHIBIT** (0 = charge enabled) | 0xE70E | Write EN_LWPWR = 0 (needed for ADC); WDTMR 01; CHRG_INHIBIT = 1 until configured ([DS] p.42-44) |
| 0x03/02 | ChargeCurrent | bits12:6 × 64 mA (10 mΩ); 2.496 A = 39 → **0x09C0**; 1.792 A = 28 → 0x0700 | 0 A or 256 mA (contradictory) | Write after ChargeVoltage. Resets to 0 on adapter removal, RESET_REG, ChargeVoltage = 0 ([DS] p.45) |
| 0x05/04 | ChargeVoltage | bits14:3 × 8 mV; 8.400 V = **0x20D0** ([DS] p.9 row) | 8.400 V (2S strap) | Write first ([DS] p.47) |
| 0x0B/0A | InputVoltage (VINDPM) | bits13:6 × 64 mV + 3.2 V. 19.008 V = 247 → **0x3DC0**; 19.52 V = 255 → 0x3FC0; 13.504 V = 161 → **0x2840** (check: 0x3C80 = 18.688 V, [DS] p.10) | VBUS_noload − 1.28 V | Regen / FC threshold; read back every time ([DS] p.79) |
| 0x0F/0E | IIN_HOST | bits14:8 × 50 mA (10 mΩ); 1.0 A = 20 → **0x1400**; 1.3 A = 26 → 0x1A00. Code 0 = 50 mA. Max = nominal + 100 mA | 3.25 A (10 mΩ) | FC-mode input cap; the effective limit is the lower of this and the ILIM_HIZ pin (EN_EXTILIM = 1) ([DS] p.80, p.6) |
| 0x21/20 | ChargerStatus | hi: STAT_AC, IN_VINDPM, IN_IIN_DPM, IN_FCHRG, IN_OTG; lo: ACOV, BATOC, ACOC, SYSOVP(R/W), VSYS_UVP(R/W), Force_Conv_Off, OTG_OVP/UVP (latched until read) | 0 | G3 fault class; readiness ([DS] p.49-50) |
| 0x31/30 | ChargeOption1 | 0x31: bit7 EN_IBAT, bits5:4 PSYS_CONFIG, **bit3 RSNS_RAC, bit2 RSNS_RSR** (1 = 5 mΩ), bit0 EN_FAST_5MOHM. 0x30: bit7 CMP_REF, bit6 CMP_POL, bits5:4 CMP_DEG, **bit3 FORCE_CONV_OFF**, **bit2 EN_PTM (never set)**, bit1 EN_SHIP_DCHG, bit0 AUTO_WAKEUP_EN (keep 0) | 0x3F00 (header) / 0x3300 (figure) | Write RSNS = 0 before any current register ([DS] p.59-61) |
| 0x33/32 | ChargeOption2 | 0x32 bit7 EN_EXTILIM (1 = pin limit active), bit3 EN_ACOC | 0x00B7 | Keep EN_EXTILIM = 1 so the resistor ceiling holds ([DS] p.62-63) |
| 0x35/34 | ChargeOption3 | 0x35: **bit7 EN_HIZ**, bit6 RESET_REG, bit5 RESET_VINDPM, **bit4 EN_OTG (never)**; 0x34: bit5 OTG_VAP_MODE, bits4:3 IL_AVG (00 = 6 A) | 0x0434 | Set IL_AVG = 6 A ([DS] p.64-65) |
| 0x3B/3A | ADCOption | ADC_CONV (cont. 1 s), ADC_START, channel enables | 0x2000 | ([DS] p.70) |
| 0x26-0x2D | ADC results | VBUS 96 mV; ICHG 64 mA; IIN 50 mA; VBAT/VSYS 64 mV + 2.88 V | – | ([DS] p.54-58) |
| 0x2E / 0x2F | ID | 0x40 / 0xD6 | – | Probe ([DS] p.82) |

**Init order (per input power cycle, lazy, as `pollAg105()` today):**
1. Probe the ID registers.
2. ChargeOption1: RSNS bits to 0, EN_PTM to 0.
3. ChargeOption0: EN_LWPWR 0, WDT 5 s, CHRG_INHIBIT 1.
4. ChargeOption3: IL_AVG 6 A.
5. ChargeVoltage 0x20D0.
6. IIN_HOST.
7. InputVoltage.
8. ChargeCurrent.
9. ADC enable.
10. **Read back every register**, then CHRG_INHIBIT 0.
11. Only after step 10 may P5 go HIGH.

Feed the watchdog by rewriting ChargeCurrent at least every 3 s.

Write-mask: refuse EN_PTM, EN_OTG, EN_LEARN, AUTO_WAKEUP_EN, RESET_REG, RESET_VINDPM and EN_FRS outside State 98, and in State 98
allow them only behind the same verified-config gate as [LOOP] F2.
- **EN_PTM** (Q1 + Q4 on, [DS] §9.4.3 p.35) would put VCHG-IN (16-21 V) directly on the pack. Whether HIZ overrides PTM is unknown, so treat it as a forbidden write.
- **OTG** would drive VCHG-IN. The RT1987s block it toward the bus. The OTG pin is tied low.

---

## 4. Timing in words

**Run entry (always-powered regen mode):**
1. REGEN (pin 30) closes. RT1987 tD_ON is 8 ms and the ramp (10-90 %) about 1.4 ms ([SPEC] §5). PERMIT is LOW, so ILIM_HIZ < 0.4 V and the charger stays in HIZ.
2. Charger POR at VBUS > 2.55 V. Registers are reset after 5 ms and accessible after another 5 ms ([DS] §9.3.1 p.24).
3. Firmware runs the init list (~3 ms over loop ticks) and the read-back.
4. Firmware sets P5 HIGH. ILIM_HIZ still follows H1. In cruise V-MOT ≈ VBUS, so H1 = 0 and the charger stays in HIZ.

**Brake:**
1. V-MOT rises from 15.9 V to ~21.35 V in 19-47 ms, i.e. **116-287 V/s** ([REGEN], calc).
2. H1 rises at about 1.067 × VBUS + 0.30 V, roughly 17.3 V at VBUS 15.9 V ([LOOP] §9).
3. Q1 turns on and Q2 turns off. ILIM_HIZ rises through the R19/R27 divider (τ ≈ 140 kΩ × 100 pF C35 = 14 µs).
4. The charger exits HIZ (latency L_x unknown, M2) and sits in VINDPM until V-MOT crosses Vth (19.0 V).
5. **Head start** from H1 to Vth: (19.0 − 17.3) V / (116-287 V/s) = **5.9-14.7 ms** (calc). Requirement: L_x + converter start ≤ ~6 ms worst case, then τ_warm ≤ 4 ms after the Vth crossing ([REGEN]).
6. Charge current rises at the charge-loop rate (no [DS] figure; soft-start, if it re-applies, is 64 mA per 8 µs ≈ 0.31 ms to 2.5 A, [DS] p.17). V-MOT is then held at about Vth.

**Brake end:**
1. Regen current falls. V-MOT drops to Vth, VINDPM reduces the charge current, and V-MOT keeps decaying toward the bus.
2. H1 falls at about 1.067 × VBUS − 0.16 V. ILIM_HIZ goes low through Q2 and the charger enters HIZ in L_in, which must be ≤ 290 µs ([LOOP] §4.3, M2).
3. If L_in is longer, D-MT-EN carries bus current only for the excess: a single bounded pulse ([LOOP] §4.3).

**FC window:** switch order per [LOOP] §6:
1. P5 LOW (HIZ).
2. REGEN and BT_BUS LOW (`assertFcChargeEnable()`).
3. FC_CHARGE HIGH, with the ramp onto 41.5 µF.
4. Charger POR or retained config; write VINDPM 13.504 V and IIN_HOST 1.0 A, then read back.
5. H2 permit (hardware).
6. P5 HIGH.

Reverse the order on exit. Charge current is 0 on every input loss (adapter-removal reset, [DS] p.45), so the firmware must
re-write it on every entry.

---

## 5. Hazards specific to this part

| ID | Hazard | Mitigation |
|---|---|---|
| R-1 | Host VINDPM possibly overwritten by the "no-load VBUS measurement before converter enable" at HIZ exit ([DS] §9.3.6) | M2 read-back. If it is overwritten: no loop (H1), but harvest is lost. Fallback: in Run keep ILIM released while VINDPM is verified (losing H1 as the gate), or move to another charger. Operator decision after M2 |
| R-2 | Watchdog expiry loads 256 mA, not 0 ([DS] p.33) | Hardware P5/H1/H2; RTWDOG (future work) |
| R-3 | POR: charge enabled, ChargeCurrent possibly 256 mA, VINDPM below the bus | ILIM_HIZ stage biased from VDDA; init with CHRG_INHIBIT = 1 before P5 |
| R-4 | EN_PTM ties the input to the pack | Firmware write-mask; FAULT on STAT_PTM (0x3C bit0) read-back |
| R-5 | Converter runs with charge disabled (VSYS regulation): current into a pack below VSYS_MIN is not limited by ChargeCurrent | Pack floor 7.4 V (UV latch); HIZ outside permitted windows; H7 bench check |
| R-6 | ICHG/IIN accuracy at 5 mΩ is −12/+13.5 % at 2 A and ±200 mA at 0.8 A ([DS] p.10) | Mod A3 (10 mΩ). Board INA253 currents remain the safety measurement |
| R-7 | VINDPM ceiling 19.52 V cannot clear the TPS61288 OVP maximum 19.5 V | H1 comparator ([LOOP] §7) |

---

## 6. EVM modifications (designators from [UG] Fig 3-8 / BOM)

| # | Change | Why |
|---|---|---|
| A1 | **Remove C53 (33 µF Ta), C23, C24, C44, C45** (4 × 10 µF). Keep C3, C4, C42, C43, the R3/R4/C18 damper, R13/C25 and C11/C12/C17 | Inrush 1.36 A → 0.50 A (H8) |
| A2 | Keep **R8** (0 Ω) fitted; Q6/Q7 and their driver (Q9, Q10, R9, R10, R14, R17, C22, Z1) stay bypassed. Optionally remove Q6/Q7/Z1 | RT1987s already block reverse; no input FET is needed |
| A3 | Replace **R1 and R2** (5 mΩ) with **10 mΩ** 1 % 1 W 1206; firmware writes RSNS_RAC = RSNS_RSR = 0 first | Regulation/ADC accuracy at 1-2.5 A ([DS] §9.3.5 p.25); IIN_HOST max becomes 6.35 A, ample |
| A4 | Retune ILIM ceiling: keep **R19** 383 k, change **R27** 220 k → **139 k** (at RAC 10 mΩ: VILIM ≈ 6 V × 139/522 = 1.60 V → 1.5 A; REGN 5.7-6.3 V gives 1.29-1.70 A, [DS] p.10 REGN, p.6 formula) | Hardware input ceiling (C2 of [LOOP]); regen needs ≤ 1.15 A at 19 V for 2.5 A out (calc) |
| A5 | Add inhibit stage (b) ([LOOP] §9): **Q2** (2N7002-class) drain to ILIM_HIZ (TP22), source GND, gate 100 k to **VDDA** (TP19); **Q1** drain to Q2 gate, gate = PERMIT via 1 k + 100 k to GND. **JP6** stays open; nothing drives J2-ILIM_HIZ | Fail-safe HIZ biased from the charger's own rail (H2/H3) |
| A6 | **OTG pin tied to GND**: JP2 fitted, preferably replaced by a solder short, or remove R45 | Prevents OTG/VAP enable (R45 10 k pulls OTG/VAP to 3V3) |
| A7 | JP3 (3-4) = 2S strap fitted; JP4 open; J2-CELL_control unconnected | Correct CV/SYSOVP defaults; prevents a "battery removed" reset |
| A8 | Remove **R35, R32** (I2C pull-ups to EVM 3V3) and **R33** (CHRG_OK pull-up). CHRG_OK goes to pad 3 with a 10 k pull-up to Teensy 3V3 | No back-powering or dead-rail loading (H9) |
| A9 | J6 (VSYS) left unconnected; J5 → VBAT+ / VBAT− pads | SYS = battery node on this part |
| A10 | Board side (not EVM): C-D8/C-D10 → ≥ 35 V; carrier logic for H1/H2/P5 per [LOOP] §9; spare ADC pins for IBAT/IADPT entered in the IO CSV | [SPEC] §2.2; H12 |
| A11 | Optional backstop: CMPIN on a V-MOT divider with FORCE_CONV_OFF armed by firmware (latching off above, e.g., 23 V; CMP_DEG 5 µs). It is not fail-safe at POR (default disarmed) | Extra overvoltage stop ([DS] p.59-60) |

---

## 7. MCU hardware watchdog: REQUIRED FUTURE WORK (operator ruling 5)

Path A with the BQ25731 **requires** a Teensy 4.1 hardware watchdog. The charger's own watchdog cannot replace it:
- its minimum period is 4 s;
- on expiry it loads 256 mA rather than zero ([DS] p.18, p.33).

Adopt the [LOOP] §10 design:
- RTWDOG at 100 ms as the primary;
- WDOG1 at 1.0 s as the independent second timer, with its output **not** routed to pin 19 (I2C SCL);
- after a watchdog reset, latch `ERR_MCU_WDT` and require acknowledgement before Run.

Bench proof M6: a forced hang must reset within the timeout, with every EN < 0.6 V, PERMIT LOW and ILIM_HIZ < 0.4 V.

Carry this into the feasibility study and the fw roadmap as a blocking item for the first unattended charger session.

---

## 8. Bench gates for this candidate (in order)

1. **B0:** probe 0x2E/0x2F; read the POR value of 0x03/02 (resolves 0 vs 256 mA); read POR VINDPM.
2. **M2:** HIZ entry latency (≤ 290 µs × 1.5 A / I_in); HIZ exit to regulating; VINDPM and other register retention across 10 HIZ cycles and an input brown-out.
3. **M4:** warm response through the H1-style HIZ release (head-start ~6 ms + τ_warm ≤ 4 ms).
4. **H7 check:** cold start into the 0 V VCHG node through D-BT-SQ; charge-disabled VSYS level; zero pack current at VBT 7.4 V.
5. **H8 check:** FC-window open after mod A1, I_fc peak < 1.3 A, no OC_FC.
6. **H9 check:** unpowered I2C idle level ≥ 3.1 V.
7. **H10:** lead test, VCHG ripple < 50 mVp-p at 2.5 A, thermal.
8. Inherited from [REGEN]/[LOOP]: M-R0 to M-R3 (VESC cut-off mechanism, V-MOT capacitance, CV-load test) before any charger purchase decision rests on harvest numbers. M1, M6, M7, M8.

---

## missing_primaries

- Mouser and Farnell/Newark listings for BQ25731EVM (stock, price, lead time). `www.mouser.com` is not in the session's allowed network; Farnell timed out.
- TI store stock count (login-gated).
- BQ25731EVM board outline dimensions (not in SLUUCB9A).
- Murata GRM21BR6YA106KE43L DC-bias curve (effective input C). H8 is closed at nominal (worst case) without it.
- AON6362 (EVM Q1-Q4) datasheet: VDS 30 V from the BOM only.
- Littelfuse SMAJ26CA (EVM Z1) breakdown and leakage.
- TI LM3480 (EVM U2) input range.
- BQ25731 HIZ entry/exit latency, HIZ quiescent current with input present, VINDPM/charge-loop transient response: not in SLUSE66A.
- Whether a host-written VINDPM survives HIZ exit or brown-out: not stated in SLUSE66A.
- BQ25731 errata or TI clarification for the ChargeCurrent POR value (0x0000 vs 0x0080) and the watchdog result (0 vs 256 mA). SLUSE66A contradicts itself.
- Unpowered SDA/SCL/CHRG_OK pin leakage.
- Inherited from [LOOP]/[REGEN]: NXP i.MX RT1060 Reference Manual (watchdog), Teensy 4.1 reset pad states, 74LVC1G datasheets, TL431, VESC Six EDU `l_max_vin` / fault-stop / input capacitance, RT1987 turn-off delay.
