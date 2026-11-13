## Assembly item (change request section 5): CR parts against the stencil-and-reflow rules

### 1. Findings

**1.1 Part census.** Every count below was extracted with pcbnew from `hardware/charger_evm_r8/cr/cr.kicad_pcb`. The script and its output are at `C:\Users\ricky\AppData\Local\Temp\claude\3fe373bc8dcb48b3\88ddad5f-e7e9-4a73-b399-a08cdcf77486\scratchpad\outline\assembly\parts.py`, with the area booking in `area.py` in the same folder. The census confirms CR Table 3 of the change request:
- six 0402 parts: R101, R103, R105 and C101 on top; R104 and R106s on the bottom;
- eight DCT parts: U105, U106, U110, U111, U113, U114, U116 and U118;
- three SC70-6 parts (U107 to U109) and two SC70-5 parts (U122, U123);
- 78 bottom parts, all passives: 74 x 0603, 2 x 0805 and 2 x 0402.

No IC is on the bottom.

**1.2 U101, TPS26630RGER.** SLVSE94G (`references/Datasheets/tps2663.pdf`) lists the TPS26630 in RGE (VQFN-24, 4 x 4 mm) only. The HTSSOP option is PWP (HTSSOP-20, 6.5 x 4.4 mm), and it exists only for the TPS26631, TPS26633, TPS26636 and TPS26637 (Package Information table, p.1). The PWP pitch is 0.65 mm ("18X 0.65", PWP0020T package outline). The RGE pitch is 0.5 mm ("20X 0.5", RGE0024H outline). This agrees with design doc line 1453. The PWP variants compare as follows (SLVSE94G Â§4, p.2):
- **TPS26633, TPS26636 and TPS26637 fail B.4.** The TPS26633 and TPS26636 have a fixed overvoltage clamp at 35 V or 39 V, and the TPS26637 has no overvoltage function. B.4 needs an adjustable cutoff at 23.12 V because the BQ25798 VBUS recommended maximum is 24 V (design doc line 1696).
- **TPS26631PWP is the only same-family PWP candidate.** It has the adjustable OVP cutoff, IMON, FLT, UVLO, MODE and the 31 mOhm FET. It differs from the TPS26630 in two ways:
  - (a) **2x pulse current support.** The device passes up to 2 x I(OL) for tCB(dly) = 20-31 ms before it regulates at 1x (Â§8.3.7.1.2 p.23; Â§6.6). Â§8.3.7.1.2 states that this support "is activated only after PGOOD goes high". B.4 ties PGTH and PGOOD to GND (line 1710), so the internal power-good state may never assert, and the part would then behave as a 1x limiter. TODO(verify: TI E2E / SLVSE94G, whether the PGOOD state with PGTH at GND blocks the 2x mode).
  - (b) **Fast-trip threshold at 3 x I(OL), not 2 x I(OL)** (Â§6.5 I(FASTRIP) rows). The B.4 fast-trip window of 4.1-4.8 A becomes about 6.2-7.2 A with R101 = 8.06 kOhm. That moves the H.5 and H.19 IN-side energy figures and the T-C-04 criteria.
  - The pin map also changes (Table 5-1 HTSSOP column): IN 1/2/3, B_GATE 4, DRV 5, IN_SYS 6, UVLO 7, OVP 8, GND 9, dVdT 10, ILIM 11, MODE 12, SHDN 13, IMON 14, FLT 15, PGTH 16, PGOOD 17, OUT 18/19/20, plus the PowerPAD.
  - The moisture rating of PWP is Level-2-260C-1 YEAR; the RGE parts are listed at Level-1 (SLVSE94G orderable addendum, p.43 onward).
- **Alternate family: TI TPS26600PWP** (SLVSDG2G, https://www.ti.com/lit/ds/symlink/tps2660.pdf), HTSSOP-16, 0.65 mm ("14X 0.65", PWP0016A). Its features against B.4:
  - an adjustable OVP cut-off (TPS26600 and TPS26601; the TPS26602 has a 38 V clamp, Â§5) and adjustable UVLO;
  - an IMON output with a gain of 72-85 uA/A, so R105, R129 and the FR-11 scaling would change;
  - a current limit of 2.11-2.35 A at R(ILIM) = 5.36 kOhm, which is its maximum setting (Â§7.5). This sits at the top of its range against the B.4 window of 2.05-2.41 A;
  - 150 mOhm RON (about 0.46 W at 1.76 A) and integrated reverse blocking;
  - a 62 V absolute maximum. B.4 requires "D107 Vc <= 60 V against the U101 IN abs max", which leaves 2 V margin here against 7 V for the TPS2663.
  
  The TPS26600PWP therefore needs its own H.5 and H.19 pass, plus T-A-05 and T-C-04. The hot-short behaviour and the MODE-open response are TODO(verify: SLVSDG2G Â§9.3, Â§9.4).
- **No other family was verified in this item.** Any other leaded 60 V eFuse is TODO(verify).

**1.3 The 0402 parts.** All six were 0402 only because of the r7 +x pocket. The r5 decision was "pocket parts 0402 top-only" (line 304), and the BOM row at line 2217 names "the 0603 parts on the bottom" as the fallback. D-32 put R104 on the bottom only because the bottom clearance rule (D-17) covered the pocket. With the new outline, change request item 4.4 (the low-mount rules re-assessed) and a top-only board, that reason disappears. All six can be 0603 on top, and the only placement rule that binds is A.8 "R103/R104 <= 5 mm from pins 7-13".

R106s dissipates <= 11.5 mW (H.23(n), line 1707). An 0603 part is rated far above that, TODO(verify: Vishay CRCW e3, doc 20035). The R106s placement rule (only the F17 pad and the R106s terminal exposed on CHG_EFUSE_FLT) does not depend on size.

**1.4 Logic and comparators.**
- **The TLV3012 is already SOT-23-6 (DBV, 0.95 mm).** The ordering BOM lists TLV3012BIDBVR and the footprint is `SOT-23-6_CrtYd0.10`. No change is needed.
- **The single gates have DBV parts.** TI lists SOT-23 (DBV) for the SN74LVC1G11 (https://www.ti.com/product/SN74LVC1G11, read 2026-11-12). The 1G08, 1G14 and 1G04 DBV parts are standard TI catalogue items, TODO(verify: orderable addenda of SCES217, SCES218 and SCES214). The pin numbering of each DBV part against its DCK part is TODO(verify: Pin Functions tables), so B.8 must be re-checked pin by pin.
- **The dual, triple and monostable parts have no SOT-23 or SOIC-8 version.** The product pages list only DCT, DCU and YZP for the SN74LVC2G08 and the SN74LVC1G123 (https://www.ti.com/product/SN74LVC2G08, https://www.ti.com/product/SN74LVC1G123). The 2G32, 3G04 and 3G06 are the same family, TODO(verify). DCT at 0.65 mm meets rule 5.5 without approval.
- **U105 uses one section of three** (B.3, line 1654: "sections 1 and 3 spare"), so a single SN74LVC1G04 in DBV does the same job.

**1.5 One-side area booking.** Table 1 gives the courtyard areas.

Table 1. Courtyard area booking.

| Item | Area (mmÂ²) |
|---|---|
| SMT parts now (top 402.7 + bottom 235.8) + J101 64.9 | 703.4 |
| Upsizing: 0402 to 0603 (+9.4), SC70 to SOT-23 (+17.9), U105 DCT to DBV (-5.0), U101 to PWP-20 (+26.6, estimate) | +48.9 |
| Lead pads W1-W4, W6/W7 | 39.7 |
| Tap pads F01-F24 | 95.0 |
| CHG pad field (J1 courtyard) | 75.4 |
| Four standoff keep-outs, assumed 7 mm diameter (as for the EIB, D-25) | 153.9 |
| **Top-side booking** | **about 1116** |
| Usable top area (outline 48.416 x 87 = 4212.2, less a 0.4 mm edge band) | 4104.5 |

The top-side booking is about 27 % of the usable area. The EIB routes at 64 % single-sided (A.9, line 1462). The r7 CR (1394 mmÂ², both sides) held the same 914 mmÂ² of courtyard, which is about 65 % of one side, and did not route. The PWP-20 courtyard estimate assumes a 6.6 x 7.3 mm land plus 0.1 mm, TODO(verify: PWP0020T example board layout).

The bottom side keeps only the receptacle bodies, which are through-hole and hand-soldered last (rule 5.3), so no second reflow is needed. Area does not decide the side question; the fixed-coordinate rules and item 4.6 (heat under the CR) do.

**1.6 Strip affected by the new -x edge.** Five bottom or top courtyards reach x < 18.584 today: R108, R131B and R176 (courtyard -x edge 18.16) and U114 and U116 (18.155). They are re-placed anyway in a top-only layout.

**1.7 VR-1 / D-36 conflict.** The open conflict matters most at the U101 exposed pad. Today the pad carries nine 0.30 mm drilled vias inside it (D-03). A PWP PowerPAD also needs thermal vias in the pad. Under change request Â§5.6 (VR-1 stays) these vias are forbidden. Under D-36 they are allowed, but with stencil and reflow an unfilled via wicks paste away from the pad. The remedies are a windowed stencil aperture plus bottom-side tenting, or vias only outside the pad, which costs thermal resistance. The ruling is needed before the U101 footprint is frozen. Elsewhere a one-side layout with ample area needs no via in a pad.

### 2. Proposal

1. Make the CR **top-side SMT only**, with all passives 0603 or larger (0805 for the existing 0.1 % divider tops). Keep the bottom (L4) as GND facing the MB switching nodes (item 4.5). The receptacle, the lead pads and any other through-hole part are hand-soldered last.
2. U101 has two options:
   - **(A, preferred if the operator accepts one 0.5 mm part)** keep the TPS26630RGER with an explicit 0.5 mm approval. This keeps every B.4, H.5 and H.19 figure.
   - **(B)** use the TPS26631PWPR, 0.65 mm, with a re-derivation of the fast-trip (3x), the confirmation of the PGOOD-gated 2x mode, a new B.8 pin map and T-A-05/T-C-04 again.
   
   The TPS26600PWP is a second-tier fallback.
3. Change the SC70 parts to DBV and U105 to a 1G04 in DBV. Keep the DCT parts.

Table 2 gives the parts-list changes. Stock and Digi-Key SKUs are TODO(verify) for every row, because the vendor pages are bot-blocked (ordering BOM notes).

Table 2. Parts-list changes.

| Ref | Now | Proposed (orderable) | Package / pitch | Note |
|---|---|---|---|---|
| R101 | CRCW04028K06FKED | CRCW06038K06FKEA | 0603 | option B keeps the value; TPS2660 would change it |
| R103 | TNPW040266K5BEED | TNPW060366K5BEEA | 0603 | <= 5 mm from pins 7-13 |
| R104 | TNPW040249K9BEED (bottom) | TNPW060349K9BEEA (top) | 0603 | retires D-32 |
| R105 | CRCW040227K4FKED | CRCW060327K4FKEA | 0603 | |
| R106s | CRCW04021K00FKED | CRCW06031K00FKEA (existing BOM line, +1) | 0603 | |
| C101 | GRM155R71H223KA12D | GRM188R71H223KA01D, TODO(verify: Murata) | 0603 | 22 nF 50 V X7R |
| U107-U109 | SN74LVC1G11DCKR | SN74LVC1G11DBVR | SOT-23-6, 0.95 | pinout TODO(verify) |
| U122 | SN74LVC1G08DCKR | SN74LVC1G08DBVR | SOT-23-5, 0.95 | |
| U123 | SN74LVC1G14DCKR | SN74LVC1G14DBVR | SOT-23-5, 0.95 | |
| U105 | SN74LVC3G04DCTR | SN74LVC1G04DBVR | SOT-23-5, 0.95 | one section used; netlist change |
| U101 (option B) | TPS26630RGER | TPS26631PWPR (TPS26631PWPT, 250-piece reel) | HTSSOP-20, 0.65 | re-derivation required |
| U106, U110, U111, U113, U114, U116, U118 | DCT | unchanged | SSOP-8, 0.65 | compliant; SOIC-14 quads (SN74LVC08A, SN74LVC32A) would merge gates and are not recommended |
| TLV3012, BAV199, SMA, 0805/1206/1210 | - | unchanged | >= 0.95 | compliant |

### 3. Rows that change

**Design doc** (`docs/charger_bq25798_wiring_design_2026-11-05.md`):
- A.8 hand-assembly bullet (lines 1452-1456): stencil plus reflow, and the U101 package decision.
- A.8 pocket rows and r5-9 (line 304): "0402 top-only".
- B.3 U105, U107-U109, U122 and U123 (lines 1654-1671).
- B.4 U101, R105 "(0402, r5)" and R106s "0402" (lines 1694, 1704, 1707).
- B.8 package pinout header and the U101 row (lines 1872 and 1884), plus R105 and R106s (lines 1888 and 1890).
- E rows 2196-2200, 2217, 2225, 2226 and 2253; the U101 row 2194.
- The H.18 area booking (line 962).

**LAYOUT_DECISIONS.md:**
- D-03: the U101 and SC70 footprint rows, and the "hand-assembled with hot air" rationale.
- D-09: the pocket table.
- D-32: retire.
- D-17, D-18 and D-19: the bottom side and the feet, retired for SMT.
- D-20 and D-36 against VR-1: the thermal-pad vias.
- D-31: the U105 netlist note.
- P-07 and P-10.

### 4. Operator questions

1. Do you approve the 0.5 mm TPS26630RGER (option A), or should the design move to the TPS26631PWPR (option B) and re-derive the fast-trip and pulse-mode behaviour?
2. Which rule holds for the U101 thermal-pad vias: VR-1 as in Â§5.6, or D-36?
3. Do you confirm a top-only SMT layout (all 78 bottom passives move to the top)?
4. Do you accept U105 changing to SN74LVC1G04DBVR, which is a netlist change?
5. Do you accept that the DCT parts stay at 0.65 mm?
6. What are the standoff hole size and keep-out? The 7 mm keep-out is an assumption: TODO(measure: operator).
