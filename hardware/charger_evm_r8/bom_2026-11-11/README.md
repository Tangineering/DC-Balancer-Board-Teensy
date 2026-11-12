# Ordering BOM for the BQ25798 charger retrofit (design r8), 2026-11-11

## 1. Scope

This folder holds the ordering bill of materials for one build of the BQ25798 charger retrofit
described in `docs/charger_bq25798_wiring_design_2026-11-05.md` (revision r8). One build is one
carrier board (CR), one EVM interface board (EIB), two BQ25798EVM modules, the EVM rework of
section C and the motherboard (MB) rework of section D.1. Nothing has been ordered.

The folder contains three files:

- `ordering_bom.csv`, the ordering list (113 rows);
- `footprint_relevant_choices.md`, the land-pattern facts for the parts that constrain the PCB capture;
- this README.

## 2. Method

### 2.1 Source of rows and quantities

Every row comes from design section E (lines 2185-2291). The order quantity in `BOM Qty` is the
section E quantity plus the listed spare: "1 (+1)" gives 2. The `Notes` cell of each row states
"design qty N + spare M". Rows with an identical MPN are merged, and all reference designators are
listed in `PCB Names`. Three merges cross section E rows:

- CRCW060347K0FKEA carries the ten CR/EIB 47.0 kOhm parts and EVM R272 and R272b.
- CRCW06031K00FKEA carries the fourteen 1.00 kOhm parts and the two 1.00 kOhm values of the R142 kit.
- CRCW06030000Z0EA carries R137 and EVM R21.

The EVM rework row of section E lists one spare for five parts of different value. This BOM
allocates that spare to the 0 Ohm link. The allocation is a BOM choice and the operator can move it.

### 2.2 Format

The CSV copies the 35 columns and the summary cells of
`references/Scale Car Design PCB BOM 20260622.csv` (42 fields per line, CRLF). `Ready to Order`,
`Ordered` and `Received` are FALSE on every row. Electrical columns are blank except
`Voltage Max [V]` where the rating was read or is set by the part code.

The summary cells have these definitions:

- **Total Assembly Cost** is the sum of `Assembly Cost` over rows with a known price. No price was verified (section 3), so every row is excluded and the total is USD 0.00. The total is therefore not a cost estimate. Design section E gives a budget of USD 520-630 including the EVMs.
- **PCB components** (154) is the count of fitted reference designators on the CR and the EIB. R142 counts once. Spares, kit values, EVM and MB rework parts, wire, materials and hardware are not counted.
- **PCB unique parts** (60) is the count of distinct MPNs among those fitted CR/EIB parts. The R142 kit rows are not counted.

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
- 24 rows carry a Digi-Key SKU and 36 rows a Digi-Key product URL that come from the digikey.com search-engine index, not from a live page. The `Notes` cell of each such row says so. Confirm every SKU on the live page before ordering.
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
| TNPW040266K5BEED, TNPW040249K9BEED | In range: 0402, 0.1 %, 25 ppm/K covers 47 Ohm to 100 kOhm; ED is the 0402 packaging code | doc 28758 |
| TNPW0805487KBEEA, 442K, 845K, 1M00, 10K0 | In range: 0805, 0.1 %, 25 ppm/K covers 3.5 Ohm to 1 MOhm | doc 28758 |
| TNPW060356K2BEEA, TNPW0603104KBEEA | In range: 0603 covers 3.5 Ohm to 332 kOhm | doc 28758 |
| CRCW06033M30FKEA, CRCW060310M0FKEA | In range: 1 %, 100 ppm/K covers 10 Ohm to 10 MOhm (10.0 MOhm is the top) | doc 20035 |
| CRCW04021K00FKED power | P70 = 0.063 W (standard) / 0.10 W (extended); the design 11.5 mW is 18 % of 0.063 W | doc 20035 |
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
15. Polyimide: confirm the CAPLINQ PIT5S width code, film versus total thickness, dielectric strength and adhesive temperature rating.
16. DOWSIL 3145 and 3140: confirm the alkoxy cure and the "non-corrosive to copper" statement in the Dow TDS.
17. 3M 467MP: confirm the listing size and pack quantity, and the 0.05 mm thickness for that SKU.
18. Ferrule counts (10 each assumed) and the Phoenix order number for the loose AI 0,5-8 WH.
19. Heat-shrink kit, 6 x 6 mm and 10 x 10 mm adhesive tie bases: no MPN identified.
20. Workshop items: obtain stock and costs for the B1R wedge, the posts, the off-CR support, FT1/FT2, the EVM plate and clamps, the silicone pads and the bond coupon.
21. CR and EIB PCB: obtain fab quotes.
22. Open every `Datasheet` URL that was not read (section 3.2).
