# Battle Test Round 2: FMEA of IC1 Detailed Design Revision 4

Date: 2026-11-07. Target: `detailed_design_IC1.md` revision 4 (cited "DD section N" or "DD line N"). Lens: exhaustive
failure-mode and effects analysis of every new element and every existing path element that it touches, in every mode
and transition, followed by common-cause faults and credible double faults for the severe rows.

Calculations: `calc/fmea_round2_calcs.py`, output `calc/fmea_round2_calcs_output.txt` (cited "R2C section N"). Other
values come from DD, `calc/ic1_rev4_calcs_output.txt` (cited "calc4 section N"), the fact sheets of this study, and the
following primaries: BQ29200 SLUSA52C (repository copy `references/Datasheets/BQ29200_TI.pdf`, sections 7.5, 8.1-8.4,
read for this round), `references/Scale_Car_Board_20260624.sch` through `facts_board.md`, and
`teensy_controller/teensy_controller.ino` (cited "ino:line"). Values with no primary are marked ASSUMED, UNCONFIRMED or
TODO(verify: source).

Severity follows the brief: **blocker** = unsafe or cannot work and no gate catches it; **major** = a real defect that
needs a design change or a hard bench gate; **minor** = documentation or margin. Findings already adjudicated in round 1
(DD Appendix B) are not repeated unless the revision-4 fix is wrong or incomplete; where that is the case the finding
names the round-1 item.

## 1. Summary of findings

Table 1 lists the findings. Section 2 gives each finding in full. Section 3 gives the FMEA worksheet. Section 4 gives the
common-cause and double-fault analysis.

Table 1. Findings.

| ID | Severity | Title |
|---|---|---|
| FM2-1 | blocker | The revision-4 fuse move leaves the SB pack-positive copper and the pack-to-SB leads unfused, next to pack-negative copper |
| FM2-2 | major | All seven hardware clears funnel through N1, U_CLS and one /CLR pin; three diode shorts and one buffer fault defeat every comparator clear, and U_C2 has no other path |
| FM2-3 | major | A KS+ to KS- short blinds U_C1 and U_C2 together, reads 0 A on both channels and passes every self-test; the claimed bus-current plausibility check does not exist |
| FM2-4 | major | Q_D5's body diode drags D5_N to 0.65-1.02 V whenever N1 is LOW: self-test step 1 and step 6 fail on a healthy board, and ladder B bit 4 is undefined in every bonded state |
| FM2-5 | major | A negative SGND offset of 0.84-1.65 V turns S_GND off and S_CHG on in the bonded mode; with both return leads open the board return closes through the Ag105 sense in reverse |
| FM2-6 | major | An open anywhere in the pack-negative chain upstream of R_SH browns the Teensy out and drives BQ29200 VC1 to about -0.6 V: the BT1-DS-04 fix covers F_PK only |
| FM2-7 | major | The second element of the HR3 regen-loop barrier and of the bonded ML0227 barrier is latent in service: D-BC-RG/D-BC-FC shorts have no defined fault, and ERR_EFUSE_BYPASS cannot fire |
| FM2-8 | major | Stage 2 regen windows need a per-power-cycle configuration check that requires FC_CHARGE_ALLOWED 1, an FC-only bus (Q_X1) and the OR-P purge permit; none is in the Stage-2 prerequisites |
| FM2-9 | major | The Idle-entry self-test is specified as a 420 ms direct poll with the bus live: `detectFaults()` stalls, and no rule covers a Run request during it |
| FM2-10 | minor | The design asserts I_o <= 2.5 A as structural; nothing bounds I_L, and the design's own 1.4 A figure gives 3.15 A |
| FM2-11 | minor | The commissioning refusal guards pin 33 against pin 32 HIGH but not pin 32 rising while FF1 is set; J-NTC is not named in rule C2 and C-1 runs pack-absent |

The FMEA confirmed the following revision-4 claims: in Stages 1-2 no single fault powers the charger in the bonded mode
(EF_EN needs FF1.Q, and the D-BT-SQ cross-lock then limits any output path to R_KA); the buffered pin-33 path clears FF1
on a Teensy reset (calc4 section 6); no switch state can open the pack return, because the S_GND body diodes carry the
discharge direction whenever S_GND and S_CHG are both off; a shorted single gate tap, a cracked C_VT part or a lost single
VOK tap now fails toward a safe or detected state; and no IC1 path changes MOT_PWR, so no IC1 transition creates a
Death-5 hot-plug.

## 2. Findings

### 2.1 FM2-1 (blocker): the revision-4 fuse move leaves the SB pack-positive copper unfused

**Claim.** Revision 4 moved F_PK from the pack-negative lead to the pack-positive lead **downstream of SB**, with the two
gate taps upstream of it: "Pack positive passes SB as a continuous 2.5 mm2 lead with two soldered tap points, then
through F_PK to J-BT pin 1" (DD section 4.1); Figure 1 draws `pack(+) ─┬── F_PK 20 A ── J-BT pin 1` with taps 1 and 2
on the pack side of F_PK; Table 7 places F_PK in the "harness (pack-positive lead)". The pack connector is "at the SB
input" (M14). Therefore the pack terminals, the pack leads, the keyed pack connector, the SB pack-positive conductor and
both tap solder pads (upstream of F_T1/F_T2) carry pack positive with **no fuse in the loop**, on the same small 2-layer
board as SGND, PACK-, the S_GND sources and lead A/lead B. In revision 3 the same copper was protected, because F_PK in
the negative lead was in every pack loop (concept dossier Figure 1: `PACK- ─ F_PK 20 A ─ R_SH`).

**Failing scenario.** One insulation, solder-splash or vibration fault inside SB between the pack-positive copper (or a
tap pad) and SGND, PACK- or the pack-negative conductor is a direct pack short through 1-4 mOhm of copper and the pack
internal resistance: 182-576 A at an ASSUMED 10-40 mOhm 2S internal resistance (R2C section 7). F_PK is not in that loop.
The only remaining limit is an unknown pack protection board (facts_prior section 9: PCM "Unknown"). No gate tests this
in service: C-1 is a one-time, pack-absent audit with a 0.1 A supply.

**Why the revision-3 concern does not return if the fuse moves to the pack end.** BT1-DS-04 was about pack negative
losing its bond when the fuse opens. With F_PK at the pack positive terminal and the taps downstream of it, an open F_PK
removes both gate supplies, both S_GND channels turn off, and their body diodes (anode SGND, cathode PACK-) keep pack
negative within one diode drop below GND for the BQ29200 supply current (pack(+) via VBAL+ and RB1B to BQ VDD, BQ GND,
SGND, body diode, R_SH, pack(-)). VC1 - GND then equals V_cell1 minus about 0.3-0.5 V, which is positive.

**Proposed fix.** Fit F_PK (or a second fuse) at the pack connector, pack side, upstream of every SB conductor and both
tap points; keep the taps downstream of it. Add a row to Table 14 for an SB-internal pack-positive short and a B-FPK
variant that repeats the VC1 check with the fuse at its new position. If the pack carries a PCM with a short-circuit
trip, record its threshold and delay as the primary bound (pack datasheet, open item 6).

### 2.2 FM2-2 (major): every hardware clear funnels through N1, U_CLS and one /CLR pin

**Claim.** The seven hardware clear sources (P33B, PUMP_OK, UC1_N, UC2_N, WDOG1_B, D5 through Q_D5, BQ29200 OUT through
Q_OV) reach FF1 only through the wired-AND node N1, the Schmitt buffer U_CLS and the single /CLR pin of U_FF (DD Figure 2,
equation 1). Three of the sources are **push-pull** outputs joined to N1 through one BAT54 each: P33B (U_P33,
SN74LVC1G17), PUMP_OK (U_PS, SN74LVC1G17) and pin 20 (WDOG1_B). U_C2 acts **only** through N1: UC2_N has one member
besides the comparator, D_NC2 (DD Table 4). U_AND gates the eFuse with FF1.Q, PUMP_OK and SRC only.

**Failing scenarios.**

1. **D_N33, D_NP or D_N20 shorted.** N1 is then driven by a push-pull LVC output (P33B, PUMP_OK) or the i.MX pad. When
   that output is HIGH (pin 33 HIGH in a window, or the pump running), the open-drain TLV3011B outputs of U_C1, U_C2 and
   U_D5 cannot pull N1 below VT- 0.89-1.20 V through a BAT54 against an LVC driver: the comparator clears are lost.
   With D_N33 shorted, a pump stop gives a contention between two push-pull outputs through a BAT54, which leaves N1
   near mid-rail, inside the U_CLS hysteresis band (VT- 0.89-1.20 V, VT+ 1.48-1.92 V, DD Table 7), so the pump clear is
   also UNCONFIRMED. Only pin 33 LOW (firmware) and Q_OV (a direct FET, no diode) still clear.
2. **U_CLS output stuck HIGH, or its input or the /CLR pin open and floating HIGH.** No source can clear FF1. DD row F32b
   classifies "U_CKS or U_CLS stuck" as "as F32 ... availability only"; that is wrong for the stuck-HIGH case, because
   F32 relies on the pump clear, which also passes through U_CLS.
3. **D_N33 open.** Pin 33 LOW no longer clears FF1, so the FM-7 reset clear (HR5) is lost silently. No self-test step
   tests "pin 33 LOW alone clears FF1": steps 6-8 clear FF1 by injection or by the pump (DD section 9.3). The first window
   exit catches it (`ERR_CHG_EXIT`), but a reset inside a window then relies on the 43-76 ms pump clear.

**Consequence.** In scenarios 1 and 2, a U_C2 trip (F1, F12, F19, F33, F38) does nothing in hardware: FF1 stays set,
the eFuse stays enabled, and `ERR_CHG_TRIP` does not fire because FF1.Q stays HIGH. The remaining bounds are the eFuse
I_OL and the firmware `ERR_PROFILE_OC` (20 ms). A sense-blind Ag105 drawing just below I_OL min 1.84 A at 18 V
(33 W, about 3.3 A of pack current at 8 V and efficiency 0.88) is not bounded by the eFuse at all. A U_C1 trip still
re-bonds through D_Ak, but with FF1 set and the eFuse on this is the powered-charger, bypassed-sense configuration
(S_GND on, S_CHG off by Q_D) until firmware acts. The HR4 row (DD section 13) credits U_C2 as an independent hardware
bound; with one latent small-signal fault it has no actuator. Detection is at the next Idle-entry self-test only, so the
fault is latent across a whole Run of regen windows.

**Proposed fix.** (a) Make every N1 source open-drain: replace the BAT54 joins of P33B, PUMP_OK and WDOG1_B with
open-drain buffers (for example SN74LVC1G07, TODO(verify: TI datasheet)) or BSS138s, so that no single short creates a
stiff pull-up on N1. (b) Give U_C2 (and BQ OUT) a second actuator that bypasses N1 and FF1: an additional input of the
eFuse AND (UC2_N into U_AND as a fourth term, for example a cascaded SN74LVC1G08). (c) Add self-test steps that exercise
each clear source alone (pin 33 LOW alone; pump stop alone; WDOG1_B by B11b), and correct F32b.

### 2.3 FM2-3 (major): a Kelvin-pair short blinds both current channels and passes every test

**Claim.** U_SH1 and U_SH2 share the single Kelvin pair KS+/KS- (DD Figure 3; G3 "on the same Kelvin pair"). A short
between KS+ and KS- anywhere after R_K1/R_K2 (the twisted pair, its keyed connector, the LB inputs) forces both amplifier
differential inputs to zero. R_SH is shunted by 4.4 Ohm, so nothing fuses (R2C section 3).

**Failing scenario.** Both outputs sit at 1.650 V at any pack current: I_PACK1 = I_PACK2 = 0 A. U_C1 and U_C2 never trip
(0.150 V and 0.157 V from their thresholds). The signal-side injection still pulls SIG to 1.3948 V, so self-test steps 6
and 7 pass. Step 9 and `ERR_IPACK_XCHK` see a difference of 0. Every other check is gated on I_PACK1 and never evaluates:
the sense-path check (>= 0.2 A), `ERR_SGND_OPEN` (> 1 A, the only bound on F2), `ERR_RET_DEGRADED` (>= 5 A) and
`ERR_PROFILE_OC`. `ERR_ISO_MISMATCH` would detect it, but only in an FC window with valid reads; a configuration check
runs with pin 32 LOW, so the pack current and reg 0x06 are both near 0 and it does not detect it. DD row F21 lists
"I_PACK implausible against the bus currents in the bonded mode" as a detection, but Table 16 defines no such fault.

**Consequence.** One cable fault silently removes both hardware current trips, the F2 detector and the profile-fault
detector. In Stage 2 regen windows on the vehicle (no FC window per power cycle, see FM2-8), nothing detects it, so F1,
F19, F33 and F38 are then bounded by the eFuse I_OL alone (DD Table 10). The G3 claim of two independent channels ends
at the shared Kelvin pair.

**Proposed fix.** Define `ERR_IPACK_PLAUS`: in the bonded mode with BT_CURRENT (pin 41) above about 1 A, I_PACK1 must lie
within a calibrated band of the BT boost input current derived from BT_CURRENT x V_bus / (V_batt x eta) plus the LM1084
load (TODO(calibrate), C-2); latch after 50 ms, refuse windows. Make a passing plausibility check an entry condition of
every window. Alternatively add a Kelvin-side injection (a known current through R_SH or a series test resistor) to the
self-test. Add a C-2 step that shorts KS+ to KS- and confirms the new fault.

### 2.4 FM2-4 (major): Q_D5's body diode makes the D5 ladder bit and two self-test steps fail on a healthy board

**Claim.** Q_D5 is a BSS138 with D = N1, S = D5_N, G = FCQ delayed; D5_N is pulled to 3V3 through R_UD5 10 kOhm and is
ladder B bit 4 (DD Figure 3, Table 4). The intrinsic body diode of an N-MOSFET has its anode at the source. Whenever N1
is LOW (every bonded state, because P33B LOW pulls N1 to at most 0.20-0.32 V, calc4 section 6; and whenever any clear
source is active), the body diode conducts about 0.24 mA from D5_N into N1.

**Failing scenario.** D5_N sits at N1 + V_SD = 0.65-1.02 V (R2C section 2, V_SD ASSUMED 0.45-0.70 V at 0.24 mA)
instead of 3.3 V. That is LOW or undefined for the SN74LVC244A (V_IL max 0.8 V, V_IH min 2.0 V). Self-test step 1
expects "D5_N H unless BT_CURRENT is above 0.3 A" with FF1 clear, and step 6 expects "Set pin 35 LOW; expect D5_N H" while
U_C2 still holds N1 LOW. Both fail on a correctly built board, so `ERR_CHG_SELFTEST` latches at every boot and every
window is refused. If the input sits near the threshold, ladder B is undecodable in every bonded state and
`ERR_CHG_LADDER` latches after 3 ms (DD section 12.4 item 4). Inside an FC window, any other clear source also drags
D5_N LOW through the channel, so a U_C2 trip is recorded as a D5 trip.

**Proposed fix.** Block the reverse path: put a BAT54 in series between N1 and the Q_D5 drain (anode at N1, consistent
with the other N1 joins), or derive the clear from an AND gate (D5 trip AND FCQ armed) into an open-drain N1 input
(compatible with FM2-2 (a)), and take ladder B bit 4 from the U_D5 output before any FET. Add the bonded-state D5_N
level to the C-2 ladder calibration.

### 2.5 FM2-5 (major): a negative SGND offset turns S_GND off and S_CHG on in the bonded mode

**Claim.** FF1Q_SB LOW is PCB GND at LB. The Q_A gates see it through R_GAk 4.7 kOhm / R_PAk 100 kOhm and the Q_C gate
through R_CQ 10 kOhm / R_PC 100 kOhm, all referenced to SGND (DD Figure 1). When SGND sits below PCB GND by V_off, both
FETs see a positive V_GS of 0.955 V_off and 0.909 V_off. Q_A conducts at an offset of 0.84-1.57 V and Q_C at
0.88-1.65 V over the BSS138 threshold range (R2C section 1); the threshold falls with temperature
(TODO(verify: BSS138/D threshold-temperature figure)). Q_A ON pulls both S_GND gates down, which also releases Q_D, and
Q_C ON drives S_CHG on: the offset alone produces the charge-mode switch state with FF1 clear. DD section 4.2 item 1
checks only lead A alone (369 mV at 17.1 A) and a margin to 0.8 V.

**Failing scenarios.**

1. **Both return leads open** (lead A screw loosened and the lead-B joint cracked; both land on the same J-BT pin-2
   barrel, M13 is a hand joint to a 288-via pour). The board return has no low-resistance path, V_off rises, S_CHG
   closes, and the board return flows GND -> Vin- -> Ag105 sense (reverse) -> VBATN_X -> S_CHG -> PACK-. The circuit
   self-biases: below about 13.5 A the sense chain drop (R_chain about 62 mOhm, working figure) is smaller than the Q_A
   threshold offset, so S_CHG settles in the linear region with up to about 2.8 W at 7.2 A, and the Ag105 sense carries
   the full traction return in reverse, above its 4 A I_DIS (R2C section 1). `ERR_SGND_OPEN` compares -V_PACKN with
   V_D,min + I x R_allow, a criterion tuned to a body-diode drop; at an offset near the minimum Q_A threshold it may not
   fire (UNCONFIRMED). The SG readback is ambiguous because Q_Rk switches at twice its threshold.
2. **Degraded return.** R_ret above 49 mOhm at 17.1 A (116 mOhm at 7.2 A) reaches the minimum threshold. Lead B open
   leaves lead A at 21.6 mOhm, so about +27 mOhm of contact degradation at the J-BT screw (20 mOhm rated maximum,
   TB005-762 p.1) suffices. `ERR_RET_DEGRADED` (+5 mOhm at >= 5 A) detects lead B open first, which is the only reason
   this path is not reached gradually.
3. **Inductive or fault-current offset.** During a board-side VBT short (the boost-death class) before F_PK clears, a
   few hundred amperes through 1.87 mOhm of return leads gives 0.5 V or more plus L di/dt; both S_GND channels can be
   turned off together, which transfers the fault current to their body diodes. The CSD18510Q5B pulse rating against
   the F_PK clearing I2t is TODO(verify: SLPS632, fuse datasheet).

**Consequence.** A common cause for "both S_GND off" exists outside the one DD names (pack positive open, DD F2 and
section 5.1), and the double fault of scenario 1 produces an ML0227-adjacent configuration (the board return through
the Ag105 sense) with the charger unpowered, bounded only by firmware.

**Proposed fix.** Raise the offset immunity of the SB inputs: drive FF1Q_SB from 5 V and put a 3.3 V Zener (or a
BAT54 plus a resistor divider) in each SB gate input so that turn-on needs at least 3 V of FF1Q_SB above SGND; or
reference the SB gate drive to SGND through an optocoupler or a digital isolator. Add a hard C-2 step: lift lead A and
lead B together with a current-limited 7.4 V supply as the pack, load the board at 1, 3 and 7 A, and confirm that
S_CHG stays off and that a defined fault latches. Add a both-leads-open row to Table 14.

### 2.6 FM2-6 (major): a pack-negative open upstream of R_SH reverse-stresses the BQ29200 (BT1-DS-04 fix incomplete)

**Claim.** BT1-DS-04 (major, round 1) found that an open F_PK in the negative lead drove BQ29200 VC1 below -0.3 V; the
revision-4 fix moved F_PK (DD R4-2, F34). The mechanism belongs to every series element between pack(-) and the S_GND
body diodes: the pack connector negative contact (M14, a single keyed 30 A connector), the pack-negative lead, R_SH and
its two solder joints. M12 removes the J-BL position-3 negative, which on the original board was a parallel return
(facts_board section 2.2). No row of Table 14 covers R_SH open or the pack-connector negative contact open; round 1
row SB-3 marked R_SH open "OK" with the BQ29200 stress UNCONFIRMED.

**Failing scenario.** With the pack negative open upstream of R_SH and the balance plug connected, the board return can
only flow through the BQ29200 input clamps: board GND -> BQ GND -> VC1 and VC1_CB clamps -> RB3 260 Ohm || RB1A
100 Ohm -> VMID -> cell 2 -> pack(+). VC1 sits at about -0.6 V (absolute maximum -0.3 V, SLUSA52C section 7.1), pack(-)
sits at -4.3 to -4.8 V against GND, so the KS+ common mode is below the INA240 -4 V operating range, and the board
supply is limited to about 43-50 mA (R2C section 4; clamp drop ASSUMED). The Teensy browns out in Run (LM1084 needs
6.5 V, SNVS037H section 5.5) with the motor command frozen until the VESC timeout. The design's own warning (DD section 15:
"A balance plug connected without pack negative drives the BQ29200 VC1 input below its -0.3 V limit") treats this as a
mating-order procedure, but in service it is a single component or contact failure.

**Proposed fix.** Protect the BQ29200 inputs against a negative VC1 (for example a low-leakage Schottky from GND to VC1
and VC1_CB at the BQ29200, with the SLUSA52C input-resistor limits rechecked, TODO(verify: SLUSA52C section 7.6)), or
add a clamp from SGND to pack(-) upstream of R_SH that conducts only beyond the U_C1 operating range (rated for the
board load, and checked against the F12b bypass it creates in the discharge direction). Add Table 14 rows for R_SH open
and the pack-connector negative contact open, and a gate that opens pack negative at the SB connector with the balance
plug and USB connected and records VC1 - GND and the INA240 input voltages.

### 2.7 FM2-7 (major): the second element of the HR3 and bonded ML0227 barriers is latent in service

**Claim.** DD section 11 note 1 states that the regen loop needs "a VOK channel false-OK together with a D-BC-RG short
and an eFuse short". A D-BC-RG power-stage short bypasses the EN clamps, and an eFuse FET short bypasses the eFuse VOK
term, so these two faults alone close the loop: in a regen window with BT_BUS closed, whenever V-MOT is at VBUS, D-MT-EN
forward-feeds V-MOT -> D-BC-RG -> eFuse -> Ag105 -> pack -> BT boost -> bus. The count in note 1 is three; the true count
is two. The same applies to F17 (D-BC-FC short) with the eFuse short in the bonded mode, where only the D-BT-SQ
cross-lock and the R_KA limit then stand.

Both elements are latent in service:

1. F15 and F17 give the detection "V_chg with REGEN LOW (diagnostic)" and "V_chg with FC_CHARGE and REGEN LOW", but
   Table 16 defines no such fault. With MOT_PWR HIGH in Idle and Run, a D-BC-RG short holds VCHG-IN (pin 38) at about
   VBUS, which is easily visible, but no code is specified to look.
2. `ERR_EFUSE_BYPASS` ("the Ag105 ACKs I2C while EF_EN reads L") has no opportunity to fire. VCHG-IN is fed only when
   EF_EN is HIGH (D-BC-RG and the eFuse share the VOK gate; D-BC-FC and the eFuse share FCQ), and `pollAg105()` polls
   only when `chargerHasPower()` (EF_EN H and EF_FLT_N H, DD section 12.5 item 1). If firmware probes after a VOK
   release instead, the module is still alive on its own input capacitance and on the 20 uF of C-D8/C-D10 (which decay
   through about 49 kOhm of dividers, tau about 1 s), so the probe false-trips. No gate other than C-2 at build tests
   the eFuse FET. F11, F13b, F35 and F36 (M2 gap bridge) therefore have no in-service detection.

**Proposed fix.** Define `ERR_VCHG_FED`: V_chg (pin 38, board side of M2) above 5 V for 20 ms while pins 30 and 31 are
LOW, with a blanking time after each window (TODO(calibrate) against the 1 s divider decay, or add a 2.2 kOhm bleed on
VCHG-IN switched off in windows). Observe the eFuse output directly: wire PGOOD (pin 17, now open) or a comparator on
VCHG-IN_M into ladder A in place of EF_EN (which firmware can derive from FF1.Q, PUMP_OK and the CHk bits), so that an
eFuse output with EF_EN LOW is visible whenever VCHG-IN is fed. Correct note 1 to "two faults".

### 2.8 FM2-8 (major): Stage 2 cannot open a regen window on the H-20 vehicle without unlisted prerequisites

**Claim.** A regen window requires "a readback of reg 0x00-0x02 has matched Table 5 in this power cycle, in an FC window
or a configuration check" (DD section 9.5 entry conditions). The configuration check runs "under the FC-window entry
conditions" and "a check from the H-20 needs the purge-free permit (OR-P)" (DD section 9.7a). The FC-window entry
conditions include `FC_CHARGE_ALLOWED` and the purge-free permit; Q_X1 is keyed to FCQ, so BT_BUS is clamped open in
hardware for the whole check and the bus is FC-only (DD equation 9).

**Failing scenario.** On the vehicle, the fw v31-v37 builds run `FC_CHARGE_ALLOWED 0` (CLAUDE.md 2026-11-04 addendum),
and the fw v33b lockout refuses every FC window on a running H-20 (DD sections 9.7, 13). Until OR-P and
`FC_CHARGE_ALLOWED 1`, no regen window can ever open, so Stage 2 delivers nothing. If the check is instead run before the
first purge-class dip of a boot, a purge during the check lands on an FC-only bus: about 6.7 % per check
(R2C section 5) of a UV_BUS latch into State 99 at standstill. Section 14.3 lists OR-B, OR-2', OR-4 and OR-V for
Stage 2; OR-P, T-E-01 and `FC_CHARGE_ALLOWED` are not listed.

**Proposed fix.** Either list OR-P, T-E-01, W2 and `FC_CHARGE_ALLOWED 1` as Stage-2 prerequisites, or remove the FC-only
bus from the configuration check: with pin 32 LOW the charger output reaches the pack only through R_KA, so the
bus-charger-pack-BT loop cannot close. Key Q_X1 to FCQ AND EN_SQ (clamp BT_BUS only when D-BT-SQ can conduct), keep
BT_BUS closed during the check, and re-derive the D5 arming for that case.

### 2.9 FM2-9 (major): the Idle-entry self-test stalls `detectFaults()` for about 420 ms with the bus live

**Claim.** The self-test "polls the ladders directly at 100 us intervals (not once per loop iteration)" and "takes about
420 ms per Idle entry" (DD section 9.3). It runs at every Idle entry, where MOT_PWR is HIGH, both boosts run and the
VESC is powered (DD Table 12). Step 2 alone holds pin 34 static for 200 ms and waits up to 90 ms; step 8 stops the
pump with the pack in the charge mode for up to 90 ms.

**Failing scenario.** Implemented as specified, the poll blocks `loop()`: `detectFaults()`, the share loop, the Pi link
and the VESC command stream stop for about 420 ms after every stop. CLAUDE.md lists "blocking calls that stall
`detectFaults()`" as a required self-review defect. DD section 12.4 item 5 says that any block longer than about 40 ms is
a trip; the self-test is exempt only because it toggles the pump itself. No rule states what happens when the Pi commands
State 2 during steps 4-8: if the transition proceeds, traction starts with the pack in the charge mode (bounded by U_C1
at 2.52-3.50 A); if it is held, the Run start is delayed by up to 420 ms without a specified response.

**Proposed fix.** Specify the self-test as a non-blocking sub-state machine of `chgModeTick()` that runs one step per
loop iteration, with `detectFaults()` every iteration; abort it (pin 33 LOW, pump running, result "deferred") on any
State-2 request or fault; add host tests for both.

### 2.10 FM2-10 (minor): the 2.5 A module-output ceiling is not enforced

DD section 1 states that "the module output is limited to 2.5 A including the unregulated VBT load". The Ag105 regulates
only the sense current I_p; I_L (BT boost and LM1084 input) is supplied in addition, and only the eFuse I_OL limits the
total. Table 8 uses I_L = 0.6 A (gate B8, not in the revision-4 bench plan), while DD section 12.6 item 3 uses 1.4 A.
At 1.4 A the module output is 3.15 A, 26 % above the Table-4 maximum (R2C section 6), with I_PACK1 reading 1.75 A, so
`ERR_PROFILE_OC` does not act. Restore gate B8 in section 15, and add a limit on the BT share or on BT_CURRENT inside
regen windows.

### 2.11 FM2-11 (minor): two procedure gaps

1. **Commissioning refusal.** DD section 12.4 item 7 refuses pin 33 while pin 32 is HIGH, but not pin 32 rising while
   FF1 is set. The State-98 switch keys can raise BT_SEQUENCE_ENABLE in the middle of a commissioning session; with the
   as-found 2.5 A registers this is F39, and in a BENCH_TEST 1 build OC_FC is compiled out. Refuse pin 32 HIGH whenever
   ladder A bit 0 reads HIGH in `CHG_CONFIG` or commissioning.
2. **J-NTC.** The Ag105 THERM input goes to J-NTC pin 1 and pin 2 is PCB GND (facts_board section 2.1). Whether a pack
   NTC is fitted is unknown (facts_prior section 9). A pack-internal NTC whose return is tied to pack negative and wired
   to J-NTC pin 2 is an F12b bond upstream of R_SH. Rule C2 does not name J-NTC, and C-1 runs with the pack absent, so a
   pack-internal bond is never tested. Name J-NTC in rule C2 and add a pack-installed isolation check (C-1c: with the
   charger unpowered and the switches in the charge mode, PACK- to GND and pack(-) to GND resistance).

## 3. FMEA worksheet

Modes: B = bonded (Idle, Run traction, Finish, State 99); R = regen window; F = FC window, configuration check or
commissioning; T = entry and exit transitions; P = power-up, reset, hang, brown-out. "OK" means that the DD bound was
checked and holds; "FM2-n" refers to section 2.

### 3.1 Pack switch board (SB) and harness

| Row | Element | Failure | Mode | Effect | First bound | Verdict |
|---|---|---|---|---|---|---|
| SB-1 | SB pack+ copper, tap pads, pack connector + | Short to SGND, PACK- or pack(-) | all | Direct pack short, 182-576 A | None (F_PK downstream) | FM2-1 |
| SB-2 | F_PK | Open | all | Pack+ off VBT; taps upstream keep S_GND on; VC1 positive | - | OK (F34) |
| SB-3 | R_SH, its joints, pack connector -, pack - lead | Open | all | Board return through BQ29200 clamps; brown-out | None | FM2-6 |
| SB-4 | R_SH | Drift or crack (higher R) | all | Trip and I_PACK gain error | XCHK cannot see (shared) | Minor: C-2 two-point check covers drift at build only |
| SB-5 | R_K1 / R_K2 | Open | all | F21; output with an open input BENCH | XCHK if outputs diverge | OK (DD F21, C-2) |
| SB-6 | KS+ to KS- | Short | all | Both channels read 0, all I_PACK-gated checks inert | None in R | FM2-3 |
| SB-7 | KS+ or KS- | Short to pack+ or VBT | all | <= 3.85 A, R_K fuses | R_K | OK (F27) |
| SB-8 | S_GND1 or S_GND2 | D-S short | R, F | Sense bypass | U_C2 (but see FM2-2, FM2-3) | OK as F1 |
| SB-9 | S_GND1 or S_GND2 | Open, gate-source or gate-drain short | B | One channel lost | Other channel; SG bit | OK (F2a) |
| SB-10 | Both S_GND | Off together | B | Body-diode discharge 12-17 W | `ERR_SGND_OPEN` | Common cause added: FM2-5 |
| SB-11 | S_CHG | D-S short | B | Sense parallel to S_GND | - | OK (F3, latent) |
| SB-12 | S_CHG | Open | R, F | Charge through body diode | - | OK (F4) |
| SB-13 | Q_A1/Q_A2 | Open | R, F | That S_GND stays on in a window; Q_D holds S_CHG off; SG bit mismatch | Ladder within 5 ms | OK |
| SB-14 | Q_A1/Q_A2 | D-S short | B | Channel off | Other channel; SG bit | OK (F2a) |
| SB-15 | Q_A, Q_C gate inputs | Positive V_GS from SGND offset | B | S_GND off and S_CHG on with FF1 clear | Firmware only | FM2-5 |
| SB-16 | D_A1/D_A2 | Short | B | UC1_N loaded to about 1.06 V; one Q_A partly on; N1 at about 1.3 V, FF1 cannot set | Self-test step 4; SG bit | OK (detected) |
| SB-17 | D_A1/D_A2 | Open | R | U_C1 direct path lost; N1 path remains | - | OK (latent, redundant) |
| SB-18 | Q_B (BSS84) | D-S short | B | G3 driven, Q_D holds it at about 0.05 V (8 mA, 64 mW in Q_D) | Q_D | OK (latent) |
| SB-19 | Q_C | D-S short | B | As SB-18 | Q_D | OK (latent) |
| SB-20 | Q_D | Open | T | Interlock lost; S_CHG/S_GND overlap at a U_C1 trip | eFuse already off | Minor: not in F40 |
| SB-21 | Q_D | Short | R, F | S_CHG never on; charge through body diode | - | OK (availability) |
| SB-22 | R_PD3, R_B3, Z3, C_CQ | Open or short | R, F | S_CHG slow, never on or no delay; Q_D interlock retained | - | OK |
| SB-23 | F_T1 | Open | all | Channel 1 lost and S_CHG cannot turn on (Q_B on VBT_T1) | Channel 2; body diodes | OK (detected by SG bit 1) |
| SB-24 | C_VTk pair | Both shorted | all | F_Tk opens | F_Tk | OK (F31) |
| SB-25 | Q_R1/Q_R2 | Short or open | B | SG readback stuck | Ladder mismatch | OK |
| SB-26 | FF1Q_SB conductor | Short to SGk_RB in the 7-way cable | B, R | SG readback follows FF1Q_SB: masks SB-13 | None until a second fault | Minor (double fault, section 4) |
| SB-27 | FF1Q_SB conductor | Short to a positive SB conductor (VBT_Tk) | B | Both S_GND off, S_CHG on; U_C1 direct path must overpower a stiff 8 V source through 4.7 kOhm (TLV3011B V_OL TODO(verify)) | U_C1 direct; `ERR_CHG_LADDER` | Minor: margin unverified |
| SB-28 | Lead A, lead B | One open | B | Other lead carries the return | Parallel lead | OK (F22) |
| SB-29 | Lead A and lead B | Both open | B | S_CHG self-biases on; return through the Ag105 sense in reverse | Firmware only | FM2-5 |
| SB-30 | Pack connector | Reversed (keying defeated) | P | Reverse current through the S_CHG body diode, the Ag105 sense, board diodes; F_PK 20 A | F_PK | Minor: assembly, C-1 polarity check |
| SB-31 | VBATN_X | Open | R, F | F14; the sense-path check is one-sided and passes (V_PACKN about -0.7 V through body diodes) | `ERR_ISO_MISMATCH` (F only) | OK (availability) |

### 3.2 Logic board (LB)

| Row | Element | Failure | Mode | Effect | First bound | Verdict |
|---|---|---|---|---|---|---|
| LB-1 | U_FF | Q stuck HIGH; /PRE open floating LOW (both outputs HIGH with /CLR LOW) | B | F7 | U_C1 direct path | OK (F7) |
| LB-2 | U_FF /CLR, U_CLS | Stuck HIGH or open floating HIGH | R, F | No clear from any source | U_AND PUMP_OK term, firmware | FM2-2 |
| LB-3 | D_N33, D_NP, D_N20 | Short | R, F | Push-pull source holds N1 HIGH; comparator clears lost | Firmware, eFuse I_OL | FM2-2 |
| LB-4 | D_N33 | Open | P, T | Pin-33 and reset clear lost; not self-tested | Pump clear 43-76 ms | FM2-2 |
| LB-5 | D_NC1, D_NC2 | Short | all | N1 tied to an open-drain node; benign | - | OK |
| LB-6 | D_NC2 | Open | R, F | U_C2 has no actuator | eFuse I_OL | OK (self-test step 6 detects) |
| LB-7 | Q_D5 | Body diode (normal part) | B | D5_N at 0.65-1.02 V; self-test fails | - | FM2-4 |
| LB-8 | Q_OV | Open | all | F25 | OV_BATT | OK (latent, as DD) |
| LB-9 | U_P33 | Stuck HIGH | T | F32 | Pump | OK |
| LB-10 | U_BF | Stuck HIGH | B | FF1Q_SB HIGH with FF1.Q L on the ladder; S_GND off | U_C1 direct; `ERR_CHG_LADDER` (SG bits) | OK |
| LB-11 | U_SH1/U_SH2 | Dead, output stuck | all | F8/F8b | Other channel; XCHK | OK |
| LB-12 | Kelvin inputs | Common short | all | FM2-3 | None in R | FM2-3 |
| LB-13 | U_C1/U_C2 | Output stuck released | R, F | F24 | eFuse | OK (detected at Idle) |
| LB-14 | Pump C_P1 | Short | P | F9 | WDOG | OK |
| LB-15 | Pump D_P2 | Short | P | PUMP_H follows PUMP_A; static pin 34 decays through C_P1 | - | OK |
| LB-16 | U_AND | Output stuck HIGH | B | F13b | Firmware refusal; D-BT-SQ cross-lock | OK (but see FM2-7 on detection) |
| LB-17 | R_SDP | Open | P | SHDN floats HIGH on the internal 10 uA source when U_AND is unpowered | VCHG-IN unfed with the Teensy off | Minor: Table 13 "also with 3V3 absent" holds only with R_SDP intact |
| LB-18 | U_Vk | Output stuck LOW (OK) | B | One channel permits at bus level | Other channel; `ERR_VOK_STUCK` | OK (F15b) |
| LB-19 | U_BPk | Output stuck LOW (present) | all | Bus-tap guard lost; invisible while OKk_N is HIGH | Second fault needed | OK (latent pair) |
| LB-20 | R_Ok | Short (REF to BTk) | B | Channel reads OK above V-MOT about 9.9 V | `ERR_VOK_STUCK` | OK |
| LB-21 | R_Ok | Open | all | Pure ratio thresholds 17.33 / 16.57 V at 16 V; offset at 0/0 lost; U_BP blocks at 0/0 | U_BP | OK |
| LB-22 | Q_Hk | Open | R | No external hysteresis; VOK chatter on V-MOT ripple | eFuse and clamps follow | Minor (availability) |
| LB-23 | Q_RGk, Q_RBk, Q_X1, Q_X2 | Open | R, F | F40 | Parallel element | OK (accepted latent) |
| LB-24 | U_D5 | Stuck | F | F16 bound lost | Firmware BT_CURRENT | OK (self-test) |
| LB-25 | Ladder resistors, U_LA/U_LB | Drift, stuck bit | all | Mis-decode | Calibrated codes; 3 ms latch | OK |
| LB-26 | LB 3V3 tap wire | Open | all | LB unpowered with the Teensy running; FF1Q_SB on pull-downs (bonded); SHDN on R_SDP; clamps on D-BC-RG released but pin 30 refused; ladders read 0 | Firmware refuses windows | OK |
| LB-27 | LB GND tap wire | Open | all | LB ground returns through D_SGk and Q_Rk to SGND, about +0.35 V; FF1Q_SB LOW = +0.35 V at Q_A (below 0.8 V) | Ladders offset by about 3 LSB: `ERR_CHG_LADDER` | OK |
| LB-28 | Teensy pins 16/17 | Driven as outputs by a firmware defect | all | SIG forced HIGH through R_A 1 kOhm: U_C1 and U_C2 blind | Host test that pins 16/17 stay ADC inputs | Minor: add to 12.11 |

### 3.3 Charger adapter (CB), Ag105 and existing switches

| Row | Element | Failure | Mode | Effect | First bound | Verdict |
|---|---|---|---|---|---|---|
| CB-1 | U_EF | FET short | B, R | Input gate lost; latent | Firmware refusal; D-BT-SQ cross-lock | FM2-7 |
| CB-2 | U_EF | Stuck off, latch | R, F | Availability | - | OK |
| CB-3 | U_EF | No reverse blocking (by design) | T | Module input back-feeds VCHG-IN | RT1987 reverse blocking | OK |
| CB-4 | C-D8/C-D10 (existing 20 uF on VCHG-IN) | Normal hold-up, tau about 1 s | R | Each VOK assert powers the module at once from the residual charge before D-BC-RG turns on; a brief start then UVLO; ERR_EFUSE_BYPASS probe false-trips | - | FM2-7; HR1 availability (S0-6 should include it) |
| CB-5 | Q_CS, Q_MP, R_CS1, PROFILE wire | Open, short, high R | F | F23, F23d, F38 | OC_FC; U_C2 | OK |
| CB-6 | Ag105 | Sense-parallel switch (F19) | R, F | Sense blind | U_C2 | OK (S0-2) |
| CB-7 | Ag105 | Output current I_p + I_L | R | Output above 2.5 A at I_L above 0.75 A | None | FM2-10 |
| CB-8 | Ag105 THERM / J-NTC | Pack-internal NTC return | R, F | F12b bond | eFuse | FM2-11 |
| EX-1 | D-BC-RG | Power-stage short | B | VCHG-IN at VBUS (MOT_PWR HIGH); no defined fault | eFuse (needs FF1) | FM2-7 |
| EX-2 | D-BC-FC | Power-stage short | B | VCHG-IN at VBUS; no defined fault | eFuse | FM2-7 |
| EX-3 | D-BT-SQ | Power-stage short | B | F5 | EF_EN needs FF1 | OK |
| EX-4 | D-BT-EN | Power-stage short | F | F16 | D5 (but see FM2-4 for the readback) | OK |
| EX-5 | D-MT-EN | Reverse block slow after a regen pulse | R | Pre-existing; IC1 does not toggle MOT_PWR | - | OK (no IC1 change) |
| EX-6 | TPS61288 BT/FC | Back-feed when disabled | all | IC1 changes no boost enable order; State-99 phase 0 drops both bus switches first | - | OK |
| EX-7 | VBT-GND board short (boost death class) | - | B | Fault current through S_GND before F_PK clears; offset can switch both off | Body diodes | FM2-5 scenario 3 |

### 3.4 Teensy pins and firmware states

| Row | Element | Failure | Mode | Effect | First bound | Verdict |
|---|---|---|---|---|---|---|
| T-1 | Pin 33 | High-Z (reset, boot) | P | FF1 clears through U_P33 | - | OK (calc4 section 6), but see LB-4 |
| T-2 | Pin 34 | Static (hang) | P | PUMP_OK falls 43-76 ms; eFuse off through U_AND | - | OK |
| T-3 | Pin 32 | Raised during commissioning with FF1 set | F | F39 | Bench supply limit | FM2-11 |
| T-4 | Pin 5 | HIGH between regen pulses into an unpowered module | R | Possible back-power through the MPPTD input | - | OK as UNCONFIRMED (Stage-0 rig holds MPPTD on an always-on rail) |
| T-5 | Self-test | Blocking 420 ms poll | B | `detectFaults()` stalled | - | FM2-9 |
| T-6 | Configuration check | FC-only bus | F | UV_BUS on a purge; Stage 2 blocked | - | FM2-8 |
| T-7 | `ERR_VOK_STUCK` | Back-EMF rectification on a downhill coast with command 0 | B | V-MOT above VBUS by the assert margin with no negative command: false latch | - | Minor: the 200 ms rule assumes regen only follows a negative command (UNCONFIRMED for this motor) |

## 4. Common-cause and double-fault analysis

Table 2 lists the common causes and credible double faults that reach one of the outcomes named in the brief.

Table 2. Common causes and double faults.

| ID | Faults | Outcome | Bound | Reference |
|---|---|---|---|---|
| CC-1 | One SB-internal pack+ short (single) | Pack short, fire | None in the design | FM2-1 |
| CC-2 | FF1Q_SB offset (both leads open, double) | Bonded mode with the return through the Ag105 sense | Firmware | FM2-5 |
| CC-3 | Shared Kelvin pair short (single) | Both trips and every I_PACK-gated check blind | eFuse I_OL (regen) | FM2-3 |
| CC-4 | N1/U_CLS funnel (single diode or buffer) | All comparator clears lost; U_C2 without actuator | eFuse I_OL, firmware | FM2-2 |
| DF-1 | D-BC-RG short + eFuse short (both latent) | HR3 regen loop | Ag105 regulation, firmware window end | FM2-7 |
| DF-2 | Kelvin short + S_GND D-S short | Sense-blind charge in a regen window | eFuse I_OL, then latch-off within 233 ms; below I_OL min 1.84 A no bound | FM2-3 |
| DF-3 | D_N33 short + F1 or F38 | Charge above U_C2 with FF1 held set | `ERR_PROFILE_OC` (20 ms), eFuse | FM2-2 |
| DF-4 | Lead B open + lead-A contact degradation | Offset reaches the Q_A threshold at 49 mOhm (17.1 A) | `ERR_RET_DEGRADED` detects lead B first | FM2-5 |
| DF-5 | eFuse short + D-BC-FC short + Q_X2 open | ML0227 loop in the bonded mode | Firmware refusal only | Three faults; two of them latent (FM2-7) |
| DF-6 | FF1Q_SB to SGk_RB short + Q_A open | S_GND stays on in a window with a matching readback; sense bypass | U_C2 | SB-26 |
| DF-7 | R_SH or pack-connector negative open + balance plug in | BQ29200 VC1 about -0.6 V; Teensy brown-out | None | FM2-6 (single fault) |

No credible single or double fault found in this round produces a pack over-charge past the BQ29200 OVP: the Ag105 CV
point lies below the pack terminal in both sense hypotheses, `OV_BATT` over-reads in the charge mode, and Q_OV acts
directly on N1 without a diode, so it survives the FM2-2 funnel faults (it does not survive LB-2, the U_CLS stuck-HIGH
case, where only the firmware `OV_BATT` and the Ag105 CV remain). No path to a Death-5 hot-plug or to a new boost
back-feed was found.
