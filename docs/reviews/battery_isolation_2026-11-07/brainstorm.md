# Battery Isolation Feasibility Study: Brainstorm, Clustering and Drops

Date: 2026-11-07. Board revision 20260622, fw v37 rev 2 (`AG105_VBATN_ISOLATED 0`).
Inputs: `facts_board.md`, `facts_ag105.md`, `facts_firmware.md`, `facts_prior.md` in this folder.

## 1. Scope

This document records every raw concept from the brainstorm round, the clustering of those concepts
into seven distinct **isolation concepts** (IC1 to IC7), and the concepts that were dropped. The
seven briefs are the input to the flesh-out and adversarial-review rounds. Nothing in this study is
ordered, desoldered or flashed.

The study goal is to keep the Ag105 as the charger and to isolate the battery during charging, so
that the Ag105 internal current sense (DS V1.1 Fig.1 p.3, Table 2 p.4) carries the pack current
again and the 2026-11-04 circulating loop (ML0227) cannot recur. The hard requirements carried from
`docs/charger_replacement_evaluation_2026-11-05.md` are regen harvesting and fuel-cell charging
(ruling 1), no circular loop and no runaway (HR3, HR4), and a fail-safe Teensy-commanded inhibit
(HR5).

## 2. Raw concepts

Table 1 lists the 21 raw concepts as they were submitted, with a one-line identity and the cluster
that absorbed each one.

| Raw concept | Identity | Cluster |
|---|---|---|
| A | Lifted VBat-, commanded low-side bypass NFET, default bonded, Teensy opens it per charge window | IC1 |
| B | Lifted VBat-, autonomous low-side ideal-diode return steering, Teensy holds steering mode for all of Run | IC2 |
| C | B plus charge-leg blocking FET, pack shunt, hardware OC latch, BQ29200 OUT actuation | IC2 (hardened variant) |
| D | No pin lift; external BMS-style CHG/DSG pair with linear charge-current limiter in the pack return | IC7 (variant b) |
| HS-1 | Spring-return DPDT relay moves both pack legs to the Ag105 battery port; D-BT-SQ retired; LM1084 diode-OR from pack side | IC6 |
| HS-2 | Pack on Ag105 Bat+/Bat-; D-BT-SQ promoted to pack-to-VBT switch; low-side sense bypass; VCHG-IN-keyed hardware veto | IC3 |
| HS-3 | Solid-state three-switch changeover with charge-pump back-to-back NFET high-side drivers | IC4 (variant) |
| HS-4 | Isolated DC-DC ahead of the Ag105; Ag105 Vin- lifted; pack never moves | IC5 |
| T1 | Return-leg Form-C relay with Schottky transfer bridge; standstill charging only | IC1 (relay implementation) |
| T2 | Solid-state two-NMOS return changeover, hardware-sequenced, gate-keyed D-BT-SQ cross-lock | IC1 (reference implementation) |
| T3 | Bistable DPDT relay; power pole steers the return, signal pole interlocks a charger enable | IC1 (relay implementation, contact-sensed interlock option) |
| T4 | Both-leg DPDT transfer to a dedicated charge harness, VBUS-fed logic with hold-up | IC6 |
| DS-1 | Direction-steered pack return (one-way charge leg and one-way discharge leg) | IC2 |
| DS-2 | Pack on Ag105 battery port, D-BT-SQ as pack-to-board switch, one-way return pair | IC3 |
| DS-3 | Whole board on Ag105 VLoad (pure Fig.4) | Dropped (section 5) |
| DS-4 | Pack on battery port plus external high-current high-side switch permitted by VLoad-present and VCHG-IN-absent | IC4 (base) |
| C1 | Return-steered sense restoration with Schottky default, VCHG-IN eFuse, pin-28 loop breaker, external watchdog | IC1 |
| C2 | Isolated DC-DC brick ahead of the Ag105, Vin- lifted | IC5 |
| C3 | Literal two-leg 3PDT normally-closed relay, VBUS-fed logic with hold-up | IC6 |
| C4 | Control: no isolation; eFuse ceiling, hardware loop breaker, OVP trip, external watchdog | IC7 (variant a) |

## 3. Clustering criteria

The clusters separate along three axes that change the safety argument, not only the parts list.

1. **Which pack leg moves.** The return-only concepts keep pack positive on VBT, so the Teensy never
   loses its supply. The battery-port concepts move pack positive to VCHG and need a new logic feed.
   The charger-input concept moves neither leg.
2. **What breaks the circulating loop.** The return-only concepts restore the sense but leave VBT
   shared between the charger output and the BT boost input, so the loop is broken only by switch
   rules (BT_BUS LOW, MOT_PWR LOW) or by an added hardware gate. The battery-port concepts break
   the loop by topology, because VBT is unsourced while charging.
3. **How the transition is commanded.** Commanded changeover (IC1), autonomous direction steering
   (IC2), module-state permit (IC4) and electromechanical transfer (IC6) fail in different ways on a
   Teensy hang or a welded or shorted switch.

## 4. Cross-cutting findings from the brainstorm

The following findings apply to more than one cluster. Each brief references them by number.

1. **X1, the balance-lead bond.** Every concept that lifts VBat- must also break J-BL pin 3, the
   second pack-negative to GND bond (facts_board fact 1). The balance-lead negative moves to the new
   pack-negative node or is removed and keyed out of the harness.
2. **X2, a blocked sense return is not an inhibit.** If the sense return is open while the Ag105 is
   powered, the module reads zero battery current and ramps its output into whatever loads VBT
   carries, which is the ML0227 mechanism. A charge-leg switch (C's Q_CHG, T2's S_CHG) is a valid
   charge inhibit only when the charger output cannot reach a loop, that is with D-BT-SQ held off or
   the charger input removed.
3. **X3, return-only concepts do not break the loop.** IC1 and IC2 bound the pack current but not
   power that circulates charger to VBT to BT boost to bus. They need a hardware gate on the
   D-BT-EN EN net (pin 28) keyed on charge-armed or VCHG-IN-present, in addition to the v38 regen
   interlock (MOT_PWR open during regen windows).
4. **X4, the common safety-layer set.** The layers of C4 (VCHG-IN eFuse ceiling, pin-28 loop breaker,
   latched OVP trip, external watchdog IC) are applicable to every concept. The control concept IC7
   is these layers alone.
5. **X5, the FC charge budget.** A 2.5 A, 2S charge needs about 23.9 W of input at the 88 % figure
   that DS p.20 gives only for 12 V in, 3S. That is about 1.5 A at 16 V, above the 1.25 A governor and
   the 1.247 A P_MAX. Every concept needs a lower Table 4 current in FC windows.
6. **X6, the regen cold-start limit.** A cold Ag105 (65-170 ms plus a 500 ms settle) misses the first
   regen pulse in every concept. A fast switch removes the switch from the critical path; it does not
   remove the charger limit.
7. **X7, battery connect or disconnect while powered.** The datasheet does not specify Ag105
   behaviour when the battery appears or disappears with input power present (facts_ag105 section 11
   item 4). Concepts that toggle the battery-port connection per event carry this as a BENCH item.
   Concepts that keep the pack permanently on the battery port (IC3, IC4 base) avoid it.
8. **X8, common bench gates.** The Ag105 sense resistance R_s (pins 14/15 to 16/17), OQ-7 (which
   RT1987 EN nets have the 10 kOhm pull-down), the pin-cut feasibility under the module, the 5 V
   logic load I_5V, the vehicle I_batt peak from the Pi bags, and the VBT capacitance total.
9. **X9, the MCU watchdog.** No concept is acceptable without either the RTWDOG or an external
   watchdog IC that removes charger input power on a hung loop.

## 5. Kept concepts

Table 2 lists the seven kept concepts. The full briefs are carried in the workflow output and are
reproduced in the flesh-out round documents.

| ID | Name | Merged from | Distinguishing property |
|---|---|---|---|
| IC1 | Commanded low-side return changeover | A, T1, T2, T3, C1 | Teensy-commanded break-before-make transfer of pack negative between GND and the Ag105 sense; bonded by default |
| IC2 | Autonomous direction-steered return | B, DS-1, C | Ideal-diode steering; charge current can only cross the sense, discharge never does; no per-event command |
| IC3 | Pack on the Ag105 battery port, D-BT-SQ as pack-to-board switch | HS-2, DS-2 | Structural loop break with the existing 8 A RT1987 and a VCHG-IN-keyed veto |
| IC4 | Pack on the battery port with a new high-current high-side switch and hardware permits | DS-4, HS-3 | Structural loop break without the 8 A limit; module-state and VCHG-IN permits independent of the Teensy |
| IC5 | Isolate the charger input (isolated DC-DC, Vin- lifted) | HS-4, C2 | Neither pack leg moves; sense regulates total charger output |
| IC6 | Literal two-leg relay transfer, standstill charging | HS-1, T4, C3 | The operator's literal request; galvanic, mechanically fail-safe; logic fed from the pack ahead of the relay |
| IC7 | Control: no isolation, external bounding | C4, D | Baseline that shows what safety is obtainable without touching the Ag105 or restoring its regulation |

## 6. Dropped concepts and sub-options

Table 3 lists the drops. A drop is recorded only for a concept that is physically incapable on the
facts or strictly dominated by a kept concept.

| Dropped item | Reason |
|---|---|
| DS-3, whole board on Ag105 VLoad | Physically incapable: the VLoad path is 4 A continuous with no overcurrent protection (DS p.19, p.20 row 6), which limits the BT channel to at most 1.85 A of bus current at the 7.4 V floor with a lossless boost, against a TPS61288 switch limit of 12 A minimum. Its useful idea, the module's own VLoad removal as an interlock, is retained as a permit in IC4, which dominates it. |
| HS-2 firmware-only regen alternative (keep BT_SEQ HIGH and rely on the reg 0x02 threshold) | Violates HR3 between regen pulses and contradicts the IC3 hardware veto; listed by its author for review only. |
| T4 / C3 VBUS-fed logic with a 4.4 mF hold-up | Strictly dominated within IC6 by the HS-1 pack-side LM1084 feed taken ahead of the relay, which keeps the Teensy on the pack in both relay positions with no dependence on an FC-only bus that purges to about 1 V. Retained only as a recorded alternative. |
| A, uncommanded-hang behaviour (bypass held OFF with no watchdog) | Superseded within IC1 by the T2 gate arrangement (S_GND pulled ON to VBT by default) plus the X9 watchdog. |

## 7. Status

The seven briefs are the input to the flesh-out round. The adversarial round should test, first,
the X3 claim against IC1 and IC2, the D-BT-SQ 8 A rating against IC3, the VLoad-unpowered deadlock
against IC4, the termination-on-total-current behaviour against IC5, and the regen (ruling 1)
failure of IC6.
