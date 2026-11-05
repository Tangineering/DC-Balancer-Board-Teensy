# Path A design mockup: ADI DC2039A (LTC4015) on the Ag105 pads of board rev 20260622

Status: DESIGN MOCKUP. Provisional until the primary sources are read. Date 2026-11-05.

## Source status (read this first)

- **No LTC4015 or DC2039A primary document was read.**
  - `www.analog.com` fails DNS in this session. The earlier agents also found dtsheet.com, chipsmall.com, ampnuts.ru and datasheet.eeworld.com.cn blocked.
  - The workflow's WebSearch budget ran out on this step after one query. That query confirmed only that `EN_LIMIT_ALERTS` sits at 0x0D.
  - **`www.analog.com` must be allowed in the session's network settings** to close the items below. The documents needed are the LTC4015 datasheet (Rev B) and the DC2039A Demo Manual (Rev D) with its schematic.
- **Tags used for every LTC4015/DC2039A figure:**
  - [REC] = my own recollection of the LTC4015 datasheet. UNVERIFIED.
  - [WS] = an earlier agent's web-search summary, as recorded in the dossier. UNVERIFIED.
  - Board-side figures come from `spec.md`, `incident.md`, `firmware_impact.md` (same folder), the repo design files and the fw v37 rev 2 `.ino`.
- **DC2039A designators:** I have no copy of the DC2039A schematic, so I cannot give real reference designators. Every EVM part is named by function, with a placeholder such as `<RSNSB>`. A transcription pass against the DC2039A schematic is item 0 of the bench plan.
- Board tags: [SPEC] = `spec.md`, [INC] = `incident.md`, [FWI] = `firmware_impact.md`, [FW] = `teensy_controller.ino` fw v37 rev 2, [RT] = RT1987 DS-00, [AG] = Ag105 DS V1.1, [TPS] = TPS61288 SLVSFP3C.

## Executive decisions in this mockup

1. **Charge-current hardware ceiling: swap RSNSB 4 mΩ → 12 mΩ.**
   - The IC full scale is 32 mV, so 32 mV / 12 mΩ = 2.67 A [REC].
   - `ICHARGE_TARGET` = 29 then gives 2.50 A.
2. **Input-current hardware ceiling: swap RSNSI 3 mΩ → 32 mΩ.**
   - 32 mV / 32 mΩ = 1.00 A [REC].
   - This one resistor bounds a failed R3 (bus feeding the charger) to about 16 W. The incident drew about 170 W.
3. **UVCL divider strapped to 19.2 V (150 kΩ / 10.0 kΩ, 0.1 %).**
   - At POR, the input threshold therefore sits above any voltage the boosts can put on the bus.
   - For FC-charge mode, firmware lowers it to 13.5 V over I2C (`VIN_UVCL_SETTING` = 179) [REC].
   - Loss of the register at a power cycle fails safe, back to 19.2 V.
4. **Pin 5 becomes `CHG_ENABLE` (active HIGH), acting through an inverting 2-FET stage that grounds UVCLFB.**
   - Pin LOW, floating, or Teensy in reset: UVCLFB is held at 0 V and the charger regulates to about 0 A.
5. **Pin 6 becomes `CHG_ALERT`, wired to the open-drain SMBALERT with `INPUT_PULLUP`.**
6. **D-BT-SQ stays fitted (not bridged).**
   - This follows the safety lens over the dossier: it keeps the firmware's battery-side hard disconnect.
   - Cost: the LTC4015 is unpowered between bursts, so every power-up is a POR and firmware rewrites the configuration each time.
7. **BATSENS is Kelvin-sensed at the Ag105 VBAT+ pad (the charger's own output node), not at VBT.**
   - Sensing at VBT would open the CV loop whenever D-BT-SQ blocks.
8. **Mounting: the DC2039A goes off-board on 150 mm leads (20 AWG twisted pairs) from a small adapter header soldered into the Ag105 holes.**
   - A 470 nF + 10 µF/0.15 Ω RC damper sits at the EVM input.
   - No electrolytic anywhere on VIN or SYS.
9. **The board's C-D8 and C-D10 (VCHG-IN, 10 µF / 25 V) are replaced with 10 µF / 50 V X7R 1206 parts.**
   - At DC bias that is about 6 µF effective each; the replacement needs a part check.

---

## 1. Wiring

### 1.1 Wiring table: Ag105 pad to DC2039A

Ag105 pad numbers and coordinates are from [SPEC] §1. DC2039A terminal names are functional; the real turret/header IDs come from the DC2039A schematic and are UNVERIFIED.

| Ag105 pad (pin) | Board net | DC2039A terminal (functional) | Wire | Max length | Current (rms / peak) | Notes |
|---|---|---|---|---|---|---|
| VIN+ (10) | VCHG-IN | VIN+ turret | 20 AWG silicone, twisted with the VIN− wire | 150 mm | 1.0 A DC (RSNSI ceiling) / 1.0 A | Twist ≥ 1 turn per 25 mm. The input AC (0.9–1.25 A rms at 355 kHz [REC f_sw]) must circulate in the EVM's local ceramics, not in the lead (§1.3). |
| VIN− (4) | GND | VIN− / GND turret | 20 AWG, twisted with VIN+ | 150 mm | 1.0 A | This is the input return. On the EVM it must be the same copper as BAT−, checked by continuity (§2 step M0). |
| VBAT+ (18 and 19, tied) | VCHG (polygon, C-D11, D-BT-SQ VIN) | BAT+ turret | 20 AWG, twisted with BAT− | 150 mm | 2.5 A DC, small AC (inductor-side ripple is filtered by the EVM output caps) | Use both pads, for 2 × 0.64 mm pin capacity. |
| VBAT− (14 and 15, tied) | GND | BAT− turret | 20 AWG, twisted with BAT+ | 150 mm | 2.5 A | No sense element or jumper in this path on the EVM (§2 M0). |
| VBAT+ (18), second wire | VCHG | BATSENS+ (Kelvin input; pin name UNVERIFIED) | 26–28 AWG, twisted with the GND-sense wire | 150 mm | µA | Kelvin sense of the charger's own output node, upstream of D-BT-SQ. **Never connect it to VBT.** |
| VBAT− (14), second wire | GND | BATSENS− / GND sense (if the EVM has one) | 26–28 AWG | 150 mm | µA | If the EVM has no BATSENS− pin, leave this out. |
| SDA (8) | Teensy 18, 10 kΩ to 3V3 | SDA (QuikEval header pin; UNVERIFIED) | 26 AWG, in a 4-wire twisted bundle with SCL, GND, 3V3 | 150 mm (about 30–40 pF) | – | 100 kHz only [SPEC §3]. Remove the EVM's own SDA pull-up. |
| SCL (7) | Teensy 19, 10 kΩ to 3V3 | SCL | 26 AWG | 150 mm | – | Remove the EVM's own SCL pull-up. |
| (none on the pads) 3V3 from J1.29/30 or J2.05/06 | 3V3 | DVCC (SMBus logic supply; pin role [REC]) | 26 AWG | 150 mm | < 1 mA [REC] | Sets the LTC4015's SMBus logic level to 3.3 V. Do not take DVCC from the QuikEval 5 V. |
| MPPTD (11) | Teensy 5 (driven LOW at boot) | Enable-gate input on the add-on circuit (§2, mod M7) | 26 AWG | 150 mm | µA | Repurposed as `CHG_ENABLE`, active HIGH. |
| STAT (3) | Teensy 6 | SMBALERT (open drain [REC]) | 26 AWG | 150 mm | µA | `INPUT_PULLUP` in firmware. Optional external 10 kΩ to 3V3 at the adapter. |
| THERM (13) | J-NTC pin 1 | NTC (thermistor input) | 26 AWG, twisted with the NTC return | 150 mm | µA | 10 k B3435 NTC on the pack ([AG] p.9 value). EVM NTCBIAS resistor 10 k [REC]. |
| (J-NTC pin 2) | GND | NTC return / GND | 26 AWG | 150 mm | – | |
| (none on the pads) FC_CHARGE net at J1.45/46 | RT1987 D-BC-FC EN | Optional only, if hardware threshold select is chosen (§3.4b) | 26 AWG | – | – | Not used in the baseline mockup. |
| Unused pads 1, 2, 5, 6, 9, 12, 16, 17, 20–22 | floating | – | – | – | – | Adapter header pins provide mechanical anchoring only. |

**Adapter:** a 22-position strip of 2.54 mm pin header in the Ag105 holes (two rows, 25.00 mm apart [SPEC §7]), on a small perfboard or carrier no larger than 32 × 35 mm.
- The 20 AWG leads solder to the carrier.
- The carrier carries mod M7 (the enable inverter) and the optional STAT pull-up.
- It needs a ≥ 2.54 mm standoff over D-BT-SQ, C-D11 and C-D12 [SPEC §7].
- Strain-relieve the lead bundle to the chassis. The LM1084 sits 1.8 mm to the right and runs hot, so route the bundle away from it.

### 1.2 Copper loss and drop (20 AWG = 33.3 mΩ/m; loop = 2 × length)

| Pair | Loop R at 150 mm | I²R | Drop | Effect |
|---|---|---|---|---|
| BAT (2.5 A CC) | 10.0 mΩ | 62 mW | 25 mV | None on CV, because BATSENS is Kelvin-sensed at the pad. Current tapers in CV, so at the 0.25 A termination the drop is 2.5 mV. |
| BAT at 300 mm (if 150 mm proves impossible) | 20.0 mΩ | 125 mW | 50 mV | Still acceptable with Kelvin sense. |
| VIN (1.0 A ceiling) | 10.0 mΩ | 10 mW | 10 mV | Negligible against the 19.2 / 13.5 V thresholds. |
| 22 AWG BAT at 150 mm (for comparison) | 15.9 mΩ | 99 mW | 40 mV | Usable, but 20 AWG is preferred for fusing margin. |

Recommendation: 20 AWG, 150 mm maximum, 300 mm absolute. 18 AWG adds nothing electrically and is stiffer on the adapter.

### 1.3 Ripple current, lead inductance, local capacitance

- **Buck input AC current:** `I_rms = I_o·√(D(1−D))`, with D = 8.4 / V_IN.
  - 16 V at 1.79 A out: 0.89 A rms.
  - 21 V at 2.35 A out: 1.15 A rms.
  - Worst theoretical case (16 V, 2.5 A): 1.25 A rms.
  - This AC must be supplied by ceramics on the EVM's SYS node, which is the buck input after the INFET [REC topology]. The input lead only carries DC.
- **Input ripple voltage** at f_sw 355 kHz [REC], `ΔV = I_o·D(1−D)/(f·C)`:
  - 21 V, 2.35 A: 0.16 V p-p with 10 µF effective, 0.08 V with 20 µF effective.
  - **So the SYS node needs ≥ 20 µF effective ceramic.** The EVM's existing SYS ceramics are UNVERIFIED; keep them.
- **Lead inductance:** about 0.6 µH/m for a twisted pair (rule-of-thumb, UNVERIFIED), so the 150 mm VIN pair is about 0.1 µH. The VCHG-IN board trace (110 mm, 1.524 mm wide over the pour) adds about 0.1 µH, for L ≈ 0.2 µH total.
- **Lead-and-capacitor resonance:** f₀ = 1/(2π√(LC)).
  - With 10–30 µF on the EVM side, f₀ = 113–65 kHz and Z₀ = 0.14–0.08 Ω.
  - All-ceramic means the Q is high, so it rings on abrupt events: D-BC-RG turn-off mid-burst, D-BT-SQ re-close, or a burst onset at a buck load step.
  - The RT1987 turn-on ramp (1.3–1.75 ms, against a 9–15 µs ring period) is too slow to excite it.
- **Damper at the EVM VIN turret:** 10 µF / 50 V X7R in series with 0.15 Ω (≈ Z₀, 0805 resistor), plus 470 nF / 50 V directly across it for HF.
  - This adds only about 10 µF to the inrush budget, about 0.12 A.
  - **Do not use a bulk electrolytic.** 470 µF would draw 5.6 A, the Death-5 class [SPEC §6].
- **Board end:** no extra capacitance on VCHG-IN beyond the uprated C-D8 and C-D10.
- **Battery end:** keep C-D11 (10 µF, on VCHG). The EVM's BAT output ceramics (UNVERIFIED value) see the D-BT-SQ step load ([RT] p.15 Table 1: no soft-start after a reverse block). Remove any BAT-side electrolytic on the EVM as well, so the charger output is not a large reservoir dumped into the pack when D-BT-SQ closes. It is not an inrush issue, because the pack is the stiff side.

### 1.4 Block diagram (SVG: `mockup_LTC4015.svg`, same folder)

```
 VBUS 16.0V ─[D-BC-FC RT1987, EN=pin31]─┐
                                         ├─ VCHG-IN ──(C-D8,C-D10 → 50V)── Ag105 pad 10 ══20AWG/150mm══╗
 V-MOT ──────[D-BC-RG RT1987, EN=pin30]─┘     │                                                        ║
                                     R1-CHG/R2-CHG → pin38                                              ║
                                                                                                       ║
  DC2039A (off-board) ┌──────────────────────────────────────────────────────────────────────────────┐║
  VIN+ ◄═══════════════╪══ [damper 10µ+0.15Ω ∥ 470n] ─ INFET ─ RSNSI 32mΩ ─ SYS(≥20µF cer) ─ buck ─ L ─ RSNSB 12mΩ ─┐
  VIN− ════════════════╪══ GND ═════════════════════════════════════════════════════════════════════════════════════╪═ BAT−
                       │   UVCLFB ← 150k/10k (19.2V) ; Q1 (UVCLFB→GND, gate←INTVCC/100k) ; Q2 (Q1 gate→GND, gate←pin5) │
                       │   DVCC ← 3V3 ; SDA/SCL (EVM pull-ups REMOVED) ; SMBALERT → pin6 ; NTC ← J-NTC              │
                       └─────────────────────────────────────────────────────────────────────────────────────── BAT+ ┘
                                                                                                       ║
  Ag105 pads 18/19 (VCHG) ◄══20AWG/150mm══ BAT+ ; BATSENS Kelvin ── pad 18                              ║
  VCHG ─(C-D11)─ D-BT-SQ RT1987 (EN=pin32, kept) ─ VBT = pack+ (2S 7.4-8.4V) ─ BT boost, LM1084 5V
  Pads 14/15 + 4 = GND = pack−  (one node, no shunt)
```

---

## 2. DC2039A modifications and jumper settings

Every designator is a placeholder until it is transcribed from the DC2039A schematic. The stock values are [WS] (dossier) and the formulas are [REC].

| # | EVM item (placeholder) | Stock | Change to | Why / computation | Source status |
|---|---|---|---|---|---|
| M0 | VIN− ↔ BAT− continuity (the R-GND requirement) | – | Verify < 5 mΩ copper, with no jumper, shunt or FET in the path | The incident's root cause [INC (a)]. Do this check before buying a second unit. | Schematic UNVERIFIED |
| M1 | `<RSNSB>` (CSP–CSN, in BAT+) | 4 mΩ (7.9/8/8.1 A [WS]) | **12 mΩ, 1 %, ≥ 0.5 W, 2512** (13 mΩ if the pack is limited to < 2.5 A: 2.46 A max) | I_CHG = (N+1)·1 mV / RSNSB, with N = 0..31 [REC]. Max 32 mV / 12 mΩ = 2.67 A. Step 83.3 mA. 2.5 A × 12 mΩ = 30 mV of signal. Dissipation at 2.67 A: 86 mW. | [WS] stock, [REC] formula |
| M2 | `<RSNSI>` (CLP–CLN, input side) | 3 mΩ [WS] | **32 mΩ, 1 %, ≥ 0.25 W, 2010/2512** | I_IN = (N+1)·0.5 mV / RSNSI, with N = 0..63 [REC]. Max 1.00 A, step 15.6 mA. 32 mW at 1 A. This is the POR bound for a failed R3. | [WS]/[REC] |
| M3 | CHEM / CELLS straps (three-level, 0 Ω positions) | Factory setting **UNVERIFIED** (the dossier title claims 2S, but its own body says verify) | Li-ion "programmable" chemistry (4.2 V/cell maximum), **2 cells** | Safety-critical: BQ29200 OUT drives nothing [SPEC §0.4], so the charger's CV is the only overcharge control. A 3S strap is a fire path (12.6 V). Check the straps physically, then check `CHEM_CELLS` by readback (§4). | Table: Demo Manual Fig 3 [WS], UNVERIFIED |
| M4 | UVCL divider `<RUVCL_top>` / `<RUVCL_bot>` to the UVCLFB pin | EVM default UNVERIFIED (probably disabled or low) | **150 kΩ / 10.0 kΩ, 0.1 %, 25 ppm** | V_UVCL = 1.2 V·(1 + 150/10) = **19.20 V** (UVCLFB servo 1.2 V [REC]). Window [SPEC §4]: 18.3–20.0 V. 0.1 % resistors keep the tolerance about ±1 % plus the reference tolerance (UNVERIFIED). | [REC] |
| M5 | EVM SDA/SCL pull-ups (QuikEval/DC590 side) and any SMBALERT pull-up to 5 V | Fitted [REC typical] | **Remove** | Avoids back-powering 3V3 and putting 5 V on the Teensy's SDA/SCL. The board's RSDA/RSCL 10 kΩ to 3V3 remain the only pull-ups. Never plug a DC590 into this EVM again. | Designators UNVERIFIED |
| M6 | DVCC source jumper (if any) | Probably from QuikEval [REC] | **Feed DVCC from Teensy 3V3** (J1.29/30) | SMBus logic level 3.3 V | UNVERIFIED |
| M7 | **Add (on the adapter): enable inverter** | – | Q1: BSS138, drain → UVCLFB, source → GND, gate → 100 kΩ to the EVM's INTVCC (5 V [REC]) and to Q2 drain. Q2: BSS138, drain → Q1 gate, source → GND, gate → pin 5 net, plus 47 kΩ gate-to-GND pull-down and 1 kΩ series. | Pin 5 LOW, floating, or in reset: Q2 off, Q1 on, UVCLFB = 0 V, so the UVCL loop commands about 0 A ("regulation off"). Pin 5 HIGH (3.3 V > BSS138 V_GS(th) max 1.5 V, UNVERIFIED): Q1 off, divider active. Q1 gets its gate drive only when the charger is powered, which is the only time it matters. Q1's capacitance on UVCLFB (about 30 pF) is negligible against 9.4 kΩ (150 ∥ 10 kΩ). | Design mine; INTVCC turret UNVERIFIED |
| M8 | Bulk electrolytic(s) on VIN / SYS / BAT | Likely fitted (ADI demo practice; UNVERIFIED) | **Remove every one** | The inrush budget (§3.1) | UNVERIFIED |
| M9 | VIN and SYS ceramics | UNVERIFIED | Keep ≥ 20 µF effective on SYS. Cap total VIN + SYS at ≤ 40 µF effective at 16–21 V bias. Add the damper (§1.3). | §1.3, §3.1 | – |
| M10 | INFET bypass jumper or 0 Ω (if any) | UNVERIFIED | **Must be open / not fitted.** Confirm INFET orientation (source toward VIN, body diode VIN → SYS). | The INFET is what blocks pack/SYS → VCHG-IN back-feed when D-BT-SQ is bridged. With D-BT-SQ kept, it still blocks SYS → VIN after a burst. | UNVERIFIED |
| M11 | NTC: EVM `<RNTCBIAS>` and on-board thermistor (if any) | UNVERIFIED | Keep RNTCBIAS = 10 kΩ. Remove any EVM-mounted NTC or fixed resistor. Wire NTC to J-NTC with a 10 k B3435 NTC **on the pack**. | **Do not fit a fixed 10 k resistor on the vehicle** (safety lens): it would disable the only pack-temperature protection. An open NTC reading "cold" makes JEITA pause charging, which is fail-safe. | [REC] JEITA default on |
| M12 | MPPT pin/jumper (if the DC2039A has an MPPT enable pin strap) | UNVERIFIED | MPPT **off** (pin low/strapped off) | MPPT overrides UVCLFB (ADI EngineerZone, per the verdicts), which would defeat R3 | UNVERIFIED |
| M13 | EQ / other chemistry-only jumpers | – | Default / irrelevant for Li-ion | – | – |

**Board-side modifications**

| # | Item | Change |
|---|---|---|
| B1 | Ag105 (CHG) | Cut the pins and remove them one at a time. The GND pads have no thermal relief. Check barrel continuity on every used pad [INC (d)]. |
| B2 | C-D8, C-D10 (VCHG-IN, 10 µF / 25 V) | 10 µF / 50 V X7R 1206 (about 6 µF each at 20 V bias; vendor curve UNVERIFIED). Needed because V-MOT can exceed 21.4 V [SPEC §2B]. |
| B3 | C-D11 (VCHG, 25 V) | Keep. With BATSENS at the pad, VCHG is CV-regulated, so the 25 V rating holds in normal operation. Also see Risk R9. |
| B4 | D-BT-SQ | **Keep.** Damage-check it first (§5.0). |
| B5 | Adapter carrier | 22-pin header plus M7 plus terminal points for the leads |
| B6 | Teensy IO CSV | Amend before any firmware: pin 5 `MPPT_DISABLE` → `CHG_ENABLE` (OUT, active HIGH, LTC4015 UVCLFB gate); pin 6 `CHARGER_STAT` → `CHG_ALERT` (IN, pull-up, LTC4015 SMBALERT, open drain). Add a never-rotated hardware bodge record in CLAUDE.md. |

---

## 3. Quantitative checks

### 3.1 Inrush when D-BC-RG or D-BC-FC closes

- **RT1987 soft-start:** `t_ON = (V_IN/35)·(C_SS/0.0023 − 100) µs` with C_SS = 5.6 nF (C-DC8, [SPEC §6]/[RT] p.15).
  - The slew is independent of V_IN: 28 V / 2335 µs = **12.0 V/ms**.
  - So inrush is C × 12 mA/µF.
  - The ramp lasts 1.32 ms at 15.8 V (FC) and 1.75 ms at 21 V (regen), after tD_ON = 8 ms.
- **Capacitance on the switched node** (effective at DC bias; EVM values are budgets, not readings):

| Element | Nominal | Effective (est.) | Inrush |
|---|---|---|---|
| C-D8 + C-D10 (uprated, 50 V) | 20 µF | ~12 µF | 0.14 A |
| Damper 10 µF + 0.47 µF | 10.5 µF | ~7 µF | 0.08 A |
| EVM VIN ceramics (budget) | – | ≤ 10 µF | ≤ 0.12 A |
| EVM SYS ceramics (charges through the INFET body diode / ideal diode on the same ramp; it is **outside** the RSNSI loop) | – | 20–30 µF | 0.24–0.36 A |
| **Total** | – | **49–59 µF** | **0.59–0.71 A** |
| *Worst case if all nominal (no derating)* | 80 µF | – | 0.96 A |

- **Against the limits:**
  - RT1987 start-up short-circuit protection: 2.5 A initial limit, 250 µs timer [SPEC §6]. Margin is 3.5–4×, so it cannot nuisance-trip.
  - **FC mode** (the binding case, through D-BC-FC from VBUS): 0.71 A + aux 0.10–0.15 A = 0.81–0.86 A, under the ~1.0 A budget and the 1.4 A `LIMIT_I_FC_MAX` single-sample latch [SPEC §2A].
    - The buck must not switch during the ramp. Initially UVCL holds it off: VIN < 19.2 V at POR, and the M7 gate holds UVCLFB low until firmware raises pin 5 after configuration.
    - FC charging is compiled out today (`FC_CHARGE_ALLOWED 0`).
  - **Regen mode** (through D-BC-RG from V-MOT at ~21 V): the charge comes from the 470 µF V-MOT node.
    - V-MOT droop = Q/C = 59 µF × 21 V / 530 µF ≈ 2.4 V, if the ramp were instantaneous. The real ramp is spread over 1.75 ms while the motor keeps pumping, so it is smaller (UNVERIFIED).
    - If V-MOT dips below VBUS, D-MT-EN conducts and the bus tops up the charger capacitors. That is capacitor charge only, bounded at ≤ 0.71 A for ~1.75 ms. It is not a charge draw, because UVCL at 19.2 V forbids switching below 19.2 V.
- **Death-5 comparison:** 470 µF at 12 V/ms = 5.6 A, which kills a boost. This design stays under 1 A. **The hard rule is no electrolytic (M8).**
- **State-99 drains** (FC_CHARGE, then REGEN, ~10 ms each [SPEC §2D]): the switched node holds only capacitor energy (≤ 59 µF × 21 V² / 2 ≈ 13 mJ). The LTC4015 sees a brown-in/brown-out. At 19.2 V UVCL it never starts switching from a drained node. No latched fault is expected (POR clears everything).

### 3.2 CV error through D-BT-SQ

- **VCHARGE_SETTING:** `(N/80 + 3.8125) V/cell`, N = 0..31. N = 31 gives 4.2000 V/cell = 8.400 V for 2S. The register can only lower it [REC].
- **At the pack:**
  - D-BT-SQ regulates a 35 mV forward drop at light load, or 20 mΩ × I at higher current ([RT] p.7/p.16).
  - At termination (C/10 = 0.25 A) the drop is 35 mV, so **V_pack = 8.365 V (−0.42 %)**. Lead drop is excluded by the BATSENS Kelvin.
  - During CC at 2.5 A the drop is 50 mV, but the pack is below CV then, so it is irrelevant.
- **Upward compensation is impossible** (8.4 V is the code maximum). The deficit costs roughly 3–4 % of capacity at 4.18 V/cell instead of 4.2 V/cell (rule of thumb, UNVERIFIED). Accept it, or bridge D-BT-SQ (rejected in §0 decision 6).
- **Overcharge side:**
  - LTC4015 CV accuracy is **UNVERIFIED**; I recall ±0.5 % or tighter over temperature [REC].
  - Worst high at +1 %: 8.484 − 0.035 = 8.449 V at the pack, 51 mV under `LIMIT_V_BATT_MAX` 8.5 V [FW ~2140].
  - The V_batt ADC error (ADC_MAX ceiling 8.646 V per CLAUDE.md fw v30) must stay < 51 mV, or end of charge risks a nuisance OV_BATT latch. Bench test S2.4 checks this.
  - BQ29200 detects 4.35 V/cell ±25 mV, but its OUT drives nothing [SPEC §0.4].

### 3.3 Efficiency and thermal

Assumptions: 355 kHz [REC], 8 A-class FETs and inductor on the DC2039A, efficiency 93–95 % at mid load [REC/dossier]. All UNVERIFIED.

| Case | Input limit | P_in | P_out | I_out | Loss | Comment |
|---|---|---|---|---|---|---|
| 16 V → 8.4 V, **2.5 A requested** | 1.0 A (RSNSI 32 mΩ) | 15.8 W | ~14.7 W | **1.75 A** | ~1.1 W | **2.5 A is not reachable from 16 V under the FC-safe input ceiling.** Getting 2.5 A needs 1.40 A in, which breaks the FC budget and OC_FC margin. Accepted: FC mode is a 1.75 A charge. |
| 16 V → 8.4 V, 1.0 A in, FC budget at 0.8 A (`IIN_LIMIT_SETTING` = 50 → 0.797 A) | 0.8 A | 12.6 W | ~11.7 W | 1.39 A | ~0.9 W | Recommended FC-mode setting until the aux budget is measured |
| 21 V → 8.4 V | 1.0 A | 21 W | ~19.7 W | **2.35 A** | ~1.3 W | Regen peak. In practice the burst average is about 0.2 A into the pack [P37 3.2]. |
| 21 V → 8.4 V, light load (~2 W out) | – | ~2.3 W | 2 W | 0.24 A | ~0.25–0.35 W | Fixed losses: INTVCC LDO from SYS (gate charge about 20 nC × 355 kHz ≈ 7 mA, plus about 5 mA I_q [REC]) × 21 V ≈ 0.25 W. **Efficiency 85–88 %** (estimate). |

- **Thermal:** about 1.3 W on an 8 A demo board in free air is trivial (estimate). It is off-board, so it does not heat the LM1084 area.
- **Sense resistor dissipation:** 86 mW (RSNSB) and 32 mW (RSNSI).
- **Wiring loss:** 72 mW total at worst.

### 3.4 Input thresholds: FC-charge mode versus regen mode, and the R3 margin

The UVCL loop reduces charge current to keep V_IN ≥ V_UVCL. It is a regulation loop, not a hard off [WS/REC].

`VIN_UVCL_SETTING` (0x16) scales the divider threshold: V = (N+1)/256 × 19.20 V, POR N = 255 [REC].

| Mode | V_UVCL | Register | Margin vs VBUS 16.0 V nominal | Margin vs other limits |
|---|---|---|---|---|
| **POR / regen / any time the Teensy has not written** | **19.20 V** (divider) | N = 255 (POR) | **+3.2 V** above nominal; +1.7 V above firmware OV 17.5 V | +0.9 V above TPS61288 OVP minimum 18.3 V ([TPS] p.6); 0.4 V below OVP maximum 19.5 V. A boost in OVP cannot hold the bus above 19.2 V, so the bus cannot feed the charger. 2.2 V below the 21.4 V clamp, so regen bursts harvest above 19.2 V. |
| **FC charge** (only with FC_CHARGE high and REGEN/BT_BUS low, per `assertFcChargeEnable()`) | **13.50 V** | N = 179: 180/256 × 19.2 = 13.500 V | 2.5 V below nominal, so it charges from the droop-loaded bus | +1.5 V above the 12.0 V UV latch; +0.7 V above the 12.8 V UV backoff [INC (b)]. The charger backs off before the FC-only bus collapses. |
| Pin 5 LOW (M7) | UVCLFB = 0, i.e. "infinite" | – | – | Off at any V_IN, including the 21.4 V clamp |

- **R3 (no bus-fed charging in Run) is enforced three ways in this mockup:**
  1. Firmware: REGEN only closes on the v38 interlock, and the G5 gate stays closed until bench sign-off.
  2. UVCL at 19.2 V: about 0 A from a 15.8 V bus. **Bench-verify the "about 0 A" claim (S1.5)**, because it is a regulation floor, not a disconnect.
  3. RSNSI bounds it at 1.0 A (about 16 W) if 1 and 2 both fail.
- **The MPPT trap:** `mppt_en_i2c` overrides UVCLFB (EngineerZone reply, per the verdicts). Firmware writes it 0 and verifies by readback before every enable. Any read of 1 means refuse and trip.
- **Hardware threshold select (alternative 3.4b, not baseline):** a FET gated by the FC_CHARGE net (J1.45/46) switches the divider to 13.5 V.
  - A parallel top resistor of 324 kΩ gives 150 ∥ 324 = 102.5 kΩ, so 1.2 × (1 + 10.25) = 13.5 V. That FET needs high-side drive.
  - Alternatively, use a normally-on bottom-leg arrangement. **That fails unsafe if the gate floats**, so I recommend I2C-only lowering, which fails safe to 19.2 V on every POR.

### 3.5 Regen start-up latency (the main functional unknown)

- **Board overhead:** 12–20 ms [SPEC §5], of which tD_ON is 8 ms and the ramp 1.75 ms.
- **LTC4015 chain:** INTVCC up, measurement system, battery detection, NTC/JEITA qualification, soft-start. **All UNVERIFIED.**
- **Battery detection on a 10 µF node behind D-BT-SQ:**
  - The LTC4015 sources current into BATSENS to detect a battery (ez.analog.com thread 103969, per the safety verdict).
  - That current will raise VCHG until D-BT-SQ closes onto the pack at VBT + 35 mV, after which the pack is "found".
  - Alternatively the IC declares `bat_missing_fault` (CHARGER_STATE bit 1 [REC]) and retries on an unknown schedule.
  - **This is the decisive bench measurement M1 (S1.6).** If it exceeds 100 ms, regen harvesting with D-BT-SQ kept is not achievable with this candidate. FC charging (long windows) is unaffected.

---

## 4. Register / pin initialisation, and the driver sketch

### 4.1 Register map used ([REC] unless noted)

- Address: **0x68** (7-bit) [REC].
- Access: SMBus read/write word, 16-bit, low byte first.
- Verify every address and bit against the datasheet register map before any flash.

| Addr | Name | Use | Value written | Decode |
|---|---|---|---|---|
| 0x0D | EN_LIMIT_ALERTS | alert enables | 0x0000 | Address confirmed by a web snippet: `en_meas_sys_valid_alert` = bit 15 |
| 0x0E | EN_CHARGER_STATE_ALERTS | SMBALERT on fault states | 0x0007 | bits 0..2 = bat_short_fault, bat_missing_fault, max_charge_time_fault [REC] |
| 0x14 | CONFIG_BITS | suspend, measurement, MPPT | config phase: **0x0110**; run: **0x0010** | bit 8 suspend_charger; bit 4 force_meas_sys_on; bit 3 mppt_en_i2c = **0 always**; bit 2 en_qcount = 0 (no coulomb counting: the IC loses power between bursts) |
| 0x15 | IIN_LIMIT_SETTING | input ceiling | regen **63** (1.00 A); FC **50** (0.797 A) | (N+1) × 0.5 mV / 32 mΩ |
| 0x16 | VIN_UVCL_SETTING | input threshold | regen **255** (19.20 V); FC **179** (13.50 V) | (N+1)/256 × 19.2 V |
| 0x1A | ICHARGE_TARGET | charge current | **29** (2.50 A); `charge_goal` maps to 2..29 (0.25–2.50 A, 83.3 mA steps) | (N+1) × 1 mV / 12 mΩ |
| 0x1B | VCHARGE_SETTING | CV | **31** (4.2000 V/cell = 8.400 V) | N/80 + 3.8125 V/cell |
| 0x1C | C_OVER_X_THRESHOLD | termination | **2048** (0.25 A = C/10) | I × RSNSB / 1.46487 µV = 0.25 × 0.012 / 1.46487e-6 = 2048 |
| 0x1D | MAX_CV_TIME | CV timer | **3600** s | seconds |
| 0x29 | CHARGER_CONFIG_BITS | termination, JEITA | **0x0005** | bit 2 en_c_over_x_term = 1; bit 0 en_jeita = 1 |
| 0x34 | CHARGER_STATE | read | – | bit 0 bat_short_fault, 1 bat_missing_fault, 2 max_charge_time_fault, 3 c_over_x_term, 4 timer_term, 5 ntc_pause, 6 cc_cv_charge, 7 precharge, 8 charger_suspended, 9 absorb, 10 equalize |
| 0x35 | CHARGE_STATUS | read | – | bit 0 constant_voltage, 1 constant_current, 2 iin_limit_active, 3 vin_uvcl_active |
| 0x39 | SYSTEM_STATUS | read | – | bit 2 vin_gt_vbat, 3 vin_ovlo, 4 thermal_shutdown, 6 ok_to_charge, 8 cell_count_err, 13 charger_enabled |
| 0x3A | VBAT | read | – | 192.264 µV/LSB **per cell** (Li); × 2 for the pack (this reads VCHG, not the pack) |
| 0x3B | VIN | read | – | 1.648 mV/LSB |
| 0x3D | IBAT | read, signed | – | 1.46487 µV / 12 mΩ = **122.07 µA/LSB** → `I_charge` |
| 0x3E | IIN | read, signed | – | 1.46487 µV / 32 mΩ = **45.78 µA/LSB** → G2 input-power credit |
| 0x3F | DIE_TEMP | read | – | (X − 12010)/45.6 °C |
| 0x43 | CHEM_CELLS | read | – | chem nibble [11:8], cell count [3:0]. **Refuse unless Li-ion programmable and 2 cells** (bit layout [REC]). |

- **Watchdog:** the LTC4015 has **no host watchdog** [REC; the verdicts agree].
  - The host-silence stop is firmware's: on Pi or I2C silence of more than 2 s, drop pin 5 LOW, then open REGEN and FC_CHARGE.
  - The existing Pi watchdog already drives Run to Finish.
  - In a Teensy reset, layer 1 (the RT1987 EN pull-downs) and layer 2 (M7: pin 5 high-Z, so UVCLFB is grounded) both hold.
- **Pin 5 (`CHG_ENABLE`):** `setup()` already drives it LOW [FW 6720], which is "off" under M7. No code change is needed for the boot default; only the CSV and name change.
  - HIGH only after configuration and readback verification.
  - LOW first on every stop path, before any serial output.
- **Pin 6 (`CHG_ALERT`):** `pinMode(INPUT_PULLUP)`. LOW means an alert is pending: read the alert register and clear it via ARA 0x0C [REC].
  - It is **not** a "charging" signal. It replaces the old "STAT steady-LOW = no input" guard, which is removed.
  - Use I2C CHARGER_STATE as the primary readiness source.
- **Telemetry (no protocol bump required):**
  - `I_charge` = IBAT (A).
  - `ag105_status_raw` (byte 51) = a translated Ag105-style byte. GENSTAT (bits 0–2) from CHARGER_STATE:
    - fault bits 0/2 → 5 (OC/Reg Error)
    - ntc_pause / thermal_shutdown → 6
    - max_charge_time → 7
    - c_over_x_term or timer_term → 3 (Fully Charged)
    - cc_cv_charge → 2
    - precharge → 4
    - suspended / no ok_to_charge → 1
    - bat_missing → 0
  - Bit 5 = constant_voltage, bit 6 = constant_current, bit 7 = ntc_pause.
  - Recommended anyway: fold a charger-type id into the approved v5 telemetry bump [FWI].

### 4.2 Init sequence (per power-up; lazy, like `pollAg105()`)

On each power-up, after `chargerHasPower()` is true and `LTC_SETTLE_MS` = 20 ms has elapsed (TODO(calibrate) once the M1 latency is known), with pin 5 LOW throughout steps 1–4:

1. **Probe:** read 0x39 SYSTEM_STATUS. A NAK means retry next tick (no fault, matching the Ag105 lazy rule).
2. **Strap check:** read 0x43 CHEM_CELLS. If it is not Li-ion programmable / 2S, latch `ERR_CHG_STRAP` (G6, new) and keep pin 5 LOW.
3. **Configure:**
   - 0x14 ← 0x0110 (suspend, measurement system on, MPPT off).
   - 0x1B ← 31; 0x1A ← f(charge_goal) (2..29); 0x15 ← 63 or 50; 0x16 ← 255 (regen) or 179 (FC only when `assertFcChargeEnable()` owns the path); 0x1C ← 2048; 0x1D ← 3600; 0x29 ← 0x0005; 0x0E ← 0x0007.
4. **Verify:**
   - Read back 0x14, 0x15, 0x16, 0x1A, 0x1B. Any mismatch, or `mppt_en_i2c` = 1, means do not enable, and count toward G3.
   - In particular check that `VIN_UVCL_SETTING` is ≥ the mode minimum: 255 in regen.
5. **Enable:** pin 5 HIGH, then 0x14 ← 0x0010 (release suspend). Set `ltcConfigured`.
6. **Poll at 50 Hz:**
   - Every tick: 0x3D IBAT, then 0x34/0x35.
   - Every 5th tick: 0x3B, 0x3E, 0x39.
   - About 4 transactions × ~0.5 ms at 100 kHz ≈ 2 ms per 20 ms tick. Spread them round-robin (one transaction per loop tick, as the Ag105 commissioning code does), so `detectFaults()` is never stalled by more than ~0.5 ms.
7. **Power loss:** clear `ltcConfigured`, zero `I_charge`, set status 0xFF stale, the same as the Ag105 stale-clear.

### 4.3 C++ driver sketch (not in the repo; mirrors the `pollAg105` / `initAg105Charger` structure and the fw v37 rev 2 guards)

```cpp
// ---- LTC4015 replacement driver sketch (Path A, DC2039A). ALL addresses/bits [REC] — verify vs
// LTC4015 datasheet register map before use. Not compiled. ----
#define LTC_ADDR            0x68   // TODO(verify: LTC4015 DS, SMBus address)
#define LTC_REG_EN_CHGST_AL 0x0E
#define LTC_REG_CONFIG      0x14
#define LTC_REG_IIN_LIM     0x15
#define LTC_REG_UVCL        0x16
#define LTC_REG_ICHG        0x1A
#define LTC_REG_VCHG        0x1B
#define LTC_REG_CX_THR      0x1C
#define LTC_REG_MAX_CV_T    0x1D
#define LTC_REG_CHGCFG      0x29
#define LTC_REG_CHG_STATE   0x34
#define LTC_REG_CHG_STATUS  0x35
#define LTC_REG_SYS_STATUS  0x39
#define LTC_REG_VBAT        0x3A
#define LTC_REG_VIN         0x3B
#define LTC_REG_IBAT        0x3D
#define LTC_REG_IIN         0x3E
#define LTC_REG_CHEM_CELLS  0x43
#define LTC_CFG_SUSPEND     (1u << 8)
#define LTC_CFG_MEAS_ON     (1u << 4)
#define LTC_CFG_MPPT        (1u << 3)       // MUST stay 0: MPPT overrides UVCLFB (defeats R3)
#define LTC_RSNSB_OHM       0.012f          // mod M1
#define LTC_RSNSI_OHM       0.032f          // mod M2
#define LTC_IBAT_A_PER_LSB  (1.46487e-6f / LTC_RSNSB_OHM)   // 122.07 uA
#define LTC_IIN_A_PER_LSB   (1.46487e-6f / LTC_RSNSI_OHM)   // 45.78 uA
#define LTC_VIN_V_PER_LSB   1.648e-3f
#define LTC_UVCL_REGEN      255             // 19.20 V (150k/10k strap)
#define LTC_UVCL_FC         179             // 13.50 V
#define LTC_IIN_REGEN       63              // 1.00 A
#define LTC_IIN_FC          50              // 0.797 A — TODO(calibrate) vs measured aux budget
#define LTC_VCHG_2S_8V4     31              // 4.2000 V/cell
#define LTC_SETTLE_MS       20u             // TODO(calibrate): bench M1
// Guards (ported from fw v37 rev 2 J session; now also live in Run when the charger path is open)
#define CHG_G1_I_SRC_MAX_A     1.6f   // was 1.0 A (Ag105 J); healthy 1.0 A-in charge + aux + margin. TODO(calibrate)
#define CHG_G1_DWELL_MS        5u
#define CHG_G2_P_UNACCT_W      3.0f   // unchanged threshold
#define CHG_G2_DWELL_MS        20u
#define CHG_G2_ETA_MIN         0.80f  // input-side credit now MEASURED (IIN*VIN), eta only for slack
#define CHG_G3_ARM_MS          40u

bool  ltcConfigured = false, ltcTrip = false /* G4: reboot-only */;
uint32_t ltcPowerEdgeMs = 0;
float I_charge = 0.0f, ltcVin = 0.0f, ltcIin = 0.0f;
uint8_t chargerStatusByte = 0xFF;   // Ag105-style translated byte for telemetry offset 51

static bool ltcRead16(uint8_t reg, uint16_t &v) {
  Wire.beginTransmission(LTC_ADDR); Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;            // repeated start
  if (Wire.requestFrom((int)LTC_ADDR, 2) != 2) return false;
  uint8_t lo = Wire.read(), hi = Wire.read(); v = (uint16_t)lo | ((uint16_t)hi << 8); return true;
}
static bool ltcWrite16(uint8_t reg, uint16_t v) {
  Wire.beginTransmission(LTC_ADDR); Wire.write(reg); Wire.write(v & 0xFF); Wire.write(v >> 8);
  return Wire.endTransmission() == 0;
}
static inline void chargerHardStop() {          // ORDER: REGEN first (fw v37 rev 2), then enable pin
  digitalWrite(REGEN_ENABLE, LOW);
  digitalWrite(CHG_ENABLE, LOW);                // pin 5: UVCLFB grounded via M7
  assertFcChargeEnable(false);                  // existing guarded path
}

// mirrors initAg105Charger(): returns true when configured + verified + enabled
bool initLtc4015Charger(bool fcMode, uint8_t ichgCode) {
  digitalWrite(CHG_ENABLE, LOW);
  uint16_t cc; if (!ltcRead16(LTC_REG_CHEM_CELLS, cc)) return false;              // NAK -> retry later
  if (((cc >> 8) & 0x0F) != /*Li-ion programmable*/ 0x0 || (cc & 0x0F) != 2) {   // TODO(verify) codes
    ltcTrip = true; chargerHardStop(); return false;                              // G6 strap guard
  }
  const uint16_t uvcl = fcMode ? LTC_UVCL_FC : LTC_UVCL_REGEN;
  const uint16_t iin  = fcMode ? LTC_IIN_FC  : LTC_IIN_REGEN;
  bool ok = ltcWrite16(LTC_REG_CONFIG, LTC_CFG_SUSPEND | LTC_CFG_MEAS_ON)
         && ltcWrite16(LTC_REG_VCHG, LTC_VCHG_2S_8V4)
         && ltcWrite16(LTC_REG_ICHG, ichgCode > 29 ? 29 : ichgCode)
         && ltcWrite16(LTC_REG_IIN_LIM, iin)
         && ltcWrite16(LTC_REG_UVCL, uvcl)
         && ltcWrite16(LTC_REG_CX_THR, 2048)
         && ltcWrite16(LTC_REG_MAX_CV_T, 3600)
         && ltcWrite16(LTC_REG_CHGCFG, 0x0005)
         && ltcWrite16(LTC_REG_EN_CHGST_AL, 0x0007);
  if (!ok) return false;
  uint16_t r;                                            // readback verify (R3-critical fields)
  if (!ltcRead16(LTC_REG_CONFIG, r) || (r & LTC_CFG_MPPT)) return false;
  if (!ltcRead16(LTC_REG_UVCL, r) || r != uvcl) return false;
  if (!ltcRead16(LTC_REG_VCHG, r) || r != LTC_VCHG_2S_8V4) return false;
  if (!ltcRead16(LTC_REG_IIN_LIM, r) || r != iin) return false;
  if (fcMode && !digitalRead(FC_CHARGE_ENABLE)) return false;   // FC thresholds only on the FC path
  digitalWrite(CHG_ENABLE, HIGH);
  return ltcWrite16(LTC_REG_CONFIG, LTC_CFG_MEAS_ON);           // release suspend
}

static uint8_t ltcTranslateStatus(uint16_t st, uint16_t cs) {   // -> Ag105 Table 6 layout
  uint8_t g;
  if (st & 0x0001) g = 5; else if (st & 0x0004) g = 7; else if (st & 0x0020) g = 6;
  else if (st & 0x0002) g = 0; else if (st & 0x0018) g = 3; else if (st & 0x0080) g = 4;
  else if (st & 0x0040) g = 2; else g = 1;
  return g | ((cs & 0x1) ? 0x20 : 0) | ((cs & 0x2) ? 0x40 : 0) | ((st & 0x20) ? 0x80 : 0);
}

// mirrors pollAg105(): call every loop; does at most ONE I2C transaction per call (round robin)
void pollLtc4015() {
  static uint8_t rr = 0; static uint32_t lastMs = 0; static uint16_t st = 0, cs = 0;
  static bool g1Hi = false, g2Hi = false; static uint32_t g1Since = 0, g2Since = 0;
  const uint32_t now = millis();
  if (!chargerHasPower()) {                       // unchanged power gate
    ltcConfigured = false; I_charge = 0.0f; chargerStatusByte = 0xFF; ltcPowerEdgeMs = 0;
    digitalWrite(CHG_ENABLE, LOW); return;
  }
  if (ltcPowerEdgeMs == 0) ltcPowerEdgeMs = now;
  if (ltcTrip || !chargerFeedGateOpen()) { chargerHardStop(); return; }   // G4 latch + G5 gate
  // G1: bus-side source current (both boosts) — TRANSPORT-INDEPENDENT, evaluated first
  const float iSrc = I_fc + I_batt;
  if (iSrc > CHG_G1_I_SRC_MAX_A) { if (!g1Hi) { g1Hi = true; g1Since = now; }
    else if (now - g1Since >= CHG_G1_DWELL_MS) { chargerHardStop(); ltcTrip = true; return; } }
  else g1Hi = false;
  // G2: boosts' output power minus the charger's MEASURED input power (IIN*VIN) and baseline
  const float pUn = V_bus * iSrc - chgBaselineW - (ltcConfigured ? ltcVin * ltcIin / CHG_G2_ETA_MIN : 0.0f);
  if (pUn > CHG_G2_P_UNACCT_W) { if (!g2Hi) { g2Hi = true; g2Since = now; }
    else if (now - g2Since >= CHG_G2_DWELL_MS) { chargerHardStop(); ltcTrip = true; return; } }
  else g2Hi = false;
  if (now - ltcPowerEdgeMs < LTC_SETTLE_MS) return;
  if (!ltcConfigured) { ltcConfigured = initLtc4015Charger(digitalRead(FC_CHARGE_ENABLE), ichgFromGoal()); return; }
  if (now - lastMs < 4) return; lastMs = now;     // 5 slots x 4 ms = 20 ms (50 Hz) per IBAT
  uint16_t v; bool ok;
  switch (rr++ % 5) {
    case 0: case 2: if ((ok = ltcRead16(LTC_REG_IBAT, v))) I_charge = (int16_t)v * LTC_IBAT_A_PER_LSB; break;
    case 1: if ((ok = ltcRead16(LTC_REG_CHG_STATE, v))) st = v; break;
    case 3: if ((ok = ltcRead16(LTC_REG_CHG_STATUS, v))) cs = v; break;
    default: { uint16_t a, b; ok = ltcRead16(LTC_REG_VIN, a) && ltcRead16(LTC_REG_IIN, b);
               if (ok) { ltcVin = a * LTC_VIN_V_PER_LSB; ltcIin = (int16_t)b * LTC_IIN_A_PER_LSB; } }
  }
  if (!ok) { ltcConfigured = false; return; }     // brown-out/POR: lazily reconfigure (IC lost regs)
  chargerStatusByte = ltcTranslateStatus(st, cs);
  // G3: charger fault bits (bat_short, max_charge_time, thermal/NTC is a pause, not a trip)
  if ((now - ltcPowerEdgeMs) >= CHG_G3_ARM_MS && (st & 0x0005)) { chargerHardStop(); ltcTrip = true; }
}
```

**Firmware integration notes:**
- `chargerHasPower()`, `assertFcChargeEnable()` and the v38 three-layer R3 interlock are unchanged.
- `AG105_VBATN_ISOLATED` becomes `CHG_RETURN_VERIFIED`. Default 0 on real boards; open it only after the bench plan passes. HIL_SIM gets 1.
- The MPPT threshold manager (about 400 lines) and its EPROM budget are deleted. The UVCL write replaces them.
- Tests: the mock_wire needs a register-addressed responder [FWI].
- Effort per [FWI]: about 20–29 engineer-days for Path A overall.

---

## 5. Staged bench plan

### Stage 0: pre-integration damage checks (on the board, Ag105 removed) [INC (d)]

| # | Check | Pass |
|---|---|---|
| 0.1 | FC channel: 1–2 A resistive load on the bus with both sources on | I_fc ≈ half the load (±25 %) |
| 0.2 | FC only (BT_BUS off), 0.5 A load | Bus holds and I_fc ≈ load. "Reads 0 but bus holds" = sense/ADC damage. "Collapses" = FC boost or D-FC-EN damage. Stop if either. |
| 0.3 | D-BT-SQ (carried an estimated 11–13 A against an 8 A rating) | (a) EN LOW, pack connected: VCHG ≈ 0 V (< 0.1 V), so reverse block holds. (b) Forward drop at 1 A and 2 A from a bench supply on VCHG: 35–60 mV. (c) EN controls it. |
| 0.4 | D-BC-RG, D-MT-EN (carried 8–11.4 A for ~0.2 s) | The same three checks, plus soft-start ramp time at 16 V within ±20 % of 1.33 ms (scope) |
| 0.5 | Ag105 pads after removal | Barrel continuity on VIN+, VBAT+ and the GND pads to their nets: < 0.1 Ω |
| 0.6 | Bench supply | Record the current limit and what latched during ML0227 |
| 0.7 | J-BT and J-BL pack-negative bonds | J-BT terminal torque checked. Fire risk if loose [INC (c)]. |

### Stage 1: DC2039A standalone (bench supply + RT1987 stand-in + pack)

Setup:
- Bench supply (16 V, current limit 1.5 A) → an RT1987 EVM or spare D-BC-type switch with a 5.6 nF SS cap → modified DC2039A → a spare RT1987 ideal diode as the D-BT-SQ stand-in → a 2S pack with a protection board, or a 2S cell simulator / e-load in CV mode.
- Clamp meter on the BAT lead; scope on VIN (the switched node) and VCHG.
- I2C from a spare 3.3 V Teensy running the §4.3 sketch, or a USB-I2C adapter at 3.3 V.

| # | Test | Pass / fail |
|---|---|---|
| S1.0 | Mods M0–M13 done and inspected. VIN−↔BAT− continuity < 5 mΩ. RSNSB/RSNSI measured with 4-wire at 12 / 32 mΩ ±2 %. CHEM/CELLS straps photographed. | All yes, else stop |
| S1.1 | Inrush: close the stand-in switch at 16 V and at 21 V, measuring I_in with a current probe | Peak ≤ 0.8 A (budget 0.71 A estimated). Ramp 1.3 / 1.75 ms ±20 %. No RT1987 SCP retry. |
| S1.2 | POR state, pin 5 LOW (M7 holding UVCLFB = 0) at 21 V | I_BAT ≤ 10 mA; UVCLFB < 0.1 V |
| S1.3 | Readback: CHEM_CELLS, CONFIG_BITS (MPPT = 0), VIN_UVCL = 255, VCHARGE = 31 | Exact. **Fail if CHEM_CELLS ≠ 2S Li-ion.** |
| S1.4 | Enable at 21 V, ICHARGE = 29 | CC 2.50 A ±5 % on the clamp, IBAT register within ±3 % of the clamp, I_in ≤ 1.00 A ±5 % (RSNSI ceiling) |
| S1.5 | **R3 floor:** supply stiff at 15.8 V, UVCL 19.2 V, pin 5 HIGH, enabled, for 60 s | Average I_in ≤ 20 mA (capacitor/bias only), I_BAT ≤ 10 mA, `vin_uvcl_active` set, no oscillation > 0.2 V p-p on VIN. **Fail = this candidate cannot meet R3 tier 2.** |
| S1.6 | **Latency (M1):** step the input from 0 to 21 V (stand-in switch, 8 ms tD_ON + 1.75 ms ramp) with the pack at 7.6 V behind the D-BT-SQ stand-in; firmware configures at power-edge + 20 ms | Measure input-edge → I_BAT ≥ 90 % of set. **≤ 30 ms target, ≤ 100 ms hard.** Record bat_missing events. Repeat 20× at 0.5 s burst length. ≥ 18/20 must reach 90 % within the burst. |
| S1.7 | Abrupt input loss mid-CC (open the switch), then re-apply | No latched fault; restarts at the next power-up; VCHG ringing < 2 V overshoot (damper working) |
| S1.8 | CV / termination: pack near full | Pack terminal 8.36–8.40 V at C/10 termination. Never > 8.45 V. `c_over_x_term` set. |
| S1.9 | FC mode: UVCL 179, IIN 50, input from a supply with 2 Ω series (droop stand-in) | Input settles ≥ 13.3 V; I_in ≤ 0.8 A; no hunting > 0.3 V p-p |
| S1.10 | MPPT trap: write `mppt_en_i2c` = 1 | The driver detects it on readback and refuses / trips |
| S1.11 | NTC open, then NTC at 25 °C | Open: charging paused (`ntc_pause`). 10 k at 25 °C: charges. |
| S1.12 | Light-load efficiency, 21 V, 0.25 A | Record. ≥ 80 % is a goal, not a gate. |

### Stage 2: Teensy control on the real board (no motor, State 98)

Prerequisites: the CSV is amended, the new driver is in a BENCH_TEST 1 build, and `CHG_RETURN_VERIFIED` is 0, so Run and `D` regen stay gated.

| # | Test | Pass / fail |
|---|---|---|
| S2.1 | Boot / reset / reflash, with the charger wired and FC_CHARGE/REGEN LOW | Pin 5 LOW throughout (scope through reset); UVCLFB 0 V whenever powered |
| S2.2 | I2C bus integrity, charger unpowered | SDA/SCL idle at 3.3 V; no clamping (DVCC from 3V3); Teensy reads NAK cleanly |
| S2.3 | Commissioning (the `J` replacement), bus-fed at reduced ICHARGE 0.5 A, attended | G1/G2/G3 do not fire. Charger IBAT ≈ ΔI_batt (pack) ±10 %. Bus-side I_fc + I_batt ≤ 0.9 A. Inject a G2 fault (temporarily raise ICHARGE without the credit): G2 trips within 20 ms and REGEN drops first. |
| S2.4 | Pack ADC versus charger VBAT at CV | V_batt (pin 25) within 30 mV of a DMM at the pack; no OV_BATT nuisance trip at termination |
| S2.5 | State-99 drain pulses with the charger wired | No hang; reconfigures cleanly afterwards |
| S2.6 | FC-charge window (if `FC_CHARGE_ALLOWED` is enabled for the test) via `assertFcChargeEnable()` | Inrush on I_fc ≤ 1.0 A; no OC_FC; UVCL 13.5 V holds the bus ≥ 13.3 V |

### Stage 3: Integration (vehicle on stands, scope on VCHG-IN and VCHG, clamp on the battery lead)

| # | Test | Pass / fail |
|---|---|---|
| S3.1 | Run with the v38 interlock, cruise (V-MOT ≈ bus), REGEN commanded by firmware only on V-MOT > threshold | Charger I_in ≈ 0 whenever V-MOT < 19.2 V. Zero bus-to-charger energy per R3 (the G2 log stays at baseline). |
| S3.2 | Braking bursts (RegenTest_v2 profile) | Fraction of bursts reaching ≥ 90 % charge current within 100 ms ≥ 75 %. Energy into the pack per decel recorded against the ~0.7 J estimate [P37]. |
| S3.3 | V-MOT peak during a burst with the charger loading it | Record the maximum. **Fail if > 30 V** (C-D8/C-D10/EVM ratings). |
| S3.4 | Then open `CHG_RETURN_VERIFIED` = 1 in a committed build, with the CLAUDE.md bodge record | – |

---

## 6. BOM, cost, time and residual risks

### 6.1 BOM and cost (prices are 2026-11-05 web snapshots from the practical verdict; UNVERIFIED by me)

| Item | Qty | Est. cost |
|---|---|---|
| DC2039A (USD 134–176; Mouser about USD 152, 44 in stock) | 1 (2 recommended: one sacrificial for the standalone stage) | USD 152 (304) |
| RSNSB 12 mΩ 1 % 2512 1 W (plus 13 mΩ spare) | 2+2 | USD 4 |
| RSNSI 32 mΩ 1 % 2512 | 2 | USD 2 |
| UVCL divider 150 kΩ / 10.0 kΩ 0.1 % 0603 | 2 sets | USD 3 |
| BSS138 ×2, 100 kΩ, 47 kΩ, 1 kΩ (M7) | 1 set | USD 2 |
| Damper: 10 µF 50 V X7R 1210, 0.15 Ω 0805, 470 nF 50 V | 1 set | USD 3 |
| C-D8 / C-D10 replacements 10 µF 50 V X7R 1206 | 2 (+2) | USD 3 |
| 10 k B3435 NTC with leads | 1 | USD 3 |
| 22-pin 2.54 mm header strip, perfboard carrier, 20 AWG and 26 AWG silicone wire | – | USD 10 |
| Spare RT1987 (stand-in) or RT1987 EVM | 1 | USD 5–30 |
| **Total** | – | **about USD 190 (one EVM) to 340 (two)** |

### 6.2 Time

| Task | Effort |
|---|---|
| Unblock analog.com and transcribe the DC2039A schematic/datasheet (closes the [REC] items) | 0.5–1 d |
| Hardware mods M0–M13, adapter, board B1–B6 | 1.5–2 d |
| Stage 0 damage checks | 0.5–1 d |
| Stage 1 standalone (including M1 latency) | 2–3 d |
| Minimal driver + `J` replacement + tests | 4–6 d [FWI] |
| Stage 2 | 1–2 d |
| Full Run integration + v38 interlock + HIL/EMS model update | 15–22 d [FWI] |
| **Total** | **about 25–37 engineer-days** (Path A estimate [FWI] 20–29 d, plus the hardware and bench stages here) |

- **Lead time:** stock exists (about 44 at Mouser, snapshot).
- **Go/no-go gate after about 5 days:** the Stage 1 S1.5 (R3 floor) and S1.6 (latency) results.

### 6.3 Residual risks (ranked)

1. **Every LTC4015/DC2039A number is unverified.** That includes addresses, bit positions, formulas, the UVCL mechanism, POR defaults, CV accuracy and the stock part values. **Mitigation:** allow `www.analog.com`, then transcribe before buying.
2. **Regen cold-start latency** with D-BT-SQ kept (battery detection on 10 µF, JEITA, soft-start) could exceed 100 ms and make regen harvesting ineffective. FC charging is unaffected. **Mitigation:** S1.6 is the go/no-go. The fallback is to bridge D-BT-SQ, which costs the battery-side disconnect (see 7).
3. **UVCL is a regulation floor, not a disconnect.** The R3 tier-2 floor at 15.8 V must be proven (S1.5). RSNSI bounds the failure at 1.0 A / about 16 W.
4. **`mppt_en_i2c` defeats R3 in software.** Mitigated by write-0 plus readback before every enable, and by G2.
5. **POR autonomous charging, with no charge-enable pin.** Bounded by M1/M2 and suppressed by M7 (UVCLFB grounded) plus the 19.2 V strap. The M7 "off" is itself a regulation state (verify S1.2).
6. **The CHEM/CELLS strap is the only overcharge control,** since BQ29200 OUT is orphaned. Mitigated by a physical check plus the `CHEM_CELLS` readback guard. A 3S mis-strap is a fire risk.
7. **A shorted buck top FET puts VCHG-IN (16–21 V) on VCHG.** D-BT-SQ (kept) plus the firmware OV_BATT latch opening the RT1987s are the actuators. C-D11 at 25 V survives 21.4 V but not a higher V-MOT peak. Consider 50 V for C-D11 too.
8. **The V-MOT peak above 21.4 V is unmeasured** (S3.3).
9. **CV −0.42 % undercharge** through D-BT-SQ, which cannot be compensated (the register maximum is 8.4 V). Plus an unknown CV tolerance against the 51 mV margin to the 8.5 V OV latch.
10. **Off-board leads:** vibration and strain on the adapter, lead inductance ringing (damped), I2C over 150 mm (fine at 100 kHz).
11. **FC mode limited to about 1.4–1.75 A charge** by the FC-safe 1.0 A input ceiling.
12. **Light-load efficiency** at about 2 W regen with 8 A-class FETs (estimate 85–88 %).
13. **No coulomb counting:** the IC loses power between bursts. The Pi EKF keeps using `I_charge`.
14. **The INFET orientation / bypass** must be confirmed (M10). It matters most if D-BT-SQ is ever bridged.
15. **Firmware and HIL rework** about 20–29 d, plus a CSV amendment and a never-rotated CLAUDE.md bodge record.
