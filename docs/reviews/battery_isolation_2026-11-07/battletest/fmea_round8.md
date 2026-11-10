# Battle-Test Round 8: Delta FMEA of the Revision-8 Hardware and the Revision 9-11 Rules

Target: `detailed_design_IC1.md` revision 11. Lens: delta FMEA (short, open, stuck, drift, reversed, intermittent)
of R_VC1c, R_MS3, R_BL3/R_BL2, R_PGL, the D_VC1 clamp as specified, the two signal sleeves of section 5.7 item 4
(revision 8, R8-3), and the revision 9-11 firmware rules listed in Appendix I. Calculation:
`calc/bt8_fmea_rev8_sleeve.py` (output `calc/bt8_fmea_rev8_sleeve_output.txt`, cited "bt8 section N"). New primary:
TI SLVSE94G (TPS2663x, September 2018, revised June 2024), section 6.5, "Low IQ shutdown (SHDN) input", read in this
round. The purge predictor and the unpredicted-purge collapse are out of scope (rulings OR-P, OR-SC).

## 1. Result

One finding survives: **BT8-FM-01 (Major)**. Every other delta row is fail-safe, loud, or a documentation-level
inconsistency that does not change an outcome; section 3 records them so that a later round does not repeat the work.

| ID | Severity | Title |
|---|---|---|
| BT8-FM-01 | Major (damage class) | An MD_G-SHDN_EF short inside the revision-8 CB-LB sleeve parks both the eFuse SHDN pin and the Q_MD gate at 1.6 V in both EF_EN states |

## 2. Finding BT8-FM-01: MD_G-SHDN_EF short in the shared CB-LB sleeve

### 2.1 Claim

Revision 8 (R8-3, section 5.7 item 4) routes SHDN_EF, EF_FLT_N, IMON, PROFILE, MD_G and MS in one sleeve, the CB-LB
sleeve. A GND conductor is required only between MS and SHDN_EF. A single insulation failure between the adjacent
conductors MD_G and SHDN_EF joins two LVC outputs that always drive opposite levels (U_MDI = NOT EF_EN) through
equal 1 kOhm resistors (R_SD, revision 4; R_MDS, revision 7). The joined node then sits at **1.594-1.626 V in both
EF_EN states** (bt8 section 1). Two consequences follow:

1. **The eFuse SHDN level is indeterminate in both states.** SLVSE94G section 6.5 guarantees shutdown only below
   V(SHUTF) = 0.8 V (minimum) and turn-on only above V(SHUTR) = 2.0 V (maximum). At 1.6 V the eFuse is on or off
   per unit and per history. When it reads ON, EF_EN no longer actuates the eFuse: a clear of FF1 by U_C1, U_C2,
   U_IM, D5 or Q_OV (BQ29200 OVP) no longer removes module power. The re-bond and the D-BT-SQ cross-lock remain,
   so the pack is not left on an unregulated charge path by this fault alone; however, one of the three hardware
   actuators is gone with no indication (ladder A bit 1 reads EF_EN at the U_AND output, not the SHDN_EF level).
2. **Q_MD is biased into its linear region whenever the module node is fed.** Q_MD is a TODO(select) "logic-level
   N-MOSFET" (Table 7) with no V_GS(th) bound in the specification. A part whose threshold band covers 1.6 V
   conducts partially. With the node at 15.5-17.5 V behind R_MD 15 Ohm, Q_MD dissipates up to 4.00-5.10 W
   (I_Q = V/(2 R_MD)), and 3.45 W at I_Q = 0.30 A (bt8 section 2).

### 2.2 Failing scenario (Stage 1, no gate catches it)

1. Vibration chafes the MD_G and SHDN_EF insulation inside the CB-LB sleeve. The unit's eFuse reads ON at 1.6 V; the
   fitted Q_MD conducts I_Q between 0 and 0.31 A at V_GS = 1.6 V.
2. Bonded Idle: VCHG-IN is unfed, so nothing happens and nothing is detected.
3. First FC-window request: the dump check (section 9.7b) compares the FC_CURRENT step against 0.4 A. With the
   module input at most 9 mA (pin 32 LOW), any I_Q up to 0.391 A passes. The positive control of U_MS passes
   (pin 8 follows the node, which is fed). The exit hold check passes (pin 8 does not follow EF_EN). A pass is
   recorded.
4. The FC window opens. FC current = 0.15 A aux + 0.838-0.936 A module input (Table 8 power at the calc11
   in-window V_chg) + I_Q. `OC_FC` (BENCH_TEST 0 only) trips only for I_Q above 0.314-0.412 A; U_IM only above
   0.574-0.672 A (bt8 section 2). For I_Q at or below 0.314 A the window runs to the 30 s cap with Q_MD at up to
   3.40 W and R_MD at 1.48 W (44.5 J in 30 s, against the CC-18 design duty of 0.095 W mean and the 1.71 J
   single-pulse probe cap).
5. A SOT-23-class FET reaches T_J 150 C at 40 C ambient for 0.31-0.88 W (R_thJA 125-350 K/W, an ASSUMED class
   range; the part is not selected). Q_MD therefore overheats within the window. Its threshold falls with
   temperature, so the current moves through the 4.3 W peak at 0.53 A before OC_FC or U_IM can act. Q_MD fails
   (open: `ERR_MOD_DRAIN` at a later exit; short: row F50, with R_MD at 17-20 W until the Fully Charged exit in the
   corner that section 5.3 item 1 already names). The CB sits beside the Ag105 (section 5.7 item 3).

The configuration-check probe (section 9.7a) would read pin 8 HIGH with EF_EN L and latch `ERR_EFUSE_BYPASS`, but it
runs only before Stage-2 regen windows, and only after the module has been powered through `AG105_SETTLE_MS`
(500 ms) with Q_MD in the same linear state. In Stage 1 the probe never runs on this path.

### 2.3 Why earlier rounds did not catch it

Round 4 (`fmea_round4.md` line 257) classed the MD_G-SHDN_EF short as an "inverted eFuse enable" that the positive
control and the probe detect ("loud"). That was true in revision 6, where U_MDI drove MD_G directly and won the fight
(node 0.08 V with EF_EN H, 3.22 V with EF_EN L; bt8 section 1). Revision 7 added R_MDS 1 kOhm (the MD_G
short-to-GND current limit, Table 7), which equalised the two source resistances and turned the inversion into a
mid-rail level. Revision 8 then put both leads in one sleeve and guarded only the MS-SHDN_EF pair. No gate tests
lead-to-lead insulation inside a sleeve: gates C-1 and C-4 test each sleeved lead against VBT and the VCHG-IN lead
only (section 15, rows F54b/F54c), and C-2a item 27 shorts MD_G to GND only.

### 2.4 Other pairs in the same sleeve (checked, loud or benign)

bt8 section 3 evaluates the remaining pairs. MD_G-IMON and SHDN_EF-IMON put 2.9-3.0 V on U_IM IN- in one EF_EN state
and refuse FF1 set or trip at entry. SHDN_EF-EF_FLT_N and MD_G-EF_FLT_N read a false FLT (0.29-0.30 V) in one state.
PROFILE-MD_G and PROFILE-SHDN_EF leave both actuators correct (PROFILE is behind R_PGL 22 kOhm, so the driven lead wins:
0.14 V / 3.13 V); the profile then follows NOT EF_EN or EF_EN, which at worst selects the 18 V regen threshold in an
FC window (no charge). PROFILE-MS puts 1.40 V on MS_D while cold and latches `ERR_MOD_DRAIN`. MS-SHDN_EF (F55) is
unchanged by R_MS3 (lead node 3.15 V / 0.19 V; R_MS3 with about 5 pF of IN+ capacitance adds about 0.1 us against
the 150 us hold-check wait). MD_G-SHDN_EF is the only pair that is both silent and damaging.

### 2.5 Recommended fix

1. **Routing (preferred, no new circuit):** extend the section 5.7 item 4 guard rule to MD_G: MD_G and SHDN_EF never
   adjacent, with a GND conductor between them (or MD_G in its own sleeve). Add a lead-to-lead insulation test for
   every pair in the CB-LB sleeve to gates C-1 and C-4 (at least the MD_G-SHDN_EF and MS-SHDN_EF pairs).
2. **Or make the fight decisive (part-value change):** for example R_MDS 10 kOhm against R_SD 1 kOhm, so that a short
   gives SHDN_EF's level on MD_G (Q_MD on with EF_EN H: a 1.07 A dump that the dump check latches at more than
   0.4 A; Q_MD off with EF_EN L: `ERR_MOD_DRAIN` at the first exit). This needs a re-check of the Q_MD turn-off time
   at the eFuse start (section 5.3 item 1 assumes about 1 us) and of C-2a item 27.
3. **Bound Q_MD:** whichever option is taken, Table 7 should state a V_GS(th) range and a linear-mode SOA for Q_MD,
   because any mid-rail gate fault (this one, an LVC output degraded by a chafe of row F54c) otherwise reaches the
   same multi-watt state.
4. **Gate:** add a C-2a item that shorts MD_G to SHDN_EF at CB with the charger unpowered and with a current-limited
   feed, and records the eFuse state, the Q_MD gate level and the latch that results.

## 3. Delta FMEA rows with no finding

| Part or rule | Mode | Effect and detection | Evidence |
|---|---|---|---|
| R_VC1c | Open or intermittent | Pin 20 holds its last value on C_VC1 (charge-sharing drift 20-400 s at 1 kHz-50 Hz reads with an ASSUMED 5 pF sample capacitance). `ERR_CELL_MISMATCH` latches only when the pack moves by 80 mV, so a D_VC1 short that coincides with the open is detected late (double fault). Fail-safe direction. | bt8 section 4; Appendix F item 1 |
| R_VC1c | Short | Revision-7 behaviour (no injection limit); tap ratio unchanged | Section 5.2 |
| R_MS3 | Open or intermittent | IN+ floats on pF; an intermittent crack acts as a sample-and-hold. Frozen LOW: positive control fails (`ERR_MOD_SENSE`), or, if frozen after the positive control, the exit drain passes early; the hardware dump Q_MD still drains the node in 1.3-2.9 ms and the D-BT-SQ cross-lock opens with FF1, so no ML0227 path forms. Frozen HIGH: `ERR_MOD_DRAIN`. A freeze between the positive control and the probe can mask an eFuse bypass (double fault). | Section 5.3 items 1, 3; Appendix F item 2 |
| R_BL3, R_BL2 | Leakage at the LVC input limit | BAL_OK = VIH at 6.92 V pack with 5 uA (TODO(verify: TI)), below the 7.4 V floor; worst effect `ERR_BAL_ABSENT` (refusal, not latched) under a deep traction sag | bt8 section 4; Appendix F item 3 |
| R_BL3 | Statement | Section 5.7 item 4 says neither sleeve carries a conductor above 3.6 V; the BAL_OK lead sits at 4.21 V at an 8.5 V pack behind 74 kOhm. Not a hazard source; the sentence should say "no conductor that can source more than about 0.1 mA above 3.6 V". | bt8 section 4 |
| R_PGL | Value, open | Q_CS/Q_MP gates at 2.52-2.68 V (BSS138 V_GS(th) maximum 1.5 V). Open: gates pulled LOW by R_PGP, 18 V threshold in an FC window, no charge | bt8 section 4; Appendix F item 4 |
| D_VC1 | As specified | Feasibility conflict unchanged and correctly held UNCONFIRMED behind B8 and OR-AC; no new failure path found | Table 7; R8-4 |
| Rev 11 fixed split | Restore timing | The restore follows the BT_BUS write by one iteration and precedes RT1987 conduction (t_D_ON 8-12 ms); no MDAC write with both switches conducting found | Section 9.7 exit step 4 |
| Rev 11 Idle FC_BUS release | Hot-plug | `busHotPlugUnsafe()` tests V_bus only (ino:13043-13045); the release closes FC_BUS onto a battery-fed bus that is already in band, the normal Run topology; during a purge the ideal diode blocks and the FC restarts into the joined bus as in Run | ino:13043; section 12.4 item 9 |
| Rev 11 request flag | Corruption | Byte 20 (`droop_enable_reserved`, ino:7525) is inside the XOR checksum span (bytes 1-20 against byte 21, ino:7488-7490); a single-byte error is rejected | ino:7488-7528 |

## 4. Appendix I items not closed by this round

Appendix I items 1, 2, 5 and 6 (the State-2 dump check duration, the hold discipline of byte 20 in the firmware
round, the State-98 bring-up keys against the boost-enable condition, and the 15 ms iteration criterion) are
firmware-round or bench items; this round found no damaging path in them on the document text.
