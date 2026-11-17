# Phase C, BOM agent: notes (2026-11-15)

## 1. Scope

This note records the phase C work of the BOM agent on the second-review findings R2-BOM-0 to R2-BOM-6, R2-INT-4,
R2-INT-5, R2-DOC-1, R2-DOC-11, R2-LOG-1, R2-CRT-0 and R2-CRT-1. The finding texts are in
`C:/Users/ricky/AppData/Local/Temp/claude/phaseC/review2_findings.md`. The agent edited only these files:

- `gen/netlist.py` (two Note fields and three comments; no pin, net, value or MPN change);
- `gen/sync_fields.py` (option `--add-missing`; saves only on a change);
- `gen/bom_split.py` (note rewrites, the EIB stencil history, `desc120()`, five SPARE lines, the optional total);
- `cr/cr.kicad_sch`, `cr/cr.net`, `cr/erc.rpt` (regenerated);
- the field text of `cr/cr.kicad_pcb` and `eib/eib.kicad_pcb` (through `gen/sync_fields.py`; no geometry);
- `bom_2026-11-14/` (regenerated CSV files and README.md).

`gen/sch.py` was not changed. The EIB schematic and symbol library regenerate identically. The re-exported
`eib/eib.net` and `eib/erc.rpt` differed only in their date line, so the previous files were restored.

## 2. Changes and evidence

### 2.1 J1 and J102 Note fields (R2-BOM-2, R2-INT-4, R2-INT-5)

The J1 Note now reads "... MB mates SSQ-110-01-G-S + SSQ-112-01-G-S (ordered -G plating, 2026-11-13)". The ordered
sockets are the -G parts (`bom_2026-11-14/system_bom.csv` lines 11-12; operator ruling 2026-11-13, chat: "Yes, use
-G"). The J102 Note now states that the mate is built from workshop stock and carries "TODO(verify: workshop wire,
T-A-05)" for the wire gauge against the R170/R171 joints. The Molex 2147561101 cable is off the BOM
(`digikey_skipped.csv` line 2; design r9-22). The superseded texts are quoted in the `gen/netlist.py` comments. The
`cr_bom.csv` J102 row gained the same mate sentence.

The design-document instances of the -L sockets (A.1, A.7, A.8, B carrier summary, T-A-05) and of the cable (A.4
heading and r9-4 paragraph), and HANDOFF.md line 555, are outside this brief.

### 2.2 `gen/sync_fields.py --add-missing`

Without the flag, the script updates existing fields only and lists each missing field. With the flag, it adds a
missing MPN, Manufacturer or Note field as a hidden field that copies the attributes of the footprint Value field
(layer F.Fab). The real boards were synced with the flag:

- CR: J1 and J102 Notes updated; Note added on U102, U103, U119, U120 (B suffix sentence), D103 (alternate
  sentence) and J101 ("lead pads for W5 wires (D-66), no part"); 8 fields.
- EIB: Note added on J201; 1 field.

The new fields carry random UUIDs, so a re-run on a fresh board does not reproduce the UUIDs byte for byte.

### 2.3 BOM notes (R2-BOM-1, R2-LOG-1)

`clean_notes()` now rewrites these rows of `cr_bom.csv`:

- C101: the two Murata TODO sentences are removed (the fitted part is KEMET C0603C223K5RACTU).
- D103: "candidate - T-A-05 datasheet check required" and "design section E still reads 'selected in T-A-05'"
  become the ordered-part statement; section E r9-25 carries STPS2H100A (design doc D103 row of section E). Both old
  texts are quoted as superseded in the note.
- D104-D106: the "TODO(verify) leakage equivalence ... before substituting" sentence becomes "Confirm the leakage of
  the fitted part in T-A-05, TODO(verify: Diodes BAV199 datasheet IR at 75 V)".
- J102: the lower-case "Vendor SKU blank; price and stock not read" sentence is removed (new BOILER pattern); the
  T5-T10 diagonal is recorded as accepted by the operator on 2026-11-12, as the `gen/netlist.py` J102 comment states.
- R131B/R132: the ordering-code TODO is closed by the 13b upload match 541-4.99KHCT-ND, "RES SMD 4.99K OHM 1% 1/10W
  0603" (`bom_2026-11-13/digikey_upload_result_2026-11-13b.csv` line 33).
- U107: the DBV pinout TODO is closed (section 2.4).

The EIB stencil row no longer quotes the 2026-11-11 CR stencil history; it states that the row is new by D-69. The CR
stencil row keeps that history as its superseded text.

### 2.4 U107 DBV pinout (R2-LOG-1)

The TI datasheet was fetched from ti.com (`sn74lvc1g11.pdf`, kept in the scratch directory
`C:/Users/ricky/AppData/Local/Temp/claude/phaseC/bom/ds/`; it is not added to `references/`). It is SCES487I,
September 2003, revised November 2024. Figure 4-1 is titled "DBV or DCK Package, 6-Pin SOT-23 or SOT-SC70 (Top
View)". Table 4-1 gives one column for SOT-23, SOT-SC70 and SON: A 1, GND 2, B 3, Y 4, VCC 5, C 6.

The capture agrees. `gen/netlist.py` `lvc1g11()` maps 1 A, 2 GND, 3 B, 4 Y, 5 VCC, 6 C, and U107 =
`lvc1g11("U107", "QUAL", "FCCN", "P5N", "QF")`. `cr/cr.net` lists U107 pins 1 A, 2 GND, 3 B, 4 Y, 5 VCC, 6 C. On
`cr/cr.kicad_pcb` (footprint SOT-23-6_CrtYd0.25, rotation 0) the pads are 1 /QUAL, 2 /GND, 3 /FCCN at x -1.14 mm and
4 /QF, 5 /3V3, 6 /P5N at x +1.14 mm, with pad 1 opposite pad 6, as in Figure 4-1. The TODO is closed in the BOM. The
design document still carries it in B.3, B.8 and T-A-05 and at line 420 (owner: the design-document agent).

### 2.5 IMON comment (R2-CRT-0)

The `gen/netlist.py` C105 comment now cites TCKE1401NM DS Rev. 3.0 section 7.10 (p.9): a capacitor must not connect
to the IMON pin, because it degrades the current monitor tracking. The SLVSE94G 8.3.9 citation is quoted as
superseded. The comment states the R129/C129 load (27.4k || 10.0k = 7.32 kOhm above about 16 kHz, a 10 us pole) and
carries "TODO(verify: Toshiba IMON capacitive load through series R; T-B-14 / T-C-04 IMON step capture with and
without C129)". C129 is unchanged.

### 2.6 Description cut (R2-BOM-6)

`desc120()` replaces `desc[:120]` in all three import writers. When character 120 is not a space, comma, semicolon
or closing parenthesis, the cut moves back to the last space; trailing " ,;(-" characters are stripped. The J102
line uses a shorter description (`DESC_SHORT`) so that "8.5 A per contact" stays whole. Changed cells: TSW-110 and
TSW-112 now end "-L plating"; 43045-1012 now ends "8.5 A per contact". The Mouser U101 description ends at a word
boundary already and is unchanged.

### 2.7 SPARE lines (R2-BOM-0, R2-BOM-5, R2-CRT-1)

Five opt-in lines were added to `digikey_optional.csv` only (prices from the 13b upload result):

| Line | Digi-Key | Qty | Unit | Cost |
|---|---|---|---|---|
| SPARE TLV3012BIDBVR | 296-TLV3012BIDBVRCT-ND | 2 | $2.78 | $5.56 |
| SPARE GMC21X5R106K50NT | 4713-GMC21X5R106K50NTCT-ND | 5 | $1.76 | $8.80 |
| SPARE TSW-112-07-L-S | 612-TSW-112-07-L-S-ND | 1 | $1.10 | $1.10 |
| SPARE SSQ-110-01-G-S | 612-SSQ-110-01-G-S-ND | 1 | $2.56 | $2.56 |
| SPARE SSQ-112-01-G-S | 612-SSQ-112-01-G-S-ND | 1 | $3.05 | $3.05 |

The J1 basis: one CR needs one TSW-110 (J1 pads 1-10) and one TSW-112 (pads 11-22) (`gen/netlist.py` J1;
`cr_bom.csv` rows J1). The main lines order 3 x TSW-110 (attrition at $0.84) and 1 x TSW-112 ($1.10, no attrition).
One more TSW-112 gives a second matched set. One MB takes one SSQ-110 and one SSQ-112, and the main lines order
exactly one each. No ruling on the number of assembled CRs was found in `bom_2026-11-13/README.md` or
`bom_2026-11-14/README.md`; the parts order is for one build, and six CR PCBs are ordered.

The GMC21X5R106K50NT count of 5 follows design section E "2 (+2)" and "5 (+3)". The main line orders exactly 7 and
no spare. The conflict stays open for the operator and for the section E records: add this line, or change
section E to "2" and "5" with no spare.

## 3. Verification

- `gen/sch.py` into scratch: only the two Note properties of `cr/cr.kicad_sch` change; the CR symbol library and
  every EIB file regenerate identically (line endings ignored; all files LF).
- ERC (`kicad-cli sch erc --severity-all`): 0 errors, 0 warnings on both schematics.
- Net membership (scratch `netcmp.py`, old against new netlist): CR 78 references and 77 net entries, EIB 46
  references and 35 net entries, membership identical; field differences J1 Note and J102 Note only. The counts of
  77 and 35 are the `(net (code` entries, the same as in git HEAD; phase B quoted 76 and 34 nets.
- New hashes (sha256): `cr/cr.net` 148f1952...0d8d00, `cr/cr.kicad_sch` 7a2efeec...3c77a; `eib/eib.net` unchanged at
  14ff5713...2ff2d0b.
- Board diff against the pre-sync copy: only `property "Note"` blocks are added or changed. Counts of segments, vias,
  zones, pads and graphic items are unchanged (CR 692 / 426 / 85 / 277 / 41; EIB 332 / 96 / 5 / 113 / 33).
- DRC (`kicad-cli pcb drc --severity-all --schematic-parity`, reports in the scratch directory): CR 0 violations,
  0 unconnected, 0 parity, 0 footprint errors; EIB the same.
- `gen/check_constraints.py` on both boards: identical to `cr/constraint_check.md` and `eib/constraint_check.md`
  (line endings ignored); CR 0 FAIL.
- `python gen/bom_split.py bom_2026-11-14`: CR 46 rows (72 parts), EIB 13 rows (25 parts), system 26 rows, 61
  Digi-Key MPNs in 62 main lines, 9 optional lines, 4 Mouser lines, 35 skipped. Against the pre-run files:
  `digikey_import.csv` differs only in the three Description cells; `system_bom.csv`, `mouser_import.csv` and
  `digikey_skipped.csv` are byte-identical; `cr_bom.csv` and `eib_bom.csv` differ only in the Notes of the rows of
  section 2.3.

## 4. Open items and items for other agents

- The fab packages `fab/cr_2026-11-14/` and `fab/eib_2026-11-14/` were exported before these field changes. A
  re-export (export agent) carries the new J1/J102 Notes and the added Note fields into the fab assembly files.
- Design document (design-document agent): the -L socket text (A.1, A.7, A.8, B carrier summary, T-A-05), the
  2147561101 text (A.4), the U107 TODO (line 420, B.3, B.8, T-A-05), section E rows of R2-BOM-3 and the
  GMC21X5R106K50NT spare conflict; the R129/C129 TCKE1401NM basis in B.4 and J.1 item 26.
- HANDOFF.md line 555 still lists the 2147561101 wire-gauge TODO (records agent).
- D107 SMAJ33A still reads "candidate - T-A-05 datasheet check required" in `cr_bom.csv`; not in this brief.
- New numbers: optional file 9 lines, about USD 25.80 in all (four alternate and bench lines about USD 4.74, five
  SPARE lines USD 21.07); main Digi-Key lines unchanged at 62 lines, USD 91.49.
