# Charger IC search for the custom charger board (2026-11-10)

## 0. Scope, evidence base and status

This document records a wide search for a charger IC to replace the Silvertel Ag105 MPPT charger (BOM `CHG`) on board rev
20260622. The charger now sits on a **custom charger board (CCB)**: one board that plugs into the 22 Ag105 through-holes on
pin headers, may extend sideways past the 32.0 x 34.8 mm footprint, and carries the charger IC, its power stage and the
hardware interlock. Reflow assembly is available, so QFN and WCSP packages are eligible. The 2026-11-05 evaluation screened
parts partly on the availability and modification of an off-the-shelf evaluation module (EVM). That constraint no longer
applies: any IC that the CCB can carry is eligible, including charge controllers with external FETs.

This document is research and documentation only. No part was ordered, no firmware was changed, and no existing charger
document was edited. The BQ25798 custom-board design that proceeds in parallel is the baseline against which every
candidate is scored.

### 0.0 Evidence base and status codes

Every candidate fact in this document is taken from a working document in
`docs/reviews/charger_ic_search_2026-11-10/`, except Table 3.2. That table was added on 2026-11-10 from third-party
datasheet mirrors and search snippets; every entry is UNVERIFIED (sources in Table 8.1 items 26-28 and section 9.3). Each
working document cites the primary datasheet by literature number and page. This document re-reads no primary datasheet;
it keeps every UNVERIFIED, U and B mark of its sources. Table 0.1 lists the source tags.

One dependency runs in the other direction. [D690] section 11.5 defers to section 5.6 of this document for the VCHG-IN
behaviour through a purge. The handover order and timing of section 5.6 are those of [EVAL] section 4.4 and [WD], and its
hold-up figures are those of the dossier quiescent-draw and capacitance rows. [SCO] Table 8 cites section 5.6 for the same
reason.

**Table 0.1.** Source tags.

| Tag | Document |
|---|---|
| [CRIT] | `reviews/charger_ic_search_2026-11-10/screening_criteria.md`: must-haves M1-M13, scored criteria S1-S16, evidence cap, decision rule, buck versus buck-boost |
| [SCR] | `reviews/charger_ic_search_2026-11-10/screening.md`: screening record, quick dismissals, finalist selection |
| [RES] | `reviews/charger_ic_search_2026-11-10/rescreen_2026-11-05_candidates.md`: re-screen of the 2026-11-05 candidates |
| [SCO] | `reviews/charger_ic_search_2026-11-10/scoring.md`: normalised scores, decision rule, sensitivity, ranked shortlist |
| [D798] | `reviews/charger_ic_search_2026-11-10/dossier_BQ25798.md` |
| [D690] | `reviews/charger_ic_search_2026-11-10/dossier_BQ25690.md` |
| [D773] | `reviews/charger_ic_search_2026-11-10/dossier_BQ25773_SMBus_twin_BQ25770G.md` |
| [D4015] | `reviews/charger_ic_search_2026-11-10/dossier_LTC4015.md` |
| [DRAA] | `reviews/charger_ic_search_2026-11-10/dossier_RAA489110_alternates_RAA489118_RAA489108_in_the_same_dossier.md` |
| [EVAL] | `charger_replacement_evaluation_2026-11-05.md` (the 2026-11-05 evaluation) |
| [WD] | `charger_bq25798_wiring_design_2026-11-05.md` (interlock functions; reference only) |
| [R6] | `reviews/charger_eval_2026-11-05/round3/review_loop.md`, review round 6 of the BQ25798 carrier design |
| [BIF] | `battery_isolation_feasibility_2026-11-07.md` |

The status codes are those of [EVAL] section 1.2: P = PROVEN_DATASHEET, C = PROVEN_CALC, B = BENCH_GATE, F = FAIL,
U = UNKNOWN or missing primary, sys = blocked at system level. "c" after a must-have identifier marks a conditional pass.
A fact taken from a product page, a distributor listing, a search snippet or recollection is marked UNVERIFIED.

### 0.1 Recommendation and ranked shortlist

**No candidate beats the BQ25798 by enough to justify a switch. The custom BQ25798 board should continue.** Three
challengers score 5.7-8.7 points above the BQ25798 on the 100-point scale of [CRIT] section 3, below the 10-point switching
margin, and none meets all four conditions of the decision rule (section 6.3). Table 0.2 gives the ranked shortlist under
the protected-standoff reading of the 35 V requirement (section 1.3). The rank follows the decision-rule outcome first.
Where totals lie within the evidence band of section 6.5 (BQ25773 and BQ25690: 0.7 points against a band of 3.0-4.0
points), the hazard comparison of section 6.4 statement 5 follows second; the weighted score is third ([SCO] section 10.1).

**Table 0.2.** Ranked shortlist.

| Rank | Part | Score | Margin over BQ25798 | Status |
|---|---|---|---|---|
| 1 | TI BQ25798 | 40.3 | - | Baseline; retained |
| 2 | TI BQ25773 (SMBus twin BQ25770G) | 49.0 | +8.7 | Alternate (provisional): conditions 1 and 4 met; condition 3 met provisionally, pending ruling R-S14 (the strict S14 reading fails it, section 6.4 statement 4); margin below 10 |
| 3 | TI BQ25690 | 48.3 | +8.0 | Alternate only if bench gate T-5.HIZ passes (condition 1 open); condition 3 provisional on R-S14 |
| 4 | ADI LTC4015 (design B) | 46.0 | +5.7 | Not eligible: charge-voltage tolerance fails M3 (+-1.25 %); no dedicated inhibit pin (M5 c) |
| 5 | Renesas RAA489110 | 35.7 | -4.7 | Below the baseline: inhibit pin defeatable by registers (M5 c); heavier I2C burden reopens R6 finding 8 |

The score order among ranks 2-4 is not significant: the three totals lie within 3.0 points of each other, inside the
evidence band of section 6.5. The recommendation rests on five reasons:

1. **The margins lie inside the evidence band, and the open items cannot decide the switch.** The open stock and price
   questions move single parts by 3.0-4.0 points, the S6 adder-counting reading by 3.3 points and the S14 reading by
   1.7 points (section 6.5; [SCO] sections 8.3, 8.4, 9). Closed adversely together, these items reduce the BQ25773 margin to
   +0.7. Across Table 6.5 the three leading challengers span +2.0 (LTC4015 B, B3) to +13.7 (BQ25773, A2), and no sign
   reverses. The BQ25773 margin stays at +8.7 under every symmetric closure of the open evidence, because every criterion
   that separates it from the BQ25798 already rests on P or C evidence. While the BQ25798 is eligible, the BQ25773, the
   only challenger that meets condition 1, reaches condition 2 only through an asymmetric bench outcome (section 6.5). The
   other routes past 10 points (B1, D3, E2, A4) leave condition 1 open or failed. The switch is therefore decided by bench
   gate S1-B4 and by the forward switching cost of section 6.5, not by the open fetches and counts.
2. **Each challenger brings a documented or bench-gated hazard.** The BQ25773 passes through a nominal 5 ms
   pre-charge-to-fast-charge transit (tTRANS_CHG; SLUSEK7 section 6.6 p.21, NOM only, shape unpublished) on burst entry from
   a drained VCHG node. Against tau_warm <= 4 ms it passes as a linear ramp (63 % at about 2.9 ms) and fails as a delay, so
   it is B on gate B4. Its fuel-cell (FC) bus draw after a loss of its input-current register reaches 1.39 A, above the 1.20
   A arm drop ([D773] sections 8.3, 11.4). The **arm drop** is the firmware raw-I_fc limit above which the charger arm signal
   P5 is dropped on the same tick ([EVAL] sections 2.4, 3.4). The BQ25798 shares this FC hazard class at 1.70-1.76 A unless
   bench gate S1-B6 shows continuous ILIM_HIZ re-sampling; its 1.15 A figure is nominal (section 6.1). The BQ25690 may not
   start a charge cycle with the pack above its recharge threshold of about 8.0-8.15 V, has no ADC, and its per-burst inhibit
   pin stops charging but not conversion ([D690] sections 8.3, 10.2, 16). The LTC4015 needs a fused bridge across the battery
   switch D-BT-SQ, which removes the hard battery disconnect ([D4015] section 2.4).
3. **No challenger simplifies the CCB.** The IC-specific interlock adder count falls to 8-10 for three challengers
   (BQ25773 8, BQ25690 9, RAA489110 about 10, against 11 for the BQ25798; [SCO] Table 6). Only the BQ25773 reaches the
   S6 = 1 band, and four contingent items would each move it out. The total CCB part count does not fall: the smallest
   challenger stage (BQ25690, about 33 parts plus 9 adders) exceeds the BQ25798 stage of 27-28 parts plus 11 adders
   ([SCO] Tables 6 and 7).
4. **Every finalist meets the HR1 input condition at the threshold floor** (>= 23 W; section 5.0, Table 5.1). The 3.10 A
   regen setting of the BQ25798 image ([WD] H.7) is a design setting conditional on the pack ruling, not a requirement. At
   an 8.4 V pack and the low tolerance corners, the BQ25690 delivers 2.62 A and the BQ25773 2.77 A, each input-limited at
   its regen ceiling minimum. The BQ25798 delivers 3.10 A at the nominal ICHG and about 2.90 A at the extrapolated ICHG low
   corner (U); a 3.32 A setting closes its gap. Neither challenger gap can close without a regen ceiling above the HR4
   hard-stop row. Every finalist still puts 16 % or more above the 18.9 W brake peak into the pack.
5. **No challenger resolves the decisive unknown.** No datasheet in the set publishes a warm-response figure, so regen
   harvesting (HR1) stays U or B for every part. Only a bench measurement resolves it.

The recommendation holds under two conditions (section 7):

- **R-M2.** The operator accepts the TPS26630 eFuse on VCHG-IN as the 35 V element, with the IC rating scored separately (the
  eFuse OVP cut-off 22.61-23.63 V and turn-off delay of at most 14 us, SLVSE94G p.6 and p.8, hold the IC pins under the 24 V
  operating maximum; bench confirmation in section 7). If the operator requires 35 V at the IC pins, the BQ25798 (30 V) is
  not eligible.
- **S1-B4.** If the BQ25798 warm-response bench gate fails while a challenger passes its equivalent gate, the BQ25798 fails
  M9 and the decision is no longer a scoring question (scenario A2 assumes that the challenger passes). If the gate fails for
  all three TI parts (scenario A1), only the LTC4015 exceeds 10 points, and it stays ineligible without rulings R-M3, R-BR
  and R-INH.

In both cases the baseline is ineligible, and one order applies (section 7, rule of succession): the BQ25773 leads while
bench gate T-5.HIZ is open; the BQ25690 leads if T-5.HIZ passes. Both TI leads deliver less than the 3.10 A image setting
at an 8.4 V pack (BQ25773 2.77 A, BQ25690 2.62 A). These shortfalls are information only unless ruling R-I3A1 makes 3.1 A
delivered a hard requirement. Under a yes ruling neither TI challenger can lead, and only the LTC4015 route (rulings R-M3,
R-BR and R-INH) or a new search remains (section 7).

Under the decision rule the search is closed except for two evidence-unresolved reserve parts and one bounded class. The
TI BQ25820 (85 V buck controller with I2C) is held at M9 U, because the figure that would reject it is illegible (section
3.3, Table 8.1 item 13). The MPS MP2769 (60 V I2C buck-boost controller) has its primary datasheet behind an MPS login, so
every must-have is U (section 3.3, Table 8.1 item 10). The 30-33 V parts re-admitted by the protected-standoff reading
have no dossier, but they cannot reach the switching margin (section 6.4). Three further reserve groups apply only if a
requirement changes or a bench gate passes: the RT9492 second source, the LT3651-8.4 and SC8802 analog-only option, and
the BQ25756 family on its warm analog inhibit W2 (section 3.3). The SY20776/SY20779 are not scorable, are likely M2
failures (25 V class, UNVERIFIED) and are not held in reserve.

---

## 1. Requirements and the screening table

### 1.1 Hard requirements carried from 2026-11-05

The five hard requirements of [EVAL] section 1.1 apply unchanged. Table 1.1 restates them.

**Table 1.1.** Hard requirements HR1-HR5 ([EVAL] section 1.1).

| ID | Requirement | Pass condition |
|---|---|---|
| HR1 | Regen harvesting | Warm response within the tau budget of [EVAL] section 3.2; input >= 23 W at the threshold for the defining 3 -> 1 m/s, 12 A brake (peak 18.9 W) |
| HR2 | FC charging | Commanded charging from VBUS in an FC window within the FC budget (governor 1.25 A, H-20 P_MAX about 1.247 A bus, OC_FC 1.4 A single sample, minus aux and traction), surviving H-20 purges |
| HR3 | No circular loop | No single fault produces a sustained bus -> charger -> pack -> BT boost -> bus current |
| HR4 | No runaway | Charge and input current bounded by a hardware ceiling plus registers; the ceiling holds after a charger POR |
| HR5 | Fail-safe hard inhibit | Teensy-commanded hard inhibit that defaults to inhibit with the Teensy unpowered, in reset, hung or with I2C dead; no autonomous charge out of POR or from stored settings |

The constraining facts of the board are the following ([CRIT] sections 1, 4; [EVAL] sections 2.5, 3.2, 3.4):

- The pack is 2S Li-ion, 7.4-8.4 V, CV 8.400 V. Pack negative is PCB GND, so input return and battery return are one node,
  and charge-current sense must be high-side or input-side. A BAT- shunt is bypassed; this was the defect behind the
  ML0227 incident of 2026-11-04.
- VCHG-IN is fed through two RT1987 ideal diodes: from VBUS (16.0 V regulated; FC mode) and from V-MOT (regen; measured up
  to 21.5 V, TL431/BSP170P clamp up to 22.28 V). The charger output reaches the pack through a third RT1987, D-BT-SQ.
- The regen path needs >= 23 W input at the threshold (HR1). The BQ25798 image sets ICHG 3.10 A for this at a 7.4 V pack
  ([WD] H.7: 23 W x 0.93 / 7.4 V, divided by 0.935 for the -6.5 % ICHG tolerance, gives 3.09 A). The setting is conditional
  on the maximum charge current of the pack ([EVAL] section 8.1 item 6). In this document the **3.1 A figure** has two
  readings, which are kept apart. M4 (section 1.3) is a capability test: the charge-current regulation range and the power
  stage of the part reach 3.1 A at an 8.4 V pack within 2 W. The **delivered charge at the threshold floor** is the
  worst-case current at an 8.4 V pack with every tolerance at its low corner and the regen VINDPM at its floor. Table 5.1
  reports it against the 3.10 A BQ25798 image setting for information; HR1 passes or fails on the input condition alone.
  Whether 3.1 A delivered at an 8.4 V pack is a hard requirement is an operator ruling (R-I3A1, Table 8.0a).
- Warm response: tau_warm <= 4 ms (10-90 % <= 9 ms; <= 2 ms at board-only capacitance) for a step from Vth - 0.5 V to
  Vth + 1 V, with no input-detect deglitch, POR or soft-start at the threshold crossing. The inhibit exit plus the warm
  response must fit the head start. The hard stop after the H1 comparator trips must complete within about 115 us
  ([EVAL] section 2.5, rows 117-194 us). A cold start (65-170 ms) never captures a burst.
- The input-voltage regulation must be settable at runtime to about 18.5-19.5 V (regen) and 13.5-15 V (FC mode), with a
  draw of 5-10 mA or less just below the threshold.
- The host interface is I2C at 3.3 V logic, 100 kHz, with charge-current telemetry at least.
- The two FC purge rulings of 2026-11-08 apply ([BIF] section 0.1). Ruling 1: no FC charging during or just before an
  H-20 purge, a preemptive share shift to the battery, and EMS-requested charging between purges. Ruling 2 (OR-SC): the
  purge predictor is taken as ideal. An unpredicted purge may collapse the bus and latch State 99, provided that no
  component is damaged on the collapse, on the fuel-cell recovery or at the next power-up. The pack may not be left in a
  hazardous configuration. The FC-mode input budget is about 1.0 A bus.

The incumbent Ag105 fails HR1 structurally at 2S and needs isolation of its VBat- terminal ([BIF], verdict).

### 1.2 Changes from the 2026-11-05 screen

The custom board changes the meaning of six 2026-11-05 requirements. Table 1.2 states each change ([CRIT] section 1.2).

**Table 1.2.** Requirements whose meaning changes on the CCB.

| Requirement | Meaning on 2026-11-05 | Meaning on the CCB |
|---|---|---|
| H8 inrush | Stock EVM input capacitance against the RT1987-ramped node | A CCB design constraint: input capacitance after DC-bias derating, plus the motherboard capacitors, must keep the D-BC-FC close current at or below 1.0 A including the 0.15 A aux load. A part fails only if its datasheet demands more capacitance than the budget allows |
| H10 thermal / mechanical | Loss <= 2 W and an off-board mount on leads | Loss <= 2 W kept; the power stage, interlock and headers must fit one CCB with the IC heat path in CCB copper. Lead-length limits (R6 findings 13, 14) no longer apply |
| H11 availability | EVM stock | Stock of the IC and of its critical power-stage parts at an authorised source |
| EVM modifications | Mods M1-M11, EM1-EM4 and the EVM interface board | Schematic choices. A stock-EVM defect is no penalty; a datasheet-level property (for example a register that defeats a pin) still is |
| HR4 hardware ceiling | Mode-switched ILIM_HIZ divider on the EVM | The ceiling may come from the IC (ILIM pin, sense-resistor full scale) or from a CCB current regulator; the IC route scores higher |
| H12 telemetry | IC ADC only | IC ADC, or a CCB current monitor on the same I2C bus; the IC route scores higher |

The interlock functions that every charger must support are system-level and identical for every candidate: the H1
V-MOT/VBUS comparator, the H2 FC-window permit with BT_ACT, the C7 qualifier, the `CHG_QUAL AND NOT P5` release term, the
OVN pack-OV term from the BQ29200 OUT, the eFuse on VCHG-IN, the mode-switched input ceiling keyed to FCC_net, and the MCU
watchdog ([WD]; [EVAL] section 2.6). The screen counts only the IC-specific hardware that connects each candidate to these
functions.

### 1.3 Must-haves

A candidate that fails a must-have on a documented contrary fact is rejected. A must-have whose evidence is U or B passes
conditionally and becomes a named bench gate. Table 1.3 lists the must-haves ([CRIT] section 2).

**Table 1.3.** Must-haves.

| ID | Requirement | Pass condition |
|---|---|---|
| M1 | Common ground | Input and battery returns are one node; charge sense high-side or input-side; no element in either return |
| M2 | Input rating | Absolute maximum >= 35 V on every pin that sees VCHG-IN; operating range covers 22.28 V; no OVP drop-out at or below 22.28 V |
| M3 | 2S profile | CV settable to 8.400 V with +-1.0 % total error over temperature; pre-charge, CC, CV and termination |
| M4 | Charge current | >= 3.1 A at an 8.4 V pack with <= 2 W loss on the CCB |
| M5 | Hard inhibit pin | A pin that stops conversion, including pre-charge and trickle, from POR without I2C; a defeating register bit is acceptable only if its POR value enables the pin and readback can hold it |
| M6 | Fail-safe default | With the inhibit pin biased to inhibit by a resistor, no charge with the Teensy unpowered, in reset, hung or with I2C dead; no non-volatile setting enables autonomous charge |
| M7 | Hardware current ceiling | Input or charge ceiling set by hardware, active from POR, not raisable by any register write |
| M8 | Runtime input-voltage regulation | IC loop settable at runtime to 13.5-15 V and 18.5-19.5 V; regulates current to zero below the threshold without shutdown; draw <= 10 mA |
| M9 | No cold restart in the regen path | Neither the threshold crossing nor the per-burst inhibit exit re-runs a deglitch, POR or soft-start of 10 ms or longer |
| M10 | Host interface | I2C or SMBus at 100 kHz, 3.3 V-compatible, no back-powering of SDA/SCL when unpowered |
| M11 | Charge-current telemetry | Readable at >= 50 Hz by the IC ADC or a CCB monitor |
| M12 | Runtime current control | Input-current limit and charge current settable at runtime (the FC-window governor writes at 50 Hz) |
| M13 | Lifecycle | Active |

The 35 V figure of M2 is stricter than the 2026-11-05 H6 rule (30 V minimum, 36 V preferred). The BQ25798 (30 V on VAC1,
VAC2, VBUS, PMID and SW1; SLUSDV2C p.7) fails M2 as written. The screen ([SCR] section 1.2) rejected 30-33 V parts on
the strict reading. The scoring ([SCO]) applies one rule to every scored part, the **protected-standoff reading**: M2 is met at the CCB input when the TPS26630 eFuse (60 V part, OVP cut-off
22.61-23.63 V, [D798] section 2.2) is the 35 V element and the IC operating range covers 22.28 V without an OVP drop-out.
The IC absolute maximum is then scored in S9 only ([SCO] section 2.1). This reading rests on the TPS26630 OVP response. The
OVP switch turn-off delay OVP_tOFF(dly) is 8.5/11/14 us (SLVSE94G section 6.6 p.8; URL confirmed). At the 4.30 V/ms regen
slope ([EVAL] section 2.5) the eFuse output therefore holds at most 0.06 V above the cut-off, so the BQ25798 pins stay at or
below 23.7 V. This level is under the 24 V recommended VBUS maximum and the 25.2 V VBUS_OVP minimum (SLUSDV2C section 6.3
p.7, section 6.5 p.9; [D798] section 3). The output overshoot during the turn-off delay remains a bench item (section 7,
condition 1). The strict reading, in which the IC pins must reach 35 V, is evaluated in section 6.4; the choice is operator
ruling R-M2.

The protected-standoff reading has two further consequences ([D798] section 3). First, the eFuse OVP minimum, 22.61 V, is
0.33 V (1.5 %) above the 22.28 V clamp maximum ([WD] B.4, H.5). A V-MOT excursion above 22.61 V for more than 8.5-14 us
opens the eFuse (SLVSE94G p.8). VCHG-IN then collapses, and the charger restarts cold once V-MOT falls below 21.0-22.2 V:
eFuse turn-on about 1.2 ms, dVdT ramp about 7.5 ms (SLVSE94G p.8-9, C(dVdT) 22 nF), then the charger cold start of
Table 5.2 (BQ25798 about 190 ms in total). M9 is therefore met only while V-MOT stays below 22.61 V; the peak above the
VESC cut is unmeasured ([WD] T-E-03, [EVAL] M-R0). Second, the [EVAL] section 3.2 lever "raise the VESC cut-off to about
23-24 V" is not available under this reading. The cut-off must stay below 22.61 V with the fitted divider, and below about
22.9 V with any divider whose OVP maximum stays under the BQ25798 24 V operating limit ([WD] T-E-03).

### 1.4 Scored criteria

Each candidate that passes the must-haves is scored 0-3 on sixteen criteria. The weighted score is the sum of
weight x score / 3, with a maximum of 100. Table 1.4 summarises the criteria; [CRIT] section 3.1 gives the full anchors.

**Table 1.4.** Scored criteria ([CRIT] section 3.1).

| ID | Criterion | Weight | Score 3 anchor (summary) |
|---|---|---|---|
| S1 | Warm response and inhibit-exit path | 15 | Documented warm exit < 1 ms and a published loop step response consistent with tau <= 4 ms |
| S2 | Intrinsic fail-safe POR | 10 | No charge at POR and the POR input threshold above 22.28 V |
| S3 | Hardware ceiling quality | 8 | IC ceiling switchable by one resistor and one switch, re-sampled continuously, published accuracy |
| S4 | Input threshold quality | 8 | Step <= 100 mV, +-2 % at 18-19 V, documented survival across inhibit exit, dips and watchdog |
| S5 | Inhibit latency | 7 | Documented converter-off within 115 us at the pin |
| S6 | IC-specific interlock adders | 10 | <= 2 adder parts (0 = more than 8) |
| S7 | Telemetry | 5 | IC ADC for charge current, input current and input voltage with published accuracy, <= 20 ms |
| S8 | FC-mode fitness | 6 | Input-limit step <= 50 mA, CV +-0.5 %, programmable termination, published input-current accuracy at >= 12 V |
| S9 | Rating margin | 4 | Absolute maximum >= 60 V (0 = 35-37 V or below) |
| S10 | Layout difficulty | 7 | Integrated buck, leaded or 0.5 mm-pitch package, published reference layout (0 = external-FET buck-boost) |
| S11 | Package | 3 | Leaded or QFN at >= 0.65 mm pitch |
| S12 | Stock | 5 | >= 1000 units at two or more authorised sources |
| S13 | Cost (IC plus power stage) | 2 | < USD 15 per board |
| S14 | Round-6 findings | 5 | Net closes >= 1 IC-dependent R6 finding |
| S15 | Input capacitance and inrush | 3 | Fits the H8 budget with >= 30 % margin |
| S16 | Topology barrier | 2 | Buck with a documented headroom comparator that stops conversion below VBAT plus a margin |

The score of a criterion is capped by its evidence: P or C has no cap, B caps at 2, and U or UNVERIFIED caps at 1
([CRIT] section 3.2). This rule prevents a well-documented part from losing to a part whose datasheet is silent.

### 1.5 Decision rule

A challenger is recommended over the BQ25798 only if all four conditions hold ([CRIT] section 3.5):

1. It passes every must-have, and none of its conditional passes concerns M5, M6 or M7 where the BQ25798 has P evidence.
2. Its weighted score exceeds the BQ25798 score by at least 10 points.
3. It reopens no IC-dependent round-6 finding of major severity (R6 findings 1, 8 and 10).
4. Its S1 score is at least the BQ25798 S1 score.

A challenger that meets conditions 1, 3 and 4 with a margin below 10 points is recorded as the alternate. Section 6.5 gives
the basis of the 10-point margin.

---

## 2. Buck versus buck-boost

### 2.1 Question

A buck converter charges only while its input exceeds its output by the dropout headroom. This section finds the lowest
VCHG-IN at which charging is required, the highest charger output voltage and the worst-case buck headroom, and lists the
cases that would need boost ([CRIT] section 4).

### 2.2 Highest charger output voltage

The charger regulates VCHG, the input side of D-BT-SQ. During CC the pack is below CV, so the charger output stays at or
below its CV setpoint; the D-BT-SQ and lead drops only lengthen the CV phase. The highest charger output voltage is
**8.484 V** at the M3 limit (+1.0 % on 8.400 V), and 8.455 V for the BQ25798 (-0.25/+0.65 %, [EVAL] section 3.4). The charge
current used for headroom is 3.21 A (3.10 A plus the +3.5 % ICHG tolerance, [WD] H.11).

### 2.3 Buck headroom

The headroom model is VIN >= (VOUT + I x R_internal) / D_max, with an assumed R_internal of 100 mOhm at 3.21 A (0.32 V)
where the part is not selected. Table 2.1 gives the required input for four headroom models ([CRIT] section 4.3).

**Table 2.1.** Required VIN at 8.484 V out and 3.21 A.

| Headroom model | Required VIN | Source |
|---|---|---|
| D_max 98.4 % | 8.95 V | LTC4015 Rev B p.7, via the round-2 dossier |
| D_max 95 % (assumed generic) | 9.27 V | Assumption |
| VIN >= VBAT + about 1 V | 9.48 V | BQ24650 SLUU444A p.3, via the round-2 dossier |
| VIN > VBAT + VHDRM 2.4 V | **10.88 V** | MP2759 DS Rev 1.0 p.6, via the round-2 dossier |

The worst case, 10.88 V, is the buck feasibility floor. For the BQ25798, the buck-path resistance is RSNS + RQ1 + RQ4 +
RBATFET = 60 mOhm typical plus the inductor DCR, a drop of 0.22 V at 3.21 A with an assumed 10 mOhm DCR ([D798] section 2.1),
inside the 100 mOhm assumption.

### 2.4 Lowest input at which charging is required

Table 2.2 gives the lowest VCHG-IN in each mode and the margin over 10.88 V ([CRIT] section 4.4).

**Table 2.2.** Lowest charging input per mode.

| Mode | Lowest VCHG-IN | Derivation | Margin over 10.88 V |
|---|---|---|---|
| FC charging, nominal | 15.57 V | VBUS 16.0 V nominal, 15.6 V loaded sag, D-BC-FC drop 35 mV (RT1987 DS-00 section 17.6) | 4.69 V (43 %) |
| FC charging, threshold floor | 13.14 V | FC-mode VINDPM 13.5 V at -2.6 %, the BQ25798 VINDPM tolerance interpolated at 13.5 V ([EVAL] section 3.4, threshold row); below this value the input loop takes charge current to zero | 2.26 V (21 %) |
| Regen | 18.13 V | Regen VINDPM 18.5 V at -2 % (bottom of the H4 range, conservative for headroom; the design setting is 19.0 V, section 5.0); H1 fall trip >= 16.62 V | 7.25 V (67 %) |
| Bus UV limit | 12.0 V | `LIMIT_V_BUS_MIN`; a fault point, not a charging point | 1.12 V |

The lowest input-to-output ratio at which charging is required is 13.14 / 8.484 = 1.55, a duty cycle of about 0.67 with the
assumed internal drop. A buck covers the full operating envelope with at least 2.26 V of margin over the most pessimistic
headroom model.

The 13.14 V floor uses the BQ25798 tolerance. The FC-mode floor of each finalist depends on its own VINDPM tolerance at about
13.5 V. Table 2.2a gives the per-part floor. The lowest value, 13.10 V, leaves 2.22 V over the 10.88 V buck floor, so the
conclusion of section 2.6 does not depend on the part.

**Table 2.2a.** FC-mode threshold floor per part.

| Part | FC setting and tolerance at about 13.5 V | Floor | Source |
|---|---|---|---|
| BQ25798 | 13.5 V, +-2.6 % interpolated | 13.14 V | [EVAL] section 3.4 |
| BQ25690 | 13.50 V, +-2 % extrapolated between the 12 V and 20 V specification points | 13.23 V | [D690] section 6.1 (FC row) |
| BQ25773 | 13.5 V; +-1 % is published at 18 V only; bench gate B1 admits +-3 % at 13.5 V | 13.10 V at the B1 limit (TODO(verify: SLUSEK7, VINDPM accuracy at 13.5 V)) | [D773] section 4 (HR2 row), section 15.1 (gate B1) |
| LTC4015 | UVCL code 189, 14.04 V nominal; tolerance at this code not computed | TODO(verify: 4015fb UVCL accuracy) | [D4015] section 4 (HR2 row) |
| RAA489110 | 13.568 V (code 106, 128 mV step); relative error of the 4.096 V row (-2.8 %); accuracy at 13-20 V unpublished | 13.18 V (C) | [DRAA] section 6 (VIN register table) |

Note that no tolerance in Table 2.2a is a published specification at 13.5 V: each is interpolated, extrapolated, derived from another code or a bench limit.

### 2.5 Low-input states and cases that would need boost

In every low-input state of the board, charging is forbidden or useless: staged bring-up P0 (bus floor 5.0 V, VCHG-IN
normally unpowered), a bus fed through a disabled TPS61288 body diode (a pack -> bus -> charger -> pack circulation), an H-20
purge collapse, and a latched UV_BUS ([CRIT] section 4.5). A buck converter cannot charge unless VIN exceeds VBAT plus its
headroom, which is about 7.5-10.9 V over the 7.4-8.484 V pack range (LTC4015: VBAT + 0.14-0.25 V, 4015fb p.4). No register
write or charger POR can lower this floor. The floor blocks the passthrough-bus circulation, because that bus lies below
VBAT. In bring-up P0 the precharged bus can exceed this floor, so the absence of charge in P0 relies on FC_CHARGE_ENABLE and
REGEN_ENABLE being LOW. A buck-boost converter removes this floor and relies on its threshold register and on the interlock.

In regen-armed cruise, VCHG (the D-BT-SQ input, not VCHG-IN) decays below the RT1987 UVLO in 0.17-0.78 s ([EVAL] section
0.1a). The next burst then pays tD_ON 8 ms plus tON of about 1.9 ms against the tau_warm <= 4 ms warm-response budget,
for every part (P1, S1-B7, T-B-09; [D798] section 8). The buck-floor argument does not apply to this node.

Table 2.3 lists the cases that would need boost ([CRIT] section 4.6).

**Table 2.3.** Cases that would need boost.

| Case | Input range | Buck feasible | Status on board rev 20260622 |
|---|---|---|---|
| Direct charging from the H-20 stack | About 7.8 V at 2.6 A loaded (H-20 brochure figure; TODO(verify: H-20 datasheet)); purges to about 1 V | No | Not possible: no CCB pad carries the stack voltage; needs a motherboard re-spin |
| 3S pack | CV 12.6 V; required VIN 13.7-15.1 V | Marginal (0.5-1.9 V from the loaded bus; fails at the 13.14 V FC floor) | Out of scope: the pack is 2S by operator ruling of 2026-07-10 |
| 4S pack | CV 16.8 V, above the 16.0 V bus | No | Out of scope |
| Charging during bring-up or from a low bus | 5-10 V | No | Not wanted (section 2.5, first paragraph) |

### 2.6 Conclusion

**A buck charger is sufficient.** The lowest input at which charging is required is 13.14 V, and the worst-case buck
requirement is 10.88 V at 8.484 V out and 3.21 A, a margin of 2.26 V (21 %). Regen inputs (>= 18.13 V) have 7.25 V of
margin. No 2S operating mode needs boost; the cases that would need it (direct-stack charging, a 4S pack) need a
motherboard re-spin first.

Buck-boost parts stay eligible, because a buck-boost IC operates in buck mode across this envelope; the BQ25798 baseline is
one. A buck-boost earns no credit for its boost capability. A buck earns the S16 credit for its hardware no-charge floor
(VIN > VBAT plus headroom), which makes the passthrough-bus circulation, where VIN < VBAT, physically impossible independent
of registers and of the interlock. However,
the buck class produced only one finalist with I2C (the LTC4015, section 5.4), so the S16 credit did not decide the ranking.
A 3S pack is marginal on a buck and is recorded as a re-spin trigger, not as a screening requirement.

Each finalist must also meet a minimum on-time at the lowest duty cycle in the envelope, and its buck-path resistance must
stay inside the 100 mOhm assumption of section 2.3 ([CRIT] section 4.8 items 2 and 4). The duty band 0.13-0.27 is the
charger output voltage divided by the maximum input (22.28 V): about 6.0 V at a pre-charge pack gives 6.0 / 22.28 = 0.27,
and a VCHG node held near 3 V behind D-BT-SQ gives 3 / 22.28 = 0.13. An NVDC part regulates SYS at or above its minimum
system voltage, so its buck duty cannot fall below VSYSMIN / 22.28. Table 2.4 gives the result per part.

**Table 2.4.** Minimum on-time and buck-path resistance per finalist.

| Part | Lowest duty in the envelope | Minimum on-time | Buck-path resistance at 3.21 A | Source |
|---|---|---|---|---|
| BQ25798 | >= 0.32 (NVDC, VSYSMIN 7.12-7.52 V); 427 ns at 750 kHz | Not specified; not limiting at 427 ns | RSNS + RQ1 + RQ4 + RBATFET = 60 mOhm typical plus DCR; 0.22 V with 10 mOhm DCR | [D798] sections 2.1, 15.1 item 4 |
| BQ25690 | >= 0.28 (NVDC, VSYSMIN 6.2 V at 2S; 6.2 / 22.28, C) | Not stated in [D690]; TODO(verify: SLUSFN4A) | Q1 + Q4 = 74 mOhm typical (134 mOhm maximum) + BATFET 3.7 mOhm + RBAT_SNS 10 mOhm + RAC_SNS 10 mOhm = 97.7 mOhm typical before DCR; 107.7 mOhm with an assumed 10 mOhm DCR (SRP5050FA DCR TODO(verify: Bourns SRP5050FA datasheet)); above 100 mOhm. Not limiting (buck-boost): at the maximum values, Q1 + Q4 134 mOhm + BATFET 3.7 mOhm + shunts 20 mOhm + an assumed worst-case DCR of 74 mOhm (TODO(verify: Bourns SRP5050FA datasheet)) = 232 mOhm, and (8.484 + 3.21 x 0.232) / 0.95 = 9.71 V | [D690] sections 11.2, 6.3 (VSYSMIN row) |
| BQ25773 | >= 0.30 (VSYS_MIN 6.6 V); 493 ns at 600 kHz | Not published; TODO(verify: SLUSEK7) | External FETs; BATFET and RSR add 0.10 W at 3.2 A (about 10 mOhm); RAC 10 mOhm | [D773] sections 11.2, 12.1 (minimum-duty row) |
| LTC4015 | 0.135 (3 V / 22.28 V); 270 ns at 500 kHz | 140 ns typical (EC), about 85 ns (applications text): no cycle skipping | 70 mOhm (top FET 10, DCR 25, RSNSB 10, RSNSI 20, INFET 5; assumed parts); VIN,min 8.85 V | [D4015] section 11.1 (4015fb p.7, p.45) |
| RAA489110 | NVDC; MinSystemVoltage-dependent, not computed in [DRAA] | Not stated in [DRAA]; TODO(verify: R16DS0212EU0202) | Loss-model parts: Q1 8, Q4 5, Q5 5 mOhm, DCR 12 mOhm (assumed, A) | [DRAA] section 11.2 |

The BQ25798 and the LTC4015 stay inside the 100 mOhm assumption at the typical values. The BQ25690 exceeds it once the
inductor DCR is included (97.7 mOhm before DCR, 107.7 mOhm with an assumed 10 mOhm DCR). However, it is a buck-boost, and its
worst-case required input of 9.71 V stays below the 10.88 V floor. The minimum on-time is open for the BQ25690, the BQ25773
and the RAA489110. The NVDC duty floor of the BQ25690 and the BQ25773 (>= 0.28) makes a limit unlikely at their switching
frequencies, but this is not confirmed.

---

## 3. Search coverage

### 3.1 Vendors and method

The search covered TI, ADI (Linear Technology and Maxim), MPS, Richtek, Renesas (including Intersil), onsemi, ST, NXP,
Microchip, Southchip, Silergy, SG Micro, Halo, Injoinic, ETA, Awinic and Infineon, plus a check for qualifying parts at
Nuvolta, Cellwise, Chipown, Joulwatt, Hynetek, Analogy and ConvenientPower ([SCR] sections 2, 3). It included integrated
chargers, external-FET charge controllers, standalone resistor-programmed chargers, and two composite architectures (a
charge controller driving an external DC/DC, and a discrete buck with op-amp CC/CV/VINDPM loops and an I2C monitor).

The must-haves were applied in four strict readings ([SCR] section 1.2):

1. M2 judges only the pins that see VCHG-IN, the switch node and the bootstrap pins.
2. M9 applies to the per-burst inhibit that H1 drives; a part whose only pin-level inhibit has a documented restart of
   10 ms or longer fails, even if its input loop is warm.
3. A CCB current monitor satisfies M11 but not M10 or M12, because the FC-window governor writes a continuous input limit at
   50 Hz.
4. The M8 input-voltage loop must be in the charger IC.

### 3.2 Number of parts screened

The screen covered four groups of parts:

- 31 entries screened in full against M1-M13, covering about 40 part numbers including siblings ([SCR] section 2.1);
- 8 entries of the 2026-11-05 candidate set that the screen re-checked and kept rejected or unchanged ([SCR] section 2.2);
- the 10 round-2 candidates and the round-1 rejection list of the 2026-11-05 evaluation, re-screened for form-factor
  reasons (section 4, Tables 4.1 and 4.2);
- about 180 part numbers dismissed on a single must-have or on scope ([SCR] section 3).

### 3.3 Rejections of the full screen

Table 3.1 summarises the rejections of the full screen by the decisive must-have. Most rejections rest on a primary-read
fact cited by literature number and page. Three rejected or held entries do not: the BQ25822 and LT8705/LT8705A rejections
are UNVERIFIED (primary not read or blocked), and the BQ25820 is held at M9 U because its decisive figure is illegible. The
two Not-scorable entries (MP2769, SY20776/SY20779) also have no primary read and are not rejected. The primary
citations in [SCR] sections 1.3, 2 and 3 are the record of the sweeps; the downloaded sweep material is not retained in
the repository.

**Table 3.1.** Full-screen rejections ([SCR] section 2.1).

| Decisive failure | Parts | Primary basis |
|---|---|---|
| M2 (30-32 V input; strict reading, re-admitted to scoring under section 1.3 and bounded in section 6.4) | RT9492, RT9490S/RT9490, RT9478M, SGM41575 | RT9492_DS-05 sections 12-13; RT9490S_DS-00 sections 11-12; RT9478M_DS-01 sections 10-11; SGM41575 REV A.2 |
| M9 (cold pin inhibit) | BQ25756/BQ25756E/BQ25750 and the same-core BQ25856-Q1 (about 40 ms compensation toggle at startup, SLUSEN5A p.21, SLUSFH5A section 7.3.3.3 p.22, [SCR] rows 9 and 9a; W2 held in reserve below), SC8815A/SC8815 (PSTOP 220-330 ms, SC8815A DS V1.1.0 p.12), SC8813 (PSTOP 220 ms, p.11), LT8491 (SHDN exit boots from EEPROM, Rev 0 p.18-19) | As listed |
| M9 U, held in reserve | BQ25820: the /CE-to-current time (about 120-160 ms, SLUSFN3B Fig 8-7 p.67) rests on an illegible time base and is UNVERIFIED. The 12 ms ACUV/ACOV deglitch (EC p.15) applies to a threshold crossing of the ACUV comparator, not to the per-burst inhibit. ILIM_HIZ HIZ turns REGN off (p.24), so ILIM_HIZ is a cold stop; this alone does not decide M9, because /CE is a second inhibit pin | SLUSFN3B p.15, p.24, p.67 (Table 8.1 item 13) |
| M9 F expected, UNVERIFIED | BQ25822 (same core as the BQ25820; SLUSG44A Fig 7-6 not read) | None read (Table 8.1) |
| M10/M12 (no I2C) | SC8802, LT3651-8.4, LTC4020, LTC4000/LTC4000-1, MAX17703, MP2759A, LTC4013, ISL81601 | SC8802 DS p.3-4; 36518284fa p.7-8; 4020fd p.8-9; 4000fb p.1, p.8-10; 40001fa p.1; 19-100908 Rev 0 p.3-5; MP2759A DS Rev 1.0; 4013fa p.12; FN9299 Rev 3.1 p.11-12 |
| M10 F, UNVERIFIED | LT8705/LT8705A (80 V buck-boost voltage controller, not a charger; primary blocked) | None read (Table 8.1) |
| M4 (current) | MP2759A ("up to 3A", DS Rev 1.0 p.14-15) | As listed |
| M5 (no inhibit pin) | LTC4162-L (no inhibit pin and no UVCL feedback pin; every new charge cycle runs a 2-4 s battery detection) | LTC4162-L Rev A p.21, p.23, p.27 |
| M7 (no firmware-independent ceiling) | MCP19118/MCP19119 | DS20005350A section 4.1 |
| M8 (no IC input loop) | Discrete buck with op-amp loops and an I2C monitor | [SCR] section 1.2 reading 4 |
| Not scorable | MP2769 (primary behind an MPS login), SY20776/SY20779 (Silergy pages fail) | Section 8.3 |

Five parts or part groups are held in reserve with a named promotion condition ([SCR] section 4.4):

- the BQ25820, if a legible SLUSFN3B Fig 8-7 shows a /CE-to-current time below 10 ms (or a primary-backed warm analog
  inhibit exists), and an input-capacitance scheme meets its >= 80 uF minimum. The BQ25820 is the strongest buck with I2C in
  the sweep (85 V, 16-bit ADC) and the only buck other than the LTC4015 that could earn the S16 credit. If the hand fetch
  clears M9, it needs a dossier before the recommendation of section 7 can be treated as complete;
- the RT9492, as a functional (not pin-compatible) second source of the BQ25798;
- the LT3651-8.4 and the SC8802, for an analog-only architecture if the operator relaxes M10/M12;
- the MP2769, if its datasheet shows a pin-set input ceiling and a non-charging POR;
- the BQ25756 (with the BQ25756E and the automotive BQ25856-Q1, SLUSFH5A), if the W2 analog warm inhibit passes bench gate
  B10 on an EVM and an input-capacitance scheme meets its >= 80 uF minimum; until then M9 stands at F on the pin stops and
  U on W2 (Table 4.1; [SCR] section 4.4).

### 3.4 Quick dismissals

The quick dismissals fall into five classes ([SCR] section 3):

- **Input rating below 35 V (M2, strict reading; the 30-33 V parts are bounded in section 6.4):** the TI notebook and NVDC class (BQ25713(B), BQ25710, BQ25700A, BQ25703A, BQ25720,
  BQ25723, BQ25731, BQ24725A, BQ24735, BQ24780S, BQ24800, BQ24171, BQ24172), the BQ2579x/BQ2567x family, the TI standalone
  BQ246xx and BQ2530x parts, the 28-30 V ADI/Maxim, MPS, Renesas (ISL9241, ISL9238/C, ISL9237) and Southchip classes, and
  the Injoinic power-bank SoCs.
- **Wrong cell count or topology:** 1S parts from every vendor, 2S boost-from-5 V parts (BQ25883, BQ25887, MP2672(A),
  MP2639A/C), lead-acid and supercapacitor parts, and converters that are not chargers.
- **Charge current below 3.1 A (M4):** for example LT3652HV, LT3650-8.4, LTC4121 and the 2 A MPS and Silergy parts.
- **Lifecycle (M13):** parts listed as obsolete or NRND, for example NCP1871, MP2618 and the ST PM661x class (UNVERIFIED).
- **No datasheet located:** TI part numbers whose ti.com/lit/ds/symlink form returns HTTP 404 with and without the -q1
  suffix (BQ25770 non-G, BQ25680, BQ25821, BQ25823, BQ25855, BQ25771/2/4; not located, UNVERIFIED). The BQ25856-Q1
  (SLUSFH5A, October 2024) was located under its orderable suffix. It is a BQ25756-family buck-boost controller (85 V
  absolute maximum, 4.4-70 V operating, I2C, 0.4-20 A) with the same 40 ms start-up compensation toggle (SLUSFH5A section
  7.3.3.3 p.22) and the same 80 uF minimum input capacitance (p.65). Its /CE edge precedes charge current by about 92 ms
  (72-112 ms; Fig 8-7 p.66, 40 ms/div, figure reading). It fails M9 with the BQ25756 ([SCR] section 2.1 row 9a).

Infineon offers no standalone multi-cell Li-ion charger IC. Dismissals that rest on a secondary source are marked
UNVERIFIED in [SCR]; no such part was a candidate for a finalist position.

Three vendor groups and one ADI family were not in the original sweep. Table 3.2 closes them on secondary evidence only;
every entry is UNVERIFIED, and none changes the shortlist unless a primary contradicts the rating shown.

**Table 3.2.** Vendors and parts added after the sweep (all UNVERIFIED).

| Vendor or family | Part | Basis | Outcome |
|---|---|---|---|
| ROHM | BD99954GW / BD99954MWV (1-4 cell buck-boost charger with I2C/SMBus) | Third-party mirror of the datasheet: VBUS, VCC, SRP/SRN, ACP/ACN and BATT -0.3 to 28 V absolute maximum; 3.8-25 V operating (search snippet, 2026-11-10; table extraction garbled) | M2 F (28 V class). TODO(verify: ROHM bd99954xxx-e.pdf, absolute maximum table) |
| ADI (Linear) | LTC4100 (SMBus smart-battery charger controller) | Search snippets: 28 V appears as the DCIN operating condition; the absolute maximum was not seen | M2 F expected (28 V class). TODO(verify: LTC4100 data sheet) |
| ADI (Linear) | LTC4101 (SMBus smart-battery charger controller) | Search snippet: DCIN, CLP, CLN 32 V absolute maximum | M2 F (32 V). TODO(verify: LTC4101 data sheet) |
| Diodes Inc | No multi-cell switching charger with I2C and a 35 V rating identified | Not swept against a parametric table | Coverage gap; recorded as an open item (Table 8.1) |
| Toshiba | No multi-cell switching charger with I2C identified | Not swept; named only in the 2026-11-05 round-1 search item | Coverage gap; recorded as an open item (Table 8.1) |

### 3.5 Finalists

Four parts survived the screen as finalists ([SCR] section 4.2). They represent three mechanism classes from three
vendors:

- TI BQ25690: integrated 4-switch buck-boost with external sense resistors;
- TI BQ25773 (SMBus twin BQ25770G): external-FET quasi dual-phase NVDC buck-boost controller;
- ADI LTC4015: external-FET synchronous buck controller with I2C, under a declared M3 exception;
- Renesas RAA489110 (alternates RAA489118, RAA489108): external-FET NVDC buck-boost controller with a battery-FET inhibit.

No integrated buck with I2C and a 35 V rating survived the screen, and no controller-plus-monitor architecture passes M8
and M10.

---

## 4. Re-screen of the 2026-11-05 candidates

Each 2026-11-05 candidate was re-screened for the CCB by separating **form-factor reasons** (EVM availability or stock, EVM
modifications, EVM input capacitance, EVM pull-up rails and jumper defaults, off-board mounting) from **IC-intrinsic
reasons** (telemetry, restart and detection behaviour, VINDPM ceiling and POR behaviour, sense location, rating, current
capability, watchdog). Form-factor reasons are void on the CCB; a part reopens only when its rejection rested mainly on them
([RES] sections 0.1, 0.4). Table 4.1 gives the outcome.

**Table 4.1.** Re-screen of the 2026-11-05 candidates ([RES] section 2).

| Part | 2026-11-05 status | Rejection or downgrade rested on | New status |
|---|---|---|---|
| BQ25798 | Chosen | Kept on intrinsic merit; EVM conditions void on the CCB | Baseline; fails strict M2 (30 V) |
| BQ25713 | Runner-up | IC-intrinsic: VINDPM ceiling 19.52 V (SLUSD83C p.12), VINDPM retention across Hi-Z exit undocumented, AUTO_WAKEUP_EN = 1 at POR; 30 V | Unchanged; M2 F as written |
| BQ25773 | Alternate; round 1 "refuted (practical)" | **Form-factor**: "16 A-class over-design", JP4 at 4S, 167.6 uF EVM input capacitance, EVM pull-up rail | **Reopened as finalist** |
| BQ25720 | "Adds nothing" | IC-intrinsic: same 19.52 V ceiling as the BQ25713; 32 V | Unchanged reject |
| BQ25731 | "Adds nothing" | Round-1 EVM stock reason void; round-2 reason intrinsic (19.52 V ceiling, watchdog loads 256 mA, 32 V) | Unchanged reject |
| LTC4015 | Plausible; round 1 rank 1 | **Mostly form-factor**: DC2039A 120 uF electrolytic, on-board PIC master, 9 V UVCL divider, off-board mount, unreachable distributor pages | **Reopened as finalist** |
| BQ25756 | Ranked below the TI NVDC parts | IC-intrinsic: every hard stop restarts cold (typical 145-175 ms); C_IN >= 80 uF | Screened again; M9 F on every pin stop (section 3.3). The [RES] section 3.7 option W2 (ILIM_HIZ held at about 3.0 V, between VREF_ILIM_HIZ 2.0 V typ and VIH_ILIM_HIZ 3.7 V min) has a primary basis for its premise only: a pin voltage above VREF_ILIM_HIZ enters input-current regulation, DPM reduces the charge current to zero, and REGN stays enabled while charge is enabled and HIZ is not entered (SLUSEN5A p.10, p.21-22, p.28-29; [SCR] section 4.4). The recovery time, the residual input current and the pin's tolerance of an external drive are not specified. W2 is UNVERIFIED (dossier A1 bench gate B10: I_IN < 10 mA, recovery <= 4 ms, REGN up). Held in reserve on the same condition as the BQ25820, not rejected on W2 |
| BQ24650 | Rejected | IC-intrinsic: no I2C, 1.5 s MPPSET release, 33 V | Unchanged reject |
| MP2759 | NOT_FEASIBLE | IC-intrinsic: no I2C, 170-175 ms re-enable, autonomous POR charge, 3 A recommended maximum | Unchanged reject |
| LTC4162-L | Round 1 "showstopper" | Mixed; primary never read | Primary read; M5 F (section 3.3) |

Two parts reopened because their downgrade rested on the EVM: the BQ25773 and the LTC4015. No part was rejected
in round 2 for a reason that was purely form-factor; the round-1 list holds most of the form-factor rejections ([RES]
section 6).
The custom board removes four classes of condition from every part (EVM fail-safe defects, EVM input capacitance, off-board
mounting, EVM stock). It does not remove four system-level conditions: D-BT-SQ stays in series, the HR2 purge and FC-budget
blockers stay, the warm-response and inhibit-latency unknowns stay, and the MCU hardware watchdog stays mandatory
([RES] sections 1.1, 1.2).

The round-1 rejection list of 2026-11-05 held further parts whose rejection rested on EVB or EVM availability. [RES]
section 4 marks them "reopen-possible". Table 4.2 gives the final outcome of each after the wide screen and the evidence
class of that outcome. No round-1 part reopens to a finalist position.

**Table 4.2.** Round-1 parts marked reopen-possible ([RES] section 4) and their final outcome.

| Part | Round-1 reason | Final outcome | Evidence class | Source |
|---|---|---|---|---|
| SC8815 (and SC8815A) | No official EVB; sense location UNVERIFIED | M9 F: PSTOP 220-330 ms deglitch | P | Table 3.1; SC8815A DS V1.1.0 p.12 |
| SC8886S, SC8885S | No official EVB | M2 F expected (24-29 V class) | UNVERIFIED: primary not located | [SCR] section 3; Table 8.1 |
| SC89890 | No official EVB | Scope: 1S part | UNVERIFIED (sweep listing, no primary cited) | [SCR] section 3 |
| RT9490 (RT9490S) | VAC_OVP POR 7 V | M2 F: 30 V absolute maximum (strict reading; bounded in section 6.4) | P | RT9490S_DS-00 sections 11-12 |
| RT9492 | Abs max and MIVR UNVERIFIED; EVB availability | M2 F: 30 V absolute maximum (strict reading; bounded in section 6.4); held in reserve as a functional BQ25798 second source | P | RT9492_DS-05 sections 12-13 |
| MAX77960 / MAX77961 | Primary missing; EV kit orientation | M2 F: CHGIN 30 V (B parts; strict reading, bounded in section 6.4); non-B parts UNVERIFIED | P (B parts) | 19-101123 Rev 0 p.2-3 |
| LT8491 | Demo-board configuration | M8 F, M9 F: SHDN exit boots from EEPROM, CRC and soft-start | P | LT8491 Rev 0 p.18-19 |
| LTC4013 | Demo-board configuration | M7 F, M8 F, M10 F | P | 4013fa p.6, p.12 |
| LTC4020 | Demo-board configuration | M10 F, M12 F | P | 4020fd p.8-9 |
| LTC4000 | Needs an external front end | M8 F (LTC4000), M7 F (LTC4000-1), M10 F, M12 F | P | 4000fb p.1, p.8-10; 40001fa p.1 |
| BQ25756, BQ25756E, BQ25750 | "10 A / 5 mOhm class, oversized" | M9 F on the pin stops: about 40 ms compensation toggle at startup; W2 held in reserve (section 3.3) | P (40 ms toggle at startup, p.21; /CE to current about 144 ms, Fig 7-7 p.66, figure reading); U for recurrence on every /CE start (dossier A1 section 11) and for W2 | SLUSEN5A p.21, p.66; SLUSFF4A p.22; SLUSDY3 p.23 |
| BQ25758(A) | As above | Scope: DC/DC without a charge profile | P | SLUSFN3B Table 4-1 p.3 |
| BQ25820 | As above | M9 U; held in reserve (section 3.3) | U | SLUSFN3B p.67 (illegible) |
| BQ25672 | EVM existence UNVERIFIED | M2 F (30 V), M4 F (3 A) | P | SLUSEB9B p.7 |
| NXP / Toshiba (search item) | No suitable EVB found | NXP: scope only (1S chargers, PMIC, cell monitor); Toshiba: not swept | NXP: sweep listing; Toshiba: gap (Table 3.2) | [SCR] section 3 |

---

## 5. Finalists

Each subsection gives the key facts, the HR codes, the interlock delta against the BQ25798 design, the treatment of the FC
purge ruling and the principal risks. The HR codes and margins are those of [SCO] Table 5 at the scored builds.

### 5.0 Charge current at an 8.4 V pack against the 3.10 A BQ25798 image setting

Table 5.1 gives, for each part, the M4 capability, the delivered charge at an 8.4 V pack at the regen threshold floor
(section 1.1 defines the two readings) and the HR1 input condition. The regen threshold floor is the low tolerance corner of
each part's regen setting: 18.62 V for the BQ25798 and the BQ25690 (VINDPM 19.0 V at -2 %, [EVAL] section 4.5), 18.81 V for
the BQ25773 (VINDPM 19.0 V at -1 %, [D773] section 11.3), 18.69 V for the LTC4015 (code 0xFF) and 18.53 V for the RAA489110
(code 149). The 18.13 V of Table 2.2 is the bottom of the H4 range and is used only for buck headroom. Every delivered
figure applies each published tolerance at its low corner; where no tolerance is published at the operating point, the
nearest published row is extrapolated and marked U. The input at the threshold is the lower of the input-ceiling limit and
the charge-current limit ([D773] section 11.3), at a 7.4 V pack and the low tolerance corners. The efficiency is that of each
dossier (BQ25798 0.925, BQ25690 0.92, BQ25773 0.95, RAA489110 0.94 assumed); the spread moves the margins by a few percent
and changes no pass result. The HR1 column is the pass/fail column.

**Table 5.1.** Charge current at an 8.4 V pack.

| Part | M4 capability (range and loss at 3.1 A) | Delivered at the threshold floor, 8.4 V pack, low tolerance corners | Against the 3.10 A BQ25798 image setting | HR1 input at the threshold (pass >= 23 W) | M4 grade |
|---|---|---|---|---|---|
| BQ25798 | ICHG 0.05-5 A; 2.11 W at 20 V (B) | 3.10 A at the nominal ICHG (input-ceiling limit 3.18 A with the reference-biased ceiling; 2.91 A with the REGN divider); 2.90 A at the ICHG low corner if the 2 A-row -6.5 % applies at 3.1 A (U: no ICHG accuracy is published above 2 A); 2.86 A with a -10 % pin error (B, S1-B6); an ICHG setting of 3.32 A gives 3.10 A at the low corner | Met at the nominal ICHG; below the setting at the extrapolated low corner (-0.20 A) unless ICHG is set to 3.32 A | Pass: 24.8 W (+7.8 %, charge-limited at 7.4 V); 23.2 W (+0.8 %) at the extrapolated ICHG low corner (U); input-ceiling capability 28.9 W (1.55 A x 18.62 V) | c (B, loss) |
| BQ25690 | ICHG 0.04-3.3 A; 2.14-2.48 W typical at 3.1 A, 15-20 V input (B) | 2.62 A: input-limited at the regen ceiling minimum (1.285 A x 18.62 V, eta 0.92); capture above VRECHG (8.02-8.15 V) not established | Below the setting (-0.48 A); structural | Pass: 23.9 W (+4.0 %) | c (B, loss) |
| BQ25773 | CHARGE_CURRENT 0-16.32 A; about 1.4 W at 3.2 A, 8.4 V | 2.77 A: input-limited at the regen ceiling minimum (1.30 A x 18.81 V, eta 0.95; 2.81 A at 1.32 A without the leakage term); the ICHG low corner (3.04 A at the 3.200 A setting) does not bind | Below the setting (-0.33 A); structural; a higher CHARGE_CURRENT setting does not close it | Pass: 23.7 W (+3.0 %, charge-limited at 7.4 V) | P / C |
| LTC4015 B | 32 mV / RSNSB, 10 mOhm; 1.2 W estimate | 3.105 A minimum | At or above the setting | Pass: 24.0 W (+4.3 %, charge-limited at 7.4 V) | P / C |
| RAA489110 | ChargeCurrentLimit register, 3.248 A setting; 1.41 W at 3.25 A (C) | 3.103 A minimum | At or above the setting | Pass: 24.4 W (+6.1 %, charge-limited at 7.4 V, eta 0.94 assumed) | P / C |

Sources: [SCO] Table 5; [D798] sections 7, 11.1, 11.3; [D690] sections 3 (M4 row), 11.3; [D773] sections 7.3, 11.1, 11.3;
[D4015] section 11; [DRAA] section 11.

M4 is a capability test, and every part can be set to 3.1 A or more. The 2 W loss limit at 3.1 A is met by the three
external-FET parts (BQ25773 about 1.4 W, LTC4015 B 1.2 W estimate, RAA489110 1.41 W). M4 is conditional on loss for the
BQ25798 (2.11 W at 20 V, +0.11 W) and the BQ25690 (2.14-2.48 W at 15-20 V, +0.14 to +0.48 W). A delivery below the 3.10 A
image setting is a delivered-current shortfall, a separate item. It is graded as an HR1 margin note, not as an HR1 failure:

- **BQ25798.** The shortfall is a setting choice. The buck ICHG accuracy is published only at 0.5-2 A (2 A: -6.5/+3.5 %,
  DS EC p.11), so the low corner at 3.10 A is an extrapolation, 3.10 x 0.935 = 2.90 A (U). A 3.32 A setting gives
  3.32 x 0.935 = 3.10 A at the low corner, below the 3.18 A input-ceiling limit of the reference-biased ceiling (C nominal;
  pin-to-current accuracy U, S1-B6). The headroom and copper basis of section 2.2 would then rise from 3.21 A to 3.44 A
  (3.32 A plus +3.5 %) ([D798] section 11.3).
- **BQ25690.** The shortfall is structural. A guaranteed 3.1 A at an 8.4 V pack needs a regen ceiling minimum of about
  3.1 x 8.4 / (0.92 x 18.62) = 1.52 A (C). The R_RG band scales by 1.715 / 1.285 = 1.33, so a 1.52 A minimum gives a maximum
  of about 2.03 A, above the 1.72 A hard-stop row of HR4 (B). The BQ25690 therefore cannot meet the delivered 3.1 A at an
  8.4 V pack and the HR4 ceiling at the same time with the IC pin ceiling (KILIM +-13 %; the 1.715 A and 2.03 A values lie
  above the 1.6 A KILIM test point and are extrapolated, B). A CCB current regulator narrower than the KILIM band
  (Table 1.2) could close the gap at an S3 penalty that this document does not score. The 23 W HR1 input condition is met.
- **BQ25773.** The shortfall is structural. At an 8.4 V pack the regen input ceiling binds, not ICHG:
  1.30 A x 18.81 V x 0.95 / 8.4 V = 2.77 A (C). A guaranteed 3.1 A at an 8.4 V pack needs a regen ceiling minimum of
  3.1 x 8.4 / (0.95 x 18.81) = 1.46 A (C). With the +-0.245 A pin, divider and leakage band of [D773] section 7.3, the maximum
  becomes about 1.95 A, 13 % above the 1.72 A hard-stop row of HR4. The hard-stop allowance then falls to about 96.5 us
  against the 110 us bench pass (C; constant-charge model of [EVAL] section 2.5, [D773] section 11.3). The 23 W HR1 input
  condition is met.

On this record every finalist meets the HR1 input condition. The BQ25690 and the BQ25773 deliver less than the 3.10 A
BQ25798 image setting at the low tolerance corner, and both shortfalls are structural. The BQ25798 shortfall at the
extrapolated corner closes with a register setting, and the LTC4015 and the RAA489110 reach the setting. The scores of
section 6 do not change, because no criterion scores delivered current; the structural shortfall is a disadvantage of the
BQ25690 and the BQ25773 that the weighted score does not capture.

### 5.1 Baseline: TI BQ25798 on the CCB

Dossier: [`dossier_BQ25798.md`](reviews/charger_ic_search_2026-11-10/dossier_BQ25798.md). Primary: TI SLUSDV2C, revised
June 2026.

Key facts:

- Integrated 4-switch buck-boost NVDC charger with an internal BATFET and internal high-side input and charge sense; VQFN-HR
  29, 4.0 x 4.0 mm, 0.4 mm pitch, no exposed pad (DS p.148); Active (DS p.145).
- Absolute maximum 30 V on VAC1, VAC2, VBUS, PMID and SW1; 24 V operating; VBUS_OVP 25.2 V minimum (DS p.7, p.9).
- VINDPM 3.6-22 V in 100 mV steps, +-2 % at 18.6 V. The IC rewrites it to VBUS0 - 1.4 V (14.5 V at a 15.9 V bus, below
  the bus) at each plug-in, at FORCE_VINDPM_DET = 1 and at EN_MPPT = 1; it is not reset by REG_RST or the watchdog (DS
  p.12, section 7.3.4.4 p.27, Table 7-17 p.62). Survival across the re-qualification paths (VBUS_OVP retry, 7-minute
  poor-source retry, EN_HIZ = 0 retry) is not stated: B, bench gate S1-B2 ([D798] section 6).
- ILIM_HIZ below 0.75 V stops switching, above 1 V resumes (DS section 7.3.4.3 p.27). POR charges at 1 A; the CCB biases
  /CE and ILIM_HIZ from REGN so that both default to inhibit.
- Charger watchdog shortest setting 0.5 s (no tolerance published at that setting; DS Table 7-26 p.72); cold start REGN about 150 ms after VBUS_PRESENT (DS section 7.3.4
  p.26), so an always-powered design is mandatory.
- ICHG 0.05-5 A in 10 mA steps; buck ICHG accuracy is published only at 0.5-2 A (2 A: -6.5/+3.5 %, DS EC p.11). With the
  reference-biased regen ceiling (1.55-1.61 A) the input-ceiling limit at the threshold floor is 3.18 A at an 8.4 V pack, so
  the CCB delivers 3.10 A at the nominal ICHG at both 7.4 V and 8.4 V packs. At the extrapolated ICHG low corner it delivers
  about 2.90 A (U), and a 3.32 A setting restores 3.10 A. The 2026-11-05 REGN divider gave 2.91 A at 8.4 V at the nominal
  ICHG ([D798] section 11.3).
- Loss at 3.1 A into 8.4 V at a 20 V input: 2.11 W at 750 kHz (figure reading, typical; [D798] section 11.2).
- Stock 415 146 at the TI store on 2026-11-10 (P); USD 5.04 at 1-99 (P); second-source stock UNKNOWN.

HR codes: HR1 U (B, S1-B4); HR2 P / sys; HR3 C, conditional on SYS kept as a separate capacitor-only node; HR4 C nominal
(regen ceiling maximum 1.61 A with a 129 us hard-stop allowance; FC bound after a POR 1.15 A, margin 0.05 A to the 1.20 A
arm drop, pin-to-current accuracy unpublished (U, S1-B6); after an IINDPM register loss the FC bound is conditional on
P6 / S1-B6: 1.15 A if re-sampled, 1.70-1.76 A if sampled once; the ILIM clamp is register-defeatable through EN_EXTILIM
REG14[1] and is covered by the REG14 read-back each pass, M7 conditional, Table 6.0a); HR5 C by design, conditional on
the REGN bias and the heartbeat path, watchdog items B.

Interlock: 11 IC-specific adders in the minimal build (S6 = 0), about 18 in the single-fault parity build ([SCO] Table 6).

Purge ruling: supported through the P5 static /CE arm and the H2 permit; the window-close path is that of 2026-11-05
([D798] section 11.4).

Principal risks: the 30 V rating needs the eFuse standoff (R-M2); a SYS-BAT strap makes the design NOT FEASIBLE ([D798]
section 16, gate CCB-1); the ILIM_HIZ sampling ambiguity (P6), the BAT 2.5 V hold and BATOVP cycling behind D-BT-SQ (P1, P2),
the contradictory watchdog fields (P7) and the 7-minute poor-source lockout (C6) stay open; a host-writable CELL field lifts
the VREG bound to 18.8 V until POR (R6 finding 1).

### 5.2 TI BQ25773 (SMBus twin BQ25770G)

Dossier: [`dossier_BQ25773_SMBus_twin_BQ25770G.md`](reviews/charger_ic_search_2026-11-10/dossier_BQ25773_SMBus_twin_BQ25770G.md).
Primary: TI SLUSEK7, September 2024 (BQ25770G: SLUSFK8, April 2024).

Key facts:

- External-FET quasi dual-phase NVDC buck-boost controller, 2-5S, I2C address 0x6B; WQFN-36, 4.0 x 5.0 mm, 0.4 mm pitch;
  Active (SLUSEK7 orderable addendum p.138).
- Absolute maximum 45 V; ACOV 33 V default, 32.25 V minimum (SLUSEK7 p.8, p.17).
- POR CHARGE_CURRENT 0 and EN_AUTO_CHG 0, no non-volatile memory (Table 7-2 p.31, p.63, p.77): the part does not charge out
  of POR.
- VINDPM 3.2-27 V in 20 mV steps, +-1 % at 18 V (p.12, p.66); POR VINDPM 3.2 V, below the pack.
- ILIM_HIZ pin ceiling read continuously, +-200 mA absolute at all tabulated points (EC p.12); VILIM_ENZ at 4.1-4.2 V
  disables the pin ceiling regardless of EN_EXTILIM (p.6, p.20).
- Independent comparator with FRC_CONV_OFF and a 1 us deglitch (section 7.3.4 p.30); the recommended build does not use it,
  because REG0x30 also holds EN_PTM and SYSOVP_MAX and is placed on the never-write list.
- Converter powers up 226 ms after VBUS qualifies (section 7.3.1 p.27): always-powered design mandatory.
- Efficiency about 95.5 % at 20 V, 7.4 V, 3 A (Fig 6-3 p.22, figure reading, typical).
- Stock 15 695 at the TI store on 2026-11-10 (P), single source; USD 3.14 with an unstated quantity basis (UNVERIFIED).

HR codes: HR1 U (B, gates B2, B4); HR2 P / sys; HR3 C; HR4 C in regen (maximum 1.79 A, 110 us on the constant
0.757 V margin: 302.8 uC / 1.79 A - 59 us = 110.2 us; bench pass <= 110 us, margin under 1 us),
C but weaker than the baseline in FC mode; HR5 P at POR, C for the hold-down, B for the watchdog (4-7 s).

Interlock: 8 adders in the recommended build (S6 = 1): an ILIM_HIZ hold-down with a REGN gate pull-up and a release
transistor (inhibit and ceiling on one pin), the FC leg with gate bias, and a 2.5 V shunt reference with bias. Four
contingent items would each move S6 to 0: the `CHG_QUAL` gates if bench gate B13 fails (+2), a keep-alive above 6.8 V (+3),
a THERM comparator, and the FRC_CONV_OFF fast path (+2) ([SCO] Table 6).

Charge at an 8.4 V pack: 2.77 A, input-limited at the regen ceiling minimum, below the 3.10 A BQ25798 image setting; a higher
charge-current setting does not close it (Table 5.1).

Purge ruling: handled at system level; the IC contributes VINDPM 13.5-15 V and an FC hardware ceiling of 0.76-1.24 A
([D773] section 4). The per-purge cost is that of section 5.6.

Principal risks:

- **FC bound after a register loss.** The +-200 mA pin accuracy gives an FC ceiling of 0.76-1.24 A. After an IIN_HOST loss
  the bus draw can reach 1.39 A, above the 1.20 A arm drop and the 1.247 A H-20 P_MAX. No ceiling position meets both H5 at
  the low corner and the arm drop at the high corner; the same holds for the BQ25798 REGN-divider FC leg (band 0.29 A
  against a 0.19 A window) and the BQ25690 (0.25 A against 0.20 A). The BQ25773 differs in the width of its band (0.48 A,
  a pin accuracy specification) and therefore in its bus draw at the chosen nominal (1.39 A against 1.15 A and 1.10 A)
  ([D773] section 11.4; ruling R-FCCEIL).
- **Burst entry from a drained VCHG.** Behind D-BT-SQ the next burst starts in pre-charge and passes through the nominal
  5 ms tTRANS_CHG (NOM only, no MIN or MAX, shape unpublished; SLUSEK7 section 6.6 p.21). As a linear ramp from IPRECHG
  0.384 A to the 3.200 A setting, 63 % is reached at about 2.9 ms and 90 % at about 4.4 ms, inside the 4 ms and 9 ms
  budgets. As a delay it fails by 1.0 ms. Every reading except an exponential one fails the 2 ms board-only case. The same
  scenario pays the IC-independent D-BT-SQ drop-out (tD_ON 8 ms + tON about 1.9 ms) for every candidate ([D798] section 8).
  A remedy (BATFETOFF_HIZ = 1, EN_LDO = 0, or a keep-alive above about 6.8 V) must be proven on gate B4 ([D773]
  section 8.3).
- **Register-defeat surface.** The never-write list holds seven fields at eight positions, including EN_IIN_DPM and
  IIN_DPM_AUTO_DISABLE ([D773] sections 5.1, 7.2).
- **No battery TS input** ([D773] section 2.4).
- **Layout.** Seven external N-FETs, two inductors, three shunts, three hot loops, about 57 parts and about 590 mm2 of
  placement on a four-layer CCB with phase B populated ([SCO] Table 7).

### 5.3 TI BQ25690

Dossier: [`dossier_BQ25690.md`](reviews/charger_ic_search_2026-11-10/dossier_BQ25690.md). Primary: TI SLUSFN4A, Revision A,
December 2025.

Key facts:

- Integrated 4-switch buck-boost NVDC charger, 1-7S, external N-channel BATFET and two external sense resistors; WQFN-HR 26,
  4.0 x 3.5 mm (section 10.1 p.75); Active.
- Absolute maximum 45 V (section 5.1 p.5); VIN_OVP 35.5 V minimum.
- 2S CV 8.358-8.442 V at TJ 0 to 85 C (section 5.5 p.8): M3 is P on that basis. Over TJ -40 to 125 C (-1.15/+0.9 %, same
  page) the band is 8.303-8.476 V, 13 mV below the 8.316 V lower limit and 8 mV inside the 8.484 V upper limit.
- RILIM_HIZ recommended range 0-33 kOhm (section 5.3 p.6); KILIM 2890/3333/3780 A*Ohm at IIN_MAX 0.5, 1.0 and 1.6 A
  (section 5.5 p.9). The ceiling is continuous and fails low; above 1.6 A the band is an extrapolation.
- At a true POR the ICHG strap fault clears EN_CHG, so the part does not charge without host writes ([D690] section 5.3).
  This does not hold after an input dip with SRN bias, and is U after REG_RST.
- No ADC in the register map (Table 6-12 p.45): telemetry needs a CCB current monitor.
- /CE stops charging but leaves the converter regulating SYS; the only typical capture shows charge current about 1.2 ms
  after the /CE edge in boost mode at 5 V (figure reading, typical). An exit through ILIM_HIZ re-reads the CELL, ICHG and
  VCHG straps, so the per-burst inhibit must be /CE.
- Charger watchdog shortest setting 40 s (nominal; no maximum published, DS Table 6-24 p.50, section 5.6 pp.12-13) against
  0.5 s in the baseline.
- CVIN >= 10 uF after derating (section 5.3 p.5).
- STAT LOW = charging (Table 6-11 p.39), the inverse of the Ag105 steady-HIGH = charging decoded on `CHARGER_STAT`; a
  firmware change would be needed before use.
- Stock: DigiKey regional snippets of 176 and 460, 18-week lead time (UNVERIFIED); about USD 5.2 (UNVERIFIED).

HR codes: HR1 U (B, gates T-8a, T-8b, T-3.VRECHG); HR2 P / sys (FC charge 1.25-1.58 A, typical 1.46 A; H5 fails at the
typical value with R_FC 4.02 kOhm, and R_FC 3.83 kOhm restores 1.51 A); HR3 C (two hardware layers); HR4 C (regen
maximum 1.715 A, extrapolated, B; FC bound after a POR 1.10 A, margin 0.10 A; the pin ceiling is register-defeatable through
EN_EXTILIM REG0x14 bit 5); HR5 C, watchdog shortest setting 40 s, no maximum published.

Interlock: 9 adders in the minimal build (S6 = 0): a /CE REGN pull-up and open-drain stage, a static HIZ drive from a
VCHG-IN-derived rail (micro-power LDO, inverter, Schottky diode, series resistor), and the regen leg with its gate
pull-down; no `CHG_QUAL` gates. A CCB current monitor (3 parts) is counted under S7 ([SCO] Table 6).

Charge at an 8.4 V pack: 2.62 A at the regen ceiling minimum, below the 3.10 A BQ25798 image setting but 4.0 % above the HR1
input condition, and the HR4 ceiling row prevents a fix by a
higher ceiling with the IC pin (Table 5.1).

Purge ruling: the /CE stop of about 20 us (typical) lands a pre-purge inhibit well before the bus sags ([D690]
section 11.5). [D690] section 11.5 also charges the BQ25690 with a cold re-entry after every purge, on the assumption that
VCHG-IN decays when the FC feed opens. Section 5.6 replaces that assumption with one system assumption for every part: in
Run, D-BC-RG re-closes within the 10-12 ms handover before a predicted purge, VCHG-IN droops by about 0.3-0.8 V on the
BQ25690, and no part pays a cold re-entry per predicted purge in Run.

Principal risks:

- **M5 conditional.** /CE disables charging but does not stop conversion, and the ILIM_HIZ HIZ entry level has a minimum
  only (VIH_ILIM_HIZ 1.77 V minimum, section 5.5 p.9). Decision-rule condition 1 stays open until T-5.HIZ passes.
- **Regen start condition.** A /CE edge starts a cycle only with SRN below VRECHG (section 6.3.8.2.2 p.28), so capture at a
  pack above about 8.0-8.15 V is not established (T-3.VRECHG). The affected band is about 25-38 % of the 7.4-8.4 V window
  (8.022 V at the POR setting, 8.148 V at the 97 % maximum). SLUSFN4A p.28 also states that a /CE toggle after termination
  starts a new cycle, so the status is B.
- **Single-bit defeat.** EN_EXTILIM (REG0x14 bit 5) = 0 disables both the ILIM_HIZ ceiling and HIZ entry through the pin
  (DS section 6.3.8.1.2.1 p.26, [D690] section 3). The remaining limits are /CE (charge disable, converter running) and the
  IINDPM register (0.90 A in FC mode, about 1.05 A bus draw with the 0.15 A aux term, inside the 1.20 A arm drop). REG0x14
  also holds FORCE_VINDPM and EN_BAT_DETECT, which the POR enable sequence writes, so every REG0x14 write is a masked
  read-modify-write with readback. A watchdog expiry (40 s shortest setting) restores the bit only if the host does not.
- **Ceiling fault direction.** A grounded ILIM_HIZ pin, or a STAT-to-ILIM_HIZ bridge while charging, defeats the hardware
  ceiling instead of inhibiting the converter.
- **No ADC**, so R6 finding 10 stays open on the accuracy of a CCB monitor.

### 5.4 ADI LTC4015

Dossier: [`dossier_LTC4015.md`](reviews/charger_ic_search_2026-11-10/dossier_LTC4015.md). Primary: LTC4015 data sheet Rev B
(4015fb), read from a vendor-PDF mirror because analog.com did not respond; whether a later revision exists is U.

Key facts:

- External-FET synchronous buck controller with INFET and OUTFET drivers, high-side RSNSI and RSNSB, I2C and a coulomb
  counter; QFN-38, 5 x 7 mm, 0.50 mm pitch, one exposed pad (p.3, p.74).
- VIN absolute maximum 40 V (p.3); operating 3.1-35 V (p.4); OVLO 37.7 V minimum (p.4, p.41).
- VCHARGE tolerance +-1.25 % over the full operating junction range (p.4; no narrower-range row is published): code 31
  (4.200 V/cell) gives 8.295-8.505 V, 21 mV outside the M3 band on both sides. DAC code 30 (4.1875 V/cell) gives
  8.270-8.480 V: the upper limit holds, the lower bound is 46 mV below 8.316 V, so no code meets +-1.0 % on both sides;
  code 30 also reverts to 4.20 V/cell after every charger POR.
- UVCL threshold resets at POR to the divider maximum (VIN_UVCL_SETTING 0xFF, p.22, p.60): every charger POR lands in a
  regen-only state, and a register write can only lower the threshold. The CV DAC cannot exceed 4.2 V/cell, which closes R6
  finding 1 by design.
- Every new charge cycle runs a 2-4 s battery detection, then a 1-2 s open/short test if unstable (p.30).
- No dedicated inhibit pin; the UVCLFB clamp is register-defeatable (p.46). No host watchdog. Hold-state input draw is not
  tabulated; p.46 gives a 5-20 mA minimum operating current, so M8 is U/B (at risk) against the <= 10 mA criterion.
- Documented VIN-BATSENS differential UVLO of 140-250 mV (p.4), the hardware no-charge floor credited by S16.
- Stock: Mouser.ca snippet 47 191, DigiKey.com.br 639 (UNVERIFIED); lifecycle U.

HR codes (design B): HR1 B; HR2 P / sys (1.69 A at IIN 1.00 A); HR3 C, with the D-BT-SQ bridge removing the pack isolator;
HR4 C (regen maximum 1.649 A, 125 us: 302.8 uC / 1.649 A - 59 us = 124.6 us; FC bound about 1.15 A, tolerance band not computed); HR5 C, B for the DRVCC stage,
sys for the absent host watchdog.

Interlock: 13 adders in design B (S6 = 0), 7 in design A. The adders carry a UVCLFB clamp FET with an INTVCC pull-up and a
release FET (per-burst zero current), a DRVCC load switch (converter-off master, cold exit), the D-BT-SQ bridge fuse, and in
design B a UVCLFB divider switch and an RSNSI bypass P-FET with its level shifter ([SCO] Table 6).

Purge ruling: the FC threshold (UVCL code 189, 14.04 V) is a bus-collapse guard only. The bus falls from 16.0 V to the
threshold in about 0.06-0.07 ms at 28-31 V/ms while the charger draws 0.90-1.00 A (0.76 ms at the aux-only 2.57 V/ms), so the
ruling relies on the EMS and the core permit ([D4015] section 11.4). The
per-purge cost is that of section 5.6.

Principal risks: M3 F as written; no inhibit pin (M5 c, ruling R-INH); the mandatory fused bridge across D-BT-SQ (ruling R-BR)
removes the Teensy-controlled pack isolator, makes a bottom-FET short a pack short that only the fuse clears, and sits off
the CCB or needs a flying lead to VBT at C-D12; any input collapse costs a 2-4 s battery detection; design A has no hardware
FC ceiling (ruling R-FCA). The LTC4015 is the only finalist with a modelled warm path (0.07-0.2 ms with a 10 nF VC network,
[D4015] section 8.2; C on the model, B on the numbers), which makes it the fallback if the TI warm response fails
(section 6.4).

### 5.5 Renesas RAA489110 (alternates RAA489118, RAA489108)

Dossier: [`dossier_RAA489110_alternates_RAA489118_RAA489108_in_the_same_dossier.md`](reviews/charger_ic_search_2026-11-10/dossier_RAA489110_alternates_RAA489118_RAA489108_in_the_same_dossier.md).
Primary: Renesas R16DS0212EU0202 Rev.2.02, August 2026.

Key facts:

- External-FET 4-switch NVDC buck-boost controller, 2-4S, SMBus/I2C, internal 8-bit ADC, five N-FETs including the battery
  FET Q5 (BFET); TQFN-32, 4.0 x 4.0 mm, 0.40 mm pitch, one exposed pad (p.91).
- CSIP, CSIN, DCIN and BYPSRC absolute maximum 36 V (section 3.1 p.11); 30 V operating ceiling.
- Runtime VIN register to 24.576 V in 128 mV steps; accuracy at 19 V unpublished.
- No charge at POR; BATGONE defaults to inhibit through its internal pull-up current source and opens the BFET. The
  converter keeps regulating VSYS while BATGONE is HIGH.
- BATGONE is defeated by Control4 bits 15 and 14; the adapter-current ceiling has four register defeat paths (Control3 bits 5
  and 6, PTM, PPS).
- The parked regen state can enter a VSYS UV fault and reload the adapter-current limit to 53 mA unless configured out
  ([DRAA] sections 6.1, 7.3).
- Input-current ADC saturates at 1.515 A; charge-current LSB 22 mA; no published ADC accuracy.
- Stock "in stock" without a quantity (product-page summary, UNVERIFIED); USD 4.51-4.96 (UNVERIFIED).

HR codes: HR1 U (B, gates R-B2, R-B4); HR2 C / sys (1.51-1.62 A at 8.4 V); HR3 C, but a Q5 short leaves the converter charging
with PERMIT LOW; HR4 C (regen maximum 1.687 A, 120 us: 302.8 uC / 1.687 A - 59 us = 120.5 us; FC bound 0.20 A after POR, 1.84 A after a stray write inside a window); HR5 P
intrinsic, C for the bias, B for the latency; SMBus timeout 4.95 s.

Interlock: about 10 adders at equal function (S6 = 0): a BATGONE open-drain channel with pull-ups and a series resistor, a
mandatory keep-alive (3 parts) and an FC eFuse current-limit leg (3 parts, a trip, not a regulated ceiling); 11-14 at
single-fault parity ([SCO] Table 6).

Purge ruling: handled at system level; however, a Q5 short leaves only firmware to stop FC charging, which breaks the
ruling for the firmware response time ([DRAA] section 16).

Principal risks: M5 conditional on a register defeat, the class [CRIT] M5 admits and on which the BQ25798 is itself B
(S1-B3), so decision-rule condition 1 is not decided on M5; about 14 word transactions (about
6.3 ms) per safety-verify cycle against one 11-byte burst of about 1.4 ms for the BQ25798, which reopens R6 finding 8
(condition 3 fails); the inhibit acts on a single series FET; two hot loops on a 0.40 mm-pitch QFN.

The RAA489118 (2-7S, 512 mV VIN step, no ADC, BATGONE with an internal 5 uA pull-down that defaults to permit,
strap-dependent POR charging; R16DS0321EU0200) and the RAA489108 (2-4S, 512 mV step, no ADC; R16DS0159EU0105) are weaker than
the RAA489110 on S4 and S7, and the RAA489118 also on S2 and S6. They are second sources of the same mechanism only
([DRAA] section 17).

### 5.6 System assumption through an H-20 purge

The dossiers made two different assumptions about VCHG-IN through a purge. [D690] section 11.5 assumes that VCHG-IN decays
when the FC feed opens. [D4015] section 8.4 and [DRAA] section 8.2 assume that D-BC-RG holds VCHG-IN at about bus level
through Run. This document applies one system assumption to every part:

1. Under the always-powered design ([EVAL] section 0.1, ruling 3), REGEN (D-BC-RG) is closed through Run except inside an
   FC window. Inside an FC window IO CSV row 31 requires REGEN and BT_BUS LOW (`FAULT_SWITCH_CONFLICT`,
   `assertFcChargeEnable()`). V-MOT is energized at bus level through Idle and Run (the `MOT_PWR_ENABLE` pre-charge rule
   of the firmware sequencing rules).
2. Before a predicted purge the FC window closes first, in the order of [WD] (r1-1, invariant I-9) and [EVAL] section 4.4
   ("FC -> regen"). The charger is inhibited (P5 LOW, or the hard-inhibit equivalent of the part), and its threshold is
   written back above the bus. Then `FC_CHARGE_ENABLE` goes LOW. Then `BT_BUS_ENABLE` and `REGEN_ENABLE` close
   (`FAULT_SWITCH_CONFLICT` is the backstop). The share shift toward the battery follows the BT_BUS close ([EVAL]
   section 0.1, ruling 6). This handover is a design item of [EVAL] section 4.4; the fw v37 rev 2 Run path does not
   implement it.
3. VCHG-IN has no feed for the RT1987 turn-off plus tD_ON, about 10-12 ms (tD_ON 8 ms typical; turn-off measured at bench
   gate S0-M3). Over that gap only the quiescent draw discharges VCHG-IN. Table 5.1a gives the droop per part; each part
   stays above its re-qualification threshold. When D-BC-RG has re-closed, VCHG-IN is at about V-MOT, that is, at bus
   level, now battery-fed.

**Table 5.1a.** VCHG-IN droop over a 12 ms handover gap (dV = I x t / C).

| Part | Quiescent draw | VCHG-IN capacitance | Droop | Re-qualification threshold | Source |
|---|---|---|---|---|---|
| BQ25798 | IQ_VBUS 5 mA | 70.2 uF (25.8 uF eFuse baseline) | About 0.9 V (2.3 V at 25.8 uF) | VBUS_PRESENTZ 3.1-3.3 V | [D798] M8 row (IQ_VBUS), VBUS_PRESENTZ row, H8 capacitance table |
| BQ25690 | IQ_VIN 0.25-0.7 mA | About 11 uF | About 0.3-0.8 V | VIN_OKZ 2.35 V maximum | [D690] input-dip row (VIN_OKZ), section 11.5 (IQ_VIN, 11 uF) |
| BQ25773 | IQ_VAC 2.5 mA typical | 20 uF (motherboard C-D8/C-D10 alone) | About 1.5 V | VVBUS_CONVEN 3.1-3.7 V | [D773] section 2.2 (VVBUS_CONVEN), section 6 (IQ_VAC draw row) |
| LTC4015 | 5-20 mA | 40 uF | About 1.5-6 V (VCHG-IN 10.0-14.5 V) | BATSENS + 100 mV, about 8.5 V | [D4015] section 8.4 |
| RAA489110 | IQ 2.25-2.35 mA | Not fixed in [DRAA]; 20 uF assumed | About 1.4 V | ACOK (VCHG-IN stays above the pack) | [DRAA] draw row (IQ1, DS p.12) |

D-BC-FC is not the stop element once D-BC-RG has re-closed. The FC-mode threshold floor (13.10-13.14 V, Table 2.2a) lies
below the 16 V bus, so an uninhibited charger would draw from the battery-fed bus. The stop is the hard inhibit, the
threshold write and the H2 permit. The FCC_OFF term of the permit falls with `FC_CHARGE_ENABLE`, and its BTB_OFF term
falls with `BT_BUS_ENABLE` within 2-4 us ([WD]). A BT_BUS close while the charger is still permitted would run the HR3 loop
from the bus through the charger, the pack and the BT boost back to the bus. The loop current is bounded by the input
limit (0.90 A IINDPM; FC ILIM ceiling 0.74-0.96 A) until the permit falls, about 58 uJ of overlap. I-9 forbids that order.

Under this assumption a predicted purge in Run costs every part the same thing: the charger is inhibited, its threshold
returns above the bus, the H2 permit falls, and the next FC window opens warm. No part takes a POR or a cold start per
predicted purge in Run. A true BQ25690 POR needs the feed open for about 214 ms or more, longer than the 100-200 ms purge.
Concurrent REGEN and FC_CHARGE ([EVAL] section 0.1, ruling 7; IO CSV row-31 amendment pending) is not required for this
result. The LTC4015 result holds inside the 12 ms budget of [EVAL] section 4.4 only: at the 40 ms upper bound of [EVAL]
section 0.1 ruling 3, a 20 mA draw gives a 20 V droop and a cold re-entry.

A cold re-entry occurs when D-BC-RG does not re-close within the hold-up after `FC_CHARGE_ENABLE` drops (outside Run, for
example at standstill in Idle). VCHG-IN then decays, and every part pays its own cold-start cost, as Table 5.2 gives.

An unpredicted purge in an FC window (ruling 2 of section 1.1) falls outside this assumption. BT_BUS_ENABLE is LOW, and
VCHG-IN follows the FC-only bus through D-BC-FC. The bus falls at about 28.3 V/ms while the charger still draws its 0.90 A
FC ceiling ((0.09 + 0.90) A / 35 uF), and at about 2.57 V/ms once the charger has stopped (I_AUX 0.09 A / C_VBUS 35 uF).
UV_BUS (20 ms dwell) then latches State 99 about 21 ms after the onset, inside the purge ([EVAL] section 3.4). The collapse
is bounded identically for every part: D-BT-SQ blocks pack-to-charger reverse current, the input threshold or the buck
dropout stops the input draw, and the eFuse sees a falling input only. Each part then pays the Table 5.2 cold re-entry
cost. Its behaviour on the fuel-cell recovery is the HR4 "after a charger POR" row and the HR5 row of Table 6.0b:

- BQ25798: VAC_OVP returns to its 7 V POR default, and P5 stays LOW until the image is re-verified (1.15 A bus draw bound
  after a POR).
- BQ25690: the ICHG strap fault clears EN_CHG (1.10 A).
- BQ25773: CHARGE_CURRENT 0 and VINDPM 3.2 V, but IIN_HOST 5 A leaves 1.39 A to the eFuse (HR4 C).
- LTC4015: a 2-4 s battery detection; 1.80 A hardware bound in design A.
- RAA489110: AdapterCurrentLimit1 reloads to 53 mA (0.20 A).

No damage path is identified for any finalist. "No damage" stays UNCONFIRMED until a CCB equivalent of [BIF] bench gate
W2c is run.

**Table 5.2.** Per-purge cost of a cold re-entry (D-BC-RG left open beyond the hold-up after an FC window, or any
unpredicted collapse in Run).

| Part | Cold re-entry cost per purge | Source |
|---|---|---|
| BQ25798 | REGN about 150 ms after VBUS_PRESENT, plus about 30 ms poor-source check; re-write of VAC_OVP (POR 7 V, P5) and the register image; risk of the 7-minute poor-source lockout (C6) | [D798] section 8 (cold-start row), SLUSDV2C section 7.3.4 p.26; [EVAL] P5, C6 |
| BQ25690 | About 270 ms cold start (Figure 7-2, figure reading); after a true POR the ICHG strap fault and a 6-7-transaction enable sequence | [D690] sections 5.3, 11.5 |
| BQ25773 | 226 ms converter power-up after VBUS qualifies; image restore from POR (CHARGE_CURRENT 0) | SLUSEK7 section 7.3.1 p.27, via [D773] |
| LTC4015 | A VCHG-IN drop below BATSENS + 100 mV starts a new cycle with a 2-4 s battery detection | [D4015] section 8.4; 4015fb p.30, p.41 |
| RAA489110 | Adapter re-insertion: about 8 ms to ACOK, about 12 ms to first switching; AdapterCurrentLimit1 reload to 53 mA at the ACOK fall; possible VSYS UV fault (100 ms debounce, 1.3 s retry) unless configured out | [DRAA] section 3 (M9 row), sections 6.1, 7.3 |

The R6 finding 8 entries of Table 6.6 follow this assumption: the per-POR enable sequence of the BQ25690 is a burden only on
a true POR, which a predicted purge in Run does not cause under the [EVAL] section 4.4 handover.

## 6. Scoring and decision

### 6.1 Normalisation, must-haves and HR1-HR5

The five dossiers were written in parallel and applied four rules differently. [SCO] section 2 fixes one reading of each
and applies it to every part:

- **M2:** the protected-standoff reading of section 1.3. This reading keeps the BQ25798 eligible.
- **S1:** the score-2 anchor requires that the datasheet documents a warm inhibit exit. An inferred absence of a soft-start
  scores 1. Every part then scores S1 = 1; the LTC4015 dossier score of 2 (design B total 51.0) becomes 1 (46.0).
- **S6:** every package, every gate-bias resistor of an adder transistor, the mode-switched ceiling leg where needed, and a
  keep-alive only where mandatory are counted in the build that gives the same functions as the BQ25798 minimal build.
  Single-fault redundancy is counted separately. The BQ25690 count moved from 8 to 9 (S6 1 to 0, total 51.7 to 48.3); the
  BQ25773 count moved from 7 to 8 (S6 unchanged at 1).
- **S14:** R6 finding 8 counts as reopened only where a dossier shows a larger burden at first order (more transactions per
  safety-verify cycle or per mode change). On this rule only the RAA489110 reopens it; the strict reading is a sensitivity
  (section 6.4).

Each part is scored in a build with the same functions as the BQ25798 design: the BQ25798 with the reference-biased regen
ceiling and SYS separate, the BQ25690 with R_FC 4.02 kOhm and R_RG 4.99 kOhm, the BQ25773 recommended build, LTC4015
design B, and the RAA489110 equal-function build ([SCO] Table 2).

Table 6.0a gives the must-have outcome of each part under the protected-standoff M2 reading. Items not named pass on P or
C evidence ([SCO] Table 4).

**Table 6.0a.** Must-have outcome.

| Part | Fails | Conditional passes | Decision-rule condition 1 |
|---|---|---|---|
| BQ25798 | None (M2 c as protected standoff) | M2 (eFuse OVP response U), M4 (B, loss 2.11 W at 20 V), M5 (stop level 0.75 V / 1 V P, SLUSDV2C p.27; the EN_EXTILIM = 0 interaction with the stop is B, bench S1-B3; EN_EXTILIM POR 1, reset by REG_RST only, Table 7-30 p.78), M7 (EN_EXTILIM REG14[1]), M9 (exit timing U/B), M10 (unpowered pins U) | Baseline |
| BQ25690 | None | M4 (B), M5 (ILIM_HIZ HIZ entry level has a minimum only, B), M7 (EN_EXTILIM REG0x14 bit 5; the same bit disables HIZ entry through ILIM_HIZ, [D690] section 3 M5), M8 (FORCE_VINDPM reset by the watchdog), M9 (/CE delay typical, VRECHG start condition), M10, M11 (CCB monitor) | **Open**: M5 is B on the published HIZ entry level (VIH_ILIM_HIZ MIN only), where the BQ25798 has P (0.75 V / 1 V); the BQ25798's own M5 B (EN_EXTILIM interaction, S1-B3) is a different sub-claim that [CRIT] M5 admits with readback. The status holds until bench gate T-5.HIZ passes |
| BQ25773 | None | M7 (EN_EXTILIM at two addresses, EN_IIN_DPM, VILIM_ENZ), M9 (exit latency unpublished), M10 | **Met** under a symmetric M7 grading: the BQ25798 M7 is itself conditional ([D773] section 16.3) |
| LTC4015 | **M3 F** (CV +-1.25 %; code 30 reverts to 4.20 V/cell after every POR) | M5 (no inhibit pin; UVCLFB clamp register-defeatable; DRVCC stage B), M8 (hold-state draw not tabulated; 5-20 mA minimum operating current, U/B), M9, M13 (U) | **Fails**: M3 F |
| RAA489110 | None | M5 (BATGONE defeated by Control4 bits 15 and 14), M7 (four register defeat paths), M8 (parked VSYS UV fault), M9, M13 (UNVERIFIED) | **Not decided on M5**: the BATGONE register defeat (Control4 bits 15, 14; POR 0; readback) is the class [CRIT] M5 admits and on which the BQ25798 is itself B (S1-B3); condition 3 fails (finding 8) and the score is -4.7 |

M1 (common ground, high-side or input-side sense) passes on P or C evidence for every part. The unpowered-pin clause of M10
(no back-powering of SDA and SCL) is U for the BQ25798, the BQ25690, the BQ25773 and the RAA489110 (the RAA489110 dossier
records it inside a pass, [DRAA] section 3); the LTC4015 passes on P evidence (DVCC-referenced pins, [D4015] section 3).

M3 is graded on the TJ 0 to 85 C specification where the datasheet publishes one (BQ25690 and BQ25773 at 0 to 85 C;
BQ25798 at -40 to 85 C; the RAA489110 row states no basis). The LTC4015 publishes one tolerance over its full operating
junction range only. On that same -40 to 125 C range the BQ25690 reads 8.303-8.476 V, 13 mV below the 8.316 V lower limit.
The BQ25690 pass and the LTC4015 fail therefore rest on different bases. An operator ruling for the full range would move
the BQ25690 to M3 F and its Table 0.2 status to Not eligible.

Table 6.0b gives the HR status codes and the governing margins at the scored builds ([SCO] Table 5).

**Table 6.0b.** HR1-HR5 status and margins.

| Req | BQ25798 | BQ25690 | BQ25773 | LTC4015 (design B) | RAA489110 |
|---|---|---|---|---|---|
| HR1 status | U (B) | U (B) | U (B) | B | U (B) |
| HR1 input at the threshold (pass >= 23 W) | 24.8 W (charge-limited, 7.4 V pack, ICHG 3.1 A, eta 0.925), +7.8 % (C); 23.2 W at the ICHG -6.5 % corner (accuracy given only at 2 A, DS EC p.11; extrapolation U), +0.8 %; input-ceiling capability 28.9 W (1.55 A x 18.62 V) | 23.9 W (1.285 A x 18.62 V), +4.0 % (C) | 23.7 W (charge-limited, 7.4 V pack), +3.0 % (C) | 24.0 W (charge-limited, 7.4 V pack), +4.3 % (C) | 24.4 W (charge-limited, 7.4 V pack, eta 0.94 assumed), +6.1 % (C) |
| HR1 charge at an 8.4 V pack, threshold floor (Table 5.1) | 3.10 A at the nominal ICHG (input-ceiling limit 3.18 A, reference-biased ceiling); about 2.90 A at the extrapolated ICHG low corner (U); a 3.32 A setting gives 3.10 A | 2.62 A at the ceiling minimum; below the 3.10 A image setting; capture above VRECHG (8.02-8.15 V) not established | 2.77 A at the ceiling minimum; below the 3.10 A image setting | 3.105 A minimum | 3.103 A minimum |
| HR1 documented hazard (conditional; bench gate) | None documented (above-2 A ICHG accuracy U) | /CE edge starts a cycle only with SRN < VRECHG ([D690] section 8.3); about 25-38 % of the 7.4-8.4 V window (8.022 V at the POR setting, 8.148 V at the 97 % maximum); SLUSFN4A p.28 also states that a /CE toggle after termination starts a new cycle, so the status is B | None documented; burst entry from a drained VCHG passes through a nominal 5 ms tTRANS_CHG of unpublished shape (B, gate B4; [D773] section 8.3) | 2-4 s battery detection on any input collapse ([D4015] section 8.4) | Parked VSYS UV fault and 53 mA ACLIM reload unless configured out ([DRAA] sections 6.1, 7.3) |
| HR2 | P / sys; FC charge 1.24-1.75 A at 8.4 V, nominal 1.50 A (H5 F at the low corner with the REGN-divider FC leg; a reference-biased FC leg is not computed in [D798]) | P / sys; 1.25-1.58 A, typical 1.46 A (H5 F at typical; R_FC 3.83 kOhm restores 1.51 A) | P / sys; 1.35-1.77 A, typical 1.60 A (H5 F at the low corner) | P / sys; 1.69 A at IIN 1.00 A | C / sys; 1.51-1.62 A |
| HR3 | C (SYS separate, parity build, 129 us allowance) | C (two hardware layers) | C | C (D-BT-SQ bridge removes the pack isolator) | C (Q5 short leaves the converter charging with PERMIT LOW) |
| HR4 regen ceiling maximum (hard-stop row 1.72 A / 117 us) | 1.61 A, 129 us (C) | 1.715 A, 118 us, extrapolated above the 1.6 A KILIM test point (B) | 1.79 A, 110 us; bench pass <= 110 us, margin < 1 us (C) | 1.649 A, 125 us (C) | 1.687 A, 120 us (C) |
| HR4 FC bus draw after a charger POR or a register loss (limit: 1.20 A arm drop) | After a POR: 1.15 A nominal, margin 0.05 A (0.047 A); pin-to-current accuracy unpublished (U, S1-B6); the IINDPM_ACC proxy at 1 A (880-1000 mA) adds no high-side error (B). After an IINDPM loss (REG_RST, a stray REG06 write or EN_EXTILIM = 0; the watchdog does not reset REG06): 1.15 A only if ILIM_HIZ is re-sampled after qualification (P6, S1-B6 open); if it is sampled once, the regen clamp latched at the Run-entry qualification persists through FC windows and the bound is 1.70-1.76 A (reference-biased 1.55-1.61 A + 0.15 A aux), above the arm drop by 0.56 A and the 1.4 A OC_FC latch by 0.36 A ([EVAL] section 4.1; [D798] section 7.2) | 1.10 A, margin 0.10 A (C) | 1.39 A after an IIN_HOST loss: exceeds by 0.19 A (C) | About 1.15 A in design B (C; band not computed in [D4015]); design A 1.80 A hardware bound | 0.20 A after POR; 1.84 A after a stray write inside a window (C) |
| HR4 status | C nominal (regen); conditional on S1-B6 (FC, register loss); regen accuracy B (S1-B6) | C (continuous pin ceiling; register-defeatable through EN_EXTILIM REG0x14 bit 5, never-write plus readback, as the baseline REG14[1]); regen maximum B (T-7) | C regen; C, weaker than the baseline, in FC mode | C | C |
| HR5 | C by design (cond.) / B watchdog (0.5 s setting) | C; watchdog shortest setting 40 s, no maximum published | P POR / C hold-down / B watchdog (4-7 s) | C / B (DRVCC stage) / sys (no host watchdog) | P intrinsic / C bias (cond.) / B latency; SMBus timeout 4.95 s |

The input at the threshold is the lower of the input-ceiling limit and the charge-current limit ([D773] section 11.3), at a
7.4 V pack and the low tolerance corners; section 5.0 states the threshold floor of each part.

No part has a P or C warm-response figure, so HR1 stays U or B for every part. The BQ25690 and the LTC4015 carry a documented
HR1 hazard that the BQ25798 does not carry, the RAA489110 item is configuration-dependent, and the BQ25773 item is a bench
gate; the BQ25798 carries its own D-BT-SQ hazards P1 and P2 (section 6.6). After a register loss the BQ25773 FC bound (1.39
A) exceeds the 1.20 A arm drop and the 1.247 A H-20 P_MAX. The BQ25798 FC bound after an IINDPM loss stays at 1.15 A only if
ILIM_HIZ is re-sampled after qualification (P6, S1-B6). In the branch the datasheet describes (an ADC read at POR and at each
qualification, held as an IINDPM clamp; SLUSDV2C section 7.3.4 step 6 and section 7.3.4.3 p.27), the bound is 1.70-1.76 A.

### 6.2 Scores and arithmetic

Table 6.1 gives the criterion scores and Table 6.2 the weighted terms (weight x score / 3).

**Table 6.1.** Criterion scores, evidence in brackets ([SCO] Table 10).

| Criterion (weight) | BQ25798 | BQ25690 | BQ25773 | LTC4015 B | RAA489110 |
|---|---|---|---|---|---|
| S1 warm response (15) | 1 (U/B) | 1 (B) | 1 (U) | 1 (B) | 1 (U/B) |
| S2 fail-safe POR (10) | 1 (P/C) | 2 (P) | 2 (P) | 1 (P) | 2 (P) |
| S3 ceiling quality (8) | 2 (B) | 3 (P) | 3 (P) | 3 (C) | 1 (P/C) |
| S4 threshold quality (8) | 2 (B) | 2 (P) | 2 (P/B) | 2 (B; zero-current point 1.15 V typical only, 4015fb p.13) | 1 (P/U) |
| S5 inhibit latency (7) | 1 (U) | 2 (B) | 1 (U) | 1 (U) | 1 (U/B) |
| S6 interlock adders (10) | 0 (C) | 0 (C) | 1 (P/B) | 0 (C) | 0 (C) |
| S7 telemetry (5) | 2 (P) | 0 (P) | 2 (P) | 3 (P) | 2 (P) |
| S8 FC-mode fitness (6) | 1 (P) | 2 (P) | 1 (P) | 0 (P) | 3 (P) |
| S9 rating margin (4) | 0 (P) | 2 (P) | 2 (P) | 1 (P) | 0 (P) |
| S10 layout (7) | 1 (P) | 1 (P) | 0 (P) | 1 (P) | 0 (P) |
| S11 package (3) | 1 (P) | 1 (P) | 1 (P) | 2 (P) | 1 (P) |
| S12 stock (5) | 2 (P/U) | 1 (cap) | 2 (P) | 1 (cap) | 1 (cap) |
| S13 cost (2) | 1 (cap) | 1 (cap) | 1 (cap) | 1 (cap) | 1 (cap) |
| S14 round-6 findings (5) | 2 (C) | 2 (C) | 2 (P) | 3 (C) | 1 (C) |
| S15 input capacitance (3) | 3 (C) | 3 (C) | 2 (C) | 2 (C) | 2 (C) |
| S16 topology barrier (2) | 0 (P) | 0 (C) | 0 (P) | 3 (P) | 0 (P) |

**Table 6.2.** Weighted terms and totals ([SCO] Table 11).

| Part | S1 | S2 | S3 | S4 | S5 | S6 | S7 | S8 | S9 | S10 | S11 | S12 | S13 | S14 | S15 | S16 | Total | Margin |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BQ25798 | 5.00 | 3.33 | 5.33 | 5.33 | 2.33 | 0 | 3.33 | 2.00 | 0 | 2.33 | 1.00 | 3.33 | 0.67 | 3.33 | 3.00 | 0 | **40.3** | - |
| BQ25690 | 5.00 | 6.67 | 8.00 | 5.33 | 4.67 | 0 | 0 | 4.00 | 2.67 | 2.33 | 1.00 | 1.67 | 0.67 | 3.33 | 3.00 | 0 | **48.3** | +8.0 |
| BQ25773 | 5.00 | 6.67 | 8.00 | 5.33 | 2.33 | 3.33 | 3.33 | 2.00 | 2.67 | 0 | 1.00 | 3.33 | 0.67 | 3.33 | 2.00 | 0 | **49.0** | +8.7 |
| LTC4015 B | 5.00 | 3.33 | 8.00 | 5.33 | 2.33 | 0 | 5.00 | 0 | 1.33 | 2.33 | 2.00 | 1.67 | 0.67 | 5.00 | 2.00 | 2.00 | **46.0** | +5.7 |
| RAA489110 | 5.00 | 6.67 | 2.67 | 2.67 | 2.33 | 0 | 3.33 | 6.00 | 0 | 0 | 1.00 | 1.67 | 0.67 | 1.67 | 2.00 | 0 | **35.7** | -4.7 |

The three leading challengers gain over the BQ25798 on S3 (a continuously read ceiling with published accuracy) and S9 (a
40-45 V rating); the BQ25690 and the BQ25773 also gain on S2 (no charge out of POR). Each loses part of that gain elsewhere:
the BQ25690 on S7 (no ADC), the BQ25773 on S10 (the hardest layout) and S15, and the LTC4015 on S8 (CV +-1.25 %). LTC4015
design A scores 40.7 (+0.3), because its FC ceiling is a register value only (S3 = 1) and its S6 is 0. Design A has 7 adders,
inside the 6-8 band (S6 = 1), but the S6 score-0 anchor also covers "an adder needed to defeat a register-defeatable pin"
([CRIT] section 3.1). Adder A3 (the DRVCC stage) exists because VIN_UVCL_SETTING = 0x00 defeats the UVCLFB clamp (4015fb
p.46), so the score-0 clause applies ([D4015] section 9.4). With S6 = 1, design A would score 44.0 (+3.7); the outcome does
not change, because design A also fails condition 1.

Table 6.3 compares the build and supply criteria with their evidence status ([SCO] Table 7).

**Table 6.3.** Power stage, layout, package, stock and cost.

| Part | Power stage | Package | Stock | IC price; stage cost per board |
|---|---|---|---|---|
| BQ25798 | Integrated; one 2.2 uH inductor at 750 kHz; 27-28 parts | VQFN-HR 29, 4.0 x 4.0 mm, 0.4 mm, no exposed pad | 415 146 at the TI store (P); second source U | USD 5.04 at 1-99 (P); USD 10-12 (passives UNVERIFIED) |
| BQ25690 | Integrated; external BATFET, two shunts, 10 uH at 450 kHz; about 30 parts plus a 3-part monitor | WQFN-HR 26, 4.0 x 3.5 mm, inner pad | 176 and 460 (regional snippets, UNVERIFIED) | About USD 5.2 (UNVERIFIED); USD 15-19 with the monitor |
| BQ25773 | 7 N-FETs, 2 inductors, 3 shunts; 57 parts; about 590 mm2 | WQFN-36, 4.0 x 5.0 mm, 0.4 mm, one exposed pad | 15 695 at the TI store (P), single source | USD 3.14, quantity unstated (UNVERIFIED); USD 13-20 |
| LTC4015 | Buck with INFET and OUTFET, 15 uH, 2 shunts; about 43 parts; off-CCB bridge fuse | QFN-38, 5 x 7 mm, 0.50 mm, one exposed pad | 47 191 and 639 (snippets, UNVERIFIED); lifecycle U | USD 8-17 (UNVERIFIED); USD 19-30 |
| RAA489110 | 5 N-FETs including the BFET; about 32 parts | TQFN-32, 4.0 x 4.0 mm, 0.40 mm, one exposed pad | "In stock", no quantity (UNVERIFIED) | USD 4.51-4.96 (UNVERIFIED); USD 11-15 |

The BQ25798 has the smallest power stage of the five and the only primary stock figure above 100 000 units. Every S13 score
is capped at 1, because the passive and power-stage prices of every part are allowances.

### 6.3 Decision rule

Table 6.4 applies the four conditions of section 1.5 ([SCO] Table 12).

**Table 6.4.** Decision rule against the baseline (40.3).

| Condition | BQ25690 | BQ25773 | LTC4015 B | RAA489110 |
|---|---|---|---|---|
| 1. Must-haves; no conditional M5-M7 where the BQ25798 has P | Open (M5 B on the entry level, T-5.HIZ) | Met under a symmetric M7 grading (the BQ25798 M7 is itself conditional on EN_EXTILIM) | Fails (M3 F) | Not decided (M5 c, same class as the BQ25798 S1-B3 item) |
| 2. Margin >= 10 points | Not met (+8.0) | Not met (+8.7) | Not met (+5.7) | Not met (-4.7) |
| 3. No major R6 finding reopened | Met (provisional) | Met (provisional) | Met | Fails (finding 8) |
| 4. S1 >= baseline S1 | Met (1 = 1) | Met (1 = 1) | Met (1 = 1) | Met (1 = 1) |
| Outcome | Alternate, pending T-5.HIZ | **Alternate** | Not eligible without rulings R-M3, R-BR, R-INH | Below the baseline |

No challenger meets condition 2. The BQ25773 is the only part that meets conditions 1, 3 and 4 on present evidence;
condition 3 is met provisionally, pending ruling R-S14.

### 6.4 Sensitivity

Each scenario of Table 6.5 changes one assumption from section 6.2 unless stated ([SCO] Table 13).

**Table 6.5.** Totals and margins over the BQ25798 (margin in brackets).

| Scenario | BQ25798 | BQ25690 | BQ25773 | LTC4015 B | RAA489110 |
|---|---|---|---|---|---|
| Base | 40.3 | 48.3 (+8.0) | 49.0 (+8.7) | 46.0 (+5.7) | 35.7 (-4.7) |
| A1: HR1 resolves badly for the three TI parts (S1 0) | 35.3 | 43.3 (+8.0) | 44.0 (+8.7) | 46.0 (+10.7) | 35.7 (+0.3) |
| A2: HR1 resolves badly for the BQ25798 only (S1 0) | 35.3 | 48.3 (+13.0) | 49.0 (+13.7) | 46.0 (+10.7) | 35.7 (+0.3) |
| A3: HR1 resolves well for every part (S1 2) | 45.3 | 53.3 (+8.0) | 54.0 (+8.7) | 51.0 (+5.7) | 40.7 (-4.7) |
| A4: LTC4015 S1 read as 2 | 40.3 | 48.3 (+8.0) | 49.0 (+8.7) | 51.0 (+10.7) | 35.7 (-4.7) |
| B1: S12 and S13 weights 0 (renormalised) | 39.1 | 49.5 (+10.4) | 48.4 (+9.3) | 47.0 (+7.9) | 35.8 (-3.2) |
| B2: S12 and S13 weights doubled | 41.4 | 47.4 (+5.9) | 49.5 (+8.1) | 45.2 (+3.7) | 35.5 (-5.9) |
| B3: S12 and S13 weights tripled | 42.4 | 46.5 (+4.1) | 50.0 (+7.6) | 44.4 (+2.0) | 35.4 (-7.0) |
| C1: stock and price caps lifted (best case) | 43.3 | 52.3 (+9.0) | 52.0 (+8.7) | 50.0 (+6.7) | 38.7 (-4.7) |
| D1: strict S14 (longer never-write list reopens finding 8) | 40.3 | 46.7 (+6.3) | 47.3 (+7.0) | 46.0 (+5.7) | 35.7 (-4.7) |
| D2: BQ25773 needs a contingent adder (S6 0) | 40.3 | 48.3 (+8.0) | 45.7 (+5.3) | 46.0 (+5.7) | 35.7 (-4.7) |
| D3: BQ25690 S6 on its dossier 8-adder basis | 40.3 | 51.7 (+11.3) | 49.0 (+8.7) | 46.0 (+5.7) | 35.7 (-4.7) |
| E1: challengers pessimistic (D1 with BQ25690 S5 1 and BQ25773 S6 0) | 40.3 | 44.3 (+4.0) | 44.0 (+3.7) | 46.0 (+5.7) | 35.7 (-4.7) |
| E2: challengers optimistic (C1 with D3) | 43.3 | 55.7 (+12.3) | 52.0 (+8.7) | 50.0 (+6.7) | 38.7 (-4.7) |

The sensitivity supports five statements:

1. **HR1 decides the switch, through the BQ25798 bench gate.** A uniform change of S1 for the TI parts (A1, A3) leaves their
   order and margins unchanged. A change that affects the BQ25798 alone (A2) moves every finalist except the RAA489110
   (+0.3) above 10 points; in that case the BQ25798 fails M9 outright and the decision is no longer a scoring question.
2. **The LTC4015 crosses 10 points only where it stays ineligible.** In A1 and A4 it reaches +10.7, but it still fails
   condition 1 (M3 F). If the TI warm response fails outright, it becomes the only finalist with a modelled warm path,
   and it needs rulings R-M3, R-BR and R-INH and bench gates L-2 and L-3.
3. **Stock and cost weights move the order, not the outcome.** With the weights set to 0 (B1) the BQ25690 passes 10 points
   (+10.4) and the LTC4015 reaches +7.9; condition 1 stays open for the BQ25690 on T-5.HIZ. With the weights doubled or
   tripled (B2, B3) the BQ25773 leads and every margin falls further below 10.
4. **The BQ25690 crosses 10 points only on its own adder count** (D3, +11.3) or in the compound optimistic case (E2, +12.3);
   condition 1 stays open on T-5.HIZ in both. Under the strict S14 reading (D1), the BQ25690 and the BQ25773 each lose
   1.7 points and fail condition 3, because finding 8 is major. In the pessimistic compound case (E1) the two TI challengers
   fall to +4.0 and +3.7.
5. **Strict M2 reading.** If the IC pins must reach 35 V, the BQ25798 is not eligible, and the decision is a forced choice
   among the finalists. The BQ25773 (49.0) and the BQ25690 (48.3) are tied within the evidence band. The order then follows
   the rule of succession of section 7: decision-rule condition 1 first, because it is the must-have test and does not depend
   on the baseline score. The BQ25773 meets condition 1 and leads while T-5.HIZ is open. If T-5.HIZ passes, the BQ25690
   leads, for three reasons: its FC bus draw after a POR is 1.10 A, inside the 1.20 A arm drop (BQ25773: 1.39 A after an
   IIN_HOST loss); it is an integrated stage of about 30 parts (BQ25773: 57 parts, three hot loops); and its HR1 hazard is
   decided by one bench gate (T-3.VRECHG) with no hardware change, whereas the BQ25773 burst-entry hazard needs a hardware
   remedy that is not yet proven. However, the BQ25690 has five disadvantages. It has no ADC. Its /CE pin does not stop
   conversion. Its watchdog is 80 times slower than the baseline setting. One register bit (EN_EXTILIM) removes both its HIZ
   inhibit and its ceiling, whereas the BQ25773 HIZ entry has no register override ([D773] section 3 M5). It delivers
   2.62 A at an 8.4 V pack, below the BQ25798 3.10 A image setting but 4.0 % above the HR1 input condition (BQ25773:
   2.77 A, also structural; Table 5.1; [SCO] section 8.5).

The three reasons of statement 5 are weighed above the five disadvantages. The first and third reasons concern an HR4 or
HR1 hazard with a hard-stop consequence (the arm drop, the burst-entry transition). The second reason concerns stage
complexity (part count and hot loops). The EN_EXTILIM item is a register-loss ceiling hazard (HR4). It is set against the
BQ25773 register-loss bound of 1.39 A after an IIN_HOST loss (reason 1), so the register-loss hazards of the two parts
offset each other. The delivered-current, ADC, /CE and watchdog items are margin notes under the criteria of section 1.3:
M4 is a capability test, and the 3.10 A figure is a design setting (section 5.0). The operator may change this weighing
through ruling R-I3A1 (Table 8.0a). Under a yes ruling, both TI challengers fail the delivered-current requirement
structurally (Table 5.1), so neither can lead.

The protected-standoff reading also re-admits every part that [SCR] rejected on M2 F alone: the BQ25713, BQ25720, BQ25723,
BQ25731, BQ25790 and BQ25792 (TI), the RT9490/RT9490S, RT9492 and RT9478M (Richtek), the SGM41575 (SG Micro), the
MAX77960/MAX77961 (ADI), the ISL9241 (Renesas) and the SMBus buck chargers of the quick-dismissal list (BQ25710, BQ25700A,
BQ25703A, BQ24725A, BQ24735, BQ24780S, BQ24800, LTC1760). None has a 2026-11-10 dossier. Apart from the RT9492 (24 V
operating, [SCR] row 10), none was checked against the 22.28 V operating condition of the reading. The class cannot
produce a switch. A BQ25798-class twin that differs from the baseline only by a non-charging POR (S2 = 3), primary stock
(S12 = 3) and cost (S13 = 3) scores 50.0 against the 50.3 threshold of condition 2 (`calc/score.py`). A 30 V part cannot
raise S9, S6 or S10 above the baseline. The BQ25713-class parts (RT9478M, BQ25720/23/31) carry the 19.52 V VINDPM ceiling
and score about 34.3 on the provisional, not dossier-backed BQ25713 analogue. The re-admission therefore produces no
challenger under the decision rule ([SCO] section 8.6).

The value of the re-admission is a second source. The RT9492 is a functional BQ25798 twin with the same 30 V ceiling and
autonomous POR charging, so it can at most equal the BQ25798; it is not pin-compatible (RT9492_DS-05; [SCR] row 10). The
RT9490 and the SGM41575 are further candidates, not yet screened against the operating condition. The BQ25792 shares the
BQ25798 evaluation board, the U1 footprint (VQFN-HR 29, BQ25792RQM) and the 3.6-24 V operating range, and it lacks MPPT
and backup mode ([SCR] sections 2.2 and 3, from SLUUCB5E p.3, p.19, p.23). Its datasheet SLUSDG1, its absolute maximum rating and
its ACOVP and POR defaults remain UNVERIFIED, because every ti.com URL for the part, including the product page, returned
HTTP 404 on 2026-11-10 (Table 8.1 item 21).

### 6.5 Switching margin

The 10-point margin of condition 2 is kept for three reasons ([SCO] section 9):

1. **Switching cost.** Only forward work that a challenger adds over the baseline enters the margin. That work is the CCB
   layout in progress (extent not recorded in the repository), one register image table and poll schedule of the kind in
   [EVAL] section 4.5, the IC-specific part of the test registry, and at least one review cycle of the same depth. About 40
   of the 112 registry entries name BQ25798 registers or I2C behaviour ([WD] section I); the eFuse, comparator, motherboard
   and watchdog entries carry over to any IC. The firmware driver, never-write list and readback image are owed for every
   part, including the BQ25798: `teensy_controller.ino` contains no BQ25798 code, and [EVAL] section 5.2 lists the driver as
   new work. The BQ25773 and BQ25690 dossiers already give their never-write lists ([D773] section 5.1; [D690] section 14).
   The six review rounds and the registry entries already written are spent whichever part is chosen, so they do not enter
   the margin. The 10-point figure is a judgement, not a quantity derived from this cost. The BQ25773 fails only condition 2,
   by 1.3 points, so this judgement decides its status as the alternate.
2. **Evidence band.** The base margins (5.7-8.7 points) lie inside the movement that the open fetches and counts produce:
   the stock and price caps move single parts by 3.0-4.0 points, the S6 counting reading by 3.3 points, and the S14 reading
   by 1.7 points. Closed adversely together (BQ25773 S6 0 and S14 1; baseline S12 3 and S13 3), they reduce the BQ25773
   margin to +0.7; no combination of these items reverses a sign. The BQ25773 S6 item closes on bench gates B4 and B13
   ([SCO] section 11.2), so the band is not fetch-only.
3. **Scale of the margin.** Ten points equal two levels of S1, the heaviest criterion (5.0 points per level). No challenger
   can earn that gap through S1 while the BQ25798 is eligible: the evidence cap holds every S1 at 1 or 2, so the largest S1
   lead over an eligible baseline is one level (5.0 points). The equivalence states the size of the margin only; the route
   to it is the BQ25798 bench gate S1-B4 (section 6.4, statement 1).

The three reasons bound what can change the outcome. Every criterion that separates the BQ25773 from the BQ25798 (S2, S3,
S6, S9, S10, S15) already rests on P or C evidence, and the open criteria (S1, S4, S5, S12, S13) are shared at equal scores.
The BQ25773 margin therefore stays at +8.7 under every symmetric closure of the open evidence; scenario A3 is one instance.
While the BQ25798 is eligible, the BQ25773, the only challenger that meets condition 1, reaches condition 2 only through an
asymmetric bench outcome. The other routes past 10 points (B1, D3, E2, A4) leave condition 1 open or failed. A challenger
that passes its warm-response gate before S1-B4 is run gains one S1 level and, provisionally, meets condition 2 (BQ25773:
54.0, +13.7). Once S1-B4 runs, a pass restores the +8.7 margin. A failure makes the baseline ineligible (scenario A2 if a
challenger passes its equivalent gate; scenario A1 if the gate fails for all three TI parts). The switch question is
therefore decided by bench gate S1-B4 and by the switching cost of reason 1.

The margin is not lowered for the strict M2 case, because that case is not a switch decision: the baseline is then
ineligible.

### 6.6 Round-6 findings closed and reopened

Four findings of review round 6 depend on the IC ([CRIT] section 3.4). Table 6.6 gives the effect of each part ([SCO] Table 8).

**Table 6.6.** IC-dependent round-6 findings.

| R6 finding | BQ25798 | BQ25690 | BQ25773 | LTC4015 B | RAA489110 |
|---|---|---|---|---|---|
| 1 VREG corruption, no fixed pack OVP (major) | Kept, more serious: a CELL write lifts the VREG bound to 18.8 V until POR | Kept, mitigated: VREG clamped by strap; one REG0x1B write may move it (U, T-14) | Kept: CHARGE_VOLTAGE register; SYSOVP_MAX can raise SYSOVP to 27 V | **Closed**: CV DAC capped at 4.2 V/cell; cell count by strap | Kept: MaxSystemVoltage writable to 18.304 V |
| 8 Loop budget (major) | Kept, eased by 400 kHz on short traces | Kept; 6-7 transactions after every true POR (a purge in Run causes none under the [EVAL] section 4.4 handover; section 5.6) | Kept; never-write list of seven fields | **Closed**: no I2C write per mode change | **Reopened**: about 14 word transactions, about 6.3 ms |
| 10 `chg_src` misattribution (major) | Kept (no ADC accuracy) | Kept (CCB monitor) | Kept (IIN accuracy at 5 A only) | Closed conditionally (IIN ADC accuracy published) | Kept (8-bit, saturates at 1.515 A) |
| 12 Reversal hold at 100 kHz (minor) | Kept, eased | Kept | Kept | **Closed** (hardware mode switching) | Kept |

Three IC-independent findings change with the part ([SCO] section 6.2):

- Finding 2 (D-BT-SQ short, unfused pack on VCHG) reopens in a new form for the LTC4015: the bridge puts the pack permanently
  on the charger output, and a bottom-FET short is a pack short that only the bridge fuse clears.
- Finding 3 (battery-path copper sized below ICHG) reopens for every part as a CCB copper-sizing task, on a basis current of
  3.21 A (BQ25798), 3.36 A (BQ25773) or 3.30 A (LTC4015). The BQ25690 and RAA489110 basis currents are not recorded in
  [SCO] or the dossiers. TODO(verify: set from the chosen ICHG plus tolerance at design time; 3.21 A is the conservative
  floor). The RAA489110 figure of 3.30 A in [DRAA] is a charge-side input-ceiling limit, not a copper basis.
- Findings 13-16 (EVM-carrier geometry) close for every part.

The 2026-11-05 panel and critic rounds left BQ25798-specific open items. Every challenger closes P5 (the 7 V VAC_OVP at POR)
and P6 (ILIM_HIZ sampled only at qualification). No challenger closes P1 (BAT held near 2.5 V behind D-BT-SQ) without a cost:
the burst-entry problem reappears in an equivalent form for each, except for the LTC4015, which removes it by bridging
D-BT-SQ and thereby loses the hard battery disconnect. The ICHG 2.50 A cap of critic item C2 is open for every part on the pack
ruling ([EVAL] section 8.1 item 6; [WD] T-E-11); every part's ICHG range covers 3.1 A, so the CCB adds no limit ([SCO] Table 9).

---

## 7. Recommendation and conditions

**The custom BQ25798 board should continue.** No finalist beats the BQ25798 by the 10-point switching margin, and none
meets all four conditions of the decision rule. The challengers' gains in POR behaviour, ceiling quality and input rating are
real. However, the BQ25690 and the LTC4015 bring a documented hazard that the BQ25798 design does not carry, and the BQ25773
burst-entry item is a bench gate (B4). The BQ25798 shares the FC register-loss class of the BQ25773 unless bench gate S1-B6
shows re-sampling (section 6.1). No challenger reduces the total CCB part count, and none publishes the warm-response
figure that decides HR1.

The **BQ25773** is the alternate on present evidence: it meets conditions 1 and 4, and condition 3 provisionally (ruling
R-S14, section 8.1). Under the strict S14 reading it fails condition 3 and loses alternate status (section 6.4, statement 4).
It has the most different inhibit mechanism among the eligible parts. The **BQ25690** becomes a second alternate if bench
gate T-5.HIZ passes. The LTC4015 is not eligible without rulings R-M3, R-BR and R-INH, and the RAA489110 scores below the
baseline.

The recommendation holds under two conditions:

1. **R-M2.** The operator accepts the protected-standoff reading of M2. Its basis is the TPS26630 OVP cut-off 22.61-23.63 V
   and OVP switch turn-off delay OVP_tOFF(dly) 8.5-14 us (SLVSE94G section 6.5 p.6, section 6.6 p.8). At the 4.30 V/ms regen
   slope ([EVAL] section 2.5) the eFuse output holds at most 0.06 V above the cut-off, so the BQ25798 pins stay at or below
   23.7 V. This level is under the 24 V recommended VBUS maximum and the 25.2 V VBUS_OVP minimum (SLUSDV2C section 6.3 p.7,
   section 6.5 p.9). A conservative reading that adds the 20 mV OVP-pin overdrive of the delay specification (0.39 V at the
   input) gives 24.07 V ([D798] section 3). Bench confirmation at the CCB, both tests with VCHG-IN, U101 OUT and the BQ25798
   VBUS pin scoped:
   (a) a REGEN close at 21.5 V, pass < 24.0 V at the VBUS pin;
   (b) a bench-supply ramp into VCHG-IN at >= 4.3 V/ms through 22.6-23.6 V, pass: U101 OUT trips inside the band and holds
   < 24.0 V, and VBUS_OVP_STAT stays 0.
   Test (b) is required because the 21.5 V of a REGEN close stays 1.11 V below the eFuse OVP band and never exercises the
   OVP response. A hold level between 24.0 V and 25.2 V is outside the recommended range without a VBUS_OVP trip and needs
   an operator ruling. If the operator requires 35 V at the IC pins, the BQ25798 is not eligible, and the rule of succession
   below applies (section 6.4, statement 5).
2. **S1-B4.** If the BQ25798 warm-response bench gate fails while a challenger passes its equivalent gate, the BQ25798 fails
   M9 and the decision is no longer a scoring question (scenario A2 assumes that the challenger passes). The rule of
   succession below applies. If the gate fails for all three TI parts (scenario A1), only the LTC4015 exceeds 10 points
   (+10.7), and it stays ineligible without rulings R-M3, R-BR and R-INH.

**Rule of succession.** When the BQ25798 is ineligible (strict M2, or S1-B4 failed), the order among the challengers follows
decision-rule condition 1 first and the hazard comparison of section 6.4 statement 5 second, as in the rank rule of
section 0.1. The weighted score is not reached, because the two totals lie within the evidence band. Condition 1 comes
first because it is the must-have test and does not depend on the baseline score. The same order applies to both cases:

- while bench gate T-5.HIZ is open, the BQ25773 leads (gates B2, B4, B13), and the BQ25690 is the alternate;
- if T-5.HIZ passes, the BQ25690 leads (gates T-8a, T-3.VRECHG), and the BQ25773 is the alternate;
- the LTC4015 follows only with rulings R-M3, R-BR and R-INH; it becomes the lead only if the TI warm response fails for all
  three TI parts (section 6.4, statement 2).

Both TI leads carry a structural delivered-current shortfall at an 8.4 V pack below the BQ25798 3.10 A image setting
(BQ25690 2.62 A, 4.0 % above the HR1 input condition; BQ25773 2.77 A; Table 5.1). The shortfalls are information only
unless ruling R-I3A1 makes 3.1 A delivered a hard requirement. Under a yes ruling neither TI challenger can lead, and the
rule of succession names no TI part. The LTC4015 (3.105 A minimum, Table 5.1) then remains only with rulings R-M3, R-BR and
R-INH; without them the search reopens.

The 2026-11-05 recommendation to measure two inhibit mechanisms in parallel ([EVAL] section 0.3, P11) remains valid for the
CCB, with the BQ25773 as the second mechanism. The P11 vehicle is unchanged: two BQ25798EVM and one BQ25773EVM (USD 511.90,
[EVAL] section 7), each with a real RT1987 in the D-BT-SQ position ([EVAL] section 0.3, P2). The warm-response,
inhibit-exit and register-remedy gates (S1-B4, S1-B4r, B2, B4 remedies 1 and 2, B13, T-5.HIZ) measure IC properties and
transfer from an EVM to the CCB. The gates that measure the CCB divider or bias (S1-B3, S1-B6, CCB-1, CCB-2, B4 remedy 3)
run on the CCB prototype. S1-B4 runs first, because its failure changes the question (condition 2). No vehicle for T-5.HIZ
is confirmed (BQ25690EVM existence UNVERIFIED, [D690] section 1.3). This document orders nothing.

---

## 8. Open items

### 8.1 Operator rulings

Table 8.0a lists the operator rulings that the recommendation depends on.

**Table 8.0a.** Operator rulings.

| ID | Question | Effect |
|---|---|---|
| R-M2 | Accept the eFuse as the 35 V element (IC rating scored in S9), or require 35 V at the IC pins | Decides whether the BQ25798 is eligible; under the strict reading the rule of succession of section 7 applies (BQ25773 first while T-5.HIZ is open). Under the protected reading the eFuse OVP band (22.61-23.63 V) bounds the VESC cut-off below 22.61 V as fitted and below about 22.9 V for the BQ25798 in any case, so the [EVAL] section 3.2 cut-off lever (23-24 V) is not available; a V-MOT excursion above 22.61 V costs a charger cold start of about 190 ms (section 1.3) |
| R-S14 | Whether a longer never-write list counts as a reopening of R6 finding 8 when the transaction count is unchanged | Decides condition 3 for the BQ25690 and the BQ25773 |
| R-M3, R-BR, R-INH, R-FCA | LTC4015: CV tolerance or code-30 setpoint; fused D-BT-SQ bridge; two-stage inhibit in place of a pin; design A FC bound ([D4015] section 15.1) | Needed only if the TI warm response fails |
| R-FCCEIL | FC ceiling position for every TI finalist: no setting of a divider-tolerance or pin-accuracy band meets both H5 at the low corner (ceiling minimum 0.85-0.86 A) and the 1.20 A arm drop at the high corner (ceiling maximum 1.05 A); for the BQ25798 the choice is the REGN-divider FC leg (H5 F at 1.24 A worst case) or a reference-biased FC leg (band not computed, pin accuracy B until S1-B6) | Needed for the adopted part |
| R-CEIL798 | BQ25798 regen ceiling: reference-biased divider (1.55-1.61 A, 129 us allowance) or REGN divider (1.42-1.81 A, S1-B3 tightened to <= 108 us) ([D798] section 15.1 item 2) | Sets the BQ25798 HR1 charge at an 8.4 V pack at the nominal ICHG (3.10 A or 2.91 A); about 2.90 A in either case at the extrapolated ICHG low corner unless ICHG is set to 3.32 A |
| Pack limit | Maximum pack charge current for a 3.1 A or higher ICHG setting ([EVAL] section 8.1 item 6) | Applies to every part |
| R-I3A1 | Whether 3.1 A delivered at an 8.4 V pack and the low tolerance corners is a hard requirement, or HR1 (>= 23 W input at the threshold) alone governs | If a hard requirement: the BQ25690 (2.62 A) and the BQ25773 (2.77 A) fail it structurally, and the BQ25798 needs ICHG 3.32 A (copper basis 3.44 A) and the pack limit, and neither TI challenger can lead; with the BQ25798 also ineligible (strict M2 or S1-B4 failed), no TI successor remains, and only the LTC4015 route (R-M3, R-BR, R-INH) or a new search is left (section 7); if not: Table 5.1 is information only (section 5.0) |

### 8.2 Bench gates that can change the outcome

The vehicle and order of each gate follow section 7 (P11 paragraph). The costs carried by the sources are USD 156.45
per BQ25798EVM, USD 199.00 per BQ25773EVM and USD 511.90 for the P11 set, with 4-6 bench days for the S1 stage ([EVAL]
section 7). Table 8.0b lists the gates.

**Table 8.0b.** Bench gates that can change the outcome.

| Gate | Part | Vehicle; order | Effect on the decision |
|---|---|---|---|
| S1-B4 / S1-B4r | BQ25798 | BQ25798EVM with a real RT1987 in the D-BT-SQ position ([EVAL] section 6.2); first | Decides M9 for the baseline; a failure while a challenger passes its equivalent gate makes the baseline ineligible (scenario A2); a failure for all three TI parts leaves only the ineligible LTC4015 above 10 points (scenario A1) |
| S1-B3 | BQ25798 | BQ25798 CCB prototype | Hard-stop latency <= 115 us (reference-biased ceiling); EN_EXTILIM = 0 check. If EN_EXTILIM = 0 removes the < 0.75 V stop, the BQ25798 M5 becomes a conditional pass of the register-defeat class; the RAA489110 M5 clause of condition 1 is then met (its outcome is unchanged by condition 3 and the -4.7 margin) |
| S1-B6 | BQ25798 | BQ25798 CCB prototype | Decides P6, whether ILIM_HIZ is sampled once or re-sampled after qualification, and therefore the BQ25798 FC bound after an IINDPM loss: 1.15 A if re-sampled, 1.70-1.76 A if sampled once (above the 1.20 A arm drop and the 1.4 A OC_FC latch; Table 6.0b). It also sets the pin-to-current accuracy of the 1.15 A nominal figure |
| CCB-1 | BQ25798 | BQ25798 CCB prototype | SYS separate from BAT and the REGN-ordering closure; a SYS-BAT strap makes the BQ25798 NOT FEASIBLE |
| CCB-2 | BQ25798 | BQ25798 CCB prototype | 3.1 A regen burst at 750 kHz: loss, die temperature, SW1 ringing (M4) |
| T-5.HIZ | BQ25690 | BQ25690 vehicle UNVERIFIED ([D690] section 1.3) | Closes or fails decision-rule condition 1 |
| T-3.VRECHG, T-8a | BQ25690 | BQ25690 vehicle UNVERIFIED ([D690] section 1.3) | Regen capture above about 8.0 V; buck-mode /CE-to-current delay |
| B4, B13 | BQ25773 | BQ25773EVM with a real RT1987 in the D-BT-SQ position (B4 remedies 1 and 2, B13); CCB prototype for B4 remedy 3 | Drained-VCHG remedy against the nominal 5 ms tTRANS_CHG, with the charge-current waveform logged to extract t63 and t10-90; whether the `CHG_QUAL` gates are needed (S6 1 or 0) |
| L-2, L-3 | LTC4015 | Only if the TI warm response fails | Hard stop within 115 us; VC network stability at about 47 nF or less |

### 8.3 Missing primaries, blocked fetches and counts

The operator may fetch the items of Table 8.1 by hand. Where a URL form is not confirmed, the table says so.

**Table 8.1.** Missing primaries and blocked fetches.

| # | Item | URL | Reason | Needed for |
|---|---|---|---|---|
| 1 | TPS26630 datasheet SLVSE94G: OVP response time and output overshoot | https://www.ti.com/lit/ds/symlink/tps2663.pdf (URL confirmed) | Response time closed: OVP_tOFF(dly) 8.5/11/14 us, SLVSE94G section 6.6 p.8 ([D798] section 3); the output overshoot is a bench item (section 7, condition 1, test (b)) | R-M2 |
| 2 | BQ25798 second-source stock | https://www.mouser.com/c/?q=BQ25798RQMR ; https://www.digikey.com/en/products/result?keywords=BQ25798RQMR | Bot wall; HTTP 403 | S12 of the baseline (scenario C1) |
| 3 | BQ25690 product page and store inventory | https://www.ti.com/product/BQ25690 ; https://www.ti.com/storeservices/cart/opninventory?opn=BQ25690RBAR | HTTP 403; store not attempted | S12/S13, the largest single score gain in scenario C1 |
| 4 | BQ25690 distributor listing | https://www.digikey.com/en/products/detail/texas-instruments/BQ25690RBAR/28738808 | Only regional snippets seen | S12 |
| 5 | BQ25773 distributor stock and TI price breaks | https://www.digikey.com/en/products/result?keywords=BQ25773REER ; https://www.mouser.com/c/?q=BQ25773REER | HTTP 403; script-rendered page; TI price endpoint HTTP 404 | S12/S13 |
| 6 | LTC4015 lifecycle, latest revision and stock | https://www.analog.com/en/products/ltc4015.html ; https://www.analog.com/media/en/technical-documentation/data-sheets/LTC4015.pdf ; https://www.digikey.com/en/products/detail/analog-devices-inc/LTC4015EUHF-PBF/5361644 ; https://www.mouser.com/ProductDetail/584-LTC4015IUHF%23PBF | Timeout; HTTP 403; not attempted | M13, confirmation of Rev B, S12 |
| 7 | RAA489110 order data with quantities | https://www.renesas.com/en/products/raa489110 ; https://www.digikey.com/en/products/result?keywords=RAA489110 ; https://www.mouser.com/c/?q=RAA489110 | Dynamic page; HTTP 403; timeout | S12/S13 |
| 8 | RAA489110 firmware or programming guide (referenced on DS p.70) | Renesas device page (not located) | Not located | BATGONE and register 0x4B behaviour |
| 9 | INA228 datasheet (BQ25690 telemetry monitor) | https://www.ti.com/lit/ds/symlink/ina228.pdf | Not fetched | BQ25690 S7 build |
| 10 | MP2769 datasheet | https://www.monolithicpower.com/jp/mp2769.html | MPS login popup; no public mirror | Only MPS part above 35 V with I2C (reserve) |
| 11 | TI parametric table export (Li-ion, 2 cells, VIN max >= 30 V) | https://www.ti.com/en-us/product-category/battery-management-ics/battery-charger-ics/products | JavaScript-rendered; HTTP 403 expected | Completeness of the TI sweep |
| 12 | Silergy SY20776/SY20779 datasheets | https://www.silergy.com/productsview/SY20776QFQ ; https://www.silergy.com/productsview/SY20779QFQ | Server error page | Silergy coverage |
| 13 | BQ25820 /CE-to-ICHG time base (reserve part) | https://www.ti.com/lit/ds/symlink/bq25820.pdf (SLUSFN3B Fig 8-5/8-7, p.67) | Illegible at the rendered resolution | BQ25820 M9 grade (U); a time below 10 ms requires a BQ25820 dossier (section 3.3) |
| 14 | Inductor datasheets (Wurth WE-LHMI 74437346022, TDK SPM6530T-1R0M120) | Vendor sites | Not fetched; ratings UNVERIFIED | BQ25798 power stage |
| 15 | Word-by-word never-write and readback count for the BQ25798, the BQ25690 and the BQ25773 against the BQ25798 image of [EVAL] section 4.5 | Analysis, not a fetch | Not done | R-S14 |
| 16 | LTC4015 design B FC ceiling band with tolerances | Analysis, not a fetch | Not computed | HR4 FC row |
| 17 | TI E2E questions on the BQ25690: /CE delay origin in buck mode, ILIM_HIZ HIZ entry level, CVIN split, EN_CHG after a watchdog expiry | TI E2E forum | Questions, not fetches | T-5.HIZ, T-8a |
| 18 | SC8886 / SC8886S and SC8885S primary datasheets | Not located; reference-design page https://www.we-online.com/en/components/icref/southchip/SC8886S-SC8886S-Demo-Buck-Boost ; Southchip applications support (application@southchip.com) | Primary not located | Confirms the UNVERIFIED M2 F of Table 4.2 |
| 19 | MAX77962 / MAX77963 absolute maximum | https://www.analog.com/media/en/technical-documentation/data-sheets/max77962.pdf | No response | Confirms the UNVERIFIED 30 V class dismissal |
| 20 | BQ25822 SLUSG44A Fig 7-6 | https://www.ti.com/lit/ds/symlink/bq25822.pdf | Not read | BQ25822 M9 (UNVERIFIED) |
| 21 | BQ25792 datasheet (SLUSDG1, listed in SLUUCB5E Table 1-1 p.3) | https://www.ti.com/lit/ds/symlink/bq25792.pdf ; https://www.ti.com/lit/gpn/BQ25792 ; https://www.ti.com/product/BQ25792 | HTTP 404 on all three (2026-11-10); the TI store API still lists BQ25792RQMR (10 964) and BQ25792EVM (131) | BQ25792 as a BQ25798 twin and second source (UNVERIFIED): absolute maximum, ACOVP default and POR behaviour (BQ25790 7 V against BQ25798 26 V, SLUSDV2C Table 4-1 p.3) |
| 22 | ST PM6610 / PM6613N lifecycle and rating | https://www.st.com/resource/en/datasheet/pm6610.pdf ; https://www.st.com/en/power-management/pm6610.html | Timeout | M13 dismissal (UNVERIFIED) |
| 23 | onsemi NCP1871 lifecycle | https://www.onsemi.com/pdf/datasheet/ncp1871-d.pdf | HTML shell instead of the PDF | M13 dismissal (UNVERIFIED) |
| 24 | INA238 datasheet | https://www.ti.com/lit/ds/symlink/ina238.pdf | HTTP 403 | Common-mode rating of a CCB telemetry monitor (BQ25690 build, discrete-buck option) |
| 25 | LM5148 datasheet | https://www.ti.com/lit/ds/symlink/lm5148.pdf | HTTP 403 | Discrete-buck option (Table 3.1, M8 row) |
| 26 | ROHM BD99954 absolute maximum table | https://fscdn.rohm.com/en/products/databook/datasheet/ic/power/battery_management/bd99954xxx-e.pdf (path from the ROHM application note; not confirmed) | Direct fetch returned HTML | Table 3.2 (UNVERIFIED 28 V) |
| 27 | LTC4100 / LTC4101 absolute maximum | https://www.analog.com/en/products/ltc4100.html ; https://www.analog.com/en/products/ltc4101.html | Not fetched; snippets only | Table 3.2 (UNVERIFIED 28 V / 32 V) |
| 28 | Diodes Inc and Toshiba multi-cell charger portfolios | https://www.diodes.com ; https://toshiba.semicon-storage.com | Not swept | Coverage gap of Table 3.2 |
| 29 | Minimum on-time of the BQ25690, the BQ25773 and the RAA489110 | SLUSFN4A; SLUSEK7; R16DS0212EU0202 | Not stated in the dossiers | Table 2.4 |
| 30 | FC-mode VINDPM accuracy at 13.5 V for the BQ25773, the LTC4015 (UVCL code 189) and the RAA489110 | SLUSEK7 EC; 4015fb p.4, p.22; R16DS0212EU0202 p.13 | Not published or not computed | Table 2.2a |

The full lists of blocked fetches per working document are in [SCR] section 6 and in section 15 of each dossier.

### 8.4 Adversarial review of this document

The adversarial review run 001 (2026-11-10) is recorded in `docs/reviews/charger_ic_search_2026-11-10/adversarial_review/`
(`ledger.md`, `run-001-2026-11-10.md`). It raised 47 findings: 5 major, 40 minor and 2 refuted. The Codex reviewer was
unavailable (CLI 0.146.0 is too old for the configured model), so independent reviewers stood in. All accepted findings
are applied in this revision. `calc/bq798_ccb.py` reproduces the BQ25798 low-corner delivered charge (2.90 A), the 3.32 A
setting and the 1.70-1.76 A FC bound after an IINDPM loss. No finding changed the recommendation.

### 8.5 Calculation record

The arithmetic of the scoring and of two dossiers is reproduced by the scripts in
`docs/reviews/charger_ic_search_2026-11-10/calc/`: `score.py` (Tables 6.1, 6.2 and 6.5; its scenario labels differ from
Table 6.5, its values do not), `bq798_ccb.py` ([D798]), `raa_calc.py` and `f1050.py` ([DRAA]). Each result used in this
document is also restated with its inputs in the source document. The downloaded datasheets of the sweeps are not retained
in the repository; the literature-number and page citations in [SCR] and the dossiers are the record.

---

## 9. Sources

### 9.1 Primary datasheets cited through the dossiers

Table 9.1 lists the primary datasheet of each finalist and of the RT1987.

**Table 9.1.** Primary datasheets.

| Part | Document |
|---|---|
| BQ25798 | TI SLUSDV2C, revised June 2026; TI SLUUCB5E (EVM guide, layout only) |
| BQ25690 | TI SLUSFN4A, Revision A, December 2025 |
| BQ25773 / BQ25770G | TI SLUSEK7, September 2024; TI SLUSFK8, April 2024; TI SLUUCY2 (EVM guide) |
| LTC4015 | Analog Devices LTC4015 data sheet Rev B (4015fb), read from a vendor-PDF mirror |
| RAA489110 / RAA489118 / RAA489108 | Renesas R16DS0212EU0202 Rev.2.02; R16UZ0064EU0102 Rev.1.02 (evaluation board manual); R16DS0321EU0200 Rev.2.00; R16DS0159EU0105 Rev.1.05 |
| RT1987 | Richtek RT1987 DS-00, September 2024 (`references/Datasheets/RT1987_DS-00.pdf`) |
| Screened and rejected parts | As cited by literature number and page in [SCR] sections 2 and 3 |

### 9.2 Project documents

- `docs/reviews/charger_ic_search_2026-11-10/screening_criteria.md`
- `docs/reviews/charger_ic_search_2026-11-10/rescreen_2026-11-05_candidates.md`
- `docs/reviews/charger_ic_search_2026-11-10/screening.md`
- `docs/reviews/charger_ic_search_2026-11-10/dossier_BQ25798.md`
- `docs/reviews/charger_ic_search_2026-11-10/dossier_BQ25690.md`
- `docs/reviews/charger_ic_search_2026-11-10/dossier_BQ25773_SMBus_twin_BQ25770G.md`
- `docs/reviews/charger_ic_search_2026-11-10/dossier_LTC4015.md`
- `docs/reviews/charger_ic_search_2026-11-10/dossier_RAA489110_alternates_RAA489118_RAA489108_in_the_same_dossier.md`
- `docs/reviews/charger_ic_search_2026-11-10/scoring.md`
- `docs/reviews/charger_ic_search_2026-11-10/calc/` (score.py, bq798_ccb.py, raa_calc.py, f1050.py)
- `docs/charger_replacement_evaluation_2026-11-05.md`
- `docs/charger_bq25798_wiring_design_2026-11-05.md`
- `docs/reviews/charger_eval_2026-11-05/round3/review_loop.md`
- `docs/battery_isolation_feasibility_2026-11-07.md`

### 9.3 Secondary sources (UNVERIFIED)

Table 3.2 rests on the following secondary sources, consulted 2026-11-10:

- BD99954GW datasheet mirror: https://pdf.jiepei.com/bd99954gw-42468961.html ; ROHM application note
  https://fscdn.rohm.com/en/products/databook/applinote/ic/power/battery_management/bd99954xxx_an-e.pdf ; ROHM evaluation
  board guide https://fscdn.rohm.com/en/products/databook/applinote/ic/power/battery_management/bd99954mwv-evk-101_ug-e.pdf
- LTC4100 / LTC4101 datasheet mirrors: https://pdf.elecfans.com/LINER/LTC4100_09.html ;
  https://manualmachine.com/lineartechnology/ltc4101/8423393-technical-data
