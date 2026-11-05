# Dossier: ADI DC2038A-A (LTC4162EUFD-LAD), Path A replacement for the Ag105

Date: 2026-11-05. Board rev 20260622. Spec: `charger_eval/spec.md` ([SPEC]).

## 0. How the sources were read (read this first)
- **No primary PDF was fetched. Nothing was saved to `datasheets/`.**
  - `datasheet.chipsmall.com`, `www.analog.com` and `docs.ampnuts.ru` all failed DNS in this session, which means they are
    outside the allowed network domains. Per tool policy I stopped trying further hosts.
  - To close this dossier, allow `www.analog.com` and fetch:
    - the datasheet: `media/en/technical-documentation/data-sheets/LTC4162-L.pdf` (Rev A);
    - the demo manual: `media/en/dsp-documentation/evaluation-kit-manuals/dc2038a.pdf` (Rev 0, 2/10/2021);
    - the schematic: DC2038A, dated 3/25/2019. The REV11 PCA schematic is mirrored at docs.ampnuts.ru.
- **Evidence tiers:**
  - **[WS]** = web-search snippets quoting the LTC4162-L datasheet (Rev A copies on analog.com, Arrow, Scribd, radiolocman),
    the DC2038A demo manual, EngineerZone (EZ) threads, or the Linux driver `drivers/power/supply/ltc4162-l-charger.c`.
    These are quoted text, but not read by me in the PDF.
  - **[TRIAGE]** = the workflow triage rationale.
  - **[SPEC]** = spec.md board facts.
  - **[REC]** = my own recollection. **Always UNVERIFIED.**
- **Page and section numbers cannot be cited** until the PDFs are read. The register addresses below come from [WS] and must
  be re-read against the datasheet's register map (Rev A, ~p.36 onward per [WS]).

## 1. Verdict
- **Fit score: 3 / 10 (provisional).**
- **Common ground: PASS by architecture, UNVERIFIED on the EVM schematic.** Both sense resistors are high-side: RSNSI between
  CLP and CLN on the input, RSNSB between CSP and CSN on the battery side. GND is a single exposed-pad node.
- **Electrical envelope: good.** VIN, CLP, CLN, CSP, CSN, BATSENS+ and VOUT are rated −0.3 to 36 V absolute maximum [WS]. The
  VIN operating range is quoted as 5–35 V [WS demo-manual mirror], with up to 3.2 A of charge current (32 mV/RSNSB at 10 mΩ).
- **Input regulation: R3 numbers reachable.** The input-UV regulation register (0x16) is 8 bits, at (N+1) × 140.625 mV, a range
  of 0.14–36 V [WS].
  - 13.5 V = N 95 (exact).
  - 19.0 V ≈ N 134 (18.98 V).
  - It can be switched at runtime over I2C.
- **Showstoppers:**
  1. **Battery detection.** Every charge cycle starts with a **2–4 s battery-detection test (1 mA load), and ADI says it
     cannot be disabled** [WS, datasheet + EZ]. Under R3 every regen burst is a cold start, and a burst lasts 0.3–0.6 s. **Regen
     harvesting is impossible with this IC.**
  2. **D-BT-SQ.** With D-BT-SQ in the path, the charger's BAT node is 10 µF behind an ideal diode. Detection very likely
     reports `bat_missing_fault` and retries every 30 s [WS]. **FC charging would therefore also need D-BT-SQ bridged.**
- **Major risks:**
  1. **No enable pin.** The LAD powers up charging autonomously with defaults: 4.2 V/cell × the strapped cell count, and the
     maximum charge current [WS defaults; current default UNVERIFIED].
  2. **The EVM carries a SAM D21 MCU** on the I2C bus [WS]. It must be isolated.
  3. **The board is large.** A multi-terminal demo board with an MCU will not fit the 32 × 35 mm footprint.
  4. **UVCL is a regulation loop, not a hard off.**
- **Fair use case:** FC-only charging with D-BT-SQ bridged. Regen would need a different charger, or the re-spin (Path B).

## 2. Common ground (R-GND)
**Verdict: PASS by IC architecture. UNVERIFIED on the DC2038A schematic** (not readable).

**Pin roles [WS, datasheet pin functions]:**
- CLP (pin 5) and CLN (pin 4) are the input sense resistor terminals. Input limit = (iin_limit_target + 1) × 500 µV / RSNSI.
- CSP (pin 21) and CSN (pin 20) are the charge-current sense terminals.
- BATSENS+ (pin 19) is the battery Kelvin sense.
- INFET (pin 6) drives an N-FET for input reverse blocking between VIN and VOUT.
- BATFET (pin 22) drives an N-FET for reverse blocking between the battery and VOUT.

**Why this passes:** both shunts sit in positive rails, and there is no low-side sense pin. On the EVM, the input GND turret,
battery GND turret and IC exposed pad are expected to be one plane.

**Before ordering, confirm on the schematic:**
- no shunt, jumper or FET in GND between the VIN− and BAT− terminals;
- whether a reverse-polarity FET is in the BAT− leg (some ADI demo boards fit one; UNVERIFIED for DC2038A).

## 3. Input voltage threshold (R3) and mode switching
- **Register 0x16 `vin_uvcl_setting`** [WS, register description + EZ]:
  - read/write, 8 bits, default 31 (= 4.5 V);
  - V = (N+1) × 140.625 mV, a range of 0.140 to 36.0 V.
  - The default of 31 was confirmed by an ADI engineer [WS EZ].
- **Values for this board:**
  - FC mode, 13.5 V: N = 95 → 13.500 V.
  - Regen mode, 19.0 V: N = 134 → 18.984 V (N = 135 → 19.125 V).
  - **Threshold accuracy is UNVERIFIED** (spec asks ≤ ±3.5 % at 19 V).
- **Runtime switching:** yes, by I2C write at any time. No hardware threshold-select pin exists (UVCL is register-only on the
  -L [REC, UNVERIFIED]), so the spec's preferred FET-switched resistor option is unavailable.
- **The reset default (4.5 V) is FAIL-UNSAFE for R3.** After any input-power cycle that resets the IC, the threshold sits far
  below the 15.8 V bus until firmware rewrites it. If the IC loses power whenever VCHG-IN is removed (the case with D-BT-SQ in
  place), every power-up starts at 4.5 V.
  - The 2–4 s battery detection would in practice cover the I2C write window. That is incidental, not a guarantee.
- **The mechanism is a regulation loop.** UVCL cuts charge current to hold VIN at the setting. It is not a comparator off. EZ
  thread 120107, "UnderVoltage Control Loop Recursive", reports oscillation/recursion behaviour [WS title only; content
  unread]. Bench-verify ~0 A from a stiff 15.8 V source with N = 134.
- **Hard-off candidates:**
  - `suspend_charger` (CONFIG_BITS_REG 0x14, bit 5) halts charging [WS].
    - The datasheet warns of a deadlock "that may require factory service" when the host interface depends on battery voltage
      [WS]. Here the Teensy is powered from the pack via the LM1084, not from the charger, so the deadlock path appears not to
      apply (UNVERIFIED reasoning).
    - The bit resets to 0 on power-up, so it is not fail-safe.
  - `vin_gt_vbat`: charging also needs VIN > BATSENS+ [WS]. This is irrelevant for R3, because 15.8 V is far above 8.4 V.
- **MPPT:** `mppt_en` is OFF by default on the LAD (the "M" suffix variants default ON) [WS]. Keep it OFF. MPPT sweeps would
  defeat a fixed R3 threshold.

## 4. CV / 2S configuration and accuracy
- **Variant:** DC2038A-A = LTC4162-LAD, the I2C-adjustable Li-ion variant (marking 4162A). DC2038A-B = L40, fixed 4.0 V [WS demo
  manual + datasheet order table]. **Order the -A suffix only.**
- **Defaults:** LAD resets to the same values as L42, i.e. 4.2 V/cell, adjustable afterward [WS, EZ 113945]. The
  `vcharge_setting` default is 31 [WS EZ]. 3.8125 V + 31 × 12.5 mV = 4.2 V/cell is my mapping [REC, UNVERIFIED].
- **Cell count:** set by the three-level pins CELLS1 and CELLS0 (INTVCC / VCC2P5 / GND), via shunts on the DC2038A.
  - The demo-manual table gives **2-cell Li-ion as CELLS1 = INTVCC, CELLS0 = VCC2P5** [WS].
  - An EZ user reported the swapped pairing [WS].
  - **UNVERIFIED: read the datasheet's CELLS mapping table.**
  - Telemetry register `cell_count` reads back the decode. ADI notes it reads correctly only with the charger enabled [WS].
- **Result:** 2S × 4.2 V = 8.400 V at reset with no I2C write. That is good, and it is the one setting that survives
  power-cycling.
- **CV accuracy is UNVERIFIED** (spec needs ±0.5 %).
- **BATSENS+ placement:** it should be wired as a Kelvin to the pack (VBT at C-D12), not to VCHG. See section 6.

## 5. Charge current setting
- **Register 0x1A `charge_current_setting`**, 5 bits. I = (N+1) × 1 mV / RSNSB [WS, quoted from the JEITA context; driver
  defines 0x1A].
  - With RSNSB = 10 mΩ (the datasheet default value [WS]): 100 mA steps, 0.1–3.2 A.
  - 2.5 A → N = 24. 0.25 A → N = 1 (0.2 A) or 2 (0.3 A).
  - **The EVM's fitted RSNSB is UNVERIFIED.**
- **Register 0x15 `iin_limit_target`**, 6 bits. Iin = (N+1) × 500 µV / RSNSI [WS + driver].
  - At 10 mΩ: 50 mA steps. 1.0 A FC-mode budget → N = 19. This meets the spec's ≤ 1.0 A input limit.
- **Battery current is readable over I2C** (`ibat` telemetry; LSB not confirmed in [WS]; input-current LSB 1.466 µV/RSNSI [WS]),
  so `I_charge` stays real.
- **The default charge current at reset is UNVERIFIED.** It is likely the maximum (31 → 3.2 A), above the spec's 2.5 A and the
  pack rating (open question 4).

## 6. Behaviour through D-BT-SQ (ideal diode between charger output and pack)
- **Detection failure.** Battery detection draws 1 mA from the battery for 2–4 s [WS datasheet].
  - Through D-BT-SQ the charger's battery node is VCHG: 10 µF (C-D11) plus D-BT-SQ's own VIN draw.
  - That node collapses under 1 mA in ~tens of ms, or never rises. The expected result is `bat_missing_fault` /
    `bat_short_fault` / `bat_detect_failed_fault`, then a retry every 30 s [WS]. **This is an expected FAIL, not measured.**
  - An EZ user with no battery saw VBAT rise to 2.9 V about 1 s after VIN, then 4.2 V about 1.5 s later in 1-cell mode
    [WS, user observation]. So the no-battery behaviour is not simply "regulate to CV". Treat it as non-deterministic until
    read.
- **CV sense.** BATSENS+ reads whatever it is wired to. A Kelvin to VBT removes the 35–50 mV D-BT-SQ error. **But then
  detection would see the real pack while the current path is blocked until VCHG > VBT + 35 mV.** That interaction is
  unpredictable and needs the datasheet's detection algorithm.
- **Termination.** Termination and auto-recharge cycling would be driven by the decaying VCHG node.
- **Register loss.** The IC is powered from VIN, or from the battery through BATFET/VOUT [WS: "measurement system disabled
  when battery is only source"]. With D-BT-SQ blocking, the IC loses power and registers whenever VCHG-IN is removed. The
  UVCL and current settings must then be rewritten on every power-up. Whether registers reset on power loss was not confirmed
  [WS].
- **Option: bridge D-BT-SQ** (recommended if this part is used at all).
  - The LTC4162 then sits permanently on the pack.
  - Detection passes against a real battery.
  - The IC stays alive from the battery, so registers persist and UVCL can be pre-set to the safe 19 V value before any input
    appears.
  - Back-feed to VCHG-IN is blocked by the INFET reverse-blocking FET between VIN and VOUT [WS pin description].
    **Check that the EVM has no INFET bypass jumper.**
  - **Cost of bridging:**
    - Firmware loses its hard battery-side disconnect.
    - A permanent battery quiescent drain applies (UNVERIFIED value; telemetry is off on battery unless `force_telemetry_on`
      [WS]).
    - The BATFET then connects the pack to EVM VOUT. **VOUT must be left unloaded and unconnected.**
- **Detection still runs with the bridge.** Even bridged, detection runs at the start of each charge cycle; whether a new
  VIN arrival starts a new cycle is UNVERIFIED [REC: yes]. So **each regen burst would still start with 2–4 s of no charging.**

## 7. Start-up latency
- **2–4 s minimum to first charge current** per charge cycle (battery detection) [WS]. It cannot be disabled [WS, EZ].
- The spec requires ≤ 30 ms target and ≤ 100 ms hard maximum [SPEC §5]. **FAIL by a factor of 20–40.**
- If detection fails, the retry interval is 30 s.
- For FC mode, a 2–4 s start is acceptable (charging windows last seconds to minutes).
- Telemetry ADC readings take ~1.6 ms [WS EZ], which is irrelevant to the charge-start latency.

## 8. Fail-safe disable / Teensy reset
- **There is no charge-enable pin on the LTC4162-L** [REC; no pin found in the [WS] pin list]. The IC starts charging on its
  own, with register defaults, whenever VIN > BATSENS+ and detection passes.
- **Fail-safe therefore relies entirely on Layer 1:** the RT1987 input switches, held low by the 10 kΩ bodge plus internal
  pull-downs [SPEC §3].
- **The spec's Layer 2 (a charger-side enable defaulting OFF on pin 5) cannot be met natively.** Options:
  - (a) Add an external series P-FET or load switch on VIN, gated by pin 5 with a pull-down. This adds input capacitance and
    latency.
  - (b) Accept Layer 1 alone.
  - (c) With D-BT-SQ bridged, keep `suspend_charger` = 1 written while the IC is battery-powered. This is not fail-safe across
    a reset of the IC, but survives a Teensy reset because the IC stays powered from the pack.
- **There is no host-silence watchdog** in the register set as found [WS: none mentioned; UNVERIFIED]. Firmware must open the
  RT1987s on its own watchdog.
- **The power-on default fails the spec's "no charging until host enables it" rule.** It charges at 8.4 V and the default
  current.

## 9. I2C and rails
- **Address:** **UNVERIFIED.** 0x68 (7-bit) is my recollection and was not confirmed by [WS]. It does not conflict with
  anything, because the charger is the only device on the bus.
- **Logic rail:** the SDA, SCL and SMBALERT absolute maximum is DVCC. DVCC itself is 5.5 V absolute maximum, with a 1.8–5.5 V
  logic reference range [WS].
  - Tie DVCC to Teensy 3V3 (J1.29/30 or J2.05/06). The logic is then 3.3 V-referenced. Good.
- **Back-powering:** if DVCC is from the Teensy 3V3 while VIN is absent, the IC may be partly biased through DVCC.
  - Whether DVCC pins clamp SDA/SCL when VIN/BAT are absent is **UNVERIFIED**.
  - With D-BT-SQ bridged the IC is always battery-powered, so the question is moot.
- **EVM conflict:** the DC2038A carries a **SAM D21 MCU** (firmware per variant; USB/QuikEval GUI) [WS demo manual]. It is an
  I2C master on the same bus with its own pull-ups (likely to its 3.3 V; UNVERIFIED).
  - Isolate it: cut its SDA/SCL links or hold it in reset.
  - Remove its pull-ups; the board already has RSDA/RSCL 10 kΩ to 3V3.
  - Confirm DVCC's source on the EVM.
- **SMBALERT:** an open-drain alert. Optional; spare pin only via the CSV.
- **Bus speed:** 100 kHz per spec. Fine.

## 10. Status output
- **No STAT/CHRG pin was found in the [WS] pin list** [REC: the LTC4162 reports status only via I2C and SMBALERT].
- Use `charger_state` (0x34, 13 bits, mutually exclusive one-hot bits; e.g. `battery_detection` = 2048, `charger_suspended` =
  256 [WS driver enum]) and `charge_status` as the primary readiness source.
- Pin 6 (CHARGER_STAT) could take SMBALERT (needs `INPUT_PULLUP`) or be left unused. That needs a CSV change.

## 11. Thermistor
- NTC and NTCBIAS pins are present, with JEITA charge profiles (`icharge_jeita_*` registers) [WS].
- J-NTC can connect to NTC.
- **No-NTC behaviour is UNVERIFIED.** With JEITA enabled and the NTC open, the IC may read "cold" and suspend. Check
  `en_jeita` and the NTC-open behaviour in the datasheet, or fit a 10 k resistor.
- The B-value compatibility with the board's 10 k / B 3435 NTC ([AG] p.9) is UNVERIFIED.

## 12. Input capacitance and inrush (spec §6: C_chg ≤ ~50 µF effective, no bulk electrolytic)
- **The DC2038A input capacitance is UNVERIFIED** (schematic not readable).
- ADI demo boards of this class commonly fit a bulk electrolytic on VIN to damp hot-plug ringing [REC, UNVERIFIED]. If present,
  it must be removed. At 12 mA/µF, 100 µF draws 1.2 A, which latches OC_FC in FC mode.
- The IC's own charge-pump INFET start and switching delay are UNVERIFIED. The 2–4 s detection does guarantee no switching
  during the 1.3–1.75 ms RT1987 ramp.
- **Action:** read the BOM, keep only ceramics, and replace C-D8/C-D10 with ≥ 35 V parts [SPEC].

## 13. Efficiency and thermal at 16 V → 8 V, 2.5 A
- **UNVERIFIED.** No efficiency curve was read. It is a monolithic synchronous buck at 3.2 A, with an integrated switch and
  external input and battery N-FETs.
- [REC] Datasheet curves are in the low-to-mid 90 % range at a 2:1 step-down. Do not rely on that.
- At ~2 W regen, light-load efficiency is moot, because regen is infeasible (section 7).

## 14. Size and mounting
- The DC2038A is a full demo board with turrets, CELLS shunts and a SAM D21 MCU with USB [WS]. Dimensions are UNVERIFIED but
  certainly larger than 32 × 35 mm.
- **It cannot sit on the Ag105 footprint.** Mount it off-board with short twisted leads:
  - VIN+ / GND from pads 10 / 4;
  - BAT+ / BAT− to pads 18-19 / 14-15;
  - SDA, SCL, DVCC (3V3) and NTC.
- The lead inductance on the VIN side adds to the hot-plug ringing concern.
- A custom carrier with the bare LTC4162 (5 × 4 mm QFN-28 UFD [REC]) would fit 32 × 35 mm, but that is a design job, not an
  EVM drop-in.

## 15. Price, stock and lead time
- ~USD 197, element14 2 units [TRIAGE]. Digi-Key lists DC2038A-A [WS]. Live stock UNVERIFIED.

## 16. EVM modifications required (if pursued, FC-only)
1. Order DC2038A-**A** only (LAD).
2. Strap CELLS for 2S: CELLS1 = INTVCC, CELLS0 = VCC2P5 per the demo manual. Verify against the datasheet table, and confirm
   the `cell_count` readback = 2.
3. Isolate the on-board SAM D21 from SDA/SCL. Remove EVM I2C pull-ups.
4. Tie DVCC to the Teensy 3V3.
5. Remove any bulk electrolytic on VIN. Keep total C on VCHG-IN ≤ ~50 µF effective.
6. Replace board caps C-D8/C-D10 (25 V) with ≥ 35 V parts.
7. Wire BATSENS+ as a Kelvin to the pack (VBT, C-D12).
8. Decide on D-BT-SQ: bridging is effectively required for battery detection to pass. Leave EVM VOUT unconnected; confirm there
   is no INFET bypass.
9. Handle the NTC: fit J-NTC or a 10 k resistor, or disable JEITA by register.
10. Firmware (CSV-first for any pin change):
    - replace the Ag105 code with LTC4162 register writes: 0x16 UVCL = 95 (FC) / 134 (regen-safe default), 0x15 = 19, 0x1A = 24,
      `mppt_en` = 0;
    - poll `charger_state` and `ibat`;
    - keep `suspend_charger` = 1 when not charging (if bridged);
    - port the `J` guards G1–G3.

## 17. Risks
- UVCL is a regulation loop. Stiff-source behaviour at N = 134 and stability with a high-impedance FC source are unverified;
  see EZ thread 120107.
- It charges autonomously at power-up with defaults. There is no enable pin, and the reset UVCL of 4.5 V fails R3.
- The default charge current may be 3.2 A, above the pack rating.
- The SAM D21 sits on the I2C bus.
- Bridging D-BT-SQ removes the hard battery disconnect and adds quiescent drain.
- The CELLS pairing is ambiguous across sources.
- No-NTC JEITA behaviour is unknown.
- Stock is thin (2 units).
- No primary document was read. Every number here is [WS] or [REC].

## 18. Showstoppers
1. Battery detection lasts 2–4 s per charge cycle and cannot be disabled. Regen cold starts (≤ 100 ms required, bursts last
   0.3–0.6 s) are impossible. **Regen goal FAILS.**
2. With D-BT-SQ in place, battery detection is expected to fail against a 10 µF diode-isolated node (retry every 30 s). FC
   charging needs D-BT-SQ bridged; with it in place, both goals FAIL.

## Sources (web search only; none read as PDF)
- LTC4162-L datasheet Rev A: https://www.analog.com/media/en/technical-documentation/data-sheets/LTC4162-L.pdf (also Arrow
  mirror static6.arrow.com, Scribd 604800310, radiolocman di=170443)
- DC2038A demo manual Rev 0: https://www.analog.com/media/en/dsp-documentation/evaluation-kit-manuals/dc2038a.pdf ;
  https://www.mouser.com/pdfDocs/DC2038A.pdf ; manuals.plus mirror
- DC2038A schematic REV11: https://docs.ampnuts.ru/analog.com.datasheet/ltc4162-f/related_data/710-DC2038A_REV11_PCA_SCHEMATIC.pdf
- Linux driver: https://codebrowser.dev/linux/linux/drivers/power/supply/ltc4162-l-charger.c.html
- EZ threads: 113945 (LAD defaults), 111362 (battery detection), 547879 (no battery), 120107 (UVCL loop), 539432 (MPPT reg)
- Digi-Key DC2038A-A: https://www.digikey.com/en/products/detail/analog-devices-inc/DC2038A-A/9996133
