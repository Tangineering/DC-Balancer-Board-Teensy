# Per-unit BOMs and Digi-Key import for the BQ25798 charger retrofit, 2026-11-13

## 1. Scope

This folder holds the bills of materials for one unit of the charger retrofit, with no spares. One unit is one
carrier board (CR), one EVM interface board (EIB) and the rest of one build: the two BQ25798EVM modules, the EVM
rework of design section C, the motherboard (MB) rework of section D.1, the harness, wire, materials, hardware and
workshop items. The folder replaces the single ordering list `bom_2026-11-11/ordering_bom.csv`, which ordered one
build with spares in one file. That folder is kept as the record of the row data, the verification status and the
candidate MPNs (its sections 3 to 7 still apply).

The folder contains these files:

- `cr_bom.csv`, the parts of one CR, the CR PCB and the CR stencil;
- `eib_bom.csv`, the parts of one EIB and the EIB PCB;
- `system_bom.csv`, the rest of one build;
- `digikey_import.csv`, the Digi-Key lines of the three BOMs, merged by MPN, for upload to Digi-Key;
- `digikey_skipped.csv`, the rows that are not in the Digi-Key file, with their vendor;
- `PREORDER_REVIEW.md`, the pre-order review of the boards and these BOMs, with the items to settle before each
  order;
- this README.

## 2. Method

`gen/bom_split.py` writes every file except this README (run from `hardware/charger_evm_r8`:
`python gen/bom_split.py bom_2026-11-13`). It reads the fitted reference designators of `cr/cr.net` and
`eib/eib.net` and the row data of `bom_2026-11-11/ordering_bom.csv`.

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
Number, Manufacturer, Description, Customer Reference and Reference Designators. The Customer Reference gives the
use per BOM (for example "CR x10 EIB x3") and is at most 48 characters. Most rows have no Digi-Key Part Number,
because the Digi-Key pages were not readable on 2026-11-11; the upload then matches on the Manufacturer Part Number.

To upload the file, open Digi-Key's BOM Manager (or a new list), choose the CSV upload and map the columns to
Quantity, Digi-Key Part Number, Manufacturer Part Number and Customer Reference. Review every line that the upload
cannot match or matches to more than one product.

The quantities are for one unit with no spares. Small passives are often cheaper in a larger cut-tape quantity, and
an order for more than one unit multiplies every quantity.

## 3. Rows outside the Digi-Key file

`digikey_skipped.csv` lists them: the two PCBs (OSH Park), the BQ25798EVM (TI store), the CR stencil, the Samtec W5
key, the DOWSIL 3145 RTV, the workshop items and four NOT IDENTIFIED rows (heat-shrink tubing and the two adhesive
tie bases among them).
