# IC3 design dossier: pack on the Ag105 battery port, D-BT-SQ as the pack-to-board switch, VCHG-IN-keyed hardware veto

Date: 2026-11-07. Board revision 20260622, firmware fw v37 rev 2 (`AG105_VBATN_ISOLATED 0`).
Inputs: `facts_board.md`, `facts_ag105.md`, `facts_firmware.md`, `facts_prior.md` and `brainstorm.md` in this folder.
Status: revision 1, after review round 1 (fault, electrical and system lenses). Section 11 records the adjudication of
every finding; the design body below already carries the accepted fixes. Nothing in this dossier has been ordered,
desoldered, flashed or bench-tested.

## 0. Summary

This dossier develops isolation concept IC3 into a buildable design and tests it against HR1-HR5. The pack
positive moves from J-BT pin 1 (net `VBT`) to net `VCHG` (Ag105 VBat+, D-BT-SQ VIN). The pack negative moves to the
Ag105 VBat- pins 14/15, which are cut free of the GND barrels, with one low-side bypass MOSFET, **S_BYP**, from the pack
negative to PCB GND. The existing RT1987 **D-BT-SQ** becomes the only path from the pack to the board. A comparator on
`VCHG-IN` forces the D-BT-SQ enable low whenever the charger input carries more than about 9.7 V. The S_BYP gate
follows the same veto-qualified enable net, so one control net opens the pack-to-board path and restores the Ag105
current sense together. A **pack current monitor** (an INA253A1 in the pack-negative lead with two ratiometric
comparators) bounds the pack current in hardware in both directions, independently of the Ag105 sense and of the
Teensy.

The design has the following properties after review round 1:

1. **The circulating loop of ML0227 is broken by topology plus a hardware veto (HR3).** While the charger input is
   live, `VBT` has no source, so charger output cannot reach the BT boost. The veto is now tested functionally before
   every window and its sense path is checked in every window.
2. **The Ag105 sense regulates the pack current again (HR4),** provided that S_BYP is off and no hidden pack-negative
   bond exists. A shorted S_BYP, a stuck gate driver or a lost sense return is now bounded in hardware at about 2.1 A of
   charge current by the pack current monitor, on any source, including a bench supply.
3. **FC charging (HR2) is BENCH-gated.** It is feasible on budget only at a reduced Ag105 current (Table 4 code 5,
   1.25 A), only at standstill or very light traction, and only in windows scheduled between H-20 purges by a purge
   predictor that does not yet exist.
4. **Regen harvesting (HR1) fails structurally as ruling 1 states it.** The charger can never be warm while the pack
   feeds the bus, so every brake starts from a cold Ag105 and the first regen pulse is always lost. This is a declared
   failure for an operator ruling (section 10).
5. **D-BT-SQ carries the whole BT boost input current, and its exposed pad has no thermal copper on this board.**
   At the `OC_BT` limit the input current is about 7.6 A, 95 % of the 8 A rating. The thermal gate G-T1 is the first
   kill gate; its likely outcome is a BT continuous cap well below today's capability, or replacement of D-BT-SQ by an
   external high-side switch, which converges with IC4.
6. **The rework is in place:** the Ag105 module stays soldered; only pins 14 and 15 are cut above the board.

## 1. Topology

### 1.1 Switches and nets

Table 1 lists every switch in the IC3 power path, the net on each terminal, its control and its default state. The
new parts are S_BYP, the veto comparator U_V, the S_BYP gate driver U_G, the charger-input drain Q_D, the pack current
monitor U_P with comparators U_OCD and U_OCC, and the feed-cut transistors Q_F30 and Q_F31.

Table 1. IC3 switches.

| Switch | Part | Terminal A (net) | Terminal B (net) | Control | Default with Teensy unpowered, in reset or hung |
|---|---|---|---|---|---|
| D-BT-SQ (existing, re-purposed) | RT1987N-A | VIN = `VCHG` = pack positive | VOUT = `VBT` | Net `D-BT-SQ` (EN): Teensy pin 32 through new R_S 1 kOhm; pull-downs R_PD 10 kOhm (veto board) and R_PD2 10 kOhm (at the EN pad end); open-drain pull-downs from U_V (veto) and U_OCD (discharge over-current) | Off (R_PD, R_PD2; RT1987 internal REN_PD 475-985 kOhm, RT1987 DS-00 p.7) |
| S_BYP (new) | Infineon BSC010N04LSC, 40 V | Drain = new net `PACKN` (pack negative after the U_P shunt; Ag105 VBat- lead) | Source = PCB `GND`, by two soldered leads onto the J-BT pin-2 pad, not through the screw contact | U_G output; U_G IN+ from net `D-BT-SQ` through R_d 10 kOhm / C_d 100 nF | Off (U_G output held low on floating input and in VDD UVLO, SLUSAY4D p.1 features; gate pull-down R_GS 10 kOhm) |
| D-BC-FC (existing) | RT1987N-A | `VBUS` | `VCHG-IN` | Teensy pin 31 `FC_CHARGE_ENABLE` through new R_S31 1 kOhm; Q_F31 pulls EN low on a charge over-current | Off (pull-down bodge, OQ-7) |
| D-BC-RG (existing) | RT1987N-A | `V-MOT` | `VCHG-IN` | Teensy pin 30 `REGEN_ENABLE` through new R_S30 1 kOhm; Q_F30 pulls EN low on a charge over-current | Off (pull-down bodge, OQ-7) |
| D-BT-EN (existing) | RT1987N-A | `VBUS-BT` | `VBUS` | Teensy pin 28 `BT_BUS_ENABLE` | Off (pull-down bodge, OQ-7) |
| Q_D (new) | 2N7002-class NFET + R_D 330 Ohm, 2 W | `VCHG-IN` | `GND` | Teensy pin 33 | Off (gate pull-down 100 kOhm) |
| R_BL (new, passive) | 10 kOhm, 0.25 W | `VCHG-IN` | `GND` | Permanent bleed | Always present |

The Ag105 internal current sense sits between `PACKN` (VBat-, pins 14/15) and `GND` (Vin-, pin 4, plus VLoad- pins
16/17, which are internally Vin-, Ag105 DS V1.1 Table 2 p.4) inside the module (DS Fig.1 p.3). With S_BYP off, it is
the only intended element between pack negative and system ground for charge current.

### 1.2 Power-path diagram

Figure 1 shows the reworked power path. Heavy lines (`==`) carry pack discharge current; `[X]` marks a cut or
removed connection.

```
 PACK (2S LiPo)                                  BOARD (rev 20260622, reworked)
 +-------------+
 |  pack +  o==+==[F1 fuse, mandatory]==[ 14 AWG lead ]==> VCHG pour ---+--- Ag105 VBat+ (18,19)
 |             |                                            (C-D11 10uF)  |
 |             |                                                          +--> D-BT-SQ VIN ==(RT1987)==> VOUT = VBT
 |             |                                                          |       EN <- net D-BT-SQ        |
 |             |                                                          |                                 +== preformed lug/braid ==> J-BT pin 1 (VBT)
 |             |                                                          |                                 |     -> REG-BT VIN, L-BT, C1-BT,
 |             |                                                          |                                 |        C-D12, R1-BT (V_batt divider)
 |             |                                                          +--> new feed --> REG-5V INPUT (LM1084) [X] old VBT feed cut
 |             |                                                          +--> R_PV1 22.1k / R_PV2 10k --> Teensy pin 16 (PACK_VOLTAGE)
 |             |                                                          +--> 10R + 1uF --> U_G VDD (UCC27517)
 |             |
 |  pack -  o==+==[ harness ]==> U_P INA253A1 (IS+ -> IS-, 2 mOhm) ==> PACKN node (switch board)
 |             |                                                      |
 |  bal. neg o-+--[X] insulated, NOT on J-BL pin 3                    +--- [F2 3 A fuse] --- 20 AWG lead --> Ag105 VBat- (14,15 stubs,
 |  VMID     o-------------------> J-BL pin 2                         |                                    cut free of the GND barrels)
 |  VBAL+    o-------------------> J-BL pin 1                         |                                          |
 +-------------+                                                      |                                 [Ag105 internal sense]
                                                                      |                                          |
                                                             S_BYP drain                               Ag105 Vin- (4) = GND,
                                                             S_BYP source ==2 leads==> J-BT pin-2 pad   VLoad- (16,17) bonded to GND
                                                             (body diode: anode GND, cathode PACKN = passes discharge only)
                                                             PACKN --> 10k --+--> Teensy pin 17 (PACKN_VOLTAGE, bipolar)
                                                                    3V3 --10k-+   clamps to GND and 3V3
                                                             U_P OUT --> 10k/10k --> Teensy pin 23 (PACK_CURRENT)
                                                             U_P OUT --> U_OCD (pulls D-BT-SQ EN low below -8.3 A)
                                                             U_P OUT --> U_OCC (drives Q_F30, Q_F31 above +2.1 A)

 Charger input: VBUS --D-BC-FC (pin 31 via R_S31; Q_F31)--+
                V-MOT --D-BC-RG (pin 30 via R_S30; Q_F30)--+--> VCHG-IN --> Ag105 Vin+ (10)
                                                           |
                                                           +--> R_BL 10k --> GND (permanent bleed)
                                                           +--> R_V1 100k / R_V2 14.7k --> U_V (TLV3011B) IN-  (and 10k --> Teensy pin 22)
                                                           +--> R_D 330R --Q_D (pin 33)--> GND   (window-exit drain)
```

Figure 1. IC3 power path, revision 1. The interpretation follows.

1. In Run, pack current leaves pack positive, crosses D-BT-SQ into `VBT` and the BT boost, and returns through
   PCB GND, the J-BT pin-2 pad, S_BYP, `PACKN` and the U_P shunt to the pack negative. The Ag105 branch (F2, lead,
   module) is in parallel with S_BYP and carries a reverse share of the discharge current (section 4.6).
2. In a charge window, D-BT-SQ and S_BYP are off. The Ag105 output reaches only the pack and the LM1084 feed. Pack
   charge current returns through U_P, `PACKN`, F2 and the Ag105 sense to Vin- (GND), so the module regulates it, and
   U_P bounds it in hardware if the sense is bypassed.
3. The LM1084 is fed from pack positive in every state, so the Teensy never depends on `VBT`.
4. `VCHG-IN` is held near 0 V outside windows by R_BL against any off-state leakage of the two charger feeds
   (section 4.7).

### 1.3 Control and veto circuit

Figure 2 shows the control net of D-BT-SQ after the rework. The existing trace from Teensy pin 32 to the D-BT-SQ EN
pad is cut; all new parts except R_PD2 sit on a small veto board wired to both cut ends.

```
 Teensy pin 32 --[R_S 1k]--+------------------------------+==(flying lead)==+--> D-BT-SQ EN (pad 5)
                           |                              |                 +--[R_PD2 10k]--> GND (at the pad end)
                           +--> Teensy pin 34 (readback)  +--[R_PD 10k]--> GND
                           |                              |
                           |                              +-- U_V OUT (open-drain)  <-- TLV3011B, VS = 5V rail
                           |                              |     IN- <-- VCHG-IN x 14.7k/114.7k
                           |                              |             (+ test inject: pin 35 -[10k]-|>|- BAT54)
                           |                              |             (+ readback: 10k --> Teensy pin 22)
                           |                              |     IN+ <-- U_V REF (1.242 V)
                           |                              |
                           |                              +-- U_OCD OUT (open-drain) <-- TLV3011B, VS = 5V
                           |                                    IN+ <-- U_P OUT;  IN- <-- 5V x 10k/30k = 1.667 V
                           |
                           +--[R_d 10k]--+--> U_G IN+ (UCC27517, VDD = VCHG via 10R/1uF, IN- to GND)
                                         |
                                       [C_d 100nF] to GND
                           U_G OUT --[R_G 4.7R]--> S_BYP gate, [R_GS 10k] gate-source
                           S_BYP gate --[22k]--+--[10k]--> GND
                                               +--> Teensy pin 10 (S_BYP gate readback)

 U_OCC (TLV3011B, VS = 5V): IN+ <-- U_P OUT; IN- <-- 5V x 10k/18.45k = 2.710 V (+ test inject: pin 21 -[10k]-|>|- BAT54 into IN+)
   OUT (open-drain, 10k pull-up to 5V) --> gates of Q_F30, Q_F31 (2N7002-class), each drain on its feed EN net
```

Figure 2. D-BT-SQ enable net with the veto, the discharge over-current pull-down and the slaved S_BYP drive, plus the
charge over-current feed cut. The interpretation follows.

1. With pin 32 HIGH and no pull-down active, the EN net sits at 3.3 x 5 / 6 = 2.75 V (R_S against R_PD parallel
   R_PD2). This is above the RT1987 VEN_R of 1.4 V maximum (RT1987 DS-00 Table 13 p.7) and above the UCC27517 VIN_H of
   2.4 V maximum (SLUSAY4D, Electrical Characteristics, input section).
2. When `VCHG-IN` exceeds the veto threshold, U_V sinks the 3.3 mA from R_S. The TLV3011 output low level is 200 mV
   maximum at 5 mA sink with VS = 5 V (SBOS300C section 6.7), below the RT1987 VEN_F of 0.6 V minimum (RT1987 DS-00
   Table 13 p.7) and below the UCC27517 VIN_L of 1.0 V minimum. D-BT-SQ and S_BYP therefore both open. U_OCD acts on the
   same net in the same way when the discharge pack current exceeds about 8.3 A.
3. R_d/C_d delay the S_BYP edges (section 4.3). On a falling edge D-BT-SQ opens first: S_BYP follows 1.01 ms later
   when pin 32 drives the net to 0 V, and 1.16 ms later when the veto holds it at 0.2 V. On a rising edge S_BYP closes
   1.6-2.1 ms after EN rises, about 6 ms before D-BT-SQ conducts (tD_ON 8 ms typical, no minimum given, RT1987 DS-00
   Table 13 p.7).
4. Pin 34 reads the EN net after the pull-downs. Pin 10 reads the S_BYP gate. Pin 35 injects a test level into the veto
   input through a BAT54, which is reverse-biased when pin 35 is LOW, so it does not load the veto divider. Pin 22
   reads the veto input node, so the divider and the `VCHG-IN` flying lead can be checked against `V_chg` (pin 38).
5. U_OCC releases its open-drain output above about 2.1 A of charge current; the pull-up then turns on Q_F30 and Q_F31,
   which hold both charger-feed EN nets low against the 1 kOhm series resistors R_S30 and R_S31. Pin 21 injects a test
   level into U_OCC IN+.

### 1.4 Deviation from the concept brief

The brief assigns pin 33 to an independent S_BYP control. This dossier instead slaves S_BYP to the veto-qualified
D-BT-SQ enable net. The reason is that IC3 has no legal state with D-BT-SQ conducting and S_BYP off, or with S_BYP
on and the charger powered. Slaving removes the illegal combination "S_BYP on while VCHG-IN is live" unless the veto
itself has failed. However, a single U_G or R_d fault now also forces S_BYP off in Run; section 6 rows F4 and F17
cover this. Pin 33 is re-used for the charger-input drain Q_D.

The brief also offers an optional VBUS leg for the LM1084 feed. This dossier rejects it on thermal grounds
(section 4.5).

## 2. Selected parts, ratings and fail-safe defaults

### 2.1 Parts and primary ratings

Table 2 lists each new or re-purposed part with the ratings this design depends on. Prices that no primary gives are
marked TODO.

Table 2. Selected parts.

| Ref | Part | Ratings used (primary) | Role |
|---|---|---|---|
| D-BT-SQ | RT1987N-A (fitted; BOM line 77, USD 1.77) | 3.4-32 V VIN; 8 A continuous, 20 A peak for 10 ms at 2 % duty (RT1987 DS-00 section 12); R_ON 20 mOhm typical at VIN = 20 V and 22 mOhm typical at VIN = 5 V, no maximum given (Table 13 p.7); thetaJA 53.05 C/W only on a JEDEC 51-7 four-layer board with the exposed pad soldered to a large isolated copper area with many vias (sections 8 and 18.3); TJ 125 C recommended maximum (section 12); OTP 140 C, a **latch**: Table 13 p.7 "System latches off" and section 17.8 "Toggle the EN pin or cycle the input power" (section 17.4 Table 1 alone says auto-restart); SCP 2.5 A at ramp start, active only during soft-start (section 17.5); ISHDN 75 typ / 105 uA max at EN = 0 V; IOUT_LK 45 typ / 60 uA max (Table 13 p.7); UVLO rising 3.0-3.35 V; fast reverse comparator -50 mV / 0.5 us (section 17.6) | Pack-to-board switch |
| S_BYP | Infineon BSC010N04LSC, PG-TDSON-8 (Final Data Sheet Rev. 2.3, 2020-04-16) | VDS 40 V; RDS(on) 0.90 typ / 1.05 max mOhm at VGS 10 V and 1.05 / 1.35 mOhm at 4.5 V, ID 50 A (Table 4 p.4); VGS(th) 1.2-2.0 V; VGS +/-20 V (Table 2 p.3); RthJA 50 C/W on 6 cm2 copper (Table 3 p.3); diode VSD 0.81 typ / 1.0 V max at 50 A (Table 7 p.5). The data sheet refers non-UL-2595 applications to BSC010N04LS, which may be substituted after its own data sheet is read | Low-side bypass, body diode passes discharge only |
| U_V, U_OCD, U_OCC | TI TLV3011B, SOT-23-6 (SBOS300C) | Open-drain output; VS 1.65-5.5 V for B versions, 7 V absolute; reference 1.208 / 1.242 / 1.276 V; VOL 200 mV max at 5 mA, VS = 5 V; propagation 6-13.5 us; IQ 5 uA max; fail-safe inputs and 2-8 mV internal hysteresis in the B version (sections 1, 6.1, 6.7-6.9). U_OCD and U_OCC use an external 5 V-ratiometric threshold, not the internal reference | Veto; discharge and charge over-current |
| U_P | TI INA253A1IPWR (fitted type, BOM line 14, USD 4.03) | Integrated 2 mOhm shunt; +/-15 A continuous at -40 to +85 C; common mode -4 to +80 V; gain 100 mV/A; system gain error 0.4 % max; IQ 2.4 mA max; VS 2.7-5.5 V; output set to VS/2 with REF1 to VS and REF2 to GND (SLOS954A p.1 features, section 8.4.5) | Pack current monitor |
| U_G | TI UCC27517DBV (SLUSAY4D) | VDD 4.5-18 V; UVLO VON 3.91-4.5 V; VIN_H 2.2 typ / 2.4 V max, VIN_L 1.0 min / 1.2 V typ, independent of VDD; output held low in UVLO and with inputs floating (p.1 features; Electrical Characteristics) | S_BYP gate driver |
| Q_D, Q_F30, Q_F31 | 2N7002-class 60 V NFET | Ratings TODO(verify: vendor data sheet before ordering); Q_D needs >= 30 V VDS and >= 70 mA | Charger-input drain; feed cuts |
| R_D | 330 Ohm, 2 W | 16 V^2 / 330 = 0.78 W, 22.13 V^2 / 330 = 1.48 W if stuck on at the chopper clamp | Drain load |
| R_BL | 10 kOhm, 0.25 W | 21.4 V^2 / 10 k = 46 mW at the regen peak; 1.6 mA of bus current in an FC window | `VCHG-IN` bleed |
| F1 | Pack-lead fuse, mandatory | Ag105 DS V1.1 Figs. 4, 9, 10 (pp.7, 15, 16) recommend a 10 A slow-blow fuse in the battery lead; interrupting rating must exceed the 120-420 A prospective pack current (`facts_prior.md` section 9). F1 protects the wiring only; it does not protect D-BT-SQ (U_OCD does). Part TODO(verify: fuse vendor) | Pack short protection |
| F2 | 3 A fast-acting fuse in the Ag105 VBat- lead | Below the Ag105 I_DIS of 4 A maximum (DS p.20 row 6), above the 1.45 A charge trip at code 5 (set + 200 mA, DS p.18). Its resistance is part of the reverse-share ballast (section 4.6). Part and resistance TODO(verify: fuse vendor) | Ag105 discharge-path protection |
| R_PV1/R_PV2 | 22.1 kOhm / 10 kOhm, 0.1 % | Full scale 3.3 x 32.1 / 10 = 10.59 V; load 0.26 mA at 8.4 V | PACK_VOLTAGE |
| R_V1/R_V2 | 100 kOhm / 14.7 kOhm, 0.1 % | Threshold 1.242 x 114.7 / 14.7 = 9.69 V nominal; 9.43-9.96 V over the reference spread (section 4.7) | Veto divider |

### 2.2 Gate-drive scheme

S_BYP is a low-side NFET with its source on PCB GND, so its gate is referenced to the same ground as the Teensy. U_G
is powered from `VCHG` (pack positive, 7.4-8.5 V operating) through 10 Ohm and 1 uF. The gate therefore swings to
7.4-8.4 V, between the 4.5 V and 10 V RDS(on) test points. This dossier uses the 4.5 V maximum, 1.35 mOhm, as the
conservative figure. No rail above `VBUS` is needed, because no new high-side switch is added.

D-BT-SQ needs no external gate drive; the RT1987 drives its own internal MOSFET from its CAP charge pump. The RT1987
is supplied from VIN, which is now pack positive, so it stays above its 3.0-3.35 V UVLO in every state where the pack
is connected.

### 2.3 Fail-safe defaults

Table 3 lists the default of each control line and the passive part that sets it.

Table 3. Fail-safe defaults.

| Line | Passive default | Value | Result with the GPIO high-Z |
|---|---|---|---|
| D-BT-SQ EN | R_PD on the veto board and R_PD2 at the EN pad end | 10 kOhm each (whether the OQ-7 bodge already exists on this net is unknown: the `.brd` signal `D-BT-SQ` has no resistor) | D-BT-SQ off, also with an open EN flying lead |
| S_BYP gate | U_G held low on a floating input (SLUSAY4D) plus R_GS | 10 kOhm | S_BYP off |
| Q_D gate | Gate to GND | 100 kOhm | Drain off |
| Pins 35 and 21 test inject | BAT54 reverse-biased | n/a | Comparator inputs unloaded |
| Pins 30, 31 (charger feeds) | Existing 10 kOhm bodges behind the new 1 kOhm series resistors | OQ-7 | Charger input off |

The Teensy pad keeper is weak (PJRC, `facts_board.md` section 7.3); a 10 kOhm pull-down dominates it. Firmware must
still drive pins 21, 32, 33 and 35 LOW first in `setup()`.

## 3. Teensy pins and control sequences

### 3.1 Pin allocation

Table 4 lists the pins. All new pins are on the CSV-free list (`facts_board.md` section 7.2). Pin 32 keeps its
number but changes its meaning, which requires a CSV amendment by the operator. After this allocation only pin 20
remains free, and it stays reserved for WDOG1_B (`facts_prior.md` section 5).

Table 4. IC3 pin allocation.

| Pin | Proposed code name | Direction | Function |
|---|---|---|---|
| 32 | `BT_SEQUENCE_ENABLE` (CSV meaning changes to "pack-to-board switch") | OUT | D-BT-SQ and, through U_G, S_BYP |
| 34 | `PACK_SW_SENSE` | IN | EN net after the pull-downs (LOW while pin 32 HIGH means veto or U_OCD active) |
| 10 | `SBYP_GATE_SENSE` | IN | S_BYP gate through 22k/10k (7.4-8.4 V gate reads 2.3-2.6 V) |
| 35 | `VETO_TEST` | OUT | Veto self-test inject |
| 22 | `VETO_SENSE` | AIN | U_V IN- node (veto divider and `VCHG-IN` lead continuity) |
| 21 | `CHG_OC_TEST` | OUT | U_OCC self-test inject |
| 23 | `PACK_CURRENT` | AIN | U_P output through 10k/10k: 1.25 V at 0 A, 50 mV/A, charge positive |
| 33 | `CHG_IN_DRAIN` | OUT | Q_D, charger-input drain after a window |
| 16 | `PACK_VOLTAGE` | AIN | Pack positive (`VCHG`) against GND |
| 17 | `PACKN_VOLTAGE` | AIN | `PACKN` against GND, biased to mid-scale: V_pin = (V_PACKN + 3.3) / 2, clamps to GND and 3.3 V, resolution about 1.6 mV of `PACKN` per count at 12 bits |

### 3.2 Sequences

Each sequence below lists the steps in order, with the ordering rationale. The back-feed rule of CLAUDE.md section 2
(a disabled TPS61288 must never sit behind a path that regen can reach) is satisfied in every step because D-BT-EN
blocks reverse current and is opened before the BT boost is disabled. No charge window of either type may open
unless the MCU watchdog is configured and its forced-hang test T-W-01 has passed (X9; `facts_prior.md` section 7).

**Boot (`setup()` and bring-up P0).**

1. Drive pins 21, 32, 33 and 35 LOW, and all existing path switches LOW (as today, ino:6709-6715).
2. Require `V_chg` (pin 38) below 1 V, `VETO_SENSE` (pin 22) below 0.15 V, `PACK_VOLTAGE` inside 7.4-8.5 V, and
   `PACK_CURRENT` inside +/-0.5 A of zero.
3. D-BT-SQ short test, before P0 while the bus is dark: with pin 32 LOW and BT_REG LOW, `V_batt` (pin 25, now `VBT`)
   must fall below `PACK_VOLTAGE` minus 2.0 V within 1.5 s (`VBT` decays through R1-BT/R2-BT 26.2 kOhm and 20.1 uF,
   tau about 0.53 s). On failure, latch `ERR_DBTSQ_SHORT`.
4. Veto self-test: set pin 35 HIGH first, then pin 32 HIGH. Pin 34 must read LOW and pin 10 must stay LOW for 2 ms.
   Because the inject is asserted before pin 32 rises, the EN net never rises above the veto low level, whatever the
   RT1987 tD_ON minimum is. On failure, set pin 32 LOW and latch `ERR_VETO_SELFTEST`.
5. Set pin 35 LOW with pin 32 still HIGH. Pin 34 must return HIGH; D-BT-SQ then closes. Require pin 10 HIGH within
   3 ms and `V_batt` within 0.3 V of `PACK_VOLTAGE` within 30 ms.
6. Run the existing P0-P3 bring-up unchanged. P0 now reads `PACK_VOLTAGE` in its gate in place of `V_batt`.

**Idle (State 1).** D-BT-SQ and S_BYP on; REGEN and FC_CHARGE LOW; the bus and `MOT_PWR_ENABLE` as today. The
continuous checks of section 8.1 item 4 run in every state.

**Run discharge (State 2).** As Idle. A continuous-current budget on the BT channel limits the D-BT-SQ dissipation
(section 4.1). `OC_BT` and every IC3 interlock are compiled into every build, BENCH_TEST included.

**Common window entry (regen or FC).** Steps 1-9 are shared by both window types.

1. Preconditions: FC_BUS conducting and out of blanking, because the bus becomes FC-only; no purge predicted within
   the window length plus 200 ms (ruling 6); the FC budget of section 4.4 holds, including traction; the watchdog is
   armed. If the battery-only selector holds FC off the bus, the window is refused for this event.
2. Motoring interlock on: the motor command is clamped to `<= 0` from this step until exit step 7.
3. `BT_BUS_ENABLE` LOW. Reason: remove the BT channel from the bus before its input loses its source.
4. `BT_REG_ENABLE` LOW. Reason: the boost must not drain `VBT` while it is unsourced, and its path to the bus is
   already open.
5. Veto functional test: pin 35 HIGH. Pin 34 must read LOW within 1 ms (the veto, not pin 32, has opened D-BT-SQ);
   otherwise abort the window and latch `ERR_VETO_SELFTEST`. This test is safe in this position because BT is already
   off the bus and the next step opens D-BT-SQ anyway.
6. Pin 32 LOW, then pin 35 LOW. S_BYP opens 1.0-1.2 ms later.
7. Require pin 34 LOW and pin 10 LOW within 3 ms; otherwise abort through the exit sequence and latch
   `ERR_PACKSW_MISMATCH`.
8. Charge over-current test for the feed about to open: pin 21 HIGH, then the feed pin HIGH. For 15 ms, `V_chg` must
   stay below 1 V (Q_F30 or Q_F31 holds the feed EN low). Then pin 21 LOW; the feed opens after its tD_ON. On failure,
   drive the feed pin LOW and latch `ERR_CHG_OC_SELFTEST`.
9. Once `V_chg` exceeds 11.0 V: `VETO_SENSE` must equal `V_chg` x 14.7 / 114.7 within +/-10 %, otherwise abort and
   latch `ERR_VETO_SENSE` (open R_V1, open flying lead or drifted divider).

**Regen brake window (State 2, `current < -0.1`).** The common entry with REGEN (pin 30) as the feed. Because
`MOT_PWR_ENABLE` stays closed (Death-5 doctrine), V-MOT sits at `VBUS` between pulses, and the Ag105 draws from the
FC-only bus through D-MT-EN and D-BC-RG for the whole window. A regen window is therefore an FC charge window with
occasional motor-fed pulses, and the FC budget applies to it in full. The window is held for the whole brake event,
including the 0.535 s VESC re-pulse interval, with the existing anti-chatter dwells (`facts_prior.md` section 10
item 13).

**FC-charge window (State 2, standstill or very light traction).** The common entry with `assertFcChargeEnable(true)`
as the feed. `assertFcChargeEnable()` gains three preconditions: pin 32 LOW, pin 34 LOW and pin 10 LOW. `pollAg105()`
configures the module lazily as today. The Ag105 code is 5 (1.25 A) until the efficiency at 16 V in, 2S is measured
(section 4.4). The window closes 200 ms before the next predicted purge, at `FC_CHG_MAX_MS`, or on any abort, through
the exit sequence.

**Window abort conditions (checked every loop iteration in a window).** Any of the following starts the exit
sequence at once: I_fc above 1.20 A (the existing raw arm-drop level); a positive motor command request held for
more than 100 ms (traction wanted); `PACK_CURRENT` and Ag105 reg 0x06 disagree by more than 0.3 A for 100 ms after
the first valid reg 0x06 reading; a `V_fc` dip that the purge predictor did not forecast; U_OCC tripped.

**Window exit, Finish (State 3) and abort.**

1. `REGEN_ENABLE` LOW (or FC_CHARGE off through `assertFcChargeEnable(false)`).
2. Pin 33 HIGH until `V_chg` reads below 6.0 V, timeout 100 ms (fault on timeout); then pin 33 LOW.
3. If the window lasted at least 0.6 s, require `V_batt` (`VBT`) below `PACK_VOLTAGE` minus 2.0 V (healthy `VBT`
   decays with tau 0.53 s); otherwise latch `ERR_DBTSQ_SHORT`. This makes every long window a D-BT-SQ short test.
4. Pin 32 HIGH. Require pin 34 HIGH and pin 10 HIGH within 3 ms.
5. Wait for `V_batt` within 0.3 V of `PACK_VOLTAGE` (tD_ON 8 ms plus about 1 ms ramp).
6. `BT_REG_ENABLE` HIGH; wait the TPS61288 soft start, 3 ms typical (SLVSFP3C section 7.5, TSS).
7. Guarded BT_BUS re-close through the existing latch path (8 ms tD_ON, 30 ms blanking). The motoring interlock is
   released when BT_BUS conducts and is out of blanking.

**H-20 purge.** In Run, Idle and Finish, D-BT-SQ is on and the purge is carried by the pack exactly as today. No
window may overlap a predicted purge. An unpredicted purge inside a window is not survivable: the exit sequence needs
about 25-35 ms plus the drain before BT_BUS conducts, while the bus falls at about 2.57 V/ms (`facts_prior.md`
section 7). The result is a `UV_BUS` latch, which is safe but ends the run.

**State 99.** The teardown is re-ordered so that the pack is isolated before any drain powers the charger, and the
veto is a backup on this path, not the mechanism.

1. Phase 0a: motor command 0; `FC_BUS_ENABLE` and `BT_BUS_ENABLE` LOW; `BT_REG_ENABLE` LOW; pin 32 LOW.
2. Phase 0b: wait until pin 34 and pin 10 both read LOW, timeout 3 ms.
3. Phase 0c: skip both drains if the readback failed, or if the latch cause is `ERR_OV_BATT`, `ERR_DBTSQ_SHORT`,
   `ERR_PACKSW_MISMATCH`, `ERR_VETO_SELFTEST`, `ERR_VETO_SENSE`, `ERR_PACK_OC` or `ERR_SBYP_OPEN`. `VBUS` is then
   left to decay through its own loads. Otherwise run the existing VBUS and V-MOT drains (ino:8299-8327) into a
   charger that now regulates the pack current through its sense.
4. Phase 2 as today, with pin 32 left LOW while latched. The latched board has an unsourced `VBT` and a dark BT
   boost; the Teensy stays powered from the pack positive. This replaces today's rule that BT_SEQUENCE_ENABLE stays
   HIGH in State 99.

**Teensy reset or brown-out.** All GPIOs go high-Z. D-BT-SQ, S_BYP, Q_D and both charger feeds open through their
pull-downs. The bus collapses because the BT boost loses its input and the share switches open. The Teensy keeps
its supply from the pack positive and reboots into the boot sequence.

**Teensy hang.** The outputs hold until the watchdog acts. In a charge window, the charger keeps charging; its
current is regulated by the restored sense and bounded by U_OCC, and no loop exists. In Run, U_OCD bounds the D-BT-SQ
current in hardware. The watchdog is a precondition of every window (above), not future work.

## 4. Quantitative checks

### 4.1 Conduction loss and D-BT-SQ thermal limit in Run

The BT boost input current at the production `OC_BT` limit (3.0 A bus-side, single sample, ino:2155) is
I_in = V_bus x I_bus / (eta x V_BT). Table 5 evaluates it at the TPS61288 headline efficiency of 96.9 % at 7.2 V to
16 V, 2.5 A (SLVSFP3C p.1) and at an assumed 93 % with a sagged input. In the worst case `VBT` is the 7.4 V pack floor
minus the drop across the pack resistance (24 mOhm, UNCONFIRMED), the lead, D-BT-SQ, S_BYP and the shunt, which gives
about 6.8 V at 7.6 A.

Table 5. BT boost input current at I_bus = 3.0 A, V_bus = 16.0 V.

| Case | eta | V_BT | I_in |
|---|---|---|---|
| Nominal | 0.969 | 7.4 V | 6.69 A |
| Worst, self-consistent sag (UNCONFIRMED eta) | 0.93 | 6.8 V | 7.59 A |

The design value is therefore 7.6 A, 95 % of the RT1987 8 A continuous rating. The pack lead additionally carries the
logic current, about 0.2 A (BENCH), so the pack current reaches about 7.8 A. Table 6 lists the conduction loss of each
series element at 7.6 A.

Table 6. Added conduction loss at 7.6 A.

| Element | Resistance | Loss | Source |
|---|---|---|---|
| D-BT-SQ | 20 mOhm typ at 25 C; 28 mOhm hot (x1.4, UNCONFIRMED, no maximum given) | 1.16 W / 1.62 W | RT1987 DS-00 Table 13 p.7 |
| S_BYP | 1.35 mOhm max at VGS 4.5 V; 2.0 mOhm hot (x1.5, UNCONFIRMED) | 0.08 W / 0.12 W | BSC010N04LSC Table 4 |
| U_P shunt | 2 mOhm (4.5 mOhm package total) | 0.12 W / 0.26 W | SLOS954A section 9 layout notes |
| New pack lead and lug | about 5 mOhm (UNCONFIRMED, length-dependent) | about 0.29 W | Estimate |

**The D-BT-SQ exposed pad has no thermal copper on this board.** RT1987 DS-00 section 8 (pin 13) requires the exposed
pad, which is the common-drain node, to be soldered to a large isolated pad tied to as much copper as possible with
many vias; the 53.05 C/W figure of section 18.3 is valid only for that layout on a four-layer JEDEC board. On this
board pad 13 is on signal `N$32` together with pad 9 (CD) only, with one 0.254 mm top-layer wire and no polygon or via
(`.brd`, signal `N$32`). The board thetaJA of this device is therefore well above 53 C/W; its value is UNCONFIRMED and
can only be measured.

Table 7 shows the junction temperature at 40 C ambient and the input current that holds a 110 C junction target, as a
function of the unknown thetaJA. The bus-side equivalent uses eta 0.95 and V_BT 7.2 V.

Table 7. D-BT-SQ junction temperature and continuous-current cap versus thetaJA.

| thetaJA | TJ at 7.6 A, 20 mOhm | TJ at 7.6 A, 28 mOhm | I_in for TJ = 110 C at 28 mOhm | Bus-side cap |
|---|---|---|---|---|
| 53.05 C/W (JEDEC four-layer, not this board) | 102 C | 126 C | 6.9 A | 2.9 A |
| 80 C/W | 133 C | 170 C | 5.6 A | 2.4 A |
| 120 C/W | 179 C | 234 C | 4.6 A | 1.95 A |
| 160 C/W | 226 C | 299 C | 4.0 A | 1.7 A |

At the `OC_BT` limit the device reaches its 140 C OTP threshold for any thetaJA above about 62 C/W at 28 mOhm. Because
the OTP is a latch, an OTP event in Run removes the BT channel until firmware toggles EN. The 20 A, 10 ms peak rating
covers boost load steps but not sustained operation.

The firmware therefore enforces an I^2t budget on the BT bus current whose limit is set from gate G-T1, with the
3.0 A single-sample `OC_BT` limit unchanged and compiled into every build. G-T1 is the first kill gate of this concept.
If G-T1 measures a cap below about 2.0 A bus-side, IC3 loses about one third of today's BT capability, against
recorded I_batt peaks of 2.345 A (TP0053) and 3.586 A (TP0010) (`docs/HIL_REPLAY_LOGS.md` section 3b-ter) and against
the battery-only selector default at Run entry and light load. The fallback is to replace D-BT-SQ by an external
low-RDS(on) back-to-back NFET pair with its own high-side drive; that fallback is concept IC4 in substance.

Two copper bottlenecks are addressed by rework. The existing 1.524 mm `VBT` branch to D-BT-SQ (17.4 mm, 1 oz) has
about 1.72e-8 x 0.0174 / (1.524e-3 x 35e-6) = 5.6 mOhm and would dissipate 0.32 W at 7.6 A; the new preformed lug or
flat braid from the D-BT-SQ output pour to J-BT pin 1 bypasses it and adds copper near the package. The pack lead
lands on the `VCHG` pour next to the D-BT-SQ VIN pads for the same reason. Neither addition reaches the exposed pad.

### 4.2 Safe operating area and inrush

1. **D-BT-SQ re-close, warm.** After the LM1084 feed is cut, the capacitance on `VBT` is C1-BT 10 uF + C2-BT 0.1 uF +
   C-D12 10 uF = 20.1 uF nominal (SCH net `VBT`; BOM). `VOUT-BT` stays charged near 16 V behind the open D-BT-EN, so
   the boost body diode is reverse-biased. At the 12 V/ms slew of CSS 5.6 nF (RT1987 DS-00 section 17.3,
   tON = 12.4 x VIN x (CSS - 0.23) us) the inrush is 20.1 x 12 mA = 0.24 A, below the 2.5 A SCP start limit (section
   17.5). After a long window `VBT` has decayed (exit step 3), so the ramp is the full pack voltage.
2. **D-BT-SQ close, cold (boot).** If `VOUT-BT` is discharged, the ramp also charges C4A/B/C-BT 3 x 22 uF and C-D3
   10 uF through the disabled boost's body diode: 96.1 uF x 12 mA/uF = 1.15 A, also below 2.5 A. BT_BUS is LOW
   during this ramp, so `VBUS` capacitance is not in the path.
3. **D-BT-SQ after soft-start.** The SCP is disabled after tON (RT1987 DS-00 section 17.5), and the TPS61288 input can
   draw up to its 12-17.1 A switching peak current limit (SLVSFP3C Electrical Characteristics, ILIM). U_OCD bounds the
   pack current at 8.3 A nominal (section 4.8), independently of firmware and of the build flags. Its effect depends on
   the RT1987 EN-low turn-off time, which the data sheet does not give (TODO(verify: Richtek)).
4. **S_BYP.** It switches with near-zero drain-source voltage, because D-BT-SQ has already stopped the discharge
   current or has not yet started it. Its SOA is not stressed. The only exposure is the reverse current through the
   Ag105 branch between the two edges (section 4.6). Because tD_ON has no specified minimum, the 6 ms gap between
   S_BYP closing and D-BT-SQ conducting is a typical figure.
5. **Charger input.** The `VCHG-IN` inrush is unchanged from today (H8 of the charger study applies unchanged).
6. **TRCB chatter.** The pack lead inductance and the 10 uF C-D11 now sit upstream of D-BT-SQ. A fast boost load step
   could pull `VCHG` below `VBT` by 50 mV and trip the fast reverse comparator. The TPS61288 runs in PFM/DCM at light
   load (SLVSFP3C section 8.4.2), so the boost does not reverse current into `VBT`; the risk is limited to
   lead-inductance transients (gate G-T2). If G-T2 fails, the mitigation is added bulk capacitance with damping ESR on
   `VCHG` (an electrolytic or polymer part), not ceramics alone, because a hard pack plug-in onto a large ceramic bank
   rings (section 4.9).

### 4.3 Timing against the regen burst and the Ag105 Bring-Up

Table 8 lists the latency of each step of a regen window entry and exit.

Table 8. Regen window timing.

| Step | Latency | Source |
|---|---|---|
| Brake detection (`chargingControl()` at 50 Hz) | up to 20 ms plus one motor period | `facts_firmware.md` section 8 |
| BT_BUS LOW, BT_REG LOW, veto test, pin 32 LOW | about 1 ms; D-BT-SQ EN-low turn-off time TODO(verify: Richtek) | ino `digitalWrite`; entry steps 3-6 |
| S_BYP off after EN falls | tau x ln(2.75 / 1.0) = 1.01 ms (pin 32 LOW); tau x ln(2.55 / 0.8) = 1.16 ms (veto at 0.2 V); tau = 1 ms | SLUSAY4D VIN_L 1.0 V min |
| Charge over-current test | 15 ms | Entry step 8 |
| D-BC-RG tD_ON plus ramp to about 16-21 V | 8 ms + about 1.5 ms | RT1987 DS-00 Table 13 |
| Ag105 start to charge current | not specified; prior cold-start estimate 65-170 ms; firmware settle 500 ms (`TODO(calibrate)`) | `facts_ag105.md` section 6; `facts_prior.md` section 6 |
| First regen pulse duration | 19-47 ms to the VESC trip at about 21.35 V | `facts_prior.md` section 6 |
| Second pulse | 0.523-0.562 s later | `facts_prior.md` section 6 |
| Exit: `VCHG-IN` drain from 21.4 V to 6.0 V | tau = (330 Ohm parallel 10 kOhm) x (20 uF + C_Ag105,in) = 6.4 ms with C_Ag105,in = 0; 6.4 ms x ln(21.4 / 6.0) = 8.1 ms; C_Ag105,in TODO(verify: Silvertel) | C-D8, C-D10 (SCH) |
| Exit: D-BT-SQ re-close | 8 ms + about 1 ms | RT1987 DS-00 |
| Exit: BT boost soft start | 3 ms typical | SLVSFP3C section 7.5 |
| Exit: D-BT-EN re-close and blanking | 8 ms + 30 ms blanking | ino:4869, 4875 |

The window entry puts charger power on the input about 25 ms after the decision, but the charger start-up is far
longer than the first pulse. The first pulse is therefore always lost, and only a second pulse 0.535 s later can be
caught, and only if the cold start is shorter than that interval. The exit returns the pack to the bus about 30-40 ms
after the decision, plus the drain time; IC1 and IC2 need only a BT_BUS re-close. The bus is FC-only for the whole
window plus this exit.

The ML0227 Bring-Up slope (0.64 V/s) does not apply to IC3. That ramp was into an open `VCHG` node with the sense
shorted. In IC3 the pack is always present on VBat+ and the sense is in the return, so detection should see a
battery immediately (UNCONFIRMED; gate G-A2 measures the time from input arrival to first charge current).

The probability that an unscheduled purge (100-140 ms every 10.34 s) overlaps a regen window of 0.35-0.67 s is
(0.45 to 0.81) / 10.34 = 4.4-7.8 % per event. The purge-schedule precondition is therefore mandatory, and the regen
windows it refuses are lost harvest.

### 4.4 FC-window budget, traction and throughput

The Ag105 input power during a window is the pack charge power plus the logic load, both divided by the module
efficiency. The logic load now hangs on `VCHG`, so the Ag105 supplies it, unregulated, on top of the regulated pack
current (`facts_ag105.md` section 1.4, UNCONFIRMED). Table 9 evaluates the bus current at V_bus = 15.9 V, a CV-end pack
voltage of 8.4 V, an assumed logic load I_5V = 0.2 A (BENCH) and an aux load of 0.15 A. The traction headroom column is
the difference to the 1.25 A governor ceiling; the H-20 P_MAX of 1.247 A bus-side is the same limit to 0.2 %.

Table 9. FC-window bus current and traction headroom.

| Ag105 code (Table 4 JSON) | I_chg | eta | P_in | I_bus incl. aux | Traction headroom to 1.25 A |
|---|---|---|---|---|---|
| 1 | 2.5 A | 0.88 | 25.8 W | 1.77 A | None (fails) |
| 4 | 1.5 A | 0.88 | 16.2 W | 1.17 A | 0.08 A (1.3 W) |
| 4 | 1.5 A | 0.80 | 17.9 W | 1.27 A | None (fails) |
| 5 | 1.25 A | 0.88 | 13.8 W | 1.02 A | 0.23 A (3.7 W) |
| 5 | 1.25 A | 0.80 | 15.2 W | 1.11 A | 0.14 A (2.2 W) |

The 88 % efficiency is specified only at 12 V in, 3S (Ag105 DS V1.1 p.20 note 2). Code 5 is therefore the starting
value, and code 4 requires a measured efficiency of at least about 0.85 at 16 V in, 2S (gate G-A3). This also changes
the CLAUDE.md section 3 rule "write 0x01 to register 0x00", which needs an operator ruling. A single code serves both
window types, so no per-window EPROM write is needed. The cost is that regen above about 13.8 W of charger input (the
18.9 W peak of a 3 to 1 m/s brake) is clipped.

With 0.14-0.23 A of headroom, **FC windows are standstill or very-light-traction windows**, consistent with
`facts_prior.md` section 7. The entry precondition is a filtered bus-side traction estimate below 0.1 A for 1 s, and
the motoring interlock plus the I_fc abort of section 3.2 hold the budget inside the window. Regen windows carry the
same FC draw between pulses, so the same budget and the same interlock apply.

Each window is a fresh charger power session, because the pack must be back on the bus before every purge and the
veto forbids a powered charger while it is. Per 10.34 s purge interval the following time is lost to charging: the
purge itself (0.10-0.14 s), the 0.2 s guard, the entry (about 0.025 s), the cold start (0.065-0.17 s) and the exit
(about 0.045 s). That is 0.44-0.58 s, or 4-6 % of the interval, if the Ag105 charges while `MPPT_DISABLE` is LOW. If
charging waits for the firmware's 500 ms settle and 1000 ms MPPT-release holdoff, the loss rises to 1.9-2.1 s, or
19-20 %. Which applies depends on the unverified meaning of `MPPT_DISABLE` during charging (TODO(verify: Silvertel)).

In addition, the Ag105 reports Fully Charged without charging when a battery is within 0.2 V/cell of the setting, and
restarts only 0.2 V/cell below it (DS V1.1 p.5, p.6, p.11). With 8.4 V set and the pack directly on VBat+, no window
charges a pack resting at or above about 8.0 V, which is the upper 40 % of the 7.4-8.4 V operating window. This rule
applies to every concept that powers the Ag105 per window.

### 4.5 Teensy supply continuity

The LM1084 input moves from `VBT` to `VCHG`. Table 10 compares the feed options.

Table 10. LM1084 feed options.

| Feed | Minimum input | Headroom to 5 V + 1.5 V dropout max (SNVS037H section 5.5) | Dissipation at I_5V = 0.2 A | Verdict |
|---|---|---|---|---|
| `VCHG` direct (selected) | 7.2 V at the 7.4 V pack floor with 24 mOhm x 7.8 A of pack sag | 0.7 V | (8.4 - 5) x 0.2 = 0.68 W, as today | Selected |
| Diode-OR `VCHG` + `VBUS` | 7.0 V after a 0.4 V Schottky (UNCONFIRMED drop) | 0.5 V | (16 - 0.4 - 5) x 0.2 = 2.1 W; at RthJA 40.4 C/W (SNVS037H section 5.4, KTT) the rise is 86 C | Rejected |

With the selected feed, the Teensy is powered in every state in which the pack is connected: Run, every charge window,
State 99, Teensy reset and a D-BT-SQ fault. It loses power only if the pack, F1 or the pack protection circuit opens,
which matches today's behaviour.

While S_BYP is off and the Ag105 is not supplying `VCHG` (boot before step 5, window entry before the charger starts,
State 99 latched), the logic current returns from GND to the pack negative through the Ag105 branch in the reverse
direction, or through the S_BYP body diode if that branch has a high resistance. VBat- may then sit up to one body-diode
drop (0.5-1.0 V) below Vin-. The Ag105 tolerance of that condition is not given (TODO(verify: Silvertel); gate G-A6).

### 4.6 Reference shifts and the reverse share in Run

Table 11 lists every measurement whose reference moves, and the size of the shift.

Table 11. Reference shifts.

| Measurement | Reference after rework | Shift in Run (S_BYP on, 7.6 A) | Shift in a charge window (S_BYP off, I_chg) |
|---|---|---|---|
| `V_batt` (pin 25) | Now reads `VBT`, not the pack | Pack minus 0.15-0.21 V (D-BT-SQ drop) | Decays to near 0 V (unsourced); D-BT-SQ-short detector (exit step 3) |
| `PACK_VOLTAGE` (pin 16) | Pack positive against GND | Under-reads by the return-path drop, about 15 mV | Over-reads by I_chg x R_A; corrected by `PACKN_VOLTAGE` |
| `PACKN_VOLTAGE` (pin 17) | `PACKN` against GND, bipolar | -I x R_ret, about -15 mV with the lug; an open S_BYP gives -0.1 to -1.0 V | +I_chg x R_A, a pack-return continuity check |
| `PACK_CURRENT` (pin 23) | Total pack current, sign charge-positive | Measured | Measured, independent of the Ag105 sense |
| INA253 `I_fc`, `I_batt` | Unchanged (boost outputs, PCB GND) | None | None |
| BQ29200 bottom cell (VC1 to GND) | J-BL pin 3 removed; BAL GND stays PCB GND | Under-reads cell 1 by the return drop, 15-20 mV | Over-reads cell 1 by I_chg x R_A, so OVP trips early (safe direction); OUT is unconnected anyway |
| Ag105 reg 0x06 | Restored: reads the pack charge current | Reverse share (not reported) | Correct; cross-checked against `PACK_CURRENT` |

The Ag105 branch in Run is in parallel with the S_BYP branch between `PACKN` and GND. Its resistance R_A is the sum of
F2, the 20 AWG lead (about 33 mOhm/m, about 5 mOhm at 0.15 m, UNCONFIRMED length), the module-internal sense or its
parallel switch (R_s, not published) and the Vin- joints. The S_BYP branch resistance R_B is S_BYP (1.35 mOhm max) plus
its two soldered source leads (about 0.5-1 mOhm, UNCONFIRMED). The share through the module is
I x R_B / (R_A + R_B). Table 12 evaluates it at 7.6 A.

Table 12. Reverse share through the Ag105 branch at 7.6 A.

| S_BYP source landing | R_B | R_A | Share |
|---|---|---|---|
| Through the J-BT screw contact (TB005-762, 20 mOhm maximum contact resistance, CUI/Same Sky TB005-762 p.1) | 21.4 mOhm | 5 mOhm (R_s = 0, no F2) | 6.2 A, above I_DIS 4 A: rejected |
| Soldered leads on the J-BT pin-2 pad (selected) | 2.0 mOhm | 5 mOhm (R_s = 0, no F2) | 2.2 A |
| Soldered leads (selected) | 2.0 mOhm | 25 mOhm (with F2 and lead, R_s = 0) | 0.56 A |

The datasheet places the battery on VLoad whenever the module is not charging (DS p.9) and gives a battery standby
current of 120-420 uA with no input (DS p.20 row 7). The module is therefore battery-powered in Run, and the internal
switch drawn in parallel with the sense (DS Fig.1 p.3) is plausibly closed in Run (UNCONFIRMED). R_A is therefore taken
with R_s = 0 in Table 12. The selected landing keeps the share below 4 A in every case and near 0.6 A with the F2
ballast; the I_DIS rating of 4 A (DS p.20 row 6) applies to this direction, because it is the module's own load
discharge direction. Gate G-A6 measures the share in circuit in the Run state. If it exceeds 1 A, the fallback is a
low-side ideal-diode element in the VBat- lead that passes charge current and blocks the reverse share (the DS-2 pair
of the brainstorm).

### 4.7 Veto threshold, leakage and bleed

The veto threshold must sit above any `VCHG-IN` voltage that can occur while the pack is legitimately on the bus, and
below the input voltage at which the Ag105 can start delivering charge. Table 13 lists both bounds.

Table 13. Veto threshold window.

| Bound | Value | Source |
|---|---|---|
| Lower: highest pack voltage | 8.70 V (BQ29200 OVP, 4.35 V/cell) | `facts_prior.md` section 5 |
| Lower: worst off-state leakage into `VCHG-IN` | 2 x 105 uA (ISHDN maximum of D-BC-FC and D-BC-RG) x 8.33 kOhm = 1.75 V | RT1987 DS-00 Table 13 p.7; by KCL the current that leaves VOUT of a disabled RT1987 cannot exceed the current that enters VIN |
| Selected threshold | 9.69 V nominal; 9.43-9.96 V over the reference spread; hysteresis 2-8 mV x 7.80 = 16-62 mV | SBOS300C sections 6.7-6.9 |
| Upper: Ag105 input lockout | V_LOCK 11 V typical, no minimum given | Ag105 DS V1.1 p.19 row 2; TODO(verify: Silvertel) |
| Upper: Ag105 measurement validity | Measurements read 0xFF below 9 V input | Ag105 DS V1.1 p.14 |
| Second, soft barrier | Charging starts only above the reg 0x02 MPPT threshold, which fw v24 clamps to 12.32-13.38 V | CLAUDE.md section 3 |

The margin is 0.73 V above the pack maximum and about 1.0 V below the typical Ag105 lockout. Because the lockout has
no specified minimum, gate G-V3 measures the lowest input voltage at which this module delivers any output current.

Without a bleed, the only load on `VCHG-IN` is R1-CHG/R2-CHG (88.7 kOhm) in parallel with the veto divider
(114.7 kOhm), about 50 kOhm, so 210 uA of leakage could hold the node at 10.5 V and veto D-BT-SQ in Run. R_BL 10 kOhm
reduces the node resistance to 8.33 kOhm and the worst leakage voltage to 1.75 V. A back-feed from VBat+ through the
module to Vin+ would need more than 1.1 mA to reach 9.43 V; gate G-A6 measures it.

### 4.8 Pack current monitor

U_P sits in the pack-negative lead, upstream of the split into the S_BYP and Ag105 branches, so it reads the total
pack current in both directions. With REF1 at VS (5 V) and REF2 at GND the output is V_P = 2.5 V + 0.1 V/A x I, with
charge positive (SLOS954A section 8.4.5). Both thresholds are taken from the same 5 V rail, so they are ratiometric
to the U_P offset and the 2.7 % spread of the TLV3011 internal reference does not enter. Table 14 lists the two
thresholds.

Table 14. Pack current monitor thresholds.

| Comparator | Threshold node | V_P at trip | Pack current at trip | Action |
|---|---|---|---|---|
| U_OCD | 5 V x 10k / (20k + 10k) = 1.667 V | below 1.667 V | -8.33 A (discharge) | Pulls the D-BT-SQ EN net low (D-BT-SQ and S_BYP open) |
| U_OCC | 5 V x 10k / (8.45k + 10k) = 2.710 V | above 2.710 V | +2.10 A (charge) | Turns on Q_F30 and Q_F31 (both charger feeds open) |

The U_OCD threshold sits above the 7.8 A worst pack current at the `OC_BT` limit, so the firmware trips first in
normal operation; U_OCD acts on a hung Teensy, a missing `OC_BT` or a hard fault. A hiccup follows a U_OCD trip with
a hung Teensy: the current falls, U_OCD releases and D-BT-SQ re-tries after tD_ON with its soft-start current limit
active (UNCONFIRMED behaviour; bench gate G-OC). The U_OCC threshold sits above the 1.45 A Ag105 trip at code 5
(set + 200 mA, DS p.18) and below the F2 rating. Both comparators need an RC filter against boost ripple on the pack
lead; its value is BENCH (gate G-OC). The 0.4 % system gain error of U_P (SLOS954A) moves the thresholds by less than
0.04 A.

U_P does not see a hidden pack-negative bond that leaves the pack upstream of the shunt, for example a balance lead or
a pack thermistor. Such a bond is excluded by the harness audit and continuity gate G-H1, and detected in operation
by the reg 0x06 versus `PACK_CURRENT` cross-check.

### 4.9 Pack plug-in and VBat+ rating

The pack plugs onto `VCHG` permanently, which carries C-D11 10 uF and the RT1987 VIN. The hot-plug ring of the lead
inductance into this ceramic node is not computed (BENCH, gate G-T2). The Ag105 datasheet gives an absolute maximum only
for the DC supply (-0.3 V to 36 V, DS p.19); it gives no rating for VBat+ (TODO(verify: Silvertel)). A plug-in ring
of a 2S pack is unlikely to approach 36 V, but the VBat+ rating is unverified.

## 5. HR1-HR5 status

Table 15 states the status of each hard requirement for IC3 after review round 1.

Table 15. Hard-requirement status.

| ID | Status | Reason |
|---|---|---|
| HR1 Regen harvesting | FAILS | The veto, by design, forbids a powered charger while the pack is on the bus, so every brake starts from a cold Ag105 and the first 19-47 ms pulse is always lost; capture is at best the cold-start fraction (6-40 %, `facts_prior.md` section 6) and needs a clean purge schedule. Between pulses the window draws FC power (section 3.2), so measured "regen" harvest is mostly FC energy. Carried to the operator as a declared failure against ruling 1 |
| HR2 FC charging | BENCH | Budget passes at code 5 only at standstill or below about 0.14-0.23 A of traction (Table 9); every window depends on a purge predictor that does not exist yet (gate G-P1, T-E-01), because the existing `fcUvLockoutActive()` gate refuses windows outright on a running stack (ino:15493-15500); 4-20 % of each purge interval is lost to session overhead and no charge occurs above about 8.0 V |
| HR3 No circular loop | PROVEN_CALC for the topology; BENCH for the veto threshold | `VBT` is unsourced whenever `VCHG-IN` exceeds about 9.7 V, by the hardware veto, and firmware opens D-BT-SQ before any charger feed; the veto is tested before every window and its sense path in every window; a shorted D-BT-SQ alone does not close the loop because BT_BUS and BT_REG are LOW in windows, and it is detected at boot and after every long window; the threshold upper bound rests on gate G-V3 |
| HR4 No runaway | PROVEN_CALC, conditional | The Ag105 sense and its set + 200 mA trip (DS p.18) bound the pack current once VBat- is isolated and S_BYP is off; a shorted S_BYP, a stuck-high U_G or an open sense return is bounded in hardware by U_OCC at 2.1 A on any source; conditional on gate G-H1 (no hidden pack-negative bond) and G-OC |
| HR5 Fail-safe inhibit | BENCH | Reset, brown-out and POR open every charger feed and the pack switch through pull-downs; U_OCC and U_OCD act without the Teensy; a hang is ended by the MCU watchdog, which is a precondition of every window; OQ-7 must confirm the pull-downs (G-S1) and T-W-01 the watchdog (G-W1) |

## 6. Single-fault table

Table 16 lists the single faults considered, their consequences and the detection or bound.

Table 16. Single faults.

| ID | Fault | Consequence | Detection and bound |
|---|---|---|---|
| F1 | D-BT-SQ shorted | Charger output reaches `VBT`; loop needs BT_REG and BT_BUS HIGH as well | Boot test (step 3) and exit step 3 after every window of at least 0.6 s latch `ERR_DBTSQ_SHORT`; `FAULT_SWITCH_CONFLICT` extended to BT_REG/BT_BUS HIGH with FC_CHARGE or REGEN HIGH, in every build |
| F2 | D-BT-SQ open or OTP-latched | BT channel lost in Run; bus FC-only | `V_batt` falls while pins 32, 34 and 10 are HIGH; existing UV_BUS and selector logic; firmware EN toggle once (the OTP is a latch), then fault |
| F3 | S_BYP shorted (drain-source) | Sense bypassed in windows; loop-free charge | U_OCC opens both feeds at 2.1 A within its filter time on any source; reg 0x06 versus `PACK_CURRENT` cross-check latches `ERR_PACK_OC` |
| F4 | U_G output stuck low | Run discharge through the S_BYP body diode and the Ag105 branch | Pin 10 LOW while pin 34 HIGH for more than 3 ms: pin 32 LOW and fault; also F17 |
| F5 | U_G stuck high | Same as F3 in windows | Pin 10 HIGH while pin 34 LOW: refuse or abort the window; U_OCC bound as F3 |
| F6 | R_d or C_d fault | S_BYP edge timing lost | Covered by F4 and F5 checks |
| F7 | Veto comparator dead (output open) | Loop protection reduces to firmware ordering | Pre-window functional test (entry step 5) at every window; boot test |
| F8 | Veto stuck low | D-BT-SQ cannot close; BT channel unavailable | Boot self-test fails; safe |
| F9 | R_PD missing and pin 32 high-Z | D-BT-SQ state undefined during reset | R_PD2 at the pad end and REN_PD 475-985 kOhm; OQ-7 inspection (G-S1) |
| F10 | J-BL pin 3, pack NTC return or a pack-powered accessory bonded to the pack negative | Sense bypassed through the balance lead or accessory; not seen by U_P | Mechanical: pin 3 clamp sealed and labelled; continuity gate G-H1; reg 0x06 versus `PACK_CURRENT` and the G2-style power balance in operation |
| F11 | Pack lead reversed | Ag105 VBat+ and RT1987 VIN driven to -8 V; damage | Keyed connector; no electrical bound (Ag105 has no reversal protection, DS p.18) |
| F12 | Pack shorted on `VCHG` side | 120-420 A prospective | F1 fuse, mandatory (part TODO) |
| F13 | Q_D stuck on | 0.78-1.48 W in R_D during windows | `V_chg` reading; R_D rated 2 W |
| F14 | Teensy hang in a window | Charge continues, regulated, bounded by U_OCC | Watchdog precondition (X9, T-W-01) |
| F15 | Unpredicted purge in a window | UV_BUS latch, State 99 | Safe stop; schedule precondition |
| F16 | Pack protection circuit opens in a window | Ag105 output feeds only the logic load; regulation error and Bring-Up (DS p.11, p.19) | Teensy stays up on the Ag105 output; `PACK_VOLTAGE`, `PACK_CURRENT` and GENSTAT |
| F17 | S_BYP open in Run (channel, joint, lead or harness) with a correct gate | Full discharge return through F2 and the Ag105 branch, then through the body diode when F2 opens | `PACKN_VOLTAGE` below -0.1 V with `PACK_CURRENT` above 2 A discharge latches `ERR_SBYP_OPEN` and drives pin 32 LOW (thresholds BENCH); F2 opens before the 4 A I_DIS is sustained |
| F18 | F2 open or Ag105 VBat- lead open | No charge return (X2); a window would ramp `VCHG` | Window abort: `PACK_CURRENT` stays near 0 while reg 0x06 or `V_chg` shows a powered charger; `OV_BATT` on `PACK_VOLTAGE` as backstop |
| F19 | Veto sense lead or R_V1 open | Veto blind | `VETO_SENSE` ratio check in every window (entry step 9) latches `ERR_VETO_SENSE` |
| F20 | U_OCC dead | Charge bound lost | Pre-window inject test (entry step 8) |
| F21 | U_OCD dead | Discharge hardware bound lost; firmware `OC_BT` remains | Dormant between bench checks (gate G-OC); residual risk recorded |
| F22 | Ag105 Vin- joint open | Ag105 ground floats onto the I2C, STAT and MPPTD lines | Vin- pin 4 stays soldered (no socket), and VLoad- pins 16/17 are bonded to GND as parallel contacts |
| F23 | 5 V rail lost with the Teensy alive (USB-powered bench with VUSB-VIN cut) | Veto and comparators unpowered | Possible only on the bench with the VUSB-VIN pads cut (status unknown, `facts_board.md` section 7); the TLV3011 output state with VS = 0 is UNCONFIRMED; bench rule: no window on USB power |

## 7. Rework on the manufactured board

### 7.1 Steps

The steps below are a procedure for a later bench session. Nothing is to be done during this study.

1. Measure and record the as-found state: OQ-7 pull-downs on all RT1987 EN nets; whether the Teensy VUSB-VIN pads
   are cut; the Ag105 module standoff height.
2. Cut Ag105 pins 14 and 15 above the board, leaving the module soldered in place and the GND barrels unused
   (`facts_board.md` section 4.3; `incident.md` recommends cutting pins rather than desoldering a module with
   solid-connected GND pads). Insulate both barrel stubs. If the standoff is too low to cut the pins, removing the module
   is the fallback.
3. Solder a 20 AWG lead to the module-side stubs of pins 14 and 15. Check that pins 14/15 have no continuity to GND.
4. Bond VLoad- pins 16 and 17 (isolated pads, `facts_board.md` section 4.3) to the nearest GND pour with short wires as
   parallel Vin- contacts.
5. Cut the LM1084 input trace on the `VBT` side so that REG-5V pad 3 and CIN-5V stay together (exact cut point
   TODO(verify: `.brd` signal `VBT` near (57.66, 34.54) to (59.18, 39.57))). Wire the LM1084 input to the `VCHG`
   pour with 22 AWG.
6. Scrape the solder mask on the `VCHG` pour next to the D-BT-SQ VIN pads and solder the 14 AWG pack-positive lead.
7. Solder a preformed lug or flat braid from the D-BT-SQ output pour (30.8-35.0 x 48.3-49.8 mm) to J-BT pin 1, with a
   heat-sink clip on the D-BT-SQ package so that VOUT pins 1/2 do not reflow. Clamp the braid in J-BT pin 1 so that the
   terminal is occupied, and label J-BT "do not connect pack".
8. Cut the 0.254 mm top-layer `D-BT-SQ` trace between (32.258, 51.054) and (32.258, 52.324), wire both ends to the
   veto board, and fit R_PD2 from the pad-side end to the nearest GND.
9. Cut the traces from Teensy pins 30 and 31 to their RT1987 EN nets and insert R_S30 and R_S31, 1 kOhm each, with the
   Q_F30 and Q_F31 drains on the EN side (cut points TODO(verify: `.brd` signals of the two EN nets)).
10. Build the off-board switch board (U_P, S_BYP, U_G, R_GS, F2, the PACKN bias network) in the pack-negative harness:
    pack negative to U_P IS+, U_P IS- to `PACKN`, `PACKN` to F2 and the Ag105 VBat- lead and to the drain. Solder two
    source leads to the J-BT pin-2 pad itself, not into the screw clamp.
11. Build the veto board (U_V, U_OCD, U_OCC, dividers, R_S, R_PD, R_d/C_d, Q_D, R_D, R_BL, Q_F30, Q_F31, both test
    injects, readback dividers) and wire it to J1/J2 pins 10, 16, 17, 21, 22, 23, 33, 34, 35, 5V and GND, and to
    `VCHG-IN` at C-D8.
12. Insulate the pack's balance-lead negative wire; seal the J-BL pin-3 clamp and label it. Audit the harness for
    every other conductor from pack negative to the board or to an accessory (J-NTC, Raspberry Pi supply, USB links).
13. Fit F1 and the keyed connector in the pack-positive lead.
14. Record the rework as a never-rotated hardware bodge record (operator action) and amend the IO CSV rows 10, 16, 17,
    21-23, 30-35 (operator action).

### 7.2 Parts list and cost

Table 17 lists the parts. Only the existing BOM parts have a primary price; the others are TODO.

Table 17. Parts list.

| Qty | Part | Unit price |
|---|---|---|
| 1 | Spare Silvertel Ag105 (in case step 2 damages the module) | USD 14.70 (BOM line 29) |
| 1 | Spare RT1987N-A | USD 1.77 (BOM line 77) |
| 1 | TI INA253A1IPWR | USD 4.03 (BOM line 14) |
| 1-2 | Infineon BSC010N04LSC (or BSC010N04LS) | TODO(verify: distributor) |
| 3 | TI TLV3011B, SOT-23-6 | TODO(verify: distributor) |
| 1 | TI UCC27517DBV | TODO(verify: distributor) |
| 3 | 2N7002-class NFET | TODO(verify: distributor) |
| 2 | BAT54 Schottky (test injects) plus clamp diodes | TODO(verify: distributor) |
| 1 | 330 Ohm, 2 W resistor | TODO(verify: distributor) |
| about 25 | 0.1 % and 1 % resistors, 100 nF / 1 uF ceramics | TODO(verify: distributor) |
| 2 | Fuses with holders: F1 (pack lead) and F2 (3 A, Ag105 VBat- lead) | TODO(verify: fuse vendor) |
| 1 | Keyed pack connector pair, 14/20/22 AWG wire, flat braid, two prototype boards | TODO(verify: distributor) |

The total is UNCONFIRMED. As an order-of-magnitude estimate only, the new parts are likely below USD 60 excluding the
spare module.

### 7.3 Permanent pack drain

With the pack permanently on `VCHG`, the following draw from the pack whenever it is plugged in: the LM1084 and the
Teensy (as today), the Ag105 battery standby current 120-420 uA (DS p.20 row 7), R_PV1/R_PV2 0.26 mA, U_P 2.4 mA
maximum, the three comparators 15 uA maximum, U_G quiescent current (TODO(verify: SLUSAY4D)) and the RT1987 IQ of
D-BT-SQ while enabled (780 uA maximum, Table 13 p.7). The new terms total about 3.9 mA at most, small against the
Teensy load.

## 8. Firmware, telemetry and HIL impact

### 8.1 Firmware

The following changes are needed. Each is a firmware round in its own right and must follow the orchestrated-feature
and self-review practice. Realistically this is three or more rounds.

1. New pin defines and early `setup()` levels for pins 10, 16, 17, 21, 22, 23, 33, 34, 35; boot D-BT-SQ short test
   and veto self-test; new latched errors `ERR_VETO_SELFTEST`, `ERR_VETO_SENSE`, `ERR_CHG_OC_SELFTEST`,
   `ERR_PACKSW_MISMATCH` (pin 34 or pin 10 against the command), `ERR_DBTSQ_SHORT`, `ERR_SBYP_OPEN` and
   `ERR_PACK_OC`. **Every IC3 interlock and `OC_BT` are compiled into every build;** the precedent of compiling
   `FAULT_SWITCH_CONFLICT` and `OC_BT` out of BENCH_TEST builds (ino:7413-7418, 7430) must not apply to them.
2. A single chokepoint `assertPackSwitch(bool)` for pin 32, with the readback checks, the veto test and the
   BT_BUS/BT_REG ordering. `BT_SEQUENCE_ENABLE` stops being "on once, never off" (IO CSV row 32 Notes, CLAUDE.md
   section 2 both change).
3. `assertFcChargeEnable(true)` and the regen branch gain the preconditions pin 32 LOW, pin 34 LOW and pin 10 LOW. The
   regen branch must now drive BT_BUS and BT_REG LOW, which reverses ino:15361 and is the first automatic BT_REG LOW
   in Run.
4. Continuous checks in every state: `PACKN_VOLTAGE` versus `PACK_CURRENT` (S_BYP open), pin 34/pin 10 against the
   command, `PACK_CURRENT` against the U_OCD/U_OCC levels, `OV_BATT` and `UV_BATT` on `PACK_VOLTAGE` with arming no
   longer tied to BT_BUS/BT_REG.
5. Bring-up P0 gates on `PACK_VOLTAGE`; the pack switch closes before P0.
6. A purge predictor (period and phase from `V_fc` dips) that replaces `fcUvLockoutActive()` as the window
   precondition. The fw v33b refusal stays until the predictor exists and gate G-P1 passes.
7. The BT-channel I^2t budget for D-BT-SQ, with its limit from gate G-T1, and an OTP-latch recovery (one EN toggle,
   then fault).
8. The State-99 phase-0 re-ordering and drain-skip rules of section 3.2.
9. The motoring interlock in windows and their exit; the window abort conditions of section 3.2.
10. Ownership while the pack is off the bus in a window: `chargingControl()` owns BT_BUS and BT_REG for the window and
    its exit; the share latch and the selector are suspended (no re-arm, no BT selection) and resume from a fresh
    battery-only arm after exit step 7; the k_d topology hold of fw v28 rev 4 already applies (exactly one bus switch
    HIGH); UV_BUS stays armed by the FC pair alone; UV_BATT and OV_BATT read `PACK_VOLTAGE` and stay armed.
11. `AG105_VBATN_ISOLATED` set to 1 after the rework; its meaning then matches the hardware. `FC_CHARGE_ALLOWED` stays
    0 until the bench gates pass. Ag105 reg 0x00 code 5 in place of 0x01 needs an operator ruling.
12. `chargerHasPower()` is unchanged: it reads pin levels (ino:16244-16247), so an I2C ACK from a battery-powered
    module in Run does not change it.
13. The MCU watchdog (RTWDOG, WDOG1) from `facts_prior.md` section 10 item 7, as a precondition of every window.

### 8.2 Telemetry

The two spare `switch_state` bits can carry the pin 34 readback (0x40) and the pin 10 readback (0x80) without a
length change. However, the meaning of the byte changes, so the Pi bridge must be updated in lockstep, and the change
should be folded into the planned telemetry v5 together with `PACK_VOLTAGE`, `PACK_CURRENT` and `PACKN_VOLTAGE`.
`I_charge` (reg 0x06) becomes a real pack charge current, which changes its interpretation in every downstream
analysis.

### 8.3 HIL

The hi-fi engine already models `BT_SEQ` as a pack-to-BT-boost input switch (`tools/hil_electrical.py:2069-2240`),
which is close to IC3. It lacks the veto coupling to `VCHG-IN`, S_BYP, the pack current monitor, the logic supply on the
pack, the FC-only bus during every window and the cold-start charger. The simple plant ignores `BT_SEQ` and must gain
the switch, the window sequences and the readback bits. The HIL aux byte is full, so the new readbacks need a frame
change.

## 9. Open questions and bench gates

Table 18 lists the gates that must pass before the first charge session on a reworked board, in kill order.

Table 18. Bench gates.

| Gate | Question | Pass condition |
|---|---|---|
| G-T1 | D-BT-SQ case temperature during a 60 s soak at 4.6, 5.6 and 7.6 A input, on this board with pad 13 un-heatsunk | Sets the BT continuous cap (Table 7); a cap below about 2.0 A bus-side is the kill criterion, with the external high-side switch (IC4) as the fallback |
| G-A6 | In circuit, module battery-powered, no input: Ag105 branch current in Run, I2C behaviour, battery-side quiescent drain, VBat+ to Vin+ back-feed, tolerance of VBat- below Vin- | Branch current below 1 A at 7.6 A pack current; back-feed below 1.1 mA |
| G-V3 | Lowest Ag105 input voltage at which any output current flows | Above 10.5 V |
| G-H1 | Continuity pack negative to GND with S_BYP off and the Ag105 lead removed, harness and accessories connected | Open |
| G-A1 | Ag105 sense resistance R_s, pins 14/15 to 16/17, module unpowered | Measured; input to Table 12 |
| G-A2 | Time from input arrival to first charge current with the pack on VBat+ | Measured; decides whether a second regen pulse is catchable |
| G-A3 | Ag105 efficiency at 15.9 V in, 2S, 1.25 A and 1.5 A | >= 0.85 for code 4 |
| G-A4 | Ag105 input capacitance and `VCHG-IN` drain time with Q_D and R_BL | Drain to 6.0 V in <= 20 ms |
| G-A5 | Does reg 0x06 track `PACK_CURRENT` and a clamp meter after the rework | Within 0.05 A at 0.5-1.5 A |
| G-OC | U_OCD and U_OCC trip currents, filter time and the U_OCD hiccup with a hung Teensy | Trip within 5 % of Table 14; no nuisance trip at BT load steps |
| G-T2 | `VCHG` minus `VBT` on a scope at BT load steps and at pack plug-in | No TRCB trip; ring below the RT1987 32 V VIN maximum |
| G-V1 | Veto threshold and response with a bench supply on `VCHG-IN`; Run soak with V-MOT live and regen pulses | EN below 0.6 V within 50 us above 9.96 V; no spurious veto in the soak |
| G-V2 | Boot and pre-window self-tests with injected faults (comparator removed, R_V1 open, U_G removed, U_OCC removed) | Each fault latched |
| G-S1 | OQ-7: pull-down on every RT1987 EN, including pin 32 | Present |
| G-S2 | I_5V of the full logic load | Measured; enters Table 9 |
| G-P1 | Purge period and phase predictability (T-E-01) | Window scheduling error < 100 ms |
| G-R1 | S0-R3 / T-E-03: VESC behaviour with V-MOT held | Carried from the charger study; decides HR1 for every concept |
| G-W1 | Watchdog forced-hang test (T-W-01) | Charger feeds open within the watchdog period |

The following questions remain open and are not resolved by any primary in hand:

1. The RT1987 EN-low turn-off time and the R_ON maximum and temperature coefficient are not given. The OTP is treated
   as a latch, on two of the three data-sheet statements.
2. The meaning of `MPPT_DISABLE` LOW during charging (TODO(verify: Silvertel)) decides whether 4-6 % or 19-20 % of each
   purge interval is lost to session overhead.
3. The Ag105 behaviour under reverse current and the purpose of the internal switch drawn in parallel with the sense
   in DS Fig.1 are UNCONFIRMED (gate G-A6).
4. The pack's maximum charge current and protection circuit are unknown; the Ag105 supports protected packs only
   (DS p.18).
5. The Ag105 VBat+ rating and the hot-plug ring at pack plug-in are not given or computed.

## 10. Adversarial assessment

### 10.1 Against the prior "switch both legs" objections

`facts_prior.md` section 8 records five objections that rated "switch both battery legs" as the weakest re-spin option.
IC3 engages them as follows.

1. **The bus needs another source in every window, which can only be the FC.** Unchanged. IC3 makes every window, regen
   included, an FC-only bus, and needs a purge predictor (G-P1). This objection is shared by every concept that opens
   BT_BUS in a window (brainstorm X3, ruling 7).
2. **The Teensy would brown out.** Retired. The LM1084 moves to `VCHG`, upstream of the switch, and sees about 7.2 V at
   the 7.4 V floor under load, against a 6.5 V need (section 4.5).
3. **The pack cannot buffer bus transients.** Unchanged in windows; shared with every concept.
4. **Every regen event costs two switch transitions plus a charger bring-up.** Worse. IC3 needs six transitions per
   brake (BT_BUS, BT_REG, D-BT-SQ, S_BYP, REGEN, and the reverse) and a cold charger start.
5. **The BQ29200, V_batt divider and BT sense references move.** Partly addressed: the references stay on PCB GND,
   `V_batt` becomes a `VBT` monitor, and new channels (`PACK_VOLTAGE`, `PACKN_VOLTAGE`, `PACK_CURRENT`) carry the pack
   measurements.

### 10.2 Verdict

IC3 achieves the study goal for FC charging at standstill. The pack is isolated from the board during every charge
window, the Ag105 regulates the pack current through its own sense, the pack current is bounded in hardware if the
sense is bypassed, and the ML0227 loop cannot form while the charger input is live. The Teensy supply becomes
independent of `VBT`.

However, IC3 cannot meet ruling 1 for regen, and review round 1 has made its weakest point sharper: D-BT-SQ, which
carried almost no current before, becomes the series element for the whole BT channel at 95 % of its rating with no
thermal copper under its exposed pad. In addition, the fixes of review round 1 have roughly doubled the added hardware
(nine Teensy pins, three comparators, a current monitor and four trace cuts) and the firmware scope.

The concept should therefore be carried to the synthesis only as an FC-charging-only design, with HR1 declared
failed for an operator ruling, and with G-T1 as its first kill gate. If G-T1 fails, the remaining value of IC3 is its
veto and pack-current-monitor architecture, which transfers to IC4.

## 11. Review round 1 adjudication

### 11.1 Method

Three adversarial reviewers (fault/safety, electrical, system) returned "survives with fixes" with no fatal finding.
Each finding was checked against the primaries named in its row. A finding is ACCEPTED when the primary confirms it,
and the design body above carries the fix. A finding is REFUTED, in full or in part, only where a primary contradicts
it; the refuting evidence is quoted by location. Prefixes: FM/Fm = fault lens major/minor, EM/Em = electrical lens,
SM/Sm = system lens.

### 11.2 Primary checks performed

Table 19 lists the primary checks that decided more than one finding.

Table 19. Primary checks.

| Item | Result | Source |
|---|---|---|
| RT1987 OTP | Table 13 p.7: "Temperature rising. System latches off"; section 17.8: "Toggle the EN pin or cycle the input power"; section 17.4 Table 1: "Auto-restart with soft-start". Two of three statements say latch | RT1987 DS-00 |
| RT1987 exposed pad | Section 8 pin 13: common-drain node, "must be electrically isolated", solder to a large isolated pad with many vias; section 18.3: 53.05 C/W on JEDEC 51-7 four-layer | RT1987 DS-00 |
| D-BT-SQ pad 13 copper | Signal `N$32` = D-BT-SQ pads 13 and 9 only, two 0.254 mm layer-1 wires, no polygon, no via | `.brd` lines 6837-6842 |
| RT1987 ISHDN, IOUT_LK, REN_PD | ISHDN 75 typ / 105 uA max; IOUT_LK 45 / 60 uA; REN_PD 475 / 730 / 985 kOhm; RON_5V 22 mOhm typ | RT1987 DS-00 Table 13 p.7 |
| TB005-762 contact resistance | 20 mOhm (max column) | TB005-762 data sheet p.1, Specifications |
| Ag105 I_DIS, I_BAT | I_DIS 4 A max (row 6); I_BAT 120-420 uA, no input (row 7) | Ag105 DS V1.1 p.20 |
| Ag105 battery on VLoad | "presents the battery potential across the Vload output at all times that the battery is not being charged" | Ag105 DS V1.1 p.9 |
| Ag105 Full rule | Within 0.2 V/cell reports Fully Charged; restart 0.2 V/cell below | Ag105 DS V1.1 p.5, p.6, p.11 |
| Ag105 abs max | Only DC supply -0.3 to 36 V; no VBat+ rating | Ag105 DS V1.1 p.19 |
| TPS61288 ILIM | 12 / 15 / 17.1 A at VIN 7.2 V, VOUT 16 V; PFM at light load | SLVSFP3C Electrical Characteristics; section 8.4.2 |
| Firmware build gates | `FAULT_SWITCH_CONFLICT` and `OC_BT` inside `#if !BENCH_TEST` | ino:7413-7418, 7430 |
| FC lockout | `UV_FC_PURGE_LOCKOUT_MS` 30000; comment: "re-arms itself on every purge"; charge entry requires `!fcUvLockoutActive()` and "REFUSES charge windows outright" | ino:2245-2257, 15493-15500 |
| State 99 phase 0 | Bus switches LOW then `assertFcChargeEnable(true)`; BT_REG not dropped in phase 0 | ino:8299-8318 |
| INA253 bidirectional | Mid-supply output with REF1 = VS, REF2 = GND; +/-15 A; CM -4 to 80 V | SLOS954A p.1, section 8.4.5 |

### 11.3 Fault lens

Table 20 records the fault-lens findings.

Table 20. Fault-lens adjudication.

| ID | Finding | Verdict | Evidence and design change |
|---|---|---|---|
| FM1 | Veto self-test does not cover the sense path; veto invisible in windows; interlocks compiled out of BENCH_TEST | ACCEPTED | Dossier Fig. 2 rev 0 injected after R_V1; ino:7413-7418, 7430 confirm the build gates. Fix: `VETO_SENSE` readback on pin 22 with a ratio check against `V_chg` in every window (entry step 9, F19); pre-window functional inject test (entry step 5, F7); all IC3 interlocks and `OC_BT` in every build (section 8.1 item 1) |
| FM2 | Sense-bypass faults undetectable before charging; unbounded on a bench supply | ACCEPTED | PACKN rev 0 was clamped at 0 V and the pre-window signal is millivolts. Detection before the window is still not achieved; instead the charge current is bounded in hardware by U_P and U_OCC at 2.1 A on any source (section 4.8, F3, F5). Hidden bonds upstream of the shunt remain a mechanical item (G-H1, F10) |
| FM3 | Open pack return diverts discharge through the Ag105, undetected | ACCEPTED | Ag105 I_DIS 4 A (DS p.20 row 6). Fix: bipolar `PACKN_VOLTAGE` with `ERR_SBYP_OPEN` (F17); F2 3 A fuse in the Ag105 lead; two soldered S_BYP source leads |
| FM4 | No hardware bound on the D-BT-SQ current | ACCEPTED | RT1987 SCP only in soft-start (DS-00 section 17.5); 8 A / 20 A-10 ms (section 12); TPS61288 ILIM 12-17.1 A. Fix: U_OCD at 8.33 A on the EN net (section 4.8); `OC_BT` in every build; watchdog precondition; boot and post-window D-BT-SQ short tests (F1). A fuse cannot both pass 7.6 A and protect a 20 A-10 ms envelope, so a fuse is not used for this purpose |
| FM5 | Ag105 battery-powered in Run, uncharacterised; veto threshold below pack maximum | ACCEPTED, with one part REFUTED | DS p.9 and p.20 row 7 support battery-side operation; rev 0 threshold 7.92-8.37 V was below 8.5-8.70 V. Fix: threshold 9.43-9.96 V (section 4.7), gate G-A6. REFUTED part: an I2C ACK in Run does not break `chargerHasPower()`, which reads pin levels only (ino:16244-16247); `pollAg105()` does not address the module unless that function is true |
| FM6 | Socketed refit creates single-point power contacts | ACCEPTED | Fix: no socket; pins 14/15 cut in place, Vin- pin 4 stays soldered, VLoad- 16/17 bonded to GND (section 7.1 steps 2-4, F22) |
| FM7 | State-99 phase 0 contradicts the interlock | ACCEPTED | ino:8299-8318 drains with BT_REG HIGH. Fix: phase 0a-0c drops BT_REG and pin 32 with readback before any drain, and skips the drains on pack-path faults and OV_BATT (section 3.2) |
| Fm1 | Boot test raises pin 32 before the inject | ACCEPTED | tD_ON has no minimum (DS-00 Table 13 p.7). Fix: inject first (boot step 4) |
| Fm2 | R_PD only on the veto board | ACCEPTED | Fix: R_PD2 at the EN pad end (Table 1, step 8) |
| Fm3 | Idle D-BT-SQ short test overlaps purges | ACCEPTED | Fix: test moved to boot before P0, plus a post-window test (boot step 3, exit step 3); no Idle test |
| Fm4 | New interlocks must be in BENCH_TEST builds | ACCEPTED | Section 8.1 item 1 |
| Fm5 | `PACKN_VOLTAGE` has no positive clamp | ACCEPTED | Fix: mid-scale bias with clamps to GND and 3.3 V (Table 4) |
| Fm6 | F7 "lost 5 V unpowers the Teensy" false with USB | ACCEPTED | Facts_board section 7 leaves the VUSB-VIN pad state unknown. F7 rewritten; new F23 with a bench rule |
| Fm7 | Hang in a regen window; watchdog must be a precondition | ACCEPTED | Section 3.2 preamble; section 8.1 item 13 |
| Fm8 | OTP latch corroborated | ACCEPTED | Table 19; open question 1 of rev 0 closed as "treat as latch" |
| Fm9 | Ceramics ring at plug-in; VBat+ abs max unchecked; F1 mandatory | ACCEPTED | DS p.19 gives no VBat+ rating (section 4.9); ceramic-only mitigation dropped (section 4.2 item 6); F1 marked mandatory |
| Fm10 | HR1 fails; needs operator ruling | ACCEPTED | Table 15; section 10.2 |

### 11.4 Electrical lens

Table 21 records the electrical-lens findings.

Table 21. Electrical-lens adjudication.

| ID | Finding | Verdict | Evidence and design change |
|---|---|---|---|
| EM1 | D-BT-SQ thermal case worse than 80 C/W; pad 13 has no copper | ACCEPTED | `.brd` signal `N$32`; DS-00 sections 8, 18.3. The arithmetic is correct: 40 + 1.49 x 80 = 159 C. Fix: Table 7 as a function of thetaJA; G-T1 first kill gate; OTP treated as latch; IC4-type external switch as fallback (section 4.1) |
| EM2 | Reverse share computed without the J-BT contact; Ag105 switch likely ON in Run; G-A1 measures the wrong state | ACCEPTED | TB005-762 20 mOhm; DS p.9, p.20 row 7. Fix: source leads soldered to the pad, F2 ballast, share recomputed (Table 12), new in-circuit gate G-A6. The one-way element is kept as the fallback rather than the default, because Table 12 keeps the share below 1 A with the soldered landing and F2 |
| EM3 | Veto threshold at or below the pack voltage; leakage can float `VCHG-IN` | ACCEPTED | Threshold raised to 9.43-9.96 V; R_BL 10 kOhm bleed; leakage bounded by ISHDN 105 uA by KCL (section 4.7); G-V1 extended with a Run soak; G-V3 added |
| EM4 | S_BYP open in Run undetectable | ACCEPTED | Bipolar PACKN and `ERR_SBYP_OPEN` (F17) |
| EM5 | FC budget omits traction | ACCEPTED | Table 9 headroom column; HR2 restated as standstill or very light traction (Table 15) |
| EM6 | HR1 fails structurally | ACCEPTED | Carried to the operator (section 10.2) |
| Em1 | RT1987 numbers verified | ACCEPTED (confirmation) | RON_5V 22 mOhm added to Table 2 |
| Em2 | BT input slightly above 7.27 A self-consistently | ACCEPTED | Table 5: 7.59 A at 6.8 V; design value 7.6 A |
| Em3 | 16.46 A event; periodic short check mandatory | ACCEPTED | U_OCD bounds the event; short checks at boot and after windows. The Idle form of the check is replaced (Fm3) |
| Em4 | Socket contact; bond VLoad- to GND | ACCEPTED | As FM6 |
| Em5 | Soldering a 14 AWG jumper next to the VDFN | ACCEPTED | Preformed lug or flat braid with a heat-sink clip (step 7) |
| Em6 | Hidden pack-negative bonds not audited | ACCEPTED | Step 12 audit; gate G-H1; F10 widened |
| Em7 | VBat- driven below Vin- when S_BYP is off before the charger starts | ACCEPTED | Section 4.5; TODO(verify: Silvertel); G-A6 |
| Em8 | Veto-held turn-off delay is 1.25 ms, not 1.10 ms | ACCEPTED | Recomputed with the rev 1 EN level of 2.75 V: 1.01 ms (pin 32 LOW) and 1.16 ms (veto at 0.2 V) (Table 8) |
| Em9 | Fully Charged cycling with the logic load in a long window | ACCEPTED | Section 4.4 Full rule; reg 0x06 and GENSTAT interpretation must allow it (no design change) |
| Em10 | TPS61288 PFM/DCM supports the dossier | ACCEPTED (confirmation) | SLVSFP3C section 8.4.2 cited in section 4.2 item 6 |

### 11.5 System lens

Table 22 records the system-lens findings.

Table 22. System-lens adjudication.

| ID | Finding | Verdict | Evidence and design change |
|---|---|---|---|
| SM1 | HR1 fails; study-level ruling item | ACCEPTED | Cold-start limit X6 applies to every Ag105-retaining concept; IC3 adds the veto on top. Carried to the operator |
| SM2 | Regen window is an unbudgeted FC window; no motoring interlock | ACCEPTED | `facts_firmware.md` section 6 (V-MOT at bus level with MOT_PWR closed). Fix: regen windows carry the FC budget; motoring interlock from entry step 2 to exit step 7 (section 3.2) |
| SM3 | `fcUvLockoutActive()` can never be met on a running stack | ACCEPTED | ino:2245-2257, 15493-15500. Fix: purge predictor replaces it (section 8.1 item 6); HR2 downgraded to BENCH |
| SM4 | Window throughput not assessed; Full rule | ACCEPTED | Section 4.4: 4-6 % or 19-20 % overhead per interval depending on `MPPT_DISABLE` semantics; no charge above about 8.0 V |
| SM5 | D-BT-SQ exposure reduces capability; OC_BT compiled out; OTP latch | ACCEPTED | As EM1 and FM4; capability loss quantified against the logged peaks (section 4.1) |
| SM6 | Fault-detection gaps on the return switch | ACCEPTED | As FM2, FM3 and EM4 |
| SM7 | Firmware, test and HIL scope larger; share-loop ownership unspecified | ACCEPTED | Section 8.1 item 10 assigns the owners; item 2 lists the CSV and CLAUDE.md changes; "three or more rounds" stated |
| Sm1 | In-place pin cut should be primary | ACCEPTED | Section 7.1 step 2 |
| Sm2 | Comparison with the prior "switch both legs" rating missing | ACCEPTED | Section 10.1 |
| Sm3 | Restore slower than return-only concepts | ACCEPTED | Section 4.3 |
| Sm4 | Veto immunity to off-state leakage unverified; ISHDN quoted as 75-985 uA | ACCEPTED in substance; the figure is REFUTED | RT1987 DS-00 Table 13 p.7 gives ISHDN 75 typ / 105 uA max; 985 is the REN_PD maximum in kOhm. The concern stands and is closed by R_BL and the KCL bound (section 4.7) and the G-V1 soak |
| Sm5 | State-99 drains on OV_BATT | ACCEPTED | Drains skipped on OV_BATT and pack-path faults (section 3.2) |
| Sm6 | Permanent pack drain | ACCEPTED | Section 7.3 |
| Sm7 | Re-plugging the pack into J-BT bypasses the isolation | ACCEPTED | J-BT pin 1 is occupied by the braid and labelled (step 7). In addition, a pack on J-BT alone leaves `VCHG` and the LM1084 unpowered, because D-BT-SQ blocks reverse current when disabled, so the board does not boot (UNCONFIRMED; self-revealing misplug) |
| Sm8 | `MPPT_DISABLE` semantics while charging unconfirmed | ACCEPTED | Open question 2; it also decides the throughput figure |

### 11.6 Post-review status

No finding was fatal, and no finding was refuted in substance; two were refuted only in a detail (FM5 on
`chargerHasPower()`, Sm4 on the ISHDN figure). Every accepted finding has a design change above.

The honest status of IC3 after review round 1 is the following.

1. **HR1 fails structurally** and cannot be fixed inside IC3. The concept can be selected only if the operator re-rules
   ruling 1 to accept FC charging with, at best, tail capture of regen.
2. **HR2 is BENCH, not PROVEN_CALC.** It is limited to standstill or very light traction, depends on a purge predictor
   that does not exist, and loses 4-20 % of each purge interval plus all charging above about 8.0 V.
3. **HR3 and HR4 are now argued with hardware bounds** (veto tested per window, U_OCC, U_OCD), conditional on gates
   G-V3, G-H1 and G-OC.
4. **G-T1 is a probable kill.** With no thermal copper under the D-BT-SQ exposed pad, the junction reaches the OTP
   latch at the `OC_BT` limit for any board thetaJA above about 62 C/W. A cap near 2 A bus-side, or the external
   high-side switch of IC4, is the likely outcome.
5. **The cost of the fixes is high:** nine Teensy pins (only pin 20 remains, reserved), three comparators, a current
   monitor, four trace cuts (D-BT-SQ EN, LM1084 input, and the pin-30 and pin-31 EN feeds) and three or more firmware rounds.

IC3 therefore survives review round 1 as an FC-charging-only design with a probable thermal kill. It is not a
candidate for the overall winner unless the operator re-rules HR1 and G-T1 passes. Its veto, its pack current monitor
and its in-place VBat- rework transfer directly to IC4.
