# Per-unit BOMs and order files for the BQ25798 charger retrofit, 2026-11-14

## 1. Scope

This folder holds the bills of materials and the order files of the 2026-11-14 round. It replaces
`bom_2026-11-13/` as the order set. `bom_2026-11-13/` is kept unchanged as the record of the 2026-11-13 order work,
including both Digi-Key upload results.

One unit is one carrier board (CR), one EVM interface board (EIB) and the rest of one build: one BQ25798EVM
(operator ruling 2026-11-13, chat: "no second BQ25798EVM"), the EVM rework of design section C, the motherboard (MB)
rework of section D.1, the harness, the materials, the hardware and the workshop items. Wire, tape and the J-TAP cable
come from workshop stock and are not on the BOM.

The folder contains these files:

- `cr_bom.csv`, the parts of one CR, the CR PCB and the CR stencil;
- `eib_bom.csv`, the parts of one EIB, the EIB PCB and the EIB stencil;
- `system_bom.csv`, the rest of one build;
- `digikey_import.csv`, the Digi-Key lines of the three BOMs, merged by MPN (**Superseded 2026-11-14, fix round
  2026-11-15:** "followed by four labelled alternate lines (section 5)");
- `digikey_optional.csv`, the four labelled alternate and bench lines of section 5 and the five SPARE lines of
  section 5.4, in a separate opt-in file (**Superseded 2026-11-15, phase C:** "the four labelled alternate and bench
  lines of section 5, in a separate opt-in file");
- `mouser_import.csv`, the Mouser lines (U101, R101, R103 and R104, D-67);
- `digikey_skipped.csv`, the rows that are in neither import file, with their vendor or the reason;
- this README.

## 2. Method

`gen/bom_split.py` writes every file except this README. Run it from `hardware/charger_evm_r8`:
`python gen/bom_split.py bom_2026-11-14`. The inputs are the same as for `bom_2026-11-13/`: the fitted references of
`cr/cr.net` and `eib/eib.net`, the row data of `bom_2026-11-11/ordering_bom.csv`, the `SUBST` table and the Digi-Key
part numbers of `bom_2026-11-13/digikey_upload_result_2026-11-13.csv`. The method of `bom_2026-11-13/README.md`
sections 2.1 to 2.3 and the attrition rule of its section 4.6 still apply.

The 2026-11-14 round changed `gen/bom_split.py` as follows (findings of `REVIEW_2026-11-14.md`):

- The netlist MPN check accepts a netlist MPN that equals the `SUBST` target of its row, because the netlist now
  carries the ordered parts (BOM-11, section 6).
- Each stencil row carries its own board in PCB Names, its own upload path and its own pitch and area-ratio text
  (BOM-1). The EIB stencil row states that the 14 DNP footprints have no aperture (BOM-2).
- The `VMAX` table writes the rated voltage of the substituted parts into `Voltage Max [V]` (BOM-3).
- `clean_notes()` removes the 2026-11-11 boilerplate on rows that now carry a vendor part number, removes the
  wrong-board fragments of shared rows and rewrites the stale statements on settled parts (BOM-4).
- The PLT1M-C row is counted per tie (BOM-6).
- The U118, Q201/Q202 and TLV3012B notes are corrected or extended (BOM-8, BOM-9, sim 3).
- The upload part number fills every row whose Vendor SKU is empty (BOM-10).
- The `ALTERNATES` table writes the alternate lines of section 5 to the opt-in file `digikey_optional.csv`
  (**Superseded 2026-11-14, fix round 2026-11-15:** "appends the alternate lines of section 5 to
  `digikey_import.csv`"). An opt-out line can reach the order unnoticed. In addition, the ALT C108 line has the
  part number 490-1443-1-ND of the C106/C107 main line, and a list upload can merge the two lines into one line of
  the summed quantity.
- The PCB rows name the exported 2026-11-14 packages and their copper state; the "TODO(verify: package exported)"
  of both rows is closed (fix round 2026-11-15).

The phase C round of 2026-11-15 (second review, findings R2-*; `update_2026-11-14/notes_phaseC_bom.md`) changed
`gen/bom_split.py` as follows:

- `clean_notes()` rewrites further stale notes on settled parts: C101 (the Murata TODO), D103 ("candidate" and the
  section E sentence), D104-D106 (the substitution TODO), J102 (the keyword-search sentence and the operator
  acceptance of the T5-T10 diagonal), R131B/R132 (the ordering-code TODO) and U107 (the DBV pinout TODO, closed on
  TI SCES487I Table 4-1) (R2-BOM-1, R2-LOG-1).
- The J102 row states that the J-TAP mate is built from workshop stock (R2-INT-5).
- The EIB stencil row no longer quotes the CR stencil history (R2-BOM-1).
- `desc120()` cuts each Description cell at a word boundary at most 120 characters long; it was cut mid-word
  (R2-BOM-6).
- The `ALTERNATES` table also writes five opt-in SPARE lines to `digikey_optional.csv` (section 5.4; R2-BOM-0,
  R2-BOM-5, R2-CRT-1).

## 3. Changes since bom_2026-11-13

### 3.1 Quantities, part numbers and order lines

No fitted part, MPN, Digi-Key part number, BOM quantity, order quantity or Customer Reference changed. The 62 main
lines of `digikey_import.csv` equal the 62 lines of `bom_2026-11-13/digikey_import.csv` in these columns. The four
lines of section 5 are new and are in `digikey_optional.csv`. `mouser_import.csv` and `digikey_skipped.csv` are unchanged.
The phase C round changed only the Description cell of three main lines: TSW-110-07-L-S and TSW-112-07-L-S now end
at "-L plating", and 43045-1012 carries a shorter description that ends "8.5 A per contact" (R2-BOM-6). It added the
five SPARE lines of section 5.4 to `digikey_optional.csv`.

### 3.2 Row changes

Table 1 lists every row whose content changed, apart from the note cleaning of section 3.3.

Table 1. Row changes from `bom_2026-11-13/` to `bom_2026-11-14/`.

| File | Row | Column | Was | Now | Finding and source |
|---|---|---|---|---|---|
| cr_bom | C102b | Specification | "(2.80 mm max thickness)" | "(2.50 mm, Digi-Key description)" | Digi-Key description "CAP 1210 X7R 100V 4.7UF 10% 2.50" (`bom_2026-11-13/digikey_upload_result_2026-11-13b.csv`) |
| cr_bom | C102b | Notes | "TODO(verify: TDK DC-bias curve) ..." | DC bias closed: about 3.04 uF typ at 23.6 V, 2.96 uF at 24.41 V | BOM-4; `bom_2026-11-13/README.md` section 4.4 |
| cr_bom | C102c | Vendor SKU | blank | 490-3285-1-ND | BOM-10 |
| cr_bom | C110-C132 | Voltage Max [V] | 50 | 100 | BOM-3; Digi-Key description "CAP CER 0.1UF 100V X7R 0603" |
| cr_bom | C125 | Voltage Max [V] | 10 | 16 | BOM-3; Digi-Key description "CAP CER 10UF 16V X7R 0805" |
| cr_bom | U101 | Voltage Max [V] | 60 | 75 | BOM-3; TCKE1401NM DS Rev. 3.0 Table 9.1, input voltage 4.7 to 75 V |
| cr_bom | U101 | Notes | TPS26630 index text ("restock date in 2027; availability is a risk") | Mouser source sentence and the 75 V basis | BOM-4, DOC-9 |
| cr_bom | R101, R103, R104 | Notes | "No Digi-Key product page URL ...", "66.5 k in range", "49.9 k in range" | Mouser source sentence; R103 range TODO(verify: Panasonic ERA-3A datasheet); "51.1 k in range" | BOM-4 |
| cr_bom | C102a | Notes | Murata NRND flag and drop-in candidate text | removed | BOM-4 |
| cr_bom | D103 | Notes | "The netlist ... leave the D103 MPN open ..." | the netlist carries STPS2H100A; MBRA2H100T3G alternate sentence | BOM-11; section 5.1 |
| cr_bom | C108, C129 | Notes | none | C108 = 470 pF option at assembly | section 5.3 |
| cr_bom | R130, R131A | Notes | none | 2026-11-14 decision; the R131A "no GND neighbour" reason is void under D-66 | EIB-1; section 5.2 |
| cr_bom | U102, U103, U119, U120 | Notes | none | "B suffix required, no non-B substitute" | sim/comparators/RESULTS.md section 5.6; SBOS300C 9.4.4 |
| cr_bom | U118 | Notes | none | "-40 to 85 C (SCES557E p.14 package option addendum)" | BOM-8 |
| cr_bom | Stencil | Specification, Notes | 13f upload path; both board ratios | `fab/cr_2026-11-14/gerbers/cr-F_Paste.gtp`; CR ratios only | BOM-1 |
| cr_bom | CR PCB | Notes | 13f upload | `fab/cr_2026-11-14/kikit_oshpark/gerbers.zip` | DOC-9 |
| eib_bom | C201, C202, C205 | Voltage Max [V] | 50 | 100 | BOM-3 |
| eib_bom | C201, C202, C205 | Notes | CR capacitor history (C109-C135) | removed | BOM-4 |
| eib_bom | R250-R275 (1.00 kOhm) | Notes | R106s, R121 and R142 text | removed | BOM-4 |
| eib_bom | Q201, Q202 | Notes | "suits the 3.3 V gate drive" | gates pulled to REGN (4.8-5.2 V at VBUS 15 V, SLUSDV2C p.15) through R252/R254 47.0 kOhm; Vgs(th) TODO(verify: Nexperia 2N7002BK datasheet) | BOM-9 |
| eib_bom | Stencil | PCB Names | "CR top side (reflow assembly)" | "EIB top side (reflow assembly)" | BOM-1 |
| eib_bom | Stencil | Specification | 13c upload path; U101 pitch sentence | `fab/eib_2026-11-14/gerbers/eib-F_Paste.gtp`; no aperture on the 14 DNP footprints; finest pitch 0.65 mm | BOM-1, BOM-2; `update_2026-11-14/notes_eib.md` section 2.2 |
| eib_bom | EIB PCB | Notes | 13c upload | `fab/eib_2026-11-14/kikit_oshpark/gerbers.zip` | DOC-9 |
| system_bom | C (MB) x2, C (EVM) x5 | Voltage Max [V] | 35 | 50 | BOM-3; Digi-Key description "CAP0805 X5R 10UF 10% 50V" |
| system_bom | PLT1M-C | BOM Units, Specification, Notes | "pack", "100-pack", "One 100-pack ... TODO(verify)" | "ea", one tie, sentence removed | BOM-6 |
| digikey_import | PLT1M-C | Description, unit price | "100-pack", 0.25 | one tie, 0.23 | BOM-6; 13b unit price $0.229 |
| digikey_import | C102b | Description | as the C102b Specification | as the C102b Specification | as above |

### 3.3 Note cleaning

On every row with a vendor part number, `clean_notes()` removes these 2026-11-11 sentences: "No Digi-Key product
page URL was found ...", "Price and stock not read ...", "Link and Vendor SKU from the digikey.com search-engine index
...", and the related index sentences. It appends one source sentence instead: the 13b upload result for Digi-Key
rows, and the findchips.com listing of 2026-11-13 for Mouser rows. "Voltage from the Murata part code (TODO(verify)
...)" is replaced by the Digi-Key description of the 13b upload result, which states the rated voltage. The EIB 10.0
kOhm and 47.0 kOhm rows and the system 47.0 kOhm row lose their CR-only history sentences.

### 3.4 Stencils and packages

The stencil and PCB rows name the 2026-11-14 packages `fab/cr_2026-11-14/` and `fab/eib_2026-11-14/`. The packages
were written on 2026-11-15 by `bash gen/export.sh <board> 2026-11-14` (`update_2026-11-14/notes_phaseB_export.md`).
(**Superseded 2026-11-14, packages exported:** "These packages are not exported yet. Export them with `bash
gen/export.sh <board> 2026-11-14` before the PCB and stencil orders.") Against the previous packages, the tracks,
vias, pads and zone outlines are unchanged. The F.Cu pour fill changes at CR J1 pin 18 (D-75), and the EIB F.Cu and
B.Cu pour fill changes at J201 (D-70). The EIB stencil from `fab/eib_2026-11-13c/` prints paste on the 32 pads of the DNP parts (REVIEW BOM-2); the
2026-11-14 board has no paste aperture on them.

## 4. Digi-Key and Mouser orders

### 4.1 Build a new Digi-Key list (BOM-0)

1. Create a new list (or BOM Manager project) at Digi-Key.
2. Upload `bom_2026-11-14/digikey_import.csv`.
3. Map the columns to Quantity, Digi-Key Part Number, Manufacturer Part Number and Customer Reference.
4. To order an alternate or bench line of section 5, copy that line from `bom_2026-11-14/digikey_optional.csv` into
   the list. The Customer Reference of an alternate line starts with "ALT" or "BENCH". If you add the ALT C108 line,
   make sure that the list keeps it as a separate line. The C106/C107 main line has the same part number,
   490-1443-1-ND, and a merged line has the quantity 20.
   (**Superseded 2026-11-14, fix round 2026-11-15:** "Delete each alternate line that you do not want (section 5).")
   To order a spare, copy its SPARE line (section 5.4). Each SPARE line has the part number of a main line. If the
   list merges the two lines, the merged quantity is the main quantity plus the spare, which is the intended total.
5. Do not use the list of the 2026-11-13 second upload (`bom_2026-11-13/digikey_upload_result_2026-11-13b.csv`).

The 13b list holds four lines that the rulings removed: CRCW06038K06FKEA x10 (8.06 kOhm, pre-D-67 R101),
TNPW060366K5BEEA x3 (66.5 kOhm, pre-D-67 R103), TNPW060349K9BEEA x3 (49.9 kOhm, pre-D-67 R104) and 2147561101 x1 (the
J-TAP cable, workshop stock). Fitted, the three resistors would set the TCKE1401NM current limit to about 2.48 A and
move OVP and UVLO away from the D-67 values of 23.19 V and 9.86 V (REVIEW BOM-0).

### 4.2 Totals

The 62 main lines are the 13b lines without the four removed lines. At the 13b prices they total $91.49 ($99.85 less
$8.36 for the four removed lines). The four optional lines add about $4.74 at the quantity-1 prices of section 5
(3 x $0.98 + 10 x $0.07 + 10 x $0.11; the 10 nF line has no USD price). (**Superseded 2026-11-14, ALT D103 order
quantity 8 -> 3:** "The four alternate lines add about $9.64 at the quantity-1 prices of section 5.")
The five SPARE lines of section 5.4 add $21.07 (2 x $2.78 + 5 x $1.76 + $1.10 + $2.56 + $3.05). All nine optional
lines together are about $25.80 at the prices of Table 2 (the script prints this sum; the 10 nF line is excluded).
`mouser_import.csv` is unchanged: 4 lines (`bom_2026-11-13/README.md` section 4.8).

### 4.3 Quantity basis

The main lines order one build with the attrition of `bom_2026-11-13/README.md` section 4.6. The ALT C108 line uses a
BOM quantity of 6, one for each CR of the order of 6 boards. The ALT D103 line uses a BOM quantity of 2, a test fit on
two CRs, and an order quantity of 3. The 2026-11-14 D103 decision recommends 2 to 3 parts for an operator question. The
two bench lines use a BOM quantity of 4. The attrition rule gives the order quantity of each optional line except ALT
D103. (**Superseded 2026-11-14, fix round 2026-11-15:** "The two CR alternate lines use a BOM quantity of 6, one for
each CR of the order of 6 boards." and "The attrition rule then gives the order quantity of each alternate line.")
Each SPARE line of section 5.4 has an explicit order quantity equal to its BOM quantity; section 5.4 gives the basis.

## 5. Alternate lines (2026-11-14 decisions)

No decision of the round changed a fitted part. Table 2 lists the alternate lines that the decisions added. They are
in the opt-in file `digikey_optional.csv` (**Superseded 2026-11-14, fix round 2026-11-15:** "added to
`digikey_import.csv`"). No alternate part is in the netlist or on a board.

Table 2. Lines of `digikey_optional.csv`.

| Line | Digi-Key | MPN | BOM qty | Order qty | Unit price at 1 | Stock (read) |
|---|---|---|---|---|---|---|
| ALT D103 | MBRA2H100T3GOSCT-ND | onsemi MBRA2H100T3G | 2 (**Superseded 2026-11-14:** "6") | 3 (**Superseded 2026-11-14:** "8") | $0.98 (search-index snapshot of the US site, not the live page) | 1,135, Active (digikey.co.uk, 2026-11-15) |
| ALT C108 | 490-1443-1-ND | Murata GRM1885C1H471JA01D | 6 | 10 | $0.069 (2026-11-13 upload) | 93,987 (13b upload, 2026-11-13) |
| BENCH C107 | 490-9669-1-ND | Murata GRM1885C1H472JA01D | 4 | 10 | $0.11 (digikey.com.mx search index) | 26,836, Active (digikey.co.uk, 2026-11-15) |
| BENCH C106/C107 | 490-9666-1-ND | Murata GRM1885C1H103JA01D | 4 | 10 | not read in USD (GBP 0.10 on digikey.co.uk) | 252, Active (digikey.co.uk, 2026-11-15) |

digikey.com returned HTTP 403 to the page reader on 2026-11-15, so the stock figures come from digikey.co.uk and can
differ from the US stock. Confirm price and stock at checkout. The 10 nF line has no USD price, so the script orders it
as a part of $0.25 or less.

### 5.1 D103: STPS2H100A stays, MBRA2H100T3G is an operator question

The ordered STPS2H100A stays as D103. The onsemi MBRA2H100T3G fits the existing D_SMA land with the cathode on pad 1
(onsemi CASE 403D, Style 1; `cr/charger_r8_cr.pretty/D_SMA_CrtYd0.25.kicad_mod`). Its IFSM is 130 A against 75 A
(onsemi MBRS2H100/D Rev. 16 p.2). In sim 1 it gives an OUT minimum 1.2-1.3 V shallower and a plateau of -1.44 V
against -2.69 V (`sim/hardshort/RESULTS.md` Table 5). However, it keeps OUT below -0.3 V longer than the STPS2H100A
fit (8.9 us against 7.8 us nominal), and its IR maximum at 125 C and 100 V is 1.5 mA against 1 mA. Both parts fail the
T-A-05 limit "VF at 3 A <= 0.5 V" (design section I, row T-A-05). The design section B.4 D103 row records that limit
as an r3 criterion of the 40 V B340A era, which no 100 V, 2 A SMA part meets. Its restatement as "read and recorded"
is the operator question of design J.2 item 79. (**Superseded 2026-11-15, phase C, R2-BOM-4 and R2-DOC-11:** "(design
doc line 3495), which design section B.4 (line 1961) does not state.") Neither datasheet gives the 130 A, 1 us pulse
rating of criterion (4). The operator rules whether to fit it.

### 5.2 R130 and R131A: no change

R130 and R131A stay 100 Ohm. A value in the H.24(d) window of 3.16-10.5 kOhm restores the CR rail on the CR 5-9 and
7-3 bridges, but it leaves /CE LOW with P5 LOW on the 3V3-CE_DRV_J bridges. It also leaves N_CEIN undefined on the
STAT-CE_DRV_J short. The mitigation of the single-bridge faults on the W5 wire-pad grids is an operator question:
a post-solder isolation check of every orthogonal J101/J201 pad pair, or a grid reorder (a copper change). The R131A
reason "conductor 7 has no GND neighbour" is void under D-66: a CR 7-3 bridge pulls the CR rail to 1.98-2.36 V
(`sim/permit/RESULTS.md` Table 5.6). `gen/netlist.py` and the `cr_bom.csv` row record this.

### 5.3 C106, C107 and C108: no change, one option at assembly

C106 = C107 = 470 pF and C108 = 1.0 nF stay. C108 = 470 pF (GRM1885C1H471JA01D, the C106/C107 part) is an option at
assembly. It lowers the ILIM_HIZ peak for T2 interruptions of 20 us and longer, and it leaves the 10 us case
unchanged (scratch re-run of the sim 4 decks, an unreviewed copy; a formal sim 4 re-run is open). The 4.7 nF and
10 nF parts are for bench tests only. C106 = C107 = 4.7 nF or 10 nF breaks the H.13 allowance that T-B-06 must fit
inside at 1.25 A and 1.80 A. If C108 = 470 pF is fitted, split C108 from the C108/C129 row and update design B.2
(tau about 44 us) and companion-doc C308.

### 5.4 Spare lines (phase C, 2026-11-15)

The main lines order one build. Parts above $1.00 at quantity 1 get no attrition (`bom_2026-11-13/README.md`
section 4.6), so several single-source parts have no spare. Table 3 lists the five opt-in SPARE lines. They are in
`digikey_optional.csv` only and never in `digikey_import.csv`. Their Customer Reference starts with "SPARE".

Table 3. SPARE lines of `digikey_optional.csv` (prices and stock from the 13b upload result,
`bom_2026-11-13/digikey_upload_result_2026-11-13b.csv`).

| Line | Digi-Key | MPN | Order qty | Unit price at 1 | Cost | Basis |
|---|---|---|---|---|---|---|
| SPARE TLV3012B | 296-TLV3012BIDBVRCT-ND | TLV3012BIDBVR | 2 | $2.78 | $5.56 | The B suffix has no substitute (`cr_bom.csv` U102 note; `sim/comparators/RESULTS.md` section 5.6). The main line orders exactly the 4 fitted parts. Design section E reads "4 (+2)" (R2-BOM-5). |
| SPARE C (MB)/C (EVM) | 4713-GMC21X5R106K50NTCT-ND | GMC21X5R106K50NT | 5 | $1.76 | $8.80 | The main line orders exactly 7 (MB 2 + EVM 5). Design section E reads "2 (+2)" and "5 (+3)", that is 5 spares (R2-CRT-1, REVIEW BOM-7). |
| SPARE CR J1 TSW-112 | 612-TSW-112-07-L-S-ND | TSW-112-07-L-S | 1 | $1.10 | $1.10 | One CR needs one TSW-110 and one TSW-112 (J1 pads 1-10 and 11-22, `gen/netlist.py` J1). The main lines order 3 x TSW-110 (attrition at $0.84) and 1 x TSW-112. This line makes a second matched J1 set. The 13b stock was 12 pieces (R2-BOM-0). |
| SPARE MB socket 1x10 | 612-SSQ-110-01-G-S-ND | SSQ-110-01-G-S | 1 | $2.56 | $2.56 | One MB takes one SSQ-110; the main line orders exactly 1 (R2-BOM-0). |
| SPARE MB socket 1x12 | 612-SSQ-112-01-G-S-ND | SSQ-112-01-G-S | 1 | $3.05 | $3.05 | One MB takes one SSQ-112; the main line orders exactly 1 (R2-BOM-0). |

The five lines cost $21.07. The quantity basis is one assembled CR and one MB, because one unit is one CR, one EIB
and one build (section 1). No ruling on the number of assembled CRs was found in `bom_2026-11-13/README.md` or in
this README: six CR boards are ordered, and the parts order is for one build. A second assembled CR needs a full
second CR parts set, which is outside these SPARE lines.

The GMC21X5R106K50NT line resolves a conflict between design section E and the order. Section E promises 5 spares,
and the main line orders none. Either the operator adds this line, or design section E changes to "2" and "5" with
no spare. That choice belongs to the operator and to the records of design section E.

## 6. Netlist and board fields (BOM-11)

`gen/netlist.py` now carries the ordered values and MPNs of `bom_2026-11-13/cr_bom.csv` and `eib_bom.csv`. The
schematics, `cr/cr.net` and `eib/eib.net` were regenerated with `gen/sch.py` and `kicad-cli`. The board fields were
copied with `gen/sync_fields.py`. Net membership is identical before and after on both boards, and copper is
unchanged. `update_2026-11-14/notes_phaseB_bom.md` lists every field and the verification. The fab packages
`fab/cr_2026-11-13f/` and `fab/eib_2026-11-13c/` still carry the old MPNs; the 2026-11-14 export carries the new ones.

The phase C round of 2026-11-15 changed two Note fields in `gen/netlist.py` (R2-BOM-2, R2-INT-4, R2-INT-5). The J1
Note names the ordered sockets SSQ-110-01-G-S and SSQ-112-01-G-S; it named the -L parts. The J102 Note states that
the mate is built from workshop stock; it named the Molex 2147561101 cable. `gen/sync_fields.py` gained the option
`--add-missing`, which adds a netlist field that a footprint does not have, as a hidden F.Fab field. With it, the
Note fields of U102, U103, U119, U120, D103 and J101 (CR) and J201 (EIB) now reach the boards. Net membership, ERC
and DRC with schematic parity are unchanged (`update_2026-11-14/notes_phaseC_bom.md`). The fab packages
`fab/cr_2026-11-14/` and `fab/eib_2026-11-14/` were exported before this change; a re-export carries the new fields.

## 7. Statements of bom_2026-11-13 that this folder supersedes

`bom_2026-11-13/README.md` and `bom_2026-11-13/PREORDER_REVIEW.md` are kept unchanged as the record. These statements
in them are superseded (REVIEW BOM-5, DOC-9):

- README line 6, "the two BQ25798EVM modules": one EVM per build.
- README lines 14-15: `eib_bom.csv` also holds the EIB stencil.
- README lines 19-20: the file list omits `digikey_upload_result_2026-11-13b.csv`.
- README lines 39-40: J101 and J201 are wire pads with no part, not placeholders.
- README lines 71-72, "Most rows have no Digi-Key Part Number": every Digi-Key line has one.
- README line 83: the skipped file lists both stencils, and the W5 key is a polarising plug, not a Samtec part (ruled off).
- README lines 132-133: the schematic and board MPN fields now name the ordered parts (section 6).
- README lines 141-143 (section 4.3): delete all four lines of the 13b list, or build a new list (section 4.1).
- README line 166: the current packages are the 2026-11-14 packages (section 3.4).
- README line 169 (section 4.5 item 4), "43045-1012 and the 2147561101 cable stay": the cable is workshop stock
  (README line 150; `digikey_skipped.csv` line 2).
- README lines 186-189, "65 parts lines ... about $65 ... $123": 62 lines, $91.49 at the 13b prices (section 4.2).
- PREORDER_REVIEW line 56, "fab/cr_2026-11-13e/": the 2026-11-14 package.
- PREORDER_REVIEW item 4.6 (line 90): the C3225X7S2A475K200AB and TPS26630RGER stock sentences and "DC-bias check
  open" are superseded by the CNC6P1X7R2A475K250AE DC-bias closure and by D-67.
- PREORDER_REVIEW lines 24-26: the PLT1M-C description reads one tie (section 3.2).
- PREORDER_REVIEW line 122: J102/2147561101, J201/FFSD and J8/KK are not mating pairs on the order; all three mates
  were ruled off.

## 8. Open items

- (**Closed 2026-11-15:** "Export `fab/cr_2026-11-14/` and `fab/eib_2026-11-14/` before the PCB and stencil orders
  (section 3.4)." The packages exist; section 3.4.)
- Operator questions: D103 MBRA2H100T3G (section 5.1), the W5 grid mitigation (section 5.2) and the C108 option
  (section 5.3).
- 2N7002BK Vgs(th) maximum: TODO(verify: Nexperia 2N7002BK datasheet).
- R103 range: TODO(verify: Panasonic ERA-3A datasheet).
- Cal-Chip GMC21X5R106K50NT DC bias is not recorded (REVIEW BOM-7). The spare count of the same part is the
  operator choice of section 5.4 (R2-CRT-1).
- Spares of the single-source parts above $1.00 are opt-in SPARE lines (section 5.4; REVIEW BOM-14, R2-BOM-0,
  R2-BOM-5). Without them the order holds one matched J1 set, one set of MB sockets and exactly four TLV3012BIDBVR.
- The heat-shrink tubing, the two adhesive tie bases, the solder paste and the 6-32 screws are not identified
  (REVIEW BOM-13).
- Design section E: revision r9-25 reconciled it with this BOM (REVIEW BOM-12, DOC-1). Section E now names this
  folder as the ordering record, and the BOM set governs where a row differs. At r9-25 these rows still differed
  (R2-BOM-3, R2-DOC-1): the CR PCB and EIB PCB rows said "(to be exported)"; the EIB PCB row said "from PM0 Gerbers
  (same panel)" and "(in CR panel)", although the EIB is a separate OSH Park 2-layer order; the Cost paragraph ended
  "with the EVMs at USD 312.90" (one EVM is USD 156.45); EM14 and PM2 named the GRM21BR6YA106KE43L candidate; the
  section E "C (MB)" and "C (EVM)" rows promise 5 spares (section 5.4). The design-document pass of 2026-11-15 owns
  these rows; check design section 0.3 for the revision that closes them. (**Superseded 2026-11-15, phase C:**
  "Design section E is not reconciled with this BOM (REVIEW BOM-12, DOC-1).")
- The design document still carries the U107 "TODO(verify: SCES487I ... DBV column)" text in B.3, B.8 and T-A-05
  (R2-LOG-1). This BOM closes it on the U107 row: TI SCES487I (revised November 2024) Figure 4-1 and Table 4-1 give
  A 1, GND 2, B 3, Y 4, VCC 5, C 6 for DBV and DCK, which `gen/netlist.py` and the U107 pads carry.
- The D107 SMAJ33A row still reads "candidate - T-A-05 datasheet check required"; it is the ordered part.
