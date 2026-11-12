# CR routability options (2026-11-12)

This document lists the changes that can make the CR routable on its 4-layer OSH Park stack. Section 2 gives
the physical changes and section 3 the functional changes. Section 4 lists the constraints that fix each
footprint, so that the operator can check them against the hardware. Section 5 gives a recommended order.

The analyses are in `routability_2026-11-12/`:

- `footprint_options.md`: the physical analysis.
- `functional_options.md`: the functional analysis.
- `claim_verification.json`: ten independent checks of their load-bearing claims.

Where a check corrected a figure, this document uses the corrected figure.

## 1. Shortfall

The adopted placement (D-34) under the rulings of D-36 has the following routing state:

- Scripted routing makes 162-173 of 199 signal connections at four seeds (r2_A). The best run on the variant B
  placement makes 177.
- Plane vias placed outside SMD pads leave 31-43 GND connections open. With vias allowed in pads, the open count
  on r2_A seed 1 falls from 43 to 18. Nineteen GND fill pieces still have no via site.
- The shortfall is spread over four regions, not one choke point:
  - the comparator band (x 26-43, y 35-45, In2.Cu);
  - the region between W6/W7, D107/C125 and the VCHGOUT belt (x 33-38, y 56-62);
  - the tab Y root (x 28-34, y 67-68);
  - the U101 +x pocket (/N_DVDT and /N_OV, F.Cu).
- In2.Cu carries 62 % of the routed length. The column x 38-40 has the lowest cut capacity on every layer,
  because of the VIN_L3 strap and the VIN_L1 pour.

Round 3 of the scripted study (vias in pads allowed, divider-top metric as a soft cost) is in progress. Its
results are added in section 6.

## 2. Physical changes

Table 1 ranks the physical changes by gain against effort. "Verified" refers to the independent check.

Table 1. Physical changes.

| # | Change | Gain (measured unless marked) | Cost and risk | Verified |
|---|---|---|---|---|
| P1 | Via 0.46/0.25 or 0.50/0.25 mm in an OSH Park-only rule file; plain vias in pads | About 45 mm² per layer at 0.46 mm (32 mm² at 0.50 mm), from 258 signal vias. A GND via fits in 72 of 93 GND SMD pads at 0.46 mm (68 at 0.60 mm). | Rule file only. The ring of a 0.46 mm via is 3 µm over the OSH Park 4 mil minimum. Solder wicks into an open via in a pad. | Fab figures confirmed (docs.oshpark.com drill specs, services page) |
| P2 | Remove the unused inner pads of W1-W4 (W2/W4 keep their In1 GND tie) | 10.69 mm² on In2.Cu, at the busiest cell beside W4 and on the W1/W2 cut | Footprint flag only; D-30 applied the same change to J1 | Confirmed |
| P3 | Bottom passives 0603 → 0402 (72 parts; R176, R177 stay 0603) | Bottom courtyard −112 mm²; B.Cu cut capacity +20 to +41 % at x 24-38 (estimated with P2) | New BOM rows. C151 (330 nF X7R) has no confirmed 0402 part; if it stays 0603, the count is 71 and the gain 110.6 mm². R142 (select on test) may stay 0603. 0402 pads take only a 0.46 or 0.50 mm via in pad. | Partly: count and area corrected; voltage and value ranges confirmed |
| P4 | Comparators TLV3012BIDBVR → TLV3012BIDCKR (7), BAV199 → BAV199W (4) | About 41 mm² in the comparator band; the band booking falls from 69.5 % to about 47 % | New footprints. BAV199W pinning not yet read from the Nexperia datasheet. | Confirmed: both parts active, BAV199W leakage ≤ 5 nA at 75 V |
| P5 | LVC gates DCT → DCU (8 parts: 1G123 ×2, 2G08 ×3, 2G32 ×2, 3G04) | 50-58 mm² top area (DCU courtyard estimated), mostly on tab Y | 0.5 mm pitch; the 1G123 timing curves for DCU are not checked | Confirmed: all four DCU orderables active, same pinout |
| P6 | J1 outer pads 1.9 → 1.7 mm (or only the signal pins) | Router lanes between pins 1 → 2 per gap; up to 40 more crossings | Smaller solder fillet; 0.30 mm ring on the 1.1 mm hole | Partly: the 1.9 mm figure has no recorded source; two tracks already fit at 1.9 mm with 5 µm margin |
| P7 | 6-layer OSH Park stack (L2 and L5 GND, three signal layers) | About +40 % routing area; vias 0.41/0.20 mm; /3V3 can become a fill | $15/in² against $10/in² (about $46 against $31 per set of 3, area basis unverified); 12-21 days against 9-14 days; re-derive the stack-up, H.23(f) and C102b ≤ 2 nH rows | Fab figures confirmed |
| P8 | J101 into tab Y | J101 net straight length 211.7 → 112-127 mm | Does not fit unless FT2 moves; re-derive A.3 (W5) and H.23(l) | Not checked |
| P9 | Divider tops 0805 → 0603 | Divider-top zone −13 % | TNPW0603 stops at 332 kΩ; R102 needs ≥ 75 V | Not checked |

P1 and P2 change no part and no function. P7 is the only single change whose gain is of the same size as the
shortfall. The remaining changes give between 10 and 115 mm² each, so they act in combination.

The following physical changes give little or no gain:

- removing F22/F23/F24, which D-31 keeps;
- smaller tap pads, because tab X is not a bottleneck;
- ICs on the bottom, which A.7 excludes;
- outline extensions, which A.7 rejects for reasons other than height;
- D107 to SMF, which needs the H.19 check because SMF33A is rated 200 W against 400 W.

## 3. Functional changes

Table 2 ranks the functional changes by connections freed per unit of function lost. The counts are netlist
edits measured with a minimum-spanning-tree proxy, not routed results.

Table 2. Functional changes.

| # | Change | Connections freed | Function lost or changed | Verified |
|---|---|---|---|---|
| F0 | Move U118 into tab Y, as A.8 assigns (placement, no function change) | Wire −85 mm HPWL (−60 mm MST); FCCN, H1R, QQF shorten, RGN_ON lengthens 20 mm | None. Tab Y top has no free position today: a hand repack is necessary. | Partly: assignment confirmed, figures corrected |
| F1 | Delete R137; tie U107.6 to /3V3 | 1 (/FCI_OK) | The R137 pad is the rework point for the U117 FC-current permit if T-F-04b fails | Partly: rework point and BOM edit added |
| F2 | Remove the J1 → W6/W7 pass-through from the CR (land the I2C and TS_EXT leads elsewhere) | 3 (/SCL, /SDA, /TS_EXT) | None in the circuit; changes the A.8 fixed coordinates and the A.3/A.5 leads. Mechanics unverified. | Not checked |
| F3 | One EIB 3V3 feed: delete R177, leave J101.2 open | 2 (/J3V3_2) | A single open in R176, J101.1 or ribbon conductor 1 then latches an FR-08(b) trip (availability, not safety). Six design-doc rows change. | Confirmed with qualifications |
| F4 | Consolidate the 13 LVC packages into about 7 | 13 | No function lost. SN74LVC08A and SN74LVC32A specify no Ioff, so the B.7 back-feed guarantee needs Ioff-rated parts on CHG_ARM (U114) and FCCEIL (U116), or a bench test | Partly: Ioff gap found |
| F5 | One programmable logic device for all gate logic | About 57 | Protection stays in hardware, but power-up state, back-feed and one-shot timing must be re-proven. A GreenPAK-class part has no Ioff: every Teensy-driven input needs a series resistor. | Confirmed (no Ioff) |
| F6 | Delete the eFuse IMON readback (R105, R129, C129, F18, F19) | 4 (/N_IMON, /CHG_IIN) | The eFuse current limit is unchanged (IMON is a monitor output). Lost: FR-11, the CHG_IIN arm of FR-33, the CHG_IIN term of the bench G2 guard, and the chg_iin_ma / chg_e_in_mj telemetry | Partly: dependency list extended |
| F7 | Replace the U111 QUAL one-shot with a 3-input AND | 5 | A QUAL line stuck HIGH is no longer time-limited in hardware | Not checked |
| — | Delete the pack-OV term, ground the eFuse OVP pin, or remove the FC-charging path | 2-50 | Hardware protection becomes firmware-only, the eFuse cut-off rises to 34.3 V, or ruling R1 is broken | Not recommended |

F0 to F3 lose no circuit function. F4 loses none if Ioff-rated AND parts stay on CHG_ARM and FCCEIL. Of the
four nets open at every seed, /N_DVDT and /N_OV compete for the single F.Cu lane in the U101 pocket, and
/RFC_OFF_J and /BT_OK are long crossings. Only the not-recommended changes remove them functionally, so these
four nets remain a layout problem.

## 4. Constraints to check against the hardware

Table 3 lists every footprint or position that an outside constraint fixes, with the item the operator can
check physically.

Table 3. Fixed footprints and positions.

| Part | Fixed item | Source of the constraint | What to check |
|---|---|---|---|
| J1 (22 holes) | Positions; 1.1 mm drill; 1.9 mm outer pad | MB CHG element (A.2/A.8 hole table, D-02); Ag105 datasheet hole 1.1 ± 0.05 mm. The 1.9 mm pad has no recorded source; the MB rules give 1.65 mm | Measure the carrier-header post. Make a trial joint with a 1.7 mm pad on scrap 1 oz board. Decide whether the power pins (4, 10, 14, 15, 18, 19) keep 1.9 mm. |
| J101 | FTSH 2×7 1.27 mm SMT; region x 37.0-44.5 | W5 ribbon to EIB J201 (A.3, B.8; EIB fabricated) | Whether the W5 cable reaches tab Y, and whether FT2 can move toward −x (P8) |
| W1/W2, W3/W4 | 1.3 / 1.5 mm holes, positions | Lead gauge for 2.41 A / 3.21 A (A.8) | Whether the fab requires non-functional inner pads on 1.3-1.5 mm holes (P2) |
| W6/W7 | 1.2 × 1.5 mm SMT pads at y 57.5 | I2C and TS_EXT leads to the EVM (A.3) | Whether those leads can land on J1 or the MB instead (F2) |
| Tap pads F01-F24 | 1.5 mm on a 2.54 mm grid; F22-F24 without net | A.4, A.8 r7, H.23(g) short table; D-31 | None proposed |
| U101 | VQFN-24, centre (41.70, 63.65) | Only TPS26630 package; D-09 | None |
| C102a/b/c, D103, D107, C103 | 100 V parts; loop ≤ 2 nH | B.4, A.8, H.19 | None, unless P7 re-derives the loop |
| R101-R105 pocket | 0402; R104 within 5 mm of pin 7 | A.8 pocket row, D-32 | None |
| R102/R109/R111/R114 | 0805, 0.1 % thin film | TNPW0603 range ≤ 332 kΩ; R102 ≥ 75 V | P9 only with another 0603 series |
| FT1/FT2 | Feet positions and keep-outs | A.8 r7, MB support spots | Whether FT2 can move (P8) |
| Outline | r7 vertices | A.7 clearances to the MB parts | None (A.7 reasons are not height) |
| Bottom parts | Passives only, ≤ 1.0 mm; ≥ 1.0 mm from MB copper | A.7, D-17 | Whether "passives only" is required |
| Vias | Tented on both sides (A.8 "every L4 via tented") | A.8; R106s rule on /N_FLT and /CHG_EFUSE_FLT | The purpose of the L4 tenting rule, which decides where a via in a bottom pad is acceptable |

## 5. Recommended order

1. Apply P1 and P2 together. They change no part or function, and P1 follows the D-36 via ruling. Confirm with
   OSH Park support that an unfilled via inside an SMD pad is accepted; their documents give no policy.
2. Hand-place U118 (F0) during the interactive pass, with U105 if room allows.
3. If the board does not close, apply P3, P4 and P5 together with F1 and F3. These are package and BOM changes
   with no protection loss. F4 follows if the Ioff question is resolved.
4. If the board still does not close, move to the 6-layer stack (P7). The functional changes F5-F7 are the
   alternative, at the cost of re-proving protection behaviour.

## 6. Round 3 results

Pending.
