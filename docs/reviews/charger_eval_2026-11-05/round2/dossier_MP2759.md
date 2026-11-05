# Dossier R2: MPS MP2759 / EV2759 evaluation board, Path A requirement matrix (2026-11-05)

## 0. Sources and what is still missing

**Primary documents read in full (both in `charger_eval/datasheets/`, with a pdftotext `.txt` beside each):**
- **[DS]** MPS *MP2759, 36 V Switching Charger with Power Path Management for 1-Cell to 6-Cell Batteries*, Rev. 1.0, 11/30/2020, 23 pp (`MP2759_ds.pdf`). The same file is served at cdn.components.ru/media/PDF/8093961.pdf (1 509 528 B), so it is the only public MP2759 revision found.
- **[EVB]** MPS *EV2759-Q-01A Evaluation Board*, Rev. 1.0, 12/7/2020, 11 pp (`EV2759-Q-01A_evb.pdf`). It covers the schematic (Fig. 1, p.5), the BOM (pp.6-7) and the scope captures (pp.8-9).
- Scope and schematic readings in this dossier were taken from 400 dpi renders in `r2/mp2759/` (`crop_vlim.png`, `crop_out.png`, `crop_vlimonoff.png`, `crop_eff.png`).
- **Calculations:** `r2/mp2759/vlim_calc.py`.

**MISSING PRIMARIES (the operator must fetch these by hand):**
1. **MP2759A datasheet** (Rev. 1.0, 6/16/2021; Farnell 3632066.pdf). Search snippets give the only visible difference: a "narrow NTC window" and an NTC resistance table. Its electrical table, VLIM behaviour and OTP map were **not read**. Every number below is for the **MP2759**. Before buying an EV2759A-Q-00A, read its datasheet.
2. **EV2759-Q-00A user guide** (the EVB that [DS] p.3 lists in its ordering table) and **EV2759A-Q-00A user guide** (Mouser pdfDocs). Only **EV2759-Q-01A** was read. The board designators below are from the -01A, so confirm them on whichever board is bought.
3. **Stock, price and lead time for every EVB and IC.** Every source was blocked: Mouser closes the connection (curl error 52/92), Digi-Key and Octopart return 403, monolithicpower.com serves a JavaScript client challenge, and WebFetch cannot resolve www.farnell.com or www.monolithicpower.com. To retry, allow www.farnell.com, www.monolithicpower.com and www.mouser.com, or check by hand.
4. **MPS AN155** ("Using a microcontroller to adjust the MP2759 charging current"). Not fetched.
5. **VLIM input-voltage-loop bandwidth and warm response.** Absent from [DS]; it can only come from bench test M-R4.
6. **2N7002MTF** datasheet (EVB M2): the gate threshold at 3.3 V drive was not read.
7. **An I2C current/charge monitor IC** (for example TI INA228 or INA238) for the H12 add-on. No datasheet was read; the part is only proposed.
8. **NXP i.MX RT1060 RM** watchdog chapters (carried over from the loop analysis), needed for the H3(b) future work.

## 1. Identity (corrected)
- **What it is:** a stand-alone, resistor-programmed synchronous buck charger with integrated blocking, high-side and low-side FETs (Q1 38 mΩ, Q2 38 mΩ, Q3 55 mΩ typ; [DS] p.6). It supports 1S-6S Li-ion.
- **No I2C or SMBus, no ADC, no host watchdog.** The pinout is IN, PMID, SW, BST, PGND x3, STAT, ACOK, CELL, VB, NTC, ILIM, BATT, CSP, AGND, VCC, ISET and VLIM ([DS] p.3-4). OTP sets only factory options (the "-xxxx" suffix, "contact an MPS FAE", [DS] p.3, OTP map p.16).
- **Configuration:**
  - CELL strap selects 2S with 30-40 kΩ ([DS] Table 1, p.14).
  - VB strap selects 4.2 V with 100-110 kΩ ([DS] Table 2).
  - ICC = 96 kΩ / RISET ([DS] Eq.3, p.14).
  - IIN_LIM = 80 kΩ / RILIM ([DS] Eq.2).
  - VIN_MIN = 1.2 V x (R1 + R2)/R1, where R1 is the bottom resistor ([DS] Eq.1).
- **Enable:** pulling VLIM below 0.8 V disables the charger ([DS] p.14, p.18).

## 2. Requirement matrix

| Req | Status | Evidence (citation) | Bench test / condition |
|---|---|---|---|
| **H1 common ground** | PROVEN_DATASHEET | EVB Fig.1 p.5: input GND (TP2), BATT GND (TP4, C6 return), SYS GND (TP6), PGND pins 5-7, AGND pin 16 and C1/C2/C5/C8/C9/C7 returns all go to one GND symbol, with no FET or shunt in any return. **RS1** (20 mΩ, BOM p.6) sits between L1 (CSP, pin 15) and the BATT terminal (pin 14 senses the far side), so charge-current sense is high-side in BAT+. No unregulated path: charge current flows only through Q1 → PMID → Q2 → L1 → RS1. D2 (B140) runs IN → PMID, in parallel with Q1, and feeds PMID/SYS only; it never reaches BATT because Q2 is off when disabled. | Continuity check of EVB GND pads before wiring |
| **H2 hard inhibit while powered** | PROVEN_DATASHEET (mechanism); stop latency BENCH_GATE | The only inhibit is **VLIM < VVLIM_OFF** = 0.6/0.8/1.0 V falling, 40 mV hysteresis ([DS] p.8). It "disables the charger and resets the safety timer" ([DS] p.18, Fig.4). No inhibit bit (no I2C), no Hi-Z pin, no separate EN pin. ChargeCurrent = 0 is not available: ICC is resistor-set (a ≥ 3.2 MΩ ISET would not be a guaranteed off). **Does it stop all current into BATT?** The buck HS-FET Q2 stops. The device has no NVDC/BATFET path into BATT and no supplement mode. Trickle and pre-charge are converter phases, so they stop too. The external EVB power-path FET M1 conducts BATT → SYS only (gate from VIN through D1; [EVB] p.5). Shutdown input current is 600 µA max at 32 V with VLIM = AGND ([DS] p.6). BATT leakage is specified only with VIN = 0 (5.5/10 µA, [DS] p.6). **Response:** off-latency is not specified. The EVB "VLIM On/Off" capture ([EVB] p.9, 200 ms/div, DISABLE 5 V / 1 Hz) shows IBATT falling within one pixel (≈ 2 ms upper bound, read from the image). **Re-enable latency ≈ 175 ms** (DISABLE falling edge to switching start, 0.87 div at 200 ms/div, image read). This agrees with the "170 ms delay" before the DC/DC enables ([DS] p.13). **POR default:** the IC charges by itself 170 ms after ACOK unless VLIM < 0.8 V ([DS] p.13). | **M2:** VLIM pulled low → input current < 10 mA, measured in µs (the loop analysis needs ≤ 290 µs at a 1.5 A input). Measure the release → switching latency on the bought part. |
| **H3 fail-safe** | FAIL natively (it charges out of POR, and nothing catches a hung MCU). Feasible only with added hardware, then BENCH_GATE | **(a) Teensy in reset / high-Z:** the RT1987 EN 10 k pull-downs leave the charger unpowered (board, [SPEC]). If VCHG-IN is powered, the EVB as shipped *charges*: the DISABLE gate pull-down R12 (10 k) keeps M2 off, so VLIM follows the divider ([EVB] p.5). **Fix:** move M2's gate pull-up to the charger's own VCC (≈ 5 V, 4.8-5.2 V, [DS] p.6) through 100 k, so the default is **disabled**. Add an enable N-FET Q_EN (gate from pin 5 with a 47 k pull-down) that pulls M2's gate low. With an unpowered or high-Z MCU, VLIM sits at ~0 V and the charger is disabled. VCC exists only when VIN is present, which is exactly when it is needed. **(b) Teensy hung with pins latched:** the charger has **no host watchdog** (no host interface). A latched pin-5 HIGH keeps it enabled indefinitely. Its own bounds remain: the CC/CV straps, the input limit, the VLIM threshold, the 20 h safety timer ([DS] p.8, p.15) and termination. **Needs:** the MCU hardware watchdog (operator ruling 5, §8), and optionally an AC-coupled or charge-pump enable so that a static pin level means disabled. **(c) I2C dead:** not applicable; charging does not depend on I2C. **(d) POR defaults:** it charges autonomously to the strapped CELL × VB (8.40 V with the 2S/4.2 V straps; **the EVB ships at 3 cells / 4.2 V = 12.6 V**, [EVB] Table 3 p.4) at the strapped ICC (EVB default 2 A). The trickle (100 mA) → pre-charge (10 %, min 100 mA) → CC → CV sequence starts 170 ms after ACOK ([DS] p.13). **Advantage over every TI candidate:** the VLIM regulation threshold is set by resistors, so it is valid from the first microsecond. It is not re-derived from VIN at POR (compare loop_analysis finding 1). | Forced-hang test, Teensy reset test: VLIM < 0.4 V within 1 ms with VIN applied, and STAT Hi-Z |
| **H4 input-voltage threshold (always-powered regen)** | BENCH_GATE (warm response, zero-current idle). There is a PROVEN_CALC constraint that forces a custom VLIM control block. | **Range:** any value from VBATT_REG + VHDRM (8.4 + 2.4 = 10.8 V worst case, [DS] p.6, p.18) to 36 V, set by a divider. 19 V (regen) and 15 V (FC) are both reachable. **Accuracy:** VIN_MIN_REF = 1.18/1.20/1.22 V (±1.67 %, [DS] p.7) plus divider tolerance. With 0.1 % parts: 19.0 V nominal gives **18.66-19.30 V**; 15.08 V nominal gives 14.83-15.34 V (calc). **Runtime programmability:** none over I2C. Only resistor switching works (an FET in the bottom leg, see §4). Unlike the BQ25713/720 (max 19.52 V), it can be set above the TPS61288 OVP max of 19.5 V. **CRITICAL CONSTRAINT (PROVEN_CALC):** the regulation reference (1.18 V min) and the off threshold (1.0 V max + 40 mV hysteresis = 1.04 V) share the pin. To stay *enabled* (warm) at a 15.59 V bus, the plain divider needs Vth_nom ≤ **17.95 V** (Vth range 17.62-18.29 V). A 19.0 V plain divider puts VLIM at **0.986 V at a 15.59 V bus and 1.012 V at 16.0 V**, inside the 0.6-1.0 V off band. The part may then simply be *disabled* at bus voltage, and each regen burst becomes a 175 ms cold start (the VESC trips in 19-47 ms, regen_dynamics). Adding an offset from VCC widens the Vth spread to 1.9 V at 19 V nominal (`vlim_calc.py`). **Therefore:** idle warmth needs either a ~17.9 V threshold (0.12 V above the 17.5 V fw OV latch at worst case; it does not cover the 17.2 V overshoot plus tolerance, nor a failed-FB boost) or the **warm-clamp** VLIM block (§4). **Leakage at or under threshold:** not specified. IIN_Q = 1 mA typ only for "charging enabled, terminated" at 32 V ([DS] p.6). **Warm response:** not specified. The only VIN-loop capture ([DS] p.11, [EVB] p.9, 1 µs/div) is steady state. **Requalification:** none on a dip below VIN_MIN; ACOK depends only on UVLO (3.3-3.9 V) and VIN > VBATT + VHDRM ([DS] p.6, p.13). Dipping below the VLIM *off* threshold does re-run the 170 ms delay (EVB p.9). | **M-R4** warm step (idle at Vth − 0.5 V, step to Vth + 1 V; τ63 ≤ 4 ms required). **M-W1:** input current from a stiff 16 V source with VLIM clamped at 1.11 V (target < 10 mA, no switching bursts). **M-W2:** measure VVLIM_OFF on the bought part over temperature. |
| **H5 FC-charging mode** | PROVEN_DATASHEET (charger); the input budget is a board constraint | From VBUS ≈ 15.9 V through D-BC-FC: VIN > VBATT + VHDRM (8.4 + 2.4 = 10.8 V) holds ([DS] p.6). The threshold moves to ~15.08 V via the FC_CHARGE-net FET (§4), and the VLIM loop then also backs off if the FC bus sags (a free hardware bus guard). **ICC:** up to 3 A recommended ([DS] p.5); 96 k/RISET; ±10 % (1.8-2.2 A at 48 k, [DS] p.6). 2.5 A = R1 95.3 k ∥ 64.9 k = 38.6 k → 2.49 A nominal (2.24-2.74 A). **CV:** 2S/4.2 V = 8.36/8.40/8.44 V **at 25 °C only** ([DS] p.7); no over-temperature limit is given. **Termination:** 10 % ICC (min 100 mA, 60-145 mA), deglitch 100 ms, CV only, and not while in the IIN/VIN loop ([DS] pp.7, 13). Auto-recharge at 150-250 mV/cell below VREG ([DS] p.7). Safety timer 20 h ±2 h, enabled by default ([DS] p.8, OTP p.16). **≥ 2 A at 8.4 V** needs ≈ 1.12 A input at 15.9 V (calc, η ≈ 94 %). The input limit ±10 % ([DS] p.7) has to be ≥ 1.3 A nominal (61.9 k), which **exceeds the round-1 FC budget of ≤ 1.0 A** and approaches OC_FC 1.4 A. No charger meets both "≥ 2 A out" and "≤ 1.0 A in" at 15.9 V; this is a system-level conflict, not specific to the MP2759. | FC charge at 15.9 V: ICC, IIN, CV and termination, logged on pins 38/41 |
| **H6 voltage ratings** | PROVEN_DATASHEET (IC); EVB mods required | Absolute maximum 45 V on IN, PMID, ACOK, BATT and CSP; SW 45 V; VLIM and the other small-signal pins 5.5 V ([DS] p.5). Operating VIN 4-36 V. **OVLO 35/36/37 V rising, 1 V hysteresis** ([DS] p.6), so there is no drop-out mid-burst anywhere near the 21.4 V clamp or the 24 V V_chg latch. The regen peak VLIM is ≈ 1.27-1.42 V with these dividers, below the 5.5 V pin limit. **EVB "VIN < 20 V" note** ([EVB] p.4, p.5 note 1): the cause is hot-insertion ringing, not component ratings. C1, C2, C5, C8 and C9 are all 50 V parts (BOM p.6); only C7 on VCC is 25 V. Above 20 V, [EVB] note 2 asks for ≥ 47 µF electrolytic, a B240A in place of D2 (B140, 1 A; [DS] p.4 and Table 5 require 2 A/40 V), and a TVS if spikes reach 45 V. On this board VCHG-IN is ramped by the RT1987, not hot-plugged by a cable. | Scope VCHG-IN and PMID during the first REGEN close and during a hard regen burst; spike must stay < 40 V |
| **H7 battery pin behind D-BT-SQ** | PROVEN_DATASHEET (with a consequence for H4) | **No battery-detection routine** is described anywhere in [DS]. Behaviour on a 0 V output: trickle at 100 mA (70-130 mA) below 2.0 V/cell (4.0 V), pre-charge at 10 % ICC (min 100 mA) below 3.0 V/cell (6.0 V), then CC and CV ([DS] p.6, p.13). It therefore ramps C-D11 + EVB C8 + C9 (≈ 115 µF) from 0 V to above the pack on its own, in about 6 ms plus any unspecified phase deglitch (calc). It opens D-BT-SQ once VCHG > VBT + 35 mV. **CV** is sensed at BATT (VCHG), so the pack finishes at 8.36-8.44 V minus 35-50 mV (spec.md §3.4). **No BATFET/NVDC** inside the IC; EVB M1 is an optional BATT → SYS FET (remove it). **Keep D-BT-SQ.** Bridging it would make PMID ≈ pack through Q2's body diode. Q1 and D2 block PMID → IN ([DS] p.1 "integrated reverse blocking FET", p.17), so there is no back-feed into VCHG-IN, but the hard pack disconnect is lost. **Consequences of keeping it:** (i) after termination VCHG decays only through leakage and the RT1987 VIN load, so auto-recharge may never fire. Firmware must re-arm with a VLIM pulse (costs ~175 ms; Idle only). (ii) While idling in the VLIM loop, VCHG decays. A regen burst may then start in trickle or pre-charge (100-250 mA), which adds roughly 1-2 ms to τ_warm. | **M-W3:** VCHG decay rate in idle and phase-transition timing during the first 10 ms of a warm burst |
| **H8 inrush / hot-plug** | PROVEN_CALC | The input node seen by D-BC-FC/D-BC-RG is EVB C1 1 µF + C2 10 µF (electrolytic) + C5 2.2 µF (charged through D2 B140, which is in parallel with Q1; the PMID path is not current-limited) ≈ 13 µF, plus board C-D8/C-D10 (2 × 10 µF/25 V, derated): ≈ 25-33 µF total. That is under spec §6's ~50 µF bound. At 12 mA/µF RT1987 soft-start this is ≈ 0.4 A, under OC_FC 1.4 A. **Do not** add the 47 µF electrolytic from [DS] p.17: it would bring the node to ~80 µF. The BATT-side caps (C8 + C9 ≈ 110 µF) are charged only after the 170 ms delay, at trickle current, so the RT1987 ramp never sees them. In the always-powered design, VCHG-IN charges once, during the MOT_PWR / V-MOT pre-charge (Death-5 rule). | Scope D-BC-RG/D-BC-FC current on first close; ≤ 0.5 A peak |
| **H9 I2C / logic** | PROVEN_DATASHEET | **No I2C.** Pins 18/19 and the RSDA/RSCL pull-ups have nothing to back-power, and the address question does not arise. **STAT** (pin 8) is open-drain, 0.4 V at 5 mA ([DS] p.8). Per [DS] Table 3 p.15: **LOW = charging; Hi-Z = complete / disabled / IN absent; 2 Hz blink = NTC fault, timer expired or battery OVP.** Wire it to Teensy pin 6 with a 3V3 pull-up. **Remove EVB LED2 + R6**: R6 (2 k) pulls STAT to the 5 V VCC through LED2, and Teensy pins are not 5 V tolerant. **ACOK** is open-drain with LED1 + R5 (20 k) **to VIN**, up to 21 V. Never connect it to a Teensy pin without removing R5/LED1 and adding a 3V3 pull-up. No pin is assigned to it. **Pin 5** becomes the charger enable (to Q_EN). **VLIM direct-drive levels:** > 1.3 V high, < 0.4 V low ([DS] p.18). The FET drive scheme makes these irrelevant. | — |
| **H10 thermal / efficiency / mechanical** | PROVEN_CALC (graph read); mounting is a design task | Efficiency at 16 V → 8.4 V, 700 kHz: ≈ 94 % at 2.5 A and 95 % peak at ≈ 1.6 A ([DS] p.10 graph, typical). No data below 0.5 A, so light-load (~2 W regen) efficiency is unknown. Loss at 2.5 A ≈ 1.34 W, of which L1 DCR (35 mΩ) ≈ 0.22 W and RS1 ≈ 0.13 W, leaving the IC at ≈ 1.0 W → ΔTj ≈ 50 °C at θJA = 50 °C/W (JESD51-7, [DS] p.5). Tj limits: 125 °C operating, TSD 150 °C (20 °C hysteresis, [DS] p.8). Regen at 21 → 8.4 V: no curve given; estimate a few points lower (unproven). **The stock inductor is acceptable**: at fSW = 700 kHz (OTP default) [EVB] note 5 permits it at any ICC. **EVB size 63.5 × 63.5 × 13 mm** ([EVB] p.2) against the 32 × 35 mm Ag105 footprint, so it must be mounted off-board on short twisted pairs (VCHG-IN/GND and VCHG/GND, < 10 cm) plus a signal harness (pin 5, pin 6, FC_CHARGE net, 3V3, GND). A ≤ 32 × 35 mm carrier using the bare IC is possible but is a custom PCB. | Thermal soak at 2.5 A for 30 min, IR camera, Tcase < 100 °C |
| **H11 availability** | UNKNOWN_MISSING_PRIMARY | Every distributor and MPS page was blocked this session (§0 item 3). Round-1 listing numbers, unverified: EV2759A-Q-00A Digi-Key 15861764, element14 3890219; EV2759-Q-01A Digi-Key 14552495, Farnell 3773209 (round 1 saw a "notify me" banner); MP2759AGQ-0000-P element14 3890220; MP2759GQ-0000-Z Farnell 3773211. | Operator check |
| **H12 telemetry** | **FAIL (natively)** | No I2C and no ADC ([DS] pin list p.4). Charge current, input voltage and input current cannot be read back. The only digital signals are STAT and ACOK. The EMS needs per-decel coulombs of 0.2-0.66 C (regen_dynamics), and the ported J-guards G1-G3 need charger input power. The board's own pins 38 (V_chg) and 39 (V_rgn) give voltages but no charger current. **The only route is an add-on:** an I2C current/charge monitor (e.g. an INA228-class part, on the free Teensy I2C bus) across RS1 (CSP → BATT, 0-8.4 V common mode) or across a dedicated VCHG-IN shunt. That is extra hardware and is not covered by any primary document read here. | If pursued: monitor IC datasheet + calibration against a bench meter |

## 3. Register map excerpts
There is no register map. The resistor and OTP "map" is:
- **CELL:** AGND 1S; **30-40 k 2S**; 60-70 k 3S; 100-110 k 4S; 160-170 k 5S; VCC 6S ([DS] Table 1).
- **VB:** AGND 3.6 V; 30-40 k 4.0 V; 60-70 k 4.15 V (OTP bit 5 = 1, default) or 4.1 V; **100-110 k 4.2 V**; 160-170 k 4.35 V; VCC 4.4 V ([DS] Table 2, p.14; OTP p.16).
- **ISET:** ICC = 96 k/RISET, 20 mΩ sense ([DS] Eq.3). **ILIM:** IIN = 80 k/RILIM ([DS] Eq.2). **VLIM:** Eq.1, reference 1.2 V, off < 0.8 V.
- **OTP (factory, not field-writable):**

| Bit | Name | Default value | Default meaning |
|---|---|---|---|
| 10 | JEITA_EN | 0 | JEITA enabled |
| 9 | VCOLD | 0 | 74 % |
| 8 | VCOOL | 0 | 65 % |
| 7 | VWARM | 0 | 32.5 % |
| 6 | VHOT | 0 | 23 % |
| 5 | VREG_4P1 | 1 | 4.15 V |
| 4 | ITERM | 0 | 10 % |
| 3 | IPRE | 0 | 10 % |
| 2 | FSW | 0 | 700 kHz |
| 1 | TTMR | 0 | 20 h |
| 0 | EN_TMR | 0 | timer enabled |

  Source: [DS] p.16.
- **There is no watchdog of any kind.**

## 4. EVM modifications (EV2759-Q-01A designators; re-verify on the -00A or A-Q-00A board)

1. **Strap 2S / 4.2 V before first power.**
   - VB: fit **JP4** only. JP4 selects R17 105 k, which gives 4.2 V.
   - CELL: fit **JP8** only. JP8 selects R19 34.8 k, which gives 2S.
   - Jumper order as read from the Fig.1 render: JP1/JP7 = AGND; JP2-JP5 and JP8-JP11 = R15-R18 and R19-R22; JP6/JP12 = VCC. Ohm-check before power.
   - The default (3 cells, 4.2 V) charges toward 12.6 V, and the BQ29200 OUT drives nothing.
2. **ISET for 2.5 A:** replace R9 (95.3 k, JP19) with 64.9 k, keep R1 95.3 k and fit JP19, giving 38.6 k → 2.49 A. Leave JP20 open.
3. **ILIM, two levels (optional):** R2 = 61.9 k always (FC mode, 1.29 A). Rb = 200 k in series with the threshold FET Q_T2 (below) gives 1.69 A in regen mode. Remove JP17 and JP18.
4. **VLIM block (replaces R3, R4, R13/R14/R24, JP14-16, M2 and R11/R12):**
   - Top: R4 221 k (0.1 %).
   - Bottom: R_A 19.1 k (0.1 %) always, plus R_B 68.1 k in series with N-FET Q_T. **Q_T on → 18.98 V (18.66-19.30 V); Q_T off → 15.08 V (14.83-15.34 V).** (Round 1 had this direction reversed.)
   - Q_T's gate is pulled up to VCC through 100 k, so the default is the high threshold. An inverter N-FET driven from the **FC_CHARGE net** (J1.45/46, RT1987 EN, already 10 k pulled down) pulls Q_T's gate low. The threshold is therefore low only while FC_CHARGE is HIGH.
   - **Hard disable M_D** (VLIM → GND). Its gate is pulled up to VCC through 100 k, so the default is **disabled**. Q_EN (gate = Teensy pin 5, 47 k pull-down) pulls M_D's gate low to enable. The loop-analysis FC permit can go in series with Q_EN. **Do not** put the H1 V-MOT/VBUS comparator in series with Q_EN: its release would cost 175 ms per burst.
   - **Warm clamp, needed only to hold Vth ≈ 19 V:** a precision 1.11 V source (accurate to ±50 mV over temperature; window 1.04-1.18 V), low impedance, switched onto VLIM by an analog switch while H1 = inhibit. While H1 = permit, V-MOT > 1.067 × VBUS ≥ 16.47 V and the 19 V divider gives VLIM ≥ 1.041 V, so the part stays enabled. **Single-fault caveat:** the clamp sits only 70 mV below the level at which the charger draws full current, so a clamp-reference fault (high) can open the circular loop. G1/G2 plus the hard disable must back it up.
   - **Alternative without the clamp:** a plain Vth of 17.9 V (enabled at ≥ 15.59 V), with H1 used only as a detector that trips the hard disable. It covers neither the 17.2 V bus overshoot (with tolerance) nor a failed-FB boost (18.3-19.5 V).
5. **STAT:** remove LED2 and R6, wire STAT (TP9) to pin 6, and pull up to Teensy 3V3 (10 k). **ACOK:** remove LED1 and R5, leave it unconnected or give it its own 3V3 pull-up if a pin is ever assigned.
6. **Power path:** remove M1 (AM4417), D1, ZD1 and R23, and leave SYS (TP3) open. Replace D2 B140 with a B240A ([DS] Table 5; [EVB] note 2).
7. **NTC:** keep JP13 on the RNTC1/RNTC2 divider (10 k/10 k = 50 % of VCC, inside the cool-warm band of 65 %-32.5 %, [DS] p.8), or fit a pack NTC.
8. **Input capacitance:** keep C1 and C2. Do **not** add 47 µF. Main board: C-D8/C-D10 25 V → ≥ 35 V ([SPEC]).
9. **H12 add-on:** an I2C current monitor across RS1 or a VCHG shunt (see H12).
10. **IO CSV:** pin 5 is renamed from MPPT_DISABLE to CHG_ENABLE (active-HIGH). Pin 6 stays CHARGER_STAT with inverted semantics (LOW = charging).

## 5. Timing in words
- **Cold start, from REGEN or FC_CHARGE closing:**
  1. RT1987 ramp of about 1.5 ms (board).
  2. ACOK goes low once VIN > 3.9 V and VIN > VBATT + 2.4 V.
  3. **170 ms** later the DC/DC enables ([DS] p.13).
  4. Trickle, then pre-charge, then CC into C-D11 + C8 + C9, about 6 ms (calc).
  5. D-BT-SQ conducts and CC flows to the pack.
  6. Total ≈ 180 ms, which fails the ≤ 100 ms spec and every regen cold-start case. The always-powered design hides it, because the start happens once per boot.
- **Hard disable** (pin 5 LOW or Q_EN off): VLIM drops to 0, switching stops within ≤ 2 ms (EVB p.9 image bound; M2 measures the real figure) and STAT goes Hi-Z. **Re-enable ≈ 175 ms** (EVB p.9), and the safety timer resets.
- **Warm regen burst** (enabled, idling in the VIN loop):
  1. V-MOT rises past Vth.
  2. The VIN-loop error amplifier releases the charge-current reference. The rate is unspecified (M-R4).
  3. The current ramps to min(ICC, ILIM-equivalent) and V-MOT is held at Vth.
  4. When the burst ends, V-MOT falls below Vth and the loop throttles to zero.
  5. No ACOK requalification happens as long as V-MOT stays above VBATT + VHDRM and VLIM stays above the off threshold.
- **Termination:** CV, I < ITERM for 100 ms, and not in the VIN or IIN loop. STAT goes Hi-Z and the charger stays off. Re-arm needs a VLIM pulse.

## 6. Round-1 corrections
1. The primary datasheet and the EV2759-Q-01A guide have now been read. The MP2759A datasheet and the -00A / A-Q-00A guides have **still not** been read.
2. An **input current limit does exist**: the ILIM pin, IIN_LIM = 80 k/RILIM, ±10 % ([DS] p.7, p.14). Round 1 said none was documented.
3. The VLIM reference is **1.18/1.20/1.22 V** ([DS] p.7). Round 1 called 1.2 V unverified and said not to use it.
4. **The direction of round 1's threshold-lowering FET was wrong.** Paralleling a resistor across the bottom leg *raises* Vth (Eq.1). The low threshold needs the bottom-leg FET *off*.
5. **New hazard round 1 missed:** VLIM's off threshold (max 1.0 V) shares the pin with the 1.2 V reference. A plain 19 V divider can leave the part *disabled* at bus voltage, so every regen burst becomes a 175 ms cold start.
6. **The re-enable latency after VLIM release is ≈ 175 ms** (EVB p.9), and the cold start is 170 ms after ACOK ([DS] p.13). Round 1 had both as unknown.
7. The cause of the EVB "VIN < 20 V" note is hot-insertion ringing and the D2 rating, **not low-voltage capacitors**: every power capacitor is 50 V (BOM p.6). Round 1 guessed low-voltage input capacitors.
8. The EVB carries electrolytics: C2 (10 µF/50 V input) and C9 (100 µF/50 V on BATT). Input capacitance is ≈ 13 µF, which is acceptable. Round 1 did not know this.
9. EVB defaults: 3 cells, 4.2 V, ICC 2 A, ILIM 2 A, VIN_MIN 10 V (JP14). Round 1 had only 3S/4.2 V.
10. CV accuracy is ±0.48 % **at 25 °C only**; no over-temperature limit is given.
11. The stock inductor is fine at 700 kHz for any ICC: the note reads "fSW = 700 kHz **or** ICC < 2.5 A".
12. There is no battery-detection routine, and the part starts into a 0 V output (trickle 100 mA). Round 1's "battery-absent misfire" risk is retired.
13. Termination is suppressed while in the VIN or IIN loop ([DS] p.13), so the charger does not terminate while idling.
14. Reverse blocking is confirmed: integrated Q1 plus the mandatory Schottky from IN to PMID. PMID charges to BATT through Q2's body diode ([DS] p.17).
15. OVLO is 35/36/37 V with 1 V hysteresis, and the absolute maximum is 45 V. Both confirmed ([DS] pp.5-6).
16. **EVB STAT and ACOK carry 5 V and VIN pull-ups through LEDs** and must be modified before touching the Teensy. Round 1 only suspected a VCC pull-up.
17. EVB size is 63.5 × 63.5 × 13 mm (round 1 guessed ~50 × 50 mm). Efficiency is ≈ 94 % at 16 → 8.4 V, 2.5 A (round 1 said ~90 %, uncited).
18. The safety timer is 20 h ±2 h, enabled by default, and resets on a VLIM pulse or input re-insertion ([DS] p.8, p.15).
19. Round 1's fail-safe enable network was correct in concept. The EVB M2 network as shipped is confirmed **not** fail-safe (R12 pulls the gate down, so the board defaults to enabled).
20. The round-1 fit score of 5.5/10 is withdrawn. H12 fails natively, and H4 needs a custom precision analog block.

## 7. Verdict
**NOT_FEASIBLE as an off-the-shelf Path A swap.**
- **H12 fails outright:** no I2C telemetry at all.
- **H4 needs a custom analog block.** The always-powered regen mode needs a precision VLIM control circuit with a 140 mV window to stay warm, because the hard inhibit's 175 ms exit rules out per-burst gating. That circuit adds a single-fault path to the circular loop.
- **H3(b) is uncovered:** nothing in the part catches a hung MCU.
- **Strengths:** a hardware threshold that is valid at POR, 45 V absolute maximum, high-side sense, integrated reverse blocking and a starts-into-0 V behaviour.
- **It could be rescued** with the §4 mods plus an I2C monitor, provided M-R4, M-W1, M-W2 and M2 all pass. It would still rank below the I2C candidates, which have a fast hard inhibit and native readback.

## 8. MCU hardware watchdog: required future work (operator ruling 5)
- **Why the MP2759 needs it more than the others:** it has no charger-side watchdog, so a hung Teensy with pin 5 latched HIGH leaves the charger enabled. Its bounds are then only its straps, the VLIM threshold, the 20 h timer and the RT1987 switch states.
- **Carry over the loop-analysis §10 design:**
  - RTWDOG at 100 ms as the primary timer, plus WDOG1 at 1.0 s as an independent second timer.
  - Do not route the WDOG1 output to pin 19.
  - On reset, every RT1987 EN falls through its 10 k pull-down. Pin 5 goes high-Z, so Q_EN turns off and VLIM is pulled to 0 V: charger disabled.
  - Latch `ERR_MCU_WDT` and require acknowledgement before Run.
- **Bench proof:** a forced hang must produce a reset within the timeout, with every EN < 0.6 V, VLIM < 0.4 V and STAT Hi-Z.
- **Optional extra layer:** a dynamic (AC-coupled) enable on Q_EN, so that a static pin 5 level of either polarity disables the charger.
- **Primaries still needed:** NXP RT1060 RM and the PJRC pad states during reset.
