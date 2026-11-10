# EIB merged onto the carrier: effect on the round-3 fail-safe arguments

Round 4 work note. Subject: the BQ25798EVM path that replaces the Silvertel Ag105 (MB designator CHG) on motherboard rev
20260622, design document `docs/charger_bq25798_wiring_design_2026-11-05.md` revision r6 (the **design**). This note decides
what happens to each EVM-interface-board (EIB) fail-safe argument if the EIB circuit moves onto the carrier (CR). Numbers come
from `work/eib_merge_calc.py` (output `work/eib_merge_calc_out.txt`, stdlib Python, run with `python -I`), from the design
sections cited, and from the vector EVM geometry in `work/evm_geometry.md` (Table 1). Section 10 lists every assumed value and
the measurement that replaces it.

## 1. Scope, terms and verdict

### 1.1 Question and geometries

The **merged design (MD)** places the B.6 EIB parts (U201-U204, Q201-Q203, R250-R275, C201-C205) on the CR, in the sideways
extension that the round-4 operator change permits. The W5 ribbon, J101, J201, R176 and R177 are deleted. CE_DRV, ILIM_REL_A,
ILIM_REL_B, RFC_OFF, ILIM_SENSE, CE_SENSE and STAT become CR traces. The E-leads E1-E8 then run from a pad row on the CR edge to
the A.5 EVM points. Two geometries are analysed:

- **G1:** the EVM is mounted on or directly beside the CR; CR-edge-to-EVM-pin distance 10-60 mm.
- **G2:** the EVM stays off-board; CR-edge-to-EVM-pin distance 0.10-0.30 m.

Four verdict terms are used, each with one meaning:

- **holds as is:** the round-3 argument and its proof apply without change.
- **holds with a stated change:** the argument applies after the named change to parts, layout or wording.
- **needs re-proof:** the argument rests on a premise the merge removes; the named analysis or test must be redone.
- **retires:** the hazard the argument covered no longer exists.

Three lead groups recur. The **ILIM group** is E2, E3 and E4: all three land on the ILIM_HIZ node at the EVM end, because EVM
R21 is a 0 ohm link (EM3). The **/CE group** is E5 and E6. The **island** is a separate AGND copper area under the EIB section
of the CR (section 3.5).

### 1.2 Verdict

**G1: the merge is acceptable under the conditions of section 7.** Every round-3 argument for an open conductor, an open
part or a dead driver holds, because each one rests on circuit topology that the merge does not change. The W5 ribbon, its
adjacent-short list, J101/J201, R176/R177, the EIB-only 3V3-loss row and T-C-13 retire. The ground scheme holds only with the
island and R273 (section 3.5). The computed pickup on the length-critical leads stays below a 10 % share of each margin at
10-60 mm (section 6). Confidence: high for the topology arguments; medium for the pickup figures, which use assumed loop
areas and edge times until T-C-16 measures them.

**G2: a direct merge is not acceptable.** The open-conductor arguments still hold, but the r1-2 premise inverts: round 3 put
the switches at the EVM pins and ran 3.3 V logic through series resistors over the long distance, while the merge exports the
unbuffered ILIM_HIZ node, REGN, /CE and STAT over 0.10-0.30 m. A single E-bundle short E1 to the ILIM group removes the hardware
input-current clamp undetected (section 3.6). A crush onto a VCHG-IN or V-MOT conductor drives ILIM_HIZ directly. A floating
E4 or E6 after a lead-off can chatter below the FR-08 persistence windows (2 ms and 1 ms) and hide the lead-off (section
3.3). A re-proof needs segregated shielded cables, EVM-end parts and comparator-input filters (section 8). Those EVM-end parts
re-create the EIB, so **for G2 the round-3 split (EIB at the EVM pins, W5 ribbon to the CR) stays the design.** Confidence:
high that the premise inverts; medium on the severity of each new single fault, which depends on the unverified BQ25798 REGN
current limit and pin absolute maxima (section 10).

## 2. What the merge moves

Table 1 shows which conductors carry the long distance in each arrangement.

**Table 1. Conductor exposure, r6 against the merged design**

| Conductor class | r6 (EIB at the EVM) | MD-G1 | MD-G2 |
|---|---|---|---|
| Logic commands CE_DRV, ILIM_REL_A/B, RFC_OFF | 0.30 m ribbon; 100 ohm source (R130-R132), 1 kOhm series and 47 kOhm pull-down at the receiver | CR traces | CR traces |
| 3V3 to the EIB parts | two ribbon conductors through R176/R177 200 ohm | CR rail (R175 68 ohm at T6) | CR rail |
| Readbacks ILIM_SENSE, CE_SENSE | ribbon through R265/R264 470 ohm | CR traces | CR traces |
| ILIM_HIZ node (E2, E3, E4) | 25-35 mm separate leads at the EVM | 10-60 mm | 100-300 mm |
| REGN (E1) | 85-90 mm (JP12) | 10-90 mm (section 6) | 100-300 mm |
| /CE (E5, E6) | 60-65 mm | 10-60 mm | 100-300 mm |
| STAT (E7) | 40 mm, then the ribbon through R275 | 10-60 mm, R275 at the CR pad | 100-300 mm |
| AGND reference (E8) | 20 mm | 10-60 mm | 100-300 mm |

The EVM points cluster in two places (`evm_geometry.md` Table 1; calc section 1). TP49, TP33, JP21 pin 1, JP14 pin 2 and TP38
lie 5.5-22.9 mm from the EVM right edge. TP36, JP17 pin 1 and JP12 pin 1 lie 13.7-26.8 mm from the bottom edge and 33-50 mm
from the right edge. The nearest power-stage copper (L2, U1, the C19-C21/C29-C31/C37-C40 banks and the SW test points) is
12.0 mm from TP38, 13.5 mm from JP17 pin 1 and 17-33 mm from the other points. Note: JP21 pin 1 (ILIM_HIZ) is the lower post at
(75.312, 64.769) EVM mm; the A.5 pixel coordinate names the AGND post (`evm_geometry.md` 7.2).

## 3. The fail-safe arguments

### 3.1 (a) Two series switches for the ILIM release (r1-2 eib-wireoff-releases-converter; r2 evm-jp14-feed-joint-floating)

The r1-2 argument has two parts. First, a release needs both Q203 on (feed from REGN through R255) and Q201 off (hold-down
released), and each switch has its own driver and conductor. Second, the EVM has no other path from REGN to ILIM_HIZ (EM3: R21
is a 0 ohm link, JP14 pin 1, JP13 pin 1 and R20 removed), so any open in the feed chain leaves the pin at the R23 || R256
level (<= 0.11 V, H.4).

In the MD the opens are E1, E2, E3 and the CR-internal parts. Table 2 traces each one.

**Table 2. Opens in the release chain, merged design**

| Open | Effect | Converter |
|---|---|---|
| E1 (REGN to the gate pull-ups and the Q203 source) | Q203 has no source: no feed. Q201 and Q202 gates lose their pull-up. | HIZ at <= 0.11 V; U203 reads held while release is expected: FR-08 safe-direction "permit stuck LOW" |
| E2 (feed lead) or R255 | no feed | HIZ; same detection |
| E3 (hold lead) | hold and FC leg lost; feed absent unless commanded | HIZ while held; regen clamp instead of FC clamp in FC windows (B.6 row, bounded by the FC image register, FR-09, OC_FC) |
| U201 2A path or U114 2Y (R268 pulls 2A LOW) | Q203 off | HIZ |
| U202 A path (R270 pulls A LOW) | Q201 stays on | held (latent, B.6 row 2) |
| CR rail lost | open-drain outputs float; R252/R254/R271 pull the gates to REGN | Q201 on, Q203 off, Q202 on: HIZ with FC clamp |

The "drivers at the EVM pins" clause existed because the long run in r6 was the logic side: an open ribbon conductor had to
leave the driver input at a safe level (R267-R270). In the MD the drivers sit on the CR beside the switches, and the long
run is the drain side, whose opens are all safe by Table 2. The H.4 levels change by at most 1.3e-6 of the release level at
0.30 m of 28 AWG (64 mOhm against R255 48.7 kOhm, calc section 8).

- **G1: holds with a stated change.** The clause "drivers at the EVM pins" becomes "switches and drivers together on the CR
  island; every E-lead open leaves HIZ" (Table 2). EM3 stays mandatory: with the stock R21 127 kOhm or a JP14/JP13 shunt the
  EVM would release the converter on any E2/E3 open, which is the r0 defect.
- **G2: needs re-proof.** The open-circuit half holds. The two-switch half depends on the E2/E3/E4 conductors never meeting
  REGN or a power conductor, and over 0.10-0.30 m of dressed bundle that is a credible single fault (section 3.6, Table 5).
- **evm-jp14-feed-joint-floating: holds as is** in G1 and G2 (EVM-side modification).

### 3.2 (b) /CE driver U201 1Y and the redundant pull-ups R272/R272b (r3 ce-pullup-link-sense-divider-fails-low)

The argument: U201 1Y is open drain; an E5 open, a dead driver or an open command path leaves /CE pulled HIGH (inhibit) by
R272 and R272b, which sit on the EVM on separate joints and links, so either one alone keeps /CE >= 4.17 V (H.19). R272b is
not on the EIB, because there it would pull a lifted E6 up and mask a stuck-LOW /CE.

- **G1: holds as is.** R272/R272b stay on the EVM. The R272b placement rule extends to the CR: no /CE pull-up on the CR side
  of E6.
- **G2: holds with a stated change.** The topology holds. When U201 releases, E5 is a 0.30 m lead hanging on /CE behind
  23.5 kOhm. A 20 V edge on a parallel conductor 10 mm away dips /CE by up to 2.75 V for about 0.25 us (calc section 5,
  assumed aggressor). From 4.17 V this reaches 1.42 V, 0.12 V above VIH 1.3 V. The dip is toward "charge allowed", but it is
  sub-microsecond, and in the only state with the converter released and /CE HIGH (QQ qualification) EN_CHG = 0 is written
  first (B.1). The change: E5 and E6 twisted together with an E8 conductor, or shielded, in any G2 build.

### 3.3 (c) Far-end senses U203 (ILIM_HIZ) and U204 (/CE)

The argument: each sense lands on its own EVM joint (E4 on JP21 pin 1, E6 on the JP17 /CE pin), separate from the control
joints, and a lead-off reads in the dangerous direction. An open E4 lets R259 (10.0 MOhm) pull IN+ to 3V3 and read
"released", which trips FR-08(a) when GATE is expected 0. An open E6 lets R263 pull IN+ to 0 V and read "/CE LOW", which trips
FR-08(b) when P5 is LOW. A dead or unpowered comparator reads LOW through the pin-33 and pin-7 pad pull-downs.

The r3 finding u203-threshold-ignores-sense-offset set R258 = 10.0 kOhm, so the R259 current lifts IN+ only 2.6-2.7 mV above
the pin; the pin-referred trip is 0.587-0.650 V. In the MD the R259 current through the lead adds 0.02 uV at 0.30 m (calc
section 8).

Two effects grow with lead length:

1. **Pickup with the lead intact.** Section 6 gives the budgets (E4 48 mV, E6 159 mV) and the lengths at which a parallel
   aggressor reaches them.
2. **Pickup on a floating lead after a lead-off.** The open lead stays attached to R258 (E4) or R262 (E6) and couples
   capacitively to nearby switched conductors. With a 20 V edge on a conductor 10 mm away along the whole run, the spike at
   the lead is 0.81 V at 30 mm, 1.41 V at 60 mm and 3.40 V at 300 mm; recovery takes tau = 35-85 us through R259 (E4) and
   7-17 us through R262 + R263 (E6) (calc section 5). At 300 mm the E4 spike can pull IN+ from 3.3 V below the 0.587 V trip,
   and at a 20-30 kHz aggressor (33-50 us between edges, assumed) the reading chatters. FR-08(a) requires pin 33 HIGH for
   more than 2 ms and FR-08(b) pin 7 LOW for more than 1 ms (G.2; read here as continuous, TODO(verify: the FR-08
   implementation in the firmware round)), so a chattering readback never satisfies the persistence rule and the lead-off
   stays hidden. The EVM switch node is not such an aggressor: its edges alternate at
   1.5 MHz with fF-class coupling, and the slow input node averages them.

- **G1: holds as is**, provided the routing rule of section 7 (no switched conductor within 10 mm of any E-lead along the run)
  holds. At 60 mm with that rule the intact-lead pickup is <= 7.3 mV sustained from the EVM field (section 6), and no
  PWM-class aggressor exists for the floating-lead mechanism. The separate-joint rule and the island reference (section 3.5)
  stay mandatory.
- **G2: needs re-proof.** The lead-off property degrades to a chatter that FR-08 ignores. The re-proof needs either a shielded
  E4/E6 (shield on the island) or a filter capacitor at each comparator input, plus a lead-off test under live aggressors
  (T-C-05 change, section 9). A 1 nF C0G at U203 IN+ gives tau = 10 us with R258 for the intact lead and 10 ms with R259
  after a lead-off; IN+ then crosses the 0.650 V trip from the 0.11 V held level in about 1.9 ms, which adds that delay to
  the lead-off detection only, and a 1.44 pF aggressor coupling moves it by <= 29 mV. At U204 the same capacitor gives 0.5 ms with R262 || R263.
  These values are computed here and are not yet in the design.

### 3.4 (d) REGN supply E1 to the gate pull-ups (r4 eib-e1-regn-adjacent-to-ilim-feed)

E1 carries REGN to R252, R254, R271, the Q203 source and C205 (100 nF). The static load is <= 0.36 mA (H.15), so the drop is
<= 23 uV at 0.30 m. The A.9 rule isolates the E1 pad with an empty position on each side, because an E1-E2 bridge feeds REGN
onto ILIM_HIZ through R21 = 0 ohm and bypasses Q203 + R255.

Two length effects are new in this note:

1. **E1 + C205 series resonance.** The E1 lead with its E8 return and C205 form a series LC driven by the REGN ripple at the
   EVM. With a 5 mm return spacing the resonance is 3.03 MHz at 20 mm, 1.75 MHz at 60 mm, **1.47 MHz at 85 mm** and 0.78 MHz
   at 300 mm (calc section 6). The r6 build (E1 85-90 mm to JP12) therefore sits on the 1.5 MHz switching frequency with
   Q of about 19-20 (lead resistance plus an assumed 20 mOhm C205 ESR). The gate nodes are protected: R252 x Ciss is a 68 kHz
   low-pass, which attenuates a 1.5 MHz ripple 22 times. The circulating current in E1/E8 and the radiated field are not
   bounded until the REGN ripple is measured (T-C-16). A 10 ohm resistor in series with E1 at the CR pad reduces Q to about
   0.1 and shifts the release level by 1.6 mV (2 mA of ILIM clamp). This applies to r6 as well.
2. **Exposure of REGN off the EVM.** In G2 REGN runs 0.10-0.30 m in the vehicle wiring. A short to AGND collapses REGN (safe:
   converter off, /CE pull-ups fall, FR-08(b) trips with P5 LOW). A short into the ILIM group or onto a power conductor is
   treated in section 3.6.

- **G1: holds with a stated change.** The A.9 E1 isolation moves to the CR pad row, and E1 is dressed apart from the ILIM group
  over its whole length. A 10 ohm series resistor at the CR end of E1 is recommended (also for r6).
- **G2: needs re-proof** (section 3.6, Table 5; REGN current limit TODO).

### 3.5 (e) Ground: E8/TP49 single DC ground, R273, and the A.6 single-point scheme

In r6 the EIB has one DC ground, E8 at TP49 (EVM AGND). The four ribbon GND conductors reach EIB AGND only through R273 10 ohm,
so the net EVM ground current (1.4-1.6 A, A.6) stays in W2/W4 and the EIB return currents (<= ~1 mA) drop <= 10 mV across R273.

If the EIB parts sit directly on the CR plane, E8 bonds EVM AGND to the CR plane and becomes a parallel return to W2/W4. Table 3
gives the E8 current.

**Table 3. E8 current with and without the island (calc section 7; 1.5 A net EVM ground current)**

| Case | W2 \|\| W4 | E8 | E8 current, direct bond | E8 current, island + R273 | CR-plane-to-EVM offset (H.11 scaled) |
|---|---|---|---|---|---|
| G1, W 60 mm, E8 20 mm | 0.77 mOhm | 4.3 mOhm | 230 mA | 0.12 mA | <= 3.9 mV |
| G1, W 60 mm, E8 60 mm | 0.77 mOhm | 12.8 mOhm | 85 mA | 0.12 mA | <= 3.9 mV |
| G2, W 0.10 m, E8 0.10 m | 1.29 mOhm | 21.3 mOhm | 85 mA | 0.19 mA | <= 6.5 mV |
| G2, W 0.30 m, E8 0.30 m | 3.86 mOhm | 63.9 mOhm | 85 mA | 0.57 mA | <= 19.5 mV |

A direct bond fails the T-F-11 limit (20 mA in any signal-ground conductor) by a factor of 4-11 and puts EVM power-return current
on the AGND copper near the ILIM and TS grounds, against SLUUCB5E layout note 7. It would also reference U203 to the CR plane
while the pin is referenced to EVM AGND, which shifts the pin-referred band by the offset (up to 19.5 mV in G2) and consumes the
17 mV margin of the R23-open held level.

The merged scheme therefore keeps the r6 graph with one substitution. The EIB section has its own AGND island on the CR
(all four layers cleared of the CR plane under it). The island joins EVM AGND through E8 only and the CR plane through R273
only; R273 takes the place of the four ribbon GND conductors. The logic nets cross the island boundary only through their
existing series resistors (R250, R251, R253, R266 into the drivers; R264, R265 out of the comparators). With this island the
A.6 single-point statements stay true: the CR plane bonds to MB GND at CHG pads 4/14/15; EVM PGND/AGND reach the CR plane
through W2/W4 (power) and through E8 + R273 (signal, <= 0.6 mA); the W7 and W6 GND conductors stay bonded at the CR pad only.
No new DC path appears.

An open E8 leaves the island at CR-plane potential through R273: the hold then references a node <= 3.9 mV (G1) or <= 19.5 mV
(G2) from EVM AGND, far below the 0.75 V threshold (latent, found by T-C-05). An open R273 leaves the island on EVM AGND through
E8 only (no functional change, latent). Both behave as in r6.

A G1 build that fixes the EVM to the CR or to a common bracket must not bond EVM copper to the CR plane through hardware. The
EVM has no mounting holes, and a hole drilled at a bumpon position cuts the ground pour and 7-17 vias (`evm_geometry.md`
section 3), so any fastener through the EVM is insulated or the EVM is clamped by its edges.

- **G1 and G2: holds with a stated change** (the island and R273 replace the ribbon GND conductors; the isolation check moves
  to T-A-08). The r2 findings ground-loops-parallel-returns and evm-agnd-parallel-return stay closed only with the island.

### 3.6 (f) The W5 ribbon and its adjacent-short list

Every entry of the A.3 W5 list concerns a ribbon conductor: 1-2, 2-3, 3-4, 4-5, 5-6, 6-7, 7-8, 8-9, 9-10, 10-11, 11-12, 12-13
and 13-14, plus the keyed rotation and shift cases. In the MD the ribbon does not exist, so the whole list **retires** in G1 and
G2. Its CR-side equivalents are covered elsewhere: a short of the T12 or T20 tap wire to GND is limited by R125 or R148 (with or
without R264/R265, <= 3.3 mA from a TLV3012B output, against the 10 mA absolute maximum), and the merged-rail short is the R175
case (48.5 mA, H.20).

What replaces the list depends on the geometry.

- **G1:** the E-leads are 10-60 mm (E1 up to 90 mm) point-to-point leads, the same class as the r6 E-leads (20-90 mm). The r6
  analysis treated only solder bridges at the pad row as credible conductor-to-conductor shorts, and that treatment carries
  over if the leads are dressed individually and never tied into a bundle with each other's forbidden neighbours, with W1-W4 or
  with vehicle wiring. The A.9 pad order (E8, empty, E3, E4, E2, empty, E7, empty, E1, empty, E5, E6) and the bare-board
  isolation pairs (E1 to E2/E3/E5, E7 to E1/E2/E5/E6/E8, E8 to E3) move unchanged to the CR edge.
- **G2:** 0.10-0.30 m of eight conductors must be dressed and tied as a bundle on a moving vehicle, so a short between any two
  of them is a credible single fault, as it was for the ribbon. Table 5 lists the outcomes. Unlike the ribbon, the bundle
  carries the BQ25798 pin nodes without series impedance (R21 = 0 ohm joins E2 to the pin; E3 and E4 land on it directly).

**Table 5. G2 E-bundle conductor-to-conductor shorts (outcome per pair class)**

| Pair | Held state (Q201 on) | Released state | Detection | Class |
|---|---|---|---|---|
| E1-E2/E3/E4 (REGN onto the ILIM node) | Q201 sinks REGN: the pin stays held only if Rds(on) x I_REGN,lim < 0.75 V, i.e. I_REGN,lim < 190-375 mA at 2-4 ohm (TODO(verify: SLUSDV2C REGN current limit)) | the pin sits at REGN 4.8-5.2 V: Q203 + R255 bypassed, ILIM pin limit (5 - 1)/0.8 = 5 A, so only the IINDPM register (FR-46) and the eFuse (2.05-2.41 A) bound the input; FC leg lost | none (U203 reads as expected in both states) | **barrier defeated, undetected** |
| E1-E5/E6 (REGN onto /CE) | - | /CE HIGH permanently (inhibit); U201 1Y sinks REGN with no series resistance (TODO(verify: SCES364J output current absolute maximum)) | U204 /CE HIGH while P5 HIGH: FR-47 latch | safe direction, possible U201 damage |
| E1-E7 (REGN onto STAT) | - | STAT sinks REGN when charging, far above its 6 mA absolute maximum; pin 6 sees REGN through R275 1 kOhm | FR-44 | charger damage, no barrier lost |
| E1-E8 (REGN to AGND) | REGN collapses, converter off | same | /CE falls with REGN: FR-08(b) with P5 LOW | safe |
| E2-E3, E2-E4, E3-E4 | same node | same node | a later lead-off of one of them is masked | latent |
| ILIM group-E5/E6 | /CE LOW drags the pin LOW: held | /CE pull-ups raise the pin to ~3.6 V while /CE reads HIGH (charging inhibited) | U203/U204 mismatch: FR-08 | mutually blocking, detected |
| ILIM group-E7 | STAT LOW holds the pin | STAT HIGH (3.3 V through R275 + R107) raises the pin to ~2.95 V; charging pulls STAT LOW and holds the pin: relaxation | FR-44, FR-08 | detected |
| ILIM group-E8 | held | held | permit stuck LOW | safe |
| E5-E6 | same node | same node | a later E6 lead-off is masked | latent |
| E5/E6-E7 | - | while charging, STAT LOW holds /CE LOW: the /CE inhibit self-latches | FR-08(b) (pin 7 LOW with P5 LOW) trips and takes the ILIM hold | detected, second barrier intact |
| E5/E6-E8 | - | /CE LOW permanently | FR-08(b) | detected |
| E7-E8 | - | pin 6 reads "charging" permanently | FR-44 | detected |

A crush through the bundle onto a VCHG-IN, V-MOT or VCHGOUT conductor (up to the 22.61-23.63 V eFuse OVP band, H.5) drives the
ILIM group to that voltage: the pin exceeds its absolute maximum (TODO(verify: SLUSDV2C §6.1)), Q201 conducts the fault
current (TODO(verify: 2N7002K drain current rating), T-A-03), and the converter is released. In r6 the same crush reaches a
ribbon conductor, which enters an LVC input through 1 kOhm, and a release still needs both drivers to fail sinking. Over a
10-60 mm point-to-point G1 run no such crush is credible under the section-7 routing rules.

- **r4 ribbon-adjacent-short-ilimrelb-rfcoff, r5 ribbon-4-5-stat-sink-abs-max, r5 ribbon-adjacent-short-stat-cedrv: retire**
  in G1 and G2. R275 stays, with a changed argument: it limits the STAT pin current from any CR-side fault on the STAT net (a
  short to a push-pull logic HIGH gives 3.3 mA against 6 mA) and keeps the FR-44 pairing; it does not protect an EVM-side
  bundle short in G2, because it sits at the CR end of E7.
- **r3 j101-unkeyed-ribbon-reversal: retires** in G1 and G2 (a connectorised G2 bundle would re-open a keying question).
- **r4 tlv3012-ribbon-driver-short-current: holds with a stated change.** R125 and R148 alone limit a tap short to 3.3 mA, so
  R264/R265 become optional.

### 3.7 (g) 3V3 feed R176/R177 and the bleed R274 (r2 eib-pin8-backpower-unpowered-outputs; r4 cr-eib-3v3-feed-unprotected-short)

In r6 the EIB rail was fed through two ribbon conductors, each with a 200 ohm resistor, so one open conductor changed nothing and
a ribbon short drew <= 15.9 mA per conductor (H.20). R274 (10.0 kOhm) bled the EIB rail so that a lost rail collapsed below
1.5 V within ~20 ms and no residual source could hold it above the LVC/TLV3012B minimum.

In the MD the EIB parts take the CR rail behind R175 (68 ohm at F07). R176 and R177 have nothing to feed and retire. The merged
rail short is the existing R175 case (48.5 mA, 0.16 W, H.20). The rail load is unchanged at ~1.86 mA (H.15 already counts the EIB),
so the CR rail stays at ~3.17 V; U203's REF and the R259 offset are rail-independent to within the 2.7 mV of H.4.

R274 holds with a stated change: it stays, on the merged rail. B.7 already relies on it ("holds the rail near 0.3-0.45 V across
R274" for the BAV199 residual of <= ~50 uA plus <= 57 uA from D108). The merge adds no back-feed source: R259 passes <= 0.24 uA
from a released ILIM_HIZ, U204 IN+ is a fail-safe input behind R262, and the open-drain outputs have Ioff. The pin-7 readback
path through the vacated ROS pad is unchanged. The B.6 row "3V3 lost on the EIB (both ribbon 3V3 conductors open)" retires and
folds into the B.7 row "CR 3V3 lost while armed (T6 open)", whose detection (pin 7 LOW with P5 LOW and `regnExpected`, FR-08(b))
is unchanged. The merged rail decays with C125 (10 uF) in both r6 and the MD, because in r6 the EIB rail followed the CR rail
through R176 || R177 = 100 ohm when T6 opened.

- **eib-pin8-backpower-unpowered-outputs: holds with a stated change** (the two-conductor feed retires; pin 7, INPUT_PULLDOWN
  readbacks and R274 stay).
- **cr-eib-3v3-feed-unprotected-short: holds with a stated change** (R175 only).

### 3.8 (h) Pickup on the length-critical leads, and the H.13 glitch analysis

Section 6 derives the per-lead limits. The H.13 result (a 0.1 us or 1 us release glitch lifts ILIM_HIZ to 0.28 V or 0.32 V) rests
on tau = (R255 || R23 || R256) x C252 = 48.3 us and on the Q201/Q203 gate recovery through 47 kOhm. Both stay on their r6
values: C252 and R256 stay at the JP21 posts on the EVM, and the gate nodes stay beside their drivers. The E2, E3 and E4 leads add
<= 2 pF at 60 mm and <= 12 pF at 300 mm to the pin node (0.1 % and 0.6 % of C252). The merge also removes the 0.30 m ribbon from
the glitch path, so fewer glitch sources reach the drivers. **H.13 holds as is in G1 and G2.**

One dynamic effect is new. With Q201 on, the E3 + E8 loop inductance and C252 form a series LC: 33 MHz at 20 mm (tight pair)
down to 5.3 MHz at 300 mm with 5 mm spacing (calc section 6). Q201 turns on through R252 x Ciss (tau 2.35 us), so its Rds(on)
passes the loop impedance (2-14 ohm) over microseconds and the hold transition is not underdamped. Once Q201 is fully on, the
loop damping is 0.07-0.9; the ns pickup it rings with stays <= 38 mV at the pin (section 6). The gate drive must stay slow: a
faster Q201 turn-on would ring the pin below ground on long E3 leads.

## 4. Review findings

Table 6 collects the named findings.

**Table 6. Round-3 findings under the merge**

| Finding (round-r#) | G1 | G2 |
|---|---|---|
| eib-wireoff-releases-converter (r1-2) | holds with a stated change (3.1) | needs re-proof (3.1, 3.6) |
| evm-jp14-feed-joint-floating (r2-1) | holds as is | holds as is |
| eib-pin8-backpower-unpowered-outputs (r2-6) | holds with a stated change (3.7) | holds with a stated change (3.7) |
| ground-loops-parallel-returns, evm-agnd-parallel-return (r2-26/27) | holds with a stated change: island + R273 (3.5) | same |
| ce-pullup-link-sense-divider-fails-low (r3-4) | holds as is; no /CE pull-up on the CR (3.2) | holds with a stated change: E5/E6 twisted or shielded (3.2) |
| u203-threshold-ignores-sense-offset (r3-17) | holds with a stated change: valid only with U203 on the island (3.5) | same; without the island the 19.5 mV offset would consume the 17 mV R23-open margin |
| j101-unkeyed-ribbon-reversal (r3-25) | retires | retires |
| r256-c252-agnd-landing-unspecified (r3-30) | holds as is | holds as is |
| eib-layout-unbudgeted (r3-33) | retires (H.18b); replaced by the CR re-book (~253 mm² courtyard, section 7) | n/a (no merge) |
| eib-e1-regn-adjacent-to-ilim-feed (r4-9) | holds with a stated change: CR pad row and lead dressing | needs re-proof: bundle (Table 5) |
| cr-eib-3v3-feed-unprotected-short (r4-16) | holds with a stated change: R175 only | same |
| ribbon-adjacent-short-ilimrelb-rfcoff (r4-17) | retires | retires; replaced by Table 5 |
| tlv3012-ribbon-driver-short-current (r4-18) | holds with a stated change: R264/R265 optional | same |
| ribbon-4-5-stat-sink-abs-max, ribbon-adjacent-short-stat-cedrv (r5-10/18) | retire as ribbon faults; R275 kept with a changed argument (3.6) | same; E5/E6-E7 and E1-E7 bundle pairs in Table 5 |
| eib-e6-e7-ce-stat-bridge (r5-11) | holds with a stated change: CR pad row | needs re-proof: bundle (Table 5) |
| eib-e-lead-max-lengths-geometrically-infeasible (r6-14) | re-derived by criterion (section 6) | re-derived; untwisted limits below the G2 range |

## 5. B.6 single-fault table, row by row

Table 7 takes each B.6 row in order.

**Table 7. B.6 single-fault rows under the merge**

| B.6 row | G1 | G2 | Change or re-proof |
|---|---|---|---|
| E2 lead off, R255 open, Q203 open, U201 2Y stuck open, ribbon 7 open | holds with a stated change | holds with a stated change | "ribbon 7 open" becomes "U114 2Y to U201 2A path open (R268 pulls 2A LOW)"; outcome and detection unchanged |
| Q201 open, R252 open, U202 stuck open, ribbon 8 open | holds with a stated change | holds with a stated change | as above for ribbon 8 (R270); latent, T-C-05 |
| Q203 D-S short, U201 2Y stuck sinking | holds as is | needs re-proof | G2 adds the equivalent zero-resistance bypass E1-ILIM group (Table 5): held only if Q201 out-sinks the REGN current limit |
| Q201 D-S short | holds as is | holds as is | permanent HIZ |
| E3 lead off | holds as is | holds as is | longer lead raises the lead-off probability on a vehicle (T-F-18); outcome unchanged |
| E4 sense lead off, U203 dead | holds as is | needs re-proof | floating-lead chatter vs FR-08(a) 2 ms persistence (3.3); IN+ filter or shield |
| EVM R23 open | holds as is | holds as is | EVM-side |
| E5 lead off, U201 1Y stuck open, ribbon 5 open | holds with a stated change | holds with a stated change | "ribbon 5 open" becomes the CE_DRV trace (R267 pulls 1A LOW); FR-47 latch unchanged |
| U201 1Y stuck sinking | holds as is | holds as is | FR-08(b) |
| R272 or R272b, or link L1/L2, open | holds as is | holds as is | EVM-side, latent |
| R272 and R272b both open | holds as is | holds with a stated change | G2: /CE then rests on R262 + R263 (2 MOhm) through a 0.30 m lead, so pickup moves /CE freely; still read LOW and tripped; a double fault |
| E6 sense lead off, U204 dead | holds as is | needs re-proof | floating-lead chatter vs FR-08(b) 1 ms persistence (3.3) |
| Ribbon conductor shorted to a neighbour | retires | retires | replaced by the pad-row bridges (G1, A.9 list) or Table 5 (G2) |
| 3V3 lost on the EIB | retires | retires | folds into B.7 "CR 3V3 lost while armed (T6 open)" (3.7) |
| (new) E1 lead off | holds (new row) | holds (new row) | HIZ, permit stuck LOW (Table 2); T-C-05 already opens E1 |
| (new, G2 only) E-bundle conductor short | n/a under section 7 | needs re-proof | Table 5: E1-ILIM group defeats the hardware clamp undetected |
| (new, G2 only) bundle crush onto a power conductor | n/a under section 7 | needs re-proof | ILIM_HIZ driven above its absolute maximum; release (3.6) |

## 6. Maximum E-lead lengths

### 6.1 Criterion

The r6 classes (length-critical E3/E4/E6/E8, semi-critical E2, static E1/E5/E7) were qualitative, and the r6 maxima were
geometric (straight distance x 1.25). This note uses a quantitative criterion: **the sustained (>= 1 us) EMF in the loop formed by
a lead and its return must stay at or below 10 % of the smallest margin of the argument that the lead serves.** The H.4 and H.19
bands already contain divider tolerance, REF drift over 0-45 C, Vos, hysteresis and leakage, so the margin is pure headroom; the
10 % share leaves 90 % for the unspecified ILIM_HIZ deglitch and other unmodelled terms. Sub-microsecond spikes are checked
separately at the protected node, after the C252 or R258 filter. Table 8 gives the margins.

**Table 8. Margins and budgets (calc section 2)**

| Lead | Protected reading | Margin | Budget (10 %) |
|---|---|---|---|
| E3 | ILIM_HIZ held with Q201 on (about 0 V) against VIL_ILIM_HIZ max 0.75 V | 0.750 V | 75 mV |
| E4 | held 0.11 V against the 0.587 V trip (nuisance); released 1.52 V against 0.650 V (masking) | 0.477 V / 0.870 V | 48 mV |
| E6 | /CE HIGH >= 4.17 V against the 2.39-2.58 V U204 trip (nuisance); /CE LOW <= 0.10 V against it (masking) | 1.587 V / 2.285 V | 159 mV |

E2 has no pickup budget: an EMF in the E2 loop acts through R255 (48.7 kOhm) into the pin node (21.9 kOhm || 2.2 nF). E1, E5 and
E7 are static nets whose open state is safe at any length. E8 is the return of the E3, E4 and E6 loops; it has no budget of its
own (0.13 mV of offset at 2 mA over 0.30 m), but its routing sets their loop areas.

### 6.2 Aggressors

Two aggressor models are evaluated (calc sections 3 and 4).

1. **The EVM power stage as a magnetic dipole.** L2 (1 uH) ripple slope 12.3 A/us at 19.72 V in and 7.4 V out, 3.08 A p-p, 4.75 A
   peak; assumed effective areas 5-50 mm² (ripple loop) and 1-10 mm² (input hot loop), assumed 2-10 ns edges. For a lead pair
   with 5 mm spacing whose closest approach is 13 mm, the sustained ripple EMF is 2.6 mV at 10 mm length, 6.7 mV at 60 mm and
   7.3 mV as the length goes to infinity. The field falls as r^-3, so the EVM term saturates with length. It reaches the
   budgets only at 3-5 mm from the stage centre-line, where no E-point lies (the nearest is 12.0 mm). The hot-loop spike
   (<= 0.28 V for 2 ns, upper bound) reaches the pin at <= 38 mV through the E3 loop inductance and C252, and U203 IN+ at
   <= 0.07 of its EMF through R258 and the input capacitance.
2. **A parallel conductor along the route.** Mutual inductance per metre M' = (mu0/2pi) ln((d + s)/d). Class A is a 1 A/us load
   step; class B is 10 A/us, the order of the EVM L2 slope (12.3 A/us) and the MB boost inductor slope (8.4 V / 2.2 uH = 3.8
   A/us; L-BT HCM1A1305V3-2R2-R from `round4/calc/mb_neighbours_out.txt`, TPS61288 fSW 440-600 kHz from its datasheet EC
   table). A twisted pair (25 mm pitch, 0.6 mm spacing) leaves one uncancelled half twist, 0.15 nH, independent of length.

### 6.3 Limits

Table 9 gives the maximum length per lead.

**Table 9. Maximum E-lead length by criterion (class B parallel conductor at 10 mm unless stated)**

| Lead | Budget | Untwisted, s 5 mm | Untwisted, s 2 mm | Twisted with E8 or shielded | G1 (10-60 mm) | G2 (0.10-0.30 m) |
|---|---|---|---|---|---|---|
| E3 | 75 mV | 92 mm (class A 925 mm) | 206 mm | no limit to 0.30 m (1.5 mV) | pass; run with E8 | twist or shield required above 92-206 mm |
| E4 | 48 mV | 59 mm (class A 588 mm) | 131 mm | no limit (1.5 mV) | pass with E4 within 2 mm of E8, or with no class-B conductor within 20 mm (107 mm at d 20 mm) | twist or shield; plus the lead-off filter of 3.3 |
| E6 | 159 mV | 196 mm (class A 1957 mm) | 435 mm | no limit (1.5 mV) | pass | twist or shield above 196 mm |
| E8 | none (return) | as its group | as its group | as its group | with E3/E4 | with each group (two E8 conductors, both island to TP49) |
| E2 | none (series 48.7 kOhm) | no pickup limit | - | - | geometric; A.9 adjacency | bundle rules (Table 5) |
| E1 | none (static) | no pickup limit | - | - | up to 90 mm to JP12 with the 10 ohm damping resistor (3.4) | bundle rules (Table 5) |
| E5 | none (static, open drain) | no fail-safe limit | - | - | geometric | twisted with E6 and an E8 (3.2) |
| E7 | none (static) | no limit | - | - | geometric; A.9 adjacency | bundle rules (Table 5) |

In G1 the realistic aggressors near the leads are the EVM stage and the MB boost stages (dipole-like, mV at >= 10 mm) and the
W1-W4 pairs (twisted, DC plus ms-scale steps, class A at most). Table 9 therefore gives no binding limit inside 10-60 mm once the
routing rules of section 7 hold; the build maxima stay geometric (straight distance x 1.25, rounded up to 5 mm, as in r6, re-run
on the vector positions: `evm_geometry.md` Table 6). In G2 every untwisted length-critical lead exceeds its class-B limit at the
upper end of the range, and the vehicle aggressor field is unmeasured.

## 7. Conditions for the G1 merge

The G1 merge is acceptable only with all of the following.

1. **Island:** the EIB section has its own AGND island on all four CR layers, joined to EVM AGND by E8 only and to the CR plane by
   R273 (10 ohm) only. Logic nets cross the boundary only through R250/R251/R253/R266 and R264/R265 (or R125/R148 if R264/R265
   are omitted).
2. **Pad row:** the A.9 order and isolation pairs move unchanged to the CR edge that faces the EVM point cluster (or the EVM is
   rotated so that its right edge faces the CR).
3. **Lead dressing:** each E-lead runs point to point; E1 and E7 run apart from the ILIM group and from each other over their
   whole length; E3 and E4 run within 2 mm of E8 except over the last ~20 mm, where TP49 and TP33/JP21 diverge by ~16 mm; no
   E-lead is tied into a bundle with W1-W4 or vehicle wiring, and none passes
   within 10 mm of L2, U1, the C19-C21/C29-C31 banks or the SW copper, or crosses the EVM power stage.
4. **Parts kept:** EM3, R256/C252 at the JP21 posts, R272/R272b on separate EVM joints, R274 on the merged rail, R275 at the CR
   E7 pad, R258 10.0 kOhm, the R267-R270 pull-downs; no /CE pull-up on the CR.
5. **Parts deleted:** W5, J101, J201, R176, R177; R130-R132 become 0 ohm or are removed; R264/R265 are optional.
6. **E1 damping:** a 10 ohm resistor in series with E1 at the CR pad (Q of the E1 + C205 loop from ~20 to ~0.1; release-level
   shift 1.6 mV). The same change is recommended for r6.
7. **Mechanics:** the EVM and the CR sit on one rigid body, or every E-lead has a strain relief at the CR edge and T-F-18 passes.
   No fastener or bracket bonds EVM copper to the CR plane (`evm_geometry.md` finding 1: no mounting holes).
8. **Thermal:** the EIB section sits where its temperature stays inside the H.4 basis (25 C + 45 C); the LM1084 side is excluded
   unless a thermocouple shows it (TODO(measure: EIB-section temperature, Run, 30 min)).
9. **Area:** the EIB section needs ~253 mm² of courtyard (H.18b basis without J201 and the two M3 keep-outs); the J101 body frees
   37 mm². The r6 top side would reach ~895 mm² against ~881 mm² (102 %), so the section must go into the sideways extension.
10. **CR analog front ends:** the EVM power stage stays outside a 20 mm radius of U104 (BT_OK, 6-34 mV threshold), U102/U103 and
    the T8/T9 landing; T-C-16 includes these nodes. (This is a CR consequence of G1, outside the EIB arguments, and is listed so
    that it is not lost.)

## 8. G2: what a re-proof would need

A G2 merge could be re-proven only with all of the following, each of which is a design change.

1. Segregated cables: E1 alone in its own sleeve; the ILIM group and an E8 in a foil-shielded cable; the /CE group and a second
   E8 in another; each shield bonded at the island only. A crush then meets the shield first.
2. A measured REGN current limit and a Q201 sink capability that holds ILIM_HIZ below 0.75 V against it, or a series resistor at
   the EVM end of E1 (100 ohm limits an E1 short to 48 mA and shifts the release level by 16 mV, 20 mA of clamp; calc section 6).
3. Series protection or a clamp at the EVM end of the ILIM group against a crush (changes H.4; re-run `r3_calc.py`).
4. A 1 nF C0G filter at U203 and U204 IN+ (3.3), and FR-08 persistence re-checked against it.
5. A full adjacent-short sweep of the chosen cable, a crush test and a vehicle pickup survey.

Items 2 and 3 put parts back at the EVM pins, and item 1 adds two shielded cables in place of one ribbon. The result is the r6
EIB with a different cable. For G2 the r6 split therefore stays the design.

## 9. Tests

### 9.1 New (G1 merge)

- **T-A-08 Merged-CR island and EVM mounting isolation.** Power off. Island to CR plane = R273 10 ohm +- 1 % and > 1 MOhm with R273
  lifted; E8 pad to TP49 < 0.5 ohm after fitting; EVM copper (TP49, J1 pin 1) to the CR plane through the mounting > 1 MOhm with
  W2/W4 and E8 disconnected; bare-CR E-pad isolation for the A.9 pairs > 1 MOhm; E7 pad to TP38 = 1.00 kOhm +- 1 % through R275
  after the E7 lead is fitted; first power of the merged CR from a 3.3 V supply at a 20 mA limit in place of T6, draw <= 1.86 mA
  plus margin (the T-C-13 first-power step).
- **T-C-16 Pickup at the protected nodes, charger converting.** Scope (>= 200 MHz, ground springs) TP33 against TP49, U203 IN+ and
  U204 IN+ against the island, JP17 /CE against TP49, and REGN at C205 against the island. States: held; released at the regen
  image (ICHG 3.10 A, input 19 V); FC image; MB boosts at full load. Pass: sustained (1 MHz bandwidth limit) pickup <= 75 mV at
  TP33 held, <= 48 mV at U203 IN+ referred to the pin, <= 159 mV at /CE; ns spikes recorded and below the same budgets after the
  node filters; pins 33 and 7 show no uncommanded transition over 10 min (LA, 1 us). Also record the E1/C205 ring with and
  without the 10 ohm damping resistor, and U104 IN- pickup (condition 10). Fail: re-route, twist with E8, or shorten.
- **T-F-18 E-lead integrity on the vehicle.** Road or shaker run with an LA on pins 7 and 33 and a continuity monitor on E1-E8.
  Pass: no uncommanded transition and no FR-08 trip. Applies when the EVM is not on the same rigid body as the CR.

### 9.2 Changed

- **T-A-02:** E-lead lengths against the section-6 maxima (geometric build maxima, re-run on the vector positions) and the
  section-7 dressing rules; JP21 pin 1 is the lower post; the corner-hole step is replaced by the T-A-08 mounting isolation.
- **T-A-05:** J101/J201, the W5 cable assembly, the polarising plug and the R176/R177 ratings are removed; the 10 ohm E1 resistor
  is added.
- **T-A-06:** placement DRC on the extended CR outline with the EIB section and the island; netlist check that R273 is the only
  island-to-plane connection; the E-pad row order; E-leads measured on the dry fit. Removed: the 36 x 24 mm EIB outline and its
  1:1 print, the bare-EIB isolation (moved to T-A-08), the J101 region and mated-socket dry fit, the W5 cable exit.
- **T-C-05:** keep the E1-E8 opens, R255, R252, R271, R272/R272b and L1/L2, Q201 drain, Q203 and Q201 D-S shorts, E4/E6 joint
  lifts; R273 open and E8 open now act on the island. Add: E4 and E6 lifted with the MB boosts and the EVM converting, readback
  held at its lead-off level continuously for longer than the FR-08 persistence (2 ms / 1 ms); powered bridges of the same-node
  pad pairs (E3-E4, E4-E2, E5-E6) showing masking only. Remove: every ribbon conductor open, the ribbon 3V3 single and double
  opens, the adjacent ribbon-pair sweep (including 3-4, 4-5, 11-12) and the U204-against-EIB-rail scope step.
- **T-C-07:** T6 open now covers the merged rail (pass: merged rail < 0.8 V, every output at its fail-safe level, pin 7 LOW and
  FR-08(b) within 20 ms); the C201 short becomes a merged-rail short (R175, <= 48.5 mA). Remove: W5 conductor opens, the 2-3 and
  1-3 ribbon shorts and the one-ribbon-3V3-conductor rail check.
- **T-D-11:** content unchanged (E3 lifted, Q201 and R252 removed, U202 Y LOW, E5 lifted, U201 1Y LOW, R272/R272b removed, E6
  lifted at Run entry, the r4/r5 window cases); "EIB" reads "CR EIB section"; add E1 lifted.
- **T-F-11:** measure at R273 (island tie) and in E8; limits unchanged (< 20 mA, < 2 mV AGND-PGND); expected <= 0.12 mA (G1).
- **T-F-12:** add the E-lead strain relief and pull check at the CR edge.

### 9.3 Retired (G1 merge)

- **T-C-13** (ribbon orientation and first power): retired; its R275 metering and its 20 mA-limited first power move to T-A-08.
- The ribbon parts of T-C-05, T-C-07, T-A-05 and T-A-06 listed in 9.2.
- The calculation rows H.18b (EIB area) and the H.20 ribbon rows (ribbon 3V3 conductor short 15.9 mA, EIB rail short 31.8 mA,
  R264/R265 6.7 mA into a ribbon short); the J.2 items 22 (EIB layout), 30 (EIB rail drop) and 31 (1.27 mm ribbon).
- **Not retired:** T-B-03, T-A-03, T-C-10, T-B-20 and T-D-11 keep their content; they test the EIB function wherever it sits.

### 9.4 Only if a G2 merge were pursued

T-C-18 (adjacent-short sweep of the chosen cable, every pair, powered, in held and released states), a crush-to-shield test, a
REGN current-limit measurement against Q201, and a vehicle-route pickup survey (search coil and capacitive probe along the run).

## 10. Assumptions and open values

| Value | Used here | What decides it |
|---|---|---|
| EVM ripple-loop area 5-50 mm², hot-loop area 1-10 mm², SW edge 2-10 ns | dipole pickup (6.2) | TODO(measure: T-C-16) |
| Aggressor classes A 1 A/us and B 10 A/us; 20 V edges at 20-30 kHz | Table 9, 3.3 | TODO(measure: vehicle-route survey, G2 only); G1 excludes them by routing |
| TLV3012B IN+ capacitance 3-8 pF | ns attenuation at U203 | TODO(verify: SBOS300C) |
| C205 ESR 20 mOhm at 1.5 MHz | E1 ring Q | TODO(measure: T-C-16 ring amplitude) |
| 2N7002K Ciss 50 pF, Rds(on) 2-4 ohm | gate tau, hold-loop damping | T-A-03 (r6 assumption) |
| 28 AWG Kynar centre spacing 0.6 mm when twisted | twisted residual | TODO(verify: wire datasheet OD) |
| BQ25798 REGN current limit | Table 5 E1-ILIM group, held state | TODO(verify: SLUSDV2C EC table) |
| ILIM_HIZ, /CE, STAT, REGN absolute maxima; ILIM_HIZ deglitch | Table 5, 3.6, 6.1 | TODO(verify: SLUSDV2C §6.1, §7.3.4.3) |
| SN74LVC3G06 continuous output current maximum | Table 5 E1-E5/E6 | TODO(verify: SCES364J §6.1) |
| /CE pin capacitance 5 pF | /CE dip (3.2) | TODO(verify: SLUSDV2C) |
| EIB-section temperature | H.4 basis | TODO(measure: thermocouple, condition 8) |

## 11. Confidence

The open-circuit, dead-driver and rail-loss conclusions are high confidence: they follow from the B.8 netlist and the EM3 state,
which the merge leaves unchanged. The ground conclusion is high confidence: it uses AWG resistances and the H.11 drop scaled by
length. The pickup figures are order-of-magnitude estimates (dipole and line-current models with assumed areas, edges and
aggressor classes, about a factor of 2 at r0 comparable to the 19 x 16 mm stage), and T-C-16 is the gate for G1. The G2 short
outcomes are medium confidence until the REGN current limit and the pin absolute maxima are verified; the G2 verdict does not
depend on them, because the undetected loss of the hardware clamp (Table 5, released state) holds whatever those values are.
