# IC2: Autonomous Direction-Steered Pack Return

Design dossier for isolation concept IC2 of the battery-isolation feasibility study. Date: 2026-11-07,
revision 1 (after review round 1; section 10 holds the adjudication). Board revision 20260622, firmware
fw v37 rev 2 (`AG105_VBATN_ISOLATED 0`, `BENCH_TEST 1`). Inputs: `brainstorm.md`, `facts_board.md`,
`facts_ag105.md`, `facts_firmware.md` and `facts_prior.md` in this folder. Citation tags: **DS** = Ag105 DS
V1.1 (Nov 2021); **SLVSFP3C** = TPS61288; **SNVS037H** = LM1084; **DS-00** = RT1987; **SLUSA52C** = BQ29200;
**SLPS492B** = CSD17573Q5B; **SNOSD50A** = TLV1805; **SBOS793H** = INA181; **SCES217AA** = SN74LVC1G08;
**SCES794G** = SN74LVC1G74; **SBVS366A** = TPS3430; **SLVSE94G** = TPS2663. SCES794G, SBVS366A and SBOS793H
were read in review round 1 (TI vendor PDFs, text-extracted; not saved in the repository). Values that no
primary gives are marked BENCH or TODO(verify: source). Inferences are marked UNCONFIRMED. Nothing in this
dossier is ordered, desoldered or flashed.

## 0. Summary of the design position

This section states the design position in eight points, so that the reader can test each later section
against it.

1. IC2 keeps pack positive permanently on VBT. Only the pack return is steered. The Teensy supply and the
   pack buffering of the bus therefore remain as today (section 4.5, Table 8).
2. The pack return splits on an off-board **return-splitter board** into a **charge leg** through the
   Ag105 internal current sense (pack negative to VBat- pins 14/15, restored) and a **bypass leg** through a
   low-side NFET to PCB GND. A pack-current shunt and comparators select the leg.
3. Steering is **permitted only while a charger input is commanded**. Outside charge windows the splitter
   is held in **FORCED BYPASS**: the sense leg is open and the bypass FET is on at any current. The GAP and
   SENSE states therefore exist only inside charge windows (review finding E-M1 / S-MAJ-1).
4. The steering restores Ag105 regulation of the **pack** current. It does not by itself break the
   circulating loop bus to charger to VBT to BT boost to bus (finding X3, section 4.7). Hardware gates on the
   RT1987 enables carry the loop break, and the charger output switch D-BT-SQ conducts only while a charger
   input is commanded.
5. A wired-OR **LATCH** removes charger input and output power on any of seven hardware detections: pack
   over-current, splitter supply or reference failure, the external watchdog, the MCU watchdog output,
   bus-to-charger current in an FC window, and uncommanded charger input voltage (section 2.10).
6. A TPS2663 eFuse in VCHG-IN is **mandatory** (it was optional in revision 0). It bounds the charger input
   current in every single-fault case that the gates cannot open.
7. The Ag105 charge-current setting is lowered from 2.5 A to **1.5 A** (reg 0x00 = 0x04, DS Table 4) so that
   an FC window fits the FC budget (section 4.10). This changes CLAUDE.md section 3 and needs an operator
   ruling.
8. IC2 does not solve the regen cold-start limit (finding X6) or the H-20 purge limit. **HR1 FAILS** by
   calculation for the cold-start design, so IC2 does **not** satisfy operator ruling 1. HR2 is BENCH and at
   risk on the Ag105 Bring-Up time (section 4.10). Section 4.11 records a warm-regen variant for an operator
   ruling; its HR1 status is UNDETERMINED.

## 1. Topology

### 1.1 Nets added or changed

Table 1 defines the new nets. Every other net keeps its 20260622 name and members.

Table 1. New and changed nets.

| Net | Members | Origin |
|---|---|---|
| `PACK_P` | Pack positive lead, main fuse F_MAIN, shunt R_SH (pack side) | Off-board, pack harness |
| `VBT` (unchanged on the board) | J-BT pin 1 via the splitter output lead, R_SH (board side) | Existing |
| `PACK_N` | Pack negative lead, Q_A source, Q_B drain | Off-board, splitter board |
| `GND_RET` | Q_B source; lead A to J-BT pin 2; lead B to J-BL pin 3 | Splitter side of PCB `GND` |
| `VBAT_N` | Q_A drain, fuse F_VBN, flying lead to the cut stubs of Ag105 pins 14/15 | New; formerly `GND` |
| J-BL pin 3 | Balance-lead negative wire removed and insulated; the terminal now receives GND_RET lead B | Finding X1; review F-M6 |
| `VCHG-IN` (split) | Board side: D-BC-FC VOUT, D-BC-RG VOUT, C-D8, C-D10, R1-CHG. Module side: TPS2663 OUT to the cut stub of Ag105 pin 10 | Review F-M1 / S-MAJ-6 |

### 1.2 Diagram

Figure 1 shows the power topology. Arrows mark the conducting direction of each leg. The splitter board is
in the pack harness next to J-BT; the Ag105 pin-14/15 and pin-10 flying leads are the only new power
conductors on the PCB itself.

```
 Figure 1. IC2 power topology (power conductors only).

  PACK+ ─[F_MAIN]─[R_SH 2 mOhm]──────────────────── J-BT pin 1 ── VBT ──┬── REG-BT (TPS61288) VIN
          (INA181 #1, #2 sense here, VCM = VBT)                         ├── REG-5V (LM1084) ─ 5V ─ Teensy
                                                                        ├── R1-BT/R2-BT (V_batt)
                                                                        └── D-BT-SQ VOUT ◄── VCHG ◄── Ag105 VBat+ (18/19)

  PACK- ── PACK_N ──┬── Q_B (D)  Q_B (S) ── GND_RET ──┬── lead A ── J-BT pin 2 ──┐
                    │   bypass leg (body diode         └── lead B ── J-BL pin 3 ──┴── PCB GND ─┬── Ag105 Vin- (pin 4)
                    │   = discharge direction)                                                ├── BQ29200 GND, REG-BT PGND
                    │                                                                         └── INA253 GND/REF, Teensy GND
                    └── Q_A (S)  Q_A (D) ─[F_VBN]─ VBAT_N ── flying lead ── Ag105 VBat- (14/15, stubs cut free)
                        charge leg (body diode = charge direction)                   │ internal sense (DS Fig.1 p.3)
                                                                                      └── Vin- = GND

  VCHG-IN (board) ── TPS2663 eFuse ── flying lead ── Ag105 Vin+ (pin 10, stub cut free)
  J-BL pin 1 (VBAL+), pin 2 (VMID): unchanged.
```

### 1.3 Current directions

The steering rule follows from the two current directions. Discharge current leaves pack positive, crosses
the board and returns from PCB GND to PACK_N. Charge current enters pack positive from the Ag105 through
D-BT-SQ and returns from PACK_N to GND. The charge return through Q_A and VBat- crosses the Ag105 sense,
which is the topology that DS p.4 Table 2 requires (VBat- "Must NOT be connected directly to the GND pin").

- **Q_B (bypass leg).** NFET, drain PACK_N, source GND_RET. Its body diode (anode = source) conducts
  GND_RET to PACK_N, that is the discharge direction. With its channel OFF, Q_B blocks the charge direction.
- **Q_A (charge leg).** NFET, source PACK_N, drain VBAT_N. Its body diode conducts PACK_N to VBAT_N, that is
  the charge direction. With its channel OFF, Q_A blocks discharge through the sense.

Therefore, whenever Q_B is OFF, every charge current crosses the sense, through either the Q_A channel or
its body diode.

### 1.4 Steering states

The splitter has four states. Table 2 defines them. "I_dis" is the pack current measured on R_SH, positive
for discharge. "PERMIT" is the interposer signal of section 2.6; it is true only while a charger input is
commanded and LATCH and BOND_FORCE are both inactive.

Table 2. Steering states.

| State | PERMIT | Q_A | Q_B | Entered when | Return path |
|---|---|---|---|---|---|
| **FORCED BYPASS** | false | OFF (held) | ON (forced) | PERMIT false, at any current | Q_B channel |
| **SENSE** | true | ON | OFF | I_dis falls below 0.30 A (includes every charge current) | Through the Ag105 sense |
| **GAP** | true | OFF | OFF | Between transitions: 0.60 A < I_dis < 1.00 A rising, 0.70 A > I_dis > 0.30 A falling | Q_B body diode |
| **BYPASS** | true | OFF | ON | I_dis rises above 1.00 A | Q_B channel |

The thresholds are nominal; their tolerance is analysed in section 4.4. FORCED BYPASS is the default in
reset, with the interposer cable open, and on a splitter supply or reference failure (section 2.5).

## 2. Parts, gate drive and fail-safe defaults

### 2.1 Power switches Q_A and Q_B

Both legs use the TI CSD17573Q5B, so that one part number and one footprint cover both. Table 3 lists the
ratings that the design uses.

Table 3. CSD17573Q5B ratings (SLPS492B, p.1 Absolute Maximum Ratings and Product Summary; p.3 sections 5.1
and 5.2).

| Parameter | Value | Source |
|---|---|---|
| V_DS | 30 V | p.1 |
| V_GS absolute maximum | +/-20 V | p.1 |
| R_DS(on), V_GS = 4.5 V, I_D = 35 A | 1.19 mOhm typ, 1.45 mOhm max | p.3, 5.1 |
| R_DS(on), V_GS = 10 V, I_D = 35 A | 0.84 mOhm typ, 1.00 mOhm max | p.3, 5.1 |
| V_GS(th) | 1.1 / 1.4 / 1.8 V (min/typ/max) | p.3, 5.1 |
| Q_g total at 4.5 V | 49 nC typ, 64 nC max | p.3, 5.1 |
| C_iss | 6920 pF typ, 9000 pF max | p.3, 5.1 |
| Body diode V_SD, I_SD = 35 A | 0.8 V typ, 1 V max | p.3, 5.1 |
| I_D continuous (package limited) | 100 A | p.1 |
| I_D continuous (1 in^2, 2 oz pad) | 43 A | p.1 note 1 |
| R_thJA | 40 C/W typ (1 in^2, 2 oz Cu); 50 C/W max (5.2) | p.1 note 1; p.3, 5.2 |
| R_thJC | 0.8 C/W max | p.3, 5.2 |
| T_J | -55 to 150 C | p.1 |

The voltage across either FET in normal service is below 1 V (section 4.2). The 30 V rating covers a pack
whose own protection circuit opens, when PACK_N can rise towards VBT (at most the 8.5 V `LIMIT_V_BATT_MAX`
plus the Ag105 CV error; UNCONFIRMED worst case, BENCH).

### 2.2 Current measurement: R_SH, INA181 #1 and INA181 #2

The pack current is measured high-side on PACK_P. This placement keeps the amplifier common-mode at VBT
in every steering state; a low-side shunt on PACK_N would see about -0.8 V in the GAP state, which is
outside the INA181 input range.

- **R_SH**: 2 mOhm, four-terminal metal-element shunt, power rating >= 2 W. The part is not yet selected;
  its tolerance and temperature coefficient are TODO(verify: vendor datasheet). Dissipation at 17.1 A is
  17.1^2 x 0.002 = 0.585 W.
- **INA181A2** x 2 (SBOS793H): supply 2.7-5.5 V; common-mode -0.2 V to +26 V (p.1 Features); gain options
  20 / 50 / 100 / 200 V/V for A1-A4, A2 = 50 V/V (p.1); offset 150 uV maximum at V_IN+ = 0 V and 500 uV
  maximum otherwise (section 6.5, V_OS rows); quiescent current 260 uA maximum (p.1); bandwidth 210 kHz for
  A2 (section 6.5); bidirectional through the REF pin (p.1). The REF pin impedance requirement is
  TODO(verify: SBOS793H section 8, REF pin).
- **Input protection.** Each INA181 input has a series resistor of at most 10 Ohm to limit fault current
  from PACK_P (value bounded by the gain error from the input bias current, TODO(verify: SBOS793H section
  8)).
- **Polarity.** The amplifier inputs are connected so that discharge **lowers** the output:
  V_AMP = V_IREF - 0.1 V/A x I_dis, with V_IREF = 1.650 V. An unpowered or failed amplifier output near 0 V
  therefore reads as a large discharge and selects BYPASS (rationale in section 5, fault F5).
- **Range.** 0.1 V/A x 16 A = 1.6 V, so the linear range is about +/-16 A (the output-swing limits are
  (V_S) - 0.03 V and (V_GND) + a few mV maximum, SBOS793H section 6.5, V_SP / V_SN rows). The 17.1 A boost
  switch limit is a peak inductor value, not the average input current, so the range covers the average
  pack current (UNCONFIRMED; the vehicle I_batt peak from the Pi bags is bench gate X8).
- **INA181 #1** feeds U_A, U_B and Teensy pin 16. **INA181 #2** feeds U_OC, the Q_A veto comparator U_AV and
  Teensy pin 17. Two packages are used so that a single amplifier failure cannot blind both the steering
  and the protection layer (section 5, F5, F6).
- **Supply.** A local 3.3 V low-dropout regulator on the splitter board, fed from PACK_P through a PTC,
  supplies both amplifiers only. The comparator references come from a separate shunt reference (section
  2.3). The regulator part is not selected; requirements: input >= 9 V absolute, quiescent current
  < 100 uA (TODO(verify: vendor datasheet)).

### 2.3 Comparators and gate drivers U_A, U_B, U_OC, U_AV

Each FET is driven directly by a TLV1805 push-pull comparator. Table 4 lists the ratings used.

Table 4. TLV1805 ratings (SNOSD50A).

| Parameter | Value | Source |
|---|---|---|
| Supply V_S | 3.3-40 V recommended; 42 V absolute maximum | 6.3; 6.1 |
| Input common-mode range | (V-) - 0.2 V to (V+) + 0.2 V | 6.5 |
| Input offset V_IO | +/-0.5 mV typ, +/-4.5 mV max (25 C); +/-6.5 mV max (-40 to 125 C) | 6.5 |
| Built-in hysteresis | 14 mV typ | p.1 Features; 6.5 |
| Propagation delay | 250 ns typ | p.1 Features; 6.6 |
| Peak source current | 300 mA typ (output shorted to V-) | 6.5 |
| Peak sink current | TODO(verify: SNOSD50A 6.5, the extracted column is ambiguous) | 6.5 |
| Shutdown | Active-high SHDN, output high-Z in shutdown; SHDN maximum (V-) + 5.5 V | p.1; 6.1 |
| Power-on reset | Prevents false outputs at power-up | p.1 |

Supply rails and references are chosen so that each comparator output LOW is exactly the source of the FET
it drives:

- **U_B (Q_B):** V+ = PACK_P, V- = GND_RET (the Q_B source). Inverting: V_AMP1 drives IN- through a
  2.0 kOhm / 10 nF filter (tau = 20 us). IN+ takes V_REF_B through R1 = 2.0 kOhm, with R2 = 1.0 MOhm feedback
  from OUT. External hysteresis = V_OH x R1/R2 = 7.8 V x 0.002 = 15.6 mV (14.0 mV at 7.0 V, 17.0 mV at 8.5 V),
  plus the 14 mV built-in, about 30 mV = 0.30 A. Turn-on at V_AMP1 < 1.550 V (I_dis > 1.00 A); turn-off near
  V_AMP1 > 1.580 V (I_dis < 0.70 A). A 1.0 MOhm resistor from PACK_P to IN+ biases IN+ positive when the
  reference is absent (section 2.5); its 16 mV nominal shift is folded into V_REF_B.
- **U_A (Q_A):** V+ = PACK_P, **V- = PACK_N** (the Q_A source; revision 0 used GND_RET, review F-M4).
  Non-inverting: V_AMP1 drives IN+ through R1 = 2.0 kOhm with R2 = 1.0 MOhm feedback; IN- takes V_REF_A.
  Q_A turns on for V_AMP1 > 1.620 V (I_dis < 0.30 A) and off for V_AMP1 < about 1.590 V (I_dis > 0.60 A).
  The input common mode relative to PACK_N is 1.65-2.65 V, inside the range of Table 4. A comparator LOW
  now gives V_GS(Q_A) = 0 V in every state, including GAP and fault F2.
- **U_AV (Q_A veto, new):** V+ = PACK_P, V- = PACK_N. It compares V_AMP2 against the Q_A turn-off
  reference (I_dis > 0.60 A) and drives a small NFET from the Q_A gate to PACK_N. A discharge seen by
  channel #2 therefore turns Q_A OFF even if channel #1 has failed high (review F-M3).
- **U_OC (over-current):** V+ = PACK_P, V- = GND_RET. V_AMP2 drives IN+ through a 1 ms RC (rejects the
  300 mAp-p Ag105 ripple current, DS p.20 row 13); IN- takes V_REF_OC = 1.650 + 0.1 x 2.2 = 1.870 V. A charge
  current above 2.2 A sets LATCH through the open-drain crossing of section 2.6. 2.2 A lies above the Ag105
  own trip at the new 1.5 A setting, set + 200 mA = 1.7 A (DS p.18), so the latch does not pre-empt a normal
  Ag105 trip.
- **References.** V_IREF, V_REF_A, V_REF_B, V_REF_OC come from one 0.1 % divider string on a **shunt
  reference fed from PACK_P**, not from the amplifier LDO (review E-M3). Each tap drives its comparator
  through a buffer or has a Thevenin impedance <= 100 Ohm, so that the U_A/U_B feedback current (about
  8 uA through 1 MOhm) shifts no tap by more than 1 mV (review E-m7). The INA181 REF pins and the Teensy
  V_IREF line are driven by a unity-gain buffer powered from PACK_P. Part numbers: TODO(verify: vendor
  datasheet).

### 2.4 Gate networks and break-before-make

Each gate has a 10 kOhm series resistor bypassed by a small Schottky diode (cathode towards the comparator
output), and a 100 kOhm gate-to-source pull-down to the FET source. Turn-on is therefore slow and turn-off
is fast:

- Turn-on: tau = 10 kOhm x C_iss (6.92 nF typ) = 69 us; V_GS reaches V_GS(th) = 1.4 V of 7.8 V after
  about 0.2 tau = 14 us (UNCONFIRMED first-order estimate; the Miller plateau adds delay).
- Turn-off: through the Schottky at the comparator sink current; with Q_g = 64 nC maximum and an assumed
  100 mA sink, about 0.6 us (sink current TODO(verify: SNOSD50A 6.5)).
- The current thresholds separate the two conduction states by a GAP band, and the timing asymmetry adds a
  second separation, so Q_A and Q_B are never ON together (section 4.4).
- The 100 kOhm pull-downs hold both gates OFF when the comparators are unpowered, in POR or high-Z. Both
  FETs OFF is a defined state: discharge flows through the Q_B body diode, and charge through the Q_A body
  diode and the sense.
- The veto and force NFETs act on the gate node behind the 10 kOhm resistor or on the comparator inputs.
  They never contend with a push-pull output through less than 10 kOhm (about 0.85 mA at 8.5 V).

### 2.5 FORCED BYPASS injection (redesigned, review F-M5 / E-m1)

Revision 0 injected BOND_FORCE through a series diode. Both reviewers showed that the polarity cannot work
as drawn. The injection is now an active-high **nFORCE** line on the splitter:

- **Pull-up.** nFORCE is pulled to PACK_P through 100 kOhm on the splitter. With no interposer pull-down it
  is HIGH, that is FORCED BYPASS. An open signal cable therefore selects FORCED BYPASS.
- **Release.** The interposer releases steering by pulling nFORCE LOW with an NFET (source = PCB GND) while
  PERMIT is true (section 2.6).
- **Q_A held OFF.** Through a 2:1 divider, nFORCE drives NFET N1 (source = PACK_N) that clamps the Q_A gate
  to PACK_N.
- **Q_B forced ON.** Through a 2:1 divider, nFORCE drives NFET N2 (source = GND_RET) that pulls U_B IN- (the
  filtered V_AMP1 node, 2 kOhm source) to GND_RET. U_B IN+ stays above 0 V through V_REF_B, or through the
  1 MOhm bias of section 2.3 if the reference is absent. U_B therefore drives Q_B ON.
- **Logic-low margin.** When the interposer pulls nFORCE LOW, the line sits at PCB GND. PCB GND is up to
  about 0.34 V above GND_RET at 17.1 A (lead resistance, section 2.6) and up to 1 V above PACK_N in GAP. The
  divider halves this to <= 0.67 V at the N1/N2 gates. N1 and N2 must therefore have V_GS(th) min >= 1.5 V
  (part TODO(verify: vendor datasheet)).
- **Supervisor.** A dual-channel voltage supervisor monitors the amplifier LDO output and the shunt
  reference. On an under-voltage of either, its open-drain output pulls nFORCE HIGH through a PFET (or holds
  the release NFET off) and pulls the LATCH preset line LOW (section 2.6). Part TODO(verify: vendor
  datasheet).

Table 2a gives the resulting truth table. "x" means either level.

Table 2a. FORCED BYPASS truth table.

| PERMIT (interposer) | Cable | LDO, reference | Supervisor | Result |
|---|---|---|---|---|
| false | x | x | x | FORCED BYPASS |
| true | intact | good | quiet | Autonomous steering (SENSE / GAP / BYPASS) |
| true | open | x | x | FORCED BYPASS (pull-up) |
| true | intact | LDO failed | asserts | FORCED BYPASS and LATCH set; also V_AMP near 0 V selects BYPASS on its own |
| true | intact | reference failed | asserts | FORCED BYPASS and LATCH set; U_B IN+ held positive by the 1 MOhm bias |
| floating (Teensy reset, interposer unpowered) | intact | x | x | FORCED BYPASS: PERMIT pull-downs, NFET off |

### 2.6 Interposer: gated enables, PERMIT, LATCH and crossings

The loop break and the inhibit are implemented by gating four RT1987 enable lines on a **Teensy
interposer**: a 2 x 24 stacking adapter between the Teensy and the J1/J2 receptacles. It breaks Teensy pins
28, 30, 31 and 32 out of the receptacle contacts and drives the receptacle contacts from gate outputs. No
board copper is cut. The interposer mechanical clearance, retention and the integrity of the 44
pass-through contacts are BENCH.

**Input pull-downs (review F-M2).** Every interposer input from the Teensy (pins 10, 28, 30, 31, 32, 33)
has a 10 kOhm pull-down at the gate input. The i.MX RT1062 pads default to input with a keeper (PJRC,
facts_board section 7.3); a keeper that holds a HIGH across a warm or RTWDOG reset would otherwise appear as
a strong HIGH at an LVC input. The <= 47 kOhm rule of the prior study (facts_prior section 10 item 6)
applies. Pad behaviour across a reset remains TODO(verify: PJRC/NXP) and is bench gate B2.

Table 5 defines the gated levels. Abbreviations: **BF** = pin 33 `PACK_BOND_FORCE`; **L** = LATCH Q
(HIGH = inhibit); **VOK** = VMOT_OK1 AND VMOT_OK2 (section 2.7); **FCD** = pin 31 with a 20 ms
falling-edge delay; **CMDD** = (pin 31 OR pin 30) with a 20 ms falling-edge delay. The delays are diode-RC
stages into Schmitt buffers (part TODO(verify: SN74LVC1G17 datasheet)); a rising edge passes at once.

Table 5. Gated RT1987 enables and PERMIT (levels seen by the board).

| Output | Equation | Purpose |
|---|---|---|
| D-BT-EN | pin28 AND NOT FCD | BT_BUS cannot conduct while FC_CHARGE is commanded, nor for 20 ms after it drops (loop break X3; removes the reversal pulse of review E-m6 at window end) |
| D-BC-FC | pin31 AND NOT L AND NOT BF | Charger input from VBUS |
| D-BC-RG | pin30 AND VOK AND NOT L AND NOT BF | Charger input from V-MOT only while V-MOT is above the bus by the VMOT_OK margin |
| D-BT-SQ | pin32 AND CMDD AND NOT L AND NOT BF | Charger output reaches VBT only while a charger input is commanded (review F-M1). Built in a separate gate package from the D-BC gates. |
| PERMIT | CMDD AND NOT L AND NOT BF | Releases nFORCE (section 2.5); the sense stays in the return for 20 ms after the input is removed |

The falling-edge delay on CMDD makes the hardware order at the end of every window: input off, then
20 ms, then charger output off and FORCED BYPASS. The 20 ms value is TODO(calibrate) against the Ag105
output decay (bench gate B3).

Logic family: SN74LVC1G08 AND gates and SN74LVC1G04 inverters on the Teensy 3V3 (SCES217AA: inputs tolerant
to 5.5 V, I_off partial-power-down, p.1). The RT1987 EN thresholds are V_EN_R <= 1.4 V and V_EN_F >= 0.6 V
(DS-00 section 17.1 and EC table), so a 3.3 V LVC output drives them directly. With the Teensy 3V3 absent the
LVC outputs are high-Z (I_off), and the existing 10 kOhm EN pull-downs (bodge B7, coverage OQ-7) plus the
RT1987 internal pull-down hold every switch OFF.

**Invariants made hard by the gates (review F-m9, E-m10).** (1) D-BT-EN re-closes in hardware 20 ms after
pin 31 falls. This is benign only while firmware also holds pin 28 LOW during windows, which it does at
ino:12761. (2) D-BT-EN drops at once on pin 31 HIGH, while FC_CHARGE conducts only after t_D_ON = 8 ms
(DS-00 17.1). Any firmware path that raises pin 31 with FC_BUS not conducting collapses the bus (the
campaign-G F1 class). The fw v28 conduction gate prevents this today (facts_firmware section 3.2 item 5).

**LATCH (review F-m1, F-m2).** LATCH is an SN74LVC1G74 (SCES794G). PRE and CLR are active-low
(SCES794G pin functions, "Pull low to set Q output high"; Table 8-1). The input voltage range is -0.5 to
6.5 V absolute (SCES794G 6.1). Connections:

- D tied LOW; CLR tied HIGH (inactive); CLK = Teensy pin 10 `PACK_LATCH_RESET`. A rising clock edge loads
  Q = 0. A LOW on PRE sets Q = HIGH regardless of CLK (Table 8-1), so a stuck or keeper-held reset line can
  never mask a set request. The PRE-and-CLR-both-LOW state (Q and Q-bar both HIGH, Table 8-1 note 1) cannot
  occur because CLR is not used.
- **nPRE** is a wired-OR open-drain line, pulled to 3V3 through 10 kOhm on the interposer, with an RC that
  holds it LOW for about 50 ms at power-up (LATCH SET at power-up; BENCH gate B2). It has a Schottky clamp
  to PCB GND so that an open-drain LOW at GND_RET potential stays above the -0.5 V input limit.
- Set sources (each open-drain onto nPRE): see section 2.10.

**Crossings (review F-M6, E-M2, F-m1, F-m4).** No ground conductor runs between the splitter and the
interposer. GND_RET reaches PCB GND only through the two power return leads. Every signal crosses as
follows:

- **Splitter to interposer, digital:** open-drain NFETs on the splitter (source = GND_RET), pulled up to
  3V3 on the interposer, clamped to PCB GND by Schottky diodes, then buffered by LVC. This applies to the
  U_OC trip, the supervisor, and the Q_A / Q_B gate states. The Q_A status NFET has its source on GND_RET
  and its gate on the Q_A gate node (V_GS <= 0 V when Q_A is OFF). No PACK_P-level signal reaches an LVC
  input; the revision-0 47k/47k dividers are removed.
- **Splitter to Teensy, analog:** V_AMP1 (pin 16), V_AMP2 (pin 17) and the buffered V_IREF (pin 23). The
  firmware computes I_dis = (V_IREF - V_AMP) / 0.1 V/A, so the GND_RET-to-PCB-GND offset (up to about
  0.34 V at 17.1 A through a 20 mOhm contact, TB005-762 p.1) cancels as a common-mode term. Each line has a
  1 kOhm series resistor at the Teensy end.
- **Interposer to splitter:** the nFORCE release NFET (section 2.5).

**Readback (review S-MAJ-7).** Two 4-bit binary-weighted resistor ladders driven by LVC buffers present the
gated states to analog pins:

- `PACK_STAT_A` (pin 22): Q_A gate, Q_B gate, LATCH Q, VOK.
- `PACK_STAT_B` (pin 21): D-BT-EN, D-BC-FC, D-BC-RG and D-BT-SQ as seen by the board.

The step between codes is 3.3 V / 15 = 0.22 V, ratiometric to the 3V3 ADC reference. The ladder accuracy
with 1 % resistors is TODO(calibrate) on bench gate B2.

### 2.7 V-MOT over VBUS comparators (VMOT_OK1, VMOT_OK2)

The REGEN gate needs a physical V-MOT > VBUS condition. This is the H1 comparator of the prior study
(V-MOT > 1.067 x VBUS with 0.1 % dividers; facts_prior section 10 item 12). IC2 now uses **two** TLV1805
comparators with **independent** 0.1 % divider pairs on V-MOT (flying lead to J-M pin 1 or the V-MOT pour)
and VBUS, ANDed (review F-M1 / S-MAJ-6: a single stuck-high comparator can no longer enable REGEN at bus
level). The comparators run from the 5V rail (J2 pins 01/02), because the TLV1805 is specified from 3.3 V
upwards (SNOSD50A 6.3); their 5 V outputs drive LVC inputs within the 5.5 V tolerance (SCES217AA p.1).

- **Ratio.** 1/8 gives 2.68 V at the 21.47 V measured V-MOT peak (facts_prior section 6) and 2.19 V at the
  17.5 V `LIMIT_V_BUS_MAX`.
- **Hysteresis (review E-M4 / S-MAJ-2).** Assert at V-MOT > 1.067 x VBUS (17.07 V at 16.0 V); release at
  V-MOT < 1.020 x VBUS (16.32 V). The release stays above VBUS, so D-MT-EN cannot be forward-biased while
  REGEN is effective. The release margin of 0.32 V at a V-MOT fall rate of about 0.3 V/ms (section 4.9)
  leaves about 1 ms for comparator, gate and RT1987 turn-off (RT1987 turn-off time TODO(verify: DS-00)).
- This element is shared with every concept that keeps REGEN.

`docs/fw37_planning_2026-11-04.md` section 3.3 keeps MOT_PWR closed during regen and relies on the
reverse-biased D-MT-EN while V_rgn > V_bus. This dossier follows that document; VMOT_OK is the hardware form
of its layer 1.

### 2.8 Watchdogs

The RTWDOG/WDOG1 of the i.MX RT1062 remains mandatory (finding X9; operator ruling 5). Its WDOG1_B output
(pin 20, reserved by the prior study) is routed to nPRE through an open-drain stage. An external window
watchdog TPS3430 adds an independent path to LATCH:

- Configuration: CWD = NC, SET0 = 0, SET1 = 1. Then t_WDL = 1.48-2.22 ms and t_WDU = 23.4-31.6 ms
  (SBVS366A section 6.6, t_WDL and t_WDU rows). The upper bound lies inside the 50 ms target of the prior
  study (facts_prior section 7) against the 100-140 ms purge.
- Firmware kicks WDI on pin 34 at a 5-10 ms interval from a timer, and only after `detectFaults()` completes.
  A kick faster than t_WDL max = 2.22 ms is itself a fault (SBVS366A section 6.6), so the 1.13 ms main loop
  must not kick every iteration.
- At power-up WDI is ignored until t_RST = 170-230 ms (C_RST open) expires; the first falling edge must then
  arrive before t_WDU max (SBVS366A section 8, power-up paragraph). The 2 s SD initialisation (facts_firmware
  section 8) therefore asserts WDO and sets LATCH at every boot. This is the intended default: firmware
  clears LATCH only after the kick timer runs.
- WDO is open-drain and active-low (SBVS366A pin functions, WDO), so it joins nPRE directly.

### 2.9 Mandatory VCHG-IN eFuse

A TPS2663 eFuse in VCHG-IN bounds the charger input current independently of every command (SLVSE94G p.1:
4.5-60 V operating, 67 V absolute maximum, 0.6-6 A adjustable current limit +/-7 %, latch-off or auto-retry
selectable, analog IMON). It is now **mandatory** (reviews F-M1, E-M4, S-MAJ-6).

- Fitting it needs Ag105 pin 10 (VIN+) cut free of the VCHG-IN copper and flying-leaded in the same way as
  pins 14/15.
- Current limit: 1.30 A nominal, 1.39 A at +7 %. This is above the FC-window demand of about 1.0 A
  (section 4.10) and the regen demand at 18.9 W / 17 V = 1.11 A, and below the 1.4 A `OC_FC` single-sample
  limit (facts_firmware section 4).
- Fault mode: latch-off. If the TPS2663 fault output is open-drain, it joins nPRE (TODO(verify: SLVSE94G
  pin functions)).

### 2.10 Hardware detectors that set LATCH

Each detector drives nPRE through an open-drain stage. Table 5a lists them. LATCH removes D-BC-FC, D-BC-RG
and D-BT-SQ and asserts FORCED BYPASS (Table 5).

Table 5a. LATCH set sources.

| ID | Detector | Condition | Location | Covers |
|---|---|---|---|---|
| D1 | U_OC | Pack charge current > 2.2 A (channel #2, 1 ms RC) | Splitter | HR4 ceiling; F1, F17 |
| D2 | Supervisor | LDO or shunt reference under-voltage | Splitter | F8, F8b |
| D3 | TPS3430 WDO | No valid kick within 23.4-31.6 ms | Interposer | F14 |
| D4 | WDOG1_B | MCU watchdog timeout | Teensy pin 20 | F14 |
| D5 | BT_LOOP | BT boost output current > 0.5 A (BT_CURRENT net, INA253 0.1 V/A, 50 mV) while D-BC-FC is effective, after a 10 ms arming delay | Interposer, flying lead to the pin-41 net | F9, gate stuck HIGH on D-BT-EN |
| D6 | CHG_UNCMD | VCHG-IN > 12 V (1.35 V on the pin-38 divider, 10/88.7) while CMDD is LOW for > 200 ms | Interposer, tap on the pin-38 net | F10, F13 |
| D7 (opt.) | BQ29200 OUT | Pack OVP (8.70 V, 2.0-4.0 s; facts_prior section 5) through an NFET | Fly-wire to QFN pin 8 | Pack OV |

D5 relies on the INA253 floor of up to 0.1 A (facts_prior section 10 item 11); the 0.5 A threshold leaves
0.4 A of margin. In an FC window BT_BUS is open, so a legitimate BT boost output current is zero. D6 must
wait for C-D8 and C-D10 (20 uF) to decay below 12 V after a window; with the Ag105 idle input current up to
18 mA (DS p.20 row 4) the decay from 21 V takes at least 10 ms. The 200 ms delay and both thresholds are
TODO(calibrate) (bench gate B2).

## 3. Teensy pins and control sequence

### 3.1 Pin assignment

Table 6 assigns spare pins from the authoritative CSV free list (10, 16, 17, 20-23, 33-35;
facts_board section 7.2). The CSV must be amended first; this study does not edit it.

Table 6. New Teensy pins.

| Pin | Proposed code name | Dir | Function | Default without Teensy drive |
|---|---|---|---|---|
| 16 (A2) | `PACK_CURRENT` | AIN | V_AMP1 (discharge lowers the voltage), 0.1 V/A | n/a |
| 17 (A3) | `PACK_CURRENT_OC` | AIN | V_AMP2, independent channel | n/a |
| 23 (A9) | `PACK_IREF` | AIN | Buffered V_IREF, for the differential current read | n/a |
| 22 (A8) | `PACK_STAT_A` | AIN | Ladder: Q_A gate, Q_B gate, LATCH Q, VOK | n/a |
| 21 (A7) | `PACK_STAT_B` | AIN | Ladder: the four gated board ENs | n/a |
| 33 | `PACK_BOND_FORCE` | OUT | HIGH = inhibit both charger inputs and the charger output; FORCED BYPASS | LOW (10 kOhm pull-down) |
| 10 | `PACK_LATCH_RESET` | OUT | Rising edge clears LATCH unless a set source is active | LOW (10 kOhm pull-down) |
| 34 | `WDT_KICK` | OUT | TPS3430 WDI | n/a |
| 20 (A6) | WDOG1_B | OUT (peripheral) | MCU watchdog output to nPRE | Reserved by the prior study |

Pin 35 remains spare. The total of nine pins plus pin 20 consumes every CSV spare except pin 35.

### 3.2 Control sequence by operating mode

Table 7 gives the switch and steering state in each mode. Pin numbers are Teensy pins; the "eff." columns
are the gated board EN levels of Table 5.

Table 7. Control sequence.

| Mode | BOND_FORCE | Steering | FC_CHG eff. | REGEN eff. | BT_BUS eff. | D-BT-SQ eff. | Notes |
|---|---|---|---|---|---|---|---|
| Boot (Teensy in reset / before `setup()`) | LOW (pull-down) | FORCED BYPASS | LOW | LOW | LOW | LOW | LATCH SET by the nPRE power-up RC and by the TPS3430 |
| `setup()` | Drive HIGH first | FORCED BYPASS | LOW | LOW | LOW | LOW | Start the kick timer; clear LATCH after the SD and Ethernet init; read `PACK_STAT_A` LATCH bit LOW |
| Idle (State 1) | HIGH | FORCED BYPASS | LOW | LOW | per firmware | LOW | No charger path can open |
| Run, no charge (State 2) | LOW | FORCED BYPASS | LOW | LOW | per firmware | LOW | Pack return through Q_B at any current; no GAP |
| Regen window (State 2) | LOW | Steer | LOW | HIGH only while VOK | HIGH | HIGH while pin 30 (+20 ms) | Charger cold-starts per event (section 4.6) |
| FC-charge window (State 2) | LOW | Steer (SENSE while net charge) | HIGH | LOW (`assertFcChargeEnable`) | LOW (forced by FCD) | HIGH | Bus FC-only during the window and 20 ms after |
| H-20 purge | LOW | FORCED BYPASS | LOW (window closed >= 28 ms before, ruling 6) | - | Restored 20 ms after pin 31 LOW | LOW | Pack stays on VBT |
| Finish (State 3) | LOW then HIGH on entry to Idle | FORCED BYPASS | LOW | LOW | per firmware | LOW | |
| State 99 phase 0 drain | LOW (HIGH on a steering-class fault) | Steer for 10 ms | HIGH ~10 ms (refused if BF) | LOW | LOW | HIGH ~10 ms | The drain must tolerate a hardware refusal |
| State 99 phase 1 drain | as phase 0 | as phase 0 | LOW | HIGH only if VOK | LOW | as REGEN | VOK refuses the V-MOT drain at bus level |
| State 99 phase 2 latched | HIGH | FORCED BYPASS | LOW | LOW | LOW | LOW | |
| Teensy hang (any state) | Last level | Last level until LATCH | LOW after D3/D4 | LOW | Last level | LOW after LATCH | LATCH asserts FORCED BYPASS |
| Teensy reset (warm or RTWDOG) | LOW (pull-down) | FORCED BYPASS | LOW (pull-downs) | LOW | LOW | LOW | LATCH keeps its state; D4 sets it on an RTWDOG event |

The ordering rule into a charging state is: (1) firmware drives FC_CHARGE or REGEN only after BOND_FORCE is
LOW and the LATCH bit reads LOW; (2) the hardware gates hold the loop break regardless of firmware order.
The ordering rule out of a charging state is enforced in hardware by the 20 ms CMDD and FCD delays.

## 4. Quantitative checks

### 4.1 Conduction loss at peak BT current

The BT boost peak switch current limit is 12 / 15 / 17.1 A (min/typ/max; SLVSFP3C section 7.5). This
dossier uses 17.1 A as an upper bound on the average pack current in BYPASS; the true average input current
is lower (UNCONFIRMED; X8 vehicle I_batt peak).

- Q_B: 17.1^2 x 1.45 mOhm = 0.424 W at 25 C. The R_DS(on) rise at elevated T_J is read from the SLPS492B
  R_DS(on) versus temperature figure (not extracted; TODO(verify: SLPS492B section 5.3)); a factor of 1.5
  gives 0.64 W. With R_thJA 50 C/W maximum (SLPS492B 5.2) the junction rise is 32 C.
- R_SH: 0.585 W (section 2.2).
- Added series drop at 17.1 A: 17.1 x (1.45 + 2.0) mOhm = 59 mV, plus the harness contacts. With a 20 mOhm
  maximum contact resistance (TB005-762 p.1) a single contact costs up to 0.34 V at 17.1 A. The two
  parallel GND_RET leads halve this on the return; the PACK+ and VBT joints must be soldered or use
  high-current connectors with a datasheet contact resistance <= 1 mOhm (TODO(verify: connector
  datasheet)).
- Q_A: carries at most 1.7 A in charge (Ag105 OC trip at the 1.5 A setting, DS p.18) and at most 0.6 A of
  discharge. 1.7^2 x 1.45 mOhm = 4.2 mW.

### 4.2 Safe operating area and switching

Neither FET switches a significant voltage. Every steering transition takes place at |I_dis| <= 1.0 A,
where the voltage across the opening path is at most the Q_B body-diode drop. With V_SD below 1 V
(SLPS492B 5.1, at 35 A; lower at 1 A), the switched power is below 1 W for microseconds. The PERMIT
transitions (FORCED BYPASS to steering and back) switch the same paths at the window current. SOA is
therefore not a constraint in normal service.

The binding thermal cases are the GAP state and the Q_B channel failure (section 5, F2):

- GAP state: at most 1.0 A x 1 V = 1.0 W in the Q_B body diode, 50 C rise at 50 C/W. GAP now exists only
  inside charge windows. Firmware faults a GAP that persists for more than 2 s (section 8.2).
- Q_B channel failed OFF at 17.1 A: 17.1 W in the body diode. This exceeds the steady rating of the
  package; the time to damage is not given by SLPS492B (TODO(verify: SLPS492B transient thermal impedance
  figure)). Firmware detection is required (`FAULT_PACK_STEER`).

### 4.3 Inrush

IC2 does not close a switch onto a charged node at a different voltage. A steering transition moves PCB
GND relative to PACK_N by at most the body-diode drop (below 1 V). The VBT capacitance recharges by that
amount through the pack. The pack plug-in inrush flows through the Q_B body diode, or the channel once U_B
wakes, and is the same event as today's plug-in. The RT1987 EN gating of Table 5 only removes ON conditions
or delays an OFF; it never adds an ON condition. The existing inrush rules for MOT_PWR, REGEN and FC_CHARGE
(facts_prior section 10 item 4) are unchanged. D-BT-SQ now closes at every window start onto VCHG; it is an
ideal diode that conducts only VCHG to VBT, so its closure causes no inrush from the pack.

### 4.4 Threshold tolerance and the no-overlap proof

The steering is safe only if Q_B is OFF for every charge current and Q_A and Q_B are never ON together.
The error budget, referred to pack current at 0.1 V/A, is:

- INA181 offset: below 500 uV x 50 = 25 mV = 0.25 A (SBOS793H section 6.5, V_OS row at V_SENSE = 0 mV);
- TLV1805 offset: 4.5 mV = 0.045 A at 25 C, 6.5 mV = 0.065 A over temperature (SNOSD50A 6.5);
- reference divider with 0.1 % resistors: about 2 mV = 0.02 A (calculated);
- R_SH tolerance and gain error: TODO(verify: R_SH and SBOS793H gain-error rows).

**Q_B OFF before charge.** The amplifier offset is common to U_A and U_B and shifts all thresholds
together. The nominal Q_B release is I_dis = 0.70 A; the worst-case shift is 0.25 + 0.065 + 0.02 = 0.335 A.
Q_B therefore releases at I_dis >= 0.365 A, that is before the pack current reaches zero. A gain or shunt
error scales this but cannot change its sign. Section 1.3 then guarantees that every charge current crosses
the sense.

**No overlap.** Q_A turns ON only below 0.30 A and Q_B is ON only above 0.70 A (falling). The relative error
between U_A and U_B excludes the common amplifier offset: 2 x 0.065 + 0.02 = 0.15 A, which is less than the
0.40 A separation. U_A and U_B now use different V- rails (PACK_N and GND_RET); the comparison is
differential, so this does not change the budget. In addition, turn-on takes about 14 us and turn-off about
0.6 us (section 2.4). In FORCED BYPASS, N1 clamps Q_A OFF independently of U_A.

**Fast reversal.** If the pack current falls from discharge into charge faster than the 20 us filter, Q_B can
carry charge-direction current for at most the filter delay plus 0.6 us. The charge current is sourced by
the Ag105, whose output slew is slow (0.64 V/s Bring-Up and 10.6 A/s ramp were measured in ML0227;
facts_prior section 4); the charge carried in that interval is negligible (UNCONFIRMED; BENCH gate B3).

**Reverse step from SENSE (review E-m6).** A discharge step while in SENSE first flows through the sense in
reverse, until Q_A turns off and Q_B conducts. Its peak is up to about 0.6-0.7 V / (R_s + R_QA + R_wire),
tens of amperes for R_s near 20 mOhm, for 20-40 us. At window end the FCD and CMDD delays prevent this step
(BT_BUS cannot conduct before FORCED BYPASS). Inside a regen window a re-acceleration can still produce it.
The sense pulse rating is TODO(verify: Silvertel); the F_VBN fuse I^2t must exceed the pulse (section 7.2).

**Chatter.** The steering has 0.30 A of hysteresis per comparator. The 500 kHz boost switching ripple
(f_SW 440 / 500 / 600 kHz, SLVSFP3C section 7.5) is attenuated by the VBT capacitors and by the 20 us
filter (corner 8 kHz). The pack ripple amplitude at R_SH is unknown, and the 2-6 Hz once-per-rev current
ripple (fw37 planning section 6) can cross the hysteresis band in a regen window (bench gate B2). Chatter is
now confined to charge windows.

### 4.5 Teensy supply continuity, measurement offsets and the respin objections

Pack positive is never switched, so the LM1084 input is VBT in every mode.

- **Outside charge windows (FORCED BYPASS).** VBT - PCB GND = V_pack minus I_dis x (R_SH + R_QB + lead
  resistance), below 0.2 V at 17.1 A with two return leads. The LM1084-5.0 dropout is 1.5 V maximum over the
  full load range (SNVS037H p.1 and section 5.5; the 1.3 V entry in that table is the typical column, review
  E-m3), and regulation is specified from V_IN = 6.5 V. At a 7.4 V pack the margin is about 0.7 V at full
  current and larger at the Teensy load.
- **Inside charge windows, GAP.** VBT - PCB GND = V_pack - V_SD. At a 7.4 V pack and 0.6-1.0 V body-diode
  drop, VBT - GND is 6.4-6.8 V, at or 0.1 V below the specified regulation range. GAP is bounded by the window
  and faulted after 2 s (section 8.2).
- **Cold start.** Before the comparators wake, the logic load returns through the Q_B body diode or the Q_A
  body diode and the sense. The comparators need only 3.3 V (SNOSD50A 6.3).

**V_batt and UV_BATT.** In FORCED BYPASS, V_batt reads low by the lead and FET drop only (< 0.2 V at 17.1 A).
In a regen window, GAP can read V_batt low by 0.6-1.0 V for the window length (0.3-0.6 s per burst,
facts_prior section 6). `UV_BATT` is armed by BT_BUS and BT_REG HIGH (ino:7272-7310); firmware must hold the
UV_BATT dwell while `PACK_STAT_A` shows GAP (both gates LOW), as fw v30 already holds the UV_FC dwell on a
share-loop cut (CLAUDE.md fw v30 addendum). In FC windows BT_BUS is LOW, so UV_BATT is disarmed.

**BQ29200.** In GAP, PCB GND lies V_SD above PACK_N, so the bottom-cell reading VC1 - GND is low by 0.6-1.0 V,
far above the 17-45 mV mismatch-detection threshold (SLUSA52C 7.5); the balancer bleeds the top cell at up to
15 mA (SLUSA52C 8.1.2) during GAP dwell. Confining GAP to windows bounds this to window time. The VC1 versus
GND absolute maximum in this condition is TODO(verify: SLUSA52C 6.1).

Table 8 engages the five objections of the re-spin note to "switch both legs" (review S-minor 3 corrected
the revision-0 table).

Table 8. Re-spin option 2 objections versus IC2.

| Objection | IC2 status |
|---|---|
| 1. The bus needs another source during charge windows; the FC purges to about 1 V | Equal to today in FC windows: BT_BUS is LOW today and stays forced LOW. Not applicable to regen windows: BT stays on the bus. |
| 2. The Teensy browns out | Retired: pack positive is never switched. |
| 3. No pack buffering | Retired outside FC windows. |
| 4. Two switch transitions plus a charger bring-up per regen event | Not retired. The steering transitions are cheap, but the charger cold start and Bring-Up per regen event and per purge cycle remain the expensive half (sections 4.6, 4.9, 4.10). |
| 5. BQ29200, V_batt and BT sense references move | Partly retired: tens to hundreds of millivolts in FORCED BYPASS; 0.6-1.0 V in GAP inside charge windows (this section, Table 9). |

### 4.6 Timing against the regen burst and the Ag105 Bring-Up

The steering is not on the regen critical path. The chain is: INA181 bandwidth 210 kHz (SBOS793H 6.5),
filter 20 us, comparator 250 ns (SNOSD50A), gate 14 us on / 0.6 us off. The total is below 40 us, against a
19-47 ms V-MOT pulse and a 0.3-0.6 s burst (facts_prior section 6).

The charger is on the critical path, as in every cold-start concept (finding X6). The chain per regen event
is:

1. VMOT_OK asserts when V-MOT exceeds 1.067 x VBUS (about 17 V at a 16 V bus). Firmware layer 1 runs at
   1 kHz; the RT1987 D-BC-RG turn-on delay t_D_ON is 8 ms typical (DS-00 section 17.1).
2. The Ag105 starts: 65-170 ms cold start to first current (facts_prior section 6, measured on this rig),
   with no datasheet start-up time (facts_ag105 section 6).
3. VCHG decays below the RT1987 UVLO in 0.17-0.66 s between windows (facts_prior section 10 item 1), so at
   most events the Ag105 meets a near-0 V node and runs Bring-Up (DS p.6). The only measured Bring-Up slope
   is 0.64 V/s (ML0227, with the sense shorted); from 2 V to a 7.67 V pack that is 8.9 s (calculated).
4. With the sense restored, the Bring-Up exit condition (10 % current through the sense, DS p.6) becomes
   observable. Whether the ramp is faster with a working sense is UNCONFIRMED (BENCH gate B4).

Consequence: with the measured numbers, the first pulse of every regen event is missed, and the first event
after more than about 0.2-0.7 s of cruise is missed entirely. **HR1 FAILS by calculation** (section 6). Ruling
1 states that a charger that "catches only the tail of regen bursts, fails" (facts_prior section 3). IC2 in
this form therefore does not meet the study goal. Section 4.11 records the only HR1 path that remains.

### 4.7 The circulating loop with the sense restored (X3)

IC2 restores regulation of the pack current, not of the Ag105 output current. If the charger is powered
from the bus while BT_BUS conducts, the BT boost input draws from VBT a current that bypasses the sense
(facts_ag105 section 1.4). Let s be the BT share of the bus load, eta the Ag105 efficiency and eta_b the
BT boost efficiency. The BT boost output power P_b satisfies
P_b = s x (P_load + P_pack/eta + P_b/(eta x eta_b)), hence
P_b = s x (P_load + P_pack/eta) / (1 - s/(eta x eta_b)).
With eta = 0.88 (DS p.20, 12 V 3S only) and eta_b = 0.9 (UNCONFIRMED placeholder), eta x eta_b = 0.79. For
s >= 0.79 the denominator is not positive and the circulating power grows until a current limit acts; the
share selector can command s = 1.0 (battery-only start at every Idle to Run, facts_firmware section 5).

Therefore the steered return alone does **not** satisfy HR3. The loop is broken by four hardware layers:

1. D-BT-EN cannot conduct while FC_CHARGE is commanded or for 20 ms after (Table 5).
2. D-BC-RG cannot conduct unless both VMOT_OK comparators report V-MOT above the bus (D-MT-EN reverse-biased,
   so the bus cannot feed V-MOT).
3. D-BT-SQ cannot conduct unless a charger input is commanded (Table 5), computed in a separate gate package.
4. The detectors D5 (BT boost output current in an FC window) and D6 (uncommanded VCHG-IN) set LATCH, and the
   TPS2663 bounds the charger input current at 1.39 A in the meantime.

In a regen window with BT_BUS HIGH, the Ag105 output partly feeds the BT boost. Its input power is then the
regen power (18.9 W peak for a 3 to 1 m/s brake, facts_prior section 6) and is also bounded by the eFuse at
1.39 A x V-MOT. That bounds the Ag105 output at about 18.9 x 0.88 / 7.4 = 2.2 A (calculated).

### 4.8 Reference shifts: V_batt, INA253, BQ29200

The steering moves PCB GND relative to PACK_N by the drop of the active leg. Table 9 lists the effects. R_s
is the unknown Ag105 sense resistance (gate X8).

Table 9. Reference shifts.

| Measurement | Today | IC2 FORCED BYPASS / BYPASS (discharge 15 A) | IC2 GAP (window only) | IC2 SENSE (charge 1.5 A) |
|---|---|---|---|---|
| V_batt (VBT - GND, pin 25) | V_pack minus J-BT harness drop | Low by 15 x (R_QB + R_SH) = 52 mV plus the return leads | Low by 0.6-1.0 V | Reads V_CV - 0.035 + 1.5 x R_s |
| OV_BATT (8.5 V, single sample, all builds) | - | No effect | No effect | False latch at CV entry if 8.365 + 1.5 x R_s + ripple > 8.5. With +50 mV ripple (DS p.20 row 9, 100 mVp-p typ): **R_s > 57 mOhm** |
| INA253 SNS-BT / SNS-FC | GND-referenced | Unchanged (shunts on boost outputs) | Unchanged | Unchanged |
| BQ29200 bottom cell (VC1 - GND) | Balance negative at GND | Low by the bypass and lead drop | Low by 0.6-1.0 V; top cell bleeds at <= 15 mA | High by 1.5 x (R_s + R_QA + R_wire) |
| BQ29200 OVP 4.35 V (SLUSA52C) | OUT unconnected | Late OVP (irrelevant) | Late OVP | Early OVP; false trip at a 4.20 V cell needs > 0.15 V, R_s > about 90 mOhm |
| Ag105 reg 0x05 | Reads VCHG to GND | Unpowered | Unpowered or Bring-Up | Reads its own terminals |

The V_batt and OV_BATT effects remain a hard bench gate: **R_s must be measured**. The lower setting (1.5 A
instead of 2.5 A) raises the tolerable R_s from about 34 mOhm (2.5 A with +50 mV ripple: 0.085 V / 2.5 A; review
E-m5 estimated about 40 mOhm) to about 57 mOhm (0.085 V / 1.5 A). In addition, firmware filters V_batt over at least 10 ms for OV_BATT while SENSE is reported with a
charger powered, so the single-sample check does not trip on ripple (operator ruling, section 8.2).

### 4.9 Regen-window input regulation and the VMOT_OK limit cycle (review E-M4, S-MAJ-2)

The regen branch drives MPPT_DISABLE LOW (facts_firmware section 3.2 item 3), and the fw v24 policy writes
reg 0x02 to 12.32-13.38 V (CLAUDE.md section 3). Both reviewers showed that the charger then pulls V-MOT
down through the VMOT_OK threshold:

- At the revision-0 2.5 A setting the Ag105 demands 2.5 x 8.4 / 0.88 = 23.9 W, above the 18.9 W regen peak.
  At the new 1.5 A setting it demands 1.5 x 8.4 / 0.88 = 14.3 W, below the peak but above the burst tail.
- A net drain of about 5 W at 17 V (0.3 A) from 0.97 mF falls at about 0.3 V/ms, so V-MOT reaches the VMOT_OK
  release within milliseconds of the tail (calculated; V-MOT capacitance range M-R1).
- After release, C-D8 + C-D10 = 20 uF at about 1 A fall from 17 V to the 11 V UVLO (DS p.19) in about
  0.12 ms (calculated). Every re-entry costs t_D_ON = 8 ms plus a 65-170 ms cold start, and clears
  `ag105Configured` (ino:16138-16152).

The hysteresis of section 2.7 prevents fast chatter but not the cycle. The cycle ends only if the Ag105 itself
stops drawing above the release voltage. Two options exist, both needing an operator ruling:

- **Option R-a.** Release MPPT (MPPT_DISABLE HIGH) in regen windows with reg 0x02 at count 86
  (11 + 86 x 0.088 = 18.57 V, DS p.13 Table 7). Keep MPPT_DISABLE LOW in FC windows. This works with one
  EPROM value only if MPPTD LOW bypasses the input threshold (facts_ag105 section 7: TODO(verify:
  Silvertel)), because the FC window input is the 16 V bus. It inverts the CLAUDE.md section 3 regen
  strategy.
- **Option R-b.** A Teensy-switched MPPTS resistor with reg 0x02 >= 251 (DS p.13 Table 7), so that the
  threshold changes without an EPROM write. This needs a further pin and an analog switch.

If neither works, regen windows harvest only until the first VMOT_OK release. Bench gate B5a decides this.

### 4.10 HR2: FC-window budget and per-purge timing (review S-MAJ-5)

**Budget.** The FC budget is the 1.247 A P_MAX bus equivalent, the 1.25 A governor and the 1.4 A OC_FC
single-sample latch, minus aux 0.10-0.15 A (facts_prior section 7). In an FC window the Ag105 also supplies the
Teensy logic load I_L on VBT, which returns outside the sense (facts_ag105 section 1.4; I_L is BENCH, about
0.2 A assumed). Table 10a gives the bus current.

Table 10a. FC-window bus current (calculated, standstill, eta = 0.88 from DS p.20 at 12 V 3S only).

| Setting (reg 0x00) | Output (pack + I_L) | Bus current at 16 V, CC at 8.0 V | At CV 8.4 V | Plus aux 0.15 A, CV | Margin to 1.247 A |
|---|---|---|---|---|---|
| 0x01, 2.5 A | 2.7 A | 1.53 A | 1.61 A | 1.76 A | -0.51 A (infeasible) |
| 0x04, 1.5 A | 1.7 A | 0.97 A | 1.01 A | 1.16 A | +0.09 A |
| 0x05, 1.25 A | 1.45 A | 0.82 A | 0.87 A | 1.02 A | +0.23 A |

The 1.5 A setting fits at eta = 0.88 with no traction headroom; at eta = 0.80 it exceeds P_MAX by 0.03 A
(calculated). IC2 therefore specifies 0x04 provisionally and 0x05 if the measured eta at 16 V input and 2S
output is below 0.85 (bench gate B6). One setting serves both FC and regen windows, so no per-window EPROM
write is needed. U_OC (2.2 A) and the eFuse (1.30 A) are sized to this setting.

**Per-purge timing.** Windows run only between purges (ruling 6; period 10.34 s, duration 100-140 ms,
facts_prior section 7). Table 10b gives the costs of one window.

Table 10b. Re-entry costs per window.

| Item | Time | Source |
|---|---|---|
| `FC_CHG_COOLDOWN_MS` after the previous window | 2000 ms | ino:2634 |
| RT1987 t_D_ON | 8 ms | DS-00 17.1 |
| Ag105 cold start to first current | 65-170 ms | facts_prior section 6 |
| VCHG decay between windows | Below RT1987 UVLO in 0.17-0.66 s | facts_prior section 10 item 1 |
| Bring-Up from about 2 V to the pack | 8.9 s at the measured 0.64 V/s | ML0227, sense shorted |
| CMDD/FCD hardware tail before BT_BUS returns | 20 ms | Table 5 |
| `AG105_SETTLE_MS` and MPPT holdoff | 500 ms and 1000 ms | ino:2484, ino:2655 (firmware gates; they do not stop the module from charging) |

With the measured Bring-Up slope, current starts about 9.1 s after the window opens. The window must close
before the next purge, about 10.0 s after the previous one, and the 2 s cooldown then skips the next
inter-purge interval. The delivered charge is therefore about 0-1 C per two purge periods, an average below
0.05 A (calculated). With a Bring-Up of 1 s or less (unknown, B4) and a cooldown reduced to the purge gap,
the average rises to about 1.2 A (calculated). **HR2 therefore hinges on bench gate B4.** A VCHG keep-alive
would remove the Bring-Up from 0 V but is a last resort (ruling 9).

### 4.11 Warm-regen variant for an operator ruling (review S-MAJ-3)

Revision 0 excluded a warm charger by citing planning ruling R3. That citation is superseded: evaluation
ruling 3 (2026-11-05) replaced R3 with "no adverse behaviour" and permits an always-powered charger if the
charger has a reliable, Teensy-commanded, fail-safe way to prevent charging while powered (facts_prior
section 3). Revision 1 of IC2 has such a mechanism for faults: LATCH opens D-BT-SQ, which disconnects the
charger output from the pack while its input stays powered. It does not have one for normal operation,
because an opened D-BT-SQ forces the Ag105 back into Bring-Up and the charger is then no longer warm.

A warm variant **IC2-W** would hold REGEN closed through Run at bus level, keep D-BT-SQ ON, and rely on
reg 0x02 above the bus maximum to stop charging until V-MOT rises (MPPT released). Its HR3 backstop would be
a further detector: TPS2663 IMON above about 0.2 A while VOK is false sets LATCH (bus feeding the charger).
PERMIT would follow VOK OR FC_CHARGE, so FORCED BYPASS still holds in normal Run. Open items: whether the
Ag105 responds within the tau_warm <= 4 ms budget (facts_prior section 6) with MPPT enabled; whether the
threshold stops a charge in progress (facts_ag105 section 7). IC2-W HR1 status: **UNDETERMINED**. IC2-W is not
part of the IC2 baseline; it needs an operator ruling under evaluation ruling 3.

## 5. Single-fault table

Table 10 lists single faults, their effect, the detecting layer and the residual. "Charger powered" means
any of the gated input enables of Table 5 is HIGH.

Table 10. Single faults (revision 1).

| ID | Fault | Effect | Detection / limiting layer | Residual |
|---|---|---|---|---|
| F1 | Q_B drain-source short | Sense bypassed whenever the charger is powered | U_OC (D1) at 2.2 A pack charge; firmware cross-check PACK_CURRENT vs reg 0x06; boot check | Pack charge bounded at 2.2 A in hardware. Charging disabled until repair. |
| F2 | Q_B channel open | Discharge through the body diode, up to 17.1 W | `PACK_STAT_A` Q_B LOW while discharge > 1.5 A for 5 ms: `FAULT_PACK_STEER`; firmware drops BT_BUS and BT_REG | Thermal damage if firmware fails; time to damage TODO(verify: SLPS492B Zth). V_GS(Q_A) = 0 V now holds in this case (U_A on PACK_N). |
| F3 | Q_A drain-source short | Sense always connected; in BYPASS about 1.1 A of 17.1 A through the sense at R_s = 20 mOhm | Not detectable directly | Within the 4 A I_DIS rating (DS p.20 row 6) and below F_VBN. Latent. |
| F4 | Q_A channel open | Charge through the Q_A body diode: up to 0.7 V drop, 1.2 W at 1.7 A | `PACK_STAT_A` Q_A LOW while charge > 0.3 A | Performance fault. |
| F5 | INA181 #1 output stuck low | Reads as large discharge: BYPASS in windows | U_OC and U_AV on channel #2; firmware pins 16 vs 17 (> 0.5 A disagreement) | Charging blocked; discharge normal. |
| F6 | INA181 #1 output stuck high (or U_A high with U_B low) | Steering wants SENSE at any discharge in a window | U_AV vetoes Q_A at > 0.6 A on channel #2: GAP, not SENSE. F_VBN (3-4 A fast) opens if the veto also fails. Firmware pins 16 vs 17 | Discharge through the Q_B body diode (F2 class) until firmware acts. Revision 0 claimed body-diode sharing above 4 A; that was wrong (review F-M3). |
| F7 | INA181 #2 or U_OC failed | No D1 latch, no veto | Ag105 own trip (set + 200 mA) with the sense restored; eFuse input bound; firmware G1/G2 | Latent; boot self-test (B2). |
| F8 | Local LDO failure | Amplifiers unpowered, V_AMP near 0 V | Supervisor (D2): LATCH set and FORCED BYPASS | Charging blocked. Revision 0 analysed this wrongly (shared supply, review E-M3). |
| F8b | Shunt reference failure | Thresholds collapse | Supervisor (D2); U_B IN+ held positive by the 1 MOhm bias, so Q_B ON | Charging blocked. |
| F9 | D-BT-EN RT1987 short, or its gate output stuck HIGH | Loop of section 4.7 in an FC window | D5 (BT boost output > 0.5 A while D-BC-FC effective) sets LATCH; eFuse bounds the charger input at 1.39 A; firmware G1/G2 | Bounded pulse until D5 trips (comparator and RT1987 turn-off, TODO(verify: DS-00 t_OFF)). |
| F10 | D-BC-FC or D-BC-RG short | Charger powered without command | D-BT-SQ is LOW unless a charger input is commanded, so the output cannot reach VBT; D6 sets LATCH after 200 ms; eFuse bound | Charger runs into an open VCHG node. During a commanded regen window with V-MOT at bus level, a bounded pulse until firmware layer 1 drops pin 30 (about 1 ms) plus 20 ms CMDD. |
| F11 | D-BT-SQ short | Pack visible on VCHG; Ag105 back-fed through its output when unpowered (standby 120-420 uA, DS p.20 row 7) | None needed for safety | Same as today. Together with F10 it is a double fault. |
| F12 | One VMOT_OK comparator stuck high | None: the AND with the second comparator holds REGEN off at bus level | Firmware compares `PACK_STAT_A` VOK with V_rgn - V_bus | Latent; boot check with V-MOT at bus. |
| F13 | LVC gate output stuck high on D-BC-FC or D-BC-RG | As F10 | As F10 (D-BT-SQ gate in a separate package) | As F10. |
| F14 | Teensy hang with a charger path open | Charging continues uncommanded | D3 within 23.4-31.6 ms and D4 set LATCH; RTWDOG reset; pull-downs | Depends on bench gate T-W-01. |
| F15 | Teensy reset or brownout | GPIOs high-Z, keeper may hold the last level | 10 kOhm interposer pull-downs; I_off; FORCED BYPASS | None at the logic level; pad behaviour across reset is B2. |
| F16 | One GND_RET lead or terminal open | The other lead (independent terminal, J-BT pin 2 or J-BL pin 3) carries all return current | Firmware: differential V_IREF read unaffected; V_batt shifts by the lead drop | Each lead sized for the full current. Revision 0 had both leads under one screw (review F-M6, S-minor 2). |
| F17 | Balance-lead negative re-bonded at J-BL pin 3 | Sense paralleled again (finding X1) | U_OC (D1); firmware cross-check | Keyed, mechanically distinct connectors required. |
| F18 | Pack protection opens in the pack | PACK_N floats up towards VBT | Both FETs see up to about 8.5 V; within the 30 V V_DS rating | None. |
| F19 | Interposer contact loss (input) | Gate input at its pull-down: that output OFF | Readback ladders | Safe (OFF). Mechanical retention BENCH. |
| F20 | Interposer contact loss (output to receptacle) | Board EN at its 10 kOhm pull-down: switch OFF | Readback ladders | Safe (OFF). |
| F21 | Interposer 3V3 or GND contact loss | LVC outputs high-Z (I_off): all gated switches OFF; nPRE pull-up lost | Ladders read invalid; firmware inhibits | Safe (OFF); the LATCH state is lost, but every output it gates is already OFF. |
| F22 | nFORCE / signal cable open | FORCED BYPASS by the pull-up while a window may be commanded | Ladder shows Q_B ON in SENSE conditions; firmware cross-check | Sense bypassed with the charger powered: pack charge bounded by D1 at 2.2 A; in FC windows BT_BUS is LOW (no loop); in regen windows the input is V-MOT above the bus (no loop). |
| F23 | Main return path open at both leads | Board has no return; Teensy browns out | None | Double fault under F16; not credited. |
| F24 | Reversed or swapped harness | Negative supply on splitter ICs; or VBAT_N and GND_RET exchanged (bypass current through the Ag105) | Keyed, mechanically distinct connectors; reverse-blocking diode on the splitter logic feed; F_MAIN | The power path has no reversal protection, as today (DS p.18 recommends D1 at the pack). |

## 6. Hard requirements HR1-HR5

Table 11 gives the status of each hard requirement after review round 1 (definitions in facts_prior section
2.1).

Table 11. HR status (revision 1).

| HR | Status | Reason |
|---|---|---|
| HR1 regen harvesting | **FAILS** (calculation) | Per-event cold start 65-170 ms plus Bring-Up into the D-BT-SQ-isolated VCHG node (0.64 V/s measured) misses the 19-47 ms first pulse; the VMOT_OK limit cycle (section 4.9) further limits later pulses. IC2 does not meet ruling 1. IC2-W (section 4.11) is UNDETERMINED and needs a ruling. |
| HR2 FC charging | **BENCH, at risk** | Budget closed by calculation at 1.5 A (+0.09 A at eta 0.88, Table 10a). Per-purge timing gives about 0 average charge at the measured Bring-Up slope (Table 10b); B4 decides. |
| HR3 no circular loop | **PROVEN_CALC at logic level**, conditional | Every single fault of Table 10 that powers the charger without a legitimate source is opened by an independent hardware layer (D-BT-SQ gating, 2oo2 VMOT_OK, D5, D6) or bounded to a pulse with the eFuse bound. The detector thresholds and RT1987 turn-off times are TODO(calibrate) and not bench-verified. |
| HR4 no runaway | **PROVEN_CALC**, conditional | Three ceilings: the restored Ag105 sense (set + 200 mA = 1.7 A, DS p.18), U_OC at 2.2 A pack charge, and the eFuse at 1.39 A input. Conditional on R_s and on Ag105 regulation with the sense restored (B0, B3). |
| HR5 fail-safe inhibit | **BENCH** | Defaults to inhibit in reset, unpowered, cable-open and supply-failed states (Tables 2a, 10). The hung case uses D3 (23.4-31.6 ms, SBVS366A 6.6) and D4. Preconditions before any charging session: the RTWDOG implementation (T-W-01) and a production-fault build, not `BENCH_TEST 1` (review S-MAJ-6). |

## 7. Rework, parts list and cost

### 7.1 Rework steps on the manufactured board

The steps below are a procedure for a later approved rework. This study performs none of them.

1. Disconnect the pack. Discharge VBUS, V-MOT and VCHG-IN to below 1 V. Measure each with a DMM.
2. Measure, with the Ag105 fitted and unpowered, the resistance between pins 14/15 and pin 4 in both
   polarities. Record the values (gate X8, R_s).
3. Cut Ag105 pin 14 between the module body and the board. Do not desolder the pin. Cut pin 15 in the same
   way. Keep the barrels on the GND pour unused.
4. Measure from each cut module-side stub to PCB GND. The resistance must equal the value of step 2, not
   0 Ohm.
5. Cut Ag105 pin 10 in the same way. Measure that the module-side stub is isolated from VCHG-IN.
6. Solder one flying lead to both pin-14/15 stubs and one to the pin-10 stub. Size each lead for its fuse or
   eFuse rating (TODO(verify: wire ampacity table)). Label them `VBAT_N` and `VIN+_EF`.
7. Remove the balance-lead negative wire from J-BL pin 3. Insulate its end and key the harness so that it
   cannot be re-inserted.
8. Fit the TPS2663 carrier between VCHG-IN (board side) and `VIN+_EF`.
9. Fit the Teensy interposer (pins 28, 30, 31, 32 gated; pins 10, 16, 17, 20, 21, 22, 23, 33, 34 broken
   out). Do not cut board copper.
10. Fit the two independent V-MOT and VBUS divider pairs for VMOT_OK1/2, and the taps to the pin-38 and
    pin-41 nets for D5 and D6.
11. Build the pack harness: PACK+ through F_MAIN to the splitter, splitter output to J-BT pin 1; PACK- to
    splitter PACK_N; GND_RET lead A to J-BT pin 2; GND_RET lead B to J-BL pin 3; `VBAT_N` through F_VBN to the
    splitter Q_A drain. Use keyed, mechanically distinct connectors for PACK_P, PACK_N, GND_RET and VBAT_N.
12. Run the signal bundle (three analog lines, three open-drain lines, nFORCE) twisted to the interposer.
    **Do not run a ground conductor in the bundle.**
13. Optional: fly-wire BQ29200 OUT (QFN pin 8, no copper; workmanship UNCONFIRMED) to nPRE through an NFET.
14. Record the rework as a never-rotated hardware bodge record before the first power-up.

**WARNING:** Do not power the board with the balance-lead negative connected at J-BL pin 3. The connection
parallels the Ag105 sense, and an uncommanded charge current is then limited only by the U_OC latch.

**WARNING:** Do not exchange the GND_RET and VBAT_N leads. The exchange sends the bypass current through the
Ag105 sense and can exceed the 4 A I_DIS rating (DS p.20 row 6).

### 7.2 Parts list

Table 12 lists the parts. Unit costs are ESTIMATES for planning, not vendor quotations
(TODO(verify: DigiKey/Mouser pages on the order date)).

Table 12. Parts list (revision 1).

| Qty | Part | Function | Est. unit cost (USD) |
|---|---|---|---|
| 3 | TI CSD17573Q5B | Q_A, Q_B, spare | 1.5-2.5 |
| 8 | TI TLV1805DBVR | U_A, U_B, U_OC, U_AV, VMOT_OK1, VMOT_OK2, D5, D6 | 1.0-1.5 |
| 2 | TI INA181A2 | Pack current #1, #2 | 0.6-1.0 |
| 1 | 2 mOhm 4-terminal shunt, >= 2 W | R_SH | 1.0-3.0 |
| 1 | 3.3 V LDO (to be selected) | Amplifier supply | 0.5-1.0 |
| 1 | Shunt reference (to be selected) | Comparator references | 0.5-1.0 |
| 1-2 | Op-amp buffer (to be selected, >= 9 V supply) | INA181 REF and V_IREF drive, tap buffers | 0.5-1.0 |
| 1 | Dual voltage supervisor (to be selected) | D2 | 1.0-2.0 |
| ~8 | Small NFET, V_GS(th) min >= 1.5 V (to be selected) | N1, N2, veto, crossings | 0.1-0.3 |
| 12-16 | SN74LVC1G08 / 1G04 / 1G17 | Enable gates, delays, buffers | 0.2-0.4 |
| 1 | SN74LVC1G74 | LATCH | 0.3-0.5 |
| 1 | TI TPS3430 | External watchdog | 1.0-2.0 |
| 1 | TI TPS2663 + carrier | Mandatory VCHG-IN ceiling | 4-8 |
| 1 | Main fuse F_MAIN, rating from X8 (the DS 10 A slow-blow, DS p.7, is the starting point) | Pack positive | 1-3 |
| 1 | Fast fuse F_VBN, 3-4 A, I^2t above the section 4.4 reversal pulse | VBAT_N lead | 1-3 |
| 2 | PTC or 0.5 A fuse | LDO and reference feeds | 0.3-0.5 |
| ~50 | 0.1 % and 1 % resistors, Schottky diodes, capacitors | Thresholds, ladders, gate networks | 8 total |
| 2 | Small PCBs (splitter 2 oz; interposer) | Carriers | 10-30 total |
| 1 set | Keyed high-current connectors (4 distinct), wire, heat-shrink | Harness | 15-30 total |

Estimated total: USD 75-140 (ESTIMATE). Rework labour: about two days plus splitter and interposer layout
(ESTIMATE).

**Standing drain (review F-m7, E-m8).** The splitter draws from the pack whenever it is connected: two
INA181 at up to 260 uA each (SBOS793H p.1), the reference string, the supervisor and the comparator
quiescent currents (TODO(verify: SNOSD50A 6.5)). A 1-3 mA total (UNCONFIRMED) empties a 5 Ah pack in 70-210
days, in addition to today's V_batt divider (0.32 mA, facts_board 3.4) and Ag105 standby (120-420 uA, DS p.20
row 7). Storage procedure: unplug the pack harness.

## 8. Firmware, telemetry and HIL impact

The hardware is bodge-level. The firmware, telemetry and HIL change set is not; it is a full feature round
(review S-MAJ-7).

### 8.1 Pin map and flags

- The CSV gains the rows of Table 6 before any firmware change (CLAUDE.md priority 1).
- `AG105_VBATN_ISOLATED` describes "battery return not tied to PCB GND" (ino:5058-5062). A new flag
  `PACK_RETURN_STEERED` is preferred, with `AG105_VBATN_ISOLATED` set only after bench gates B0-B4 pass
  (UNCONFIRMED naming decision; operator).
- `FC_CHARGE_ALLOWED` stays 0 until HR2 is resolved.
- Reg 0x00 changes from 0x01 (2.5 A) to 0x04 (1.5 A) in `pollAg105()` (operator ruling; CLAUDE.md section 3).

### 8.2 New firmware duties

1. `setup()`: drive `PACK_BOND_FORCE` HIGH, then the RT1987 ENs LOW (existing), start the WDI kick timer,
   complete SD and Ethernet init, then clock `PACK_LATCH_RESET` and confirm the LATCH bit LOW. LATCH must be
   cleared before `doState0()` P0 drives `BT_SEQUENCE_ENABLE` HIGH (ino:12936-12938); a missed clear leaves
   charging disabled (safe, but it needs a check).
2. Boot self-test in Idle: with BOND_FORCE HIGH, confirm Q_B ON and Q_A OFF on `PACK_STAT_A`; confirm the
   differential pins 16 and 17 agree within 0.5 A; confirm VOK reads LOW with V-MOT at bus level.
3. `FAULT_PACK_STEER`: Q_B status LOW with discharge > 1.5 A for 5 ms; Q_A and Q_B both HIGH for any sample;
   or GAP for > 2 s. Action: drop BT_BUS and BT_REG, BOND_FORCE HIGH, State 99. Live in every build.
4. `FAULT_PACK_CROSSCHECK`: during a powered charger session, PACK_CURRENT charge > 0.3 A while reg 0x06
   reads below 0.1 A for 100 ms (the F1 signature), or pins 16 and 17 disagree by > 0.5 A. **A reg 0x06
   reading of 0xFF (DS p.14) or an I2C NACK counts as invalid, and an invalid reading also inhibits charging**
   (review F-m3). Action: charger inputs LOW, BOND_FORCE HIGH.
5. `FAULT_PACK_LATCH`: LATCH bit HIGH while not commanded. Action: State 99; LATCH stays set.
6. OV_BATT: filter V_batt over >= 10 ms while SENSE is reported with a charger powered (operator ruling,
   because OV_BATT is single-sample in all builds today).
7. UV_BATT: hold the dwell while `PACK_STAT_A` shows GAP (section 4.5).
8. State 99: on a steering-class fault, BOND_FORCE HIGH before phase 0, so both drains are refused in
   hardware; phases 0 and 1 must time out and continue on a refused drain (review S-minor 4).
9. The RTWDOG/WDOG1 implementation (X9) and the TPS3430 kick, fed only after `detectFaults()` completes, at a
   5-10 ms interval (section 2.8).
10. **Output-pin reads that the gates invalidate.** Every `digitalRead()` of an output pin returns the Teensy
    command, not the board level. The sites are: UV_BUS and UV_BATT arming (`digitalRead(BT_BUS_ENABLE)` and
    the matched-pair checks), the share latch, `chargerHasPower()` and the HIL mirror. Each must read
    `PACK_STAT_B` instead, or AND the command with it. `chargerHasPower()` becomes "D-BC-FC effective, or
    D-BC-RG effective" from the ladder; the revision-0 V_chg > 11 V heuristic is dropped (the CHG divider has
    a 7.87x ground-shift amplification, facts_prior section 5).

### 8.3 Telemetry

`switch_state` has two spare bits (facts_firmware section 7): bit 6 = Q_B ON, bit 7 = LATCH set. PACK_CURRENT
(signed, 16-bit, 10 mA/count) and the gated EN byte need new fields. That is a layout change: it must go
through the `protocol-bump` procedure (protocol v5, byte count, checksum span, PLAN.md section 6b, Pi bridge in
lockstep). The telemetry v5 proposal already in the repository is the natural carrier.

### 8.4 HIL and tests

- The simple plant (`tools/hil_plant_sim.py`) needs a pack-current state, the four steering states of
  Table 2, the gated enables of Table 5 and a charger that regulates pack current, with the BT boost draw and
  the logic load supplied unregulated (section 4.7).
- The hi-fi engine (`tools/hil_electrical.py:2069-2240`) models `BT_SEQ` as a pack-to-boost switch, which
  contradicts the netlist (facts_firmware section 9). The model must be corrected to VCHG-to-VBT before any
  IC2 scenario is meaningful.
- The 18-byte observation frame and the aux byte are full; the steering state and the gated ENs need a frame
  extension (HIL_MODE.md lockstep).
- The host-native test suite needs fixtures in which a commanded output pin and the board EN differ.

## 9. Open questions and bench gates

### 9.1 Open questions

1. R_s, the Ag105 sense resistance, and whether the sense conducts both ways when the module is unpowered
   (X8).
2. Whether the Ag105 over-current trip reads the same sense as the regulation loop (TODO(verify:
   Silvertel)).
3. Whether the undocumented internal switch in parallel with the sense (DS Fig.1 p.3) conducts when the module
   is unpowered or idle.
4. The Bring-Up behaviour with the sense restored: ramp rate, exit time, and the response to a reverse (pack
   discharging) sense current while powered (review S-MAJ-4). In the DS topology a VLoad discharge also
   crosses the Bat- leg (facts_ag105 section 1.3), so a reverse sense current is a designed condition when the
   module is not charging; its effect during Bring-Up is UNCONFIRMED.
5. Whether MPPTD LOW bypasses the reg 0x02 threshold (section 4.9).
6. The pack current ripple at R_SH and the steering transition rate in regen windows.
7. The INA181 offset at V_CM = 8 V, the REF drive requirement, and the TLV1805 sink current.
8. The interposer clearance and retention on the J1/J2 receptacles, and the Ag105 pin-cut access under the
   module.
9. OQ-7: which RT1987 EN nets carry the 10 kOhm pull-down; the gating relies on all four of Table 5.
10. The i.MX RT1062 pad state across a warm and an RTWDOG reset (PJRC/NXP).
11. Whether CLAUDE.md section 4 (CB_EN hardwired) or the schematic (CB_EN on pin 9) describes the fitted
    board (facts_board section 5 item 4).
12. Charger-independent gates carried over: S0-R3 / T-E-03, M-R1, M-R2, T-E-01, T-W-01 (facts_prior
    section 11).

### 9.2 Bench gates, in order

1. **B0 (passive).** Steps 2, 4 and 5 of section 7.1; R_s both polarities; continuity of `VBAT_N` and
   `VIN+_EF`.
2. **B1 (splitter alone).** Bench supply as the pack, electronic load and a current-limited source/sink on
   PACK_N. Sweep I_dis from -3 A to +17 A and back, DC and with superimposed 2-6 Hz and boost-frequency
   ripple. Record the thresholds, the hysteresis and both gate states; confirm Q_A and Q_B never ON together
   (scope both gates). Inject 2.5 A charge: LATCH preset line must assert. Remove the LDO, then the reference:
   FORCED BYPASS and the preset assertion must result each time. Open the signal cable: FORCED BYPASS. Measure
   V_GS(Q_A) in GAP at the hot-case body-diode drop.
3. **B2 (board, no charger power).** Pack on the splitter, Teensy running, BOND_FORCE HIGH. Boot self-test;
   LATCH power-up SET; TPS3430 and RTWDOG forced-hang tests (T-W-01); a forced RTWDOG warm reset with each
   gated pin previously HIGH, observing every board EN; ladder calibration; D5 and D6 thresholds with
   injected voltages; standing drain.
4. **B3 (Ag105 from a bench supply, BT boost disabled, then BT boost enabled).** Power VCHG-IN from a
   current-limited supply with BT_BUS forced LOW and **the Teensy powered from the pack**. Confirm reg 0x06
   equals PACK_CURRENT within 0.1 A, the CC current at 0x04, CV termination at 10 % (DS p.5), V_batt below
   8.5 V at CV entry, and the OC trip at set + 200 mA. Repeat with a BT-boost draw step. Measure VCHG
   overshoot when CMDD falls and when LATCH sets under load (review E-m9).
5. **B4 (Bring-Up timing).** From an input power edge, measure the time to the first charge current with VCHG
   at 0 V, with the Teensy load on VBT. This gate decides HR2.
6. **B5a (input regulation).** With MPPTD LOW and reg 0x02 = 18.57 V, does the module charge from a 16 V input?
   Decides option R-a (section 4.9).
7. **B5 (regen, after S0-R3).** VMOT_OK1/2 thresholds; then one braking event with BT_BUS HIGH; confirm no
   bus-side current excess (G1/G2), the BYPASS-to-SENSE transient while powered (review F-M7), and the absence
   of an OC nuisance trip.
8. **B6 (FC window).** Only after HR2 rulings; Ag105 efficiency at 16 V input and 2S output; the bus current
   of Table 10a.

Each gate must pass before the next one starts. A failure at B1 or B3 stops the concept. A failure at B4
leaves IC2 as a standstill design that removes the ML0227 root cause and delivers little FC charge.

## 10. Review round 1 adjudication

### 10.1 Method

Three adversarial reviewers (fault, electrical, system) returned survives_with_fixes with no fatal finding.
Each finding was checked against the primaries named in its row. Three TI datasheets not previously read were
obtained from the vendor and text-extracted for this round: SBOS793H (INA181), SCES794G (SN74LVC1G74) and
SBVS366A (TPS3430). The LM1084 dropout table (SNVS037H section 5.5) was re-read from the local PDF. Finding
identifiers use the prefixes F- (fault reviewer), E- (electrical) and S- (system). "ACCEPTED" means the design
body was changed; "PARTLY REFUTED" names the part that the evidence does not support.

### 10.2 Fault reviewer

Table 13 records the adjudication of the fault reviewer's findings.

Table 13. Fault reviewer findings.

| ID | Verdict | Evidence | Design change |
|---|---|---|---|
| F-M1 | ACCEPTED | V-MOT is held at bus level in Idle and Run (facts_firmware section 6); BT_BUS is HIGH under the battery-only start (section 5). With D-BC-RG shorted, revision-0 BOND_FORCE forced BYPASS and no LATCH input fired, because the loop current runs through the BT boost, not the pack (facts_prior section 4.1). The revision-0 F10/F13 residuals were wrong. | D-BT-SQ gated on a commanded charger input in a separate package; D6 uncommanded-input detector; D5 BT-loop detector; eFuse mandatory; F9, F10, F12, F13 and HR3 re-derived (sections 2.6, 2.10, 4.7, Tables 10, 11). |
| F-M2 | ACCEPTED (UNCONFIRMED mechanism) | PJRC states a pad keeper (facts_board 7.3); the prior study requires <= 47 kOhm pull-downs to beat a keeper (facts_prior section 10 item 6). Pad state across reset is not in a read primary. | 10 kOhm pull-downs on every interposer input; B2 forced-reset test. |
| F-M3 | ACCEPTED | At 17.1 A the sense path stays below the 0.8 V knee for path resistance < 47 mOhm (0.8 / 17.1); revision 0's "above 4 A" holds only above 200 mOhm. I_DIS = 4 A (DS p.20 row 6). | U_AV veto on channel #2; fast fuse F_VBN 3-4 A in VBAT_N. |
| F-M4 | ACCEPTED | V_GS(th) min 1.1 V (SLPS492B 5.1) against a 0.8-1 V body-diode offset (SLPS492B 5.1). | U_A and its pull-down referenced to PACK_N; N1 clamps the Q_A gate to PACK_N. |
| F-M5 | ACCEPTED | A diode from a 3.3 V HIGH cannot pull a 1.6 V node low; the reversed diode forces BYPASS when LOW. | nFORCE NFET injection with defined defaults (section 2.5, Table 2a). |
| F-M6 | ACCEPTED | Contact resistance 20 mOhm maximum (TB005-762 p.1); a parallel signal ground shares the return current by resistance ratio. | No ground conductor in the bundle; differential analog reads; open-drain crossings; GND_RET lead B on J-BL pin 3 (independent terminal). |
| F-M7 | ACCEPTED | Q_B shunts the sense in BYPASS while the charger is powered in a regen window; the module then runs at its CC setting into the BT boost. | Section 4.7 bound (input power and eFuse); 1.5 A setting lowers the step; bench gate B5 measures the transition and nuisance trips. |
| F-m1 | ACCEPTED | SN74LVC1G74 input range -0.5 to 6.5 V (SCES794G 6.1); PRE is active-low (SCES794G pin functions, Table 8-1). | Open-drain crossings onto an active-low nPRE. |
| F-m2 | ACCEPTED | PRE and CLR both LOW give Q = Q-bar = HIGH (SCES794G Table 8-1 note 1). | Reset by clock edge with D = 0; CLR unused. |
| F-m3 | ACCEPTED | Reg 0x06 reads 0xFF below 9 V or in an error state (DS p.14). | 0xFF or NACK = invalid = inhibit (section 8.2 item 4). |
| F-m4 | ACCEPTED | One open lower resistor puts 8.5 V on a 5.5 V-tolerant input (SCES217AA p.1). | Dividers removed; open-drain crossings. |
| F-m5 | ACCEPTED | DS typical circuits fit a 10 A slow-blow fuse in the battery lead (DS pp.7, 15, 16). | F_MAIN; PTCs on the logic feeds. |
| F-m6 | ACCEPTED | No reversal protection on the module (DS p.18). | Keyed distinct connectors; reverse-blocking diode on the logic feed; F24. |
| F-m7 | ACCEPTED | INA181 260 uA maximum each (SBOS793H p.1). | Standing-drain paragraph and storage procedure (section 7.2). |
| F-m8 | ACCEPTED | VMM_DET_ON 17-45 mV (SLUSA52C 7.5) against a 0.6-1.0 V offset. | GAP confined to windows (FORCED BYPASS); VC1 absolute maximum remains TODO. |
| F-m9 | ACCEPTED | ino:12761 holds BT_BUS LOW in windows (facts_firmware 3.1). | Stated as invariant (section 2.6). |
| F-m10 | ACCEPTED, now resolved | SBVS366A section 6.6: t_WDU 23.4-31.6 ms at CWD = NC, SET0 = 0, SET1 = 1. | Configuration and kick rules in section 2.8. |

### 10.3 Electrical reviewer

Table 14 records the adjudication of the electrical reviewer's findings.

Table 14. Electrical reviewer findings.

| ID | Verdict | Evidence | Design change |
|---|---|---|---|
| E-M1 | ACCEPTED | 4.8 W / 0.9 / 7.8 V = 0.68 A pack current sits in the 0.6-1.0 A GAP band; UV_BATT arms on BT_BUS and BT_REG (facts_firmware section 4); LM1084 regulation from 6.5 V (SNVS037H 5.5). The drop at sub-ampere current is likely below the 0.8 V (35 A) figure, but no SLPS492B curve was extracted, so 0.6-1.0 V is used. | FORCED BYPASS outside charge windows; UV_BATT dwell hold in GAP; GAP > 2 s fault. |
| E-M2 | ACCEPTED | As F-M6. The 0.34 V offset (17.1 A x 20 mOhm) is a 3.4 A error at 0.1 V/A on a single-ended read. | Differential read against V_IREF on pin 23; thresholds in firmware referenced to the differential value. |
| E-M3 | ACCEPTED | Revision 0 put references and amplifier supplies on one LDO; 0 V against 0 V is indeterminate within the 4.5 mV offset (SNOSD50A 6.5). | Separate shunt reference on PACK_P; supervisor D2; 1 MOhm IN+ bias on U_B; F8 and F8b rewritten. |
| E-M4 | ACCEPTED | Reg 0x02 policy 12.32-13.38 V (CLAUDE.md section 3) lies below the 17.07 V VMOT_OK trip; 14 mV built-in hysteresis gives about 112 mV at V-MOT. | VMOT_OK hysteresis to 1.020 x VBUS; eFuse mandatory; section 4.9 options R-a/R-b; B5a. |
| E-M5 | ACCEPTED | DS pp.7, 15, 16 (fuse and D1); DS p.18 (protected packs). The DS 10 A rating is below the 12-17.1 A ILIM (SLVSFP3C 7.5), but ILIM is a peak inductor value. | F_MAIN rated from X8; signal-tap series resistors and PTCs; reversal behaviour stated (F24). |
| E-m1 | ACCEPTED | As F-M5. | As F-M5. |
| E-m2 | ACCEPTED | As F-m1; VMOT_OK comparators now on 5 V with outputs into 5.5 V-tolerant LVC (SCES217AA p.1). | Open-drain crossings; active-low nPRE. |
| E-m3 | ACCEPTED | SNVS037H section 5.5: the 1.3 V entry falls in the TYP column; p.1 gives "a maximum dropout of 1.5V". | Section 4.5 corrected to 1.5 V maximum. |
| E-m4 | ACCEPTED | As F-M4. | As F-M4. |
| E-m5 | ACCEPTED | Ripple 100 mVp-p typical (DS p.20 row 9). | R_s limit restated with ripple; V_batt filter in SENSE (section 8.2 item 6). |
| E-m6 | ACCEPTED | A discharge step in SENSE crosses the sense in reverse for 20-40 us. | FCD/CMDD delays block BT_BUS until FORCED BYPASS at window end; regen-window residual stated; F_VBN I^2t requirement. |
| E-m7 | ACCEPTED | 8 V / 1 MOhm = 8 uA into a tap; 8 mV at 1 kOhm. | Buffered taps or <= 100 Ohm Thevenin. |
| E-m8 | ACCEPTED | As F-m7. | As F-m7. |
| E-m9 | ACCEPTED | Ag105 open-output response unspecified (facts_ag105 3.2, 3.3). | B3 measures VCHG overshoot on CMDD fall and on LATCH. |
| E-m10 | ACCEPTED | t_D_ON 8 ms (DS-00 17.1). | Invariant stated (section 2.6). |
| E-m11 | ACCEPTED | Fault currents F3, F6, F16 exceed the 3.3 A sizing. | VBAT_N sized to F_VBN; GAP faults handled by U_AV. |

### 10.4 System reviewer

Table 15 records the adjudication of the system reviewer's findings.

Table 15. System reviewer findings.

| ID | Verdict | Evidence | Design change |
|---|---|---|---|
| S-MAJ-1 | ACCEPTED | As E-M1; the battery-only start is the default at standstill (facts_firmware section 5). The BQ29200 bleed (b) and LM1084 headroom (c) follow from SLUSA52C 7.5 and SNVS037H 5.5. | FORCED BYPASS outside windows; Table 8 objection 5 and Table 9 corrected. |
| S-MAJ-2 | ACCEPTED | 2.5 x 8.4 / 0.88 = 23.9 W > 18.9 W (facts_prior section 6); regen branch drives MPPT LOW (facts_firmware 3.2 item 3). The 86 us decay figure is consistent with 20 uF x 6 V / 1.4 A. | Section 4.9; VMOT_OK hysteresis; 1.5 A setting; options R-a/R-b; B5a. |
| S-MAJ-3 | ACCEPTED in part; PARTLY REFUTED | ACCEPTED: HR1 fails and ruling 1 is not met; the R3 citation was superseded by evaluation ruling 3 (facts_prior section 3). PARTLY REFUTED: revision 0 LATCH already removed D-BT-SQ ("pin32 AND NOT LATCH"), which disconnects the output while the input is powered, so "only remove input power" is inaccurate. That mechanism does not keep the charger warm, so the conclusion stands. | Section 0 item 8, Table 11 HR1 FAILS; section 4.11 IC2-W for an operator ruling. |
| S-MAJ-4 | ACCEPTED, with one qualification | The logic load and the BT boost return outside the sense (facts_ag105 1.4). Qualification: in the DS topology a VLoad discharge also crosses the Bat- leg (facts_ag105 1.3), so a reverse sense current is not foreign to the module; its effect during Bring-Up remains UNCONFIRMED. | Open question 4; B3 with the Teensy on the pack and a BT draw step. |
| S-MAJ-5 | ACCEPTED | Table 4 codes (Ag105_Table4 JSON); FC budget (facts_prior section 7); firmware timings ino:2484, 2634, 2655. | Section 4.10, Tables 10a and 10b; 1.5 A setting; U_OC and eFuse scaled. |
| S-MAJ-6 | ACCEPTED | BENCH_TEST 1 compiles out OC_FC, OC_BT, UV_BATT and SWITCH_CONFLICT (facts_firmware build flags); no MCU watchdog (section 8). | eFuse mandatory; 2oo2 VMOT_OK; RTWDOG and a production-fault build as charging preconditions (HR5 row). |
| S-MAJ-7 | ACCEPTED | Table 6 consumes all but one spare pin; `digitalRead(output)` sites listed in facts_firmware sections 2-4. | Readback ladders; invalidated read sites listed (section 8.2 item 10); V_chg heuristic dropped; firmware scope stated as a full feature round. |
| S-minor 1 | ACCEPTED | As F-M4. | As F-M4. |
| S-minor 2 | ACCEPTED | In BYPASS the Q_A body diode blocks discharge, so an open return leaves no path. | Independent second return lead; F16 rewritten. |
| S-minor 3 | ACCEPTED | Objection 4 includes the charger bring-up per event (facts_prior section 8). | Table 8 rewritten. |
| S-minor 4 | ACCEPTED | Phase 0 drives FC_CHARGE HIGH for about 10 ms (facts_firmware 2.1). | BOND_FORCE HIGH on steering-class faults; drains tolerate refusal. |
| S-minor 5 | ACCEPTED | J1/J2 are dual-contact 87606-324LF receptacles (facts_board 7.2). | F19-F21 added; retention BENCH. |
| S-minor 6 | ACCEPTED | P0 drives BT_SEQUENCE HIGH at ino:12936-12938. | Firmware ordering check (section 8.2 item 1). |
| S-minor 7 | ACCEPTED, no change needed | The fix of S-MAJ-1 does not lower the thresholds; the 0.365 A margin of section 4.4 is unchanged. | None. |
| S-minor 8 | ACCEPTED | The 2-6 Hz ripple is recorded (fw37 planning section 6). | B1 adds ripple sweeps; chatter confined to windows. |

### 10.5 Post-review status

The adjudication accepts every major finding of the three reviewers, wholly or in part. No finding was fully
refuted. One claim (S-MAJ-3, input-only inhibit) is partly refuted without changing its conclusion. The
revision-1 design closes each finding by a stated change or moves it to a named bench gate.

The honest status of IC2 after review round 1 is as follows:

1. **The root cause of ML0227 is removed in principle.** The pack return crosses the Ag105 sense during every
   charge, and three hardware ceilings bound the pack charge current (HR4 PROVEN_CALC, conditional on R_s and
   bench gates B0-B3).
2. **The loop hazard is closed at the logic level for every enumerated single fault** (HR3), but only by
   adding D-BT-SQ gating, a second VMOT_OK comparator, two current/voltage detectors and a mandatory eFuse
   with a second module pin cut. None of these layers has been bench-tested.
3. **HR1 fails.** IC2 does not satisfy operator ruling 1 as specified. The warm variant IC2-W is the only HR1
   path and needs a ruling under evaluation ruling 3 plus an Ag105 warm-response measurement.
4. **HR2 is at risk.** The budget closes only at a reduced 1.5 A setting with about 0.09 A of margin, and the
   measured Bring-Up slope gives an average charge near zero between purges. Bench gate B4 decides.
5. **The concept is larger than revision 0 claimed.** The hardware remains off-board or bodge-level (a
   splitter board, an interposer, three Ag105 pin cuts, flying leads), at an estimated USD 75-140 and about two
   days of labour. The firmware, telemetry, HIL and test changes are a full feature round, and the pin budget
   leaves one spare pin.

IC2 therefore survives review round 1 as a feasible **FC-only, standstill-weighted** isolation design with
open bench gates. It does not meet the complete study goal of regen and FC charging.
