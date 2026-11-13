## EIB impact of the 2026-11-12 tap review

**Recommendation:** use the fabricated EIB as it is, with the sense branch left unfitted (DNP). Do not respin. The CR keeps a 2x7 J101 with all 14 positions. On the CR, J101 pins 11 and 13 change from sense inputs to GND.

One caveat comes first. The fab README still says "Do not order until the operator has reviewed this package" (`fab/eib_2026-11-11/README.md:52`). TODO(verify: operator): do bare EIBs physically exist? If the EIB is not yet ordered, a respin is only a generator edit. Even so, DNP remains adequate, and a respin gains very little (section 4).

### 1. EIB parts and pins that become unused

The far-end sense branch is a leaf. It reads E4 and E6 and drives only J201.11 and J201.13. No fitted part takes an input from it (`gen/netlist.py:270-285`; B.8 `docs/charger_bq25798_wiring_design_2026-11-05.md:1963-1966`).

| Unused on the EIB | Net / function | Source |
|---|---|---|
| U203, C203, R258, R259, R260, R261, R265 | ILIM_HIZ far-end sense (E4 to J201.11) | netlist.py:270-278; B.6 :1808 |
| U204, C204, R262, R263, R264 | /CE far-end sense (E6 to J201.13) | netlist.py:279-285; B.6 :1809 |
| E4 and E6 pads (no lead fitted) | ILIM_SNS, nCE_SNS | netlist.py:299, 301 |
| J201.11, J201.13 | ILIM_SENSE, CE_SENSE | netlist.py:290-293; B.8 :1969 |
| W5 conductors 11 and 13 | ribbon senses | A.3 W5 row :489 |

The DNP set is 2 ICs and 10 passives. It needs a DNP flag in the EIB BOM and pos files (`fab/eib_2026-11-11/assembly/eib-bom.csv` lines 21 and 25, plus the R258-R263 and C203/C204 lines).

These EIB parts stay functional and unchanged: U201 ch1-ch3, U202, Q201, Q202, Q203, R250-R257, R266-R271, R273-R276, C201, C202, C205, J201 pins 1-5 and 7-10, and E1, E2, E3, E5, E7, E8. On the EVM, R272 and R272b stay.

**CE_DRV = P5** changes nothing on the EIB. J201.5 still reaches U201 1A through R250 and R267 (netlist.py:247-248). On the CR, `CE_DRV` is no longer the U114 output (netlist.py:189). It becomes `CHG_ARM` (pin 5) through R130, and R130 stays (netlist.py:199). At reset, pin 5 is high-Z. R108 (47 kOhm, CR, netlist.py:168) and R267 (47 kOhm, EIB) then pull 1A LOW, so /CE goes HIGH (inhibit). The default level is unchanged.

### 2. Is DNP on the fabricated EIB safe? (floating nodes and pulls)

- **Unfitted IC inputs.** Every input of U203 and U204 belongs to a DNP part, so no fitted gate input floats. When R258 and R259 are unfitted, the 10 MOhm pull-up to 3V3 no longer reaches ILIM_HIZ. This lowers the held ILIM level and slightly lowers the released and clamp levels, which is the conservative direction. H.4 included "sense pull-up" (:3072-3073). TODO(calc: r3_calc.py): re-run H.4 without the R259/R258 term.
- **J201.11 and J201.13** become stubs that end at the empty R265 and R264 pads. Nothing is connected to them on the EIB.
- **/CE pull-up margin improves.** The U204 divider (R262 + R263 = 2 MOhm to AGND) loaded /CE in H.19 (:3119; B.6 R272 row :1799). Without it, /CE HIGH rises above 4.49 V with both pull-ups and above 4.17 V with one open. TODO(calc): restate H.19.
- **Double fault R272 and R272b both open.** In the old design, R263 pulled /CE toward 0 V, so U204 announced the fault (:1845). Without R263, /CE has no defined pull. Only IIN_BIAS_CE and U201 Ioff act on it, and the datasheet requires "must be pulled HIGH or LOW" (SLUSDV2C pin table, quoted at :1799). This case is a double fault, and T-C-05 still meters both pull-ups at every build. However, the case is no longer self-announcing. TODO(verify: SLUSDV2C IIN_BIAS_CE direction) to establish where an open /CE drifts.
- **EIB 3V3 (CR R176 and R177).** The EIB rail now feeds U201, U202 and the R274 bleed (330 uA). Removing two TLV3012B quiescent currents (TODO(verify: SBOS300C IQ, a few uA each)) changes the H.20 figures of 3.131 V and 3.086 V (:3126) by less than 1 mV. Keep R176 and R177 and both 3V3 conductors. The 2-3 short limit (15.9 mA) and the single-open redundancy still apply. The "R264/R265 470 ohm: 6.7 mA into a short" clause of H.20 is retired.
- **3V3 lost on the EIB** is still safe: /CE goes HIGH through R272 and R272b, Q201 turns on, and Q203 turns off, giving HIZ (:1848). The hardware detection through the pin 7 and pin 33 pull-downs is gone, which is accepted cost 4 (`decisions_2026-11-12/cr_tap_review_2026-11-12.md:146`). Firmware sees only the loss of charge current (pin 22 `CHG_IIN`, I2C).

### 3. CR side: J101 map and nets crossing

Keep J101 as a 2x7 part. The W5 factory cable is a 14-way FFSD-class part (A.3 :489), and the fabricated J201 is a 14-pad FTSH-107 footprint (`eib/charger_r8_eib.pretty/Samtec_FTSH-107-01-DV_2x07_P1.27mm_SMD.kicad_mod`, pads 1-14). The signals still needed are **exactly positions 1-10**: 3V3, 3V3, GND, STAT, CE_DRV, KEY, REL_A, REL_B, GND and RFC_OFF.

Proposed J101 map (CR only):

| Pin | Was | New |
|---|---|---|
| 1-10 | unchanged | unchanged |
| 11 | ILIM_SENSE to R125 to F13 (pin 33) | **GND** (CR plane) |
| 12, 14 | GND | GND |
| 13 | CE_SENSE to R148 to F20 (pin 7) | **GND** (CR plane) |

Effects on the CR:
- R125, R148 and the ILIM_SENSE and CE_SENSE nets are deleted (netlist.py:196-197, 211). With T12 and T20 also gone, the signal nets crossing W5 fall from 9 to 7: two 3V3 feeds, STAT, CE_DRV, REL_A, REL_B and RFC_OFF.
- Six GND conductors are bonded at the CR end only. At J201 the old sense conductors end on DNP pads, so they add no second DC path into the EIB AGND (the R273 single-ground rule, :1969, is unchanged).
- Grounding pin 11 converts the old 10-11 hazard (pin 33 follows RFC_OFF) into "RFC_OFF pulled LOW, giving the FC clamp", the safe case already listed for 9-10. The 11-12, 12-13 and 13-14 pairs become GND-GND.
- Alternative: leave pins 11 and 13 NC. This is also safe, because those conductors then float at both ends. GND is preferred because it removes the two signal routes and adds a return conductor next to RFC_OFF.

The 2x5 option (a 10-way cable and J101 with an unshrouded J201 offset-mated on pins 1-10) saves about 2.5 mm of J101 length. It is not recommended, for three reasons:
- It needs a new cable assembly.
- It halves the GND conductors from four to two.
- The A.3 keying and row-shift proof (:489), which relies on the plug in socket hole 6 against a 14-pin field, would have to be re-derived. A shifted 2x5 socket can seat on J201 pins 3-12 or 5-14.

### 4. DNP vs respin

| Criterion | DNP on the fabricated EIB | Respin |
|---|---|---|
| Circuit of the kept functions | identical to the reviewed and DRC-clean board (`HANDOFF.md:9`) | must be re-verified (ERC, DRC, parity) |
| Floating or loaded fitted nodes | none (section 2) | none |
| Gain | - | about 12 fewer pads, E4/E6 removed, about 1-2 mm of board, a cleaner A.9 analog row (:1476) |
| Cost | DNP flags and doc edits | new fab, delay, a new EIB package |
| Mating | W5 14-way and J201 unchanged | same unless 2x5 (section 3) |

A respin pays off only if the EIB is respun for another reason, such as the r7-11 "merge onto the CR" option (:350). That option is now smaller to implement, but nothing in the tap review requires it.

### 5. Side effect outside the EIB: EVM placement

Fallback (iii), with the EIB at the EVM left edge, failed **only** because of E4 (82.3 mm needed against a 59 mm pickup-criterion limit) (:1197). Fallback (ii) also cited E4 (:1196). With E4 deleted, fallback (iii) may become feasible. TODO(verify: A.7 / H.23(l)): re-check E1, E2, E3, E5 and E7 against their limits.

EVM modification list:
- **EM1 (:1992):** JP17 pin 1 is no longer the E6 sense joint. Removing the shunt and JP17 pin 2 is still required.
- **EM5 (:1996):** the "E4 on the pin-1 post" clause goes. R256 and C252 stay.

### 6. B.6 rows to change

1. **U203 row (:1808) and U204 row (:1809):** mark DNP with "retired 2026-11-12, tap review". Alternatively, move them to a DNP-on-fabricated-board note.
2. **R272 and R272b row (:1799):** remove "and the U204 divider load (H.19)" and update the H.19 figures.
3. **r7 paragraph (:1821):** remove "the U203/U204 far-end senses" from the list of fail-safe arguments.
4. **ILIM levels paragraph (:1823):** remove the U203 threshold sentence. Re-state "held" without the sense pull-up term.

Fault table (:1833-1848):

5. **E2/R255/Q203 open, ribbon 7 open, E1 off (:1835):** the converter column is unchanged. Detection changes from U203 to firmware seeing no input current (pin 22 or I2C IBUS) when a release is expected. TODO: confirm that FR-08 keeps such a rule (tap review Â§5 strips FR-08(a)).
6. **Q201 drain-source short (:1838):** detection changes from U203 stuck LOW to no charge current while a release is expected.
7. **E4 sense lead off or U203 dead (:1840):** delete.
8. **E5 lead off, U201 1Y open, ribbon 5 open (:1842):** the latched FR-47(b) trip loses its input. The converter is still inhibited (safe). Detection is no charging while P5 is HIGH, as a non-latching flag.
9. **U201 1Y stuck sinking (:1843):** this is the important change. /CE is stuck LOW, and now nothing in hardware detects it. EN_CHG = 0 (FR-04 precondition) and the ILIM hold still stop charging outside the release terms. TODO(verify: SLUSDV2C, /CE and EN_CHG gating). Proposal: add a firmware plausibility check in place of FR-08(b): STAT pin 6 or I2C CHG_STAT reporting charging while P5 is LOW gives a trip.
10. **R272 and R272b both open (:1845):** /CE becomes undefined, not "pulled toward 0 V by R263". It is latent, found by T-C-05.
11. **E6 sense lead off or U204 dead (:1846):** delete.
12. **Ribbon short row (:1847):** 10-11 becomes the FC clamp (safe) with pin 11 grounded at the CR. 11-12, 12-13 and 13-14 have no effect. Delete the FR-08(a) and FR-08(b) references and the U203 6.7 mA clause.
13. **3V3 lost on the EIB (:1848):** the converter column is unchanged. In the detection column, the pin 7 and pin 33 path is removed. Only the loss of charge current remains.
14. **REGN paragraph (:1850):** `regnExpected` gating of FR-08(a) and FR-08(b) by the senses is retired. Keep it only where FR-08(d) or the new plausibility check needs it.

### 7. B.8 rows to change

- **CR "Readbacks" (:1938):** delete R125 (F13) and R148 (F20). R127 and R128 also go under the tap review (outside the EIB).
- **CR J101 (:1941):** 11 and 13 become GND (or NC). Drop "11 ILIM_SENSE; 13 CE_SENSE".
- **CR CE_DRV source:** U114 to R130 becomes CHG_ARM (pin 5) to R130. U114's fate is still to be re-derived per tap review Â§2.
- **EIB U203 (:1963), R258/R259/R260/R261 (:1964), U204 (:1965), R262/R263 (:1966):** mark DNP, or move to a "pads present, unfitted" line.
- **EIB J201 (:1969):** add "11 and 13: no fitted connection (R265 and R264 DNP); grounded at the CR end".
- **E-pad list (A.9 :1473):** E4 and E6 pads present, no lead.

### 8. Associated rows outside B.6 and B.8

- **B.7 (:1869, :1873):** remove the "CE readback on pin 7" wording.
- **B.9 (:1974-1985):** delete "the two far-end senses compared in the dangerous direction with the heartbeat timeout HB_dead". Also delete the FR-47 "unexpected /CE-sense HIGH kept as a carrier-inhibit trip" clause.
- **H rows:** retire the H.4 sense-threshold row (:3073). Recompute H.4 clamps (:3072) and H.19 /CE (:3119). Remove the R264/R265 clause from H.20 (:3126).
- **Tests:** T-B-03 (U203 ramp) retires. T-C-05 and T-C-07 (adjacent-pair sweep) and T-C-13 (J201 metering) need to be re-scoped.

