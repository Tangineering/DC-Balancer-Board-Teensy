# Ordering BOM for the BQ25798 charger retrofit (design r8), 2026-11-11

## 1. Scope

This folder holds the ordering bill of materials for one build of the BQ25798 charger retrofit
described in `docs/charger_bq25798_wiring_design_2026-11-05.md` (revision r8), updated for the
operator decisions of 2026-11-12 (r9 BOM edit, section 8). One build is one carrier board (CR), one
EVM interface board (EIB), two BQ25798EVM modules, the EVM rework of section C and the motherboard
(MB) rework of section D.1. Nothing has been ordered.

The folder contains three files:

- `ordering_bom.csv`, the ordering list (102 rows after r9-12, section 8.5; **superseded in r9:** 101 rows; 113 before the r9 edit);
- `footprint_relevant_choices.md`, the land-pattern facts for the parts that constrain the PCB capture;
- this README.

## 2. Method

### 2.1 Source of rows and quantities

Every row comes from design section E (lines 2185-2291), as amended by the r9 decisions of
2026-11-12 (section 8). The order quantity in `BOM Qty` is the
section E quantity plus the listed spare: "1 (+1)" gives 2. The `Notes` cell of each row states
"design qty N + spare M". Rows with an identical MPN are merged, and all reference designators are
listed in `PCB Names`. Two merges cross section E rows:

- CRCW060347K0FKEA carries the nine CR/EIB 47.0 kOhm parts and EVM R272 and R272b.
- CRCW06031K00FKEA carries the nine 1.00 kOhm parts, R106s included (r9: R106s moved from 0402 to 0603).

(**superseded in r9:** CRCW06031K00FKEA also carried the two 1.00 kOhm values of the R142 kit, and
CRCW06030000Z0EA carried R137 and EVM R21. The R142 kit and R137 are removed; the 0 Ohm row now
carries EVM R21 only.)

The EVM rework row of section E lists one spare for five parts of different value. This BOM
allocates that spare to the 0 Ohm link. The allocation is a BOM choice and the operator can move it.

### 2.2 Format

The CSV copies the 35 columns and the summary cells of
`references/Scale Car Design PCB BOM 20260622.csv` (42 fields per line, CRLF). `Ready to Order`,
`Ordered` and `Received` are FALSE on every row. Electrical columns are blank except
`Voltage Max [V]` where the rating was read or is set by the part code.

The summary cells have these definitions:

- **Total Assembly Cost** is the sum of `Assembly Cost` over rows with a known price. No price was verified (section 3), so every row is excluded and the total is USD 0.00. The total is therefore not a cost estimate. Design section E gives a budget of USD 520-630 including the EVMs.
- **PCB components** (98; 154 before r9) is the count of fitted reference designators on the CR and the EIB, excluding the solder pads W1-W7, E1-E8 and the tap field F01-F24. J1 (the CHG header pair) counts once. Spares, kit values, EVM and MB rework parts, wire, materials and hardware are not counted. The r9 figure was computed from the `gen/netlist.py` r9 working copy (78 CR entries, 46 EIB entries) with the EIB DNP set of section 8.4 applied: 72 CR parts and 26 EIB parts. The same computation on the r8 netlist reproduces 154.
- **PCB unique parts** (52 after r9-12, section 8.5; **superseded in r9:** 51; 60 before r9) is the count of distinct MPN strings among those fitted CR/EIB parts, by the same computation.

### 2.3 Build quantity basis

The quantities are for one build. The PCB rows (5 CR, 5 EIB) follow section E, which orders five
boards of each. Wire and tape are bought in the vendor's sellable unit, which is a 100 ft (30.5 m)
spool for every wire row and a roll for the tape rows. Each wire row states the length that the
build needs.

## 3. Verification status

### 3.1 Vendor pages were not readable

Digi-Key, Mouser, Newark, Arrow and Octopart returned bot-check or HTTP 403 pages to the built-in
browser on 2026-11-11. The CAPTCHA pages were not bypassed. The TI product and tool pages loaded,
but their ordering sections (price and inventory) did not render. As a result:

- **No row is fully verified** (MPN + SKU + price + stock read on a live vendor page).
- Every `Cost / BOM Unit`, `Assembly Cost` and `MOQ` cell is blank, and `Pricing Status` is "not verified" on every row.
- 20 rows carry a Digi-Key SKU and 28 rows a Digi-Key product URL (24 and 36 before r9) that come from the digikey.com search-engine index, not from a live page. The `Notes` cell of each such row says so. Confirm every SKU on the live page before ordering.
- Rows without an indexed product page use the Digi-Key keyword-search URL as `Link` and leave `Vendor SKU` blank.

Search-index snippets sometimes showed prices and stock levels. These figures are undated and are
not used in any cell. They appear in `Notes` only where they reveal an availability risk.

### 3.2 Datasheet reads

The following datasheets were read as text and support the figures in the CSV:

- Vishay TNPW e3, doc 28758 (rev 10-Apr-2026): resistance ranges, power and packaging codes.
- Vishay D/CRCW e3, doc 20035 (rev 14-Apr-2026): resistance ranges and power.
- ST STPS2H100, DocID6115 Rev 8: ratings, leakage and SMA land.
- Littelfuse SMAJ series, rev BA.10/21/20: SMAJ33A characteristics and SMA land.
- Samtec FTSH (F-226) and FFSD catalogue sheets: option codes, sizes and envelopes.

The `Datasheet` URLs of the other rows follow the manufacturers' URL patterns and were not opened.
They are TODO(verify).

### 3.3 Spec confirmations requested in the brief

| Item | Result | Source |
|---|---|---|
| TNPW060366K5BEEA, TNPW060349K9BEEA (r9; were TNPW040266K5BEED, TNPW040249K9BEED) | In range: 0603, 0.1 %, 25 ppm/K covers 3.5 Ohm to 332 kOhm (**superseded in r9:** 0402 covers 47 Ohm to 100 kOhm; ED is the 0402 packaging code) | doc 28758 |
| TNPW0805487KBEEA, 442K, 845K, 1M00, 10K0 | In range: 0805, 0.1 %, 25 ppm/K covers 3.5 Ohm to 1 MOhm | doc 28758 |
| TNPW060356K2BEEA, TNPW0603104KBEEA | In range: 0603 covers 3.5 Ohm to 332 kOhm | doc 28758 |
| CRCW06033M30FKEA, CRCW060310M0FKEA | In range: 1 %, 100 ppm/K covers 10 Ohm to 10 MOhm (10.0 MOhm is the top) | doc 20035 |
| CRCW04021K00FKED power (r9: R106s is now CRCW06031K00FKEA) | P70 = 0.063 W (standard) / 0.10 W (extended); the design 11.5 mW is 18 % of 0.063 W. The 0603 P70 figure was not read: TODO(verify: doc 20035) | doc 20035 |
| C102a voltage | 100 V (part code and distributor listings; the Murata sheet was not read) | index |
| C102b voltage | 100 V (part code and distributor listings; the TDK sheet was not read) | index |

## 4. Candidate MPNs pending the T-A-05 datasheet check

Section E names every MPN as a candidate that T-A-05 checks before ordering. The following rows
are new choices made for this BOM and carry "candidate - T-A-05 datasheet check required":

| Ref | Chosen MPN | Basis |
|---|---|---|
| D103 | ST STPS2H100A (SMA) | 100 V; IFSM 75 A (10 ms sine), which meets the >= 75 A limit with zero margin; IR max 1 uA at 25 C and 1 mA at 125 C. The IR at 23.6 V and 60 C is not tabulated and must be read from the IR(VR) curve. |
| D107 | Littelfuse SMAJ33A (SMA) | VRWM 33 V; VBR(min) 36.70 V; Vc 53.3 V at 7.5 A; IR max 1 uA at VRWM and 25 C. The IR at 60 C is not tabulated. |
| J101 | Samtec FTSH-107-01-L-DV, ordered with the polarized-position option (position 6 omitted) | The FTSH OPTION field -"XXX" omits a specified pin at the factory. The body length of 8.89 mm fits the 9.4 mm courtyard. The body width is not on the catalogue sheet. |
| J201 | Samtec FTSH-107-01-L-DV-K | The keying shroud (-K) mates with the FFSD notch (-N). It is valid for 05-25 pins per row in style -01. |
| W5 | Samtec FFSD-07-D-12.00-01-N | 12.00 in, double end, notch polarization. 07 is outside the standard FFSD size list but is built to order. |
| W5 key | Not identified | The FFSD sheet lists no hole plug. A Samtec enquiry is required. |

The r9 rows below are also candidates that T-A-05 checks before ordering:

| Ref | Chosen MPN | Basis |
|---|---|---|
| U107 | TI SN74LVC1G11DBVR | dec2-assembly rule 2b (single gates to SOT-23 DBV). The DBV pinout against the DCK pinout is TODO(verify: TI Pin Functions table); B.8 is re-checked pin by pin. |
| C101 | Murata GRM188R71H223KA01D | Part number from the dec2-assembly record; TODO(verify: Murata). |
| J102 (J-TAP) | Molex Micro-Fit 3.0 2x5 THT header, 43045 series | The exact P/N is TODO(verify: Molex 43045 series exact P/N); orientation, pegs or locks and cavity numbering follow the Molex drawing. |
| J-TAP lead set | Molex 2147581101 | Operator choice (in stock). Circuits, wire gauge, length and housing P/N are TODO(verify: Molex 2147581101). |
| CHG stack | Samtec TSW-110-07-L-S, TSW-112-07-L-S (CR); SSQ-110-01-L-S, SSQ-112-01-L-S (MB) | `decisions_2026-11-12/cr_decision_mating_connector_2026-11-12.md` item 4. The SSQ sheet was not opened. |

The section E candidates C102a (GRM31CR72A105KA01L), C102b (TDK C3225X7S2A475K, completed to
C3225X7S2A475K200AB) and C102c (GRM188R72A104KA35D) also remain subject to T-A-04/T-A-05.

## 5. Availability flags

The following rows have an availability or obsolescence flag from distributor listings (search
index, undated). Each row keeps the design MPN and names the nearest drop-in alternative in
`Notes`:

- **Molex 08-50-0114** (W7 crimp) is shown as obsolete. The alternative is 08-50-0113 (same terminal, reel or cut tape). TODO(verify).
- **Murata GRM31CR72A105KA01L** (C102a) is marked NRND by aggregators. The alternative is TDK C3216X7R2A105K160AA. TODO(verify).
- **TDK C3225X7S2A475K200AB** (C102b) is marked "not suitable for new designs" by one distributor, with zero stock. The alternative is Murata GRM32ER72A475KA35L. TODO(verify) the DC bias at 23.6 V.
- **TI TPS26630RGER** (U101) showed zero Digi-Key stock in one snippet.
- **Nexperia BAV199,215** showed zero Digi-Key stock in one snippet. Digi-Key lists BAV199-7-F and BAV199LT1G as substitutes; leakage equivalence is a T-A-05 item.

## 6. Parts deliberately not included

The following DNP parts are excluded: R106, R134, R145, R146, C105, C124, C127, C152, U112
(TPS22810DBVR), U117 (TLV3012), R160, R161 (and its select-on-test kit), R162, R163, D101
(BAT54HT1G), R_KA, R172, F101 and the fallback-2 fused link kit. The EVM R20 removal needs no
part.

r8-17 (2026-11-12, D-38): the T22 input stage (R178, D108, R179, U123), the AND gate U122, their
decouplers C134 and C135, and the 30 AWG Kynar wire for T22 are removed by operator ruling. Pack-voltage
protection moves to firmware. The SN74LVC1G08 and SN74LVC1G14 rows and the 30 AWG wire row are deleted, and
the BAV199, 100 kOhm, 1.00 MOhm and 100 nF quantities are reduced.

r9 (2026-11-12): the tap-review removals, the dec2-gate 5-LVC mapping, the EIB DNP set, the
retired polyimide sheet and the removed thermocouple delete further rows; section 8 lists them. The
B.5 keep-alive parts (U112, C152, D101, R_KA) and U117 with R160-R163, C127 and C124 were already
absent from this BOM (DNP tiers 2 and 3, D-31); the dec2-assembly ruling retires them, so they stay
excluded. The EIB DNP parts (U203, U204, C203, C204, R258-R265) are not ordered.

The optional MB overlay wire of section E is included, because section E lists a quantity for it.
It is cut from the 24 AWG bus-wire spool, the same stock as the T-F-13 fallback wire.

## 7. TODO(verify) list

1. Confirm every Digi-Key SKU, price, stock and MOQ on the live page. No value in this BOM was read on a live vendor page.
2. Confirm the TI store price and stock of BQ25798EVM (section E: USD 156.45, 162 in stock on 2026-11-05).
3. J101: obtain the Samtec suffix string for "position 6 omitted" and the body width of the -DV header, and confirm it fits 3.9 mm (x).
4. J201: obtain the -K shroud envelope.
5. W5: confirm the FFSD-07 build, the notch orientation and the conductor-1 marking at both ends. Obtain a hole-6 polarizing plug from Samtec or rule on the -K shroud for J101.
6. D103: read IR at 23.6 V and 60 C from the STPS2H100 IR(VR) curve, and the VF at >= 20 A pulse.
7. D107: confirm IR at 23.6 V and 60 C.
8. C102a and C102b: read the DC-bias curves and confirm availability. Choose the alternatives if needed.
9. BSS84LT1G: confirm |VGS(th)| max <= 2.0 V.
10. The R142 kit MPNs (604R, 715R, 825R, 1K21, 1K40) follow the CRCW part-number scheme. Confirm that each listing exists.
11. W1/W2: the Alpha 3053 stranding is 10/30, not 19/32 or 7/28 as the r8 spec names, and its 1.75 mm OD sits at the top of the window. Obtain an operator ruling or an alternative.
12. W3/W4: confirm that the Alpha 5857 conductor diameter is <= 1.35 mm. Consider a shorter or less expensive PTFE source.
13. 28 AWG Kynar: the Jonard R28 spools appear to be solid. Stranded 7/36 is preferred. Confirm the strand count.
14. Alpha 297 and 296 bus wire: obtain the length suffix of the smallest put-up.
15. Withdrawn in r9: the polyimide sheet is retired (stack-up decisions section 2), so the CAPLINQ PIT5S row is deleted.
16. DOWSIL 3145: confirm the alkoxy cure and the "non-corrosive to copper" statement in the Dow TDS.
17. 3M 467MP (B1R wedge bond only after r9-5): confirm the listing size and pack quantity, and the 0.05 mm thickness for that SKU.
18. Ferrule counts (10 each assumed) and the Phoenix order number for the loose AI 0,5-8 WH.
19. Heat-shrink kit, 6 x 6 mm and 10 x 10 mm adhesive tie bases: no MPN identified.
20. Workshop items: obtain stock and costs for the B1R wedge, the posts, the off-CR support, the EVM plate and clamps and the silicone pads (r9-5: the FT1/FT2 feet and the bond coupon are withdrawn).
21. CR and EIB PCB: obtain fab quotes.
22. Open every `Datasheet` URL that was not read (section 3.2).
23. r9: confirm the Molex 43045-series header P/N, its orientation, pegs and cavity numbering, and the Molex 2147581101 circuits, wire gauge, length and housing P/N.
24. r9: confirm SN74LVC1G11DBVR (DBV pinout) and GRM188R71H223KA01D (Murata) on the manufacturer pages.
25. r9: confirm the TSW-110/112-07-L-S and SSQ-110/112-01-L-S listings; the Digi-Key SKUs of the earlier -G rows no longer apply.
26. r9: rows that this edit did not change but that the 2026-11-12 decisions make stale: the FT1/FT2 feet, the DOWSIL 3140 FT1/FT2 bed and the 3M 467MP FT1/FT2 bond (feet retired with the plug-on outline), the bond coupon (polyimide offcut), the B1R wedge, the posts and the off-CR support (the A.3 lead route re-derives with the new outline), and the CR PCB row (r7 outline and 2 oz outer copper, against the OSH Park 4-layer rule file of the stack-up decisions). The design-doc section E rewrite decides them. **Applied (r9-5, design section E rewrite):** the FT1/FT2 feet, DOWSIL 3140 bed and bond coupon rows are deleted (Table 8-1); the 467MP row is re-scoped to the B1R wedge bond and the DOWSIL 3145 row to the W1-W4 strain-relief beads; the CR PCB row carries the plug-on rectangle, 1 oz outer / 0.5 oz inner, ENIG and no NPTH; a stencil and solder-paste row is added. The B1R wedge, the posts and the off-CR support stay as listed until the A.3 lead route is re-derived on the plug-on outline.
27. r9: the J102 cavity map has T5 (A4) diagonal to T10 (B5). The gate rule (T5, T6 and T10 pairwise non-adjacent, opposite row included) is met; the recommended diagonal separation is not. Operator confirmation is open; the map is not changed.

## 8. Revision r9 (2026-11-12): row changes

### 8.1 Sources

The edit applies these operator decisions of 2026-11-12, as reconciled in
`decisions_2026-11-12/round2/orchestrator_digest.md`:

- the tap review (`decisions_2026-11-12/cr_tap_review_2026-11-12.md`) and the gate mapping of
  `decisions_2026-11-12/ramifications/gate.md` (5 LVC packages U105, U106, U107, U110 and U118; CE_DRV buffered by U106A);
- the parts and assembly decisions (`round2/dec2_parts_assembly_2026-11-12.md`): six 0402 parts to 0603, U107 to DBV, B.5 and U117 retired;
- the EIB decisions (`round2/dec2_eib_2026-11-12.md`): U203, U204, C203, C204 and R258-R265 DNP, E4 and E6 leads not built;
- the tap connector decisions (`round2/tap_connector/dec_tap_connector_2026-11-12.md`);
- the mating connector decision (`cr_decision_mating_connector_2026-11-12.md`);
- the stack-up decisions (`stackup_fabrules_decisions_2026-11-12.md`): polyimide sheet retired, thermocouple removed.

The surviving CR reference designators agree with the `gen/netlist.py` r9 working copy, which names the
tap connector J102.

### 8.2 Quantity changes

Table 8-1 lists every order-quantity change (design quantity + spare in parentheses).

Table 8-1. Order-quantity changes, r8 to r9.

| MPN | r8 | r9 | Reason |
|---|---|---|---|
| TLV3012BIDBVR | 11 (9 + 2) | 6 (4 + 2) | U104, U115 and U121 removed; EIB U203 and U204 DNP |
| SN74LVC1G11DCKR -> SN74LVC1G11DBVR | 4 (3 + 1) | 2 (1 + 1) | U108 and U109 removed; U107 DCK -> DBV |
| SN74LVC1G123DCTR | 3 (2 + 1) | 0, row deleted | U111 and U113 removed |
| SN74LVC2G08DCTR | 4 (3 + 1) | 2 (1 + 1) | U114 and U116 removed |
| CRCW060320K0FKEA | 2 | 1 | R117 removed |
| CRCW060310K0FKEA | 11 | 5 | R118, R120 and R140 removed; EIB R258, R260 and R261 DNP (R274 stays fitted) |
| CRCW0603453KFKEA | 2 | 1 | R190 removed |
| CRCW060361K9FKEA | 1 | 0, row deleted | R141 removed |
| CRCW0603100RFKEA | 5 | 4 | R143 removed |
| CRCW060347K0FKEA | 12 | 11 | R124 removed |
| CRCW06031K00FKEA | 16 | 10 (9 + 1) | R121, R125, R127, R128, R135, R148 and the two R142 kit values removed; R106s added (1 + spare 1) |
| CRCW04021K00FKED | 2 (1 + 1) | 0, row deleted | R106s moved to the CRCW06031K00FKEA row |
| CRCW0603470RFKEA | 2 | 0, row deleted | EIB R264 and R265 DNP |
| CRCW0603100KFKEA | 4 | 0, row deleted | R133, R136, R150 and R151 removed |
| CRCW06031M00FKEA | 5 | 1 | R144 and R191 removed; EIB R262 and R263 DNP |
| CRCW060310M0FKEA | 3 | 1 | R119 removed; EIB R259 DNP |
| CRCW06030000Z0EA | 3 (2 + 1) | 2 (1 + 1) | R137 removed; EVM R21 and the EVM-group spare remain |
| CRCW0603604RFKEA, CRCW0603715RFKEA, CRCW0603825RFKEA, CRCW06031K21FKEA, CRCW06031K40FKEA | 2 each | 0, five rows deleted | R142 select-on-test kit removed with U104 |
| GRM188R71H104KA93D | 30 (25 + 5) | 18 (13 + 5) | C109, C112, C113, C117, C118, C120, C121, C122, C123 and C133 removed; EIB C203 and C204 DNP |
| GRM188R71H103KA01D | 1 | 0, row deleted | C140 removed |
| GRM21BR71C335KA73L | 1 | 0, row deleted | C150 removed |
| GRM188R71C334KA01D | 1 | 0, row deleted | C151 removed |
| TSW-101-07-G-S | 30 (20 + 10) | 0, row deleted | the tap far ends use the operator's workshop .100 in crimp terminals (dec2-tapconn) |
| Micro-Fit 3.0 2x5 THT header (J102), TODO(verify: Molex 43045 series exact P/N) | - | 1, new row | dec2-tapconn |
| Molex 2147581101 | - | 1, new row | dec2-tapconn |
| SSQ-110-01-L-S | - | 1, new row | mating connector decision, MB side |
| SSQ-112-01-L-S | - | 1, new row | mating connector decision, MB side |
| CAPLINQ PIT5S | 1 roll | 0, row deleted | polyimide sheet retired |
| Omega 5TC-TT-K-36-36 | 1 | 0, row deleted | thermocouple removed |
| DOWSIL 3140 RTV (FT1/FT2 beds) | 1 tube | 0, row deleted | r9-5: no foot beds (section E 'Bed RTV (r7)' withdrawn) |
| FT1/FT2 feet (workshop) | 4 (2 + 2) | 0, row deleted | r9-5: no feet |
| Bond coupon (workshop) | 2 (1 + 1) | 0, row deleted | r9-5: no foot bond and no sheet; T-A-09 withdrawn |
| Stencil and solder paste | - | 1 set, new row | r9-5 reflow assembly (section E 'Stencil and solder paste (r9-5)') |

The design quantity of the new J102 header is 1 with no spare listed; the operator can add a spare.

### 8.3 Changes without a quantity change

- R101, R103, R104, R105 and C101 change MPN from 0402 to 0603 (dec2-assembly item 2a): R101
  CRCW06038K06FKEA, R103 TNPW060366K5BEEA, R104 TNPW060349K9BEEA (moved to the top side), R105
  CRCW060327K4FKEA and C101 GRM188R71H223KA01D (TODO(verify: Murata)). The Link cells are keyword searches.
- U107 changes from SN74LVC1G11DCKR to SN74LVC1G11DBVR. U105 (sections 1 and 2 used), U106 (both sections used;
  U106A buffers CE_DRV), U110 and U118 stay DCT. The dec2-assembly change of U106 to SN74LVC1G32DBVR is void
  under the dec2-gate mapping. The U105, U106 and U118 notes record this.
- TSW-110-07-G-S and TSW-112-07-G-S become TSW-110-07-L-S and TSW-112-07-L-S, with the body on the CR
  underside. The Digi-Key SKUs of the -G parts are removed.
- The 26 AWG white and blue spools now serve W6 only, because the taps run in the J102 cable assembly. The
  quantity stays one sellable spool each.
- The 28 AWG Kynar red row notes that E4 and E6 are not built, so its 2 m E-lead figure is an upper bound.
- The Kapton tape row loses its thermocouple-bond use. The heat-shrink row names the tap lead far ends in
  place of the tap pins.
- The summary cells change from 154 to 98 components and from 60 to 51 unique parts (section 2.2).
- The CR PCB row follows design section E (r9-5): the plug-on rectangle x 18.584-67, y 7-94 (48.416 x 87 mm), no
  NPTH, 4-layer 1.6 mm, 1 oz outer / 0.5 oz inner (OSH Park, D-29), ENIG.
- The 3M 467MP row is re-scoped to the B1R wedge bond, and the DOWSIL 3145 row to the A.3 W1-W4 strain-relief
  beads (the A.4 tap beads leave with the tap field).
- The C101 Datasheet URL now names GRM188R71H223KA01D (TODO(verify: Murata)).
- The two TSW rows name the netlist refdes J1 in PCB Names.
- The D103 row records that the netlist and section E leave its MPN open; STPS2H100A remains the ordering
  candidate, TODO(verify: T-A-05).

### 8.4 EIB DNP set

U203, U204, C203, C204 and R258-R265 are DNP, and the E4 and E6 leads are not built. R274 stays fitted. The
EIB fabrication package (`fab/eib_2026-11-11/`) carries the same set. The EIB copper is unchanged.

### 8.5 r9-12 (2026-11-12): R131B and R132 value change

Check-in 2 ruling R2 (J.2 item 70(a), option (a)) raises R131B and R132 from 100 Ohm to 4.99 kOhm 1 % 0603. The
basis is design section H.24(d) and `round4/calc/r9_calc.py` R9.H24(d). The footprint does not change.

- The CRCW0603100RFKEA row now carries R130 and R131A only, and its quantity changes from 4 to 2.
- A new CRCW06034K99FKEA row carries R131B and R132, quantity 2. The ordering code is TODO(verify: Vishay doc 20035).
- The PCB components cell stays 98. The PCB unique parts cell changes from 51 to 52, because CRCW06034K99FKEA is a
  new MPN among the fitted CR/EIB parts.
- The CR netlist `cr/cr.net` carries the same values (LAYOUT_DECISIONS D-53).
