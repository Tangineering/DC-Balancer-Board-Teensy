# Decision group 3: firmware-side rules from the reduced permit gate (2026-11-12)

Source: an interactive session with the operator (the dec2 firmware-rules session). These are design-document firmware
REQUIREMENTS only. No repo file was edited and nothing was committed. Abbreviations: DD = docs/charger_bq25798_wiring_design_2026-11-05.md
(branch charger-evm-round4), TR = cr_tap_review_2026-11-12.md.

## 1. Operator statements (verbatim, where the operator wrote text)

- Decision 5: "Move CHG_QUAL to pin 33 only. The RT1987's already solve boot-time power flow blocking"
- On R5: "Regarding R5, it will be built alongside the rest of the firmware updates for the new charger, as part of the handoff after the PCB design is done"
- Decisions 1, 2, 3a, 3b, 4a, 7 and 8: the operator selected the recommended option. Decision 4b: "Accept both". Decision 6: "FC-window J, R5 required".

## 2. Decisions and the intent of the requirement text

| # | Decision | Intent of the requirement text |
|---|---|---|
| 1 | T_QUAL_MAX = 0.46 s, latching | FR-04 / I-5: an independent backstop in the FR-45 1 kHz timer domain, separate from the step machine. If QUAL has been HIGH for more than T_QUAL_MAX (0.46 s, the old tw_QQ maximum) since its rising edge, QUAL, P5 and REGEN go LOW on the detecting tick and `CHG_QUAL_OVERRUN` latches; regen arming is refused until Idle. J.1 gains an explicit R3 exception: during qualification the bus feeds the BQ25798 IQ_VBUS, about 3-5 mA typical (no datasheet maximum, SLUSDV2C section 6.5), plus the ADC, about 50-90 mW, for at most T_QUAL_MAX per Run entry. Under an MCU hang that exposure is bounded only by R5. |
| 2 | QUAL LOW before P5 HIGH, with a 1-tick gap | F.5 T1 and T9, I-5: a normative step. Drive QUAL LOW, wait at least one 1 kHz tick, then drive P5 HIGH. A host test checks the order on every P5 path. |
| 3a | Pin-34 ISR on both edges | FR-07: the pin-34 ISR handles both edges. The rising edge posts the raise (T3). The falling edge posts T4 (restore) at the head of the queue. The worker re-reads H1 rb when it services a request, so the level present at service time decides. Safety does not depend on T-B-07 (whether the ILIM pin is re-read). F.5 T4 trigger (a) becomes the edge event. |
| 3b | Both guards | F.5 T3: the raise requires REGEN read back HIGH. FR-49: outside State 98, refuse FCC HIGH while REGEN is LOW. |
| 4a | CHG_IIN cross-checked against IBUS | FR-11 and T10 proof (d): whenever the I2C IBUS ADC reads above 0.2 A, CHG_IIN (pin 22) must agree with it within the T-B-14 tolerance. Proof (d) (FCC and REGEN EN read back LOW for the turn-off time + 2 ms, and CHG_IIN < 0.1 A for 1 ms) is accepted only if pin 22 has shown that agreement earlier in the same charger power cycle (a "lead-alive" proof). Otherwise T10 falls back to proof (b), the V_chg decay. (2026-11-14, REVIEW FW-2: CHG_IIN is ignored and every CHG_IIN-based check is suspended unless V_chg > 10.2 V and CHG_EFUSE_FLT is HIGH, DD FR-01; with the U101 pin leakage the T10 proof (b) level is 8.0 V, DD F.5, `hardware/charger_evm_r8/sim/efuse_decay/RESULTS.md` section 4.1.) A sustained disagreement latches `CHG_IIN_LEAD` and refuses FC windows. There is no Teensy-end pull on pin 22; FR-01 `INPUT_DISABLE` stands. |
| 4b | Accept both | No new firmware check. J.1 accepted costs: (i) an open T13 makes pin 34 read LOW ("no brake") through `INPUT_PULLDOWN`, so T3 never fires and harvest above the FC image is lost; the hardware H1 still acts on the CR; this is the safe direction and is undetected. (ii) An open T16 makes pin 35 read "no fault" through `INPUT_PULLUP` (the r4 ruling); a latched eFuse is then seen as VBUS_PRESENT_STAT = 0 with FLT HIGH and V_chg > 10.2 V for > T_REGN_MAX, which raises the "FLT tap suspect" flag and the "charger unbiased" state (DD F.3 T16 row, FR-23; DD FR-51 classifies it as a latched U101). V_chg (pin 38) sits upstream of U101 and does not fall at a U101 trip (DD FR-30) (2026-11-15, REVIEW R2-FW-11) (**Superseded 2026-11-15, REVIEW R2-FW-11:** "an eFuse trip is then seen only as a V_chg collapse.") |
| 5 | CHG_QUAL moves from pin 10 to pin 33 | CSV/D.3 row, FR-01 and the TR section 4 prepared row now name pin 33 for `CHG_QUAL` (an OUTPUT, driven LOW early in `setup()`). FR-49 and T-D-01 are NOT extended for the reset levels of pins 5 and 33. Rationale (operator): the RT1987 EN 10 kOhm pull-downs keep the charger unpowered through any reset or boot, so the P5 and QUAL levels in that window cannot cause a power flow. This also disposes of check_3's QUAL slow-edge point (the T-D-01 exception list need not add QUAL). Pin 10 (the SPI CS0 default) becomes free, so the CS0 question is moot. |
| 6 | State 98 `J` redefined on the FC-window topology, R5 required | FR-02 / State 98: the fw v37 `J` (Ag105, charger fed from the bus through MOT_PWR + REGEN) is retired. The new `J` has two stages. Stage 1 is register commissioning only: QUAL qualification, write and read back the image, EN_CHG = 0. Stage 2 is a supervised FC-window charge through `assertFcChargeEnable()` (BT_BUS LOW, FC_BUS HIGH, REGEN HIGH), with the fw v37 rev 2 G1-G3 trip guards and the reboot-only trip latch re-keyed to the BQ25798 signals. Stage 2 keeps every FC-window precondition, including the R5 watchdog fitted and T-W-01 passed. R5 is built in the same firmware round as the charger (operator), so this does not block bench commissioning beyond that round. |
| 7 | Freed pins: `INPUT_PULLDOWN` plus a boot check | FR-01: after the pin-33 move the freed pins are 10, 16, 17, 21 and 23. Each is set to `INPUT_PULLDOWN` early in `setup()`. At boot each pin is read, and any HIGH raises a non-blocking `UNEXPECTED_LEAD` flag reported on Serial, which catches a tap lead mis-plugged onto a free header pin. Pin 21 keeps this mode until group 2 decides on EWM_OUT_B. Pins 2, 7 and 8 keep their existing FR-01 ruling. |
| 8 | FR-08(b) replaced by an I2C latch trip | FR-08(b) new text: while P5 has been LOW for >= 20 ms and `regnExpected` is true, REG1C CHG_STAT in {1h, 2h, 3h, 4h, 6h} (the charging phases; 0h Not Charging and 7h Charge Termination Done are excluded, SLUSDV2C Table 7-37 p.87) OR IBAT > 50 mA in the charge direction, on 2 consecutive fresh reads (a fresh read follows at least one full ADC scan period of the current REG2F/REG30 mask since the previous read, DD G.1 r9-25), (**Superseded 2026-11-14, REVIEW FW-6 and FW-1:** "REG1C CHG_STAT != not-charging OR IBAT > 50 mA in the charge direction, on 2 consecutive fresh reads,") raises a latching trip: P5, QUAL, REGEN and FCC LOW on the detecting tick (I-4(b)), and T10 inside a window. FR-44 (pin 6 vs REG1C vs P5 over 2 s) stays as the slower hardware cross-check. The check sees a stuck-LOW /CE (SAFETY-2) only while the converter is released (FC window or brake). |

## 3. Open TODOs

- Pin 33 replaces pin 10 for `CHG_QUAL`: the IO CSV row (operator edits), DD D.3, FR-01, B.6/W5 notes, and the TR section 4 prepared row must change. Pin 33 is no longer on the TR freed list, and pin 10 is added to it.
- F.5 T4 currently says "No T4 within 50 ms of a T3". Decide whether an edge-posted T4 (3a) is exempt from that hold-off, because an abrupt VESC stop within 50 ms of the raise is exactly the case 3a targets. Recommended: exempt, with the service-time H1 rb re-read as the debounce.
- T_QUAL_MAX 0.46 s against T-B-20's measured REGN-marker and PG_STAT timing: TODO(calibrate: T-B-20).
- IQ_VBUS maximum: TODO(verify: SLUSDV2C section 6.5, measure on the bench).
- 4a: the agreement tolerance comes from T-B-14 (the measured IMON gain and offset); the 0.2 A agreement threshold is TODO(calibrate: T-B-14).
- 8: the IBAT 50 mA threshold and the 20 ms settle time are TODO(calibrate) against the REG1C update latency and the /CE response (SLUSDV2C).
- 6: re-key the G1-G3 thresholds of fw v37 rev 2 (G1 bus-side current, G2 unaccounted power, G3 GENSTAT) to BQ25798 equivalents: TODO(design, firmware round).
- 5: not adopted, recorded for completeness: PJRC SPI.cpp was not checked, and the i.MX RT1062 keeper against 47 kOhm was not verified. Both are moot under the operator's ruling.
- R5 timing (operator): built in the post-PCB firmware handoff together with the charger firmware. Group 2 (dec2-watchdog) should use this.
- 2026-11-14 (`hardware/charger_evm_r8/REVIEW_2026-11-14.md` and the five simulations under `hardware/charger_evm_r8/sim/`;
  DD row r9-25): the following firmware criteria changed or were added. DD G.1 and G.2 state each one in full.
  - FR-12(a2): fail if dV_rgn > 0.2 x dV_bus, evaluated only when dV_bus >= 2 V; a shorter window is inconclusive and
    repeats at the next bring-up, never a pass; k may return to 0.5 after the U-SNT repair (`sim/efuse_decay/RESULTS.md`
    section 5(c); REVIEW VR-3). The V_fc reading clips at 12.34 V (`SCALE_V_FC`, `teensy_controller.ino`:2024), so with the
    H-20 at 13 V the P0 gate passes at V_bus 10.84 V, not 11.5 V; the firmware round reviews every rule that reads V_fc
    above 12.34 V.
  - FR-12(b1): passes if V_chg < 12.0 V at 0.5 s, or if the mean slope over 0.2-0.4 s is -1.0 V/s or steeper; otherwise it
    fails (sim 5 section 5(b); REVIEW PWR-1). A plain 1.5 s dwell is admissible only after T-C-04 measures the EVM Idle
    VBUS draw (>= 0.351 mA at 51.4 uF, about 6.8 uA per uF), the effective C_evm, the U101 IN-side current and the RT1987
    sourced leakage (below a few uA). DD FR-12 keeps the superseded r8 dwell text.
  - FR-12(b2): with a near-zero EVM draw the wait to 3 V can reach 12.96 s; the probe is then skipped and
    `vchg_slow_decay` logged, which is not a false fault (sim 5 section 4.2).
  - G.1 ADC masks: REG2F = 0x3E and REG30 = 0xF0 in the static image (IBUS and IBAT only, a 12 ms scan); a fresh read
    follows one full scan of the current mask; the FR-48(a) one-shot first writes REG2F:30 = 0xEE 0xF0 (VBAT only) and
    reads it back (SLUSDV2C Tables 7-56 and 7-57, section 7.3.10; REVIEW FW-1). The scan time is TODO(calibrate: T-B-14b,
    T-D-15).
  - FR-08(b) trigger set: CHG_STAT in {1h, 2h, 3h, 4h, 6h} or IBAT > 50 mA (decision 8 above; REVIEW FW-6); the FR-22 host test
    covers CHG_STAT after a termination followed by P5 LOW. No section I bench step reads it yet; a T-B-15 step
    is proposed to the DD section I owner (2026-11-15, REVIEW R2-FW-12) (**Superseded 2026-11-15, REVIEW R2-FW-12:**
    "a T-B test reads CHG_STAT after a termination followed by P5 LOW.")
  - Wherever REGEN is closed, a V-MOT comparison uses V_chg (pin 38), not V_rgn (pin 39), until U-SNT is repaired
    (REVIEW VR-1, VR-3).
  - The G.1 byte-order self-check accepts REG01:02 = 0x03 0x48 or 0x03 0x40; the action on any other value is
    TODO(decide: firmware round) (REVIEW FW-7).
  - FR-23 EX2: an ACK with VBUS_PRESENT_STAT = 1 and IBUS below the T-B-14 noise floor is non-latching, because FLAG also
    asserts on reverse current (REVIEW FW-5); whether the comparator acts without Q1 is TODO(verify: Toshiba).
  - FR-45: the 1 kHz timer domain never calls `analogRead()` (REVIEW FW-11).
  - The project CLAUDE.md still requires REGEN_ENABLE LOW before FC_CHARGE_ENABLE, against FR-06 and FR-49; DD D.5 (r9-25)
    states the change that the operator must approve before the firmware round (REVIEW FW-0).
- 2026-11-15 (second holistic review, findings R2-FW-*; DD row r9-26): the following firmware requirements changed or were
  added. DD G.1 and G.2 state each one in full.
  - FR-50: the single-sample OV_CHG State-99 latch at `LIMIT_V_CHG_MAX` 24.0 V (`teensy_controller.ino`:2285, :7436) is
    re-derived for the REGEN-held-HIGH topology. Its value, response and filter wait for the DD J.2 item 74 operator
    ruling; the code stays unchanged meanwhile (REVIEW R2-FW-0).
  - FR-51: a latched U101 in Run is detected through the FR-23 EX2 episode inside the V_chg window 10.76-19.50 V and
    flagged (`CHG_EFUSE_LATCHED`); recovery inside a Run is an operator decision (REVIEW R2-FW-1).
  - G.1: REG2E = 0xA0 in Run and 0xE0 for the one-shot (ADC_SAMPLE 10b, 6 ms, SLUSDV2C Table 7-55); no Run poll of
    REG35-36 or REG41; the T-B-16 mask REG2F = 0x3C (18 ms scan); REG17 stays at POR 0x7A; REG47 is the DPDM driver
    (REVIEW R2-FW-2, R2-FW-3, R2-FW-8).
  - FR-02 / FR-20: the Ag105 fault bits 0x0800 and 0x1000 are retired; the codes 0x0C and 0x0D stay allocated and
    unused; an I2C-dead rule (3 NACK frames, provisional) is defined; offset 51 and `chg_vbus_mv` (= V_chg) are defined
    (REVIEW R2-FW-5).
  - FR-01: every analog input pin is `INPUT_DISABLE` (REVIEW R2-FW-7). FR-28: the watchdog feed runs in a loop-context
    block, never in the timer (REVIEW R2-FW-9).
  - F.5 T10: the proof (b) decay to 8.0 V is 0.083-4.39 s on the sim 5 basis, not 55-181 ms (REVIEW R2-DOC-5).

