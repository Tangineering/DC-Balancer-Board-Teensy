# Digest: charger decision record, review history and battery-isolation gate (for the custom BQ25798 board)

Prepared 2026-11-10 from the worktree `C:\Life Ops\School\Thesis\DC-Balancer-Charger-custom` (branch
`charger-bq25798-custom-board`). Abbreviations for sources:

- **[EVAL]** `docs/charger_replacement_evaluation_2026-11-05.md` (round 2 + round-3 summary, 1120 lines).
- **[WD]** `docs/charger_bq25798_wiring_design_2026-11-05.md` (round 3 r6, 2699 lines).
- **[LOOP]** `docs/reviews/charger_eval_2026-11-05/round3/review_loop.md` (421 lines).
- **[PB]** `docs/reviews/charger_eval_2026-11-05/path_b_respin.md` (419 lines; round-1 era, predates the R3 relaxation).
- **[BI]** `docs/battery_isolation_feasibility_2026-11-07.md`; **[DD]** `docs/reviews/battery_isolation_2026-11-07/detailed_design_IC1.md`;
  **[FB]** `docs/reviews/battery_isolation_2026-11-07/facts_board.md`; **[C1]** `.../concept_IC1-commanded-return-changeover.md`.

Line numbers are those of the files as read on 2026-11-10.

---

## 1. Decision record

### 1.1 Operator rulings

[EVAL] §0.1 numbers the rulings 1-10 (lines 33-65); [WD] §0.1 (lines 23-35) restates them as R1-R9 (R3' replaces R3; the
EVAL ruling 10 "Assumed part for Path A: the BQ25798EVM" is folded into R2). Both are given verbatim.

**[WD] §0.1 table (R1-R9), verbatim:**

| ID | Ruling | Where it lands |
|---|---|---|
| R1 | Regen harvesting and FC charging are both hard requirements | F, H.7, H.8 |
| R2 | Path A on the current board with the BQ25798EVM | whole document |
| R3' | No circular charging loop (bus -> charger -> pack -> BT boost -> bus) and no runaway. The charger may stay powered through Run only with a fail-safe Teensy-commanded hard inhibit plus a hardware comparator backstop | B.1, B.6, F.3 |
| R4 | PCB and pack survived 2026-11-04 | D (no damage repair) |
| R5 | MCU hardware watchdog is required future work; no unattended charger session until its forced-hang test passes. **r4 consequence:** a Teensy hang inside an FC window cannot survive the next purge (F.4), so **no FC-charge window, attended or not, runs before T-W-01 passes**; R1's FC charging therefore depends on R5, and this design treats the watchdog as a precondition of FC charging, not as future work | G.3, F.4, T-W-01, T-D-14 |
| R6 | FC charging only in windows between H-20 purges. A predicted purge interrupts the window so the battery is back on the bus before the dip | F.4, H.8 |
| R7 | Regen and FC charging may run concurrently (IO CSV row 31 to be amended) | F.2, F.3, D.3 |
| R8 | The BT-current trip residual (INA253 floor ~0.1 A, residual loop up to ~0.29 A) is accepted for now | J.1 |
| R9 | The VBT->VCHG keep-alive is last resort. Design without it, give the test that decides it and any lower-drain alternative | B.5, H.9-H.10, H.15, T-B-09 |

**[EVAL] §0.1 rulings 1-10, verbatim (lines 35-65):**

1. **Regen harvesting AND fuel-cell charging are both hard requirements.** The core of the research is EMS strategies that
   use both. A charger that does only FC charging, or only catches the tail of regen bursts, fails. Round 1's framing of regen
   as "demonstration value" is void.
2. **Path A is strongly preferred** (the re-spin is a much larger investment), but it must be shown **fully feasible** before
   committing.
3. **R3 ("the bus never feeds the charger") is replaced by the true requirement: no adverse behaviour.** In particular: no
   circular charging loop (bus -> charger -> pack -> BT boost -> bus) and no runaway or unregulated charge current. R3 existed
   only because the Ag105 cannot be stopped from charging while powered. It may be relaxed for a replacement **only if** that
   charger has a reliable, Teensy-commanded, fail-safe way to **prevent charging while powered** (hard inhibit / Hi-Z /
   converter off, plus an input-voltage threshold). The operator **accepts the always-powered charger design:** REGEN
   (D-BC-RG, pin 30) held closed through Run so the charger is booted before braking starts; its input-voltage regulation
   threshold set between the bus maximum and the regen clamp so it draws about nothing at bus voltage and absorbs only when
   regen lifts V-MOT; the threshold moved below the bus over I2C for FC charging; with independent backstops (hard inhibit,
   a hardware comparator V-MOT > VBUS + margin gating the charger off, a firmware interlock, and the fw v37 rev 2 `J` guards
   G1-G3 plus the trip latch, ported).
4. **The PCB and battery survived the 11-13 A incident; everything runs normally.** Stage-0 damage checks are considered
   passed. A scope-armed bring-up before the first charger session remains good practice.
5. **An MCU hardware watchdog (Teensy 4.1 WDOG1 / RTWDOG) is required future work if Path A is pursued, and must be recorded
   in this feasibility study** (section 5.1).
6. **FC charging only in the windows between H-20 purges.** A predicted purge interrupts the FC-charge window, so the battery
   is back on the bus before the purge voltage dip.
7. **Regen and FC charging may run concurrently.** The IO CSV row-31 rule "REGEN off before FC_CHARGE" is to be amended
   (pending documentation change, not yet made). Mechanism, per the operator: regen lifts V-MOT above VBUS, D-BC-FC is
   reverse-biased, and the FC stops supplying the charger until V-MOT returns to bus voltage. BT_BUS is open in this mode, so
   the pack cannot form a loop.
8. **The BT-current trip residual is accepted for now:** INA253 floor about 0.1 A, residual loop up to about 0.29 A.
9. **The 1 kOhm VBT -> VCHG keep-alive resistor is a last resort only** (it would worsen the energy statistics).
10. **Assumed part for Path A: the BQ25798EVM.**

Later ruling relevant here (task context, memory `operator-ruling-fc-purge-handling`, 2026-11-08): no FC charging during or
just before a purge; preemptive share shift to battery; EMS-requested charging between purges. [BI] §0.1 applies it as OR-P
and records further rulings OR-S, OR-SC, OR-RQ, OR-I, OR-J, OR-K, OR-AC, OR-B, OR-G (isolation study only).

### 1.2 Study verdict

- **[EVAL] §0.2 (line 102), round 2:** "VERDICT: UNDETERMINED. Path A is credible but is NOT yet shown to be fully feasible."
  Per requirement: HR1 UNDETERMINED; HR2 UNDETERMINED at system level (charger side proven from datasheets); HR3 PROVEN_CALC,
  conditional on the interlock hardware; HR4 PROVEN_CALC (nominal) with readback discipline; HR5 BENCH_GATE (lines 106-112).
  Chosen part BQ25798EVM (SLUSDV2C; EVM SLUUCB5E); runner-up BQ25713EVM-017; alternate BQ25773EVM, one bought in parallel
  (lines 114-132). Rejected: MP2759, BQ24650; LTC4015 plausible but ranked below; BQ25756 cold restart 145-175 ms
  (lines 134-137). Fourteen conditions (lines 139-201). §0.3 panel P1-P12 and §0.4 critic C1-C14 left the verdict unchanged.
- **[WD] §0.2 (line 39), round 3 r6:** "On paper the design is feasible. No datasheet fact blocks it. The circular loop is
  impossible by construction in every mode, with any single fault (section F.3), except the R8 residual, which the operator
  has accepted." Not proven: twelve decisive tests (T-E-03, T-B-09, T-B-06/-10/-12, T-B-19/T-E-11, T-E-01/-12/-06, T-F-08,
  T-B-21 + T-A-01b, T-B-20, T-C-04, T-W-01, T-A-05b/T-E-13, T-F-17/T-C-09; lines 52-92).
- **[EVAL] §0.1a (lines 67-98), round-3 summary:** Path A now needs two custom PCBs (4-layer 31 x 33 mm carrier in the 22 Ag105
  holes; 2-layer 36 x 24 mm EIB), 11 EVM modifications and MB modifications; parts budget about USD 505-540 including two
  EVMs; FC charging depends on the MCU watchdog (T-W-01); regen rests on T-E-03 and TI-unpublished dynamics
  (T-B-06/-10/-12); regen-armed cruise probably needs the keep-alive (T-B-09; VCHG decays below the RT1987 UVLO in 0.17-0.78 s);
  **"The review loop did not converge"** (verified findings 53 -> 44 -> 34 -> 32 -> 24 -> 16; round 6 no blocker, nine majors
  applied; final independent audit not run, account spend limit). "Treat the design as review-round-6, not as audited."

### 1.3 Requirements HR1-HR5 ([EVAL] §1.1, lines 279-286), verbatim

| ID | Requirement | Pass condition |
|---|---|---|
| **HR1** | Regen harvesting (ruling 1) | Charger absorbs the mechanics-limited regen energy of a hard decel with the VESC not tripping: warm response within the τ budget of section 3.2; input >= 23 W at the threshold for a 3 -> 1 m/s, 12 A brake (peak 18.9 W) |
| **HR2** | FC charging (ruling 1) | Commanded charging from VBUS in an FC window, within the FC budget (governor 1.25 A, H-20 P_MAX ≈ 1.247 A bus, OC_FC 1.4 A single sample, minus aux and traction), surviving H-20 purges |
| **HR3** | No circular loop (replaces R3) | No single fault produces a sustained bus -> charger -> pack -> BT boost -> bus current; a bounded single pulse per event is acceptable |
| **HR4** | No runaway | Charge and input current bounded by a hardware ceiling plus registers; no unregulated path |
| **HR5** | Fail-safe Teensy-commanded hard inhibit | Hard inhibit (Hi-Z / converter off / charge disable) that defaults to inhibit with the Teensy unpowered, in reset, hung, or with I2C dead; no autonomous charge out of POR or from stored settings |

The board-side H1-H12 rows follow at [EVAL] lines 287-297 (H4: threshold settable 18.5-19.5 V+, FC value about 13.5-15 V,
draw <= 5-10 mA below threshold; H5: >= 1.5 A at 8.4 V, CV 8.400 V ±0.5 %; H6: abs max >= 30 V, 36 V preferred; H8: peak
<= 1.0 A inrush on the RT1987-ramped node with aux, no electrolytic; H10: <= 2 W loss; H12: charge current and input V/I
readable). Note for the custom board: H6 says ">= 30 V (36 V preferred)"; the task context sets ">= 35 V" for input-side parts.

### 1.4 Loop / runaway analysis and backstop set ([EVAL] §2, lines 363-516)

- **§2.1 Why the charger threshold cannot be the interlock:** every TI charger resets its input threshold at power-up
  (BQ25798: VBUS0 - 1.4 V, SLUSDV2C §7.3.4.4 p.27; BQ25713/20 VBUS - 1.28 V; BQ25773 3.2 V). The threshold is a soft layer,
  valid only after a host write and read-back in the current power cycle.
- **§2.2 H1 physical barrier:** bus current reaches V-MOT only through D-MT-EN, which conducts only when V-MOT < VBUS (RT1987
  DS-00 §17.6: forward regulation 35 mV, reverse comparator -50 mV, ~0.5 µs, all typical). Comparator permits only while
  V-MOT > 1.067 x VBUS. Part TLV3012B (Vos ±9 mV at VCM = V-; CMRR term 3.4-4.2 mV TODO(verify: SBOS300C) at 3.3 V; hysteresis
  2-8 mV; prop <= 4 µs at 100 mV overdrive, 15 µs allocated; output LOW when unpowered). Dividers V-MOT 499k/56.2k, VBUS
  464k/56.2k, **0.1 %**, 470 pF (24 µs matched); RH 6.49 MΩ (≈0.30 V hysteresis). Trip points at VBUS 15.9 V: permit 17.13 V
  nominal (17.33 V worst max), inhibit 16.82 V (16.62 V worst min). Guard >= 0.70 V over 15.59-19.5 V; collapses to 0.24 V
  with 1 % parts. RGN-V divider must not be reused (TL431 REF). ([WD] r1 re-trimmed: H1 ratio 1.089, R111 442 kOhm; [LOOP]
  line 156/165.)
- **§2.3 H2 and the C7 qualifier:** `H2 = FCC_net AND NOT(BTB_net OR RGN_net OR BT_ACT)`, BT_ACT = TLV3012B on the INA253 BT
  output at 19.8 mV (trip 0.11-0.29 A). INA253A1 zero-current floor up to 10 mV = 0.1 A (SLOS954A §7.5), so a 50 mA firmware
  trip is impossible; boot-measured floor + margin (~0.12 A) and a charger-side power-balance cross-check instead. Final logic:
  `GATE = (H1 AND RGN_net AND NOT FCC_net) OR H2`; `PERMIT = P5 AND GATE`; `ILIM_REL = GATE OR (CHG_QUAL AND NOT P5)`.
  Logic family SN74LVC1G08/11/27/32/04 (VIH 2.0 V / VIL 0.8 V at 3.0-3.6 V, Ioff). [WD] r1-r6 later rewrote this network for
  R6/R7 (H2c = FCC . BTB_OFF . BT_OK . FCI_OK . ((UVB . FCCEIL) + H1); heartbeat ARM_OK; OVN from BQ29200; comparators
  U115, U119-U121; [WD] §0.3 r1-8, r2-10, r6-1, r6-6).
- **§2.4 Runaway bound:** high-side sense internal to the BQ25798 (SLUSDV2C Table 5-1 pp.4-5); mode-switched ILIM_HIZ divider
  regen 1.44-1.72 A / FC 0.74-0.96 A (Eq.1 p.27: ILIM = (V - 1 V)/0.8 Ω; [WD] r1 with leakage: regen 1.33-1.76 A, FC
  0.65-0.95 A, [LOOP] line 156); register bounds IINDPM, ICHG, VREG; no passive SYS -> VBUS path. Physical reverse-power
  barrier: D-BC-FC and D-BC-RG block VOUT > VIN (RT1987 §17.6, §17.4). No hardware pack-OV action on the MB (round 2);
  [WD] r6 added the BQ29200 OUT -> OVN permit term.
- **§2.5 Inhibit-latency allowance (S1-B3):** 184/194 µs at 1.25 A, 158/167 µs at 1.40 A, 117/125 µs at 1.72 A (VBUS
  15.9/16.39 V, 0.4 mF on V-MOT); **<= 115 µs** covers every row; no datasheet gives it. Criterion is a bounded pulse per event.
- **§2.6 Minimal backstop set (table, lines 470-476), verbatim layers:**

| Layer | Element | Duty |
|---|---|---|
| Hardware (carries the loop proof) | H1 V-MOT/VBUS comparator; H2 FC-window permit; C7 logic; CHG_QUAL AND NOT P5; inhibit stages biased from the charger's REGN; reverse blocking of D-BC-RG/D-BC-FC | Loop impossible with any single fault; absent logic = inhibit |
| Charger-intrinsic | Hard-inhibit pin (not register-only); high-side sense with resistor ceiling; no charge until enabled; no autonomous restart from stored settings | Runaway bound; fail-safe |
| Independent | eFuse (active current limit, fast trip) on VCHG-IN, section 4.2 | Charger power-stage FET short (no controller can open it) |
| Firmware | 1 kHz F1 cross-check (PERMIT/H1/H2 vs ADCs; needs V_rgn calibrated first); mode-transition sequencer; I_BT trip with BT_BUS LOW above the measured INA253 floor (section 2.3); FC-window power-balance cross-check; poor-source recovery; safety-register readback; ported G1-G3 + trip latch; `FAULT_SWITCH_CONFLICT` in all builds | Overcharge, stale state, detection |
| Watchdogs | MCU RTWDOG + WDOG1 (section 5.1); charger watchdog second tier only (P7) | Hung-MCU double faults |

- **§2.7 single-fault table** (lines 483-503): Teensy reset/unpowered, hang, I2C dead, comparator stuck HIGH/LOW, CHG_QUAL+P5
  both HIGH, D-BT-EN short (with/without brake), charger HS FET short (eFuse), REG0A/REG14/REG16 corruption, VINDPM reset at
  plug-in, failed-FB boost, VESC abrupt stop, D-BC-FC / D-BC-RG / D-MT-EN short, MCU WDT reset mid-burst. All land safe or
  harvest-lost except the R8 residual.
- **§2.8 firmware findings (fw v37 rev 2):** `J` session closes loop L-R by construction (retire); `FAULT_SWITCH_CONFLICT` inside
  `#if !BENCH_TEST`; State-99 drain-into-charger phases to delete; State-98 `4` toggles pin 5 unconditionally.

### 1.5 Regen dynamics and FC-charging mode ([EVAL] §3, lines 518-622)

- **§3.1 logs:** V-MOT rises 15.9 -> 21.20-21.47 V in 19-47 ms, onset within ~5 ms of `I_cmd` < 0; linear decay 14-20 V/s;
  second pulse 0.523-0.562 s later (mean 0.535 s, 8 events); VESC default `MCCONF_M_FAULT_STOP_TIME` 500 ms (vedderb/bldc
  `mcconf_default.h` line 546). Energy reaching V-MOT today 0.13-0.28 J at 0.97 mF or 0.54-1.17 J at 4 mF; board-only
  capacitance ~0.48 mF; VESC input C never measured.
- **§3.2 energy if the VESC keeps braking (-12 A rail):** 2 -> 1 m/s: 2.09 J at V-MOT, 1.81 J (215 mC) into pack, 11.1 W peak,
  0.30 s; **3 -> 1 m/s: 6.32 J, 5.55 J (661 mC), 18.9 W peak, 0.58 s**; 2 -> 1 m/s at 5 A: 2.17 J, 1.83 J, 0.53 s.
  Capture is a cliff: 96-99 % if the charger reaches current before V-MOT reaches ~21.35 V, else 6-40 %. Cold start
  (65-170 ms) never works. **τ_warm <= 4 ms (10-90 % <= 9 ms), <= 2 ms if C is board-only**; ~20 ms if 4 mF confirmed; ~60 ms if
  the VESC cut-off is raised. τ table at Vth 19 V, 2.5 A: 3 -> 1 m/s 12 A: 2.5 / **4.5** / 10 / 23 ms at 0.49 / 0.97 / 2 / 4 mF.
  H1 releases at 17.1-17.8 V, 1.8-11.6 ms head start (fastest rise 287 V/s). Levers: raise VESC cut-off to ~23-24 V (<= 23 V
  preferred: BQ25798 VBUS recommended max 24 V), add V-MOT C (~4 ms per mF; ~0.65 A extra D-MT-EN soft-start per mF).
  EMS value 0.2-0.66 C per hard decel.
- **§3.3 ceiling vs requirement:** regen ILIM 1.44-1.72 A (R21 121k / R23 100k from REGN); worst case input at the 18.62 V
  VINDPM floor 1.435 A x 0.88 x 18.62 V = **23.5 W**. ICHG 2.50 A caps input at **20.3 W at 7.4 V, 23.1 W at 8.4 V** (91 %
  efficiency, Fig 6-4 p.18 figure reading); 23 W at low SoC needs ICHG >= 2.83 A (pack datasheet). [WD] r1-10 then set the
  regen image ICHG **3.10 A** (0x0136) with capability = min(input limit, ICHG limit), H.7 (21.8 W at ICHG 3.10 A, [LOOP] line
  157); 2.50 A (0x00FA) until T-E-11/T-B-19 pass ([WD] G.1 line 2001). [WD] r5-9: ICHG upper tolerance **3.21 A** used for
  ratings (battery-side copper basis, r6-3).
- **§3.4 FC-charging mode (study values):** switches FC_REG 1, BT_REG 1, FC_BUS 1, **BT_BUS 0**, MOT_PWR 1, **REGEN 0**,
  **FC_CHARGE 1**, BT_SEQ 1; VINDPM 13.5 V (0x87; ±2.6 % -> 13.14-13.86 V); IINDPM 0.90 A standstill, in cruise
  min(0.90, 1.20 - I_aux - I_traction,filt - 0.10) A at 50 Hz, window closes below 0.30 A; ICHG 1.60 A; standstill charge
  1.31-1.58 A (bus side 0.89-1.05 A); FC ILIM 0.74-0.96 A; VREG 8.400 V -0.25/+0.65 % -> pack at termination 8.34-8.42 V;
  ITERM 200 mA. System blockers: purge collapse (bus falls ~2.57 V/ms, UV_BUS 20 ms dwell); FC budget (standstill-weighted);
  time multiplexing (row 31, since relaxed by R7); no cold FC close (70.2 µF x 12 mA/µF = 0.84 A + 0.15 A aux = 0.99 A vs
  1.0 A). [WD] supersedes: FC image VINDPM **14.5 V** (0x91), REGEN stays closed in FC windows (R7), FC windows open warm from
  REGEN ([WD] §0.3 r0 items 1-4; G.1 line 1999).

### 1.6 BQ25798 design choices ([EVAL] §4 and [WD] G.1)

**Architecture ([EVAL] §4.1):** per-burst gate ILIM_HIZ (< 0.75 V stops switching with REGN on, > 1 V resumes; SLUSDV2C
§7.3.4.3 p.27; EC p.16), EN_EXTILIM = 1 (POR value, never written in [WD] r2); static gate /CE (charging needs EN_CHG = 1 and /CE
LOW, §7.3.9.1 p.41), default drive = P5 AND NOT trip (panel P1: /CE HIGH holds BAT near 2.5 V behind D-BT-SQ, SLUSDV2C p.33);
mode-switched ILIM divider (R21 121k / R23 100k from REGN; Q3 + R_FC 158k in FC mode; [WD] r1 changed R23 to 49.9 kOhm);
CHG_QUAL releases ILIM_HIZ only during qualification with P5 LOW; D-BC-RG EN is **not** gated with H1 (tD_ON 8 ms + tON
~1.5 ms exceeds τ). EVM mods M1-M11 ([EVAL] §4.2) and EM1-EM25 ([WD] §C). eFuse requirement: active limit ~2.0-2.5 A, µs
response, latched/slow retry, >= 30 V, OV >= 24 V ([EVAL] line 703); [WD] selected **TI TPS26630RGER** (U101), OVP 23.12 V
(22.61-23.63 V), UVLO 9.99 V, R105 27.4 kOhm IMON, C102a/b/c + D107 (VBR(min) >= 36 V), D103 + C103 ([WD] §0.3 r0-6, r1-14,
r3-9, r4-10; [LOOP] P2-2, P2-4).

**Operating modes ([EVAL] §4.3):** Init/Idle 1 1 1 1 1 0 0 1, P5/QUAL 0/0, EN_CHG 0; Run cruise regen-armed 1 1 1 1 1 1 0 1,
VINDPM 19.0 V, IINDPM 1.70 A, ICHG 2.50 A; regen burst absorbing, IBUS_OCP 7-9 A (EC p.9); FC window 1 1 1 0 1 0 1 1 (round 2;
[WD] F.2 makes it 1 1 1 0 1 1 1 1 with REGEN closed, line 1408).

**Registers ([EVAL] §4.5 at 0x6B, 100 kHz; [WD] G.1 at 400 kHz with 2.7 kOhm MB pull-ups, 100 kHz fallback):**

| Reg | Value | Meaning | Source |
|---|---|---|---|
| never write | REG0A, REG16, REG09 bit 6 REG_RST, OTG regs REG0B-0D/REG47; **REG14** ([WD] r2) | - | [EVAL] line 740; [WD] line 1962 |
| 0x00 | 0x04 | VSYSMIN 3.5 V | Table 7-14 p.59 |
| 0x01:02 | 0x03 0x48 (8.400 V) in [EVAL]; **0x03 0x40 (8.320 V) interim** in [WD] r4 until T-E-13 | VREG | Table 7-15 p.60 |
| 0x03:04 | regen 2.50 A ([EVAL]) / **3.10 A 0x0136** ([WD], 2.50 A until T-E-11/T-B-19); FC 1.60 A 0x00A0 | ICHG 10 mA/LSB | Table 7-16 p.61 |
| 0x05 | regen 0xBE (19.0 V); raised 0xB6 (18.2 V, ratchet to 19.0); FC 0x87 (13.5 V, [EVAL]) / **0x91 (14.5 V, [WD])** | VINDPM, reloaded only at plug-in | Table 7-17 p.62 |
| 0x06:07 | regen 0x00AA (1.70 A); FC <= 0x005A (0.90 A, governor) | IINDPM, clamped by ILIM pin | Table 7-18 p.63 |
| 0x08 | 0x03 | VBAT_LOWV 15 % VREG; IPRECHG 120 mA | Table 7-19 p.64 |
| 0x09 | 0x25 | STOP_WD_CHG 1; ITERM 200 mA | Table 7-20 p.65 |
| 0x0E | 0x3D | timers (POR) | Table 7-24 p.69 |
| 0x0F | 0x02 (EN_CHG 0) / 0x22 armed | EN_AUTO_IBATDIS 0, EN_CHG, EN_ICO 0, EN_HIZ 0, EN_TERM 1, EN_BACKUP 0 | Table 7-25 pp.70-71 |
| 0x10 | 0x81 (kick 0x89) | VAC_OVP 0h = 26 V; watchdog 0.5 s | Table 7-26 p.72 |
| 0x11 | 0x00 | AUTO_INDET_EN 0 (reset by WD) | Table 7-27 p.73 |
| 0x12 | 0x04 | EN_OTG 0, DIS_LDO 1 | Table 7-28 p.75 |
| 0x13 | 0x01 | ACDRV off, 1.5 MHz, EN_IBUS_OCP 1 | Table 7-29 pp.76-77 |
| 0x14 | 0x16 expected, read-only verify ([WD]); [EVAL] wrote 0x16 | EN_IINDPM 1, EN_EXTILIM 1 | Table 7-30 pp.78-79 |
| 0x15 | 0xAA | EN_MPPT 0 | Table 7-31 p.80 |
| 0x18 | 0x54 | TS active | Table 7-34 p.83 |
| 0x2E-0x30 | continuous 13-bit ([WD]: whenever powered in Run) | ADC | Tables 7-55..7-57 |

**Quantitative checks ([EVAL] §4.6):** cold-path inrush 70.2 µF x 12.0 mA/µF = 0.84 A ~1.3 ms; VINDPM - bus steady max
(16.39 V) 2.23 V; - 17.2 V transient 1.42 V; - fw OV latch 17.5 V 1.12 V; - TPS61288 OVP min 18.3 V 0.32 V; H1 rise max -
VINDPM min 0.76 V; VESC cut 21.35 V - V-MOT hold max 19.48 V = 1.87 V ([WD] r3: static max 19.72 V, margin 1.63 V with
R_PATH_RG 0.12-0.19 ohm); VBUS_OVP min - design clamp max 2.9 V, to 24 V recommended max 1.7 V; FC POR bus load <= 1.11 A;
thermal FC 1.6 A x 8.4 V ~1.0 W, TJ 70-75 °C (RθJA 44.2 °C/W p.8), regen 2.1 W for <= 0.6 s; pack at
termination 8.34-8.42 V.

**Ag105 pad map for the header (from [EVAL] line 270-273 and [FB] §4.1):** CHG at (47.498, 34.544) R180, rows 25.00 mm apart,
2.54 mm pitch, outline 32.0 x 34.8 mm; VIN+ (10) = VCHG-IN; VIN- (4), VBAT- (14, 15) = GND (solid to both pours, no thermal
relief); VBAT+ (18, 19) = VCHG; SDA (8) / SCL (7) = Teensy 18/19; STAT (3) = Teensy 6; MPPTD (11) = Teensy 5; THERM (13) =
J-NTC; pins 1, 2, 5, 6, 9, 12, 16, 17, 20, 21, 22 have no copper connection.

### 1.7 Bench gates ([EVAL] §6, lines 880-962)

- **Track 0 (no purchase, week 0-1):** S0-R0 (VESC fault watch, `l_max_vin`, fault-stop time); **S0-R3** (CV load 19.0 V,
  1.3 A on V-MOT; GO if braking continues >= 0.25 s with V-MOT held at 19 V on a 2 -> 1 m/s decel; NO-GO for regen if the pulse
  still ends after 30-50 ms); S0-R1 (V-MOT C ±20 %); S0-R2 (V_rgn ratio < 1 %); S0-M3 (RT1987 turn-off, UVLO re-tD_ON); ruling
  gate (conditions 2, 3, 4). [WD] equivalents: T-E-03, T-E-04, T-E-05b, T-E-06.
- **Track 1 (EVM bench, weeks 1-3):** S1-0 (as-booted ICHG, WD_STAT, PG_STAT), **S1-0b** (first qualification at VIN 16/21 V
  with VAC_OVP POR 7 V), S1-B0 (/CE >= 2.9 V not armed; ILIM_HIZ <= 0.2 V held; 1.92-2.08 V released), **S1-B1** (inhibited
  <= 1 mA, released <= 5 mA at 15.9/18.5 V, VINDPM 19 V), **S1-B2** (VINDPM retention over 1000 cycles + 12 V dip), **S1-B3**
  (inhibit latency <= 115 µs), **S1-B4** (warm step 18.5 -> 20.0 V, τ63 <= 4 ms, 10-90 % <= 9 ms, real RT1987 in D-BT-SQ
  position, no BATOVP cycling), **S1-B4r** (release at 17.5 V, ramp 285 V/s, switching <= 4.5 ms), B4b (current-limited source,
  regulates 19.0 ± 0.3 V), **S1-B5** (charger WD; EN_CHG reads 0 after expiry), **S1-B6** (ILIM sampled once or continuously;
  IINDPM accuracy at 19 V within -12 %), **S1-PS** (poor-source retry < 1 s, never 7 min), **S1-B7** (BAT 2.5 V hold with /CE
  HIGH), S1-B8 (30 min 1.6 A, TDIE < 100 °C), S1-B9 (ADC vs shunt), **S1-C** (CV 8.34-8.42 V, termination), S1-773 (BQ25773
  comparison).
- **Tracks 2-5:** S2-a..d (sequences, H1 sweep at real ramp rates, H2 + C7 truth table, F1 <= 6 ms); S3-a..f (reset, hang,
  SDA LOW, comparator faults, carrier 3V3 removed, REG05 14 V while armed); **S3-g** (brake in FC window with D-BT-EN shorted;
  stray register writes); **S3-h** (VCHG-IN short downstream of the eFuse; charger input-to-output short); **S3-i** (CHG_QUAL
  and P5 both HIGH); S3-W/M6 (MCU WDT, unattended-only gate); S4-a (boot self-test incl. INA253 floor); S4-b (cruise 60 s, IBAT
  0 ± 20 mA); **S4-c** (warm FC transitions, I_fc peak < 1.2 A, TRCB re-close within 1.0 A); **S4-n** (switching noise, zero
  spurious permit transitions); **S4-H20** (window on a running H-20); **S5-a** (2 -> 1 m/s, >= 80 % of S0-R3 energy), **S5-b**
  (3 -> 1 m/s 12 A, IBAT <= 2.5 A, no rise to 21.35 V), S5-c (abrupt stop), S5-d (drive cycle).
- **Exit criteria (line 939):** S0-R3, ruling gate, S1-0b, S1-B1, S1-B2, S1-B3, S1-B4/B4r, S1-B5, S1-B6, S1-B7, S1-C, S1-PS,
  S3-all (incl. S3-g/h/i), S4-c, S4-n, S4-H20, S5-a, S5-b. S3-W gates unattended operation only.
- **§6.4 results that force the re-spin (lines 946-955):** (1) S0-R3 fails and `l_max_vin` <= 23 V does not restore braking;
  (2) warm response exceeds τ on BQ25798, BQ25773 and BQ25713; (3) inhibit latency fails on every candidate; (4) no
  purge-tolerant FC topology; (5) **hand-wired carrier shows coupled-glitch permit releases, ground-shift faults or unreliable
  rework in S3**; (6) D-BT-SQ reversed/damaged; (7) EMS needs concurrency and row 31 kept (since relaxed by R7).
- [WD] §I replaces these with 112 test IDs ([EVAL] line 70); the decisive set is in §1.2 above.

---

## 2. Path A and Path B: definitions, effort, cost, schedule, risk

### 2.1 Path A

- **Definition ([EVAL] line 8):** "desolder the Ag105 and wire an off-the-shelf charger EVM to its pads on the current board
  (operator: strongly preferred, but must be shown fully feasible before committing)". Round 3 ([EVAL] §0.1a): BQ25798EVM
  off-board on nylon standoffs (>= 20 mm from the LM1084 side, leads <= 0.30 m, [EVAL] line 672) + carrier CR (4-layer
  31 x 33 mm in the 22 holes: TPS26630 eFuse + bulk + TVS, seven TLV3012B, permit logic incl. BQ29200 pack-OV term, two
  monostables) + EIB (2-layer 36 x 24 mm: open-drain /CE and ILIM_HIZ drivers, FC-leg ceiling switch) + 11 EVM modifications
  (EM1-EM25 in [WD] §C) + MB modifications ([WD] §D, PM0-PM11).
- **Cost:** round 2: EVMs USD 511.90 (2 x BQ25798EVM USD 156.45 + 1 x BQ25773EVM USD 199.00), parts ~USD 40-70, optional
  carrier PCB ~USD 30, **total ≈ USD 580-620** (USD 740-780 with the optional BQ25713EVM USD 156.45) ([EVAL] lines 973-991; TI
  store 2026-11-05). Round 3: **parts budget about USD 505-540 including two EVMs** ([EVAL] line 84). TI stock 2026-11-05:
  BQ25798EVM 162, BQ25773EVM 95, BQ25713EVM-017 38. [PB] (round 1) cited BQ25713EVM ~€179 (DigiKey NL).
- **Schedule (round 2, one engineer, [EVAL] lines 995-1010):** Track 0 week 1; EVM mods + carrier week 2; Track 1 week 3;
  firmware 2-3 weeks (weeks 2-5); MCU WDT +1 week; S2-S3 week 5-6; S4 week 6; S4-H20 + S5 **≈ week 6-7**; HIL/EMS 7-10 days +
  campaign after S5. FC-charging data around week 4-6. Firmware/HIL/EMS **about 30-45 eng-days** (UNVERIFIED; round 1 had
  20-29). Round 3 adds a PCB design-and-fab cycle for CR + EIB ([EVAL] line 85-86); no revised schedule is recorded.
- **Risk:** [PB] §5.1: risk to the only working board "Real" (desolder of a 22-pin DIL with GND pads solid to both pours, D-BT-SQ,
  C-D11, C-D12 underneath; possibly incident-damaged; mitigate by cutting pins and removing one at a time); bring-up risk
  "Low to moderate". [EVAL] §6.4 item 5: the hand-wired carrier itself is a re-spin trigger. [EVAL] condition 13: do not
  desolder the Ag105 until the stage-1 EVM gates pass.

### 2.2 Path B

- **Definition:** re-spin the board ([EVAL] line 10; §6.4). Two options from [PB] (round-1 estimates "not re-derived in round 2",
  [EVAL] line 957):
  - **B1 minimal re-spin:** new charger IC on the board with its own BATFET, BAT on the pack, all bodges folded in (D2-D13,
    D15-D18, D22), BQ29200 OUT -> hardware charge inhibit, >= 35 V input caps, D-BT-SQ option (a) recommended ([PB] §2.2-2.3).
    Optional **B1+**: hardware REGEN gate comparator, charger kept powered behind a hardware hard-off, regen buffer C (not
    recommended) ([PB] §2.4). Under the round-2 rulings B1 must also carry the H1/H2 interlock on-board and a purge-tolerant
    FC path ([EVAL] line 961).
  - **B2 bidirectional pack-to-bus converter:** replaces BT TPS61288 and the charger; FC stage current-commanded; retires the
    droop-share platform ([PB] §3).
- **Effort / cost / schedule / risk:**

| Item | B1 | B2 | Source |
|---|---|---|---|
| Hardware design | ~2-4 engineer-weeks (ESTIMATE) | ~8-14 engineer-weeks, likely 2 spins, 50 % chance of a rev-2 fix | [PB] §2.6, §3.3 |
| Cash | ~USD 1-2k for 5 boards (BOM USD 149.66/board for 111 parts; Ag105 line USD 14.70) | ~USD 2-4k over 1-2 spins (+USD 30-80/board over B1) | [PB] §2.6, §3.3; [EVAL] line 961-962 |
| Firmware/HIL/EMS | ~23-37 eng-days | ~63-95 eng-days + campaigns | [PB] §2.6, §3.3; [EVAL] table line 959 |
| Schedule | design 3-4 wk -> fab 2-3 wk -> bring-up 2-6 wk = **~8-13 weeks to first safe charge** ([EVAL] table: weeks 8-14) | ~5-9 months integrated, ~4-6 months to first bench charge | [PB] §2.6, §3.3 |
| Bring-up risk | Moderate (one new switching stage; copy the EVM layout; bring up charger block first) | High (two new power stages, redesigned motor-node path) | [PB] §2.6, §5.1 |
| Board risk | None to the existing board; creates spares | None to old board | [PB] §5.1 |

- [PB] §0 recommendation (round 1): run in sequence, Path A as the de-risking prototype of the B1 charger; B2 as a research
  decision. [PB] §5.2 rated the BQ25798 as "Compact and integrated (good for a <= 32 x 35 mm carrier), but its 24 V operating /
  26 V VAC_OVP is tight against the regen overshoot".
- Note: [PB] §4's regen arithmetic (every burst a cold start, onset >= 62-70 ms) predates ruling 3 (always-powered charger)
  and is superseded for Path A by [EVAL] §3.2.

---

## 3. Review findings, rounds 1-6 (every key)

Source: [LOOP] round tables (lines 95-149, 172-217, 236-271, 291-324, 345-370, 389-406); dispositions that differ from the
finding are in [WD] §L (lines 2551-2699). **No finding was rejected in any round** ([WD] L.2-L.6 closing lines); all 203 keys
were verified real. Severity is as recorded in [LOOP].

**Tags** (root cause): (a) off-board EVM / 0.3 m leads / lead length; (b) EIB / ribbon / far-end readback; (c) EVM
modifications; (d) carrier logic or carrier PCB ("d-mech" = carrier layout/mechanics); (e) BQ25798 IC behaviour; (f)
firmware; (g) MB / system; doc = documentation only.

**CB column** (this digest's assessment, not from the sources): effect of one custom board carrying the BQ25798 + power stage,
the CR logic and the EIB drivers in the 22 holes. **Y** = root cause removed (the EVM, its leads, its mods, the EIB or the
ribbon no longer exist); **P** = eased (shorter paths, more area, own part values), but the analysis or test must be redone
for the new layout; **N** = persists (IC, firmware, MB/system, carrier logic, or header/MB-interface mechanics that the
custom board inherits). The MB taps (V-MOT, VBUS, EN nets, INA253 BT, BQ29200 OUT, CO-5V, Teensy readback pins) are still
flying leads from the custom board, so tap-related keys stay N.

| Rnd | # | Key | Severity | Issue (one line) | Disposition | Root-cause tag | CB |
|---|---|---|---|---|---|---|---|
| 1 | 1 | `preempt-fcc-btb-overlap` | major | Purge pre-emption could hold FC_CHARGE and BT_BUS EN HIGH together | Applied: P5, FCC+FCCEIL, VINDPM read-back, then BT_BUS; invariant I-9 | f,g | N |
| 1 | 2 | `eib-wireoff-releases-converter` | major | A lifted EIB/EVM lead released ILIM_HIZ (converter on) | Applied (alt.): two series switches Q203 feed + Q201 hold, JP14 out, far-end ILIM sense | b,c | Y |
| 1 | 3 | `qual-window-single-barrier` | major | Run-entry QUAL window rested on one barrier | Applied: EN_CHG 0 written first; U111 LVC1G123 one-shot cleared by P5N | d,e | N |
| 1 | 4 | `p5-static-arm-hang` | major | Static P5 arm survives a Teensy hang | Applied: pin-21 heartbeat into monostable U113; CE_DRV and ILIM_REL ANDed with ARM_OK | d,f | N |
| 1 | 5 | `permit-tap-failsafe-and-en-threshold` | minor | Permit taps on MB EN nets not fail-safe; LVC threshold vs RT1987 EN band | Applied via comparator U115 + pull-ups/downs | d,g | N |
| 1 | 6 | `comparator-divider-open-faults` | minor | Open V-MOT/VBUS divider tap faults | Applied: H1q gated by UVB, BAV199 clamps, FR-08d | d,g | N |
| 1 | 7 | `uvb-blocks-raised-regen` | minor | Bus-sag term UVB cut a raised regen burst | Applied: H2c = ... ((UVB . FCCEIL) + H1) | d | N |
| 1 | 8 | `btok-sense-wire-open` | minor | Open BT_OK sense wire undefined | Applied: 1 MOhm open-input bias | d,g | N |
| 1 | 9 | `regen-capability-ichg-bound` | major | Regen capability bounded by ICHG, not only the input limit | Applied: H.7 as min(); ICHG 3.10 A | e | N |
| 1 | 10 | `btbus-reclose-inrush-unquantified` | major (uncert.) | BT_BUS re-close transient from an FC-only bus unquantified | Applied: H.6 transient, lever 3(i)/(ii) ruling, FR-26, T-F-08 | g | N |
| 1 | 11 | `efuse-out-schottky-missing` | major | eFuse OUT goes negative at a hard short (lead inductance) | Applied: D103 3 A Schottky + C103 1 uF; T-C-04 | a,d | P |
| 1 | 12 | `ocfc-margin-traction-transient-fc-window` | major (uncert.) | OC_FC margin vs traction transients in FC window | Applied: admission bound, setpoint hold, peak-hold governor; U117 DNP | f,g | N |
| 1 | 13 | `ilim-band-leakage-omitted` | minor | ILIM_HIZ pin leakage omitted from the clamp band | Applied (alt.): EVM R23 -> 49.9 kOhm too | e,c | P |
| 1 | 14 | `evm-c43-25v-vbus-ldo` | minor | EVM C43 (25 V) on the JP30 VBUS LDO path | Applied: JP30 removed | c | Y |
| 1 | 15 | `btok-kelvin-wrong-reference` | minor (uncert.) | BT_OK comparator referenced to wrong ground point | Applied: T9 to SNS-BT GND/REF1 | d,g | N |
| 1 | 16 | `run-quiescent-draw-unaccounted` | minor | Run quiescent draw of the charger chain not counted | Applied: H.15 line, T-B-04 | e,d | P |
| 1 | 17 | `efuse-ovp-above-bq-rating` | minor | eFuse OVP set above the BQ25798 rating | Applied: OVP 23.12 V (22.61-23.63 V), 0.1 % divider | d,e | N |
| 1 | 18 | `carrier-copper-unspecified` | minor | Carrier copper weight and pours unspecified | Applied: 2 oz, pour widths, vias (W8 later deleted) | d-mech | N |
| 1 | 19 | `btb-sense-threshold-gap` | major | BTB sensed by LVC input; gap vs RT1987 VEN_F 0.6 V | Applied: BTB_OFF comparator U115 at 0.39-0.44 V | d,g | N |
| 1 | 20 | `open-input-failsafe` | major | Every input on a removable conductor must fail safe | Applied (alt.): pull-downs on EIB inputs, BTB 1 MOhm, R143 | b,d | P |
| 1 | 21 | `readback-misses-evm-side` | major | Inhibit readbacks taken at carrier, not at the EVM pin | Applied (alt.): far-end ILIM sense U203 (pin 33), /CE sense U204; I2C on W7 | b | Y |
| 1 | 22 | `raise-latency-i2c-budget` | major | I2C latency budget for the T3 raise | Applied: FR-07 normative, 2.7 kOhm pull-ups, 400 kHz, EEPROM deferral | a,f | P |
| 1 | 23 | `latent-comparator-faults` | minor | Latent stuck comparator faults undetected | Applied: FR-08c (BT_OK vs pin 41), FR-08d | d,f | N |
| 1 | 24 | `uvb-ref-drift-margin` | minor (uncert.) | UVB reference drift margin | Applied: drift + CMRR in r3_calc; R115 104 kOhm | d | N |
| 1 | 25 | `imon-clamp-leakage` | minor (uncert.) | IMON clamp diode leakage error | Applied: D102 removed, R129 10 kOhm + C129 1 nF | d | N |
| 1 | 26 | `btok-kelvin-reference` | minor (uncert.) | Duplicate of btok-kelvin-wrong-reference (BT_OK Kelvin point) | Applied with #15 plus R143 100 ohm | d,g | N |
| 1 | 27 | `efuse-flt-unpowered-state` | minor (uncert.) | eFuse FLT level undefined when unpowered | Applied: FR-12/FR-23 ordering | d,f | N |
| 1 | 28 | `tb03-ce-pass-criterion` | minor | /CE test criterion and pull-up value | Applied: /CE >= 3.0 V; 47 kOhm pull-ups | c,e | P |
| 1 | 29 | `stale-designators-in-fixes` | minor | Stale designators | Applied | doc | N |
| 1 | 30 | `pin34-wdog1b-pad` | minor | WDOG1_B pad mux vs pin 34 | Applied: WDOG1_B on pin 20 only | f,g | N |
| 1 | 31 | `preempt-switch-conflict-latch` | major | FAULT_SWITCH_CONFLICT latch during pre-emption | Applied with #1 (FR-13) | f | N |
| 1 | 32 | `preempt-bt-trcb-conduction` | major (uncert.) | RT1987 enabled-but-blocking (TRCB) state on pre-emption | Applied: two-state analysis; T-E-12 | g | N |
| 1 | 33 | `early-purge-refusal-band` | major | Early-purge rescue refusal band | Applied: purgeRescueOk(), four outcomes | f,g | N |
| 1 | 34 | `restore-threshold-vindpm-band` | major | T4 restore threshold inside the VINDPM band | Applied: T3 level-sensitive, FR-24 deleted, guard | e,f | N |
| 1 | 35 | `regen-capability-ignores-ichg` | major (uncert.) | Duplicate of regen-capability-ichg-bound | Applied with #9; FR-25 CV derate | e | N |
| 1 | 36 | `fr08-uvb-unobservable` | major | FR-08 tripped on unobservable UVB | Applied: dangerous-direction-only FR-08 | d,f | N |
| 1 | 37 | `raise-vindpm-unload-transient` | major (uncert.) | VINDPM raise unloads V-MOT transiently | Applied: staged T3 (IINDPM, ICHG, VINDPM 18.2 V, ratchet) | e | N |
| 1 | 38 | `purge-interval-load-dependence` | minor (uncert.) | Purge interval depends on load | Applied: T-E-01 >= 20 intervals at window load | g | N |
| 1 | 39 | `fc-window-por-latches-fc-clamp` | minor (uncert.) | Charger POR in FC window latches the FC ILIM clamp | Applied: FR-30 flag + re-qualify | e | N |
| 1 | 40 | `t3-latency-blocking-i2c` | minor | Duplicate of raise-latency-i2c-budget | Applied with #22 | a,f | P |
| 1 | 41 | `t2-bt-bus-ownership` | minor | BT_BUS ownership in windows | Applied: latch owns BT_BUS | f | N |
| 1 | 42 | `telemetry-ems-gaps` | minor | Telemetry gaps for the new modes | Applied: FR-20 fields | f | N |
| 1 | 43 | `carrier-no-buildable-layout` | major | No buildable carrier layout | Applied (alt.): B.8 netlist, A.8 rules, PM0 gate | d-mech,doc | N |
| 1 | 44 | `eib-mounting-and-tp-placement` | major | EIB mounting and EVM test-point placement | Applied: fabricated EIB on chassis, per-wire lengths | b | Y |
| 1 | 45 | `stale-designators-collide-with-evm` | major | Carrier designators collide with EVM designators | Applied: renumbered 1xx/2xx | c,doc | Y |
| 1 | 46 | `evm-c43-25v-on-input` | major | EVM C43 25 V on the input | Applied with #14 | c | Y |
| 1 | 47 | `bom-mpns-incomplete` | major | BOM MPNs incomplete | Applied: every line an MPN | doc | N |
| 1 | 48 | `rb2-designator-collides-with-mb` | minor | Designator collides with MB RB2 | Applied | doc | N |
| 1 | 49 | `duplicate-em-ids` | minor | Duplicate EVM-mod IDs | Applied: EM1-EM25 | c,doc | Y |
| 1 | 50 | `tap-twisted-gnd-unterminated` | minor | Tap twisted-pair GND unterminated | Applied: T7b, T17r | g | N |
| 1 | 51 | `registry-missing-pass-fail` | minor | Registry rows without pass/fail | Applied | doc | N |
| 1 | 52 | `t1-t2-unprotected-power-taps` | minor | V-MOT/VBUS tap joints unprotected | Applied: R170/R171 10 kOhm at the joints | d,g | N |
| 1 | 53 | `doc-svg-number-mismatches` | minor | Doc/SVG number mismatches | Applied | doc | N |
| 2 | 1 | `evm-jp14-feed-joint-floating` | blocker | Removing EVM R21 left the ILIM feed joint floating | Applied: R21 0 ohm link, JP14 pin 1 removed | c | Y |
| 2 | 2 | `reg14-write-reopens-extilim` | major | A REG14 write can clear EN_EXTILIM (reset only by REG_RST) | Applied: REG14 never written; masked verify every 20 ms; latched trip | e,f | N |
| 2 | 3 | `efuse-out-schottky-missing-reopen` | major | D103 not sized for the hard short | Applied: two turn-off cases; T-C-04 survival | a,d | P |
| 2 | 4 | `w8-unfused-hot-lead` | major | Second VIN+ lead W8 unfused in Run | Applied: W8 deleted | a | Y |
| 2 | 5 | `fr08-hb-latency-false-trip` | major | FR-08 false trip from heartbeat latency | Applied: HB_dead, TW_HB_MAX/TW_QQ_MAX from T-C-10 | d,f | N |
| 2 | 6 | `eib-pin8-backpower-unpowered-outputs` | major | Unpowered EIB outputs back-powered via the pin-8 readback | Applied (alt.): CE_RB on pin 7; INPUT_PULLDOWN; EIB 3V3 on two conductors | b,g | P |
| 2 | 7 | `cr-3v3-single-tap-backpower` | major | CR 3V3 single tap back-powered by external sources | Applied (alt.): MB RSDA/RSCL 2.7 kOhm, CR pull-ups DNP | b,c,g | P |
| 2 | 8 | `pin8-encoder-net-occupancy` | major | Pin 8 still on the encoder net | Applied (alt.): pin 7 after ROS removal; T-A-01b | g | N |
| 2 | 9 | `pin8-tap-on-encoder-net` | major | Duplicate of pin8-encoder-net-occupancy | Applied (merged) | g | N |
| 2 | 10 | `preempt-drops-subh1-regen` | major | Pre-emption with P5 LOW dropped sub-H1 regen | Applied: P5 stays HIGH in pre-emption/T5/T6 | f | N |
| 2 | 11 | `preempt-p5-low-drops-brake-absorption` | minor | Duplicate (brake absorption) | Applied (merged) | f | N |
| 2 | 12 | `rescue-predicate-checked-before-tdon` | major | Rescue predicate evaluated before RT1987 tD_ON | Applied: predicate at conduction | f,g | N |
| 2 | 13 | `setpoint-hold-conduction-deadlock` | major | Setpoint hold could deadlock | Applied: readiness release, T_HOLD_MAX | f | N |
| 2 | 14 | `t2-btbus-open-without-fc-conduction` | major | T2 opened BT_BUS without a live FC | Applied: live FC survivor predicate | f,g | N |
| 2 | 15 | `warm-response-pass-criteria-inconsistent` | major | Warm-response pass criteria inconsistent | Applied: one budget; V-MOT peak <= 20.5 V | e,doc | N |
| 2 | 16 | `telemetry-ems-gaps-reopen` | major | EMS telemetry gaps (ADC mode, counters) | Applied: ADC continuous in Run; chg_q_mc/chg_e_in_mj | e,f | N |
| 2 | 17 | `window-reopen-rule-limits-fc-duty` | major | Window re-open rule limits FC duty | Applied: mid-interval re-open, single G test | f | N |
| 2 | 18 | `chg-header-strips-10-12` | major | CHG header must be 10- and 12-pin strips | Applied: TSW-110 + TSW-112 | d-mech | N |
| 2 | 19 | `carrier-no-buildable-layout-reopen` | major | Carrier still not buildable (area, tap field) | Applied: 3x8 field, SMT J101, double-sided 4-layer | d-mech | P |
| 2 | 20 | `bom-resistor-mpns-out-of-range` | major | Resistor MPNs out of range | Applied: TNPW0805; R116 10 MOhm | doc,d | N |
| 2 | 21 | `evm-tp42-is-scl` | major | EVM TP42 is SCL, not the intended node | Applied: TP41 | c | Y |
| 2 | 22 | `tc04-out-spike-criterion-unattainable` | major | Duplicate (eFuse OUT spike criterion) | Applied (merged) | a,d | P |
| 2 | 23 | `btb-pullup-backdrives-en` | minor | BTB pull-up back-drives the RT1987 EN | Applied: R119 10 MOhm | d,g | N |
| 2 | 24 | `h2c-h1-term-not-rgn-qualified` | minor | H1 term in H2c not RGN-qualified | Applied: H1R = H1 AND RGN | d | N |
| 2 | 25 | `qual-clr-edge-bypasses-gate` | minor | QUAL clear edge bypasses the gate | Applied: QQF = QQ AND FCCN | d | N |
| 2 | 26 | `ground-loops-parallel-returns` | minor | Parallel ground returns through ribbon/leads | Applied (alt.): ribbon GND via R273 10 ohm; shields at CR end | a,b | Y |
| 2 | 27 | `evm-agnd-parallel-return` | minor | EVM AGND parallel return | Applied (merged) | a,b,c | Y |
| 2 | 28 | `run-quiescent-draw-unaccounted-reopen` | minor | Run draw still under-counted (TS bias, EIB pull-ups) | Applied: 55-78 mW | e,b,d | P |
| 2 | 29 | `evm-power-shunts-unsourced` | minor | EVM power shunts JP3/JP5 unrated | Applied: soldered links | c | Y |
| 2 | 30 | `ina253-adc-offset-from-charger-return` | minor | Charger return current shifts INA253/ADC ground | Applied: T-F-04c | a,g | P |
| 2 | 31 | `t-a-04-criterion-not-datasheet` | minor | EVM cap-rating test criterion not from datasheet | Applied: SLUSDV2C 6.3 totals | c,doc | Y |
| 2 | 32 | `ilim-sense-threshold-above-hiz-vil` | minor | Far-end ILIM sense threshold above HIZ VIL | Applied: threshold 0.59-0.65 V | b | P |
| 2 | 33 | `lvc-slow-edges-reset` | minor | LVC inputs see slow edges at reset | Applied (alt.): exception + T-D-01 | d | N |
| 2 | 34 | `i2c-bus-recovery-missing` | minor | No I2C bus-clear recovery | Applied: bus clear in FR-07 | f | N |
| 2 | 35 | `csv-h2-text-omits-fciok` | minor | CSV H2 text omits FCI_OK | Applied | doc | N |
| 2 | 36 | `csv-row16-omits-fciok` | minor | Duplicate (CSV row 16) | Applied | doc | N |
| 2 | 37 | `early-purge-trigger-misattribution` | minor | Early-purge trigger misattributed | Applied: V_bus < 14.16 V or V_fc onset | f | N |
| 2 | 38 | `fc-window-budget-vs-h20-pmax` | minor | FC window budget vs H-20 P_MAX | Applied (alt.): stack-power cap in G; FR-32 | f,g | N |
| 2 | 39 | `todo-outside-registry` | minor | TODOs not tied to tests | Applied: FR-31 | doc | N |
| 2 | 40 | `evm-input-cap-figure` | minor | EVM input capacitance figure wrong | Applied: 50.4 uF | c,e | P |
| 2 | 41 | `w7-gnd-termination` | minor | I2C cable W7 GND termination | Applied: twisted triple, GND at CR end | a | Y |
| 2 | 42 | `p5-name-collision` | minor | Name P5 collides (tap hole vs logic net) | Applied: F01-F24, CHG_ARM | doc | N |
| 2 | 43 | `svg-netlist-designator-gaps` | minor | SVG/netlist designator gaps | Applied | doc | N |
| 2 | 44 | `h15-3v3-load-understated` | minor | 3V3 load understated | Applied: 1.82 mA | d | N |
| 3 | 1 | `t1-ce-check-before-regn` | major | /CE check at T1 before REGN is up | Applied (alt.): regnExpected predicate (FR-23) | e,f | N |
| 3 | 2 | `fr08-powered-predicate-ignores-regn` | major | FR-08 powered predicate ignores REGN | Applied (alt.): same predicate | e,f | N |
| 3 | 3 | `ce-sense-gating-before-regn` | major | /CE sense gating before REGN | Applied (alt.): same predicate; FR-08f merged | e,b | N |
| 3 | 4 | `ce-pullup-link-sense-divider-fails-low` | major | /CE pull-up link on EVM fails to 'LOW' sense | Applied: redundant R272 + R272b on EVM | c,b | P |
| 3 | 5 | `heartbeat-proves-loop-not-monitor` | minor | Heartbeat proves loop(), not the monitor | Applied: completion token (FR-28) | f | N |
| 3 | 6 | `btb-off-stuck-high-undetectable` | minor | BTB_OFF stuck HIGH undetectable | Applied (alt.): accepted latent; T-C-12 | d | N |
| 3 | 7 | `u203-stuck-held-latent-no-entry-test` | minor | Far-end ILIM sense U203 stuck latent | Applied: T1 step 6 pin-33 proof | b | P |
| 3 | 8 | `early-purge-sag-asserts-h1` | minor (uncert.) | Bus sag in early purge asserts H1 | Applied: T3 qualified by V_bus not falling | d,g | N |
| 3 | 9 | `t3-t4-fcceil-race` | minor | T3/T4 FCCEIL race | Applied: worker re-asserts FCCEIL LOW | f | N |
| 3 | 10 | `ina253-bt-common-cause` | minor | Dead INA253 BT channel is a common cause | Applied: FR-38 | g | N |
| 3 | 11 | `efuse-in-spike-c102-undersized` | major | eFuse IN spike with C102 undersized (up to 134 V sim) | Applied: C102a/b/c + D107 by default | d,g | N |
| 3 | 12 | `cr-bottom-over-mb-power-traces` | major | CR bottom tails over MB power copper | Applied (alt.): flush tails, SMT tap pads, polyimide | d-mech,g | N |
| 3 | 13 | `input-path-ir-drop-omitted` | major | Input-path resistance (leads, EVM R2, JP3) omitted | Applied: R_PATH_RG 0.12-0.19 ohm; warm budget 0.33/0.80 ms | a,c | P |
| 3 | 14 | `mb-vchgin-vias-current-rating` | minor (uncert.) | MB VCHG-IN vias current rating | Applied: T-F-13 | g | N |
| 3 | 15 | `t18-5v-tap-unprotected` | minor | CO-5V tap T18 unprotected | Applied: R172 at CO-5V joint | g | N |
| 3 | 16 | `btok-selftest-floor-overlap` | major | BT_OK self-test overlaps INA253 floor | Applied (alt.): split outcome; R142 select-on-test | d,g | N |
| 3 | 17 | `u203-threshold-ignores-sense-offset` | minor | U203 threshold ignores sense offset | Applied (alt.): R258 10.0 kOhm | b | P |
| 3 | 18 | `csv-pin20-reservation-missing` | minor | CSV pin 20 reservation missing | Applied | doc,f | N |
| 3 | 19 | `early-purge-fc-ridethrough-infeasible` | major | FC ride-through of an early purge infeasible | Applied: early purge = State 99 | g | N |
| 3 | 20 | `window-ignores-ems-intent-and-termination` | major | Window ignores EMS intent and termination | Applied: rule (h), chgFull latch | f | N |
| 3 | 21 | `scheduler-unlock-on-load-starves-windows` | major (uncert.) | Scheduler unlock on load starves windows | Applied: model-dependent prediction | f | N |
| 3 | 22 | `h1-asserts-on-bus-sag` | minor | H1 asserts on bus sag | Applied (merged with #8) | d | N |
| 3 | 23 | `cr-power-pad-coords-on-pin-column` | major | CR power-lead pad coordinates on the pin column | Applied (alt.): explicit pad coordinates | a,d-mech | P |
| 3 | 24 | `evm-jp13-regn-pin-stray-shunt` | major | EVM JP13 REGN pin is a stray-shunt path | Applied: R20 and JP13 pin 1 removed | c | Y |
| 3 | 25 | `j101-unkeyed-ribbon-reversal` | major | Ribbon J101 unkeyed (reversal) | Applied (alt.): keyed J101, T-C-13 | b | Y |
| 3 | 26 | `tps26630-pwp-alternate-nonexistent` | minor | TPS26630PWPR alternate does not exist | Applied: deleted | d | N |
| 3 | 27 | `todo-outside-registry-reopen` | minor | TODOs outside registry | Applied | doc | N |
| 3 | 28 | `fr08b-label-collision` | minor | FR-08b label collision | Applied: FR-33..36 | doc | N |
| 3 | 29 | `bav199-clamps-backfeed-cr-rail` | minor | BAV199 clamps back-feed the CR rail | Applied: residual stated; T-C-07 | d | N |
| 3 | 30 | `r256-c252-agnd-landing-unspecified` | minor | R256/C252 AGND landing on EVM unspecified | Applied: across JP21 | c,b | Y |
| 3 | 31 | `evm-j3-j4-live-terminals` | minor | EVM J3/J4 terminals live | Applied: desoldered or insulated | c | Y |
| 3 | 32 | `d103-fallback-contradicts-criteria` | minor | D103 fallback contradicts criteria | Applied (alt.): >= 40 V class, B340A bench-only | d | N |
| 3 | 33 | `eib-layout-unbudgeted` | minor (uncert.) | EIB layout unbudgeted | Applied: EIB 36 x 24 mm | b | Y |
| 3 | 34 | `u117-option-values-missing` | minor | U117 option values missing | Applied (alt.): values + R161 select-on-test | d | N |
| 4 | 1 | `hang-fc-window-r5-gates-r1` | major | A Teensy hang in an FC window cannot survive the next purge | Applied: FC windows gated on T-W-01; RTWDOG 50 ms | f,g | N |
| 4 | 2 | `hang-fc-window-purge-reclose-death5` | major (uncert.) | Purge under hang re-closes onto drained V-MOT (Death-5) | Applied (alt.): bench-only T-D-14 | g | N |
| 4 | 3 | `i2-vs-preempt-stepb-failure-branch` | major | I-2 vs pre-emption step-B failure branch | Applied: barrier clauses, step-D guard | f | N |
| 4 | 4 | `i4-blocks-state99-under-h1` | major | I-4 blocked State 99 under H1 | Applied (alt.): I-4(a)/(b) split | f | N |
| 4 | 5 | `fr12-idle-selftests-need-motpwr-btbus-low` | major | Idle self-tests need MOT_PWR/BT_BUS LOW | Applied (alt.): moved to busBringupTick() | f | N |
| 4 | 6 | `charger-trip-in-window-leaves-bt-bus-open` | major | Charger trip inside window leaves BT_BUS open | Applied (alt.): T10 | f | N |
| 4 | 7 | `hb-selftest-skips-ilim-leg` | minor | Heartbeat self-test skips the ILIM leg | Applied (alt.): T1 step 8b | d,f | N |
| 4 | 8 | `pin35-flt-floats-on-open-tap` | minor | eFuse FLT on pin 35 floats on an open tap | Applied (alt.): INPUT_PULLUP, R106 DNP | g,f | N |
| 4 | 9 | `eib-e1-regn-adjacent-to-ilim-feed` | minor | EIB E1 (REGN) adjacent to ILIM feed | Applied: empty pads | b | Y |
| 4 | 10 | `i2-btboff-precondition-unobservable` | minor | I-2 BTB_OFF precondition unobservable | Applied | f | N |
| 4 | 11 | `fallback2-dbtsq-disconnect-claim` | minor | Fallback-2 D-BT-SQ disconnect claim wrong | Applied: trade-off restated | g | N |
| 4 | 12 | `d107-tvs-crowbars-vmot-regen` | major | D107 TVS could crowbar V-MOT regen | Applied: VBR(min) >= 36 V; T-A-05b | d,g | N |
| 4 | 13 | `ov-batt-cv-margin-ignores-adc-error` | major | OV_BATT vs CV margin ignores ADC error | Applied (alt.): interim VREG 8.32 V; T-E-13 | e,g | N |
| 4 | 14 | `ilim-clamp-por-adc-error-omitted` | minor (uncert.) | ILIM POR ADC conversion error omitted | Applied: T-B-23 | e | N |
| 4 | 15 | `r172-0805-short-dissipation` | minor | R172 0805 burns in a short | Applied: F101 + R172 33 ohm 1206 | g,d | N |
| 4 | 16 | `cr-eib-3v3-feed-unprotected-short` | major | CR->EIB 3V3 feed unprotected against a short | Applied (alt.): R175 68 ohm, R176/R177 200 ohm | b,d | P |
| 4 | 17 | `ribbon-adjacent-short-ilimrelb-rfcoff` | minor | Adjacent ribbon short ILIM_REL_B/RFC_OFF | Applied: conductors swapped | b | Y |
| 4 | 18 | `tlv3012-ribbon-driver-short-current` | minor | TLV3012 ribbon driver short current | Applied: R264/R265 470 ohm | b | Y |
| 4 | 19 | `pin22-adc-keeper-imon-error` | minor | Pin-22 pad keeper error on IMON | Applied: INPUT_DISABLE | f,g | N |
| 4 | 20 | `fc-window-raise-ignores-governor-floor` | major | FC-window raise ignores governor floor | Applied (alt.): brake feed-forward 0.90 A (FR-41) | f,e | N |
| 4 | 21 | `purge-lock-tolerance-exceeds-tlead` | major | Purge lock tolerance exceeds T_LEAD | Applied (alt.): PURGE_EARLY_MAX 55 ms | f | N |
| 4 | 22 | `preempt-btbus-not-owned-through-purge` | major | BT_BUS not owned through the purge | Applied (alt.): FR-15b fcPurgeExposure() | f | N |
| 4 | 23 | `fr11-trips-on-concurrent-regen` | major | FR-11 trips on concurrent regen | Applied (alt.): one-sided, quiet intervals | f | N |
| 4 | 24 | `preempt-vindpm-failure-blocks-step-d` | minor | Duplicate of #3 | Applied with #3 | f | N |
| 4 | 25 | `sag-path-no-return-to-raise` | minor (uncert.) | Sag path has no return to raise | Applied: 5 ms re-entry | f | N |
| 4 | 26 | `chg-src-misattributes-subh1-regen` | minor | chg_src misattributes sub-H1 regen | Applied: split counters | f,g | N |
| 4 | 27 | `efuse-cluster-no-room-at-pad10` | major | No room for the eFuse cluster at pad 10 (31 x 33 mm CR) | Applied (alt.): U101 rotated, 1.27 mm J101 | d-mech | P |
| 4 | 28 | `svg-w5-pin6-legend-gnd` | minor | SVG W5 legend wrong | Applied | doc,b | Y |
| 4 | 29 | `bom-26awg-wire-quantity` | minor | 26 AWG wire quantity | Applied | a,doc | Y |
| 4 | 30 | `w3w4-hole-vs-18awg-silicone` | minor | W3/W4 holes too small for 18 AWG silicone | Applied: 1.5 mm holes | a | Y |
| 4 | 31 | `evm-jp3-jp5-link-pin-rating` | minor (uncert.) | EVM JP3/JP5 link pin rating | Applied (alt.): links into plated holes | c | Y |
| 4 | 32 | `pm4-header-solder-sequence-ambiguous` | minor | Header solder sequence (PM4) ambiguous | Applied: ordered PM4 | d-mech | N |
| 5 | 1 | `ff-brake-edge-clears-peakhold-on-ripple` | major | Brake feed-forward clears peak-hold on ripple | Applied (alt.): I_ff 1.0 A, ACK-gated hold | f | N |
| 5 | 2 | `preempt-deadline-outside-completion-token` | major | Pre-emption deadline outside completion token | Applied (alt.): FR-42 backstop | f | N |
| 5 | 3 | `rtwdog-50ms-vs-blocking-flash-ops` | major (uncert.) | RTWDOG 50 ms vs blocking flash ops | Applied (alt.): FR-43 gate, windowed watchdog | f | N |
| 5 | 4 | `t10-fr08b-proof-relies-on-slow-decay` | minor | T10 proof relies on slow V_chg decay | Applied: far-end ILIM held + IBUS < 0.1 A | f,e | N |
| 5 | 5 | `rt1987-ovp-otp-restart-contradiction` | minor (uncert.) | RT1987 OVP/OTP latch vs restart contradiction | Applied: FR-30/T9 restart-mode independent | g | N |
| 5 | 6 | `fallback2-pack-unfused-on-w3-and-bridge-rating` | major | Fallback-2 pack path unfused on W3; bridge rating | Applied (alt.): fused link C-D12 -> C-D11 | a,g | P |
| 5 | 7 | `rt1987-ovp-latch-vs-autorestart-contradiction` | minor (uncert.) | Duplicate of #5 | Applied with #5 | g | N |
| 5 | 8 | `imon-vchg-ground-offset-under-charge-current` | minor (uncert.) | IMON/CHG_VOLTAGE ground offset under charge current | Applied: A.6, T-F-15 | a,g | P |
| 5 | 9 | `ichg-upper-tolerance-omitted-in-ratings` | minor | ICHG upper tolerance (3.21 A) omitted from ratings | Applied: 3.21 A basis | e | N |
| 5 | 10 | `ribbon-4-5-stat-sink-abs-max` | major | Ribbon 4-5 short exceeds STAT sink abs max | Applied: R275 1 kOhm at E7 | b | Y |
| 5 | 11 | `eib-e6-e7-ce-stat-bridge` | minor | EIB E6/E7 /CE-STAT bridge risk | Applied: empty positions | b | Y |
| 5 | 12 | `gov-cmd-proxy-abs-closes-window-on-brake` | major | Governor command proxy closes window on brake | Applied (alt.): traction-only proxy | f | N |
| 5 | 13 | `ff-iindpm-step-overlaps-traction-ocfc` | major (uncert.) | FF IINDPM step overlaps traction -> OC_FC | Applied (alt.): measurement-gated ramp; T-B-24 | f,e | N |
| 5 | 14 | `flash-commit-stalls-hb-and-wdt-in-run` | major | Flash commit stalls heartbeat and watchdog in Run | Applied (alt.) with #3 | f | N |
| 5 | 15 | `purge-fc-only-ridethrough-bag-evidence` | major (uncert.) | FC-only purge ride-through vs bag evidence | Applied: battery rescue, T_LEAD from P(fail|load) | g | N |
| 5 | 16 | `efuse-cluster-no-room-at-pad10-reopen` | major | eFuse cluster still no room at pad 10 | Applied (alt.): courtyard-checked table | d-mech | P |
| 5 | 17 | `pm4-header-solder-sequence-ambiguous-reopen` | major | PM4 sequence still ambiguous (W1-W4 trim, heights) | Applied: PM4 step 2b | d-mech,a | P |
| 5 | 18 | `ribbon-adjacent-short-stat-cedrv` | major | Duplicate of #10 (STAT/CE_DRV short) | Applied (alt.): R275 | b | Y |
| 5 | 19 | `j101-mated-socket-envelope` | minor (uncert.) | J101 mated socket envelope | Applied: dry fit T-A-06 | b | Y |
| 5 | 20 | `evm-jp17-stray-shunt` | minor | EVM JP17 stray shunt | Applied: JP17 pin 2 removed | c | Y |
| 5 | 21 | `b8-netlist-omits-cr-holes-pads` | minor | B.8 netlist omits CR holes/pads | Applied (alt.); BAV199 pinning TODO(verify) | doc,d | N |
| 5 | 22 | `bom-polyimide-adhesive-unspecified` | minor | Polyimide sheet/adhesive unspecified | Applied (alt.) | d-mech | N |
| 5 | 23 | `cr-end-strain-relief-anchor` | minor | CR-end lead strain relief anchor | Applied: adhesive + chassis tie | a | P |
| 5 | 24 | `layout-table-dimension-gaps` | minor | Layout table dimension gaps | Applied | doc | N |
| 6 | 1 | `vreg-corruption-no-fixed-pack-ovp` | major | VREG corruption: no fixed pack-OV backstop | Applied (alt.): BQ29200 OUT -> U123 -> OVN -> ARM_OK' | d,e,g | N |
| 6 | 2 | `dbtsq-short-unfused-pack-on-vchg` | minor | D-BT-SQ short puts unfused pack on VCHG | Applied (alt.): FR-48 detection | g | N |
| 6 | 3 | `cr-and-mb-battery-path-copper-sized-below-ichg` | major (uncert.; verifier minor) | CR/MB battery-path copper below ICHG | Applied: 3.21 A basis, T-A-06c, T-F-16 | d-mech,g | N |
| 6 | 4 | `tc04-in-spike-criterion-omits-mb-vchgin-ratings` | major (uncert.) | T-C-04 omits MB VCHG-IN ratings | Applied: three-point scope | d,g | N |
| 6 | 5 | `imon-bypass-cap-against-datasheet` | minor | IMON bypass cap forbidden by SLVSE94G | Applied: C105 DNP | d | N |
| 6 | 6 | `fcc-rgn-lvc-threshold-vs-rt1987-en-band` | major | FCC/RGN LVC threshold vs RT1987 EN band | Applied (alt.): comparators U119/U120/U121 | d,g | N |
| 6 | 7 | `pin38-39-adc-overvoltage-on-vmot-excursion` | minor (uncert.) | Pins 38/39 over-range on V-MOT excursion | Applied (alt.): FR-49 | g | N |
| 6 | 8 | `loop-budget-5ms-breaks-1ms-tick-deadlines` | major | 5 ms loop budget breaks 1 ms deadlines | Applied: FR-45 timer domain | f | N |
| 6 | 9 | `purge-fc-only-ridethrough-bag-evidence-reopen` | major | Rescue predicate floor not supported by bags | Applied: SAG_FLOOR; rescue compiled out | f,g | N |
| 6 | 10 | `chg-src-misattributes-subh1-regen-reopen` | major | chg_src still misattributes sub-H1 regen | Applied: braking gate, learned baseline | f | N |
| 6 | 11 | `ff-headroom-admission-contradicts-single-g-test` | major | FF headroom admission contradicts single G test | Applied (Option A) | f | N |
| 6 | 12 | `ff-reversal-hold-unattainable-at-100khz` | minor | Reversal hold unattainable at 100 kHz I2C | Applied: ACK completion; 1.0/1.5 ms | f,a | P |
| 6 | 13 | `cr-coordinate-convention-mirror-ambiguity` | major | CR coordinate convention / mirror ambiguity | Applied: pin_identity_check.py, chamfer | d-mech | N |
| 6 | 14 | `eib-e-lead-max-lengths-geometrically-infeasible` | minor | EIB E-lead maxima geometrically infeasible | Applied (alt.): re-ordered row | b,a | Y |
| 6 | 15 | `t-a-05-stale-j101-region-dims` | minor | T-A-05 stale J101 region dims | Applied | b,doc | Y |
| 6 | 16 | `a6-w2-not-beside-star-pads` | minor | W2 GND lead not beside star pads | Applied: L1 GND pour rule | a | Y |

Totals: 203 finding keys (rounds 1-6). CB = Y: 35, P: 29, N: 139.
- Round 1: 53 keys; Y 7, P 7, N 39.
- Round 2: 44 keys; Y 8, P 9, N 27.
- Round 3: 34 keys; Y 5, P 5, N 24.
- Round 4: 32 keys; Y 7, P 2, N 23.
- Round 5: 24 keys; Y 5, P 5, N 14.
- Round 6: 16 keys; Y 3, P 1, N 12.

Tag occurrences (a key may carry several tags): a 21, b 28, c 21, d 47, d-mech 13, doc 24, e 25, f 61, g 53.

Blocker/major keys by CB: blocker/Y 1, major/N 66, major/P 16, major/Y 11.

### 3.1 What the table says for a single custom board

- Of 203 keys, the custom board removes the root cause of **35 (Y)** and eases **29 (P)**; **139 (N)** persist. Of the 1
  blocker and 93 majors: blocker 1 Y; majors 11 Y, 16 P, 66 N (generated counts above).
- The **Y** set is almost entirely the EVM-mod, EIB/ribbon and lead keys: the round-2 blocker `evm-jp14-feed-joint-floating`,
  `eib-wireoff-releases-converter`, `readback-misses-evm-side`, every ribbon-short key (`ribbon-*`, `tlv3012-ribbon-*`,
  `j101-*`), every `evm-*` key, `w8-unfused-hot-lead`, `w7-gnd-termination`, `w3w4-hole-vs-18awg-silicone`,
  `ground-loops-parallel-returns` / `evm-agnd-parallel-return`, the EIB E-pad keys.
- The **P** set carries over as layout work: eFuse OUT/IN transients (`efuse-out-schottky-missing*`; the OUT side no longer
  drives 0.3 m of lead), input-path resistance (`input-path-ir-drop-omitted`: R_PATH_RG 0.12-0.19 ohm included W1/W2, EVM
  R2 and JP3), the I2C budget at 400 kHz (`raise-latency-i2c-budget`, `ff-reversal-hold-unattainable-at-100khz`), area
  (`efuse-cluster-no-room-at-pad10*`, relieved by the sideways extension), ILIM leakage and part values
  (`ilim-band-leakage-omitted`), the far-end readback thresholds (still needed if the inhibit pins are read back), and the
  charge-return ground offset at the MB (`ina253-adc-offset-from-charger-return`, `imon-vchg-ground-offset-*`).
- The **N** set is the loop proof, the purge/pre-emption firmware (61 f-tag occurrences), the MB/system facts (53 g-tag),
  the BQ25798 behaviour unknowns (25 e-tag: REG14/EN_EXTILIM, REGN timing, VINDPM reload, ILIM POR sampling, ICHG/VREG
  margins), and the header/MB-interface mechanics (`chg-header-strips-10-12`, `cr-bottom-over-mb-power-traces`,
  `cr-coordinate-convention-mirror-ambiguity`, `pm4-header-solder-sequence-ambiguous`, `cr-and-mb-battery-path-copper-*`),
  which a board in the same 22 holes inherits unchanged.
- The CB judgement is this digest's; it should be re-checked by whoever writes the custom-board design.

### 3.2 Self-review passes before round 1 ([LOOP] lines 13-86, r0)

Pass 1 (P1-1..P1-8, safety: selector dwell 250 ms vs 100 ms lead; pre-emption in a raised burst; POR in cruise latches 100 mA
clamp; governor vs selector escape; raise/restore dither; no defect in P1-6..P1-8), Pass 2 (P2-1..P2-8, electrical: RC filters
violate LVC 10 ns/V input transition (SCES364J etc.); IMON could overdrive pin 22; UVB, eFuse UVLO and keep-alive values
re-solved; P2-6..P2-8 no defect), Pass 3 (P3-1..P3-7, integration: designator collisions with the EVM BOM, FR-12 phantom
readback, `chargerHasPower()` semantics, Teensy reset pad state unknown, untested uncertainties, EVM JP7 on micro-USB, SVG
routing). Of these, P2-1 (LVC input edge rate behind EIB RC filters), P3-1 (EVM designator collisions) and P3-6 (EVM JP7) are
EVM/EIB-specific; the rest persist for a custom board.

---

## 4. Gate D-2 and the other mechanical unknowns

### 4.1 Gate D-2 (battery-isolation study)

- **Definition ([DD] §15.2 line 3461), verbatim:** "| D-2 | Ag105 module standoff and cut-gap feasibility | Standoff at least
  1 mm stub + 1 mm gap + the solder-joint height (record the value); after M1/M2, gap insulation at least 10 MOhm at 50 V
  (TODO(calibrate)) | Module carrier (revision 2 section 7.1 step 3) |"
- **[BI] Table 1 (line 116):** goal (a) "the Ag105 is kept" is Met by design with "buildability BENCH (gate D-2: module standoff
  and cut gap)". **[BI] §0.3 condition 3 (line 246):** "The board gates must pass: D-2 (the Ag105 standoff admits the pin
  cuts), ...". **[BI] §4.3 (line 785):** "D-2 (Ag105 standoff and cut gap; NO-GO falls back to a module carrier)".
- **Original wording ([C1] line 890):** "| D-2 | Ag105 module standoff | Solderable stub of at least 1 mm, or the carrier
  fallback chosen | Rework step 3 |". Rework step 3 ([C1] §7.1 line 789-792): "Measure the Ag105 module standoff (gap between
  the module body and the board). If no stub of at least 1 mm can be soldered on pins 10, 14 and 15 after a cut, use the
  fallback: cut every module pin and remove the pins one by one (incident.md section (d), Ag105 pads), then mount the module
  on a carrier with pins 10, 14 and 15 brought out by flying leads and the other pins returned to their pads. The carrier is
  a design-detail item."
- **Modification M1 ([DD] line 934):** cut pins 14/15 flush with the top of the board-side barrel; >= 1 mm air gap between
  module-side stub and barrel with Kapton and an epoxy barrier; 0.5 mm2 flying lead VBATN_X. Related: F36 cut-gap bridge row
  ([DD] line 2592); C-4 repeats the D-2 gap insulation after the first drive ([DD] line 3501).
- **Status:** the Ag105 standoff height (module body to board) is **unmeasured** in every source read; no source gives the
  Ag105 pin length or body thickness ([FB] §4 and `facts_ag105.md` carry no mechanical dimension). TODO(measure: Ag105
  standoff, pin length below body, body height above board, on the vehicle board).

### 4.2 Other mechanical facts and unknowns relevant to a board in the 22 holes

- **Footprint ([FB] §4.1, lines 133-158):** through-hole DIL, Silvertel package `AG105`, 22 pads, **1.1 mm drill, square pads,
  25 mm row spacing**, 2.54 mm pitch; element origin (47.498, 34.544) R180; PnP centroid (33.50, 50.51); pad column x 46.0
  (pins 1-10) and x 21.0 (pins 11-22). Pad annulus ~1.65 mm for 1.1 mm drill (computed, UNCONFIRMED against Gerbers, [FB] §1
  item 5). Board 2-layer, 1.6608 mm thick, 1 oz design rule (ordered weight TODO(verify: fabrication order)); GND solid pour
  both layers, `thermals="no"`, so VIN-/VBAT- pads are solid to both pours ([FB] §1).
- **Removal risk ([FB] §4.3; [PB] §5.1):** desoldering a module with solid-connected GND pads on a 1.66 mm board is a lifted-pad
  and barrel-damage risk; recommended method is to cut the module pins and remove them one at a time. Parts under the module
  footprint: D-BT-SQ (29.7, 50.0), C-D11 (26.2, 50.3), C-D12 (34.3, 50.0), C-DC11 (34.0, 52.3), C-DC12 (27.9, 52.6); all
  <= 1.10 mm tall ([WD] A.7, line 465 and 497-498).
- **Header used by the CR ([WD] r2-15, A.7):** TSW-110 + TSW-112 strips (10- and 12-pin), 2.54 mm body clears the parts under
  the footprint with >= 1.4-1.5 mm air; CR bottom tails flush-cut <= 0.5 mm; bottom parts passives only <= 1.0 mm, outside the MB
  power-copper shadow + 1 mm; 0.125 mm polyimide sheet on the MB; bottom keep-out x 24.5-36.0, y 48.5-53.5 mm. Header pin
  current rating: VBAT+ and GND pins >= 2.0 A each on a 3.21 A basis ([WD] r6-3). Header heights for the mated pair are recorded
  in PM4 step 2b ([WD] r5-10) and are TODO(measure).
- **CR outline ([WD] A.7):** x 17.70-48.70, y 34.14-67.14 mm, inside the CHG silkscreen 32.0 x 34.8 mm; 1.0 mm chamfer at the
  pin-11 corner; overhang allowed only at low-y (over C4A/B-BT, 1210, 1.35 mm) or high-y (over OP-FC, SOIC ~1.75 mm,
  UNVERIFIED), **never on the J-NTC/J-BL side or over LM1084/CO-5V; T-A-06 measures the heights**.
- **Neighbours ([WD] A.7 line 509; task context):** CO-5V 0.1 mm right; LM1084 1.8 mm right, 4.83 mm tall (runs hot);
  J-NTC/J-BL left, terminal blocks 0.8-0.9 mm from the outline ([WD] L.2, line 2588); J-BL is a TB005-762-03BE
  3-pole 7.62 mm block, J-BT TB005-762-02BE ([FB] §2.1). The isolation study adds gate **JBL** (J-BL position-3 clamp screw
  removable; [DD] §15.2) and removes J-BL position 3 (the second pack-negative bond) in its design only.
- **Vibration / strain relief ([WD] r5-10, r5-23):** adhesive strain relief + chassis tie within 30 mm with a pull check for
  CR-end leads; [DD] C-4 post-drive inspection of every flying-lead joint. No vibration specification exists in the sources.
- **Unknown heights to measure before an overhang design (none found in any source read):** Ag105 standoff and body height
  (D-2); LM1084 heat-sink/tab clearance and temperature at the footprint edge (TODO(measure)); OP-FC height (UNVERIFIED);
  mated J101-class socket height (only relevant if a ribbon remains); the seated height of the TSW strips on the MB and the
  resulting board-to-MB gap (PM4 step 2b).
