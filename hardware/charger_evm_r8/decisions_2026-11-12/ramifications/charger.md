## BQ25798 open questions under the reduced permit gate (charger item)

Sources: SLUSDV2C, read from `references/TI_BQ25798_design_files/BQ25798_SLUSDV2C.pdf` (it is not in `references/Datasheets/`); the design doc `docs/charger_bq25798_wiring_design_2026-11-05.md` (cited below as DD:line); `decisions_2026-11-12/cr_tap_review_2026-11-12.md` (TR). Page numbers are the datasheet's printed page numbers.

### 1. Qualification state: ILIM_HIZ released, /CE HIGH, no hardware time limit

**The converter runs, but it does not charge.**
- The converter starts switching again once ILIM_HIZ rises above 1 V, and REGN stays on (Â§7.3.4.3, p.27).
- Charging needs EN_CHG = 1 **and** /CE LOW (pin table p.5; Â§7.3.9.1, p.41).
- The reduced gate makes the QUAL term `QUAL AND FCC_OFF AND NOT P5`, and CE_DRV = P5 (TR Â§2). So while QUAL is releasing, /CE is HIGH by construction.
- EN_CHG = 0 is the second barrier: it is written and read back before QUAL (FR-04, DD:2969; F.2 row DD:2330).

**Input current is IQ_VBUS: 3 mA typical with OOA disabled, 5 mA with OOA enabled.**
- The datasheet condition (p.8, Â§6.5) is VBUS 15 V, VBAT 8 V, charge disabled, converter switching, ISYS 0. This matches the qualification state, because EM7 removes or caps the EVM SYSTEM terminal (DD:1998).
- **No maximum is given.** TODO(verify: SLUSDV2C Â§6.5 has a typical value only; measure in T-B-xx).
- Add the ADC at 0.2-0.52 mA (H.15, cited in G.1 DD:2909) until a BQ watchdog expiry clears ADC_EN.
- The supply path is VBUS â†’ MOT_PWR â†’ V-MOT â†’ REGEN â†’ VCHG-IN (switch vector 1 1 1 1 1 1 0 1, DD:2330). At ~16 V that is about 50-90 mW taken from the bus.

**Risk to the bus and the FC:**
- **Magnitude:** negligible. A few mA is small against Run bus loads of 0.3 A and up.
- **R3:** this is the bus feeding the charger in Run. F.2 accepted it only as "input = IQ_VBUS 3-5 mA" bounded by tw_QQ 0.20-0.46 s (DD:2330). With the U111 one-shot gone, the exposure has no time limit if firmware or a hang leaves pin 10 HIGH (TR Â§6 cost 6).
- **Recommendation:** add a firmware T_QUAL_MAX to FR-04, with a latch on overrun. Record the unbounded IQ draw as an explicit R3 exception.
- **Single barrier after a BQ watchdog expiry.** On a hang with QUAL HIGH and P5 LOW, the BQ watchdog can reset EN_CHG to 1 (section 2 below). /CE HIGH would then be the only barrier left. It is driven through the 47 kOhm pull-down on pin 5 and EIB U201 (TR Â§4, row 5). Charging still cannot start, because /CE stays HIGH, but the design no longer has two barriers there.
- **Other states unaffected:** a brake during qualification (H1 AND UVB) adds nothing, because the converter is already released. In an FC window, FCC_OFF = 0 blocks the QUAL term.

### 2. The BQ25798 I2C watchdog on an MCU hang

**Timing:**
- Firmware sets WATCHDOG = 1h (0.5 s) in REG10 (G.1, DD:2901).
- WATCHDOG is reset only by REG_RST (Table 7-26, p.72), so the 0.5 s setting survives an expiry.
- The EC specifies tWDT only for the 160 s setting (136-160 s, p.17). **The tolerance of the 0.5 s setting is unspecified.** TODO(verify: T-B-08 measures it; DD:3221 expects 0.4-1.0 s).

**Behaviour on expiry (Â§7.4.1, p.56):**
- The device returns to default mode and the WD-reset fields go back to their defaults. WD_STAT and WD_FLAG are set and INT asserts.
- In default mode it **keeps charging** under the default safety timers.
- Only an I2C write leaves default mode, and a hung MCU makes none.

| Field | Reset by WD? | After expiry | Source |
|---|---|---|---|
| ICHG REG03 | yes | 1 A POR default (FC image 1.60 A, regen 3.10 A) | Table 7-16 p.61; Â§7.3.2 p.25 |
| VREG REG01 | **conflict** | the table says REG_RST only; the Â§7.3.2 text says WD returns it to 8.4 V for 2S. If the text holds, the 8.32 V interim (FR-40) rises to 8.40 V | Table 7-15 p.60 vs p.25 |
| VSYSMIN REG00 | same conflict | 3.5 V or 7 V; harmless with the pack at â‰¥ 7.4 V | Table 7-14 p.59 vs p.25 |
| VINDPM REG05 | no | kept (14.5 V FC, 19.0 V regen); after a VBUS unplug/replug it is re-measured as VBUS0 - 1.4 V | Table 7-17 p.62 |
| IINDPM REG06 | no (REG_RST and D+/D- only) | governor value kept | Table 7-18 p.63 |
| EN_EXTILIM REG14 | no (REG_RST only) | ILIM-pin clamp stays in force | DD:2915 (Table 7-30) |
| EN_CHG REG0F | **conflict** | Table 7-25: WD resets it to 1. REG09 STOP_WD_CHG = 1 means WD sets EN_CHG = 0 (p.65). STOP_WD_CHG is drawn **R-0h** in Fig 7-32 but listed RW in Table 7-20, so its writability is open | p.70; p.65 |
| EN_HIZ | no | kept | p.70 |
| EN_TERM, ITERM, IPRECHG, timers REG0E, ADC_EN, REG12/13/18 | yes | defaults: termination on, 200 mA ITERM, 12 h fast-charge timer, ADC off | pp.64-69; G.1 DD:2899-2912 |
| AUTO_INDET_EN REG11 | yes, to 1 | D+/D- detection re-arms on the next VBUS plug-in. A purge collapse and recovery of VCHG-IN could re-run it, and the ILIM pin still clamps the result. TODO(verify: T-B-07 asks whether ILIM_HIZ is re-read at a replug; EVM D+/D- termination) | p.73 |

**Can charging continue or change while /CE stays LOW (P5 frozen HIGH)?**
- **If STOP_WD_CHG is effective:** EN_CHG goes to 0 after ~0.5 s and charging stops. The converter keeps running to supply SYS (p.56), so the input draw falls to IQ_VBUS. Nothing on a hung MCU can set EN_CHG back to 1.
- **If STOP_WD_CHG is not effective (the R-0h reading):** EN_CHG returns to 1 and charging **continues indefinitely**.
  - The charge current is min(ICHG 1 A, the input limit). The input limit is min(IINDPM governor â‰¤ 0.90 A, ILIM pin clamp 0.65-0.95 A in FC, 1.33-1.76 A regen) (H.4).
  - VREG is 8.32 V or 8.40 V. The charger terminates at 200 mA and auto-recharges at VREG - 200 mV after 1024 ms (Table 7-21 p.66).
- **Conclusion:** the BQ watchdog is a parameter change, not an inhibit. It can only lower ICHG. It may raise VREG by 80 mV, which is the unsafe direction. DD T-B-08 already says "Do not cite the charger WD" until it passes. That verdict stands, and it matters more now that the heartbeat is gone.

### 3. R5 MCU watchdog as a hard FC-window precondition

**Assessment: endorse.** It is already normative and needs no new mechanism:
- R5 (DD:60);
- FR-05 "R5 watchdog fitted with T-W-01 passed (a build flag set only after the test)" (DD:2970);
- G.3 r4 (DD:3027);
- critical path item 10 (DD:161).

With U113, ARM_OK and U111 removed, the R5 reset is the **only** hang defence (TR Â§6 cost 1).

**What an R5 reset achieves (within t_WDT + 1 ms, 50 ms target):**
- Every RT1987 EN falls through its 10 kOhm pull-down (DD:3029).
- Pin 5 (P5) and pin 10 (QUAL) fall through their 47 kOhm pull-downs (TR Â§4). /CE then goes HIGH and the QUAL term goes to 0.
- With FC_CHARGE and REGEN LOW, VCHG-IN is unpowered.

**G.3 text that is now stale and must be edited before the precondition is meaningful:**
1. "the 50 ms RTWDOG timeout is loaded only while the charger heartbeat runs" (DD:3044). The heartbeat no longer exists. Re-key the short-timeout window to "P5 OR QUAL OR FC_CHARGE OR REGEN HIGH", or to the FR-04 T1-to-T6/T7 span. Re-key FR-43 `flashWriteAllowed`/`sdOpAllowed` "heartbeat stopped" (DD:3047-3051) and FR-27 tw_HB,min (DD:2998) to t_WDT likewise.
2. "The hardware heartbeat (B.1) already inhibits charging on a hang" (DD:3023) is now false.
3. "Pin 21 now carries CHG_HB, so the EWM_OUT_B option is given up" (DD:3021) no longer applies. Pin 21 is free (TR Â§3), so the EWM_OUT_B route is available again. TODO(verify: IMXRT1060RM AD_B1_11 ALT1).
4. FR-28 survives only as the **watchdog feed token**, with the stage mask and the FR-45 tick count. The CHG_HB toggle is deleted.
5. T-W-01 (DD:3317) gains these cases: hang with QUAL HIGH; hang in regen-armed Run during a brake. In every case, record IBAT and /CE at the EVM after the reset, because the far-end senses U203/U204 are gone.

**What a hang can still do with the watchdog fitted (bounded by t_WDT â‰ˆ 50 ms):**
- Keep charging for â‰¤ 51 ms with all limits frozen. A pack-OV contribution in that time is negligible.
- In an FC window, the hang leaves BT_BUS LOW. A hang that starts within ~t_WDT + T_LEAD of a purge onset is the G.3 residual, ~1.5 % of window hangs (J.2, T-D-14 DD:3273).
- Leave the VESC on its last current command until the reset. TODO(verify: VESC UART timeout setting).
- **Not covered:** a firmware live-lock that still completes the 1 kHz tick, and any state inside a stretched FR-43 bracket. The re-key in item 1 must keep those brackets out of every charger-powered state.

**Recommendation beyond FC windows (operator ruling needed):**
- Regen charging is no longer hang-protected either. A hung MCU with P5 HIGH charges on every brake.
- R3 still holds in that case, because hardware releases only on H1 AND UVB.
- However, pack OV then rests only on the BQ25798's own VREG regulation and on VBAT_OVP at 103-105 % of VREG: 8.57-8.82 V, above `LIMIT_V_BATT_MAX` 8.5 V (p.12; FR-40 DD:3005).
- **Option:** gate every P5 rise, not only FC windows, on the watchdog build flag.
- **Cost:** no regen harvest until T-W-01 passes.
- The operator stated "not concerned about an MCU hang" (TR Â§1), so this is offered, not assumed.

### 4. FR-46 / FR-47 pack-OV layers under a hang

- **FR-46 read-back** (DD:3012) is firmware and is dead under a hang. The BQ watchdog then changes ICHG, and possibly VREG and VSYSMIN, with no read-back. After the R5 reset, FR-03 "POR/WD re-image starting with REG0F = 0x02" (DD:2968) must also run when the charger stayed alive on BAT and only went into WD default mode.
  - TODO(verify: DD, whether BAT stays connected across an MCU reset so that the charger does not POR).
  - Firmware should read WD_STAT/WD_FLAG at reconnect and treat the image as lost.
- **FR-47(a)** `CHG_PACK_OV` and OV_BATT (DD:3013) are firmware only (D-38) and are dead under a hang. With R5 fitted, they are replaced for the hang interval by the reset: P5 falls through 47 kOhm, so /CE goes HIGH. Without R5, the only layers left are BQ VREG regulation and VBAT_OVP (103-105 % of VREG). VBAT_OVP follows VREG and is not independent (FR-40), so a VREG corruption that is in place before the hang is uncovered.
- **FR-47(b)** loses its input: the pin 7 /CE far-end sense goes with T20 (TR Â§5). It did nothing under a hang in any case.
- **Net:** under a hang, the pack-OV defence = R5 reset time + BQ25798 self-regulation. This is a further reason to require R5 for any unattended charging, regen included.

### Open verification items
- TODO(verify: SLUSDV2C): IQ_VBUS maximum; the 0.5 s tWDT tolerance; STOP_WD_CHG writability; the VREG/VSYSMIN WD-reset conflict. All of these go to T-B-08 on the bench.
- TODO(verify: T-B-07): whether the ILIM pin is re-read after a D+/D- re-detection in default mode.
- TODO(verify: IMXRT1060RM / T-W-01): GPIO levels during and after a WDOG1/RTWDOG reset.

