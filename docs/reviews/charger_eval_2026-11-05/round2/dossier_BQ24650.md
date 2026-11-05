# Dossier R2: TI BQ24650 / BQ24650EVM-639 (HPA639A) as the Path A replacement for the Ag105

Round 2, 2026-11-05. Written against the operator rulings of 2026-11-05: regen and FC charging are both
HARD; Path A is preferred but must be fully feasible; R3 relaxed to "no adverse behaviour"; the
always-powered design is accepted; an MCU hardware watchdog is required future work. Cross-reads
`loop_analysis.md` and `regen_dynamics.md` in this folder.

## 0. Sources (all primary, read in full where they bear on a requirement)

| Tag | Document | Notes |
|---|---|---|
| [DS] | TI SLUSA75B, BQ24650 data sheet, Jul 2010, rev. Jan 2020 (library `BQ24650_ds.pdf`, 32 pp.) | Page numbers = PDF page = printed page |
| [UG] | TI SLUU444A, bq24650EVM user's guide, Aug 2010, rev. Oct 2010 (library `BQ24650EVM_ug_SLUU444.pdf`) | Fig. 8 schematic (p.17) is a raster image. It was rendered at 400 dpi (`r2/bq650/sch-17.png`, `hi-17.png`) and read by eye. Designators and values below come from it and from the BOM (p.10) |
| [TIW] | ti.com/product/BQ24650 and ti.com/tool/BQ24650EVM-639, fetched 2026-11-05 with curl (saved as `r2/bq650/ti_product_BQ24650_20261105.html`, `ti_tool_BQ24650EVM-639_20261105.html`) | Price tables are in the page's JSON. Stock needs a TI login |
| [LA] / [RD] | `r2/loop_analysis.md`, `r2/regen_dynamics.md` | Board-side requirements (290 µs inhibit budget, τ_warm ≤ 4 ms, comparator H1/H2/H3) |
| [SPEC] | `docs/reviews/charger_eval_2026-11-05/spec.md` | Board interface at the Ag105 pads |

Not obtainable this session: Mouser and Farnell (WebFetch: DNS not allowed; curl: HTTP/2 INTERNAL_ERROR, then
timeout), DigiKey (HTTP 403). See `missing_primaries`.

## 1. What the part is (verified)

- A stand-alone synchronous buck charge controller with external NMOS-NMOS FETs at 600 kHz (510-690 kHz)
  ([DS] p.1, EC p.9). **There is no I2C, no register, and no host watchdog.** The 16 pins are listed in [DS] p.4-5.
- Every parameter is set by resistors:
  - VBAT = 2.1 V·(1 + R2/R1) ([DS] §8.3.1, eq. 1, p.13).
  - I_CHG = 40 mV / RSR ([DS] §8.3.3, eq. 3, p.14). I_PRECHG = I_TERM = 4 mV / RSR ([DS] eq. 4-5, p.14).
  - Input-regulation ("MPPT") set point V_IN = 1.2 V·(1 + R3/R4) ([DS] §8.3.2, eq. 2, p.14).
- Charge enable is the MPPSET pin: below 75 mV disables, above 175 mV enables ([DS] p.4, EC p.7, §8.3.2, §8.3.18).
- Status is two open-drain pins, STAT1 and STAT2 ([DS] Table 2, p.18).

### 1.1 The EVM as built ([UG] Fig. 8 p.17, BOM p.10, Table 2-3 p.3)

| Function | Designators / values | Factory setting |
|---|---|---|
| Input terminal | J1-1 VIN, J1-2 PGND | 5-28 V ([UG] Table 3) |
| Input damper | R1 ∥ R2 = 3.9 Ω ∥ 3.9 Ω in series with C4 2.2 µF/35 V, VIN to GND | Same network as [DS] Fig. 16 |
| Input reverse diode | **D1 PDS1040 (40 V, 10 A Schottky), anode J1-VIN, cathode VSYS** | - |
| VSYS rail | Q1A drain; C1 10 µF, C2 10 µF (35 V X7R 1210); C3 1 µF 35 V. VCC is fed through R3 10 Ω (R4 open), C5 1 µF | Brought out on J2-4 VSYS |
| Battery-to-system diode | **D3 PDS1040, anode VBAT, cathode VSYS** | Lets the battery feed VSYS when VIN is absent |
| Power stage | Q1 Si7288 (dual N, 40 V, 19 mΩ); L1 10 µH IHLP2525CZ (102 mΩ, 7 A); D2 ZLLS350 bootstrap diode with R5 2.2 Ω; C6 0.1 µF BTST cap | - |
| Current sense | **R6 20 mΩ** (WSLP1206, 0.1 %) between L1 and VBAT, i.e. in the **BAT+ leg**. SRP is at the L1 end; SRN is at the VBAT end through R7 0 Ω; C12 and C14 filter | 2 A ([UG] eq. 3, p.4) |
| Output | VBAT = J2-3 VOUT; C7 10 µF 35 V, C8 1 µF 35 V, C11 0.1 µF 50 V | - |
| CV divider | R13 499 kΩ (VBAT, via R10 0 Ω, to VFB) and R15 100 kΩ (VFB to GND); C15 22 pF across R13 | **12.6 V** ([UG] eq. 1, p.3) |
| MPPSET divider | **R17 499 kΩ from J1-VIN (before D1)** and R19 36 kΩ to GND; C17 22 pF across R17 | **17.8 V** ([UG] eq. 2, p.3) |
| Charge enable | **Q2 2N7002: drain on MPPSET, source GND, gate = /CE net**. /CE is pulled up to VREF by R18 100 kΩ. JP4 shorts /CE to GND | **JP4 OFF = charger disabled** ([UG] Table 2) |
| TS | R9 5.23 kΩ (VREF to TS) and R12 30.1 kΩ (TS to GND), R11 100 Ω to the pin. JP1 selects J2-TS (1-2) or R14 10 kΩ "internal valid TS" (2-3) | JP1 1-2 |
| TERM_EN | JP3: 2-3 = VREF (enabled), 1-2 = GND (disabled) | Termination enabled |
| Status | STAT1 drives D4 and STAT2 drives D5 (LEDs), each through 10 kΩ (R20, R21) to LEDPWR. **JP2 ties LEDPWR to VIN** | JP2 ON |
| Ground | J1-2 PGND, J2-3 PGND and every return use the same ground symbol. There is no shunt or jumper in the negative leg | - |
| PCB | HPA639, 3 in × 3 in × 0.062 in | Gerbers available as SLUC264 ([TIW]) |

## 2. Requirement matrix

| # | Requirement | Status | Evidence (primary) | Bench test / condition |
|---|---|---|---|---|
| H1 | Common ground; current sense in BAT+ or the input leg; no unregulated path | **PROVEN_DATASHEET** | [UG] Fig. 8: J1-2 PGND and J2-3 PGND are one ground net; sense R6 sits between L1 and VBAT (BAT+); D1 is in VIN+. [DS] p.4: one GND pin, which is the thermal pad. Non-converter paths: D3 and the Q1A body diode ([DS] §8.3.13) both run VBAT → VSYS, and D1 blocks them from J1-VIN. No element conducts from VIN to VBAT except the converter | Continuity check J1-2 ↔ J2-3 < 10 mΩ before first connection |
| H2a | Hard charge inhibit while powered: exists, stops all battery current, POR default | **PROVEN_DATASHEET** | MPPSET < 75 mV disables charge ([DS] p.4, EC p.7 V_MPPSET_CD, §8.3.18). It also resets all timers and faults (§8.3.18). With MPPSET disabled REGN reads 0 V and with it enabled REGN reads 6 V ([UG] §2.7.1-2.7.2 p.7; EC p.8 V_REGN_REG is specified only with MPPSET > 175 mV), so gate drive is absent. There is no BATFET, NVDC or supplement path. Pre-charge, trickle and the 125 mA detect pulse are converter currents and stop too. EVM POR default: JP4 OFF → Q2 on → disabled ([UG] Table 2). **Re-enable costs 1.5 s** (EC p.9 "Delay from MPPSET > 175 mV to charger is allowed to turn on") | Stop latency is not specified ([DS] Fig. 4, 10 ms/div, is qualitative). Bench M2 |
| H2b | Fast, reversible inhibit for comparator gating of each regen burst (≤ 290 µs × 1.5 A / I_in, i.e. ≤ ~530 µs at 0.82 A in and ≤ ~435 µs at 1.0 A in) | **BENCH_GATE** | MPPSET-to-GND cannot serve: every release costs 1.5 s. Usable mechanism: switch the MPPSET divider to an **unreachable threshold** (~45 V, §4.2), keeping MPPSET above 175 mV. [DS] §8.3.2 p.13: "If the MPPSET pin voltage is forced below 1.2 V, the BQ24650 stays in the input voltage regulation loop while the output current is zero." At zero duty neither FET turns on except the ~80 ns bootstrap refresh ([DS] §8.4.2 p.21; ramp offset 300 mV allows 0 % duty, §8.3.9 p.15). This is regulation-class, so the slow hard inhibit (H2a) stays as the state-level backstop | M2: step MPPSET from the run threshold to the 45 V tap with the charger at full current from a stiff 19.5 V supply; measure I_in < 10 mA latency |
| H3 | Fail-safe: (a) MCU reset / high-Z, (b) MCU hung, (c) I2C dead, (d) POR defaults | **PROVEN_CALC** (with the §5 mods; (b) relies on external backstops) | (a) Pin 5 pull-down (47 kΩ) → Q_drv off → /CE pulled to VREF by R18 → Q2 on → disabled. PERMIT_FAST is unpowered → Q_imp on (biased from charger VREF) → 45 V threshold. The RT1987 EN pull-downs also leave the charger unpowered ([SPEC] §3). (b) No charger watchdog exists ([DS] pin list p.4-5). A hang with pin 5 latched HIGH leaves the charger enabled, so the comparator stage (H1/H2 of [LA] §8) and the 19 V threshold are the only protection until the **MCU watchdog** (required future work, §8) resets the Teensy into case (a). (c) There is no I2C, so nothing depends on it. (d) There is no stored state; everything is resistor-strapped and identical at every POR. If enabled out of POR: 30 ms SLEEP-exit deglitch (EC p.7) + 1.5 s enable delay (EC p.9) + battery detection (≈ 1 s with D_byp, §4.4) → charges at 40 mV/RSR to the VFB CV. **Factory EVM CV is 12.6 V and must be reworked before first connection** | Forced-hang bench test of [LA] M6 with pin 5 HIGH: all EN < 0.6 V, Q2 gate HIGH, MPPSET < 75 mV |
| H4 | Input-voltage threshold for the always-powered regen mode | **BENCH_GATE** | Range: any value with VCC 5-28 V ([DS] EC p.6), resistor-set and continuous. Accuracy: ±0.6 % on 1.2 V (EC p.7). Plus MPPSET leakage ≤ 1 µA (EC p.7, worst case, into the pin, so it raises the threshold): 1 µA × 4.68 kΩ = +0.39 %. Plus 0.1 % divider ratio ±0.2 %. Result: **19.02 V nominal, 18.87-19.25 V**. That is 1.37 V above the fw OV latch (17.5 V), 1.67 V above the measured overshoot (17.2 V), 0.57 V above the TPS61288 OVP min (18.3 V), and 2.1 V below the VESC cut-off (21.35 V, [RD]). FC tap: 14.51 V (14.40-14.69 V). No I2C, so no runtime register. Hardware-switched taps (19.02 / 14.51 / ~45 V) by FETs. **The threshold cannot be reset by a POR** (resistor-strapped). This removes the [LA] finding-1 objection that applies to BQ25713/720/798/773. Below threshold: output current zero ([DS] §8.3.2). No qualification restarts while MPPSET stays > 175 mV: the stop conditions in §8.3.7 do not include input regulation, and STAT1 stays LOW (charging) ([DS] §8.3.2). Quiescent at the threshold is not specified: 0.7-1 mA disabled, 2-3 mA "charge done", 25 mA "charging, Qg 10 nC" ([DS] EC p.6). **Warm response is not specified.** Soft start runs "every time the charger goes into fast-charge" ([DS] §8.3.8). Input regulation is inside fast charge (STAT1 LOW), so by that reading it does not re-run; this is unverified. Loop: internal type-III, voltage mode, LC 12-17 kHz ([DS] §8.3.9 / §8.3.19; §8.4.1 says 17-25 kHz, so the DS contradicts itself). DCM at light load slows the loop (§8.4.2). The warm state also requires VCHG to be held above LOWV and the RT1987 UVLO (§4.4) | M-R4 warm step (Vth−0.5 V → Vth+1 V, stiff source, charger already enabled): pass if τ_warm ≤ 4 ms (≤ 2 ms if the node is board-only; ≤ 20 ms if 4 mF is confirmed). M-Q: input current from a stiff 16.0 V and 18.8 V source with the charger enabled at the 19.02 V tap and at the 45 V tap. Pass if < 30 mA and zero battery current |
| H5a | FC charging from VBUS (~15.9 V) via D-BC-FC with BT_BUS off; CV accuracy; termination | **PROVEN_DATASHEET** | VCC 15.9 V is inside 5-28 V (EC p.6). Dropout: input ≥ VBAT + ~1 V ([UG] p.3); 15.9 V vs 8.4 V is fine. I_CHG = 40 mV/RSR ±3 % (EC p.6). CV: 2.1 V ±0.5 % at T_J 0-85 °C, ±0.7 % at −40 to 125 °C (EC p.6), plus divider tolerance; VFB leakage ≤ 100 nA (EC p.6). Termination at 4 mV/RSR ±25 % with a 250 ms qualification (EC p.7). Set TERM_EN LOW (§5). The 14.51 V FC tap gives built-in power-follow: if the FC-fed bus sags to the tap, charge current falls ([DS] §8.3.2). Window entry costs 1.5 s only if pin 5 was LOW; it is kept HIGH through mode changes (§6) | FC bench: 15.9 V source through a 0.5 Ω droop emulator, measure I_in and I_chg at 1.667 A setting |
| H5b | Charge current programmable to ≥ 2 A within the FC input budget (≤ ~1.0 A in, [SPEC] 2.1A), runtime-adjustable by the EMS | **FAIL** | The current is set only by RSR ([DS] §8.3.3). There is no ISET pin, no register, and **no input current limit** (no such function in [DS] §8.3). 2.0 A out at 15.8 V in ≈ 1.17 A in plus aux, which breaks the FC budget. One RSR cannot serve both FC (≤ 1.71 A) and the regen ceiling ([RD]: 2.0 A covers 2 m/s, 2.5 A covers 3 m/s). The EMS lever is on/off only, with a 1.5 s turn-on after a hard inhibit | Mitigation (operator decision): RSR = 24 mΩ → 1.667 A (0.97 A in at 15.8 V, η 0.91); cap VESC "Battery Current Regen Max" ≈ 0.82 A (1.667 × 8.4 / (0.9 × 19)) so braking never outruns the charger. This loses regen capture above ~1.8 m/s × 12 A brakes. Not recommended: switched RSR (a single SRP/SRN pair; FET R_DS in the sense path) |
| H6 | Voltage ratings, OVP behaviour | **PROVEN_DATASHEET** | Abs max: VCC/SRP/SRN/STAT 33 V, PH 36 V, BTST/HIDRV 39 V, VFB 16 V, MPPSET 7 V ([DS] §7.1 p.5). Recommended: VCC 28 V, PH 30 V ([DS] §7.3 p.5). **ACOV 31/32/33 V**, 1 V hysteresis, 1 ms deglitch to disable, 20 ms to resume, non-latching (EC p.7-8, §8.3.12). So no dropout mid-burst at 21.4 V or at the VESC hardware ceiling of 27 V. EVM parts: input/output caps 35 V X7R, BTST/filter caps 50 V, Q1 40 V, D1/D3/D2 40 V ([UG] BOM p.10). The DS asks for 40 V FETs at 20-28 V input ([DS] §9.2.2.4), which Q1 meets. MPPSET at 27 V in with the 19 V divider = 1.70 V, inside 7 V. Board C-D8/C-D10 are 25 V ([SPEC]); swap to ≥ 35 V | - |
| H7 | Battery pin through D-BT-SQ: detection, CV, ~0 V at POR, BATFET/NVDC, bridging | **BENCH_GATE** | No BATFET/NVDC ([DS] §8.1-8.3). D-BT-SQ draws its supply from VCHG ([SPEC] §3.4). With the charger idle at zero current, VCHG (≈ 21 µF) decays through the VFB divider. Below VFB 1.55 V (6.2 V at VCHG, EC p.7) the charger is in pre-charge (C/10, 25 ms deglitch out); below 3.0-3.35 V D-BT-SQ drops into UVLO. Either of these destroys the warm response. A 30-min pre-charge timeout FAULT is possible ([DS] §8.3.4) if the timer runs during input regulation; this is not stated. VSRP < 2 V forces non-synchronous mode (EC p.8). Detection ([DS] §8.3.21, Fig. 12, EC p.8): 6 mA discharge for 1 s (the flowchart says 8 mA; the DS is inconsistent); if VFB < LOWV, 125 mA for 0.5 s; VFB > VRECH means absent and the routine retries. **Fix: D_byp, a small Schottky with anode on VBT (pack) and cathode on VCHG.** It holds VCHG at pack − ~0.3 V ≥ 7.1 V, so VFB ≥ 1.78 V > LOWV, D-BT-SQ stays biased, and detection resolves "present" when the 1 s timer expires. Do **not** bridge D-BT-SQ. Consequences of D_byp: pack drain ≈ VFB divider 42 µA + SLEEP ≤ 15 µA (EC p.6); the pack can now drive VCHG, but the Q1A body diode/D3 → VSYS path is blocked at J1 by D1; a D_byp short equals a bridged D-BT-SQ (benign) | M-B1: detection and first charge at 7.4 V and 8.2 V pack through D-BT-SQ, with and without D_byp. M-B2: 30 min idle in input regulation; check for any FAULT (STAT1 = STAT2 = OFF) |
| H8 | Inrush / hot-plug on the RT1987-ramped node | **PROVEN_CALC** | EVM input C: C1 + C2 = 20 µF, C3 1 µF, C5 1 µF (via 10 Ω), C4 2.2 µF (via 1.95 Ω), so **24.2 µF nominal, no electrolytic**. Plus board C-D8/C-D10 20 µF = 44 µF nominal (less after DC-bias derating), under the [SPEC] §6 limit of ≤ 50 µF effective. Inrush ≈ 44 × 12 mA/µF = 0.53 A. Plus aux 0.15 A, below the 1.0 A budget and the 1.4 A OC_FC sample. This is 4 % of the Death-5 node (470 µF + VESC). The BQ24650 has no ACFET/RBFET. The converter cannot load the node during the 1.3-1.75 ms RT1987 ramp because of the 30 ms SLEEP-exit deglitch and the 1.5 s enable delay (EC p.7, p.9). In the always-powered design the plug event happens once, at Idle → REGEN close | Scope I(D-BC-RG) at first REGEN close; pass if < 1.0 A |
| H9 | I2C/logic: address, 3.3 V levels, back-powering, status on pin 6 | **PROVEN_DATASHEET** | No I2C. The SDA/SCL pads stay open; the board pull-ups terminate on nothing. Teensy-driven nodes are gates only (Q_drv, Q_inv, and the comparator into Q_imp), so they cannot back-power the charger. STAT1/STAT2: open drain, 33 V abs max, V_OL ≤ 0.5 V at 5 mA, leakage ≤ 1.2 µA ([DS] §7.1, EC p.9). Pull up to Teensy 3V3. **JP2 must be OFF**: with JP2 ON, the LED pull-ups tie STAT1/2 to VIN (16-21 V) through 10 kΩ + LED, which would inject ~1.3 mA into a Teensy pin. STAT1 → pin 6: LOW = charging, which includes input regulation at zero current ([DS] §8.3.2). STAT2 needs a spare pin (CSV first) | - |
| H10 | Thermal, efficiency, wiring, mechanical | **PROVEN_CALC** | [DS] Fig. 23 (VCC 25 V): ≈ 89-90 % at 8.4 V out, 1 A and 2 A. At 15.8 V in, efficiency should be higher (lower switching loss); the estimate uses 0.90-0.91. Losses at 1.667 A × 8.4 V = 14 W out: L1 DCR 0.28 W, R6 0.07 W, Q1 conduction ≈ 0.05 W, D1 ≈ 0.4-0.5 W (Vf not read; TODO(verify: PDS1040)), switching + gate drive ≈ 0.4-0.6 W (Q1 Qg not read; IC gate-drive loss = V_IN·Qg·f_s, [DS] eq. 23). Total ≈ 1.3-1.5 W, η ≈ 0.90. IC: R_θJA 43.8 °C/W ([DS] §7.4) × ~0.2 W ≈ +9 °C; TSHUT 145 °C ([DS] EC p.8). The EVM is **76 × 76 mm**, larger than the 32 × 35 mm Ag105 outline, so mount it off-board on ≤ 100 mm twisted pairs to Ag105 pins 10/4 (VIN±) and 18-19/14-15 (VBAT±). The EVM keeps its own input caps and the R1/R2/C4 damper ([DS] §9.2.2.5). Output LC: L1 10 µH with C7 + C8 + C11 + board C-D11 ≈ 21 µF gives f0 ≈ 11 kHz, below 12-17 kHz ([DS] §8.3.19). Removing C7 gives ≈ 15 kHz | Thermal soak at 1.667 A for 30 min from 15.9 V and from 21 V |
| H11 | Availability today | **UNKNOWN_MISSING_PRIMARY** | [TIW] JSON price tables (2026-11-05): BQ24650RVAR USD 4.302 (1-99), 3.507 (100-249), 2.757 (250-999), 2.338 (1 k); BQ24650RVAT USD 5.163 / 4.209 / 3.308 / 2.806. Part status **Active** ([DS] addendum p.32, 9-Nov-2025). The schema tag reads OutOfStock, but inventory is behind a TI login. The EVM page's static HTML contains every stock-state template, so stock cannot be determined. Mouser, Farnell and DigiKey could not be reached. The EVM price was not found | Operator: check ti.com (logged in), Mouser and Farnell by hand |
| H12 | Telemetry: charge current, input V/I over I2C | **FAIL** | No I2C and no ADC in the IC ([DS] pin list p.4-5). Available: STAT1/STAT2 only. Board-side: V_chg on pin 38 exists; the INA253s give I_fc/I_bt and V_bus. **I_charge needs added hardware**: a current-sense amplifier across R6 (Kelvin at R6, 24 mΩ × 1.667 A = 40 mV, e.g. gain 50 → 2.0 V) into a spare ADC pin (CSV first). Part datasheet not read: TODO(verify). J-guard port: G1 (I_fc + I_bt > 1.0 A / 5 ms) and G2 (unaccounted bus power) use board sensors plus the added amplifier. G3 becomes "STAT1 = STAT2 = OFF for > 2 s while pin 5 HIGH, charger powered and MPPSET enabled" (suspend / OV / sleep / absent / fault cannot be told apart, [DS] Table 2) | Calibrate the added amp against a bench DMM at 0.2 / 1.0 / 1.667 A |

## 3. Register map excerpt (there are no registers: the "map" is the strap set)

| Function | Strap ([DS] equation / EC row) | Current EVM | Proposed |
|---|---|---|---|
| Hard inhibit | MPPSET < 75 mV / > 175 mV (EC p.7), 1.5 s re-enable (EC p.9) | Q2 on /CE, R18 100 kΩ → VREF, JP4 | Keep Q2 and R18; JP4 OFF; add Q_drv (/CE to GND, gate = pin 5, 47 kΩ pull-down) |
| Fast inhibit | MPPSET forced below 1.2 V → zero output ([DS] §8.3.2) | - | R_imp 3.40 kΩ + Q_imp, MPPSET to GND (default ON from VREF via 100 kΩ; PERMIT_FAST HIGH turns it off) → 45.2 V / 40.7 V |
| Input threshold | V_IN = 1.2·(1 + R17/R19_eff) (eq. 2), ±0.6 % | 499k/36k = 17.8 V | R17 = 74.1 kΩ, R19 = 4.99 kΩ, R19b = 1.69 kΩ in series, Q_sel across R19b (default ON) → **19.02 V regen / 14.51 V FC**; C17 22 pF → 150 pF (keeps the R·C) |
| CV | 2.1·(1 + R13/R15) (eq. 1), ±0.5 % | 499k/100k = 12.6 V | **R13 150 kΩ / R15 49.9 kΩ (0.1 %) = 8.413 V** (pack ≈ 8.36-8.38 V after D-BT-SQ); C15 22 pF → 68 pF |
| Charge current | 40 mV/RSR ±3 % (eq. 3) | R6 20 mΩ = 2.0 A | **R6 24 mΩ = 1.667 A** (pre-charge/term 0.167 A) |
| Termination | TERM_EN > 1.6 V enables, < 0.4 V disables (EC p.9) | JP3 2-3 (on) | **JP3 1-2 (off)** |
| TS | V_LTF 73.5 %, V_HTF 47.5 %, V_TCO 45 % of VREF; 400 ms out / 20 ms in (EC p.8) | JP1 1-2 | JP1 2-3 (internal valid) or J-NTC with a bias |
| Watchdog | none | - | MCU RTWDOG/WDOG1 (§8) |
| Readback | STAT1/STAT2 ([DS] Table 2) | LEDs on VIN | JP2 OFF; STAT1 → pin 6 with 10 kΩ to 3V3 |

## 4. Detail

### 4.1 Hard inhibit (H2a)
MPPSET < 75 mV is a genuine converter-off: REGN collapses ([UG] §2.7.1-2.7.2), so HIDRV/LODRV have no supply.
It clears all timers and faults ([DS] §8.3.18). Its cost is the 1.5 s enable delay on every release (EC p.9),
which also explains why the [DS] Fig. 2 "Charge start on MPPSET" trace uses 400 ms/div. **Use it only at state
level** (Init, Idle-off, Error, and the FC-window permit when the window is long), never per burst.

### 4.2 Fast inhibit by unreachable threshold (H2b)
A FET switches R_imp = 3.40 kΩ in parallel with the bottom leg:
- R19_eff = 4.99 ∥ 3.40 = 2.02 kΩ → V_th = 45.2 V. In FC mode, (6.68 ∥ 3.40) kΩ → 40.7 V.
- MPPSET at V-MOT = 16 V is 0.425 V; at 10 V it is 0.266 V. Both are above 175 mV, so there is no 1.5 s penalty.
- The hard reset (< 75 mV) occurs only below ~2.8 V in.

[DS] §8.3.2 states that the output current is zero while MPPSET is held below 1.2 V. The idle cruise state at the
19.02 V tap is *the same loop state* (V-MOT 16 V < 19 V), so the fast inhibit adds no wind-up penalty beyond
plain idling.

This turns the [LA] §8 H3 stage (option b) into "MPPSET → unreachable threshold" instead of "MPPSET → GND". **The
[LA] text that lists BQ24650 MPPSET < 75 mV as the C1 hard-inhibit pin would, if wired to PERMIT, cost 1.5 s on
every regen burst and capture nothing.**

Fail-safe arrangement:
- Q_imp's gate is pulled up to the charger's VREF by 100 kΩ, so it is ON (inhibit) whenever the charger is
  powered and the logic is absent.
- PERMIT_FAST = H1 ∨ H2 (from [LA]) drives an NMOS that pulls Q_imp's gate LOW.

Latency is not in the DS (bench M2).

### 4.3 Thresholds and where they sit
Regen tap 18.87-19.25 V. FC tap 14.40-14.69 V: below the FC-only bus at the K_DROOP droop, above `LIMIT_V_BUS_MIN`
12 V. The 14.51 V figure is a proposal; TODO(calibrate) against the measured FC-window bus sag.

The TPS61288 OVP max (19.5 V) can exceed the regen tap. The [LA] comparator H1 tracks VBUS and holds the 45 V tap
in that case.

A 19.7 V tap (min 19.54 V) would clear the OVP max outright. It cuts the absorb window to the 21.35 V VESC cut-off
from 2.1 V to 1.65 V, which tightens τ_warm by ~0.7× ([RD] budget ∝ C·ΔV/I).

### 4.4 Keeping the charger warm: D_byp
Without D_byp, VCHG decays between bursts with τ ≈ (R13 + R15)·C ≈ 200 kΩ × 21 µF ≈ 4 s. The charger falls into
pre-charge (C/10) and D-BT-SQ into UVLO. The next burst then gets at least 25 ms (LOWV deglitch) + 13 ms soft
start + RT1987 restart before full current. That fails τ_warm.

D_byp (Schottky, anode VBT, cathode VCHG, at the board VCHG polygon / C-D12) pins VCHG at pack − Vf:
- When charging, VCHG sits ~35-50 mV above VBT, so D_byp is reverse-biased by that amount (negligible).
- In detection, the 6 mA discharge cannot pull VFB below LOWV, so the routine ends "battery present" at 1 s.

Part not selected: TODO(verify: Schottky datasheet).

### 4.5 Timing in words

1. **Init → Idle.** P5 LOW, REGEN and FC_CHARGE LOW. The charger is unpowered; VCHG is held at pack − Vf by D_byp.
   The IC sits in SLEEP (VCC < SRN, ≤ 15 µA, [DS] §8.3.6).
2. **Run entry.**
   - Close REGEN onto V-MOT ≈ 16 V. The RT1987 ramp charges ~44 µF.
   - +30 ms: the IC exits SLEEP (EC p.7). VREF comes up and Q2/Q_imp turn on, so the charger is inhibited.
   - Raise P5. MPPSET is held at the 45 V tap (≥ 175 mV); the 1.5 s enable timer starts.
   - +1.5 s: battery detection, 1 s ("present" via D_byp).
   - +~2.5 s: the charger is in fast charge, held at zero current by the threshold (STAT1 LOW).
   - The motor may start in parallel. The charger is warm ~2.5 s after REGEN closes.
3. **Cruise.** PERMIT_FAST LOW (V-MOT ≈ VBUS < 1.067·VBUS), so the 45 V tap applies. Zero output; bus draw is IC
   quiescent (3-25 mA, unspecified) plus the divider (0.2 mA).
4. **Braking.** V-MOT rises in 19-47 ms ([RD]).
   - At ≈ 1.067·VBUS + hysteresis (≈ 17.1 V), H1 permits, Q_imp turns off, and the 19.02 V tap applies.
   - At 19.02 V the input loop releases and current rises at the unmeasured warm rate (M-R4). V-MOT holds at ~19 V
     while I_chg ≤ 1.667 A covers the VESC regen current, which is capped at 0.82 A.
   - When regen ends, V-MOT decays below 19 V (current → 0) and below the comparator's falling threshold (45 V tap).
     The charger is still enabled and warm.
5. **FC window.**
   - Firmware drops REGEN (the comparator holds the 45 V tap).
   - The FC_CHARGE net goes HIGH (Q_inv turns off Q_sel → 14.51 V tap) and the H2 permit goes HIGH → charging.
   - During the RT1987 8 ms changeover, VCHG-IN droops at IAC/C: ≤ 25 mA × 8 ms / 24 µF ≤ 8.3 V worst. This stays
     above VCC LOWV 4.1 V and MPPSET 175 mV, and is far shorter than the 100 ms SLEEP-entry deglitch (EC p.7).
     **No 1.5 s re-enable.** Bench-check this droop.
6. **Error (State 99).** P5 LOW (hard inhibit, REGN off) and PERMIT LOW, then REGEN/FC_CHARGE LOW in the safe
   order.

### 4.6 Loop-hazard check (operator ruling 3)

- **Bus → charger → pack → BT boost.** The charger converts only when V-MOT exceeds the active tap. The fast
  inhibit holds the tap at 45 V unless the comparator proves V-MOT > 1.067·VBUS, which is physically impossible
  while D-MT-EN feeds the bus into V-MOT ([LA] §2). IC housekeeping current (≤ 25 mA) is consumed and never
  reaches the pack.
- **Runaway current.** The charge current is bounded in hardware by RSR: 40 mV/RSR ±3 %, with a cycle-by-cycle
  limit at 200 % ([DS] §8.3.15, EC p.8 V_OC 80 mV). No I2C or host state can raise it.
- **Single faults:**
  - Q_sel stuck OFF in regen: 14.5 V tap, but the 45 V fast inhibit still holds through cruise.
  - Q_imp stuck OFF: falls back to the 19.02 V tap; still above the fw OV latch.
  - Divider R19 open: MPPSET follows VIN through 74.1 kΩ to the 7 V abs max with only the pin leakage as load. The
    threshold is lost and the charger converts at any VIN, so the comparator + P5 + F1 monitor must catch it.
    TODO: add a 7 V clamp, or rely on [LA] F1.
- **Pack back-feed.** The Q1A body diode and D3 run to VSYS; D1 blocks them from VCHG-IN ([UG] Fig. 8).

## 5. EVM / board modifications (Path A)

1. **Before first connection:** R13 499 kΩ → 150 kΩ, R15 100 kΩ → 49.9 kΩ (0.1 %), C15 → 68 pF. CV = 8.413 V.
2. R6 20 mΩ → 24 mΩ (0.1 %, 1206, WSLP-class): 1.667 A.
3. R17 499 kΩ → 74.1 kΩ, R19 36 kΩ → 4.99 kΩ + R19b 1.69 kΩ in series (all 0.1 %), C17 → 150 pF. Add:
   - Q_sel (2N7002-class) across R19b, gate to VREF via 100 kΩ.
   - Q_inv with gate on the FC_CHARGE net (10 kΩ EN pull-down already on the board), drain on the Q_sel gate.
4. Add R_imp 3.40 kΩ + Q_imp, MPPSET to GND; gate to VREF via 100 kΩ; an NMOS driven by PERMIT_FAST (the [LA] §8
   comparator carrier) pulls the gate LOW.
5. Keep Q2 and R18. **JP4 OFF.** Add Q_drv: drain to the /CE test point, source GND, gate = Teensy pin 5 via 1 kΩ,
   47 kΩ pull-down. Pin 5 becomes CHG_PERMIT (active-HIGH). Update the IO CSV first.
6. JP3 → 1-2 (termination off). JP1 → 2-3 (internal valid TS).
7. **JP2 OFF.** STAT1 → pin 6 with 10 kΩ to Teensy 3V3. STAT2 → spare pin (CSV first) or left open.
8. Remove C7 (keep C8, C11; board C-D11 supplies 10 µF) so f0 ≈ 15 kHz. Bench-verify stability.
9. Leave J2-4 VSYS unconnected. Keep D1 (it blocks pack → VCHG-IN).
10. Board: D_byp Schottky VBT → VCHG. C-D8/C-D10 → ≥ 35 V. Comparator carrier per [LA] §8 with the H3 stage
    targeting Q_imp (not Q2). Current-sense amp across R6 → spare ADC pin. Calibrate V_rgn (0.85×) first.
11. VESC: Battery Current Regen Max ≈ 0.82 A, unless M-R3/M-R4 show the charger can take more.
12. Firmware:
    - Delete the Ag105 I2C code.
    - Pin 5 permit through an F2-style sequencer (the State-98 `M` free toggle goes away).
    - STAT1/STAT2 decode.
    - Port G1-G3 and the trip latch.
    - FC-window order (REGEN LOW → FC_CHARGE HIGH, P5 kept HIGH).
    - Periodic P5 re-arm at stops if M-B2 finds a fast-charge timer.
    - `ERR_MCU_WDT` + RTWDOG (§8).

## 6. Open questions

- **Is there a fast-charge safety timer?** [DS] Fig. 14 (p.22) shows "Start Fastcharge timer" / "Fastcharge Timer
  Expired → FAULT". [UG] p.2 says "a programmable fast-charge timer". Yet the DS has no timer pin and no EC
  entry. A charger enabled for a whole Run might time out. Bench M-B2 (multi-hour enabled idle), or ask TI.
- Warm response (H4) and fast-inhibit latency (H2b): the two decisive bench gates.
- [DS] §8.3.19 says 12-17 kHz and §8.4.1 says 17-25 kHz: ask TI or bench-verify the loop.

## 7. Corrections to the round-1 dossier

1. The "rev-original 28 V / 30 V / ±0.2 V abs max" are the **Recommended Operating Conditions of SLUSA75B itself**
   (§7.3, p.5-6), not an older abs max. Abs max is 33/36/±0.5 V (p.5). The EVM parts are all ≥ 35 V (caps) and
   40 V (FETs, diodes) ([UG] BOM), so the "2010 rating class" concern is void.
2. "No input OVP comparator found": **wrong.** ACOV is 31/32/33 V, with 1 V hysteresis, 1 ms disable and 20 ms
   resume (EC p.7-8, §8.3.12).
3. I_CHG = 40 mV/RSR (±3 %), I_PRE = I_TERM = 4 mV/RSR (±25 %), VFB 2.1 V: now verified (EC p.6-7, §8.3.1-8.3.5).
   CV accuracy is ±0.5 % only at 0-85 °C (±0.7 % full range), so the round-1 idea of compensating to 8.43 V fails
   the ≤ ±0.3 % condition.
4. Switching frequency is **600 kHz** (510-690, EC p.9), not ~300 kHz.
5. EVM factory settings verified: 12.6 V CV (R13/R15), 17.8 V MPPSET (R17/R19), 2 A (R6 20 mΩ) ([UG] p.3-4). The
   EVM has a **second PDS1040, D3, from VBAT to VSYS** that round 1 missed, and the MPPSET divider taps J1-VIN
   **before** D1.
6. The round-1 hard-disable network (Q_en + Q_drv) mostly **already exists on the EVM** as Q2 + R18 (/CE). Only
   Q_drv needs adding.
7. **Major:** gating the charger per regen burst through MPPSET < 75 mV (the round-1 hard disable, and the [LA] H3
   example) re-arms the 1.5 s enable delay on every release (EC p.9). Fast gating must use a switched
   unreachable threshold (§4.2).
8. "Whether switching stops in input regulation UNVERIFIED (§8.3.9)": **closed.** [DS] §8.3.2 says the output
   current is zero; §8.4.2 says neither FET switches at zero duty except the 80 ns refresh. The quiescent current
   is still unspecified.
9. Round 1 noted VCHG decays through the VFB divider but missed the consequence: pre-charge mode (C/10) below VFB
   1.55 V, D-BT-SQ UVLO, and a possible 30-min pre-charge FAULT. These kill the warm response unless D_byp is
   fitted (§4.4).
10. Battery detection: the discharge is 6 mA for 1 s (EC p.8; the flowchart says 8 mA). If VFB < LOWV, 125 mA for
    0.5 s follows (I_WAKE specified only at R_SENSE 10 mΩ, 50-200 mA). Round 1's "sources current out of SRN" was
    a paraphrase; corrected per [DS] §8.3.21 / Fig. 12.
11. The MPPSET leakage (≤ 1 µA, EC p.7) was ignored. Round 1's 148 kΩ/10 kΩ network carries +0.8 % from it, and
    the EVM's 499 kΩ/36 kΩ carries +2.8 %. The proposal uses a 4.68 kΩ Thevenin (+0.39 %).
12. STAT truth table verified ([DS] Table 2, p.18). STAT1 is LOW during input regulation at zero current
    (§8.3.2), so pin 6 cannot tell "harvesting" from "armed and idle".
13. TS thresholds verified (EC p.8): 73.5 % / 47.5 % / 45 % of VREF; 400 ms out / 20 ms in.
14. EVM input capacitance is now known: 24.2 µF nominal, all X7R 35 V, no electrolytic ([UG] BOM). It fits
    [SPEC] §6.
15. The efficiency curve exists ([DS] Fig. 23): ≈ 89-90 % at 8.4 V / 25 V in.
16. Price: TI.com BQ24650RVAR USD 4.302 (1-99) … 2.338 (1 k) ([TIW]). The "DigiKey 12-week" lead time remains
    unverified. Gerbers SLUC264 are available, which supports a custom footprint-sized carrier.
17. The round-1 FC recommendation (RSR 24 mΩ ≈ 1.67 A) is confirmed: ≈ 0.97 A in at η 0.91. Under ruling 1 it
    now also sets the regen ceiling, hence the VESC regen cap.
18. Round 1 framed regen as viable "only in always-armed mode needing an R3 ruling". The ruling is now given. The
    remaining regen risk is quantitative (warm response, 1.667 A ceiling), not architectural.

## 8. MCU hardware watchdog (operator ruling 5, REQUIRED FUTURE WORK if this candidate is pursued)

The BQ24650 has **no host watchdog of its own**, so with it the MCU watchdog is the only timer-based protection
against a hung Teensy holding pin 5 HIGH. Adopt [LA] §10 unchanged:
- RTWDOG at 100 ms as primary, plus WDOG1 at 1.0 s.
- WDOG1's output must not be routed to pin 19 (SCL).
- After a WDT reset: latch `ERR_MCU_WDT` and require an acknowledgement before Run.
- Bench M6: a forced hang with pin 5, REGEN and BT_BUS HIGH must reset within the timeout, with every EN
  < 0.6 V and MPPSET < 75 mV.

The NXP RT1060 reference manual and PJRC reset pad states remain missing primaries ([LA]).

## 9. Verdict

**UNDETERMINED (no proven showstopper; two FAILs that need operator acceptance plus hardware; two decisive bench
gates).**

The BQ24650 is the only candidate whose input threshold survives any POR (resistor-strapped) and whose charge
current is hardware-bounded with no host state. That is a strong fit for the loop/runaway rules. Against it:
- **H5b FAIL.** No runtime current or input-current limit. One RSR must serve both FC and regen, so the
  recommendation is 1.667 A with the VESC regen cap.
- **H12 FAIL.** No telemetry; an external sense amp is needed.
- H2b fast-inhibit latency and H4 warm response are not in any primary and decide regen.
- The fast-charge-timer question and stock are open.

Path A with this part is feasible only after M2, M-R4, M-B1, M-B2 pass and the operator accepts on/off-only FC
charging at a fixed ~1.67 A, plus an added I_charge sensor.
