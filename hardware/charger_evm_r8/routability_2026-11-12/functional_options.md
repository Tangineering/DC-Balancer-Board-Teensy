# CR functional options to reduce routing demand (charger EVM r8)

## Answer first

- **Only one change is sized to the shortfall on its own.** Replacing the 13 LVC logic packages with one programmable logic device (P6) frees about 57 of the 199 connections and about 20 % of the minimum-wire demand. The router leaves 22 to 37 connections open.
- **A bundle of low-loss changes frees about 29 connections.** The bundle is P5, P1, P11, P7, P4' and P3a. It costs about 7 % of the wire demand (147 mm of 2024 mm minimum-spanning length, Manhattan). Whether that closes the board is UNVERIFIED and needs a route-race test.
- **Three of the four always-open nets are geometric, not functional.** /N_DVDT and /N_OV fight for the single +x-pocket lane. /RFC_OFF_J and /BT_OK are long crossings between tab Y and J101 or the comparator row. A functional change frees /BT_OK only with P8 and /N_OV only with P9. Both fail an operator ruling or a hardware protection.
- **One non-functional finding is worth more than most functional ones.** U118 sits at (47.3, 63.5), far from U106/U110/U116 on tab Y. U118 back on tab Y cuts 87 mm of minimum wire (FCCN 68 to 44 mm, H1R 53 to 11 mm, QQF 48 to 9 mm). A.8 already assigns U118 to tab Y top. That fix is a placement change and belongs to the placement owner.

Coordinates are in the KiCad frame of `cr/cr.kicad_pcb` (y down). The design doc frame is mirrored in y. Connection counts come from the adopted placement (variant A). I counted them by editing the netlist. The method is in section 6.

## 1. Constraints that bound every proposal

- **R1 (operator ruling, design doc 0.1):** regen harvesting and FC charging are both hard requirements.
- **R3':** the charger may stay powered through Run only with a Teensy hard inhibit **plus a hardware comparator backstop**. The TLV3012 comparators therefore cannot move to firmware.
- **No spare Teensy pins.** B.8/A.4 leave only pins 2 and 8, and both sit on encoder nets. A firmware takeover of any CR function needs a pin that another proposal frees first: pin 22 (P4'), pin 10 (P3b), or pins 16, 17 and 23 (P8).
- **DNP tiers.** Tiers 1-3 are gone, and the netlist has no DNP part left. The only "tier 4" candidate is R137 (0 Ω, P11).

## 2. Net-by-net picture (adopted placement, r2_A seeds 1-4)

The count is the number of seeds (of 4) at which the net stayed open. MST is the Manhattan minimum spanning length.

| Net | Open | Circuit and function | Geometry |
|---|---|---|---|
| /BT_OK | 4 | U104 OUT (INA253 BT current < 19.75 mV) to U107 A (Y1, the FC-window loop barrier) and R128 to F16 (pin 23 readback) | comparator row (33.4, 62.5) to tab Y (32.7, 31.2): 32 mm vertical across the whole board |
| /N_DVDT | 4 | U101.9 dVdT to C101 22 nF (eFuse soft-start, >= 10 nF required) | 3.6 mm, in the +x pocket. It loses the only F.Cu lane to /N_OV and /N_UV, and R101 sits between U101.10 and C101 |
| /N_OV | 4 | U101.7 OVP to the R103/R104 divider (OVP 23.12 V) | R104 is on B.Cu at (39.0, 37.2). The net competes with /N_UV (R102 to R103) for the same lane |
| /RFC_OFF_J | 4 | R132 100 Ω to J101.10. RFC_OFF = FCCN OR H1R, which drives EIB U201 ch3 and Q202 (the FC clamp leg) | R132 on the tab Y bottom (24.8, 29.3) to J101 (42.6, 54.4): 43 mm |
| /Y1, /FCC_ON, /H1R | 3 | H2c chain: U107 to U108; U120 to U108; U118A to U106 | U108 is in the interior (34.8, 45), U107 is on tab Y, U120 is in the comparator row, and U118 is at the far +x edge |
| /SCL | 3 | J1.7 to W7.1, an MB-to-EVM I2C pass-through with no CR function | 22 mm across the centre, through the D-35 zone (J1.7 is exempt) |
| /RGN, /N_FNP | 3 | T4 tap R121 (tab X) to the U121 divider; U120 IN+ divider | tab X to the comparator row and the divider strip |
| /J3V3_1, /CE_DRV_J | 3 | EIB 3V3 feed R176 to J101.1; R130 to J101.5 | the resistors sit on tab Y (20-31, 28-32), 28-38 mm from J101 |
| /BT_CURR, /BTOK_RB | 3 | T8 INA253 input to R140/R144; R128 to F16 readback | comparator row to the low row and to tab X |
| /QQF, /QQ, /FCCN | 1-2 | the QUAL one-shot gating (U118B) | FCCN is the longest signal net (68 mm), because U118 is mis-placed |

**Pattern.** Most open nets are long links between three clusters: the comparator row (y about 59-64), the tab Y gate cluster (y about 27-33), and J101 and the tab X taps (x 38-64). The +x pocket is a local lane defect. The /3V3 rail alone is 56 connections and 181 mm of minimum wire; it took 41 vias in the best run.

## 3. Ranked proposals

The rank is connections freed per unit of functional loss. Δconn is the change against the 199 connections, and Δwire is the change in minimum wire length.

| Rank | ID | Change | Δconn | Δwire | Open nets freed | Functional / protection loss |
|---|---|---|---|---|---|---|
| 1 | P11 | R137 deleted; U107.6 tied to /3V3 | -1 | -5 mm | /FCI_OK | none: the U117 option is gone, so R137 is a 0 Ω jumper |
| 2 | P5 | I2C and TS pass-through taken off the CR: W6/W7 land at J1.7/J1.8/J1.13, or the EVM leads land on the MB | -3 | -52 mm | /SCL (3/4), /SDA, /TS_EXT | no circuit change; mechanical and lead-dressing change only |
| 3 | P1 | one 200 Ω EIB 3V3 feed: R177 deleted, J101.2 not connected (or joined to J101.1 at the pads) | -2 | -34 mm | /J3V3_2 | redundancy of the EIB feed (availability only; the loss of the feed is fail-safe) |
| 4 | P7 | 13 LVC packages consolidated into about 7 (LVC11A, 2 x LVC08A, LVC32A, LVC2G14) | -13 | -20 mm | none named (/3V3 56 to 43) | none; more gates share one die |
| 5 | P6 | all 13 LVC packages replaced by one programmable logic device | -57 (SPLD with the monostables kept: -41) | -396 mm (-241) | /ARM_OK, /QQF, /H1R, /H1Q, /W, /Y1 and 13 internal nets | none in principle; high re-verification load |
| 6 | P4' | IMON readback deleted: R105, R129, C129, F18, F19 removed; IMON left floating | -4 | -42 mm | /N_IMON, /CHG_IIN; may relieve the pocket | an independent analog charger-input current reading; firmware checks only |
| 7 | P3a | the U111 one-shot replaced by a 3-input AND QQF = QUAL·FCCN·P5N | -5 | about -60 mm | /QQ | the hardware time limit on the QUAL release |
| 8 | P3b | QUAL path deleted (U111, U105, R123, R147, R150, C150, F11, U118B, U110B) | -17 | -209 mm | /QQF, /QUAL, /QUAL_TAP | the Run-entry proof of the ILIM release chain |
| 9 | P2 | CR ribbon series resistors deleted (R130 only: -1; all four: -4) | -1 / -4 | ~0 / -57 mm | /CE_DRV_J; /RFC_OFF_J by name only | ribbon damping; short-current limit of the LVC outputs (all-four variant) |
| 10 | P10 | pack-OV term deleted (U122, U123, R178, R179, D108, F08) | -12 | -48 mm | /T22_BAL | **hardware protection becomes firmware-only** |
| 11 | P9 | eFuse OVP pin to GND (R104 deleted) | -2 | -12 mm | /N_OV (always-open) | **hardware OVP moves from 23.12 V to 34.3 V** |
| 12 | P8 | regen-only CR: the FC-window permit (H2c) deleted | -50 | -423 mm | /BT_OK (always-open) and 10 sometimes-open nets | **violates R1** (FC charging is a hard requirement) |

**Bundles.** The low-loss bundle is P11 + P5 + P1 + P7 + P4' + P3a. It frees -29 connections, about -150 mm of wire, and the names /SCL, /SDA, /TS_EXT, /J3V3_2, /N_IMON, /CHG_IIN, /FCI_OK and /QQ. The script computed -24 connections and -147 mm without P3a; I added P3a by hand. The P6 route frees -57 connections and -396 mm. P6 includes the P7 and P11 gains, so do not add them to P6.

## 4. Proposal details

### 4.1 P11: R137 deleted (tier 4)
- **What changes:** Y1 = BT_OK·X·FCI_OK already has FCI_OK held HIGH through a 0 Ω resistor since tier 3. Tie U107.6 straight to /3V3.
- **Function lost:** none. Re-fitting U117 later needs a re-spin, but tier 3 already removed U117 itself.
- **Design-doc rows to change:** B.1 (FCI_OK row), B.2 (U117 row), B.8 (R137), E (R137), D-31 (tier 4).

### 4.2 P5: W6/W7 off the CR
- **What changes:** /SCL, /SDA and /TS_EXT only carry MB J1 pins to the EVM leads; no CR part uses them.
- **Option a:** move the W7/W6 pads next to J1.7, J1.8 and J1.13.
- **Option b:** land the EVM leads at the MB (the Ag105 footprint pads).
- **Routing effect:** either option removes three centre crossings and two escapes inside the D-35 zone (J1.7/J1.8 are exempt pins today).
- **Function lost:** none. The W7 GND conductor must keep a CR or MB GND point, and A.6 single-point bonding must be re-checked. Mechanical feasibility next to the header posts is UNVERIFIED.
- **Design-doc rows to change:** A.8 (W6/W7 coordinates are fixed, D-08), A.3/A.5 (lead routing and lengths, 400 kHz I2C lead length), A.8 routing note r5 (SCL/SDA on L3).

### 4.3 P1: single EIB 3V3 feed
- **What changes:** H.20 already gives 3.09 V with one conductor open. One feed is therefore enough electrically.
- **Function lost:** redundancy. A lost feed is fail-safe (B.6 row "3V3 lost on the EIB": /CE HIGH, HIZ and the FC clamp) and is detected through FR-08(b). The loss is availability, not protection.
- **Variant:** the joined-pads form keeps both ribbon conductors through one R176. It frees 1 connection instead of 2.
- **Design-doc rows to change:** A.3 W5 pin table (pin 2), B.6 U201 VCC, H.20, the B.6 ribbon-short row (2-3), T-C-05 ("one W5 3V3 conductor open"), B.8 and E (R177).

### 4.4 P7: standard-logic consolidation
- **Saving:** -13 connections, almost all on /3V3 (one VCC pin and one decoupler per removed package).
- **Candidate parts (each existence and package TODO(verify: TI)):**
  - U107, U108 and U109 (3 x 1G11) become one SN74LVC11A.
  - U114, U116, U118 and U122 (7 ANDs) become two SN74LVC08A.
  - U106 and U110 become one SN74LVC32A.
  - U105 (one section used) and U123 become one SN74LVC2G14.
- **Placement side effect:** gate pairs become intra-package, and U118's gates move into a tab Y package. That move also yields the 87 mm placement gain.
- **Cost:** the A.8/H.23(e2) tab Y area booking must be redone. Small QFN-14 packages (about 3.5 x 3.5 mm) keep the area about neutral (UNVERIFIED).
- **Protection impact:** none functional. One die now carries more terms; for example, CE_DRV and ARM_OK' share a die. B.7 must be re-read, but the Ioff and power-up behaviour are LVC-family properties and do not change.
- **Design-doc rows to change:** B.3 table, B.8 pin tables, E, A.8 tab Y list, H.23(e2), D-03 footprint table.

### 4.5 P6: one programmable logic device
- **Device size:** about 12 inputs (H1, UVB, BT_OK, BTB_OFF, FCCN, FCC_ON, RGN_ON, N_BAL as a Schmitt input, CHG_ARM, QUAL, FCCEIL, HB) and 4 outputs (CE_DRV, ILIM_REL, RFC_OFF, H2c readback).
- **Variant (a), GreenPAK-class:** about 20 pins, with internal delay blocks that also absorb U111/U113 and their RC parts. This variant frees -57 connections.
- **Variant (b), non-volatile SPLD (22V10-class):** the RC monostables stay external. This variant frees -41 connections.
- **Protection:** stays hardware; no software runs. However, the B.7 and B.1 fail-safe arguments rest on LVC facts that a PLD must re-prove:
  - glitch-free power-up (SCES586E) and outputs during the configuration load: UNVERIFIED for any candidate;
  - **Ioff:** B.7 says that LVC Ioff blocks back-feed from Teensy-driven inputs when T6 opens. A PLD with clamp diodes to VDD back-powers the CR rail through CHG_ARM and FCCEIL, which have no series resistor. This is a likely real hazard and must be checked;
  - one-shot timing from an internal oscillator instead of RC (variant a), so tw_QQ and tw_HB (H.17) must be re-derived;
  - configuration integrity (NVM), and a programming step in the build.
- **Firmware dependency:** none, if the truth table is preserved bit-exact. T-D-01 and T-C-06 must run again.
- **Design-doc rows to change:** all of B.1 (sequential elements), B.3, B.7, B.8, E, H.17, A.8 tab Y, and the T-D/T-C test rows.

### 4.6 P4': IMON readback deleted
- **Datasheet basis:** SLVSE94G pin table, IMON: "If unused, leave this pin floating" (`references/Datasheets/tps2663.pdf`). R105 can therefore go as well.
- **Pocket relief:** R105 is in the +x pocket at (44.8, 34.9). The HANDOFF relief for the /N_UV, /N_OV and /N_DVDT lane needs R105 0.3 mm and R101 0.6 mm in +y. With the R105 slot freed, P4' may free the two always-open pocket nets. This is UNVERIFIED and needs a routing run.
- **Function lost:** CHG_IIN (pin 22) is the I2C-independent charger-input current. Without it:
  - FR-11 (the charger drawing more than the FC supplies) must use the I2C IBUS ADC;
  - T10 proof (c) has to use its "or the IBUS ADC" branch;
  - telemetry `chg_iin_ma` and `chg_e_in_mj`, the G2 bench guard P_chg_in, and T-B-14 calibration lose their source.
- **Protection impact:** these are firmware protections, weakened by depending on I2C (slower, and the bus may be the failed item). The eFuse limits stay unchanged. Pin 22 becomes free.
- **Variant:** move R129/C129 to the MB J2.09 joint, as was done for R170/R171. This variant frees -2 connections with no function loss, but C129 needs an MB GND that breaks the T17r CR-only shield bond (A.6).
- **Design-doc rows to change:** B.4 (R105/C105, R129/C129 rows), A.4 T17/T17r, G.2 FR-11, T10, telemetry, H.5 IMON row, T-B-14.

### 4.7 P3a and P3b: QUAL one-shot
- **Basis for P3a:** a frozen MCU already loses ARM_OK within tw_HB, and ILIM_REL = ILIM_PRE·ARM_OK', so U113 covers the hang case of U111's time limit. P3a keeps the P5N mask (QUAL with P5 HIGH must stay converter-off; ruling R3: the bus never feeds the charger) and drops only the one-shot.
- **What P3a loses:** a QUAL conductor or pin stuck HIGH while the MCU runs now holds ILIM released (FCC LOW, P5 LOW). /CE HIGH and EN_CHG = 0 still bar charging, and FR-08(a) sees pin 33 HIGH. A hardware time bound therefore becomes a firmware-detected fault. The P5-fall retrigger quirk also goes. The net gain is only -5, because a 1G11 must be added.
- **What P3b loses:** the r3-4 Run-entry proof of the ILIM release chain (finding u203-stuck-held-latent-no-entry-test reopens). It also loses the detection of EVM R23 open (B.6) and possibly the charger's pin read of the regen clamp at qualification (design doc F.2 "regen clamp read by the IC"; T-B-07 is unresolved). P3b also removes U105, which clears the D-35 interim exemption of U105.5/P5N, and it frees pin 10.
- **Firmware dependency:** the T1 step machine, QQ_est in FR-08, TW_QQ_MAX, FR-04/I-5, T-D-13.
- **Design-doc rows to change:** B.1 (U111, QQF equations and truth table), B.3, B.7, H.17, A.4 T10, and r3-4 in 0.3.

### 4.8 P2: ribbon series resistors
- **R130 deleted:** benign. Conductor 5 neighbours conductor 4 (STAT through R275 1 kΩ) and the key position. The saving is 1 connection.
- **R131A, R131B and R132 deleted:** a ribbon pair short (8-9 and 9-10, where 9 is GND) then drives U114 or U106 outputs straight into GND. The LVC absolute-maximum output current is about ±50 mA, TODO(verify: SCES198N/SCES201N). U114 also drives CE_DRV, so the failure direction of an overstressed die is unknown. Deleting R131A/B also ties ILIM_REL_A and ILIM_REL_B together, which removes the conductor independence.
- **Routing effect:** /RFC_OFF_J disappears by name, but its copper demand moves onto /RFC_OFF.
- **Recommendation:** delete R130 only.
- **Design-doc rows to change:** B.3 ribbon-driver paragraph, the B.6 ribbon-short row, A.3.

### 4.9 P9, P10 and P8: high-loss options
- **P9:** with OVP to GND, the TPS26630 uses its factory V(IN_SYS_OVP) of 34.3 V (SLVSE94G, OVP pin table row and the overvoltage section of 8.3). That is above the BQ25798 24 V recommended maximum and its 25.2-26.2 V VBUS_OVP. The 23.12 V hardware cut-off is lost, and no firmware path replaces it at the needed speed. **Not recommended.** It frees the always-open /N_OV.
- **P10:** OVN is the only fixed pack-OV backstop against VREG corruption (finding vreg-corruption-no-fixed-pack-ovp). Deleting it leaves FR-46 read-back and OV_BATT 8.5 V, so the protection becomes **firmware-only. Not recommended.**
- **P8:** deletes U104, U107, U108, U115, U120, their networks, the T3/T8/T9/T11/T14/T15 taps and readbacks. It is the largest single saving besides P6, and the current firmware already ships `FC_CHARGE_ALLOWED 0`. It **contradicts R1** and the 2026-11-08 ruling (EMS-requested charging between purges). It frees Teensy pins 16, 17 and 23. **List it only as an operator fallback.**

## 5. Options considered and not ranked

- **Quad comparator plus a shared reference in place of the seven TLV3012s:** it would save about 8 /3V3 connections. It loses the per-comparator POR-LOW behaviour (B.7) and adds a common-mode reference failure. The comparators are also spread along the A.8 analog band, so a quad lengthens the divider nets.
- **Comparators or UVB moved to Teensy firmware:** R3' forbids it, and no pins are free. UVB also acts in microseconds against the purge sag (R6).
- **J101 pin reassignment:** J101 rows are only 1.27 mm apart, and almost every J101 net heads toward lower y. The gain would be a few millimetres. The change would reopen the r5 "complete" adjacent-pair fault table and re-spin the finished EIB.
- **J1 reassignment:** not possible. The MB copper fixes the Teensy pins on J1.
- **Tap series resistors moved to the MB joints (as R170/R171):** each would save 1 connection. However, the A.8 pad-bridge analysis (F05-F17) relies on the resistor being at the CR pad.

## 6. Method and unverified items

- **Pad positions:** from `cr/cr.kicad_pcb` via pcbnew. The netlist matches `cr/cr.net` (199 signal connections, /GND and the VCHG* pours excluded).
- **Proposal effects:** applied as netlist edits. "Δwire" is the change in Manhattan MST length, a demand proxy, not a routed result. P6's device position is approximated at U106, and the decoupler-to-IC mapping is the nearest /3V3 capacitor.
- **Open frequencies:** from `RACE/cr/r2_A/ref/seeds/s1-s4/route_report.md`.
- **UNVERIFIED:**
  - that any bundle closes the board (it needs a route-race run with the edited netlist);
  - P4' pocket relief;
  - existence and packages of the P7 parts;
  - PLD power-up, Ioff and timing behaviour;
  - P5 mechanics;
  - LVC output short-current limits;
  - the charger's ILIM pin-read semantics at qualification (T-B-07).
- **Next step:** the U118 tab Y placement (87 mm) and the R130/R131/R132/R176/R177 positions are placement items. Test them first, together with P5 + P1 + P11, because those carry no functional loss.
