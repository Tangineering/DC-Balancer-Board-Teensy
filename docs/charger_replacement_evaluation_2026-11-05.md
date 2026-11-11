# Charger replacement: feasibility study, round 2 (2026-11-05)

**Scope.** This is the single authoritative decision document for replacing the Silvertel Ag105 (BOM `CHG`) on board rev
20260622. Round 2 (this revision) re-runs the evaluation under the operator's 2026-11-05 rulings (section 0.1) with the
candidate primaries actually read. It supersedes round 1 (same file, earlier revision of 2026-11-05) wherever they disagree;
round-1 content that is still valid is kept and marked. It also still supersedes `docs/bq25713_charger_replacement_2026-11-04.md`.

- **Path A:** desolder the Ag105 and wire an off-the-shelf charger EVM to its pads on the current board (operator: strongly
  preferred, but must be shown fully feasible before committing).
- **Path B:** re-spin the board (kept as the alternate, section 6.3).

**Evidence base.**
- **Board side (primary, local):** schematic/board files, BOM, IO CSV, fw v37 rev 2, Ag105 / RT1987 / TPS61288 / BQ29200
  datasheets, `docs/boost-bringup-debug.md` (2026-11-04), `logs/ML0227.BLG`, the 9 BLG logs and the RegenTest_v2 rosbag used
  by the regen analysis, `docs/fw37_planning_2026-11-04.md`.
- **Candidate side: primaries read this round** (TI, ADI, MPS documents fetched; literature numbers in section 9). Every
  candidate number below is cited to literature number + page/section/table. Numbers read off a datasheet *figure* are
  labelled "figure reading, typical". A value no primary gives is marked **BENCH** or **TODO(verify: source)**. Search
  snippets and recollection are not used as evidence in this revision.
- **Working material:** `docs/reviews/charger_eval_2026-11-05/round2/` (loop analysis, regen dynamics, nine dossiers, two
  complete designs, calculation scripts, figures). The 27 adversarial reviews (three lenses per dossier) and the final
  three-reviewer panel are summarized in sections 0.3 and 1.3; their raw text was not preserved as files.

**Status of the hardware.** Nothing has been ordered, desoldered or changed. fw v37 rev 2 stays on the bench board
(`AG105_VBATN_ISOLATED 0`: no regen charging; `J` hardened with G1-G3 and the trip latch). The operator reports the PCB and
battery survived the 2026-11-04 11-13 A incident and everything runs normally (ruling 4). Only this file and
`docs/reviews/charger_eval_2026-11-05/` were modified.

---

## 0. Status, rulings and verdict

### 0.1 Operator rulings (2026-11-05; these supersede round 1 where they conflict)

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

Rulings added later on 2026-11-05 (round 3, the BQ25798EVM wiring design):

6. **FC charging only in the windows between H-20 purges.** A predicted purge interrupts the FC-charge window, so the battery
   is back on the bus before the purge voltage dip.
7. **Regen and FC charging may run concurrently.** The IO CSV row-31 rule "REGEN off before FC_CHARGE" is to be amended
   (pending documentation change, not yet made). Mechanism, per the operator: regen lifts V-MOT above VBUS, D-BC-FC is
   reverse-biased, and the FC stops supplying the charger until V-MOT returns to bus voltage. BT_BUS is open in this mode, so
   the pack cannot form a loop.
8. **The BT-current trip residual is accepted for now:** INA253 floor about 0.1 A, residual loop up to about 0.29 A.
9. **The 1 kOhm VBT -> VCHG keep-alive resistor is a last resort only** (it would worsen the energy statistics).
10. **Assumed part for Path A: the BQ25798EVM.**

### 0.1a Round 3: the BQ25798EVM wiring design (2026-11-05/06)

The full design is in `docs/charger_bq25798_wiring_design_2026-11-05.md`, with its SVGs, calculations and review log in
`docs/reviews/charger_eval_2026-11-05/round3/`. Its section I is the operator test registry: 112 test IDs in bench order,
each with a pass/fail criterion and the design change if it fails.

What it means for the Path A vs Path B comparison (orchestrator summary, 2026-11-06):

- **Path A is no longer "wire an EVM to the Ag105 pads".** The loop-safe, fail-safe design needs **two small custom PCBs**:
  - a 4-layer, 31 x 33 mm carrier that plugs into the 22 Ag105 holes and carries:
    - the TPS26630 eFuse with its input bulk and TVS;
    - seven TLV3012B comparators (H1, the FC permit terms, FCC/RGN level sensing);
    - the permit logic, including the BQ29200 pack-OV term;
    - two heartbeat/qualification monostables;
  - a 2-layer, 36 x 24 mm EVM interface board, holding the open-drain drivers for /CE and ILIM_HIZ and the FC-leg ceiling
    switch.
  
  Plus 11 EVM modifications and the motherboard modifications. Parts budget about USD 505-540 including two EVMs. This is
  still far smaller than a board re-spin (no power stage, no boost, no layout of the main board), but it is a PCB design-and-
  fab cycle, not a wiring job.
- **FC charging depends on the MCU hardware watchdog.** If the Teensy hangs inside an FC window, the heartbeat stops the
  charger, but BT_BUS stays open, and the next purge collapses the FC-only bus. The design therefore makes the watchdog's
  forced-hang test (T-W-01) a precondition of any FC window, not future work. Regen does not depend on it.
- **Regen still rests on T-E-03** (does the VESC keep braking with V-MOT held at 19 V?) and on charger dynamics that TI does
  not publish (T-B-06/-10/-12).
- **Regen-armed cruise probably needs the keep-alive** (T-B-09 decides it). In cruise, VCHG decays below the RT1987 UVLO in
  0.17-0.78 s. The design carries a Run-gated keep-alive that draws nothing when parked, as a do-not-populate option
  consistent with ruling 9.
- **The review loop did not converge.** Six rounds were run, each with five lenses and every serious finding independently
  verified. Verified findings per round fell 53 -> 44 -> 34 -> 32 -> 24 -> 16; round 6 had no blocker but nine majors, all
  applied. The planned final independent audit was not run (account spend limit). **Treat the design as review-round-6, not
  as audited.** Run another review round and the audit before ordering the carrier PCB.

**Round 4 (2026-11-10, design r7).** The carrier may now extend sideways past the 31 x 33 mm footprint; the EVM stays the power stage.
The record is `docs/reviews/charger_eval_2026-11-05/round4/review_loop.md`.

- The carrier grows two tabs (tab X toward the Teensy, tab Y on +y), still 4-layer, with two bonded feet (FT1, FT2). The EVM and the
  EIB stay off the carrier, on one plate beside the motherboard. The tap field moves to tab X, which shortens the 20 tap wires by
  about 31 %.
- W1/W2 stay at a fixed 0.30 m: a shorter route raises the hard-short spike to within about 1 V of the D107 breakdown.
- The operator ruled on 2026-11-10 that there is no height limit for the motherboard and its PCBs. The Ag105 envelope is no longer a gate.
- Review round 7 verified 60 findings (no blocker, 10 major), all applied. The final independent audit, which round 3 skipped, then
  found 13 (no blocker, 3 major, 10 minor; ledger `docs/reviews/charger-design/`). The audit fixes are not yet applied.
- Parts budget about USD 520-630 including two EVMs. Before ordering: apply the audit fixes, take the operator measurements MS1-MS8,
  and run the KiCad capture.

### 0.2 Feasibility verdict

**VERDICT: UNDETERMINED. Path A is credible but is NOT yet shown to be fully feasible.** No datasheet fact found in round 2
makes Path A impossible, and the loop/runaway requirement is met by construction with the hardware interlock (section 2).
But both hard requirements still rest on numbers that no primary document gives:

| Requirement | Status | Why |
|---|---|---|
| HR1 Regen harvesting | **UNDETERMINED** | Capture is a cliff: 96-99 % if the charger reaches current within about 4 ms of V-MOT crossing its threshold (at the HIL-nominal 0.97 mF on V-MOT), else 6-40 %. No TI/ADI/MPS datasheet specifies inhibit-exit latency, warm response or VINDPM loop bandwidth. On this rig the VESC currently **stops regenerating at about 21.35 V within 19-47 ms**; whether braking continues when V-MOT is held at 19 V is unmeasured (M-R3). **Input capability (critic round):** the single 1.15-1.35 A ILIM ceiling of the first draft gave only 21.4 W at the bottom of tolerance, below the HR1 23 W pass condition; the mode-switched ILIM divider (section 4.1) gives >= 23.5 W including the IINDPM regulation tolerance. The charge-side ICHG 2.50 A cap then limits input to about 20.3 W at a 7.4 V pack and 23.1 W at 8.4 V (91 % efficiency, figure reading): above the 18.9 W peak of the defining 3 -> 1 m/s brake, but meeting 23 W at low SoC needs ICHG >= 2.83 A, which waits on the pack datasheet (section 8.1 item 6). Section 3 |
| HR2 FC charging | **UNDETERMINED at system level** (charger side proven from datasheets) | An FC window needs BT_BUS LOW, so the bus is FC-only; the H-20 purges to about 1 V, the bus collapses and UV_BUS latches (bench, 2026-10-28; fw v35 v33b refuses windows on a running stack). Traction + aux + charger also share the 1.25 A governor ceiling, the 1.247 A H-20 P_MAX and the 1.4 A single-sample OC_FC latch. Both need an operator ruling or design work, not a different charger. Section 3.4 |
| HR3 No circular loop | **PROVEN_CALC, conditional** on the interlock hardware and the listed fixes | H1 compares V-MOT with VBUS directly across D-MT-EN, which conducts only when V-MOT <= VBUS (RT1987 DS-00 §17.6). The critic round closed a firmware-only path (CHG_QUAL with P5 HIGH released ILIM_HIZ with no hardware barrier) by gating CHG_QUAL with NOT P5 in hardware (section 2.3). **Residual for an operator ruling:** in an FC window with D-BT-EN shorted, a sustained loop below the BT_ACT trip (0.11-0.29 A) is not seen by the INA253 BT channel, whose zero-current output floor can be up to 10 mV = 0.1 A (SLOS954A §7.5); the proposed charger-side power-balance cross-check (section 2.3) closes it only if its bench accuracy is good enough (S1-B9). Section 2 |
| HR4 No runaway | **PROVEN_CALC (nominal)** with readback discipline | Hardware ILIM ceiling, now mode-switched (regen 1.44-1.72 A, FC 0.74-0.96 A, so the FC bound holds after a charger POR without relying on ICHG), plus register bounds; the ceiling's ADC-read accuracy is unspecified. Section 2.4 |
| HR5 Fail-safe, Teensy-commanded hard inhibit | **BENCH_GATE** | Hardware inhibit pins exist on every TI finalist; stock EVMs are NOT fail-safe until modified; MCU watchdog is required future work |

**Chosen part (Path A): TI BQ25798EVM** (BQ25798, SLUSDV2C; EVM SLUUCB5E), mounted off-board on leads to the Ag105 pads, built
per section 4. Reasons:
1. Its input-voltage threshold VINDPM is rewritten **only at adapter plug-in** and "is not reset by the REG_RST and the
   WATCHDOG" (SLUSDV2C Table 7-17, p.62; §7.3.4.4 p.27). For the BQ25713 the equivalent retention across Hi-Z exit is
   undocumented and, if it fails, disqualifying (runner-up gate B3).
2. The open question all three reviews raised (does the ILIM_HIZ hard-off survive EN_EXTILIM = 0?) is **designed out**:
   EN_EXTILIM stays at its POR value 1 and a line `CHG_QUAL` releases ILIM_HIZ only during input qualification (hardware-gated
   with NOT P5 after the critic round), so the resistor ceiling holds in every mode. The ceiling is mode-switched by FCC_net
   (regen 1.44-1.72 A, FC 0.74-0.96 A; section 4.1); whether the pin is re-read after qualification is bench gate S1-B6.
3. Two hardware inhibit pins (/CE, ILIM_HIZ < 0.75 V stops switching with REGN on, SLUSDV2C §7.3.4.3 p.27), 22 V VINDPM range,
   1 mA / 1 mV I2C telemetry, VBUS_OVP 25.2 V minimum, and the best stock (162 EVMs at the TI store, 2026-11-05).

**Runner-up: TI BQ25713EVM-017** (complete design in `round2/design_BQ25713.md`: REGN-biased ILIM_HIZ hold-down,
mode-switched ILIM 1.80 A regen / 0.71 A FC, PTM bits on a never-write list with readback). It ranks second because SLUSD83C
does not say whether a host-written VINDPM survives a Hi-Z exit (gate B3), and because its VINDPM ceiling is 19.52 V.
**Alternate: TI BQ25773EVM** (VINDPM 3.2-27 V, intrinsically fail-safe POR with CHARGE_CURRENT 0 and VINDPM fixed at 3.2 V,
FRC_CONV_OFF comparator with 1 µs deglitch, 45 V abs max). **One BQ25773EVM is bought in parallel for stage 1** (panel
recommendation, section 0.3) because the decisive unknowns (inhibit latency, warm response) are shared by every TI part and
measuring two mechanisms at once avoids a serial month.

**Rejected:** MP2759 (NOT_FEASIBLE: no telemetry, VLIM off-threshold shares the regulation pin, no per-burst hard inhibit),
BQ24650 (no runtime current control or telemetry, 1.5 s re-enable). LTC4015 is plausible but has no host watchdog, a 2-4 s
battery detection and unverified availability. BQ25756 restarts cold (about 145-175 ms) on every hard stop and needs at least
80 µF of input capacitance. BQ25720/BQ25731 add nothing over the BQ25713/BQ25798 here (section 1.3).

**Conditions on the verdict (all must be met before Path A is called fully feasible):**

1. **Stage 0 first, no purchase needed:** M-R0 (VESC fault watch + read VESC `l_max_vin`, fault-stop time, fault log), M-R3
   (constant-voltage electronic load at 19 V, 1.3 A limit, on V-MOT during a step decel), M-R1 (V-MOT capacitance), M-R2
   (scope-calibrate V_rgn near 21 V). **M-R3 decides regen for every candidate.**
2. **Operator ruling on the FC-window topology** (purge tolerance): (a) BT hot standby with a BT_ACTIVE current permit
   (relaxes the BT_BUS-off rule; needs a new H2 definition and a new sub-threshold detector, section 2.6), (b) bus hold-up
   capacitance (about 7.5 mF for 0.15 A over 200 ms at <= 4 V sag; inrush consequences), or (c) FC windows synchronised to the
   purge schedule. Without one, FC charging on a running stack fails with any charger.
3. **Operator ruling on brakes inside FC windows:** the FC -> regen transition takes about 11-40 ms while regen onset is about
   5 ms after `I_cmd` goes negative. Options: hold the negative VESC command <= 15 ms until the transition completes; restrict
   FC windows to standstill/coast (recommended for bring-up); or allow a combined REGEN + FC_CHARGE mode with BT_BUS LOW
   (loop-free by the loop analysis §5, forbidden today by IO CSV row 31).
4. **Operator ruling on the D-BT-SQ disposition** (new after the panel, section 0.3 item P1): (i) M8 1 kΩ keep-alive VBT -> VCHG
   plus /CE driven from P5 (static) with ILIM_HIZ as the per-burst gate; (ii) D-BT-SQ bridged plus an independent fuse;
   (iii) /CE on PERMIT only if bench S1-B7 shows the BAT pin is not held at 2.5 V. M8 is a **proposal**, not a ruling
   (about 1.2-1.7 mA permanent pack drain).
5. **FC-window input-current governor:** IINDPM set at run time from the live I_fc margin, under a **hardware FC-mode ceiling
   that stays safe after a charger POR**: the mode-switched ILIM_HIZ divider (section 4.1; FC 0.74-0.96 A, so the bus load
   after a POR at standstill is <= 0.96 + 0.15 A aux = 1.11 A, below the 1.247 A H-20 P_MAX, the 1.20 A firmware arm drop and
   the 1.4 A OC_FC latch, without relying on the ICHG default, which conflicts between SLUSDV2C (1 A) and SLUUCB5E (2 A)).
   Expected FC charge 1.31-1.58 A at standstill (1.50 A at the nominal ceiling), less in cruise; H5's 1.5 A is met at the
   nominal ceiling only. EMS models use these figures.
6. **Interlock hardware before REGEN may be held closed through Run:** TLV3012B H1 comparator with new 0.1 % dividers (the
   RGN-V/TL431 divider must not be reused), the H2 FC-window permit, and the **C7-qualified** 74LVC1G network
   `PERMIT = P5 AND [(H1 AND RGN AND NOT FCC) OR (FCC AND NOT(RGN OR BTB OR BTA))]` as the sole driver of the charger inhibit
   pins, with **`ILIM_REL = GATE OR (CHG_QUAL AND NOT P5)`** so no firmware state can release ILIM_HIZ with the charger armed
   outside GATE (critic round; two extra gates, 1G04 + 1G08). No push-pull comparator output wire-ORed with a GPIO. Inhibit
   pull-ups biased from the charger's own rails (REGN), so absent logic means inhibit. Mode-switched ILIM divider (third
   resistor switched by FCC_net).
7. **Independent overcurrent cut on VCHG-IN, specified and bench-tested** (a shorted charger high-side FET is a bus-to-pack
   path no controller-level inhibit can open; RT1987 current limiting is disabled after tON, DS-00 §17.5): an eFuse with active
   current limit and fast trip, sized so a VCHG-IN fault clears before the TPS61288 boosts or the OC_FC / UV_BUS latches are
   stressed (section 4.2), and injection gate S3-h.
8. **Firmware trips:** the INA253 A1's zero-current output can sit up to **10 mV above ground = 0.1 A** (Swing to GND,
   VGND + 1 mV typ / + 10 mV max, plus I_OS ±15 mA max; SLOS954A §7.5, `references/Datasheets/INA253A1IPWR.pdf`), so the
   round-1 "I_BT > 50 mA" trip is **not achievable**. Instead: measure the BT-channel zero-current floor on this board at every
   boot (S4-a) and trip on I_BT above floor + margin (>= about 0.12 A with the datasheet maximum floor) for > 20 ms while
   BT_BUS is commanded LOW; **plus a charger-side power-balance cross-check in FC windows** (G2 style: IBUS·VBUS from the
   BQ25798 ADC plus modelled aux must match I_fc·V_bus; a loop shows as a mismatch whatever the INA253 floor), with its
   threshold set from S1-B9. If neither reaches below the BT_ACT trip, the residual (a bounded loop below 0.29 A in an FC
   window with D-BT-EN shorted) goes to the operator for a ruling. Also: 1 kHz cross-check of PERMIT/H1/H2 against the ADCs;
   continuous readback of the safety registers; VINDPM/IINDPM rewritten on every mode transition; poor-source recovery (PG_STAT
   still 0 about 300 ms after REGEN or FCC closes, or POORSRC_FLAG set -> P5 LOW, forced retry, harvest-lost flag; the charger
   otherwise waits 7 minutes, SLUSDV2C §7.3.4.2 p.27, §7.3.13.1.3 p.51); `FAULT_SWITCH_CONFLICT` enabled in every build; `J`
   guards and trip latch ported; the bus-fed `J` session retired; State-99 drain-into-charger phases removed.
9. **EVM mods M1-M7, M9-M11 and board C-D8/C-D10 -> >= 35 V** (section 4.2), including R42 (/CE pull-up) re-biased from REGN.
10. **No cold D-BC-FC close** (0.99 A vs a 1.0 A budget). FC windows open only onto a VCHG-IN node pre-charged from the regen
    path, or fit 100 nF CSS on D-BC-RG/D-BC-FC (same rework class as bodge B3; 0.645 V/ms, about 0.15 A), recorded as a
    never-rotated bodge.
11. **IO CSV amended first**, then pinmap audit, then the CLAUDE.md bodge record; telemetry v5 through the protocol-bump
    procedure with the Pi bridge in lockstep; HIL plant charger model and EMS charger economics re-derived before any EMS
    campaign uses the new charger.
12. **MCU hardware watchdog, REQUIRED FUTURE WORK** (ruling 5; spec in section 5.1). No unattended charger session until bench
    gate M6/S3-W passes (also run once during a brake). S3-W gates **unattended operation only**; it is not a feasibility exit
    criterion, as ruling 5 frames it.
13. **Do not desolder the Ag105 until the stage-1 EVM bench gates pass** on a bench rig.
14. **Exit-criteria gates pass** (section 6.3, extended in the critic round): S0-R3, ruling gate, S1-0b (VAC_OVP POR 7 V first
    qualification), S1-B1 (draw at bus voltage within 5 mA, the operator's "draws about nothing" condition), S1-B2 (VINDPM
    retention, chosen-part reason 1), S1-B3 (recomputed latency allowance), S1-B4/B4r, S1-B5, S1-B6 (ILIM sampled once or
    continuously, P6), S1-B7, S1-C (CV and termination, the HR4 overcharge bound), S1-PS (poor-source recovery), S3-all incl.
    S3-h/S3-i, S4-c (warm FC transitions, no OC_FC / UV_BUS, part of HR2), S4-n (switching noise), S4-H20, S5-a and S5-b (the
    3 -> 1 m/s 12 A brake that defines the HR1 pass condition).

### 0.3 Panel objections and how they are resolved

The final panel (three independent reviewers, after the verdict was drafted) refuted neither the UNDETERMINED verdict nor
the BQ25798 choice. Each raised design defects. Every one is either fixed in this document or carried as an explicit gate.

| # | Objection (panel) | Evidence re-checked | Resolution in this study |
|---|---|---|---|
| P1 | **/CE held HIGH through cruise holds BAT near 2.5 V** with D-BT-SQ blocking: "Charge disabled by CE pin ... the charger keeps the BAT pin voltage at low-level, steady-state voltage, close to 2.5V" | SLUSDV2C p.33 (power path, "no battery attached ... or open pack protector", item 1): confirmed verbatim | S1-B7 is re-weighted from "possible" to **expected failure** for the /CE-per-burst scheme. 2.5 V is below the RT1987 VIN UVLO (3.0-3.35 V rising, DS-00 p.7), so every burst could pay tD_ON 8 ms. The M8 keep-alive would be fought (about 6 mA from the pack). **Design change (section 4.1):** the carrier carries a 0 Ω link selecting /CE drive: **default = P5 (static arm: /CE LOW only while armed and the trip latch is clear)**, ILIM_HIZ = the per-burst hardware gate (unambiguous HIZ with EN_EXTILIM = 1, §7.3.4.3 p.27). /CE-on-PERMIT is used only if S1-B7 proves no BAT hold. D-BT-SQ disposition is condition 4 |
| P2 | **BATOVP triangular cycling** when BAT capacitance < 200 µF and D-BT-SQ has not yet conducted: "The BAT pin follows the charge profile but ends with a BATOVP fault ... triangular waveforms" | SLUSDV2C p.33 item 2: confirmed. RT1987 DS-00 gives no forward-recovery time from TRCB | S1-B4/B4r must run **with a real RT1987 in the D-BT-SQ position** and VCHG below VBT at release, logging BATOVP_FLAG and CHG_STAT. Keeping VCHG warm (M8, or bridging D-BT-SQ) is the mitigation; EN_AUTO_IBATDIS = 0 already in the static image |
| P3 | **The chosen design omits the C7 qualifier**: design_BQ25798 §3.3 builds GATE = H1 OR H2. In an FC window a brake raises H1 and grants PERMIT, bypassing H2's ¬BTB/BT_ACT terms; with D-BT-EN shorted that is a 0.3-0.6 s L-F loop | Confirmed against `round2/design_BQ25798.md` §3.1/§3.3 | **Fixed:** section 4.1 requires the C7 network (H1 leg ANDed with RGN AND NOT FCC; one extra 74LVC1G gate, as in design_BQ25713). A correction banner was added to the copied design record. S3 failure injection adds "brake during FC window with D-BT-EN shorted" |
| P4 | **/CE pull-up R42 goes to the EVM PULLUP LDO, not REGN**; "CE pin must be pulled HIGH or LOW, do not leave floating" | SLUUCB5E Table 1-3 (JP30, R42/PULLUP); SLUSDV2C pin table | **Fixed:** mod M2b re-biases /CE pull-up from REGN (REGN 4.8-5.2 V, /CE abs max 6 V, SLUSDV2C §6.1 p.7) |
| P5 | **VAC_OVP POR is 7 V**, not 26 V: the EVM guide says "increase the VAC_OVP from 7 V default ... REG10b[5:4]" | SLUUCB5E §2.4.3 step 6 (line confirmed); SLUSDV2C REG10 is self-contradictory (0h default vs POR 11b) | Static image already writes VAC_OVP = 0h (26 V, REG10 = 0x81). Added bench step S1-0b: first power-up with VAC1 = VCHG-IN at 16-21 V and VAC_OVP at its POR value must still qualify and switch (VAC_OVP acts on ACDRV, §7.3.13.1.1, which is grounded in M5). M5 also ties VAC2 to VBUS (SLUSDV2C §7.3.5.2) |
| P6 | **ILIM_HIZ may be sampled only at qualification**: a re-qualification while PERMIT holds the pin LOW clamps IINDPM to 100 mA for the rest of the Run | SLUSDV2C §7.3.4.3 p.27 vs pin table p.5 disagree | Firmware reads REG19 ICO_ILIM and PG/VBUS_PRESENT flags every poll, raises a harvest-lost flag, and re-qualifies via CHG_QUAL in Idle. Bench step added to S1-B6 (once vs continuous sampling). Safe failure direction (no current) |
| P7 | **Charger watchdog contradictory**: STOP_WD_CHG shown "R-0h" in the figure but RW in Table 7-20; Table 7-25 lists EN_CHG as reset by WATCHDOG to 1. Also (critic round): Table 7-15 lists VREG as reset by REG_RST only, but the §7.3.2 text after Table 7-2 (p.25) says a watchdog expiry returns ICHG, VSYSMIN and VREG to 1 A / 7 V / 8.4 V | SLUSDV2C p.25, p.60, p.65, p.70 | The charger watchdog is **not cited as protection** until S1-B5 reads back EN_CHG (and VREG, ICHG) after expiry. This makes the MCU watchdog more load-bearing (section 5.1) |
| P8 | **HR4 ceiling labelled PROVEN_DATASHEET is ideal arithmetic** (no ILIM ADC accuracy; IINDPM accuracy only at VBUS 9 V) | SLUSDV2C Eq.1 p.27; EC p.12 | Relabelled **PROVEN_CALC (nominal)**; REG19 readback is the check |
| P9 | **M8 is assumed by the sequences** (IC pack-powered in Idle, image verified before REGEN closes, AUTO_INDET_EN = 0 retained) | design_BQ25798 §4/§5.1 | Section 4.5 gives the **no-M8 sequence** (image written after PG_STAT at every Run entry, D+/D- skipped only after the write; AUTO_INDET_EN is reset by WATCHDOG, Table 7-27 p.73) |
| P10 | **Option (a) BT hot standby re-opens the sub-threshold loop**: H2 demands ¬BTB, and the firmware I_BT trip is keyed on BT_BUS commanded LOW | loop analysis §9 (BT_ACT trips at 0.11-0.29 A) | Condition 2 now states (a) needs a new H2 and a hysteretic/latched BT_ACT near the measured INA253 offset before it can be offered under ruling 3 |
| P11 | **BQ25773 is intrinsically fail-safe at POR**; buy one in parallel rather than holding it as a serial alternate | SLUSEK7 Table 7-3 p.32 (CHARGE_CURRENT 0, EN_AUTO_CHG 0), REG0x08 p.66 (VINDPM POR 3.2 V) | Adopted: section 7 buys 2 x BQ25798EVM + 1 x BQ25773EVM |
| P12 | **Split the plan so FC-charging data does not wait for the regen carrier** | - | Adopted: section 6 runs an FC-path track (H2 + governor + purge ruling) ahead of the regen track (H1 + warm response) |

Net effect: the verdict stands as UNDETERMINED, the chosen part stands, and the conditions grew by four items (C7 network,
D-BT-SQ ruling, R42 re-bias, VAC_OVP first-power check).

### 0.4 Critic round (2026-11-05, after the panel)

A further critic found that the verdict holds and raised 14 fixes. Each was re-checked against the local primaries before it was
applied. Recalculations are appended to `round2/calc/comp_calc.py` (critic-fix block).

| # | Fix | Disposition |
|---|---|---|
| C1 | Exit criteria omitted S1-0b, S1-B1, S1-B2, S1-B6, S1-C, S4-c, S5-b | **Applied** (condition 14, section 6.3); S3-W stays an unattended-operation gate |
| C2 | Single ILIM ceiling misses HR1 23 W (21.4 W) and leaves the FC bound after a POR on a conflicting ICHG default | **Applied**: mode-switched divider, regen 1.44-1.72 A / FC 0.74-0.96 A (sections 3.3, 3.4, 4.1, 4.6). ICHG conflict confirmed: SLUSDV2C Table 7-2 p.25 and Table 7-16 p.61 say 1 A, and its revision history records "Corrected REG0x03 default charge current to 1A" (Rev A -> B, Jan 2023); SLUUCB5E Table 1-3 (JP24, "2 A charging current", rev July 2022) predates that correction. POR detection now uses WD_STAT (HIGH in default mode, SLUSDV2C §7.4.1 p.55), PG/VBUS_PRESENT flags and the full masked verify, not "ICHG = 1 A". New residual: ICHG 2.50 A caps input at 20.3 W at a 7.4 V pack (HR1 row) |
| C3 | CHG_QUAL with P5 HIGH releases ILIM_HIZ below the bus with no hardware barrier (loop L-R) | **Applied**: `ILIM_REL = GATE OR (CHG_QUAL AND NOT P5)`; new section 2.7 row; injection S3-i. Confirmed that EN_CHG resets to 1 (SLUSDV2C Table 7-25), so a charger POR plus this firmware fault would charge |
| C4 | Firmware I_BT > 50 mA trip unachievable (INA253 swing to GND 10 mV max = 0.1 A) | **Applied**: SLOS954A §7.5 confirmed; claim corrected, boot-time floor measurement, charger-side power-balance cross-check, residual stated for a ruling. Also noted: BT_ACT's zero-current false-trip margin is only 0.8 mV worst case (min trip 10.8 mV vs floor 10 mV), failing in the safe direction (harvest lost) |
| C5 | S1-B3 latency budget carried from the earlier 17.0 V H1 | **Applied**: recomputed with final dividers, CMRR, VFWD 35 mV, 24 µs RC lag, 15 µs comparator, 20 µs gate RC. Allowance 184 / 194 µs at 1.25 A, 158 / 167 µs at 1.40 A, 117 / 125 µs at the 1.72 A regen ceiling (VBUS 15.9 / 16.39 V, 0.4 mF) |
| C6 | 7-minute poor-source lockout missing | **Applied** (SLUSDV2C §7.3.4.2 p.27, §7.3.13.1.3 p.51 confirmed): firmware recovery rule, gate S1-PS, HIL model item |
| C7 | VAC2 build instruction inconsistent | **Applied**: keep JP4 installed (VAC2 tied to VBUS, SLUSDV2C Table 5-1 p.5, §7.3.5.2), insulate or remove the J2 block; design_BQ25798 banner corrected |
| C8 | VCHG-IN fuse unspecified, untested | **Applied**: eFuse requirement (section 4.2), S3-h injection. Part not selected (no eFuse primary in the library): TODO(verify) |
| C9 | No switching-noise bench check | **Applied**: gate S4-n |
| C10 | Missing single-fault rows (D-BC-FC / D-BC-RG / D-MT-EN shorted; WDT reset mid-brake) | **Applied** (section 2.7); S3-W also run during a brake |
| C11 | H1 offset under-counted | **Applied in part**: CMRR term added (3.4-4.2 mV at 54 dB; SBOS300C §6.9 specifies CMRR only at VS = 5.5 V, so 3.3 V is TODO(verify)). **Rejected in part**: the 2-8 mV internal hysteresis was already in the comp_calc.py worst case (`hint` loop). Slow-ramp tPD noted (15 µs allocated, S2-b) |
| C12 | Small numerics | **Applied**: 2.32 A (not 2.37 A) at 8.4 V; BQ29200 delay 2.0-4.0 s (6-12 s/µF, 0-60 °C, SLUSA52C p.5, capacitor tolerance excluded); VREG watchdog-reset conflict noted at P7. **Corrected differently**: H1 rise max - VINDPM min is **0.76 V** worst case by recomputation (worst rise max 17.86 V at 16.39 V bus), not the critic's 0.63 V (17.99 V not reproduced) |
| C13 | Reverse-power barriers not stated as physical; RT1987 TRCB restart without soft-start | **Applied** (RT1987 DS-00 §17.4 Table 1, §17.6 confirmed): section 2.4 barrier, S4-c re-close scope, typical-only labels |
| C14 | INA253 cited as a fetch; pack datasheet missing from section 8.2 | **Applied** |

The verdict is unchanged: **UNDETERMINED**, BQ25798EVM chosen. The critic round adds no showstopper. It adds two hardware items
(the NOT-P5 gate and the mode-switched divider), one hardware specification (the eFuse), and two items for operator rulings: the
sub-0.29 A FC-window loop residual (HR3 row) and the ICHG value that the pack allows (HR1 row).

---

## 1. Requirements and candidate status

### 1.0 Background (round 1, still valid)

- **Incident 2026-11-04 (`J` session, ML0227):** charger fed from the bus through D-MT-EN + D-BC-RG; 1 s linear ramp to about
  11 A bus-side (~170 W), Ag105 reg 0x06 reading 0.011-0.033 A; bench FC supply dropped out, BT boost 16.5 A, bus 6.84 V in
  ~4 ms. **Mechanism (UNCONFIRMED by direct measurement):** the Ag105 senses current in Bat- (Ag105 DS V1.1 Fig. 1 p.3); on
  this board pack negative = PCB GND (operator-confirmed by design), so the shunt is paralleled and the module had no working
  output-current limit; estimated 11-13 A into the pack (4.6-5x its 2.5 A setting). Refuted alternatives: D-BT-SQ reversed
  (the .brd shows VIN on VCHG), Ag105 internal short, RT1987 limiting (its SCP works only during soft-start, DS-00 §17.5).
- **What any swap must provide:** input return and battery return on the same copper, with high-side (BAT+) or input-side
  current sense, and a **hardware** current ceiling (not a register default).
- **What a swap does not fix:** the bus can still reach the charger through D-MT-EN + D-BC-RG with V-MOT at bus level (now
  handled by the H1/H2 interlock, section 2); there is no hardware overcharge action (BQ29200 OUT goes to the orphan net
  `BAL-NOK`; VPROTECT 4.35 V/cell = 8.70 V pack after 2.0-4.0 s with CBLD 0.33 µF at 6-12 s/µF, 0-60 °C, capacitor tolerance excluded, SLUSA52C p.5; ~3.0 s nominal); D-BT-SQ hides the pack from
  the charger; Death-5 hot-plug class; pack-negative double bond at J-BT pin 2 and J-BL pin 3.
- **Pads** (CHG at (47.498, 34.544) mm, R180; rows 25.00 mm apart, 2.54 mm pitch; outline 32.0 x 34.8 mm; full table in
  `spec.md`): VIN+ (10) = VCHG-IN (C-D8, C-D10 10 µF/25 V; R1-CHG 78.7k / R2-CHG 10k -> pin 38); VIN- (4), VBAT- (14, 15) =
  GND; VBAT+ (18, 19) = VCHG (C-D11, D-BT-SQ VIN); SDA (8) / SCL (7) = Teensy 18/19 with 10 kΩ to 3V3; STAT (3) = Teensy 6
  (`INPUT`, no pull); MPPTD (11) = Teensy 5; THERM (13) = J-NTC. Spare Teensy pins: 10, 16, 17, 20-23, 33, 34 (CSV first).

### 1.1 Requirements

The board-side envelope of round 1 section 2.2 is kept except where noted. R3 is **superseded** by HR3-HR5.

| ID | Requirement | Pass condition |
|---|---|---|
| **HR1** | Regen harvesting (ruling 1) | Charger absorbs the mechanics-limited regen energy of a hard decel with the VESC not tripping: warm response within the τ budget of section 3.2; input >= 23 W at the threshold for a 3 -> 1 m/s, 12 A brake (peak 18.9 W) |
| **HR2** | FC charging (ruling 1) | Commanded charging from VBUS in an FC window, within the FC budget (governor 1.25 A, H-20 P_MAX ≈ 1.247 A bus, OC_FC 1.4 A single sample, minus aux and traction), surviving H-20 purges |
| **HR3** | No circular loop (replaces R3) | No single fault produces a sustained bus -> charger -> pack -> BT boost -> bus current; a bounded single pulse per event is acceptable |
| **HR4** | No runaway | Charge and input current bounded by a hardware ceiling plus registers; no unregulated path |
| **HR5** | Fail-safe Teensy-commanded hard inhibit | Hard inhibit (Hi-Z / converter off / charge disable) that defaults to inhibit with the Teensy unpowered, in reset, hung, or with I2C dead; no autonomous charge out of POR or from stored settings |
| H1 | Common ground, high-side sense, no unregulated path | VIN- = VBAT- one node, no shunt or FET in the return |
| H2 | Hard charge inhibit while powered | Mechanism exists, covers trickle/pre-charge, latency within the section 2.5 allowance at the regen input current (critic-round recomputation: about 117-194 µs depending on input current and bus voltage; supersedes loop analysis §4.3's 290-340 µs) |
| H3 | Fail-safe (reset / hang / I2C dead / POR) | As HR5 |
| H4 | Input-voltage threshold for always-powered regen | Settable 18.5-19.5 V+ at runtime, accuracy known; FC value about 13.5-15 V; draw <= 5-10 mA just below threshold; no re-qualification on a dip; warm response per section 3.2 |
| H5 | FC charging from VBUS 15.9 V | >= 1.5 A at 8.4 V within the FC input budget; CV 8.400 V ±0.5 % or better; termination |
| H6 | Voltage ratings / OVP | No OVP drop-out at the 21.4 V measured peak / 22.13 V design clamp; abs max >= 30 V (36 V preferred) |
| H7 | Battery pin through D-BT-SQ | Starts into an open/capacitive VCHG; no lockout; CV error known |
| H8 | Inrush / hot-plug | On the RT1987-ramped node (12 mA/µF with 5.6 nF CSS): peak <= 1.0 A with aux; no electrolytic; no switching during the ramp |
| H9 | I2C / logic / status | 3.3 V open-drain, 100 kHz, no back-powering, status on pin 6 |
| H10 | Thermal / efficiency / wiring / mechanical | <= 2 W loss; off-board mount feasible |
| H11 | Availability | In stock today from a primary vendor page |
| H12 | Telemetry | Charge current and input V/I readable by the Teensy (EMS accounting, G2 credit term) |

### 1.2 Requirement-status matrix (all candidates)

Codes: **P** = PROVEN_DATASHEET, **C** = PROVEN_CALC, **B** = BENCH_GATE, **F** = FAIL, **U** = UNKNOWN / missing primary,
**sys** = blocked at system level (same for every candidate). "stock F" = fails as shipped, passes after the listed EVM mods.
Sources: the nine dossiers in `round2/` and their three adversarial lenses each.

| Req | BQ25798 (chosen) | BQ25713 (runner-up) | BQ25773 (alternate) | BQ25720 | BQ25731 | LTC4015 | BQ25756 | BQ24650 | MP2759 |
|---|---|---|---|---|---|---|---|---|---|
| HR1 regen | U (B: latency, warm) | U (B3, B4b) | U (B2, B4) | U (HIZ-exit re-measure likely) | U (R-1, M4) | U (VC windup) | U (cold restart per hard stop) | U (soft-start re-run?) | F (no hard per-burst inhibit) |
| HR2 FC | P charger / sys | P / sys | P / sys (review "refuted" = the system purge issue) | C / sys | P / sys | P / sys (permit error fixed) | P / sys | P on/off only / sys | P on/off only / sys |
| HR3 loop | C (interlock + C7 + fixes) | C (interlock; PTM bits) | C (interlock; REG0x30 PTM) | C | C (F1b needed) | C (FET-short fuse needed) | C (register-defeatable stops) | C | F (warm clamp is a throttle) |
| HR4 runaway | C nominal | C | C | C | C (EN_EXTILIM, IL_AVG 15 A default) | C (RSNSI ceiling 1.6 A > OC_FC) | C | C (shared sense R6) | C |
| HR5 fail-safe | B (stock F) | C after mods (stock F) | P intrinsic POR | B | P-cond (WDT loads 256 mA) | B (no host WDT) | C after mods (stock F) | C | F |
| H1 ground/sense | P | P | P | P | P | P | P | P | P |
| H2 inhibit | P mech / B latency | B | P / B latency | B | B | B (UVCLFB pulldown, not converter-off) | B | P / B | P (VLIM, 175 ms re-enable) |
| H3 fail-safe | B (stock F) | C (stock F) | P | B | P-cond | B | C (stock F) | C | F |
| H4 threshold | P range / B warm | B (19.52 V max; retention) | P (3.2-27 V) / B warm | B (19.52 V max) | B (19.52 V max) | B (UVCL POR = divider max) | B | B | B (shares off-threshold) |
| H5 FC | P | P | P | C | P | P | P | P (fixed RSR) / F runtime | P (fixed) |
| H6 ratings | P (30 V abs, OVP 25.2 V) | P (30 V abs; C25 16 V swap) | P (45 V abs, ACOV 33 V) | P (32 V, ACOV 26 V) | P (32 V, ACOV 26 V) | P (40 V, OVLO 37.7 V) | P (85 V) | P (33 V, ACOV 31 V) | P (45 V) |
| H7 D-BT-SQ | B (2.5 V hold, BATOVP) | P / B | B (register retention) | B | P | B (2-4 s detect) | P | B (needs D_byp) | P |
| H8 inrush | C 0.84 A (B scope) | C stock F 1.52 A -> 0.77 A | C stock F 2.25 A -> 0.74 A | C | C stock 1.36 A -> 0.50 A | B stock F 2.3-2.9 A | C stock F 2.6 A; 80 µF min | C 0.53 A | C 0.4 A |
| H9 I2C/logic | P | P | B | P (SMBus 0x09; CHRG_OK high unpowered) | B | P | P | P (no I2C) | P (no I2C) |
| H10 thermal/mech | B | P | B | B | B | C | B | C | C |
| H11 stock | P (TI 162) | P (TI 38) | P (TI 95) | U | U (TI page "In stock", qty login-gated) | U | P (TI 114) | P (TI 570) | U |
| H12 telemetry | P (1 mA/1 mV) | P (64 mA) | P (1 mA) | P (slow, 25 ms/ch) | P (slow) | P (coulomb counter) | P | F | F |
| **Dossier verdict** | FEASIBLE_W_COND | FEASIBLE_W_COND | FEASIBLE_W_COND | FEASIBLE_W_COND | FEASIBLE_W_COND | FEASIBLE_W_COND | FEASIBLE_W_COND | UNDETERMINED | NOT_FEASIBLE |

### 1.3 Candidate notes (round-2 primaries; round-1 numbers superseded)

- **BQ25798** (SLUSDV2C, SLUUCB5E). VINDPM 3.6-22 V / 100 mV, ±2 % at 18.6 V (EC p.12); retention per Table 7-17 p.62. POR
  charges at 1 A with VINDPM = VBUS0 - 1.4 V (§7.3.4.4 p.27, Table 7-9 p.41); stock EVM grounds /CE through JP17. Cold start
  >= 0.2-0.6 s (REGN +150 ms, poor-source ~30 ms, D+/D- 0.5-2 s if enabled, +30 ms; §7.3.4 p.26), so always-powered is
  mandatory. Never-write REG0A (a CELL write can move VREG to 12.6 V, §7.3.2 p.25) and REG16 (VAC1_PD_EN = 60 Ω on VCHG-IN).
- **BQ25713** (SLUSD83C, SLUUBT8B). VINDPM 3.2-19.52 V / 64 mV, -3/+2 % at 18.688 V (p.12); POR "VBUS no-load - 1.28 V"
  (§9.3.3.2 p.25); cold start >= 150 ms (§9.3.3 step 5 p.24). Review findings: the TLV3012B is push-pull (SBOS300C p.1), so
  the dossier's wire-OR inhibit was wrong; PTM (EN_PTM, PTM_PINSEL, EN_EXTILIM) turns "ILIM_HIZ low" into pass-through
  (§9.4.3 p.32) - never write, read back; IIN_HOST resets to 3.25 A on adapter removal (§9.6.6.1 p.61). Fixed in
  `design_BQ25713.md`.
- **BQ25773** (SLUSEK7, SLUUCY2). VINDPM 3.2-27 V / 20 mV, ±1 % at 18 V (p.12, p.66); POR CHARGE_CURRENT 0, VINDPM 3.2 V; 5 s
  watchdog option (p.21); ACOV 33 V default; 45 V abs max (p.8). Review findings: registers persist in battery-only mode when
  VCHG > VBAT_UVLO 3.3-4.05 V (§7.3.1 p.27), so "every input loss is a POR" is false; REG0x30 holds EN_PTM and SYSOVP_MAX
  next to FRC_CONV_OFF (write as full constant); JP4 ships at 4S; the watchdog is kicked by any CHARGE_CURRENT write
  (§7.3.26.1 p.47), so kick with WD_RST only; Mod B (JP6 removed) is excluded because FRC_CONV_OFF pulls CHRG_OK LOW
  (§7.3.4 p.30). The regen-lens "showstopper" is the system-level purge problem (HR2), which applies to every candidate.
- **BQ25720 / BQ25731** (SLUSDU3/SLUUC74; SLUSE66A/SLUUCB9A). Same 19.52 V VINDPM ceiling as the BQ25713; a no-load VBUS
  measurement "right before the converter is enabled" (SLUSDU3 §9.3.7 p.28; SLUSE66A §9.3.6 p.26) makes VINDPM re-measure
  on Hi-Z exit plausible, which would turn every burst into an H1 hysteresis limit cycle. BQ25731 watchdog loads 256 mA on
  expiry (SLUSE66A §9.3.21.1 p.33), contradicted at p.45. ADCs 25 ms per channel.
- **LTC4015** (LTC4015 Rev B, DC2039A Rev D). UVCL resets at POR to the divider maximum (code 0xFF, register can only lower
  it; DS p.22, p.60) - the safest POR threshold of all candidates. Against: no host watchdog in the register map; leaving
  `suspend_charger` costs a 2-4 s battery detection (p.30); the DC2039A carries a 120 µF electrolytic (2.3-2.9 A inrush) and
  a PIC16F1459 I2C master; the dossier's series permit (P5 AND H1) blocks FC charging (needs H1 OR H2); bridging D-BT-SQ
  exposes the pack to a power-stage FET short.
- **BQ25756** (SLUSEN5A, SLUUCT7D). VAC_DPM 4.2-65 V / 20 mV, not auto-reset except REG_RESET/POR. Every hard stop restarts
  cold (12 ms deglitch, ~40 ms compensation toggle, typical 145-175 ms). DIS_CE_PIN / EN_ILIM_HIZ_PIN / EN_ICHG_PIN make the
  "hardware" stops register-defeatable (Tables 6-20/6-21). The S1 "co-ramp during low-voltage bring-up" doctrine is retired
  on this board (bring-up staged P0-P3; `motPwrConnectBlocked()`, ino ~2340).
- **BQ24650** (SLUSA75B, SLUU444A). Resistor-strapped MPPSET threshold survives POR (a real strength); but every MPPSET < 75 mV
  release costs 1.5 s (EC p.9), no runtime current control (H5b F), no telemetry (H12 F). Rejected.
- **MP2759** (DS Rev 1.0, EV2759-Q-01A). VLIM off threshold (0.6-1.0 V) shares the pin with the 1.2 V reference; a plain 19 V
  divider sits inside the off band at bus voltage; re-enable about 175 ms (EVB p.9). No I2C. NOT_FEASIBLE.

---

## 2. Loop / runaway analysis and the backstop set

Full analysis: `round2/loop_analysis.md` (calculations `round2/calc/comp_calc.py`).

### 2.1 Why the charger threshold cannot be the interlock

Every primary-read TI charger resets its input-voltage threshold at power-up from the voltage it sees (BQ25713/BQ25720:
VBUS - 1.28 V, SLUSD83C §9.3.3.2 p.25, SLUSDU3 p.28; BQ25798: VBUS0 - 1.4 V, SLUSDV2C §7.3.4.4 p.27) or to 3.2 V (BQ25773,
SLUSEK7 p.39). An always-powered charger re-boots at bus level after any glitch with its threshold **below** the bus. The
threshold is a soft layer, valid only after a host write and readback in the current power cycle.

### 2.2 The physical barrier for the regen path (H1)

Bus current can reach V-MOT only through D-MT-EN, and D-MT-EN conducts only when V-MOT < VBUS (RT1987 DS-00 §17.6: forward
regulation 35 mV, fast reverse comparator at -50 mV, about 0.5 µs; all typical only). A comparator measuring directly across D-MT-EN that
permits the charger only while **V-MOT > 1.067 x VBUS** therefore lets the charger convert only while the bus *cannot* feed
V-MOT, whatever the registers hold and whether the MCU runs, hangs or resets.

| Item | Value |
|---|---|
| Part | TLV3012B (push-pull, Vos ±9 mV **at VCM = V- only** plus a CMRR term at H1's VCM 1.68-2.11 V (54 dB min, specified at VS = 5.5 V only; 3.4-4.2 mV used, TODO(verify: SBOS300C) at 3.3 V), internal hysteresis 2-8 mV (included in the worst case); prop <= 4 µs **at 100 mV overdrive** (slow ramps are slower: 15 µs allocated, S2-b); output LOW during its <= 1.9 ms POR and when unpowered; fail-safe inputs to 5.5 V; SBOS300C §6.9-6.10, §9.4.4-9.4.5) |
| Dividers | V-MOT 499k / 56.2k, VBUS 464k / 56.2k, **0.1 %**, 470 pF each (24 µs matched); RH 6.49 MΩ (≈ 0.30 V hysteresis) |
| Trip points | VBUS 15.9 V: permit 17.13 V nominal (17.33 V worst max), inhibit 16.82 V nominal (16.62 V worst min); VBUS 16.39 V: worst rise max 17.86 V, worst fall min 17.15 V; VBUS 19.5 V: inhibit >= 20.47 V (worst values include the CMRR term, critic round) |
| Guard | >= 0.70 V over 15.59-19.5 V with 0.1 % parts (0.73 V before the CMRR term); collapses to 0.24 V with 1 % parts, so 0.1 % is mandatory |
| D-MT-EN figures | VFWD 35 mV, VFRC -50 mV, tFRC 0.5 µs are **typical only** (RT1987 DS-00 EC p.7, §17.6); so are tD_ON 8 ms and tON 1.9 ms used elsewhere |
| Not reused | The RGN-V divider (its node is the TL431 REF; loading it shifts the clamp and pin 39) |

### 2.3 The FC-window permit (H2) and the C7 qualifier

In an FC window the bus is FC-only, so a pack -> bus path needs D-BT-EN to conduct.
`H2 = FCC_net AND NOT(BTB_net OR RGN_net OR BT_ACT)`, with BT_ACT a second TLV3012B on the INA253 BT output at 19.8 mV
(I_BT ≈ 0.2 A; trip 0.11-0.29 A over Vos).

**INA253 zero-current floor (corrected in the critic round).** Source: `references/Datasheets/INA253A1IPWR.pdf` (SLOS954A,
§7.5 Electrical Characteristics): I_OS ±2.5 mA typ / ±15 mA max input-referred, **and Swing to GND VGND + 1 mV typ /
VGND + 10 mV max** (RL 10 kΩ, ISENSE = 0 A, VREF1 = VREF2 = 0 V, -40 to 125 °C). With REF1 = REF2 = GND (unipolar) the output
cannot go below that floor, so at the A1's 100 mV/A a zero current can read up to 0.1 A. The round-1 claim that a firmware
trip at about 50 mA is "> 3x the maximum offset" was **wrong**: 50 mA (5 mV) is inside the floor. Consequences:
- Firmware I_BT trip: threshold = the BT-channel zero-current floor measured on this board at each boot (S4-a, FCC = REGEN =
  BT_BUS = 0) plus margin; with the datasheet maximum floor that is about 0.12 A.
- BT_ACT: its minimum trip 10.8 mV (19.8 mV - 9 mV) sits only 0.8 mV above the 10 mV maximum floor. A false trip at zero
  current withdraws H2 (harvest lost), which is the safe direction.
- **Charger-side power-balance cross-check (new, FC windows):** IBUS x VBUS from the BQ25798 ADC (REG31, REG35) plus modelled
  aux must equal I_fc x V_bus within a threshold set from S1-B9. A circulating loop through D-BT-EN shows as charger input that
  the FC did not deliver, however small the INA253 reading. The IBUS ADC accuracy is unspecified ("valid for DC states only",
  §7.3.10 p.47), so the achievable threshold is a bench result.
- **Residual if neither reaches below the BT_ACT trip:** a sustained loop of up to about 0.29 A in an FC window, needing
  D-BT-EN shorted, bounded by the FC ILIM ceiling (0.74-0.96 A) and lasting for the window. This goes to the operator for a
  ruling (HR3 row, section 0.2).

**C7 correction (BQ25713 design; panel P3 for the BQ25798):** H1 is meaningful only in regen mode. The final logic is

```
GATE     = (H1 AND RGN_net AND NOT FCC_net) OR H2
PERMIT   = P5 AND GATE
ILIM_REL = GATE OR (CHG_QUAL AND NOT P5)        [critic round: NOT P5 term is hardware, not firmware invariant I-5]
```

Without the qualifier, a brake during an FC window raises H1 and grants PERMIT through the OR, bypassing H2; with D-BT-EN
shorted that sustains loop L-F for the brake duration. Without the NOT P5 term, firmware driving P5 HIGH while CHG_QUAL is still
HIGH at Run entry (VINDPM still the plug-in auto value, about 14.5 V, below the bus; EN_CHG resets to 1, SLUSDV2C Table 7-25)
would let the converter charge from the bus at the ILIM ceiling with BT_BUS closed (loop L-R) and no hardware barrier. The term
costs a 1G04 and a 1G08 feeding the existing OR. Logic family: SN74LVC1G08/11/27/32/04 (VIH 2.0 V / VIL 0.8 V at
3.0-3.6 V, Ioff partial power-down; SCES217 §5.3 p.5 and family sheets, fetched). Residual: an EN net stuck between the
RT1987 VEN_F minimum 0.6 V and VIL 0.8 V reads "off" while the switch may conduct; BT_ACT covers it in the FC window.

### 2.4 Runaway bound

Charge current can run only while the charger converts, and is bounded by the charger's own sense. Required (and met by
the chosen design): high-side sense (BQ25798 senses VBUS-PMID and SYS-BAT internally, SLUSDV2C Table 5-1 pp.4-5); a
**hardware** input ceiling (mode-switched ILIM_HIZ divider, regen 1.44-1.72 A, FC 0.74-0.96 A with 1 % resistors and REGN
4.8-5.2 V, §7.3.4.3 Eq.1 p.27: ILIM = (V - 1 V)/0.8 Ω; the ADC reads the pin at each plug-in after PG_STAT, §7.3.4 step 6
p.26, so a charger POR inside an FC window latches the FC ceiling); register bounds (IINDPM, ICHG, VREG); no passive SYS ->
VBUS path and backup mode blocked without an ACFET (SLUSDV2C p.6, §7.3.7.2 p.37).

**Physical reverse-power barrier (critic round).** A stray OTG or backup-mode enable would drive the charger's VBUS pin
(= VCHG-IN) from the pack. That energy cannot reach VBUS or V-MOT: D-BC-FC (VIN = VBUS, VOUT = VCHG-IN) and D-BC-RG
(VIN = V-MOT, VOUT = VCHG-IN) are back-to-back-FET ideal diodes that block VOUT > VIN (RT1987 DS-00 §17.6; a TRCB condition also
prevents turn-on, §17.4). The never-write list (OTG registers) is the second layer, not the only one. The RT1987 auto-restarts
**without soft-start** when a TRCB condition clears (DS-00 §17.4 Table 1), so a D-BC-RG/D-BC-FC re-close after a reverse trip
is a hard close onto the EVM input capacitance through the leads; S4-c scopes it. In regen mode charge power is self-limiting (drawing more than regen supplies pulls V-MOT to VINDPM, then to the H1
fall trip). In FC mode OC_FC (1.4 A, single sample, `LIMIT_I_FC_MAX`, ino 2090) and the firmware raw I_fc > 1.20 A arm drop
bound it. The board has **no hardware pack-OV action**, so firmware OV_BATT (8.5 V) and VREG readback (<= 8.40 V) are the
only overcharge bounds.

### 2.5 The timing requirement that remains

After H1 trips, the charger input current must stop before V-MOT falls to VBUS - VFWD (D-MT-EN starts conducting). **Recomputed
in the critic round** (`round2/calc/comp_calc.py`, critic-fix block) from the final dividers' worst-case fall trip (including
CMRR and internal hysteresis), VFWD 35 mV (typical only), 0.4 mF on V-MOT, and deductions of 24 µs divider RC lag, 15 µs
comparator (slow-ramp overdrive) and 20 µs gate RC. The earlier "290 µs at 1.5 A / 320-340 µs at 1.25 A" (loop analysis §4.3)
used an H1 fall trip of 17.0 V and is superseded.

| Charger input at the stop | V-MOT slew | Allowance, VBUS 15.9 V | Allowance, VBUS 16.39 V |
|---|---|---|---|
| 1.25 A | 3.13 V/ms | **184 µs** | **194 µs** |
| 1.40 A (ICHG 2.50 A bound with margin: 1.33 A at η 0.85, 8.4 V pack, 18.62 V in) | 3.50 V/ms | **158 µs** | **167 µs** |
| 1.72 A (regen ILIM ceiling max) | 4.30 V/ms | **117 µs** | **125 µs** |

The pass value for S1-B3 is the row of the measured input current at ICHG 2.50 A; **<= 115 µs** covers every row. If
slower, the bus feeds the charger for the excess only: one bounded pulse per event that bus energy cannot sustain (H1
hysteresis cannot be re-crossed by bus energy). On a regen-to-motoring reversal V-MOT reaches VBUS in tens of µs, so the
criterion is a **bounded pulse** (<= I_in x t_inh per reversal, t_inh well under 1 ms), not "no bus feed" (BQ25731 loop review).
No datasheet gives this latency: bench gate S1-B3.

### 2.6 Minimal backstop set

| Layer | Element | Duty |
|---|---|---|
| Hardware (carries the loop proof) | H1 V-MOT/VBUS comparator; H2 FC-window permit; C7 logic; CHG_QUAL AND NOT P5; inhibit stages biased from the charger's REGN; reverse blocking of D-BC-RG/D-BC-FC | Loop impossible with any single fault; absent logic = inhibit |
| Charger-intrinsic | Hard-inhibit pin (not register-only); high-side sense with resistor ceiling; no charge until enabled; no autonomous restart from stored settings | Runaway bound; fail-safe |
| Independent | eFuse (active current limit, fast trip) on VCHG-IN, section 4.2 | Charger power-stage FET short (no controller can open it) |
| Firmware | 1 kHz F1 cross-check (PERMIT/H1/H2 vs ADCs; needs V_rgn calibrated first); mode-transition sequencer; I_BT trip with BT_BUS LOW above the measured INA253 floor (section 2.3); FC-window power-balance cross-check; poor-source recovery; safety-register readback; ported G1-G3 + trip latch; `FAULT_SWITCH_CONFLICT` in all builds | Overcharge, stale state, detection |
| Watchdogs | MCU RTWDOG + WDOG1 (section 5.1); charger watchdog second tier only (P7) | Hung-MCU double faults |

**Option (a) (BT hot standby in FC windows)** removes ¬BTB from H2 and makes the firmware I_BT trip inapplicable; it needs a
replacement barrier (hysteretic or latched BT_ACT near the measured offset) before it can be offered (P10).

### 2.7 Single-fault table (summary; full table in loop analysis §8 plus review additions)

| Fault | Outcome with the chosen design |
|---|---|
| Teensy reset / unpowered | RT1987 EN 10 kΩ pull-downs open all paths; P5/QUAL 47 kΩ pull-downs; /CE HIGH; charger off |
| Teensy hang (pins frozen) | H1/H2 still gate ILIM_HIZ; charger watchdog unproven (P7); MCU watchdog required |
| I2C dead | P5 held LOW (config unverifiable); /CE HIGH |
| Comparator stuck HIGH | VINDPM soft layer (19.0 V) holds at bus level; F1 trips <= 6 ms; with a hang = double fault, bounded by the regen ILIM ceiling (<= 1.72 A) |
| **CHG_QUAL and P5 both HIGH, H1 = 0, VINDPM below the bus** (firmware fault at Run entry; critic round) | Hardware term `CHG_QUAL AND NOT P5` keeps ILIM_HIZ LOW: converter off. Without it: loop L-R at the ILIM ceiling. Injection S3-i |
| Comparator stuck LOW / unpowered | Charger inhibited (harvest lost, safe) |
| D-BT-EN shorted in FC window | BT_ACT withdraws permit above 0.11-0.29 A; below that the firmware I_BT trip (measured floor + margin, about 0.12 A) and the power-balance cross-check; residual below their thresholds is an operator ruling (section 2.3) |
| D-BT-EN shorted + brake in FC window | Closed by the C7 qualifier (P3) |
| Charger HS FET short | Fuse / independent OC cut (condition 7); RT1987 has no current limit after tON |
| REG0A CELL write | Never-write list + readback of CELL and VREG <= 8.40 V each poll |
| REG14 bit slip (EN_IINDPM/EN_EXTILIM) | Readback each pass; ICHG <= 1.8 A in FC mode |
| REG16 VAC1_PD_EN set | 60 Ω on VCHG-IN (0.27-0.36 A, 4.3-7.6 W); never-write + readback |
| VINDPM reset at plug-in (every Run start) | Image written only after PG_STAT = 1 and the auto-set has landed, P5 held LOW until then |
| Failed-FB boost (bus 18.3-19.5 V) | VINDPM 18.62 V min alone does not cover it; H1 does (fall trip >= 20.52 V at 19.5 V bus) |
| VESC abrupt stop mid-burst | H1 falls (comparator 4 µs at 100 mV overdrive, 15 µs allocated); one bounded pulse if charger latency > the section 2.5 allowance |
| D-BC-FC shorted (critic round) | VCHG-IN tied to VBUS. In regen mode D-BC-RG then conducts V-MOT into the bus, so V-MOT cannot rise 6.7 % above VBUS: H1 never permits (harvest lost); regen energy raises the bus to the fw OV_BUS latch (17.5 V) -> State 99. In Idle the charger is powered but inhibited (GATE = 0). No loop. Detected by the S4-a self-test (V_chg does not decay with FCC = REGEN = 0) |
| D-BC-RG shorted (critic round) | VCHG-IN tied to V-MOT (about VBUS with MOT_PWR closed). Idle: charger powered, GATE = 0 (RGN_net and FCC_net LOW), inhibited. FC window: V-MOT and VBUS both feed VCHG-IN, BT_BUS LOW, H2 governs; a brake feeds the charger only (D-BC-FC blocks VCHG-IN -> VBUS). No loop. Detected by S4-a |
| D-MT-EN shorted (critic round) | V-MOT = VBUS both ways: H1 ratio about 1, never permits (harvest lost); regen raises the bus to OV_BUS. No loop through the charger. Detected at bring-up (V_rgn tracks VBUS with MOT_PWR LOW) and by S4-a |
| MCU watchdog reset during a regen burst (critic round) | EN pull-downs open MOT_PWR and REGEN together; V-MOT is isolated with the VESC still braking and dumps only into the 0.47 A chopper, rising to the VESC OV cut (~21.35 V) and the VESC OV fault stops regen, as on today's rig. P5/QUAL pull-downs inhibit the charger. Safe, harvest lost; chopper SOA at this duty is a missing primary (BSP170P). S3-W is run once during a brake |

### 2.8 Incidental firmware findings (fw v37 rev 2)

- The `J` session (charger fed through MOT_PWR + REGEN with BT_BUS closed) **closes loop L-R by construction**. Retire it;
  replace with an FC-path session (BT_BUS 0, REGEN 0, FCC 1, H2 in force).
- `FAULT_SWITCH_CONFLICT` is inside `#if !BENCH_TEST` (ino ~7413-7419), so the BENCH_TEST 1 build now on the bench has no
  illegal-switch-combination fault.
- State-99 phases that drain VBUS and V-MOT "into the charger" drain nothing into an inhibited charger; delete them, and the
  REGEN HIGH with MOT_PWR LOW pattern with them.
- State-98 `4` toggles pin 5 unconditionally; after the mods pin 5 HIGH arms the new charger. The EVM must not be connected
  until the CSV rename and new firmware are flashed.

---

## 3. Regen dynamics, capture model, FC-charging mode

Full analysis: `round2/regen_dynamics.md`, figures `round2/figs/fig1-fig4`, model `round2/calc/capsim.py`.

### 3.1 What the logs show

- **Pulse shape** (9 BLGs at 1 kHz + RegenTest_v2 bag): V-MOT rises 15.9 -> 21.20-21.47 V in 19-47 ms, starting within about 5 ms
  of `I_cmd` going negative; sharp cusp; linear decay at 14-20 V/s with no regen current; a second pulse 0.523-0.562 s later
  (mean 0.535 s, 8 events); `I_cmd` stays at the -12 A rail throughout.
- **Likely cause (UNCONFIRMED):** a VESC over-voltage fault followed by its fault-stop timer. **Upgraded this revision:** the
  VESC firmware default `MCCONF_M_FAULT_STOP_TIME` is 500 ms ("Ignore commands for this duration in msec when faults
  occur"; vedderb/bldc `motor/mcconf_default.h` line 546, master, fetched 2026-11-05), consistent with the 0.535 s re-pulse.
  The generic `MCCONF_L_MAX_VOLTAGE` default there is 57 V (lines 62-63); the cut at ~21.35 V therefore implies a
  hardware- or user-configured limit on this VESC Six EDU, which M-R0 must read from VESC Tool. The EDU hwconf file was not
  obtained.
- **Corrections to earlier docs:** fw37 planning §3.2's "rises 0.08-0.12 s after the setpoint" is the 50 Hz setpoint chain,
  not the electrical onset (about 5 ms). "About 0.2 A for 0.4 s" is wrong: the real pulse is 30-50 ms; the 0.3-0.6 s tail is
  node capacitance discharging into VESC housekeeping. Chopper dissipation is about 0 J (peaks below the 22.13 V design
  clamp).
- **Energy reaching V-MOT per hard decel today:** C x (134-292) J/F = 0.13-0.28 J at 0.97 mF (HIL default) or 0.54-1.17 J
  at 4 mF. Board-only capacitance is about 0.48 mF (CAL 470 µF + C-D6/C-D7); VESC input capacitance never measured; two weak
  checks point to about 4 mF total.

### 3.2 Capture model and warm-response requirement

**Energy available if the VESC keeps braking** (model at the -12 A rail):

| Decel | Electrical at V-MOT | Into pack (8.4 V) | Peak power | Braking time |
|---|---|---|---|---|
| 2 -> 1 m/s | 2.09 J | 1.81 J (215 mC) | 11.1 W | 0.30 s |
| 3 -> 1 m/s | 6.32 J | 5.55 J (661 mC) | 18.9 W | 0.58 s |
| 2 -> 1 m/s at 5 A | 2.17 J | 1.83 J | - | 0.53 s |

About 10x what reaches the node today.

**Capture is a cliff:** if the charger reaches current before V-MOT climbs from Vth to ~21.35 V, capture is 96-99 % and
V-MOT holds at Vth with the chopper off; if not, the VESC trips, coasts 0.53 s, and capture drops to 6-40 %. Threshold
choice across 18.0-19.5 V costs only 1-2 % of energy, so Vth is set by the safety floor. A cold start (65-170 ms) never works
on this rig.

**τ_warm requirement** (step from Vth - 0.5 V to Vth + 1 V; τ = time to 63 % of the charge-current setting), Vth 19 V, 2.5 A
ceiling:

| Braking case | C = 0.49 mF | C = 0.97 mF | C = 2 mF | C = 4 mF |
|---|---|---|---|---|
| 3 -> 1 m/s, 12 A | 2.5 ms | **4.5 ms** | 10 ms | 23 ms |
| 2 -> 1 m/s, 12 A | 8.2 ms | **17 ms** | 41 ms | 114 ms |
| 2 -> 1 m/s, 5 A | 34 ms | **73 ms** | 187 ms | > 300 ms |

**Requirement: τ_warm <= 4 ms (10-90 % <= 9 ms), <= 2 ms if C is board-only;** relaxes to about 20 ms if 4 mF is confirmed,
about 60 ms if the VESC cut-off is raised. The charger must not re-run input-detect deglitch, POR or soft-start each time
V-MOT crosses Vth. Review refinements: the pass limit must be set at the **worst-case** Vth (setting x 1.02 for the BQ25798),
the fitted input ceiling and the lowest observed cut (21.20 V); when the VESC regen limit is set equal to the charger's input
capability the bound reduces to C·ΔV/A (2.5-3.0 ms at 0.97 mF). In the H1-gated design the comparator releases at about
17.1-17.8 V, giving **1.8-11.6 ms of head start** before V-MOT reaches Vth (worst case at elevated bus and the fastest
measured rise, 287 V/s), so the B4 test is run as "release at the H1 edge, then ramp at the measured slope".

**Levers if τ fails:** raise the VESC cut-off to about 23-24 V (the chopper then buffers up to 0.47 A; 2 m/s brakes never trip;
3 m/s allows τ 63-75 ms; needs M-R0, C-D8/C-D10 >= 35 V; BQ25798 VBUS recommended max 24 V, so <= 23 V preferred); add V-MOT
capacitance (about 4 ms per mF at Vth 19 V, but about 0.65 A extra D-MT-EN soft-start current per mF; measure first, M-R1).

**EMS usefulness:** 0.2-0.66 C per hard decel = 1.2e-5 to 3.7e-5 SoC on a 5 Ah pack (capacity unverified), 0.2-0.6 % of the FC
energy in a 61 s cycle per decel. Readback: BQ25798 IBAT 1 mA LSB (6 ms/channel, "valid for DC states only", §7.3.10 p.47;
accuracy unspecified -> S1-B9). Research drive cycles need decels steeper than coast-down (0.65-1.03 m/s²).

### 3.3 Charger ceiling vs the regen requirement (chosen part)

**Critic-round redesign.** The first draft's single ILIM ceiling (1.15-1.35 A) gave 1.15 A x 18.62 V = 21.4 W at the bottom of
tolerance, which is 2.32 A of charge at 8.4 V (91 % efficiency at 20 V, SLUSDV2C Fig 6-4 p.18, figure reading, typical; the
first draft's 2.37 A holds only at 8.2 V). That failed the HR1 pass condition (>= 23 W at the threshold). The divider is now
mode-switched (section 4.1): R21 121k / R23 100k from REGN in regen mode gives **1.44-1.72 A** (1 % resistors, REGN 4.8-5.2 V,
§7.3.4.3 Eq.1 p.27). With the IINDPM regulation tolerance (880-1000 mA at a 1000 mA setting, VBUS 9 V, SLUSDV2C EC; not
specified at 19 V, so bench S1-B6) the worst-case input at the 18.62 V VINDPM floor is 1.435 A x 0.88 x 18.62 V = **23.5 W**.

The ICHG 2.50 A register cap is now the binding limit: input = 2.50 A x V_pack / 0.91 = **20.3 W at 7.4 V, 23.1 W at 8.4 V**
(efficiency typical). Both exceed the 18.9 W peak of the 3 -> 1 m/s, 12 A brake that defines HR1, so the defining case is
covered. Meeting the 23 W design target at low SoC needs ICHG >= 2.83 A (23 x 0.91 / 7.4), which waits on the pack
datasheet's maximum charge current (section 8.1 item 6, section 8.2). Alternatively, the operator restates HR1 at about 20 W.
The VESC regen current limit is the backstop (regen dynamics §3.1).

### 3.4 FC-charging mode

| Item | Value (chosen design) |
|---|---|
| Switches | FC_REG 1, BT_REG 1, FC_BUS 1, **BT_BUS 0**, MOT_PWR 1, **REGEN 0**, **FC_CHARGE 1**, BT_SEQ 1 |
| Threshold | VINDPM 13.5 V (0x87; about ±2.6 % interpolated -> 13.14-13.86 V); it is a bus-collapse guard, not an FC-sag guard (the bus is the regulated 16 V boost output) |
| Input limit | IINDPM 0.90 A at standstill; in cruise min(0.90, 1.20 - I_aux - I_traction,filt - 0.10) A, rewritten at 50 Hz with readback; window closes below 0.30 A. The FC ILIM ceiling (0.74-0.96 A) can bind below the 0.90 A register value |
| Charge | ICHG 1.60 A; standstill result **1.31-1.58 A** at 0.74-0.90 A input (≈ 93.5 %, Fig 6-4 figure reading; 1.50 A at the nominal 0.85 A ceiling, so H5's 1.5 A holds at nominal only); bus side 0.89-1.05 A |
| Hard bounds | FC ILIM ceiling 0.74-0.96 A (R_FC 158k switched in by FCC_net; holds after a charger POR inside the window, since the ADC re-reads the pin at plug-in); after a POR at standstill the bus load is <= 0.96 + 0.15 A aux = 1.11 A without relying on ICHG; firmware raw I_fc > 1.20 A drops P5 the same tick; OC_FC 1.4 A latch |
| CV | VREG 8.400 V, -0.25/+0.65 % (EC p.11) -> VCHG 8.379-8.455 V; pack at termination **8.34-8.42 V** through D-BT-SQ and leads; do not trim upward |
| Termination | ITERM 200 mA; firmware clears EN_CHG at CHG_STAT 7h |

**System blockers (HR2):**
1. **Purge collapse.** The H-20 purges to about 1 V, below the TPS61288 2.0 V VIN minimum (SLVSFP3C ROC); with BT_BUS LOW the
   bus falls at about I_AUX/C_VBUS (2.57 V/ms, campaign G) and UV_BUS (20 ms dwell) latches inside a 100-200 ms purge. Bench
   2026-10-28: UV_FC + UV_BUS latched within seconds of the first window. fw v35 v33b gates windows on `!fcUvLockoutActive()`,
   which "in practice REFUSES charge windows outright" on a running stack (ino ~15483-15499). Needs the condition-2 ruling.
2. **Budget.** With BT_BUS LOW the FC alone carries traction + aux + charger; FC charging is effectively standstill-weighted
   (about 0.1-0.25 A traction headroom at a 1.0 A charger input). The phase-A finding that FC-charge + traction is infeasible on
   1010 of 2525 SDP cells is consistent.
3. **Time-multiplexing.** Under CSV row 31 regen and FC charging are mutually exclusive in time; a brake inside an FC window
   is not harvested unless the transition is pre-emptive (condition 3).
4. **No cold FC close.** 70.2 µF x 12 mA/µF = 0.84 A + 0.15 A aux = 0.99 A from an FC-only bus (1 % margin; RT1987 tON is
   typical-only); forbidden. FC windows open warm from the regen path (VCHG-IN droops <= 0.6 V over the 8 ms tD_ON, typical
   only), or fit 100 nF CSS.

---

## 4. The chosen design (BQ25798EVM) and the runner-up delta

Design record: `round2/design_BQ25798.md` + `round2/design_BQ25798.svg` (with the round-2 correction banner). This section is
authoritative where they differ.

### 4.1 Architecture

```
H1       = TLV3012B: V-MOT > 1.067 x VBUS (+0.30 V hysteresis)
BT_ACT   = TLV3012B: INA253 BT output > 19.8 mV (I_BT > ~0.2 A)
H1q      = H1 AND RGN_net AND NOT FCC_net                          [C7 qualifier, panel P3]
H2       = FCC_net AND NOT(BTB_net OR RGN_net OR BT_ACT)
GATE     = H1q OR H2
PERMIT   = GATE AND P5 (CHG_ARM)
ILIM_REL = GATE OR (CHG_QUAL AND NOT P5) -> stage B -> ILIM_HIZ    (per-burst hardware converter-off; EN_EXTILIM = 1)
ILIM div = R21 121k / R23 100k from REGN; R_FC 158k to AGND via Q3 when FCC_net   (regen 1.44-1.72 A / FC 0.74-0.96 A)
/CE drive (0 Ω link):  default  P5 AND NOT trip   -> stage A -> /CE   (static arm; panel P1)
                       option   PERMIT            -> stage A -> /CE   (only if S1-B7 shows no 2.5 V BAT hold)
```

- **Per-burst gate:** ILIM_HIZ. Below 0.75 V switching stops with REGN on; above 1 V it resumes (SLUSDV2C §7.3.4.3 p.27; EC
  p.16). With EN_EXTILIM = 1 this behaviour carries no register caveat.
- **Mode-switched hardware ceiling (critic round, replaces the single R21 150k / R23 100k = 1.15-1.35 A divider):** R21 121k /
  R23 100k from REGN = 0.4525 x REGN, 2.15-2.37 V -> **1.44-1.72 A** in regen mode; Q3 (NMOS, gate from a buffered FCC_net copy
  on the carrier) adds R_FC 158k in parallel with R23 in FC mode -> **0.74-0.96 A** (1 % resistors, REGN 4.8-5.2 V, Eq.1 p.27;
  `round2/calc/comp_calc.py`). The ADC reads the pin after PG_STAT at each plug-in (§7.3.4 step 6 p.26), so a charger POR
  inside an FC window latches the FC ceiling and the FC bound no longer depends on the conflicting ICHG default (1 A per
  SLUSDV2C Table 7-2 / Table 7-16, 2 A per SLUUCB5E Table 1-3 JP24). Whether the pin is also re-read continuously (pin table:
  "the lower setting of ILIM_HIZ pin and the IINDPM register") or only at qualification (§7.3.4.3: "At POR ... the charger ADC
  reads the ILIM_HIZ pin") is P6 / S1-B6. If only at qualification, a Run-entry qualification in regen mode keeps the regen
  clamp through an FC window (the FC bound is then IINDPM, written and read back, plus firmware), and a charger POR in an FC
  window leaves the FC clamp in force on return to regen (detected by the REG06 readback, harvest-degraded flag, re-qualify in
  Idle). Q3's Vgs(th) at 3.3 V drive is a missing primary (BSS138/2N7002).
- **Static gate:** /CE, HIGH whenever the Teensy has not armed, is in reset, is unpowered, or the trip latch has fired.
  Charging needs EN_CHG = 1 **and** /CE LOW (§7.3.9.1 p.41).
- **CHG_QUAL** (new pin 10) releases ILIM_HIZ only during input qualification with P5 LOW, so the qualification ADC read sees
  the divider rather than the 100 mA clamp (< 1.08 V, §7.3.4.3). "With P5 LOW" is enforced in hardware (`AND NOT P5`, critic
  round), not only by firmware invariant I-5.
- **Not gated:** D-BC-RG EN with H1. Every burst would pay tD_ON 8 ms + tON ~1.5 ms (exceeds τ) and hot-plug VCHG-IN; it is
  the opposite of the accepted always-powered design.
- **Loop proof under the default /CE drive:** one dynamic hardware pin (ILIM_HIZ via H1q/H2) plus the VINDPM soft layer plus
  the physics of D-MT-EN; /CE adds a firmware-commanded static barrier covering the Run-entry window when VINDPM is still the
  plug-in auto value (about 14.5 V). A failed stage B **and** a stale VINDPM is a double fault, bounded by the ILIM ceiling.

### 4.2 Wiring and mods

**Mount:** EVM off-board on nylon standoffs, >= 20 mm from the LM1084 side, leads <= 0.30 m; the 32 x 35 mm footprint cannot
take it (5 terminal blocks, ~33 jumpers). No capacitor added at the EVM input.

| Ag105 pad | Board net | EVM point | Wire |
|---|---|---|---|
| VIN+ (10) / VIN- (4) | VCHG-IN / GND | J1 VIN1 / J1 GND (through the VCHG-IN eFuse) | 20 AWG twisted, <= 1.72 A |
| VBAT+ (18, 19) / VBAT- (14, 15) | VCHG / GND | J5 pin 1 / J5 pin 3 | 18 AWG twisted, <= 2.5 A (31 mV at 2.5 A round trip) |
| SDA (8) / SCL (7) | Teensy 18/19, 10 kΩ to 3V3 | EVM SDA/SCL (J8, by continuity) | 26 AWG twisted with GND; **100 kHz only** (t_r ≈ 0.85 µs) |
| STAT (3) | Teensy 6 | EVM STAT (JP32 side) | Open-drain, **LOW = charging** (Table 7-11 p.48); `INPUT_PULLUP` |
| MPPTD (11) | Teensy 5 | carrier input P5 | pin 5 -> `CHG_ARM` (CSV first) |
| THERM (13) | J-NTC | J7 EXT_TS (remove JP18) | only if a pack NTC is fitted |
| new | carrier PERMIT/P5 link, ILIM_REL | EVM /CE (stage A), ILIM_HIZ (stage B) | 26 AWG twisted with GND |

Comparator taps (26 AWG, <= 0.10 m): V-MOT at CAL+, VBUS at C-D2, BT_CURRENT at the pin-41 node, EN nets BT_BUS (28), REGEN
(30, J1.43/44), FC_CHARGE (31, J1.45/46), 3V3 (J1.29/30), GND.

| ID | Change | Evidence |
|---|---|---|
| M1 | Remove JP17 (stock /CE grounded = charging; POR charges at 1 A) | SLUUCB5E Table 1-3 p.5; SLUSDV2C Table 7-9 p.41 |
| M2 | Stage A: NMOS (BSS138/2N7002 class) drain on /CE, gate from the /CE-drive link via 1 kΩ, 100 kΩ + 10 nF to AGND | /CE VIH 1.3 V / VIL 0.4 V (EC p.16) |
| **M2b (new, P4)** | Re-bias the /CE pull-up (R42) from **REGN** instead of PULLUP | SLUSDV2C pin table "do not leave floating"; abs max 6 V (§6.1 p.7) |
| M3 | Stage B: R21 127k -> **121k** (JP14 fitted; R23 100k kept, value to be confirmed on the EVM); **Q3 NMOS + R_FC 158k ILIM_HIZ -> AGND, gate from buffered FCC_net (critic round)**; Q2 NMOS ILIM_HIZ -> AGND, gate 100 kΩ to REGN; Q1 pulls Q2 gate low from ILIM_REL (1 kΩ, 100 kΩ + 10 nF) | Eq.1 p.27; leakage ±1.5 µA (EC p.12) |
| M4 | Remove R39/R40 (I2C pull-ups to PULLUP) and JP32 (STAT LED) | Back-powering the Teensy |
| M5 | JP3 + JP4 installed, JP1 + JP2 to GND (2-3); feed J1 only. **Keep JP4 installed** (it ties VAC2 to VBUS, required with no ACFET2/RBFET2: "Connect to VBUS if the ACFET2 and RBFET2 are not installed", SLUSDV2C Table 5-1 p.5; §7.3.5.2) and **insulate or remove the J2 terminal block** (J2 is live through JP4). Do not remove JP4: VAC2 would float (critic round; design_BQ25798 M5 corrected) | SLUUCB5E Table 1-3 p.4 (JP3/JP4 "VINx/VACx to VBUS bypass"); SLUSDV2C Table 5-1 p.5, §7.3.5.2 p.30 |
| M6 | JP5 + JP8 1-2 (ship FET bypassed); JP9 2-3 (BATP at BAT pin) | Table 1-3 p.4 |
| M7 | C11, C12, C29-C31 (10 µF 25 V X5R) -> >= 35 V X7R; board C-D8/C-D10 -> 10 µF 35 V 1206 X7R | V-MOT 21.2-21.5 V measured; clamp 21.98-22.28 V |
| M8 (PROPOSAL) | 1.0 kΩ 0.25 W VBT (C-D12) -> VCHG | Keeps VCHG above RT1987 UVLO; ~1.2-1.7 mA pack drain (~41 mAh/day); see condition 4 |
| M9 | TS: J-NTC -> J7, remove JP18; else keep JP18; never rely on TS_IGNORE (reset by WD, Table 7-34) | - |
| M10 | Keep JP24 (2S, 1.5 MHz); read back CELL = 1h and PWM_FREQ = 0 (R29 6.04k in Fig 4-6 vs 6.20k in BOM) | Table 7-2 p.25 |
| M11 | Remove JP6, JP10, JP11 (D+/D-) | - |
| Board | Carrier (H1, BT_ACT, C7 network plus the NOT-P5 term (8 gates), FCC_net buffer for Q3, /CE link); VCHG-IN eFuse (condition 7, below) | - |
| **eFuse (critic round)** | In the VCHG-IN lead between the board pad and EVM J1: active current limit about 2.0-2.5 A (above the 1.72 A regen ceiling), current-limit response in µs and a latched or slow-retry fault so a VCHG-IN short or a charger input-to-output short never draws more than that from the bus or V-MOT; rated >= 30 V with OV at or above 24 V; its own soft-start must finish once at Run entry (always-powered, so it is not re-run per burst). Coordination: the 2.0-2.5 A limit is above the OC_FC latch (1.4 A single sample), so a VCHG-IN fault in an FC window will latch OC_FC -> State 99; that is acceptable (a firmware stop, not a boost death). The eFuse's job is to bound the fault current within µs so the boosts never see a dead short at bus level, and to hold the bus above UV_BUS for the fault duration (limit x fault time well inside the 20 ms dwell). TPS61288 peak switch current limit 12-15-17.1 A (SLVSFP3C EC p.6) protects the boost switch cycle by cycle but not the Death-5 hot-plug class. A plain fuse cannot meet this (ms-scale clearing at 2-10x rating). Part not selected: no eFuse primary is in the library, TODO(verify: candidate eFuse datasheet). A short of the board node itself (C-D8/C-D10) is upstream of the eFuse and remains covered only by the RT1987 SCP during soft-start (DS-00 §17.5) | - |
| CSV | pin 5 `MPPT_DISABLE` -> `CHG_ARM`; pin 6 `CHARGER_STAT` keeps its name, meaning inverts (LOW = charging); new pin 10 `CHG_QUAL` (OUT), pin 33 `CHG_PERMIT_RB`, pin 34 `CHG_H1_RB`, pin 16 `CHG_H2_RB` (IN) | CLAUDE.md: the CSV is authoritative |

### 4.3 Operating modes

Switch vector: FC_REG, BT_REG, FC_BUS, BT_BUS, MOT_PWR, REGEN, FC_CHARGE, BT_SEQ.

| Mode | Switches | P5 / QUAL | Charger | Loop barrier | Runaway bound |
|---|---|---|---|---|---|
| Reset / boot | all 0 (pull-downs) | high-Z (pulled down) | unpowered (or pack-powered via M8) | no input power | - |
| Init / Idle | 1 1 1 1 1 0 0 1 | 0 / 0 | static image, EN_CHG 0 | REGEN = FCC = 0 | - |
| **Run cruise, regen armed** | 1 1 1 1 1 **1** 0 1 | 1 / 0 | VINDPM 19.0 V, IINDPM 1.70 A (clamped to the regen ILIM 1.44-1.72 A), ICHG 2.50 A, EN_CHG 1 | H1q = 0 -> ILIM_HIZ LOW (converter off); VINDPM 18.62-19.38 V above bus max 17.2 V | converter off |
| **Regen burst** | as cruise | 1 / 0 | absorbing | D-MT-EN reverse-biased; H1q releases only then | self-limited; regen ILIM 1.44-1.72 A; ICHG 2.5 A; IBUS_OCP 7-9 A (EC p.9) |
| **FC window** | 1 1 1 **0** 1 **0** **1** 1 | 1 / 0 | VINDPM 13.5 V, IINDPM scheduled, ICHG 1.60 A | H2 | FC ILIM 0.74-0.96 A (R_FC in; see S1-B6 caveat); firmware I_fc arm drop 1.20 A; OC_FC |
| Finish / Run exit | -> Idle | 0 / 0 | EN_CHG 0 | P5 LOW first, then REGEN LOW | - |
| State 99 | phased open | **0 / 0 in phase 0** | EN_CHG 0 (best effort) | both pins inhibited, then paths open | - |
| Teensy hang | frozen | frozen | frozen | H1/H2 stages MCU-independent | ILIM; MCU WDT resets (future work) |

### 4.4 Transitions (ordered)

Invariants: (I-1) P5 LOW across every switch change; (I-2) a sub-bus VINDPM (13.5 V) written only with REGEN 0, BT_BUS 0, FCC 1;
the 19.0 V value written before FCC drops; (I-3) P5 rises only after readback of the full masked image and of REG06/REG19 ICO_ILIM
in the mode window (regen [1.40, 1.75] A; FC: the written value if <= the FC clamp, else the clamp, in [0.70, 0.98] A); (I-4) no transition while H1 = 1 except the pre-emptive brake-edge FC -> regen; (I-5) CHG_QUAL HIGH only with P5
LOW, from a REGEN/FCC close until PG_STAT = 1 + 50 ms (also enforced in hardware by `CHG_QUAL AND NOT P5`, critic round);
(I-6) poor-source recovery: if PG_STAT is still 0 about 300 ms after a REGEN or FCC close, or POORSRC_FLAG is set, keep P5
LOW, force a retry (EN_HIZ 1 -> 0, or a REGEN cycle) and set a harvest-lost flag; otherwise the charger retries only every
7 minutes (SLUSDV2C §7.3.4.2 p.27, §7.3.13.1.3 p.51).

| Transition | Order | Time |
|---|---|---|
| Run entry | P5 LOW; CHG_QUAL HIGH; REGEN HIGH (tD_ON 8 ms + ~1.3 ms ramp, RT1987 typical only; 0.84 A from CAL, refilled by both boosts); wait PG_STAT (REGN +150 ms, poor-source ~30 ms; I-6 if not set by ~300 ms); poll REG05 until the auto value lands and is stable 2 x 20 ms; CHG_QUAL LOW; write and read back the regen image + REG19; P5 HIGH | arm ≈ 0.25 s after REGEN |
| Regen -> FC | H1 = 0 check; P5 LOW; wait >= 1 ms; REGEN LOW (no unplug: VCHG-IN 70 µF falls at ~40-70 V/s, far above VBUS_PRESENTZ ~3.2 V); BT_BUS LOW (existing `assertFcChargeEnable()` order); wait RT1987 turn-off (measured, S0-M3); FC_CHARGE HIGH (warm, <= 0.6 V droop over the typical-only tD_ON); write + read back FC image; P5 HIGH | ≈ 10-20 ms |
| FC -> regen (brake edge) | P5 LOW; write + read back VINDPM 19.0 V / IINDPM 1.70 A / ICHG 2.50 A while still FC-powered (≈ 0.6 ms at 100 kHz); FC_CHARGE LOW; BT_BUS HIGH (share-loop guards) and REGEN HIGH in parallel; when pin 38 tracks pin 39 within 0.3 V re-verify, P5 HIGH | ≈ 10-12 ms; regen onset ≈ 5 ms after `I_cmd` < 0 -> condition 3 |
| Exit / State 99 | P5 LOW and CHG_QUAL LOW first; EN_CHG 0; REGEN (and FCC) LOW | - |

### 4.5 Registers (I2C 0x6B, 100 kHz; byte order self-checked at first read: REG01:02 = 0x03 0x48 = 8.40 V)

**Never write:** REG0A (CELL/TRECHG/VRECHG), REG16 (pull-downs), REG09 bit 6 REG_RST (always 0), OTG registers.

| Reg | Value | Meaning | Source |
|---|---|---|---|
| 0x00 | 0x04 | VSYSMIN 3.5 V | Table 7-14 p.59 |
| 0x01:02 | 0x03 0x48 | VREG 8.400 V; require <= 840 | Table 7-15 p.60 |
| 0x03:04 | mode | ICHG 10 mA/LSB (reset by WD -> 1 A per SLUSDV2C; SLUUCB5E Table 1-3 says 2 A for JP24 - predates the datasheet's Rev-B correction; S1-0 records the as-booted value; no safety bound relies on it) | Table 7-16 p.61 |
| 0x05 | 0xBE / 0x87 | VINDPM 19.0 V regen / 13.5 V FC | Table 7-17 p.62 |
| 0x06:07 | 0x00 0xAA / 0x00 0x5A | IINDPM 1.70 A regen (reads back as the ILIM clamp if lower, §7.3.4.3) / 0.90 A FC (critic round: was 0x7D = 1.25 A, which with the -12 % IINDPM tolerance could cap regen input near 1.10 A) | Table 7-18 p.63 |
| 0x08 | 0x03 | VBAT_LOWV 0h (15 % VREG: fast charge from VCHG ≈ 2.5-6 V); IPRECHG 120 mA | Table 7-19 p.64 |
| 0x09 | 0x25 | STOP_WD_CHG 1 (writability = S1-B5); ITERM 200 mA | Table 7-20 p.65 |
| 0x0E | 0x3D | timers (POR) | Table 7-24 p.69 |
| 0x0F | 0x02 / 0x22 | EN_AUTO_IBATDIS 0, EN_CHG 0/1, EN_ICO 0, EN_HIZ 0, EN_TERM 1, EN_BACKUP 0 | Table 7-25 pp.70-71 |
| 0x10 | 0x81 (kick 0x89) | VAC_OVP 0h (26 V), watchdog 0.5 s | Table 7-26 p.72 |
| 0x11 | 0x00 | AUTO_INDET_EN 0 (**reset by WD -> 1**; re-verify each plug-in) | Table 7-27 p.73 |
| 0x12 | 0x04 | EN_OTG 0, DIS_LDO 1 | Table 7-28 p.75 |
| 0x13 | 0x01 | ACDRV off, 1.5 MHz, EN_IBUS_OCP 1 | Table 7-29 pp.76-77 |
| 0x14 | 0x16 | EN_IINDPM 1, **EN_EXTILIM 1** (read each pass) | Table 7-30 pp.78-79 |
| 0x15 | 0xAA | EN_MPPT 0 | Table 7-31 p.80 |
| 0x18 | 0x54 | TS active | Table 7-34 p.83 |
| 0x2E-0x30 | 0xA0 0x08 0xF0 | ADC continuous, 13-bit, 6 channels ≈ 28 Hz | Tables 7-55..7-57 |

**Poll schedule** (20 ms frame, blocking <= 1.4 ms per slot at 100 kHz): status REG1B-21; critical verify REG00-0A; ADC
REG31-36 + REG41; WD kick (REG10 = 0x89), only in an iteration where `detectFaults()` and the 1 kHz interlock ran. On WD_STAT,
any masked mismatch, VBUS_PRESENT/PG change or flag, POORSRC_FLAG, or WD_STAT = 1 (the charger is in default mode after a POR or
watchdog expiry, SLUSDV2C §7.4.1 p.55): **P5 LOW first**, rewrite, verify, re-arm through the Run-entry steps. (The first
draft's "VREG = 8.40 V with ICHG = 1 A" POR signature is dropped: VREG 8.40 V is also the written value, and the ICHG default
conflicts between sources.)

**No-M8 sequence (P9):** without M8 the IC is unpowered in Idle. Run entry then writes the **full static image** after
PG_STAT = 1 (not before), with AUTO_INDET_EN at its POR value 1 for the first plug-in: D+/D- detection may add 0.5-2 s
(§7.3.4.5) and rewrite IINDPM, so arming waits for D+/D- completion (IINDPM_STAT/flags) before the write and readback. VAC_OVP
is at its POR value (7 V per SLUUCB5E §2.4.3) during that first qualification (bench S1-0b).

### 4.6 Quantitative checks

| Check | Result |
|---|---|
| Inrush, either path cold | 70.2 µF x 12.0 mA/µF = **0.84 A** for ~1.3 ms (RT1987 DS-00 §17.3, CSS 5.6 nF; tON typical only); REGEN-first at Run entry sourced by CAL; cold FC from FC-only bus 0.99 A -> forbidden |
| VINDPM - bus steady max (16.39 V) | **2.23 V** |
| VINDPM - 17.2 V transient | **1.42 V** |
| VINDPM - fw OV latch 17.5 V | **1.12 V** |
| VINDPM - TPS61288 OVP min 18.3 V | **0.32 V** (H1 covers a failed-FB boost) |
| H1 rise max - VINDPM min | **0.76 V** worst case (rise max 17.86 V at a 16.39 V bus incl. CMRR; the first draft's 0.79 V used the 17.83 V nominal) (absorption never chatters H1) |
| VESC cut (21.35 V) - V-MOT hold max (19.48 V incl. 0.10 V path drop) | **1.87 V** |
| VBUS_OVP min - design clamp max | **2.9 V**; to the 24 V recommended max **1.7 V** |
| Inhibit-latency allowance | **184 / 194 µs at 1.25 A, 158 / 167 µs at 1.40 A, 117 / 125 µs at 1.72 A** (VBUS 15.9 / 16.39 V; section 2.5; S1-B3). Supersedes the first draft's 320 µs |
| Regen input at the VINDPM floor | >= 23.5 W from the ILIM ceiling (incl. -12 % IINDPM tolerance); ICHG 2.50 A caps it at 20.3-23.1 W (7.4-8.4 V pack) |
| FC bus load after a charger POR (standstill) | <= 0.96 A + 0.15 A aux = 1.11 A (< 1.20 A arm drop, < 1.247 A P_MAX, < 1.4 A OC_FC) |
| Thermal | FC 1.6 A x 8.4 V at ~93 % -> ~1.0 W, TJ ≈ 70-75 °C (RθJA 44.2 °C/W, p.8); regen 2.1 W for <= 0.6 s |
| Pack at termination | 8.34-8.42 V (below OV_BATT 8.5 V) |
| FC standstill | 1.31-1.58 A charge, 0.89-1.05 A bus side (FC ILIM 0.74-0.96 A vs IINDPM 0.90 A) |

### 4.7 Runner-up delta (BQ25713EVM-017, `round2/design_BQ25713.md`)

| Item | BQ25713 design |
|---|---|
| Inhibit | ILIM_HIZ only (Hi-Z < 0.4 V, exit > 0.8 V, SLUSD83C p.18); Q_a hold-down gate pulled up from REGN (TP21), Q_b released by PERMIT; C7 network (six 74LVC1G gates) |
| Ceiling | Mode-switched by the FC_CHARGE net: regen 154k (1.80 A nominal, 1.33-2.28 A worst incl. ±0.2 A pin accuracy, p.12); FC 154k ∥ 324k (0.71 A, 0.30-1.13 A) |
| Registers | ChargeOption0 0x270F -> 0x270E; ChargeOption1 0x0210 (AUTO_WAKEUP 0, PTM 0); ChargeOption2 0x02B7 (EN_EXTILIM 1); ChargeOption3 0x0030; MaxChargeVoltage 0x20D0 (8.400 V); VINDPM 0x3DC0 / 0x2840 (19.008 / 13.504 V); IIN_HOST 0x2000 / 0x0600; ChargeCurrent 0x09C0 / <= 0x04C0; safety readback <= 170 ms |
| Mods | Remove C53 + three MLCCs (inrush 1.52 -> 0.77 A); C25 0.47 µF 16 V -> >= 35 V; R32/R35 off; AUTO_WAKEUP_EN = 0 before release |
| Decisive gates | B3 VINDPM retention across Hi-Z (failure disqualifies regen); B4b Hi-Z-exit warm response <= 4 ms from VCHG decayed below 6.144 V; B2 Hi-Z entry <= 275 µs at 1.6 A |
| Telemetry | 64 mA ICHG LSB; one-shot ADC ~10 ms (continuous refreshes every 1 s, p.50) |
| Stock | TI store USD 156.45, 38 in stock (2026-11-05) |

---

## 5. Required future work

### 5.1 MCU HARDWARE WATCHDOG (operator ruling 5) - REQUIRED before any unattended charger session

**Status:** absent in fw v37 rev 2 (grep finds only the Pi watchdog and a reset-reason string, ino ~9651). It is load-bearing
for the double-fault cases (comparator stuck + hang) and for overcharge with a hung MCU, more so because the BQ25798's own
watchdog cannot be cited until S1-B5 (P7). Primary source obtained this round: **NXP IMXRT1060RM Rev. 3, 07/2021** (PJRC
mirror, fetched 2026-11-05).

| Item | Specification |
|---|---|
| Primary timer | **RTWDOG (WDOG3)**, clock LPO_CLK or INTCLK = 32 kHz ("both LPO clock and INTCLK are 32 KHz clock generated by 32 KHz XTAL, which could be automatically switched to 32 KHz RCOSC upon XTAL clock loss", RM §58.1 p.3269). **TOVAL 3200 = 100 ms.** Pass-through range 1-65535 reference periods (2.048 s max at 32 kHz); prescaler 256 extends it (RM Table 58-2 p.3276). Refresh = 0xA602 then 0xB480; unlock = 0xC520 then 0xD928, then reconfigure within 128 bus clocks (RM Ch 58 refresh/unlock sections) |
| Secondary timer | **WDOG1 at 1.0 s** (WCR WT field: 0.5 s per step, 0.5-128 s; RM §57.8 WCR WT), independent of RTWDOG. **WDOG1_B must not be routed to pin 19 (SCL)**; pin 20 acceptable if a hardware WDOG_B is wanted (CSV first). Note the WDOG1 power-down counter (WMCR PDE = 1 at reset; software must clear it within 16 s of reset, RM §57.8.1.6 p.3267-3268) - TODO(verify: Teensy core startup clears PDE) |
| Optional | EWM output as an extra AND input to PERMIT so a hang drops the permit before the reset (polarity TODO(verify: RM EWM chapter)) |
| Feed policy | Exactly once per `loop()`, after `detectFaults()`, the 1 kHz interlock monitor and the switch writer have run in that iteration. Never from an ISR or timer. No feed inside blocking calls |
| Timeout sizing | 100 ms > longest legitimate stall; measure a loop-period histogram first. Known blocking paths: `EEPROM.update()` encoder-sign commit, SdFat `write/truncate/close`, charger I2C slots (<= 1.4 ms), Serial. Restructure or budget them (durations TODO(verify: PJRC)) |
| Reset behaviour | Cause from **SRC_SRSR** (0x400F_8008, RM §21.6.3 p.1276-1277): bit 7 `wdog3_rst_b` (RTWDOG), bit 4 `wdog_rst_b` (WDOG1). SRC_SCR `mask_wdog3_rst` must stay at its unmasked default 1010b (RM Ch 21). From reset until `setup()` the 10 kΩ EN pull-downs hold every RT1987 off (VEN_F min 0.6 V, DS-00 p.7) and the carrier 47 kΩ pull-downs hold P5/QUAL LOW. Pad keeper state during reset: TODO(verify: RM IOMUXC chapter, now available locally); PJRC boot time to `setup()`: TODO(verify: PJRC) |
| After a WDT reset | Boot to State 0; latch **ERR_MCU_WDT** (telemetry v5 bit); **require Pi or operator acknowledgement before Run**; re-bring-up through the staged bring-up and `assertMotPwrEnable()`/`motPwrHotPlugUnsafe()`; charger re-imaged with P5 LOW |
| Host test | Mock RTWDOG: no feed on any iteration that skipped `detectFaults()`; ERR_MCU_WDT latches and blocks Run until acknowledged |
| Bench proof (M6 / S3-W) | State-98 hang key spinning with P5, REGEN and BT_BUS HIGH. **Pass:** reset within 100 ms (+ clock tolerance); every RT1987 EN < 0.6 V within 1 ms of reset; PERMIT and ILIM_REL LOW; ERR_MCU_WDT reported after boot. Repeat with WDOG1 only (<= 1.0 s). Also force the hang inside an SD close and an EEPROM commit |

### 5.2 Firmware (`teensy_controller.ino`, fw v37 rev 2 tip)

| Area | Change |
|---|---|
| Pins (CSV first) | pin 5 `CHG_ARM`; pin 6 STAT semantics inverted; new pins 10, 16, 33, 34; never-rotated CLAUDE.md bodge record |
| Ag105 code removed | `pollAg105()`, `initAg105Charger()`, `ag105IsReady()`, the reg-0x02 MPPT ratchet and `N` key (~400 lines), GENSTAT latch, `AG105_ADDR`, `AG105_VBATN_ISOLATED` -> `CHG_RETURN_VERIFIED` |
| New driver | BQ25798 at 0x6B; static + mode images; masked verify; never-write list; WD kick policy; POR/WD re-image; non-blocking mode manager `chargerModeTick()` (one I2C transaction per tick); recommended follow-up: non-blocking LPI2C |
| Interlock | 1 kHz F1 cross-check of PERMIT/H1/H2 readbacks against pin 38/39/24-26 ADCs (requires V_rgn calibration, M-R2); I_BT above the boot-measured INA253 floor + margin (about 0.12 A at the datasheet maximum floor; not 50 mA, section 2.3) for 20 ms with BT_BUS LOW -> trip; FC-window power-balance cross-check (IBUS·VBUS + aux vs I_fc·V_bus) -> trip; poor-source recovery (invariant I-6) |
| Sequencer | Section 4.4 transitions incl. brake-edge FC -> regen (trigger on the command, condition 3) |
| `chargingControl()` | Regen arming no longer depends on `charge_goal` (ruling 1); FC windows under the governor; `FC_CHARGE_ALLOWED` (0 in fw v31-v37) re-enabled only after the purge ruling |
| Guards | G1 (bench session) 1.0 A / 5 ms; G1-Run: an armed burst must not raise I_fc + I_batt > 0.3 A over pre-burst; G2 with P_chg_in = IBUS x VBUS (REG31/REG35); G3 = REG20/21 faults + timer faults; EN_HIZ auto-set in Run -> harvest-lost flag; reboot-only trip latch |
| Faults | `FAULT_SWITCH_CONFLICT` out of `#if !BENCH_TEST`; new ERR_CHG_H_MISMATCH, ERR_CHG_PERMIT_STUCK, ERR_MCU_WDT; OV_BATT active in all builds |
| State 98 | `4` removed; new `J` = FC-path session; `V` = image/readback dump; `5` refuses a cold close in Run |
| State 99 | P5 and CHG_QUAL LOW in phase 0; delete the drain-into-charger phases |
| MCU WDT | Section 5.1 |

### 5.3 Telemetry / Pi bridge (protocol-bump skill, lockstep)

Proposed **v5 = 65 bytes** (design_BQ25798 §7.3): offset 19 `I_charge` = BQ25798 IBAT; offset 51 `charger_status` redefined
(CHG_STAT, PG, VINDPM/IINDPM_STAT, fault, image verified); new 57 `chg_in_ma` (int16), 59 `chg_vbus_mv` (uint16), 61 `chg_ctrl`
(ARM, PERMIT/H1/H2 readbacks, QUAL, FC mode, trip latch, WD seen), 62 `chg_fault` (REG20), 63 `chg_vindpm`, 64 checksum (XOR
1-63). The Pi bridge (`teensy_bridge_node_2026-10-31A.py` asserts 58 B and passes byte 51 through; its EKF treats `I_charge`
as battery-side) must change in the same commit series. BLG gains the same fields (BLG v10) by its own procedure.

### 5.4 Tests

- `test_main.cpp`: about 60 charger/MPPT/`J` tests (~1340 lines referencing Ag105 symbols) rewritten or deleted;
  `mock_wire.h` needs a register-addressed responder (the Ag105 status-byte-first protocol goes).
- New behavioural tests: invariants I-1..I-6 (incl. poor-source recovery and the harvest-lost flag); boot-time INA253 floor
  measurement and the derived I_BT threshold; power-balance cross-check; never-write list; masked verify and mismatch disarm; WD re-image; brake-edge
  transition; F1 cross-check; I_BT trip; P5 LOW on every stop path before serial; MCU WDT feed rule and ERR_MCU_WDT; the
  `FAULT_SWITCH_CONFLICT` in BENCH_TEST builds; v5 layout and checksum span.
- Run all three targets per CLAUDE.md §9 plus the encoder harness.

### 5.5 HIL / EMS

- `tools/hil_plant_sim.py`: replace the Ag105 threshold/MPPT model with a VINDPM-gated model behind H1, with the measured
  warm-response and latency once known, the mode-switched ILIM ceiling, and the poor-source behaviour (a failed
  qualification on a soft or sagging source sets EN_HIZ and retries after 7 minutes unless the firmware forces a retry); injection/observation frame fields with Ag105 semantics (injection `I_charge` @34,
  `ag105_status` @38; observation `mppt_thresh_count`) re-specified (`docs/HIL_MODE.md`).
- Charger efficiency `ETA_CHG` 0.88 (era key) -> measured BQ25798 figure; FC charge ceiling ≈ 1.6 A standstill and the
  traction-coupled budget; DP/SDP/MPC re-solves; lambda/alpha re-derived. The suite's charge/regen legs re-pinned.
- Regen research needs drive cycles with decels steeper than coast-down.

### 5.6 Hardware / documentation

- Never-rotated CLAUDE.md bodge records for: Ag105 removal + EVM; C-D8/C-D10 35 V; carrier and its taps; fuse; optional 100 nF
  CSS on D-BC-RG/D-BC-FC; M8 or a D-BT-SQ bridge if ruled.
- `docs/boost-bringup-debug.md` entries for every powered stage (bench-incident skill).

---

## 6. Bench go/no-go gates (in order) and what forces the re-spin

Scope-armed first power at every new stage (ruling 4). Gates are numbered as in `design_BQ25798.md` §9 plus round-2 additions
(marked *new*).

### 6.1 Track 0 - no purchase (week 0-1, on the vehicle)

| Gate | Test | Pass / fail |
|---|---|---|
| S0-R0 (M-R0) | State-98 `U` fault watch during a 2 -> 1 m/s, 12 A step decel; read VESC Tool Maximum Input Voltage, Fault Stop Time, fault log | Mechanism identified (OV fault + fault-stop yes/no); `l_max_vin` recorded |
| **S0-R3 (M-R3)** | CV electronic load at 19.0 V, 1.3 A limit, on V-MOT; hard decel | **GO** if braking continues with V-MOT held at 19 V for >= 0.25 s (2 -> 1 m/s). **NO-GO for regen** if the pulse still ends after 30-50 ms (at most ~20 mC, 0.17 J per decel for any charger) -> try raising `l_max_vin` (<= 23 V, with 35 V caps), else section 6.3 |
| S0-R1 (M-R1) | V-MOT capacitance | Known to ±20 %; sets τ limit (2 / 4 / 20 ms) |
| S0-R2 (M-R2) | Scope true V-MOT vs pin 39 at ~21 V | V_rgn ratio known to < 1 % (needed before F1 is trusted) |
| S0-M3 | RT1987 turn-off delay; whether UVLO recovery with EN high repeats tD_ON | Measured |
| S0-D | D-BT-SQ check after Ag105 removal is deferred to S4; operator ruling 4 accepts the board | - |
| **Ruling gate** | Conditions 2, 3, 4 ruled by the operator | Required before S4 |

### 6.2 Track 1 - EVM bench (weeks 1-3), FC-path subset first (P12)

| Gate | Test | Pass / fail |
|---|---|---|
| S1-0 | Power-up (from the pack via M8, or from VIN without M8): REG48, REG01:02 = 0x03 0x48, CELL = 1h, PWM_FREQ = 0; **read and record the as-booted ICHG (REG03:04), WD_STAT, PG_STAT, VBUS_PRESENT_STAT** (settles the 1 A / 2 A source conflict for this EVM); write + verify static image | All match; I2C at 100 kHz with 10 kΩ pull-ups; ICHG recorded (no bound relies on it) |
| **S1-0b** *new* | First qualification at VIN 16 and 21 V with VAC_OVP at POR (7 V) and VAC1/VAC2 tied to VBUS | Qualifies and switches; record VAC1_OVP flags; else firmware must write REG10 before first input (requires M8 or a pre-power path) |
| S1-B0 | /CE and ILIM_HIZ levels driven / floating / unpowered | /CE >= 2.9 V when not armed; ILIM_HIZ <= 0.2 V when not released (REGN up); 1.92-2.08 V released |
| S1-B1 | I(VIN) from stiff 15.9 and 18.5 V, VINDPM 19.0 V; inhibited and released | inhibited <= 1 mA; released <= 5 mA; IBAT = 0 ± 10 mA |
| S1-B2 | VINDPM retention over 1000 ILIM_HIZ/CE cycles and a 12 V dip | REG05 unchanged; PG kept; no EN_HIZ auto-set |
| **S1-B3** | Inhibit latency at 1.25 A in / 2.5 A charge: /CE alone, ILIM_HIZ alone; repeat on a regen -> motoring reversal | IBUS < 10 % within the section 2.5 allowance for the measured input current (**<= 115 µs** covers every case; 184 µs at 1.25 A / 15.9 V, 194 µs at 1.25 A / 16.39 V) for ILIM_HIZ (the per-burst pin in the default drive); both pins within 1 ms; bounded-pulse criterion on reversal |
| **S1-B4** (M-R4) | Warm step 18.5 -> 20.0 V, stiff source, **real RT1987 in the D-BT-SQ position**, VCHG below VBT at release; log BATOVP_FLAG, CHG_STAT (P2) | **τ63 <= 4 ms (10-90 % <= 9 ms)** or the S0-R1-derived limit at worst-case Vth; no BATOVP cycling; PG stays 1 |
| **S1-B4r** | Release ILIM_HIZ at 17.5 V and ramp to 20 V at 285 V/s | Switching <= 4.5 ms after release; 63 % ICHG <= 4 ms after V crosses 19.0 V |
| B4b | Current-limited source 0.3 / 0.7 / 1.2 A into 0.5 mF and 4 mF, VINDPM 19.0 V | V-MOT regulates 19.0 ± 0.3 V; never below ~16.8 V (H1 fall); no limit-cycling |
| S1-B5 | Charger WD 0.5 s, STOP_WD_CHG 1, stop kicking during 1.6 A charge | STOP_WD_CHG reads back 1; charging stops 0.4-1.0 s; **EN_CHG reads 0 after expiry** (P7) |
| S1-B6 | Qualification with CHG_QUAL in regen and in FC divider positions: REG06/REG19; repeat with ILIM held LOW; switch Q3 after qualification and read back; force a re-qualification with ILIM LOW mid-run (P6); measure IINDPM regulation at 19 V | Regen 1.44-1.72 A, FC 0.74-0.96 A; 0.10 A when qualified low; **record whether the pin is sampled once or continuously** (decides whether the FC ceiling binds outside a POR); IINDPM accuracy at 19 V within the -12 % assumed in section 3.3 |
| **S1-PS** *new (critic)* | Qualify on a soft source (series R so VBUS sags below VPOORSRC 3.3-3.5 V at IPOORSRC 7-20 mA) and on a source that dips during qualification | POORSRC_FLAG / EN_HIZ seen; firmware forces a retry and re-qualifies within 1 s once the source is good; harvest-lost flag raised; never waits the 7 minutes |
| **S1-B7** | 10 s cruise state (/CE HIGH, ILIM_HIZ LOW) then a burst; with and without M8; also /CE LOW + ILIM_HIZ LOW | Record VCHG (2.5 V hold expected with /CE HIGH, P1); first pack current <= 4 ms after release in the chosen configuration -> selects the /CE link and the condition-4 option |
| S1-B8 | 30 min FC charge 1.6 A at 15.9 V + 5 min 1 Hz bursts | TDIE < 100 °C; TREG_STAT 0 |
| S1-B9 | ADC vs shunt/DMM, DC, 50 ms pulses, burst integrals | Characterization (EMS accounting) |
| S1-C | CV/termination through the RT1987 stand-in | Pack 8.34-8.42 V; EN_CHG cleared at CHG_STAT 7h |
| S1-773 *new* | Same S1-B3/B4/B4r on the BQ25773EVM (FRC_CONV_OFF and ILIM_HIZ paths) | Comparative; decides the fallback if the BQ25798 fails B3/B4 |

### 6.3 Tracks 2-5 - Teensy control, failure injection, integration, regen

| Gate | Test | Pass / fail |
|---|---|---|
| S2-a..d | Sequences on emulated supplies; H1 trip sweep at VBUS 15.9/16.4/19.5 V **at the real ramp rates (3-4.3 V/ms falling, up to 287 V/s rising) to confirm the slow-ramp comparator delay against the 15 µs allocation**; H2 + C7 truth table (all combinations incl. FCC with H1 = 1); F1 with H1 stuck HIGH | Invariants hold; trips within section 2.2 worst case, hysteresis 0.25-0.35 V; truth table exact; F1 trip <= 6 ms |
| S3-a..f | Teensy reset; hang with P5 HIGH; SDA held LOW; comparator unpowered / output LOW / forced HIGH; carrier 3V3 removed; REG05 written 14 V while armed | IBAT = 0 or IBUS <= 5 mA as specified in design §9; disarm within 20 ms on mismatch |
| **S3-g** *new* | Brake during FC window with D-BT-EN shorted (P3); stray writes to REG0A/REG14/REG16; BT-current injection with BT_BUS LOW | No sustained bus-to-pack current; trip/inhibit in every case |
| **S3-h** *new (critic)* | Low-impedance VCHG-IN-to-GND short downstream of the eFuse, and a charger input-to-output short (VIN to VBAT through a low R), each at bus level in regen-armed cruise and in an FC window; scope I_fc, I_BT (INA253 outputs and current probes), VBUS, V-MOT | eFuse limits within µs at <= its rated limit; no boost damage; bus stays above UV_BUS for the fault or the firmware stops cleanly (OC_FC in an FC window acceptable); no hot-plug signature on restore |
| **S3-i** *new (critic)* | Force CHG_QUAL and P5 both HIGH with H1 = 0 and VINDPM at the plug-in auto value (below the bus), BT_BUS closed | ILIM_HIZ stays LOW; converter off; IBUS <= 5 mA |
| S3-W / M6 | MCU WDT (section 5.1); run once with P5, REGEN and BT_BUS HIGH and **once during a brake** | As specified; **required before any unattended session** (not a feasibility exit criterion) |
| S4-a | Power-on self-test each boot (FCC = REGEN = 0 -> V_chg decays, catching shorted D-BC-FC/D-BC-RG; V_rgn not tracking VBUS before MOT_PWR closes, catching a shorted D-MT-EN; Idle H1 = 0; BT_ACT = 0; **BT-channel INA253 zero-current floor measured and stored as the I_BT trip base**); D-BT-SQ check (Ag105 removed, BT_SEQ HIGH, VCHG floating ≈ 0 V into 1 kΩ) | Pass every boot |
| S4-b | Run with regen armed, cruise 60 s at 0.5-1.5 m/s | IBAT = 0 ± 20 mA; I_batt, I_fc unchanged vs fw v37 ± 50 mA; no G1/G2/G3 |
| S4-c | Warm FC transitions at standstill, 20 cycles; inrush scope incl. REGEN-first cold close, a warm D-BC-FC re-close at 0.5-2 V deficit, and **a D-BC-RG re-close after a reverse-current (TRCB) trip, which restarts without soft-start** (RT1987 DS-00 §17.4 Table 1) | I_fc peak < 1.2 A; no OC_FC, no UV_BUS; charge 1.31-1.58 A (FC ILIM tolerance); TRCB re-close peak recorded and within the H8 1.0 A budget |
| **S4-n** *new (critic)* | Converter at full regen current and at full FC current, 10 min each: count spurious H1/H2/BT_ACT/PERMIT transitions; ADC noise on pins 24-26, 38, 39, 41; F1 and G-guard trips | Zero spurious permit transitions and zero false F1/G1-G3/power-balance trips; ADC noise recorded and below the F1/guard thresholds with margin; V-MOT ripple at H1 recorded |
| **S4-H20** *new* | FC window on a **running H-20** with the ruled purge-tolerant topology | No UV_BUS / UV_FC latch; I_fc <= 1.20 A with charger + traction |
| S5-a | 2 -> 1 m/s at 5 A then 12 A, 10 each | V-MOT holds 18.7-19.5 V; no second pulse at +0.53 s; **captured >= 80 % of the S0-R3-predicted energy**; no bus current rise (G1-Run) |
| S5-b | 3 -> 1 m/s, 12 A | Same; IBAT <= 2.5 A; no rise to 21.35 V |
| S5-c | VESC abrupt stop mid-burst | Bus pulse into V-MOT <= I_in x (t_inh - t_allow), t_allow from section 2.5 at the measured I_in |
| S5-d | Drive cycle with steep decels + an FC window | EMS sees I_charge per event; no trip |

**Exit criteria for "Path A fully feasible" (extended in the critic round):** S0-R3, ruling gate, S1-0b, S1-B1, S1-B2, S1-B3,
S1-B4/B4r, S1-B5, S1-B6, S1-B7, S1-C, S1-PS, S3-all (incl. S3-g, S3-h, S3-i), S4-c, S4-n, S4-H20, S5-a and **S5-b** (the
3 -> 1 m/s, 12 A brake that defines the HR1 pass condition) pass. **S3-W gates unattended operation only** (ruling 5); it is
required future work, not a feasibility criterion.

### 6.4 Results that force the re-spin (Path B), or end Path A as a regen solution

1. **S0-R3 fails** and raising `l_max_vin` to <= 23 V does not restore sustained braking: no charger on the Ag105 pads can meet
   HR1 (a VESC/drivetrain change, not necessarily a PCB change, but it ends Path A as a regen solution).
2. **Warm response (or inhibit exit + warm) exceeds the measured τ budget on the BQ25798, BQ25773 and BQ25713**, and the VESC
   cut-off cannot be raised to buffer the gap: a re-spin with a dedicated fast regen sink on V-MOT.
3. **Inhibit latency fails on every candidate** and the operator does not accept the bounded-pulse interpretation.
4. **No purge-tolerant FC-window topology is acceptable** (BT hot standby rejected, hold-up capacitance does not fit or worsens
   inrush, purge synchronisation unreliable): FC charging on a running stack needs a different bus/sequencing topology.
5. **The hand-wired carrier shows coupled-glitch permit releases, ground-shift faults or unreliable rework** in S3.
6. **D-BT-SQ** proves reversed or incident-damaged and cannot be reworked in place.
7. **The EMS needs regen and FC charging concurrently**, the operator keeps CSV row 31 and rejects brake-command holds.

**Path B costs (round-1 estimates, not re-derived in round 2; `path_b_respin.md`):**

| Option | Time | Cash | Firmware/HIL/EMS | Notes |
|---|---|---|---|---|
| B1 minimal re-spin (new charger IC with its own BATFET, BAT on the pack, all bodges folded in, BQ29200 OUT -> hardware charge inhibit, >= 35 V input caps) | first safe charge weeks 8-14 | ~USD 1-2k for 5 boards | ~23-37 eng-days | Under the round-2 rulings B1 must also carry the H1/H2 interlock on-board and a purge-tolerant FC path; re-estimate |
| B2 bidirectional pack-to-bus converter | 5-9 months integrated | ~USD 2-4k | ~63-95 eng-days + campaigns | Removes the loop hazard by construction; retires the droop-share platform (operator exception to "What NOT to change") |

---

## 7. Parts, stock, cost, schedule

**Stock:** TI store inventory endpoint (`ti.com/storeservices/cart/opninventory?opn=...`, plain curl), 2026-11-05 17:25-20:02
UTC. Non-TI stock UNKNOWN (Mouser DNS-blocked / HTTP/2 errors; Farnell timeouts; DigiKey 403).

| Part | Qty | Unit | Stock (TI) | Note |
|---|---|---|---|---|
| **BQ25798EVM** | 2 | USD 156.45 | 162 | one modified, one characterization/spare |
| **BQ25773EVM** | 1 | USD 199.00 | 95 | parallel stage-1 hedge (P11) |
| BQ25713EVM-017 (optional) | 1 | USD 156.45 | 38 | only if the operator wants the runner-up characterized concurrently |
| TLV3012BIDBVR / BIDCKR | 2 + 2 | ~USD 1, TODO(verify: price) | 27 694 / 144 621 | H1, BT_ACT |
| SN74LVC1G27DCKR | 1 + 1 | - | 1 050 765 | NOR3 |
| SN74LVC1G08DCKR | 3 + 1 | - | 863 376 | AND (C7 adds one) |
| SN74LVC1G32DRLR | 2 + 1 | - | 937 821 (DBVR only 54) | order DRLR |
| SN74LVC1G04 / 1G11 | as needed for C7 | - | 421 236 / 36 150 | per design_BQ25713 network |
| BSS138 / 2N7002 SOT-23 | 4 + spares | - | UNKNOWN | stages A/B |
| 0.1 % resistors 499k, 464k, 56.2k x2; 6.49M; 61.9k; 1.00k | 2 sets | - | UNKNOWN | - |
| 10 µF >= 35 V X7R 0805 (EVM) / 1206 (board C-D8, C-D10) | 5 + 2 + spares | - | UNKNOWN | - |
| eFuse for VCHG-IN (active limit ~2.0-2.5 A, >= 30 V, µs response) | 1 + 1 | - | UNKNOWN | condition 7; part not selected, TODO(verify: eFuse datasheet) |
| SN74LVC1G04 + SN74LVC1G08 (NOT-P5 term) | 1 + 1 each | - | see rows above | critic round |
| Q3 NMOS + 158k, 121k 1 % (mode-switched ILIM) | 1 set | - | UNKNOWN | critic round; R21 121k replaces the 150k |
| 1.0 kΩ 0.25 W (M8) | 1 | - | - | pending ruling |
| Wire, perfboard / small carrier PCB | - | - | - | - |

**Cost:** EVMs USD 511.90 (2 x BQ25798 + 1 x BQ25773), +USD 156.45 optional BQ25713; parts ~USD 40-70; optional carrier PCB ~USD
30. **Total ≈ USD 580-620** (≈ USD 740-780 with the optional runner-up EVM).

**Schedule (estimates, one engineer):**

| Step | Duration | Cumulative |
|---|---|---|
| Track 0: M-R0..M-R3, S0-M3; operator rulings; order parts (parallel) | 2-3 bench days + 3-7 days lead | week 1 |
| EVM mods + carrier build | 2-3 days | week 2 |
| Track 1 S1 (FC subset first, then regen gates; BQ25773 in parallel) | 4-6 bench days | week 3 |
| Firmware round (driver, mode manager, interlock, guards, v5, tests; orchestrated) | 2-3 weeks (overlaps) | weeks 2-5 |
| MCU WDT (section 5.1) | +1 week | before unattended use |
| S2-S3 | 3-4 days | week 5-6 |
| S4 (FC windows at standstill first) | 2-3 days | week 6 |
| S4-H20, S5 regen | 2-3 days | **≈ week 6-7** |
| HIL plant + EMS re-derivation + one campaign | 7-10 days + campaign | after S5 |

Firmware/HIL/EMS effort estimate: round 1's ~20-29 eng-days assumed a charger with its own watchdog and per-burst gating; the
interlock monitor, sequencer, v5 protocol, MCU WDT, HIL charger model and test rewrite raise it to **about 30-45 eng-days**
(UNVERIFIED estimate). **FC-charging data can arrive around week 4-6** (H2 + governor + purge ruling, standstill windows) before
regen data (P12). The Ag105 stays fitted until stage 1 passes.

---

## 8. Open questions and missing primaries

### 8.1 Operator decisions

1. FC-window purge topology (condition 2: hot standby / hold-up / synchronisation).
2. Brakes inside FC windows (condition 3: command hold <= 15 ms / standstill-only windows / combined mode with a CSV row-31
   change).
3. D-BT-SQ disposition (condition 4: M8 + P5 /CE / bridge + fuse / PERMIT-on-/CE if S1-B7 allows). M8 costs ~41 mAh/day.
4. Whether to raise VESC `l_max_vin` (after M-R0), with C-D8/C-D10 >= 35 V.
5. Buy the optional BQ25713EVM in parallel (USD 156.45)?
6. Pack datasheet: maximum charge current, protection board, capacity (the 5 Ah used in the EMS sizing is unverified), NTC. It
   now also decides whether ICHG may exceed 2.50 A (>= 2.83 A needed for 23 W regen input at a 7.4 V pack), or whether HR1 is
   restated at about 20 W (critic round).
7. Accept that FC charging is standstill-weighted under the current rules.
8. The FC-window loop residual: accept a bounded loop below the BT_ACT trip (<= 0.29 A, D-BT-EN shorted) if the boot-measured
   INA253 floor and the power-balance cross-check cannot reach below it (section 2.3).

### 8.2 Missing primaries (operator to fetch by hand)

| Document | Why | URL / where |
|---|---|---|
| **Pack datasheet and protection-board details** (maximum charge current, protection-board OV/OC thresholds and delays, capacity, NTC) | Sets the ICHG ceiling (2.50 A today, 2.83 A for HR1 at 23 W), the HR1/HR4 bounds and the EMS capacity; listed in round 2 only as an operator decision (critic round) | Pack vendor / label on the vehicle pack |
| eFuse candidate datasheet (VCHG-IN, condition 7) | Current-limit level, response time, fault mode, ratings | TI / vendor product pages |
| TI E2E / FAE answers: BQ25798 /CE and ILIM_HIZ entry/exit latency in buck mode, IINDPM regulation accuracy at VBUS 19 V, whether the ILIM_HIZ pin is re-read after qualification, ICHG POR default on the EVM (1 A vs 2 A), VINDPM loop bandwidth out of saturation, ADC accuracy, watchdog accuracy at 0.5 s, REGN-on HIZ VBUS draw, BAT behaviour with /CE HIGH and a 1 kΩ-fed "battery", STOP_WD_CHG / EN_CHG contradiction, VAC_OVP POR value, ILIM_HIZ sampling (once vs continuous) | Decisive for HR1 and HR5 (not in SLUSDV2C) | https://e2e.ti.com/support/power-management-group/power-management/ (BQ25798 forum) |
| Same questions for BQ25773 (HIZ / FRC_CONV_OFF exit, VINDPM loop, ADC_IBAT accuracy) and BQ25713 (Hi-Z latency, VINDPM retention across Hi-Z/ACOV/WD, Hi-Z quiescent) | Parallel candidate / runner-up | TI E2E as above |
| VESC Six EDU hardware config (`hw_*.h` for the EDU: HW_LIM_VIN, input capacitance) and the as-configured `l_max_vin`, fault-stop time, fault log | Confirms the 21.35 V cut mechanism | https://github.com/vedderb/bldc (hwconf); VESC Tool on the vehicle; Trampa product page https://trampaboards.com |
| PJRC Teensy 4.1: pad state during reset, boot time to `setup()`, Wire timeout API, EEPROM commit and flash-erase durations, whether the core clears WDOG1 PDE | MCU WDT sizing, fail-safe pad state | https://www.pjrc.com/teensy/ (forum / core source https://github.com/PaulStoffregen/cores) |
| Richtek RT1987: turn-off delay, UVLO-recovery tD_ON with EN high, tON min/max, OVP recovery inconsistency | Transition timing, D-BT-SQ warm path | https://www.richtek.com/ (RT1987 product page; DS-00 is the copy in hand) |
| BSS138 / 2N7002 (Vgs(th), Ron at 3.3 V gate drive) | Stages A/B | https://www.onsemi.com/pdf/datasheet/bss138-d.pdf ; https://www.onsemi.com/pdf/datasheet/2n7002-d.pdf |
| MLCC DC-bias curves: TDK C2012X5R1E106K125AB (BQ25798EVM input), Murata GRM21BR61E106KA73L (BQ25713EVM), GRM21BR61H106KE43L (BQ25773EVM), TDK C3216X7R1V106K (C-D6/C-D7), replacement for C-D8/C-D10 | Effective input capacitance / inrush | https://product.tdk.com/ ; https://ds.murata.co.jp/simsurfing/ |
| Panasonic EEE-FN1V471UP capacitance tolerance | V-MOT capacitance estimate | https://industrial.panasonic.com/ |
| Infineon BSP170P SOA | Chopper if the VESC cut-off is raised | https://www.infineon.com/ (BSP170P) |
| TL431 datasheet (TI) | Chopper clamp tolerance (only the BOM ±0.5 % cited) | https://www.ti.com/lit/ds/symlink/tl431.pdf |
| EVM mechanical outlines (BQ25798EVM, BQ25773EVM, BQ25713EVM-017 design files) | Mounting | https://www.ti.com/tool/BQ25798EVM ; https://www.ti.com/tool/BQ25773EVM ; https://www.ti.com/tool/BQ25713EVM-017 |
| Distributor stock / price / lead time for all EVMs and the non-TI parts | H11 for non-TI parts | https://www.mouser.com ; https://uk.farnell.com ; https://www.digikey.com (all unreachable from this session) |
| Only if those candidates return: MP2759A DS (https://www.farnell.com/datasheets/3632066.pdf), EV2759A-Q-00A (https://www.mouser.com/pdfDocs/EV2759A-Q-00A.pdf), BQ25723 DS, BQ25792 DS SLUSDG1, Mikroe Charger 25 Click | - | as given |

**Closed this round (previously missing):** NXP IMXRT1060RM Rev. 3 (watchdog chapters, SRC_SRSR) via the PJRC mirror
https://www.pjrc.com/teensy/IMXRT1060RM_rev3.pdf; VESC default fault-stop time (500 ms, `mcconf_default.h`); INA253 offset (±15 mA
max, and Swing to GND +10 mV max; local repo copy `references/Datasheets/INA253A1IPWR.pdf`, SLOS954A §7.5); TI LM3480 (30 V operating / 35 V abs max, SNVS011H); SN74LVC1G08/11/27/32/04 thresholds; all candidate datasheets and EVM
guides listed in section 9.

### 8.3 Open technical questions (bench)

V-MOT peak above 21.4 V; V-MOT ripple at H1 (S4-n); FC-mode aux and droop budget; INA253 BT channel zero-current floor on this
board (up to 10 mV = 0.1 A per SLOS954A §7.5; sets the BT_ACT margin and the firmware trip; S4-a); Teensy reset pad state on pins 5, 9, 10; whether D-BT-SQ repeats tD_ON leaving UVLO; the 0.85x V_rgn
reading (gain vs offset).

---

## 9. Sources

**Board and repo:** `references/Scale_Car_Board_20260624.sch`; `references/Scale Car Board PCB 20260625.brd`;
`references/Scale Car Design PCB BOM 20260622.csv`; Teensy IO CSV; `teensy_controller/teensy_controller.ino` fw v37 rev 2;
`docs/boost-bringup-debug.md`; `logs/ML0227.BLG` and the BLG/rosbag set in `round2/regen_dynamics.md` §1;
`docs/fw37_planning_2026-11-04.md`; `docs/reviews/fw36_regen_2026-11-04/`; `docs/fw30_fc_purge_uv.md`;
`references/EMS/Pi_2026-11-03/teensy_bridge_node_2026-10-31A.py`.

**Board-side datasheets (primary):** Silvertel Ag105 DS V1.1 (Nov 2021); Richtek RT1987 DS-00 (EC p.7; §17.3 tON; §17.4 Table 1;
§17.5 SCP; §17.6 reverse blocking); TI TPS61288 SLVSFP3C (VOVP 18.3/19/19.5 V, p.6); TI bq29200 SLUSA52C (p.1, p.5); TI LM3480
SNVS011H; TI INA253 **SLOS954A** (repo copy `references/Datasheets/INA253A1IPWR.pdf`; §7.5: I_OS ±2.5 mA typ / ±15 mA max,
Swing to GND VGND + 1 mV typ / + 10 mV max).

**Candidate primaries (read this round):**
- TI BQ25798 **SLUSDV2C** (rev June 2026); BQ2579xEVM **SLUUCB5E** (rev July 2022).
- TI BQ25713 **SLUSD83C**; BQ25713B datasheet; BQ2571x EVM **SLUUBT8B**.
- TI BQ25773 **SLUSEK7** (Sep 2024); BQ25770G datasheet; BQ2577xEVM **SLUUCY2** (Nov 2023).
- TI BQ25720 **SLUSDU3**; BQ25720/23 EVM **SLUUC74**.
- TI BQ25731 **SLUSE66A**; BQ2573x EVM **SLUUCB9A**.
- TI BQ25756 **SLUSEN5A**; BQ25756E **SLUSFF4A**; BQ25756EVM **SLUUCT7D**; BQ25756EEVM **SLUUCY5A**.
- TI BQ24650 **SLUSA75B**; BQ24650EVM **SLUU444A**.
- ADI LTC4015 datasheet **Rev B (4015fb)**; DC2039A Demo Manual **Rev D** (schematic Rev 5).
- MPS MP2759 datasheet **Rev 1.0 (11/30/2020)**; EV2759-Q-01A **Rev 1.0 (12/7/2020)**.
- TI TLV3011/3012 **SBOS300C**; SN74LVC1G08 **SCES217A(A)**, 1G11 **SCES487I**, 1G27 **SCES488E**, 1G32 **SCES219W**, 1G04
  **SCES214A**, 1G00.
- Also in the library (screened): BQ24800, BQ25672 + SLUUCF3, BQ25750, BQ25758, BQ25820 + SLUUD36, ISL9241.

**MCU / VESC:** NXP **IMXRT1060RM Rev. 3, 07/2021** (Ch 21 SRC §21.6.3 SRC_SRSR p.1276-1277; Ch 57 WDOG1-2 incl. §57.8.1.6
WMCR p.3267-3268 and WCR WT; Ch 58 RTWDOG §58.1 p.3269, Table 58-2 p.3276); tonton81 WDT_T4 library source (not an NXP primary;
`round2` analysis only); vedderb/bldc `motor/mcconf_default.h` (master, fetched 2026-11-05: `MCCONF_M_FAULT_STOP_TIME` 500 ms
line 546; `MCCONF_L_MAX_VOLTAGE` 57 V lines 62-63).

**Stock/price:** TI store opninventory endpoint and tool-page `data-price`, 2026-11-05 17:25-20:02 UTC.

**Working material (`docs/reviews/charger_eval_2026-11-05/`):** round 1: `spec.md`, `incident.md`, `firmware_impact.md`,
round-1 dossiers, `mockup_*`, `path_b_respin.md`. Round 2 (`round2/`): `loop_analysis.md`, `regen_dynamics.md`,
`dossier_{BQ25798,BQ25713,BQ25773,BQ25720,A2 (BQ25731),LTC4015,A1 (BQ25756),BQ24650,MP2759}.md`, `design_BQ25798.{md,svg}`,
`design_BQ25713.{md,svg}`, `figs/fig1-4`, `calc/` (capsim, comp_calc, taumax, ilim_calc_bq25713).

---

## Appendix A. Round-1 content superseded by round 2

| Round-1 statement | Status |
|---|---|
| Regen capture has "demonstration value" | **Void** (ruling 1) |
| R3: the bus must never feed the charger in Run; three-layer interlock with the charger threshold as layer 2 | **Superseded** by HR3-HR5 and the always-powered design (ruling 3) |
| Ranking LTC4015 #1, BQ25713 #2, BQ25798 #3 (practical lens "refuted") | **Superseded**: BQ25798 chosen, BQ25713 runner-up, BQ25773 alternate; LTC4015 plausible but ranked below (no host WDT, 2-4 s detect, availability) |
| Regen cold-start target <= 30 ms / <= 100 ms hard | **Superseded**: cold start never works (VESC trips in 19-47 ms); warm τ <= 4 ms is the requirement |
| "~0.7 J per decel" regen value | **Superseded**: 0.13-1.17 J reaches the node today; 1.8-5.5 J into the pack is available if the VESC keeps braking |
| Candidate numbers tagged [REC]/[snip]; gate G0 | **Closed**: primaries read; numbers replaced by citations |
| "TI NVDC parts all reset VINDPM to VBUS - 1.28 V" | **Corrected**: BQ25713/20 yes; BQ25798 VBUS0 - 1.4 V; BQ25773 fixed 3.2 V |
| BQ25731/BQ25756 screened out (stock / "oversized") | **Corrected**: both evaluated in round 2 (BQ25731 in stock per TI page; BQ25756 2.5 A settable); neither ranks above the finalists |
| Stage 0 damage checks before integration | **Considered passed** (ruling 4); the D-BT-SQ reverse-blocking check remains a one-minute item at S4-a |
| Path A' (bridge D-BT-SQ) by ruling only | Retained as condition-4 option (ii), now with a required fuse |
| Round-1 bench plan (G0, S0-S3) | **Superseded** by section 6 |
| Round-1 screened-and-rejected list (BQ24610, BQ24630, LT3652, XL4015/LM2596 low-side-shunt modules, etc.) | **Still valid**; see the round-1 revision of this file in git history and `spec.md` |
