# Charger IC search: scoring of the finalists against the BQ25798 baseline (2026-11-10)

## 1. Scope, sources and status codes

### 1.1 Scope

This document scores the four finalists of the 2026-11-10 charger search against the TI BQ25798 baseline, for the custom
charger board (CCB) that replaces the Silvertel Ag105 (BOM `CHG`) on board rev 20260622. It applies one set of
normalisation rules to the five finalist dossiers, compares the parts on HR1-HR5, interlock hardware, layout, package,
stock, cost and the round-6 review ledger, and runs a sensitivity check. It then decides whether any finalist beats the
BQ25798 by enough to justify a switch.

The finalists are the TI BQ25690, the TI BQ25773 (SMBus twin BQ25770G), the ADI LTC4015 and the Renesas RAA489110 (with
the RAA489118 and RAA489108 as alternates in the same dossier). Parts that the screen rejected are outside the scope of this
document, except for the 30-33 V class that section 2.1 re-admits under the M2 rule.

### 1.2 Sources

Table 1 lists the documents cited in this file.

**Table 1.** Source tags.

| Tag | Document |
|---|---|
| [CRIT] | `screening_criteria.md` (this folder): must-haves M1-M13, scored criteria S1-S16, evidence cap, decision rule |
| [SCR] | `screening.md` (this folder): screening record and provisional scores |
| [RES] | `rescreen_2026-11-05_candidates.md` (this folder) |
| [D798] | `dossier_BQ25798.md` (this folder) |
| [D690] | `dossier_BQ25690.md` (this folder) |
| [D773] | `dossier_BQ25773_SMBus_twin_BQ25770G.md` (this folder) |
| [D4015] | `dossier_LTC4015.md` (this folder) |
| [DRAA] | `dossier_RAA489110_alternates_RAA489118_RAA489108_in_the_same_dossier.md` (this folder) |
| [EVAL] | `docs/charger_replacement_evaluation_2026-11-05.md`, sections 0.2-0.4, 1.1, 2.5, 3.4, 4.5, 5.2 |
| [WD] | `docs/charger_bq25798_wiring_design_2026-11-05.md`, section I (test registry) |
| [R6] | `docs/reviews/charger_eval_2026-11-05/round3/review_loop.md`, review round 6 and its closing pass |

Every candidate fact in this document is taken from a finalist dossier, which cites the primary datasheet by literature
number and page. This document re-reads no primary datasheet. Where a dossier marks a fact UNVERIFIED, U or B, this document
keeps that mark. The arithmetic is reproduced by `calc/score.py` in this folder (its scenario labels differ from Table 13,
its values do not); every result used here is restated with its inputs.

### 1.3 Status codes

The status codes follow [EVAL] section 1.2: P = PROVEN_DATASHEET, C = PROVEN_CALC, B = BENCH_GATE, F = FAIL, U = UNKNOWN or
missing primary, sys = blocked at system level. "c" after a must-have identifier marks a conditional pass ([CRIT] section 2).

---

## 2. Normalisation rules

The five dossiers were written in parallel and apply four rules differently. This section fixes one reading of each rule
and applies it to every part. Section 2.6 lists each score that changes as a result.

### 2.1 M2 rule: protected standoff

The BQ25798 is rated 30 V absolute maximum on VAC1, VAC2, VBUS, PMID and SW1 ([D798] section 3, M2), so it fails M2 as
written. [D798] section 3 and [SCR] section 5.2 require one M2 rule for every part. This document applies the
**protected-standoff reading** as the primary rule:

1. M2 is met at the CCB input when the eFuse of the system core (TPS26630, 60 V part, OVP cut-off 22.61-23.63 V, [D798]
   section 2.2) is the 35 V element and the IC operating range covers 22.28 V without an OVP drop-out.
2. The IC absolute-maximum rating is scored in S9 only. A 30-33 V part scores S9 = 0.
3. The reading applies to every part. The 30-33 V class that [SCR] rejected on M2 F is therefore re-admitted to scoring
   (section 8.6).

The reason for this reading is that the eFuse belongs to the system core of every candidate ([CRIT] section 3.3), and the
V-MOT source is clamped in hardware at 22.28 V maximum. The BQ25798 absolute maximum sits 7.72 V above that clamp. The
TPS26630 OVP cut-off is 22.61-23.63 V and its turn-off delay OVP_tOFF(dly) is 8.5/11/14 us (SLVSE94G section 6.5 p.6,
section 6.6 p.8). At the 4.30 V/ms regen slope the IC pins therefore stay at or below 23.69 V, under the 24 V recommended
VBUS maximum and the 25.2 V VBUS_OVP minimum ([D798] section 3). A conservative reading that adds the 20 mV OVP-pin
overdrive of the delay specification (0.39 V at the input) gives 24.07 V ([D798] section 3). However, the output overshoot
during the turn-off delay is not measured; it is a bench item of R-M2. The reading also caps the VESC cut-off below 22.61 V as fitted and below about
22.9 V in any case, and an excursion above 22.61 V costs a charger cold start of about 190 ms ([D798] section 3). The strict
reading, in which the IC pin
rating must reach 35 V, is evaluated in section 8.5. The choice between the two readings is operator ruling R-M2
(section 11.1).

### 2.2 S1 anchor: strict reading

The S1 score 2 anchor requires that "the datasheet documents" a warm inhibit exit with no deglitch or soft-start, or one
shorter than 1 ms ([CRIT] section 3.1). The dossiers read this anchor differently. [D690] applied it strictly (a 1.2 ms /CE
delay in a typical figure gives 1). [D4015] scored 2 on an inference that the UVCLFB release runs no soft-start; the
datasheet does not state it ([D4015] section 5.1, tagged C). This document applies the strict reading to every part: an
inferred absence of a soft-start scores 1. Every finalist and the baseline then score S1 = 1. The LTC4015 reading of 2 is
evaluated as a sensitivity (section 8.1).

### 2.3 S6 counting rule

[CRIT] section 3.3 counts every resistor network, transistor, gate, comparator or switch that exists only to connect the IC
to the system core. The dossiers counted gate-bias resistors inconsistently. This document counts, for the **minimal build**
of each part (the build that provides the same functions as the BQ25798 minimal build of [D798] section 9.2):

- every package, including each channel package once;
- every resistor that biases a gate or a pin of an adder transistor;
- the mode-switched ceiling leg, where the part needs one to give a hardware FC ceiling;
- a keep-alive only where the dossier makes it mandatory.

Single-fault redundancy (redundant pull-ups, far-end readback, second series channels) is counted separately as the
**parity build** and does not enter S6. Section 4 gives the counts.

### 2.4 S14 rule for R6 finding 8

[CRIT] section 3.4 counts a candidate as reopening R6 finding 8 when it makes the I2C burden worse: more never-write
registers, a slower ADC or more writes per mode change. The dossiers did not tabulate the never-write lists word by word.
This document applies the following rule. Finding 8 counts as reopened only where the dossier shows a larger burden at first
order (more transactions per safety-verify cycle or per mode change). A longer never-write list that the dossier shows to fit
the same class of transaction is scored net 0, with the strict reading as a sensitivity (section 8.4). On this rule the
RAA489110 reopens finding 8 (about 14 word transactions, about 6.3 ms, against one 11-byte burst of about 1.4 ms, [DRAA]
section 14). The BQ25690 and the BQ25773 do not reopen it on present evidence.

### 2.5 Builds scored

Table 2 states the build that this document scores for each part.

**Table 2.** Builds scored.

| Part | Build scored | Source |
|---|---|---|
| BQ25798 | CCB minimal build with the reference-biased regen ceiling (1.55-1.61 A, hard-stop allowance 129 us); SYS a separate capacitor-only node | [D798] sections 2.2, 7.2, 9.2 |
| BQ25690 | R_FC 4.02 kOhm / R_RG 4.99 kOhm, /CE per burst, static ILIM_HIZ HIZ drive from a VCHG-IN-derived rail, CCB current monitor | [D690] sections 5.2a, 7.2, 10.2 |
| BQ25773 | Recommended build: 2.5 V reference-biased ILIM_HIZ divider, no FRC_CONV_OFF fast path, REG0x30 never written, no keep-alive | [D773] sections 7.3, 9.2, 16.1 |
| LTC4015 | Design B (hardware FC ceiling and UVCLFB divider switch keyed to FCC_net), the like-for-like build; design A shown beside it | [D4015] sections 9.2-9.4 |
| RAA489110 | Equal-function build: BATGONE network, mandatory keep-alive, FC eFuse ILIM leg | [DRAA] section 9.2 |

### 2.6 Score changes from the dossiers

Table 3 lists every criterion whose score in this document differs from the dossier score.

**Table 3.** Scores changed by the normalisation rules.

| Part | Criterion | Dossier score | Score here | Rule |
|---|---|---|---|---|
| BQ25690 | S6 | 1 (8 adders) | 0 (9 adders) | Section 2.3: the gate pull-down of the regen-leg FET is counted, as the FC-leg gate pull-up is counted for the BQ25798 |
| BQ25773 | S6 | 1 (7 adders) | 1 (8 adders) | Section 2.3: the gate bias of Q_FC is counted; the score stays in the 6-8 band |
| LTC4015 | S1 | 2 | 1 | Section 2.2: the warm UVCLFB exit is inferred, not documented |
| LTC4015 | Total | 51.0 (design B) | 46.0 (design B) | Consequence of the S1 change |

The BQ25798 is scored as in [D798] section 16 (S2 1, S6 0, S8 1, S12 2, S13 1, S16 0). The [SCR] section 4.1 provisional
baseline of about 45 is superseded, and the [D690] comparison against it (51.7 against 45.0) is restated in section 7.

---

## 3. Must-haves and HR1-HR5

### 3.1 Must-have outcome

Table 4 gives the must-have outcome of each part under the M2 rule of section 2.1. Items not named pass on P or C evidence.

**Table 4.** Must-have outcome.

| Part | Fails | Conditional passes | Decision-rule condition 1 ([CRIT] 3.5) |
|---|---|---|---|
| BQ25798 | None (M2 c as protected standoff) | M2 (eFuse OVP response U), M4 (B, loss 2.11 W at 20 V), M5 (stop level 0.75 V / 1 V P, SLUSDV2C p.27; the EN_EXTILIM = 0 interaction with the stop is B, bench S1-B3; EN_EXTILIM POR 1, reset by REG_RST only, Table 7-30 p.78), M7 (EN_EXTILIM REG14[1]), M9 (exit timing U/B), M10 (unpowered pins U) | Baseline |
| BQ25690 | None | M4 (B), M5 (ILIM_HIZ HIZ entry level has a MIN only, B), M7 (EN_EXTILIM REG0x14 bit 5; the same bit disables HIZ entry through ILIM_HIZ, [D690] section 3 M5), M8 (FORCE_VINDPM reset by the watchdog), M9 (/CE delay typical, VRECHG start condition), M10, M11 (CCB monitor) | **Open**: M5 is B on the published HIZ entry level (VIH_ILIM_HIZ MIN only), where the BQ25798 has P (0.75 V / 1 V); the BQ25798's own M5 B (EN_EXTILIM interaction, S1-B3) is a different sub-claim that [CRIT] M5 admits with readback. The status holds until bench gate T-5.HIZ passes |
| BQ25773 | None | M7 (EN_EXTILIM at two addresses, EN_IIN_DPM, VILIM_ENZ), M9 (exit latency unpublished), M10 | **Met** under a symmetric M7 grading: the BQ25798 M7 is itself conditional ([D773] section 16.3) |
| LTC4015 | **M3 F** (CV +-1.25 %; code 30 reverts to 4.20 V/cell after every POR) | M5 (no inhibit pin; UVCLFB clamp register-defeatable; DRVCC stage B), M8 (hold-state draw not tabulated; 5-20 mA minimum operating current, U/B), M9, M13 (U) | **Fails**: M3 F |
| RAA489110 | None | M5 (BATGONE defeated by Control4 bits 15 and 14), M7 (four register defeat paths), M8 (parked VSYS UV fault), M9, M13 (UNVERIFIED) | **Not decided on M5**: the BATGONE register defeat (Control4 bits 15, 14; POR 0; readback) is the class [CRIT] M5 admits and on which the BQ25798 is itself B (S1-B3); condition 3 fails (finding 8) and the score is -4.7 |

### 3.2 HR1-HR5 with margins

Table 5 gives the HR status codes and the governing margins. The margins are taken from the dossiers at the scored builds.

**Table 5.** HR1-HR5 status and margins.

| Req | BQ25798 | BQ25690 | BQ25773 | LTC4015 (design B) | RAA489110 |
|---|---|---|---|---|---|
| HR1 status | U (B) | U (B) | U (B) | B | U (B) |
| HR1 input at the threshold (pass >= 23 W) | 24.8 W (charge-limited, 7.4 V pack, ICHG 3.1 A, eta 0.925), +7.8 % (C); 23.2 W at the ICHG -6.5 % corner (accuracy given only at 2 A, DS EC p.11; extrapolation U), +0.8 %; input-ceiling capability 28.9 W (1.55 A x 18.62 V) | 23.9 W (1.285 A x 18.62 V), +4.0 % (C) | 23.7 W (charge-limited, 7.4 V pack), +3.0 % (C) | 24.0 W (charge-limited, 7.4 V pack), +4.3 % (C) | 24.4 W (charge-limited, 7.4 V pack, eta 0.94 assumed), +6.1 % (C) |
| HR1 charge at an 8.4 V pack, threshold floor | 3.10 A at the nominal ICHG (input-ceiling limit 3.18 A, reference-biased ceiling); about 2.90 A at the extrapolated ICHG low corner (U); a 3.32 A setting gives 3.10 A | 2.62 A at the ceiling minimum; below the 3.10 A image setting; capture above VRECHG (8.02-8.15 V) not established | 2.77 A at the ceiling minimum (1.30 A x 18.81 V, eta 0.95); below the 3.10 A image setting; a higher CHARGE_CURRENT setting does not close it | 3.105 A minimum | 3.103 A minimum |
| HR1 documented hazard (conditional; bench gate) | None documented (above-2 A ICHG accuracy U) | /CE edge starts a cycle only with SRN < VRECHG ([D690] section 8.3); about 25-38 % of the 7.4-8.4 V window (8.022 V at the POR setting, 8.148 V at the 97 % maximum); SLUSFN4A p.28 also states that a /CE toggle after termination starts a new cycle, so the status is B | None documented; burst entry from a drained VCHG passes through a nominal 5 ms tTRANS_CHG of unpublished shape (B, gate B4; [D773] section 8.3) | 2-4 s battery detection on any input collapse ([D4015] section 8.4) | Parked VSYS UV fault and 53 mA ACLIM reload unless configured out ([DRAA] sections 6.1, 7.3) |
| HR2 | P / sys; FC charge 1.24-1.75 A at 8.4 V, nominal 1.50 A (H5 F at the low corner with the REGN-divider FC leg; a reference-biased FC leg is not computed in [D798]) | P / sys; 1.25-1.58 A, typical 1.46 A (H5 F at typical; R_FC 3.83 kOhm restores 1.51 A) | P / sys; 1.35-1.77 A, typical 1.60 A (H5 F at the low corner) | P / sys; 1.69 A at IIN 1.00 A | C / sys; 1.51-1.62 A |
| HR3 | C (SYS separate, parity build, 129 us allowance) | C (two hardware layers) | C | C (D-BT-SQ bridge removes the pack isolator) | C (Q5 short leaves the converter charging with PERMIT LOW) |
| HR4 regen ceiling maximum (hard-stop row 1.72 A / 117 us) | 1.61 A, 129 us (C) | 1.715 A, 118 us, extrapolated above the 1.6 A KILIM test point (B) | 1.79 A, 110 us; bench pass <= 110 us, margin < 1 us (C) | 1.649 A, 125 us (C) | 1.687 A, 120 us (C) |
| HR4 FC bus draw after a charger POR or a register loss (limit: 1.20 A arm drop) | After a POR: 1.15 A nominal, margin 0.05 A (0.047 A); pin-to-current accuracy unpublished (U, S1-B6); the IINDPM_ACC proxy at 1 A (880-1000 mA) adds no high-side error (B). After an IINDPM loss (REG_RST, a stray REG06 write or EN_EXTILIM = 0; the watchdog does not reset REG06): 1.15 A only if ILIM_HIZ is re-sampled after qualification (P6, S1-B6 open); if it is sampled once, the regen clamp latched at the Run-entry qualification persists through FC windows and the bound is 1.70-1.76 A (reference-biased 1.55-1.61 A + 0.15 A aux), above the arm drop by 0.56 A and the 1.4 A OC_FC latch by 0.36 A ([EVAL] section 4.1; [D798] section 7.2) | 1.10 A, margin 0.10 A (C) | 1.39 A after an IIN_HOST loss: exceeds by 0.19 A (C) | About 1.15 A in design B (C; band not computed in [D4015]); design A 1.80 A hardware bound | 0.20 A after POR; 1.84 A after a stray write inside a window (C) |
| HR4 status | C nominal (regen); conditional on S1-B6 (FC, register loss); regen accuracy B (S1-B6) | C (continuous pin ceiling; register-defeatable through EN_EXTILIM REG0x14 bit 5, never-write plus readback, as the baseline REG14[1]); regen maximum B (T-7) | C regen; C, weaker than the baseline, in FC mode | C | C |
| HR5 | C by design (cond.) / B watchdog (0.5 s setting) | C; watchdog shortest setting 40 s, no maximum published | P POR / C hold-down / B watchdog (4-7 s) | C / B (DRVCC stage) / sys (no host watchdog) | P intrinsic / C bias (cond.) / B latency; SMBus timeout 4.95 s |

The input at the threshold is the lower of the input-ceiling limit and the charge-current limit ([D773] section 11.3), at a
7.4 V pack and the low tolerance corners. The charge row applies each published tolerance at its low corner and is reported
against the 3.10 A BQ25798 image setting, a design setting conditional on the pack ruling ([EVAL] section 8.1 item 6); HR1
passes or fails on the input condition alone.

Three observations follow from Table 5. First, no part has a P or C warm-response figure, so HR1 stays U or B for every
part. Second, the BQ25690 and the LTC4015 carry a documented HR1 hazard that the BQ25798 does not
carry, the RAA489110 item is configuration-dependent, and the BQ25773 item is a bench gate; the BQ25798 carries its own D-BT-SQ hazards P1 and P2 (section 6.3). Third, after a register loss
the BQ25773 FC bound (1.39 A) exceeds the 1.20 A arm drop and the 1.247 A H-20 P_MAX. The BQ25798 FC bound after an IINDPM
loss stays at 1.15 A only if ILIM_HIZ is re-sampled after qualification (P6, S1-B6). In the branch the datasheet describes
(an ADC read at POR and at each qualification, held as an IINDPM clamp; SLUSDV2C section 7.3.4 step 6 and section 7.3.4.3
p.27), the bound is 1.70-1.76 A.

---

## 4. Interlock hardware around each IC

The system core (H1 comparator, H2 FC permit with BT_ACT, C7 qualifier, OVN pack-OV term, eFuse on VCHG-IN, heartbeat
monostables, FCC/RGN level sensing, MCU watchdog) is the same for every part and is not counted ([CRIT] section 3.3). Table 6
gives the IC-specific adders under the rule of section 2.3.

**Table 6.** IC-specific interlock adders.

| Part | Minimal build (count, S6) | What the adders carry | Parity build | Contingent adders |
|---|---|---|---|---|
| BQ25798 | 11, S6 = 0 (9 of [D798] section 9.2 plus the 2.5 V reference and its feed for the regen ceiling) | /CE open-drain channel and REGN pull-up (static arm); ILIM_HIZ hold-down NMOS, release channel and gate pull-up (per-burst converter-off); FC leg (R_FC, NMOS, gate pull-up); `CHG_QUAL AND NOT P5` (1G04, 1G08); reference and feed (regen ceiling band) | About 18 (release PMOS and feed, far-end readback of /CE and ILIM_HIZ) | Keep-alive, 3 parts, DNP |
| BQ25690 | 9, S6 = 0 | /CE REGN pull-up and open-drain stage (per burst; stops charging, not conversion); static HIZ drive from VCHG-IN (micro-power LDO, inverter, Schottky diode, series resistor); regen leg (R_RG, NMOS, gate pull-down; FC default); no `CHG_QUAL` gates | 11 (redundant /CE pull-up, /CE far-end readback) | None planned; a keep-alive above 6.2 V if T-6.4b fails. A CCB current monitor (3 parts) is counted in S7, not in S6 |
| BQ25773 | 8, S6 = 1 | ILIM_HIZ hold-down Q_H with REGN gate pull-up R_H and release Q_R (inhibit and ceiling on one pin); FC leg (R_FC, Q_FC, gate bias); 2.5 V shunt reference and bias (ceiling accuracy and the VILIM_ENZ guard); no /CE pin; no `CHG_QUAL` gates if bench B13 passes | Not tabulated in [D773] | `CHG_QUAL` gates (+2, if B13 fails); keep-alive above 6.8 V (+3); THERM comparator; fast path (+2). Any one moves S6 to 0 |
| LTC4015 | Design B 13, S6 = 0 (design A 7) | UVCLFB clamp FET and INTVCC pull-up, release FET and pull-down (per-burst zero current); DRVCC load switch and pull-down (converter-off master, cold exit); D-BT-SQ bridge fuse (off the CCB, or one flying lead to C-D12); design B adds the UVCLFB divider switch and an RSNSI bypass P-FET with its level shifter | Not tabulated | VC clamp FET (A5) |
| RAA489110 | About 10, S6 = 0 | BATGONE open-drain channel with gate pull-down, VDD pull-up, 10 kOhm series resistor (inhibit acts on Q5 only); mandatory keep-alive (3); FC eFuse ILIM leg (3; a trip, not a regulated ceiling) | 11-14 (second series channel, eFuse EN keyed to P5) | None |

The interlock hardware does not separate the parts. The baseline and three challengers land at 9-13 adders (S6 = 0): the
BQ25798 11, the BQ25690 9, the RAA489110 about 10 and LTC4015 design B 13. The BQ25773 sits at 8, one part inside the 6-8
band, with four contingent items that would each move it out. The adder count therefore falls for three challengers (by 1-3
parts), but the total CCB part count does not: the smallest challenger stage (BQ25690, about 33 parts plus 9 adders)
exceeds the BQ25798 stage of 27-28 parts plus 11 adders (Table 7). The parts differ more in
what the adders protect against than in their number:

- The BQ25798 and the BQ25773 stop the converter with a REGN-biased hold-down on ILIM_HIZ.
- The BQ25690 needs a pull-UP above an unpublished HIZ entry level, from a rail derived from VCHG-IN, because HIZ turns REGN
  off and a grounded ILIM_HIZ defeats the ceiling instead of inhibiting.
- The RAA489110 inhibit acts on the battery FET only, so a Q5 short is a single fault that leaves the converter charging.
- The LTC4015 has no inhibit pin; its two stages use undocumented control inputs (UVCLFB clamp register-defeatable, DRVCC
  UVLO).

---

## 5. Layout, package, stock and cost

Table 7 compares the build and supply criteria. Stock and price figures are those of the dossiers, with their evidence
status.

**Table 7.** Layout, package, stock and cost.

| Part | Power stage | Layout (S10) | Package (S11) | Stock (S12) | IC price; stage cost per board (S13) |
|---|---|---|---|---|---|
| BQ25798 | Integrated 4-switch buck-boost, internal BATFET and sense; one 2.2 uH inductor at 750 kHz; 27-28 parts | Integrated buck-boost, two internal hot loops, 4 layers (1) | VQFN-HR 29, 4.0 x 4.0 mm, 0.4 mm pitch, no exposed pad (1) | 415 146 at the TI store, 2026-11-10 (P); second source UNKNOWN (2) | USD 5.04 at 1-99 (P); USD 10-12, passives UNVERIFIED (1) |
| BQ25690 | Integrated 4-switch buck-boost, external N BATFET, two external shunts, 10 uH at 450 kHz; about 30 parts plus a 3-part monitor | Integrated buck-boost, printed 2-layer reference layout (1) | WQFN-HR 26, 4.0 x 3.5 mm, 0.45 mm signal pitch, inner pad (1) | DigiKey regional snippets 176 and 460, 18-week lead time; UNVERIFIED (1) | About USD 5.2, UNVERIFIED; USD 15-19 including the monitor (1) |
| BQ25773 | External-FET quasi dual-phase NVDC buck-boost: 7 N-FETs, 2 inductors, 3 shunts; 57 parts; about 590 mm2 placement | Three hot loops, 4 layers, phase B populated (0) | WQFN-36, 4.0 x 5.0 mm, 0.4 mm pitch, one exposed pad (1) | 15 695 at the TI store (P), single source (2) | USD 3.14, quantity basis unstated; USD 13-20 (1) |
| LTC4015 | External-FET buck with INFET and OUTFET, 15 uH, 2 shunts; about 43 parts; off-CCB bridge fuse | One hot loop, plus two power-path FETs (1) | QFN-38, 5 x 7 mm, 0.50 mm pitch, one exposed pad (2) | Mouser.ca snippet 47 191, DigiKey.com.br 639; UNVERIFIED; lifecycle U (1) | USD 8-17, UNVERIFIED; USD 19-30 (1) |
| RAA489110 | External-FET 4-switch buck-boost, 5 N-FETs including the BFET; about 32 parts | Two hot loops (0) | TQFN-32, 4.0 x 4.0 mm, 0.40 mm pitch, one exposed pad (1) | Product-page summary "in stock", no quantity; UNVERIFIED (1) | USD 4.51-4.96, UNVERIFIED; USD 11-15 (1) |

The BQ25798 is the simplest stage of the five on part count and the only part with a primary stock figure above
100 000 units. The BQ25690 is the only challenger with a comparable stage size; it adds a BATFET, two shunts and a current
monitor. The two external-FET buck-boost controllers (BQ25773, RAA489110) carry the largest layout cost. Every S13 score is
capped at 1, because the passive and power-stage prices of every part are allowances.

---

## 6. Round-6 findings and earlier open items

### 6.1 IC-dependent round-6 findings

[CRIT] section 3.4 counts four IC-dependent findings of [R6] review round 6: finding 1 (VREG corruption, no fixed pack OVP,
major), finding 8 (5 ms loop budget against 1 ms deadlines, major), finding 10 (`chg_src` misattribution of sub-H1 regen,
major) and finding 12 (reversal hold unattainable at 100 kHz, minor). Table 8 gives the effect of each part.

**Table 8.** IC-dependent round-6 findings.

| R6 finding | BQ25798 | BQ25690 | BQ25773 | LTC4015 (design B) | RAA489110 |
|---|---|---|---|---|---|
| 1 VREG corruption (major) | Kept, more serious: a CELL write lifts the VREG bound to 18.8 V until POR | Kept, mitigated: VREG clamped by strap; one REG0x1B write may move it (U, T-14) | Kept: CHARGE_VOLTAGE register; SYSOVP_MAX can raise SYSOVP to 27 V | **Closed**: Li-ion CV DAC capped at 4.2 V/cell; cell count by strap | Kept: MaxSystemVoltage writable to 18.304 V |
| 8 Loop budget (major) | Kept, eased by 400 kHz on short traces | Kept; per-POR enable sequence of 6-7 transactions after every true POR (a purge in Run causes none under the [EVAL] section 4.4 handover; system assumption of the main document, section 5.6) | Kept; never-write list of seven fields at eight positions | **Closed** (no I2C write per mode change) | **Reopened**: about 14 word transactions, about 6.3 ms |
| 10 `chg_src` (major) | Kept (no ADC accuracy) | Kept (no IC ADC; CCB monitor) | Kept (IIN accuracy only at 5 A) | Closed conditionally (IIN ADC accuracy published, battery-only conditions) | Kept (8-bit, no accuracy, saturates at 1.515 A) |
| 12 Reversal hold (minor) | Kept, eased | Kept | Kept | **Closed** (hardware mode switching) | Kept |
| Net, S14 | 0, S14 = 2 | 0, S14 = 2 | 0, S14 = 2 | Closes 1, 8, 12; S14 = 3 | Reopens 8, S14 = 1 |

### 6.2 Other round-6 findings with a part-specific effect

Two IC-independent findings change with the part, although [CRIT] section 3.4 does not score them:

- Finding 2 (D-BT-SQ short, unfused pack on VCHG) **reopens in a new form for the LTC4015**. The mandatory D-BT-SQ bridge puts
  the pack permanently on the charger output; a bottom-FET short is then a pack short that only the bridge fuse clears, and the
  Teensy-controlled pack isolator is lost ([D4015] sections 2.4, 5.5).
- Finding 3 (battery-path copper sized below ICHG) reopens for every part as a CCB copper-sizing task. The basis current
  differs: 3.21 A for the BQ25798, 3.36 A for the BQ25773 at its recommended 3.2 A setting ([D773] section 11.1), and 3.30 A
  for the LTC4015 ICHG maximum. The BQ25690 and RAA489110 basis currents are not recorded in this document or the dossiers.
  TODO(verify: set from the chosen ICHG plus tolerance at design time; 3.21 A is the conservative floor). The RAA489110
  figure of 3.30 A in [DRAA] is a charge-side input-ceiling limit, not a copper basis.

Findings 13-16 (EVM-carrier geometry) close for every part.

### 6.3 Open items from the earlier rounds

The 2026-11-05 panel and critic rounds left BQ25798-specific open items ([EVAL] sections 0.3, 0.4). Table 9 records which of
them each challenger closes, keeps in an equivalent form or does not have. This ledger is not scored; it informs the
recommendation.

**Table 9.** Earlier-round open items.

| Item | BQ25798 | BQ25690 | BQ25773 | LTC4015 | RAA489110 |
|---|---|---|---|---|---|
| P1: BAT held near 2.5 V with /CE HIGH behind D-BT-SQ | Open (architectural; /CE static, ILIM_HIZ per burst) | Equivalent open: SRN decay re-enters trickle and pre-charge (T-6.4b) | Equivalent open: VCHG drains in HIZ, pre-charge and the nominal 5 ms tTRANS_CHG (shape unpublished, B) | Removed by the bridge (isolator lost) | Equivalent open: keep-alive mandatory |
| P2: BATOVP cycling behind D-BT-SQ | Open (S1-B4/B4r) | U | U | Removed by the bridge | U |
| P5: VAC_OVP POR 7 V | Open (S1-0b) | Closed (VIN_OVP 35.5 V min) | Closed (ACOV 32.25 V min) | Closed (OVLO 37.7 V min) | Closed (OVP 32.5 V min) |
| P6: ILIM_HIZ sampled only at qualification | Open (S1-B6) | Closed (continuous analog, KILIM published) | Closed (read continuously, +-200 mA published) | Closed (sense-resistor full scale) | Closed (sense-resistor full scale) |
| P7: charger watchdog contradictions | Open (S1-B5) | Equivalent open (EN_CHG / STOP_WD_CHG contradiction; shortest setting 40 s, no maximum published) | Open (B7; register and EC nominals differ) | No host watchdog | SMBus timeout 4.95 s turns BGATE off |
| C6: 7-minute poor-source lockout | Open (S1-PS) | Not found in [D690] | Latched OCP and SYSOVP states need an EN_HIZ toggle | 2-4 s battery detection on any input collapse | VSYS UV fault, 1.3 s retry |
| HR3 residual (sub-0.29 A FC loop, power-balance cross-check) | IBUS and VBUS ADC, no accuracy | CCB monitor (accuracy of the monitor) | IIN and VBUS ADC, accuracy at 5 A only | IIN and VIN ADC with published accuracy | 8-bit, no accuracy |
| ICHG 2.50 A cap at a 7.4 V pack (critic C2) | Open on the pack ruling ([EVAL] section 8.1 item 6; [WD] T-E-11); ICHG range covers 3.1 A, so the CCB adds no limit | Open on the pack ruling (3.3 A range) | Open on the pack ruling (16.32 A range) | Open on the pack ruling (3.105-3.297 A) | Open on the pack ruling (3.103 A minimum) |

Every challenger closes P5 and P6. No challenger closes P1 without a cost: the D-BT-SQ burst-entry problem reappears in an
equivalent form for each, except for the LTC4015, which removes it by bridging D-BT-SQ and thereby loses the hard battery
disconnect.

---

## 7. Weighted scores

### 7.1 Score table

Each criterion is scored 0-3 with the evidence cap of [CRIT] section 3.2; the weighted score is the sum of weight x score / 3.
Table 10 gives the scores and Table 11 the weighted terms.

**Table 10.** Criterion scores (evidence in brackets).

| Criterion (weight) | BQ25798 | BQ25690 | BQ25773 | LTC4015 B | LTC4015 A | RAA489110 |
|---|---|---|---|---|---|---|
| S1 warm response (15) | 1 (U/B) | 1 (B) | 1 (U) | 1 (B; section 2.2) | 1 | 1 (U/B) |
| S2 fail-safe POR (10) | 1 (P/C) | 2 (P) | 2 (P) | 1 (P) | 1 | 2 (P) |
| S3 ceiling quality (8) | 2 (B) | 3 (P) | 3 (P) | 3 (C) | 1 (P) | 1 (P/C) |
| S4 threshold quality (8) | 2 (B) | 2 (P) | 2 (P/B) | 2 (B; zero-current point 1.15 V typical only, 4015fb p.13) | 2 | 1 (P/U) |
| S5 inhibit latency (7) | 1 (U) | 2 (B) | 1 (U) | 1 (U) | 1 | 1 (U/B) |
| S6 interlock adders (10) | 0 (C) | 0 (C) | 1 (P/B) | 0 (C) | 0 | 0 (C) |
| S7 telemetry (5) | 2 (P) | 0 (P) | 2 (P) | 3 (P) | 3 | 2 (P) |
| S8 FC-mode fitness (6) | 1 (P) | 2 (P) | 1 (P) | 0 (P) | 0 | 3 (P) |
| S9 rating margin (4) | 0 (P) | 2 (P) | 2 (P) | 1 (P) | 1 | 0 (P) |
| S10 layout (7) | 1 (P) | 1 (P) | 0 (P) | 1 (P) | 1 | 0 (P) |
| S11 package (3) | 1 (P) | 1 (P) | 1 (P) | 2 (P) | 2 | 1 (P) |
| S12 stock (5) | 2 (P/U) | 1 (cap) | 2 (P) | 1 (cap) | 1 | 1 (cap) |
| S13 cost (2) | 1 (cap) | 1 (cap) | 1 (cap) | 1 (cap) | 1 | 1 (cap) |
| S14 round-6 (5) | 2 (C) | 2 (C) | 2 (P) | 3 (C) | 3 | 1 (C) |
| S15 input capacitance (3) | 3 (C) | 3 (C) | 2 (C) | 2 (C) | 2 | 2 (C) |
| S16 topology barrier (2) | 0 (P) | 0 (C) | 0 (P) | 3 (P) | 3 | 0 (P) |

**Table 11.** Weighted terms and totals (weight x score / 3).

| Part | S1 | S2 | S3 | S4 | S5 | S6 | S7 | S8 | S9 | S10 | S11 | S12 | S13 | S14 | S15 | S16 | **Total** | **Margin** |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BQ25798 | 5.00 | 3.33 | 5.33 | 5.33 | 2.33 | 0 | 3.33 | 2.00 | 0 | 2.33 | 1.00 | 3.33 | 0.67 | 3.33 | 3.00 | 0 | **40.3** | - |
| BQ25690 | 5.00 | 6.67 | 8.00 | 5.33 | 4.67 | 0 | 0 | 4.00 | 2.67 | 2.33 | 1.00 | 1.67 | 0.67 | 3.33 | 3.00 | 0 | **48.3** | **+8.0** |
| BQ25773 | 5.00 | 6.67 | 8.00 | 5.33 | 2.33 | 3.33 | 3.33 | 2.00 | 2.67 | 0 | 1.00 | 3.33 | 0.67 | 3.33 | 2.00 | 0 | **49.0** | **+8.7** |
| LTC4015 B | 5.00 | 3.33 | 8.00 | 5.33 | 2.33 | 0 | 5.00 | 0 | 1.33 | 2.33 | 2.00 | 1.67 | 0.67 | 5.00 | 2.00 | 2.00 | **46.0** | **+5.7** |
| LTC4015 A | 5.00 | 3.33 | 2.67 | 5.33 | 2.33 | 0 | 5.00 | 0 | 1.33 | 2.33 | 2.00 | 1.67 | 0.67 | 5.00 | 2.00 | 2.00 | **40.7** | +0.3 |
| RAA489110 | 5.00 | 6.67 | 2.67 | 2.67 | 2.33 | 0 | 3.33 | 6.00 | 0 | 0 | 1.00 | 1.67 | 0.67 | 1.67 | 2.00 | 0 | **35.7** | -4.7 |

LTC4015 design A has 7 adders, inside the 6-8 band, but scores S6 = 0 under the score-0 clause "an adder needed to defeat a
register-defeatable pin" ([CRIT] section 3.1): adder A3 exists because VIN_UVCL_SETTING = 0x00 defeats the UVCLFB clamp
(4015fb p.46; [D4015] section 9.4). With S6 = 1 design A would score 44.0 (+3.7); it fails condition 1 either way.

The three leading challengers lie within 3.0 points of each other, at 5.7-8.7 points above the baseline. Their advantages
over the BQ25798 come from the same three criteria: S2 (no charge out of POR or a strap-fault POR inhibit; BQ25690,
BQ25773), S3 (a continuously read ceiling with published accuracy) and S9 (a 40-45 V rating). Each challenger loses part of
that gain elsewhere: the BQ25690 on S7 (no ADC), the BQ25773 on S10 (the hardest layout) and S15, the LTC4015 on S8 (CV
+-1.25 %).

### 7.2 Decision rule

[CRIT] section 3.5 recommends a challenger only if all four conditions hold. Table 12 applies them.

**Table 12.** Decision rule against the baseline (40.3).

| Condition | BQ25690 | BQ25773 | LTC4015 B | RAA489110 |
|---|---|---|---|---|
| 1. Every must-have passes; no conditional pass on M5, M6 or M7 where the BQ25798 has P | Open (M5 B on the entry level, T-5.HIZ) | Met (symmetric M7) | Fails (M3 F) | Not decided (M5 c, same class as the BQ25798 S1-B3 item) |
| 2. Margin >= 10 points | Not met (+8.0) | Not met (+8.7) | Not met (+5.7) | Not met (-4.7) |
| 3. No major IC-dependent R6 finding reopened | Met (provisional; section 8.4) | Met (provisional; section 8.4) | Met | Fails (finding 8) |
| 4. S1 >= baseline S1 | Met (1 = 1) | Met (1 = 1) | Met (1 = 1) | Met (1 = 1) |
| Outcome | Alternate, pending T-5.HIZ | **Alternate** | Not eligible without rulings R-M3, R-BR, R-INH | Below the baseline |

No challenger meets condition 2. The BQ25773 is the only part that meets conditions 1, 3 and 4 on present evidence, so it is
the alternate under [CRIT] section 3.5; condition 3 is met provisionally, pending ruling R-S14 (section 8.4). The BQ25690 becomes a second alternate if T-5.HIZ passes.

---

## 8. Sensitivity

The scenarios below change one assumption at a time from section 7.1, unless stated. Table 13 summarises the totals and the
margins over the baseline.

**Table 13.** Sensitivity of the totals and the margins (margin over the BQ25798 in brackets).

| Scenario | BQ25798 | BQ25690 | BQ25773 | LTC4015 B | RAA489110 |
|---|---|---|---|---|---|
| Base (section 7.1) | 40.3 | 48.3 (+8.0) | 49.0 (+8.7) | 46.0 (+5.7) | 35.7 (-4.7) |
| A1: HR1 resolves badly for every TI part (S1 0 for the three TI parts) | 35.3 | 43.3 (+8.0) | 44.0 (+8.7) | 46.0 (+10.7) | 35.7 (+0.3) |
| A2: HR1 resolves badly for the BQ25798 only (S1 0) | 35.3 | 48.3 (+13.0) | 49.0 (+13.7) | 46.0 (+10.7) | 35.7 (+0.3) |
| A3: HR1 resolves well for every part (S1 2, the B cap) | 45.3 | 53.3 (+8.0) | 54.0 (+8.7) | 51.0 (+5.7) | 40.7 (-4.7) |
| A4: LTC4015 S1 read as 2 ([D4015] reading) | 40.3 | 48.3 (+8.0) | 49.0 (+8.7) | 51.0 (+10.7) | 35.7 (-4.7) |
| B1: S12 and S13 weights set to 0 (renormalised to 100) | 39.1 | 49.5 (+10.4) | 48.4 (+9.3) | 47.0 (+7.9) | 35.8 (-3.2) |
| B2: S12 and S13 weights doubled (renormalised) | 41.4 | 47.4 (+5.9) | 49.5 (+8.1) | 45.2 (+3.7) | 35.5 (-5.9) |
| B3: S12 and S13 weights tripled (renormalised) | 42.4 | 46.5 (+4.1) | 50.0 (+7.6) | 44.4 (+2.0) | 35.4 (-7.0) |
| C1: evidence caps lifted by stock and price fetches (best case) | 43.3 | 52.3 (+9.0) | 52.0 (+8.7) | 50.0 (+6.7) | 38.7 (-4.7) |
| D1: strict S14 (longer never-write list reopens finding 8) | 40.3 | 46.7 (+6.3) | 47.3 (+7.0) | 46.0 (+5.7) | 35.7 (-4.7) |
| D2: BQ25773 needs the `CHG_QUAL` gates or a keep-alive (S6 0) | 40.3 | 48.3 (+8.0) | 45.7 (+5.3) | 46.0 (+5.7) | 35.7 (-4.7) |
| D3: BQ25690 S6 on the [D690] 8-adder basis (S6 1) | 40.3 | 51.7 (+11.3) | 49.0 (+8.7) | 46.0 (+5.7) | 35.7 (-4.7) |
| E1: challengers pessimistic (D1 with BQ25690 S5 1 and BQ25773 S6 0) | 40.3 | 44.3 (+4.0) | 44.0 (+3.7) | 46.0 (+5.7) | 35.7 (-4.7) |
| E2: challengers optimistic (C1 with D3) | 43.3 | 55.7 (+12.3) | 52.0 (+8.7) | 50.0 (+6.7) | 38.7 (-4.7) |

### 8.1 HR1 warm response

HR1 is the requirement that decides the switch. A uniform change of S1 for every TI part (scenarios A1 and A3) leaves the
order of the TI parts and their margins unchanged, because all three TI parts move together. It moves only the non-TI parts:
in A1 the LTC4015 rises to +10.7 points, above the 10-point margin, but it still fails condition 1 (M3 F). If the TI
warm response fails outright, M9 fails for all three TI parts, and the LTC4015 becomes the only finalist with a modelled warm
path (0.07-0.2 ms with a 10 nF VC network, [D4015] section 8.2). That route needs operator rulings R-M3, R-BR and R-INH and
bench gates L-2 and L-3.

A change that affects the BQ25798 alone (scenario A2) moves every finalist except the RAA489110 (+0.3) above the 10-point
margin. In that case the
BQ25798 fails M9 outright, and the decision is no longer a scoring question. The switch decision therefore depends on bench
gate S1-B4 of the BQ25798 more than on any datasheet fact.

### 8.2 Stock and cost weights

The stock and cost weights move the order but not the outcome. With the weights set to 0 (B1), the BQ25690 rises to +10.4
and the LTC4015 to +7.9, because their UNVERIFIED stock caps no longer count. Only the BQ25690 passes 10 points, and its
condition 1 stays open on T-5.HIZ. With the weights
doubled or tripled (B2, B3), the BQ25773 leads, because it has the only primary stock figure among the challengers, and every
margin falls further below 10.

### 8.3 Evidence caps

A primary fetch of stock and price (scenario C1) moves the scores with the least effort. It raises the baseline by 3.0 points
(second-source stock, verified passive prices) and the challengers by 3.0-4.0 points. The largest single gain is the
BQ25690 S12 (1 to 3, +3.3 points), which rests on a blocked ti.com fetch. No margin reaches 10 points in C1.

### 8.4 Counting and S14 readings

The margin of the BQ25690 crosses 10 points only on the [D690] 8-adder basis (scenario D3, +11.3) or in the compound
optimistic case (E2, +12.3). In both cases condition 1 stays open on T-5.HIZ. Under the strict S14 reading (D1), the BQ25690
and the BQ25773 each drop 1.7 points, and condition 3 then fails for both, because finding 8 is major. Scenario D2 shows that
the BQ25773 S6 credit is fragile: any one of its four contingent adders removes 3.3 points.

### 8.5 Strict M2 reading

Under the strict M2 reading the BQ25798 fails a must-have and is not eligible, whatever its score. The 30-33 V class is also
excluded. The decision is then a forced choice among the four finalists:

- The BQ25773 (49.0) and the BQ25690 (48.3) are tied within the evidence band.
- The LTC4015 (46.0) fails M3 and needs four rulings.
- The RAA489110 (35.7) fails conditions 1 and 3.

Between the two TI challengers the order follows decision-rule condition 1 first, because it is the must-have test and does
not depend on the baseline score: the BQ25773 meets it and leads while bench gate T-5.HIZ is open. If T-5.HIZ passes, the
BQ25690 is preferred for three reasons. First, its FC bus draw
after a POR is 1.10 A, inside the 1.20 A arm drop, where the BQ25773 reaches 1.39 A after an IIN_HOST loss ([D773] section
11.4). Second, it is an integrated stage of about 30 parts against
57 parts and three hot loops. Third, its documented HR1 hazard (the VRECHG start condition) is decided by one
bench gate (T-3.VRECHG) with no hardware change, whereas the BQ25773 burst-entry hazard (the nominal 5 ms tTRANS_CHG, B)
needs a hardware remedy that is not yet proven. However, the BQ25690 has five disadvantages. It has no ADC. Its hard
inhibit pin does not stop conversion. Its charger watchdog is 80 times slower than the baseline setting. One register bit
(EN_EXTILIM) removes both its HIZ inhibit and its ceiling, whereas the BQ25773 HIZ entry has no register override ([D773]
section 3 M5). It delivers 2.62 A at an 8.4 V pack at the threshold floor, below the BQ25798 3.10 A image setting but 4.0 %
above the HR1 input condition (BQ25773: 2.77 A, also structural; Table 5). The same order applies when the BQ25798 fails
bench gate S1-B4 (section 8.1).

The three reasons are weighed above the five disadvantages. The first and third reasons concern an HR4 or HR1 hazard with a
hard-stop consequence (the arm drop, the burst-entry transition). The second reason concerns stage complexity (part count
and hot loops). The EN_EXTILIM item is a register-loss ceiling hazard (HR4). It is set against the BQ25773 register-loss
bound of 1.39 A after an IIN_HOST loss (the first reason), so the register-loss hazards of the two parts offset each other.
The delivered-current, ADC, hard-inhibit and watchdog items are margin notes: M4 is a capability test, and the 3.10 A
figure is a design setting (Table 5). The operator may change this weighing through ruling R-I3A1 (section 11.1). Under a
yes ruling, both TI challengers fail the delivered-current requirement structurally (Table 5), so neither can lead. If the
BQ25798 is then also ineligible, no TI successor remains, and only the LTC4015 route (rulings R-M3, R-BR and R-INH) or a
new search is left.

### 8.6 Re-admitted 30-33 V class

The protected-standoff reading of section 2.1 re-admits every part that [SCR] rejected on M2 F alone: the BQ25713, BQ25720,
BQ25723, BQ25731, BQ25790 and BQ25792 (TI), the RT9490/RT9490S, RT9492 and RT9478M (Richtek), the SGM41575 (SG Micro), the
MAX77960/MAX77961 (ADI), the ISL9241 (Renesas) and the SMBus buck chargers of the [SCR] quick-dismissal list (BQ25710,
BQ25700A, BQ25703A, BQ24725A, BQ24735, BQ24780S, BQ24800, LTC1760). None of them has a 2026-11-10 dossier, and apart from the
RT9492 (24 V operating, [SCR] row 10) none was checked against the 22.28 V operating condition of the reading. Their
IC-intrinsic record from 2026-11-05 ranks the scored examples below the BQ25798 ([EVAL] section 0.2; [RES] sections 3.2,
3.4, 3.5; [SCR] row 10):

- BQ25713: VINDPM ceiling 19.52 V, retention across Hi-Z exit undocumented (gate B3), AUTO_WAKEUP_EN = 1 at POR, external-FET
  buck-boost. A provisional score from these facts (S1 1, S2 1, S3 2, S4 1, S5 1, S6 0, S7 2, S8 1, S9 0, S10 0, S11 1, S12 2,
  S13 1, S14 2, S15 2, S16 0) is 34.3 (calc/score.py). This figure is not dossier-backed. The RT9478M and the BQ25720,
  BQ25723 and BQ25731 share the 19.52 V ceiling and fall in the same class.
- BQ25731: the watchdog expiry also loads 256 mA.
- BQ25798-class parts (RT9492, RT9490/RT9490S, SGM41575, BQ25792): a 30 V part scores S9 = 0 and cannot raise S6 or S10 above
  the BQ25798. A twin that differs from the baseline only by a non-charging POR (S2 3), primary stock (S12 3) and cost
  (S13 3) scores 50.0 against the condition-2 threshold of 50.3 (calc/score.py). No such part is documented with a
  non-charging POR: the RT9492 charges autonomously at POR ([SCR] row 10), the RT9490 shares the baseline VAC_OVP POR
  ([RES] section 4), and the SGM41575 and BQ25792 POR behaviour is unrecorded.

The re-admission therefore produces no challenger under the decision rule. Its practical value is a second source: the
RT9492 is a functional BQ25798 alternate, although not pin-compatible ([SCR] row 10, RT9492_DS-05 sections 12-13); the RT9490
and the SGM41575 are further candidates, not yet screened against the operating condition.

---

## 9. Switching threshold

This document keeps the 10-point threshold of [CRIT] section 3.5 condition 2. Three reasons support that value.

First, the threshold must cover the forward switching cost, that is, the work a challenger adds over the baseline. That work
is the CCB layout in progress (a parallel design of a custom BQ25798 board; extent not recorded in the repository), one
register image table and poll schedule of the kind in [EVAL] section 4.5, the IC-specific part of the test registry, and at
least one review cycle of the same depth. About 40 of the 112 registry entries name BQ25798 registers or I2C behaviour
([WD] section I); the eFuse, comparator, motherboard and watchdog entries carry over to any IC. The firmware driver,
never-write list and readback image are owed for every part, including the BQ25798: `teensy_controller.ino` contains no
BQ25798 code, and [EVAL] section 5.2 lists the driver as new work. The BQ25773 and BQ25690 dossiers already give their
never-write lists ([D773] section 5.1; [D690] section 14). The six review rounds and the registry entries already written
are spent whichever part is chosen, so they do not enter the threshold. The 10-point figure is a judgement, not a quantity
derived from this cost. The BQ25773 fails only condition 2, by 1.3 points, so this judgement decides its status as the
alternate.

Second, the threshold must exceed the evidence band. The base margins (5.7-8.7 points) lie inside the movement that the open
fetches and counts produce: the stock and price caps move single parts by 3.0-4.0 points (section 8.3), the S6 counting
reading by 3.3 points (sections 8.4, D2 and D3), and the S14 reading by 1.7 points. Closed adversely together (BQ25773 S6 0
and S14 1; baseline S12 3 and S13 3), they reduce the BQ25773 margin to +0.7 (49.0 - 3.3 - 1.7 = 44.0 against
40.3 + 1.7 + 1.3 = 43.3); no combination of these items reverses a sign. Across Table 13 the three leading challengers span
+2.0 (LTC4015 B, B3) to +13.7 (BQ25773, A2), and no sign reverses. The BQ25773 S6 item closes on bench gates B4 and B13 (section 11.2), so the band is not fetch-only.

Third, a margin of 10 points is two levels of S1, the heaviest criterion (5.0 points per level). No challenger can earn that
gap through S1 while the BQ25798 is eligible: the evidence cap holds every S1 at 1 or 2, so the largest S1 lead over an
eligible baseline is one level (5.0 points). The equivalence states the size of the margin only; the route to it is the
BQ25798 bench gate S1-B4 (section 8.1).

The three reasons bound what can change the outcome. Every criterion that separates the BQ25773 from the BQ25798 (S2, S3,
S6, S9, S10, S15) already rests on P or C evidence, and the open criteria (S1, S4, S5, S12, S13) are shared at equal scores.
The BQ25773 margin therefore stays at +8.7 under every symmetric closure of the open evidence; scenario A3 is one instance.
While the BQ25798 is eligible, the BQ25773, the only challenger that meets condition 1, reaches condition 2 only through an
asymmetric bench outcome. The other routes past 10 points (B1, D3, E2, A4) leave condition 1 open or failed. A challenger
that passes its warm-response gate before S1-B4 is run gains one S1 level and, provisionally, meets condition 2 (BQ25773:
54.0, +13.7). Once S1-B4 runs, a pass restores the +8.7 margin. A failure makes the baseline ineligible (scenario A2 if a
challenger passes its equivalent gate; scenario A1 if the gate fails for all three TI parts). The switch question is
therefore decided by bench gate S1-B4 and by the forward switching cost.

The threshold is not lowered for the strict M2 case of section 8.5, because that case is not a switch decision: the baseline
is then ineligible.

---

## 10. Ranked shortlist and recommendation

### 10.1 Ranked shortlist

Table 14 ranks the parts under the protected-standoff M2 reading. Rank follows the decision-rule outcome first. Where totals
lie within the evidence band of section 9 (BQ25773 and BQ25690: 0.7 points against a band of 3.0-4.0 points), the hazard
comparison of section 8.5 follows second; the weighted score is third.

**Table 14.** Ranked shortlist.

| Rank | Part | Score | Margin | Status |
|---|---|---|---|---|
| 1 | BQ25798 | 40.3 | - | Baseline; retained |
| 2 | BQ25773 | 49.0 | +8.7 | Alternate (provisional): conditions 1 and 4 met; condition 3 met provisionally, pending ruling R-S14 (the strict S14 reading fails it, section 8.4); margin below 10 |
| 3 | BQ25690 | 48.3 | +8.0 | Alternate if T-5.HIZ passes; condition 1 open; condition 3 provisional on R-S14 |
| 4 | LTC4015 (design B) | 46.0 | +5.7 | Not eligible: M3 F and M5 c; needs rulings R-M3, R-BR, R-INH (and R-FCA for design A) |
| 5 | RAA489110 | 35.7 | -4.7 | Below the baseline; conditions 1 and 3 fail |

The BQ25798 ranks first although three challengers score higher, because no challenger meets the decision rule. The score
order among ranks 2-4 is not significant: the three totals lie within 3.0 points, inside the evidence band of section 9.

### 10.2 Recommendation

**No finalist beats the BQ25798 by enough to justify a switch. The custom BQ25798 board should continue.** The reasons are as
follows:

1. No challenger reaches the 10-point margin under the base scores or under any single-assumption change except those that
   also leave condition 1 open (sections 7.2, 8).
2. The challengers' gains (POR behaviour, ceiling quality, rating) are real but are offset by documented or bench-gated
   hazards: burst entry from a drained VCHG through a nominal 5 ms tTRANS_CHG of unpublished shape (B, gate B4; BQ25773), an
   FC bound above the arm drop after a register loss (BQ25773; also present for the BQ25798 unless S1-B6 shows re-sampling),
   a regen start condition above 8.0-8.15 V (BQ25690), an inhibit pin that does not stop conversion and no ADC (BQ25690), a
   mandatory D-BT-SQ bridge and a CV tolerance outside M3 (LTC4015).
3. The total CCB part count does not shrink with any challenger (sections 4 and 5), so a switch does not simplify the CCB. The
   interlock adder count falls to 8-10 for three challengers, but only the BQ25773 reaches the S6 = 1 band.
4. HR1 stays U or B for every part. A switch does not resolve the decisive unknown; only a bench measurement does.

The recommendation holds under two conditions:

- **R-M2.** The operator accepts the protected-standoff reading of M2 (section 2.1). Its basis is the TPS26630 OVP cut-off
  22.61-23.63 V and turn-off delay 8.5-14 us (SLVSE94G p.6, p.8), which hold the BQ25798 pins at or below 23.7 V at the
  4.30 V/ms regen slope ([D798] section 3). Bench confirmation at the CCB, with VCHG-IN, U101 OUT and the VBUS pin scoped:
  (a) a REGEN close at 21.5 V, pass < 24.0 V at the VBUS pin; (b) a bench-supply ramp into VCHG-IN at >= 4.3 V/ms through
  22.6-23.6 V, pass: U101 OUT trips inside the band and holds < 24.0 V, VBUS_OVP_STAT stays 0. A hold level between 24.0 V
  and 25.2 V is outside the recommended range without a VBUS_OVP trip and needs an operator ruling. A conservative reading
  that adds the 20 mV OVP-pin overdrive of the delay specification (0.39 V at the input) gives 24.07 V ([D798] section 3).
  If the operator requires a 35 V rating at the IC pins, the BQ25798 is not eligible, and the order of
  section 8.5 applies: the BQ25773 leads while T-5.HIZ is open, and the BQ25690 leads if T-5.HIZ passes.
- **S1-B4.** If the BQ25798 warm-response bench gate fails while a challenger passes its equivalent gate, the BQ25798 fails M9
  and the decision is no longer a scoring question (scenario A2 assumes that the challenger passes). If the gate fails for all
  three TI parts (scenario A1), only the LTC4015 exceeds 10 points (+10.7), and it stays ineligible without rulings R-M3, R-BR
  and R-INH. In the A2 case the BQ25773 (bench gates B2, B4) and the BQ25690 (T-8a, T-3.VRECHG, T-5.HIZ) are the candidates, in that order of decision-rule standing while
  T-5.HIZ is open; the BQ25690 leads if T-5.HIZ passes (section 8.5).

The 2026-11-05 recommendation to measure two mechanisms in parallel ([EVAL] section 0.3, P11) remains valid on the custom
board: the BQ25773 is the alternate (condition 3 provisional on R-S14) with the most different inhibit mechanism among the
eligible parts. The P11 vehicle is unchanged: two BQ25798EVM and one BQ25773EVM (USD 511.90, [EVAL] section 7), each with a
real RT1987 in the D-BT-SQ position ([EVAL] section 0.3, P2). The warm-response, inhibit-exit and register-remedy gates
(S1-B4, S1-B4r, B2, B4 remedies 1 and 2, B13, T-5.HIZ) measure IC properties and transfer from an EVM to the CCB. The gates
that measure the CCB divider or bias (S1-B3, S1-B6, CCB-1, CCB-2, B4 remedy 3) run on the CCB prototype. S1-B4 runs first,
because its failure changes the question (condition 2). No vehicle for T-5.HIZ is confirmed (BQ25690EVM existence
UNVERIFIED, [D690] section 1.3). This document orders nothing.

---

## 11. Open items

### 11.1 Operator rulings

Table 15 lists the operator rulings that the recommendation depends on.

**Table 15.** Operator rulings.

| ID | Question |
|---|---|
| R-M2 | Accept the protected-standoff M2 reading (eFuse OVP as the 35 V element, IC rating scored in S9), or require 35 V at the IC pins (section 2.1). Decides whether the BQ25798 is eligible; under the strict reading the order of section 8.5 applies. Under the protected reading the eFuse OVP band (22.61-23.63 V) bounds the VESC cut-off below 22.61 V as fitted and below about 22.9 V for the BQ25798 in any case, so the [EVAL] section 3.2 cut-off lever (23-24 V) is not available; a V-MOT excursion above 22.61 V costs a charger cold start of about 190 ms ([D798] section 3) |
| R-S14 | Whether a longer never-write list counts as a reopening of R6 finding 8 when the transaction count is unchanged (section 2.4). Decides condition 3 for the BQ25690 and the BQ25773 |
| R-M3, R-BR, R-INH, R-FCA | LTC4015 rulings of [D4015] section 15.1; needed only if the TI warm response fails (section 8.1) |
| R-FCCEIL | FC ceiling position for every TI finalist: no setting of a divider-tolerance or pin-accuracy band meets both H5 at the low corner (ceiling minimum 0.85-0.86 A) and the 1.20 A arm drop at the high corner (ceiling maximum 1.05 A) ([D773] section 11.4; [D798] section 7.2); for the BQ25798 the choice is the REGN-divider FC leg (H5 F at 1.24 A worst case) or a reference-biased FC leg (band not computed, pin accuracy B until S1-B6). Needed for the adopted part |
| R-I3A1 | Whether 3.1 A delivered at an 8.4 V pack and the low tolerance corners is a hard requirement, or HR1 (>= 23 W input at the threshold) alone governs. Under a yes ruling the BQ25690 (2.62 A) and the BQ25773 (2.77 A) fail it structurally (Table 5), and neither can lead; with the BQ25798 also ineligible (strict M2 or S1-B4 failed), no TI successor remains, and only the LTC4015 route (R-M3, R-BR, R-INH) or a new search is left (section 8.5) |

### 11.2 Bench gates that can change the outcome

Table 16 lists the bench gates whose outcome can change the decision.

**Table 16.** Bench gates that can change the outcome.

| Gate | Part | Effect on the decision |
|---|---|---|
| S1-B4 / S1-B4r | BQ25798 | Decides M9 for the baseline; a failure while a challenger passes its equivalent gate makes the baseline ineligible (scenario A2); a failure for all three TI parts leaves only the ineligible LTC4015 above 10 points (scenario A1) |
| S1-B3 | BQ25798 | Hard-stop latency <= 115 us (reference-biased ceiling); EN_EXTILIM = 0 check. If EN_EXTILIM = 0 removes the < 0.75 V stop, the BQ25798 M5 becomes a conditional pass of the register-defeat class; the RAA489110 M5 clause of condition 1 is then met (its outcome is unchanged by condition 3 and the -4.7 margin) |
| S1-B6 | BQ25798 | Decides P6, whether ILIM_HIZ is sampled once or re-sampled after qualification, and therefore the BQ25798 FC bound after an IINDPM loss: 1.15 A if re-sampled, 1.70-1.76 A if sampled once (above the 1.20 A arm drop and the 1.4 A OC_FC latch; Table 5). It also sets the pin-to-current accuracy of the 1.15 A nominal figure |
| CCB-1 | BQ25798 | SYS separate from BAT; REGN-ordering closure. A SYS-BAT strap makes the BQ25798 NOT FEASIBLE ([D798] section 16) |
| T-5.HIZ | BQ25690 | Closes or fails condition 1 |
| T-3.VRECHG, T-8a | BQ25690 | Decide whether regen capture works above 8.0 V and the buck-mode /CE delay |
| B4, B13 | BQ25773 | Decide the drained-VCHG remedy against the nominal 5 ms tTRANS_CHG (charge-current waveform logged to extract t63 and t10-90) and the `CHG_QUAL` gates (S6 1 or 0) |
| L-2, L-3 | LTC4015 | Hard stop within 115 us; VC network stability at about 47 nF or less |

### 11.3 Fetches and counts

1. TPS26630 SLVSE94G, OVP response time (R-M2): closed, OVP_tOFF(dly) 8.5/11/14 us, SLVSE94G section 6.6 p.8; URL
   confirmed. The output overshoot during the turn-off delay is a bench item (section 10.2, R-M2 test (b)).
2. Second-source stock of the BQ25798 (Mouser, DigiKey: bot wall and HTTP 403 in [D798] section 15.3).
3. ti.com product and store pages for the BQ25690 (HTTP 403 in [D690] section 15.3); the largest single score gain in
   scenario C1.
4. Distributor stock and lifecycle for the LTC4015 (analog.com timeout, DigiKey HTTP 403, [D4015] section 15.4).
5. Renesas order data with quantities for the RAA489110 ([DRAA] section 15.3).
6. A word-by-word never-write and readback count for the BQ25798, the BQ25690 and the BQ25773, against the BQ25798 image of
   [EVAL] section 4.5 (REG0A, REG16, REG09 bit 6, OTG registers, EN_EXTILIM read each pass; verify burst REG00-0A). This count
   resolves R-S14.
7. The LTC4015 design B FC ceiling band with tolerances (section 3.2, Table 5): not computed in [D4015].
8. Dossiers for the re-admitted 30-33 V class, only if a second source of the baseline is wanted (section 8.6).
