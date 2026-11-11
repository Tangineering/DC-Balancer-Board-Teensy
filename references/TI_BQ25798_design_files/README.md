# TI design files for BQ2579x power stages (fetched 2026-11-10)

Reference material for `docs/charger_bq25798_custom_board_2026-11-10.md`. All files are TI copyright and are
supplied under the TI notice in `TIDA-050047/altium_TIDM752/IMPORTANT NOTICE AND DISCLAIMER.pdf`.

## 1. BQ25798EVM (BMS034)

TI does not publish an Altium project or Gerber archive for the BQ25798EVM on the tool page
(https://www.ti.com/tool/BQ25798EVM, checked 2026-11-10). The EVM user guide SLUUCB5E contains the schematic,
the BOM and the four layer figures.

| File | Content |
|---|---|
| `BQ25798_SLUSDV2C.pdf` | BQ25798 data sheet, SLUSDV2C (revised June 2026); layout guidelines in section 8.4 |
| `BQ2579xEVM_SLUUCB5E.pdf` | BQ2579xEVM user guide, SLUUCB5E (schematic, BOM, layer figures 4-1 to 4-4) |

## 2. TIDA-050047 (TIDUEY1C): USB Type-C PD and 2-4 cell charging reference design

Source page: https://www.ti.com/tool/TIDA-050047. The design pairs a TPS25750 PD controller with a BQ2579x charger.
The schematic sheet and the Altium library part are **BQ25792RQM**; the TIDM749 BOM lists **BQ25798RQM**. The two
parts share the RQM package and the power-stage pinout (TODO(verify: SLUSDV2C vs BQ25792 data sheet pin tables)).

| File | TI ID | Content |
|---|---|---|
| `TIDA-050047/TIDUEY1C.pdf` | TIDUEY1C | Design guide |
| `TIDA-050047/TIDM748.pdf` | TIDM748A | Schematic |
| `TIDA-050047/TIDM749.pdf` | TIDM749 | Bill of materials (1 uH and 4.7 uH 7 A shielded inductors) |
| `TIDA-050047/TIDM750.pdf` | TIDM750 | Layer plots (PDF) |
| `TIDA-050047/TIDM751.pdf` | TIDM751 | Layer plots / assembly drawings (PDF) |
| `TIDA-050047/altium_TIDM752/` | TIDM752 | Altium project REV_A1 (2020-11): `.PcbDoc`, `.SchDoc`, BOM `.xlsx`, and `Project Outputs/` with 4-layer Gerbers (GTL, G1, G2, GBL; stack-up drawing on GM12) and NC drill files. The Altium `History/` folder of the archive was not extracted. |

Not fetched: `TIDCFY4.ZIP` (697 KB) on the same page requires a myTI login. Fetch it by hand if needed.
