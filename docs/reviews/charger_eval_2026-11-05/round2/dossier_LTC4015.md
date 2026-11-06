# Dossier R2: ADI DC2039A (LTC4015), Path A replacement for the Ag105

Date 2026-11-05. Board rev 20260622. Round 2: primary documents read. Operator rulings of 2026-11-05 apply (regen and FC
charging are both hard requirements; R3 is replaced by "no adverse behaviour"; always-powered charger accepted; the MCU
hardware watchdog is required future work).

## 0. Sources (all primary, read in this round)

| Tag | Document | Location |
|---|---|---|
| [DS] | LTC4015 datasheet, Rev B (footer "4015fb"), 76 pp | `scratchpad/charger_eval/datasheets/LTC4015_ds_revB.pdf` (+ .txt; per-page split in `r2/ltc4015/LTC4015_ds_revB_pNN.txt`) |
| [DM] | Demo Manual DC2039A, Rev D (schematic Rev 5, 2-4-16), 32 pp | `datasheets/DC2039A_demo_manual.pdf` (+ .txt; schematic renders `r2/ltc4015/rot-30.png`, `rot-31.png`, crops `c30_*.png`, `c31_*.png`) |
| [LOOP] | `r2/loop_analysis.md` (comparator, permit, watchdog) | cross-cutting |
| [REGEN] | `r2/regen_dynamics.md` (τ_warm requirement, M-R0..M-R4) | cross-cutting |
| [SPEC] | `docs/reviews/charger_eval_2026-11-05/spec.md` | board interface |

Page numbers below are the datasheet's printed page numbers (equal to PDF page numbers for both documents).
**Not obtained (see `missing_primaries`):** distributor pages (www.mouser.com and www.analog.com fail DNS in WebFetch;
Mouser and Farnell time out over curl), Murata GRM31CR61H106KA12 DC-bias curve, LTC4015 error-amplifier output-current
limits and VC-node slew data (not in [DS]), DC2039A board outline dimensions (not in [DM] text).

## 1. Verdict

**FEASIBLE_WITH_CONDITIONS.** Fit score 7.5 / 10 (round 1: 5.5 provisional).

The LTC4015 has one property no TI candidate has: **its input-voltage threshold resets at POR to the HIGHEST value the
resistor divider allows** (VIN_UVCL_SETTING default 0xFF = 1.2 V at UVCLFB, the register can only lower it; [DS] p.22, p.60,
[DM] p.7). With the divider strapped to the regen threshold (19.0 V), every charger reset lands in the regen-only state,
where it cannot draw from a 16 V bus. FC charging needs a deliberate I2C write that lowers the threshold. A failed or
corrupted write leaves it at 19.0 V, which means no charging. This directly answers [LOOP] finding 1, where TI parts reset
to the input voltage minus an offset.

The conditions:
1. **EVM rework is mandatory.** As shipped, the DC2039A fails three requirements:
   - inrush: about 240 µF nominal on VIN+SYS, including a 120 µF electrolytic, gives about 2.9 A at 12 mA/µF, against
     the 1.4 A OC_FC latch;
   - I2C: an on-board PIC is the bus master and powers DVCC;
   - threshold: the UVCL divider sets 9 V.
   The rework list is in §4.
2. **No pin-level charge inhibit exists on the IC**, and **there is no host watchdog** (full register map, [DS] pp.49-54).
   - The Teensy-commanded, fail-safe hard inhibit has to be built: an N-FET that pulls UVCLFB to GND, with its gate pulled
     up from the charger's INTVCC (§3 H2/H3).
   - A DRVCC-UVLO cut is an optional second "converter off".
   - The MCU hardware watchdog (operator ruling 5) is therefore **mandatory, not optional**, for this candidate.
3. **Bench gates (BENCH_GATE):**
   - warm response τ_warm ≤ 4 ms ([REGEN]; estimated 1.6 ms with the stock VC network, about 70 µs with the datasheet's
     10 nF VC capacitor);
   - inhibit latency ≤ 290 µs ([LOOP]; estimated 160 µs stock, about 7 µs with 10 nF);
   - UVCL zero-current point and hold-mode quiescent;
   - inrush after the mods.
   All latency and loop-speed figures are estimates. [DS] gives no loop bandwidth.
4. **D-BT-SQ must be bridged** (charger BAT on the pack).
   - Otherwise the 2-4 s battery-detection test runs into a ~30 µF node with the pack hidden ([DS] p.30), and the IC loses
     its registers every input cycle.
   - With the bridge, the INFET (M5) still blocks pack to VIN back-feed ([DS] p.18), so no new loop path appears.
   - Cost: the hard battery-side disconnect is lost.
5. **The regen hard requirement still depends on cross-cutting gates** that apply to every candidate: [REGEN] M-R0
   (VESC over-voltage cut-off mechanism) and M-R3 (does braking continue with V-MOT held at 19 V).

Strengths:
- 40 V VIN absolute maximum. OVLO at 37.7 V minimum, so there is no drop-out anywhere near the 21.4 V clamp.
- Both current senses are on the high side; common ground is proven on the EVM schematic.
- Resistor-set hardware ceilings on charge and input current.
- Full telemetry, with a hardware coulomb counter.
- No soft-start or re-qualification on a UVCL release while VIN stays more than 100 mV above BATSENS: the warm path is
  only the analog loop.

## 2. Corrections to round 1 (dossier_ADI_LTC4015...md)

| # | Round-1 claim | Round-2 finding (primary) |
|---|---|---|
| C1 | "No primary PDF fetched"; evidence [WS]/[REC] | LTC4015 Rev B and DC2039A Rev D read in full where relevant |
| C2 | UVCL programming UNVERIFIED; proposed a 19 V strap plus a FET to 13.5 V because the I2C range was unknown | UVCLFB regulation = (VIN_UVCL_SETTING+1) × 4.6875 mV, 8 bits, default 0xFF = 1.2 V, register can only lower ([DS] p.4, p.22, p.60). With divider k = 15.833, codes 0..255 span 0.074-19.0 V in 74.2 mV steps, so **I2C alone spans FC and regen**. The FET-switched divider is unnecessary. |
| C3 | "No charge-enable pin; suspend_charger in CONFIG_BITS [REC]" | Confirmed: suspend_charger = 0x14 bit 8, default 0 ([DS] p.50, p.59). **Leaving suspend restarts the whole charge cycle: battery detection 2-4 s (+1-2 s open/short test), then soft-start ≤ 12.4 ms** ([DS] p.30, p.32, p.59). Usable for latched faults only, never per burst. |
| C4 | Battery detection "of order 100s of ms" [REC] | **2-4 s** with a 1 mA load, plus 1-2 s at minimum current if unstable ([DS] p.30, p.36). A regen cold start is impossible; warm operation is mandatory. |
| C5 | ICHARGE_TARGET formula [REC]; POR = maximum codes | Confirmed: (N+1) × 1 mV/RSNSB, default 0x1F; IIN (N+1) × 0.5 mV/RSNSI, default 0x3F ([DS] p.22, p.50). **Missed in round 1:** en_jeita defaults to 1 for lithium, and while it is set **writes to ICHARGE_TARGET have no effect** (the current comes from icharge_jeita_n) ([DS] p.33, p.60, p.63). Firmware must write en_jeita = 0 or the icharge_jeita_n fields. |
| C6 | ICHARGE = 0 implied as an inhibit option elsewhere | **The minimum code is 1 mV/RSNSB (83 mA at 12 mΩ), not zero.** The IIN minimum is 0.5 mV/RSNSI. Neither register can inhibit ([DS] p.5, p.60). |
| C7 | VCHARGE accuracy "~±0.5 %?" | **±1.25 %** over temperature, all chemistries ([DS] p.4): 2S at 4.2 V/cell gives 8.295-8.505 V. The register can only lower it ((N/80 + 3.8125) V/cell, [DS] p.60). |
| C8 | "Watchdog: none known [REC]" | **Confirmed none**: the register map 0x01-0x4A has no watchdog or host-timeout field ([DS] pp.49-54). |
| C9 | DC2039A CIN/CSYS unknown | VIN: C2-C5 = 4 × 10 µF/50 V X5R 1206. SYS: C17 0.1 µF + C18-C25 8 × 10 µF/50 V + **C26 120 µF/40 V electrolytic**. BAT: C9, C10 2 × 10 µF ([DM] p.28, schematic p.30). |
| C10 | UVCL divider unknown | R3 226k, R4 64.9k, R6 10.0k, R7 10k series, C6 100 pF. With JP1 = OFF (MPPT off), M1 shorts R3, giving **9 V threshold** (10/75); MPPT selection opens M1, giving 36 V ([DM] p.7, p.8, schematic p.30). |
| C11 | "QuikEval/DC590 connector pull-ups, remove them" | **There is no DC590.** The DC2039A carries a USB-isolated (LTM2884, U3) **PIC16F1459 (U4) as the I2C master**. It drives DVCC from RB7, with pull-ups R27-R29 4.7k to DVCC. External host header J4 is unpopulated (OPT). Unpowered-USB sneak paths raise BAT IQ above 1 mA ([DM] p.7, p.29, schematic p.31). U4 must be removed. |
| C12 | "J-NTC empty, fit 10k" | NTC: JP2 selects INT = CAT5140 digital pot (U5, factory 25 °C, **only alive with USB power**) or EXT; RNTCBIAS 10k fitted ([DM] p.3, p.7, p.29). Set JP2 = EXT and fit 10k (or the pack NTC) at E6 to GND. |
| C13 | RSNSI → 32 mΩ (1.0 A) so POR is safe in FC mode | Revised to **20 mΩ (1.6 A)**. FC charging cannot occur after a POR, because the threshold returns to 19 V. The ceiling only has to bound regen (1.19 A needed at 19 V for 2.5 A out). The FC 1.0 A limit is firmware-set and readback-verified **before** the threshold is lowered. |
| C14 | UVCL "not a hard off" | Still true, but [DS] p.45 itself states a threshold above the input "will result in the LTC4015 not charging the battery", and p.13 states "at 1.15 V the charge current is zero". Hardware pull-down of UVCLFB is therefore a datasheet-backed zero-current state. |
| C15 | Pin 5 to switch UVCL divider to > 30 V | Replaced with a simpler design: pin 5 → permit chain → N-FET pulls UVCLFB to GND (§3 H2). |
| C16 | VIN abs max 40 V; OVLO not known | Confirmed 40 V ([DS] p.3). OVLO **37.7/38.6/39.5 V** rising, 1.4 V hysteresis ([DS] p.4, p.41). |
| C17 | Address 0x68 [REC] | Confirmed 1101_000[R/W] = 0x68 ([DS] p.8). |
| C18 | IBAT LSB 1.46487 µV/RSNSB [REC] | Confirmed ([DS] p.54). Accuracy: ±200 µV at 0 mV (±17 mA at 12 mΩ), ±2.5 % at 32 mV ([DS] p.7). |
| C19 | Mouser 44 pcs ~USD 152 [TRIAGE] | Still not verified from a primary page; distributor sites unreachable this round. |
| C20 | INFET only | Plus OUTFET M4 (Si7611DN P-ch), BAT → SYS ideal diode. No SYS → BAT path except the buck ([DS] p.18, [DM] p.8). |

## 3. Requirement matrix

### H1 Common ground: PROVEN_DATASHEET
- On DC2039A schematic sheet 1 ([DM] p.30), the VIN return (E2/E4), the BAT return (E7/E8), the SYS return (E11/E12) and
  the NTC GND (E5) all go to the single GND symbol. There is no low-side shunt or jumper.
- Input sense **RSNSI** (KRL3216T4, 3 mΩ) sits in the VIN+ leg between INFET M5 and SYS.
- Charge sense **RSNSB** (4 mΩ) sits between the L1/CSP node and the BAT turret E10 (CSP-CSN; [DS] p.14).
- No unregulated path from VIN to BAT:
  - VIN → M5 (body diode VIN → SYS) → SYS → buck M3B/M3A + L1 → RSNSB → BAT.
  - M4's body diode conducts BAT → SYS only ([DM] p.8 "body diode already has the correct polarity").
- **Caveat (by architecture):** with the buck top FET M3B shorted, SYS connects to BAT through L1. That is a
  component-failure path; the RT1987 input switches and the [LOOP] comparator cover it.

### H2 Hard charge inhibit while powered: BENCH_GATE (mechanisms proven; latency unspecified)

| Mechanism | How | Stops all battery current? | Response | POR default |
|---|---|---|---|---|
| suspend_charger (0x14 b8) | I2C write | Yes: buck off, charger_suspended. No SYS → BAT path exists (M4 body-diode orientation, [DM] p.8). Covers pre-charge and CC/CV. | Not specified. **Exit = new cycle: detection 2-4 s + soft-start ≤ 12.4 ms** ([DS] p.30, p.59) | 0 = charging enabled ([DS] p.50) |
| UVCL via register (0x16) | I2C; threshold above VIN | Charge current regulated to 0 ([DS] p.18, p.45). State stays cc_cv_charge; no re-detection | VC loop slew (est. below) | 0xFF = divider max (safe high) |
| **UVCLFB forced to GND** (proposed hardware inhibit) | N-FET on UVCLFB, gate pulled up from LTC4015 INTVCC, released by the Teensy permit chain | "at 1.15 V the charge current is zero" ([DS] p.13); 0 V ≪ 1.15 V at any code. Regulation-loop zero, not a converter-off | **Estimate** 160 µs with the stock VC network (Cc 0.22 µF/Rc 200 Ω/Cc2 10 nF, [DM] p.30): gm(UVCL) 1.06 mS ([DS] p.7) × 1.2 V error into 0.23 µF = 5.5 V/ms, ΔVC ≈ 0.9 V. About 7 µs with the datasheet's 6.8-14.7 nF VC ([DS] p.42). Error-amp current saturation is not given: **bench M-L2** | Inhibit when the MCU is dead (gate pull-up) |
| DRVCC UVLO cut (optional) | Split DRVCC from INTVCC; feed through a switch; drop below 3.9 V | Converter off: "switching controller off if DRVCC falls below 3.9 V" ([DS] p.41) | DRVCC cap ≥ 2.2 µF; est. ~0.2 ms with active discharge. Is a system fault, so **re-detection on recovery**. For latched faults only. Sequencing: DRVCC only after INTVCC > 3 V ([DS] p.14, p.41) | n/a |
| ICHARGE_TARGET / IIN_LIMIT minimum | I2C | **No**: minimum 1 mV/RSNSB and 0.5 mV/RSNSI ([DS] p.5, p.60) | n/a | max codes |
| NTC forced out of JEITA window | Pull the NTC pin to GND (region 7) | Charger OFF in regions 1/7 ([DS] p.34, p.62); NTC_PAUSE returns to the previous state without re-detection (Fig. 5A, p.28) | ADC cycle ~7 × 1.6 ms ≈ 11 ms ([DS] p.20); slow. Only with en_jeita = 1 | JEITA on |
| Hi-Z / converter-disable pin | none exists | | | |
| Ship mode | Only acts when VIN < ~1 V and is irreversible until a power cycle ([DS] p.22-23, p.60) | not an inhibit | | |

- There is no NVDC supplement mode that charges the battery. The OUTFET path only discharges BAT into SYS.
- Pre-charge and trickle are buck states, and every inhibit above stops them.
- The UVCL-hold state is the normal regen standby. After entry, CHARGE_STATUS.vin_uvcl_active = 1 and IBAT ≈ 0 ([DS] p.52).
  Firmware can cross-check that the inhibit path is working.

### H3 Fail-safe: BENCH_GATE (architecture proven; needs the external inhibit and the MCU watchdog)
- **(a) Teensy in reset / pins high-Z:**
  - The RT1987 EN pins have 10 kΩ pull-downs, so D-BC-RG and D-BC-FC open and the charger input is unpowered.
  - The proposed UVCLFB N-FET has its gate pulled up to INTVCC, so it reads "inhibit" whenever the Teensy is not driving
    the permit.
  - The permit chain is two series N-FETs whose gates come from pin 5 and from the TLV3012 output, each with a pull-down.
    Both must be ON to pull the inhibit FET's gate low. Teensy high-Z or comparator unpowered (output LOW, [LOOP]) both
    give inhibit.
  - If D-BT-SQ is bridged the IC stays powered from the pack and keeps its registers. A Teensy reset while in FC mode
    therefore leaves the threshold at the FC value, but input power and the permit are both removed.
- **(b) Teensy hung, pins latched:**
  - **The LTC4015 has no watchdog** ([DS] pp.49-54).
  - Hung in FC mode: charging continues at the firmware-set IIN limit (1.0 A) and CV/termination. Bounded, and not a
    loop, because the [LOOP] FC permit needs BT_BUS LOW and I_bt below 0.2 A in hardware.
  - Hung in regen mode: the [LOOP] V-MOT/VBUS comparator blocks any bus-fed draw.
  - **The MCU hardware watchdog (RTWDOG 100 ms + WDOG1 1 s, [LOOP] §10) is REQUIRED future work** before Path A with this
    part. A WDT reset then falls into case (a).
- **(c) I2C dead or stuck:**
  - The charger keeps its last configuration and runs autonomously.
  - Pin 5 permit and the hardware comparator still inhibit without I2C.
  - If the stuck write was the FC threshold-lower, the write either completed (FC mode, still guarded by the permit) or
    did not (threshold stays 19.0 V, no charge). Write order is §5.
- **(d) POR defaults (out of reset the charger charges by itself):**
  - suspend_charger = 0.
  - ICHARGE: JEITA region 3 (10k fixed NTC, ratio 0.5 = 10922, between T2 = 0x372A and T3 = 0x1F27) gives
    32 mV/RSNSB = 2.67 A at 12 mΩ ([DS] p.34, p.51).
  - IIN: 32 mV/RSNSI = 1.6 A at 20 mΩ.
  - VCHARGE: 4.2 V/cell = 8.40 V ±1.25 %.
  - **UVCL: divider max = 19.0 V**, so at bus voltage (≤ 17.5 V) the charge current is zero; the zero-current point is
    18.21 V nominal, worst 17.99 V (see H4).
  - The autonomous POR state is "regen-only, bounded by RSNSB/RSNSI". That is benign, given the comparator.
- **Pulls needed:**
  - 100k from the inhibit FET gate to LTC4015 INTVCC.
  - 100k pull-downs on both permit-FET gates.
  - JP1 = OFF: MPPT pin held low by R19 1M ([DM] p.30). MPPT must never run, because it sweeps VIN_UVCL_SETTING and
    would find a sub-bus threshold from a stiff source ([DS] p.18, p.59).
  - mppt_en_i2c defaults to 0 ([DS] p.50).

### H4 Input-voltage threshold (always-powered regen mode): PROVEN_DATASHEET for range and programmability; BENCH_GATE for warm response, taper and hold quiescent

**Range and resolution:**
- VTH = k × (code+1) × 4.6875 mV, where k = divider ratio ([DS] p.60).
- With k = 15.833 (example: R_top 158k / R_bot 10.7k, 0.1 %, k = 15.77, 18.92 V; trim values to taste), code 0xFF =
  19.0 V and the LSB is 74.2 mV.
- FC 14.03 V = code 188; 14.47 V = code 194.
- Any threshold up to 35 V is possible (VIN abs max 40 V). Unlike the BQ25713/720 (19.52 V cap, [LOOP] finding 4), the
  LTC4015 **can** place its zero-current point above the TPS61288 OVP maximum of 19.5 V:
  - VTH ≈ 20.6 V puts zero current at ≥ 19.5 V and full current at ≤ 20.85 V, under the ~21.35 V VESC cut-off
    ([REGEN]).
  - This trades away about 2 ms of warm-response headroom.
  - Recommended default stays 19.0 V, with the comparator covering boost-OVP faults.

**Accuracy:**
- VUVCLFB at code 0xFF: 1188/1200/1212 mV over temperature (±1 %, [DS] p.4).
- Divider ±0.1 % per resistor.
- Full-current point: 19.0 V ± 1.2 % = 18.77-19.23 V.
- Only the LSB is specified at lower codes, so FC-mode threshold accuracy is unspecified. It is not safety-relevant.

**Taper and zero-current point:**
- "Charge current tapered off when UVCLFB is below 1.2 V, at 1.15 V the charge current is zero" ([DS] p.13; [DM] p.7).
  This is typical only; there is no min/max.
- Zero-current point: 18.21 V nominal, 17.99 V worst (1.2 % low × 1.15/1.2).
- Margins: 0.49 V above the 17.5 V firmware OV latch, 0.79 V above the measured 17.2 V overshoot.
- Bench M-L4 maps IBAT against VIN at codes 0xFF and 188.

**Runtime programmability:**
- Word write to 0x16 at any time; do not write while MPPT is enabled ([DS] p.45).
- The MPPT algorithm moves this DAC dynamically ([DS] p.18), which implies a live DAC. Write-to-effect latency is not
  specified.

**Draw from a stiff source at or below the threshold (hold mode):**
- VIN pin < 140 µA ([DS] p.4).
- SYS (fed from VIN through M5): IQ "charging, switcher suspended" 3.00 mA; ISYS 3.65 mA with VBAT > VCHARGE ([DS] p.4).
- Plus the gate charge of any skipped cycles, plus the UVCL divider (~0.11 mA at 19 V with 169k).
- Expected **≈ 4 mA ≈ 64 mW from V-MOT**: IC bias, not charge.
- [DS] p.46 warns that a charger starved of input current can discharge the battery by < 10 mA. The reverse inductor
  limit IREV is 3.8-10 mV/RSNSB ([DS] p.6). In UVCL hold, some pack → SYS circulation is possible; it cannot reach VIN
  (INFET reverse turn-off -30 mV, fast-off at 25 mV, [DS] p.6, p.18).
- **Bench M-L1:** IIN, IBAT and VSYS at stiff 16.0/17.5/18.0 V with VTH = 19.0 V. Pass: input ≤ 10 mA, |IBAT| ≤ 10 mA,
  VSYS ≤ VIN + 0.5 V.

**Warm response (powered, enabled, UVCL-held, then V-MOT crosses VTH):**
- No state change happens: all states fall to charger_suspended only if VIN comes within 100 mV of BATSENS, suspend is
  written, or a system fault occurs (Fig. 5A note, [DS] p.28, p.37). V-MOT ≥ 15 V ≫ 8.5 V, so the charger stays in
  cc_cv_charge.
- Soft-start only runs "when charging is enabled" ([DS] p.40), so it does **not** re-run.
- The rise is set purely by the VC node: after UVCL releases, the CC amp (gm 4.1 mS, [DS] p.7) drives VC.
- Linear estimate: 4.1 mS × 32 mV / 0.23 µF = 0.57 V/ms. ΔVC ≈ 0.9 V gives **τ ≈ 1.6 ms (stock DC2039A VC)**. With the
  datasheet 6.8-14.7 nF VC: ≈ 70 µs.
- **Uncertainty:** VC may be wound below 0.9 V during hold, and the amplifier current limits are not specified.
- Requirement τ_warm ≤ 4 ms ([REGEN]). **Bench M-L3 = [REGEN] M-R4.**
- The stock 0.22 µF VC is the MPPT/resistive-source compensation ([DS] p.42 "100's of nF when MPPT with > 0.5 Ω
  sources"). Re-compensating towards ~10-15 nF with Rc scaled needs loop stability verified on the regen source
  (CAL 470 µF + VESC).

### H5 FC-charging mode: PROVEN_DATASHEET (current, CV, termination); conditions on configuration
- **Input:** VBUS 15.9 V through D-BC-FC. Charging needs VIN > BATSENS + 140-250 mV (VIN_DUVLO, [DS] p.4); 15.9 ≫ 8.6 ✓.
  Maximum duty 98.4 % ([DS] p.7) ✓.
- **Charge current with RSNSB = 12 mΩ:**
  - (N+1) × 83.3 mA. N = 23 gives 2.00 A; N = 29 gives 2.50 A; N = 31 gives 2.67 A maximum.
  - Tolerance ±2 % at full scale ([DS] p.4).
  - Precharge ~10 % below 2.9 V/cell ([DS] p.30), irrelevant for a 7.4-8.4 V pack.
  - **en_jeita must be cleared, or icharge_jeita_3 written** (C5).
- **Input limit for FC:** IIN_LIMIT code 39 = 1.00 A at 20 mΩ ([DS] p.60). ICL is ±2 % at full scale ([DS] p.4). No SYS
  load exists on this board, so ICL bounds the total input apart from IC bias ([DS] p.18).
- **FC threshold:** code 188 (14.03 V). The charger then also backs off if the FC bus sags below ~14 V, which protects
  the bus. Optional.
- **CV:**
  - 2S Li-ion programmable (CHEM1/0 = L/L; CELLS2/1/0 = L/H/L; DC2039A default, [DM] p.4).
  - 8.40 V ±1.25 % (8.295-8.505 V). The upper bound exceeds the 8.4 V pack rating and nears LIMIT_V_BATT_MAX 8.5 V.
    Recommend VCHARGE_SETTING = 29 (4.175 V/cell = 8.35 V, worst 8.454 V).
  - The BQ29200 OVP remains the cell-level protection ([DS] p.9 note 11: "not a substitute for pack protection").
- **Termination:**
  - Li-ion timer termination after MAX_CV_TIME (default 14,400 s) in CV, **cannot be disabled for Li-ion** ([DS] p.32,
    p.62). Optional C/x (en_c_over_x_term, default 0).
  - Auto-recharge below 97.5 % of VCHARGE ([DS] p.5, p.32).
  - MAX_CHARGE_TIME 18.2 h fault, writable (0 disables, [DS] p.50, p.62).
  - **EMS consequence:** after a timer or C/x termination the charger stays off (regen not absorbed) until VBAT
    < 0.975 × VCHARGE or until a suspend toggle, which costs a 2-4 s re-detection.

### H6 Voltage ratings: PROVEN_DATASHEET
- VIN and CSN: -0.3 to 40 V absolute maximum ([DS] p.3). Operating VIN 3.1-35 V, VSYS ≤ 35 V ([DS] p.4).
- OVLO 37.7 V minimum rising ([DS] p.4); the controller holds both switches off above 38.6 V and resumes at 37.2 V
  ([DS] p.41). **No drop-out inside the 15.9-21.4 V window or any credible overshoot**, so there is no mid-burst cut.
- EVM parts:
  - VIN/SYS/BAT ceramics: 50 V.
  - C26: 40 V (removed anyway).
  - M3 FDMC8030: dual 40 V. M5 FDMC8327L: 40 V. M4 Si7611DN: -40 V.
  - D1 15 V zener sits gate-source on M1 ([DM] p.28-29, p.30); it is removed with M1 in the rework.
- The board's C-D8/C-D10 (25 V, at VCHG-IN) are still the weakest parts at the 21.4 V clamp; ≥ 35 V replacement per
  [SPEC] s2.

### H7 Battery pin through D-BT-SQ: BENCH_GATE if kept; PROVEN_DATASHEET consequences if bridged (recommended)
- **Kept:**
  - At each input power-up the BAT pin sees 20 µF (C9/C10) + C-D11 10 µF at ~0 V, with the pack hidden until VCHG
    > VBT + 35 mV ([SPEC] s3).
  - Battery detection is "1 mA load for 2-4 s; if unstable, open/short test at minimum current for 1-2 s" ([DS] p.30).
    It may classify the node as shorted or missing; bat_missing_fault exits only after 30 s (Fig. 5A).
  - Below 2.4 V at BATSENS the charger runs constant-peak-current at 7 mV/RSNSB ([DS] p.30), which should lift VCHG until
    D-BT-SQ conducts.
  - The outcome is UNVERIFIED: bench M-L6.
  - The IC is unpowered between sessions (its supply is max(VIN, VBAT) through SYS, [DS] p.14), so the registers reset
    every input cycle. Firmware must re-configure, and the threshold POR value (19 V) keeps that safe.
  - BATSENS Kelvin to VBT across D-BT-SQ is still **rejected** (round-1 §9 hazard stands: if D-BT-SQ blocks, the CV loop
    opens and VCHG runs toward VIN).
- **Bridged (recommended):** solder link VCHG ↔ VBT (or a 0 Ω across D-BT-SQ).
  - The pack sits on BAT, and BATSENS reads the pack at the BAT turret E10. No 35 mV CV error.
  - The IC is always powered from the pack through OUTFET M4 → SYS → INTVCC (SYS = max(VIN, VBAT), [DS] p.14, p.17-18).
    Registers persist.
  - Battery detection runs once per VIN rise, at Run entry, not per burst.
  - The coulomb counter runs continuously.
  - **Back-feed:** the INFET (M5) blocks SYS → VIN (reverse turn-off -30 mV, fast-off when VIN falls 25 mV below SYS,
    t_off 2 µs, [DS] p.6, p.18), so the pack cannot energize VCHG-IN/V-MOT/VBUS through the charger.
  - Costs:
    - BT_SEQUENCE_ENABLE (pin 32) no longer isolates the charger.
    - Battery-only drain 112-325 µA with telemetry off ([DS] p.4). That figure needs U4 removed ([DM] p.7: > 1 mA with
      the PIC unpowered).
    - Firmware's D-BT-SQ sequencing becomes a no-op for the charger path.

### H8 Inrush / hot-plug: FAIL as shipped; PROVEN_CALC with mods (BENCH_GATE M-L5 to confirm)
- RT1987 slew is 12 V/ms, giving 12 mA/µF ([SPEC] s6).
- M5's body diode conducts VIN → SYS, so **VIN and SYS caps both charge on the ramp**. The INFET gate itself takes
  550 µs (tIF(ON), [DS] p.6).
- **As shipped:**
  - Nominal 40 µF (VIN) + 80.1 µF (SYS ceramic) + 120 µF (C26 electrolytic) ≈ 240 µF, giving **2.9 A**.
  - With the ceramics derated to ~60 % at 16-21 V (assumption; the Murata DC-bias curve was not read): ≈ 192 µF,
    **2.3 A**.
  - Both exceed the 1.4 A single-sample OC_FC latch. This is the Death-5 class.
- **Modified (remove C26, C4, C5, C22-C25; keep C2, C3 on VIN and C18-C21 + C17 on SYS):**
  - Nominal 60 µF, giving 0.72 A.
  - Plus board C-D8/C-D10 20 µF nominal = 0.24 A, plus aux 0.15 A: 1.11 A worst nominal. ≈ 0.5-0.7 A with derating.
  - Meets the [SPEC] ≤ ~1.0 A budget once derating is counted.
  - Ripple check: ΔVSYS = (VB/VS)(1 - VB/VS) × ICHG/(CSYS × f) = 0.525 × 0.475 × 2.5/(24 µF × 500 kHz) = 52 mV ✓
    ([DS] p.43).
  - CSYS RMS current ≤ ICHG/2 = 1.25 A, shared by 4 × 1206 parts. The per-part rating was not read: verify.
- **No charger draw during the ramp:** charging cannot begin until battery detection (2-4 s) has run after VIN > BATSENS
  + 200 mV ([DS] p.30, p.41), and the UVCL threshold (19 V or 14 V) is above most of the ramp. ✓
- **Regen-path closure (D-BC-RG at Run entry):** the inrush comes from V-MOT (CAL 470 µF), which D-MT-EN refills from the
  bus. The same 12 mA/µF applies. It happens once per Run, not per burst (always-powered design).

### H9 I2C / logic: PROVEN_DATASHEET (with EVM mods)
- **Address 0x68** ([DS] p.8). There is no other device on the Teensy bus.
- 400 kHz maximum. Word read/write SMBus protocol; there is no byte-write mode ([DS] p.8, p.19; [DM] p.8).
- **Levels:**
  - DVCC 1.6-5.5 V; VIH 70 % / VIL 30 % of DVCC; SDA VOL 0.4 V at 3 mA; leakage ±1 µA; IDVCC 0 µA static ([DS] p.8).
  - SDA/SCL absolute maximum: -0.3 V to DVCC ([DS] p.3).
  - **DVCC must be tied to the pull-up supply** ([DS] p.13, p.19): wire DVCC to Teensy 3V3.
- **EVM mods:**
  - Remove U4 (PIC16F1459, the I2C master that also drives DVCC from RB7).
  - Remove R27-R29 (4.7k to DVCC), or keep them as pull-ups to 3V3 (in parallel with RSDA/RSCL).
  - Leave USB J1 unconnected.
  - Use the J4 footprint (Vcc / DVcc / SCL / nSMBALERT / SDA / GND) as the Teensy harness point ([DM] p.31).
- **Back-powering:**
  - With D-BT-SQ bridged the LTC4015 is always powered.
  - When the Teensy is off (3V3 = 0, DVCC = 0), SDA/SCL sit at 0 V through the pull-ups: inside the absolute maximum.
  - Charger unpowered (D-BT-SQ kept) with 3V3 up: IDVCC 0 µA, leakage ±1 µA, so no back-power (behaviour of an
    unpowered IC with DVCC present is not characterized).
- **Pin 6 (CHARGER_STAT):**
  - SMBALERT is open-drain, 5 V tolerant, 1 µA leakage, VOL 100 mV at 1 mA ([DS] p.8). It can drive pin 6 with
    INPUT_PULLUP.
  - Enable alerts: charger_suspended, bat_missing/short, max_charge_time_fault, vin_ovlo by polling.
  - Clearing needs the ARA read at 0x19, which returns 0xD1 ([DS] p.19).
  - Readiness source = CHARGER_STATE 0x34 / SYSTEM_STATUS 0x39 over I2C.
- **Pin 5:** becomes the inhibit-permit input (§3 H2). **The IO CSV must be amended first** (CSV-wins rule).

### H10 Thermal / efficiency / wiring / mechanical: PROVEN_CALC (thermal); dimensions UNKNOWN (off-board mount required)
- **Power path at 2.5 A:**
  - 16 → 8.4 V: P_out 21 W. 21 → 8.4 V (regen): P_out 21 W.
  - The DC2039A runs 8 A from 25 V at η ≈ 0.925 ([DM] p.3).
  - At 2.5 A the conduction losses fall as I² and switching losses as I, so ≤ ~1.5 W total (estimate) on an 8 A-rated
    board, thermally trivial.
  - L1 XAL1010-103 (10 µH, 13.4 mΩ DCR, 17.5 A sat, [DM] p.5): I²R at 2.5 A ≈ 84 mW.
  - RSNSB 12 mΩ at 2.5 A: 75 mW. KRL3216T4 is rated 1 W ([DM] p.28).
- **IC dissipation:** ≈ VSYS × (IQ + IG) ≈ 20 V × (4 + ~10) mA ≈ 0.28 W, giving ΔT ≈ 9.5 °C at θJA 34 °C/W ([DS] p.3,
  p.41).
- **Light load (2-5 W regen):**
  - Fixed 500 kHz (RT 95.3k, [DS] p.7, [DM] p.5).
  - [DS] documents no burst mode, so efficiency at < 0.5 A is unspecified (efficiency curve [DM] p.1 is graphical only).
    Bench.
- **Mechanical:**
  - DC2039A outline dimensions are not in [DM] text. It carries turrets, banana jacks, the LTM2884 and 4 nylon standoffs
    ([DM] p.29), so it **cannot sit on the 32 × 35 mm Ag105 footprint**.
  - Mount it off-board on the standoffs with twisted pairs:
    - VCHG-IN/GND (≤ 1.6 A), from Ag105 pads 10 + GND;
    - BAT/GND (≤ 2.7 A), to VBT/GND after the D-BT-SQ bridge;
    - SDA/SCL/DVCC(3V3)/GND/SMBALERT;
    - UVCLFB-inhibit permit lines.
  - Keep VIN/SYS ceramics on the EVM, so lead inductance is outside the switching loop. Lead ringing on the slow 12 V/ms
    ramp is minor (verify in M-L5).

### H11 Availability: UNKNOWN_MISSING_PRIMARY
- Primary distributor pages were unreachable:
  - www.mouser.com and www.analog.com: DNS failure in WebFetch.
  - Mouser and Farnell over curl: HTTP/2 INTERNAL_ERROR, then timeout.
- **Leads only (web search, 2026-11-05, unverified):**
  - Mouser 584-DC2039A ~44 pcs ~USD 152.
  - DigiKey 9664282 ~23-30 pcs USD 175-233.
  - ADI direct ~USD 147.
  - Farnell 4032839 ~USD 172.
  - Arrow 0 stock.
- Lead time not established.
- The bare LTC4015EUHF/IUHF also exists for a carrier (Path A') ([DS] p.3).

### H12 Telemetry: PROVEN_DATASHEET
Registers ([DS] p.20, p.54):

| Quantity | Register | Scale | Value at this board's resistors |
|---|---|---|---|
| IBAT | 0x3D | 1.46487 µV/RSNSB | 0.122 mA/LSB at 12 mΩ |
| IIN | 0x3E | 1.46487 µV/RSNSI | 0.073 mA/LSB at 20 mΩ |
| VIN | 0x3B | 1.648 mV | |
| VSYS | 0x3C | 1.648 mV | |
| VBAT/cell | 0x3A | 192.264 µV | |
| VBAT_FILT | 0x47 | | |
| DIE_TEMP | 0x3F | | |
| NTC_RATIO | 0x40 | | |

- **Update:** 7 channels × ~1.6 ms, so each channel refreshes about every 11 ms ([DS] p.20). Fast enough for 50 Hz
  `I_charge` and for the G2 power-accounting guard.
- **Accuracy:**
  - ±200 µV at 0 mV (±17 mA IBAT at 12 mΩ; ±10 mA IIN at 20 mΩ).
  - ±2.5 % at 32 mV.
  - VIN ±1.5 % at 35 V.
  - [DS] p.7 lists these under "Battery Only Mode"; accuracy while charging is not separately tabulated.
- **Coulomb counter:**
  - qLSB = QCOUNT_PRESCALE_FACTOR/(8333.33 × RSNSB). ±1.5 % TCE for 10-50 mV, < 1 % at 1 mV ([DS] p.8, p.59).
  - en_qcount default 0, so firmware must enable it.
- **J-guard port:**
  - G1 (bus-side I_fc + I_batt) uses the Teensy INA253s, unchanged.
  - G2 uses VIN × IIN against VBAT × IBAT.
  - G3 (GENSTAT 5/6/7) maps to CHARGER_STATE bat_short_fault / bat_missing_fault / max_charge_time_fault, plus
    SYSTEM_STATUS thermal_shutdown / vin_ovlo / cell_count_error / no_rt ([DS] p.52-54).
- **Per-decel resolution for the EMS ([REGEN]):** 0.2-0.66 C per hard decel against 0.122 mA LSB and 11 ms refresh.
  Usable, and the hardware coulomb counter is the better integrator.

## 4. EVM modifications (DC2039A Rev 5 designators)

| # | Change | Why |
|---|---|---|
| E1 | Remove **C26** (120 µF/40 V); remove **C4, C5** (VIN) and **C22-C25** (SYS) | Inrush ≤ 1.0 A (H8) |
| E2 | **RSNSB** 4 mΩ → **12 mΩ** (KRL3216T4 family, 1 %) | 2.67 A hardware ceiling at POR (H5) |
| E3 | **RSNSI** 3 mΩ → **20 mΩ** | 1.6 A input ceiling (regen 1.19 A needed); FC 1.0 A set by register (H5) |
| E4 | UVCL divider: replace **R3** with 0 Ω and remove **M1, M2, U2, R1, R2, D1** (MPPT threshold switch); set R4/R6 for k ≈ 15.83 (e.g. R4 158k / R6 10.7k, 0.1 %) | POR threshold = 19.0 V (H3, H4) |
| E5 | **JP1 = OFF** (MPPT low through R19 1M); never fit ON | MPPT would lower the threshold below the bus |
| E6 | **JP2 = EXT**; fit 10.0 kΩ (or the pack NTC) from E6 (NTC) to E5 (GND) | The digital pot U5 is dead without USB; JEITA region 3 |
| E7 | Remove **U4** (PIC16F1459); optionally **U3** (LTM2884); leave J1 open; wire **DVCC (J4 pin 2) to Teensy 3V3**; SDA/SCL/SMBALERT/GND via the J4 footprint; R27-R29 removed or kept as 3V3 pull-ups | Teensy is the sole I2C master (H9) |
| E8 | Add the **UVCLFB inhibit**: N-FET drain at the R4/R6 node (or pin 8), source GND, gate 100k to INTVCC; permit chain = two series N-FETs (gates: Teensy pin 5, TLV3012 output; 100k pull-downs) pulling the gate low | Teensy-commanded fail-safe inhibit (H2, H3) |
| E9 | Optional: re-compensate VC (Cc 0.22 µF → ~10-15 nF, Rc and Cc2 scaled per [DS] p.42) | Warm response and inhibit latency; stability bench needed |
| E10 | Optional: split **DRVCC** from INTVCC (C14 10 µF stays on INTVCC; add ≥ 2.2 µF on DRVCC) through a P-FET as a latched converter-off | Second, true converter-off (H2) |
| B1 | Board: **bridge D-BT-SQ** (VCHG ↔ VBT); keep BATSENS local on the EVM (BAT turret) | H7 |
| B2 | Board: C-D8/C-D10 → ≥ 35 V parts ([SPEC] s2) | H6 |

## 5. Register map excerpt and configuration sequence

| Reg | Name | Bits | Default | Write |
|---|---|---|---|---|
| 0x14 | CONFIG_BITS | b8 suspend_charger, b3 mppt_en_i2c, b2 en_qcount, b4 force_meas_sys_on | 0x0000 | b2 = 1; b3 = 0 always |
| 0x15 | IIN_LIMIT_SETTING | 5:0, (N+1) × 0.5 mV/RSNSI | 0x3F | regen 0x3F (1.6 A); FC 39 (1.00 A) |
| 0x16 | VIN_UVCL_SETTING | 7:0, (N+1) × 4.6875 mV at UVCLFB | 0xFF | regen 0xFF (19.0 V); FC 188 (14.03 V) |
| 0x1A | ICHARGE_TARGET | 4:0, (N+1) × 1 mV/RSNSB (ignored if en_jeita = 1) | 0x1F | 29 (2.50 A) or as EMS |
| 0x1B | VCHARGE_SETTING | 4:0, N/80 + 3.8125 V/cell | 0x1F (4.2) | 29 (4.175 V/cell) |
| 0x1D | MAX_CV_TIME | s | 14400 | per test plan |
| 0x1E | MAX_CHARGE_TIME | s, 0 = off | 65535 | 0 or per plan |
| 0x29 | CHARGER_CONFIG_BITS | b0 en_jeita, b2 en_c_over_x_term | jeita 1 | en_jeita 0 (or use 0x28 icharge_jeita_3) |
| 0x34 | CHARGER_STATE | b8 suspended, b6 cc_cv, b5 ntc_pause, b4 timer_term, b2/b1/b0 faults | R | readiness and G3 |
| 0x35 | CHARGE_STATUS | b3 vin_uvcl_active, b2 iin_limit, b1 CC, b0 CV | R | inhibit cross-check |
| 0x39 | SYSTEM_STATUS | b13 charger_enabled, b11 mppt_en_pin, b6 ok_to_charge, b4 thermal_sd, b3 vin_ovlo, b2 vin_gt_vbat | R | G3 / MPPT-pin check |
| 0x3A-0x40 | VBAT, VIN, VSYS, IBAT, IIN, DIE_TEMP, NTC_RATIO | | R | telemetry |
| watchdog | none | | | MCU WDT required |

**Write-order rule:** the threshold must always move **last when lowering** and **first when raising**, each write
read back:
- Entering FC: IIN → 1.0 A (verify), then UVCL → 188 (verify), then release the permit.
- Leaving FC: inhibit, UVCL → 0xFF (verify), then IIN → regen value.

A failed write in either direction leaves the safe (high-threshold) state.

## 6. Timing diagrams (in words)

**Run entry (always-powered regen standby), D-BT-SQ bridged:**
1. t0: MOT_PWR already closed (V-MOT ≈ VBUS). Pin 5 LOW, so UVCLFB is grounded (inhibit).
2. Firmware closes D-BC-RG (pin 30).
3. t0 + 8 ms (RT1987 tD_ON) to t0 + ~9.5 ms: VCHG-IN ramps at 12 V/ms. SYS follows through M5's body diode; the INFET
   enhances 550 µs later.
4. When VIN > BATSENS + 200 mV, the charger leaves suspended. **Battery detection 2-4 s** (1 mA), then soft-start
   (≤ 12.4 ms of DAC ramp, but the current is held at 0 by the inhibit).
5. During detection the firmware verifies the config by readback and checks CHARGER_STATE = cc_cv_charge,
   vin_uvcl_active = 1, IBAT ≈ 0, mppt_en_pin = 0.
6. Once the [LOOP] comparator is armed, pin 5 goes HIGH (permit).
7. Standby: V-MOT ≈ 16 V < 18.2 V zero point, so IBAT ≈ 0 and the input draw is ≈ 4 mA bias.

**Braking burst:**
1. V-MOT starts rising within ~5 ms of I_cmd < 0 and reaches 21.35 V in 19-47 ms if unabsorbed ([REGEN]).
2. Crossing ~18.2-19.0 V, UVCL releases. VC slews (est. 1.6 ms stock, ~70 µs re-compensated). IBAT rises to
   min(ICHARGE, IIN limit × VIN/VBAT × η, CV), and V-MOT is held near 19.0 V while regen power exceeds 23 W.
3. Burst end: V-MOT falls below 19 V. UVCL returns the current to 0, and the state stays cc_cv_charge (no re-detection).
4. Comparator trip (V-MOT < 1.067 × VBUS - hysteresis) forces the inhibit within the M-L2 latency.

**Regen → FC (assertFcChargeEnable path):**
1. Pin 5 LOW (inhibit).
2. Open D-BC-RG.
3. Close D-BC-FC. Its tD_ON is 8 ms; VCHG-IN droops ≈ 4 mA/40 µF = 0.1 V/ms, so ≈ 0.8 V and stays ≫ BATSENS. No
   re-detection, as long as the gap is ≪ ~70 ms.
4. Write IIN 1.0 A (verify).
5. Write UVCL 188 (verify).
6. The FC hardware permit is satisfied (FC_CHARGE HIGH, BT_BUS/REGEN LOW, I_bt < 0.2 A), so pin 5 goes HIGH.
7. Charge rises at the VC slew, limited at 1.0 A input.

**FC → regen:**
1. Pin 5 LOW.
2. Write UVCL 0xFF (verify).
3. Write IIN regen value.
4. Open D-BC-FC.
5. Close D-BC-RG (MOT_PWR already closed).
6. Comparator armed, then pin 5 HIGH.

**Fault (any J-guard G1-G3, comparator/ADC disagreement, illegal switch combination):**
1. Pin 5 LOW.
2. Open D-BC-RG/D-BC-FC.
3. Write suspend_charger = 1, kept latched until the operator acknowledges.
4. Clearing it costs a 2-4 s re-detection, which is acceptable for a fault.

**Charger POR (pack disconnect, or bridge absent):** all registers return to defaults, so UVCL = 19.0 V and the charger
cannot draw from a ≤ 17.5 V bus. Firmware detects the POR as registers back at defaults (for example en_qcount = 0, or
a canary register such as QCOUNT_LO_ALERT_LIMIT ≠ the written value) and re-runs §5 before any permit.

## 7. Bench gates (all on the modified EVM, before connecting to the vehicle)

| ID | Test | Pass |
|---|---|---|
| M-L1 | Stiff VIN 16.0 / 17.5 / 18.0 V, VTH 19.0 V, pack (or bench supply + load) on BAT | IIN ≤ 10 mA; \|IBAT\| ≤ 10 mA; VSYS ≤ VIN + 0.5 V; vin_uvcl_active = 1 |
| M-L2 | Charging 2.5 A from stiff 20 V; step UVCLFB inhibit (and E10 DRVCC cut if fitted) | Input current < 50 mA within 290 µs ([LOOP]) |
| M-L3 | = [REGEN] M-R4: VIN Vth - 0.5 → Vth + 1 V step, stiff | τ_warm (63 % of ICHARGE) ≤ 4 ms; CHARGER_STATE stays cc_cv_charge; stock and re-compensated VC; stability on a 470 µF + high-impedance source |
| M-L4 | IBAT vs VIN sweep at codes 0xFF and 188 | Zero-current point ≥ 17.9 V at 0xFF |
| M-L5 | RT1987 12 V/ms ramp 0 → 16 V into VIN (FC path emulation) | Peak input current ≤ 1.0 A |
| M-L6 | Detection timing at Run entry; D-BT-SQ kept vs bridged | Bridged: cc_cv_charge within 4.5 s, no fault |
| M-L7 | Readback after DVCC = 3V3, U4 removed; Teensy off / charger on and the reverse | ACK 0x68; no rail back-powering > 0.3 V |
| M-L8 | 2.5 A at 16 V and at 21 V for 10 min | DIE_TEMP and component temperatures within rating |
| M-L9 | Charger POR in FC configuration (BAT supply drop below UVLO) | Threshold back at 0xFF; no charging from 16 V |

## 8. MCU hardware watchdog (operator ruling 5): required future work

The LTC4015 has no host watchdog, so a hung Teensy holding pin 5 HIGH with a path closed is stopped only by the hardware
comparator and the FC permit. Path A with this part therefore REQUIRES the [LOOP] §10 watchdog before any charger
session outside bench attendance:
- RTWDOG at 100 ms (primary) plus WDOG1 at 1 s (secondary); WDOG1's output not routed to pin 19 (SCL);
- a WDT reset falls into H3(a) through the RT1987 EN pull-downs and the inhibit gate pull-up;
- firmware latches ERR_MCU_WDT and requires acknowledgement before Run;
- bench proof is a forced hang: reset within the timeout, every EN below 0.6 V, the permit LOW, and IBAT → 0.
