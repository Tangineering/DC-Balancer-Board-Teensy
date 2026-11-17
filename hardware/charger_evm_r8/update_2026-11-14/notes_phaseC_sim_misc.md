# Phase C notes: sim_misc (sims 1, 3, 5 and sim/README.md)

Date: 2026-11-15. Scope: `sim/hardshort/`, `sim/comparators/`, `sim/efuse_decay/` and `sim/README.md`. The folders
`sim/chopper/` and `sim/permit/` were not edited. Second-review findings handled: R2-SIM-8, R2-SIM-4, R2-SIM-9,
R2-PWR-0 (sim 1 part only) and R2-SIM-5 (check only). Backups of every edited file before this round are in
`C:\Users\ricky\AppData\Local\Temp\claude\phaseC\sim_misc\`.

## 1. Changes

### 1.1 R2-SIM-8: comparators run log and the duplicate-block incident (FIXED)

1. `sim/comparators/run_log.txt` was the console of the run before the final one (543 s). It is replaced by the
   console of the final run, copied from `C:\Users\ricky\AppData\Local\Temp\claude\sim_2026-11-14\comp_pre_dedup\rerun_log.txt`
   (557 s). The earlier console is kept as `sim/comparators/run_log_pre_dedup_2026-11-15.txt`.
2. Evidence that the final run is the source of the present outputs: `summary.json` gives `runtime_s` 557.35; the
   backup `summary.json` gives 542.90.
3. All 11 CSV files of `sim/comparators/csv/` are byte-identical to the 11 backup files (`cmp`).
4. `summary.json` equals the backup in every field except `runtime_s`; NaN fields are NaN in both files.
5. The two consoles agree on all 921 lines once the per-deck run times and the total run time are masked.
6. `run.py` holds one `def dc_deck` (line 555) and one `def dc_trip` (line 570); 34 top-level functions, no duplicated
   name. The module-level `cr.net` topology asserts pass on the current `cr.net` (module import test, no output
   written).
7. `sim/comparators/RESULTS.md`: section 9 rows for `run.py` (557 s), `run_log.txt` and the kept earlier console, with
   the old text in superseded form; new section 10.1 records the incident and the four comparisons.
8. `sim/README.md`: incident record paragraph.

Open: the removed block was not preserved, so its content rests on the orchestrator's report. `run.py` still does
not write its own log (the console was redirected); `run.py` was not changed, so that it stays the script that
produced the outputs.

### 1.2 R2-SIM-4: stale source citations (FIXED)

1. A citation note at the top of `sim/hardshort/RESULTS.md`, `sim/comparators/RESULTS.md` and
   `sim/efuse_decay/RESULTS.md`, and a short paragraph in `sim/README.md`: line numbers for `gen/netlist.py`,
   `cr/cr.net` and the design document refer to git tag `charger-r8-pre-review-2026-11-14` (commit 014c745).
   Verified: at the tag, `gen/netlist.py` line 95 is C102a, 96 C102b, 98 C102c, 105-110 U101, 111/115/116
   R102/R103/R104, 118 R101, 121 C103, 122-123 D103, 131 the U102 block header, 165 R188, 205 R175, 228-229 W1/W2;
   design-doc lines 1954, 3258, 3534, 1860, 3390, 3400 are the cited rows at the tag (they are not in the working copy).
2. BOM: every simulated part has the same Specification and MPN in `bom_2026-11-13/` and `bom_2026-11-14/`
   (`cr_bom.csv` for C102a/c, D107, U101, R101-R105, C103, D103, R109-R116, R122, R126, R175, R184-R189, C106-C108,
   D104-D106, U102, U103, U119, U120, C101, R108; `system_bom.csv` R170/R171). The only difference is the C102b thickness
   text ("2.50 mm, Digi-Key description" in place of "2.80 mm max thickness"); its MPN and value are unchanged.
3. Inline citations rewritten with the old text in the superseded form: comparators section 2.1 (netlist lines,
   `bom_2026-11-13/README.md` line 116 -> `bom_2026-11-14/system_bom.csv` line 3) and section 3 (`cr_bom.csv` lines
   22-39, same lines in `bom_2026-11-14`); efuse_decay sections 2.1 and 2.2 (netlist lines 95/96/98, 105-108, 106,
   111/115/116); hardshort Table 1 fast-trip row.
4. `sim/hardshort/RESULTS.md` section 2.1: the netlist-versus-BOM MPN mismatch paragraph is marked resolved by D-82
   (current `gen/netlist.py`: C102a CL31B105KCHSFNE, C102b CNC6P1X7R2A475K250AE, C103 CL21B105KBFNNNF, D103 STPS2H100A
   "Schottky 100V 2A SMA"); Table 9 item 10 notes the resolution.
5. `sim/hardshort/run.py` docstring: the netlist line citation names the tag.

Not changed: README line 1352 of R2-SIM-4 is a design-document line; `sim/README.md` already reads "section 6 (sim 5:
section 5)". `sim/chopper/RESULTS.md` citations belong to another agent.

### 1.3 R2-SIM-9: tFASTTRIP at the datasheet values (FIXED by re-run)

1. Source re-read: TCKE1401NM DS Rev. 3.0 Table 10.3 (p.16): tFASTTRIP 4 us typical, 8 us maximum, no minimum, for
   6 kOhm < RILIM <= 30 kOhm (3 / 5.2 us for 3-6 kOhm). R101 8.45 kOhm uses the first row. DS sec. 7.9 (p.9) gives
   3 us (Typ.) for IFASTTRIP < IOUT < ISCP.
2. `sim/hardshort/run.py`: new `--tft-check` mode (`set_tft_check()`, `tft_check()`), and
   `write_behav_models(write=True)` gained a `write` flag so that the mode leaves `sim/models/` untouched (md5 of the
   three `hardshort_*.lib` files unchanged). The mode runs the `rsh` set (120 cases) and 12 headline grid cases
   (bench and vehicle, 16/22/23.6 V, 5 mOhm, nominal lead, STPS2H100A fit and MBRA2H100T3G) at 3, 4, 6 and 8 us,
   528 runs, 92-156 s. It writes only `results/tft_check.csv`, `results/tft_check.md` and `decks/tft*.cir`.
3. Reproduction check: the 6 us runs equal `results/rsh.csv` and `results/grid.csv` in 132 of 132 cases (OUT minimum,
   trip path, FET current at the turn-off, time below -0.3 V, U101 VIN peak).
4. Results (`sim/hardshort/RESULTS.md` section 5.6, Table 7a; range over the four corners of the per-corner worst):

| R_short | 3 us | 4 us (typ.) | 6 us (old base) | 8 us (max.) |
|---|---|---|---|---|
| 0.5 Ohm | -0.77 to -0.52 | -1.01 to -0.77 | -1.01 to -0.20 | -0.89 to -0.10 |
| 0.9 Ohm | +0.015 to +0.022 | +0.016 to +0.024 | +0.021 to +0.031 | +0.024 to +0.041 |
| 1.0 Ohm | +0.030 to +0.044 | +0.033 to +0.048 | +0.041 to +0.062 | +0.047 to +0.078 |
| 1.5 Ohm | +0.25 to +0.36 | +0.27 to +0.39 | +0.30 to +0.45 | +0.33 to +0.53 |
| 2.0 Ohm | +0.72 to +1.02 | +0.76 to +1.09 | +0.82 to +1.23 | +0.89 to +1.39 |

5. The hard-short headline (Table 5, Table 8) is unchanged: all 12 headline cases are identical at 3/4/6/8 us,
   because the SCP or UVLO path opens the FET 1.26-2.11 us after the short.
6. Restated with the old text superseded: recommendation 2 (2 Ohm +0.72 to +1.39 V over 3-8 us, +0.76 to +1.09 V at
   4 us; 1.5 Ohm +0.25 to +0.53 V; 1 Ohm +0.030 to +0.078 V; 0.9 Ohm +0.015 to +0.041 V) and bench item 2 (2 Ohm, 16 V:
   OUT above +0.7 V, FET opens 4.3-10.0 us after the short, FET current at the trip 3.6-6.6 A).
7. A shorter delay lowers the OUT minimum of the fast-trip shorts (the FET opens on an earlier, higher part of the
   lead-current ring). The old 6 us base overstated the 2 Ohm margin by 0.07 V (4 us) and 0.11 V (3 us).

### 1.4 R2-PWR-0: current-limit dwell after a trip (RECORDED in sim 1; not simulated)

`sim/hardshort/RESULTS.md` section 5.7 (Table 7b), Table 8 new row, section 3 item 2, section 7 item 1, bench items 5
and 6, Table 9a. Sources: TCKE1401NM DS Rev. 3.0 sec. 7.8 and 7.9 (p.9), Formula 9 (p.9), Table 10.1 (p.14), Table
10.2 (TSD 165 C typ., p.15), Table 10.3 (tCL_PLIM 130/160/190 ms, tCL_PLIM_FLAG 1.0/1.9/3.5 ms at 12-75 V, p.16),
Table 7.3 (MODE open: latch-off, p.11), Table 8.1 (PD 2.2 W, Note 9). Numbers (I_LIM 1.97/2.37/2.77 A, the 9 kOhm row
scaled by 2.367/2.21, UNVERIFIED extrapolation):

| Case | P at 16 V (W) | P at 23.6 V (W) | E, 23.6 V, 190 ms (J) | E, 16 V, 190 ms (J) |
|---|---|---|---|---|
| Hard short (step 2) and step (1) CC load, bound VIN x I_LIM | 31.5-44.3 | 46.5-65.4 | 8.8-12.4 | 6.0-8.4 |
| 2 Ohm fast-trip short, (VIN - 2 I_LIM) I_LIM | 23.8-29.0 | 38.7-50.0 | 7.4-9.5 | 4.5-5.5 |
| 1.5 Ohm fast-trip short | 25.7-32.8 | 40.7-53.9 | 7.7-10.2 | 4.9-6.2 |
| Step (3) OVP trip, 1.7 A | no dwell (1.7 A < 1.97 A) | - | - | - |

Also recorded: an ASSUMPTION that an SCP turn-off, and a UVLO turn-off after VIN recovers, also end in the dwell
(TODO(verify: Toshiba)); an analytic, unsimulated estimate of the final turn-off at the end of the dwell on a
low-resistance short: OUT near -0.83 V for 0.54 us (STPS2H100A fit) or -0.63 V for 0.71 us (MBRA2H100T3G)
(TODO(calibrate) against the T-C-04 scope capture). The fast-trip-short substitute removes the negative excursion of
the first turn-off, but not the dwell.

Left for the design-document agent (not edited here): the B.4 fault paragraph and the T-C-04 row (step (1) label
"above I_LIM x 2.0", repetition counts, the 200 ms scope requirement, the I_LIM measurement at VIN - VOUT = 1 V).

### 1.5 R2-SIM-5: FR-12(b1) zero-draw maximum (no sim file wrong)

Sim 5 Table 2 is correct: OVP_START 22.28 V, all I_evm, 4.021 s; ON 22.28 V 4.010 s (`results/headline.txt`
agrees). A one-sentence note under Table 2 now states that a quotation of the zero-draw worst case must use 4.02 s.
The design-document rows H.21 and H.23(q) ("up to 4.01 s") belong to another agent: the correct figure is 4.02 s.

## 2. Verification

- `run.py --tft-check` ran twice (528 cases each, 0 failed); the second run (after a table-header fix) gave identical
  aggregates. The 6 us subset reproduces the revision-2 CSVs exactly. `sim/models/hardshort_*.lib` md5 unchanged.
- `run.py` parses (ASCII, `ast.parse`).
- Comparators: CSV byte comparison, `summary.json` field comparison, masked console comparison and the topology
  asserts, as listed in 1.1.
- No board, BOM, fab, generator or design-document file was edited.

## 3. For later agents

- New numbers for T-C-04 / B.4 text: fast-trip-short OUT minimum over tFASTTRIP 3-8 us: 2 Ohm +0.72 to +1.39 V
  (+0.76 to +1.09 V at the 4 us typical), 1.5 Ohm +0.25 to +0.53 V, 1 Ohm +0.030 to +0.078 V, 0.9 Ohm +0.015 to
  +0.041 V; 2 Ohm at 16 V: trip 4.3-10.0 us after the short at 3.6-6.6 A.
- Dwell bound per event: up to 65.4 W / 12.4 J at 23.6 V, 44.3 W / 8.4 J at 16 V (hard short, step (1)); 2 Ohm short
  29.0 W / 5.5 J at 16 V.
- FR-12(b1) zero-draw worst case: 4.021 s (OVP_START), not 4.01 s.
- Cite sim line numbers as "at tag charger-r8-pre-review-2026-11-14".
