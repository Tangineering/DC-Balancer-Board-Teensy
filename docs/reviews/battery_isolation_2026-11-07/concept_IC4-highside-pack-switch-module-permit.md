# IC4: High-Side Pack Switch with Hardware Permits, Pack on the Ag105 Battery Port

Design dossier for isolation concept IC4 of the battery-isolation feasibility study. Date: 2026-11-07.
Revision 2: the design body incorporates the fixes accepted in review round 1 (fault, electrical and system
lenses); section 10 records the adjudication of every finding and the post-review status.
Board revision 20260622, firmware fw v37 rev 2 (`AG105_VBATN_ISOLATED 0`, `BENCH_TEST 1`).
Inputs: `brainstorm.md`, `facts_board.md`, `facts_ag105.md`, `facts_firmware.md` and `facts_prior.md` in this
folder. Nothing in this dossier is ordered, desoldered or flashed.

Citation tags used in this document:

| Tag | Primary |
|---|---|
| DS | Silvertel Ag105 datasheet V1.1, November 2021 (`references/Datasheets/AG105_Silvertel.pdf`) |
| SNOSD95C | TI LM7480-Q1 (covers LM74800-Q1), rev. C, December 2020 (vendor PDF, ti.com) |
| SLPS632 | TI CSD18510Q5B N-channel NexFET, March 2017 (vendor PDF, ti.com) |
| SLUSBP4C | TI UCC27524A dual low-side gate driver, rev. C, June 2024 (vendor PDF, ti.com) |
| SLVSDM5F | TI TLV701x/TLV702x comparators, rev. F, March 2020 (vendor PDF, ti.com) |
| SCES487I | TI SN74LVC1G11 3-input AND gate, rev. I (vendor PDF, ti.com) |
| SLVSFP3C | TI TPS61288 (`references/Datasheets/TPS61288LRQQR.pdf`) |
| SNVS037H | TI LM1084 (`references/Datasheets/LM1084ISX-5p0.pdf`) |
| DS-00 | Richtek RT1987 (`references/Datasheets/RT1987_DS-00.pdf`), values as quoted in `facts_prior.md` section 5 |
| SLUSA52C | TI BQ29200 (`references/Datasheets/BQ29200_TI.pdf`) |
| BRD / SCH / BOM / CSV | `references/Scale Car Board PCB 20260625.brd`, `references/Scale_Car_Board_20260624.sch`, `references/Scale Car Design PCB BOM 20260622.csv`, `references/Scale Car Teensy IO - IO.csv` |

Values that no primary gives are marked BENCH or TODO(verify: source). Inferences are marked UNCONFIRMED.

## 0. Design position

This section states the design position in six points, so that each later section can be tested against it.

1. The pack moves permanently to the Ag105 battery port. Pack positive connects to VBat+ (net `VCHG`) through a
   fused charge lead. Pack negative connects to VBat- (pins 14/15, lifted from GND) through a low-side switch Q_A.
   The module therefore regulates the pack current through its own sense (DS p.3 Fig. 1), and it never sees a
   battery appear or disappear while powered (finding X7 is avoided).
2. The pack reaches VBT only through **Q_H**, a new back-to-back N-FET switch driven by an LM74800-Q1. The discharge
   return reaches the pack only through **Q_B**, a low-side N-FET that bypasses the module sense. D-BT-SQ is removed
   from VBT by a trace cut, and the LM1084 input is moved from VBT to pack positive by a trace cut.
3. **Two hardware barriers with separate sensing hold Q_H open whenever the charger input `VCHG-IN` carries
   voltage:** the LM74800-Q1 OV comparator on tap T_OV, and a 3.3 V logic permit (TLV7012 comparator plus SN74LVC1G11
   AND) on tap T_LG. Each tap has its own resistors at its own capacitor pad and its own wire. An open T_OV wire fails
   toward "charger present" (Q_H off). While the charger is powered, VBT therefore has no source, and the circulating
   loop bus to charger to VBT to BT boost to bus cannot form. Both barriers act through one actuator (the LM74800 HGATE
   and Q2); actuator faults are covered by detection, not by a second actuator (section 5). This is the HR3 argument.
4. The low-side return is steered autonomously from the T_LG decision: Q_B conducts while the charger is unpowered,
   Q_A conducts while it is powered. No Teensy command can close Q_B during a charge. The T_LG threshold lies above the
   T_OV threshold, so Q_H is already open when the low side swaps, and Q_H re-closes only after Q_B is on again.
5. The Teensy logic supply stays on the pack (upstream of Q_H). The Teensy never browns out on a Q_H transition.
6. The concept pays for its structural loop break with one system cost: **every charging event, FC window or regen,
   runs on an FC-only bus.** An unpredicted H-20 purge during any charging event collapses the bus (section 4.6).
   This cost is inherent to IC4 and is not removed by any part choice. Purge prediction and a verified RTWDOG are
   therefore hard preconditions of every charging event.
7. **The Teensy request is active-high release (`PACK_RELEASE`), with a pull-down: the default is "pack on the bus,
   subject to the barriers".** A Teensy reset, brown-out or open request wire therefore never opens Q_H under load.
   A reset during a charging event becomes a hardware charge exit: the charger enables fall LOW, `VCHG-IN` bleeds
   down, Q_B returns, and Q_H re-closes with the BT boost held disabled by a hardware AND (section 2.4).

The datasheet-intended Ag105 topology (all pack current through VLoad) is not used, because the load output is rated
4 A continuous with no overcurrent protection (DS p.20 row 6, p.19), against a BT boost switch limit of 12-17.1 A
(SLVSFP3C section 7.5). The VLoad output is used only as an optional sensing input (section 2.6).

## 1. Topology

### 1.1 Nets added or changed

Table 1 defines the new and changed nets. Every other net keeps its 20260622 name and members.

Table 1. New and changed nets.

| Net | Members | Origin |
|---|---|---|
| `P_POS` | Pack positive lead after fuse F1; Q1 source (LM74800 A, VSNS/SW); fuse F2 (charge lead); fuse F3 (logic lead); PACK_V divider top; TVS1 | Switch board |
| `P_NEG` | Pack negative lead; Q_A source; Q_B drain; TVS1 | Switch board |
| `QH_MID` | Q1 drain, Q2 drain, LM74800 VS, C_VS | Switch board (common-drain node) |
| `VBT` | Q2 source (LM74800 OUT, C), J-BT pin 1, REG-BT VIN, L-BT, C1-BT, C2-BT, R1-BT, D_CLAMP cathode | Board net, minus D-BT-SQ VOUT, C-D12, REG-5V, CIN-5V |
| `VCHG` | Ag105 VBat+ (pins 18/19), C-D11, D-BT-SQ VIN, charge lead from F2 | Board net, now pack-fed |
| `VBAT_N` | Ag105 pins 14/15 stubs (cut from GND), flying lead, Q_A drain | New; formerly `GND` |
| `LOGIC_IN` | REG-5V pad 3, CIN-5V pad 1, flying lead from F3 | New; formerly part of `VBT` |
| `DBTSQ_OUT` | D-BT-SQ VOUT, C-D12 | Isolated stub after cut R3 |
| `GND` (J-BT pin 2) | Q_B source, switch-board logic ground; also a 4.7 Ohm fusible ground wire to J2 03/04 | Board net |
| J-BL pin 3 | Disconnected on the board: the pad-to-GND trace is cut and the terminal position is filled (rework R11) | Finding X1 |
| `T_OV` | 39.2 kOhm / 10 kOhm divider mounted at the C-D8 pads (bottom leg to PCB GND), wire W_OV to the LM74800 OV pin; 1 MOhm pull-up to VS at the switch board | New tap 1 |
| `T_LG` | 100 kOhm / 10 kOhm divider mounted at the C-D10 pads (bottom leg to PCB GND), wire W_LG to the TLV7012 #1 input; 1 MOhm pull-down at the switch board | New tap 2 |
| `BT_REG_EFF` | TPS61288 EN after the cut pin-4 trace; driven by AND #2 = `BT_REG_ENABLE` (pin 4) AND PERMIT | New; formerly the pin-4 net (rework R10) |
| `VLOAD_TAP` | 100 kOhm resistor mounted at Ag105 VLOAD+1 (pin 21), 47 kOhm at J2, Teensy pin 17 | Diagnostic only (no permit term) |

### 1.2 Power diagram

Figure 1 shows the power conductors. The switch board sits in the pack harness between the pack and J-BT. Three
flying leads land on the PCB: the charge lead to `VCHG`, the logic lead to `LOGIC_IN`, and the VBat- lead to the cut
stubs of Ag105 pins 14/15.

```
 Figure 1. IC4 power topology (power conductors only; arrows = permitted current direction when OFF).

                 F1 25 A                 Q_H = Q1 + Q2 (2 x CSD18510Q5B, common drain, LM74800-Q1)
 PACK+ ────────[fuse]──── P_POS ──┬── S Q1 D ──── QH_MID ──── D Q2 S ──── J-BT 1 ── VBT ──┬── REG-BT VIN (TPS61288)
  (2S)                            │   (DGATE)    (LM74800 VS)  (HGATE)                     ├── C1-BT, C2-BT, L-BT
                                  │   body diode: P_POS -> MID  body diode: VBT -> MID      ├── R1-BT/R2-BT -> pin 25
                                  │                                                         └── D_CLAMP (GND -> VBT)
                                  ├──[F2 3 A]──┬─ charge lead ──── VCHG pour (C-D11 pad 1) = Ag105 VBat+ 18/19
                                  │            D_RV2 (cathode up, anode P_NEG): blows F2 on a reversed pack
                                  │                                 (D-BT-SQ VIN also here; its VOUT branch is CUT, R3)
                                  ├──[F3 1 A]──┬─ logic lead ───── LOGIC_IN = REG-5V pad 3 / CIN-5V (trace CUT, R2)
                                  │            D_RV3 (cathode up, anode P_NEG): blows F3 on a reversed pack
                                  └── R_PV1 16.2k ── wire ── R_PV2 10k at J2 ── Teensy pin 16 (PACK_V)
                         TVS1
                       P_POS..P_NEG
 PACK- ──────────────────── P_NEG ──┬── S Q_A D ──── VBat- lead ──── Ag105 pins 14/15 (cut from GND, R1)
                                    │   (CSD18510Q5B; body diode P_NEG -> VBAT_N = charge direction)
                                    └── D Q_B S ──── J-BT 2 ── GND (PCB) ── Ag105 VIN- (pin 4), all returns
                                        (CSD18510Q5B; body diode GND -> P_NEG = discharge direction)

 Balance lead: pack VBAL+ -> J-BL 1, pack VMID -> J-BL 2, pack balance negative -> open; J-BL pin 3 is also
 disconnected on the board (trace cut and terminal position filled, R11), so a standard lead cannot re-bond it.
 Ag105 internal (DS p.3 Fig. 1): VBat+ -> converter output; VBat- -> current sense -> Vin-/Load- node (= GND).
```

### 1.3 Control diagram

Figure 2 shows the permit and steering logic. All logic is on the switch board and is referenced to the J-BT pin 2
lead (local GND). The switch board takes 3V3 and 5V from the J2 receptacle, plus a 4.7 Ohm fusible ground wire
(section 2.7).

```
 Figure 2. Permit and steering logic (revision 2).

 Tap T_OV (both resistors at the C-D8 pads):
   VCHG-IN ──[39.2k]──┬──[10k]── PCB GND
                      └── wire W_OV ──┬──► LM74800 OV pin (rising: VCHG-IN 5.55-5.96 V -> HGATE OFF)
                                      ├──[1M]── VS (QH_MID)        (open W_OV -> OV pin pulled to VS -> Q_H OFF)
                                      └──[100k]── wire ── Teensy pin 22 (OV_TAP_V, latent-fault cross-check)

 Tap T_LG (both resistors at the C-D10 pads):
   VCHG-IN ──[100k]──┬──[10k]── PCB GND
                     └── wire W_LG ── N_LG ──[1M]── GND_local     (open W_LG -> reads "absent"; firmware cross-check)

 3V3 ──[41.2k]── N_REF ──[10k]── GND_local      (N_REF = 0.645 V nominal -> VCHG-IN 7.09 V)
 3V3 ──[10k]──── N_MID ──[10k]── GND_local      (N_MID = 1.65 V)

 TLV7012 #1 ch1: IN+ = N_LG, IN- = N_REF, 1M from output to IN+ (hysteresis) -> CHG_PRESENT
 TLV7012 #1 ch2: IN+ = N_MID, IN- = CHG_PRESENT                              -> CHG_ABSENT (inverse of ch1)
 3V3 ──[10k]── N_QB ──[10k]── P_NEG             (N_QB = (3.3 V + V(P_NEG)) / 2, local GND = Q_B source)
 3V3 ──[11.5k]── N_DIODE ──[10k]── GND_local    (N_DIODE = 1.535 V -> V(P_NEG) = -0.23 V)
 TLV7012 #2 ch1: IN+ = N_DIODE, IN- = N_QB (Q_B body-diode detector, section 2.2) -> QB_DIODE (to Teensy pin 21)
 TLV7012 #2 ch2: IN+ = N_MID, IN- = PACK_RELEASE                             -> PACK_ALLOW (inverse of the request)

 Teensy pin 34 (PACK_RELEASE) ──[1k]──┬── 10k to GND_local (default: release LOW = pack allowed)
                                      └──► TLV7012 #2 ch2 IN-
 AND #1 (SN74LVC1G11): A = PACK_ALLOW, B = CHG_ABSENT, C = QB_GATE (Q_B gate pin through 10k; 10k gate pull-down)
 AND #1 Y = PERMIT ──[10k]──┬── 10 nF and 47k to GND_local ── LM74800 EN/UVLO   (turn-off delayed ~100 us, section 2.4)
                            ├──[100k]── wire ── Teensy pin 35 (PERMIT_RB, input only; Serial8 reserved)
                            └──► AND #2 B
 AND #2 (SN74LVC1G11): A = BT_REG_ENABLE (Teensy pin 4, 10k pull-down), B = PERMIT, C = 3V3
 AND #2 Y = BT_REG_EFF ── flying lead ── TPS61288 EN (pin-4 trace cut, R10)   (boost stops before Q2 opens)
 CHG_PRESENT ──[10k]── wire ── Teensy pin 33 (CHG_PRESENT_RB)

 UCC27524A (VDD = 5V): INA = CHG_ABSENT -> OUTA -> Q_B gate (on while the charger is unpowered)
                       INB = 5V via 10k, ENB = CHG_PRESENT via 10k / 10 nF, 100k pull-down -> OUTB -> Q_A gate
                       (Q_A enable delayed ~90 us, after Q_H is already off)
 VLOAD_TAP ──[100k at Ag105 pin 21]── wire ──[47k at J2]── GND ── Teensy pin 17 (VLOAD_V, diagnostic only)
```

### 1.4 Operating modes

The topology has two hardware modes. Table 2 lists them; the mode is selected by `VCHG-IN` alone, and the Teensy
only grants or withdraws Q_H within discharge mode.

Table 2. Hardware modes.

| Mode | Condition | Q_H | Q_B | Q_A | Pack current path | VBT |
|---|---|---|---|---|---|---|
| Discharge | VCHG-IN below the T_LG release (6.5-7.1 V falling) and the T_OV release (5.04-5.43 V falling) | ON unless PACK_RELEASE high | ON | OFF | P_POS -> Q_H -> VBT -> loads -> GND -> Q_B -> P_NEG | Pack |
| Discharge, Q_H withdrawn | As above, PACK_RELEASE high | OFF | ON | OFF | Logic load only, via F3 and Q_B | Unsourced, decays |
| Charge | VCHG-IN above the thresholds | OFF (two barriers) | OFF | ON | Ag105 VBat+ -> pack -> P_NEG -> Q_A -> VBat- -> sense -> Vin- | Unsourced, decays |

## 2. Parts, gate drive and fail-safe defaults

### 2.1 Q_H: LM74800-Q1 with two CSD18510Q5B

The LM74800-Q1 was selected over a discrete P-FET because it provides, in one part, a fast EN shutdown of both gates,
an OV comparator usable as an independent barrier, a defined inrush slope, and a fail-safe gate state below its
supply thresholds. Table 3 lists the ratings that the design uses.

Table 3. LM74800-Q1 ratings used (SNOSD95C).

| Parameter | Value | Reference |
|---|---|---|
| Operating input range | 3-65 V | SNOSD95C section 9.1, p.12 |
| A to GND, VS to GND (recommended) | -60 to 65 V; 0 to 65 V | section 7.3, p.4 |
| EN/UVLO rising threshold | 1.195 / 1.231 / 1.267 V | section 7.5, p.5 |
| EN low-Iq shutdown threshold (falling) | 0.30 / 0.67 / 0.93 V | section 7.5, p.5 |
| Shutdown current (EN low) | 2.87 uA typ, 5 uA max | section 7.5, p.5 |
| EN leakage | 52 nA typ, 200 nA max | section 7.5, p.5 |
| EN low effect | "both the external MOSFETs and controller is off" | section 9.1, p.12 |
| OV threshold rising / falling | 1.195-1.267 V / 1.091-1.159 V | section 7.5, p.5 |
| HGATE drive (5 V < VS < 65 V) | 10 V min, 11.1 V typ, 14.5 V max | section 7.5, p.6 |
| HGATE source / sink current | 39-75 uA / 168 mA min | section 7.5, p.6 |
| HGATE turn-off deglitch (EN) | 3-6 us | section 7.6, p.7 |
| HGATE turn-off deglitch (OV) | 3.98-5.4 us (LM74800-Q1) | section 7.6, p.7 |
| DGATE regulated forward drop | 6.8 / 10.5 / 13.4 mV | section 7.5, p.6 |
| Fail-safe | HGATE is tied to OUT unless CAP-VS exceeds its UVLO and VS exceeds POR | section 9.3.2, p.15 |
| Charge pump UVLO (CAP-VS) rising / falling | 5.4-7.9 V / 4.4-6.6 V | section 7.5, p.6 |
| VS POR rising / falling | 2.4-2.85 V / 1.9-2.3 V | section 7.5, p.5 |
| Inrush | C_dVdT = I_HGATE x C_OUT / I_INRUSH (Equation 2) | section 9.3.2, p.15-16 |
| External MOSFET V_GS rating required | >= 15 V | section 7.3, p.4 |

Table 4 lists the CSD18510Q5B ratings. The same part is used for Q1, Q2, Q_A and Q_B to keep one MOSFET type.

Table 4. CSD18510Q5B ratings used (SLPS632, p.1 and section 5.1, p.3).

| Parameter | Value |
|---|---|
| V_DS / V_GS | 40 V / +/-20 V |
| I_D package-limited | 100 A |
| R_DS(on) at V_GS 10 V, 32 A | 0.79 typ, 0.96 max mOhm |
| R_DS(on) at V_GS 4.5 V, 32 A | 1.2 typ, 1.6 max mOhm |
| V_GS(th) | 1.2 / 1.7 / 2.3 V |
| Q_g (10 V) / Q_gd | 118 typ, 153 max nC / 21 nC |
| Body diode V_SD at 32 A | 0.8 typ, 1.0 max V |
| E_AS single pulse | 328 mJ (81 A, 0.1 mH) |
| R_thJA | 40 C/W typical on 1 in2 2 oz copper (p.1 note 1) |
| Safe operating area | Figure 10 (p.6); numerical read-out not taken: TODO(verify: SLPS632 Fig. 10) |

**Topology choice.** Q1 (DGATE) and Q2 (HGATE) are in the common-drain arrangement of SNOSD95C section 9.1. Q2
blocks the forward direction P_POS to VBT; Q1 blocks the reverse direction VBT to P_POS. Only Q2 blocks the
direction that matters for the loop. Section 5 treats a shorted Q2 as a single fault.

**Pin connections.** A = P_POS, C = QH_MID side of Q1 drain per SNOSD95C Table 6-1 (C = drain of Q1), VS = QH_MID with
100 nF to GND, CAP = 100 nF to VS, OUT = VBT, VSNS and SW shorted to VS (SNOSD95C Table 6-1, SW description: "If the
internal disconnect switch ... is not used then short them together and connect to VS pin"). GND = local GND.

**Inrush.** The target is the project hot-plug rule of 12 mA/uF (facts_prior section 10 item 4), that is a VBT
slew of 12 V/ms. Equation 2 rearranged gives dV/dt = I_HGATE / C_dVdT, independent of C_OUT. With C_dVdT = 4.7 nF:
dV/dt = 39-75 uA / 4.7 nF = 8.3-16.0 V/ms, that is 8.3-16.0 mA/uF. The series resistor R1 of SNOSD95C Figure 9-3 is
1 kOhm (turn-off speed-up). The upper bound exceeds the 12 mA/uF rule by 33 % at the maximum HGATE current; the
alternative C_dVdT = 6.8 nF gives 5.7-11.0 V/ms. This document selects **6.8 nF** so that the rule holds at the
HGATE maximum.

**Gate rating.** HGATE drive is 10-14.5 V; the CSD18510Q5B gate rating is +/-20 V, and SNOSD95C section 7.3 requires
a V_GS rating of at least 15 V. Both are met.

### 2.2 Q_A and Q_B: CSD18510Q5B with UCC27524A

The UCC27524A drives both low-side gates from the 5V rail. Table 5 lists its ratings.

Table 5. UCC27524A ratings used (SLUSBP4C).

| Parameter | Value | Reference |
|---|---|---|
| VDD operating | 4.5-18 V | section 5.3, p.4 |
| VDD UVLO rising / falling (DGN) | 3.8-4.4 V / 3.5-4.1 V | section 5.5, p.5 |
| Outputs during VDD UVLO | Held low | Features, p.1 |
| Input floating | Output held low | Table 4-1 (INA/INB), p.3 |
| Enable floating | Output enabled (ENx floats high) | Table 4-1 (ENA/ENB), p.3 |
| Input / enable range | -2 to 18 V (recommended); thresholds independent of VDD | section 5.3, p.4; Features, p.1 |

Q_B: drain on P_NEG, source on GND. Its body diode conducts GND to P_NEG (discharge direction) and blocks the charge
direction. The gate is OUTA, driven by CHG_ABSENT. V_GS = 5 V minus 0 V; R_DS(on) is therefore bounded by the 4.5 V
figure, 1.6 mOhm maximum.

Q_A: source on P_NEG, drain on VBAT_N. Its body diode conducts P_NEG to VBAT_N (charge direction) and blocks discharge
through the module sense. The gate is OUTB, enabled by CHG_PRESENT on ENB. V_GS = 5 V minus V(P_NEG), and V(P_NEG)
is within tens of millivolts of GND while Q_A conducts charge current (section 4.7).

**Why Q_A exists.** Without Q_A, the discharge return in Run would split between Q_B and the module sense path in
the ratio of their resistances. The sense resistance R_s is unknown (TODO(verify: Silvertel); BENCH gate B2), and the
module path is rated 4 A (DS p.20 row 6). Q_A off removes that split. A Schottky in place of Q_A would add about
0.2-0.45 V of charge-path drop, which the Ag105 CV loop does not see, so the pack would end that much below 8.4 V.

**ENB polarity hazard.** The UCC27524A enables a floating ENB (SLUSBP4C Table 4-1). If the CHG_PRESENT trace opens,
ENB floats high and Q_A turns on in discharge mode. Q_A on in discharge mode is not dangerous by itself (Q_B still
carries most of the return; the module path then shares current by resistance ratio), but it re-creates the split
that Q_A exists to prevent. A 100 kOhm ENB pull-down to GND is fitted so that an open trace disables Q_A.

**ENB delay.** CHG_PRESENT reaches ENB through 10 kOhm with 10 nF to GND (and the 100 kOhm pull-down), a time
constant of about 91 us. The T_LG threshold already lies above the T_OV threshold (section 2.3), so in the healthy
case Q_H is off before CHG_PRESENT rises. The delay covers the case in which T_OV has failed toward "absent" and the
logic permit is the only barrier: the permit then removes the LM74800 EN and HGATE turns off within its 3-6 us
deglitch (SNOSD95C 7.6), well before Q_A is enabled. The ENB high threshold of the UCC27524A is TODO(verify:
SLUSBP4C 5.5); the delay is BENCH gate B6.

**Q_B body-diode detector and gate interlock.** Two additions make a non-conducting Q_B visible. (1) The Q_B gate pin
is sensed through 10 kOhm into AND #1 input C (SN74LVC1G11 inputs tolerate 5.5 V, SCES487I section 5.3), with a
10 kOhm gate pull-down. A lost 5V wire, a UCC27524A in UVLO (outputs held low, SLUSBP4C Features), CHG_ABSENT stuck
low, or an open gate trace therefore removes the permit, and Q_H cannot stay closed with Q_B off. (2) TLV7012 #2
ch1 compares P_NEG against the Q_B source (local GND) through the level shift of Figure 2 and asserts QB_DIODE when
V(P_NEG) falls below -0.23 V. An enhanced Q_B at 16.46 A drops 26 mV; the body diode drops 0.8-1.0 V at 32 A
(SLPS632 section 5.1). The detector measures across Q_B alone, so the J-BT pin 2 lead drop does not enter. It covers a
Q_B die or bond-wire open with a healthy gate. Firmware latches a fault on QB_DIODE in discharge mode with Q_H closed.
The detector is not part of the permit, because a permit trip on load current would oscillate (Q_H off removes the
load, the diode current falls, the permit returns).

### 2.3 VCHG-IN detection: TLV7012 and the LM74800 OV pin

Table 6 lists the comparator ratings.

Table 6. TLV7012 ratings used (SLVSDM5F).

| Parameter | Value | Reference |
|---|---|---|
| Supply | 1.6-6.5 V | Features, p.1 (dual-channel figure) |
| Input common-mode range | Up to V_CC + 0.1 V (specified); recommended input range to V_CC + 0.2 V; abs. max. 7 V independent of V_CC | sections 6.8, 6.4, 6.2 (as cited by the electrical reviewer; not re-fetched in this round) |
| Input offset | +/-0.5 typ, +/-8 mV max | section 6.8, p.7 |
| Hysteresis (internal) | 1.2 / 4.2 / 14 mV | section 6.8, p.7 |
| Propagation delay | 260 ns (high-to-low), 310 ns (low-to-high) typ | section 6.9, p.7 |
| Power-on behaviour (push-pull TLV701x) | Output held low while the POR is active | section 7.4, p.15 |

Offset, hysteresis and delay are quoted from the TLV701x single-channel tables; the dual TLV7012 characteristics
are taken as equal (UNCONFIRMED; TODO(verify: SLVSDM5F dual-channel tables)).

**Two taps, two thresholds.** The two barriers use separate taps (Figure 2), each with both divider resistors at its
own capacitor pad, so that a tap-wire short to GND is limited by the top resistor and a single open element affects
only one barrier.

- **T_OV (LM74800 OV pin).** 39.2 kOhm over 10 kOhm at the C-D8 pads, a ratio of 4.92, plus a 1 MOhm pull-up to VS at
  the switch board. The pull-up adds 8.4 V x 7.97 kOhm / 1008 kOhm = 66 mV at the OV pin (pack at 8.4 V). The OV
  threshold is 1.195-1.267 V rising and 1.091-1.159 V falling (SNOSD95C 7.5), so Q_H opens at VCHG-IN 5.55-5.96 V and
  may re-close below 5.04-5.43 V. If W_OV opens, the pull-up drives the OV pin to VS and Q_H opens: the failure is
  toward "charger present". At the 36 V Ag105 absolute maximum (DS p.19) the OV pin sees 7.3 V, far below its
  70 V absolute maximum (SNOSD95C 7.1).
- **T_LG (TLV7012 #1).** 100 kOhm over 10 kOhm at the C-D10 pads, a ratio of 11.0, plus a 1 MOhm pull-down at the
  switch board. At 36 V the comparator input is 3.27 V, inside V_CC + 0.1 V = 3.4 V; at the 21.4 V regen clamp it is
  1.95 V. The reference is 3V3 x 10/51.2 = 0.645 V, so CHG_PRESENT rises at 7.09 V. With the 3V3 tolerance assumed at
  +/-3 % (UNCONFIRMED; TODO(verify: PJRC)) and 1 % resistors the rising threshold lies within about 6.8-7.4 V. The
  1 MOhm output-to-input feedback adds 3.3 V x 8.26 kOhm / 1 MOhm = 27 mV of hysteresis at the input, that is
  about 0.30 V at VCHG-IN, so the release lies within about 6.5-7.1 V. This hysteresis prevents chatter on the 30 ms
  bleed decay. If W_LG opens, the input reads "absent" (unsafe direction); the firmware cross-check of section 3.2
  detects it within 2 ms of the first charger power-up, before the Ag105 delivers any current (start-up 65-170 ms).

The resulting order is correct in both directions. Rising: T_OV opens Q_H (at most 5.96 V) before T_LG swaps the
low side (at least 6.8 V). Falling: T_LG returns Q_B and removes Q_A (at least 6.5 V) before T_OV lets Q_H re-close
(at most 5.43 V). Both thresholds lie below the Ag105 input UVLO of 11 V typical (DS p.19); the datasheet gives no
minimum, so a UVLO minimum above 7.6 V is bench gate B15.

**Ground offset.** Both taps are referenced to PCB GND at the board pads, while the switch-board logic is referenced
to the Q_B source. In discharge the J-BT pin 2 lead lifts PCB GND by up to 0.4 V above local GND (section 2.7). With
`VCHG-IN` at 0 V (charger paths off, R_BL bleed), the T_LG node then reads up to 0.4 V against the 0.645 V reference,
and the T_OV node up to 0.47 V against the 1.091 V minimum release. Neither trips. The margin on T_LG is 0.245 V and
the measured lead offset is BENCH gate B16.

**Use of the OV pin.** SNOSD95C intends the OV ladder to sense the protected supply (section 9.3.3). Driving it from
an external node is within the OV pin ratings (abs. max. 70 V to GND, SNOSD95C section 7.1; leakage 200 nA max,
section 7.5, which is 2 mV of error into 8 kOhm). This use is outside the datasheet's described application and is
UNCONFIRMED until bench gate B6.

**Why the tap resistors sit at the board pads.** `VCHG-IN` is fed by two RT1987s whose short-circuit protection is
active only during soft-start (DS-00 section 17.5, via facts_prior section 5). A tap wire short to GND would therefore
see the full source current. The top resistors limit a shorted tap to 0.55 mA (T_OV) and 0.21 mA (T_LG) at 21.4 V.

### 2.4 Logic permit: SN74LVC1G11

The SN74LVC1G11 is supplied from 3V3. Its high-level input threshold is 2.0 V at V_CC 3.0-3.6 V and its input range
extends to 5.5 V (SCES487I section 5.3, p.4). It supports partial power-down (I_off, SCES487I p.1). AND #1 forms
PERMIT = PACK_ALLOW AND CHG_ABSENT AND QB_GATE.

**Request polarity.** Teensy pin 34 drives `PACK_RELEASE`, active HIGH, with a 10 kOhm pull-down. TLV7012 #2 ch2
inverts it into PACK_ALLOW, which the TLV7012 holds LOW during its own POR (SLVSDM5F 7.4). The default state of the
request is therefore "pack allowed": a Teensy reset, brown-out, `pinMode` error or open request wire leaves Q_H under
the control of the barriers, as the pack connection is on the 20260622 board today. Q_H is opened deliberately only
by the charge-entry procedure, at near-zero BT current.

**EN drive and turn-off delay.** PERMIT drives the LM74800 EN/UVLO pin through 10 kOhm into 10 nF, with a 47 kOhm
pull-down at the EN pin. The pull-down holds EN low when the gate output is unpowered or the trace is open. The RC
delays the EN fall by about 10 kOhm x 10 nF x ln(3.3 / 1.2) = 0.10 ms; the EN/UVLO falling threshold is taken at
the 1.195 V rising minimum, because SNOSD95C 7.5 gives no separate falling figure in the values used here
(TODO(verify: SNOSD95C 7.5 EN/UVLO hysteresis)). During this delay AND #2 has already removed BT_REG_EFF.

**Boost-first interlock (AND #2).** The pin-4 trace to the TPS61288 EN is cut (rework R10) and re-driven from AND #2:
BT_REG_EFF = BT_REG_ENABLE AND PERMIT. A permit loss therefore stops the BT boost about 0.1 ms before Q2 starts to
turn off, so that a barrier trip under load does not open Q_H against a switching boost (section 4.4). The 10 kOhm
pull-down on the pin-4 input holds the boost disabled while the Teensy is in reset, which also covers the autonomous
Q_H re-close after a reset (section 3.2). The TPS61288 EN-to-stop time is TODO(verify: SLVSFP3C); bench gate B7
measures the sequence at full current.

**Readback.** The PERMIT node feeds Teensy pin 35 through 100 kOhm. If pin 35 is ever driven HIGH (a `pinMode`
error, or `Serial8` TX, which uses pin 35), a LOW gate output holds the PERMIT node near 0 V against the 33 uA that
100 kOhm can source, so EN stays low. With the gate output unpowered (high impedance), the EN node reaches
3.3 V x 47 / (100 + 10 + 47) = 0.99 V, below the 1.195 V EN minimum. The revision-1 values (1 kOhm readback) allowed
1.65 V, above the 1.267 V maximum. Pin 35 and `Serial8` are reserved in the CSV notes and
in firmware. CHG_PRESENT is read back on pin 33 through 10 kOhm.

### 2.5 VCHG-IN bleed

The Q_H barrier releases only after `VCHG-IN` decays below the T_OV release of 5.04-5.43 V. The existing load on `VCHG-IN` is the
R1-CHG/R2-CHG divider (88.7 kOhm) and the Ag105 idle current (18 mA max while powered, DS p.20 row 4; the current
below UVLO is not given). With C-D8 + C-D10 = 20 uF (BRD; BOM 0805 10 uF parts) the divider alone gives a time
constant of 1.77 s, which would delay every return of the pack to the bus by more than a second.

A bleed resistor R_BL = 1.5 kOhm, 1 W, is piggybacked across C-D8 (pad 1 to its GND pad). The time constant becomes
1.5 kOhm x 20 uF = 30 ms. The Ag105 internal input capacitance is TODO(verify: Silvertel) and adds to this. The bleed
dissipates 0.17 W at 16 V and 0.31 W at 21.4 V. Over a 0.5 s regen event it consumes 0.15 J, that is 3-8 % of the
1.81-5.55 J that the prior study computes as available (facts_prior section 6). This is a deliberate trade-off:
benefit, a pack return latency of tens of milliseconds; however, a continuous loss during every charging event.

### 2.6 VLoad: diagnostic only

The concept brief puts VLOAD_PRESENT into the permit, using DS p.9: the module "will never present the battery
potential on the Vload output when charging is in process". This term is independent of the `VCHG-IN` detection and
reads the module's own state.

Revision 2 removes the term from the permit: AND #1 input C now carries the Q_B gate interlock (section 2.2), and
JP1 is deleted. The revision-1 drawing tied input C to 3V3 through 10 kOhm on the node that also fed pin 17, which
would have corrupted the VLoad diagnostic. The VLoad divider now has its own node (100 kOhm at pin 21, 47 kOhm at J2,
Teensy pin 17). The reasons for keeping VLoad out of the permit are as follows:

- The datasheet does not state whether VLoad carries the battery while the module input is unpowered. If it does not,
  the permit deadlocks Q_H open at every boot (brief first-gate risk). BENCH gate B1.
- The datasheet does not state every module state in which VLoad is removed (for example Low Power, thermal or
  battery-temperature states). Any such state in Run opens Q_H under load, which collapses a battery-only bus.
- The term adds protection only against a double fault (both `VCHG-IN` barriers failed). Its single-point nuisance
  trip in Run is a worse failure than the double fault it guards.

The divider is still fitted and read on Teensy pin 17 as a diagnostic, so that bench gate B1 can characterise the
VLoad behaviour before anyone enables the term. The 100 kOhm top resistor is mounted at the Ag105 pin-21 pad, because
VLoad+ is pack-fed through a module switch with no overcurrent protection (DS p.19 section 5.6.2).

### 2.7 Switch-board grounding

The switch board logic ground is the Q_B source node, which is the J-BT pin 2 lead. A separate GND wire to the J2
receptacle would parallel the J-BT pin 2 lead and carry a share of the return current inversely proportional to its
resistance; with a 24 AWG signal wire against a power lead, that share is of the order of 2-5 % (UNCONFIRMED;
depends on the lead resistances), up to about 0.8 A at the incident peak. No such wire is fitted. The logic signals
therefore see the drop of the J-BT pin 2 lead and its terminal contact as a common-mode offset: at 16.46 A this is
16.46 A x (lead + up to 20 mOhm contact, TB005-762 datasheet p.1) = up to about 0.4 V. The SN74LVC1G11 low threshold is
0.8 V at 3.3 V supply (SCES487I section 5.3), so a low PACK_RELEASE stays a valid low. For the analog PACK_V, the
bottom divider resistor is mounted at the J2 end so that the reading is referenced to the Teensy ground.

**Fusible ground wire (revision 2).** Without any ground wire, an open J-BT pin 2 lead would force the board return
through the logic wires, and 3V3 measured against the floating local GND could exceed the SN74LVC1G11 and TLV7012
absolute maxima. A 26 AWG ground wire from the switch-board local GND to J2 03/04 through a 4.7 Ohm fusible resistor
(TODO(select)) is therefore fitted. In normal discharge it carries at most 0.4 V / 4.7 Ohm = 85 mA, so the offset
argument above is unchanged. If the J-BT pin 2 lead opens, the resistor holds the two grounds together while the
board current collapses, and it fuses if the board current persists. Each signal wire also carries its series
resistor (Figure 2), which limits the injected current.

### 2.8 Protection parts

Table 7 lists the protection parts. Parts without a fetched primary are marked TODO(select); no rating is claimed for
them beyond the requirement.

Table 7. Protection parts and requirements.

| Ref | Function | Requirement | Part |
|---|---|---|---|
| F1 | Pack main fuse | 25 A, DC rating >= 16 V, interrupting rating >= the prospective pack current of 120-420 A (facts_prior section 9) | TODO(select) |
| F2 | Charge lead fuse | 3 A (revision 2, was 5 A): carries the 1.7 A code-4 trip current (set + 200 mA, DS p.18) continuously and bounds a sense-bypass fault at about the Ag105 2.5 A maximum; same interrupting requirement; the `VCHG` pour, C-D11 and D-BT-SQ VIN become permanently pack-fed (facts_prior section 10 item 2) | TODO(select) |
| F3 | Logic lead fuse | 1 A, same interrupting requirement | TODO(select) |
| D_RV2, D_RV3 | Shunt reversal diodes after F2 and F3, cathode to the lead, anode to P_NEG | Blow F2 / F3 on a reversed pack; the Ag105 has no reversal protection and DS p.18 recommends an external diode (DST1550S) with a fuse (facts_ag105 section 4.1) | TODO(select) |
| TVS1 | P_POS to P_NEG clamp for a Q_H turn-off under load | V_RWM >= 9 V, clamp <= 30 V at 20 A (Q1/Q2 V_DS 40 V) | TODO(select) |
| D_CLAMP | Schottky, anode GND, cathode VBT | Secondary clamp only. No Schottky holds VBT above the TPS61288 VIN minimum of -0.3 V (SLVSFP3C 7.1) at 16.5 A (forward drop at that current about 0.4-0.5 V, UNCONFIRMED); the primary measure is the boost-first interlock (section 2.4) | TODO(select) |
| R_GW | Fusible ground-wire resistor, 4.7 Ohm | Section 2.7 | TODO(select) |
| Connectors | Pack-side and board-side power connectors | Polarised, one housing per pack connection so that P_POS and P_NEG cannot be swapped, contact resistance well below the TB005 20 mOhm maximum | TODO(select) |

### 2.9 Fail-safe defaults

Table 8 lists the default state of each switch for each loss of control. Resistor values are those of sections 2.1
to 2.6.

Table 8. Fail-safe defaults.

| Condition | PACK_RELEASE | PERMIT | Q_H | Q_B | Q_A | Mechanism |
|---|---|---|---|---|---|---|
| Teensy in reset or GPIO high-Z | Low (10 kOhm pull-down, below the 47 kOhm keeper bound of facts_prior section 10 item 6) = pack allowed | High if the charger is unpowered | ON if the charger is unpowered (pack on VBT, as on the 20260622 board today); BT boost held off by AND #2 (pin-4 pull-down) | ON if charger unpowered | OFF if charger unpowered | The barriers alone decide; a reset during a charge window becomes a hardware charge exit once the RT1987 ENs fall (OQ-7) |
| 3V3 rail absent | - | Low (47 kOhm) | OFF | OFF (TLV7012 output held low in POR, SLVSDM5F 7.4) | OFF | Body diodes carry the logic load |
| 5V rail absent or 5V wire open | - | Low (QB_GATE low) | OFF | OFF (UCC27524A UVLO, outputs low) | OFF | Gate interlock (section 2.2); body diodes |
| LM74800 VS below POR or charge pump in UVLO | - | - | OFF (HGATE tied to OUT, SNOSD95C 9.3.2) | - | - | Inside the controller |
| Teensy hung | Last level | Follows `VCHG-IN` | Opens whenever `VCHG-IN` rises | Follows `VCHG-IN` | Follows `VCHG-IN` | The barriers do not depend on the Teensy; the RTWDOG (a precondition of charging, section 3.2) resets the MCU |
| Charger input present, any Teensy state | Any | Low | OFF (two barriers) | OFF | ON | Section 1.3 |
| W_OV open | Any | As logic | OFF (OV pin pulled to VS) | Follows T_LG | Follows T_LG | Fails toward pack-off; detected by BT_VOLTAGE vs PACK_VOLTAGE |

## 3. Teensy pins and control sequence

### 3.1 Pins

Table 9 lists the pins. All seven are free in the CSV and on the J2 receptacle (facts_board section 7.2). The CSV
must be amended before any firmware change (CSV authority, CLAUDE.md section 1). Pins 34 and 35 are the `Serial8`
pins (facts_firmware line 174); `Serial8` must stay unused, and the CSV notes must say so.

Table 9. New Teensy pins.

| Pin | J2 contacts | Proposed Code Name | Dir | Function |
|---|---|---|---|---|
| 34 | 45/46 | `PACK_RELEASE` | OUT | HIGH takes the pack off VBT (Q_H open); 10 kOhm pull-down = pack allowed |
| 35 | 43/44 | `PACK_PERMIT` | IN only | Read-back of the PERMIT node through 100 kOhm |
| 33 | 47/48 | `CHG_PRESENT_RB` | IN | Read-back of the T_LG comparator decision |
| 21 (A7) | 11/12 | `QB_DIODE` | IN | Q_B body-diode conduction detector (section 2.2) |
| 22 (A8) | 09/10 | `OV_TAP_V` | AIN | T_OV node at the switch board through 100 kOhm; x4.92 = VCHG-IN (plus the 66 mV pull-up offset) |
| 16 (A2) | 21/22 | `PACK_VOLTAGE` | AIN | Pack voltage, 16.2k/10k divider, 8.646 V full scale (same scale as `BT_VOLTAGE`) |
| 17 (A3) | 19/20 | `VLOAD_VOLTAGE` | AIN | Ag105 VLoad+ through 100k/47k, 10.32 V full scale; diagnostic |

The existing `BT_REG_ENABLE` (pin 4) keeps its pin and meaning, but its trace now ends at AND #2 on the switch
board, so the TPS61288 runs only while PERMIT is high (rework R10).

The existing pins keep their meaning with two changes. `BT_VOLTAGE` (25) now reads VBT, which equals the pack only
while Q_H is closed. `BT_SEQUENCE_ENABLE` (32) drives a D-BT-SQ whose output is isolated; firmware holds it LOW.

### 3.2 Control sequence per state

Table 10 lists the sequence. "Charge entry" and "charge exit" are the two procedures defined below the table; every
charging event uses them.

Table 10. Control sequence.

| State or event | Sequence | Hardware backstop |
|---|---|---|
| Boot (`setup()`) | 1. Drive every RT1987 EN LOW (existing, ino:6709-6715) and PACK_RELEASE LOW; BT_REG_ENABLE LOW. Q_H has normally closed by hardware before `setup()` runs (default allow), with the boost held off by AND #2. 2. Read PACK_VOLTAGE; require 7.4-8.5 V. 3. Require `VCHG-IN` (pin 38) below 2 V, CHG_PRESENT_RB low, OV_TAP_V below 0.4 V, PACK_PERMIT high, QB_DIODE low. 4. Require BT_VOLTAGE within 0.3 V of PACK_VOLTAGE (Q_H closed). 5. **Q2/HGATE self-test:** drive PACK_RELEASE HIGH; require PACK_PERMIT low within 1 ms and BT_VOLTAGE at least 1.5 V below PACK_VOLTAGE within 120 ms (VBT decays with tau 0.26 s; 1.5 V from 7.4 V takes 59 ms); then PACK_RELEASE LOW and BT_VOLTAGE back within 0.3 V in 20 ms. 6. Continue with the existing bring-up; P0 reads V_batt = VBT = pack. | Q_H cannot close while `VCHG-IN` is present |
| Idle (State 1) | PACK_RELEASE LOW. Charger paths LOW (existing). On every Idle entry, repeat the boot step-5 self-test (latent Q2 or HGATE short). | As above |
| Run, discharge (State 2) | PACK_RELEASE LOW; share loop as today. Every tick: QB_DIODE low; PACK_PERMIT high; with all charger ENs LOW, CHG_PRESENT_RB low and pin 38 below 2 V. | As above |
| Regen brake, mode R-a (event-triggered) | Charge entry on the brake command, then REGEN HIGH with MOT_PWR HIGH. Charge exit when V_rgn falls to V_bus or the brake ends. Misses the first VESC pulse (section 4.3). | Q_H opens at `VCHG-IN` above 5.96 V even if the entry steps were skipped |
| Regen brake, mode R-b (pre-warm) | **Conflicts with ruling R3 (2026-11-04: the bus must never feed the charger in Run) and is not part of the design unless the operator rules otherwise (Q1).** As revision 1: the charger runs from the FC bus through D-MT-EN and D-BC-RG during decelerations. | As above |
| FC charge window | Charge entry, then `assertFcChargeEnable(true)` (existing guard). Window ends at least 150 ms before the predicted purge (ruling 6). Charge exit. Re-acceleration is held off until the charge exit has completed. | As above |
| H-20 purge in discharge mode | No change; the pack is on the bus. | - |
| H-20 purge during a charging event | Predicted: charge exit before the purge (a precondition of entry). Unpredicted: the bus collapses (section 4.6); UV_BUS latches State 99. | None; this is the IC4 structural cost |
| Finish (State 3) | Charger paths LOW (existing), then charge exit if a charging event was active. | - |
| State 99 | **Phase 0: PACK_RELEASE HIGH first**, before the drains; keep it HIGH while latched. Phase 0/1 drains open FC_CHARGE and REGEN for about 10 ms each (ino:8299-8327); the barriers also hold Q_H open. Phase 2 as today. The Teensy stays powered from the pack. | Barriers |
| Teensy reset | GPIO high-Z: PACK_RELEASE low via 10 kOhm (pack allowed), BT_REG_EFF low via the pin-4 pull-down; RT1987 ENs low via the 10 kOhm bodge (OQ-7 open). If a charge window was active, `VCHG-IN` bleeds down, Q_B returns, and Q_H re-closes onto a disabled boost: a hardware charge exit. On restart, the boot sequence runs. | Pull-downs, barriers |
| Teensy hang | Outputs hold. If a charging event was active, charging continues, regulated and loop-free, on an FC-only bus; the RTWDOG resets the MCU, which then behaves as a reset. **A verified RTWDOG (T-W-01) is a precondition of any charging event**; without it, no charging event is started. | Barriers, Ag105 regulation, RTWDOG |

**Charge-entry preconditions** (checked before step 1; any failure refuses the event):

- `PACK_SWITCH_FITTED` set, the RTWDOG armed and T-W-01 recorded as passed; purge prediction available and no predicted
  purge inside the event length plus 150 ms plus the 48 ms exit time.
- No IC4 fault latched; the last boot or Idle self-test passed.
- Bus budget: the bus-side load I_fc + I_batt plus the estimated charger input at the configured code (Table 15) at
  most 1.15 A; for a regen event, a commanded motor current at or below 0 A (actual braking).

**Charge entry** (all steps in the 1 kHz path, not in the 50 Hz `chargingControl()`):

1. Disarm the share source selector and close FC_BUS through the guarded path. Require FC_BUS HIGH and out of its
   blanking for at least `RT1987_T_D_ON_MS` + `SHARE_CUT_SURVIVOR_BLANK_MS` = 8 + 30 = 38 ms (ino:4869-4881), and
   V_bus at least 15 V. When the share loop already has FC_BUS conducting and settled, this step costs nothing.
2. Drive BT_BUS_ENABLE LOW, then BT_REG_ENABLE LOW (back-feed rule, CLAUDE.md section 2). BT_REG LOW also discharges
   the TPS61288 soft-start capacitor (SLVSFP3C section 8.3.1). Require for 5 ms: V_bus at least 15 V, I_fc at least
   the pre-step total minus 0.1 A (the FC has taken the load), and I_batt below the INA253 floor (0.1 A,
   facts_prior section 10 item 11).
3. Drive PACK_RELEASE HIGH; require PACK_PERMIT low within 1 ms.
4. Power the charger (REGEN or FC_CHARGE through the existing guards).
5. **Concurrent checks during the Ag105 start-up (65-170 ms), each ending the event and latching a fault:**
   (a) VBT decay: BT_VOLTAGE at least 1.5 V below PACK_VOLTAGE within 120 ms (Q2 or HGATE stuck on); a shorted Q2
   holds VBT within one body-diode drop at 0.3 mA, which is below 1.5 V (UNCONFIRMED until the SLPS632 body-diode
   curve is read at that current; bench gate B17). (b) Tap agreement: within 2 ms of pin 38 exceeding 8 V,
   CHG_PRESENT_RB high and OV_TAP_V x 4.92 within 1 V of pin 38. (c) Ag105 reg 0x00 reads code 4 once the module
   ACKs; I2C dead or another code ends the event. (d) The existing bench-session guards G1/G2/G3 (fw v37 rev 2) run
   in every build.

**Charge exit:**

1. Drive FC_CHARGE_ENABLE and REGEN_ENABLE LOW.
2. Wait for `VCHG-IN` (pin 38) below 5 V and CHG_PRESENT_RB low. Expected 23-35 ms (section 4.3); a 100 ms timeout
   latches a fault (R_BL open).
3. Drive PACK_RELEASE LOW; require PACK_PERMIT high and BT_VOLTAGE within 0.3 V of PACK_VOLTAGE within 5 ms
   (EN-to-gate delay 98-270 us, SNOSD95C 7.6, plus the 0.8-1.5 ms ramp).
4. Drive BT_REG_ENABLE HIGH; wait the TPS61288 soft-start, 3 ms typical (SLVSFP3C section 7.5, T_SS), maximum not
   given (TODO(verify: SLVSFP3C)).
5. Drive BT_BUS_ENABLE HIGH through the existing guarded re-close (RT1987 t_D_ON 8 ms typical, DS-00 p.7).

## 4. Quantitative checks

### 4.1 Conduction loss at the peak BT current

The design peak is the 16.46 A BT-boost current recorded in the 2026-11-04 incident (facts_prior section 9). Whether
that figure is the boost input or output is not recorded (UNCONFIRMED); it is used here as the input current. The
in-service figure is about 3 A per channel at the bus (CLAUDE.md RC-BT bodge record), which is 16 V x 3 A / (7.4 V x
0.9) = 7.2 A at the pack with an assumed 90 % boost efficiency (UNCONFIRMED). Table 11 gives the losses.

Table 11. Conduction losses (R_DS(on) maxima at 25 C from SLPS632; hot values x 1.5, UNCONFIRMED pending SLPS632 Fig. 8).

| Element | R (25 C max) | Loss at 7.2 A | Loss at 16.46 A | Loss at 16.46 A, hot |
|---|---|---|---|---|
| Q1 + Q2 (V_GS >= 10 V) | 2 x 0.96 = 1.92 mOhm | 0.10 W | 0.52 W | 0.78 W |
| Q_B (V_GS 5 V, bounded by the 4.5 V figure) | 1.6 mOhm | 0.08 W | 0.43 W | 0.65 W |
| FET total | 3.52 mOhm | 0.18 W | 0.95 W | 1.43 W |
| Two added connector pairs at the TB005 maximum (20 mOhm each) | 40 mOhm | 2.1 W | 10.8 W | - |

The FET path drops 58 mV at 16.46 A. The added interconnect, not the FETs, dominates the loss if connectors of the
TB005 class are used at their maximum contact resistance. Connectors with a specified contact resistance well below
1 mOhm are therefore a requirement (TODO(select)). A junction rise of 0.43 W x 40 C/W = 17 C for Q_B at the incident
peak is acceptable on the SLPS632 reference copper; the switch board must provide comparable copper (UNCONFIRMED).

### 4.2 SOA and inrush at Q_H turn-on

At turn-on, Q2 charges the VBT capacitance. With BT_REG LOW, the disabled TPS61288 passes VBT to VOUT-BT through its
body diode (CLAUDE.md section 2), so the charged capacitance includes the boost output capacitors. Table 12 gives the
inrush with C_dVdT = 6.8 nF (5.7-11.0 V/ms).

Table 12. Q_H turn-on inrush.

| Capacitance | Value (nominal) | Inrush at 5.7-11.0 V/ms |
|---|---|---|
| C1-BT + C2-BT (BOM line 3; SCH) | 10.1 uF | 0.06-0.11 A |
| C4A/B/C-BT (BOM line 6, 3 x 22 uF 25 V X7R 1210) | 66 uF | 0.38-0.73 A |
| Total | 76 uF | 0.43-0.84 A |

The ramp to 8.5 V lasts 0.77-1.5 ms. The peak Q2 dissipation is about 8.5 V x 0.84 A = 7.1 W at the start of the ramp,
falling linearly, for at most 1.5 ms. Whether this point lies inside SLPS632 Figure 10 has not been read numerically:
TODO(verify: SLPS632 Fig. 10). Derating of the MLCCs at 8 V reduces the inrush; the derated total is BENCH (finding
X8). Because VBT decays slowly (time constant 0.26 s), a Q_H re-close after a short charging event starts from a
partly charged VBT and the inrush is shorter.

### 4.3 Timing

Table 13 lists the timing of the charge entry and exit and compares them with the regen burst and the Ag105 start-up.

Table 13. Timing budget.

| Step | Duration | Source |
|---|---|---|
| Firmware reaction to a brake command | <= 1.3 ms (1 kHz path; median loop 1131 us, worst gap 9.76 ms) | facts_firmware section 8 |
| FC_BUS conducting and out of blanking (entry step 1) | 0 ms if already settled; otherwise 38 ms | ino:4869-4881; Section 3.2 |
| BT_BUS and BT_REG LOW, load-transfer check | 5-6 ms | Section 3.2 |
| PACK_RELEASE HIGH to Q2 off | About 0.1 ms EN RC delay, 3-6 us deglitch, gate discharge <= 1 us (168 mA min sink into <= 153 nC) | Section 2.4; SNOSD95C 7.5, 7.6 |
| Q2-short (VBT decay) check | Runs concurrently with the Ag105 start-up; no added latency | Section 3.2 |
| RT1987 turn-on of D-BC-RG or D-BC-FC | 8 ms typical t_D_ON, plus about 1.3-1.8 ms soft-start to 16-21 V at 12 V/ms | DS-00 p.7 via facts_prior section 5 |
| Ag105 start-up to charge current | Not given by the datasheet (TODO(verify: Silvertel)); 65-170 ms cold start in the prior study | facts_ag105 section 6; facts_prior section 6 |
| **Entry total, cold (mode R-a)** | **about 80-225 ms (FC_BUS settled) or 118-263 ms (FC_BUS closed at entry)** | Sum |
| VCHG-IN decay to the T_OV release (5.04-5.43 V) after exit | About 0.3 ms from 16 V to the 11 V UVLO while the Ag105 still draws its charge power (UNCONFIRMED), then 30 ms x ln(11/5.04) = 23 ms through R_BL | Section 2.5 |
| LM74800 EN-to-gate turn-on delay | 98-270 us | SNOSD95C 7.6 (as cited by the electrical reviewer) |
| Q_H ramp | 0.8-1.5 ms | Section 4.2 |
| TPS61288 soft-start | 3 ms typical | SLVSFP3C 7.5 |
| BT_BUS re-close | 8 ms typical | DS-00 p.7 |
| **Exit total (pack back on the bus)** | **about 36-48 ms plus the unspecified maxima** | Sum |

The regen comparison follows from Table 13. The first VESC pulse ends 19-47 ms after onset and the VESC re-pulses
0.523-0.562 s later; the burst lasts 0.3-0.6 s (facts_prior section 6). The firmware regen trigger is the commanded
motor current (`regenActive = (current < -0.1f)`, ino:15336), so on a hard brake the brake command and the regen
onset arrive together. In mode R-a, the 80-263 ms entry therefore misses the first pulse on every event, which is
finding X6, and the capture falls on the 6-40 % side of the capture cliff. The switch itself contributes under 1 ms
of this budget; the FC_BUS settle, the Ag105 start-up and the RT1987 turn-on dominate.

Mode R-b (revision 1) claimed to remove the entry from the critical path. Review round 1 showed that it does not:
without a look-ahead signal, which the 22-byte command packet does not carry, a deceleration command arrives together
with the regen onset, and holding charge mode through all coasting multiplies the FC-only-bus exposure of section
4.6. Mode R-b also feeds the charger from the bus in Run, which ruling R3 forbids. The following paragraph is kept
only as the record of what R-b would need. Its capture would depend on the Ag105 warm response (tau <= 4 ms required at 0.97 mF, facts_prior
section 6), which is unmeasured for every concept. The Ag105 Bring-Up ramp (0.64 V/s in ML0227) does not apply to
IC4: the battery is always on the battery port, so the module detects a battery at every power-up and does not ramp
into an open node (DS p.6). Whether the module's detection still ramps the current from zero, and how long that
takes, is not given (TODO(verify: Silvertel); BENCH gate B3).

### 4.4 Q_H turn-off under load

In normal operation Q_H opens at near-zero current (charge entry step 2). Revision 1 also opened Q_H at full load on
every Teensy reset, brown-out or open request wire, because the request pulled down to "off". Revision 2 inverts the
request (section 2.4), so these events leave Q_H closed. The remaining causes of a hard turn-off are a barrier trip
while firmware has skipped the entry steps, an open W_OV, and loss of the switch-board 5V or 3V3 supply. These are
fault cases, but they are not rare enough to be ignored, so the boost-first interlock (AND #2) stops the TPS61288
about 0.1 ms before Q2 starts to turn off. Two effects remain.

- **Pack side.** The harness inductance is unknown; with an assumed 1 uH (UNCONFIRMED), the stored energy at 16.46 A
  is 0.5 x 1 uH x 16.46^2 = 0.14 mJ. This is far below the 328 mJ E_AS of the CSD18510Q5B (SLPS632 p.1), and TVS1
  limits the voltage. Harness inductance is BENCH.
- **VBT side, without the interlock (revision 1).** The TPS61288 inductor (2.2 uH, L-BT) keeps drawing current from
  VBT, and C1-BT (10 uF) supplies it. VBT falls at up to 16.46 A / 10 uF = 1.6 V/us until the boost stops at its VIN
  UVLO (1.8-2.0 V falling, SLVSFP3C section 7.5). The residual inductor current then pulls VBT below GND. A Schottky
  clamp at 16.5 A drops about 0.4-0.5 V (UNCONFIRMED, part-dependent), which violates the TPS61288 VIN absolute
  minimum of -0.3 V (SLVSFP3C 7.1). No passive clamp was found that meets that limit.
- **VBT side, with the interlock (revision 2).** The boost stops switching while Q_H still conducts, so the inductor
  current decays into VOUT-BT with the pack still holding VBT. Q2 then opens at a current set by the TPS61288 stop
  behaviour, which is TODO(verify: SLVSFP3C EN-to-stop time). D_CLAMP stays fitted as a secondary clamp. **Bench gate
  B7 (full 16 A current, scope on VBT, VIN-BT and P_POS) must pass before the module is fitted to the vehicle.**

### 4.5 Teensy supply continuity

The LM1084 input moves to P_POS through F3 and cut R2 (section 7). Q_H transitions therefore do not touch the logic
supply. The LM1084 regulation range is 6.5-20 V (SNVS037H section 5.5) and its dropout is 1.5 V maximum at 5 A
(SNVS037H p.1). Table 14 gives the input voltage in each mode.

Table 14. LM1084 input voltage relative to PCB GND.

| Mode | V(LOGIC_IN) - V(GND) | At pack 7.4 V |
|---|---|---|
| Discharge (Q_B on) | V_pack - I_return x 1.6 mOhm | 7.37 V at 16.46 A |
| Charge, Ag105 delivering | V_pack + I_chg x (R_s + R_QA), so slightly above the pack voltage | >= 7.4 V |
| Charge, Ag105 idle (Fully Charged), Q_A on | V_pack - I_logic x (R_s + R_QA) | about 7.4 V |
| All logic rails absent, both low-side FETs off (start-up only) | V_pack - V_SD(Q_B body diode, 0.8-1.0 V) | 6.4-6.6 V |

The last row is the only marginal case. It exists for the interval between pack connection and the UCC27524A
reaching its UVLO (3.8-4.4 V on the 5V rail), during which the LM1084 starts through the Q_B body diode. At a 7.4 V
pack the input is 6.4-6.6 V against the 6.5 V regulation minimum, so the 5V rail may come up slightly low; the
UCC27524A then turns Q_B on and the input rises to the pack voltage. This start-up has no feedback path into a reset
loop, because Q_B is keyed on CHG_ABSENT and not on the Teensy. It is still bench gate B9 at a 7.4 V pack.

Q_B is keyed on CHG_ABSENT and not on the Teensy request. Keying it on the request would leave the logic return on
the body diode whenever the pack is released, which at a 7.4 V pack can brown out the Teensy and hold the request in
its default state, a self-sustaining lockout.

**Logic load in charge mode (review round 1).** In charge mode Q_B is off, so the logic current drawn from P_POS
(LM1084, about 0.1-0.3 A, BENCH) returns through GND into the Ag105 Vin- node. While the module delivers current, its
sense carries the pack current only, so the converter output is the set current plus the logic current. When the
module is idle (Fully Charged or terminated), the pack supplies the logic load and that current crosses the sense in
the discharge direction. Whether the over-current trip (set + 200 mA, DS p.18) acts on the sense or on the converter
output, and how termination and re-charge behave under a standing discharge current, are not stated
(TODO(verify: Silvertel); facts_ag105 section 1.4). Bench gate B3 is therefore run with the F3 logic lead and the full
Teensy and 5V load connected, and the charge code is chosen with margin for the measured logic current.

### 4.6 The FC-only bus during charging events

Every charging event in IC4 runs with the pack off the bus. Table 15 quantifies the consequences.

Table 15. Bus budget and purge exposure during charging events.

| Quantity | Value | Basis |
|---|---|---|
| Charger input at code 4 (1.5 A, Table 4 JSON), 8.4 V | 8.4 x 1.5 / 0.88 / 16 = 0.89 A at 16 V | DS p.20 efficiency 88 % (specified only at 12 V in, 3S: UNCONFIRMED here) |
| Charger input at code 1 (2.5 A) | 1.49 A | Exceeds the 1.25 A governor and the 1.247 A P_MAX (finding X5) |
| Aux load | 0.10-0.15 A | facts_prior section 7 |
| FC bus total at code 4, standstill | 0.99-1.04 A | Below 1.25 A; 0.21-0.26 A of traction headroom |
| Regen absorption ceiling at code 4 | 1.5 A x 8.4 V / 0.88 = 14.3 W | Below the 18.9 W peak of a 3 -> 1 m/s brake; above the 11.1 W peak of 2 -> 1 m/s (facts_prior section 6) |
| Bus fall rate with no battery | 2.57 V/ms | facts_prior section 7 |
| Time from 16 V to the 12 V UV_BUS threshold | 1.6 ms | Calculation |
| Pack return latency (exit total) | 36-48 ms plus maxima | Table 13 |
| Purge overlap probability for one 0.6 s regen event | (0.6 + 0.14 + 0.048) / 10.34 = 7.6 % | Purge period 10.34 s, duration 100-140 ms (facts_prior section 7) |
| State-99 probability, 8 brakes per cycle, no purge prediction | 1 - 0.924^8 = 47 % | State 99 latches until a power cycle (facts_firmware line 35) |

The pack return latency exceeds the bus collapse time by a factor of about 25. IC4 therefore cannot rescue the bus
from an unpredicted purge during a charging event. Bus hold-up is not a rescue either: carrying about 1.04 A for
45 ms with a 4 V sag needs 11.7 mF on VBUS, which the 12 mA/uF hot-plug rule turns into a 140 A inrush. The only
mitigation is purge prediction (ruling 6), applied to regen events as well as FC windows: a charging event is
refused, or ended at least 150 ms early, when a purge is predicted inside it. With a 0.6 s event this refuses about
8 % of brakes. Purge prediction is therefore a hard precondition of every charging event (section 3.2), not an
optimisation. The prediction accuracy (+/-20 ms per edge) and the load dependence of the purge schedule are open
(bench gate T-E-01).

On the bus budget, the 0.21-0.26 A of traction headroom at code 4 means that FC charge windows are feasible only
near standstill. The entry preconditions enforce this through the 1.15 A bus-load check. Dropping BT_BUS also steps
the FC from about 0.1 A (battery-only arm at light load) to about 1.0 A within one RT1987 transition, onto an H-20
under the 1000 ms UV_FC dwell, with the inherited-MDAC-code turn-on overshoot of campaign G finding F7. Re-acceleration
is therefore held off until the charge exit has completed and PACK_PERMIT reads high.

A code-4 ceiling is a single EPROM-stored setting; changing reg 0x00 per event would consume EPROM writes of unknown
endurance (DS p.13 Table 7; facts_ag105 section 9). This document therefore assumes one fixed setting, read back
before every event. Benefit, the FC budget holds in every window; however, regen absorption is capped at 14.3 W,
which is below the 23 W charger-input condition of HR1 (facts_prior section 2.1), so IC4 fails HR1 at code 4.
Code 1 (2.5 A, 23.9 W) meets the HR1 power condition but draws 1.49 A from the FC bus, above the 1.25 A governor,
and fails HR2. The only candidate resolution found is resistor mode (reg 0x00 = 0x00) with a Teensy-switched RCS
resistor (Table 4 JSON: 39 kOhm = 1.5 A, 200 kOhm = 2.5 A); whether the module re-reads RCS while running is
TODO(verify: Silvertel) and bench gate B18. In the input-threshold method of the always-powered concepts the charger
idles warm on the bus until V-MOT rises; that method is unavailable in IC4, because any voltage on `VCHG-IN` opens
Q_H.

### 4.7 Reference shifts

Table 16 lists the measurement references. R_s is the unknown Ag105 sense resistance; R_QA = 1.6 mOhm maximum.

Table 16. Reference shifts relative to PCB GND.

| Measurement | Reads | Error in discharge (16.46 A) | Error in charge (2.5 A) |
|---|---|---|---|
| `BT_VOLTAGE` (pin 25, R1-BT/R2-BT to GND) | VBT | -58 mV against the pack (FET drop) | Not the pack: VBT is unsourced and decays |
| `PACK_VOLTAGE` (pin 16, new) | P_POS to GND = V_pack + V(P_NEG) - V(GND) | -26 mV (Q_B drop) | +I_chg x (R_s + 1.6 mOhm); reads high, which causes OV_BATT nuisance trips unless corrected (below) |
| INA253 SNS-BT (boost output side, GND-referenced) | Unchanged | None | None (boost off) |
| BQ29200 bottom cell (VC1 - GND, SLUSA52C section 7.5) | V_cell1 + V(P_NEG) - V(GND) | -26 mV | +2.5 A x (R_s + 1.6 mOhm) |
| BQ29200 during start-up with Q_B off | V_cell1 - 0.8..1.0 V | - | - |

The charge-mode offset makes the BQ29200 bottom-cell reading high, which is the conservative direction for OVP but
could trip it early near the 4.35 V/cell threshold (SLUSA52C p.5, via facts_prior section 5) if R_s is tens of
milliohms. The BQ29200 OUT pin is still unconnected, so an early trip actuates nothing. The size of the offset is
bench gate B2.

**OV_BATT in charge mode (review round 1).** Revision 1 moved OV_BATT to `PACK_VOLTAGE` and called the charge-mode
offset conservative. That is wrong for nuisance trips. At the CV transition `PACK_VOLTAGE` reads 8.4 V plus
I_chg x (R_s + R_QA), plus half the 100 mVp-p output ripple (DS p.20 row 9), plus the CV setpoint tolerance (not
given) and about +/-85 mV of 1 % divider error. With R_s of about 20 mOhm at a 1.5 A CV entry the nominal reading is
about 8.48 V against the 8.5 V `LIMIT_V_BATT_MAX` (fw v30). Revision 2 therefore applies OV_BATT in charge mode to
the corrected value PACK_VOLTAGE - (reg 0x06 current) x (R_s + R_QA), with R_s from bench gate B2 and the residual
margin `TODO(calibrate)`. In discharge mode the existing 8.5 V limit applies unchanged.

### 4.8 Pack standby drain

The pack now feeds the Ag105 battery port permanently. The module draws 120-420 uA from the battery with no input
(DS p.20 row 7), which is 2.9-10 mAh per day, plus about 0.08 mA for the two new dividers and 5 uA for the LM74800 in
shutdown (SNOSD95C section 7.5). Today D-BT-SQ blocks this drain. The pack must therefore be unplugged in storage,
as it already must be for the Teensy load.

## 5. Single-fault table

Table 17 lists the single faults and their outcomes. "Loop" means the circulating path bus to charger to VBT to BT
boost to bus. A fault is acceptable when its outcome is bounded and either detected or harmless.

Table 17. Single faults (revision 2).

| Fault | Outcome | Detection | Acceptable |
|---|---|---|---|
| Q2 short (drain-source), or HGATE stuck high (LM74800 internal fault) | P_POS reaches VBT (through the Q1 body diode for a Q2 short) whenever Q_H is commanded off. Both barriers act through this actuator, so neither helps. A loop needs BT on the bus while the charger is powered; firmware holds BT_BUS and BT_REG LOW (AND #2 does not help, because PERMIT is low) | VBT-decay self-test at boot and at every Idle entry (1.5 V threshold); concurrent VBT-decay check in every charging event; new all-build switch-conflict fault | Yes as a detected latent fault; a loop needs this fault plus a firmware error |
| Q1 short | Reverse blocking lost; VBT has no other source | None needed | Yes |
| T_OV top resistor open, or OV pin stuck low | OV barrier lost silently; the logic barrier (separate tap) still holds Q_H open | OV_TAP_V x 4.92 disagrees with pin 38 at the first charging event (entry check 5b) | Yes; detected before the next event |
| W_OV open | OV pin pulled to VS; Q_H opens (in discharge: a hard turn-off under load, section 4.4) | BT_VOLTAGE falls below PACK_VOLTAGE; boot self-test | Yes (fails toward pack-off) |
| T_LG top resistor or W_LG open; TLV7012 #1 ch1 stuck low | Logic barrier and steering read "absent": Q_B stays on and Q_A off during a charge, so the sense is bypassed. The OV barrier (separate tap) still holds Q_H open, so there is no loop | Entry check 5b: pin 38 above 8 V without CHG_PRESENT_RB within 2 ms; the event ends before the Ag105 delivers current (start-up 65-170 ms) | Yes, provided the check runs in every build |
| TLV7012 #1 ch2 stuck high (CHG_ABSENT) or UCC27524A OUTA stuck high | Q_B stays on during charge: sense bypassed. No loop: the OV barrier holds Q_H open | Not seen by check 5b (CHG_PRESENT_RB is correct); seen by the G2-style check (reg 0x06 near zero while V_chg and I_fc show charger power) | Bounded, not prevented: F2 (3 A) and the source bound the pack current; detection is firmware |
| TLV7012 #1 ch1 stuck high (CHG_PRESENT) | Q_B off and permit low in discharge: Q_H hard turn-off under load (interlocked boost), then the logic load runs on the Q_B body diode | QB_DIODE; BT_VOLTAGE vs PACK_VOLTAGE; boot | Yes (fails toward pack-off) |
| Q_B short | Sense bypassed during charge (no loop) | G2-style check | Bounded, not prevented (F2, source) |
| Q_B open (die), gate healthy | Discharge return on the Q_B body diode, 13-16 W at 16.46 A | QB_DIODE at 1 kHz, fault and State 99 within milliseconds | Yes, with firmware; a firmware hang falls to the RTWDOG |
| Q_B gate drive lost (5V wire, UCC27524A UVLO, gate trace open) | Q_B off; AND #1 input C low, so Q_H opens (hard turn-off, interlocked boost) | PACK_PERMIT low with PACK_RELEASE low | Yes (fails toward pack-off) |
| Q_A short | Discharge return splits into the module sense path by resistance ratio | None direct | Conditional on R_s (B2); if the split can exceed 4 A, a second series element is needed |
| Q2 open | Q_H never closes; boot stops at step 4 | Boot check | Yes |
| PACK_RELEASE stuck low or pin 34 not driven | Q_H follows the barriers only (the default) | Entry step 3: PACK_PERMIT stays high | Yes; no event starts |
| Pin 35 driven HIGH (`pinMode` error, `Serial8`) | EN stays below 1.195 V in every gate state (section 2.4) | None needed | Yes |
| D-BT-SQ VOUT cut incomplete (R3) | D-BT-SQ links pack positive to VBT outside Q_H; a loop exists if BT_SEQUENCE_ENABLE goes HIGH or if RT1987 EN-low does not block forward conduction (TODO(verify: DS-00 block diagram)) | Continuity test after the cut (B8) | Yes only after B8 |
| LM1084 trace cut R2 incomplete | P_POS reaches VBT through the logic lead, a 1 A-fused bypass of Q_H; a loop through it is fuse-limited only | Continuity test (B8) | Yes only after B8 |
| Balance-lead negative re-bonded | Not possible with J-BL pin 3 cut on the board (R11) | B8 | Yes after R11 |
| External parallel return (pack NTC, chassis, other device on pack negative) | Sense bypassed in charge | Isolation test P_NEG to GND with Q_B off (B8) | Requires B8 |
| R_BL open | VCHG-IN decays with tau 1.77 s; the exit stalls | Exit step 2 timeout (100 ms), fault | Yes |
| J-BT pin 2 lead open | Board return through the 4.7 Ohm ground wire until it fuses | Board loss of power | Yes |
| F1 opens | Pack lost; Teensy loses supply; all RT1987s default off | - | Yes |
| F2 opens | Charging impossible; Ag105 reports Battery Disconnect | GENSTAT 0x00 in a charge window | Yes |
| Teensy reset during a charging event | Hardware charge exit: RT1987 ENs fall (OQ-7), VCHG-IN bleeds, Q_H re-closes onto a disabled boost | Boot | Yes, after B10 |
| Teensy hang during a charging event | Charging continues, regulated and loop-free, bus FC-only; a purge collapses the bus | RTWDOG (a precondition of every event) | Bounded; purge exposure for up to the RTWDOG period |
| Teensy hang in discharge | Run continues at the last command | Pi watchdog, RTWDOG | As today |
| RT1987 D-BC-FC or D-BC-RG short | Charger always powered: Q_H permanently open, board cannot leave charge mode | Boot check step 3 | Yes (fails safe, board unusable) |

The table shows two residual classes that no part choice in revision 2 removes. (1) An actuator fault (Q2 short or
HGATE stuck high) leaves firmware as the only layer that keeps BT off the bus while the charger is powered; the fault
is detected as a latent fault at every boot, every Idle entry and during every event. Two series forward-blocking
FETs would close this gap at the cost of a second controller or a custom gate drive (open question Q4). (2) A
stuck-on low-side element (Q_B short, OUTA stuck high, CHG_ABSENT stuck high) bypasses the module sense during a
charge. It is loop-free, bounded by F2 (3 A) and by the source (on the vehicle, the OC_FC latch at 1.4 A; on the
bench, the supply current limit), and detected by firmware, but it is not prevented. A series-redundant Q_B driven
from the T_OV chain would make it a double fault, at the cost of a second gate driver, a comparator on T_OV with its
own input-range limit, and a further 0.43 W at 16.46 A (open question Q6).

## 6. HR1-HR5 status

Table 18 states the status of each hard requirement after review round 1.

Table 18. Hard-requirement status (revision 2).

| ID | Status | Reason |
|---|---|---|
| HR1 Regen harvesting | FAILS | Mode R-a misses the first pulse on every event (80-263 ms entry against a 19-47 ms pulse; the trigger is the brake command itself). The code-4 ceiling gives 14.3 W against the 23 W charger-input condition. Mode R-b has no lead time without a look-ahead protocol extension and conflicts with ruling R3. A path out needs an operator ruling (Q1) and the resistor-mode RCS switch (B18) |
| HR2 FC charging | BENCH (standstill only) | Code 4 gives 0.99-1.04 A at standstill, below the 1.25 A governor, with 0.21-0.26 A of traction headroom. Purge prediction (T-E-01) and a verified RTWDOG (T-W-01) are hard preconditions; entry from a battery-only arm is safe only with entry step 1 |
| HR3 No circular loop | PROVEN_CALC (structural) for sensing faults; detected-latent for actuator faults | VBT has no source while `VCHG-IN` is present: two barriers on separate taps, D-BT-SQ and the LM1084 feed removed from VBT. A Q2 short or stuck HGATE is covered by the VBT-decay self-tests and firmware, not by a second actuator |
| HR4 No runaway | BENCH | The restored sense is the hardware ceiling (B3, the premise of the concept). Sense-bypass faults (Q_B short, OUTA or CHG_ABSENT stuck high, external return) are bounded by F2 and the source and detected by firmware, not prevented. The logic load returns through the module in charge mode (section 4.5); its effect on the OC trip and termination is unverified |
| HR5 Fail-safe inhibit | BENCH | A reset is now a hardware charge exit (default allow plus the RT1987 EN pull-downs, OQ-7 open). A hang requires the RTWDOG, which is a precondition of every event. IC4 adds no charger inhibit while the MCU is hung and the charger is powered |

**Ruling question.** Ruling 3 permits the bus to feed the charger only if the charger can be inhibited while powered,
and the later ruling R3 (2026-11-04) forbids the bus feeding the charger in Run. IC4 does not add an inhibit; it makes
a powered charger loop-free by topology. Mode R-b conflicts with R3 directly. Whether a structural loop break
satisfies the substance of ruling 3 for FC windows at standstill is an operator decision (open question Q1).

## 7. Rework on the manufactured board

### 7.1 Steps

The rework uses no new board copper. Each step names its location from the BRD.

1. **R1, lift VBat-.** Cut Ag105 pins 14 and 15 above the board, one at a time, leaving the GND-connected barrels
   unused (incident.md recommendation via facts_board section 4.3). Join the two pin stubs and solder an 18 AWG flying
   lead to them. Pads VBAT-1 (21.0, 56.86) and VBAT-2 (21.0, 54.32).
2. **R2, move the LM1084 feed.** Cut the bottom-layer VBT segment between the vias at (46.99, 34.54) and
   (57.66, 34.54) (BRD signal VBT, 1.016 mm, layer 16). Downstream of the cut are REG-5V pad 3 and CIN-5V pad 1, so both
   move to `LOGIC_IN`. Solder the F3 logic lead to the via at (57.66, 34.54) or to CIN-5V pad 1 (about 61.7, 40.5).
   The cut lies inside the bottom GND pour; the cut must sever the trace without bridging to the pour.
3. **R3, isolate D-BT-SQ.** Cut the top-layer 1.524 mm VBT branch from (34.80, 31.75) to (34.80, 48.65) (BRD signal
   VBT). D-BT-SQ VOUT and C-D12 become the isolated stub `DBTSQ_OUT`. This one cut replaces the brief's EN-trace cut,
   and it removes any dependence on the RT1987 off-state blocking. Firmware holds pin 32 LOW.
4. **R4, charge lead.** Solder the F2 charge lead (18 AWG; F2 3 A) to C-D11 pad 1 at about (26.2, 50.3), on the
   `VCHG` pour.
5. **R5, taps and bleed.** Mount the T_OV divider (39.2 kOhm from C-D8 pad 1 = VCHG-IN, 10 kOhm to the C-D8 GND pad)
   and the 1.5 kOhm 1 W bleed at C-D8. Mount the T_LG divider (100 kOhm / 10 kOhm) at C-D10; which C-D10 pad is
   VCHG-IN is TODO(verify: BRD contactref C-D10). Run two separate 26 AWG wires, W_OV and W_LG, to the switch board.
6. **R6, VLoad tap.** Mount the 100 kOhm resistor on Ag105 pin 21 (VLOAD+1, isolated pad at (21.0, 39.08)) and run a
   26 AWG wire to J2, where the 47 kOhm bottom resistor and the pin-17 connection are made.
7. **R7, signals.** Solder 26 AWG wires to the J2 receptacle tails: pins 34 (J2 45/46), 35 (43/44), 33 (47/48),
   21 (11/12), 22 (09/10), 16 (21/22), 17 (19/20), 3V3 (05/06) and 5V (01/02), and the fused ground wire (03/04,
   through R_GW 4.7 Ohm at the switch board). Mount R_PV2 (10 kOhm) at J2 21/22 to GND (J2 03/04).
8. **R8, harness.** Build the switch board into the pack harness: pack positive through F1 to P_POS, pack negative to
   P_NEG, Q2 source lead to J-BT pin 1, Q_B source lead to J-BT pin 2. Use one polarised housing for the pack
   connection. The balance lead carries VBAL+ and VMID to J-BL pins 1 and 2 only.
9. **R10, BT boost enable through AND #2.** Cut the top-layer 0.254 mm `EN-REG-BT` segment from (45.091, 21.999) to
   (45.091, 25.775), next to REG-BT pad 6 (BRD signal EN-REG-BT; members REG-BT pad 6, Teensy pin 4, J1 11/12). Solder
   a 26 AWG flying lead from the REG-BT side stub (`BT_REG_EFF`) to AND #2 Y, and a second lead from the Teensy side
   (J1 11/12) to AND #2 A. If an OQ-7 EN pull-down is fitted on the REG-BT side, it stays on `BT_REG_EFF`.
10. **R11, disable J-BL pin 3.** Remove the clamp screw of J-BL position 3 (11.43, 30.48) and fill the wire entry
    with epoxy, so that no lead can be clamped there. The pad stays on GND; no copper is cut. This replaces the
    revision-1 "keyed adapter", which a screw terminal cannot enforce (BOM line 52, TB005-762-03BE).
11. **R9, continuity verification (B8)** before any power: P_POS to VBT open with Q_H off; P_POS to `DBTSQ_OUT` open;
    VBT to `LOGIC_IN` open; P_NEG to GND above 1 kOhm with Q_B off and the pack disconnected; Ag105 pin-14/15 stubs to
    GND open; J-BL position 3 blocked; Teensy pin 4 to REG-BT pad 6 open.

### 7.2 Parts list and cost

Table 19 lists the parts. Prices are order-of-magnitude estimates, not quotations: TODO(verify: distributor price).

Table 19. Parts list (revision 2).

| Qty | Part | Function | Estimate (USD) |
|---|---|---|---|
| 1 | LM74800QDRRRQ1 | Q_H controller | 2-4 |
| 4 | CSD18510Q5B | Q1, Q2, Q_A, Q_B | 8-14 |
| 1 | UCC27524A (DGN) | Low-side drivers | 1-2 |
| 2 | TLV7012 | T_LG decision and inverse; Q_B body-diode detector and request inverter | 2 |
| 2 | SN74LVC1G11 | AND #1 (permit), AND #2 (boost-first interlock) | 1 |
| 3 | Fuses with holders (25 A, 3 A, 1 A) | F1-F3 | 6-15 |
| 1 | TVS, 3 Schottky | TVS1, D_CLAMP, D_RV2, D_RV3 | 2-5 |
| - | Passives (1 % resistors, 4.7 Ohm fusible, C_dVdT 6.8 nF C0G, 10 nF, 100 nF, 1.5 kOhm 1 W) | - | 3-5 |
| 2 pairs | Low-resistance polarised power connectors | Harness | 5-15 |
| 1 | 2-layer switch PCB (SON 5x6 packages need a PCB, not perfboard) | Carrier | 10-30 |
| - | Wire (12-14 AWG power, 18 AWG, 26 AWG), heat-shrink, epoxy | Harness and flying leads | 5 |
| | **Total** | | **about 45-100** |

## 8. Firmware, telemetry and HIL impact

### 8.1 Firmware

The firmware changes are the largest of any concept in this study, because IC4 changes what VBT is. They amount to a
firmware and HIL round on the scale of fw v28. The changes are as follows:

- CSV amendment for pins 16, 17, 21, 22, 33, 34 and 35 (Table 9), with `Serial8` (pins 34/35) reserved; new macros
  with the CSV Code Names.
- `setup()`: PACK_RELEASE LOW and BT_REG_ENABLE LOW with the other ENs, then the boot sequence and Q2/HGATE
  self-test of Table 10. The self-test repeats at every Idle entry.
- New functions `packOnBus()` and `packOffBus()` that implement charge exit and charge entry, including the
  preconditions, the FC_BUS-first step, the load-transfer check and the concurrent checks. Every charger power edge
  (`assertFcChargeEnable(true)`, the regen branch, the `J` session, State-98 keys `4` and `5`) must pass through
  `packOffBus()` first.
- The converse is also required: every BT_BUS and BT_REG HIGH write site must refuse while the pack is released or
  the charger input is live. The sites are `BT_BUS_ENABLE` at ino 8670 (`2`), 12762 (`assertFcChargeEnable`), 12905
  (P0), 13463 and 13570 (share latch), 14893 and 14904 (`applyShareRatio()`), 15321, 15361, 15392 and 15526
  (`chargingControl()`), the selector BT re-arm, and the BT_REG write sites including P0 (12936-12938) (facts_firmware
  line 42; the BT_REG list is TODO(verify: grep of the .ino)).
- The regen branch of `chargingControl()` keeps BT_BUS HIGH today (ino:15361). Under IC4 that branch must take BT off
  the bus through `packOffBus()`, and the regen decision must move to the 1 kHz path.
- A new switch-conflict fault, (any charger EN HIGH or CHG_PRESENT_RB high) while (BT_BUS or BT_REG HIGH), compiled
  in **every** build. The existing `FAULT_SWITCH_CONFLICT` check is inside `#if !BENCH_TEST` (ino:7413-7419) and is
  absent from the bench build on the board; IC4 must not rely on it.
- The new checks (QB_DIODE, tap agreement, VBT decay, PACK_PERMIT against PACK_RELEASE, exit timeout) and the
  G1/G2/G3 guards of fw v37 rev 2 run in every build.
- `AG105_VBATN_ISOLATED` (ino:5078-5085) describes the lifted VBat-; it may be set to 1 only after bench gates B2, B3
  and B8. A new flag, `PACK_SWITCH_FITTED`, gates the IC4 paths, and charging stays refused until the RTWDOG
  (T-W-01) and purge prediction (T-E-01) are in place.
- Faults: UV_BATT moves from `BT_VOLTAGE` to `PACK_VOLTAGE` (VBT is unsourced in charge mode); OV_BATT moves to
  `PACK_VOLTAGE` in discharge mode and to the sense-corrected value in charge mode (section 4.7).
- State 99: PACK_RELEASE HIGH at phase 0, before the drains.
- Reg 0x00 is read back in every charging event; a code other than the configured one, or no ACK, ends the event.
- `BT_SEQUENCE_ENABLE` is retired in practice (held LOW); PLAN.md and the CSV notes must say so.

### 8.2 Telemetry

`switch_state` has two spare bits (facts_firmware section 7); they carry PACK_RELEASE and PACK_PERMIT. PACK_VOLTAGE
and the new detector bits need new fields, which changes the layout: protocol v5, with the byte count and checksum
span recomputed and the Pi bridge updated in lockstep (protocol-bump procedure). BLG: one new voltage field and the
new bits.

### 8.3 HIL

The simple plant (`tools/hil_plant_sim.py`) keeps the pack permanently connected and models no VBT node; it needs a
VBT node separate from the pack, the Q_H state with its barrier logic and the AND #2 interlock, the charger on the
battery port, and the FC-only bus during charging events (facts_firmware section 9). The hi-fi engine already gates
the pack into the BT boost input with `BT_SEQ` (`tools/hil_electrical.py:2069-2240`), which is close to IC4's Q_H by
coincidence; it must be re-keyed to PACK_RELEASE and the barrier, and `BT_SEQ` must lose that meaning. The 18-byte
observation frame and the aux byte are full, so the new switch states need a frame extension (`docs/HIL_MODE.md`).
Every charge-window HIL leg must be re-pinned, and a new leg must start a charge entry from a battery-only arm.

## 9. Open questions and bench gates

### 9.1 Open questions

1. **Q1.** Does a structural loop break without a charger inhibit satisfy ruling 3, and is mode R-b (bus-fed charger
   in Run) admissible under ruling R3? (Operator ruling.) Without it, only mode R-a and standstill FC windows remain.
2. **Q2.** Is an FC-only bus during every charging event acceptable, given the 7.6 % purge overlap per 0.6 s event
   (47 % State-99 probability per 8-brake cycle without prediction)? (Operator ruling.)
3. **Q3.** Is the code-4 (1.5 A) fixed setting acceptable, given that it fails the 23 W HR1 condition? The
   alternative is resistor mode with a Teensy-switched RCS (B18).
4. **Q4.** Should Q_H use two series forward-blocking FETs to remove the firmware layer from the Q2-short case?
5. **Q5.** Variant HS-3 (a second switch from pack positive to `VCHG`, mutually exclusive with Q_H) would give a
   charger-side inhibit that satisfies ruling 3 literally. It reintroduces finding X7 (battery connect and disconnect
   on a powered module, undefined in the datasheet). This document does not recommend it before B1-B3 are done.
6. **Q6.** Should Q_B be made series-redundant (two FETs, driven from the T_LG and T_OV chains) so that a sense
   bypass needs two faults?
7. **Q7.** Should the orphaned BQ29200 OUT be wired to pull the D-BC-FC and D-BC-RG ENs low, as a hardware per-cell
   OVP cut? OUT polarity and drive are TODO(verify: SLUSA52C); not adopted in revision 2.

### 9.2 Bench gates

Table 20 lists the bench gates in the order in which they should run. Gates B0-B3 decide whether IC4 is viable at all.

Table 20. Bench gates (revision 2).

| Gate | Measurement | Pass condition |
|---|---|---|
| B0 | VCHG-IN back-feed: pack on VBat+ (after R1 and R4), charger input open, R_BL fitted | VCHG-IN below 2 V (a body-diode path to Vin+ would hold it near 7.7 V, open Q_H permanently and end the concept) |
| B2 | R_s, Ag105 pins 14/15 to 16/17, module unpowered (after R1) | Value recorded; offset at 1.5 A within the BQ29200 margin and the OV_BATT charge-mode margin |
| B3 | Ag105 regulation with the restored sense: charge the pack at code 6 (1 A), then code 4, from a current-limited bench supply on `VCHG-IN`, pack on the battery port, **F3 logic lead and the full Teensy and 5V load connected**, meter in the pack lead and in the logic lead | Pack current = set value within the datasheet tolerance; reg 0x06 agrees; over-current trip location (sense or converter output) established; termination observed with the logic load present |
| B15 | Ag105 input UVLO minimum and its start-up time from input arrival | UVLO minimum above 7.6 V (T_LG margin); start-up time recorded |
| B1 | VLoad+ voltage in every module state, including input absent; I2C ACK with the module pack-fed and the input absent | Recorded (diagnostic only); `pollAg105()` assumptions re-derived |
| B8 | Continuity after R1-R11 and the harness (section 7.1, R9) | All isolations as listed |
| B16 | J-BT pin 2 lead offset (PCB GND minus local GND) at 16 A | Below 0.4 V (T_LG margin 0.245 V at the node) |
| B17 | Q1 body-diode V_SD at 0.3 mA, 25 C and hot | Below 1.0 V, so that the 1.5 V VBT-decay threshold discriminates a Q2 short |
| B6 | Barrier timing: step `VCHG-IN` from 0 to 16 V with PACK_RELEASE LOW; repeat with T_OV disconnected | Q_H off before CHG_PRESENT rises; Q_A enabled at least 50 us after Q2 V_GS falls below V_GS(th) min; with T_OV disconnected, Q_H off via the logic permit before Q_A is enabled |
| B5 | Q_H inrush with BT_REG LOW, VBT and VOUT-BT on the scope; SLPS632 Fig. 10 read-out | Peak <= 12 mA/uF of measured capacitance; the point lies inside the SOA |
| B7 | Q_H hard turn-off under a 5 A then 16 A BT boost load, via PERMIT removal (AND #2 active); repeat without AND #2 for the record | TPS61288 VIN never below -0.3 V; P_POS spike within the TVS1 rating; **must pass at 16 A before the module is fitted** |
| B9 | Teensy start-up at a 7.4 V pack (Q_B body-diode interval) and through Q_H toggles | No reset |
| B4 | `VCHG-IN` decay after charge exit | Below 5.0 V within 40 ms |
| B10 | OQ-7: which RT1987 EN nets carry the 10 kOhm pull-down | All charger-path ENs pulled down (a reset is then a hardware charge exit) |
| B11 | TPS61288 restart after Q_H close and BT_REG HIGH | Soft-start observed, no input current spike above the inrush budget |
| B18 | Resistor mode: does the Ag105 re-read RCS while running? | Recorded; decides Q3 |
| B12 | Purge statistics T-E-01 | Prediction error within the 150 ms lead; precondition of any charging event |
| B13 | S0-R3 / T-E-03 (VESC braking with V-MOT held) and the Ag105 warm response | Only if Q1 admits mode R-b |
| B14 | RTWDOG forced-hang test T-W-01 | MCU reset within the target, all ENs low; precondition of any charging event |

### 9.3 Unproven items carried by this design

The following statements in this dossier are not proven and must not be treated as facts until their gate passes:

- The Ag105 regulates the pack current correctly once VBat- carries the pack return (B3). This is the premise of the
  whole concept.
- The pack-fed VBat+ does not back-feed `VCHG-IN` (B0).
- The Ag105 UVLO minimum lies above the 7.4 V upper bound of the T_LG threshold (B15).
- The LM74800 OV pin works as a foreign-node comparator in this application (B6).
- The boost-first interlock keeps the TPS61288 VIN above -0.3 V on a hard turn-off at 16 A (B7).
- A shorted Q2 holds VBT within 1.5 V of the pack at the 0.3 mA bleed (B17).
- The source-power bound on a sense bypass (Table 17) assumes that the Ag105 CV loop is voltage-sensed and unaffected
  by the bypass.
- The 88 % efficiency used in the FC budget is specified only at 12 V input, 3S (DS p.20 note 2).
- The TLV7012 input range, dual-channel characteristics and the LM74800 EN-to-gate delay were taken from the
  reviewers' citations and not re-fetched.
- The harness inductance, the VBT negative excursion and the MLCC derating are estimates (B5, B7).

## 10. Review round 1 adjudication

### 10.1 Method

Three adversarial reviewers (fault, electrical, system) examined revision 1. Each finding was checked against the
primaries available in the repository: the BRD and SCH XML, the BOM, the IO CSV, `teensy_controller.ino`, the
facts files of this folder and the datasheets cited in them. Vendor datasheets that are not in the repository
(SLVSDM5F, SNOSD95C section 7.6, SLPS632 body-diode curves) were not re-fetched in this round; where a finding rests
on such a figure, the figure is labelled as the reviewer's citation. Table 21 records the verdict for each finding.
F, E and S denote the fault, electrical and system lenses; M is a major finding and m a minor one.

### 10.2 Adjudication table

Table 21. Review round 1 adjudication.

| ID | Finding | Evidence checked | Verdict | Design change |
|---|---|---|---|---|
| F-M1, E-M1, S-m5 | Both barriers and the steering share one tap node; an open tap reads "no charger" and defeats all of them; the pin-38 check at entry cannot see it | Revision-1 Figure 2: N_CHG feeds the OV pin and both comparator inputs through one 39.2 kOhm resistor and one wire over a 10 kOhm pull-down | ACCEPTED | Two taps (T_OV at C-D8, T_LG at C-D10), each with both resistors at its pad and its own wire; W_OV open fails toward "present" (1 MOhm to VS); tap agreement checked in every event (pin 38, CHG_PRESENT_RB, OV_TAP_V); Table 17 and HR3 restated (sections 2.3, 3.2, 5, 6) |
| F-M2, E-M3 (Q_B open) | Q_B open or gate-drive loss is undetected: PACK_V and BT_V are both GND-referenced, so their difference holds only the Q_H drop | Section 2.7 places R_PV2 at J2 (Teensy GND); facts_board 3.4 places the R2-BT ground pad on the PCB GND pour; both readings move with PCB GND | ACCEPTED | Q_B gate sensed into AND #1 input C (gate loss opens Q_H); QB_DIODE comparator across Q_B alone (-0.23 V threshold) to pin 21; PACK_V - BT_V criterion removed (section 2.2) |
| F-M3, E-M4, S-M5 | The Q2-short check (0.5 V drop) does not discriminate: at 0.3 mA a body diode drops about 0.4-0.6 V; divider errors add about +/-85 mV | VBT bleed 26.2 kOhm (facts_board 3.4); 0.5 V threshold in revision-1 step 4; the low-current V_SD is not in the dossier's SLPS632 figures | ACCEPTED | Threshold raised to 1.5 V; check moved off the critical path (boot, every Idle entry, concurrent with the Ag105 start-up); B17 measures V_SD at 0.3 mA |
| F-M3 (second part) | `FAULT_SWITCH_CONFLICT` is compiled out under `BENCH_TEST 1`, the build on the board | ino:7413-7419: the check is inside `#if !BENCH_TEST` | ACCEPTED | New all-build switch-conflict fault; all IC4 checks in every build (section 8.1) |
| F-M4 | Pin 35 output HIGH (pinMode error or Serial8 TX) back-drives the PERMIT node to about 1.65 V, above the EN maximum | Revision-1 Figure 2 (1 kOhm + 1 kOhm); facts_firmware line 174 (Serial8 = pins 34/35, unused) | ACCEPTED | Readback through 100 kOhm; EN pull-down 47 kOhm; worst case 0.99 V; pins 34/35 and Serial8 reserved (section 2.4, Table 9) |
| F-M5 | Several single faults recreate the sense bypass; the "keyed adapter" cannot key a screw terminal | BOM line 52: J-BL is TB005-762-03BE; facts_board line 45 | ACCEPTED, partly fixed | J-BL position 3 blocked on the board (R11); F2 reduced to 3 A; G-style checks in every build; residual recorded (section 5, Q6). Prevention by series-redundant Q_B is not adopted |
| F-M6 | The charge-entry I_batt check is vacuous: SNS-BT sits on the boost output and reads zero once BT_BUS is LOW | facts_board 3.3 item 2: SNS-BT between VOUT-BT and VBUS-BT | ACCEPTED | Entry preconditions include a bus-load budget and actual braking; step 2 checks V_bus and I_fc taking the load (section 3.2) |
| F-M7 | Q_H hard turn-off under load is routine (every reset, brown-out, open wire), and a Schottky cannot hold VBT above -0.3 V at 16 A | Revision-1 PACK_REQ 10 kOhm pull-down; SLVSFP3C 7.1 (VIN minimum -0.3 V) | ACCEPTED | Request inverted to PACK_RELEASE (default allow); boost-first interlock AND #2 with a 0.1 ms EN delay; D_CLAMP demoted to secondary; B7 at 16 A before fitting (sections 2.4, 4.4) |
| F-M8, S-M3 (hang, purge) | A hang during a charge leaves an FC-only bus with no latch; purges collapse it | facts_firmware line 183 (no MCU watchdog); facts_prior section 7 (purge 10.34 s) | ACCEPTED | RTWDOG (T-W-01) and purge prediction (T-E-01) are hard preconditions of every event; a reset is now a hardware charge exit (sections 3.2, 4.6) |
| E-M2 | Wrong order: the low-side swap (about 5.4 V) precedes the OV barrier (5.88-6.23 V), so a skipped entry forces the pack return through the module sense in reverse | Revision-1 section 2.3 thresholds | ACCEPTED | T_LG threshold raised to 6.8-7.4 V, above T_OV 5.55-5.96 V; Q_A enable delayed about 90 us (sections 2.2, 2.3) |
| E-M3 (common mode) | Comparator inputs exceed V_CC + 0.1 V above about 16.7 V on VCHG-IN, and exceed 7 V at the 36 V Ag105 maximum | Revision-1 ratio 4.92; TLV7012 limits as cited by the reviewer (SLVSDM5F 6.2, 6.4, 6.8) | ACCEPTED (limits not re-fetched) | T_LG ratio 11.0: 3.27 V at 36 V (section 2.3) |
| E-M5 | The logic load returns through the Ag105 in charge mode and adds to the converter output; the OC trip location is unknown | Topology: LOGIC_IN on P_POS, its return via GND to Vin-; DS p.18 (trip at set + 200 mA); facts_ag105 line 84 (sense element of the trip not stated) | ACCEPTED | Section 4.5 paragraph; B3 run with the logic lead and full load connected; code chosen with margin |
| E-M6 | OV_BATT on PACK_VOLTAGE collides with the CV end point | DS p.20 row 9 (100 mVp-p ripple); fw v30 `LIMIT_V_BATT_MAX` 8.5 V | ACCEPTED | Charge-mode OV_BATT on the sense-corrected value, margin `TODO(calibrate)` after B2 (section 4.7) |
| S-M1 | Mode R-b has no lead time: the regen trigger is the brake command | ino:15336 (`regenActive = (current < -0.1f)`) | ACCEPTED | R-b's timing claim withdrawn (section 4.3); HR1 FAILS |
| S-M2 | HR1 and HR2 conflict on one EPROM setting: code 4 gives 14.3 W against the 23 W HR1 condition; code 1 breaks the FC budget | facts_prior line 34 (HR1 pass condition >= 23 W); Table 15 | ACCEPTED | HR1 restated as FAILS at code 4; resistor-mode RCS switching recorded as the only candidate (B18, Q3) |
| S-M3 (objections) | The prior "weakest option" objections 1, 3 and 4 are not answered; regen events add purge exposure, because today's regen branch keeps BT_BUS HIGH | ino:15361; facts_prior section 7 | ACCEPTED | Table 15 adds the 47 % State-99 figure and the hold-up calculation; section 10.3 states that IC4 does not refute the prior rating |
| S-M4 | Charge entry can leave the bus source-less from a battery-only arm | facts_firmware line 139 (battery-only start at every Idle to Run; re-arm at <= 0.25 A); facts_firmware line 129 (2.57 V/ms) | ACCEPTED | Entry step 1: disarm the selector, close FC_BUS, wait 38 ms conducting and unblanked; HIL leg added (sections 3.2, 8.3) |
| S-M6 | The firmware scope is under-counted: BT_BUS and BT_REG HIGH write sites must refuse while the pack is released | facts_firmware line 42 (BT_BUS write sites) | ACCEPTED | Write sites listed; scope stated as a fw v28-scale round (section 8.1) |
| S-M7 | Mode R-b feeds the charger from the bus in Run, which ruling R3 forbids | CLAUDE.md 2026-11-04 addendum (R3) | ACCEPTED | R-b removed from the design unless ruled admissible (Table 10, Q1) |
| F-m1 | Reverse polarity bypasses the LM74800 on F2 and F3 | facts_ag105 line 153 (no reversal protection; DS p.18 recommends DST1550S and a fuse) | ACCEPTED | D_RV2, D_RV3 shunt diodes; one polarised housing (Table 7) |
| F-m2 | TLV7012 hysteresis about 6 mV at VCHG-IN; chatter on the bleed decay | Table 6 (1.2-14 mV) | ACCEPTED | 0.30 V external hysteresis (section 2.3) |
| F-m3 | No ground wire; an open J-BT pin 2 lead can overstress the logic | Section 2.7 of revision 1 | ACCEPTED | 4.7 Ohm fusible ground wire (section 2.7) |
| F-m4, E-m4 | JP1 and the VLoad diagnostic share a node | Revision-1 Figure 2 | ACCEPTED | VLoad removed from the permit; JP1 deleted; separate node (section 2.6) |
| F-m5 | Q_A sees V_GS +0.8-1.0 V while Q_B conducts on its body diode | SLPS632 V_GS(th) min 1.2 V (Table 4) | ACCEPTED as minor | Exposure now limited to the start-up interval and to Q_B faults (gate interlock, QB_DIODE); no change |
| F-m6 | Code 4 depends on an EPROM value; code 1 as found would overload the FC | Table 15; DS p.13 Table 7 | ACCEPTED | Reg 0x00 read back in every event (section 3.2) |
| F-m7 | R_BL open stalls the exit | Section 2.5 (tau 1.77 s without R_BL) | ACCEPTED | 100 ms exit timeout and fault |
| F-m8 | BQ29200 OUT could cut the charger ENs | facts_board (OUT orphaned) | ACCEPTED as an option | Q7; OUT polarity TODO(verify: SLUSA52C) |
| F-m9 | Q2 linear-mode SOA if Q_H re-closes with BT_REG HIGH | LM74800 has no current limit (SNOSD95C) | ACCEPTED | AND #2 holds the boost off until PERMIT is high and on reset; SOA read-out stays in B5 |
| E-m1 | EN-to-gate turn-on delay missing from the exit budget | SNOSD95C 7.6 as cited by the reviewer | ACCEPTED | Added to Table 13 |
| E-m2 | Table 6 cites single-channel tables for the dual part | SLVSDM5F section structure as cited | ACCEPTED | Citation note added (section 2.3) |
| E-m3 | VCHG-IN back-feed from the pack-fed VBat+ is unverified | DS p.20 row 7 (120-420 uA standby) does not rule out a diode path | ACCEPTED | Bench gate B0, first in order |
| E-m5 | HR2 headroom only at standstill; R-b conflicts with R3 | Table 15 | ACCEPTED | HR2 restated "standstill only"; R-b removed |
| E-m6 | Q_B thermal claim rests on reference copper | SLPS632 p.1 note 1 | ACCEPTED | Remains BENCH (section 4.1); no change |
| E-m7 | Thresholds must be re-derived with the 0.4 V ground offset | Section 2.7 | ACCEPTED | Ground-offset paragraph in section 2.3; B16 |
| E-m8 | CSD18510Q5B and UCC27524A figures not re-fetched by the reviewer; TB005 and Table 4 codes confirmed | - | NOTED | No change required |
| S-m1 | Both barriers act through one actuator (HGATE and Q2) | Topology | ACCEPTED | Stated in section 0 point 3 and Table 17; self-tests at boot and Idle entry |
| S-m2 | Logic current crosses the sense in the discharge direction in the idle states | Topology | ACCEPTED | Section 4.5 paragraph; B3 |
| S-m3 | The FC load step at entry and re-acceleration within the pack-return latency | facts_firmware line 139; campaign G F7 | ACCEPTED | Re-acceleration held off until the exit completes (sections 3.2, 4.6) |
| S-m4 | In R-b the charger bills FC hydrogen during every deceleration | facts_prior section 6 (about 6 % of a -12 A command delivered) | ACCEPTED | Moot while R-b is excluded; recorded under Q1 |
| S-m6 | State-99 ordering against the autonomous barrier | Revision-1 Table 10 | ACCEPTED | PACK_RELEASE HIGH at phase 0 |
| S-m7 | A pack-fed Ag105 may ACK I2C at boot | DS p.20 row 7 | ACCEPTED | B1 extended; `pollAg105()` assumptions re-derived |
| S-m8 | Balance-adapter dependence | BOM line 52 | ACCEPTED | R11 |
| S-m9 | LM1084 start-up through the Q_B body diode | SNVS037H section 5.5 | ACCEPTED | Remains B9 |

No finding was refuted. Two findings were accepted with a partial fix only (F-M5 sense-bypass prevention; S-M2 HR1
power condition), and their residuals are recorded in section 5 and in Q3 and Q6.

### 10.3 Post-review status

Revision 2 closes the hardware defects that the reviewers found in the barrier design. The two barriers now sense
through separate taps, the threshold order is correct in both directions, the comparator stays inside its input
range up to the 36 V Ag105 maximum, the permit cannot be back-driven from the Teensy, a non-conducting Q_B is visible
in hardware and to firmware, and a Teensy reset no longer opens Q_H under load. With these fixes, the loop break of
HR3 holds against every single sensing fault; actuator faults (Q2 short, HGATE stuck) remain detected-latent with
firmware as the second layer.

However, the review also showed that IC4 does not meet the project requirements as a whole. HR1 fails: the entry
cannot beat the first VESC pulse, the code-4 ceiling of 14.3 W is below the 23 W condition, and the only mode that
could improve the timing (R-b) conflicts with ruling R3. HR2 holds only for FC windows at standstill, and only with
purge prediction and a verified RTWDOG, neither of which exists today. Every charging event runs on an FC-only bus
whose collapse latches State 99 until a power cycle. Sense-bypass faults are bounded and detected but not prevented,
and the module regulation with the restored sense (B3) is still the unproven premise.

IC4 is therefore the prior "switch the pack off the bus while charging" option with better plumbing. It does not
refute the earlier rating of that option as the weakest re-spin path; it removes the brown-out objection and makes
the loop break structural, but objections 1 (no bus source during charge), 3 (no pack buffering) and 4 (transitions
per regen event) stand. The honest post-review status is: **survives with fixes as a loop-free standstill
FC-charging arrangement; fails HR1; not suitable as the overall winner unless the operator rules regen harvesting
out of scope or admits a bus-fed charger in Run (Q1) together with the resistor-mode RCS option (Q3, B18).** Gates
B0, B2 and B3 decide whether even the standstill role is viable, and they should run before any other IC4 work.
