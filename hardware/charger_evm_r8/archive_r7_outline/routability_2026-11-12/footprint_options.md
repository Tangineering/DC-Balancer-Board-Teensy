# CR r8: physical changes for routability (read-only analysis, 2026-11-12)

Measurements come from `cr/cr.kicad_pcb` (D-34 variant A placement, pours, unrouted) with the pcbnew venv. The scripts are in this folder: `measure.py`, `cuts.py`/`cuts2.py`, `zone.py`, `pth.py`. The **cut capacity** is the number of 0.127/0.127 mm tracks that can cross a straight line through the board on one layer. It counts pads, non-GND pours, holes and keep-outs as obstacles and treats the GND pour as free. It is a geometric upper bound, not a router result. Router facts come from the r2_A/r2_B study folders. The orchestrator's `r3/seeds_ref_vip` and `seeds_soft_vip` runs (via-in-pad) were started at 08:24 and have no results yet, so this report does not predict their numbers.

## 1. Where the capacity goes (measured)

- **Free routing area** (inside the 0.40 mm edge band, net of obstacles): F.Cu 667 mm², In2.Cu 1154 mm², B.Cu 909 mm² of 1323 mm². In2.Cu already carries 62 % of the routed length (1309 of 2099 mm, r2_B seed 3).
- **Lost-to locations** (r2_A seed 3) fall into four clusters:
  - the comparator band, x 26-43, y 35-45, In2.Cu;
  - the region x 33-38, y 56-62, between W6/W7, D107/C125 and the VCHGOUT belt;
  - the tab Y root, x 28-34, y 67-68;
  - the U101 +x pocket. /N_DVDT and /N_OV are open at every seed, on F.Cu.
- **Busiest x cut**: x = 38-40 has the lowest vertical cut capacity of the body (F 21-31, In2 80-126, B 59-96). The VIN_L3 strap (In2, x 39.15-41.95, y 51.25-61.45) and the VIN_L1 pour cause it, together with D107 and C125.
- **/3V3**: 57 pads with no pour. It uses 226 mm of track and 40 vias, which is 11 % of the track length and 15 % of the signal vias.
- **Signal vias**: 258 of them at 0.6/0.3 mm. Each via removes a 0.854 mm disc (via + 2 × clearance) on every layer, about 148 mm² per layer in total.

## 2. Proposals, ranked by gain/effort

### P1. Via geometry at the OSH Park 4-layer minimum, with via-in-pad (rule file only)

1. **Change.** The rule file `fab_4layer_5mil_oshpark_pcbway.kicad_dru` takes the PCBWay annular ring of 0.15 mm, so the minimum via is 0.554/0.254 mm, and the router uses 0.60/0.30 mm. The OSH Park 4-layer page (read 2026-11-12) gives a 10 mil drill and a 4 mil (0.1016 mm) annular ring, so the minimum via is **0.46/0.25 mm**. A 5 mil ring gives **0.50/0.25 mm**. Now that the fab is OSH Park only, an OSH-only rule file is needed.
2. **Gain.** The via disc shrinks from 0.854 to 0.714 mm, which is 30 % less blocked area per via. At 258 vias, this frees about **45 mm² on every layer** (32 mm² at 0.50 mm). A via site needs a 0.714 mm gap instead of 0.854 mm. Two vias with one track between them need a 0.841 mm pitch instead of 0.981 mm. Via-in-pad also gives a GND via site in **72 of 93 GND SMD pads** at 0.46 mm (68 at 0.60 mm). These are the pads with a smallest dimension of at least the via diameter. For signals, 211 of 301 SMD pads can take a 0.46 mm via (203 at 0.60 mm). The 21 GND pads that cannot are 12 DCT gate pins, 6 SC70 pins and 3 VQFN pins, all 0.25-0.40 mm wide. Their pour pieces still need a via beside the pin.
3. **Cost and risk.** There is no BOM or placement change. The ring is at the fab minimum with no margin, and whether "10 mil" is drilled or finished size is open (TODO(verify: OSH Park), LAYOUT_DECISIONS §11 item 5). An unfilled via in a hand-soldered pad wicks solder. A 0.25 mm drill wicks less than 0.30 mm, and an off-centre via at the outer pad end reduces it further.
4. **Primary constraints.**
   - D-20 sets "0.6/0.3, TOOLCHAIN 0.3 mm drill" and tenting on both sides. A via in a pad cannot be tented on the pad side.
   - A.8 r8 R106s rule: every via on /N_FLT and /CHG_EFUSE_FLT must be tented on both sides. Exclude these nets from via-in-pad.
   - A.8 VCHG-IN rule: the copper must be solder-masked with no exposed pad. Exclude power nets.
   - A.8 "every L4 via tented": operator check whether this rule targets exposed copper facing the MB. Bottom SMD pads are exposed copper anyway, and the bottom clearance rule covers them.

### P2. Remove the unused In2 (and In1) pads of W1-W4 (footprint fix)

1. **Change.** D-30 removed the inner-layer pads of J1 only. W1 (/VCHGOUT), W2 (/GND), W3 (/VCHG) and W4 (/GND) still flash full 2.3/2.5 mm pads on In2.Cu, although no In2 zone connects them (`pth.py`; the only In2 zone is VCHGIN_L3_strap). Set `remove_unused_layers` and `keep_end_layers`.
2. **Gain.** The In2 obstacle shrinks from about 2.55-2.75 mm to about 1.81-2.01 mm. This frees **10.7 mm² on In2.Cu**, mostly at the 0.90-utilisation cell (24.65, 55.05) beside W4 and at the W1/W2 pair on the y 61.2 cut. Measured together with P3: In2 free area +11 mm², and In2 crossings at y 60 rise from 137 to 146 tracks.
3. **Cost and risk.** None known. The barrel carries the current between L1 and L4.
4. **Primary constraints.** The A.8 hole table sets the W1/W2 hole at 1.3 mm and the W3/W4 hole at 1.5 mm, from the lead gauge for 2.41 A and 3.21 A. The inner pads have no stated reason.

### P3. Bottom passives 0603 → 0402

1. **Change.** 74 bottom 0603 parts (46 R, 28 C) go to 0402. R176 and R177 stay 0603: they are 200 Ω on the ribbon 3V3, which dissipates 54 mW into a short against 63 mW for CRCW0402. C125 and C150 (0805) are optional; C150 is a timing capacitor, so keep it.
2. **Gain.**
   - Measured courtyard: 0603 = 3.01 mm², 0402 = 1.45 mm². The bottom courtyard falls from 222.7 to about 107 mm², a **115 mm²** gain, against the 569.1 mm² of bottom area under the bottom clearance rule.
   - B.Cu free area rises from 909 to **990 mm² (+81 mm², +8.9 %)**.
   - B.Cu cut capacity at x = 38 rises from 59 to 83 tracks, at x = 24 from 95 to 124 and at x = 32 from 104 to 125 (+20 % to +41 %). These are the comparator and divider columns. The two figures include P2.
   - Smaller bottom pads also leave more via landing sites beside each pad.
3. **Cost and risk.** The parts must be reordered (BOM rows). Hand assembly is unchanged in kind: the +x pocket already uses 0402. Coupling with P1: a 0402 pad (0.54 mm) admits a 0.46 or 0.50 mm via in pad but not a 0.60 mm via. TODO(verify):
   - 0402 availability for 100 nF/50 V X7R, 470 pF and 1 nF C0G, and 10 nF/50 V X7R;
   - CRCW0402 reaching 6.49 MΩ (R113) and 10.0 MΩ (R116); the design notes that CRCW0603 stops at 10 MΩ;
   - the TNPW0402 range for any 0.1 % bottom part (R178/R179 class).
4. **Primary constraints.** A.7 "bottom-side parts passives only, ≤ 1.0 mm tall (0603/0805)" is met by 0402. The r3/r7 courtyard bookings (H.23(e)) are 0603-based and remain valid as an upper bound. The A.8 bottom set lists 0603, and E (BOM) sets the packages.

### P4. Comparators and clamps to SC70 packages (top, comparator band)

1. **Change.** U102-U104, U115 and U119-U121 go from TLV3012B in DBV (SOT-23-6) to DCK (SC70-6). D104-D106 and D108 go from BAV199 (SOT-23) to BAV199W (SOT-323).
2. **Gain.** Measured courtyard: SOT-23-6 10.20 → SC70-6 6.22 mm², so 7 × 3.98 = **27.9 mm²** in the band, which is a lost-to cluster. SOT-23 9.52 → SOT-323 about 6.2 mm², so 4 × 3.3 = about 13 mm². The band books 69.5 % today (H.23(e2)) and would book about 47 %.
3. **Cost and risk.** TODO(verify: SBOS300C package table): whether the B grade exists in DCK with the same POR and fail-safe-input specification. TODO(verify: Nexperia BAV199W): the leakage matches BAV199 (B.2 uses its low leakage). The pitch is 0.65 mm in both cases, so hand assembly is unchanged.
4. **Primary constraints.** B.2 (part choice, push-pull, POR) and E. The band position is fixed by H.23(f) distances, not by package.

### P5. LVC gates DCT (SSOP-8, 0.65 mm) → DCU (VSSOP-8, 0.5 mm)

1. **Change.** The 8 DCT parts are U105, U106, U110, U111, U113, U114, U116 and U118 (SN74LVC3G04, 2G32, 1G123, 2G08). They change to the DCU variants. TODO(verify: TI orderables), for example SN74LVC2G08DCUR.
2. **Gain.** The DCT courtyard is measured at 15.22 mm² each (121.8 mm² total, the largest IC class). The DCU courtyard is estimated at 8-9 mm² (TODO(verify: TI DCU0008A land)), so the gain is **about 50-58 mm² of top area**. Five of the gates sit on tab Y top, where the booking is 73.45 % and the tab Y root is a lost-to cluster. Merging gates into multi-gate packages gains nothing: area per gate is 7.6 mm² (2G in DCT), 7.2 mm² (1G in SC70-5) and about 9 mm² (quad TSSOP-14). Merging would also concentrate the crossings.
3. **Cost and risk.** The pitch falls to 0.5 mm. U101 already needs hot air, so this adds no new capability. The pad widths of about 0.25-0.30 mm do not admit via-in-pad, so the GND pins need adjacent vias. The SN74LVC1G123 timing (N_RC/N_CX) is unchanged, but TODO(verify) the DCU datasheet curves.
4. **Primary constraints.** B.3 and E fix the part numbers. A.8 tab Y lists the gate set.

### P6. CHG header outer pads 1.9 → 1.7 mm

1. **Change.** The 22 J1 pads go from 1.9 to 1.7 mm on F.Cu and B.Cu. The inner pads were already removed (D-30).
2. **Gain.** The gap between pads grows from 0.64 to 0.84 mm, so **1 → 2 tracks per gap** on each outer layer. Two tracks need 0.635 mm. The two columns have 20 gaps, so up to 40 extra outer-layer crossings. This matters mainly for the x 45.998 column, which the tab X nets (about 17) must cross between pins 7-10 or around the U101 pocket.
3. **Cost and risk.** The annular ring falls from 0.40 to 0.30 mm on a 1.1 mm hole with a 0.64 mm square post, which leaves a smaller hand-solder fillet. Thermal relief to the GND pins (J1 pin 4 is already a starved thermal) gets harder.
4. **Primary constraints.** The A.8 hole table says "drill 1.1 mm, plated, pad ≥ 1.9 mm". D-30 records a TODO on whether the rule targets the outer layers. The drill comes from the Samtec TSW post (TODO(verify: TSW footprint)). Operator check: whether the 1.9 mm came from a solder-joint or current requirement (pin 10 carries 2.41 A and pins 18/19 carry 1.93 A each); if it did, exempt those pins.

### P7. 6-layer stack-up (OSH Park 6-layer prototype)

1. **Change.** The OSH Park 6-layer service (read 2026-11-12) gives 5/5 mil, an **8 mil drill**, a 4 mil ring, 1 oz outer and 0.5 oz inner copper and 1.6 mm thickness. The 4-layer service has a 0.10 mm L1-L2 dielectric and a 0.93 mm core. A suggested stack:
   - L1: signals and power pours;
   - L2: GND;
   - L3: signals;
   - L4: signals, or /3V3 fills plus signals;
   - L5: GND;
   - L6: signals, the GND pour and the VCHGOUT strap.
   The vias become **0.41/0.20 mm**, which also fit the 0.40 mm DCT/SC70 GND pins.
2. **Gain.**
   - One more full inner routing layer: about +1150 mm² of free area, about **+40 % of total routing area**, on the layer type that already carries 62 % of the length.
   - The via disc is 0.664 mm (−40 % in area against 0.6/0.3 mm).
   - /3V3 can leave the signal layers as a fill (226 mm and 40 vias today).
   - The VIN strap on L3 sits 0.10 mm over L2 GND instead of 0.2 mm over the L4 pour, so the C102b loop inductance falls; this needs re-derivation.
3. **Cost.** $15/in² against $10/in². For the 47.30 × 41.86 mm bounding box (3.07 in²), a set of 3 costs **about $46 against $31**, assuming OSH Park bills the bounding rectangle (TODO(verify: OSH Park area basis)). The lead time is 12-21 days against 9-14 days, and there is no Super Swift service.
4. **Risk.** The A.8 stack-up row (r7) and the D-20 stack-up, the H.23(f) coupling figures and the A.8 C102b ≤ 2 nH row must be re-stated. Inner copper stays 0.5 oz, so the D-29 IPC-2152 TODO is unchanged. The 10 mil drill-to-inner-copper rule is unchanged. The thickness is 1.6 mm, so the header-stack figures (H.23(j)) hold. Primary constraint: the operator ruling of 2026-11-11 (4-layer OSH Park) and A.8 "Stack-up (r7)".

### P8. J101 into tab Y (placement relief; highest effort)

1. **Change.** Six of the nine J101 signal nets end in tab Y: J3V3_1/2, ILIM_REL_A/B, RFC_OFF_J and CE_DRV_J, at R130-R132 and R176/R177. With J101 rotated into tab Y, the straight length of the J101 nets falls from **211.7 to 112-127 mm (−40 % to −47 %)**. Six nets leave the y 52-67 crossing band, which holds the two 0.78-0.84 cells at y 57. STAT gets longer (6 → 28-30 mm).
2. **Gain.** The six nets no longer cross the congested band, and the J101 region (65 mm², interior) frees for gates.
3. **Cost and risk.** The rotated courtyard (9.31 × 7.15 mm) does **not fit** beside the FT2 fill-hole disc: it needs centre x ≥ 33.66 to clear the disc and centre x ≤ 32.4 to stay inside the tab. It fits only if FT2 moves, or if DCU gates (P5) and a moved FT2 free the room. Unrotated, the part crosses into the OUT strip (D103).
4. **Primary constraints.**
   - A.8 J101 region and the r4/r5 findings efuse-cluster-no-room-at-pad10 and j101-mated-socket-envelope;
   - the A.3 W5 route and the S1/S2/S3 bead spots (H.23(l));
   - the A.8 FT2 keep-out (x 25.5-30.5, y 70.75-75.75);
   - the tab Y top booking (H.23(e2)).
   Operator check: whether FT2 can move toward -x, and whether the FFSD socket (13.08 × 3.05 × 5.08 mm) can stand on tab Y with W5 leaving toward its current path at y 73.1.

### P9. Divider tops 0805 → 0603 (small)

1. **Change.** R102, R109, R111 and R114 go to 0603.
2. **Gain.** The divider-top zone (pad hull + 2 mm) shrinks from 95.5 to **83.2 mm² (−13 %)**, measured. J1.7 /SCL, U103.5 and two analog pads leave the zone. The logic pads in the zone fall from 10 to 9.
3. **Cost and risk.** The E BOM notes that TNPW0603 stops at 332 kΩ (Vishay doc 28758), and the parts are 442 kΩ-1 MΩ at 0.1 %/25 ppm. The change needs another 0.1 % thin-film series that reaches 1 MΩ in 0603 (TODO(verify)), or lower-impedance dividers. Lower-impedance dividers change B.2 and the R170/R171 joint ratio. R102 also needs at least 75 V working voltage (TVS clamp 53.3 V), so 0402 is excluded.
4. **Primary constraints.** E (r2 finding bom-resistor-mpns-out-of-range) and the A.8 Analog row. A cheaper relief for the same metric is placement: move R109/R111/R114 to the -x end of the divider strip, away from J101 x ≥ 37.

### P10. Not recommended or low gain

- **Remove the no-net pads F22/F23/F24.** The gain is 4 mm² each; F22 sits beside U118 in the comparator band. D-31 rules that they stay, so this needs an operator reversal.
- **Shrink the tap pads below 1.5 mm.** Tab X is not a bottleneck: the x = 49 cut has 109 tracks for about 20 crossing nets. The A.8 short table is built on the 1.04 mm gap.
- **ICs on the bottom.** A.7 says "passives only, ≤ 1.0 mm". DCU parts are 0.9 mm tall (TODO(verify)) and tab Y bottom has 133 mm² with no MB non-GND copper. This is an option only if the operator relaxes "passives only".
- **Outline extensions.** A.7 rejects every zone for reasons other than height: J-FC/J-NTC access, rework points, boost switching nodes, and the 34.2 mm cantilever. This is unchanged by the no-height ruling.
- **D107 SMA → SMF.** The gain is about 10 mm² in the x 37-39 column. SMF33A is 200 W against the 400 W of SMAJ33A, so the H.19 IN-spike check must be re-run first.

## 3. Parts whose footprint or position is fixed by an outside constraint

| Part | Fixed item | Constraint and source | Relaxable? |
|---|---|---|---|
| J1 (22 holes) | positions, 1.1 mm drill, 1.9 mm outer pad | MB CHG element at (47.498, 34.544) R180 (A.2/A.8 hole table, D-02); Samtec TSW-110/112 post; A.8 "pad ≥ 1.9" | Positions no. Outer pad to 1.7 mm possibly (P6); check solder joint and current per pin |
| J101 | FTSH 2×7 1.27 mm SMT, no pin 6; region x 37.0-44.5, y 42.13-51.53 | W5 FFSD-07 IDC cable to EIB J201 (A.3; EIB fab package done); B.8 pinout; A.8 region | Pitch or pinout: only with an EIB respin. Position: P8, if FT2 and W5 dressing allow |
| W1/W2 | 1.3 mm hole, 2.3 mm pad at (30.3/27.7, 61.2) | A.8 r5; VCHGOUT/GND lead to the EVM, 2.41 A; MB copper | Inner pads yes (P2); hole and position no |
| W3/W4 | 1.5 mm hole, 2.5 mm pad at (24.3, 45.4/55.6) | A.8 r4; 3.21 A battery-side lead | Inner pads yes (P2) |
| W6/W7 | 1.2 × 1.5 mm SMT, y 57.5 | A.8; I2C and TS_EXT leads to the EVM (A.3 west group) | Pad size possibly; check the lead gauge |
| F01-F21 tap pads | 1.5 mm on a 2.54 mm grid, tab X (r7 assignment) | A.4, A.8 r7, H.23(g) short table, T-F-12 | Not without re-running H.23(g) |
| F08/F09/F10 | low row y 35.80 | A.8 residual pads; MB tap routes (A.4) | No |
| F22/F23/F24 | no net | D-31 ruling | Removal needs the operator |
| R175 | 1206 at (50.80, 62.75) | A.8 r7 (R175a/b grid rows); 68 Ω limiter, short power | No |
| U101 | VQFN-24 RGE, centre (41.70, 63.65) | Only TPS26630 package (A.8 hand assembly row, SLVSE94G); D-09 | No |
| C102a/b/c, D107, D103, C103 | 1206/1210/0603 100 V, SMA | B.4 voltage ratings; A.8 loop-inductance rows (≤ 2 nH); H.19 | D107 to SMF only after H.19 |
| +x pocket R101/R103/R105/C101, R104 (bottom) | 0402; R104 within 5 mm of pin 7 | A.8 pocket row; D-32 | No (0201 is not hand-friendly) |
| R102/R109/R111/R114 | 0805, 0.1 % TNPW | E: TNPW0603 range ≤ 332 kΩ; R102 voltage | P9 conditions |
| FT1/FT2 | feet; keep-outs (61.72, 66.705) and (28.00, 73.25); FT2 1.0 mm NPTH + 2 mm disc | A.8 r7 (machined feet, MB support spots), B.8 Mechanical | FT2 position only with the A.8 foot re-check (blocks P8) |
| Outline | r7 vertices V1-V11 | A.7: L-FC 0.862 mm, ROP1-FC 0.501 mm, MDAC-FC, REG-5V, C-D2 clearances; rejected zones | No (A.7 reasons are not height) |
| Bottom parts | passives ≤ 1.0 mm; ≥ 1.0 mm from MB non-GND copper | A.7 controlled interface, bottom clearance rule (D-17) | Height met by 0402; "passives only" is an operator question |
| VIN_L3 strap (In2), VOUT L4 strap | 2.8 mm straps | D-21/D-22, A.8 C102b ≤ 2 nH | Only by re-deriving the loop budget (moves with P7) |

## 4. Suggested test order

1. P1 + P2 together (rule file and footprint flags only). Run them as a route-race arm at 0.46/0.25 and at 0.50/0.25 against the r3 via-in-pad control.
2. P3 (packer re-run, BOM).
3. P4 + P5 if the datasheet checks pass.
4. P7 if 1-3 do not close the board. P7 is the only proposal that adds capacity on the scale of the shortfall (22 signal + 27 GND connections open).
