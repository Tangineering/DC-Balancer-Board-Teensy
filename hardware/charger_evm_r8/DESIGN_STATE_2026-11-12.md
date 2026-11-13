# Charger EVM r8: design state after the 2026-11-12 decisions

## 1. Purpose

This document records the operator decisions of 2026-11-12, the ramifications of the tap review, and the
decisions that remain open before the next design round. The decision records are in `decisions_2026-11-12/`. The
ramification analyses and their three independent checks are in `decisions_2026-11-12/ramifications/`.

**Status update (2026-11-12, later).** The second-round decisions (`decisions_2026-11-12/round2/`) closed every
open group of section 4. They are applied as design-document revision r9 (change rows r9-1 to r9-8), LAYOUT_DECISIONS
D-39 to D-50, the ordering BOM and the EIB DNP set. The CR netlist was regenerated: 78 parts (145 before), ERC 0
errors and 0 warnings. The stale r7-outline layout work, including `cr/interactive/`, is in `archive_r7_outline/`.
Sections 2 to 4 below are the record as it stood before the second round.

**Status update (2026-11-12, end of D-50 steps 2-4).** The section H re-run is done in
`docs/reviews/charger_eval_2026-11-05/round4/calc/r9_calc.py` (design change row r9-9). Audit run 002 is adjudicated
in `docs/reviews/charger-design/run-002-2026-11-12.md` (r9-10): 29 findings, 0 blocker, 8 major and 21 minor after
verification; no fix is applied before operator check-in 2. The new-outline generator is built (LAYOUT_DECISIONS
D-51, D-52), and `cr/geometry_check.md` passes; D-51 closes the height survey. The D.3 IO CSV rows are applied to
`references/Scale Car Teensy IO - IO - 2026-11-12.csv` (r9-11).

## 2. Decisions taken

Table 1 lists the decisions taken on 2026-11-12.

Table 1. Operator decisions of 2026-11-12.

| Area | Decision | Record |
|---|---|---|
| Outline and mounting | Plug-on CR, outline x 18.584-67, y 7-94 (MB frame); stencil and reflow assembly | Change request; `OUTLINE_CHANGE_REASSESSMENT_2026-11-12.md` |
| Vias | No via in an SMD pad first; plain unfilled via-in-pad only as a listed last resort | D-37 |
| Pack OV | Tap T22 and the BQ29200 permit removed; pack OV is firmware-only | D-38 |
| U101 | TPS26630RGER stays (0.5 mm, the one approved 0.5 mm exception); its exposed-pad vias are exempt from D-37, with window-pane stencil apertures and L4 tenting | U101 session report |
| Mating connector | Samtec SSQ-110/112-01-L-S sockets on the MB, TSW-110/112-07-L-S pins on the CR (bodies on the CR underside); CR underside 11.05 mm above the MB at a hard stop; all 22 positions; no mechanical key (the terminal blocks stop a 180-degree flip; the engagement-start height must stay below 21.70 mm); CR pins soldered while plugged | `cr_decision_mating_connector_2026-11-12.md` |
| Standoffs | None this round; the CR is held by the 22-pin friction fit | `dec_standoffs_2026-11-12.md` |
| Stack-up | L4 solid GND over the whole board, no signals or straps; VCHGOUT strap on L1 or L3 (design owner); air gap ≥ 1.5 mm; sensitive-part window y 30.8-66.86 preferred, not hard | `stackup_fabrules_decisions_2026-11-12.md` |
| Film and thermocouple | Polyimide sheet retired; MB VBT-trace thermocouple removed; T-F-16 retired (operator ruling 2026-11-12; trace rise accepted unmeasured, design document J.1 item 25) | Same file, section 3a |
| Fab rules | OSH Park-only rule file; 0.6/0.3 mm is the only via; unused inner pads removed on all THT; 6/6 mil default, 5/5 mil at necks | Same file |
| Leads | Taps go to one CR connector; W leads stay soldered on the CR as through-hole and unplug at the existing EVM terminals | Lead session (closed before it finished) |
| Taps and permit gate | 10 conductors kept (T1, T7b, T2, T5, T6, T10, T13, T16, T17, T17r), 13 removed; reduced gate release = (H1·UVB) + FCC_ON + (QUAL·FCC_OFF·¬P5), /CE = ¬P5, RFC_OFF = FCC_OFF + (H1·UVB); U104, U111, U113, U115, U121, the FCCEIL terms and EIB U203/U204/R264 removed | `cr_tap_review_2026-11-12.md` |

## 3. Ramifications of the tap review

### 3.1 Gate correctness

The re-derivation against F.3 and F.5 finds that the reduced gate keeps R3' in every operating mode, provided
firmware keeps invariant I-9 and the R5 watchdog is fitted. Five LVC packages remain (U105, U106, U107, U110, U118),
down from eleven. The single-fault picture is weaker than the gate analysis first stated. The independent checks
found the following latent single faults, which nothing now detects:

- **Gate outputs stuck HIGH.** A stuck-HIGH output of U120 (FCC_ON), U118A, U118B, U110A or U110B, or a short of
  the ILIM_REL net to 3V3, releases the converter in regen-armed cruise with the battery on the bus and /CE LOW.
  Only the VINDPM register (18.62-19.38 V) then stops a bus → charger → pack loop. In r8 the EIB far-end sense U203
  (pin 33) detected all of these.
- **The FCC_ON AND NOT FCC_OFF agreement term** (zero packages, spare U105 section 1 and U118 gate B) covers a
  stuck U120 or U119, but not a fault that drives the shared tap T5 itself, such as a T5-to-T6 (3V3) short in the
  tap connector.
- **QUAL stuck HIGH** (pin 10, or T10 shorted to T6) releases the converter indefinitely with /CE HIGH as the only
  barrier. The U111 one-shot bounded this to 0.20-0.46 s.
- **/CE stuck LOW** (U201 1Y sinking; with R263 not fitted, R272 and R272b both open leaves /CE floating). U204 detected
  this. With QUAL stuck HIGH, two latent faults give the full R3' loop.
- **A ribbon 4-5 short with pin 5 high-Z** pulls CE_DRV to about 2.3 V through the STAT pull-up, above VIH, because
  CE_DRV is no longer driven push-pull.

### 3.2 Hang defence

With the heartbeat and ARM_OK removed, the R5 MCU watchdog (pin 20, G.3) is the only defence against a hung MCU.
R5 is still future work, so a rule "no FC window before T-W-01 passes" blocks all FC charging until the watchdog
firmware and its test exist. In addition:

- a hang during qualification (QUAL HIGH) or in regen-armed Run is not bounded unless R5 applies to every Run entry;
- the G.3 short-timeout window, FR-43 and FR-27 are keyed to the deleted heartbeat and must be re-keyed;
- SLUSDV2C is inconsistent on whether the BQ25798 watchdog stops charging (STOP_WD_CHG) and on whether its expiry
  resets VREG from 8.32 V to 8.40 V (T-B-08 must settle both);
- an alternative restores a hardware hang inhibit: route WDOG1_B (pin 20) into the gate as an eleventh tap.

### 3.3 Firmware consequences

- FR-08 (a)-(c), FR-34 and FR-35 lose their inputs; the heartbeat parts of FR-27/28/42/43 and the FCCEIL parts of
  FR-07/09/17/41 go; FR-04 makes QUAL a level input.
- New requirements are proposed: a qualification time limit (T_QUAL_MAX, with the IQ_VBUS draw recorded as an R3
  exception); drop QUAL before raising P5; handle the pin-34 falling edge to post T4; gate the T3 raise on REGEN read
  back HIGH; a new no-conversion proof (d) using CHG_IIN (pin 22) plus EN read-backs.
- Proof (d) and FR-11 depend on tap T17, which is now a plug-in. An open T17 leaves pin 22 near 0 V and passes the
  proof falsely. Open-lead behaviour of T13 (pin 34) and T16 (pin 35) is also unanalysed.
- The i.MX RT1062 reset keeper on pins 5 and 10, and pin 10's role as the Teensy SPI CS0 default, need checks
  (FR-49 extension, T-D-01).
- State 98 `J` as implemented in fw v37 (REGEN + MOT_PWR from the bus) cannot convert under the reduced gate.
- These are design-document requirements; the firmware itself is not edited in this round.

### 3.4 EIB

The EIB (fab package `fab/eib_2026-11-11`) can stay as fabricated if U203, U204, C203, C204 and R258-R265 are left
unfitted and the E4/E6 leads are not fitted. Whether boards were already ordered or populated is unverified. The
J101 2 x 7 pinout stays; pins 11 and 13 can be NC or GND. Keeping U204 fitted as a build-time-only /CE check (probed
at J201.13 in T-C-05) is an option that costs no Teensy pin.

### 3.5 Parts, records and tooling

- The CR loses U104, U108, U109, U111, U113, U114, U115, U116, U121, R137 and their passives (the exact set depends
  on the gate mapping), plus 13 tap pads. The ordering BOM rows for TLV3012B (9 → 4) and SN74LVC1G123 change.
- The keep-alive option B.5 (U112) is dead as drawn, because its enable (T4) and supply (T18) are removed. DNP tier 3
  (U117 FC-current permit) loses its gate input.
- About 18 review-log dispositions in section L rest on removed parts, so the r8 final audit no longer certifies the
  design. The H calculations (`round3/calc/r3_calc.py`, `round4/calc/r7_calc.py`) must be re-run.
- `gen/layout_cr.py`, `gen/check_constraints.py`, `gen/sch.py` and LAYOUT_DECISIONS D-11, D-16, D-35 and P-03 refer
  to removed parts. The placement variants and `cr/interactive/` are stale.

## 4. Decisions still open

The open decisions fall into six groups. Each group has its own decision session.

1. **Permit-gate hardware.** The agreement term; the gate mapping (5 LVC packages or single-gate DBV parts); CE_DRV
   direct from pin 5 or buffered, and the R108 value; acceptance of the latent faults of section 3.1 as J.1 risks or
   build tests (including U204 kept as a build-time check); the J-TAP pin-order rule against T5, T6 and T10 shorts.
2. **Hang defence and the watchdog.** R5 as a precondition for FC windows only or for every Run entry; WDOG1_B into
   the gate as a hardware inhibit; the consequence that FC charging waits for R5; how the watchdog window is re-keyed.
3. **Firmware-side rules from the reduced gate.** T_QUAL_MAX and the R3 exception; the QUAL-before-P5 order; the
   pin-34 falling edge; the T3 REGEN gate; proof (d) and the T17 open-lead problem; pulls or cross-checks on pins 22,
   34 and 35; pins 5 and 10 at reset; the State 98 `J` redefinition; freed-pin modes.
4. **EIB.** Keep the fabricated EIB with DNP parts or respin; J101 pins 11 and 13; the EIB fab status.
5. **Parts and assembly (re-opened).** All-top SMT; package upsizing on the reduced parts list; DNP tiers including the
   dead keep-alive B.5 and the U117 option; silkscreen designators and the courtyard basis.
6. **Tap connector (re-opened).** The connector for 10 conductors (2 x 5, or 2 x 6 with GND guards), its family and the
   crimp tools; the T1 and T2 MB-soldered taps.

A seventh, process group is for the design owner to propose to the operator: the scope of an r9 audit pass over B.1,
F.2-F.5 and G.3, the re-run of the H calculation scripts, and the disposal of the stale layout work.
