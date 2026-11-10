# Battle Test Round 1: FMEA of IC1 Detailed Design Revision 3

Date: 2026-11-07. Target: `detailed_design_IC1.md` revision 3 (cited "DD section N"). Lens: exhaustive failure-mode and
effects analysis of every new element and every existing path element that it touches, in every mode and transition,
followed by common-cause faults and credible double faults for the severe rows.

Calculations: `calc/fmea_round1_calcs.py`, with its output in `calc/fmea_round1_calcs_output.txt` (cited "FC section X").
One new primary was read for this round: TI SN74LVC1G74 data sheet SCES794G (October 2009, revised September 2021),
section 6.3 (V_IH min 2 V and V_IL max 0.8 V at V_CC 3.0-3.6 V; input transition rate 10 ns/V maximum at 3.3 V) and
the Description on p.1 (PRE and CLR both LOW force the outputs). Every other value is taken from DD, its calculation
file, the fact sheets of this study or the schematic net extraction (`references/Scale_Car_Board_20260624.sch`).

Severity follows the brief: **blocker** = unsafe or cannot work and no gate catches it; **major** = a real defect that
needs a design change or a hard bench gate; **minor** = documentation or margin.

## 1. Summary of findings

Table 1 lists the findings. Section 2 gives each finding in full. Section 3 gives the FMEA worksheet from which they
were drawn, and section 4 gives the common-cause and double-fault analysis.

Table 1. Findings.

| ID | Severity | Title |
|---|---|---|
| FM-1 | blocker | The Kelvin leads KS+ and KS- are unfused pack-negative conductors in a signal cable |
| FM-2 | major | An open VBUS tap reads "V-MOT above VBUS"; both VOK channels share the same tap pads |
| FM-3 | major | The status ladders settle in 8 ms against 1 ms and 2 ms confirmation windows |
| FM-4 | major | The injection self-test passes with U_C2 blind (R_T2b open, R_F2 open) and does not test D5 or the clamps |
| FM-5 | major | Every current monitor sits in the same series chain; a parallel pack-negative bond is invisible to all of them |
| FM-6 | major | One part (F_T or C_VT) removes the gate supply of both S_GND channels |
| FM-7 | major | With pin 33 high-Z, N1 and the FF1 clock sit at 1.5-1.8 V, inside the undefined LVC band |
| FM-8 | major | The bonded-mode barriers against the ML0227 loop are latent; nothing observes the eFuse output |
| FM-9 | minor | A drain-source short of S_GND is invisible to the SG readback; the entry check passes |
| FM-10 | minor | IC1 disables the State-99 VBUS and V-MOT drains |
| FM-11 | minor | Loss of the 5 V rail pulls OK1_N and OK2_N LOW ("OK"); Table 13 states the opposite |
| FM-12 | minor | The S_CHG interlock threshold (Q_D) and the SG readback threshold lie above the S_GND conduction threshold |
| FM-13 | minor | The FF1 clock and clear edges violate the LVC input-transition limit |
| FM-14 | minor | The hardware pack-OVP chain (BQ29200 OUT, balance lead) has no in-service observation |

The FMEA found no single fault that recreates the ML0227 loop in the bonded mode, and confirmed the following design
claims: the regen-window loop needs D-MT-EN forward-biased, which a correctly working VOK excludes; the FC-window loop
is blocked by Q_X1 and D5; a firmware error that raises pin 30 or pin 31 in the bonded mode cannot power the charger,
because the eFuse needs FF1.Q; U_C1 holds N1 LOW above 2.67-3.33 A of discharge, so FF1 cannot set during traction;
a VBATN_X short to pack positive in the charge mode is a discharge through R_SH that U_C1 interrupts by opening S_CHG
(section 3.1, row SB-12). The defects are in fail-direction choices, diagnostic coverage and wiring protection, not in
the changeover principle.

## 2. Findings

### 2.1 FM-1 (blocker): unfused Kelvin leads on the pack negative

**Claim.** KS+ connects to the pack-end terminal of R_SH, downstream of F_PK, and KS- connects to PACK- (DD Figure 1,
Table 4). Both run as a twisted pair from SB to the INA240 inputs on LB, next to the Teensy receptacles (DD sections 4.1,
4.2 item 3). Neither lead has a series resistor or a fuse. Two single faults follow:

1. **KS+ or KS- shorted to pack positive, VBT or any positive rail** (insulation chafe in the harness, a solder bridge
   on LB). The pack discharges through the signal wire. F_PK (20 A slow-blow) is the only element in the loop, and a
   signal-gauge conductor reaches its fusing current far below 20 A. For KS-, U_C1 sees the discharge through R_SH and
   trips, but its action (S_GND ON, S_CHG OFF) does not interrupt the path from PACK- through R_SH and F_PK to the pack.
   For KS+, R_SH is not even in the loop.
2. **KS+ shorted to PCB GND** (for example the LB GND plane or an INA240 GND pin). This is the F12 class: a parallel
   bond that bypasses S_GND, S_CHG and R_SH. In the charge mode the bond carries the share of the pack current set by
   the resistance ratio (FC section F: up to 5.0 A in the bond at R_s 50 mOhm and R_b 20 mOhm). See FM-5.

**Evidence.** DD Figure 1 (KS+ "at the pack end", R_SH between KS+ and KS-), Table 4 rows PACK_NEG, PACK-, KS+/KS-;
DD section 7.6 (F_PK carries the whole budget); DD Table 7 (F_PK 20 A slow-blow, TODO(verify) fuse). The wire gauge
of the twisted pair is not specified in DD Table 7 ("twisted pair KS+/KS-"). No gate in DD section 15 tests the
in-service insulation of these leads; C-1 audits static paths once, with the pack absent.

**Proposed fix.** Fit a fusible (flame-proof) resistor in each Kelvin lead **on SB, at the R_SH terminals**, so that
the cable never carries more than milliamperes. The INA240 data sheet gives the gain-error cost of series input
resistance (SBOS662C, input-filtering section; TODO(verify: SBOS662C section number)); a matched 10 Ohm pair with the
90 uA typical bias current gives a common 0.9 mV shift and a differential error set by the mismatch. Re-run the calc
section 6 trip budget with the chosen value. Treat the V_PACKN_S lead (already behind R_VPS 10 kOhm on SB) as the
model. Add a harness rule: no unfused pack-negative conductor leaves SB.

### 2.2 FM-2 (major): VOK fails toward "OK" on a VBUS-side open, and both channels share the taps

**Claim.** Each VOK comparator compares the V-MOT tap (IN-) with the VBUS tap plus an offset from its own REF (IN+)
(DD Figure 4). If the VBUS tap opens (tap wire broken, R_Bk1a or R_Bk1b open, pad lifted) the bus tap falls to the
REF offset alone, 57.7-59.4 mV, and the channel reads OK for any V-MOT above 0.62-0.64 V (FC section C). An R_Bk2 or
C_Bk short gives the same result. The V-MOT-side opens fail safe (tap at 0 V reads NOT OK). Therefore the dominant
open-circuit failure of the bus side is **fail-unsafe**.

DD Figure 4 lands both channels on the same two pads: "V-MOT at J-M pin 1 (or the CAL positive pad); VBUS at the R1-BUS
pin-2 pad". The schematic confirms that R1-BUS pin 2 is net VBUS and J-M pin 1 is net V-MOT. One lifted R1-BUS pin-2
pad, one cracked joint carrying both tap wires, or one bundled pair of tap wires that breaks, takes both channels to
OK at bus level. The 2oo2 claim of DD Table 2 (G1), Table 14 note 1 and Table 17 (HR3, "a loop needs two failures")
does not hold for this common cause.

**Consequence.** In the next regen window (pin 30 HIGH, FF1 set, pump running) both clamps Q_RG1/Q_RG2 release, the
eFuse VOK term is true, and the charger is fed from VBUS through D-MT-EN (MOT_PWR is HIGH by design) and D-BC-RG.
BT_BUS is legitimately closed in a regen window (DD Table 12), so the ML0227 loop forms with the Ag105 regulating only
the pack current and the BT boost input supplied as the unregulated I_L. The circulating input power diverges as the BT
share approaches eta_chg x eta_bt = 0.79 (FC section C2: 21.6 W at a 0.2 share, 46.2 W at 0.5). Above the eFuse I_OL
(1.84-2.16 A) the eFuse latches within 233 ms; below it, at a low BT share, the loop is sustained and only firmware G2
(3 W for 20 ms) acts. HR3 forbids a sustained loop from a single fault. U_C1, U_C2 and D5 do not act (the pack current
is the regulated 1.75 A charge; D5 is disarmed without FCQ).

**Detection gap.** `ERR_VOK_STUCK` runs only "Idle with MOT_PWR HIGH" (DD Table 16), so a tap lost during Run is
latent until the next Idle entry, and the first regen window after the loss forms the loop.

**Proposed fix.** (1) Give the two channels physically separate VBUS and V-MOT taps on different copper (for example
channel 2 on the D-MT-EN VIN side of net VBUS and on the CAL positive pad), routed in separate wires. (2) Make the
bus-side open fail safe: invert the structure so that the VBUS divider drives IN- with its bottom resistor returned to a
pull-up level, or add a third comparator per channel that asserts NOT OK when the bus tap is below a plausibility floor
(for example 1.2 V, VBUS below about 9 V) while V-MOT is above it. A plain pull-up on the bus tap cannot fix it (FC
section C: a 1 MOhm pull-up to 5 V leaves an open tap at 0.128 V). (3) Run the `ERR_VOK_STUCK` comparison every
iteration in Idle and in Run outside regen braking (V_rgn within 0.5 V of V_bus while an OK bit reads OK), not only at
Idle entry. (4) Add V2-1 sub-steps: each tap wire opened in turn, R_Bk2 shorted.

### 2.3 FM-3 (major): status-ladder settling makes every confirmation fail

**Claim.** Each R-2R ladder has a Thevenin resistance R = 20.0 kOhm into C_LA/C_LB = 100 nF (DD Figure 5), so
tau = 2.0 ms (DD calc section 7 states this). A ladder that changes code needs 2.5 ms (LSB) to 8.0 ms (MSB) to come
within the 30 mV decode tolerance (FC section B). Intermediate voltages fall within 30 mV of other codes, so firmware
reads wrong codes, not only undecodable ones, during the transition. The design requires:

- self-test step 4: FF1.Q H and both SG bits L "within 1 ms" (DD section 9.3); at 1 ms the ladder-B step (309 mV)
  still has 187 mV of error;
- window entry: "within 2 ms" (DD section 9.5 step 4, 9.7 step 3); residual 114 mV on ladder B (FC section B);
- exit: "within 2 ms ... latch `ERR_CHG_EXIT` (State 99)" (DD section 9.5 exit step 3);
- `ERR_CHG_LADDER`: "a mismatch that persists for 2 ms" (DD section 12.4 item 4).

Every self-test, every entry and every exit therefore fails as specified. In production `ERR_CHG_EXIT` enters State 99
(DD section 9.5), so the traction-exit path of DD section 9.6 (OR-2') would stop the vehicle on the first traction
request inside a window. In addition, OK1_N, OK2_N and EF_EN change at every regen pulse without a firmware command
(DD section 9.5 Hold), so a "compare with the commanded state" check (DD section 12.4 item 4) needs an explicit rule for
hardware-driven bits; DD gives none.

**Evidence.** DD Figure 5, sections 7.7, 9.3, 9.5, 12.4; calc ic1_rev3 section 7 ("tau 2.0 ms"); FC section B.

**Proposed fix.** Reduce C_LA/C_LB to 1-4.7 nF (tau 20-94 us, MSB settle 80-377 us, FC section B) and set the Teensy
ADC sample time for a 20 kOhm source (TODO(verify: IMXRT1060RM ADC sampling)), or keep the 100 nF and change every
confirmation window to 12 ms with a "settled" qualifier (two equal consecutive decodes). State which ladder bits are
hardware-driven (UC1_N, UC2_N, OK1_N, OK2_N, EF_EN, EF_FLT_N, PUMP_OK) and how the consistency check treats them. Gate
C-2 must measure the step response.

### 2.4 FM-4 (major): self-test coverage gaps on U_C2, U_C1 thresholds, D5 and the clamps

**Claim.** The U_C2 injection pulls the threshold node TH2 down through R_I2 1 kOhm (DD Figure 3). It proves that U_C2
can switch, not that its threshold is intact:

- **R_T2b open** (or its joint cracked): TH2 rises to 3.3 V, above the INA240 output ceiling of 3.1 V, so U_C2 can never
  trip in service. The injection still forces TH2 to 0.30 V and the test passes (FC section D).
- **R_T2b drift high** (for example 20 kOhm): trip at 11.0 A, test passes (FC section D).
- **R_F2 open**: SIG2 holds its last value on C_F2; the injection on TH2 still trips; in service U_C2 is blind. The
  I_PACK2 ADC path taps U_SH2 OUT upstream of R_F2 (DD Figure 3), so `ERR_IPACK_XCHK` does not see it.
- The U_C1 injection drives SIG1 to 0.66 V, so any TH1 between 0.66 V and 1.50 V passes, that is a discharge trip
  anywhere from 3.0 A to 19.8 A (FC section D).
- **D5** has no self-test step at all. R_D5c open sets its reference to 3.3 V and D5 can never trip (FC section E).
  D5 is the only hardware cut of the FC-window loop for a shorted D-BT-EN (DD Table 14 row F16).
- **Q_X1, Q_X2, Q_RG1, Q_RG2** (F6, F15d, F16b) are tested only at C-2 and B10, once.

DD Table 14 rows F8b and F24 and Table 16 (`ERR_CHG_SELFTEST` "covers F8, F8b, F9, F24") claim in-service detection
that the test does not provide for these modes. With U_C2 blind, a second fault that bypasses the Ag105 sense (F1, F19,
FM-5) leaves only the eFuse I_OL (input 1.84-2.16 A, output up to about 5 A) and its latch-off within 233 ms.

**Proposed fix.** (1) Inject on the signal side for U_C2 as for U_C1 (pull SIG2 up toward 3V3 through a resistor sized
to a level just beyond the nominal threshold), and choose both injection levels so that a nominal threshold trips and a
threshold 20 % high does not, which needs two injection levels or an ADC read of TH1 and TH2 (two spare-free options:
put TH1/TH2 on the ladders, or time-multiplex pin 23). (2) Add a D5 self-test: in Idle, inject a 60-100 mV level on the
D5 input through a FET with FCQ forced armed by a test path, or read the D5 output on a ladder bit. (3) Add an in-service
clamp test at boot: with pin 28/30/32 HIGH and the clamp gates asserted, read the EN-pad sides through a ladder bit or
an ADC divider.

### 2.5 FM-5 (major): a parallel pack-negative bond is invisible to every current monitor

**Claim.** R_SH, S_CHG, VBATN_X and the Ag105 sense are one series chain (DD Figure 1). Any parallel bond upstream of
R_SH (J-BL position 3 re-wired, a pack-side accessory sharing GND, KS+ shorted to GND, an earth-referenced scope ground
clipped to the pack negative while the Teensy USB ties PCB GND to earth) carries current that none of R_SH, I_PACK1,
I_PACK2, reg 0x06 or V_PACKN sees. In the charge mode the Ag105 regulates its sensed 1.75 A, I_PACK1 also reads 1.75 A,
`ERR_ISO_MISMATCH` sees agreement, V_PACKN/I_PACK1 equals the normal chain resistance, and U_C2 stays released, while
the true pack current is 1.75 x (1 + R_chain/R_b): 2.2-11.1 A over the plausible R_s and R_b ranges (FC section F). The
bond conductor carries the difference. `ERR_RET_DEGRADED` tests only an increase of R_ret (DD Table 16), and a bond
upstream of R_SH does not change R_ret in the bonded mode either.

DD Table 14 row F12 names V_PACKN "about 0 at all currents" as the detection; that holds only for a bond downstream of
R_SH. The remaining bounds are the eFuse I_OL (latch-off within 233 ms) and firmware G2 (3 W for 20 ms, estimated from
reg 0x06 and reg 0x07, both of which read normally here). The earthed-probe case is credible on the bench during gates
S0-3, C-2 ("SB ground offset"), V2-2 and W1.

**Proposed fix.** (1) Add a bond-integrity test at every window entry, before the charger is powered: with FF1 set and
the eFuse off, the board load flows through the chain in reverse; compare I_PACK1 with a board-side estimate of pack
discharge (BT boost output current x V_bus / (V_batt x eta) plus the 5 V load), and refuse the window if I_PACK1 is
low by more than a calibrated margin. (2) Add a bench warning to every Stage 0-2 gate: no earth-referenced probe on any
pack-side node (pack negative, PACK-, KS+/KS-, VBATN_X) while the Teensy USB is connected; use a differential probe or
a USB isolator. (3) Recheck FM-1 (KS+ to GND is a member of this class).

### 2.6 FM-6 (major): one part removes the gate supply of both S_GND channels

**Claim.** R_GU1 and R_GU2 both hang from VBT_T, which is the pack-positive tap through F_T 0.5 A, with C_VT 1 uF 25 V
from VBT_T to SGND (DD Figure 1, Table 4 row VBT_T). F_T open, C_VT shorted (which then opens F_T), or the VBT_T tap
lead open removes the gate drive of both channels. DD Table 14 row F2 states that losing both channels needs "two
faults or a common cause" and has "no hardware cut". This is a single-part common cause.

**Consequence.** The bonded return then flows through two body diodes: 5.0-7.2 W at the in-service 7.2 A and
12.0-17.1 W at 17.1 A, 6.0-8.6 W per CSD18510Q5B (FC section G). The VBT-to-GND voltage falls by the diode drop: at a
7.4 V pack and 7.2 A it is about 6.46 V, below the 6.5 V LM1084 regulation floor (SNVS037H section 5.5, via DD
section 7.6). S_CHG also loses its supply (Q_B sources from VBT_T), so charging stops; the ladder SG bits read
"not enhanced" and firmware `ERR_SGND_OPEN` / ladder mismatch can cut BT_BUS and BT_REG. The bound is firmware only.

**Proposed fix.** Feed each channel from its own tap and fuse (F_T1, F_T2), or feed the gates from VBT_T through a
current-limiting resistor without a fuse (the R_GU 10 kOhm already limits the gate current to 0.85 mA) so that no
fusible element is common, and use two series capacitors or a fail-open (flexible-termination) part for C_VT. Correct
row F2 to "single fault (F_T, C_VT, VBT_T lead)" and give it a thermal bound (time to firmware cut versus the SON5x6
thermal mass).

### 2.7 FM-7 (major): N1 and the FF1 clock float mid-band when pin 33 is high-Z

**Claim.** D_N33 joins N1 (R_N1 10 kOhm to 3V3) to pin 33 (R_P33 10 kOhm to GND) (DD Figure 2). With pin 33 high-Z
(Teensy reset, boot before `setup()`, brownout, RTWDOG reset), the two 10 kOhm resistors form a divider through the
BAT54: N1 = 1.75-1.81 V and the pin-33 node (the FF1 CLK input through R_CK) = 1.49-1.55 V (FC section A). Both lie
between V_IL max 0.8 V and V_IH min 2.0 V of the SN74LVC1G74 (SCES794G section 6.3). During the 3V3 ramp both nodes sit
near V_CC/2 at every V_CC. DD section 9.10 ("Teensy reset or brownout: pins 33, 34 fall to their pull-downs; FF1
clears"), Table 13 row FF1 and Table 17 HR5 therefore credit a clear source that does not exist in the high-Z state.

**Consequence.** During a reset in charge mode FF1 is cleared only by PUMP_OK, 43-76 ms after the last pump edge; at
power-up only PUMP_OK (C_P2 discharged) holds /CLR LOW. HR5 thus rests on one layer during reset, and a stuck-HIGH
PUMP_OK (detected only at the next boot or Idle self-test) plus a reset leaves FF1 in an undefined state with a
mid-rail clock. The charger is unpowered in this state because the RT1987 EN pins fall to their pull-downs, so the
direct consequence is bounded; the defect is the false HR5 claim and the loss of a layer.

**Proposed fix.** Use R_P33 = 1.0 kOhm (N1 = 0.59 V, FC section A) or replace D_N33 with an LVC Schmitt inverter pair
so that pin 33 drives N1 actively; put the CLK input behind an LVC1G17 instead of the 1 kOhm/1 nF RC (see FM-13).
Add gate B11c: hold the Teensy in reset (PROGRAM button) in the charge mode and confirm FF1.Q LOW within 1 ms.

### 2.8 FM-8 (major): the bonded-mode barriers are latent and the eFuse output is never observed

**Claim.** In the bonded mode the ML0227 loop needs three things: charger powered, VCHG-IN fed, D-BT-SQ conducting.
DD relies on the eFuse (needs FF1.Q) and on the D-BT-SQ cross-lock (Q_X2). Their failures are latent in service:

- F11 eFuse FET short: detection "Bench C-2; IMON test point" only (DD Table 14). Nothing reads VCHG-IN_M; pin 38 reads
  the input side (VCHG-IN).
- A short of the SHDN_EF wire downstream of R_SD (LB to CB wire, near the VCHG-IN leads of M2): ladder bit 1 reads the
  U_AND output, not the SHDN pin, so the fault is invisible.
- The M2 cut of Ag105 pin 10 leaves the board-side stub (VCHG-IN) about 1 mm from the module-side stub (VCHG-IN_M)
  (gate D-2 accepts a 1 mm standoff). A bent stub or solder bridge on a vibrating vehicle bypasses the eFuse; the same
  geometry at pins 14/15 re-bonds VBat- to GND (the F1 class).
- F5 (D-BT-SQ power-stage short) and F6 (Q_X2 open): detected only by pre-rework check D-1 and C-2.

With two of these latent (for example F11 and F6), the third element is routine: the existing State-98 `5` key or
`assertFcChargeEnable(true)` in State-99 phase 0 (facts_firmware section 2.1) feeds VCHG-IN in the bonded mode. The
module then runs with S_CHG OFF, so VBat- floats and the Ag105 sense carries nothing: this is the ML0227 condition, and
with the eFuse bypassed there is no input ceiling at all.

**Proposed fix.** (1) Add an ADC divider on VCHG-IN_M (a spare ladder bit with a comparator at 3 V is enough), and add
a boot test: with FF1 clear and pin 31 HIGH for 50 ms (VCHG-IN fed), require VCHG-IN_M below 3 V. (2) Read the SHDN_EF
pin level at CB, not the U_AND output, on ladder A bit 1. (3) Insulate both cut gaps (Kapton plus epoxy) and add a
continuity check to the State-98 self-test. (4) Block the State-98 `4`/`5` keys and the State-99 drains from raising
REGEN or FC_CHARGE while FF1.Q is LOW under `PACK_RETURN_CHANGEOVER` (see also FM-10).

### 2.9 FM-9 (minor): an S_GND drain-source short passes the entry check

**Claim.** The SG readback measures the gate (Q_Rk from Gk), not channel conduction (DD Figure 1). A drain-source
short leaves Gk pulled LOW by Q_Ak, so the bit reads "not enhanced" and DD section 9.5 step 4 passes. DD Table 14 row F1
lists "ladder SG bit stays H" as a detection; that is wrong for a channel short. The first powered interval of every
window after each reboot then runs blind into U_C2 (2.84-3.47 A) before `ERR_ISO_MISMATCH` (100 ms) latches, and with
FM-4 U_C2 may be blind.

**Proposed fix.** Before powering the charger at entry, require V_PACKN to show the reverse drop of the board load
through the chain (V_PACKN below -I_PACK1 x R_chain,min) and refuse the window when V_PACKN stays near 0 V.

### 2.10 FM-10 (minor): IC1 disables the State-99 drains

**Claim.** State 99 phase 0 drains VBUS by raising FC_CHARGE for about 10 ms and phase 1 drains V-MOT by raising REGEN
with MOT_PWR LOW (facts_firmware section 2.1, ino:8299-8327). DD section 9.9 clears FF1 first, so the eFuse is off and
both drains see only C-D8/C-D10 and R1-CHG; the REGEN drain is also clamped by VOK, because V-MOT and VBUS are near
equal. DD marks drain adequacy UNCONFIRMED but does not state why the drains exist. The drains also become the routine
third element of FM-8.

**Proposed fix.** State the purpose of the drains (from the State-99 design record); either remove them under
`PACK_RETURN_CHANGEOVER` or replace them with a dedicated bleed resistor switched by a FET on VBUS and V-MOT.

### 2.11 FM-11 (minor): 5 V loss reads as "OK"

**Claim.** R_UP1/R_UP2 pull OK1_N/OK2_N to 5 V (DD Figure 4). With 5 V absent the open-drain outputs and their pull-ups
both fall to 0 V, which is the "OK" level: Q_RG1/Q_RG2 release and U_NOR asserts VOK. DD Table 13 row D-BC-RG states
the opposite ("OK1_N or OK2_N HIGH (comparator released, unpowered or absent)"). The pump driver U_PD also runs from
5 V, so PUMP_OK falls and FF1 clears within 43-76 ms; the hazard is masked, not designed out. In Stage 1 (comparators
absent) the same 5 V loss releases the D-BC-RG clamp, contrary to DD section 14.2.

**Proposed fix.** Pull OK1_N/OK2_N up to 3V3 through the inverting sense the logic needs, or add a 5 V-present term to
the eFuse AND gate; correct Table 13.

### 2.12 FM-12 (minor): interlock thresholds versus the S_GND conduction threshold

**Claim.** S_GND conducts from V_GS(th) 1.2 V (CSD18510Q5B minimum, DD Table 7). Q_D (which blocks S_CHG) turns on at
0.3 V + 1.47 x V_GS(th),QD = 1.5-2.5 V on Gk, and Q_R (the SG readback) at 2 x V_GS(th),QR = 1.6-3.0 V (DD Figure 1
dividers; BSS138 V_GS(th) 0.8-1.5 V). A gate that stays between 1.2 V and the Q_D/Q_R thresholds (a leaky Q_Ak, a
degraded R_GUk) leaves S_GND partly conducting while S_CHG is permitted ON and the readback says "off". The effect is a
partial sense bypass bounded by U_C2. **Proposed fix.** Re-ratio the Q_D and Q_R dividers so that both act below 1.0 V
on Gk, or state the band as an accepted residual with V_PACKN as its detector.

### 2.13 FM-13 (minor): slow edges on the FF1 inputs

**Claim.** The CLK input is fed through R_CK 1 kOhm and C_CK 1 nF (tau 1 us) and /CLR through R_N1 10 kOhm into the node
capacitance; SCES794G section 6.3 limits the input transition rate to 10 ns/V at 3.3 V. The data sheet states that
clocking occurs at a voltage level, so a slow CLK edge with D tied HIGH is benign, but a slow /CLR release can toggle
near threshold. **Proposed fix.** Buffer CLK and /CLR through LVC1G17 Schmitt buffers; this also serves FM-7.

### 2.14 FM-14 (minor): the hardware pack-OVP chain is unobservable

**Claim.** The BQ29200 is powered from the balance lead (VDD through RB1B, facts_board section 2.3). A disconnected
balance plug unpowers it and removes the M8 OVP actuation; Q_OV acts on N1, which no ladder bit reads, and DD Table 14
row F25 states "not detectable in service". **Proposed fix.** Put BAL_OUT, or a divider of VBAL+, on a ladder bit and
refuse windows when the BQ29200 supply is absent.

## 3. FMEA worksheet

The modes are B (bonded: Idle, Run traction, Finish), R (regen window), F (FC window), T (transitions: entry, exit,
trip), P (power-up, reset, hang, brownout). "OK" in the verdict column means that the design's stated bound was checked
and holds; otherwise the finding is named.

### 3.1 Pack switch board (SB)

| Row | Element | Failure | Modes | Effect | Design bound | Verdict |
|---|---|---|---|---|---|---|
| SB-1 | F_PK | Open (blown, holder contact) | all | Pack return open; board GND floats; body current returns through VMID, RB3 260 Ohm and the BQ29200 VC1 input clamp, tens of mA; Teensy browns out; all EN fall to pull-downs | Brown-out is the fuse response | OK; BQ29200 input stress UNCONFIRMED |
| SB-2 | F_PK | Short / wrong rating | all | No over-current protection of the pack negative | - | OK (assembly check) |
| SB-3 | R_SH | Open | all | Pack return open, as SB-1 | - | OK |
| SB-4 | R_SH | Drift | R, F | Trip thresholds shift | 1 % assumed | OK (TODO(verify) shunt) |
| SB-5 | S_GND1 or S_GND2 | D-S short | R, F | Sense bypass; Ag105 blind | U_C2 | FM-9 (readback blind) |
| SB-6 | S_GND pair | Both lost via F_T, C_VT, VBT_T lead | B | Body-diode return, 6-8.6 W per FET at 17.1 A | Firmware only | **FM-6** |
| SB-7 | S_GNDk gate | Partial enhancement | R, F | Partial bypass with readback "off" | U_C2 | FM-12 |
| SB-8 | S_CHG | D-S short | B | Sense parallels S_GND, about 5-10 % of return through the sense | - | OK (F3) |
| SB-9 | S_CHG | Open | R, F | Charge through body diode | - | OK (F4) |
| SB-10 | Q_Ak | D-S short | all | Channel k never ON | Parallel channel | OK (F2a) |
| SB-11 | Q_B | D-S short | B | G3 driven from VBT_T through R_B3 1 kOhm; Q_D holds G3 at about 50 mV, 70 mW in Q_D | Q_D | OK, latent |
| SB-12 | VBATN_X | Short to pack positive | R, F | Discharge through S_CHG and R_SH | U_C1 trips, S_CHG opens (G3 discharged by Q_D once Gk rises) | OK (SOA of S_CHG at the prospective current UNCONFIRMED) |
| SB-13 | VBATN_X | Short to GND / module stub to barrel | R, F | F1 class | U_C2 | OK; FM-8 item 3 |
| SB-14 | VBATN_X | Open | R, F | Charger output reaches VBT; pack floats upward; body diodes carry the board load between pulses (VBT-GND 6.6 V at 7.4 V) | OV_BATT if the Ag105 ramps | OK (F14) |
| SB-15 | KS+ / KS- | Short to positive rail | all | Pack short through a signal wire | F_PK only | **FM-1** |
| SB-16 | KS+ | Short to GND | R, F | Parallel bond | eFuse I_OL, G2 | **FM-1, FM-5** |
| SB-17 | KS+ / KS- | Open | all | INA240 input undefined | BENCH | OK (F21, gated C-2) |
| SB-18 | Q_Rk | Short / open | B | SG bit stuck | Ladder mismatch | OK |
| SB-19 | Zk, Z3 | Short | B / R | Channel off / S_CHG off | - | OK |
| SB-20 | Lead A or B | Open | B | Higher SB ground offset | `ERR_RET_DEGRADED` | OK (F22) |

### 3.2 Logic board (LB)

| Row | Element | Failure | Modes | Effect | Design bound | Verdict |
|---|---|---|---|---|---|---|
| LB-1 | U_FF Q | Stuck HIGH | B | Charge mode in traction; U_C1 holds S_GND ON above 3 A | U_C1 direct path | OK (F7) |
| LB-2 | U_FF /PRE | Open or LOW | B | Q and /Q both HIGH (SCES794G p.1); X disables D-BT-SQ; as LB-1 | U_C1 | OK |
| LB-3 | N1 / pin 33 | Pin 33 high-Z | P | N1 1.75-1.81 V, CLK 1.49-1.55 V | PUMP_OK only | **FM-7** |
| LB-4 | U_BF | Output stuck HIGH | B | S_GND OFF in traction; ladder shows FF1.Q LOW, SG L | U_C1; ladder | OK |
| LB-5 | Pump C_P1 | Short | P | PUMP_OK HIGH with pin 34 static HIGH | WDOG1_B, RTWDOG; self-test | OK (F9) |
| LB-6 | U_PS | Output stuck HIGH | P | Hang layer lost | WDOG1_B | OK, latent to next self-test |
| LB-7 | U_SH2 / U_C2 path | R_T2b open, R_F2 open, R_T2b drift | R, F | Charge trip lost | eFuse I_OL | **FM-4** |
| LB-8 | U_C1 path | R_T1a drift | R | Discharge trip up to 19.8 A, test passes | Firmware exit | **FM-4** |
| LB-9 | U_D5 path | R_D5c open; Q_D5 open | F | D-BT-EN-short loop uncut | Firmware G2 | **FM-4** |
| LB-10 | VOK bus side | Tap open, R_Bk1 open, R_Bk2/C_Bk short | R | Channel OK at bus level | Other channel (unless shared pad) | **FM-2** |
| LB-11 | VOK V-MOT side | Tap open | R | NOT OK | - | OK |
| LB-12 | Q_Hk | Open / short | R | Hysteresis lost or doubled; release still above VBUS | - | OK |
| LB-13 | R_Ok | Open | R | Threshold rises (safe) | - | OK |
| LB-14 | U_NOR | Stuck HIGH / LOW | R | VOK term stuck true / false | Q_RG clamps / availability | OK (F15c) |
| LB-15 | 5 V rail | Lost | P | OKk_N LOW = OK | Pump on the same rail | FM-11 |
| LB-16 | U_AND / SHDN_EF | Output HIGH; wire short downstream of R_SD | B | eFuse enabled when VCHG-IN fed | Firmware; Q_RG | **FM-8** (downstream short invisible) |
| LB-17 | Q_X1 | Open | F | BT_BUS not clamped | `assertFcChargeEnable()`, D5 | FM-4 item 3 (latent) |
| LB-18 | Q_X2 / X node | Open | B | D-BT-SQ enabled in bonded mode | eFuse | **FM-8** (latent) |
| LB-19 | Q_RG1 or Q_RG2 | Open | R | One clamp lost | Other clamp, eFuse VOK term | OK, latent |
| LB-20 | Ladders | Settling | T | All confirmations fail | - | **FM-3** |
| LB-21 | Injection FETs | Short | R, F | Comparator permanently tripped | Availability | OK |
| LB-22 | Q_OV / BAL_OUT | Open; balance plug off | R, F | Hardware OVP lost | Ag105 CV, OV_BATT | FM-14 |
| LB-23 | WDOG1_B | Path open / pin mux unavailable | P | Hang layer lost | Pump, RTWDOG | OK (F9b) |

### 3.3 Charger adapter (CB) and the Ag105

| Row | Element | Failure | Modes | Effect | Design bound | Verdict |
|---|---|---|---|---|---|---|
| CB-1 | U_EF FET | Short | all | Charger powered whenever VCHG-IN is fed | Firmware; cross-lock | **FM-8** (latent) |
| CB-2 | U_EF | Fails open / latches | R, F | No charging | FLT on ladder | OK |
| CB-3 | M2 cut gap | Re-contact | all | eFuse bypassed | None | **FM-8** |
| CB-4 | M1 cut gap | Re-contact | R, F | VBat- to GND | U_C2 | OK; FM-8 item 3 |
| CB-5 | R_SDP | Open | B | SHDN floats only if the wire also opens | - | OK (F13) |
| CB-6 | RCS / MPPTS networks | Any single fault | R, F | Current at or below 1.75 A | - | OK (calc ic1_rev3 section 3) |
| CB-7 | LD tie | Open | R, F | Unknown effect on the sense-parallel switch | S0-2 | OK (gated) |
| CB-8 | Ag105 | Internal sense switch closed | R, F | Blind regulation | U_C2 (FM-4 caveat) | OK (F19) |
| CB-9 | Ag105 | Stored reg 0x01 = 3S | R | 12.6 V CV; readback never runs in a regen window, because a regen pulse is shorter than `AG105_SETTLE_MS` | OV_BATT single sample; BQ29200 (FM-14) | OK, margin minor |

### 3.4 Existing path elements and Teensy pins

| Row | Element | Failure | Modes | Effect | Design bound | Verdict |
|---|---|---|---|---|---|---|
| EX-1 | D-BT-SQ | Short | B | VCHG tied to VBT | eFuse | FM-8 (latent) |
| EX-2 | D-BC-RG | Short | R | V-MOT on VCHG-IN | eFuse VOK term; V_chg diagnostic in Run | OK (F15) |
| EX-3 | D-BC-FC | Short | R | VCHG-IN tied to VBUS; regen pulse pushes VBUS up through D-BC-RG and the short until VOK releases | VOK release; OV_BUS | OK (F17; the VBUS pump is new and benign) |
| EX-4 | D-MT-EN | Short | R | V-MOT clamped to VBUS; VOK never asserts | Availability | OK |
| EX-5 | D-BT-EN | Short | F | FC-window loop | D5 | OK (F16; FM-4 latent D5) |
| EX-6 | TPS61288 BT | Disabled with VBT fed by the charger | R, F | HS body diode to VOUT-BT at about VBT - 0.7 V, below VBUS | - | OK |
| EX-7 | Teensy pin 34 | Hang static | P | FF1 clears in 43-76 ms | Pump | OK |
| EX-8 | Teensy pin 33 | High-Z | P | See LB-3 | - | **FM-7** |
| EX-9 | Teensy pins 28-32 | High-Z | P | RT1987 EN pull-downs; charger unpowered | Bodge 10 kOhm | OK |
| EX-10 | Teensy 3V3 | Lost | P | All logic unpowered; eFuse held off by R_SDP | - | OK |
| EX-11 | State 98 keys / State-99 drains | Raise FC_CHARGE or REGEN with FF1 clear | B | VCHG-IN fed in the bonded mode | eFuse (latent) | FM-8, FM-10 |

## 4. Common-cause faults and credible double faults

Table 2 lists the common causes found. Table 3 lists the double faults that reach a severe outcome.

Table 2. Common-cause faults.

| CC | Cause | Elements defeated together | Outcome | Finding |
|---|---|---|---|---|
| CC-1 | Shared R1-BUS pin-2 pad or shared tap wiring | VOK channels 1 and 2 | Regen-window loop | FM-2 |
| CC-2 | F_T / C_VT / VBT_T lead | S_GND1 and S_GND2 gate supply, S_CHG supply | Body-diode return, LM1084 margin | FM-6 |
| CC-3 | One Kelvin pair to U_SH1 and U_SH2 | U_C1, U_C2, I_PACK1, I_PACK2 | Both trips blind on a lead fault | Acknowledged F21; FM-1 |
| CC-4 | 5 V rail | VOK pull-ups and the pump | Masked by the pump | FM-11 |
| CC-5 | Earthed instrument on the pack side with USB connected | Every chain monitor | Unseen bond current | FM-5 |
| CC-6 | Vibration at the 1 mm cut gaps (M1, M2) | eFuse and VBat- isolation | eFuse bypass; F1 class | FM-8 |

Table 3. Credible double faults with a severe outcome.

| DF | Faults | Outcome | Remaining bound | Finding |
|---|---|---|---|---|
| DF-1 | F11 (eFuse short, latent) + F6 (cross-lock open, latent), then State-98 `5` key or State-99 phase 0 | ML0227 loop in the bonded mode with VBat- floating, no input ceiling | None in hardware; firmware G1/G2 only where they run | FM-8 |
| DF-2 | U_C2 blind (R_T2b open, passes self-test) + S_GND D-S short (passes entry check) | Unregulated charge current in every window | eFuse I_OL, latch-off at most 233 ms; `ERR_ISO_MISMATCH` 100 ms | FM-4, FM-9 |
| DF-3 | D5 reference open (latent) + D-BT-EN short | Sustained FC-window loop below the eFuse I_OL | Firmware G2 | FM-4 |
| DF-4 | One VOK bus tap open (latent until Idle) + the other channel's tap open | Regen-window loop | eFuse I_OL, G2 | FM-2 |
| DF-5 | F_PK holder degrading + both return leads on the J-BT pin-2 barrel | Open return, Teensy brown-out, balance-lead current through the BQ29200 inputs | All EN fall to their pull-downs | SB-1 |

No credible double fault reaches pack over-charge past the BQ29200 threshold while the balance lead is connected: the
Ag105 CV loop is a voltage loop that a sense bypass does not defeat, firmware `OV_BATT` acts on one sample at 8.5 V, and
the BQ29200 clears FF1 within 2.0-4.0 s. No credible single or double fault was found that re-closes MOT_PWR onto a
discharged V-MOT node (Death-5) or that back-feeds a disabled TPS61288, because IC1 neither switches MOT_PWR nor adds a
path into VOUT-BT or VOUT-FC.
