# Battle Test Round 3: FMEA of IC1 Detailed Design Revision 5

## 0. Scope and method

This report is the round-3 exhaustive failure-mode and effects analysis (FMEA) of
`detailed_design_IC1.md` revision 5. The analysis enumerates every new component (SB, LB, CB, harness, the
motherboard modifications M1-M16) and every existing path element that the new hardware touches (D-BT-SQ, D-BT-EN,
D-BC-RG, D-BC-FC, D-MT-EN, both TPS61288 boosts, the Ag105, the BQ29200 and the balance lead, the Teensy pins in
reset, Hi-Z, hang and brown-out). Each element is taken through short, open, stuck HIGH, stuck LOW, drift and
intermittent, in the bonded mode, both window types, the self-test, commissioning, the configuration check and probe,
State 99, and every transition between them. The credible double faults of the severe rows follow in section 4.

The analysis does not repeat the round-1 and round-2 findings that Appendices B and C of the design adjudicated, except
where the revision-5 fix itself introduces the defect (FM3-1). Calculations are in `calc/fmea_round3_calcs.py`
(output `calc/fmea_round3_calcs_output.txt`). Every input that no primary gives is marked ASSUMED, BENCH or
TODO(verify).

## 1. Summary of findings

Table 1 lists the findings in severity order.

Table 1. Round-3 findings.

| ID | Severity | Finding |
|---|---|---|
| FM3-1 | blocker | The revision-5 clamp D_VM puts a zero-impedance element from the balance midpoint (cell 1 positive) to PCB GND. A D_VM short is an unfused, unbreakable short of cell 1 through the balance lead (34-71 A). The design gives D_VM no surge rating, although the F34b event it exists for drives 12-17.1 A of BT-boost input current through it. |
| FM3-2 | major | VBATN_X (0.5 mm2) is protected only by F_PK 20 A. A short of VBATN_X to a pack-positive conductor drives 17-164 A through the lead and the Ag105 internal sense (rated 4 A) in the bonded mode. Rule C1's charge-mode argument ends in this same loop, because U_C1 re-bonds the pack. |
| FM3-3 | major | The 5 ms entry and exit confirmations and the 3 ms ladder persistence are wall-clock deadlines that a healthy board misses whenever one loop iteration near an edge exceeds about 3.9 ms (worst measured 9.76 ms). The result is a false `ERR_CHG_ENTRY`, `ERR_CHG_EXIT` or `ERR_CHG_LADDER` and, in production, State 99. |
| FM3-4 | minor | `ERR_VCHG_FED`, the only closure of the one-fault D-BC-FC loop (F17), rests on one ADC channel (pin 38). A pin-38 channel that reads low passes the detector and the regen entry precondition, and its health is checked at most once per power cycle in Stage 2. |

The remainder of the enumeration (section 3) found no further defect that the revision-5 rows, gates and faults do
not already bound. Section 4 records the double faults that reach a severe outcome.

## 2. Findings

### 2.1 FM3-1 (blocker): a D_VM short shorts cell 1 through the balance lead with no interrupter

**Element.** D_VM, the low-V_F Schottky added by R5-4 (M16): anode on the J-BL pin-3 barrel (PCB GND, both pours),
cathode on the J-BL pin-2 barrel (net VMID), "upstream of RB3 and RB1A" (Table 6 row M16; Table 4 net VMID).

**Failure mode and scenario.** D_VM short, or a solder bridge between the pin-2 and pin-3 barrels on the board
underside where M16 places the part (7.62 mm pitch; the pin-3 barrel needs the M13 preheat, Table 6 row M16). The
loop is cell 1 positive (midpoint tap), the balance midpoint wire and plug contact, J-BL pin 2, D_VM, the GND pours,
J-BT pin 2, leads A and B, SGND, S_GND1 and S_GND2, PACK-, R_SH and pack(-). In the charge mode the loop runs through
the Ag105 sense in reverse; U_C1 then trips at 2.52-3.50 A (Table 10) and re-bonds the pack, so the loop ends in the
bonded path in every mode.

**Numbers.** The prospective current is 34-71 A over V_cell1 3.0-4.2 V and an ASSUMED cell resistance of 10-40 mOhm
with a 0.3 m 24 AWG balance lead (`calc/fmea_round3_calcs.py` section 1). The loop contains no fuse: F_PK is in pack
positive only (section 4.1), and the balance lead has no fuse on the board (facts_board section 2.3). The only possible
interrupter is the pack PCM, whose short-circuit trip is not known (open item 11; facts_prior section 9). Before
revision 5 the lowest impedance from VMID to GND on the board was RB3 parallel RB1A, 72.2 Ohm, which limits the same
fault to 58 mA at 4.2 V.

**No actuator and no detector.** Firmware cannot break the loop: the charge mode moves it onto the Ag105 sense, and
U_C1 forces the bond back. I_PACK1 would read a discharge of tens of amperes, but no fault in Table 16 acts on an
I_PACK1 discharge without a matching load, and no switch interrupts the balance lead. Gate B-PKN measures only the D_VM
forward voltage at build. Nothing detects a later short.

**The protected event stresses the part.** Row F34b assumes that the board browns out at the pack-negative open. The
TPS61288 keeps running down to VIN 2.0 V (SLVSFP3C section 7.3; facts_board section 3.3 item 1). After the open the
board sees only cell 2 (about 3.3-3.75 V), so a BT boost in traction draws its input current, clipped at the
12-17.1 A switch limit, through D_VM and the balance midpoint wire (calc section 1b). This lasts until the Teensy browns
out. With USB powering the Teensy (every bench and commissioning session; B13 state), it lasts until
`ERR_IPACK_PLAUS` latches at 100 ms (BT_CURRENT above 1.0 A with I_PACK1 near zero, because R_SH carries no current)
plus the State-99 teardown. `UV_BATT` does not bound it: its dwell is 1000 ms (ino:2266) and it is not armed below
7.8 V. M16 states a forward-voltage and a leakage requirement but no surge (I_FSM) requirement. A small low-V_F
Schottky surged at 12-17 A is a credible route to a short, which then becomes the cell-1 short above when the
intermittent pack-negative contact recloses.

**The specification itself is not met by a reference part.** M16 asks for V_F below 0.25 V at the brown-out board
current and I_R at most 1 uA at 4.2 V and 25 C. A "very low V_F" MEGA Schottky, Nexperia PMEG2005EB, gives V_F
320-380 mV at 100 mA and I_R 7 uA typical, 30 uA maximum at 10 V and 25 C (WebSearch transcription of the data sheet
characteristics table, page not read: UNCONFIRMED). The B-PKN NO-GO action ("select a lower-V_F diode or move the clamp
to the BQ29200 pins") therefore applies on present evidence.

**Severity.** Blocker: a single part short gives an unfused cell short through a signal-gauge lead (fire), no gate
catches a short that develops in service, and the event that the part exists for drives it into surge.

**Proposed fix.**
1. Move the clamp downstream of RB3 and RB1A, with one Schottky from GND to VC1 and one from GND to VC1_CB at the
   BQ29200 pins. A short is then limited to 58 mA by the existing resistors, and the F34b board current is limited to
   at most 58 mA, so the BT boost cannot draw through the clamp. The clamp needs V_F below 0.3 V at 58 mA or less
   (BENCH, B-PKN). This is the NO-GO alternative already named at B-PKN; make it the design.
2. If D_VM stays at the barrels, fit a fast chip fuse in series with it (its drop inside the V_F budget), state an
   I_FSM requirement of at least 17.1 A for the time to `ERR_IPACK_PLAUS` plus the teardown (about 130 ms), and fuse
   the balance midpoint lead at the pack end (TODO(select)).
3. Add row F47 (D_VM short) to Table 14, and extend B-PKN with a pack-negative open under a 5 A board load from a
   current-limited supply.

### 2.2 FM3-2 (major): VBATN_X is not protected by any fuse sized for it

**Element.** VBATN_X, the 0.5 mm2 flying lead from the S_CHG drain on SB to the Ag105 pins 14/15 module-side stubs
(Table 4; M1; Table 7 harness row). Its length is 0.3-0.5 m (section 12.6 item 1).

**Failure mode and scenario.** A chafe, a crushed joint or a solder splash puts VBATN_X in contact with a pack-positive
conductor: the 2.5 mm2 pack-positive lead it runs beside between SB and the motherboard, the SB tap copper, or VBT
copper near J-BT. In the bonded mode S_CHG is off and its body diode (anode PACK-, cathode VBATN_X) is
reverse-biased. The current flows pack+, F_PK, the short, the lead from the short point to the module, the Ag105
VBat- stubs, the module's internal sense, VLoad-/Vin- (internally connected, facts_board section 4.2 item 2), the GND
pours, leads A and B, S_GND, PACK-, R_SH and pack(-).

Rule C1 (section 4.2) treats only the charge mode: "a short of VBATN_X to a positive conductor drives a
discharge-direction current through R_SH, which trips U_C1 and opens S_CHG within about 0.4 ms". That is correct for
the S_CHG path, but U_C1 also forces both S_GND gates on (Figure 1, D_A1/D_A2), so after 0.4 ms the fault current moves
to the bonded-mode path above. Rule C1 therefore ends in the same unprotected loop.

**Numbers.** With an ASSUMED Ag105 sense resistance of 10-100 mOhm (S0-1 measures it), the 0.5 m lead, an ASSUMED
20 mOhm pack and a bolted to 0.3 Ohm fault, the loop current is 17-164 A, which is 4-41 times the Ag105 4 A
continuous rating of that path (DS p.20 row 6) (`calc/fmea_round3_calcs.py` section 2). The adiabatic limit of 0.5 mm2
PVC copper (k = 115, IEC 60364-4-43) is 3306 A2s: 0.12-0.5 s for a bolted fault and 1-12 s for a resistive fault. F_PK
is a 20 A fuse sized for the 2.5 mm2 leads; at 95-260 % of its rating its opening time is seconds to minutes
(TODO(verify: fuse datasheet)), and below 100 % it does not open. Firmware has no actuator: the charge mode routes the
current through S_CHG and U_C1 re-bonds. `ERR_PACKN_RANGE` and State 99 shut the boosts down but do not touch a
pack-direct loop.

**Severity.** Major: a single harness fault leads to an overheated signal-gauge lead and an Ag105 sense far above its
rating. F_PK eventually opens a bolted fault, which separates this from FM3-1, but the fuse does not protect the
conductor.

**Proposed fix.** Fit a fast fuse (about 5 A, TODO(select)) in VBATN_X at the module end, on CB next to the stubs. The
legitimate current is at most the U_C1/U_C2 range (3.64 A), so 5 A carries every legitimate current and protects the
lead and the module against a short at any point along the lead. A second fuse at the SB end (at the S_CHG drain)
covers the 0.4 ms charge-mode phase. Route VBATN_X apart from the pack-positive lead (section 5.7 rule 4). Restate
rule C1 for both modes and add a row F48 (VBATN_X to pack positive, bonded mode) to Table 14.

### 2.3 FM3-3 (major): wall-clock confirmation deadlines fail on a healthy board at a long loop iteration

**Element.** The firmware confirmation rules: entry and exit "within 5 ms, confirm a settled reading" (section 9.5
steps 4 and exit 4; section 9.7 step 3; `ERR_CHG_ENTRY` / `ERR_CHG_EXIT`, Table 16), and "an undecodable reading, or a
settled reading that mismatches the commanded state, that persists for 3 ms ... latches `ERR_CHG_LADDER`" (section
12.4 item 4). A settled reading is "two identical decodes on successive loop iterations" (section 7.7).

**Failure mode and scenario.** The loop has no fixed tick. Its measured median is 1131 us, its p99 1337-1341 us and
its worst measured gap 9.76 ms (Table 11; facts_firmware section 8, ML0226). A settled reading after an edge needs two
iterations. When the edge is written at the end of an iteration, any one iteration of about 3.9 ms or more among the
next two misses the 5 ms deadline. One 9.76 ms iteration gives 19.5 ms to a settled reading
(`calc/fmea_round3_calcs.py` section 3). In the same way, a single read that straddles a hardware edge is undecodable
and, if the next iteration is longer than 3 ms, "persists" past the 3 ms rule. In Stage 2 hardware edges occur at every
VOK assert and release (EF_EN, CH1_OK, CH2_OK) and at every D5_N change. The 2.4 ms I2C intervals measured during the
fw v37 `J` session (facts_firmware section 8) and the SD drain of a bench log are known sources of long iterations;
the frequency of iterations above 3.9 ms in a production build is not measured (BENCH).

**Effect.** A healthy board latches `ERR_CHG_ENTRY`, `ERR_CHG_EXIT` or `ERR_CHG_LADDER`. In production these enter
State 99 (ruling OR-E proposed). In Stage 1 that is a lost charge session; in Stage 2 it is a State-99 teardown in Run
at a brake or a brake end. `ERR_CHG_EXIT` also stops the pump. The 43-76 ms hardware hang path and the RTWDOG already
cover a loop that has stopped, so a wall-clock deadline of 3-5 ms adds no safety beyond the iteration count.

**Severity.** Major: a false State 99 in normal operation, with no gate that measures it. The host tests of section
12.11 model the ladder RC but not a long iteration.

**Proposed fix.** Express each confirmation in iterations (for example, a settled reading within four iterations of
the edge), with a separate wall-clock cap set above the worst measured gap and below the pump hang time (for example
30 ms against the 43 ms minimum). Measure ladder persistence in consecutive iterations. Defer SD drain and Ag105 I2C
work on the iteration that writes a pin-33 edge. Add host tests with an injected 10 ms iteration at each entry, exit
and VOK edge, and a bench record of the iteration-time histogram in each window type (V2-4, W1).

### 2.4 FM3-4 (minor): `ERR_VCHG_FED` rests on one ADC channel with no in-service plausibility check

**Element.** Pin 38 (`CHG_VOLTAGE`, divider to full scale 29.27 V, ino:2030) and `ERR_VCHG_FED` (Table 16), which the
design names as the only closure of the one-fault D-BC-FC loop (note 1 of section 11; HR3 row of Table 17).

**Failure mode and scenario.** An open upper divider leg, an open ADC input or an ADC stuck low reads V_chg near 0 V.
`ERR_VCHG_FED` then never fires, and the regen-window precondition "V_chg reads below 11 V" passes. The channel's
health is exercised only where `chargerHasPower()` or the probe needs V_chg of at least 13.5 V: an FC window, a
configuration check or probe step 3. In Stage 2 on the vehicle that happens at most once per power cycle, because FC
windows run only in State 1 or State 98. A pin-38 failure after the configuration check leaves F17 a one-fault loop for
the rest of the power cycle. A void probe (V_chg below 13.5 V) "repeats at the next check" and raises no fault, so a
dead channel at the check can also pass silently if the readback is taken from an FC window.

**Severity.** Minor: two faults are needed (the sensor and the D-BC-FC short), and the design accepts latent single
elements elsewhere (F40). However, HR3 is stated as conditional on this one detector.

**Proposed fix.** Add a plausibility check in every regen pulse: after a VOK assert, V_chg must exceed 12 V within
t_D_ON + 3 ms (bounded by V2-0); a miss on two consecutive pulses latches a new `ERR_VCHG_SENSE` and refuses regen
windows. Make a void probe a deferred result that refuses regen windows. Add both to the host tests.

## 3. FMEA worksheet

The worksheet groups the elements by assembly. "Covered" names the design row, fault or gate that bounds the mode and
was checked against revision 5. Only modes that change the outcome are listed; modes whose effect is identical to a
listed row are folded into it.

### 3.1 Pack positive, F_PK, SB and the harness

| Element | Mode | Mode or transition | Effect | Disposition |
|---|---|---|---|---|
| F_PK | Open | Any | Board unpowered from the pack; body diodes keep VC1 positive | Covered: F34, B-FPK |
| F_PK | Undersized for a branch conductor | Any | Does not protect VBATN_X (0.5 mm2) | **FM3-2** |
| Pack-positive lead, SB taps | Short to SGND/PACK-/pack-negative | Any | 174-592 A prospective, F_PK in loop | Covered: F43 |
| F_T1, F_T2 | Open | Bonded; window | One S_GND channel off; in a window the S_CHG drive (from VBT_T1) is lost with F_T1, so charge flows through the S_CHG body diode and the board load through the S_GND body diodes (about 0.7 V) | Covered: F31 + F4; availability only |
| C_VTka/b | One short, both short | Any | Series pair; both short opens F_Tk | Covered: F31 |
| R_SH | Open | Any | Pack-negative open upstream of the Kelvin taps | Covered: F34b; see FM3-1 for the D_VM stress |
| R_SH Kelvin joints, R_K1/R_K2 | Open; KS pair short | Any | Undefined or zero output | Covered: F21, F44, `ERR_IPACK_PLAUS` |
| R_K1/R_K2 | Short (0 Ohm) | Any | KS lead loses its current limit | Latent; second fault (KS to pack+) gives F27 without R_K: accepted double fault (section 4) |
| S_GND1/S_GND2 | D-S short; open; gate leaky | All | Sense bypass; channel loss; parked gate | Covered: F1, F2a, F2, F42 |
| S_CHG | Short; open | All | Sense in parallel when bonded; body-diode charge | Covered: F3, F4 |
| Q_Ak, Q_C, Q_D, Q_Rk, Q_B | Short, open, G-D short | All | Channel loss, S_CHG lock lost, readback wrong | Covered: F2a, F42, ladder consistency; Q_A G-D short feeds 8.4 V through 14.7 kOhm into FF1Q_SB (0.57 mA into the U_BF clamp): benign |
| Zk, Z3 | Short | Any | Gate held off | Covered: F2a; Z3 short = S_CHG never on (F4 class) |
| Lead A / lead B | Open; both open | Any | Offset | Covered: F22, F22b |
| VBATN_X | Open | Window | No charge | Covered: F14 |
| VBATN_X | Short to GND | Window | Downstream bond | Covered: F12 |
| VBATN_X | Short to pack positive | Bonded and window | 17-164 A through the lead and the Ag105 sense | **FM3-2** |
| 7-way signal cable | Open | Inside / outside a window | Bonded by default; F1 on both channels in a window | Covered: section 9.10, F33 |
| 7-way signal cable | Conductor shorted to pack-positive copper inside SB | Any | FF1Q_SB: forced charge mode until U_C1; SGk_RB: LVC input above 6.5 V | Not filed: workmanship double-fault class; series resistors at the SB end of the four LB signals would bound it (recommendation, not a finding) |

### 3.2 Logic board (LB)

| Element | Mode | Effect | Disposition |
|---|---|---|---|
| U_FF (LVC74) | Q stuck HIGH; /PRE joint open (floating /PRE reads LOW) | Charge mode outside a window; with /PRE and /CLR both LOW, Q = /Q = HIGH | Covered: F7 (`ERR_CHG_LADDER`, State 99); the pack stays in the charge mode at board load in State 99 (bounded by U_C1) |
| U_FF | Q stuck LOW; CLK or /CLR open | FF1 cannot set; no clear | Covered: F32b, F32c |
| U_P33, U_N33, U_NP, U_CLS, U_CKS, U_BF | Stuck HIGH, stuck LOW, open | Lost clear layer or availability | Covered: F32, F32b, F32c, F32d |
| R_P33 | Open | Pin-33 Hi-Z no longer guaranteed LOW at U_P33 (LVC input floats) | Partly covered: B11c (warm reset) would show a set or slow clear; the i.MX pad keeper state at reset is TODO(verify: IMXRT1060RM). Bounded by the pump clear (43-76 ms) |
| Pump (U_PD, C_P1, C_P2, D_P1, D_P2, R_P2, U_PS) | C_P1 short, R_P2 open, D_P2 short | PUMP_OK stuck HIGH on a static pin | Covered: F9 (step 2), WDOG |
| D_NC1, D_NC2, D_NIM, D_N20, D_D5S | Short; open | Short holds N1 LOW (availability); open loses one clear | Covered: step 4, F40 |
| Q_OV, R_OVP, R_OVG, fly-wire | Open, short to GND | Open: refuses charging; short: OVP actuation lost | Covered: F25 |
| U_SH1/U_SH2, U_C1/U_C2, R_F, R_T, R_I | All | Lost trip or permanent trip | Covered: F8, F8b, F24, F41, steps 6-7 |
| U_IM, R_IMa/b, IMON wire | Open, stuck released | Start-into-overload bound lost | Covered: F40, S0-12b |
| U_D5, Q_D5, D_D5S | All | D5 cut lost or availability | Covered: F16, F40, step 6 |
| U_AND, U_OR, U_RS | Stuck HIGH | eFuse enabled without a source term | Covered: F13b, F15c; U_RS stuck HIGH is visible at step 4 (EF_EN L expected) |
| Q_X1, Q_X2, X network | Open | Cross-lock lost | Covered: F6, F16b, B10 |
| Ladders U_LA/U_LB, R-2R | Bit stuck, resistor drift | Undecodable or wrong code | Covered: `ERR_CHG_LADDER`, C-2 calibration; but see **FM3-3** for the persistence rule |
| VOK channels (Stage 2) | All | Covered: F15b, F15c, F15d, F29 | Covered |
| R_V1/R_V2/R_VPS, pin 23 | Open | V_PACKN out of range | Covered: `ERR_PACKN_RANGE` |
| BAL_OK (R_BL1, R_BL2) | R_BL1 short together with a chafed BAL_OK lead | Pack positive to GND through the balance positive wire | Double fault (section 4) |

### 3.3 Charger adapter (CB), the Ag105 and the existing switches

| Element | Mode | Effect | Disposition |
|---|---|---|---|
| U_EF (TPS26631/TPS26636) | FET short; SHDN stuck HIGH; start into overload | Ag105 powered without FF1; thermal regulation 2.3-2.9 s | Covered: F11, F35, F13, U_IM (DS2-1) |
| R_ILIM, C_DV, R_UV1/R_UV2 | Open or short | I_OL or UVLO shift | R_ILIM open gives the minimum limit per SLVSE94G (TODO(verify)); C_DV open gives a fast inrush: bounded by U_IM (1.71 A) and C-3; R_UV2 short holds the eFuse off: availability |
| Profile networks (R_CS1/R_CS2, Q_CS, R_MP, Q_MP) | All | 1.25-2.5 A or wrong threshold | Covered: F23-F23d, F38 |
| R_KA | Bridge | Pack tied to VCHG | Covered: F18 |
| M1, M2 cut gaps | Bridge | Sense bypass or eFuse bypass | Covered: F36, P-M1, C-4 |
| Ag105 | Internal switch across the sense; back-feed of its input; I2C ACK unpowered | Blind regulation; false reads | Covered: F19, S0-2, S0-7, the probe criterion |
| D-BT-SQ | Power-stage short; EN cut stub open | Pack tied to VCHG; D-BT-SQ disabled | Covered: F5 (latent after D-1), F6 |
| D-BT-EN | Power-stage short in an FC window | BT on the bus while the charger is fed | Covered: F16 (D5) |
| D-BC-FC | Power-stage short | One-fault loop in a regen window | Covered: F17, `ERR_VCHG_FED`; see **FM3-4** for the detector |
| D-BC-RG | Power-stage short | VCHG-IN = V-MOT | Covered: F15 |
| D-MT-EN | Reverse leakage or short | V-MOT tied to VBUS: VOK never asserts (availability); a short also lets the bus feed V-MOT-side loads, as today | Covered by VOK design (Table 9 item 1): with D-MT-EN shorted V-MOT = VBUS and VOK reads NOT OK |
| TPS61288 boosts | Running at VIN 2.0 V after a pack-negative open | 12-17.1 A drawn through the new return clamp | **FM3-1** |
| BQ29200 | OUT stuck LOW (internal) | OVP actuation lost | Covered: F25 (short form); BG-17 at build only |
| Balance lead (VBAL+, VMID) | VMID to GND through D_VM | Unfused cell-1 short | **FM3-1** |
| D_VM | Short; surge; leakage | Cell-1 short; surge failure; cell-1 drain | **FM3-1** |

### 3.4 Teensy pins and firmware states

| Element | Mode | Effect | Disposition |
|---|---|---|---|
| Pin 33 | Hi-Z (reset, boot, brown-out) | FF1 clear through U_P33/U_N33 | Covered: B11c |
| Pin 33 | Glitch HIGH (firmware defect) | FF1 sets outside a window | Covered: F7 class; `ERR_CHG_LADDER` |
| Pin 34 | Static; toggled from an ISR | Pump clear; hang detection defeated | Covered: F9, F20 |
| Pin 35, pin 10 | Stuck HIGH | Injection permanently on: FF1 cannot set (availability); profile wrong | Covered: step 1, F23 |
| Pin 20 | Not WDOG1_B, or push-pull HIGH | One hang layer lost | Covered: F9b, B11b |
| Pins 28, 30, 31, 32 | Stuck HIGH | Feed with both feeds commanded LOW; D-BT-SQ enable | Covered: `ERR_VCHG_FED`, cross-lock |
| Pins 16, 17, 21, 22, 23, 38, 41 (ADC) | Open, stuck low | Blind measurement | Covered for 16/17/21/22/23/41 by the self-test, cross-check and plausibility; **FM3-4** for pin 38 |
| Loop timing | One iteration of 3.9-9.76 ms near an edge | False entry, exit or ladder latch | **FM3-3** |
| Hang | Loop stopped | Pump clear 43-76 ms, RTWDOG | Covered: B11 |
| Brown-out with USB attached | Teensy stays alive at a pack-negative open | BT boost keeps drawing through the return clamp until `ERR_IPACK_PLAUS` (100 ms) | **FM3-1** |
| 3V3 slow collapse | LVC outputs track VCC | Bonded while the eFuse is enabled | Covered: F45, B11d |

## 4. Common-cause and double faults

Table 2 lists the double faults that reach one of the severe outcomes named in the brief. Each pair was checked against
section 11 of the design.

Table 2. Credible double faults with a severe outcome.

| Pair | Outcome | Current design position |
|---|---|---|
| Pack-negative open (F34b) during traction, then D_VM surge failure | The first event surges D_VM at 12-17.1 A; the short then shorts cell 1 when the intermittent contact recloses | Not covered: **FM3-1** (common cause: one intermittent connector) |
| D_VM short + any balance-plug or lead fault | Cell-1 short | Not covered: **FM3-1** (a single fault suffices) |
| VBATN_X chafe + F_PK resistive-fault region | 17-50 A for seconds in a 0.5 mm2 lead and the Ag105 sense | Not covered: **FM3-2** (a single fault suffices) |
| Pin-38 channel low + D-BC-FC short (F17) | Bus-fed loop in every regen window (HR3) | **FM3-4** |
| eFuse short (F11) + D-BT-SQ short (F5) during the eFuse-blocking probe | Bonded module powered with VBat- on GND (the ML0227 configuration) for up to 100 ms | Bounded: Q_X1 holds BT_BUS off for the whole probe (FCQ HIGH), so the ML0227 loop through the BT boost is open; the residual is an FC-bus charge with a blind sense, bounded by `OC_FC` 1.4 A. No finding |
| S_CHG short (F3) + both S_GND lost (F2) | Traction through the Ag105 sense | Covered: `ERR_SGND_OPEN`, F3 residual |
| R_K short + KS lead chafed to pack positive | F27 without its fusible limit: 100-270 A in a 24 AWG lead | Accepted double fault; R_K1/R_K2 have no in-service test. A 4-wire check of R_K at C-4 would bound the latency (recommendation) |
| U_C2 dead (F8b) + F1 in a regen window | Blind regulation bounded by U_IM and the eFuse | Covered: HR4 row |
| F_PK holder and pack connector resistance + 7.4 V pack at 17.1 A | VBT - GND at the 6.5 V LM1084 limit; Teensy brown-out in traction | Covered by section 7.6 (lead B margin of about 0.3 V); the F_PK holder resistance is TODO(verify) and decides it |

Three common causes span more than one barrier:

1. **The J-BL underside.** R_BL1 (VBAL+, pin 1), D_VM (pin 2 to pin 3) and the M12 epoxy fill share one 3-way terminal
   at 7.62 mm pitch, two of whose barrels are solid to both GND pours. One solder bridge or a cracked part there joins
   an unfused balance conductor to GND (FM3-1).
2. **The SB-to-motherboard harness run.** The 2.5 mm2 pack-positive lead, the 0.5 mm2 VBATN_X lead and the KS twisted
   pair leave SB together. One abrasion point can reach all three; only the KS pair has a series limit (FM3-2).
3. **The loop iteration time.** One long iteration affects every wall-clock confirmation at once (FM3-3).

## 5. Evidence

- Design: `detailed_design_IC1.md` revision 5, sections 4.1, 4.2 (rule C1), 5.5 (M1, M16), 7.7, 9.5, 9.7, 11 (F34b, F17,
  note 1), 12.4 item 4, 12.6 (Table 16), Table 11, Table 17.
- Board facts: `facts_board.md` sections 2.3 (balance network, RB3 260 Ohm, RB1A 100 Ohm), 3.3 (TPS61288 VIN 2.0-18 V,
  switch limit 12/15/17.1 A, SLVSFP3C sections 7.3 and 7.5), 4.2 (Ag105 VLoad-/Vin- internal connection, I_DIS 4 A,
  DS p.20 row 6).
- Firmware facts: `facts_firmware.md` section 8 (loop 1131 us median, 9.76 ms worst, 2.4 ms I2C interval);
  `teensy_controller.ino` line 2266 (`UV_BATT_DWELL_LATCH_MS` 1000 ms), line 2096 (`LIMIT_V_BATT_MIN`), lines 8298-8345
  (State-99 teardown).
- Calculations: `calc/fmea_round3_calcs.py`, output `calc/fmea_round3_calcs_output.txt` (sections 1, 1b, 2, 3, 4).
- External: Nexperia PMEG2005EB data sheet characteristics (V_F 320-380 mV at 100 mA; I_R 7 uA typical, 30 uA
  maximum at 10 V, 25 C), read through a WebSearch result summary only: UNCONFIRMED until the PDF is read. IEC
  60364-4-43 copper/PVC adiabatic constant k = 115. Blade-fuse opening times TODO(verify: fuse datasheet).
