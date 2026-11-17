# Phase C notes: companion document (key `companion`, 2026-11-15)

## 1. Scope

This note records the phase C edits to `docs/charger_bq25798_custom_board_2026-11-10.md` (the CCB companion). The
companion is now revision r4 (2026-11-15). No other file was changed. The backup of the pre-edit file and the two edit
scripts are in `C:/Users/ricky/AppData/Local/Temp/claude/phaseC/companion/` (`companion_backup.md`, `apply_r4.py`,
`apply_r4b.py`). Each script asserts an exact match count for every replacement before it writes. No CCB design value
changes. Superseded text is kept in the form (**Superseded 2026-11-15, <reason>:** "old text").

## 2. Changes by review finding

| R2 ID | Status | Change and evidence |
|---|---|---|
| R2-CRT-2 | FIXED (recorded as open item O-18) | Status notes at §1.10.1, §1.12.1, §2.5.7 and section 4 state that the permit chapters follow [WD] r8, before r8-17 (D-38) and r9-1. Inline notes on §1.12.2 item 4, the F08 tap row, the Table 2.8 T22 row, FR-47, the CSV row 5 note, the §5.10 BQ29200 bullet, the §5.9.1 OVN and CHG_ARM rows, T-A-01c, T-F-17, the §6 PM11 row, the §7.1 PM11 row and the `p5-static-arm-hang` row. The two `vreg-corruption-no-fixed-pack-ovp` ledger rows change from KEPT to OPEN, O-18 (old status quoted). New O-18 in §8.3.1 and item 37 in §8.1. Source: [WD] revision rows r8-17 (line 412) and r9-1 (line 418), and the [WD] verdict paragraph near line 79 |
| R2-SIM-6 | FIXED | The 21.35-23.10 V band is restated as a conduction onset in constraint 2, §1.5, §1.11.1, D2, §2.1.2, the T1_VMOT/T2C row (the finding's fix text) and §5.5.2 item 5. The §1.6.2 and §3.7.1 sentences are qualified to a surplus of about 0.47 A. Self-release is stated as a [SIM2] model input with TCKE1401NM DS Rev. 3.0 §7.3, §7.5 and Table 10.3 as support, and the MODE-latch question as TODO(verify: Toshiba). Source: `sim/chopper/RESULTS.md` §5.1, §5.2, §5.8.7, Tables 5.2-5.3 |
| R2-SIM-0 | RECORDED (companion side) | §1.11.1 gains a lever (a) paragraph: 68.1k / 47.5k gives 23.256-26.863 V; the 1.100 V_OVPR spread forces at least 25.41 V; the 0.5x string gives 23.163-26.180 V with TODO(recalc: [SIM5] part b). Operator decision [WD] J.2 item 74 left open. Source: `sim/chopper/RESULTS.md` §5.8.3-5.8.5, Tables 5.7-5.8 |
| R2-DOC-4 (companion instance) | FIXED | The no-leak bands in §1.11.1 and D2 are the [SIM5] Table 1 corners with the 0.1 % resistor tolerance: OVP 22.149 / 23.188 / 24.457 V, UVLO 9.444-10.158 V. The D-67 figures (9.46-10.14 V, 22.19 / 23.19 / 24.41 V) are quoted as superseded. Source: `sim/efuse_decay/RESULTS.md` Table 1 |
| R2-SIM-9 / R2-PWR-0 (companion instance) | FIXED | The T-C-04 row takes the [SIM1] Table 7a margins (2 Ohm +0.72 to +1.39 V over 3-8 us, +0.76 to +1.09 V at 4 us; 1.5 Ohm +0.25 to +0.53 V) and the current-limit dwell of [SIM1] §5.7 and Table 7b (I_LIM 1.97-2.77 A, up to 190 ms, 23.8-44.3 W at 16 V, up to 65.4 W and 12.4 J at 23.6 V). The I_LIM band and the SCP/UVLO dwell carry TODO(verify: Toshiba) |
| R2-SIM-1 / R2-LOG-0 (companion instance) | FIXED | The C308 row and the T-D-04 row cite [SIM4] §5.6a (Tables 5.4a, 5.4d) in place of the scratch re-run: as built 5-30 us, up to 1.810 V and 50.7 us; 470 pF narrows to 5-20 us; 4.7 nF and 10 nF move the hazard to 30 us and 50 us or longer. The old TODO(verify: formal [SIM4] re-run) is quoted as superseded. Choice left open ([WD] J.2 item 77) |
| R2-CRT-0 (companion instance) | RECORDED | O-17 notes that the TCKE1401NM datasheet forbids a capacitor on IMON (DS Rev. 3.0 §7.10, p.9) and that R329/C329 load IMON through 10 kOhm; TODO(verify: Toshiba IMON capacitive load through series R). The CCB keeps the TPS26630 basis until O-17 is ruled |
| R2-SIM-3 / R2-LOG-2 (keeper bound) | NOT APPLICABLE | `grep "42.6"` finds no instance in the companion |
| "21.90 V" leak corner | NOT APPLICABLE | `grep "21.90"` finds no instance in the companion |
| R2-SIM-5 (4.01 s) | NOT APPLICABLE | No instance in the companion |

Additional records (not review findings):

- The T-B-06 row records the [SIM4] Table 5.4b as-built H.13 budget at 1.80 A: 158.7 us with fixed delays and 139.1 us
  under the overdrive model, the latter below 150 us; TODO(verify: SBOS300C tPD at about 0.5 mV/us). Recorded only.
- Citation keys: [SIM1] is revision 3 with §5.6-5.7; [SIM2] names §5.8; [SIM4] names §5.6a; §9.3 lists the TCKE1401NM
  data sheet Rev. 3.0 (`references/Datasheets/tcke1401nm.pdf`).
- The words "healthy chopper band" became "healthy chopper onset band" in T-B-19, §8.1 item 14 and L-8 without a
  superseded quote; the r4 revision row states this.

## 3. Verification

- Both scripts asserted the expected match count for all 45 replacements before writing.
- A pipe count on every changed table row against its pre-edit version shows no column change.
- A grep for "chopper band", "chopper holds", "clamps at", "9.46-10.14" and "22.19 / 23.19" finds only superseded
  quotes, qualified text or the onset wording.

## 4. Left open

- O-18 (new): whether the CCB adopts D-38 and r9-1. The figure, Table 1.12, the §2.5 netlists, Table 2.8, section 4
  and bom.csv still describe the r8 permit; they are kept as the r2 record with status notes. A rewrite needs the
  operator ruling.
- [WD] J.2 item 74 (U101 OVP band) and J.2 item 77 (C106/C107/C108) stay operator decisions.
- The r4 revision is not reviewed.

## Addendum (phase C fix round, 2026-11-15)

superseded quotes added at T-B-19, section 8.1 item 14 and L-8; the r4 row updated. See `notes_phaseC_fix1.md`.
