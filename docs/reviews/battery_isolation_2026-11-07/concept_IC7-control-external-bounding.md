# Concept IC7: Control Concept, External Bounding of the Blind Charger

Date: 2026-11-07. Board revision 20260622, fw v37 rev 2 (`AG105_VBATN_ISOLATED 0`). Study folder:
`docs/reviews/battery_isolation_2026-11-07/`. Inputs: `facts_board.md`, `facts_ag105.md`, `facts_firmware.md`,
`facts_prior.md`, `brainstorm.md` (cluster IC7, raw concepts C4 and D; cross-cutting findings X1-X9).

## 0. Summary

This dossier develops the control concept IC7. IC7 does not isolate the pack and does not restore the Ag105 current
sense. It places hardware bounds around the Ag105 from outside: a latching eFuse on the charger input, a hardware loop
breaker on the D-BT-EN enable, a latched over-voltage trip, and an external watchdog. Variant b adds a linear
charge-current limiter in the pack return.

The analysis reaches the following verdict. Variant a meets HR3 (no sustained loop) by a hardware gate and bounds every
charger event by the eFuse. However, variant a cannot charge: with the sense shorted, every charge attempt is a Bring-Up
ramp that ends at the eFuse trip, so HR1, HR2 and HR4 fail. Variant b can, in principle, form a crude CC-CV charger
(CC from the linear FET, CV from the Ag105 voltage loop), but that CV behaviour with a blind sense is UNCONFIRMED, the
linear FET needs a heatsink, and the low-side placement corrupts the BQ29200 bottom-cell reading and violates X1 unless
the balance-lead return is re-terminated. IC7 is therefore retained as the source of the common safety layers (X4), not
as a candidate design. The safety-layer set in sections 2.1-2.4 is detailed enough to transplant into IC1-IC6.

## 1. Topology

### 1.1 Notation

The following terms are used throughout.

- **EF_CHG**: the new eFuse inserted between net `VCHG-IN` and Ag105 pin 10 (Vin+).
- **VCHG-EF**: the new node between the EF_CHG output and Ag105 Vin+. It is the actual Ag105 input.
- **Loop breaker**: the new logic gate inserted in net `D-BT-EN` between Teensy pin 28 and the D-BT-EN EN pad.
- **Trip latch**: the new flip-flop that, once set, removes the EF_CHG enable until the Teensy clears it.
- **Trip line**: the open-drain wired-OR net (active LOW) that sets the trip latch.
- **Q_CHG**: variant b only; the linear charge-current limiter MOSFET in the pack return.

### 1.2 Variant a (safety-layer kit)

Figure 1 shows variant a. Existing parts are in plain text; new parts are marked `[NEW]`. The pack, J-BT, J-BL, the
Ag105 pins 14/15 and D-BT-SQ are unchanged.

```
 Figure 1. IC7 variant a. Power path (top) and control logic (bottom).

 VBUS --[D-BC-FC, EN=31]--+                                  pack+ --J-BT1-- VBT ---+--> REG-BT (BT boost) --> SNS-BT
                          +-- VCHG-IN --[EF_CHG NEW]-- VCHG-EF --> Ag105 Vin+          |                       --> D-BT-EN --> VBUS
 V-MOT --[D-BC-RG, EN=30]-+   (C-D8, C-D10,         (Ag105 pin 10)                     +--> REG-5V (LM1084) --> Teensy
                              R1-CHG/R2-CHG)             |                              +--> R1-BT/R2-BT (V_batt)
                                                         |  Ag105 VBat+ = VCHG --[D-BT-SQ, EN=32]--> VBT
                                                         |  Ag105 VBat- = Vin- = GND (UNCHANGED: sense still shorted)
                                                         |
                                  [NEW] R 4.7k bleeder --+-- [NEW] divider 383k/100k --> CMP_PWR (TLV3012B, 5V)
                                                                                        "NOT_POWERED" (HIGH = VCHG-EF < 6.0 V)

 Control logic (all [NEW], on a carrier board fed from J2 3V3 / 5V / GND):

  Teensy 28 --(trace cut)--> AND2_BRK.A ---------------------\
  CMP_PWR "NOT_POWERED" -------------> AND2_BRK.B ------------> AND2_BRK.Y --> D-BT-EN EN pad (existing 10k pull-down kept)

  VBT  --590k/100k--> CMP_OVP (TLV3011B, open drain) --\
  BQ29200 OUT --200k/100k--> CMP_BAL (TLV3011B, OD) ----+--> TRIP line (10k to 3V3, 1 uF to GND) --> FF.PRE#  (SN74LVC1G74)
  TPS3431 WDO (open drain) ----------------------------/                                       \--> AND3.C
  Teensy 35 WDT_KICK --> TPS3431 WDI                                                  FF.Q  --> Teensy 10 (TRIP_Q readback)
  Teensy 21 TRIP_CLR# (10k pull-up to 3V3) --> FF.CLR#                                FF.Q# --> AND3.B
  Teensy 34 CHG_ARM (10k pull-down) ----------------------------------------------------------> AND3.A
                                                     AND3.Y (SN74LVC1G11) --1k--> EF_CHG EN/UVLO (100k pull-down)
  EF_CHG ILM --> Teensy 16 (A2, EF_ILM analog)       EF_CHG PG (open drain, 10k to 3V3) --> Teensy 23 (EF_PG)
  CMP_PWR "NOT_POWERED" --> Teensy 33 (CHG_PWR readback)
```

The loop that ML0227 produced (bus, D-MT-EN, V-MOT, D-BC-RG, VCHG-IN, Ag105, VCHG, D-BT-SQ, VBT, BT boost, D-BT-EN, bus;
`facts_prior.md` section 4.1) is cut at D-BT-EN whenever VCHG-EF is above 6.0 V. The pack can reach VBUS only through
D-BT-EN (`facts_prior.md` section 5, from [LOOP] 2), so this cut removes every bus-closing path of the loop. The
charger-to-pack leg (VCHG, D-BT-SQ, VBT, pack) remains and is bounded only by EF_CHG and the trip latch.

### 1.3 Variant b (pack-return linear limiter)

Variant b keeps every part of variant a and adds the elements in Figure 2. The brief's back-to-back CHG/DSG pair reduces
to a single FET (section 2.6): Q_DSG has no function in IC7, because IC7 never blocks discharge.

```
 Figure 2. IC7 variant b additions (pack return, low side).

 pack- --[NEW harness]-- Q_CHG drain   Q_CHG source --[R_SH 2 mOhm NEW]-- J-BT pin 2 (PCB GND)
                         (CSD18535KCS, TO-220 on heatsink; body diode conducts GND -> pack-, i.e. discharge)
 J-BL pin 3 (balance negative): board pad isolated from GND, wire moved to pack- (X1) -- see section 4.6

 Limiter (all VBT-powered, Teensy-independent):
   OPA197 (V+ = VBT, V- = GND): IN+ = V_REF_LIM, IN- = top of R_SH (charge current -> positive)
   OPA197 OUT --100 Ohm--> Q_CHG gate; gate 100k to GND
   V_REF_LIM = 3.0 mV (1.5 A x 2 mOhm) when LIM_SEL is HIGH; 0 mV (charge inhibit) by default
   Teensy 22 LIM_SEL (10k pull-down) --> reference-select switch (part TODO)
   R_SH --> second amplifier (gain 100, charge direction only, part TODO) --> Teensy 17 (A3, PACK_I)
```

## 2. Parts, ratings, gate drive and fail-safe defaults

### 2.1 Charger-input eFuse EF_CHG

Table 1 lists the selected eFuse. The circuit-breaker latch-off variant is chosen because an active current limit
would hold the Ag105 input at the limit and dissipate (V_IN - V_OUT) x I_LIM in the eFuse.

Table 1. EF_CHG, TI TPS259474LRPW (SLVSFC9C, revised May 2026).

| Parameter | Value | Source |
|---|---|---|
| Variant | Adjustable OVLO, circuit breaker, latch-off | SLVSFC9C section 4, Device Comparison Table |
| Input operating range | 2.7-23 V | SLVSFC9C section 6.3 |
| Absolute maximum IN | 28 V | SLVSFC9C section 6.1 |
| Continuous current | 5.5 A (TJ <= 125 C) | SLVSFC9C section 6.3 |
| R_ON | 28.3 mOhm typical | SLVSFC9C section 1 |
| I_LIM setting | R_ILM = 3334 / I_LIM; accuracy +/-10 % for I_LIM > 1 A | SLVSFC9C Equation 5 (section 7.3.5.2); section 1 |
| Selected I_LIM | R_ILM = 2.21 kOhm gives 1.509 A nominal (1.36-1.66 A) | Computed from Equation 5 |
| Transient blanking | t_ITIMER = V_ITIMER x C_ITIMER / I_ITIMER (I_ITIMER 1.8 uA) | SLVSFC9C Equation 6 |
| Selected C_ITIMER | 2.2 nF, about 1.8 ms (V_ITIMER read as about 1.5 V; TODO(verify: SLVSFC9C section 6.5, column scrambled in text extraction)) | Computed |
| Fast trip | Scalable fast trip at about 2 x I_LIM; fixed fast trip I_FT | SLVSFC9C sections 7.3.5, 6.5 (values TODO(verify: rendered table)) |
| Reverse current | Integrated back-to-back FETs, true reverse-current blocking | SLVSFC9C section 1 |
| EN/UVLO | Rising threshold about 1.2 V; pin maximum 6.5 V | SLVSFC9C sections 6.1, 6.5 (threshold TODO(verify: rendered table)) |
| OVLO | Rising threshold about 1.2 V on an external divider | SLVSFC9C section 7.3.3 (TODO(verify: rendered table)) |
| dVdt | C_dVdt (pF) = 2000 / SR (V/ms); 3300 pF gives 0.61 V/ms at 12 V | SLVSFC9C Equation 4; section 6.7 |
| Load monitor ILM | Gain 182 uA/A typical (165-200) | SLVSFC9C section 6.5 |
| Thermal | R_thetaJA 41.7 C/W (4-layer 2s2p); TSD 154 C | SLVSFC9C sections 6.4, 6.5 |
| Package | 10-pin QFN (RPW) | SLVSFC9C section 6.4 |

The design settings are as follows.

1. **I_LIM 1.51 A nominal.** The value is above the FC budget (1.247 A P_MAX bus equivalent, `facts_prior.md`
   section 7), so the firmware G1/G2 guards still own the FC budget. It is below the regen requirement only for the
   largest event: 1.36 A x 19 V = 25.8 W at the low tolerance limit, against 21.5 W for the 18.9 W, 3 -> 1 m/s peak at
   the 0.88 efficiency (`facts_prior.md` section 6; Ag105 DS p.20). The ILM voltage at I_LIM is 1.51 A x 182 uA/A x
   2.21 kOhm = 0.61 V, inside the 3.3 V ADC range.
2. **OVLO 23.0 V.** A 1.20 V threshold needs a ratio of 19.2; 1.82 MOhm / 100 kOhm gives 23.0 V. This is below the
   23 V operating maximum only in nominal terms; the threshold tolerance is TODO(verify). The OVLO keeps EF_CHG inside
   its rating against V-MOT, which the firmware allows up to 28 V (`OV_RGN`, `facts_firmware.md` section 4) and which
   the chopper clamps at a 22.13 V design value (`facts_prior.md` section 6).
3. **dVdt 3300 pF.** The output ramp is 0.61-0.71 V/ms (SLVSFC9C section 6.7), so VCHG-EF needs about 16 ms to reach the
   11 V Ag105 UVLO (Ag105 DS p.19). This slow ramp is the timing margin of the loop breaker (section 4.3).
4. **EN drive.** AND3.Y drives EN/UVLO through 1 kOhm, with 100 kOhm to GND. The 3.3 V logic HIGH exceeds the EN
   threshold and is below the 6.5 V pin maximum.

**Adversarial note on the voltage rating.** EF_CHG lowers the absolute maximum of the charger input chain from 36 V
(Ag105 DS p.19) to 28 V. The chain then depends on the chopper and on the OVLO acting before V-MOT exceeds 28 V. The
OVLO response time is a few microseconds (SLVSFC9C section 6.6, value TODO(verify)); a V-MOT spike above 28 V faster than
that would exceed the rating. This is UNCONFIRMED risk and a bench gate (section 9).

### 2.2 Loop breaker

The loop breaker is a two-input AND gate in net `D-BT-EN`. The firmware's `BT_BUS_ENABLE` command passes to the RT1987
EN only while VCHG-EF is below 6.0 V. Table 2 lists the parts.

Table 2. Loop-breaker parts.

| Part | Function | Rating used | Source |
|---|---|---|---|
| SN74LVC1G08 (AND2_BRK) | EN_DBTEN = PIN28 AND NOT_POWERED | 1.65-5.5 V supply; inputs accept 5.5 V; I_off partial power-down | SCES217AA section 1 |
| TLV3012B (CMP_PWR) | NOT_POWERED = HIGH when VCHG-EF < 6.0 V | 1.65-5.5 V supply; push-pull; 1.242 V reference (1.208-1.276 V); POR; integrated hysteresis | SBOS300C section 1, section 6 |
| 383 kOhm / 100 kOhm, 0.1 % | Threshold 1.242 x 4.83 = 6.00 V (5.84-6.16 V over the reference range) | Computed | - |
| BZT52C4V7 | Clamp across the 100 kOhm leg | 4.7 V nominal | `references/Datasheets/BZT52C_Diodes.pdf` (page TODO(verify)) |
| 4.7 kOhm, 0.25 W bleeder | Discharges VCHG-EF after EF_CHG opens | 3.4 mA, 54 mW at 16 V | Computed |

CMP_PWR is supplied from 5V (J2 pins 01/02) so that its input stays inside the common-mode range: VCHG-EF is capped at
the 23 V OVLO, which maps to 4.76 V. Its output drives a 3.3 V AND gate, which accepts 5.5 V inputs (SCES217AA
section 1). The CMP_PWR input wiring is IN+ = 1.242 V reference, IN- = divider, so a dead comparator or a lost 5 V rail
reads "powered" (LOW) and holds D-BT-EN off. That failure direction is conservative for the loop and costs bus support.

The existing 10 kOhm EN-to-GND bodge resistor on D-BT-EN (OQ-7, scope TODO) stays on the EN-pad side of the cut. A new
10 kOhm pull-down is added on AND2_BRK.A so the Teensy side has a defined LOW while pin 28 is high-Z.

### 2.3 Trip latch, OVP comparators and watchdog

Table 3 lists the trip-chain parts. All parts run from 3V3 (J2 pins 05/06). The 3V3 budget is 250 mA (PJRC,
`facts_board.md` section 6.1); the chain draws tens of microamperes plus pull-up currents, about 1 mA total
(UNCONFIRMED sum).

Table 3. Trip-chain parts.

| Part | Function | Ratings and settings | Source |
|---|---|---|---|
| SN74LVC1G74 (FF) | Trip latch. PRE# = trip line; CLR# = Teensy 21; D tied HIGH, CLK tied LOW | PRE# LOW sets Q HIGH; CLR# LOW clears; PRE# and CLR# both LOW gives Q = Q# = HIGH, "nonstable" | SCES794G Table 8-1 |
| SN74LVC1G11 (AND3) | EF_CHG EN = CHG_ARM AND Q# AND TRIP_LINE | 3-input AND, inputs accept 5.5 V | SCES487I section 1 |
| TLV3011B (CMP_OVP) | Trip when VBT > 8.57 V nominal | Open drain; reference 1.223-1.260 V (B version, TODO(verify: which table row applies to B)); 590 kOhm / 100 kOhm, 0.1 %; 100 nF across the 100 kOhm leg (tau 8.5 ms) | SBOS300C |
| TLV3011B (CMP_BAL) | Trip when BQ29200 OUT is HIGH | OUT / 3 (200 kOhm / 100 kOhm) against REF / 4 (300 kOhm / 100 kOhm from the REF pin) = 0.31 V | SBOS300C; SLUSA52C section 7.5 |
| TPS3431 (WDT) | Hardware watchdog | VDD 1.8-6.5 V; CWD = 10 kOhm to VDD and SET1 = 1 gives t_WD 200 ms (170-230 ms); WDO open drain, LOW for t_RST after a timeout | SNVSB66A sections 1, 6.6, pin table |
| 10 kOhm + 1 uF on the trip line | Power-up set | tau 10 ms holds PRE# LOW at power-up | Computed |

The design rules are as follows.

1. **Power-up state is TRIPPED.** The 1 uF holds the trip line LOW while 3V3 rises, so Q = HIGH and Q# = LOW. EF_CHG
   cannot enable until the Teensy clears the latch.
2. **The "both LOW" hazard of the flip-flop is closed by the third AND input.** With PRE# and CLR# both LOW, the
   SN74LVC1G74 drives Q# HIGH (SCES794G Table 8-1, note 1). Without the TRIP_LINE input on AND3, a firmware clear pulse
   that overlapped an active trip would enable EF_CHG. AND3.C = TRIP_LINE removes the enable for as long as any trip
   source is asserted, independent of the latch state.
3. **CMP_OVP threshold.** 1.242 V x 6.90 = 8.57 V nominal; the B-version reference range gives 8.44-8.70 V. The lower
   bound is 75 mV above the expected end-of-charge VBT of about 8.365 V (8.40 V CV minus the 35 mV D-BT-SQ forward
   regulation, `facts_prior.md` section 10 item 1). This margin is BENCH; the reference of the fitted part should be
   measured and the divider trimmed. The firmware `OV_BATT` (8.5 V, single sample) sits inside the hardware band.
4. **CMP_BAL.** BQ29200 OUT is at least 1.75 V when HIGH (at VDD = V_PROTECT, I_OH = -100 uA) and at most 200 mV when
   LOW; its absolute maximum is 16 V and its high level reaches 8.25 V typical at VDD = 10 V (SLUSA52C section 7.5).
   The divide-by-3 maps 1.75 V to 0.58 V and 9.5 V to 3.17 V, inside the comparator's range on 3V3; the 0.31 V
   threshold sits between the 0.067 V LOW and the 0.58 V HIGH. CMP_BAL adds the per-cell 8.70 V pack (4.35 V/cell)
   protection with its 2-4 s delay (`facts_prior.md` section 5). It uses the BQ29200 OUT pad, which has no copper today
   (`facts_board.md` section 5 item 3), so it needs a fly wire to QFN pin 8.
5. **Watchdog.** WDI is kicked from the main loop only after `detectFaults()` completes. A hung loop lets WDO fall within
   230 ms; WDO sets the latch, and AND3 drops the EF_CHG enable. The t_RST unit is printed in a scrambled column of the
   text extraction (TODO(verify: SNVSB66A section 6.6, rendered page)); it does not matter for the latch, which holds
   after WDO releases. The TPS3431 is independent of the Teensy clock; the RTWDOG (ruling 5) remains required in
   addition (section 8).

### 2.4 Teensy pins

Table 4 lists the Teensy pins. All are from the spare list in `facts_board.md` section 7.2 and `facts_firmware.md`
section 7; none is in the IO CSV today, so the CSV must be amended first by the operator. Pin 20 is deliberately left
free, because WDOG1_B can be routed only to pin 20 (`facts_prior.md` section 5); the brief's "pin 20 latch reset" is
therefore moved to pin 21.

Table 4. New Teensy pins (proposed; CSV amendment required).

| Pin | Proposed name | Dir | Default with Teensy high-Z | Function |
|---|---|---|---|---|
| 34 | `CHG_ARM` | OUT | LOW (10 kOhm pull-down) | Enables EF_CHG through AND3 |
| 35 | `WDT_KICK` | OUT | Undefined (keeper); no kicks means a trip within 230 ms | TPS3431 WDI |
| 21 | `TRIP_CLR` | OUT, active LOW | HIGH (10 kOhm pull-up to 3V3) = no clear | FF.CLR# |
| 10 | `TRIP_Q` | IN | - | Latch state readback (HIGH = tripped) |
| 33 | `CHG_PWR` | IN | - | CMP_PWR readback (HIGH = VCHG-EF below 6 V) |
| 16 (A2) | `EF_ILM` | AIN | - | EF_CHG input-current monitor, 0.61 V at 1.51 A |
| 23 | `EF_PG` | IN | - | EF_CHG power good (open drain, 10 kOhm to 3V3) |
| 22 | `LIM_SEL` | OUT | LOW (10 kOhm pull-down) = charge inhibit | Variant b only |
| 17 (A3) | `PACK_I` | AIN | - | Variant b only; pack charge current |

Pin 28 keeps its name and meaning (`BT_BUS_ENABLE`); after the rework it commands the loop breaker input instead of the
RT1987 EN directly.

### 2.5 Fail-safe defaults

Table 5 lists the state of every new element with the Teensy unpowered, in reset or hung.

Table 5. Fail-safe defaults.

| Element | Unpowered Teensy (3V3 lost) | Teensy in reset (pins high-Z, keeper) | Teensy hung (pins frozen) |
|---|---|---|---|
| EF_CHG | Off: AND3 unpowered, EN 100 kOhm to GND | Off: CHG_ARM pulled LOW | Off within 230 ms: WDO sets the latch, AND3.B and AND3.C go LOW |
| Trip latch | Unpowered; sets on the next power-up | Q holds or sets (WDO) | Set by WDO |
| D-BT-EN | Off: AND2 unpowered, EN pull-down | Off: AND2.A pulled LOW | Follows the frozen pin 28, but forced off while VCHG-EF > 6 V |
| Q_CHG (variant b) | Limiter is VBT-powered and keeps running; reference 0 mV = charge inhibit | Same | LIM_SEL frozen; limit stays at the frozen setting; EF_CHG removes charger power |

### 2.6 Variant b parts

Table 6 lists the variant b parts. Only Q_CHG is primary-cited; the shunt, reference switch and current amplifier are
TODO.

Table 6. Variant b parts.

| Part | Rating | Source |
|---|---|---|
| Q_CHG: TI CSD18535KCS, TO-220 | 60 V; V_GS +/-20 V; V_GS(th) 1.4-2.4 V; R_DS(on) 2.3 typ / 2.9 max mOhm at 4.5 V, 1.6 typ / 2.0 max mOhm at 10 V (25 C); C_iss 5090-6620 pF; R_thetaJC 0.5 C/W max; R_thetaJA 62 C/W | SLPS531A sections 1, 5 and Figure 4-10 note |
| Limiter op-amp: OPA197 (already on the BOM) | 4.5-36 V single supply; rail-to-rail input and output; capacitive load drive 1 nF | SBOS737C section 1 |
| R_SH 2 mOhm, 2512 or larger | Power rating TODO(verify: vendor) | TODO |
| Reference switch, current amplifier | TODO(verify: part selection) | TODO |
| Heatsink, R_theta_SA <= 10 C/W | TODO(verify: vendor) | TODO |

**Why one FET, not a back-to-back pair.** Q_CHG has its source toward PCB GND and its drain toward pack-. Charge
current flows pack- to GND, that is drain to source, and is blocked when Q_CHG is off. Discharge current flows GND to
pack- through the channel when Q_CHG is on, or through the body diode when it is off. A Q_DSG would only add the
ability to block discharge, which IC7 never uses; a Teensy-commanded discharge cut would also remove the Teensy's own
supply. Q_DSG is therefore dropped.

**Gate drive.** The OPA197 runs from VBT (7.4-8.5 V) and swings to within about 0.5 V of its rail (SBOS737C section 7,
output swing figure, value TODO(verify)), so V_GS is about 6.9-8.0 V in discharge. R_DS(on) then lies between the
4.5 V and 10 V figures; this dossier uses the 2.9 mOhm 4.5 V maximum as the conservative bound. C_iss exceeds the
OPA197's 1 nF drive capability, so a 100 Ohm series gate resistor and loop compensation are required; loop stability is
BENCH.

**Bootstrap.** At first pack connection, the op-amp is unpowered and Q_CHG is off. The body diode conducts in the
discharge direction, so VBT rises to about V_pack - 0.8 V (CSD18535KCS V_SD, SLPS531A section 5), which exceeds the
OPA197 4.5 V minimum. The op-amp then drives the gate HIGH, because discharge current makes the shunt voltage negative.
The limiter therefore starts without the Teensy.

## 3. Control sequence

Table 7 gives the commanded states. "Firmware" names the action; "Hardware" names what the new logic enforces
independently. Variant b rows apply in addition to variant a.

Table 7. Control sequence by state.

| State | Firmware | Hardware enforcement |
|---|---|---|
| Boot (setup) | Drive `CHG_ARM` LOW and `TRIP_CLR` HIGH before the SD probe and Ethernet. Read `TRIP_Q` = HIGH (power-up set, a self-test of the set path). Start kicking only from `loop()`. Clear the latch only in State 1 after 10 consecutive kick periods. `LIM_SEL` LOW. | EF_CHG off (latch set, CHG_ARM LOW). D-BT-EN follows pin 28 while VCHG-EF < 6 V. |
| Bring-up P0-P3 | Unchanged. `BT_BUS_ENABLE` HIGH in P0 passes the breaker because VCHG-EF is 0 V. | Breaker transparent. |
| Idle (State 1) | `CHG_ARM` LOW. Clear the latch once (pulse `TRIP_CLR` LOW for 1 ms) only if the trip line is HIGH. | EF_CHG off. |
| Run, discharge | `CHG_ARM` LOW unless a charge window is open. | Breaker transparent. |
| Regen brake | Not permitted in IC7 (section 4.4). If ever enabled: FC_BUS conducting first, then `BT_BUS_ENABLE` LOW, then `CHG_ARM` HIGH, then `REGEN_ENABLE` HIGH. | Breaker forces D-BT-EN off once VCHG-EF > 6 V even if the firmware keeps `BT_BUS_ENABLE` HIGH (fw v37 keeps it HIGH, ino:15361). |
| FC-charge window | `assertFcChargeEnable(true)` already drops BT_BUS and REGEN (ino:12743-12778). Add: verify `TRIP_Q` LOW and `CHG_PWR` HIGH, then `CHG_ARM` HIGH, then `FC_CHARGE_ENABLE` HIGH. Monitor `EF_ILM` and `EF_PG`. Variant b: `LIM_SEL` HIGH after `CHG_ARM`. | EF_CHG bounds the input at 1.36-1.66 A; breaker holds D-BT-EN off; OVP and BAL trips latch EF_CHG off. |
| Window close before an H-20 purge | `FC_CHARGE_ENABLE` LOW and `CHG_ARM` LOW together; wait for `CHG_PWR` HIGH; then `BT_BUS_ENABLE` HIGH. Variant b: `LIM_SEL` LOW. | Breaker releases only after VCHG-EF < 6 V (section 4.3 timing). |
| H-20 purge | No charge window (ruling 6). Battery on the bus. | - |
| Finish (State 3) | `CHG_ARM` LOW with `assertFcChargeEnable(false)`. | EF_CHG off. |
| State 99 | `CHG_ARM` LOW first, before the phase-0 bus switches. The phase-0 VBUS drain into the charger and the phase-1 V-MOT drain (ino:8299-8327) then end at EF_CHG; the drains must be re-designed or `CHG_ARM` held HIGH for their 10 ms each (section 8). Do not clear the latch. | EF_CHG off; latch untouched. |
| Teensy reset | - | Section 2.5: EF_CHG off, D-BT-EN off, limiter at 0 mV. |

## 4. Quantitative checks

### 4.1 Conduction loss at peak BT current

The peak BT current is the 16.46 A incident value (`facts_prior.md` section 9), which approaches the TPS61288 switch
limit of 12-17.1 A (SLVSFP3C section 7.5). Table 8 gives the added loss in the pack path.

Table 8. Added pack-path loss at 16.46 A.

| Element | Resistance | Drop | Loss |
|---|---|---|---|
| Variant a | No element in the pack path | 0 | 0 W |
| Variant b, Q_CHG at 25 C | 2.9 mOhm (4.5 V maximum) | 47.7 mV | 0.79 W |
| Variant b, R_SH | 2 mOhm | 32.9 mV | 0.54 W |
| Variant b, total at 25 C | 4.9 mOhm | 80.7 mV | 1.33 W |

The temperature coefficient of R_DS(on) is not extracted here (TODO(verify: SLPS531A normalized R_DS(on) figure)). In
vehicle service the per-channel current is about 3 A (`facts_prior.md` section 9), which gives 0.044 W in variant b.

### 4.2 SOA of the variant b limiter

The limiter holds the pack current at I_lim while the Ag105 drives VBT. The FET drop is
V_DS = V_VBT - V_pack - I_lim x R_SH. Two bounds apply.

1. **Ag105 CV holds (UNCONFIRMED with a blind sense).** V_VBT <= 8.365 V. At I_lim = 1.5 A: V_pack = 7.4 V gives
   V_DS = 0.96 V and 1.44 W; V_pack = 6.0 V (3.0 V/cell, below the 7.4 V operating floor but reachable on a drained
   pack) gives 2.36 V and 3.54 W.
2. **Ag105 CV does not hold.** VBT rises until CMP_OVP trips at 8.44-8.70 V. At 8.70 V and V_pack = 6.0 V the drop is
   2.70 V and 4.05 W, for the time the trip takes (8.5 ms filter plus about 13.5 us comparator delay, SBOS300C).

The DC thermal limit, not the SOA curve, binds. At 3.54 W with R_thetaJC 0.5 C/W, a 0.5 C/W interface and a 10 C/W
heatsink, the junction rise is 3.54 x 11.0 = 39 C. Without a heatsink, at R_thetaJA 62 C/W, the rise would be 219 C,
which is not acceptable. The DC SOA line at V_DS of about 1-3 V is read from SLPS531A Figure 4-10 only at
T_C = 25 C single pulse; a linear-mode (Spirito) stability check at these low current densities is BENCH, and an
enhanced-SOA "ASFET" class part would remove that uncertainty (the Nexperia datasheets could not be fetched; TODO).

### 4.3 Loop-breaker timing

The breaker must open D-BT-EN before the Ag105 produces output, and must release it fast enough after a window closes to
put the battery back on the bus before a purge.

1. **Open, FC window.** `FC_CHARGE_ENABLE` HIGH at t0. D-BC-FC conducts after t_D_ON = 8 ms typical and slews VCHG-IN at
   12 V/ms (`facts_prior.md` section 5, section 10 item 4). EF_CHG starts its own 0.61-0.71 V/ms ramp once its input
   passes the 2.53 V UVP (SLVSFC9C section 6.5). VCHG-EF passes 6.0 V at about t0 + 8.2 ms + 8.5 ms = t0 + 16.7 ms and
   11 V at about t0 + 24 ms. CMP_PWR reacts in about 12 us (SBOS300C section 6) and AND2 in nanoseconds; the RT1987
   EN-off delay is TODO(verify: RT1987 DS-00). The breaker therefore opens about 7 ms before the Ag105 can start, and
   the Ag105 start-up time (65-170 ms cold, `facts_prior.md` section 6) adds further margin. The firmware also drops
   BT_BUS 100 us before `FC_CHARGE_ENABLE` (ino:12761-12774), so the breaker is a backstop on this path.
2. **Release.** With EF_CHG off, VCHG-EF discharges through the Ag105 idle draw (18 mA maximum, Ag105 DS p.20), the
   4.7 kOhm bleeder and the 483 kOhm divider. With an Ag105 input capacitance C_in (TODO(verify: Silvertel); BENCH),
   the bleeder alone gives t = 4.7 kOhm x C_in x ln(16/6) = 4.6 ms per 1 uF. At C_in = 10 uF the bleeder-only bound is
   46 ms; with the Ag105 idle current (a constant-current approximation, typical value not given) it is
   10 uF x 10 V / 18 mA = 5.6 ms. D-BT-EN then needs t_D_ON = 8 ms. The release-to-battery time is therefore 14-54 ms
   plus one 20 ms `chargingControl()` period, against a purge duration of 100-140 ms that must be predicted
   (`facts_prior.md` section 7). The bleeder costs 54 mW during a window.
3. **Why the breaker senses VCHG-EF, not VCHG-IN.** VCHG-IN carries 20 uF (C-D8, C-D10) and the 88.7 kOhm R1-CHG/R2-CHG
   divider (`facts_board.md` section 4.4), a time constant of about 1.8 s; a breaker on VCHG-IN would hold the battery off
   the bus for about 1.7 s after every window. Sensing VCHG-EF also keeps the breaker correct if EF_CHG is off while
   D-BC-FC is on (no Ag105 power, no loop).

### 4.4 Timing against the regen burst and the Ag105 Bring-Up

The regen burst lasts 0.3-0.6 s, with a true pulse of 30-50 ms (`facts_prior.md` section 6). VCHG decays below the
RT1987 UVLO in 0.17-0.66 s of cruise (`facts_prior.md` section 10 item 1), so a regen event starts with VCHG near 0 V.
The only measured Bring-Up slope is 0.64 V/s (ML0227, BENCH, sense shorted), which needs about 11.7 s to pass a 7.67 V
pack. A cold Ag105 also needs 65-170 ms before output (`facts_prior.md` section 6). IC7 therefore delivers no regen
energy to the pack. An always-powered Ag105 would avoid the cold start, but with the breaker it would hold BT_BUS off
for all of Run, which is an FC-only bus across purges (`facts_firmware.md` section 5). Section 6 records HR1 as FAILS.

### 4.5 What a charge attempt does in variant a

This subsection traces a charge attempt from the evidence. The mechanism is UNCONFIRMED by a bench run with EF_CHG.

1. The Ag105 enters Bring-Up and ramps VCHG. With the sense shorted, the 10 % current exit condition is never met
   (`facts_ag105.md` section 3).
2. Once VCHG passes the pack voltage plus the D-BT-SQ drop, pack current rises at the Bring-Up slope divided by the loop
   resistance. The ML0227 bus-side slope was about 10.6 A/s (`facts_prior.md` section 4.1).
3. The Ag105 input current reaches I_LIM when the pack current reaches about
   eta x V_in x I_LIM / V_pack = 0.88 x 16.0 x 1.36 / 7.4 = 2.6 A (low-tolerance I_LIM, 16 V input).
4. EF_CHG blanks for about 1.8 ms and latches off (SLVSFC9C section 7.3.5.2).

The upper bound on pack current at any instant is set by the input limit. With eta <= 1 and the high-tolerance
I_LIM = 1.66 A: 16.0 V x 1.66 A / 7.4 V = 3.6 A, and 21.35 V x 1.66 A / 7.4 V = 4.8 A. Over the blanking interval the
added energy is negligible. A charge session therefore ends at the first eFuse trip, typically within about 0.3-0.5 s
of current onset at the ML0227 slope, unless the Ag105 reaches its 8.4 V CV first, which happens only on a nearly full
pack. The Ag105 MPPT input threshold could, in principle, throttle the module's input draw when the eFuse sags the input
(Ag105 DS p.10 says the module "adjusts the charge profile"); a circuit breaker does not sag the input before it trips,
so this mechanism is not available. That conclusion would change only with an active-current-limit eFuse whose power
dissipation the Ag105 then regulates against; that is UNCONFIRMED and is listed as a bench gate.

### 4.6 Inrush

EF_CHG adds no inrush upstream: VCHG-IN still slews at 12 V/ms behind D-BC-FC/D-BC-RG onto 20 uF, 0.24 A, as today.
Downstream, EF_CHG charges the Ag105 input capacitance at 0.61-0.71 V/ms, so I_inrush = C_in x 0.71 mA per uF (for
example 7.1 mA at 10 uF). No new switch closes onto VBT or VBUS in variant a.

### 4.7 Teensy supply continuity

Variant a never interrupts the pack-to-VBT connection, so the LM1084 and the Teensy stay on the pack in every state.
Objection 2 of the re-spin note does not apply. In variant b the only series element in the return is Q_CHG, whose
discharge direction conducts through the channel when the limiter runs and through the body diode when it does not.
The pack can therefore always supply VBT, at a cost of 0.8 V and up to 13 W at 16.46 A if the gate drive fails (single
fault S-b2 in section 5).

### 4.8 Reference shifts: V_batt, INA253, BQ29200

1. **Variant a.** No reference moves. V_batt still reads VBT = pack against PCB GND; the INA253s and the BQ29200 are
   unchanged.
2. **Variant b, discharge.** Pack- sits below PCB GND by I x 4.9 mOhm, 81 mV at 16.46 A. V_batt (VBT minus GND) reads
   V_pack - 81 mV. The INA253s are on the boost outputs and are unaffected.
3. **Variant b, limiting.** Pack- sits above GND by V_DS + I x R_SH, up to about 1-2.7 V (section 4.2). V_batt reads
   V_pack plus that drop and approaches `OV_BATT` (8.5 V) whenever VBT is near 8.365 V, whatever the pack voltage.
   `OV_BATT` would therefore latch on a correct, limited charge if the Ag105 CV is more than 1.6 % high; BENCH.
4. **Variant b, BQ29200.** X1 forces J-BL pin 3 off PCB GND and onto pack-. The BQ29200 GND is PCB GND (exposed pad),
   so its bottom-cell reading VC1 - GND becomes V_cell1 + V_drop. During limiting this exceeds the 4.35 V threshold at
   a true cell voltage of about 3.35 V. CMP_BAL would then trip falsely, so in variant b the BQ29200 path must be
   disconnected and the per-cell protection is lost during charging. A high-side form (variant b', P-channel limiter in
   the pack positive) keeps all references fixed; its parts are not selected in this dossier (TODO).

## 5. Single-fault table

Table 9 lists single faults. "Bound" names what limits the consequence. HR3 accepts a bounded single pulse per event.

Table 9. Single faults.

| ID | Fault | Consequence | Bound / detection |
|---|---|---|---|
| S-a1 | EF_CHG pass FET shorted | Charger powered whenever D-BC-FC or D-BC-RG conducts; input unbounded; ML0227 pack leg returns | Breaker still opens the loop. Pack current unbounded until the Ag105 UVLO or OVP; OVP cannot open a shorted eFuse. Detection: `EF_ILM` above I_LIM, `CHG_PWR` LOW with `CHG_ARM` LOW. Firmware must then hold FC_CHARGE and REGEN LOW (dual fault to fail). |
| S-a2 | EF_CHG fails to trip | As S-a1 while the window is open | Firmware G1/G2 on bus-side current; OVP latch removes EN (ineffective if the fault is in the breaker logic of the part). |
| S-a3 | AND3 output stuck HIGH | Trip latch cannot remove EF_CHG | Firmware `CHG_ARM` irrelevant; EF_CHG own breaker still trips; OVP/WDT ineffective. Detection: `EF_PG` HIGH with `CHG_ARM` LOW and a path open. |
| S-a4 | CMP_PWR stuck "not powered" (HIGH) | Breaker transparent; loop possible if firmware also fails | EF_CHG I_LIM bounds input to 1.66 A; pack and BT boost share it. Bounded but repeatable each window. Detection: `CHG_PWR` HIGH while `EF_PG` HIGH. |
| S-a5 | CMP_PWR stuck "powered" (LOW) | D-BT-EN held off permanently; battery cannot support the bus | Safe for the loop; bus collapses at the next FC purge or battery-only arm (UV_BUS). Detection: `CHG_PWR` LOW with EF_CHG off. |
| S-a6 | D-BT-EN shorted | Loop path closed regardless of breaker | EF_CHG I_LIM and the trip latch bound each event to one blanking interval; repeat on each window. Firmware cannot detect directly (bus-side I_batt with BT_BUS LOW). |
| S-a7 | D-BC-FC shorted | VCHG-IN always at VBUS | EF_CHG off unless armed; no effect while disarmed. |
| S-a8 | Trip latch stuck clear (Q# HIGH) | WDT/OVP set ignored by the latch | AND3.C still removes EN while the trip line is LOW; a pulsed WDO re-enables after t_RST. Detection: boot self-test (`TRIP_Q` must read HIGH at power-up). |
| S-a9 | TPS3431 dead (WDO high-Z) | No hang protection | Teensy hang with `CHG_ARM` HIGH leaves EF_CHG on, bounded by I_LIM and OVP. RTWDOG (section 8) covers it. Detection: State-98 forced-hang test. |
| S-a10 | CMP_OVP divider top open | OVP never trips | Firmware `OV_BATT`; CMP_BAL at 8.70 V after 2-4 s. Bottom open: input high, trips permanently (fail-safe). |
| S-a11 | 3V3 lost | All logic off | EF_CHG off by pull-down; D-BT-EN off by pull-down; Teensy itself is off. |
| S-a12 | Teensy hang, `CHG_ARM` HIGH | Window continues | WDO within 230 ms sets the latch; EF_CHG off. |
| S-a13 | Pack lead opens during a window | VBT fed only by the Ag105 through D-BT-SQ; Teensy powered by the charger | Ag105 output into LM1084 and BT boost, sense blind, bounded by I_LIM; CMP_OVP trips if VBT exceeds 8.57 V. Ag105 behaviour UNCONFIRMED (`facts_ag105.md` section 3.2). |
| S-b1 | Q_CHG shorted | Limiter lost | Reverts to variant a bounds. Detection: `PACK_I` above I_lim. |
| S-b2 | Q_CHG gate stuck LOW (op-amp output or gate resistor open) | Discharge through the body diode: 0.8 V, 13 W at 16.46 A | Thermal destruction of Q_CHG; V_batt reads low by 0.8 V and UV_BATT may latch. No hardware bound. |
| S-b3 | R_SH open | R_SH is in series with the whole pack return, so the pack is fully disconnected from PCB GND | Teensy browns out unless the Ag105 feeds VBT; no hardware bound. Severity high; R_SH must be a non-fusing element rated well above 16.46 A. |
| S-b4 | Reference switch stuck at I_lim | Charge allowed with Teensy off | EF_CHG is off with the Teensy off, so no charger power; benign. |

Two adversarial conclusions follow from Table 9. First, S-a1, S-a3 and S-a6 show that the HR3 argument rests on two
independent parts (breaker and EF_CHG); each single fault leaves the other, but S-a1 removes the only bound on the pack
leg itself. Second, variant b adds S-b2 and S-b3, which are new pack-path failure modes with no hardware bound; variant a
adds no element to the pack path and has none.

## 6. HR1-HR5 status

Table 10 gives the status of the hard requirements.

Table 10. HR status for IC7.

| HR | Variant a | Variant b |
|---|---|---|
| HR1 Regen | FAILS: every regen event starts with VCHG near 0 V and a 65-170 ms cold start; the only measured Bring-Up slope needs about 11.7 s to reach the pack; an always-powered Ag105 forces BT_BUS off for all of Run (section 4.4) | FAILS for the same reasons |
| HR2 FC charging | FAILS (PROVEN_CALC on the ML0227 slope; Ag105 Bring-Up exit UNCONFIRMED): each attempt ends at the EF_CHG trip at about 2.6 A pack current (section 4.5). The purge blocker of `facts_prior.md` section 7 also remains | BENCH: crude CC (Q_CHG) plus CV (Ag105 voltage loop, UNCONFIRMED with a blind sense) plus firmware termination on `PACK_I`; purge blocker remains; OV_BATT margin 1.6 % |
| HR3 No circular loop | PROVEN_CALC (conditional on the breaker hardware): the loop needs D-BT-EN conducting while VCHG-EF > 6 V, which the breaker forbids; single faults S-a4 and S-a6 are bounded by EF_CHG to one blanking interval per window | Same as a |
| HR4 No runaway | FAILS: input and pack current are bounded (3.6-4.8 A) but not regulated, and the Ag105 never terminates; "no unregulated path" is not met | FAILS strictly: the Ag105 CC loop is still blind; regulation comes from a linear FET and firmware termination; CV correctness UNCONFIRMED |
| HR5 Fail-safe inhibit | BENCH: EF_CHG defaults off with the Teensy unpowered, in reset or hung (Table 5); power-up is tripped; the Ag105 cannot start from stored settings without EF_CHG enabled. Bench: forced-hang test, reset pad states, latch self-test | BENCH: as a, plus the limiter defaults to a 0 mV (inhibit) reference |

`AG105_VBATN_ISOLATED` cannot honestly be set to 1 under IC7, because the declared hardware fact (Ag105 battery return
not tied to PCB GND, ino:5058-5062) remains false.

## 7. Rework on the manufactured board, parts and cost

### 7.1 Rework steps (variant a)

The steps below are a rework plan for review. Nothing is to be cut, fitted or flashed by this study.

1. Build a carrier board holding EF_CHG (QFN, needs a breakout), the logic, comparators, TPS3431 and passives. Mount it
   off-board near the Ag105, fed from J2 pins 01/02 (5V), 05/06 (3V3) and 03/04 (GND).
2. Cut the `VCHG-IN` connection to Ag105 pin 10 (VIN+ pad at (46.0, 61.94)). The pad is fed by 1.524 mm traces on both
   layers (`facts_board.md` section 4.1), so both traces must be cut next to the pad, and continuity from the pad to
   `VCHG-IN` must read open afterwards (BENCH). Run a flying lead from `VCHG-IN` (for example the via at (39.62, 34.54),
   `facts_board.md` section 4.4) to EF_CHG IN, and from EF_CHG OUT to the isolated VIN+ pad. The wire must carry
   1.66 A at 23 V.
3. Cut net `D-BT-EN` on the 0.254 mm top-layer segment from (66.294, 24.384) to (66.294, 29.718) (BRD signal
   `D-BT-EN`), which lies between D-BT-EN pad 5 and the via at (67.056, 30.48). Wire the Teensy side (via, or J1 pads
   39/40) to AND2_BRK.A and the pad side to AND2_BRK.Y. Confirm first that the 10 kOhm EN bodge resistor (OQ-7) sits on
   the pad side of the cut.
4. Fly-wire BQ29200 OUT (QFN pin 8, no copper today) to CMP_BAL through 200 kOhm.
5. Tap VBT for CMP_OVP at J-BT pin 1 or C1-BT, through the 590 kOhm resistor at the tap.
6. Tap the spare Teensy pins at the J1/J2 receptacle pads (Table 4; `facts_board.md` section 7.2).
7. The operator amends the IO CSV for pins 10, 16, 21, 23, 33, 34 and 35 before any firmware change.
8. Record the rework as a never-rotated bodge record (prior-study lesson 5).

### 7.2 Additional steps for variant b

1. Insert Q_CHG and R_SH in the pack negative lead of the harness, between pack- and J-BT pin 2, with Q_CHG on a
   heatsink.
2. Isolate J-BL pin 3 from GND. The pad is solid to both pours with no thermal relief, so the wire must instead be
   removed from J-BL pin 3 and re-terminated on pack- at the harness (X1), with the BQ29200 consequence of section 4.8
   item 4.
3. Build the limiter (OPA197 on VBT), reference switch and current amplifier on the carrier board.

### 7.3 Parts list and cost

Table 11 lists the parts. Distributor prices were not retrieved; every cost is TODO(verify: distributor).

Table 11. Parts list.

| Qty | Part | Variant | Cost |
|---|---|---|---|
| 1 | TI TPS259474LRPW eFuse + QFN breakout | a | TODO(verify) |
| 1 | TI TPS3431 watchdog | a | TODO(verify) |
| 2 | TI TLV3011B comparator (OVP, BAL) | a | TODO(verify) |
| 1 | TI TLV3012B comparator (CMP_PWR) | a | TODO(verify) |
| 1 | TI SN74LVC1G74 flip-flop | a | TODO(verify) |
| 1 | TI SN74LVC1G11 3-input AND | a | TODO(verify) |
| 1 | TI SN74LVC1G08 2-input AND | a | TODO(verify) |
| 1 | BZT52C4V7 zener | a | TODO(verify) |
| ~20 | 0.1 % and 1 % resistors, 100 nF / 1 uF / 2.2 nF / 3300 pF capacitors, carrier board, wire | a | TODO(verify) |
| 1 | TI CSD18535KCS + heatsink <= 10 C/W | b | TODO(verify) |
| 1 | 2 mOhm shunt | b | TODO(verify) |
| 1 | OPA197 or OPA2197, reference switch, current amplifier | b | TODO(verify) |

## 8. Firmware, telemetry and HIL impact

The firmware changes below are a list for a later orchestrated round, not changes made here.

1. **Pins.** New defines for Table 4 after the CSV amendment; `setup()` drives `CHG_ARM` LOW and `TRIP_CLR` HIGH in the
   early block (ino:6709-6715).
2. **Watchdog kick.** Toggle `WDT_KICK` once per loop after `detectFaults()`. Known blocking paths (EEPROM commit up to
   about 1.2 s, SdFat close, `Ethernet.begin()`) must not run while `CHG_ARM` is HIGH, or they will trip the latch
   (`facts_prior.md` section 10 item 7). The RTWDOG/WDOG1 (ruling 5) is still required; WDOG1_B on pin 20 could be
   OR-ed into the trip line.
3. **Latch management.** Boot self-test (`TRIP_Q` HIGH at power-up), clear only in Idle, never in State 99; a new
   fault code for an unexpected `TRIP_Q` HIGH during a window.
4. **Charge-path chokepoint.** `assertFcChargeEnable()` gains `CHG_ARM` and the `TRIP_Q`/`CHG_PWR` preconditions;
   window close waits for `CHG_PWR` HIGH before re-closing BT_BUS.
5. **Regen branch.** The fw v37 regen branch keeps `BT_BUS_ENABLE` HIGH (ino:15361). Under the breaker that is a
   hardware/firmware disagreement; the branch must drop BT_BUS and require a conducting FC_BUS, or regen stays off
   (the IC7 verdict).
6. **State 99 drains.** The phase-0 and phase-1 drains into the charger (ino:8299-8327) end at EF_CHG when `CHG_ARM`
   is LOW. Either the drains move to another sink or `CHG_ARM` stays HIGH for those 10 ms phases; the second option
   powers a blind charger during a fault and is not recommended.
7. **New consistency faults.** `CHG_PWR` LOW with `CHG_ARM` LOW (S-a1); `EF_PG` HIGH with `CHG_ARM` LOW (S-a3);
   `CHG_PWR` HIGH while `EF_PG` HIGH (S-a4).
8. **G5 flag.** `AG105_VBATN_ISOLATED` stays 0. A separate flag, for example `CHG_INPUT_BOUNDED`, would describe IC7
   truthfully; it should not unlock charging, because HR4 fails.
9. **Telemetry.** `switch_state` has 2 spare bits (`facts_firmware.md` section 7): `CHG_ARM` and `TRIP_Q` fit without
   a layout change. `EF_ILM` (and `PACK_I` in variant b) need the protocol v5 extension already proposed; that needs the
   `protocol-bump` procedure.
10. **HIL.** The simple plant needs EF_CHG state, the trip latch, the breaker on the BT bus switch and a VCHG-EF node;
    the hi-fi `BT_SEQ` semantics mismatch (`facts_firmware.md` section 9) is independent but should be fixed in the
    same round. Tests: the breaker truth table, the latch power-up and both-LOW cases, and the window-close wait.

## 9. Open questions and bench gates

The following items remain open. Each would change a conclusion above if it came out differently.

1. **B-IC7-1, Ag105 Bring-Up exit with a blind sense.** Does the Bring-Up ramp end at the 8.4 V CV setting, at another
   voltage, or not at all? This decides whether variant b can charge (section 4.2) and whether variant a ever reaches CV.
   Source: TODO(verify: Silvertel); bench with a current-limited supply, not the board.
2. **B-IC7-2, Ag105 input capacitance and idle draw.** Needed for the breaker release time (section 4.3).
3. **B-IC7-3, MPPT input regulation under a current-limited source.** If the Ag105 regulates its input voltage at the
   reg 0x02 threshold when the source sags, an active-current-limit eFuse could become a crude input-power regulator.
   This is UNCONFIRMED and would revisit section 4.5.
4. **B-IC7-4, RT1987 EN-to-off delay** (D-BT-EN). TODO(verify: RT1987 DS-00).
5. **B-IC7-5, OQ-7.** Which RT1987 EN nets carry the 10 kOhm pull-down, and on which side of the planned cut.
6. **B-IC7-6, CMP_OVP reference.** Measure the fitted TLV3011B reference and trim the divider; the lower bound is 75 mV
   above end-of-charge VBT.
7. **B-IC7-7, EF_CHG rendered-table values.** EN/UVLO and OVLO thresholds, fast-trip currents, V_ITIMER and the timing
   table were read from a column-scrambled text extraction of SLVSFC9C; read them from the rendered pages.
8. **B-IC7-8, TPS3431 t_RST and start-up delay.** Read from the rendered SNVSB66A section 6.6.
9. **B-IC7-9, V-MOT spike amplitude above 28 V.** EF_CHG absolute maximum (section 2.1).
10. **B-IC7-10, forced-hang test** (`T-W-01` class): stop the kick with `CHG_ARM` HIGH on a dummy load; EF_CHG must be off
    within 230 ms.
11. **B-IC7-11, variant b limiter stability and linear-mode SOA** of the fitted FET; heatsink temperature at 3.5 W.
12. **B-IC7-12, pack data.** Maximum charge current and protection board (`facts_prior.md` section 9) bound the 3.6-4.8 A
    instantaneous pack current of variant a.
13. **Charger-independent gates carried over:** S0-R3/T-E-03, M-R1, M-R2, T-E-01, T-W-01 (`facts_prior.md` section 11).

## 10. Disposition

This dossier has shown that external bounding alone cannot make the Ag105 a working charger on this board. Variant a
converts the ML0227 runaway into a bounded, latched, single-interval event and breaks the circulating loop in hardware,
but it delivers no useful charge and no regen harvest. Variant b can deliver a crude limited charge only if an
UNCONFIRMED Ag105 behaviour holds, at the cost of a heatsinked linear FET, two new unbounded pack-path faults, and the
loss of the BQ29200 per-cell protection during charging. IC7 is therefore not a candidate. Its variant-a layers
(EF_CHG with OVLO, the VCHG-EF-keyed loop breaker, the latched OVP and BQ29200 trips, the external watchdog, and the
3-input enable with the flip-flop both-LOW guard) are recommended as the common safety-layer set X4 for whichever
isolation concept survives review.
