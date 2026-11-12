# Decision group 2: hang defence and the watchdog (operator rulings 2026-11-12)

Session: dec2-hang-defence (side session). Sources read: `hardware/charger_evm_r8/DESIGN_STATE_2026-11-12.md` §3.2/§4,
`decisions_2026-11-12/ramifications/charger.md`, `check_1-3.json`, design doc (DD) G.3, FR-05/27/28/40/42/43/46/47/49,
T-W-01, T-B-08; SLUSDV2C read directly (`references/TI_BQ25798_design_files/BQ25798_SLUSDV2C.pdf`). No repo file edited.
Operator's words = the option labels they selected.

## D2-1. Scope of the R5 precondition
- Operator: "All charger arming (Recommended)".
- Requirement intent: QUAL (pin 10), every P5 (pin 5) rise and every FC window require the R5 build flag. Run itself
  (driving with the charger disarmed: REGEN LOW, no QUAL) does not. T-W-01 splits:
  - T-W-01a: bench forced-hang cases without purge (hang with QUAL HIGH; hang in regen-armed Run during a brake;
    hang with P5 HIGH; legitimate-stall cases). Gates qualification and regen charging.
  - T-W-01 (full): adds the T-D-14 purge-emulator cases. Gates FC windows (unchanged r4 rule).
  - In every case, record IBAT and /CE at the EVM after reset (U203/U204 far-end senses are gone).
- Edits implied: R5 row (DD:60), FR-05 (the flag moves from "FC windows" to "any charger arming"), FR-04 (QUAL refused
  without the flag), G.3 r4 paragraph, critical-path item 10 (DD:161), F.4 rule (i).
- Scheduling consequence (stated to and accepted by the operator): no charging of any kind (regen, qualification, FC) on
  the vehicle until the R5 firmware (RTWDOG + WDOG1 config, FR-28 feed token, ERR_MCU_WDT, FR-43 brackets) and T-W-01a
  exist; FC charging additionally waits for full T-W-01 with the T-D-14 rig. State 98 `J` is already unusable under the
  reduced gate (DESIGN_STATE §3.3), so there is no bench charging path before R5 either.

## D2-2. WDOG1_B into the gate
- Operator: "Firmware-only R5 (Recommended)".
- Requirement intent: no 11th tap; tap count stays 10. Pin 20 stays the WDOG1_B route (FR-29, AD_B1_10 ALT1), no CR
  consumer. Reasons given: WDOG1_B asserts only when firmware has configured WDOG1 (no removal of the R5 firmware
  dependency); WDOG1 is the 1.0 s second stage in G.3; after reset the pad returns to its reset mux state, so the gate
  would see a pulse unless a latch part is re-added; the reset already drops P5, QUAL and every EN through pull-downs.
- Edit implied: G.3 sentence "The hardware heartbeat (B.1) already inhibits charging on a hang" (DD:3023) is false and
  must be replaced by "R5 is the only hang defence; no hardware hang inhibit exists (operator ruling 2026-11-12)".

## D2-3. Re-keying the short RTWDOG window, FR-43, FR-27
- Operator: "State 2 OR charger pins (Recommended)".
- Requirement intent: `rtwdogShort` = mainState 2 OR any of P5, QUAL, FC_CHARGE, REGEN HIGH (commanded or read back).
  The State-2 term covers the fw v28 selector's FC-only arms (BT_BUS LOW, FC_REG HIGH, no charger), which carry the same
  purge exposure G.3 was sized for; the pin terms cover State 98 sessions.
  - G.3 r5 item (1) "loaded only while the charger heartbeat runs" (DD:3044) -> loaded while `rtwdogShort`.
  - FR-43: replace "NOT `chgHbRunning`" with "NOT `rtwdogShort`" in `flashWriteAllowed` and `sdOpAllowed`
    (`rtwdogMode == WDT_LONG` stays). Flash stays Idle-only; SD close/sync Idle/98 with `rtwdogShort` false, or State 99
    phase 3 (State 99 phase 3: confirm `rtwdogShort` is false there - all paths LOW - TODO in the edit).
  - FR-27: keep the 5 ms single-iteration budget; re-state the bound as max legitimate stall + margin < t_WDT <
    T-E-01 minimum purge - 21 ms (no tw_HB,min reference). T-C-09 / T-W-02 measure against t_WDT.
  - FR-28: survives only as the watchdog feed token (stage mask + FR-45 tick count); CHG_HB toggle deleted. FR-42's
    "a deliberately broken backstop stops the heartbeat and the watchdog feed" -> "stops the watchdog feed".
  - T-W-01: "RTWDOG mode following the heartbeat (50 ms only between T1 step 0 and T6/T7)" -> following `rtwdogShort`.

## D2-4. BQ25798 watchdog (T-B-08)
- Operator: "0.5 s + STOP_WD_CHG, fallback (Recommended)".
- Verified in SLUSDV2C rev C (June 2026), three conflicts:
  - STOP_WD_CHG: Fig 7-32 R-0h vs Table 7-20 RW (p.65); revision history "Corrected REG0x09 header to include STOP_WD_CHG".
  - EN_CHG on expiry: Table 7-20 "0h = WD timer expiration keeps existing EN_CHG setting" vs Table 7-25 EN_CHG
    "Reset by: WATCHDOG", POR 1.
  - VREG on expiry: Table 7-15 "Reset by: REG_RST" only vs §7.3.2 p.25 text (WD expiry returns VREG to 8.4 V for 2S).
  - VBAT_OVP 103/104/105 % of VREG (p.12 EC): 8.57/8.65/8.74 V at 8.32 V; 8.65/8.74/8.82 V at 8.40 V. EN_TERM = 0 would
    lower VBAT_OVP to VREG (§7.3.9.3), but EN_TERM is WD-reset to 1 - not usable as a hang backstop.
- Requirement intent: G.1 keeps WATCHDOG = 0.5 s; FR-03 image adds STOP_WD_CHG = 1 with masked read-back. T-B-08 settles:
  STOP_WD_CHG write/read-back; EN_CHG after expiry for STOP_WD_CHG 0 and 1, starting from EN_CHG 0 (qualification) and 1;
  VREG, VSYSMIN, ICHG after expiry; the 0.5 s tWDT tolerance (DD expects 0.4-1.0 s). Fallback rule: if expiry neither
  clears EN_CHG nor keeps VREG at 8.32 V, set WATCHDOG = 00 so a hang freezes the 8.32 V image. Either way the charger
  WD is never cited as a barrier (T-B-08 "if fail" column stays). FR-03: after any MCU reset, read WD_STAT/WD_FLAG at
  reconnect and treat the image as lost (re-image starting REG0F = 0x02).

## D2-4b. Hang-time charging with BQ-only pack OV
- Operator: "Accept without condition".
- Requirement intent: record as a J.2 residual - with R5 gating all charger arming, a hang charges for at most
  t_WDT + 1 ms (~51 ms) with pack OV left to BQ25798 VREG regulation and VBAT_OVP (above LIMIT_V_BATT_MAX 8.5 V).
  The operator declined the proposed condition (FR-49 extended to pins 5 and 10; T-W-01 scoping P5/QUAL at reset).
- Residual stated honestly: the bound assumes P5 and QUAL fall at reset. The i.MX RT1062 reset pad state on pins 5 and
  10 is a keeper (PKE = 1 / PUE = 0, FR-01) opposed only by 47 kOhm pull-downs; keeper strength TODO(verify:
  IMXRT1060RM). If the keeper held P5 HIGH, /CE would stay LOW through and after the reset and the hang bound would not
  apply. Not added as a requirement per the ruling; listed here as an open TODO for the r9 audit to note.

## D2-5. Pin 21
- Operator: "Leave free (Recommended)".
- Requirement intent: pin 21 unassigned; defined firmware mode under the freed-pin rule (decision group 3). G.3 sentence
  "Pin 21 now carries CHG_HB, so the EWM_OUT_B option ... is given up" (DD:3021) -> "Pin 21 is free; EWM_OUT_B
  (AD_B1_11 ALT1, TODO(verify: IMXRT1060RM)) is not used." IO CSV row for pin 21 to be updated by the owner session.

## Open TODOs
1. R5 firmware round + T-W-01a / T-W-01 test writing (now on the critical path for ALL charging).
2. T-B-08 bench run (settles D2-4; fallback to WATCHDOG = 00).
3. Pins 5/10 reset keeper vs 47k pull-down (TODO(verify: IMXRT1060RM)) - unconditioned residual per D2-4b.
4. 0.5 s tWDT tolerance (SLUSDV2C specifies tWDT only at 160 s).
5. State 99 phase 3 vs `rtwdogShort` (confirm all four pins LOW there so `sdOpAllowed` still admits the close).
6. Design-doc edit list above (R5 row, FR-04/05/27/28/42/43, G.1, G.3, T-W-01, T-B-08, J.2, critical path item 10).
