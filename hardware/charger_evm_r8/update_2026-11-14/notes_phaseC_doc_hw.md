# Phase C notes: doc_hw (wiring design document, hardware sections)

## 1. Scope and method

This note records the phase C changes to `docs/charger_bq25798_wiring_design_2026-11-05.md` in sections 0, A, B.1-B.8,
C, D.1, E, H, I, J and K. Sections B.9, D.2-D.5, F and G were not edited; another agent owns them. The document is now
revision r9-26 (section 0.3 row r9-26 and the status line).

Every change was made by an exact-match replacement script that checks the match count before it writes. The scripts
and a pre-edit backup are in `C:/Users/ricky/AppData/Local/Temp/claude/phaseC/doc_hw/` (`edA.py`, `edB.py`,
`edC.py`, `edH.py`, `edI.py`, `edJ.py`, `edK0.py`, `backup_wiring.md`). Superseded text is kept in the form
(**Superseded 2026-11-15, reason:** "old text"). No pin, net, copper, value or fitted part changed. No operator decision
was taken.

## 2. Verification

- Line endings: 0 bare LF before and after (CRLF kept); 4616 lines before, 4681 after.
- Tables: every row of every table has the pipe count of its header row (checker `check.py`). Two rows failed on the
  first pass because the parallel-resistance notation "||" added pipes; the notation was replaced by "in parallel with".
- Section map: a line diff against the backup touches only the status line (line 3) and sections 0.3, A.1, A.4, A.6,
  A.7, A.8, A.9, B.1, B.2, B.3, B.4, B.6, B.7, B.8, C, D.1, E, H, I, J.1, J.2 and K (`secdiff.py`).
- Numbers were taken from the phase C RESULTS revisions: sim 1 revision 3 (sections 5.6, 5.7, Tables 6, 7a, 7b, 8),
  sim 2 section 5.8, sim 3 Tables 4, 6 and 7, sim 4 section 5.6a (Tables 5.4a-5.4d), sim 5 Tables 1 and 2. The sim 3
  and sim 4 tables were read directly; the sim 2 lever figures come from the sim_chopper phase C report.

## 3. Changes by review finding

| ID | Status | Where | Change and evidence |
|---|---|---|---|
| R2-PWR-0 | FIXED | B.4 fault paragraph; T-C-04 steps (1), (c), (i)-(l), pass and fail columns; H.5 OUT row; J.1 item 5; J.2 item 84 | Fast trip or SCP, then re-turn-on into I_LIM regulation for up to tCL_PLIM 130-190 ms or TSD, then latch-off (TCKE1401NM DS Rev. 3.0 §7.8, §7.9, Table 7.3, Table 10.3; sim 1 section 5.7, Table 7b: up to 65.4 W, 12.4 J). Step (1) measures I_LIM at VIN - VOUT = 1 V. The fast trip is tested only above the 2 x I_LIM band 3.94-5.54 A (item (c), 8 A). Repetitions: 5 of step (1) and (3), 3 of item (c), at most 1 of step (2), pending Toshiba. Item (j) scopes VOUT, the W1 current and FLAG for 200 ms. The Toshiba query adds the repetitive current-limit/TSD rating |
| R2-PWR-1 | NOT FIXED here | LAYOUT_DECISIONS D-67, P-08 | Outside this brief (records agent) |
| R2-PWR-2 | FIXED | T-C-04; H.5 IN-side row; J.1 item 5 | The r8 FR-12(b1) paragraph and the TI E2E sentence are superseded; "re-run from 8 V" becomes 10.6 V (twice); the MB feed at 10.6/12 V; H.5 carries the sim 1 IN peaks (<= 33.6 V grid, 34.3 V at tSCP 2 us; about 1.7 V to 36 V) and points to T-C-04 items (a)-(c); the plateau is -0.6 to -2.7 V for 2.9-11.2 us (sim 1 Table 5) |
| R2-PWR-3 | FIXED | B.4 R102/R103/R104 row; T-C-04 item (d) | VSEL_UVLO 153.2-272.8 mV is crossed at VCHG-IN 1.27-2.26 V; T-C-04 (d) confirms turn-on in 9.055-10.548 V, not near VSYS_UVLO 14.61-23.62 V; TODO(verify: Toshiba) |
| R2-PWR-4 | FIXED (basis); option RECORDED | B.4 C102c and C103 rows; J.2 item 85 | Basis restated on TCKE1401NM Table 9.1, Tables 10.3/10.4 (COUT = 1 uF), Figure 12.1 and section 12.2; sim 1 Table 6 C103 sensitivity (STPS2H100A -7.15 V at 1.0 uF against -7.83 V at 0.70 uF); a 4.7 uF part is an operator option |
| R2-LOG-0 | FIXED | B.1 H1 row; B.2 lost-T2 bullet; J.2 item 77 | Citations move to sim 4 section 5.6a; the %TEMP% path and TODO(verify: sim/permit re-run) are kept only in superseded quotes. F.3 (line about 2801 before the edit) is outside this brief |
| R2-LOG-1 | FIXED | B.3, B.8 header and U107 row, T-A-05 | Pinout closed on SCES487I Table 4-1 / Figure 4-1 (one map for DBV and DCK), LAYOUT_DECISIONS section 11 item 18. Rows r9-3 (section 0.3, history) keep their TODO text |
| R2-LOG-2, R2-SIM-3 | FIXED in my sections | B.1 pack-voltage bullet; J.2 item 69 | Keeper bound < 17.0 uA (sim 4 section 5.3). F.4 (line about 3029) is outside this brief and still reads 42.6 uA |
| R2-LOG-3 | FIXED | B.7 Teensy-reset row, ILIM_HIZ column | Held unless H1U = 1, then released at the regen clamp if REGN is present from the pack; charger unpowered, /CE HIGH (sim 4 Table 5.1) |
| R2-LOG-4 | FIXED | B.2 H1, UVB and FCC bullets | Sim 3 Table 4: fall >= 16.732 V (guard 0.832 V) at 15.9 V, >= 15.978 V (0.778 V) at 15.2 V, 17.260-17.843 V and rise <= 18.127 V at 16.39 V. Table 6: UVB fall 12.846-13.818 V (0.30 V margin), rise 13.255-14.188 V. Table 7 closes the FCC TODO: FCC_OFF 0.374-0.436 V (IN- 0.389-0.444 V), FCC_ON 1.732-1.880 V |
| R2-INT-0 | FIXED (document part) | PM4 (2b); T-A-06 test and pass columns | W1 meters < 1 ohm to D103 pad 1 (/VCHGOUT) and W2 < 1 ohm to GND on the bare CR before the leads go in; the board labels 'VIN1' (W1) and 'GND' (W2) are described with LAYOUT_DECISIONS D-85 |
| R2-INT-1 | FIXED | T-A-06; B.6 grid row; J.2 item 76 | Staged check: (i) bare-EIB references, (ii) J201 end soldered with the CR ends free, (iii) bare-CR readings and the free-wire-end readings R_W, (iv) CR ends soldered, each CR pair equals R_CR in parallel with R_W within 10 %, (v) loupe inspection. Wire n joins J101.n and J201.n (A.3). The 10 % band is TODO(calibrate: T-A-06 first build), because junctions make readings meter-dependent |
| R2-INT-2 | FIXED | B.8 U203, U204 rows | R265.2 / R264.2 not connected (D-66) |
| R2-INT-3 | FIXED | A.6 power-star bullet | 23.7 mm to pad 4 and 7.6 mm to pad 14, from W2 (27.2, 61.2) |
| R2-INT-4 | FIXED in my sections | A.1, A.7, A.8 J1 row, T-A-05 | SSQ-11x-01-G-S. The fifth instance (D.4 bodge-record text, about line 2381 before the edit) is outside this brief |
| R2-INT-5 | FIXED | A.4 heading and r9-4 paragraph; H tap-wire row; T-A-05 | Workshop-stock mate; TODO re-pointed to the workshop wire gauge against the R170/R171 0805 joints |
| R2-INT-6 | FIXED | D.1 PM3 | Tab X sentences superseded; C-D2 pad 1 lies about 9.1 mm beyond the CR +x edge; the R171 position is recorded in T-A-06 item (13) |
| R2-EIB-0 | FIXED | B.6 U202, Q201, Q202 and threshold paragraph; B.8 Q201/Q202; T-A-03 | SN74LVC1G06DCKT, 2N7002BK,215, BSS84LT1G. The BSS84LT1G threshold figures of the review are quoted with TODO(verify: onsemi BSS84LT1/D), because no local datasheet exists |
| R2-EIB-1 | FIXED | B.6 grid row; T-A-06 | EIB 1-4, 2-4, 4-8 and 3-8 added; 3-9 is one GND_J net and is no bridge check. The STAT absolute maximum is TODO(verify: SLUSDV2C) |
| R2-EIB-2 | FIXED | A.9 E1-E8 row; T-A-06 | E1 positive on every E1 pair, E3 positive on E8-E3 |
| R2-EIB-3 | FIXED | C EM14; D.1 PM2; T-E-03 | GMC21X5R106K50NT 50 V; 25.0 V bias point; the 24.41 V clause superseded; T-E-03 band 21.588-25.019 V |
| R2-EIB-4 | FIXED in my sections | J.2 items 22 and 70(e); A.9 J201 row; B.8 U203/U204 and fit-state list | R256 removed from the EIB fitted list. The schematic title block (gen/sch.py) is outside this brief |
| R2-EIB-5 | RECORDED | B.6 paragraph after the threshold sentence | Deviation from SLUSDV2C 7.3.4.1 (p.26) recorded: only R252, R254 and R271 are non-charger loads, at most about 0.31 mA; about 1 mA in total with TS, against IREGN 30 mA (SLUSDV2C 6.5, p.15); T-B-04 measures the draw |
| R2-CRL-0, R2-DOC-12 | FIXED (record); acceptance RECORDED as J.2 item 82 | A.8 copper bullet and header-pin bullet; H.25; T-A-06 | TODO(recalc: D-67) markers closed in superseded form; H.25 result restated: pass at 2.41 A only; 10.2 C / 11.9 C at 2.77 A; transient-only argument (tCL_PLIM <= 190 ms, service current about 1.75 A). The OSH Park 25.4 um plating figure of the review is noted, not re-read |
| R2-CRL-1, R2-DOC-9 | FIXED | A.8 5 mm bullet; T-A-06 pass column; A.9 REGN row | D-56 strap exemption (about 7.3 mm, buried on In2.Cu); D-84 note (R252.2 at 13.55 mm) |
| R2-CRL-3 | RECORDED | A.8 analog bullet; J.2 item 83 | /CHG_ARM 5.25 mm inside the zone, 0.224 mm from R114.2; exemption left to the operator |
| R2-CRL-4 | RECORDED | A.8 D103 bullet; T-A-06 | Board copper about 0.7-0.8 nH (board agent, notes_phaseC_board.md section 4.5); package inductances TODO(verify); sim 1 3 nH nominal covers it |
| R2-EIL-3 | Nothing left in my sections | A.9 outline row already correct; J.2 items 22 and 70(e) closed | Generator and fab README parts were fixed by the board agent |
| R2-EIL-4 | FIXED | A.9 J201 and REGN rows | F.Silkscreen pin-and-net map (D-73); D-84 note |
| R2-BOM-3, R2-DOC-1 | FIXED in my sections | C EM14; D.1 PM2; E intro, U101, C (MB), C (EVM), CR PCB, EIB PCB and cost rows | Packages exported; EIB a separate OSH Park 2-layer order; two lots of 3; U101 cites bom_2026-11-14/mouser_import.csv; total USD 360-470 with one EVM. README and the BOM README are outside this brief |
| R2-CRT-1 | FIXED (record); conflict RECORDED | E C (MB)/C (EVM); T-A-04; EM14 | Spares = the opt-in SPARE line x5 in digikey_optional.csv (main order exactly 7). T-A-04 adds the 25.0 V bias point (25.019 V OVP maximum). Ordering the SPARE line stays an operator choice |
| R2-CRT-0 | RECORDED | B.4 R129/C129 row; J.1 item 26 (f); T-B-14; T-C-04 items (i) and (l) | TCKE1401NM §7.10 forbids a capacitor on IMON; 27.4 kOhm in parallel with 10.0 kOhm = 7.32 kOhm above about 16 kHz; TODO(verify: Toshiba IMON capacitive load through series R); step capture with and without C129 |
| R2-DOC-4 | FIXED in my sections | T-C-04 (r8 sub-step superseded); T-C-05c; J.2 item 65 | 9.055-10.548 V rising, 8.203-9.934 V falling (sim 5 Table 1). FR-12 (G.2) is outside this brief; history rows of section 0.3 keep their text |
| R2-DOC-5 | FIXED in my sections | H.21 check column; T-D-11 | Proof (b) or (d); the T-D-11 window adds 180 ms. F.5 T10 (40-100 ms) is outside this brief |
| R2-DOC-8 | FIXED | A.8 +x pocket row (two places); T-A-05 | C101 KEMET C0603C223K5RACTU (D-82) |
| R2-DOC-10 | FIXED | K (new bullet "r9-25 and r9-26 additions") | Review, five RESULTS files, D103 sources (ST DocID6115, onsemi MBRS2H100/D Rev. 16, CASE 403D Issue J, the onsemi model), SBOS300C Figures 8-12/8-13, SCES487I, TCKE1401NM sections, SLUSDV2C pages, LAYOUT_DECISIONS D-73/D-82/D-84/D-85/D-86 |
| R2-DOC-13 | FIXED in my sections | J.1 item 24; J.2 item 73; E W-lead anchors row | "ribbon conductor" becomes "W5 wire"; the S1/S2 fold text is superseded by D-66. README section 7 is outside this brief |
| R2-SIM-0 | RECORDED (evidence sharpened) | J.2 item 74 | Lever (a) restated from sim 2 section 5.8: no-leak minimum about 23.7 V, leak maximum about 26.8 V; candidate 845k/68.1k/47.5k gives 23.256-26.863 V, 0.66 V above the BQ25798 VBUS_OVP maximum 26.2 V; the conflict is structural (1.100 spread, >= 25.41 V); 0.5x string 23.163-26.180 V with TODO(recalc: sim 5 part b). A note states that a retune changes the Mouser order (R2-DOC-0). The decision stays open |
| R2-SIM-1 | FIXED in my sections | B.2; J.2 item 77; T-D-04; T-E-07 | 5-30 us band (sim 4 Table 5.4a); T-D-04 interrupts T2 for 5, 10, 20 and 30 us. D-81 and F.3 are outside this brief |
| R2-SIM-2 | FIXED | J.2 item 77 | 197-269 us (4.7 nF) and 340-598 us (10 nF) of H1 inhibit latency (sim 4 Table 5.4b); the 134/232 us figures are superseded |
| R2-SIM-5 | FIXED | H.21 and H.23(q) | Up to 4.02 s (4.021 s, OVP_START, sim 5 Table 2) |
| R2-SIM-6 | FIXED in my sections | r9-25 row; B.4 MODE row; C EM14; T-C-04 item (e); J.1 item 26 (b); J.2 item 74 | Onset wording; self-release cited to TCKE1401NM §7.3/§7.5 and the Table 10.3 OVP_ton rows, sim 2 section 5.6 only for the consequence |
| R2-SIM-9 | FIXED in my sections | T-C-04 item (c) and pass column; H.5 OUT row | 1 ohm +0.030 to +0.078 V; 2 ohm +0.72 to +1.39 V and 3.6-6.6 A over tFASTTRIP 3-8 us (sim 1 Table 7a) |
| R2-FW-1 | RECORDED | B.4 MODE row | The reset needs VSYS below V_UVLOF (8.203-9.934 V); the latched-U101 rule is open in G.2 (FW-4), not mine |
| R2-FW-2 | FIXED in my sections | T-B-16 | TDIE is logged under a State-98 diagnostic mask; mask value TODO(design: G.1). The poll schedule and FR-20 are outside this brief |
| R2-FW-12 | FIXED in my sections | B.1 keeper; T-C-04 FLAG below 4.7 V | FLAG state below 4.7 V is unspecified and recorded. D.4 and the rules file are outside this brief |

The sim 4 H.13 overdrive-model note (139.1-149.6 us at 1.80 A, below the T-B-06 150 us) is recorded in H.13 and T-B-06
without a design change, with TODO(verify: SBOS300C tPD at a ramped input of about 0.5 mV/us).

## 4. New J.2 items

- Item 82: VCHGIN strap and J1.10 joint at 2.77 A (acceptance of the transient-only over-basis rise).
- Item 83: /CHG_ARM inside the D-36 divider-top zone (exemption or re-route).
- Item 84: U101 current-limit dwell and the T-C-04 repetition counts (confirm counts, spare U101, step (2)).
- Item 85: C103 value (keep 1.0 uF or fit 4.7 uF).

Table J.2-1 in item 77 is the option table of sim 4 Table 5.4d.

## 5. Left open, and why

- Operator decisions: J.2 items 74, 76, 77, 78, 79 and 82-85, FW-0, D103, R130/R131A, C106-C108, the W5 grid reorder and the
  SPARE lines. The evidence was sharpened only.
- History rows of section 0.3 (r9-3, r9-20 and others) keep their original numbers; they are revision history.
- TODO markers left with a reason: Toshiba questions (dwell after SCP/UVLO, repetitive rating, IMON capacitor, VSEL
  latching, MODE on OVP); BSS84LT1G thresholds (no local datasheet); SLUSDV2C STAT absolute maximum; Cal-Chip DC-bias
  curve; distributor stock of 0.1 % 68.1k/47.5k; sim 5 part b for a scaled string; the T-A-06 10 % band; OSH Park
  plating (review figure not re-read).

## 6. For the later agents

- **B.9 / D.2-D.5 / F / G owner:** stale items remain there: F.3 T2 row cites sim 4 section 5.6 and "10-20 us" (R2-LOG-0,
  R2-SIM-1; use sim 4 section 5.6a, 5-30 us, 1.810 V, 50.7 us); F.4 keeper "< 42.6 uA" (R2-LOG-2; use < 17.0 uA); F.5
  T10 "40-100 ms" (R2-DOC-5; 55-181 ms); G.2 FR-12 "9.46-10.14 V" and its closed TODO (R2-DOC-4; 9.055-10.548 V);
  FR-08 "eFuse-fault handling" (R2-FW-1); the poll schedule and FR-20 (R2-FW-2); B.9 QUAL wording (R2-FW-6); D.3 row 22
  (R2-FW-10); D.4 CSV row list (R2-FW-12); the D.4 bodge-record "SSQ-110-01-L-S / SSQ-112-01-L-S" (R2-INT-4, fifth
  instance). The firmware-facing T-C-04 changes for these agents: FLAG is LOW through the up-to-190 ms dwell before the
  latch (B.4), and the TDIE log of T-B-16 needs a diagnostic ADC mask (TODO(design: G.1)).
- **Records agent:** the design document cites LAYOUT_DECISIONS **D-85** (CR W1/W2 labels) and **D-86** (EIB E-pad
  labels), which the board agent drafted in `notes_phaseC_board.md` section 9; use those numbers. README, HANDOFF and
  LAYOUT_DECISIONS operator-question lists should add J.2 items 82-85 beside items 74, 77, 78 and FW-0 (R2-DOC-0). The
  section E total is now USD 360-470 with one EVM; the optional Digi-Key file is nine lines, about USD 25.80.
- **New numbers:** 2 x I_LIM band 3.94-5.54 A; dwell 23.8-65.4 W, up to 12.4 J per event; repetition counts 5 / 5 / 3 /
  <= 1; T-A-04 bias point 25.0 V; W2 distances 23.7 / 7.6 mm.

## Addendum (phase C fix round, 2026-11-15)

H.21 and T-D-11 restated on the sim 5 decay (0.083-4.39 s); J.2 item 26 (b) 22.28 V clause superseded; HANDOFF residual list adds the schematic title blocks (R2-EIB-4 item 5). See `notes_phaseC_fix1.md`.
