# Battle-Test Round 5: Delta FMEA of Detailed Design IC1, Revision 7

Date: 2026-11-07. Target: `detailed_design_IC1.md` revision 7 (cited "DD"). Lens: delta FMEA of every component, net and
firmware rule that revision 6, the completeness-critic edits and revision 7 added or changed (DD Tables 0c and 0d,
Appendix E, section "Completeness critic"). Calculation script: `calc/fmea_round5_calcs.py` (output
`calc/fmea_round5_calcs_output.txt`, cited "r5 section N"). Primaries: SLUSA52C (`references/Datasheets/BQ29200_TI.pdf`,
cited "SLUSA52C"), the BOM, the firmware (`teensy_controller/teensy_controller.ino`, cited "ino:line"), and the calc
outputs of revisions 6 and 7 (calc6, calc7) and `calc/bt4_logic_seq_enum_output.txt` (cited "bt4-LS"). Nothing was
ordered, built or flashed.

## 1. Scope and method

This report applies the failure modes short, open, stuck, drift, reversed and intermittent to each added or changed item
in each mode (bonded Idle, bonded Run, configuration check and probe, FC window, regen window, commanded exit, hardware
trip, State 99, Teensy reset, hang and brownout). It then checks the interaction of each item with the existing
changeover (S_GND1/2, S_CHG, FF1, N1, the eFuse, U_C1, U_C2, U_IM, D5, VOK, the cross-locks, D-BT-SQ, the Ag105 and the
BQ29200). The round-4 fixes were attacked first, as the task requires. Findings already adjudicated in round 4 are not
repeated unless the round-4 fix is itself wrong.

Section 2 gives the findings. Section 3 gives the delta FMEA table. Section 4 gives the double faults and common causes.
Section 5 lists the items that were attacked and cleared.

## 2. Findings

Table 1 summarises the findings. No blocker was found: every finding either fails toward a refused window or is caught
by an existing bench gate, or its harm needs a second event.

Table 1. Round-5 findings.

| ID | Severity | Title | Round-4 fix attacked |
|---|---|---|---|
| FM5-1 | Major | `ERR_MOD_SENSE` (c) false-latches on a healthy board at a commanded regen exit between VOK pulses and on the probe feed drop | FM4-2 (R7-7) |
| FM5-2 | Major | The VC1 tap lead lands on Teensy pin 20 with no LB-side series element; a lead chafe forces pack or bus voltage onto the MCU | BT4-DS-02, FM4-1 (R7-2) |
| FM5-3 | Major | The D_VC1 specification is self-contradictory over its stated temperature range; calc7 section 3 evaluated the V_F limit at 25 C only | FM4-5, BT4-DS-01 (R7-1) |
| FM5-4 | Minor | `ERR_CELL_MISMATCH` budget assumes a calibrated pin 25 that no gate calibrates; uncalibrated, a 3V3 error of 0.5 % exhausts the margin | BT4-DS-02 (R7-2) |
| FM5-5 | Minor | `ERR_IPACK_PLAUS` gain band (State 99): the symbol I_L,cal names two different quantities; the B8 regen-window value puts a healthy board below 0.75 | BT4-TR-02 (R7-8) |

### 2.1 FM5-1 (major): `ERR_MOD_SENSE` (c) false-latches between regen pulses and on the probe

**Defect.** The revision-7 exit hold check (DD section 9.5 exit step 1; Table 16 `ERR_MOD_SENSE` (c)) runs when "pin 8
has read HIGH in this window and V_chg was at or above 13.5 V on the last settled reading before the write". It then
latches on a LOW sample of pin 8 at 50 us or 150 us after the feed-drop write. The trigger condition tests neither EF_EN
nor pin 8 at the write. V_chg (pin 38) is VCHG-IN, the eFuse input, which holds charge on about 20 uF with a bleed time
constant of 0.984 s after every VOK release (DD section 9.5 hold duties; bt4-LS section 3; calc7 section 5). The module
node VCHG-IN_M, which U_MS watches, is dumped by Q_MD below 8.67-9.17 V within 1.3-2.9 ms of the release (calc6
section 3). Between VOK pulses the trigger therefore holds while the node is already cold. This is the stale-residual
mechanism of BT4-LS-02, which revision 7 removed from rule (b) and re-introduced in rule (c).

**Failing scenario 1 (regen window, traction request between pulses).** The VESC re-pulses every 0.523-0.562 s with a
VOK off-span of 0.147-0.294 s (bt4-LS section 3). After a release at 16.13-16.43 V, V_chg stays at or above 13.5 V for
175-193 ms (158-210 ms over a +/-20 % tau spread). A commanded exit inside that interval meets the trigger with pin 8
already LOW, so the 50 us sample reads LOW and `ERR_MOD_SENSE` (c) latches (r5 section 1). The exposed interval is
27.5-36.1 % of the pulse period. A traction request (DD section 9.6) arrives at a random time with respect to the pulses,
so the probability of a false latch is 0.25-0.36 per exit and 0.58-0.74 for three exits in a power cycle (r5 section 1).
The release-dwell exit (brake demand ended for 200 ms) reads 13.16-13.41 V at the nominal tau and is not evaluated, but
it reads 13.66 V with a tau 10 % longer and a 16.43 V release, which latches. The latch refuses every window for the
power cycle and voids the last eFuse-blocking probe. Regen windows then need a new configuration check, which on the
vehicle needs a bench supply on J-FC until ruling OR-P (DD section 9.7a). Stage 2 is therefore expected to lose regen
after the first or second regen window of most drives.

**Failing scenario 2 (configuration check, probe feed drop).** Probe step 3 raises FC_CHARGE with EF_EN L and confirms
V_chg at or above 13.5 V on two settled iterations; step 4 requires pin 8 LOW (the pass); step 5 drops FC_CHARGE. The
same check has already read pin 8 HIGH in its positive control (DD section 9.7a step 6, CC-6). The step-5 feed drop
therefore meets the Table 16 (c) trigger exactly, and the healthy probe result (pin 8 LOW) latches (c) and voids the
probe it has just produced. DD section 9.7a does not exclude the probe drop from (c). If the firmware implements Table 16
as written, no healthy board can complete a qualified probe, and regen windows never open.

**Why no gate catches scenario 1.** Gate C-2b item (g) runs the exit hold check only at configuration-check exits, where
the node is fed at the write (DD section 15.3). No gate or host test (DD section 12.11) commands an exit between two VOK
pulses with a residual V_chg. Scenario 2 is caught by C-2b item (g) only if that item includes the probe drop; its text
names "the exit hold check on the healthy board" without the probe.

**Pulse-time exits are not affected.** With the node fed at the write, the healthy fall to 9.17 V takes 358-1821 us for
C_mod 100-221 uF and an input power of 0-22.7 W from 13.5-16 V (r5 section 2), and 168-387 us even at an assumed
47 uF. The 0.248 ms bound of calc7 section 6 holds for this case.

**Proposed fix.** Evaluate (c) only when, in the same iteration and immediately before the write, ladder A bit 1 (EF_EN)
reads H and a direct read of pin 8 reads HIGH; drop the V_chg term, which cannot represent the module node. Exclude the
probe feed drop explicitly (EF_EN is L there by design). A pin 8 that follows EF_EN (row F55) still reads HIGH before the
write and LOW at 50 us, so the F55 detection is kept. Add a host test with a traction request 50 ms after a VOK release
and V_chg at 14.0 V, and a host test of a complete healthy probe; add both cases to C-2b item (g).

### 2.2 FM5-2 (major): the VC1 tap lead lands on Teensy pin 20 with no LB-side series element

**Defect.** The VC1 tap is "VC1 pad at M16 ─ R_VC1a 200k ─ flying lead ─ VC1_T ─ Teensy pin 20 (A6) ; R_VC1b 200k ─ GND ;
C_VC1 100 nF ─ GND" (DD Figure 2; Table 4 net VC1_T; pin map row 20). The flying lead is the pin-20 node itself. Row F54
and Table 7 state that "R_VC1a at the tap end limits any lead fault to at most 42.5 uA". That bound is the current drawn
from VC1 when the lead is forced to 0 V or 8.5 V (calc7 section 2); it is not the stress on pin 20. A chafe of the lead
onto a positive conductor forces pin 20 to that conductor's voltage through nothing but the lead and the pin's ESD
structure.

**Failing scenario.** The lead runs from M16 at (19.3, 28.4) mm, 2.3 mm from the Ag105 body and beside J-BL and J-BT
(DD Table 6 M16, M13), to LB at the J2 strip, in the same flying-lead population that the design itself treats as
chafe-prone (row F48 for VBATN_X, row F55 for MS-to-SHDN_EF, section 5.7 item 4). A chafe onto VBT (8.5 V), VBUS
(16-17.5 V) or VCHG-IN_M (up to 21.5 V) drives pin 20 far beyond the i.MX RT1062 GPIO absolute maximum (about
NVCC_GPIO + 0.3 V = 3.6 V, TODO(verify: IMXRT1060CEC absolute-maximum table); calc7 section 2 uses the same 3.6 V clamp
onset). The clamp current is limited only by the source and the ESD structure (amperes; r5 section 4). The expected
results are the loss of pin 20 and the ADC that it shares, and a forward-biased ESD path into the Teensy 3V3, which is
also the LB 3V3 (J2 05/06). LB 3V3 supplies FF1, U_C1, U_C2, U_IM, U_MS, U_MDI, the ladders and both INA240s (DD
section 5.2). While the injection lasts, every ADC-based detector (I_PACK1/2 on pins 16/17, V_PACKN, V_chg, FC_CURRENT,
BT_CURRENT) can be corrupted (UNCONFIRMED: i.MX RT ADC cross-channel injection behaviour, TODO(verify: IMXRT1060RM ADC
chapter)); if the 3V3 rail is driven up, the hardware latch chain is exposed beyond its supply rating, and its failure
state is not analysed in DD section 11. The design-rule analogue of rule C1 (a series limiting element at the end where a
fault can enter) is met at the VC1 end but not at the LB end. The same gap exists on the MS sense lead: MS_D lands on
U_MS IN+ with only R_MS2 16.2 kOhm to GND, and the lead is adjacent to VCHG-IN_M on CB, so a chafe onto the node puts
13.5-21.5 V on a 7 V absolute-maximum input with no limit (SBOS300C section 6.2; compare row F56, which bounds only the
open-R_MS2 case at 0.215 mA).

**Detection.** `ERR_CELL_MISMATCH` would read the mismatch only if the ADC still works, and only in bonded mode with
|I_PACK1| at or below 1 A. No gate injects a lead-to-positive chafe (C-2a item 5 injects only mismatch levels).

**Proposed fix.** Fit a series resistor of 22-47 kOhm at the LB entry of the VC1 tap, with C_VC1 on the pin side
(injection 0.22-0.81 mA at 21.5 V, r5 section 4), and re-derive the divider ratio and the tap load; or move R_VC1b to
M16 so the lead carries a 100 kOhm Thevenin source, and still fit the LB-side series resistor. Apply the same rule to the
MS lead (a series resistor at U_MS IN+ ahead of C_MS, re-deriving the U_MS window and the CMRR term). Correct row F54 and
Table 7, add a row for each lead chafed to a positive conductor, and add the injection current to the pin-20 open item 24
with the i.MX RT injection limit.

### 2.3 FM5-3 (major): the D_VC1 specification contradicts itself over temperature

**Defect.** Table 7 specifies D_VC1 as a "low-leakage small-signal Schottky" with V_F at most 0.25 V at 16.2 mA "over -20
to 85 C" and I_R at most 40 uA at 4.2 V at T_M16,max, and states that "the 0.25 V at 16.2 mA limit implies I_S of at
least 1.0-2.3 uA at 25 C, which leaves room for the hot limit (calc7 section 3)". Calc7 section 3 evaluates the V_F limit
at 25 C only. The V_F limit binds at the cold end, where I_S is one to two decades lower, so the cold V_F limit forces a
much larger I_S at 25 C, and the reverse leakage at the hot end scales with the same I_S.

**Numbers (r5 section 3).** With a thermionic model (I_S proportional to T^2 exp(-phi_B/kT); series resistance and
barrier lowering ignored, both optimistic), V_F at most 0.25 V at 16.2 mA at -20 C requires I_S(-20 C) of at least
171-484 nA (n = 1.0-1.1). The hottest M16 temperature at which I_R then stays at or below 40 uA is:

- 87 C only for a barrier of 0.35 eV and n = 1.0 (and 60 C at n = 1.1);
- 41-60 C for 0.45 eV;
- 29-43 C for 0.55 eV;
- 21-33 C for 0.65 eV.

Even with a cold limit of 0 C or 10 C, a 0.55 eV part exceeds 40 uA above 46-69 C. Only an ultra-low-barrier part meets
both limits at a T_M16,max near 85 C, and such parts are the opposite of the "low-leakage" type that Table 7 names. M16 is
2.3 mm from the Ag105 body, whose case the design allows to reach 90 C during M13 (DD Table 6), and T_M16,max is an open
item (DD section 18 item 27).

**Consequences.** If the part meets the cold V_F limit, the hot leakage is likely 100-500 uA: VC1 then reads 26-130 mV
low through RB3 (261 Ohm), so the BQ29200 cell-1 OVP (SLUSA52C section 7.5) trips 26-130 mV late, and
`ERR_CELL_MISMATCH` sees twice that (52-260 mV) and latches at about 75 uA, refusing every window while the board is hot.
`ERR_CELL_MISMATCH` is evaluated only in bonded mode, so the cell-1 OVP shift during a long FC window, when the Ag105
heats M16, is not observed at all. If the part meets the hot leakage limit instead, V_F at the cold end exceeds 0.25 V,
and VC1 can fall below the SLUSA52C section 7.1 minimum of -0.3 V in row F34b. Gates B-PKN (coldest ambient) and BG-17
(hot trip) can expose either outcome, so the defect is gated; its likely result is that no part passes both gates and
Stage 1 stops at B-PKN ("select a lower-V_F clamp").

**Proposed fix.** State the cold and hot limits with the temperatures that bind them (T_cold of the operating range;
T_M16,max measured at B8 before part selection), and re-derive the feasibility on a candidate datasheet's V_F and I_R
curves rather than on a 25 C I_S. If no part fits, relax one side explicitly: raise RB3 so that 0.3 V at the reduced F34b
current is within the cold limit (re-checking the SLUSA52C section 7.3 RIN range of 100 Ohm-1 kOhm and the VC1 error
from I_IN of 2.5 uA, SLUSA52C section 7.5), or accept a larger leakage and widen the `ERR_CELL_MISMATCH` budget with a
temperature-compensated term and an OVP-margin statement for cell 1.

### 2.4 FM5-4 (minor): `ERR_CELL_MISMATCH` assumes a pin-25 calibration that no gate performs

The healthy budget of 41.5 mV (calc7 section 2) includes "V_BT channel after two-point cal (ASSUMED 5 mV)". Gate C-2a
item 5 calibrates only the VC1 tap against a DMM; no Table 19 item calibrates pin 25. The firmware scales pin 25 with
the nominal ADC_VREF of 3.3 V (ino:2025-2026, ino:7030). The divider is 0.1 % (BOM lines 60-61), so its error is at most
about 10 mV, but the ADC reference error is not removed: the VC1 channel absorbs the true 3V3 at its calibration, pin 25
does not, and the error appears in full in V_BT - 2 V_VC1. Over the 3V3 range that the design itself uses (3.2-3.4 V, DD
section 5.2), the pin-25 error is -247 to +262 mV at 8.4 V, against the 80 mV threshold. The 38.5 mV margin holds only
for a 3V3 within +/-0.46-0.52 % of 3.30 V (r5 section 5). Outside that band the rule latches on a balanced pack in every
power cycle and refuses every window. C-2a item 5 ("no `ERR_CELL_MISMATCH` at 40 mV") would fail on such a board, so the
defect is caught, but its NO-GO action ("fix and repeat") names no fix. **Proposed fix:** add a pin-25 two-point
calibration to C-2a item 5 (same DMM, same session) and store it with the VC1 constants (open item CC-B4).

### 2.5 FM5-5 (minor): `ERR_IPACK_PLAUS` gain band uses an ambiguous I_L,cal

The revision-7 gain band (Table 16) compares I_PACK1 with BT_CURRENT x V_bus / (eta_cal x V_batt) + I_L,cal and latches
`ERR_IPACK_PLAUS`, which is a State-99 fault under ruling OR-E, outside 0.75-1.30. The boost-input term already carries
the BT-boost input current, so I_L,cal in this formula must be the non-boost VBT load only (calc7 section 10 assumed
0.1-0.3 A). Gate B8, which stores I_L,cal, measures "I_L (LM1084 input current plus the BT-boost input current)" in both
window types, and Table 8 gives working values of 0.6 A (regen window, BT_BUS closed) and 0.3 A (FC window). With the
regen-window value the lowest healthy ratio is 0.70 (0.67 at 0.75 A), below the 0.75 band edge, which puts a healthy
vehicle into State 99 in traction; with the FC-window value it is 0.779, a margin of 0.029 (r5 section 6). The calc7
section 10 spread (0.82-1.19) is also static only: the rule as written has no dwell on the band violation itself, only a
1 s qualification of BT_CURRENT at or above 1.0 A. **Proposed fix:** define a separate stored constant I_NB,cal (LM1084
input current at bonded Idle, measured at C-2a), state the band evaluation as a mean over the 1 s window, and add a host
test with I_L,cal at the B8 regen value.

## 3. Delta FMEA table

Table 2 lists every added or changed item with the failure modes attacked and the result. "Covered" cites the DD row or
rule that already handles the mode correctly. "FM5-n" marks a finding of section 2.

Table 2. Delta FMEA.

| Item (revision) | Mode | Effect and interaction | Result |
|---|---|---|---|
| RB1A 4.7 kOhm (R7) | Open | VC1_CB floats: no balancing; OVP sensing on VC1/VC2 unaffected | Covered (C-1 resistance check) |
| RB1A | Short (0 Ohm) or wrong value 100 Ohm | Returns to the revision-6 bound (39 mA into VC1_CB in F34b) | Covered (C-1 4.47-4.94 kOhm) |
| RB1A | Drift high | Balance current below 0.5 mA; SLUSA52C 7.3 range exceeded (RCB maximum 4.7 kOhm) | Accepted; OR-AA |
| D_VCB (deleted, R7) | Fitted by mistake (stale BOM) | Revision-6 FM4-1 hazard returns | Covered (C-1 VC1_CB-to-GND check) |
| D_VC1 (R6/R7) | Short, reversed | V_pack across VC2-VC1; 16.2 mA cell-1 drain | Covered (F47, `ERR_CELL_MISMATCH`, C-1) |
| D_VC1 | Drift (hot leakage), V_F at cold | Cell-1 OVP late or VC1 below -0.3 V | **FM5-3** |
| D_VC1 | Open | F34b unclamped: VC1 to about -V_cell2 through RB3 | Covered (C-1 diode check; B-PKN) |
| R_VC1a (R7) | Open | Pin 20 reads 0 V: mismatch about V_pack, window inhibit | Covered (F54) |
| R_VC1a | Short | VC1 loaded by 200 kOhm only: 21 uA, 5.5 mV through RB3 | Covered (F54 order of magnitude) |
| R_VC1b (R7) | Open | Pin 20 at about VC1 (up to 4.2 V) through 200 kOhm: about 3 uA clamp current | Covered (F54) |
| R_VC1b, C_VC1 | Short | Pin 20 at 0 V: mismatch, window inhibit | Covered (F54) |
| VC1 tap lead | Chafe to GND | VC1 loaded by 21 uA | Covered (F54) |
| VC1 tap lead | Chafe to VBT, VBUS, VCHG-IN_M | Pin 20 and possibly 3V3 overdriven | **FM5-2** |
| Pin 20 (R7) | Teensy reset, unpowered | Analog input, no drive; at most a few uA into the unpowered rail | Covered |
| Pin 20 | Firmware still configures WDOG1_B | Pin drives C_VC1 at 3.3 V; tap reads 3.3 V | Benign; host test of the pin configuration recommended |
| WDOG1_B / D_N20 (deleted, R7) | Loss of the third hang layer | Pump plus RTWDOG remain (B11, B11b) | Covered (F9b) |
| `ERR_CELL_MISMATCH` (R7) | Healthy board, 3V3 off nominal | Latch on a balanced pack | **FM5-4** |
| `ERR_CELL_MISMATCH` | Real imbalance above 80 mV | Windows refused per power cycle; 0.5-1 mA balancing continues whenever CB_EN is LOW (SLUSA52C 8.1.2: enable at 17-45 mV, off at +/-9 mV) | Accepted (OR-AA; health flag) |
| R_MDS 1 kOhm (R7) | Open | Q_MD held off by R_MDG: no dump | Covered (F49, `ERR_MOD_DRAIN`, C-2b (d)) |
| R_MDS | Short | Revision-6 state; MD_G-to-GND short loads U_MDI output | Covered (C-2a item 27) |
| R_MDS | Slower gate edges | Turn-off about 1-3 us at near-zero V_DS; turn-on Miller about 1-3 us at 1.1 mA plateau current; overlap at 5.79 V/ms adds below 5 mA | Covered |
| MD_G lead | Chafe to VCHG-IN_M or VBT | Q_MD stuck on (and V_GS possibly above its rating) | Covered (`ERR_MOD_DUMP_ON`, F50) |
| `ERR_MOD_DUMP_ON` (R7) | Healthy step from the BT-current residual (below 0.2 A at the baseline) | Healthy step at most about 0.2 + 0.023 A plus noise against 0.4 A | Covered (margin about 0.13 A) |
| `ERR_MOD_DUMP_ON` | Ramp still in progress at the sample | Sample is at least 10 ms after V_chg 13.5 V; eFuse ramp 4.4-5.6 ms (calc4 section 11) | Covered |
| `ERR_MOD_DUMP_ON` | Module warm restart inside 10 ms | A charging module would add 0.75 A (FC profile, bus side) | BENCH (S0-7/S0-8 restart time); not a finding |
| `ERR_MOD_SENSE` (b) crossing anchor (R7) | No reading below 13.0 V | Pulse not evaluated; probe void (CC-6) | Covered (availability only) |
| `ERR_MOD_SENSE` (c) exit hold check (R7) | Exit between pulses; probe drop | False latch | **FM5-1** |
| `ERR_MOD_SENSE` (c) | Exit during a pulse | Healthy fall 358-1821 us (168 us at 47 uF) | Covered (r5 section 2) |
| T_drain,max rule (R7) | 9.76 ms iteration | Latest healthy second LOW read 12.44 ms against 13.78 ms | Covered (calc7 section 5) |
| `ERR_IPACK_PLAUS` gain band (R7) | I_L,cal definition; no band dwell | State 99 in healthy traction | **FM5-5** |
| `ERR_CHG_PATH_OPEN` (R7) | Regen off-span with residual V_chg (chargerHasPower() still true) | Board load returns through the sense in reverse, V_PACKN negative: rule cannot fire | Covered |
| FC-window UVLO exit (R7) | Bus dip below 13.0 V at V_chg | Window ends, no latch; next start cold | Covered |
| `ERR_VCHG_SENSE` (a) in every mode (R7) | eFuse reverse body path in C-2a item 24 | V_chg about node - 0.6 V, above 8 V at the U_MS edge | Covered; note that `ERR_MOD_SENSE` (a) may latch in item 24 (V_chg below 9 V with pin 8 HIGH), which a power cycle clears |
| Idle-entry step 1 / step 10 (R7) | CH bit stuck HIGH at boot (Stage 2) | Step 10 deferred; `ERR_VOK_STUCK` (r below 1.003) latches | Covered |
| C-2a / C-2b split (R7) | C-2b (g) coverage | Tests configuration-check exits only | Part of **FM5-1** |
| Stage 3 (withdrawn, R7) | Hardware fitted from an older revision | Re-key deadlock of BT4-TR-01 | Covered (section 14.4; nothing fitted) |

## 4. Double faults and common causes

The following combinations were examined for a new path to the ML0227 loop, unregulated charge, a pack short, an open
pack return, BQ29200 pin overstress, a design-disabling false latch or Q_MD/R_MD dumping a live source.

1. **FM5-1 with F55 (MS shorted to SHDN_EF).** With the FM5-1 fix (EF_EN H and pin 8 HIGH immediately before the
   write), F55 still reads HIGH before and LOW 50 us after the write, so its detection is preserved. Without the fix,
   frequent false latches void probes and teach operators to ignore `ERR_MOD_SENSE` (c), which is the only in-service
   detector of F55.
2. **FM5-2 with any eFuse bypass (F11, F35, F36-M2).** A chafe that drives the shared 3V3 rail can upset U_MS, U_IM and
   FF1 at the same time. With a bypass present, the module node could be fed while the detectors are corrupted. Both
   events must coincide; the harm path is UNCONFIRMED because the failure state of over-driven LVC/TLV3011B parts is not
   specified. It is the only common cause found that couples a pack-side conductor to every LB detector at once.
3. **FM5-3 with F34b (pack-negative open) at cold.** A D_VC1 chosen for low hot leakage gives V_F above 0.25 V at cold;
   F34b then takes VC1 below -0.3 V (SLUSA52C 7.1). B-PKN at the coldest ambient is the only check.
4. **FM5-3 with a long FC window.** M16 heats beside the Ag105, D_VC1 leakage grows, and the BQ29200 cell-1 OVP moves
   late while `ERR_CELL_MISMATCH` is not evaluated (bonded only). The pack-level OV_BATT check and the Ag105 CV loop
   remain; cell-level protection of cell 1 is degraded by 26-130 mV.
5. **D_VC1 short (F47) with a dead VC1 tap (F54).** Both read a mismatch near V_pack; detection survives. Response is a
   window inhibit only, while the 16.2 mA cell-1 drain and the VC2-VC1 overstress continue with the Teensy off
   (accepted in round 4; storage rule).
6. **Shared Teensy pin.** Pin 20 is no longer shared with WDOG1_B. Pin 8 (U_MS) and pin 38 (V_chg) feed (b), (c), `ERR_MOD_FED`,
   `ERR_VCHG_SENSE` and `ERR_MOD_DUMP_ON` (through `chargerHasPower()`); a pin-38 fault that reads high keeps
   `chargerHasPower()` true and makes (c) evaluate on every exit, which the FM5-1 fix also removes.
7. **Q_MD dumping a live source.** Every new path found requires a stuck dump with a feed (F50, already covered by
   `ERR_MOD_DUMP_ON` and the R_MD fail-open requirement) or an eFuse bypass during the probe (bounded at 100 ms,
   1.71 J). Revision 7 adds no new path.

No combination examined gives a single-fault path to the ML0227 loop, an unregulated charge, a pack short or an open
pack return.

## 5. Items attacked and cleared

- RB1A at the SLUSA52C section 7.3 maximum: the balance current falls to 0.5-1 mA (SLUSA52C Table 7.6); the OVP sensing
  path does not pass RB1A, so the VC1 and VC2 readings are unchanged. The "OUT timing" reference in SLUSA52C 7.3 points
  to Figure 9 and section 8.3.1, which give no RCB dependence.
- `ERR_MOD_DUMP_ON` timing and margin (Table 2 rows); the bus is FC-only before the baseline (DD section 9.7 step 5) and
  FC_CURRENT is the FC boost output current (ino:5087: "I_fc / I_batt are the INA253 boost-OUTPUT (bus-side)"
  currents; facts_board item 2 for SNS-BT), so the 1.08-1.19 A stuck-dump step
  of calc7 section 4 applies without conversion.
- `assertFcChargeEnable(false)` writes FC_CHARGE LOW with no delay (ino:12743-12778), so the 50 us and 150 us exit
  samples are referenced to the actual feed drop in FC windows.
- The healthy node fall during a fed exit (r5 section 2).
- The deadline rule for `ERR_MOD_DRAIN` and the regen positive control (calc7 section 5).
- The Idle-entry step-10 settle and the re-evaluated `ERR_VMOT_CAL`.
