# Phase B notes: wiring design document and firmware rules (round 2026-11-14)

## 1. Scope

This note records the text changes of round r9-25 in two files:

- `docs/charger_bq25798_wiring_design_2026-11-05.md` (the design document, "DD"); and
- `hardware/charger_evm_r8/decisions_2026-11-12/round2/dec2_firmware_rules_2026-11-12.md` (the firmware rules).

The inputs are `hardware/charger_evm_r8/REVIEW_2026-11-14.md` (the review), the five simulation records
`hardware/charger_evm_r8/sim/{hardshort,chopper,comparators,permit,efuse_decay}/RESULTS.md` (sims 1-5, final revisions
with their "Check and corrections" sections), the 2026-11-14 decisions on D103, R130/R131A and C106-C108, and the BOM
set `hardware/charger_evm_r8/bom_2026-11-14/` with `update_2026-11-14/notes_phaseB_bom.md`.

No board, netlist, BOM, simulation, firmware, CLAUDE.md, WORK_QUEUE.md, IO CSV or companion-document file was edited.
Nothing was committed. Superseded text stays in place in the form `(**Superseded 2026-11-14, <reason>:** "old text")`.
The design document now carries 157 such markers. Both files keep their CRLF line endings.

## 2. Files changed

| File | Change |
|---|---|
| `docs/charger_bq25798_wiring_design_2026-11-05.md` | 321 lines inserted, 167 deleted (git diff --stat); one new 0.3 row (r9-25), one J.1 item (26), J.2 items 74-81 |
| `hardware/charger_evm_r8/decisions_2026-11-12/round2/dec2_firmware_rules_2026-11-12.md` | decision 8 trigger set, decision 4a note, ten new section 3 items |
| `hardware/charger_evm_r8/update_2026-11-14/notes_phaseB_wiring_doc.md` | this note |

## 3. Changes in the design document, with evidence

### 3.1 Status, change list and records

| Location | Change | Evidence |
|---|---|---|
| Status (line 3) | New status sentence for r9-25 before the 2026-11-12 status | DOC-12 |
| Section 0.2 r8 bullet | FLT bridge figures restated for the TCKE1401NM (3.48 mA, factor 2.87, 0.302 V) | DOC-12; DD B.4 R106s row |
| Section 0.3 | Row r9-25 added after r9-24; cites the review and the five sims | task brief |
| r9-20 row | 0.69 V OVP-to-clamp gap with leakage; the clamp rests on the VR-1 premise | sim 5 Table 1; VR-1 |
| A.1 EIB row, A.9 outline | 24.0 x 38.0 mm | EIB-6; LAYOUT_DECISIONS D-25 |
| A.3 W2, A.6, A.7, A.8, B.8, D.4, T-A-06 | W2 at (27.2, 61.2) | INT-7; pcbnew read of `cr/cr.kicad_pcb` (W2 pad KiCad (27.2, 38.8)) |
| A.3 W6/W7, A.8, B.8 | W6 TS_EXT (23.81, 58.58), GND (23.81, 61.12); W7 SCL (48.81, 53.08), GND (48.81, 55.62), SDA (48.81, 58.16); 1.0 mm drill, 1.8 mm pad | INT-7; pcbnew read of `cr/cr.kicad_pcb` |
| A.3 W5 row, A.6, A.7 J101 bullet, A.8 J101 region, A.9 J201, B.6 J201/R273, B.8 J101/J201 | Nine soldered wires on the D-66 3 x 3 grids; GND on wires 3 and 9 | INT-3, DOC-6, EIB-6; LAYOUT_DECISIONS D-66, Table D-66 |
| A.3 W7 row | W7 soldered to J8 pins 2/3; KK housing superseded | D-66 |
| A.3 r9-4 paragraph, D.1 PM6 | CR removal procedure: desolder W5 and W7 at one end (TODO(decide: operator, CR end or EIB/EVM end)), or lift CR, EIB and EVM plate together | DOC-4 |
| A.4, D.1 PM6, E tap pins | Male 0.100 in (0.64 mm square-post) crimp pins mating the MB 87606-324LF receptacles | INT-6 |
| A.4 | Full-voltage-tap requirement pointer | VR-4 |
| A.7 | EIB-to-J5 clearance about 0.77 mm; EIB placed at least 2.3 mm higher; E3/E8 lengths TODO(recalc: r7_calc.py H.23(l) with EIB_H 38.0) | EIL-3 |
| A.8 copper bullet, H.25 | R9.H25 formulas at 2.77 A: required 4.234 mm; D-57 section 10.2 C, D-56 section 11.9 C; three vias 4.00 A (1.44 x); J1.10 solid perimeter 3.456 mm below 4.234 mm; formal calc run stays TODO(recalc: D-67) | CRL-2; scratch script `C:/Users/ricky/AppData/Local/Temp/claude/update_2026-11-14/phaseB/wiring_doc/h25_277.py`, which copies the formulas of `docs/reviews/charger_eval_2026-11-05/round4/calc/r9_calc.py` lines 1018-1042 and reproduces the published 2.57 A and 2.75 A |
| A.9 Ground | AGND pours on both layers (D-63, D-68) | EIB-6 |
| D.1 PM3 | T2 wire from J-TAP A1 (pin 1) | INT-1 |
| D.1 PM4, E CHG sockets | SSQ-110/112-01-G-S (ordered -G) | `bom_2026-11-14/system_bom.csv` |
| D.2, FR-01 | Pin 7 left unconfigured, never driven | FW-10 |
| D.3 | Row 22 marked as proposed text; CSV edit pending (INT-4); gain band 17.58-38.22 uA/A | FW-3 |
| D.5 | The three "No change beyond D.4" statements superseded; new r9-25 proposal table with the exact CLAUDE.md change for operator approval | FW-0 |
| Section E | 2026-11-14 paragraph naming `bom_2026-11-14/`; rows for EVM, U101, U118, U202, Q201/Q202, D103, D107, D104-D106, R102, R109, R110/R112, R115, R170/R171, 100 nF, C101, C102a/b/c, C103, C125, C108 option, C252, C (MB), C (EVM), CR PCB (6, D-62 outline, four NPTH), EIB PCB (3, 24.0 x 38.0 mm), J101, W5 key, J201, W5, W7 mate, tap cable, CHG sockets, stencils, cost | DOC-1, BOM-12; `bom_2026-11-14/*.csv` and README sections 3-5 |
| B.8 Mechanical | Four 3.70 mm NPTH MH1-MH4, D-62 outline | LAYOUT_DECISIONS D-60, D-62 |
| B.8 J-TAP row | r9-13 cavity map from `cr/cr.net` J102 (pad nets read with pcbnew) | INT-1, DOC-3 |
| L.8 CHG-R1-03 | Six transactions after the EX1 poll | FW-1 |

### 3.2 U101 eFuse (TCKE1401NM)

| Location | Change | Evidence |
|---|---|---|
| B.4 R102-R104, H.5, T-C-04 pass | UVLO rising 9.055-10.548 V, falling 8.203-9.934 V; OVP rising 21.588-25.019 V, falling 19.899-22.927 V; 0.348 V above 10.2 V; 0.69 V below 22.28 V; 0.18 V below 25.2 V | PWR-2, DOC-0; sim 5 section 4.1, Table 1 |
| B.4 R102-R104, T-C-04 (d) | VSEL_OVP band crossed for VCHG-IN 3.14-4.98 V; latch TODO(verify: Toshiba); ramp test added | PWR-3 |
| B.4 C102a/C102b/D103 | Placement by the A.8 <= 2 nH rule (8.50 / 5.01 mm centres); C102a pad edge 2.09 mm | PWR-6 |
| B.4 C102b | About 2.90 uF at the 25.02 V OVP maximum, 3 % below 3 uF; H.19 figure TODO(recalc: D-67) | sim 5 Table 1; r9-22 TDK data |
| B.4 D103, E D103, T-A-05, J.1 item 5, J.2 item 79 | STPS2H100A stays; MBRA2H100T3G alternate is an operator question; criterion (3) inconsistency named; criterion (4) open | 2026-11-14 D103 decision; PWR-0; sim 1 sections 5.1 and 6 |
| B.4 D103, H.5 OUT, J.1 item 5 | OUT -3.8 to -7.8 V, spike 4-8 V for 0.2-0.4 us, plateau -0.6 to -2.7 V, below -0.3 V for 2.9-11.2 us; TI basis replaced by TODO(verify: Toshiba) | sim 1 Table 8 |
| B.4 D107, E D107 | Ordered SMAJ33A; 24-108 J per burst if the RT1987 OVP does not act below 36.7 V; energy rating TODO(verify) | sim 2 section 5.5 |
| B.4 MODE | OVP appears self-releasing; TODO(verify: Toshiba) | sim 2 section 5.6; VR-2 |
| B.4 EN | 0 V guaranteed margin; clean pin-12 area; optional bodge | PWR-4, DOC-13 |
| B.4 R105, FR-01 | CHG_IIN gate (V_chg > 10.2 V and FLAG HIGH) | FW-2 |
| B.4 R106 | Not fitted, no footprint | DOC-12 |
| F.5 T1 step 2 | UVLO_ton typical only, 0.539 ms | DOC-13 |
| F.5 T10 proof (b), H.21(g) | Proof level 8.0 V; decay to 8.0 V about 55-181 ms (hand estimate, TODO(recalc: D-67)) | sim 5 section 4.1; DOC-0 verifier inputs |
| H.15, H.23(q) | IQ(ON) table layout confirmed; totals stay TODO(recalc: D-67) | DOC-13 |
| T-C-04 | Items (a)-(i): step (2) last; no 8 V pre-step; 2 ohm / 1.5 ohm fast-trip short with pass > +0.8 V and 3.7-6.3 A; UVLO/OVP trips; OVP latch-or-release capture; open-EN voltage; reverse-current FLAG; FR-12(b1) decay measurements; Toshiba question; PG_STAT/REG1B instead of pin 7; 4.7 V | sim 1 sections 5.3, 6, 8; sim 2 section 8 item 5; sim 5 section 7; PWR-3, PWR-4, FW-5, FW-9, DOC-5 |
| T-B-23, J.2 item 74 | R101 7.87 kOhm (about 2.53 A typical) as an operator item | DOC-0 |
| J.1 item 26 | D-67 accepted risks; TPS26601 source TODO(verify) | DOC-5 |

### 3.3 Firmware requirements (G.1, G.2) and the rules file

| Location | Change | Evidence |
|---|---|---|
| G.1 ADC row, fresh-read paragraph, poll schedule | REG2F = 0x3E, REG30 = 0xF0; 12 ms scan; explicit mask switches; fresh read defined by time | FW-1; SLUSDV2C Table 7-56 p.114, Table 7-57 p.115, section 7.3.10 p.47, section 6.5 p.16 (read from `references/TI_BQ25798_design_files/BQ25798_SLUSDV2C.pdf`) |
| FR-23 EX1/EX2, FR-48(a)/(b), L.8 | REG2F:30 = 0xEE 0xF0 before the one-shot; T_ADC_ONESHOT 9 ms typical; six / seven transactions | FW-1 |
| G.1 self-check | Accept 0x03 0x48 or 0x03 0x40; action TODO(decide: firmware round) | FW-7 |
| FR-08(b), FR-22, rules decision 8 | CHG_STAT in {1h, 2h, 3h, 4h, 6h} or IBAT > 50 mA | FW-6; SLUSDV2C Table 7-37 |
| FR-08(d), FR-11, A.8 T1 row, H.22, FR-49, T-E-05 | V_chg with REGEN closed; V_rgn coarse only; pin-39 over-range cannot fire | VR-3; sim 2 section 5.1 |
| FR-11, FR-33 | Inside the FR-01 CHG_IIN gate | FW-2 |
| FR-12(a2), rules section 3 | k = 0.2, dV_bus >= 2 V, inconclusive short windows, k 0.5 after U-SNT repair; P0 gate at 10.84 V from the 12.34 V V_fc clip (`teensy_controller.ino`:2024, read only) | VR-3; sim 5 sections 2.3 and 5(c) |
| FR-12(b1), H.21 pin-38 row, H.23(q), rules section 3 | Slope test with a timed fallback; 1.5 s gated by four T-C-04 measurements | PWR-1; sim 5 sections 4.2 and 5(b) |
| FR-12(b2) | 12.96 s wait with zero EVM draw is a skipped probe | sim 5 section 4.2 |
| FR-12 | 4.7 V VIN/VSYS minimum | PWR-6, FW-9 |
| FR-23 EX2 | IBUS check before the carrier-fault latch (reverse-current FLAG) | FW-5 |
| FR-30 | U101 OVP trip invisible to FR-30; threshold an operator item | VR-2; sim 2 section 5.6; sim 5 section 4.1 |
| FR-45 | No `analogRead()` in the timer domain | FW-11 (core line numbers as cited by the review, TODO(verify: core version in use)) |

### 3.4 Permit logic, comparators and the W5 grids

| Location | Change | Evidence |
|---|---|---|
| F.2 GATE column | Per-row text for Init, Idle, Finish, State 99, T10, Teensy reset, Run entry | LOG-3; sim 4 Table 5.0 |
| B.7 Teensy reset, B.7 hang row, F.2 hang row, 0.2, H.24(b), T-D-01 | Keeper bound 17.0 uA for a guaranteed LOW; 42.6 uA is the HIGH guarantee | sim 4 section 5.3, Table 5.2 |
| B.7 CR 3V3 lost row | T6 timeline: release drops at 34-45 ms, /CE HIGH after 72-119 ms | sim 4 section 5.5, Table 5.3 |
| B.1 H1 row, B.2, F.3 new T2 row, T-D-04, J.2 item 77 | Lost/interrupted T2 release pulse; C106-C108 decision | sim 4 section 5.6, Tables 5.4 and 5.5; 2026-11-14 C106-C108 decision (re-run figures from the unreviewed scratch re-run at `C:/Users/ricky/AppData/Local/Temp/claude/update_2026-11-14/phaseB/verify_c108/sim/permit/recon.csv` and `recon2.csv`, as relayed in the decision) |
| F.3 divider-bottom row, T-D-04 | R111 open, C107 short, D105 lower-diode short, N_H1M to GND | LOG-0 |
| F.3 new R187 row, T-C-12 | 1.536 V EN net in reset; R187 > 3 MOhm check | LOG-1; sim 4 Table 5.2 |
| F.3 gate-stuck-HIGH row, T-C-01, T-C-05 | U106B / RFC_OFF stuck HIGH | LOG-2 |
| B.6 ribbon row, new grid-bridge row, H.20, H.24(d), T-A-06, T-C-05, T-C-13, J.2 items 70 and 76 | D-66 grid bridges; 3V3-GND bridge 1.85-2.06 V and 18.3-20.5 mA; R130/R131A stay 100 ohm; orthogonal pair lists for both grids (derived from Table D-66) | INT-0, EIB-0, EIB-1, EIB-2; sim 4 section 5.8, Table 5.6; 2026-11-14 R130/R131A decision |
| B.3 edge rate, J.2 item 80 | About 166 ns/V on the 4.99 kOhm paths | 2026-11-14 R130/R131A decision |
| B.6 closing paragraph | REGN live from BAT with ADC_EN = 1 | EIB-4; SLUSDV2C section 7.3.4.1 |
| B.6 ILIM levels, H.4, H.7 | IINDPM_ACC downward tolerance (FC about 15-17 %, regen about 10-12 %) | EIB-5; SLUSDV2C section 6.5 p.12 |
| H.1, H.2, J.2 item 78 | Worst-case margins with TCR; H1 fall 17.843 V, 3 mV over VINDPM_STAGE1 | sim 3 section 5.2, Tables 4, 5, 5a |
| H.1 ripple, T-E-07 | 0.36 V p-p at 8 kHz | sim 3 section 5.7, Table 10 |
| B.2 | Full-voltage-tap requirement; H1+ ratio kept; VR-4 0.08 not adopted; B suffix load-bearing | VR-4; sim 3 sections 5.5 and 5.6 |

### 3.5 V-MOT premise and regen (VR-1, VR-2)

| Location | Change | Evidence |
|---|---|---|
| C EM14, threshold stack, H.5, H.7, F.3 regen rule, J.2 item 15, F.5 T2 residual, J.2 item 81 | 21.2-21.5 V, VESC cut 21.35 V and clamp 21.98-22.28 V marked invalid; healthy chopper 21.35-23.10 V; 23.4-25.2 V true at the logged 18.26 V | VR-1; sim 2 sections 5.1 and 6 |
| J.2 item 74 | OVP band vs chopper band, U101 cycling, harvest cliff, levers (OVP minimum >= 23.40 V or VESC cut below the band), VESC `l_max_vin` bench item, FR-30 and R101 operator items | VR-2; sim 2 sections 5.2, 5.6, 5.7, 6 and 8 |
| J.2 item 75 | D-BC-RG 45.9-83.7 A for about 1.5 us; R-G 0402 overstress 0.21 W | sim 1 section 5.4; sim 2 section 5.4 |

## 4. Changes in the firmware rules file

- Decision 8: trigger set CHG_STAT in {1h, 2h, 3h, 4h, 6h} or IBAT > 50 mA, with the fresh-read definition; old text kept
  as superseded (FW-6, FW-1).
- Decision 4a: note on the CHG_IIN gate (FW-2) and the 8.0 V proof (b) level (sim 5 section 4.1).
- Section 3: ten new 2026-11-14 items (FR-12(a2), FR-12(b1), FR-12(b2), ADC masks, FR-08(b), V_chg with REGEN closed,
  self-check, FR-23 EX2, FR-45, CLAUDE.md conflict).

## 5. Left open

- Operator questions (DD J.2): D103 MBRA2H100T3G swap and criterion (3) restatement (item 79); W5 grid isolation check
  or grid reorder (item 76); C108 470 pF option or a design change (item 77); H1 fall 3 mV overlap (item 78); OVP band
  levers, FR-30 threshold and R101 7.87 kOhm (item 74); whether T-C-04 step (2) runs at all (J.1 item 5); CR removal
  end for W5/W7 (A.3); the CLAUDE.md change in D.5 (FW-0, operator approval before the firmware round).
- TODO(verify): Toshiba (OUT excursion, OVP release, VSEL_OVP latch, reverse comparator without Q1); SLUSDV2C ILIM_HIZ
  deglitch; SMAJ33A energy rating; onsemi/ST pulse rating; i.MX RT1062 injection limit; SCES364J/SCES295AB edge-rate
  limit; Nexperia 2N7002BK Vgs(th); RT1987 soft-start slew; TPS26601 fallback source; Teensyduino core version.
- TODO(recalc: D-67): the formal `r9_calc.py` run at the 2.77 A basis (H.25, A.8), the H.15 total, the H.21(g) decay to
  8.0 V, the C102b H.19 figure at 25 V, and `r7_calc.py` H.23(l) with EIB_H 38.0.
- Not done (other owners or outside this brief): the companion document `docs/charger_bq25798_custom_board_2026-11-10.md`
  (VR-1 lines, C308); README sections 7, 8.5, 8.6, 9-12; LAYOUT_DECISIONS D-67 bands, P-08 margin and section 11 item 13;
  HANDOFF.md line 202; the IO CSV row 22 (INT-4); `gen/readme_figures.py` Fig 2.1; a formal sim 4 re-run with 2-40 us
  T2 interruptions; the r9-13 netlist freeze hash (DOC-11, new hashes in `notes_phaseB_bom.md`).
- Style: many inserted sentences follow the long-sentence pattern of the surrounding rows and exceed the 25-word target;
  a style pass is still open.
- Several live sections still describe the retired ribbon in detail (A.3 W5 routing history inside the superseded
  quote, A.7 J101 bullet body, J.2 items 31 and 59, B.6 n / n+1 pair list); they are marked superseded or pointed to D-66
  but not rewritten.

## Fix round 1 (2026-11-15, check1 issues 1, 8, 9 and 11)

- J.2 item 77: the permanent-open peak now reads "0.56-0.86 V at VBUS 15.9-16.4 V (0.21-0.46 V at 14.5 V)"
  (`sim/permit/RESULTS.md` Table 5.4); the brief-interruption figures cite the scratch files
  `phaseB/verify_c108/sim/permit/recon.csv` and `recon2.csv`.
- T-A-06 r9-25 addition, B.6 W5 row and J.2 item 76: the orthogonal-pair isolation check is marked pending the
  operator ruling of J.2 item 76, option (a).
- r9-25 BOM paragraph, cost paragraph and J.2 item 79: the optional lines are in `bom_2026-11-14/digikey_optional.csv`;
  ALT D103 is 2 parts for a test fit, order 3; the optional lines total about USD 4.74.
- Details: `notes_phaseB_fix1.md` sections 3.1, 3.2 and 3.8.
