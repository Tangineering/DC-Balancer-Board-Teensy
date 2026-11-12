# CR tap review with the operator (2026-11-12)

Source: tap-review session, against the `charger-evm-round4` worktree (A.4, B.1, B.2, D.3, F.2, G.2; outline_change_2026-11-12/leads.md).
The operator went through every tap. A forked side session prepared the permit-architecture variant, and this session reviewed it with the operator.
No repo file was edited. The operator edits the IO CSV themselves.

## 1. Operator decisions (verbatim)

- On the fork's reduced permit architecture: "This variant is my selection."
- "Let's keep T13, but not T12 or T20"
- "The U111 charger check I want to keep but a one-shot is not necessary, as I'm not concerned about an MCU hang. T5 we can keep if it's necessary for the regen release logic. Note though that it is fine for regen to occur during a fuel cell charging window, as it simply takes the load off of the fuel cell."
- "RFC_OFF: (b), keep harvest"
- "T18 and T19 remove"
- F24 / pin 2 PURGE_SENSE: "Drop it"
- Teensy IO names: "If these accurately reflect the functionality then they're fine"
- On the added NOT P5 term in the qualification release: "Confirmed, add the NOT P5 term and send the report"

Stance behind the variant (the operator's choice, from the fork): trust firmware fully except for one hardware check. The regen check V-MOT > VBUS (H1, with UVB) stays, so with FC_CHARGE off the bus cannot feed the charger through the regen path (R3), even with firmware hung.

## 2. Resulting permit logic

The equations below were reduced in this session and NOT re-derived against F.3 or F.5:

```
release = (H1 AND UVB) OR FCC_ON OR (QUAL AND FCC_OFF AND NOT P5)   -> ILIM_REL (W5 pins 7/8)
CE_DRV  = P5                       -> /CE = NOT P5 at the EVM (was P5 AND ARM_OK)
RFC_OFF = FCC_OFF OR (H1 AND UVB)  -> W5 pin 10 (option b: harvest kept)
```

- **QUAL** is now a level input on pin 10. The U111 one-shot is removed, so there is no hardware time limit. Firmware drops pin 10 when the qualification read completes.
- **The NOT P5 term** replaces the one-shot's CLR = P5N. Without it, QUAL HIGH with P5 HIGH would release the converter with charging enabled and the bus feeding the charger in Run, which violates R3.
- **RFC_OFF (b)** accepts the r2 hazard (finding h2c-h1-term-not-rgn-qualified): during an FC window, a brake with REGEN LOW removes the FC clamp while VCHG-IN is fed from VBUS alone. The operator accepts this because regen inside an FC window "simply takes the load off of the fuel cell". Inside an FC window, the hardware no longer distinguishes REGEN on from REGEN off, because RGN_ON is gone.
- **Parts kept:** U102 H1, U103 UVB, U119 FCC_OFF, U120 FCC_ON, and gates to form the three equations. The fork's text had dropped U119. U119 stays because it drives the qualification term and RFC_OFF, and it sits on T5, which is kept.
- **Parts removed:**
  - U104 BT_OK (T8, T9);
  - U115 BTB_OFF (T3);
  - U121 RGN_ON (T4);
  - U113 heartbeat and ARM_OK (T21);
  - U111 one-shot;
  - the FCCEIL terms (T11);
  - EIB far-end senses U203 (ILIM) and U204 (/CE), their R264 path, and the ribbon sense conductors.
- **U106, U107, U108, U109, U110, U114, U116, U118, R137:** the design owner must re-derive which of these survive.

## 3. Tap table

| Tap | Decision | Teensy IO | Reason / note |
|---|---|---|---|
| T1 (F01, V-MOT via R170) | keep | none | H1 |
| T7b (F02, shield) | keep | none | T1 shield |
| T2 (F03, VBUS via R171) | keep | none | H1 IN- and UVB |
| T3 (F04, D-BT-EN) | **remove** | pin 28 (CR no longer loads it) | BTB_OFF gone; FC loop barrier is firmware-only (I-9) |
| T4 (F05, D-BC-RG) | **remove** | pin 30 (CR no longer loads it) | RGN_ON gone; RFC_OFF (b) |
| T5 (F06, D-BC-FC) | keep | pin 31 net | U119 FCC_OFF + U120 FCC_ON |
| T6 (F07 + R175, 3V3) | keep | Teensy 3V3 | only CR/EIB logic supply |
| T22 (F08) | removed by D-38 | - | - |
| T8 (F09, INA253 BT) | **remove** | pin 41 (CR no longer loads it) | BT_OK gone |
| T9 (F10, SNS-BT Kelvin) | **remove** | none | BT_OK gone; also removes the lead that ran under the CR |
| T10 (F11) | keep | **pin 10 `CHG_QUAL`** (level release request) | qualification release |
| T11 (F12) | **remove** | pin 17 freed | FCCEIL gone |
| T12 (F13) | **remove** ("not T12") | pin 33 freed | far-end ILIM readback gone |
| T13 (F14) | keep ("keep T13") | **pin 34 `CHG_H1_RB`** | FR-07 brake-edge ISR, FR-08(d) |
| T14 (F15) | **remove** | pin 16 freed | H2c gone |
| T15 (F16) | **remove** | pin 23 freed | BT_OK gone |
| T16 (F17 + R106s) | keep | **pin 35 `CHG_EFUSE_FLT`** | FR-23, FR-48 |
| T17 (F18) | keep | **pin 22 `CHG_IIN`** | FR-11, FR-13, FR-33 |
| T17r (F19, shield) | keep | none | T17 shield |
| T20 (F20, ROS pad 2) | **remove** ("not T20") | pin 7 stays undriven (`ENC_ENABLE`, "No longer in use") | far-end /CE readback gone; PM10 (ROS removal) and T-A-01b likely unnecessary |
| T21 (F21) | **remove** | pin 21 freed | heartbeat and ARM_OK gone |
| T18 (F22) | **remove** ("T18 and T19 remove") | none | parts already gone (D-31); delete row and pad |
| T19 (F23) | **remove** ("T18 and T19 remove") | none | U117 already gone (D-31); delete row and pad |
| F24 (pin 2 PURGE_SENSE) | **drop** ("Drop it") | none | delete row, pad and the D.3 conditional row |

The result is 10 conductors: T1, T7b, T2, T5, T6, T10, T13, T16, T17 and T17r.
- **Soldered on the MB:** only T1 (C-D6) and T2 (C-D2). T7b is insulated at C-D6.
- **Dubox J1/J2 plug-ins:** T5, T6, T10, T13, T16, T17 and T17r.
- **Teensy pins used by the CR:** 10, 22, 34 and 35, plus the pin-31 net through T5.
- **Free Teensy pins after this:** 2, 7, 8, 16, 17, 21, 23 and 33. Pin 20 stays reserved for WDOG1_B.

## 4. IO CSV rows prepared for the operator (the operator pastes these; this session made no edit)

```
5,Output,Digital,Charger arm (BQ25798 /CE through the CHG carrier),CHG_ARM,"HIGH = charging allowed (carrier drives /CE LOW through EIB U201). LOW or high-Z = inhibited (47 kOhm pull-down on the carrier). CHG_QUAL acts only while this pin is LOW. Was MPPT_DISABLE (Ag105 removed)"
10,Output,Digital,Charger input-qualification release request,CHG_QUAL,"Level: HIGH releases ILIM_HIZ for the charger qualification read only while CHG_ARM is LOW and FC_CHARGE is proven off (carrier FCC_OFF comparator). No hardware time limit. Raise only after EN_CHG = 0 is read back; drop when the read completes. 47 kOhm pull-down"
22,Input,Analog,Charger input current (eFuse IMON),CHG_IIN,(D.3 text unchanged)
34,Input,Digital,V-MOT above bus comparator readback,CHG_H1_RB,(D.3 text unchanged)
35,Input,Digital,Charger input eFuse fault,CHG_EFUSE_FLT,(D.3 text, "keeps the interlock monitors armed" shortened to "reads no fault")
```

Changes to the rest of D.3:
- **Rows 6, 19, 20 and 31:** unchanged.
- **Rows 27, 29 and 32:** r6 notes unchanged (FR-49 stands).
- **Rows 28 and 30:** keep the never-INPUT_PULLUP note, but drop the carrier-tap sentences.
- **Row 41:** no carrier note.
- **Rows 7, 16, 17, 21, 23 and 33:** not added.
- **Pin 2 conditional row:** dropped.

## 5. Affected design-doc rows and firmware requirements (from greps; not exhaustive)

**Design doc:**
- A.4: tap table, heading and lengths.
- A.8: pad assignment and short table. The removed pads are F04, F05, F09, F10, F12, F13, F15, F16, F20, F21, F22, F23 and F24.
- B.1: inputs, equations and truth table.
- B.2: U104, U115 and U121 removed; U119 kept.
- B.3: logic parts.
- B.6 EIB: U203 and U204, R264, and the ribbon sense pins. The W5 pin map may shrink.
- B.7 and B.8: netlist.
- B.9.
- D.2 and D.3: CSV rows; PM10 is likely unnecessary.
- E: BOM.
- F.2: mode table qualifiers (ARM_OK, FCI_OK).
- F.3: loop proof. There is no hardware FC-path barrier now.
- F.5.
- H.17: the one-shots are retired.
- J.1: accepted risks (section 6).
- leads.md and the J-TAP cavity count (10 taps).

**Firmware requirements:**
- **FR-08:**
  - (a) loses the ILIM sense and expected_max;
  - (b) loses the /CE sense and HB_dead;
  - (c) loses the H2c readback;
  - (d) stays.
- **FR-27, FR-28, FR-42 and FR-43:** the heartbeat parts go.
- **FR-07, FR-09, FR-17 and FR-41:** the FCCEIL parts go. The FR-07 pin-34 ISR stays, but only posts the raise.
- **FR-34 and FR-35:** go.
- **FR-36:** loses its /CE-sense use.
- **FR-47(b):** the unexpected-inhibit trip loses its input. FR-47(a) is unchanged (pack OV acts through P5).
- **FR-04:** QUAL becomes a level input, gated by NOT P5 in hardware. The T1 step-5 REGN proof keeps only PG_STAT.
- **FR-12 self-test, FR-20 telemetry bits and FR-22 tests:** change.
- **FR-01:** pin list shrinks.
- **FR-49, FR-23, FR-48, FR-11 and FR-13:** unchanged in intent.

**Tests:**
- T-C-10 (one-shot and heartbeat widths): retire.
- T-C-12: likely retires.
- T-A-01b (pin-7 tap): retires.
- T-F-xx tests that use H2c, BT_OK or FCCEIL: review.
- T-F-09 (REGEN LOW in a window): its expectation changes under RFC_OFF (b).

## 6. Accepted costs (operator stance) and open TODOs

**Accepted costs:**
1. A hung MCU during an FC window keeps charging. The only hang defence left is the R5 MCU watchdog (G.3, pin 20). Proposal: make "watchdog fitted and T-W-01 passed" a hard FC-window precondition (FR-05 already lists it).
2. The FC-window loop (battery to bus to charger) is prevented only by firmware (assertFcChargeEnable, I-9).
3. There is no microsecond shed on a bus sag inside an FC window; firmware at 1 kHz plus VINDPM must handle it.
4. There is no check that ILIM_HIZ or /CE actually arrived at the EVM. A broken ribbon conductor or a dead EIB driver goes unseen.
5. Pack OV stays firmware-only (D-38).
6. The qualification release has no hardware time limit (level QUAL). Only firmware drops pin 10.
7. Under RFC_OFF (b), the r2 hazard is accepted (section 2).

**TODO:**
- Re-derive the gate against F.3 and F.5, in particular:
  - State 98 `J` with REGEN 0 and FCC 1, which passes via FCC_ON alone;
  - a brake inside an FC window (R7), with REGEN on and with REGEN off.
- Confirm that a BQ25798 "charger POR inside an FC window" still lands on a safe clamp now that RFC_OFF is (b).
- TODO(verify: SLUSDV2C) the BQ25798 input draw with ILIM_HIZ released and /CE HIGH (the qualification state, now with no hardware time limit).
- TODO(verify: SLUSDV2C) the BQ25798 I2C watchdog on an MCU hang: which registers reset to default, and whether EN_CHG or the limits change while /CE stays as driven.
- Confirm the remaining CR and EIB parts list and the routing area freed (13 fewer pads; the logic area shrinks).
- dec-leads: J-TAP drops to 10 cavities, and only T1 and T2 remain MB-soldered. T9 and T22, the leads that ran under the CR, are both gone.
