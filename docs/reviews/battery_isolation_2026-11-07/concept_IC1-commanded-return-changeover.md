# Concept IC1: Commanded Low-Side Return Changeover (Design Dossier)

Date: 2026-11-07. Board revision 20260622, fw v37 rev 2 (`AG105_VBATN_ISOLATED 0`, `FC_CHARGE_ALLOWED 0`).
Inputs: `facts_board.md`, `facts_ag105.md`, `facts_firmware.md`, `facts_prior.md` and `brainstorm.md` in this folder.
Status: design dossier, **revision 2 (after review round 1)**. Section 10 records the adjudication of the three
adversarial reviews (fault, electrical, system) and every change that the adjudication made to sections 0-9. Nothing in
this document has been ordered, built, desoldered or flashed.

## 0. Summary

This dossier develops concept IC1 into a buildable reference design. Pack positive stays permanently on J-BT pin 1
(VBT), so the LM1084 and the Teensy never lose the pack. Pack negative moves to a new off-board node **PACK-**, and an
NMOS changeover on an off-board switch board transfers that node between PCB GND (the **bonded mode**) and the Ag105
VBat- pins (the **charge mode**). In the charge mode the pack return passes only through the Ag105 internal current
sense, which restores the module's charge-current regulation and its over-current trip (Ag105 DS V1.1 Fig. 1 p.3,
Table 2 p.4).

The design adds the following hardware layers to the changeover:

1. a charger power gate: the eFuse in series with the Ag105 input conducts only when **both** the permit latch (FF1,
   charge mode) and the arm latch (FF2) are set, so the Ag105 is unpowered in every bonded state;
2. a cross-lock that holds D-BT-SQ disabled while FF1 is clear or either S_GND gate is high, released only after a
   delay that follows the eFuse turn-off on every exit;
3. a pack shunt with a bidirectional amplifier and two latching comparators, which force the bonded mode on a
   discharge above 3 A and remove charger input on a pack charge current above 3.2 A;
4. a latching eFuse (TPS26631, MODE open) that limits the charger input to 1.84-2.16 A and latches off after at most
   233 ms of overload (SLVSE94G Table 8-1, section 6.6);
5. an external watchdog (TPS3431) that clears both latches on a hung loop.

The analysis in sections 4 to 6 supports the following findings. The changeover itself is electrically benign: every
transition moves PACK- by tens of millivolts, body diodes keep the return continuous through every dead time, and the
worst conduction loss is 0.35 W per device. With the charger unpowered in the bonded mode, no single fault in the
bonded mode can recreate the ML0227 loop (section 5). HR5 reaches PROVEN_CALC (bench-gated). HR3 and HR4 are proven
for the external backstops only (3.2 A pack charge, 2.16 A input with latch-off); the Ag105's own regulation is a
further layer only after bench gate B14 shows that the restored sense carries the return in every charge sub-state.

However, IC1 does not demonstrate either harvesting requirement. HR1 (regen) cannot meet its 23 W margin criterion
within the 2.5 A module rating at any legal current code with the VBT load I_L present; it meets the 18.9 W peak only
by calculation with an unverified 2S efficiency. HR1 also needs two motor-path changes and a MOT_PWR cycle per brake
event, which reverse the Death-5 doctrine and need operator rulings. HR2 (FC charging) remains blocked at system level
exactly as before IC1 (FC-only bus across purges), with a standstill-only budget and four EPROM writes per window of
unpublished endurance. Both requirements also depend on Ag105 start and restart timing that no primary gives
(gates B3-B5). Section 6 states the post-review status.

## 1. Topology

### 1.1 Nets and switches

Table 1 defines the new nets. Existing nets keep their schematic names (`references/Scale_Car_Board_20260624.sch`).

Table 1. New and modified nets.

| Net | Members | Notes |
|---|---|---|
| PACK- | Pack negative (through F_PK and R_SH), S_GND1/S_GND2 drains, S_CHG source, V_PACKN sense divider, S_CHG gate pull-down and clamps | Off-board node on the switch board |
| VBATN_X | Ag105 pins 14/15 module-side stubs (flying lead), S_CHG drain | Replaces the GND connection of pins 14/15 |
| VCHG-IN_M | Ag105 pin 10 module-side stub, eFuse OUT | VCHG-IN (board side, pad 10 barrel) becomes eFuse IN |
| EN_SQ_X | D-BT-SQ EN pad 5 side of a cut in net D-BT-SQ | Teensy pin 32 drives it through R_S32 4.7 kOhm |
| EN_BE_X | D-BT-EN EN pad 5 side of a cut in net D-BT-EN | Teensy pin 28 drives it through R_S28 4.7 kOhm |
| N1 | /CLR of FF1 (PERMIT), 10 kOhm pull-up to 3V3, wired-AND of open-drain sources | Section 2.4 |
| N2 | /CLR of FF2 (ARM), 10 kOhm pull-up to 3V3, wired-AND | Section 2.4 |
| SHDN_EF | eFuse SHDN: FF2.Q through 1 kOhm, 22 kOhm to GND, clamp Q_E (gate = FF1./Q) | Section 2.4, item 3 |
| VBT_T | Fused VBT tap on the switch board (F_T 0.5 A) | Gate drive and sense supply (section 2.2) |

### 1.2 Power diagram

Figure 1 shows the power path. The arrows give the conventional current direction in each mode.

```
                    J-BT pin 1 (VBT, unchanged)
  PACK+ ───────────────────────────────────────────────┬── LM1084 ─ 5V ─ Teensy
   │                                                    ├── TPS61288 (REG-BT) ─ SNS-BT ─ D-BT-EN ─ VBUS
 [2S]                                                   ├── R1-BT/R2-BT (V_batt, pin 25)
   │                                                    └── D-BT-SQ VOUT ◄── VIN = VCHG ◄── Ag105 VBat+ (18/19)
  PACK- ─ F_PK 20 A ─ R_SH 0.5 mOhm ─┐                                     ▲             │
  (harness, off-board, keyed plug)   │ PACK- (switch board)                │ R_KA 1 kOhm, 1206 0.25 W (keep-alive,
                                     │                                     └─────────────┘  operator ruling 9)
              ┌──────────────────────┴───────────────────────┐
              │ D                     │ D                    │ S
           S_GND1                  S_GND2                 S_CHG (all CSD18510Q5B)
              │ S                     │ S                    │ D   body diode: PACK- -> VBATN_X
              └──────────┬────────────┘                      │
                 J-BT pin 2 (GND)                      VBATN_X ── flying lead ── Ag105 pins 14/15 (cut from GND)
                         │                                                       │
                  PCB GND pour ═══════════ Ag105 Vin- (pin 4) ◄── internal sense ┘
                                           (Vin- stays on GND: I2C, STAT, MPPTD, THERM unchanged)

  VCHG-IN (D-BC-FC VOUT, D-BC-RG VOUT, R1-CHG) ── eFuse TPS26631 (SHDN = FF1.Q AND FF2.Q; UVLO ≈ 10.4 V) ── pin 10 stub
  J-BL pin 3: emptied; the balance-lead negative wire is removed from the harness and insulated (X1).
```

Figure 1. IC1 power topology. Bonded mode: S_GND1 and S_GND2 ON, S_CHG OFF, eFuse OFF. Charge mode: S_GND1 and S_GND2
OFF, S_CHG ON, eFuse ON when armed.

The return currents in each mode are as follows.

- **Bonded mode.** Pack discharge returns GND -> S_GND1 || S_GND2 -> PACK- -> R_SH -> pack negative. The Ag105 sense
  carries no pack current. The Ag105 is unpowered (eFuse off, section 2.4) and D-BT-SQ is held disabled by the
  cross-lock, so no charger output exists and none can reach VBT.
- **Charge mode.** Pack charge current returns pack negative -> R_SH -> PACK- -> S_CHG -> VBATN_X -> sense -> Vin- ->
  GND. A net discharge (VBT load larger than the charger output) flows the reverse way through the same sense, which is
  the datasheet's own load-return direction (Load- -> Vin- node -> sense -> Bat-, Ag105 DS Fig. 1 p.3).
- **Dead time and both-OFF.** Discharge flows through the S_GND body diodes (anode GND, cathode PACK-); charge flows
  through the S_CHG body diode (anode PACK-, cathode VBATN_X) and still crosses the sense. The return is never open.

S_GND is two devices in parallel, each with its own gate pull-up, zener and pull-down transistor (section 2.2), so that
no single gate-drive fault opens the bonded return (review finding fault-M2).

### 1.3 Why the pack current is the only current the sense sees

In the charge mode, Kirchhoff's current law at the Ag105 terminals gives the following relations, with I_o the
converter output current into VCHG, I_p the pack charge current and I_L the total VBT load (BT boost input, LM1084
input, V_batt divider):

- I_o = I_p + I_L (at node VBT, through D-BT-SQ);
- sense current = I_p (the only current in PACK- is the pack current, because I_L returns to GND directly).

The Ag105 constant-current loop therefore regulates I_p, and it supplies I_L **in addition, outside regulation**
(facts_ag105 section 1.4, UNCONFIRMED from the block diagram only). This is the central limitation of every
return-only concept (brainstorm X3): the restored sense bounds the pack current, not the converter output. Section 4.4
sizes I_L and selects the current code so that I_set + I_L stays inside the 2.5 A module rating.

A further limitation is that Ag105 DS Fig. 1 p.3 draws an internal switch in parallel with the sense, whose function is
not described (facts_ag105 section 1.2). If that switch conducts in any charge sub-state, the module's own current
regulation is as blind as in ML0227 and only the external backstops (U_C2, eFuse) bound the current. Bench gate B14
(section 9) decides this.

## 2. Parts, gate drive and fail-safe defaults

### 2.1 Power switches

Table 2 lists the power MOSFETs. One part number serves all three positions so that a spare covers any of them.

Table 2. S_GND1, S_GND2 and S_CHG: TI CSD18510Q5B (SLPS632, March 2017).

| Rating | Value | Source |
|---|---|---|
| V_DS | 40 V | SLPS632 Absolute Maximum Ratings, p.1 |
| V_GS | +/-20 V | SLPS632 Absolute Maximum Ratings, p.1 |
| I_D continuous (package limited / silicon) | see p.1; 300 A silicon limited | SLPS632 p.1 |
| I_DM pulsed | 400 A | SLPS632 p.1 |
| R_DS(on) at V_GS 4.5 V, 32 A | 1.2 typ / 1.6 max mOhm | SLPS632 section 5.1 |
| R_DS(on) at V_GS 10 V, 32 A | 0.79 typ / 0.96 max mOhm | SLPS632 section 5.1 |
| V_GS(th) | 1.2 / 1.7 / 2.3 V | SLPS632 section 5.1 |
| Q_g at 4.5 V / 10 V | 58 (75 max) / 118 (153 max) nC | SLPS632 section 5.1 |
| C_iss | 8770 typ / 11400 max pF | SLPS632 section 5.1 |
| Body diode V_SD at 32 A | 0.8 typ / 1.0 max V | SLPS632 section 5.1 |
| R_thJC / R_thJA | 0.8 / 50 C/W (R_thJA on 1 in2 copper, note 2) | SLPS632 section 5.2 |
| R_DS(on) temperature factor | about 1.5x at 125 C, read from Figure 8 | SLPS632 Figure 8 (graph reading, UNCONFIRMED) |

The gate drive comes from VBT (7.4-8.5 V operating, CLAUDE.md section 6), so V_GS lies between the two specified
points. The design uses the 4.5 V maximum (1.6 mOhm) as the bound, which is conservative only while the loaded gate
voltage stays at or above 4.5 V; section 2.2 item 6 sets that as an acceptance condition.

### 2.2 Gate drive and changeover sequencer

The sequencer runs from VBT_T (power gates, through fuse F_T 0.5 A at the tap, TODO(verify: fuse data sheet)) and 3V3
(logic). Figure 2 shows it.

```
 For k = 1, 2 (two independent channels):
 VBT_T ─ R_GUk 10k ─┬─ S_GNDk gate ── Zk BZT52C15 to GND
                    ├─ Q_Ak (BSS138) drain, source GND
                    │   Q_Ak gate ─ 4.7k ─ FF1.Q ; 100k to GND ; BAT54 (cathode at U_C1 OUT) [U_C1 pulls low]
                    ├─ BAT54 ─ 47k ─┐
                    │               ├─ X node (100 nF to GND, 47k to GND) ─ Q_X2 gate (D-BT-SQ cross-lock)
 FF1./Q ─ BAT54 ─ 10k ──────────────┘
                    ├─ BAT54 ─ 47k ─ D node (100k to PACK-) ─ Q_D gate (S_CHG clamp)
                    └─ R_Wk ─ pin 23 summing node (15k to GND); R_W1 = 200k, R_W2 = 100k  (SGND_GATE)

 VBT_T ─ R 100k ─┬─ Q_B (BSS84) gate        Q_B source = VBT_T, drain ─ 1k ─┬─ S_CHG gate ── Z3 BZT52C15 to PACK-
                 └─ R 33k ─ Q_C (BSS138) drain                              ├─ 47k to PACK-
                    Q_C gate ─ RC 10k/10nF ─ FF1.Q ; 100k to GND            └─ Q_D (BSS138) drain, source PACK-

 Teensy pin 32 ─ R_S32 4.7k ─ EN_SQ_X (D-BT-SQ EN) ─ Q_X2 drain (BSS138), source GND
 Teensy pin 28 ─ R_S28 4.7k ─ EN_BE_X (D-BT-EN EN) ─┬─ Q_X1 drain (gate = pin-31 net FC_CHARGE)
                                                     └─ Q_X3a ─ Q_X3b ─ Q_X3c in series to GND
                                                        (gates = pin-29 net, pin-30 net, FF1.Q)
```

Figure 2. Sequencer and cross-locks (resistor values are design values; BSS84 ratings TODO(verify: onsemi BSS84
data sheet)).

The sequencer behaves as follows.

1. **Bonded is the passive state.** Each R_GUk pulls its S_GND gate to VBT_T whenever its Q_Ak is off. Q_Ak turns on
   only when FF1.Q is high, and FF1 cannot set without a Teensy edge (section 2.4). With the Teensy unpowered, in reset
   or with 3V3 absent, the 100 kOhm pull-downs hold both Q_A off and both S_GND devices conduct. A drain-source short of
   one Q_Ak, a short of one Zk, an open R_GUk or an open gate lead turns off one S_GND only; the other carries the
   bonded return at 2 x the single-device loss of the pair (section 4.1).
2. **U_C1 direct path.** The U_C1 open-drain output pulls both Q_A gates low through BAT54 diodes, independent of FF1,
   so a discharge above 3.0 A bonds the pack even with FF1 stuck set (former F7 residual). The 4.7 kOhm series resistor
   from FF1.Q limits the contention current to 0.7 mA; the TLV3011 output sink at that current is TODO(verify: SBOS300C
   section 6.5).
3. **Break before make, bonded to charge.** FF1.Q rising turns both Q_A on; each discharges about 95 nC of gate charge
   (between the 4.5 V and 10 V figures of Table 2) in microseconds. Q_C turns on after the RC delay (tau = 100 us), Q_B
   then drives the S_CHG gate to VBT_T through 1 kOhm. Q_D additionally clamps the S_CHG gate to its source while either
   S_GND gate is above the Q_D threshold (BSS138 V_GS(th) 0.8-1.5 V, onsemi BSS138/D p.2), so S_CHG cannot turn on
   while either S_GND gate is high even if the RC delay is wrong.
4. **Break before make, charge to bonded.** FF1.Q falling turns both Q_A off. Each S_GND gate rises with
   tau = 10 kOhm x 8.8-11.4 nF = 88-114 us. Q_D clamps the S_CHG gate as soon as either S_GND gate passes 0.8-1.5 V,
   which is below the S_GND threshold of 1.2-2.3 V, so S_CHG is pulled off before S_GND conducts in most of the
   tolerance space. The tolerance corner (Q_D at 1.5 V, S_GND at 1.2 V) gives a brief overlap; with the charger
   unpowered by then (section 2.4 item 3) the overlap has no consequence (section 5, row F10).
5. **S_CHG gate referenced to PACK-.** The S_CHG pull-down, Z3 and Q_D source return to PACK- (the S_CHG source), not
   to GND. While the S_GND body diodes conduct, PACK- sits 0.7-1.0 V below GND; a GND-referenced clamp would then give
   S_CHG a V_GS of +0.7 to +1.0 V against a minimum threshold of 1.2 V that falls with temperature (review finding
   fault-m7, electrical minor). The PACK- reference holds V_GS at 0 V.
6. **Gate loading.** The SGND_GATE readback (R_W 100-200 kOhm) and the cross-lock networks (BAT54 + 47 kOhm) load each
   gate in parallel with R_GU 10 kOhm. With 47 kOhm + 47 kOhm || 100-200 kOhm the loaded gate is about 0.75-0.8 x VBT,
   which is 5.6-5.9 V at the 7.4 V pack floor (calculation from the design values, UNCONFIRMED until the detail
   design). The acceptance condition is a loaded gate of at least 4.5 V at VBT = 7.4 V (bench gate C-2), where
   SLPS632 specifies 1.6 mOhm maximum.
7. **Zener clamps** hold the gates at 15 V against VBT transients (BZT52C15, `references/Datasheets/BZT52C_Diodes.pdf`;
   tolerance TODO(verify: BZT52C_Diodes.pdf table)). V_GS max is 20 V (Table 2).

Static consumption in the charge mode is 2 x VBT / R_GU = 1.7 mA at 8.5 V plus 64 uA in the Q_B divider. The bonded mode
draws the gate-network load current (about 0.2 mA per gate at 8.5 V) plus leakage.

### 2.3 Cross-locks on the existing RT1987 enables

Two existing EN nets receive a series resistor and clamp FETs. The series resistor is necessary so that a clamp never
fights the Teensy GPIO directly.

1. **D-BT-SQ (net D-BT-SQ, Teensy pin 32).** Q_X2 pulls EN_SQ_X below V_EN_F whenever the X node is above the BSS138
   threshold. The X node is a diode-OR of FF1./Q (through 10 kOhm) and both S_GND gates (through 47 kOhm each), with
   100 nF and 47 kOhm to GND. D-BT-SQ is therefore released only when FF1 is set **and** both S_GND gates are low.
   - The RT1987 disables below V_EN_F = 0.6 V minimum and enables above V_EN_R = 1.4 V maximum (RT1987 DS-00 section 13,
     section 17.1). With the Teensy at 3.3 V through 4.7 kOhm and the 10 kOhm bodge pull-down (if fitted, OQ-7), EN
     rises to 3.3 x 10 / 14.7 = 2.24 V when Q_X2 is off, which exceeds 1.4 V. Q_X2 must hold EN below 0.6 V against
     3.3 V / 4.7 kOhm, which needs R_DS(on) below about 1.0 kOhm; BSS138 is specified at 6 Ohm maximum at V_GS 4.5 V
     (BSS138/D p.2). From FF1./Q the X node reaches (3.3 - 0.3) x 47 / 57 = 2.5 V, so Q_X2 at V_GS 2.5 V is covered by
     bench gate B10.
   - Timing: the X node charges with tau of about 1 ms (10 kOhm, 100 nF) from FF1./Q, so on every exit D-BT-SQ disables
     0.3-0.7 ms after FF1 clears, while the eFuse is already off within 1.5 us (section 2.4 item 3). On entry the X node
     discharges through 47 kOhm (tau 4.7 ms), so D-BT-SQ is released about 5 ms after FF1 sets and turns on t_D_ON = 8 ms
     typical later (RT1987 DS-00 section 13; no maximum given).
   - The RT1987 "completely isolates VIN and VOUT when disabled" with back-to-back MOSFETs (RT1987 DS-00 section 17,
     overview), so a disabled D-BT-SQ blocks both directions.
   - Firmware keeps pin 32 HIGH at all times after boot, as the IO CSV note and CLAUDE.md section 2 require. The
     hardware cross-lock alone holds D-BT-SQ off in the bonded mode; the pin-32 doctrine is unchanged.
2. **D-BT-EN (net D-BT-EN, Teensy pin 28).** Q_X1 clamps EN_BE_X while the FC_CHARGE_ENABLE net (pin 31) is high,
   which makes the existing firmware rule "BT_BUS LOW before FC_CHARGE" a hardware rule. The series string
   Q_X3a/b/c clamps EN_BE_X while MOT_PWR (pin 29) AND REGEN (pin 30) AND charge mode (FF1.Q) are all high, which
   closes the regen loop L-R (bus -> D-MT-EN -> V-MOT -> D-BC-RG -> charger -> VBT -> BT boost -> bus) in the charge
   mode. The Q_X1 and Q_X3 gates are driven by 3.3 V logic nets; BSS138 R_DS(on) at V_GS 3.3 V is not tabulated
   (BSS138/D p.2 gives 2.75 V curves only) and is TODO(verify: BSS138/D Figure; bench B10), but the required value is
   below 1.0 kOhm.
3. **Readback of the clamped EN nodes.** The clamps sit behind series resistors, so `digitalRead(BT_BUS_ENABLE)` and
   `switch_state` report the commanded level, not the hardware level. Firmware must derive the effective BT_BUS state
   as `pin28 AND NOT pin31 AND NOT (pin29 AND pin30 AND CHG_PERMIT_RB)` and must refuse any transition that would leave
   the bus source-less (FC_BUS LOW while the derived BT_BUS is OFF). C-2 verifies the derivation against the EN pad
   voltage once per rework. No spare pin remains for a direct EN-node readback (section 3.1).

The cut points are on top-layer 0.254 mm traces next to each EN pad (BRD signal D-BT-SQ: pad 5 trace end
(31.193, 50.788), cut on the segment (32.258, 51.054)-(32.258, 52.324); BRD signal D-BT-EN: pad 5 trace end
(65.229, 23.61), cut on the segment (66.294, 24.384)-(66.294, 29.718)). The position of the 10 kOhm bodge pull-down on
each net relative to the cut is OQ-7 and must be checked before the cut; the pull-down must stay on the EN-pad side.

### 2.4 Latches, comparators, eFuse and watchdog

Table 3 lists the logic and protection parts. All logic runs from 3V3 (Teensy regulator, 250 mA external budget,
facts_board section 6.1).

Table 3. Logic and protection parts.

| Ref | Part | Function | Key primary figures |
|---|---|---|---|
| FF1, FF2 | SN74LVC74A dual D flip-flop | FF1 = PERMIT (charge mode), FF2 = ARM (charger input) | TODO(verify: TI SN74LVC74A data sheet; Ioff behaviour) |
| U_SH | INA240A3 (100 V/V) | Pack-current amplifier on R_SH | SBOS662C: V_CM -4 to 80 V, V_S 2.7-5.5 V, V_OS +/-25 uV max, gain error 0.20 % max, swing V_S - 0.2 V and GND + 10 mV, BW 400 kHz (sections 6.3, 6.5); not re-verified in review round 1 |
| U_C1, U_C2 | TLV3011 (open-drain) | C1: discharge > 3.0 A; C2: charge > 3.2 A | SBOS300C: 1.8-5.5 V supply, open-drain output, t_PD 6-13.5 us typ (section 6.7); not re-verified |
| U_WD | TPS3431 | External watchdog, WDO open-drain active low | SNVSB66A: VDD 1.8-6.5 V; C_CWD 0.1 nF gives t_WD 62.74 ms typ; 0.905-1.095 band (section 8.3); EN pin, start-up delay and WDO behaviour in the start-up window TODO(verify: SNVSB66A) |
| U_EF | TPS26631PWPR, MODE open (latch-off) | Series in VCHG-IN, SHDN = SHDN_EF | SLVSE94G (rev. June 2024): see Table 3a |
| Q_E | BSS138 | Clamps SHDN_EF while FF1 is clear | BSS138/D p.2 |
| R_SH | 0.5 mOhm, 2512 metal strip | Pack shunt | TODO(verify: vendor data sheet, for example Vishay WSL2512) |
| F_PK | 20 A slow-blow automotive blade fuse | Pack-lead fuse | Ag105 DS Figs. 4, 9, 10 fit a 10 A slow-blow fuse; 20 A is chosen above the 17.1 A boost limit; resistance TODO(verify: fuse data sheet) |
| F_T | 0.5 A fuse | VBT_T tap | TODO(verify: fuse data sheet) |

Table 3a gives the TPS26631 figures that the design relies on, read from SLVSE94G (September 2018, revised June 2024).

Table 3a. TPS26631 figures (SLVSE94G).

| Item | Value | Source |
|---|---|---|
| Factory UVLO (UVLO pin to GND) | rising 15.1 / 15.46 / 15.9 V, falling 14.0 / 14.47 / 15.1 V | Section 6.5, V(INSYS_UVLO) |
| UVLO pin threshold, rising / falling | 1.176 / 1.2 / 1.224 V; 1.09 / 1.122 / 1.15 V | Section 6.5, V(UVLOR), V(UVLOF) |
| SHDN open-circuit voltage | 2.48 / 2.7 / 3.3 V at I(SHDN) = 0.1 uA | Section 6.5, V(SHDN) |
| SHDN thresholds | falling (low-IQ shutdown) 0.8 V min; rising 2 V max | Section 6.5, V(SHUTF), V(SHUTR) |
| SHDN current at 0 V | -10 uA | Section 6.5, I(SHDN) |
| SHDN to FET off | 0.8 / 1 / 1.5 us | Section 6.6, tSD(dly) |
| I_OL at R_ILIM 9 kOhm | 1.84 / 2.00 / 2.16 A | Section 6.5 |
| Fast trip (TPS26631) | 3 x I_OL | Section 6.5, I(FASTRIP) |
| 2 x I_OL pulse support | 20 / 25.5 / 31 ms, active only after PGOOD is high | Section 6.6, tCB(dly); section 8.3.7.1.2 |
| Duration in current limit | 129 / 162 / 202 ms; the EC row names TPS26632/33/35/36/37, section 8.3.7.1.1 gives 162 ms typical | Section 6.6, tCL_PLIM(dly) |
| MODE open response | TPS26631: 2 x I_OL for tCB(dly), then 1 x I_OL for at most tCL_PLIM(dly), then latches OFF; reset by SHDN low-to-high, UVLO low-to-high or IN_SYS power cycle | Table 8-1, section 8.4 |
| Factory OVP (OVP pin to GND) | 34.3 V typical, 440 mV hysteresis | Section 8.3.4 |

The latch wiring is as follows.

1. **FF1 (PERMIT).** D = 3V3, CLK = Teensy pin 33 (`CHG_MODE_REQ`) through 1 kOhm / 1 nF, /PRE = 3V3, /CLR = N1. N1 is
   pulled up by 10 kOhm and pulled low by any of: pin 33 low (BAT54 Schottky, cathode at pin 33), U_C1, U_C2, U_WD WDO,
   BQ29200 OUT (through Q_OV, mandatory, section 7.1 step 10) and FF2./Q. Pin 33 has a 10 kOhm pull-down. FF1.Q
   therefore sets only on a pin-33 rising edge while FF2 is set and no clear source is active, and it stays clear after
   any trip until the Teensy drives pin 33 low and high again. The RC on CLK delays the clock edge by about 1 us after
   /CLR releases, so the edge does not race the clear recovery (a lost race leaves FF1 clear, which is safe).
2. **FF2 (ARM).** Identical, with CLK = Teensy pin 34 (`CHG_ARM`) and /CLR = N2, pulled low by pin 34 low, U_C2, WDO
   and BQ29200 OUT (through a second Q_OV drain).
3. **eFuse enable = FF1 AND FF2.** SHDN_EF is driven from FF2.Q through 1 kOhm, has a 22 kOhm pull-down to GND, and is
   clamped to GND by Q_E while FF1./Q is high (FF1 clear). The levels are as follows.
   - FF1 and FF2 set: SHDN_EF = 3.3 x 22 / 23 = 3.16 V, above the 2 V rising threshold.
   - FF2 clear (output low), FF2 output high-Z (3V3 absent, open lead) or FF1 clear: SHDN_EF is at most
     10 uA x 22 kOhm = 0.22 V through the pull-down, or clamped by Q_E. Both are below the 0.8 V falling threshold.
   - Q_E must pull SHDN_EF below 0.8 V against 3.3 V / 1 kOhm, which needs R_DS(on) below about 300 Ohm at V_GS 3.3 V
     (bench gate B10). Q_E has a 100 kOhm gate pull-down, so with the logic unpowered it is off and the 22 kOhm
     pull-down alone holds the eFuse off.
   - The eFuse therefore turns off within tSD(dly) 1.5 us of any FF1 clear, which is before the S_GND gates rise
     (88-114 us) and before the D-BT-SQ cross-lock acts (0.3-0.7 ms). Every hardware exit and trip removes charger input
     first (review findings electrical-M2, system-M7).
4. **eFuse configuration.** MODE open (latch-off). UVLO set by a divider from IN_SYS: 100 kOhm / 13 kOhm gives
   1.2 x 113 / 13 = 10.4 V rising and 1.122 x 113 / 13 = 9.75 V falling (Table 3a), replacing the factory 15.1-15.9 V
   threshold that sits on the 16.0 V bus. OVP pin to GND selects the factory 34.3 V cutoff, above the 21.4 V regen
   clamp (CLAUDE.md 2026-11-04 addendum, corrected V_rgn reading) and above the Ag105 input range. PGTH to GND, so the
   2 x I_OL pulse support is never activated (section 8.3.7.1.2) and the overload bound is I_OL. R_ILIM 9 kOhm. The
   dVdT capacitor is a design-detail item against the Ag105 input capacitance (TODO(verify: Silvertel)). FLT is read
   on pin 10 (`EF_FLT`, 10 kOhm pull-up).
5. **Power-up.** Pins 33 and 34 are inputs with a keeper at reset (PJRC, facts_board section 7.3), the 10 kOhm
   pull-downs hold them low, so N1 and N2 are low and both flip-flops come up clear. The flip-flop power-up state is
   irrelevant while /CLR is held.
6. **U_SH.** R_SH sits between pack negative and PACK- in the harness. REF1 = 3V3 and REF2 = GND place zero current at
   V_S / 2 = 1.65 V (SBOS662C section 8.4, bidirectional split reference). The scale is 100 V/V x 0.5 mOhm = 50 mV/A.
   The swing limits give +29 A and -32.8 A of range. The offset term is 25 uV / 0.5 mOhm = 50 mA. The Teensy reads
   OUT on pin 16 (`I_PACK`) at 12 bits: 0.806 mV per count = 16 mA per count.
7. **U_C1 and U_C2 thresholds and filtering.** Each comparator compares U_SH OUT, filtered by 1.5 kOhm / 47 nF
   (tau = 70 us), with a divider from the same 3V3 that sets the INA240 reference, so the midscale and the threshold
   track the 3V3 tolerance together. U_C1 trips at OUT < 1.65 - 0.15 = 1.50 V (discharge 3.0 A); U_C2 trips at
   OUT > 1.65 + 0.16 = 1.81 V (charge 3.2 A). The filter rejects share-loop handoffs, BT_BUS closures and boost input
   ripple; its time constant must be confirmed against the C-2 and B-gate waveforms. With 0.1 % dividers the threshold
   error is dominated by the INA240 gain error (0.2 %) and offset (50 mA); a 20 mV hysteresis (0.4 A) is set with a
   feedback resistor.
8. **U_WD.** WDI = Teensy pin 35 (`WDT_KICK`), SET1 = 3V3, C_CWD = 0.1 nF for t_WD = 62.74 ms typ (56.8-68.7 ms with
   the 0.905-1.095 band). WDO is wired into N1 and N2. The watchdog does not reset the Teensy; it only clears both
   latches. Because the latches need a new edge to set, a hung Teensy that holds pins 33 and 34 high stays in the
   bonded, unpowered-charger state after the first timeout. The RTWDOG/WDOG1 MCU reset of ruling 5 remains required in
   addition (facts_prior section 10 item 7); pin 20 is kept free for a hardware WDOG1_B (section 3.1).

### 2.5 Fail-safe default summary

Table 4 lists every new control element and its state with the Teensy unpowered, in reset or hung.

Table 4. Fail-safe defaults.

| Element | Default mechanism | Resulting state |
|---|---|---|
| S_GND1, S_GND2 | R_GUk 10 kOhm to VBT_T; Q_Ak gate 100 kOhm to GND (independent per channel) | ON (bonded) |
| S_CHG | 47 kOhm to PACK-; Q_B off (100 kOhm to VBT_T); Q_D on while either S_GND gate is high | OFF |
| D-BT-SQ | Q_X2 on while FF1./Q or either S_GND gate is high; existing 10 kOhm bodge (OQ-7) | Disabled |
| D-BT-EN | Existing 10 kOhm bodge (OQ-7); Teensy pin 28 | Disabled at reset (unchanged) |
| eFuse U_EF | SHDN_EF 22 kOhm pull-down; Q_E clamp while FF1 is clear; FF2 clear | OFF, charger unpowered (also with 3V3 absent) |
| FF1, FF2 | /CLR held by pin-33/34 pull-downs and WDO | Clear |
| Hung loop | U_WD clears FF1 and FF2 within 56.8-68.7 ms; no new edge can set them | Bonded, charger unpowered |

## 3. Teensy pins and control sequences

### 3.1 Pin assignment

Table 5 assigns spare pins from facts_board section 7.2 (free on the J1/J2 headers, wired to nothing else). Pins 2, 7
and 8 are avoided. Pin 20 is reserved for a hardware WDOG1_B (charger evaluation, section 5.1 timer row). Every
assignment must first be entered in `references/Scale Car Teensy IO - IO.csv`, which is not edited by this study.
With this table every listed spare pin is in use.

Table 5. Proposed pin use.

| Pin | Proposed Code Name | Dir | Function |
|---|---|---|---|
| 33 | `CHG_MODE_REQ` | OUT, 10 kOhm pull-down | Rising edge sets FF1 (charge mode); LOW clears it |
| 34 | `CHG_ARM` | OUT, 10 kOhm pull-down | Rising edge sets FF2 (arm); LOW clears it |
| 35 | `WDT_KICK` | OUT | TPS3431 WDI |
| 16 (A2) | `I_PACK` | AIN | INA240A3 OUT, 50 mV/A about 1.65 V |
| 17 (A3) | `V_PACKN` | AIN | PACK- relative to GND through 100 kOhm / 100 kOhm from 3V3: V = (3.3 + V_PACKN) / 2 |
| 23 (A9) | `SGND_GATE` | AIN | Weighted sum of both S_GND gates (200 kOhm, 100 kOhm, 15 kOhm to GND) |
| 21 | `CHG_PERMIT_RB` | IN | FF1.Q readback |
| 22 | `CHG_ARM_RB` | IN | SHDN_EF readback (effective eFuse enable, FF1 AND FF2) |
| 10 | `EF_FLT` | IN | eFuse FLT (open-drain, 10 kOhm pull-up to 3V3) |
| 20 | (reserved) | - | Hardware WDOG1_B, ruling 5 |

The SGND_GATE summing node gives V = (G1 / 200k + G2 / 100k) / (1/200k + 1/100k + 1/15k). At VBT = 7.4 V with loaded
gates near 0.8 x VBT (5.9 V), both gates high read 1.08 V, S_GND2 only 0.72 V, S_GND1 only 0.36 V and both low 0 V. A
15 V zener-clamped transient on both gates reads 2.75 V, inside the 3.3 V pin range. The exact levels follow the detail
design and are checked in C-2.

V_PACKN spans -1.0 V (S_GND body diodes at full current) to about +0.3 V, which maps to 1.15-1.80 V at the pin, within
the ADC range. The reading includes the J-BT pin-2 contact (20 mOhm maximum, TB005-762 p.1) and the harness wire,
because the divider is referenced to PCB GND. The divider resolution is 1.6 mV per count.

### 3.2 Operating modes

Table 6 defines the switch states of each mode. "Firmware" columns are pin levels the firmware commands; "hardware"
columns are the result after the cross-locks.

Table 6. Mode table (H = HIGH, L = LOW, X = unchanged by the mode).

| Mode | FF1 (pin 33) | FF2 (pin 34) | S_GND | S_CHG | eFuse | D-BT-SQ | BT_BUS (28) | MOT_PWR (29) | REGEN (30) | FC_CHG (31) |
|---|---|---|---|---|---|---|---|---|---|---|
| Boot / reset / hang | clear | clear | ON | OFF | OFF | off | L | L | L | L |
| Idle, Run traction, Finish | clear | H allowed (Run) | ON | OFF | OFF (FF1 clear) | off (cross-lock) | X | H | L | L |
| Regen window | set | H | OFF | ON | ON | on | H allowed | **L** | H | L |
| FC-charge window (standstill only) | set | H | OFF | ON | ON | on | **L (hardware via Q_X1)** | X | L | H |
| State 99 | clear second | clear first | ON | OFF | OFF | off | L | L | per section 3.3 | per section 3.3 |

The bonded Run row keeps REGEN LOW and the eFuse is off, so the bus never feeds the Ag105 in the bonded mode. The bus
feeds the charger only inside a commanded FC window. In the regen window MOT_PWR is LOW, so V-MOT is fed only by the
VESC. This replaces the "always-powered" Run row of revision 1, whose bonded-mode exposure (D-BT-SQ as the only
barrier) was the subject of review findings fault-M1, fault-M3 and system-M8.

The cost of this change is that the Ag105 starts cold on every window. The Ag105 starts from its stored EPROM codes;
section 3.3 sets those stored codes to the regen values so that a regen window needs no I2C write. The start time is
the decisive unknown (B3-B5).

### 3.3 Sequences

The following sequences are firmware proposals. Every timing value that no primary gives is marked. The [RER] dwell
rules (arm 40 ms, release 200 ms, at most 20 transitions per minute) apply to every window.

**Boot.**

1. Hardware: both S_GND on, D-BT-SQ disabled, eFuse off (Table 4). The LM1084 runs from VBT; the Teensy boots.
2. `setup()` drives pins 33, 34 LOW, starts the WDT kick (pin 35) and the RTWDOG before the SD probe and Ethernet,
   since SD init blocks up to about 2 s (facts_firmware section 8) and the external watchdog would otherwise fire
   (harmless, because both latches are already clear).
3. Self-test with the charger unpowered: `SGND_GATE` reads the both-high level (section 3.1); `CHG_ARM_RB` LOW;
   `I_PACK` about 1.65 V with a discharge equal to the board load; the return-resistance test below passes.
4. Bring-up P0-P3 as today. The P0 gate reads V_batt, which still reads the pack because pack positive never moves.

**Return-resistance test (replaces the revision-1 `V_PACKN < -0.3 V` rule).** While bonded with a discharge above
1 A, firmware computes R_ret = -V_PACKN / I_PACK over a 5 ms window. A healthy return gives R_ret = R_DS(pair) +
R_contact + R_wire, at most about 0.0012 + 0.020 + R_wire Ohm. Body-diode conduction adds 0.6-1.0 V that does not
scale with current. Firmware latches `ERR_SGND_OPEN` when -V_PACKN > V_D,min + I_PACK x R_allow, with R_allow = 30 mOhm
(contact plus a wire allowance, TODO(calibrate) against B1) and V_D,min the S_GND body-diode V_SD at 1-3 A measured in
B1 (SLPS632 gives V_SD only at 32 A). With the parallel pair, `ERR_SGND_OPEN` requires both channels to be lost; a
single lost channel is detected by `SGND_GATE` (one-high level) and latches `ERR_SGND_DEGRADED`.

**Idle.** Bonded. Pin 34 may stay LOW or HIGH; the eFuse is off either way. REGEN stays LOW per today's Idle rule.

**Run, traction (discharge).** Bonded. Pin 34 HIGH (armed). REGEN LOW. MOT_PWR HIGH per the Death-5 doctrine.

**Regen brake (charge mode).** This sequence needs operator rulings OR-1 to OR-4 (section 9). The Teensy commands the
VESC, so it sequences before the brake current exists. The stored Ag105 codes are the regen codes: reg 0x00 = code 3
(1.75 A), reg 0x01 = 2S, reg 0x02 = 0xFF with MPPTS open, which selects the 18 V default threshold (facts_ag105
section 7). The 18 V threshold lies above the 17.5 V `LIMIT_V_BUS_MAX` and below the 21.2-21.5 V regen node
(facts_prior section 6).

1. Arm: `motorControl()` requests a negative current for at least the 40 ms arm dwell, the transition-rate limit allows
   a window, the pack is below the Fully-Charged restart level, and no charge fault is latched.
2. t0: the command sent to the VESC is held at 0 A (brake pre-arm) and a traction hold is set. Firmware waits t_VD for
   the VESC current to decay (BENCH, B15).
3. t0 + t_VD: MOT_PWR LOW. D-MT-EN is an ideal diode, so V-MOT keeps its charge; the VESC now runs from V-MOT's
   0.48 to about 5 mF only (facts_prior section 6), which is why the traction hold must stand for the whole window.
4. Pin 33 HIGH. Hardware: both S_GND off and S_CHG on (0.1-0.3 ms); the eFuse SHDN rises and the eFuse turns on
   (dVdT ramp). REGEN HIGH once `CHG_PERMIT_RB` and `SGND_GATE` confirm the charge mode. Q_X3 does not clamp BT_BUS,
   because MOT_PWR is LOW. MPPT_DISABLE stays HIGH (MPPT enabled) throughout, because whether the 18 V threshold gates
   charge start while MPPTD is LOW is TODO(verify: Silvertel) (facts_ag105 section 7); this reverses the CLAUDE.md
   section 3 regen strategy for IC1 (OR-4).
5. The X node releases D-BT-SQ about 5 ms after pin 33; D-BT-SQ turns on t_D_ON = 8 ms typical later.
6. t0 + t_VD + t_hold: release the brake command, with t_hold = X-node release + t_D_ON maximum + margin
   (provisionally 16 ms; B9). The VESC raises V-MOT; the Ag105 starts charging when VCHG-IN exceeds 18 V, if its start
   time allows (B3-B5). I_p is regulated by the sense. The traction hold stays set.
7. Exit, when the brake demand has ended for the 200 ms release dwell, or V_rgn has fallen below 18 V minus a margin:
   REGEN LOW; wait until `I_PACK` charge is below 0.1 A for 20 ms, capped at 100 ms; pin 33 LOW. Hardware: eFuse off in
   1.5 us, both S_GND on in about 0.1 ms, D-BT-SQ disabled 0.3-0.7 ms later.
8. MOT_PWR re-close through `assertMotPwrEnable()` only if V_bus is in regulation. Because the charger stops drawing
   below its 18 V threshold, V-MOT ends the window at or above the threshold, which is above the bus, so D-MT-EN
   reconnects onto a node that is not discharged and conducts only once V-MOT bleeds below the bus. If V_rgn is below
   V_bus minus a margin at re-close (for example after a long window), the re-close follows the P3 rule: the motor stays
   held at 0 until V_rgn tracks V_bus. The traction hold is then released.

The exit rule in step 7 limits the "battery disconnected during a charge" case (facts_ag105 section 3.2, brainstorm X7)
to the hardware trips, and in those the eFuse removes the charger input before D-BT-SQ opens (section 2.4 item 3).
The residual overshoot from the Ag105 output capacitance is bench gate B6, which is a hard precondition of any charge
session and of any trip test.

The first regen window after power-up charges on the stored codes before firmware can read them, because the Ag105
start and its I2C readiness follow the same power-up (`AG105_SETTLE_MS`, CLAUDE.md section 3). Firmware reads back
reg 0x00, 0x01 and 0x02 inside every window and refuses further windows on any mismatch. The worst wrong stored code
is code 1 (2.5 A), which gives I_o = 2.5 + I_L = 3.1 A for one burst of at most 0.6 s; the pack current is 2.5 A,
below the 3.2 A U_C2 trip, and the eFuse I_OL bounds the input (review finding fault-m4). A one-time commissioning
write sets the regen codes and restores reg 0x02 = 0xFF, because the fw v24 policy may have left counts 15-27
(12.3-13.4 V) in the EPROM (CLAUDE.md section 3). The fw v24 dynamic reg 0x02 policy must be disabled under IC1.

**FC-charge window (standstill only).** The window is permitted only at standstill (motor command 0, speed below a
threshold) because the FC budget leaves about 0.2 A of traction headroom (section 4.4). At most two windows per boot
are allowed, which bounds the EPROM writes to 8 per boot (OR-5).

1. Preconditions as fw v37 (`FC_CHARGE_ALLOWED`, no FC-only lockout, V_bus at least 13.5 V, between predicted purges,
   ruling 6), plus `SGND_GATE`, `V_PACKN` and both readbacks consistent with the bonded mode, and the window count.
2. BT_BUS LOW (`assertFcChargeEnable()` already does this; Q_X1 enforces it).
3. Pin 33 HIGH (charge mode), confirm `CHG_PERMIT_RB` and `SGND_GATE` low.
4. FC_CHARGE HIGH through `assertFcChargeEnable(true)`. The charger powers up through the eFuse on its stored regen
   codes; with an 18 V threshold above the bus it does not start charging.
5. After `AG105_SETTLE_MS`, read back reg 0x00-0x02. Write reg 0x00 = code 5 (1.25 A), then reg 0x02 = the FC count
   (below the bus minus the path drops, TODO(calibrate); for example count 30 = 13.6 V). Charging starts.
6. Close: reg 0x02 = 0xFF (charging stops), FC_CHARGE LOW, wait for `I_PACK` charge below 0.1 A for 20 ms, pin 33 LOW,
   guarded BT_BUS re-close, then reg 0x00 = code 3. If the charger is unpowered before the code-3 write, the write is
   deferred to the start of the next FC window (the stored code 5 is the safer direction for a regen window).

**H-20 purge.** The purge behaviour is unchanged by IC1 because the FC window still has BT_BUS open, which the X3 loop
rule requires. The rule of ruling 6 (close the window before the predicted purge) applies. The change that IC1 makes
is that the Teensy, the INA253s and the MDACs remain powered from the pack through any bus collapse, because pack
positive never leaves VBT. A purge inside a regen window is benign: BT_BUS is closed in that mode and the bus keeps
the battery.

**Finish (State 3).** Motor 0, FC_CHARGE off, REGEN LOW, then pin 33 LOW after the `I_PACK` exit rule. Pin 34 may
remain HIGH.

**State 99.** The order removes charger input before the changeover:

1. FC_CHARGE LOW and REGEN LOW; pin 34 LOW (FF2 clear, eFuse off).
2. Wait until `I_PACK` charge is below 0.1 A, capped at 20 ms. If the trip source is a pack over-current (U_C2 or
   U_C1), the hardware has already cleared FF1 and FF2 and this wait is skipped.
3. Pin 33 LOW (bonded, D-BT-SQ cross-locked).
4. The existing drains (facts_firmware section 2.1) then run with the eFuse off, so they discharge VBUS and V-MOT into
   the VCHG-IN node and its R1-CHG divider only, not into the Ag105 input capacitance. Whether the drains remain
   adequate is a firmware review item (UNCONFIRMED).

A hung loop during State 99 is covered by the external watchdog and the RTWDOG.

**Teensy reset or brownout.** Pins 33 and 34 fall to their pull-downs; FF1 and FF2 clear; the eFuse opens within
1.5 us; both S_GND turn on within about 0.1 ms; D-BT-SQ is cross-locked off. The pack still supplies the LM1084, so a
brownout requires a pack, harness or LM1084 failure, not an isolation event.

## 4. Quantitative checks

### 4.1 Conduction loss, harness drop and thermal

The peak BT boost input current is bounded by the TPS61288 switch limit, 12 / 15 / 17.1 A min / typ / max at
VIN 7.2 V (SLVSFP3C section 7.5). Table 7 uses 17.1 A as a DC worst case, which overstates the average input current.

Table 7. Bonded-mode losses at 17.1 A.

| Element | Resistance | Loss | Note |
|---|---|---|---|
| S_GND1 or S_GND2, hot, pair sharing | 2.4 mOhm each, 1.2 mOhm pair | 0.35 W each | Table 2; 17.5 C rise at 50 C/W |
| One S_GND after a single gate fault | 2.4 mOhm | 0.70 W | 35 C rise |
| R_SH | 0.5 mOhm | 0.15 W | 2512 power rating TODO(verify) |
| F_PK and holder | TODO(verify: fuse data sheet) | - | Counted in the drop budget below |
| J-BT pins 1 and 2 (existing) | 20 mOhm max each | 5.8 W each at 17.1 A | TB005-762 p.1; pre-existing |

The LM1084 regulates for VIN of at least 6.5 V (SNVS037H section 5.5). At the 7.4 V pack floor and 17.1 A, the
existing two J-BT contacts already drop up to 0.68 V, which leaves VBT - GND = 6.72 V. The new series elements (pair
1.2 mOhm, R_SH 0.5 mOhm, F_PK, its holder, the switch-board terminals and the added harness length) must therefore
total less than 0.22 V / 17.1 A = 12.9 mOhm. This is a design constraint on the harness (review finding electrical
minor). At the in-service level of about 7.2 A at the pack (3 A per channel on the bus, CLAUDE.md RC-BT record, 0.9
boost efficiency assumed) the existing drop is 0.29 V and the margin is large.

In the charge mode S_CHG carries at most the U_C2 trip (3.2 A) forward and the U_C1 trip (3.0 A) in reverse:
3.2^2 x 2.4 mOhm = 25 mW.

### 4.2 Body-diode and SOA cases

1. **Dead time.** During the 100-300 us dead time the board load flows through the S_GND body diodes. At the transition
   current that firmware allows (below 1 A), the dissipation is below 1 W for under 1 ms.
2. **Mis-sequence (traction in the charge mode).** A discharge above 3.0 A trips U_C1 within t_PD = 6-13.5 us
   (SBOS300C section 6.7) plus the 70 us filter plus the S_GND gate rise (88-114 us tau). At 17.1 A x 1.0 V = 17 W for
   about 0.5 ms, the energy is about 9 mJ. Until U_C1 acts, the discharge flows through the Ag105 sense in reverse for
   100-500 us. I_DIS 4 A (DS p.20 row 6) is a continuous figure; the pulse rating of the sense is not given, so bench
   gate B7b tests a 15 A, 1 ms reverse pulse on a sacrificial module, or the operator accepts the risk explicitly.
3. **Both S_GND channels open in the bonded mode.** Sustained body-diode conduction gives 5.6-7 W at the in-service
   7 A and 17 W at the 17.1 A peak, which exceeds the steady thermal path of an SON 5 x 6 package. This now needs two
   independent channel faults, or a common cause (FF1 stuck set with U_C1 dead). Detection is the return-resistance
   test in firmware; the bound is firmware cutting BT_BUS and BT_REG, and the RTWDOG/WDOG1 reset (required, ruling 5)
   drops every RT1987 EN to its pull-down if firmware hangs. No hardware cut exists for this double fault (row F2).
4. **Switching transients.** Each transition commutates current between a channel and the body diode of the same or
   the parallel device; no current is interrupted, so no avalanche energy is expected. The harness inductance is not
   switched. Avalanche rating 328 mJ (SLPS632 p.1) is a margin, not a design point.

### 4.3 Inrush

1. The changeover moves PACK- by at most about 1 V (body diode), so the switched capacitances see negligible charge
   current.
2. D-BT-SQ enabling onto VBT does not cause inrush: VBT is already at pack voltage and VCHG is pre-biased through R_KA
   (or open), so the RT1987 is reverse-biased until the Ag105 raises VCHG.
3. The eFuse closes onto the Ag105 input capacitance at every window entry. The Ag105 input capacitance is not given
   (TODO(verify: Silvertel)). The dVdT capacitor sets the slew; the prior rule of 12 mA/uF at the RT1987 slew and no
   electrolytic on a switched node applies (facts_prior section 10 item 4). In an FC window this inrush lands on the FC
   channel and must stay below OC_FC 1.4 A single sample together with the aux load (bench gate C-3).
4. The MOT_PWR re-close at the end of a regen window is onto a node at or above the 18 V threshold (section 3.3 step 8)
   and causes no inrush in that case; the discharged-node case follows the P3 rule.
5. Pack connection at the harness is unchanged from today (VBT capacitors C1-BT, CIN-5V, C-D12).

### 4.4 Ag105 current codes, the unregulated load I_L, and the HR1 power ceiling

In the charge mode the converter supplies I_o = I_p + I_L (section 1.3). I_L contains the LM1084 input current
(equal to I_5V, BENCH, facts_board section 6.2), the TPS61288 no-load current with BT_BUS open (TODO(verify:
SLVSFP3C)), and 0.32 mA in the V_batt divider. In the regen window BT_BUS is closed, so the BT boost also supplies the
bus aux load: 0.15 A x 16 V / 7.4 V / 0.9 = 0.36 A at the pack (aux 0.1-0.15 A, facts_prior section 7; 0.9 assumed).
This document uses I_L = 0.3 A (FC window) and 0.6 A (regen window) as working values, both UNCONFIRMED (B8).

The module rating is 2.5 A of output (Table 4 JSON code 1; DS p.20). The over-current trip at I_set + 200 mA (DS p.18)
reads only I_p, so firmware must choose codes with I_set + I_L at or below 2.5 A. Table 8 gives the codes. Input power
uses the 0.88 efficiency that DS p.20 gives only at 12 V in, 3S.

Table 8. Reg 0x00 codes (Table 4 JSON) with I_L included.

| Window | Code | I_set | I_o = I_set + I_L | Within 2.5 A? | Input power at V_pack 7.4 / 8.2 / 8.4 V | Constraint |
|---|---|---|---|---|---|---|
| FC | 5 | 1.25 A | 1.55 A | Yes | 13.0 / 14.4 / 14.8 W; 0.90 A at 16 V for 8.2 V | FC budget about 1.1 A after 0.15 A aux (governor 1.25 A) |
| Regen (selected) | 3 | 1.75 A | 2.35 A | Yes | 19.8 / 21.9 / 22.4 W | Meets the 18.9 W peak; misses the 23 W HR1 margin |
| Regen (rejected) | 2 | 2.0 A | 2.6 A | **No** | 21.9 / 24.2 / 24.8 W | Exceeds the rating whenever the regen input exceeds about 21 W |
| (not used) | 1 | 2.5 A | 3.1 A | **No** | 26.1 / 28.9 / 29.6 W | Exceeds the rating at any I_L |

Three consequences follow.

1. **HR1 power ceiling.** Within the rating, the input power is at most 2.5 A x V_pack / 0.88, which is 21.0 W at
   7.4 V and 23.0 W only at 8.1 V. With I_L = 0.6 A the largest legal code is code 3, whose ceiling is 19.8-22.4 W.
   HR1's 23 W criterion (facts_prior section 2.1) therefore fails at every pack voltage with the regen-window I_L.
   Opening BT_BUS in the regen window would reduce I_L to about 0.3 A but would make the bus FC-only through the brake,
   which brings back purge objection 1; code 2 with I_L 0.3 A gives 2.3 A and 19.3-21.9 W, which also misses 23 W.
   This ceiling belongs to the Ag105 at 2S, not to IC1; it applies to every concept that keeps the Ag105.
2. **Two codes and the EPROM.** No single code serves both windows: code 3 in an FC window draws about 1.2 A from the
   bus plus 0.15 A aux, against OC_FC 1.4 A single sample (facts_firmware section 4); code 5 in a regen window has a
   15.6 W ceiling at 7.4 V, below the 18.9 W peak. Section 3.3 stores the regen codes and writes the FC values only
   inside an FC window, so regen windows cost no writes and each FC window costs four (reg 0x00 and reg 0x02, each
   written and restored). Endurance is unpublished (TODO(verify: Silvertel)).
3. **Thermal derating.** The 2S derating (2.0 A at 60 C, 1.75 A at 70 C, DS p.17 Table 9) applies to code 3 above
   70 C module temperature.

The eFuse I_OL is 2.0 A (R_ILIM 9 kOhm, 1.84-2.16 A, SLVSE94G section 6.5). This passes the regen case (code 3 at
22.4 W is 1.24 A at 18 V) with margin and bounds the input to 2.16 A x 21.4 V = 46 W. With PGTH grounded, the
TPS26631 regulates at I_OL for at most tCL_PLIM(dly) and then latches off (Table 3a). The fast-trip level is 3 x I_OL.

### 4.5 Reverse current through the Ag105 sense

In the charge mode any VBT load not supplied by the converter flows backwards through the sense. This is the
datasheet's discharge direction (load return, DS Fig. 1 p.3) and the continuous limit is I_DIS = 4 A (DS p.20 row 6,
applied to this path UNCONFIRMED). U_C1 trips at 3.0 A, below 4 A. The S_GND body diodes do not protect the sense:
they conduct only when I x (R_s + R_DS) exceeds about 0.6-0.8 V, which is 12-60 A for R_s between 10 and 50 mOhm (R_s
is BENCH, so this range is illustrative only). The pulse case is section 4.2 item 2.

### 4.6 Timing against the regen burst and the Ag105 start

Table 9 lists the delay chain of a regen event. The VESC raises V-MOT from 15.9 V to 21.2-21.5 V in 19-47 ms with
onset within about 5 ms of the negative command, stops at about 21.35 V and repeats after about 0.535 s; the burst lasts
0.3-0.6 s (facts_prior section 6).

Table 9. Regen delay chain.

| Step | Delay | Source |
|---|---|---|
| Firmware decision incl. 40 ms arm dwell | 40-42 ms at 1 kHz (median loop 1131 us, worst 9.76 ms) | facts_firmware section 8; [RER] |
| VESC current decay before MOT_PWR LOW | t_VD, unknown | BENCH (B15) |
| FF1 set, S_GND off, S_CHG on, eFuse on | about 0.1-0.3 ms, eFuse dVdT ramp design-dependent | Sections 2.2, 2.4 |
| X-node release of D-BT-SQ | about 5 ms | Section 2.3 |
| D-BT-SQ t_D_ON | 8 ms typ, no maximum | RT1987 DS-00 section 13 |
| Brake hold t_hold | 16 ms provisional (covers the two lines above) | Section 3.3; B9 |
| Ag105 cold start from unpowered to current | unknown | BENCH (B3) |
| Ag105 restart from "Fully Charged" | unknown | DS p.5, p.11; BENCH (B5) |

The switch chain and the arm dwell together delay the brake by about 56 ms plus t_VD, against a 300-600 ms burst. The
brake pre-arm changes the motor-command path; at the v37 drive-law crossover of 6.55 rad/s a 16 ms hold costs
6.55 x 0.016 = 0.105 rad = 6.0 degrees of the 58.1-degree phase margin (CLAUDE.md 2026-11-04 addendum), and the
traction hold removes positive torque for the whole window. Both are motor-path changes (OR-1, OR-2).

The decisive term is the Ag105 start. Two cases apply.

1. **No keep-alive.** D-BT-SQ blocks the pack from VCHG until it turns on, so the Ag105 sees an unbiased output and
   performs Bring-Up. The only measured slope is 0.64 V/s from about 2 V (ML0227, taken with the sense shorted).
   Reaching a 7.4-8.0 V pack takes 8.4-9.4 s; the incident record gives 11.7 s to pass 7.67 V. HR1 fails and HR2
   delivers almost no charge inside a 10.34 s purge interval.
2. **Keep-alive R_KA = 1 kOhm, VBT to VCHG.** VCHG sits at VBT minus R_KA x (Ag105 standby 120-420 uA, DS p.20 row 7,
   plus D-BT-SQ shutdown current 75 uA typ, RT1987 DS-00 section 13) = VBT - 0.2 to 0.5 V. The Ag105 then sees a
   battery at 3.5-4.2 V per cell, which by DS p.6 ("If the battery presents 0V it performs a Bring-Up Charge") should
   skip Bring-Up (UNCONFIRMED). The drain is about 0.5 mA, 12 mAh per day. Ruling 9 classes this resistor as a last
   resort; the [WIRE] alternative is a Run-gated TPS22810 keep-alive (facts_prior section 10 item 3). R_KA is rated
   0.25 W or more (1206): if VCHG reaches the module output limit with the pack at its floor, R_KA dissipates
   (21.4 - 7.4)^2 / 1 kOhm = 0.196 W in the worst back-fed case.

With the charger unpowered between windows, the module sees VCHG pre-biased but no input; the behaviour on each
power-up (Bring-Up, CC start, or Fully-Charged detection on the keep-alive load) is unspecified by the datasheet.
Whether the module back-feeds its own input from VCHG through its power stage while unpowered is also unspecified; if
it does, the eFuse OUT side and, through the eFuse body diode, V_chg (pin 38) read a few volts below VBT, and firmware
must not infer "charger powered" from V_chg below the UVLO level (review finding system-m6). B3, B4 and B5 are go/no-go
gates for HR1 and HR2.

### 4.7 Teensy supply continuity

Pack positive is on VBT in every mode. The pack return is continuous in every mode through a channel or a body diode
(section 1.2). In every non-fault mode the added drop is below 22 mV at 17.1 A (section 4.1), within the 12.9 mOhm
budget. The double-fault case (both S_GND open, body diode at 1.0 V) gives VBT - GND = 7.4 - 0.68 - 1.0 = 5.7 V at the
floor and 17.1 A, below the LM1084 regulation range; this case is already a fault (row F2). Therefore the objection
"the Teensy would brown out" (respin option 2, objection 2) does not apply to IC1 in any single-fault state.

### 4.8 Reference shifts

PCB GND remains the reference of every board measurement. Only pack negative moves relative to GND. Table 10 lists the
shifts with R_s the unknown Ag105 sense resistance.

Table 10. Measurement shifts (positive = reads high).

| Measurement | Bonded discharge (15 A) | Charge mode, I_p charging |
|---|---|---|
| V_batt (VBT - GND, pin 25) | -15 A x (1.2 + 0.5) mOhm = -26 mV plus the J-BT pin-2 contact | +I_p x (R_SH + R_DS(S_CHG) + R_s) |
| BQ29200 bottom cell (VC1 - GND) | -26 mV plus contact | +I_p x (R_SH + R_DS(S_CHG) + R_s) |
| INA253 SNS-FC, SNS-BT | none (referenced to GND, on boost outputs) | none |
| Ag105 CV sense (VCHG - VBat-) | - | Reads V_pack + 35 mV (D-BT-SQ, RT1987 V_FWD) + I_p x (R_SH + R_DS(S_CHG)); pack ends below 8.40 V |
| V_chg (pin 38) | moves to the eFuse input side | unchanged reference |

Two items follow. First, the V_batt over-read in the charge mode interacts with `OV_BATT` (8.5 V single sample,
facts_firmware section 4). At the end of CC the Ag105 holds VCHG - VBat- at 8.4 V, so V_batt reads
8.4 - 0.035 + I_p x R_s. At I_p = 1.75 A (code 3) the reading exceeds 8.5 V for R_s above 77 mOhm; the S_CHG and R_SH
terms (about 3 mOhm) shift that boundary by about 3 mOhm. The trip direction is safe (a nuisance State 99), but the R_s
measurement (B1) must precede any firmware threshold. Second, the BQ29200 over-reads in the charge mode, which makes
its OVP trip early; this is the safe direction.

## 5. Single-fault table

Table 11 lists single faults. "Bounded by" names the first layer that limits the consequence. Rows marked R1 were
added or corrected by review round 1.

Table 11. Single faults.

| ID | Fault | Effect | Bounded by | Detection | Residual |
|---|---|---|---|---|---|
| F1 | One S_GND short | Charge mode: charge current bypasses the sense in parallel with S_CHG + sense; I_p no longer regulated by the module | U_C2 at 3.2 A pack charge clears FF1 and FF2 (eFuse off first); eFuse I_OL | `I_PACK` charge with reg 0x06 near zero (`ERR_ISO_MISMATCH`); `V_PACKN` about 0 in charge mode | One bounded pulse per arming; latched until edge |
| F2 (R1) | Both S_GND channels lost (two faults or a common cause) | Bonded discharge through body diodes, 5.6-17 W | Firmware return-resistance test cuts BT_BUS and BT_REG; RTWDOG reset if hung | `ERR_SGND_OPEN` | No hardware cut; needs two faults |
| F2a (R1) | One S_GND channel lost: Q_Ak short, Zk short, R_GUk open, gate lead open | Other channel carries the return at 0.70 W (17.1 A, hot) | The parallel channel | `SGND_GATE` one-high level, `ERR_SGND_DEGRADED` | Latent until detected; second fault is F2 |
| F3 | S_CHG short | Sense in parallel with S_GND in bonded mode: harmless; charge mode unaffected | - | Undetectable in bonded mode | Latent; with both S_GND lost, traction flows through the sense |
| F4 | S_CHG open | Charge mode: charge returns through its body diode (regulated); reverse load current flows through the S_GND body diodes | Body diodes | `V_PACKN` about -0.7 V in charge mode | Pack ends about 0.7 V below the CV setpoint (availability fault) |
| F5 (R1) | D-BT-SQ power-stage short | Bonded mode: pack tied to VCHG; the Ag105 is unpowered (eFuse off), so no charger output exists | eFuse off by FF1 AND FF2 | Pre-rework incident check (d) | Benign in bonded mode; charge mode unaffected (D-BT-SQ conducts there by design) |
| F6 (R1) | Q_X2 open, X-node fault or EN_SQ_X lead open | D-BT-SQ enabled in bonded mode (pin 32 HIGH) | As F5: charger unpowered | C-2 cross-lock test | Benign alone; with F11 (eFuse short) plus REGEN or FC_CHARGE HIGH in bonded mode it is the ML0227 path, a double fault |
| F7 | FF1 stuck set | Charge mode during traction | U_C1 pulls both Q_A gates low directly (section 2.2 item 2), bonding the pack; FF1 stuck set keeps the eFuse enable only if FF2 is also set | `I_PACK`, `CHG_PERMIT_RB` | Reverse sense pulse until U_C1 acts (B7b) |
| F8 | U_SH or comparator dead | Loss of the 3.0 A / 3.2 A layer | Ag105 OC trip (I_set + 0.2 A, effective if B14 passes), eFuse I_OL | Boot self-test of `I_PACK` midscale | Second layer remains |
| F9 | External watchdog dead | Hung Teensy keeps latches | RTWDOG (required, ruling 5) | Boot test T-W-01 | Depends on RTWDOG |
| F10 | Gate overlap at the tolerance corner | Sub-millisecond sense bypass at charge-mode exit | eFuse already off (1.5 us) | none | Negligible |
| F11 | eFuse short | Charger powered whenever its input is fed; in bonded mode D-BT-SQ is still cross-locked off | Cross-lock; firmware keeps REGEN and FC_CHARGE LOW in bonded mode | Pin 38 and I2C ACK with SHDN_EF LOW; `EF_FLT` | Input ceiling lost in charge mode; Ag105 OC trip and U_C2 remain |
| F12 | Balance-lead negative left in J-BL pin 3, or any pack-direct load sharing GND | Parallel pack-to-GND bond: S_GND and S_CHG bypassed; balance wire carries return current | F_PK does not protect the balance wire | Full harness audit C-1; `V_PACKN` about 0 at all currents | **Fire hazard** (facts_prior section 5); harness keying mandatory |
| F13 | Q_E open or SHDN_EF pull-down open | eFuse enable follows FF2 alone | FF1 clear still bonds the pack and cross-locks D-BT-SQ | C-2 (eFuse state with FF1 clear, FF2 set) | Reverts to the revision-1 bonded exposure; second fault needed for a loop |
| F14 (R1) | VBat- flying lead open | Charge mode: VBat- sits at Vin- (GND) through the sense, which reads 0 A; CC loop open; CV holds VCHG at 8.4 V relative to GND; the module becomes an 8.4 V source of unregulated current for the VBT loads; the pack cannot charge (S_GND body diodes block that direction) and PACK- floats above GND | CV loop (8.4 V); eFuse I_OL | `I_PACK` zero with FF1 set and charger powered; V_batt at 8.4 V with I_PACK zero | Bounded; exit opens D-BT-SQ under the VBT load (X7 class, B6) |
| F15 (R1) | D-MT-EN power-stage short in a regen window | V-MOT tied to the bus: bus feeds the charger; the output feeds the pack (sensed, regulated) and I_L, which returns to the bus through the BT boost | Sense regulates I_p; eFuse I_OL then latch-off (Table 3a); firmware G2 (unaccounted bus power) | G2; V_rgn tracks V_bus with MOT_PWR LOW | A circulating flow below I_OL is not cut in hardware (bounded, not runaway) |
| F16 (R1) | D-BT-EN power-stage short in an FC window | BT boost connected to the bus while the charger is fed from it: same circulating class as F15 | As F15 | G2 | As F15 |
| F17 (R1) | D-BC-FC or D-BC-RG power-stage short | Bonded mode: input reaches the eFuse IN only (eFuse off). Charge mode: input path forced open | eFuse off in bonded mode; as F15 in charge mode | V_chg (pin 38) with FC_CHARGE and REGEN LOW | Benign in bonded mode |
| F18 (R1) | R_KA solder bridge between VCHG and VBT pours | Bonded mode: pack tied to VCHG, charger unpowered; charge mode: parallel to D-BT-SQ | eFuse off in bonded mode | Pre-rework continuity | Benign alone (as F5) |
| F19 (R1) | Ag105 internal switch in parallel with the sense conducts in a charge sub-state | Module regulation blind, as ML0227, but in the charge mode | U_C2 3.2 A, eFuse I_OL and latch | `ERR_ISO_MISMATCH` (I_PACK versus reg 0x06) | Decided by B14 |

Notes:

1. **F4.** With S_CHG open, the charge current crosses the S_CHG body diode in the direction PACK- -> VBat-, so
   V(VBat-) = V(PACK-) - 0.7 V. The Ag105 regulates VCHG - VBat- to 8.4 V, so it holds VCHG - PACK- at about 7.7 V and
   the pack ends about 0.7 V below the setpoint. The direction is safe.
2. **F15 and F16.** With the sense in the return, the pack current is regulated, VBT is clamped by the pack, and the BT
   boost draws what the share loop asks of it, so the flow circulates with losses and does not run away as in ML0227.
   The eFuse latches if the input exceeds I_OL for tCL_PLIM(dly); below I_OL only the firmware G2 guard acts. The power
   circulating below I_OL is at most 2.16 A x 21.4 V = 46 W of input. G1-G3 must be ported to production builds before
   the first charge session.
3. **F12** is an assembly fault; the rework must physically remove the balance-lead negative wire from the J-BL plug,
   and C-1 must pass before the first charge.

## 6. Hard-requirement status

Table 12 states HR1-HR5 (facts_prior section 2.1) for IC1 after review round 1.

Table 12. HR status.

| HR | Status | Reason |
|---|---|---|
| HR1 regen | FAILS as stated; BENCH for the reduced criterion | Within the 2.5 A module rating and with I_L 0.6 A, the input ceiling is 19.8-22.4 W (code 3, Table 8), below the 23 W criterion at every pack voltage; it exceeds the 18.9 W peak by calculation with the unverified 2S efficiency. Capture also depends on the Ag105 cold start (B3-B5), R_KA (ruling 9) and four operator rulings OR-1 to OR-4 (brake pre-arm, traction hold, per-event MOT_PWR cycling, MPPTD HIGH in regen). Without R_KA it fails outright (8-12 s Bring-Up). |
| HR2 FC charging | Blocked at system level, as before IC1 | The FC window still opens BT_BUS (Q_X1), so the bus is FC-only and purges to about 1 V collapse it into UV_BUS within 20 ms (facts_prior section 7). The budget at code 5 (0.90 A input plus 0.15 A aux) leaves about 0.2 A of traction headroom under the 1.25 A governor, so windows are standstill-only. Each window costs four EPROM writes of unpublished endurance (OR-5). Start time B3-B5 is a go/no-go gate. |
| HR3 no circular loop | PROVEN_CALC for the bonded mode; bounded by external backstops in the charge mode | Bonded mode: the charger is unpowered by FF1 AND FF2 and D-BT-SQ is cross-locked, so no single fault recreates the ML0227 loop (rows F5, F6, F17, F18). Charge mode: Q_X1 and Q_X3 forbid BT_BUS with an open bus-to-charger path; a power-stage short (F15-F17) gives a bounded circulating flow, cut by the eFuse latch above I_OL and by firmware G2 below it. Conditional on C-1, B10, B14 and B16. |
| HR4 no runaway | Bounded by U_C2 (3.2 A pack) and the eFuse (2.16 A, 46 W input, latch-off within 233 ms) | The Ag105 OC trip (I_set + 0.2 A, DS p.18) is an additional layer only after B14 shows that the sense carries the return in CC, CV, Fully Charged and restart. Converter output above rating by I_L is bounded by the code choice (Table 8). |
| HR5 fail-safe inhibit | PROVEN_CALC, bench-gated | Bonded + D-BT-SQ disabled + eFuse off with the Teensy unpowered, in reset, hung, or with 3V3 absent (Table 4); watchdog clear within 56.8-68.7 ms; no autonomous re-arm (edge-set latches). Bench: B11, B16, C-2. |

The respin note's five objections to two-leg switching (facts_prior section 8) resolve as follows:

- objection 2 (brownout) does not apply in any single-fault state;
- objection 5 (reference shifts) reduces to I x R millivolts (Table 10);
- objection 3 (no pack buffering) applies only in FC windows, where the existing firmware already opens BT_BUS;
- objection 4 (per-event transitions) is replaced by a larger cost: a MOT_PWR cycle, a brake hold and a traction hold per
  regen event, and a cold Ag105 start per window;
- objection 1 (purge) is unchanged.

## 7. Rework, parts and cost

### 7.1 Rework steps on the manufactured board

The following procedure is a proposal; it is not to be executed by this study. Each step is a never-rotated bodge
record.

1. Disconnect the pack and every supply. Confirm that VBT, VBUS and VCHG-IN read 0 V.
2. Run the incident.md section (d) damage checks on D-BT-SQ, D-BC-RG, D-MT-EN and the FC channel. A failed check stops
   the rework.
3. Measure the Ag105 module standoff (gap between the module body and the board). If no stub of at least 1 mm can be
   soldered on pins 10, 14 and 15 after a cut, use the fallback: cut every module pin and remove the pins one by one
   (incident.md section (d), Ag105 pads), then mount the module on a carrier with pins 10, 14 and 15 brought out by
   flying leads and the other pins returned to their pads. The carrier is a design-detail item.
4. Cut Ag105 pins 14 and 15 between the module body and the PCB. Leave the board-side stubs in their GND barrels.
   Solder one flying lead (at least 0.5 mm2, about AWG 20) to both module-side stubs.
5. Cut Ag105 pin 10 the same way. The board-side stub (VCHG-IN) goes to the eFuse IN; the module-side stub goes to the
   eFuse OUT. Both leads at least 0.5 mm2.
6. Locate the 10 kOhm EN bodge resistors on nets D-BT-SQ and D-BT-EN (OQ-7). Cut the 0.254 mm top traces at the
   segments of section 2.3, on the Teensy side of each bodge resistor. Bridge each cut with 4.7 kOhm (0603). Solder a
   fine lead from the EN-pad side of each cut to the switch board.
7. Solder taps to the header contacts of pins 29, 30, 31 (gate inputs of Q_X1/Q_X3), pins 10, 16, 17, 21, 22, 23, 33,
   34 and 35 (facts_board section 7.2 header map), and 3V3 and GND from J3.
8. Subject to operator ruling 9: R_KA 1 kOhm, 1206, 0.25 W or more, between the VCHG pour (C-D11 pad) and the adjacent
   VBT pour at D-BT-SQ (30.8-35.0 x 48.3-49.8 mm). Check for a bridge to the adjacent pour after soldering (row F18).
9. Build the switch board (Figure 1, Figure 2, Table 3) and mount it at the pack harness. Route the pack negative
   through F_PK and R_SH to PACK-, PACK- to both S_GND drains and the S_CHG source, both S_GND sources to J-BT pin 2,
   the S_CHG drain to the VBat- flying lead. Use Kelvin taps on R_SH. Take VBT_T through F_T at the tap. Keep the total
   added series resistance below 12.9 mOhm (section 4.1). Fit a keyed, polarized pack connector.
10. Remove the balance-lead negative wire from the J-BL plug, insulate it, and fit a blank in the J-BL pin 3 position
    (X1). Leave J-BL pins 1 and 2 as they are.
11. Mandatory: wire BQ29200 OUT (pin 8, no copper, SON package) through Q_OV (BSS138, two drains) into N1 and N2, so
    that a cell OVP forces the bonded mode and removes charger input. The OUT drive levels are TODO(verify: SLUSA52C
    section 7.5); the soldering is UNCONFIRMED workmanship. If the pin cannot be reached, charging is not enabled.
12. Record the rework as never-rotated hardware bodge records in CLAUDE.md (operator action) and amend the IO CSV for
    the new pins before any firmware change.

### 7.2 Parts list and cost

Table 13 lists the parts. Prices are rough estimates for budgeting, not quotes; no distributor page was read.

Table 13. Parts list.

| Qty | Part | Role | Rough unit cost (USD, estimate) |
|---|---|---|---|
| 3 (+1 spare) | CSD18510Q5B | S_GND1, S_GND2, S_CHG | 2-3 |
| 1 | TPS26631PWPR | eFuse | 3-4 |
| 1 | INA240A3 | Pack-current amplifier | 2-3 |
| 2 | TLV3011 | U_C1, U_C2 | 1 |
| 1 | SN74LVC74A | FF1, FF2 | 0.5 |
| 1 | TPS3431 | Watchdog | 1-2 |
| 12 | BSS138 | Q_A1, Q_A2, Q_C, Q_D, Q_E, Q_X1, Q_X2, Q_X3a/b/c, Q_OV | 0.1-0.2 |
| 1 | BSS84 | Q_B | 0.2 |
| 3 | BZT52C15 | Z1, Z2, Z3 | 0.1 |
| 1 | 0.5 mOhm 2512 shunt | R_SH | 1-2 |
| 1 | 20 A blade fuse and holder | F_PK | 3-5 |
| 1 | 0.5 A fuse | F_T | 0.5-1 |
| set | Resistors (0.1 % for comparator dividers, R_KA 1206), capacitors, BAT54 x 8 | - | 3-6 |
| 1 | Two-layer switch board (custom) or prototyping board | - | 5-30 |
| set | Wire 0.5 mm2 and 2.5 mm2, ring terminals, keyed 30 A pack connector | Harness | 5-12 |

The estimated total is USD 40-85, against USD 505-540 for the BQ25798 design of the prior study (facts_prior section
11). The estimate is UNCONFIRMED.

## 8. Firmware, telemetry and HIL impact

The following changes are required; none are made by this study.

1. **Pin map.** Nine new pins (Table 5) into the CSV first, then the `#define` block; pin 20 reserved.
2. **Gate flag.** `AG105_VBATN_ISOLATED` was defined as "the Ag105 battery return is not tied to PCB GND"
   (facts_firmware section 3.4). Under IC1 that statement is true only in the charge mode. A new flag
   (for example `PACK_RETURN_CHANGEOVER`) should gate charging, and `AG105_VBATN_ISOLATED` should be redefined or
   retired; the naming decision is the operator's.
3. **Mode manager.** A new module that owns pins 33 and 34, enforces the entry preconditions, the [RER] dwells and
   rate limit, the `I_PACK` exit rule and the window count, and is called by `chargingControl()` at 1 kHz for regen
   (today 50 Hz) and by State 99.
4. **Motor-path changes.** The brake pre-arm hold, the VESC decay wait and the traction hold for the whole regen window
   and its exit (OR-1, OR-2).
5. **MOT_PWR doctrine.** Per-event MOT_PWR LOW in regen windows and the guarded re-close of section 3.3 step 8, with
   host-native tests that the motor stays at 0 until V_rgn tracks V_bus (OR-3).
6. **Ag105 policy.** Stored regen codes; FC values written only inside FC windows; readback of reg 0x00-0x02 inside every
   window; fw v24 dynamic reg 0x02 policy disabled; MPPTD HIGH in IC1 windows (OR-4).
7. **chargerHasPower().** Must use `CHG_ARM_RB` (SHDN_EF, effective enable) AND NOT `EF_FLT` AND the feed path, so
   that `pollAg105()` does not fault on a NAK after an eFuse latch. V_chg alone is not sufficient (section 4.6).
8. **Watchdog.** Pin 35 kick after `detectFaults()` each iteration; RTWDOG/WDOG1 per ruling 5; no EEPROM commit while
   pin 33 or 34 is HIGH.
9. **Faults.** New `ERR_SGND_OPEN` and `ERR_SGND_DEGRADED` (section 3.3), `ERR_ISO_MISMATCH` (`I_PACK` versus reg 0x06
   beyond a tolerance, F1, F19), `ERR_CHG_TRIP` (readback clear while commanded set), and a boot self-test fault. Port
   G1-G3 and the trip latch to production builds; `FAULT_SWITCH_CONFLICT` should run in BENCH_TEST builds as well and
   must use the derived BT_BUS state (section 2.3 item 3).
10. **State 99.** The order of section 3.3, and a review of the drains with the eFuse off.
11. **Telemetry.** `switch_state` has two spare bits: charge mode and effective arm. `I_PACK` and `V_PACKN` need new
    fields, which is a protocol bump (v5 is already proposed); the protocol-bump procedure applies.
12. **HIL.** The simple plant needs a PACK- node, the Ag105 sense in the return, the keep-alive, the switches, the
    eFuse with latch-off, the D-BT-SQ cross-lock and the unregulated I_L supply. The hi-fi engine's `BT_SEQ` semantics
    (pack to boost input) contradict the netlist and must be corrected first (facts_firmware section 9). The
    status-level Ag105 model cannot represent Bring-Up, Fully-Charged cycling or start latency, so the HIL cannot test
    HR1 or HR2; the bench gates decide them.
13. **Tests.** Host-native tests for the mode manager ordering, the exit rule, the State-99 ordering, the motor holds,
    the MOT_PWR re-close rule and every new fault.

## 9. Open questions, operator rulings and bench gates

Table 14 lists the gates in the order they should run. No gate has been executed. Gates marked GO/NO-GO decide whether
IC1 delivers a hard requirement at all and should run on a bench rig before the board rework.

Table 14. Bench gates.

| ID | Gate | Pass condition | Blocks |
|---|---|---|---|
| D-1 | incident.md (d) damage checks (D-BT-SQ, D-BC-RG, D-MT-EN, FC channel) | All pass | Rework |
| D-2 | Ag105 module standoff | Solderable stub of at least 1 mm, or the carrier fallback chosen | Rework step 3 |
| B3 | Ag105 cold start with R_KA pre-bias, input applied, 0.1 A code (code 12), on a spare module and a bench return through its sense | Current flows without a Bring-Up ramp; time recorded | **GO/NO-GO** HR1, HR2 |
| B4 | Ag105 state after power-up on the keep-alive load only | Behaviour recorded | **GO/NO-GO** HR1 |
| B5 | Restart latency from Fully Charged when the pack is below 8.0 V | Recorded | **GO/NO-GO** HR1 |
| B14 | Ag105 sense carries the return: reg 0x06 versus I_PACK across CC, CV, Fully Charged and restart | Agreement within tolerance in every sub-state | HR3, HR4 Ag105 layer |
| B16 | TPS26631 latch-off under sustained I_OL with MODE open and PGTH grounded | Latches within 233 ms; FLT asserted; stays off | HR3, HR4 |
| C-1 | Full harness audit after rework, pack absent and with every accessory connected: PACK- to GND with both S_GND gates held low | Open in the charge direction (body diode reverse); no other pack-direct load or shared GND path (F12) | Everything |
| B2 | OQ-7: which RT1987 EN nets carry the 10 kOhm pull-down, and where | Located on the EN-pad side of the cuts | Rework step 6 |
| C-2 | Mode toggle with charger unpowered | `SGND_GATE` levels, readbacks, `V_PACKN`, loaded gate at least 4.5 V at VBT 7.4 V, derived BT_BUS state, eFuse state with 3V3 removed and with the FF2.Q lead open, single-channel gate faults; U_C1 trips at 3.0 +/- 0.4 A on an injected load | Any charging |
| C-3 | eFuse turn-on inrush in an FC window | FC channel peak plus aux below 1.4 A | FC windows |
| B1 | Ag105 sense resistance R_s and S_GND body-diode V_SD at 1-3 A | Values recorded; OV_BATT margin (Table 10) and R_allow checked | Firmware thresholds |
| B6 | Charge-mode exit with current flowing (X7): VCHG overshoot when D-BT-SQ opens at 0.5, 2.0 and 3.2 A, with the eFuse-first order and with D-BT-SQ alone | VCHG below the 40 V D-BT-SQ VIN rating and the C-D11 rating; recorded | **Hard precondition of any charge session and any trip test** |
| B7 | Reverse current through the Ag105 sense at 3 A for 60 s, module unpowered and powered | No damage; reg 0x06 and status recorded | U_C1 threshold |
| B7b | Reverse pulse 15 A for 1 ms through the sense, sacrificial module | No damage; or operator accepts the risk | Mis-sequence residual |
| B8 | I_5V and BT boost no-load input current (I_L) | Recorded; Table 8 recomputed | Code choice |
| B9 | D-BT-SQ t_D_ON distribution and X-node release on this board | Maximum recorded; t_hold set to max + margin | Brake pre-arm |
| B10 | BSS138 R_DS(on) at V_GS 2.5-3.3 V for Q_X1, Q_X2, Q_X3, Q_E | Clamps hold EN below 0.6 V and SHDN_EF below 0.8 V | HR3, HR5 |
| B11 | Watchdog forced-hang test (T-W-01 class) | Latches clear within 68.7 ms; no re-arm | HR5 |
| B12 | Charger-independent gates carried over: S0-R3 / T-E-03, M-R1, M-R2, T-E-01 | As facts_prior section 11 | HR1, HR2 |
| B13 | Teensy VUSB-VIN pad state | Recorded | Bench safety |
| B15 | VESC current decay after a 0 A command | t_VD recorded | Regen sequence |

Operator rulings required before any build:

- **OR-1** brake pre-arm hold (motor-command path change, about 6 degrees of phase margin);
- **OR-2** traction hold for the whole regen window and its exit;
- **OR-3** per-event MOT_PWR LOW in regen windows, which reverses the Death-5 doctrine of continuous MOT_PWR in Run
  (the re-close follows `assertMotPwrEnable()` and the P3 rule);
- **OR-4** MPPTD HIGH during IC1 regen windows, which reverses the CLAUDE.md section 3 strategy;
- **OR-5** four EPROM writes per FC window, at most two windows per boot, against unpublished endurance;
- **ruling 9** R_KA keep-alive;
- **ruling 3 / HR3-HR5** that FC-window feeding of the charger from the bus with the hardware layers of section 2 meets
  the fail-safe-inhibit clause (CLAUDE.md still records R3 as "the bus must never feed the charger in Run");
- **HR1 criterion**: whether the 23 W margin is relaxed to the 18.9 W peak, since no legal Ag105 code meets 23 W with
  the regen-window I_L.

Open questions that no bench gate in this list closes:

1. The function of the undocumented internal switch drawn in parallel with the Ag105 sense (DS Fig. 1 p.3). Pulling LD
   (pin 20 of the module) to Vin- may keep it open (UNCONFIRMED). TODO(verify: Silvertel). B14 measures its effect.
2. Ag105 EPROM write endurance. TODO(verify: Silvertel).
3. Whether the 18 V threshold gates charge start while MPPTD is LOW, and whether an in-progress charge stops below it.
   TODO(verify: Silvertel).
4. The pack maximum charge current and protection board (pack datasheet missing, facts_prior section 9).
5. Whether the 0.88 efficiency holds at 2S and 16-21 V input (DS p.20 gives only 12 V, 3S).

## 10. Review round 1 adjudication

### 10.1 Method

Three adversarial reviews (fault, electrical, system) returned "survives with fixes" and no fatal finding. Each finding
was checked against the primaries. The TPS26631 figures were re-read from SLVSE94G (September 2018, revised June 2024),
fetched from the TI site for this adjudication and not saved in the repository. The other checks used the local
datasheets, the JSON tables, `docs/charger_replacement_evaluation_2026-11-05.md`,
`docs/reviews/charger_eval_2026-11-05/incident.md` and the facts files. Every accepted finding changed the design
body as recorded below.

### 10.2 Fault review

| Finding | Verdict | Evidence and design change |
|---|---|---|
| M1 D-BT-SQ is the only barrier in the bonded Run row; U_C2 does not see the loop current | ACCEPTED | The loop current VCHG -> VBT -> BT boost does not pass R_SH, so U_C2 cannot bound it. incident.md section (d) records D-BT-SQ at 11-13 A (UNCONFIRMED) against 8 A continuous / 20 A for 10 ms (RT1987 DS-00 p.6), so a shorted D-BT-SQ is credible. Fix F1(a) adopted: the eFuse enable is FF1 AND FF2 (section 2.4 item 3), the bonded Run row no longer powers the charger (Table 6), D-1 damage checks precede rework, rows F5, F6, F18 rewritten. |
| M1 sub-claim: TPS26631 latch-off behaviour UNCONFIRMED because the tCL_PLIM row omits it | REFUTED in part | SLVSE94G Table 8-1 lists TPS26631 under MODE open: 2 x I_OL for tCB(dly), then 1 x I_OL for at most tCL_PLIM(dly), then latch-off; section 8.3.7.1.2 describes the same for TPS26631. Only the EC tolerance row for tCL_PLIM omits the part; section 8.3.7.1.1 gives 162 ms typical. The latch-off is specified; the 129-202 ms tolerance is applied with that caveat (Table 3a). Bench gate B16 retained as a check. |
| M2 single gate-drive faults turn S_GND off and release the cross-lock | ACCEPTED | S_GND is now two channels with independent pull-up, zener and Q_A (section 2.2 item 1); the cross-lock is driven from FF1./Q as well as the gates (section 2.3 item 1), so a gate fault does not release D-BT-SQ. Rows F2, F2a added. A hardware V_DS comparator was not added: the return-resistance test plus the parallel channel make the hazard a double fault. |
| M3 RT1987 power-stage shorts are not covered by EN interlocks | ACCEPTED | Rows F15-F17 added. In the bonded mode the charger is unpowered, so these faults are benign there. In the charge mode the flow circulates with the pack current regulated; the eFuse latch bounds it above I_OL and firmware G2 below it (section 5 note 2). HR3 now names the eFuse as a bounding layer. |
| M4 eFuse SHDN has an internal pull-up; a high-Z FF2 enables it | ACCEPTED | SLVSE94G section 6.5: V(SHDN) open circuit 2.48-3.3 V, V(SHUTR) 2 V, I(SHDN) -10 uA. SHDN_EF now has a 22 kOhm pull-down (0.22 V worst case) and the Q_E clamp (section 2.4 item 3); C-2 tests 3V3 removed and the FF2.Q lead open. |
| M5 per-event MOT_PWR opening reverses the Death-5 doctrine; no motor hold-off | ACCEPTED | Section 3.3 regen steps 2, 3, 7, 8: VESC decay wait, traction hold for the window, re-close only from a regulated bus, P3 rule if V_rgn is below V_bus. The 18 V stored threshold leaves V-MOT above the bus at exit, so the normal re-close is onto a charged node. Operator ruling OR-3. |
| m1 F5, F6, F14 rows wrong | ACCEPTED | Rows rewritten (F14 per the reviewer's analysis, which is consistent with DS Fig. 1). |
| m2 ERR_SGND_OPEN nuisance-trips through the J-BT contact drop | ACCEPTED | 15 A x 20 mOhm (TB005-762 p.1) = 0.30 V. Replaced by the current-normalised return-resistance test (section 3.3). |
| m3 reverse pack polarity adds the Ag105 to the destroyed parts | ACCEPTED | Keyed, polarized pack connector made a rework requirement (step 9). DS-style reversal protection not added; recorded as optional. |
| m4 stored EPROM code 1 gives 3.1 A output before readback | ACCEPTED | Readback inside every window, refusal on mismatch, one-time commissioning write, regen codes stored (section 3.3). The first-window residual is stated: 3.1 A output for at most one 0.6 s burst. |
| m5 BQ29200 OUT wiring optional | ACCEPTED | Step 11 is mandatory into N1 and N2; charging is not enabled if the pin cannot be reached. |
| m6 clamped EN nodes read HIGH in firmware | ACCEPTED | Derived BT_BUS state and the source-less-bus refusal (section 2.3 item 3); no spare pin remains for a direct readback. |
| m7 S_CHG partial enhancement while PACK- is below GND | ACCEPTED | S_CHG gate pull-down, Z3 and Q_D now return to PACK- (section 2.2 item 5). |
| m8 unfused VBT gate-drive tap | ACCEPTED | F_T 0.5 A at the tap (VBT_T). |
| m9 TPS3431 details unspecified | ACCEPTED | Marked TODO(verify: SNVSB66A) in Table 3; the CLK/clear race is noted as availability only. |
| m10 cross-lock requires pin 32 LOW in bonded mode, reversing the CSV/CLAUDE.md doctrine | REFUTED after the fix | With Q_X2 driven from FF1./Q, the hardware holds D-BT-SQ off in the bonded mode with pin 32 HIGH, so the pin-32 doctrine stands unchanged (section 2.3 item 1). |

### 10.3 Electrical review

| Finding | Verdict | Evidence and design change |
|---|---|---|
| eFuse UVLO default sits on the bus voltage | ACCEPTED | SLVSE94G section 6.5: 15.1/15.46/15.9 V rising, 14.0/14.47/15.1 V falling with UVLO to GND. External divider 100 k / 13 k sets 10.4 V rising, 9.75 V falling (section 2.4 item 4). OVP default re-checked: 34.3 V typical (section 8.3.4), above the 21.4 V regen node. |
| Trip path forces the X7 case; ordering not specified | ACCEPTED | eFuse enable = FF1 AND FF2, so every FF1 clear removes input within 1.5 us (tSD(dly), section 6.6), before the S_GND gates rise and before the X-node cross-lock (0.3-0.7 ms). B6 made a hard precondition of any charge session and trip test. |
| HR3/HR4 PROVEN_CALC rests on the restored sense; internal parallel switch | ACCEPTED | HR3 and HR4 restated (Table 12); row F19 and gate B14 added. |
| Pin-stub soldering may be impossible | ACCEPTED | Gate D-2 and the carrier fallback (step 3). |
| Harness not audited for other pack-direct loads | ACCEPTED | C-1 extended to a full harness audit with every accessory connected; F12 widened. |
| SGND_GATE divider loads the gate; readback expectations wrong | ACCEPTED | Recomputed: 10 k against 30 k gives 0.75 x VBT and a reading of VBT / 4 (2.13 V at 8.5 V), as the reviewer states. Replaced by a 100-200 kOhm weighted summing readback (section 3.1); loaded-gate acceptance at 4.5 V in C-2. |
| SHDN pull-down needed | ACCEPTED | Same fix as fault-M4. |
| R_KA power rating | ACCEPTED | (21.4 - 7.4)^2 / 1 kOhm = 0.196 W; 1206, 0.25 W or more specified. |
| No comparator input filtering | ACCEPTED | 1.5 kOhm / 47 nF (70 us) on both comparator inputs (section 2.4 item 7). |
| F2 is bounded by the MCU watchdog; 17 W uses the peak as DC | ACCEPTED | Row F2 and section 4.2 item 3 name the RTWDOG reset as a bound; the in-service 5.6-7 W figure is stated beside the peak. |
| Hot-body-diode corner on S_CHG | ACCEPTED | Same fix as fault-m7. |
| Table 10 omits R_DS(S_CHG) and R_SH | ACCEPTED | Table 10 corrected; boundary restated at code 3. |
| Harness drop against the LM1084 6.5 V minimum | ACCEPTED | Section 4.1: the existing contacts leave 6.72 V at 17.1 A and 7.4 V; a 12.9 mOhm budget for the added series elements. |
| TPS3431, TLV3011, INA240 and BSS138 figures not independently verified | ACCEPTED | Marked as not re-verified in Table 3; B10 widened to all clamps. |
| Reverse sense pulse overstress | ACCEPTED | Gate B7b or explicit risk acceptance. |

### 10.4 System review

| Finding | Verdict | Evidence and design change |
|---|---|---|
| M1 HR1 has no power margin; Table 8 contradicts section 1.3 | ACCEPTED | Table 4 JSON code 1 = 2500 mA is the module maximum; revision-1 Table 8 put code 2 at 2.6 A. Recomputed: within 2.5 A the ceiling is 21.0 W at 7.4 V and 23.0 W only at 8.1 V; code 3 (selected) gives 19.8-22.4 W. HR1 restated as FAILS against 23 W (Table 12, section 4.4 item 1). |
| M2 no single code serves both windows; EPROM writes per window | ACCEPTED | Regen codes stored, so regen windows write nothing; FC windows standstill-only, four writes each, at most two per boot (OR-5). Endurance remains TODO(verify: Silvertel). |
| M3 FC window never lowers reg 0x02 below the bus | ACCEPTED | facts_ag105 section 7: default 18 V with MPPTS open, above the 16 V bus. FC sequence now writes the FC threshold after power-up and restores 0xFF before closing (section 3.3). |
| M4 MOT_PWR cycling cost understated | ACCEPTED | Regen sequence fully specified (VESC decay, traction hold, [RER] dwells and rate limit, re-close rule); inrush case analysed (section 4.3 item 4); rulings OR-1 to OR-3. The "about 12 ms" claim is withdrawn (Table 9). |
| M5 HR1/HR2 rest on R_KA and unmeasured Ag105 timing | ACCEPTED | B3-B5 are GO/NO-GO gates before any build; R_KA is listed as ruling 9; F19/B14 carry the internal-switch risk. |
| M6 HR2 overstated as budget PROVEN_CALC | ACCEPTED | HR2 restated as blocked at system level with a standstill-only budget (Table 12). |
| M7 State-99 and trip ordering force X7 | ACCEPTED | State 99 re-ordered (eFuse off, bounded I_PACK wait, then bonding); hardware trips remove input first by construction. |
| M8 F5/F6 bound overstated; eFuse may regulate indefinitely | ACCEPTED in part, REFUTED in part | The U_C2 overstatement is accepted and removed. The concern that the TPS26631 may regulate at I_OL indefinitely is refuted by SLVSE94G Table 8-1 (latch-off after tCL_PLIM(dly) with MODE open). The bonded-mode loop no longer exists with the AND-gated eFuse. A circulating flow below I_OL in the charge mode remains firmware-bounded (F15 note). |
| m1 pin 20 is needed for WDOG1_B | ACCEPTED, with a correction | The charger evaluation (section 5.1 timer row) says pin 20 is "acceptable" for WDOG1_B and that pin 19 must not be used; it does not say pin 20 is the only route. Pin 20 is nevertheless reserved and SGND_GATE moved to pin 23. |
| m2 ruling 3 must be re-stated | ACCEPTED | With the AND-gated eFuse the bus no longer feeds the charger in bonded Run; FC-window feeding remains and is listed for an operator ruling (section 9). |
| m3 firmware/HIL burden larger than stated | ACCEPTED | Section 8 expanded; the HIL cannot test HR1 or HR2. |
| m4 chargerHasPower() must include the eFuse fault state | ACCEPTED | `EF_FLT` on pin 10 and `CHG_ARM_RB` on the SHDN_EF node (section 8 item 7). |
| m5 buildability plausible but not shown | ACCEPTED | D-1, D-2 and the carrier fallback; every step is a bodge record. |
| m6 R_KA back-bias may back-feed VCHG-IN | ACCEPTED | Stated as unspecified; firmware must not infer charger power from V_chg below UVLO (section 4.6). |
| m7 objection accounting | ACCEPTED | Section 6 list rewritten. |

### 10.5 Post-review status

IC1 survives review round 1 as a safe isolation design, but it does not demonstrate either harvesting requirement.

1. **Safety (HR3-HR5).** With the eFuse enabled only by FF1 AND FF2, no single fault in the bonded mode can power the
   charger and route its output to the pack, and every hardware exit removes charger input before D-BT-SQ opens.
   HR5 is PROVEN_CALC subject to B10, B11, B16 and C-2. HR3 and HR4 are bounded by U_C2 (3.2 A) and the eFuse (2.16 A
   input, latch-off within 233 ms per SLVSE94G Table 8-1); the Ag105's own regulation counts only after B14. A
   charge-mode circulating flow below I_OL after a power-stage short is bounded but cut only by firmware G2.
2. **HR1.** FAILS against the 23 W criterion at every legal Ag105 code with the regen-window I_L; this ceiling is a
   property of the Ag105 at 2S and applies to every concept that keeps the Ag105. The 18.9 W peak is met by calculation
   only. Capture further needs four operator rulings (OR-1 to OR-4), R_KA (ruling 9) and passing GO/NO-GO gates B3-B5.
3. **HR2.** Blocked at system level exactly as before IC1, with a standstill-only budget and four EPROM writes per
   window.
4. **Residual uncertainty.** The largest unknowns are the Ag105 cold-start and restart timing (B3-B5), the internal
   switch in parallel with the sense (B14), the EPROM endurance, and the module standoff (D-2). The first three can be
   measured on a spare module with a bench return before any board rework, and that order is recommended.
