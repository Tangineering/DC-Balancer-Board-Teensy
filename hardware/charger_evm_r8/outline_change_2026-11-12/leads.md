# Item 4.3: Removability of the taps and the W leads

DD = `docs/charger_bq25798_wiring_design_2026-11-05.md` (worktree DC-Balancer-round4). CRQ = `CR_OUTLINE_CHANGE_REQUEST_2026-11-12.md`.

## 1. Findings

### 1.1 Lead inventory (CR end, far end, current)

**W leads (DD A.3, lines 480-489):**

| Lead | CR end today | Far end | Current | Removable today at |
|---|---|---|---|---|
| W1 / W2 | 1.3 mm PTH, 2.3 mm pad (DD:1221-1222) | EVM J1 pins 2/1, On-Shore ED120 screw terminal (DD:3682) | <= 2.41 A for <= 202 ms, normally <= 1.76 A (DD:489) | far end only (screw) |
| W3 / W4 | 1.5 mm PTH, 2.5 mm pad | EVM J5 pins 1/3, ED120/3DS, 0.75 mmÂ² ferrules | <= 3.21 A (DD:489) | far end only (screw) |
| W5 | J101, 2x7 1.27 mm SMT (Samtec FTSH), IDC socket | EIB J201, IDC | signal | **both ends already** |
| W6 | SMT pads 1.2 x 1.5 mm (DD:1226) | EVM J7 pin 1, termination TODO(verify: SLUUCB5E J7 type) | thermistor, < 1 mA | unclear; only fitted with an NTC (T-E-09) |
| W7 | SMT pads (DD:1225) | EVM J8, KK 254 22-01-3047 + 08-50-0114 | I2C, mA | far end only (KK) |

The E leads (DD A.5, E1-E8) run from the EIB to the EVM. They do not touch the CR, so they do not affect CR removability. **W8 is DNP** (DD A.3).

**Taps (DD A.4, lines 659-682):** 21 tap conductors are wired in the baseline. Every tap is a signal. The worst case is T6 (3V3): 1.82 mA in normal operation, and R175 limits a fault to 48.5 mA (DD:665). There are two groups of far-end terminations:

- **Already pluggable at the far end (15 taps):** T3-T6, T8, T10-T17, T17r and T21. Each ends in a single TSW male pin pushed into the second J1/J2 Dubox position.
- **Soldered on the MB (6 taps):**
  - T1, at C-D6 pad 1 through R170 at the joint;
  - T7b, at C-D6 pad 2;
  - T2, at C-D2 pad 1 through R171 at the joint;
  - T9, at the SNS-BT GND/REF1 pad;
  - T20, at ROS pad 2;
  - T22, at BQ29200 pin 8 (30 AWG Kynar, the most fragile joint, DD:666).

**Pads with no CR net:** F22 (T18), because the keep-alive parts were removed (D-31 tier 2). F23 (T19), because U117 was removed (D-31 tier 3). F24 is an optional spare (pin 2, only if T-A-01b clears it) (LAYOUT_DECISIONS.md D-31, D-05).

### 1.2 Where the far ends lie against the new outline (x 18.584-67, y 7-94)

The positions come from the MB `.brd`, read with `mb_part_extents.py`:

- Outside the outline, on the +x side:
  - J1 (x 83.2-88.5) and J2 (x 106.1-111.3), both y 31.5-93.3;
  - ROS (81.5, 70.6);
  - C-D6 (97.8, 17.9);
  - C-D2, body x 67.42-69.74 at y 69.9. It is only 0.42 mm past the +x edge.
- **Under the new outline:**
  - SNS-BT (55.1, 23.6), the end of T9;
  - BAL (24.4, 29.5), pin 8 at (25.86, 30.44), the end of T22;
  - CO-5V (50.8, 39.6). T18 is not fitted.

T9 and T22 therefore leave the MB under the CR. A lead that ends at a connector on the CR top must run in the CR-to-MB gap to a CR edge and then rise. T9 is 11.6 mm from the +x edge. T22 is 23 mm from the -y edge and 41 mm from the +x edge. The A.4 maximum for T22 is 0.05 m, which a route to the +x edge exceeds (TODO(calc)).

### 1.3 Two ways to make the CR removable

- **(A) Connectors on the CR.** Every lead unplugs at the CR. Each lead stays with the MB or the EVM. This is the cleanest option.
- **(B) Leads stay soldered to the CR and unplug at the far end.** The CR comes out with its leads attached. This works for W1-W4 and W7, through screws or the KK housing, and for the 15 Dubox taps. However, the operator must then pull and re-seat 15 loose single pins into J1/J2 on every removal. A pin in the wrong position puts a Teensy output on a wrong net, and no key prevents it. In addition, the 6 MB-soldered taps still need a break point. Option (B) is therefore incomplete without at least one connector.

### 1.4 Effect on the A.8 adjacent-pad short table (H.23(g))

The short table (DD:1257-1305) models one hand-solder bridge or one stray strand across the 1.04 mm gap between 1.5 mm SMT pads. With crimp contacts in a housing, no wire-side solder joint remains on the CR. The table becomes a **connector-cavity adjacency table**, and three failure modes remain:

- a crimp inserted in the wrong cavity;
- a bridge at the hand-soldered THT header tails, at a 2.0-3.0 mm pitch;
- a bent or deformed contact.

The six adjacency exclusions still apply to the new pin map. The three open hazards (F05-F12, F07-F12 and F08-F09, DD:1305) can all be **closed by assignment**:

- The residual-row geometry that forced T22 beside T8 disappears.
- The extended exclusion set of J.2 item 63 can be adopted: no EN tap (T3, T4, T5) and no T6 beside a push-pull pad (T10, T11, T21), and T22 not beside T8.
- Spare cavities or GND cavities can separate the hazard pairs.

Four rows of the table disappear when R175 leaves the pad field: R175a-F03, R175b-F01, R175b-R175a and R175a-F07. R175 then sits in series behind the T6 cavity.

The R106s exposed-copper rule (DD A.8 r8) moves from "the F17 pad" to "the T16 header pin". The masking rules stay the same.

## 2. Proposal

### 2.1 Connector set (option A)

| Connector | Leads | Family (pitch) | Rating vs need | Wire fit | Mount |
|---|---|---|---|---|---|
| **J-TAP**, 2x12 | T1, T7b, T2, T3-T6, T8, T9, T10-T17, T17r, T20, T21, T22, F24 spare, 2 separators | Molex Micro-Fit 3.0 dual-row (3.00 mm). Alternative: 2 x JST PH 1x12 (2.0 mm) | Micro-Fit up to 8.5 A per contact by distributor listings ([Heilind](https://estore.heilind.com/mol43030-0007.html)); PH 2 A at AWG 24 ([JST PH datasheet copy](https://cdn.sparkfun.com/assets/0/e/f/7/2/ePH.pdf)). The need is <= 48.5 mA | Micro-Fit 26-30 AWG crimp TODO(verify: Molex 43030 drawing, the 26-30 AWG part number); PH SPH-002T-P0.5S takes AWG 24-30, insulation OD 0.8-1.5 mm, so T22 at 30 AWG fits | THT vertical, positive latch |
| **J-W12**, 2-pos | W1, W2 | Phoenix MC 1,5/2-G-3,81 header with MC 1,5/2-ST-3,81 screw plug (1803578) | 8 A, CSA 28-16 AWG ([Phoenix 1803578](https://www.phoenixcontact.com/gb/products/1803578/pdf)), against 2.41 A | the screw clamp does not depend on the insulation OD. This matters because the r8 W1/W2 OD is 1.60-1.75 mm (DD:480), and a crimp insulation range may not cover it, TODO(verify) | THT |
| **J-W34**, 2-pos | W3, W4 | Phoenix MSTB 2,5/2-G-5,08 (5.08 mm), TODO(verify: Phoenix rating, 18 AWG and 0.75 mmÂ² ferrule) | needs >= 3.21 A plus derating | 18 AWG fine-strand silicone | THT |
| **J-W67**, 2x3 | W7 (SCL, GND, SDA), W6 (TS_EXT, GND) | same family as J-TAP | signal | 26 / 28 AWG | THT |
| J101 (W5) | no change | FTSH 1.27 mm SMT | already removable | â€” | SMT, reflowed with the top side |

The rationale for each choice is as follows:

- **One keyed, latched J-TAP replaces 21 loose joints.** The vehicle sees 30 g (DD T-F-18b). PH and KK hold only by friction, so a positive latch is preferred.
- **Different pitches (3.81 mm and 5.08 mm) make J-W12 and J-W34 non-interchangeable.** A cross-mate would put VCHGOUT onto VCHG.
- **Screw plugs need no crimp tool.** They also keep the W1/W2 fixed build length of 0.30 m +-10 mm (D-F3) adjustable at the bench.
- **The THT headers comply with CRQ Â§5.3** (hand-soldered last). Their holes also admit a soldered wire directly as a fallback if a connector is not fitted. The THT tails protrude on the MB-facing side, so item 4.4 must count them, TODO(calc).
- **An SMT variant of each header would keep the board one-sided (Â§5.1).** However, the wire loads then rest on the solder pads alone. THT is recommended because the standoffs carry the cable loads (CRQ Â§2) only once the load reaches the board.

### 2.2 Placement

- **J-TAP:** on the +x edge, approximately y 55-75 and x 52-66, with the wire entry facing +x toward J1/J2/ROS. The run to C-D2 is about 5 mm.
- **T9 and T22:** run in the gap under the CR to the +x edge, dressed and RTV-anchored on the MB so that the seated CR cannot pinch them. If the T22 length to the +x edge is not acceptable, give T22 its own 1x2 connector at the -y edge (23 mm run). The -x edge is excluded, because the -x rejection of CRQ Â§3.3 still applies.
- **J-W34:** beside pins 18/19 and 14/15, near the present W3/W4 positions, with the entry facing +y. This keeps the 3.21 A copper short. A J-W34 on the +y edge would add about 47 mm of VCHG copper, about 12 mOhm at 2 mm width on 1 oz copper, TODO(calc: IPC-2152 width, H.11 drop).
- **J-W12:** beside the U101/D103 OUT strip, with the entry facing +y.
- **J-W67:** near pins 7/8.
- **The W leads** leave the CR at the +y edge (y 94), 4 mm from the MB +y edge (98.04) and inside the A.3 crossing band x 56-68.91. The A.3 dressing path (B1R, B3, S1-S3) is retired with the r7 tabs and must be re-derived.

### 2.3 Area estimate

The figures below come from the pitch arithmetic. Every body dimension is TODO(verify: Molex 43045, JST PH B12B-PH-K-S, Phoenix MC/MSTB drawings).

| Connector | Courtyard estimate (mmÂ²) | Basis |
|---|---|---|
| J-TAP 2x12 Micro-Fit | about 390, or about 510 with finger and latch access | 11 x 3.00 mm + ends gives about 39 x 10 mm. Two PH 1x12 give about 2 x 26 x 6 = 312 |
| J-W12 | about 60-120 | â€” |
| J-W34 | about 120-200 | â€” |
| J-W67 | about 90-130 | â€” |
| **Total** | **about 660-960** | 16-23 % of the 4212 mmÂ² gross outline |

The items that the connectors replace free about 190 mmÂ²:

- the tab X field courtyard, 14.7 x 9.62 = 141 mmÂ² (DD:1252);
- the residual row;
- the W pads and W pad exclusions.

The net demand is therefore about 470-770 mmÂ², which is 17-27 % of the 2818 mmÂ² that the new outline adds.

### 2.4 Electrical and procedural consequences

- **J-W12 adds two contact resistances to R_PATH_RG** (0.12-0.19 ohm, DD r3-11) and to the W1/W2 loop that sets the H.5 IN-peak. TODO(verify: Phoenix contact resistance; calc: H.5, H.19 re-run).
- **Hot-unplug.** Unplug only with the charger unpowered: the procedure gets a PM step. Each tap keeps its designed open-tap state (DD A.4), so a partly mated J-TAP fails safe in the same way as a lost tap.
- **Unplug J-TAP before the CR is lifted.** This protects the T22 joint on BAL pin 8 (30 AWG). T22 also gets a service loop.
- **T-F-12** changes from a check of the tap pads to a check of the cavities on the mated harness, and T-A-06 item (6) is rewritten.

## 3. Design-doc and LAYOUT_DECISIONS rows that change

- **DD A.3 W1-W7 table (lines 480-486):**
  - the CR-end termination becomes J-W12, J-W34 and J-W67;
  - the fixed length of W1/W2 is measured from the plug;
  - the dressing-path notes and the B1R wedge, B3 post and S1/S2 bead spots are retired;
  - W5 does not change.
- **DD A.4 heading and table (lines 639-682):** "tap solder field F01-F24" becomes the J-TAP pin map. The following are removed:
  - the gap path and the tab X dressing rule;
  - the F22 and F23 rows;
  - the T22 and T8 "residual row" rows.

  The maximum length of T22 and T9 is re-computed for the route under the CR.
- **DD A.8 pad table (lines 1221-1228):** the W holes and the F pads give way to the connector footprints. The tab X assignment and the six exclusions are re-stated for the cavities. **The short table (1257-1305)** is regenerated by `r7_calc.py` H.23(g) as a cavity table, with the extended set adopted (J.2 item 63 closes).
- **DD H.23(g):** re-run. **H.20:** the 26 AWG quantity changes. **E:** add the four headers, the plugs and the crimps; the 08-50-0114 status is TODO(verify: Molex, listed obsolete by RS). **PM6/PM7, T-A-06 item (6), T-F-12:** rewritten.
- **LAYOUT_DECISIONS.md:**
  - D-08: the fixed W/F pads become connector positions;
  - D-05: the F-pad net names map to cavity numbers;
  - D-31: the F22 and F23 pads are deleted, not kept;
  - D-19 and D-14: the feet and the B1R/S1/S2 rule areas go;
  - Â§4 footprint table row "W1-W4, W6/W7, F01-F24": new connector footprints;
  - P-xx: a new proposal row for the connector set.

## 4. VR-1 / D-36 conflict

The THT connectors have no SMD pads, so the conflict does not arise for them. It matters only if SMT header variants are chosen, or for the R106s and R175 vias next to T16 and T6. Until the conflict is resolved, follow CRQ Â§5.6 (no via in pad).
