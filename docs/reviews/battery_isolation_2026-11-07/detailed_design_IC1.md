# Detailed Design IC1: Commanded Low-Side Return Changeover, Revision 12

Date: 2026-11-08 (revision 11: 2026-11-08; revision 10: 2026-11-08; revision 9: 2026-11-08; revision 8: 2026-11-07). Board revision 20260622 (manufactured), firmware
baseline fw v37 rev 2.
Status: **detailed design, revision 12** (revision 11 corrected after battle-test round 8, Appendix J; revision 10 corrected after battle-test round 7, Appendix I; revision 9 corrected after battle-test round 6, Appendix H; revision 9
extended revision 8 for the operator rulings of 2026-11-08 on FC windows between H-20 purges, Appendix G; revision 7 corrected after battle-test round 5, Appendix F; revision 6 corrected
after battle-test round 4, Appendix E; revision 5 corrected after battle-test round 3, Appendix D; revision 4 corrected
after battle-test round 2, Appendix C; revision 3 corrected after battle-test round 1, Appendix B). Nothing in this document has been ordered, built, cut, soldered or
flashed. The operator rulings of 2026-11-09 are recorded in section 17 without a revision change: 30 of the 36 rulings
are decided (two of them by a named bench gate), and 6 remain open (section 17).
Predecessor: `concept_IC1-commanded-return-changeover.md` (revision 2, kept unchanged as the design history).
Calculations: `calc/ic1_rev3_calcs.py` (output `calc/ic1_rev3_calcs_output.txt`, cited "calc section N"),
`calc/ic1_rev4_calcs.py` (output `calc/ic1_rev4_calcs_output.txt`, cited "calc4 section N"),
`calc/ic1_rev5_calcs.py` (output `calc/ic1_rev5_calcs_output.txt`, cited "calc5 section N"),
`calc/ic1_rev6_calcs.py` (output `calc/ic1_rev6_calcs_output.txt`, cited "calc6 section N"),
`calc/ic1_rev7_calcs.py` (output `calc/ic1_rev7_calcs_output.txt`, cited "calc7 section N") and
`calc/ic1_rev8_calcs.py` (output `calc/ic1_rev8_calcs_output.txt`, cited "calc8 section N") and
`calc/ic1_rev9_calcs.py` (output `calc/ic1_rev9_calcs_output.txt`, cited "calc9 section N") and
`calc/ic1_rev10_calcs.py` (output `calc/ic1_rev10_calcs_output.txt`, cited "calc10 section N") and
`calc/ic1_rev11_calcs.py` (output `calc/ic1_rev11_calcs_output.txt`, cited "calc11 section N") and
`calc/ic1_rev12_calcs.py` (output `calc/ic1_rev12_calcs_output.txt`, cited "calc12 section N"). Where they disagree,
the later script governs. Battle-test round 6 scripts (`calc/bt6_*.py`, `calc/fmea_round6_calcs.py`, cited "r6
section N" for the latter) and battle-test round 7 scripts (`calc/bt7_*.py`, `calc/fmea_round7_calcs.py`;
`calc/bt7_transient_sim.py` is cited "bt7 section N") and battle-test round 8 scripts (`calc/bt8_*.py`) are cited by name. Revision 9 also rests on three fact sheets of 2026-11-08 and their scripts:
`facts_purge_sequencing.md` (`calc/purge_sequencing_timeline.py`, cited "seq section N"), `facts_purge_collapse.md`
(`calc/purge_collapse_sim.py`, cited "pc section N") and `facts_purge_demand.md` (`calc/purge_demand_budget.py`, cited
"out sN"). Battle-test round 2-5 scripts (`calc/bt2_*.py`, `calc/bt3_*.py`, `calc/bt4_*.py`, `calc/bt5_*.py`,
`calc/fmea_round5_calcs.py`,
`calc/fmea_round2_calcs.py`, `calc/fmea_round3_calcs.py`, `calc/fmea_round4_calcs.py`, `calc/bt_r2_ag105_lens.py`,
`calc/verify_*.py`) are cited by name. The completeness critic (section "Completeness critic", items CC-n) uses `calc/cc_completeness_calcs.py` (output
`calc/cc_completeness_calcs_output.txt`).

## 0. Document control

### 0.1 Purpose and scope

This document is the build-ready detailed design of concept IC1. IC1 keeps the Silvertel Ag105 charger. It moves pack
negative off PCB GND onto an off-board node (PACK-), which a three-MOSFET changeover transfers between PCB GND (the
**bonded mode**) and the Ag105 VBat- pins (the **charge mode**). In the charge mode the pack return passes only through
the Ag105 internal current sense (Ag105 DS V1.1 Fig. 1 p.3, Table 2 p.4), which restores the module's own charge-current
regulation.

The document gives the following items:

- the complete netlist of three new assemblies and every motherboard modification, with ASCII schematics;
- a table of every component with part number, value, rating and primary citation;
- the logic and gate-drive equations, the timing budget and the step-by-step sequence of every mode and transition;
- the fail-safe default table and the single-fault table;
- the firmware specification, the staged build, the staged bench test plan with go/no-go criteria, the parts list with
  cost, and the list of operator rulings.

The pack chemistry, the pack protection board and the VESC configuration are outside the scope of this document. The
requirements are those of `docs/charger_replacement_evaluation_2026-11-05.md` sections 0.1 (operator rulings 1-10) and
1.1 (HR1-HR5), as extracted in `facts_prior.md` sections 2-3.

IC1 isolates the pack **return** during charging. Pack positive stays on VBT in every mode, so the pack keeps supplying
the board load (the Teensy LM1084 and the BT boost) through the Ag105 sense in the charge mode. Ruling OR-S records this
interpretation of "battery isolated during charging".

### 0.2 Evidence conventions

Every number cites a primary: a datasheet with literature number and section or page, the schematic
(`references/Scale_Car_Board_20260624.sch`, cited "SCH"), the board file (`references/Scale Car Board PCB 20260625.brd`,
cited "BRD"), the IO CSV, the BOM, the firmware (`teensy_controller/teensy_controller.ino`, cited "ino:line"), a fact
sheet of this study, or a calculation script. The tags have the following meanings:

- **BENCH**: no primary gives the value; a bench gate in section 15 measures it.
- **TODO(verify: source)**: a primary exists but was not read for this revision.
- **UNCONFIRMED**: an inference that no primary states directly.
- **ASSUMED**: a working value used in a calculation, with no primary; the result carries the same tag.

Three new-part datasheets were read for revision 3 from the TI site (not saved in the repository): TPS2663x SLVSE94G
(September 2018, revised June 2024), TLV3011/TLV3011B SBOS300C (February 2004, revised April 2023) and INA240 SBOS662C
(July 2016, revised December 2021). Battle-test round 1 additionally read SN74LVC1G74 SCES794G section 6.3 and BQ29200
SLUSA52C (repository copy `BQ29200_TI.pdf`). The other new-part figures are carried from the revision-2 dossier or the
IC2-IC5 dossiers with their citations, and are marked where they were not re-read.

### 0.3 Changes from revision 2

Table 0 lists the revision-3 changes. Section 3 gives the graft decisions in full.

Table 0. Revision-3 changes.

| No. | Change | Source |
|---|---|---|
| R3-1 | The regen charger input is gated in hardware by a two-out-of-two V-MOT-over-VBUS detector (VMOT_OK, here **VOK**). VOK clamps the D-BC-RG enable and also gates the eFuse enable. MOT_PWR stays HIGH through regen windows (Death-5 doctrine restored). The revision-2 per-event MOT_PWR cycle, brake pre-arm hold and Q_X3 clamp are removed. | Graft G1, adopted modified |
| R3-2 | The arm latch FF2 and the TPS3431 watchdog are replaced by a **pumped arm**: a capacitor-coupled charge pump toggled from `loop()` only. Loss of toggling clears the permit latch FF1 in 43-76 ms. | Graft G4, adopted modified |
| R3-3 | Two independent INA240A3 channels: channel 1 feeds U_C1 and Teensy pin 16; channel 2 feeds U_C2 and Teensy pin 17. WDOG1_B (pin 20) clears FF1. | Graft G3, adopted |
| R3-4 | The Ag105 runs in resistor mode for charge current and MPPT threshold. Two Teensy-switched resistor networks select the regen profile (1.75 A, 18 V) or the FC profile (1.25 A, 13.8 V) while the module is unpowered. Runtime EPROM writes fall to zero. | Graft G6, adopted modified |
| R3-5 | Ag105 LD (pin 20) is tied to Vin-. | Graft G5, adopted modified |
| R3-6 | A hardware BT-loop detector (D5) clears FF1 when the BT boost delivers current inside an FC window. | Graft G2, adopted modified |
| R3-7 | Pre-window and boot injection self-tests of U_C1 and U_C2, the latch and the changeover. | Graft G7, adopted in part |
| R3-8 | J-BL position 3 is blocked mechanically; a second soldered return lead parallels the J-BT pin-2 screw contact. | Grafts G8 and G9 |
| R3-9 | Digital readbacks are collapsed into two 5-bit R-2R ladders on two analog pins. | Graft G10, adopted modified |
| R3-10 | The hardware is partitioned into three assemblies with no ground conductor between the pack switch board and the logic board. | Section 4.2 |
| R3-11 | A third enable cut (D-BC-RG) and its clamp. | Section 5.5 |
| R3-12 | Comparator tolerances from the TLV3011B data sheet. | Calc section 6 |
| R3-13 | A staged build: Stage 0 (bench rig), Stage 1 (standstill charge isolation), Stage 2 (Run-time regen), Stage 3 (optional hold-up). | Section 14 |

### 0.4 Changes from revision 3

Table 0a lists the revision-4 changes. Appendix B gives the finding-by-finding adjudication.

Table 0a. Revision-4 changes.

| No. | Change | Findings |
|---|---|---|
| R4-1 | Fusible series resistors R_K1 and R_K2 (2.2 Ohm) in the Kelvin leads at the R_SH terminals. New design rule: no pack-referenced conductor leaves SB without a series current-limiting element at its SB end. | FM-1 |
| R4-2 | The pack fuse F_PK moves to the pack-positive lead. The S_GND gate supply is split per channel (VBT_T1, VBT_T2), each with its own fuse and a series pair of capacitors, tapped upstream of F_PK. | BT1-DS-04, FM-6, BT1-07 |
| R4-3 | VOK: each channel has its own V-MOT and VBUS tap points and wires; a bus-present comparator per channel clamps the D-BC-RG enable and gates VOK when its bus tap is open or its lower leg is shorted; the VOK comparators and pull-ups move from 5V to 3V3; `ERR_VOK_STUCK` runs in every non-braking iteration. | FM-2, BT1-02, FM-11, BT1-T4 |
| R4-4 | Status ladders: R = 2.00 kOhm, 2R = 4.02 kOhm, 10 nF (tau 20 us, revision 3: 2.0 ms). A settled-reading rule; hardware-driven bits are not compared with the commanded state. UC1_N and UC2_N leave the ladders; BAL_OK and D5_N take their bits. | FM-3, BT1-T1, BT1-03, BT1-BM-01, FM-14 |
| R4-5 | Self-test injection moves to the signal side of U_C1 and U_C2, with ADC readback of SIG1 and SIG2 (pins 16 and 17 now tap SIG1 and SIG2; the U_SH2 inputs are reversed so that both injections are pull-downs). D5 gains an injection and a ladder bit. | FM-4 |
| R4-6 | Pin 33 is buffered (U_P33, pull-down at the buffer input), and CLK and /CLR have Schmitt buffers; R_CK rises to 10 kOhm. A Teensy reset now clears FF1 at once. | FM-7, FM-13, BT1-04, BT1-T3, BT1-DS-01, BT1-DS-02 |
| R4-7 | The V_PACKN transfer function includes R_VPS; two-point calibration; the return-resistance test runs only at 5 A or more. | BT1-BM-02 |
| R4-8 | Guard G1 takes a residual form inside FC windows. | BT1-BM-04 |
| R4-9 | M3 and M11 move outside the Ag105 body; the M1/M2 cut gaps get an insulation rule and a post-cut gate; the lead-B joint gets a procedure and an acceptance value; Table 6 gets a reversal column. | BT1-BM-05, BT1-BM-06, BT1-BM-08, BT1-BM-10 |
| R4-10 | Commissioning runs with pin 32 LOW (no charge path); gate D-3 qualifies the vehicle Ag105; the Stage-0 rig reproduces the vehicle charge-mode topology. | BT1-AG-1, BT1-AG-2, BT1-AG-4, BT1-AG-5 |
| R4-11 | Firmware: REGEN and FC_CHARGE are refused in the bonded mode (State-98 keys included; State-99 drains skipped); the [RER] power arm triggers regen windows; FC-window entry waits for the BT current to decay; new fault `ERR_PROFILE_OC`; status reads of 0xFF are excluded; diagnostic scopes are stated per window type. | FM-8, BT1-06, FM-10, BT1-RO-06, BT1-T5, BT1-AG-3, BT1-AG-7, BT1-RO-05 |
| R4-12 | eFuse UVLO raised above the Ag105 11 V lockout (R_UV2 10.5 kOhm). | BT1-DS-08 |
| R4-13 | Bench plan: earth-reference warning and gate C-1b; per-pulse S0-6 criterion; gates V2-0, S0-8b, W0, B11c, B-FPK, P-M1, D-3; Kelvin-short and ladder-step tests in C-2. | BT1-BM-07, BT1-T2, BT1-RO-03, BT1-DS-03, BT1-BM-03 |
| R4-14 | Stage 3 needs a C_HU dump FET keyed to FF1./Q. | BT1-05, BT1-AG-6, BT1-RO-04 |
| R4-15 | Rulings added: OR-M, OR-O, OR-P, OR-R, OR-S, OR-T, OR-V; OR-C, OR-G and OR-2' extended. | BT1-RO-07, BT1-RO-02, BT1-RO-09 |

### 0.5 Changes from revision 4

Table 0b lists the revision-5 changes. Appendix C gives the finding-by-finding adjudication.

Table 0b. Revision-5 changes.

| No. | Change | Findings |
|---|---|---|
| R5-1 | F_PK moves to the pack-terminal side of the pack connector, upstream of every SB conductor and both gate taps. New row F43 (SB-internal pack+ short). F34 restated; gate B-FPK repeated at the new position. | FM2-1 |
| R5-2 | New fault `ERR_IPACK_PLAUS` (bonded mode: BT_CURRENT above 1.0 A while I_PACK1 shows less than 0.5 A of discharge). A pass in the current power cycle is a regen-window precondition. Self-test step 5 fails instead of skipping when BT_CURRENT predicts a discharge. New row F44 (KS pair shorted); F21 detection corrected. | FM2-3, BT2-BM-01 |
| R5-3 | BAT54 D_D5S in series with the Q_D5 drain blocks the Q_D5 body diode; self-test steps 1 and 6 now measure U_D5 itself. | FM2-4 |
| R5-4 | Schottky D_VM from GND to VMID at J-BL clamps the BQ29200 VC1 input when pack negative opens upstream of R_SH. New row F34b; gate B-PKN; the mating-order warning restated. | FM2-6 |
| R5-5 | New fault `ERR_VCHG_FED` (V_chg above 11 V with pins 30 and 31 LOW, outside a 1.0 s blanking); it is also a window-entry precondition. `ERR_EFUSE_BYPASS` becomes a scheduled feed probe inside the configuration check, judged on reg 0x07, not on an ACK. Single-fault note 1 corrected: a D-BC-FC or D-BC-RG short is a one-fault loop path that only `ERR_VCHG_FED` closes. | FM2-7, BT2-LS-01, BT2-TR-03, BT2-AG-2, BT2-LS-05 |
| R5-6 | The self-test is a non-blocking sub-state of `chgModeTick()`; `detectFaults()` runs every iteration; a State-2 request or a fault aborts it, and the State 1 to 2 transition waits for the bonded settled reading. | FM2-9, BT2-LS-07 |
| R5-7 | `ERR_VOK_STUCK` latches on channel disagreement (exactly one channel permits for 50 ms, any state), with a secondary both-permit check 400 ms after the 200 ms no-brake rule. | BT2-TR-01 |
| R5-8 | Regen-window trigger changes from the [RER] 40 ms power arm to a command-step arm (I_cmd at or below -2 A on two 1 kHz ticks), ruling OR-V'. The S0-6 GO inequality gains the window-open latency term; V2-4 gains a captured-charge criterion. | BT2-TR-02, BT2-RO-01 |
| R5-9 | Guard G1 is built from I_PACK1 (1 kHz), a calibrated I_L and efficiency, with a threshold I_G1 from a written error budget, blanked until the first valid charging read plus two polls. Note 2 no longer claims that G1 resolves sub-D5 flows. | BT2-TR-04 |
| R5-10 | State 99: only the three drain statements are removed under `PACK_RETURN_CHANGEOVER`; the motor zero, both bus opens, the flag resets and MOT_PWR LOW stay before the boosts go LOW. | BT2-LS-02 |
| R5-11 | FC windows and configuration checks only in State 1 or State 98; the `chargingControl()` cruise FC branch compiles out; a traction request or a State 1 to 2 transition exits the window; the mode manager is the sole writer of pin 30; no direct FC-to-regen transition. | BT2-LS-03, BT2-RO-03 |
| R5-12 | eFuse start-into-overload: new comparator U_IM on IMON (1.71 A input) clears FF1 through N1; 7.5, Table 11 and HR4 restated (thermal regulation up to 2.9 s with FLT not asserted; fast trip 3 x I_OL, active); gate S0-12b. TPS26636PWPR named as the approved alternate. | DS2-1, DS2-3 |
| R5-13 | `ERR_ISO_MISMATCH` compares signed quantities in GENSTAT Charging only, has a Fully Charged form, is blanked after a GENSTAT change and is not evaluated with pin 32 LOW. Settings readbacks (reg 0x00-0x04) are valid on any status byte other than 0xFF; the 0xFF data exclusion applies to measurements only. | BT2-AG-1 |
| R5-14 | R_OVP (Q_OV gate) pulls up to 3V3: an open BQ29200 OUT fly-wire now holds N1 LOW (detected availability fault, not latent loss of OVP). | BT2-BM-02 |
| R5-15 | Regen source term SRC = (VOK AND p30) OR FCQ (U_RS). Every commanded exit drops the feed, waits T_drain (2 ms) and only then sets pin 33 LOW, so the module input drains with the sense in path. | BT2-TR-05, BT2-LS-04, BT2-AG-5 |
| R5-16 | P33B and PUMP_OK join N1 through open-drain buffers (U_N33, U_NP); pin 20 is configured open-drain; self-test step 4b (pin 33 LOW alone clears FF1); F32b corrected; rows F32c, F32d. | FM2-2 |
| R5-17 | `chargerHasPower()` requires V_chg at or above 13.5 V on two settled iterations; EF_FLT_N is compared only while EF_EN is HIGH and outside the entry mask. | DS2-2 |
| R5-18 | Stage 1 leaves out M5 and the VOK clamp logic (deferred to Stage 2); Stage 0 plus Stage 1 is the recommended first build and end state. | BT2-RO-06 |
| R5-19 | Rows, gates and rulings for the minor findings: F22b, B8, C-1c, B11d, S0-2 matrix, S0-2b, S0-7 record, V2-6, section 5.7 (mechanical), channel-2 VBUS tap moved off C-D2, LB placement, D-3 wording, Table 18 module count, lead times, OR-G extended, OR-W added, section 12.12 size restated. | FM2-5, FM2-8, FM2-10, FM2-11, BT2-LS-06, DS2-4, BT2-AG-3, BT2-AG-4, BT2-BM-03, BT2-BM-04, BT2-RO-02, BT2-RO-04, BT2-RO-05 |

### 0.6 Changes from revision 5

Table 0c lists the revision-6 changes. Appendix D gives the finding-by-finding adjudication.

Table 0c. Revision-6 changes.

| No. | Change | Findings |
|---|---|---|
| R6-1 | D_VM at the J-BL barrels is deleted. Two Schottky clamps sit at the BQ29200 pins, behind RB3 and RB1A: D_VC1 (anode GND, cathode VC1) and D_VCB (anode GND, cathode VC1_CB). A clamp short, a reversed clamp and a pack-negative open are limited to at most 58 mA by RB3 parallel RB1A (calc6 section 1). New row F47; F34b restated; gate C-1 gains a diode-mode orientation check before the balance plug is first connected; gate B-PKN gains a pack-negative open under board load with the boosts running. | FM3-1, BT3-BM-01, BT3-BM-02 |
| R6-2 | Fast fuse F_VX (4 A) in VBATN_X at the Ag105 stub end, on CB. Rule C1 restated for both modes; VBATN_X routed in its own sleeve; C-1 and C-4 insulation checks; new row F48; the OV_BATT and BQ29200 charge-mode boundaries and P-M1 include R_FVX. | FM3-2, BT3-BM-03 |
| R6-3 | The module input node VCHG-IN_M gains a dump (Q_MD with R_MD 15 Ohm, gate = NOT EF_EN through U_MDI), a bleed R_MB 3.3 kOhm and a comparator U_MS (threshold 8.69-9.15 V) read on Teensy pin 8 (`CHG_MOD_COLD_N`, LOW = module node cold). Every commanded exit waits for pin 8 LOW (measured drain, cap 10 ms, `ERR_MOD_DRAIN`); every window entry, profile change and MPPTD change needs a cold module; every eFuse start is therefore cold. New faults `ERR_MOD_FED`, `ERR_MOD_DRAIN`, `ERR_MOD_SENSE`; new rows F49, F50. Gate P8 checks the pin-8 net before use. | BT3-TR-02, BT3-TR-03, DS3-2, BT3-AG-1 |
| R6-4 | The eFuse-blocking probe is judged on U_MS (module node at or above 8.69-9.15 V with EF_EN L), not on reg 0x07. Every window is a positive control of U_MS. A hard gate injects an eFuse bypass and requires the latch (C-2, V2-6, S0-14). Until that gate passes, F11, F35 and F36(M2) have no qualified in-service detector. | DS3-2, BT3-AG-1, BT3-TR-03 |
| R6-5 | R_ILIM 9.09 kOhm becomes 8.06 kOhm (I_OL 2.06-2.41 A). The U_IM window includes the SLVSE94G IMON gain range: 1.51-1.98 A at 3V3 3.2-3.4 V, below the new I_OL minimum by at least 0.078 A (calc6 section 5). S0-12b becomes a per-unit trim gate. Section 7.5 separates the thermally limited hard short from the soft overload. | DS3-1 |
| R6-6 | `ERR_VOK_STUCK` is gated by the measured V-MOT/VBUS ratio, not by a dwell: a channel that permits while the ratio, referred to its Idle self-calibration, is below 1.003 for 50 ms latches. The 6.6 V/s validity bound and its `static_assert` are deleted. Pin-39 calibration (M-R2) becomes a Stage-2 precondition. | BT3-TR-01 |
| R6-7 | `chargingControl()` loses every write of pins 5 and 30 under `PACK_RETURN_CHANGEOVER` (regen branch, charge_goal branch and MPPT tail); pins 5, 30 and 31 are written only through chokepoint setters owned by `chgModeTick()`. Pin 5 is driven open-drain. | BT3-LS-01, BT3-AG-4 |
| R6-8 | Self-test step 1 expects PUMP_OK L at boot and H at an Idle entry. | BT3-LS-02 |
| R6-9 | M13 heat confined to the J-BT area with the Ag105 case at or below 90 C; D-3 runs after the last heated modification. | BT3-BM-04 |
| R6-10 | `ERR_IPACK_PLAUS` re-keyed to 0.4 A BT current and 0.25 A pack discharge; the configuration check and the probe are exempt from the 8.0 V gate; the regen 8.0 V gate becomes conditional on S0-8b; HR1 availability stated from the bags. | BT3-RO-01 |
| R6-11 | Confirmations and ladder persistence are counted in loop iterations with a 30 ms wall-clock cap; the SD drain and Ag105 I2C are deferred on a pin-33 edge iteration. | FM3-3 |
| R6-12 | Minor findings: pin-38 plausibility (`ERR_VCHG_SENSE`), pin 32 LOW on `ERR_CHG_LADDER` and in State 99, Ag105 ambient derating and a non-latching GENSTAT Thermal Shutdown, reg 0x01 re-read in every regen window, the Stage-0 rig sense chain and positive control, rule C2 extended to the rig and D-3(b), the regen arm restated for the fw v37 drive law, telemetry renamed protocol v6 on top of the R4 v5 layout, and the ruling inventory regenerated (OR-E per-fault table, OR-X added). | FM3-4, BT3-LS-03, DS3-3, BT3-AG-2, BT3-AG-3, BT3-AG-4, BT3-RO-02, BT3-RO-03, BT3-RO-04 |

### 0.7 Changes from revision 6

Table 0d lists the revision-7 changes. Appendix E gives the finding-by-finding adjudication. Revision 7 prefers a
firmware rule, a gate, a part-value change or a deleted feature to new circuitry. The only hardware additions are
passive: R_MDS and the VC1 tap divider (R_VC1a, R_VC1b, C_VC1). Appendix E lists what a later review must check on
each.

Table 0d. Revision-7 changes.

| No. | Change | Findings |
|---|---|---|
| R7-1 | D_VCB is deleted and RB1A rises from 100 Ohm to 4.7 kOhm, the top of the SLUSA52C section 7.3 RCB range. No fitted part can then ground VC1_CB (a pin-3 solder bridge would draw 0.89 mA through RB1A instead of 42 mA, and C-1 checks for it), so the FM4-1 path of the balance top-cell switch from VDD into a grounded VC1_CB no longer follows a part failure, and the pack-negative-open return falls from 58 mA to 16.2 mA through RB3 alone, with at most 0.83 mA into the unclamped VC1_CB pin (calc7 section 1). Cell balancing falls to 0.5-1 mA (SLUSA52C Table 7.6; ruling OR-AA). D_VC1 is specified at V_F at most 0.25 V at 16.2 mA over -20 to 85 C and I_R at most 40 uA at 4.2 V at the M16 temperature (VC1 error at most 10.4 mV). | FM4-1, FM4-5, BT4-DS-01 |
| R7-2 | A VC1 tap (R_VC1a 200 kOhm at the VC1 pad, R_VC1b 200 kOhm and C_VC1 100 nF on LB) feeds Teensy pin 20 (A6), and `ERR_CELL_MISMATCH` compares the two cell voltages independently of the BQ29200. A shorted or reversed D_VC1, which puts the pack voltage across the BQ29200 VC2-VC1 (8 V absolute maximum), latches it on the first evaluation. WDOG1_B and D_N20 are deleted to free pin 20; the pump and the RTWDOG reset remain as the two hang layers. | BT4-DS-02, FM4-1, FM4-5 |
| R7-3 | `ERR_MOD_DUMP_ON`: at every EF_EN rise of an FC window, configuration check or commissioning session, FC_CURRENT 10 ms after `chargerHasPower()` first turns true (the feed has reached the eFuse and its output ramp is over), compared with the iteration before the rise, latches on a step above 0.4 A (stuck dump 1.08-1.19 A, healthy node 23 mA). R_MDS 1 kOhm in series with the U_MDI output. Rows F49 and F50 corrected (U_IM does not detect a stuck dump). | FM4-3, BT4-1 |
| R7-4 | Stage 3 (hold-up) is withdrawn: its dump keyed to FF1./Q deadlocked every commanded exit into `ERR_MOD_DRAIN` and `ERR_MOD_FED`. Section 14.4 records the conditions of a re-specification. | FM4-4, BT4-TR-01 |
| R7-5 | Idle-entry self-test: step 1 checks the CH bits in Stage 1 only; step 10 waits for both CH bits LOW for 100 ms (deadline 1 s, else "deferred"); the k_idle mean starts after the same settle; `ERR_VMOT_CAL` is re-evaluated at every valid k_idle. | BT4-LS-01 |
| R7-6 | The `ERR_MOD_SENSE` (b) anchor is an observed V_chg crossing (a reading below 13.0 V, then two readings at or above 13.5 V, all with EF_EN H). T_drain,max and the regen positive-control deadline are the later of 10 ms and 4 iterations, capped at 30 ms. | BT4-LS-02, BT4-LS-03 |
| R7-7 | Exit hold check: pin 8 sampled 50 us and 150 us after a commanded feed drop (`ERR_MOD_SENSE` (c)); `ERR_VCHG_SENSE` rule (a) evaluated in every mode; the MS lead routed apart from SHDN_EF; gate C-2b repeated at C-4. | FM4-2 |
| R7-8 | An open R_SH element puts KS+ about 8.4 V below PCB GND, beyond the INA240 -6 V absolute maximum (row F34c). `ERR_IPACK_PLAUS` gains a two-sided gain band; a repair rule replaces U_SH1 and U_SH2 after any R_SH open; B-PKN measures KS+ at the LB connector; ruling OR-AB. | BT4-TR-02 |
| R7-9 | Gate C-2 splits into C-2a (charger unpowered, one GO per sub-item, Table 19) and C-2b (fed, after commissioning). The U_MS threshold sub-step runs with MD_G lifted and a 50 mA supply limit; a warning forbids feeding VCHG-IN_M with EF_EN L. | BT4-2, BT4-3, CC-B9 |
| R7-10 | Minor findings: row F14 and `ERR_CHG_PATH_OPEN`; the `ERR_CHG_LADDER` pin-32 order; the R_MD and Q_MD duty; the probe soft-start current and the S0-14/C-2b verdicts; the eFuse-start sag in section 7.2 item 5; an FC-window UVLO dip as a commanded exit; the TPS26636 overload cases; Table 7 candidates; the U_MS unpowered state (HIGH); the CMRR term of the U_MS window; the F_VX interrupting rating; the M16 coordinates and heating method; gate P8 rewritten; the section 15.2 order; the open-R_MS2 overstress stated (row F56); CC-B15 closed. | FM4-6, BT4-LS-04, BT4-TR-03 to BT4-TR-06, BT4-DS-03 to BT4-DS-07, BT4-4, BT4-5, BT4-6 |
| R7-11 | Completeness items closed by design: CC-B5, CC-B9, CC-B10, CC-B12, CC-B13, CC-B14, CC-B15; CC-B1 and CC-B2 listed as rulings OR-Z and OR-Y. | CC-B |

### 0.8 Changes from revision 7

Table 0e lists the revision-8 changes. Appendix F gives the finding-by-finding adjudication. As in revision 7, a
firmware rule, a gate, a part-value change or a deleted feature is preferred to new circuitry. The only hardware
additions are four passive series resistors at the LB end of flying signal leads (R_VC1c, R_MS3, R_BL3, R_PGL) and a
value change of R_BL2; Appendix F lists what a later review must check on each.

Table 0e. Revision-8 changes.

| No. | Change | Findings |
|---|---|---|
| R8-1 | `ERR_MOD_SENSE` (c), the exit hold check, runs only when, in the write iteration and immediately before the write, EF_EN reads H, pin 8 reads HIGH and has read HIGH for at least 2 ms in the current EF_EN-H interval, and V_chg reads at or above 13.5 V. Exits between regen pulses and the probe feed drop are not evaluated; the V_chg term stays (calc8 section 1). | FM5-1, BT5-LS-01, BT5-TR-01 |
| R8-2 | `ERR_MOD_DUMP_ON` is evaluated only in sessions with pin 32 LOW (new dump check, section 9.7b; configuration check; commissioning), on 4-iteration means. A dump-check pass in the power cycle is a precondition of every window of either type. FC windows no longer sample it; `OC_FC` and U_IM cover a dump that sticks later while the module charges. Row F50 restated: U_IM or the eFuse start into overload trips at the eFuse start on most corners (calc8 section 2). | BT5-LS-02, BT5-TR-02, BT5-TR-03 |
| R8-3 | LB-entry series resistors on the flying signal leads that land on an input: R_VC1c 22 kOhm (VC1 tap, C_VC1 moved to the pin side), R_MS3 22 kOhm (MS lead, C_MS stays on the lead side), R_BL3 47 kOhm with R_BL2 82 to 100 kOhm (BAL_OK), R_PGL 22 kOhm (PROFILE). Two signal sleeves without conductors above 3.6 V; C-1 and C-4 insulation tests; rows F54, F54b, F54c (calc8 section 5). | FM5-2, BT5-BO-02 |
| R8-4 | D_VC1 specified at two temperature endpoints: the V_F limit at T_min (ruling OR-AC), the I_R limit at T_M16,max (gate B8). The revision-7 feasibility claim is withdrawn; feasibility is UNCONFIRMED and the part is selected after B8 (calc8 section 3). The `ERR_CELL_MISMATCH` latch leakage is about 114 uA, not 75 uA. | BT5-DS-01, FM5-3 |
| R8-5 | C-2a item 5: pin-25 two-point calibration added; pack at 7.4 V; the D_VC1-short case injected by grounding the tap junction on LB, not by jumpering D_VC1; cell-simulator connection stated; BG-17b repeated after any F47 event. | BT5-BO-03, FM5-4 |
| R8-6 | `ERR_IPACK_PLAUS` gain band uses a separate non-boost load constant I_NB,cal (C-2a item 28) and 1 s means. | FM5-5 |
| R8-7 | Minor findings: self-test entered only from `CHG_BONDED` (BT5-LS-03); regen powered interval includes the VESC-stop tail (BT5-TR-04); B-PKN on the vehicle with RB1A lifted (BT5-DS-02); F_VX data from the 4 A row (BT5-DS-03); R_MD rated on the continuous-pulse curve (BT5-DS-04); pin-20 keeper statement and leakage term (BT5-BO-01); C-2a item 20 at 1 and 3 A, D-3 voiding rule (BT5-BO-04); BG-17 split into BG-17a and BG-17b (BT5-BO-05); CBL2 replaced at M16 and a C-1 VC1 resistance check (BT5-BO-06); S0-11 gains a lower bound on C_mod. | BT5-* minors |
| R8-8 | Completeness item CC-B4 closed by design (calibration record in EEPROM 0-511, State-98 key `7`); CC-B7 narrowed. | CC-B |

### 0.9 Changes from revision 8

Table 0f lists the revision-9 changes. They apply the operator rulings of 2026-11-08 (section 17: OR-P decided, OR-SC
new, OR-O replaced by OR-O'). Appendix G records the inputs and how they were reconciled. Revision 9 adds no hardware:
every change is a firmware rule, a gate, a ruling or a statement.

Table 0f. Revision-9 changes.

| No. | Change | Source |
|---|---|---|
| R9-1 | Ruling OR-P is decided: a purge predictor exists, is the operator's design, is outside the scope of this document and is taken as ideal. It replaces the fw v33b FC-only lockout as the purge gate of every FC-fed session; the lockout keeps refusing FC-only source selection. No section relies any more on the lockout refusing H-20 windows, and no section limits FC windows to a bench supply. | Ruling (1), (2) of 2026-11-08 |
| R9-2 | New section 9.11 "FC windows between purges": the predictor interface (requirements PI-1 to PI-7), the design lead times T_lead,min 60 ms (State 1 and 98) and T_lead,nom 290 ms (State 2), the pre-purge sequence with its timing table, the post-purge re-entry, the EMS interface and the variant evaluation with HR2 recomputed. | calc9 sections 1-5; seq; out |
| R9-3 | Ruling OR-SC: an unpredicted purge may collapse the bus and latch State 99 if no component is damaged. New fault `ERR_FC_ONLY_COLLAPSE` (State 99, no dwell, no BT_BUS re-close) in every session that holds BT_BUS open: a V_chg reading below 13.0 V with EF_EN H after `chargerHasPower()`, or a V_bus reading below 12.0 V. It replaces the revision-7 commanded exit on the same V_chg reading (BT4-TR-06), which could re-close BT_BUS while the FC recovered into a sagged bus (hazard H-R). The safe-collapse teardown and the no-damage argument per mechanism are in section 9.11.5. | pc sections 2-6 |
| R9-4 | Ruling OR-O' replaces OR-O: FC windows open parked (variant P) and in State 2 at standstill (variant D-s, build flag `IC1_FC_RUN_STANDSTILL`). Windows in motion (variant D) are evaluated and not adopted (ruling OR-DM). Inside any FC-fed session the mode manager is the sole writer of pins 27 and 28. | out s4-s5; pc section 7 |
| R9-5 | The entry condition "V_chg below 11 V outside its blanking" takes the literal reading: V_chg below 11 V on two settled iterations. The `ERR_VCHG_FED` blanking delays the latch only. | calc9 section 2 |
| R9-6 | EMS interface: charge_goal is a window request in State 1 and in State 2 at standstill; refusals carry a reason code in protocol v6 (Table 25). | Section 9.11.6 |
| R9-7 | Rows F57-F62; Table 16 (`ERR_FC_ONLY_COLLAPSE`); gates W2 rewritten and W2a-W2d added; V2-6 rewritten; HR2 row; sections 1, 2, 9.7, 9.7a, 9.7b, 12.2, 12.4, 12.6, 12.9, 12.11, 12.12, 14.2, 14.3, 17 and 18 brought into line. | - |

### 0.10 Changes from revision 9

Table 0g lists the revision-10 changes. Appendix H gives the finding-by-finding adjudication. Revision 10 adds no
hardware: every change is a firmware rule, a restriction, a gate, a ruling or a statement.

Table 0g. Revision-10 changes.

| No. | Change | Findings |
|---|---|---|
| R10-1 | PI-4 fails toward policy E2. Inside a session that holds BT_BUS open, an UNKNOWN transition, `purge_active` rising, or a prediction first observed with `purge_tto` below T_late (61 ms) latches `ERR_FC_ONLY_COLLAPSE` (State 99, no BT_BUS re-close); the commanded exit runs only on a timely prediction. A `busHotPlugUnsafe()` refusal at exit step 4 latches on the next iteration that still refuses. The bt6 section-3 grid then gives OPEN in 4860 of 4860 cases, no BT_BUS write after the onset and no turn-on peak above 2.5 A (calc10 section 5). | BT6-LS-01 |
| R10-2 | SC-1 reading (b) (V_bus below 12.0 V, no dwell) stays armed after the BT_BUS re-close write of a prediction exit until the declared purge end (PI-2), so a BT_BUS that never conducts latches State 99 before the FC recovery in all but one case of r6 section 1 (11.74 V at 80 ms, the Table 23 class). New row F63; row F59 corrected; W2c sub-step. | FM6-1 |
| R10-3 | In P and D-s the BT_BUS re-close is the whole ruling-(1) shift: below the 0.25 A gate the share loop holds or freezes the MDAC split, so no share override is written. T_lead,min = 80 ms for every FC-fed session (re-derived over every placement of the iteration gap); T_lead,nom = 290 ms applies only to State 2 in closed loop (filtered total at or above 0.25 A) with no FC-fed session. The admission horizon is 1.282 s for P and D-s. Tables 20-22, 26, PI-1, PI-3, W2b and the host tests restated. | BT6-TR-01, FM6-2, BT6-REQ-04, BT6-LS-03 |
| R10-4 | State-2 standstill window: SC-8 ownership of pins 27 and 28 starts at the first entry write (pin 10) and ends when BT_BUS has conducted after the exit; FC_BUS HIGH, unblanked, with no share-latch cut flag, is re-tested immediately before entry step 5 (else exit, code 11); the D-s entry runs the fw v28 F1 disarm; while a D-s request stands at standstill the mode manager substitutes a strictly in-band share command for an EMS rail command; the S2 restore in `assertFcChargeEnable(true)` is a refusal on the IC1 path. | BT6-LS-02, BT6-REQ-03 |
| R10-5 | New entry condition V_batt at or above `LIMIT_V_BATT_MIN` 7.4 V (refusal code 14); Table 24 D7 and D11 narrowed; a State-99 drain warning and an operating rule (attended parked H-20 windows, Pi alert on any State 99). | BT6-TR-02, BT6-REQ-02 |
| R10-6 | A State-2 traction request released only after BT_BUS has been HIGH for the conduction bound (31.8 ms, W2a); W2b criterion restated. | FM6-3 |
| R10-7 | HR2 stated against EMS requests: D-s carries 107.3 s (24.0 %) of the 446.6 s requested, D 127.5 s (28.5 %); Table 27 labelled as an upper bound. Firmware size re-derived per package. Superseded by R11-3. | BT6-REQ-01, BT6-REQ-05 |

### 0.11 Changes from revision 10

Table 0h lists the revision-11 changes. Appendix I gives the finding-by-finding adjudication. Revision 11 adds no
hardware: every change is a firmware rule, a restriction, a gate, a ruling or a statement.

Table 0h. Revision-11 changes.

| No. | Change | Findings |
|---|---|---|
| R11-1 | The dump check of section 9.7b is also admitted in State 2 under the D-s standstill conditions (`IC1_FC_RUN_STANDSTILL` 1), started by the first D-s request of a power cycle without a pass; the window follows at the same stop. Section 12.4 item 7 and Table 25 code 12 restated. Under the revision-10 text D-s was refused with code 12 on every recorded session; with the State-2 dump check the counterfactual figure is 106.6 s (nominal chain) against 107.3 s (calc11 section 1). | FM7-1, BT7-LS-01 |
| R11-2 | An FC-window request is explicit: the reserved command byte (offset 20, ino:7527) equal to 0xA5 together with `charge_goal` above `CHG_GOAL_MIN`. A `charge_goal` above `CHG_GOAL_MIN` without the flag is refused with the new code 15. A parked request on a Pi-connected vehicle uses `mode_cmd` 4 (ino:7534-7538). The Pi round that sets the flag is a Stage-1 prerequisite (ruling OR-RQ); new gate W2e. | BT7-REQ-01 |
| R11-3 | HR2 against EMS requests restated: the recorded `charge_goal` is the regen latch of the deployed SDP nodes, so the recorded sessions carry 0 s of FC-charge request and HR2 in Run against EMS requests is undetermined; Table 27 stays the upper bound; the D-s/D comparison on the recorded requests and the request-gated basis of OR-DM are withdrawn. | BT7-REQ-02 |
| R11-4 | Fixed window split: from entry step 5 to the BT_BUS conduction after the exit, the share loop, its k_d schedule and every MDAC write are frozen; the mode manager writes one defined split (r = `DROOP_R_MAX` 0.85 at k_d = `K_DROOP`) after BT_BUS has opened and restores the stored split immediately after the exit's BT_BUS write. In-window R_FC 0.094-0.353 Ohm instead of up to 2.0 Ohm (calc11 section 2). W1 and W2b gain a V_chg criterion. | BT7-TR-01 |
| R11-5 | FC_REG HIGH and BT_REG HIGH on two settled iterations join the entry conditions of every FC-fed session (code 11); BT_REG LOW at exit step 4 latches `ERR_FC_ONLY_COLLAPSE` with no BT_BUS write; the State-98 `B` and `F` write forms are refused while an FC-window request stands. | BT7-LS-02 |
| R11-6 | Open item 37 closed by design: before a State-1 or State-98 FC-fed session the mode manager runs the F1 disarm and the guarded FC_BUS latch release when a share-latch or selector flag holds FC_BUS LOW. | BT7-LS-01 (secondary) |
| R11-7 | W1 and W2b gain a hard maximum-iteration criterion (15 ms, against the 19.0 ms bound of the PI-4 late rule) on the production build; the BLG records the iteration that precedes each prediction observation. | FM7-2 |
| R11-8 | The W2b criterion "MDAC codes unchanged from the window close to the onset" is replaced by the section 9.11.3 statement; the standstill auxiliary load and its share-loop regime are recorded. | FM7-3 |

### 0.12 Changes from revision 11

Table 0i lists the revision-12 changes. Appendix J gives the finding-by-finding adjudication. Revision 12 adds no
electrical component. One harness routing rule changes (R12-1); every other change is a firmware rule, a part-selection
requirement, a gate, a ruling or a statement.

Table 0i. Revision-12 changes.

| No. | Change | Findings |
|---|---|---|
| R12-1 | SHDN_EF runs in a sleeve of its own, apart from every other lead (section 5.7 item 4). A short of MD_G to SHDN_EF holds both at 1.55-1.68 V in both EF_EN states, where the TPS26631 state is not specified and Q_MD can run in linear mode; it now needs two insulation failures (new row F66). Gates C-1 and C-4 add lead-to-lead insulation tests inside the CB-LB sleeve and of SHDN_EF against it; C-2b item (h) injects the short; Table 7 records the Q_MD V_GS(th) range and V_GSS (calc12 section 1). | BT8-FM-01 |
| R12-2 | The Idle-entry self-test is no longer aborted by a window request: the window waits for the result. A deferred result refuses windows (new refusal code 16) until a re-run passes; the re-run comes at the first Idle iteration with no State-2 request, and Stage-2 step 10 re-runs when MOT_PWR reads HIGH. The State 0 to State 1 transition is not an Idle entry (sections 9.3, 9.5, 12.4 item 8, Table 16, Table 25; calc12 section 10). | BT8-LS-01 |
| R12-3 | One J-FC bench-supply setting: 12.0 V with a 1.5 A limit for commissioning (pin 32 LOW) and with a 2.0 A limit for every later FC-fed session; a WARNING against J-FC above 12.3 V (pin 24 reaches its 3.6 V absolute maximum at 13.46 V); a V_fc pre-check in C-2b and W1 (section 9.2; calc12 section 2). | BT8-REQ-01 |
| R12-4 | The LB-entry resistors of revision 8 are restated as current limits for the LB side only. The TLV3011B inputs have no clamp to V+, the LVC outputs have no positive clamp, the i.MX RT1062 pad has no injection rating, and no LB-end element protects the CB-end pin of its lead; segregation is the protection of every low-voltage flying lead at both ends (section 5.7 item 4, rows F54b and F54c, Table 7; calc12 section 9). | BT8-DS-01, BT8-DS-02 |
| R12-5 | `ERR_CELL_MISMATCH`: the datasheet pad-leakage bound (1 uA, 488 mV of mismatch) is 12.7 times the allowance, so the 80 mV threshold rests on the C-2a hot and cold record; F47 detection does not depend on it (at least 7.5 V of signal against 0.53 V of worst healthy error; calc12 section 7). | BT8-DS-03 |
| R12-6 | Ruling OR-AC restated: no passive D_VC1 meets both endpoints (a real Schottky leaks about 10 x I_S, so the 40 uA budget holds only to about 44 C even at T_min 25 C; calc12 section 8); option (d), a provisional part for the first build at T_min 25 C, breaks the B8 ordering loop. Gate B8 is split into B8-1 (Stage 1) and B8-2 (Stage 2); B-FPK and B-PKN move ahead of C-2b. | BT8-DS-04, BT8-REQ-02 |
| R12-7 | Minor findings: dump-check trigger on every request while no pass is recorded, one attempt per stop or purge period, three no-verdict attempts per power cycle (BT8-LS-02); C_DV rule against the measured C_mod, the `ERR_MOD_DUMP_ON` sample re-keyed to the measured ramp, C-3 at the largest C_mod (BT8-TR-01); fixed-split code 717 (BT8-TR-02); R_BL2 fixed at 100 kOhm 1 % (BT8-TR-03); W1 as two 30 s windows with a State-98 window-request key, gate order W1, B8-1, W2a, W2e, W2, W2c, W2b, W2d (BT8-REQ-03); HR2 parked figure as net pack current, stale labels, the firmware-size and HIL injection-frame items (BT8-REQ-04). | BT8-* minors |

**Operator rulings of 2026-11-09.** The operator ruled on the open rulings of revision 12 without a revision change
(section 17). OR-AC is decided at option (d) for the first build. The two round-8 residuals are accepted: the row F66
double-insulation residual (Q_MD destruction) and sleeve segregation as the only protection of the low-voltage flying
leads at both ends, with no clamps added. Every other ruling is recorded at the answer that the design proposes or
recommends; six rulings have no single proposed answer and remain open (OR-B, OR-F, OR-J, OR-L, OR-R, OR-X). Table 0i is
unchanged.

## 1. Summary

Revision 12 keeps the revision-3 architecture: a commanded changeover of the pack return, a VOK-gated regen input, an
eFuse charger gate enabled only by FF1 AND a pumped arm AND a source term, resistor-mode Ag105 profiles, and three
assemblies with no ground conductor in the pack-side signal bundle. Revision 8 corrected the defects found in
battle-test rounds 1-5; revision 9 added the FC windows between H-20 purges that the operator rulings of 2026-11-08 ask
for, with no hardware change (section 9.11); revision 10 corrects them after battle-test round 6 (Appendix H) and revision 11 after
battle-test round 7 (Appendix I), again with no hardware change; revision 12 corrects it after battle-test round 8
(Appendix J) with one harness routing rule and no new electrical component.

The safety findings are as follows. Every pack conductor on SB and in the harness is downstream of the pack fuse F_PK,
which sits at the pack terminal (row F43). The balance midpoint reaches PCB GND only through RB3 (clamped by D_VC1) and
RB1A (4.7 kOhm in revision 7, unclamped), so no board fault draws more than 16.2 mA through the balance lead (rows F34b
and F47, calc7 section 1). A VC1 tap on pin 20 detects a shorted clamp and a cell mismatch independently of the BQ29200
(`ERR_CELL_MISMATCH`). The low-voltage flying signal leads run in sleeves that contain no conductor above 3.6 V, and SHDN_EF runs in a
sleeve of its own (revision 12), so a chafe onto a positive conductor, or a short between SHDN_EF and another driven
lead, needs two insulation failures; the LB-entry resistors of revision 8 limit only the LB-side current and do not
protect the inputs or the CB-end pins of the same leads (revision 12, rows F54b, F54c and F66). VBATN_X carries the fast
fuse F_VX at the module end, so a chafe onto a positive conductor in either mode ends as an open lead (row F48). In the
bonded mode the charger input is unfed in Stages 1 and 2, a fed input with both feeds commanded LOW latches
`ERR_VCHG_FED`, and a fed module node in the bonded mode latches `ERR_MOD_FED`, so no single fault recreates the ML0227
configuration (section 11). After every commanded exit the module input node is dumped through R_MD and firmware waits
until the comparator U_MS reads it below 8.69-9.15 V before the re-bond, so the module stops converting with the sense
still in the return path (section 9.5). After a hardware trip the module converts from its own input capacitance for at
most about 1.1 ms with the sense partly bypassed, while the same dump takes the node cold in parallel (row F10). A dump
stuck on is detected by the FC-current step at the eFuse enable of a dump check with pin 32 LOW, or by U_IM at that
start, before the first window of either type in a power cycle (`ERR_MOD_DUMP_ON`, section 9.7b, row F50). The Stage-3 hold-up is withdrawn (section 14.4). In a regen window a bus-fed loop needs two independent failures when `ERR_VCHG_FED` is in service: the
two VOK channels have separate taps, a bus-present comparator makes a bus-tap open fail toward NOT OK, and
`ERR_VOK_STUCK` latches when a channel permits while the measured V-MOT/VBUS ratio is below every healthy release level.
A D-BC-FC or D-BC-RG power-stage short is a one-fault loop path that `ERR_VCHG_FED` detects before any window opens
(note 1 of section 11). An eFuse bypass is detected by the probe of section 9.7a on the module-node comparator, once the
injected-bypass gate has qualified it. In an FC window the BT_BUS clamp prevents the loop and D5 cuts a shorted D-BT-EN
in hardware. A shorted Kelvin pair, which blinds both pack-current channels, latches `ERR_IPACK_PLAUS` at the first
traction above 0.4 A of BT current (row F44). A Teensy reset clears FF1 at once through the buffered pin-33 path; the
pump clear remains as the second layer.

The harvesting findings are unchanged in kind. The 23 W HR1 criterion cannot be met in any regen window: the module
output is limited to 2.5 A including the unregulated VBT load, provided that I_L stays at or below 0.75 A (a regen-window
hold condition, gate B8), and the window entry gate (V_batt below 8.0 V) caps the input at 22.73 W (calc4 section 12).
The 18.9 W peak is met at the regen profile by calculation (19.8-22.4 W with the unverified 0.88 efficiency), at ambient
temperatures up to 45 C (Ag105 DS p.17 Table 9). The window opens on a command step (ruling OR-V'). Under the retired
fw v35 drive law pin 30 was HIGH 5.4-7.4 ms after the braking command, ahead of the VOK assert (calc5 section 7); under
the flashed fw v37 law the arm comes 4-26 ms after a decel step (`calc/bt3_requirements_operability.py` section B), so
the first pulse of a gentle decel can be lost (section 7.8). On the fast (19 ms) regen pulse the hardware chain leaves
about 5.3-6.4 ms for the eFuse ramp and the Ag105 start at typical RT1987 timing, of which the eFuse alone uses
4.4-5.6 ms (calc4 section 11); at the measured 65-170 ms cold start the rise of no pulse is captured, and only the
VESC-stop tail (VOK asserted for 84-416 ms per pulse) can carry charge (section 7.8). On the 23 recorded Pi sessions
the window preconditions of revision 5 admitted regen windows in 2 sessions; revision 6 raises the
`ERR_IPACK_PLAUS` pass rate to 19 of 23 sessions, and the 8.0 V entry gate then leaves 12 of 23 (section 13).

The FC-charging findings of revisions 9 and 10 are as follows (section 9.11). The operator's purge predictor (ruling
OR-P, taken as ideal) must announce each purge at least 80 ms before the onset while an FC window can be open (parked,
or in State 2 at standstill), and 290 ms before it in State 2 while the share loop runs in closed loop; the window then
drops the charger feed, drains the module, bonds the pack and re-closes BT_BUS, which conducts 34-47 ms after the
prediction (61.7 ms on the deadline chain; calc10 section 1). At a standstill load the BT_BUS re-close is the whole
share shift of ruling (1), because the share loop holds its split below the 0.25 A gate (calc10 section 4). Charge
current resumes 0.37-0.49 s after the onset, so 94.5-95.6 % of each 10.34 s purge period is usable, provided that the
Ag105 starts in 65-170 ms; without R_KA a Bring-Up of 8.4-11.7 s leaves 0-0.19 A (calc10 section 2, ruling 9). An
unpredicted purge latches State 99 through `ERR_FC_ONLY_COLLAPSE`, also when the predictor recognises the onset late or
reports UNKNOWN; FC_BUS opens before the earliest FC recovery, no bus switch re-closes, and no damage path was found
for any of the eleven mechanisms examined (section 9.11.5, ruling OR-SC). Parked windows (variant P) deliver 1.17-1.19 A
of net pack current with R_KA (1.18-1.20 A of charger output less the dead-time drain, revision 12). Windows in State 2 at standstill (variant D-s) deliver at most 1.9-31.9 mAh per drive cycle on the plant
model with a request at every stop. On the recorded Pi sessions the EMS made no FC-charge request: the 446.6 s of
`charge_goal` there is the regen gate of the deployed SDP nodes (`calc/bt7_req_origin_output.txt`), so HR2 in Run
against EMS requests is undetermined until an EMS that requests FC charge runs (revision 11). An FC-window request is
therefore an explicit flag in the command packet, which the deployed nodes do not send (section 9.11.6). Windows in
motion (variant D) are not adopted: their traction allowance of 0.06-0.33 A is the size of the current-sense error, and a
purge at a pre-purge I_fc of 1.0-1.25 A is outside the recorded evidence (section 9.11.7). Inside every FC-fed session the
MDAC split is fixed at the FC's smallest droop, so the FC-only window bus sits at 15.5-15.8 V and not at the 13.5-14.1 V
that the closed-loop share clamp would give (calc11 section 2).

The recommended first build, and its end state until the Stage-2 evidence exists, is Stage 0 followed by Stage 1
(section 14). Stage 0 measures the Ag105 unknowns on two spare modules in a rig that reproduces the vehicle charge-mode
topology. Stage 1 delivers FC charging between predicted purges, parked and then at standstill in Run, with the pack
return isolated (gates W2, W2a-W2e); a bench supply on J-FC at 12.0 V (section 9.2) serves the commissioning and the first windows. Stage 2
(regen windows in Run) is held until S0-6 shows a cold start inside the per-family allowance and V2-4 shows captured
charge.

## 2. Requirements and the judges' residual risks

Table 1 maps the eight residual risks of the stage-1 judges to their disposition.

Table 1. Residual-risk disposition.

| No. | Residual risk | Disposition (revision 7; later changes are named in the row) | Where |
|---|---|---|---|
| 1 | HR1 23 W missed at every legal code (code 3 gives 19.8-22.4 W) | Structural to the Ag105 at 2S: I_o <= 2.5 A gives 21.0 W at 7.4 V and at most 22.73 W at the 8.0 V regen entry gate. No switch topology changes it. Ruling OR-B. | Section 7.1, calc4 section 12 |
| 2 | Ag105 cold start and Bring-Up timing unknown (B3-B5); R_KA effect unknown | Stage 0 measures cold start, keep-alive effect, restart and power-up near full charge in a vehicle-topology rig (S0-6 to S0-8b). S0-6 has a per-pulse GO criterion that includes the window-open latency (section 15.1). With VOK gating every pulse needs a start; a hold-up stage is the remaining lever, withdrawn from revision 7 until re-specified (section 14.4, OR-F). | Sections 7.8, 14, 15 |
| 3 | Undocumented internal switch across the sense (B14) | LD tied to Vin- (G5); S0-2 measures the sense in every reachable charge sub-state, with LD tied and open and with R_KA fitted and open; S0-2b repeats the input-cycling pattern of Stage 2. U_C2, the eFuse and U_IM bound the current if the switch conducts. | Sections 3, 15 |
| 4 | Motor-path rulings OR-1 to OR-4 | OR-1 and OR-3 removed by G1. OR-2 shrinks to OR-2': a window ends on any traction request; torque resumes after the measured module drain and the exit confirmation (4.7-6.3 ms at the median loop, 5.3-6.9 ms at the p99 loop for C_mod 100-221 uF, calc6 section 9). OR-4 remains. | Sections 3, 9, 17 |
| 5 | HR2 blocked by the FC-only bus across purges | Revision 9: the ideal purge predictor (ruling OR-P) closes every window before the onset (T_lead,min 80 ms for every FC-fed session, revision 10; T_lead,nom 290 ms for the share shift in closed-loop State 2); an unpredicted purge is a safe collapse into State 99 (ruling OR-SC, `ERR_FC_ONLY_COLLAPSE`). Windows open parked and in State 2 at standstill (OR-O') on an explicit EMS request (OR-RQ, revision 11). Value set by ruling 9 (R_KA) and S0-6; against EMS requests undetermined until an EMS that requests FC charge runs. | Sections 9.7, 9.11, 13 |
| 6 | EPROM write endurance unpublished | Resistor mode for reg 0x00 and reg 0x02 (G6): three commissioning writes, zero runtime writes. | Sections 5.4, 9.2 |
| 7 | Charge-mode circulating flow below I_OL cut only by firmware | Regen window: prevented by VOK on two diverse elements, with fail-safe tap faults (R4-3), and by `ERR_VCHG_FED`, which detects a D-BC-FC or D-BC-RG short before any window (R5-5). FC window: Q_X1 prevents; D5 detects a shorted D-BT-EN and clears FF1. U_IM clears FF1 at 1.51-1.98 A of eFuse input, below the I_OL minimum of 2.06 A (R5-12, R6-5). | Section 11 |
| 8 | Buildability gates (pin-stub cuts, BQ29200 OUT tap, EN trace cuts) | Pre-rework gates D-1, D-2 (with gap insulation), D-3 (vehicle module), B2 (with the module outline), BG-17 (with the open-wire test), P-M1, JBL; M3 and M11 re-sited outside the module body; M5 deferred to Stage 2; mechanical rules and the post-drive gate C-4 (section 5.7). | Sections 5.5, 5.7, 15.2 |

## 3. Graft decisions G1-G10

Table 2 records the decision on each judge graft proposal, with the evidence. Revision-4 amendments are marked.

Table 2. Graft decisions.

| ID | Proposal | Decision | Evidence and resulting design |
|---|---|---|---|
| G1 | 2oo2 VMOT_OK comparators gate D-BC-RG; MOT_PWR stays closed; remove OR-1, OR-2, OR-3; re-key Q_X3 to VMOT_OK. | **ADOPT-MODIFIED** | Two TLV3011B channels with independent 0.1 % dividers and references; VOK = channel 1 AND channel 2; MOT_PWR HIGH through windows; OR-1 and OR-3 removed. (a) The ratio thresholds gain a fixed offset from each comparator's own 1.242 V reference, so VOK reads NOT OK at V-MOT = VBUS = 0 (calc section 2). (b) VOK gates the eFuse as well as the D-BC-RG enable, because the eFuse turns off in 0.8-1.5 us (SLVSE94G section 6.6) while the RT1987 turn-off time is not given. (c) Q_X3 is removed, not re-keyed (a clamp keyed to "REGEN AND charge mode AND NOT VOK" would open BT_BUS for whole windows). (d) OR-2 is reduced to OR-2'. **Revision 4:** (e) each channel has its own V-MOT and VBUS tap pads and wires; (f) a bus-present comparator U_BPk per channel blocks the channel when its bus tap reads below about 9.6 V-equivalent, so a bus-tap open, a lower-leg short or a capacitor short fails toward NOT OK (calc4 section 3); (g) the comparators run from 3V3, so a 5 V loss no longer reads OK. |
| G2 | Hardware BT-loop detector and uncommanded-VCHG-IN detector, both clearing the latches. | **ADOPT-MODIFIED** | D5 adopted for the FC window only: a TLV3011B on the BT-CURR net (INA253A1, 0.1 V/A) at 50 mV, ANDed with the pin-31 net through an arming delay, clears FF1. Trip range 0.31-0.59 A. The uncommanded-VCHG-IN detector is rejected (the eFuse source term already removes charger power with no feed). **Revision 4:** the arming delay is 2.8-6.1 ms (Q_D5 threshold crossing, calc4 section 10), and firmware waits for the BT current to fall below 0.2 A before it raises FC_CHARGE; D5 gains an injection and the ladder bit D5_N. **Revision 5:** a BAT54 (D_D5S) in series with the Q_D5 drain blocks the Q_D5 body diode, which otherwise dragged D5_N to 0.65-1.02 V whenever N1 was LOW (calc5 section 2). **Revision 6:** a module-node comparator U_MS (section 5.3) is adopted after all. The revision-5 rejection rested on reg 0x07 observing the module input, which Ag105 DS p.14 contradicts (all measures read 0xFF in an error state, and the probe state is expected to be a Battery Disconnect error, DS p.6, UNCONFIRMED). |
| G3 | Second independent current amplifier; WDOG1_B into the clear nets. | **ADOPT** | U_SH1 and U_SH2 are separate INA240A3 packages on the same Kelvin pair. **Revision 4:** U_SH2 has its inputs reversed, so a charge current lowers its output and both comparators share one injection topology; the Kelvin pair passes through R_K1/R_K2. WDOG1_B joins N1 through a BAT54 (pin-mux TODO(verify: IMXRT1060RM IOMUXC)). **Revision 5:** pin 20 is configured open-drain (ODE, TODO(verify: IMXRT1060RM IOMUXC)); `ERR_IPACK_PLAUS` covers the shared-Kelvin-pair common cause that the cross-check cannot see. **Revision 7:** the WDOG1_B join (D_N20) is deleted, because pin 20 carries the VC1 tap; the pump and the RTWDOG reset remain. |
| G4 | Pumped dynamic enable toggled only from `loop()`. | **ADOPT-MODIFIED** | The pump replaces FF2 and the TPS3431; PUMP_OK enters N1 and the eFuse AND gate. V_H 3.70 V, ON margin 1.38 V, hang-to-off 43-76 ms, minimum pump rate 26 Hz (calc section 4). **Revision 5:** PUMP_OK joins N1 through the open-drain buffer U_NP, so a shorted join cannot hold N1 HIGH. |
| G5 | Tie Ag105 LD (pin 20) to Vin-; test the sense-parallel switch with LD tied. | **ADOPT-MODIFIED** | LD tied to Vin-. Whether LD also holds the internal switch open is UNCONFIRMED; S0-2 runs with LD tied and open. |
| G6 | Ag105 resistor mode with a Teensy-switched RCS. | **ADOPT-MODIFIED** | Extended to the MPPT threshold (reg 0x02 >= 251 selects the MPPTS resistor, Table 7 JSON). The profile pin changes only while the eFuse is off. RCS 62.0 kOhm (1750 mA) or 62.0 kOhm in parallel with 39.2 kOhm (24.02 kOhm, 1250 mA, Table 4 JSON); MPPTS open (18 V) or 41.7 kOhm (13.82 V by the approximate DS p.10 law). **Revision 4:** every open or short single fault of the networks gives at most 1.75 A (calc section 3). A high-resistance fault of R_CS1 or the CSEL lead can select up to 2.5 A, because Table 4 is monotone in R; `ERR_PROFILE_OC` detects it and U_C2 bounds the pack current (row F38). The MPPTS law is approximate, so the threshold is BENCH (S0-4). **Revision 6:** "while the eFuse is off" is not enough, because the module can stay powered from its input capacitance; the profile changes only on a cold module (pin 8 LOW for 20 ms, section 12.4 item 2), which the dump Q_MD makes reachable within milliseconds. |
| G7 | Pre-window injection self-tests of U_C1/U_C2 and the clamps; VBT-decay test. | **ADOPT in part** | Injection runs at boot and at each Idle entry. **Revision 4:** the injection acts on the signal side (SIG1, SIG2) and the ADC reads SIG1 and SIG2, so an open threshold resistor or an open filter resistor fails the test (calc4 section 5); D5 is injected through pin 35. The clamps Q_X1, Q_X2, Q_RG1, Q_RG2, Q_RB1, Q_RB2 have no readback pins; they are tested at C-2 and B10 only (row F40). The VBT-decay test is rejected (pack positive never leaves VBT). |
| G8 | Remove the J-BL position-3 clamp screw and epoxy the entry. | **ADOPT** | Mechanical prevention of row F12. Screw removability TODO(verify: Same Sky TB005-762 drawing), gate JBL. |
| G9 | Second independent return lead. | **ADOPT-MODIFIED** | Lead B soldered to the underside of the J-BT pin-2 barrel. SB ground 32 mV below PCB GND at 17.1 A instead of 369 mV (calc section 8). **Revision 4:** a joint procedure and a 4-wire acceptance value (M13, C-2). |
| G10 | Collapse digital readbacks into one ladder. | **ADOPT-MODIFIED** | Two 5-bit R-2R ladders (pins 21 and 22), decoded against per-code values calibrated at C-2. **Revision 4:** R = 2.00 kOhm, 2R = 4.02 kOhm and 10 nF give tau 20 us; the largest step settles to 30 mV in 93 us (calc4 section 4). |

## 4. Architecture

### 4.1 Assemblies

The design adds three assemblies to the manufactured board. Table 3 defines them.

Table 3. Assemblies.

| Assembly | Location | Reference node | Contents |
|---|---|---|---|
| **SB** (pack switch board) | In the pack harness, between the keyed pack connector and J-BT | SGND = the S_GND source node, joined to PCB GND only by the two return leads | F_T1, F_T2, R_SH, R_K1, R_K2, R_VPS, S_GND1, S_GND2, S_CHG, gate drive, two open-drain status FETs |
| **Pack fuse** | In the pack-positive lead at the pack terminal, on the pack side of the keyed pack connector | - | F_PK 20 A and its holder |
| **LB** (logic board) | Separate 2-layer board, mezzanine over the J2/RSDA strip or chassis-mounted (section 5.7) | PCB GND (J2 pins 03/04) | FF1 and its input buffers, pump, INA240 x 2, U_C1, U_C2, U_IM, U_MS, U_MDI with R_MDS, injection, VOK x 2 with bus-present comparators (Stage 2), D5, gates, cross-lock clamps, ladders, VC1 tap lower leg R_VC1b/C_VC1 |
| **CB** (charger adapter) | At the Ag105, on the motherboard top side | PCB GND (Ag105 Vin-, pin 4) | TPS26631 eFuse, RCS and MPPTS networks, LD tie, F_VX in VBATN_X, module-node dump Q_MD/R_MD, bleed R_MB, U_MS divider top R_MS1, R_KA (underside) |
| **Balance network** (motherboard, M16) | At the BQ29200 | PCB GND | D_VC1; RB1A replaced by 4.7 kOhm; R_VC1a (VC1 tap top); the revision-6 D_VCB is not fitted |

Pack positive passes F_PK first, at the pack terminal on the pack side of the keyed pack connector, then SB as a
continuous 2.5 mm2 lead with two soldered tap points, to J-BT pin 1. Every SB conductor and both tap points are
downstream of F_PK, so a short of SB pack-positive copper to SGND, PACK- or the pack-negative conductor is in the F_PK
loop (row F43). With F_PK open, both gate supplies collapse and S_GND1/S_GND2 turn off. Their body diodes (anode SGND,
cathode PACK-) hold pack(-) within one diode drop below GND for the BQ29200 supply current, which flows from VBAL+
through RB1B into the BQ29200 and returns through GND, SGND, a body diode, PACK- and R_SH. VC1 - GND therefore stays at
V_cell1 - V_F, which is positive (row F34; calc5 section 1). That VBAL+ is the only remaining source is UNCONFIRMED; gate
B-FPK checks it. The pack's own leads between the cells and the pack terminal remain unfused; their protection is the
pack PCM, whose short-circuit trip is not known (facts_prior section 9).

### 4.2 Grounding and conductor rules

The SB power return reaches PCB GND only through the two return leads: lead A to the J-BT pin-2 screw, and lead B
soldered to the underside of the J-BT pin-2 barrel. **No ground conductor runs in the SB-to-LB signal bundle.** A ground
wire in that bundle would parallel the return leads and carry a share of the pack return current.

**Rule C1.** No pack-referenced conductor leaves SB without a series current-limiting element at its SB end. The rule
gives the following elements: R_K1 and R_K2 (2.2 Ohm fusible) on KS+ and KS-, R_VPS (10 kOhm) on V_PACKN_S, F_T1 and F_T2
(0.5 A) on the gate taps. VBATN_X is a switched power lead and is the exception to the SB-end rule. In the bonded mode
it is GND-referenced through the Ag105 sense R_s (pins 14/15 sit on the sense element inside the module); in the charge
mode it is PACK--referenced through S_CHG. A short of VBATN_X to a positive conductor therefore drives current toward the
module in both modes, and U_C1 cannot open that loop: its only actuator is the bond, and the bond completes the loop
through R_s, GND, S_GND and R_SH (row F48). The series limiting element of VBATN_X is the fast fuse F_VX (4 A) at the
**module end** (CB, at the pin 14/15 stubs), so the whole lead and the SB copper are upstream of it. A short of
VBATN_X to a positive conductor clears F_VX in either mode and leaves row F14. VBATN_X runs in its own sleeve, apart from
the pack-positive lead (section 5.7 item 4).

**Rule C2.** No earth-referenced instrument, supply, load or charger connects to pack(-), KS+, KS-, PACK-, VBATN_X or an
SB node while the pack is installed (section 15, warning). The same rule applies to every Ag105 rig of Stage 0 and to
gate D-3(b), whether or not a pack is connected: the rig has one earth point, at module Vin-; the I2C/MPPTD master is
battery-powered or behind a USB isolator; every measurement on VBat-, VBATN_X, the external shunt or the simulator
negative uses a differential probe, an isolated probe or a floating DMM (section 14.1). No pack-internal conductor (for example a pack NTC returned to
pack(-)) connects to J-NTC, J-BL position 3 or any other PCB GND point; J-NTC pin 2 is PCB GND, so a pack NTC wired to
it would be an F12b-class bond upstream of R_SH. Gate C-1c checks this with the pack installed. The Teensy USB ties PCB GND to the host ground, so an earthed
probe ground on a pack-side node closes a parallel return (row F12b).

The signal crossings are of three kinds:

1. **LB to SB, gate drive.** The FF1Q_SB line drives the Q_A and Q_C gates through 4.7 kOhm and 10 kOhm. The gate
   sources sit on SGND, which is below PCB GND by the lead drop: at most 32 mV at 17.1 A with both leads, and 369 mV with
   lead A alone (calc section 8). A LOW from LB therefore gives a V_GS of at most 0.37 V, below the BSS138 V_GS(th)
   minimum of 0.8 V (onsemi BSS138/D p.2). The dividers pass 0.955 (Q_A) and 0.909 (Q_C) of the offset, so the
   ground offset alone turns Q_A on at 0.84-1.57 V and Q_C on at 0.88-1.65 V (less when hot). An offset that large
   needs both leads open, or lead B open together with lead A above 27 mOhm (49 mOhm at 17.1 A); the result is the
   charge-mode switch state with FF1 clear (row F22b, `calc/verify_sgnd_offset_bothleads.py`).
2. **SB to LB, status.** Q_R1 and Q_R2 are open-drain BSS138s with their sources on SGND. LB pulls each line to 3V3
   through 10 kOhm and clamps it to PCB GND with a BAT54 (anode at GND), so that the line never falls below the
   -0.5 V input limit of the LVC Schmitt inverters (TODO(verify: TI SN74LVC1G14 datasheet)).
3. **Analog.** The R_SH Kelvin pair runs through R_K1 and R_K2 as a twisted pair (24 AWG minimum, keyed connector) to
   the INA240 inputs on LB. The INA240 common-mode range is -4 to 80 V relative to its GND pin (SBOS662C section 7.3),
   and PACK- sits between about -1.0 V and +0.4 V relative to PCB GND. The common-mode absolute minimum is -6 V
   (SBOS662C section 7.1); an open R_SH element puts KS+ at pack(-), up to about 8.4 V below PCB GND, beyond it (row
   F34c). The V_PACKN sense line carries about 16 uA
   through R_VPS (10 kOhm) into the LB divider; R_VPS is part of the divider lower leg (section 7.9).

In the charge mode the S_GND leads carry no current, so SGND equals PCB GND to within millivolts.

### 4.3 Nets

Table 4 lists the new and modified nets. Existing nets keep their schematic names.

Table 4. Net list (new and modified nets).

| Net | Members | Notes |
|---|---|---|
| PACK_POS | Pack terminal; F_PK; pack connector; pack positive wire through SB with the tap points for F_T1 and F_T2 (downstream of F_PK); lead to J-BT pin 1 | Harness and SB |
| PACK_NEG | Pack negative wire to the R_SH pack-end terminal | Harness |
| VMID | Existing net (J-BL 2, RB3, RB1A); RB1A is 4.7 kOhm from revision 7 | Reaches PCB GND only through RB3 (clamped by D_VC1) or RB1A 4.7 kOhm |
| VC1 / VC1_CB | Existing nets (BQ29200 pins 2 / 3, RB3 / RB1A pin-side pads, CBL2 on VC1); VC1 now also carries the D_VC1 cathode and R_VC1a (revision 7: D_VCB deleted, VC1_CB unclamped) | D_VC1 anode on PCB GND (M16) |
| VC1_T | R_VC1a 200 kOhm (at the RB3 VC1 pad, M16) to a flying lead; R_VC1b 200 kOhm and C_VC1 100 nF to GND on LB; Teensy pin 20 (A6) | VC1 tap: V(pin 20) = VC1 / 2 (revision 7) |
| PACK- | R_SH load end, S_GND1 D, S_GND2 D, S_CHG S, R_PD3, Z3 anode, Q_D S, R_PDD, R_VPS | SB node |
| KS+ / KS- | R_SH Kelvin terminals, each through R_K1 / R_K2 at the terminal, to U_SH1 IN+ / IN- and U_SH2 IN- / IN+ | Twisted pair, SB to LB |
| SGND | S_GND1 S, S_GND2 S, Q_A1 S, Q_A2 S, Q_C S, Q_R1 S, Q_R2 S, Z1/Z2 anodes, R_PA1, R_PA2, R_PC, R_SP1, R_SP2, C_VT1b, C_VT2b, lead A, lead B | SB local reference |
| VBT_T1 / VBT_T2 | Pack positive through F_T1 / F_T2 0.5 A; VBT_T1: R_GU1, Q_B S, R_BU, C_VT1a; VBT_T2: R_GU2, C_VT2a | SB gate supplies, one per channel |
| G1 / G2 | S_GND1 / S_GND2 gates; R_GUk, Zk cathode, Q_Ak D, D_Dk anode, R_SRk | Per channel |
| G3 | S_CHG gate; R_B3, R_PD3, Z3 cathode, Q_D D | Referenced to PACK- |
| VBATN_X | S_CHG D; flying lead (own sleeve) to F_VX on CB | Harness |
| VBATN_M | F_VX module side; short lead (at most 30 mm) to the Ag105 pins 14/15 module-side stubs | Replaces their GND connection |
| FF1Q_SB | U_BF output (LB); R_GA1, R_GA2, R_CQ (SB) | Gate-drive line |
| UC1_N | U_C1 output (LB); D_A1/D_A2 cathodes (SB); D_NC1 cathode (LB) | U_C1 direct path to the Q_A gates |
| UC2_N | U_C2 output; D_NC2 cathode | LB |
| SG1_RB / SG2_RB | Q_R1 / Q_R2 drains (SB); R_SG1/R_SG2, D_SG1/D_SG2, U_SG1/U_SG2 inputs (LB) | LOW = S_GND k enhanced |
| SG1_ON / SG2_ON | U_SG1 / U_SG2 outputs; D_X2 / D_X3; ladder B bits 0 / 1 | HIGH = S_GND k enhanced |
| V_PACKN_S | R_VPS (SB) to R_V2 (LB) | V_PACKN sense |
| P33B | U_P33 output; U_N33 input; R_CK | Buffered pin 33 |
| CLK_RC | R_CK, C_CK, U_CKS input | FF1 clock delay |
| N1 | R_N1 to 3V3; U_N33 and U_NP open-drain outputs; anodes of D_NC1, D_NC2, D_NIM, D_D5S; Q_OV D; U_CLS input | Wired-AND clear net (every source open-drain or diode-isolated from an open-drain node); U_CLS output drives U_FF /CLR |
| PUMP_A / PUMP_H | Pump coupling node / hold node | LB |
| PUMP_OK | U_PS output; U_NP input; U_AND input; ladder A bit 3 | LB |
| SIG1 / SIG2 | R_F1 / R_F2 output; C_F1 / C_F2; U_C1 / U_C2 IN+; R_I1 / R_I2; R_A16 / R_A17 to pins 16 / 17 | Filtered current signals |
| OK1_N / OK2_N | U_V1 / U_V2 outputs; R_UP1/R_UP2 to 3V3; Q_H1/Q_H2 gates; Q_RG1/Q_RG2 gates; U_CH1/U_CH2 inputs | LOW = V-MOT tap above the bus tap |
| BP1_N / BP2_N | U_BP1 / U_BP2 outputs; R_BP1/R_BP2 to 3V3; Q_RB1/Q_RB2 gates; U_CH1/U_CH2 inputs | HIGH = bus tap below the bus-present level |
| CH1_OK / CH2_OK | U_CH1 / U_CH2 outputs; U_VA inputs; ladder B bits 2 / 3 | HIGH = channel k permits |
| VOK / RGQ / SRC | U_VA output (Stage 1: R_VKP 100k to GND, U_VA not fitted) / U_RS output = VOK AND p30 / U_OR output = RGQ OR FCQ | LB |
| P30Q | Pin-30 net tap (J1 43/44) through R_RQ 1k; R_RQP 100k to GND; U_RS input | LB |
| UIM_N | U_IM output; R_UIM 10k to 3V3; D_NIM cathode | LOW = eFuse input above the 1.51-1.98 A trip |
| FCQ | Pin-31 net tap (J1 45/46) through R_FQ; R_FQP to GND; U_OR input; Q_X1 gate; R_D5d | LB |
| EF_EN | U_AND output; R_SD; U_MDI input; ladder A bit 1 | LB |
| MD_G | U_MDI output through R_MDS 1k (LB); wire to CB; R_MDG 100k to GND; Q_MD gate | HIGH = dump on (EF_EN L) |
| MS / MS_D | R_MS1 100k (at the VCHG-IN_M end, CB) to MS_D; wire to LB; R_MS2 16.2k and C_MS 1 nF to GND; U_MS IN+ | Divided module node |
| MOD_COLD_N | U_MS output; R_UMS 10k to 3V3 (LB); tap to Teensy pin 8 (J1 19/20) | LOW = module node below 8.69-9.15 V (cold); HIGH = fed, or the sense path open or unpowered |
| SHDN_EF | U_EF SHDN; R_SD; R_SDP 22 kOhm to GND (CB) | LB to CB |
| EF_FLT_N | U_EF FLT; R_FLT 10 kOhm to 3V3 (LB); ladder A bit 2 | LOW = eFuse fault |
| D5_N | U_D5 output; R_UD5; Q_D5 S; ladder B bit 4 | LOW = BT current above the D5 level |
| D5_D | Q_D5 D; D_D5S cathode | Isolates the Q_D5 body diode from N1 |
| BAL_OK | R_BL1 from J-BL pin 1 (VBAL+); R_BL2 to GND; ladder A bit 4 | HIGH = balance lead present |
| VCHG-IN | Existing net (D-BC-FC VOUT, D-BC-RG VOUT, C-D8, C-D10, R1-CHG); now also U_EF IN and IN_SYS, C_EI, R_UV1 | Ag105 pin 10 board-side stub |
| VCHG-IN_M | U_EF OUT, C_EO, Ag105 pin 10 module-side stub, R_MD (to Q_MD D), R_MB, R_MS1 | CB |
| EN_SQ_X / EN_BE_X / EN_RG_X | EN-pad sides of the cuts in nets D-BT-SQ, D-BT-EN, D-BC-RG | Driven through R_S32, R_S28, R_S30 |
| X | Q_X2 gate; C_X, R_X; D_X1 + R_X1 from FF1./Q, D_X2 + R_X2 from SG1_ON, D_X3 + R_X3 from SG2_ON | D-BT-SQ cross-lock |
| PROFILE | Pin-10 line; R_P10; Q_I1b gate; Q_INV gate; CB Q_CS/Q_MP gates through R_PG | Profile select |
| CSEL_N / MPPTS_N | Ag105 CSEL pad (pin 2) to R_CS1, R_CS2; MPPTSEL pad (pin 12) to R_MP | CB |
| STAT_A / STAT_B | Ladder outputs to pins 21 / 22 | LB |
| BAL_OUT | BQ29200 pin 8 fly-wire to R_OVG | Pack OVP actuation; Q_OV gate pulled up to 3V3 by R_OVP (an open wire clears FF1) |

## 5. Schematics, components and motherboard modifications

### 5.1 Pack switch board (SB)

Figure 1 shows SB.

```
 Figure 1. SB (SGND is the local reference of the S_GND drive; PACK- is the reference of the S_CHG drive)

 Positive lead (rev 5): F_PK at the pack terminal, upstream of the connector and of every SB conductor
   pack(+) ─ F_PK 20 A ─ pack connector ─┬───────────────────────── J-BT pin 1 (VBT)
                                         ├─ tap 1 ─ F_T1 0.5 A ─ VBT_T1 ; C_VT1a 2.2 uF ─ C_VT1b 2.2 uF ─ SGND  (series pair)
                                         └─ tap 2 ─ F_T2 0.5 A ─ VBT_T2 ; C_VT2a 2.2 uF ─ C_VT2b 2.2 uF ─ SGND

 Negative lead:
   pack(-) ─┬─ R_K1 2.2 Ohm fusible (soldered at the R_SH pack-end Kelvin terminal) ─ KS+ (to LB)
            R_SH 0.5 mOhm (4-terminal)
            ├─ R_K2 2.2 Ohm fusible (soldered at the R_SH load-end Kelvin terminal) ─ KS- (to LB)
            └───────────────── PACK- ──┬──────────────┬─────────────────────┐
                                       │D             │D                    │S
                                    S_GND1         S_GND2                S_CHG
                                       │S             │S                    │D
                                       └──── SGND ────┘                     └── VBATN_X ─ lead (own sleeve) ─ F_VX 4 A (CB) ─ Ag105 pins 14/15
                                              ├─ lead A ─ J-BT pin 2 (screw)
                                              └─ lead B ─ J-BT pin 2 barrel underside (solder, G9)

 Per channel k = 1, 2:
   VBT_Tk ─ R_GUk 10k ─┬─ Gk (S_GNDk gate) ── Zk BZT52C15 ── SGND
                       ├─ Q_Ak D (BSS138, S = SGND); Q_Ak G ─ R_GAk 4.7k ─ FF1Q_SB ; R_PAk 100k ─ SGND
                       │                              Q_Ak G ─ D_Ak BAT54 ─► UC1_N  (cathode at UC1_N)
                       ├─ D_Dk BAT54 (anode at Gk) ─ R_Dk 47k ─► node DQ
                       └─ R_SRk 47k ─┬─ Q_Rk G (BSS138, S = SGND, D = SGk_RB to LB)
                                     └─ R_SPk 47k ─ SGND
   node DQ ─ Q_D G (BSS138, S = PACK-) ; R_PDD 100k ─ PACK-

 S_CHG drive (from VBT_T1):
   VBT_T1 ─ R_BU 100k ─┬─ Q_B G (BSS84, S = VBT_T1)
                       └─ R_BC 33k ─ Q_C D (BSS138, S = SGND)
   Q_C G ─ R_CQ 10k ─ FF1Q_SB ; C_CQ 10 nF ─ SGND ; R_PC 100k ─ SGND
   Q_B D ─ R_B3 1k ─ G3 (S_CHG gate) ─┬─ R_PD3 47k ─ PACK-
                                      ├─ Z3 BZT52C15 ─ PACK-
                                      └─ Q_D D

 V_PACKN sense: PACK- ─ R_VPS 10k ─ V_PACKN_S (to LB)
```

Every S_GND channel turns ON passively through R_GUk from its own tap when Q_Ak is off. That is its state with FF1Q_SB
LOW, open or undriven. Loss of one tap, fuse or capacitor pair removes one channel only (row F31). The common causes of
both taps are the pack-positive conductor and F_PK; when either opens, the pack supplies nothing, so no return current
flows (row F34).
S_CHG turns ON only when FF1Q_SB has been HIGH for longer than the R_CQ/C_CQ delay and neither S_GND gate is above the
Q_D threshold. Q_Rk turns ON when Gk exceeds about twice its own threshold (divider 47k/47k), that is when S_GNDk is
enhanced; the line SGk_RB is then LOW.

R_K1 and R_K2 are matched 1 % fusible flame-proof resistors (TODO(select): a metal-film fusible type with a published
fusing curve). A KS lead shorted to pack positive carries at most 3.85 A and puts 32.5 W into a 0.25 W part (130 times
its rating), so the resistor opens and the signal wire never carries the pack's prospective current (calc4 section 1).

### 5.2 Logic board (LB)

Figure 2 shows the permit latch, its input buffers, the pump, the clear net N1 and the eFuse enable logic.

```
 Figure 2. LB: permit latch FF1, pumped arm, clear net N1 and eFuse enable (rev 5 input network)

 pin 33 ─┬─ R_P33 10k ─ GND
         └─ U_P33 (SN74LVC1G17, 3V3) ─ P33B
 P33B ─┬─ R_CK 10k ─┬─ U_CKS (SN74LVC1G17) ─ U_FF CLK     U_FF (SN74LVC1G74): D = 3V3 ; /PRE = 3V3 ; Q = FF1.Q ; /Q = FF1./Q
       │            └─ C_CK 1 nF C0G ─ GND
       └─ U_N33 (SN74LVC1G07, open-drain) ─ N1        (P33B LOW pulls N1 LOW; P33B HIGH releases N1)

 N1 ─ U_CLS (SN74LVC1G17) ─ U_FF /CLR ; R_N1 10k ─ 3V3. Each of the following pulls N1 LOW:
   U_N33 (P33B LOW) ; U_NP (PUMP_OK LOW) ; D_NC1 (UC1_N LOW) ; D_NC2 (UC2_N LOW) ; D_NIM (UIM_N LOW) ;
   D_D5S + Q_D5 (D5 trip while FCQ armed) ;          (rev 7: the WDOG1_B join D_N20 is deleted)
   Q_OV (BQ29200 OUT HIGH, or the OUT fly-wire open)
   (every BAT54 has its anode at N1 and its cathode at an open-drain source node; no source can drive N1 HIGH)

 Pumped arm:
   pin 34 ─ R_P34 10k ─ GND
   pin 34 ─ U_PD (SN74AHCT1G125, VCC = 5V, /OE = GND) ─ R_P1 470 ─ C_P1 1 uF C0G ─ PUMP_A
   PUMP_A ─ D_P1 BAT54 (anode GND, cathode PUMP_A)
   PUMP_A ─ D_P2 BAT54 (anode PUMP_A, cathode PUMP_H)
   PUMP_H ─ C_P2 1 uF ─ GND ; R_P2 47k ─ GND ; U_PS input (SN74LVC1G17, VCC 3V3) ; U_PS output = PUMP_OK
   PUMP_OK ─ U_NP (SN74LVC1G07, open-drain) ─ N1

 FF1.Q ─ U_BF (SN74LVC1G17) ─ FF1Q_SB (to SB)
 VOK (from Figure 4), P30Q ─ U_RS (SN74LVC1G08) ─ RGQ          (rev 5: the regen source needs pin 30 as well as VOK)
 RGQ, FCQ ─ U_OR (SN74LVC1G32) ─ SRC
 FF1.Q, PUMP_OK, SRC ─ U_AND (SN74LVC1G11) ─ EF_EN ─ R_SD 1k ─ SHDN_EF (to CB; R_SDP 22k to GND at CB)
 EF_EN ─ U_MDI (SN74LVC1G04, 3V3) ─ R_MDS 1k ─ MD_G (wire to CB; R_MDG 100k to GND at CB) ─ Q_MD gate   (dump on while EF_EN L; rev 7: R_MDS)
 MS_D (from R_MS1 at CB) ─┬─ R_MS2 16.2k 0.1 % ─ GND ; C_MS 1 nF C0G ─ GND      (lead side, at the LB entry)
                          └─ R_MS3 22k ─ U_MS IN+ (TLV3011B, 3V3); U_MS IN- = U_MS REF (1.242 V)   (rev 8: R_MS3)
 U_MS OUT = MOD_COLD_N ; R_UMS 10k ─ 3V3 ; tap to Teensy pin 8 (J1 19/20)      (rev 6: LOW = module node below 8.69-9.15 V)

 FCQ:  pin-31 net (J1 45/46) ─ R_FQ 1k ─ FCQ ; R_FQP 100k ─ GND
 P30Q: pin-30 net (J1 43/44) ─ R_RQ 1k ─ P30Q ; R_RQP 100k ─ GND
 VOK in Stage 1: U_VA not fitted; R_VKP 100k holds VOK LOW
 OVP:  BQ29200 pin 8 (fly-wire) ─ R_OVG 1k ─ Q_OV G (BSS138, S = GND, D = N1) ; R_OVP 1M ─ 3V3   (rev 5: pull-UP)
 VC1 tap (rev 7): VC1 pad at M16 ─ R_VC1a 200k ─ flying lead ─ VC1_L ; R_VC1b 200k 0.1 % ─ GND (at the LB entry)
          (rev 8): VC1_L ─ R_VC1c 22k ─ VC1_T ─ Teensy pin 20 (A6) ; C_VC1 100 nF ─ GND (pin side)
 IMON: U_EF IMON (CB, R_IM 10k) ─ wire ─ R_IMF 10k ─ U_IM IN- ; C_IMF 10 nF ─ GND          (filter tau 0.1 ms)
       U_IM (TLV3011B, 3V3): IN+ = 3V3 x 10.0k / (59.0k + 10.0k) = 0.478 V (R_IMa 59.0k, R_IMb 10.0k, 0.1 %)
       U_IM OUT = UIM_N ; R_UIM 10k ─ 3V3 ; ─◄ D_NIM BAT54 ─ N1        (LOW when the eFuse input exceeds 1.51-1.98 A)
```

With pin 33 high-Z (reset, boot before `setup()`, brownout), the U_P33 input sits at I_I x R_P33 = 50 mV at most, so
P33B is LOW, U_N33 pulls N1 LOW and U_CLS holds /CLR LOW: FF1 clears at once (calc4 section 6, with the open-drain
output in place of the BAT54 the N1 level is lower). Because every N1 source is open-drain or a BAT54 whose cathode sits
on an open-drain node, a shorted join can only hold N1 LOW (FF1 cannot set: detected by self-test step 4), never HIGH.
The CLK path sits at 0 V, so no clock edge can occur. On a commanded set, U_CKS switches 5.6-9.9 us after P33B rises,
and N1 releases /CLR within 1.1 us at a node capacitance of 130 pF: the margin is at least 4.5 us (up to 668 pF is
tolerated, `calc/verify_lb_placement.py`). U_CKS and U_CLS give both FF1 inputs nanosecond edges, which meets the LVC74
input transition-rate limit (SCES794G section 6.3).

U_IM watches the eFuse current monitor (GAIN(IMON) 25.66 / 27.9 / 30.14 uA/A for 0.6-2 A, SLVSE94G section 6.5, into
R_IM 10 kOhm). Including that gain range, the TLV3011B offset, the rising-input half of its hysteresis, the 0.1 %
divider and R_IM, it trips at 1.56-1.92 A of eFuse input at 3V3 = 3.30 V and at 1.51-1.98 A over 3V3 = 3.2-3.4 V
(calc6 section 5; `calc/verify_bt3_uim_gain_window.py`). The lower end is 0.050 A above the largest legitimate input
(1.458 A at the 2.5 A output ceiling, efficiency 0.80 and the 18 V threshold, `calc/bt3_datasheet_lens_calcs.py`
section 1); the upper end is 0.078 A below the I_OL minimum of 2.06 A that R_ILIM 8.06 kOhm sets (revision 5 used
9.09 kOhm, whose 1.82 A I_OL minimum lay inside the trip range). The window is held per unit by gate S0-12b, which trims
R_IMa on the fitted CB if the measured trip falls outside I_OL - 0.05 A and 1.46 + 0.05 A. U_IM clears FF1 in a start
into an overload, where the eFuse limits the current in thermal regulation for up to 2.9 s without asserting FLT
(section 7.5). A clear of FF1 ends the window; FF1 then needs a new pin-33 edge, so a regen window cannot repeat the
overload on every pulse.

R_OVP pulls the Q_OV gate up to 3V3. The BQ29200 OUT low state sinks at least 30 uA at 0.05 V (SLUSA52C section 7.5),
so with the fly-wire intact OUT holds the gate at about 6 mV against the 3.3 uA pull-up. With the fly-wire open, the gate
rises to about 3.3 V, above the 1.5 V maximum BSS138 threshold, and Q_OV holds N1 LOW: FF1 cannot set (detected at
self-test step 4 and window entry). At an OVP event OUT drives 6-9.5 V through R_OVG and back-feeds at most 6.2 uA into
3V3. A short of the fly-wire to GND remains latent (row F25).

The VC1 tap enters LB through R_VC1c (revision 8). R_VC1b stays on the lead side, so the DC ratio remains VC1 / 2; C_VC1
moves to the pin side and the tap filter becomes 12.2 ms. In revision 7 the flying lead was the pin-20 node itself, so a
chafe of the lead onto VBT, VBUS or VCHG-IN put 8.5-21.5 V on the pin with no current limit; R_VC1c limits the current
to 0.22-0.81 mA (calc8 section 5, row F54b). The pad has no rated injection current (IMXRT1060CEC Table 7 rates the
pad voltage only to OVDD + 0.3 V), so a pad clamp that conducts this current operates outside the rating (revision 12,
BT8-DS-02); the protection of the lead is its sleeve. The same series elements sit on MS_D (R_MS3), BAL_OK (R_BL3)
and PROFILE (R_PGL), section 5.7 item 4.

Figure 3 shows the pack-current channels, the comparators, the injection network and the BT-loop detector.

```
 Figure 3. LB: U_SH1/U_SH2, U_C1/U_C2, injection and D5

 KS+ ─┬─ U_SH1 IN+      KS- ─┬─ U_SH1 IN-     (INA240A3, VS = 3V3, REF1 = 3V3, REF2 = GND, 100 nF decoupling)
      └─ U_SH2 IN-           └─ U_SH2 IN+     (rev 4: reversed, so a charge current LOWERS OUT2)

 U_SH1 OUT ─ R_F1 1.5k ─ SIG1 ; C_F1 47 nF ─ GND ; SIG1 ─ R_A16 1k ─ pin 16
 U_C1 (TLV3011B, 3V3): IN+ = SIG1 ; IN- = TH1 = 3V3 x 10.0k / (12.0k + 10.0k) = 1.500 V  (R_T1a 12.0k top, R_T1b 10.0k bottom)
                       OUT = UC1_N ; R_UC1 10k ─ 3V3        LOW when SIG1 < TH1 (discharge > 3.00 A)

 U_SH2 OUT ─ R_F2 1.5k ─ SIG2 ; C_F2 47 nF ─ GND ; SIG2 ─ R_A17 1k ─ pin 17
 U_C2 (TLV3011B, 3V3): IN+ = SIG2 ; IN- = TH2 = 3V3 x 10.0k / (12.1k + 10.0k) = 1.493 V  (R_T2a 12.1k top, R_T2b 10.0k bottom)
                       OUT = UC2_N ; R_UC2 10k ─ 3V3        LOW when SIG2 < TH2 (charge > 3.14 A)

 Injection (pin 35 TEST_INJ, R_P35 10k ─ GND; pin 10 PROFILE, R_P10 10k ─ GND), signal side (rev 4):
   SIG1 ─ R_I1 8.2k ─ Q_I1a (G = pin 35) ─ Q_I1b (G = pin 10) ─ GND        SIG1 to 0.845 x OUT1 (about 5.1 A equivalent)
   SIG2 ─ R_I2 8.2k ─ Q_I2a (G = pin 35) ─ Q_I2b (G = PROFILE_N) ─ GND     SIG2 to 0.845 x OUT2
   PROFILE_N: 3V3 ─ R_INV 100k ─ Q_INV D (G = pin 10, S = GND)
   pin 35 ─ R_I3 100k ─ D_I3 BAT54 ─► U_D5 IN-                             D5 injection (+0.27 V, about 2.7 A equivalent)

 D5 BT-loop detector (U_D5 TLV3011B, 3V3):
   BT-CURR tap (J2 31/32) ─ R_D5a 10k ─ U_D5 IN- ; C_D5a 100 nF ─ GND               (filter tau 1 ms)
   U_D5 IN+ = 3V3 x 1.00k / (64.9k + 1.00k) = 50.1 mV                                (R_D5b 64.9k, R_D5c 1.00k)
   U_D5 OUT = D5_N ; R_UD5 10k ─ 3V3 ; ladder B bit 4                                (LOW when I_BT > 0.5 A)
   Q_D5 (BSS138): D = D5_D, S = D5_N, G = FCQ delayed (R_D5d 100k, C_D5d 100 nF, D_D5 BAT54 for a fast fall)
   D_D5S BAT54: anode at N1, cathode at D5_D            (rev 5: blocks the Q_D5 body diode when N1 is LOW)
```

The Q_D5 body diode has its anode at the source (D5_N). Without D_D5S, every LOW on N1 (pin 33 LOW, any clear source)
dragged D5_N to 0.65-1.02 V through that diode, so self-test step 1 failed on a healthy board and the step-6 "D5_N L"
check passed whatever U_D5 did. With D_D5S the diode is reverse-biased whenever N1 is below D5_N, so D5_N reads the
U_D5 output alone (at least 3.28 V released, calc5 section 2). On a D5 trip with FCQ armed, N1 sits at most at 0.42 V,
below the U_CLS VT- minimum of 0.89 V (calc5 section 2; VT- at 3.3 V TODO(verify: SCES351)). With FCQ HIGH, D_D5S also
blocks the Q_D5 channel in the reverse direction, so another clear source no longer pulls D5_N LOW and a trip is no
longer misattributed to D5.

The injection pulls the comparator signal node down through R_I against R_F, so the test passes only if the signal
path, the threshold and the comparator all work. The ADC reads SIG1 and SIG2 during the injection: an open R_F reads
about 0 V, an open R_I reads no change. An open upper threshold resistor puts the threshold at 0 V and the injection does
not trip; an open lower threshold resistor puts it at 3V3, and FF1 cannot set (calc4 section 5).

Figure 4 shows one VOK channel. Channel 2 is identical, with its own parts, its own taps and its own wires.

```
 Figure 4. LB: VOK channel k (k = 1, 2); U_Vk and U_BPk = TLV3011B at 3V3 (rev 4)

 V-MOT tap k ─ R_Mk1a 49.9k ─ R_Mk1b 49.9k ─ MTk ─┬─ R_Mk2 13.6k ─┬─ R_Mk3 715 ─ GND
                                                  │               └─ Q_Hk D (BSS138, S = GND, G = OKk_N)   shorts R_Mk3
                                                  ├─ C_Mk 1 nF ─ GND
                                                  └─ U_Vk IN-
 VBUS tap k  ─ R_Bk1a 49.9k ─ R_Bk1b 49.9k ─ BTk ─┬─ R_Bk2 14.9k ─ GND
                                                  ├─ R_Ok 301k ─ U_Vk REF (1.242 V)
                                                  ├─ C_Bk 1 nF ─ GND
                                                  ├─ U_Vk IN+
                                                  └─ U_BPk IN-          U_BPk IN+ = U_BPk REF (1.242 V)
 U_Vk  OUT = OKk_N ; R_UPk 10k ─ 3V3        LOW = OK (V-MOT tap above the bus tap)
 U_BPk OUT = BPk_N ; R_BPk 10k ─ 3V3        HIGH = BTk below REF: bus below 9.3-9.8 V, bus tap open, or lower leg shorted
 OKk_N ─ Q_RGk G ; BPk_N ─ Q_RBk G          (BSS138, D = EN_RG_X, S = GND): either HIGH clamps the D-BC-RG enable
 OKk_N, BPk_N ─ U_CHk (SN74LVC1G02) ─ CHk_OK (HIGH = channel k permits) ─ ladder B bit (k + 1)
 CH1_OK, CH2_OK ─ U_VA (SN74LVC1G08) ─ VOK
 All divider resistors 0.1 %. R_Mk1a and R_Bk1a mount at the tap ends on an adhesive-staked tab (section 5.7);
 no tap is soldered to an MLCC termination.
 Taps (no two share a pad, a joint or a wire): channel 1 V-MOT at J-M pin 1, VBUS at the R1-BUS pin-2 pad;
                                               channel 2 V-MOT at the CAL pad 1, VBUS at a VBUS via or exposed VBUS
                                               copper that does not share a pad with channel 1 (TODO(verify: BRD net VBUS
                                               via list)), not at the C-D2 MLCC.
 Stage 1 fits none of Figure 4: OK1_N, OK2_N, BP1_N, BP2_N, U_CH1, U_CH2, U_VA, Q_H1, Q_H2, Q_RG1, Q_RG2, Q_RB1 and
 Q_RB2 are Stage-2 parts. In Stage 1 the ladder-B bit-2 and bit-3 inputs are tied to GND through R_CHP1 and R_CHP2
 (100 kOhm) and VOK through R_VKP (Figure 2).
```

A bus-tap open leaves BTk at 58.6 mV and a lower-leg or capacitor short leaves it at 0 V; in each case BPk_N goes HIGH
and the channel blocks (calc4 section 3). A V-MOT-side open, or a short of R_Mk2, R_Mk3 or C_Mk, pulls MTk LOW and the
channel reads NOT OK. A short of the V-MOT top string, or an open R_Mk2, makes one channel read OK at bus level; the
other channel blocks, and `ERR_VOK_STUCK` latches when the channels disagree for 50 ms (row F15b). At the lowest window
bus of 13.5 V BTk is 1.733 V, above the 1.269 V worst bus-present threshold.

Figure 5 shows the cross-locks on the three cut enable nets, the S_GND status inputs and the status ladders.

```
 Figure 5. LB: enable cross-locks, status inputs and ladders

 pin 32 net (Teensy side of the cut) ─ R_S32 4.7k ─ EN_SQ_X ─ Q_X2 D (BSS138, S = GND, G = X)
   X: C_X 100 nF ─ GND ; R_X 47k ─ GND ; charged through D_X1 + R_X1 10k from FF1./Q,
      D_X2 + R_X2 10k from SG1_ON, D_X3 + R_X3 10k from SG2_ON
 pin 28 net ─ R_S28 4.7k ─ EN_BE_X ─ Q_X1 D (BSS138, S = GND, G = FCQ)
 pin 30 net ─ R_S30 4.7k ─ EN_RG_X ─ Q_RG1 D, Q_RG2 D, Q_RB1 D, Q_RB2 D (BSS138, S = GND)   (Stage 2 only, with M5)

 SGk_RB (from SB) ─┬─ R_SGk 10k ─ 3V3
                   ├─ D_SGk BAT54 (anode GND, cathode SGk_RB)
                   └─ U_SGk (SN74LVC1G14) input ; output = SGk_ON (HIGH when S_GNDk is enhanced)

 Ladder A ─ pin 21: 5-bit R-2R (R = 2.00k, 2R = 4.02k, 0.1 %), bits driven by U_LA (SN74LVC244A, 3V3):
   bit 0 FF1.Q ; bit 1 EF_EN ; bit 2 EF_FLT_N ; bit 3 PUMP_OK ; bit 4 BAL_OK        C_LA 10 nF C0G at the pin
 Ladder B ─ pin 22: same network, U_LB:
   bit 0 SG1_ON ; bit 1 SG2_ON ; bit 2 CH1_OK ; bit 3 CH2_OK ; bit 4 D5_N            C_LB 10 nF C0G at the pin
 BAL_OK: J-BL pin 1 (VBAL+) ─ R_BL1 150k (at the tap) ─ lead ─ R_BL3 47k (LB entry, rev 8) ─ BAL_OK (U_LA input) ─ R_BL2 100k ─ GND
 V_PACKN: 3V3 ─ R_V1 100k ─ pin 23 ─ R_V2 100k ─ V_PACKN_S ─ R_VPS 10k (SB) ─ PACK- ; C_V 10 nF ─ GND
          V(pin 23) = 1.7286 V + 0.4762 x V_PACKN at 3V3 = 3.30 V ; V_PACKN = 2.100 x V(pin 23) - 1.100 x 3V3
```

### 5.3 Charger adapter (CB)

Figure 6 shows CB.

```
 Figure 6. CB (at the Ag105; GND = Ag105 Vin-, pin 4)

 VCHG-IN (Ag105 pin 10 board-side stub) ─┬─ U_EF IN (pins 1-3) and IN_SYS (pin 6)     (TPS26631PWPR; approved alternate TPS26636PWPR, pin 8 = PLIM to GND)
                                         ├─ C_EI 1 uF 50 V ─ GND
                                         └─ R_UV1 100k ─ UVLO (pin 7) ─ R_UV2 10.5k ─ GND   (rev 4)
 U_EF OUT (pins 18-20) ─ VCHG-IN_M ─ Ag105 pin 10 module-side stub ; C_EO 1 uF 50 V ─ GND
 VCHG-IN_M (rev 6) ─┬─ R_MD 15 Ohm pulse-rated ─ Q_MD D (logic-level N-MOSFET, S = GND, G = MD_G from LB U_MDI; R_MDG 100k ─ GND)
                    ├─ R_MB 3.3k 2010 0.5 W ─ GND                                   (bleed, independent of the module idle current)
                    └─ R_MS1 100k 0.1 % ─ MS_D (wire to LB: R_MS2, U_MS)               (module-node sense)
 VBATN_X (from SB) ─ F_VX 4 A fast-acting ─ VBATN_M ─ Ag105 pins 14/15 module-side stubs (at most 30 mm)   (rev 6)
 U_EF: OVP (8) ─ GND ; MODE (12) open (latch-off) ; PGTH (16) ─ GND ; PGOOD (17) open ; B_GATE (4), DRV (5) open
       dVdT (10) ─ C_DV 10 nF C0G ─ GND ; ILIM (11) ─ R_ILIM 8.06k 0.1 % ─ GND (rev 6) ; IMON (14) ─ R_IM 10k ─ GND ; IMON wire to LB U_IM
       SHDN (13) ─ SHDN_EF ; R_SDP 22k ─ GND ; FLT (15) ─ EF_FLT_N (10k pull-up on LB) ; GND (9), PowerPAD ─ GND

 Profile networks (reference Vin- = GND):
   CSEL pad (pin 2)    ─┬─ R_CS1 62.0k ─ GND
                        └─ R_CS2 39.2k ─ Q_CS D (BSS138, S = GND)
   MPPTSEL pad (pin 12) ─ R_MP 41.7k ─ Q_MP D (BSS138, S = GND)
   PROFILE (lead from LB; LB end: pin-10 net ─ R_PGL 22k, rev 8) ─ R_PG 1k ─ Q_CS G, Q_MP G ; R_PGP 100k ─ GND
 LD:   LDIS pad (pin 20) ─ wire ─ GND (nearest GND via or the Vin- pad)
 R_KA (ruling 9; rev 4: board underside): Ag105 VBAT+ pin barrel (21.0, 46.70) ─ 1k ─ VBT bottom trace at x >= 48
 Stage 3 (hold-up C_HU): withdrawn in revision 7 (section 14.4); nothing is fitted
```

Revision 6 adds three elements on the module input node (BT3-TR-02, BT3-TR-03, DS3-2, BT3-AG-1). In revision 5 the node
decayed only through the module idle current, for which Ag105 DS p.20 row 4 gives an 18 mA maximum and no minimum, and
through the eFuse reverse path into the 34 kOhm VCHG-IN bleed; under the threshold behaviour that S0-5 requires, the
module stayed powered for 0.02-2.3 s after every cut (`calc/bt3_transient_sim.py` sections 2-3).

1. **Dump Q_MD / R_MD.** Q_MD conducts whenever EF_EN is L. R_MD 15 Ohm takes the node from 21.5 V to below 9 V in
   1.3-2.9 ms for a module input capacitance of 100-221 uF (calc6 section 3), so every commanded exit drains the module
   with the sense in the return path, and every eFuse start (window entry or VOK pulse) begins from a cold module. On a
   rising EF_EN, U_MDI turns Q_MD off within about 1 us; the eFuse output slews at no more than 5.79 V/ms (section 7.5),
   so the overlap adds at most 0.4 mA to the inrush (calc6 section 3). A dump energy is at most 51 mJ (221 uF at
   21.5 V). With a bypassed eFuse and a fed input, R_MD draws about 1.07 A from the FC bus (17.1 W); the probe of section
   9.7a ends that within about 10 ms (0.17 J), and the 100 ms probe cap bounds it at 1.71 J (R_MD pulse rating
   TODO(select)). A dump that is stuck on (Q_MD drain-source short, U_MDI output stuck HIGH, MD_G shorted to a HIGH
   conductor) loads a fed node with the same 1.07-1.19 A while the eFuse is on. At the eFuse start the inrush into the
   module node adds to it: the start current reaches 1.50-2.48 A at the end of the ramp, above the 1.51 A U_IM minimum
   for up to 2.5 ms and above the I_OL minimum at C_mod 221 uF (`calc/bt5_transient_sim.py` section 4), so U_IM or the
   eFuse start into overload clears FF1 on most corners (`ERR_CHG_TRIP`). The steady 1.07-1.19 A alone lies below the
   U_IM minimum and, in a session with pin 32 LOW, below `OC_FC`. Firmware detects the remaining corners in sessions with
   pin 32 LOW only (the dump check of section 9.7b, the configuration check and commissioning), where the module output
   path is R_KA alone, so the module input is at most about 9 mA whatever its start speed. It compares the 4-iteration
   mean of FC_CURRENT (pin 40) before the EF_EN rise with the 4-iteration mean that starts 10 ms after
   `chargerHasPower()` first turns true, and latches `ERR_MOD_DUMP_ON` on a step above 0.4 A (healthy at most 0.232 A
   including a 0.2 A BT handoff, stuck at least 1.09 A; calc8 section 2). Revision 7 also sampled every FC window; with
   pin 32 HIGH a module that starts inside the Stage-2 allowance of Table 8a already draws 0.45-0.97 A at the sample, so
   the check false-latched on a healthy board (BT5-LS-02). A dump-check pass in the power cycle is a precondition of
   every window. In an FC window a dump that sticks later adds to the module input: the FC bus then carries at least
   1.68 A against `OC_FC` 1.4 A (BENCH_TEST 0) and the eFuse input 1.53-2.16 A against U_IM 1.51-1.98 A; with the module
   Fully Charged it is below both, and R_MD carries 17-20 W until the Fully-Charged exit (calc8 section 2). R_MD takes
   about 0.5-0.6 J before the latch (calc7 section 4). R_MDS 1 kOhm limits a short of MD_G to GND to 3.3 mA at the U_MDI output.
   A short of MD_G to SHDN_EF holds both at 1.55-1.68 V in both EF_EN states (the two LVC outputs always drive
   opposite levels through R_MDS and R_SD), where the TPS26631 state is not specified (SLVSE94G section 6.5: off below
   0.8 V, on above 2.0 V) and Q_MD can run in linear mode; SHDN_EF therefore runs in its own sleeve (revision 12,
   section 5.7 item 4, row F66, calc12 section 1).
2. **Bleed R_MB.** With Q_MD open, R_MB 3.3 kOhm takes the node from 16 V to below 9 V in at most 0.42 s at 221 uF and
   from 21.47 V to 11 V in at most 0.49 s, inside the 1.0 s `ERR_VCHG_FED` blanking (calc6 section 3). It draws 6.5 mA
   (0.14 W) at 21.5 V.
3. **Sense U_MS.** R_MS1 / R_MS2 (100 k / 16.2 k, 0.1 %) against the TLV3011B 1.242 V reference give a threshold of
   8.69-9.15 V (calc6 section 4), below the Ag105 11 V lockout (Ag105 DS p.19). MOD_COLD_N on pin 8 is LOW below the
   threshold. The TLV3011B CMRR term (54 dB minimum at the 1.242 V input level, SBOS300C section 6.9) adds 2.5 mV at
   IN+, 18 mV at the node, so the full window is 8.67-9.17 V (calc7 section 7). At the dump slope near 9 V (2.7-6 V/ms, calc6
   section 3) this moves the drain times by at most 7 us; gates S0-11 and C-2a item 24 use the wider window. An open divider top or an open sense wire reads LOW permanently, which the positive control
   of every window detects (`ERR_MOD_SENSE`, section 12.6). An open R_MS2 reads HIGH whenever the node is above about
   1.3 V, which lengthens the drain wait and latches `ERR_MOD_DRAIN` at its deadline; it also puts the module node
   through R_MS1 on U_MS IN+ (13.5-21.5 V against the 7 V absolute maximum, SBOS300C section 6.2, at most 0.215 mA), so
   it is an overstress of the comparator, not a fail-safe event (row F56). Pin 8 also
   has the Teensy internal pull-up (section 12.3), so an open pin-8 tap reads HIGH; in the bonded mode with V_chg below
   9 V that is a sense fault (`ERR_MOD_SENSE`, windows refused), and with V_chg at or above 9 V it is a fed module
   while bonded (`ERR_MOD_FED`, State 99). An unpowered U_MS (LB 3V3 lost with the Teensy alive) has a high-impedance
   output (SBOS300C section 9.4.5: the open-drain output is Hi-Z during the 1.9 ms power-on reset and below the minimum
   supply), so pin 8 reads HIGH on the Teensy pull-up; both ladders decode code 0 and `ERR_CHG_LADDER` latches (row
   F51). The MS lead runs apart from the SHDN_EF lead (section 5.7 item 4): a short between them makes pin 8 follow
   EF_EN, which the exit hold check of section 9.5 detects (row F55). R_MS3 22 kOhm (revision 8) sits between
   the lead node and U_MS IN+, with R_MS2 and C_MS on the lead side; the threshold and timing are unchanged (TLV3011B
   bias in the pA range; added delay about 0.1 us; calc8 section 5). A chafe of the MS lead onto a positive conductor
   cannot raise the 3V3 rail, because the TLV3011B input has no clamp to V+ (SBOS300C section 6.2 note 2, section
   9.4.4). The input then follows the chafe voltage (8.5-21.5 V against the 7 V absolute maximum), and R_MS3 limits only
   the current into an input that has failed short (at most 0.83 mA, calc12 section 9). The MS lead relies on its sleeve
   (revision 12, BT8-DS-01, row F54b).

F_VX (4 A fast-acting) sits in VBATN_X at the module end (rule C1, row F48). It carries every legitimate current: at most
1.75 A on the regen profile, 2.5 A at the F38 ceiling, and the U_C1 and U_C2 trip currents (at most 3.50 A and 3.64 A)
for the fraction of a millisecond before a trip acts; with a 75 % derating it carries 3.0 A continuously (calc6
section 2). Its rating does not exceed the Ag105 I_DIS of 4 A (DS p.20 row 6). Its specification also states a DC
voltage rating of at least 32 V, an interrupting rating of at least 300 A DC at that voltage (the prospective chafe
current at R_int 0 is 252 A with 10 mOhm of fuse resistance and 297 A with 5 mOhm, calc7 section 8), a cold resistance of
at most 30 mOhm (the upper bound used in section 12.6 items 1-2) and a recorded melting I2t. Candidate: Littelfuse
Nano2 451/453 series, 4 A, amp code 004: 16.0 mOhm cold, melting I2t 2.469 A2s (calculated at 8 ms), interrupting
rating 400 A at 32 VDC from the 2-5 A rows (Littelfuse 451/453 datasheet rev GD, 08/23/21, electrical specifications by
item, as read in battle-test round 5, BT5-DS-03; re-read at order). Revision 7 quoted 3.152 A2s, the amp code 005 (5 A)
value. Its I2t against the Ag105 sense rating is TODO(verify: Silvertel); the reverse pulses of gate C-2a item 20 reach at
most 5.4 % of the melting I2t (calc8 section 7).

The eFuse output is the only supply of the Ag105. B_GATE and DRV are left open, which SLVSE94G Table 5-1 permits when
no blocking FET is used; the eFuse then does not block reverse current from OUT to IN. The Ag105 is not expected to
source current into its own input, but this is UNCONFIRMED.

With R_UV2 10.5 kOhm the eFuse turns on at 12.38-12.88 V and off at 11.47-12.10 V (calc4 section 9). The eFuse therefore
removes power before the module reaches its own 11 V lockout band (Ag105 DS p.19), and stays below the 13.5 V FC-window
bus floor. No Ag105 input capacitor beyond the module's own is fitted. If the S0-11 measurement or a lead-length rule
calls for an added capacitor (Ag105 DS p.6 advises 470 uF for long input leads), C_DV is re-derived first, so that the
inrush stays at or below 0.6 A (a C_in of 220 uF at C_DV 10 nF draws 1.28 A, which with the 0.15 A aux exceeds OC_FC
1.4 A). The same rule applies to the module's own capacitance (revision 12, BT8-TR-01): at C_DV 10 nF and the 5.79 V/ms
maximum slew the 0.6 A limit holds for C_mod at or below 103.6 uF. A larger measured C_mod (S0-11) needs C_DV of at
least 10 nF x C_mod / 103.6 uF (21.3 nF at 221 uF, a ramp of up to 8.2 ms plus the UVLO delay, whose C_DV scaling is
TODO(verify: SLVSE94G)); the `ERR_MOD_DUMP_ON` sample then moves to the measured ramp plus 2 ms when that is later than
10 ms, and the Stage-2 regen-pulse budget (calc4 section 11) is re-derived before Stage 2 (calc12 section 3).

### 5.4 Ag105 configuration (one-time commissioning)

Table 5 gives the register settings. The writes are made once, in a State-98 commissioning session with pin 32 LOW (no
charge path to the pack) and the module powered from a bench supply on J-FC (section 9.2), and are read back in every FC
window and every configuration check (section 9.7a). Reg 0x01 is also read back once in every regen window while the
module is powered (section 12.5 item 2), because a one-bit corruption of 0x08 gives a 3S code (0x09, 0x0A, 0x0C;
`calc/bt3_ag105_bench_lens.py` section 4).

Table 5. Ag105 register settings (Table 7 JSON; Table 3 and Table 4 JSON).

| Register | Value | Meaning | Behaviour after an EPROM reset (reg 0xE6) |
|---|---|---|---|
| 0x00 Charge current | 0x00 | Resistor mode: RCS network (1750 mA regen profile, 1250 mA FC profile) | 0x00: the same |
| 0x01 Battery voltage | 0x08 | 2S, 8.4 V | 0x00 with VSEL open: 4.2 V default (undercharge, safe) |
| 0x02 MPPT voltage | 0xFF | Resistor mode: MPPTS open = 18 V default, MPPTS 41.7 kOhm = 13.82 V (approximate law) | 0xFF: the same |
| 0x03, 0x04 | 0x00 | No timeout, no recovery | 0x00 |

The vehicle module's as-found state is reg 0x00 = 0x01 (2.5 A, register mode), reg 0x01 = 0x08 and reg 0x02 = 21
(12.85 V) (facts_prior section 4.2). Until the commissioning writes are made, the module charges at 2.5 A in register
mode, which gives an output of 2.8 A with the board load (above the 2.5 A rating). The commissioning procedure therefore
removes the charge path before it powers the module.

The fw v24 dynamic reg 0x02 policy and the `pollAg105()` configuration writes (ino:16196-16198) are disabled under IC1.
The commissioning writes are the only EPROM writes: at most three per module, plus three after any EPROM reset.

### 5.5 Motherboard modifications

Table 6 lists every motherboard modification in build order. Each is a never-rotated hardware bodge record (operator
action OR-G). Coordinates are BRD board coordinates in millimetres. The Ag105 body covers board x 18.9-47.5 mm and
y 34.5-67.6 mm (Ag105 DS V1.1 Fig. 11 p.21, body 28.6 x 33.1 mm, placed by element CHG at (47.498, 34.544) R180); no
modification other than M1, M2, M9 and M10 is made inside that outline.

Table 6. Motherboard modifications.

| ID | Stage | Modification | Reversal | Primary |
|---|---|---|---|---|
| M1 | 1 | Cut Ag105 pins 14 and 15 flush with the top of the board-side barrel. Remove the board-side remnant flush or drill it out. Leave at least 1 mm of air gap between the module-side stub and the barrel, with Kapton tape on the pad and an epoxy barrier. Solder one 0.5 mm2 flying lead (VBATN_X) to both module-side stubs and sleeve the joint with heat-shrink. Fallback if the standoff fails gate D-2: the module carrier of revision 2 section 7.1 step 3. | Replace the module, or splice the stubs (not equivalent to the original joint) | facts_board 4.1, 4.3 |
| M2 | 1 | Cut Ag105 pin 10 the same way (gap, barrier, sleeve). Board-side barrel (VCHG-IN) to U_EF IN; module-side stub to U_EF OUT. Both leads 0.5 mm2 or more. | As M1 | facts_board 4.1, 4.4 |
| M3 | 1 | D-BT-SQ enable cut on the **bottom-layer** run between the vias at (45.466, 36.068) and (60.96, 36.068), at x >= 49.2 (outside the Ag105 body; reached from the underside). Bridge with R_S32 4.7 kOhm; lead from EN_SQ_X to Q_X2. Gate B2 confirms that the 10 kOhm bodge pull-down stays on the EN-pad side of the cut. | Remove R_S32's leads; bridge the cut with a solder wire | BRD signal D-BT-SQ (EN pad 5, top trace, via (37.084, 40.894), bottom run, via (60.96, 36.068), J1 47/48) |
| M4 | 1 | D-BT-EN enable cut on the top segment (66.294, 24.384)-(66.294, 29.718). Bridge with R_S28; lead from EN_BE_X to Q_X1. | Bridge the cut | Rev 2 section 2.3; BRD signal D-BT-EN |
| M5 | 2 (deferred from Stage 1 in revision 5) | D-BC-RG enable cut. Candidates: top segment (81.063, 3.302)-(80.010, 3.302) next to pad 5, or top segment (80.772, 25.400)-(80.772, 35.560). The choice follows the bodge pull-down position (gate B2). Bridge with R_S30; lead from EN_RG_X to Q_RG1, Q_RG2, Q_RB1, Q_RB2. In Stage 1 the cut is not made: D-BC-RG stays on its pin-30 net with the 10 kOhm bodge pull-down, firmware holds pin 30 LOW (`IC1_STAGE` 1), the eFuse regen source term RGQ is LOW (VOK held LOW by R_VKP), and a fed VCHG-IN with pin 30 LOW latches `ERR_VCHG_FED`. | Bridge the cut | BRD signal D-BC-RG |
| M6 | 1 | Taps soldered to the receptacle contacts: J1 39/40 (pin 28 net), J1 41/42 (pin 29), J1 43/44 (pin 30), J1 45/46 (pin 31), J2 31/32 (BT-CURR, pin 41), J2 37/38 (CHG-V, pin 38, scope point); the spare pins 10, 16, 17, 20, 21, 22, 23, 33, 34, 35 at their J1/J2 contacts; pin 8 at J1 19/20 (MOD_COLD_N, input only, after gate P8); 3V3 at J2 05/06; 5V at J2 01/02; GND at J2 03/04. Pin-to-pin continuity check of adjacent taps (J2 43-48: pins 35, 34, 33) at C-1. | Unsolder | SCH nets; facts_board 7.2 |
| M7 | 2 | VOK taps, one pad and one wire per tap: channel 1 V-MOT at J-M pin 1 (element at 119.126, 5.842), channel 1 VBUS at the R1-BUS pin-2 pad (element at 79.502, 46.736); channel 2 V-MOT at CAL pad 1 (element at 105.156, 15.24), channel 2 VBUS at a VBUS via or exposed VBUS copper not shared with channel 1 (TODO(verify: BRD net VBUS via list)); no tap on the C-D2 MLCC (0805, CAPC2012X110, a flex-crack risk under a soldered lead). R_Mk1a and R_Bk1a mount at the tap ends on an adhesive-staked tab; each tap carries a stranded lead with a strain-relief loop (section 5.7). | Unsolder | SCH nets V-MOT (J-M 1, CAL 1) and VBUS; BRD element placements |
| M8 | 1 | BQ29200 OUT (pin 8, net BAL-NOK, no copper) fly-wire to R_OVG on LB. **Mandatory.** Stake the fly-wire with adhesive within 2-3 mm of pin 8 and route it with a strain-relief loop. If the pin cannot be reached or its drive level fails gate BG-17, charging is not enabled. An open fly-wire holds N1 LOW through R_OVP (pull-up), which refuses every window. | Unsolder | facts_board 5 item 3; SLUSA52C section 7.5 |
| M9 | 1 | LDIS pad (21.0, 41.62) wired to GND (G5). | Unsolder | facts_board 4.1 |
| M10 | 1 | CSEL pad (46.0, 41.62) and MPPTSEL pad (21.0, 61.94) wired to the CB networks; GND reference at the VIN- pad (46.0, 46.70) or the nearest GND via. VSEL (46.0, 39.08) stays open. | Unsolder | facts_board 4.1 |
| M11 | 1 | Subject to ruling 9: R_KA 1 kOhm, fitted on the **board underside** between the Ag105 VBAT+1 pin barrel annulus (21.0, 46.70; net VCHG) and the bottom-layer VBT trace from (46.99, 34.544) to (57.658, 34.544) at x >= 48. Insulated leads; continuity check for a bridge to an adjacent node (row F18). | Unsolder | BRD; facts_board 4.1 |
| M12 | 1 | J-BL position 3 (11.43, 30.48): remove the balance-lead negative wire from the harness plug and insulate it; remove the clamp screw and fill the wire entry with epoxy (G8). | Replace the J-BL terminal block (pad solid to both pours: lifted-pad risk) | facts_board 2.1, 2.2 |
| M13 | 1 | Lead B (G9): solder a 2.5 mm2 lead from SGND to the underside of the J-BT pin-2 barrel (11.68, 11.94). The pad is solid to both GND pours (288 stitching vias, no thermal relief). Preheat the J-BT barrel area from the underside with the heater confined to board x < 15 mm (TODO(calibrate)); keep the Ag105 case at or below 90 C, measured with a thermocouple on the module case corner nearest J-BL (Ag105 DS V1.1 p.19: storage maximum 100 C); make up the remaining heat with an iron of 80 W or more and a large tip. Make M13 before D-3 (section 15.2). Acceptance by 4-wire measurement at C-2. | Unsolder | facts_board 1 item 4, 2.1; Ag105 DS p.19 |
| M14 | 1 | Fit F_PK in the pack-positive lead at the pack terminal, on the pack side of a keyed, polarized pack connector at the SB input (BOM line 51 lists an MPD BF302 25 A inline holder whose harness position is not recorded: survey the harness and use it for F_PK if it is already at the pack terminal and its fuse type matches, TODO(verify: BF302 datasheet)). Route pack positive from the connector through SB (two tap points, F_T1 and F_T2) to J-BT pin 1; route pack negative to R_SH. Colour-code and label the two J-BT leads. Total added series resistance in the pack loop below 12.9 mOhm (revision 2 section 4.1). | Remove SB and refit the original harness | Rev 2 section 7.1 step 9 |
| M15 | 1 | BAL_OK tap: R_BL1 150 kOhm soldered at the underside of the J-BL pin-1 barrel (11.43, 45.72; net VBAL+), lead to LB. | Unsolder | facts_board 2.1, 2.3 |
| M16 (R7) | 1 | Balance-network rework at the BQ29200 (24.38, 29.46); pad centres from the BRD (`calc/bt4_m16_geometry.py`). (a) Replace RB1A (0402 at (20.828, 27.94), R90; RB1A.1 VMID at (20.828, 27.433), RB1A.2 VC1_CB at (20.828, 28.448)) by 4.7 kOhm 1 % 0402. (b) Remove CBL2 (100 nF 0603) and fit a new 100 nF 0603 on the same pads; then fit D_VC1 on the CBL2 land with its terminals soldered to the exposed pad copper beside the new CBL2 terminations, not to the terminations (cathode on CBL2.1 (19.317, 30.226; net VC1), anode on CBL2.2 (17.767, 30.226; GND); pad pitch 1.549 mm); inspect the new CBL2 under magnification after the joint cools (revision 8, BT5-BO-06: a cracked CBL2 shorts VC1 to GND, an F47 cause). (c) Fit R_VC1a 200 kOhm with one end on the RB3 VC1 pad RB3.2 (19.304, 28.448) and the VC1-tap flying lead on the other end, staked within 3 mm; mask the GND via at (20.066, 29.21), 1.08 mm from RB3.2, with Kapton during the joint. Gate C-1 reads VC1 to GND by resistance (row F47). The revision-6 D_VCB is not fitted. Both GND pours are solid with no thermal relief, and the group's highest pad (CBL1, y 32.22) is at most 2.3 mm from the Ag105 body edge (y 34.5) and 0.62 mm from its footprint silkscreen (y 32.84). Method: preheat from the underside, confined to board x < 30 mm and y < 32 mm; solder with a fine iron; shield the Ag105 edge with Kapton tape and a copper shim; keep the thermocouple on the Ag105 case at or below 90 C. Before the balance plug is first connected, gate C-1 checks D_VC1 in diode mode and RB1A by resistance. | Unsolder; refit RB1A 100 Ohm (as built) | facts_board 2.3, 5; SLUSA52C 7.1, 7.3, 7.6; BRD; calc7 sections 1-2 |

### 5.6 Component table

Table 7 lists every component. Ratings marked TODO(verify) were not read for this revision. Passives are 1 % thick film
0603 unless stated, 0.1 % thin film where stated, and X7R 0603 capacitors unless stated.

Table 7. Components.

| Ref | Assy | Part number | Value | Rating used | Primary citation |
|---|---|---|---|---|---|
| S_GND1, S_GND2, S_CHG | SB | TI CSD18510Q5B | - | 40 V V_DS; +/-20 V V_GS; 1.6 mOhm max at V_GS 4.5 V; V_GS(th) 1.2-2.3 V; C_iss 8.77-11.4 nF; body diode 1.0 V max at 32 A | SLPS632 p.1, section 5.1 |
| R_SH | SB | 4-terminal 2512 metal strip (candidate Vishay WSK2512) | 0.5 mOhm | 0.15 W at 17.1 A; 1 % tolerance assumed | TODO(verify: vendor datasheet) |
| R_K1, R_K2 | SB | Fusible flame-proof metal film, 0.25 W | 2.2 Ohm, 1 % (matched pair) | Opens on a pack+ short (3.85 A, 32.5 W); fusing curve TODO(verify: vendor datasheet) | Calc4 section 1 |
| F_PK | harness, pack-positive lead at the pack terminal (pack side of the connector) | ATO blade fuse, slow-blow, inline holder (or the BOM-line-51 BF302 holder if surveyed in place, TODO(verify: BF302 datasheet)) | 20 A | Above the 17.1 A boost switch limit; I2t against the 2.5 mm2 leads and the S_GND pair SOA TODO(verify: fuse datasheet, SLPS632) | SLVSFP3C section 7.5 |
| F_T1, F_T2 | SB | SMD fuse | 0.5 A | One per gate tap | TODO(verify: fuse datasheet) |
| C_VT1a, C_VT1b, C_VT2a, C_VT2b | SB | X7R 0805 | 2.2 uF, 25 V | Series pair per channel (1.1 uF); one cracked part leaves 2.2 uF, not a short | Calc4 section 12 |
| R_GU1, R_GU2 | SB | 0603 | 10 kOhm | 0.85 mA at 8.5 V | - |
| Z1, Z2, Z3 | SB | BZT52C15 | 15 V | V_GS clamp below the 20 V maximum | `references/Datasheets/BZT52C_Diodes.pdf`; tolerance TODO(verify) |
| Q_A1, Q_A2, Q_C, Q_D, Q_R1, Q_R2 | SB | onsemi BSS138 | - | 50 V; +/-20 V V_GS; V_GS(th) 0.8/1.3/1.5 V; 6 Ohm max at 4.5 V | onsemi BSS138/D Rev 7 p.1-2 |
| Q_B | SB | onsemi BSS84 | - | P-channel, -50 V | TODO(verify: onsemi BSS84 datasheet) |
| R_GA1, R_GA2 | SB | 0603 | 4.7 kOhm | U_C1 contention 0.7 mA | - |
| R_PA1, R_PA2, R_PC, R_BU, R_PDD | SB | 0603 | 100 kOhm | - | - |
| D_A1, D_A2, D_D1, D_D2 | SB | onsemi BAT54 | - | 30 V; VF 0.32 V max at 1 mA | BAT54LT1/D Rev 18 p.1-2 |
| R_D1, R_D2, R_PD3, R_SR1, R_SR2, R_SP1, R_SP2 | SB | 0603 | 47 kOhm | - | - |
| R_BC | SB | 0603 | 33 kOhm | - | - |
| R_CQ, R_VPS | SB | 0603 | 10 kOhm | R_VPS is in the V_PACKN divider lower leg | - |
| C_CQ | SB | X7R 0603 | 10 nF | S_CHG delay, tau 100 us | - |
| R_B3 | SB | 0603 | 1 kOhm | - | - |
| U_FF | LB | TI SN74LVC1G74 | - | PRE and CLR active-low; V_IH 2.0 V min, V_IL 0.8 V max at VCC 3.0-3.6 V; input transition rate 10 ns/V max at 3.3 V | SCES794G section 6.3 (literature number confirmed from the TI PDF header) |
| U_PD | LB | TI SN74AHCT1G125 | - | 5 V supply, TTL inputs; recommended IOH magnitude 8 mA at 4.5 V, exceeded by about 10 mA on the first edge into a discharged pump (accepted transient overdrive; V_H is not specified for it) | SCLS378P Recommended Operating Conditions; `calc/bt2_datasheet_reverify_calcs.py` section 4 |
| U_PS, U_BF, U_P33, U_CKS, U_CLS | LB | TI SN74LVC1G17 | - | VT+ 1.48-1.92 V and VT- 0.89-1.20 V at 3.0 V; I_I +/-5 uA; Ioff | SCES351Y Table 5-1, section 5.5; values at 3.3 V TODO(verify) |
| U_SG1, U_SG2 | LB | TI SN74LVC1G14 | - | Schmitt inverter, Ioff | TODO(verify: TI datasheet) |
| U_CH1, U_CH2 | LB | TI SN74LVC1G02 | - | Two-input NOR | TODO(verify: TI datasheet) |
| U_VA, U_RS | LB | TI SN74LVC1G08 | - | Two-input AND (U_VA Stage 2 only) | TODO(verify: TI datasheet) |
| U_N33, U_NP | LB | TI SN74LVC1G07 | - | Open-drain buffer: output LOW when the input is LOW; Ioff | TODO(verify: TI datasheet) |
| U_OR | LB | TI SN74LVC1G32 | - | - | TODO(verify: TI datasheet) |
| U_AND | LB | TI SN74LVC1G11 | - | Three-input AND | TODO(verify: TI datasheet) |
| U_LA, U_LB | LB | TI SN74LVC244A | - | Octal buffer, five bits used; about 0.55 mA per bit | TODO(verify: TI datasheet) |
| U_SH1, U_SH2 | LB | TI INA240A3 in any stocked package (INA240A3D SOIC-8 preferred; INA240A3PWR had no stock on 2026-11-07) | 100 V/V | V_CM -4 to 80 V; V_OS 25 uV max; gain error 0.20 % max; reference divider 0.1 % max; swing VS - 0.2 V and GND + 10 mV; I_B 90 uA typ; series-resistor gain error 3000/(R_S + 3000): 0.073 % per amplifier at 2.2 Ohm; I_B mismatch TODO(verify: SBOS662C) | SBOS662C sections 7.3, 7.5, 9.1.1 Eq. 2 |
| U_C1, U_C2, U_D5, U_IM, U_MS | LB | TI TLV3011BIDBVR | - | 1.65-5.5 V; open-drain; V_OS +/-6 mV (25 C), +/-9 mV (-40 to 125 C) at VCM = V-; CMRR 54 dB min; hysteresis 2-8 mV; REF 1.223-1.260 V; t_ON 1.9 ms. The 4 us t_PD at 100 mV overdrive is the push-pull TLV3011 figure; the open-drain delay is not specified (only t_FALL), TODO(verify: SBOS300C), measured at T1 and V2-2 | SBOS300C sections 6.6, 6.9, 6.10 |
| U_V1, U_V2, U_BP1, U_BP2 | LB | TI TLV3011BIDBVR | - | As above at 3V3; inputs (V-) - 0.2 to (V+) + 0.2 V operating, 7 V absolute; V_OL at 0.3 mA TODO(verify) | SBOS300C sections 6.2, 6.6 |
| Q_I1a, Q_I1b, Q_I2a, Q_I2b, Q_INV, Q_D5, Q_OV, Q_H1, Q_H2, Q_RG1, Q_RG2, Q_RB1, Q_RB2, Q_X1, Q_X2 | LB | onsemi BSS138 | - | As SB | BSS138/D Rev 7 |
| D_NC1, D_NC2, D_NIM, D_D5S, D_P1, D_P2, D_X1, D_X2, D_X3, D_SG1, D_SG2, D_D5, D_I3 | LB | onsemi BAT54 | - | As SB; I_R 2 uA max at 25 V, 25 C (hot value TODO(verify)) | BAT54LT1/D Rev 18 |
| C_P1 | LB | C0G 1206 | 1 uF, 25 V | Pump coupling | TODO(verify: capacitor datasheet) |
| C_P2 | LB | X7R 0805 | 1 uF | Hold capacitor | - |
| R_P1 | LB | 0603 | 470 Ohm | - | - |
| R_P2 | LB | 0603 | 47 kOhm | Hold discharge | - |
| R_N1, R_P33, R_P34, R_P35, R_P10, R_UC1, R_UC2, R_UD5, R_UIM, R_IMF, R_SG1, R_SG2, R_UP1, R_UP2, R_BP1, R_BP2, R_FLT, R_X1, R_X2, R_X3, R_CK | LB | 0603 | 10 kOhm | R_UPk and R_BPk to 3V3; R_CK 1 % | - |
| R_SD, R_FQ, R_RQ, R_A16, R_A17, R_OVG | LB | 0603 | 1 kOhm | - | - |
| R_I1, R_I2 | LB | 0.1 % 0603 | 8.2 kOhm | Injection about 5.1 A equivalent | Calc4 section 5 |
| R_I3 | LB | 0603 | 100 kOhm | D5 injection | Calc4 section 5 |
| C_CK | LB | C0G 0603, 5 % | 1 nF | Clock RC 9.4-10.6 us | - |
| R_FQP, R_RQP, R_INV, R_D5d, R_VKP, R_CHP1, R_CHP2 | LB | 0603 | 100 kOhm | R_VKP, R_CHP1, R_CHP2 fitted in Stage 1 only | - |
| R_IMa, R_IMb | LB | 0.1 % 0603 | 59.0 k / 10.0 k (R_IMa trimmed per unit at S0-12b) | U_IM threshold 0.478 V (1.51-1.98 A eFuse input over the IMON gain range and 3V3 3.2-3.4 V) | Calc6 section 5 |
| C_IMF | LB | C0G 0603 | 10 nF | IMON filter tau 0.1 ms | - |
| R_X | LB | 0603 | 47 kOhm | Cross-lock release, tau 4.7 ms | Rev 2 section 2.3 |
| C_X | LB | X7R 0603 | 100 nF | - | Rev 2 section 2.3 |
| R_OVP | LB | 0603 | 1 MOhm | Q_OV gate pull-up to 3V3 (open-wire fail-safe, revision 5) | SLUSA52C section 7.5 (OUT low sink 30 uA min at 0.05 V) |
| R_F1, R_F2 | LB | 0.1 % 0603 | 1.5 kOhm | - | - |
| C_F1, C_F2 | LB | C0G 0805 | 47 nF | Filter tau 70 us | - |
| R_T1a, R_T1b | LB | 0.1 % 0603 | 12.0 k / 10.0 k | U_C1 threshold 1.500 V | - |
| R_T2a, R_T2b | LB | 0.1 % 0603 | 12.1 k / 10.0 k | U_C2 threshold 1.493 V (reversed channel) | Calc4 section 2 |
| R_D5a, C_D5a | LB | 0603 | 10 kOhm, 100 nF | D5 filter 1 ms | - |
| R_D5b, R_D5c | LB | 0.1 % 0603 | 64.9 k / 1.00 k | D5 reference 50.1 mV | - |
| C_D5d | LB | X7R 0603 | 100 nF | D5 arming 2.8-6.1 ms | Calc4 section 10 |
| R_M11a, R_M11b, R_M21a, R_M21b, R_B11a, R_B11b, R_B21a, R_B21b | LB | 0.1 % 0805 thin film | 49.9 kOhm | - | - |
| R_M12, R_M22 | LB | 0.1 % 0603 | 13.6 kOhm | - | Calc section 2 |
| R_M13, R_M23 | LB | 0.1 % 0603 | 715 Ohm | - | Calc section 2 |
| R_B12, R_B22 | LB | 0.1 % 0603 | 14.9 kOhm | - | Calc section 2 |
| R_O1, R_O2 | LB | 0.1 % 0603 | 301 kOhm | Offset from REF | Calc section 2 |
| C_M1, C_M2, C_B1, C_B2 | LB | C0G 0603 | 1 nF | Tap filter about 12.5 us | Calc section 9 |
| R_S28, R_S30, R_S32 | board | 0603 across each cut | 4.7 kOhm | - | Rev 2 section 2.3 |
| Ladder resistors | LB | 0.1 % 0603 | 8 x 2.00 kOhm, 12 x 4.02 kOhm | Two R-2R ladders | Calc4 section 4 |
| C_LA, C_LB | LB | C0G 0603 | 10 nF | Ladder tau 20 us | Calc4 section 4 |
| R_BL1, R_BL3, R_BL2 | R_BL1 at the J-BL tap; R_BL3 at the LB entry; R_BL2 at the U_LA input | 0603 | 150 k / 47 k / 100 kOhm, R_BL2 1 % and fixed (revision 8; R_BL2 was 82 kOhm and R_BL3 did not exist; revision 12, BT8-TR-03: the revision-8 range '82 to 100 kOhm' is withdrawn, because 82 kOhm moves the BAL_OK threshold to VBAL+ 7.79-7.90 V, above the 7.4 V entry floor) | BAL_OK reaches VIH at VBAL+ 7.0 V at the worst 1 % corner with 5 uA of input leakage, 0.4 V below the 7.4 V entry floor (calc12 section 5); BAL_OK 2.49 V at 7.4 V and 2.86 V at 8.5 V against the LVC VIH of 2.0 V (TODO(verify: TI SN74LVC244A)); 29 uA drain; a lead chafe up to 9.5 V holds the U_LA input at or below its 6.5 V absolute maximum; above that the lead relies on segregation (section 5.7 item 4) | Calc8 section 5 |
| C_V | LB | X7R 0603 | 10 nF | - | - |
| R_V1, R_V2 | LB | 0.1 % 0603 | 100 kOhm | V_PACKN divider (with R_VPS) | Calc4 section 7 |
| Decoupling (24) | LB | X7R 0603 | 100 nF | One per IC | - |
| U_EF | CB | TI TPS26631PWPR (approved alternate TPS26636PWPR, section 16; the alternate is a 1 x I_OL limiter with an OV clamp in place of the OVP cutoff and an unstated fast trip, section 7.5) | - | 4.5-60 V; R_ON 30.44 mOhm typ, 45 mOhm max at 85 C; I_OL 1.84/2.00/2.16 A at R_ILIM 9 kOhm; fast trip 3 x I_OL (active); latch-off with MODE open; thermal regulation at start-up up to t(Treg_timeout) 2.3-2.9 s, FLT only after the timeout; tCB_FLT(dly) 22-30 ms; tSD(dly) 0.8-1.5 us; V_SHUTF 0.8 V min; V_SHUTR 2 V max; UVLO pin 1.176-1.224 V rising, 1.09-1.15 V falling; GAIN_dVdT 23.5-26; I_dVdT 1.775-2.225 uA; GAIN(IMON) 25.66 / 27.9 / 30.14 uA/A (0.6-2 A) | SLVSE94G sections 4, 5 (Table 5-1), 6.3, 6.5, 6.6, 8.3.1.1, 8.3.7.2.1, Table 8-1 |
| R_ILIM | CB | 0.1 % 0603 | 8.06 kOhm (revision 6) | I_OL 2.06-2.41 A (I(OL) 1.84-2.16 A at 9 k, scaled 9/8.06); fast trip 6.2-7.2 A | SLVSE94G section 6.5; calc6 section 5 |
| R_UV1, R_UV2 | CB | 0.1 % 0603 | 100 k / 10.5 k | UVLO 12.38-12.88 V rising, 11.47-12.10 V falling | Calc4 section 9 |
| C_DV | CB | C0G 0603 | 10 nF | Slew 4.17-5.79 V/ms; inrush at or below 0.6 A for C_mod at or below 103.6 uF; for a larger measured C_mod (S0-11), C_DV at least 10 nF x C_mod / 103.6 uF (revision 12, calc12 section 3); re-derive if an input capacitor is added | SLVSE94G sections 6.3, 6.5 |
| R_IM | CB | 0.1 % 0603 | 10 kOhm | IMON 0.279 V/A into U_IM | SLVSE94G section 6.5 |
| D_VC1 | board (M16) | Low-leakage small-signal Schottky. First build: a provisional part under ruling OR-AC option (d) (decided 2026-11-09; candidate NSR0320MW2); final part TODO(select) after gate B8-1 | - | V_F at most 0.25 V at 16.2 mA at T_min, the minimum operating ambient (ruling OR-AC; T_min 25 C for the bench-attended Stage-1 sessions of the first build, decided 2026-11-09; the vehicle T_min for the final part is open item 31) (VC1 above the -0.3 V VC1-GND minimum in row F34b; BENCH, B-PKN at the coldest ambient); I_R at most 40 uA at 4.2 V at T_M16,max (TODO(calibrate) at B8), so the VC1 error through RB3 is at most 10.4 mV and adds to the BQ29200 V_OA and V_OA_DRIFT budget (SLUSA52C 7.5). The two limits bind at opposite ends and conflict: under the design's x2 per 10 K rule the V_F limit needs I_S(T_min) of at least 0.17-0.48 uA (n 1.0-1.1) at T_min -20 C, and the 40 uA limit then holds only up to T_M16,max of 44-59 C (63-76 C at T_min 20 C) (calc8 section 3; thermionic model `calc/fmea_round5_calcs.py` section 3, `calc/verify_dvc1_two_endpoint.py`). Revision 7 stated that the cold limit 'leaves room for the hot limit'; calc7 section 3 itself contradicts it (0.96-2.33 uA needed at 25 C against 0.62 uA allowed). Feasibility is UNCONFIRMED: the selection calculation checks a candidate's datasheet V_F(T_min) and I_R(T_M16,max) curves against both limits; if no part meets both, ruling OR-AC chooses the fallback. A short draws 16.2 mA through RB3 and puts V_pack across VC2-VC1 (row F47). Revision 12 (BT8-DS-04): the 44-76 C windows assume ideal saturation-current leakage. A real low-V_F Schottky leaks about 10 x I_S at 25 C (onsemi NSR0320MW2T1/D Rev. 8, as read in battle-test round 8: I_S about 0.96 uA from its 0.24 V typical row at 10 mA, I_R 10 uA typical at 15 V), so for a die that just meets the V_F limit the 40 uA budget holds only up to about 44 C even at T_min 25 C (calc12 section 8). The NSR0320MW2 itself fails the 0.25 V limit on its 25 C maximum row (0.27 V at 10 mA, 0.283 V at 16.2 mA), 17 mV inside the -0.3 V absolute minimum. The 0.25 V figure is the design limit; the -0.3 V VC1-GND minimum (SLUSA52C 7.1) is the requirement. No passive part that meets both endpoints has been identified; under ruling OR-AC option (d), decided 2026-11-09, a provisional part whose 25 C maximum V_F row at 16.2 mA is below 0.3 V is fitted for the first build (section 15.3, gate B8-1); after B8-1, option (a), option (c) or a confirmed passive part replaces it | SLUSA52C 7.1, 7.5; BOM line 88; calc7 sections 1, 3 |
| RB1A (replaced) | board (M16) | 0402 thick film, 1 % | 4.7 kOhm (was 100 Ohm) | RCB at the top of the SLUSA52C 7.3 range (100 Ohm-4.7 kOhm); balance current 0.5-1 mA (Table 7.6); a VC1_CB bridge to GND draws 0.89 mA (3.75 mW); the unclamped VC1_CB takes at most 0.83 mA in row F34b (VC1_CB absolute maximum not in SLUSA52C 7.1, TODO(verify: TI)) | SLUSA52C 7.3, 7.6; calc7 section 1 |
| R_VC1a, R_VC1b | board (M16) / LB entry (lead side) | 0.1 % 0603 | 200 kOhm / 200 kOhm | VC1 tap, V(pin 20) = VC1 / 2; at most 11 uA from VC1 (2.9 mV through RB3); a lead chafed to GND draws at most 22 uA from VC1 through R_VC1a (revision 7 quoted 42.5 uA, 8.5 V / 200 kOhm, which is the VC1 drain and not the pin-20 stress) | Calc7 section 2; calc8 section 5 |
| C_VC1 | LB (pin side of R_VC1c) | X7R 0603 | 100 nF | Tap filter, tau 12.2 ms with the 100 kOhm Thevenin source plus R_VC1c | Calc8 section 5 |
| R_VC1c (R8) | LB (VC1 lead entry, pin side) | 0603 | 22 kOhm | A lead chafed to 8.5-21.5 V drives 0.22-0.81 mA into pin 20; IMXRT1060CEC Table 7 rates the pad only to OVDD + 0.3 V and gives no injection current, so a pad clamp that conducts this current operates outside the rating, and the lead relies on its sleeve (revision 12, BT8-DS-02; pad survival TODO(verify: IMXRT1060CEC)); mismatch sensitivity to pin-20 current 0.488 V/uA | Calc8 sections 4-5 |
| F_VX | CB | Fast-acting fuse, SMD or inline, TODO(select); candidate Littelfuse Nano2 451/453 4 A, amp code 004: 16.0 mOhm, melting I2t 2.469 A2s at 8 ms, 400 A at 32 VDC (datasheet rev GD as read in BT5-DS-03; re-read at order) | 4 A | Carries 2.5 A continuous with 75 % derating; at most the Ag105 I_DIS 4 A; DC rating at least 32 V; interrupting rating at least 300 A DC at that voltage; cold resistance at most 30 mOhm; melting I2t recorded; I2t against the Ag105 sense TODO(verify: Silvertel) | Ag105 DS p.20 row 6; calc6 section 2; calc7 section 8 |
| Q_MD | CB | Logic-level N-MOSFET with an R_DS(on) row at V_GS 2.5 V (at most 0.5 Ohm), at least 40 V V_DS, at least 2 A pulsed, TODO(select) | - | Module-node dump, ON while EF_EN is L; survives the stuck-on case until `ERR_MOD_DUMP_ON` (1.19 A for about 30 ms) and the 12.7 Hz limit-cycle duty (section 7.2 item 5). Revision 12 (BT8-FM-01): the selection records the V_GS(th) range, the transfer characteristic near 1.55-1.68 V, a linear-mode SOA and V_GSS (at least +/-20 V); when the V_GS(th) range covers 1.55-1.68 V, row F66 records Q_MD destruction (up to 4.0-5.1 W in linear mode) under the double insulation fault as accepted. Thermal limits with an assumed SOT-23-class R_thJA of 125-350 K/W are UNCONFIRMED until the part is selected | Calc6 section 3; calc7 sections 4, 9 |
| R_MD | CB | Pulse-rated thick film 2512; candidate Vishay CRCW2512-HP 15 Ohm (doc 20043 pulse-load curves: about 20 W at 0.1 s and about 200 W at 1 ms; TODO(verify: Vishay doc 20043)) | 15 Ohm | Peak 1.43 A; 51 mJ per dump; 1.71 J single 100 ms pulse (probe cap); repetitive duty: one dump per VOK pulse, 56 dumps and at most 2.86 J per 30 s window (0.095 W mean, CC-18), and up to one dump per 79 ms in a module-driven limit cycle, 0.65 W mean for 30 s (BT4-TR-03, calc7 section 9); stuck-on dump about 0.5-0.6 J before `ERR_MOD_DUMP_ON` (calc7 section 4) and, if the fault arises during a drive, the first regen pulse on most corners (U_IM or I_OL at the eFuse start) or 0.46-1.45 J per pulse on the residual corner (row F50). Rating basis (revision 8, BT5-DS-04): the doc 20043 single-pulse curve applies to fewer than 1000 pulses in life (its caption 'n < 1000'), so it rates only the 1.71 J probe-cap and stuck-on events; the per-VOK-pulse dump (more than 1000 within a few drives) is rated on the doc 20043 continuous-pulse curve at t_i 3-10 ms and the measured cadence (both curve points TODO(verify: Vishay doc 20043, revision 17-Mar-2026)). The part must fail open, not short (row F49); rating TODO(select) | Calc6 section 3; calc7 sections 4, 9 |
| R_MDS | LB | 0603 | 1 kOhm | U_MDI output series resistor: an MD_G short to GND draws 3.3 mA; the Q_MD gate sees 99 % of the drive with R_MDG; with R_SD it makes an MD_G-SHDN_EF short sit at 1.55-1.68 V in both EF_EN states (row F66; SHDN_EF in its own sleeve, revision 12) | Calc7 section 4 |
| R_MDG | CB | 0603 | 100 kOhm | Q_MD gate pull-down (dump off with the wire open) | - |
| R_MB | CB | 2010 | 3.3 kOhm, 0.5 W | 0.14 W at 21.5 V; bleed with Q_MD open | Calc6 section 3 |
| R_MS1, R_MS2 | CB (R_MS1 at the node), LB | 0.1 % 0603 | 100 k / 16.2 k | U_MS threshold 8.69-9.15 V | Calc6 section 4 |
| C_MS | LB (lead side of R_MS3) | C0G 0603 | 1 nF | U_MS input filter | - |
| R_MS3 (R8) | LB (U_MS IN+) | 0603 | 22 kOhm | Limits the current into a U_MS IN+ that has failed short to at most 0.83 mA. The input is not clamped to V+ (SBOS300C section 6.2 note 2, section 9.4.4), so a chafe puts the chafe voltage on IN+ and the MS lead relies on its sleeve (revision 12, BT8-DS-01; revision 8 cited section 6.1 and an IN+ clamp that does not exist); added delay about 0.1 us | Calc8 section 5 |
| U_MDI | LB | TI SN74LVC1G04 | - | Inverter EF_EN to MD_G; Ioff | TODO(verify: TI datasheet) |
| R_UMS | LB | 0603 | 10 kOhm | MOD_COLD_N pull-up to 3V3 | - |
| R_SDP | CB | 0603 | 22 kOhm | 0.22 V with the -10 uA SHDN current | SLVSE94G section 6.5 |
| C_EI, C_EO | CB | X7R 1206 | 1 uF, 50 V | - | SLVSE94G section 6.3 |
| R_CS1, R_CS2 | CB | 0.1 % 0603 | 62.0 k / 39.2 k | 1750 mA / 1250 mA equivalent | Table 4 JSON; calc section 3 |
| R_MP | CB | 0.1 % 0603 | 41.7 kOhm | 13.82 V by the approximate DS p.10 law; BENCH (S0-4) | Ag105 DS p.10 |
| Q_CS, Q_MP | CB | onsemi BSS138 | - | Off-state leakage effect TODO(verify: Silvertel); gate S0-4 | BSS138/D Rev 7 |
| R_PG, R_PGP | CB | 0603 | 1 kOhm / 100 kOhm | - | - |
| R_PGL (R8) | LB (PROFILE lead exit) | 0603 | 22 kOhm | Limits the current from a PROFILE-lead chafe into the pin-10 net to at most 0.81 mA. It does not protect the CB end, where the chafe reaches the Q_CS and Q_MP gates (up to 21.29 V against the BSS138 +/-20 V V_GSS) and switches the profile; the lead relies on its sleeve (revision 12, BT8-DS-02); gate RC about 4.4 us | Calc8 section 5 |
| R_KA | CB (underside) | 1206 thick film | 1 kOhm, 0.25 W | Worst back-fed dissipation 0.196 W | Rev 2 section 4.6 (ruling 9) |
| Harness | - | 2.5 mm2 power leads (pack positive, pack negative, lead A, lead B), 0.5 mm2 VBATN_X in its own sleeve (section 5.7 item 4), keyed twisted pair KS+/KS- (24 AWG minimum), keyed 7-way signal cable without a ground conductor, keyed 30 A pack connector | - | - | - |

### 5.7 Mechanical and placement

The three assemblies and the flying leads ride on a vibrating vehicle. The following rules apply.

1. **SB.** SB sits in a rigid enclosure fixed to the chassis. Every 2.5 mm2 lead has a cable clamp within 20 mm of its
   joint. The keyed pack connector is fixed to the enclosure.
2. **LB.** LB does not fit flat beside the Teensy receptacles: the only free strip right of J2 (x 112-131 mm, y 30-98 mm)
   is about 1300 mm2, and LB needs about 1470 mm2 of component courtyard before routing
   (`calc/bt2_buildability_measurement.py` section 3, `calc/verify_lb_placement.py`). LB is therefore a separate 2-layer
   board of about 60 x 50 mm (TODO(layout)), mounted as a mezzanine over the J2/RSDA strip on M2.5 standoffs, or
   chassis-mounted with a keyed ribbon to a tap header. The maximum receptacle-tap length is 150 mm and the SB signal
   cable is at most 0.5 m (TODO(calibrate)). The FF1 set race tolerates a clear-net capacitance C_N1 of up to 668 pF
   against the 130 pF working value (`calc/verify_lb_placement.py`); C-2 measures C_N1 on the as-built harness.
3. **CB.** CB is staked to the motherboard beside the Ag105.
4. **Flying leads.** Every flying lead (the M6 receptacle taps, the M7 VOK taps, the M8 fly-wire, VBATN_X, the M2 leads,
   R_KA, SHDN_EF, EF_FLT_N, IMON, PROFILE, MD_G, the MS sense lead from R_MS1 and the VC1 tap from R_VC1a) is stranded,
   staked with adhesive within 3 mm of its joint and routed with a strain-relief loop. SHDN_EF runs in a sleeve of its
   own over its whole length, apart from every other lead (revision 12, BT8-FM-01; revision 7 separated only MS from
   SHDN_EF). A short between MS and SHDN_EF makes pin 8 follow EF_EN (row F55). A short between MD_G and SHDN_EF holds
   both at 1.55-1.68 V in both EF_EN states, where the TPS26631 state is not specified and Q_MD can run in linear mode
   (row F66, calc12 section 1). Shorts of SHDN_EF to IMON, EF_FLT_N or PROFILE give loud refusals or trips
   (`calc/bt8_fmea_rev8_sleeve.py` section 3). No lead is soldered to an MLCC termination. Tap-end resistors (R_Mk1a, R_Bk1a) stay at the tap
   end, so that a chafed lead shorted to GND carries at most 0.16 mA; they are staked on a small tab. VBATN_X runs in
   its own sleeve over its whole length and is routed apart from the pack-positive lead and the SB pack-positive copper;
   on SB the S_CHG drain copper keeps creepage from pack-positive copper (TODO(layout)). Gate C-1 tests the insulation
   of VBATN_X against pack positive with the harness flexed (row F48). **LB entry elements and segregation (revision 8,
   restated in revision 12).** A flying signal lead that lands on an LB input or a Teensy pin carries a series element
   at its LB end: R_VC1c (VC1 tap), R_MS3 (MS), R_BL3 with R_BL2 100 kOhm (BAL_OK: the U_LA input stays at or below
   6.5 V up to a 9.5 V chafe), R_PGL (PROFILE), R_IMF (IMON, the existing 10 kOhm), R_Mk1b and R_Bk1b (VOK taps,
   existing). Apart from R_BL3, these elements limit the LB-side current only; they do not protect the inputs, and none
   sits in series with the CB-end pin of its own lead (revision 12, BT8-DS-01, BT8-DS-02, calc12 section 9). The
   TLV3011B inputs (U_MS IN+, U_IM IN-) have no clamp to V+ and follow a chafe voltage of 8.5-21.5 V against their 7 V
   absolute maximum (SBOS300C section 6.2 note 2, section 9.4.4). The i.MX RT1062 pad on pin 20 has no rated injection
   current (IMXRT1060CEC Table 7: OVDD + 0.3 V). The SN74LVC1G04/1G11 outputs on SHDN_EF and MD_G (behind R_SD and R_MDS,
   1 kOhm) have no positive clamp (SCES214AF section 5.1: VO at most VCC + 0.5 V; Ioff), so a chafe pulls them to the
   chafe voltage, and the revision-8 figure of "at most 18 mA into the output clamp" is withdrawn. At the CB end a
   chafe reaches the TPS26631 SHDN and IMON pins (5.5 V absolute maximum, SLVSE94G section 6.1), the Q_MD gate, and the
   Q_CS and Q_MP gates (up to 21.29 V against the BSS138 +/-20 V V_GSS) directly. The 3V3 rail does not rise: the TLV3011B inputs draw 10 pA, and an input that has failed short draws at most 0.83 mA
   (R_MS3) or 1.82 mA (R_IMF). Segregation is therefore the protection of SHDN_EF, MD_G, PROFILE, IMON, MS, EF_FLT_N and
   the VC1 tap at both lead ends. Three sleeves carry the low-voltage leads: the SHDN_EF sleeve (SHDN_EF alone, revision
   12), the CB-LB sleeve (EF_FLT_N, IMON, PROFILE, MD_G, MS) and the J-BL/M16 sleeve (VC1 tap, BAL_OK). None contains a
   conductor above 3.6 V, and all run apart from VBATN_X, the M2 leads, R_KA and the pack-positive lead. A chafe onto a
   positive conductor therefore needs two insulation failures, and so does a short between SHDN_EF and any other
   lead. Gates C-1 and C-4 test the insulation of every sleeved lead against VBT and the M2 VCHG-IN lead, and (revision
   12) every lead-to-lead pair inside the CB-LB sleeve and the SHDN_EF lead against the CB-LB bundle (rows F54b, F54c,
   F66).
5. **Inspection.** After the first driving session, gate C-4 repeats P-M1, the D-2 gap insulation, the VBATN_X
   insulation test, gate C-2b items (a), (c) and (g), and a visual check of every tap joint.
6. **Heated modifications.** No heating step may take the Ag105 case above 90 C (Ag105 DS V1.1 p.19: storage maximum
   100 C; no soldering profile is published). Every heated modification (M1, M2, M13, M16) is made before gate D-3, and
   D-3 runs after the last of them; if a heated step follows D-3, D-3(b) is repeated before commissioning step 1.

## 6. Logic and gate-drive equations

The following equations define the hardware. "H" means the logic level HIGH (3.3 V), "L" means LOW. A signal with the
suffix `_N` is active-low. Pin numbers are Teensy pins.

1. **Clear net.** N1 = P33B AND PUMP_OK AND UC1_N AND UC2_N AND UIM_N AND NOT(D5trip AND FCQ_armed) AND NOT
   (BQ_OUT OR BQ_OUT_open), where P33B = Schmitt(p33) and P33B is L when pin 33 is L or high-Z. /CLR = Schmitt(N1).
   Every term is open-drain, so a single join fault can only force N1 L.
2. **Permit latch.** FF1.Q is set by a rising edge on P33B, delayed 5.6-9.9 us by R_CK/C_CK and U_CKS, while /CLR is H.
   FF1.Q is cleared whenever /CLR is L. FF1 cannot set while any clear source is active, and stays clear after the source
   releases until a new pin-33 rising edge.
3. **Pumped arm.** PUMP_OK = Schmitt(PUMP_H). PUMP_H rises only while p34 toggles at 26 Hz or more; it falls below the
   lower Schmitt threshold 43-76 ms after the last edge (calc section 4).
4. **Regen-source gate.** OKk = (V-MOT x r_k > VBUS x b_k + V_off,k), with hysteresis by Q_Hk. BPk = (BTk > REF_k),
   true for an intact tap above VBUS 9.34-9.77 V (calc4 section 3). CHk_OK = OKk AND BPk. VOK = CH1_OK AND CH2_OK.
   Assert 16.90-17.24 V and release 16.16-16.43 V at VBUS 16.0 V (calc section 2; with a centred hysteresis the release
   can lie up to 32 mV lower, calc4 section 3).
5. **Charger power.** EF_EN = FF1.Q AND PUMP_OK AND ((VOK AND p30) OR FCQ). The eFuse conducts when EF_EN is H and its
   input is above 12.38-12.88 V (rising) and below the factory OVP (TPS26631) or OV clamp (TPS26636), until an overload
   latch-off or a U_IM clear of FF1. In Stage 1 VOK is held L, so EF_EN = FF1.Q AND PUMP_OK AND FCQ. Module node
   (revision 6): Q_MD ON = NOT EF_EN; MOD_COLD_N = L while VCHG-IN_M is below 8.69-9.15 V. Revision 7 deletes the
   p20 (WDOG1_B) term of item 1 and the Stage-3 dump.
6. **S_GND channel k.** S_GNDk ON = NOT (FF1Q_SB AND NOT UC1trip).
7. **S_CHG.** S_CHG ON = FF1Q_SB(delayed 100 us) AND NOT G1high AND NOT G2high, where Gkhigh means the S_GNDk gate is
   above the Q_D threshold **referred to the gate**: VF(BAT54) + V_GS(th)(Q_D) x 147k/100k = 1.43-2.46 V. That band
   overlaps the CSD18510Q5B V_GS(th) of 1.2-2.3 V (SLPS632 section 5.1), so on every exit S_CHG and S_GND conduct
   together for about 25-45 us at nominal values (row F10).
8. **D-BT-SQ effective enable.** EN_SQ = p32 AND NOT X, with X asserted (Q_X2 on) while FF1./Q OR SG1_ON OR SG2_ON, and
   released about 5 ms after all three fall (tau 4.7 ms).
9. **D-BT-EN effective enable.** EN_BE = p28 AND NOT FCQ.
10. **D-BC-RG effective enable.** Stage 2: EN_RG = p30 AND OK1 AND OK2 AND BP1 AND BP2. Stage 1 (M5 not made):
    EN_RG = p30, and firmware holds p30 L.
11. **D-BC-FC effective enable.** EN_FC = p31 (unchanged).
12. **D-MT-EN effective enable.** EN_MT = p29 (unchanged).
13. **Derived BT_BUS state for firmware.** BT_BUS_eff = p28 AND NOT p31.
14. **Gate voltages.** The loaded S_GND gate is about 0.85 x VBT, 6.3 V at 7.4 V (UNCONFIRMED until C-2). The acceptance
    condition is at least 4.5 V at VBT 7.4 V (gate C-2), where SLPS632 specifies 1.6 mOhm maximum.

The hardware closes S_CHG only after both S_GND gates are below 1.43-2.46 V. On a commanded exit the feed drops first,
Q_MD dumps the module input and firmware waits until MOD_COLD_N reads L (T_drain, measured), so the module stops
converting with the sense still in the return path and the overlap of item 7 carries no charger current. On a hardware
trip the eFuse is off within microseconds and Q_MD turns on with it, but the module converts from its own input
capacitance for at most about 1.1 ms, partly with the sense bypassed (row F10). The hardware never powers the charger in
the bonded mode (item 5 needs FF1.Q) unless a fault bypasses the eFuse (rows F11, F35, F36), and never feeds the charger
from V-MOT unless pin 30 is H, V-MOT is above VBUS by the release margin and both bus taps are intact (items 4, 5 and
10).

## 7. Quantitative checks

### 7.1 HR1 power envelope

The Ag105 supplies I_o = I_p + I_L, where I_p is the regulated pack current and I_L is the unregulated VBT load
(revision 2 section 1.3). The module output is rated at 2.5 A (Table 4 JSON code 1). Table 8 gives the input power at the
two profiles (calc section 1, efficiency 0.88 from Ag105 DS p.20, which is stated only at 12 V input and 3S).

Table 8. Input power by profile and pack voltage.

| Profile | I_set | I_L (working value) | I_o | P_in at 7.4 / 7.8 / 8.1 / 8.2 / 8.4 V | Notes |
|---|---|---|---|---|---|
| Regen (RCS 62 kOhm) | 1.75 A | 0.6 A (BT_BUS closed) | 2.35 A | 19.8 / 20.8 / 21.6 / 21.9 / 22.4 W | Meets 18.9 W; misses 23 W; windows open only below 8.0 V |
| FC (RCS 24.02 kOhm) | 1.25 A | 0.3 A (BT_BUS open) | 1.55 A | 13.0 / 13.7 / 14.3 / 14.4 / 14.8 W | Bus 0.82-0.93 A + 0.15 A aux; headroom 0.17-0.28 A to P_MAX 1.247 A |
| Ceiling | - | - | 2.50 A | 21.0 / 22.2 / 23.0 / 23.3 / 23.9 W | 23 W needs a pack at or above 8.10 V |

The 23 W criterion of HR1 cannot be met in a regen window: the window entry gate admits only V_batt below 8.0 V, where
the 2.5 A ceiling gives at most 22.73 W (calc4 section 12). The regen profile needs I_o of at least 2.25 A to reach the
18.9 W peak at 7.4 V; code 3 gives 2.35 A. With an efficiency of 0.80 the regen profile draws 21.7-24.7 W and stays
within the rating, because the rating is on the output current.

The 2.5 A output ceiling is not structural. The Ag105 regulates only I_p; I_L is supplied on top and is bounded only by
the eFuse. At the 1.4 A reverse load of section 12.6 item 3 the module output would be 3.15 A while I_PACK1 reads
1.75 A, so `ERR_PROFILE_OC` stays silent. The design therefore holds I_L at or below 2.5 A - I_set (0.75 A on the regen
profile, 1.25 A on the FC profile; calc5 section 11): a regen window exits when the estimated I_L (BT_CURRENT x V_bus /
(eta x V_batt) plus the LM1084 input) exceeds 0.75 A for 20 ms (TODO(calibrate) at gate B8), and gate B8 measures I_L
in both window types.

The 2.5 A rating is itself an ambient-dependent figure. Ag105 DS p.17 Table 9 permits a 2-cell module every current
setting only up to 45 C ambient, 2.0 A at 60 C and 1.75 A at 70 C, with about 0.5 m/s of airflow, and warns that an
enclosure or limited airflow derates further; above its limit the module enters Thermal Shutdown (Table 6 GENSTAT 110).
The Table 8 regen and ceiling rows (2.35 A and 2.50 A output) therefore hold only up to 45 C ambient at the module, and
the module sits beside the boosts and the CB eFuse. HR1 carries this condition; gates B8 and S0-6 record the module case
temperature at the worst in-vehicle airflow, and a GENSTAT 110 inside a window ends the window without a latch (section
12.5 item 4).

### 7.2 VOK thresholds and the limit-cycle check

Table 9 gives the VOK thresholds over all resistor (0.1 %), reference (1.223-1.260 V), offset (+/-9 mV) and hysteresis
(0-8 mV, applied to the assert level) corners (calc section 2). The comparator supply moves from 5V to 3V3; the
thresholds depend only on the dividers and the internal reference, so Table 9 is unchanged.

Table 9. VOK assert and release voltages (worst case).

| VBUS | Assert | Release | Release margin above VBUS |
|---|---|---|---|
| 13.5 V | 14.31-14.64 V | 13.69-13.94 V | >= 0.186 V |
| 15.9 V | 16.79-17.14 V | 16.06-16.33 V | >= 0.161 V |
| 16.0 V | 16.90-17.24 V | 16.16-16.43 V | >= 0.160 V |
| 16.5 V | 17.41-17.76 V | 16.65-16.93 V | >= 0.154 V |
| 17.5 V | 18.45-18.81 V | 17.64-17.92 V | >= 0.144 V |

If the 2-8 mV internal hysteresis is centred on the threshold, the release falls by up to 32 mV at V-MOT, and the worst
release margin becomes 0.112 V at VBUS 17.5 V (calc4 section 3). Gate V2-1 measures it. The consequences are as follows.

1. **No bus feed while VOK is asserted.** The release level is always at least 0.112 V above VBUS, so D-MT-EN is
   reverse-biased whenever VOK is asserted (RT1987 DS-00 section 13: forward regulation 35 mV, reverse blocking).
2. **Release race.** With the charger drawing 22.4 W from the board-only 0.48 mF, V-MOT falls at 2.59 V/ms and passes
   from the release minimum to VBUS in 62 us; at 0.97 mF this takes 124 us (calc section 2). The eFuse cut completes
   about 18 us after the release at 100 mV overdrive; at the overdrive of a slow ramp the TLV3011B delay is longer
   (SBOS300C Fig. 8-13, typical only), and the cut lands at about 30-38 us (UNCONFIRMED, gate V2-2). For this fall the
   charger is unpowered before D-MT-EN can conduct. When the VESC itself draws 5-20 A from V-MOT (a traction onset),
   V-MOT can cross the release margin in 2.5-12 us; D-MT-EN then feeds the charger from the bus for at most about 12 us
   (about 15 uC) before the cut. The bus never sustains a feed: once V-MOT is at VBUS, VOK stays false and the eFuse
   stays off. HR3 is stated with this bound (section 13).
3. **Zero-input state.** At V-MOT = VBUS = 0 the bus tap carries at least 50.4 mV of reference offset against a V_OS of
   9 mV, so OKk reads NOT OK; BPk also reads absent below 9.3 V.
4. **Assert against the VESC peak.** The worst assert at VBUS 17.5 V is 18.81 V, 2.39 V below the lowest measured V-MOT
   peak of 21.20 V (facts_prior section 6).
5. **Limit cycle.** A cycle occurs if the charger pulls V-MOT down to the release level while regen energy still arrives.
   No cycle occurs if the Ag105 stops drawing at an input above the release level. With the regen profile the threshold
   is the 18.0 V default (Ag105 DS p.10), against a release maximum of 16.43 V at VBUS 16.0 V (margin 1.57 V) and 17.92 V
   at VBUS 17.5 V (margin 0.08 V). The Ag105 threshold tolerance is not given (gate S0-5). This argument covers the
   module draw only. Every VOK pulse also recharges the dumped module node (C_mod) and VCHG-IN from V-MOT through the
   eFuse start, which sags V-MOT by about C_mod x V / C_VMOT: at C_VMOT 0.48 mF the release can come 10.7-11.3 ms into
   the pulse with the node at 2.7-6.2 V, so the module is never powered and the dump repeats at each re-assert; the
   other corners pass with 0.14-0.24 V of margin (`calc/bt4_transient_sim.py` section 2). A limit cycle reduces harvest
   only. S0-5 and V2-4 include the dumped-node start; a Stage-2 build that pursues it lowers the eFuse slew (C_DV up)
   until the start current stays below the regen current.
6. **Tap faults.** With separate taps, no single pad, joint or wire is shared by the two channels. A bus-side tap open,
   a lower-leg short or a capacitor short on one channel makes that channel's U_BPk block it. Even a common lift of both
   VBUS taps fails toward NOT OK. A true copper lift of the R1-BUS pin-2 pad also cuts R1-BUS from VBUS, so pin 26 reads
   0 V and UV_BUS latches after 20 ms.

### 7.3 Pack-current trips

Table 10 gives the trip ranges (calc4 section 2). Compared with revision 3, the budget adds the TLV3011B common-mode
term (CMRR 54 dB at the threshold voltage), the R_K bias-current term and the 3V3 tolerance; the trip current is
proportional to 3V3, because both the threshold and the INA240 midpoint are ratiometric.

Table 10. Trip thresholds.

| Trip | Nominal | Range at 3V3 = 3.30 V | Range at 3V3 = 3.2-3.4 V (ASSUMED tolerance) | Basis |
|---|---|---|---|---|
| U_C1 discharge (reverse through the sense) | 3.00 A | 2.60-3.40 A | 2.52-3.50 A | TLV3011B 9 mV = 0.18 A; CMRR 0.06 A; INA240 offset 0.05 A, reference 0.033 A; divider 0.033 A; R_K 0.008 A; gain 0.2 %; 1 % shunt |
| U_C2 charge | 3.14 A | 2.73-3.54 A | 2.65-3.64 A | As above |
| D5 BT-loop | 0.50 A | 0.31-0.59 A | - | INA253 floor 10 mV; TLV3011B 9 mV |
| eFuse I_OL | 1.98 A | 1.84-2.16 A | - | SLVSE94G section 6.5 |
| Ag105 OC trip (credited only after S0-2 and D-3) | I_set + 0.2 A | 1.95 A regen, 1.45 A FC | - | Ag105 DS p.18 |

The I_B mismatch of the two INA240 inputs through R_K adds 0.044 A per 10 uA of mismatch; the mismatch value and the
series-resistor gain error are TODO(verify: SBOS662C input filtering), so gate T1 sets the final range. U_C1 lies below
the 4 A continuous discharge limit of the module (Ag105 DS p.20 row 6; applied to this path UNCONFIRMED). U_C2 lies above
the largest wrong stored code (2.5 A) and above the regen profile with its OC trip (1.95 A). The pack maximum charge
current is not known (pack datasheet missing, facts_prior section 9). The trip timing of about 76 us uses the 4 us t_PD
at 100 mV overdrive; at a slow ramp the delay is longer (BENCH, gate T1).

### 7.4 Pumped arm

The pump runs at half the loop rate, 442 Hz at the 1131 us median iteration (facts_firmware section 8). The hold voltage
is 3.70 V +/- 0.24 V, the ON margin above the Schmitt upper threshold is 1.38 V, and the hold node stays above 2.96 V
after the worst measured 9.76 ms loop gap. After the last edge, PUMP_OK falls in 43-76 ms. The pump needs at least 26 Hz,
that is a mean iteration of at most 19.2 ms (calc section 4). The Schmitt thresholds at 3.3 V are interpolated (IC5
section 3.2, UNCONFIRMED) and the driver output level is TODO(verify: AHCT1G125 datasheet).

### 7.5 eFuse

The SHDN node reaches 3.16 V when EF_EN is H (2 V maximum rising threshold) and at most 0.22 V when the gate output is
high-Z (0.8 V minimum falling threshold). With C_DV 10 nF the output slews at 4.17-5.79 V/ms, the UVLO turn-on delay is
about 1.24 ms, the output reaches 18 V about 3.6 ms after turn-on, and a 100 uF Ag105 input capacitance draws at most
0.58 A of inrush (calc section 5). Q_MD is off within about 1 us of the EF_EN rise and adds at most 0.4 mA to it
(calc6 section 3). The Ag105 input capacitance is not given (gate S0-11). With R_ILIM 8.06 kOhm the input power bound
at I_OL maximum (2.41 A) and the 21.47 V regen peak is 51.8 W (calc6 section 5).

The eFuse overload behaviour depends on when the overload starts (SLVSE94G sections 6.6, 8.3.1.1, 8.3.7.2.1, Table 8-1):

1. **Overload after a completed start-up.** The current limits at I_OL and the eFuse latches off after tCL_PLIM(dly),
   129-202 ms (the section 6.6 row omits the TPS26631 while Table 8-1 applies it: TODO(verify: SLVSE94G), gate S0-12).
   The 2 x I_OL pulse phase (tCB) needs PGOOD HIGH, which PGTH = GND prevents, so tCB does not apply. FLT asserts
   after tCB_FLT(dly), 22-30 ms for the TPS26631.
2. **Start into an overload.** Every window entry is a power-up of the eFuse (SHDN or UVLO rising), which enables the
   thermal-regulation loop. With an overload present from the start, the current limits at I_OL and T_J is regulated at
   145 C for up to t(Treg_timeout), 2.3-2.9 s; FLT asserts only after that timeout. In a regen window every VOK pulse is
   a new start, and a SHDN toggle resets the latch. The eFuse can hold I_OL only while the input-output drop is small:
   at an RthJA of 31.4 C/W (SLVSE94G EVM figure) T_J reaches the 145 C regulation point at a drop of about 1.6-2.1 V
   at 25 C and 1.1-1.5 V at 60 C (3.8 W and 2.7 W at 2.41-1.82 A) (`calc/bt3_datasheet_lens_calcs.py` section 1). A **soft overload** (a load that holds the
   output within that drop) is therefore held at I_OL for up to 2.9 s, about 112 J at 16 V and 2.41 A; this is the
   case that U_IM bounds. A **hard short** is thermally limited to about 0.13-0.28 A during regulation, so its energy
   is far smaller. Whether the 2.9 s timer runs when T_J never reaches 145 C, and the role of the 162 ms timeout on the
   current-limit path of the block diagram, are TODO(verify: SLVSE94G section 8.3.7.2.1); gate S0-12b measures it.
3. **Hard short after start-up.** The fast trip at 3 x I_OL (6.2-7.2 A at R_ILIM 8.06 kOhm) stays active; PGTH = GND
   does not disable it.

The approved alternate TPS26636 differs. SLVSE94G rev G (section 11) deleted it from section 8.3.7.1.2 and Table 8-1
groups it with the TPS26630 and TPS26632, so it is a 1 x I_OL limiter; neither I(FASTRIP) row of section 6.5 names it
(fast trip TODO(verify: TI)); and its pin 8 is PLIM, with an overvoltage clamp (35 V in section 8.3, 39 V in the
comparison table) in place of the TPS26631 OVP cutoff. Cases 1 and 2 and the U_IM bound apply to it unchanged; case 3
is unverified for it. S0-12 qualifies the part actually fitted.

The magnitude bound (at most I_OL, 2.41 A) holds in every case; the time bound does not hold for case 2. U_IM therefore
clears FF1 when the eFuse input exceeds its trip of 1.51-1.98 A (section 5.2), which bounds case 2 to the U_IM response
(filter tau 0.1 ms plus the comparator delay, BENCH S0-12b) and ends the window. The trip lies below the I_OL minimum of
2.06 A on every unit, by design and by the per-unit S0-12b trim, so the eFuse cannot hold an overload at I_OL while
U_IM stays released.

### 7.6 Return path and Teensy supply

With lead A alone the SB ground sits 155 mV below PCB GND at the in-service 7.2 A and 369 mV at 17.1 A. With lead B in
parallel the figures are 14 mV and 32 mV (calc section 8). The new series elements in the pack loop (S_GND pair hot
1.2 mOhm, R_SH 0.5 mOhm) use 1.7 mOhm of the 12.9 mOhm budget of revision 2 section 4.1; F_PK (now in the positive
lead), its holder and the SB terminals take the rest (TODO(verify: fuse datasheet)). At the 7.4 V floor and 17.1 A, with
two 20 mOhm contacts and the full budget, VBT - GND is 6.50 V, exactly the LM1084 regulation limit (SNVS037H section
5.5); lead B removes about 0.3 V of the pin-2 contact drop and restores the margin. Pack positive never leaves VBT. With
both S_GND channels lost (row F2) VBT - GND falls by one body-diode drop. The LM1084 dropout is specified as 1.5 V
maximum over the full output-current range (SNVS037H section 5.5 note 5), so a lower dropout at the Teensy load is
typical only; with a 1.0 V body diode at the 7.4 V floor the regulator input sits at 6.4 V, below the 6.5 V limit.

### 7.7 Status ladders

The ladder step is 103 mV. A 0.5 % mismatch between 2R and 2 x R contributes up to 16 mV, and the worst-specification
LVC output-high droop on the MSB contributes up to 50 mV; the sum (66 mV) exceeds the 52 mV half step. Firmware therefore
decodes each ladder against the 32 voltages measured at C-2 and treats a reading more than 30 mV from every calibrated
code as undecodable (calc section 7).

With R = 2.00 kOhm and C = 10 nF the time constant is 20 us. A one-LSB change settles to 30 mV in 25 us; the largest
change (31 LSB) settles in 93 us (calc4 section 4). Each bit draws about 0.55 mA from its buffer. The ADC sample-capacitor
kickback is 1.6 mV at an ASSUMED 5 pF and 6.6 mV at 20 pF, and recovers within 40 us (C_sample TODO(verify: IMXRT1060
datasheet)). Gate C-2 measures the step response.

A reading is **settled** when two decodes on successive loop iterations give the same code. The time-critical
confirmations of section 9 use settled readings. The loop has no fixed tick (1131 us median, 1337-1341 us p99,
9.76 ms worst measured, Table 11), so every confirmation deadline and every persistence rule is counted in iterations,
not in milliseconds (revision 6, FM3-3): an entry or exit confirmation is due within 4 iterations of the edge, a
persistence rule needs 3 consecutive iterations, and a 30 ms wall-clock cap (above the 9.76 ms worst gap and below the
43 ms pump hang-to-off minimum) backs both. Four iterations take 4.52 ms at the median, and 13.15 ms with one worst gap
(calc6 section 7). A single read that straddles an edge is undecodable for less than 0.1 ms and needs one more
iteration, which the 4-iteration allowance contains. Hardware-driven bits (CH1_OK, CH2_OK, D5_N and the
VOK-dependent part of EF_EN) change without a command and are not compared with the commanded state.

### 7.8 Ag105 start and the regen pulse

A regen pulse lifts V-MOT from 15.9 V to 21.2-21.5 V in 19-47 ms (facts_prior section 6). With VOK gating, the charger
receives input only above the assert level, so in every pulse the chain is as follows: V-MOT crosses 16.90-17.24 V; D-BC-RG
turns on after t_D_ON (8 ms typical, no maximum, RT1987 DS-00 section 13); D-BC-RG ramps at 12 V/ms (CSS 5.6 nF) to the
eFuse UVLO (about 1.07 ms to 12.88 V); the eFuse output ramps (about 1.2 ms delay plus about 3.6 ms to 18 V); the Ag105
starts. Table 8a gives the time left for the eFuse ramp and the Ag105 start before V-MOT reaches the 21.35 V VESC stop
(linear ramp, calc4 section 11).

Table 8a. Allowance from eFuse enable to charge current, by pulse.

| Pulse | VOK assert (16.90 / 17.24 V) | Allowance at t_D_ON 8 ms | Allowance at t_D_ON 12 ms (sensitivity) |
|---|---|---|---|
| 19 ms | 3.5 / 4.7 ms | 6.4 / 5.3 ms | 2.4 / 1.3 ms |
| 47 ms | 8.6 / 11.6 ms | 29.3 / 26.4 ms | 25.3 / 22.4 ms |

Table 8a assumes that pin 30 is HIGH before VOK asserts. Under the revision-4 [RER] power arm (at least 3.0 W for
40 ms) pin 30 rose 42.3-45.4 ms after the braking command, after the first pulse had peaked (24-52 ms after the command),
so the first pulse of every decel was lost and at most 43.9 % of the node energy above 18 V stayed reachable even with
an instantaneous Ag105 (`calc/bt2_transient_sim.py` section 2, `calc/bt2_requirements_operability.py` sections A-B).
Revision 5 arms the window on the command step (ruling OR-V', section 9.5): pin 30 is HIGH 5.4-7.4 ms after the command,
and the VOK assert follows 8.5-16.6 ms after it, so pin 30 leads VOK by at least 1.1 ms at the worst pairing (calc5
section 7). The window-open latency t_open = t_arm + t_settled + t_step5 enters the S0-6 GO inequality.

The 5.4-7.4 ms figure rests on the retired fw v35 drive law, in which the command railed to -12 A and the arm came
1.2-3.4 ms after the first negative command on all 7 BLG events (`calc/bt3_requirements_operability.py` section A). The
flashed fw v37 law has a feedthrough of 0.214 A per m/s, so even with the speed frozen the command reaches -2 A 4, 8, 14
and 26 ms after a decel step of 1.0, 0.5, 0.2 and 0.1 m/s (section B). The arm then lands after the first VOK assert of
a gentle decel, and its first pulse can be lost. The controller updates every 2 ms (DRIVE_CTRL_TS_US 2000), so the arm
is stated as two consecutive drive-controller samples (4 ms), not two 1 kHz ticks. The latency is measured from the
first command below -0.1 A (gates S0-6 and V2-4). Calc5 section 7 is to be re-derived with the v37 law in closed loop
around the HIL plant (`tools/drive_ripple.py`), and a v37 decel BLG with a non-zero target steeper than coast-down is a
Stage-0 evidence item (ML0226 has no negative command); an arm on a smaller magnitude with a rate condition is recorded
under ruling OR-V'.

The eFuse delay and ramp alone take 4.4-5.6 ms, so on the 19 ms pulse almost no time is left for the Ag105 start. The
prior study measured a cold start of 65-170 ms. Between pulses VOK releases and the charger is cold again. At the measured
cold start the rise of no pulse is captured. The powered interval is longer than the rise: after the VESC stop at 21.35 V,
V-MOT decays at 14-20 V/s with no IC1 load and at about 72 V/s with the idle IC1 node load, so VOK stays asserted for
84-416 ms per pulse and V-MOT stays above the 18 V threshold for about 47-239 ms (`calc/bt5_transient_sim.py` section 1,
facts_prior section 6; revision 7 treated the 19-47 ms rise as the whole interval, BT5-TR-04). A start of 65-170 ms can
therefore complete inside the tail and capture tail energy; how much is BENCH (V2-4). HR1 capture depends on gates S0-6
and V2-0 per pulse family; the hold-up stage that could add margin is withdrawn
from revision 7 (section 14.4).

### 7.9 V_PACKN channel

R_VPS is in series with R_V2, so the lower leg is 110 kOhm. V(pin 23) = 1.7286 V + 0.4762 x V_PACKN at 3V3 = 3.30 V, and
V_PACKN = 2.100 x V(pin 23) - 1.100 x 3V3 (calc4 section 7). The revision-3 decode had a +157 mV offset and a -4.8 % gain
error. One ADC count is 1.692 mV of V_PACKN. A 5 mOhm change of the return resistance is 3 counts at 1 A and 15 counts at
5 A; the return-resistance test therefore runs only at 5 A or more. Gate C-2 calibrates offset and gain at two points
(V_PACKN = 0 and a known negative voltage injected at V_PACKN_S) and uses the measured 3V3.

## 8. Timing budget

Table 11 lists every delay that a sequence or a protection relies on.

Table 11. Timing budget.

| Chain | Delay | Source |
|---|---|---|
| p33 rising edge to FF1.Q | 5.6-9.9 us (R_CK 10k / C_CK 1 nF into U_CKS) plus the LVC propagation; /CLR released within 1.1 us at C_N1 130 pF; margin >= 4.5 us | Calc4 section 6; C_N1 BENCH (C-2) |
| p33 LOW or high-Z to FF1 clear | Nanoseconds (U_P33, U_N33, U_CLS) | Calc4 section 6 |
| FF1.Q H to both S_GND off | Within 0.1 ms | Rev 2 section 2.2 item 3 |
| FF1.Q H to S_CHG on | R_CQ/C_CQ tau 100 us, then Q_B into 8.8-11.4 nF through 1 kOhm | Rev 2 section 2.2 |
| FF1.Q H to D-BT-SQ conducting | X release about 5 ms plus t_D_ON 8 ms typical: about 13 ms | Calc section 9; RT1987 DS-00 section 13 |
| FF1.Q L to eFuse off | tSD(dly) 0.8-1.5 us | SLVSE94G section 6.6 |
| FF1.Q L to both S_GND on | Gate rise tau 88-114 us | Rev 2 section 2.2 item 4 |
| S_CHG and S_GND overlap at exit | About 25-45 us at nominal values | Eq. 7; BT1-DS-05 calc; C-2 |
| FF1.Q L to D-BT-SQ disabled | 0.3-0.7 ms | Rev 2 section 2.3 |
| VOK release to eFuse off | About 18 us at 100 mV overdrive; about 30-38 us on a 2.6 V/ms fall; both rest on the push-pull t_PD, the open-drain delay is not specified (UNCONFIRMED, V2-2) | Calc section 9; SBOS300C 6.10 |
| VOK release to D-BC-RG off | Clamp: microseconds; RT1987 turn-off after EN low TODO(verify: RT1987 DS-00) | - |
| VOK assert to D-BC-RG on | t_D_ON 8 ms typical, no maximum; BENCH V2-0 | RT1987 DS-00 section 13 |
| D-BC-RG on to eFuse UVLO | About 1.07 ms (12 V/ms to 12.88 V) | facts_prior section 10 item 4; calc4 section 9 |
| eFuse enable to output at 18 V | UVLO/SHDN turn-on about 1.24 ms plus 3.6 ms ramp | Calc section 5 |
| U_C1 / U_C2 trip to eFuse off | Filter tau 70 us plus t_PD plus 1.5 us: about 76 us at 100 mV overdrive | Calc section 9; T1 |
| U_C1 trip to S_GND on (direct path) | 76 us plus gate rise tau 88-114 us | Rev 2 section 4.2 |
| Pump stop to FF1 clear | 43-76 ms | Calc section 4 |
| D5 arming after FCQ rises | 2.8-6.1 ms (Q_D5 threshold 0.8-1.5 V) | Calc4 section 10 |
| D5 detection | Filter tau 1 ms plus t_PD | Design value |
| BQ29200 OVP to FF1 clear | CD delay BENCH (BG-17): XDELAY 6-12 s/uF (SLUSA52C section 7.5) x the fitted 0.33 uF gives 1.98-3.96 s, but 0.33 uF is 3.3 x the 0.1 uF recommended maximum (section 7.3) and the figure excludes capacitor variation (1.58-4.75 s with X7R tolerance) | `calc/bt2_datasheet_reverify_calcs.py` section 3 |
| eFuse overload latch-off | Post-start overload: tCL_PLIM 129-202 ms, FLT after tCB_FLT 22-30 ms. Start into an overload: up to 2.9 s of thermal regulation, FLT only after it (bounded by U_IM instead) | SLVSE94G sections 6.6, 8.3.1.1, 8.3.7.2.1, Table 8-1 |
| eFuse input above the U_IM trip (1.51-1.98 A) to FF1 clear | Filter tau 0.1 ms plus the open-drain comparator delay; BENCH S0-12b (GO within 5 ms) | Calc6 section 5 |
| Commanded exit: feed off to pin 33 LOW (T_drain) | Measured: until MOD_COLD_N reads L on two successive iterations (module node below 8.69-9.15 V through R_MD); 1.3-2.9 ms at C_mod 100-221 uF from 21.5 V (3.02 ms to the 8.69 V edge), plus one iteration. Deadline T_drain,max = the later of 10 ms and 4 iterations after the feed drop, capped at 30 ms (`ERR_MOD_DRAIN`): with one 9.76 ms iteration the latest healthy second LOW read is 12.02 ms against a 13.15 ms deadline at the median loop and 12.44 ms against 13.78 ms at the p99 loop | Calc6 sections 3, 9; calc7 section 5 |
| Commanded exit: exit hold check of pin 8 | Evaluated only with EF_EN H, pin 8 HIGH for at least 2 ms and V_chg at or above 13.5 V read immediately before the write (revision 8). Samples 50 us and 150 us after the feed-drop write; a healthy fed node (at least 13.4 V) holds U_MS HIGH for at least 170 us at C_mod 47 uF and 22.7 W, 361 us at 100 uF (ESTIMATE); a pin 8 that follows EF_EN falls in about 3 us plus the U_MS delay (TODO(verify: SBOS300C), C-2b) | Calc8 section 1; `calc/verify_ms_shdn_short.py` S3 |
| `ERR_MOD_SENSE` (b) deadline after the crossing anchor | 50 ms (FC window, configuration check); regen window: the later of 10 ms and 4 iterations, capped at 30 ms; worst lag to pin 8 HIGH 3.38 ms; margin 5.28 ms at the p99 loop without a gap | Calc7 section 5 |
| Window entry: cold-module precondition | MOD_COLD_N L for at least 20 ms (node below 0.5 V after 5.3-11.5 ms of dump) | Calc6 section 3 |
| Module node decay with Q_MD open (bleed R_MB only) | 16 V to 9 V in at most 0.42 s; 21.47 V to 11 V in at most 0.49 s (C_mod 221 uF) | Calc6 section 3 |
| Ladder settle (largest step to 30 mV) | 93 us | Calc4 section 4 |
| Firmware loop | 1131 us median, 1337-1341 us p99, 9.76 ms worst measured | facts_firmware section 8 |
| Settled ladder reading | Two iterations: 2.26 ms median, 2.68 ms p99 | Calc4 section 4 |
| Entry or exit confirmation deadline | 4 iterations after the edge (4.52 ms median; 13.15 ms with one 9.76 ms gap), or 30 ms wall-clock, whichever comes first | Calc6 section 7 |
| Ladder persistence (`ERR_CHG_LADDER`) | 3 consecutive iterations (3.39 ms median) | Calc6 section 7 |
| Regen entry arm | Commanded motor current at or below -2 A on two consecutive drive-controller samples (4 ms; ruling OR-V'). Pin 30 HIGH 5.4-7.4 ms after the command under the retired fw v35 law; under fw v37 the -2 A level comes 4-26 ms after a decel step (UNCONFIRMED in closed loop) | Calc5 section 7; `calc/bt3_requirements_operability.py` sections A-B |
| Regen release dwell | 200 ms | [RER] |
| Window rate limit | At most 20 transitions per minute | [RER] |
| Ag105 cold start to current | 65-170 ms (prior measurement); BENCH S0-6 | facts_prior section 6 |
| `ERR_VCHG_FED` blanking after a feed edge | 1.0 s (VCHG-IN bleed tau 0.984 s; 21.47 V to 11 V in 0.658 s); valid because Q_MD holds the module node below VCHG-IN, so the eFuse reverse path no longer couples the module hold-up onto VCHG-IN (with Q_MD open, R_MB brings the coupled node to 11 V in at most 0.49 s); TODO(calibrate) at C-2 | Calc5 section 5; calc6 section 3 |
| `ERR_VOK_STUCK` persistence | 50 ms of a channel permitting while the self-calibrated V-MOT/VBUS ratio is below 1.003; independent of the V-MOT decay rate (the revision-5 dwell rule needed 14.9 V/s or faster for a single-channel assert, against a measured 14.2-20.1 V/s) | Calc6 section 6; `calc/bt3_transient_sim.py` section 1 |
| Ag105 Bring-Up without a keep-alive | About 8.4-11.7 s (0.64 V/s, ML0227, sense shorted; applicability to an isolated return UNCONFIRMED) | facts_ag105 section 3 |
| `AG105_SETTLE_MS` | 500 ms, TODO(calibrate); gates the configuration writes and the NAK fault, not the reg 0x06 read | ino:2484, ino:16158-16207 |

## 9. Modes and transitions

### 9.1 Mode table

Table 12 gives the commanded pin levels and the resulting hardware state of each mode. "T" means toggling once per
`loop()` iteration. "x" means unchanged by the mode (owned by the existing state machine and share loop). MPPTD is Teensy
pin 5 (`MPPT_DISABLE`, open-drain from revision 6), LOW = MPPT disabled, H = released. The column "Q_MD" is the
module-node dump (ON while EF_EN is L) and "p8" the expected MOD_COLD_N level.

Table 12. Mode table.

| Mode | p33 | p34 | p35 | p10 | p28 | p29 | p30 | p31 | p32 | p5 | FF1 | S_GND | S_CHG | D-BT-SQ | D-BT-EN | D-BC-RG | eFuse | Q_MD / p8 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Unpowered, reset, hung | Z (U_P33 pull-down: FF1 clear at once) | Z or static | Z | Z | Z | Z | Z | Z | Z | Z | clear | ON | OFF | off | off | off | off | Unpowered: off (gate pull-down) / H (pull-up). Reset or hung with the LB 3V3 up: ON (U_MDI drives MD_G = NOT EF_EN) / L (completeness critic CC-12) |
| Boot, before bring-up | L | L | L | L | L | L | L | L | L | L | clear | ON | OFF | off | off | off | off | ON / L |
| Self-test (section 9.3) | per step | T | per step | per step | L | L | L | L | H | L | per step | per step | per step | off | off | off | off (VCHG-IN unfed) | ON / L |
| Idle (State 1) | L | T | L | L | x | H | L | L | H | L | clear | ON | OFF | off (cross-lock) | x | off | off | ON / L |
| Run, traction (State 2) | L | T | L | L | x | H | L | L | H | L | clear | ON | OFF | off | x | off | off | ON / L |
| Regen window (Stage 2) | H | T | L | L | x (BT_BUS may stay closed) | H | H | L | H | H | set | OFF | ON | on after ~13 ms | x | on iff VOK (after t_D_ON) | on iff VOK | ON between pulses / H in a pulse |
| FC window (State 1 or 98; State 2 at standstill, revision 9) | H | T | L | H | L (and Q_X1) | H | L | H | H | H | set | OFF | ON | on after ~13 ms | off (hardware) | off | on | off / H |
| Commissioning, configuration check or eFuse-blocking probe (sections 9.2, 9.7a; the probe runs with p33 L and FF1 clear) | H | T | L | H | L (and Q_X1) | H | L | H | **L** | L | set | OFF | ON | **off (p32 L)** | off | off | on (probe: off) | off / H (probe: ON / L expected) |
| Finish (State 3) | L | T | L | L | x | H | L | L | H | L | clear | ON | OFF | off | x | off | off | ON / L |
| State 99 (latched) | L | L (stopped) | L | L | per teardown | per teardown | L (drains skipped) | L (drains skipped) | **L** (revision 6) | L | clear | ON | OFF | off | per teardown | off | off | ON / L |

The bonded rows keep REGEN and FC_CHARGE LOW, and firmware refuses both outside the charge-mode states (section 12.4
item 7), so the bus never feeds the Ag105 in the bonded mode. The only exception is the eFuse-blocking probe of section
9.7a (FC_CHARGE HIGH for at most 100 ms with pin 32 LOW and FF1 clear), which tests that the eFuse blocks. Pin 32 stays HIGH after boot except in commissioning,
configuration checks, State 99 and after `ERR_CHG_LADDER` (revision 6: with a dead LB 3V3 rail the cross-lock is
lost, BT3-LS-03); otherwise the cross-lock alone disables D-BT-SQ in the bonded mode (ruling OR-G records this change
of meaning for IO CSV row 32).

### 9.2 Commissioning (one time, State 98, Stage 1 bench)

The following procedure sets the Ag105 registers of Table 5. The FC input is a current-limited bench supply on J-FC, set as
step 2 states. Pin
32 stays LOW throughout, so D-BT-SQ is disabled, the module sees an open VCHG node and draws only its quiescent current
(RT1987 disabled: VIN isolated from VOUT, RT1987 DS-00 section 17).

1. Make sure that gates C-1, C-1b, C-1c, C-1d, C-2a, P8, P-M1, B-FPK, B-PKN, BG-17a, BG-17b and D-3 have passed (gate C-2b
   follows step 11). Note the build: in a BENCH_TEST 1 build `OC_FC` is compiled
   out (ino:7114-7115), so the bench supply limit is the only current bound.

WARNING: Do not set the J-FC bench supply above 12.3 V. The FC-V divider (R1-FC 27.4 kOhm over R2-FC 10 kOhm, no clamp,
BOM rows 58-59) puts more than 3.3 V on Teensy pin 24 above 12.34 V and more than its 3.6 V absolute maximum above
13.46 V (calc12 section 2). Above the 15.95 V bus target the FC boost cannot regulate, and the firmware has no V_fc
overvoltage fault, so the reading saturates at 12.34 V with no indication.

2. Set the bench supply on J-FC to 12.0 V with a 1.5 A current limit (pin 32 LOW: the module draws only its quiescent
   current). Before step 3, confirm that V_fc (pin 24) reads 12.0 V +/- 0.2 V. Revision 11 set 16 V, which put 4.28 V on
   pin 24 and held the FC boost out of regulation (revision 12, BT8-REQ-01).
3. In State 98, bring the bus up with `G`.
4. Set pin 32 LOW. Confirm on ladder B that both SG bits are HIGH (bonded).
5. Start the pump (pin 34 toggling) and set pin 10 HIGH (FC profile).
6. Set pin 33 HIGH. Confirm a settled reading: FF1.Q HIGH on ladder A, both SG bits LOW on ladder B.
6b. Drop BT_BUS through the existing guarded path and wait until BT_CURRENT (pin 41) reads below 0.2 A (timeout
   20 ms: abandon the session), as section 9.7 entry step 5, so that the BT current has decayed before D5 arms
   (CC-3).
7. Raise FC_CHARGE through `assertFcChargeEnable(true)`. Confirm ladder A bit 1 (EF_EN) HIGH. The commissioning
   sub-mode is the `CHG_CONFIG` state with the register writes of step 9 enabled, so the refusals of section 12.4
   item 7 admit this call (CC-4). Read the 4-iteration mean of FC_CURRENT (pin 40) before the raise and the 4-iteration
   mean that starts 10 ms after `chargerHasPower()` first turns true (revision 8); a step
   above 0.4 A latches `ERR_MOD_DUMP_ON` and ends the session through step 11 (row F50). In a BENCH_TEST 1 build this is
   the only detector of a stuck dump, because `OC_FC` is compiled out.
8. Wait `AG105_SETTLE_MS`. Read and record the as-found reg 0x00-0x04 and 0x0A.
9. When reg 0x00, 0x01 or 0x02 differs from Table 5, write the Table 5 value. Write each register once only.
10. Read back the three registers. When a readback differs, stop and record the values.
11. Drop FC_CHARGE, wait until pin 8 (MOD_COLD_N) reads LOW (T_drain, section 9.5 exit step 2), set pin 33 LOW,
    confirm a settled reading of FF1.Q L, stop the pump, then set pin 32 HIGH. Record the time from the feed drop to the
    pin-8 LOW reads and confirm that `ERR_MOD_DRAIN` did not latch: this is the first run of the drain wait on the
    vehicle, and gate C-2b then repeats it under test. Pin 32 HIGH is refused while ladder A bit 0 (FF1.Q) reads HIGH (section 12.4 item 7).

WARNING: Do not write reg 0x01 with a value other than 0x08. A 3S code charges the 2S pack to 12.6 V.

WARNING: Do not feed VCHG-IN_M from an external supply while EF_EN is L. Q_MD then connects R_MD 15 Ohm across the
supply, which puts 5 W or more into R_MD beside the Ag105 at 9 V (about 19 J on a 9.5 s ramp to 9.5 V). Lift MD_G at CB
first, so that R_MDG holds Q_MD off, and set the supply current limit to 50 mA (`calc/verify_c2_ums_ramp_rmd.py`).

**J-FC setting for every later bench-supply session (revision 12, BT8-REQ-01).** Every FC-fed session from a bench supply
after commissioning (gates C-2b, C-3, W1, B8-1, W2a, W2c and V2-6) uses J-FC at 12.0 V with a 2.0 A current limit. An
FC window draws 1.24-1.58 A from J-FC at 12.0 V (bus 15.8 V, charger 0.82-0.93 A plus aux 0.09-0.15 A, boost efficiency
0.90-0.97 ASSUMED from SLVSFP3C p.1, TODO(calibrate) at B8-1), so the 1.5 A commissioning limit would fold the supply back
inside a window and latch `ERR_FC_ONLY_COLLAPSE`; 2.0 A is 1.27 times the worst draw (calc12 section 2). The 9.3 V supply
of the ML0227 session (`docs/boost-bringup-debug.md`, 2026-11-04) draws 1.59-2.04 A and is not used for windows.

WARNING: Do not set pin 32 HIGH while the module is powered with the as-found reg 0x00 = 0x01. The module then charges
at 2.5 A plus the board load (2.8 A output, above the 2.5 A rating), and the bus-side current of 1.63-1.75 A trips
`OC_FC` or exceeds the bench supply limit.

### 9.3 Boot and Idle self-test

The self-test runs once in `setup()` after the pins are driven to their boot levels, and again at each Idle entry. An
Idle entry is a transition into State 1 from State 3 or from State 98. The State 0 to State 1 transition after the
bring-up is not an Idle entry: the boot self-test has just run, and its result stands for the first Idle (revision 12,
BT8-LS-01; otherwise a Pi Run command 0.00-0.49 s into a session aborts the first self-test, and the deferred result
refuses every D-s window of that Run). In
both cases FC_CHARGE and REGEN are LOW, so VCHG-IN is unfed and the Ag105 stays unpowered even when the eFuse enable is
HIGH. Any failure sets a reboot-only `ERR_CHG_SELFTEST` latch that refuses every window. An Idle entry while a commanded
exit is still in progress (a Finish inside a window reaches State 1 within two iterations) queues the self-test until
the mode manager is back in `CHG_BONDED` (section 12.4 item 8, revision 8).

The Idle-entry self-test is a non-blocking sub-state of `chgModeTick()`. It advances at most one step per loop
iteration, after `detectFaults()`, so the fault dwells, the share loop, the Pi link and the VESC stream run on every
iteration. Each confirmation uses settled readings from successive iterations (two identical decodes, section 7.7);
timed holds and waits use `millis()` deadlines. The pump writer of section 12.4 item 1 stays the only writer of pin 34:
the self-test only requests "stop" or "run". While step 2 holds pin 34 static, pin 33 is LOW, so the 40 ms hang rule of
section 12.4 item 5 has nothing to clear. The boot self-test runs the same sub-state machine from `setup()` before the
bring-up, with no traction possible.

**Abort.** A State-2 request, a non-zero motor command or any fault aborts the self-test. A window request does not
abort it: the window waits for the self-test result, which delays the first window of that Idle by at most 457.5 ms
(revision 12, BT8-LS-01, calc12 section 10). Revision 11 also aborted on a window request; the OR-RQ parked request
stands in every packet from the MODE_SAFE packet that causes the Finish, so every Idle-entry self-test of a parked
vehicle was deferred and every P window refused. The abort sets pin 35 LOW, pin 10 LOW and pin 33 LOW, sets the pump
running, and records the result "deferred". A deferred result refuses every window, with refusal code 16 (Table 25),
until the self-test passes. After a deferral the mode manager re-runs the self-test at the first Idle iteration with no
State-2 request pending. In Stage 2, after a deferral by step 10 alone, it re-runs step 10 when MOT_PWR reads HIGH,
without waiting for a new Idle entry. A Run request inside the self-test therefore refuses D-s windows in that Run
(code 16) until the next Idle re-run passes. The State 1 to 2 transition and any non-zero motor command wait
until the abort shows a settled reading of FF1.Q L and both SG bits H (at most about 3 ms after the request at the p99
loop). While any charge-mode step runs, the VESC command is held at 0 A. A step that sees |I_PACK1| above 0.5 A during a
charge-mode step aborts (result "deferred"); it does not fail.

1. Read both ladders. Expect FF1.Q L, EF_EN L, EF_FLT_N H, PUMP_OK L at the boot self-test (pump not yet started,
   section 12.3 item 5) and PUMP_OK H at an Idle-entry self-test (pump running, section 12.4 item 1; the PUMP_OK L check
   at an Idle entry is the stop clause of step 2), pin 8 (MOD_COLD_N) L, both SG bits H (both S_GND enhanced), CH1_OK L
   and CH2_OK L in Stage 1 only (tied LOW; in Stage 2 the CH bits are checked at step 10 after the V-MOT settle, because
   a regen tail keeps a channel permitting for up to 0.238-0.381 s after a pulse peak, `calc/bt4_logic_seq_enum.py`
   section 2), and D5_N H unless BT_CURRENT (pin 41) is above 0.3 A. When BAL_OK is L, windows are
   refused (section 12.6, `ERR_BAL_ABSENT`) but the self-test continues.
2. Pump test (IC5 section 3.5 steps a-c): run the pump for 20 ms; expect PUMP_OK H. Stop it; expect PUMP_OK L within
   90 ms. Hold pin 34 HIGH static for 200 ms; expect PUMP_OK to stay L (detects a shorted C_P1). Throughout this step
   expect FF1.Q to stay L (detects a pin-33/pin-34 tap bridge).
3. Restart the pump. Wait 20 ms.
4. Latch test: set pin 33 HIGH. Expect FF1.Q H, both SG bits L and EF_EN L (no source term: RGQ L, FCQ L). A FF1 that
   cannot set (a clear source stuck LOW, an open BQ29200 OUT fly-wire, a shorted N1 join) fails here.
4b. Pin-33 clear test: set pin 33 LOW alone (pump running, no injection). Expect FF1.Q L and both SG bits H on the next
   settled reading. Set pin 33 HIGH again; expect FF1.Q H. This tests the U_N33 path on its own.
5. Sense-path test (rows F1, F44): when I_PACK1 shows a discharge of at least 0.2 A, expect V_PACKN at or below
   -I_PACK1 x R_chain,min, where R_chain,min is the C-2 value of the charge-mode chain (S_CHG, VBATN_X, Ag105 sense). A
   reading near 0 V means that a bond bypasses the sense (an S_GND drain-source short). When BT_CURRENT predicts a pack
   discharge above 0.5 A (BT_CURRENT x V_bus / (0.95 x V_batt)) while I_PACK1 reads less than 0.2 A, the step fails
   (the Kelvin pair is blind). When both are below their levels, the step is skipped, not failed (TODO(calibrate)).
6. U_C2 and D5 injection: set pin 10 LOW, then pin 35 HIGH. Expect SIG2 (pin 17) to fall to 0.845 x its previous value
   +/- 3 % and to at most 1.460 V; expect FF1.Q L, both SG bits H and D5_N L (with FCQ LOW, Q_D5 is off and D_D5S blocks
   its body diode, so D5_N L is the U_D5 output itself). Set pin 33 LOW, then HIGH again; expect FF1.Q to stay L (U_C2
   holds the clear). Set pin 35 LOW; expect D5_N H. Set pin 33 LOW.
7. U_C1 injection: set pin 33 HIGH (expect FF1.Q H). Set pin 10 HIGH, then pin 35 HIGH. Expect SIG1 (pin 16) to fall to
   0.845 x its previous value +/- 3 % and to at most 1.460 V; expect FF1.Q L and both SG bits H. Re-edge pin 33; expect
   FF1.Q to stay L. Set pin 35 LOW, then pin 10 LOW, then pin 33 LOW.
8. Pump-clear test: set pin 33 HIGH (expect FF1.Q H). Stop the pump. Expect FF1.Q L within 90 ms. Restart the pump.
9. Current cross-check: with the pack bonded and the board load only, expect |I_PACK1 - I_PACK2| at or below 0.15 A
   (TODO(calibrate)). A common-mode zero (shorted Kelvin pair) passes this step; `ERR_IPACK_PLAUS` covers it.
10. VOK check (Stage 2, Idle only, MOT_PWR HIGH so that V-MOT tracks VBUS): wait until both CH bits read L on settled
    readings for 100 ms, with a deadline of 1 s from the Idle entry. At the deadline the result is "deferred", not
    "fail". A Finish or a State-98 `Q` at the peak of a brake pulse settles by 0.48 s (calc7 section 11). The k_idle
    refresh of `ERR_VOK_STUCK` starts only after this settle (Table 16, `ERR_VMOT_CAL`). With MOT_PWR LOW (an Idle entry
    through the State-98 `Q` key, ino:9279) step 10 and the k_idle refresh do not run, the result is "deferred", and
    step 10 and the refresh run when MOT_PWR next reads HIGH (revision 12).

Steps 6 and 7 are valid only when |I_PACK1| is at most 0.5 A; otherwise the sub-state waits up to 2 s by deadline and
then records "deferred" (calc4 section 5). The return-resistance baseline is not a self-test step; it runs in Run
whenever I_PACK1 exceeds 5 A (section 12.6).

During steps 4-7 the pack is in the charge mode for at most a few iterations per step; during step 8 for at most 90 ms
(until the pump clear). In each case the board load flows through the Ag105 sense in reverse, at well below the U_C1
threshold, and the VESC command is held at 0 A. The whole sequence takes about 360-460 ms per Idle entry
(`calc/cc_completeness_calcs.py` section 1: 424-430 ms at the 76 ms hang-to-off maximum; 2.4 s with the 2 s validity
deadline) and delays the first window by that time; it never
delays traction by more than the abort time.

### 9.4 Idle and Run traction

The pack is bonded. Firmware toggles pin 34 every iteration after `detectFaults()`, keeps pins 33, 35 and 10 LOW, and
keeps REGEN and FC_CHARGE LOW. MOT_PWR stays HIGH per the Death-5 doctrine. The share loop, the selector and the
existing bring-up are unchanged, except that in State 2 in closed loop with no session the mode manager overrides the
share setpoint from a purge prediction until the declared purge end (section 9.11.3), that at standstill with a window
request it substitutes an in-band value for an EMS rail command (section 9.11.6), and that pins 27 and 28 belong to the
mode manager over the SC-8 interval (section 12.4 item 7, revisions 9 and 10). `ERR_VOK_STUCK`, `ERR_SGND_OPEN`, `ERR_IPACK_PLAUS` (both forms), `ERR_VCHG_FED`, `ERR_VCHG_SENSE` (a), `ERR_MOD_FED`,
`ERR_MOD_SENSE` and `ERR_CELL_MISMATCH` run every iteration.

### 9.5 Regen window (Stage 2)

The window runs with MOT_PWR HIGH throughout. The VESC command path is not delayed: firmware sends the brake command at
once, and the changeover proceeds in parallel.

Entry conditions (all true): `PACK_RETURN_CHANGEOVER` and Stage 2 enabled; State 2; the command-step arm is met (the
commanded motor current at or below -2 A on two consecutive drive-controller samples, 4 ms, ruling OR-V'; a +/-0.1 A
dither never meets it); the window rate limit allows a transition (at most 20 per minute); no charge trip is latched;
the boot self-test has passed this power cycle and the latest Idle-entry self-test is neither deferred nor failed
(revision 12); an `ERR_IPACK_PLAUS` evaluation has passed this power cycle (BT_CURRENT at or
above 0.4 A with I_PACK1 discharge at or above 0.25 A for 100 ms, section 12.6); `ERR_VCHG_FED`, `ERR_VCHG_SENSE`,
`ERR_MOD_SENSE`, `ERR_MOD_DRAIN`, `ERR_MOD_DUMP_ON`, `ERR_CELL_MISMATCH` and `ERR_VMOT_CAL` are clear and V_chg reads
below 11 V outside its blanking; the
module is cold (pin 8 MOD_COLD_N LOW for at least 20 ms); the ladders give settled readings; BAL_OK is H; pin 9 (`CBAL_DISABLE`) LOW (CC-8); I_PACK1
discharge is below 1.5 A; V_batt is below the restart level of 8.0 V (Ag105 DS p.5) until gate S0-8b shows that the
module charges from a cold power-up above 8.0 V (every regen pulse is a cold start); the estimated I_L is at or below
0.75 A (section 7.1); a readback of reg 0x00-0x02 has matched Table 5 in this power cycle, in an FC window or a
configuration check (section 9.7a); the eFuse-blocking probe has passed this power cycle and gate C-2 has qualified it
(a void or deferred probe refuses regen windows); a dump check (section 9.7b) has passed this power cycle (the
configuration check carries one); no FC window or configuration check is open (the mode manager passes
through `CHG_BONDED` between window types; no direct transition).

Entry sequence:

1. Set pin 10 LOW (regen profile). The module is cold (pin 8 LOW for at least 20 ms, the node dumped below 0.5 V), so
   the profile takes effect at its next power-up.
2. Release pin 5 (MPPT_DISABLE, open-drain) HIGH (MPPT enabled, so that the 18 V threshold applies; ruling OR-4). The
   mode manager is the only writer of pin 5 while the window is open (section 12.4 item 7).
3. Set pin 33 HIGH. Hardware: FF1 sets; both S_GND turn off within 0.1 ms; S_CHG turns on after about 0.1 ms; X
   releases D-BT-SQ about 5 ms later and D-BT-SQ turns on t_D_ON later.
4. Within 4 iterations (30 ms wall-clock cap, section 7.7), confirm a settled reading of FF1.Q H and both SG bits L.
   When the check fails, run the exit sequence and latch `ERR_CHG_ENTRY`.
5. Run the sense-path check of section 9.3 step 5 (one iteration). When it fails, run the exit sequence and latch
   `ERR_CHG_ENTRY`.
6. Set pin 30 HIGH. Hardware: RGQ follows VOK; EN_RG_X stays clamped while VOK is false.

Under the retired fw v35 drive law pin 30 was HIGH 5.4-7.4 ms after the braking command, and the VOK assert of the
first pulse followed 8.5-16.6 ms after it (calc5 section 7). Under the fw v37 law the arm itself comes 4-26 ms after a
decel step (section 7.8). A host test pins the arm-to-pin-30 latency at 10 ms or less; gates S0-6 and V2-4 measure the
latency from the first command below -0.1 A. The iteration that writes the pin-33 edge defers the SD drain and the
Ag105 I2C poll to the next iteration (section 12.4 item 5).

Hold (hardware only): when V-MOT exceeds the VOK assert level, the clamps release EN_RG_X, D-BC-RG turns on after
t_D_ON, and the eFuse enable rises at once (RGQ term). The eFuse output ramps when VCHG-IN exceeds 12.38-12.88 V. The
Ag105 starts on the regen profile (1.75 A, 18 V threshold). When V-MOT falls below the release level, the eFuse turns off,
EN_RG_X is clamped and Q_MD dumps the module node, so the next pulse repeats the start from a cold module (provided
that V-MOT takes longer to recover the 0.74 V hysteresis than the dump takes to the U_MS edge: 2.64-6.32 ms against
1.10-3.02 ms at the recorded 117-280 V/s; the rebound rate is BENCH, V2-4, BT4-TR-06). An eFuse input above the U_IM trip (1.51-1.98 A) at any time clears FF1 through U_IM
and ends the window.

Firmware duties during the hold: every iteration, decode the ladders and apply the consistency rule of section 12.4
item 4; poll reg 0x06 while the eFuse output is up, excluding invalid reads (section 12.5); apply `ERR_PROFILE_OC` and
the I_L hold condition of section 7.1; read back reg 0x01 once per window while EF_EN is H and V_chg is at or above
13.5 V (a valid settings read other than 0x08 latches `ERR_AG105_CFG`); apply the positive control of U_MS
(`ERR_MOD_SENSE` (b), section 12.6). Its anchor is the second consecutive V_chg reading at or above 13.5 V after a
reading below 13.0 V, all three taken while EF_EN is H, and pin 8 must read HIGH by the later of 10 ms and 4 iterations
after the anchor (cap 30 ms). The anchor is an observed crossing for two reasons: EF_EN rises at the VOK assert, t_D_ON
before VCHG-IN is fed (CC-1), and from the second pulse of a window VCHG-IN can still hold 13.5-14.5 V from the previous
pulse (bleed tau 0.984 s; `calc/bt4_logic_seq_enum.py` section 3, calc7 section 5). A residual at or above 13.0 V is
above the eFuse UVLO, so the eFuse start drains VCHG-IN into the cold module node down to its UVLO (at most 12.10 V)
about 1.24 ms after the assert, and a reading below 13.0 V then precedes the real feed. A pulse with no observed
crossing is not evaluated. Apply the pin-38 plausibility rule `ERR_VCHG_SENSE` (section 12.6), whose rule (a) runs in
every iteration of every mode. A GENSTAT
Thermal Shutdown ends the window without a latch (section 12.5 item 4). The regen powered interval is the pulse rise plus the
VESC-stop tail, 84-416 ms per pulse (`calc/bt5_transient_sim.py` section 1; revision 7 used the 19-47 ms rise only,
BT5-TR-04), which is shorter than `AG105_SETTLE_MS` (500 ms) but can exceed the 100 ms persistence of
`ERR_ISO_MISMATCH`. `ERR_ISO_MISMATCH` is evaluated in FC windows only (row F1), so in a regen window F1 and F19 are
detected by hardware only (U_C2, U_IM, eFuse I_OL); extending it into regen windows is a Stage-2 option after V2-4.

Exit conditions (any): the brake demand has ended for the 200 ms release dwell; a positive motor-current request
(section 9.6); any fault; a ladder mismatch; the estimated I_L above 0.75 A for 20 ms; the window has lasted 30 s
(TODO(calibrate)).

Exit sequence:

1. Set pin 30 LOW. Hardware: RGQ falls, so the eFuse turns off within microseconds (the source term no longer needs VOK
   to fall), and D-BC-RG is clamped by the firmware level as well as by VOK. Exit hold check (revision 8): in the
   iteration of the write and immediately before it, read ladder A (raw decode), pin 8 and V_chg. The check runs only
   when EF_EN reads H, pin 8 reads HIGH and has read HIGH continuously for at least 2 ms in the current EF_EN-H
   interval (a `micros()` stamp), and V_chg reads at or above 13.5 V. It then samples pin 8 50 us and 150 us after the
   write; a LOW sample latches `ERR_MOD_SENSE` (c) and voids the last eFuse-blocking probe. Under these conditions the
   node is fed at the write and lies within the eFuse drop of V_chg (at least 13.4 V; 2 ms after the U_MS edge a ramping
   node is at least 17.5 V or at its feed level), so a healthy node holds U_MS HIGH for at least 170 us at C_mod 47 uF
   and 361 us at 100 uF (calc8 section 1), while a pin 8 that follows EF_EN (row F55) falls within microseconds. An exit
   between regen pulses (EF_EN L; the node was dumped at the VOK release while VCHG-IN still holds 13.5 V or more for
   175-193 ms) and an exit in the cold span after a re-assert (pin 8 LOW) are not evaluated. Revision 7 armed the check
   on a pin-8 HIGH read anywhere earlier in the window and on the last settled V_chg, and false-latched on 21.4-37.0 %
   of healthy regen exits (FM5-1, BT5-LS-01, BT5-TR-01). The V_chg term stays: with EF_EN H and the eFuse in UVLO (in
   revision 8 the FC-window exit on V_chg below 13.0 V; in revision 9 the State-99 teardown after
   `ERR_FC_ONLY_COLLAPSE`, whose feed drop the term therefore excludes) the node can sit just above the U_MS edge and
   falls in 21-117 us (calc8 section 1).
2. Wait until pin 8 (MOD_COLD_N) reads LOW on two successive iterations (T_drain, measured). Hardware: EF_EN is L, so
   Q_MD dumps the module node through R_MD; the module stops converting below its threshold or its 11 V lockout with
   the sense still in the return path (1.3-2.9 ms from 21.5 V at C_mod 100-221 uF, calc6 section 3). When the two LOW
   reads have not occurred by T_drain,max (the later of 10 ms and 4 iterations after step 1, capped at 30 ms; calc7
   section 5), latch `ERR_MOD_DRAIN` (Q_MD or R_MD open, or an extra capacitance), and continue. The wall-clock 10 ms of
   revision 6 false-latched when the deferred SD drain and Ag105 poll made the first drain-wait iteration longer than
   7.7-8.9 ms (BT4-LS-03).
3. Set pin 33 LOW. Hardware: FF1 clears; both S_GND turn on within about 0.3 ms; X disables D-BT-SQ 0.3-0.7 ms later.
4. Within 4 iterations (30 ms wall-clock cap), confirm a settled reading of FF1.Q L, EF_EN L and both SG bits H. When a
   check fails, stop the pump (the hardware clears FF1 in 43-76 ms even if the pin-33 path has failed), drop every
   charger feed and latch `ERR_CHG_EXIT` (State 99).
5. Set pin 5 LOW once pin 8 has read LOW for 20 ms (the cold-module rule of section 12.4 item 2; about 23 ms after the
   feed drop, `calc/cc_completeness_calcs.py` section 6, CC-2). The bonded confirmation of step 4 does not wait for
   this write, so traction is not delayed by it; the mode manager holds `CHG_EXITING` only for the pin-5 write.

The revision-2 wait for `I_PACK` below 0.1 A before bonding is not used. On a commanded exit the eFuse is off, and the
module node is below 8.69-9.15 V, before the S_GND gates rise: the module has stopped converting before the bond and
is cold, whatever its threshold behaviour and idle current (revision 5 relied on the module converting down to its
11 V lockout, which the threshold behaviour of S0-5 contradicts, `calc/bt3_transient_sim.py` section 2). On a hardware
trip (U_C1, U_C2, U_IM, D5, BQ OUT) FF1 clears first, so the module can convert from its input capacitance for up to
about 1.1 ms after the S_GND gates rise, while Q_MD dumps the node in parallel (row F10). The residual overshoot on VCHG when D-BT-SQ opens with current
still flowing is gate S0-3, which is a hard precondition of any charge session.

### 9.6 Traction request inside a regen window (ruling OR-2')

With MOT_PWR HIGH a positive motor current draws bus power from the BT boost, and in the charge mode that pack current
returns through the Ag105 sense in reverse. U_C1 bonds the pack in hardware above 2.52-3.50 A, but firmware does not use
the trip as a normal path. When `motorControl()` requests a positive current inside a window:

1. Hold the VESC command at 0 A until step 3.
2. Run the exit sequence of section 9.5 (steps 1-4).
3. Release the motor command when the exit confirmation of step 4 is complete.

The traction delay is the measured drain plus one iteration for the pin-8 confirmation plus two iterations for the
settled reading: 4.7-6.3 ms at the median loop and 5.3-6.9 ms at the p99 loop for C_mod 100-221 uF, one iteration
more when the first read straddles an edge (calc6 section 9); the cap is T_drain,max (the later of 10 ms and 4
iterations, at most 30 ms) plus the 4-iteration confirmation. Ruling OR-2' decides whether the drive-law state is frozen during the hold; the default is no change to
the drive law.

### 9.7 FC window (State 1 or State 98; State 2 at standstill)

The FC window is permitted with the vehicle parked in Idle (State 1) or in State 98 (**variant P**), and, from revision
9, in State 2 at standstill between purges (**variant D-s**, ruling OR-O', build flag `IC1_FC_RUN_STANDSTILL`). A window
in motion (**variant D**) is not permitted (ruling OR-DM, section 9.11.7): the FC budget leaves 0.17-0.28 A of headroom
at the FC profile (Table 8), 0.06-0.33 A over the pack-voltage and efficiency range (out s1), and a traction load above
it on the FC-only bus would latch `OC_FC` on one sample. A drive cycle runs in State 2 throughout, stops included
(ino:7919-7959), so variant D-s is the form that reaches the drive-cycle stops. Section 9.11 gives the purge sequence,
the re-entry, the safe collapse and the EMS interface.

The entry conditions are: either `mainState` 1 or 98 with motor command 0 and |v_actual| below the standstill
threshold (TODO(calibrate)), or (variant D-s, `IC1_FC_RUN_STANDSTILL` 1) `mainState` 2 with the commanded speed
`v_setpoint` 0, |I_cmd| at or below the standstill current I_still and |v_actual| below the standstill threshold for at
least T_still (I_still above the measured standstill command dither, T_still and the threshold TODO(calibrate) at
W2b); an FC window request (section 9.11.6: the explicit request flag of revision 11); `FC_CHARGE_ALLOWED`; the existing
F1 conduction gate (in State 2 after the fw v28 F1 disarm of section 9.11.6, revision 10; in State 1 and 98 after the
guarded FC_BUS release of section 12.4 item 9, revision 11); FC_REG_ENABLE (pin 3) and BT_REG_ENABLE (pin 4) both HIGH
on two settled iterations (revision 11, BT7-LS-02: `busHotPlugUnsafe(BT_REG_ENABLE)` is false with the BT boost
disabled, ino:13043-13045, so exit step 4 would otherwise re-close BT_BUS onto a disabled TPS61288; refusal code 11);
V_bus at or above 13.5 V; BAL_OK H; pin 9 (`CBAL_DISABLE`) LOW (CC-8); V_batt below 8.0 V until gate S0-8b shows that the module charges
from a cold power-up above 8.0 V; V_batt at or above `LIMIT_V_BATT_MIN` 7.4 V (ino:2096) on two settled iterations,
read directly and independent of the UV_BATT arming (revision 10, BT6-TR-02: a pack that boots below the 7.8 V arm
level never arms UV_BATT, ino:2261-2267, ino:7283-7294); `ERR_VCHG_FED`, `ERR_MOD_SENSE`, `ERR_MOD_DRAIN`, `ERR_MOD_DUMP_ON`,
`ERR_CHG_PATH_OPEN` and `ERR_CELL_MISMATCH` clear; V_chg below 11 V on two settled iterations (revision 9, the literal
reading: the 1.0 s `ERR_VCHG_FED` blanking delays the latch, not the entry, section 9.11.4); a dump-check pass in this
power cycle (section 9.7b, revision 8; from revision 11 the first request of a power cycle without a pass starts the
dump check in the state in which the request arrives, State 2 at standstill included); the module cold (pin 8 LOW for at least 20 ms); BT_CURRENT below 0.2 A (entry
step 5); no regen window open; the purge permit of section 9.11.2 (a predicted time to the next onset of at least
1.282 s in every state, calc10 section 3); and V_fc at or above `V_FC_ARM_THRESH` 7.0 V on two settled iterations (ino:2278). Revision 9
removes the fw v33b FC-only lockout (`fcUvLockoutActive()`, `UV_FC_PURGE_LOCKOUT_MS` 30 s, ino:2256, ino:15493-15500)
from the charge path, because against the 10.34 s purge period it refuses every window on a running H-20; the purge
permit replaces it (ruling OR-P). The lockout still refuses an FC-only source selection; the window does not use the
selector (entry step 5 drops BT_BUS through the mode manager). `chargingControl()` is not called in Idle (ino:7888), so
the State-1 window needs the new call site of section 12.4 item 6; in State 2 the existing call serves the standstill
window, and the purge sequence itself runs in `chgModeTick()`, which runs every iteration in every state. Under
`PACK_RETURN_CHANGEOVER` the State-2 cruise FC branch of `chargingControl()` (ino:15503-15506) stays compiled out
(section 12.4 item 6).

Entry sequence:

1. Set pin 10 HIGH (FC profile: 1.25 A, 13.82 V threshold, BENCH). The module is cold (entry condition).
2. Release pin 5 HIGH (open-drain).
3. Set pin 33 HIGH; confirm a settled reading of FF1.Q H and both SG bits L within 4 iterations (as section 9.5
   step 4).
4. Run the sense-path check of section 9.3 step 5.
5. Immediately before the BT_BUS drop, re-test in the same iteration that FC_BUS (pin 27) reads HIGH, that it is outside
   `busSwitchBlanked()`, and that `shareSpCutFC`, `shareIsoFC` and `shareBatteryOnlyArmed` are all clear; otherwise run
   the exit sequence and refuse the window with code 11 (revision 10, BT6-LS-02: a share-latch cut of FC_BUS during
   steps 1-4 would otherwise leave the bus with no source at this step). Drop BT_BUS through the existing guarded path,
   then wait until BT_CURRENT (pin 41) is below 0.2 A (timeout 20 ms:
   run the exit sequence and refuse the window). This keeps the legitimate BT current out of the D5 arming window.
   **Fixed window split (revision 11, BT7-TR-01).** In the iteration in which BT_CURRENT first reads below 0.2 A, the
   mode manager stores the two MDAC codes and k_d, freezes the share loop (`powerBalance()` returns before its filter,
   its controller and its MDAC writes; the integrator and the filter hold), freezes the fw v28 rev 4 k_d topology slew
   (ino:13863-13897), and writes one defined split: r = `DROOP_R_MAX` 0.85 at k_d = `K_DROOP` 0.30 (g_FC 0.1753, code
   717, the value that the truncating cast of `setDroopMdac()` writes, ino:15264-15265; the host test computes the code
   through `setDroopMdac()`, revision 12, BT8-TR-02, calc12 section 4), the smallest FC droop the in-band span allows. On the design chain R_FC is 0.353 Ohm and on
   the bench-scaled droop 0.094 Ohm (TODO(calibrate): the 4x design/bench droop gap, `tools/hil_plant_sim.py:467-505`,
   is open), so the window bus sits at V_chg 15.52-15.82 V at the Table-8 input power, 1.70-1.98 V above the 13.82 V
   module threshold and 1.20-1.48 V above the 14.32 V S0-4 acceptance limit, with a deliverable power of 100 % (calc11
   section 2). Without the rule a State-2 window runs the share
   loop in closed loop on the charger current (filtered total about 1 A, above the 0.25 A gate, ino:14313-14327), winds
   the output to the fw v29 clamp 0.15 (ino:14723-14726) and puts R_FC at up to 2.0 Ohm on the design chain: V_chg
   13.50-13.99 V, the module threshold binds and only 65-100 % of the input power is deliverable (bt7 sections 1-2;
   HIL campaign I charge-to-full, codes 4067/717 on every in-window row). The split is written only while BT_BUS is
   open, so the forced-split relay class of TP0053 (two sources, one forced below the conduction floor,
   ino:14302-14311) cannot arise. The same rule applies in State 1 and 98 (variant P), the dump check, the configuration
   check and the probe, so that no FC-fed session depends on the split that Idle holds.
6. Call `assertFcChargeEnable(true)`. It drops REGEN, waits 100 us, and raises FC_CHARGE (ino:12743-12778). Under
   `PACK_RETURN_CHANGEOVER` its S2 restore (an unguarded FC_BUS HIGH write when FC_BUS reads LOW, ino:12756-12760) is
   replaced by a refusal: the call returns false, the mode manager runs the exit and refuses with code 11 (revision 10).
   Hardware:
   Q_X1 clamps EN_BE_X; FCQ enables the eFuse; D5 arms 2.8-6.1 ms later. `ERR_MOD_DUMP_ON` is not
   sampled here (revision 8, BT5-LS-02): with pin 32 HIGH a module that starts inside the Stage-2 allowance of Table 8a
   draws 0.45-0.97 A at the sample time, so a fixed step false-latches. The dump check of section 9.7b has passed in this
   power cycle, and `OC_FC` (BENCH_TEST 0) and U_IM cover a dump that sticks later while the module charges
   (calc8 section 2, row F50).
7. The Ag105 starts on the FC profile. Firmware applies the positive control of U_MS (`ERR_MOD_SENSE` (b) with the
   crossing anchor and the 50 ms deadline), reads reg 0x06 at 50 Hz and, after `AG105_SETTLE_MS`, reads back
   reg 0x00-0x02.

Exit conditions (any): window end (the request withdrawn); a timely purge prediction (the predicted time to the next
onset at or below T_lead,min and, at the first iteration that observes it, at or above T_late; section 9.11.2; an
UNKNOWN transition, `purge_active` rising or a late prediction inside the window is not an exit but a latch of
`ERR_FC_ONLY_COLLAPSE`, PI-4, revision 10); fault; 30 s `FC_CHG_MAX_MS`; in State 1
or 98 any non-zero motor command or a State 1 to State 2 transition request; in State 2 a non-zero `v_setpoint` or
|I_cmd| above I_still, evaluated on the command before it reaches the VESC (section 9.11.7); |v_actual| above the
standstill threshold; GENSTAT Fully Charged on two successive valid reads (no latch; a new window waits for V_batt below
the restart level, CC-15). From revision 9, a V_chg reading below 13.0 V with EF_EN H after `chargerHasPower()` has been
true in this window is **not** an exit: it latches `ERR_FC_ONLY_COLLAPSE` (State 99) with no BT_BUS re-close
(section 9.11.5). The revision-7 commanded exit on this reading (BT4-TR-06) kept FC_BUS closed while it waited for
BT_BUS to conduct, and an FC that recovered from a purge inside that interval restarted into a sagged bus joined to V-MOT
(hazard H-R, pc section 3b).

Exit sequence:

1. Call `assertFcChargeEnable(false)`. Hardware: FCQ falls, the eFuse turns off within microseconds, D5 disarms, Q_X1
   releases EN_BE_X. Apply the exit hold check of section 9.5 exit step 1. On a traction request, hold the VESC command
   at 0 A from this step until step 3 confirms.
2. Wait until pin 8 reads LOW on two successive iterations (as section 9.5 exit step 2, deadline T_drain,max).
3. Set pin 33 LOW; confirm as section 9.5 exit step 4.
4. Re-close BT_BUS through the existing guarded path. If `busHotPlugUnsafe()` refuses the re-close, SC-1 stays active
   and `ERR_FC_ONLY_COLLAPSE` latches on the next iteration that still refuses; there is no retry loop (revision 10,
   BT6-LS-01). If BT_REG_ENABLE (pin 4) reads LOW at this step, no BT_BUS write is made and `ERR_FC_ONLY_COLLAPSE`
   latches at once (revision 11, BT7-LS-02; the S5 back-feed doctrine that every fw v37 release path enforces,
   ino:13421-13426, ino:13441-13450). In the iteration after the BT_BUS write the mode manager restores the MDAC codes and
   k_d stored at entry step 5; the share loop and the k_d slew stay frozen until the SC-8 interval ends (BT_BUS HIGH for
   the conduction bound and, after a prediction exit, the declared purge end), and then resume from their held state
   (revision 11, BT7-TR-01). The BT-only bus during a purge therefore carries the BT droop of the restored split. On a traction request, release the motor command only after BT_BUS has been HIGH for the conduction
   bound of Table 20 (31.8 ms at t_D_ON 12 ms, gate W2a), so that a launch never draws from the FC alone (revision 10,
   FM6-3; the release comes 43-47 ms after the command on the healthy chain and at most 61.7 ms on the deadline chain,
   calc10 section 8). Set pin 10 LOW and pin 5 LOW once pin 8 has read LOW for 20 ms (section 12.4 item 2, CC-2).
   On a purge-prediction exit, SC-1 reading (b) stays armed from this write until the declared purge end (section
   9.11.5).

The FC window opens BT_BUS, so the bus is FC-only for the window. A predicted purge closes the window and re-closes
BT_BUS before the onset (section 9.11.3). An unpredicted purge collapses the bus; `ERR_FC_ONLY_COLLAPSE` latches State
99 and the teardown of section 9.11.5 opens FC_BUS before the FC can recover (ruling OR-SC).

### 9.7a Configuration check and eFuse-blocking probe (Stage 2 prerequisite)

Before the first regen window of a power cycle without an FC window, the mode manager runs a configuration check in
State 1: the commissioning steps 4-8 (step 6b included) and 10-11 of section 9.2 without writes, with pin 32 LOW, under the FC-window entry
conditions except the V_batt below 8.0 V limit, which does not apply because pin 32 is LOW and the module output path
is only R_KA (about 14 mA). The check is also the positive control of U_MS (section 9.7 entry step 7). A register readback is a settings read: it is valid on any status byte other than 0xFF, whatever GENSTAT
reports (section 12.5 item 2). A mismatch latches `ERR_AG105_CFG`. `ERR_ISO_MISMATCH` is not evaluated with pin 32 LOW.
A check from the H-20 runs inside the purge permit of section 9.11.2 (ruling OR-P, revision 9), in State 1 or State 98
only, and closes on a purge prediction as an FC window does; a bench supply on J-FC remains an alternative feed.

The check ends with the **eFuse-blocking probe**, the in-service detector of an eFuse bypass (rows F11, F35, F36-M2).
Revision 6 judges it on the module-node comparator U_MS, not on reg 0x07: Ag105 DS p.14 states that all measures read
0xFF below 9 V input or while the module reports an error state, and in the probe state (VBat- open with FF1 clear,
D-BT-SQ off) a fed module is expected to report Battery Disconnect (DS p.6; Table 5 mode 2, "Disconnected Battery
Error"), so reg 0x07 is expected to read 0xFF exactly when a bypass exists (DS3-2, BT3-AG-1). The module boot time
would also put a valid read outside the 100 ms window (65-170 ms cold start, `AG105_SETTLE_MS` 500 ms).

1. With FC_CHARGE LOW and the drain of section 9.5 exit step 2 complete, set pin 33 LOW and confirm the bonded settled
   reading (FF1.Q L, EF_EN L). Pin 32 stays LOW, so D-BT-SQ is disabled and an output path exists only through R_KA
   (about 14 mA). Q_MD is ON (EF_EN L).
2. Wait until pin 8 has read LOW for 20 ms (module node cold: a measured precondition that no residual is left, which
   replaces the revision-5 T_hold of 0.5 s sized on the shortest hold-up).
3. Raise FC_CHARGE through the probe path of section 12.4 item 7 (the only bonded-mode FC_CHARGE write). Confirm V_chg
   at or above 13.5 V on two settled iterations (the feed reached the eFuse input; otherwise the probe is void, which
   refuses regen windows in this power cycle, and repeats at the next check).
4. Read pin 8 on two successive iterations. HIGH on both means that the module node is at or above 8.69-9.15 V with
   EF_EN L and Q_MD loading it: latch `ERR_EFUSE_BYPASS`. LOW on both is a pass. Mixed reads repeat step 4 once.
5. Drop FC_CHARGE at once after step 4, and within 100 ms of step 3 in every case. This feed drop is not a commanded
   exit: EF_EN is L, so the exit hold check (`ERR_MOD_SENSE` (c)) is not evaluated (Table 16, revision 8). Restore pin 32 HIGH only after
   FF1.Q has read L.
6. Re-close BT_BUS through the existing guarded path (it was dropped at commissioning step 6b), and set pin 10 LOW and
   pin 5 LOW under the cold-module rule (CC-5). The probe verdict counts only if the positive control of the same
   check (pin 8 HIGH while the module was powered) passed; otherwise the probe is void (CC-6).

A healthy eFuse leaves the node at 0 V through Q_MD. A bypassed eFuse puts the FC bus (about 16 V) on the node, and
R_MD then draws about 1.07 A from the FC bus until step 5, about 0.17 J in 10 ms (calc6 section 3). During the 1.33 ms
soft-start of D-BC-FC (CSS 5.6 nF, about 12 V/ms) the bypass also charges C_VCHG + C_EO + C_mod (122-243 uF), so the FC
bus carries 2.68-4.13 A at the peak including the aux load, and 1.23-1.34 A afterwards (`calc/bt4_transient_sim.py`
section 4). On a BENCH_TEST 0 build a real bypass can therefore latch `OC_FC` (State 99) before `ERR_EFUSE_BYPASS`;
either latch is a detection, and S0-14 and C-2b record which one fired. The configuration check runs commissioning step
7 with pin 32 LOW, so its own EF_EN rise also carries the `ERR_MOD_DUMP_ON` check and counts as the dump check of
section 9.7b. The verdict needs
no Ag105 measurement, no module boot and no I_q bound. The probe holds the bus FC-only for about t_D_ON plus three
iterations, inside the purge permit of section 9.11.2. `ERR_VCHG_FED` is blanked during the probe and for 1.0 s after it. The probe
is a qualified detector only after gate C-2 has injected a bypass (an eFuse IN-OUT jumper, then SHDN_EF tied HIGH) and
seen the latch; until then rows F11, F35 and F36(M2) carry "no qualified in-service detector".

### 9.7b Dump check (revision 8)

The dump check is the evaluation of `ERR_MOD_DUMP_ON` with pin 32 LOW, where the module output path is R_KA alone and
the module input is at most about 9 mA whatever its start speed (calc8 section 2). A pass in the current power cycle is
a precondition of every FC window and every regen window. The configuration check (section 9.7a) carries one at its own
EF_EN rise. Before the first FC window of a power cycle without a configuration check, the mode manager runs a dump
check on its own in `CHG_CONFIG`, with the register reads and writes disabled, under the FC-window entry conditions
except the V_batt below 8.0 V limit and the dump-check pass itself. It takes about 20-60 ms plus the exit
(TODO(calibrate)). The trigger is any FC-window request while no dump-check pass is recorded in this power cycle
(revision 12, BT8-LS-02: the revision-11 wording "the first FC-window request of the power cycle without a pass" never
re-ran a dump check that had ended with no verdict), with at most one attempt per stop in State 2 or per purge period in
State 1 or 98, and at most three attempts without a verdict per power cycle; after the third, code 12 stands for the
power cycle. The request may arrive (revision 11, FM7-1, BT7-LS-01) in State 1 or 98, or (`IC1_FC_RUN_STANDSTILL` 1) in State 2 under the D-s standstill conditions of section
9.7. In State 2 every D-s rule applies to the dump check as to a window: the F1 disarm before step 1, SC-8 ownership of
pins 27 and 28, the in-band substitution of an EMS rail command (section 9.11.6), the fixed window split of section 9.7
entry step 5, and the traction exit: a non-zero `v_setpoint` or |I_cmd| above I_still aborts it through the FC exit
with no verdict and with the traction hold of section 9.7 exit step 4. When the dump check passes and the request and
the standstill conditions still hold, the window follows at the same stop once V_chg has fallen below 11 V (365.6 ms
after the dump-check feed drop, calc10 section 2) and the module is cold. On the recorded Pi sessions, treated as if
their `charge_goal` were a flagged request (a counterfactual, section 9.11.6), this costs 0.7 s of the 107.3 s (106.6 s
on the nominal chain, 104.8-104.9 s on the slow chain), where the revision-10 text gave 0 s because the first request of
every session arrives in State 2 (calc11 section 1; `calc/fmea_round7_calcs_output.txt` section 1). An Idle-dwell
trigger independent of a request is not adopted: with a Pi connected, any packet with `mode_cmd` 0-3 received in State 1
sets `changeToRun` (ino:7533-7535), and the Pi's first command arrives 0.00-0.49 s into each recorded session, which is
too short for the V_fc arm, the purge permit and a dump check with its exit.

1. Set pin 32 LOW and confirm both SG bits H. Set pin 10 HIGH (the module is cold, entry condition).
2. Set pin 33 HIGH; confirm a settled reading of FF1.Q H and both SG bits L within 4 iterations (as section 9.5 entry
   step 4).
3. Drop BT_BUS through the existing guarded path; wait until BT_CURRENT (pin 41) is below 0.2 A (timeout 20 ms: run the
   exit, no verdict).
4. Take the 4-iteration mean of FC_CURRENT (pin 40). Call `assertFcChargeEnable(true)`.
5. When `chargerHasPower()` first turns true, wait 10 ms (or the S0-11 measured eFuse ramp plus 2 ms when that is later,
   revision 12, BT8-TR-01), take the 4-iteration mean of FC_CURRENT and apply
   `ERR_MOD_DUMP_ON` (Table 16). Apply the positive control of U_MS (`ERR_MOD_SENSE` (b), 50 ms deadline) in the same
   session. When `chargerHasPower()` has not turned true within 100 ms, end the session with no verdict.
6. Run the FC exit sequence of section 9.7 (exit hold check, drain, pin 33 LOW, bonded confirmation, BT_BUS re-closed,
   pin 10 LOW under the cold-module rule). Restore pin 32 HIGH only after FF1.Q has read L.

A pass is recorded when step 5 shows no step above 0.4 A, the positive control has passed and the exit has confirmed.
The session also evaluates `ERR_MOD_SENSE` (c) with the node fed at the write, so a pin 8 that follows EF_EN (row F55)
latches at the first dump check or configuration check of a power cycle. A stuck dump can instead trip U_IM or the
eFuse start into overload at step 4 (`ERR_CHG_TRIP`, row F50); either latch is a detection. On the vehicle the dump
check needs the same feed as an FC window: the H-20 inside the purge permit of section 9.11.2 (revision 9), or a bench
supply on J-FC. It runs in State 1 or State 98, or (`IC1_FC_RUN_STANDSTILL` 1) in State 2 under the D-s standstill
conditions (revision 11). Its exposure in State 2 is no larger than that of a D-s window: pin 32 is LOW, the module
output path is R_KA alone (module input at most about 9 mA, calc8 section 2), and the bus is the same FC-only standstill
bus. A window is refused with code 12 only while no pass is recorded and the dump check cannot run or has ended with no
verdict (Table 25).

### 9.8 Finish (State 3)

Run the regen or FC exit sequence if a window stands. Keep pin 33 LOW, pin 30 LOW and FC_CHARGE off. The pump may
continue.

### 9.9 State 99

1. Set FC_CHARGE LOW and REGEN LOW.
2. If a window was open, wait until pin 8 reads LOW on two successive iterations (deadline T_drain,max), then set pin
   33 LOW. Set pin 32 LOW (revision 6:
   D-BT-SQ is not needed in the bonded mode, and a dead LB rail would otherwise leave it on pin 32 alone, row F51). Hardware: eFuse off within 1.5 us (already off after step 1
   on a commanded path), bonded within about 0.3 ms.
3. Under `PACK_RETURN_CHANGEOVER`, remove only the two drain actions of the existing teardown: the
   `assertFcChargeEnable(true)` call in phase 0 (ino:8316), and the `assertFcChargeEnable(false)` call and the
   `REGEN_ENABLE` HIGH write in phase 1 (ino:8323-8324). Keep every other phase-0 and phase-1 statement in its current
   order: `ag105CommissionAbandon()`, `commandMotorCurrent(0)`, both bus switches LOW, the flag resets, the 10 ms dwell,
   then `MOT_PWR_ENABLE` LOW. Phase 2 then sets REGEN LOW, MPPT LOW and both boosts LOW. With the eFuse off the drains
   would discharge only into the 20 uF on VCHG-IN, so they provide no bleed; VBUS and V-MOT decay through their existing
   bleed resistors. The motor command is 0 A and both bus switches and MOT_PWR are LOW before the first `*_REG_ENABLE`
   LOW write, so no energized path points into a disabled boost (ino:8251-8255, ino:8334); the MOT_PWR-LOW time of
   t0 + 10 ms that `test/test_main.cpp:22547` pins is unchanged.
4. Stop toggling pin 34 once phase 3 is reached.

Steps 1 and 2 run in phase 0 as a non-blocking sub-step of `chgModeTick()`, beside the existing 10 ms dwell. The phase
timeline does not wait for the pin-8 reads: pin 33 LOW is written at the second LOW read or at the deadline, whichever
comes first, and pin 32 LOW follows it. The MOT_PWR LOW time of t0 + 10 ms is therefore unchanged; a write-log host test
covers State 99 entered from both window types (CC-B13).

### 9.10 Hardware trip, reset, brownout, hang and cable faults

| Event | Hardware response | Firmware response |
|---|---|---|
| U_C1, U_C2, U_IM, D5, BQ29200 OUT, or the OUT fly-wire open | /CLR LOW: FF1 clears; eFuse off within about 76 us (comparators) or at once (BQ OUT); bonded within about 0.3 ms; the module converts from its input capacitance for up to about 1.1 ms (row F10) | Ladder shows FF1.Q L while pin 33 is HIGH: latch `ERR_CHG_TRIP` with both ladders, I_PACK1, I_PACK2 and V_PACKN (the comparator outputs are not on the ladders); production builds enter State 99 (ruling OR-E) |
| eFuse overload latch-off | eFuse off; FLT LOW | Ladder bit 2: latch `ERR_CHG_TRIP` |
| Loop hang | Pump stops: FF1 clears in 43-76 ms; the RTWDOG reset (ruling 5) puts pin 33 high-Z, which clears FF1 at once | - |
| Teensy reset or brownout | Pin 33 high-Z: U_P33 input on R_P33 reads LOW: FF1 clears at once; eFuse off at once; bonded within about 0.3 ms; pump stops | Boot sequence |
| 3V3 lost | LVC outputs high-Z (Ioff); SHDN_EF on R_SDP 22 kOhm (0.22 V): eFuse off; FF1Q_SB on the Q_A pull-downs: bonded; VOK comparators and pull-ups unpowered; pin 30 undriven, so D-BC-RG is on its own pull-down. This holds for a rail that is absent; a slow collapse through 0.84-1.57 V is row F45 (gate B11d) | Teensy also unpowered |
| LB 3V3 tap open, Teensy running (row F51) | Bonded (FF1Q_SB on R_PA) and eFuse off (SHDN_EF on R_SDP); the cross-lock X loses its sources, so D-BT-SQ follows pin 32; R_UPk and R_BPk pull OKk_N and BPk_N to a dead rail, so the four D-BC-RG clamps release and D-BC-RG follows pin 30 (fail toward permit) | Both ladders decode code 0: `ERR_CHG_LADDER` within 3 iterations sets pin 32 LOW at once (code 0 means that the cross-lock is lost) and ends any window (pin 30 LOW); for any other ladder mismatch the commanded exit runs first and pin 32 LOW follows the bonded confirmation (section 12.4 item 4); State 99 also sets pin 32 LOW. Exposure: at most 3 iterations of D-BC-RG on pin 30 with the eFuse off (gate B11e) |
| 5V lost | Pump driver unpowered: FF1 clears in 43-76 ms. VOK is unaffected (3V3). The 5V rail is also the Teensy VIN (facts_board section 6.1), so this row applies only with the Teensy powered from USB; on the pack alone it is the "Teensy reset or brownout" row (CC-13) | `ERR_CHG_TRIP` |
| SB signal cable open, outside a window | Q_A gates on R_PAk: both S_GND ON; Q_C off: S_CHG OFF | SG bits read "not enhanced" while bonded is commanded: windows refused |
| SB signal cable open, inside a window | Both S_GND ON, S_CHG OFF; FF1 stays set and the charger stays powered: the sense is bypassed as in F1 on both channels; U_C2 (the KS pair is a separate cable) clears FF1 at 2.65-3.64 A; eFuse I_OL | The SG bits match the charge mode, so the ladder cannot see it. `ERR_ISO_MISMATCH` (FC window, 100 ms) or `ERR_CHG_TRIP` after the U_C2 trip; V_PACKN reads about +3.3 V (pin 23 open), which `ERR_PACKN_RANGE` latches |

### 9.11 FC windows between purges (revisions 9 to 11)

#### 9.11.1 Rulings, scope and the fixed order

This section applies the operator rulings of 2026-11-08 (section 17: OR-P decided, OR-SC, OR-O'). Firmware does not
allow FC charging during a purge or in the interval that leads up to it, and shifts the share toward the battery before
the purge where the share loop runs. FC charging resumes between purges when the EMS requests it. The purge predictor
is the operator's design and is outside the scope of this document; it is taken as ideal. This section therefore
states the interface that the predictor must satisfy, the sequence that the isolation firmware runs on a prediction,
the re-entry after the purge, and the safe collapse on an unpredicted purge. The purge figures are those of
facts_prior section 7 only: period 10.34 s, duration 100-140 ms with +/-20 ms per edge, floor about 1 V.

The order of the pre-purge sequence is fixed by the isolation. In an FC window Q_X1 holds BT_BUS open
(EN_BE = p28 AND NOT FCQ, section 6 item 9), because in the charge mode a closed BT_BUS would let the BT boost draw from
the pack through the Ag105 sense in reverse and recreate the bus-charger-pack-BT boost loop (section 9.6). The share
shift toward the battery therefore cannot start inside a window. The order is: window close (feed drop and cold-module
drain), bond, BT_BUS re-close, share shift, purge, shift back, window re-entry with an Ag105 cold start. At a
standstill load (variants P and D-s) the share loop does not run (State 1 and 98) or holds its split below the
0.25 A gate (State 2), so the BT_BUS re-close is the whole shift and no override or shift back is written (revision 10,
section 9.11.3 step 5).

#### 9.11.2 Predictor interface

The predictor delivers two quantities to `chgModeTick()` in every iteration:

- `purge_tto`, the predicted time to the next purge onset, or the value UNKNOWN;
- `purge_active`, TRUE from the onset to the end of the purge that the predictor declares.

The **purge permit** of an FC-fed session (FC window, configuration check, dump check, probe) is `purge_tto` at or above
the admission horizon of Table 20 with `purge_active` FALSE. A **purge prediction** is `purge_tto` at or below the lead
time that applies (PI-1). A prediction is **timely** when the first iteration that observes it reads `purge_tto` at or
above **T_late = 61 ms**, the worst conduction time of the exit chain counted from that iteration (calc10 section 1);
otherwise it is **late**. The requirements on the predictor are as follows:

- **PI-1 (lead time, keyed on load; revision 10).** Every onset is predicted at least T_lead,min = 80 ms ahead whenever
  an FC-fed session can be open or is open: State 1 and 98, and State 2 at standstill (variant D-s). In those cases
  ruling (1) is satisfied by the BT_BUS re-close: below the 0.25 A gate the share loop holds or freezes the MDAC split
  (ino:14287, ino:14380-14385, ino:13746; calc10 section 4). T_lead,nom = 290 ms applies only in State 2 while the
  share loop runs in closed loop (filtered total at or above 0.25 A, ino:14313-14327) and no FC-fed session is open;
  there it bounds the share override of section 9.11.3 step 5. A prediction with a lead between 80 ms and 290 ms in that
  case leaves the share shift incomplete; the two source pairs stay closed, and no fault results. Table 20 gives the
  derivation.
- **PI-2 (end of purge).** The predictor declares the end of each purge. Firmware also requires V_fc at or above
  `V_FC_ARM_THRESH` 7.0 V (ino:2278) on two settled iterations before an override ends and before a re-entry. SC-1
  reading (b) stays armed after a prediction exit until this end (section 9.11.5, revision 10).
- **PI-3 (horizon).** `purge_tto` is valid up to at least the admission horizon (1.282 s, calc10 section 3), so that
  the predictor does not admit a window that cannot carry 1.0 s of charge current before the next lead time begins.
- **PI-4 (fail closed; revision 10).** `purge_tto` is UNKNOWN whenever the predictor does not track the stack: before
  its first purge after an H-20 start and after a reset; UNKNOWN refuses every FC-fed session. Inside a session that
  holds BT_BUS open (from entry step 5 to the BT_BUS re-close write of the exit), an UNKNOWN transition, `purge_active`
  rising, or a late prediction is an unpredicted onset: it latches `ERR_FC_ONLY_COLLAPSE` (State 99) with no BT_BUS
  re-close, and the exit sequence of section 9.7 is not started. In `CHG_ENTERING` before step 5 (BT_BUS still closed)
  the same events abort the entry through the exit sequence. Revision 9 let UNKNOWN close an open session "as a
  prediction does"; on a recognised onset that re-entered the rejected policy E1 (BT_BUS written after the onset in
  886 of 2430 cases, turn-on peaks to 4.46 A, 15 HAZARD cases at 80 ms, `calc/bt6_logic_seq_enum.py` section 3). With
  the latch the same grid gives OPEN in 4860 of 4860 cases (calc10 section 5).
- **PI-5 (sources without purges).** A source that shows no purge-class dip (a bench supply on J-FC for gates C-2b and
  W1) is reported as "no onset inside the horizon", so that the bench gates can run with the same firmware.
- **PI-6 (loop budget).** The predictor runs in `loop()` context and obeys the blocking rule of section 12.4 item 5; a
  stall of about 40 ms stops the pump and clears FF1 in hardware.
- **PI-7 (error band).** The values above contain no allowance for prediction error. A real predictor adds its own
  error band to T_lead,min and T_lead,nom and to the declared end (operator's responsibility, ruling OR-P).

On a timely prediction the isolation firmware does the following: it refuses every new FC-fed session; it runs the
exit sequence of section 9.7 (or of section 9.7a/9.7b) for an open session; in State 2 with the share loop in closed
loop and no session open it starts the share override (section 9.11.3 step 5); and it records a `PURGE_LEAD_SHORT`
event when `purge_active` rises before BT_BUS has been HIGH for 31.8 ms (the conduction basis of Table 20). On a late
prediction, an UNKNOWN transition or `purge_active` rising inside a session that holds BT_BUS open, it latches
`ERR_FC_ONLY_COLLAPSE` (PI-4).

Table 20 gives the lead-time requirement.

Table 20. Predictor lead time T_lead (calc10 section 1; calc9 section 1; seq sections 2-4).

| Tier | Condition at the onset | Typical | Worst healthy | Deadline-based, any gap placement | Requirement |
|---|---|---|---|---|---|
| Hard (every FC-fed session; P and D-s) | Feed off, module cold, pack bonded, BT_BUS conducting | 33.6-34.7 ms | 47.0 ms | 61.7 ms from the prediction; 60.6 ms from the observing iteration | **T_lead,min = 80 ms**; T_late = 61 ms |
| Full (State 2, closed loop, no session) | Share override complete | 100-168 ms (ESTIMATE) | 274.1 ms | 288.7 ms | **T_lead,nom = 290 ms** (upper bound) |
| Admission horizon | A window can carry 1.0 s of charge current before the next lead time | - | - | entry 201.8 ms + 1.0 s + lead | 1.282 s |

The worst healthy chain uses the p99 loop, one 9.76 ms iteration gap, the slow module node (221 uF to the 8.69 V edge)
and t_D_ON 12 ms (seq section 2). The deadline-based chain lets the drain wait and the bonded confirmation each run to
its deadline and places the one 9.76 ms gap at every position (before the feed drop, in the drain, in the
confirmation): the worst conduction is 61.7 ms after the prediction, whichever position the gap takes, and 60.6 ms after
the iteration that observes the prediction (calc10 section 1; revision 9 placed the gap inside the waits only and
stated 59.6 ms, which the gap before the drop exceeds by 2.1 ms, `calc/bt6_logic_seq_enum.py` section 2). T_late is the
second figure rounded up. T_lead,min is T_late plus one gap before the observing iteration, rounded up to 10 ms: an
ideal announcement at 80 ms is observed at 70.2 ms or more, 9.2 ms above T_late, and conducts 18.3 ms before the
onset. The conduction term is t_D_ON plus the soft-start of D-BT-EN
onto a live bus, (V_IN/35) x (CSS/0.0023 - 100) us = 19.77 ms at CSS 100 nF and 15.95 V (ino:4853-4860): 27.8 ms at
t_D_ON 8 ms and 31.8 ms at 12 ms. The 8 ms t_D_ON alone understates the re-close, and the 13 ms of Table 11 applies to
D-BT-SQ (CSS 5.6 nF), not to D-BT-EN. The RT1987 datasheet gives no t_D_ON maximum (open item 2), so each millisecond of
t_D_ON above 12 ms adds one millisecond to both requirements; gate W2a measures it. The full tier uses the dark-channel
handoff slew of the share loop (175 ticks at 0.002 and 18 ticks at 0.02 per tick, ino:3242, ino:3288-3325), 258.8 ms
at the p99 loop; the demand sheet's 108.3 ms rested on a 20-50 ms ESTIMATE of the shift and is superseded (Appendix G).
The walk assumes a 0.85 start and a 0.15 end; the in-band minority clip lifts the end to lo = 0.125/I_tot
(ino:14581-14583), and an output already at the fw v29 clamp needs no walk, so 290 ms is an upper bound (revision 10).

#### 9.11.3 Pre-purge sequence

On a timely purge prediction the mode manager runs the following steps. Steps 1-4 are the FC exit sequence of section
9.7 and do not change.

1. FC_CHARGE LOW through `assertFcChargeEnable(false)`, with the exit hold check. The eFuse turns off within
   microseconds and the charger input (0.82-0.93 A of bus current, out s1) leaves the FC at once.
2. Drain wait: pin 8 LOW on two successive iterations (deadline T_drain,max, `ERR_MOD_DRAIN`).
3. Pin 33 LOW; bonded confirmation within 4 iterations (30 ms cap, `ERR_CHG_EXIT` and State 99 on a failure).
4. BT_BUS re-closed through the guarded path (`busHotPlugUnsafe()`, ino:13043). D-BT-EN conducts t_D_ON plus its
   soft-start later.
5. **Share shift (revision 10: State 2 in closed loop only).** **P and D-s:** no override is written. In State 1 and 98
   no share loop runs (`powerBalance()` is called in State 2 only, ino:7826-7869, ino:7944-7950). In State 2 at
   standstill the filtered total after the feed drop is the auxiliary load: below `SHARE_I_TOT_MIN_A` 0.075 A the loop
   returns frozen before its filter (ino:3116, ino:14287; the Pi bags show 0.016 A median and 0.024 A maximum at
   standstill, `calc/bt6_bag_launch_output.txt`); between 0.075 and 0.25 A the in-band clip band
   [0.125/I_tot, 1 - 0.125/I_tot] is empty and the feedforward path returns the previous ratio (ino:13772-13782,
   ino:13746, ino:14380-14385; calc10 section 4). An override would therefore move no MDAC code. The BT_BUS re-close moves
   the bus from FC-only to the droop split that the MDACs hold; this is the whole ruling-(1) shift at a standstill load.
   A direct MDAC write with both bus switches closed is not specified: a forced split below the conduction floor is the
   TP0053 relay class that collapsed the bus to 7-9 V (ino:14302-14311). The fixed window split of section 9.7 entry
   step 5 (revision 11) is written only while BT_BUS is open, and its restore re-applies the split that the loop held
   before the session, written in the iteration after the BT_BUS re-close write and before D-BT-EN conducts. **State 2 in closed loop with no FC-fed session** (ordinary
   driving, filtered total at or above 0.25 A): on a prediction at T_lead,nom the mode manager replaces the EMS
   `power_share_setpoint` with R_OV and stores the EMS value. R_OV is the lowest value strictly inside the inclusive
   selector rails (`DROOP_R_MIN` 0.15, ino:14107-14123), a host-test constant; the delivered target is max(R_OV,
   0.125/I_tot) by the in-band clip (ino:14581-14583), and the fw v29 span clamp holds the controller output in
   [0.15, 0.85] (ino:14723-14726). The override stands until the declared purge end (PI-2), when the stored value is
   restored. This case involves no FC window and no IC1 hardware; it is listed because the predictor interface carries
   it.
6. Pin 10 LOW and pin 5 LOW once pin 8 has read LOW for 20 ms (cold-module rule).

Table 21 gives the timing from the prediction.

Table 21. Pre-purge sequence timing, from the prediction (seq section 2; calc9 section 1).

| Event | Typical (median loop) | Worst healthy | Bound | Class |
|---|---|---|---|---|
| FC_CHARGE LOW (feed drop) | 1.13 ms | 1.34 ms | - | CALC |
| Module node 15.95 V to the U_MS edge | 0.83-2.01 ms after the drop | 2.01 ms after the drop | T_drain,max (`ERR_MOD_DRAIN`, sequence continues) | CALC; C_mod BENCH (S0-11) |
| Pin 33 LOW (second pin-8 LOW read) | 3.54-4.67 ms | 12.59 ms | - | CALC |
| Both S_GND on (pack bonded) | 3.84-4.97 ms | 12.89 ms | - | CALC |
| Bonded confirmation; BT_BUS written HIGH | 5.81-6.94 ms | 15.27 ms | 30 ms cap (`ERR_CHG_EXIT`, State 99) | CALC |
| D-BT-EN conducting | 33.6-34.7 ms | 47.0 ms | 93.3 ms (deadline bound) | ESTIMATE; BENCH W2a |
| Survivor blanking of BT_BUS ends (write + 30 ms) | 35.8-36.9 ms | 45.3 ms | - | CALC (ino:4869); ends before the worst-healthy conduction at t_D_ON above 10.23 ms (r6 section 3, open item 32) |
| State 2 in closed loop, no session: share override complete | 100-168 ms | 274.1 ms | 288.7 ms | ESTIMATE; HIL-measurable. Not applicable in P and D-s (no override below the 0.25 A gate) |

The bus does not need the share shift to survive the purge. In 172 recorded purges with FC_BUS and BT_BUS both closed,
V_bus stayed at 15.29-15.93 V at a pre-purge I_fc of up to 0.712 A (`calc/purge_seq_bags_output.txt` section 5, seq
section 4.3). In variants P and D-s the feed drop of step 1 leaves the FC with the auxiliary load only (0.09-0.15 A) at
the onset, inside that evidence; a purge at a pre-purge I_fc of 1.0-1.25 A arises only in variant D and is not covered
(ruling OR-DM). The MDAC split at the onset in P and D-s is the pre-session split, restored at exit step 4 (revision 11);
it is recorded at W2b and carries no requirement beyond V_bus above `LIMIT_V_BUS_MIN` at the onset. With a standstill
auxiliary load at or above `SHARE_I_TOT_MIN_A` 0.075 A the share loop could leave its freeze in closed loop and slew
k_d before the onset (40-57 ticks to the open-loop exit at 0.09-0.15 A, calc10 section 4; FM7-3); revision 11 keeps
the loop frozen through the SC-8 interval, which ends at the declared purge end after a prediction exit, so no MDAC
write from the share loop reaches the onset. The recorded standstill auxiliary load is 0.016-0.024 A (bags) against
0.09-0.15 A (HIL `I_AUX_A`, Table 26); W2b records it.

A chain that misses a deadline ends in a defined state: a missed drain latches `ERR_MOD_DRAIN` and continues to pin 33
LOW; a failed bonded confirmation latches `ERR_CHG_EXIT` and enters State 99 without a BT_BUS re-close. From the BT_BUS
re-close write of a prediction exit until the declared purge end, SC-1 reading (b) stays armed (V_bus below 12.0 V, no
dwell; section 9.11.5). A BT_BUS that conducts later than the onset (`PURGE_LEAD_SHORT`, row F59) leaves an
auxiliary-load bus with both source pairs commanded closed; with t_D_ON up to 100 ms every case of r6 section 1 is
BENIGN or OPEN at the FC recovery. A BT_BUS that never conducts (row F63: a Q_X1 drain-source short, an open R_S28 or
EN_BE_X lead, or the FCQ net stuck HIGH) leaves the FC alone on the bus at the onset: under the UV_BUS dwell alone
UV_BUS latched 36.7-103.4 ms after the onset across the r6 sweep and 5 cases had FC_BUS and FC_REG HIGH at the 80 ms
recovery with the bus at 8.88-11.74 V; with reading (b) kept armed, 1 case remains at 80 ms (bus 11.74 V, latch at
78.9 ms, FC_BUS LOW at 80.3 ms) and none at 100 ms (r6 section 1, remedy R at 12.0 V). The remaining case is the class
that Table 23 row 3 already accepts (FC_BUS HIGH at 80 ms with the bus at 12.04 V or more), 0.3 V deeper. Every such
case needs an FC fall of 60-75 ms, which no primary gives (open item 34). A 13.5 V threshold removes it in the model but
has no measured margin against State-2 traction transients; it is deferred to the W2d false-latch data.

#### 9.11.4 Post-purge re-entry

Re-entry needs every entry condition of section 9.7. Four of them bind after a purge:

- **End of purge.** The predictor declares the end, and V_fc reads at or above 7.0 V on two settled iterations (PI-2).
  The design figure is the onset plus 160 ms (140 ms plus the 20 ms edge uncertainty, facts_prior section 7).
- **Shift back.** Not applicable in P and D-s from revision 10 (no override is written at a standstill load,
  section 9.11.3 step 5). The window entry drops BT_BUS through the mode manager (section 9.7 entry step 5) after the
  FC_BUS re-test of that step, whatever share the loop holds; the bus-side BT share at that step is at most about
  0.065 A (seq section 8 item 3), far below the U_C1 trip of 2.52-3.50 A. In State 2 with no session the override ends
  at the declared purge end.
- **VCHG-IN unfed.** V_chg below 11 V on two settled iterations (the literal reading, ruling OR-VC). VCHG-IN decays on
  its bleed from 15.95 V to 11 V in 365.6 ms after the feed drop (tau 0.984 s, TODO(calibrate) at C-2b; calc9
  section 2). The strict reading (wait out the 1.0 s `ERR_VCHG_FED` blanking) is not used: a fed VCHG-IN (rows F15 and
  F17, or a pin-31 net stuck HIGH) never falls below 11 V, so the literal reading refuses the same windows, and the
  blanking then delays only the latch. The strict reading would cost 0.5-0.6 s per purge period (dead time 1.08-1.20 s
  against 0.45-0.79 s, seq section 5).
- **Purge permit.** The predicted time to the next onset is at least the admission horizon (PI-3).

The entry chain from the gates to charge current is 83.5 ms (typical), 188.5 ms (slow Ag105 start) and 201.8 ms (worst),
of which the Ag105 cold start is 65-170 ms (facts_prior section 6; gate S0-6; applicability to the FC profile at a
15.9 V input UNCONFIRMED). Table 22 gives the resulting purge cost.

Table 22. Re-entry and usable charge time per 10.34 s purge period, R_KA fitted (calc10 section 2).

| Variant | Case | T_lead | Binding gate | Charge current resumes | Dead time per period | Usable time | Mean charger output at I_set 1.25 A (net pack current with I_L 0.2-0.3 A in the dead time, calc12 section 6) |
|---|---|---|---|---|---|---|---|
| P and D-s | Typical | 80 ms | V_chg below 11 V | onset + 0.371 s | 0.450 s | 9.890 s (95.6 %) | 1.196 A (1.183-1.187 A) |
| P and D-s | Worst | 80 ms | V_chg below 11 V | onset + 0.489 s | 0.569 s | 9.771 s (94.5 %) | 1.181 A (1.165-1.170 A) |

With the V_chg gate binding, the dead time runs from the feed drop to the charge resume and does not depend on the lead;
the revision-10 lead of 80 ms moves the resume 20 ms earlier relative to the onset and leaves the dead time unchanged.
Revision 9 billed D-s an override and a shift back (0.573-0.785 s); neither runs at a standstill load (calc10
section 4). The figures are the sequence bound. They hold only while the Ag105 starts in 65-170 ms at every window. Without the
keep-alive R_KA, a Bring-Up of 8.4 s per cold start leaves 1.3-1.6 s per period (0.16-0.19 A mean) and a Bring-Up of
11.7 s leaves nothing (calc9 section 2). Ruling 9 (R_KA), with gates S0-6 and S0-8b, therefore decides whether FC windows
between purges deliver charge at all. One window per period gives 11.6 transitions per minute against the [RER] limit
of 20 per minute; `FC_CHG_MAX_MS` (30 s) does not bind, and `FC_CHG_COOLDOWN_MS` applies only after a 30 s dwell close
(ino:15472-15480, `calc/verify_hr2_cooldown.py`).

#### 9.11.5 Unpredicted purge: safe collapse

Ruling OR-SC accepts that an unpredicted purge collapses the bus and latches State 99, provided that no component is
damaged, on the collapse, on the recovery of the FC and on the next power-up, and that the pack is never left in a
hazardous configuration. A ride-through is not required. This subsection gives the detector, the teardown order, the
argument per damage mechanism, and the recovery. The evidence is `facts_purge_collapse.md` and pc sections 1-6: a
five-node model (FC boost output, VBUS, VCHG-IN, the module node, V-MOT) with the RT1987, eFuse and TPS61288 behaviour
from their datasheets, an 864-case grid and a 1296-case fall-time sweep. The FC fall time is swept because no primary
gives it.

**Collapse.** With the Ag105 drawing 13.0-14.8 W (Table 8), the FC-only bus falls at 3.9-6.2 V/ms; the eFuse turns off
at its UVLO (11.47-12.10 V) about 1.0-1.1 ms after a step onset and the module stops converting about 0.2 ms later. The
bus then carries only its auxiliary load and decays at 0.008-0.231 V/ms (pc section 1). If the Ag105 MPPT loop throttles
fast enough to hold its node at the 13.82 V FC-profile threshold (an ideal bound; the loop speed is unpublished,
facts_ag105 section 7), the bus joins V-MOT through D-MT-EN and V_chg reaches 13.0 V 13.6-31.3 ms after the onset
(pc section 2). In every grid case the module node reads 1.46-5.81 V at the bond, below the U_MS edge and the 11 V
lockout (pc section 3).

**Detector (SC-1).** `ERR_FC_ONLY_COLLAPSE` is evaluated in `chgModeTick()` in every iteration of a session that holds
BT_BUS open (the mode manager in `CHG_ENTERING` after entry step 5, `CHG_FC`, `CHG_CONFIG`, the dump check and the probe,
and `CHG_EXITING` up to the BT_BUS re-close write). It latches State 99 at once, with no dwell, on either of two diverse
readings: (a) V_chg (pin 38) below 13.0 V with EF_EN H after `chargerHasPower()` has been true in the session, or
(b) V_bus (pin 26) below `LIMIT_V_BUS_MIN` 12.0 V. Reading (a) is the first symptom in a window (1.4 ms after a step
onset). Reading (b) covers the sessions with EF_EN L (the probe) and a failed pin-38 channel. The detector does not read
`uvBusArmed` and does not depend on the share loop: in State 2 a share-loop cut of FC_BUS leaves no matched source
pair, and UV_BUS then disarms and dumps its dwell (ino:7338-7356). No BT_BUS re-close follows the latch (SC-4).

Revision 10 extends SC-1 in three ways. (i) **Predictor events (PI-4).** Inside the same sessions an UNKNOWN transition,
`purge_active` rising or a late prediction latches `ERR_FC_ONLY_COLLAPSE` at once; the commanded exit is not started.
The latch takes precedence over the exit in either in-iteration order. Reading (a) is evaluated "in a session in which
EF_EN has been H", not on the present EF_EN level. (ii) **Purge interval.** Reading (b) stays armed after the BT_BUS
re-close write of a prediction exit until the declared purge end (PI-2), so a BT_BUS that never conducts (row F63)
latches before the FC recovery (section 9.11.3). (iii) **Guard refusal.** When `busHotPlugUnsafe()` refuses the exit's
BT_BUS re-close, SC-1 stays active and latches on the next iteration that still refuses. The bt6 section-3 grid (3 load
modes, 3 auxiliary loads, 3 V-MOT capacitances, 5 FC fall times, variants P and D, recognition latency t_det 0-70 ms,
both orderings, p99 loop) gives OPEN at 80 ms and at 100 ms in 4860 of 4860 cases with rule (i), no BT_BUS write after
the onset and no turn-on peak above 2.5 A; the latch comes 1.4-70.7 ms after the onset (calc10 section 5).

**Why not ride through.** Under the revision-8 rule (policy E1) the same reading started a commanded exit that held
FC_BUS HIGH while it waited 21-31 ms for BT_BUS to conduct, plus the 20 ms UV_BUS dwell. With the ideal MPPT hold and an
FC fall of 60-75 ms the trigger moves to 63.9-78.9 ms, and in 8-20 of 324 cases per variant the FC recovered at 80 ms
into a bus at 6.73-8.70 V with V-MOT joined (hazard H-R, pc section 3b). That is the TP0010 class (33 sags to 6.5 V with
reconnect spikes above 3 A; nondestructive but recorded as Death-5-family stress, `docs/boost-bringup-debug.md`
2026-08-11). Its severity depends on whether the TPS61288 soft-starts after a VIN-UVLO recovery with EN held HIGH, which
SLVSFP3C section 8.3.1 does not state (TODO(verify: TI)). Policy E2 (this revision) removes the race instead of
characterising it. Policy E3 (E1 with FC_BUS LOW at the trigger and a bus-recovery deadline of about 40 ms) would keep a
ride-through; it is recorded as an option under ruling OR-SC and is not specified.

Table 23 gives the ordered teardown. It is the State-99 order of section 9.9, entered from inside a window.

Table 23. Safe-collapse teardown from an FC window (policy E2; pc sections 3, 3b; facts_purge_collapse Table 4).

| Order | Pin or signal | End state | Time after the onset (grid) | Reason |
|---|---|---|---|---|
| 1 | Latch (SC-1) | State 99 | 1.4-50.3 ms (State 1 window); 1.4-31.3 ms (window with 0.28 A traction, the variant-D bound) | First reading below the threshold |
| 2 | 31 FC_CHARGE, 30 REGEN (SC-2) | LOW | Phase 0, next iteration | EF_EN falls; the eFuse turns off; Q_MD dumps the module node |
| 3 | 27 FC_BUS, 28 BT_BUS (SC-3, SC-4) | LOW | 2.7-51.6 ms; at 100 ms LOW in all 648 sweep cases; at 80 ms still HIGH in 12 cases, all with a 75 ms fall and the bus at 12.04 V or more | FC isolated before the earliest recovery at 80 ms; no source re-close |
| 4 | Motor command | 0 A | Phase 0 | Section 9.9 step 3 |
| 5 | 33 (SC-5) | LOW | After pin 8 reads LOW twice, or at T_drain,max | Bond only on a cold module (node 1.46-5.81 V at the bond) |
| 6 | 32 BT_SEQUENCE_ENABLE | LOW | After the bonded state | Section 9.9 step 2 |
| 7 | 29 MOT_PWR (SC-6) | LOW | Phase 0 + 10 ms: 13.6-62.6 ms | Before the boosts (ino:8320-8325) |
| 8 | 3, 4 FC_REG, BT_REG (SC-6) | LOW | Phase 0 + 20 ms, last | After every bus and motor switch (ino:8329-8337) |
| 9 | 5 MPPT_DISABLE | LOW | Phase 2, cold module | Section 12.4 item 2 |
| 10 | 9 CBAL_DISABLE | LOW (unchanged) | - | OVP active (ino:8338) |
| 11 | 34 pump | Stopped at phase 3 | - | FF1 already clear |

The end state holds until a power cycle (SC-7): pins 27, 28, 29, 30, 31 and 33 stay LOW and EF_EN stays L. The
production firmware has no exit from State 99; the HIL auto-recovery compiles only under `HIL_SIM` (ino:8350 onward).

Table 24 gives the verdict on each damage mechanism. "Excluded" means that no current path or stress exists in the model
and the primaries; it is not a bench result.

Table 24. Damage mechanisms of an unpredicted purge (pc sections 1-6; facts_purge_collapse Table 3).

| No. | Mechanism | Verdict under E2 | Evidence |
|---|---|---|---|
| D1 | Death-5 hot-plug: the FC recovers onto a discharged or sagged node | Excluded (revision 10: with the PI-4 latch of SC-1 (i); under the revision-9 PI-4 text a recognised onset re-entered E1, `calc/bt6_logic_seq_enum.py` section 3) | With the PI-4 latch, FC_BUS LOW at 80 and 100 ms in 4860 of 4860 recognised-onset cases (calc10 section 5); FC_BUS LOW at 100 ms in all 648 sweep cases; the 12 cases still HIGH at 80 ms have the bus at 12.04 V or more (IN-FAMILY with the nondestructive TP0178 dropout) and phase 0 follows within one iteration (pc section 3b); a 9.76 ms iteration moves no case into a worse class (pc section 4) |
| D2 | TPS61288 body-diode back-feed | Excluded | Boosts LOW only after FC_BUS, BT_BUS and MOT_PWR (ino:8320-8337); no RT1987 conducts in reverse (DS-00 sections 17, 17.6); the recovering H-20 charges only the 30 uF FC boost output, as at every FC connection |
| D3 | RT1987 reverse stress | Excluded | Highest pin voltage 22.13 V (V-MOT at the chopper clamp) against the 40 V absolute maximum (DS-00 section 10); no VIN-VOUT differential rating is given (UNCONFIRMED that none applies) |
| D4 | RT1987 turn-on stress | No turn-on occurs | No bus switch re-closes after the latch (SC-4), and no exit re-closes BT_BUS after a recognised onset (SC-1 (i), revision 10: 0 BT_BUS writes and 0 peaks above 2.5 A in 4860 cases, calc10 section 5). Under E1 the BT_BUS re-close drew 0.05-1.62 A at V-MOT up to 1.5 mF and up to 4.46 A at 5 mF (pc section 5) |
| D5 | Ag105 brown-out and restart in the charge mode | Not a damage mechanism | The dark module with the sense in the return path is the designed cold state (section 9.5); a warm eFuse restart on a slow FC fall (8-28 of 216 cases, before the latch) is bounded by U_IM and, after a trip, by row F10 (at most about 24 mJ); restart behaviour TODO(verify: Silvertel) |
| D6 | Pack left in the charge mode or with the sense bypassed | Excluded | State 99 bonds after pin 8 LOW or at T_drain,max, then sets pin 32 LOW (section 9.9); a reset, brownout or hang clears FF1 in hardware (section 9.10) |
| D7 | Teensy supply during the collapse and the recovery | Survives | Scope: supply integrity during the event only; the long-term State-99 drain is in the Residuals paragraph. VBT is the pack and no VBUS-to-VBT path exists (facts_board section 6.3 item 2); the LM1084 input stays at 7.38-7.40 V at a 7.4 V pack against its 6.5 V limit (SNVS037H section 5.5; pc section 6) |
| D8 | BQ29200 | Not affected | Supplied from the cells; no charge flows during the collapse; CBAL_DISABLE stays LOW (ino:8338) |
| D9 | R_MD dump duty | Negligible | 6.1-28.1 mJ per event, peak 0.73-1.06 A (pc section 6), against the 51 mJ design dump; at most one event per power cycle (State 99 latches); pulse rating TODO(select), open item 17 |
| D10 | Motor regen onto a collapsed bus (State 2) | Excluded | D-MT-EN blocks V-MOT from the bus; pin 30 is LOW in an FC window and the bus-present comparators hold VOK at NOT OK below about 9.6 V-equivalent (section 3, G1 (f)); V-MOT is bounded by the VESC stop at about 21.35 V and the chopper clamp at 22.13 V (facts_prior section 6) |
| D11 | Next power-up | No latent hazard found in the switch topology | See the recovery paragraph below. A pack drained below 7.4 V by a State-99 latch held for hours is refused a window by the entry condition V_batt at or above 7.4 V (section 9.7, code 14, revision 10); the drain itself is the Residuals paragraph and open item 39 |

**Recovery and next power-up.** The FC returns 100-140 ms after the onset with State 99 latched; FC_REG and FC_BUS are
LOW, so the H-20 charges only the FC boost output through the passthrough (pc section 2). At the next power-up no window
state is stored; the Teensy reset leaves pin 33 high-Z, which clears FF1, and SHDN_EF on R_SDP keeps the eFuse off
(section 9.10). `setup()` drives every path switch LOW before the SD probe and Ethernet (ino:6709-6715). The staged
bring-up connects V-MOT only from a regulated bus through the D-MT-EN soft-start. VCHG-IN falls below 11 V within about
0.35 s of the collapse (out s2), so a power cycle of normal length does not latch `ERR_VCHG_FED` at boot (a shorter power cycle is
UNCONFIRMED). A window again needs the boot self-test and a dump-check pass in the new power cycle (sections 9.3, 9.7b).
The Ag105 clears its error states on an input power cycle (Ag105 DS p.18), and the collapse does not meet the Major
Battery Fault condition (battery below 2 V at 10 % current, DS p.6).

**Variant-specific rules (SC-8).** In State 2 the share loop, the source selector and the load guard do not write pins
27 and 28 from the first entry write (pin 10) until BT_BUS has been HIGH for the conduction bound after the exit
(section 12.4 item 7, revision 10; revision 9 started at entry step 5 and left a share-latch cut of FC_BUS possible in
steps 1-4, BT6-LS-02); the window exit is keyed on the command
(section 9.7); and a braking command at standstill cannot arise (`v_setpoint` 0), while in motion the window types stay
exclusive (OR-7). With traction on V-MOT at the moment of an unpredicted purge (variant D only), the VESC reaches an
ASSUMED 8 V cut-off 10.7-33.4 ms after the onset at V-MOT 0.48-1.5 mF and the vehicle coasts; no damage path follows
from it (pc section 1, facts_purge_collapse section 7).

**Residuals.** The only bench record of an FC-window purge collapse is 2026-10-28 (UV_FC and UV_BUS latched,
`docs/firmware-versions.md` row 35, pre-IC1 topology); no damage inspection is recorded, so "no damage" is
UNCONFIRMED until gate W2c. The E2 false-latch rate is BENCH (W2d). A latched State 99 keeps the Teensy on the pack
through the LM1084 at about 0.2-0.25 A (UNCONFIRMED; 4.8-6.0 Ah per day) until the operator power-cycles. No state of
fw v37 disconnects the logic load from the pack, and a UV_BATT latch itself ends in State 99 (ino:7300-7308). The
State-99 load is the smallest of the parked drains: State 1 keeps both boosts and V-MOT energized (Death-5 doctrine),
State 99 sets them LOW (Table 23 rows 7-8). Unattended deep discharge is therefore an operating exposure of any powered
board, not a mechanism of the collapse; revision 9 adds one trigger to it and makes an unattended parked session more
plausible. Remaining charge of 2-5 Ah lasts 8-25 h at that load (calc10 section 7; capacity and load UNCONFIRMED); the
pack PCM cut-off is unknown (open items 6 and 11). The drain is measured at gate W2c.

**WARNING:** After any State-99 latch, power-cycle the board or disconnect the pack. If the board stays latched, the
logic load of about 0.2-0.25 A (UNCONFIRMED) can over-discharge the pack in 8-25 h.

Operating rule (ruling OR-PK, revision 10): a parked FC window on the H-20 is attended, and the Pi alerts the operator on
`error_code` `ERR_FC_ONLY_COLLAPSE` or on any State 99 (`error_code` is carried in protocol v4 and v6 telemetry).

#### 9.11.6 EMS interface

The EMS request is explicit (revision 11, BT7-REQ-01). The deployed SDP nodes use `charge_goal` as their regen gate:
it is raised while braking and latched until P_demand exceeds 0.5 W (`sdp_ems_node_2026-10-28B.py`:24-30, :181-182,
:293-319), so it holds 1.0 through every stop that follows a deceleration. On the six recorded sessions with a request,
419.3 s of the 446.6 s of `charge_goal` is that latch, 0.0 s is the node's FC-charge branch (:381-382) and 27.3 s is
unclassified; all 112.8 s at standstill is the latch (`calc/bt7_req_origin_output.txt`). The 22-byte command packet
carries no version field (ino:7517-7527), so the firmware cannot tell a regen latch from a window request by
`charge_goal` alone. Under `PACK_RETURN_CHANGEOVER` the request therefore has the following meaning:

- An FC-window request is the reserved command byte (offset 20, `droop_enable_reserved`, parsed and discarded today,
  ino:7527-7528) equal to the request flag 0xA5 together with `charge_goal` above `CHG_GOAL_MIN` (TODO(calibrate); the
  bag analysis used 0.05, out s5). The deployed nodes and bridges send 0 or 1 in that byte, so a stale Pi stack cannot
  request a window; a `charge_goal` above `CHG_GOAL_MIN` without the flag is refused with code 15, so that a stale node
  is visible in telemetry. The packet length (22 B) and the checksum span are unchanged; the semantic change of byte 20
  goes through the protocol-bump procedure with the telemetry v6 lockstep (OR-H, section 12.12 item 6). The magnitude of
  `charge_goal` is not used: the window charges at the fixed FC profile (1.25 A, resistor mode, ruling OR-5'), and the
  Ag105 has no per-milliampere current control (CLAUDE.md section 3).
- In State 1 and State 98 a request opens a window when the conditions of section 9.7 hold. On a Pi-connected vehicle a
  parked request must carry `mode_cmd` 4 (MODE_SAFE): any packet with `mode_cmd` 0-3 received in State 1 sets
  `changeToRun` (ino:7533-7535), and the deployed nodes and bridge send MODE_SAFE only with `charge_goal` 0.0
  (`sdp_ems_node_2026-10-28B.py`:325, :338; `teensy_bridge_node_2026-10-31A.py`:618, :661). A parked request is
  therefore a new Pi command form (`mode_cmd` 4, flag 0xA5, `charge_goal` above `CHG_GOAL_MIN`), part of the Pi round of
  ruling OR-RQ. A Pi link loss does not end
  a parked window (`checkPiWatchdog()` acts only in State 2 and 3, ino:7463-7466, CC-B15); `FC_CHG_MAX_MS` and every
  purge prediction bound each window.
- In State 2 a request opens a window only at standstill (variant D-s, `IC1_FC_RUN_STANDSTILL` 1). A request in motion
  is refused with reason code 3. The fw v37 FC-path bootstrap that opened FC_CHARGE on intent in cruise stays withdrawn
  (ruling OR-W).
- Every purge prediction closes the window whatever the request; the window re-opens after the purge without a new
  request while the request stands.
- **Share command at standstill (revision 10, BT6-LS-02, BT6-REQ-03).** The fw v28 rev 5/6 re-entry rule re-arms the
  source selector when the command is on or outside an inclusive rail (0.15 or 0.85) in the closed-before region with
  the filtered total at or below 0.25 A (ino:14106-14125), and the fw v33b FC-only lockout then selects battery-only and
  cuts FC_BUS (ino:14119). A recorded SDP session commands exactly 0.15 at standstill with a charge request for 38.8 s
  (`rosbag_sdp_2026-10-28_20-46-53`, `calc/bt6_req_ds_request_gate_output.txt` section B). Therefore, while a State-2
  window request stands and the standstill conditions of section 9.7 hold, and through every D-s session and its exit
  until BT_BUS has conducted, the mode manager substitutes the nearest value strictly inside the rails (R_OV or 1 -
  R_OV) for an EMS rail command; an in-band command passes unchanged. Below the 0.25 A gate the substitution moves no
  MDAC code (section 9.11.3 step 5). The D-s entry runs the fw v28 F1 disarm (ino:195-215, ino:15444-15463) when the
  selector holds FC_BUS LOW, then waits for FC_BUS HIGH and unblanked (the F1 conduction gate) before entry step 1; the
  disarm sets the re-arm inhibit, and the substituted command keeps the selector disarmed afterwards. The F1 disarm runs
  at most once per stop. The fw v30 operator ruling that the Pi keeps the command inside (0.15, 0.85) stands
  (CLAUDE.md 2026-09-16 addendum); the substitution is the firmware backstop.

Telemetry protocol v6 (section 12.9, ruling OR-H) carries the request bit, the window state, the purge-permit state
(permit, prediction, UNKNOWN, purge active), the share-override bit, a `PURGE_LEAD_SHORT` counter and an 8-bit refusal
code. Table 25 defines the code; when several reasons apply, the lowest code is reported.

Table 25. FC-window refusal codes (telemetry protocol v6).

| Code | Reason |
|---|---|
| 0 | No refusal (window open, entering or exiting, or no request) |
| 1 | Build or stage: `PACK_RETURN_CHANGEOVER`, `IC1_STAGE` or `FC_CHARGE_ALLOWED` does not permit the window |
| 2 | Latched fault or window inhibit (the fault word gives the fault) |
| 3 | State: not State 1 or 98, and not State 2 at standstill with `IC1_FC_RUN_STANDSTILL` 1 |
| 4 | Purge permit UNKNOWN (PI-4) |
| 5 | Predicted time to the next onset below the admission horizon (PI-3) |
| 6 | Purge active, or V_fc below 7.0 V after a purge (PI-2) |
| 7 | V_batt at or above the 8.0 V entry gate (until S0-8b) |
| 8 | V_chg not yet below 11 V (section 9.11.4) |
| 9 | Module not cold (pin 8 LOW for less than 20 ms) |
| 10 | Window rate limit or `FC_CHG_COOLDOWN_MS` |
| 11 | Bus conditions: V_bus below 13.5 V, F1 conduction gate, or BT_CURRENT not below 0.2 A |
| 12 | No dump-check pass in this power cycle, and the dump check cannot run or ended with no verdict (section 9.7b; revision 11: a request starts the dump check in State 1, 98 or, with `IC1_FC_RUN_STANDSTILL` 1, State 2 at standstill; revision 12: retried at most once per stop or purge period, three no-verdict attempts per power cycle) |
| 13 | GENSTAT Fully Charged hold or the 60 s Thermal Shutdown hold (section 12.5 item 4) |
| 14 | V_batt below `LIMIT_V_BATT_MIN` 7.4 V (revision 10, section 9.7) |
| 15 | `charge_goal` above `CHG_GOAL_MIN` without the request flag 0xA5 in command byte 20 (revision 11: stale Pi command form; no window is requested) |
| 16 | Idle-entry self-test running, deferred or not yet re-run to a pass (revision 12, section 9.3) |

Code 11 also covers, from revision 11, FC_REG_ENABLE or BT_REG_ENABLE not HIGH on two settled iterations, and a
State-1 or State-98 FC_BUS held LOW by a share-latch or selector flag that the guarded release of section 12.4 item 9
could not release.

The EMS policies place charge requests as follows. The frontier SDP v6 policy has no charge cells, so it requests no
window. The SDP v7 policy places its 140 charge cells in demand bins 0-2 (below about 3 W, a bus total below about
0.19 A), which fit the FC-window budget (facts_purge_demand section 5.3); variant D-s admits only the part of them that
falls at standstill, which is not evaluated for v7 (open item 40). The 2026-10-28B node has an FC-charge branch
(`fc_may_charge`, a J_charge table, :381-382), which no recorded sample reached. On the recorded Pi sessions the EMS
therefore made 0 s of FC-charge request, and HR2 in Run against EMS requests is undetermined until an EMS that requests
FC charge runs (revision 11, BT7-REQ-02). Revision 10 stated D-s as 107.3 s of 446.6 s "requested" (24.0 %); that
figure measures the regen latch and is withdrawn as an HR2 value. It remains useful only as a counterfactual for the
cost of the dump-check precondition (calc11 section 1: 106.6 s with the State-2 dump check, 0 s under the revision-10
text). MPC charge commits are produced at run time and are not evaluated. A Pi-side policy that sets the request flag at
stops (from its FC-charge decision only) and sends the parked form matches variants D-s and P; that Pi round is a
Stage-1 prerequisite (ruling OR-RQ, section 12.12 item 6).

#### 9.11.7 Variants P, D-s and D, and HR2

Table 26 compares the three variants. Variant D-s is the State-2 standstill subset of variant D.

Table 26. FC-window variants.

| Item | P (parked, State 1 or 98) | D-s (State 2, standstill) | D (State 2, in motion) |
|---|---|---|---|
| Lead time | T_lead,min 80 ms | T_lead,min 80 ms (revision 10) | T_lead,nom 290 ms |
| Share shift (ruling 1) | BT_BUS re-close only; no share loop in Idle | BT_BUS re-close only; share loop frozen or holding below the 0.25 A gate; rail commands substituted in band (section 9.11.6) | Share override |
| Load on the FC at the onset | Auxiliary only (0.09-0.15 A) | Auxiliary only | Traction plus auxiliary, up to 1.25 A; two-source purge above I_fc 0.712 A not recorded (BENCH) |
| Traction allowance in the window | None (motor command 0) | None (exit on the command) | 0.06-0.33 A bus-side (out s1, on the stiff 0.16 V/A bus), the size of the INA253A1 zero error of up to 0.1 A per channel and of the 24-48 % plant-to-rig traction error (out s5). The voltage headroom depends on the split: at the closed-loop clamp r 0.15 it falls to 0.03-0.08 A to the 13.82 V module threshold on the design-chain and HIL droop (bt7 section 5); a variant-D firmware would need the fixed split of section 9.7 entry step 5 as well |
| Exit on traction | Any non-zero motor command | `v_setpoint` non-zero or \|I_cmd\| above I_still, before the VESC command; torque released after BT_BUS has conducted (43-47 ms healthy, at most 61.7 ms; revision 10) | A demand-budget exit keyed on the commanded current (new logic) |
| Unpredicted purge | Safe collapse (Table 23) | Safe collapse | Safe collapse; the VESC browns out in motion and the vehicle coasts |
| Value per drive cycle (plant model, R_KA, 7.4 V; request at every stop, no T_still dwell: upper bound) | 0 | 1.9-31.9 mAh (Table 27) | 19.8-63.2 mAh nominal, 3.5-34.3 mAh pessimistic (Table 27) |
| Value on the recorded sessions against EMS FC-charge requests (revision 11) | 0 in Run | 0 s: the recorded `charge_goal` is the regen latch, 0 s of FC-charge request (`calc/bt7_req_origin_output.txt`); undetermined for an EMS that requests FC charge | 0 s, as D-s |
| Counterfactual: recorded `charge_goal` treated as a flagged request (2831 s live, 8.0 V gate) | 0 in Run | 106.6 s with the State-2 dump check (calc11 section 1); 0 s under the revision-10 text (code 12); 107.3 s without the precondition (calc10 section 6) | 127.5 s without the precondition (calc10 section 6); the 20.2 s increment is braking or coasting time, where FC windows are exclusive with regen windows (OR-7) |
| Value on the recorded sessions, not request-gated | 0 in Run | 600 s (21.2 %) | 650 s (23.0 %): 50 s more than D-s (calc9 section 5) |
| Firmware beyond D-s | - | - | Traction-allowance exit, demand estimate with a calibrated sense offset, a two-source purge gate at high I_fc |

Table 27 gives HR2 per drive cycle (calc9 section 4, from out s4: plant demand model, R_KA fitted, V_pack 7.4 V, the
re-entry rule "none"; the adopted literal rule lowers every figure by at most 7 %, the reduction that rule "blank"
gives). Charge is I_set x time in the CC region. Every D-s figure assumes a charge request at every stop and no T_still
dwell (T_still is TODO(calibrate), open item 38), and the demand sheet used its own lead of 58.7-108.3 ms, so the D-s
columns are an upper bound; the frontier SDP v6 policy requests no window, so with that policy HR2 in Run is 0.

Table 27. HR2 per drive cycle (upper bound: request at every stop, no T_still dwell).

| Cycle | Length | D-s window time (fraction) | D-s charge | D-s mean over the cycle | D charge, nominal | D charge, pessimistic (aux 0.15 A, 7.8 V, worst chain) |
|---|---|---|---|---|---|---|
| 61 s cycle (ems-dp-replay) | 61 s | 5.5 s (9.0 %) | 1.9 mAh | 0.112 A | 19.8 mAh | 3.5 mAh |
| FTP-75 rig slice | 345 s | 67.1 s (19.4 %) | 23.3 mAh | 0.243 A | 63.2 mAh | 27.8 mAh |
| ftp75c | 175 s | 35.7 s (20.4 %) | 12.4 mAh | 0.255 A | 32.4 mAh | 15.1 mAh |
| UDDS_trimmed_3.5mps | 333 s | 55.5 s (16.7 %) | 19.3 mAh | 0.209 A | 50.3 mAh | 23.3 mAh |
| RegenTest_v2_lowspeed | 152 s | 80.5 s (53.0 %) | 28.0 mAh | 0.663 A | 34.1 mAh | 29.5 mAh |
| RegenTest_decel_sweep | 183 s | 91.8 s (50.2 %) | 31.9 mAh | 0.628 A | 38.5 mAh | 34.3 mAh |

The HR2 results are as follows. Variant P delivers 1.18-1.20 A mean of charger output (1.18-1.20 Ah per parked hour),
and 1.17-1.19 A of net pack current once the pack supplies the ASSUMED I_L of 0.2-0.3 A in the dead time (revision 12,
BT8-REQ-04, calc12 section 6), with R_KA below the
8.0 V entry gate and 0 Ah per drive cycle (Table 22). Variant D-s delivers 9-53 % of the cycle time at 1.25 A on the
plant model with a request at every stop. On the recorded Pi sessions the EMS made no FC-charge request (section 9.11.6,
revision 11), so HR2 in Run against EMS requests is undetermined; Table 27 is the only HR2 figure in Run and is an upper
bound. Every D-s figure assumes the fixed window split of section 9.7 entry step 5 (revision 11), under which the
module input power is fully deliverable at I_set 1.25 A on both the design-chain and the bench-scaled droop (calc11
section 2); at the closed-loop clamp split of revision 10 the design-chain droop would have lowered it to 65-100 %. All
values rest on the ASSUMED I_L 0.3 A and efficiency 0.88/0.80 (gate B8) and on the Ag105 cold start (S0-6).

**Recommendation.** Adopt variants P and D-s (ruling OR-O'). Variant D-s reaches every stop of a drive cycle with no
traction allowance to calibrate, because the window ends on the command before any traction current flows. Variant D
is not unsafe by the analysis of section 9.11.5. However, its in-motion increment (D minus D-s) rests on a 0.06-0.33 A
allowance that the current-sense error and the plant error can consume, that allowance falls to 0.03-0.08 A of voltage
headroom at a drooped split (bt7 section 5), it halves on the 61 s cycle for a 0.02-0.08 A change of an assumed input
(facts_purge_demand section 5.2, out s4), and a purge at a pre-purge I_fc of 1.0-1.25 A is outside the 172-purge
evidence. On the plant drive cycles with a request assumed at every stop, variant D (pessimistic) exceeds D-s by
1.2-1.8x (calc10 section 6). The comparison against an EMS that requests FC charge (an SDP v7 or J_charge walk over the
drive cycles with the IC1 admission rules) is open item 40. Ruling OR-DM records variant D as an option to re-evaluate
after gates B8 and W1 have calibrated I_L, the efficiency and the INA253A1 offsets and after open item 40; its basis is
the traction-allowance, sense-error and uncovered-purge argument above. The revision-10 statement that D-s carries 84 %
of the window time of D "on the recorded EMS requests" is withdrawn (revision 11, BT7-REQ-02).

## 10. Fail-safe defaults

Table 13 lists every new control element and its state without firmware control.

Table 13. Fail-safe defaults.

| Element | Default mechanism | State with the Teensy unpowered, in reset or hung |
|---|---|---|
| S_GND1, S_GND2 | R_GUk 10 kOhm to VBT_Tk (one tap per channel); Q_Ak gate on R_PAk 100 kOhm | ON (bonded) while the pack supplies the taps |
| S_CHG | R_PD3 47 kOhm to PACK-; Q_C gate on R_PC; Q_D on while either S_GND gate is high | OFF |
| FF1 | In reset: /CLR held LOW through U_P33 (input on R_P33) and U_N33. In a hang: by PUMP_OK within 43-76 ms of the last pump edge | Clear (at once in reset; 43-76 ms in a hang) |
| Pumped arm | No toggling: PUMP_H decays through R_P2 | PUMP_OK LOW |
| eFuse U_EF | EF_EN needs FF1.Q AND PUMP_OK AND ((VOK AND p30) OR FCQ); R_SDP 22 kOhm at the eFuse pin | OFF (also with 3V3 absent or the SHDN wire open) |
| U_IM | Open-drain output on R_UIM; IMON at 0 V with the eFuse off | Released (no clear) |
| Q_OV | Gate on R_OVP 1 MOhm to 3V3, held LOW by BQ29200 OUT through the fly-wire | OFF while the fly-wire is intact and no OVP; ON (FF1 held clear) if the fly-wire opens |
| D-BT-SQ | Q_X2 on while FF1./Q is high; existing 10 kOhm bodge pull-down (B2) | Disabled |
| D-BT-EN | Existing 10 kOhm bodge pull-down; Q_X1 while FCQ is high | Disabled at reset (unchanged) |
| D-BC-RG | Existing 10 kOhm bodge pull-down; Stage 2 adds Q_RG1, Q_RG2, Q_RB1, Q_RB2 on while OKk_N or BPk_N is HIGH | Disabled |
| D-BC-FC, D-MT-EN, D-FC-EN | Existing 10 kOhm bodge pull-downs | Disabled at reset (unchanged) |
| VOK | Stage 2: comparators and pull-ups on 3V3; open-drain outputs released read NOT OK and bus absent; zero-input offset 50.4 mV minimum. Stage 1: R_VKP holds VOK LOW | NOT OK |
| Profile switches Q_CS, Q_MP | R_PGP 100 kOhm | OFF: regen profile (1.75 A, 18 V), relevant only when the charger is powered |
| Injection FETs | R_P35, R_P10 pull-downs | OFF |
| Ag105 settings | Resistor mode for current and threshold; EPROM voltage 0x08 | An EPROM reset gives 4.2 V (undercharge) |
| Module-node dump Q_MD | Gate on MD_G = NOT EF_EN through U_MDI and R_MDS 1 kOhm; R_MDG 100 kOhm pull-down | ON while the LB rail is up and EF_EN is L; OFF with 3V3 absent or the MD_G wire open, when R_MB 3.3 kOhm still bleeds the node (16 V to 9 V in at most 0.42 s) |
| U_MS / pin 8 | Open-drain output on R_UMS and the Teensy internal pull-up | HIGH (reads "fed") with U_MS released or unpowered (output Hi-Z, SBOS300C section 9.4.5); the bonded consistency check of section 12.4 item 4 refuses windows |
| VC1 tap / pin 20 | Passive divider R_VC1a/R_VC1b; pin 20 is an analog input in every state | No control function; at most 11 uA from VC1 |
| MPPTD (pin 5) | Open-drain (revision 6); Teensy high-Z in reset | Released: the module's own MPPTD bias applies (TODO(verify: Silvertel) that released means MPPT enabled; S0-7) |
| D_VC1; RB1A 4.7 kOhm | Passive | D_VC1 clamps VC1 at -V_F; at most 16.2 mA through RB3 and 0.83 mA through RB1A into VC1_CB in any fault (calc7 section 1) |
| F_VX | Passive | Opens on a VBATN_X short to a positive conductor in either mode |

## 11. Single-fault table

Table 14 lists the single faults. "First bound" names the first layer that limits the consequence. A row marked R4 to R8
is new or changed in that revision (R9-R11 likewise).

Table 14. Single faults.

| ID | Fault | Effect | First bound | Detection | Residual |
|---|---|---|---|---|---|
| F1 (R5) | One S_GND drain-source short | Charge mode: the charge current bypasses the sense in parallel with S_CHG; the module regulation is blind | U_C2 at 2.65-3.64 A clears FF1; U_IM at 1.51-1.98 A of eFuse input; eFuse I_OL | Sense-path check at entry and in the self-test (V_PACKN about 0 instead of the reverse chain drop); `ERR_ISO_MISMATCH` (FC windows only). The ladder SG bit reads the gate, so it does not see a drain-source short | One bounded pulse per entry if the sense-path check cannot resolve (board load below 0.2 A); latched until reboot |
| F2 (R5) | Both S_GND channels lost (two independent faults; the common causes, pack positive or F_PK open, stop all pack current) | Bonded discharge through the body diodes: 5.0-7.2 W at 7.2 A, 12.0-17.1 W at 17.1 A | Firmware `ERR_SGND_OPEN` cuts BT_BUS and BT_REG within one iteration; RTWDOG reset if hung | `ERR_SGND_OPEN` (corrected V_PACKN decode, numeric acceptance at C-2) | No hardware cut; needs two faults. The S_CHG body diode is a third path through the Ag105 sense (UNCONFIRMED); the FET transient thermal bound against the cut time is TODO(verify: SLPS632 Z_th curve). At the 7.4 V floor the body-diode drop can take the LM1084 input below 6.5 V (1.5 V dropout maximum at every load, SNVS037H 5.5 note 5): Teensy brown-out possible |
| F2a | One S_GND channel lost (Q_Ak short, Zk short, R_GUk open, gate lead open) | The other channel carries the return at 0.70 W (17.1 A, hot) | Parallel channel | Ladder SG bit; `ERR_SGND_DEGRADED` | Latent until the next ladder read (every iteration) |
| F3 | S_CHG short | Bonded mode: sense in parallel with S_GND, harmless | - | Not detectable in the bonded mode | Latent; with F2 traction flows through the sense |
| F4 | S_CHG open | Charge mode: charge through the S_CHG body diode (regulated); the pack ends about 0.7 V below the CV setpoint | Body diodes | V_PACKN about -0.7 V in the charge mode | Availability only |
| F5 (R4) | D-BT-SQ power-stage short | Bonded mode: pack tied to VCHG, charger unpowered (Stages 1-2) | EF_EN needs FF1 | Pre-rework check D-1 | Benign in the bonded mode (Stage 3, row F37, is withdrawn) |
| F6 (R4) | Q_X2 open, X fault or EN_SQ_X lead open | D-BT-SQ enabled in the bonded mode | Charger unpowered (EF_EN needs FF1; Stages 1-2) | C-2 cross-lock test | Benign alone (Stage 3, row F37, is withdrawn) |
| F7 | FF1 output stuck HIGH | Charge mode outside a window | U_C1 bonds directly at 2.52-3.50 A discharge; EF_EN still needs PUMP_OK and a source term; firmware refuses REGEN and FC_CHARGE outside windows | Ladder bit 0 H with pin 33 L | Reverse sense current up to the U_C1 trip until firmware or U_C1 acts |
| F8 (R4) | U_SH1 or U_C1 dead | Loss of the discharge trip | Firmware exit on traction (section 9.6); I_DIS 4 A (Ag105 DS p.20) | Self-test step 7; `ERR_IPACK_XCHK` | Second fault needed for a sense overstress |
| F8b (R4) | U_SH2 or U_C2 dead | Loss of the charge trip | eFuse I_OL; Ag105 OC trip (after S0-2 and D-3) | Self-test step 6; `ERR_IPACK_XCHK` | Latent until the next Idle entry |
| F9 | C_P1 short with pin 34 static HIGH during a hang | PUMP_OK stays HIGH | The RTWDOG reset (ruling 5): pin 33 goes high-Z and FF1 clears at once | Self-test step 2 | Needs the short and a hang |
| F9b (R7) | RTWDOG not configured, or its timeout too long | One hang layer lost (revision 7 deletes the WDOG1_B join: pin 20 carries the VC1 tap) | Pump | Bench B11b (forced RTWDOG timeout) | The pump remains |
| F10 (R6) | Module input capacitance at a re-bond; S_CHG and S_GND overlap at exit (about 25-45 us at nominal values) | Commanded exit: none, because the feed drops and Q_MD dumps the node until pin 8 reads LOW before pin 33 LOW, so the module is cold before the bond. Hardware trip (U_C1, U_C2, U_IM, D5, BQ OUT): the eFuse turns off with FF1 and Q_MD turns on with it, but the module converts from C_in + C_EO for up to 1.08 ms (C_in up to 144 uF), partly after S_GND re-bonds with the sense bypassed | eFuse off at the trip; Q_MD dump in parallel; D-BT-SQ disabled 0.3-0.7 ms after FF1 clears | C-2 overlap measurement; S0-13 exit case without C_HU (stage 1-2) | At most about 24 mJ per hardware trip (calc5 section 10); below the F37 bound of 0.152 J |
| F11 (R5) | eFuse FET short | Charger powered whenever VCHG-IN is fed | VCHG-IN is unfed in the bonded mode (feeds refused; `ERR_VCHG_FED` latches a fed input with both feeds LOW); D-BT-SQ cross-locked; R_KA limits any output path to about 14 mA | eFuse-blocking probe at every configuration check (section 9.7a: U_MS reads the module node at or above 8.69-9.15 V with EF_EN L, `ERR_EFUSE_BYPASS`); a fed module node in the bonded mode (`ERR_MOD_FED`); bench C-2 injected-bypass gate. **No qualified in-service detector until C-2 has passed** | Latent between configuration checks. Inside a window the input ceiling is lost; U_C2, U_IM (sees the input current) and the Ag105 trip remain; firmware `OC_FC` 1.4 A and `OV_BATT` 8.5 V remain |
| F12 (R4) | Pack-direct bond **downstream** of R_SH (PACK- or VBATN_X to GND): balance-lead negative in J-BL position 3, a pack-side accessory, an earth-referenced probe on PACK- | Parallel bond; S_GND and S_CHG bypassed | G8 (position 3 blocked); rule C2 | C-1 and C-1b; V_PACKN about 0 and `ERR_ISO_MISMATCH` (FC windows); all pack current still passes R_SH, so U_C2 trips at 2.65-3.64 A | **Fire hazard** if G8 is defeated |
| F12b (R4) | Pack-direct bond **upstream** of R_SH (pack negative terminal or KS+ to GND, including an earth-referenced probe ground with USB connected) | Parallel bond across the whole chain: I_PACK1, U_C2, reg 0x06 and V_PACKN all read the regulated chain current while the true pack current is higher | FC window: G2 trips above about 2.4 A of pack current. Regen window: eFuse I_OL (pack current at most about 5.5 A); rule C2; R_K limits a KS+ bond to milliamperes | C-1b (earth to pack(-) open before every session) | Bounded by the eFuse; no detector in regen windows |
| F13 | SHDN_EF wire open between LB and CB | SHDN would float and enable the eFuse | R_SDP 22 kOhm at the eFuse pin holds 0.22 V | C-2 (wire open test) | Benign alone |
| F13b (R4) | U_AND output stuck HIGH | eFuse enabled whenever VCHG-IN is fed | D-BC-RG still clamped; firmware refuses FC_CHARGE and REGEN in the bonded mode; D-BT-SQ cross-locked | Ladder bit 1 H with FF1.Q L | As F11 |
| F14 (R7) | VBATN_X lead open, or F_VX open | Charge mode: no charge path. The module CV loop holds VBT near 8.4 V against Vin- (PCB GND), so pack(-) sits 0.1-0.9 V above GND, the S_GND body diodes are reverse-biased, and the module supplies the board load with its return outside its sense (`calc/fmea_round4_calcs.py` section 5; the module behaviour with an open VBat- is UNCONFIRMED) | CV loop; U_IM; eFuse I_OL | reg 0x06 and I_PACK1 read about 0, so `ERR_ISO_MISMATCH` stays quiet and GENSTAT can report Fully Charged; `ERR_CHG_PATH_OPEN` (revision 7, Table 16); P-M1 and C-4 | Bounded; window inhibit |
| F15 (R5) | D-BC-RG power-stage short | VCHG-IN tied to V-MOT; with MOT_PWR HIGH, VCHG-IN = VBUS in Idle and Run | Bonded: eFuse needs FF1. Regen window: VOK compares V-MOT with VBUS only and cannot see the VCHG-IN source; with an eFuse short as well, a bus-fed loop on two faults | `ERR_VCHG_FED` (V_chg above 11 V for 50 ms with pins 30 and 31 LOW) in every bonded iteration and as a window-entry precondition | Detected before any window. A short that arises inside a window lasts until the exit plus the 1.0 s blanking |
| F15b (R4) | One VOK channel reads OK at bus level (comparator stuck, V-MOT top string shorted, R_Mk2 open, U_BPk stuck "present" together with a tap fault) | One channel permits at bus level | The other channel: its Q_RG or Q_RB clamps D-BC-RG and U_VA holds VOK false | `ERR_VOK_STUCK` (revision 6): a channel permits while the self-calibrated V-MOT/VBUS ratio is below 1.003 for 50 ms, in any state; a healthy channel permits only above its release level (ratio at least 1.0062, calc6 section 6), so the rule does not depend on the V-MOT decay rate | Latent for at most 50 ms; a common-mode fault of both channels is caught by the same rule (any channel, not exactly one) |
| F15c (R4) | U_VA output stuck HIGH | eFuse VOK term always true | The four clamps still hold D-BC-RG off when V-MOT is not above VBUS | Ladder: EF_EN H with CH1_OK or CH2_OK L and FCQ L in a regen window | Benign alone |
| F15d (R4) | One clamp (Q_RGk or Q_RBk) open | That clamp no longer acts | The other clamps and the eFuse VOK term | C-2, B10 only (no readback pin): accepted latent (F40) | Benign alone |
| F16 (R4) | D-BT-EN power-stage short in an FC window | BT boost on the bus while the charger is fed from it | D5 clears FF1 when the BT output exceeds 0.31-0.59 A, after the 2.8-6.1 ms arming delay; firmware reads BT_CURRENT and drops pin 31 | Ladder FF1.Q L while pin 33 H; D5_N | One bounded pulse of about 4-7 ms (arming plus the 1 ms filter); flow below 0.31 A is bounded, not cut in hardware |
| F16b | Q_X1 open | BT_BUS not clamped in an FC window | `assertFcChargeEnable()` drops BT_BUS first; D5 | C-2 | Benign alone |
| F17 (R5) | D-BC-FC power-stage short | VCHG-IN tied to VBUS in every state | Bonded: eFuse needs FF1. FC window: none needed (same FC-only bus). Regen window: none in hardware; at every VOK assert the eFuse feeds the Ag105 from VBUS while BT_BUS may stay closed: a one-fault loop for about t_D_ON per pulse (about 0.18 J per pulse with a warm module, `calc/bt2_logic_seq_enum.py` section 4.5) | `ERR_VCHG_FED` before any window (regen- and FC-window entry precondition) | **Not benign**: closed only by the firmware detector. A short that arises inside a regen window is latent until the exit plus 1.0 s (at most one 30 s window); U_C2 and U_IM bound the current |
| F18 | R_KA bridge to an adjacent node | Pack tied to VCHG; charger unpowered in the bonded mode | EF_EN needs FF1 | Pre-rework continuity | Benign alone |
| F19 | Ag105 internal switch across the sense conducts in a charge sub-state | Module regulation blind, as in ML0227, but in the charge mode | U_C2; U_IM; eFuse I_OL and latch-off | `ERR_ISO_MISMATCH` (FC windows only); regen windows hardware-only | Decided by S0-2 and S0-2b |
| F20 | Pump toggled from an ISR or timer by a firmware defect | Hang detection by the pump defeated | RTWDOG | Host-native test that pin 34 is written only from `loop()` | Firmware rule |
| F21 (R5) | Kelvin lead KS+ or KS- open (or R_K1/R_K2 open, or a cracked R_SH Kelvin joint) | Both amplifiers read an undefined value; U_C1/U_C2 may be blind | eFuse I_OL; U_IM; Ag105 OC trip (after S0-2 and D-3) | `ERR_IPACK_XCHK` (output undefined, BENCH C-2); `ERR_IPACK_PLAUS` if the outputs settle near zero | Output behaviour with an open input is BENCH (C-2) |
| F22 (R4) | Lead A or lead B open | The other lead carries the return | Parallel lead | Lead B open: R_ret above the C-2 baseline plus 5 mOhm at 5 A or more (`ERR_RET_DEGRADED`). Lead A open: R_ret rises by only 0.18 mOhm, not detectable | Lead A open is benign (lead B carries the return; 32 mV at 17.1 A); lead B open gives 0.37 V of SB ground offset at 17.1 A |
| F22b (R5) | Both return leads open, or lead B open with lead A above 27 mOhm (49 mOhm at 17.1 A) | GND rises until Q_A and Q_C self-bias at a 0.84-1.65 V offset; S_GND turns off and S_CHG turns on with FF1 clear; the board return flows through the Ag105 sense in reverse at board load; S_CHG dissipates 5.6-12.6 W at 7.2 A | `ERR_PACKN_RANGE` (-V_PACKN 1.23-2.20 V, outside -1.2 to +0.6 V within 5 ms) and `ERR_SGND_OPEN` cut BT_BUS and BT_REG | V_PACKN; C-2 both-leads-open step | Reverse sense pulse of about one iteration plus 5 ms at board load; Ag105 reverse-pulse rating TODO(verify: Silvertel); the 0.35 V lower diode drop is ASSUMED (`calc/verify_sgnd_offset_bothleads.py`) |
| F23 | Q_CS open (FC window runs on the regen current setting) | FC bus current about 1.37 A including aux at 8.4 V | `OC_FC` 1.4 A single sample; FC governor; `ERR_PROFILE_OC` | reg 0x06 above 1.4 A | Bounded; safe direction |
| F23b | Q_CS short (regen window on the FC current setting) | Regen ceiling 15.6-17.7 W | - | reg 0x06 | Availability only |
| F23c | Q_MP short in a regen window (13.82 V threshold) | Limit cycle at the VOK release | eFuse VOK term | Repeated VOK releases | Availability only |
| F23d | Q_MP open in an FC window (18 V threshold) | No charging from the 16 V bus | - | GENSTAT not Charging | Availability only |
| F24 (R4) | U_C2 output stuck released | No charge trip | U_IM; eFuse I_OL; Ag105 OC trip (after S0-2 and D-3) | Self-test step 6 | Latent until the next Idle entry |
| F25 (R5) | BQ29200 OUT path open (fly-wire lifted or OUT joint open); OUT lead shorted to GND | Open: R_OVP pulls the Q_OV gate to 3V3, N1 is held LOW, FF1 cannot set. Short to GND: hardware pack-OVP actuation lost | Open: no window can open. Short: firmware `OV_BATT` 8.5 V (pack total only); Ag105 CV 8.4 V | Open: self-test step 4 and window entry (`ERR_CHG_SELFTEST`, `ERR_CHG_ENTRY`). Short: not detectable in service (BG-17 at build) | Open: availability only. Short to GND: latent; a single-cell overvoltage needs a second fault (cell imbalance) |
| F26 | A clear source stuck LOW | FF1 cannot set | - | `ERR_CHG_ENTRY` | Availability only |
| F27 (R4) | KS+ or KS- lead shorted to pack positive, VBT or another positive conductor | Without R_K: 100-270 A through the signal wire (fire). With R_K: at most 3.85 A | R_K1/R_K2 open (fusible) | C-2 injection test; afterwards F21 detection | Two resistors replaced after the event |
| F28 (R4) | KS+ bonded to PCB GND | Without R_K: an F12b-class bond carrying up to about 2.4 A. With R_K: about 40 mA | R_K1 | `ERR_IPACK_XCHK` (both channels see the same offset: may be latent) | Negligible current |
| F29 (R4) | One VOK VBUS-side tap open, pad lift, R_Bk2 short or C_Bk short | Without U_BP: that channel reads OK at bus level. With U_BP: BTk below REF, so BPk_N is HIGH and the channel blocks | U_BPk and Q_RBk | Channel never permits: V2-4 availability | Fail-safe; the other channel is unaffected (separate taps) |
| F30 (R4) | 5V rail lost | Revision 3: OK1_N/OK2_N fell LOW (OK). Revision 4: VOK is on 3V3 and unaffected; the pump stops | Pump clear 43-76 ms | `ERR_CHG_TRIP` | Benign |
| F31 (R4) | One gate tap lost (F_Tk open, C_VTk series pair shorted, tap lead open) | One S_GND channel off | The other channel (own tap) | Ladder SG bit; `ERR_SGND_DEGRADED` | As F2a |
| F32 (R4) | U_P33 output stuck HIGH | Pin 33 cannot clear FF1 | Pump clear: the exit sequence stops the pump on a failed confirmation (43-76 ms) | `ERR_CHG_EXIT` | One exit delayed by at most 76 ms |
| F32b (R5) | U_P33 output stuck LOW, U_CKS stuck, or U_CLS output stuck LOW | FF1 cannot set | - | `ERR_CHG_SELFTEST` (step 4) | Availability only |
| F32c (R5) | U_CLS output stuck HIGH, or the /CLR pin open | No clear source can clear FF1 (pin 33, pump, U_C1, U_C2, U_IM, D5, BQ OUT) | U_C1 still bonds directly through D_A1/D_A2; U_AND still needs PUMP_OK (a hang cuts the eFuse); firmware drops every feed | Self-test steps 4b and 6 (FF1 stays HIGH): `ERR_CHG_SELFTEST` at boot and every Idle entry | Latent within one Run; the U_C2, U_IM and D5 cuts are lost until the next Idle entry; current stays bounded by the eFuse I_OL |
| F32d (R5) | U_N33 or U_NP output stuck LOW, or open | Stuck LOW: FF1 cannot set. Open: the pin-33 clear (U_N33) or the pump clear of FF1 (U_NP) is lost | Open U_N33: the pump clear (43-76 ms) on a failed exit; open U_NP: the PUMP_OK term of U_AND still cuts the eFuse on a hang | Stuck LOW: step 4. Open U_N33: step 4b. Open U_NP: step 8 | Availability, or one slower clear until the next Idle entry |
| F33 (R4) | SB signal cable open inside a window | F1 on both channels (sense bypassed) while the charger stays powered | U_C2 (KS pair separate; valid only while row F44 is absent); U_IM; eFuse I_OL | `ERR_ISO_MISMATCH` (FC), `ERR_CHG_TRIP`, `ERR_PACKN_RANGE` | One bounded pulse, as F1 |
| F34 (R5) | F_PK open (at the pack terminal) | Pack positive disconnected from everything downstream; both gate supplies collapse and S_GND turns off; the S_GND body diodes hold pack(-) one diode drop below GND for the BQ29200 supply current from VBAL+, so VC1 - GND = V_cell1 - V_F, positive (calc5 section 1) | - | Board unpowered from the pack; gate B-FPK at build (that VBAL+ is the only remaining source is UNCONFIRMED until B-FPK) | Benign |
| F34b (R7) | Pack-negative open upstream of R_SH (pack-connector negative contact, pack-negative lead, the R_SH pack-end joint), balance plug in, in any state including traction with both boosts running | Board return only through D_VC1 into RB3 (260 Ohm) and the balance midpoint wire: at most 16.2 mA at V_cell2 4.2 V (revision 6: 58 mA through both clamps); RB1A 4.7 kOhm passes at most 0.83 mA into the unclamped VC1_CB pin (calc7 section 1); the board browns out and GND rises toward pack(+); VC1 at -V_F. The S_GND body diodes conduct in the fault direction (anode SGND, cathode PACK-), so S_GND is not an actuator. An open R_SH element is row F34c | RB3 and RB1A limit the current; D_VC1 holds VC1 above -0.3 V (V_F at most 0.25 V at 16.2 mA required: BENCH) | Brown-out; gate B-PKN at build (USB-powered, and on the pack with both boosts running and a bus load, at 25 C and at the coldest ambient) | Brown-out drops every EN to its pull-down. VC1_CB is driven below GND at sub-mA (absolute maximum TODO(verify: TI)); BG-17 is repeated after the event. Revision 5 put D_VM at VMID ahead of RB3/RB1A, which passed 6-17.1 A of boost input current through the balance lead in this event and made D_VM a likely short (rows F47, `calc/fmea_round3_calcs.py` sections 1, 1b) |
| F35 (R6) | SHDN_EF shorted to a HIGH conductor downstream of R_SD | eFuse enabled while ladder bit 1 reads L | As F11 | eFuse-blocking probe on U_MS (section 9.7a), qualified by C-2 | As F11 |
| F36 (R5) | Cut-gap bridge: M2 (pin 10 stubs: eFuse bypass) or M1 (pins 14/15 to Vin-: sense bypass) | M2: as F11. M1: as F1 | M2: as F11. M1: U_C2, U_IM, eFuse | M2: eFuse-blocking probe on U_MS (after C-2). M1: `ERR_ISO_MISMATCH`, sense-path check | D-2 gap insulation (at least 10 MOhm at 50 V), P-M1 at build and C-4 after the first driving session |
| F34c (R7) | R_SH element open (a cracked 4-terminal shunt), pack-negative wire intact | As F34b; in addition KS+ follows pack(-) through R_K1 while KS- follows PACK- near GND, so U_SH1 IN+ and U_SH2 IN- reach about 8.4 V below PCB GND at brown-out (`calc/verify_f34b_ks_ina240.py` section 1), beyond the INA240 common-mode absolute minimum of -6 V (SBOS662C section 7.1; operating minimum -4 V, section 7.3). Both amplifiers share KS+, so both are stressed together | R_K1 (2.2 Ohm fusible) limits the current into the input structure (its behaviour beyond -6 V is not specified, TODO(verify: TI)); the event is self-revealing, because the board cannot run on a 16 mA return | Repair rule: after any R_SH open, replace U_SH1 and U_SH2, then repeat C-2a items 13-14 and T1. In service, a common-mode gain loss above about 25 % latches the two-sided `ERR_IPACK_PLAUS` (calc7 section 10); `ERR_RET_DEGRADED` sees a resistive crack at 5 A or more | An intermittent crack can stress both amplifiers without a repair; a common-mode error inside the gain band stays latent (ruling OR-AB) |
| F37 (R7) | Stage 3 (hold-up) | Withdrawn in revision 7: the revision-6 Stage-3 dump keyed to FF1./Q deadlocked every commanded exit into `ERR_MOD_DRAIN` and, under the S0-5 threshold behaviour, `ERR_MOD_FED` (BT4-TR-01, FM4-4) | - | - | Section 14.4 records the conditions of a re-specification |
| F38 (R4) | High-resistance R_CS1 or CSEL lead (partial crack, resistive joint) | Selects up to 2.5 A (Table 4 monotone in R) | U_C2 (2.65-3.64 A) | `ERR_PROFILE_OC` (I_PACK1 charge above I_set + 0.25 A for 20 ms) | Module over-rating in a regen window until the fault latches |
| F39 (R5) | Firmware drives pin 32 HIGH while commissioning an as-found module, or a State-98 key raises pin 32 while FF1 is set in `CHG_CONFIG` | 2.8 A output | Refusal of pin 32 HIGH while ladder A bit 0 reads HIGH (section 12.4 item 7); `OC_FC` (BENCH_TEST 0); bench supply limit | Host test of both refusal directions | Procedure rule (section 9.2) |
| F40 (R5) | Clamp FET open: Q_X1, Q_X2, Q_RG1, Q_RG2, Q_RB1, Q_RB2; Q_D5 or D_D5S open; U_IM output stuck released or the IMON wire open | One clamp, the D5 cut or the start-into-overload cut lost | The parallel element of each pair; firmware ordering; eFuse I_OL (U_IM) | C-2, B10 and S0-12b only (no readback pins); the D5 comparator itself in every self-test (step 6, now unmasked by D_D5S) | Accepted latent fault; each needs a second fault to matter |
| F41 (R4) | Threshold or filter network fault: R_T1a, R_T2a open (threshold 0 V), R_T1b, R_T2b open (threshold 3V3), R_F1, R_F2 open, R_D5c open, R_D5b open | Comparator blind or permanently tripped | Self-test | Steps 1, 4, 6, 7 (signal-side injection with ADC readback) | Detected at the next Idle entry |
| F42 (R4) | S_GND gate parked between its conduction threshold (1.2 V) and the Q_D or Q_R threshold (1.43-3.0 V) by a leaky Q_Ak or a degraded R_GUk | Partial sense bypass with S_CHG permitted and the readback showing off | U_C2 | Sense-path check; C-2 measures the band | Accepted residual |
| F43 (R5) | Short inside SB or the harness between pack-positive copper (lead, tap pads, F_T inputs) and SGND, PACK- or the pack-negative conductor (solder splash, insulation, vibration) | Direct pack short: 174-592 A prospective at an ASSUMED R_int of 40-10 mOhm; any loop below 0.37 Ohm exceeds 20 A (calc5 section 1) | F_PK 20 A at the pack terminal (in the loop since revision 5) | Fuse open: board unpowered | Pack leads between the cells and the pack terminal remain protected only by the pack PCM (trip not known, facts_prior section 9) |
| F44 (R5) | KS+ shorted to KS- downstream of R_K1/R_K2 (harness insulation, LB connector) | OUT1 = OUT2 = 1.650 V at any current: I_PACK1 = I_PACK2 = 0; U_C1, U_C2 blind; the injection self-tests and `ERR_IPACK_XCHK` pass; `ERR_SGND_OPEN`, `ERR_RET_DEGRADED`, `ERR_PROFILE_OC` never evaluate. The short carries 0.82 mA at 7.2 A | eFuse I_OL; U_IM; Ag105 OC trip (after S0-2 and D-3) | `ERR_IPACK_PLAUS` at the first traction above 0.4 A of BT current (pack discharge at least 0.54 A, calc6 section 8); self-test step 5 fails when BT_CURRENT predicts a discharge; regen windows refused until a plausibility pass; `ERR_ISO_MISMATCH` in FC windows; C-2 short test | Latent from boot until the first traction above 0.4 A of BT current; on the 23 recorded sessions that level occurs in 19 (the revision-5 1.0 A level in 3, `calc/bt3_bag_scan_plaus.py`); regen windows stay refused throughout the latency, and `ERR_ISO_MISMATCH` covers FC windows |
| F45 (R5) | Slow 3V3 collapse through 0.84-1.57 V inside a window | LVC outputs track VCC: the S_GND bond can begin while EF_EN is still above V_SHUTF (0.8 V min), so the module can be fed while bonded for the rail fall time (`calc/bt2_logic_seq_enum.py` section 2b) | Not established | Gate B11d (3.3 V to 0 V in 10 ms inside an FC window: eFuse off before both SG lines go H) | If B11d fails: fit a 3V3 supervisor that pulls SHDN_EF and N1 LOW below 2.9 V (TODO(select)) |
| F46 (R5) | Flex crack of an MLCC under a soldered tap (revision 4: channel-2 VBUS tap on C-D2) | Resistive VBUS-GND path (2.56 W at 100 Ohm, below every trip) | Eliminated: no tap on an MLCC termination (M7, section 5.7) | C-4 tap inspection | - |
| F47 (R7) | D_VC1 short, fitted reversed, or a solder bridge across it | VC1 at GND (short) or at about +V_F (reversed); cell 1 drains through RB3 at 16.2 mA (0.39 Ah per day, 67.6 mW in a 0.1 W part). VC2-VC1 then equals V_pack (8.40 V at CV, 8.50 V at LIMIT_V_BATT_MAX) or V_pack - V_F, above the SLUSA52C 7.1 VC2-VC1 absolute maximum of 8 V whenever V_pack exceeds 8.0 V (short) or 8.0 V + V_F (reversed). The BQ29200 then reads cell 2 above VPROTECT and asserts OUT if it survives. Revision 6 also fitted D_VCB, whose short drained cell 1 at 42 mA and, with balancing enabled, let the top-cell switch conduct VBAL+/(100 Ohm + RCB2) from VDD into the grounded VC1_CB, so that VDD fell below 4 V for RCB2 below 91 Ohm at 8.4 V (FM4-1); D_VCB is deleted and RB1A raised to 4.7 kOhm, so no fitted part can ground VC1_CB any more; a solder bridge of BQ29200 pin 3 to GND would draw 0.89 mA from cell 1 through RB1A, while the top-cell switch path (VDD through RCB2 into VC1_CB) does not pass RB1A and remains the FM4-1 hazard for that build defect, which gate C-1 checks (VC1_CB to GND not below 4.4 kOhm) | RB3 (series, on the cell side) | `ERR_CELL_MISMATCH` on the VC1 tap: the mismatch reads about V_pack, independently of the BQ29200 (first evaluation after the power-up); BQ29200 OUT (self-test step 4) if the IC survives; C-1 diode-mode check before the balance plug is first connected | Replace the BQ29200 after any such event with V_pack above 8.0 V (overstress; TODO(verify: TI)) and repeat BG-17b. Gate C-2a item 5 does not create this event (revision 8: it grounds the tap junction on LB, not D_VC1). A cracked CBL2 beside the D_VC1 joint is a further cause (M16); C-1 reads VC1 to GND by resistance. The drain continues with the balance plug in and the Teensy unpowered, so the storage rule of section 15 applies |
| F48 (R6) | VBATN_X shorted to pack positive, VBT, VBUS, V-MOT or another positive conductor (chafe, splash), either mode | Bonded: pack(+) through the short, VBATN_X, F_VX, the Ag105 sense R_s, Vin- (PCB GND), S_GND and R_SH; 39-252 A prospective without F_VX (10-63 x I_DIS). Charge mode: U_C1 trips and re-bonds, which moves the current into the same loop | F_VX 4 A fast-acting at the module end opens; U_C1 cannot open the loop (its only actuator is the bond) | C-1 and C-4 insulation test (VBATN_X to pack positive at 50 V or more, at least 10 MOhm, harness flexed); after the event as F14 | Module sense I2t during the F_VX clearing time TODO(verify: fuse datasheet, Silvertel); the lead and SB copper are upstream of F_VX and protected |
| F49 (R7) | Q_MD or R_MD open, MD_G wire open or shorted to GND (R_MDS limits the U_MDI output to 3.3 mA), or an extra capacitance on VCHG-IN_M | The dump is lost; the node decays through R_MB (16 V to 9 V in at most 0.42 s at 221 uF) | R_MB | `ERR_MOD_DRAIN` at the first exit (pin 8 not LOW within 10 ms): regen and FC windows refused for the power cycle | Availability only |
| F50 (R8) | Q_MD drain-source short, U_MDI output stuck HIGH, or MD_G shorted to a HIGH conductor | The dump stays on while the node is fed: 1.07 A at 16 V and 1.19 A at 17.5 V into R_MD (17.1-20.4 W) on top of the module input. At the eFuse start the inrush into the node adds to it: 1.50-2.48 A at the end of the ramp (`calc/bt5_transient_sim.py` section 4) | U_IM or the eFuse start into overload at the eFuse start on most corners (`ERR_CHG_TRIP`; the exception is FC 15.9 V, C_mod 100 uF, 4.17 V/ms); in an FC window with the module charging, `OC_FC` (FC bus at least 1.68 A, BENCH_TEST 0) and U_IM (eFuse input 1.53-2.16 A) (calc8 section 2). Revision 7 stated 'not U_IM', which held for the steady current only (BT5-TR-03) | `ERR_MOD_DUMP_ON` in the pin-32-LOW dump check that precedes the first window of either type in every power cycle (section 9.7b; healthy step at most 0.232 A, stuck at least 1.09 A), or `ERR_CHG_TRIP` from U_IM at the same start; C-2b item (f) with Q_MD jumpered | A fault that arises after the dump check: in an FC window with the module Fully Charged, 17-20 W in R_MD until the Fully-Charged exit; in a regen window U_IM trips the first pulse on most corners, and on the residual corner R_MD takes 0.46-1.45 J per pulse until the next power cycle or until it fails open (row F49); the R_MD part must fail open (Table 7) |
| F51 (R6) | LB 3V3 tap open while the Teensy runs | Bonded and eFuse off (fail-safe), but the cross-lock and the four D-BC-RG clamps release (fail toward permit on D-BT-SQ and D-BC-RG) | eFuse off (SHDN_EF on R_SDP); firmware drops pins 30 and 32 | Both ladders read code 0: `ERR_CHG_LADDER` within 3 iterations; pin 8 consistency | At most 3 iterations of D-BC-RG and D-BT-SQ on their Teensy pins with the eFuse off; with a latent F11 as well, a bus feed into the module for those iterations (gate B11e) |
| F52 (R6) | Pin-38 channel failed low (upper divider leg or ADC input open) | `ERR_VCHG_FED` blind and the V_chg-below-11-V entry precondition always passes; F17 would become latent | - | `ERR_VCHG_SENSE`: pin 8 HIGH while V_chg reads below 8 V for 3 iterations, or two consecutive VOK pulses with EF_EN H for 20 ms and V_chg never above 12 V; every FC window and configuration check needs V_chg at or above 13.5 V | Regen windows refused once detected; a failure that arises inside a window is latent until the next pulse |
| F53 (CC-11) | UC1_N conductor open between LB and SB (D_A1/D_A2 lose their drive), or one D_Ak open | The direct U_C1 path to the Q_A gates is lost; U_C1 still clears FF1 through D_NC1 and N1, which drops FF1Q_SB and re-bonds | U_C1 through N1 (about 76 us plus the gate rise, Table 11) | None in service: self-test step 7 sees FF1.Q L and both SG bits H whichever path acted; gate C-2a item 26 tests the direct path with D_NC1 lifted (revision 7, CC-B14) | Accepted latent fault, benign alone (the direct path is the backup for a stuck FF1, row F7 and F32c) |
| F54 (R8) | VC1 tap lead open, R_VC1b open or shorted, R_VC1c open, C_VC1 shorted, or the tap lead chafed to GND | Pin 20 reads 0 V, or up to about 2 x VC1 (R_VC1b open) | R_VC1a at the tap end limits a lead-to-GND chafe to at most 22 uA from VC1 (5.7 mV through RB3); revision 7 quoted 42.5 uA (8.5 V / 200 kOhm), which is the VC1 drain and not the pin-20 stress (FM5-2) | `ERR_CELL_MISMATCH` (a dead tap reads a mismatch near V_pack); C-2a item 5 | Fails toward window refusal; the BQ29200 OVP is unaffected |
| F54b (R8, R12) | VC1 tap lead or MS lead chafed to a positive conductor (VBT 8.5 V, VBUS 16-17.5 V, VCHG-IN or VCHG-IN_M up to 21.5 V) | In revision 7 the lead node was pin 20 or U_MS IN+ itself, so a chafe forced 8.5-21.5 V onto an i.MX RT pin or onto the TLV3011B input (7 V absolute maximum, SBOS300C section 6.2) (FM5-2, BT5-BO-02). Revision 12 (BT8-DS-01, BT8-DS-02): with the revision-8 resistors fitted, pin 20 is driven by 0.22-0.81 mA, outside the IMXRT1060CEC Table 7 rating (OVDD + 0.3 V, no injection current given); U_MS IN+ has no clamp to V+ (SBOS300C section 6.2 note 2, section 9.4.4) and follows the chafe voltage (8.5-21.5 V against 7 V) | R_VC1c (22 kOhm) limits the pin-20 current to 0.22-0.81 mA (calc8 section 5). R_MS3 limits no current into a healthy U_MS input (10 pA, so the 3V3 rail does not rise) and limits a U_MS that fails short to at most 0.83 mA (calc12 section 9). Both leads rely on segregation: the sleeves of section 5.7 item 4 make the chafe a two-insulation fault | Pin 20 at full scale: `ERR_CELL_MISMATCH`; MS lead high: pin 8 HIGH in the bonded mode (`ERR_MOD_FED` or `ERR_MOD_SENSE` (a)); C-1 and C-4 insulation tests | Double insulation fault: U_MS overstress accepted (F56 class); pin-20 pad survival at 0.22-0.81 mA TODO(verify: IMXRT1060CEC). The revision-8 'injection-limited' claim is withdrawn for the MS lead (FM5-2 / BT5-BO-02 stay FIXED for pin 20 and PROFILE current only) |
| F54c (R8, R12) | BAL_OK, PROFILE, IMON, EF_FLT_N, SHDN_EF or MD_G lead chafed to a positive conductor | BAL_OK: U_LA input above its 6.5 V absolute maximum for a chafe above 9.5 V. PROFILE: the pin-10 net driven through R_PGL. IMON: U_IM IN- has no clamp to V+ and follows the chafe (SBOS300C section 6.2 note 2). EF_FLT_N: U_LA input through its pull-up only. SHDN_EF, MD_G: the LVC output has no positive clamp and is pulled to the chafe voltage through 1 kOhm (SCES214AF section 5.1). CB end (revision 12, BT8-DS-02): the TPS26631 SHDN and IMON pins at 8.5-21.5 V against 5.5 V (SLVSE94G section 6.1); the Q_CS and Q_MP V_GS up to 21.29 V against 20 V, and the charger profile switches; the Q_MD gate at the chafe voltage (calc12 section 9) | R_BL3 with R_BL2 (U_LA input at or below 6.5 V up to a 9.5 V chafe). R_PGL, R_IMF, R_SD and R_MDS limit the LB-side current only (U_IM failed short at most 1.82 mA); none sits in series with the CB-end pin of its lead | Sleeve segregation: the SHDN_EF, CB-LB and J-BL/M16 sleeves contain no conductor above 3.6 V (section 5.7 item 4); C-1 and C-4 insulation tests of every sleeved lead, and (revision 12) the lead-to-lead pairs | Segregation is the sole protection of SHDN_EF, MD_G, PROFILE, IMON and EF_FLT_N at both lead ends, and of BAL_OK above 9.5 V (a chafe needs two insulation failures; accepted, and accepted by the operator on 2026-11-09 for SHDN_EF, MD_G, PROFILE, IMON, MS, EF_FLT_N and the VC1 tap at both lead ends, with no clamps added). The revision-8 'LVC IOK' TODO is closed as negative (revision 12) |
| F55 (R7) | MS sense lead shorted to SHDN_EF (adjacent flying leads) | The joined node reads 2.95-3.15 V while EF_EN is H and 0-0.19 V while EF_EN is L, whatever the module node; the eFuse still switches; pin 8 follows EF_EN, so the positive control passes, the drain wait returns at once, the eFuse-blocking probe reads cold on a bypassed eFuse and `ERR_MOD_FED` cannot assert (`calc/verify_ms_shdn_short.py` section S1) | Harmless alone; harm needs an independent eFuse bypass (F11, F35, F36-M2) and a feed while bonded | `ERR_MOD_SENSE` (c): the exit hold check reads pin 8 LOW 50 us after the feed drop of the first dump check, configuration check or FC window of a power cycle, where EF_EN is H at the write (a healthy fed node holds it HIGH for at least 170 us at C_mod 47 uF, calc8 section 1); a regen exit between pulses is not evaluated (revision 8); `ERR_VCHG_SENSE` rule (a) at the first EF_EN rise with V_chg below 8 V (UNCONFIRMED: needs the unfed V_chg below 8 V, C-2b); routing rule of section 5.7 item 4 (revision 12: SHDN_EF in its own sleeve, so the short needs two insulation failures; C-1 and C-4 lead-to-lead tests); C-2b repeated at C-4 | Latent only if the U_MS open-drain fall exceeds 50 us (TODO(verify: SBOS300C), measured at C-2b item (g)) |
| F56 (R7) | R_MS2 or its GND return open | U_MS IN+ follows the module node through R_MS1 (13.5-21.5 V against the 7 V absolute maximum, SBOS300C section 6.2; at most 0.215 mA); while undamaged, U_MS reads HIGH whenever the node is above about 1.3 V | R_MS1 limits the input current | `ERR_MOD_DRAIN` at the first exit (fail-safe while U_MS survives); if the overstressed U_MS later fails LOW, the positive control of the next window (`ERR_MOD_SENSE` (b)) | A U_MS that fails LOW during an exit re-bonds the fed module: the F10 class, about 24 mJ (calc5 section 10); accepted, no clamp added |
| F57 (R9, R10) | Unpredicted purge (a source loss that the predictor did not announce, or announced late, or recognised after the onset as UNKNOWN or `purge_active`) while a session holds BT_BUS open | FC-only bus falls at 3.9-6.2 V/ms with the charger running, 2.57 V/ms on the auxiliary load; the eFuse turns off at UVLO in about 1.0-1.1 ms; a slow FC fall can give a warm eFuse restart before the latch (pc sections 1-3) | `ERR_FC_ONLY_COLLAPSE` latches State 99 at 1.4-50.3 ms, or at the predictor event if earlier (PI-4, revision 10: no commanded exit after a recognised onset; OPEN in 4860 of 4860 cases, calc10 section 5); FC_BUS LOW before the earliest FC recovery at 80 ms, or with the bus at 12.04 V or more (Table 23); U_IM and row F10 bound a warm restart | `ERR_FC_ONLY_COLLAPSE` on pin 38 or pin 26 (diverse readings) | Shutdown accepted by ruling OR-SC; no damage path found (Table 24), UNCONFIRMED until gate W2c; at most one event per power cycle |
| F58 (R9) | Wrong purge permit from the predictor (the operator's design, ruling OR-P) | As F57 at each purge that falls inside a session | As F57 | As F57 | Availability only; the predictor is outside the scope of this document |
| F59 (R9) | D-BT-EN conducts later than the T_lead basis (t_D_ON above 12 ms; no RT1987 maximum) | A predicted onset arrives before BT_BUS conducts; the auxiliary-load bus sags with both source pairs commanded closed | SC-1 reading (b) armed to the purge end (revision 10); UV_BUS (armed) latches 36.7-103.4 ms after the onset across the r6 sweep under its dwell alone; a late D-BT-EN with t_D_ON up to 100 ms is BENIGN or OPEN at the FC recovery in every case (r6 section 1) | `PURGE_LEAD_SHORT` event (section 9.11.2); gate W2a measures the conduction time | A safe State 99 or a BENIGN ride-through; W2a NO-GO raises T_lead |
| F60 (R9) | Pin-38 or pin-26 channel failed while a session holds BT_BUS open | One reading of `ERR_FC_ONLY_COLLAPSE` is blind | The other reading | Before a window: pin 38 high latches `ERR_VCHG_FED` in the bonded mode; pin 38 low is row F52 (`ERR_VCHG_SENSE`; `chargerHasPower()` needs 13.5 V); pin 26 low or high latches the existing UV_BUS or OV_BUS | A failure that arises inside a window leaves one reading until the window ends |
| F61 (R9, R10) | Firmware defect: the share loop, the selector or the load guard writes pin 27 or 28 inside the SC-8 interval (revision 10: from the first entry write to the BT_BUS conduction after the exit) | Pin 27 LOW: the bus loses its source and UV_BUS disarms (ino:7338-7356). Pin 28 HIGH: Q_X1 holds EN_BE_X | Q_X1 (pin 28); `ERR_FC_ONLY_COLLAPSE`, which does not read `uvBusArmed` (pin 27) | Write-log host test (section 12.11) | Safe State 99; firmware rule (section 12.4 item 7) |
| F62 (R9) | Traction step inside a State-2 standstill window that outruns the command-keyed exit, or (revision 10) a launch released before D-BT-EN conducts | FC-only bus carries traction plus the charger input until the feed drop, or traction alone from the BT_BUS write to the conduction (28-47 ms) | `OC_FC` 1.4 A on one sample (State 99); the exit drops the feed in the iteration of the command; the motor command is held at 0 A until BT_BUS has been HIGH for the conduction bound (section 9.7 exit step 4) | `OC_FC`; W2b records the peak FC_CURRENT between the write and the conduction | Safe shutdown; the bus power of a launch from standstill is small (UNCONFIRMED, gate W2b) |
| F63 (R10) | BT_BUS never conducts after a prediction exit: Q_X1 drain-source short, R_S28 or the EN_BE_X lead open, or the FCQ net stuck HIGH after a feed drop (a new fault inside the window; a pre-existing one fails the V_chg-below-11 V entry and latches `ERR_VCHG_FED`) | The FC carries the bus alone at the onset; under the UV_BUS dwell alone the H-20 could recover through a boost with EN HIGH into a bus at 8.2-11.7 V (5 cases at 80 ms, 4 at 100 ms, r6 section 1; the TP0010 class) | SC-1 reading (b) armed from the BT_BUS write to the declared purge end, 12.0 V, no dwell (revision 10): 1 case at 80 ms (bus 11.74 V, FC_BUS LOW at 80.3 ms), none at 100 ms | Latent until the first purge; detected at C-2 and B10 only (no Q_X1 readback); the latch at the first purge after the fault | Safe State 99; same contributor class as an open D-BT-EN channel on the present board (any open BT channel during a two-source purge); TPS61288 restart after VIN UVLO with EN HIGH TODO(verify: TI), open item 33; gate W2c sub-step |
| F64 (R11) | A boost enable LOW at an FC-fed session: the State-98 `B` or `F` key before a request, or a firmware defect that writes pin 3 or 4 LOW | BT_REG LOW: the exit's BT_BUS re-close would land on a disabled TPS61288 (`busHotPlugUnsafe(BT_REG_ENABLE)` is false with the boost disabled, ino:13043-13045) and SC-1 reading (b) latches State 99 at the predicted onset on a healthy board (`calc/bt7_logic_seq_enum.py` section 6). FC_REG LOW: entry step 5 would drop BT_BUS onto an FC-passthrough bus | Entry condition FC_REG and BT_REG HIGH on two settled iterations (code 11); BT_REG LOW at exit step 4 latches `ERR_FC_ONLY_COLLAPSE` with no BT_BUS write; the `B` and `F` write forms refused while a request stands (section 12.4 item 7) | Pin readback each iteration; host test | Refusal or safe State 99; the RT1987 blocks reverse current, so no damage path (bt7_logic_seq_enum section 6) |
| F65 (R11) | Stale Pi EMS node: `charge_goal` used as the regen gate and latched through stops (`sdp_ems_node_2026-10-28B.py`:293-319) | Revision 10: a D-s window at every stop after braking that the EMS did not request (112.8 s of standstill latch on the recorded sessions, `calc/bt7_req_origin_output.txt`) | The request needs the flag 0xA5 in command byte 20, which the deployed nodes never send; refusal code 15 | Telemetry code 15; gate W2e with the deployed node | No window opens; no hardware exposure |
| F66 (R12) | MD_G shorted to SHDN_EF (two driven outputs; adjacent in the revision-8 CB-LB sleeve) | U_MDI and the EF_EN path drive opposite levels through R_MDS and R_SD (1 kOhm each), so the joined node sits at 1.55-1.68 V in both EF_EN states (calc12 section 1). SLVSE94G section 6.5 guarantees the eFuse neither off (below 0.8 V) nor on (above 2.0 V) there. eFuse off: no window feed. eFuse on: EF_EN no longer switches it, so the FF1 hardware trips lose this actuator (the F11/F35 latent class), and Q_MD sits at a fixed 1.55-1.68 V gate; a Q_MD whose threshold lies near that level runs in linear mode at up to 4.0-5.1 W, and for I_Q at or below about 0.31 A no detector acts in an FC window (dump-check step 0.4 A, `OC_FC` above 0.314-0.412 A on BENCH_TEST 0 only, U_IM above 0.574-0.672 A; `calc/bt8_fmea_rev8_sleeve.py` section 2). Before revision 7 (no R_MDS) the LVC output won and the short was a loud inverted enable (0.08 V / 3.22 V) | Revision 12: SHDN_EF runs in its own sleeve (section 5.7 item 4), so the short needs two insulation failures | eFuse off: `ERR_MOD_SENSE` (b) at the first dump check. Q_MD near full enhancement: `ERR_MOD_DUMP_ON` (about 1.07 A, row F50). Build: C-1 and C-4 lead-to-lead insulation tests; C-2b item (h) injects the short | Double insulation fault: Q_MD destruction when its V_GS(th) range covers 1.55-1.68 V (Table 7 records the range; the SOT-23-class R_thJA of 125-350 K/W is ASSUMED, so the bound is UNCONFIRMED until selection); accepted under the double-insulation rule of row F54c, and accepted by the operator on 2026-11-09; the Q_MD selection still records V_GS(th), the linear-mode SOA and V_GSS |

Notes:

1. The regen loop (bus to D-MT-EN to V-MOT to D-BC-RG to the charger, with BT_BUS closed) requires one of the following:
   both VOK channels false-OK (two failures; separate taps, each with a bus-present guard, and the disagreement detector);
   a D-BC-RG power-stage short together with an eFuse short (F11, F35, or an M2 bridge F36), which is two failures,
   because VOK gates only those two elements; or a **D-BC-FC power-stage short alone** (F17), which feeds VCHG-IN from VBUS
   at every VOK assert. The last path is one fault; only `ERR_VCHG_FED` closes it, by detecting the short before any
   window opens. The D-BC-RG/eFuse pair closes the loop only inside a Stage-2 regen window. In the bonded mode the D-BT-SQ
   cross-lock and R_KA (about 14 mA) remain, so an ML0227-class bonded runaway still needs three faults (for example
   F17 with an eFuse short and F6).
2. The FC-window loop requires a D-BT-EN short and is cut by D5 above 0.31-0.59 A. A circulating flow below the D5
   threshold remains bounded by the regulated pack current, the eFuse and the FC governor. G1 does not resolve flows
   below its threshold I_G1 (working figure 0.35 A, section 12.7), so a flow below the D5 range is bounded, not cut.
3. F12 and F12b are assembly or procedure faults. Gates C-1 and C-1b must pass before every charge session.
4. Revision 6 removes the two unfused pack-direct paths that revision 5 had: the balance midpoint conductor now reaches
   PCB GND only through RB3 (clamped by D_VC1) or RB1A 4.7 kOhm (at most 16.2 mA and 0.83 mA in revision 7, rows F34b
   and F47), and VBATN_X is fused at the module end (row
   F48). The HR3 two-failure count of note 1 for an eFuse bypass holds only once the probe of section 9.7a is
   qualified by the C-2 injected-bypass gate; before that, an eFuse bypass is latent with no in-service detector.

## 12. Firmware specification

None of the changes below is made by this study. Each needs the IO CSV amendment first and then the orchestrated-feature
procedure with its tests.

### 12.1 Pin map

Table 15 assigns all ten spare pins and pin 8 (facts_board section 7.2). Pins 2 and 7 stay avoided. Pin 8 (old net
ENC_B, RENC2 pull-up to 3V3 possibly still fitted) is used as an input only: a pull-up holds no enable, so the
facts_board objection to it (an output held HIGH during reset) does not apply. Gate P8 confirms that nothing else
drives the ENC_B net after the 2026-08-16 encoder reroute; if P8 fails, pin 2 is checked the same way. The code names are proposals
for the `Code Name` column of `references/Scale Car Teensy IO - IO.csv`.

Table 15. New Teensy pins.

| Pin | Header | Code Name | Dir | Function | Level without firmware |
|---|---|---|---|---|---|
| 33 | J2 47/48 | `CHG_MODE_REQ` | OUT | Rising edge sets FF1 (charge mode); LOW or high-Z clears it (through U_P33) | LOW (R_P33 at the U_P33 input) |
| 34 | J2 45/46 | `CHG_PUMP` | OUT | Toggled once per `loop()` iteration while charging is permitted | LOW (R_P34); static = no arm |
| 35 | J2 43/44 | `CHG_TEST_INJ` | OUT | Self-test injection (U_C1 or U_C2 by pin 10; D5 always) | LOW (R_P35) |
| 10 | J1 23/24 | `CHG_PROFILE` | OUT | HIGH = FC profile (1.25 A, 13.82 V); LOW = regen profile (1.75 A, 18 V); also selects the injection target | LOW (R_P10) |
| 20 (A6) | J2 13/14 | `CELL1_V` | AIN | VC1 tap: V(pin 20) = VC1 / 2 (R_VC1a/R_VC1b 200 kOhm), two-point calibrated at C-2a; feeds `ERR_CELL_MISMATCH` (revision 6 used pin 20 for WDOG1_B) | - (input) |
| 16 (A2) | J2 21/22 | `I_PACK1` | AIN | SIG1 (U_SH1 after R_F1), 50 mV/A about 1.65 V; discharge lowers it | - |
| 17 (A3) | J2 19/20 | `I_PACK2` | AIN | SIG2 (U_SH2 reversed, after R_F2); charge lowers it | - |
| 23 (A9) | J2 07/08 | `V_PACKN` | AIN | 1.7286 V + 0.4762 x V_PACKN at 3V3 = 3.30 V | - |
| 21 (A7) | J2 11/12 | `CHG_STAT_A` | AIN | Ladder A: FF1.Q, EF_EN, EF_FLT_N, PUMP_OK, BAL_OK | - |
| 22 (A8) | J2 09/10 | `CHG_STAT_B` | AIN | Ladder B: SG1_ON, SG2_ON, CH1_OK, CH2_OK, D5_N | - |
| 8 | J1 19/20 | `CHG_MOD_COLD_N` | IN (`INPUT_PULLUP`) | U_MS: LOW = module input node below 8.69-9.15 V (cold); HIGH = fed, or the sense path open | HIGH (pull-ups) |

The existing pins 28-32 keep their names. Their commanded levels are no longer the effective levels: firmware derives
EN_BE = p28 AND NOT p31 and, in Stage 2, EN_RG = p30 AND VOK (from ladder B), and must not infer an effective enable from
`digitalRead()`. Pin 39 (`RGN_VOLTAGE`) measures V-MOT through the chopper reference divider R1-SNT/R2-SNT (SCH net RGN-V)
and reads 0.85 x true until the M-R2 calibration.

### 12.2 Build flags

1. **`PACK_RETURN_CHANGEOVER`** (new, default 0): 1 enables the mode manager and the IC1 faults. 0 keeps fw v37 rev 2
   behaviour.
2. **`IC1_STAGE`** (new, 1 or 2): 1 permits FC windows in State 1 or State 98 (and in State 2 at standstill with
   `IC1_FC_RUN_STANDSTILL` 1, revision 9), configuration checks and State-98
   commissioning only, holds pin 30 LOW and compiles the regen window out; 2 adds the regen window.
3. **`AG105_VBATN_ISOLATED`**: its declared meaning (ino:5058-5062) is true only in the charge mode under IC1. Ruling OR-L
   decides whether to retire it in favour of `PACK_RETURN_CHANGEOVER` or to redefine it. Until then, IC1 builds set it to
   1 only together with `PACK_RETURN_CHANGEOVER` 1. Setting it to 1 lifts the fw v37 refusal of the State-98 `5` key;
   the mode-manager refusal of section 12.4 item 7 replaces that refusal.
4. **`FC_CHARGE_ALLOWED`**: Stage 1 needs it at 1. This reverses the regen-only charging policy of every fw v31-v37
   build (ino:2600-2616) for the FC window of section 9.7 only (ruling OR-W).
5. The fw v24 dynamic reg 0x02 policy and the `pollAg105()` configuration writes compile out when
   `PACK_RETURN_CHANGEOVER` is 1. So does the State-2 cruise FC branch of `chargingControl()` (ino:15503-15506); the
   close path (ino:15507-15527) stays.
6. **`IC1_FC_RUN_STANDSTILL`** (new, revision 9, default 0): 1 admits the State-2 standstill FC window (variant D-s,
   section 9.11.7). It is set to 1 only after gate W2b.

### 12.3 `setup()`

1. Drive pins 33, 34, 35 and 10 LOW in the same block that drives the RT1987 enables LOW (ino:6709-6715), before the SD
   probe and Ethernet. Pin 20 needs no `pinMode()`: the Teensy core `analogRead()` clears the pad keeper
   when it finds the reset state PKE = 1, PUE = 0 (Teensy core 1.62.0 `cores/teensy4/analog.c` lines 111-119), so the
   keeper does not load the 122 kOhm tap source (revision 8, BT5-BO-01); WDOG1_B is not routed (revision 7).
2. Configure the RTWDOG (ruling 5); WDOG1_B is not used (revision 7). Arm the
   watchdog after `Ethernet.begin()` returns, or bound `Ethernet.begin()` with a timeout: a `USE_ETHERNET 1` build hangs
   in `Ethernet.begin()` with no link (CLAUDE.md fw v37 addendum). The watchdog timeout is TODO(calibrate); with the
   non-blocking self-test no armed-state operation is longer than one loop iteration except those of item 3.
3. Before the watchdog is armed in any state, move every blocking operation longer than its timeout out of the armed
   states: the interrupt-masked EEPROM commit (duration TODO(verify: PJRC)) and the SdFat close ([EVAL] section 5.1,
   facts_prior section 10 item 7).
4. Run the boot self-test of section 9.3 (steps 1-9) before the bring-up. Read the reset cause.
5. Start the continuous pump only after the self-test passes; the self-test's own run and stop requests in steps 2, 3
   and 8 are the only pump activity before then. Configure pin 8 as `INPUT_PULLUP` (MOD_COLD_N) and pin 5 as
   `OUTPUT_OPENDRAIN` (MPPTD, section 12.5 item 3) in the same block as item 1.

### 12.4 Mode manager

A new module `chgModeTick()` runs every iteration after `detectFaults()` and owns pins 33, 34, 35, 10 and, under
`PACK_RETURN_CHANGEOVER`, pins 5 and 30 and the FC_CHARGE write path of pin 31 (item 7); it also reads pin 8. It has the states `CHG_BONDED`, `CHG_SELFTEST`, `CHG_ENTERING`, `CHG_REGEN`, `CHG_FC`,
`CHG_CONFIG`, `CHG_EXITING` and `CHG_INHIBITED`.

1. **Pump.** Pin 34 toggles once per iteration in every state except `CHG_INHIBITED`, State 99 phase 3 and the stop
   intervals that the self-test requests. It is written only from `loop()` context, never from an ISR or an
   IntervalTimer (host test).
2. **Profile and cold module.** Pin 10 and pin 5 change only while ladder A bit 1 (EF_EN) reads LOW and pin 8 has read
   LOW for at least 20 ms (module cold). Every window entry (pin 33 rise) needs the same cold-module condition.
3. **Entry and exit.** Sections 9.5-9.7a, with the command-step arm of ruling OR-V' (I_cmd at or below -2 A on two
   consecutive drive-controller samples, 4 ms), the [RER] rate limit (at most 20 transitions per minute) and the 200 ms release dwell. The
   regen arm is evaluated on every drive-controller sample, not in the 50 Hz `chargingControl()`. Every commanded exit
   drops the feed (pin 30 or FC_CHARGE), applies the exit hold check of pin 8 under its precondition (section 9.5 exit step 1), waits until
   pin 8 reads LOW on two successive iterations (deadline T_drain,max: the later of 10 ms and 4 iterations after the
   feed drop, capped at 30 ms; `ERR_MOD_DRAIN`) and only then sets pin 33 LOW. Window types are mutually exclusive: the only path
   from `CHG_FC` or `CHG_CONFIG` to `CHG_REGEN` is through `CHG_EXITING` and `CHG_BONDED` (ruling OR-7).
4. **Consistency.** Every iteration, decode both ladders and read pin 8. A decision uses only a settled reading (two
   identical decodes on successive iterations). An undecodable raw decode on 3 consecutive iterations, or a settled
   mismatch with the commanded state on 3 consecutive iterations, latches `ERR_CHG_LADDER` (counted in iterations,
   section 7.7; the 30 ms cap applies to the entry and exit confirmations) and ends any window. When both ladders decode
   code 0 (the LB rail is lost and the cross-lock with it, row F51), pin 32 is set LOW at once. Otherwise the commanded
   exit runs first (feed drop, drain wait, pin 33 LOW, bonded confirmation) and pin 32 is set LOW after it, as section
   9.9 orders it, so that D-BT-SQ never opens under charge current (revision 7, BT4-LS-04). In the bonded mode, outside the drain interval after an exit and outside the probe, pin 8 must read
   LOW: a HIGH on 3 consecutive iterations latches `ERR_MOD_FED` when V_chg reads 9 V or more, and `ERR_MOD_SENSE`
   otherwise. The compared bits are FF1.Q, PUMP_OK, SG1_ON and
   SG2_ON. EF_FLT_N is compared only while EF_EN reads H, and is masked from the EF_EN rise until V_chg has been at or
   above 13.5 V on two settled iterations, and again after any V_chg excursion below 13.0 V (the eFuse asserts FLT
   throughout UVLO and for 0.5-0.7 ms after it, SLVSE94G section 6.6; with the CSS 5.6 nF of D-BC-RG and D-BC-FC the FLT
   LOW interval at entry is 1.16-1.40 ms, `calc/bt2_datasheet_reverify_calcs.py` section 1; a CSS change requires the
   mask to be re-derived). Outside the mask, EF_FLT_N L is a trip. CH1_OK, CH2_OK and D5_N are hardware-driven and are
   not compared. EF_EN is checked by implication: EF_EN H requires FF1.Q H, PUMP_OK H and either pin 30 H with both
   CHk_OK H, or FCQ H. BAL_OK L refuses window entry.
5. **Blocking calls.** No EEPROM commit, SD close or `Ethernet.begin()` in any state in which the watchdog is armed
   (section 12.3 item 3). Any block longer than about 40 ms stops the pump and clears FF1 in hardware; the mode manager
   treats that as a trip. An iteration that writes a pin-33 edge, or the first iteration of an exit drain, defers the SD
   drain (`logDrainTick()`) and the Ag105 I2C poll to the next iteration (FM3-3), and the iteration-time histogram is
   recorded at gates W1 and V2-4.
6. **Interaction with existing owners.** Under `PACK_RETURN_CHANGEOVER`, `chargingControl()` keeps the FC window limits
   (F1 gate, `FC_CHG_MAX_MS`, the dwell lockout) and calls the mode manager around `assertFcChargeEnable()`; its cruise
   FC branch compiles out, and every `REGEN_ENABLE` and `MPPT_DISABLE` write in it compiles out: the charge_goal-branch
   writes (ino:15304, 15308), the whole regen branch body (ino:15338-15362, including the only HIGH writer of pin 30 at
   ino:15357 and the pin-5 write at ino:15358), the backoff and cruise writes (ino:15375, 15377, 15395, 15524) and the
   MPPT tail (ino:15545-15556). The mode manager is then the sole writer of pins 5 and 30, in State 2, in State 1 and in
   the State-98 D/Y/W profiles (`chargingControlGated()`, ino:7950, ino:9339). Revision 5 listed only the four LOW
   writes, which left ino:15357 driving pin 30 HIGH on every braking tick and ino:15304/15358 driving pin 5 LOW 0-20 ms
   into every regen window (`calc/bt3_logic_seq_enum.py` sections 2-3). A new State-1 call site runs the FC window and the configuration check
   (section 12.12). Revision 9, restated in revision 11: an FC-window request (`charge_goal` above `CHG_GOAL_MIN` with
   the request flag 0xA5 in command byte 20, section 9.11.6) is admitted in State 1, State 98 and, with
   `IC1_FC_RUN_STANDSTILL` 1, in State 2 at standstill; every refusal is reported with the code of Table 25 in telemetry
   protocol v6 (section 9.11.6, ruling OR-O'). The purge sequence of section 9.11 (prediction exit, share override,
   re-entry gates) and the `ERR_FC_ONLY_COLLAPSE` detector run in `chgModeTick()` in every state.
7. **Chokepoints and refusals.** Under `PACK_RETURN_CHANGEOVER`, pins 5, 30 and 31 are written only through three
   setters owned by `chgModeTick()` (`chgSetMpptd()`, `chgSetRegen()`, `chgSetFcCharge()`); every other caller goes
   through them and is refused by the rules below. A host test asserts from the write log that no other code writes
   these pins:
   - the State-98 `4` and `5` keys, `assertFcChargeEnable(true)` and any REGEN_ENABLE HIGH write are refused unless
     ladder A bit 0 (FF1.Q) reads HIGH and the mode manager is in `CHG_ENTERING`, `CHG_REGEN`, `CHG_FC` or
     `CHG_CONFIG`; the one exception is the eFuse-blocking probe of section 9.7a, which raises FC_CHARGE for at most
     100 ms with FF1.Q L and pin 32 LOW;
   - `CHG_CONFIG` (configuration check, dump check, probe) is refused unless `mainState` is 1 or 98 with the motor
     command 0; the dump-check sub-mode (register reads and writes disabled) is also admitted in `mainState` 2 under the
     D-s standstill conditions of section 9.7 with `IC1_FC_RUN_STANDSTILL` 1 (revision 11, FM7-1, BT7-LS-01); `CHG_FC` is refused unless `mainState` is 1 or 98 with the motor command 0, or (revision 9)
     `mainState` is 2 with the standstill conditions of section 9.7 and `IC1_FC_RUN_STANDSTILL` 1; every FC-fed
     session is refused without the purge permit of section 9.11.2;
   - (revision 9, SC-8; extended in revision 10, BT6-LS-02) from the first entry write of any FC-fed session (pin 10)
     through the whole `CHG_ENTERING` state, the session and its exit, until BT_BUS has been HIGH for the conduction
     bound of Table 20 (and, after a prediction exit, until the declared purge end), pins 27 and 28 are written only by
     the mode manager and by the State-99 teardown; a write from the share latch, the source selector, the load guard,
     `chargingControl()` or a State-98 key is refused (row F61; write-log host test). In the same interval in State 2
     the mode manager substitutes a strictly in-band share command for an EMS rail command (section 9.11.6), and
     `assertFcChargeEnable(true)` refuses instead of running its S2 FC_BUS restore (section 9.7 entry step 6);
   - in `CHG_CONFIG` and the State-98 commissioning sub-mode, pin 33 is refused unless pin 32 is LOW, and pin 32 HIGH
     is refused while ladder A bit 0 (FF1.Q) reads HIGH;
   - REGEN_ENABLE HIGH is refused in every state when `IC1_STAGE` is 1;
   - a pin-5 write from outside the mode manager is refused while the mode manager is in `CHG_ENTERING`, `CHG_REGEN`,
     `CHG_FC` or `CHG_CONFIG`, and a pin-5 change is refused unless the module is cold (item 2);
   - (completeness critic CC-7) while the mode manager is in any state other than `CHG_BONDED`, `CHG_SELFTEST` and
     `CHG_INHIBITED`, the State-98 keys refused by the fw v37 `J` session are refused as well: `1`, `2`, `3`, `6`
     (bus switches, MOT_PWR, pin 32), `C` (CBAL_DISABLE), `A`, `V`, `P`, `O` (manual motor and droop writes), `F`,
     `B` (boost enables, the back-feed class), `G` (bring-up) and the write forms of `N` (ino:8594-8615). `X` runs the
     commanded exit; `Q` runs the commanded exit before leaving State 98. From revision 11 (BT7-LS-02) the `B` and `F`
     write forms are also refused in `CHG_BONDED` while an FC-window request stands, and a boost enable that reads LOW
     refuses entry (code 11). A pin-32 LOW write inside a window would open
     the battery path during charge (gate S0-3) and a boost-enable LOW write would leave a disabled boost on a live bus;
     neither is reachable from a key. The only firmware pin-32 LOW writes that can occur inside a window are those of
     `ERR_CHG_LADDER` with code 0 (item 4) and of State 99 after pin 33 LOW (section 9.9); gate S0-3 covers both;
   - (CC-8) window entry of every type (and commissioning) is refused while pin 9 (`CBAL_DISABLE`) reads HIGH, as the
     fw v37 `J` start refuses it (ino:11303-11307), because the BQ29200 OUT term of N1 is the only hardware pack-OVP
     actuator. SLUSA52C sections 8.1.1 and 8.1.2 describe the overvoltage comparison as continuous and CB_EN as the
     enable of the cell-mismatch correction only, so pin 9 HIGH is not expected to disable OUT (not tested: BG-17b
     records OUT with pin 9 HIGH and LOW); the refusal holds in either case. With RB1A at 4.7 kOhm (revision 7) the
     balance current is 0.5-1 mA (ruling OR-AA).
8. **Self-test sub-state.** `CHG_SELFTEST` is entered only from `CHG_BONDED`, after any `CHG_EXITING` has completed,
   including the pin-5 write of the exit (revision 8, BT5-LS-03); an Idle entry during `CHG_EXITING` queues the
   self-test until then. `CHG_SELFTEST` runs section 9.3 one step per iteration and aborts on a State-2 request, a
   non-zero motor command or a fault; a window request waits for its result, and a deferred result is re-run as section
   9.3 states (revision 12, BT8-LS-01). While it runs, the State 1 to 2 transition and any non-zero motor command wait until the
   abort shows the bonded settled reading.
9. **Guarded FC_BUS release before a State-1 or State-98 session (revision 11, open item 37).** `doState3()` clears only
   the selector flags (ino:8010-8015) and leaves the bus switches as they are (ino:7989), and the only latch release is
   `powerBalance()` in State 2 (ino:13421, ino:7944-7950), so a Run that ends with `shareSpCutFC` or `shareIsoFC` set
   leaves FC_BUS LOW in Idle (2 of 22 bags end with `switch_state` 0x26, `calc/bt7_bag_reachability_output.txt`).
   Before any FC-fed session in State 1 or 98, when FC_BUS reads LOW and a share-latch or selector flag holds it, the
   mode manager runs the fw v28 F1 disarm and the guarded release of the latch: V_bus at or above 13.5 V, FC_REG HIGH
   and BT_BUS HIGH, `busHotPlugUnsafe(FC_REG_ENABLE)` false, then FC_BUS HIGH through the guarded path and the flags
   cleared; the session waits until FC_BUS is outside `busSwitchBlanked()` (30 ms). A refused release refuses the
   session with code 11. The release is the same guarded write that `powerBalance()` makes in State 2.
10. **Fixed window split and MDAC ownership (revision 11, BT7-TR-01).** From the iteration of section 9.7 entry step 5
   in which BT_CURRENT first reads below 0.2 A until the SC-8 interval ends, the MDAC writes and k_d belong to the mode
   manager: the share loop returns before its filter with its state held, the fw v28 rev 4 k_d topology slew is
   frozen, and `setDroopMdac()` is called only by the mode manager (write-log host test). The mode manager writes the
   split r = `DROOP_R_MAX` at k_d = `K_DROOP` at entry and restores the stored codes and k_d in the iteration after the
   exit's BT_BUS write. A session that ends without reaching entry step 5 writes no MDAC code.

### 12.5 Ag105 policy

1. **`chargerHasPower()`** returns true only when ladder A bit 1 (EF_EN) is HIGH, V_chg (pin 38, VCHG-IN, the eFuse
   input) has been at or above 13.5 V on two settled iterations (TODO(calibrate): pin-38 gain error against the
   12.88 V UVLO maximum), and ladder A bit 2 (EF_FLT_N) is HIGH outside the mask of section 12.4 item 4. EF_FLT_N alone
   is not power evidence: below the 4.5 V IN_SYS minimum the eFuse is unpowered and FLT reads HIGH on its pull-up
   (SLVSE94G section 6.5), and PGOOD is unusable with PGTH grounded. The pin-level definition (ino:16244-16247) is wrong
   under IC1.
2. **`pollAg105()`** makes no configuration writes. It reads reg 0x00, 0x01 and 0x02 once per powered interval in FC
   windows and configuration checks, reads reg 0x01 once per regen window while EF_EN is H and V_chg is at or above
   13.5 V (revision 6, BT3-AG-4), and latches `ERR_AG105_CFG` on a mismatch with Table 5. It reads reg 0x06 at 50 Hz
   while powered. Validity depends on the register type:
   - **Settings (reg 0x00-0x04, 0x0A).** Valid when the device ACKs and the status byte is not 0xFF, whatever GENSTAT
     reports (Battery Disconnect and Bring-Up included). The data is compared raw: reg 0x02 = 0xFF is the expected
     resistor-mode value (Table 5), not an invalid read.
   - **Measurements (reg 0x05-0x07).** Valid only when the status byte gives GENSTAT Charging or Fully Charged and the
     data is not 0xFF (Ag105 DS p.14: measures read 0xFF below 9 V input). Reg 0x06 is an unsigned 8-bit field
     (0.011 A/count) and cannot represent a reverse pack current.
   `ERR_ISO_MISMATCH` uses valid measurements only; `ERR_AG105_CFG` uses valid settings reads. `I_charge` telemetry is
   meaningful in FC windows only; in regen windows it reads 0 or a single sample.
   **I2C NAK and missing reads (CC-16).** The existing `FAULT_I2C_CHARGER` latches only for a powered, settled charger
   in State 2 or 3 (facts_firmware section 3.3, ino:16158, 16216-16228), so under IC1 it cannot fire in an FC window or a
   configuration check (State 1 or 98) or in a regen window (powered interval shorter than `AG105_SETTLE_MS`). A
   State-2 standstill window (revision 9) is powered and settled in State 2, so under `PACK_RETURN_CHANGEOVER` the
   existing `FAULT_I2C_CHARGER` is not evaluated while the mode manager owns the charger, and rule (a) applies in every
   state. Under `PACK_RETURN_CHANGEOVER`: (a) in `CHG_FC` and `CHG_CONFIG`, a NAK, or no valid settings read, after
   `AG105_SETTLE_MS` with `chargerHasPower()` true ends the window and voids the check (regen windows stay refused);
   its class under ruling OR-E is window inhibit; (b) the once-per-regen-window reg 0x01 readback is opportunistic: the
   powered interval is the pulse rise plus the VESC-stop tail, 84-416 ms per pulse (`calc/bt5_transient_sim.py`
   section 1, revision 8), so a 65-170 ms module boot can give a valid read inside the tail, but not on every pulse; a
   window without a valid read is not a fault; the FC-window and configuration-check readbacks remain the
   `ERR_AG105_CFG` evidence.
3. **MPPTD.** Pin 5 is driven open-drain (`OUTPUT_OPENDRAIN`, revision 6): LOW pulls MPPTD to Vin- and disables MPPT
   (Ag105 DS p.4, "Pull this pin to Vin- to disable"); released, the module's own bias sets MPPT enabled
   (TODO(verify: Silvertel) that a released pin reads enabled; S0-7 records the status-byte bit 3). The Teensy then
   never sources current into an unpowered module through MPPTD. If S0-7 shows that a released pin does not enable
   MPPT, pin 5 returns to push-pull through a series 10 kOhm resistor and S0-7 gains a NO-GO on back-powered module
   activity. Pin 5 is released only while a window is open and changes only on a cold module (section 12.4 item 2).
   The Teensy-side I2C pull-ups remain a possible back-power path (UNCONFIRMED; S0-7).
4. **GENSTAT latch.** `FAULT_CHARGER_STAT` runs in every build under `PACK_RETURN_CHANGEOVER` for GENSTAT 101
   (OC/Regulation Error) and 111 (Timeout Error; reg 0x03 = 0 disables the timer, so 111 is itself a stored-code
   fault). GENSTAT 110 (Thermal Shutdown, Table 6 JSON) inside a window ends the window, records the event and refuses
   a new window for 60 s (TODO(calibrate) at B8), without a latch: above 45 C ambient the module derates by design
   (Ag105 DS p.17 Table 9, section 7.1).
5. **`CHARGER_STAT` (pin 6).** Logged only; no IC1 decision uses it, because STAT is referenced to module Vin- in both
   modes and a single read cannot tell Charging from an error pulse train (CLAUDE.md section 3). The fw v37 `J` STAT
   activity window retires with `J` (CC-B12).

### 12.6 Faults

Table 16 lists the new faults. All are latched unless stated. The response of each fault in a production build follows
the per-fault table of ruling OR-E (section 17): State 99 for the traction and isolation hazards, and a window inhibit
with a telemetry flag for the charge-subsystem health faults. The rows that state "not State 99" give the proposed
inhibit class.

Table 16. New faults.

| Fault | Condition | Covers |
|---|---|---|
| `ERR_CHG_SELFTEST` | Any self-test step of section 9.3 fails (a deferred result refuses windows with code 16 until a re-run passes, and does not latch; revision 12) | F1, F8, F8b, F9, F24, F25 (open), F32b, F32c, F32d, F41, F44 (step 5) |
| `ERR_CHG_TRIP` | FF1.Q LOW while pin 33 HIGH and the mode manager did not request it; ladders, I_PACK1, I_PACK2 and V_PACKN stored | Hardware trips |
| `ERR_CHG_ENTRY` / `ERR_CHG_EXIT` | No settled confirmation within 4 loop iterations after an entry or exit edge, or 30 ms wall-clock, whichever comes first (section 7.7), or the sense-path check fails at entry; on `ERR_CHG_EXIT` the pump stops | F1, F26, F32, gate faults |
| `ERR_CHG_LADDER` | Undecodable raw decode on 3 consecutive iterations, or a settled mismatch on 3 consecutive iterations (section 12.4 item 4); pin 32 LOW at once on code 0, otherwise after the commanded exit | Readback faults, F51 |
| `ERR_SGND_OPEN` | Bonded, I_PACK1 discharge above 1 A: -V_PACKN > V_D,min + I_PACK1 x R_allow, with the corrected decode of section 7.9 (V_D,min and R_allow from S0-1 and C-2; trip demonstrated at 1, 3 and 7 A at C-2) | F2 |
| `ERR_SGND_DEGRADED` | Exactly one SG bit HIGH in the bonded mode | F2a, F31 |
| `ERR_RET_DEGRADED` | I_PACK1 at or above 5 A: R_ret above the C-2 baseline plus 5 mOhm | F22 (lead B) |
| `ERR_ISO_MISMATCH` | FC window only (never with pin 32 LOW), charger powered, valid measurement, outside a 200 ms blanking after any GENSTAT change. GENSTAT Charging with the CC or CV bit set: \|max(I_PACK1 charge, 0) - reg 0x06 x 0.011 A\| above max(0.15 A, 10 %) for 100 ms. GENSTAT Fully Charged: reg 0x06 above 10 % of I_set, or I_PACK1 charge above +0.1 A, for 100 ms (TODO(calibrate)). The board load I_L flows through the sense in reverse, so I_PACK1 = I_o - I_L can be negative while reg 0x06 cannot | F1, F19, F33, F44 (FC windows only) |
| `ERR_IPACK_XCHK` | \|I_PACK1 - I_PACK2\| above 0.15 A for 100 ms (TODO(calibrate)) | F8, F8b, F21, F28 |
| `ERR_AG105_CFG` | Valid settings readback (status byte not 0xFF, any GENSTAT) of reg 0x00-0x02 differs from Table 5 | Stored-code faults |
| `ERR_IPACK_PLAUS` | Bonded mode, every iteration: BT_CURRENT (pin 41) at or above 0.4 A for 100 ms while I_PACK1 shows less than 0.25 A of discharge (0.4 A less the 0.10 A INA253 floor at a 15.1 V bus and an 8.4 V pack implies at least 0.54 A of discharge, x2.16, calc6 section 8; re-derived at C-2). A pass (BT_CURRENT at or above 0.4 A with I_PACK1 discharge at or above 0.25 A for 100 ms) is recorded once per power cycle and is a regen-window precondition. Revision 5 used 1.0 A / 0.5 A, which 3 of 23 recorded sessions reached. Revision 7 adds a gain band: in bonded traction with BT_CURRENT at or above 1.0 A for 1 s, a 1 s mean of the I_PACK1 discharge outside 0.75-1.30 x the 1 s mean of (BT_CURRENT x V_bus / (eta_cal x V_batt) + I_NB,cal) latches the same fault. I_NB,cal is the non-boost VBT load (the LM1084 input and the other VBT loads, without the BT-boost input), measured in bonded Idle at C-2a item 28 (revision 8, FM5-5); the B8 I_L,cal includes the BT-boost input, counts it twice in this formula and put the lowest healthy ratio at 0.70 (`calc/fmea_round5_calcs.py` section 6), so it is not used here. Healthy spread 0.84-1.19 over eta 0.85-0.95, I_NB 0.1-0.3 A calibrated to +/-0.05 A and the INA253 floor (calc8 section 6; TODO(calibrate) at C-2a and W1) | F44, F21 (outputs near zero), F34c (common-mode gain loss) |
| `ERR_VCHG_FED` | Every bonded iteration with the bus up, and as a window-entry precondition: V_chg (pin 38) above 11 V for 50 ms while pins 30 and 31 are commanded LOW, outside a 1.0 s blanking after any pin-30 or pin-31 fall, VOK release or probe (VCHG-IN bleed tau 0.984 s; calc5 section 5; the module-node coupling removed by Q_MD and bounded by R_MB, calc6 section 3; TODO(calibrate) at C-2). Threshold above the highest unfed level (VBT 8.5 V through R_KA, UNCONFIRMED path) and below the 13.5 V window floor | F15, F17, and a pin-30 or pin-31 net stuck HIGH |
| `ERR_VOK_STUCK` | Stage 2, any state: CH1_OK or CH2_OK permits on a settled read while r = (V_rgn / V_bus) / k_idle is below 1.003 for 50 ms (TODO(calibrate) at V2-1). V_rgn is pin 39 after the M-R2 two-point calibration; k_idle is the 1 s mean of V_rgn / V_bus in bonded Idle with MOT_PWR HIGH and the motor current below 0.5 A (V-MOT = VBUS less the D-MT-EN drop), refreshed at every Idle entry after the step-10 settle (`ERR_VMOT_CAL` row). A healthy channel permits only while V-MOT is above its own release level, so r is at least 1.0062 (Table 9 with the centred hysteresis, calc6 section 6), and a channel stuck OK at bus level reads r = 1.000: a slow decay or a plateau cannot defeat the rule. The revision-5 dwell rule (exactly one channel for 50 ms) false-latched on a single-channel assert in [A1, A2) unless V-MOT fell at 14.9 V/s or faster, against a measured 14.2-20.1 V/s (`calc/bt3_transient_sim.py` section 1); it and its 6.6 V/s `static_assert` are deleted. A channel that blocks while r is above 1.0775 + 0.003 is an availability flag (`VOK_CH_LOW`, reported, not latched) | F15b |
| `ERR_VMOT_CAL` | Stage 2: the latest valid k_idle outside +/-3 % of the C-2a value, or no valid k_idle in this power cycle: regen windows refused (not State 99, not latched; re-evaluated at every valid k_idle). A valid k_idle is a 1 s mean that starts after self-test step 10 has seen both CH bits L for 100 ms, with MOT_PWR HIGH and the motor current below 0.5 A, and contains no sample with a CH bit H or a ratio above 1.01 x the C-2a value (revision 7, BT4-LS-01: a mean that began within about 0.11 s of a regen peak read 1.037-1.067) | Pin-39 or pin-26 drift |
| `ERR_PROFILE_OC` | EF_EN H: I_PACK1 charge above I_set(profile) + 0.25 A for 20 ms (TODO(calibrate)) | F23, F38 |
| `ERR_BAL_ABSENT` | BAL_OK reads L: windows refused (not latched) | Balance lead absent; BQ29200 unpowered |
| `ERR_EFUSE_BYPASS` | eFuse-blocking probe of section 9.7a only: with the module cold (pin 8 LOW for 20 ms), FC_CHARGE raised, V_chg at or above 13.5 V on two settled iterations and EF_EN L, pin 8 reads HIGH on two successive iterations (module node at or above 8.69-9.15 V against the Q_MD load). No Ag105 read is used. A qualified detector only after the C-2 injected-bypass gate | F11, F35, F36 (M2) |
| `ERR_MOD_FED` | Bonded mode, outside the exit drain interval and the probe: pin 8 HIGH on 3 consecutive iterations while V_chg reads 9 V or more (module node fed while bonded). State 99 | F11 or F35 together with a feed |
| `ERR_MOD_SENSE` | (a) Bonded: pin 8 HIGH on 3 consecutive iterations while V_chg reads below 9 V. (b) Positive control: with EF_EN H, pin 8 has not read HIGH by the deadline after the anchor, and EF_EN stayed H until the deadline (a shorter span is not evaluated). The anchor is the second consecutive V_chg reading at or above 13.5 V that follows a V_chg reading below 13.0 V, all three taken while EF_EN is H. The deadline is 50 ms in an FC window or configuration check, and in a regen window the later of 10 ms and 4 iterations after the anchor, capped at 30 ms. Worst lag from V_chg 13.5 V to pin 8 HIGH is 3.38 ms. The revision-6 anchor (any second reading at or above 13.5 V) fell before the feed whenever VCHG-IN still held 13.5-14.5 V from the previous pulse, which false-latched from the second pulse of a window (BT4-LS-02); the earlier EF_EN-interval form false-latched on a 10-12.5 ms VOK interval (CC-1). (c) Exit hold check: in the iteration of a commanded exit feed drop, when immediately before the write EF_EN (ladder A bit 1, raw decode) reads H, pin 8 reads HIGH and has read HIGH continuously for at least 2 ms in the current EF_EN-H interval, and V_chg reads at or above 13.5 V in that iteration, pin 8 reads LOW at 50 us or 150 us after the write; the last eFuse-blocking probe is then void (row F55; calc8 section 1). The eFuse-blocking probe feed drop (section 9.7a step 5) and any feed drop with EF_EN L (an exit between regen pulses) are not evaluated (revision 8, FM5-1, BT5-LS-01, BT5-TR-01). Windows refused for the power cycle (not State 99) | U_MS, divider, pin-8 tap faults, F55 |
| `ERR_MOD_DRAIN` | Pin 8 has not read LOW on two successive iterations by T_drain,max after a feed drop at a commanded exit: the later of 10 ms and 4 iterations, capped at 30 ms (with one 9.76 ms iteration the latest healthy second LOW read is 12.44 ms against a 13.78 ms deadline at the p99 loop, calc7 section 5). Windows refused for the power cycle (not State 99) | F49, F56 |
| `ERR_MOD_DUMP_ON` | At the EF_EN rise of every session with pin 32 LOW only (the dump check of section 9.7b, the configuration check, commissioning), with the bus FC-only: the 4-iteration mean of FC_CURRENT (pin 40) that starts 10 ms after `chargerHasPower()` first turns true exceeds the 4-iteration mean before the rise by more than 0.4 A (TODO(calibrate)). The sample is keyed on `chargerHasPower()` because D-BC-FC has no specified t_D_ON maximum (RT1987 DS-00 section 13); 10 ms later the eFuse output ramp (at most 3.8 ms at C_DV 10 nF, calc12 section 3) and its inrush are over; with a C_DV raised under S0-11 the sample moves to the measured ramp plus 2 ms when that is later (revision 12, BT8-TR-01). With pin 32 LOW the module output path is R_KA alone, so the healthy step is at most 0.232 A (23 mA node, about 9 mA module input, up to 0.2 A BT handoff) whatever the module start speed, and a stuck dump gives at least 1.09 A; FC_CURRENT resolves 8.1 mA (calc8 section 2, calc7 section 4). Not evaluated in FC windows (pin 32 HIGH): a module that starts inside the Stage-2 allowance draws 0.45-0.97 A at the sample (revision 8, BT5-LS-02, BT5-TR-02); there `OC_FC` (BENCH_TEST 0) and U_IM cover a stuck dump while the module charges. A pass is recorded once per power cycle and is a precondition of every window. A session in which `chargerHasPower()` never turns true is not evaluated. The session ends through the commanded exit. Window inhibit for the power cycle (not State 99) | F50 |
| `ERR_CELL_MISMATCH` | Bonded mode, BAL_OK H, \|I_PACK1\| at or below 1 A, every iteration: \|V_BT - 2 x V_VC1 + V_PACKN\| above 80 mV (TODO(calibrate)) for 1 s, where V_VC1 is pin 20 and V_BT is pin 25, each after its own C-2a item 5 two-point calibration against the same DMM (revision 8, FM5-4: revision 7 calibrated pin 20 only, so a 3V3 error beyond about +/-0.5 % alone exceeded the margin, `calc/fmea_round5_calcs.py` section 5), and V_PACKN the section 7.9 decode (V_cell2 - V_cell1 with pack(-) = PACK- to within I x R_SH). The worst healthy error is 41.5 mV, of which 20.9 mV is D_VC1 leakage at 40 uA (calc7 section 2), plus 0.488 V per uA of pin-20 leakage drift that the room-temperature calibration does not absorb (79 nA allowed against the 38.5 mV margin; TODO(verify: IMXRT1060CEC); C-2a item 5 is repeated at the B8 hot soak and at the coldest operating ambient; calc8 section 4). IMXRT1060CEC Table 22 bounds the pad input current only at +/-1 uA, which is 488 mV of mismatch (12.7 times the allowance, calc12 section 7), so the 80 mV threshold rests on the C-2a hot and cold record, not on the datasheet (revision 12, BT8-DS-03). F47 detection does not depend on it: F47 reads at least 7.5 V of mismatch (8.0 V - 2 x 0.25 V) against a worst healthy error of 0.53 V at the datasheet limit, so any threshold up to 7 V detects F47 on the first evaluation. A shorted or reversed D_VC1, a dead tap, D_VC1 leakage above about 114 uA (other terms at their bounds; 153 uA with them at zero; revision 7 stated 75 uA, which was the excess above 40 uA) or a pack imbalance above 80 mV latches it. The threshold is set from the measured hot and cold spread (TODO(calibrate)). Window inhibit for every window type (not State 99) | F47, F54, D_VC1 leakage, pack imbalance |
| `ERR_CHG_PATH_OPEN` | A window with `chargerHasPower()` true: V_PACKN above I_PACK1,charge x R_chain,max + 0.1 V for 100 ms (pack(-) above GND with no charge current through the chain), or GENSTAT Fully Charged on two valid reads while V_BT - V_PACKN reads below 8.0 V (TODO(calibrate); R_chain,max from C-2a). Window inhibit | F14 |
| `ERR_VCHG_SENSE` | (a) Pin 8 HIGH while V_chg reads below 8 V on 3 consecutive iterations, evaluated in every iteration of every mode (revision 7: the domain is stated, FM4-2); (b) two consecutive VOK pulses with EF_EN H for 20 ms and V_chg never above 12 V; a void probe is a deferred result. Regen windows refused (not State 99) | F52 (pin-38 channel failed low), F55 |
| `ERR_PACKN_RANGE` | V_PACKN outside -1.2 to +0.6 V for 5 ms (TODO(calibrate)) | F33, V_PACKN_S open |
| `ERR_FC_ONLY_COLLAPSE` (R9) | Every iteration of a session that holds BT_BUS open (`CHG_ENTERING` after entry step 5, `CHG_FC`, `CHG_CONFIG` with the dump check and the probe, and `CHG_EXITING` up to the BT_BUS re-close write): (a) one V_chg reading below 13.0 V with EF_EN H after `chargerHasPower()` has been true in the session, or (b) one V_bus reading below `LIMIT_V_BUS_MIN` 12.0 V. No dwell; independent of `uvBusArmed` and of the share loop. State 99 with no BT_BUS re-close (section 9.11.5, policy E2). Reading (a) replaces the revision-7 commanded exit on the same reading (BT4-TR-06). Revision 10: (a) is evaluated in a session in which EF_EN has been H; (c) in the same sessions an UNKNOWN transition, `purge_active` rising or a late prediction (first observed with `purge_tto` below T_late 61 ms) latches at once, before any exit step (PI-4); (b) stays armed after the BT_BUS re-close write of a prediction exit until the declared purge end (PI-2); a `busHotPlugUnsafe()` refusal of the exit's re-close latches on the next iteration that still refuses. The false-latch rate is BENCH (gate W2d) | F57, F58, F60, F61, F63 |

Existing faults are re-checked as follows.

1. **`OV_BATT`** (8.5 V single sample). In the charge mode V_batt reads high by I_p x (R_SH + R_DS(S_CHG) + R_VBATN_X +
   R_FVX + R_s). The VBATN_X lead adds 10.3 mOhm (0.3 m of 0.5 mm2) to 17.2 mOhm (0.5 m), which moves the boundary from
   about 74 mOhm to about 60-64 mOhm of R_s at 1.75 A; F_VX adds its cold resistance (10-30 mOhm ASSUMED,
   TODO(verify: fuse datasheet)), which moves it to about 30-54 mOhm (calc6 section 2). The threshold or a charge-mode
   compensation is set after S0-1 and the F_VX selection, under ruling OR-X.
2. **BQ29200 bottom cell.** The BQ29200 measures cell 1 as VC1 - PCB GND (SLUSA52C section 7.5, facts_board section 5
   item 1). In the charge mode it reads high by I_p x (R_SH + R_DS(S_CHG) + R_VBATN_X + R_FVX + R_s). With the Ag105 CV
   loop holding VCHG - VBat- at 8.40 V (UNCONFIRMED sense point), the balanced reading at CV entry reaches the 4.325 V
   lower OVP limit for R_s above about 72-75 mOhm at 1.75 A (`calc/verify_bq_chargemode_offset.py`), less R_FVX
   (about 42-65 mOhm at an ASSUMED 10-30 mOhm), or for a bottom-cell excess of twice the remaining margin. In the
   bonded mode D_VC1 leakage shifts the same reading low by at most 10.4 mV at T_M16,max (Table 7), and the VC1 tap
   load by at most 2.9 mV; `ERR_CELL_MISMATCH` measures the bonded-mode result on the VC1 tap. A BQ trip in a window clears FF1 and, in production builds, enters State 99 (ruling
   OR-E, accepted 2026-11-09); a W0 NO-GO reopens charge inhibit under OR-E. Gate W0 measures the margin.
3. **`UV_BATT`.** Between regen pulses the board load returns through the sense in reverse, so V_batt under-reads by
   I_rev x (path resistance), about 90 mV at 1.4 A through about 62 mOhm (working figure). The armed 7.4 V dwell then
   latches at a true pack of about 7.49 V: a nuisance, not a hazard. The charge-mode OV_BATT and UV_BATT limits reverse
   the fw v30 limits of CLAUDE.md section 6 and need ruling OR-X.
4. **`SWITCH_CONFLICT`** runs in every build and uses the derived BT_BUS state.
5. **`UV_BUS`** (revision 9). Unchanged: 12.0 V with a 20 ms accumulated dwell, armed only while a matched source pair
   is closed (ino:2163, ino:2189-2193, ino:7338-7377). Inside a session that holds BT_BUS open,
   `ERR_FC_ONLY_COLLAPSE` acts first and does not depend on the arming; from revision 10 its reading (b) also covers
   the interval from the exit's BT_BUS re-close write to the declared purge end (rows F59, F63), and UV_BUS remains the
   second layer there.
6. **`UV_FC` and the FC-only lockout** (revision 9). The 1000 ms UV_FC dwell and the 4.5 V threshold are unchanged
   (`docs/fw30_fc_purge_uv.md`): one purge of 100-140 ms per 10.34 s period does not ratchet the dwell (break-even purge
   interval 4.2 s). Under `PACK_RETURN_CHANGEOVER`, `fcUvLockoutActive()` no longer gates any FC-fed session (the purge
   permit replaces it, ruling OR-P); it still refuses an FC-only source selection for 30 s after a purge-class dip.

### 12.7 Guards ported to production

The fw v37 rev 2 `J` guards and the reboot-only trip latch run in every build inside every window (facts_firmware
section 3.5), in the following forms.

1. **G1, FC window and configuration check.** Residual form, evaluated at 1 kHz:
   I_fc + I_batt - ((I_PACK1 + I_L,cal) x V_batt / (eta_cal x V_bus) + I_AUX) above I_G1 for 5 ms. I_L,cal and eta_cal
   are measured at gates B8 and W1 (TODO(calibrate)); I_PACK1 is the 1 kHz charge-direction pack current, so the
   estimate does not lag the charger start the way a 50 Hz reg-0x06 estimate would. I_G1 comes from a written error
   budget: the INA253 zero-current floor on I_batt (0.10 A; I_fc runs near 1 A and has no floor term), the efficiency
   spread (0.098 A uncalibrated over 0.80-0.88, 0.023 A with eta calibrated to +/-0.02), the I_L spread (0.035 A at
   +/-0.05 A), the I_AUX spread (0.03 A, ASSUMED) and the I_PACK1 error (0.022 A at 2 %, ASSUMED): 0.28 A uncalibrated
   (calc5 section 8). The working figure is I_G1 = 0.35 A (TODO(calibrate)). G1 is blanked from the FCQ rise until the
   first valid Charging read plus two polls (at least 40 ms after it). The legitimate FC-window bus current is
   0.965-1.075 A at efficiency 0.88 and up to 1.167 A at 0.80 (calc4 section 8), so the fw v37 absolute form (1.0 A)
   would trip every window above a pack of 7.72 V. The revision-4 form (P_chg,est from reg 0x07 x reg 0x06) took the
   input voltage for the output voltage and was blind below about 0.65-0.9 A (`calc/bt2_transient_sim.py` section 4).
   Because I_G1 is above the 0.31 A bottom of the D5 range, G1 does not resolve sub-D5 circulating flows (section 11
   note 2).
2. **G1, State-98 commissioning.** The absolute 1.0 A form, as in fw v37.
3. **G1, regen window.** Not applied: the BT boost legitimately supplies the bus.
4. **G2.** FC windows and configuration checks only (in a regen window the charger is fed from V-MOT, which the bus-side
   G2 does not see). Its fixed 0.75 efficiency and its baseline are re-derived per window type, and its baseline gains
   the same I_L,cal term as G1 (TODO(calibrate)).
5. **G3.** GENSTAT 101 and 111 latch, every window; GENSTAT 110 (Thermal Shutdown) ends the window without a latch
   (section 12.5 item 4).

### 12.8 State 98

State 98 gains the following functions, on keys to be allocated against PLAN.md section 9 (TODO(verify: PLAN.md key
map)): force each mode-manager state with the hardware interlocks and the refusals of section 12.4 item 7 in force; run
the self-test; print both ladders decoded; run the commissioning procedure of section 9.2 (pin 32 LOW enforced); toggle
the profile pin while the eFuse is off. The `J` session of fw v37 is replaced by the commissioning procedure under
`PACK_RETURN_CHANGEOVER`. Key `7` (free in fw v37: the State-98 help list at ino:8535 and above names no `7`, and no `case '7'` exists; revision 8, CC-B4) stores
the per-board calibration record of section 12.12 item 2; it is refused outside `CHG_BONDED` and with a non-zero motor
command. A window-request key (revision 12, BT8-REQ-03; allocated against PLAN.md section 9, TODO(verify: PLAN.md key
map)) raises and withdraws a State-98 FC-window request with the effect of a flagged request (section 9.11.6); it is
refused outside State 98, and the request ends on any exit from State 98. Gates W1, W2 and C-2b use it, so that no
window before the W2e Pi round needs the OR-RQ packet form.

### 12.9 Telemetry and logging

The telemetry needs `I_PACK1` (int16 mA), `V_PACKN` (int16 mV) and a 16-bit hardware status word (both ladders, pin 8
and the mode-manager state). These are a protocol change: the protocol-bump procedure applies, and the Pi bridge must
change in lockstep (OR-H). The operator-approved telemetry v5 of ruling R4 (`docs/fw37_planning_2026-11-04.md`
section 4: proto_version, fw_version, blg_file_index, blg_prefix, I_cmd, charger_flags, loop_hz_avg10,
loop_dt_max_us; 73 bytes) is scheduled with fw v38 and BLG v10. IC1 therefore names its layout **protocol v6**, built
on the R4 v5 layout with the IC1 fields appended, so that no two v5 layouts exist. Under `PACK_RETURN_CHANGEOVER` the
R4 `charger_flags` bits are redefined: `ag105Configured` becomes "commissioning readback matched this power cycle",
`chargerHasPower()` takes the section 12.5 item 1 definition, "regen armed" becomes the OR-V' command-step arm, and
`FC_CHARGE_ALLOWED` follows ruling OR-W. `switch_state` bits 0x40 and 0x80 are reserved for the HIL topology
word (ino:710-713); spending them on FF1.Q and EF_EN needs ruling OR-R and a lockstep change of the HIL plant and the
campaign comparators. The BLG record gains the same fields (a BLG version bump, with `tools/decode_benchlog.py` and
`tools/benchlog_analysis` in lockstep). Revision 9 adds to the protocol-v6 fields the FC-window request bit, the purge
permit state (permit, prediction, UNKNOWN, purge active), the share-override bit, the `PURGE_LEAD_SHORT` counter and the
8-bit refusal code of Table 25 (section 9.11.6); the byte count and the checksum span are set in the protocol-bump round
(CC-B3). Revision 11 adds code 15 (no field change) and changes the meaning of command byte 20 (the request flag, section
9.11.6), which the same protocol-bump round carries; it adds to the BLG record the duration of the iteration that
precedes each iteration that first observes a purge prediction (FM7-2), so that gate W2d can attribute an
`ERR_FC_ONLY_COLLAPSE` from the late rule to a long iteration.

### 12.10 HIL

The simple plant needs a PACK- node, the Ag105 sense in the return, the three switches with their body diodes, the eFuse
with latch-off, the cross-lock, the VOK comparators with the bus-present guard, the pumped arm and the unregulated I_L
supply; the observation frame needs the new status fields. The hi-fi engine's `BT_SEQ` semantics contradict the netlist
and must be corrected first (facts_firmware section 9). The status-level Ag105 model cannot represent Bring-Up, start
latency or the threshold behaviour, so the HIL cannot test HR1 or HR2; the bench gates decide them. The 40-byte injection
frame carries no source for the ladders, pin 8, pin 20, I_PACK1, I_PACK2 or V_PACKN, so until an injection-frame
extension round (a lockstep HIL protocol change) the firmware carries
`static_assert(!(PACK_RETURN_CHANGEOVER && HIL_SIM))` (CC-B5). Until that round lands, no IC1 firmware runs on the HIL,
which is the project's main validation path; the round is change-set item 5 (revision 12, BT8-REQ-04).

### 12.11 Host-native tests

The minimum test set is the following:

- mode-manager ordering for every entry and exit, including `CHG_CONFIG` and the probe; the pin-8 drain wait between the feed
  drop and pin 33 LOW on every commanded exit; no direct `CHG_FC` to `CHG_REGEN` transition;
- profile changes only with EF_EN LOW; pump writes only from `loop()`;
- self-test pass and every failure branch, with a mock ADC that models the 20 us ladder RC and the D_D5S-blocked Q_D5
  path (D5_N reads H with N1 LOW): no latch on entry, exit or a VOK toggle; a latch on 3 consecutive undecodable iterations;
- the self-test as a sub-state: `detectFaults()` runs on every iteration during it; an injected OV_BUS during step 2
  latches State 99 within its normal dwell; an abort on a State-2 request at each step 1-10 leaves FF1.Q L and the pump
  running within one iteration; a Run command at each step produces no motor current until the bonded settled reading;
- the traction-exit path of section 9.6 with the VESC command held at 0 A until the settled exit confirmation;
- State-99 ordering under `PACK_RETURN_CHANGEOVER`, from Run and from both window types: FC_CHARGE and REGEN never HIGH
  after pin 33 goes LOW; the motor command is 0 A and FC_BUS, BT_BUS and MOT_PWR are all LOW before the first
  `*_REG_ENABLE` LOW write (write-log order); MOT_PWR LOW at t0 + 10 ms unchanged;
- the refusals of section 12.4 item 7 (State-98 `4` and `5` keys, `assertFcChargeEnable(true)`, REGEN HIGH; pin 33 in
  commissioning with pin 32 HIGH; pin 32 HIGH with FF1.Q HIGH; `CHG_FC` in State 2 with charge_goal 1.0 and every FC
  gate true while the vehicle moves, and at standstill with `IC1_FC_RUN_STANDSTILL` 0 (revision 9); `CHG_CONFIG` in
  State 2; REGEN HIGH with `IC1_STAGE` 1); no `REGEN_ENABLE` write from `chargingControl()` under the flag;
- an FC window exits on a non-zero motor command, with the VESC command held at 0 A until the exit confirmation;
- the regen arm: a +/-0.1 A command dither opens no window; two drive-controller samples at or below -2 A raise pin 30
  within 10 ms of the arm sample; with the fw v37 law, a 0.1-1.0 m/s decel step arms at the latency of section 7.8;
- FC-window entry waits for BT_CURRENT below 0.2 A;
- G1 FC-window form: pack 7.4 and 8.4 V, efficiency 0.80 and 0.88, the I_batt floor at 0 and 0.1 A, a 10 ms charger ramp
  after a 65 ms delay: no trip at any corner; an unaccounted flow of I_G1 + 0.3 A trips within 5-6 ms; in both
  BENCH_TEST builds;
- every new fault, with `ERR_SGND_OPEN` firing within one iteration at a body-diode drop of 0.7 V;
- `ERR_VOK_STUCK`: no latch on the post-brake V-MOT tail (21.35 V decaying at 14 and 20 V/s, the command ending 0, 50
  and 150 ms after the VESC stop); one channel stuck at bus level latches within 52 ms of the disagreement;
- `ERR_IPACK_PLAUS`: BT_CURRENT 2 A with I_PACK1 0 latches within 100 ms; a healthy 4 A reading does not; regen entry is
  refused before the first pass;
- `ERR_VCHG_FED`: V_chg = V_bus = 16 V with pins 30 and 31 LOW latches and refuses a regen and an FC window; V_chg 8.5 V
  does not; a VOK release followed by the 21.47 V tail does not latch inside the 1.0 s blanking;
- `ERR_EFUSE_BYPASS`: a regen window, a VOK release and the exit drain give no latch; in the probe, pin 8 LOW on two
  reads passes, pin 8 HIGH on two reads latches, and no Ag105 read is consulted;
- `ERR_ISO_MISMATCH`: a full FC charge into Fully Charged with I_L 0.3 A does not trip; an input-limited charge with
  I_o below I_L does not trip; it is never evaluated with pin 32 LOW;
- settings readbacks valid in Battery Disconnect, Bring-Up and Fully Charged; reg 0x02 = 0xFF matches Table 5;
  invalid measurements (0xFF, GENSTAT error) excluded from `ERR_ISO_MISMATCH`;
- `chargerHasPower()` false until V_chg has read 13.5 V or more on two settled iterations; EF_FLT_N LOW inside the entry
  mask (1.4 ms) and with EF_EN L gives no `ERR_CHG_LADDER`; the derived BT_BUS state in `SWITCH_CONFLICT`; no Ag105
  configuration write under `PACK_RETURN_CHANGEOVER`;
- a regen window exits when the estimated I_L exceeds 0.75 A for 20 ms;
- (revision 6) a healthy board passes the Idle-entry self-test (result PASS, no `ERR_CHG_SELFTEST`) when entered from
  the State 0 bring-up and from State 2, with pin 34 toggling beforehand (BT3-LS-02);
- (revision 6) write-log chokepoints: no write to pin 5, pin 30 or pin 31 from outside `chgSetMpptd()`,
  `chgSetRegen()` and `chgSetFcCharge()` in State 1, State 2 and the State-98 D/Y/W profiles; pin 5 reads released on
  every tick of a 780 ms `CHG_REGEN` window with charge_goal 0 and 0.5, at all four 50 Hz phases (revision 5 records
  the first LOW write 7-20 ms into the window); pin 30 never HIGH with FF1.Q L or under `IC1_STAGE` 1; no pin-30
  re-raise during an exit drain (BT3-LS-01);
- (revision 6) an injected 10 ms iteration immediately after the pin-33 entry write, after the exit write and after a
  VOK-toggle straddle gives no `ERR_CHG_ENTRY`, `ERR_CHG_EXIT` or `ERR_CHG_LADDER`; a stuck FF1 still latches within
  4 iterations or 30 ms (FM3-3);
- (revision 6) `ERR_VOK_STUCK`: a single channel that asserts at A1 + 0.01 V and decays at 14 V/s, and one that holds a
  2 s plateau just above its release, do not latch; a channel stuck OK at bus level latches within 52 ms; k_idle out of
  band latches `ERR_VMOT_CAL` (BT3-TR-01);
- (revision 6) module node: every commanded exit waits for pin 8 LOW before pin 33 LOW, and latches `ERR_MOD_DRAIN` at
  T_drain,max (revision 7: the later of 10 ms and 4 iterations) with pin 8 held HIGH; window entry and pin 10 and pin 5 changes are refused until pin 8 has read LOW for 20 ms;
  the probe latches `ERR_EFUSE_BYPASS` with pin 8 HIGH and passes with pin 8 LOW, and is void without V_chg at
  13.5 V; the positive control latches `ERR_MOD_SENSE` when pin 8 never reads HIGH in a powered window; a module
  modelled as a held capacitor (I_q 0 to 18 mA, C_mod 100-221 uF) with Q_MD open gives no `ERR_VCHG_FED` and no probe
  false latch (BT3-TR-02, BT3-TR-03, DS3-2, BT3-AG-1);
- (revision 6) `ERR_IPACK_PLAUS` at the 0.4 A / 0.25 A levels, including a healthy 0.5 A BT draw that passes;
  `ERR_VCHG_SENSE` on a pin-38 reading of 0 V with pin 8 HIGH; GENSTAT 110 in a window gives no latch;
- (revision 7) Idle entry inside a regen tail: a Finish at the pulse peak, a Finish 0.2 s after it, and a State-98 `Q`
  during a `D` regen hold (21.35 V decaying at 14 and 20 V/s) each end with self-test PASS or "deferred", no
  `ERR_CHG_SELFTEST` and no `ERR_VMOT_CAL`; no k_idle sample precedes the 100 ms CH settle (BT4-LS-01);
- (revision 7) `ERR_MOD_SENSE` (b): two VOK pulses 0.523 s apart, decay 14 V/s (residual V_chg 14.1 V at the second
  assert), t_D_ON 8 and 12 ms, the read phase swept across one loop period: no latch; a pin 8 that never reads HIGH in
  a fed pulse latches (BT4-LS-02);
- (revision 7) a 9.76 ms iteration as the first drain-wait iteration (the deferred SD drain and Ag105 poll) gives no
  `ERR_MOD_DRAIN` and no `ERR_MOD_SENSE`; pin 8 held HIGH latches `ERR_MOD_DRAIN` at the later of 10 ms and 4
  iterations (BT4-LS-03);
- (revision 7) pin 8 injected equal to EF_EN latches `ERR_MOD_SENSE` (c) at the first exit and `ERR_VCHG_SENSE` at the
  first EF_EN rise with V_chg below 8 V; a healthy node (U_MS HIGH for 0.25 ms after the drop) gives no latch (FM4-2);
- (revision 7) `ERR_MOD_DUMP_ON`: a 1.07 A FC_CURRENT step at the EF_EN rise latches in an FC window, a configuration
  check and commissioning; a 23 mA step and a 0.58 A inrush that ends within 3 ms do not (FM4-3, BT4-1);
- (revision 7) `ERR_CELL_MISMATCH`: V_VC1 = 0 latches within 1.1 s; a 40 mV mismatch does not; it is not evaluated
  with \|I_PACK1\| above 1 A or in the charge mode (BT4-DS-02);
- (revision 7) `ERR_IPACK_PLAUS` gain band: a 0.5 x common-mode gain on both channels latches; the healthy corners of
  calc7 section 10 do not (BT4-TR-02);
- (revision 7) `ERR_CHG_LADDER`: code 0 sets pin 32 LOW in the same iteration; a settled mismatch with a code other
  than 0 sets pin 32 LOW only after the bonded confirmation (write-log order, BT4-LS-04);
- (revision 7) `ERR_CHG_PATH_OPEN` on V_PACKN at +0.5 V with I_PACK1 0 in a window, and on Fully Charged at 7.6 V;
  no latch on a healthy 1.75 A window (FM4-6);
- (revision 7, restated in revision 9) a V_chg reading below 13.0 V with EF_EN H after `chargerHasPower()` latches
  `ERR_FC_ONLY_COLLAPSE` and State 99 with no BT_BUS write after the latch; not before `chargerHasPower()` (BT4-TR-06);
- (revision 7) State 99 entered from both window types: the pin-8 wait is non-blocking, pin 33 LOW precedes pin 32
  LOW, and MOT_PWR LOW stays at t0 + 10 ms (CC-B13).
- (revision 8) `ERR_MOD_SENSE` (c): a regen exit 50 ms and 150 ms after a VOK release, with V_chg at 14.0-16.0 V,
  EF_EN L and pin 8 LOW, does not latch; an exit in the cold span after a re-assert (EF_EN H, pin 8 LOW) does not latch;
  an FC-window exit with EF_EN H, V_chg 12.5 V and the node at 9.5 V does not latch; an exit 1 ms after pin 8 first
  reads HIGH (node ramping) is not evaluated; pin 8 injected equal to EF_EN latches at the exit of the first dump check
  and of an FC window, and at a regen exit taken during a pulse (FM5-1, BT5-LS-01, BT5-TR-01);
- (revision 8) a complete configuration check with its eFuse-blocking probe on a healthy model latches nothing, does
  not void the probe and records a probe pass (FM5-1 scenario 2);
- (revision 8) `ERR_MOD_DUMP_ON`: in a dump check (pin 32 LOW) a 1.07 A step latches and a 0.23 A step (BT handoff
  plus node) does not; in an FC window (pin 32 HIGH) a healthy module drawing 0.85 A from 5 ms after the eFuse enable
  gives no latch and no sample is taken; an FC window or a regen window is refused without a dump-check pass in the
  power cycle (BT5-LS-02, BT5-TR-02);
- (revision 8) a Finish inside an open regen window and inside an FC window: `CHG_SELFTEST` starts only after
  `CHG_EXITING` has written pin 5, and the self-test passes (BT5-LS-03);
- (revision 8) `ERR_IPACK_PLAUS` gain band: with I_NB,cal 0.15 A and the B8 I_L,cal stored separately at 0.6 A, the
  healthy corners of calc8 section 6 give no latch; a 0.5 x common-mode gain still latches within 1.1 s (FM5-5);
- (revision 8) `ERR_CELL_MISMATCH` with both pin-20 and pin-25 calibrations: a 3V3 of 3.20 and 3.40 V with a balanced
  pack gives no latch (FM5-4).
- (revision 9) an ideal-predictor stub: a prediction at the lead time of the state closes the window in the order feed
  drop, pin-8 drain, pin 33 LOW, bonded confirmation, BT_BUS HIGH (write log), and writes no share override (revision
  10: the override is written only in State 2 in closed loop with no session); BT_BUS is HIGH at least 31.8 ms before
  the predicted onset with T_lead 80 ms in State 1, 98 and State 2 at standstill, with the one 9.76 ms iteration placed
  before the feed drop, in the drain and in the confirmation in turn and both waits at their deadlines (revision 10,
  BT6-LS-03); a prediction announced at 80 ms never trips the late rule;
- (revision 10, replaces the revision-9 R_OV test) at standstill in State 2 the MDAC write count stays 0 from the
  window close to the onset at filtered totals of 0.016, 0.165 and 0.225 A, and V_bus stays above `LIMIT_V_BUS_MIN` at
  the onset (plant stub); no override is written in P or D-s; in State 2 at a closed-loop total of 0.6 A the override
  R_OV never arms the selector and the stored EMS setpoint is restored at the declared purge end;
- (revision 10, BT6-LS-02 and BT6-REQ-03) a D-s request standing with an EMS command of 0.15, 0.85 and 0.0 at standstill
  across at least two purge periods, and an in-band-to-rail EMS step injected in each of entry steps 1-4: no FC_BUS LOW
  write from the share latch, the selector or the load guard inside the SC-8 interval, no State 99, and each period
  ends in an open window or a code-11 refusal; with the selector already armed battery-only at the stop, the entry
  runs the F1 disarm once and the window opens; `assertFcChargeEnable(true)` with FC_BUS LOW returns false with no
  FC_BUS HIGH write;
- (revision 10, BT6-LS-01) with V_chg above 13.0 V in `CHG_FC`, each of `purge_active` rising, UNKNOWN, and a
  prediction first observed at `purge_tto` 50 ms gives State 99 in that iteration with no FC_CHARGE-to-BT_BUS exit
  sequence and no BT_BUS HIGH write after the event; in `CHG_ENTERING` before step 5 the same events abort the entry with
  BT_BUS HIGH throughout; a `busHotPlugUnsafe()` refusal at exit step 4 (V_bus 12.5 V) latches on the next iteration;
- (revision 10, FM6-1) after a prediction exit, BT_BUS forced never to conduct (plant stub) and V_bus falling through
  12.0 V before the declared purge end latches `ERR_FC_ONLY_COLLAPSE` in that iteration; after the purge end the
  reading is disarmed;
- (revision 10, FM6-3) a `v_setpoint` step inside a D-s window: the VESC command stays at 0 A until BT_BUS has been HIGH
  for the conduction bound;
- (revision 10, BT6-TR-02) a window request at V_batt 7.3 V on a never-armed pack (boot at 7.3 V) is refused with code
  14;
- (revision 9) re-entry: refused while `purge_active`, while V_fc reads below 7.0 V, while V_chg reads 11 V or more
  and while `purge_tto` is below the admission horizon; granted with V_chg at 10.9 V inside the 1.0 s `ERR_VCHG_FED`
  blanking; a fed V_chg of 16 V still refuses and latches `ERR_VCHG_FED` at the end of the blanking;
- (revision 9, restated in revision 10) `purge_tto` UNKNOWN refuses every FC-fed session; an UNKNOWN transition inside
  a session that holds BT_BUS open latches `ERR_FC_ONLY_COLLAPSE` with no BT_BUS HIGH write (PI-4);
- (revision 9) `ERR_FC_ONLY_COLLAPSE`: a V_chg step from 15.9 V to 12.9 V with EF_EN H inside a window latches in the
  same iteration; V_bus 11.9 V in the probe (EF_EN L) latches; neither latches in the bonded mode or before
  `chargerHasPower()`; the latch holds with `uvBusArmed` false (FC_BUS cut injected from the share latch); the State-99
  write log shows FC_CHARGE LOW, then FC_BUS and BT_BUS LOW, then pin 33 LOW after two pin-8 LOW reads, MOT_PWR LOW at
  t0 + 10 ms and the boosts last, with no BT_BUS HIGH write after the latch (Table 23);
- (revision 9) write-log chokepoint: no write to pin 27 or pin 28 from the share latch, the selector, the load guard,
  `chargingControl()` or a State-98 key while a session holds BT_BUS open (row F61);
- (revision 9) State-2 standstill window: a `v_setpoint` step from 0 drops FC_CHARGE in the iteration of the command and
  holds the VESC command at 0 A until the bonded confirmation; a command dither at or below I_still opens and keeps the
  window; `IC1_FC_RUN_STANDSTILL` 0 refuses it with code 3;
- (revision 9, decided in revision 11) a Run that ends with the selector holding FC_BUS LOW (`shareSpCutFC` set,
  `doState3()` does not clear it, ino:7961-7999), then Finish and Idle with a flagged window request: the mode manager
  runs the guarded release (section 12.4 item 9), waits out the 30 ms blanking, runs the dump check and opens variant P;
  with V_bus at 13.4 V the release is refused and the session is refused with code 11;
- (revision 11, FM7-1, BT7-LS-01) boot, a Pi packet with `mode_cmd` 0 (State 2), the H-20 tracked, standstill, then the
  first flagged request: the dump check runs in State 2, a pass is recorded, and the window opens with code 0 at the same
  stop after V_chg falls below 11 V; the same sequence with `IC1_FC_RUN_STANDSTILL` 0 is refused with code 3, and with a
  `v_setpoint` step during the dump check it ends with no verdict through the FC exit and the traction hold, and the next
  stop starts a new dump check;
- (revision 11, BT7-REQ-01) a replay of the recorded regen latch (`charge_goal` 1.0 through a stop and the end-of-run
  tail, command byte 20 in {0, 1}, at all four phases of the 50 Hz command against the loop) never raises FC_CHARGE and
  reports code 15; the same stream with byte 20 = 0xA5 opens the window; in State 1 a packet with `mode_cmd` 4, the flag
  and `charge_goal` 1.0 opens variant P and does not set `changeToRun`;
- (revision 11, BT7-TR-01) in a D-s window with a 1.0 A charger load the share loop writes no MDAC code and k_d does not
  move from entry step 5 until the SC-8 interval ends; the MDAC write log shows exactly the fixed split at entry and the
  stored codes in the iteration after the exit's BT_BUS write; a variant-P window writes the same pair;
- (revision 11, BT7-LS-02) a State-98 window request with BT_REG_ENABLE LOW, and one with FC_REG_ENABLE LOW, is refused
  with code 11; BT_REG_ENABLE forced LOW inside a window followed by a timely prediction latches `ERR_FC_ONLY_COLLAPSE`
  at exit step 4 with no BT_BUS HIGH write; the `B` and `F` write forms are refused while a request stands;
- (revision 9) every refusal reason of Table 25 is reported with its code, and the lowest code wins.
- (revision 12, BT8-LS-01) a parked-form packet (`mode_cmd` 4, flag 0xA5, `charge_goal` 1.0) that arrives with the
  Finish opens a P window after the Idle-entry self-test passes, with code 16 reported while it runs; a Run command 40 ms
  after the first State-1 iteration after boot still admits a D-s window at the first stop (State 0 to 1 is not an Idle
  entry); a Finish followed by a Run request inside the self-test reports code 16 in that Run and passes at the next
  Idle re-run; in Stage 2 a step-10 deferral with MOT_PWR LOW re-runs step 10 when MOT_PWR reads HIGH;
- (revision 12, BT8-LS-02) a first-stop dump check aborted by a `v_setpoint` step is retried at the next stop and the
  window opens there; a third no-verdict attempt leaves code 12 for the power cycle;
- (revision 12, BT8-TR-02) the fixed-split MDAC code is the value that `setDroopMdac()` computes for g_FC 0.1753 (717), not
  a literal;
- (revision 12, BT8-REQ-03) the State-98 window-request key opens a window in State 98 and is refused in every other
  state, and the request ends on exit from State 98.

### 12.12 Change-set inventory

The firmware, tool and data work that Stage 1 and Stage 2 need is listed below. Each item is a separate orchestrated
round with its own tests.

1. **Watchdog round (Stage 1 entry gate).** RTWDOG/WDOG1 configuration; removal of blocking operations from armed states
   (section 12.3); the `Ethernet.begin()` ordering; the forced-hang test T-W-01.
2. **Mode manager and self-test.** Sections 9.3-9.10, 12.4, the ladder decode with per-board calibration, and the new
   faults. The 2 x 32 ladder calibration values, V_D,min, R_allow, R_chain,min, the R_ret baseline, I_L,cal, eta_cal,
   I_NB,cal (revision 8) and the V_PACKN, pin-20 (VC1 tap) and pin-25 (V_BT, revision 8) two-point calibrations are
   per-board constants: they are stored in EEPROM with a magic, a version and a checksum (written only in State 98, never
   in an armed state), and a missing or corrupt record refuses every window. Location (revision 8, CC-B4): EEPROM bytes
   0-511 are reserved for the record (the only existing record is the encoder direction sense at 4276-4279,
   ino:3045-3065); layout: magic 2 bytes, version 1, payload length 2, payload (at most 400 bytes: 64 ladder codes as
   uint16 and at most 34 float constants), CRC-16 2 bytes. The record is written with `EEPROM.update()` only by
   State-98 key `7` (section 12.8) and read once in `setup()`.
3. **Ag105 policy, FC window and the purge interface.** Section 12.5; the State-1 window call site (Idle does not call
   `chargingControl()`, ino:7888) and the cruise branch compiled out; the configuration check and the eFuse-blocking
   probe; the predictor interface of section 9.11.2 (`purge_tto`, `purge_active`, the permit, the prediction and the
   UNKNOWN state), the pre-purge sequence and share override, the re-entry gates, `ERR_FC_ONLY_COLLAPSE`, the State-2
   standstill window behind `IC1_FC_RUN_STANDSTILL`, and the removal of the fw v33b lockout from the charge path (the
   FC-only share-selection lockout is unchanged). The purge predictor itself is the operator's design (ruling OR-P,
   formerly item T-E-01); this round implements the interface and tests it against an ideal-predictor stub.
4. **Telemetry v5, BLG and Pi bridge** (OR-H, OR-R), including the charge_goal refusal flag.
5. **HIL plant, observation frame and injection frame** (section 12.10). Revision 12 (BT8-REQ-04): the injection-frame
   extension (sources for the ladders, pin 8, pin 20, I_PACK1, I_PACK2 and V_PACKN; a lockstep HIL protocol change) is part
   of this item, because the `static_assert` of section 12.10 holds IC1 off the HIL until it lands.
6. **Pi EMS (Stage-1 prerequisite, ruling OR-RQ; corrected in revision 11).** The deployed EMS nodes use `charge_goal`
   as a regen gate (`sdp_ems_node_2026-10-28B.py`:293-319; the same `_charge_goal` latch is in the 10-26A, 10-27A,
   10-27B and newbuild nodes), so they cannot request a window. A window request requires command byte 20 set to 0xA5
   together with `charge_goal` above `CHG_GOAL_MIN`; without it the firmware refuses with code 15 (section 9.11.6). The
   Pi round sets the flag from an explicit FC-charge decision only (the SDP P_batt < 0 branch, a J_charge table or a
   parked-charge command), never from the regen gate; adds the parked form (`mode_cmd` 4 with the flag); decodes the
   Table 25 codes; and lands in lockstep with OR-H through the protocol-bump procedure. Requests in motion are refused
   with code 3. Gate W2e checks the deployed node against the firmware before the first vehicle FC window.
7. **HIL suite and tool mirrors.** The charge scenarios of `tools/run_hil_suite.py` and `tools/hil_plant_sim.py` (27 and
   95 charge_goal references) are re-specified for standstill windows between purges or retired; the `governor_model`
   and `ems_walk` mirrors and `hil_replay_suite.TARGET_FW_VERSION` follow. The share-override duration of Table 21 is
   firmware-only and is measurable on the existing HIL plant once the `static_assert` of section 12.10 is lifted.
8. **The fw v38 plan** (`docs/fw37_planning_2026-11-04.md` sections 3.3, 4 and 9.3). Under `PACK_RETURN_CHANGEOVER`
   the regen interlock layers 1-3 of planning section 3.3 are **superseded** by the VOK hardware, the eFuse source term
   and `ERR_VCHG_FED` (the bus can feed the charger only through a fault that these detect); the V_rgn calibration
   (M-R2) and `LIMIT_V_RGN_MAX` are **prerequisites** of Stage 2 (`ERR_VOK_STUCK` uses pin 39); telemetry v5 and BLG
   v10 are **absorbed** as the base of protocol v6 (section 12.9); the "charger proven" fault gating is **superseded**
   by the self-test, the configuration check and the probe; the 1x drive notch and the encoder items are independent.
   The size estimate below is stated against fw v37 rev 2 and assumes that the v38 telemetry and BLG work lands first.
9. **Documentation.** PLAN.md section 9 (State-98 keys), the CLAUDE.md doctrine text named by OR-W and OR-G, and the IO
   CSV amendment.

The size of the change, calibrated against the repository history (fw v28, one feature package, added 1,916 `.ino` lines
and 389 `run_tests` checks; the fw v37 `J` session, one State-98 mode with three guards, about 1,250 lines; the fw v37
rev 2 guards alone added 449), is re-derived per package in revision 10 (calc10 section 9; revision 5 gave
4,000-7,000 lines before the purge package and before the fault set grew to 27 new conditions against the 18 of
fw v37 rev 2):

- mode manager with 8 states, self-test, two ladder decoders and the EEPROM record: 1,900-2,900 lines (1-1.5 fw v28
  packages);
- the 27 new fault conditions at 100-150 lines each: 2,700-4,100 lines;
- Ag105 policy, FC window, configuration check, probe and dump check: 1,250-1,900 lines (1-1.5 `J` sessions);
- purge interface, PI-4 latch, the D-s window, the in-band substitution and the traction hold: 1,000-1,900 lines
  (0.5-1 fw v28 packages);
- telemetry v6, BLG and the refusal word: 300-600 lines.

The total is about 7,100-11,300 lines of `.ino` code and 1,450-2,300 host test checks at the fw v28 ratio, plus
1,000-2,000 lines of tool, HIL and Pi changes (estimate, UNCONFIRMED). About 90 % of it is Stage 1; the purge package
alone is 1,000-1,900 lines. The estimate is not re-derived for the revision-11 items (the State-2 dump check, the byte-20
flag parse with code 15, the fixed-split freeze and restore, the guarded Idle FC_BUS release, the boost-enable entry and
exit rules, the BLG field) or the revision-12 items (the self-test re-run rule with code 16, the dump-check retry, the
State-98 window-request key, the injection-frame extension); open item 43.

## 13. Hard-requirement status

Table 17 states HR1-HR5 for revision 12.

Table 17. HR status.

| HR | Status | Reason |
|---|---|---|
| HR1 regen | **FAILS as stated**; BENCH for a relaxed criterion | 23 W is unreachable in any regen window (at most 22.73 W at the 8.0 V entry gate, provided that I_L stays at or below 0.75 A, gate B8). The regen profile reaches 19.8-22.4 W (meets the 18.9 W peak by calculation with the unverified 0.88 efficiency). Under the command-step arm (OR-V') pin 30 was HIGH 5.4-7.4 ms after the braking command, ahead of the first VOK assert, under the retired fw v35 drive law; under the flashed fw v37 law the -2 A arm comes 4-26 ms after a decel step, so the first pulse of a gentle decel can be lost (section 7.8, re-derivation pending); under the revision-4 [RER] power arm the first pulse of every decel was lost (at most 43.9 % of the node energy above 18 V reachable), which ruling 1 classes as a fail. VOK removes the charger input between pulses, so every pulse needs a cold start. On the 19 ms pulse the hardware chain leaves 5.3-6.4 ms from eFuse enable at typical t_D_ON, of which the eFuse uses 4.4-5.6 ms; the hold-up stage is withdrawn (section 14.4), so the fast-decel family has no capture margin from hardware alone. On the 47 ms pulse 26.4-29.3 ms remain. At the prior 65-170 ms cold start the rise of no pulse is captured; the VESC-stop tail keeps VOK asserted for 84-416 ms per pulse (section 7.8), so a start inside the tail can capture tail energy (V2-4). Gates S0-6 (with the window-open latency term measured from the first command below -0.1 A), V2-0 and V2-4 (captured charge per event, and the fraction of decels that open a window) decide per pulse family. The 2.35-2.5 A output holds only up to 45 C module ambient (Ag105 DS p.17 Table 9). **Availability is bounded before any bench gate:** on the 23 recorded Pi sessions the revision-5 preconditions admitted regen windows in 2 (the `ERR_IPACK_PLAUS` pass at 1.0 A occurred in 3 sessions, 13 sessions started at or above 8.0 V and so ran no configuration check, and all 7 HR1 evidence events ran at V_batt 8.21-8.45 V, above the 8.0 V gate; `calc/bt3_bag_scan_plaus.py`, `calc/bt3_bag_scan_vstart.py`, `calc/bt3_requirements_operability.py` section C). Revision 6 re-keys the pass to 0.4 A (19 of 23 sessions), exempts the configuration check from the 8.0 V gate, and leaves 12 of 23 sessions with a pass followed by V_batt below 8.0 V; the window share of driving time is then bounded by the time spent below 8.0 V, which the 8.0 V regen gate holds until S0-8b. Stage 2 on the vehicle needs a configuration check inside the purge permit of section 9.11.2 (section 9.7a). |
| HR2 FC charging | **PROVEN_CALC by sequence under rulings OR-P and OR-SC**, conditional on ruling 9 (R_KA), S0-6 and the Pi round of ruling OR-RQ; BENCH W2, W2a-W2e. Parked: **1.17-1.19 A net pack current** (1.18-1.20 A of charger output; revision 12). Drive cycle (variant D-s): **at most 1.9-31.9 mAh, 9-53 % of the cycle time** (request at every stop, no T_still dwell). Against EMS FC-charge requests: **undetermined** (the recorded sessions carry 0 s of FC-charge request; revision 11) | Revisions 9-11 (section 9.11). Revision 11: the revision-10 figure of 107.3 s of 446.6 s measured the regen latch of the deployed nodes and is withdrawn as an HR2 value; under the revision-10 text D-s could not open at all on those sessions (code 12, the dump check ran in State 1/98 only), and the State-2 dump check restores the counterfactual to 106.6 s (calc11 section 1). The fixed window split keeps the module input power fully deliverable (calc11 section 2). Purges are survived by sequence: the operator's ideal predictor announces each onset at least 80 ms ahead whenever an FC window can be open (290 ms in closed-loop State 2 for the share shift), and the window drops its feed, bonds the pack and re-closes BT_BUS before the onset (D-BT-EN conducting 34-47 ms after the prediction, 61.7 ms on the deadline chain); charge current resumes 0.37-0.49 s after the onset, so 94.5-95.6 % of each 10.34 s period is usable in P and D-s (calc10 section 2). An unpredicted purge, including one that the predictor recognises late or reports as UNKNOWN, latches State 99 through `ERR_FC_ONLY_COLLAPSE` with no BT_BUS re-close and no damage path found (Table 24, calc10 section 5), which ruling OR-SC accepts. Windows run within the FC budget (governor 1.25 A, P_MAX 1.247 A, `OC_FC` 1.4 A): parked or at standstill, with no traction in the window. Per drive cycle on the plant model with a request at every stop, D-s gives at most 1.9 mAh on the 61 s cycle, 23.3 mAh on the FTP-75 slice, 12.4 mAh on ftp75c and 19.3 mAh on UDDS (Table 27); with the frontier SDP v6 policy, which requests no window, HR2 in Run is 0. Windows in motion (variant D) are not adopted (OR-DM): traction allowance, sense error and the uncovered purge at a high pre-purge I_fc. Without R_KA every cold start may run an 8.4-11.7 s Bring-Up, which leaves 0-0.19 A. Until S0-8b, FC windows open only below 8.0 V. |
| HR3 no circular loop | **PROVEN_CALC** against single faults in the bonded mode and in both windows, **conditional on `ERR_VCHG_FED`** (rows F15, F17), on the C-2 injected-bypass gate for an eFuse bypass, and on C-2, B10, S0-2, V2-1 (with the tap-open sub-steps and the ratio rule) and V2-2 | Bonded: the charger input is unfed in Stages 1-2 (firmware refuses REGEN and FC_CHARGE there, except the 100 ms eFuse-blocking probe with FF1 clear and pin 32 LOW), EF_EN needs FF1, and a fed input with both feeds LOW latches `ERR_VCHG_FED`; with Stage 3 see F37. Regen window: VOK acts on two diverse elements; the two channels share no tap; a tap fault fails toward NOT OK (U_BPk); a channel that permits while the measured V-MOT/VBUS ratio is below every healthy release level latches `ERR_VOK_STUCK` within 50 ms, independent of the V-MOT decay rate (revision 6; requires the M-R2 pin-39 calibration). The two-failure count for an eFuse bypass (rows F11, F35, F36-M2) holds only once the U_MS probe has passed the C-2 injected-bypass gate; before that the bypass is latent with no in-service detector, and the HR3 claim for the D-BC-RG-plus-eFuse pair degrades to one detected plus one latent failure (that pair closes a loop only inside a regen window, where the module sense is in circuit). A fed module node in the bonded mode latches `ERR_MOD_FED`. A D-BC-FC power-stage short (F17) feeds VCHG-IN from VBUS at every VOK assert, which is a one-fault loop; `ERR_VCHG_FED` detects it before any window, so with the detector in service a loop needs two failures. A short that arises inside a window is latent until its exit plus 1.0 s. A traction onset that pulls V-MOT down faster than about 9 V/ms can let D-MT-EN feed the charger for at most about 12 us (about 15 uC) before the cut; the bus never sustains a feed. FC window: Q_X1 prevents; D5 cuts a D-BT-EN short. |
| HR4 no runaway | **Bounded** by U_C2 (2.65-3.64 A pack charge with the 3V3 tolerance), U_IM (eFuse input above 1.51-1.98 A clears FF1, including the SLVSE94G IMON gain range; below the I_OL minimum on every unit by R_ILIM 8.06 kOhm and the per-unit S0-12b trim), the eFuse (I_OL 2.06-2.41 A input; latch-off after tCL_PLIM 129-202 ms for an overload after start-up; for a start into an overload thermal regulation for up to 2.9 s with FLT not asserted, which U_IM bounds) and the profile networks (every open or short single fault at or below 1.75 A; a high-resistance fault up to 2.5 A, caught by `ERR_PROFILE_OC` and bounded by U_C2) | The Ag105 OC trip is credited only after S0-2 on the rig and D-3 on the vehicle module. A shorted Kelvin pair (F44) blinds U_C1 and U_C2 until `ERR_IPACK_PLAUS` fires; U_IM and the eFuse I_OL remain. The magnitude stays far below the ML0227 11-13 A in every case. Two pack-direct loops that bypass every one of these bounds are closed in revision 6: a VBATN_X chafe onto a positive conductor (39-252 A prospective through the module sense) clears F_VX (row F48), and the balance midpoint conductor reaches GND only through RB3 or RB1A 4.7 kOhm (at most 16.2 mA and 0.83 mA, rows F34b and F47; revision 7). A dump stuck on is detected by the pin-32-LOW dump check before the first window of either type in every power cycle, or by U_IM at the same eFuse start (`ERR_MOD_DUMP_ON`, `ERR_CHG_TRIP`, row F50); if it arises later, `OC_FC` and U_IM end an FC window while the module charges, and U_IM trips the first regen pulse on most corners (row F50). A chafed signal lead can no longer force a pack or bus voltage onto an LB input or a Teensy pin (rows F54b, F54c; revision 8). An open R_SH element exposes both INA240 inputs to about -8.4 V (row F34c): the current bounds then rest on U_IM and the eFuse until the repair rule replaces both amplifiers (ruling OR-AB). |
| HR5 fail-safe inhibit | **PROVEN_CALC** for absent rails, bench-gated for a slow 3V3 collapse and for an LB-only 3V3 loss with the Teensy running | Bonded, D-BT-SQ disabled and eFuse off with the Teensy unpowered, in reset (FF1 clears at once through U_P33 and U_N33), hung (pump clears FF1 in 43-76 ms; MCU watchdog resets), with 3V3 or 5V absent, with the SB cable open (outside a window), with the SHDN wire open or with the BQ29200 OUT fly-wire open (Table 13). No autonomous re-arm: FF1 needs a pin-33 edge. A slow 3V3 collapse through 0.84-1.57 V is not proven (row F45, gate B11d). An LB 3V3 tap open with the Teensy running keeps the bond and the eFuse off, but releases the D-BT-SQ cross-lock and the D-BC-RG clamps to pins 32 and 30 for at most 3 iterations, until `ERR_CHG_LADDER` drops both pins (row F51, gate B11e). A chafed signal lead can no longer drive a pack or bus voltage into the 3V3 rail that supplies the trip logic: every LB-bound lead carries a series element or runs in a segregated sleeve (rows F54b, F54c; revision 8). Bench: B11, B11b, B11c, B11d, B11e, B16, C-1 (sleeve insulation), C-2. |

## 14. Staged build

### 14.1 Stage 0: bench rig, no board change

The rig reproduces the vehicle charge-mode topology around two spare Ag105 modules: unit X (stress unit, never fitted)
and unit Q (qualification unit, run only inside the rated envelope; it may become the vehicle module through gate
D-3(a)). The rig has the following parts:

- a lab supply on Vin+ through the CB circuit (eFuse, profile networks, LD tie, U_IM), with its current limit at or below
  1.2 x P_in / V_in for the profile under test;
- an RT1987 (as D-BT-SQ) between the module VBat+ and the pack positive, with a switchable 1 kOhm R_KA from pack positive
  to the RT1987 VIN side;
- an electronic load of 0.3 and 0.6 A (and the gate-B8 measured I_L) from pack positive to Vin-, which is the I_L path
  outside the sense;
- the pack return into VBat- through an external 10 mOhm 4-terminal shunt (0.5 mV per 0.05 A; 62.5 mW at 2.5 A) read by
  an INA240A1 on the rig (or a calibrated DC current probe with a stated accuracy of 0.02 A or better), with the
  bandwidth limit and the averaging stated in the gate log (1 ms averaging for the steady criterion; at least 50 kHz for
  the start-peak criterion); a mandatory fast trip on that channel at I_set + 0.6 A driving the eFuse SHDN (revision 6,
  BT3-AG-2: an 8-bit scope on a 0.5 mOhm shunt resolved 62 mA per LSB under 150 uV p-p of module ripple);
- MPPTD and the I2C pull-ups held at 3.3 V from an always-on rail;
- for S0-5 and S0-6, a source made of a 0.48, 0.97 or 4 mF bank charged by a current source through the CB eFuse;
- a programmable two-quadrant pack simulator (sink limit I_set + 0.3 A) with the profile of S0-2, and a real 2S pack
  only after the simulator runs pass;
- **one earth point, at module Vin-** (rule C2 applies to the rig whether or not a pack is connected): the I2C/MPPTD
  master is battery-powered or behind a USB isolator; every measurement on VBat-, VBATN_X, the shunt or the simulator
  negative uses a differential or isolated probe or a floating DMM; the lab-supply and simulator outputs are confirmed
  floating. Before every energisation of S0-2, S0-2b, S0-6 and D-3(b), the resistance from VBat- and from the simulator
  negative to earth and to Vin- is measured with every instrument connected, and must be open (BT3-AG-3: a USB-earthed
  I2C master and a single-ended probe ground on the shunt close a path in parallel with the sense).

Stage 0 measures every Ag105 unknown that decides whether Stages 1-3 have value. Unit X runs every stress gate (S0-3,
S0-5, S0-6 with a capacitor-bank source, S0-9, S0-10) and the first S0-2 exploration with both R_KA states. Unit Q runs
only S0-1, S0-2, S0-4, S0-6 (lab-supply source) and S0-8b, and runs S0-1 and the efficiency and thermal reference before
any other gate. Results apply to the vehicle module only through gate D-3. Stage 0 needs rulings OR-A and OR-J (the
sacrificial module for S0-10) and no motherboard change. OR-A was accepted on 2026-11-09; OR-J is open, so S0-10 waits
for it. Before Stage-2 firmware is written, Stage 0 also records a
fw v37 decel BLG with a non-zero target steeper than coast-down (section 7.8).

### 14.2 Stage 1: standstill charge isolation

Stage 1 fits SB, CB and LB without the VOK channels (U_V1, U_V2, U_BP1, U_BP2, U_CH1, U_CH2, U_VA, Q_H1, Q_H2) and
without the D-BC-RG clamps (Q_RG1, Q_RG2, Q_RB1, Q_RB2), and makes modifications M1-M4, M6 and M8-M16. M5 (the D-BC-RG
enable cut) is deferred to Stage 2: it is irreversible, and in Stage 1 it adds no HR3 margin. With pin 31 HIGH, Q_X1
clamps BT_BUS, so a D-BC-RG feed at standstill would come from the same FC-only bus and close no loop; in the bonded mode
the eFuse needs FF1; and a fed VCHG-IN with pin 30 LOW latches `ERR_VCHG_FED`. R_VKP holds VOK LOW, so the eFuse regen
source term RGQ is false, and firmware `IC1_STAGE` 1 holds pin 30 LOW. `IC1_STAGE` 1 permits FC windows in State 1 or
State 98, and with `IC1_FC_RUN_STANDSTILL` 1 in State 2 at standstill (revision 9), the configuration check and the
commissioning procedure.

Stage 1 delivers FC charging between predicted H-20 purges with the pack return isolated from the ML0227 configuration,
and the self-test and protection layers in service (revision 9, section 9.11). It meets the operator's goal (Ag105 kept,
battery return isolated during charging, Teensy-controlled with fail-safe defaults) and is the recommended first build
and end state until the Stage-2 evidence exists. The order of commissioning is: a bench supply on J-FC for commissioning,
C-2b and W1; the H-20 parked between predicted purges (gates W2a, W2 and W2c, variant P); then State-2 standstill
windows (gate W2b, `IC1_FC_RUN_STANDSTILL` 1, variant D-s). Gate W2d counts false latches throughout; gate W2e precedes
the first vehicle window (revision 11: the Pi request flag). Stage 1 needs the
following rulings, taken from the stage column of section 17: OR-A, OR-C, OR-2', OR-4, OR-5', OR-D, OR-E, OR-G, OR-H,
OR-I (conditional on S0-2), OR-K, OR-L, OR-M, OR-O', OR-DM, OR-PK, OR-P (decided 2026-11-08), OR-R, OR-RQ (revision 11), OR-S, OR-SC (decided
2026-11-08), OR-T, OR-VC, OR-W, OR-X, OR-AA, OR-AB, OR-AC (revision 8: the D_VC1 endpoints) and ruling 9 (R_KA,
decided with S0-6 before the build). Ruling 9 is the decision point that sets the Stage-1 HR2 value (calc9 section 2):
with R_KA, 1.17-1.19 A net pack current when parked and 1.9-31.9 mAh per drive cycle at standstill (Table 27; the fw v32a cooldown
applies only after a 30 s dwell close, so a purge-synchronised re-entry does not pay it, `calc/verify_hr2_cooldown.py`);
without R_KA, 0-0.19 A when parked (Bring-Up of 8.4-11.7 s per cold start, UNCONFIRMED for an isolated return, S0-6).

Status of the Stage-1 rulings after the operator rulings of 2026-11-09 (section 17): OR-AC is decided at option (d) for
the first build; OR-I and ruling 9 are accepted as proposed and are decided by S0-2 and S0-6; OR-L, OR-R and OR-X remain
open and are needed before the Stage-1 firmware round; every other Stage-1 ruling is accepted as proposed, except OR-P and
OR-SC, which were decided on 2026-11-08.

Ruling OR-T offers a reduced Stage 1 ("Stage 1-lite"): a single FC profile, the ladders replaced by direct readbacks,
and one INA240. It saves about 44 % of the LB ICs. It is not recommended: with one INA240 a single amplifier fault
defeats both U_C1 and U_C2 and only U_IM and the eFuse remain, and the injection cannot detect an amplifier fault
without the cross-check. The simplification adopted instead is the Stage-2 deferral above. On 2026-11-09 OR-T was
decided at Stage 1 as specified.

### 14.3 Stage 2: Run-time regen

Stage 2 makes M5 and M7, fits the VOK channels and the D-BC-RG clamps, removes R_VKP, R_CHP1 and R_CHP2, and enables
`IC1_STAGE` 2. It needs the Stage-1 rulings and OR-B, OR-7, OR-V', OR-Y and OR-Z (section 17; OR-7, OR-V', OR-Y and OR-Z
accepted as proposed on 2026-11-09, OR-B open), the M-R2 pin-39 calibration, and
gates V2-0 to V2-6. On the vehicle it also needs the
Stage-1 H-20 path (section 9.11, gates W2 and W2a): each power cycle admits regen windows only after a configuration
check (section 9.7a); this check holds the bus FC-only in State 1 for at least `AG105_SETTLE_MS` (500 ms, ino:2484) after
the Idle self-test, so it runs inside the purge permit of section 9.11.2 with its own admission horizon (the check
duration plus T_lead,min, TODO(calibrate) with ruling OR-Z) and closes on a purge prediction. The Stage-2
firmware is written and tested only after S0-6 shows a cold start inside the per-family allowance of Table 8a with the
window-open latency. Its harvesting value depends on S0-6, V2-0 and V2-4 per pulse family and on the VESC behaviour
S0-R3 / T-E-03; on present evidence (cold start 65-170 ms; Pi-run second pulses at 16.8-19.0 V; UDDS braking no steeper
than coast-down) it is near zero.

### 14.4 Stage 3: hold-up (withdrawn in revision 7)

Revision 6 specified a hold-up capacitor C_HU (1.5 mF) on the eFuse output, with the dump Q_MD re-keyed to FF1./Q so
that it fired only when FF1 cleared. Battle-test round 4 showed that this deadlocks every commanded Stage-3 exit. Exit
step 2 waits for pin 8 LOW while FF1 is still set, so the dump is off and the node drains through R_MB and the module
idle current only: 0.60 s at 18 mA and up to 4.85 s at 0 mA, against the drain deadline (`calc/verify_stage3_exit_drain.py`
section 1). `ERR_MOD_DRAIN` then latches, the re-bond follows with C_HU charged, and under the S0-5 threshold behaviour
pin 8 stays HIGH in the bonded mode with V_chg at or above 9 V, which latches `ERR_MOD_FED` (State 99) (BT4-TR-01,
FM4-4). R_MB also cut the hold-up of 1.5 mF from 583 ms to 469 ms against the 535 ms target (same script, section 2).
Stage 3 is therefore withdrawn from the build: nothing of it is fitted, and no row, mode or gate of this document assumes
it.

A re-specification needs at least the following:

- the dump keyed to NOT(FF1.Q AND (P30Q OR FCQ)), so that it starts at the commanded feed drop and at any FF1 clear,
  while the hold-up survives between VOK pulses (pin 30 stays HIGH through a regen window);
- a Stage-3 T_drain,max of at least 20 ms (the drain to 9.15 V takes up to 16.4 ms at 1.93 mF from 21.5 V through
  10 Ohm, same script, section 3) and the OR-2' traction cap restated with it;
- C_HU of at least 1.71 mF with R_MB included, or R_MB switched out while FF1 is set;
- Q_MD rated for at least 3 A pulsed (21.5 V / 10 Ohm = 2.15 A) and R_MD for 0.35 J per FF1 clear;
- an eFuse slew low enough that charging C_HU stays below the U_IM trip (C_DV about 5 times larger or more; at C_DV
  10 nF the inrush into 1.5 mF is 6-8.7 A);
- gate S0-13 showing that a warm module resumes without Bring-Up.

Ruling OR-F decides whether that round runs. On present evidence (cold start 65-170 ms; HR1 capture near zero) it has
no measured harvest to recover.

## 15. Bench test plan

The gates run in the order below. A NO-GO stops the stage and names the fallback. No gate has been executed. Revision 12
(BT8-REQ-02, BT8-REQ-03) moved B-FPK and B-PKN ahead of C-2b, split B8 into B8-1 (Stage 1, after W1) and B8-2 (Stage
2), and put W2e ahead of every vehicle window; elsewhere in this document "B8" means B8-1 for the FC window and the
M16 temperature, and B8-2 for the regen window and the HR1 hold condition. Every bench-supply session on J-FC uses the
section 9.2 setting.

WARNING: Do not connect an earth-referenced instrument, supply, load or charger to pack(-), KS+, KS-, PACK-, VBATN_X or
an SB node while the pack is installed. An earth path in parallel with the pack return bypasses the Ag105 sense and,
upstream of R_SH, U_C1 and U_C2; several amperes then flow in the probe lead and the USB ground. Measure these nodes only
with a differential probe, an isolated probe or a battery-powered DMM.

WARNING: Connect the pack connector before the balance plug, and disconnect the balance plug first. A balance plug
connected without pack negative makes the BQ29200 VC1/VC1_CB inputs, through RB3 and RB1A, the only board return: the
Teensy browns out, and the clamp D_VC1 holds VC1 at -V_F while RB1A 4.7 kOhm limits VC1_CB to under 1 mA (row F34b),
which holds only after gate B-PKN has shown V_F below 0.25 V. Do not connect the balance plug before gate C-1 has
checked the orientation of D_VC1 and the value of RB1A: a reversed D_VC1 holds the BQ29200 in OVP and puts the pack
voltage across its VC2-VC1 input (row F47).

WARNING: Disconnect the balance plug when the vehicle is stored for more than one day. A shorted D_VC1 drains cell 1 at
16 mA (0.39 Ah per day) with the Teensy unpowered, and no firmware runs to detect it until the next power-up (row
F47).

### 15.1 Stage 0 gates (spare module, vehicle-topology rig)

| ID | Gate | GO | NO-GO action |
|---|---|---|---|
| S0-1 (B1) | Ag105 sense resistance R_s (pins 14/15 to 16/17, unpowered); CSD18510Q5B body-diode V_SD at 1-3.6 A | Values recorded | - (input to OV_BATT, R_allow, W0 and the BQ margin) |
| S0-12 (B16) | Fitted eFuse (TPS26631 or the TPS26636 alternate) with MODE open and PGTH grounded: an overload applied after a completed start-up (run before S0-2); a hard short | Post-start overload: latches within tCL_PLIM (129-202 ms) and stays off; FLT LOW within 30 ms; hard short: fast trip at about 3 x I_OL | Choose another eFuse |
| S0-12b | Per-unit trim on the fitted CB, at 25 C and at the hot-soak temperature (and at the coldest operating ambient): measure the IMON gain and the unit's own I_OL; then start into an overload (enable the eFuse by SHDN into a load that draws more than I_OL from t = 0), once and repeated at the regen pulse cadence (19 and 47 ms on, 535 ms period, 20 cycles), with U_IM and a test FF1; also a soft overload held within a 1.5 V drop | Measured U_IM trip below the unit's I_OL minus 0.05 A and above 1.46 + 0.05 A at every temperature; U_IM clears FF1 within 5 ms of the enable in every case; the time to FLT without U_IM recorded | Trim R_IMa and repeat; no charge session until it passes |
| S0-2 (B14) | Pre-energisation earth check (section 14.1). Positive control first, on unit X: jumper VBat- to Vin- through the rig shunt at R_CS 10 kOhm (500 mA, Table 4 JSON) to make a sense-blind module; the rig must flag the disagreement between reg 0x06 x 0.011 A and the shunt, and the CB U_IM or the rig fast trip must end the run inside its stated range. Do not run S0-2 on unit Q until the positive control has passed. Then sense coverage on unit X, then unit Q, in each of {R_KA fitted, R_KA open} x {LD tied to Vin-, LD open}, with I_L present at the start: scope-captured pack current and reg 0x06 x 0.011 A against the external shunt. Simulator profile: 0 V with D-BT-SQ open (Bring-Up); 5.0 V (Pre-Charge, simulator only); 7.4 V (CC); a ramp to 8.45 V (CV, Fully Charged); a step to 7.9 V (restart); a -0.5 V step in 1 ms (OC stimulus, TODO(verify: Silvertel) whether it trips). Then a real pack (CC, CV, Fully Charged, restart) | Positive control flagged and ended; pack current at or below I_set + 0.2 A at every start and sub-state transition (read on the 10 mOhm channel); steady agreement within max(0.05 A, 10 %) in every reachable sub-state with LD tied (valid measurements only); sub-states not reachable on the rig are recorded as such, not failed; the peak module output current (I_pack + I_L) of every unit-Q run recorded | The Ag105 regulation layer is not credited; U_C2, U_IM and the eFuse are the sole current bounds (OR-I, accepted 2026-11-09) |
| S0-2b | Input cycling (run only if S0-6 gives an HR1 GO), on unit X: eFuse SHDN on for 19 ms and for 47 ms per 535 ms, both R_KA states, the input cut by the eFuse at full current, with the CB dump fitted; the cycle count is the vehicle's per-drive pulse count (TODO(calibrate) from V2-4; at least 2000 cycles each); reg 0x00-0x02 read back every 100 cycles | Pack current at or below I_set + 0.2 A at every restart; no module fault code; no register change | Stage 2 not pursued |
| S0-3 (B6) | Battery opened during charge at 0.5, 1.25 and 1.75 A, with the eFuse turned off first and with D-BT-SQ alone: VBat+ overshoot | Below 30 V (RT1987 VIN 40 V absolute maximum, DS-00 p.6; C-D11 rating TODO(verify: BOM)) | Add a TVS clamp on VCHG and repeat |
| S0-4 (B18) | Resistor mode: reg 0x00 = 0x00 with 62.0 kOhm and with 24.02 kOhm; R_CS points 100k, 200k, 470k, 1M and open (open-detect boundary, TODO(verify: Silvertel)); reg 0x02 = 0xFF with MPPTS open and with 41.7 kOhm (start threshold measured); profile alternation across at least 3 input-off cycles with the battery and R_KA connected, each input-off taken only to the cold-module condition of section 12.4 item 2 (node below 8.69-9.15 V for 20 ms with the dump fitted); BSS138 off-state in the networks; on unit X, reg 0x01 set to 0x05 (7.8 V) against an 8.4 V simulator with the input powered: the eFuse input current direction and VCHG-IN_M recorded | CC within 10 % of 1750 / 1250 mA; thresholds within 0.5 V of 18.0 / 13.82 V; the profile follows every cold-module cycle; the reg-0x01 case recorded | Fall back to I2C writes per window (ruling OR-5); if only the threshold misses, re-select R_MP for a mid-band target |
| S0-5 (B5a) | Threshold behaviour with MPPTD HIGH, from the 0.48 / 0.97 / 4 mF source; the eFuse start into a dumped module node from the 0.48 and 0.97 mF sources (node voltage at each VOK release, section 7.2 item 5) | The module stops drawing or regulates its input at or above 17.95 V on the regen profile; the dumped-node start recorded | Stage 2 harvest limited by the VOK limit cycle |
| S0-6 (B3) | Cold start from eFuse enable (input present, module node dumped to 0 V) to 63 % of I_set, with R_KA and without, both profiles, 20 repetitions; record the state entered with R_KA and the module case temperature | HR1 GO for a pulse family only if (a) the window-open latency t_open = t_arm + t_settled + t_step5 (measured from the first command below -0.1 A under the flashed drive law; 5.4-7.4 ms by calc5 section 7 under the retired fw v35 law, re-derived for fw v37) is at most the VOK assert time t_VOK from the command, and (b) t_VOK + t_D_ON (V2-0) + 1.07 ms (D-BC-RG ramp to the eFuse UVLO) + the eFuse delay and ramp + the S0-6 interval is less than the time for V-MOT to reach 21.35 V on that family's fastest measured pulse: at t_D_ON 8 ms, at most 5.3 ms on the 19 ms pulse and 26.4 ms on the 47 ms pulse (Table 8a). Under the revision-4 [RER] arm (t_open at least 42.3 ms) condition (a) fails for the first pulse of every decel. HR2 GO at about 1 s or less | HR1: Stage 2 has no capture value for that family without Stage 3. HR2: Stage 1 FC windows have little value |
| S0-7 (B4) | Unit X, R_KA fitted, input absent, pack present: poll 0x30 for 60 s; record the ACK/NAK count, the status byte and reg 0x07; record whether a pushed-HIGH MPPTD or the I2C pull-ups back-power the module, and whether a released (open-drain) MPPTD reads MPPT enabled (status byte bit 3). Then force an OC or Battery Disconnect error, cycle the input only, and record whether the error clears. Then the probe state: input fed at 16 V with pin 32 LOW (VBat- open), R_KA fitted and open, V_pack 7.4 and 7.95 V: log the status byte, GENSTAT, reg 0x07 and STAT every 5 ms for 1 s | Recorded (input to ruling 9). Released MPPTD must read MPPT enabled, or pin 5 reverts to push-pull through 10 kOhm (section 12.5 item 3). If GENSTAT 101 appears in the probe state with R_KA, record it: G3 would latch in every configuration check | - |
| S0-8 (B5) | Restart from Fully Charged with the pack below 8.0 V | The restart level recorded; with S0-8b it sets the V_batt restart condition after a Fully Charged exit (CC-15) | Keep the 8.0 V entry gate (CC-B10) |
| S0-8b | Cold power-up with the pack at 7.95, 8.05, 8.20 and 8.35 V at rest, both profiles: reg 0x06, GENSTAT and STAT | Recorded | If the module reports Fully Charged above 8.0 V, IC1 charges only to about 8.0 V at rest; keep the FC-window 8.0 V entry limit and take ruling OR-B / OR-M on the ceiling |
| S0-9 (B7) | Reverse current at 3.5 A through the sense until thermal steady state, module unpowered and powered; record the VBat- to Vin- drop | No damage; the drop exceeds I x R_s (S0-1) by no more than 50 % of the S0-1 V_SD at that current | Lower U_C1 and repeat |
| S0-10 (B7b) | Reverse pulse of 17 A for at least 0.5 ms through the sense, sacrificial module | No damage | Ruling OR-J |
| S0-11 | Ag105 input capacitance C_mod; eFuse inrush with C_DV 10 nF; module run-on after the input is cut at 2.35 A output (time until the module output stops); the open-input decay of the module node from 16 V to 11 V and to 9 V with no dump and with R_KA fitted and open (records I_q); the same decay with R_MB alone and with the dump Q_MD/R_MD; the time to the pin-8 LOW edge | Inrush at most 0.6 A (at C_DV 10 nF this holds for C_mod at or below 103.6 uF; revision 12, BT8-TR-01, calc12 section 3); with the dump, run-on ends and the node is below 9 V within 3 ms from 21.5 V; with R_MB alone below 9 V within 0.5 s; C_mod at most 221 uF and at least 47 uF (revision 8: below 47 uF the healthy U_MS hold after a feed drop from 13.4 V can fall under the 150 us sample of the exit hold check, calc8 section 1, `calc/bt5_transient_sim.py` section 2) | Raise C_DV to at least 10 nF x C_mod / 103.6 uF, measure the eFuse output ramp, set the `ERR_MOD_DUMP_ON` sample to the later of 10 ms and the ramp plus 2 ms, re-derive the Stage-2 regen-pulse budget (calc4 section 11) before Stage 2, and repeat; re-size R_MD and R_MB to the measured C_mod (calc6 section 3); if C_mod is below 47 uF, measure the hold at C-2b item (g) and drop the 150 us sample if the hold is under 200 us |
| S0-14 | Probe qualification on the rig: the CB eFuse IN-OUT jumpered (a deliberate bypass), then SHDN_EF tied HIGH; run the section 9.7a probe sequence with R_KA fitted and open, at V_pack 7.4 and 7.95 V | U_MS reads HIGH and the probe latches in every case (a rig that runs firmware with `OC_FC` may latch `OC_FC` first, which also counts and is recorded); with the jumper removed it passes | Re-trim U_MS; no Stage 2 until it passes |
| S0-13 | Exit cases on the rig at the regen profile: (a) a commanded exit (feed off, the pin-8 drain through the CB dump, then the re-bond) and (b) a hardware-trip exit (eFuse cut and a re-bond path closed within 0.3 ms); scope the pack current and the module output until the module stops | (a) no pack current through the bypass after the re-bond; (b) pack current below the U_C2 range within 1 ms of the cut, no module fault code afterwards | (a) re-size R_MD; (b) record the energy in F10 |

### 15.2 Board gates before and after the rework

The gates of this section run in this order: D-1, D-2, B2, BG-17a, B13, P8 and JBL before any rework; then the Stage-1
modifications M1-M16 (section 5.5); then P-M1 and D-3; BG-17b runs after M8, M16 and LB are fitted (revision 8,
BT5-BO-05). Under D-3(a), fitting unit Q and making M1 and M2 on it are
heated steps after its rig qualification, so the on-board S0-1 and S0-2 of D-3(b) are repeated after them.

| ID | Gate | GO | NO-GO action |
|---|---|---|---|
| D-1 | incident.md (d) damage checks on D-BT-SQ, D-BC-RG, D-MT-EN and the FC channel | All pass | Repair first |
| D-2 | Ag105 module standoff and cut-gap feasibility | Standoff at least 1 mm stub + 1 mm gap + the solder-joint height (record the value); after M1/M2, gap insulation at least 10 MOhm at 50 V (TODO(calibrate)) | Module carrier (revision 2 section 7.1 step 3) |
| B2 | Position of the 10 kOhm bodge pull-down on D-BT-SQ, D-BT-EN and D-BC-RG; every cut and fitting point checked against the Ag105 body outline | Located; cut points chosen on the Teensy side; no point inside the outline except M1, M2, M9, M10 | Re-fit the pull-down on the EN-pad side |
| BG-17a, BG-17b (R8) | BG-17a (before any rework): OUT reachable, its drive level at OVP, the CD delay, the open-wire fail-safe and the OUT state with VDD absent. BG-17b (after M8, M16 and LB are fitted): the items that need D_VC1, RB1A 4.7 kOhm, the fly-wire on LB and pin 9. Item list: BQ29200 OUT reachable on the SON pin 8; its drive level at OVP; the CD delay at 25 C and at the hot-soak temperature (fitted CBLD 0.33 uF is 3.3 x the 0.1 uF recommended maximum, SLUSA52C 7.3); the open-wire fail-safe; the OUT state with VDD absent (balance plug out, TODO(verify: SLUSA52C)); with D_VC1 and RB1A 4.7 kOhm fitted, the cell-1 OVP trip voltage (VC1-GND rising) at 25 C and at the hot-soak temperature, and OUT with pin 9 HIGH and with pin 9 LOW; BG-17b is repeated after any row F34b or F47 event or injection | Reachable; Q_OV switches with a cell simulator at 8.70 V; with the fly-wire intact and the cells below VPROTECT the Q_OV V_GS is at most 50 mV; with the fly-wire lifted, FF1.Q fails to set (self-test step 4 fails); CD delay recorded (if above 4 s, replace CBLD by 0.1 uF: 0.6-1.2 s); cell-1 trip at most 4.35 V + 10 mV + 0.4 mV/C x (T - 25 C) + 10.4 mV (the D_VC1 budget; re-set by ruling OR-AC); OUT asserts with pin 9 in either state | No charging (M8 is mandatory) |
| B13 | Teensy VUSB-VIN pad state | Recorded; it decides whether the section 9.10 "5V lost" row (a USB-powered Teensy with the 5V rail lost) can occur on the vehicle (CC-B10) | - |
| P8 (R7) | Pin-8 net (ENC_B) after the 2026-08-16 encoder reroute. With the Teensy unpowered and U_MS not fitted: resistance from the pin-8 pad and from J1 19/20 to 3V3, 5V and GND; continuity from J1 19/20 to the Teensy pin-8 pad, to J2 23/24 (pins 14/15) and to both sides of the 74HC14. Then with the board powered and U_MS not fitted: the DC level of the net, and the net recorded while the wheel turns through at least two slot transitions in each direction | Pin-8 pad continuous with J1 19/20; resistance to 3V3 equal to RENC2 (4.7 kOhm as designed, or 2.2 kOhm if the 2026-08-16 bodge reached it) or open; no path to 5V below 1 MOhm; no continuity to the encoder chain; DC level at most 3.3 V; no transitions | Check pin 2 the same way (it shares the RENC1 history); if both fail, remove RENC2 and cut the pin-8 net at J1 19/20 as a recorded bodge, or move MOD_COLD_N to a sixth ladder bit after a ladder re-derivation (operator choice) |
| JBL | J-BL position-3 clamp screw removable without damage | Removed; entry filled | Epoxy over an empty cage with the screw tightened |
| P-M1 | After M1 and F_VX: 4-wire resistance from the VBATN_X lead end (SB side of F_VX) to the VIN- pad (46.0, 46.70), and from VBATN_M (module side of F_VX) to the VIN- pad; VLOAD-1 (pin 16) to VBATN_M | The VBATN_M values equal the S0-1 R_s (or the D-3 value) within the S0-1 tolerance; the lead-end value exceeds it by R_FVX (recorded; it re-baselines R_chain,min, section 9.3 step 5, and the section 12.6 boundaries); a value near 0 means a bridge to GND | Redo the cut |
| D-3 | Vehicle Ag105 qualification (incident.md (d): "Do not reuse it without testing"). Any later gate that drives a reverse sense current above 3.5 A, or a reverse I2t above 0.1445 A2s, through unit Q voids D-3(a) and requires D-3(b) (revision 8, BT5-BO-04). D-3 runs after the last heated modification (M1, M2, M13, M16); a heated step after D-3 repeats D-3(b) (section 5.7 item 6). Rule C2 and the pre-energisation earth check of section 14.1 apply to D-3(b). Either (a) fit unit Q, a new module that is not the stress unit X and has run only S0-1, S0-2, S0-4, S0-6 (lab-supply source) and S0-8b on the rig, inside the rated envelope, and has never run S0-3, S0-5, S0-6 with a capacitor-bank source, S0-9 or S0-10; record its serial or date code and its gate history in the bodge record (same order and date code as unit X where marked, TODO(verify: Silvertel lot traceability)); or (b) after M1/M2, with no pack connected, run S0-1 on the vehicle module and S0-2 with a pack simulator through the external shunt in the VBATN_X lead, plus a thermal and efficiency check at 1.75 A | (a) all three passed on the fitted unit; its gate log shows no stress gate and no recorded module output current above 2.5 A; (b) R_s recorded and compared with the unit-Q reference (taken before any stress gate); reg 0x06 agrees with the shunt within max(0.05 A, 10 %) in every reachable sub-state with LD tied; efficiency and case temperature within 10 % of the reference | Replace the module |

### 15.3 Stage 1 assembly and commissioning gates

| ID | Gate | GO | NO-GO action |
|---|---|---|---|
| C-1 | Full harness audit, pack absent, every accessory, instrument and USB host connected: PACK- to GND with both S_GND gates held low; polarity check with a 0.1 A current-limited supply in place of the pack at the SB connector (VBT and GND at J-BT, no short); continuity of the M6 adjacent taps; keying of the pack connector, the 7-way cable and the KS pair; before the balance plug is ever connected, D_VC1 in diode mode (forward from GND to VC1, reverse open), RB1A by resistance from the J-BL pin-2 barrel to BQ29200 pin 3, and VC1_CB to GND in both DMM polarities; insulation of VBATN_X against pack positive at 50 V or more with the harness flexed; insulation of every lead in the CB-LB and J-BL/M16 signal sleeves against VBT and the VCHG-IN lead at 50 V or more with LB unplugged and the harness flexed (rows F54b, F54c); (revision 12) every lead-to-lead pair inside the CB-LB sleeve, and the SHDN_EF lead against the CB-LB bundle, at 50 V or more with LB and CB both unplugged and the harness flexed (rows F55, F66); VC1 to GND by resistance in both DMM polarities (row F47: a cracked CBL2 or a bridged R_VC1a reads ohms to kilohms, D_VC1 reverse leakage megohms); F_VX continuity | Open in the charge direction; no other pack-direct path (F12); polarity correct; no tap bridge; D_VC1 oriented (forward 0.1-0.4 V, reverse open); RB1A 4.47-4.94 kOhm; no VC1_CB-to-GND reading below 100 Ohm in both polarities (no pin-3 bridge); VBATN_X, sleeved-lead and lead-to-lead insulation at least 10 MOhm; VC1 to GND above 1 MOhm in the D_VC1 reverse polarity | Find and remove the path; refit a reversed clamp |
| C-1b | Before every charge session, with the USB host and every instrument connected: resistance from earth to pack(-) | Open | Remove the path (F12b) |
| C-1c | Pack installed, charger unpowered, switches forced to the charge mode in State 98 with pin 32 LOW: resistance from PACK- to GND and from pack(-) to GND, with the J-NTC, J-BL and every pack accessory connected | Open in the charge direction (no pack-internal bond, F12/F12b) | Find and remove the path (pack NTC return, accessory) |
| C-2a (R7) | Mode toggles and checks with the charger unpowered (bench supply as the pack), before commissioning: the 28 sub-items of Table 19, each with its own GO. Every reference to gate C-2 elsewhere in this document means C-2a, except the injected-bypass and fed-exit items, which are C-2b | Every Table 19 item passes; record-only items recorded | Fix and repeat the failed item |
| C-1d (CC-10) | After M9-M11, pack absent: LDIS pad to the Vin- pad; MPPTSEL pad to GND in both PROFILE states, flying lead included (C-2 measures CSEL only); R_KA: the VCHG barrel to the VBT trace, and each R_KA lead to its neighbouring nodes (row F18) | LDIS continuous to Vin- (limit TODO(calibrate)); MPPTSEL open with PROFILE L and 41.7 kOhm within 2 % with PROFILE H (the C-2 CSEL criterion); R_KA equal to its fitted value within the part tolerance, and no bridge to an adjacent node | Redo the joint |
| B-FPK | Pull F_PK at its pack-terminal position with the Teensy powered (USB) and the balance plug connected; record every board node that stays powered | VC1 - GND and VC1_CB - GND at or above the cell 1 voltage minus 0.5 V (never below -0.3 V); VBAL+ through RB1B is the only remaining source; BQ29200 OUT threshold (BG-17) unchanged afterwards | Stop: the fuse position is wrong |
| B-PKN (R8) | On the vehicle board run (a) and (b) with RB1A.2 lifted (VC1_CB open) until TODO(verify: TI) gives a VC1_CB negative-injection rating (SLUSA52C 7.1 gives none; revision 8, BT5-DS-02); refit RB1A afterwards and repeat the C-1 RB1A check. (a) With USB and the balance plug connected, open pack negative at the SB connector, then at the R_SH pack-end joint. (b) With the board on the pack (no USB), both boosts enabled and a 1-3 A bus load, then with the pack replaced by a current-limited two-cell supply and a 5 A board load, open pack negative the same two ways. (c) With LB unplugged at the KS connector and a current-limited two-cell supply as the pack, lift R_SH at its load-end terminal (a simulated element open, row F34c). Run (a) and (b) at 25 C and at the coldest operating ambient. Record VC1 - GND, VC1_CB - GND, the D_VC1 and RB1A currents, the balance midpoint wire current and temperature, the time until BT_REG EN falls below 0.4 V, the Teensy 3V3 rail, and in (c) KS+ - GND at the KS connector with a differential probe | VC1 - GND at or above -0.3 V in every case (D_VC1 V_F at most 0.25 V at 16.2 mA, at both temperatures); balance midpoint current at most 17 mA; VC1_CB current recorded (expected at most 0.83 mA); KS+ recorded (expected down to about -8.4 V; the INA240s are not connected); BG-17b repeated afterwards; on the vehicle board VC1_CB is open (RB1A.2 lifted) until the TI rating exists | Select a lower-V_F clamp under ruling OR-AC; no charging until it passes. With the provisional part of OR-AC option (d), run (a) and (b) at 25 C only (VC1 - GND at or above -0.3 V); the coldest-ambient run waits for the final part (revision 12) |
| C-2b (CC-9, R7) | After commissioning (section 9.2 step 11) and before W1, from a bench supply on J-FC at 12.0 V with a 2.0 A limit (section 9.2; V_fc on pin 24 reads 12.0 V +/- 0.2 V before the first session), with pin 32 LOW as in the configuration check (module output only through R_KA): (a) the CB eFuse IN-OUT jumpered, then SHDN_EF tied HIGH, and the configuration check and probe of section 9.7a run, once of them on a BENCH_TEST 0 build; (b) in bonded Idle with R_KA fitted and V_batt at 8.5 V (bench supply as the pack), V_chg read for 60 s with both feeds LOW; (c) pin 8 LOW within 3 ms of the feed drop at the exit of each of 10 configuration checks, drain time recorded; (d) MD_G lifted at CB: `ERR_MOD_DRAIN` at the first exit; (e) V_chg with both feeds LOW after a check; (f) Q_MD jumpered drain-source, then a dump check (section 9.7b); (g) the exit hold check on the healthy board in a dump check, in a complete configuration check with its probe, and at the exit of an FC window with pin 32 HIGH and the module charging, then with MS shorted to SHDN_EF at LB (injected), and the U_MS open-drain fall time on a 1 V overdrive step; (h) (revision 12, row F66) MD_G shorted to SHDN_EF at LB (injected), then one dump check with J-FC at 12.0 V and a 0.5 A limit, ended by the operator within 1 s: the joined node in both EF_EN states, the eFuse output, the Q_MD gate and drain current, the Q_MD case temperature and the resulting latch recorded | (a) `ERR_EFUSE_BYPASS` latches in both injected cases (or `OC_FC` first on the BENCH_TEST 0 build, recorded); with the jumper removed and SHDN_EF free the probe passes and the positive control reads pin 8 HIGH; (b) the unfed V_chg stays below 11 V less the pin-38 error (whether it stays below 8 V, which row F55 credits, is recorded); (c) every drain below 3 ms and no `ERR_MOD_DRAIN`; (d) latch; (e) decay to 11 V within the 1.0 s blanking; (f) `ERR_MOD_DUMP_ON`, or `ERR_CHG_TRIP` with the U_IM attribution recorded (row F50), with R_MD energy below 1 J; (g) no latch on the healthy board (the probe passes), `ERR_MOD_SENSE` (c) with the injected short, fall time below 50 us; (h) node 1.55-1.68 V; a latch (`ERR_MOD_SENSE` (b), `ERR_MOD_DUMP_ON`, `ERR_CHG_TRIP` or `ERR_FC_ONLY_COLLAPSE`), or, with no latch, the Q_MD current at the fed node recorded against the Table 7 selection (input to row F66) | Re-trim U_MS; fix and repeat; no Stage 2 until (a) passes; raise the `ERR_VCHG_FED` threshold only with a re-derived window floor |
| B10 | Clamp strength: Q_X1, Q_X2, Q_RG1, Q_RG2, Q_RB1, Q_RB2 hold their EN below 0.6 V against 3.3 V / 4.7 kOhm | Pass | Smaller series resistor or a stronger FET |
| B11 | Hang test: stop the pump in charge mode | FF1 clear within 43-76 ms (90 ms limit); no re-arm | Re-size the pump |
| B11b | Forced RTWDOG timeout from a Stage-1 window | Reset; pin 33 high-Z clears FF1 at once; bonded within 0.3 ms | Fix the watchdog configuration; no charging without it (ruling OR-K) |
| B11c | Warm reset (program button and RTWDOG) from Idle with the pump running, and from a Stage-1 window, 20 times each | FF1.Q stays or goes L within 1 us of reset; both SG lines H with no gap; N1 below 0.8 V | Fix the U_P33 network |
| B11d | Slow 3V3 collapse (3.3 V to 0 V in 10 ms) inside an FC window from a bench supply | eFuse output off before both SG lines go H | Fit a 3V3 supervisor (output valid to about 0.7 V) that pulls SHDN_EF and N1 LOW below 2.9 V (row F45) |
| B11e | LB 3V3 tap opened with the Teensy running: in bonded Idle, and inside a Stage-2 regen window from a bench supply on the taps | eFuse stays off; `ERR_CHG_LADDER` within 3 iterations; pins 30 and 32 LOW within 3 iterations | Bias the D-BC-RG clamp gates from a supply that survives an LB rail loss (row F51) |
| ST | Self-test of section 9.3, with each injection FET, R_T resistor, R_F resistor and R_D5c removed in turn | Each removal detected | Fix |
| T1 | U_C1 and U_C2 with real current from a load bank in the charge mode, with ramps of 1 A/ms and 10 A/ms | Trips within 2.52-3.50 A and 2.65-3.64 A; trip-to-eFuse-off delay recorded | Re-trim the thresholds |
| T2 | D5 with an injected BT-CURR level inside an FC window | Trips within 0.31-0.59 A after the 2.8-6.1 ms arming | Re-trim |
| C-3 (R12) | eFuse turn-on in an FC window from J-FC at 12.0 V with a 2.0 A limit (section 9.2), at the largest fitted C_mod and with an aux load of 0.15 A (revision 12, BT8-TR-01) | FC_CURRENT peak below 1.3 A (`OC_FC` 1.4 A less the 0.10 A INA253A1 zero error); G1 blanking duration recorded | Raise C_DV as the S0-11 NO-GO action states |
| W0 | After S0-1, at the FC profile (1.25 A) and the regen profile current (1.75 A): VC1 - GND against the true bottom cell at the pack tap at CV entry | Reading plus the measured imbalance below 4.30 V | Lower the profile current, or rule OR-E as charge inhibit for a BQ trip |
| W1 (R12) | First FC windows from a bench supply on J-FC at 12.0 V with a 2.0 A limit (section 9.2), standstill, two 30 s windows separated by `FC_CHG_COOLDOWN_MS` (the 30 s `FC_CHG_MAX_MS` cap ends each window, ino:2633-2634; revision 12, BT8-REQ-03; revision 11 asked for one 60 s window), FC profile, the request raised with the State-98 window-request key of section 12.8 (or a parked flagged request from a Pi that runs the OR-RQ form); loop iteration-time histogram recorded on the production build (USE_ETHERNET 1, the Ag105 poll and the SD drain as flown; revision 11); in-window minimum V_chg, both MDAC codes and reg 0x06 against I_set recorded | V_fc reads 12.0 V +/- 0.2 V before the first window; I_PACK1 within 10 % of reg 0x06; pack current 1.25 A +/- 10 %; pin 8 HIGH in the window and LOW within 3 ms of the exit feed drop; no fault; (revision 11) MDAC codes equal to the fixed split from entry step 5 to the exit; in-window V_chg at or above the measured S0-4 threshold + 0.3 V and at or above 14.0 V; maximum iteration at or below 15 ms (19.0 ms bound of the PI-4 late rule, calc11 section 3) | Stop; analyse with S0-2 data. On the iteration criterion: raise T_lead,min and T_late by the excess of the measured maximum over 19.0 ms (a requirement change on the predictor, ruling OR-P). On the V_chg criterion: measure the droop block (open item 41) before W2 |
| B8-1 (R12) | Stage 1 part of B8 (revision 12, BT8-REQ-02), after W1: I_L (LM1084 input current plus the BT-boost input current) in the charge mode at the FC profile with BT_BUS open (FC window), at V_batt 7.4 V and at the highest V_batt that the entry gate admits (below 8.0 V until S0-8b; 8.4 V once S0-8b has passed), from J-FC at 12.0 V with a 2.0 A limit (section 9.2) or from the H-20; I_L,cal and eta_cal for G1 at the FC profile and the boost efficiency at J-FC 12.0 V; the Ag105 case temperature at the worst in-vehicle airflow (section 7.1); the board temperature at M16 (thermocouple on the CBL2 pads) during the longest FC-window sequence (two consecutive 30 s windows) at the hottest ambient, which is T_M16,max for the D_VC1 selection and ruling OR-AC; run with the D_VC1 part that OR-AC names for the first build fitted | I_set + I_L at or below 2.5 A (I_L at most 1.25 A); I_L,cal and eta_cal stored; T_M16,max recorded; then the fitted D_VC1 re-verified against T_M16,max or replaced under OR-AC, and the C-1 D_VC1 items, BG-17b and B-PKN repeated | Lower I_set or tighten the I_L hold condition; D_VC1 under OR-AC |
| W2a (R9) | Before W2, on the vehicle with the H-20 or a bench supply on J-FC (12.0 V, 2.0 A limit, section 9.2), the FC carrying the auxiliary load only: BT_BUS dropped and re-closed onto the live bus 20 times, and FC_BUS likewise; V_bus and BT_CURRENT (FC_CURRENT) against the EN edge | Conduction onset (t_D_ON plus the soft-start) at or below 31.8 ms in every repetition; maximum recorded | Raise T_lead,min, T_late, T_lead,nom and the traction-release bound by the excess (a requirement change on the predictor, ruling OR-P); re-derive `SHARE_CUT_SURVIVOR_BLANK_MS` (open item 32) |
| W2e (R11) | Before the first vehicle FC window: the deployed (unmodified) Pi node and bridge drive a recorded UDDS stop and a Run exit, then the updated Pi node does the same with an FC-charge decision forced at the stop and a parked request in State 1 | Deployed node: FC_CHARGE never HIGH, refusal code 15 reported whenever `charge_goal` is above `CHG_GOAL_MIN`; updated node: a window opens at the stop and parked, and no window opens on the regen gate alone | Keep FC windows refused on the vehicle until the Pi round of OR-RQ passes |
| W2 (R9) | FC windows from the H-20 between predicted purges, parked (variant P), for at least 30 min (about 170 purges), the predictor in service, the Ag105 profile and R_KA as ruled | No UV_BUS, no `ERR_FC_ONLY_COLLAPSE`, no `PURGE_LEAD_SHORT`; at every onset the window closed, the pack bonded and BT_BUS HIGH for at least 31.8 ms (log); V_bus at or above 13.5 V across every purge; charge-current time per period recorded against Table 22 (94.5-95.6 %) and the Ag105 start time per window recorded | Keep FC windows on the bench supply; analyse the chain timing and the Ag105 start against S0-6 |
| W2c (R9) | Unpredicted collapse, from a bench supply on J-FC at 12.0 V with a 2.0 A limit (section 9.2) inside a charging window (predictor permit asserted): the supply output switched off and back on after 80 ms and after 140 ms, at a step fall and at a ramp of 20 ms; then each reading of `ERR_FC_ONLY_COLLAPSE` alone (pin 38 held, then pin 26 held). Revision 10 sub-steps: (i) the predictor stub raises `purge_active`, then UNKNOWN, then a prediction at `purge_tto` 50 ms, each 0-70 ms after the supply step; (ii) with EN_BE_X grounded (BT_BUS cannot conduct, row F63), a predicted purge from the bench supply with a 60 ms fall; (iii) the State-99 board drain from the pack measured with an ammeter in the pack lead for 10 min. With the operator's approval, one window on the H-20 with the prediction suppressed | `ERR_FC_ONLY_COLLAPSE` latches; FC_BUS LOW before the source returns; no BT_BUS HIGH write after the latch or after a step-(i) event; in (ii) State 99 with FC_BUS LOW before the supply returns; the Table 23 end state; after a power cycle the boot self-test, a dump check, C-2b items (c) and (g) and W1 pass, and both boosts regulate in the bring-up; the TPS61288 restart after its VIN UVLO captured (open item 33); the (iii) drain recorded against the 0.2-0.25 A estimate | Stop; revise the teardown and repeat |
| W2b (R9, R10) | As W2 in State 2 at standstill (variant D-s, `IC1_FC_RUN_STANDSTILL` 1) inside drive sessions; EMS share commands of 0.15 and 0.16 at standstill with the request standing; `v_setpoint` steps issued inside windows at random phase | As W2; no `OC_FC`; the MDAC codes and V_bus recorded at the onset, with V_bus above `LIMIT_V_BUS_MIN` (no requirement on the ratio; revision 11, FM7-3: the codes change at the exit by the restore of section 9.7 exit step 4, and no MDAC write from the share loop occurs in the SC-8 interval); no pin-27 or pin-28 write from the share latch or the selector in the SC-8 interval; the standstill auxiliary load recorded with its share-loop regime (below or above 0.075 A); the W1 V_chg and iteration criteria on every window; one sub-step that starts from a boot with the first flagged request issued in Run: the dump check runs at the first stop and the window opens at that stop (revision 11); traction released after BT_BUS has conducted, at most 61.7 ms after the command (47.0 ms worst healthy, calc10 section 8); peak FC_CURRENT between the BT_BUS write and the conduction below 1.25 A on every launch; I_still and T_still set from the measured standstill dither | Keep `IC1_FC_RUN_STANDSTILL` 0 |
| W2d (R9) | False-latch count over every W1, W2 and W2b session, and over the drive sessions of C-4 | No `ERR_FC_ONLY_COLLAPSE` without a source loss; the minimum V_bus of every two-source purge and of every State-2 launch inside the reading-(b) purge interval recorded (basis for the deferred 13.5 V option of section 9.11.3) | Re-derive the 13.0 V and 12.0 V thresholds of `ERR_FC_ONLY_COLLAPSE` from the measured window dips |
| C-4 | After the first driving session: repeat P-M1, the D-2 gap insulation, the VBATN_X, sleeved-lead and lead-to-lead insulation tests (revision 12) and C-2b items (a), (c) and (g); inspect every flying-lead joint and stake, D_VC1 and the RB1A replacement (section 5.7) | Unchanged from the build values; no cracked joint; the C-2b items pass | Repair and repeat after the next session |

Table 19 lists the sub-items of gate C-2a (revision 7, BT4-2 and CC-B9). They need no fed charger: the module stays
unpowered and no window opens. The fed-exit items of revision 6 (pin 8 LOW within 3 ms of a feed drop, `ERR_MOD_DRAIN`
with the Q_MD gate lifted, V_chg after a window) moved to C-2b.

Table 19. Gate C-2a sub-items.

| No. | Sub-item | GO |
|---|---|---|
| 1 | Loaded S_GND gate at a 7.4 V pack | At least 4.5 V |
| 2 | S_GND gate band against the Q_D and Q_R thresholds (row F42) | Record-only (limit TODO(calibrate) from S0-1 and the F10 analysis) |
| 3 | Ladder calibration (32 codes each) and step response | 64 codes stored; largest step within 30 mV in less than 0.2 ms |
| 4 | V_PACKN two-point calibration (section 7.9) | Offset and gain stored |
| 5 (R8) | Two-point calibration of the VC1 tap (pin 20) against a DMM on the RB3 VC1 pad, and of V_BT (pin 25) against the same DMM at J-BT pin 1. Then a two-output cell simulator: top output to J-BL position 1 (VBAL+) and to the pack supply on J-BT; midpoint to J-BL position 2 (VMID); common to PACK- (J-BL position 3 is removed, M12). Pack at 7.4 V (0.6 V below the SLUSA52C 7.1 VC2-VC1 maximum of 8 V). Apply a 40 mV and a 120 mV mismatch. Then pull the R_VC1a/R_VC1b junction on LB to GND (the D_VC1-short equivalent; do not jumper D_VC1, which at 8.0 V or more puts the pack voltage across VC2-VC1, row F47). Repeat the calibration readings at the B8 hot soak and at the coldest operating ambient | Constants stored; no `ERR_CELL_MISMATCH` at 40 mV; latch within 1.5 s at 120 mV and with the tap junction grounded; the hot and cold readings recorded (they set the threshold) |
| 6 | `ERR_SGND_OPEN` forced at 1, 3 and 7 A with both S_GND off | Latch within one iteration at each current |
| 7 | R_ret baseline at 5 A or more; R_chain,min and R_chain,max | Record-only (stored) |
| 8 | Lead B 4-wire from its far end to the J-BT pin-2 pad; SB ground offset at a 10 A load | At most 1.0 mOhm; at most 30 mV |
| 9 | Derived BT_BUS against the EN pads | Matches in every p28/p31 state |
| 10 | eFuse state with 3V3 removed, with the SHDN wire open and with the SB cable open | eFuse off in each case |
| 11 | Each gate tap removed in turn, then both | The other channel holds; both removed: `ERR_SGND_OPEN` within one iteration |
| 12 | Kelvin-lead open behaviour, each lead in turn | Record-only (amplifier outputs recorded) |
| 13 | A current-limited pack+ (0.1 A) injected onto each KS lead and onto the SB side of each R_K | The current bound is confirmed; INA240 offsets unchanged afterwards |
| 14 | KS+ shorted to KS- at the LB connector, traction at 1, 3 and 7 A; a 0.5 x gain injected on both channels in traction above 1 A | `ERR_IPACK_PLAUS` within 100 ms and windows refused; the gain-band form latches within 1.1 s |
| 15 | CSEL to Vin- resistance in both PROFILE states, flying lead included | Within 2 % |
| 16 | S_CHG/S_GND exit overlap | Record-only (limit TODO(calibrate) from the F10 analysis) |
| 17 | N1 and CLK edges on the pin-33 edge; the clear-net capacitance C_N1 | 1000 consecutive sets without a failure; C_N1 at most 668 pF |
| 18 | BAL_OK with the balance plug in and out | H and L |
| 19 | D5_N with pin 33 LOW | At or above 3.2 V |
| 20 (R8) | Both return leads lifted, a current-limited 7.4 V supply as the pack, board load 1 and 3 A (at most 3.5 A, the S0-9 envelope: the reverse sense current through unit Q equals the board load; at 3 A the worst I2t is 0.133 A2s against the S0-10 0.1445 A2s, calc8 section 7) | `ERR_PACKN_RANGE` or `ERR_SGND_OPEN` latches; -V_PACKN and the S_CHG state recorded |
| 21 | EF_FLT_N and IN_SYS scoped while the eFuse input decays with SHDN low | Record-only (FLT behaviour on UVLO with SHDN low, TODO(verify: SLVSE94G)) |
| 22 | An injected V_chg of 16 V with both feeds LOW | `ERR_VCHG_FED` latches |
| 23 | U_MS output lifted in the bonded mode (pin 8 HIGH on the pull-up) | `ERR_MOD_SENSE` (a) latches |
| 24 | U_MS threshold: MD_G lifted at CB (R_MDG holds Q_MD off), a supply on VCHG-IN_M ramped from 0 to 9.5 V with a 50 mA current limit (see the section 9.2 warning) | Pin 8 rises at 8.67-9.17 V and returns LOW below it; MD_G restored and its continuity confirmed |
| 25 | Pin 39 two-point calibration (M-R2) and the k_idle value (Stage 2) | Stored |
| 26 | D_NC1 lifted, U_C1 injected (CC-B14) | Both SG lines go H while FF1.Q stays H; D_NC1 refitted and the self-test passes |
| 27 | MD_G shorted to GND at CB with EF_EN L | U_MDI output current at most 4 mA; Q_MD off |
| 28 (R8) | I_NB,cal: the VBT load without the BT-boost input (I_PACK1 minus the BT-boost input current), in bonded Idle with the boosts at no load, at V_batt 7.4 and 8.4 V | Stored (input to the `ERR_IPACK_PLAUS` gain band) |

### 15.4 Stage 2 gates

| ID | Gate | GO | NO-GO action |
|---|---|---|---|
| V2-0 | t_D_ON of D-BC-RG: EN released to VOUT at 12.4 V, at VIN 17-21 V, 20 repetitions | Recorded (feeds S0-6) | - |
| V2-1 | VOK channels with two ramped supplies on the taps; each VBUS tap lifted in turn; R_Bk2 shorted; both VBUS taps lifted together; the post-brake V-MOT tail (21.35 V decaying at 14 and 20 V/s); pulses that peak inside the per-board band between the two channels' assert levels, decaying at 8 and 14 V/s and holding a 2 s plateau; the pin-39/pin-26 ratio noise over 50 ms; on the vehicle, a Y-profile step-down from -2 to -6 A to 0 with V-MOT captured between 17.2 V and 16.2 V | Assert and release within Table 9 at 13.5, 16.0 and 17.5 V; NOT OK at 0/0; bus-present level within 9.3-9.8 V; every tap-open and short case reads "channel blocks"; no `ERR_VOK_STUCK` on any in-band, tail or plateau case; a channel forced OK at bus level latches within 52 ms; 50 ms ratio error at most 0.002 | Re-trim; fix the guard; re-derive r_TH |
| V2-2 | Release race: scope V-MOT, VBUS, eFuse OUT and EN_RG_X during a commanded release at board-only capacitance, during a V-MOT fall of 1-3 V/ms, and during a VESC-draw-driven fall (traction onset) | eFuse off before V-MOT reaches VBUS for the charger-only fall; bus feed at most 12 us for the VESC-draw fall | Add a delay-free clamp or a larger margin |
| V2-3 | S0-R3 / T-E-03: does the VESC keep braking with V-MOT held near 18 V | Recorded | HR1 capture limited by the VESC stop |
| V2-4 | Regen windows on the stand at 2-3 m/s decels, per pulse family, and a representative drive session; loop iteration-time histogram recorded; the eFuse start into the dumped node at the vehicle C_VMOT (node voltage at each VOK release) | No fault (no `ERR_VOK_STUCK` on brake ends); ladder consistent; arm-to-pin-30 latency at most 10 ms and the latency from the first command below -0.1 A recorded; the fraction of decels that open a window recorded; captured charge per event (reg 0x06 integrated and I_PACK1) at or above a stated fraction of that event's node energy above 18 V (fraction set by ruling OR-B). A firmware stop is not evidence of capture | Disable Stage 2 |
| V2-5 | Traction request inside a window | Traction delay at most about 7 ms at the p99 loop (the module drain included, C_mod at most 221 uF); no U_C1 trip | Fix the mode manager |
| V2-6 | Configuration check and eFuse-blocking probe from the H-20 between predicted purges (the purge permit of section 9.11.2 in service, gate W2 passed); the C-2 injected-bypass gate has passed on this board | No UV_BUS; readback valid; pin 8 HIGH in the check (positive control) and LOW in the probe | Configuration checks from a bench supply only (J-FC at 12.0 V, 2.0 A limit, section 9.2) |
| B8-2 (R12) | Stage 2 part of B8 (revision 12, BT8-REQ-02): I_L in the charge mode at the regen profile with BT_BUS closed (regen window), at V_batt 7.4 V and at the highest admitted V_batt; I_L,cal and eta_cal for G1 at the regen profile; the board temperature at M16 in Run and in regen windows (re-check of T_M16,max) | I_set + I_L at or below 2.5 A; I_L at most 0.75 A (the HR1 hold condition) | Lower I_set; record HR1 against the measured I_L |

## 16. Parts list and cost

Table 18 summarises the parts by assembly. Prices are rough budget estimates and UNCONFIRMED. The battle-test round 2
availability read (DigiKey and TI.com, 2026-11-07; the verifier could not re-read them, so every figure is UNCONFIRMED
and must be re-checked at order) gave the following:

- TPS26631PWPR: 0 in stock, 505 expected 2026-12-03 and 1,495 on 2027-01-25, standard lead 26 weeks; TI.com out of
  stock. The approved alternate is **TPS26636PWPR** (1,218 in stock): same PWP-20 pinout except pin 8 (PLIM instead of
  OVP; tied to GND, the "PLIM not used" connection of SLVSE94G Table 5-1); 1 x I_OL current limiting with MODE open,
  latch-off after tCL_PLIM 129-202 ms and no 2 x tCB phase (Table 8-1); fast-trip multiple not stated
  (TODO(verify: SLVSE94G)); a fixed overvoltage clamp at 35.7-39 V (section 6.5) in place of the TPS26631 cutoff at
  33.2-35.4 V. The clamp tops out above the Ag105 36 V absolute maximum (DS p.19); this is acceptable only because the
  eFuse input is at most 21.5 V and the RT1987 OVP sits upstream. S0-12 and S0-12b run on the part actually fitted.
- INA240A3PWR: 0 in stock, 2,000 expected 2026-11-27, lead 26 weeks. INA240A3D (SOIC-8, 4,008 in stock) or
  INA240A3EDRQ1 (3,022) are specified instead; LB has no layout yet, so the package change costs nothing.
- CSD18510Q5B: out of stock at TI.com; order CSD18510Q5BT (250-reel, 936 at DigiKey).
- TLV3011BIDBVR: 974 in stock.
- Battle-test round 4 (2026-11-07): TI.com showed TPS26631PWPR and TPS26631PWPT out of stock, and cached DigiKey pages
  in the search results disagreed (140-3292 in stock). Stock is UNCONFIRMED; confirm it live at DigiKey or Mouser, with
  the date recorded, before any order.

The board fabrication and assembly turn times are TODO(verify: board house).

Table 18. Parts and cost estimate (USD).

| Assembly | Main parts | Estimate |
|---|---|---|
| SB | 3 x CSD18510Q5BT (+1 spare), R_SH, 2 x fusible R_K, 6 x BSS138, BSS84, 3 x BZT52C15, 4 x BAT54, 2 x F_T, 4 x 2.2 uF, passives, 2-layer board, enclosure and cable clamps | 35-60 |
| LB | SN74LVC1G74, AHCT1G125, 5 x LVC1G17, 2 x LVC1G07, 2 x LVC1G14, 2 x LVC1G02, 2 x LVC1G08, LVC1G32, LVC1G11, 2 x LVC244A, LVC1G04, 2 x INA240A3, 9 x TLV3011B, 15 x BSS138, 13 x BAT54, about 36 x 0.1 % resistors (R_VC1b included), R_MDS, C_VC1, passives, 2-layer board, standoffs | 60-95 |
| CB | TPS26631PWPR (or TPS26636PWPR), 2 x BSS138, Q_MD, R_MD (pulse-rated), R_MB, F_VX 4 A and holder, 0.1 % resistors, passives, small board | 12-25 |
| Balance network (M16) | 1 x low-leakage small-signal Schottky (D_VC1), 4.7 kOhm 0402 (RB1A), 200 kOhm 0.1 % (R_VC1a) | 1-2 |
| Harness | 20 A fuse and holder at the pack terminal, keyed 30 A pack connector, keyed 7-way and KS connectors, 2.5 mm2 and 0.5 mm2 stranded wire, twisted pair, adhesive for staking | 20-30 |
| Stage 0 rig | 2 x Ag105 (unit X stress spare and unit Q qualification unit; a third if OR-J selects S0-10), external shunt, carrier, RT1987, electronic load, programmable pack simulator access, capacitor bank | 60-100 plus two or three module prices TODO(verify: distributor) |
| Stage 3 | Withdrawn in revision 7 (section 14.4) | - |

Stage 1 costs about USD 115-210 for SB, LB without the VOK channels and the D-BC-RG clamps, CB, the clamps and the harness; Stage 2
adds about USD 10-20. The total is well below the USD 505-540 of the BQ25798 design (facts_prior section 11).

## 17. Operator rulings

**Operator rulings 2026-11-09.** The operator answered the open rulings of revision 12 on 2026-11-09 through the chat
question dialog. The answers were as follows (verbatim):

1. "OR-AC: option (d) chosen for the first build - provisional D_VC1 (candidate NSR0320MW2) at T_min 25 C,
   bench-attended Stage-1 sessions only, so C-1, BG-17b, B-PKN at 25 C and B8-1 can run; choose (a) or (c) after B8-1
   unless B8-1 shows T_M16,max below about 44 C."
2. "Row F66 double-insulation residual (Q_MD may be destroyed if both the SHDN_EF and CB-LB sleeve insulation fail and
   its V_GS(th) covers 1.55-1.68 V): ACCEPTED. Q_MD selection must still record V_GS(th), SOA and V_GSS."
3. "Sleeve segregation accepted as the only protection of SHDN_EF, MD_G, PROFILE, IMON, MS, EF_FLT_N and the VC1 tap at
   both lead ends (BT8-DS-01/02); no clamps added."
4. "Accept as proposed": every other open ruling is recorded at the answer the design proposes or recommends.

The Status column records the result. A ruling whose proposal names one answer is recorded at that answer. A ruling
whose proposal leaves the answer to a named bench gate is recorded as decided by that gate. A ruling that offers two or
more options without a recommendation, or asks a question without a proposed answer, stays open. After 2026-11-09, 30 of
the 36 rulings are decided: OR-P and OR-SC on 2026-11-08, and 28 on 2026-11-09, of which OR-I and ruling 9 are decided by
gates S0-2 and S0-6. Six remain open: OR-J (Stage 0, gate S0-10), OR-L, OR-R and OR-X (Stage 1, before the firmware
round), OR-B (Stage 2) and OR-F (Stage 3). The revision number is unchanged.

The three round-8 acceptances (OR-AC option (d), the row F66 residual and sleeve segregation) no longer block a
motherboard change, and no open ruling blocks it directly; OR-J is needed within Stage 0. The following items still
block a motherboard change: the Q_MD selection (open item 17, with
the V_GS(th) range, the linear-mode SOA and V_GSS of row F66), Stage 0 (section 14.1, with ruling 9 decided at S0-6 and
OR-J before S0-10), the board gates of section 15.2, and a further battle-test round on revision 12 with a buildability
lens.

The following rulings apply. Each names the stage that needs it; the per-stage lists of sections 14.1-14.3 are
taken from this column (Stage 0: OR-A, OR-J; Stage 1: every row marked 1; Stage 2: the Stage-1 rows plus every row
marked 2; Stage 3: OR-F).

| ID | Ruling | Stage | Status (2026-11-09) |
|---|---|---|---|
| OR-A | Adopt IC1 revision 12 as staged, with Stage 0 plus Stage 1 as the first build and its end state until the Stage-2 evidence exists; run Stage 0 before any board change | All | **Accepted as proposed 2026-11-09.** IC1 revision 12 is adopted as staged, with Stage 0 plus Stage 1 as the first build. Before a motherboard change the following still block: the Q_MD selection, Stage 0, the board gates of section 15.2, and a further battle-test round on revision 12 with a buildability lens |
| OR-B | HR1 criterion: relax 23 W to the 18.9 W peak, or record HR1 as failed (23 W is unreachable in any regen window; at most 22.73 W at the 8.0 V entry gate). Also set the V2-4 captured-charge fraction per event | 2 | **Open.** The ruling offers two options without a recommendation, and the V2-4 captured-charge fraction has no proposed value. Stage 2 only |
| OR-C | Ruling 3 restatement: the bus feeds the charger only in a commanded FC window (eFuse FCQ term, Q_X1, D5) and from V-MOT only when V-MOT exceeds VBUS by the VOK margin, except a feed of at most about 12 us per traction onset (section 7.2 item 2). The ruling-3 always-powered strategy is not used; every window starts the Ag105 cold (OR-F). CLAUDE.md still records R3 | 1, 2 | **Accepted as proposed 2026-11-09.** The CLAUDE.md R3 text changes in the firmware round; this document does not edit CLAUDE.md |
| OR-2' | A regen window ends on any traction request; torque resumes after the measured module drain and the settled exit confirmation (4.7-6.3 ms median, 5.3-6.9 ms at the p99 loop for C_mod 100-221 uF, calc6 section 9). Also decide whether the drive-law state is frozen during the 0 A hold (default: no change). An FC window also ends on any traction request (section 9.7); in State 2 (variant D-s, revision 9) the request is a non-zero `v_setpoint` or \|I_cmd\| above I_still, read before the command reaches the VESC, and (revision 10) torque resumes only after BT_BUS has been HIGH for the conduction bound (43-47 ms after the command on the healthy chain, at most 61.7 ms) | 1, 2 | **Accepted as proposed 2026-11-09.** The drive-law state is not changed during the 0 A hold (the stated default) |
| OR-4 | MPPTD released (HIGH) inside every window, with pin 5 driven open-drain and written only by the mode manager (reverses the CLAUDE.md section 3 regen strategy, which asserts MPPT_DISABLE during regen) | 1, 2 | **Accepted as proposed 2026-11-09.** |
| OR-5' | Three one-time commissioning writes (reg 0x00 = 0x00, 0x01 = 0x08, 0x02 = 0xFF) with pin 32 LOW; fw v24 dynamic reg 0x02 policy disabled; fallback to per-window writes only if S0-4 fails. The CLAUDE.md section 3 reversals that follow are listed under OR-W | 1 | **Accepted as proposed 2026-11-09.** The fallback to per-window writes applies only if S0-4 fails, as the proposal states |
| OR-7 | Concurrent regen and FC windows (ruling 7; IO CSV row-31 amendment pending): the hardware permits them; firmware keeps them exclusive, with no direct transition (FC or configuration check, exit, bonded, regen), until ruled | 2 | **Accepted as proposed 2026-11-09.** Regen and FC windows stay exclusive, with no direct transition. The IO CSV row-31 amendment is carried by OR-G |
| Ruling 9 | R_KA keep-alive fitted or not (decided with S0-6, before the Stage-1 build) | 1 | **Accepted as proposed 2026-11-09: decided by S0-6 per the proposal**, before the Stage-1 build |
| OR-D | BQ29200 OUT tap mandatory; no charging without it; the Q_OV gate is pulled up to 3V3, so an open tap refuses charging by itself | 1 | **Accepted as proposed 2026-11-09.** |
| OR-E | Per-fault response in production builds (proposed): **State 99** for the traction and isolation hazards (`ERR_SGND_OPEN`, `ERR_CHG_EXIT`, `ERR_CHG_TRIP`, `ERR_VCHG_FED` and `ERR_MOD_FED` with a feed present, `ERR_EFUSE_BYPASS`, `ERR_VOK_STUCK`, `ERR_IPACK_PLAUS`, `ERR_PACKN_RANGE`, and from revision 9 `ERR_FC_ONLY_COLLAPSE`); **window inhibit with a telemetry flag**, latched for the power cycle, for the charge-subsystem health faults (`ERR_CHG_SELFTEST`, `ERR_CHG_ENTRY`, `ERR_CHG_LADDER`, `ERR_IPACK_XCHK`, `ERR_SGND_DEGRADED`, `ERR_RET_DEGRADED`, `ERR_AG105_CFG`, `ERR_PROFILE_OC`, `ERR_MOD_SENSE`, `ERR_MOD_DRAIN`, `ERR_VCHG_SENSE`, `ERR_VMOT_CAL`, `ERR_MOD_DUMP_ON`, `ERR_CELL_MISMATCH`, `ERR_CHG_PATH_OPEN`); separately for a BQ29200 OUT trip in a window (W0). Revision 5 left every new fault at State 99, which let five health checks with TODO(calibrate) thresholds halt a drive | 1 | **Accepted as proposed 2026-11-09.** The per-fault response applies as listed. A BQ29200 OUT trip in a window enters State 99 (section 12.6 item 2); charge inhibit is reconsidered only on a W0 NO-GO |
| OR-F | Stage 3 hold-up: withdrawn in revision 7; decide whether a re-specification round (section 14.4) runs | 3 | **Open.** The ruling asks whether a re-specification round runs and proposes no answer. Stage 3 only; it blocks no work in Stages 0-2 |
| OR-G | IO CSV amendment for the ten pins and the changed meaning of rows 28, 30, 31 and 32: row 28 (effective enable p28 AND NOT p31, Q_X1); row 30 (Stage 2: EN_RG = p30 AND both VOK channels, and p30 enters the eFuse source term; Stage 1: held LOW by firmware); row 31 (also drives the eFuse source term, the Q_X1 BT_BUS clamp and the D5 arming); row 32 (D-BT-SQ disabled by the cross-lock while bonded; pin 32 LOW in commissioning and configuration checks); pin 20 open-drain. Pin 5 driven open-drain (row 5); pin 8 used as the input `CHG_MOD_COLD_N` (row 8, after gate P8); pin 20 used as the analog input `CELL1_V` (row 20, revision 7; the revision-6 WDOG1_B assignment is dropped). Bodge records M1-M16 in CLAUDE.md (M16 is the revision-7 balance-network rework: D_VC1, RB1A 4.7 kOhm, R_VC1a), including the change to CLAUDE.md section 4 (BAL-NOK is no longer unused: M8). Completeness critic CC-17: also the CLAUDE.md section 2 text that `BT_SEQUENCE_ENABLE` "does not need to be turned off again" (IC1 drives pin 32 LOW in commissioning, configuration checks, State 99 and on `ERR_CHG_LADDER`, reversing the fw State-99 rule that leaves it HIGH, facts_firmware section 2.1), and the CLAUDE.md section 4 statement that CB_EN is hardwired to GND (SCH, BRD and ino:6728-6729 show CB_EN on Teensy pin 9, facts_board section 5 item 4) | 1 | **Accepted as proposed 2026-11-09.** The IO CSV amendment, the bodge records M1-M16 and the CLAUDE.md section 2 and section 4 changes are made in the firmware round together with the firmware; this document does not edit the CSV or CLAUDE.md |
| OR-H | Telemetry protocol v6 = the operator-approved R4 v5 layout (fw v38) with the IC1 fields appended (I_PACK1, V_PACKN, hardware status word with pin 8, the charge_goal refusal flag) and the R4 `charger_flags` bits redefined under `PACK_RETURN_CHANGEOVER` (section 12.9); the Pi bridge lockstep. Alternatively, append the IC1 fields to the R4 v5 round before fw v38 lands. CLAUDE.md section 1 requires `I_charge` from reg 0x06 at 50 Hz; under IC1 it is meaningful in FC windows only and reads 0 or a single sample in regen windows | 1 | **Accepted as proposed 2026-11-09.** Telemetry protocol v6 on the R4 v5 layout; the alternative (the IC1 fields in the R4 v5 round) is not adopted. The protocol-bump procedure and the Pi bridge lockstep apply (CC-B3) |
| OR-I | If S0-2 fails: accept U_C2, U_IM and the eFuse as the sole current bounds | 1 | **Accepted as proposed 2026-11-09: decided by S0-2 per the proposal.** The bounds U_C2, U_IM and the eFuse become the sole current bounds only if S0-2 fails |
| OR-J | Sacrificial module for S0-10, or acceptance of the mis-sequence residual | 0 | **Open.** The ruling offers two options without a recommendation; section 16 counts a third module only if OR-J selects S0-10. Gate S0-10 waits for it |
| OR-K | MCU watchdog (RTWDOG, ruling 5) mandatory before the first charge; WDOG1_B is not used, because pin 20 carries the VC1 tap (revision 7) | 1 | **Accepted as proposed 2026-11-09.** |
| OR-L | Retire or redefine `AG105_VBATN_ISOLATED` | 1 | **Open.** The ruling offers retirement or redefinition without a recommendation. Until it is ruled, IC1 builds set `AG105_VBATN_ISOLATED` to 1 only together with `PACK_RETURN_CHANGEOVER` 1 (section 12.2 item 3). Needed before the Stage-1 firmware round |
| OR-M | FC profile 1.25 A against H5's 1.5 A. Code 4 (1.5 A) gives a bus current of 1.09-1.22 A against P_MAX 1.247 A at efficiency 0.88 and 1.19-1.33 A at 0.80 (exceeds P_MAX). Accept 1.25 A, or adopt code 4 subject to a bench efficiency gate | 1 | **Accepted as proposed 2026-11-09.** The FC profile stays at 1.25 A, the value on which the design is specified (Table 5, sections 9.7 and 13). Code 4 (1.5 A) remains a recorded option subject to a bench efficiency gate |
| OR-O' | (Revision 9; replaces OR-O, which limited FC windows to State 1 and 98 and ignored charge_goal in Run.) The operator ruled on 2026-11-08: "Fuel cell charging would occur between purges if requested by the EMS." Proposed implementation: FC windows parked in State 1 or 98 (variant P) and in State 2 at standstill (variant D-s: `v_setpoint` 0, \|I_cmd\| at or below I_still, \|v_actual\| below the standstill threshold, behind `IC1_FC_RUN_STANDSTILL` after gate W2b); charge_goal is the window request in each of these states (section 9.11.6); windows in motion are not adopted (OR-DM). D-s gives at most 1.9-31.9 mAh per drive cycle on the plant model with a request at every stop (Table 27). Revision 11: the recorded sessions carry 0 s of EMS FC-charge request (their `charge_goal` is the regen gate), so HR2 against EMS requests is undetermined; the request is explicit (OR-RQ); the dump check that every window needs runs in State 2 at standstill as well (section 9.7b). Revision 10: at standstill an EMS rail command is substituted in band while the request stands (section 9.11.6) | 1 | **Accepted as proposed 2026-11-09.** FC windows open parked (variant P) and in State 2 at standstill (variant D-s, after gate W2b), on an explicit request (OR-RQ) |
| OR-P | **Decided 2026-11-08.** The operator ruled: "Regarding the fuel cell purges, those would be handled in firmware by not allowing fuel cell charging during and leading up to a purge, and by shifting the share ratio back towards battery power preemptively. Fuel cell charging would occur between purges if requested by the EMS." and "The purge predictor is not within scope of this session- assume it works perfectly as far as designing the isolation circuitry goes." Consequences in this design: the purge predictor is the operator's (formerly T-E-01) and is taken as ideal; it must meet the interface PI-1 to PI-7 of section 9.11.2 (revision 10: T_lead,min 80 ms whenever an FC window can be open, T_lead,nom 290 ms only for the share shift in closed-loop State 2, the late threshold T_late 61 ms, declared end, horizon 1.282 s, fail-closed UNKNOWN that latches State 99 inside an open session); its permit replaces the fw v33b lockout for every FC-fed session; the lockout keeps refusing FC-only source selection. W2a may raise the lead times (a requirement change on the predictor) | 1 (decided) | Decided 2026-11-08 (unchanged) |
| OR-SC | **Decided 2026-11-08.** The operator ruled: "An unpredicted purge causing the bus to collapse and the system to shut down without any damage to components is acceptable. That will be on me to design the purge predictor appropriately." Consequences: no ride-through is designed; `ERR_FC_ONLY_COLLAPSE` latches State 99 with no BT_BUS re-close (policy E2, section 9.11.5), also on a late or after-the-onset recognition by the predictor (PI-4, revision 10); the no-damage argument of Table 24 is UNCONFIRMED until W2c. Recorded option, not specified: policy E3 (a ride-through with FC_BUS LOW at the trigger and a bus-recovery deadline of about 40 ms), for a later ruling | 1 (decided) | Decided 2026-11-08 (unchanged); policy E3 stays a recorded option |
| OR-DM | (Revision 9.) FC windows in motion (variant D) are not adopted: their 0.06-0.33 A traction allowance is the size of the INA253A1 zero error and of the plant-to-rig error, that allowance falls to 0.03-0.08 A of voltage headroom at a drooped split (bt7 section 5), and a purge at a pre-purge I_fc of 1.0-1.25 A is outside the 172-purge evidence (section 9.11.7). On the plant drive cycles with a request at every stop, D (pessimistic) gives 1.2-1.8x D-s. Revision 11: the revision-10 basis "the request-gated figure" is withdrawn, because the recorded requests are the regen latch (BT7-REQ-02). Re-evaluate after B8 and W1 have calibrated I_L, the efficiency and the current-sense offsets and after the EMS walk of open item 40; adoption would need the fixed window split of section 9.7 entry step 5, a demand-budget exit keyed on the commanded current and a two-source purge gate at I_fc 1.0-1.25 A | 1 | **Accepted as proposed 2026-11-09.** Variant D is not adopted; it is re-evaluated after B8 and W1 and open item 40 |
| OR-VC | (Revision 9.) The entry condition "V_chg below 11 V outside its blanking" takes the literal reading (V_chg below 11 V on two settled iterations); the strict reading (wait out the 1.0 s `ERR_VCHG_FED` blanking) costs 0.5-0.6 s per purge period and refuses no additional fault (section 9.11.4). Confirm or reverse | 1 | **Accepted as proposed 2026-11-09.** The literal reading is confirmed |
| OR-PK | (Revision 10, BT6-TR-02, BT6-REQ-02.) Operating rule for the State-99 pack drain: a parked FC window on the H-20 is attended, and the Pi raises an operator alert on `error_code` `ERR_FC_ONLY_COLLAPSE` or any State 99 (a Pi round). Alternatives for a later round: a confirmed pack PCM under-voltage cut-off (pack datasheet, open items 6 and 11), or a firmware low-power State 99 after the teardown (TODO(verify: PJRC)) | 1 | **Accepted as proposed 2026-11-09.** The operating rule applies; the Pi alert is a Pi round. The alternatives stay recorded for a later round |
| OR-R | switch_state bits 0x40/0x80 spent on FF1.Q and EF_EN (reserved for the HIL topology word, ino:710-713); HIL plant and campaign comparators in lockstep; or carry the bits in the new status word only | 1 | **Open.** The ruling offers two options without a recommendation. Needed before the Stage-1 firmware round (protocol v6 and the HIL plant lockstep) |
| OR-S | "Battery isolated during charging" is delivered as return isolation: pack positive stays on VBT, and the pack supplies the board load through the Ag105 sense in reverse in every window | 1 | **Accepted as proposed 2026-11-09.** |
| OR-T | Stage 1 as specified (recommended, with the Stage-2 deferral of M5 and the VOK clamp logic), or "Stage 1-lite" (section 14.2) with its weaker HR4 position (not recommended) | 1 | **Accepted as recommended 2026-11-09.** Stage 1 as specified; Stage 1-lite is not adopted |
| OR-V' | Replaces OR-V. The regen window arms on the command step (commanded motor current at or below -2 A on two consecutive drive-controller samples, 4 ms; under the retired fw v35 law pin 30 was HIGH 5.4-7.4 ms after the command, ahead of the first VOK assert; under the flashed fw v37 law the arm comes 4-26 ms after a decel step, section 7.8). A recorded option is an arm on a smaller magnitude with a rate condition (for example I_cmd at or below -0.5 A and decreasing on two successive controller samples), to be decided after the v37 re-derivation. The alternative is the revision-4 [RER] power arm (at least 3.0 W for 40 ms), which loses the first pulse of every decel (at most 43.9 % of the node energy above 18 V reachable), which ruling 1 classes as a fail. The cost of OR-V' is more short windows on light brakes, bounded by the 20-per-minute rate limit | 2 | **Accepted as proposed 2026-11-09.** The regen window arms on the command step. The rate-conditioned arm stays a recorded option, decided after the fw v37 re-derivation (open item 21) as the proposal states; the [RER] power arm is not adopted |
| OR-X | Charge-mode limits for the existing faults (reversals of the fw v30 limits of CLAUDE.md section 6): `OV_BATT` 8.5 V single sample reads high by I_p x (R_SH + R_DS + R_VBATN_X + R_FVX + R_s) in the charge mode (section 12.6 item 1): a charge-mode threshold or compensation after S0-1 and the F_VX selection; `UV_BATT` latches at a true pack of about 7.49 V between regen pulses (item 3): a charge-mode offset or a dwell exemption inside windows | 1 | **Open.** The ruling proposes no single form for either limit: OV_BATT takes a charge-mode threshold or a compensation, set after S0-1 and the F_VX selection; UV_BATT takes a charge-mode offset or a dwell exemption inside windows. Needed before the Stage-1 firmware round |
| OR-W | Reversals of current doctrine and firmware policy that IC1 needs, beyond OR-4 and OR-5': (a) `FC_CHARGE_ALLOWED` 1 for the FC window of section 9.7 only (parked, or at standstill in State 2), reversing the fw v31-v37 regen-only charging policy (ino:2600-2616); (b) CLAUDE.md section 3: the 2.5 A charge-current strategy (reg 0x00 = 0x01) becomes resistor mode (Table 5); the lazy configuration in `pollAg105()` becomes the one-time commissioning; the FC-path bootstrap that opens FC_CHARGE on intent in cruise is withdrawn (OR-O', OR-DM); the fw v33b lockout leaves the charge path (OR-P); the `chargerHasPower()` definition changes (section 12.5 item 1). The Death-5 MOT_PWR doctrine is kept | 1 | **Accepted as proposed 2026-11-09.** The CLAUDE.md section 3 text and `FC_CHARGE_ALLOWED` change in the firmware round; this document does not edit CLAUDE.md or the firmware |
| OR-AA | Cell balancing falls from up to 15 mA to 0.5-1 mA because RB1A becomes 4.7 kOhm (SLUSA52C 7.3, 7.6) and D_VCB is deleted (FM4-1). This agrees with the CLAUDE.md section 4 statement that the BQ29200 is used for OVP only; the pack's own balancing (pack datasheet missing) remains the only material balancing. The alternative, RB1A 100 Ohm with D_VCB, keeps the FM4-1 hazard (a clamp short drains cell 1 at 37-42 mA and can collapse the BQ29200 VDD) | 1 | **Accepted as proposed 2026-11-09.** RB1A 4.7 kOhm and no D_VCB; cell balancing 0.5-1 mA |
| OR-AB | Accept that an R_SH element open exposes both INA240 inputs to about -8.4 V (absolute maximum -6 V, row F34c), with the repair rule (replace U_SH1 and U_SH2 after any R_SH open) and the two-sided `ERR_IPACK_PLAUS` as the in-service check; or order an input-protection round. The rejected candidates are a GND-anode Schottky at KS+ (it conducts at the normal -1.0 V common mode and carries 1.9-3.7 A through R_K1 in the fault) and 100 Ohm series resistors (3.23 % gain error and up to 2 A equivalent of I_B-mismatch offset), `calc/verify_f34b_ks_ina240.py` sections 2-3 | 1 | **Accepted as proposed 2026-11-09.** The -8.4 V INA240 input exposure on an R_SH element open is accepted with the repair rule and the two-sided `ERR_IPACK_PLAUS`; no input-protection round is ordered |
| OR-AC | (BT5-DS-01, FM5-3; revision 8) D_VC1 temperature endpoints. Set T_min, the minimum operating ambient at which the V_F limit (0.25 V at 16.2 mA) applies; revision 7 used -20 C. With the B8 measurement of T_M16,max, the 40 uA leakage limit is feasible only if T_M16,max is at most about 44-59 C at T_min -20 C, or 63-76 C at T_min 20 C (calc8 section 3; upper bounds, because barrier lowering raises I_R). If no part meets both limits, choose: (a) a TI written rating for transient VC1 injection below -0.3 V at up to 16 mA (TODO(verify: TI)), which relaxes the V_F limit; (b) a larger leakage budget with a matching BG-17b hot-trip GO, `ERR_CELL_MISMATCH` threshold and a stated cell-1 OVP late-trip margin (I_R x 261 Ohm: 30 mV at 114 uA); or (c) an active clamp that keeps the VC1-short detection (a new circuit and its own review round). **Restated in revision 12 (BT8-DS-04, BT8-REQ-02).** The 44-76 C windows assume ideal saturation-current leakage. A real low-V_F Schottky leaks about 10 x I_S at 25 C (onsemi NSR0320MW2: I_S about 0.96 uA, I_R 10 uA typical at 15 V), so for a die that just meets the V_F limit the 40 uA budget holds only up to about 44 C even at T_min 25 C, and T_min is a weak lever (calc12 section 8). The NSR0320MW2 fails the 0.25 V design limit on its 25 C maximum row (0.283 V at 16.2 mA) and sits 17 mV inside the -0.3 V absolute minimum. No passive part has been identified that meets both endpoints. Unless B8-1 shows T_M16,max below about 44 C, decide between (a) and (c). For the first build only, option (d): fit a provisional part whose 25 C maximum V_F row at 16.2 mA is below 0.3 V (candidate NSR0320MW2), with T_min 25 C for the bench-attended Stage-1 sessions, so that C-1, BG-17b, B-PKN (at 25 C) and B8-1 can run; after B8-1, (a), (c) or a confirmed passive part replaces it | 1 | **Decided 2026-11-09: option (d) for the first build.** The operator ruled: "option (d) chosen for the first build - provisional D_VC1 (candidate NSR0320MW2) at T_min 25 C, bench-attended Stage-1 sessions only, so C-1, BG-17b, B-PKN at 25 C and B8-1 can run; choose (a) or (c) after B8-1 unless B8-1 shows T_M16,max below about 44 C." Only bench-attended Stage-1 sessions run with the provisional part fitted, at an ambient of at least 25 C; the choice between (a) and (c) follows B8-1 |
| OR-Y | (CC-B2) Regen windows in the State-98 D/Y/W profiles. Proposed: refused (pin 30 held LOW in State 98 except through `CHG_CONFIG`) | 2 | **Accepted as proposed 2026-11-09.** Regen windows are refused in the State-98 D/Y/W profiles |
| OR-RQ | (Revision 11, BT7-REQ-01.) The FC-window request is explicit: command byte 20 = 0xA5 with `charge_goal` above `CHG_GOAL_MIN`; a parked request on a Pi-connected vehicle carries `mode_cmd` 4. The Pi round that sets the flag from an explicit FC-charge decision only, never from the regen gate, is a Stage-1 prerequisite (section 12.12 item 6, gate W2e). Alternative for the operator: a command-protocol version byte; it needs a 23-byte packet and a lockstep length change | 1 | **Accepted as proposed 2026-11-09.** The request is the explicit flag (0xA5 in command byte 20); the version-byte alternative is not adopted. The Pi round remains a Stage-1 prerequisite (gate W2e) |
| OR-Z | (CC-B1) Trigger of the configuration check. Proposed: the mode manager starts `CHG_CONFIG` at the first Idle dwell after a self-test pass when `IC1_STAGE` is 2, no pass is recorded in this power cycle and the FC-window entry conditions hold; a State 1 to 2 request aborts it as the section 9.7 exit does | 2 | **Accepted as proposed 2026-11-09.** The configuration check starts as proposed |

Two round-8 residuals have no ruling ID (Appendix J, Table J1). The operator accepted both on 2026-11-09. First, row F66:
a double insulation failure (SHDN_EF and the CB-LB sleeve) can destroy Q_MD in linear mode when its V_GS(th) range
covers 1.55-1.68 V; the Q_MD selection still records V_GS(th), the linear-mode SOA and V_GSS (open item 17). Second,
sleeve segregation is the only protection of the SHDN_EF, MD_G, PROFILE, IMON, MS and EF_FLT_N leads and of the VC1 tap
at both lead ends (BT8-DS-01, BT8-DS-02, rows F54b and F54c); no clamps are added.

## 18. Open items

The following items have no primary in this study.

1. Ag105: cold-start and restart timing; threshold tolerance and behaviour; MPPTS law accuracy; function of the internal
   switch across the sense and the effect of LD; input capacitance; EPROM endurance; whether resistor mode is read at
   power-up only; the RCS open-detect boundary; behaviour at power-up within 0.2 V/cell of the CV setting; whether the
   module back-feeds its input; efficiency at 2S and 16-21 V input. TODO(verify: Silvertel).
2. RT1987 turn-off time after EN falls and the t_D_ON maximum. TODO(verify: RT1987 DS-00).
3. TPS26631 SHDN-rising to FET-on delay. TODO(verify: SLVSE94G section 6.6).
4. (Closed in revision 7: WDOG1_B is not used; pin 20 carries the VC1 tap.)
5. TI LVC gate, LVC1G17 thresholds at 3.3 V, AHCT buffer and LVC244A figures; TLV3011B V_OL and output clamp when
   unpowered; INA240 I_B mismatch and series-resistor gain error; BSS84; BZT52C15 tolerance; R_SH, fusible resistor and
   fuse data sheets (F_PK I2t); SLPS632 transient thermal impedance; i.MX RT1062 ADC sample capacitance; Teensy 3V3
   tolerance.
6. The pack maximum charge current and protection board (pack datasheet missing).
7. I_L (LM1084 input current and TPS61288 no-load current) in each window type, gate B8.
8. V_rgn reads 0.85 x true (M-R2).
9. The node capacitance C_N1 of the clear net on the as-built harness (C-2; tolerance up to 668 pF).
10. TPS26631 IMON gain tolerance, the tCL_PLIM row for the TPS26631, FLT behaviour on UVLO with SHDN low, and the
    TPS26636 fast-trip multiple. TODO(verify: SLVSE94G).
11. The pack PCM short-circuit trip current and delay, which bound the unfused pack leads between the cells and F_PK
    (row F43). TODO(verify: pack datasheet).
12. The harness position of the BOM-line-51 BF302 inline holder. TODO(verify: harness survey).
13. Clamp part D_VC1 with V_F at most 0.25 V at 16.2 mA at T_min and I_R at most 40 uA at 4.2 V at T_M16,max (the two
    limits conflict above T_M16,max of about 44-76 C, calc8 section 3; with real-part leakage about 44 C, calc12 section
    8; no passive part identified, revision 12; ruling OR-AC, option (d) for the first build, decided 2026-11-09: a
    provisional part, candidate NSR0320MW2, at T_min 25 C; the final part, or option (a) or (c), after B8-1); the BQ29200 VC1_CB absolute maximum (sub-mA injection in row F34b). TODO(select), TODO(verify: TI). The
    pad positions are resolved from the BRD (M16).
14. The open-drain TLV3011B propagation delay; the LVC1G07 figures. TODO(verify: SBOS300C, TI datasheet).
15. The VBUS via used for the channel-2 VOK tap (M7). TODO(verify: BRD net VBUS via list).
16. F_VX part (candidate Littelfuse Nano2 451/453 4 A, amp code 004: 16.0 mOhm, 2.469 A2s, 400 A at 32 VDC as read in
    BT5-DS-03) and its I2t against the Ag105 sense rating. Re-read at order; TODO(verify: Silvertel).
17. Q_MD part (40 V, logic-level, an R_DS(on) row at V_GS 2.5 V; revision 12: the V_GS(th) range, the transfer
    characteristic near 1.55-1.68 V, a linear-mode SOA and V_GSS recorded for row F66, whose double-fault residual the
    operator accepted on 2026-11-09) and the R_MD pulse and repetitive rating (1.71 J in
    100 ms; 0.65 W for 30 s; fails open; repetitive dumps on the doc 20043 continuous-pulse curve, revision 8); candidate
    Vishay CRCW2512-HP 15 Ohm. TODO(select), TODO(verify: Vishay doc 20043).
18. Whether a released (open-drain) MPPTD reads MPPT enabled; the module status in the probe state. TODO(verify:
    Silvertel), S0-7.
19. (Closed in revision 7: SBOS300C section 9.4.5 gives a Hi-Z output below the minimum supply.)
20. Whether the SLVSE94G thermal-regulation timer runs when T_J stays below 145 C in a soft overload, and the 162 ms
    current-limit timeout of the block diagram. TODO(verify: SLVSE94G section 8.3.7.2.1), S0-12b.
21. The regen-arm latency under the fw v37 drive law in closed loop (section 7.8) and the V-MOT sink slope after a
    step-down pulse whose command ends at 0 (V2-1). Calculation round and BENCH.
22. What drives the ENC_B net on pin 8 after the 2026-08-16 encoder reroute, and the rail of the RENC2 pull-up (3V3 on
    the SCH; a 5 V rail is a speculation in `docs/claude-md-archive.md`, UNCONFIRMED) (gate P8).
23. The items left open by the completeness critic (section "Completeness critic", table CC-B).
24. The i.MX RT1062 analog-input leakage drift on pin 20 against the 122 kOhm tap source (0.488 V of mismatch per uA;
    79 nA allowed, calc8 section 4). TODO(verify: IMXRT1060CEC); C-2a item 5 calibrates at room temperature and records
    the hot and cold readings. A CMOS follower on LB is the fallback if the drift exceeds the allowance (a new circuit).
    Revision 12: the datasheet bound (1 uA, Table 22) is 12.7 times the allowance; if the hot and cold spread needs a
    threshold above 80 mV, only the D_VC1 leakage and pack-imbalance coverage is lost (F47 detection holds up to 7 V,
    calc12 section 7); then adopt the CMOS follower or OR-AC (b).
25. The TLV3011B open-drain output fall delay (the exit hold check needs less than 50 us). TODO(verify: SBOS300C),
    C-2b item (g).
26. The INA240 input behaviour beyond the -6 V common-mode absolute maximum (row F34c). TODO(verify: TI).
27. The board temperature at M16 (T_M16,max) in Run and in windows. Gate B8; it gates the D_VC1 selection (OR-AC).
28. TPS26631PWPR stock (TI.com out of stock on 2026-11-07; distributor snapshots disagree). Confirm it live before any
    order.
29. Input-injection limits of the parts behind the revision-8 LB-entry resistors. Revision 12 (BT8-DS-01, BT8-DS-02):
    the TLV3011B inputs have no clamp to V+ (SBOS300C section 6.2 note 2, section 9.4.4) and the LVC outputs have no
    positive clamp (SCES214AF section 5.1), so both questions are closed as negative and the leads rely on segregation
    (section 5.7 item 4); the operator accepted segregation as their only protection on 2026-11-09, with no clamps
    added. Still open: whether the i.MX RT1062 pad (pin 20, pin 10) survives 0.22-0.81 mA, for which
    IMXRT1060CEC Table 7 gives no injection current. TODO(verify: IMXRT1060CEC).
30. The minimum Ag105 input capacitance C_mod (no lower bound in the datasheet); the exit hold check needs at least
    47 uF for its 150 us sample (S0-11).
31. The minimum operating ambient T_min of the vehicle (ruling OR-AC). For the first build, OR-AC option (d) sets T_min
    25 C for bench-attended Stage-1 sessions (2026-11-09); the vehicle T_min for the final part remains open.
32. (Revision 9.) The D-BT-EN and D-FC-EN conduction onset after a re-close onto a live bus (t_D_ON plus the 19.77 ms
    soft-start), on which T_lead rests (gate W2a). The 30 ms `SHARE_CUT_SURVIVOR_BLANK_MS` covers the onset only at
    t_D_ON 8 ms (27.8 ms), not at 12 ms (31.8 ms); the break-even is t_D_ON 10.23 ms (r6 section 3). This concerns
    every bus-switch re-close, not only the purge sequence (seq section 9 item 1). Inside the IC1 purge sequence SC-8
    ownership and the in-band substitution hold the share latch off pins 27 and 28 until BT_BUS has conducted
    (revision 10), so the uncovered interval cannot cut FC_BUS there. TODO(verify: RT1987 DS-00), BENCH.
33. (Revision 9.) Whether the TPS61288 soft-starts after a VIN-UVLO recovery with EN held HIGH (SLVSFP3C section 8.3.1
    describes the soft-start for an EN rising edge only). Under policy E2 FC_REG is LOW before the FC recovers in every
    grid case, so the answer matters only for policy E1 or E3. TODO(verify: TI), recorded at W2c.
34. (Revision 9.) The TPS26631 reverse current from OUT to IN with B_GATE open, and its rating (TODO(verify: SLVSE94G));
    the Ag105 lockout tolerance (11 V typical only), MPPT loop speed and restart after a brown-out (TODO(verify:
    Silvertel)); the FC fall time at a purge onset (no primary; E2 removes the dependence).
35. (Revision 9.) V-MOT capacitance (0.48-5 mF), the bus-side auxiliary load (0.5-150 mA) and the VESC cut-off voltage
    (8 V ASSUMED), which set the collapse rates of section 9.11.5. BENCH; TODO(verify: VESC).
36. (Revision 9; narrowed in revision 10.) At a standstill load no override is written and the MDAC split carries no
    requirement (section 9.11.3 step 5). Open: the share-override duration in closed-loop State 2 with no session
    (Table 21: 100-168 ms ESTIMATE, 288.7 ms bound) and the stale filter value on a frozen return (ino:14287), which
    re-enters closed loop at the next launch with the pre-drop total until the EMA decays (UNVERIFIED). Host test and
    HIL.
37. (Revision 9; closed by design in revision 11.) `doState3()` does not clear `shareSpCutFC` (ino:7961-7999): a Run that
    ends with the selector holding FC_BUS LOW left an Idle window refused with nothing to release the cut (seq section 9
    item 2). Revision 11 releases it through the guarded path before a State-1 or State-98 session (section 12.4 item 9);
    host test in section 12.11.
38. (Revision 9.) The standstill constants I_still, T_still and the standstill speed threshold of variant D-s, and the
    charge_goal request threshold `CHG_GOAL_MIN` (TODO(calibrate), W2b).
39. (Revision 9; revision 10.) The State-99 drain of the pack through the LM1084 at about 0.2-0.25 A until a power
    cycle (UNCONFIRMED; 8-25 h for 2-5 Ah remaining, calc10 section 7), measured at W2c step (iii); the pack PCM
    under-voltage cut-off (open items 6, 11); the LM1084 headroom at the end of a parked discharge (dropout 1.5 V,
    SNVS037H section 5.5). Operating rule OR-PK.
40. (Revision 11, BT7-REQ-02.) HR2 in Run against an EMS that requests FC charge: walk the SDP v7 policy and the Pi
    J_charge table of the 2026-10-28B node over the drive cycles in `tools/ems_walk.py` with the IC1 admission rules
    (standstill, the 8.0 V gate, the 1.282 s admission horizon, a dead time of 0.450-0.569 s per purge period, the
    State-2 dump check at the first stop) and compare D-s with D. ANALYSIS, not run in this study.
41. (Revision 11, BT7-TR-01.) The in-window FC droop resistance at the fixed split: 0.094 Ohm (bench-scaled) to
    0.353 Ohm (design chain) at r 0.85, and the 4x design/bench droop gap behind it (`tools/hil_plant_sim.py:467-505`;
    the open DMM measurement of the AD5443/OPA197 block). TODO(calibrate) at W1.
42. (Revision 11, FM7-2.) The maximum loop iteration on the production build (USE_ETHERNET 1, State 2, the Ag105 poll
    and the SD drain): the only figure is 9.76 ms on a State-98 USE_ETHERNET 0 build (ML0226,
    `docs/reviews/noise_fw37_2026-11-05/agents/vbus_blg1k.md` section 1). BENCH at W1 and W2b.
43. (Revision 12, BT8-REQ-04.) The firmware-size estimate of section 12.12 for the revision-11 and revision-12 items and
    the HIL injection-frame extension. ANALYSIS at the firmware round.
44. (Revision 12, BT8-REQ-01.) The H-20 open-circuit voltage against the 12.34 V full scale of the pin-24 divider: an
    unloaded stack above 13.46 V would overstress pin 24 in W2 and W2a as the 16 V setpoint did. TODO(verify: Horizon
    H-20 OCV); this exposure exists on the board revision 20260622 independently of IC1.
45. (Revision 12, BT8-REQ-01.) fw v37 rev 2 has no V_fc overvoltage fault (no `LIMIT_V_FC_MAX`, no `OV_FC`), so a V_fc
    reading saturated at 12.34 V is not detected. Recorded; a fault is a firmware-round option, not part of IC1.
46. (Revision 12, BT8-TR-01.) The TPS26631 UVLO-to-ramp delay and whether it scales with C_DV (1.24 ms at 10 nF).
    TODO(verify: SLVSE94G); measured at S0-11.

## Appendix A. Traceability to revision 2

Revision 2 rows F1-F19, gates B1-B16, C-1 to C-3 and D-1, D-2 are carried into sections 11 and 15 with the same meaning,
renumbered where Stage 0 groups them. Revision-2 items removed in revision 3: FF2, the TPS3431, Q_E, Q_X3, the per-event
MOT_PWR cycle, the brake pre-arm hold, the traction hold for the whole window, gate B15, the per-window EPROM writes
(OR-5), the J3 GND tap to the switch board, and the exit wait for I_PACK below 0.1 A. The revision-2 dossier remains the
design history; this document supersedes it for any build.

## Appendix B. Battle-test round 1 adjudication

Battle-test round 1 produced 62 findings (1 blocker, 20 major, 41 minor after verification): the FMEA lens (`battletest/fmea_round1.md`, FM-1 to FM-14) and the transient,
logic, datasheet, Ag105, buildability and requirements lenses (BT1-*). Each blocker and major finding was verified
independently; no finding was refuted in full. Table B1 gives the disposition of each finding. The dispositions have the
following meanings:

- **FIXED**: the hardware, sequence or firmware specification changed.
- **GATED**: only a measurement can decide; a hard bench gate was added or changed.
- **RULING**: the decision belongs to the operator; a ruling was added to section 17.
- **REJECTED**: not adopted, with the evidence given.

A finding can carry more than one disposition. Rejected parts of otherwise adopted findings are named in the last column.

Table B1. Battle-test round 1 adjudication.

| Finding | Severity (verified) | Disposition | What changed |
|---|---|---|---|
| FM-1 Kelvin leads unfused | Blocker | FIXED, GATED | R_K1/R_K2 2.2 Ohm fusible at the R_SH terminals (Fig. 1); rule C1 (section 4.2); trip budget re-run with the R_K term (Table 10); rows F27, F28; C-2 injection test. The value 2.2 Ohm (not 10 Ohm) keeps the I_B x dR term at 0.008 A (calc4 section 1). The bond figure of part (2) is bounded by the eFuse I_OL; R_K reduces it to about 40 mA. |
| FM-2 VOK fails toward OK on a VBUS-side open; shared tap pads | Major | FIXED, GATED | Separate taps and wires per channel (Fig. 4, M7); bus-present comparators U_BP1/U_BP2 with clamps Q_RB1/Q_RB2 and the U_CH/U_VA logic; `ERR_VOK_STUCK` in every non-braking iteration; rows F15b, F29; V2-1 tap-open sub-steps. The pull-up proposal is REJECTED (0.128 V with 1 MOhm to 5 V, verifier recompute). |
| FM-3 Ladders settle in up to 8 ms | Major | FIXED, GATED | Ladders at 2.00k/4.02k/10 nF (tau 20 us, calc4 section 4); settled-reading rule; hardware-driven bits excluded (section 12.4 item 4); C-2 step-response gate; host test with the RC model. |
| FM-4 Injection self-test passes with U_C2 blind; D5 and clamps untested | Major | FIXED, GATED | Signal-side injection with ADC readback of SIG1/SIG2 (U_SH2 reversed); D5 injection and the D5_N ladder bit; rows F40, F41; gate ST extended. Clamp and Q_D5-path faults have no readback pins: accepted latent faults tested at C-2/B10 (F40). The two-level injection is REJECTED as unnecessary once the ADC reads the signal node (an open R_F reads 0 V). **Revision 5:** the step-6 D5 check was masked by the Q_D5 body diode; D_D5S fixes it (FM2-4, Appendix C). |
| FM-5 Parallel bond upstream of R_SH invisible | Minor | FIXED | Rows F12/F12b with corrected detection and causes; rule C2; earth-reference warning; C-1b. The bonded-mode integrity check is REJECTED (a 7 % shortfall at R_b 100 mOhm is within the estimate uncertainty). |
| FM-6 One part removes both S_GND gate supplies | Major | FIXED | Per-channel taps VBT_T1/VBT_T2 with F_T1/F_T2 and series capacitor pairs (Fig. 1); F2 reclassified; F31. Dropping the common fuse is REJECTED (a C_VT short would put pack+ on SGND behind only the 20 A fuse). |
| FM-7 Pin 33 high-Z leaves N1 and CLK undefined | Major | FIXED, GATED | U_P33 buffer with its pull-down at the buffer input (Fig. 2, calc4 section 6); Table 13, 9.10 and HR5 restated; B11c. A Schmitt buffer without a defined input is REJECTED as insufficient (verifier). |
| FM-8 Bonded-mode barriers latent; eFuse output never observed | Minor | FIXED, GATED | Refusals of REGEN/FC_CHARGE and the State-98 `4`/`5` keys outside charge-mode states (section 12.4 item 7); State-99 drains skipped (9.9); `ERR_EFUSE_BYPASS`; rows F35, F36; D-2 gap insulation. The boot test that feeds VCHG-IN in the bonded mode is REJECTED (verifier: unproven threshold, deliberate feed). **Revision 5:** `ERR_EFUSE_BYPASS` as defined here had no firing opportunity; replaced by the eFuse-blocking probe and `ERR_VCHG_FED` (FM2-7, Appendix C). |
| FM-9 S_GND drain-source short passes the SG readback | Minor | FIXED | Sense-path check (V_PACKN against the reverse chain drop) in the self-test and at entry; F1 detection corrected. |
| FM-10 State-99 drains inert under IC1 | Minor | FIXED | Same as BT1-06. |
| FM-11 5V loss reads OK | Minor | FIXED | VOK comparators and pull-ups on 3V3 (Fig. 4); F30; Table 13 corrected. |
| FM-12 Q_D and readback thresholds above the S_GND conduction threshold | Minor | GATED | Recorded as an accepted residual (F42) with the sense-path check as detector; C-2 measures the band. Re-ratioing still overlaps (BSS138 0.8-1.5 V against CSD18510Q5B 1.2-2.3 V). |
| FM-13 Slow FF1 edges | Minor | FIXED | U_CKS and U_CLS Schmitt buffers. |
| FM-14 OVP chain not observed in service | Minor | FIXED | BAL_OK on ladder A bit 4 (M15); `ERR_BAL_ABSENT` refuses windows. The OUT path itself (F25) remains latent. **Revision 5:** R_OVP pull-up makes an open OUT path detected; a short to GND remains latent (BT2-BM-02). |
| BT1-T1 Ladder RC against 1-2 ms deadlines | Major | FIXED | Same as FM-3; confirmations now 5 ms with settled readings; 9.6 delay restated; self-test step-7 exposure (up to 90 ms) stated. |
| BT1-T2 S0-6 GO inconsistent with the 19 ms pulse | Major | GATED | Per-pulse S0-6 criterion (Table 8a, calc4 section 11); new gate V2-0 (t_D_ON); HR1 row states no fast-pulse margin from hardware alone. Pre-closing D-BC-RG is REJECTED: it would leave the eFuse as the only VOK element and break the two-element HR3 argument. |
| BT1-T3 FF1 set race | Minor | FIXED, GATED | R_CK 10k with U_CKS; U_CLS on /CLR; margin at least 4.5 us at 130 pF; C-2 edge capture with 1000 sets. |
| BT1-T4 Release race fails for fast V-MOT falls | Minor | FIXED, GATED | Section 7.2 item 2 and HR3 restated (bus feed at most about 12 us per traction onset); centred-hysteresis release margin 0.112 V; V2-2 extended. |
| BT1-T5 D5 arming 2.8-6.1 ms | Minor | FIXED | Text corrected; FC-window entry waits for BT_CURRENT below 0.2 A (9.7 step 5). |
| BT1-T6 FC-window inrush with a large input capacitor | Minor | FIXED | Section 5.3 rule: no added input capacitor unless C_DV is re-derived first (inrush at most 0.6 A). |
| BT1-01 SB cable open inside a window | Minor | FIXED | 9.10 rows corrected; F33; `ERR_PACKN_RANGE`. The fail-safe readback inversion and an SG term in U_AND are deferred to a later round (they need a second hardware proof). |
| BT1-02 Shared VBUS tap and 5V loss give a bus-fed loop | Major | FIXED, GATED | Same as FM-2 and FM-11; 7.2 item 6 notes that a copper lift of the R1-BUS pad also latches UV_BUS. |
| BT1-03 Ladder confirmations cannot settle | Major | FIXED | Same as FM-3; the decode-failure branch now has a persistence window. |
| BT1-04 Reset does not clear FF1 and can set it | Major | FIXED, GATED | Same as FM-7. |
| BT1-05 Stage-3 hold-up breaks "input removed before the bond" | Minor | FIXED, GATED | Dump FET Q_HU keyed to FF1./Q (Fig. 6, 14.4); F37; S0-13 exit case. |
| BT1-06 State-99 drains in the bonded mode | Minor | FIXED | Drains skipped under `PACK_RETURN_CHANGEOVER` (9.9); F11 bound restated; host test. Running the drains before pin 33 LOW is REJECTED (from Idle or Run the board is already bonded, so the eFuse cannot be enabled). |
| BT1-07 One C_VT short or F_T open removes both gate supplies | Major | FIXED | Same as FM-6. The V_PACKN comparator into BT_REG is not adopted: the brownout is UNCONFIRMED and the firmware cut exists (7.6). |
| BT1-DS-01 /CLR at 1.6-1.9 V with pin 33 high-Z | Minor | FIXED | Same as FM-7. |
| BT1-DS-02 RC edges over the LVC74 slew limit | Minor | FIXED | Same as FM-13 and BT1-T3. |
| BT1-DS-03 BQ29200 bottom cell referenced to PCB GND | Minor | GATED, RULING | Offset restored in 12.6 item 2; gate W0; OR-E covers the BQ trip response. The "OVP blind" half is REJECTED (the cells are discharging when PACK- is negative); option (a), ungating the OVP, is REJECTED. |
| BT1-DS-04 F_PK open drives VC1 below -0.3 V | Major | FIXED, GATED | F_PK moved to the pack-positive lead, gate taps upstream of it (section 4.1); F34; gate B-FPK; connector mating-order warning. **Revision 5:** PARTIAL. The fix covered F_PK only and left SB pack-positive copper unfused (FM2-1); F_PK moved to the pack terminal; pack-negative opens upstream of R_SH covered by D_VM and F34b (FM2-6). |
| BT1-AG-1 Overstressed Ag105 reused without qualification | Major | GATED | Gate D-3 (new module from the qualified lot, or in-situ requalification); commissioning step 1 requires D-3; 14.1 states that Stage-0 results transfer only through D-3. |
| BT1-AG-2 Commissioning charges at the as-found 2.5 A | Major | FIXED | Commissioning with pin 32 LOW (9.2, Table 12); as-found registers recorded before any charge path; refusal in 12.4 item 7; F39. |
| BT1-AG-3 Profile network fault can select 2.5 A | Minor | FIXED, GATED | `ERR_PROFILE_OC`; F38; C-2 CSEL resistance measurement; S0-4 open-detect points; G6 and HR4 text corrected. A profile-keyed U_C2 is REJECTED as unnecessary (U_C2 already bounds the pack current). |
| BT1-AG-4 Stage-0 rig omits the vehicle conditions | Major | FIXED | Rig rebuilt (14.1): RT1987, switchable R_KA, I_L load, always-on MPPTD/I2C rail, capacitor-bank source; S0-2, S0-4, S0-9, S0-10 extended; S0-9 NO-GO derived from S0-1 instead of an invented 0.3 V. |
| BT1-AG-5 S0-2 unbounded | Minor | FIXED | S0-12 before S0-2; supply current limit; pack simulator first; scope criterion. Changing the NO-GO to "stop Stages 1-2" is a RULING already covered by OR-I. |
| BT1-AG-6 Stage-3 hold-up keeps the module powered | Minor | FIXED | Same as BT1-05. |
| BT1-AG-7 Stage-2 I2C checks inert; 0xFF not excluded | Minor | FIXED | Valid-read rule (12.5 item 2); `ERR_ISO_MISMATCH` scoped to FC windows; configuration check 9.7a replaces the "first window after power-up" clause. **Revision 5:** the 0xFF exclusion now applies to measurements only (reg 0x02 = 0xFF is the expected setting) (BT2-AG-1). |
| BT1-BM-01 Ladder RC; UC1_N toggles in bonded Run | Major | FIXED | Ladder values; UC1_N and UC2_N removed from the ladders (trip attribution from I_PACK1/I_PACK2/V_PACKN at the trip sample). |
| BT1-BM-02 V_PACKN transfer omits R_VPS | Major | FIXED, GATED | Section 7.9; Table 15; two-point calibration and `ERR_SGND_OPEN` acceptance at C-2; R_ret test at 5 A or more; F22 lead A stated undetectable and benign. |
| BT1-BM-03 BQ bottom cell over-reads in the charge mode | Minor | GATED | Same as BT1-DS-03; OV_BATT boundary includes the VBATN_X lead (about 60-64 mOhm). |
| BT1-BM-04 G1 trips inside the FC window | Major | FIXED | G1 residual form in FC windows (12.7); host test. The I_OL-based threshold is REJECTED (at least 2.3 A, above OC_FC, so G1 would be inert). **Revision 5:** the residual form was mis-specified (input voltage for output voltage); rebuilt on I_PACK1 (BT2-TR-04). |
| BT1-BM-05 M3 and M11 under the module | Major | FIXED, GATED | M3 on the bottom-layer run at x >= 49.2; M11 on the underside; outline check in B2. |
| BT1-BM-06 Cut-gap isolation | Minor | FIXED, GATED | M1/M2 procedure (flush cut, gap, barrier, sleeve); D-2 standoff and insulation; P-M1; F36. |
| BT1-BM-07 Earth-referenced instruments | Major | FIXED, GATED | Rule C2; warning in section 15; C-1 extended; C-1b. |
| BT1-BM-08 Lead B joint unspecified | Minor | FIXED, GATED | M13 procedure; C-2 4-wire and ground-offset acceptance. |
| BT1-BM-09 Assembly-error modes | Minor | FIXED, GATED | C-1 polarity check with a 0.1 A supply; keyed KS and 7-way connectors; colour-coded J-BT leads; self-test step 2 checks FF1.Q; M6 tap continuity. |
| BT1-BM-10 Reversibility, lead times, U_C2 figure | Minor | FIXED | Table 6 reversal column; lead times TODO(verify) in section 16; U_C2 figures regenerated by calc4 section 2. |
| BT1-RO-01 HR1 capture; S0-6 looser than the requirement; 23 W text | Minor | FIXED, GATED | Section 1 and 7.1 text (22.73 W ceiling); S0-6 per-pulse criterion. The claim that ruling 3 is reversed without a ruling is REJECTED: OR-C restates ruling 3 and now names the always-powered strategy as unused. |
| BT1-RO-02 HR2 zero on the vehicle | Minor | RULING, FIXED | OR-P; purge predictor and State-1 call site in 12.12; Stage-1 value restated (14.2). |
| BT1-RO-03 Fully Charged at cold power-up caps the pack near 8.0 V | Minor | GATED | S0-8b; interim FC-window entry limit V_batt below 8.0 V. |
| BT1-RO-04 Stage-3 hold-up | Minor | FIXED | Same as BT1-05. The OR-2' contradiction is REJECTED (the exit does not wait for C_HU decay). Revision-7 note: the revision-5 drain wait made this clause false, and Stage 3 is withdrawn (Appendix E, BT4-TR-01). |
| BT1-RO-05 Regen-window diagnostics cannot run | Minor | FIXED | Same as BT1-AG-7; F1 and F19 detection in regen windows stated as hardware-only. |
| BT1-RO-06 Dwell-free regen entry | Minor | FIXED, RULING | [RER] power arm (OR-V); host dither test; OR-2' drive-law question. The "or V_rgn above the bus" trigger is REJECTED ([RER] marks V_rgn gating blocked by the 0.85 reading). **Revision 5:** the 40 ms power arm loses the first pulse; replaced by the command-step arm OR-V' (BT2-TR-02, BT2-RO-01). |
| BT1-RO-07 Missing rulings | Minor | RULING | OR-M, OR-O, OR-P, OR-R, OR-S added; OR-C and OR-G extended. Item 4 (concurrent windows) is REJECTED as already covered by OR-7. |
| BT1-RO-08 Change set understated | Minor | FIXED | Section 12.12 inventory, watchdog prerequisites in 12.3, per-board calibration storage. |
| BT1-RO-09 Stage 1-lite | Minor | RULING | OR-T, with the weaker HR4 position stated (14.2). The claim of an equal HR3-HR5 position is REJECTED (one INA240 is a single point for both trips). |
| BT1-RO-10 Self-test exposure misstated | Minor | FIXED | 9.3 exposure (up to 90 ms), validity and deferral rules, duration about 420 ms; the R_ret step moved to Run at 5 A or more. **Revision 5:** the self-test is non-blocking (FM2-9). |
| BT1-DS-05 S_CHG interlock threshold on the wrong node | Minor | FIXED, GATED | Equation 7 gate-referred (1.43-2.46 V); F10 nominal overlap 25-45 us; C-2 measurement. |
| BT1-DS-06 TLV3011B terms outside data-sheet conditions | Minor | FIXED, GATED | CMRR and 3V3 terms in Table 10; ramp-aware delays in 7.2 and Table 11; T1 and V2-2 measure them. |
| BT1-DS-07 MPPTS law approximate | Minor | GATED | Threshold marked BENCH; S0-4 measures the start threshold; mid-band re-selection as the NO-GO action. |
| BT1-DS-08 eFuse UVLO below the Ag105 11 V minimum | Minor | FIXED | R_UV2 10.5 kOhm: 12.38-12.88 V on, 11.47-12.10 V off (calc4 section 9). |

The following findings change the HR status of section 13: FM-2 and BT1-02 (HR3 two-failure claim restored by
construction, now conditional on the V2-1 tap-open sub-steps), FM-7 and BT1-04 (HR5 reset clear restored), BT1-T4 (HR3
restated with the 12 us transient bound), BT1-AG-3 (HR4 restated) and BT1-T2 (HR1 fast-pulse margin stated).


## Appendix C. Battle-test round 2 adjudication

Battle-test round 2 produced 42 findings: 1 blocker, 16 major and 25 minor at their verified severity. The lenses were
the FMEA lens (`battletest/fmea_round2.md`, FM2-1 to FM2-11) and the transient, logic, datasheet, Ag105, buildability
and requirements lenses (BT2-*, DS2-*). Every blocker and major finding, and the minor findings listed with a verifier
note, was verified independently; no finding was refuted in full. Thirteen findings were confirmed at a lower severity
than filed or with corrections (FM2-2, FM2-5, FM2-8, BT2-TR-03, DS2-2, DS2-3, BT2-AG-2, BT2-AG-3, BT2-AG-4, BT2-BM-03,
BT2-BM-04, BT2-RO-02, BT2-RO-03). The dispositions have the meanings of Appendix B. Rejected parts of otherwise adopted
findings are named in the last column, with the evidence.

Table C1. Battle-test round 2 adjudication.

| Finding | Severity (verified) | Disposition | What changed |
|---|---|---|---|
| FM2-1 SB pack-positive copper unfused next to pack-negative copper | Blocker | FIXED, GATED | F_PK moved to the pack terminal, upstream of the connector, every SB conductor and both taps (section 4.1, Fig. 1, Tables 3, 4, 7, M14). New row F43 (174-592 A prospective at an ASSUMED R_int; any loop below 0.37 Ohm exceeds 20 A, calc5 section 1). F34 restated: with F_PK open the S_GND body diodes keep VC1 - GND at V_cell1 - V_F (positive). Gate B-FPK repeated at the new position and now records every node that stays powered (VBAL+ as the only source is UNCONFIRMED). The BF302 holder of BOM line 51 is surveyed as a candidate holder. The pack leads between the cells and F_PK remain bounded only by the pack PCM (open item 11). |
| FM2-2 All clears funnel through N1 and U_CLS; diode shorts on push-pull sources | Minor | FIXED | P33B and PUMP_OK join N1 through open-drain SN74LVC1G07 buffers (U_N33, U_NP); pin 20 open-drain; every N1 source can only pull LOW (Fig. 2, eq. 1). F32b corrected (U_CLS stuck HIGH is F32c, detected at steps 4b/6, not step 4); rows F32c, F32d; self-test step 4b (pin 33 LOW alone clears FF1). A fourth U_AND term from UC2_N is REJECTED: it is not latched and would limit-cycle with the eFuse dV/dT restart (verifier); the U_C2 loss is bounded by U_IM and the eFuse I_OL, as in F24. |
| FM2-3 KS+/KS- short blinds U_C1 and U_C2; plausibility check undefined | Major | FIXED, GATED | New fault `ERR_IPACK_PLAUS` (bonded: BT_CURRENT above 1.0 A for 100 ms with I_PACK1 discharge below 0.5 A; margin at least x4.0, calc5 section 4); a pass this power cycle is a regen-window precondition; self-test step 5 fails instead of skipping when BT_CURRENT predicts a discharge; row F44; F21 detection corrected (it named a non-existent check); C-2 short test at 1, 3 and 7 A. FC windows are also covered by `ERR_ISO_MISMATCH` (I_PACK1 0 against reg 0x06 1.25 A). A second 4-terminal shunt (true channel independence) is not adopted: the hardware cost is not needed once the common cause is detected. |
| FM2-4 Q_D5 body diode drags D5_N LOW when N1 is LOW | Major | FIXED, GATED | D_D5S BAT54 between N1 (anode) and the Q_D5 drain (Fig. 3, Table 4). D5_N then reads at least 3.28 V with N1 LOW; on a D5 trip N1 sits at most at 0.42 V against VT- 0.89 V (calc5 section 2). Self-test step 1 passes on a healthy board and the step-6 D5_N L check measures U_D5 itself; trips are no longer misattributed to D5. C-2: D5_N at or above 3.2 V with pin 33 LOW. FM-4 note added in Appendix B. The "ladder bit from ahead of any FET" alternative is moot (D5_N is the U_D5 output). |
| FM2-5 Ground offset turns S_GND off and S_CHG on; both leads open | Minor | FIXED, GATED | Row F22b (self-bias at 0.84-1.65 V; S_CHG 5.6-12.6 W at 7.2 A, `calc/verify_sgnd_offset_bothleads.py`; detected by `ERR_PACKN_RANGE` and `ERR_SGND_OPEN`); section 4.2 item 1 states the self-bias threshold; C-2 both-leads-open step. The finding's 2.8 W figure is corrected upward and its doubt about detection is refuted (verifier). The Zener or isolator gate input is REJECTED as unnecessary: the pulse is bounded to one iteration plus 5 ms at board load by two independent detectors. |
| FM2-6 Pack-negative open upstream of R_SH: VC1 below -0.3 V | Major | FIXED, GATED | D_VM Schottky from GND to VMID at J-BL (M16, upstream of RB3/RB1A), so VC1 = -V_F in the fault (needs V_F below 0.25 V, calc5 section 3); row F34b; gate B-PKN (connector and R_SH-joint opens); mating-order warning restated; BT1-DS-04 marked PARTIAL in Appendix B. Round-1 row SB-3 (`battletest/fmea_round1.md`) is superseded by F34b. Pin-level clamps at VC1/VC1_CB are the B-PKN fallback. |
| FM2-7 HR3 second elements latent; `ERR_EFUSE_BYPASS` cannot fire; note 1 miscounted | Major | FIXED, GATED | New fault `ERR_VCHG_FED` (V_chg above 11 V for 50 ms with pins 30 and 31 LOW, 1.0 s blanking, calc5 section 5), also a window-entry precondition; `ERR_EFUSE_BYPASS` replaced by the eFuse-blocking probe in every configuration check (section 9.7a, reg 0x07 criterion); note 1 rewritten (D-BC-RG + eFuse is two faults; D-BC-FC alone is one, closed by `ERR_VCHG_FED`); rows F11, F15, F17, F35, F36 restated; FM-8 re-opened and closed again by these changes. The VCHG-IN_M comparator on a ladder bit is REJECTED: with a healthy upstream switch VCHG-IN_M is unfed in the bonded mode either way, so any detector needs a deliberate feed, which the probe provides without new hardware. |
| FM2-8 Stage-2 configuration check needs OR-P and FC_CHARGE_ALLOWED 1 | Minor | FIXED, GATED | Section 14.3 lists OR-P, T-E-01 and W2 as Stage-2 prerequisites on the vehicle; HR1 row notes it; gate V2-6. FC_CHARGE_ALLOWED 1 was already a Stage-1 prerequisite (12.2 item 4, now OR-W). Keeping BT_BUS closed during the check (Q_X1 keyed to FCQ AND EN_SQ) is not adopted: it is a schematic change whose loop bound through R_KA is not proven. |
| FM2-9 Self-test is a 420 ms blocking poll with the bus live | Major | FIXED | Self-test respecified as the non-blocking `CHG_SELFTEST` sub-state (section 9.3, 12.4 item 8): one step per iteration after `detectFaults()`, `millis()` deadlines, the 2 s validity wait as a deferral, abort on a State-2 request or fault with the transition held until the bonded settled reading; the pump writer stays in `loop()`; host tests for the abort, for `detectFaults()` during the test and for an OV_BUS during step 2. Watchdog timeout recorded as TODO(calibrate) (12.3 item 2). |
| FM2-10 I_o at most 2.5 A asserted but unenforced | Minor | FIXED, GATED | Section 7.1 states the ceiling as conditional; regen-window hold condition: estimated I_L at most 0.75 A for 20 ms, else exit; gate B8 restored (I_L, I_L,cal, eta_cal in both window types). |
| FM2-11 Commissioning refusal one-directional; J-NTC; pack-absent C-1 | Minor | FIXED, GATED | Pin 32 HIGH refused while FF1.Q reads HIGH (12.4 item 7, 9.2 step 11, F39); rule C2 names J-NTC and pack-internal conductors; gate C-1c (pack installed). |
| BT2-TR-01 `ERR_VOK_STUCK` latches on the normal post-brake tail | Major | FIXED | Re-keyed on channel disagreement (exactly one channel permits for 50 ms, any state; healthy disagreement at most 23.6 ms) with a secondary both-permit check 400 ms after the 200 ms rule (tail at most 375 ms) (calc5 section 6, Table 16, F15b); validity bound V-MOT decay at least 6.6 V/s pinned by V2-1 and a `static_assert`; tail host test. |
| BT2-TR-02 OR-V 40 ms arm opens the window after pulse 1 ends | Major | FIXED, RULING, GATED | Command-step arm (I_cmd at or below -2 A on two 1 kHz ticks; pin 30 at 5.4-7.4 ms, ahead of VOK at 8.5-16.6 ms, calc5 section 7), ruling OR-V' with the power arm as the recorded alternative; section 7.8 and Table 8a premise stated; S0-6 GO gains the window-open latency term; V2-4 gains a captured-charge criterion; host test pins the latency at 10 ms. Option (b), the charge mode held through coast, is not adopted (it would keep the pack in the charge mode during traction onsets). |
| BT2-TR-03 `ERR_EFUSE_BYPASS` false-latches on hold-up or R_KA | Minor | FIXED, GATED | The detector is the scheduled probe of section 9.7a (T_hold 0.5 s after EF_EN and FF1 L, a feed confirmed by V_chg, a valid reg 0x07 of 64-254); host tests for the regen release and the probe cases; S0-7 records keep-alive I2C behaviour. The "V_chg below 2 V" condition is REJECTED: pin 38 reads the board side of the M2 cut and adds no module-side evidence (verifier). The 50 Hz poll is not a trigger (it runs only while powered). |
| BT2-TR-04 G1 residual mis-specified | Major | FIXED | G1 rebuilt from I_PACK1 at 1 kHz with I_L,cal and eta_cal; written error budget (0.28 A uncalibrated, calc5 section 8); working I_G1 0.35 A; blanking until the first valid Charging read plus two polls; note 2 withdraws the sub-D5 claim; host test over the voltage, efficiency, floor and ramp corners. Only I_batt carries the INA253 floor (verifier correction). G2 gains the I_L,cal term. |
| BT2-TR-05 Regen exit cannot de-energise the module before the re-bond | Minor | FIXED, GATED | SRC = (VOK AND p30) OR FCQ (U_RS); every commanded exit drops the feed, waits T_drain 2 ms, then sets pin 33 LOW (sections 9.5-9.7, 9.9, 12.4 item 3); traction delay restated (about 6 ms at p99); S0-11 measures run-on, S0-13 exit cases for Stages 1-2. |
| BT2-LS-01 D-BC-FC short gives a one-fault loop in every regen window | Major | FIXED | `ERR_VCHG_FED` (as FM2-7) detects the short before any window and is a regen- and FC-window entry precondition; F17 no longer "Benign"; note 1 and HR3 restated as conditional on `ERR_VCHG_FED`; host tests. Threshold 11 V (the verifier's recommendation) in place of the finding's 9 V. |
| BT2-LS-02 State-99 skip range removes the motor zero, bus opens and MOT_PWR LOW | Major | FIXED | Section 9.9 step 3 names exactly the three removed statements (ino:8316, ino:8323-8324) and keeps every other phase-0/1 statement in order; host test checks the write-log order (motor 0 A, FC_BUS, BT_BUS, MOT_PWR LOW before any `*_REG_ENABLE` LOW) from Run and both window types. |
| BT2-LS-03 FC window reachable in Run cruise; pin 30 has two owners | Major | FIXED, RULING | FC windows and configuration checks only in State 1 or 98 with the motor command 0; cruise branch compiled out (12.2 item 5); exit on any non-zero motor command or a State 1 to 2 request with the VESC held at 0 A; mode manager the sole writer of pin 30 (bare writes at ino:15308, 15375, 15395, 15524 removed under the flag); no direct FC-to-regen transition (OR-7); host tests. OR-O reworded. |
| BT2-LS-04 Module input capacitance keeps converting after the bond | Minor | FIXED, GATED | As BT2-TR-05; section 1 no longer claims "unpowered by construction" for the exit interval; F10 bounds the hardware-trip case (at most about 24 mJ, calc5 section 10). The Stage-3 dump in Stages 1-2 is not adopted: T_drain covers commanded exits without new parts. |
| BT2-LS-05 eFuse bypass latent in service; cut then depends on RT1987 turn-off | Minor | FIXED, GATED | The eFuse-blocking probe (section 9.7a) is the in-service test the finding proposed; `ERR_VCHG_FED` covers the upstream-switch half; the RT1987 turn-off remains open item 2 (V2-2). The VCHG-IN_M comparator alternative is REJECTED for the reason given under FM2-7. |
| BT2-LS-06 Slow 3V3 collapse gives bonded with the eFuse enabled | Minor | GATED | Row F45; HR5 restated as proven for absent rails only; gate B11d (10 ms ramp inside an FC window) with a 3V3 supervisor as the NO-GO action. |
| BT2-LS-07 Run command during the self-test | Minor | FIXED | Merged with FM2-9: the State 1 to 2 transition and any motor command wait for the abort's bonded settled reading; a charge-mode step that sees more than 0.5 A aborts (deferred) instead of failing; host test. |
| DS2-1 eFuse start into an overload: 2.3-2.9 s of thermal regulation with FLT not asserted | Major | FIXED, GATED | New comparator U_IM on IMON (trip 1.68-1.75 A of eFuse input, above the 1.37 A largest legitimate input and below I_OL 1.82 A, calc5 section 9) clears FF1 through N1 (Fig. 2); section 7.5, Table 11, the U_EF row and HR4 restated (three overload cases; fast trip 3 x I_OL, active; FLT after tCB_FLT 22-30 ms for the TPS26631, the verifier's correction of the finding's 1.6 ms); gate S0-12b (one-shot and at the regen cadence; GO within 5 ms). The finding's threshold "about 1.6 A" is moved to 1.71 A to clear the 1.37 A regen input at efficiency 0.80. |
| DS2-2 EF_FLT_N is not power evidence | Minor | FIXED, GATED | `chargerHasPower()` adds V_chg at or above 13.5 V on two settled iterations (12.5 item 1); EF_FLT_N compared only while EF_EN is H and outside the entry mask, with the CSS 5.6 nF dependency stated (12.4 item 4); C-2 scopes FLT on the SHDN-low decay (the verifier's adjacent case, UNCONFIRMED in SLVSE94G). |
| DS2-3 TPS26631PWPR and INA240A3PWR availability | Minor | FIXED | Section 16 records the 2026-11-07 figures as UNCONFIRMED (the verifier could not re-read them); TPS26636PWPR approved alternate with its differences (1 x limit, OV clamp at 35.7-39 V above the Ag105 36 V maximum, acceptable at a 21.5 V input); INA240A3 in SOIC-8; CSD18510Q5BT. |
| DS2-4 Cited figures outside their primaries | Minor | FIXED, GATED | BQ29200 CD delay marked BENCH with the section 7.5 citation and a BG-17 measurement (0.1 uF replacement as the NO-GO action); TLV3011B 4 us t_PD marked as the push-pull figure; F2 and section 7.6 use the 1.5 V LM1084 dropout at every load; U_PD IOH overdrive recorded; SCES794G and the INA240 series-resistor error (0.073 %) closed. Raising R_P1 to 680 Ohm is REJECTED for this revision: it needs the pump hold re-derived, and the overdrive is a first-edge transient of about 10 mA. |
| BT2-AG-1 `ERR_ISO_MISMATCH` false-latches when the module output is zero | Major | FIXED | Signed comparison in GENSTAT Charging (CC or CV set) only; a Fully Charged form; 200 ms blanking after a GENSTAT change; never with pin 32 LOW (Table 16). Settings readbacks are valid on any status byte other than 0xFF and reg 0x02 = 0xFF is compared raw (12.5 item 2), which also removes the verifier's adjacent finding that no reg 0x02 readback could ever be valid. Host tests for Fully Charged, input-limited and pin-32-LOW cases. |
| BT2-AG-2 `ERR_EFUSE_BYPASS` assumes no I2C ACK without input | Minor | FIXED, GATED | Criterion moved from an ACK to a valid reg 0x07 of 64-254 (section 9.7a, Table 16); S0-7 acceptance record (60 s poll with R_KA, error-clear behaviour, MPPTD and I2C back-power). The TLV3011B on VCHG-IN_M is REJECTED: reg 0x07 observes the module input over the existing bus. |
| BT2-AG-3 One spare module for stress and qualification | Minor | FIXED | Two units (X stress, Q qualification) in sections 14.1 and 15.2 (D-3(a) reworded: the fitted unit has run no stress gate; serial and gate log recorded; "same lot" hedged as TODO(verify)); the D-3(b) reference is taken on unit Q before any stress gate; Table 18 budgets two or three modules. |
| BT2-AG-4 S0-2 does not fix the R_KA state or reach every sub-state | Minor | FIXED, GATED | S0-2 run as an {R_KA} x {LD} matrix with a programmable simulator profile; unreachable sub-states recorded, not failed; new S0-2b input-cycling gate; optional rig fast trip. The finding's statement that R_KA holds the sense-parallel switch is UNCONFIRMED (verifier). |
| BT2-AG-5 eFuse off treated as charger unpowered at every exit | Minor | FIXED, GATED | As BT2-TR-05 and BT2-LS-04 (T_drain; F10 bound; S0-13 exit cases without C_HU). |
| BT2-BM-01 Shared Kelvin path blinds both channels | Major | FIXED, GATED | As FM2-3. The cracked-Kelvin-joint half is an open input (F21, output undefined), not a guaranteed zero (verifier); F21 now names `ERR_IPACK_PLAUS` for outputs that settle near zero. |
| BT2-BM-02 BQ29200 OUT fly-wire fails open toward no OVP | Major | FIXED, GATED | R_OVP 1 MOhm to 3V3 (Fig. 2, Table 7): intact wire holds the gate at about 6 mV (30 uA sink at 0.05 V, SLUSA52C 7.5); open wire holds N1 LOW (detected at step 4 and entry); F25 restated (a short to GND remains latent); BG-17 extended (open-wire test, CD delay, VDD-absent state); M8 staking. |
| BT2-BM-03 VBUS tap on an MLCC; no mechanical specification | Minor | FIXED, GATED | Channel-2 VBUS tap moved to a VBUS via or exposed copper (M7, Fig. 4); section 5.7 Mechanical (SB enclosure and clamps, LB mounting, staked and looped stranded leads); gate C-4 after the first drive; row F46. Moving R_Bk1a to LB is REJECTED: it would remove the tap-end current limit (0.16 mA into a chafed lead) that F29 relies on (verifier). |
| BT2-BM-04 LB cannot be placed next to J1/J2 | Minor | FIXED | Table 3 and section 5.7: LB as a mezzanine or chassis board, maximum tap and cable lengths, C_N1 tolerance 668 pF (`calc/verify_lb_placement.py`) measured at C-2. The finding's C_N1 margin concern is refuted at that tolerance; the turn-time claim was already a TODO (verifier). `calc/verify_ff1_set_race.py` (pre-revision-4 R_CK) is superseded by calc4 section 6. |
| BT2-RO-01 OR-V arm opens after the first pulse | Major | FIXED, RULING, GATED | As BT2-TR-02. |
| BT2-RO-02 Stage 2 depends on an OR-P configuration check | Minor | FIXED, GATED | As FM2-8. The EEPROM-persistence alternative is left to the OR-P ruling; the Ag105 tables give no module-identity register, so a module swap would go undetected (TODO(verify: Ag105 DS)). |
| BT2-RO-03 HR2 overstated: FC windows 0 % of a drive cycle | Minor | FIXED | OR-O reworded (0 % in a drive cycle; the State-2 standstill window recorded as a separate option); section 9.7 uses State 1 or 98; HR2 row; charge_goal ignored in Run and reported (OR-H). The 0.95 A and 0.000 A figures are REJECTED: `FC_CHG_COOLDOWN_MS` applies only after the 30 s dwell close (ino:15473-15480), so 1.14 A stands (`calc/verify_hr2_cooldown.py`); without R_KA the parked figure is about 0.14 A at a 7.4 V Bring-Up end. The cooldown exemption is REJECTED as already the behaviour of the code. |
| BT2-RO-04 Doctrine reversals and CSV amendments missing | Minor | RULING | OR-G extended to rows 28, 30 and 31 and pin 20; new ruling OR-W (FC_CHARGE_ALLOWED 1 for the standstill window; the CLAUDE.md section 3 reversals); OR-H names the `I_charge` change. |
| BT2-RO-05 Change-set size low; inventory incomplete | Minor | FIXED | Section 12.12 restated against the git history (4,000-7,000 `.ino` lines, 800-1,500 checks, UNCONFIRMED) and extended with the Pi EMS, the HIL charge scenarios, the tool mirrors and the documentation. |
| BT2-RO-06 Recommend Stage 1 as the end state; defer M5 | Minor | FIXED, RULING | Section 1, 14.2 and OR-A/OR-T: Stage 0 plus Stage 1 is the first build and end state until the Stage-2 evidence exists; M5, the VOK channels and the D-BC-RG clamps move to Stage 2 (Table 6, Fig. 4, eq. 10, Table 13); Stage-2 firmware is written only after S0-6. |

The following findings change the HR status of section 13: FM2-7 and BT2-LS-01 (HR3 now conditional on `ERR_VCHG_FED`;
a D-BC-FC short is a one-fault path without it), BT2-TR-02 and BT2-RO-01 (HR1: first-pulse capture restored in
principle by OR-V'; the [RER] alternative fails ruling 1), DS2-1 (HR4: the eFuse time bound does not hold for a start
into an overload; U_IM added), FM2-3 and BT2-BM-01 (HR4: F44 stated), FM2-10 (HR1/HR4: the 2.5 A output ceiling is
conditional on I_L), BT2-RO-03 (HR2: 0 % during a drive cycle) and BT2-LS-06 (HR5: proven for absent rails only).

## Appendix D. Battle-test round 3 adjudication

Battle-test round 3 produced 25 findings: 2 blockers, 12 major and 11 minor at their verified severity. The lenses were
the FMEA lens (FM3-1 to FM3-4, `calc/fmea_round3_calcs.py`) and the transient, logic, datasheet, Ag105, buildability
and requirements lenses (BT3-*, DS3-*; `calc/bt3_*.py`). Every blocker and major finding was verified independently; no
finding was refuted in full. Five findings were confirmed at a lower severity than filed or only in part (FM3-3,
BT3-TR-02, BT3-LS-01, BT3-AG-2, BT3-AG-3). The dispositions have the meanings of Appendix B. Rejected parts of otherwise
adopted findings are named in the last column, with the evidence.

Table D1. Battle-test round 3 adjudication.

| Finding | Severity (verified) | Disposition | What changed |
|---|---|---|---|
| FM3-1 D_VM short is an unfused short of cell 1, surged by the event it protects | Blocker | FIXED, GATED | D_VM deleted; clamps D_VC1 (GND to VC1) and D_VCB (GND to VC1_CB) at the BQ29200 pins, behind RB3 and RB1A (M16, Tables 4 and 7). A clamp short draws at most 16 mA (RB3) or 42 mA (RB1A, 176 mW in a 0.125 W part, which may open: benign); a pack-negative open passes at most 58 mA, so the TPS61288 cannot draw its input current through the balance lead (calc6 section 1). Rows F34b (the S_GND body diodes conduct in the fault direction, so S_GND is not an actuator) and F47; B-PKN extended with a pack-negative open on the pack with both boosts running and with a 5 A board load; mating-order warning restated. The fused-D_VM alternative is not adopted: it needs three new elements where the pin-side position needs none. |
| BT3-BM-01 D_VM reversed or shorted shorts cell 1 | Blocker | FIXED, GATED | As FM3-1. Gate C-1 checks both clamps in diode mode with the pack absent and before the balance plug is first connected; row F47 covers a reversed clamp (a reversed D_VC1 asserts BQ29200 OVP; a reversed D_VCB drains cell 1 at up to 42 mA). The verifier's V_F caveat stands: the clamp part needs V_F at most 0.25 V at 45 mA (TODO(select), B-PKN); a BAT54 is not assumed to meet it. |
| BT3-BM-02 Pack-negative open in service drives the BT boost input current through D_VM | Major | FIXED, GATED | Removed by the pin-side clamps (at most 58 mA, calc6 section 1); B-PKN part (b) records the clamp and balance-wire currents, the EN-low time and the 3V3 rail with both boosts running. The UV comparator on VBT is not adopted, because the path no longer exists. The verifier's point that the Teensy may not brown out is moot at a 58 mA bound. |
| FM3-2 VBATN_X short to pack positive drives 17-164 A through the module sense | Major | FIXED, GATED | F_VX 4 A fast-acting at the module end on CB (Fig. 6, Table 7); rule C1 restated for both modes (U_C1 cannot open the loop); section 5.7 item 4 sleeve and separation rule (added, not cited); row F48; C-1 and C-4 insulation tests; R_FVX added to the section 12.6 OV_BATT and BQ29200 boundaries (to about 30-54 mOhm and 42-65 mOhm of R_s at an ASSUMED 10-30 mOhm) and to P-M1 and R_chain,min. The verifier's 5 A value is replaced by 4 A: it carries the 2.5 A F38 ceiling with 75 % derating and does not exceed the Ag105 I_DIS of 4 A. The optional second fuse at the S_CHG drain is not adopted (10.8 A2s for the 0.4 ms charge-mode phase against 3306 A2s, verifier). |
| BT3-BM-03 VBATN_X chafe; the U_C1 claim of rule C1 is wrong | Major | FIXED, GATED | As FM3-2. Rule C1 rewritten (VBATN_X is GND-referenced through R_s in the bonded mode); creepage on SB between the S_CHG drain copper and pack-positive copper (TODO(layout)); the same-class chafe onto VBUS or V-MOT near the stubs is covered by F_VX (verifier adjacent finding). |
| BT3-BM-04 M13/M16 pre-heat above the Ag105 100 C storage maximum after D-3 | Major | FIXED, GATED | M13 heat confined to x < 15 mm with the Ag105 case at or below 90 C by thermocouple (Ag105 DS p.19); the new M16 sits at the BQ29200 under the same case limit; section 5.7 item 6: every heated step before D-3, D-3 after the last of them, D-3(b) repeated after any later heating. The verifier's adjacent finding (fitting unit Q is itself a thermal step) is covered by the same rule. |
| BT3-TR-01 `ERR_VOK_STUCK` false-latches on a single-channel assert | Major | FIXED, GATED | The rule is gated by the measured ratio r = (V_rgn/V_bus)/k_idle: a channel that permits while r is below 1.003 for 50 ms latches; a healthy permit needs r of at least 1.0062 and a stuck channel reads 1.000, so no decay rate or plateau defeats it (calc6 section 6, Table 16). The dwell rule and the 6.6 V/s `static_assert` are deleted; `ERR_VMOT_CAL` added; M-R2 is a Stage-2 precondition; V2-1 gains in-band peaks, 8 and 14 V/s decays, a 2 s plateau and the step-down sink-slope capture; host tests. The dwell-only alternative (at least 100 ms) is not adopted: a plateau defeats it. The verifier's correction of "no gate catches this" is noted (V2-4 would show it as a nuisance State 99, not prove it). |
| BT3-TR-02 T_drain does not drain the module | Minor | FIXED, GATED | Dump Q_MD/R_MD keyed to NOT EF_EN, bleed R_MB and the U_MS sense (section 5.3); T_drain becomes a measured wait for pin 8 LOW (cap 10 ms, `ERR_MOD_DRAIN`); every entry, profile change and MPPTD change needs a cold module; every eFuse start is cold, so the warm-restart U_IM case cannot arise; the dump-off interlock is shown (Q_MD off within about 1 us, eFuse slew at most 5.79 V/ms, at most 0.4 mA, calc6 section 3); S0-11 measures the open-input decay and I_q; S0-4 alternates the profile on cold cycles. Rejected part: the "unbounded" hold-up; the eFuse reverse path into the 34 kOhm VCHG-IN bleed bounds it at about 1-2.3 s (verifier). The revision-5 rejection of a Stages 1-2 dump (BT2-LS-04) is reversed. |
| BT3-TR-03 Probe and `ERR_VCHG_FED` blanking sized on the shortest hold-up | Major | FIXED, GATED | The probe precondition is a measured cold module (pin 8 LOW for 20 ms), not T_hold; Q_MD holds the module node below VCHG-IN, so the 1.0 s blanking of calc5 section 5 is valid again, and with Q_MD open R_MB (3.3 kOhm, inside the verifier's 4.0-6.2 kOhm bound) brings the coupled node to 11 V in at most 0.49 s (calc6 section 3); the probe verdict no longer uses reg 0x07, so the measurement-validity conflict disappears; host test with the module as a held capacitor. |
| DS3-2 Probe blind: reg 0x07 reads 0xFF in the probe state | Major | FIXED, GATED | Option (a): module-node comparator U_MS on pin 8 (section 5.3, Fig. 2); the probe latches on pin 8 HIGH with EF_EN L (section 9.7a, Table 16); injected-bypass gate at C-2 and S0-14; V2-6 amended; F11, F35 and F36(M2) carry "no qualified in-service detector" until C-2 passes; S0-7 logs the probe-state status byte and reg 0x07. Rejected part: the rider that a latent bypass plus a D-BC-RG or D-BC-FC fault restores the bonded runaway (that needs three faults; the pair closes a loop only inside a regen window with the sense in circuit; verifier). Option (b) is not adopted (it holds the bus FC-only past the purge budget). The revision-5 rejections of a VCHG-IN_M comparator (FM2-7, BT2-AG-2, BT2-LS-05) are reversed. |
| BT3-AG-1 Probe cannot detect a bypass; no positive control | Major | FIXED, GATED | As DS3-2. Every FC window, configuration check and regen window is a positive control of U_MS (`ERR_MOD_SENSE`); the probe needs no module boot, which removes the verifier's timing defeat. The verifier's pin correction is applied: no spare ADC pin exists, so U_MS drives digital pin 8 after gate P8 (pin 2 as the fallback, a sixth ladder bit as the last resort). |
| DS3-1 U_IM trip not guaranteed below I_OL | Major | FIXED, GATED | R_ILIM 9.09 kOhm to 8.06 kOhm (I_OL 2.06-2.41 A); U_IM 1.51-1.98 A over the IMON gain range and 3V3 3.2-3.4 V, 0.078 A below the I_OL minimum and 0.050 A above the 1.458 A largest input (calc6 section 5); S0-12b a per-unit trim gate at temperature; section 7.5 separates the thermally limited hard short (0.13-0.28 A) from the soft overload; magnitude and power bounds restated (2.41 A, 51.8 W). Rejected parts: the finding's "raise R_ILIM" (I_OL = 18/R_ILIM, so it must fall) and the absolute-REF threshold (ratio 1.273 against 1.248 available); the two-sided hysteresis term (one-sided for a rising trip). All three per the verifier. |
| BT3-LS-01 `chargingControl()` still writes pins 5 and 30 | Major (pin 5); the pin-30 parts are document drift | FIXED | Section 12.4 item 6 lists every write that compiles out (ino:15304, 15308, 15338-15362 including 15357 and 15358, 15375, 15377, 15395, 15524, 15545-15556); item 7 adds chokepoint setters for pins 5, 30 and 31 with a pin-5 refusal; write-log host tests over a 780 ms window at all four 50 Hz phases. Rejected part: the pin-30 hazards (ii) and (iii), which the revision-5 refusal of 12.4 item 7 and the existing host test already block (verifier). The optional evaluation of `ERR_VCHG_FED` against the commanded state is not adopted. |
| BT3-LS-02 Idle-entry self-test fails step 1 on PUMP_OK | Major | FIXED | Step 1 expects PUMP_OK L at boot and H at an Idle entry (the L check is the stop clause of step 2); section 12.3 item 5 reworded; host test of a healthy pass after the State 0 bring-up and after Run. The 430 ms total is unchanged. |
| BT3-RO-01 Stage-2 windows almost never permitted | Major | FIXED, GATED | `ERR_IPACK_PLAUS` re-keyed to 0.4 A BT current and 0.25 A pack discharge (x2.16 margin, calc6 section 8; 19 of 23 sessions pass); configuration check exempt from the 8.0 V gate; regen 8.0 V gate conditional on S0-8b (verifier adjacent finding); availability stated in section 1 and the HR1 row; V2-4 records the fraction of decels that open a window; F44 latency restated. The bag-per-power-cycle assumption stays UNCONFIRMED (it could raise 2 to about 4 of 23); telemetry v6 carries the state word, which closes the verifier's no-mainState gap. |
| FM3-3 Wall-clock 5 ms confirmations false-latch on a long iteration | Minor | FIXED | Confirmations within 4 iterations, persistence over 3 iterations, a 30 ms wall-clock cap (section 7.7, Table 11, Table 16); SD drain and Ag105 I2C deferred on a pin-33 edge iteration; injected 10 ms iteration host tests; iteration histogram at W1 and V2-4. Rejected part: "19.5 ms to a settled reading" (one gap gives 10.89 ms; `calc/fmea_round3_calcs.py` section 3 double-counts the gap, calc6 section 7). The verifier's "whichever is later" deadline wording is replaced by "whichever comes first": a later-of rule would make every deadline 30 ms. |
| FM3-4 `ERR_VCHG_FED` depends on one pin-38 channel | Minor | FIXED | `ERR_VCHG_SENSE` (pin 8 HIGH with V_chg below 8 V, or two VOK pulses with EF_EN H for 20 ms and V_chg never above 12 V) refuses regen windows; a void probe refuses regen windows; row F52; host test. U_MS gives the module-side view that the per-pulse rule needs. |
| BT3-LS-03 LB 3V3 open with the Teensy alive releases the cross-lock and the D-BC-RG clamps | Minor | FIXED, GATED | Pin 32 LOW on `ERR_CHG_LADDER` and in State 99 (Table 12, section 9.9); row F51; event table and HR5 restated for an LB-only rail loss; gate B11e. The clamp-gate bias change is not adopted now; it is the B11e NO-GO action. |
| DS3-3 Ag105 ambient derating not applied | Minor | FIXED, GATED | Section 7.1 states the DS p.17 Table 9 derating as an HR1 condition; GENSTAT 110 in a window exits without a latch and refuses a new window for 60 s (section 12.5 item 4, G3); module case temperature at B8 and S0-6. |
| BT3-AG-2 S0-2 rig cannot resolve its criteria; no positive control | Minor | FIXED | 10 mOhm 4-terminal rig shunt with an INA240A1 or a 0.02 A DC probe, stated bandwidth and averaging, a mandatory fast trip at I_set + 0.6 A (section 14.1); positive control on unit X before unit Q (S0-2). Rejected part: the central claim that a sense-blind module is indistinguishable from a pass; the steady criterion compares reg 0x06 with the shunt, and ML0227 shows reg 0x06 near zero under about 5 A (verifier). The simulator sink limit stays I_set + 0.3 A. |
| BT3-AG-3 Rule C2 scoped to the vehicle only | Minor | FIXED | Rule C2 extended to every Ag105 rig and to D-3(b) (sections 4.2, 14.1); pre-energisation earth check before S0-2, S0-2b, S0-6 and D-3(b); D-3(a) disqualifies unit Q on any recorded module output above 2.5 A; S0-2 records it. Rejected part: the 4.10 A module output, which the rig's own sink and input limits cap at about 2.35-2.82 A (verifier). |
| BT3-AG-4 MPPTD HIGH into an unpowered module; reg 0x01 read once per power cycle | Minor | FIXED, GATED | Pin 5 open-drain (section 12.5 item 3, OR-4, OR-G) with a push-pull plus 10 kOhm fallback decided by S0-7; reg 0x01 read once per regen window (section 12.5 item 2); S0-4 adds the reg 0x01 = 0x05 case; S0-2b runs the per-drive cycle count with register read-backs. A register read at every Idle entry is not possible (the module is unpowered in Idle). |
| BT3-RO-02 OR-V' timing from the retired drive law | Minor | FIXED, RULING | Section 7.8, Table 11, section 9.5, HR1 and OR-V' restated for the fw v37 law (arm 4-26 ms after a decel step); the arm stated as two drive-controller samples (4 ms); latency measured from the first command below -0.1 A in S0-6 and V2-4; re-derivation with `tools/drive_ripple.py` and a v37 decel BLG listed (open item 21, section 14.1); the rate-conditioned arm recorded under OR-V'. |
| BT3-RO-03 Telemetry v5 collides with the R4 v5 and the fw v38 plan | Minor | FIXED, RULING | IC1 layout named protocol v6 on the R4 v5 layout (section 12.9, OR-H); `charger_flags` bits redefined under the flag; section 12.12 item 8 maps the fw v38 items (interlock layers superseded, M-R2 and `LIMIT_V_RGN_MAX` prerequisite, telemetry v5 and BLG v10 absorbed, "charger proven" superseded). |
| BT3-RO-04 Ruling inventory inconsistent | Minor | FIXED, RULING | Stage lists in sections 14.1-14.3 taken from the section 17 column (OR-J at Stage 0; 21 Stage-1 rulings); OR-P and ruling 9 named as the Stage-1 decision points and "bench-supply charger without OR-P" stated; OR-X added for the charge-mode OV_BATT and UV_BATT limits; OR-E extended to a per-fault response table. |

The following findings change the HR status of section 13: FM3-1, BT3-BM-01, FM3-2 and BT3-BM-03 (HR4: two pack-direct
loops outside every revision-5 bound are closed by RB3/RB1A and F_VX), DS3-1 (HR4: the U_IM window is restated with the
IMON gain range and a lower R_ILIM), DS3-2 and BT3-AG-1 (HR3: the eFuse-bypass detector is qualified only by the C-2
injected-bypass gate; until then the two-failure count for an eFuse bypass is one detected plus one latent), BT3-TR-01
(HR3: the VOK disagreement detector no longer depends on the V-MOT decay rate), BT3-RO-01 and BT3-RO-02 (HR1:
availability bounded and the arm latency restated for fw v37), DS3-3 (HR1: 45 C ambient condition) and BT3-LS-03 (HR5:
an LB-only rail loss with the Teensy running is bench-gated).

## Appendix E. Battle-test round 4 adjudication

Battle-test round 4 produced 29 findings: 9 major and 20 minor at their verified severity, and no blocker. The lenses
were the FMEA lens (FM4-1 to FM4-6, `battletest/fmea_round4.md`, `calc/fmea_round4_calcs.py`) and the logic, transient,
datasheet and buildability lenses (BT4-*; `calc/bt4_*.py`). Every major finding was verified independently; no finding
was refuted in full. Ten findings were confirmed at a lower severity than filed or only in part (FM4-2, FM4-4, FM4-5,
BT4-LS-03, BT4-DS-01, BT4-DS-03, BT4-DS-04, BT4-DS-05, BT4-2, BT4-4). The dispositions have the meanings of Appendix B,
with **RULING** for a disposition that an operator ruling of section 17 completes. The revision-7 numbers are in
`calc/ic1_rev7_calcs.py` (calc7).

As in rounds 2 and 3, most round-4 majors were introduced by the previous round's fixes: D_VCB (FM4-1), the Q_MD
dump (FM4-3, BT4-1, BT4-3), the CC-1 anchor (BT4-LS-02), the R6-8 Idle-entry step 1 (BT4-LS-01) and the Stage-3 re-key
(BT4-TR-01). Revision 7 therefore removes parts where it can (D_VCB, D_N20, the Stage-3 circuit), changes values
(RB1A) and moves detection into firmware rules on existing channels (FC_CURRENT, V_PACKN, pin 8). It adds two passive
items only, R_MDS and the VC1 tap divider.

Table E1. Battle-test round 4 adjudication.

| Finding | Severity (verified) | Disposition | What changed |
|---|---|---|---|
| FM4-1 D_VCB short drains cell 1 and lets the top-cell balance switch pull VDD down | Major | FIXED, RULING | D_VCB deleted and RB1A raised from 100 Ohm to 4.7 kOhm (top of the SLUSA52C 7.3 RCB range): no fitted part can ground VC1_CB; a pin-3 solder bridge draws 0.89 mA through RB1A (C-1 checks VC1_CB to GND); the F34b return falls to 16.2 mA through RB3, with at most 0.83 mA into the unclamped VC1_CB (calc7 section 1; VC1_CB absolute maximum TODO(verify: TI), measured at B-PKN). Balancing falls to 0.5-1 mA (ruling OR-AA). The verifier's VMID measurement is implemented as a VC1 tap on pin 20 with `ERR_CELL_MISMATCH` (it also covers BT4-DS-02 and FM4-5). Rejected parts: the plain deletion of D_VCB with RB1A 100 Ohm (36-39 mA into the VC1_CB pin, verifier); pin 9 HIGH on a mismatch, which is no longer needed at a 1 mA balance current. Row F47, Table 7, M16, C-1, B-PKN, BG-17 and the storage warning restated. |
| FM4-3 Q_MD stuck on escapes U_IM and OC_FC and overloads R_MD | Major | FIXED, GATED | `ERR_MOD_DUMP_ON`: FC_CURRENT step above 0.4 A 10 ms after `chargerHasPower()` first turns true at every EF_EN rise of an FC window, configuration check and commissioning (re-anchored from the finding's 20 ms after the EF_EN rise, because D-BC-FC has no t_D_ON maximum) (healthy 23 mA, stuck 1.08-1.19 A, about 0.5-0.6 J before the latch; calc7 section 4); R_MDS 1 kOhm at the U_MDI output; rows F49 and F50 corrected; C-2b item (f) jumpers Q_MD. The H-20 adjacent point (a stuck dump takes a check to 99.7 % of P_MAX) is covered by the same latch. |
| BT4-1 F50 latent in regen windows; R_MD at 12-28 x its mean | Major | FIXED, GATED | As FM4-3 (the verifier's preferred fix). The check runs before the first regen window of every power cycle; a fault that arises during a drive is bounded by R_MD failing open (F49), and Table 7 requires a fail-open part. Rejected part: the series PTC (it lengthens T_drain and its trip under pulsed current is unproven, verifier). |
| BT4-3 C-2 U_MS threshold sub-step overloads R_MD | Major | FIXED | C-2a item 24 runs with MD_G lifted (R_MDG holds Q_MD off) and a 50 mA limit; a section 9.2 warning forbids feeding VCHG-IN_M with EF_EN L. The finding's 5 mA limit is raised to 50 mA (module idle up to 18 mA plus 3 mA of divider and bleed, verifier). |
| BT4-DS-02 A D_VC1 short puts V_pack across the BQ29200 VC2-VC1 (8 V absolute maximum) | Major | FIXED, GATED | Row F47 states the overstress; option (b): the VC1 tap on Teensy pin 20 (R_VC1a 200 kOhm at the VC1 pad, R_VC1b 200 kOhm and C_VC1 100 nF on LB) and `ERR_CELL_MISMATCH`, \|V_BT - 2 V_VC1 + V_PACKN\| above 80 mV for 1 s, independent of the BQ29200 (worst healthy error 41.5 mV, calc7 section 2); the BQ29200 is replaced after the event. Pin 20 is taken from WDOG1_B (D_N20 deleted; the pump and the RTWDOG reset remain; rows F9, F9b, F20, B11b, OR-K). Option (c) is not adopted: any clamp position that holds VC1 above -0.3 V in F34b can short VC1 to GND. |
| BT4-TR-02 R_SH element open puts KS+ beyond the INA240 -6 V absolute maximum | Major | FIXED (statement), GATED, RULING | Section 4.2 item 3 and new row F34c state the -8.4 V exposure on both amplifiers; `ERR_IPACK_PLAUS` gains a two-sided gain band (0.75-1.30 x prediction, healthy 0.82-1.19, calc7 section 10); repair rule (replace U_SH1 and U_SH2 after any R_SH open); B-PKN (c) measures KS+ at the KS connector with LB unplugged, so no gate stresses the amplifiers. Rejected parts: the GND-anode Schottky clamps (they conduct at the normal -1.0 V common mode and carry 1.9-3.7 A through R_K1 in the fault) and the 100 Ohm series resistors (3.23 % gain error, up to 2 A equivalent offset), `calc/verify_f34b_ks_ina240.py` sections 2-3; ruling OR-AB records the choice. |
| BT4-LS-01 Idle entry inside a regen tail fails self-test step 1 and biases k_idle | Major | FIXED | Step 1 checks the CH bits in Stage 1 only; step 10 waits for both CH bits L for 100 ms (deadline 1 s, else "deferred"; a `Q` entry with MOT_PWR LOW defers it); the k_idle mean starts after the settle and excludes samples with a CH bit H or a ratio above 1.01; `ERR_VMOT_CAL` is re-evaluated at every valid k_idle, not latched; host tests for Finish at the peak, Finish 0.2 s later and `Q` in a regen hold. The verifier's corrections (two iterations to Idle; the k_idle half needs an entry within 0.11 s and does not apply to `Q`) are adopted. |
| BT4-LS-02 `ERR_MOD_SENSE` (b) false-latches from the second regen pulse | Major | FIXED | The anchor is the second consecutive V_chg reading at or above 13.5 V after a reading below 13.0 V, all with EF_EN H (verifier's wording); a residual at or above 13.0 V is above the eFuse UVLO and is drained to at most 12.10 V before the feed, and a pulse without a crossing is not evaluated (calc7 section 5); the regen deadline follows the BT4-LS-03 rule; host test with two pulses 0.523 s apart. The other proposed anchors (EF_EN + t_D_ON,max, first pulse only) are not adopted. CC-B8 now names both t_D_ON dependencies. |
| BT4-TR-01 Stage 3 deadlocks every exit into `ERR_MOD_DRAIN` and `ERR_MOD_FED` | Major | FIXED (feature deleted), RULING | Stage 3 withdrawn (section 14.4; Figure 6, Tables 7, 11, 13, rows F37, sections 9.5 and 7.8). The re-key to NOT(FF1.Q AND (P30Q OR FCQ)), the 20 ms Stage-3 drain deadline, C_HU of at least 1.71 mF with R_MB, Q_MD 3 A and R_MD 0.35 J, the C_DV increase and S0-13 are recorded as re-specification conditions (ruling OR-F). The verifier's adjacent items (the tau-15 ms Table 11 row; the 1.5 mF inrush) are removed with the stage. |
| FM4-2 MS-to-SHDN_EF short makes pin 8 follow EF_EN | Minor | FIXED, GATED | Exit hold check (`ERR_MOD_SENSE` (c)): pin 8 sampled 50 us and 150 us after a commanded feed drop, conditioned on a fed window, latch and void the last probe (calc7 section 6); `ERR_VCHG_SENSE` rule (a) evaluated in every mode; the MS lead added to the flying-lead list and routed apart from SHDN_EF with a GND conductor; C-2b item (g) and C-4; row F55; host test. Rejected part: the "HIGH throughout 300 us" check, which false-latches on a healthy board (verifier: a healthy node can fall after 0.248 ms). The 20/60 us samples became 50/150 us to allow for the unspecified open-drain delay of U_MS. |
| FM4-4 Stage-3 re-key contradicts the exit rule | Minor | FIXED (feature deleted) | As BT4-TR-01. |
| FM4-5 D_VC1 hot leakage offsets VC1 and the balancer converts it into imbalance | Minor | FIXED, GATED | D_VC1 I_R at most 40 uA at 4.2 V at T_M16,max (10.4 mV); V_F at most 0.25 V at 16.2 mA over -20 to 85 C (D_VC1 alone carries the RB3 current; the 45 mA requirement left with D_VCB); balancing reduced to 0.5-1 mA, so the conversion into real imbalance has no authority (OR-AA); `ERR_CELL_MISMATCH` sees 2 x the offset; BG-17 measures the hot trip. Rejected part: V_F 0.3 V at 16 mA (zero margin to -0.3 V, verifier). The verifier's adjacent Run-mode offset is moot for balancing and is corrected in the mismatch formula by the V_PACKN term. |
| FM4-6 F_VX open in a window reads as Fully Charged | Minor | FIXED | Row F14 restated; `ERR_CHG_PATH_OPEN` on V_PACKN above I_PACK1 x R_chain,max + 0.1 V or on Fully Charged while V_BT - V_PACKN is below 8.0 V. The finding's "V_batt below 8.0 V" is corrected: V_batt (VBT - GND) reads about 8.4 V in this fault, so the true pack voltage V_BT - V_PACKN is used. |
| BT4-LS-03 10 ms wall-clock drain deadline shorter than the deferred SD/I2C iteration | Minor | FIXED | T_drain,max and the regen positive-control deadline are the later of 10 ms and 4 iterations, capped at 30 ms; with one 9.76 ms iteration the latest healthy read is 12.02-12.44 ms against 13.15-13.78 ms (calc7 section 5); host test extended to `ERR_MOD_DRAIN` and `ERR_MOD_SENSE`. The longer SD/I2C deferral is not adopted (the deadline rule removes the false latch without loading the BLG ring). |
| BT4-LS-04 `ERR_CHG_LADDER` pin-32 LOW has no order against the exit drain | Minor | FIXED | Code 0: pin 32 LOW at once; any other mismatch: the commanded exit first, pin 32 LOW after the bonded confirmation (section 12.4 item 4, section 9.10, Table 16); the CC-7 statement corrected; S0-3 covers both remaining writes; host test. |
| BT4-TR-03 R_MD duty basis ignores the admitted limit cycle | Minor | FIXED | Table 7: R_MD and Q_MD rated for one dump per 79 ms (0.65 W for 30 s) as well as the 1.71 J pulse; open item 17 and CC-B7 updated. The firmware N-release rule is not adopted. |
| BT4-TR-04 Probe current omits the soft-start charge | Minor | FIXED, GATED | Section 9.7a states 2.68-4.13 A peak and 1.23-1.34 A steady; `OC_FC` first counts as a detection; S0-14 and C-2b record which fault fired, once on a BENCH_TEST 0 build. The probe-local `OC_FC` suppression is not adopted. |
| BT4-TR-05 eFuse start into a dumped node can hold V-MOT below the release | Minor | FIXED, GATED | Section 7.2 item 5 includes the start sag; S0-5 and V2-4 record the dumped-node start; the C_DV change is a condition of pursuing Stage 2 harvest. |
| BT4-TR-06 "Every eFuse start is cold" fails on a UVLO drop with EF_EN H | Minor | FIXED | An FC window ends on a V_chg reading below 13.0 V after `chargerHasPower()` (section 9.7), so the next start follows a dump; the rebound-rate residual in regen windows is BENCH (V2-4). The hardware gating of EF_EN on MOD_COLD_N is not adopted (new logic). The 8.69 V drain figure (1.37-3.02 ms) is quoted in Table 11. |
| BT4-DS-01 D_VC1 leakage at temperature; VC1_CB has no absolute maximum | Minor | FIXED, GATED | As FM4-5 (the verifier's 40 uA / 10.4 mV budget; the 2 mV budget is infeasible with any part that meets the V_F limit); the SLUSA52C 7.1 citation for VC1_CB is replaced by TODO(verify: TI); B-PKN at the coldest ambient; BG-17 hot trip. |
| BT4-DS-03 Pin 8 may still carry the encoder phototransistor | Minor | FIXED, GATED | Gate P8 rewritten (5 V leg, DC level, chain non-continuity, pad-to-J1 continuity, two slot transitions each way); fallback pin 2 stated with its shared history and the RENC2-removal bodge or the sixth ladder bit as operator choices; open item 22 extended. Rejected part: "very likely" (the 2026-08-16 bench record shows the pin-8 ISR silent after the reroute, verifier). |
| BT4-DS-04 Open R_MS2 overstresses U_MS IN+ | Minor | FIXED (statement) | Section 5.3 item 3 and new row F56 state the overstress and its F10-class bound (about 24 mJ); no clamp is added, because harm needs a second event and the next positive control catches a U_MS that fails LOW (verifier). |
| BT4-DS-05 F_VX specification omits the interrupting rating | Minor | FIXED | F_VX: at least 32 V DC, at least 300 A DC interrupting, at most 30 mOhm cold, melting I2t recorded; candidate Littelfuse Nano2 451/453 4 A (TODO(verify: datasheet rev GD)); prospective 252-297 A at R_int 0 (calc7 section 8). Rejected part: the 3.4 x shortfall, which compared a rating at 125 V (verifier). |
| BT4-DS-06 TPS26636 does not share the TPS26631 overload and OV behaviour | Minor | FIXED | Section 7.5 and Table 7 state the alternate's 1 x limit, unstated fast trip and OV clamp; S0-12 qualifies the fitted part. |
| BT4-DS-07 Six parts unselected; stock; small corrections | Minor | FIXED (in part) | U_MS unpowered state HIGH (SBOS300C 9.4.5; open item 19 closed); CMRR term in the U_MS window (8.67-9.17 V, calc7 section 7); R_MD candidate CRCW2512-HP; Q_MD requirement row; MPPTD remains S0-7 dependent; TPS26631 stock UNCONFIRMED with a confirm-before-order rule. The parts stay TODO(select). |
| BT4-2 C-2 sub-items need a fed module before commissioning | Minor | FIXED | C-2 split into C-2a (Table 19, unpowered, one GO each) and C-2b (fed, after commissioning, pin 32 LOW); C-1d and P-M1 added to the commissioning step-1 prerequisites; the commissioning exit is recorded. The S_CHG/S_GND overlap stays in C-2a, because it needs only mode toggles (verifier). |
| BT4-4 M16 clamp pads on solid pours 2.2 mm from the Ag105 | Minor | FIXED | M16 gives the BRD coordinates, D_VC1 across CBL2, R_VC1a on the RB3 VC1 pad, and the underside-preheat-plus-iron method with a shield and the 90 C case limit; the silkscreen edge (y 32.84 mm) is named. D_VCB is deleted, so its routing across VC1 no longer arises. |
| BT4-5 Section 15.2 order labels | Minor | FIXED | Section 15.2 retitled and ordered D-1, D-2, B2, BG-17, B13, P8, JBL, rework, P-M1, D-3; D-3(a) repeats the on-board S0-1 and S0-2 after M1/M2 on unit Q. |
| BT4-6 CC-B15 is closed by the firmware | Minor | FIXED | CC-B15 closed citing ino:7463-7466; recorded as not required in Idle. |

The following findings change the HR status of section 13: FM4-1 and BT4-DS-02 (HR4: the balance-lead bound falls from
58 mA to 16.2 mA, and a clamp short is detected independently of the BQ29200), FM4-3 and BT4-1 (HR4: a stuck dump is
detected before the first regen window of a power cycle; the revision-6 U_IM claim was false), BT4-TR-02 (HR4: an R_SH
element open stresses both pack-current amplifiers; ruling OR-AB), BT4-TR-01 (HR1: the hold-up lever is withdrawn) and
BT4-LS-01, BT4-LS-02, BT4-LS-03 (availability: three false latches on healthy boards removed).

**What a later review must check on the revision-7 changes.** The rounds so far show that each fix can carry the next
blocker; the following items are where to look first.

1. **RB1A 4.7 kOhm and the unclamped VC1_CB.** The BQ29200 behaviour with RCB at the top of its range (OUT timing note
   of SLUSA52C 7.3); the VC1_CB pin structure under 0.83 mA of negative injection (no absolute maximum in 7.1); a pin-3
   solder bridge, which still lets the top-cell switch draw VBAL+/(100 Ohm + RCB2) from VDD (gate C-1 is the only
   check).
2. **The VC1 tap.** The 11 uA load on VC1 through RB3 (2.9 mV into the OVP budget); pin 20 input leakage against a
   100 kOhm source (open item 24); a tap-lead chafe (at most 42.5 uA, 11 mV); pin 20 behaviour during reset and with
   the Teensy unpowered (VC1 behind 200 kOhm); the mismatch error budget and the 80 mV threshold against real pack
   imbalance (nuisance window refusal).
3. **Pin 20 reassignment.** The loss of WDOG1_B (the pump and the RTWDOG reset remain; B11b); any firmware that still
   routes WDOG1_B to pin 20 would drive the tap node.
4. **R_MDS.** Q_MD gate charge through 1 kOhm (turn-on and turn-off times against the 1 us dump-off interlock of
   section 5.3 item 1).
5. **Firmware rules.** The `ERR_MOD_DUMP_ON` sample (10 ms after `chargerHasPower()`; revision 7 printed '20 ms' here) against the eFuse inrush and any added input capacitance;
   the `ERR_MOD_SENSE` (b) crossing anchor when t_D_ON is short (no below-13.0 V read: the pulse is not evaluated);
   the 50/150 us exit hold check inside an iteration (busy wait of 150 us); the deadline rule against the 30 ms cap;
   the two-sided `ERR_IPACK_PLAUS` against real efficiency spread; the FC-window exit on a UVLO dip; the step-10
   settle deadline after a `Q`.

Table E2 lists the completeness-critic items that revision 7 closes. The CC-B table marks each one.

Table E2. Completeness-critic items closed or listed in revision 7.

| Item | Disposition |
|---|---|
| CC-B1 | Listed as ruling OR-Z (configuration-check trigger) |
| CC-B2 | Listed as ruling OR-Y (regen windows in State-98 profiles) |
| CC-B5 | Closed: the `static_assert` is specified (section 12.10) |
| CC-B9 | Closed: gate C-2a, one GO per sub-item (Table 19) |
| CC-B10 | Closed: B13 consumer and S0-8 criterion stated |
| CC-B12 | Closed: `CHARGER_STAT` logged only (section 12.5 item 5) |
| CC-B13 | Closed: section 9.9 non-blocking phase-0 sub-step, host test |
| CC-B14 | Closed: gate C-2a item 26 |
| CC-B15 | Closed: ino:7463-7466 |

CC-B3, CC-B4, CC-B6, CC-B7, CC-B8 and CC-B11 remain open.

## Appendix F. Battle-test round 5 adjudication

Battle-test round 5 produced 22 findings: 8 major and 14 minor at their verified severity, and no blocker. The lenses
were the FMEA lens (FM5-1 to FM5-5, `battletest/fmea_round5.md`, `calc/fmea_round5_calcs.py`) and the logic, transient,
datasheet and buildability lenses (BT5-*; `calc/bt5_*.py`). Every major finding was verified independently; no finding
was refuted in full. Four findings were confirmed at a lower severity than filed or only in part (FM5-3, BT5-TR-02,
BT5-BO-01, BT5-BO-04). The dispositions have the meanings of Appendix B, with **RULING** for a disposition that an
operator ruling of section 17 completes. The revision-8 numbers are in `calc/ic1_rev8_calcs.py` (calc8).

As in rounds 2-4, most round-5 majors were introduced by the previous round's fixes: the exit hold check of R7-7
(FM5-1, BT5-LS-01, BT5-TR-01), the FC-current step of R7-3 (BT5-LS-02), the VC1 tap of R7-2 (FM5-2, BT5-BO-02) and the
D_VC1 specification of R7-1 (BT5-DS-01). Revision 8 therefore re-keys the two firmware rules on facts read at the
moment they matter, restricts the dump check to the one session type in which its premise holds, turns the D_VC1
conflict into a stated ruling, and adds hardware only where a firmware rule cannot help: four passive series resistors
at the LB end of flying leads.

Table F1. Battle-test round 5 adjudication.

| Finding | Severity (verified) | Disposition | What changed |
|---|---|---|---|
| FM5-1 `ERR_MOD_SENSE` (c) false-latches between regen pulses and on the probe feed drop | Major | FIXED | Table 16 (c) and section 9.5 exit step 1: the check runs only when, in the write iteration and immediately before the write, EF_EN (raw ladder A) reads H, pin 8 reads HIGH and has read HIGH for at least 2 ms in the current EF_EN-H interval, and V_chg reads at or above 13.5 V; the probe feed drop (section 9.7a step 5) is excluded by name. Exposure between pulses falls from 21.4-37.0 % per exit to 0. The finding's proposal to drop the V_chg term is **not adopted** (verifier): with EF_EN H and the eFuse in UVLO the node at 9.3-9.5 V falls in 21-117 us (calc8 section 1). The 2 ms term is added beyond the verifier's fix: it excludes an exit taken while the eFuse output still ramps through the U_MS edge. F55 is still caught at the first dump check, configuration check or FC window. Host tests and C-2b (g) cases added. The 3-exit probability lower bound reads 0.62, not 0.58 (verifier). |
| BT5-LS-01 Same defect (logic lens) | Major | FIXED | As FM5-1. The verifier's freshness point (a fresh read, not the settled value) is adopted. |
| BT5-TR-01 Same defect (transient lens) | Major | FIXED, GATED | As FM5-1. The C_mod lower bound is adopted in S0-11: at least 47 uF, at which the healthy hold from 13.4 V is at least 170 us at 22.7 W input (calc8 section 1; the DD's 1.0 A estimate gives 59.8 uF, `calc/bt5_transient_sim.py` section 2); below it the 150 us sample is dropped after C-2b (g) measures the hold. C-2b (g) now also runs at an FC-window exit with pin 32 HIGH. |
| BT5-LS-02 `ERR_MOD_DUMP_ON` false-latches every FC window when the Ag105 starts fast | Major | FIXED | The rule is evaluated only with pin 32 LOW (dump check, configuration check, commissioning), where the module input is at most about 9 mA whatever its start speed; both readings are 4-iteration means; a dump-check pass in the power cycle (new section 9.7b) is a precondition of every window. In FC windows the sample is removed: a dump that sticks later is bounded by `OC_FC` (FC bus at least 1.68 A against 1.4 A, BENCH_TEST 0) and U_IM (eFuse input 1.53-2.16 A) while the module charges (calc8 section 2). The verifier's residual form (option b, predicted charger input) is **not adopted**: its 0.4 A margin rests on an efficiency calibration, and `OC_FC` already covers the charging case. Residual: a stuck dump with the module Fully Charged carries 17-20 W in R_MD until the Fully-Charged exit; on a BENCH_TEST 1 build only U_IM and the bench supply limit act (row F50). |
| BT5-TR-02 Same timing contradiction (transient lens) | Minor (lowered) | FIXED | As BT5-LS-02. The baseline noise point is answered by the 4-iteration means (margin 0.168 A, calc8 section 2). |
| BT5-TR-03 Stuck dump trips U_IM or I_OL at the eFuse start; F50 and C-2b (f) wrong | Minor | FIXED | Row F50 restated (U_IM or the start into overload on most corners; `ERR_MOD_DUMP_ON` covers the residual corner); C-2b (f) GO accepts `ERR_MOD_DUMP_ON` or `ERR_CHG_TRIP` with the U_IM attribution recorded; Table 7 R_MD and section 5.3 item 1 corrected. |
| FM5-2 VC1 tap lead lands on pin 20 with no LB-side series element | Major | FIXED (hardware added), GATED | R_VC1c 22 kOhm at the LB entry, R_VC1b on the lead side, C_VC1 on the pin side: a chafe to 8.5-21.5 V injects 0.22-0.81 mA (calc8 section 5); the DC ratio is unchanged and the tap filter becomes 12.2 ms. The same rule for the MS lead (R_MS3 22 kOhm, C_MS on the lead side, threshold and timing unchanged), BAL_OK (R_BL3 47 kOhm, R_BL2 82 to 100 kOhm) and PROFILE (R_PGL 22 kOhm). Rows F54 (42.5 uA corrected to the VC1 drain), F54b, F54c; section 5.7 item 4 adds the LB entry rule and two signal sleeves; C-1 and C-4 insulation tests. Injection limits TODO(verify), open item 29. A BAT54 clamp at pin 20 is **not adopted**: its leakage enters the mismatch budget at 0.488 V/uA. |
| BT5-BO-02 F54 false; same topology on MS and BAL_OK | Major | FIXED (hardware added), GATED | As FM5-2. The verifier's adjacent audit of the other LB-bound leads is done in section 5.7 item 4: IMON (R_IMF 10 kOhm, existing), SHDN_EF and MD_G (driven outputs behind 1 kOhm, at most 18 mA into the LVC clamp), PROFILE (R_PGL added), EF_FLT_N (no series element; segregation only, row F54c). |
| BT5-DS-01 D_VC1 specification is physically unsatisfiable | Major | FIXED (statement), GATED, RULING | Table 7 states the two endpoints and their conflict: under the x2 per 10 K rule the 40 uA limit holds only up to T_M16,max of about 44-59 C at T_min -20 C and 63-76 C at T_min 20 C (calc8 section 3). The 'leaves room' claim is withdrawn. Selection waits for B8 (T_M16,max) and ruling OR-AC (T_min and the fallback: TI injection rating, a wider budget with matching BG-17b and mismatch limits, or an active clamp). The `ERR_CELL_MISMATCH` latch leakage is 114 uA (153 uA with the other terms at zero), not 75 uA. |
| FM5-3 D_VC1 specification contradicts itself over temperature | Minor (lowered) | FIXED, RULING | As BT5-DS-01. The verifier's correction of the cold-side claim (a hot-capable part stays inside -0.3 V at 85 C for barriers below 0.55 eV) is recorded; the RB3 option is **not adopted** (the error is independent of RB3 at a fixed V_F limit, `calc/verify_dvc1_two_endpoint.py`). |
| BT5-BO-03 C-2a item 5 injects the F47 overstress with no pack-voltage limit | Major | FIXED | Item 5 rewritten (verifier's wording): pack at 7.4 V (0.6 V margin to the 8 V VC2-VC1 maximum), cell-simulator connection stated (common to PACK-, J-BL position 3 removed), the D_VC1-short case injected by grounding the R_VC1a/R_VC1b junction on LB (VC1 sag 5.5 mV, calc8 section 7). BG-17b is repeated after any F47 event or injection; row F47 bounds the replacement rule to V_pack above 8.0 V. |
| FM5-4 Mismatch budget assumes a pin-25 calibration that no gate performs | Minor | FIXED | C-2a item 5 calibrates pin 25 against the same DMM; the calibration is a stored per-board constant (section 12.12 item 2); host test at 3V3 3.20 and 3.40 V. |
| FM5-5 `ERR_IPACK_PLAUS` gain band uses an ambiguous I_L,cal and no dwell | Minor | FIXED | Separate constant I_NB,cal (non-boost VBT load, C-2a item 28); the band compares 1 s means; healthy ratio 0.84-1.19 (calc8 section 6); host test with the B8 I_L,cal stored at 0.6 A. |
| BT5-LS-03 Idle-entry self-test not ordered after an unfinished exit | Minor | FIXED | Section 12.4 item 8 and section 9.3: `CHG_SELFTEST` is entered only from `CHG_BONDED` after `CHG_EXITING` has written pin 5; an Idle entry during an exit queues it; host test with a Finish inside an open regen window. |
| BT5-TR-04 Regen-pulse model omits the VESC-stop tail | Minor | FIXED | Sections 7.8, 9.5, 12.5 item 2(b), section 1 and HR1 state the powered interval as 84-416 ms per pulse; the F1/F19 hardware-only statement now rests on `ERR_ISO_MISMATCH` being an FC-window rule (its extension into regen windows is a Stage-2 option after V2-4); the reg 0x01 readback can be valid inside the tail. |
| BT5-DS-02 B-PKN drives the unrated VC1_CB pin below -0.3 V | Minor | FIXED, GATED | B-PKN (a) and (b) run on the vehicle board with RB1A.2 lifted until a TI rating exists; RB1A is refitted and checked at C-1 afterwards. |
| BT5-DS-03 F_VX data mixes the 4 A and 5 A rows | Minor | FIXED | 16.0 mOhm, 2.469 A2s (8 ms) and 400 A at 32 VDC from the 4 A row, as read in this finding (Littelfuse 451/453 rev GD); re-read at order. The item-20 reverse pulses reach at most 5.4 % of the melting I2t (calc8 section 7). |
| BT5-DS-04 R_MD rated on the single-pulse curve (n < 1000) | Minor | FIXED (basis), GATED | Table 7: the repetitive dump is rated on the doc 20043 continuous-pulse curve; the single-pulse curve covers only the probe-cap and stuck-on events; both curve points TODO(verify: Vishay); CC-B7 narrowed. |
| BT5-BO-01 Pin-20 keeper and leakage against the 80 mV budget | Minor (lowered) | FIXED (statement), GATED | The keeper half is refuted (Teensy core 1.62.0 `analogRead()` clears PKE, analog.c lines 111-119); section 12.3 item 1 says so. The leakage half: a 0.488 V/uA term (79 nA allowed with R_VC1c) enters the Table 16 budget, C-2a item 5 records hot and cold readings, and the threshold is set from them; a CMOS follower is the recorded fallback (open item 24). INPUT_DISABLE is **not adopted** (not the mechanism, verifier). |
| BT5-BO-04 C-2a item 20 reverse-stresses unit Q and F_VX | Minor (lowered) | FIXED | Item 20 runs at 1 and 3 A only (at most 3.5 A; 0.133 A2s worst against 0.1445 A2s, calc8 section 7); D-3 gains a voiding rule for any later reverse current above 3.5 A or I2t above 0.1445 A2s. The F_VX ageing claim is refuted (5.4 % of the melting I2t). The F22b omission of R_FVX is benign (+0.11-0.21 V at 7 A, verifier) and is not re-derived. |
| BT5-BO-05 BG-17 precedes the rework but needs D_VC1, M8 and LB | Minor | FIXED | BG-17 split: BG-17a before the rework, BG-17b after M8, M16 and LB; commissioning step 1 names both. |
| BT5-BO-06 M16 solders D_VC1 onto the CBL2 terminations | Minor | FIXED, GATED | M16 replaces CBL2 with a new part and solders D_VC1 to the exposed pad copper, not to the terminations; the GND via beside RB3.2 is masked; C-1 reads VC1 to GND by resistance in both polarities (ohms to kilohms for a crack or bridge, megohms for D_VC1 leakage); row F47 names the cracked CBL2 as a cause. Moving D_VC1 to RB3.2 is **not adopted**: RB3.2 already carries R_VC1a. |

The following findings change the HR status of section 13: FM5-2 and BT5-BO-02 (HR4 and HR5: a chafed signal lead no
longer forces a pack or bus voltage onto the MCU or the LB logic that implements the hardware trips), BT5-LS-02 (HR4:
the stuck-dump detection moves to the dump check and to `OC_FC`/U_IM in FC windows), BT5-TR-04 (HR1: the tail can carry
charge, BENCH) and FM5-1, BT5-LS-01, BT5-TR-01, BT5-LS-02 (availability: two false latches on healthy boards removed,
one of which voided every healthy probe).

**What a later review must check on the revision-8 changes.**

1. **R_VC1c and C_VC1 on the pin side.** An open R_VC1c leaves pin 20 on C_VC1 and pad leakage: the reading drifts
   rather than jumping, so the time to an `ERR_CELL_MISMATCH` latch is not bounded; the 12.2 ms tap tau against the 1 s
   persistence; the pad injection limit (open item 29).
2. **R_MS3.** An open R_MS3 leaves U_MS IN+ floating: the output can read LOW (the positive control catches it), HIGH
   (`ERR_MOD_SENSE` (a) or `ERR_MOD_DRAIN`) or chatter; the chatter case is not analysed. The F55 short now joins
   SHDN_EF to the lead node ahead of R_MS3; the exit hold check timing with the IN+ capacitance behind 22 kOhm.
3. **R_BL3 / R_BL2 100 kOhm.** BAL_OK at 7.4 V is 2.49 V against the LVC VIH of 2.0 V, with up to 0.33 V of input-leakage
   offset through the 66 kOhm Thevenin source (TODO(verify: TI SN74LVC244A)).
4. **R_PGL.** It sits only on the PROFILE lead to CB; the LB injection gates Q_I1b and Q_INV stay on the pin-10 net.
5. **Dump check (section 9.7b).** One more FC-fed session per power cycle before the first FC window: its feed, its
   interaction with the purge-free permit, the D5 arming with the BT handoff, and the pin-32 LOW/HIGH cycle around it.
6. **Exit hold check precondition.** The 2 ms `micros()` stamp, the raw (not settled) ladder read, the 150 us busy
   wait inside the exit iteration, and the F55 detection that now depends on an exit with EF_EN H (dump check,
   configuration check, FC window, or a regen exit during a pulse).
7. **`OC_FC` as an FC-window stuck-dump detector.** BENCH_TEST 0 only; the BENCH_TEST 1 residual of row F50.
8. **I_NB,cal.** How C-2a item 28 separates the BT-boost input from the other VBT loads with the sensors fitted.

Table F2 lists the completeness-critic items that revision 8 closes or narrows.

Table F2. Completeness-critic items in revision 8.

| Item | Disposition |
|---|---|
| CC-B4 | Closed: EEPROM bytes 0-511, record layout and State-98 key `7` (sections 12.8, 12.12 item 2) |
| CC-B7 | Narrowed: R_MD rating basis named (BT5-DS-04); part selection still open |

CC-B3, CC-B6, CC-B7 (part selection), CC-B8 and CC-B11 remain open. Each needs a primary, a measurement or a protocol
round: CC-B3 the protocol-v6 layout under OR-H; CC-B6 the quiescent currents of the LB parts; CC-B8 the V2-0 maximum
t_D_ON; CC-B11 connector and enclosure part data.

## Appendix G. Operator rulings of 2026-11-08 and the purge round

Revision 9 is not a battle-test round. It applies two operator rulings of 2026-11-08 (section 17, OR-P and OR-SC) and
the operator's intent to charge between purges during drive cycles (OR-O'). Three fact sheets supplied the evidence:
`facts_purge_sequencing.md` (the pre-purge timeline and the predictor interface), `facts_purge_collapse.md` (the safe
collapse on an unpredicted purge) and `facts_purge_demand.md` (the FC-window budget in drive). Each fact sheet used only
the facts_prior section 7 purge figures and did not model or criticise the predictor. Table G1 records where the fact
sheets disagreed or proposed a change, and the disposition.

Table G1. Reconciliation of the purge fact sheets.

| Item | Fact sheets | Disposition in revision 9 |
|---|---|---|
| Hard lead time | Sequencing: 34.7 ms typical, 47.0 ms worst healthy, 93.3 ms deadline bound. Demand: 38.7 ms nominal, 58.2 ms worst | Both rest on the same BT_BUS conduction term (t_D_ON plus the 19.77 ms soft-start). The demand worst lets the drain and the confirmation run to their 13.15 ms deadlines but omits the 1.34 ms from the prediction to the feed drop; with it the chain is 59.6 ms. T_lead,min = 60 ms (calc9 section 1) |
| Full lead time (ruling-1 shift) | Sequencing: 101-168 ms typical, 274.1 ms worst from the firmware slew constants. Demand: 58.7-108.3 ms from a 20-50 ms EMA ESTIMATE | The slew constants bound the walk (ino:3242, 3288-3325); the EMA estimate is superseded. T_lead,nom = 290 ms with the deadline chain (calc9 section 1) |
| Firmware confirmation of BT conduction before the onset | Demand: proposed (UNCONFIRMED mechanism) | Not adopted as a gate: BT_CURRENT need not rise at a held droop split, so the confirmation is not observable in every case. Replaced by the bench bound W2a, the `PURGE_LEAD_SHORT` event and the armed UV_BUS (row F59) |
| The FC-only lockout and the selector | Demand: the predictor permit must replace `UV_FC_PURGE_LOCKOUT_MS` for the selector as well. Sequencing: the shift back stops at 0.85 and entry step 5 moves the rest | Not adopted for the selector: the window drops BT_BUS through the mode manager, not through the selector, so the lockout does not block a window (section 9.7); the selector lockout is unchanged |
| Share-shift target | Sequencing: a command at `DROOP_R_MIN` can arm the selector battery-only and cut FC_BUS | R_OV strictly inside the inclusive rails (section 9.11.3) |
| V_chg re-entry rule | Sequencing: strict or literal; demand: none, v11 or blank | Literal adopted (ruling OR-VC); "none" is not adopted, because a V_chg above 11 V at entry cannot be told from a fed input (rows F15, F17) |
| Exit policy on a window collapse | Collapse: E1 (revision 8) leaves the race H-R; E2 removes it; E3 keeps a ride-through | E2 adopted (`ERR_FC_ONLY_COLLAPSE`); reading (b) on V_bus added to cover the sessions with EF_EN L and a failed pin-38 channel; E3 recorded under OR-SC |
| Detector independence and pin-27 writes (variant D) | Collapse: required | Adopted for every FC-fed session in every state (section 12.4 item 7, row F61) |
| Variant D | Collapse: not unsafe with three rules. Demand: of limited worth; 92 % of the recorded window time is at standstill | D-s adopted, D not adopted (OR-DM) |
| Survivor blanking and t_D_ON; `doState3()` and `shareSpCutFC` | Sequencing observations 1 and 2 | Open items 32 and 37; host test |

**What a later review must check on the revision-9 changes.**

1. **`ERR_FC_ONLY_COLLAPSE` with no dwell.** A single V_bus reading below 12.0 V or V_chg reading below 13.0 V latches
   State 99. The false-latch exposure at the eFuse start, at an Ag105 start transient and on ADC noise near the
   threshold is not calculated; W2d counts it.
2. **The extent of a BT-open session.** The detector covers `CHG_EXITING` up to the BT_BUS re-close write. The interval
   from that write to the D-BT-EN conduction (up to 31.8 ms) is covered only by UV_BUS (row F59).
3. **Share override R_OV.** Its value, its interaction with the fw v28 sliver hold and with the gate below 0.25 A at
   standstill, and the ratio held at a window close (open item 36).
4. **The State-2 standstill window.** I_still against the drive-controller dither, the hold of the VESC command at 0 A
   on a `v_setpoint` step, the Pi watchdog in State 2 inside a window, and the coexistence with the share loop's
   FC-charge-window behaviour (the k_d hold of fw v28 rev 4).
5. **The predictor interface.** The UNKNOWN state at boot and after an H-20 restart, and whether the bench-supply case
   of PI-5 can be reported without a mode switch.
6. **The literal V_chg rule.** Whether any fault leaves V_chg below 11 V with a feed present (row F52 is the known case,
   covered by `ERR_VCHG_SENSE` and the 13.5 V `chargerHasPower()` floor).

## Appendix H. Battle-test round 6 adjudication

Battle-test round 6 attacked revision 9 under the operator rulings of 2026-11-08: the purge predictor is ideal and out of
scope (OR-P), and an unpredicted purge may end in a shutdown without damage (OR-SC). No finding attacked the predictor,
and none rested on a bare collapse to shutdown, so the ruling filter refuted none. The round produced 13 findings: 3
major and 10 minor at their verified or filed severity, and no blocker. The lenses were the FMEA lens (FM6-1 to FM6-3,
`calc/fmea_round6_calcs.py`, cited "r6") and the logic, transient and requirements lenses (BT6-*; `calc/bt6_*.py`).
Five findings were verified at a lower severity than filed or only in part: FM6-1, FM6-2, BT6-TR-02, BT6-REQ-01 and
BT6-REQ-02, all minor. Five minors carry no verifier record (FM6-3, BT6-LS-03, BT6-REQ-03, BT6-REQ-04,
BT6-REQ-05) and were checked against the firmware and the scripts before the fix. The revision-10 numbers are in
`calc/ic1_rev10_calcs.py` (calc10). Revision 10 adds no hardware.

Two of the three majors were introduced by revision 9 itself: the PI-4 sentence that let UNKNOWN close a session "as a
prediction does" (BT6-LS-01), and the State-2 standstill window that left the share latch in control of pins 27 and 28
during entry steps 1-4 (BT6-LS-02). The third (BT6-TR-01) is a wrong published requirement: the share override that set
T_lead,nom for D-s does not move the MDACs at a standstill load. Revision 10 therefore narrows the feature (no override
at standstill, one lead time for every FC window), extends the existing detector instead of adding a new one, and
extends an existing ownership rule.

Table H1. Battle-test round 6 adjudication.

| Finding | Severity (verified) | Disposition | What changed |
|---|---|---|---|
| BT6-LS-01 PI-4 "UNKNOWN closes an open session as a prediction does" re-enters policy E1 on an unpredicted purge | Major | FIXED | PI-4 rewritten (verifier's wording): inside a session that holds BT_BUS open, an UNKNOWN transition, `purge_active` rising or a late prediction latches `ERR_FC_ONLY_COLLAPSE`; the exit runs only on a timely prediction (first observed with `purge_tto` at or above T_late 61 ms, calc10 section 1). "Or the permit UNKNOWN" deleted from the section 9.7 exit conditions. Reading (a) keyed on "a session in which EF_EN has been H". Exit step 4: a `busHotPlugUnsafe()` refusal latches on the next iteration that still refuses. The bt6 section-3 grid re-run with the latch: OPEN in 4860 of 4860 cases at 80 and 100 ms, 0 BT_BUS writes after the onset, 0 peaks above 2.5 A (calc10 section 5; baseline as written 15 HAZARD, 886 writes, 137 peaks). Table 24 D1 and D4, rows F57 and Table 16 corrected; host tests added; W2c sub-step (i). The adjacent `PURGE_LEAD_SHORT` race in the 0 to T_lead,min band is closed by the same late rule. |
| BT6-LS-02 State-2 standstill entry: the share latch cuts FC_BUS during entry steps 1-4, so step 5 leaves the bus with no source | Major | FIXED | Fix items 1-4 adopted: SC-8 ownership of pins 27 and 28 from the first entry write (pin 10) through `CHG_ENTERING`, the session and its exit until BT_BUS has conducted (section 12.4 item 7); the FC_BUS HIGH, unblanked and no-cut re-test immediately before entry step 5, else exit and code 11 (section 9.7); the S2 restore in `assertFcChargeEnable(true)` replaced by a refusal on the IC1 path. Item 3 is met by removing the standstill override (BT6-TR-01) and by the in-band substitution of EMS rail commands while a D-s request stands (section 9.11.6). The verifier's adjacent finding (a rail command at a stop re-arms the selector before admission and refuses every D-s window) is closed by running the fw v28 F1 disarm at the D-s entry, once per stop. Line citations corrected (cut at ino:13533-13552; S2 restore at ino:12756-12760). Host tests: rail commands 0.15, 0.85, 0.0 across two purge periods and a rail step in each of entry steps 1-4. |
| BT6-TR-01 The State-2 standstill share override is a no-op, so T_lead,nom = 290 ms and the D-s rows rest on a walk that never happens | Major | FIXED | Verifier's minimal fix adopted: in P and D-s the BT_BUS re-close is the whole ruling-(1) shift and no override is written (section 9.11.3 step 5, citing the frozen return at ino:14287 that the verifier added, the empty clip band at ino:13772-13782 and the open-loop HOLD at ino:14380-14385; calc10 section 4). PI-1 keyed on load; T_lead,nom 290 ms applies only to State 2 in closed loop with no session and is labelled an upper bound against the clip floor. Table 22 D-s rows take the P values (0.450/0.569 s dead time, 95.6/94.5 % usable); admission horizon 1.282 s (the BT6-LS-03 change raised T_lead,min to 80 ms; the dead time is unchanged because the V_chg gate binds, calc10 section 2). Table 21, Table 26, the HR2 row, W2b and the host tests restated. A direct standstill MDAC write is not specified (the TP0053 relay class, ino:14302-14311). |
| FM6-1 A failed BT_BUS re-close at a predicted purge leaves only the UV_BUS dwell | Minor (lowered) | FIXED, GATED | Verifier's minimal fix: SC-1 reading (b) at `LIMIT_V_BUS_MIN` 12.0 V, no dwell, armed from the prediction exit's BT_BUS write to the declared purge end (r6 section 1: 5 HAZARD at 80 ms falls to 1 at 11.74 V, the Table 23 row-3 class; 4 at 100 ms falls to 0). The 13.5 V threshold and the extension to every state are deferred to W2d data (W2d now records the minimum V_bus of every two-source purge and launch). New row F63 (Q_X1 drain-source short, R_S28 or EN_BE_X open, FCQ stuck HIGH after a feed drop); the F59 "22-23 ms" sentence replaced by the swept 36.7-103.4 ms and the BENIGN/OPEN result for a late D-BT-EN; W2c sub-step (ii) with EN_BE_X grounded. |
| FM6-2 The share override and the shift back move no MDAC code at standstill | Minor (lowered) | FIXED | As BT6-TR-01 (the same mechanism, filed by the FMEA lens). |
| BT6-REQ-04 T_lead,nom keyed on State 2 rests on a walk that does not run at D-s standstill | Minor | FIXED | As BT6-TR-01; PI-1 keyed on load; "override complete" declared not applicable below the gate (Table 21). |
| BT6-LS-03 T_lead,min 60 ms is not the deadline-chain bound when the gap falls before the feed drop | Minor | FIXED | The chain is bounded over every gap placement: 61.7 ms from the prediction, 60.6 ms from the observing iteration (calc10 section 1, reproducing `calc/bt6_logic_seq_enum.py` section 2). T_late = 61 ms; T_lead,min = T_late plus one gap, rounded up to 10 ms = 80 ms, so an ideal announcement is observed at 70.2 ms or more and never trips the late rule. PI-7's error band is added on top by the operator. |
| FM6-3 The State-2 exit releases traction before D-BT-EN conducts; the W2b delay criterion contradicts Table 21 | Minor | FIXED | Exit step 4 holds the motor command at 0 A until BT_BUS has been HIGH for the conduction bound (43-47 ms after the command healthy, at most 61.7 ms; calc10 section 8); OR-2' extended; row F62 extended; W2b criterion restated (release at most 61.7 ms; peak FC_CURRENT between the write and the conduction below 1.25 A). The blanking/conduction overlap of Table 21 is referenced to open item 32, where SC-8 now keeps the share latch off pins 27 and 28 for the purge sequence. |
| BT6-REQ-03 The EMS share interface omits the selector rails; a recorded SDP commands exactly 0.15 at standstill with a request | Minor | FIXED | The second option adopted: the mode manager substitutes the nearest strictly in-band value for an EMS rail command while a D-s request stands and through the session and its exit (section 9.11.6); the D-s entry performs the fw v28 F1 disarm once per stop. The fw v30 ruling that the Pi keeps the command inside (0.15, 0.85) stands. Host test across two purge periods. |
| BT6-TR-02 Safe collapse ends in a State 99 that drains the pack; the next power-up can charge an over-discharged pack | Minor (lowered) | FIXED | Verifier's minimal fix: entry condition V_batt at or above 7.4 V on two settled iterations, independent of the UV_BATT arming (code 14); D11 verdict narrowed; WARNING in the 9.11.5 Residuals; State-99 drain measured at W2c (iii). The SNVS power-off is not specified (optional, TODO(verify: PJRC)). Host test at 7.3 V on a never-armed pack. |
| BT6-REQ-02 The State-99 end state leaves the pack under an unbounded drain | Minor (lowered) | FIXED, RULING | Verifier's wording adopted: the Residuals state that no fw v37 state disconnects the logic load and that State 99 is the smallest parked drain; D7 narrowed to supply integrity during the event; new operating rule OR-PK (attended parked H-20 windows; Pi alert on any State 99). The proposed D12 row with an OPEN verdict is **not adopted**: the mechanism is not specific to the collapse (verifier). |
| BT6-REQ-01 HR2 in Run is not measured against EMS requests | Minor (lowered) | FIXED | Request-gated figures added (D-s 107.3 s, 37.3 mAh, 24.0 % of 446.6 s; D 127.5 s, 44.3 mAh, 28.5 %; increment 20.2 s, about 7 mAh; calc10 section 6) to Table 26, section 9.11.6, section 9.11.7, OR-O', OR-DM, the summary and the HR2 row; Table 27 and the HR2 row labelled as an upper bound (request at every stop, no T_still dwell); the 1.2-1.8x plant-cycle ratio of D (pessimistic) over D-s stated beside the recommendation. The verifier's corrections are applied: the decomposition in (a) is not repeated, and the 28.4 % rounding becomes 28.5 %. The OR-DM decision is unchanged and stays with the operator. |
| BT6-REQ-05 The firmware size estimate is the round-2 figure | Minor | FIXED | Re-derived per package against the fw v28 and fw v37 `J` calibration points: about 7,100-11,300 `.ino` lines and 1,450-2,300 host checks, about 90 % Stage 1, the purge package 1,000-1,900 lines (section 12.12, calc10 section 9; ESTIMATE, UNCONFIRMED). |

**Variant D under the operator's intent.** The rulings let FC windows open in State 2 between purges. Variant D (in
motion) is not unsafe by section 9.11.5 and is now covered by the PI-4 latch, but it is of small worth: on the recorded
EMS requests it adds 20.2 s (about 7 mAh) to D-s over 47 minutes of driving, its 0.06-0.33 A traction allowance is the
size of the INA253A1 zero error and the plant-to-rig error, and a purge at a pre-purge I_fc of 1.0-1.25 A is outside the
172-purge evidence. Variant D-s carries the operator's intent at stops; ruling OR-DM keeps D as a re-evaluation after B8
and W1.

The following findings change the HR status of section 13: BT6-LS-01 (HR2 under OR-SC: the no-damage claim now holds on
a recognised onset), BT6-TR-01, FM6-2, BT6-REQ-04 and BT6-LS-03 (HR2: one lead time of 80 ms for every FC window; D-s
dead time 0.450-0.569 s), BT6-REQ-01 (HR2 stated against requests), BT6-LS-02 (availability: a healthy-board State-99
latch removed from the D-s entry).

**What a later review must check on the revision-10 changes.**

1. **The PI-4 latch.** Its false-latch exposure on a predictor glitch (an UNKNOWN that is not an onset) is a predictor
   property under OR-P; W2d counts it. The precedence over every exit step, including an exit already past its feed
   drop when `purge_active` rises.
2. **Reading (b) through the purge interval.** The 12.0 V threshold at a two-source purge with State-2 traction above
   the 0.712 A of the recorded purges (W2d records it); the purge end as declared by the predictor versus V_fc.
3. **SC-8 over the whole entry and exit.** The interaction with the selector's gate release and with the fw v28 k_d
   hold while pins 27 and 28 are owned for up to about 0.1 s per exit plus the purge interval.
4. **The in-band substitution.** That it never reaches the share loop in closed loop (it is limited to the standstill
   conditions and the D-s session), and the stale filter on a frozen return at the next launch (open item 36).
5. **The F1 disarm at the D-s entry.** Its FC_BUS re-close onto the battery-fed bus and the 30 ms blanking before the
   conduction gate passes; once per stop.
6. **The traction hold.** A 43-62 ms launch delay at every D-s exit on a traction request; the drive-law state during
   the hold (OR-2').
7. **T_lead,min 80 ms and T_late 61 ms.** Both rest on t_D_ON at most 12 ms; W2a raises both by any excess.

## Appendix I. Battle-test round 7 adjudication

Battle-test round 7 attacked revision 10 through the FMEA, logic-sequencing, transient-simulation and requirements
lenses. Eight findings were confirmed and none was refuted. The operator rulings of 2026-11-08 bound the round: the
purge predictor is ideal (OR-P) and an unpredicted purge may end in a State-99 shutdown with no damage (OR-SC). No
finding concerns the predictor or the unpredicted-purge collapse. Revision 11 answers every finding with firmware
rules, gates, statements and one ruling; it adds no circuit. Table I1 gives the dispositions. The calculation is
`calc/ic1_rev11_calcs.py` (calc11).

Table I1. Round-7 findings and dispositions.

| ID and claim | Severity | Disposition | What changed |
|---|---|---|---|
| FM7-1 D-s needs a State-1/98 dump-check pass that no specified trigger produces; D-s delivers 0 s on every recorded session | Major | FIXED | Verifier's preferred fix adopted: the dump check (register reads and writes disabled) is also admitted in State 2 under the D-s standstill conditions, started by the first request of a power cycle without a pass, with every D-s rule applied (F1 disarm, SC-8, in-band substitution, fixed split, traction exit with no verdict and the traction hold); the window follows at the same stop after V_chg falls below 11 V (section 9.7b; section 12.4 item 7; Table 25 code 12 restated). The Idle-dwell trigger of the finding's first option is not adopted: with a Pi connected, any `mode_cmd` 0-3 packet in State 1 sets `changeToRun` (ino:7533-7535) within 0.00-0.49 s of the session start. Code 4 does not bind at the first request: the H-20 is tracked for at least 5.2 purge periods before it (calc11 section 1). Host test (boot, mode-0 packet, standstill, first request: dump check, pass, window with code 0). Recomputed counterfactual: 106.6 s on the nominal chain and 104.8-104.9 s on the slow chain, against 107.3 s with no precondition and 0 s under the revision-10 text (calc11 section 1); as an HR2 value it is withdrawn by BT7-REQ-02. |
| BT7-LS-01 D-s cannot open in a power cycle whose first request arrives in Run; open item 37 also blocks the State-1 dump check | Major | FIXED | Main claim: as FM7-1 (one fix serves both). W2b gains a sub-step that starts from a boot with the first flagged request in Run. Secondary claim (open item 37): closed by design. Before any State-1 or State-98 FC-fed session the mode manager runs the F1 disarm and the guarded FC_BUS latch release (V_bus at or above 13.5 V, FC_REG HIGH, BT_BUS HIGH, `busHotPlugUnsafe(FC_REG_ENABLE)` false) and waits out the 30 ms blanking; a refused release is code 11 (section 12.4 item 9; host test). The verifier's alternative, an Idle auto-trigger at the first purge permit, is not adopted for the reason given under FM7-1. |
| BT7-REQ-01 The deployed Pi EMS uses `charge_goal` as its regen gate, so IC1 opens FC windows that the EMS never requested | Major | FIXED, RULING | Verifier's minimal fix adopted: a request is command byte 20 = 0xA5 with `charge_goal` above `CHG_GOAL_MIN`; without the flag the firmware refuses with the new code 15 (section 9.11.6, Table 25). `mode_cmd` 3 is not used as the flag, because it sets `changeToRun` in State 1. A parked request on a Pi-connected vehicle carries `mode_cmd` 4. Section 12.12 item 6 is rewritten (its premise that the nodes "keep charge_goal as a window request" was false); the Pi round is a Stage-1 prerequisite (new ruling OR-RQ); new gate W2e; new row F65; host test that replays the latch at four phases. The verifier's refutation of the parked-window and drain sub-claims is recorded: from a live Pi, State 1 is entered only through MODE_SAFE with `charge_goal` 0.0, so the latch cannot stand in State 1; OR-PK is unchanged. The semantic change of byte 20 goes through the protocol-bump procedure with the telemetry v6 lockstep. |
| BT7-REQ-02 The revision-10 "HR2 against EMS requests" measures regen-latch time | Minor | FIXED, GATED | Restated in the summary, Table 1 row 5, section 9.11.6, section 9.11.7 (Table 26 rows, the HR2 paragraph, the recommendation), Table 17, OR-O' and OR-DM: the recorded sessions carry 0 s of FC-charge request, HR2 in Run against EMS requests is undetermined, and Table 27 is the only figure in Run (an upper bound). The 84 % claim and the request-gated basis of OR-DM are withdrawn; OR-DM rests on the traction allowance, the sense error and the uncovered high-I_fc purge. The proposed EMS walk is open item 40 (not run in this round). Appendix H keeps its revision-10 text as the record. |
| BT7-TR-01 The FC-only window bus is drooped by the closed-loop share split, not held at 15.9 V | Minor (lowered by the verifier) | FIXED, GATED | The proposed firmware rule is adopted, with the order set so that the split is written only while BT_BUS is open. At entry step 5, once BT_CURRENT is below 0.2 A, the share loop, the k_d topology slew and every MDAC write are frozen and the mode manager writes r = 0.85 at k_d = `K_DROOP` (code 718). The stored split is restored in the iteration after the exit's BT_BUS write, and the freeze lasts to the end of the SC-8 interval. The same rule applies in P, the dump check, the configuration check and the probe (section 9.7 entry step 5 and exit step 4; section 12.4 item 10; host test). In-window R_FC becomes 0.094-0.353 Ohm and V_chg 15.52-15.82 V, 1.70-1.98 V above the 13.82 V threshold with 100 % of the input power deliverable; at the closed-loop clamp the design chain gives 13.50-13.99 V and 65-100 % (calc11 section 2). W1 and W2b gain the V_chg criterion (at or above the S0-4 threshold + 0.3 V and at or above 14.0 V) and record the codes and reg 0x06. R_FC is TODO(calibrate) (open item 41). Table 26 notes the split dependence of the variant-D headroom (0.03-0.08 A at r 0.15, bt7 section 5). The verifier's severity is kept: no damage path follows, and a false SC-1 latch is a safe State 99. |
| FM7-2 The PI-4 late-prediction margin rests on a loop gap from a State-98, USE_ETHERNET 0 build | Minor | GATED | W1 and W2b gain a hard criterion: the maximum iteration on the production build is at or below 15 ms against the 19.0 ms bound (calc11 section 3); otherwise T_lead,min and T_late rise by the excess over 19.0 ms (a predictor requirement under OR-P). The BLG records the iteration that precedes each prediction observation (section 12.9). Open item 42. |
| FM7-3 The W2b criterion "MDAC codes unchanged from the window close to the onset" contradicts the closed-loop tail | Minor | FIXED | The criterion is replaced by the section 9.11.3 statement (codes and V_bus recorded at the onset, V_bus above `LIMIT_V_BUS_MIN`, no pin-27 or pin-28 write from the share latch or the selector in the SC-8 interval); the standstill auxiliary load and its regime are recorded. The BT7-TR-01 freeze also removes the mechanism: the share loop stays frozen through the SC-8 interval, which ends at the declared purge end after a prediction exit, so the closed-loop tail cannot write codes before the onset (section 9.11.3). |
| BT7-LS-02 The exit-step-4 guard ignores a disabled BT boost, and the entry never tests the boost enables | Minor | FIXED | FC_REG and BT_REG HIGH on two settled iterations are added to the entry conditions of every FC-fed session (code 11); BT_REG LOW at exit step 4 latches `ERR_FC_ONLY_COLLAPSE` with no BT_BUS write; the `B` and `F` write forms are refused while a request stands (sections 9.7 and 12.4 item 7); new row F64; host test. |

The following findings change the HR status of section 13: BT7-REQ-02 and BT7-REQ-01 (HR2 against EMS requests is
undetermined, and a request needs the Pi round of OR-RQ), FM7-1 and BT7-LS-01 (variant D-s reachable at all in the
recorded operating sequence) and BT7-TR-01 (the deliverable input power in a window). HR1, HR3, HR4 and HR5 are
unchanged.

**Variant D under the operator's intent.** The operator's intent admits FC windows in State 2 between purges whenever
the EMS requests them. Variant D-s serves that intent at stops. Variant D (in motion) is not unsafe by section 9.11.5.
However, its worth cannot be shown from the recorded sessions (0 s of FC-charge request), its traction allowance is the
size of the sense error on a stiff bus and falls to 0.03-0.08 A of voltage headroom at a drooped split, and a purge at a
high pre-purge I_fc is outside the recorded evidence. It stays an option under OR-DM, to be re-evaluated with open items
40 and 41.

**What a later review must check on the revision-11 changes.**

1. **The State-2 dump check.** That it inherits every D-s rule (SC-8, the substitution, the fixed split, the traction
   exit and hold), that an abort with no verdict records no pass, and the extra 365.6 ms V_chg decay before the first
   window of a power cycle.
2. **The request flag.** That byte 20 is parsed with the same hold discipline as the floats (ino:7516-7528), that one
   packet without the flag inside a window ends the window as a withdrawn request and is not a fault, and the lockstep
   with the Pi bridge.
3. **The fixed split and the freeze.** The held share-loop integrator and filter after a long window (the stale filter
   of open item 36 now spans the whole window); that the restore precedes D-BT-EN conduction in every case of Table 21;
   that no MDAC write reaches the bus with both bus switches closed.
4. **The guarded FC_BUS release in Idle.** Its FC_BUS re-close onto the battery-fed bus outside State 2 (the Death-5
   hot-plug class: `busHotPlugUnsafe()` must pass), and that it never runs inside a session.
5. **The boost-enable entry condition.** Its interaction with the State-98 bring-up keys and with a fault teardown that
   drops FC_REG.
6. **The iteration criterion.** The 15 ms limit against the measured production-build histogram.

## Appendix J. Battle-test round 8 adjudication

Battle-test round 8 attacked revision 11 through the FMEA, logic-sequencing, datasheet, transient-simulation and
requirements lenses. It covered the revision-8 hardware that no earlier round had attacked (R_VC1c, R_MS3, R_BL3,
R_PGL, the D_VC1 selection under OR-AC: Appendix F later-review items 1-4) and the revision-11 firmware rules. Fourteen
findings were confirmed and none was refuted; three majors stand after verification, and the verifiers lowered five
findings from major to minor. The operator rulings of 2026-11-08 bound the round (OR-P, OR-SC); no finding concerns the
purge predictor. Revision 12 answers every finding without a new electrical component: one harness routing rule
(SHDN_EF in its own sleeve), one tightened part-selection requirement (Q_MD), firmware rules, gates, statements and one
restated ruling (OR-AC). Table J1 gives the dispositions. The calculation is `calc/ic1_rev12_calcs.py` (calc12).

Table J1. Round-8 findings and dispositions.

| ID and claim | Severity | Lens | Disposition | What changed |
|---|---|---|---|---|
| BT8-FM-01 An MD_G-SHDN_EF short in the revision-8 CB-LB sleeve parks the eFuse SHDN pin and the Q_MD gate at about 1.6 V in both EF_EN states | Major | FMEA | FIXED, GATED | The verifier's minimal fix is adopted in its segregation form: SHDN_EF runs in a sleeve of its own, apart from every other lead (section 5.7 item 4), so the short needs two insulation failures; this also covers the MS-SHDN_EF pair of row F55 and the SHDN_EF pairs of `calc/bt8_fmea_rev8_sleeve.py` section 3. New row F66 (node 1.55-1.68 V over the 3V3 range, calc12 section 1). C-1 and C-4 add lead-to-lead insulation tests inside the CB-LB sleeve and of SHDN_EF against it; C-2b item (h) injects the short from J-FC at 12.0 V with a 0.5 A limit for at most 1 s and records the eFuse state, the gate level, the Q_MD current and the latch. Table 7 Q_MD: the selection records the V_GS(th) range, the transfer characteristic near 1.55-1.68 V, a linear-mode SOA and V_GSS; Q_MD destruction under the double fault is accepted (the F54c class; accepted by the operator on 2026-11-09, section 17). The alternative (R_MDS 10 kOhm) is not adopted: it reopens the Q_MD gate-charge timing and C-2a item 27. A Q_MD bound that forces either full enhancement or cut-off at 1.6 V is not adopted: a 40 V part rated for full enhancement at 1.5 V, or one that stays off at 1.63 V at 125 C while it is fully on at a 3.1 V LVC high level, was not shown to exist, which would repeat the D_VC1 pattern. |
| BT8-LS-01 The Idle-entry self-test aborts on a window request and its deferred result then refuses that window; P windows deadlock on the OR-RQ parked form, and D-s can be refused for a whole Run | Major | Logic | FIXED | The verifier's minimal fix is adopted (sections 9.3, 9.5, 12.4 item 8, Table 16, Table 25): a State-2 request, a non-zero motor command or a fault aborts the self-test; a window request waits for the result (at most 457.5 ms, calc12 section 10); a deferred result refuses windows with the new code 16 until a re-run passes; the re-run comes at the first Idle iteration with no State-2 request, and Stage-2 step 10 re-runs when MOT_PWR reads HIGH; the State 0 to State 1 transition is not an Idle entry, so the boot self-test stands for the first Idle. T1, T2 and T4 pass, T3 re-runs step 10, and T5 no longer arises (calc12 section 10). The residual (a Run request inside an Idle self-test refuses D-s in that Run, code 16) is stated. Host tests at the firmware round: the parked form that arrives with the Finish opens a P window after the self-test; a Run command 40 ms after the first State-1 iteration still admits a D-s window at the first stop. The T1 and T5 traces join W2e and W2b through those host tests. |
| BT8-REQ-01 The 16 V J-FC commissioning setpoint overdrives Teensy pin 24 and bypasses the FC boost; later J-FC gates have no supply setting | Major | Requirements | FIXED | Section 9.2: J-FC at 12.0 V with a 1.5 A limit for commissioning, a WARNING against J-FC above 12.3 V (3.6 V on pin 24 at 13.46 V), a V_fc pre-check (12.0 V +/- 0.2 V), and one setting of 12.0 V with a 2.0 A limit for every later bench-supply session (1.27 times the 1.58 A worst window draw, calc12 section 2), cited in C-2b, C-3, W1, B8-1, W2a, W2c and V2-6. Adjacent items recorded: the H-20 open-circuit voltage against the pin-24 divider (open item 44) and the missing V_fc overvoltage fault (open item 45). The W1 duration item is BT8-REQ-03. |
| BT8-DS-01 R_MS3 and R_IMF protect nothing: the TLV3011B has no upper input clamp | Minor (lowered by the verifier) | Datasheet | FIXED | The verifier's documentation fix is adopted: section 5.3 item 3, section 5.7 item 4, Table 7 R_MS3 (citation corrected to SBOS300C section 6.2 note 2 and section 9.4.4), rows F54b and F54c. The MS and IMON leads rely on segregation; the resistors limit the current into an input that has failed short (0.83 mA, 1.82 mA). FM5-2 and BT5-BO-02 stay FIXED for the pin-20 and PROFILE current only. The Schottky clamp alternative is not adopted: it brings back the rail injection and adds hot leakage to the U_MS threshold and the U_IM window. |
| BT8-DS-02 The LB-entry rule rests on clamp currents that no primary rates, and the CB-end pins of the same leads have no protection | Minor (lowered by the verifier) | Datasheet | FIXED | Section 5.2 VC1-tap text, section 5.7 item 4, Table 7 (R_VC1c, R_PGL), rows F54b and F54c: the LVC outputs have no positive clamp (SCES214AF section 5.1), the 18 mA output-clamp figure is withdrawn and the 'LVC IOK' TODO is closed as negative; the CB-end exposure is stated (TPS26631 SHDN and IMON at 8.5-21.5 V against 5.5 V; Q_CS and Q_MP V_GS up to 21.29 V against 20 V; the Q_MD gate); segregation is the sole protection at both lead ends. TODO(verify: IMXRT1060CEC) for pin 20 stays open, restated as an unrated pad (open item 29). Real clamps are not adopted: the operator accepted segregation as the only protection at both lead ends on 2026-11-09, with no clamps added (section 17). |
| BT8-DS-03 The pin-20 leakage limit in the primary is 12.7 times the `ERR_CELL_MISMATCH` allowance | Minor (lowered by the verifier) | Datasheet | FIXED | Table 16 `ERR_CELL_MISMATCH` and open item 24 state the 12.7x ratio and that the 80 mV threshold rests on the C-2a hot and cold record. The F47 safety claim of the finding is refuted by the verifier: F47 reads at least 7.5 V against a worst healthy error of 0.53 V at the datasheet limit, so any threshold up to 7 V detects it (calc12 section 7). The CMOS follower stays the fallback, not adopted. |
| BT8-DS-04 D_VC1 is not buildable from stock: the lowest-V_F Schottky found fails the V_F limit at 25 C, and its hot leakage is 5 times the budget | Minor (lowered by the verifier) | Datasheet | RULING | OR-AC restated (section 17) and Table 7 D_VC1 extended: real-part leakage about 10 x I_S cuts the 40 uA window to about 44 C even at T_min 25 C (calc12 section 8); the NSR0320MW2 fails the 0.25 V design limit on its maximum row and sits 17 mV inside the -0.3 V requirement; no passive part is identified; (a) or (c) unless B8-1 shows T_M16,max below about 44 C. New option (d): a provisional part for the first build at T_min 25 C; the operator chose option (d) for the first build on 2026-11-09 (section 17). Open item 13 updated. The PMEG2005ESF figures (secondary copy) stay UNCONFIRMED and are not used. |
| BT8-REQ-02 The D_VC1 selection depends on gate B8, which cannot run before D_VC1 is fitted | Minor (lowered by the verifier) | Requirements | FIXED, RULING | OR-AC option (d), chosen by the operator on 2026-11-09, breaks the cycle. B8 is split into B8-1 (Stage 1, FC window, after W1, with the M16 temperature, followed by a re-verification or replacement of D_VC1 and repeats of the C-1 D_VC1 items, BG-17b and B-PKN) and B8-2 (Stage 2, regen window, HR1 hold condition I_L at most 0.75 A). B-FPK and B-PKN move ahead of C-2b, so that the table order matches section 9.2 step 1. The 8.0 V sub-claim is refuted by the verifier: the code-7 limit applies only until S0-8b, a Stage-0 gate; B8-1 measures at the highest admitted V_batt. |
| BT8-LS-02 The State-2 dump-check trigger is literally once per power cycle | Minor | Logic | FIXED | Section 9.7b and Table 25 code 12: the trigger is any request while no pass is recorded, at most one attempt per stop (State 2) or per purge period (State 1, 98), at most three no-verdict attempts per power cycle; code 12 then stands. Host test at the firmware round: a first-stop dump check aborted by a `v_setpoint` step is retried at the next stop and the window opens. |
| BT8-TR-01 S0-11 accepts C_mod up to 221 uF, but at C_DV 10 nF the 0.6 A inrush limit holds only to 103.6 uF | Minor | Transient | FIXED, GATED | Section 5.3, Table 7 C_DV, S0-11: C_DV at least 10 nF x C_mod / 103.6 uF for a larger measured C_mod; the `ERR_MOD_DUMP_ON` sample moves to the later of 10 ms and the measured ramp plus 2 ms (section 9.7b step 5, Table 16); the Stage-2 regen-pulse budget is re-derived before Stage 2; C-3 runs at the largest fitted C_mod with 0.15 A of aux against 1.3 A (1.4 A less the INA253A1 zero). Table 16 now cites the ramp as 3.8 ms at C_DV 10 nF (calc12 section 3). The UVLO-delay scaling is open item 46. A raised C_DV is a part-value change that S0-11 triggers only on a measured C_mod above 103.6 uF. |
| BT8-TR-02 The fixed window split is 'code 718', but `setDroopMdac()` truncates to 717 | Minor | Transient | FIXED | Section 9.7 entry step 5 states code 717 and has the host test compute the code through `setDroopMdac()` (calc12 section 4). |
| BT8-TR-03 The R8-3 range 'R_BL2 82 to 100 kOhm' admits a value at which BAL_OK fails VIH above the 7.4 V entry floor | Minor | Transient | FIXED | Table 7: R_BL2 fixed at 100 kOhm, 1 %; the threshold VBAL+ 7.0 V at the worst corner (0.4 V below the 7.4 V floor, calc12 section 5) is stated. The revision-8 table 0e row is history and is not edited. |
| BT8-REQ-03 W1 cannot run as written (60 s against the 30 s cap; no request source) and the gate order contradicts 'W2e precedes the first vehicle window' | Minor | Requirements | FIXED | W1 is two 30 s windows separated by `FC_CHG_COOLDOWN_MS`; a State-98 window-request key (section 12.8) is the request source for W1, W2 and C-2b before the W2e Pi round; table 15.3 order W1, B8-1, W2a, W2e, W2, W2c, W2b, W2d. |
| BT8-REQ-04 The parked HR2 headline omits the dead-time pack drain; revision-11 text is stale; the workload estimate predates revision 11 | Minor | Requirements | FIXED, GATED | HR2 stated as 1.17-1.19 A of net pack current at the ASSUMED I_L of 0.2-0.3 A (summary, Table 22, section 9.11.7, section 14.2, Table 17; calc12 section 6); the summary gate list, the 9.11 heading and the Table 1 header corrected; change-set item 5 names the injection-frame extension, and section 12.10 states that IC1 has no HIL coverage until it lands; the size estimate is not re-derived (open item 43). |

The following findings change the HR status of section 13: BT8-REQ-04 (the HR2 parked figure is net pack current,
1.17-1.19 A). BT8-FM-01 and BT8-DS-01/02 change no HR row but restate the basis of HR4 and HR5 for a chafed or shorted
signal lead: the protection is segregation (two insulation failures), not the LB-entry resistors. BT8-LS-01 removes an
availability defect of HR2 (variant P on a Pi-connected vehicle). HR1 and HR3 are unchanged.

**Answers to the round-7 items for a later attacker (Appendix I).** Round 8 checked item 1 (the State-2 dump check: an
abort records no pass, BT8-LS-02 fixed the retry). Items 2-6 of Appendix I were not reported on and remain open for a
later round.

**What a later review must check on the revision-12 changes.**

1. **The SHDN_EF sleeve.** That the third sleeve fits the CB-LB route on the vehicle (TODO(layout)); that no connector
   or tap header puts SHDN_EF on a pin adjacent to MD_G, MS, IMON, EF_FLT_N or PROFILE (a short at the connector is not
   prevented by the sleeve); and the C-1 lead-to-lead test method with LB and CB both unplugged.
2. **C-2b item (h).** That the 0.5 A limit and the 1 s operator stop bound the Q_MD stress on the selected part, and
   that the injected short is removed and the C-1 lead-to-lead test repeated afterwards.
3. **The self-test re-run rule.** That a re-run cannot start while a window or an exit is active (it is entered only
   from `CHG_BONDED`); that the 457.5 ms wait does not interact with the PI-3 admission horizon of a P window; that
   code 16 is reported only while no lower code applies; and that the boot self-test result covers the first Idle in
   both a USB-powered bench boot and a vehicle boot.
4. **The dump-check retry.** The per-stop and per-purge-period spacing against the D-s standstill conditions, and the
   three-attempt cap against a traction-heavy drive cycle with many short stops.
5. **The J-FC setting.** The 2.0 A limit against the measured window draw at B8-1, and the ADC headroom (2.8 % of full
   scale at 12.0 V) against the bench-supply set-point accuracy.
6. **OR-AC option (d).** The operator chose option (d) for the first build on 2026-11-09. A later review checks that the
   restriction to bench-attended Stage-1 sessions is enforced, and that the vehicle is not run below 25 C with the
   provisional part fitted.
7. **The C_DV rule.** The `ERR_MOD_DUMP_ON` sample move against the dump-check duration (20-60 ms) and the
   Stage-2 regen-pulse chain if C_DV is raised.

**Operator rulings of 2026-11-09 on the round-8 items.** The operator chose OR-AC option (d) for the first build
(BT8-DS-04, BT8-REQ-02), accepted the row F66 double-insulation residual (BT8-FM-01; the Q_MD selection still records
V_GS(th), the linear-mode SOA and V_GSS), and accepted sleeve segregation as the only protection of the SHDN_EF, MD_G,
PROFILE, IMON, MS and EF_FLT_N leads and of the VC1 tap at both lead ends, with no clamps added (BT8-DS-01, BT8-DS-02).
None of the three blocks a motherboard change. Section 17 records the answers verbatim.

## Completeness critic

A completeness review read this document, the three FMEA rounds under `battletest/` and the scripts under `calc/`. It
searched for unsequenced modes and transitions, unenumerated fault classes, uncited claims, parts without a primary,
gates without a pass criterion, unlisted operator rulings, unspecified firmware duties and inconsistencies between
sections. Every battle-test "not covered" entry was already adjudicated in Appendices B-D. The new calculation is
`calc/cc_completeness_calcs.py` (output `calc/cc_completeness_calcs_output.txt`, cited "cc section N"); it uses only
values stated in this document or in the firmware.

### CC-A. Gaps closed in this document

Table CC-A lists each gap that was closed by an edit in the body. The CC tags in the body mark the edited text.

Table CC-A. Gaps closed.

| ID | Class | Gap | Edit |
|---|---|---|---|
| CC-1 | Inconsistency, false latch | The U_MS positive control (section 9.5 hold duties, Table 16 `ERR_MOD_SENSE` (b)) was keyed on an EF_EN H interval of 10 ms. EF_EN rises at the VOK assert, t_D_ON before VCHG-IN is fed, so at typical t_D_ON a VOK interval of 10-12.5 ms latched `ERR_MOD_SENSE` on a healthy board (cc section 2). Section 9.7 already keyed the FC window on V_chg. | Both rules keyed on the second settled V_chg reading at or above 13.5 V: 10 ms (regen), 50 ms (FC window, configuration check); worst lag 3.38 ms. |
| CC-2 | Inconsistency | Regen exit step 5 and FC exit step 4 wrote pins 5 and 10 about 3 ms after the drain, while section 12.4 item 2 requires pin 8 LOW for 20 ms before any pin-5 or pin-10 change (cc section 6). | The writes wait for the 20 ms cold condition (about 23 ms after the feed drop); the bonded confirmation and the traction release do not wait for them. |
| CC-3 | Unsequenced transition | Commissioning (section 9.2) and the configuration check (section 9.7a) raised FC_CHARGE without the BT_BUS drop and the BT current wait of section 9.7 entry step 5, so D5 could trip FF1 on the decaying BT current after its 2.8-6.1 ms arming. | Step 6b added to section 9.2 and named in section 9.7a. |
| CC-4 | Inconsistency | Section 12.4 item 7 admits `assertFcChargeEnable(true)` only in `CHG_ENTERING`, `CHG_REGEN`, `CHG_FC` or `CHG_CONFIG`, but the commissioning sub-mode was not one of them. | Section 9.2 step 7: commissioning is `CHG_CONFIG` with the writes enabled. |
| CC-5 | Unsequenced transition | The configuration check ended with the probe and never re-closed BT_BUS or restored pins 10 and 5. | Section 9.7a step 6. |
| CC-6 | Fault class | A pin-8 tap or U_MS output stuck LOW made the probe pass on a bypassed eFuse; the positive control of the same check was not a precondition of the probe verdict. | Section 9.7a step 6: the probe is void unless the positive control of the same check passed. |
| CC-7 | Firmware duty | Section 12.4 item 7 refused only the State-98 `4` and `5` keys inside a window. The fw v37 `J` session refuses a wider set (ino:8594-8615); a pin-32 LOW (`6`) inside a window opens the battery path during charge (S0-3 overshoot), and `F`/`B` reach the boost back-feed class. | Item 7 extended to the full `J` refusal set while a window or exit is active; `X` and `Q` run the commanded exit. |
| CC-8 | Firmware duty | `CBAL_DISABLE` (pin 9) HIGH was not a window refusal, although BQ29200 OUT is the only hardware pack-OVP actuator and fw v37 `J` refuses it (ino:11303-11307). | Window-entry precondition in sections 9.5 and 9.7 and a refusal in section 12.4 item 7; the CB_EN effect on OUT is TODO(verify: SLUSA52C). |
| CC-9 | Inconsistency | Gate C-2 ran the injected-bypass configuration check before commissioning, which section 9.2 step 1 requires C-2 to precede: the as-found registers would latch `ERR_AG105_CFG`. | The sub-gate moves to new gate C-2b after commissioning; C-2b also measures the unfed V_chg with R_KA fitted, on which the `ERR_VCHG_FED` 11 V threshold rests (UNCONFIRMED before). |
| CC-10 | Gate without a check | M9 (LD tie), the MPPTSEL half of M10 and M11 (R_KA, row F18 "pre-rework continuity") had no gate. | Gate C-1d. |
| CC-11 | Fault class | An open UC1_N conductor between LB and SB, or an open D_Ak, was not enumerated. | Row F53 (accepted latent, benign alone). |
| CC-12 | Inconsistency | Table 12 gave Q_MD off and pin 8 H in reset and hang, while Table 13 and Figure 2 keep Q_MD on whenever the LB rail is up and EF_EN is L. | Table 12 row split by power state. |
| CC-13 | Inconsistency | The "5V lost" event of section 9.10 assumed a running Teensy, whose VIN is the 5V rail. | Row restricted to a USB-powered Teensy. |
| CC-14 | Uncited claim | The 430 ms self-test duration cited an appendix entry that gives no derivation. | Section 9.3 cites cc section 1 (357-458 ms over the hang-to-off and loop spread). |
| CC-15 | Unsequenced transition | No FC-window exit on GENSTAT Fully Charged; the window held the bus FC-only for no charge until the 30 s cap. | Exit condition added in section 9.7 (no latch). |
| CC-16 | Fault class, firmware duty | `FAULT_I2C_CHARGER` fires only in State 2 or 3 after `AG105_SETTLE_MS`, so under IC1 an I2C NAK could never fault in any window, and the regen-window reg 0x01 readback is expected never to be valid (boot 65-170 ms against a 19-47 ms pulse) with no stated outcome. | Section 12.5 item 2: NAK or no valid read after settle ends an FC window or voids a check (window inhibit); the regen readback is opportunistic and its absence is not a fault. |
| CC-17 | Ruling not listed | The IC1 reversals of the CLAUDE.md section 2 pin-32 text and the CLAUDE.md section 4 CB_EN statement were not in any ruling. | OR-G extended. |
| CC-18 | Uncited claim, part rating | R_MD was rated only for the single 1.71 J probe pulse; in a regen window it dumps once per VOK pulse. | Table 7: 56 dumps and at most 2.86 J per 30 s window, 0.095 W mean (cc section 3). |

The behavioural fixes CC-1, CC-2, CC-3, CC-5, CC-6, CC-7, CC-8, CC-15 and CC-16 each add a host test to section 12.11
when the firmware round runs: a VOK interval of 10-12.5 ms with t_D_ON 8 ms gives no `ERR_MOD_SENSE`; pins 5 and 10 are
not written before pin 8 has read LOW for 20 ms; commissioning and the configuration check wait for BT_CURRENT below
0.2 A before FC_CHARGE; BT_BUS is re-closed after the probe; a pin 8 stuck LOW voids the probe; every key of the CC-7
set is refused in each window state; pin 9 HIGH refuses every window type; Fully Charged ends an FC window; an Ag105
NAK after settle in `CHG_FC` and `CHG_CONFIG` ends the window.

### CC-B. Items that remain open

Table CC-B lists the gaps that this review could not close without a primary, a measurement or an operator decision.

Table CC-B. Open items.

| ID | Class | Open item | Proposed default or next step |
|---|---|---|---|
| CC-B1 | Ruling not listed (proposed OR-Z) | The trigger of the configuration check is not specified. Section 9.7a says only that it runs in State 1 "before the first regen window of a power cycle"; on the vehicle it needs a bench supply on J-FC until OR-P (revision 9: OR-P is decided; the check runs from the H-20 inside the purge permit of section 9.11.2). | **Listed as ruling OR-Z (revision 7).** Proposed: the mode manager starts `CHG_CONFIG` automatically at the first Idle dwell after a self-test pass when `IC1_STAGE` is 2, no pass is recorded this power cycle and the FC-window entry conditions hold; a State 1 to 2 request aborts it (as the section 9.7 exit). **Closed 2026-11-09:** OR-Z accepted as proposed. |
| CC-B2 | Inconsistency, ruling (proposed OR-Y) | Section 12.4 item 6 makes the mode manager the writer of pins 5 and 30 in the State-98 D/Y/W profiles, but section 9.5 admits regen windows in State 2 only. Whether a regen window may open in a State-98 drive profile is undecided. | **Listed as ruling OR-Y (revision 7).** Proposed: refused (pin 30 held LOW in State 98 except through `CHG_CONFIG`). **Closed 2026-11-09:** OR-Y accepted as proposed. |
| CC-B3 | Firmware duty, protocol | The 16-bit `fault_flags` word has no free bit (FAULT_* 0x0001-0x8000, ino:2038-2058) and Table 16 adds 26 conditions in revision 7 (23 in revision 6); `error_code` can take 0x11-0x27 (cc section 5). The protocol-v6 layout, byte count and checksum span are not defined. | Protocol v6 carries an IC1 fault word of at least 23 bits (uint32); run the protocol-bump procedure under OR-H. |
| CC-B4 | Firmware duty | The per-board calibration record of section 12.12 item 2 had no EEPROM address or size (the emulated EEPROM is 4284 B and the encoder record occupies 4276-4279, ino:3048-3063), and section 12.8 named no State-98 command that writes it. | **Closed (revision 8):** EEPROM bytes 0-511 reserved; magic, version, length, payload of at most 400 bytes, CRC-16 (section 12.12 item 2); State-98 key `7` stores it, refused outside `CHG_BONDED` (section 12.8). The PLAN.md section 9 key map is updated in the firmware round. |
| CC-B5 | Mode not sequenced (HIL) | Under `HIL_SIM` the HIL Teensy has no LB: the ladders, pin 8, I_PACK1, I_PACK2 and V_PACKN have no source in the 40-byte injection frame, so a `PACK_RETURN_CHANGEOVER` 1 HIL build would latch `ERR_CHG_LADDER`. Section 12.10 extends only the observation frame. | **Closed (revision 7):** the `static_assert` is part of the firmware specification (section 12.10) until an injection-frame extension round (a lockstep HIL protocol change). |
| CC-B6 | Uncited claim | No 3V3 load budget. The LB resistive load is at most 10.25 mA (cc section 4); the quiescent currents of 2 x INA240A3, 9 x TLV3011B and the LVC/AHCT gates, and the existing 3V3 load, are not totalled against the PJRC 250 mA external limit (facts_board section 6.1). | TODO(verify: SBOS662C, SBOS300C, TI LVC datasheets); total the rail before the LB layout. |
| CC-B7 | Part rating | R_MD repetitive-pulse rating (CC-18 duty) and the Q_MD part remain TODO(select) (open item 17). | Select both against 51 mJ per dump at one dump per 535 ms, the 1.71 J probe pulse, the 0.65 W limit-cycle duty and the stuck-on case. Revision 8 names the rating basis: the doc 20043 continuous-pulse curve for the repetitive dump and the single-pulse curve (fewer than 1000 pulses) for the probe-cap and stuck-on events (BT5-DS-04). Still open (part selection). |
| CC-B8 | Bench dependency | `ERR_VCHG_SENSE` rule (b) (two VOK pulses with EF_EN H for 20 ms and V_chg never above 12 V) false-latches if t_D_ON exceeds 19.0 ms (cc section 2); the RT1987 has no t_D_ON maximum (open item 2). | Gate V2-0 records the maximum t_D_ON; re-derive the 20 ms window from it before Stage 2, together with the revision-7 `ERR_MOD_SENSE` (b) crossing anchor, which needs a V_chg reading below 13.0 V between the eFuse UVLO and the D-BC-RG feed (a pulse without one is not evaluated). |
| CC-B9 | Gate without a criterion | Gate C-2 has the composite GO "All as designed". Several sub-items have no numeric acceptance: the S_GND gate band against Q_D and Q_R (F42), the Kelvin-lead open behaviour, the S_CHG/S_GND exit overlap, the R_ret baseline, R_chain,min, k_idle and the EF_FLT_N scope. No primary gives these limits. | **Closed (revision 7):** gate C-2a lists 27 sub-items with one GO each (Table 19), record-only items marked; the fed items are C-2b. Original proposal: split C-2 into one GO per sub-item; mark record-only items as such; set the overlap and gate-band limits as TODO(calibrate) from S0-1 and the F10 analysis. |
| CC-B10 | Gate without a consumer or criterion | B13 (Teensy VUSB-VIN pad state, "Recorded") is used by no section; S0-8 (restart from Fully Charged) has no GO criterion and no NO-GO action. | **Closed (revision 7):** B13 feeds the section 9.10 "5V lost" row; S0-8 records the restart level for the Fully Charged exit and keeps the 8.0 V gate as its NO-GO. |
| CC-B11 | Part with no primary | The keyed 30 A pack connector, the 7-way and KS connectors, the F_PK holder and ATO fuse part, the SB enclosure and the three boards have no part number or primary. | TODO(select) with current, contact-resistance and keying data, against the 12.9 mOhm pack-loop budget of section 7.6. |
| CC-B12 | Firmware duty | The role of `CHARGER_STAT` (pin 6) under IC1 is not stated. STAT is referenced to module Vin- (PCB GND) in both modes, and pin 6 is a plain input (ino:6706). | **Closed (revision 7):** log only (section 12.5 item 5). |
| CC-B13 | Unsequenced transition | Section 9.9 step 2 (pin-8 wait of up to 10 ms, then pin 33 LOW and pin 32 LOW) is not placed on the existing State-99 phase timeline, and the text does not say that the wait is non-blocking. The MOT_PWR LOW time pinned at t0 + 10 ms (test/test_main.cpp:22547) must hold. | **Closed (revision 7):** section 9.9 specifies the non-blocking phase-0 sub-step; host test in section 12.11. |
| CC-B14 | Gate without a check | Row F53 (UC1_N open) has no build gate: the self-test cannot tell the direct U_C1 path from the N1 path. | **Closed (revision 7):** gate C-2a item 26. |
| CC-B15 | Fault class (unverified) | Whether `PI_TIMEOUT` acts in State 1 and State 98, and therefore whether a Pi link loss ends a parked FC window, is not stated. | **Closed (revision 7):** `checkPiWatchdog()` returns unless `mainState` is 2 or 3 (ino:7463-7466: "States 0, 1, 98, and 99 must not fault due to Pi absence"), so a Pi link loss does not end a parked FC window; the window stays bounded by its 30 s cap, the Fully Charged exit, the purge-free permit and the hardware trips. Recorded as not required in Idle; a Pi-commanded window end on link loss would be a commanded exit, not a fault, and needs an operator request. |
