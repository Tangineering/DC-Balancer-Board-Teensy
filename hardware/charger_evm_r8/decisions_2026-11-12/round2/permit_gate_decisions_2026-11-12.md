# Permit-gate hardware decisions (operator, 2026-11-12)

Source session: permit-gate decision session (side session of "EVM design updates"). No repo file was edited.
Sources read: DESIGN_STATE_2026-11-12.md, decisions_2026-11-12/cr_tap_review_2026-11-12.md,
ramifications/gate.md, inventory.md, check_1-3.json; wiring design B.3, B.6, B.7, J.1 (DC-Balancer-round4 worktree).
Operator stance restated to the operator: trust firmware except the regen H1·UVB check.

## 1. Decisions (operator's selections, verbatim option labels)

| # | Item | Operator's answer | Meaning |
|---|---|---|---|
| 1 | Agreement term | "Adopt (Recommended)" | FCCP = FCC_ON AND NOT FCC_OFF, using U105 section 1 and U118 gate B |
| 2 | Gate mapping | "gate.md 5-LVC (Recommended)" | U105 3G04, U106 2G32, U107 1G11, U110 2G32, U118 2G08; the inventory mapping (U109/U116) is rejected |
| 3 | CE_DRV | "Buffer via U106A (Recommended)" | CE_DRV = CHG_ARM OR GND on U106 gate A, push-pull into R130; R108 stays 47 kOhm |
| 4a | Gate outputs stuck HIGH, ILIM_REL common-mode | "Accept + build sweep (Recommended)" | J.1 entry; full truth-table sweep (T-C-01/T-C-05) at every build; no in-service readback (no 11th tap) |
| 4b | QUAL stuck HIGH | "Accept + rules (Recommended)" | J.1 entry; the T6-T10 short is excluded by the pin-order rule; host test that SPI never claims pin 10 as CS0; the two-latent-fault loop (with 4c) is recorded |
| 4c | /CE stuck LOW | "Accept residual risk. Rely on firmware measurement of currents and switch states" (operator's own text) | J.1 entry; no hardware sense, no build-time /CE check was chosen; the U204 network is not used (inferred: DNP, confirm) |
| 5 | Tap-connector pin order | "Non-adjacency only" | T5, T6 and T10 pairwise non-adjacent; no dedicated GND guards required |

The SAFETY-2 "EN_CHG = 1 for 5 ms" check was not offered: check_2 and check_3 refuted it (unsafe under the fault, insensitive).

## 2. Resulting gate netlist intent (gate.md section 2 plus decision 3)

```
P5N      = NOT CHG_ARM            U105 sec 2 (2A <- CHG_ARM, 2Y -> P5N)
FCCNN    = NOT FCCN               U105 sec 1 (1A <- FCCN, 1Y -> FCCNN)
(spare)                           U105 sec 3 (3A -> GND, 3Y nc)
H1U      = H1 AND UVB             U118A (1A <- H1, 1B <- UVB, 1Y -> H1U)
FCCP     = FCC_ON AND FCCNN       U118B (2A <- FCC_ON, 2B <- FCCNN, 2Y -> FCCP)
QF       = QUAL AND FCCN AND P5N  U107 1G11 (A <- QUAL, B <- FCCN, C <- P5N, Y -> QF)
GATE     = H1U OR FCCP            U110A
ILIM_REL = GATE OR QF             U110B -> R131A/R131B -> J101.7/.8
RFC_OFF  = FCCN OR H1U            U106B -> R132 -> J101.10
CE_DRV   = CHG_ARM OR GND         U106A (1A <- CHG_ARM, 1B <- GND, 1Y -> CE_DRV) -> R130 -> J101.5   [changed from gate.md's direct wire]
R108     = 47.0 kOhm (unchanged)
```

Equations: release = H1·UVB + FC_ON·¬FCC_OFF + QUAL·FCC_OFF·¬P5; /CE = ¬P5; RFC_OFF = FCC_OFF + H1·UVB.
The only spare section left is U105 section 3. Pin 5 no longer drives the ribbon.

Design-owner checks for decision 3:
- The 4-5 ribbon-short row: with U106A driving push-pull, CE_DRV stays LOW against R107 10k with pin 5 high-Z. Re-derive the B.6/A.3 row.
- The r5 "4-5 with CE_DRV HIGH and STAT sinking" figure (U201 1A >= 2.72 V) assumed U114 push-pull through R130 100 ohm. U106A is the same class of driver, so the figure should hold. Re-check it.
- The slow pin-5 fall now reaches U106A (a plain LVC input). The T-D-01 scope point and its Schmitt fallback move to the U106A input.
- A J101.5-to-GND short now loads an LVC output at about 33 mA (100 ohm), as U114 did in r8. The Teensy-pad concern in gate.md section 2 is gone.
- Computation note: R108 at 10k gives about 1.49 V on the 4-5 short (10k || 48k against R107 10k; check_2 says about 1.3 V). Both are in the LVC undefined band, which is why the buffer was chosen.

## 3. Constraints passed to other sessions

- **dec2-tapconn:** T5, T6 (3V3) and T10 must be pairwise non-adjacent. In a 2-row housing, adjacency includes the opposite-row pin and, as a recommendation, the diagonals. The operator chose non-adjacency only, with no mandatory GND guards. The 10-conductor short and open table must still be re-derived (check_1 section 1.2).
- **dec2-assembly:** the gate logic is 4 DCT packages (U105, U106, U110, U118) plus 1 SC70/DCK (U107). The single-gate DBV option was rejected.
- **dec2-eib:** the U203 and U204 networks are not needed by this gate. J101.11 and J101.13 are free (NC or GND is that session's call). A GND tie is safe only if U203 and U204 are not fitted.
- **dec2-fwrules (from 4a-4c, firmware is the in-service layer):**
  - a host test that the SPI and core setup never claim pin 10 (CHG_QUAL) as CS0;
  - an in-service detection for /CE stuck LOW, from currents and switch states (the operator's words). Suggestion: when FR-47(a) drops P5, also write EN_CHG = 0 and verify that the charge current falls. The EN_CHG pulse test is refuted and must not be used;
  - CHG_IIN plausibility against the expected gate state, which partly covers 4a in service.

## 4. Open TODOs

- U204 DNP: CONFIRMED by the dec2-eib session (operator decision there): U203, U204, R258-R265 and C203/C204 are DNP, and J101.11/.13 are NC. This agrees with 4c, so U204 is not needed back. The R272 + R272b double-open leaves /CE floating; it is latent, and T-C-05 metering is the only check.
- J.1 entries to write: 4a (CR gate output stuck HIGH or ILIM_REL short, one fault leaves VINDPM; a charger POR resets VINDPM to VBUS0 - 1.4 V), 4b (QUAL stuck HIGH, /CE HIGH plus EN_CHG = 0 as barriers), 4c (/CE stuck LOW, which also floats /CE on a double R272/R272b open with R263 DNP), and the 4b+4c two-latent-fault loop.
- T-C-01/T-C-05: define the build truth-table sweep for the new 4-input gate (H1, UVB, FCC_ON, FCC_OFF, QUAL, P5).
- The T5 node short (T5 to 3V3, or pin 31 stuck HIGH) is still uncovered by the agreement term. The rule in decision 5 is its only hardware mitigation. The check_3 firmware backstop (V_chg pin 38 or CHG_IIN while FCC is commanded LOW) was offered but not selected.
- TODO(verify: TI orderables) is no longer needed (the DBV option was rejected).
