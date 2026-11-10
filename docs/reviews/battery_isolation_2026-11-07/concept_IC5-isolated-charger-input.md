# IC5: Isolated Charger Input (Isolated DC-DC Ahead of the Ag105, Ag105 Vin- Lifted)

Date: 2026-11-07. Board revision 20260622, fw v37 rev 2 (`AG105_VBATN_ISOLATED 0`, `FC_CHARGE_ALLOWED 0`).
Inputs: `facts_board.md`, `facts_ag105.md`, `facts_firmware.md`, `facts_prior.md` and `brainstorm.md` in this folder.
Status: design dossier, revised after review round 1 (section 10). Nothing in this document has been ordered, built,
desoldered or flashed.

## 0. Summary

**Post-review status (round 1, section 10).** IC5 survives as a **sense-restoration and fail-safe charger-input
inhibit retrofit**. It does not add a switch at the battery terminals (section 0.1). After the round-1 fixes, HR4 holds
by a specified maximum (a TPS259474L eFuse on the brick secondary, section 2.2a) in every single-fault case that
bypasses the sense. HR5 holds in hardware out of POR, subject to bench timing. However, no IC5 mode meets HR1, HR2 and
HR3 together (section 6). Warm regen capture requires the Ag105 to charge at constant current for the whole of Run,
because the brick removes the reg 0x02 input-threshold discriminator. Mode C fails HR3 by construction. Mode S meets
HR3 only with a conduction-keyed limiter, and it is restricted to standstill with RTWDOG and purge prediction as hard
preconditions. The choice among these is one coupled operator ruling (section 9.1, Q1). The numbered conclusions below
are the original round-0 text; where section 10 changes one, the change is marked.

### 0.1 Scope against the request

IC5 adds no switch between the battery terminals and J-BT or J-BL. In Mode C the pack is not isolated during charging.
In Mode S the pack is isolated from the bus only by the existing BT_BUS switch (D-BT-EN), which fw v37 already opens
for FC windows (`assertFcChargeEnable()`). What IC5 adds is the restoration of the Ag105 current sense and a fail-safe
inhibit on the charger input. Table 0 maps IC5 against the five objections to option 2 of the re-spin note
(facts_prior section 8).

Table 0. IC5 against the option-2 objections.

| Option-2 objection | IC5 outcome |
|---|---|
| 1. The bus needs another source during charge windows; the H-20 purges to about 1 V | Mode C: removed (the pack stays on the bus). Mode S: inherited unchanged (section 4.5) |
| 2. The Teensy browns out (LM1084 off VBT) | Removed: the pack never leaves VBT (section 4.7) |
| 3. No pack buffering | Mode C: removed. Mode S: inherited for the bus, removed for VBT |
| 4. Switch transitions per regen event | Replaced by "the charger must run continuously at CC through Run to capture regen" (section 4.4, finding S-M1) |
| 5. BQ29200, V_batt divider and BT sense references move | Removed: no reference moves (section 4.8) |

Whether a charger-side isolation satisfies the request is operator ruling Q0 (section 9.1).

This dossier develops concept IC5. The concept keeps the pack wired exactly as it is today and isolates the Ag105
**input** instead. An isolated DC-DC converter (the **brick**) is inserted between net `VCHG-IN` and the Ag105 input
pins. Ag105 Vin- (pin 4) is cut free of PCB GND and connected only to the brick secondary return. Ag105 VBat- (pins
14/15) stays on PCB GND, which is also pack negative.

With this change the Ag105 sees the topology of its own datasheet (DS V1.1 Fig. 1 p.3, Fig. 4 p.7). The only DC return
from the module output to the module input is GND to VBat- to the internal sense to Vin-. The internal sense therefore
measures every ampere that the module delivers, and its constant-current limit, its over-current trip and its battery
detection act again. The 2026-11-04 circulating loop (ML0227) can still form electrically, but its current is bounded by
the Ag105 set current and, independently, by the brick output over-load protection.

The dossier reaches the following conclusions. The detailed basis is in sections 4 to 6.

1. **No element is added to the pack path.** The pack, J-BT, J-BL, D-BT-SQ, the BQ29200, the V_batt divider, the
   INA253s and the LM1084 are untouched. The added conduction loss at the 16.46 A peak BT current is zero, and the
   Teensy supply is continuous in every state.
2. **HR4 (no runaway) is satisfied by calculation**, conditional on bench proof that the sense is restored (BG-1) and
   that no second DC path joins Vin- to GND (BG-2). Two independent current ceilings exist: the Ag105 constant-current
   loop on its total output, and the brick over-load protection at 150 % of 2.0 A typical (maximum not published). Round 1: the brick limit is typical only; the ceiling is now the F2 eFuse, section 4.10.
3. **HR5 (fail-safe inhibit) is met by the design, subject to bench timing.** The brick runs only while the Teensy
   toggles pin 33 in its main loop. A static pin, a hung loop, a reset or a lost 3V3 rail switches the brick off within
   30-44 ms by calculation (round 1: 40-74 ms). The brick enable is a second, independent inhibit in series with the existing RT1987 path
   switches (round 1: only outside a charge period, section 3.6).
4. **HR3 (no circular loop) depends on an operator ruling.** In the strict operating mode (Mode S) the pack is off the
   bus during charging except for hardware-bounded purge bridges of at most 0.34-0.68 s (round 1: 0.32-1.02 s, BENCH), which meets the HR3 pass
   condition literally. In the circulation-accepted mode (Mode C) BT_BUS stays closed, purges are harmless and the
   charger stays warm, but a bounded circulating current exists for the whole charge period. Mode C fails the literal
   HR3 text (round 1: fails by construction; Mode S is standstill only, section 6).
5. **HR1 (regen) is UNDETERMINED and fails for a cold charger.** A cold start needs the brick start-up (30 ms) plus an
   Ag105 Bring-Up of about 9 s (BENCH figure). Regen is captured only while the charger is already running, that is in
   Mode C or inside a Mode S window, and only up to the Ag105 set power.
6. **HR2 (FC charging) is UNDETERMINED.** Mode S fits the FC budget only at standstill and only with predicted purges,
   as in the prior study. Mode C removes the purge blocker at the cost of the HR3 ruling.

The concept also has two costs that the brief anticipated. The pin-4 cut is effectively irreversible. Charge
termination (10 % of the set current) cannot trigger while the VBT logic load exceeds the cut-off current, so firmware
must terminate the charge.

## 1. Topology

### 1.1 Changes to the board

IC5 changes three things on the manufactured board and adds one off-board carrier.

1. The Ag105 Vin+ pin (pin 10; PCB pad VIN+ at (46.0, 61.94), facts_board section 4.1) is cut between the module body
   and the PCB. The PCB pad stays on `VCHG-IN`; the module-side stub receives a flying lead from the brick positive
   output through eFuse F2. (Round 0 cut the traces at the pad instead; round 1 cuts the pin, finding E-m4.)
2. The Ag105 Vin- pin (pin 4, pad VIN- at (46.0, 46.70)) is cut between the module body and the PCB. The pad is solid
   to both GND pours with no thermal relief (facts_board section 4.3), so a trace cut cannot isolate it. The PCB-side
   stub is trimmed flush. The brick secondary return lands on the isolated VLOAD-1 pad (pin 16, "internally connected
   to Vin-", DS Table 2 p.4), not on the pin-4 stub (finding E-m3).
3. LD (pin 20, isolated LDIS pad) is bridged to the VLOAD-2 pad, which disables the Ag105 load output (finding E-M4).
4. Five spare Teensy pins, the pin-28 and pin-41 nets and the 5 V rail are tapped at the J1/J2 receptacles (section
   3.1).
5. An off-board carrier holds the brick, its input fuse F1, the secondary eFuse F2, the pump driver, the enable chain,
   the overlap limiter and the V_brick divider. A 470 uF capacitor sits at the Ag105 input on the secondary side.

Figure 1 below is the round-0 drawing. In round 1, F2 sits in series with the +Vout lead, the -Vout lead lands on
VLOAD-1, and the Mode C feed is through REGEN only (Table 4).

### 1.2 Power topology

Figure 1 shows the power topology after the rework. The new parts are BR1 (brick), F1 (input fuse) and Q_EN (enable
switch). Every RT1987 switch keeps its existing net, Teensy pin and default state.

```
 Figure 1. IC5 power topology (new parts marked *)

                         FC_CHARGE_ENABLE (31)
   VBUS ─────────────────[D-BC-FC RT1987]──────────┐
                                                   │
   VBUS ─[D-MT-EN, MOT_PWR (29)]─ V-MOT ─[D-BC-RG, REGEN (30)]─┤
                                                   │
                                     VCHG-IN ──────┴── C-D8, C-D10 (20 uF), R1-CHG/R2-CHG -> pin 38
                                        │
                                     *F1 (fuse)
                                        │
                              +Vin ┌────┴──────────────────┐ +Vout
                                   │ *BR1 RP30-2415SFW/N    │───────────────────► Ag105 pin 10 Vin+
                                   │  9-36 V in, 15 V out   │                     (pad, VCHG-IN traces cut)
   PCB GND ─────────────── -Vin ───│  1.6 kVDC isolation    │ -Vout
                                   │ CTRL ◄── *Q_EN (D)     │───────────────────► Ag105 pin 4 Vin- (pin cut
                                   └────────────────────────┘                     above PCB; node N_VINM)
                 *Q_EN source ── -Vin (= PCB GND)

   Inside the Ag105 (DS V1.1 Fig. 1 p.3):  N_VINM ──[internal sense R_s]── VBat- (pins 14, 15)
                                           N_VINM ── VLoad- (pins 16, 17; pads unconnected)

   Ag105 VBat- (14, 15) ── PCB GND pour ══ J-BT pin 2 ══ J-BL pin 3 ══ pack negative      (unchanged)
   Ag105 VBat+ (18, 19) ── VCHG ──[D-BT-SQ RT1987, BT_SEQ (32)]── VBT ══ J-BT pin 1 ══ pack positive
                                                                  │
                                                                  ├── REG-BT (TPS61288) ── VOUT-BT ── SNS-BT ──[D-BT-EN, BT_BUS (28)]── VBUS
                                                                  ├── REG-5V (LM1084) ── 5V ── Teensy VIN
                                                                  └── R1-BT/R2-BT -> pin 25 (V_batt)
```

### 1.3 The current loop that restores the sense

The Ag105 output current follows one closed path. It leaves BR1 +Vout, passes through the Ag105 converter to VBat+,
then through VCHG, D-BT-SQ and VBT into the pack and the VBT loads (REG-BT, REG-5V, R1-BT). It returns through the PCB
GND pour to VBat-, passes the internal sense R_s to node N_VINM, and leaves through Vin- to BR1 -Vout. BR1 is
galvanically isolated (1.6 kVDC, 1 GOhm minimum, 1500 pF maximum; RECOM RP30-FW datasheet REV 3/2019, p.PD-4). There
is therefore no DC path from PCB GND to N_VINM except through R_s.

This arrangement is electrically the datasheet topology. In DS V1.1 Fig. 4 (p.7) the input supply return is the
module ground and the battery negative is a separate node behind the sense. In IC5 the input supply floats, so the
module cannot distinguish "PCB GND = pack negative" from "Vin- = system ground"; only potentials between its own pins
matter. The DS rule "VBat- must NOT be connected directly to the GND pin" (Table 2 p.4) is satisfied, because the
module GND pin is Vin- and Vin- is no longer on PCB GND.

### 1.4 Every signal and auxiliary connection to the floating node

The following connections join the module to PCB-GND-referenced circuits. Each was checked for a DC path that would
bypass R_s. A path that carries current through module internals to N_VINM returns to GND only through R_s, so it is
counted by the sense and does not bypass it. A bypass exists only if a low-impedance conductor joins N_VINM (or BR1
-Vout) to PCB GND.

| Connection | Net | Path to N_VINM | Effect |
|---|---|---|---|
| SDA, SCL (pins 8, 7) | 10 kOhm pull-ups to Teensy 3V3 (RSDA, RSCL) | Module I/O to its internal ground | At most 0.33 mA per line through R_s; logic levels offset by I x R_s (UNCONFIRMED size, BG-1) |
| MPPTD (pin 11) | Teensy pin 5, push-pull | Module input | Microamp-to-milliamp current; LOW = PCB GND = N_VINM + I x R_s |
| STAT (pin 3) | Teensy pin 6 | Internal 20 kOhm series output (DS p.10 Fig. 6a) | Negligible current |
| THERM (pin 13) | J-NTC pin 1; J-NTC pin 2 on PCB GND | Through the NTC, if fitted, to PCB GND | High impedance (10 kOhm NTC); temperature reading offset by I x R_s (UNCONFIRMED) |
| VLoad- (16, 17), LD (20) | Round 1: VLOAD-1 carries the brick return; LD bridged to VLOAD-2 | They are N_VINM | Never to PCB GND |
| VS, CS, MPPTS | No copper | None | Must stay unconnected; a resistor from VS/CS/MPPTS to "Vin-" must go to N_VINM, never to GND |
| V_brick divider (new, section 2.5) | BR1 +Vout to PCB GND | Load on BR1, returns through R_s | 0.14 mA counted as output current; not a bypass |
| BR1 Y-capacitance | 1500 pF maximum, primary to secondary | AC only | Common-mode current through R_s at the 387-473 kHz switching frequency; noise on reg 0x06 (BG-11) |

The table shows one hazard class: any DC conductor from BR1 -Vout, the pin-4 stub or VLoad- to PCB GND. Examples are a
scope ground clip, a solder splash, a chafed lead, a non-isolated substitute converter, or a future bodge that adds an
MPPTS resistor "to GND". Section 5 treats this as fault F7.

## 2. Selected parts, gate drive and fail-safe defaults

### 2.1 Brick: RECOM RP30-2415SFW/N

Table 1 lists the brick parameters that the design uses. All values are from the RECOM RP30-FW datasheet, REV 3/2019,
pages PD-1 to PD-7 (recom-power.com/pdf/Powerline_DC-DC/RP30-FW.pdf, read 2026-11-07).

Table 1. RP30-2415SFW/N parameters.

| Parameter | Value | Source page |
|---|---|---|
| Input range | 9-36 VDC (24 V nominal family) | PD-1 selection guide, PD-2 |
| Input surge | 50 VDC, 100 ms maximum | PD-2 |
| UVLO | DC-DC ON 9 VDC, DC-DC OFF 8 VDC | PD-2 |
| Output | 15 VDC, 2000 mA, 30 W | PD-1 |
| Efficiency | 89 % typical (nominal input, full load) | PD-1 |
| Input current | 1404 mA maximum at nominal input, full load | PD-1 (note 1) |
| Maximum capacitive load | 2000 uF | PD-1 |
| Start-up time | 30 ms (power up), 30 ms (ON/OFF CTRL) | PD-2 |
| CTRL, negative logic ("/N") | ON: short or 0 < V_CTRL < 1.2 V; OFF: open or 3.0 < V_CTRL < 12 V; referenced to -Vin | PD-1 note 3, PD-2 note 6 |
| CTRL pin current | -0.5 mA to +0.5 mA (DC-DC ON) | PD-2 |
| Standby input current | 3 mA (DC-DC OFF) | PD-2 |
| Output accuracy / trim | +/-1.0 % maximum / -10 % to +10 % | PD-2, PD-4 |
| OVP | Zener clamp, 18 VDC for the 15 V output | PD-4 |
| Over-load protection | 150 % of rated Iout, typical (no maximum given) | PD-4 |
| Short-circuit protection | Continuous, automatic recovery | PD-4 |
| Over-temperature protection | 115 C typical | PD-4 |
| Isolation | 1.6 kVDC / 1 min; 1 GOhm minimum at 500 VDC; 1500 pF maximum | PD-4 |
| Fusing | "Not internally fused. An input line fuse must always be used" (note 8) | PD-4 |
| Operating temperature | -40 to +62 C without derating | PD-5 |
| Size, mass | 50.8 x 25.4 x 10.2 mm, 30.5 g | PD-6 |
| Pins | 1 +Vin, 2 -Vin, 3 CTRL, 4 +Vout, 5 -Vout, 6 Trim | PD-7 |

The 15 V output was chosen over 24 V for three reasons:

- The 18 V output clamp stays far below the Ag105 absolute maximum of 36 V (DS p.19). A 24 V brick of the alternative
  family (Same Sky PYBE30, datasheet rev 1.13, 11/10/2023, p.3) specifies OVP at 110-160 % of output, which reaches
  38.4 V and exceeds 36 V.
- 15 V is 4 V above the Ag105 input UVLO of 11 V typical (DS p.19).
- A 15 V output is below the Ag105 default MPPT threshold of 18 V (DS p.10). An Ag105 that loses its EPROM settings
  therefore does not charge. This fails in the safe direction (section 6, HR5).

The consequence of the 15 V choice is that reg 0x02 must hold a threshold below 15 V. The present EPROM value is
12.85 V on the incident board (facts_prior section 4.2), and fw v24 writes counts 15-27 (12.320-13.376 V, CLAUDE.md
section 3). A single write of count 27 is sufficient (section 8).

The negative-logic variant is the fail-safe choice: an open CTRL pin means OFF. The positive-logic variant (no suffix)
turns ON with CTRL open (PD-2), so a broken enable wire would enable the brick. Section 2.6 gives the inverting stage
that is required if only the positive-logic part can be obtained.

Availability is not confirmed. An aggregator snapshot on 2026-11-07 showed the DigiKey US listing of RP30-2415SFW/N
out of stock with a 10-week lead time at about USD 96, and Mouser stock of the positive-logic RP30-2415SFW at about
USD 91 (findchips.com search results; TODO(verify: distributor live page)). H11 is therefore OPEN for this part.

### 2.2 Input fuse F1

RECOM note 8 (PD-4) requires an input line fuse. F1 protects the bus against a brick input short, which is otherwise
limited only by the boosts, because the RT1987 short-circuit protection is disabled after tON (RT1987 DS-00 section
17.5, via facts_prior section 5). F1 is not part of any interlock.

The fuse requirement is the following. The operating input current at the selected charge setting is 0.84 A at
16.0 V and 1.12 A at 12 V (section 4.1). At the brick over-load point (3 A output, 150 % typical), the input current
is about 15 x 3.0 / 0.89 / 12 = 4.2 A at 12 V. F1 is therefore specified as a 2.5 A time-lag fuse, at least 32 VDC
rated, with a breaking capacity at least the prospective bus fault current. The part number is TODO(verify: fuse
datasheet), and the prospective fault current is BENCH. A 2.5 A fuse does not clear an over-load hiccup of the brick;
the brick protects itself in that case (PD-4). **F1 does not protect against a sense bypass (fault F7):** the F7 input
current is about 45 / 0.89 / 16 = 3.2 A, 128 % of the F1 rating, which a time-lag fuse can carry for minutes (round 1,
finding E-M1). Section 2.2a gives the F7 ceiling.

### 2.2a Secondary eFuse F2 (round 1; HR4 ceiling by specified maximum)

A TI TPS259474L eFuse (SLVSFC9C, October 2020, revised May 2026) is inserted in the brick +Vout lead, between BR1 +Vout
and the Ag105 Vin+ pin. Its GND pin connects to N_VINM (the brick -Vout node), never to PCB GND. The device data that
the design uses are the following:

- Input range 2.7-23 V (section 6.3, Recommended Operating Conditions); the brick output of 15 V and its 18 V clamp (PD-4) are inside it.
- Adjustable threshold ILIM 0.5-6 A with +/-10 % accuracy for ILIM above 1 A (p.1 Features). RILM = 3.32 kOhm gives
  1.150 A (section 6.5, Overcurrent Threshold row), so the maximum is 1.265 A.
- The "4L" variant has a circuit-breaker overcurrent response with latch-off (section 4, Device Comparison Table). The
  latch clears when VIN falls to 0 V (section 7.3.9), which happens at every brick-off.
- Circuit-breaker operation allows peaks up to 2 x ILIM for the ITIMER interval (p.1 Features); C_ITIMER is
  TODO(calibrate) and is set to cover the Ag105 input-capacitor charge only.

With F2 fitted, every DC path that the module output can drive returns through F2, because F2 sits in the brick
output loop. The Ag105 input power is at most 15.15 V (brick +1 %, PD-2) x 1.265 A = 19.2 W. Because the module
efficiency cannot exceed 1, its output into VBT is at most 19.2 / 7.4 V = **2.59 A** at the 7.4 V pack floor
(`LIMIT_V_BATT_MIN`). This bound holds for F7, F15, F18, F19 (brick isolation breakdown) and the chafed +Vout lead,
and it uses no typical value. The bound is above the Ag105 set current at code 5 (1.25 A) and the pack maximum charge
current is unknown (BG-15), so HR4 "no runaway" holds but the pack rating is a separate gate. ILIM must be re-set if
code 3 is selected (1.11 A brick output exceeds the 1.035 A ILIM minimum): RILM for that case is TODO(calibrate:
SLVSFC9C section 7.3.5.2).

### 2.3 Enable chain (dynamic enable with integrated hang detection)

The brick is enabled only while the Teensy toggles pin 33 (`BRICK_PUMP`). A diode charge pump converts the toggling
into a DC level; a static pin at either level gives no DC level. A Schmitt buffer then drives the CTRL switch. Three
pull-down transistors on the hold node can force the brick OFF: a firmware kill line, the overlap limiter and,
optionally, the BQ29200 over-voltage output.

```
 Figure 2. Enable chain (all parts on the off-board carrier; supply 3V3 from J2 05/06, GND from J2 03/04)

 pin 33 ──R1 1k──┤├──C1 220 nF (C0G)──A──D2 BAT54 ►──H──┬───────┬──────┬──────┬──────┬─────► U1 SN74LVC1G17 in
                                     │                  │       │      │      │      │      U1 out = EN_LOGIC
                              D1 BAT54 (anode GND,      C2      R2     Q_KILL Q_OVL  Q_OVP     │
                              cathode A)                470 nF  100k   (D)    (D)    (D)      ├─R7 100 Ohm─► Q_EN gate
                                                        to GND  to GND  S=GND  S=GND  S=GND   │             (R8 100k to GND)
                                                                                              └─R9 10k────► pin 34 (readback)
 Q_EN = BSS138: drain -> BR1 CTRL, source -> BR1 -Vin (PCB GND)

 pin 35 (BRICK_KILL) ──R10 1k──► Q_KILL gate (R11 100k to GND)
 BQ29200 OUT (pin 8, net BAL-NOK) ──R12 1k──► Q_OVP gate (R13 1M to GND)          [MANDATORY after round 1]
 OVL (from the limiter, Figure 3) ───────────► Q_OVL gate (R14 100k to GND)
```

**Round-1 values (findings E-M3, F-m4).** C1 is 1 uF C0G (at least 25 V; part TODO(verify: capacitor datasheet)),
R2 is 47 kOhm and C2 is 1 uF, so R2 C2 stays 47 ms. Section 3.2 gives the recomputed timing. Q_OVP is mandatory. The
BQ29200 OUT drives at least 1.75 V (VDD = VPROTECT) and 6 / 8.25 / 9.5 V min/typ/max (VDD = 10 V) in an overvoltage
condition, and at most 200 mV at IOL 100 uA otherwise (SLUSA52C, section 7.5, OUT pin drive voltage rows). With
R12 1 kOhm and R13 1 MOhm the gate sees at least 1.75 V x 1000/1001 = 1.75 V, above the 1.5 V BSS138 VGS(th) maximum
at 1 mA. The margin at the VDD = VPROTECT row is 0.25 V, so Q_OVP actuation is bench gate BG-17. The 200 mV low level
stays below the 0.8 V VGS(th) minimum.

Table 2 lists the parts and the ratings that the chain depends on.

Table 2. Enable-chain parts.

| Ref | Part | Rating used | Source |
|---|---|---|---|
| Q_EN, Q_KILL, Q_OVL, Q_OVP | onsemi BSS138 (SOT-23) | VDSS 50 V; VGS +/-20 V; ID 0.22 A; VGS(th) 0.8 / 1.3 / 1.5 V min/typ/max at 1 mA; RDS(on) 6.0 Ohm max at VGS 4.5 V | onsemi BSS138/D, Rev. 7, April 2024, p.1-2 |
| D1, D2 | onsemi BAT54 | VR 30 V; IF 200 mA; VF 0.22 / 0.24 V (typ/max) at 0.1 mA, 0.29 / 0.32 V at 1.0 mA, 0.35 / 0.40 V at 10 mA; IR 0.2 / 2.0 uA at VR 25 V, 25 C (corrected in round 1, finding E-M3) | onsemi BAT54LT1/D, Rev. 18, November 2024, p.1-2 |
| U1 (and U3 in Figure 3) | TI SN74LVC1G17 Schmitt buffer | VCC 1.65-5.5 V; at VCC = 3 V: VT+ 1.48-1.92 V, VT- 0.89-1.20 V, hysteresis 0.51-0.83 V; at 4.5 V: VT+ 2.19-2.74 V, VT- 1.51-1.97 V; Ioff partial power-down | TI SCES351Y (rev. Oct 2025), Table 5-1, p.6 |
| C1 | 220 nF C0G/NP0, at least 25 V | Coupling capacitor (a C0G part fails open more often than shorted; section 5 F12) | TODO(verify: capacitor datasheet) |

**Operation.** Each falling edge of pin 33 pulls node A to about -0.24 V through D1; each rising edge lifts A by the
pin swing and charges the hold node H through D2. With pin 33 static, C1 blocks DC, D1 clamps A to ground and R2
discharges H. Pin 33 high-Z (reset, brownout) behaves as static.

**Defaults (Teensy unpowered, in reset, hung, or pin static).** H decays through R2 to 0 V, U1 output is LOW, Q_EN is
OFF (R8 holds its gate low), CTRL is open and the negative-logic brick is OFF. If the 3V3 rail is lost, U1 output is 0 V
(Ioff part) and the same holds. Q_KILL, Q_OVL and Q_OVP default OFF through their gate pull-downs (R11, R14 100 kOhm;
R13 1 MOhm), which is the non-inhibiting state; their failure to pull down is covered by the primary default (no
pump, no enable).

**Pump driver (round 1, finding E-M3).** Pin 33 does not drive C1 directly. A 5 V-supplied buffer with TTL-level
inputs (candidate TI SN74AHCT1G125; levels and drive TODO(verify: TI AHCT1G125 datasheet)) translates pin 33 to a 5 V
swing, and R1 is 470 Ohm. The 5 V rail is the LM1084 output (REG-5V), tapped at the Teensy VIN header contact
(TODO(verify: facts_board section 7.2)). The reason is the U1 input leakage: SN74LVC1G17 II is +/-5 uA maximum on the
A input (SCES351Y, July 2001, revised October 2025, section 5.5 DC table), which is +/-0.235 V on the 47 kOhm hold node
and leaves no ON margin with a 3.3 V pump (section 3.2). U1 tolerates the higher hold voltage, because its inputs are
rated to 5.5 V (same table, Ioff row). A lost 5 V rail or a static buffer output stops the pump, so the driver adds no
enable path.

### 2.4 Overlap limiter (hardware HR3 bound for Mode S; redesigned in round 1)

The limiter forces the brick OFF if the brick enable coincides with BT-to-bus **conduction** for longer than the purge
bridge needs. Conduction is detected two ways: the pin-28 command (P28), or a BT boost output current above 0.2 A on
the SNS-BT INA253 output (net `BT_CURRENT`, Teensy pin 41). The current path catches a shorted D-BT-EN (fault F20),
which the command path cannot see (finding F-M2). The limiter latches while conduction persists and releases after
it ends. It is fitted for Mode S and omitted for Mode C.

```
 Figure 3. Overlap limiter, round-1 revision (no diodes; all logic SN74LVC family at 3V3)

 BT_CURRENT (pin-41 net) ──► CMP+ ; CMP- ◄── 20 mV reference (3V3 divider)      CMP out = C_BT
 P28 ─────┐
          U2b OR ── P_COND                    EN_LOGIC ─┐
 C_BT ────┘                                             U2a OR ── E_OR
                                              OVL ──────┘
 E_OR ───┐
         U4 AND ──R15 47k──┬── T ──► U3 SN74LVC1G17 in;  U3 out = OVL ──► Q_OVL gate (Figure 2)
 P_COND ─┘                 │                                   └─R17 10k──► pin 17 (readback)
                           └── C3 15 uF to GND
 U2 = SN74LVC2G32 dual OR; U4 = SN74LVC1G08 AND; CMP = push-pull comparator, part TODO(verify: TI TLV7011 datasheet).
 P28 = Teensy pin-28 net (D-BT-EN), tapped at J1 39/40, with a 100 kOhm pull-down on the carrier (finding F-m3).
```

The INA253A1 gain is 0.1 V/A (BOM line 14; CLAUDE.md section 5), so 0.2 A is 20 mV. The input-referred offset is
+/-15 mA maximum (INA253 datasheet, Electrical Characteristics, IOS row), which is 7.5 % of the threshold. The
comparator offset and input bias are TODO(verify: comparator datasheet). The literature numbers for SN74LVC2G32 and
SN74LVC1G08 are TODO(verify: TI datasheets); the VOH used in section 3.3 is the LVC-family value VCC - 0.1 V at
IOH = -100 uA, read from SCES351Y section 5.5 for the SN74LVC1G17 and assumed for the gates (UNCONFIRMED). The gate
inputs have Ioff, so they do not load the pin-28 net when the carrier is unpowered (UNCONFIRMED until the gate
datasheets are read).

### 2.5 V_brick divider

A 100 kOhm / 10 kOhm divider from BR1 +Vout to PCB GND feeds pin 16 (analog) through a 10 kOhm series resistor and a
clamp to 3V3 (finding F-m1). The gain is 11, so the full scale is 3.3 x 11 = 36.3 V and one 12-bit count is 8.9 mV.
The divider current, 15 / 110 kOhm = 0.14 mA, returns through R_s and is counted as output current (section 1.4). The
reading equals the brick output minus I x R_s. With the Teensy unpowered, 100 kOhm limits back-feed into pin 16 to
14 uA. If the 100 kOhm leg shorts, the series resistor limits the clamp current to (15 - 3.3) / 10 kOhm = 1.2 mA. The
clamp part and its level against the i.MX RT1062 pin absolute maximum are TODO(verify: NXP IMXRT1060CEC).

### 2.6 Fallback for a positive-logic brick (UNCONFIRMED circuit, not preferred)

If only RP30-2415SFW (positive logic, open = ON, PD-2) is available, Q_EN is replaced by an inverting pair. Q_OFF
(BSS138) pulls CTRL to -Vin and is held ON by a gate pull-up from `VCHG-IN` (100 kOhm with a 12 V zener clamp to keep
VGS under the 20 V maximum). Q_INV (BSS138, gate = EN_LOGIC) pulls the Q_OFF gate low to enable the brick. The brick
is then OFF whenever it has input and EN_LOGIC is low. The zener part and its tolerance are TODO(verify: zener
datasheet); the local `BZT52C_Diodes.pdf` table did not extract cleanly. The inverting pair adds one single-point
failure (Q_OFF open = brick ON when commanded by nothing but input power), so the negative-logic part is preferred.

## 3. Teensy pins and control sequences

### 3.1 New pin assignments

Table 3 lists the new pins. All are spare on the CSV (facts_board section 7.2). The CSV must be amended first, as the
project rule requires. Pins 2, 7 and 8 are not used (facts_board section 7.2).

Table 3. New Teensy pins.

| Pin | Header contacts | Proposed code name | Dir | Function | Default without firmware |
|---|---|---|---|---|---|
| 33 | J2 47/48 | `BRICK_PUMP` | OUT | Toggled once per main-loop iteration while charging is permitted | Static, so brick OFF |
| 34 | J2 45/46 | `BRICK_EN_SENSE` | IN | EN_LOGIC readback (pump and Schmitt health) | - |
| 35 | J2 43/44 | `BRICK_KILL` | OUT | Active HIGH; discharges H through Q_KILL | Low through R11 (not inhibiting; primary default holds) |
| 16 | J2 21/22 | `BRICK_VOLTAGE` | AIN | V_brick, gain 11 | - |
| 17 | J2 19/20 | `BRICK_OVL_SENSE` | IN | Overlap-limiter trip readback | - |
| (28) | J1 39/40 | existing `BT_BUS_ENABLE` | tap | Limiter input only; no new driver | - |
| (41) | TODO(verify: facts_board section 7.2) | existing `BT_CURRENT` | tap | Limiter conduction comparator (round 1) | - |
| (VIN) | TODO(verify: facts_board section 7.2) | 5 V rail | tap | Pump driver supply (round 1) | - |

### 3.2 Pump timing (calculated, round-1 values; bench gate BG-4)

The firmware toggles pin 33 once per iteration, so the pump frequency is half the loop rate. With the measured median
iteration of 1131 us (facts_firmware section 8), f = 442 Hz. The pump driver swings to about 4.9 V (TODO(verify: AHCT
VOH)). The peak drive at C1 is 4.9 - 2 x 0.32 = 4.26 V, with the BAT54 VF maximum at 1 mA (BAT54LT1/D Rev. 18, p.2;
round 0 used the 0.1 mA row, finding E-M3). With R1 C1 = 0.47 ms and a half period of 1.13 ms, the per-edge transfer
is 1 - exp(-1.13/0.47) = 0.91. The steady hold voltage is

  V_H = 4.26 x 0.91 x k / (1 + k), with k = f x C1 x R2 = 442 x 1e-6 x 47e3 = 20.8, so V_H = 3.70 V.

The U1 leakage of +/-5 uA moves H by +/-0.235 V (section 2.3), so V_H lies between 3.47 V and 3.94 V. U1 at VCC = 3.3 V
has VT+ between the 3.0 V and 4.5 V table rows. Linear interpolation gives VT+ at most 2.08 V and VT- between 1.01 V
and 1.35 V (UNCONFIRMED interpolation; the 3.0 V row gives VT+ at most 1.92 V). The ON margin is therefore at least
3.47 - 2.08 = 1.39 V.

- **Minimum loop rate.** The brick enables reliably only while V_H - 0.235 V exceeds 2.08 V. This needs k of at least
  1.48, that is a pump frequency of at least 32 Hz, or a mean iteration of at most 16 ms. Firmware checks the measured
  loop rate against this minimum while charging (section 8 item 3).
- **Hang to brick-off.** With R2 C2 = 47 ms and the leakage as an offset of +/-0.235 V, H falls to VT- in
  47 x ln(3.705/1.585) = 40 ms (fastest) to 47 x ln(3.705/0.775) = 74 ms (slowest). The brick CTRL-to-output-off latency
  is not specified by RECOM (BG-5). Round 0 gave 30-44 ms; that range used the wrong VF row and omitted the leakage.
- **Loop jitter tolerance.** The worst measured gap of 9.76 ms (facts_firmware section 8) lowers H in the worst case to
  -0.235 + 3.705 x exp(-9.76/47) = 2.77 V, which stays above VT- maximum (1.35 V). Normal jitter does not drop the brick.
- **Blocking calls drop the brick.** Any call that blocks the loop for more than about 40 ms switches the brick OFF:
  the EEPROM commit (up to about 1.2 s, facts_prior section 10 item 7), SD init and close, `Ethernet.begin()` with no
  link, and a Wire transaction stalled on a module that loses power mid-transfer (finding S-m2). This is the intended
  fail-safe behaviour; the cost is an Ag105 restart (section 4.4). Firmware lists and guards these calls (section 8).
- **Toggle context (finding F-m6).** Pin 33 must be toggled only from `loop()` context. A toggle from an IntervalTimer
  or an ISR keeps pumping while the main loop is hung and defeats the hang detection. This is a firmware rule with a
  host test (section 8 item 12).
- **Commanded fast off.** Q_KILL discharges C2 through its RDS(on). RDS(on) at VGS = 3.3 V is not specified (6.0 Ohm
  maximum at 4.5 V); at 50 Ohm the time constant is 24 us, so EN_LOGIC falls within 0.1 ms (UNCONFIRMED).

### 3.3 Limiter timing (calculated, round-1 values; BENCH, gate BG-4)

The round-0 limiter (1 MOhm and 4.7 MOhm on the timing node, BAT54 steering diodes) did not meet its timing over the
datasheet leakage: U3 II of +/-5 uA on a 0.82 MOhm node is +/-4.1 V, larger than the whole threshold window (finding
E-M2). The round-1 limiter has a 47 kOhm source impedance and no diodes. With U4 high, T charges toward
V_OH = 3.2 V (VCC - 0.1 V) with tau = R15 C3 = 0.705 s, and the U3 leakage moves the end point by +/-0.235 V. U3 trips at
VT+ (1.48-2.08 V), after

  t_ovl = 0.705 x ln(3.435 / (3.435 - 1.48)) = 0.40 s (fastest) to 0.705 x ln(2.965 / (2.965 - 2.08)) = 0.85 s (slowest).

C3 is a 15 uF X7R part whose tolerance and DC-bias derating are not yet sourced. At +/-20 % the range widens to about
0.32-1.02 s. The limiter timing is therefore BENCH, not PROVEN_CALC. After a trip, the OR of OVL into U2a holds U4 high
while conduction persists, so the trip latches. When P_COND falls, T discharges through R15 into the U4 low output
and the brick is held off for 0.705 x ln(3.2/1.585) = 0.50 s to 0.705 x ln(3.2/0.655) = 1.12 s. A normal purge bridge
of 0.21 s (section 3.5) charges T to at most 3.435 x (1 - exp(-0.21/0.564)) = 1.07 V at C3 -20 %, which is below VT+
minimum; the residue decays to below 0.01 V within the 10.34 s purge period.

### 3.4 Operating modes

IC5 can be operated in two modes. The mode is an operator ruling (section 9, Q1).

- **Mode S (strict).** BT_BUS is LOW whenever the brick runs, except for bounded purge bridges. The limiter enforces
  the bound in hardware. The FC carries traction, aux and the charger between purges.
- **Mode C (circulation accepted).** BT_BUS stays HIGH while the brick runs. The limiter is not fitted. The battery
  stays on the bus through purges and traction peaks, and the charger output partly circulates through the BT boost.

### 3.5 Sequences

Table 4 gives the switch sequence for each operating situation. "Pump ON" means the firmware toggles pin 33;
"Pump OFF" means pin 33 is driven LOW and static. The existing rules for MOT_PWR (Death-5 doctrine), the v38 regen
interlock and the share latch are unchanged unless stated.

Table 4. Control sequences.

| Situation | Sequence (in order) | Rationale |
|---|---|---|
| Boot (`setup()`) | 1. Pin 35 OUTPUT HIGH (kill asserted). 2. Pin 33 OUTPUT LOW. 3. Pins 34, 17 INPUT; pin 16 analog. 4. Existing early LOW writes of all RT1987 EN pins. | Brick OFF by three layers before any power path can close; the hardware default already holds it OFF |
| Boot self-test (during bring-up P0, `VCHG-IN` unpowered) | 0. Read V_chg (pin 38): it must be below 1.0 V, or the self-test is skipped and charging stays refused (finding F-m2: a stuck-ON D-BC-FC or D-BC-RG would power the charger). a. Release pin 35; toggle pin 33 for 20 ms: pin 34 must read HIGH. b. Stop toggling: pin 34 must read LOW within 90 ms. c. Hold pin 33 HIGH static for 200 ms: pin 34 must stay LOW (detects a shorted C1). d. Toggle with pin 35 HIGH: pin 34 must stay LOW. e. In P0, where BT_BUS is HIGH, toggle for 1.5 s: pin 17 must read HIGH and pin 34 LOW (limiter, Mode S only). f. Pin 35 HIGH, pin 33 LOW. Any failure sets a reboot-only `BRICK_SELFTEST` latch that refuses charging. | Proves every element of the inhibit chain without powering the charger; `VCHG-IN` is proven dark, so a toggled brick has no input |
| Idle (State 1) | Pump OFF, pin 35 HIGH, FC_CHARGE LOW, REGEN LOW. | No charging in Idle in this dossier (standstill charging in Idle is a possible extension, section 9 Q6) |
| Run, discharge (State 2, no charge intent) | Pump OFF, pin 35 HIGH, **FC_CHARGE LOW and REGEN LOW** (round 1, findings F-M4 / E-M5). | The RT1987 input switches stay a hardware inhibit in series with the brick enable; a single brick-enable fault (F4, F12) cannot make the bus feed the charger |
| Run, FC-charge window, Mode S (**standstill only**, round 1) | Preconditions: vehicle stopped (motor current command 0), RTWDOG (T-W-01) fitted and armed, purge prediction (T-E-01) passed, the battery-only selector arm and its re-arm held off. 1. FC_CHARGE HIGH with BT_BUS still HIGH, REGEN LOW (IO-CSV row 31 satisfied for REGEN) and the brick OFF. 2. Wait tD_ON 8 ms + ramp + 30 ms blanking. 3. Reserve the full brick draw (0.84 A at code 5) as FC headroom. 4. Pin 35 LOW, pump ON. 5. Wait 50 ms (brick start-up 30 ms + margin). 6. BT_BUS LOW. 7. Ag105 Bring-Up proceeds (about 9 s, BENCH); its unscheduled step to CC is already inside the reserved headroom. 8. Config writes per `pollAg105()` if not already in EPROM. | The `VCHG-IN` hot-plug happens with both sources on the bus; the 50 ms overlap is inside the 0.32 s limiter minimum. The reservation covers the Bring-Up-to-CC step that the Ag105 times itself (finding S-M5) |
| Run, charge period, Mode C | 1. With MOT_PWR HIGH (Death-5 rule), REGEN HIGH; **FC_CHARGE stays LOW** (round 1, finding F-M5). The brick input is then bus-fed through D-MT-EN, V-MOT and D-BC-RG. 2. Wait tD_ON 8 ms + ramp + 30 ms blanking. 3. Pin 35 LOW, pump ON. BT_BUS stays HIGH; the share loop holds an in-band two-source command; the battery-only arm and the selector re-arm are forbidden while the pump runs, and the command policy covers pump-off gaps below the 0.25 A selector gate (finding S-m5). 4. The pump gate (section 4.6) arms and releases on traction power and FC headroom, with hysteresis sized against the 9 s restart. | Uses only the REGEN path, so REGEN and FC_CHARGE are never HIGH together (IO-CSV row 31 and CLAUDE.md section 2 hold). Bounded circulation (section 4.6); fails HR3 by construction |
| Regen brake | Mode C: no switching; the brick is already fed from V-MOT through D-BC-RG, so a V-MOT rise is seen directly. D-MT-EN blocks V-MOT from back-feeding VBUS by its ideal-diode reverse blocking (RT1987 DS-00 section 17.6: fast reverse comparator, tFRC about 0.5 us typical at VFRC about -50 mV, typical values only); this dependency exists today on every regen event. Mode S: regen is not captured (standstill only). Cold charger: not captured (section 4.4). | The brick is a near-constant-power load, so a V-MOT rise does not change the Ag105 input |
| H-20 purge, Mode S | At predicted purge start minus 40 ms: BT_BUS HIGH (BT boost is already enabled). At purge end plus 30 ms: BT_BUS LOW. Total overlap about 0.21 s for a 140 ms purge. | Bounded pulse below the 0.32 s limiter minimum; the charger stays warm. An unpredicted purge collapses the bus (section 4.5) |
| H-20 purge, Mode C | No action. | The BT boost already shares the bus |
| Finish (State 3) | 1. Pin 35 HIGH, pump OFF. 2. Wait 5 ms. 3. FC_CHARGE LOW, REGEN LOW (existing). 4. BT_BUS restored by the existing guarded re-close. | The charger loses input before the input path opens, so no RT1987 opens under charger load |
| State 99 (Error), new phase 0 head | 1. If the latched error is charger-class (`OV_BRICK`, `BRICK_UNCOMMANDED`, `OV_BATT`, `BRICK_SELFTEST`, sense-bypass or limiter trip): pin 35 HIGH, pump OFF, first action. 2. Otherwise, if the brick is already running, keep the pump for the phase-0 and phase-1 drain windows (about 20 ms, bounded), then pin 35 HIGH. If the brick is OFF, it is not started; the drains then reach only C-D8/C-D10 and the brick input filter, and VBUS and V-MOT discharge through the bleed paths. 3. Existing phases 0-2. | The drain into the charger is kept where it is available; the back-feed ordering (CLAUDE.md section 2) with bleed-only discharge is bench gate BG-18 and operator ruling Q5 (finding S-M6) |
| Teensy reset / brownout / hang | No firmware action possible. Pin 33 goes high-Z or static; the brick falls OFF in 40-74 ms; the RT1987 EN pull-downs open the input paths on a reset or brownout. A hang leaves the input paths and BT_BUS at their last level but the brick OFF; in Mode S only RTWDOG restores the pack to the bus before the next purge. | Two independent inhibits in series outside a charge period; one (the brick) inside it |

### 3.6 Effect on operator ruling 3

Ruling 3 allows the bus to feed the charger only if the charger can be inhibited while powered, reliably, by the
Teensy and fail-safe (facts_prior section 3). The Ag105 itself has no such inhibit (facts_ag105 section 10). In IC5 the
brick enable removes the Ag105 input while `VCHG-IN` stays live; it is Teensy-commanded, defaults OFF and detects a
hung loop. IC5 therefore supplies the inhibit that the relaxation clause requires. Whether it is "reliable" in the
ruling's sense is a bench result (BG-4, BG-5). This is UNCONFIRMED until the operator rules on it.

Inside a charge period the bus feeds the charger by intent, and the brick is then the only hardware inhibit; REGEN (or
FC_CHARGE) is the second, firmware-opened layer. Outside a charge period both layers are open (Table 4, round 1). The
round-0 claim of "two independent inhibits in series" holds only outside a charge period.

**Regen discriminator (round 1, finding S-M1).** The brick holds the Ag105 input at a regulated 15 V whatever V-MOT
does. The reg 0x02 input-threshold mechanism (DS V1.1 p.10) can therefore no longer separate "regen present" from
"bus only", and the always-powered regen scheme accepted under ruling 3 does not carry over to IC5. The Ag105 has no
charge enable (facts_ag105 section 10) and VCHG decays behind D-BT-SQ in 0.17-0.78 s, so the charger is either cold
(about 9 s Bring-Up) or charging at CC from `VCHG-IN`. Warm regen capture in IC5 therefore requires continuous CC
charging from the bus for the whole of Run. Two warm-idle candidates are open and are bench gates (BG-19): the
ruling-9 keep-alive (1 kOhm VBT to VCHG, which joins two positive nodes and does not bypass the sense), and a fast
charge-start lever without EPROM writes (MPPTD with a reg 0x02 threshold above 15 V, gated on whether the threshold
still gates charge start while MPPTD is LOW, TODO(verify: Silvertel); or the brick Trim pin keyed to the brake command).

## 4. Quantitative checks

### 4.1 Power chain and the FC budget

Table 5 gives the power chain for three Ag105 current settings. The Ag105 efficiency of 0.88 is specified only at
12 V input, 3S, 25 C (DS p.20); the brick efficiency of 0.89 is specified only at 24 V input and full load (PD-1).
Both are therefore UNCONFIRMED at the operating point (15 V in, 2S; 16 V brick input at 40-80 % load) and are bench
gate BG-10. The Ag105 output power is taken at CV, 8.4 V.

Table 5. Power chain per Ag105 current code (reg 0x00, `Ag105_Table4_Charge_Current_Select.json`).

| Code | I_set | Cut-off (10 %) | Ag105 out | Brick out (A at 15 V) | Brick in | Bus current at 16.0 V | Bus current at 12 V |
|---|---|---|---|---|---|---|---|
| 6 | 1.00 A | 100 mA | 8.40 W | 9.55 W (0.64 A) | 10.73 W | 0.67 A | 0.89 A |
| 5 | 1.25 A | 125 mA | 10.50 W | 11.93 W (0.80 A) | 13.41 W | 0.84 A | 1.12 A |
| 3 | 1.75 A | 175 mA | 14.70 W | 16.70 W (1.11 A) | 18.77 W | 1.17 A | 1.56 A |
| 1 | 2.50 A | 250 mA | 21.00 W | 23.86 W (1.59 A) | 26.81 W | 1.68 A | 2.23 A |

The chain efficiency is 0.89 x 0.88 = 0.783, against 0.88 for the Ag105 alone. The brick costs about 1.5 W at code 5.

**Mode S budget.** The FC limits are the 1.25 A governor, the 1.247 A P_MAX and the 1.4 A single-sample OC_FC
(facts_prior section 7). At code 5 the headroom for aux (0.10-0.15 A) and traction is 1.25 - 0.84 - (0.10 to 0.15) =
0.26 to 0.31 A. Mode S charging is therefore standstill-weighted, as the prior study found for every charger (X5).
Code 6 gives 0.43-0.48 A. Code 1 (2.5 A) exceeds the governor and is excluded in Mode S.

**Recommended setting.** Code 5 is written once and left in EPROM, so no per-mode EPROM writes occur. Code 3 is the
smallest setting that covers the 18.9 W regen peak (section 4.4); it needs Mode C and the pack maximum charge current,
which is unknown (facts_prior section 9).

### 4.2 Conduction loss and SOA in the pack path

IC5 adds no element to the pack path, the BT boost input or the return. The added conduction loss at the 16.46 A peak
BT boost current (incident record, facts_prior section 9) is **0 W**. The only new series elements carry charger
current: F1 (at most 1.12 A at code 5) and the two flying leads (at most 0.80 A, 3 A at brick over-load). Q_EN and the
other BSS138s switch the CTRL pin (at most 0.5 mA at no more than 12 V, PD-2) or logic nodes, so their SOA is not a
constraint.

### 4.3 Inrush

1. **Input-path close onto `VCHG-IN` (brick OFF).** The switched capacitance is C-D8 + C-D10 = 20 uF plus the brick
   internal Pi-filter capacitance C_int. C_int is not published (PD-2 gives only "Pi-Type"); TODO(verify: RECOM) and
   BG-6. At 12 mA/uF (RT1987 with CSS 5.6 nF, facts_prior section 10 item 4) the inrush is 0.24 A + 12 mA/uF x C_int.
   The prior budget for a cold close from an FC-only bus is at most 1.0 A including 0.15 A aux, which allows C_int up to
   (0.85 / 0.012) - 20 = 51 uF. In the recommended sequence (Table 4) BT_BUS is still HIGH at this close, so the inrush
   is not drawn from an FC-only bus. No external input electrolytic is fitted; the RECOM EMC suggestion of 330 uF
   (PD-6 note 11) is omitted under the hot-plug rule.
2. **Brick enable.** The brick soft-starts in 30 ms (PD-2) into its own output capacitance and the Ag105 input
   capacitance (not published; TODO(verify: Silvertel)). The brick limits this current itself (over-load 150 %
   typical). The draw appears on a bus that both sources still supply.
3. **Ag105 output into VCHG.** The Ag105 ramps its own output (Bring-Up) and D-BT-SQ soft-starts; no step occurs.

### 4.4 Timing against the regen burst and the Ag105 Bring-Up

Table 6 compares the cold and warm paths against the regen facts (facts_prior section 6: first pulse 19-47 ms, burst
0.3-0.6 s, VESC stop at about 21.35 V).

Table 6. Regen timing.

| Path element | Cold charger | Warm charger (Mode C or inside a window) |
|---|---|---|
| Input path | REGEN tD_ON 8 ms + about 1.3 ms ramp (typical only) | Already closed |
| Brick | UVLO ON at 9 V, then start-up 30 ms (PD-2) | Already running |
| Ag105 | Start-up not published; Bring-Up from VCHG near 0 V to VBT at about 0.64 V/s: (7.8 - 2.0) / 0.64 = 9.1 s (BENCH figure from ML0227, taken with the sense shorted) | Already in CC; supply transfer by the RT1987 ideal diodes |
| Result | About 9 s against a 0.3-0.6 s burst: the burst is **not captured** | Captured up to the Ag105 input power |

**Warm capture estimate (UNCONFIRMED pulse shape).** At code 5 the charger draws 13.4 W. The 2 -> 1 m/s brake peaks
at 11.1 W, below the draw, so V-MOT need not rise toward the VESC cut-off; the energy into VBT is about
2.09 J x 0.783 = 1.64 J (against 1.81 J with the Ag105 alone, facts_prior section 6). The 3 -> 1 m/s brake peaks at
18.9 W over 0.58 s. For a triangular pulse, the energy above the 13.4 W draw is 0.5 x 0.58 x (18.9 - 13.4)^2 / 18.9 =
0.46 J. The V-MOT headroom from 16.0 V to 21.35 V is 0.5 x C x (21.35^2 - 16.0^2) = 0.097 J at 0.97 mF and 0.40 J at
4 mF. The excess exceeds both, so the VESC is expected to trip and the capture falls onto the 6-40 % cliff. Code 3
(18.8 W) would cover the peak.

**Ag105 restart cost.** VCHG sits behind D-BT-SQ, which blocks the pack, so after any input loss the module sees
VCHG decaying toward 0 V (0.17-0.78 s, facts_prior section 10 item 1) and performs Bring-Up again. Each brick power-up
therefore costs about 9 s before charge current flows (BENCH). Whether a short interruption (under about 0.2 s, while
VCHG is still near VBT) skips Bring-Up is not specified (BG-3). The ruling-9 keep-alive (1 kOhm VBT -> VCHG) would
remove the cost; it is a last resort and does not bypass the sense (it joins two positive nodes).

### 4.5 FC windows and purges

- **Mode S.** A 30 s window (`FC_CHG_MAX_MS`, facts_firmware section 3.2) yields at most about 21 s of charge after a
  9 s Bring-Up. Purge bridges keep the brick ON, so the window limit can be lengthened in IC5 (section 8 item 4).
- **Unpredicted purge in Mode S.** The bus capacitance implied by 2.57 V/ms at the aux load (0.15 A) is about 58 uF
  (UNCONFIRMED derivation). With the brick drawing 0.84 A as well, the bus falls at about 17 V/ms once the FC boost
  can no longer hold it, which is far faster than the 8 ms BT_BUS turn-on. The brick then stops at its 8 V UVLO, the
  Ag105 loses input and UV_BUS can latch. Mode S therefore depends on purge prediction (ruling 6, bench gate T-E-01),
  exactly as the prior study found. IC5 does not remove this blocker in Mode S. The brick is a constant-power load down
  to its 8 V UVLO (PD-2), so its current rises as the bus falls and the 17 V/ms figure is optimistic (finding S-m1).
- **Recovery after an unpredicted purge in Mode S (round 1, finding F-M3).** With MOT_PWR closed (Death-5 rule), the
  V-MOT node (470 uF + VESC) drains with VBUS. The recovery is either the FC boost restart at purge end or the BT_BUS
  re-close, both onto a drained V-MOT node. Whether either is a Death-5-class inrush is UNCONFIRMED. The same exposure
  exists today in every FC-charge window of fw v28 and later, in which BT_BUS is open (facts_firmware section 2), so it
  is not new to IC5; IC5 lengthens the exposure by keeping the window open longer. Round 1 therefore restricts Mode S to
  standstill (motor current command 0) and makes RTWDOG (T-W-01) and purge prediction (T-E-01) hard preconditions
  (Table 4). The drained-node recovery is bench gate BG-20. A Teensy hang inside a Mode S window leaves BT_BUS LOW; only
  RTWDOG restores the pack to the bus before the next purge.
- **Constant-power load on an FC-only bus (finding E-m6).** In Mode S the brick has a negative incremental input
  resistance on a drooped FC-only bus. Bus stability with the brick at code 5 plus the aux load is bench gate BG-21.
- **Mode C.** The BT boost already shares the bus, so a purge only moves load to the BT channel. The bus does not
  collapse and the charger stays warm. This is the only IC5 mode in which HR2 survives an unpredicted purge.

### 4.6 Circulation in Mode C

At standstill and code 5, the bus load is 0.84 A (brick) + 0.15 A (aux) = 0.99 A. At the in-band command 0.85 FC
share, the BT boost delivers 0.15 x 0.99 x 16.0 = 2.38 W and draws about 2.64 W from VBT (TPS61288 efficiency 0.90
assumed, UNCONFIRMED). The Ag105 puts 10.5 W into VBT and the LM1084 draws about 1.0-1.7 W (I_5V of 0.12-0.20 A is
BENCH). The pack therefore gains about 6.2-6.9 W while 2.64 W circulates. Producing the 2.64 W at VBT takes
2.64 / 0.783 = 3.37 W from the bus, and the BT boost returns 2.38 W of it. The circulation loss is therefore about
1.0 W, or 7 % of the 13.4 W charger input.

If the selector arms battery-only (share 0) while the brick runs, the BT boost carries the whole bus load (about
15.8 W) and the pack discharges at about 7 W while "charging". This is bounded but useless; firmware must prevent it
(Table 4).

**Pack net power under traction (round 1, finding S-M3).** Under the fw v26 governor the FC delivers at most about
20 W at the bus (1.25 A at 16.0 V), and the BT boost carries every watt above that cap. Table 5a gives the pack net
power at code 5 against traction power, with the same assumptions as above (TPS61288 efficiency 0.90 assumed, LM1084
1.0-1.7 W BENCH, share command 0.85).

Table 5a. Mode C pack net power at code 5 under the governor (UNCONFIRMED efficiencies).

| Traction at the bus | Bus load | BT boost output | VBT draw by the BT boost | Pack net power |
|---|---|---|---|---|
| 0 W | 15.8 W | 2.4 W (15 % share) | 2.6 W | +6.2 to +6.9 W |
| 10 W | 25.8 W | 5.8 W (above the cap) | 6.4 W | +2.4 to +3.1 W |
| 15 W | 30.8 W | 10.8 W | 12.0 W | -3.2 to -2.5 W |

The pack net power crosses zero at about 12.1-12.7 W of traction. Mode C therefore needs a firmware pump gate on
traction power and FC headroom. The gate releases the pump above about 8 W of filtered traction (TODO(calibrate)) and
re-arms below a lower threshold with a dwell sized against the 9 s Bring-Up penalty. Each release costs a warm charger,
so in Mode C regen capture is limited to braking that follows a low-traction interval.

### 4.7 Teensy supply continuity

The pack never leaves VBT in IC5. The LM1084 input stays on the pack in every state, and during charging the Ag105
also feeds VBT through D-BT-SQ. The Teensy supply is therefore continuous. Objection 2 of the re-spin note
(facts_prior section 8) does not apply.

### 4.8 Reference shifts

Table 7 lists the measurement references. The only node that moves is N_VINM, which sits below PCB GND by I x R_s.

Table 7. Reference shifts.

| Measurement | Reference after IC5 | Shift |
|---|---|---|
| V_batt (pin 25, R1-BT/R2-BT) | PCB GND = pack negative | None |
| I_fc, I_batt (INA253, REF1/REF2 on GND) | PCB GND | None |
| BQ29200 cell taps, GND, VDD | PCB GND and the balance lead | None; J-BL pin 3 stays on GND, which is now correct |
| V_chg (pin 38) | PCB GND | None, but it now measures the brick input, not the Ag105 input |
| Ag105 reg 0x05, 0x07 | Module's own pins | 0x07 now reads the brick output (15 V) |
| Ag105 STAT, MPPTD, I2C, THERM | N_VINM | Offset of I x R_s; R_s not published (BG-1). At 1.25 A and an assumed 40 mOhm, 50 mV (UNCONFIRMED) |
| Ag105 CV point | VBat+ to VBat- | VBat- sees the GND pour at the module pads; BT boost return current in the pour adds an error in Mode C (UNCONFIRMED; Mode S has little return current) |

### 4.9 Charge termination with the VBT load

The Ag105 terminates when the CV current falls to 10 % of the set current (DS p.5; Table 4 JSON). In IC5 the sense
measures pack current plus the VBT loads. The LM1084 draws I_5V plus a quiescent current of 5 mA typical and 10 mA
maximum (LM1084 SNVS037H, electrical characteristics and section 7). The Teensy, INA253s, MDACs and OPA197s give an
I_5V of about 0.12-0.20 A (BENCH). This exceeds the 125 mA cut-off at code 5, so the module is expected **never to
terminate**: the pack floats at CV (8.4 V at VCHG, minus the 35-50 mV D-BT-SQ drop). Floating a LiPo at 4.18 V/cell is
not a safety hazard, but the firmware must end the charge itself (section 8 item 5). In Mode C the BT boost load adds
to the same effect.

### 4.10 Independent current ceilings (HR4; revised in round 1)

1. **Ag105 constant-current loop**, on total output, once the sense is restored (DS p.5; BG-1).
2. **Ag105 over-current trip** at the set current + 200 mA (DS p.18), if it uses the same sense (TODO(verify:
   Silvertel)).
3. **Secondary eFuse F2 (TPS259474L)**, independent of the Ag105 and of the sense. Its ILIM is at most 1.265 A
   (SLVSFC9C p.1, +/-10 %), so the current into VBT is at most 2.59 A in every fault that bypasses the sense (F7, F15,
   F18, F19), with transient peaks up to 2 x ILIM for the ITIMER interval (section 2.2a). This is the HR4 ceiling for
   the fault case, and it uses no typical value.
4. **Brick over-load protection**, 150 % of 2.0 A **typical only** (PD-4; no maximum and no protection mode given). It
   is a backstop behind F2, not a ceiling the design relies on (finding F-M1, E-M1). With MPPT enabled, an over-loaded
   brick sags toward the reg 0x02 threshold, so this backstop is about I_OLP x 13.4 V, not x 15 V (finding E-m7).
5. **Firmware.** G1 and G2 run only inside the State-98 `J` session (`ag105CommissionTick()`, ino:9440, returns unless
   a session is active), and their 1.0 A threshold would trip on normal traction. They give no protection in Run as
   written (finding F-M1). Run-time equivalents need a redesign (section 8 item 13); until then they are not counted.
   The F1 input fuse is not an F7 protection (section 2.2).

## 5. Single-fault table

Table 8 lists single faults. "Bounded" means the current is limited by a named ceiling from section 4.10.

Table 8. Single faults.

| ID | Fault | Consequence | Detection / bound | Residual |
|---|---|---|---|---|
| F1 | Teensy main loop hangs | Pump stops; brick OFF in 40-74 ms. Input paths and BT_BUS stay at their last level | Hardware (brick); RTWDOG for the rest | Mode S: BT_BUS stays LOW into the next purge; RTWDOG (T-W-01) is a hard precondition of Mode S, not a residual |
| F2 | Teensy reset or brownout | Pins high-Z: brick OFF; RT1987 EN pull-downs open the paths | Hardware | OQ-7: which EN nets carry the 10 kOhm bodge |
| F3 | Firmware bug: pump ON with no charge intent, BT_BUS HIGH | Outside a charge period REGEN and FC_CHARGE are LOW, so the brick has no input; inside one, bounded circulation | Mode S: limiter trips in 0.32-1.02 s (BENCH); Mode C: none in hardware, bounded by the Ag105 CC and F2 | Mode C fails HR3 by construction |
| F4 | Q_EN drain-source short | Brick ON whenever `VCHG-IN` is live; outside a charge period `VCHG-IN` is dark (Table 4, round 1) | V_brick (pin 16) above 11 V without command: firmware opens FC_CHARGE and REGEN | Inside a charge period the brick enable is the only hardware layer |
| F5 | Q_EN open, U1 dead, C1 open, D2 open, pump driver dead, 5 V lost | Brick never ON | Self-test step a; no charge | None (safe) |
| F6 | Brick fails with output high | 18 V clamp (PD-4) below 36 V and below the 23 V F2 rating | V_brick high: firmware opens the input paths | Clamp rating under sustained fault TODO(verify: RECOM); firmware-dependent (finding F-m8) |
| F7 | DC path from N_VINM or BR1 -Vout to PCB GND (scope clip, solder splash, chafed lead, substitute non-isolated converter, MPPTS resistor to GND) | The sense is bypassed again (the ML0227 mechanism) | **Bounded at 2.59 A into VBT by F2 (specified maximum, section 2.2a)**; reg 0x06 low while V_brick x I is high (firmware, section 8 item 13) | The main hazard class of the concept. Bench procedure rule: differential probes only on the secondary |
| F8 | Ag105 internal short Vin+ to VBat+ | Brick drives VBT directly | Bounded by F2 (1.265 A maximum); OV_BATT at 8.5 V stops the pump; **mandatory** Q_OVP from BQ29200 OUT at 8.70 V after 2-4 s | Q_OVP actuation margin is BENCH (BG-17) |
| F9 | Ag105 EPROM reg 0x01 corrupted to 3S/12.6 V | Overcharge attempt at CC | OV_BATT 8.5 V single sample; `J` 3S check; mandatory Q_OVP | As F8 |
| F10 | Ag105 EPROM reset (reg 0x02 to default 18 V) | No charge (15 V input below threshold) | Firmware sees GENSTAT not charging | None (safe) |
| F11 | D-BC-FC or D-BC-RG stuck ON | `VCHG-IN` live with brick OFF | Brick blocks charging; self-test gated on V_chg below 1.0 V (finding F-m2) | Outside a charge period one hardware layer remains |
| F12 | C1 short plus pin 33 held HIGH | H held near 4.3 V DC: brick ON without toggling | Self-test step c at every boot | Latent between boots; C0G part chosen to make shorts unlikely (UNCONFIRMED failure-mode statistics) |
| F13 | Limiter fails to trip | Mode S overlap unbounded | Bounded by the Ag105 CC and F2; self-test step e | HR3 then rests on firmware |
| F14 | Limiter trips spuriously | Brick OFF, Ag105 restart (9 s) | Pin 17 readback | Charge time lost only |
| F15 | Undocumented internal switch across R_s (DS Fig. 1) closes | Sense bypassed inside the module | Bounded by F2; LD tied to N_VINM disables the load output (section 7.1); same signatures as F7 | UNCONFIRMED behaviour; BG-14 |
| F16 | D-BT-SQ shorted | Pack back-feeds VCHG | As today (prior lesson 2) | Unchanged by IC5 |
| F17 | F1 fuse open | No charge | V_brick 0 with pump ON | None (safe) |
| F18 | Pin-4 stub touches the PCB pad or barrel | As F7 | Bounded by F2; PCB-side stub trimmed flush and sleeved; visual check | Mechanical, rework quality |
| F19 | BR1 primary-to-secondary isolation breakdown (bonds -Vout to -Vin = PCB GND) | As F7 | Bounded by F2; BG-2 isolation check at commissioning | Added in round 1 (finding F-M1) |
| F20 | D-BT-EN shorted (RT1987 single fault) | BT-to-bus conduction with P28 LOW: circular path in Mode S | Limiter current comparator on `BT_CURRENT` (0.2 A) trips in 0.32-1.02 s (BENCH); Ag105 CC and F2 bound the loop | Added in round 1 (finding F-M2) |
| F21 | Pack opens during a charge (PCM trip, J-BT fretting) | The Ag105 drives VBT directly; VBat+ overshoot unspecified | OV_BATT stops the pump; brick-off latency BG-5; TVS on VBT TODO(verify: part) | Added in round 1 (finding F-m5); bench gate BG-22 |
| F22 | +Vout lead chafed to PCB GND | Brick output shorted through R_s in reverse | Bounded by F2; leads insulated | Added in round 1 (finding F-m1) |

## 6. HR1-HR5 status

Table 9 gives the status per requirement after review round 1. HR1, HR2 and HR3 are one coupled choice (finding S-M2):
no IC5 mode meets all three, so they are presented as three options for operator ruling Q1.

Table 9. Hard-requirement status (round 1).

| ID | Status | Basis |
|---|---|---|
| HR1 regen | **FAILS cold; BENCH warm, and warm means continuous CC from the bus through Run** | The brick removes the reg 0x02 discriminator and there is no warm-idle state (section 3.6); a cold charger needs about 9 s. Code 3 covers the 18.9 W peak but needs 1.17 A of bus, above the 1.25 A governor once aux is added, so the BT boost feeds the charger permanently (option i). Code 5 misses the peak and falls onto the 6-40 % cliff (option ii, fails ruling 1's tail clause). Mode S captures no regen (option iii, standstill only) |
| HR2 FC charging | **BENCH** | Mode S: standstill only, with RTWDOG and predicted purges, 9 s Bring-Up per window. Mode C: survives purges, needs the pump gate of Table 5a and the HR3 ruling |
| HR3 no circular loop | **FAILS (Mode C, by construction) / BENCH (Mode S, conduction-keyed limiter of 0.32-1.02 s)** | Mode C circulates in normal operation. Mode S limiter timing rests on an unsourced C3 tolerance, so it is not PROVEN_CALC |
| HR4 no runaway | **PROVEN_CALC with F2 fitted, conditional on BG-1 and BG-2** | Restored sense: Ag105 CC. Sense bypassed (F7, F15, F18, F19): F2 ILIM maximum 1.265 A, at most 2.59 A into VBT. Pack rating against that bound is BG-15 |
| HR5 fail-safe inhibit | **BENCH** | Negative-logic CTRL (open = OFF, PD-2); dynamic pump with 40-74 ms hang detection; boot self-test gated on a dark `VCHG-IN`; no autonomous charge out of POR because the Ag105 is unpowered until the pump runs; minimum loop rate 32 Hz pump frequency |

## 7. Rework procedure, parts list and cost

### 7.1 Procedure (manufactured board)

The following procedure is a plan. Do not perform it until the operator approves the concept and BG-9 is complete.

WARNING: Disconnect the pack at J-BT and J-BL and all bench supplies before you cut any pin. A live pack can short
through the cutter to the GND pour and cause burns or a fire.

1. Measure the Ag105 standoff height and photograph both rows (BG-9).
2. Record R_s: measure 4-wire from the VLoad-1 pad (21.0, 51.78) to the VBAT-1 pad (21.0, 56.86) at no more than
   10 mA (BG-1).
3. Cut pin 4 (Vin-) between the module body and the PCB with flush cutters.
4. Trim the PCB-side pin-4 stub flush with the pad and fit an insulating sleeve over the module-side stub (finding
   E-m3). No lead is soldered to pin 4.
5. Cut pin 10 (Vin+) between the module body and the PCB (finding E-m4). The PCB VIN+ pad stays on `VCHG-IN` and is
   not used. Trim its stub flush. Solder a 22 AWG lead to the module-side stub of pin 10.
6. Measure from the module-side pin-10 stub to the C-D8 pad. The reading must be open circuit, which proves that no
   via or inner-layer path joins the module input to `VCHG-IN` (BG-2).
7. Solder a 22 AWG lead to the VLOAD-1 pad (pin 16, (21.0, 51.78); isolated, "internally connected to Vin-", DS
   Table 2 p.4). This lead is node N_VINM. Label it "VIN- FLOAT - NEVER TO GND".
8. Bridge the LDIS pad (pin 20, (21.0, 41.62)) to the VLOAD-2 pad (pin 17, (21.0, 49.24)) with insulated wire. This
   pulls LD to Vin- and disables the load output (DS Table 2 p.4; finding E-M4). Never connect LD to PCB GND.
9. Solder a fine wire to BQ29200 pin 8 (net BAL-NOK, no copper) for Q_OVP. Q_OVP is mandatory (finding F-m4). If the
   pad cannot be reached without risk to the package, stop and refer the concept to the operator.
10. Build the carrier: BR1, F1, F2 (TPS259474L, RILM 3.32 kOhm), the pump driver, the enable chain (Figure 2), the
    limiter for Mode S (Figure 3) and the V_brick divider. Use single-point grounding: the logic ground of U1-U4, Q_EN
    and the comparator joins PCB GND only at BR1 -Vin; J2 03/04 serves only as the reference for the readback lines
    (finding F-m3).
11. Connect `VCHG-IN` (from the C-D8 pad) through F1 to BR1 +Vin. Connect PCB GND to BR1 -Vin. Twist the pair.
12. Connect BR1 +Vout through F2 to the pin-10 lead, and BR1 -Vout and the F2 GND pin to the VLOAD-1 lead. Twist the
    pair, sleeve it and keep it under 10 cm. Fit a 470 uF capacitor across the Ag105 input at the module end (DS p.6,
    section 2.3; finding E-m2), from the pin-10 lead to the VLOAD-1 lead; it sits behind the brick and F2 soft-start
    and is inside the 2000 uF brick maximum capacitive load (PD-1).
13. Connect the Teensy taps: J2 47/48, 45/46, 43/44, 21/22, 19/20, 05/06 (3V3), 03/04 (GND), J1 39/40 (P28), the
    pin-41 net and the 5 V rail (contacts TODO(verify: facts_board section 7.2)).
14. With the pack disconnected, measure the VLOAD-1 lead to PCB GND with the lead disconnected from BR1. The reading
    must be at least the RECOM isolation value of 1 GOhm (BG-2). Repeat with BR1 connected.
15. Reconnect the lead. Do the bench gates BG-1 to BG-8 in order before any charge above code 12 (100 mA).

WARNING: Do not connect a mains-referenced oscilloscope ground clip to BR1 -Vout, the VLOAD-1 lead or any Ag105 pin on
the secondary side. The clip bonds the floating node to PCB GND through earth and reproduces the 2026-11-04 runaway.
Use a differential probe.

The pin-4 and pin-10 cuts are effectively irreversible. Reverting the pin-4 cut requires a solder bridge from the stub to the pad, which
restores the forbidden tie, or a module replacement.

### 7.2 Parts list and cost

Table 10 lists the parts. Prices are UNCONFIRMED snapshots or estimates and must be checked on the live distributor
pages.

Table 10. Parts and cost.

| Qty | Part | Function | Unit cost (USD) |
|---|---|---|---|
| 1 | RECOM RP30-2415SFW/N (fallback RP30-2415SFW plus section 2.6) | BR1 | about 91-96 (aggregator snapshot, 2026-11-07); DigiKey US 10-week lead |
| 1 | 2.5 A time-lag fuse, at least 32 VDC, plus holder | F1 | TODO(verify: fuse datasheet); estimate 2-5 |
| 1 | TI TPS259474LRPW eFuse, RILM 3.32 kOhm, C_ITIMER and dVdt capacitors, breakout | F2 (round 1) | estimate 3-8 (TODO(verify: distributor)) |
| 1 | TI SN74AHCT1G125 (candidate) | Pump driver (round 1) | estimate 0.4 |
| 4 | onsemi BSS138 | Q_EN, Q_KILL, Q_OVL, Q_OVP | estimate 0.2 each |
| 2 | onsemi BAT54 | D1, D2 | estimate 0.2 each |
| 2 | TI SN74LVC1G17 | U1, U3 | estimate 0.4 each |
| 1 | TI SN74LVC2G32 + 1 TI SN74LVC1G08 | U2, U4 (Mode S only) | estimate 0.5 each |
| 1 | Push-pull comparator (candidate TI TLV7011) | CMP (Mode S only) | estimate 0.5 |
| 2 | 1 uF C0G, 25 V or more | C1, C2 | estimate 0.5-1 each |
| 1 | 15 uF X7R, 10 V or more | C3 (Mode S only) | estimate 0.3 |
| 1 | 470 uF, 35 V or more, low-ESR electrolytic | Ag105 input capacitor (round 1) | estimate 1 |
| 1 | Clamp diode or TVS for pin 16; TVS on VBT | Protection (round 1) | TODO(verify: parts); estimate 1-2 |
| ~20 | Resistors per Figures 2 and 3 and section 2.5 | - | estimate 0.05 each |
| 1 | Perfboard carrier, 2-pin and 6-pin headers, 20/22 AWG wire, sleeving | - | estimate 5-10 |
| | **Total** | | **about 115-140 (UNCONFIRMED)** |

## 8. Firmware, telemetry and HIL impact

The following changes would be needed. They are listed for the review round; none is made by this study.

1. **CSV first.** Add pins 33, 34, 35, 16 and 17 to `references/Scale Car Teensy IO - IO.csv`. Add to the row-28 note
   the IC5 rule: the brick must be OFF before BT_BUS closes, and in Mode S the brick may run only with BT_BUS LOW except
   during a bounded purge bridge. The row-31 rule ("BT_BUS_ENABLE and REGEN_ENABLE must be turned off before this is
   turned on") is kept unchanged: after round 1 no IC5 sequence holds REGEN and FC_CHARGE HIGH together (Table 4). This
   is an operator ruling, and it also changes CLAUDE.md section 2.
2. **Charge-enable split.** `assertFcChargeEnable()` keeps the input-path role; a new `assertBrickEnable()` owns the
   pump, the kill line and the BT_BUS rule. `FAULT_SWITCH_CONFLICT` (ino:7413-7418) is re-keyed to "brick enabled and
   BT_BUS HIGH outside a bridge" (Mode S) and enabled in bench builds. In Mode S every BT_BUS-closing owner must be
   made brick-aware (finding S-M4): the share latch (ino:13463, 13570), `applyShareRatio()` (ino:14893, 14904), the
   guarded re-closes and the regen branch of `chargingControl()` (ino:15321, 15361, 15392, 15526), the F1 disarm, the
   selector re-arm and the load-guard restore. Each either refuses while the pump runs or stops the pump first.
3. **Pump.** One `digitalWriteFast(33, ...)` toggle per `loop()` iteration, after `detectFaults()`, only while
   `assertBrickEnable()` permits, and never from an ISR or IntervalTimer (section 3.2). Blocking calls (EEPROM commit,
   SD init and close, `Ethernet.begin()`, Wire to a module at a power edge) are forbidden while charging is desired,
   or the firmware accepts the charger restart. Firmware measures the loop rate while pumping and stops the pump
   below the 32 Hz pump-frequency minimum (section 3.2).
4. **Windows.** `FC_CHG_MAX_MS` (30 s) and the 2 s cooldown no longer fit a 9 s Bring-Up; the window logic is
   redesigned around purge bridges (Mode S, standstill only) or replaced by the traction pump gate (Mode C, Table 5a).
   The fw v33b purge refusal and the FC-only lockout are revisited per mode. In Mode S the full brick draw is reserved
   as FC headroom from pump start (finding S-M5).
5. **Termination.** The firmware ends a charge when GENSTAT shows CV (status bit 5) and reg 0x06 stays below
   I_5V_est + 0.10 A for a dwell (both TODO(calibrate)), because the module itself will not terminate (section 4.9).
6. **State 99.** Charger-class errors stop the pump as the first action; other errors keep an already running brick for
   the phase-0 and phase-1 drains, then stop it (Table 4). The bleed-only discharge time of VBUS and V-MOT, and the
   TPS61288 back-feed ordering against it, are bench gate BG-18 before the State-99 head change is accepted.
7. **Ag105 configuration.** The lazy config writes reg 0x00 = 0x05 (1.25 A) instead of 0x01 (2.5 A), reg 0x01 = 0x08,
   and a fixed reg 0x02 count 27 (13.376 V) once. The fw v24 dynamic threshold policy is retired, and its tests and
   HIL mirror are retired or re-pinned, not left disabled (finding S-m7): the pin-38 window now measures the brick
   input, and the brick output is fixed. `chargerHasPower()` adds "brick enabled and V_brick above 11 V". The settle
   timer starts on the brick edge.
8. **Flag.** `AG105_VBATN_ISOLATED` no longer describes the hardware. A new `AG105_SENSE_RESTORED_IC5` flag is set
   only after BG-1 and BG-2 pass; the G1-G4 guards and the trip latch stay.
9. **New faults.** `OV_BRICK` (V_brick above 17 V, below the 18 V clamp), `BRICK_UNCOMMANDED` (V_brick above 11 V with
   the pump OFF for more than 60 ms: open the input paths), the `BRICK_SELFTEST` latch, and a limiter-trip fault.
   `OV_BATT` at 8.5 V sits only about 0.1-0.15 V above the Ag105 CV minus the D-BT-SQ drop, before divider tolerance;
   nuisance trips are possible and the margin is measured in BG-12 (finding F-m9).
10. **Telemetry.** `switch_state` bits 0x40 (EN_LOGIC readback) and 0x80 (limiter trip) use the two spare bits. V_brick
    needs a new field, so the packet changes. The change is merged into the existing telemetry v5 proposal (commit
    `bbf560d`), not bumped independently (finding S-m6); use the protocol-bump skill. The BLG flag bytes are full, so
    the bench log needs a new version.
11. **HIL.** The simple plant (`tools/hil_plant_sim.py`) needs the brick gate on the charger model, the pump readback,
    the V_brick channel, a VBT node separate from the pack (for Mode C circulation and termination), the Bring-Up delay
    and the Bring-Up-to-CC step. The hi-fi `BT_SEQ` semantic mismatch (facts_firmware section 9) is independent of IC5
    and still open.
12. **Tests.** Host-native tests for the pump gating, the toggle-context rule, the loop-rate stop, the self-test
    sequence and its V_chg gate, the State-99 head, the Mode S bridge timing, the brick-aware BT_BUS owners and the
    fault re-keying.
13. **Run-time guards and observability (finding S-M7).** G1 and G2 cannot be ported as written, because normal
    charging draws 0.84 A plus aux and traction. A Run-time equivalent needs the brick input power, which is not
    measured; the options are a brick input current sense or a model with a stated error (TODO(calibrate)). Reg 0x06
    now counts the LM1084 load and, in Mode C, the BT-boost input draw, so pack charge current is measured nowhere.
    The Pi-side EKF SoC (bridge 2026-10-31A) loses its charge-current input.
14. **EMS scope (finding S-M7).** The chain efficiency falls from 0.88 to 0.783 (section 4.1). Every EMS artefact built
    on the Ag105 eta 0.88 ruling becomes stale: the measured L_chg lever, alpha, lambda, the SDP policies and the DP
    tables. The charge lever becomes binary with a 9 s restart latency; current changes only through EPROM writes of
    unknown endurance (DS p.13), so `charge_goal` maps onto on/off only.

## 9. Open questions and bench gates

### 9.1 Operator rulings needed

| ID | Question |
|---|---|
| Q0 | Does a charger-side isolation (sense restoration plus a fail-safe charger-input inhibit, no switch at the battery terminals) satisfy the request (section 0.1)? |
| Q1 | The coupled HR1/HR2/HR3 choice (section 6): (i) Mode C at code 3 or lower with structural BT-fed circulation, above the FC budget at standstill; (ii) Mode C at code 5 with partial regen capture (fails ruling 1's tail clause); (iii) Mode S, standstill only, no regen capture |
| Q2 | Does the brick enable satisfy the ruling-3 relaxation clause (section 3.6), given that inside a charge period it is the only hardware layer? |
| Q3 | Accept the irreversible pin-4 and pin-10 cuts |
| Q4 | Charge current code (5 baseline; 3 for full regen capture needs the pack datasheet and a new F2 RILM) |
| Q5 | State-99 drains: keep an already running brick for the drain windows (Table 4), or brick-OFF teardown with bleed only |
| Q6 | Standstill charging in Idle |
| Q7 | Withdrawn in round 1: the BQ29200 OUT trip (Q_OVP) is mandatory |
| Q8 | Mode S preconditions: RTWDOG (T-W-01) and purge prediction (T-E-01) before any Mode S window |

### 9.2 Bench gates

| ID | Gate | Pass condition |
|---|---|---|
| BG-1 | R_s value and sense restoration | Reg 0x06 tracks an external DMM-measured output current within 2 LSB at codes 12, 8 and 5 |
| BG-2 | No DC path from N_VINM to GND except R_s | VLOAD-1 lead to GND at least 1 GOhm with BR1 disconnected; module-side pin-10 stub open to `VCHG-IN` |
| BG-3 | Ag105 start-up with a stiff 15 V input and a working sense | Time from brick enable to first charge current; shape of the Bring-Up-to-CC step; restart behaviour after 0.15-0.3 s input interruptions |
| BG-4 | Enable-chain timing | Pump ON within 10 ms; OFF in 40-74 ms (calc); kill under 1 ms; enable holds at the 32 Hz minimum pump frequency; limiter 0.32-1.02 s; release 0.50-1.12 s; brick switching does not hold node H up after pin 33 stops (finding F-m7); self-test steps 0 and a-e pass |
| BG-5 | Brick CTRL-off to Ag105-input-below-11 V latency | Measured; not published |
| BG-6 | C_int of BR1 and the `VCHG-IN` close inrush | Inrush at most 1.0 A including aux |
| BG-7 | I_5V and termination behaviour | I_5V measured; firmware termination ends the charge |
| BG-8 | Sense-bypass fault injection (F7) with F2 fitted | Current into VBT at most 2.59 A; F2 latches off; firmware flags reg 0x06 low against V_brick x I |
| BG-9 | Pin-4 and pin-10 cut feasibility | Standoff allows clean cuts, flush PCB-side stubs and insulated module-side stubs |
| BG-10 | Chain efficiency at 15 V in, 2S, codes 5 and 3 | Measured |
| BG-11 | Reg 0x06 noise with the brick switching | Within 2 LSB |
| BG-12 | Mode C circulation and CV error | Pack net current by external clamp meter matches Table 5a; VBat- to J-BT pin 2 pour drop under BT load measured; OV_BATT margin measured |
| BG-13 | Carry-over gates | S0-R3/T-E-03, M-R1, M-R2, T-E-01, T-W-01 (facts_prior section 11) |
| BG-14 | Ag105 internal switch across R_s | Reg 0x06 matches the external current in every GENSTAT state, including Fully Charged to recharge, with LD tied to N_VINM |
| BG-15 | Pack datasheet, maximum charge current (against the 2.59 A F2 bound), protection board | Obtained |
| BG-16 | Run-time guard redesign (section 8 item 13) | Detection latency and false-trip rate under traction stated |
| BG-17 | Q_OVP actuation | Brick OFF when the BQ29200 OUT asserts at VDD near VPROTECT |
| BG-18 | State-99 bleed-only discharge | VBUS and V-MOT discharge times with the brick OFF; back-feed ordering re-checked |
| BG-19 | Warm-idle candidates | Keep-alive and fast-start lever: time from input-above-threshold to CC with VCHG held |
| BG-20 | Mode S drained-node recovery | FC-boost restart and BT_BUS re-close onto a drained V-MOT node stay below Death-5 inrush |
| BG-21 | Bus stability, brick on an FC-only bus | No oscillation at code 5 plus aux |
| BG-22 | Pack open during a charge | VBat+ and VBT overshoot and the brick-off latency measured; TVS sized |

### 9.3 Unproven items

The following items are not proven by this dossier: the Ag105 efficiency and Bring-Up time at the IC5 operating
point; the brick efficiency at 40 % load and 16 V; the brick over-load maximum and its CTRL-off latency; the
SN74LVC1G17 thresholds at 3.3 V (interpolated); the R_s value and the THERM/I2C offsets; the regen pulse shape behind
the 0.46 J excess; the bus capacitance behind the 17 V/ms purge collapse; the stock of the negative-logic brick; and
whether the undocumented internal switch of DS Fig. 1 ever parallels R_s during charge.

## 10. Review round 1 adjudication

### 10.1 Method and verdict summary

Three adversarial reviews (fault, electrical, system) returned "survives with fixes" with no FATAL findings. Each
finding was checked against a primary before it was adjudicated. The primaries read for this round were the following:

- `teensy_controller/teensy_controller.ino` at the cited lines (ino:9440 `ag105CommissionTick()`; ino:12743
  `assertFcChargeEnable()`, which drives BT_BUS LOW and REGEN LOW before FC_CHARGE HIGH; ino:8295-8330 State-99
  phases 0-1).
- `references/Scale Car Teensy IO - IO.csv` row 31.
- `references/Datasheets/RT1987_DS-00.pdf` section 17.6 and the Ideal Diode rows of the electrical table.
- `references/Datasheets/BQ29200_TI.pdf` (SLUSA52C) section 7.5, OUT pin rows.
- `references/Datasheets/INA253A1IPWR.pdf`, Electrical Characteristics, IOS row.
- onsemi BAT54LT1/D Rev. 18 (November 2024), p.1-2, read from the vendor PDF.
- TI SCES351Y (SN74LVC1G17, revised October 2025), section 5.5 DC table, read from the vendor PDF.
- TI SLVSFC9C (TPS25947, revised May 2026), p.1 Features, sections 4, 6.3, 6.5, 7.3.5 and 7.3.9, read from the vendor
  PDF.
- `facts_ag105.md` sections 1.2, 1.3 and 7 and `facts_board.md` sections 4 and 5 in this folder.

No vendor file was saved into the repository.

All 46 findings were verified. 43 are ACCEPTED and fixed or recorded in the design body; one of these (F-M5) is accepted in substance
with a partial refutation of a sub-claim. Two are confirmations with no defect (E-m1, E-m9), and one is a positive
note (S-m10). No finding is refuted outright. Finding identifiers are F (fault review), E (electrical review) and S
(system review), followed by the reviewer's own M (major) or m (minor) number.

### 10.2 Major findings

Table 11 gives the adjudication of the major findings.

Table 11. Major findings.

| ID | Verdict | Evidence | Design change |
|---|---|---|---|
| F-M1 | ACCEPTED | RP30-FW PD-4 gives over-load protection as "150 % typ." only (section 2.1 Table 1 already said so). ino:9440 confirms that G1 and G2 run only in `ag105CommissionTick()`, which returns without a `J` session; their 1.0 A threshold (facts_firmware section 3.5) is below normal traction. Brick isolation breakdown was missing from Table 8 | Secondary eFuse F2 (TPS259474L, ILIM maximum 1.265 A by SLVSFC9C p.1 +/-10 %), section 2.2a. F7/F15/F18/F19 bound restated as at most 2.59 A into VBT with no typical value (section 4.10). F19 added. G1/G2 removed from the counted ceilings; Run-time redesign is section 8 item 13 and BG-16 |
| F-M2 | ACCEPTED | The round-0 limiter (Figure 3) took only the P28 command. A shorted D-BT-EN conducts with P28 LOW, so the limiter could not trip. Mode C circulates in normal operation (section 4.6) | Limiter keyed on P28 OR a 0.2 A comparator on the SNS-BT INA253 output (`BT_CURRENT`), section 2.4. INA253 offset +/-15 mA maximum (IOS row) is 7.5 % of the threshold. F20 added. Table 9: Mode C HR3 FAILS by construction |
| F-M3 | ACCEPTED | Section 4.5 had no recovery analysis. The exposure is not new: fw v28 and later FC windows already open BT_BUS (facts_firmware section 2), so the same drained-node recovery exists today; IC5 lengthens it | Mode S restricted to standstill; RTWDOG (T-W-01) and purge prediction (T-E-01) are hard preconditions (Table 4, Q8). Recovery onto a drained V-MOT node is BG-20 and UNCONFIRMED |
| F-M4 | ACCEPTED | Round-0 Table 4 held REGEN HIGH in Run discharge with the brick as the inhibit, which reduces two series layers to one | Table 4: FC_CHARGE and REGEN LOW whenever the pump is OFF (Idle and Run discharge). Section 3.6 states that inside a charge period the brick is the only hardware layer |
| F-M5 | ACCEPTED, sub-claim partly refuted | IO-CSV row 31 and ino:12743 confirm that FC_CHARGE requires REGEN LOW; round-0 Mode C held both HIGH. The sub-claim that RT1987 reverse blocking is uncited is partly refuted: RT1987 DS-00 section 17.6 specifies a fast reverse-current comparator that trips within tFRC of about 0.5 us when VIN - VOUT falls below VFRC of about -50 mV. Both values are typical only, so the reverse-blocking response remains unproven by maximum | Mode C now feeds the brick through REGEN only, with FC_CHARGE LOW (MOT_PWR is HIGH through Idle and Run by the Death-5 rule, so the REGEN path is bus-fed). Row 31 is no longer deviated from (section 8 item 1). The remaining reverse-blocking dependency is D-MT-EN against V-MOT, which the board already relies on at every regen event |
| E-M1 | ACCEPTED | As F-M1. F1 at 2.5 A time-lag carries the 3.2 A F7 input current (128 %) for minutes; the fuse curve is still TODO | Same fix as F-M1. Section 2.2 now states that F1 is not an F7 protection |
| E-M2 | ACCEPTED | SCES351Y section 5.5: II = +/-5 uA on the A input in both temperature columns. On the round-0 0.82 MOhm node this is +/-4.1 V, larger than the threshold window. BAT54LT1/D p.2: IR 0.2 / 2.0 uA (typ/max) at VR 25 V, 25 C | Limiter redesigned: 47 kOhm source, no diodes, C3 15 uF; leakage moves the end point by +/-0.235 V. Timing 0.40-0.85 s at nominal C3, 0.32-1.02 s at +/-20 %. HR3 Mode S downgraded from PROVEN_CALC to BENCH (section 3.3) |
| E-M3 | ACCEPTED | BAT54LT1/D Rev. 18 p.1-2: 0.22 / 0.24 V is the IF = 0.1 mA row; 1.0 mA is 0.29 / 0.32 V; 10 mA is 0.35 / 0.40 V (the p.1 feature line "0.35 V typ at IF = 10 mA" fixes the row order). With the corrected VF and the U1 leakage, a 3.3 V pump leaves no ON margin | Table 2 corrected. Pump driven at 5 V through an AHCT buffer; C1 1 uF, R1 470 Ohm, R2 47 kOhm, C2 1 uF. V_H 3.47-3.94 V, ON margin at least 1.39 V, hang-to-off 40-74 ms, minimum pump frequency 32 Hz with a firmware loop-rate check (section 3.2) |
| E-M4 | ACCEPTED | DS p.9 (facts_ag105 section 1.3): the battery is on VLoad whenever the module is not charging; DS Table 2 p.4: "Pull this pin to Vin- to disable the load output"; facts_board section 4: LDIS is an isolated pad | LD bridged to VLOAD-2 (= N_VINM), never to PCB GND (section 7.1 step 8). F15 is also bounded by F2. BG-14 kept with LD tied |
| E-M5 | ACCEPTED | As F-M4 | As F-M4 |
| S-M1 | ACCEPTED | DS p.10: the reg 0x02 threshold gates charge start on the module input voltage; the brick fixes that input at 15 V. facts_ag105 section 10: no charge enable | Section 3.6 states that warm capture means continuous CC from the bus through Run. Warm-idle candidates (keep-alive; MPPTD with a high threshold, TODO(verify: Silvertel); Trim-pin lever) recorded as BG-19. Table 9 HR1 rewritten |
| S-M2 | ACCEPTED | Code 3: 1.17 A at 16.0 V (Table 5) plus 0.10-0.15 A aux = 1.27-1.32 A, above the 1.25 A governor and the 1.247 A P_MAX (facts_prior section 7) | Section 6 presents HR1/HR2/HR3 as one coupled ruling with options (i)-(iii); Q1 rewritten |
| S-M3 | ACCEPTED | Recomputed with the dossier's own assumptions: pack net +2.4 to +3.1 W at 10 W traction and -3.2 to -2.5 W at 15 W; zero crossing at 12.1-12.7 W | Table 5a and the Mode C pump gate (section 4.6). Battery-only arm and selector re-arm forbidden while pumping (Table 4) |
| S-M4 | ACCEPTED | The cited owners are the BT_BUS writers listed in facts_firmware sections 2 and 6 | Section 8 item 2 enumerates them and requires brick-aware behaviour. RTWDOG made a Mode S precondition (F1 row, Q8) |
| S-M5 | ACCEPTED | DS p.6: the Bring-Up exit time is not specified; OC_FC is a 1.4 A single-sample trip (`LIMIT_I_FC_MAX`, ino:2090) | Table 4 Mode S step 3 reserves the full brick draw from pump start; BG-3 extended to the step shape |
| S-M6 | ACCEPTED | ino:8295-8330: phase 0 opens both bus switches and calls `assertFcChargeEnable(true)` to drain VBUS into the charger; phase 1 opens REGEN for a V-MOT drain. With the brick OFF these drains reach only C-D8/C-D10 and the brick input filter | Table 4 State-99 row: charger-class errors stop the pump first; other errors keep an already running brick through the drain windows. Bleed-only discharge and back-feed ordering are BG-18; Q5 rewritten |
| S-M7 | ACCEPTED | Section 4.1 chain efficiency 0.783; operator rulings 2026-09-01g fix eta 0.88 in the EMS | Section 8 items 13 and 14 added (EMS re-derivation scope, binary charge lever, guard redesign, pack current unobservable for the Pi EKF) |
| S-M8 | ACCEPTED | IC5 adds no switch at J-BT or J-BL; `assertFcChargeEnable()` (ino:12743) already opens BT_BUS for FC windows | Section 0.1 and Table 0 added; operator ruling Q0 |

### 10.3 Minor findings

Table 12 gives the adjudication of the minor findings.

Table 12. Minor findings.

| ID | Verdict | Design change |
|---|---|---|
| F-m1 | ACCEPTED | 10 kOhm series resistor and clamp on pin 16 (section 2.5); secondary leads sleeved; a chafed +Vout lead is bounded by F2 (F22) |
| F-m2 | ACCEPTED | Self-test step 0: V_chg below 1.0 V, or no self-test and no charging (Table 4) |
| F-m3 | ACCEPTED | Single-point carrier grounding at BR1 -Vin (section 7.1 step 10); 100 kOhm pull-down on the P28 tap (Figure 3) |
| F-m4 | ACCEPTED | Q_OVP mandatory. SLUSA52C section 7.5: OUT at least 1.75 V at VDD = VPROTECT, 6 / 8.25 / 9.5 V at VDD = 10 V, at most 200 mV low. R12 1 kOhm, R13 1 MOhm; the 0.25 V margin over the BSS138 VGS(th) maximum is BG-17 |
| F-m5 | ACCEPTED | F21 added; TVS on VBT (part TODO); BG-22 |
| F-m6 | ACCEPTED | Toggle-context rule (section 3.2) and host test (section 8 item 12) |
| F-m7 | ACCEPTED | Added to BG-4 |
| F-m8 | ACCEPTED | F6 residual states the firmware dependency |
| F-m9 | ACCEPTED | Section 8 item 9; margin measured in BG-12 |
| E-m1 | No defect | The selection-guide values (1404 mA, 89 %, 2000 uF) are to be re-read from the rendered PD-1 page before ordering; no change |
| E-m2 | ACCEPTED | 470 uF at the Ag105 input, secondary side (section 7.1 step 12) |
| E-m3 | ACCEPTED | -Vout lands on VLOAD-1; PCB-side pin-4 stub trimmed flush (section 7.1 steps 4 and 7) |
| E-m4 | ACCEPTED | Pin 10 cut instead of the pad traces; open-circuit check to C-D8 (section 7.1 steps 5 and 6) |
| E-m5 | ACCEPTED | Pour-drop measurement in BG-12 |
| E-m6 | ACCEPTED | BG-21 |
| E-m7 | ACCEPTED | Section 4.10 item 4 |
| E-m8 | ACCEPTED | BG-3 re-measures the Bring-Up with the sense restored |
| E-m9 | Confirmation | No change |
| S-m1 | ACCEPTED | Section 4.5 notes the constant-power acceleration |
| S-m2 | ACCEPTED | Blocking-call list and guard (section 3.2, section 8 item 3) |
| S-m3 | ACCEPTED | Superseded by the redesigned limiter (minimum 0.32 s, release 0.50-1.12 s); a mispredicted long purge still costs a lockout and a Bring-Up |
| S-m4 | ACCEPTED | BG-3 (as E-m8) |
| S-m5 | ACCEPTED | Mode C command policy covers pump-off gaps below the 0.25 A selector gate (Table 4) |
| S-m6 | ACCEPTED | Merge into the existing telemetry v5 proposal (section 8 item 10) |
| S-m7 | ACCEPTED | fw v24 tests and HIL mirror retired or re-pinned (section 8 item 7) |
| S-m8 | ACCEPTED | H11 remains OPEN; the positive-logic fallback keeps its single-point failure (section 2.6) |
| S-m9 | ACCEPTED | Duplicate of E-m5; BG-12 |
| S-m10 | Positive note | No change |

### 10.4 Post-review status

IC5 survives round 1 as a **charger-side** concept. It restores the Ag105 current sense, it bounds every single fault
that bypasses the sense at 2.59 A into VBT by a specified eFuse maximum, and it gives a fail-safe, Teensy-commanded
charger-input inhibit that defaults OFF out of POR and drops within 40-74 ms of a hung loop (calculated). The pack,
the Teensy supply and every measurement reference stay untouched. These are real advantages over option 2 of the
re-spin note.

However, IC5 does not deliver the operator's literal request, because it adds no switch at the battery terminals
(Q0). It also cannot meet HR1, HR2 and HR3 together in any mode:

- Mode C fails HR3 by construction, and its regen capture needs either code 3 with permanent BT-fed circulation
  above the FC budget, or code 5 with partial capture that fails ruling 1's tail clause.
- Mode S meets HR3 only at BENCH level and only at standstill, with RTWDOG and purge prediction as preconditions, and
  it captures no regen.
- Warm regen capture in any mode means continuous CC charging from the bus through Run, which ruling R3 forbids unless
  the operator accepts the brick enable under the ruling-3 relaxation clause (Q2).

Status by requirement: HR4 PROVEN_CALC with F2, conditional on BG-1 and BG-2; HR5 BENCH; HR3 FAILS (Mode C) or
BENCH (Mode S); HR2 BENCH; HR1 FAILS cold and is BENCH warm only under continuous CC. The concept is therefore not a
complete winner on the hard requirements. It is a viable, low-regret retrofit if the operator rules Q0 and Q1 in its
favour, and its HR4 and HR5 elements (F2 on the charger output loop, the pumped negative-logic enable, the LD tie) are
reusable by any concept that keeps the Ag105.

The largest remaining uncertainties are the following: the Ag105 Bring-Up time and step shape with the sense restored
(BG-3); the brick CTRL-off latency (BG-5); the limiter timing with a sourced C3 tolerance (BG-4); the drained-node
recovery in Mode S (BG-20); the pack maximum charge current against the 2.59 A bound (BG-15); and whether the
undocumented internal switch of DS Fig. 1 ever conducts with LD tied (BG-14).
