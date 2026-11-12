## Gate re-derivation: reduced permit (2026-11-12)

**Outcome.** The reduced gate holds R3' in every operating mode I enumerated, provided firmware keeps I-9 and the R5 watchdog is fitted. It also adds no new converter back-feed path. One real single-fault gap needs a fix: **SAFETY-1**, a stuck-HIGH FC_ON comparator U120. The fix uses spare gate sections and costs no package. The gate needs **5 LVC packages, down from 11**.

Abbreviations: D = `docs/charger_bq25798_wiring_design_2026-11-05.md`, TR = `decisions_2026-11-12/cr_tap_review_2026-11-12.md`.

Equations used (TR:25-27):
- REL = H1Â·UVB + FCC_ON + QUALÂ·FCCNÂ·Â¬P5
- /CE = Â¬P5
- RFC_OFF = FCCN + H1Â·UVB

RFC_OFF = 1 gives the regen clamp (Q202 off). RFC_OFF = 0 gives the FC clamp (D:1805-1807).

### 1. Mode and transition table

| Case | REL | /CE | RFC_OFF | R-rule / converter verdict |
|---|---|---|---|---|
| Init, Idle (REGEN = FCC = 0) | H1Â·UVB | HIGH | 1 | The charger has no input path, so it is unpowered (D:2328). OK |
| Run entry, qualification (REGEN 1, FCC 0, P5 0, QUAL 1, H1 0) | 1 (QUAL term) | HIGH | 1 | Charging is blocked twice: /CE HIGH and EN_CHG = 0. The bus feeds only the IC quiescent current and SYS. The draw is TODO(verify: SLUSDV2C). There is no hardware time limit (TR:148 item 6). OK under R3' |
| Firmware slip: QUAL with P5 HIGH | H1Â·UVB | LOW | 1 | The NOT P5 term masks QUAL (TR:31). OK |
| Run cruise, regen armed (P5 1, H1 0) | 0, held | LOW | 1 | Hard converter-off, still conditional on EN_EXTILIM = 1 (T-B-21, D:2331). OK |
| Regen burst outside a window (H1Â·UVB) | 1 | LOW | 1 | V-MOT > 1.089Â·VBUS, so D-MT-EN is reverse-biased and the charger draws from the motor only (D:2332). R3 OK |
| Brake with UVB 0 or T2 open | 0 | LOW | FCCN | Held. With T2 open in a window, RFC_OFF = 0 keeps the FC clamp, which is better than r8 (where H1R kept the regen clamp, D:2493) |
| FC window, cruise (FCC 1, BT_BUS 0, REGEN 1) | 1 (FCC_ON) | LOW | 0 (FC clamp) | Loop barrier is **firmware only** (I-9, FAULT_SWITCH_CONFLICT; TR:144 item 2). BTB_OFF and BT_OK are gone (D:1536). No UVB shed (TR:145 item 3) |
| Bus sag in a window, no brake | 1 | LOW | 0 | Only VINDPM 14.5 V and 1 kHz firmware act. Accepted |
| Brake in a window, REGEN ON (R7), UVB 1 | 1 | LOW | 1 (regen clamp) | D-BC-FC is reverse-biased once VCHG-IN > VBUS âˆ’ 35 mV, so the FC is unloaded (D:2402-2408). OK |
| Brake in a window, REGEN ON, UVB 0 | 1 | LOW | 0 (FC clamp, 0.65-0.95 A) | Absorption is limited, so V-MOT may reach the VESC cut (harvest lost). Safe |
| Brake in a window, **REGEN OFF** (State 98 `J`, D-BC-RG OTP) | 1 | LOW | 1 | The FC clamp lifts while VCHG-IN is fed from VBUS only: the r2 hazard, accepted (TR:32). See 1.1 |
| Raised image, then V-MOT falls back (H1 â†’ 0) | 1 | LOW | 0 | **The hardware blank is gone** (D:2338). Only VINDPM 18.2 V (soft) and the firmware T4 restore act. See 1.1 |
| Charger POR inside a window | 1 | per P5 | H1Â·UVB at the POR instant | Without a brake the FC clamp latches. During a brake the regen clamp latches. In both cases P5 drops within 20 ms or the watchdog resets within 50 ms, both under the â‰¥ 180 ms switching delay (D:2348). Lands safe. Pin re-read is T-B-07 |
| Charger POR, regen-armed cruise | 0 | per P5 | 1 | 100 mA clamp latch, unchanged |
| Purge pre-emption (T5), FCC â†’ 0 | H1Â·UVB | LOW | 1 | A brake in progress is still absorbed. OK |
| Finish (T6), State 99 (T7) | H1Â·UVB until the switches open | HIGH | FCCN | OK. Remove FCCEIL and HB from phase 0 |
| State 98 `J`, REGEN 0, FCC 1 | 1 (FCC_ON alone) | per P5 | H1Â·UVB | **No hardware loop barrier.** Safety rests on `assertFcChargeEnable()` driving BT_BUS LOW (CLAUDE.md Â§2, Â§8). The fw v37 `J` mode (REGEN + MOT_PWR from the bus, H1 0) can no longer convert |
| MCU reset, pins high-Z (R108/R123 47 k, EN 10 k) | H1Â·UVB | HIGH | 1 | The charger is unpowered. A slow fall of QUAL or P5 can make REL chatter only with /CE going HIGH (D:1691). OK |
| MCU hang, P5 frozen HIGH, in a window | 1 | LOW | 0 | Charging continues; ARM_OK is gone. The watchdog expiry resets EN_CHG and ICHG but not VINDPM or IINDPM (D:2900-2905). Only R5/T-W-01 bounds it (TR:143) |
| Hang in qualification (QUAL 1, P5 0) | 1 | HIGH | 1 | No charge (/CE). The watchdog reset drops QUAL through R123 |
| Brown-out | â€“ | â€“ | â€“ | TODO(verify: SCES LVC below 1.65 V). The EN nets fall with the MCU, so the charger loses input power. Same exposure as r8 |
| CR 3V3 lost (T6 open) | 0 | HIGH (EIB unpowered, R272/R272b) | 0 | Fails safe. **Undetected**, because the pin-7 sense is gone (TR:146 item 4) |
| Ribbon conductor open: pin 5 / 7 / 8 / 10 / 1+2 | â€“ | HIGH / HIZ / held (U202 Y floats, so Q201 is on) / FC clamp / all safe | | All fail to the safe side through R267-R270, but none is detected now. Note: the B.6 row at D:1836 files "ribbon 8 open" under latent; it actually holds |

#### 1.1 Consequences that need a J.1 or firmware entry (not R3' violations)

- **Blank loss.** The raise (T3) writes IINDPM 1.70 A and VINDPM 18.2 V. After H1 falls, VINDPM above the bus is the only stop on FC draw. An abrupt VESC stop (4.4 V/ms) relies on the VINDPM loop speed (unspecified) and on the OC_FC 1.4 A sample, which gives a nuisance State 99. **Fix:** make the FR-07 pin-34 ISR also handle the **falling** edge and post T4 at the queue head.
- **Brake in a window with REGEN OFF.** T3 fires on H1 rb without checking REGEN. VCHG-IN â‰ˆ VBUS < 18.2 V, so VINDPM stops the draw. The exposure is register-only, bounded by OC_FC. **Fix:** T3 requires REGEN read back HIGH. Outside State 98, FR-49 refuses FCC HIGH with REGEN LOW.
- **F.5 proofs that lost their sensor.**
  - I-2(a) and T10 step 2 proofs (a) and (c) used pin 7 and pin 33 (D:2833, D:2879). Only (b), V_chg decay (37-102 ms), remains, so late trips fall into the double-fault State 99.
  - **Fix:** add a proof (d): FCC and REGEN EN read back LOW for the turn-off time plus 2 ms, **and** CHG_IIN (pin 22, T17 kept) < 0.1 A for 1 ms.
  - Also delete T1 steps 6, 8, 8b and 8c, delete I-7, remove FCCEIL from I-1, I-4 and T3/T4, and rewrite the I-5 one-shot sentence.

#### 1.2 Hazards flagged

- **SAFETY-1: U120 FCC_ON stuck HIGH** (output fault, or R188 shorted) **is latent and alone breaks R3'.**
  - Effect: REL = 1 in regen-armed cruise with BT on the bus and /CE LOW. Bus â†’ charger â†’ pack becomes a loop held only by VINDPM 18.62-19.38 V, a register.
  - Why r8 was covered: H2c needed BTB_OFFÂ·BT_OK (D:1526), and FR-08(a) on pin 33 would have read "released".
  - Why it is latent now: there is no FCC_ON readback, and current through IMON is â‰ˆ 0 while VINDPM holds.
  - H1 does not have this gap, because its pin-34 readback stays for FR-08(d).
  - **Fix (no package):** use FCC_ONÂ·Â¬FCC_OFF, so the two independent comparators U119 and U120 must agree. It uses the spare U105 section 1 and the spare U118 gate B. A stuck-HIGH U120 then needs U119 to also misread before the converter releases.
- **SAFETY-2 (latent; recommend a J.1 entry or a test): /CE stuck LOW.** Causes: U201 1Y sinking, or R272 and R272b both open (D:1843-1845). This was detected by U204/FR-08(b) and is now invisible. It silently removes FR-47(a) pack OV, which acts only through P5 (TR:147). OV_BATT â†’ State 99 teardown remains.
  - **Fix:** a Run-entry functional check. During qualification with P5 LOW, write EN_CHG 1 for â‰¤ 5 ms. Then require CHG_STAT = not charging and IBAT â‰ˆ 0 (TODO(verify: SLUSDV2C REG1C)). Otherwise trip.

### 2. Minimal realisation

Surviving comparators: U102 (H1), U103 (UVB), U119 (FCCN), U120 (FCC_ON). With the SAFETY-1 term the logic is:

```
P5N   = NOT CHG_ARM               U105 sec2 (existing)
FCCNN = NOT FCCN                  U105 sec1 (was spare, D:1927)
H1U   = H1 AND UVB                U118A
FCCP  = FCC_ON AND FCCNN          U118B
QF    = QUAL AND FCCN AND P5N     U107
GATE  = H1U OR FCCP               U110A
ILIM_REL = GATE OR QF             U110B -> R131A/R131B -> J101.7/.8
RFC_OFF  = FCCN OR H1U            U106B -> R132 -> J101.10
CE_DRV   = CHG_ARM (wire)         R130 -> J101.5
```

Pin-level netlist (pinout D:1880-1885, generator `lvc2g`/`lvc1g11`):

| Ref | Pins |
|---|---|
| U105 SN74LVC3G04 | 1 1A â† FCCN; 7 1Y â†’ FCCNN; 3 2A â† CHG_ARM; 5 2Y â†’ P5N; 6 3A â†’ GND; 2 3Y nc; 4 GND; 8 VCC (C114) |
| U118 SN74LVC2G08 | 1 1A â† H1; 2 1B â† UVB; 7 1Y â†’ H1U; 5 2A â† FCC_ON; 6 2B â† FCCNN; 3 2Y â†’ FCCP; 4 GND; 8 VCC (C126) |
| U107 SN74LVC1G11 | 1 A â† QUAL; 3 B â† FCCN; 6 C â† P5N; 4 Y â†’ QF; 2 GND; 5 VCC (C116) |
| U110 SN74LVC2G32 | 1 1A â† H1U; 2 1B â† FCCP; 7 1Y â†’ GATE; 5 2A â† GATE; 6 2B â† QF; 3 2Y â†’ ILIM_REL; 4 GND; 8 VCC (C119) |
| U106 SN74LVC2G32 | 1 1A, 2 1B â†’ GND; 7 1Y nc; 5 2A â† FCCN; 6 2B â† H1U; 3 2Y â†’ RFC_OFF; 4 GND; 8 VCC (C115) |
| R130 | CHG_ARM â€“ CE_DRV_J (J101.5) |

Without SAFETY-1, the package count is the same; only U105 section 1 and U118 gate B go spare.

**Ioff and edges.**
- Every remaining LVC part has Ioff (D:1663), as does U201 (SCES364J, D:1795). With T6 lost, Teensy pins 5 and 10 cannot back-power either rail; the B.7 row at D:1873 holds.
- Pin 5 now drives the ribbon directly. A short of J101.5 to GND puts 3.3 V across 100 Î©, about 33 mA on a Teensy pad. TODO(verify: i.MX RT1062 pad limit); consider R130 â†’ 470 Î©.
- The slow pin-5 fall now reaches U201 1A directly. It chatters only toward /CE HIGH, as already accepted at D:1691, so T-D-01 still covers it.
- U119 and U120 still share the T5 tap, so R187 stays 3.30 MÎ© (D:1621).

### 3. Part and net delta

**Survive:** U105, U106 (gate A now spare), U107 (re-purposed), U110, U118 (re-purposed), and C114, C115, C116, C119, C126. U102, U103, U119 and U120 stay with their networks.

**Remove:**
- Logic packages U108, U109, U114 and U116, with C117, C118, C122 and C123. This adds to the TR removals U104, U111, U113, U115 and U121.
- R137 (FCI_OK).
- Timing parts R150/C150 and R151/C151.
- R124 (FCCEIL), R135/R136 (HB), and R121/R133 (RGN tap).
- Readback resistors R125, R127, R128 and R148.
- Comparator networks: U104 (R140-R144, C112), U115 (R117-R120, C109, C113), U121 (R190, R191, C133).
- BAV199 count unchanged (D104-D106).

**Nets removed:** UF, X, Y1, W, H1Q, H2C, H1R, QQ, QQF, ILIM_PRE, ARM_OK, HB, FCCEIL, FCI_OK, BT_OK, BTB_OFF, RGN, RGN_ON, ILIM_SENSE, CE_SENSE.

**Nets added:** H1U, FCCNN, FCCP, QF.

**Ribbon:** tie J101.11 and J101.13 to GND as guard conductors. On the fabricated EIB, fit U203, U204, R258-R265 and C203/C204 as DNP, so J201.11 and J201.13 stay open there.

**Keep-alive option:** U112 lost its EN (RGN) and its VIN (T18), so the B.5 option is dead as drawn.

### 4. Open TODOs

- TODO(verify: SLUSDV2C) the qualification-state input draw.
- TODO(verify: SLUSDV2C) the ICHG default after a watchdog expiry.
- T-B-07: is the ILIM pin re-read continuously?
- The SAFETY-1 and SAFETY-2 fixes need an operator decision.

Scratch output: none written. This was a read-only analysis.
