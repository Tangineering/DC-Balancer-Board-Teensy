# Battle Test Round 4: Delta FMEA of IC1 Detailed Design Revision 6

## 0. Scope and method

This report is the round-4 delta failure-mode and effects analysis (FMEA) of `detailed_design_IC1.md` revision 6
(cited "DD"). It covers only the components, nets and rules that revision 6 added or changed (Table 0c, R6-1 to R6-12;
Appendix D) and the completeness-critic edits CC-1 to CC-18. Each element is taken through short, open, stuck, drift,
reversed and intermittent, in the bonded mode, the regen and FC windows, the self-test, commissioning, the
configuration check and the eFuse-blocking probe, State 99, Teensy reset, Hi-Z and hang, and the transitions between
them. Section 4 gives the credible double faults and the common causes of the severe rows.

The rounds-1 to 3 findings that Appendices B-D adjudicated are not repeated. Calculations are in
`calc/fmea_round4_calcs.py` (output `calc/fmea_round4_calcs_output.txt`, cited "calc R4 section N"). Every input that
no primary gives is marked ASSUMED, BENCH, UNCONFIRMED or TODO(verify). The BQ29200 figures are from the repository copy
of SLUSA52C (`references/Datasheets/BQ29200_TI.pdf`); the balance-network values are from `facts_board.md` section 2.3
(RB1B 100 Ohm to VDD, RB2 160 Ohm to VC2, RB3 260 Ohm to VC1, RB1A 100 Ohm to VC1_CB).

## 1. Summary of findings

Table 1 lists the findings in severity order. As in rounds 2 and 3, the defects sit in the parts that the previous
round added: the module-node dump Q_MD/R_MD, the comparator U_MS and the pin-side clamps D_VC1/D_VCB.

Table 1. Round-4 findings.

| ID | Severity | Finding |
|---|---|---|
| FM4-1 | major (blocker if RCB2 is below about 67 Ohm, UNCONFIRMED) | A D_VCB short or a reversed D_VCB (row F47, "not detected in service") grounds VC1_CB. Cell 1 drains at 37-42 mA with no detector, and once the cells differ by 17-45 mV the enabled balancer (pin 9 LOW, required for every window by CC-8) connects VDD to the grounded VC1_CB through its top-cell switch: 13-63 mA in a switch sized for 15 mA, with VDD at 1.85-7.09 V. At the low end of RCB2 the BQ29200, the only hardware pack-OVP actuator, loses supply while the pack-level CV of 8.4 V drives the healthy cell 2 over voltage. |
| FM4-2 | major | A short of the MS sense wire to SHDN_EF (adjacent LB-CB flying leads) makes U_MS follow EF_EN instead of the module node. The window works, the positive control passes, every exit "drains" at once, the eFuse-blocking probe passes with a bypass present, and `ERR_MOD_FED` can never assert. One undetected wire fault silently removes the only qualified in-service eFuse-bypass detector that C-2b qualified. |
| FM4-3 | major | Row F50 (Q_MD stuck ON, U_MDI stuck HIGH, MD_G shorted to a HIGH conductor) claims detection by U_IM "at the first window". With the module not charging, R_MD alone draws 1.067 A at 16 V and the eFuse input is 1.085-1.093 A, below the 1.508 A minimum U_IM trip and below OC_FC (1.24 A FC bus). Every configuration check then puts 17.1 W into R_MD for at least 0.5 s (8.5 J, then 17 J per extra second), commissioning on a BENCH_TEST 1 build has no OC_FC, and the positive control passes. No gate or fault detects it. |
| FM4-4 | major | The revision-6 Stage-3 key (Q_MD re-keyed to FF1./Q) contradicts the revision-6 exit rule. With FF1 still set at exit step 2, C_HU (1.5 mF) drains only through R_MB: 3.35-4.23 s to the U_MS level against the 10 ms T_drain,max, so every commanded exit latches `ERR_MOD_DRAIN`. R_MB also shortens the hold-up from 537 ms to 432 ms at the 1.38 mF design value (target 535 ms). |
| FM4-5 | major | D_VC1 reverse leakage is specified only at 25 C (10 uA at 4.2 V). The leakage flows through RB3 (260 Ohm) and offsets the BQ29200 bottom-cell sense: 26 mV per 100 uA, equal to the +/-25 mV OVP accuracy. The enabled balancer then drives a true imbalance of twice the offset. The V_F requirement (0.25 V at 45 mA) pushes the selection toward low-V_F parts, whose leakage is high when hot. No gate measures the hot offset. |
| FM4-6 | minor | Row F14 (F_VX or VBATN_X open) in a charge window: the module, not the pack, supplies the board load once VBT exceeds pack(+), with the return outside the module sense. The row's "V_PACKN about -0.7 V" and "I_PACK zero" detection hold only below the CV point; GENSTAT then reads Fully Charged and every window ends without a fault. |

The remainder of the delta enumeration (section 3) found no further defect that the revision-6 rows, gates and faults
do not already bound.

## 2. Findings

### 2.1 FM4-1 (major; blocker if RCB2 is low): a D_VCB short removes the BQ29200 supply through its own balancer

**Element.** D_VCB (M16, R6-1): anode on PCB GND, cathode on VC1_CB (BQ29200 pin 3, the bottom-cell balance input).
Row F47 lists "a short, or a reversed D_VCB: not detected in service (C-4 inspection)" with the residual "bounded at
58 mA; cell-1 drain until found".

**Mechanism.** The row omits the BQ29200 balancer. SLUSA52C section 8.3.5 eq. 2 gives the top-cell balancing current
as ICB2 = (VC2 - VC1) / ((RCB + RVD) + RCB2). The top-cell balance path therefore runs from VDD (fed from VBAL+ through
RB1B = RVD = 100 Ohm) through the internal switch RCB2 into VC1_CB. CB_EN is LOW (balancing enabled): firmware drives
pin 9 LOW at boot (facts_board section 5 item 4), and DD 12.4 item 7 (CC-8) refuses every window while pin 9 is HIGH.
The failing sequence is as follows:

1. D_VCB shorts (or is fitted reversed and passes C-1 by an inspection error). VC1_CB sits at GND. Cell 1 drains
   through RB1A at 37-42 mA, 0.89-1.01 Ah per day, with the vehicle parked or running (calc R4 section 4). RB1A runs at
   137-176 mW against 125 mW. The VC1 sense pin (through RB3) is unaffected, so the BQ29200 measures both cells
   correctly and OUT stays LOW. No firmware channel measures VMID (BAL_OK reads VBAL+ only).
2. When cell 2 exceeds cell 1 by VMM_DET_ON (17-45 mV, SLUSA52C section 7.5), the BQ29200 turns on the top-cell
   switch. With VC1_CB grounded, that switch connects VDD to GND through RCB2. RCB2 is not tabulated; inverting eq. 2
   on the RCB = 120 Ohm row of SLUSA52C section 7.6 (ICB 5/10/15 mA at 3.8 V) gives 33-540 Ohm (UNCONFIRMED inference).
   The switch then carries 13-63 mA at VBAL+ 8.4 V, up to 4.2 times the 15 mA internal-balancing figure (SLUSA52C
   section 8.1.2), and VDD falls to 2.10-7.09 V (1.85-6.24 V at 7.4 V) (calc R4 section 6).
3. At RCB2 below about 67 Ohm, VDD falls below the 4 V minimum of the SLUSA52C section 7.6 conditions. The BQ29200 is
   then outside its operating range. Whether it resets, and whether a reset restarts the CD delay of 1.58-4.75 s (DD
   Table 11), is not stated (UNCONFIRMED). If it does, the balancer re-engages after each restart and OUT never
   asserts.
4. With cell 1 drained, a charge window raises the pack to the Ag105 CV of 8.4 V (Table 5). The Ag105 sees only the
   pack voltage (DD 7.1; facts_ag105 section 2: pre-charge at 2.7 V/cell is judged on the pack), so cell 2 is driven to
   8.4 V minus V_cell1. The BQ29200 OUT term of N1 is the only per-cell protection (DD 12.4 item 7, CC-8). Firmware
   `OV_BATT` (8.5 V) and the Ag105 CV are pack-level only.

At the nominal RCB2 (about 160 Ohm) VDD stays at 4.55-5.17 V, OVP survives and the outcome is a 28-32 mA overstress of
the internal switch, an undetected cell-1 drain and repeated OVP-ended windows. At the low end it is an undetected
single fault that disables the only cell-overvoltage actuator while it creates the imbalance that needs it. No gate
catches an in-service short: C-1 checks orientation once, before the balance plug is first connected, and C-4 is a
visual inspection.

**Recommended fix.**

1. Delete D_VCB. Protect VC1_CB by a series resistance large enough that the BQ29200 internal structure carries the
   F34b current safely, or by a clamp in series with a fusible element that opens at the balance-switch overload. The
   VC1_CB abs-max row is not given in SLUSA52C section 7.1 (only VC2-GND and VC1-GND), so the deletion needs a
   TODO(verify: TI) on the VC1_CB input structure.
2. If D_VCB stays, add a cell-1 voltage measurement (a high-impedance divider from VMID to a spare analog input; all
   ten spare pins are used, so this needs a ladder bit or a multiplexed channel) and a fault on
   |V_cell2 - V_cell1| above 50 mV (TODO(calibrate)) that refuses windows and sets pin 9 HIGH.
3. Add a gate: with D_VCB shorted deliberately on the bench and the cells imbalanced by 60 mV, record VDD, the
   switch current and OUT behaviour during a simulated cell-2 overvoltage. NO-GO if OUT does not assert within the CD
   delay.

### 2.2 FM4-2 (major): one wire-to-wire short makes U_MS a copy of EF_EN

**Element.** The MS wire (R_MS1 at CB to MS_D on LB, DD Figure 2, Table 4 net MS/MS_D) and the SHDN_EF wire (R_SD on
LB to the U_EF SHDN pin on CB). Both are LB-CB flying leads of DD 5.7 item 4.

**Mechanism.** With MS_D shorted to SHDN_EF, the joined node is driven by U_AND through R_SD (1 kOhm) and loaded by
R_SDP (22 kOhm), R_MS2 (16.2 kOhm) and the node through R_MS1 (100 kOhm). Calc R4 section 2 gives:

- EF_EN H: the node sits at 2.95-3.15 V for any module-node voltage from 0 to 21.5 V. Pin 8 reads HIGH and SHDN stays
  above V_SHUTR (2 V maximum), so the eFuse works normally.
- EF_EN L: the node sits at 0-0.19 V. Pin 8 reads LOW (cold) whatever the module node is, and SHDN is below V_SHUTF.

Every U_MS consumer is then defeated, and none reports it:

1. The positive control of DD 9.5 (hold duties) and 9.7 step 7 tests U_MS only while EF_EN is H. It passes.
2. The exit wait of DD 9.5 exit step 2 reads LOW on the first iteration after the feed drop. Pin 33 goes LOW about
   two iterations after the drop, while the node can still be above the 11 V lockout (it reaches 11 V 1.02-2.23 ms
   after the drop, calc6 section 3). This is the row-F10 trip case, bounded at about 24 mJ.
3. The eFuse-blocking probe of DD 9.7a runs with EF_EN L. With a bypass the node is at 16 V, but pin 8 reads LOW:
   the probe passes. Its validity rule (CC-6, the positive control of the same check) passes as well.
4. `ERR_MOD_FED` (DD 12.4 item 4) needs pin 8 HIGH in the bonded mode, where EF_EN is always L: it can never assert.

C-2b qualifies the probe once, after commissioning. A short that arises later (chafe, vibration; DD 5.7 item 4 names
these leads as vibration-exposed) is invisible. The design's HR3 count for an eFuse bypass (DD 13, note 4 of section
11) then reverts to "latent with no in-service detector", the state that revision 6 set out to close.

**Recommended fix.**

1. Add a positive control of U_MS in the EF_EN-L state. In the iteration that drops the feed (pin 30 or FC_CHARGE LOW),
   which already defers the SD drain and the I2C poll (DD 12.4 item 5), sample pin 8 every 20 us for 300 us
   immediately after the write. A healthy U_MS stays HIGH for at least 0.84 ms (16 V to 9.15 V at C_mod 100 uF,
   calc R4 section 2); a U_MS that follows SHDN_EF falls within about 3 us (tau 0.90 us plus tSD 0.8-1.5 us). Require
   HIGH on every sample; otherwise latch `ERR_MOD_SENSE` and void the last probe.
2. Route MS and SHDN_EF in non-adjacent positions of the LB-CB cable with a GND conductor between them (the LB-CB
   cable is GND-referenced at both ends, so the no-ground rule of DD 4.2 does not apply to it).
3. Repeat C-2b at C-4.

### 2.3 FM4-3 (major): a Q_MD stuck ON is invisible to U_IM and OC_FC and overheats R_MD

**Element.** Q_MD (drain-source short), U_MDI (output stuck HIGH), or the MD_G flying lead shorted to 3V3, 5V, VBT or
any HIGH conductor. Row F50 states the detection "U_IM trip at the first window (`ERR_CHG_TRIP`); pin 8 positive
control (`ERR_MOD_SENSE`) if the node sags below the threshold".

**Mechanism.** The eFuse holds the node at the feed voltage, so the node never sags and the positive control passes.
The U_IM claim fails in every mode in which the module does not charge (calc R4 section 1):

| Mode | eFuse input | U_IM trip (1.508-1.977 A) | FC bus vs OC_FC 1.4 A | R_MD energy |
|---|---|---|---|---|
| Configuration check, pin 32 LOW (DD 9.7a) | 1.093 A | no | 1.243 A: no | 17.1 W; 8.5 J per 0.5 s (`AG105_SETTLE_MS` plus the reads) |
| Commissioning (DD 9.2, BENCH_TEST 1: OC_FC compiled out) | 1.093 A | no | bench supply 1.5 A limit only | 17.1 W for the whole session |
| FC window before the module starts (65-170 ms cold start; Bring-Up up to about 8-12 s) | 1.085 A | no | 1.235 A: no | 17.1 W for that interval |
| FC window, module charging at 1.25 A | 1.724-1.812 A | unit-dependent after the S0-12b trim | 1.87-1.96 A: OC_FC latches in BENCH_TEST 0 only | up to 512 J in a 30 s window on a BENCH_TEST 1 build |
| Regen pulse, cold module (DD 7.8) | 1.27-1.43 A | no | - | 0.46-1.45 J per pulse; 0.85-2.70 W mean over a 30 s window |

R_MD is a 2512 thick-film part on CB beside the Ag105 (DD Table 7, rating TODO(select), sized for 51 mJ dumps). The
configuration check runs before the first regen window of every power cycle, so the overload repeats every power
cycle, and nothing in Table 16 latches on it. If R_MD fails open, the result is row F49 (`ERR_MOD_DRAIN`, availability);
if it fails hot first, the hot spot is under the module whose case limit is 100 C (DD 5.7 item 6).

A second mode of the same element: MD_G is a stiff push-pull HIGH (U_MDI, SN74LVC1G04) during the whole bonded time,
with no series resistor (DD Figure 2). A chafe of MD_G to GND shorts that output continuously (LVC output-current
rating TODO(verify: TI SN74LVC1G04)).

**Recommended fix.**

1. Detect the stuck dump with an existing channel. In the configuration check (pin 32 LOW, BT_BUS dropped, so the bus
   is FC-only), compare FC_CURRENT (pin 40) one iteration before and 20 ms after EF_EN rises. A healthy module with
   only the R_KA path draws at most about 0.03 A of eFuse input; a stuck dump adds 1.07 A. Latch `ERR_MOD_DUMP_ON`
   (window inhibit) on a step above 0.4 A (TODO(calibrate)). Run the same check at commissioning step 7 and abort the
   session on a failure.
2. Fit a 1 kOhm series resistor at the U_MDI output (LB end of MD_G).
3. Add a C-2 sub-step: Q_MD drain-source jumpered; the check of item 1 latches.
4. Correct rows F50 and F49 accordingly.

### 2.4 FM4-4 (major): Stage 3 cannot meet the revision-6 exit rule

**Element.** DD 5.3 (Stage 3: "Q_MD gate re-keyed from MD_G to FF1./Q, R_MD changed to 10 Ohm"), DD 14.4, R_MB, and
the revision-6 exit rule of DD 9.5 exit step 2 and 12.4 item 3 ("waits until pin 8 reads LOW ... and only then sets pin
33 LOW", cap 10 ms, `ERR_MOD_DRAIN`).

**Mechanism.** In Stage 3, Q_MD conducts only after FF1 clears, and FF1 clears only after pin 33 goes LOW, which the
exit rule holds until pin 8 reads LOW. At exit step 2 the node is held by C_HU and decays through R_MB alone: 3.35 s
from 18 V and 4.23 s from 21.5 V to 9.15 V (calc R4 section 3). Every commanded exit therefore latches `ERR_MOD_DRAIN`
at 10 ms, and windows are refused for the power cycle. If the firmware instead skips the wait in Stage 3, the bond
happens with C_HU charged, which is the row-F37 behaviour that the revision-6 summary (DD 1, "the module stops
converting with the sense still in the return path") says no longer occurs.

R_MB (6.5 mA at 21.5 V) also loads C_HU between pulses. The DD 14.4 sizing used the 18 mA module idle current only:
1.38 mF then holds 18 V to 11 V for 537 ms. With R_MB the hold-up is 432 ms (469 ms at 1.5 mF), below the 535 ms pulse
spacing (calc R4 section 3).

**Recommended fix.** Key the Stage-3 dump to NOT(FF1.Q AND (P30Q OR FCQ)), so that the dump starts at the feed drop
of a commanded exit and also at any FF1 clear. Re-derive T_drain,max for C_HU (1.5 mF at 10 Ohm: tau 15 ms, about
13 ms from 21.5 V to 9.15 V) and the traction delay of OR-2'. Remove R_MB in Stage 3 or include it in the C_HU sizing.
State both in DD 14.4.

### 2.5 FM4-5 (major): D_VC1 leakage biases the only hardware OVP and drives the balancer

**Element.** D_VC1 (M16), cathode on VC1 (BQ29200 pin 2, the bottom-cell sense input). DD Table 7: "I_R at most 10 uA
at 4.2 V, 25 C (VC1 error at most 2.6 mV through RB3)". V_F at most 0.25 V at 45 mA is required for row F34b.

**Mechanism.** D_VC1 is reverse-biased by V_cell1 in every normal mode, so its leakage flows from VMID through RB3
(260 Ohm). VC1 reads low by I_R x 260 Ohm. The BQ29200 then reads the bottom cell low and the top cell high by the same
amount (calc R4 section 4):

| D_VC1 leakage | VC1 offset | Against the +/-25 mV OVP accuracy (SLUSA52C, TA 0-60 C) | Imbalance the balancer drives |
|---|---|---|---|
| 10 uA (DD limit, 25 C) | 2.6 mV | 0.1 x | about 5 mV |
| 100 uA | 26 mV | 1.0 x | about 52 mV |
| 300 uA | 78 mV | 3.1 x | about 156 mV |
| 1 mA | 260 mV | 10.4 x | about 520 mV |

The balancer is enabled (pin 9 LOW, CC-8), runs whenever the pack is connected, turns on at 17-45 mV apparent mismatch
and turns off near 0 +/-9 mV (SLUSA52C section 7.5). It therefore moves the true cell voltages until the apparent
difference is zero, that is to a true imbalance of twice the offset, and it holds that imbalance indefinitely. The
bottom-cell OVP then trips late and the top-cell OVP early, both by the offset.

The leakage at temperature is not specified. With an ASSUMED doubling per 10 K (a generic Schottky behaviour, not a
primary), a part at the 25 C limit leaks 160 uA at 65 C (42 mV) and 640 uA at 85 C (166 mV). The BQ29200 sits about
5 mm from the Ag105 body (DD 5.5: Ag105 body from y 34.5 mm, BQ29200 at y 29.46 mm), which dissipates while charging.
The V_F requirement favours large-die low-V_F parts; a search snippet for one such part (Nexperia PMEG4005CEJ) lists
about 1.5 uA at 25 C and about 1 mA typical at 125 C (UNCONFIRMED: the snippet table was garbled and the vendor PDF
could not be fetched, HTTP 403). D_VCB leakage flows through RB1A and only drains cell 1.

**Recommended fix.** Specify I_R at 4.2 V at the maximum board temperature at the BQ29200 (TODO(calibrate): measure it
in a charge window), for example at most 20 uA at 70 C (5.2 mV). If no part meets both that and the V_F limit, move the
clamp requirement: hold V_F at most 0.3 V at the 16 mA that RB3 alone admits (D_VC1 carries at most 16 mA, calc6
section 1), which admits a smaller, lower-leakage die. Add a gate at C-2: VMID - VC1 at most 5 mV with the board at its
charge-window temperature.

### 2.6 FM4-6 (minor): F_VX open in a charge window is reported as a full pack

**Element.** F_VX (R6-2), whose open state is row F14 ("Charge mode: no charge path; the board load returns through the
S_GND body diodes (V_PACKN about -0.7 V)"; detection "I_PACK zero with the charger powered; `ERR_ISO_MISMATCH` (FC)").

**Mechanism.** With VBATN_X open and S_CHG on, the module output reaches VBT through D-BT-SQ, and its CV loop holds
VBT near 8.4 V relative to Vin- (GND). Pack(-) then sits 0.1-0.9 V above GND at V_pack 8.2-7.4 V, so the S_GND body
diodes are reverse-biased (calc R4 section 5). The module, not the pack, supplies the board load, with the return to
Vin- outside the sense, which is the ML0227 current path at board-load magnitude. U_IM bounds it (1.51-1.98 A of
input). reg 0x06 and I_PACK1 both read about 0, so `ERR_ISO_MISMATCH` does not fire; the module sees no sense current,
reports Fully Charged, and DD 9.7 ends the window "without a latch". The pack never charges and nothing reports why.
The model is UNCONFIRMED (whether the module regulates VBat+ against an open VBat- this way).

**Recommended fix.** Restate row F14. Add a fault: GENSTAT Fully Charged while V_batt is below the restart level
(8.0 V) latches `ERR_CHG_PATH_OPEN` (window inhibit).

## 3. Delta enumeration

Table 2 lists every revision-6 element and its failure modes. "Covered" names the existing row, fault or gate that
bounds the mode; "FM4-n" names a finding of this round.

Table 2. Delta FMEA of the revision-6 changes.

| Element (change) | Mode | Mode / transition | Effect | Disposition |
|---|---|---|---|---|
| D_VC1 (R6-1) | Short | Any | VC1 = 0, top cell reads 8 V, OUT HIGH, N1 LOW | Covered: F47, self-test step 4 |
| D_VC1 | Reversed | Any | VC1 near +V_F, top-cell OVP | Covered: F47, C-1 |
| D_VC1 | Open | F34b | VC1 to -V_F of the BQ29200 internal diode through RB3 (16 mA) | Covered: B-PKN (BENCH) |
| D_VC1 | Drift (hot leakage) | Any, continuous | OVP offset and balancer-driven imbalance | **FM4-5** |
| D_VCB (R6-1) | Short or reversed | Any, balancing enabled | Undetected cell-1 drain; VDD shorted through the top-cell switch | **FM4-1** |
| D_VCB | Open | F34b | VC1_CB unclamped; RB1A path carries up to 42 mA into the BQ29200 | Covered: B-PKN |
| F_VX (R6-2) | Open | Bonded | No effect (VBATN_X carries no bonded current) | Covered |
| F_VX | Open | Charge window | Module supplies the board load; Fully Charged reported | **FM4-6** |
| F_VX | Fails to clear (I2t) | F48 | Module sense overstress | Covered: F48 TODO(verify) |
| F_VX | Nuisance open | U_C1/U_C2 trip transients (3.5-3.64 A for under 1 ms) | As open | Covered: DD 5.3 rating text |
| VBATN_M (30 mm, downstream of F_VX) | Short to VCHG-IN_M | Any | Module input shorted to VBat-; eFuse start into a hard short; positive control fails | Covered: `ERR_MOD_SENSE` |
| Q_MD (R6-3) | Open, gate open, R_MD open | Any exit | `ERR_MOD_DRAIN` | Covered: F49 |
| Q_MD | D-S short; U_MDI stuck HIGH; MD_G to HIGH | Config check, commissioning, FC, regen | R_MD overload, undetected | **FM4-3** |
| MD_G | Short to GND | Bonded (MD_G HIGH) | Continuous LVC output short; dump lost (F49) | **FM4-3** item 2 |
| MD_G | Short to SHDN_EF | Bonded: eFuse ON; windows: eFuse OFF | Inverted eFuse enable | Covered: positive control (`ERR_MOD_SENSE`), probe (`ERR_EFUSE_BYPASS`); route as FM4-2 item 2 |
| Q_MD / eFuse overlap | Transition | EF_EN fall | At most 1.5 us of 1.43 A into R_MD | Covered (negligible) |
| Q_MD | Dumping a live source | eFuse bypass and VCHG-IN fed (probe, or F17 with a bypass) | 17.1 W until the probe cap or `ERR_VCHG_FED` | Covered: 1.71 J probe bound; double fault in section 4 |
| Q_MD (Stage 3 re-key) | By design | Commanded exit | `ERR_MOD_DRAIN` on every exit | **FM4-4** |
| R_MB (R6-3) | Short | Window start | Hard short at the eFuse output; thermal regulation 0.13-0.28 A (below U_IM); positive control fails within 10/50 ms | Covered: `ERR_MOD_SENSE` |
| R_MB | Open | Q_MD also failed | Node decays on module idle current only | Covered: F49 |
| R_MB | By design | Stage 3 | Hold-up 432 ms against 535 ms | **FM4-4** |
| U_MS (R6-3) | Output stuck LOW, MS open, R_MS1 open | Window | Positive control fails | Covered: `ERR_MOD_SENSE`; probe voided (CC-6) |
| U_MS | Output stuck released, pin-8 tap open | Bonded | Reads fed | Covered: `ERR_MOD_SENSE` / `ERR_MOD_FED` |
| U_MS | R_MS2 open | Exit | Drain wait lengthened | Covered: `ERR_MOD_DRAIN` |
| U_MS | R_MS1 fitted on the board-side pin-10 stub (VCHG-IN) | Exit, probe | Exit waits on the VCHG-IN bleed (1 s): `ERR_MOD_DRAIN`; probe reads fed: false `ERR_EFUSE_BYPASS` | Covered (loud); add to C-2 |
| MS wire | Short to SHDN_EF | All | U_MS follows EF_EN; probe and `ERR_MOD_FED` blind | **FM4-2** |
| MS wire | Short to EF_FLT_N, PROFILE, MD_G | All | Reads fed or cold permanently | Covered: `ERR_MOD_SENSE`, `ERR_MOD_DRAIN`, false `ERR_EFUSE_BYPASS` (loud) |
| Pin 8 (ENC_B net) | Encoder still on the net | All | Pin 8 toggles with the wheel | Covered: gate P8 |
| R_ILIM 8.06 k (R6-5) | Drift low | Window | I_OL below the U_IM trip on one unit | Covered: S0-12b per-unit trim |
| U_IM window | 3V3 variation after the trim | Window | +/-3 % of the trip point, about +/-0.05 A, consumes each 0.05 A margin | Covered as a gate tolerance (S0-12b); note: R_IMa sits on LB (Table 7), while the S0-12b text says "on the fitted CB" |
| `ERR_VOK_STUCK` ratio rule (R6-6) | ADC ratio bias | Run, V-MOT near release | False latch needs a 0.3 % bias for 50 ms near the release level | Covered: V2-1 (ratio error at most 0.002 over 50 ms, plateau cases); pin 39 is a 0.1 % thin-film divider (BOM R1-SNT, R2-SNT) |
| Chokepoint setters, pin 5 open-drain (R6-7) | Released pin not read as MPPT enabled | Window | MPPT disabled: input not threshold-gated | Covered: S0-7 fallback (DD 12.5 item 3) |
| Self-test step 1 (R6-8) | - | Boot, Idle entry | - | No defect |
| `ERR_IPACK_PLAUS` 0.4 A / 0.25 A (R6-10) | False latch | Bonded traction | Margin x2.16 (calc6 section 8) | Covered |
| Iteration-counted confirmations (R6-11) | - | Entry, exit | - | No defect |
| Pin 32 LOW on `ERR_CHG_LADDER` and State 99 (R6-12) | - | - | - | No defect |
| Positive-control timing (CC-1) | t_D_ON beyond 19 ms | Regen | `ERR_VCHG_SENSE` rule (b) false latch | Covered: CC-B8, V2-0 |
| Exit pin-5/pin-10 waits (CC-2) | - | Exit | Writes at about 23 ms; traction not delayed | No defect |
| CBAL_DISABLE gate (CC-8) | Forces balancing on in every window | Window | Enables the FM4-1 and FM4-5 mechanisms | **FM4-1**, **FM4-5** |

## 4. Double faults and common causes

### 4.1 Double faults of the severe rows

1. **FM4-2 (MS-SHDN_EF short) plus an eFuse bypass (F11, F35, F36-M2).** The bypass is latent; with a D-BC-RG short
   in a regen window it closes the bus-fed loop (DD 11 note 1). `ERR_VCHG_FED` still detects a D-BC-RG or D-BC-FC
   short before a window, so the loop needs a third fault that arises inside a window. The double fault removes the
   layer that revision 6 added and returns the eFuse-bypass count to the revision-5 state.
2. **FM4-3 (Q_MD stuck ON) plus an eFuse bypass.** In the bonded mode with VCHG-IN fed (probe, or F17 before
   `ERR_VCHG_FED` latches), R_MD carries 1.07 A at all times; State 99 does not remove the D-BC-FC feed, so with F17
   the dissipation lasts until the State-99 teardown has taken VBUS down. Bounded by the bus decay.
3. **FM4-1 (D_VCB short) plus a BQ29200 OUT fly-wire short to GND (F25).** Either one defeats the hardware OVP
   actuation; together they remove it without a detector at every RCB2 value.
4. **FM4-5 (hot D_VC1 leakage) plus a high cell 2.** The early top-cell trip is availability only; the late bottom-cell
   trip lets cell 1 reach V_PROTECT plus the offset before OUT asserts. With 160 uA at 65 C (ASSUMED), that is 42 mV
   above the 4.35 V threshold.
5. **Q_MD dump plus a pack-negative open (F34b).** No interaction: the dump acts on the module node only.

### 4.2 Common causes

| Common cause | Elements | Consequence | Disposition |
|---|---|---|---|
| LB-CB flying-lead bundle (SHDN_EF, EF_FLT_N, IMON, PROFILE, MD_G, MS) | Adjacent conductors in one route | MS-SHDN_EF short blinds U_MS (FM4-2); MD_G-SHDN_EF short inverts the eFuse enable (loud) | FM4-2 item 2 (routing, GND guard) |
| Bundle open as a whole | All six leads | eFuse off (R_SDP), dump off (R_MDG), U_MS reads cold, U_IM blind | Fail-safe; positive control at the next window |
| LB 3V3 (U_MDI, U_MS, U_IM, U_AND, R_UMS) | F51 | eFuse off, dump off (R_MB bleeds), ladders read code 0 | Covered: F51, `ERR_CHG_LADDER` |
| BQ29200 balancer enabled (pin 9 LOW, forced by CC-8) | D_VC1 leakage, D_VCB short | Converts a passive clamp fault into active imbalance and VDD loss | FM4-1, FM4-5 |
| BQ29200 thermal environment (5 mm from the Ag105) | D_VC1, D_VCB leakage | Leakage rises in every charge window | FM4-5 |
| Teensy reset, Hi-Z or hang | Q_MD, U_MS | Q_MD ON while the LB 3V3 is up (CC-12); pin 8 not read | Covered |

## 5. Gates and rows to change

1. Row F47: add the balancer mechanism (FM4-1); add a cell-1 measurement or delete D_VCB.
2. Row F50: correct the detection (FM4-3); add `ERR_MOD_DUMP_ON` and its C-2 sub-step.
3. Rows F11, F35, F36: add the EF_EN-L positive control of U_MS (FM4-2) as a precondition of the probe verdict.
4. DD 14.4 and the Stage-3 lines of DD 5.3 and Table 11: re-key the dump and re-derive T_drain,max and the hold-up
   (FM4-4).
5. DD Table 7, D_VC1: add a hot I_R limit; C-2: VMID - VC1 offset at temperature (FM4-5).
6. Row F14: restate; add `ERR_CHG_PATH_OPEN` (FM4-6).
