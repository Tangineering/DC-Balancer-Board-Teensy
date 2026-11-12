## Ramifications inventory: the 2026-11-12 tap review

Sources: `cr/cr.net` (145 parts, parsed), `gen/netlist.py`, `cr/cr.kicad_pcb` (courtyard bounding boxes), design doc `docs/charger_bq25798_wiring_design_2026-11-05.md` (DD), `decisions_2026-11-12/cr_tap_review_2026-11-12.md` (TR). No repo file was edited. The scripts are in the scratchpad `ramif\` folder.

### 1. CR parts, nets and pads

**1a. Named removals (TR:34-41).** Each part is listed with the passives that serve only it (`netlist.py` line numbers).
- **U104** BT_OK: R140-R144, C140 (126-134), R128 (readback), C112 (decoupling, DD:1947), and pads F09, F10, F16.
- **U115** BTB_OFF: R117-R120, C109 (136-141), C113, and pad F04.
- **U121** RGN_ON: R190, R191 (161-163), R121 and R133 (the RGN tap, 145-146), C133, and pad F05.
- **U113** heartbeat: R135, R136, R151, C151 (172-173, 186-188), C121, and pad F21.
- **U111** one-shot: R150, C150 (183-185), and C120. R147 and R123 stay, because QUAL is still an input.
- **FCCEIL:** R124 and pad F12.
- **Readbacks:** R127 (H2C_RB) with pad F15, R125 (ILIM_SENSE) with pad F13, and R148 (CE_SENSE) with pad F20. After this, J101.11 and J101.13 have no CR net.
- **Unconnected pads:** F22, F23 and F24.

These come to **49 parts**. The CR goes from **145 to 96** parts.

**1b. Re-derivation of the survivors (my proposal, not checked against F.3 or F.5).** TR:24-27 needs four functions:
- HU = H1Â·UVB;
- QF = QUALÂ·FCC_OFFÂ·P5N;
- ILIM_REL = HU + FCC_ON + QF;
- RFC_OFF = FCC_OFF + HU.

A minimal mapping onto the existing helper pinouts (`netlist.py`:41-52):

| Part | Use |
|---|---|
| U105 | P5N, still needed for the NOT P5 term |
| U116 | gate 1 forms HU; gate 2 is spare, and could buffer CE_DRV |
| U109 | 3-input AND forming QF |
| U110 | OR(HU, FCC_ON), then OR(Â·, QF) gives ILIM_REL directly into R131A/B |
| U106 | gate 2 forms RFC_OFF; gate 1 is spare |

On that mapping, **U107, U108, U114, U118 and R137**, with their decoupling capacitors C116, C117, C122 and C126, are also removed (9 more parts). The CR then has **87 parts**. CE_DRV = P5 becomes a direct wire or a buffer (see Q2). Comparators: 7 become 4 (U102, U103, U119, U120).

**1c. Courtyard area freed (bounding boxes).**

| Set | Top (mmÂ²) | Bottom (mmÂ²) | Total (mmÂ²) |
|---|---|---|---|
| 1a ICs | 61.4 | â€“ | â€“ |
| 1a passives | â€“ | 96.6 | â€“ |
| 1a, 13 tap pads | 52.0 | â€“ | â€“ |
| **1a total** | | | **210.0** |
| 1b | 43.1 | 15.3 | 58.4 |
| Both | | | **â‰ˆ268** |

Without the pads, 1a and 1b together free about 216 mmÂ². That is about 31 % of the 703.4 mmÂ² SMT booking in `outline_change_2026-11-12/assembly.md` Table 1. The F pads are retired anyway when the taps move to one connector.

**1d. EIB (already fabricated).** These become **DNP**:
- the U203 network: U203, C203, R258-R261, R265;
- the U204 network: U204, C204, R262, R263, R264 (`netlist.py`:270-285).

The E4 and E6 sense leads are not built (`netlist.py`:299, 301). J201.11 and J201.13 are then unused. No re-spin is needed.

### 2. Design-doc rows

Action key: R = rewrite, D = delete, X = retire.

| Section (DD lines) | Action |
|---|---|
| 0.2 / 0.3 (77-401) | Add an r9 entry; the history stays |
| A.1 (438-451), A.3 (485-491) | R: lead and pin lists |
| A.4 (644-696) | R: 10 taps; delete T3, T4, T8, T9, T11, T12, T14, T15, T18-T21 and F24 |
| A.5 (717-732) | D: the E4/E6 sense leads |
| A.6 (750-771) | R: the T9 Kelvin / BT_OK ground text |
| A.8 (1232-1305, 1361-1415) | R: pad table, short table, comparator-band booking |
| A.9 (1476) | R: U203/U204 DNP |
| B.1 (1482-1612) | R: inputs, equations, truth table |
| B.2 (1613-1662) | D: U104, U115, U121 |
| B.3 (1663-1700) | R: logic parts |
| B.5 (1748-1792) | X: the keep-alive EN was `RGN` (T4) and its supply was T18; both are gone |
| B.6 (1793-1861) | R: far-end senses and the W5 map |
| B.7 (1862-1876), B.8 (1877-1971, decoupling 1947), B.9 (1972-1984) | R |
| C EM1, EM5 (C table) | R: the E6 and E4 sense joints are not made |
| D.1 PM6 / PM7 / PM10 (PM10 2035) | R / X / X |
| D.2 (2037-2048) | R: pins 7, 16, 21, 23, 33 |
| D.3 (2050-2081) | R per TR Â§4 |
| D.4 bodge record (2087-2130) | R |
| E (2207-2310) | R: BOM |
| F.1 (2322) | R |
| F.2 (2324-2350) | R: rows "Regen burst", "Raised, V-MOT falls back" (H2c blank gone), State 98, Teensy hang, hang inside QUAL |
| F.3 (2465-2503) | R: no hardware FC-loop barrier; drop the U113/U111/BTB rows |
| F.4 (2600-2811) | R: FCCEIL and H2c in pre-emption and early purge |
| F.5 (2827-2881) | R: I-1, I-2, I-4, I-5; D: I-7; R: T1 steps 0/5/6/8, T3, T4, T5, T6, T7 phase 0, T10 |
| G.3 (3017-3058) | R: heartbeat references; R5 is now the only hang defence; pin 21 is free (3022) |
| H.3 (3070-3071) | X |
| H.4 (3073) | X |
| H.12 (3101) | R: "FCCEIL blank + FR-09" no longer covers the 1.84-1.90 A row |
| H.15 (3108) | R: the 3V3 load falls |
| H.17 (3113) | X |
| H.22 RGN_ON part (3151) | X |
| H.23 (e2)/(g) (3161) | R |
| J.1 items 1, 6 (3324-3354) | R; add accepted costs 1-7 from TR Â§6 |
| J.2 items 10, 11, 13 (3394-3400) and the pad-pair items (3606-3651) | R |

### 3. Firmware requirements and tests

**FR delete:** FR-09, FR-28, FR-34, FR-35, FR-37 (the retired stub) and FR-47(b).

**FR rewrite:**
- FR-01: drop CHG_FCCEIL, CHG_HB and readback pins 7, 16, 23, 33.
- FR-04: drop T1 step 5's /CE branch, the step-6 pin-33 proof and steps 8b/8c; QUAL becomes a level.
- FR-05 and FR-12: drop the BT_OK self-test, H2c rb and the far-end sense self-test.
- FR-07: the ISR only posts the raise.
- FR-08: reduce to (d).
- FR-11: the loop barrier becomes I-9, FR-10 and FR-38.
- FR-14(e): the U117 fallback "into H2c" has no attach point.
- FR-17: early-purge classification by the V_fc onset only.
- FR-20: smaller `chg_ctrl` bit set (telemetry v5).
- FR-21 and FR-22: HIL logic and host tests.
- FR-23: `regnExpected` loses its FR-08(b) and FR-47(b) consumers.
- FR-26: the H2c-only sentence.
- FR-27: re-base the 5 ms budget on t_WDT.
- FR-33: the GATE/QQ terms.
- FR-36: recovery no longer needs "/CE sense HIGH".
- FR-38: no BT_OK.
- FR-41: the "FCCEIL stays HIGH" clause.
- FR-42: no FR-28 stage-mask term.
- FR-43 and G.3: the RTWDOG short-timeout window and the flash/SD gates are keyed on `chgHbRunning` (DD:2993, 3048); they need a new "charger armed" predicate.
- FR-45: drop the FR-08(a)/(b) timing.

FR-10, FR-13, FR-44, FR-46, FR-48 and FR-49 are unchanged. The operator edits the `.ino`; no code is proposed here.

**Tests to retire:**
- T-A-01b, T-B-09, T-E-02;
- T-C-01b, T-C-01c, T-C-08, T-C-10, T-C-11;
- the BTB/RGN half of T-C-12 (the FCC half stays);
- T-D-09 as written.

**Tests to rewrite:**
- T-A-01, T-A-06;
- T-B-03 (U203 clause), T-B-08 (now R5-only), T-B-11, T-B-20, T-B-22 (pin 7 logging);
- T-C-01 (6 inputs, 64 states), T-C-03 (UVB only), T-C-05 and T-D-11 (E4/E6 lifts are no longer detected), T-C-05c, T-C-07, T-C-09, T-C-16b;
- T-D-02, T-D-03, T-D-06, T-D-07, T-D-13;
- T-E-10;
- T-F-02, T-F-03, T-F-05, T-F-07, T-F-09, T-F-12.

### 4. Effect on pending decisions

- **Assembly:**
  - DCT parts drop from 8 (`assembly.md`:7) to U106, U110 and U116 if U105 becomes a 1G04 in DBV.
  - SC70 parts drop from 3 to U109 only.
  - The U122/U123 rows in `assembly.md` Table 2 are stale (D-38).
  - "Keep DCT at 0.65 mm" now covers 3 parts.
  - The area booking and the bottom-passive count (78) must be recomputed; about 32 bottom passives go.
- **DNP tier 3 (U117):** no longer meaningful. FCI_OK and R137 go with U107 under 1b, and H2c no longer exists. Re-admitting it would need a new FCC_ONÂ·FCI_OK gate.
- **DNP tier 2 (U112):** dead, because both its EN source (RGN/T4) and its supply (T18) are removed.
- **Leads:**
  - J-TAP has 10 conductors. Only T1 and T2 are soldered on the MB; T7b is insulated at C-D6.
  - T9 and T22 no longer run under the CR, so the routing-under-the-CR problem and the separate T22 1x2 connector disappear (`leads.md`:48, 96).
  - Exclusion pairs left: T5 not beside T6, and T6 not beside T10 (`leads.md`:66).
  - The connector shrinks from 2x12 (about 390 mmÂ², `leads.md`:108) to about 2x5 or 2x6, TODO(calc).

### 5. New operator decisions

1. **Gate realisation:**
   - (a) the 1b mapping with existing parts;
   - (b) all single-gate DBV parts, so no 0.65 mm logic: 1G08, 1G11, 3x 1G32 or one 1G332, TODO(verify: TI orderables);
   - (c) keep extra spare gates.
2. **CE_DRV = P5:**
   - (a) a direct wire from pin 5 through R130;
   - (b) buffered by the spare U116 gate, which keeps pin 5 off the ribbon (FR-44 short).
3. **J101 pins 11 and 13:**
   - (a) NC, keeping 2x7 to mate with the fabricated EIB;
   - (b) tie to GND as extra returns.
4. **EIB U203 and U204 networks:**
   - (a) DNP;
   - (b) fitted but unwired.
5. **Hardware blank of the raised image is lost** (FCCEIL / H2c, DD:3101). FCC_ON alone now releases the converter, so a raised image after H1 falls is bounded only by firmware T4.
   - (a) accept and re-derive H.12 and OC_FC;
   - (b) re-admit an FCC_ONÂ·(not raised) term.
6. **UVB stuck HIGH** is now unobservable (FR-35 deleted).
   - (a) accept;
   - (b) a UVB readback on a freed pin.
7. **FR-14(e) fallback (U117):**
   - (a) retire it, leaving the standstill/coast restriction;
   - (b) reserve a gate input.
8. **B.5 keep-alive:**
   - (a) retire it with T-B-09's fallback;
   - (b) re-source its EN.
9. **Pin 21:**
   - (a) use it for EWM_OUT_B to strengthen R5 (DD:3022);
   - (b) leave it free.
10. **RTWDOG short-window predicate** (to replace `chgHbRunning`):
    - (a) any of P5, REGEN or FCC HIGH;
    - (b) Run state.
11. **J-TAP:**
    - (a) 2x5 with no spare cavities;
    - (b) 2x6 with GND separators;

    and choose the family (Micro-Fit or PH).
12. **Should T-W-01 also gate regen arming?** Today it gates FC windows only (FR-05, G.3:3031).
    - (a) no;
    - (b) yes.

**TODO(verify: SLUSDV2C):** the input draw in the level-QUAL state, and the I2C watchdog behaviour on an MCU hang (TR:156-157).
