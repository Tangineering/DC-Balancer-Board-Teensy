# Per-unit BOMs and Digi-Key import for the BQ25798 charger retrofit, 2026-11-13

## 1. Scope

This folder holds the bills of materials for one unit of the charger retrofit, with no spares. One unit is one
carrier board (CR), one EVM interface board (EIB) and the rest of one build: the two BQ25798EVM modules, the EVM
rework of design section C, the motherboard (MB) rework of section D.1, the harness, wire, materials, hardware and
workshop items. Wire and tape come from workshop stock and are not on the BOM (operator ruling 2026-11-13; section 4.1). The folder replaces the single ordering list `bom_2026-11-11/ordering_bom.csv`, which ordered one
build with spares in one file. That folder is kept as the record of the row data, the verification status and the
candidate MPNs (its sections 3 to 7 still apply).

The folder contains these files:

- `cr_bom.csv`, the parts of one CR, the CR PCB and the CR stencil;
- `eib_bom.csv`, the parts of one EIB and the EIB PCB;
- `system_bom.csv`, the rest of one build;
- `digikey_import.csv`, the Digi-Key lines of the three BOMs, merged by MPN, for upload to Digi-Key;
- `digikey_skipped.csv`, the rows that are not in the Digi-Key or Mouser file, with their vendor or the reason;
- `mouser_import.csv`, the Mouser lines (U101 and its three resistors, D-67), for upload to Mouser's BOM tool;
- `digikey_upload_result_2026-11-13.csv`, the result of the operator's first upload to Digi-Key (status, stock, Digi-Key part number and lead time per line), which section 4 acts on;
- `PREORDER_REVIEW.md`, the pre-order review of the boards and these BOMs, with the items to settle before each
  order;
- this README.

## 2. Method

`gen/bom_split.py` writes every file except this README (run from `hardware/charger_evm_r8`:
`python gen/bom_split.py bom_2026-11-13`). It reads the fitted reference designators of `cr/cr.net` and
`eib/eib.net` and the row data of `bom_2026-11-11/ordering_bom.csv`, and it applies the replacements of section 4 (the `SUBST`, `DK_HOLD` and `ORDER_QTY` tables) and the Digi-Key part numbers of the upload result.

### 2.1 Board BOMs

A CR or EIB row lists the fitted references of that board that the ordering-BOM row names, and its quantity is the
count of those references. Parts with the KiCad DNP attribute are excluded, and the lead pads W1-W7 (CR) and E1-E8
(EIB) are not parts. Rows that carried both boards, such as the 100 nF, 1.00 kOhm, 10.0 kOhm and 47.0 kOhm rows, are
split between the two files. J1 has two rows, TSW-110-07-L-S and TSW-112-07-L-S, at one each.

The script refuses to write when a fitted reference has no ordering-BOM row, or when a netlist MPN names another part
than its row. A netlist MPN that is a T-A-05 placeholder or a prefix of the row MPN is accepted: D103, D107, J101 and
J201 carry placeholders, and C102b carries the TDK part number without its packaging suffix.

The PCB rows restate the current boards from the fab package READMEs. The CR row gives the D-62 outline and the four
D-60 holes, and the EIB row gives 24.0 x 38.0 mm (D-25) and the D-63 pours. The per-unit quantity is one board; the
order quantity is in the row note (CR 6 by operator ruling 2026-11-13; EIB not ruled).

### 2.2 System BOM

A system row takes the design quantity from the "design qty N" statement of its 2026-11-11 note, so the spare is
dropped. The 47.0 kOhm row is shared by board parts and the EVM rework parts R272 and R272b; the rework references
become their own system row. Rows sold in a vendor unit (wire spools, tape rolls, packs, kits) keep one unit. Six rows state no design
quantity, and the PLT1M-C tie is sold per piece; the script sets these from a table that records the basis in the
row note: the 467MP tape (1 sheet), the M3 screws (4), the two ferrule rows (10 each, the 2026-11-11 assumption), the
two adhesive tie bases (1 each) and PLT1M-C (3).

### 2.3 Digi-Key file

The Digi-Key file takes every row of the three BOMs whose vendor is Digi-Key and whose MPN is identified, merges
rows with the same MPN and sums their quantities. The columns are Quantity, Digi-Key Part Number, Manufacturer Part
Number, Manufacturer, Description, Customer Reference and Reference Designators. Digi-Key prints the Customer
Reference on the label of each bag, so it carries the reference designators of the line, for matching bags to parts
at assembly. Digi-Key accepts at most 48 characters, so the script writes the designators in a short form:

- the board is named first when the text fits ("CR R106s,122,126,147 EIB R250,251,253,266,275");
- the letter prefix is written once per run of the same prefix ("CR R110,112" is R110 and R112);
- three or more consecutive numbers become a range ("CR D104-106" is D104, D105 and D106);
- when the board names do not fit, they are left out ("C110,111,114-116,119,126,130-132,C201,202,205"); CR
  designators are numbered 1xx and EIB designators 2xx, so the number shows the board;
- system rows give the part name of the system BOM ("W5", "EVM R21", "MB RSDA,MB RSCL"); three names that are too
  long are shortened (the J102 mate cable and the two ferrule rows).

The Reference Designators column keeps the full list per BOM. Most rows have no Digi-Key Part Number,
because the Digi-Key pages were not readable on 2026-11-11; the upload then matches on the Manufacturer Part Number.

To upload the file, open Digi-Key's BOM Manager (or a new list), choose the CSV upload and map the columns to
Quantity, Digi-Key Part Number, Manufacturer Part Number and Customer Reference. Review every line that the upload
cannot match or matches to more than one product.

The Quantity column is the order quantity with the attrition of section 4.6; the BOM Quantity column is the per-unit quantity. The BOM files themselves are for one unit with no spares. Small passives are often cheaper in a larger cut-tape quantity, and
an order for more than one unit multiplies every quantity.

## 3. Rows outside the Digi-Key file

`digikey_skipped.csv` lists them: the two PCBs (OSH Park), the BQ25798EVM (TI store), the CR stencil, the Samtec W5
key, the DOWSIL 3145 RTV, the workshop items and four NOT IDENTIFIED rows (heat-shrink tubing and the two adhesive
tie bases among them).

## 4. Digi-Key upload review, 2026-11-13

The operator uploaded the first `digikey_import.csv` (86 lines) to Digi-Key. Digi-Key matched 80 lines; 4 were
obsolete, 11 had no stock or only a reel quantity, and 6 did not match a product. Each replacement below was read on
its live Digi-Key product page on 2026-11-13: status Active, in stock, sold in cut tape or bulk from quantity 1
unless stated. Every quantity of the upload equals the BOM quantity. The Digi-Key file now holds 71 lines, and every
line carries its Digi-Key part number (cut tape where Digi-Key offers it). After the connector rulings of section 4.5 it holds 65 lines.

### 4.1 Rows removed

The 12 wire rows (Alpha 3053, 5857, 3049, 299, 297 and 296; Jonard R28) and the two tape rows (3M 467MP, Kapton
5413) are off the BOM. The operator uses wire and tape from workshop stock (operator ruling 2026-11-13, chat: "Let's
take the wire and tape off of the BOM, I'll use what I have in my workshop."). `digikey_skipped.csv` lists them.

### 4.2 Replacements

| Was | Now | Digi-Key | Reason |
|---|---|---|---|
| GRM188R71H223KA01D (C101) | KEMET C0603C223K5RACTU | 399-C0603C223K5RACTUCT-ND | obsolete; direct substitute |
| GRM21BR71H105KA12L (C103) | Samsung CL21B105KBFNNNF | 1276-CL21B105KBFNNNFCT-ND | obsolete; direct substitute |
| GRM188R71H104KA93D (13 x 100 nF) | Murata GRM188R72A104KA35D (100 V) | 490-3285-1-ND | obsolete; Digi-Key upgrade; merges with C102c |
| GRM21BR71A106KE51L (C125) | Samsung CL21B106KOQNNNE (16 V) | 1276-2872-1-ND | obsolete; Digi-Key upgrade |
| GRM31CR72A105KA01L (C102a) | Samsung CL31B105KCHSFNE | 1276-3095-1-ND | 0 stock until 22-Feb-2027 |
| C3225X7S2A475K200AB (C102b) | TDK CNC6P1X7R2A475K250AE (X7R) | 445-181657-1-ND | 0 stock until 15-Feb-2027 |
| BAV199,215 (D104-D106) | Diodes BAV199-7-F | BAV199-FDICT-ND | 0 stock until 19-Nov-2026 |
| TNPW060356K2BEEA (R110, R112) | Panasonic ERA-3AEB5622V | P56.2KDBCT-ND | 0 stock until 15-Dec-2026 |
| TNPW0805845KBEEA (R102) | Panasonic ERA-6AEB8453V | P845KDACT-ND | reel only, MOQ 15,000 |
| TNPW0805487KBEEA (R109) | Panasonic ERA-6AEB4873V | 10-ERA-6AEB4873VCT-ND | reel only, MOQ 5,000 |
| TNPW0603104KBEEA (R115) | YAGEO RT0603BRD07104KL | 13-RT0603BRD07104KLCT-ND | reel only, MOQ 5,000 |
| TNPW080510K0BEEA (MB R170, R171) | Panasonic ERA-6AEB103V | P10KDACT-ND | 0 stock until 01-Dec-2026 |
| SN74LVC2G08DCTR (U118) | TI SN74LVC2G08IDCTRQ1 | 296-36980-1-ND | 0 stock at every authorized distributor; same die and SM8 package, AEC-Q100 |
| SN74LVC1G06DCKR (U202) | TI SN74LVC1G06DCKT | 296-32290-1-ND | 2 in stock; same part on a 250-piece reel |
| 2N7002KT1G (Q201, Q202) | Nexperia 2N7002BK,215 | 1727-4789-1-ND | 0 stock, no date; Vgs(th) max 2.1 V suits the 3.3 V gate drive |
| GRM1885C1H222JA01D (EVM C252) | TDK C1608C0G1H222J080AA | 445-1297-1-ND | 0 stock until 08-Feb-2027 |
| GRM21BR6YA106KE43L (7 x 10 uF 35 V) | Cal-Chip GMC21X5R106K50NT (50 V) | 4713-GMC21X5R106K50NTCT-ND | 0 stock until 23-Feb-2027; no 35 V part stocked |
| SMAJ33A (D107) | Littelfuse SMAJ33A | SMAJ33ALFCT-ND | not matched without a manufacturer |
| AI 0,5-8 WH (ferrules) | Phoenix 3200014 | 277-2185-ND | type designation; this is its order number |
| SSQ-110-01-L-S (MB; see section 4.5) | Samtec SSQ-110-01-G-S | 612-SSQ-110-01-G-S-ND | non-stock until Jan 2027; -G is heavier gold on the contacts |
| SSQ-112-01-L-S (MB; see section 4.5) | Samtec SSQ-112-01-G-S | 612-SSQ-112-01-G-S-ND | non-stock, MOQ 1,445; -G as above |

Each replaced row carries its reason at the start of its Notes. The values, ratings, dielectrics, tolerances,
temperature coefficients and packages are the same or better. The precision resistors of the Panasonic ERA-6A
series are rated 0.125 W against the 0.26 W of the TNPW 0805; the dissipation in these dividers is in the
milliwatt range. GRM1885C1H471JA01D (C106, C107) is "Not For New Designs" but in stock, and it stays.

The schematic and board MPN fields still name the original parts; the fab package assembly BOMs therefore list
the original MPNs. Take each part from this BOM at assembly.

### 4.3 U101 from Mouser (D-67)

TPS26630RGER (U101) had no authorized stock: Digi-Key 0 (restock 8-Jul-2027), Mouser 0 and TME 0 on 2026-11-13, and every
TPS2663x and TPS1663x variant was also at 0. The operator ruled (chat 2026-11-13): "Use TCKE1401NM for U101." The
Toshiba TCKE1401NM,R1F fits the existing footprint (`LAYOUT_DECISIONS.md` D-67) and needs new values for R101
(8.45 kOhm), R103 (64.9 kOhm 0.1 %) and R104 (51.1 kOhm 0.1 %). Digi-Key sells the TCKE1401NM only as a 3,000-piece
reel, so the four parts are ordered from Mouser (section 4.8). The Digi-Key file lost the three superseded
resistor lines: CRCW06038K06FKEA (8.06 kOhm), TNPW060366K5BEEA (66.5 kOhm) and TNPW060349K9BEEA (49.9 kOhm).
Delete those three lines from the Digi-Key list that was built from the second upload (section 4.7).

(**Superseded 2026-11-13, D-67:** TPS26630RGER (U101) has no authorized stock: Digi-Key 0 (restock 8-Jul-2027), Mouser 0, TME 0 (2026-11-13). Every TPS2663x and TPS1663x variant is also at 0 authorized stock; only brokers list it, with counterfeit risk. The row stays on `cr_bom.csv` and is not in the Digi-Key file. The source is an operator decision: the TI store (ti.com, which the built-in browser could not read), a Digi-Key backorder (the part number is 296-TPS26630RGERCT-ND), or a broker with authenticity checks.)

### 4.4 Open items

- TODO(verify: TDK DC-bias curve): C102b, CNC6P1X7R2A475K250AE, effective capacitance of at least 3 uF at 23.6 V.
- The wire gauge of the J-TAP cable 2147561101 is not on its Digi-Key page (PREORDER_REVIEW.md item 4.2).
- The heat-shrink tubing and the two adhesive tie bases are still not identified.

### 4.5 Connector rulings, 2026-11-13

The operator ruled on the CR and EIB connectors (forked side session, chat 2026-11-13, relayed to this folder):

1. "We're definitely keeping J1, it gives the required board height as well." The TSW headers on the CR and the
   SSQ sockets on the MB stay. The SSQ lines are the -G plating (section 4.2), because the -L parts are
   non-stock at Digi-Key (operator ruling 2026-11-13, chat: "Yes, use -G").
2. "Let's remove the J101 and J201." and "Change the footprints to through-hole wire pads." J101 and J201 become
   wire pads with no part, like W1-W7 and E1-E8, so `gen/bom_split.py` treats them as lead pads. The FTSH-107-01-L-DV
   (J101), FTSH-107-01-L-DV-K (J201), the W5 ribbon FFSD-07-D-12.00-01-N and the W5 key plug are off the BOM. The
   board change is D-66 (`LAYOUT_DECISIONS.md`): J101 and J201 are 3 x 3 through-hole wire pads, and the
   packages are `fab/cr_2026-11-13d/` and `fab/eib_2026-11-13b/`. The nine W5 wires come from workshop stock.
3. "The EVM J8 KK I'll solder directly to the pins." The KK housing 22-01-3047 and the crimps (08-50-0114, whose
   replacement 0008500113 had a 100-piece minimum) are off the BOM.
4. "J102 (J-TAP) let's keep since we can get a premade cable." 43045-1012 and the 2147561101 cable stay.

`digikey_skipped.csv` lists each removed row with its ruling.

### 4.6 Attrition

The operator asked for extras of every inexpensive part (chat 2026-11-13: "include an attrition rate for the small
inexpensive components so that I have extras of anything inexpensive"). `gen/bom_split.py` sets the Digi-Key order
quantity from the Digi-Key unit price at quantity 1:

| Unit price | Order quantity |
|---|---|
| $0.25 or less | the larger of 10 and 1.5 x the BOM quantity, rounded up |
| above $0.25, up to $1.00 | the BOM quantity + 25 %, rounded up, and at least + 2 |
| above $1.00 | the BOM quantity |

The per-unit BOM files keep the design quantities. The Digi-Key file carries the BOM quantity and the unit price in
two extra columns, which the upload can leave unmapped. The unit prices are those of the upload result for the
unchanged lines and those read on the live product pages on 2026-11-13 for the replacements. At those prices, the
65 parts lines total about $65 at the BOM quantities and about $123 with attrition; the price breaks at 10 pieces
make the actual total lower. The 100-piece minimum of the former KK crimp line no longer applies, because the
crimps are off the BOM (section 4.5).

### 4.7 Second upload, 2026-11-13

The operator uploaded the revised `digikey_import.csv` (66 lines: 65 parts, the 100 nF part on two lines for its two
labels). `digikey_upload_result_2026-11-13b.csv` records the result. Digi-Key matched all 66 lines to the Digi-Key
part numbers of the file, with the requested quantities and the Customer References unchanged, and every line is in
stock. The extended total is $99.85 at the order quantities. Two lines carry a note that needs no action:
GRM1885C1H471JA01D (C106, C107) is "Not For New Designs" and in stock (93,987), and Digi-Key writes 43045-1012 as
0430451012, the same Molex part. TPS26630RGER (U101) is not in the file (section 4.3).

### 4.8 Mouser order (D-67)

`mouser_import.csv` holds the rows whose vendor is Mouser, with the same Customer Part Number text, attrition rule and
extra columns as the Digi-Key file. The Mouser part numbers and stock were read from the Mouser listing on findchips.com on
2026-11-13 (the Mouser site was not read directly):

| Ref | MPN | Mouser | Stock | Unit price at 1 | Order quantity |
|---|---|---|---|---|---|
| U101 | TCKE1401NM,R1F (Toshiba) | 757-TCKE1401NMR1F | 1,984 | $4.61 | 1 |
| R101 | CRCW06038K45FKEA (Vishay Dale) | 71-CRCW0603-8.45K-E3 | 705,867 | $0.10 | 10 |
| R103 | ERA-3AEB6492V (Panasonic) | 667-ERA-3AEB6492V | 1,948 | $0.10 | 10 |
| R104 | TNPW060351K1BEEA (Vishay Dale) | 71-TNPW060351K1BEEA | 6,705 | $0.26 | 3 |

To upload the file, open Mouser's BOM tool, upload the CSV and map the columns to Mouser Part Number, Manufacturer Part
Number, Quantity and Customer Part Number (Mouser prints the customer number on the bag label; the longest here is 7
characters). The attrition rule gives one U101 (above $1.00); a spare U101 for the 0.5 mm reflow is the operator's choice.

