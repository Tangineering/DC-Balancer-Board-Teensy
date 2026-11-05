# Dossier: TI BQ25798 (BQ25798EVM; compact alternative Mikroe Charger 25 Click MIKROE-5839 = BQ25792), Path A replacement for the Ag105

Date: 2026-11-05. Board rev 20260622. Spec: `charger_eval/spec.md` ([SPEC] below).

## 0. How the sources were read (read this first)
- **No primary PDF was fetched.** `www.ti.com` and `www.mouser.com` both fail DNS in this session, which means they are
  outside the allowed network domains. Per the tool policy I stopped trying further hosts after the second failure.
  **Nothing was saved to `datasheets/`.** To close this dossier, allow `www.ti.com` (lit/ds/symlink/bq25798.pdf,
  lit/ug/sluucb5e/sluucb5e.pdf) and `www.mouser.com` (Charger_25_Click-3318480.pdf) in the session network settings.
- Evidence tiers:
  - **[WS]** = web-search snippets of the TI datasheet, TI E2E, or the SLUUCB5 EVM guide. Tertiary; treat as leads.
  - **[TRIAGE]** = the workflow's triage rationale (TI product page figures). Secondary.
  - **[REC]** = my recollection of the BQ25798 datasheet. **Always UNVERIFIED.** Never act on it without a primary re-read.
  - **[SPEC]** = `charger_eval/spec.md` (board facts, already verified there from repo design files).
- **Literature numbers:** the EVM guide is SLUUCB5, rev E (Jul 2022) [WS], and covers BQ25792EVM, BQ25798EVM and
  BQ25798BKUPEVM, schematics in Figs 4-6/4-7 [WS]. One search engine named the datasheet SLUSDV2; this is UNVERIFIED.
  Section and page citations to the datasheet cannot be given until it is read.

## 1. Verdict
- **Fit score: 5.5 / 10 (provisional; every number below needs a primary re-read).**
- **Fuel-cell charging: good fit.**
  - Common ground holds by architecture.
  - There is a 2S CV register, an input current limit settable to ≤ 1.0 A, and a VINDPM inside the 13.5 V window.
  - Charge current is read back internally, so `I_charge` stays real.
- **Regen: weak fit.** Three reasons:
  1. **Cold start too slow.** Under R3 every burst is a cold start. The IC's own start-up chain is ~20 ms to I2C access,
     ~30 ms of poor-source qualification, and ~30 ms after D+/D- detection before switching [WS]. That is ≥ ~80 ms before
     charge soft-start, plus 12–20 ms of board overhead [SPEC s5]. This is at or past the 100 ms hard maximum.
  2. **Thin headroom.** The 24 V operating ceiling sits only 2.6 V above the 21.4 V clamp, and the V-MOT overshoot above
     the clamp is unmeasured.
  3. **No hard-off threshold.** R3 can only be met by VINDPM (a regulation loop) or a host-written HIZ.
- **The Click is not a drop-in.** Its POR behaviour (charging enabled with jumper defaults) and unknown input capacitors and
  I2C pull-ups need rework. A custom carrier inside 32 × 35 mm is the better Path A form factor.

## 2. Common ground (R-GND)
- **Verdict: PASS by IC architecture. UNVERIFIED on the EVM and Click schematics** (SLUUCB5E Figs 4-6/4-7 and the Click
  schematic were not readable).
- The BQ25798 is an integrated 4-FET buck-boost with an integrated BATFET and internal current sensing; it needs no external
  charge-current shunt [TRIAGE]. There is one GND/PGND node for the VBUS return and the battery [TRIAGE].
- Nothing is expected between EVM input GND and battery GND. **Before ordering, confirm on the schematic** that no shunt,
  jumper or FET sits between the VBUS-return and BAT-return terminals (EVM and Click).

## 3. VIN operating range, absolute maximum, OVP
- VBUS operating range 3.6–24 V; absolute maximum 30 V [WS, TRIAGE].
- VAC OVP (VAC_OVP[1:0], shared by VAC1/VAC2) [WS]:

  | Setting | Rising threshold | Falling threshold |
  |---|---|---|
  | 00 | 26 V | 25.2 V |
  | 01 | 18 V | – |
  | 10 | 12 V | – |
  | 11 | 7 V | – |

  The POR default is UNVERIFIED. It must be checked: 18 V or below would trip during regen.
- Against [SPEC s2]:
  - **Operating range ≥ 12 V to ≥ 23 V without OVP: met only with VAC_OVP = 26 V.** The headroom is 1 V to the 24 V
    rating, which is thin given the unmeasured V-MOT peak (open question 1).
  - **Absolute maximum ≥ 30 V: met with zero margin.** The preferred 36 V is not met.
- **The FC-mode OVP setting is an option, not a design feature.** VAC_OVP = 18 V is above the 17.5 V firmware OV and
  below the TPS61288 OVP min of 18.3 V. It would block a runaway bus in FC mode, but it is 0.5 V above firmware OV and
  needs I2C after every POR.
- **Board work:** replace C-D8/C-D10 (25 V) with ≥ 35 V parts [SPEC s2]. The module's own VBUS/PMID caps must also be
  ≥ 35 V; their rating is UNVERIFIED (section 9).

## 4. Input threshold (R3) and FC/regen mode switching
- **VINDPM (REG05):**
  - 8-bit field, 100 mV/LSB. Supporting evidence: 0x24 = 3.6 V and 0x28 = 4.0 V [WS], which is consistent with
    100 mV × code and no offset.
  - **Upper limit: UNVERIFIED.** [REC] says 22 V (0xDC).
    - If 22 V: both 13.5 V (FC) and 19.0 V (regen) are settable, and the 12.5–19.5 V range [SPEC s4] is met.
    - **If the maximum is below 19.0 V, the regen threshold cannot be set. This is a showstopper for regen under R3.**
  - **Read the REG05 description first.**
- **VINDPM is overwritten at plug-in.** A TI E2E answer [WS] says VINDPM is auto-set at plug-in to the sensed VBUS minus
  0.7 V (low-power source) or minus 1.4 V (high-power source).
  - On a 15.8 V bus that gives ~14.4–15.1 V.
  - It does **not** block the bus in FC mode at 13.5 V-class settings. A 19 V regen threshold is lost every power-up until
    firmware rewrites it.
  - **Consequence: the IC must stay charge-disabled (CE high, or EN_HIZ) until firmware has written VINDPM.**
- **The VOC-scaling MPPT is unusable here.**
  - It periodically stops the converter to sample the source's open-circuit voltage, then sets VINDPM = VOC_PCT × VOC
    [WS]. It is disabled at POR (EN_MPPT = 0) [WS].
  - On a regen burst the "VOC" is a moving V-MOT, and on the FC bus VOC is the stiff bus. Leave EN_MPPT = 0.
- **Hard off:**
  - The EN_HIZ register bit, written over I2C.
  - The ILIM_HIZ pin. The datasheet relation is V_ILIM_HIZ = 1 V + 0.8 Ω × ILIM [WS]. The pin is sampled after VBUS > UVLO
    and not re-read for the ILIM clamp [WS]. **Its HIZ-entry threshold is UNVERIFIED.**
  - There is **no programmable hysteretic input UVLO.** R3 is therefore met at the "acceptable" level [SPEC s4]: VINDPM plus
    host HIZ/CE. Bench-verify ~0 A from a stiff 15.8 V source with VINDPM = 19 V.
- **Mode switch:**
  - I2C only. There is no strap pin for VINDPM, so the spec's preferred FET-switched threshold resistor is not available.
  - **Hardware option:** a comparator on VCHG-IN (window 19.0 V regen / 13.5 V FC, selected by the FC_CHARGE net J1.45/46)
    driving ILIM_HIZ or CE, so the hard off does not depend on firmware. Feasibility depends on the ILIM_HIZ HIZ threshold
    (UNVERIFIED).
  - Firmware layer 1 and the fw v37 rev 2 `J` guards G1–G3 must be ported regardless [SPEC s4].

## 5. Charge current, input current, CV
- **ICHG:** up to 5 A, 10 mA resolution [TRIAGE]. 2.5 A is in range; the minimum is UNVERIFIED ([REC] 50 mA, which meets
  the ≤ 0.25 A requirement).
- **IINDPM:** 10 mA step [REC]. A setting ≤ 1.0 A for FC mode is plausible ([REC] range 100 mA–3.3 A, UNVERIFIED).
  - It is also clamped by the ILIM_HIZ resistor [WS], so **fit an ILIM resistor ≤ 1.0 A-equivalent.** That gives a hardware
    input-current bound that survives register resets, which suits OC_FC (1.4 A single-sample latch) [SPEC s2].
- **VREG:** 10 mV step [REC]; range ([REC] 3.0–18.8 V) and accuracy ([REC] ±0.4 %) are UNVERIFIED.
  - If ±0.4 %, it meets the ±0.5 % requirement but not the ≤ ±0.3 % needed to compensate D-BT-SQ.
  - **Set 8.400 V; the pack ends ~8.365 V** (D-BT-SQ drop, [SPEC s2]).
- **Cell-count jumper:** the Click's JP2 selects 1s/2s/3s/4s [WS]. On the EVM, cell count and default switching frequency come
  from the PROG resistor [REC]. Strap 2S so the POR VREG default is 2-cell, never 3S/4S.

## 6. Start-up latency
| Step | Time | Source |
|---|---|---|
| I2C registers accessible after valid input | ~20 ms | [WS] |
| Good-source (poor-source) qualification, then PG_STAT | ~30 ms typ, no retry | [WS] |
| Converter switching after D+/D- detection done | ~30 ms | [WS] |
| D+/D- (BC1.2) detection | UNVERIFIED | – |
| Board overhead (detect + RT1987 tD_ON + ramp) | 12–20 ms | [SPEC s5] |
| Charge soft-start to 90 % ICHG | UNVERIFIED | – |

- **D+/D- detection:** with D+/D- floating it is UNVERIFIED and could be tens to hundreds of ms. AUTO_INDET_EN can be
  cleared, but only over I2C after POR, so the first detection still runs.
- **Estimate:** ≥ ~90–120 ms from VCHG-IN applied to charge current. **Fails the ≤ 30 ms target; likely at or past the
  100 ms hard maximum.** Only the tail of a 0.3–0.6 s regen burst is captured.
- **Failed qualification retries late.** A failed qualification retries only after 7 or 10 minutes (the datasheet revisions
  disagree) unless the host toggles EN_HIZ or the input is cycled [WS]. A burst whose rising V-MOT sags under the 10–30 mA
  test current could leave the charger dead for the rest of the drive unless firmware toggles EN_HIZ on each burst.
- **FC mode:** the latency is irrelevant (a steady source).
- **Required measurement M1:** time from VCHG-IN applied to IBAT ≥ 90 %, on the bench.

## 7. Operation through D-BT-SQ (ideal diode between charger BAT and pack)
- **NVDC topology:** VBUS → buck-boost → SYS → integrated BATFET → BAT [REC]. **Leave SYS unloaded** (no load on SYS means no
  supplement-mode drain of VCHG).
- **Start-up from VCHG ≈ 0 V:**
  - The charger sees VBAT below its short or precharge thresholds and trickle- or precharges into C-D11 (10 µF) plus the
    module's BAT caps. At ~100 mA that is ~10 V/ms, so the output crosses VBT + 35 mV in a few ms.
  - D-BT-SQ then conducts and the charger sees the 7.4–8.4 V pack, above the 2S precharge threshold. It moves to fast
    charge.
  - A second RT1987 turn-on delay when D-BT-SQ comes out of UVLO may add up to 8 ms (UNVERIFIED, [SPEC s3]).
  - The thresholds are [REC]/UNVERIFIED. **Bench-verify that no "battery absent / short" fault latches.**
- **CV and termination act on VCHG, not the pack.**
  - After termination VCHG decays, because D-BT-SQ blocks the pack and the IC's battery-only quiescent current plus D-BT-SQ's
    draw discharge C-D11. The recharge threshold then restarts a cycle.
  - **Firmware must clear EN_CHG at termination** and use the board's V_batt ADC (pin 25) for state of charge.
- **Registers are lost on every input-power loss.** When VCHG-IN goes away, the IC is powered only from BAT = VCHG, which
  decays to POR. Re-write the config before every enable. Rapid back-to-back regen bursts may find it intact.
- **IBAT readback** is through the internal sense on the BATFET/charge path [REC], so it reads the true charge current. This
  fixes the incident's root cause: no sense in Bat-.
- **Disable OTG and backup mode** (EN_OTG = 0; EN_BACKUP on the BQ25798) [REC]. OTG would try to drive VCHG-IN from VCHG.
  D-BC-FC and D-BC-RG reverse-block, so only capacitor energy is involved, but these must stay disabled.
- **Option: bridge D-BT-SQ.** The IC then stays powered from the pack and keeps its config. The 4-switch topology blocks
  SYS → VBUS conduction through the body diodes (Q4's diode points SW2 → SYS). Firmware loses its hard battery-side
  disconnect and the battery-only quiescent current runs continuously. **This is an operator ruling.**

## 8. Control: fail-safe, I2C, STAT, watchdog
- **CE pin: active-LOW enable.** Charging needs EN_CHG = 1 and CE LOW [WS]; VIH 1.3 V, VIL 0.4 V [WS].
  - **Fail-safe wiring:** a pull-up from CE to 3V3 (J1.29/30 or J2.05/06; the 3V3 is battery-derived and always present),
    driven by Teensy pin 5. **Pin 5 HIGH = charge disabled, LOW = enabled.**
  - During Teensy reset (high-Z) the pull-up disables charging.
  - **Firmware:** `setup()` currently drives pin 5 LOW ([SPEC s1], FW 6720), which would ENABLE charging. Change it to drive
    HIGH first, and rename the CSV row (e.g. `CHG_CE_N`) before the firmware change.
  - CE stops charging only. The converter may still regulate SYS with no load. For zero input draw, set EN_HIZ.
- **POR default is not fail-safe.** EN_CHG defaults to 1 [REC], and the VREG/ICHG defaults come from PROG/JP2. Without the
  CE pull-up the IC charges autonomously at power-up, which fails [SPEC s3] "no charging until the host enables it". On the
  Click, check how CE is wired (UNVERIFIED).
- **Watchdog:**
  - A 160 s setting exists (136–160 s) [WS]. The default and the shorter options are UNVERIFIED ([REC] default 40 s;
    options include 0.5/1/2 s, which would meet ≤ 5 s).
  - Whether expiry resets registers is UNVERIFIED [WS].
  - **Hazard:** if expiry resets VINDPM/ICHG while a hung Teensy holds CE LOW, the bus can feed the charger. Mitigate with
    the hardware comparator (section 4) or the Teensy's own watchdog.
- **I2C:**
  - Address 0x6B ([REC], UNVERIFIED). It is the only device on the bus, so no conflict (Ag105 was 0x30).
  - 100 kHz only, per [SPEC s3].
  - **Remove the EVM/Click pull-ups:** the Click has a VCC-select for mikroBUS 3.3/5 V, UNVERIFIED. Keep the board's 10 kΩ
    pull-ups to Teensy 3V3.
  - The SDA/SCL abs max and whether an unpowered BQ25798 clamps the bus are UNVERIFIED. The IC is powered from VBUS/BAT
    (REGN), not from the pull-up rail. **Bench-check with the charger unpowered and the pull-ups live.**
- **STAT:** open-drain, LOW while charging [REC]. Add a pull-up to 3V3, or use `INPUT_PULLUP` on pin 6. Use the I2C status
  registers (CHG_STAT, VBUS_STAT, fault flags) as the primary readiness source. INT (open-drain) is optional; it would need a
  spare pin and a CSV update first.

## 9. Input capacitance and inrush (EVM / Click)
- **EVM VBUS/PMID capacitance and voltage rating: UNVERIFIED** (SLUUCB5E BOM unread). **Click: UNVERIFIED.**
- The limit from [SPEC s6]: (20 µF + C_chg) × 12 mA/µF + I_aux + start-up draw ≤ ~1.0 A, so **C_chg ≤ ~50 µF effective**
  (hard bound ~80 µF).
  - A typical 4-FET buck-boost layout (a few 10 µF ceramics on VBUS/PMID) fits.
  - **An EVM bulk electrolytic or TVS-plus-bulk at the input must be removed.**
- All input caps must be rated ≥ 35 V (V-MOT clamp ~21.4 V, plus an unmeasured overshoot).
- The IC does not switch during the RT1987 ramp: it waits for VBUS UVLO, poor-source qualification and REGN, ≥ 20–50 ms
  [WS]. This meets [SPEC s6].

## 10. Efficiency and thermal at 16 V in, 8 V out, 2.5 A
- **Not read.** The datasheet efficiency curves are UNVERIFIED.
- Engineering estimate (not a datasheet number): 94–96 % in buck mode, so ~0.9–1.3 W dissipated in a 4 × 4 mm QFN plus the
  inductor.
- The Click's thermal rating at 2.5 A is UNVERIFIED (triage weakness e). The neighbouring LM1084 is hot [SPEC s7].
- At regen (~2 W), light-load efficiency matters; PFM/out-of-audio settings exist [REC] but are UNVERIFIED.

## 11. Mechanical
- IC in a ~4 × 4 mm QFN ([REC]). IC, 1–2.2 µH inductor, caps and ILIM/PROG/TS resistors fit a carrier ≤ 32 × 35 mm plugged
  into the 22 Ag105 holes with a ≥ 2.54 mm standoff [SPEC s7]. This is the cleanest option.
- **Click:** mikroBUS form factor, dimensions UNVERIFIED. It is almost certainly wider than 25 mm in one axis, so it must
  hover on a carrier or go off-board on short twisted leads.
- **EVM:** much larger (dual-input EVM with ACFET/RBFET pairs, USB connectors). Off-board only.
- Pad mapping (Ag105 removed):

  | Ag105 pad | Connects to |
  |---|---|
  | VIN+ (VCHG-IN) | VBUS/VAC1. Leave VAC2/ACDRV2 unused; ACDRV1 FETs bypassed or not fitted. |
  | VIN- / VBAT- | GND (one node) |
  | VBAT+ (VCHG) | BAT |
  | SYS | unloaded |
  | MPPTD (pin 5) | CE (with pull-up) |
  | STAT (pin 6) | STAT (with pull-up) |
  | SDA/SCL | SDA/SCL |
  | THERM (J-NTC) | TS, through the IC's REGN-referenced TS divider (values UNVERIFIED). To run with no NTC fitted, a fixed resistor or TS_IGNORE is needed (UNVERIFIED). |

## 12. Price / stock / lead time
- **BQ25798EVM:** ~EUR 154, ~12 wk lead time [TRIAGE]. BQ25792EVM out of stock at TI [TRIAGE]. Not re-checked (vendor sites
  blocked).
- **MIKROE-5839:** listed at Digi-Key [WS]; price and stock UNVERIFIED.
- **IC (BQ25798RQMR):** for a custom carrier; price UNVERIFIED.

## 13. Showstoppers (conditional; none confirmed)
1. If the REG05 VINDPM maximum is below 19.0 V, the regen R3 threshold cannot be set.
2. If V-MOT overshoot exceeds ~24 V (operating) or 25.2 V (OVP falling), the charger is out of rating or drops out at the peak.
   The 30 V abs max leaves no margin for an unclamped event.
3. If the cold start to 90 % ICHG is measured above 100 ms, regen capture is tail-only (FC charging is unaffected).

## 14. Risks
- VINDPM is a regulation loop, not a hard off. It is overwritten at every plug-in and every POR (auto VBUS − 0.7/1.4 V). R3
  rests on CE/EN_HIZ discipline plus firmware until a hardware comparator is added.
- POR default is charging enabled. A missing CE pull-up means autonomous charging from the bus at power-up.
- A watchdog-expiry register reset (UNVERIFIED) with a hung Teensy could re-enable bus feed.
- Poor-source qualification failure on a sagging regen edge means no retry for 7–10 min unless EN_HIZ is toggled.
- Termination and recharge cycle through D-BT-SQ, so firmware must stop charging at termination.
- The Click/EVM pull-ups to 5 V or mikroBUS 3.3 V can back-power, and Teensy pins are not 5 V tolerant.
- Input caps of unknown rating (25 V class would fail regen).
- Thermal next to the LM1084, and the Click's 2.5 A rating unknown.
- **Every number here is from tertiary snippets or recollection; nothing is datasheet-verified.**

## 15. EVM / Click mods required (provisional)
1. Remove EVM/Click I2C pull-ups (or the VCC-select jumper); use the board's 10 kΩ pull-ups to 3V3.
2. CE: pull-up to 3V3 (10–47 kΩ), driven by Teensy pin 5 (HIGH = off). CSV row rename first; firmware drives HIGH early in
   `setup()`.
3. Strap 2S (Click JP2 / EVM PROG resistor).
4. ILIM resistor ≤ 1.0 A equivalent (hardware input bound for FC mode).
5. TS: wire to J-NTC or strap a fixed 10 k-equivalent per the datasheet TS table (UNVERIFIED).
6. Remove input bulk/TVS; all VBUS/PMID caps ≥ 35 V; total effective ≤ ~50 µF. Replace board C-D8/C-D10 with ≥ 35 V parts.
7. Bypass or omit ACFET/RBFET on the EVM's VAC1 path (the board's RT1987s do input switching); leave VAC2 unused; no load on SYS.
8. STAT pull-up to 3V3 (or firmware `INPUT_PULLUP`).
9. Optional: a hardware VCHG-IN comparator (19.0 / 13.5 V, selected by the FC_CHARGE net) to ILIM_HIZ or CE as the R3 hard off.

## 16. Firmware rework (summary)
- Replace `pollAg105` / `initAg105Charger` / `ag105IsReady` / the MPPT manager / `J` with a BQ25798 driver.
- Per power-up, with CE held HIGH:
  1. Write the watchdog (≤ 2 s or disabled with host kicks), EN_MPPT = 0, AUTO_INDET_EN = 0, OTG/backup off, VAC_OVP 26 V
     (regen) or 18 V (FC).
  2. Write VINDPM 19.0 V (regen) or 13.5 V (FC), VREG 8.400 V, ICHG, and IINDPM ≤ 1.0 A (FC).
  3. Read back.
  4. Lower CE.
- Toggle EN_HIZ on each regen burst to force poor-source re-qualification.
- Read IBAT/VBUS from the ADC registers into `I_charge`.
- Clear EN_CHG at termination.
- Keep `chargerHasPower()`, the G1–G3 guards and the trip latch; `AG105_VBATN_ISOLATED` becomes "charger return verified".

## Sources (tertiary, via WebSearch only)
- TI BQ25798 datasheet (URL, not fetched): https://www.ti.com/lit/ds/symlink/bq25798.pdf
- SLUUCB5E EVM guide (URL, not fetched): https://www.ti.com/lit/ug/sluucb5e/sluucb5e.pdf
- TI E2E threads: VINDPM auto-set, poor source retry, IINDPM (e2e.ti.com 1069290, 1361735, 1223984, 1442252)
- Charger 25 Click: https://www.mouser.com/datasheet/2/272/Charger_25_Click-3318480.pdf (not fetched);
  https://www.digikey.com.au/en/products/detail/mikroelektronika/MIKROE-5839/21671595 (search snippet only)
